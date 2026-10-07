# Phase 3B: separate CTR study and operations preparation

Status: **started; local data/manifest/artifact tooling, diagnostics and disposable setup
work. CTR algorithms and the minimum simulator adapter/reset remain pending.** Phase 4
has not started. Phase 3A is preserved as `phase-3a-scaffold`, an unfinished code checkpoint.

## Goals and dependencies

Two independent tracks belong here:

1. Practice observed-click prediction on MIND, comparing a logistic model with the
   training-period constant click-rate predictor. Keep it separate from the product's
   imported purchase proxies and sampled-unobserved negatives.
2. Prepare a disposable product environment for production-operation exercises. The
   separate simulator provides workloads, delivery conditions and fault orchestration;
   this repo provides application services, diagnostics and the adapter.

MIND work can proceed without the simulator or the Phase 2 feed. Product traffic exercises
need Phase 2 serving/events first; personalized model rollout also needs Phase 3A.
WORKING_AGREEMENT.md keeps core CTR/ranking algorithms as developer exercises.

## Implemented components

| Component | Location | Behavior today |
|---|---|---|
| CTR contracts/manifest | `app/ctr/contracts.py` | Independent news, impression, observed labels, examples, feature/predictor protocols, source hashes, cutoff and time-policy records |
| Local MIND reader | `app/ctr/reader.py` | Strict eight-field news/five-field behavior TSVs, source-partition IDs, explicit source zone, preserved groups/history, hidden labels as None, duplicate/malformed rejection |
| Input inventory | `scripts/inspect_mind.py` | Counts, timestamp range, source hashes, cold starts and missing history references; no downloads, training or metrics |
| CTR artifact format | `app/ctr/artifacts.py` | Independent four-feature JSON schema, finite coefficients, scaling, manifest and library versions; checked load and immutable publication |
| Shared byte publisher | `app/artifact_io.py` | Atomic no-overwrite publication/checksum verification shared with Phase 3A; model schemas remain separate |
| Learning core | `app/ctr/pipeline.py`, `evaluation.py` | Seven named TODO groups and opt-in known-answer targets; no trained model or computed quality report |
| Request metrics | `app/operations/metrics.py` | Thread-safe route-template/status counters and cumulative latency buckets; bounded labels, no query/user/item IDs |
| Service diagnostics | `app/operations/diagnostics.py` | DB pin/event/backlog summaries and queue-head age, stored registry counts and worker heartbeats; partial errors contain only exception classes |
| Control discovery/API | `app/operations/api.py` | Authenticated `/sim/capabilities` and `/sim/diagnostics`; disabled outside explicit disposable mode; unsupported operations return 501 |
| Baseline/run schemas | `app/operations/contracts.py` | Immutable baseline description and future run-registration payload; validation does not create an active run or reset receipt |
| Disposable setup | `scripts/sim_environment.py`, `infra/simulator/compose.yaml` | Private environment file, checksummed baseline descriptor, separate project/ports/images/volumes/network, read-only baseline mount |
| Initial baseline seed | `scripts/sim_baseline.py` | Checks mode, baseline hash, environment/config identity; seeds the declared demo via the existing importer/media jobs; never removes state |
| Observation export | `scripts/export_operations.py` | Control-authenticated loopback export, environment identity check, readiness including 503, immutable output; exercise outcome remains not_assessed |
| Prerequisite inventory | `scripts/phase3b_preflight.py` | Static CTR TODO/runtime inventory and unchecked acceptance gates; no completion claim |

No migration is needed. The Phase 3A schema remains the current head. No sklearn/MLflow
runtime or MIND dataset is installed/downloaded by this phase. The small committed fixture
is invented and explicitly marked `synthetic_fixture`; it tests correctness, not quality.

## MIND data and chronology

Supply local extracted `news.tsv` and `behaviors.tsv` files. The official source lists
click/nonclick labels and says the candidate order is shuffled. It does not provide a
time-zone offset in its timestamp strings; `--source-timezone` is a required, recorded
assumption. Ambiguous/nonexistent DST times are rejected rather than silently ordered.
The official news examples have eight fields despite the prose saying seven.

Each behavior row stays one impression group. Namespace IDs by partition to avoid
collisions; split complete groups chronologically and retain timestamp ties. Public dev is
a source partition, not automatically a protected final test. MIND-small provides train
and dev only: define local time-based train/validation/test periods explicitly and leave
the final period untouched. Public unlabeled candidates remain None and cannot become
supervised negatives. Inventory can inspect them without pretending labels exist.

