"""Conversation Metrics service (Phase 6 / P6AN-04).

AI 对话质量与效率指标 (conversation quality & efficiency).

``GET /api/v1/analytics/conversations`` aggregates, over a time ``range``
and optional ``agent_id`` / ``intent_type`` / ``channel`` (platform)
filters, the five headline metrics defined by the card:

    avg response time       user→assistant gap (mean, seconds)
    conversation rounds     user-role messages / conversations
    intent recognition rate PROXY  (no ground-truth labels in V1)
    human handoff rate      conversations carrying an escalating intent
    satisfaction rate       PROXY  positive-sentiment / with-sentiment

plus per-dimension breakdowns: by platform (channel), by agent, by intent.

Design (repo conventions — API → service → data layer)
-------------------------------------------------------
- All heavy aggregation happens **in the database** through a shared
  ``sc`` (scoped-conversations) CTE reused by each metric subquery. No
  10k-UUID IN-lists are ever materialised in Python, so the P95 < 500ms @
  10k-conversations target holds: the plan is a handful of indexed scans /
  hash aggregates, not per-row Python work.
- The raw numbers come back as a plain dict from one headline query plus
  three breakdown queries (all parameterised ``text()`` — no user value is
  ever spliced into SQL; the escalating-intent set is expanded to fixed
  bind params, never string-interpolated).
- :meth:`_assemble` is a **pure** function from ``(raw, filters, window,
  threshold)`` → ``ConversationMetricsResponse``. It is unit-tested in
  isolation (no DB) and is the single place division-by-zero is guarded,
  so the "empty data returns safe defaults" acceptance criterion is
  explicit and testable.

Range semantics: the window bounds ``conversation.created_at``
(conversations that *started* in the range). Default window is the last 30
days; ``range`` accepts ``1d`` / ``7d`` / ``30d`` / ``90d`` / ``365d``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.conversation_metrics import (
    AgentMetric,
    ConversationMetricsResponse,
    DEFAULT_INTENT_ACCURACY_THRESHOLD,
    ESCALATING_INTENT_TYPES,
    IntentMetric,
    PlatformMetric,
)

logger = logging.getLogger(__name__)

# Allowed ``range`` values → seconds. Anything else falls back to 30 days.
_RANGE_SECONDS = {
    "1d": 86_400,
    "7d": 7 * 86_400,
    "30d": 30 * 86_400,
    "90d": 90 * 86_400,
    "365d": 365 * 86_400,
}
_DEFAULT_RANGE = "30d"
_BREAKDOWN_LIMIT = 100


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Zero-safe ratio: numerator / denominator, or 0.0 when denominator is 0."""
    return (numerator / denominator) if denominator else 0.0


