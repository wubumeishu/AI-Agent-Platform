"""
Platform Service Layer
"""
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform import Platform
from app.schemas.platform import (
    PlatformCreate,
    PlatformUpdate,
    PlatformResponse,
    PlatformListResponse,
    TestConnectionResponse,
)
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class PlatformService:
    """Service for Platform management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_platforms(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> tuple[List[PlatformResponse], int]:
        """列出所有平台（支持分页和状态筛选）"""
        query = select(Platform).where(Platform.is_deleted == False)

        if status:
            query = query.where(Platform.status == status)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(Platform.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        platforms = result.scalars().all()

        return [PlatformResponse.model_validate(p) for p in platforms], total

    async def get_platform(self, platform_id: UUID) -> Optional[PlatformResponse]:
        """获取单个平台详情"""
        result = await self.db.execute(
            select(Platform).where(Platform.id == platform_id, Platform.is_deleted == False)
        )
        platform = result.scalar_one_or_none()
        return PlatformResponse.model_validate(platform) if platform else None

    async def create_platform(self, data: PlatformCreate) -> PlatformResponse:
        """创建平台（code 唯一约束）"""
        # 检查 code 是否已存在
        existing = await self.db.execute(
            select(Platform).where(Platform.code == data.code, Platform.is_deleted == False)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Platform code '{data.code}' already exists")

        platform = Platform(
            code=data.code,
            name=data.name,
            capabilities=data.capabilities,
            adapter_class=data.adapter_class,
            config=data.config,
            status=data.status,
        )
        self.db.add(platform)
        await self.db.commit()
        await self.db.refresh(platform)
        return PlatformResponse.model_validate(platform)

    async def update_platform(self, platform_id: UUID, data: PlatformUpdate) -> Optional[PlatformResponse]:
        """更新平台信息"""
        result = await self.db.execute(
            select(Platform).where(Platform.id == platform_id, Platform.is_deleted == False)
        )
        platform = result.scalar_one_or_none()
        if not platform:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(platform, field, value)

        await self.db.commit()
        await self.db.refresh(platform)
        return PlatformResponse.model_validate(platform)

    async def delete_platform(self, platform_id: UUID) -> bool:
        """软删除平台"""
        result = await self.db.execute(
            select(Platform).where(Platform.id == platform_id, Platform.is_deleted == False)
        )
        platform = result.scalar_one_or_none()
        if not platform:
            return False

        platform.is_deleted = True
        await self.db.commit()
        return True

    async def test_connection(self, platform_id: UUID) -> TestConnectionResponse:
        """测试平台连接（V1 返回模拟状态）"""
        result = await self.db.execute(
            select(Platform).where(Platform.id == platform_id, Platform.is_deleted == False)
        )
        platform = result.scalar_one_or_none()
        if not platform:
            return TestConnectionResponse(
                success=False,
                message=f"Platform {platform_id} not found",
                status="error",
                platform_code="",
                timestamp=datetime.now(timezone.utc),
            )

        # V1: 模拟测试，返回成功状态
        return TestConnectionResponse(
            success=True,
            message=f"Platform '{platform.name}' connection test passed (mock mode)",
            status="connected",
            platform_code=platform.code,
            timestamp=datetime.now(timezone.utc),
        )


# ========== Seed Data ==========

async def seed_default_platforms(db: AsyncSession):
    """插入内置平台初始数据"""
    default_platforms = [
        {
            "code": "wechat",
            "name": "微信",
            "capabilities": ["messaging", "friend_management", "moment", "group"],
            "adapter_class": "platforms.wechat.WeChatAdapter",
            "config": {},
        },
        {
            "code": "douyin",
            "name": "抖音",
            "capabilities": ["messaging", "comment_reply"],
            "adapter_class": "platforms.douyin.DouyinAdapter",
            "config": {},
        },
        {
            "code": "xiaohongshu",
            "name": "小红书",
            "capabilities": ["messaging", "comment_reply"],
            "adapter_class": "platforms.xiaohongshu.XiaoHongShuAdapter",
            "config": {},
        },
    ]

    for platform_data in default_platforms:
        existing = await db.execute(
            select(Platform).where(Platform.code == platform_data["code"], Platform.is_deleted == False)
        )
        if not existing.scalar_one_or_none():
            platform = Platform(**platform_data)
            db.add(platform)

    await db.commit()
    logger.info(f"Seeded {len(default_platforms)} default platforms")
