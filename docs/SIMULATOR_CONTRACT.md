# Simulator contract (reusable across projects)

The simulator is a separate project for practicing how a production system operates. It
generates sessions, traffic, actions, and delivery conditions so the developer can observe
latency, data flow, failures, recovery, and model changes without live users. Simple scripted
behavior is sufficient. Modeling real users' preferences is optional and is not the primary
purpose or acceptance criterion.

The simulator stays generic (users, items, sessions, scenarios) and uses a thin project
adapter. The adapter maps this contract onto normal application services and endpoints.
Paths below are suggestions. Load generation, session policy, and fault orchestration live
in the simulator; instrumentation and the application adapter live in the product repo.

## Scope and conventions

- This is the planned v1 contract. Implement it incrementally and advertise only working
  capabilities. The minimum integration is home recommendations, users, catalog access,
  explicit events, and reset to a recorded baseline. Snapshotting, logical-time acceleration,
  model control, and retrain triggers are optional extensions.
- Run in a disposable simulation environment with one active run at a time for v1. Its
  database, Redis namespace, object prefix/bucket, and workers are isolated from normal
  development data. Parallel isolated runs are a later extension.
- Register a run manifest before traffic: run ID, baseline/dataset version, scenario and
  random seed, model/config/feature versions, experiment policy, and time mode/reference.
  A suggested `POST /sim/runs` accepts the run ID, baseline ID, scenario ID, and seed;
  the server records resolved versions and rejects a second active run in that environment.
- All requests during a run carry `X-Sim-Run-Id: <id>`. Propagate it through requests,
  events, mutations, derived records, and background jobs. Reject unknown or closed runs.
  Health/capability discovery and run registration do not require an active run; a completed
  reset can be retried as described in section 7.
- All IDs are strings. All timestamps are ISO 8601 UTC. Positions are zero-based within
  each response; every page has its own request ID.
- Event ingestion is idempotent on `event_id` across event types. An exact retry is a
  duplicate; the same ID with different content is a conflict. Validate that supplied user,
  item, position, and run attribution match the referenced request.
- Simulation endpoints and simulation time/config overrides are disabled unless
  `SIM_MODE=true`. They require the simulation environment's control authorization.
  Simulated users still authenticate to normal endpoints as themselves.

## 1. Health and capabilities

Expose the normal health endpoint and `GET /sim/capabilities`. Example after the minimum
adapter and reset are implemented:

```json
{
  "project": "pinterest-lite",
  "contract_version": "1",
  "surfaces": ["home"],
  "event_types": ["impression", "click", "closeup", "save"],
  "supports_reset": true,
  "supports_snapshot": false,
  "supports_logical_time": false,
  "supports_model_control": false,
  "supports_train": false
}
```

Add search, related, Lens, and other actions only when their product paths exist. Unsupported
operations return an explicit error; do not imply they worked. Basic request/error metrics
and ingestion outcomes must be inspectable through the project's normal diagnostics.

## 2. Users and application actions

`POST /sim/users` with:

```json
{ "external_id": "sim-user-42", "attributes": { "locale": "en-CA" } }
```

returns `{ "user_id": "user-42", "auth_token": "..." }`. Creation is idempotent on
`(sim_run_id, external_id)`. Tokens let simulated users call normal endpoints as themselves.

The adapter maps mutations such as creating a board, saving a pin, or uploading content to
normal application services. Retried mutations must use the application's idempotency
mechanism so a transport retry does not create extra domain objects. Event ingestion in
section 5 records telemetry; it does not by itself create a board save or another mutation.
Define one canonical event ID/producer for each action so action endpoints and client
telemetry do not independently double-count it.

## 3. Catalog export

`GET /sim/catalog?cursor=&limit=500` returns the items available to a scenario:

```json
{
  "items": [
    {
      "item_id": "pin-17",
      "title": "Blue shirt",
      "text": "Cotton shirt",
      "image_url": "...",
      "attributes": { "category": "clothing", "price": 24.0 },
      "created_at": "2026-10-01T12:00:00Z"
    }
  ],
  "next_cursor": null
}
```

Embeddings and their exact model/version may be exposed as optional fields for scenarios
that need them. IDs, metadata, and simple action policies are sufficient for initial
operational exercises. Catalog availability follows the run's effective time.

## 4. Recommendations

`GET /sim/recommendations?surface=home&user_id=...&limit=25&cursor=` delegates to the same
retrieval/ranking path used by the UI and returns:

```json
{
  "request_id": "request-9",
  "model_versions": { "ranker": "logreg:v1" },
  "config_version": "feed-config:v1",
  "experiment_arms": { "ranker_test": "B" },
  "items": [ { "item_id": "pin-17", "position": 0, "kind": "organic" } ],
  "next_cursor": null
}
```

When implemented, search adds `query`, related adds `context_item_id`, and Lens uses an
adapter mapping for its image/crop input. `kind` distinguishes organic items from later ad
placeholders. Record the returned list as served items; this call does not create views.
The server validates that the requested user is the authenticated simulated user.

## 5. Events and delivery conditions

`POST /sim/events` accepts a batch. Example of a view followed by a click:

```json
{
  "events": [
    {
      "event_id": "view-1", "user_id": "user-42", "item_id": "pin-17",
      "request_id": "request-9", "position": 0, "type": "impression",
      "view_rule_version": "card-50pct-1s-v1", "event_time": "2026-10-06T12:00:01Z"
    },
    {
      "event_id": "click-1", "user_id": "user-42", "item_id": "pin-17",
      "request_id": "request-9", "position": 0, "type": "click",
      "impression_event_id": "view-1", "event_time": "2026-10-06T12:00:03Z"
    }
  ]
}
```

