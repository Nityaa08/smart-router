from pydantic import BaseModel
from typing import Any


class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, int]
    # Router metadata
    router_tier: str
    router_model: str
    cost_saved_usd: float
    from_cache: bool = False


class TierStats(BaseModel):
    count: int
    actual_cost_usd: float
    baseline_cost_usd: float
    cost_saved_usd: float
    avg_latency_ms: float


class AnalyticsResponse(BaseModel):
    total_requests: int
    actual_cost_usd: float
    baseline_cost_usd: float
    total_saved_usd: float
    savings_pct: float
    by_tier: dict[str, TierStats]
    avg_latency_ms: float
    cache_hits: int
