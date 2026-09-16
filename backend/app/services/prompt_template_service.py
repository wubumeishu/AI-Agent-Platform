"""Prompt Template Service - CRUD and version management"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.prompt_template import PromptTemplate, PromptTemplateUsage
from app.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
    PromptTemplateResponse,
    VersionHistoryResponse,
    VersionDetailResponse,
    RollbackResponse,
    RenderedTemplate,
    TemplateVariablesResponse,
    VariableDefinition,
)


class PromptTemplateService:
    """Service for managing prompt templates with version control"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_template(self, data: PromptTemplateCreate) -> PromptTemplateResponse:
        """Create a new prompt template or version"""
        # Determine if this is a baseline or version
        is_baseline = data.is_baseline
        
        if is_baseline:
            # Check if there's already a baseline with same name
            existing = await self._get_by_name(data.name, include_deleted=False)
            if existing:
                # Update existing baseline
                existing.content = data.content
                existing.variables = data.variables or []
                existing.template_type = data.template_type
                existing.description = data.description
                existing.category = data.category
                existing.updated_at = datetime.now(timezone.utc)
                await self.db.commit()
                await self.db.refresh(existing)
                return self._to_response(existing)
            
            # Create new baseline
            template = PromptTemplate(
                name=data.name,
                description=data.description,
                content=data.content,
                template_type=data.template_type,
                category=data.category,
                variables=data.variables or [],
                version=1,
                is_baseline=True,
            )
        else:
            # Create new version
            parent_id = data.parent_id or self._find_parent(data.name)
            if not parent_id:
                raise ValueError(f"No baseline found for template name: {data.name}")
            
            parent = await self._get_by_id(parent_id)
            if not parent:
                raise ValueError(f"Parent template not found: {parent_id}")
            
            # Increment version number
            new_version = parent.version + 1
            
            template = PromptTemplate(
                name=data.name,
                description=data.description,
                content=data.content,
                template_type=data.template_type,
                category=data.category,
                variables=data.variables or [],
                version=new_version,
                parent_id=parent.id,
                is_baseline=False,
            )
        
        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)
        return self._to_response(template)

    async def get_template(self, template_id: UUID) -> Optional[PromptTemplateResponse]:
        """Get template by ID"""
        template = await self._get_by_id(template_id)
        return self._to_response(template) if template else None

    async def list_templates(
        self,
        page: int = 1,
        page_size: int = 20,
        template_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> tuple[List[PromptTemplateResponse], int]:
        """List templates with pagination and filtering"""
        query = select(PromptTemplate).where(PromptTemplate.is_deleted == False)
        
        if template_type:
            query = query.where(PromptTemplate.template_type == template_type)
        if category:
            query = query.where(PromptTemplate.category == category)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Get paginated results
        query = query.order_by(PromptTemplate.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.db.execute(query)
        templates = result.scalars().all()
        
        return [self._to_response(t) for t in templates], total

    async def update_template(
        self, template_id: UUID, data: PromptTemplateUpdate
    ) -> Optional[PromptTemplateResponse]:
        """Update template fields"""
        template = await self._get_by_id(template_id)
        if not template:
            return None
        
        if data.name is not None:
            template.name = data.name
        if data.description is not None:
            template.description = data.description
        if data.content is not None:
            template.content = data.content
        if data.template_type is not None:
            template.template_type = data.template_type
        if data.category is not None:
            template.category = data.category
        if data.variables is not None:
            template.variables = data.variables
        if data.is_baseline is not None:
            template.is_baseline = data.is_baseline
        
        template.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(template)
        return self._to_response(template)

    async def delete_template(self, template_id: UUID) -> bool:
        """Soft delete a template"""
        template = await self._get_by_id(template_id)
        if not template:
            return False
        
        template.is_deleted = True
        await self.db.commit()
        return True

    async def get_version_history(self, template_id: UUID) -> VersionHistoryResponse:
        """Get version history for a template"""
        template = await self._get_by_id(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")
        
        # Get all versions (same name)
        versions_query = select(PromptTemplate).where(
            PromptTemplate.name == template.name,
            PromptTemplate.is_deleted == False,
        ).order_by(PromptTemplate.version.desc())
        
        result = await self.db.execute(versions_query)
        versions = result.scalars().all()
        
        return VersionHistoryResponse(
            items=[
                VersionHistory(
                    id=v.id,
                    name=v.name,
                    version=v.version,
                    parent_id=v.parent_id,
                    is_baseline=v.is_baseline,
                    created_at=v.created_at,
                    updated_at=v.updated_at,
                )
                for v in versions
            ],
            total=len(versions),
        )

    async def render_template(
        self, template_id: UUID, variables: dict
    ) -> RenderedTemplate:
        """Render template with variable substitution"""
        template = await self._get_by_id(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")
        
        # Extract variables from template content
        extracted_vars = self._extract_variables(template.content)
        
        # Apply variable substitution
        rendered = template.content
        for var_name, var_value in variables.items():
            rendered = rendered.replace(f"{{{{{var_name}}}}}", str(var_value))
        
        # Track usage
        usage = PromptTemplateUsage(
            template_id=template_id,
            rendered_content=rendered,
            variables_used=variables,
        )
        self.db.add(usage)
        await self.db.commit()
        
        return RenderedTemplate(
            template_id=template.id,
            template_name=template.name,
            content=rendered,
            variables_used=variables,
        )

    async def get_template_variables(self, template_id: UUID) -> TemplateVariablesResponse:
        """Extract and return variables from template"""
        template = await self._get_by_id(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")
        
        variables = self._extract_variables(template.content)
        
        # Create variable definitions
        var_defs = []
        for var_name in variables:
            # Check if default exists in stored variables
            default = None
            for v in template.variables or []:
                if isinstance(v, dict) and v.get("name") == var_name:
                    default = v.get("default")
                    break
            
            var_defs.append(VariableDefinition(
                name=var_name,
                default=default,
            ))
        
        return TemplateVariablesResponse(
            template_id=template.id,
            template_name=template.name,
            variables=var_defs,
        )

    async def compare_versions(
        self, template_id: UUID, version1: int, version2: int
    ) -> dict:
        """Compare two versions of a template"""
        template = await self._get_by_id(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        # Find both versions
        versions_query = select(PromptTemplate).where(
            PromptTemplate.name == template.name,
            PromptTemplate.is_deleted == False,
            PromptTemplate.version.in_([version1, version2]),
        )
        result = await self.db.execute(versions_query)
        versions = result.scalars().all()

        v1_content = None
        v2_content = None
        for v in versions:
            if v.version == version1:
                v1_content = v.content
            elif v.version == version2:
                v2_content = v.content

        if not v1_content or not v2_content:
            raise ValueError("One or both versions not found")

        return {
            "template_id": template_id,
            "template_name": template.name,
            "version1": {
                "version": version1,
                "content": v1_content,
            },
            "version2": {
                "version": version2,
                "content": v2_content,
            },
            "diff": self._compute_diff(v1_content, v2_content),
        }

    async def get_version_detail(
        self, template_id: UUID, version: int
    ) -> Optional["VersionDetailResponse"]:
        """Get detailed information for a specific version"""
        template = await self._get_by_id(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        # Find the specific version by name and version number
        version_query = select(PromptTemplate).where(
            PromptTemplate.name == template.name,
            PromptTemplate.version == version,
            PromptTemplate.is_deleted == False,
        )
        result = await self.db.execute(version_query)
        version_template = result.scalar_one_or_none()

        if not version_template:
            raise ValueError(
                f"Version {version} not found for template '{template.name}'"
            )

        return self._to_version_detail_response(version_template)

    async def rollback_version(
        self, template_id: UUID, version: int
    ) -> "RollbackResponse":
        """Rollback to a specific version by creating a new version with the old content"""
        template = await self._get_by_id(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        # Get the target version to rollback to
        target_query = select(PromptTemplate).where(
            PromptTemplate.name == template.name,
            PromptTemplate.version == version,
            PromptTemplate.is_deleted == False,
        )
        result = await self.db.execute(target_query)
        target_version = result.scalar_one_or_none()

        if not target_version:
            raise ValueError(
                f"Version {version} not found for template '{template.name}'"
            )

        # Find current latest version
        latest_query = select(PromptTemplate).where(
            PromptTemplate.name == template.name,
            PromptTemplate.is_deleted == False,
        ).order_by(PromptTemplate.version.desc()).limit(1)
        latest_result = await self.db.execute(latest_query)
        latest_version = latest_result.scalar_one_or_none()

        if not latest_version:
            raise ValueError(f"No active versions found for template '{template.name}'")

        # Create new version with incremented version number
        new_version_number = latest_version.version + 1

        new_template = PromptTemplate(
            name=template.name,
            description=f"rollback from version {version}: {latest_version.description or ''}",
            content=target_version.content,
            template_type=target_version.template_type,
            category=target_version.category,
            variables=target_version.variables or [],
            version=new_version_number,
            parent_id=latest_version.id,
            is_baseline=target_version.is_baseline,
        )

        self.db.add(new_template)
        await self.db.commit()
        await self.db.refresh(new_template)

        return RollbackResponse(
            template_id=template.id,
            template_name=template.name,
            new_version=new_version_number,
            rolled_back_from=version,
            message=f"Successfully rolled back to version {version}",
        )

    # ========== Private Methods ==========

    async def _get_by_id(self, template_id: UUID) -> Optional[PromptTemplate]:
        """Get template by ID"""
        result = await self.db.execute(
            select(PromptTemplate).where(
                PromptTemplate.id == template_id,
                PromptTemplate.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def _get_by_name(
        self, name: str, include_deleted: bool = False
    ) -> Optional[PromptTemplate]:
        """Get template by name"""
        query = select(PromptTemplate).where(PromptTemplate.name == name)
        if not include_deleted:
            query = query.where(PromptTemplate.is_deleted == False)
        query = query.order_by(PromptTemplate.version.desc())
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    def _find_parent(self, name: str) -> Optional[UUID]:
        """Find the parent (baseline) template ID by name"""
        result = self.db.execute(
            select(PromptTemplate.id).where(
                PromptTemplate.name == name,
                PromptTemplate.is_baseline == True,
                PromptTemplate.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    def _extract_variables(self, content: str) -> List[str]:
        """Extract {{variable}} patterns from content"""
        import re
        pattern = r'\{\{(\w+)\}\}'
        return list(set(re.findall(pattern, content)))

    def _compute_diff(self, old: str, new: str) -> dict:
        """Compute simple diff between two strings"""
        old_lines = old.split('\n')
        new_lines = new.split('\n')
        
        added = []
        removed = []
        
        for line in new_lines:
            if line not in old_lines:
                added.append(line)
        for line in old_lines:
            if line not in new_lines:
                removed.append(line)
        
        return {
            "added_lines": len(added),
            "removed_lines": len(removed),
            "added": added[:10],  # Limit to first 10
            "removed": removed[:10],
        }

    def _to_response(self, template: PromptTemplate) -> PromptTemplateResponse:
        """Convert model to response schema"""
        return PromptTemplateResponse(
            id=template.id,
            name=template.name,
            description=template.description,
            content=template.content,
            template_type=template.template_type,
            category=template.category,
            variables=template.variables,
            version=template.version,
            parent_id=template.parent_id,
            is_baseline=template.is_baseline,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )

    def _to_version_detail_response(
        self, template: PromptTemplate
    ) -> "VersionDetailResponse":
        """Convert model to version detail response schema"""
        return VersionDetailResponse(
            id=template.id,
            name=template.name,
            description=template.description,
            content=template.content,
            template_type=template.template_type,
            category=template.category,
            variables=template.variables,
            version=template.version,
            parent_id=template.parent_id,
            is_baseline=template.is_baseline,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )


# Import here to avoid circular import
from app.schemas.prompt_template import VersionHistory
