.PHONY: install demo test unit-test dev stop migrate migrate-new smoke logs clean

# ── Local, no Docker ─────────────────────────────────────────────────────────
# Python 3.12 is preferred: the pinned asyncpg 0.29 does not build on 3.13.
PYTHON ?= $(shell command -v python3.12 || command -v python3.11 || command -v python3)
VENV = .venv
BIN = $(CURDIR)/$(VENV)/bin
PORT ?= 8000

$(VENV)/.installed: backend/requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r backend/requirements.txt pytest
	@touch $@

install: $(VENV)/.installed

# Demo mode: simulated answers, no API key, no Postgres, no Redis.
demo: install
	@echo "Smart Router (demo mode) at http://localhost:$(PORT)  (dashboard: /dashboard, API docs: /docs)"
	cd backend && PROVIDER=demo DATABASE_URL=memory REDIS_URL=none $(BIN)/uvicorn app.main:app --reload --port $(PORT)

# Unit tests: no database, Redis or LLM needed (the same suite CI runs).
test: install
	cd backend && $(BIN)/python -m pytest tests/ -q

unit-test: test

# ── Docker Compose (Postgres + Redis + API) ──────────────────────────────────

dev:
	@echo "Starting Smart Router (Postgres + Redis + API)..."
	cp -n .env.example .env 2>/dev/null || true
	docker compose up --build -d
	@echo "Waiting for services..."
	@sleep 3
	docker compose exec api alembic upgrade head
	@echo ""
	@echo "✓ Smart Router running at http://localhost:8000"
	@echo "  POST /v1/chat/completions  — chat endpoint"
	@echo "  GET  /analytics            — cost savings dashboard"
	@echo "  GET  /health               — service health"

stop:
	docker compose down

migrate:
	docker compose exec api alembic upgrade head

migrate-new:
	docker compose exec api alembic revision --autogenerate -m "$(MSG)"

# If ROUTER_API_KEY is set, run as: make smoke ROUTER_API_KEY=your-key
AUTH = $(if $(ROUTER_API_KEY),-H "Authorization: Bearer $(ROUTER_API_KEY)",)

# End-to-end checks against a running stack (make dev or make demo).
smoke:
	@echo "Running smoke tests..."
	@curl -sf http://localhost:8000/health | python3 -m json.tool
	@echo ""
	@echo "Simple prompt (expect tier=simple):"
	@curl -sf -X POST http://localhost:8000/v1/chat/completions $(AUTH) \
		-H "Content-Type: application/json" \
		-d '{"messages":[{"role":"user","content":"What is 2+2?"}]}' \
		-D - 2>&1 | grep -iE "x-router|HTTP"
	@echo ""
	@echo "Complex prompt (expect tier=complex):"
	@curl -sf -X POST http://localhost:8000/v1/chat/completions $(AUTH) \
		-H "Content-Type: application/json" \
		-d '{"messages":[{"role":"user","content":"Implement a recursive algorithm to find all permutations of a list in Python. First analyze the complexity, then write the code with tests."}]}' \
		-D - 2>&1 | grep -iE "x-router|HTTP"
	@echo ""
	@echo "Analytics:"
	@curl -sf http://localhost:8000/analytics $(AUTH) | python3 -m json.tool

logs:
	docker compose logs -f api

clean:
	docker compose down -v
	@echo "Removed containers and volumes."
