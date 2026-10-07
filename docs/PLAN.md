# Pinterest-lite plan

## Purpose and first finish line

Build a working Pinterest-style product to learn machine learning engineering and gain
hands-on practice with the operating conditions of a production system. The developer
should be able to explain, debug, and extend the ML path and its supporting data flows.

**First finish line (through phase 3A):** seeded catalog → browse and save → reliable
request and impression logging → personalized feed → offline evaluation → model swap
through configuration. A simple upload path belongs in the core loop; broader product
features remain on the roadmap and do not block this milestone.

A separate, reusable simulator will provide production-like workloads and operating
conditions: sessions, concurrent requests, event delivery problems, changing data, and
recovery exercises. Its purpose is to build operational experience. Scripted behavior
provides the workload; discovering real users' preferences is not a success criterion.

## 1. Modules

Depth reflects the MLE focus: **deep** = build properly and revisit with experiments,
**standard** = solid working version, **thin** = minimal but functional. Phases 0–3A
form the first finish line; phase 3B and later phases are subsequent learning tracks.

| Layer | Module | Covers | Depth | Phase |
|---|---|---|---|---|
| Experience | Identity and profiles | Basic sign-up/login in v1; profile tabs, settings, and business accounts later | standard | 1; extras 4–5 |
| Experience | Social graph | Follow users and individual boards, Following tab, follower lists, block/mute | standard | 4 |
| Experience | Engagement | Comments, reactions, share link, hide pin, report pin, (DMs optional) | thin | 4 |
| Experience | Notifications | In-app activity, email digest via local SMTP | thin | 4 |
| Content | Pin media pipeline | Upload, metadata, resize variants, dominant color, async processing; URL import later | standard | 1; URL import 4 |
| Content | Boards and saves | Basic boards and saves in v1; sections and secret boards later | standard | 1; extras 4 |
| Content | Pin closeup | Detail page and source link in v1; comments and related grid later | standard | 1; extras 4 |
| Discovery | Home feed | Candidate generation, engagement ranking, re-ranking, cold-start fallback; interest onboarding later | **deep** | 2–3A; onboarding 4 |
| Discovery | Text search | Postgres keyword search, typeahead, filters | standard | 4 |
| Discovery | Visual search (Lens) | Crop-to-search, similar pins via image embeddings | **deep** | 4 |
| Monetization | Shopping and catalogs | Product data on pins (price, availability), shop filter | thin | 5 |
| Monetization | Ads | Ad slots in feed only; the full ads system is a separate later project | thin | 5 |
| Monetization | Creator analytics | Impressions, saves, clicks per pin from daily rollups | thin | 5 |
| Platform | Trust and safety | Report queue, upload classifier gate, duplicate detection | thin | 4 |
| Platform | Data and experiments | Served-item/impression/engagement logging, experiment bucketing, offline datasets | **deep** | 2–3A |
| Platform | CTR study | Separate MIND pipeline using observed impressions and clicks | **deep** | 3B |
| Platform | Operations practice | Metrics and diagnostic logs, simulator adapter, traffic and recovery exercises | **deep** | instrumentation 0–3A; exercises 3B onward |
| Platform | Storage and infra | Postgres, Redis, MinIO, workers, docker compose | standard | 0–1 |

Inspiration from Pinterest's published work (read when revisiting): Pixie (graph random walks),
PinSage (graph embeddings), PinnerSage (multiple embeddings per user), TransAct (real-time
action sequences in ranking), Manas (search engine).

## 2. Architecture principles

- **Swappable implementations.** The feed pipeline is composed of protocols:
  `CandidateSource`, `Ranker`, `Reranker`, plus `PinEmbedder` and `UserEmbedder`.
  Implementations register under a name and version (e.g. `ranker:logreg:v1`).
  Which one runs is resolved from config plus experiment assignment, never hardcoded.
- **Small interfaces at useful boundaries.** Apply the same idea to other modules when
  their revisit experiment is built (search backend, fan-out, image resizing). A single
  backend and worker codebase is sufficient; separate services are not a v1 requirement.
- **Everything served is attributable.** Responses carry request ID, model/config versions,
  and experiment assignment. Server records also retain surface, candidate sources, and
  scores per item, so the served list can be reconstructed without exposing diagnostic
  details in the product UI.
- **Training-serving consistency.** Snapshot all ranking features at v1 scale, including
  feature schema/version and effective feature time. Introduce sampling only as an
  explicit, recorded later decision. Historical examples use point-in-time feature builds.
- **Observable operation.** Carry request and run IDs through logs and jobs. Record request
  latency, errors, event ingestion outcomes, queue depth/age, and feature/model freshness
  as their components are introduced. Use these to diagnose the later simulator exercises.
