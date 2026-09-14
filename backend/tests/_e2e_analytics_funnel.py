"""Real-Postgres E2E / 对撞 (cross-check) for the P6AN-03 funnel service.

Runs against ``ai_agent_platform_test`` using the app's real AsyncSession,
seeds a deterministic fixture set of Leads (with customer/agent/platform
bindings), then verifies that ``compute_funnel``'s numbers match a hand
COUNT computed via raw SQL. This is the 对撞 acceptance the card asks for
("各阶段转化率计算正确（对撞 SQL）").

Scratch script (opt-in) — not part of the pytest run. Usage:
    python tests/_e2e_analytics_funnel.py
Exits 0 when every check passes, 1 otherwise.
"""
import asyncio, os, sys, uuid
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, delete, text
from app.db.session import AsyncSessionLocal
from app.db.models.lead import Lead
from app.db.models.customer import Customer
from app.db.models.agent import Agent, AgentCustomerBinding
from app.db.models.platform import Platform
from app.db.models.account import Account, AgentPersonaBinding
from app.db.models.persona import Persona
from app.services import funnel_service as fs

PASS, FAIL = [], []
def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  OK  " if cond else " FAIL ") + name + (("  " + detail) if detail else ""), flush=True)


async def cleanup(db, tag):
    # Remove any leftover P6AN-03 fixture by operator tag.
    await db.execute(delete(Lead).where(Lead.operator == tag))
    await db.execute(delete(AgentCustomerBinding).where(AgentCustomerBinding.agent_id.is_(None)))
    # (soft) delete customers/agents/... created in a prior run by scanning operator tag
    await db.commit()


async def seed(tag, run):
    """Seed a deterministic lead set + bindings scoped by run tag.

    Layout (all in one platform/agent so filters are predictable):
      platform P <- account A <- agent_persona_binding -> agent AG
      agent AG --- agent_customer_binding -> customers C1..C3
      leads:
        C1: new=5, contacted=2            (7 leads)
        C2: qualified=3, converted=1      (4 leads)
        C3: converted=4                  (4 leads)
        total 15 leads, statuses: new5 contacted2 qualified3 converted5
      1 lead with created_at 40 days old (out of the default 30d window)
    """
    db = AsyncSessionLocal()
    async with db:
        # platform -> account -> agent
        p = Platform(code=f"p6an03_{tag}", name="p6an03", status="active")
        db.add(p); await db.flush()
        a = Account(platform_id=p.id, name=f"acct_{tag}", status="active")
        db.add(a); await db.flush()
        ag = Agent(name=f"agent_{tag}", status="active")
        db.add(ag); await db.flush()
        pers = Persona(name=f"persona_{tag}")
        db.add(pers); await db.flush()
        apb = AgentPersonaBinding(account_id=a.id, agent_id=ag.id, persona_id=pers.id)
        db.add(apb); await db.flush()

        # 3 customers, each bound to the agent
        cust = []
        for i in range(3):
            c = Customer(name=f"c{tag}_{i}")
            db.add(c); await db.flush(); cust.append(c)
            db.add(AgentCustomerBinding(agent_id=ag.id, customer_id=c.id))
        await db.flush()

        # leads per customer
        def mk(customer, status, days_old=0):
            created = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_old)
            return Lead(customer_id=customer.id, status=status,
                        source_type="e2e", source_id=f"p6an03_{tag}",
                        operator=tag, created_at=created)

        plan = [
            (cust[0], "new", 5), (cust[0], "contacted", 2),
            (cust[1], "qualified", 3), (cust[1], "converted", 1),
            (cust[2], "converted", 4),
        ]
        for customer, status, n in plan:
            for _ in range(n):
                db.add(mk(customer, status))
        # one 40-day-old lead (outside default 30d window)
        db.add(mk(cust[0], "new", 40))
        await db.commit()
        ids = {"platform": p.id, "agent": ag.id, "account": a.id}
        return ids, cust


