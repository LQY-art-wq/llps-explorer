# LLPS Explorer deployment guide

This guide describes the Module 10 deployment assets. It deliberately separates
commands that can be run from evidence that was actually collected.

## Verification boundary

The deployment topology and its daemon-free static checks exist, but the audited
Windows host did not have Docker, Docker Compose, Docker Desktop services, or an
alternative container runtime available on 2026-09-04. Linux Containers, the Docker
daemon, and Compose therefore could not be confirmed. The current deployment status
is `DOCKER_RUNTIME_UNAVAILABLE`; no image build, container start, container health
check, Linux scientific regression, restart test, or backup/restore test has been
performed. The evidence is in
[`audit/module10/docker_runtime_audit.json`](audit/module10/docker_runtime_audit.json).

The instructions below are a runbook for the next machine with a working Linux
container runtime. A command appearing here is not a claim that it passed on this
host. The final Module 10 status cannot become
`PRODUCTION_READY_WITH_UNVERIFIED_ITEMS` until the required local Linux Docker stack
and end-to-end checks have actually passed.

## Deployment topology

```text
Browser
   |
   v
Caddy (the only host-published service)
   |-- /      -> Next.js production server
   `-- /api/* -> FastAPI backend
                    |-- PostgreSQL (source of truth)
                    `-- Redis / RQ
                              |
                              v
                         analysis worker
                           |-- private LRECA HTTP service -> Human checkpoint
                           `-- local NCBI segmasker process
```

FuzDrop remains manual import only. The application never contacts the official
FuzDrop site automatically. DisMeta remains blocked and is not replaced by another
IDR predictor.

The Compose file declares the following fixed images or application tags:

| Service | Image/runtime | Network boundary |
| --- | --- | --- |
| `reverse-proxy` | `caddy:2.10.2-alpine` | host `${HTTP_PORT:-80}` -> container `8080` |
| `frontend` | Node `24.19.0`, pnpm `11.19.0`, Next standalone | internal port 3000 |
| `migrate` / `backend` | Python `3.12.13-slim-bookworm` | backend internal port 8000; migration is one-shot |
| `worker` | Python `3.12.13-slim-bookworm`, NCBI BLAST+ `2.17.0+` | no public port |
| `lreca` | Python `3.10.19-slim-bookworm`, PyTorch `2.1.1+cu118` | internal port 8001 |
| `postgres` | `postgres:16.10-bookworm` | no public port; named volume |
| `redis` | `redis:7.4.5-alpine` | no public port; named volume and AOF |

Only Caddy has a `ports` entry. The application containers are non-root, read-only,
drop Linux capabilities, use `no-new-privileges`, and write transient files to
bounded `tmpfs` mounts. These statements describe the reviewed configuration; their
runtime behavior is still unverified without Docker.

## Part A - Local production-like deployment on Windows

### 1. Install and verify Docker

Install Docker Desktop, enable WSL 2 and Linux Containers, start Docker Desktop, and
wait until the daemon reports ready. From a UTF-8 PowerShell session in the project
root, run:

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
docker --version
docker compose version
docker info --format '{{json .OSType}}'
```

The last command must report `"linux"`. Stop here if any command fails; do not treat
static validation as a replacement for Linux container execution.

### 2. Place and verify the LRECA checkpoint

The checkpoint is runtime data. It is ignored by the first-party Git repository and
Docker build contexts and must not be copied into an image. The default local layout
is:

```text
models/
`-- lreca/
    `-- human_1_RCNN_ECA_parallel_089-0.9802.pt
```

Create the ignored directory, place the audited file there, and verify it:

```powershell
New-Item -ItemType Directory -Force -Path .\models\lreca | Out-Null
Get-FileHash -LiteralPath .\models\lreca\human_1_RCNN_ECA_parallel_089-0.9802.pt -Algorithm SHA256
(Get-Item -LiteralPath .\models\lreca\human_1_RCNN_ECA_parallel_089-0.9802.pt).Length
```

Expected identity:

| Field | Required value |
| --- | --- |
| Filename | `human_1_RCNN_ECA_parallel_089-0.9802.pt` |
| SHA256 | `aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc` |
| Size | 2,395,318 bytes |
| Model variant | `human_specific` |
| Upstream commit | `0b4b48ab7870529a34028c6e30dfba42eddbf215` |

The paper dataset-number mapping remains `unconfirmed`; deployment must not relabel
the model as dataset 5. Compose mounts `LRECA_MODEL_DIR` read-only at
`/models/lreca`. Public APIs expose only safe filename, digest, model variant, commit,
and device metadata, never the host or container absolute path.

The LRECA image source stage uses a blob-filtered sparse checkout containing only the
six hash-audited source/data files needed by the compatibility runtime. It removes the
remote and fails the build if any model-weight file or corresponding Git blob is
present before the source tree is copied into the runtime stage. This keeps the exact
upstream commit identity available to the existing runtime verification without
bringing the upstream repository's tracked checkpoints into the final image. The
daemon-free static gate checks that construction, but an actual built-image layer scan
is still required when Docker becomes available.

### 3. Create production-like configuration

```powershell
Copy-Item -LiteralPath .env.example -Destination .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate distinct random values for the PostgreSQL password, Redis password, and
session secret. Replace every `replace-with-*` value. Keep the password embedded in
`DATABASE_URL` identical to `POSTGRES_PASSWORD`, and the Redis password in
`REDIS_URL` identical to `REDIS_PASSWORD`. Use URL-safe generated values so URL
encoding is unambiguous.

For local HTTP retain:

```dotenv
APP_ENV=production
PUBLIC_BASE_URL=http://localhost
PUBLIC_HTTPS=false
CORS_ALLOWED_ORIGINS=http://localhost
SESSION_COOKIE_SECURE=false
LRECA_MODEL_DIR=./models/lreca
LRECA_CHECKPOINT_PATH=/models/lreca/human_1_RCNN_ECA_parallel_089-0.9802.pt
LRECA_DEVICE=cpu
```

Production settings fail fast for missing PostgreSQL, Redis/RQ, session secret, and
LRECA service configuration. A placeholder or short session secret, wildcard CORS,
or an insecure cookie with `PUBLIC_HTTPS=true` is rejected. The one-shot `migrate`
service applies `alembic upgrade head`; backend startup does not drop or recreate
tables.

`ANALYSIS_MAX_SEQUENCE_LENGTH=50000` is an operational abuse and resource limit. It
is not a scientific statement that LRECA supports only 50,000 residues. Module 7/8
tested the viewer at 5,000 aa; Module 1 inference performance was measured only to
2,000 aa, so long-sequence production capacity still requires Docker-host testing.

### 4. Validate, build, and start

```powershell
.\.venv\Scripts\python.exe scripts\verify_deployment_static.py
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

Do not continue until the migration exits successfully and all long-running services
are healthy. The initial LRECA readiness window can be longer because it verifies the
checkpoint and starts the resident scientific process.

### 5. Verify health and use the application

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost/healthz
Invoke-RestMethod http://localhost/api/v1/health/live
Invoke-RestMethod http://localhost/api/v1/health/ready
Invoke-RestMethod http://localhost/api/v1/system/status
Invoke-RestMethod http://localhost/api/v1/version
```

Open only `http://localhost` for production-like browser acceptance. Do not use
ports 3000, 8000, or 8001 as the final browser path. The browser must never receive
Docker hostnames such as `backend` or `lreca`.

The required acceptance flow is: submit a real sequence with LRECA and SEG; observe
queued -> running -> success or partial success; inspect prediction, feature, and
sequence views; verify history and JSON/CSV/FASTA exports; restart backend, worker,
Redis, PostgreSQL, and LRECA according to the test plan; reopen history; test a second
anonymous session; test retention and rate limits; then delete the analysis. Record
the actual outputs. None of this Docker flow has yet been executed on the audited
host.

### 6. Logs, stop, and reset

```powershell
docker compose logs --tail 200
docker compose logs --follow backend worker lreca
docker compose stop
docker compose down
```

`docker compose down` preserves named PostgreSQL and Redis volumes. The following is
a destructive reset and deletes all persisted analysis data in those volumes:

```powershell
docker compose down --volumes
```

Back up PostgreSQL before any destructive reset. See
[`backup_restore.md`](backup_restore.md) and [`operations.md`](operations.md).

## LRECA startup and concurrency contract

The private service performs this lifecycle once per container process:

```text
process becomes live
 -> verify mounted checkpoint SHA256
 -> load model once into RAM/VRAM
 -> model.eval()
 -> readiness becomes true
 -> serve controlled requests with the resident model
```

Missing or mismatched checkpoint keeps `/health/live` live but makes
`/health/ready` return 503 with `checkpoint_verified=false`; analysis is refused.
The model is not loaded per request. The default is one Uvicorn/model process,
`LRECA_MAX_CONCURRENT_REQUESTS=1`, and four Torch threads. Keep one model process per
GPU. Scale through the queue or explicitly provision one service per GPU instead of
adding web workers that duplicate the model in VRAM.

`LRECA_DEVICE=auto`, `cpu`, and `cuda` are accepted. The supplied Compose example
uses `cpu` until GPU container passthrough has been proved. Explicit `cuda` must fail
readiness when CUDA is unavailable; it must not silently change scientific results.
The current `compose.yaml` does not request a GPU device, so changing the environment
variable alone is insufficient. A future reviewed GPU override must grant the LRECA
container the intended NVIDIA device, keep one model process per assigned GPU, and be
accepted with `nvidia-smi`, CUDA availability, checkpoint identity, regression, and
memory/concurrency tests inside that container.

## SEG Linux build contract

The worker image fetches the fixed NCBI BLAST+ `2.17.0+` Linux x64 distribution at
build time through `scripts/setup_seg.py`, using the official audited MD5. It installs
`segmasker` at `/opt/ncbi-blast/bin/segmasker`, sets `BLAST_USAGE_REPORT=false`, and
defines build gates for `segmasker -version` plus a real 12-Q probe whose native
interval must be `0 - 11` (public coordinates 1-12). Runtime invocation retains
separate arguments, `shell=False`, stdin, timeout, and cleanup boundaries.

The Linux archive, dynamic libraries, build probe, and frozen Module 3 interval
fixtures have not run because Docker was unavailable. Their presence in the
Dockerfile is a gate definition, not passed Linux evidence.

## Part B - Future Ubuntu server deployment

This part is a future runbook. It was not tested in Module 10.

### 1. Host prerequisites

- Current Ubuntu LTS on x86_64/glibc, with security updates enabled.
- Docker Engine and the Compose v2 plugin installed from Docker's maintained
  repository, with the daemon enabled.
- At least the provisional hardware shown below, enough disk for images,
  PostgreSQL, encrypted backups, and the external checkpoint.
- A host firewall allowing SSH from an administrative allowlist and web ports 80/443
  only. PostgreSQL, Redis, backend, worker, and LRECA remain private.
- Optional GPU: a supported NVIDIA driver and NVIDIA Container Toolkit, followed by
  an actual CUDA container probe before selecting `LRECA_DEVICE=cuda`.

Clone a reviewed release or immutable commit into an application directory. Do not
deploy an unreviewed working tree. Store the checkpoint outside the first-party
Git-controlled source tree,
for example under `/srv/llps-explorer/models/lreca`, make it readable only by the
deployment account/container, and verify:

```sh
sha256sum /srv/llps-explorer/models/lreca/human_1_RCNN_ECA_parallel_089-0.9802.pt
```

Set `LRECA_MODEL_DIR=/srv/llps-explorer/models/lreca`; keep the in-container
`LRECA_CHECKPOINT_PATH` at `/models/lreca/...`. Create a protected `.env` with mode
0600 and new secrets. Start with CPU until Linux CPU regression passes.

### 2. First server start

```sh
python3 scripts/verify_deployment_static.py
docker compose config --quiet
docker compose build
docker compose up -d postgres redis lreca
docker compose run --rm migrate
docker compose up -d backend worker frontend reverse-proxy
docker compose ps
```

The normal `docker compose up -d` dependency graph also runs the one-shot migration;
the expanded sequence makes the first deployment easier to inspect. Perform the same
health, scientific regression, ownership, retention, restart, export, and backup
acceptance described in Part A before accepting traffic.

### 3. Domain and HTTPS

Point the domain's DNS A record, and AAAA only when IPv6 is correctly routed, to the
server. Replace local URLs with the exact HTTPS origin:

```dotenv
PUBLIC_BASE_URL=https://proteins.example.org
PUBLIC_HTTPS=true
CORS_ALLOWED_ORIGINS=https://proteins.example.org
SESSION_COOKIE_SECURE=true
PUBLIC_DOMAIN=proteins.example.org
```

[`docker/caddy/Caddyfile.production.example`](../docker/caddy/Caddyfile.production.example)
shows the intended same-origin TLS policy, but `compose.yaml` does not load it. The
current Compose file publishes only local HTTP and stores Caddy state in tmpfs. A
reviewed server override must mount the production Caddyfile, publish ports 80 and
443, persist `/data` and `/config` for certificate renewal, and retain only Caddy as
the public service. Confirm the container's non-root port binding strategy on the
target host. Then verify certificate issuance/renewal, HTTP-to-HTTPS behavior, Secure
cookies, security headers, API no-store headers, Origin checks, and browser console.

No public server, DNS, firewall, or Let's Encrypt request was configured in Module
10. The current status is `PUBLIC_HTTPS_UNVERIFIED`.

### 4. Updates and rollback

1. Create and verify an encrypted PostgreSQL backup.
2. Record the deployed Git revision and image digests.
3. Check out the reviewed release, validate Compose, and build versioned images.
4. Run the one-shot migration once, start services, and require readiness plus a
   scientific smoke test.
5. Roll back application images only when the migrated schema is backward compatible.
   Otherwise stop writes and restore the matching pre-update database backup before
   starting the older release. Never casually downgrade a live schema.

## Provisional server sizing

There is no Module 10 Docker benchmark, so these are initial capacity-testing targets,
not measured Linux production requirements:

| Profile | CPU | RAM | Storage | GPU | Intended use |
| --- | ---: | ---: | ---: | --- | --- |
| Minimum CPU pilot | 4 vCPU | 8 GB | 40 GB SSD | none | single-user, one RQ worker and one LRECA request; Compose memory caps must be reduced/rebalanced for this host |
| Recommended CPU | 8 vCPU | 16 GB | 80 GB SSD | none | initial multi-user validation with the supplied conservative concurrency |
| Optional GPU | 8 vCPU | 16 GB | 80 GB SSD | NVIDIA, provisional minimum 4 GB VRAM; 6-8 GB preferred | faster global/attribution work after Toolkit and Linux regression testing |

The basis is the measured Windows Module 1 adapter wall time (one warm-up, three
samples per case):

| Length | CPU global ms | CPU full ms | CUDA global ms | CUDA full ms |
| ---: | ---: | ---: | ---: | ---: |
| 50 | 5.313 | 89.593 | 5.727 | 81.656 |
| 100 | 15.468 | 112.136 | 5.369 | 96.766 |
| 500 | 37.764 | 410.552 | 17.475 | 363.562 |
| 1000 | 86.853 | 1085.733 | 32.103 | 1038.957 |
| 2000 | 150.881 | 3650.193 | 64.025 | 3676.974 |

`full` means global prediction plus Grad-CAM plus KDE. At 2,000 aa, KDE alone was
about 3.1 seconds and runs on CPU, which explains why CUDA greatly improves global
prediction but barely changes the full request. The scientific worker lifetime peak
RSS was 527.332 MiB on CPU and 779.648 MiB on CUDA; CUDA peak allocated memory was
124.979 MiB. These exclude the API, database, Redis, Next.js, and container overhead
and are not per-request increments. One hundred measured attributions kept
`load_count=1` without concerning accumulation over that finite run.

The Module 3 Windows SEG medians were 40.2523, 36.6625, 39.5880, 36.7700, and
40.0375 ms for 100, 500, 1,000, 2,000, and 5,000 aa respectively, including process
startup and parsing. They do not predict Linux/container throughput. Re-run CPU and
optional GPU benchmarks inside the actual container and size from p95 latency,
concurrent queue depth, total RSS, database growth, and backup volume before public
deployment.
