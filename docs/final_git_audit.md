# Final Repository and Git Freeze Audit

Audit date: 2026-09-04

Current result: `PRECOMMIT_AUDIT_PASSED`

This is the pre-commit audit of the completed Module 0–10 working tree. The
target private GitHub repository was created with explicit user authorization,
confirmed through both GitHub repository metadata and the GitHub Connector, and
matched to local `origin`. Host-specific absolute paths are intentionally
omitted from this repository artifact.

## Repository state

| Field | Result |
| --- | --- |
| Repository root | `.` (LLPS Explorer working tree) |
| Branch | `main` |
| HEAD before commit | `UNBORN`; the repository has no commits |
| Configured remote | `origin` → `https://github.com/LQY-art-wq/llps-explorer.git` |
| Upstream branch | None |
| Connected GitHub account | `LQY-art-wq` |
| GitHub App installations | One user installation |
| Repositories visible to the GitHub connection | 1; the target below |
| Target GitHub repository | `LQY-art-wq/llps-explorer` |
| Repository visibility | Private |
| Remote default branch | `main` |
| Target remote branch | `origin/main` |
| Modified files relative to a parent commit | 0; no parent commit exists |
| Staged added files | 598 |
| Deleted files | 0 |
| Remaining intent-to-add index entries | 0 |
| Untracked files | 0 |
| Unstaged changes | 0 |

The authenticated GitHub API created the repository without initialization.
Read-only GitHub Connector refreshes then returned exactly this repository from
both the account-wide and installation-specific listings. Metadata confirmed
`private`, default branch `main`, size 0, no prior push, and zero commits. Local
`git ls-remote` independently confirmed the configured remote was empty.

Before staging, the candidate set contained 598 unignored files: 51
intent-to-add index entries and 547 untracked files. After `git add -A`, all 598
are staged as additions with no unstaged or untracked remainder. The repository
has no parent commit, so they represent the first complete Module 0–10 commit
candidate. The working-tree set totals approximately 8.314 MiB.

## Scientific freeze audit

Result: **PASS**

- 43/43 frozen scientific files matched the immutable Module 10 SHA256
  baseline; mismatches: 0.
- 6/6 pinned LRECA upstream source files matched their recorded hashes.
- The pinned upstream commit remains
  `0b4b48ab7870529a34028c6e30dfba42eddbf215`.
- The selected Human checkpoint remains
  `human_1_RCNN_ECA_parallel_089-0.9802.pt`, size 2,395,318 bytes, SHA256
  `aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc`.
- LRECA still maps label/class index 1 to the positive `P` class and exposes the
  positive-class softmax as an uncalibrated score.
- Global classification, official Grad-CAM behavior, official four-decimal KDE
  input conversion, score-space KDE segmentation, and the documented upstream
  terminal-residue behavior remain unchanged.
- Public residue and region coordinates remain 1-based inclusive.
- SEG remains an NCBI `segmasker` low-complexity annotation only. It does not
  emit an LLPS score or join the ensemble.
- FuzDrop remains `MANUAL_IMPORT_ONLY`; no automatic request, scraping,
  CAPTCHA bypass, Selenium/Playwright bypass, or private-endpoint transport was
  found.
- DisMeta remains `INTEGRATION_BLOCKED`; no alternative IDR predictor is used
  as a substitute.
- The weighted ensemble accepts only successful LRECA and validated FuzDrop
  global results. Without FuzDrop it remains unavailable; it does not silently
  convert LRECA to 100% weight. The score remains explicitly uncalibrated.

Known scientific limitations are unchanged: the LRECA dataset-5 provenance
mapping is not confirmed, and the SEG Linux distribution manifest does not yet
contain an independently pinned binary SHA256.

## Model blob audit

Result: **PASS**

- Commit candidates with model/checkpoint extensions: 0.
- Git index entries containing model blobs: 0.
- Files at or above GitHub's 100 MB single-file limit: 0.
- A raw-filesystem scan found 221 model-like test or checkpoint artifacts: 214
  ignored audit/test artifacts and the seven ignored upstream LRECA checkpoint
  blobs below. None is a commit candidate.
