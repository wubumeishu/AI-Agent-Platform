"""
Browser Provider 相关数据库模型

Note: BrowserProfile 模型已存在于 app/db/models/account.py
此处用于向后兼容和统一导入
"""
from app.db.models.account import BrowserProfile, Proxy

__all__ = ["BrowserProfile", "Proxy"]
