"""
Routing engine: classify → select provider → call LLM → log result.
"""
import asyncio
import time
import hashlib
import json
import uuid
import logging
from dataclasses import dataclass
from typing import Literal, AsyncIterator

from ..classifier.heuristics import classify, ClassifierResult
from ..providers.base import LLMProvider, LLMResponse
from ..providers.ollama import OllamaProvider
from ..providers.groq import GroqProvider
from ..providers.openai_compat import OpenAICompatProvider
from ..providers.demo import DemoProvider
from ..config import get_settings, calculate_cost, BASELINE_MODEL
from ..models.request_log import RequestLog
from .. import database
from . import memlog

logger = logging.getLogger(__name__)

Tier = Literal["simple", "medium", "complex"]


@dataclass
class RouterResult:
    response: LLMResponse
    tier: Tier
    provider_name: str
    actual_cost: float
    baseline_cost: float
    cost_saved: float
    latency_ms: int
    from_cache: bool = False
    status: str = "success"


def _make_providers() -> dict[Tier, LLMProvider]:
    """Build provider map based on config."""
    cfg = get_settings()

    if cfg.provider == "demo":
        return {
            "simple":  DemoProvider(cfg.demo_simple_model, "simple"),
            "medium":  DemoProvider(cfg.demo_medium_model, "medium"),
            "complex": DemoProvider(cfg.demo_complex_model, "complex"),
        }

    if cfg.provider == "groq":
        if not cfg.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Set it in .env or switch PROVIDER=ollama.")
        return {
            "simple":  GroqProvider(cfg.groq_api_key, cfg.groq_simple_model),
            "medium":  GroqProvider(cfg.groq_api_key, cfg.groq_medium_model),
            "complex": GroqProvider(cfg.groq_api_key, cfg.groq_complex_model),
        }

    if cfg.provider == "openrouter":
        if not cfg.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Get a free key at openrouter.ai")
        base = "https://openrouter.ai/api/v1"
        return {
            "simple":  OpenAICompatProvider(base, cfg.openrouter_api_key, cfg.openrouter_simple_model, "openrouter"),
            "medium":  OpenAICompatProvider(base, cfg.openrouter_api_key, cfg.openrouter_medium_model, "openrouter"),
            "complex": OpenAICompatProvider(base, cfg.openrouter_api_key, cfg.openrouter_complex_model, "openrouter"),
        }

    if cfg.provider == "openai_compat":
        if not cfg.openai_compat_base_url or not cfg.openai_compat_api_key:
            raise RuntimeError("OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_API_KEY must be set.")
        base = cfg.openai_compat_base_url
        key = cfg.openai_compat_api_key
        return {
            "simple":  OpenAICompatProvider(base, key, cfg.openai_compat_simple_model, "openai_compat"),
            "medium":  OpenAICompatProvider(base, key, cfg.openai_compat_medium_model, "openai_compat"),
            "complex": OpenAICompatProvider(base, key, cfg.openai_compat_complex_model, "openai_compat"),
        }

    # Default: Ollama
    return {
        "simple":  OllamaProvider(cfg.ollama_base_url, cfg.ollama_simple_model),
        "medium":  OllamaProvider(cfg.ollama_base_url, cfg.ollama_medium_model),
        "complex": OllamaProvider(cfg.ollama_base_url, cfg.ollama_complex_model),
    }


# Module-level provider map, lazy-initialized
_providers: dict[Tier, LLMProvider] | None = None

TIER_ESCALATION: list[Tier] = ["simple", "medium", "complex"]


def get_providers() -> dict[Tier, LLMProvider]:
    global _providers
    if _providers is None:
        _providers = _make_providers()
    return _providers


