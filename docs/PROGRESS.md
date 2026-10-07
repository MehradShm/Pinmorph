# Implementation progress

## Phase 0 — complete

Implemented:

- Python 3.12 package and dependency lockfile.
- Compose services for Postgres/pgvector, Redis, MinIO, FastAPI, and RQ; one-time migration
  and media-bucket setup steps.
- Separate API liveness/readiness endpoints and request/error diagnostics.
- Alembic baseline enabling the vector extension; product tables remain phase 1 work.
- Seed command skeleton that emits a proposed manifest without writing data.
- Local checks, a CI workflow, and integration tests for migration, storage, and worker execution.

Validation on 2026-10-06:

- Python unit tests: 4 passed.
- Real-service integration tests: 4 passed (repeatable migration/pgvector, dependency
  readiness, object-storage round trip, and actual RQ job execution).
- Ruff lint passed; files formatted.
- Dependency lock validation and Docker Compose configuration validation passed.
- Alembic offline SQL generation and seed dry run passed.
- Docker Desktop installed with app-only installation (global binary links required an
  administrator password). Engine running; full Compose startup passed.
- Existing host Postgres and Redis use the standard ports; this project's published ports
  are 15432 and 16379, with corresponding application defaults and local environment settings.
- The worker exited after a Redis connection timeout during a long idle period. Added
  `restart: unless-stopped`, restarted it, and verified real job processing afterward.
- TestClient emits a non-blocking httpx deprecation warning; tests pass.

Phase 0 acceptance criteria are satisfied. Phase 1 implementation is recorded below.

Explain-back checkpoint:

1. Why can liveness return 200 while readiness returns 503?
2. Why is pinging Redis insufficient to show that background processing works?
3. Which data survives `docker compose down`, and why do migrations run separately from API startup?

Revisit experiment: observe a dependency/worker failure, then explain the symptoms and recovery.
The later simulator supplies repeatable workloads for this exercise.

## Phase 1 — core implementation validated; real H&M import pending

Implemented on 2026-10-07:

- Product migration: users, expiring sessions, pins/media state, boards, unique saves,
  import manifests, and provenance-bearing imported interactions.
- Signup/login/logout and current-user lookup; Argon2id hashes, hashed random session
  tokens, HttpOnly/SameSite cookies, origin checks, and owner authorization.
- Multipart image upload with byte/pixel/format validation; MinIO originals; asynchronous
  RQ resize/orientation/metadata removal; thumbnail/display variants; dominant color.
- Visible queued/processing/ready/failed states, owner retry after enqueue failure,
  bounded scheduled worker retries, and request/import IDs in job diagnostics.
- Ready/available catalog with cursor pagination; pin closeup/source link; API media delivery.
- Boards and idempotent saves/removals, including database enforcement for concurrent saves.
- React/TypeScript masonry UI with account/upload/board forms, processing status, closeup,
  saves/removal, and desktop/mobile layouts. nginx serves it on port 8080 with same-origin API.
- H&M importer accepting local articles/customers/transactions/images, deterministic
  subsampling and IDs, manifest hashing, original/effective dates, optional shared time
  offset, whole-day cutoff proposals, resumable imports, and credential-free seeded users.
- A separate demo seed: 32 locally generated catalog illustrations labeled `synthetic_demo`;
  no fake transaction history or app engagement/impression events.
- Frontend build/browser checks added to local commands and the configured CI workflow.
- Component/interaction explanation, API routes, limitations, and checkpoints in PHASE1.md.

Validation on 2026-10-07:

- Python unit tests: 17 passed (health diagnostics, actual image decoding, limits, EXIF
  orientation, transparency, corrupt/truncated images, reproducible seed/time manifests).
- Real-service integration tests: 12 passed (the Phase 0 checks plus accounts/session
  expiry/origins, worker/media path, ownership, repeated/concurrent saves, future-item
  exclusion, queue failure/manual retry, missing-object automatic retry, cursor pagination,
  and repeatable H&M-shaped fixture import with purchases kept separate from saves).
- Browser tests: 4 passed, Chromium desktop and mobile viewport profiles. Verified full
  signup/upload/processing/board/save/remove/logout/login loop, cookie persistence after
  reload, demo image decoding, shareable closeup, Escape dismissal, and viewport overflow.
- Ruff lint/format checks, TypeScript/static build, Compose startup, offline migration SQL,
  and Alembic model/schema drift check passed. CI is configured, not run on GitHub.
- Seeded the local catalog with 32 demo pins; every image reached ready. Manifest retained
  in `import_runs` and locally at `data/manifests/demo.json`. Exact disposable browser test
  accounts/objects are cleaned using recorded artifacts.
- Validation initially ran bulk demo seeding alongside integration tests. The single worker
  backlog caused two test deadlines to expire; logs showed continued job processing. Running
  the suite after seeding drained passed. Keep bulk imports separate from timed test runs.
- Node 20.1 could build Vite but could not load Playwright's TypeScript config; browser
  validation used a temporary Node 22 runtime. Container/CI frontend runtime is Node 22.
- TestClient still emits the non-blocking httpx deprecation warning from Phase 0.

Remaining acceptance item: the developer's actual H&M files have not been supplied. The
importer is implemented and tested against a small H&M-shaped fixture; a real-data import
and validation on those files remain pending. The current visible seed is explicitly demo
content. The working signup → upload → browse → board/save loop is ready to use now.

Phase 2 ranking/logging/experiments and the separate simulator remain unimplemented.

Explain-back checkpoint (also in PHASE1.md):

1. Why does upload return before a pin appears in the public catalog, and how does the UI
   learn that the worker finished?
2. How does the database prevent concurrent/retried saves from inflating a board's pin count?
3. Why must imported purchases stay distinguishable from app saves and impressions?

Revisit: resize on upload versus on demand; media delivery/CDN; transactional job outbox and
crash reconciliation; worker backlog under load. Operational baseline/failure exercises
will be formalized later using the simulator contract.
