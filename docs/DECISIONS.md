# Decision log

One entry per significant choice. Format: date, decision, why, alternatives considered,
what would make us revisit it. These entries double as interview prep notes.

## 2026-10-02 · Simulator is a separate, reusable project
- **Why:** reuse across several projects; keep this repo focused on the product and ML.
- **Alternatives:** a simulator embedded in this repo (faster to start, but not reusable).
- **Revisit if:** the contract turns out too limited for a project's needs.

## 2026-10-02 · Log impressions with request ID and position from phase 2
- **Why:** CTR needs negatives; position bias and model attribution need position and versions.
- **Alternatives:** logging only clicks and saves (cheaper, but blocks CTR modeling).
- **Revisit if:** storage volume becomes a problem; sample impressions then.

## 2026-10-02 · Python/FastAPI backend with Postgres + pgvector
- **Why:** the ML code and the serving code share one language; pgvector avoids running a separate vector database early.
- **Alternatives:** Node backend with Python ML service; FAISS or a dedicated vector DB.
- **Revisit if:** ANN latency or recall becomes a bottleneck (planned Lens experiment).

## 2026-10-06 · Finish the core personalized feed before broad product features
- **Decision:** phases 0–3A end with a seeded, observable, personalized feed and reproducible baseline evaluation. Move search, social features, and other product extras to later phases; MIND and simulator exercises form subsequent learning tracks.
- **Why:** reach the project's main MLE learning outcome sooner while retaining the full product roadmap.
- **Alternatives:** complete the broader Pinterest feature set before evaluating ML v1.
- **Revisit if:** a specific deferred feature becomes necessary for an ML experiment or core-loop usability.

## 2026-10-06 · Separate served items from explicit view events
- **Decision:** store returned lists in `served_items`; impressions have event IDs, timestamps, and request attribution. V1 counts one view per served item after 50% card visibility for one continuous second. Use the same rule for the UI and simulator.
- **Why:** returned but unseen items must not become negative impression examples. This refines the 2026-10-02 logging decision. At v1 scale, retain all served feature snapshots.
- **Alternatives:** count every returned item as viewed; infer views from clicks; sample feature snapshots immediately.
- **Revisit if:** UI layouts require a different view rule or volume requires a documented sampling policy; version the change.

## 2026-10-06 · Treat imported-feedback ranking and observed-impression CTR as distinct tasks
- **Decision:** app v1 uses an engagement ranker with imported proxy saves and sampled negatives. MIND provides the separate CTR exercise. Dataset manifests record provenance, candidate universe, and negative sampling policy.
- **Why:** unobserved items are not confirmed non-clicks, and sampled-label probabilities do not establish real CTR.
- **Alternatives:** describe the app's first logistic-regression model as a calibrated CTR predictor; wait for observed app traffic before building a ranker.
- **Revisit if:** enough suitable observed impressions exist for an explicit CTR objective; preserve the distinction between synthetic and manually observed events.

## 2026-10-06 · Make temporal correctness explicit and defer position-bias modeling
- **Decision:** use chronological splits plus point-in-time histories, features, and candidate eligibility. Record import/reference time and separate effective time from receipt time. Log final position but exclude it from v1 ranking features.
- **Why:** a chronological split alone does not prevent future-derived features; final display position is an output of ranking.
- **Alternatives:** compute aggregate features over the full dataset; include historical position without defining its serving-time meaning.
- **Revisit if:** adding a position-bias model or more realistic event-time handling, with a specified training/serving policy and evaluation.

## 2026-10-06 · Use the simulator to practice production operation
- **Decision:** the separate simulator supplies sessions, traffic bursts, delivery anomalies, and failure/recovery scenarios. The product supplies normal application paths, an adapter, and diagnostic telemetry. Scripted behavior is enough initially.
- **Why:** the developer wants practical experience operating a system without having had production exposure. Preference modeling is optional; operational diagnosis and recovery are the primary outcomes.
- **Alternatives:** prioritize realistic preference modeling and interpret simulated engagement lift as evidence of real-user benefit; embed load/scenario logic in this repo.
- **Revisit if:** a later learning objective specifically requires richer behavioral or preference models.

