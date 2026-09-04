# LLPS Explorer operations runbook

This runbook covers the Compose topology in [`compose.yaml`](../compose.yaml). The
audited Windows host currently has no usable Docker runtime, so every container
command below is an operator procedure awaiting execution. No Docker health,
restart, recovery, persistence, or performance result is implied by this document.

## Safe operating boundary

- Run commands from the repository root with a protected, completed `.env`.
- Publish only Caddy. Do not add host ports for PostgreSQL, Redis, backend, worker,
  or LRECA to make debugging convenient on a production host.
- Treat PostgreSQL as the source of truth. Redis carries queue coordination and
  rate-limit counters; an RQ payload contains only `job_id`, not a protein sequence.
- Back up PostgreSQL before an update, restore, volume reset, or schema change.
- Use `docker compose down --volumes` only for an intentional destructive reset.

## Start, stop, and restart

Validate configuration and start the dependency graph:

```sh
python3 scripts/verify_deployment_static.py
docker compose config --quiet
docker compose up -d
docker compose ps
```

The `migrate` service is one-shot. It must exit with code 0 before backend readiness.
The seven long-running services use `restart: unless-stopped`; migration does not
restart indefinitely.

Graceful stop and ordinary removal preserve named data volumes:

```sh
docker compose stop
docker compose down
```

Restart one service after inspecting its dependencies:

```sh
docker compose restart backend
docker compose restart worker
docker compose restart lreca
docker compose restart redis
docker compose restart postgres
```

The worker has a five-minute stop grace period and PostgreSQL has one minute. A
restart is not accepted until job recovery and history are checked as described
below.

## Status and health

Use the public same-origin edge for user-visible health:

```sh
curl --fail --silent --show-error http://localhost/healthz
curl --fail --silent --show-error http://localhost/api/v1/health/live
curl --fail --silent --show-error http://localhost/api/v1/health/ready
curl --fail --silent --show-error http://localhost/api/v1/system/status
curl --fail --silent --show-error http://localhost/api/v1/version
```

