.PHONY: up down logs check integration seed-plan seed-demo web-check browser-check

up:
	docker compose up --build -d --wait

down:
	docker compose down

logs:
	docker compose logs -f api worker

check:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked pytest -m "not integration"

integration:
	RUN_INTEGRATION=1 uv run --locked pytest -m integration

seed-plan:
	uv run --locked python -m scripts.seed --demo --dry-run --reference-time 2026-10-07T00:00:00Z

seed-demo:
	docker compose exec api python -m scripts.seed --demo --reference-time 2026-10-07T00:00:00Z --wait 120

web-check:
	cd frontend && npm run build

browser-check:
	@result=0; (cd frontend && npm run test:e2e) || result=$$?; uv run --locked python -m scripts.cleanup_browser_tests || exit $$?; exit $$result
