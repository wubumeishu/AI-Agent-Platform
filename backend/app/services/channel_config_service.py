"""Channel-configuration CRUD service — P5MSG-03.

Business/data layer for the ``channel_config`` table: list / get / create /
update / soft-delete of per-channel delivery configuration (type, account
binding, platform code, rate limit, retry strategy, enabled flag). Kept as a
separate service from :mod:`app.services.channel_delivery_service` so the
*config* (data) concern and the *delivery* (platform-adapter business) concern
stay isolated — the router composes both.

Error mapping (PHASE1-API-SPEC business codes):
  * 4001 — config not found
  * 4002 — parameter error (unknown channel/type, bad bounds, duplicate binding)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_config import ChannelConfig
from app.schemas.messages import (
    CHANNEL_TYPES,
    MESSAGE_CHANNELS,
    ChannelConfigCreate,
    ChannelConfigUpdate,
)

logger = logging.getLogger(__name__)


class ChannelConfigNotFound(Exception):
    """4001 — a referenced channel config does not exist."""


class ChannelConfigParameterError(Exception):
    """4002 — a config input is invalid (unknown channel/type, bad bounds)."""


class ChannelConfigConflict(Exception):
    """4002 — a duplicate (channel, account, platform) live binding already exists."""


def _validate_domains(channel: Optional[str], ctype: Optional[str]) -> None:
    if channel is not None and channel not in MESSAGE_CHANNELS:
        raise ChannelConfigParameterError(
            f"channel must be one of {MESSAGE_CHANNELS}, got {channel!r}"
        )
    if ctype is not None and ctype not in CHANNEL_TYPES:
        raise ChannelConfigParameterError(
            f"type must be one of {CHANNEL_TYPES}, got {ctype!r}"
        )


class ChannelConfigService:
    """CRUD over channel delivery configuration."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------ read
    async def list_configs(
        self,
        page: int = 1,
        page_size: int = 20,
        channel: Optional[str] = None,
        account_id: Optional[UUID] = None,
        enabled: Optional[bool] = None,
    ) -> Tuple[List[ChannelConfig], int, int, int]:
        """Paginated config list with channel / account / enabled filters."""
        _validate_domains(channel, None)
        q = select(ChannelConfig).where(ChannelConfig.is_deleted == False)
        if channel is not None:
            q = q.where(ChannelConfig.channel == channel)
        if account_id is not None:
            q = q.where(ChannelConfig.account_id == account_id)
        if enabled is not None:
            q = q.where(ChannelConfig.enabled == enabled)

        total = (
            await self.db.execute(select(func.count()).select_from(q.subquery()))
        ).scalar_one()

        items = (
            await self.db.execute(
                q.order_by(ChannelConfig.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total, page, page_size

    async def get_config(self, config_id: UUID) -> ChannelConfig:
        row = (
            await self.db.execute(
                select(ChannelConfig).where(
                    ChannelConfig.id == config_id,
                    ChannelConfig.is_deleted == False,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ChannelConfigNotFound(f"Channel config not found: {config_id}")
        return row

    # ------------------------------------------------------------------ write
    async def create_config(self, data: ChannelConfigCreate) -> ChannelConfig:
        _validate_domains(data.channel, data.type)
        # Uniqueness: at most one *live* (channel, account_id, platform_code).
        # The DB also enforces this with a partial unique index; this is an
        # early, friendly 4002 (the DB race/unique violation is the last line).
        await self._assert_no_duplicate(data.channel, data.account_id, data.platform_code)

        config = ChannelConfig(
            channel=data.channel,
            type=data.type,
            platform_code=data.platform_code,
            account_id=data.account_id,
            rate_limit_per_hour=data.rate_limit_per_hour,
            retry_max_attempts=data.retry_max_attempts,
            retry_backoff_seconds=data.retry_backoff_seconds,
            enabled=data.enabled,
        )
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        logger.info(
            "channel config created id=%s channel=%s account=%s rate/h=%d",
            config.id, config.channel, config.account_id, config.rate_limit_per_hour,
        )
        return config

    async def update_config(
        self, config_id: UUID, data: ChannelConfigUpdate
    ) -> ChannelConfig:
        config = await self.get_config(config_id)
        # Validate any supplied domains before applying.
        _validate_domains(
            data.channel if data.channel is not None else config.channel,
            data.type if data.type is not None else config.type,
        )
        update = data.model_dump(exclude_unset=True)

        # A change that would duplicate another live binding -> 4002.
        new_channel = update.get("channel", config.channel)
        new_account = update.get("account_id", config.account_id)
        new_platform = update.get("platform_code", config.platform_code)
        if any(k in update for k in ("channel", "account_id", "platform_code")):
            await self._assert_no_duplicate(
                new_channel, new_account, new_platform, exclude_id=config.id
            )

        for key, value in update.items():
            setattr(config, key, value)
        config.updated_at = _utcnow()
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        logger.info("channel config updated id=%s fields=%s", config.id, list(update))
        return config

    async def delete_config(self, config_id: UUID) -> bool:
        """Soft delete (is_deleted=True). Returns True when a row was removed."""
        config = await self.get_config(config_id)
        config.is_deleted = True
        config.updated_at = _utcnow()
        self.db.add(config)
        await self.db.commit()
        logger.info("channel config soft-deleted id=%s", config_id)
        return True

    # ------------------------------------------------------------------ helper
    async def _assert_no_duplicate(
        self,
        channel: str,
        account_id: Optional[UUID],
        platform_code: Optional[str],
        exclude_id: Optional[UUID] = None,
    ) -> None:
        """Only account-bound configs are unique-constrained (matches the DB
        partial unique index, which ignores NULL account_id rows)."""
        if account_id is None:
            return
        q = select(ChannelConfig.id).where(
            ChannelConfig.channel == channel,
            ChannelConfig.account_id == account_id,
            ChannelConfig.platform_code == platform_code,
            ChannelConfig.is_deleted == False,
        )
        if exclude_id is not None:
            q = q.where(ChannelConfig.id != exclude_id)
        existing = (await self.db.execute(q)).scalars().first()
        if existing is not None:
            raise ChannelConfigConflict(
                f"A live channel config already exists for "
                f"(channel={channel!r}, account={account_id}, platform={platform_code!r})"
            )


def _utcnow() -> datetime:
    """tz-aware clock for config timestamps (matches P5MSG-01/02 models)."""
    return datetime.now(timezone.utc)
