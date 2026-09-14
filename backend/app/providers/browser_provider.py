"""
Browser Provider 抽象层

V1 仅支持 BitBrowser，后续可扩展 AdsPower、LocalChromium 等
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class BrowserProvider(ABC):
    """
    Browser Provider 基类/协议定义
    
    所有浏览器提供商必须实现以下方法:
    - list_profiles(): 列出所有浏览器配置
    - create_profile(): 创建新配置
    - get_profile(): 获取单个配置详情
    - delete_profile(): 删除配置
    - test_connection(): 测试连接状态
    """
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """提供商名称标识"""
        pass
    
    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """
        测试与浏览器的连接状态
        
        Returns:
            {"connected": bool, "message": str, "endpoint": str}
        """
        pass
    
    @abstractmethod
    async def list_profiles(self) -> List[Dict[str, Any]]:
        """
        列出所有浏览器配置
        
        Returns:
            List of profile dicts with keys:
            - id: str
            - name: str
            - status: str
            - created_at: datetime
        """
        pass
    
    @abstractmethod
    async def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个配置详情
        
        Args:
            profile_id: 配置ID
            
        Returns:
            Profile dict or None if not found
        """
        pass
    
    @abstractmethod
    async def create_profile(self, name: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        创建新浏览器配置
        
        Args:
            name: 配置名称
            config: 可选配置参数
            
        Returns:
            Created profile dict
        """
        pass
    
    @abstractmethod
    async def delete_profile(self, profile_id: str) -> bool:
        """
        删除浏览器配置
        
        Args:
            profile_id: 配置ID
            
        Returns:
            True if deleted, False if not found
        """
        pass