## 2026-10-06 · Start simulation with isolated baseline reset and explicit capabilities
- **Decision:** one active run per disposable environment, with a recorded baseline, run manifest, and reset covering database, Redis/jobs, run-created objects, derived features, and pinned artifacts. Full snapshot/restore, accelerated logical time, and remote model/training controls are optional extensions.
- **Why:** define repeatability without promising to restore unspecified state or requiring all future controls up front. Event timestamps alone do not create a coherent accelerated system clock.
- **Alternatives:** mandatory arbitrary snapshots from the start; delete tagged event rows while leaving other run effects behind.
- **Revisit if:** baseline rebuilding becomes expensive, concurrent runs are needed, or a concrete exercise needs a declared optional capability.

## 2026-10-06 · Pair learning checkpoints with evidence
- **Decision:** each ML checkpoint names a baseline or invariant and explain-back outcome. Each operations exercise records expected behavior, observations, diagnosis, and recovery; stable experiment assignment uses a specified digest/version.
- **Why:** reproducible comparisons and explainable failures turn implementation into interview-ready understanding.
- **Alternatives:** declare modules complete when they execute, without evaluating or explaining their behavior.
- **Revisit if:** a checkpoint becomes busywork; simplify it while retaining a concrete demonstration of understanding.

## 2026-10-06 · Scaffold phase 0 as one Python application image plus local services
- **Decision:** Python 3.12 and a uv lockfile; one image runs FastAPI, RQ, migrations, and bucket setup as separate Compose services. Product tables and the frontend arrive in phase 1; heavyweight ML packages arrive with their modules.
- **Why:** the first infrastructure checkpoint should be small enough to understand and run locally. A single codebase keeps worker and API imports consistent.
- **Alternatives:** create separate ML services now; install the entire future ML stack before a model exists.
- **Revisit if:** measured worker resource needs or independent deployment requirements justify separate images/services. Related backlog: single-database versus partitioned infrastructure.

## 2026-10-06 · Distinguish liveness, readiness, and worker execution
- **Decision:** `/health/live` checks API responsiveness; `/health/ready` reports database/migration, Redis, and authenticated media-bucket checks. Integration tests separately execute a real JSON-serialized RQ job and an object-storage round trip. Basic access logs carry request ID, status, and duration.
- **Why:** an alive API can still have unavailable dependencies; a working Redis connection does not prove a worker can run jobs. Operational access diagnostics support phase 0 while recommendation/event logging remains a phase 2 learning task.
- **Alternatives:** a single unconditional health response; infer worker health from Redis alone.
- **Revisit if:** the product needs partial readiness/fallback, deeper metrics, or independent worker heartbeat checks. Related backlog: failure diagnosis and backpressure under simulated workloads.

## 2026-10-06 · Keep MinIO locally using its pinned upstream source release
- **Decision:** build `RELEASE.2025-10-15T17-29-55Z` in `infra/minio/Dockerfile`; bind the local stack to loopback and keep application storage access S3-compatible.
- **Why:** the upstream community repository is archived and its final tagged release directs container users to build from source. This preserves the planned local storage choice without relying on an older prebuilt release.
- **Alternatives:** immediately change to another S3-compatible server; use an older MinIO image.
- **Revisit if:** build/maintenance cost becomes a distraction or deployment beyond the learning environment is planned. Related backlog: object-storage/media strategies. [Upstream release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z).

## 2026-10-06 · Restart the local worker after a connection timeout
- **Decision:** give the RQ worker the Compose `unless-stopped` restart policy.
- **Why:** validation found that RQ exited with status 0 after a Redis connection timeout during a long idle period. An `on-failure` policy would not recover that process.
- **Alternatives:** restart it manually; change RQ connection/retry internals before the first infrastructure milestone.
- **Revisit if:** operational exercises require a more explicit supervisor, backoff, or worker availability policy.

