# Pinterest-lite

A learning-oriented clone of Pinterest, built to prepare for a machine learning engineer
role focused on recommendation/CTR modeling, pin and user embeddings, and lightweight
re-ranking. Build the core ML loop first so learning happens inside a working system:
real logging, candidate sources, measured latency, and observable background work.

The project must work end to end WITHOUT live users. A separate, reusable simulator will
plug in through docs/SIMULATOR_CONTRACT.md to provide production-like traffic, event
delivery problems, and failure/recovery exercises. Its purpose is hands-on operational
experience; simple scripted behavior is sufficient. Simulation logic lives outside this
repo; the product provides instrumentation and an adapter to normal application services.

The first finish line is phase 3A: seeded catalog, browse/save, reliable logging,
personalized feed, offline evaluation, and a configuration-driven model swap. Broader
product features, the separate MIND CTR study, and simulator exercises follow that milestone.

## Always-loaded context

- How we work together (developer profile, scaffold vs learn mode): @docs/WORKING_AGREEMENT.md
- Full plan (modules, phases, ML pipeline, logging, data, evaluation, experiments): @docs/PLAN.md
- Contract every project exposes for the future simulator: @docs/SIMULATOR_CONTRACT.md
- Decision log, append after every significant choice: @docs/DECISIONS.md

## Stack (defaults; changing one is a decision to log)

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2
- Data: PostgreSQL 16 with pgvector, Redis, MinIO (S3-compatible object storage)
- Background jobs: RQ workers (image processing, embedding jobs, rollups)
- ML: PyTorch, open_clip, LightGBM, scikit-learn, polars, MLflow (local tracking)
- Frontend: React, Vite, TypeScript, CSS-columns masonry grid. Keep it functional, not fancy.
- Tooling: uv, ruff, pytest, docker compose for everything

## Commands (run from this directory)

- Start stack: `docker compose up --build -d --wait`
- Health: `curl http://localhost:8000/health/ready`
- Local lint, format check, and unit tests: `make check`
- Real-service integration checks after starting the stack: `make integration`
- Migrate database: `uv run --locked alembic upgrade head`
- Demo catalog: `make seed-demo`; H&M importer and dry run: see README.md
- Frontend build: `make web-check`; desktop/mobile browser checks: `make browser-check`
- Phase 3A prerequisite inventory: `make phase3-preflight`; core learning targets:
  `make phase3-exercises` (expected to fail at TODOs until implemented); see docs/PHASE3A.md
- Phase 3B MIND fixture: `make mind-fixture`; prerequisite inventory: `make phase3b-preflight`;
  opt-in CTR targets: `make phase3b-exercises`; see docs/PHASE3B.md for disposable setup.
- Phase 4 is implemented: docs/PHASE4.md and docs/PHASE4_WALKTHROUGH.md.
  `make phase4-preflight` is static; `make lens-evaluate` writes real CLIP/ANN evidence.
  Shared Phase 2 and Phase 4 core checks now run normally; Phase 3A training/3B CTR remain exercises.
- Setup and container-only checks: see README.md

## Non-negotiable conventions

- Keep ML components behind small swappable interfaces; add other boundaries as their revisit experiments need them (see PLAN.md, "Architecture principles").
- Every feed, search, or related-pins response carries a `request_id` and the model versions used.
- Returned items are served items; impressions are explicit client-reported views. Unseen items are not negative impressions.
- Event ingestion is idempotent on `event_id` across event types, with explicit conflicts and out-of-order reconciliation.
- App v1 learns engagement ranking from imported proxies and sampled negatives; MIND provides the separate observed-impression CTR exercise.
- Features and candidate availability must be correct at the example time; final display position is not a v1 ranking feature.
- Keep effective event/application time separate from wall-clock receipt and elapsed latency.
- Never hardcode which model variant runs; resolve it from config plus experiment assignment.
- Advertise only implemented simulator capabilities; start with isolated baseline reset and make full snapshots optional.
- Small commits, tests for logging and ranking code, migrations for every schema change.
