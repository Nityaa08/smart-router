"""
Request guards: rate limiting (per API key, or per IP) and an optional shared API key.
"""
import hashlib
import secrets

from fastapi import HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings


def _supplied_key(request: Request) -> str:
    """The API key the caller sent, from X-API-Key or "Authorization: Bearer"."""
    supplied = request.headers.get("x-api-key", "")
    auth = request.headers.get("authorization", "")
    if not supplied and auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    return supplied


def client_ip(request: Request) -> str:
    """
    The caller's IP. With TRUST_PROXY_HEADERS=true (only behind a proxy that sets these
    headers itself, such as Vercel), use X-Real-IP / X-Forwarded-For; otherwise the socket.
    """
    if get_settings().trust_proxy_headers:
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return get_remote_address(request)


def _valid_key(supplied: str) -> bool:
    expected = get_settings().router_api_key
    return bool(expected and supplied) and secrets.compare_digest(supplied.encode(), expected.encode())


def rate_limit_key(request: Request) -> str:
    """
    Who a request counts against: the configured API key, if the caller sent it, otherwise
    their IP. A key that is not ROUTER_API_KEY (or any key when none is configured) counts
    against the IP: before 2026-11-25 every made-up key got a fresh limit, so sending
    "X-API-Key: junk1", "junk2", ... skipped the public demo's rate limit entirely.
    The key is hashed, so the raw key never becomes a storage key.
    """
    supplied = _supplied_key(request)
    if _valid_key(supplied):
        return "key:" + hashlib.sha256(supplied.encode()).hexdigest()[:16]
    return "ip:" + client_ip(request)


# Applied with @limiter.limit(...) on the chat endpoint (see api/chat.py).
# RATE_LIMIT_STORAGE="memory://" (the default) counts per process. Point it at Redis
# (e.g. redis://redis:6379) so every worker shares one count. If Redis can't be reached,
# the limiter falls back to in-memory counting instead of failing requests.
limiter = Limiter(
    key_func=rate_limit_key,
    storage_uri=get_settings().rate_limit_storage,
    in_memory_fallback_enabled=True,
)


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

    supplied = _supplied_key(request)
    if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
