"""
Proxy Service Layer
"""
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Proxy
from app.security.crypto import hash_password, is_hashed
from app.schemas.proxy import (
    ProxyCreate,
    ProxyUpdate,
    ProxyResponse,
    ProxyListResponse,
    TestConnectionResponse,
)
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ProxyService:
    """Service for Proxy management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_proxies(
        self,
        page: int = 1,
        page_size: int = 20,
        type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[List[ProxyResponse], int]:
        """列出所有代理（支持分页和类型/状态筛选）"""
        query = select(Proxy).where(Proxy.is_deleted == False)

        if type:
            query = query.where(Proxy.type == type)
        if status:
            query = query.where(Proxy.status == status)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(Proxy.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        proxies = result.scalars().all()

        return [ProxyResponse.model_validate(p) for p in proxies], total

    async def get_proxy(self, proxy_id: UUID) -> Optional[ProxyResponse]:
        """获取单个代理详情"""
        result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id, Proxy.is_deleted == False)
        )
        proxy = result.scalar_one_or_none()
        return ProxyResponse.model_validate(proxy) if proxy else None

    async def create_proxy(self, data: ProxyCreate) -> ProxyResponse:
        """创建代理"""
        proxy = Proxy(
            name=data.name,
            type=data.type,
            host=data.host,
            port=data.port,
            username=data.username,
            # F-3: store the credential hashed (irreversible); never plaintext.
            # An already-hashed value is stored as-is (no double-hash). Responses
            # never echo the value: ProxyResponse carries no password field.
            password_encrypted=(
                data.password
                if not data.password or is_hashed(data.password)
                else hash_password(data.password)
            ),
            status=data.status,
        )
        self.db.add(proxy)
        await self.db.commit()
        await self.db.refresh(proxy)
        return ProxyResponse.model_validate(proxy)

    async def update_proxy(self, proxy_id: UUID, data: ProxyUpdate) -> Optional[ProxyResponse]:
        """更新代理信息"""
        result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id, Proxy.is_deleted == False)
        )
        proxy = result.scalar_one_or_none()
        if not proxy:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == "password" and value:
                # F-3: store a newly-supplied proxy credential hashed (unless the
                # caller already supplied a stored hash); never plaintext.
                proxy.password_encrypted = (
                    value if is_hashed(value) else hash_password(value)
                )
            else:
                setattr(proxy, field, value)

        await self.db.commit()
        await self.db.refresh(proxy)
        return ProxyResponse.model_validate(proxy)

    async def delete_proxy(self, proxy_id: UUID) -> bool:
        """软删除代理"""
        result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id, Proxy.is_deleted == False)
        )
        proxy = result.scalar_one_or_none()
        if not proxy:
            return False

        proxy.is_deleted = True
        await self.db.commit()
        return True

    async def test_connection(self, proxy_id: UUID) -> TestConnectionResponse:
        """测试代理连通性（V1 返回模拟状态）"""
        result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id, Proxy.is_deleted == False)
        )
        proxy = result.scalar_one_or_none()
        if not proxy:
            return TestConnectionResponse(
                success=False,
                message=f"Proxy {proxy_id} not found",
                status="error",
                proxy_id=proxy_id,
                timestamp=datetime.now(timezone.utc),
            )

        # 更新最后测试时间
        proxy.last_tested = datetime.now(timezone.utc)
        await self.db.commit()

        # V1: 模拟测试，返回成功状态
        return TestConnectionResponse(
            success=True,
            message=f"Proxy '{proxy.name}' ({proxy.type}://{proxy.host}:{proxy.port}) connection test passed (mock mode)",
            status="connected",
            proxy_id=proxy.id,
            timestamp=datetime.now(timezone.utc),
        )
