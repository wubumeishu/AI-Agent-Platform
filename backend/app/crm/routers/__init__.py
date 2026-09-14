# CRM Sub-routers
#
# t_b6b64212 — single /api/v1 prefix convention:
#   * Every sub-router carries ONLY its module segment (no /api/v1). main.py's
#     include_router(crm_router, prefix="/api/v1") adds the /api/v1 prefix
#     exactly once, so canonical paths stay single-prefixed.
#   * main.py mounts customer_360, customer and tag DIRECTLY (its own
#     include_router calls at /api/v1/customers and /api/v1). To avoid
#     double-registration (duplicate operation IDs / spurious alias routes),
#     the aggregate below carries only the sub-routers that have no direct
#     mount in main.py: lead and lifecycle.
from fastapi import APIRouter

from .customer_360 import router as customer_360_router
from .customer import router as customer_router
from .lead import router as lead_router
from .tag import router as tag_router
from .lifecycle import router as lifecycle_router

# Aggregate the crm module's routes into one router, mounted at /api/v1 in
# main.py. Only lead + lifecycle live here; customer / tag / customer_360 are
# mounted directly by main.py so they must NOT also appear in the aggregate.
router = APIRouter()
router.include_router(lead_router)
router.include_router(lifecycle_router)

__all__ = [
    "router",
    "customer_360_router",
    "customer_router",
    "lead_router",
    "tag_router",
    "lifecycle_router",
]