def prompt_hash(messages: list[dict]) -> str:
    text = json.dumps(messages, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


async def _log_request(
    tier: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    actual_cost: float,
    baseline_cost: float,
    cost_saved: float,
    latency_ms: int,
    status: str,
    phash: str,
) -> None:
    if database.AsyncSessionLocal is None:
        # No database configured (e.g. the serverless demo): keep the row in memory.
        memlog.append({
            "tier": tier, "model": model, "provider": provider,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "actual_cost": actual_cost, "baseline_cost": baseline_cost, "cost_saved": cost_saved,
            "latency_ms": latency_ms, "status": status, "prompt_hash": phash,
        })
        return
    async with database.AsyncSessionLocal() as session:
        log = RequestLog(
            id=uuid.uuid4(),
            difficulty=tier,
            model_used=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_cost=actual_cost,
            baseline_cost=baseline_cost,
            cost_saved=cost_saved,
            latency_ms=latency_ms,
            status=status,
            prompt_hash=phash,
        )
        session.add(log)
        await session.commit()


CACHE_HIT_STATUS = "cache_hit"


def cap_max_tokens(max_tokens: int | None) -> int | None:
    """Apply MAX_COMPLETION_TOKENS (if set) so a public deployment can't ask for huge answers."""
    cap = get_settings().max_completion_tokens
    if cap <= 0:
        return max_tokens
    return min(max_tokens, cap) if max_tokens else cap

# Keep references so fire-and-forget log tasks are not garbage-collected.
_log_tasks: set[asyncio.Task] = set()


def _schedule_log(**kwargs) -> None:
    """Write the request log in the background without blocking the response."""
    task = asyncio.create_task(_log_request(**kwargs))
    _log_tasks.add(task)
    task.add_done_callback(_on_log_done)


def _on_log_done(task: asyncio.Task) -> None:
    _log_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Failed to write request log: %s", task.exception())


async def route(
    messages: list[dict],
    force_tier: Tier | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    redis_client=None,
) -> RouterResult:
    """
    Main routing function.
    1. Check Redis cache.
    2. Classify prompt.
    3. Try primary provider, escalate on failure.
    4. Calculate costs and log to DB.
    """
    providers = get_providers()
    max_tokens = cap_max_tokens(max_tokens)
    phash = prompt_hash(messages)
    # A forced tier gets its own cache entry, so it is never answered by another tier's cached reply.
    cache_key = f"sr:resp:{phash}" + (f":{force_tier}" if force_tier else "")

    # ── Cache check ──────────────────────────────────────────────────────────
    if redis_client:
        cached = await redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            logger.info("Cache hit for hash %s", phash[:8])
            # Return a minimal RouterResult from cache
            from ..providers.base import LLMResponse, LLMUsage
            resp = LLMResponse(
                content=data["content"],
                model=data["model"],
                usage=LLMUsage(
                    input_tokens=data["input_tokens"],
                    output_tokens=data["output_tokens"],
                ),
                raw={},
            )
            # A cache hit makes no provider call: it costs nothing, and the
            # whole GPT-4o baseline for those tokens counts as saved.
            baseline_cost = data["baseline_cost"]
            _schedule_log(
                tier=data["tier"],
                model=data["model"],
                provider=data["provider"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                actual_cost=0.0,
                baseline_cost=baseline_cost,
                cost_saved=baseline_cost,
                latency_ms=0,
                status=CACHE_HIT_STATUS,
                phash=phash,
            )
            return RouterResult(
                response=resp,
                tier=data["tier"],
                provider_name=data["provider"],
                actual_cost=0.0,
                baseline_cost=baseline_cost,
                cost_saved=baseline_cost,
                latency_ms=0,
                from_cache=True,
                status=CACHE_HIT_STATUS,
            )

    # ── Classify ─────────────────────────────────────────────────────────────
    classification = classify(messages)
    tier: Tier = force_tier or classification.tier
    logger.info("Classified as %s (score=%d, confidence=%.2f)", tier, classification.score, classification.confidence)

    # ── Route with fallback ──────────────────────────────────────────────────
    start = time.monotonic()
    response: LLMResponse | None = None
    used_tier = tier
    status = "success"

    tiers_to_try = TIER_ESCALATION[TIER_ESCALATION.index(tier):]
    for attempt_tier in tiers_to_try:
        try:
            provider = providers[attempt_tier]
            response = await provider.complete(messages, temperature=temperature, max_tokens=max_tokens)
            used_tier = attempt_tier
            if attempt_tier != tier:
                status = "fallback"
                logger.warning("Fell back from %s to %s", tier, attempt_tier)
            break
        except Exception as exc:
            logger.warning("Provider %s/%s failed: %s", attempt_tier, providers[attempt_tier].model_name, exc)

    if response is None:
        raise RuntimeError("All providers failed. Check Ollama is running or GROQ_API_KEY is valid.")

    latency_ms = int((time.monotonic() - start) * 1000)
    provider_obj = providers[used_tier]

    # ── Cost calculation ─────────────────────────────────────────────────────
    actual_cost = calculate_cost(provider_obj.model_name, response.usage.input_tokens, response.usage.output_tokens)
    baseline_cost = calculate_cost(BASELINE_MODEL, response.usage.input_tokens, response.usage.output_tokens)
    cost_saved = max(0.0, baseline_cost - actual_cost)

    # ── Async DB log (don't block response) ─────────────────────────────────
    # Log the tier whose model answered (as cache hits do), so /analytics puts
    # each request's cost under the tier that actually ran it.
    _schedule_log(
        tier=used_tier,
        model=provider_obj.model_name,
        provider=provider_obj.provider_name,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        actual_cost=actual_cost,
        baseline_cost=baseline_cost,
        cost_saved=cost_saved,
        latency_ms=latency_ms,
        status=status,
        phash=phash,
    )

    # ── Cache store ──────────────────────────────────────────────────────────
    if redis_client:
        cache_data = json.dumps({
            "content": response.content,
            "model": provider_obj.model_name,
            "tier": used_tier,
            "provider": provider_obj.provider_name,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "actual_cost": actual_cost,
            "baseline_cost": baseline_cost,
            "cost_saved": cost_saved,
        })
        await redis_client.setex(cache_key, 3600, cache_data)

    return RouterResult(
        response=response,
        tier=used_tier,
        provider_name=provider_obj.provider_name,
        actual_cost=actual_cost,
        baseline_cost=baseline_cost,
        cost_saved=cost_saved,
        latency_ms=latency_ms,
        from_cache=False,
        status=status,
    )


@dataclass
class OpenStream:
    """A stream whose provider has already produced its first chunk."""
    first_chunk: str | None
    rest: AsyncIterator[str]
    tier: Tier            # the tier that is actually answering
    requested_tier: Tier  # the tier the classifier (or force_tier) picked
    model: str

    @property
    def fell_back(self) -> bool:
        return self.tier != self.requested_tier


async def route_stream(
    messages: list[dict],
    force_tier: Tier | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> OpenStream:
    """
    Opens a stream with the same tier fallback as route(): if a provider fails before
    sending its first chunk, the next tier up is tried. Pulling the first chunk here means
    a provider that is down is detected before any response headers go out.
    Raises RuntimeError if every tier fails.
    """
    providers = get_providers()
    max_tokens = cap_max_tokens(max_tokens)
    classification = classify(messages)
    tier: Tier = force_tier or classification.tier

    errors: list[str] = []
    for attempt_tier in TIER_ESCALATION[TIER_ESCALATION.index(tier):]:
        provider = providers[attempt_tier]
        try:
            it = provider.stream(messages, temperature=temperature, max_tokens=max_tokens)
            first = await anext(it, None)
        except Exception as exc:
            logger.warning("Streaming provider %s/%s failed: %s", attempt_tier, provider.model_name, exc)
            errors.append(f"{attempt_tier}: {exc or exc.__class__.__name__}")
            continue
        if attempt_tier != tier:
            logger.warning("Stream fell back from %s to %s", tier, attempt_tier)
        return OpenStream(first, it, attempt_tier, tier, provider.model_name)

    raise RuntimeError("All providers failed for the stream (" + "; ".join(errors) + ")")
