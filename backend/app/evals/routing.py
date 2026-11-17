"""
Routing eval: run the classifier over the hand-labelled prompts and report
how many land in the labelled tier, where the misses go, and what the
prompts would cost on the routed tiers against GPT-4o.

Two sets: LABELLED, which the rules were tuned on (a regression check), and
HELD_OUT, which they were not (the honest accuracy). Both are reported.

Served at GET /v1/route/eval for the demo page; `python -m app.evals.routing`
prints the same report.
"""
from ..classifier.heuristics import classify
from ..config import BASELINE_MODEL, calculate_cost
from .labelled import LABELLED, KNOWN_MISSES
from .held_out import HELD_OUT

TIERS = ("simple", "medium", "complex")


HELD_OUT_CAVEAT = ("Written and labelled on 2026-11-17 before the classifier was run on them; "
                   "the rules were not changed to fit them, so this is the accuracy to quote.")


def run_routing_eval(models: dict[str, str], labelled=LABELLED, known_misses=None) -> dict:
    """`models` maps each tier to the model it routes to (for pricing).

    `known_misses` maps an index in `labelled` to a note explaining that miss; it
    defaults to KNOWN_MISSES only for the tuning set itself.
    """
    if known_misses is None:
        known_misses = KNOWN_MISSES if labelled is LABELLED else {}
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
            "note": known_misses.get(i) if result.tier != expected else None,
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


def run_full_eval(models: dict[str, str]) -> dict:
    """The tuning-set report, with the held-out set's report under "held_out"."""
    report = run_routing_eval(models)
    held_out = run_routing_eval(models, labelled=HELD_OUT)
    held_out["caveat"] = HELD_OUT_CAVEAT
    report["held_out"] = held_out
    return report


def _print(title: str, report: dict) -> None:  # pragma: no cover
    print(f"{title}: {report['correct']}/{report['total']} routed to the labelled tier "
          f"({report['accuracy']:.0%}); {report['routed_too_low']} too low, {report['routed_too_high']} too high")
    print("labelled \\ routed  " + "  ".join(f"{t:>7}" for t in TIERS))
    for exp in TIERS:
        print(f"{exp:>17}  " + "  ".join(f"{report['confusion'][exp][t]:>7}" for t in TIERS))
    for m in report["misses"]:
        print(f"miss: {m['expected']} -> {m['routed']} (score {m['score']}): {m['prompt'][:70]}")


if __name__ == "__main__":  # pragma: no cover
    from ..router.engine import get_providers, TIER_ESCALATION

    providers = get_providers()
    report = run_full_eval({t: providers[t].model_name for t in TIER_ESCALATION})
    _print("Tuning set (regression check)", report)
    c = report["cost"]
    print(f"cost per 1k runs of the set ({c['basis']}): ${c['routed_usd_per_1k_runs']:.4f} routed "
          f"vs ${c['all_complex_usd_per_1k_runs']:.4f} all on the complex tier "
          f"vs ${c['baseline_usd_per_1k_runs']:.4f} on {c['baseline_model']}")
    print()
    _print("Held-out set (not tuned on)", report["held_out"])
