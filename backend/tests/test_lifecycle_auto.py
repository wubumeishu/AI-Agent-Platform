"""
Lifecycle Auto-Transition + Funnel + Stage-Config API 测试 (t_crm_005)

分三层:
1. 纯规则引擎 (match_stage_for_signals / build_signals / stage_config_rules)
   —— 无数据库, 直接验证可配置流转规则的匹配语义.
2. 空规则降级 (apply_auto_transitions 在无规则/异常结果形状时安全返回 [])
   —— 保护 update_lead 主路径.
3. 真库集成 (ai_agent_platform_test):
   - 阶段配置 API 写入 config.rules
   - 自动流转 (intent_score / status_change / conversation_activity 触发)
   - 阶段变更日志
   - 漏斗统计 (单次 GROUP BY + 转化率)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import select, delete

from app.db.models.lifecycle import LifecycleStage, LifecycleStageLog
from app.db.models.lead import Lead
from app.db.models.conversation import Conversation, Message
from app.schemas.lifecycle import (
    LifecycleStageCreate,
    LifecycleStageUpdate,
    LifecycleStageRule,
)
from app.crm.services.auto import (
    build_signals,
    match_stage_for_signals,
    stage_config_rules,
    apply_auto_transitions,
)
from app.crm.services.lifecycle import (
    create_lifecycle_stage,
    update_lifecycle_stage,
    get_lifecycle_stage,
    delete_lifecycle_stage,
    get_lifecycle_stage_logs,
    get_funnel_stats,
)

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent_platform_test"

# 固定 stage code, 便于 cleanup 与断言
STAGE_A = "测试自动流转A"
STAGE_B = "测试自动流转B"


# ---------------------------------------------------------------------------
# 1) 纯规则引擎
# ---------------------------------------------------------------------------
class TestRuleEngine:
    def test_build_signals_defaults(self):
        signals = build_signals(None, None, 0)
        assert signals == {"intent_score": 0, "status": None, "conversation_activity": 0}

    def test_build_signals_explicit(self):
        signals = build_signals(88, "qualified", 5)
        assert signals["intent_score"] == 88
        assert signals["status"] == "qualified"
        assert signals["conversation_activity"] == 5

    def test_intent_score_rule_matches(self):
        configs = {STAGE_A: [
            {"on_trigger": "intent_score", "min_intent_score": 70,
             "target_stage_code": STAGE_B},
        ]}
        assert match_stage_for_signals(configs, build_signals(88, "new", 0)) == STAGE_B

    def test_intent_score_rule_below_threshold_no_match(self):
        configs = {STAGE_A: [
            {"on_trigger": "intent_score", "min_intent_score": 70,
             "target_stage_code": STAGE_B},
        ]}
        assert match_stage_for_signals(configs, build_signals(50, "new", 0)) is None

    def test_status_change_rule_matches(self):
        configs = {STAGE_A: [
            {"on_trigger": "status_change", "when_status": "qualified",
             "target_stage_code": STAGE_B},
        ]}
        assert match_stage_for_signals(configs, build_signals(0, "qualified", 0)) == STAGE_B
        assert match_stage_for_signals(configs, build_signals(0, "new", 0)) is None

    def test_conversation_activity_rule_matches(self):
        configs = {STAGE_A: [
            {"on_trigger": "conversation_activity", "min_messages": 2,
             "target_stage_code": STAGE_B},
        ]}
        assert match_stage_for_signals(configs, build_signals(0, "new", 3)) == STAGE_B
        assert match_stage_for_signals(configs, build_signals(0, "new", 1)) is None

    def test_first_matching_rule_wins(self):
        # 两条都命中时, 按声明顺序取第一条 (前一个阶段先列出)
        configs = {
            STAGE_A: [{"on_trigger": "status_change", "when_status": "qualified",
                       "target_stage_code": STAGE_B}],
            "另一阶段": [{"on_trigger": "status_change", "when_status": "qualified",
                          "target_stage_code": "别的阶段"}],
        }
        assert match_stage_for_signals(configs, build_signals(0, "qualified", 0)) == STAGE_B

    def test_unknown_trigger_is_skipped_not_crash(self):
        configs = {STAGE_A: [
            {"on_trigger": "bogus_trigger", "target_stage_code": STAGE_B},
            {"on_trigger": "intent_score", "min_intent_score": 0,
             "target_stage_code": STAGE_B},
        ]}
        # 第一条未知 -> 跳过, 第二条命中
        assert match_stage_for_signals(configs, build_signals(5, "new", 0)) == STAGE_B

    def test_stage_config_rules_tolerates_garbage(self):
        assert stage_config_rules(None) == []
        assert stage_config_rules({"rules": "not-a-list"}) == []
        assert stage_config_rules({"rules": [{"on_trigger": "intent_score", "min_intent_score": 1, "target_stage_code": "x"}, "garbage", 3]}) == [
            {"on_trigger": "intent_score", "min_intent_score": 1, "target_stage_code": "x"}
        ]


# ---------------------------------------------------------------------------
# 2) 空规则 / 异常降级
# ---------------------------------------------------------------------------
class TestAutoTransitionDegradation:
    async def test_no_rules_returns_empty(self):
        """无任何阶段配置规则 -> 不碰 provider, 安全返回 []."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []  # 无阶段
        db.execute.return_value = mock_result
        lead = MagicMock()
        lead.lifecycle_stage_code = "陌生"
        lead.id = uuid4()
        lead.intent_score = 90
        lead.status = "new"
        result = await apply_auto_transitions(db, lead)
        assert result == []

    async def test_unexpected_result_shape_returns_empty(self):
        """execute 返回非标准形状 (如 AsyncMock 自身) -> 降级 [], 不抛异常."""
        db = AsyncMock()
        db.execute = AsyncMock()  # 返回 AsyncMock, .all() 行为不可控
        lead = MagicMock()
        lead.lifecycle_stage_code = "陌生"
        lead.id = uuid4()
        result = await apply_auto_transitions(db, lead)
        assert result == []