## 2026-10-07 · Use opaque cookie sessions for basic authentication
- **Decision:** Argon2id password hashes, random session tokens, hashed token lookup in Postgres, seven-day expiry, logout revocation, HttpOnly/SameSite cookies, and explicit browser Origin checks. Imported customers have no credentials.
- **Why:** the browser can log in without handling bearer tokens, and a database session is easy to inspect and revoke while learning.
- **Alternatives:** signed stateless tokens; an external identity provider.
- **Revisit if:** external clients or deployments require delegated identity, account recovery, or a different session store. Local HTTP requires non-Secure cookies; HTTPS must enable `COOKIE_SECURE`.

## 2026-10-07 · Prepare media asynchronously and serve derivatives through the API
- **Decision:** accept static JPEG/PNG/WebP up to 12 MB / 24 megapixels; validate bytes, store originals, enqueue JSON RQ jobs, and generate 400/1200px JPEG variants plus dominant color. Respect orientation and strip displayed metadata. Only ready, available pins enter the public catalog. Carry request/import IDs into jobs.
- **Why:** uploads have explicit queued/processing/ready/failed states, and expensive processing is observable independently of API requests. API media paths keep internal storage URLs and credentials out of the browser.
- **Alternatives:** synchronous resize; on-demand transformations; direct signed uploads and signed derivative URLs/CDN.
- **Revisit if:** media throughput or API bandwidth becomes limiting. Related experiment: resize on upload versus on demand; direct object access versus API delivery.

## 2026-10-07 · Support enqueue recovery and bounded worker retries
- **Decision:** failed enqueues return 503 and leave an owner-retryable failed upload. Worker jobs retry three times with 2/5/10-second delays and an enabled scheduler. Each attempt has an active job ID; retry requests lock the pin row. API readiness requires the current migration revision. nginx refreshes Docker DNS so replacing the API container does not leave a stale upstream address.
- **Why:** failure is visible, a new attempt can supersede old work, and the learning stack can recover from ordinary temporary failures. Real-service tests verify both enqueue failure/manual retry and a missing object restored before an automatic retry.
- **Alternatives:** one attempt with manual database repair; a transactional outbox and reconciliation loop immediately.
- **Revisit if:** an exercise covers crashes between database commit and enqueue, killed workhorses, or sustained backlog. Those cases need explicit reconciliation/outbox work; this phase does not claim complete crash recovery.

## 2026-10-07 · Let database constraints define save idempotency
- **Decision:** boards belong to their creator; the current API checks ownership for reads/writes. A unique `(board_id, pin_id)` constraint makes repeated/concurrent saves return the existing save, and removing an absent save succeeds.
- **Why:** repeated requests do not inflate the product state; concurrency correctness belongs in the database rather than a prior existence check.
- **Alternatives:** client-only deduplication; read-then-write without a constraint; event ingestion driving saves from the start.
- **Revisit if:** public/private board features or Phase 2 action events change the API. Product-state idempotency is not a substitute for global event-ID idempotency.

## 2026-10-07 · Import H&M with explicit provenance and immutable manifest namespaces
- **Decision:** deterministic catalog/customer sampling, stable IDs per hashed manifest, full CSV and selected-image hashes, original/effective dates, reference time, optional single global offset, and proposed whole-day cutoffs. Purchases remain `imported_interactions` with `imported_purchase_proxy` provenance; no app saves/impressions are manufactured. Publication time is unavailable, so item availability is an explicit earliest-purchase proxy, otherwise reference time.
- **Why:** imports can resume without duplicates and later datasets can identify their exact input/time assumptions. Different policies/manifests create separate namespaces instead of mutating an existing history.
- **Alternatives:** generate fake observed events; silently overwrite shifted timestamps; merge source identities across incompatible import policies.
- **Revisit if:** source publication metadata becomes available or source-global identities are needed. Keep namespaces separate in later training unless a merge policy is declared.

## 2026-10-07 · Provide a labeled demo while the real dataset is unavailable
- **Decision:** seed 32 locally generated illustrations through the normal media pipeline, with `synthetic_demo` provenance and a visible Demo badge. Build and test the H&M importer using a small H&M-shaped fixture until the developer supplies their local files.
- **Why:** the signup/upload/browse/save loop can run now without pretending a real H&M import has occurred.
- **Alternatives:** block all product validation on downloading the dataset; distribute dataset images with the repo.
- **Revisit if:** local H&M files are supplied. Real-data acceptance remains pending; demo data contains no proxy interaction history.

