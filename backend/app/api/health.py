import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..router.engine import get_providers
from .. import database
from ..config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health():
    cfg = get_settings()
    results = {"status": "ok", "db": "unknown", "provider": "unknown", "provider_name": cfg.provider}

    # Check DB
    if database.engine is None:
        results["db"] = "not configured (request log kept in memory)"
    else:
        try:
            async with database.engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            results["db"] = "up"
        except Exception as e:
            # The driver's message can include the host, port and user; keep it in the log.
            logger.warning("Health check: database unreachable: %s", e)
            results["db"] = f"down ({type(e).__name__})"
            results["status"] = "degraded"

    # Check provider (also verifies models are pulled)
    try:
        providers = get_providers()
        ok = await providers["simple"].health_check()
        if ok:
            results["provider"] = "up"
        else:
            model = providers["simple"].model_name
            hint = f" Run: ollama pull {model}" if cfg.provider == "ollama" else ""
            results["provider"] = f"down: model '{model}' did not answer the health check.{hint}"
            results["status"] = "degraded"
    except Exception as e:
        logger.warning("Health check: provider check failed: %s", e)
        results["provider"] = f"down ({type(e).__name__})"
        results["status"] = "degraded"

    status_code = 200 if results["status"] == "ok" else 503
    return JSONResponse(content=results, status_code=status_code)
