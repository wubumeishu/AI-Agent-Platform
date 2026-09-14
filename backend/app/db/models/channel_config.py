"""Channel configuration model — P5MSG-03 (channel adapter / delivery config).

``ChannelConfig`` (table ``channel_config``) is the *delivery* configuration
layer that sits on top of P5MSG-01's ``messages`` table:

* **channel**: the channel code from ``MESSAGE_CHANNELS`` (web / wechat /
  wechat_work / email / sms / whatsapp / line / douyin / xiaohongshu / other).
* **type**: the channel capability — ``messaging`` (inbound+outbound),
  ``comment`` (outbound on a comment), ``web`` (a form or browser-based
  channel). V1 only ships ``messaging`` for real delivery; the other types
  are permitted by schema but their adapters are not wired.
* **account_id**: the Phase-1 Account that owns the platform binding.
  Nullable so a channel can be configured before an account is attached
  (or for ``web`` channels with no account binding).
* **platform_code**: the Phase-1 Platform code that the channel maps to
  (e.g. ``wechat``); matches the ``channel`` value for V1 channels.
* **rate_limit_per_hour**: per-channel rate limit (business layer
  enforces via an in-memory window; see ``app/services/channel_rate_limiter.py``).
* **retry_max_attempts** / **retry_backoff_seconds**: per-channel retry
  strategy; the delivery service applies them between attempts.

Design notes
------------
* This table is deliberately *not* a re-creation of Phase-1's Platform
  registry (``platform``) — it is the Message-module-specific delivery
  config: same concept, different granularity. A Platform has a name,
  capabilities, and accounts; a ChannelConfig has a rate limit and retry
  strategy that the delivery service consumes.
* ``account_id`` is SET-NULL so delivery config outlives the account
  deletion (mirrors the ``ChannelMessage.account_id`` convention).
* ``platform_code`` is a soft reference (String, not FK): the Phase-1
  Platform table is a registry of platform *types*, not an instance
  registry, and P5MSG-03 must not couple delivery config to it with a
  hard FK (would block configuring channels before a Platform row exists,
  which is the P5MSG-01/02 baseline case).
* Uniqueness: at most one config per (channel, account_id, platform_code).
  ``account_id`` NULL is not constrained (multiple account-less channels
  of the same code can coexist, one per platform_code).
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from .base import Base


class ChannelConfig(Base):
    """Channel delivery configuration (table: ``channel_config``)."""
    __tablename__ = "channel_config"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel = Column(String(50), nullable=False, index=True)
    type = Column(String(20), nullable=False, default="messaging")
    platform_code = Column(String(50), nullable=True)
    account_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("account.id", ondelete="SET NULL"),
        nullable=True,
    )
    rate_limit_per_hour = Column(Integer, nullable=False, default=60)
    retry_max_attempts = Column(Integer, nullable=False, default=3)
    retry_backoff_seconds = Column(Integer, nullable=False, default=5)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                       default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                       default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_channel_config_channel", "channel",
              postgresql_where=is_deleted == False),
        Index("idx_channel_config_account", "account_id",
              postgresql_where=(is_deleted == False) & (account_id.isnot(None))),
        Index("uq_channel_config_channel_account_platform",
              "channel", "account_id", "platform_code",
              unique=True,
              postgresql_where=(is_deleted == False) & (account_id.isnot(None))),
    )

    def __repr__(self) -> str:
        return (
            f"<ChannelConfig(id={self.id}, channel={self.channel!r}, "
            f"account={self.account_id}, platform={self.platform_code!r}, "
            f"rate_limit/h={self.rate_limit_per_hour}, enabled={self.enabled})>"
        )