## 2026-10-07 · Keep the UI and verification reproducible
- **Decision:** React/TypeScript, CSS columns, Vite, and nginx same-origin `/api` delivery; npm lockfile and Node 22 container/CI runtime. Test the full flow in Chromium on desktop and mobile viewport profiles and clean exact recorded disposable accounts.
- **Why:** the planned functional UI supports the learning loop; browser checks verify cookies, multipart upload, dialogs, media delivery, and persistence beyond API-level tests.
- **Alternatives:** frontend/backend cross-origin hosting; a UI framework before core paths exist; API-only validation.
- **Revisit if:** richer routing/accessibility or deployment needs arise. Browser mobile profiles emulate viewports, not a real mobile device. The installed Node 20.1 builds Vite but cannot load current Playwright's TypeScript configuration; validation used a temporary Node 22 runtime. [Vite 6 guide](https://v6.vite.dev/guide/), [Playwright installation](https://playwright.dev/docs/intro), [RQ retry/scheduler requirement](https://python-rq.org/docs/exceptions/).

## 2026-10-07 · Preserve historical code separately from application state
- **Decision:** initialize local Git, keep Phase 1 as an annotated `phase-1` tag, and work on `phase-2`. Provide worktree instructions and a historical Compose override with separate project volumes/network, host ports, and app/web image tags. Keep data and secrets outside Git.
- **Why:** the developer can inspect an earlier phase while later phases evolve. Code tags do not restore database schemas, queues, or media. The historical tag explicitly retains the pending real H&M acceptance item.
- **Alternatives:** moving checkpoint branches; switching current code while sharing one database; committing generated data or environment secrets.
- **Revisit if:** measured experiments require full state snapshots. Rebuilding a seeded demo baseline is sufficient for historical product inspection; no Phase 0 snapshot was reconstructed and no GitHub remote was published.

## 2026-10-07 · Scaffold the Phase 2 learning path before implementing its core
- **Decision:** implement data schemas/migration, versioned contracts/registries/config, strict payload validation, API wiring, inspection, and opt-in executable targets. Preserve Learn mode for assignment, ranking, features, serving persistence, and event ingestion. Pending services explicitly return 503; the UI continues the Phase 1 path.
- **Why:** WORKING_AGREEMENT.md leaves core ML/logging/experiment logic to the developer unless they ask for it to be written. Ordinary scaffold checks must not imply that view attribution or retries work end to end.
- **Alternatives:** silently write the learning core; return stub success; disable tests without documenting acceptance targets.
- **Revisit if:** the developer explicitly requests core implementation; then implement and walk through it as the agreement allows.

## 2026-10-07 · Design transactional serving records and a global event ledger
- **Decision:** use Postgres for atomic serving snapshots and event receipts; give impressions unique served-item identity and composite attribution constraints. Keep requested versus resolved impression IDs separate for out-of-order actions. Retain the original normalized event payload for exact retries and duplicate-view aliases. Use server UTC for normal traffic; reject simulator time/run overrides until the adapter exists.
- **Why:** request attribution, concurrency, retries, and delayed events need explicit identities and transaction boundaries. Returning an item is distinct from viewing it, and imported proxies stay separate from observed actions.
- **Alternatives:** fire-and-forget access logs; event IDs unique only per type; serving-generated impressions; a queue/log bus from the start.
- **Revisit if:** ingestion throughput requires an event bus, label materialization introduces lateness policies, or run-scoped logical time is implemented. This entry describes the schema/contract; ingestion and request-persistence core logic remain exercises.

## 2026-10-07 · Specify an honest baseline comparison and stable experiment algorithm
- **Decision:** recency score = negative age in hours; popularity score = distinct prior saving users plus distinct prior purchasing users, each provenance separately snapshotted and equally weighted. Occurrence and receipt must both precede the feature cutoff. All-zero popularity falls back to recency. Stable assignment uses the documented SHA-256 JSON/byte/bucket algorithm with golden vectors, versioned salt and complete arm allocations.
- **Why:** deterministic, inspectable baselines make later model experiments comparable. Purchase proxies are not observed CTR, and information arriving late cannot be used earlier. V1 full-catalog retrieval is explicit at demo scale.
- **Alternatives:** popularity from current board membership; silently merge purchases and observed saves; process-dependent hashes; bounded retrieval before coverage is measured.
- **Revisit if:** scale motivates SQL shortlists, different source weights, or personalized models. These algorithms remain marked core exercises until implemented and reviewed.

