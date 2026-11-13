"""
In-memory request log, used when no database is configured (DATABASE_URL=memory).

The public demo runs on serverless functions with no Postgres, so the log and
the /analytics numbers belong to one running instance and reset when it is
recycled. It keeps the most recent MAX_ROWS requests.
"""
from collections import deque

MAX_ROWS = 2000

_rows: deque[dict] = deque(maxlen=MAX_ROWS)


def append(row: dict) -> None:
    _rows.append(dict(row))


def rows() -> list[dict]:
    return list(_rows)


def clear() -> None:
    _rows.clear()


def summarize(cache_hit_status: str) -> dict:
    """The same shape as the SQL aggregation in api/analytics.py."""
    data = rows()

    def agg(items: list[dict]) -> dict:
        provider_calls = [r["latency_ms"] for r in items if r.get("status") != cache_hit_status]
        return {
            "count": len(items),
            "actual_cost_usd": float(sum(r.get("actual_cost", 0.0) for r in items)),
            "baseline_cost_usd": float(sum(r.get("baseline_cost", 0.0) for r in items)),
            "cost_saved_usd": float(sum(r.get("cost_saved", 0.0) for r in items)),
            "avg_latency_ms": float(sum(provider_calls) / len(provider_calls)) if provider_calls else 0.0,
        }

    totals = agg(data)
    by_tier: dict[str, dict] = {}
    for tier in sorted({r["tier"] for r in data}):
        by_tier[tier] = agg([r for r in data if r["tier"] == tier])

    baseline = totals["baseline_cost_usd"]
    return {
        "total_requests": totals["count"],
        "actual_cost_usd": totals["actual_cost_usd"],
        "baseline_cost_usd": baseline,
        "total_saved_usd": totals["cost_saved_usd"],
        "savings_pct": round(totals["cost_saved_usd"] / baseline * 100, 2) if baseline > 0 else 0.0,
        "by_tier": by_tier,
        "avg_latency_ms": totals["avg_latency_ms"],
        "cache_hits": sum(1 for r in data if r.get("status") == cache_hit_status),
    }