PowerShell equivalents are:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost/healthz
Invoke-RestMethod http://localhost/api/v1/health/live
Invoke-RestMethod http://localhost/api/v1/health/ready
Invoke-RestMethod http://localhost/api/v1/system/status
Invoke-RestMethod http://localhost/api/v1/version
```

`live` answers whether the process is serving. `ready` is the traffic gate. Backend
readiness in production includes PostgreSQL, Redis/queue, a registered worker,
LRECA, and SEG capability. The safe system/version endpoints must never expose
internal URLs, hostnames, filesystem paths, credentials, or DSNs.

Inspect Compose state and health failures:

```sh
docker compose ps
docker compose ps --all
docker compose logs --tail 200 reverse-proxy frontend migrate backend worker lreca postgres redis
```

## Component checks

### PostgreSQL

```sh
docker compose exec -T postgres sh -c 'pg_isready --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"'
docker compose logs --tail 100 postgres
```

After a PostgreSQL restart, wait for `pg_isready`, backend readiness, and then read a
known completed job through the owning browser session. A container restart must not
erase the `postgres-data` named volume. This persistence test remains unexecuted on
the current host.

### Redis and queue

```sh
docker compose exec -T redis sh -c 'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" ping'
docker compose exec -T redis sh -c 'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" LLEN rq:queue:analysis'
docker compose exec -T worker python /opt/llps/worker_healthcheck.py
docker compose logs --tail 200 worker redis
```

The raw `LLEN` value is only the waiting-list depth; scheduled retries, active work,
and PostgreSQL `queued`/`running` records need separate inspection. Prefer
`/api/v1/system/status` and worker health for routine monitoring. Do not print
`REDIS_URL` or passwords to logs or tickets.

Default queue policy:

| Setting | Default | Behavior |
| --- | ---: | --- |
| `ANALYSIS_QUEUE_MAX_JOBS` | 128 | active global admission cap; excess returns 503 `ANALYSIS_QUEUE_FULL` |
| `ANALYSIS_OWNER_ACTIVE_JOB_LIMIT` | 4 | per-owner queued/running cap; excess returns 429 `ANALYSIS_CONCURRENT_LIMIT` |
| `ANALYSIS_QUEUE_RETRY_MAX` | 2 | finite RQ retries |
| `ANALYSIS_QUEUE_RETRY_INTERVAL_SECONDS` | 10 | delay between retries |
| `ANALYSIS_WORKER_RECOVERY_TIMEOUT_SECONDS` | 360 | age before a running SQL job is considered stale |
| `ANALYSIS_WORKER_MAINTENANCE_INTERVAL_SECONDS` | 30 | recovery scan cadence |

RQ uses a deterministic ID derived from the analysis `job_id`. PostgreSQL claims the
job under a database execution lock, so duplicate delivery does not create a second
scientific result. A transient LRECA transport failure may be retried; invalid
persisted input is terminal and is not retried indefinitely. After retries are
exhausted, failure synchronization marks the SQL job interrupted.

If Redis restarts, completed results remain in PostgreSQL. Missing queued dispatches
are intended to be recreated from PostgreSQL by worker maintenance; a stale running
job is intended to return to queued after the configured timeout. This recovery
design has unit coverage, but its actual Redis/worker container restart behavior was
not tested because Docker was unavailable. During acceptance, kill the worker while
a job is running, wait beyond the configured recovery window if needed, and require a
terminal success, partial success, failed, or interrupted state. Permanent `running`
is a failure.

### LRECA readiness and model identity

The LRECA port is private. Probe it from inside the container:

```sh
docker compose exec -T lreca python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8001/health/live', timeout=3)))"
docker compose exec -T lreca python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8001/health/ready', timeout=3)))"
docker compose logs --tail 200 lreca
```

Required ready metadata:

- checkpoint `human_1_RCNN_ECA_parallel_089-0.9802.pt`;
- SHA256 `aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc`;
- model variant `human_specific`;
- upstream commit `0b4b48ab7870529a34028c6e30dfba42eddbf215`;
- configured resolved device.

On process start, `/health/live` is available while SHA verification and one-time
model loading run. Readiness becomes true only after both verification and loading.
A missing or mismatched model must remain live but unready and reject predictions.
Do not log or expose the host/container checkpoint path.

Keep `LRECA_MODEL_PROCESSES=1`. The supplied command starts one Uvicorn worker;
`LRECA_MAX_CONCURRENT_REQUESTS=1` serializes scientific requests. For GPU, provision
one model process per GPU. Adding Uvicorn workers duplicates the model and may exhaust
VRAM.

### SEG verification

Check the fixed binary and a real low-complexity probe:

```sh
docker compose exec -T worker /opt/ncbi-blast/bin/segmasker -version
printf '>ops_probe\nQQQQQQQQQQQQ\n' | docker compose exec -T worker /opt/ncbi-blast/bin/segmasker -in - -out - -infmt fasta -outfmt interval -window 12 -locut 2.2 -hicut 2.5
```

The expected native output is `0 - 11`; the public API maps that to one-based,
inclusive 1-12. Then rerun all frozen Module 3 fixtures inside the worker image. The
Dockerfile contains the same version/probe build gates, but those gates have not run
on this host.

## Logs and request tracing

```sh
docker compose logs --since 30m backend worker lreca
docker compose logs --follow --tail 100 backend worker lreca
```

Production application logs are JSON and include timestamp, service, level, logger,
request ID and selected operational fields such as job ID, status, runtime,
sequence length, and sequence SHA256. They intentionally do not log request bodies,
complete protein sequences, raw FuzDrop payloads, session tokens, secrets, or DSNs.
Exception traces are retained server-side and can include third-party exception text;
restrict log access and audit unexpected exception content before forwarding logs to
an external platform. Compose rotates JSON logs at 10 MiB with three files for the
application services, PostgreSQL, and Redis.

When investigating a user-visible error, use its `X-Request-ID` and job ID. Do not
ask the user to disclose the complete sequence or ownership cookie in a ticket.

## Retention cleanup

The default analysis retention is seven days. The backend runs cleanup once during
service startup and then every `ANALYSIS_CLEANUP_INTERVAL_SECONDS` (default 3,600
seconds). Cleanup removes expired jobs and purges eligible imported FuzDrop records;
PostgreSQL mutation uses a transaction-level advisory lock so the default single web
process cannot race a second scheduler if the deployment is later changed.

Monitor cleanup warnings in backend logs and verify outcomes through an isolated
short-retention acceptance stack. Do not alter production timestamps or run ad hoc
DELETE SQL on a live database. Backups have their own retention and are not deleted
by the application cleanup; see [`backup_restore.md`](backup_restore.md).

## Rate and request limits

Defaults per 60-second window are 10 analysis submissions, 10 FuzDrop imports, 30
deletes, and 60 exports per anonymous owner; the auxiliary address limit is four
times the owner limit. Redis keys use keyed digests rather than raw session tokens or
addresses. Rejected HTTP traffic returns structured 429 with `Retry-After`.

Caddy limits request bodies to 6 MB. The Next same-origin proxy independently limits
JSON POST bodies to 5 MiB and uses a 45-second upstream timeout. Canonical sequences
default to a 50,000-aa maximum and return structured 413 when exceeded. The sequence
limit is an operational safety setting, not a model science limit.

For acceptance, lower thresholds only in an isolated `.env`, prove structured 429
behavior, then restore normal values and prove ordinary analysis remains unaffected.

## Common incidents

| Symptom | Checks | Safe action |
| --- | --- | --- |
| `docker` is not recognized or daemon connection fails | Docker Desktop/Engine status; `docker info` | start/install runtime and confirm Linux Containers; do not claim deployment passed |
| `migrate` exits nonzero | migration logs, PostgreSQL health, credentials, current revision | stop dependent services, repair configuration or migration; never drop tables as a startup workaround |
| backend live but not ready | system status, PostgreSQL, Redis, worker, LRECA/SEG health | restore the failed dependency, then wait for readiness |
| LRECA live but ready returns 503 | checkpoint filename/size/SHA, read-only mount, device | provide the audited file and digest; use CPU if CUDA was selected without a tested GPU Compose override |
| LRECA timeout/OOM | sequence length, queue/concurrency, container memory, kernel/GPU logs | reduce admitted concurrency or restore capacity; allow method failure to produce partial/failed job; do not change scientific algorithms |
| no ready worker | worker health/logs, Redis ping, migration, LRECA readiness | restart one worker and observe SQL/RQ recovery before accepting jobs |
| queue remains full | queue depth, stale running SQL records, worker heartbeat | repair worker/recovery, preserve queued SQL records; do not flush Redis blindly |
| SEG unavailable | fixed binary/version, libraries, probe, permissions | rebuild the pinned worker image and rerun Module 3 fixtures; do not substitute another predictor |
| 413 response | proxy 5 MiB limit or canonical length 50,000 aa | reduce input or deliberately re-benchmark and reconfigure the operational limit |
| 429 response | `Retry-After`, owner and address thresholds | wait for window reset; investigate automation or abuse before raising limits |
| history missing after browser reset | anonymous cookie was cleared or changed | no account recovery exists; restore the original browser cookie only if the user securely retained it |

## Update and rollback checklist

1. Back up PostgreSQL and verify the archive before changing code.
2. Record the Git revision and image digests currently running.
3. Validate and build the reviewed release; inspect migration SQL and release notes.
4. Run migration once, start services, require all readiness probes, and run one
   frozen LRECA/SEG scientific smoke plus history/export checks.
5. Watch error rate, queue depth, job latency, memory, disk, and backup success.
6. Roll back images only when the new schema remains backward compatible. Otherwise
   stop writes and restore the matching database backup during a maintenance window.

The backup/restore and rollback paths are unverified until exercised against an
isolated Docker project and volume.
