"""
Main FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import engine, get_db
from app.crm.routers import router as crm_router
from app.crm.routers.customer_360 import router as customer_360_router
from app.crm.routers.customer_messages import router as customer_messages_router  # P5MSG-05
from app.crm.routers.customer import router as customer_router
from app.routers.accounts import router as accounts_router
from app.routers.personas import router as personas_router
from app.routers.private_domain import router as private_domain_router
from app.routers.browsers import router as browsers_router
from app.routers.prompt_templates import router as prompt_templates_router
from app.routers.conversations import router as conversations_router
from app.crm.routers.tag import router as tag_router
from app.routers.agents import router as agents_router
from app.routers.intents import router as intents_router
from app.routers.memory import router as memory_router
from app.routers.decision import router as decision_router
from app.routers.workflow import router as workflow_execution_log_router
from app.routers.workflow_config import router as workflow_config_router
from app.routers.workflow_framework import router as workflow_framework_router
from app.routers.workflow_task import router as workflow_task_router
from app.routers.scheduler import router as scheduler_router
from app.routers.platforms import router as platforms_router
from app.routers.proxies import router as proxies_router
from app.routers.workflow_crm import router as workflow_crm_router
from app.routers.content_generation import router as content_generation_router
from app.routers.realtime import router as realtime_router
from app.routers.messages import router as messages_router  # P5MSG-01 skeleton; P5MSG-02 builds the API on it
from app.routers.channels import router as channels_router  # P5MSG-01 channel-config skeleton (P5MSG-03 implements)

app = FastAPI(
    title="AI Agent Platform",
    description="AI Agent Platform - Resource Layer (Agent, Persona, Account, Platform, Browser, Proxy) + Private Domain",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(crm_router, prefix="/api/v1")
app.include_router(customer_360_router, prefix="/api/v1/customers")
# P5MSG-05: customer 360 message-timeline view (GET /api/v1/customers/{id}/messages)
app.include_router(customer_messages_router, prefix="/api/v1/customers")
app.include_router(customer_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")
app.include_router(personas_router, prefix="/api/v1")
app.include_router(private_domain_router, prefix="/api/v1")
app.include_router(browsers_router, prefix="/api/v1")
app.include_router(prompt_templates_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(tag_router, prefix="/api/v1")
# The AI-tier routers below self-carry their full `/api/v1/...` prefix on the
# APIRouter (agents/intents/memory/decision), so they are mounted BARE here —
# adding another `/api/v1` would produce the /api/v1/api/v1 double-prefix defect
# (same class as the P1-2 CRM bug in t_b6b64212). This matches the tested
# mounting convention in qa_phase2_app.py and the route-path assertions in
# tests/test_{decision,intent,memory}_api.py (router routes keep /api/v1/...).
app.include_router(agents_router)
app.include_router(intents_router)
app.include_router(memory_router)
app.include_router(decision_router)
app.include_router(content_generation_router)
app.include_router(workflow_execution_log_router, prefix="/api/v1")
app.include_router(workflow_config_router, prefix="/api/v1")
app.include_router(workflow_framework_router, prefix="/api/v1")
app.include_router(workflow_task_router, prefix="/api/v1")
app.include_router(scheduler_router, prefix="/api/v1")
app.include_router(platforms_router, prefix="/api/v1")
app.include_router(proxies_router, prefix="/api/v1")
app.include_router(workflow_crm_router)
app.include_router(messages_router, prefix="/api/v1")  # P5MSG-02: channel message API + delivery states
app.include_router(channels_router, prefix="/api/v1")  # P5MSG-01: channel-config skeleton (P5MSG-03 implements)
# P5MSG-04: realtime channel (SSE /api/v1/realtime) + conversation-management
# read endpoints (active list / preview / unread). Router self-carries /realtime;
# the /api/v1 outer prefix yields /api/v1/realtime.
app.include_router(realtime_router, prefix="/api/v1")


# Workflow-CRM integration: register the executor as a subscriber for all CRM
# domain events (lead.status_changed / lead.stage_changed / lead.tags_changed /
# customer.tag_changed / lead.created / customer.created). Idempotent; the
# executor re-reads live CRM state at match time so a failing/queued event
# never corrupts the publisher's request.
try:
    from app.services.workflow_crm import register_workflow_crm_subscriber
    register_workflow_crm_subscriber()
except Exception:
    import logging as _wf_crm_logging
    _wf_crm_logging.getLogger(__name__).exception(
        "workflow-crm subscriber registration failed; integration disabled"
    )

# P5MSG-04 realtime bus bridge: forward channel-message events published on the
# shared domain bus (P5MSG-02/03 producers) to the realtime hub so live SSE
# subscribers see new-message / read / status events. Redundant with the direct
# publish seam (POST /realtime/publish); best-effort, never blocks publishers.
try:
    from app.services.realtime_events import register_realtime_bus_bridge
    register_realtime_bus_bridge()
except Exception:
    import logging as _rt_logging
    _rt_logging.getLogger(__name__).exception(
        "realtime bus bridge registration failed; /api/v1/realtime SSE push disabled"
    )


# Request-scoped autoflush: after each non-streaming request, dispatch any CRM
# domain events queued during that request so workflows fire without a manual
# POST /workflow-crm/dispatch-now call.
#
# Implemented as a native ASGI middleware (NOT BaseHTTPMiddleware): the latter
# buffers response bodies and would break streaming endpoints (the SSE
# /api/v1/conversations/{id}/messages/stream added by P1-003). SSE paths are
# detected and skipped; for everything else we flush after the response is sent.
# Best-effort: a flush failure must never turn a successful request into a 500.
from app.services.crm_events import get_crm_publisher

# Paths whose responses are streamed (SSE) and must NOT be flushed by us.
_SSE_PATH_MARKERS = ("/messages/stream", "/realtime")


class _WorkflowCrmAutoflush:
    """Native ASGI middleware flushing the CRM event bus after requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        is_sse = any(marker in path for marker in _SSE_PATH_MARKERS)
        await self.app(scope, receive, send)

        if is_sse:
            return

        try:
            await get_crm_publisher().flush()
        except Exception:
            import logging
            logging.getLogger("workflow_crm.autoflush").exception(
                "post-response workflow-crm flush failed (path=%s)", path
            )


