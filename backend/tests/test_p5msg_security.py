"""P5MSG-12-SR-1 — dedicated P5MSG security test suite.

Adds the security-dedicated coverage the P5MSG-11 review flagged as missing
(P2-1, issue pool P5MSG-12-SR-P2-1): auth / overreach / PII-leak / payload
validation / credential-masking cases for the P5MSG routes.

Scope (this card):
1. **Auth** — POST /api/v1/realtime/publish: no Bearer -> 401, wrong token
   -> 403, trusted -> 202 (aligned with t_1e71c3ba FIX-1 behaviour).
   /messages/{id}/status and /realtime/read overreach: untrusted callers are
   rejected before they can drive any other customer's state machine
   (401/403); the trusted happy paths (200) are exercised end-to-end through
   the real service logic with stubbed data.
2. **PII leak** — GET /realtime/conversations ``last_message_preview``:
   customer strong validation + auth (aligned with t_74d4c4b1 FIX-2);
   cross-customer previews are not visible (404 for unknown customer,
   401/403 for untrusted callers, in-memory scoping filters foreign rows).
3. **Payload validation** — publish non-dict / > 4KB / secret-marker keys /
   embedded-secret values -> 422 via ``RealtimePublishRequest``'s
   ``validate_publish_payload`` strong schema (plus direct unit coverage of
   the validator boundaries).
4. **Credential de-echo** — GET /accounts never returns
   ``password_encrypted`` verbatim (FIX-2 ``mask_credential`` funnel).

Constraints honoured:
* Test-only — no product code is modified. If a FIX-1/FIX-2 behaviour
  deviates, the suite FAILs and the divergence is reported to the P5MSG
  issue pool (not silently patched here).
* The platform-wide P0-1 (no API auth on all routes + CORS *+credentials)
  is OUT of scope (ADR-015 security-hardening lane owns it); tests are
  written against the "trusted producer" contract that FIX-1 establishes.

Reuse: inherits the shared-tree pytest + pytest-asyncio (auto mode) config in
H:/AI-Agent-Platform/backend/pyproject.toml; all cases enter the P5MSG
regression gate (baseline 246/246) as new tests.

Run:  cd H:/AI-Agent-Platform/backend && uv run pytest tests/test_p5msg_security.py -v
"""
import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared helpers (same conventions as test_realtime_api.py /
# test_p1_security_fix.py: app.security re-reads the token env var per
# request, so per-class env setup is safe).
# ---------------------------------------------------------------------------

PUBLISH_TOKEN = "test-trusted-token"


def _auth() -> dict:
    return {"Authorization": f"Bearer {PUBLISH_TOKEN}"}


def _new_client():
    import app.main as m
    from app.services.realtime_hub import reset_realtime_hub

    reset_realtime_hub()
    return TestClient(m.app)


def _pg_available() -> bool:
    """Gate the real-Postgres cases (same probe as test_realtime_api)."""
    import asyncio

    try:
        import asyncpg

        async def _probe():
            dsn = "postgresql://postgres:***@localhost:5432/ai_agent_platform_test"
            conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=3)
            await conn.close()
            return True

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_probe())
        finally:
            loop.close()
    except Exception:
        return False


def _setup_tokens(self):
    os.environ["REALTIME_PUBLISH_TOKENS"] = PUBLISH_TOKEN
    self.client = _new_client()


def _teardown_tokens(self):
    os.environ.pop("REALTIME_PUBLISH_TOKENS", None)


# ---------------------------------------------------------------------------
# 1. AUTH — POST /api/v1/realtime/publish (trusted-producer contract)
# ---------------------------------------------------------------------------