- `external/lreca/`, common model extensions, `models/`, and `checkpoints/` are
  excluded by `.gitignore`.
- The root Docker build context excludes `external/lreca`, model directories,
  and model extensions. The LRECA container design fetches pinned source and
  mounts the selected checkpoint at runtime; it does not copy these blobs from
  the host build context.

### Seven-model-blob verification

All seven files matched the repository model manifest by filename, size, and
SHA256 and remained ignored/unindexed.

| Filename | Bytes | SHA256 |
| --- | ---: | --- |
| `mydata_1507_RCNN_ECA_089-0.9930.pt` (saliency model) | 2,393,227 | `700f11d557da5a739b704564cf5c5d9dcfabca5c401ee169cc383c5a11fe9988` |
| `human_1_RCNN_ECA_parallel_089-0.9802.pt` | 2,395,318 | `aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc` |
| `model_high_2.pt` | 5,491,418 | `0171db33c1ba8c2a7f6a585c02b1c5d2704e94d21f9483f2100a710e22b04499` |
| `model_LLPS_0.pt` | 8,209,934 | `0f8149444ae9438ee74f481e9b1e3b4355aa67354408a47dba78a5c6a2167a69` |
| `model_mydata_1.pt` | 4,339,162 | `675bb1c9ea374d161c210c2f5b9fe69e49bd5afb59ea355662d107f4332a456c` |
| `model_R_3.pt` | 4,339,162 | `ceb4035d5248d2e0b1e3dbd3764ac18455f44cdbba07a6607dc64f8c29e1c5bc` |
| `mydata_1507_RCNN_ECA_089-0.9930.pt` (trained model) | 2,393,227 | `700f11d557da5a739b704564cf5c5d9dcfabca5c401ee169cc383c5a11fe9988` |

## Secret and configuration audit

Result: **PASS**

- High-confidence private-key, GitHub token, OpenAI key, AWS key, Slack token,
  and equivalent credential findings in commit candidates: 0.
- An AWS-key-shaped regex produced two lexical matches inside the same
  4,486-residue amino-acid sequence stored in a frozen fixture and its audit
  copy. Both values contain only the 20 standard amino-acid letters and were
  reviewed as biological sequence data, not credentials.
- Two DSN-like strings were reviewed in queue tests and are synthetic test
  values, not usable credentials.
- `.env.example` files contain placeholders only. Real `.env` variants are
  ignored.
- Runtime source and production configuration contain zero dependencies on a
  Windows user directory or other host-specific absolute path.
- Nine preserved Module 10 log/JUnit evidence files contain 47 textual matches
  across 26 lines for the historical Windows workspace path. They contain no
  secret, password, token, or private server address and are retained as
  immutable historical evidence, as required by the task.

## User data and fixture provenance audit

Result: **PASS**

- Commit candidates contain no runtime SQLite/PostgreSQL database, backup,
  Redis persistence file, user export, upload directory, or runtime data
  directory.
- The local runtime SQLite database is ignored and unindexed. It is not part of
  the commit or Docker build context.
- 24/24 frozen fixture files matched their provenance manifests: 16 Module
  6–8 browser/scientific fixtures and 8 SEG fixtures.
- Across the sequence fixtures, ten distinct sequences map to documented public
  or official frozen baselines and one 45-residue sequence is explicitly
  documented as synthetic. No fixture with unclear provenance was found.
- Synthetic FuzDrop fixtures remain limited to test/development evidence and
  are not seeded or displayed by the production default path.

## Large-file audit

Result: **PASS**

The 597-file pre-report candidate set totaled approximately 8.303 MiB.

| Threshold | Candidate files |
| --- | ---: |
| Greater than 10 MB | 0 |
| Greater than 50 MB | 0 |
| Greater than 100 MB | 0 |

## `.gitignore` audit

Result: **PASS**

