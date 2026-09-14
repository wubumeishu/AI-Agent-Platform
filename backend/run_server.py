"""FastAPI server test / local launch helper.

Launches ``app.main:app`` on port 8001. A local ``backend/.env`` is loaded
up-front (real environment variables still win), so the service uses a
credentialed DSN out-of-the-box when one is configured there.

Note: even a bare ``uvicorn app.main:app`` resolves the DSN the same way —
``app.db.session`` applies the optional ``.env`` at import time. This shim just
makes the startup path explicit and keeps the dev port convention (8001).
"""
import sys

sys.path.insert(0, ".")

# Apply the optional local .env (no-op if absent; env vars win) BEFORE uvicorn
# imports the app so DATABASE_URL is resolved from the intended config.
from app.config import load_env

load_env()

import uvicorn  # noqa: E402  (imported after env is loaded, on purpose)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=False)
