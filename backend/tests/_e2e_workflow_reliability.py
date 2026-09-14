"""Real-Postgres E2E for the workflow-reliability fixes (t_0d7a076a).

Runs against ai_agent_platform_test (legacy-built schema; no alembic_version).
Covers the three acceptance scenarios:
  A. default fire end-to-end (engine enqueue -> consumer claim -> execute)
  B. crashed running task recovered at startup -> re-queued -> executed
  C. stuck running task swept to timeout by the auto-sweep -> re-queued -> executed

All DB access is via the app's real AsyncSessionLocal (DATABASE_URL -> test DB),
so this exercises the exact code the service runs, not mocks.
"""
import asyncio, os, sys, uuid
# Make ``app`` importable regardless of where the script is launched from
# (repo convention: this lives under tests/; the backend root is its parent).
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"
os.environ["WORKFLOW_TASK_SWEEP_INTERVAL"] = "3"
os.environ["SCHEDULER_WORKER"] = "1"


from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models.workflow import (
    Workflow, ExecutionLog, WorkflowTrigger, WorkflowCondition, WorkflowAction,
)
from app.db.models.workflow_runtime import WorkflowQueue, WorkflowScheduler
from app.db.models.workflow_task import WorkflowTask
from app.services.workflow_task import QueueWorkerEngine

PASS, FAIL = [], []
def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  OK  " if cond else " FAIL ") + name + (("  " + detail) if detail else ""), flush=True)

def now():
    return datetime.now(timezone.utc)

async def seed_default_queue():
    """Idempotently create the default scheduler queue (what migration 027 does)."""
    db = AsyncSessionLocal()
    async with db:
        existing = (await db.execute(select(WorkflowQueue).where(
            WorkflowQueue.name == "workflow-scheduler",
            WorkflowQueue.is_deleted == False))).scalar_one_or_none()
        if existing is not None:
            return existing.id
        q = WorkflowQueue(name="workflow-scheduler", workflow_id=None,
                          type="fifo", max_concurrency=1, retry_limit=0,
                          timeout_seconds=600, status="idle")
        db.add(q); await db.commit(); await db.refresh(q)
        return q.id

async def make_workflow():
    db = AsyncSessionLocal()
    async with db:
        wf = Workflow(name="e2e-wf-" + uuid.uuid4().hex[:8], status="active")
        db.add(wf); await db.commit(); await db.refresh(wf)
        trig = WorkflowTrigger(workflow_id=wf.id, trigger_type="manual", enabled=True)
        db.add(trig); await db.commit(); await db.refresh(trig)
        cond = WorkflowCondition(trigger_id=trig.id, expression={})  # vacuous pass
        db.add(cond); await db.commit(); await db.refresh(cond)
        act = WorkflowAction(condition_id=cond.id, action_type="custom", params={"kind": "e2e"})
        db.add(act); await db.commit(); await db.refresh(act)
        return wf.id

async def make_scheduler(queue_id, workflow_id):
    db = AsyncSessionLocal()
    async with db:
        s = WorkflowScheduler(name="e2e-sched-" + uuid.uuid4().hex[:8],
                              schedule_type="interval", interval_seconds=2,
                              enabled=True,
                              workflow_id=workflow_id,
                              next_run_at=now() + timedelta(seconds=1))
        db.add(s); await db.commit(); await db.refresh(s)
        return s.id

async def insert_running_task(queue_id, workflow_id, **kw):
    db = AsyncSessionLocal()
    async with db:
        t = WorkflowTask(queue_id=queue_id, workflow_id=workflow_id,
                         name="e2e-task", status="running",
                         payload={"origin": "scheduler"},
                         metadata_={"origin": "scheduler"}, **kw)
        db.add(t); await db.commit(); await db.refresh(t)
        return t.id

async def wait_until(pred, timeout=12.0, step=0.4):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await pred():
            return True
        await asyncio.sleep(step)
    return False

async def task_state(tid):
    db = AsyncSessionLocal()
    async with db:
        t = (await db.execute(select(WorkflowTask).where(WorkflowTask.id == tid))).scalar_one_or_none()
        return (t.status, t.retry_count, t.result) if t else None