# ---------------------------------------------------------------------------
# 3) 真库集成
# ---------------------------------------------------------------------------
def _test_engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    return eng, sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

_TEST_ENGINE, _TEST_SESSION = _test_engine()


@pytest.fixture
async def db():
    async with _TEST_SESSION() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _cleanup_custom_stages(db):
    """测试前后清理自建 stage, 保证幂等."""
    yield
    for code in (STAGE_A, STAGE_B):
        await db.execute(delete(LifecycleStage).where(LifecycleStage.code == code))
    # 清掉指向自建阶段的 lead
    await db.execute(
        delete(Lead).where(
            Lead.lifecycle_stage_code.in_([STAGE_A, STAGE_B]),
        )
    )
    # 清掉测试 conversation + message (显式按 subject 匹配, 防脏数据累积)
    test_convs = (await db.execute(
        select(Conversation.id).where(Conversation.subject == "auto-test conv")
    )).scalars().all()
    if test_convs:
        await db.execute(delete(Message).where(Message.conversation_id.in_(test_convs)))
        await db.execute(delete(Conversation).where(Conversation.id.in_(test_convs)))
    await db.commit()


async def _seed_stages(db, rules_a, rules_b):
    await create_lifecycle_stage(db, {
        "code": STAGE_A, "name": STAGE_A, "description": "auto-test stage A",
        "sort_order": 90, "config": {"rules": rules_a},
    })
    await create_lifecycle_stage(db, {
        "code": STAGE_B, "name": STAGE_B, "description": "auto-test stage B",
        "sort_order": 91, "config": {"rules": rules_b},
    })