Here `user_id` denotes the internal ID returned by user creation. Return accepted, duplicate,
and rejected counts plus per-event outcomes with reasons; partial success must be explicit
so callers can retry accurately. A valid event awaiting its referenced impression can be
accepted with attribution pending, then reconciled when the earlier event arrives.

Impressions are explicit. A scenario decides how far a session scrolls and which cards meet
the app's versioned view rule (v1: 50% visible for one continuous second). Report once per
served item. A repeated view with a new event ID for that served item must not inflate the
count. An unseen served item is not a negative impression example. Clicks without a matched
view remain usable telemetry but are excluded from impression-based label construction.

Exercise retries, duplicate batches, missing events, delayed delivery, and out-of-order
arrival. Preserve `event_time` and server `received_at` separately so delay is observable.
The label-building rules in PLAN.md determine when a window is mature and how late data
enters a later dataset version.

## 6. Time modes

- **Wall time (minimum):** requests, recency features, jobs, and rollups use server UTC.
  In simulation mode, validated event timestamps supplied by the simulator preserve the
  occurrence time of deliberately delayed events. Outside simulation mode, effective event
  time uses server receipt time in v1; client times may be retained as diagnostic metadata.
- **Logical time (optional):** `X-Sim-Time` supplies a request/action's effective time within
  the run. The application clock and scheduled work must use a defined, shared run clock;
  validate advances and propagate time context to jobs. Events retain occurrence time,
  which may be earlier than processing time. Do not advertise this capability if only
  event ingestion supports it. Record the logical clock/reference in the run manifest.
- Latency, timeouts, throughput, queue wait, and infrastructure TTLs remain measured in
  real elapsed time. Use wall-time workloads for capacity and timeout exercises; accelerated
  scenarios primarily test chronology, feature evolution, labels, and rollups.

## 7. Reset and optional snapshot

**Minimum: reset by rebuilding a recorded baseline.** `POST /sim/reset` with
`{ "sim_run_id": "..." }` operates only on that run's disposable environment. Stop intake,
quiesce/cancel run jobs, remove run-created state, and reload the manifest's baseline.
Reject a request that does not identify the environment's active run, except a retry of an
already completed reset. Reset closes that run; create a new run ID for the next scenario.
Export measurements before resetting.

The adapter may invoke a scoped environment rebuild/reseed script for this operation;
v1 does not require an undo engine for individual mutations. Preserve run manifests and
reset completion receipts outside resettable application state so retries remain safe.

| State | V1 reset behavior |
|---|---|
| Database | Restore baseline catalog, seed users/history, and configuration; remove run-created users, actions, events, requests, rollups, and derived user features |
| Redis and workers | Drain/cancel run work, clear run queues/caches, and rebuild derived caches; no old job may write after reset completes |
| Object storage | Remove run-created objects from the isolated prefix; retain immutable baseline media |
| Models and embeddings | Pin baseline artifact versions; restore/rebuild baseline derived vectors; archive needed experiment artifacts before clearing run-specific active state |
| Clock and randomness | Restore baseline time settings and recorded seeds; record a fresh run manifest |

Reset is idempotent: retrying a completed reset for the same run returns its result without
disturbing a newer run. Mark it complete only when old work cannot mutate the restored state.
Deterministic seeding plus pinned artifacts is the initial repeatability mechanism; request
scheduling and latency need not be bit-for-bit identical across runs.

**Optional later: snapshot/restore.** Advertise `supports_snapshot=true` only after a
quiescent boundary and snapshot manifest define database contents, immutable media/model
references, derived state, configuration, and logical time. Redis caches can be discarded
and rebuilt; queues must be empty with workers quiesced. Restoring requires the same
isolation rules as reset. A database dump alone is not a complete system snapshot.

Suggested endpoints: `POST /sim/snapshot` returns `snapshot_id`; `POST /sim/restore` takes
that ID. Define whether any additional state is included before implementing the extension.

## 8. Model control (optional)

`POST /sim/config` with `{ "overrides": { "ranker": "lightgbm:v2" } }` changes the active
run's configuration only. Resolve exact versions, record the effective change, and return
the resolved config version. A forced override is recorded explicitly on served requests;
do not misattribute it to an experiment arm. Preserve the previous config for rollback.

`POST /sim/train` may trigger a background training job and return a job ID. Record its data
cutoff and artifact version; training does not automatically activate a new model. This
extension supports exercises in freshness, retraining, version attribution, and rollout.

## Readiness checkpoints

Before declaring the minimum integration ready:

- [ ] Capability response lists only implemented surfaces, events, and controls
- [ ] Normal serving and mutation paths are used; simulated users authenticate normally
- [ ] A reproducible baseline and run manifest exist; run attribution reaches jobs and mutations
- [ ] Served items and viewed items remain distinct; events are idempotent and attributable
- [ ] Partial batches, conflicting IDs, and out-of-order events have explicit outcomes
- [ ] Responses carry request ID, positions, model versions, and experiment assignment
- [ ] Diagnostics expose latency/errors, ingestion outcomes, and relevant background-job lag
- [ ] Reset restores the declared baseline with no surviving writes from the previous run
- [ ] Simulation endpoints and overrides are gated by `SIM_MODE` and control authorization

Optional capabilities have their own checkpoints: consistent logical time, isolated config
overrides/rollback, retraining with explicit activation, and a complete snapshot manifest.
