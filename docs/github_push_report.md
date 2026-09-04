# GitHub Push Report

Report date: 2026-09-04

Status: `GITHUB_PUSH_COMPLETED`

## Repository and commit

| Field | Verified result |
| --- | --- |
| GitHub owner | `LQY-art-wq` |
| Repository | `LQY-art-wq/llps-explorer` |
| Visibility | Private |
| Branch | `main` |
| Upstream | `origin/main` |
| Primary commit message | `feat: complete LLPS Explorer core platform through module 10` |
| Local primary commit SHA | `9e780a26026179689defcacf005a91aa06914d4a` |
| Remote primary commit SHA | `9e780a26026179689defcacf005a91aa06914d4a` |
| Local/remote primary SHA match | YES |
| Report commit message | `docs: record verified GitHub push` |

The repository was created without GitHub-generated initialization, so the
primary commit is the root commit and did not overwrite any remote history.
The report itself is added by the subsequent documentation-only commit named
above; a commit cannot embed its own content-derived SHA. The final local and
remote SHA for that report commit is recorded by the post-push verification and
the task completion output.

## Push verification

Result: **PASS**

- Local Git reported a successful new-branch push and configured `main` to
  track `origin/main`.
- Local `git rev-parse HEAD` and `git ls-remote origin refs/heads/main` both
  returned the primary SHA above.
- GitHub Connector independently returned the same full SHA and commit message.
- GitHub Connector reported exactly one commit at the primary verification
  point, confirming that the pushed root commit was current.
- GitHub metadata confirmed `private`, default branch `main`, and a non-null
  push timestamp.

## Scientific freeze result

Result: **PASS**

- 43/43 staged frozen scientific files matched their expected SHA256.
- 6/6 pinned LRECA upstream source files matched their recorded hashes.
- `external/seg-source.json` matched its frozen SHA256 in both the working tree
  and Git blob; Git line-ending conversion was explicitly disabled for this
  byte-hashed manifest.
- LRECA remains Human-specific with positive class index 1, real global
  prediction, official Grad-CAM behavior, official KDE precision/segmentation,
  and public 1-based inclusive coordinates.
- SEG remains an NCBI `segmasker` LCR annotation only.
- FuzDrop remains `MANUAL_IMPORT_ONLY` with no automatic official-site call or
  CAPTCHA bypass.
- DisMeta remains `INTEGRATION_BLOCKED` with no substitute IDR predictor.
- The weighted ensemble remains limited to LRECA plus validated FuzDrop input
  and remains explicitly uncalibrated.

## Model blob audit

Result: **PASS**

- Local staged model/checkpoint blobs: 0.
- All seven upstream LRECA checkpoint files matched the repository manifest and
  remained ignored and outside the Git index.
- The GitHub recursive tree was complete (`truncated=false`) and contained 598
  files. Model/checkpoint extension matches: 0.
- Exact remote match for
  `human_1_RCNN_ECA_parallel_089-0.9802.pt`: 0.
- No model was uploaded through Git LFS.

## Secret audit

Result: **PASS**

- Local staged high-confidence real credentials, tokens, and private keys: 0.
- Two DSN-like test values were reviewed as synthetic fixtures.
- Two AWS-key-shaped lexical matches were reviewed inside a frozen amino-acid
  sequence and its audit copy; both are biological sequence data.
- GitHub remote tree matches for private-key file extensions: 0.
- GitHub code-search matches for private-key block markers: 0.
- Only placeholder environment examples are present; non-example `.env` files
  are absent locally and remotely.

## User-data and fixture audit

Result: **PASS**

- Database, backup, Redis persistence, upload, user export, and runtime-data
  paths were absent from both the staged snapshot and GitHub tree.
- The local runtime SQLite database remains ignored and was not uploaded.
- 24/24 fixture files matched their provenance manifests.
- Public/official regression fixtures and explicitly labeled synthetic fixtures
  remain confined to tests and audit evidence. No unclear-provenance user
  research data was found.

## Test and quality summary

| Gate | Result |
| --- | --- |
| Backend full pytest | 816 passed, 0 failed, 0 skipped; 3 warnings |
| Module 10 focused pytest | 35 passed, 0 failed, 0 skipped |
| Backend Ruff documented scope | PASS; 0 errors |
| Python compile/import/package checks | PASS |
| Frontend unit tests | 324 passed, 0 failed, 0 skipped |
| Frontend lint/typecheck/production build | PASS |
| Frozen scientific/API regression | 263/263 PASS |
| Deployment static gate | 93/93 PASS |
| Staged diff whitespace check | PASS |

## Deployment status

Current deployment status: `DEPLOYMENT_BLOCKED`

Module 10 prepared the deployment configuration and passed static checks, but
Docker CLI, Docker Compose, and a Docker daemon were unavailable. No Linux
container stack or public server deployment has been executed.

Known blockers retained:

- Docker runtime was unavailable during Module 10.
- The Linux Docker stack was not executed.
- PostgreSQL, Redis/RQ, worker, and LRECA-service Docker end-to-end behavior was
  not executed.
- LRECA and SEG Linux scientific regression and performance were not executed.
- Restart recovery and PostgreSQL backup/restore were not executed in Docker.
- Public server deployment is unverified.
- Domain, DNS, firewall, and HTTPS are not configured.
- FuzDrop remains manual import only.
- DisMeta integration remains blocked.
