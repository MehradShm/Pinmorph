# Pinmorph / Pinterest-lite

A Pinterest-style application for learning recommendation systems and production operation.
The roadmap is in [docs/PLAN.md](docs/PLAN.md); the learning agreement is in
[docs/WORKING_AGREEMENT.md](docs/WORKING_AGREEMENT.md).

Phase 1 adds a working React app: sign up/sign in, browse the catalog, upload images,
create boards, save/remove pins, and open a pin's detail/source link. Images are processed
asynchronously by the RQ worker. The H&M importer accepts local dataset files; a separate,
clearly labeled synthetic catalog lets you try the app immediately. Ranking, impression
logging, ML libraries, and MLflow arrive in their later phases.

Phase 2 has started with versioned feed interfaces, experiment configuration, serving/event
tables, validated API contracts, and learning targets. Its core ranking/ingestion/assignment
logic remains marked exercises under the learning agreement; new `/api/feed` and `/api/events`
calls return 503 until implemented. The UI still runs the Phase 1 loop. See
[docs/PHASE2.md](docs/PHASE2.md) for the implementation guide and remaining acceptance work.
The local `phase-1` tag preserves the previous version; [milestone instructions](docs/MILESTONES.md)
explain how to revisit it with isolated application state.

## Start the stack

Install and start [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/)
or another Docker engine with Compose v2. On macOS, the first Docker Desktop launch may
require completing its setup screens. Run all commands from this `pinterest-lite` directory.

For an app-only macOS installation where `docker` is not on your PATH, use this in the
terminal session before running the commands below:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
export DOCKER_CONTEXT=desktop-linux
```

```bash
cp .env.example .env
docker compose up --build -d --wait
docker compose exec api python -m scripts.seed --demo --reference-time 2026-10-07T00:00:00Z --wait 120
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

Open **http://localhost:8080**. Create your own account, upload a JPEG/PNG/WebP, create a
board from the closeup, and save a pin. The demo contains 32 generated illustrations and
no purchase history. It is not a substitute for the H&M training dataset.

The initial build downloads dependencies and compiles the pinned MinIO release;
allow extra time for it. `migrate` enables pgvector and creates the product tables;
`init-storage` creates the media bucket idempotently. Both should exit with code 0 before
the API and worker start. Named volumes preserve data between restarts.

| Service | Local address | Purpose |
|---|---|---|
| Web app | http://localhost:8080 | Browse, upload, create boards, and save pins |
| API | http://localhost:8000/docs | Interactive API documentation |
| Liveness | http://localhost:8000/health/live | Confirms the API process can respond |
| Readiness | http://localhost:8000/health/ready | Checks database/migration, Redis, and media bucket access |
| PostgreSQL | localhost:15432 | Application data and vectors |
| Redis | localhost:16379 | RQ queues and later caches |
| MinIO S3 | http://localhost:9000 | Object storage API |
| MinIO console | http://localhost:9001 | Inspect local object storage |

Local credentials and ports are in `.env.example`. Published ports bind to loopback.
Postgres and Redis use alternate host ports to coexist with installations already on this Mac.
If you change credentials or ports, keep host-run `DATABASE_URL`, `REDIS_URL`, and S3
settings consistent. Compose supplies internal service addresses automatically. Database
credential changes require updating the existing database role when a volume already exists.

## Inspect and stop

```bash
docker compose ps -a
docker compose logs --tail=100 api worker migrate init-storage
docker compose down
```

Readiness returns HTTP 503 and identifies the failed dependency when a check fails; liveness
can still return 200. Its dependency checks are sequential and individually time-bounded.
Every API response carries `X-Request-ID`. Operational access logs include that ID, HTTP
status, and elapsed time; they exclude query strings and raw connection errors. These are
basic diagnostics; the recommendation/event logging module is a phase 2 learning task.
The worker is checked by an actual queued job in the integration suite, independently of
API readiness. Its `unless-stopped` policy restarts it after an unexpected exit, including
RQ quitting after a Redis timeout. Inspect its process/logs when jobs stall.

`docker compose down` preserves volumes. Do not add `--volumes` unless you intend to erase
the local database, Redis state, and uploaded objects.

