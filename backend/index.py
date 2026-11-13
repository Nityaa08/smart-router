"""
Vercel entrypoint. Vercel's Python runtime loads the ASGI `app` from this file;
locally, run `uvicorn app.main:app` instead (see the README).
"""
from app.main import app  # noqa: F401
