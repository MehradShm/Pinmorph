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

Phase 2 has started with a learning scaffold, recorded below. The separate simulator
remains unimplemented.

Explain-back checkpoint (also in PHASE1.md):

1. Why does upload return before a pin appears in the public catalog, and how does the UI
   learn that the worker finished?
2. How does the database prevent concurrent/retried saves from inflating a board's pin count?
3. Why must imported purchases stay distinguishable from app saves and impressions?

Revisit: resize on upload versus on demand; media delivery/CDN; transactional job outbox and
crash reconciliation; worker backlog under load. Operational baseline/failure exercises
will be formalized later using the simulator contract.

## Phase 2 — started; learning core pending

Implemented on 2026-10-07:

- Local Git repository, `main` baseline, annotated `phase-1` checkpoint, and `phase-2`
  work branch. The checkpoint explicitly records the real H&M import as pending. No remote.
- Swappable CandidateSource/Ranker/Reranker contracts and explicit version registries.
- Validated feed/experiment configuration, complete bucket allocations, supported-version
  startup checks, and named exercises for deterministic bucketing and baseline ranking.
- Additive migration `ddac47bcc846`: feed requests, served items, complete feature snapshots,
  global event receipts, impressions, and engagements with pending/resolved references.
- Database constraints for served-item identity/position, global event IDs, one view per
  served item, and matching viewed user/request/pin/position.
- Authenticated `/api/feed` and `/api/events` route wiring, payload schemas, origin checks,
  and server UTC. Reject simulator override headers and untrusted event-time/user/run fields.
  Pending learning services return an explicit correlated 503, never success.
- Read-only feed inspection command, opt-in learning tests, PHASE2 implementation guide,
  milestone/worktree instructions, and a historical Phase 1 environment/image override.

Validation on 2026-10-07:

- Unit checks: 32 passed; 6 ranking/assignment exercise targets skipped by default.
- Real-service checks: 18 passed (12 existing plus 6 Phase 2 schema constraint checks).
- Browser regression: 4 passed on Chromium desktop/mobile viewports against the updated
  stack. The Phase 1 signup/upload/board/save/remove/sign-in and demo browsing still work;
  exact recorded disposable accounts and media were cleaned afterward.
- Compose build/start and schema upgrade passed; Alembic drift check reports no changes.
- Ruff lint/format and TypeScript/static build passed.
- Eleven opt-in learning targets intentionally fail at LearningExercisePending. They are pending
  acceptance work, not successful logging/ranking validation.
- The deployed read-only inspector returns not_found/exit 2 for an unknown request.
- Created a detached Phase 1 worktree and verified its merged historical Compose config
  has separate project volumes, app/web images, and ports. The historical stack was not started.

Remaining: stable bucketing, both baseline rankers, point-in-time feature queries, feed
orchestration/atomic snapshots/pagination, event ingestion/idempotency/reconciliation, UI
viewport instrumentation and action telemetry, and concurrency/browser acceptance tests.
The current UI remains the working Phase 1 catalog; no production-like simulator capability
is advertised. Phase 2 is not complete and has no completion tag.

The exact five named core exercises, expected fixtures, interaction diagram, alternatives,
and explain-back questions are in PHASE2.md. Explain-back outcomes remain pending.

## Phase 3A — started; ML scaffold ready, core pending

Implemented on 2026-10-07:

- `phase-2-scaffold` annotated checkpoint and active `phase-3a` branch; no Phase 2/3A
  completion tag and no GitHub remote publication.
- PinEmbedder/UserEmbedder contracts and typed finite vectors, aware-time histories,
  interactions, target-action provenance and training examples.
- Configured CLIP/image-title recipe, decayed user mean, candidate quotas, and diversity
  policy; explicit positive/sampling/source/time/split/evaluation manifests.
- Additive vector schema `cdfce4ed4eea`: model metadata, content/model revision keys,
  consistent dimensions, unit-norm constraints and availability timestamps.
- Locked pgvector Python adapter and NumPy; variable-dimensional storage verified.
- Validated/checksummed JSON logistic artifacts with ordered features, train-only scaling
  and provenance, atomic publication and no-overwrite behavior.
- Explicit exercises for embeddings, exact/ANN retrieval, candidate blend, temporal splits,
  implicit examples, fitting, scoring, reranking and offline metrics. No fake vectors or scores.
- Read-only prerequisite inventory, opt-in ML targets, PHASE3A guide and decision records.

Validation on 2026-10-07:

- Unit checks: 45 passed (32 existing plus 13 artifact/config/provenance/inventory checks).
- Real-service checks: 24 passed (18 existing plus 6 pgvector schema/roundtrip checks).
- Browser regression: 4 passed on Chromium desktop/mobile against the updated stack;
  exact recorded disposable accounts and media were cleaned afterward.
