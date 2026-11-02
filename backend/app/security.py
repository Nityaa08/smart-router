"""
Request guards: per-IP rate limiting and an optional shared API key.
"""
import secrets

from fastapi import HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings

# Applied with @limiter.limit(...) on the chat endpoint (see api/chat.py).
limiter = Limiter(key_func=get_remote_address)


def rate_limit() -> str:
    """Read at request time so tests and reloads pick up the current setting."""
    return get_settings().rate_limit


async def require_api_key(request: Request) -> None:
    """
    If ROUTER_API_KEY is set, require it as "Authorization: Bearer <key>"
    or "X-API-Key: <key>". If it is empty, every request is allowed.
    """
    expected = get_settings().router_api_key
    if not expected:
        return

    supplied = request.headers.get("x-api-key", "")
    auth = request.headers.get("authorization", "")
    if not supplied and auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()

    if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
