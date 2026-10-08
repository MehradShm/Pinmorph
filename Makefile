.PHONY: up down logs check integration seed-plan seed-demo web-check browser-check phase2-exercises phase3-exercises phase3-preflight phase3b-exercises phase3b-preflight phase4-exercises phase4-preflight mind-fixture

up: lens-prepare
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

# Shared Phase 2 core acceptance; requires the local stack.
phase2-exercises:
	RUN_PHASE2_EXERCISES=1 RUN_INTEGRATION=1 uv run --locked pytest -m phase2_exercise

phase3-exercises:
	RUN_PHASE3_EXERCISES=1 uv run --locked pytest -m phase3_exercise

phase3b-exercises:
	RUN_PHASE3B_EXERCISES=1 uv run --locked pytest -m phase3b_exercise

phase3b-preflight:
	uv run --locked python -m scripts.phase3b_preflight

phase4-exercises:
	RUN_PHASE4_EXERCISES=1 uv run --locked pytest -m phase4_exercise

phase4-preflight:
	uv run --locked python -m scripts.phase4_preflight

mind-fixture:
	uv run --locked python -m scripts.inspect_mind --dataset-dir backend/tests/fixtures/mind_synthetic --partition fixture --source-timezone UTC --provenance synthetic_fixture

# Read-only inventory; add --database to the Python command to inspect the running stack.
phase3-preflight:
	uv run --locked python -m scripts.phase3_preflight

seed-plan:
	uv run --locked python -m scripts.seed --demo --dry-run --reference-time 2026-10-07T00:00:00Z

seed-demo:
	docker compose exec api python -m scripts.seed --demo --reference-time 2026-10-07T00:00:00Z --wait 120

web-check:
	cd frontend && npm run build

browser-check:
	@result=0; (cd frontend && npm run test:e2e) || result=$$?; uv run --locked python -m scripts.cleanup_browser_tests || exit $$?; exit $$result

lens-prepare:
	uv run --locked python -m scripts.prepare_lens

lens-backfill:
	uv run --locked python -m scripts.backfill_lens

lens-evaluate:
	uv run --locked python -m scripts.evaluate_lens

.PHONY: analytics-rollup
analytics-rollup:
	uv run --locked python -m scripts.rollup_analytics