## 2026-10-07 · Start Phase 3A while preserving unfinished Phase 2 dependencies
- **Decision:** preserve `phase-2-scaffold` as an annotated checkpoint and develop the Phase 3A ML scaffold on `phase-3a`. Keep Phase 2 and Phase 3A core algorithms as Learn-mode exercises. Generalize pending-exercise errors to identify the phase. No completion tag or personalized-serving claim.
- **Why:** pure ML correctness exercises and storage/artifact work can proceed independently, while end-to-end serving still requires the earlier feed/logging path. WORKING_AGREEMENT.md says the developer writes the core unless they request otherwise.
- **Alternatives:** treat Phase 2 scaffolding as completed; silently implement the learning core; block all independent Phase 3A work until telemetry is complete.
- **Revisit if:** the developer requests core implementation, or all prerequisite acceptance checks pass. Phase 3B remains a separate MIND/operations track.

## 2026-10-07 · Version embeddings and preserve content revisions
- **Decision:** model metadata records checkpoint hash, dimension, preprocessing/text/fusion policy and library versions. Pin vectors are keyed by pin/model/content hash, constrained to matching model dimensions and unit norm. Use unbounded pgvector storage so new dimensions can coexist; version-specific HNSW indexes and retrieval remain exercises. Lock the pgvector Python adapter; do not download ML weights or install Torch/OpenCLIP/sklearn/MLflow merely to execute schema checks.
- **Why:** different embedding models are different spaces, and overwriting content revisions would erase the information needed for point-in-time replay. Toy storage checks establish database behavior, not CLIP inference or ANN recall.
- **Alternatives:** one mutable vector column on pins; one fixed dimension for all experiments; mix models in one ANN index.
- **Revisit if:** measured scale warrants separate tables/partitions or index changes. The future embedding writer must enforce insert-only revision semantics; schemas do not prevent arbitrary SQL updates. [pgvector mixed-dimension guidance](https://github.com/pgvector/pgvector#can-i-store-vectors-with-different-dimensions-in-the-same-column).

## 2026-10-07 · Make source replay and live availability explicit
- **Decision:** training manifests declare exact import runs, chronological cutoffs/ties, positive target (purchases and saves), source weights, negative universe/seed, embedding/feature versions, and fixed-model evaluation policy. Permit historical source replay only for imported proxies; live/observed/simulator history uses recorded receipt availability. Source adapters and feature/example builders remain learning core.
- **Why:** the local import happens long after the source interactions. An offline historical replay can use source chronology under a declared assumption, while an old occurrence time cannot move a late live event's availability backward. Closeups/source clicks can inform history but are not the v1 positive target.
- **Alternatives:** use current mutable state for historical features; silently rewrite live receipt times; pool all sources or actions without provenance/weights.
- **Revisit if:** observed-impression datasets or richer simulation time modes are implemented; those require their own label and lateness policies.

## 2026-10-07 · Use inspectable model artifacts and known-answer ML checkpoints
- **Decision:** validate and publish checksummed JSON logistic artifacts with ordered features, train-only scaling, coefficients, manifest and library versions. Publication is atomic and refuses replacement. Keep scoring/fitting and metric computation as exercises, compare exact/ANN and recency/popularity under fixed candidate policies, and expose a read-only static/runtime/data inventory.
- **Why:** serving must use the same feature order/transform as training, and model experiments need attributable, pinned artifacts. Empty history, ties, late events, unknown creators and sampled-unobserved labels need explicit correctness targets before evaluating quality.
- **Alternatives:** opaque mutable pickle artifacts; fit transforms during serving; fabricate scores/metrics for a demo; treat removed TODOs as proof of acceptance.
- **Revisit if:** LightGBM/neural models need a different artifact format, or MLflow-backed model rollout is implemented. Artifact tooling does not imply that a model has been trained or activated.

## 2026-10-07 · Keep the MIND CTR study independent of the app's proxy task
- **Decision:** separate `app/ctr` contracts, local TSV reader, manifest and four-feature logistic artifact; preserve every observed displayed label and impression group. Keep splitting, features, example construction, fitting, scoring and metrics as named Learn-mode exercises. Compare against the training-period constant click rate before trying a tree model.
- **Why:** app proxy positives/sampled negatives and MIND source click labels define different tasks. Shuffled candidate order is not display position, and hidden public-test labels cannot become zeros. Infrastructure checks and invented fixtures do not establish model quality.
- **Alternatives:** reuse the app implicit-feedback artifact; subsample nonclicks without changing calibration/evaluation policy; split candidate rows randomly.
- **Revisit if:** actual model fitting/real-data comparison is complete, or explicit sampling, content encoders, or calibration experiments are added. [Official source format](https://github.com/msnews/msnews.github.io/blob/master/assets/doc/introduction.md).

## 2026-10-07 · Declare source-time assumptions and preserve partition history
- **Decision:** require an explicit IANA source zone, record it as an assumption, reject DST ambiguity/nonexistent times, namespace impressions by source partition, and preserve provided pre-impression history. Report missing history metadata without filling it from later partitions. Inventory records hashes and detects changed inputs; it does not fit anything.
- **Why:** MIND timestamp strings have no offset and source history entries have no individual timestamps. Guessing receipt times, decay, article publication age or chronological order would create unsupported features and leakage assumptions.
- **Alternatives:** silently assume local/UTC time; pool train/dev history into a mutable per-user lookup; infer labels or prior history from current/future clicks.
- **Revisit if:** authoritative source-zone or richer history/publication metadata is supplied. Whole-group time cutoffs and a protected final period remain required.

## 2026-10-07 · Expose read-only operation evidence before advertising simulator traffic
- **Decision:** process-local request counters/cumulative latency buckets use route templates and status classes. Control-authenticated diagnostics report database counts, queue-head age and worker heartbeats, with partial failures and bounded sampling. Read worker hashes and registry cardinality without RQ cleanup side effects. Capabilities advertise diagnostics only; unsupported controls return 501, normal-mode controls return 404, and normal APIs reject simulation headers.
- **Why:** the earlier feed/event core and run/job attribution are unfinished. Operational telemetry can work now without pretending a scenario, reset, CTR result or personalized feed has run. RQ convenience reads can mutate stale registrations/registries.
- **Alternatives:** return stub successes; advertise the contract's example capabilities; unbounded item/user metric labels; assume local histograms are persisted per-run measurements.
- **Revisit if:** a measured workload requires persistent multi-process metrics, richer ingestion/freshness telemetry, or a completed adapter with active-run attribution. Related backlog: backpressure, retries and feature freshness.

## 2026-10-07 · Prepare an isolated baseline without conflating initial seed and reset
- **Decision:** preserve `phase-3a-scaffold` and work on `phase-3b`. Generate private disposable environment/config files and a checksummed baseline descriptor outside named stores. A separate Compose project uses distinct ports/application images/volumes/network and mounts the descriptor read-only. Initial seed verifies environment/config/hash and delegates to the existing importer/media jobs; observation export verifies loopback environment identity and publishes immutable evidence. Minimum run adapter/reset remains pending.
- **Why:** the developer can rehearse infrastructure operation while earlier learning core is unfinished. Resuming an importer does not quiesce old jobs, restore all state, close a run or preserve a reset receipt. No destructive reset is exposed without those guarantees.
- **Alternatives:** share development stores; overwrite the baseline on each attempt; call reseeding a reset; embed workload/fault orchestration in this product.
- **Revisit if:** Phase 2 acceptance permits the minimum adapter. Reset needs durable run/receipt records outside application state, a worker write barrier and interrupted-retry acceptance; logical time/model/snapshot controls remain later extensions.

## 2026-10-07 · Start Phase 4 with independent product modules
- **Decision:** preserve `phase-3b-scaffold`, work on `phase-4`, and implement keyword search, public profiles, social relationships, secret boards/sections and in-app follow activity first. Keep Following/related/Lens algorithms as five explicit Learn-mode exercise groups. Other Phase 4 extensions remain pending.
- **Why:** these standard product modules can work independently of unfinished Phase 2/3A/3B learning acceptance. A newer branch must not imply earlier algorithms, model quality or simulator readiness are complete.
- **Alternatives:** stop all product work until the first ML finish line; silently implement core algorithms; label the whole phase complete after scaffolding.
- **Revisit if:** the developer explicitly requests core ML implementation. Then implement and walk through it under WORKING_AGREEMENT.md. See PHASE4.md for remaining scope and acceptance.

## 2026-10-07 · Use PostgreSQL keyword matching before a dedicated search engine
- **Decision:** generated English title/description tsvector plus GIN, parameterized plain queries, bounded last-token prefix suggestions, deterministic recency/ID ordering and query/filter-bound keyset cursors. Put search behind a small backend protocol and return request/backend versions.
- **Why:** the existing database supports the first working search without another service. Stable pagination and privacy filters matter before relevance experiments. Search remains a catalog lookup while Phase 2 served-item attribution is unfinished.
- **Alternatives:** substring scanning; external search engine; learned relevance immediately; pretend search responses are logged ML exposures.
- **Revisit if:** measured latency/corpus size or language/relevance requirements need a dedicated engine. Compare PostgreSQL full-text with that engine, keeping corpus, queries and eligible visibility fixed.

## 2026-10-07 · Preserve board privacy and enforce section membership in the database
- **Decision:** all existing/new boards default secret; publication is explicit. Secret membership does not make catalog pins private. A composite FK enforces same-board save/section membership; it is checked at commit so section deletion can clear section_id without losing saves. Public reads share block/availability policy; authenticated media uses no-store.
- **Why:** migrating formerly owner-only boards must not publish private collections. Database constraints prevent cross-board assignments independently of API checks, including retries and concurrent changes.
- **Alternatives:** make legacy boards public by default; conflate board privacy with pin privacy; rely solely on application membership checks; delete saves with sections.
- **Revisit if:** true private pin media/collaborative boards are added. That needs a distinct pin access model and cache policy. Migration tests upgrade real older rows in a disposable database and verify search backfill and saved-pin preservation.

## 2026-10-07 · Serialize social transitions and notify transactionally
- **Decision:** user pair locks in ID order serialize follow/block writes. Board follows also lock/re-read publication state. Blocks remove cross-user user/board relationships and notifications; mutes suppress discovery/activity but allow direct reads. In-app follow notifications are inserted with the first relationship in the same transaction.
- **Why:** repeated/concurrent follows should create one relationship and one notice, while an unfollow followed by a later follow is a new transition. Blocking must not race with new relationships. Product records remain separate from ML engagements.
- **Alternatives:** asynchronous fan-out before delivery guarantees; retry-created duplicate notices; hiding only UI buttons; using follow writes as observed impressions.
- **Revisit if:** digest/outbox delivery or Following fan-out is implemented. Compare instant versus batched notifications and read versus write feed fan-out with a declared workload. No external email is sent by this implementation.

## 2026-10-07 · Prepare Lens pixels while keeping inference and evaluation explicit
- **Decision:** validate image size/type and normalized crop bounds, orient before cropping, flatten alpha, strip metadata, hash source/crop and retain pixels only transiently. Scaffold pinned image-only CLIP query inference and exact/ANN evaluation separately from Phase 3A catalog embedding recipes.
- **Why:** crop preparation can be verified without models. Image-only queries and image-title catalog fusion need an explicit compatibility/quality experiment; toy overlap checks do not establish crop relevance.
- **Alternatives:** silently use random vectors or downloaded weights; crop before EXIF orientation; persist user query images by default; call ANN agreement user accuracy.
- **Revisit if:** object detection proposes crops, a product-only index is needed, or a real corpus supports exact/ANN latency and retrieval comparisons. Following/related/Lens serving must use shared request/item/view attribution after Phase 2 acceptance.
