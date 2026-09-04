# Module 10 command and verification record

Date: 2026-09-04. Paths in this record are repository-relative or normalized as
`${PROJECT_ROOT}`; no workstation absolute path is part of deployment configuration.

This file separates commands actually executed on the Windows host from commands
blocked by the missing Docker runtime. A listed Docker command is not evidence that
it ran.

## Actually executed: Docker environment audit

The audit checked the Docker CLI, Compose, daemon information, common Docker Desktop
installation/service/process indicators, and alternative container CLIs. The
machine-level result was written to
[`audit/module10/docker_runtime_audit.json`](audit/module10/docker_runtime_audit.json):

```json
{
  "observed_at_utc": "2026-09-04T05:26:59.1846481Z",
  "host_platform": "windows",
  "docker_cli_available": false,
  "docker_common_installation_found": false,
  "docker_service_found": false,
  "docker_process_found": false,
  "alternative_container_cli_found": false,
  "linux_containers_confirmed": false,
  "docker_daemon_confirmed": false,
  "docker_compose_confirmed": false,
  "status": "DOCKER_RUNTIME_UNAVAILABLE"
}
```

The required user-facing probes are:

```powershell
docker --version
docker compose version
docker info
```

All three commands were directly attempted and each ended before process start with
`CommandNotFoundException`; the sanitized record is
[`audit/module10/docker_commands_attempt.log`](audit/module10/docker_commands_attempt.log).
Therefore `docker compose config`, build/start, and every container/E2E check below
were not executed.

## Actually executed: daemon-free deployment validation

Command:

```powershell
.\.venv\Scripts\python.exe scripts\verify_deployment_static.py
```

Result: **93 checks passed, 0 failed**. The checker explicitly returned:

```text
status=passed
docker_runtime_required=false
docker_build_or_runtime_claim=not_performed_by_this_static_check
```

The checks cover required services, fixed image tags, one-shot migration, private
ports/network, non-root/read-only application containers, healthcheck declarations,
read-only checkpoint mount, no checkpoint `COPY`, blob-filtered sparse LRECA source,
absence of upstream model blobs from the copied source repository, required
environment variables, LRECA process count/source commit, SEG fixed
installer/version/probe, worker heartbeat, Caddy routing/headers, ignore rules, and
backup/restore script guards. This is source inspection only.

The Dockerfile's sparse-source construction was also reproduced with host Git against
the exact upstream commit. The six allowlisted source/data files were present, the
working tree stayed clean after remote removal, and none of the seven upstream model
blob objects was present. Evidence:
[`audit/module10/lreca_sparse_source_probe.json`](audit/module10/lreca_sparse_source_probe.json).
This validates the source-sanitization mechanism, not a Docker build or final image
layer scan.

The Compose file was also parsed with PyYAML 6.0.3. YAML syntax and **7/7** selected
topology invariants passed; this does not replace Docker Compose schema validation.
Evidence: [`audit/module10/compose_yaml_parse.json`](audit/module10/compose_yaml_parse.json).

## Actually executed: sensitive tracked-file audit

The repository-safe-directory option was scoped to this invocation; no global Git
trust setting was changed. Normalized command:

```sh
git -c safe.directory="${PROJECT_ROOT}" ls-files '*.pt' '*.pth' '*.ckpt' '*.safetensors' '.env' 'backups/*' 'exports/*' '*.pem' '*.key'
```

Result: **no output**. No matching checkpoint, environment file, backup, export, or
private-key path was tracked at the time of the audit. `.gitignore` and
`.dockerignore` were also reviewed and contain these classes.

## Actually executed: host quality and regression gates

The final host gates were:

```text
Backend full pytest:                       816 passed, 0 failed
Module 10 focused backend pytest:           35 passed, 0 failed
Frontend full unit tests:                   324 passed, 0 failed
Module 8 saved-artifact regression:         263/263 passed
Backend Ruff / compileall / pip check:      passed / passed / passed
Backend 0.10.0 wheel build:                 passed
Frontend lint / typecheck / production build: passed / passed / passed
Next standalone server:                    generated
Browser JavaScript privacy scan:           14 assets, 0 forbidden findings
```

Primary evidence:

- [`audit/module10/backend_full_final.log`](audit/module10/backend_full_final.log) and
  [`backend_full_final.junit.xml`](audit/module10/backend_full_final.junit.xml)
- [`audit/module10/backend_module10_final.log`](audit/module10/backend_module10_final.log)
- [`audit/module10/frontend_tests_final.log`](audit/module10/frontend_tests_final.log),
  [`frontend_lint_final.log`](audit/module10/frontend_lint_final.log),
  [`frontend_typecheck_final.log`](audit/module10/frontend_typecheck_final.log), and
  [`frontend_build_final.log`](audit/module10/frontend_build_final.log)
