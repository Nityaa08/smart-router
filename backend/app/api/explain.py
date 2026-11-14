"""
POST /v1/route/explain: how the classifier scores a prompt, without calling any model.
GET /v1/route/eval: the classifier over the hand-labelled prompts.

The demo page uses it to show which rules fired, and the same numbers can be
used to check routing decisions offline.
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..classifier.heuristics import classify
from ..config import get_settings, calculate_cost, BASELINE_MODEL, MODEL_PRICING
from ..router.engine import get_providers, TIER_ESCALATION
from ..evals.routing import run_routing_eval
from ..security import limiter, rate_limit, require_api_key
from .chat import prompt_too_long
from ..schemas.request import Message

router = APIRouter(dependencies=[Depends(require_api_key)])

THRESHOLDS = {"simple": "score 0-1", "medium": "score 2-3", "complex": "score 4 or more"}


def list_price(model: str) -> dict[str, float]:
    """USD per 1M input/output tokens, priced the same way as calculate_cost."""
    if model.endswith(":free"):
        return {"input": 0.0, "output": 0.0}
    return dict(MODEL_PRICING.get(model, MODEL_PRICING[BASELINE_MODEL]))


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
                "price_per_1m_tokens_usd": list_price(providers[t].model_name),
            }
            for t in TIER_ESCALATION
        ],
        "baseline": {
            "model": BASELINE_MODEL,
            "input_cost_per_1k_prompts_usd": round(calculate_cost(BASELINE_MODEL, tokens, 0) * 1000, 6),
            "price_per_1m_tokens_usd": list_price(BASELINE_MODEL),
        },
    }


@router.get("/v1/route/eval")
@limiter.limit(rate_limit)
async def routing_eval(request: Request):
    """The classifier over the hand-labelled prompts: accuracy, confusion matrix, misses, cost."""
    providers = get_providers()
    return run_routing_eval({t: providers[t].model_name for t in TIER_ESCALATION})
