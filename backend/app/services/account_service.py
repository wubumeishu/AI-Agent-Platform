"""Account service layer"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import (
    Account,
    AgentPersonaBinding,
    AccountBrowserBinding,
    AccountProxyBinding,
    BrowserProfile,
    Proxy,
)
from app.db.models.platform import Platform
from app.security.crypto import hash_password, is_hashed
from app.schemas.account import (
    AccountCreate,
    AccountUpdate,
    AccountResponse,
    AgentBindingCreate,
    AgentBindingResponse,
    BrowserBindingCreate,
    BrowserBindingResponse,
    ProxyBindingCreate,
    ProxyBindingResponse,
    TestConnectionResponse,
)

# P5MSG-FIX-2 (P1-1): credentials must never be echoed to API responses.
# The ``password_encrypted`` column is masked on the way out (see
# :func:`mask_credential`); response callers only ever see whether a
# credential is set, never its value.


def mask_credential(value: Optional[str]) -> Optional[str]:
    """Mask a stored credential value for API responses (P1-1).

    Returns ``None`` when unset; otherwise a fixed-shape ``"***"`` sentinel
    (the empty string maps to ``""`` so callers can still tell *no value*
    from *value set* without seeing the value itself). The raw credential
    is never returned to any response path.
    """
    if value is None:
        return None
    return "***" if value else ""


class AccountService:
    """Service for Account CRUD and binding management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Account CRUD ----------

    async def list_accounts(
        self,
        page: int = 1,
        page_size: int = 20,
        platform_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[List[AccountResponse], int]:
        """List accounts with pagination and filters"""
        query = select(Account).where(Account.is_deleted == False)
        total_query = select(func.count()).where(Account.is_deleted == False)

        if platform_id:
            resolved = await self._resolve_platform_id(platform_id)
            if resolved is not None:
                query = query.where(Account.platform_id == resolved)
                total_query = total_query.where(Account.platform_id == resolved)
            else:
                # Unknown platform reference: return an empty page rather than 500.
                query = query.where(Account.platform_id == None)
                total_query = total_query.where(Account.platform_id == None)

        if status:
            query = query.where(Account.status == status)
            total_query = total_query.where(Account.status == status)

        # Get total count
        total_result = await self.db.execute(total_query)
        total = total_result.scalar() or 0

        # Apply pagination
        query = query.order_by(Account.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        accounts = result.scalars().all()

        return [await self._account_to_response(acc) for acc in accounts], total

    async def get_account(self, account_id: UUID) -> Optional[AccountResponse]:
        """Get account by ID"""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id, Account.is_deleted == False)
        )
        account = result.scalar_one_or_none()
        return await self._account_to_response(account) if account else None

    async def create_account(self, data: AccountCreate) -> AccountResponse:
        """Create a new account

        The API contract (schema + frontend) addresses platforms by their
        ``code`` (e.g. "wechat"), while the DB stores a UUID FK. Resolve the
        code/UUID to the platform UUID before writing.
        """
        platform_id = await self._resolve_platform_id(data.platform_id)
        # F-3: credentials are stored hashed (irreversible), never symmetrically
        # encrypted or plaintext — a DB dump must not expose usable credentials.
        # A value that is already a hash is stored as-is (no double-hash).
        account = Account(
            platform_id=platform_id,
            name=data.name,
            username=data.username,
            password_encrypted=(
                data.password_encrypted
                if not data.password_encrypted or is_hashed(data.password_encrypted)
                else hash_password(data.password_encrypted)
            ),
            status=data.status or "disconnected",
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(account)
        return await self._account_to_response(account)

    async def update_account(self, account_id: UUID, data: AccountUpdate) -> Optional[AccountResponse]:
        """Update an account"""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id, Account.is_deleted == False)
        )
        account = result.scalar_one_or_none()
        if not account:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == "platform_id" and value is not None:
                resolved = await self._resolve_platform_id(value)
                if resolved is None:
                    raise ValueError(f"Platform '{value}' not found")
                value = resolved
            # F-3: hash a newly-supplied credential; leave a stored hash alone
            # unless the client sends a new (plaintext) value to replace it.
            if field == "password_encrypted" and value:
                value = value if is_hashed(value) else hash_password(value)
            setattr(account, field, value)

        await self.db.commit()
        await self.db.refresh(account)
        return await self._account_to_response(account)

    async def delete_account(self, account_id: UUID) -> bool:
        """Soft delete an account"""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id, Account.is_deleted == False)
        )
        account = result.scalar_one_or_none()
        if not account:
            return False

        account.is_deleted = True
        account.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    # ---------- Agent Bindings ----------

    async def list_agent_bindings(self, account_id: UUID) -> List[AgentBindingResponse]:
        """List all agent bindings for an account"""
        result = await self.db.execute(
            select(AgentPersonaBinding)
            .where(AgentPersonaBinding.account_id == account_id)
            .order_by(AgentPersonaBinding.bound_at.desc())
        )
        bindings = result.scalars().all()
        return [self._agent_binding_to_response(b) for b in bindings]

    async def create_agent_binding(self, account_id: UUID, data: AgentBindingCreate) -> AgentBindingResponse:
        """Create an agent binding for an account"""
        binding = AgentPersonaBinding(
            account_id=account_id,
            agent_id=data.agent_id,
            persona_id=data.persona_id,
            is_primary=data.is_primary,
        )
        self.db.add(binding)
        await self.db.commit()
        await self.db.refresh(binding)
        return self._agent_binding_to_response(binding)

    async def delete_agent_binding(self, account_id: UUID, agent_id: UUID, persona_id: UUID) -> bool:
        """Delete an agent binding"""
        result = await self.db.execute(
            select(AgentPersonaBinding).where(
                AgentPersonaBinding.account_id == account_id,
                AgentPersonaBinding.agent_id == agent_id,
                AgentPersonaBinding.persona_id == persona_id,
            )
        )
        binding = result.scalar_one_or_none()
        if not binding:
            return False

        await self.db.delete(binding)
        await self.db.commit()
        return True

    # ---------- Browser Bindings ----------

    async def list_browser_bindings(self, account_id: UUID) -> List[BrowserBindingResponse]:
        """List all browser bindings for an account"""
        result = await self.db.execute(
            select(AccountBrowserBinding)
            .where(AccountBrowserBinding.account_id == account_id)
            .order_by(AccountBrowserBinding.bound_at.desc())
        )
        bindings = result.scalars().all()
        return [await self._browser_binding_to_response(b) for b in bindings]

    async def create_browser_binding(self, account_id: UUID, data: BrowserBindingCreate) -> BrowserBindingResponse:
        """Create a browser binding for an account"""
        binding = AccountBrowserBinding(
            account_id=account_id,
            profile_id=data.profile_id,
        )
        self.db.add(binding)
        await self.db.commit()
        await self.db.refresh(binding)
        return await self._browser_binding_to_response(binding)

    async def delete_browser_binding(self, account_id: UUID, profile_id: UUID) -> bool:
        """Delete a browser binding"""
        result = await self.db.execute(
            select(AccountBrowserBinding).where(
                AccountBrowserBinding.account_id == account_id,
                AccountBrowserBinding.profile_id == profile_id,
            )
        )
        binding = result.scalar_one_or_none()
        if not binding:
            return False

        await self.db.delete(binding)
        await self.db.commit()
        return True

    # ---------- Proxy Bindings ----------

    async def list_proxy_bindings(self, account_id: UUID) -> List[ProxyBindingResponse]:
        """List all proxy bindings for an account"""
        result = await self.db.execute(
            select(AccountProxyBinding)
            .where(AccountProxyBinding.account_id == account_id)
            .order_by(AccountProxyBinding.bound_at.desc())
        )
        bindings = result.scalars().all()
        return [await self._proxy_binding_to_response(b) for b in bindings]

    async def create_proxy_binding(self, account_id: UUID, data: ProxyBindingCreate) -> ProxyBindingResponse:
        """Create a proxy binding for an account"""
        binding = AccountProxyBinding(
            account_id=account_id,
            proxy_id=data.proxy_id,
        )
        self.db.add(binding)
        await self.db.commit()
        await self.db.refresh(binding)
        return await self._proxy_binding_to_response(binding)

    async def delete_proxy_binding(self, account_id: UUID, proxy_id: UUID) -> bool:
        """Delete a proxy binding"""
        result = await self.db.execute(
            select(AccountProxyBinding).where(
                AccountProxyBinding.account_id == account_id,
                AccountProxyBinding.proxy_id == proxy_id,
            )
        )
        binding = result.scalar_one_or_none()
        if not binding:
            return False

        await self.db.delete(binding)
        await self.db.commit()
        return True

    # ---------- Test Connection ----------

    async def test_connection(self, account_id: UUID) -> TestConnectionResponse:
        """Test account connection (V1: mock response)"""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id, Account.is_deleted == False)
        )
        account = result.scalar_one_or_none()
        if not account:
            return TestConnectionResponse(
                success=False,
                message="Account not found",
                status="not_found",
                timestamp=datetime.now(timezone.utc),
            )

        # V1: Mock connection test - return simulated success
        # Real implementation will use BitBrowser SDK
        mock_success = True
        mock_status = "connected" if mock_success else "failed"
        mock_message = "Connection test successful (mock)" if mock_success else "Connection test failed (mock)"

        account.status = mock_status
        account.last_login = datetime.now(timezone.utc)
        await self.db.commit()

        return TestConnectionResponse(
            success=mock_success,
            message=mock_message,
            status=mock_status,
            timestamp=datetime.now(timezone.utc),
        )

    # ---------- Helpers ----------

    async def _resolve_platform_id(self, ref) -> Optional[UUID]:
        """Resolve a platform reference to its UUID.

        Accepts either a platform ``code`` (e.g. "wechat") — the value the API
        contract and frontend use — or a raw UUID string. Returns None when the
        reference does not match any existing (non-deleted) platform.
        """
        if ref is None:
            return None
        uuid_val = None
        s = str(ref).strip()
        try:
            uuid_val = UUID(s)
        except (ValueError, AttributeError, TypeError):
            uuid_val = None
        if uuid_val is not None:
            res = await self.db.execute(
                select(Platform.id).where(Platform.id == uuid_val, Platform.is_deleted == False)
            )
            if res.scalar_one_or_none() is not None:
                return uuid_val
            return None
        res = await self.db.execute(
            select(Platform.id).where(Platform.code == s, Platform.is_deleted == False)
        )
        return res.scalar_one_or_none()

    async def _account_to_response(self, account: Account) -> AccountResponse:
        """Convert Account model to response schema.

        The API contract exposes the platform by its ``code`` (string), while
        the DB stores a UUID FK. Resolve via an explicit Platform query (safe
        in async sessions — no ORM lazy-loading), falling back to the raw UUID
        string when the platform row is missing.
        """
        if account is None:
            raise ValueError("account is None")
        res = await self.db.execute(
            select(Platform.code).where(
                Platform.id == account.platform_id, Platform.is_deleted == False
            )
        )
        code = res.scalar_one_or_none()
        platform_id = code if code is not None else str(account.platform_id)
        return AccountResponse(
            id=account.id,
            platform_id=platform_id,
            name=account.name,
            username=account.username,
            # P5MSG-FIX-2 (P1-1): never echo the credential value to any
            # response — mask on the way out.
            password_encrypted=mask_credential(account.password_encrypted),
            status=account.status,
            last_login=account.last_login,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    def _agent_binding_to_response(self, binding) -> AgentBindingResponse:
        """Convert AgentPersonaBinding model to response schema"""
        return AgentBindingResponse(
            account_id=binding.account_id,
            agent_id=binding.agent_id,
            persona_id=binding.persona_id,
            is_primary=binding.is_primary,
            bound_at=binding.bound_at,
        )

    async def _browser_binding_to_response(self, binding) -> BrowserBindingResponse:
        """Convert AccountBrowserBinding model to response schema.

        Load profile info via an explicit query (the ORM relationship would
        trigger a sync lazy-load that fails in an async session).
        """
        profile_name = None
        profile_provider = None
        prof = await self.db.execute(
            select(BrowserProfile).where(BrowserProfile.id == binding.profile_id)
        )
        profile = prof.scalar_one_or_none()
        if profile is not None:
            profile_name = profile.name
            profile_provider = getattr(profile, "provider", None)

        return BrowserBindingResponse(
            account_id=binding.account_id,
            profile_id=binding.profile_id,
            bound_at=binding.bound_at,
            profile_name=profile_name,
            profile_provider=profile_provider,
        )

    async def _proxy_binding_to_response(self, binding) -> ProxyBindingResponse:
        """Convert AccountProxyBinding model to response schema.

        Load proxy info via an explicit query (the ORM relationship would
        trigger a sync lazy-load that fails in an async session).
        """
        proxy_name = None
        proxy_type = None
        proxy_host = None
        proxy_port = None
        res = await self.db.execute(
            select(Proxy).where(Proxy.id == binding.proxy_id, Proxy.is_deleted == False)
        )
        proxy = res.scalar_one_or_none()
        if proxy is not None:
            proxy_name = proxy.name
            proxy_type = proxy.type
            proxy_host = proxy.host
            proxy_port = proxy.port

        return ProxyBindingResponse(
            account_id=binding.account_id,
            proxy_id=binding.proxy_id,
            bound_at=binding.bound_at,
            proxy_name=proxy_name,
            proxy_type=proxy_type,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
        )
