"""
Browser Service Layer
"""
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import BrowserProfile
from app.providers.bitbrowser_provider import BitBrowserProvider
from app.schemas.browser import (
    BrowserProfileCreate,
    BrowserProfileUpdate,
    BrowserProfileResponse,
    BrowserProfileListResponse,
    ProviderStatus,
    TestConnectionResponse,
)
from datetime import datetime, timezone


logger = logging.getLogger(__name__)


class BrowserService:
    """Service for Browser Provider management"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._providers: dict[str, BitBrowserProvider] = {}
    
    def get_provider(self, provider_name: str) -> Optional[BitBrowserProvider]:
        """
        获取浏览器提供商实例
        
        Args:
            provider_name: 提供商名称 (e.g., "bitbrowser")
            
        Returns:
            Provider instance or None
        """
        if provider_name not in self._providers:
            if provider_name == "bitbrowser":
                self._providers[provider_name] = BitBrowserProvider()
            else:
                logger.warning(f"Unknown provider: {provider_name}")
                return None
        return self._providers[provider_name]
    
    async def list_providers(self) -> List[str]:
        """列出所有可用的浏览器提供商"""
        return ["bitbrowser"]  # V1 仅支持 BitBrowser
    
    async def get_provider_status(self, provider_name: str) -> Optional[ProviderStatus]:
        """获取提供商连接状态"""
        provider = self.get_provider(provider_name)
        if not provider:
            return None
        
        status_info = await provider.test_connection()
        return ProviderStatus(
            provider=status_info["provider"],
            connected=status_info["connected"],
            status=status_info["status"],
            message=status_info["message"],
            endpoint=status_info.get("endpoint"),
            timestamp=status_info.get("timestamp") and datetime.fromisoformat(status_info["timestamp"]),
        )
    
    async def test_provider_connection(self, provider_name: str) -> TestConnectionResponse:
        """测试提供商连接"""
        provider = self.get_provider(provider_name)
        if not provider:
            return TestConnectionResponse(
                success=False,
                message=f"Provider {provider_name} not found",
                status="error",
                provider=provider_name,
                timestamp=datetime.now(timezone.utc),
            )
        
        status_info = await provider.test_connection()
        return TestConnectionResponse(
            success=status_info["connected"],
            message=status_info["message"],
            status=status_info["status"],
            provider=provider_name,
            timestamp=status_info.get("timestamp") and datetime.fromisoformat(status_info["timestamp"]) or datetime.now(timezone.utc),
        )
    
    async def list_profiles(
        self,
        page: int = 1,
        page_size: int = 20,
        provider: Optional[str] = None,
        connection_status: Optional[str] = None,
    ) -> tuple[List[BrowserProfileResponse], int]:
        """列出所有浏览器配置"""
        query = select(BrowserProfile).where(BrowserProfile.is_deleted == False)
        total_query = select(func.count()).where(BrowserProfile.is_deleted == False)
        
        if provider:
            query = query.where(BrowserProfile.provider == provider)
            total_query = total_query.where(BrowserProfile.provider == provider)
        
        if connection_status:
            query = query.where(BrowserProfile.connection_status == connection_status)
            total_query = total_query.where(BrowserProfile.connection_status == connection_status)
        
        # Get total count
        total_result = await self.db.execute(total_query)
        total = total_result.scalar() or 0
        
        # Apply pagination
        query = query.order_by(BrowserProfile.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        profiles = result.scalars().all()
        
        return [self._profile_to_response(p) for p in profiles], total
    
    async def get_profile(self, profile_id: UUID) -> Optional[BrowserProfileResponse]:
        """获取单个配置详情"""
        result = await self.db.execute(
            select(BrowserProfile).where(BrowserProfile.id == profile_id, BrowserProfile.is_deleted == False)
        )
        profile = result.scalar_one_or_none()
        return self._profile_to_response(profile) if profile else None
    
    async def create_profile(self, data: BrowserProfileCreate) -> BrowserProfileResponse:
        """创建新配置"""
        profile = BrowserProfile(
            provider=data.provider,
            profile_id=data.profile_id,
            name=data.name,
            connection_status=data.connection_status or "disconnected",
        )
        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        return self._profile_to_response(profile)
    
    async def update_profile(self, profile_id: UUID, data: BrowserProfileUpdate) -> Optional[BrowserProfileResponse]:
        """更新配置"""
        result = await self.db.execute(
            select(BrowserProfile).where(BrowserProfile.id == profile_id, BrowserProfile.is_deleted == False)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(profile, key, value)
        
        profile.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(profile)
        return self._profile_to_response(profile)
    
    async def delete_profile(self, profile_id: UUID) -> bool:
        """软删除配置"""
        result = await self.db.execute(
            select(BrowserProfile).where(BrowserProfile.id == profile_id, BrowserProfile.is_deleted == False)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return False
        
        profile.is_deleted = True
        profile.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True
    
    def _profile_to_response(self, profile: BrowserProfile) -> BrowserProfileResponse:
        """将 ORM 对象转换为响应 schema"""
        return BrowserProfileResponse(
            id=profile.id,
            provider=profile.provider,
            profile_id=profile.profile_id,
            name=profile.name,
            connection_status=profile.connection_status,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
