# Revisiting an earlier phase

The latest implementation is on GitHub's `main`; `phase-3a-completion` and earlier work
branches remain available.
Annotated tags preserve `phase-1`, `phase-2-scaffold`, `phase-3a-scaffold`, and
`phase-3b-scaffold`. The scaffold
tags are explicitly unfinished learning checkpoints, not completed milestones.
The Phase 1 tag is the validated core loop;
its tag message explicitly records that
the developer's real H&M import is still pending. There is no separate Phase 0 snapshot.
The project is published at https://github.com/MehradShm/Pinmorph. Generated reports and
fitted artifacts are excluded from every published branch and tag. Filtering those files
changes some published commit hashes; milestone names and source code are preserved.

The independent GitHub checkout is `../pinterest-lite-github` beside the original
`pinterest-lite` directory. Make future commits and pushes from that checkout. The original
checkout retains local reports and its original checkpoints; do not push its unfiltered
history. Datasets, CLIP weights, fitted models, MLflow runs, browser output and secrets
remain ignored. The small synthetic test fixtures and required CLIP tokenizer stay in Git.

Use an immutable tag for each accepted milestone, and branches for ongoing work. A worktree
lets you open an older version beside the current version without switching the active code.
Git saves code and lockfiles. Database rows, Redis queues, MinIO objects, `.env`, and imported
dataset files are external state; a tag alone cannot restore them.

## Open Phase 1 in a separate worktree

From the current `pinterest-lite` directory:

```bash
git worktree add --detach ../pinterest-lite-phase-1 phase-1
```

For edits to the historical version, create a new branch in that worktree rather than move
the tag. Do not point its migrations at the current phase's database.

## Run Phase 1 beside Phase 2

The provided override gives the original Phase 1 Compose file separate application/web
image tags. `-p pinmorph-phase1` gives it separate named volumes and network. The example
environment uses separate host ports. The pinned MinIO image can be shared; its objects
are isolated in the separate project's volume.

After creating the worktree, run from `pinterest-lite-phase-1`:

```bash
docker compose -p pinmorph-phase1 \
  --env-file ../pinterest-lite/infra/milestones/phase-1.env.example \
  -f compose.yaml -f ../pinterest-lite/infra/milestones/phase-1.compose.yaml \
  up --build -d --wait
```

Seed that environment through its own API container:

```bash
docker compose -p pinmorph-phase1 \
  --env-file ../pinterest-lite/infra/milestones/phase-1.env.example \
  -f compose.yaml -f ../pinterest-lite/infra/milestones/phase-1.compose.yaml \
  exec api python -m scripts.seed --demo --reference-time 2026-10-07T00:00:00Z --wait 120
```

Open Phase 1 at **http://127.0.0.1:8081**; keep the current app at **http://localhost:8080**.
Cookies are scoped to host rather than port, so these different hostnames keep the two
login sessions apart. Historical API docs are at http://127.0.0.1:8001/docs.

Use the same Compose flags with `down` to stop only this historical stack. Keep its named
volumes to resume later. Host-run Python commands need matching historical connection URLs;
the commands above run inside the correct container and avoid accidentally using Phase 2's
local `.env`. This reconstructs a demo baseline, not a backup of earlier user activity.

To inspect Phase 2's preserved scaffold without switching current code, use another worktree:

```bash
git worktree add --detach ../pinterest-lite-phase-2-scaffold phase-2-scaffold
```

This command is a recipe; that additional worktree has not been created. If running it,
provide its own Compose project/ports/image tags and state, as in the Phase 1 example above.
Current Phase 3A migrations use a newer schema than the Phase 2 checkpoint.

To inspect the preserved Phase 3A scaffold, use `git worktree add --detach
../pinterest-lite-phase-3a-scaffold phase-3a-scaffold`. This is a recipe; that worktree has
not been created. Use isolated state when running it. The Phase 3B simulation Compose
override creates its own separate project/stores; see PHASE3B.md. Baseline/control files
and observation exports are outside those stores and are not captured by Git tags.

Validation: the override's merged configuration is checked against the actual `phase-1`
worktree. Running two stacks concurrently is an optional exercise, not a claim that both
have been started on this machine.

To inspect the preserved Phase 3B tooling, use `git worktree add --detach
../pinterest-lite-phase-3b-scaffold phase-3b-scaffold`. This is a recipe; that worktree has
not been created. Phase 4 adds migration `d12ac1433a55`; use isolated state to run old code.
The Phase 3B tag preserves incomplete CTR/adapter work, not a completed ML/operations track.

## Phase 4 implementation checkpoint

`phase-4` is the working branch; `phase-4` is also the completion tag for the implemented
product/Lens checkpoint. It includes migration `4f1a7b239abc`, completed shared serving/events,
local CLIP and Mailpit services. Earlier scaffold tags remain historical references.
Use a separate worktree plus its own Compose project, ports, volumes and bucket to run an
older phase; Git preserves code, not database/Redis/object-storage/model state.

The Phase 4 runtime needs ignored model weights (`make lens-prepare`) and explicit catalog
backfill (`make lens-backfill`) for an existing dataset. The original Phase 1 state and
stopped simulator-lab state are preserved separately. See PHASE4.md for the current app.

## Phase 5 implementation checkpoint

Branch/tag `phase-5` preserves business/product/Shop/empty ad layout/creator analytics,
migration `e9b3c71d5f02` and its analytics scheduler. `phase-4` retains the earlier code.
To inspect it without switching the current application:

```bash
git worktree add --detach ../pinterest-lite-phase-4 refs/tags/phase-4
```

This is a recipe, not an already created worktree. Use an isolated Compose project, ports,
image tags, database, bucket and model mount as described above; old code must not run
against the current migrated database. Phase 5 details are in PHASE5.md. These code
checkpoints do not mark the separate Phase 3A/3B learning exercises complete.

## Phase 3A personalization implementation checkpoint

Branch `phase-3a-completion` completes the previously preserved Phase 3A skeleton. The
`phase-3a-personalization` tag preserves the validated implementation, migration
`72aa31f096bc` and encoder/runtime locks. Synthetic ranking/retrieval reports remain local.
Earlier `phase-5` and `phase-3a-scaffold` milestones remain available. To inspect the scaffold beside it:

```bash
git worktree add --detach ../pinterest-lite-phase-3a-scaffold refs/tags/phase-3a-scaffold
```

This is a recipe, not an already created worktree. Use separate stores/ports/images for
historical execution: the current readiness check expects the new schema. Git preserves
source code and lockfiles; the tiny validated JSON ranker/report/audit in `docs/reports`,
local active configs, CLIP weights and MLflow runs remain external ignored state in this
GitHub copy. Re-run training to create a new artifact/config with its own hash, or copy a
local validation artifact into your isolated runtime. PHASE3A.md documents configuration
activation and baseline rollback.
This checkpoint establishes mechanics on synthetic history, not real-data quality or
completed explain-back discussion. Phase 3B remains unfinished.