async def _make_lead(db, intent_score=0, status="new", source_type="manual", source_id=None, stage="陌生"):
    lead = Lead(
        customer_id=None,
        lifecycle_stage_code=stage,
        intent_score=intent_score,
        source_type=source_type,
        source_id=source_id,
        status=status,
        notes="t_crm_005 auto-test lead",
        operator="qa",
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


class TestAutoTransitionIntegration:
    async def test_intent_score_auto_transition(self, db):
        await _seed_stages(
            db,
            rules_a=[{"on_trigger": "intent_score", "min_intent_score": 70,
                      "target_stage_code": STAGE_B}],
            rules_b=[],
        )
        lead = await _make_lead(db, intent_score=90, status="new")
        applied = await apply_auto_transitions(db, lead, skip_stages=["陌生"])
        assert len(applied) == 1
        assert applied[0]["old_stage_code"] == "陌生"
        assert applied[0]["new_stage_code"] == STAGE_B
        assert applied[0]["transition_reason"] == "auto_rule"
        assert applied[0]["operator"] == "system"

        # Lead 的阶段已更新
        fresh = (await db.execute(select(Lead).where(Lead.id == lead.id))).scalar_one()
        assert fresh.lifecycle_stage_code == STAGE_B

    async def test_intent_score_below_threshold_no_transition(self, db):
        await _seed_stages(
            db,
            rules_a=[{"on_trigger": "intent_score", "min_intent_score": 70,
                      "target_stage_code": STAGE_B}],
            rules_b=[],
        )
        lead = await _make_lead(db, intent_score=30, status="new")
        applied = await apply_auto_transitions(db, lead, skip_stages=["陌生"])
        assert applied == []
        fresh = (await db.execute(select(Lead).where(Lead.id == lead.id))).scalar_one()
        assert fresh.lifecycle_stage_code == "陌生"

    async def test_status_change_auto_transition(self, db):
        await _seed_stages(
            db,
            rules_a=[{"on_trigger": "status_change", "when_status": "qualified",
                      "target_stage_code": STAGE_B}],
            rules_b=[],
        )
        lead = await _make_lead(db, intent_score=0, status="qualified")
        applied = await apply_auto_transitions(db, lead, skip_stages=["陌生"])
        assert len(applied) == 1
        assert applied[0]["new_stage_code"] == STAGE_B

    async def test_conversation_activity_auto_transition(self, db):
        # 造一条真实 conversation (customer_id NOT NULL, 查现有客户复用)
        from app.db.models.customer import Customer
        cust_row = (await db.execute(
            select(Customer.id).where(Customer.is_deleted == False).limit(1)
        )).first()
        if not cust_row:
            cust = Customer(id=uuid4(), name="qa-cust")
            db.add(cust)
            await db.commit()
            cust_id = cust.id
        else:
            cust_id = cust_row[0]
        # NOTE: 显式指定 id 且 *不* refresh(conv) —— 仓库存在同名 "Message"
        # ORM 类冲突 (conversation.Message 表 message vs 平台 Message 表 messages,
        # 测试库无 messages 表), refresh 会触发 selectin 关系加载到错误的表。
        conv = Conversation(id=uuid4(), customer_id=cust_id, subject="auto-test conv")
        db.add(conv)
        await db.commit()
        for _ in range(2):
            db.add(Message(id=uuid4(), conversation_id=conv.id, role="user", content="hello"))
        await db.commit()

        await _seed_stages(
            db,
            rules_a=[{"on_trigger": "conversation_activity", "min_messages": 2,
                      "target_stage_code": STAGE_B}],
            rules_b=[],
        )
        lead = await _make_lead(
            db, intent_score=0, status="new",
            source_type="conversation", source_id=str(conv.id),
        )
        applied = await apply_auto_transitions(db, lead, skip_stages=["陌生"])
        assert len(applied) == 1
        assert applied[0]["new_stage_code"] == STAGE_B

    async def test_transition_writes_log_entry(self, db):
        await _seed_stages(db, rules_a=[{"on_trigger": "intent_score", "min_intent_score": 1,
                                          "target_stage_code": STAGE_B}], rules_b=[])
        lead = await _make_lead(db, intent_score=5, status="new")
        applied = await apply_auto_transitions(db, lead, skip_stages=["陌生"])
        assert len(applied) == 1

        logs = await get_lifecycle_stage_logs(db, STAGE_B, lead_id=lead.id)
        assert len(logs) == 1
        assert logs[0]["old_stage_code"] == "陌生"
        assert logs[0]["new_stage_code"] == STAGE_B
        assert logs[0]["transition_reason"] == "auto_rule"
        assert logs[0]["metadata"]["signals"]["intent_score"] == 5

        # 日志表也确有记录
        log_row = (await db.execute(
            select(LifecycleStageLog).where(
                LifecycleStageLog.lead_id == lead.id,
                LifecycleStageLog.new_stage_code == STAGE_B,
            )
        )).scalar_one()
        assert log_row.transition_reason == "auto_rule"


class TestFunnelIntegration:
    async def test_funnel_counts_and_conversion_rate(self, db):
        await _seed_stages(db, rules_a=[], rules_b=[])
        # 2 个 lead 在 A, 1 个在 B, 其余在默认 "陌生" 阶段(不建, 用现有默认)
        for _ in range(2):
            await _make_lead(db, stage=STAGE_A)
        await _make_lead(db, stage=STAGE_B)

        stats = await get_funnel_stats(db)
        by_code = {s["code"]: s["customer_count"] for s in stats}
        assert by_code[STAGE_A] == 2
        assert by_code[STAGE_B] == 1

        # 验证排序 (sort_order 升序) 与转化率分母 = 顶部阶段
        ordered_codes = [s["code"] for s in stats]
        assert ordered_codes.index(STAGE_A) < ordered_codes.index(STAGE_B)

    async def test_funnel_empty_no_stages_returns_empty(self, db):
        # 删除所有默认阶段, 验证无阶段时 funnel 返回空而非报错
        await db.execute(delete(LifecycleStage))
        await db.commit()
        stats = await get_funnel_stats(db)
        assert stats == []
        # 重新播种默认阶段 (保持测试库可用)
        from app.crm.services.lifecycle import init_default_stages
        await init_default_stages(db)


class TestStageConfigAPI:
    async def test_create_stage_with_rules_model(self, db):
        model = LifecycleStageCreate(
            code=STAGE_A, name=STAGE_A, sort_order=90,
            auto_transition_rules=[
                LifecycleStageRule(on_trigger="intent_score", min_intent_score=80,
                                   target_stage_code=STAGE_B),
            ],
        )
        created = await create_lifecycle_stage(db, model)
        assert created["code"] == STAGE_A
        assert created["config"]["rules"][0]["on_trigger"] == "intent_score"

        fetched = await get_lifecycle_stage(db, STAGE_A)
        assert fetched["config"]["rules"][0]["min_intent_score"] == 80

    async def test_update_stage_rules_replaces_config(self, db):
        await create_lifecycle_stage(db, {
            "code": STAGE_A, "name": STAGE_A, "sort_order": 90,
            "config": {"rules": [{"on_trigger": "intent_score", "min_intent_score": 10,
                                  "target_stage_code": STAGE_B}]},
        })
        upd = LifecycleStageUpdate(auto_transition_rules=[
            LifecycleStageRule(on_trigger="status_change", when_status="qualified",
                               target_stage_code=STAGE_B),
        ])
        updated = await update_lifecycle_stage(db, STAGE_A, upd)
        assert updated["config"]["rules"][0]["on_trigger"] == "status_change"
        assert len(updated["config"]["rules"]) == 1

    async def test_create_stage_rejects_bad_rule(self, db):
        bad = {
            "code": STAGE_A, "name": STAGE_A, "sort_order": 90,
            "config": {"rules": [{"on_trigger": "nonsense", "target_stage_code": STAGE_B}]},
        }
        with pytest.raises(ValueError, match="校验失败"):
            await create_lifecycle_stage(db, bad)

    async def test_create_stage_rejects_missing_min_intent_score(self, db):
        bad = {
            "code": STAGE_A, "name": STAGE_A, "sort_order": 90,
            "config": {"rules": [{"on_trigger": "intent_score", "target_stage_code": STAGE_B}]},
        }
        with pytest.raises(ValueError):
            await create_lifecycle_stage(db, bad)

    async def test_delete_stage_soft(self, db):
        await create_lifecycle_stage(db, {"code": STAGE_B, "name": STAGE_B, "sort_order": 91})
        assert await delete_lifecycle_stage(db, STAGE_B) is True
        assert await get_lifecycle_stage(db, STAGE_B) is None
        assert await delete_lifecycle_stage(db, STAGE_B) is False
