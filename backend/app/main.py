import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import get_settings
from .database import engine
from .api import chat, analytics, health
from .security import limiter

cfg = get_settings()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, cfg.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis
    try:
        app.state.redis = aioredis.from_url(cfg.redis_url, decode_responses=True)
        await app.state.redis.ping()
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning("Redis unavailable (%s) — caching disabled.", e)
        app.state.redis = None

    logger.info("Smart Router ready. Provider=%s", cfg.provider)
    yield

    await engine.dispose()
    if app.state.redis:
        await app.state.redis.aclose()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Smart Router",
    description="Intelligent AI cost-control gateway — routes prompts to the cheapest capable model.",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limit: RATE_LIMIT per client IP on POST /v1/chat/completions (api/chat.py)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — configurable via CORS_ORIGINS env var
_origins = [o.strip() for o in cfg.cors_origins.split(",")] if cfg.cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Static files ──────────────────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(chat.router)
app.include_router(analytics.router)
app.include_router(health.router)


@app.get("/")
async def root():
    return FileResponse(os.path.join(_static_dir, "index.html"))