- [`audit/module10/module8_api_regression.json`](audit/module10/module8_api_regression.json)
- [`audit/module10/frontend_bundle_privacy.json`](audit/module10/frontend_bundle_privacy.json)
- [`audit/module10/backend_lint_final.log`](audit/module10/backend_lint_final.log),
  [`compileall_final.log`](audit/module10/compileall_final.log),
  [`pip_check_final.log`](audit/module10/pip_check_final.log), and
  [`backend_wheel_final.log`](audit/module10/backend_wheel_final.log)

The 263/263 wrapper read saved JSON/TSV/FASTA and frozen/current mapper bytes only; it
made zero HTTP requests, created zero jobs, and ran zero model inference. It is not a
current API or Linux scientific execution.

The generated wheel is `llps_explorer_backend-0.10.0-py3-none-any.whl`. Test totals
come only from complete suites; focused reruns are not added to them.

## Initial regression findings and resolution

The retained initial full backend run is
[`audit/module10/backend_full.log`](audit/module10/backend_full.log) with JUnit in
[`audit/module10/backend_full.junit.xml`](audit/module10/backend_full.junit.xml). Its
command was the backend pytest suite with Module 10 additions and an isolated base
temporary directory. It was an intermediate run:

```text
811 passed, 2 failed, 4 warnings in 102.22 s
```

The two initial failures were resolved as follows:

1. The orchestrator could publish the final method as terminal one event-loop turn
   before publishing the job terminal state. It now writes both in the same immutable
   snapshot, while retaining the old final publication as an active-state fallback.
2. an obsolete assertion expecting a private checkpoint absolute path in logs, which
   conflicts with the Module 10 safe-metadata rule; the test now requires the filename
   and SHA while rejecting the absolute path.

The exact cases and related analysis/orchestrator/queue tests passed, followed at
that stage by the complete 813-test suite. Intermediate command:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q `
  --basetemp .audit\module10_pytest_full_final `
  --junitxml docs\audit\module10\backend_full_final.junit.xml
```

Result at that point: **813 passed, 3 warnings in 65.03 s**. The warnings are two upstream
deprecations and a non-fatal inability to write `backend/.pytest_cache`; the isolated
pytest base temp itself worked. No failed or skipped scientific assertion remains.

A later independent review found three deployment-boundary issues: upstream LRECA
weights would have been transitively copied through the full Git checkout, the legacy
health response still reported Module 9, and generic LRECA execution failures were too
broadly considered retryable. The source stage now performs a blob-filtered sparse
checkout and rejects model blobs; health reports Module 10; only transient
unavailable/timeout failures and the existing busy-after-timeout state qualify for
method retry. Three focused retry-classification cases were added.

The first complete rerun after those changes retained two obsolete `module == 9` test
expectations. That intermediate evidence is kept in
[`audit/module10/backend_full_postreview_failed.log`](audit/module10/backend_full_postreview_failed.log)
and [`backend_full_postreview_failed.junit.xml`](audit/module10/backend_full_postreview_failed.junit.xml):

```text
814 passed, 2 failed, 4 warnings in 75.47 s
```

Both version-contract assertions were updated to Module 10 and passed directly. The
final complete suite then passed:

```text
816 passed, 3 warnings in 63.98 s
```

Final command:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q `
  --basetemp .audit\module10_pytest_full_final_v2 `
  --junitxml docs\audit\module10\backend_full_final.junit.xml
```

## Actually executed: scope and documentation validation

The scope audit compared the current bytes with the immutable 532-file Module 10
start manifest. Final result:

```text
65 added, 25 modified, 0 deleted, 90 total changed
43 frozen scientific files reviewed, 0 changed
0 unexpected changes, 0 violations
```

Evidence is in [`audit/module10/scope_review.json`](audit/module10/scope_review.json)
and [`module10_changed_files.txt`](module10_changed_files.txt). Added files include
the retained test and audit evidence. The separate documentation validator confirmed
all required Module 10 documents, local Markdown targets, answers 1 through 30, and
the exact report closing; evidence is
[`audit/module10/documentation_validation.json`](audit/module10/documentation_validation.json).

## Docker commands not executed

All rows below are `NOT RUN - DOCKER_RUNTIME_UNAVAILABLE`.

