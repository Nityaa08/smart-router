"""
POST /v1/route/explain: how the classifier scores a prompt, without calling any model.

The demo page uses it to show which rules fired, and the same numbers can be
used to check routing decisions offline.
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..classifier.heuristics import classify
from ..config import get_settings, calculate_cost, BASELINE_MODEL
from ..router.engine import get_providers, TIER_ESCALATION
from ..security import limiter, rate_limit, require_api_key
from .chat import prompt_too_long
from ..schemas.request import Message

router = APIRouter(dependencies=[Depends(require_api_key)])

THRESHOLDS = {"simple": "score 0-1", "medium": "score 2-3", "complex": "score 4 or more"}


class ExplainRequest(BaseModel):
    messages: list[Message]


@router.post("/v1/route/explain")
@limiter.limit(rate_limit)
async def explain(body: ExplainRequest, request: Request):
    messages = [m.model_dump() for m in body.messages]
    if (too_long := prompt_too_long(messages)) is not None:
        return too_long
    result = classify(messages)
    providers = get_providers()
    tokens = result.token_estimate
    return {
        "tier": result.tier,
        "score": result.score,
        "confidence": result.confidence,
        "token_estimate": tokens,
        "signals": [s.__dict__ for s in result.signals],
        "thresholds": THRESHOLDS,
        "provider": get_settings().provider,
        "tiers": [
            {
                "tier": t,
                "model": providers[t].model_name,
                # Price of the prompt tokens alone, to compare tiers before any answer exists.
                "input_cost_per_1k_prompts_usd": round(calculate_cost(providers[t].model_name, tokens, 0) * 1000, 6),
            }
            for t in TIER_ESCALATION
        ],
        "baseline": {
            "model": BASELINE_MODEL,
            "input_cost_per_1k_prompts_usd": round(calculate_cost(BASELINE_MODEL, tokens, 0) * 1000, 6),
        },
    }