- **Simulator-ready in stages.** Implement the minimum capabilities in
  docs/SIMULATOR_CONTRACT.md as their product paths become available. The simulator uses
  the same application services as the UI; simulation logic stays in the separate project.

## 3. Logging and data model (the core of the MLE work)

- `feed_requests`: request_id, user_id, surface (home initially; search, related, lens later),
  query or context pin, experiment arms, model/config versions, latency_ms, served_at
  (effective time), received_at (wall time), sim_run_id (nullable).
- `served_items`: request_id, pin_id, position, candidate sources, retrieval_score,
  rank_score, final_score. These rows record the returned list, including items never viewed.
  Deduplicate pins before serving; `(request_id, pin_id)` and `(request_id, position)` are
  unique. Each pagination response has a new request ID and zero-based positions.
- `impressions`: event_id, user_id, request_id, pin_id, position, event_time, received_at,
  view_rule_version, sim_run_id (nullable). These rows record actual client-reported views
  and reference a served item. V1 view rule: at least 50% of the pin card visible for one
  continuous second; report once per served item. The simulator emits equivalent explicit
  view events. Returning an item alone never creates an impression.
- `served_features`: request_id, pin_id, feature JSON, feature_schema_version,
  feature_as_of, for training-serving checks.
- `engagements`: event_id, user_id, pin_id, request_id (nullable), position (nullable),
  impression_event_id (nullable), type (click, closeup, save, outbound_click, hide, comment,
  purchase as implemented), event_time, received_at, sim_run_id (nullable).
- `event_id` is a global ingestion idempotency key across impression and engagement types.
  Exact retries have no additional effects; reuse with different content is a conflict.
  A second impression ID for the same served item must not inflate impression counts.
- Keep event occurrence time separate from wall-clock receipt time. Retain client timestamps
  as diagnostic metadata; the effective time policy is defined in section 5 and the contract.
- For observed-impression datasets, join engagements to the same user and served item using
  request/pin identity and, when present, impression_event_id. Start with 1 hour for clicks
  and 24 hours for saves, measured from the impression. Deduplicate the target action.
  Only a closed label window can become a negative; the label policy records the effective
  cutoff, ingestion cutoff, and allowed lateness. A later dataset version can incorporate
  events arriving beyond that policy.
- Support out-of-order delivery: temporarily unmatched events can be reconciled after their
  referenced impression arrives. Exclude unresolved events from impression-based labels;
  retain imported history and unattributed actions separately with their provenance.
- Experiment assignment uses a specified stable digest of user ID, experiment name, and
  salt/version, mapped to buckets and arms; do not use a process-dependent language hash.
  Persist assignment on the request. Count actual item exposure from impressions linked to
  that request; retain zero-view requests without treating them as observed exposures.

## 4. ML pipeline

| Stage | First implementation | Revisit upgrades |
|---|---|---|
| Pin embeddings | Pretrained CLIP (open_clip) on image plus title, stored in pgvector | Fine-tune on co-saves; graph embeddings in the spirit of PinSage |
| User embeddings | Mean of last N engaged pin embeddings, time-decayed | Several embeddings per user via clustering (PinnerSage idea); two-tower model |
| Candidate retrieval | ANN from user embedding + popular/recent, blended with quotas; popularity fallback for users without history | Followed boards in phase 4; co-save graph random walks (Pixie idea); learned blending |
| Engagement ranking | Logistic regression on similarity, pin age, historical popularity, and user activity; imported positives plus sampled negatives | LightGBM; small deep model over recent actions (TransAct idea); observed-impression CTR objective and calibration when suitable data exists |
| Re-ranking | Near-duplicate removal (cosine threshold), per-creator cap | MMR diversity, freshness boost, ad slot blending, exploration slots |
| Related pins (phase 4) | Co-occurrence on boards, fallback to embedding similarity | Graph walk; learned similarity |
| Lens (phase 4) | CLIP embedding of the cropped region, ANN search | Object detection to propose crops; product-only index |

The initial app model learns an engagement score from implicit feedback. Sampled items are
unobserved candidates, not confirmed non-clicks; its probability output is not a measured
CTR. The separate MIND pipeline practices CTR prediction on observed impression labels.
Final display position is logged for analysis but excluded from v1 scoring features because
it is produced by ranking. Position-bias modeling is a later, explicit experiment.

## 5. Data (the project must run without live users)

- **H&M Personalized Fashion Recommendations (Kaggle):** product images and text become pins;
  customer transactions become proxy historical saves for seeded users. Preserve source
  provenance: an imported purchase is not an observed app save or click. Subsample heavily
  for v1 (a few thousand items, a few thousand users).
- **MIND (Microsoft News Dataset):** real impression logs with clicked and not-clicked items.
  Use it in a separate offline CTR pipeline. The app has imported implicit feedback plus
  any impressions generated by manual use; simulator traffic adds synthetic observations.
