"""The routing eval: the report over the hand-labelled prompts (tuning and held-out) and GET /v1/route/eval."""
import pytest
from fastapi.testclient import TestClient

from app.evals.labelled import LABELLED, KNOWN_MISSES
from app.evals.held_out import HELD_OUT
from app.evals.routing import run_routing_eval, run_full_eval, TIERS
from app.main import app
from app.config import get_settings
from app.router import engine
from app.security import limiter

MODELS = {"simple": "openai/gpt-oss-20b", "medium": "openai/gpt-oss-120b", "complex": "openai/gpt-oss-120b"}


@pytest.fixture(scope="module")
def report():
    return run_routing_eval(MODELS)


def test_labelled_set_is_balanced():
    assert len(LABELLED) == 24
    for tier in TIERS:
        assert sum(exp == tier for exp, _ in LABELLED) == 8


def test_counts_and_confusion_matrix_agree(report):
    assert report["total"] == 24
    assert sum(sum(row.values()) for row in report["confusion"].values()) == 24
    assert report["correct"] == sum(report["confusion"][t][t] for t in TIERS)
    assert report["correct"] + len(report["misses"]) == 24
    assert report["routed_too_low"] + report["routed_too_high"] == len(report["misses"])


def test_current_result_is_23_of_24_with_the_known_miss(report):
    assert report["correct"] == 23
    assert report["accuracy"] == pytest.approx(23 / 24, abs=1e-4)
    [miss] = report["misses"]
    assert (miss["expected"], miss["routed"]) == ("medium", "simple")
    assert miss["note"] == KNOWN_MISSES[15]
    assert report["routed_too_low"] == 1 and report["routed_too_high"] == 0


def test_routing_costs_less_than_sending_everything_to_the_top_tier(report):
    c = report["cost"]
    assert 0 < c["routed_usd_per_1k_runs"] < c["all_complex_usd_per_1k_runs"] < c["baseline_usd_per_1k_runs"]


def test_a_tier_mix_up_is_counted_in_the_right_cell():
    r = run_routing_eval(MODELS, labelled=[("complex", "What is 2+2?")])
    assert r["confusion"]["complex"]["simple"] == 1
    assert r["correct"] == 0 and r["routed_too_low"] == 1
    assert r["misses"][0]["note"] is None  # not a documented miss


def test_endpoint_serves_the_report(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "provider", "demo")
    monkeypatch.setattr(cfg, "router_api_key", "")
    monkeypatch.setattr(cfg, "rate_limit", "1000/minute")
    monkeypatch.setattr(engine, "_providers", None)
    limiter.reset()
    body = TestClient(app).get("/v1/route/eval").json()
    assert body["correct"] == 23 and body["total"] == 24
    assert set(body["confusion"]) == set(TIERS)
    assert "not a held-out" in body["caveat"]
    held = body["held_out"]
    assert held["correct"] == 10 and held["total"] == 24
    assert "not changed to fit them" in held["caveat"]


# ── held-out set: prompts the rules were not tuned on ────────────────────────

@pytest.fixture(scope="module")
def held_out():
    return run_full_eval(MODELS)["held_out"]


def test_held_out_set_is_balanced_and_separate_from_the_tuning_set():
    assert len(HELD_OUT) == 24
    for tier in TIERS:
        assert sum(exp == tier for exp, _ in HELD_OUT) == 8
    tuned = {p.lower() for _, p in LABELLED}
    assert not tuned & {p.lower() for _, p in HELD_OUT}


def test_held_out_result_is_10_of_24_and_every_miss_routes_too_low(held_out):
    # Recorded on 2026-11-17, the first time the classifier saw these prompts.
    # If a rule change moves this number, update it here and in the README;
    # never edit or relabel a held-out prompt to make it go up.
    assert held_out["correct"] == 10
    assert held_out["accuracy"] == pytest.approx(10 / 24, abs=1e-4)
    assert held_out["routed_too_low"] == 14 and held_out["routed_too_high"] == 0
    c = held_out["confusion"]
    assert c["simple"] == {"simple": 8, "medium": 0, "complex": 0}
    assert c["medium"] == {"simple": 8, "medium": 0, "complex": 0}
    assert c["complex"] == {"simple": 4, "medium": 2, "complex": 2}


def test_held_out_misses_carry_no_tuning_set_notes(held_out):
    # KNOWN_MISSES indexes the tuning set; it must not label held-out rows.
    assert all(m["note"] is None for m in held_out["misses"])


def test_the_tuning_set_report_is_unchanged_by_the_held_out_set():
    full = run_full_eval(MODELS)
    alone = run_routing_eval(MODELS)
    assert {k: v for k, v in full.items() if k != "held_out"} == alone
