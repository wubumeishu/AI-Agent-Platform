"""QA t_3eb34805: Phase 2 AI+Backend integration test app.

Built WITHOUT app.main because main.py currently imports the workflow
task's untracked app/services/workflow.py, which raises
NameError(WorkflowDetailResponse) - a P0 blocker outside this task's scope.

Mounts the Phase 2 AI routers standalone so integration tests can run.
NOTE: this app intentionally mounts memory/intents/decision WITHOUT the
extra /api/v1 prefix to EXPOSE the double-prefix bug documented in
t_91bc7e7f's hotspot note (bug lives in main.py, not in this app).
"""
from fastapi import FastAPI

from app.routers.conversations import router as conversations_router
from app.routers.intents import router as intents_router
from app.routers.memory import router as memory_router
from app.routers.decision import router as decision_router

qa_app = FastAPI(title="QA Phase2 AI Test App", version="qa-t_3eb34805")

# Mount WITHOUT the /api/v1 outer prefix so the double-prefix defect
# (routers already carry /api/v1/...) is observable exactly as it would
# break under main.py: request /api/v1/memory/... hits a single-prefix
# path here = the CORRECT path; /api/v1/api/v1/memory = the broken one.
qa_app.include_router(conversations_router, prefix="/api/v1")
qa_app.include_router(intents_router)
qa_app.include_router(memory_router)
qa_app.include_router(decision_router)


@qa_app.get("/api/v1/health")
async def qa_health():
    return {"status": "ok", "service": "qa-phase2-ai"}