- Compose build/start and additive migration passed; Alembic schema drift check passed.
- Ruff lint and formatting passed.
- Sixteen opt-in Phase 3A core targets fail at LearningExercisePending, as intended. These
  are unfinished acceptance targets, not a successful retrieval/training/evaluation result.
- Database inventory: 32 ready demo pins; zero imported interactions, feed requests,
  impressions, engagements, embedding model registrations, and persisted embeddings.
- Read-only inventory saved locally at `data/manifests/phase3-scaffold-preflight.json`
  (ignored by Git); it is an inventory record, not a state snapshot or model report.
- Torch, OpenCLIP, sklearn and MLflow are not installed. No weights, trained models, ANN
  indexes, personalized feed, MLflow run or offline quality comparison exist yet.

Phase 2's core and UI instrumentation remain prerequisites for end-to-end personalization.
Core ML learning implementation, real declared history, runtime/checkpoint pinning, embedding
jobs, ANN recall/latency measurements, model fitting/evaluation and serving activation/rollback
remain pending. Pure fixture exercises can proceed before the complete serving path.

PHASE3A.md records the twelve exercise groups, component flow, alternatives and explain-back
questions. Explain-back and baseline comparison outcomes remain pending; the separate simulator
and Phase 3B CTR/operations track are not implemented by this scaffold.

## Phase 3B — started; CTR core and minimum adapter pending

Implemented on 2026-10-07:

- Preserved `phase-3a-scaffold` annotated checkpoint and active `phase-3b` branch;
  no Phase 3A/3B completion tag and no remote publication.
- Independent MIND CTR contracts, source-time/provenance manifest and four-feature artifact
  format. Shared immutable byte publication preserves separate app/CTR model schemas.
- Strict local news/behavior TSV reader and read-only inventory, including whole impression
  identity, observed/hidden labels, source-partition namespaces, explicit time-zone assumption,
  input hashes/change detection, empty history and missing-history metadata counts.
- Seven explicit CTR exercise groups and fifteen opt-in known-answer targets. Core algorithms
  raise Phase 3B LearningExercisePending; no model or quality report is fabricated.
- Thread-safe process request/status counters and cumulative latency buckets with route
  templates; read-only DB/queue/worker diagnostics with explicit partial failure.
- Disposable-mode/control-authenticated `/sim/capabilities` and `/sim/diagnostics`. Only
  diagnostics are advertised; unsupported controls return 501, normal-mode controls 404.
  Normal `/api` routes reject all X-Sim-* headers until attribution exists.
- Private immutable disposable environment files, baseline descriptor/run payload schema,
  separate Compose setup/read-only baseline mount, guarded initial baseline seed and
  authenticated loopback observation export. Initial seed is explicitly not reset.
- Phase 3B guide, operations exercise worksheet, decision records and commands; Phase 3B
  TODOs excluded from the independent Phase 3A prerequisite inventory.

Validation on 2026-10-07:

- Unit checks: 77 passed (45 existing plus 32 CTR/diagnostics/control/setup/export checks).
- Real-service checks: 25 passed (24 existing plus read-only DB/worker diagnostics).
- Browser regression: 4 passed on desktop/mobile; exact recorded disposable accounts
  and media cleaned afterward.
- Fifteen opt-in CTR targets fail at their named pending exercises; these are unfinished
  acceptance targets, not passing CTR fitting/evaluation checks.
- Synthetic fixture inventory: four news articles, four groups, eight displayed candidates,
  three clicks/five nonclicks; empty history, tied timestamps and missing history metadata.
- Disposable merged Compose config verifies separate project, all three stores, ports,
  app/web image names and read-only baseline mount. Both stacks started healthy.
- Initialized declared `pinmorph-sim-lab` baseline via normal media jobs: 32 ready demo pins,
  zero queued jobs, worker heartbeat present. Real control auth and unsupported reset/run
  header behavior verified. No scenario run, reset or operational diagnosis is claimed.
- Observation exported locally to `data/simulator/observations/baseline.json`; private setup
  and baseline files at `data/simulator/pinmorph-sim-lab`. All are ignored by Git.
- Final guarded seed retry preserved the same 32-pin import without new jobs; its ID is
  explicitly import_run_id. Final evidence is at `data/simulator/observations/final-baseline.json`.
  The disposable validation stack was stopped retaining its volumes/control/evidence files.
- Normal app refreshed and healthy; simulation controls disabled. No schema migration or
  ML runtime install/download was needed.

Remaining: actual MIND files and pinned sklearn/MLflow runtime; all CTR core algorithms,
reproducible baseline/held-out quality comparison and explain-back. The minimum simulator
run/users/catalog/recommendations/events adapter, mutation/job attribution and quiescent
baseline reset remain pending on earlier services. Logical time, snapshot/model/train
controls are unsupported. The separate simulator is not built here. Phase 4 has not started.