## Python development and checks

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync --locked
make check
```

uv uses the project's Python 3.12 requirement and creates `.venv`. `uv.lock` pins dependencies;
the Docker build uses the same lock. Tests run without services by default. After starting
the stack, verify migrations, object storage, dependency readiness, and real RQ execution:

```bash
make integration
```

The integration tests write and clean up uniquely named users, pins, objects, and import
fixtures. They also verify queue failure recovery and automatic worker retries. Run them
against the local development stack with the worker queue drained; run bulk seeding separately
so its backlog does not invalidate test timeouts. CI additionally builds the UI and runs browser checks.

To run checks entirely in Docker:

```bash
docker compose --profile checks build checks
docker compose --profile checks run --rm checks ruff check .
docker compose --profile checks run --rm checks ruff format --check .
docker compose --profile checks run --rm checks pytest -m 'not integration'
docker compose --profile checks run --rm -e RUN_INTEGRATION=1 checks pytest -m integration
```

For host-side API development, start just its dependencies and one-time setup, then run:

```bash
docker compose up -d postgres redis minio
docker compose run --rm migrate
docker compose run --rm init-storage
uv run --locked uvicorn app.main:app --reload --no-access-log
```

Stop the Compose `api` service first if it already owns port 8000. Run workers in their Linux
container so RQ's process model behaves consistently across developer machines.

## Frontend development and browser checks

The container builds the UI with Node 22 and serves it through nginx. For local development:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to port 8000; the Compose web app uses the
same path through nginx. Cookies and images work on the same browser origin in both modes.
`npm run build` checks TypeScript and produces the static bundle. Vite 6 supports the
existing local Node 20 installation for builds; browser checks require Node 22.

With the stack running and demo data seeded:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
cd ..
uv run --locked python -m scripts.cleanup_browser_tests
```

The browser suite checks signup → upload → asynchronous processing → board → save/remove
→ logout/login on desktop and mobile, plus seeded browsing and a reloadable pin closeup.
It records exact disposable account identities in `frontend/test-results`; cleanup only
removes those accounts and their objects. `WEB_URL` can override the browser test address.

## Migrations and H&M import

```bash
uv run --locked alembic current
uv run --locked alembic upgrade head
uv run --locked python -m scripts.seed --demo --dry-run --reference-time 2026-10-07T00:00:00Z
```

Supply your locally downloaded H&M Kaggle dataset, with `articles.csv`, `customers.csv`,
`transactions_train.csv`, and `images/<first-three-digits>/<10-digit-article-id>.jpg`:

```bash
uv run --locked python -m scripts.seed \
  --dataset-dir /absolute/path/to/h-and-m \
  --reference-time 2026-10-07T00:00:00Z \
  --max-items 2000 --max-users 2000 --seed 42 \
  --dry-run --manifest-out data/manifests/hm.json
```

Remove `--dry-run` to import, optionally add `--wait 1200` to wait for all image jobs. A dry
run validates selected images and input columns and makes no service writes; writing a
manifest file is optional. The large transaction CSV is streamed, retaining purchases for
the selected catalog. Seeded customer identities have no login credentials.

Manifests record file/image SHA-256 hashes, sample IDs, seed, reference time, source provenance,
one optional time offset, and proposed chronological cutoffs that keep whole days together.
Original dates are retained. Add `--shift-to-reference` to move the latest selected-catalog
transaction to the reference time, applying the same offset to all history and availability.
Item availability is an explicit earliest-purchase proxy because publication dates are absent;
items without history are available at the reference time. Without shifting, transactions
after the reference time are excluded. No features, negatives, or models are fitted here.

Purchases go into `imported_interactions` as `imported_purchase_proxy`, never `saves` or
observed impressions. The same manifest yields stable entity IDs and resumes missing work
without duplicate rows. A different manifest is a separate import namespace, so importing
the same source under different settings creates a separate catalog/history; do not combine
those namespaces silently in a later training dataset. Manifests also persist in `import_runs`.

See [docs/PHASE1.md](docs/PHASE1.md) for how the pieces interact and the API routes.

## Upstream implementation references

- [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/): install from the lockfile in the image.
- [pgvector](https://github.com/pgvector/pgvector): PostgreSQL extension and container tags.
- [RQ workers](https://python-rq.org/docs/workers/): process execution and JSON serialization.
- [MinIO release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z): pinned source build. The community repository is archived; retaining it for this local learning stack is recorded in the decision log, with an S3-compatible replacement as a revisit choice.
