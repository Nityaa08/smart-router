"""
Routing eval: run the classifier over the hand-labelled prompts and report
how many land in the labelled tier, where the misses go, and what the
prompts would cost on the routed tiers against GPT-4o.

Served at GET /v1/route/eval for the demo page; `python -m app.evals.routing`
prints the same report.
"""
from ..classifier.heuristics import classify
from ..config import BASELINE_MODEL, calculate_cost
from .labelled import LABELLED, KNOWN_MISSES

TIERS = ("simple", "medium", "complex")


def run_routing_eval(models: dict[str, str], labelled=LABELLED) -> dict:
    """`models` maps each tier to the model it routes to (for pricing)."""
    confusion = {exp: {got: 0 for got in TIERS} for exp in TIERS}
    rows = []
    routed_cost = top_tier_cost = baseline_cost = 0.0
    for i, (expected, prompt) in enumerate(labelled):
        result = classify([{"role": "user", "content": prompt}])
        confusion[expected][result.tier] += 1
        routed_cost += calculate_cost(models[result.tier], result.token_estimate, 0)
        top_tier_cost += calculate_cost(models["complex"], result.token_estimate, 0)
        baseline_cost += calculate_cost(BASELINE_MODEL, result.token_estimate, 0)
        rows.append({
            "prompt": prompt,
            "expected": expected,
            "routed": result.tier,
            "score": result.score,
            "correct": result.tier == expected,
            "note": KNOWN_MISSES.get(i) if result.tier != expected else None,
        })
    correct = sum(r["correct"] for r in rows)
    return {
        "total": len(rows),
        "correct": correct,
        "accuracy": round(correct / len(rows), 4) if rows else 0.0,
        # Routing up costs money; routing down risks a weak answer. Count both.
        "routed_too_low": sum(TIERS.index(r["routed"]) < TIERS.index(r["expected"]) for r in rows),
        "routed_too_high": sum(TIERS.index(r["routed"]) > TIERS.index(r["expected"]) for r in rows),
        "confusion": confusion,
        "misses": [r for r in rows if not r["correct"]],
        "rows": rows,
        "cost": {
            "basis": "prompt (input) tokens only, at list prices",
            "routed_usd_per_1k_runs": round(routed_cost * 1000, 6),
            # What routing itself saves: the same set with every prompt on the top tier.
            "all_complex_usd_per_1k_runs": round(top_tier_cost * 1000, 6),
            "baseline_model": BASELINE_MODEL,
            "baseline_usd_per_1k_runs": round(baseline_cost * 1000, 6),
        },
        "caveat": "The rules were tuned with these prompts in view, so this is a regression check, not a held-out accuracy.",
    }


if __name__ == "__main__":  # pragma: no cover
    from ..router.engine import get_providers, TIER_ESCALATION

    providers = get_providers()
    report = run_routing_eval({t: providers[t].model_name for t in TIER_ESCALATION})
    print(f"{report['correct']}/{report['total']} routed to the labelled tier ({report['accuracy']:.0%})")
    print("labelled \\ routed  " + "  ".join(f"{t:>7}" for t in TIERS))
    for exp in TIERS:
        print(f"{exp:>17}  " + "  ".join(f"{report['confusion'][exp][t]:>7}" for t in TIERS))
    for m in report["misses"]:
        print(f"miss: {m['expected']} -> {m['routed']} (score {m['score']}): {m['prompt'][:70]}")
    c = report["cost"]
    print(f"cost per 1k runs of the set ({c['basis']}): ${c['routed_usd_per_1k_runs']:.4f} routed "
          f"vs ${c['all_complex_usd_per_1k_runs']:.4f} all on the complex tier "
          f"vs ${c['baseline_usd_per_1k_runs']:.4f} on {c['baseline_model']}")
