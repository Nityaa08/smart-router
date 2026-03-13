import uuid
import json
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..schemas.request import ChatRequest
from ..router.engine import route, route_stream

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_redis(request: Request):
    return getattr(request.app.state, "redis", None)


def _err(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": detail, "type": "router_error"}})


@router.post("/v1/chat/completions")
async def chat_completions(body: ChatRequest, request: Request):
    messages = [m.model_dump() for m in body.messages]
    redis = _get_redis(request)

    # ── Streaming ─────────────────────────────────────────────────────────────
    if body.stream:
        stream_iter, tier, model = await route_stream(
            messages,
            force_tier=body.force_tier,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )

        async def sse_generator():
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
            async for chunk in await stream_iter:
                data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"delta": {"content": chunk}, "index": 0, "finish_reason": None}],
                }
                yield f"data: {json.dumps(data)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "X-Router-Tier": tier,
                "X-Router-Model": model,
            },
        )

    # ── Non-streaming ─────────────────────────────────────────────────────────
    try:
        result = await route(
            messages,
            force_tier=body.force_tier,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            redis_client=redis,
        )
    except RuntimeError as e:
        return _err(503, str(e))
    except Exception as e:
        logger.exception("Unexpected error in route()")
        return _err(500, f"Internal error: {e}")

    response_body = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": result.response.model,
        "choices": [
            {
                "message": {"role": "assistant", "content": result.response.content},
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.response.usage.input_tokens,
            "completion_tokens": result.response.usage.output_tokens,
            "total_tokens": result.response.usage.input_tokens + result.response.usage.output_tokens,
        },
        "router": {
            "tier": result.tier,
            "model": result.response.model,
            "provider": result.provider_name,
            "actual_cost_usd": result.actual_cost,
            "cost_saved_usd": result.cost_saved,
            "latency_ms": result.latency_ms,
            "from_cache": result.from_cache,
        },
    }

    return JSONResponse(
        content=response_body,
        headers={
            "X-Router-Tier": result.tier,
            "X-Router-Model": result.response.model,
            "X-Cost-Saved": f"{result.cost_saved:.8f}",
            "X-From-Cache": str(result.from_cache).lower(),
        },
    )
