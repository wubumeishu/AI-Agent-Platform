"""P5MSG-01 — Message 模块后端框架与数据 Schema: basic acceptance tests.

Scope of P5MSG-01 (per card): the ``messages`` table + Alembic migration, the
FastAPI route skeleton (``/api/v1/messages``, ``/api/v1/channels``), the
Pydantic schemas, and the standard ``{code, message, data}`` envelope with a
unified not-implemented code ``4001``.

Coordination note (shared non-git backend dir, P5MSG-01/02/03/04 siblings):
P5MSG-02 (t_ac5cd055) builds the *real* query / send / state-machine API on the
P5MSG-01 surface — it owns ``app/routers/messages.py`` +
``tests/test_message_delivery.py``. P5MSG-03 owns the channel adapter + the
``/api/v1/channels`` config CRUD. So this P5MSG-01 test file is scoped ONLY to
what P5MSG-01 owns deterministically:

  * route registration (``/api/v1/messages`` + ``/api/v1/channels`` exist),
  * the P5MSG-01 *channel-config skeleton* (``/api/v1/channels``) still answers
    with the unified 4001 envelope (its impl is P5MSG-03's, not P5MSG-01's),
  * the ``{code, message, data}`` envelope helpers,
  * the Pydantic schemas + value-domain validation,
  * the ``ChannelMessage`` model + the 022 migration DDL (offline).

It never requires a live Postgres, and never depends on P5MSG-02/03/04 having
landed, so it stays green in isolation.

Run:
    pytest tests/test_message_skeleton.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.routers.channels import router as channels_router
from app.schemas.messages import (
    MESSAGE_CHANNELS,
    MESSAGE_RECEIPT_SOURCES,
    MessageSendRequest,
    MessageStatusUpdateRequest,
    ChannelConfigResponse,
    ok,
    not_implemented,
    bad_request,
    ApiCode,
)
from app.db.models import ChannelMessage
from app.db.models.messages import MESSAGE_DIRECTIONS, MESSAGE_STATUSES

BACKEND_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"


# ---------------------------------------------------------------------------
# 1. Route registration (P5MSG-01 contract: both P5MSG paths reachable)
# ---------------------------------------------------------------------------
def test_p5msg01_routes_registered_in_app():
    """The full platform app registers BOTH P5MSG-01 paths
    (``/api/v1/messages`` and ``/api/v1/channels``). Importing app.main also
    confirms the whole shared tree (P5MSG-01..04) is importable.

    The authoritative reachable surface is the OpenAPI spec — a naive
    ``app.routes`` walk misses the paths because this FastAPI version wraps
    included routers in a lazy ``_IncludedRouter`` object (P5MSG-02 documented
    the same limitation). OpenAPI expansion resolves every included router, so
    it is the stable, version-proof check.
    """
    import app.main as m

    paths = set(m.app.openapi()["paths"].keys())
    assert "/api/v1/messages" in paths, "P5MSG-01 /api/v1/messages not registered"
    assert "/api/v1/channels" in paths, "P5MSG-01 /api/v1/channels not registered"


# ---------------------------------------------------------------------------
# 2. The /api/v1/channels router is IMPLEMENTED (P5MSG-03 replaced the 4001
#    skeleton P5MSG-01 shipped, so the not-implemented premise is obsolete)
# ---------------------------------------------------------------------------
def test_channels_router_is_implemented():
    """P5MSG-03 replaced the P5MSG-01 4001 channel-config skeleton with the real
    CRUD + delivery surface. Confirm the implemented router exposes those
    concrete routes (not a not-implemented stub). Deterministic — reads the
    router's own table, no DB / no app wiring."""
    routes = {r.path for r in channels_router.routes}
    for expected in ("/channels", "/channels/{channel_id}",
                     "/channels/deliver", "/channels/poll"):
        assert expected in routes, f"implemented channels route missing: {expected}"