Features use source pre-impression history and that partition's news metadata. Source
history lacks individual timestamps, so do not invent history decay, ingestion times,
article publication age or app-style late-event guarantees. Missing history metadata is
reported and gets the declared feature fallback; do not fill it from later partitions.
Later current-impression clicks cannot enter its features. All displayed observed labels
participate, preserving natural prevalence; no negative sampling or class balancing in v1.

## CTR exercise order and alternatives

1. `phase3b-ctr-splits`: half-open chronological group splitting before fitting transforms.
2. `phase3b-ctr-features`: four interpretable features: history length, known-history
   category fraction, candidate-title token overlap with known history, title token count.
   Lowercase alphanumeric tokenization, explicit empty-history/missing-metadata fallbacks,
   no current labels or shuffled position. Alternative: train-only TF-IDF or content encoders.
3. `phase3b-ctr-examples`: one example per displayed candidate; preserve impression identity
   and source click label; reject hidden labels. Alternative sampling needs a separate policy
   and corrected probability/evaluation interpretation.
4. `phase3b-ctr-baseline`: training click count divided by all training displayed candidates.
   Constant prediction application works; estimating its probability is the exercise.
5. `phase3b-ctr-training`: train-only scaling/logistic fit, strict training-cutoff checks,
   natural label distribution, validation selection and protected final test. Pin runtime
   and export the independent CTR artifact/MLflow manifest. Alternative: a tree model.
6. `phase3b-ctr-scoring`: pinned feature order/scaling and stable sigmoid; preserve input order.
7. `phase3b-ctr-evaluation`: pooled and macro within-group AUC, log loss, Brier score, ECE and
   within-group binary NDCG. Report eligible group counts: single-class groups have no AUC;
   no-positive groups have no NDCG. Equal scores get half AUC credit, ranking ties use news ID.
   ECE uses equal-width bins; 1 belongs to the last bin. Empty metrics are None, not zero.

The fifteen opt-in tests cover ties, cold start, feature invariance to current labels/order,
label preservation, hidden labels, training-only prevalence, artifact scoring, held-out fit
rejection, known metrics, duplicate identities and undefined cases. They are pending targets.
Actual fitting, reproducible artifact/run export and a real-data baseline report need additional
acceptance checks once core implementations exist. Do not declare success from toy metrics.

```bash
make check
make mind-fixture
make phase3b-preflight
make phase3b-exercises

uv run --locked python -m scripts.inspect_mind \
  --dataset-dir /path/to/MINDsmall_train --partition source-train \
  --source-timezone UTC --provenance mind_observed
```

UTC above is an example assumption, not a confirmed MIND source zone. Ordinary checks skip
the core targets; opting in intentionally raises LearningExercisePending until implemented.
`phase3b_preflight --fail-on-pending` returns 2. Its adapter/real-data gates remain unchecked,
even if a TODO disappears. Phase 3B TODOs do not block the Phase 3A prerequisite inventory.

## Current simulator controls

SIM_MODE defaults to false. Enabling it requires SIM_DISPOSABLE, a `pinmorph-sim-*`
environment ID and a private control token of at least 32 characters. Use the generated
Compose setup for actual isolation; flags alone cannot prove isolated infrastructure.
`X-Sim-Control-Token` authorizes discovery/diagnostics. Browser Origin policy still applies.
Responses use no-store and request IDs. No control credentials are returned or logged.

Current capabilities: diagnostics=true; surfaces/events empty; users/catalog/runs/reset,
snapshots/logical time/model control/training=false; ready_for_traffic=false. Unsupported
operations return 501 in simulation mode and 404 in the normal environment. Normal `/api`
routes reject all X-Sim-* headers until run attribution is implemented. Do not bypass this
by removing the header to pretend a registered scenario ran.

Diagnostics are point-in-time observations across components, not an atomic system snapshot.
Request counters/histograms cover this API process since startup and reset on restart;
they do not provide persisted run metrics or exact p95/p99. Queue age covers the first 100
queued job records, worker details the first 100 registrations. Registry counts describe
stored members without cleanup, including stale entries. Redis reads do not clean workers
or registries. Readiness reports storage connectivity; the diagnostic endpoint reports DB
and queue detail separately. Event ingestion core is explicitly marked pending.

