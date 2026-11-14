"""
Tests for the public-demo pieces: the demo provider, the in-memory request log
and /analytics without a database, /v1/route/explain, the prompt-size and
max-token guards, rate limiting by proxy header, and the demo pages.
No database, Redis or LLM required.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import database
from app.classifier.heuristics import classify
from app.config import get_settings, calculate_cost, BASELINE_MODEL
from app.main import app
from app.providers.demo import DemoProvider, DEMO_LABEL, DEMO_OUTPUT_TOKENS
from app.router import engine, memlog
from app.security import limiter


@pytest.fixture
def demo(monkeypatch):
    """Demo provider, no database (memory log), no Redis, generous rate limit."""
    cfg = get_settings()
    monkeypatch.setattr(cfg, "provider", "demo")
    monkeypatch.setattr(cfg, "router_api_key", "")
    monkeypatch.setattr(cfg, "rate_limit", "1000/minute")
    monkeypatch.setattr(engine, "_providers", None)  # rebuilt from PROVIDER=demo
    monkeypatch.setattr(database, "AsyncSessionLocal", None)
    monkeypatch.setattr(database, "engine", None)
    memlog.clear()
    limiter.reset()
    app.state.redis = None
    yield cfg
    memlog.clear()
    limiter.reset()


@pytest.fixture
def client(demo):
    return TestClient(app)


def _body(content):
    return {"messages": [{"role": "user", "content": content}]}


def _drain_logs():
    # Request logs are written by background tasks; let them finish.
    async def wait():
        while engine._log_tasks:
            await asyncio.sleep(0)
    if engine._log_tasks:
        asyncio.get_event_loop().run_until_complete(wait())


class TestDemoProvider:
    def test_answer_is_labelled_simulated_and_priced_like_the_model(self):
        p = DemoProvider("openai/gpt-oss-20b", "simple")
        r = asyncio.run(p.complete([{"role": "user", "content": "x" * 400}]))
        assert r.content.startswith(DEMO_LABEL)
        assert r.usage.input_tokens == 100
        assert r.usage.output_tokens == DEMO_OUTPUT_TOKENS["simple"]
        assert p.provider_name == "demo"

    def test_max_tokens_caps_estimated_output(self):
        p = DemoProvider("m", "complex")
        r = asyncio.run(p.complete([{"role": "user", "content": "hi"}], max_tokens=50))
        assert r.usage.output_tokens == 50

    def test_stream_yields_the_same_text(self):
        p = DemoProvider("m", "medium")
        msgs = [{"role": "user", "content": "Explain DNS"}]

        async def collect():
            return "".join([c async for c in p.stream(msgs)]).strip()

        assert asyncio.run(collect()) == asyncio.run(p.complete(msgs)).content


class TestDemoEndToEnd:
    def test_chat_works_without_key_database_or_redis(self, client):
        r = client.post("/v1/chat/completions", json=_body("What is 2+2?"))
        assert r.status_code == 200
        body = r.json()
        assert body["router"]["provider"] == "demo"
        assert body["router"]["tier"] == "simple"
        assert body["choices"][0]["message"]["content"].startswith(DEMO_LABEL)
        # Priced at the model's list price, compared with GPT-4o for the same tokens.
        assert body["router"]["cost_saved_usd"] > 0

    def test_requests_are_logged_in_memory_and_summarised_by_analytics(self, client):
        client.post("/v1/chat/completions", json=_body("What is 2+2?"))
        client.post("/v1/chat/completions", json=_body(
            "Implement a red-black tree. First design it, then prove the complexity of insert."))
        _drain_logs()
        a = client.get("/analytics").json()
        assert a["total_requests"] == 2
        assert set(a["by_tier"]) == {"simple", "complex"}
        assert a["baseline_cost_usd"] > a["actual_cost_usd"] > 0
        assert a["cache_hits"] == 0

    def test_streamed_requests_appear_in_analytics(self, client):
        r = client.post("/v1/chat/completions", json={**_body("What is 2+2?"), "stream": True})
        assert r.status_code == 200 and r.text.rstrip().endswith("data: [DONE]")
        _drain_logs()
        a = client.get("/analytics").json()
        assert a["total_requests"] == 1
        assert a["by_tier"]["simple"]["count"] == 1
        assert a["baseline_cost_usd"] > a["actual_cost_usd"] > 0

    def test_health_reports_memory_log(self, client):
        h = client.get("/health").json()
        assert h["status"] == "ok"
        assert h["provider_name"] == "demo"
        assert h["db"].startswith("not configured")


class TestMemlog:
    def test_summary_matches_rows(self):
        memlog.clear()
        memlog.append({"tier": "simple", "actual_cost": 1.0, "baseline_cost": 4.0, "cost_saved": 3.0,
                       "latency_ms": 10, "status": "success"})
        memlog.append({"tier": "simple", "actual_cost": 0.0, "baseline_cost": 4.0, "cost_saved": 4.0,
                       "latency_ms": 0, "status": "cache_hit"})
        s = memlog.summarize("cache_hit")
        assert s["total_requests"] == 2
        assert s["savings_pct"] == 87.5
        assert s["cache_hits"] == 1
        assert s["avg_latency_ms"] == 10.0  # cache hits excluded
        memlog.clear()


class TestExplain:
    def test_lists_the_rules_that_fired(self, client):
        r = client.post("/v1/route/explain", json=_body("What is DNS?"))
        assert r.status_code == 200
        x = r.json()
        assert x["tier"] == "simple"
        assert x["score"] == max(0, sum(s["points"] for s in x["signals"]))
        simple = [s for s in x["signals"] if s["name"] == "simple keywords"]
        assert simple and simple[0]["points"] < 0  # simple keywords pull the score down
        assert [t["tier"] for t in x["tiers"]] == ["simple", "medium", "complex"]
        assert x["baseline"]["model"] == BASELINE_MODEL

    def test_signals_sum_to_score_for_many_prompts(self):
        prompts = [
            "hi", "What is 2+2?", "Explain and compare TCP and UDP",
            "Implement quicksort. First write it, then derive its complexity.\n```py\ndef f(): pass\n```",
            "word " * 3000,
        ]
        for p in prompts:
            r = classify([{"role": "user", "content": p}])
            assert r.score == max(0, sum(s.points for s in r.signals)), p


class TestGuards:
    def test_prompt_over_max_prompt_chars_is_413(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "max_prompt_chars", 10)
        assert client.post("/v1/chat/completions", json=_body("x" * 11)).status_code == 413
        assert client.post("/v1/route/explain", json=_body("x" * 11)).status_code == 413
        assert client.post("/v1/chat/completions", json=_body("x" * 10)).status_code == 200

    def test_max_completion_tokens_caps_requests(self, monkeypatch):
        cfg = get_settings()
        monkeypatch.setattr(cfg, "max_completion_tokens", 256)
        assert engine.cap_max_tokens(None) == 256
        assert engine.cap_max_tokens(1000) == 256
        assert engine.cap_max_tokens(100) == 100
        monkeypatch.setattr(cfg, "max_completion_tokens", 0)
        assert engine.cap_max_tokens(None) is None

    def test_rate_limit_uses_proxy_ip_when_trusted(self, client, monkeypatch):
        cfg = get_settings()
        monkeypatch.setattr(cfg, "rate_limit", "2/minute")
        monkeypatch.setattr(cfg, "trust_proxy_headers", True)
        limiter.reset()
        a = {"x-real-ip": "203.0.113.1"}
        b = {"x-real-ip": "203.0.113.2"}
        assert client.post("/v1/route/explain", json=_body("hi"), headers=a).status_code == 200
        assert client.post("/v1/route/explain", json=_body("hi"), headers=a).status_code == 200
        assert client.post("/v1/route/explain", json=_body("hi"), headers=a).status_code == 429
        assert client.post("/v1/route/explain", json=_body("hi"), headers=b).status_code == 200


class TestPages:
    def test_playground_and_dashboard_are_served(self, client):
        home = client.get("/")
        assert home.status_code == 200 and "Route this prompt" in home.text
        dash = client.get("/dashboard")
        assert dash.status_code == 200 and "<title>Smart Router</title>" in dash.text


def test_demo_models_are_priced():
    cfg = get_settings()
    for m in (cfg.demo_simple_model, cfg.demo_medium_model, cfg.demo_complex_model):
        assert calculate_cost(m, 1000, 1000) < calculate_cost(BASELINE_MODEL, 1000, 1000)