- **Criteo display ads:** reserved for the separate ads ranking project.
- App v1 training uses imported positives and sampled negatives. Record the sampling
  policy, ratio, random seed, candidate universe, and label provenance with each dataset.
  Select negatives from items eligible at the example time; do not consult future actions
  to filter them. Unobserved items can still be false negatives, which is a known limitation.
- Keep imported proxies, manually observed app events, simulator events, and MIND examples
  distinguishable. Any mixed training dataset must explicitly declare its sources and weights.

### Time and leakage rules

- Split interactions chronologically before fitting data-dependent transforms or models.
  Build each user's history, popularity counts, and other behavioral features only from
  information available before that example. In delayed-delivery exercises, an event's old
  occurrence timestamp does not make it available before ingestion/feature processing;
  record that availability time too. Enforce item availability at retrieval time. Keep
  coarse timestamp ties together rather than inventing an ordering within them.
- V1 evaluation holds the model fixed and may update user features from earlier evaluation
  interactions to emulate serving. Record this policy; later outcomes never enter an earlier
  example. Pretrained content embeddings may use content available at that time.
- Record dataset version, train/validation/test cutoffs, feature definitions, and reference
  time in the import/training manifest. If old dates are shifted for browsing, apply one
  recorded offset consistently to relevant item and interaction times, preserving chronology.
- Recency, time decay, label windows, and rollups use one application clock. Normally it is
  server UTC; simulation can supply run-scoped logical time to requests, actions, and jobs.
  Event occurrence can precede processing time when delivery is delayed. Keep wall-clock
  receipt timestamps and measure latency with an elapsed-time clock. Accelerated logical
  time does not accelerate actual worker capacity, network time, or infrastructure TTLs.

## 6. Evaluation

- Offline, time-based splits plus the point-in-time rules above. Keep a final test period
  separate from model and hyperparameter selection.
- Retrieval: recall@k and catalog coverage against popularity/recency baselines. State the
  eligible catalog, held-out positive definition, and cold-start cohort.
- Implicit-feedback ranking: NDCG@k and recall@k under a fixed candidate/negative policy.
  AUC or log loss on sampled labels may be diagnostics, but do not report them as real CTR
  or compare runs that silently use different negative sampling policies.
- Observed-impression CTR (MIND, then suitable app datasets): AUC, log loss, calibration,
  and ranking metrics within impression groups. Distinguish synthetic app results from
  manually observed events and MIND results.
- Track every run in MLflow with dataset manifest, cutoffs, feature and model versions,
  random seeds, baselines, metrics, and serving feature policy.
- A/B plumbing is exercised with simulator traffic: stable assignment, exposure attribution,
  metric computation, model rollout, and rollback. Any engagement differences describe the
  configured scenario; operational correctness and diagnosis are the primary learning goals.

### Production-environment practice with the separate simulator

Start with one local, disposable environment and add one condition at a time. Record the
workload, machine resources, expected behavior, measurements, and what was learned. Set an
initial latency/error budget after measuring the baseline; local results are scoped to that
environment. The scenario runner and fault controls live outside this product repo; the
product provides normal serving paths, telemetry, and the adapter contract.

| Exercise | What to practice and measure |
|---|---|
| Normal sessions, partial scrolling, repeated visits | Request-to-view-to-action attribution; served versus viewed counts; feature updates |
| Traffic bursts and concurrent sessions | Throughput, p50/p95/p99 latency, error rate, queue age, and saturation point |
| Retries, duplicates, delayed and out-of-order events | Idempotency, event reconciliation, mature labels, ingestion lag, and missing data |
| Cold-start users, new pins, changing activity | Fallback behavior, embedding job lag, coverage, and feature freshness |
| Slow or unavailable dependencies and interrupted workers | Timeouts, defined fallback or explicit failure, job retry, backlog drainage, and recovery |
| Retraining and model/config changes | Version attribution, training-serving checks, rollout, rollback, and metric continuity |
| Reset and scenario replay | Isolation of runs, baseline reconstruction, and comparable measurements |

Simple scripted session/action policies are sufficient initially. Richer preference models
are optional workloads, not a prerequisite. Exact traffic replay tests delivery and load;
an adaptive session script can respond to changed recommendations. Record which is used.
Neither requires proving what real users would prefer.

## 7. Milestones

- **Phase 0, setup:** docker compose, health endpoint, migrations, CI-lite (lint plus tests),
  seed script skeleton, and basic request/error diagnostics. Done when the stack starts
  reproducibly and an unhealthy service can be identified.
- **Phase 1, core loop:** basic auth, pin upload/resize pipeline, boards and saves, closeup,
  masonry UI, and H&M seed import with a reproducible time/provenance manifest. Done when
  a user can sign up, upload, save, and browse the seeded catalog.
