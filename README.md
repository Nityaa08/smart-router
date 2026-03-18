# Smart Router

[![CI](https://github.com/Nityaa08/smart-router/actions/workflows/ci.yml/badge.svg)](https://github.com/Nityaa08/smart-router/actions/workflows/ci.yml)

> **An AI cost-control gateway that routes every prompt to the cheapest model capable of answering it — and proves the savings in real time.**

---

## The Problem

Every prompt you send to GPT-4o costs the same — whether you're asking *"what is 2+2?"* or *"design a distributed caching system."* Most AI workloads are simple. Routing all traffic to a frontier model wastes 90%+ of your budget on queries a 1B-parameter model handles just as well.

## What It Does

Smart Router sits between your app and your LLMs. It classifies each prompt using zero-cost heuristic rules (no API call), routes it to the cheapest capable model, logs every decision, and shows you exactly how much was saved vs. sending everything to GPT-4o.

```
Your App
    ↓
POST /v1/chat/completions  (OpenAI-compatible)
    ↓
Smart Router
    ↓
Heuristic Classifier  ← zero cost, <1ms, no LLM needed
    ↓
┌───────────┬───────────┬───────────┐
│  simple   │  medium   │  complex  │
│ ~$0.01/M  │ ~$0.05/M  │ ~$0.59/M  │
└───────────┴───────────┴───────────┘
    ↓
PostgreSQL log  ← cost, savings, latency, tier
Redis cache     ← identical prompts served instantly
```

**Typical result:** 90–99% cost reduction on mixed workloads, with a live dashboard showing exactly what was saved.

---

## Live Demo

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
```

---

## Features

| Feature | Detail |
|---|---|
| **Zero-cost classifier** | Rule-based scoring on token count, keywords, code patterns — no LLM, no API call |
| **OpenAI-compatible API** | Drop-in `POST /v1/chat/completions` — works with any OpenAI SDK |
| **4 provider options** | Ollama (local) · OpenRouter (free) · Groq (free) · Any OpenAI-compatible API |
| **Router response headers** | `X-Router-Tier`, `X-Router-Model`, `X-Cost-Saved` on every response |
| **Redis caching** | Identical prompts served from cache (SHA-256 keyed, 1hr TTL) |
| **Cost analytics dashboard** | `GET /analytics` — total saved, savings %, per-tier breakdown |
| **Fallback escalation** | Provider fails → automatically escalates to next tier |
| **Live dashboard** | Built-in UI at `/` showing real-time routing distribution and cost savings |
| **47 unit tests** | Full test coverage of classifier heuristics and cost calculation logic |

---

## Quick Start

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

```bash
# 1. Sign up at openrouter.ai → Keys → Create Key

# 2. Edit .env:
PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-your-key-here

make dev
```

### Option C — Groq (free cloud)

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
| Token count < 100 | +2 (simple signal) |
| Keywords: "what is", "define", "translate", "summarize" | +2 |
| Keywords: "explain", "compare", "analyze", "write a" | +1 |
| Code patterns (` ``` `, `def`, `class`, `function`) | +2 |
| Multi-step patterns ("first… then…", numbered steps) | +2 |
| Math/logic ("prove", "derive", "algorithm", "complexity") | +2 |
| Token count > 500 | +2 (complex signal) |

**Score ≤ 4 → simple · Score 5–7 → medium · Score ≥ 8 → complex**

---

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
make unit-test

# Integration smoke tests (requires running stack)
make test
```

The unit test suite covers the heuristic classifier and all cost calculation logic with 47 tests, zero external dependencies.

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

See `.env.example` for the full list.

---

## Project Structure

```
smart-router/
├── docker-compose.yml        # Local dev: Postgres + Redis + API
├── .env.example              # Copy to .env, fill in API key
├── Makefile                  # make dev / test / unit-test / logs / clean
├── .github/
│   └── workflows/ci.yml      # CI: unit tests + Docker build on every push
└── backend/
    ├── Dockerfile            # Production-ready (non-root, healthcheck, auto-migrate)
    ├── start.sh              # Runs migrations then starts server
    ├── requirements.txt
    ├── alembic.ini
    ├── migrations/           # Alembic schema migrations
    ├── tests/
    │   ├── test_classifier.py  # 30 classifier unit tests
    │   └── test_config.py      # 17 config/cost-calc unit tests
    └── app/
        ├── main.py           # FastAPI app (CORS, rate limiting, static files)
        ├── config.py         # Settings + DATABASE_URL scheme normalizer
        ├── database.py       # Async SQLAlchemy
        ├── classifier/       # Zero-cost heuristic scorer
        ├── providers/        # Ollama · Groq · OpenRouter · Generic OpenAI-compat
        ├── router/           # classify → route → log
        ├── api/              # /v1/chat/completions · /analytics · /health
        ├── models/           # RequestLog ORM
        └── static/           # Dashboard UI (served at /)
```

---

## Commands

```bash
make dev          # build and start everything (Postgres + Redis + API)
make unit-test    # run unit tests locally (no services needed)
make test         # end-to-end smoke tests against all endpoints
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