## Start and inspect the disposable environment

```bash
uv run --locked python -m scripts.sim_environment \
  --directory data/simulator/pinmorph-sim-lab \
  --environment-id pinmorph-sim-lab --reference-time 2026-10-07T00:00:00Z

docker compose --env-file data/simulator/pinmorph-sim-lab/simulation.env \
  -f compose.yaml -f infra/simulator/compose.yaml up --build -d --wait

docker compose --env-file data/simulator/pinmorph-sim-lab/simulation.env \
  -f compose.yaml -f infra/simulator/compose.yaml exec -T api \
  python -m scripts.sim_baseline --expected-sha256 HASH_FROM_GENERATOR_OUTPUT

uv run --locked python -m scripts.export_operations \
  --env-file data/simulator/pinmorph-sim-lab/simulation.env \
  --output data/simulator/observations/baseline.json
```

The override's project name comes from the declared environment ID; avoid overriding it
with `-p`. The example uses API 8002, UI 8082, Postgres 16432, Redis 17379 and MinIO 9100/9101.
It does not share the normal project's stores or application/web image tags. Only one such
example stack runs at a time with these ports; parallel environments require explicit ports
and image choices. Existing baseline files are verified and private configuration retained;
the generator never replaces them. Changed seeds or reference time require a new directory.
Baseline/control files and observations are outside
the application's named volumes and ignored by Git. Keep the private environment file local.

Initial seed retries resume the same importer namespace. They do not restore mutated state,
delete extra users/objects, quiesce old work, close a run or record a reset receipt. Starting
the stack and exporting a baseline observation is infrastructure validation, not a measured
traffic/failure/recovery exercise. Use [OPERATIONS_EXERCISE.md](OPERATIONS_EXERCISE.md) to
record later workloads and your diagnosis. No scenario/fault runner is added to this repo.

Stop just this stack (retaining its volumes) with the same flags and `stop`.

Run the initializer inside the generated API container. It rejects host/development connection
targets even when simulation flags are set, and distinguishes the import_run_id from a future
simulator run ID. The provided stack's internal database/Redis/storage targets are checked.

## Remaining minimum adapter and reset work

After Phase 2 acceptance, implement control-authorized durable run registration with one
active run, normal authenticated simulated users, paginated catalog, home serving through
FeedService and explicit batches through EventIngestor. Extend those shared services for
validated simulation occurrence time, conflicts/partial results and run attribution;
propagate it through mutations/jobs. Add concurrent retry/out-of-order acceptance tests.

Reset must stop intake, quiesce/cancel all old jobs, rebuild only the declared disposable
DB/Redis/object state, restore pinned baseline artifacts/configuration and close the run.
Its run journal and completion receipts must survive outside resettable state; a retry of
an old completed reset must not disturb a new run. Test interrupted reset/retry and a
surviving-worker write barrier before advertising supports_reset. No destructive reset
endpoint/script is present today. Snapshot, shared logical clock and model/train controls
remain optional later extensions.

## Completion and explain-back

CTR completion needs real declared MIND input, pinned runtime, trained artifact, reproducible
baseline/held-out metrics with group counts and calibration, and explain-back results.
Operations completion is per measured exercise after the minimum adapter/reset acceptance.
No exercise is complete merely because diagnostics exist. Current outcomes remain pending:

1. Why can a constant baseline use only training prevalence? Why can't shuffled source order
   be a display-position feature, or a hidden test label become a zero?
2. Why do pooled AUC and per-impression ranking answer different questions? Which groups
   are undefined and what does ECE depend on?
3. How would you identify a slow worker versus an unhealthy dependency? What prevents old
   work from writing after reset, and where must the completion receipt live?

Revisit: logistic versus tree models, train-only TF-IDF/content encoders, calibration bins,
local histograms versus persistent aggregated metrics, retry/backpressure/freshness and
model rollback under the separate simulator. Run manifests/measurements must declare the
machine resources and workload; local capacity results do not establish production limits.

## Primary references

- [Official MIND introduction and source format](https://github.com/msnews/msnews.github.io/blob/master/assets/doc/introduction.md).
- [Microsoft's MIND dataset page](https://learn.microsoft.com/en-us/azure/open-datasets/dataset-microsoft-news).
- [Official recommender MIND data utilities](https://github.com/recommenders-team/recommenders/blob/main/recommenders/datasets/mind.py).