class ConversationMetricsService:
    """Computes AI conversation quality & efficiency metrics (P6AN-04)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ #
    # window resolution (pure, unit-testable)
    # ------------------------------------------------------------------ #
    @staticmethod
    def resolve_range(range_value: Optional[str], now: datetime) -> tuple[datetime, datetime, str]:
        """Resolve a ``range`` token to ``(start, end, label)`` aware-UTC.

        ``end`` is clamped to ``now``; the window is the trailing N seconds
        implied by the token. Unknown tokens fall back to the 30-day default.
        """
        token = (range_value or _DEFAULT_RANGE).strip().lower()
        if token not in _RANGE_SECONDS:
            token = _DEFAULT_RANGE
        seconds = _RANGE_SECONDS[token]
        end = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        start = end - timedelta(seconds=seconds)
        return start, end, token

    # ------------------------------------------------------------------ #
    # public entry point
    # ------------------------------------------------------------------ #
    async def compute(
        self,
        *,
        agent_id: Optional[UUID] = None,
        range_value: Optional[str] = None,
        intent_type: Optional[str] = None,
        channel: Optional[str] = None,
        threshold: float = DEFAULT_INTENT_ACCURACY_THRESHOLD,
        now: Optional[datetime] = None,
        account_id: Optional[UUID] = None,
    ) -> ConversationMetricsResponse:
        """Compute conversation metrics for the given scope.

        P6AN-16: when ``account_id`` (the caller's tenant, from the token) is
        set, conversations are restricted to the tenant's own customers, so a
        tenant can never read another tenant's conversation quality data.

        Never raises on empty scope — returns a response with
        ``has_data=False`` and all-zero / empty-safe metrics.
        """
        now = now or datetime.now(timezone.utc)
        start, end, window_label = self.resolve_range(range_value, now)

        sc, sc_params = self._scoped_cte(start, end, agent_id, intent_type, channel,
                                          account_id=account_id)
        # base_params carries the window + filter binds for the shared CTE plus
        # the threshold; _params() layers the escalating-intent binds on top.
        base_params = {**sc_params, "threshold": threshold}

        raw = await self._query_headline(sc, base_params)
        by_platform_rows = await self._query_by_platform(sc, base_params)
        by_agent_rows = await self._query_by_agent(sc, base_params)
        by_intent_rows = await self._query_by_intent(sc, base_params)

        filters = {"agent_id": str(agent_id) if agent_id else None,
                   "account_id": str(account_id) if account_id else None,
                   "intent_type": intent_type, "channel": channel}
        window = {"start": start.isoformat(), "end": end.isoformat(), "window": window_label}
        return self._assemble(raw, by_platform_rows, by_agent_rows, by_intent_rows,
                              filters=filters, window=window, threshold=threshold,
                              agent_id=agent_id, intent_type=intent_type, channel=channel)

    # ------------------------------------------------------------------ #
    # SQL construction (shared scoped CTE)
    # ------------------------------------------------------------------ #
    def _scoped_cte(self, start, end, agent_id, intent_type, channel,
                    account_id: Optional[UUID] = None) -> tuple[str, Dict[str, Any]]:
        """Build the shared ``sc`` CTE and its bind params.

        Filter clauses are added **conditionally** so a NULL filter value is
        never bound into the SQL. asyncpg (the live driver) cannot infer the
        type of a bare ``NULL`` bind (``AmbiguousParameterError``), so we
        simply omit the clause and its bind instead of writing the
        ``(:x IS NULL OR ...)`` pattern. The time window is always present
        (``start``/``end`` are concrete datetimes).

        P6AN-16: ``account_id`` (the caller's tenant) adds an EXISTS clause
        restricting conversations to customers served by the tenant's own
        agents (via ``agent_persona_binding`` -> ``agent_customer_binding``).
        """
        where = [
            "c.is_deleted = false",
            "c.created_at >= :start",
            "c.created_at < :end",
        ]
        params: Dict[str, Any] = {"start": start, "end": end}
        if channel is not None:
            where.append("c.channel = :channel")
            params["channel"] = channel
        if agent_id is not None:
            where.append(
                "EXISTS (\n"
                "    SELECT 1 FROM agent_customer_binding acb\n"
                "    WHERE acb.customer_id = c.customer_id\n"
                "      AND acb.agent_id = :agent_id\n"
                "      AND acb.is_deleted = false)"
            )
            params["agent_id"] = agent_id
        if intent_type is not None:
            where.append(
                "EXISTS (\n"
                "    SELECT 1 FROM intents i\n"
                "    WHERE i.conversation_id = c.id\n"
                "      AND i.intent_type = :intent_type\n"
                "      AND i.is_deleted = false)"
            )
            params["intent_type"] = intent_type
        if account_id is not None:
            # P6AN-16: tenant scope — conversations only for customers served
            # by this account's own agents.
            where.append(
                "EXISTS (\n"
                "    SELECT 1 FROM agent_customer_binding acb\n"
                "    WHERE acb.customer_id = c.customer_id\n"
                "      AND acb.is_deleted = false\n"
                "      AND acb.agent_id IN (\n"
                "          SELECT apb.agent_id FROM agent_persona_binding apb\n"
                "          WHERE apb.account_id = :account_id))"
            )
            params["account_id"] = account_id

        where_sql = "\n    AND ".join(where)
        sc = (
            "sc AS (\n"
            "  SELECT c.id, c.customer_id, c.channel, c.sentiment, c.duration_seconds\n"
            "  FROM conversation c\n"
            f"  WHERE {where_sql}\n"
            ")"
        )
        return sc, params

    def _params(self, base: Dict[str, Any]) -> Dict[str, Any]:
        """Base (agent/intent/channel/threshold) + the fixed escalating-intent binds.

        The escalating set is a module constant, expanded to individual bind
        params (``esc0..escN``) — never string-interpolated, so no user value
        ever reaches SQL.
        """
        p = dict(base)
        esc = [f"esc{i}" for i in range(len(ESCALATING_INTENT_TYPES))]
        for name, val in zip(esc, ESCALATING_INTENT_TYPES):
            p[name] = val
        return p

    @staticmethod
    def _esc_in_clause() -> str:
        return "intent_type IN (" + ",".join(f":esc{i}" for i in range(len(ESCALATING_INTENT_TYPES))) + ")"

    async def _exec(self, sql: str, params: Dict[str, Any]) -> List[Any]:
        res = await self.db.execute(text(sql), params)
        return res.fetchall()

    async def _query_headline(self, sc: str, base: Dict[str, Any]) -> Dict[str, Any]:
        esc_in = self._esc_in_clause()
        sql = (
            f"WITH {sc},\n"
            "msg_agg AS (\n"
            "  SELECT conversation_id,\n"
            "         count(*) FILTER (WHERE role = 'user') AS user_msgs,\n"
            "         count(*) AS total_msgs\n"
            "  FROM message\n"
            "  WHERE is_deleted = false AND conversation_id IN (SELECT id FROM sc)\n"
            "  GROUP BY conversation_id\n"
            "),\n"
            "resp AS (\n"
            "  SELECT role,\n"
            "         created_at - LAG(created_at) OVER (\n"
            "           PARTITION BY conversation_id ORDER BY created_at, id) AS gap,\n"
            "         LAG(role) OVER (PARTITION BY conversation_id ORDER BY created_at, id) AS prev_role\n"
            "  FROM message\n"
            "  WHERE is_deleted = false AND conversation_id IN (SELECT id FROM sc)\n"
            "),\n"
            "intent_s AS (\n"
            "  SELECT conversation_id, confidence, matched_action, intent_type\n"
            "  FROM intents\n"
            "  WHERE is_deleted = false AND conversation_id IN (SELECT id FROM sc)\n"
            ")\n"
            "SELECT\n"
            "  (SELECT count(*) FROM sc) AS total_conversations,\n"
            "  COALESCE((SELECT sum(total_msgs) FROM msg_agg), 0) AS total_messages,\n"
            "  COALESCE((SELECT sum(user_msgs) FROM msg_agg), 0) AS total_user_messages,\n"
            "  COALESCE((SELECT avg(EXTRACT(EPOCH FROM gap)) FROM resp WHERE role = 'assistant' AND prev_role = 'user'), 0)::float AS avg_response_seconds,\n"
            "  COALESCE((SELECT avg(duration_seconds) FROM sc WHERE duration_seconds IS NOT NULL), 0)::float AS avg_duration_seconds,\n"
            "  (SELECT count(*) FROM sc WHERE sentiment = 'positive') AS positive_sentiment,\n"
            "  (SELECT count(*) FROM sc WHERE sentiment IS NOT NULL) AS with_sentiment,\n"
            "  (SELECT count(*) FROM intent_s) AS total_intents,\n"
            "  (SELECT count(*) FROM intent_s WHERE confidence >= :threshold) AS confident_intents,\n"
            "  (SELECT count(*) FROM intent_s WHERE confidence >= :threshold AND matched_action IS NOT NULL) AS accurate_intents,\n"
            f"  (SELECT count(*) FROM intent_s WHERE {esc_in} OR matched_action = 'escalate') AS escalating_intents,\n"
            f"  (SELECT count(DISTINCT conversation_id) FROM intent_s WHERE {esc_in} OR matched_action = 'escalate') AS handoff_conversations,\n"
            "  COALESCE((SELECT avg(confidence) FROM intent_s), 0)::float AS avg_confidence\n"
        )
        rows = await self._exec(sql, self._params(base))
        row = rows[0]
        keys = ("total_conversations", "total_messages", "total_user_messages",
                "avg_response_seconds", "avg_duration_seconds", "positive_sentiment",
                "with_sentiment", "total_intents", "confident_intents", "accurate_intents",
                "escalating_intents", "handoff_conversations", "avg_confidence")
        raw = dict(zip(keys, row))
        # normalise ints / floats so the pure assembler sees clean types
        for k in ("total_conversations", "total_messages", "total_user_messages",
                  "positive_sentiment", "with_sentiment", "total_intents",
                  "confident_intents", "accurate_intents", "escalating_intents",
                  "handoff_conversations"):
            raw[k] = int(raw[k] or 0)
        for k in ("avg_response_seconds", "avg_duration_seconds", "avg_confidence"):
            raw[k] = float(raw[k] or 0.0)
        return raw

    async def _query_by_platform(self, sc: str, base: Dict[str, Any]) -> List[Dict[str, Any]]:
        sql = (
            f"WITH {sc},\n"
            "msg_agg AS (\n"
            "  SELECT conversation_id, count(*) FILTER (WHERE role = 'user') AS user_msgs\n"
            "  FROM message WHERE is_deleted = false AND conversation_id IN (SELECT id FROM sc)\n"
            "  GROUP BY conversation_id\n"
            ")\n"
            "SELECT sc.channel AS channel,\n"
            "       count(*) AS conversations,\n"
            "       COALESCE(sum(ma.user_msgs), 0) AS user_messages,\n"
            "       COALESCE(avg(sc.duration_seconds) FILTER (WHERE sc.duration_seconds IS NOT NULL), 0)::float AS avg_duration_seconds,\n"
            "       COALESCE(sum(CASE WHEN sc.sentiment = 'positive' THEN 1 ELSE 0 END), 0) AS positive_sentiment,\n"
            "       COALESCE(sum(CASE WHEN sc.sentiment IS NOT NULL THEN 1 ELSE 0 END), 0) AS with_sentiment\n"
            "FROM sc LEFT JOIN msg_agg ma ON ma.conversation_id = sc.id\n"
            "GROUP BY sc.channel\n"
            "ORDER BY conversations DESC, sc.channel ASC"
        )
        rows = await self._exec(sql, self._params(base))
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "channel": r[0], "conversations": int(r[1]),
                "user_messages": int(r[2]), "avg_duration_seconds": float(r[3] or 0.0),
                "positive_sentiment": int(r[4]), "with_sentiment": int(r[5]),
            })
        return out

    async def _query_by_agent(self, sc: str, base: Dict[str, Any]) -> List[Dict[str, Any]]:
        # When an agent filter is set, restrict the breakdown to that agent so
        # co-bound siblings of the same customer don't leak into the view.
        sql = (
            f"WITH {sc},\n"
            "msg_agg AS (\n"
            "  SELECT conversation_id, count(*) FILTER (WHERE role = 'user') AS user_msgs\n"
            "  FROM message WHERE is_deleted = false AND conversation_id IN (SELECT id FROM sc)\n"
            "  GROUP BY conversation_id\n"
            ")\n"
            "SELECT acb.agent_id AS agent_id, a.name AS agent_name,\n"
            "       count(DISTINCT sc.id) AS conversations,\n"
            "       COALESCE(sum(ma.user_msgs), 0) AS user_messages\n"
            "FROM sc\n"
            "JOIN agent_customer_binding acb\n"
            "     ON acb.customer_id = sc.customer_id\n"
            "    AND acb.is_deleted = false\n"
            + ("    AND acb.agent_id = :agent_id\n" if base.get("agent_id") is not None else "")
            + "LEFT JOIN agent a ON a.id = acb.agent_id AND a.is_deleted = false\n"
            "LEFT JOIN msg_agg ma ON ma.conversation_id = sc.id\n"
            "GROUP BY acb.agent_id, a.name\n"
            "ORDER BY conversations DESC, acb.agent_id ASC\n"
            f"LIMIT {_BREAKDOWN_LIMIT}"
        )
        rows = await self._exec(sql, self._params(base))
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "agent_id": r[0], "agent_name": r[1],
                "conversations": int(r[2] or 0), "user_messages": int(r[3] or 0),
            })
        return out

    async def _query_by_intent(self, sc: str, base: Dict[str, Any]) -> List[Dict[str, Any]]:
        sql = (
            f"WITH {sc}\n"
            "SELECT i.intent_type AS intent_type,\n"
            "       count(*) AS total,\n"
            "       count(*) FILTER (WHERE i.confidence >= :threshold AND i.matched_action IS NOT NULL) AS accurate,\n"
            "       COALESCE(avg(i.confidence), 0)::float AS avg_confidence\n"
            "FROM intents i\n"
            "WHERE i.is_deleted = false AND i.conversation_id IN (SELECT id FROM sc)\n"
            "GROUP BY i.intent_type\n"
            "ORDER BY total DESC, i.intent_type ASC\n"
            f"LIMIT {_BREAKDOWN_LIMIT}"
        )
        rows = await self._exec(sql, self._params(base))
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "intent_type": r[0], "total": int(r[1]), "accurate": int(r[2] or 0),
                "avg_confidence": float(r[3] or 0.0),
            })
        return out

    # ------------------------------------------------------------------ #
    # pure assembly (unit-tested without a DB; all zero-safety lives here)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _assemble(
        raw: Dict[str, Any],
        by_platform_rows: List[Dict[str, Any]],
        by_agent_rows: List[Dict[str, Any]],
        by_intent_rows: List[Dict[str, Any]],
        *,
        filters: Dict[str, Optional[str]],
        window: Dict[str, str],
        threshold: float,
        agent_id: Optional[UUID] = None,
        intent_type: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> ConversationMetricsResponse:
        total_conv = raw["total_conversations"]
        total_msgs = raw["total_user_messages"]  # rounds are measured in user turns
        by_platform = [
            PlatformMetric(
                channel=r["channel"], conversations=r["conversations"],
                user_messages=r["user_messages"], avg_duration_seconds=r["avg_duration_seconds"],
                positive_sentiment=r["positive_sentiment"], with_sentiment=r["with_sentiment"],
                avg_rounds=round(_safe_ratio(r["user_messages"], r["conversations"]), 3),
                satisfaction_rate=round(_safe_ratio(r["positive_sentiment"], r["with_sentiment"]), 4),
            )
            for r in by_platform_rows
        ]
        by_agent = [
            AgentMetric(
                agent_id=r["agent_id"], agent_name=r.get("agent_name"),
                conversations=r["conversations"], user_messages=r["user_messages"],
                avg_rounds=round(_safe_ratio(r["user_messages"], r["conversations"]), 3),
            )
            for r in by_agent_rows
        ]
        by_intent = [
            IntentMetric(
                intent_type=r["intent_type"], total=r["total"], accurate=r["accurate"],
                avg_confidence=round(r["avg_confidence"], 4),
                accuracy=round(_safe_ratio(r["accurate"], r["total"]), 4),
                is_escalating=r["intent_type"] in ESCALATING_INTENT_TYPES,
            )
            for r in by_intent_rows
        ]

        return ConversationMetricsResponse(
            sample_size=total_conv,
            has_data=total_conv > 0,
            window=window,
            filters=filters,
            total_conversations=total_conv,
            avg_response_time_seconds=round(raw["avg_response_seconds"], 3),
            avg_conversation_rounds=round(_safe_ratio(total_msgs, total_conv), 3),
            intent_accuracy=round(_safe_ratio(raw["accurate_intents"], raw["total_intents"]), 4),
            human_handoff_rate=round(_safe_ratio(raw["handoff_conversations"], total_conv), 4),
            satisfaction_rate=round(_safe_ratio(raw["positive_sentiment"], raw["with_sentiment"]), 4),
            total_messages=raw["total_messages"],
            total_user_messages=total_msgs,
            total_intents=raw["total_intents"],
            confident_intents=raw["confident_intents"],
            accurate_intents=raw["accurate_intents"],
            escalating_intents=raw["escalating_intents"],
            handoff_conversations=raw["handoff_conversations"],
            positive_sentiment=raw["positive_sentiment"],
            with_sentiment=raw["with_sentiment"],
            avg_confidence=round(raw["avg_confidence"], 4),
            avg_duration_seconds=round(raw["avg_duration_seconds"], 3),
            accuracy_threshold=threshold,
            by_platform=by_platform,
            by_agent=by_agent,
            by_intent=by_intent,
        )