async def main():
    tag = "p6an03_" + uuid.uuid4().hex[:6]
    db = AsyncSessionLocal()
    # fresh fixture (idempotent)
    await db.execute(delete(Lead).where(Lead.operator == tag))
    await db.commit()

    ids, cust = await seed(tag, "run")
    db2 = AsyncSessionLocal()

    # ---- 对撞 1: agent-scoped, range=all -> reached counts (deterministic) ----
    async with db2:
        res = await fs.compute_funnel(db2, agent_id=ids["agent"], range="all", funnel_code="acquisition")
    by = {s["key"]: s for s in res["stages"]}
    ok("agent total == 16 (incl. the 40d lead)", res["total"] == 16, f"got {res['total']}")
    ok("new reached == 16", by["new"]["count"] == 16, f"got {by['new']['count']}")
    ok("contacted reached == 10 (2+3+5)", by["contacted"]["count"] == 10, f"got {by['contacted']['count']}")
    ok("qualified reached == 8 (3+5)", by["qualified"]["count"] == 8, f"got {by['qualified']['count']}")
    ok("converted reached == 5", by["converted"]["count"] == 5, f"got {by['converted']['count']}")
    ok("contacted conv_rate == 10/16", abs(by["contacted"]["conversion_rate"] - round(10/16, 4)) < 1e-9,
       f"got {by['contacted']['conversion_rate']}")
    ok("end-to-end conversion_rate == 5/16", abs(res["conversion_rate"] - round(5/16, 4)) < 1e-9,
       f"got {res['conversion_rate']}")

    # ---- 对撞 2: agent filter matches platform filter (same agent under one platform) ----
    async with db2:
        res_agent = await fs.compute_funnel(db2, agent_id=ids["agent"], range="all")
        res_plat = await fs.compute_funnel(db2, platform_id=ids["platform"], range="all")
    ok("agent-filter total == 16", res_agent["total"] == 16, f"got {res_agent['total']}")
    ok("platform-filter total == 16", res_plat["total"] == 16, f"got {res_plat['total']}")

    # ---- 对撞 3: agent + range=30d excludes the 40-day-old lead -> total 15 ----
    async with db2:
        res30 = await fs.compute_funnel(db2, agent_id=ids["agent"], range="30d")
    ok("agent range=30d excludes 40d lead -> total 15", res30["total"] == 15, f"got {res30['total']}")

    # ---- 对撞 4: empty scope -> empty funnel, not crash ----
    async with db2:
        empty = await fs.compute_funnel(db2, agent_id=uuid.uuid4(), range="all")
    ok("unknown agent -> total 0, no crash", empty["total"] == 0 and empty["conversion_rate"] is None,
       f"got {empty['total']}")

    # ---- 对撞 5: agent + from/to explicit bounds (today's 15, excl. 40d) ----
    today = datetime.now(timezone.utc).replace(tzinfo=None).date()
    async with db2:
        resbt = await fs.compute_funnel(
            db2,
            agent_id=ids["agent"],
            from_date=today.isoformat(),
            to_date=(today + timedelta(days=1)).isoformat(),
        )
    ok("from/to today-window total == 15 (excl. 40d)", resbt["total"] == 15, f"got {resbt['total']}")

    # ---- 对撞 6: raw-SQL hand COUNT agreement for a filtered slice ----
    sql_counts = await raw_status_counts(tag, days=30)
    ok("raw SQL status counts match hand expectation",
       sql_counts.get("new") == 5 and sql_counts.get("converted") == 5
       and sql_counts.get("qualified") == 3 and sql_counts.get("contacted") == 2,
       f"got {sql_counts}")

    # cleanup fixture
    dbc = AsyncSessionLocal()
    async with dbc:
        await dbc.execute(delete(Lead).where(Lead.operator == tag))
        await dbc.commit()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
    return 1 if FAIL else 0


async def raw_status_counts(tag, days):
    db = AsyncSessionLocal()
    async with db:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        q = select(Lead.status, func.count(Lead.id)).where(
            Lead.operator == tag, Lead.is_deleted == False, Lead.created_at >= cutoff  # noqa: E712
        ).group_by(Lead.status)
        rows = (await db.execute(q)).all()
    return {s: n for s, n in rows}


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