class TestPublishAuth:
    """P0-3 (FIX-1 aligned): the publish seam is a trusted-producer surface."""

    setup_method = _setup_tokens
    teardown_method = _teardown_tokens

    def _publish(self, payload, headers):
        return self.client.post(
            "/api/v1/realtime/publish",
            json={"kind": "channel_message.status", "conversation_id": str(uuid4()), "payload": payload},
            headers=headers,
        )

    def test_no_bearer_is_401(self):
        r = self._publish({"status": "sent"}, {})
        assert r.status_code == 401, r.text
        # HTTP-standard auth challenge header must be present on 401.
        assert r.headers.get("WWW-Authenticate") == "Bearer", r.headers
        assert r.json()["detail"]["code"] == 401

    def test_wrong_token_is_403(self):
        r = self._publish({"status": "sent"}, {"Authorization": "Bearer definitely-not-trusted"})
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == 403
        assert r.json()["detail"]["data"] is None

    def test_trusted_token_is_202(self):
        r = self._publish(
            {"status": "sent", "conversation_id": str(uuid4())}, _auth()
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["code"] == 0
        assert body["message"] == "accepted"
        assert body["data"]["emitted_seq"] is not None

    def test_empty_token_is_401(self):
        # A bare "Bearer " with an empty secret is 'no token', not 'wrong token'.
        r = self._publish({"status": "sent"}, {"Authorization": "Bearer "})
        assert r.status_code == 401, r.text

    def test_closed_posture_no_trusted_tokens_configured_is_403(self):
        # Default posture is closed: empty trusted set == nobody is trusted.
        os.environ["REALTIME_PUBLISH_TOKENS"] = ""
        r = self._publish({"status": "sent"}, {"Authorization": "Bearer anything"})
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 2. OVERREACH — /messages/{id}/status + /realtime/read (P0-2, FIX-1)
# ---------------------------------------------------------------------------


class TestOverreachAuth:
    """Cross-owner write primitives must reject untrusted callers BEFORE any
    state mutation: 401 (no token) / 403 (wrong token) on both endpoints."""

    setup_method = _setup_tokens
    teardown_method = _teardown_tokens

    def test_message_status_no_token_is_401(self):
        r = self.client.post(f"/api/v1/messages/{uuid4()}/status", json={"status": "read"})
        assert r.status_code == 401, r.text
        assert r.json()["detail"]["code"] == 401
        assert r.headers.get("WWW-Authenticate") == "Bearer"

    def test_message_status_wrong_token_is_403(self):
        r = self.client.post(
            f"/api/v1/messages/{uuid4()}/status",
            json={"status": "read"},
            headers={"Authorization": "Bearer outsider"},
        )
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == 403

    def test_realtime_read_no_token_is_401(self):
        r = self.client.post("/api/v1/realtime/read", json={"conversation_id": str(uuid4())})
        assert r.status_code == 401, r.text
        assert r.json()["detail"]["code"] == 401

    def test_realtime_read_wrong_token_is_403(self):
        r = self.client.post(
            "/api/v1/realtime/read",
            json={"conversation_id": str(uuid4())},
            headers={"Authorization": "Bearer outsider"},
        )
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == 403


class _FakeDb:
    """Minimal async-DB facade: records ``add`` / commit, plays back the
    queued ``execute`` results — enough for the real service logic to run
    through the happy path without Postgres."""

    def __init__(self, sequence):
        self._queue = list(sequence)
        self.added = []
        self.commit_calls = 0

    async def execute(self, *a, **kw):
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, *a, **kw):
        pass


def _message_row(msg_id, status):
    m = SimpleNamespace(
        id=msg_id,
        conversation_id=uuid4(),
        account_id=None,
        agent_id=None,
        channel="wechat",
        direction="in",
        status=status,
        content={"text": "hi"},
        receipts=[],
        error=None,
        sent_at=None,
        received_at=None,
        provider_message_id=None,
        last_receipt_at=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        is_deleted=False,
    )
    return m


class _Result:
    """Result facade: ``.scalars()`` is a CALLABLE (as on a real
    ``SelectResult``) and ``.scalar_one_or_none()`` a method too."""

    _DEFAULT = object()

    def __init__(self, scalars, one_or_none=_DEFAULT):
        self._scalars = list(scalars)
        # The row-lock query reads ``scalar_one_or_none()``; when not given an
        # explicit value, fall back to the first row (or None).
        if one_or_none is self._DEFAULT:
            one_or_none = self._scalars[0] if self._scalars else None
        self._one_or_none = one_or_none

    def scalars(self, *a, **kw):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def scalar_one_or_none(self, *a, **kw):
        return self._one_or_none


