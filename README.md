# Smart Router

[![CI](https://github.com/Nityaa08/smart-router/actions/workflows/ci.yml/badge.svg)](https://github.com/Nityaa08/smart-router/actions/workflows/ci.yml)

**Live demo: [smart-router-nityashree.vercel.app](https://smart-router-nityashree.vercel.app)** (simulated answers, no API key) · by [Nityashree S](https://nityashree.in)

> **An OpenAI-compatible LLM gateway that routes each prompt to one of three model tiers using hand-written rules, and estimates the cost of every request.**

[![Demo page: a 60-second summary with three try-it buttons, and a routing report card showing 23 of 24 labelled prompts routed correctly, a confusion matrix, the one miss and a cost comparison; below, the prompt console and the tier switchboard](docs/screenshot.png)](https://smart-router-nityashree.vercel.app)

### Run it in 1 minute

Needs Python 3.12 (the pinned `asyncpg` does not build on 3.13) and `make`. No API key, no Docker.

```bash
git clone https://github.com/Nityaa08/smart-router && cd smart-router
make demo    # creates .venv, installs, serves demo mode at http://localhost:8000
make test    # the unit test suite (no database, Redis or LLM needed)
make eval    # routing accuracy on 24 hand-labelled prompts, with a confusion matrix
```

Without `make`: `cd backend && pip install -r requirements.txt && PROVIDER=demo DATABASE_URL=memory REDIS_URL=none uvicorn app.main:app --reload`.
With Docker (Postgres + Redis + a real provider): `cp .env.example .env`, set a provider in `.env`, then `make dev` (or `docker compose up --build`). See [Quick Start](#quick-start).

---

## In 60 seconds

| | |
|---|---|
| **Problem** | Apps send every prompt to one expensive model, including "what is 2+2?". Most prompts don't need it. |
| **What I built** | A drop-in, OpenAI-compatible gateway. Rules score each prompt in under a millisecond, the cheapest tier that fits answers, a failing provider falls back to the next tier, and every request is logged with its cost. |
| **Proof** | 23 of 24 hand-labelled prompts reach the labelled tier ([routing eval](#routing-eval), served live at `/v1/route/eval` and shown on the demo page as a report card with a confusion matrix). 139 unit tests, CI on every push. |
| **Engineering** | FastAPI, async httpx, Pydantic, Redis cache, Postgres with Alembic, SSE streaming, rate limiting per API key, Docker, GitHub Actions. |

## The Problem

Every prompt you send to GPT-4o is billed at the same per-token price — whether you're asking *"what is 2+2?"* or *"design a distributed caching system."* Many prompts are short and simple, so sending all of them to a frontier model may cost more than needed. Smart Router explores that idea: it routes by rules and records what each request would have cost on GPT-4o.

## What It Does

Smart Router sits between your app and your LLMs. It classifies each prompt using zero-cost heuristic rules (no API call), routes it to the model configured for that tier, logs every decision, and estimates the cost difference against GPT-4o list prices.

```mermaid
flowchart LR
    App[Your app<br/>OpenAI SDK] -->|POST /v1/chat/completions| GW[Gateway<br/>API key · rate limit]
    GW --> C{Redis cache<br/>SHA-256 of messages}
    C -->|hit| Resp[Response<br/>+ X-Router-* headers]
    C -->|miss| CL[Rule classifier<br/>score 0-15, under 1 ms]
    CL -->|score 0-1| S[simple tier]
    CL -->|score 2-3| M[medium tier]
    CL -->|score 4+| X[complex tier]
    S -. provider down .-> M
    M -. provider down .-> X
    S & M & X --> P[Provider<br/>Groq · OpenRouter · Ollama · OpenAI-compatible · demo]
    P --> Resp
    P --> L[(Request log<br/>Postgres, or memory)]
    L --> A[/analytics<br/>cost vs GPT-4o/]
```

Each tier maps to a model you set in `.env`. **About the savings number:** it compares the price-table cost of the model used with GPT-4o list prices for the same token counts. It is not a measured saving — see [Known Limitations](#known-limitations-checked-2026-11-14).

---

## The Live Demo

The public demo runs this code on Vercel's free tier in **demo mode** (`PROVIDER=demo`):

- **No language model is called and no API key exists in the deployment.** Each tier is a `DemoProvider` that returns a clearly labelled simulated answer. Token counts are estimates (prompt length / 4, and a typical answer length per tier).
- **Everything else is the real code:** the classifier, routing, tier fallback, cost estimate at list prices, rate limit and analytics.
- The page at `/` is a small control room: a prompt console, and a switchboard that lights the lane (simple, medium or complex, each with its model and list price) the prompt was routed to, places the score on a gauge against the tier thresholds, lists every rule that fired with its points (from `POST /v1/route/explain`), and compares the estimated cost with GPT-4o. The dashboard at `/dashboard` shows totals and requests by tier for the instance.
- There is no Postgres or Redis on the demo: `DATABASE_URL=memory` keeps the request log in the function's memory (so `/analytics` covers one instance and resets), and `REDIS_URL=none` turns the cache off.
- Guards for a public URL: 20 requests a minute per client IP (`RATE_LIMIT`, counted per instance), prompts up to 2,000 characters (`MAX_PROMPT_CHARS`), and the client IP taken from Vercel's `X-Real-IP` header (`TRUST_PROXY_HEADERS=true`).

**To make the demo answer with real models** (free): create a Groq API key at [console.groq.com](https://console.groq.com), then in the Vercel project settings set `PROVIDER=groq`, `GROQ_API_KEY=<key>` and `MAX_COMPLETION_TOKENS=300`, and redeploy. The key stays in Vercel's encrypted environment variables, never in the repository. The page then says "Live" instead of "Demo mode".

---

## Example requests

```bash
# Simple question → routes to cheapest model
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is 2+2?"}]}'

# Response headers:
# X-Router-Tier:  simple
# X-Router-Model: llama3.2:1b
# X-Cost-Saved:   0.00016959

# Complex prompt → escalates automatically
curl -X POST http://localhost:8000/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"Implement quicksort with complexity analysis"}]}'

# X-Router-Tier:  complex
# X-Router-Model: llama3.1:8b

# Why? The rules that fired, with no model call
curl -X POST http://localhost:8000/v1/route/explain \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Implement quicksort with complexity analysis"}]}'
```

---

## Features

| Feature | Detail |
|---|---|
| **Zero-cost classifier** | Rule-based scoring on token count, keywords, code patterns — no LLM, no API call |
| **OpenAI-compatible API** | Drop-in `POST /v1/chat/completions` — works with any OpenAI SDK |
| **5 provider options** | Ollama (local) · OpenRouter (free) · Groq (free) · Any OpenAI-compatible API · `demo` (simulated, no key) |
| **Explainable routing** | `POST /v1/route/explain` returns the score, every rule that fired and the per-tier models with their list prices, without calling a model |
| **Router response headers** | `X-Router-Tier`, `X-Router-Model`, `X-Cost-Saved` on every response |
| **Redis caching** | Identical prompts served from cache (SHA-256 keyed, 1hr TTL) |
| **Cost analytics dashboard** | `GET /analytics` — estimated cost, estimated savings vs. GPT-4o list prices, per-tier breakdown |
| **Fallback escalation** | Provider fails → automatically escalates to next tier |
| **Playground and dashboard** | `/` is a playground that shows each routing decision; `/dashboard` shows routing distribution and estimated cost |
| **Optional API key** | Set `ROUTER_API_KEY` to require `Authorization: Bearer <key>` on the chat and analytics endpoints |
| **Rate limit** | `RATE_LIMIT` per client IP on `POST /v1/chat/completions` (HTTP 429 when exceeded) |
| **139 unit tests** | Classifier, the routing eval, cost calculation, the chat endpoint (routing, fallback, streaming, cache, rate limit, auth) with fake providers, and the demo mode (demo provider, in-memory log, explain endpoint, guards) |

---

## Quick Start

### Option 0 — Demo mode (no Docker, no model, no key)

```bash
make demo                      # or, by hand:
cd backend
pip install -r requirements.txt
PROVIDER=demo DATABASE_URL=memory REDIS_URL=none uvicorn app.main:app --reload
open http://localhost:8000
```

This is what the live demo runs. Answers are simulated; everything else is real.

### Option A — Ollama (local, no accounts needed)

```bash
# 1. Install Ollama and pull models (~5 GB)
brew install ollama
ollama serve                   # keep this running in a terminal
ollama pull llama3.2:1b
ollama pull llama3.1:8b

# 2. Clone and start the stack
git clone https://github.com/Nityaa08/smart-router
cd smart-router
cp .env.example .env           # PROVIDER=ollama is already set
make dev

# 3. Open dashboard
open http://localhost:8000
```

### Option B — OpenRouter (free cloud, no credit card needed)

The default models are free (`:free`) models that OpenRouter listed on 2026-11-02 (`google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`). OpenRouter's free list changes often; if a request returns 404, pick current IDs from [openrouter.ai/api/v1/models?max_price=0](https://openrouter.ai/api/v1/models?max_price=0) and set them in `.env`.

```bash
# 1. Sign up at openrouter.ai → Keys → Create Key

# 2. Edit .env:
PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-your-key-here

make dev
```

### Option C — Groq (free cloud)

The defaults are `openai/gpt-oss-20b` (simple) and `openai/gpt-oss-120b` (medium, complex), both production models on [Groq's model list](https://console.groq.com/docs/models) on 2026-11-02. Groq retired the earlier defaults (see [Groq deprecations](https://console.groq.com/docs/deprecations)).

```bash
# 1. Sign up at console.groq.com → API Keys

# 2. Edit .env:
PROVIDER=groq
GROQ_API_KEY=gsk_your-key-here

make dev
```

---

## How the Classifier Works

No LLM is called for classification. A scoring function evaluates signals in <1ms:

| Signal | Points |
|---|---|
| Simple keywords: "what is", "define", "translate", "summarize", "who is" | −1 each, at most −2 |
| Medium keywords: "explain", "compare", "analyze", "write a" | +1 each, at most +3 |
| Complex keywords: "implement", "debug", "refactor", "prove", "algorithm" | +2 each, at most +4 |
| Code patterns (` ``` `, `def`, `class`, `function f(`) | +2 |
| Multi-step patterns ("first… then…", numbered steps) | +2 |
| Math/logic ("prove", "derive", "complexity", "Big-O", `O(1)`, `O(n)`) | +2 |
| Token count > 500 | +2 |

**Score 0–1 → simple · Score 2–3 → medium · Score ≥ 4 → complex** (the score never goes below 0)

The score measures complexity, so simple keywords take points away. Until 2026-11-14 they added points and every short prompt got +2, which sent prompts with two simple questions ("What is DNS? How many root servers are there?") to `medium` and two-keyword explanations ("Explain the difference between TCP and UDP") to `simple`. On a hand-labelled set of 24 prompts in `tests/test_classifier.py` (8 per tier) the old rules matched 10, the current rules match 23.

---

## Routing eval

`make eval` (or `GET /v1/route/eval`, which the demo page draws as a report card) runs the real classifier over the 24 hand-labelled prompts in [`backend/app/evals/labelled.py`](backend/app/evals/labelled.py), 8 per tier:

```
23/24 routed to the labelled tier (96%)
labelled \ routed   simple   medium  complex
           simple        8        0        0
           medium        1        7        0
          complex        0        0        8
miss: medium -> simple (score 1): Analyze the pros and cons of remote work for a small startup
cost per 1k runs of the set (prompt (input) tokens only, at list prices): $0.0162 routed vs $0.0207 all on the complex tier vs $1.0325 on gpt-4o
```

How to read it:

- **The one miss goes down a tier**, which is the costly kind of mistake (a weaker model answers), so the report counts "too low" and "too high" separately.
- **Routing itself saves about a fifth** of the prompt cost here compared with sending everything to the complex tier ($0.0162 vs $0.0207 with the Groq defaults). Most of the gap to GPT-4o comes from the cheaper open models, not from routing.
- **This is not a held-out score.** The rules were adjusted with these prompts in view (10 of 24 matched before the scoring change on 2026-11-14), so it is a regression check that keeps obvious cases right. A real evaluation needs prompts the rules were not tuned on.

The test suite reads the same list, so a rule change that breaks a labelled case fails CI.

## API Reference

### `POST /v1/chat/completions`
OpenAI-compatible chat endpoint.

```json
{
  "messages": [{"role": "user", "content": "..."}],
  "force_tier": null,
  "stream": false
}
```

`"stream": true` returns OpenAI-style `chat.completion.chunk` Server-Sent Events ending in `data: [DONE]`, with the `X-Router-Tier` and `X-Router-Model` headers. If a provider fails before its first chunk, the stream falls back to the next tier up, like non-streamed requests, and `X-Router-Fallback: true` says so. Only if every tier fails is the response HTTP 503. Streamed requests are logged to `/analytics` when the stream ends, with estimated token counts, and are not cached (see Known Limitations).

If `ROUTER_API_KEY` is set, send `Authorization: Bearer <key>` (or `X-API-Key: <key>`); otherwise the response is HTTP 401. Requests over `RATE_LIMIT` get HTTP 429. The limit counts per API key when one is sent (hashed, never stored raw), otherwise per client IP.

Response includes a `router` field:
```json
{
  "router": {
    "tier": "simple",
    "model": "llama3.2:1b",
    "provider": "ollama",
    "actual_cost_usd": 0.0000004,
    "cost_saved_usd": 0.00017,
    "latency_ms": 2243,
    "from_cache": false
  }
}
```

### `GET /analytics`
`by_tier` groups requests by the tier whose model answered: a forced tier counts under that tier, and a fallback under the tier it fell back to. `cache_hits` counts requests answered from Redis. A cache hit is logged with zero cost, and the GPT-4o price of its tokens counts as saved; `avg_latency_ms` covers provider calls only. Requires the API key if `ROUTER_API_KEY` is set.

Example shape (illustrative values):
```json
{
  "total_requests": 1234,
  "actual_cost_usd": 0.12,
  "baseline_cost_usd": 8.70,
  "total_saved_usd": 8.58,
  "savings_pct": 98.6,
  "by_tier": { "simple": {...}, "medium": {...}, "complex": {...} },
  "avg_latency_ms": 380,
  "cache_hits": 45
}
```

### `GET /health`
```json
{"status": "ok", "db": "up", "provider": "up", "provider_name": "ollama"}
```

---

## Running Tests

```bash
# Unit tests (no database or LLM required — runs in CI)
make test

# End-to-end smoke checks against a running server (make demo or make dev)
make smoke
```

The unit test suite has 139 tests (64 classifier, 22 config/cost/default-model, 31 API, 16 demo mode, 6 routing eval; one classifier test is a known miss marked as an expected failure) with zero external dependencies: the API tests replace the LLM providers, Redis and the Postgres logger with in-memory fakes. Line coverage on 2026-11-02: 100% of `classifier/heuristics.py`, `config.py` and `security.py`, 87% of `api/chat.py`, 81% of `router/engine.py`, 71% of the app overall. The provider HTTP clients and `/analytics` SQL are not unit-tested; the fake-model run below covers them end to end.

`make smoke` prints the HTTP status and the `x-router-tier` / `x-router-model` headers. If you set `ROUTER_API_KEY`, run `make smoke ROUTER_API_KEY=your-key`.

---

## Run With a Fake Model (no account, no API key)

This checks the whole stack (routing, Postgres log, Redis cache, analytics) without any LLM provider. The fake answers in the OpenAI format with fixed text and fixed token counts, so cost numbers come only from the price table.

1. Start Docker Desktop. Then create a virtual environment and the fake server (terminal 2):

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cat > fake_llm.py <<'EOF'
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

@app.get("/v1/models")
async def models():
    return {"data": [{"id": "fake"}]}

@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    model = body.get("model", "fake")
    question = body["messages"][-1]["content"]
    answer = f"[fake answer from {model}] You asked: {question[:40]}"
    if body.get("stream"):
        def gen():
            for word in answer.split():
                chunk = {"choices": [{"delta": {"content": word + " "}}]}
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return JSONResponse({
        "choices": [{"message": {"role": "assistant", "content": answer}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 200},
    })
EOF
.venv/bin/uvicorn fake_llm:app --host 0.0.0.0 --port 9100
```

2. In terminal 1, copy `.env.example` to `.env` and set these lines:

```bash
PROVIDER=openai_compat
OPENAI_COMPAT_BASE_URL=http://host.docker.internal:9100/v1
OPENAI_COMPAT_API_KEY=not-a-real-key
OPENAI_COMPAT_SIMPLE_MODEL=llama3.2:1b
OPENAI_COMPAT_MEDIUM_MODEL=llama3.1:8b
OPENAI_COMPAT_COMPLEX_MODEL=llama3.1:8b
```

3. Run `make dev`, then `make smoke` (called `make test` at the time). Checked on 2026-10-28: health is `ok`, both prompts return HTTP 200, and `/analytics` shows 2 requests. Run `make clean` when done.

On 2026-11-02 streaming and the rate limit were checked against the same fake server (API run with uvicorn, without Postgres or Redis): `"stream": true` returned the chunks and `[DONE]`, and with `RATE_LIMIT=5/minute` the sixth request got HTTP 429. The full Docker stack was not re-run that day.

---

## Known Limitations (checked 2026-11-14)

- **Savings are an estimate, not a measurement.** `cost_saved` prices the tokens the chosen model used at GPT-4o list prices (from `config.py`) and subtracts the chosen model's price. Answer quality is not compared, and there is no evaluation set yet. The small-model prices for local Ollama models are assumptions.
- **The classifier is unvalidated.** It uses hand-written keyword rules, checked only against 24 hand-labelled prompts (23 match, see [Routing eval](#routing-eval)) that it was tuned on, not a held-out evaluation set. Known misses: a request with a single medium keyword ("Analyze the pros and cons of remote work") scores 1 and goes to `simple`, and a simple keyword cancels a harder one ("What is a closure? Implement one in JavaScript." stays `simple`). Keywords are matched anywhere in the text, with no sense of meaning.
- **Streaming is simpler than the non-streaming path.** Streamed requests fall back to the next tier only before their first chunk (a provider that fails mid-stream reports the error in the stream). They are not cached. They are logged to `/analytics`, but the providers' streams carry no token usage, so their tokens and cost are estimated at about 4 characters per token from the prompt and the streamed text, and their latency is the time until the stream ended. A stream that stops early (provider error or client disconnect) is logged with status `stream_incomplete` and the text sent so far. In demo mode a streamed answer is therefore priced lower than the same answer non-streamed, which uses a typical answer length per tier.
- **Authentication is one optional shared key.** With `ROUTER_API_KEY` unset (the default, for local dev) any client that can reach the server can send requests. There are no per-user keys or quotas. `/health` and the dashboard page stay public. CORS defaults to `*`.
- **Rate-limit counts are only shared when Redis is used.** Limits are per API key (or per IP when no key is sent). With `RATE_LIMIT_STORAGE=memory://`, each process counts separately. Docker Compose points it at the bundled Redis, so all workers share one count; if Redis goes down, counting falls back to each process.
- **Default cloud model IDs will go out of date again.** The defaults were checked on 2026-11-02 against [Groq's model list](https://console.groq.com/docs/models) and [OpenRouter's free-model list](https://openrouter.ai/api/v1/models?max_price=0). Free OpenRouter models in particular are added and removed often. If you change models, add paid ones to `MODEL_PRICING`: unknown models are priced as GPT-4o (no saving shown); any `:free` model is priced at 0.
- **Prices are hard-coded** in `config.py` (Groq prices checked 2026-11-02).
- **The live demo shows the pipeline, not model quality.** In demo mode answers are simulated and token counts are estimated, so its cost figures illustrate the pricing logic only. Its `/analytics` numbers live in one serverless instance's memory and reset when the instance is recycled, and its rate limit is counted per instance.

---

## Self-Hosting with Docker

The included `Dockerfile` builds a production-ready image. You can run it on any Docker host:

```bash
# Build
docker build -t smart-router ./backend

# Run with Postgres and Redis
docker compose up --build -d
```

Environment variables:

| Variable | Description |
|---|---|
| `PROVIDER` | `ollama` \| `openrouter` \| `groq` \| `openai_compat` |
| `OPENROUTER_API_KEY` | Required for OpenRouter |
| `GROQ_API_KEY` | Required for Groq |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `RATE_LIMIT` | Per-key (or per-IP) limit on `POST /v1/chat/completions` and `/v1/route/explain`, e.g. `60/minute` |
| `ROUTER_API_KEY` | Optional. If set, chat and analytics require `Authorization: Bearer <key>` |
| `MAX_PROMPT_CHARS` | Optional. Longer prompts get HTTP 413 (0 = no limit) |
| `MAX_COMPLETION_TOKENS` | Optional. Caps `max_tokens` sent to the provider (0 = no cap) |
| `TRUST_PROXY_HEADERS` | `true` only behind a proxy that sets `X-Real-IP` itself (e.g. Vercel) |

`DATABASE_URL=memory` keeps the request log in memory instead of Postgres; `REDIS_URL=none` turns the cache off.

See `.env.example` for the full list.

---

## Project Structure

```
smart-router/
├── docker-compose.yml        # Local dev: Postgres + Redis + API
├── .env.example              # Copy to .env, fill in API key
├── Makefile                  # make demo / test / dev / smoke / logs / clean
├── .github/
│   └── workflows/ci.yml      # CI: unit tests + Docker build on every push
└── backend/
    ├── Dockerfile            # Production-ready (non-root, healthcheck, auto-migrate)
    ├── index.py              # Vercel entrypoint (imports app.main:app)
    ├── start.sh              # Runs migrations then starts server
    ├── requirements.txt
    ├── alembic.ini
    ├── migrations/           # Alembic schema migrations
    ├── tests/
    │   ├── test_classifier.py  # 64 classifier tests, incl. the 24 hand-labelled prompts
    │   ├── test_config.py      # 22 config/cost/default-model tests
    │   ├── test_api.py         # 31 chat-endpoint tests with fake providers
    │   ├── test_demo.py        # 16 demo-mode tests
    │   └── test_eval.py        # 6 routing-eval tests
    └── app/
        ├── main.py           # FastAPI app (CORS, rate-limit handler, static files)
        ├── security.py       # Rate limiter + optional API key check
        ├── config.py         # Settings + DATABASE_URL scheme normalizer
        ├── database.py       # Async SQLAlchemy
        ├── classifier/       # Zero-cost heuristic scorer
        ├── evals/            # Hand-labelled prompts + routing eval (make eval, /v1/route/eval)
        ├── providers/        # Ollama · Groq · OpenRouter · Generic OpenAI-compat · Demo
        ├── router/           # classify → route → log (Postgres, or memlog.py in memory)
        ├── api/              # /v1/chat/completions · /v1/route/explain · /analytics · /health
        ├── models/           # RequestLog ORM
        └── static/           # demo.html (playground at /) · index.html (dashboard at /dashboard)
```

---

## Commands

```bash
make demo         # demo mode in a local .venv (no Docker, no key)
make test         # run unit tests locally (no services needed); also: make unit-test
make dev          # build and start everything with Docker (Postgres + Redis + API)
make smoke        # end-to-end smoke tests against a running server
make logs         # tail API logs
make stop         # stop containers (keep data)
make clean        # stop + wipe database
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic |
| Cache | Redis 7 |
| LLMs | Ollama · OpenRouter · Groq · Any OpenAI-compatible endpoint |
| Classifier | Heuristic rules (zero cost, <1ms) |
| Infrastructure | Docker Compose |
| CI | GitHub Actions (unit tests + Docker build) |

---

## Deployment

- **Live demo:** Vercel (free tier), project root `backend/`, entrypoint `backend/index.py`, Python 3.12 (`backend/.python-version`). Environment variables: `PROVIDER=demo`, `DATABASE_URL=memory`, `REDIS_URL=none`, `RATE_LIMIT=20/minute`, `MAX_PROMPT_CHARS=2000`, `TRUST_PROXY_HEADERS=true`. Every push to `main` redeploys.
- **Full stack (Postgres + Redis + a real provider):** Docker Compose as above, on any host that runs Docker.

---

Built by [Nityashree S](https://nityashree.in) · [GitHub](https://github.com/Nityaa08)
