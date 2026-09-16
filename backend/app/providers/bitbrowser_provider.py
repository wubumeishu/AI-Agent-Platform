"""
BitBrowser Provider 实现

依赖状态:
- 已安装: BitBrowser 本地服务运行在 http://127.0.0.1:1922
- 未安装: 降级为模拟模式，返回预设数据

API 文档: https://bitbrowser.ai/api-docs
"""
import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

import httpx

from app.providers.browser_provider import BrowserProvider


logger = logging.getLogger(__name__)


# 模拟数据（当 BitBrowser SDK 未安装时使用）
_MOCK_PROFILES = [
    {
        "id": "mock_001",
        "name": "演示配置-微信",
        "status": "idle",
        "created_at": "2026-09-13T10:00:00Z",
        "profile_id": "bitbrowser_profile_001",
    },
    {
        "id": "mock_002",
        "name": "演示配置-抖音",
        "status": "running",
        "created_at": "2026-09-13T11:00:00Z",
        "profile_id": "bitbrowser_profile_002",
    },
]


class BitBrowserProvider(BrowserProvider):
    """
    BitBrowser 浏览器提供商实现
    
    连接到 BitBrowser 本地服务的 REST API:
    - 基础地址: http://127.0.0.1:1922
    - API Key: 从环境变量 BITBROWSER_API_KEY 获取
    
    如果无法连接，自动降级为模拟模式。
    """
    
    PROVIDER_NAME = "bitbrowser"
    DEFAULT_ENDPOINT = "http://127.0.0.1:1922"
    
    def __init__(self, endpoint: Optional[str] = None, api_key: Optional[str] = None):
        """
        初始化 BitBrowser Provider
        
        Args:
            endpoint: BitBrowser 服务地址，默认 http://127.0.0.1:1922
            api_key: API Key，从环境变量读取
        """
        self.endpoint = endpoint or os.getenv("BITBROWSER_ENDPOINT", self.DEFAULT_ENDPOINT)
        self.api_key = api_key or os.getenv("BITBROWSER_API_KEY", "")
        self._connected = False
        self._sdk_available = self._check_sdk_available()
    
    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME
    
    def _check_sdk_available(self) -> bool:
        """检查 BitBrowser SDK/服务是否可用"""
        try:
            import httpx
            response = httpx.get(
                f"{self.endpoint}/api/v1/status",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=2.0
            )
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"BitBrowser service check failed: {e}")
            return False
    
    async def test_connection(self) -> Dict[str, Any]:
        """测试与 BitBrowser 的连接状态"""
        if not self._sdk_available:
            # 模拟模式
            return {
                "connected": False,
                "provider": self.PROVIDER_NAME,
                "status": "mock_mode",
                "message": "BitBrowser SDK 未安装，使用模拟模式",
                "endpoint": self.endpoint,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.endpoint}/api/v1/status",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
            if response.status_code == 200:
                self._connected = True
                return {
                    "connected": True,
                    "provider": self.PROVIDER_NAME,
                    "status": "connected",
                    "message": "BitBrowser 连接正常",
                    "endpoint": self.endpoint,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            else:
                return {
                    "connected": False,
                    "provider": self.PROVIDER_NAME,
                    "status": "error",
                    "message": f"BitBrowser 返回错误: {response.status_code}",
                    "endpoint": self.endpoint,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as e:
            logger.error(f"BitBrowser connection test failed: {e}")
            return {
                "connected": False,
                "provider": self.PROVIDER_NAME,
                "status": "error",
                "message": f"连接失败: {str(e)}",
                "endpoint": self.endpoint,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    async def list_profiles(self) -> List[Dict[str, Any]]:
        """列出所有浏览器配置"""
        if not self._sdk_available:
            return _MOCK_PROFILES.copy()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.endpoint}/api/v1/profiles",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
            if response.status_code == 200:
                return response.json().get("data", [])
            else:
                logger.error(f"Failed to list profiles: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error listing profiles: {e}")
            return []
    
    async def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """获取单个配置详情"""
        if not self._sdk_available:
            for profile in _MOCK_PROFILES:
                if profile["id"] == profile_id:
                    return profile.copy()
            return None
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.endpoint}/api/v1/profiles/{profile_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
            if response.status_code == 200:
                return response.json().get("data")
            elif response.status_code == 404:
                return None
            else:
                logger.error(f"Failed to get profile: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting profile: {e}")
            return None
    
    async def create_profile(self, name: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """创建新浏览器配置"""
        if not self._sdk_available:
            # 模拟创建
            mock_profile = {
                "id": f"mock_{datetime.now(timezone.utc).timestamp()}",
                "name": name,
                "status": "idle",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "profile_id": f"bitbrowser_profile_{len(_MOCK_PROFILES) + 1}",
            }
            _MOCK_PROFILES.append(mock_profile)
            return mock_profile
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {"name": name, **(config or {})}
                response = await client.post(
                    f"{self.endpoint}/api/v1/profiles",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload
                )
                
            if response.status_code in (200, 201):
                return response.json().get("data", {})
            else:
                logger.error(f"Failed to create profile: {response.status_code}")
                return {}
        except Exception as e:
            logger.error(f"Error creating profile: {e}")
            return {}
    
    async def delete_profile(self, profile_id: str) -> bool:
        """删除浏览器配置"""
        if not self._sdk_available:
            # 模拟删除
            global _MOCK_PROFILES
            _MOCK_PROFILES = [p for p in _MOCK_PROFILES if p["id"] != profile_id]
            return True
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.delete(
                    f"{self.endpoint}/api/v1/profiles/{profile_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
            return response.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Error deleting profile: {e}")
            return False
    
    def is_mock_mode(self) -> bool:
        """检查是否处于模拟模式"""
        return not self._sdk_available