app.add_middleware(_WorkflowCrmAutoflush)


@app.on_event("startup")
async def startup():
    """应用启动时初始化数据库 + 做一次快速 DB 可达性检查。

    Fail loudly at boot: if the configured DATABASE_URL cannot reach Postgres,
    log a loud WARNING with the *redacted* DSN so the misconfig is visible the
    moment the service starts (instead of surfacing later as scattered 500s on
    any DB-backed request). With ``DB_REQUIRED_ON_STARTUP=1`` the boot REFUSES
    to come up instead (hard-fail), for deployments that want no half-working
    process.
    """
    from app.db.models import Base
    # 创建所有表（仅在开发环境）
    # await Base.metadata.create_all(bind=engine)

    # Fast DB reachability check (bounded; never blocks boot indefinitely).
    import logging
    from app.config import db_required_on_startup
    from app.db.session import db_ping, redact_dsn, DATABASE_URL

    log = logging.getLogger("app.startup")
    ok, detail = await db_ping(timeout=5.0)
    if ok:
        log.info("DB reachable at boot: %s", redact_dsn(DATABASE_URL))
    else:
        log.warning(
            "DB NOT reachable at boot — %s | DSN=%s. DB-backed requests will 500 "
            "until the database is up / DATABASE_URL is fixed. Set "
            "DB_REQUIRED_ON_STARTUP=1 to refuse startup when the DB is down.",
            detail,
            redact_dsn(DATABASE_URL),
        )
        if db_required_on_startup():
            raise RuntimeError(
                f"DB_REQUIRED_ON_STARTUP is set but the database is unreachable "
                f"(DSN={redact_dsn(DATABASE_URL)}): {detail}"
            )

    # Workflow <-> Conversation bridge: real conversation/intent events run
    # active event-triggered workflows end-to-end (auto-reply / follow-up).
    # Mirrors the CRM executor's bus wiring — each event gets its own DB
    # session so the workflow side never holds a publisher's transaction.
    from app.services.workflow_conversation_bridge import (
        register_workflow_conversation_subscriber,
    )
    register_workflow_conversation_subscriber()

    # CRM Conversation -> Lead auto-generation (t_crm_007): when the intent
    # classifier emits a high-intent ``intent.classified`` event, capture a
    # CRM Lead for the conversation's customer (with customer-level dedup).
    # A SEPARATE subscriber from the workflow-conversation bridge — both react
    # to ``intent.classified`` but run independent handlers on their own DB
    # sessions, so a failing lead capture can never disturb workflow auto-reply.
    from app.crm.services.conversation_lead_bridge import (
        register_conversation_lead_subscriber,
    )
    register_conversation_lead_subscriber()

    # P5MSG-05: CRM message-event write-back — every ``message.created``
    # event records a read-only CRM ActivityLog row (Customer 360 activity
    # feed), idempotently (duplicate events are no-ops). Own DB session per
    # event, bus-safe, so a failing write-back never disturbs the shared
    # message-event delivery.
    from app.crm.services.message_crm_writeback import (
        register_crm_message_writeback_subscriber,
    )
    register_crm_message_writeback_subscriber()

    # P5MSG-05: AI-intent data landing — the latest ``intent.classified``
    # result for a conversation lands on its ``metadata_["last_intent"]``
    # (idempotent upsert). A separate subscriber so intent landing and lead
    # capture / workflow reply stay independent.
    from app.services.intent_conversation_lander import (
        register_intent_conversation_lander,
    )
    register_intent_conversation_lander()


