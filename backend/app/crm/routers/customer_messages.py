"""Customer 360 message-timeline router (P5MSG-05).

Exposes the customer's unified, reverse-chronological message timeline at
::

    GET /api/v1/customers/{customer_id}/messages

(plus optional filter / pagination query params). This is the *query*
half of P5MSG-05's CRM integration; the *write-back* and *intent-landing*
halves are bus subscribers wired in ``app/main.py`` and owned by
``app/crm/services/message_crm_writeback.py`` and
``app/services/intent_conversation_lander.py``.

Mounted in ``app/main.py`` under ``prefix="/api/v1/customers"`` with this
router's own empty prefix, so the public path is single-prefixed
(canonical, per the P1-2 / t_b6b64212 convention).

Response envelope follows the Customer-360 router dialect
(``{"code": 0, "message": "success", "data": ...}``); a missing customer
is a 404 and an out-of-domain filter is a 400.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Customer 360 Messages"])


@router.get("/{customer_id}/messages", response_model=dict)
async def get_customer_messages(
    customer_id: UUID,
    conversation_id: Optional[UUID] = Query(None, description="限定单个会话"),
    kind: Optional[str] = Query(None, description="消息来源: chat | channel"),
    channel: Optional[str] = Query(None, description="按渠道筛选 (如 wechat/web)"),
    direction: Optional[str] = Query(None, description="渠道消息方向: in | out"),
    status: Optional[str] = Query(None, description="渠道投递状态"),
    start_time: Optional[datetime] = Query(None, description="时间下界 (UTC)"),
    end_time: Optional[datetime] = Query(None, description="时间上界 (UTC)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db=Depends(get_db),
):
    """客户 360 消息时间线（按时间倒序，chat + 渠道消息合并）。"""
    from app.crm.services.customer_messages import (
        CustomerResourceNotFound,
        TimelineParameterError,
        get_customer_message_timeline,
    )

    try:
        data = await get_customer_message_timeline(
            db,
            customer_id,
            conversation_id=conversation_id,
            kind=kind,
            channel=channel,
            direction=direction,
            status=status,
            start_time=start_time,
            end_time=end_time,
            skip=skip,
            limit=limit,
        )
    except CustomerResourceNotFound:
        raise HTTPException(status_code=404, detail="客户不存在")
    except TimelineParameterError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"code": 0, "message": "success", "data": data}
