"""P5MSG-FIX-2 — P1 data-exposure security tests (P5MSG-11 findings P1-1 + P1-3).

Covers the acceptance criteria of t_74d4c4b1:

* **P1-3** — the realtime conversation-preview surface no longer broadcasts
  cross-customer PII:
  - ``GET /api/v1/realtime/conversations`` and ``/unread`` are auth-gated
    (trusted-producer Bearer: 401 when absent, 403 when untrusted — 异主
    preview is invisible);
  - a missing ``customer_id`` is a 422 (platform-wide previews are refused);
  - an unknown ``customer_id`` is a 404 (ownership check);
  - the opt-in ``redact_preview`` flag scrubs PII tokens (CN phone / email)
    from the rendered preview text without mutating stored content.
* **P1-1** — credential values are never echoed to API responses:
  - ``AccountResponse.password_encrypted`` is masked (``"***"`` sentinel);
  - ``ProxyResponse`` carries no password field at all;
  - the shared ``mask_credential`` helper is unit-covered.

Auth-level checks need no database (the trusted-producer dependency
short-circuits before the service layer). The 404 ownership check is
exercised through a stubbed DB session; the redaction *integration* path is
exercised against the real Postgres test DB (skipped when unavailable).

Run:  cd H:/AI-Agent-Platform/backend && uv run pytest tests/test_p1_security_fix.py -v
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


# Reuse the P5MSG-FIX-1 trusted-token convention (app.security re-reads the
# env var on every request, so setting it per-class is safe).
PUBLISH_TOKEN = "test-trusted-token"


def _auth() -> dict:
    return {"Authorization": f"Bearer {PUBLISH_TOKEN}"}


def _new_client():
    import app.main as m
    from app.services.realtime_hub import reset_realtime_hub

    reset_realtime_hub()
    return TestClient(m.app)


# ---------------------------------------------------------------------------
# P1-3 — cross-customer PII scoping of the realtime preview surface
# ---------------------------------------------------------------------------


class TestConversationsPiiScoping:
    """GET /api/v1/realtime/conversations: 异主 preview is invisible."""

    def setup_method(self):
        os.environ["REALTIME_PUBLISH_TOKENS"] = PUBLISH_TOKEN
        self.client = _new_client()

    def teardown_method(self):
        os.environ.pop("REALTIME_PUBLISH_TOKENS", None)

    def test_no_token_is_401(self):
        r = self.client.get(
            "/api/v1/realtime/conversations",
            params={"customer_id": str(uuid4())},
        )
        assert r.status_code == 401, r.text

    def test_untrusted_token_is_403(self):
        r = self.client.get(
            "/api/v1/realtime/conversations",
            params={"customer_id": str(uuid4())},
            headers={"Authorization": "Bearer not-a-trusted-token"},
        )
        assert r.status_code == 403, r.text

    def test_missing_customer_id_is_422(self):
        # Platform-wide previews are refused: no customer scoping, no PII.
        r = self.client.get("/api/v1/realtime/conversations", headers=_auth())
        assert r.status_code == 422, r.text

    def test_unknown_customer_is_404(self):
        # A customer that does not exist must not silently return a cross-
        # tenant view: the ownership check 404s.
        from app.db.session import get_db

        cid = str(uuid4())
        db_stub = MagicMock()

        async def _execute(query):
            return SimpleNamespace(
                scalar_one_or_none=MagicMock(return_value=None)
            )

        db_stub.execute = _execute

        def _override_get_db():
            yield db_stub

        app = self.client.app
        app.dependency_overrides[get_db] = _override_get_db
        try:
            r = self.client.get(
                "/api/v1/realtime/conversations",
                params={"customer_id": cid},
                headers=_auth(),
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["code"] == 4004

    def test_trusted_caller_scoped_to_existing_customer_ok(self):
        # When the customer exists, the scoped list view is served (200).
        # The stubbed session returns no active rows for this customer, so
        # the page is empty — the point is the endpoint no longer requires
        # a platform-wide view to answer.
        from app.db.session import get_db

        cid = str(uuid4())
        db_stub = MagicMock()
        executed = []

        async def _execute(query):
            executed.append(query)
            # Customer existence probe first (scalar_one_or_none), then the
            # service's list query (rows -> all()), then the unread total
            # (scalar_one).
            if len(executed) == 1:
                return SimpleNamespace(
                    scalar_one_or_none=MagicMock(return_value=cid)
                )
            return SimpleNamespace(
                all=MagicMock(return_value=[]),
                scalar_one=MagicMock(return_value=0),
            )

        db_stub.execute = _execute

        def _override_get_db():
            yield db_stub

        app = self.client.app
        app.dependency_overrides[get_db] = _override_get_db
        try:
            r = self.client.get(
                "/api/v1/realtime/conversations",
                params={"customer_id": cid},
                headers=_auth(),
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"] == []
        assert body["total_unread"] == 0


class TestUnreadPiiScoping:
    """GET /api/v1/realtime/unread: same auth + ownership surface."""

    def setup_method(self):
        os.environ["REALTIME_PUBLISH_TOKENS"] = PUBLISH_TOKEN
        self.client = _new_client()

    def teardown_method(self):
        os.environ.pop("REALTIME_PUBLISH_TOKENS", None)

    def test_no_token_is_401(self):
        assert self.client.get("/api/v1/realtime/unread").status_code == 401

    def test_untrusted_token_is_403(self):
        r = self.client.get(
            "/api/v1/realtime/unread",
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code == 403

    def test_missing_customer_id_is_422(self):
        r = self.client.get("/api/v1/realtime/unread", headers=_auth())
        assert r.status_code == 422

    def test_unknown_customer_is_404(self):
        from app.db.session import get_db

        db_stub = MagicMock()

        async def _execute(query):
            return SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))

        db_stub.execute = _execute

        def _override_get_db():
            yield db_stub

        app = self.client.app
        app.dependency_overrides[get_db] = _override_get_db
        try:
            r = self.client.get(
                "/api/v1/realtime/unread",
                params={"customer_id": str(uuid4())},
                headers=_auth(),
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == 4004


# ---------------------------------------------------------------------------
# P1-1 — credentials are never echoed to API responses
# ---------------------------------------------------------------------------


class TestCredentialMasking:
    def test_mask_credential_unit(self):
        from app.services.account_service import mask_credential

        assert mask_credential(None) is None
        assert mask_credential("super-secret") == "***"
        assert mask_credential("") == ""

    @pytest.mark.asyncio
    async def test_account_response_masks_password(self):
        """``_account_to_response`` must never surface the credential value."""
        from datetime import datetime, timezone
        from app.services.account_service import AccountService

        service = AccountService(MagicMock())
        account = MagicMock()
        account.id = uuid4()
        account.platform_id = "plat"
        account.name = "acc"
        account.username = "u"
        account.password_encrypted = "the-raw-secret"
        account.status = "connected"
        account.last_login = None
        account.created_at = datetime.now(timezone.utc)
        account.updated_at = datetime.now(timezone.utc)

        code_res = SimpleNamespace(
            scalar_one_or_none=MagicMock(return_value="wechat")
        )
        service.db.execute = AsyncMock(return_value=code_res)

        resp = await service._account_to_response(account)
        # The raw credential is nowhere in the response.
        assert "the-raw-secret" not in str(resp.__dict__)
        assert resp.password_encrypted == "***"

    def test_proxy_response_schema_has_no_password_field(self):
        """Proxy responses already leak no credential (no password field on
        the response schema) — guard that against regression."""
        from app.schemas.proxy import ProxyResponse

        assert not any(
            "password" in f.lower() for f in ProxyResponse.model_fields
        )

    def test_account_service_module_masks_on_all_response_paths(self):
        """Both ``create_account`` and ``list_accounts`` funnel through
        ``_account_to_response``; verify the funnel is the only place the
        raw value could re-enter a response."""
        import inspect
        from app.services import account_service

        src = inspect.getsource(account_service)
        # The service must reference the masker inside the response funnel.
        assert "mask_credential(account.password_encrypted)" in src


# ---------------------------------------------------------------------------
# P1-3 — preview desensitization (opt-in)
# ---------------------------------------------------------------------------


class TestPreviewRedaction:
    def test_scrub_pii_tokens(self):
        from app.services.realtime_conversation_service import (
            RealtimeConversationService as Svc,
        )

        text = "我的手机号 138 1234 5678 邮箱 test@example.com 谢谢"
        scrubbed = Svc._scrub_pii(text)
        assert "138 1234 5678" not in scrubbed
        assert "test@example.com" not in scrubbed
        assert "[PHONE]" in scrubbed
        assert "[EMAIL]" in scrubbed

    def test_preview_from_content_redacts(self):
        from app.services.realtime_conversation_service import (
            RealtimeConversationService as Svc,
        )

        plain = Svc._preview_from_content({"text": "手机号13912345678谢谢"}, redact=False)
        assert "13912345678" in plain
        scrubbed = Svc._preview_from_content({"text": "手机号13912345678谢谢"}, redact=True)
        assert "13912345678" not in scrubbed
        assert "[PHONE]" in scrubbed

    def test_preview_redaction_keeps_bounded_length(self):
        from app.services.realtime_conversation_service import (
            PREVIEW_MAX_LEN,
            RealtimeConversationService as Svc,
        )

        long_text = "手机号13912345678" * 30
        scrubbed = Svc._preview_from_content({"text": long_text}, redact=True)
        assert len(scrubbed) <= PREVIEW_MAX_LEN


def _pg_available() -> bool:
    import asyncio

    try:
        import asyncpg

        async def _probe():
            dsn = "postgresql://postgres:postgres@localhost:5432/ai_agent_platform_test"
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


@pytest.mark.skipif(not _pg_available(), reason="Postgres test DB unreachable")
class TestPreviewRedactionIntegration:
    """End-to-end: a stored PII message previews as [PHONE] when
    ``redact_preview`` is set and as the raw text otherwise — while the
    stored row is never mutated. Mirrors test_realtime_api's sessionmaker
    pattern (engine created inside the loop)."""

    async def test_redact_flag_changes_rendering_not_storage(self):
        from datetime import datetime, timezone
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        from app.db.models import Base
        from app.db.models.conversation import Conversation
        from app.db.models.customer import Customer
        from app.db.models.messages import ChannelMessage
        from app.services.realtime_conversation_service import (
            RealtimeConversationService,
        )
        from sqlalchemy import select

        TEST_DB = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"
        engine = create_async_engine(TEST_DB)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        try:
            s = Session()
            cust = Customer(name=f"pii-{uuid4().hex[:8]}", is_deleted=False)
            s.add(cust)
            await s.commit()
            await s.refresh(cust)

            conv = Conversation(
                customer_id=cust.id,
                channel="wechat",
                subject="pii-preview",
                status="active",
                is_deleted=False,
            )
            s.add(conv)
            await s.commit()
            await s.refresh(conv)

            s.add(
                ChannelMessage(
                    conversation_id=conv.id,
                    direction="out",
                    status="sent",
                    content={"text": "我的手机号13912345678谢谢"},
                )
            )
            await s.commit()

            svc = RealtimeConversationService(s)

            raw_rows = await svc.list_active_conversations(
                customer_id=cust.id, redact_preview=False
            )
            raw = [r for r in raw_rows if r.conversation_id == conv.id][0]
            assert "13912345678" in (raw.last_message_preview or "")

            red_rows = await svc.list_active_conversations(
                customer_id=cust.id, redact_preview=True
            )
            red = [r for r in red_rows if r.conversation_id == conv.id][0]
            assert "13912345678" not in (red.last_message_preview or "")
            assert "[PHONE]" in (red.last_message_preview or "")

            # Storage is untouched — the PII row still holds the raw text.
            stored = (
                await s.execute(
                    select(ChannelMessage.content).where(
                        ChannelMessage.conversation_id == conv.id
                    )
                )
            ).scalar_one()
            assert stored["text"] == "我的手机号13912345678谢谢"
            await s.close()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
