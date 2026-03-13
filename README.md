# Smart Router

> **An AI gateway that routes every prompt to the cheapest model capable of answering it — and proves the savings in real time.**

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

# Response:
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

---

## Quick Start

### Option A — Ollama (local, no accounts needed)

```bash
# 1. Install Ollama and pull models (~5 GB)
brew install ollama
ollama serve                   # keep this running in a terminal
ollama pull llama3.2:1b
ollama pull llama3.1:8b

# 2. Start the stack
git clone https://github.com/your-username/smart-router
cd smart-router
cp .env.example .env           # PROVIDER=ollama is already set
make dev

# 3. Open dashboard
open http://localhost:8000
```

### Option B — OpenRouter (free cloud, recommended for deployment)

```bash
# 1. Sign up at openrouter.ai (email + password, no credit card)
#    Go to Keys → Create Key

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

No LLM is called for classification. A scoring function evaluates signals:

| Signal | Points |
|---|---|
| Token count < 100 | +2 (simple signal) |
| Keywords: "what is", "define", "translate", "summarize" | +2 |
| Keywords: "explain", "compare", "analyze", "write a" | +1 |
| Code patterns (``` `, `def`, `class`, `function`) | +2 |
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

## Deployment (Railway)

> **Note:** Ollama is local-only. For cloud deployment, use OpenRouter or Groq.

### 1. Get a free API key
- **OpenRouter** (recommended): [openrouter.ai](https://openrouter.ai) — no credit card
- **Groq**: [console.groq.com](https://console.groq.com)

### 2. Push to GitHub
```bash
cd smart-router
git init && git add . && git commit -m "initial"
gh repo create smart-router --public --push --source=.
```

### 3. Deploy on Railway
1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Select your `smart-router` repo
3. Add plugins: **PostgreSQL** and **Redis**
4. Set environment variables:

| Variable | Value |
|---|---|
| `PROVIDER` | `openrouter` |
| `OPENROUTER_API_KEY` | your key |
| `DATABASE_URL` | auto-filled by Railway Postgres plugin |
| `REDIS_URL` | auto-filled by Railway Redis plugin |

5. Deploy → Railway builds the Docker image, runs migrations, starts the server.

---

## Project Structure

```
smart-router/
├── railway.toml              # Railway deployment config
├── docker-compose.yml        # Local dev: Postgres + Redis + API
├── .env.example              # Copy to .env
├── Makefile                  # make dev / test / logs / clean
└── backend/
    ├── Dockerfile            # Production-ready (non-root, healthcheck, auto-migrate)
    ├── start.sh              # Runs migrations then starts server
    ├── requirements.txt
    ├── alembic.ini
    ├── migrations/
    └── app/
        ├── main.py           # FastAPI app (CORS, rate limiting, static files)
        ├── config.py         # Settings + DATABASE_URL scheme fix for Railway
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
make dev          # build and start everything
make test         # smoke tests against all endpoints
make logs         # tail API logs
make stop         # stop containers (keep data)
make clean        # stop + wipe database
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) |
| Database | PostgreSQL + SQLAlchemy (async) + Alembic |
| Cache | Redis |
| LLMs | Ollama / OpenRouter / Groq / Any OpenAI-compatible |
| Classifier | Heuristic rules (zero cost) |
| Infrastructure | Docker Compose (local) · Railway (cloud) |
