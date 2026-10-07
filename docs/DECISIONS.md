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
