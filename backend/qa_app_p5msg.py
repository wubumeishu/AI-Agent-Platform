"""QA P5MSG-09: full app + re-mounted shelved conversations router.

app.main shelves the Phase-2 conversations router (P1-003 shelved comment).
P5MSG-09's vertical loop requires 创建会话 -> POST /conversations, so we mount
the SAME real router module on the SAME real app.main instance. Everything else
is the production app.main (realtime, messages, channels, customers, crm, ...).
"""
from app.main import app
from app.routers.conversations import router as conversations_router

# Re-mount the real conversation-management router (shelved in main.py) so the
# P5MSG vertical closed loop (create conversation -> send message -> state ->
# realtime push -> customer 360) is exercised end to end on the live app.
app.include_router(conversations_router, prefix="/api/v1")