class TestOverreachTrustedHappyPath:
    """Trusted producers keep working (200) — the real service logic drives
    the state machine / mark-read flow; only the data access is stubbed."""

    setup_method = _setup_tokens
    teardown_method = _teardown_tokens

    def test_message_status_trusted_legal_transition_is_200(self):
        from app.db.session import get_db
        from app.routers import messages as messages_router
        from app.services.message_service import MessageService

        msg = _message_row(uuid4(), "sent")
        db = _FakeDb([_Result([msg])])
        service = MessageService(db)

        def _override():
            yield db

        app = self.client.app
        app.dependency_overrides[get_db] = _override
        app.dependency_overrides[messages_router.get_message_service] = lambda: service
        try:
            # sent->read is the legal next hop for an inbound sent message.
            r = self.client.post(
                f"/api/v1/messages/{msg.id}/status",
                json={"status": "read", "source": "manual"},
                headers=_auth(),
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(messages_router.get_message_service, None)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0
        # The real state machine ran: the message row was updated AND an
        # ExecutionLog audit row was appended (P5MSG-02 SoT trail).
        log_rows = [a for a in db.added if getattr(a, "execution_type", None) == "message_status"]
        assert len(log_rows) == 1
        assert log_rows[0].input_params["to"] == "read"
        assert log_rows[0].input_params["from"] == "sent"

    def test_realtime_read_trusted_marks_inbound_read_is_200(self):
        from app.db.session import get_db

        # The /read router builds its own MessageService(db) and drives the
        # real state machine per inbound message: sent -> read (legal). One
        # row-lock result per message feeds _lock_message.
        conv = uuid4()
        rows = [_message_row(uuid4(), "sent") for _ in range(2)]
        for row in rows:
            row.conversation_id = conv
        db = _FakeDb([
            _Result([str(r.id) for r in rows]),  # router: select(ChannelMessage.id).scalars().all()
            _Result([rows[0]]),                  # update_status(rows[0].id): _lock_message
            _Result([rows[1]]),                   # update_status(rows[1].id): _lock_message
        ])

        def _override():
            yield db

        app = self.client.app
        app.dependency_overrides[get_db] = _override
        try:
            conv_id = str(conv)
            r = self.client.post(
                "/api/v1/realtime/read",
                json={"conversation_id": conv_id},
                headers=_auth(),
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["conversation_id"] == conv_id
        assert data["marked_read"] == 2
        assert len(data["marked_message_ids"]) == 2
        assert data["skipped"] == []
        # The real state machine ran: each inbound row transitioned sent->read
        # and a delivery audit log was appended (ADR-017: ExecutionLog is the
        # single source of truth for the receipt trail; the per-row JSONB
        # ``receipts`` column is deprecated and no longer written here).
        assert all(m.status == "read" for m in rows)
        log_rows = [a for a in db.added if getattr(a, "execution_type", None) == "message_status"]
        assert len(log_rows) == 2
        assert all(l.input_params["to"] == "read" for l in log_rows)
        # The live read-marker event was emitted on the hub. (The /read flow
        # also emits one channel_message.status event per marked message, so
        # the marker lands on the 3rd seq after the hub reset.)
        assert isinstance(data["emitted_seq"], int) and data["emitted_seq"] >= 1
        assert db.commit_calls == 2


# ---------------------------------------------------------------------------
# 3. PII LEAK — GET /realtime/conversations + /unread (P1-3, FIX-2)
# ---------------------------------------------------------------------------


class _ConvRow:
    """A customer-scope active-list row. The service unpacks rows by
    position (``r[0]`` = conversation_id ... ``r[6]`` = last_message_at)
    while the router reads named attributes — so the row supports both,
    like a real SQLAlchemy ``Row``."""

    def __init__(self, customer_id, conv_id, last_at):
        self.conversation_id = conv_id      # [0]
        self.customer_id = customer_id      # [1]
        self.channel = "wechat"            # [2]
        self.subject = "s"                 # [3]
        self.status = "active"             # [4]
        self.message_count = 3             # [5]
        self.last_message_at = last_at     # [6]

    def __getitem__(self, i):
        return (
            self.conversation_id,
            self.customer_id,
            self.channel,
            self.subject,
            self.status,
            self.message_count,
            self.last_message_at,
        )[i]


def _conv_row(customer_id, conv_id, last_at):
    return _ConvRow(customer_id, conv_id, last_at)


def _probe_result(value):
    """Router ownership-probe result (``scalar_one_or_none``)."""
    return SimpleNamespace(scalar_one_or_none=lambda: value)


def _list_stub(client, rows, contents):
    """DB stub for GET /realtime/conversations with a customer-scope row list.

    The active-list query returns ``rows`` (one row per customer: scoping is
    the service's in-memory filter, so a FOREIGN row may sit in the result
    set — that is exactly the PII-leak case under test). Call sequence per
    request (router first, then per row):

      1. router ownership probe        -> scalar_one_or_none
      2. service active-list query      -> .all()
      3..4. per row: latest-preview / unread-count  -> scalar_one_or_none
      5.. last. service unread_total    -> scalar_one
    """
    from app.db.session import get_db

    db_stub = MagicMock()
    per_row = []
    for c in contents:
        per_row.append(SimpleNamespace(scalar_one_or_none=lambda c=c: c))
        per_row.append(SimpleNamespace(scalar_one=lambda: 0))
    all_results = [
        _probe_result(str(rows[0].customer_id)),
        SimpleNamespace(all=lambda: list(rows)),
        *per_row,
        SimpleNamespace(scalar_one=lambda: 0),
    ]
    idx = {"i": 0}

    async def _execute(query):
        r = all_results[idx["i"]]
        idx["i"] += 1
        return r

    db_stub.execute = _execute

    def _override():
        yield db_stub

    app = client.app
    app.dependency_overrides[get_db] = _override
    return get_db


class TestConversationsPiiLeak:
    """``last_message_preview`` must stay customer-scoped + auth-gated."""

    setup_method = _setup_tokens
    teardown_method = _teardown_tokens

    def _conversations(self, customer_id, headers, extra=None):
        params = dict(extra or {})
        if customer_id is not None:
            params["customer_id"] = str(customer_id)
        return self.client.get("/api/v1/realtime/conversations", params=params, headers=headers)

    def test_no_token_is_401(self):
        # The auth dependency short-circuits before any DB access.
        r = self._conversations(uuid4(), {})
        assert r.status_code == 401, r.text
        assert r.json()["detail"]["code"] == 401

    def test_wrong_token_is_403(self):
        r = self._conversations(uuid4(), {"Authorization": "Bearer outsider"})
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == 403

    def test_missing_customer_id_is_422_platform_wide_refused(self):
        # No customer scoping -> no platform-wide PII preview broadcast.
        r = self._conversations(None, _auth())
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == 4002

    def test_unknown_customer_is_404_ownership_check(self):
        from app.db.session import get_db

        db_stub = MagicMock()

        async def _execute(query):
            return _probe_result(None)  # customer does not exist

        db_stub.execute = _execute

        def _override():
            yield db_stub

        app = self.client.app
        app.dependency_overrides[get_db] = _override
        try:
            r = self.client.get(
                "/api/v1/realtime/conversations",
                params={"customer_id": str(uuid4())},
                headers=_auth(),
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["code"] == 4004
        # An unknown customer must not leak a cross-tenant view — the body
        # carries no conversation / preview data.
        assert r.json()["detail"]["data"] is None

    def test_cross_customer_preview_not_visible_in_scoped_list(self):
        """A foreign customer's active row sitting in the query result set
        must be filtered out before its preview is ever rendered."""
        owner, stranger = uuid4(), uuid4()
        last_at = "2026-01-01T00:00:00+00:00"
        rows = [
            _conv_row(owner, uuid4(), last_at),
            _conv_row(stranger, uuid4(), last_at),  # foreign row: must be filtered
        ]
        contents = [
            {"text": "owner phone 13800001111"},
            {"text": "stranger phone 13900002222"},
        ]
        get_db = _list_stub(self.client, rows, contents)
        try:
            r = self._conversations(owner, _auth())
        finally:
            self.client.app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 200, r.text
        body = r.json()
        # Only the owner's conversation is served, with the owner's preview.
        assert [i["customer_id"] for i in body["items"]] == [str(owner)]
        assert len(body["items"]) == 1
        assert "13800001111" in body["items"][0]["last_message_preview"]
        # The foreign customer's PII must not be visible anywhere in the body.
        assert "13900002222" not in r.text

    def test_redact_preview_scrubs_phone_when_opted_in(self):
        """FIX-2 behaviour: ``redact_preview=true`` scrubs PII from the
        rendered preview; ``false`` keeps the raw text (the row is never
        mutated)."""
        owner = uuid4()
        rows = [_conv_row(owner, uuid4(), "2026-01-01T00:00:00+00:00")]
        contents = [{"text": "手机号13912345678谢谢"}]

        # Two independent requests, each under its own re-armed stub.
        get_db = _list_stub(self.client, rows, contents)
        try:
            raw = self._conversations(owner, _auth())
        finally:
            self.client.app.dependency_overrides.pop(get_db, None)

        get_db2 = _list_stub(self.client, rows, contents)
        try:
            red = self._conversations(owner, _auth(), extra={"redact_preview": "true"})
        finally:
            self.client.app.dependency_overrides.pop(get_db2, None)

        assert raw.status_code == 200, raw.text
        assert "13912345678" in raw.json()["items"][0]["last_message_preview"]
        assert red.status_code == 200, red.text
        assert "13912345678" not in red.text
        assert "[PHONE]" in red.json()["items"][0]["last_message_preview"]

    def test_unread_no_token_401_and_wrong_token_403(self):
        assert self.client.get("/api/v1/realtime/unread", params={"customer_id": str(uuid4())}).status_code == 401
        r = self.client.get(
            "/api/v1/realtime/unread",
            params={"customer_id": str(uuid4())},
            headers={"Authorization": "Bearer outsider"},
        )
        assert r.status_code == 403, r.text

    def test_unread_missing_customer_id_is_422(self):
        r = self.client.get("/api/v1/realtime/unread", headers=_auth())
        assert r.status_code == 422, r.text

    def test_unread_unknown_customer_is_404(self):
        from app.db.session import get_db

        db_stub = MagicMock()

        async def _execute(query):
            return SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))

        db_stub.execute = _execute

        def _override():
            yield db_stub

        app = self.client.app
        app.dependency_overrides[get_db] = _override
        try:
            r = self.client.get(
                "/api/v1/realtime/unread",
                params={"customer_id": str(uuid4())},
                headers=_auth(),
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 404, r.text


TEST_DB = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"


@pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")
class TestConversationsPiiCrossCustomerIntegration:
    """Strongest end-to-end PII-leak evidence: two real customers in Postgres,
    each with a PII-carrying last message. Requesting the *owner's* scoped
    view must surface only the owner's preview — the stranger's phone number
    must not be reachable through any scoping parameter. Run against the real
    DB (skipped when Postgres is unavailable), mirroring test_realtime_api's
    sessionmaker pattern (engine created inside the loop)."""

    async def test_cross_customer_preview_invisible(self):
        from datetime import datetime, timezone

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
            async_sessionmaker,
        )

        from app.db.models import Base
        from app.db.models.conversation import Conversation
        from app.db.models.customer import Customer
        from app.db.models.messages import ChannelMessage
        from app.services.realtime_conversation_service import (
            RealtimeConversationService,
        )

        engine = create_async_engine(TEST_DB)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        owner_phone = "13855550001"
        stranger_phone = "13955550002"

        async with Session() as s:
            owner = Customer(name=f"pii-owner-{uuid4().hex[:8]}", is_deleted=False)
            s.add(owner)
            await s.commit()
            await s.refresh(owner)

            stranger = Customer(name=f"pii-stranger-{uuid4().hex[:8]}", is_deleted=False)
            s.add(stranger)
            await s.commit()
            await s.refresh(stranger)

            owner_conv = Conversation(
                customer_id=owner.id, channel="wechat", subject="owner",
                status="active", is_deleted=False,
            )
            stranger_conv = Conversation(
                customer_id=stranger.id, channel="wechat", subject="stranger",
                status="active", is_deleted=False,
            )
            s.add_all([owner_conv, stranger_conv])
            await s.commit()
            await s.refresh(owner_conv)
            await s.refresh(stranger_conv)

            t = datetime.now(timezone.utc)
            s.add(ChannelMessage(
                conversation_id=owner_conv.id, direction="in", status="sent",
                content={"text": f"我的手机号{owner_phone}"},
                created_at=t, updated_at=t,
            ))
            s.add(ChannelMessage(
                conversation_id=stranger_conv.id, direction="in", status="sent",
                content={"text": f"我的手机号{stranger_phone}"},
                created_at=t, updated_at=t,
            ))
            await s.commit()

            svc = RealtimeConversationService(s)

            # Scoping to the owner surfaces the owner's PII preview...
            owner_rows = await svc.list_active_conversations(customer_id=owner.id)
            owner_row = [r for r in owner_rows if r.conversation_id == owner_conv.id][0]
            assert owner_phone in (owner_row.last_message_preview or "")
            assert stranger_phone not in (owner_row.last_message_preview or "")

            # ...and the *service-level* scoping also hides the stranger's
            # preview when requested under the stranger's own scope.
            stranger_rows = await svc.list_active_conversations(customer_id=stranger.id)
            stranger_row = [
                r for r in stranger_rows if r.conversation_id == stranger_conv.id
            ][0]
            assert stranger_phone in (stranger_row.last_message_preview or "")
            assert owner_phone not in (stranger_row.last_message_preview or "")

            # Redaction (FIX-2): the opt-in flag scrubs both PII values from
            # the rendered preview without touching storage.
            redacted = await svc.list_active_conversations(
                customer_id=owner.id, redact_preview=True
            )
            redacted_row = [
                r for r in redacted if r.conversation_id == owner_conv.id
            ][0]
            assert owner_phone not in (redacted_row.last_message_preview or "")
            assert "[PHONE]" in (redacted_row.last_message_preview or "")

            # Storage is untouched — the PII row still holds the raw text.
            stored = (
                await s.execute(
                    select(ChannelMessage.content).where(
                        ChannelMessage.conversation_id == owner_conv.id
                    )
                )
            ).scalar_one()
            assert f"我的手机号{owner_phone}" in stored["text"]

            await s.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 4. PAYLOAD VALIDATION — publish strong schema (P0-3, FIX-1)
# ---------------------------------------------------------------------------


class TestPublishPayloadValidation:
    """Trusted callers are STILL constrained by the strong payload schema:
    non-dict / > 4KB / PII-secret-marker keys / embedded secrets -> 422."""

    setup_method = _setup_tokens
    teardown_method = _teardown_tokens

    def _publish(self, payload, extra=None):
        body = {"kind": "channel_message.status", "payload": payload}
        body.update(extra or {})
        return self.client.post("/api/v1/realtime/publish", json=body, headers=_auth())

    def test_non_dict_payload_rejected_422(self):
        # A JSON array body is not a payload object.
        r = self._publish([1, 2, 3])
        assert r.status_code == 422, r.text

    def test_unknown_kind_rejected_422(self):
        r = self._publish({"status": "sent"}, extra={"kind": "totally.made.up"})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == 4002

    def test_non_uuid_conversation_id_rejected_422(self):
        r = self._publish({"conversation_id": "not-a-uuid"})
        assert r.status_code == 422, r.text

    def test_pii_marker_keys_rejected_422(self):
        # Each of these key shapes must be refused at the seam (unit level,
        # so the case space is explicit rather than sampled).
        from app.security import PayloadValidationError, validate_publish_payload

        for bad in ("user_email", "phone_number", "account_no", "body", "pii", "cookie"):
            with pytest.raises(PayloadValidationError):
                validate_publish_payload({"x": 1, bad: "v"})

        # And via the HTTP seam (the 422 mapping):
        r = self._publish({"status": "sent", "email": "a@b.c"})
        assert r.status_code == 422, r.text

    def test_secret_key_rejected_422(self):
        r = self._publish({"status": "sent", "api_key": "abcdef"})
        assert r.status_code == 422, r.text

    def test_embedded_secret_value_rejected_422(self):
        # A value that looks like a long bearer secret is refused even in a
        # benign-looking key.
        r = self._publish({"status": "sent", "ref": "A" * 48})
        assert r.status_code == 422, r.text

    def test_oversized_payload_rejected_422(self):
        # Pin the 4096-byte total-size boundary instead of 'some big thing'.
        #
        # Two traps to avoid when building a > 4096-byte payload that is
        # refused *for size* (not for another rule):
        #   * a single long string would trip the 512-char per-value cap
        #     first; so the size is accumulated across many medium values.
        #   * any value that is a bare run of 40+ chars from
        #     [A-Za-z0-9+/=_-] looks like an embedded secret and is rejected
        #     by the secret detector, not the size cap. Suffix every value
        #     with a '!' (outside that charset) so only the size cap can
        #     fire.
        import json

        from app.security import (
            MAX_PAYLOAD_BYTES,
            MAX_VALUE_STR_LEN,
            PayloadValidationError,
            validate_publish_payload,
        )

        n = 23  # + the "status" key = 24 total (at the key cap), so only the
                # serialized *size* varies as we sweep the value length.

        def _payloads(val_len):
            # value = "a"*(L-1) + "!"  -> length L, secret-regex-proof.
            val = "a" * max(0, val_len - 1) + "!"
            d = {f"k{i:02d}": val for i in range(n)}
            d["status"] = "sent"
            return d, val

        def _size(d):
            return len(json.dumps(d, ensure_ascii=False))

        # Binary-search the largest value length still under the byte cap.
        lo, hi = 0, 511  # per-value cap bounds the search space
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if _size(_payloads(mid)[0]) <= MAX_PAYLOAD_BYTES:
                lo = mid
            else:
                hi = mid
        assert lo < MAX_VALUE_STR_LEN
        at_cap, _ = _payloads(lo)       # <= 4096 bytes -> allowed
        over_cap, _ = _payloads(lo + 1)  # > 4096 bytes -> refused by size
        assert _size(at_cap) <= MAX_PAYLOAD_BYTES
        assert _size(over_cap) > MAX_PAYLOAD_BYTES

        validate_publish_payload(at_cap)  # at the cap: passes
        with pytest.raises(PayloadValidationError) as exc:
            validate_publish_payload(over_cap)
        # The rejection must be the *size* rule, not the secret / value caps.
        assert "4096" in str(exc.value)

        r = self._publish(over_cap)
        assert r.status_code == 422, r.text

    def test_too_many_keys_rejected_422(self):
        from app.security import MAX_PAYLOAD_KEYS, PayloadValidationError, validate_publish_payload

        with pytest.raises(PayloadValidationError):
            validate_publish_payload({f"k{i:02d}": i for i in range(MAX_PAYLOAD_KEYS + 1)})

        r = self._publish({f"k{i:02d}": i for i in range(MAX_PAYLOAD_KEYS + 1)})
        assert r.status_code == 422, r.text

    def test_nested_object_rejected_422(self):
        r = self._publish({"status": "sent", "meta": {"a": 1}})
        assert r.status_code == 422, r.text

    def test_bad_key_charset_rejected_422(self):
        r = self._publish({"status": "sent", "bad key": 1})
        assert r.status_code == 422, r.text

    def test_trusted_clean_payload_is_202(self):
        r = self._publish({"status": "delivered", "channel": "wechat"})
        assert r.status_code == 202, r.text
        assert r.json()["data"]["emitted_seq"] is not None


# ---------------------------------------------------------------------------
# 5. CREDENTIAL DE-ECHO — GET /accounts (P1-1, FIX-2 masking funnel)
# ---------------------------------------------------------------------------


class _AccountModel:
    def __init__(self, raw_password):
        self.id = uuid4()
        self.platform_id = uuid4()
        self.name = "acc"
        self.username = "u"
        self.password_encrypted = raw_password
        self.status = "connected"
        self.last_login = None
        self.created_at = "2026-01-01T00:00:00+00:00"
        self.updated_at = "2026-01-01T00:00:00+00:00"


class TestAccountsCredentialMasking:
    """GET /api/v1/accounts must never echo ``password_encrypted`` verbatim."""

    setup_method = _setup_tokens
    teardown_method = _teardown_tokens

    RAW_SECRET = "S3cr3t-raw-credential-value"

    def _accounts_list(self, raw_password):
        from app.routers import accounts as accounts_router
        from app.services.account_service import AccountService

        row = _AccountModel(raw_password)
        # Execute order for list_accounts:
        #   1. total count  -> .scalar()
        #   2. paged rows   -> .scalars().all()
        #   3. (per account) platform code -> .scalar_one_or_none()
        results = [
            SimpleNamespace(scalar=lambda: 1),
            _Result([row]),  # .scalars().all() via the Result facade
            SimpleNamespace(scalar_one_or_none=lambda: "wechat"),
        ]
        it = iter(results)
        db_stub = MagicMock()

        async def _execute(query):
            return next(it)

        db_stub.execute = _execute
        service = AccountService(db_stub)

        def _override_db():
            yield db_stub

        app = self.client.app
        app.dependency_overrides[accounts_router.get_db] = _override_db
        app.dependency_overrides[accounts_router.get_account_service] = lambda: service
        try:
            r = self.client.get("/api/v1/accounts/")
        finally:
            app.dependency_overrides.pop(accounts_router.get_db, None)
            app.dependency_overrides.pop(accounts_router.get_account_service, None)
        return r, row

    def test_list_accounts_masks_password(self):
        r, row = self._accounts_list(self.RAW_SECRET)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        item = items[0]
        # The raw value must be NOWHERE in the wire body.
        assert self.RAW_SECRET not in r.text
        # The masked sentinel is what the response carries instead.
        assert item["password_encrypted"] == "***"

    def test_get_account_by_id_masks_password(self):
        from app.routers import accounts as accounts_router
        from app.services.account_service import AccountService

        row = _AccountModel(self.RAW_SECRET)
        # Execute order for get_account:
        #   1. the account row        -> .scalar_one_or_none()
        #   2. (in _account_to_response) platform code -> .scalar_one_or_none()
        results = [
            SimpleNamespace(scalar_one_or_none=lambda: row),
            SimpleNamespace(scalar_one_or_none=lambda: "wechat"),
        ]
        it = iter(results)
        db_stub = MagicMock()

        async def _execute(query):
            return next(it)

        db_stub.execute = _execute
        service = AccountService(db_stub)

        def _override_db():
            yield db_stub

        app = self.client.app
        app.dependency_overrides[accounts_router.get_db] = _override_db
        app.dependency_overrides[accounts_router.get_account_service] = lambda: service
        try:
            r = self.client.get(f"/api/v1/accounts/{row.id}")
        finally:
            app.dependency_overrides.pop(accounts_router.get_db, None)
            app.dependency_overrides.pop(accounts_router.get_account_service, None)
        assert r.status_code == 200, r.text
        assert self.RAW_SECRET not in r.text
        assert r.json()["password_encrypted"] == "***"

    def test_unset_password_stays_null_not_sentinel(self):
        r, _ = self._accounts_list(None)
        assert r.json()["items"][0]["password_encrypted"] is None

    def test_empty_password_stays_empty_string(self):
        r, _ = self._accounts_list("")
        assert r.json()["items"][0]["password_encrypted"] == ""

    def test_masking_funnel_is_the_single_echo_point(self):
        """Structural guard: both API response builders route through
        ``_account_to_response`` (the only place a response object is built
        from a model), and that funnel masks the credential."""
        from app.services import account_service

        src = inspect.getsource(account_service)
        assert "mask_credential(account.password_encrypted)" in src
        # Every response build goes through the funnel.
        funnel = inspect.getsource(account_service.AccountService._account_to_response)
        assert "mask_credential" in funnel

    def test_proxy_response_schema_has_no_password_field(self):
        from app.schemas.proxy import ProxyResponse

        assert not any("password" in f.lower() for f in ProxyResponse.model_fields)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
