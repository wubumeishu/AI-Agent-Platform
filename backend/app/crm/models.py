"""
CRM Models: Lifecycle Stage + Funnel Pipeline
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.db.models.lifecycle import LifecycleStage, LifecycleStageLog

__all__ = ["LifecycleStage", "LifecycleStageLog"]
