"""
API tests for /v1/chat/completions with fake providers.
No database, Redis or LLM required: providers, the request logger and Redis
are replaced with in-memory fakes.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.providers.base import LLMProvider, LLMResponse, LLMUsage
from app.router import engine
from app.security import limiter


class FakeProvider(LLMProvider):
    def __init__(self, model: str, fail: bool = False, chunks=("Hello", " world")):
        self._model = model
        self.fail = fail
        self.chunks = chunks
        self.calls = 0

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "fake"

    async def complete(self, messages, temperature=0.7, max_tokens=None):
        self.calls += 1
        if self.fail:
            raise ConnectionError("provider down")
        return LLMResponse(
            content=f"answer from {self._model}",
            model=self._model,
            usage=LLMUsage(input_tokens=50, output_tokens=200),
            raw={},
        )

    async def stream(self, messages, temperature=0.7, max_tokens=None):
        if self.fail:
            raise ConnectionError("provider down")
        for c in self.chunks:
            yield c

    async def health_check(self) -> bool:
        return not self.fail


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value


@pytest.fixture
def logged(monkeypatch):
    """Capture request-log rows instead of writing to Postgres."""
    rows: list[dict] = []

    async def fake_log(**kwargs):
        rows.append(kwargs)

    monkeypatch.setattr(engine, "_log_request", fake_log)
    return rows


@pytest.fixture
def providers(monkeypatch):
    p = {
        "simple": FakeProvider("small-model"),
        "medium": FakeProvider("mid-model"),
        "complex": FakeProvider("big-model"),
    }
    monkeypatch.setattr(engine, "_providers", p)
    return p


@pytest.fixture
def settings(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "router_api_key", "")
    monkeypatch.setattr(cfg, "rate_limit", "1000/minute")
    limiter.reset()
    yield cfg
    limiter.reset()


@pytest.fixture
def client(settings, providers, logged):
    app.state.redis = None
    yield TestClient(app)
    app.state.redis = None


def chat(client, content="What is 2+2?", headers=None, **extra):
    body = {"messages": [{"role": "user", "content": content}], **extra}
    return client.post("/v1/chat/completions", json=body, headers=headers or {})


# ─── Non-streaming ────────────────────────────────────────────────────────────

class TestChat:
    def test_simple_prompt_routes_to_simple_tier(self, client, logged):
        r = chat(client)
        assert r.status_code == 200
        assert r.headers["x-router-tier"] == "simple"
        assert r.headers["x-router-model"] == "small-model"
        assert r.json()["router"]["from_cache"] is False
        assert r.json()["choices"][0]["message"]["content"] == "answer from small-model"

    def test_fallback_escalates_to_next_tier(self, client, providers):
        providers["simple"].fail = True
        r = chat(client)
        assert r.status_code == 200
        assert r.headers["x-router-tier"] == "medium"

    def test_all_providers_down_returns_503(self, client, providers):
        for p in providers.values():
            p.fail = True
        r = chat(client)
        assert r.status_code == 503


class TestLoggedTier:
    """/analytics groups cost by the logged tier, so it must be the tier whose model answered."""

    def test_forced_tier_is_logged(self, client, logged):
        r = chat(client, force_tier="complex")
        assert r.headers["x-router-tier"] == "complex"
        assert [(row["tier"], row["model"]) for row in logged] == [("complex", "big-model")]

    def test_fallback_is_logged_under_the_tier_that_answered(self, client, providers, logged):
        providers["simple"].fail = True
        chat(client)
        assert [(row["tier"], row["model"], row["status"]) for row in logged] == [("medium", "mid-model", "fallback")]


# ─── Streaming ────────────────────────────────────────────────────────────────

def _sse_events(text: str) -> list:
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            payload = line[6:]
            out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


class TestStreaming:
    def test_stream_returns_chunks(self, client):
        r = chat(client, stream=True)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _sse_events(r.text)
        assert events[-1] == "[DONE]"
        text = "".join(
            e["choices"][0]["delta"].get("content", "") for e in events[:-1]
        )
        assert text == "Hello world"
        assert events[-2]["choices"][0]["finish_reason"] == "stop"

    def test_stream_falls_back_to_next_tier(self, client, providers):
        providers["simple"].fail = True
        r = chat(client, stream=True)
        assert r.status_code == 200
        assert r.headers["x-router-tier"] == "medium"
        assert r.headers["x-router-model"] == "mid-model"
        assert r.headers["x-router-fallback"] == "true"
        events = _sse_events(r.text)
        assert "".join(e["choices"][0]["delta"].get("content", "") for e in events[:-1]) == "Hello world"

    def test_stream_without_fallback_says_so(self, client):
        r = chat(client, stream=True)
        assert r.headers["x-router-tier"] == "simple"
        assert r.headers["x-router-fallback"] == "false"

    def test_stream_all_providers_down_returns_503(self, client, providers):
        for p in providers.values():
            p.fail = True
        r = chat(client, stream=True)
        assert r.status_code == 503
        msg = r.json()["error"]["message"]
        assert "All providers failed" in msg and "provider down" in msg

    def test_stream_never_falls_back_to_a_cheaper_tier(self, client, providers):
        # A complex prompt whose provider is down fails rather than dropping to a weaker model.
        providers["complex"].fail = True
        r = chat(client, stream=True, force_tier="complex")
        assert r.status_code == 503


class BreaksMidStream(FakeProvider):
    async def stream(self, messages, temperature=0.7, max_tokens=None):
        yield "Partial answer"
        raise ConnectionError("connection reset")


class TestStreamLogging:
    """Streamed requests are logged like other requests, so they show up in /analytics."""

    def test_stream_is_logged_with_estimated_tokens(self, client, logged):
        r = chat(client, content="What is 2+2?", stream=True)
        assert r.status_code == 200
        assert len(logged) == 1
        row = logged[0]
        assert (row["tier"], row["model"], row["provider"], row["status"]) == \
            ("simple", "small-model", "fake", "success")
        # Providers' streams carry no usage, so tokens are estimated at ~4 characters each.
        assert row["input_tokens"] == len("What is 2+2?") // 4
        assert row["output_tokens"] == len("Hello world") // 4
        assert row["baseline_cost"] > 0
        assert row["phash"] == engine.prompt_hash([{"role": "user", "content": "What is 2+2?"}])

    def test_stream_fallback_is_logged_under_the_tier_that_answered(self, client, providers, logged):
        providers["simple"].fail = True
        chat(client, stream=True)
        assert [(row["tier"], row["model"], row["status"]) for row in logged] == [("medium", "mid-model", "fallback")]

    def test_stream_that_breaks_midway_is_logged_as_incomplete(self, client, providers, logged):
        providers["simple"] = BreaksMidStream("small-model")
        r = chat(client, stream=True)
        assert "connection reset" in r.text
        assert len(logged) == 1
        assert logged[0]["status"] == engine.STREAM_INCOMPLETE_STATUS
        assert logged[0]["output_tokens"] == len("Partial answer") // 4

    def test_stream_where_every_tier_fails_is_not_logged(self, client, providers, logged):
        for p in providers.values():
            p.fail = True
        assert chat(client, stream=True).status_code == 503
        assert logged == []


# ─── Cache ────────────────────────────────────────────────────────────────────

class TestCache:
    def test_cache_hit_is_logged_and_skips_provider(self, client, providers, logged):
        app.state.redis = FakeRedis()
        first = chat(client)
        second = chat(client)
        assert first.headers["x-from-cache"] == "false"
        assert second.headers["x-from-cache"] == "true"
        assert providers["simple"].calls == 1
        assert [row["status"] for row in logged] == ["success", engine.CACHE_HIT_STATUS]
        hit = logged[1]
        assert hit["actual_cost"] == 0.0
        assert hit["cost_saved"] == hit["baseline_cost"] > 0

    def test_cached_answer_is_not_served_for_a_different_forced_tier(self, client, providers):
        app.state.redis = FakeRedis()
        chat(client)
        forced = chat(client, force_tier="complex")
        assert forced.headers["x-from-cache"] == "false"
        assert forced.headers["x-router-tier"] == "complex"
        assert providers["complex"].calls == 1
        # The same forced request again is a cache hit for that tier.
        again = chat(client, force_tier="complex")
        assert again.headers["x-from-cache"] == "true"
        assert again.headers["x-router-tier"] == "complex"


# ─── Rate limit ───────────────────────────────────────────────────────────────

class TestRateLimit:
    def test_requests_over_limit_get_429(self, client, settings):
        settings.rate_limit = "3/minute"
        codes = [chat(client).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]

    def test_dashboard_is_not_rate_limited(self, client, settings):
        settings.rate_limit = "1/minute"
        for _ in range(3):
            assert client.get("/").status_code == 200

    def test_each_api_key_gets_its_own_limit(self, client, settings):
        # Two callers behind the same IP, each with their own key, don't share a count.
        settings.rate_limit = "2/minute"
        a = {"X-API-Key": "key-a"}
        b = {"Authorization": "Bearer key-b"}
        assert [chat(client, headers=a).status_code for _ in range(3)] == [200, 200, 429]
        assert [chat(client, headers=b).status_code for _ in range(2)] == [200, 200]

    def test_requests_without_a_key_are_limited_by_ip(self, client, settings):
        settings.rate_limit = "1/minute"
        assert [chat(client).status_code for _ in range(2)] == [200, 429]
        # A keyed request from the same IP is counted separately.
        assert chat(client, headers={"X-API-Key": "key-c"}).status_code == 200


class TestRateLimitKey:
    def _request(self, headers):
        from starlette.requests import Request
        scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                 "client": ("203.0.113.7", 1234)}
        return Request(scope)

    def test_key_is_hashed_never_raw(self):
        from app.security import rate_limit_key
        k = rate_limit_key(self._request({"X-API-Key": "super-secret"}))
        assert k.startswith("key:") and "super-secret" not in k

    def test_bearer_and_header_forms_match(self):
        from app.security import rate_limit_key
        assert rate_limit_key(self._request({"X-API-Key": "abc"})) == \
            rate_limit_key(self._request({"Authorization": "Bearer abc"}))

    def test_falls_back_to_ip(self):
        from app.security import rate_limit_key
        assert rate_limit_key(self._request({})) == "ip:203.0.113.7"


class TestRateLimitStorage:
    def test_defaults_to_in_memory_with_fallback(self):
        from app.security import limiter
        from app.config import get_settings
        assert get_settings().rate_limit_storage == "memory://"
        assert limiter._in_memory_fallback_enabled is True


# ─── Auth ─────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_no_key_configured_allows_requests(self, client):
        assert chat(client).status_code == 200

    def test_missing_key_rejected(self, client, settings):
        settings.router_api_key = "s3cret"
        r = chat(client)
        assert r.status_code == 401

    def test_wrong_key_rejected(self, client, settings):
        settings.router_api_key = "s3cret"
        r = chat(client, headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_bearer_key_accepted(self, client, settings):
        settings.router_api_key = "s3cret"
        r = chat(client, headers={"Authorization": "Bearer s3cret"})
        assert r.status_code == 200

    def test_x_api_key_accepted(self, client, settings):
        settings.router_api_key = "s3cret"
        r = chat(client, headers={"X-API-Key": "s3cret"})
        assert r.status_code == 200

    def test_analytics_requires_key(self, client, settings):
        settings.router_api_key = "s3cret"
        assert client.get("/analytics").status_code == 401

    def test_dashboard_page_is_public(self, client, settings):
        settings.router_api_key = "s3cret"
        assert client.get("/").status_code == 200
