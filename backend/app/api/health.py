from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..router.engine import get_providers
from ..database import engine
from ..config import get_settings

router = APIRouter()


@router.get("/health")
async def health():
    cfg = get_settings()
    results = {"status": "ok", "db": "unknown", "provider": "unknown", "provider_name": cfg.provider}

    # Check DB
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        results["db"] = "up"
    except Exception as e:
        results["db"] = f"down: {e}"
        results["status"] = "degraded"

    # Check provider (also verifies models are pulled)
    try:
        providers = get_providers()
        ok = await providers["simple"].health_check()
        if ok:
            results["provider"] = "up"
        else:
            model = providers["simple"].model_name
            results["provider"] = f"down — model '{model}' not found. Run: ollama pull {model}"
            results["status"] = "degraded"
    except Exception as e:
        results["provider"] = f"down: {e}"
        results["status"] = "degraded"

    status_code = 200 if results["status"] == "ok" else 503
    return JSONResponse(content=results, status_code=status_code)