@app.on_event("shutdown")
async def shutdown():
    """优雅停止调度引擎（t_wf_003），避免后台 task 泄漏。

    引擎默认不自动启动：由 POST /api/v1/schedulers/engine/start 显式
    启动（V1 单机、可控启停语义）。关闭时如仍在运行则等待其结束。
    """
    from app.services.scheduler.engine import get_scheduler_engine
    await get_scheduler_engine().close()


@app.get("/api/v1/health")
async def health_check():
    """Service liveness + a live, bounded DB reachability check.

    ``status`` reports the *process* (always "ok" once we're serving HTTP).
    The DB state is a first-class field so the credential-free-DSN class of
    misconfig is visible in one glance instead of surfacing as scattered 500s.
    A live but unreachable DB does NOT make the whole endpoint 500 — see the
    strict ``/api/v1/health/db`` for a monitor-friendly pass/fail probe.
    """
    from app.db.session import db_ping, redact_dsn, DATABASE_URL

    db_ok, db_detail = await db_ping(timeout=3.0)
    return {
        "status": "ok",
        "service": "ai-agent-platform",
        "database": {
            "reachable": db_ok,
            "dsn": redact_dsn(DATABASE_URL),
            "detail": db_detail,
        },
        "database_reachable": db_ok,
    }


@app.get("/api/v1/health/db")
async def health_check_db():
    """Strict DB probe: 200 when reachable, 503 when not.

    For health-checkers / load-balancers / CI that want a hard signal.
    The error body is safe to expose: no DSN password, just the error class +
    message and the redacted DSN.
    """
    from fastapi import status as http_status
    from fastapi.responses import JSONResponse
    from app.db.session import db_ping, redact_dsn, DATABASE_URL

    db_ok, db_detail = await db_ping(timeout=5.0)
    payload = {
        "reachable": db_ok,
        "dsn": redact_dsn(DATABASE_URL),
        "detail": db_detail,
    }
    if db_ok:
        return payload
    return JSONResponse(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


@app.get("/")
async def root():
    return {
        "message": "AI Agent Platform API",
        "docs": "/docs",
        "endpoints": {
            "lifecycle": "/api/v1/crm/lifecycle/stages",
            "customer_360": "/api/v1/customers/360/{customer_id}",
            "customers": "/api/v1/crm/customers",
            "accounts": "/api/v1/accounts",
            "private_domain": "/api/v1/private-domain/channels",
            "platforms": "/api/v1/platforms",
            "proxies": "/api/v1/proxies",
            "decision": "/api/v1/decision/decide",
            "execution_logs": "/api/v1/execution-logs",
            "health": "/api/v1/health",
        }
    }
