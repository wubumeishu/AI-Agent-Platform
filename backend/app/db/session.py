"""Database Session Management

The DSN is resolved through :mod:`app.config`, which loads an optional
``<backend>/.env`` (real environment variables always win). The credential-free
default is only a last resort — supply a working ``DATABASE_URL`` via the
environment (env var, ``.env``, or launch script) for a usable deployment.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# Apply any local .env before reading DATABASE_URL. No-op if none is present;
# a real environment DATABASE_URL still wins.
from app.config import load_env, database_url

load_env()

DATABASE_URL = database_url()

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


def redact_dsn(dsn: str) -> str:
    """Return a copy of *dsn* with the password (and username) masked.

    Safe to put in logs / health payloads. Handles ``scheme://user:pass@host``
    (asyncpg / postgresql URLs); leaves scheme/host/dbname intact. Never
    throws on malformed input — an unparseable DSN is returned unchanged.
    """
    import re

    # scheme://user:password@host:port/db
    m = re.match(r"^(\w[\w+.-]*)://([^:@/]*):([^@/]*)@(.*)$", dsn or "")
    if m:
        scheme, _user, _pass, tail = m.groups()
        return f"{scheme}://*****:*****@{tail}"
    # scheme://user@host  (no password) -> mask the user too, just in case
    m = re.match(r"^(\w[\w+.-]*)://([^:@/]+)@(.*)$", dsn or "")
    if m:
        scheme, _user, tail = m.groups()
        return f"{scheme}://*****@{tail}"
    return dsn or ""


async def db_ping(timeout: float = 5.0) -> tuple[bool, str]:
    """Cheap, bounded DB reachability check.

    Opens one connection and runs ``SELECT 1``. Returns ``(ok, detail)``.
    *detail* never contains the DSN password (redacted) and no secret beyond
    the error type/message.
    """
    import asyncio
    from sqlalchemy import text

    async def _ping() -> None:
        # Bound the connect step so an unreachable/slow DB cannot hang boot.
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), timeout=timeout)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't propagate
        return False, f"{type(exc).__name__}: {exc}"



async def get_db():
    async with AsyncSessionLocal() as db:
        yield db