async def main():
    from app.services.scheduler.engine import get_scheduler_engine
    from app.services.scheduler.consumer import SchedulerConsumer
    from app.services.scheduler import task_recovery

    print("== setup ==")
    qid = await seed_default_queue()
    wf = await make_workflow()
    sched = await make_scheduler(qid, wf)
    ok("seeded default queue workflow-scheduler", qid is not None, "id=" + str(qid))

    # ---- Scenario A: default fire end-to-end ----
    print("== A: engine fire -> consumer claim -> execute ==")
    eng = get_scheduler_engine()
    ok("default engine dispatcher require_queue=True",
       eng.dispatcher.require_queue is True)
    await eng.start()
    armed = await eng.load_schedules()
    ok("engine armed the persisted schedule", armed >= 1, f"armed={armed}")
    consumer = SchedulerConsumer(poll_seconds=0.5)
    await consumer.start()
    loop = task_recovery.get_task_recovery_loop()
    await loop.start(interval_seconds=3.0)

    def fired_success():
        async def _p():
            db = AsyncSessionLocal()
            async with db:
                rows = (await db.execute(select(WorkflowTask).where(
                    WorkflowTask.queue_id == qid,
                    WorkflowTask.metadata_["scheduler"].as_string() == str(sched),
                ))).scalars().all()
                return any(r.status == "success" for r in rows)
        return _p
    fired = await wait_until(fired_success(), timeout=15.0, step=0.5)
    db = AsyncSessionLocal()
    async with db:
        rows = (await db.execute(select(WorkflowTask).where(
            WorkflowTask.queue_id == qid,
            WorkflowTask.metadata_["scheduler"].as_string() == str(sched),
        ))).scalars().all()
        success_tasks = [t for t in rows if t.status == "success"]
    ok("A: scheduler fire enqueued + executed (task success)", bool(success_tasks),
       f"tasks={len(rows)} success={len(success_tasks)}")
    if success_tasks:
        r = success_tasks[0].result or {}
        ok("A: result carries the real executor routing",
           r.get("executor") == "scheduler-task"
           and (r.get("scheduler_run") or {}).get("ok") is True,
           f"executor={r.get('executor')}")

    # ---- Scenario B: crashed running task -> startup recovery -> executed ----
    print("== B: crash recovery of a running task ==")
    btask = await insert_running_task(
        qid, wf,
        claimed_at=now() - timedelta(hours=1),
        started_at=now() - timedelta(hours=1))
    db = AsyncSessionLocal()
    async with db:
        recovered = await QueueWorkerEngine(db).recover_stale_running()
    ok("B: recover_stale_running reset the stuck task to pending",
       recovered >= 1, f"recovered={recovered}")
    b_success = await wait_until(
        async_to(lambda: task_state(btask), lambda st: st and st[0] == "success"),
        timeout=12.0, step=0.5)
    b_status = await task_state(btask)
    ok("B: recovered task re-queued and executed to success",
       b_success, f"final={b_status[0] if b_status else None}")

    # ---- Scenario C: stuck running task -> auto-sweep -> timeout -> requeue ----
    print("== C: periodic sweep of a stuck running task ==")
    ctask = await insert_running_task(
        qid, wf,
        started_at=now() - timedelta(seconds=10),
        claimed_at=now() - timedelta(seconds=10),
        timeout_seconds=1, max_retries=2, retry_count=0)
    c_success = await wait_until(
        async_to(lambda: task_state(ctask), lambda st: st and st[0] == "success"),
        timeout=20.0, step=0.5)
    cst = await task_state(ctask)
    ok("C: auto-sweep timed out the stuck task, re-queued it, executed",
       c_success and cst is not None and cst[1] == 1,
       f"final_status={cst[0] if cst else None} retry_count={cst[1] if cst else None}")

    # ---- ExecutionLog observability: the fired run logged success ----
    db = AsyncSessionLocal()
    async with db:
        logs = (await db.execute(select(ExecutionLog).where(
            ExecutionLog.execution_type == "scheduler",
            ExecutionLog.status == "success",
            ExecutionLog.metadata_["scheduler"].as_string() == str(sched),
        ))).scalars().all()
    ok("A: scheduler fire recorded a success ExecutionLog (traceable)",
       len(logs) >= 1, f"log_rows={len(logs)}")

    # ---- teardown ----
    print("== teardown ==")
    await consumer.stop()
    await loop.stop()
    await eng.stop()
    db = AsyncSessionLocal()
    async with db:
        await db.execute(delete(WorkflowTask).where(
            WorkflowTask.queue_id == qid, WorkflowTask.name == "e2e-task"))
        fired_ids = (await db.execute(select(WorkflowTask.id).where(
            WorkflowTask.queue_id == qid,
            WorkflowTask.metadata_["scheduler"].as_string() == str(sched)))).scalars().all()
        if fired_ids:
            await db.execute(delete(WorkflowTask).where(WorkflowTask.id.in_(fired_ids)))
        await db.execute(delete(WorkflowScheduler).where(WorkflowScheduler.id == sched))
        # child rows first (action -> condition -> trigger -> workflow)
        trig_ids = (await db.execute(select(WorkflowTrigger.id).where(
            WorkflowTrigger.workflow_id == wf))).scalars().all()
        if trig_ids:
            await db.execute(delete(WorkflowAction).where(
                WorkflowAction.condition_id.in_(
                    select(WorkflowCondition.id).where(
                        WorkflowCondition.trigger_id.in_(trig_ids)))))
            await db.execute(delete(WorkflowCondition).where(
                WorkflowCondition.trigger_id.in_(trig_ids)))
        await db.execute(delete(WorkflowTrigger).where(WorkflowTrigger.workflow_id == wf))
        await db.execute(delete(Workflow).where(Workflow.id == wf))
        await db.execute(delete(ExecutionLog).where(
            ExecutionLog.metadata_["scheduler"].as_string() == str(sched)))
        await db.commit()
    sys.stdout.flush()
    print("\n=== RESULT: %d passed, %d failed ===" % (len(PASS), len(FAIL)), flush=True)
    if FAIL:
        print("FAILED:", FAIL, flush=True)
        sys.stdout.flush()
        os._exit(2)
    sys.stdout.flush()
    os._exit(0)

def async_to(state_fn, cond):
    async def _p():
        st = await state_fn()
        return cond(st)
    return _p

asyncio.get_event_loop().run_until_complete(main())
