"""The routing eval: the report over the hand-labelled prompts and GET /v1/route/eval."""
import pytest
from fastapi.testclient import TestClient

from app.evals.labelled import LABELLED, KNOWN_MISSES
from app.evals.routing import run_routing_eval, TIERS
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
