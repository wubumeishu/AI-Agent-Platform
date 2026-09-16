"""Analytics-surface authentication + tenant scoping (P6AN-16 / P1-1).

Closes the P1-1 architecture-review finding: every ``/api/v1/analytics/*``
endpoint was **unauthenticated** and had **no tenant scope**, so any caller
could read *cross-tenant* BI (conversion / ROI / won-deal cents / agent KPIs
/ lead funnel) and create / update / delete *any* account's analytics
definitions (``account_id`` was a free client-supplied body field).

Design (extends the ADR-011 / P0-1 JWT model in
:mod:`app.security.jwt_auth`):

* **Reuses** :func:`get_current_principal` — 401 on a missing / invalid /
  expired Bearer token. No new token machinery, no new dependency.
* Two router-level guards give the read / write split the P1 requires:

    - :func:`require_analytics_read`  — valid token + an analytics-capable
      role (read endpoints, minimum read permission).
    - :func:`require_analytics_write` — valid token + a write-capable role
      (CRUD, minimum write permission).

* **Tenant scoping.** The caller's ``account_id`` comes from the *server-
  issued* token, never from a client-supplied value. The router passes it to
  the services as the tenant boundary:

    - **Read (compute) layer** (overview / funnel / conversations / leads /
      agents / roi / private-domain) is restricted to data the caller's
      account can see (its bound agents' customers, and account-owned
      source rows).
    - **CRUD (definition) layer** enforces per-account ownership via
      :class:`~app.security.jwt_auth.AccountOwnershipError`, which the global
      403 handler in :mod:`app.main` already maps to a cross-account 403.
      ``account_id = NULL`` (platform-wide) definitions are only visible /
      mutable by an explicitly-authorized role
      (:data:`PLATFORM_WIDE_ROLES`).

Roles are the JWT ``role`` claim. The default ``operator`` role (the P0
posture) can read *and* write, but only within its own account; an elevated
role is required to reach platform-wide (``account_id = NULL``) definitions.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.security.jwt_auth import (
    AccountOwnershipError,
    PrivateDomainPrincipal,
    get_current_principal,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role model
# ---------------------------------------------------------------------------
#: Roles that may *read* the analytics surface at all. Anyone with one of
#: these is trusted to see their own tenant's BI; reads are the low bar.
ANALYTICS_ROLES = frozenset({"viewer", "operator", "admin", "platform_admin"})

#: Roles that may *write* (CRUD) analytics definitions. ``viewer`` is
#: read-only; the default ``operator`` may write within its own account.
WRITE_CAPABLE_ROLES = frozenset({"operator", "admin", "platform_admin"})

#: Roles explicitly authorized to reach *platform-wide*
#: (``account_id = NULL``) analytics definitions. This is the "显式授权角色"
#: the P1 requires for platform-wide data; a plain tenant operator is NOT in
#: this set, so it cannot read or mutate cross-tenant / platform-wide defs.
PLATFORM_WIDE_ROLES = frozenset({"admin", "platform_admin"})


def _forbidden(message: str, code: int = 403) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"code": code, "message": message, "data": None},
    )


# ---------------------------------------------------------------------------
# Router-level guards (the two auth dependencies every analytics endpoint
# takes — read for GET compute, write for CRUD).
# ---------------------------------------------------------------------------

def require_analytics_read(
    principal: PrivateDomainPrincipal = Depends(get_current_principal),
) -> PrivateDomainPrincipal:
    """Guard for analytics *read* endpoints (minimum read permission).

    401 is produced upstream by :func:`get_current_principal` (missing /
    invalid / expired Bearer). Here we enforce the *role* floor: the caller
    must hold an analytics-capable role. A token with an unknown role is a
    403, not a silent pass — the surface is authenticated AND authorized.

    An **unscoped** read (``account_id = None`` = "see the whole platform")
    is only reachable by an explicitly-authorized role: a plain tenant token
    with no account binding is a 403, so the P1 cross-tenant read path is
    closed at the guard, not just the service layer.
    """
    if principal.role not in ANALYTICS_ROLES:
        logger.info(
            "analytics read denied: principal=%s role=%s (not an analytics role)",
            principal.principal, principal.role,
        )
        raise _forbidden(
            f"role {principal.role!r} is not authorized to read analytics data"
        )
    if principal.account_id is None and principal.role not in PLATFORM_WIDE_ROLES:
        logger.info(
            "analytics read denied: principal=%s role=%s has no account binding; "
            "platform-wide read requires an elevated role",
            principal.principal, principal.role,
        )
        raise _forbidden("a platform-wide analytics read requires an elevated role")
    return principal


def require_analytics_write(
    principal: PrivateDomainPrincipal = Depends(get_current_principal),
) -> PrivateDomainPrincipal:
    """Guard for analytics *write* (CRUD) endpoints (minimum write permission)."""
    if principal.role not in WRITE_CAPABLE_ROLES:
        logger.info(
            "analytics write denied: principal=%s role=%s (no write capability)",
            principal.principal, principal.role,
        )
        raise _forbidden(
            f"role {principal.role!r} is not authorized to modify analytics definitions"
        )
    return principal


# ---------------------------------------------------------------------------
# Tenant scoping predicates (shared by every compute service)
# ---------------------------------------------------------------------------
#
# An account's *visible data* is derived from its two hard references:
#
#   account -> agent_persona_binding -> agent -> agent_customer_binding -> customer
#
# So a tenant's conversations / leads / agent KPIs are the data belonging to
# the customers served by that account's agents; its account-owned source
# rows (channel messages / deals / follow-ups / nurture executions) carry an
# explicit ``account_id``. Platform-wide actors (``account_id = NULL``, an
# elevated role) pass ``account_id=None`` to these helpers to mean "no
# scoping" and therefore see the whole platform.


def tenant_customer_subquery(account_id: UUID):
    """A scalar subquery of the customer ids visible to ``account_id``.

    Composes ``agent_persona_binding`` (account -> agent) onto
    ``agent_customer_binding`` (agent -> customer). Services bind this as
    ``<table>.customer_id.in_(tenant_customer_subquery(acct))`` to scope
    agent/customer-bound source tables (conversation / lead) to the tenant.
    """
    from app.db.models.account import AgentPersonaBinding
    from app.db.models.agent import AgentCustomerBinding

    agent_ids = (
        select(AgentPersonaBinding.agent_id)
        .where(AgentPersonaBinding.account_id == account_id)
    )
    return (
        select(AgentCustomerBinding.customer_id)
        .where(
            AgentCustomerBinding.agent_id.in_(agent_ids),
            AgentCustomerBinding.is_deleted == False,  # noqa: E712
        )
    )


def tenant_agent_subquery(account_id: UUID):
    """A scalar subquery of the agent ids bound to ``account_id``.

    Services that key off ``agent_id`` (agent-performance KPIs, ROI, funnel)
    restrict the agent dimension to the tenant's own agents this way.
    """
    from app.db.models.account import AgentPersonaBinding

    return (
        select(AgentPersonaBinding.agent_id)
        .where(AgentPersonaBinding.account_id == account_id)
    )


# ---------------------------------------------------------------------------
# CRUD ownership policy (definition layer)
# ---------------------------------------------------------------------------

def assert_account_owns(
    entity_account_id: Optional[UUID],
    principal: PrivateDomainPrincipal,
    resource_type: str = "analytics_definition",
) -> None:
    """Enforce per-account ownership for one analytics definition.

    Raises :class:`AccountOwnershipError` (-> the global 403 handler) when
    the caller may not read or mutate a definition owned by
    ``entity_account_id``. ``entity_account_id`` of ``None`` means the
    definition is *platform-wide* and is reachable only by an elevated role.

    * A **tenant** caller (``principal.account_id`` set) may touch only rows
      owned by its account; platform-wide rows require an elevated role.
    * A **platform-wide** caller (``principal.account_id`` None, elevated)
      may touch any row.
    """
    if principal.account_id is None:
        # Platform-wide actor: may touch any owned row; may touch a
        # platform-wide (NULL) row only with an explicitly-authorized role.
        if entity_account_id is None and principal.role not in PLATFORM_WIDE_ROLES:
            raise AccountOwnershipError(resource_type, None)
        return

    if entity_account_id is None:
        # Tenant reaching for a platform-wide definition: elevated role only.
        if principal.role not in PLATFORM_WIDE_ROLES:
            raise AccountOwnershipError(resource_type, None)
        return

    if entity_account_id != principal.account_id:
        logger.warning(
            "cross-account analytics %s denied: principal=%s account=%s row_account=%s",
            resource_type, principal.principal, principal.account_id, entity_account_id,
        )
        raise AccountOwnershipError(resource_type, entity_account_id)


def resolve_create_account(
    body_account_id: Optional[UUID],
    principal: PrivateDomainPrincipal,
    resource_type: str = "analytics_definition",
) -> Optional[UUID]:
    """Resolve the ``account_id`` to store when creating a definition.

    The client-supplied value is *never* trusted: a tenant account can only
    create definitions owned by its own account (a ``None`` body means "my
    account", not "platform-wide"); a platform-wide elevated actor may create
    a platform-wide (``None``) or account-scoped definition.

    Returns the authoritative ``account_id`` the service must persist, and
    raises :class:`AccountOwnershipError` on a cross-tenant write attempt.
    """
    if principal.account_id is not None:
        # Tenant operator: ownership is forced to the caller's account.
        if body_account_id is None:
            return principal.account_id
        if body_account_id != principal.account_id:
            logger.warning(
                "cross-account analytics create denied: principal=%s account=%s requested=%s",
                principal.principal, principal.account_id, body_account_id,
            )
            raise AccountOwnershipError(resource_type, body_account_id)
        return principal.account_id

    # Platform-wide actor (token with no account binding).
    if body_account_id is None and principal.role not in PLATFORM_WIDE_ROLES:
        raise AccountOwnershipError(resource_type, None)
    return body_account_id


def can_list_platform_wide(principal: PrivateDomainPrincipal) -> bool:
    """Whether the caller's definition *list* also includes platform-wide
    (``account_id = NULL``) rows in addition to its own account's rows."""
    return principal.account_id is not None and principal.role in PLATFORM_WIDE_ROLES


def list_account_predicates(model, principal: PrivateDomainPrincipal) -> list:
    """SQL predicates scoping a *definition-list* query to the caller's tenancy.

    * **Tenant** (``account_id`` set): only that account's definitions; an
      elevated tenant role additionally includes platform-wide (``NULL``)
      rows.
    * **Platform-wide actor** (``account_id`` None — guaranteed elevated by the
      read/write guards): unscoped; sees every tenant's definitions.

    Pass the returned (AND-able) predicate list into the service's list query.
    """
    from sqlalchemy import or_

    if principal.account_id is None:
        return []  # platform-wide actor: no scoping
    preds = [model.account_id == principal.account_id]
    if principal.role in PLATFORM_WIDE_ROLES:
        preds.append(model.account_id.is_(None))
    return [or_(*preds)]


def resolve_account_param(
    requested: Optional[UUID],
    principal: PrivateDomainPrincipal,
    resource_type: str = "analytics",
) -> Optional[UUID]:
    """Authoritative account scope for a client-supplied ``account_id`` param
    (the PDC / ROI read endpoints keep that Query param for API-shape
    compatibility; the *trusted* value comes from the token, never the client).

    A tenant may only scope to its own account — a different id is a
    cross-tenant attempt and raises :class:`AccountOwnershipError` (-> 403).
    A platform-wide actor passes the requested value (or ``None`` = all)
    through unchanged.
    """
    if principal.account_id is not None:
        if requested is not None and requested != principal.account_id:
            logger.warning(
                "cross-account analytics read param denied: principal=%s account=%s requested=%s",
                principal.principal, principal.account_id, requested,
            )
            raise AccountOwnershipError(resource_type, requested)
        return principal.account_id
    return requested


# ---------------------------------------------------------------------------
# Test helper (imported by the analytics test suites to mint a principal
# without standing up a real token issuer).
# ---------------------------------------------------------------------------

def test_principal(
    account_id: Optional[UUID] = None,
    role: str = "operator",
    principal: str = "test-user",
) -> PrivateDomainPrincipal:
    """Build a :class:`PrivateDomainPrincipal` for tests.

    ``account_id=None`` + an elevated role models a platform-wide actor;
    a set ``account_id`` models a tenant operator.
    """
    return PrivateDomainPrincipal(principal=principal, account_id=account_id, role=role)


def override_analytics_auth(app, principal: PrivateDomainPrincipal) -> None:
    """Test seam: force every analytics auth dependency to return ``principal``.

    Because the read/write guards are wired through
    ``Depends(get_current_principal)``, overriding that single callable in
    ``app.dependency_overrides`` covers the whole analytics surface without a
    real JWT.
    """
    app.dependency_overrides[get_current_principal] = lambda: principal
