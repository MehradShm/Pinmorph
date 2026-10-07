# Operations exercise record

Status: template, not a completed scenario. Fill this for one condition at a time after
adapter/reset acceptance. Keep evidence outside resettable application state. Diagnosis and
explain-back belong to the developer; scaffold tools do not supply a measured conclusion.

- Environment, machine resources, application revision:
- Run ID and durable run manifest:
- Baseline/data hash, seed, model/config/feature versions:
- Time mode (wall time for capacity/timeout work):
- Separate simulator version, scenario and scripted/adaptive replay policy:
- Workload (concurrency, request/action rate, duration, delivery/failure condition):
- Expected behavior and measured baseline budget:
- Observation files and request/job IDs:
- Throughput, latency distribution, errors and readiness:
- Queue depth/age, worker heartbeat, ingestion lag and feature/model freshness:
- Served versus viewed counts and retry/conflict/reconciliation outcomes:
- Symptoms observed:
- Your diagnosis and evidence supporting it:
- Recovery action and how successful recovery was verified:
- Exported evidence, reset receipt and replay comparison:
- What changed your understanding; next experiment:

Explain-back prompts:

1. Which measurement distinguishes the suspected bottleneck from a competing explanation?
2. What behavior did retries or delayed events change, and which identities prevent inflation?
3. What evidence proves recovery and that no old run job can mutate the restored baseline?
