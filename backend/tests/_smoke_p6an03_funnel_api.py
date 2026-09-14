"""P6AN-03 funnel endpoint: real-DB API smoke (opt-in scratch).

Seeds a deterministic agent/customer/lead fixture, then calls the *actual*
route handler ``compute_acquisition_funnel`` directly with a real session
(same event loop as the engine — no TestClient portal, which would create a
second loop). Verifies the response schema + the filter chain end-to-end.
"""
import os, sys, asyncio, uuid
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_ROOT)
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"

from sqlalchemy import delete
from app.routers.analytics import compute_acquisition_funnel
from app.db.session import AsyncSessionLocal
from app.db.models.lead import Lead
from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.customer import Customer


async def main():
    tag = "p6an03_smoke_" + uuid.uuid4().hex[:5]
    db = AsyncSessionLocal()
    async with db:
        ag = Agent(name="smoke_" + tag, status="active")
        db.add(ag); await db.flush()
        c = Customer(name="smoke_cust_" + tag)
        db.add(c); await db.flush()
        db.add(AgentCustomerBinding(agent_id=ag.id, customer_id=c.id)); await db.flush()
        for status, n in [("new", 3), ("contacted", 2), ("converted", 1)]:
            for _ in range(n):
                db.add(Lead(customer_id=c.id, status=status, source_type="smoke", operator=tag))
        await db.commit()
        agent_id = ag.id
        session = AsyncSessionLocal()

    async with session:
        # 1. default (30d, no filter)
        body = await compute_acquisition_funnel(
            agent_id=None, platform_id=None, range="30d",
            from_date=None, to_date=None, funnel_code=None, db=session,
        )
        print("default range:", body["filters"]["range"], "stages:", len(body["stages"]))
        assert body["filters"]["range"] == "30d"

        # 2. agent-scoped, range=all -> 6 leads; reached new=6, contacted=3, qualified=1, converted=1
        body = await compute_acquisition_funnel(
            agent_id=agent_id, platform_id=None, range="all",
            from_date=None, to_date=None, funnel_code=None, db=session,
        )
        by = {s["key"]: s for s in body["stages"]}
        print("agent-scoped total:", body["total"],
              {k: by[k]["count"] for k in by})
        assert body["total"] == 6, body
        assert by["new"]["count"] == 6
        assert by["contacted"]["count"] == 3
        assert by["qualified"]["count"] == 1
        assert by["converted"]["count"] == 1
        assert by["converted"]["overall_rate"] == round(1 / 6, 4)

        # 3. unknown agent -> empty funnel, no crash
        body = await compute_acquisition_funnel(
            agent_id=uuid.uuid4(), platform_id=None, range="all",
            from_date=None, to_date=None, funnel_code=None, db=session,
        )
        print("unknown-agent total:", body["total"])
        assert body["total"] == 0 and body["conversion_rate"] is None

    # cleanup
    db = AsyncSessionLocal()
    async with db:
        await db.execute(delete(Lead).where(Lead.operator == tag))
        await db.commit()

    print("\nAPI SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
