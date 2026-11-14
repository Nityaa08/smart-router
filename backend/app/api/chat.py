import time
import uuid
import json
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..schemas.request import ChatRequest
from ..router.engine import route, route_stream, log_stream
from ..security import limiter, rate_limit, require_api_key
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_api_key)])


def _get_redis(request: Request):
    return getattr(request.app.state, "redis", None)


def _err(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": detail, "type": "router_error"}})


def prompt_too_long(messages: list[dict]) -> JSONResponse | None:
    """MAX_PROMPT_CHARS guard for public deployments (0 = no limit)."""
    limit = get_settings().max_prompt_chars
    if limit > 0:
        size = sum(len(str(m.get("content", ""))) for m in messages)
        if size > limit:
            return _err(413, f"Prompt is {size} characters; this deployment accepts at most {limit}.")
    return None


@router.post("/v1/chat/completions")
@limiter.limit(rate_limit)
async def chat_completions(body: ChatRequest, request: Request):
    messages = [m.model_dump() for m in body.messages]
    if (too_long := prompt_too_long(messages)) is not None:
        return too_long
    redis = _get_redis(request)

    # ── Streaming ─────────────────────────────────────────────────────────────
    if body.stream:
        start = time.monotonic()
        try:
            # route_stream pulls the first chunk before any headers are sent, falling back
            # to the next tier if a provider is down; only if every tier fails is it a 503.
            opened = await route_stream(
                messages,
                force_tier=body.force_tier,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            )
        except Exception as e:
            logger.warning("Streaming provider failed: %s", e)
            return _err(503, str(e) or e.__class__.__name__)

        first_chunk, stream_iter, tier, model = opened.first_chunk, opened.rest, opened.tier, opened.model
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

        def _chunk(delta: dict, finish_reason: str | None = None) -> str:
            data = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"delta": delta, "index": 0, "finish_reason": finish_reason}],
            }
            return f"data: {json.dumps(data)}\n\n"

        async def sse_generator():
            parts: list[str] = []
            completed = False
            try:
                try:
                    if first_chunk is not None:
                        parts.append(first_chunk)
                        yield _chunk({"role": "assistant", "content": first_chunk})
                    async for chunk in stream_iter:
                        parts.append(chunk)
                        yield _chunk({"content": chunk})
                    completed = True
                    yield _chunk({}, finish_reason="stop")
                except Exception as e:
                    # Headers are already sent; report the error in-band.
                    logger.warning("Stream interrupted: %s", e)
                    err = {"error": {"message": str(e) or e.__class__.__name__, "type": "router_error"}}
                    yield f"data: {json.dumps(err)}\n\n"
            finally:
                # Runs on success, provider error and client disconnect alike.
                latency_ms = int((time.monotonic() - start) * 1000)
                log_stream(opened, messages, "".join(parts), latency_ms, completed)
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "X-Router-Tier": tier,
                "X-Router-Model": model,
                "X-Router-Fallback": "true" if opened.fell_back else "false",
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
