"""Account models for Phase 1 Resource Layer"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Boolean, DateTime, Integer, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class AccountStatus(str, Enum):
    """Account status enum"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class ProxyType(str, Enum):
    """Proxy type enum"""
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class ProxyStatus(str, Enum):
    """Proxy status enum"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"


class Account(Base):
    """Platform account entity"""
    __tablename__ = "account"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    platform_id = Column(PGUUID(as_uuid=True), ForeignKey("platform.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    username = Column(String(200), nullable=True)
    password_encrypted = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default=AccountStatus.DISCONNECTED.value)
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    agent_bindings = relationship("AgentPersonaBinding", back_populates="account", cascade="all, delete-orphan")
    browser_bindings = relationship("AccountBrowserBinding", back_populates="account", cascade="all, delete-orphan")
    proxy_bindings = relationship("AccountProxyBinding", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_account_platform", "platform_id", postgresql_where=is_deleted == False),
        Index("idx_account_status", "status", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<Account(id={self.id}, name={self.name}, platform={self.platform_id}, status={self.status})>"


class AgentPersonaBinding(Base):
    """Many-to-many binding between Account and Agent/Persona"""
    __tablename__ = "agent_persona_binding"

    account_id = Column(PGUUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), primary_key=True)
    agent_id = Column(PGUUID(as_uuid=True), ForeignKey("agent.id", ondelete="CASCADE"), primary_key=True)
    persona_id = Column(PGUUID(as_uuid=True), ForeignKey("persona.id", ondelete="CASCADE"), primary_key=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    bound_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships - use string references to avoid circular imports
    account = relationship("Account", back_populates="agent_bindings")
    persona = relationship("Persona")

    __table_args__ = (
        Index("idx_agent_persona_account", "account_id", "agent_id", "persona_id"),
    )

    def __repr__(self):
        return f"<AgentPersonaBinding(account={self.account_id}, agent={self.agent_id}, persona={self.persona_id})>"


class AccountBrowserBinding(Base):
    """Binding between Account and BrowserProfile"""
    __tablename__ = "account_browser_binding"

    account_id = Column(PGUUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), primary_key=True)
    profile_id = Column(PGUUID(as_uuid=True), ForeignKey("browser_profile.id", ondelete="CASCADE"), primary_key=True)
    bound_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    account = relationship("Account", back_populates="browser_bindings")
    profile = relationship("BrowserProfile")

    __table_args__ = (
        Index("idx_account_browser_account", "account_id", "profile_id"),
    )

    def __repr__(self):
        return f"<AccountBrowserBinding(account={self.account_id}, profile={self.profile_id})>"


class AccountProxyBinding(Base):
    """Binding between Account and Proxy"""
    __tablename__ = "account_proxy_binding"

    account_id = Column(PGUUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), primary_key=True)
    proxy_id = Column(PGUUID(as_uuid=True), ForeignKey("proxy.id", ondelete="CASCADE"), primary_key=True)
    bound_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    account = relationship("Account", back_populates="proxy_bindings")
    proxy = relationship("Proxy")

    __table_args__ = (
        Index("idx_account_proxy_account", "account_id", "proxy_id"),
    )

    def __repr__(self):
        return f"<AccountProxyBinding(account={self.account_id}, proxy={self.proxy_id})>"


class BrowserProfile(Base):
    """Browser profile entity for browser automation"""
    __tablename__ = "browser_profile"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    provider = Column(String(50), nullable=False, default="bitbrowser")
    profile_id = Column(String(100), nullable=False)
    name = Column(String(100), nullable=True)
    connection_status = Column(String(20), nullable=False, default="disconnected")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    account_bindings = relationship("AccountBrowserBinding", back_populates="profile", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_browser_profile_provider", "provider", postgresql_where=is_deleted == False),
        Index("idx_browser_profile_id", "profile_id", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<BrowserProfile(id={self.id}, name={self.name}, provider={self.provider})>"


class Proxy(Base):
    """Proxy server entity"""
    __tablename__ = "proxy"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    type = Column(String(10), nullable=False)  # http, https, socks5
    host = Column(String(200), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String(100), nullable=True)
    password_encrypted = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default=ProxyStatus.ACTIVE.value)
    last_tested = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    account_bindings = relationship("AccountProxyBinding", back_populates="proxy", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_proxy_status", "status", postgresql_where=is_deleted == False),
        Index("idx_proxy_type", "type", postgresql_where=is_deleted == False),
    )

    def __repr__(self):
        return f"<Proxy(id={self.id}, name={self.name}, type={self.type}, host={self.host}:{self.port})>"
