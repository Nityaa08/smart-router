from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from ..database import get_db
from ..models.request_log import RequestLog
from ..schemas.response import AnalyticsResponse, TierStats
from ..security import require_api_key
from ..router.engine import CACHE_HIT_STATUS

router = APIRouter(dependencies=[Depends(require_api_key)])

# Average latency over real provider calls only; cache hits (latency 0) are excluded.
_provider_latency = case((RequestLog.status != CACHE_HIT_STATUS, RequestLog.latency_ms))


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(db: AsyncSession = Depends(get_db)):
    # Aggregate totals
    totals = await db.execute(
        select(
            func.count(RequestLog.id).label("total"),
            func.coalesce(func.sum(RequestLog.actual_cost), 0).label("actual_cost"),
            func.coalesce(func.sum(RequestLog.baseline_cost), 0).label("baseline_cost"),
            func.coalesce(func.sum(RequestLog.cost_saved), 0).label("cost_saved"),
            func.coalesce(func.avg(_provider_latency), 0).label("avg_latency"),
        )
    )
    row = totals.one()
    total_requests = row.total
    actual_cost = float(row.actual_cost)
    baseline_cost = float(row.baseline_cost)
    total_saved = float(row.cost_saved)
    avg_latency = float(row.avg_latency)
    savings_pct = (total_saved / baseline_cost * 100) if baseline_cost > 0 else 0.0

    # Per-tier breakdown
    tier_rows = await db.execute(
        select(
            RequestLog.difficulty,
            func.count(RequestLog.id).label("count"),
            func.coalesce(func.sum(RequestLog.actual_cost), 0).label("actual_cost"),
            func.coalesce(func.sum(RequestLog.baseline_cost), 0).label("baseline_cost"),
            func.coalesce(func.sum(RequestLog.cost_saved), 0).label("cost_saved"),
            func.coalesce(func.avg(_provider_latency), 0).label("avg_latency"),
        ).group_by(RequestLog.difficulty)
    )

    by_tier: dict[str, TierStats] = {}
    for t in tier_rows:
        by_tier[t.difficulty] = TierStats(
            count=t.count,
            actual_cost_usd=float(t.actual_cost),
            baseline_cost_usd=float(t.baseline_cost),
            cost_saved_usd=float(t.cost_saved),
            avg_latency_ms=float(t.avg_latency),
        )

    # Cache hits are logged with status "cache_hit" (see router/engine.py)
    cache_result = await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.status == CACHE_HIT_STATUS)
    )
    cache_hits = cache_result.scalar() or 0

    return AnalyticsResponse(
        total_requests=total_requests,
        actual_cost_usd=actual_cost,
        baseline_cost_usd=baseline_cost,
        total_saved_usd=total_saved,
        savings_pct=round(savings_pct, 2),
        by_tier=by_tier,
        avg_latency_ms=avg_latency,
        cache_hits=cache_hits,
    )