# ---------------------------------------------------------------------------
# 3. Envelope helpers produce the PHASE1-API-SPEC {code, message, data} shape
# ---------------------------------------------------------------------------
def test_ok_envelope_shape():
    payload = {"id": "x"}
    env = ok(payload)
    assert env == {"code": 0, "message": "success", "data": payload}
    assert ok(None)["data"] is None
    assert ok(payload, message="done")["message"] == "done"


def test_not_implemented_envelope():
    exc = not_implemented("GET /x")
    assert exc.status_code == 501
    assert exc.detail["code"] == 4001
    assert "GET /x" in exc.detail["message"]
    assert exc.detail["data"] is None


def test_bad_request_envelope():
    exc = bad_request("bad param")
    assert exc.status_code == 400
    assert exc.detail["code"] == ApiCode.INVALID_PARAMETER == 4002
    assert exc.detail["message"] == "bad param"


# ---------------------------------------------------------------------------
# 4. Pydantic schema validation (value domains)
# ---------------------------------------------------------------------------
def test_message_send_request_valid():
    req = MessageSendRequest(
        conversation_id="00000000-0000-0000-0000-000000000000",
        channel="wechat",
        direction="out",
        content={"text": "hi"},
    )
    assert req.direction == "out"
    assert req.content == {"text": "hi"}


def test_message_send_request_rejects_bad_domains():
    base = dict(conversation_id="00000000-0000-0000-0000-000000000000",
                content={"text": "hi"})
    with pytest.raises(Exception):
        MessageSendRequest(**base, channel="not_a_channel")
    with pytest.raises(Exception):
        MessageSendRequest(**base, direction="sideways")


def test_message_send_request_requires_nonempty_content():
    with pytest.raises(Exception):
        MessageSendRequest(
            conversation_id="00000000-0000-0000-0000-000000000000",
            content={},
        )


def test_status_update_requires_error_when_failed():
    with pytest.raises(Exception):
        MessageStatusUpdateRequest(status="failed")
    good = MessageStatusUpdateRequest(status="failed",
                                      error={"code": "E", "message": "x"})
    assert good.source == "manual"
    ok1 = MessageStatusUpdateRequest(status="sent")
    assert ok1.error is None


def test_value_domain_constants_are_consistent():
    assert MESSAGE_DIRECTIONS == ["in", "out"]
    assert set(MESSAGE_STATUSES) == {"queued", "sent", "delivered", "failed", "read"}
    assert "web" in MESSAGE_CHANNELS and "wechat" in MESSAGE_CHANNELS
    assert MESSAGE_RECEIPT_SOURCES == ["provider", "manual"]


# ---------------------------------------------------------------------------
# 5. Model / migration structural surface (offline, no DB)
# ---------------------------------------------------------------------------
def test_channel_message_model_fields():
    cols = {c.name for c in ChannelMessage.__table__.columns}
    expected = {
        "id", "conversation_id", "account_id", "agent_id", "channel",
        "direction", "status", "content", "provider_message_id",
        "sent_at", "received_at", "error", "created_at", "updated_at",
        "is_deleted",
    }
    assert expected.issubset(cols), f"missing P5MSG-01 fields: {expected - cols}"
    assert ChannelMessage.__tablename__ == "messages"


def test_migration_022_creates_messages_table_with_fk():
    """Offline structural check (test_phase1_db.py pattern): the 022 migration
    must carry the messages-table DDL + the conversation FK, so a clean
    Postgres upgrade materialises the P5MSG-01 schema."""
    src = (VERSIONS_DIR / "022_messages_channel.py").read_text(encoding="utf-8")
    assert re.search(r"create_table\(\s*['\"]messages['\"]", src), \
        "no create_table('messages')"
    for target in ("conversation.id", "account.id", "agent.id"):
        assert target in src, f"FK to {target} missing in 022"
    for col in ("provider_message_id", "sent_at", "received_at", "error"):
        assert col in src, f"column {col} missing in 022"