The rules cover Python and Node caches, Next.js output, coverage files, local
environments, model/checkpoint extensions including `*.weights`, SQLite,
PostgreSQL backups, Redis/AOF data, exports, uploads, runtime user data, logs,
Docker runtime data, credentials/certificates, OS files, and IDE-private files.
Source, migrations, Dockerfiles, Compose, lockfiles, manifests, SHA256 metadata,
and documentation remain eligible. Historical logs below `docs/audit/` are an
intentional exception and were separately scanned.

## `.dockerignore` audit

Result: **PASS**

The root Docker context excludes Git metadata, local environments, credentials,
certificates, the upstream LRECA checkout, all audited model extensions,
databases, backups, Redis/PostgreSQL runtime data, uploads, exports, nested
logs, dependencies, caches, local builds, and test evidence. The seven upstream
checkpoint blobs are outside the build context.

## Verification results

All runnable host/static gates passed. Test output generated for this audit is
kept under the ignored `.audit/final_git/` directory.

| Gate | Result | Scope / duration |
| --- | --- | --- |
| Backend full pytest | **PASS** | 816 passed, 0 failed, 0 skipped, 3 warnings; 73.835 s pytest / 76.020 s process |
| Module 10 focused pytest | **PASS** | 35 passed, 0 failed, 0 skipped; 2.343 s pytest |
| Ruff documented scope | **PASS** | `backend/app` and `backend/tests`; 0 errors |
| Python compile | **PASS** | app, worker, LRECA runtime/service, and scripts |
| Dependency check | **PASS** | `pip check` reported no broken requirements |
| Source import | **PASS** | app, worker, LRECA runtime, and LRECA service |
| Fresh wheel | **PASS** | version 0.10.0 built and all required packages imported |
| Source/checkpoint identity | **PASS** | 7 checkpoints and 2 vocabulary sources verified; no inference run |
| Frontend unit tests | **PASS** | 324 passed, 0 failed, 0 skipped; 4.94 s |
| Frontend lint | **PASS** | zero warnings/errors |
| Frontend typecheck | **PASS** | completed successfully |
| Frontend production build | **PASS** | completed successfully |
| Frozen Module 8 API regression | **PASS** | 263/263; 10/10 frozen files unchanged; 0 HTTP, jobs, or inference |
| Deployment static gates | **PASS** | 93/93 after the final ignore-rule update |

The current root virtual environment still contains a stale editable package
registration for version 0.5.0. Source-path imports and a fresh version 0.10.0
wheel both passed, so this is a local environment refresh item rather than a
source or packaging failure. The documented Ruff scope passes; an optional
expanded scan reports 20 pre-existing line-length findings in two Module 10
audit scripts.

## Current deployment truth

Status: `DEPLOYMENT_BLOCKED`

Module 10 completed deployment code, static validation, topology, and
operational documentation. Docker CLI, Docker Compose, and a Docker daemon were
unavailable, so no Docker image or Linux container was built or started.

Known blockers:

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

## Commit and push gate

Result: **READY FOR COMMIT AND PUSH**

- The private target repository is uniquely confirmed as
  `LQY-art-wq/llps-explorer`.
- Local `origin` exactly matches the Connector clone URL.
- The remote is empty, so the first push cannot overwrite existing history.
- No model blob, secret, database, backup, user export, or unclear-provenance
  fixture is present in the staged snapshot.
- All runnable test, quality, scientific-freeze, and static-deployment gates
  passed.
- The staged snapshot contains 598 files; no file exceeds 10 MiB.
- `git diff --cached --check` passes. Exact historical audit bytes are retained
  through path-specific whitespace attributes rather than editing the evidence.
- All 43 frozen scientific files match their expected SHA256 in the Git index.
  `external/seg-source.json` is explicitly staged byte-for-byte without line-end
  normalization so its frozen manifest hash remains unchanged.

The remaining ordered actions are the initial commit, a normal upstream-setting
push to `origin/main`, and local plus GitHub Connector SHA verification.

Final pre-commit gate status: `PRECOMMIT_AUDIT_PASSED`