## Phase 4 — first product modules implemented; discovery core pending

Implemented on 2026-10-07:

- Preserved `phase-3b-scaffold` and started `phase-4`; earlier learning milestones remain
  unfinished. This is the first independent product milestone, not the entire Phase 4 scope.
- PostgreSQL English keyword search over title/description with generated tsvector/GIN,
  prefix title suggestions, owner/provenance/aware-date filters, recency ordering and
  query/filter-bound keyset pagination. A swappable search protocol returns request/backend
  versions; served-item/impression attribution remains a Phase 2 dependency.
- Public display-name/bio profiles, profile editing, name lookup and paginated connections,
  public board/ready-pin APIs; public output excludes email/authentication/import keys.
- Durable user/board follows, block/mute controls, shared visibility policy and transactional
  in-app follow notifications. Ordered user locks serialize concurrent relationship changes;
  board follows re-read locked publication state. Blocks remove cross-user follows/notices.
- Secret/public boards and sections. Existing boards stay secret; publishing is explicit.
  Public reads respect privacy/availability/block policy, including own-board counts.
  Same-board save/section membership is enforced by a deferred composite FK; deleting a
  section clears its assignment without removing saved pins. Authenticated media is no-store.
- Working UI for search/collection filters, People, profile editing, public boards/follows,
  activity/read acknowledgments, unblock/unmute, board publication/sections and creator links.
- Validated transient Lens crop preparation: image limits, EXIF orientation, normalized
  region, RGB/alpha flattening, metadata removal and source/crop hashes.
- Typed Following/related/crop encoder/Lens interfaces and versioned registry/config selection
  at startup, including DISCOVERY_CONFIG passthrough in Compose. Five core TODO groups and
  six opt-in Lens targets remain pending; no inference or fake retrieval results are served.
- Additive migration `d12ac1433a55`, readiness revision update, PHASE4 guide, prerequisite
  inventory, commands, roadmap, decision records and historical-checkpoint instructions.

Validation on 2026-10-07:

- Unit checks: 103 passed (77 existing plus 26 search/crop/config checks); core exercises skipped.
- Full real-service checks: 33 passed (25 existing plus seven Phase 4 API/race/privacy checks
  and one disposable migration test). Affected Phase 4 checks also passed after final
  registry/visibility changes. Additional assertions confirm search creates no ML impressions
  and valid Lens input reaches the explicit pending service.
- Fresh disposable database upgraded from Phase 3A with real legacy user/board/save/pin rows:
  old boards remained secret, bios defaulted empty, existing pins became searchable, and
  section deletion preserved saves. Downgrade/re-upgrade passed; that exact database was removed.
- Six browser checks passed: original core/seed flows plus Phase 4 search/profile/board-section/
  user-follow/board-follow/activity flows on Chromium desktop/mobile. No page errors or
  horizontal overflow. Six exact recorded test accounts and their media were cleaned afterward.
- Ruff lint/format, TypeScript/Vite build, additive migration and schema drift comparison passed.
  The normal stack is running and ready with its original 32 demo pins retained.
- Six opt-in Lens targets fail at the intended pending TODOs. Static inventory lists all
  five Phase 4 core groups and earlier serving dependencies; these are not ML acceptance.

Remaining Phase 4: actual Following/related serving and attribution, pinned crop inference,
exact/ANN corpus/latency/relevance comparisons and explain-back; interest onboarding, URL
import, comments/reactions/hide/report, digest email, moderation/classifier/duplicate gate
and richer profile/settings. Secret membership does not imply private pins. Preference
lists currently show the first 100 blocked/muted users each. Simulator capability remains
diagnostics-only; the earlier minimum run adapter/reset and CTR work are still pending.

## 2026-10-07 — finish Phase 4 implementation

Completed shared baseline serving/assignment/features and event receipt/reconciliation;
Following, public co-board related discovery and same-recipe similarity fallback; pinned
CPU CLIP crop inference, immutable catalog vectors, exact/HNSW retrieval and evaluation;
optional interest onboarding/settings; bounded public direct-image import; comments/likes/
share/hide/report; broader in-app activity; local SMTP daily outbox/scheduler; upload
classification holds, pixel duplicates and moderator-only review/preview.

The implementation guide, core walkthrough and revisit decisions are recorded. Default
Phase 2/4 core checks now execute normally. Separate Phase 3A training and Phase 3B CTR
learning targets are preserved. Explain-back discussion has not been assumed complete.
Final acceptance counts and the real Lens result are recorded in docs/reports/phase4-checks.json
and docs/reports/phase4-lens.json. The 32-pin demo catalog and earlier isolated states are
retained; generated validation accounts/media are cleaned by exact fixture identity.
