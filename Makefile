.PHONY: dev stop migrate test unit-test logs clean

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

# If ROUTER_API_KEY is set, run as: make test ROUTER_API_KEY=your-key
AUTH = $(if $(ROUTER_API_KEY),-H "Authorization: Bearer $(ROUTER_API_KEY)",)

test:
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

unit-test:
	@echo "Running unit tests (no services required)..."
	cd backend && python -m pytest tests/ -v

logs:
	docker compose logs -f api

clean:
	docker compose down -v
	@echo "Removed containers and volumes."