| Area | Required command/check | Evidence still needed |
| --- | --- | --- |
| Compose render | `docker compose config --quiet` | valid expanded topology without disclosure of rendered secrets |
| Build | `docker compose build` | image names, digests, sizes, duration, warnings, SEG build probes |
| Start | `docker compose up -d` and `docker compose ps` | migration exit 0; seven long-running services healthy |
| Local edge | request `http://localhost/healthz` and `/api/v1/*` | real Caddy forwarding and headers |
| PostgreSQL | `pg_isready`, fresh migration, restart | schema at head and named-volume persistence |
| Redis/RQ | Redis PING, queue depth, worker health | real async execution and completed-result survival |
| LRECA CPU | internal readiness plus real frozen inference | SHA verified, one load, CPU result within scientific tolerance |
| LRECA GPU | Toolkit/CUDA probe plus inference | `GPU_DOCKER_NOT_TESTED` until actually run |
| SEG Linux | version, 12-Q probe, Module 3 fixtures | fixed Linux binary and intervals match baseline |
| Recovery | kill/restart worker during queued/running job | no permanently running job; retry/requeue/interrupted reason |
| Persistence | restart backend, worker, Redis, PostgreSQL, LRECA | history and exports remain correct |
| Ownership | two independent sessions through Caddy | session B cannot get/list/export/delete session A's job |
| Retention | short isolated expiry/cleanup configuration | DB/history/import cleanup at periodic interval |
| Limits | lowered rate/queue thresholds, oversize input | structured 429/503/413 and normal flow unaffected |
| Backup/restore | scripts against isolated project/database | restored owned job/results/exports and privacy lifecycle |
| Performance | 100/500/1000/2000 aa, optional 5000 aa | Linux CPU global/full/SEG and optional GPU measurements |
| Browser E2E | full real LRECA+SEG workflow at localhost | viewers, residue detail, history, downloads, delete |
| Container security | sockets, UID/caps, image/layer and bundle scan | only Caddy public; no secrets/model/path leak |

No image name/size, build duration, warning set, container status, Linux regression,
Docker performance result, restart result, or backup result exists to report.

## Commands for the next Windows Docker Desktop run

These are pending procedures:

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'

docker --version
docker compose version
docker info --format '{{json .OSType}}'

Copy-Item -LiteralPath .env.example -Destination .env
New-Item -ItemType Directory -Force -Path .\models\lreca | Out-Null
Get-FileHash -LiteralPath .\models\lreca\human_1_RCNN_ECA_parallel_089-0.9802.pt -Algorithm SHA256

.\.venv\Scripts\python.exe scripts\verify_deployment_static.py
docker compose config --quiet
Measure-Command { docker compose build }
docker compose images
docker compose up -d
docker compose ps --all

Invoke-WebRequest -UseBasicParsing http://localhost/healthz
Invoke-RestMethod http://localhost/api/v1/health/live
Invoke-RestMethod http://localhost/api/v1/health/ready
Invoke-RestMethod http://localhost/api/v1/system/status
Invoke-RestMethod http://localhost/api/v1/version

docker compose logs --tail 200
docker compose stop
docker compose down
```

The checkpoint hash must be:

```text
aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc
```

Do not put generated secrets or an expanded Compose configuration into this document.
`docker compose down` preserves volumes; `docker compose down --volumes` is an
explicit destructive reset and must follow a verified backup and target-name review.

## Pending component probes after start

```sh
docker compose exec -T postgres sh -c 'pg_isready --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"'
docker compose exec -T redis sh -c 'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" ping'
docker compose exec -T redis sh -c 'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" LLEN rq:queue:analysis'
docker compose exec -T worker python /opt/llps/worker_healthcheck.py
docker compose exec -T lreca python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8001/health/ready', timeout=3)))"
docker compose exec -T worker /opt/ncbi-blast/bin/segmasker -version
printf '>module10_probe\nQQQQQQQQQQQQ\n' | docker compose exec -T worker /opt/ncbi-blast/bin/segmasker -in - -out - -infmt fasta -outfmt interval -window 12 -locut 2.2 -hicut 2.5
```

Expected SEG native probe interval is `0 - 11`; expected public interval is 1-12.
Expected LRECA readiness reports verified and loaded with the audited checkpoint
identity and no path.

## Pending backup and restore drill

Run from a trusted POSIX shell against an isolated Compose project:

```sh
./scripts/backup_db.sh backups/module10-restore-test.dump
sha256sum backups/module10-restore-test.dump
docker compose exec -T postgres pg_restore --list <backups/module10-restore-test.dump >/dev/null
./scripts/restore_db.sh backups/module10-restore-test.dump --confirm-replace
```

The exact isolation and privacy procedure is in
[`backup_restore.md`](backup_restore.md). These commands have not run.

## Future Ubuntu/domain commands

After installing Docker Engine/Compose and preparing protected configuration:

```sh
sha256sum /srv/llps-explorer/models/lreca/human_1_RCNN_ECA_parallel_089-0.9802.pt
chmod 600 .env
python3 scripts/verify_deployment_static.py
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

DNS A/AAAA, public firewall, production Caddy override, ports 80/443, persistent
certificate storage, automatic HTTPS, Secure cookies, and renewal must be configured
and tested on the actual server. They were not executed in Module 10; current status
is `PUBLIC_HTTPS_UNVERIFIED`.