- **Phase 2, baseline feed and logging:** recency/popularity feed, served items, explicit
  view events, engagements, feature snapshots as features are introduced, experiment
  bucketing, and imported history. Done when served and viewed counts are distinct, retries
  do not inflate counts, and each viewed item is attributable to a request and model version.
- **Phase 3A, personalized ML v1 — first finish line:** embeddings, ANN plus popularity
  retrieval, implicit-feedback logistic-regression ranker, reranker, and time-correct offline
  evaluation. Done when the feed is personalized, cold-start fallback works, a model swap
  is a config change, and a reproducible report compares the model with its baseline.
  An honestly explained lack of improvement is an acceptable learning result.
- **Phase 3B, CTR and operations learning tracks:** build the separate MIND CTR pipeline;
  complete the minimum simulator adapter and baseline reset. When the separate simulator
  is available, run the operational exercises incrementally. MIND work can proceed without
  it. Done per exercise when expected behavior, measurements, diagnosis, and recovery are
  documented; neither track blocks the phase 3A milestone.
- **Phase 4, product extensions and deep Lens work:** text search, follows/Following feed,
  related pins, interest onboarding, profile/board extras, URL import, thin engagement,
  notifications, and safety. Lens remains a deep learning module; add its crop-search
  baseline and ANN evaluation as its own checkpoint. Build these modules independently.
- **Phase 5, thin monetization:** business-account features, product data, shop filter,
  placeholder ad slots, and analytics rollups. A full ad-serving system remains separate.

### ML and operations learning checkpoints

Each checkpoint includes a reproducible comparison and 2–3 explain-back questions. Preserve
the scaffold/learn boundary in WORKING_AGREEMENT.md; completing v1 does not mean outsourcing
the core ML logic the developer intends to learn.

| Checkpoint | Baseline or invariant | Explain-back outcome |
|---|---|---|
| Logging and labels | A small known request/view/action fixture, including retries and unseen items | Pending: Phase 2 scaffold and opt-in targets are ready; explain attribution, idempotency, and when an example becomes a negative after implementing the core |
| Embeddings and retrieval | Popularity/recency; exact similarity on a small subset to check ANN recall | Explain user history cutoff, cold start, and retrieval accuracy versus latency |
| Engagement ranker | Unranked candidate blend or similarity ordering, evaluated on the same candidates | Explain sampled negatives, point-in-time features, and ranking versus CTR |
| Reranker | Same ranked list without reranking | Explain duplicate removal, creator concentration, diversity, and relevance tradeoffs |
| MIND CTR | Training-period constant click-rate predictor | Explain label source, log loss/calibration, and why the app's proxy task differs |
| Model selection and rollout | Pinned version and deterministic experiment assignment | Trace which model served an item and demonstrate a configuration rollback |
| Operational exercise | Known steady workload and explicitly expected failure/recovery behavior | Diagnose the bottleneck or failure from telemetry and explain the recovery |

## 8. Revisit experiments backlog

| Module | Experiment | Read alongside |
|---|---|---|
| Home feed / graph | Fan-out on write vs fan-out on read for the Following tab | Xu, *System Design Interview* vol. 1, news feed; Kleppmann, *DDIA*, Twitter example |
| Ranking | Logistic regression vs LightGBM vs sequence model; observed-impression calibration and position bias | Aminian and Xu, *ML System Design Interview*, ad click prediction; Huyen, *Designing ML Systems* |
| Retrieval | Single vs multiple user embeddings | PinnerSage paper; Aminian and Xu, personalized news feed |
| Re-ranking | Diversity via MMR vs hard caps | Aminian and Xu, video recommendation |
| Search | Postgres full-text vs a dedicated search engine | Xu vol. 1, search autocomplete; Kleppmann on indexes |
| Lens | Exact vs approximate nearest neighbor; index types | Aminian and Xu, visual search |
| Media | Resize on upload vs on demand | Xu vol. 1, YouTube; Xu vol. 2, object storage |
| Notifications | Instant vs batched digests | Xu vol. 1, notification system |
| Data | Logging to a table vs a queue; label windows and delayed feedback | Kleppmann on stream processing; Huyen |
| Operations | Backpressure, retry policies, cache behavior, feature freshness, and rollback under simulated workloads | Kleppmann on distributed systems; Huyen on monitoring |
| Infra | Single database vs sharding pins by ID | Kleppmann on partitioning and replication |

## 9. Out of scope for this repo

- The simulator engine, session policies, load generation, and fault orchestration (separate
  reusable project). Product instrumentation and the adapter belong in this repo.
- The full ads system with auction, pacing, and billing (separate project on Criteo data).
- Full production hardening: real security review, multi-region, high availability. Local
  timeout, failure, observability, and recovery exercises remain part of the learning scope.
