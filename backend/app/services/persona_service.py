"""Persona service layer"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.persona import Persona
from app.schemas.persona import (
    PersonaCreate,
    PersonaUpdate,
    PersonaResponse,
    PersonaListResponse,
    VersionHistory,
    VersionHistoryResponse,
)


class PersonaService:
    """Service for Persona CRUD and version management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Persona CRUD ----------

    async def list_personas(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[PersonaResponse], int]:
        """List personas with pagination"""
        query = select(Persona).where(Persona.is_deleted == False)
        total_query = select(func.count()).where(Persona.is_deleted == False)

        total_result = await self.db.execute(total_query)
        total = total_result.scalar() or 0

        query = query.order_by(Persona.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        personas = result.scalars().all()

        return [self._persona_to_response(p) for p in personas], total

    async def get_persona(self, persona_id: UUID) -> Optional[PersonaResponse]:
        """Get persona by ID"""
        result = await self.db.execute(
            select(Persona).where(Persona.id == persona_id, Persona.is_deleted == False)
        )
        persona = result.scalar_one_or_none()
        return self._persona_to_response(persona) if persona else None

    async def create_persona(self, data: PersonaCreate) -> PersonaResponse:
        """Create a new persona (version 1)"""
        persona = Persona(
            name=data.name,
            description=data.description,
            personality=data.personality,
            version=1,
        )
        self.db.add(persona)
        await self.db.commit()
        await self.db.refresh(persona)
        return self._persona_to_response(persona)

    async def update_persona(self, persona_id: UUID, data: PersonaUpdate) -> Optional[PersonaResponse]:
        """Update a persona"""
        result = await self.db.execute(
            select(Persona).where(Persona.id == persona_id, Persona.is_deleted == False)
        )
        persona = result.scalar_one_or_none()
        if not persona:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(persona, field, value)

        await self.db.commit()
        await self.db.refresh(persona)
        return self._persona_to_response(persona)

    async def delete_persona(self, persona_id: UUID) -> bool:
        """Soft delete a persona"""
        result = await self.db.execute(
            select(Persona).where(Persona.id == persona_id, Persona.is_deleted == False)
        )
        persona = result.scalar_one_or_none()
        if not persona:
            return False

        persona.is_deleted = True
        persona.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    # ---------- Version Management ----------

    async def get_version_history(self, persona_id: UUID) -> VersionHistoryResponse:
        """Get version history for a persona"""
        # Find the root persona
        result = await self.db.execute(
            select(Persona).where(Persona.id == persona_id, Persona.is_deleted == False)
        )
        root_persona = result.scalar_one_or_none()
        if not root_persona:
            return VersionHistoryResponse(items=[], total=0)

        # Get all versions (where this persona is the root or a descendant)
        query = select(Persona).where(
            Persona.is_deleted == False,
            Persona.parent_id == persona_id,
        ).order_by(Persona.version.asc())

        result = await self.db.execute(query)
        versions = result.scalars().all()

        # Include the root persona itself
        history = [self._version_to_response(root_persona)] + [
            self._version_to_response(v) for v in versions
        ]

        return VersionHistoryResponse(items=history, total=len(history))

    async def clone_persona(self, persona_id: UUID) -> PersonaResponse:
        """Clone a persona to create a new version"""
        # Get the source persona
        result = await self.db.execute(
            select(Persona).where(Persona.id == persona_id, Persona.is_deleted == False)
        )
        source = result.scalar_one_or_none()
        if not source:
            raise ValueError(f"Persona {persona_id} not found")

        # Create a new version
        new_version = source.version + 1
        new_persona = Persona(
            name=source.name,
            description=source.description,
            personality=source.personality.copy() if source.personality else {},
            version=new_version,
            parent_id=source.id,
        )
        self.db.add(new_persona)
        await self.db.commit()
        await self.db.refresh(new_persona)
        return self._persona_to_response(new_persona)

    # ---------- Helpers ----------

    def _persona_to_response(self, persona: Persona) -> PersonaResponse:
        """Convert Persona model to response schema"""
        return PersonaResponse(
            id=persona.id,
            name=persona.name,
            description=persona.description,
            personality=persona.personality,
            version=persona.version,
            parent_id=persona.parent_id,
            created_at=persona.created_at,
            updated_at=persona.updated_at,
        )

    def _version_to_response(self, persona: Persona) -> VersionHistory:
        """Convert Persona model to version history entry"""
        return VersionHistory(
            id=persona.id,
            name=persona.name,
            version=persona.version,
            parent_id=persona.parent_id,
            created_at=persona.created_at,
            updated_at=persona.updated_at,
        )
