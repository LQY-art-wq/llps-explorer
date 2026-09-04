# LLPS Explorer deployment security

This document records the Module 10 security design and its verification boundary.
Source/configuration inspection and host-side tests are possible; runtime network,
container-user, firewall, TLS, and reverse-proxy behavior were not exercised because
the audited host had no Docker runtime. Findings labelled as configuration properties
must be rechecked on the deployed Linux host.

## Trust and network boundaries

```text
Untrusted browser
   |
   | HTTP locally; HTTPS on a future public server
   v
Caddy : only published host service
   |-- /      -> Next.js production server
   `-- /api/* -> FastAPI backend
          |-- PostgreSQL: private internal network
          |-- Redis/RQ: private internal network
          `-- worker: no listener exposed
                  |-- LRECA private HTTP service
                  `-- SEG child process
```

`compose.yaml` publishes only `${HTTP_PORT:-80}:8080` on Caddy. PostgreSQL, Redis,
backend, worker, and LRECA have no host `ports` mapping. The `app-internal` network is
declared `internal: true`; only backend needs both edge and internal connectivity.
The browser uses same-origin `/api/*` and must never receive `backend:8000`,
`lreca:8001`, database/Redis locations, or checkpoint paths.

Static deployment validation checks this topology, absence of Docker socket/host
namespace access, pinned images, and private checkpoint mounting. Actual listening
sockets and firewall rules remain unverified until the stack runs.

## Anonymous ownership

On the production-like Caddy path, FastAPI creates one 32-byte random base64url
session credential when the cookie/header is absent or invalid and stores it in the
`llps_analysis_session` cookie. The non-Docker Next development proxy can create the
same credential and forward it server-side in `X-Analysis-Session`; FastAPI accepts
either the cookie or that header. The raw credential is not persisted in the
analysis row; ownership uses its digest. A request with a different owner receives
404 for job retrieval, history, export, and delete, avoiding both disclosure and a
resource-existence oracle.

This is anonymous possession-based access, not an account system. Clearing the cookie,
switching browsers/profiles, or losing it loses access to retained analyses. There is
no email/account recovery. The cookie must never be pasted into logs, tickets, URLs,
analytics, or client-readable JavaScript.

The cookie is `HttpOnly`, `SameSite=Lax`, path `/`, and has a long technical maximum
age so it can outlive retained jobs. Actual analysis data still expires according to
`ANALYSIS_RETENTION_DAYS`; cookie lifetime does not extend data retention. `Secure`
is false only for current localhost HTTP. FastAPI derives it from configured public
HTTPS unless explicitly configured; the non-Docker Next proxy derives it from its
request protocol. Future TLS configuration must set `PUBLIC_HTTPS=true` and
`SESSION_COOKIE_SECURE=true`; production settings reject an insecure cookie when
HTTPS is declared.

Ownership isolation through the real Caddy path has not yet been Docker/browser
tested. Acceptance requires two independent cookie jars: session A can create,
retrieve, list, export, and delete its job; session B must receive 404 for every
operation on A's job.

## CSRF and CORS decision

Cookie-backed browser mutations are protected on the production-like Caddy path by:

- FastAPI checks `Origin` against the configured CORS origins and public base origin
  for unsafe analysis and FuzDrop-import paths;
- `SameSite=Lax` reduces cross-site cookie sending, and the cookie is HttpOnly;

The non-Docker development path through the Next same-origin proxy adds its own
`Origin`/`Host` check plus a route/method allowlist before forwarding. Caddy routes
production-like `/api/*` directly to FastAPI, so those Next-only controls are not
claimed as a second production layer.

Non-browser API clients may omit `Origin`; in that case the ownership header/secret
is a bearer credential and must be protected as such. A present foreign or malformed
Origin is rejected with structured 403. This supports CLI use without adding a user
account/CSRF-token system.

Production CORS must contain exact approved origins. `*` is rejected by production
configuration. For local HTTP the example allows only `http://localhost`. For future
TLS, `PUBLIC_BASE_URL`, `CORS_ALLOWED_ORIGINS`, cookie security, DNS, and the edge Host
must all name the same reviewed HTTPS origin.

## Rate, queue, and request limits

Redis-backed limits combine a keyed digest of the anonymous session with a keyed
digest of client address. This prevents reliance on IP alone while providing an
address-level abuse backstop. Default limits per 60 seconds are:

| Action | Per anonymous session | Address threshold |
| --- | ---: | ---: |
| analysis submit | 10 | 40 |
| FuzDrop import | 10 | 40 |
| delete | 30 | 120 |
| export | 60 | 240 |

The address multiplier is configurable (`RATE_LIMIT_IP_MULTIPLIER`, default 4).
Excess returns structured 429 with `Retry-After`; Redis keys do not contain the raw
session token or address.

Queue admission separately caps active SQL jobs at 128 globally and four per owner.
Global saturation returns 503 `ANALYSIS_QUEUE_FULL`; per-owner saturation returns 429
`ANALYSIS_CONCURRENT_LIMIT`. RQ receives only the opaque `job_id`, not the sequence.
Retries are finite (default two) and duplicate dispatch uses a deterministic RQ ID plus
a PostgreSQL execution guard.

Caddy caps production-like request bodies at 6 MB. The non-Docker Next development
proxy separately limits JSON POST bodies to 5 MiB, requires JSON content type,
allowlists routes, disables upstream redirects, enforces a 45-second proxy timeout,
and does not cache responses. Canonical input defaults to a 50,000-aa maximum. This
is an operational abuse/resource limit, not a scientific limit of LRECA. Oversized
Caddy bodies are rejected at the edge; overlong canonical sequences receive the
backend's structured 413 before scientific execution or job creation.

Rate, queue, and request-limit behavior through the container edge remains to be
runtime-tested with isolated lowered thresholds.

## Sequence and result privacy

- Complete canonical sequences and full results are stored in PostgreSQL for the
  configured retention period, seven days by default.
- The user can delete an analysis before expiry.
- Periodic cleanup runs at startup and every configured interval; backups require a
  separate deletion policy.
- Application logging is designed around job ID, method, status, duration, sequence
  length, and sequence SHA256. Request bodies and complete sequences are not
  intentionally logged.
- FuzDrop is never contacted automatically. Users initiate official-site use and
  import the result manually. Raw import payloads are not intended for logs.
- DisMeta is unavailable and no sequence is submitted to it.
- API, history, and export responses are `private, no-store`; Caddy and FastAPI apply
  this policy on the production-like path, while Next applies it on the development
  proxy path.

Production JSON logging can include server-side exception tracebacks. Third-party
exception messages are outside a perfect allowlist, so limit log access, retention,
and export destinations and review unexpected trace contents. Reverse-proxy access
logs must not be extended to capture request bodies or cookies. Do not use sequence
text in log messages, metric labels, traces, or alert annotations.

Backups contain complete sequences and are privacy-sensitive. Encrypt them, restrict
access, keep an off-host copy under an explicit lifecycle, and normally expire them no
later than the main data. Details are in [`backup_restore.md`](backup_restore.md).

## Secrets and configuration

`.env.example` contains placeholders only. Create a local `.env` with independent
high-entropy PostgreSQL, Redis, and session secrets and filesystem mode appropriate
for the host. Do not commit it or copy it into an image. Do not expose secrets via
command history, Compose render output shared in tickets, screenshots, logs, or client
bundles.

Production configuration fails fast for missing database/Redis/LRECA settings, weak
or placeholder session secrets, wildcard CORS, and inconsistent HTTPS cookie policy.
`DATABASE_URL` and `REDIS_URL` are server-only. Caddy is the sole public route.

The Git ignore policy excludes `.env*` except examples, model/checkpoint formats,
database files/volumes, Redis data, backups, exports, secrets, certificates, and TLS
private keys. A read-only `git ls-files` audit on 2026-09-04 returned no tracked
`*.pt`, `*.pth`, `*.ckpt`, `*.safetensors`, `.env`, backup/export, `*.pem`, or `*.key`
matches. Repeat this check before every release:

```sh
git ls-files '*.pt' '*.pth' '*.ckpt' '*.safetensors' '.env' 'backups/*' 'exports/*' '*.pem' '*.key'
```

The command must produce no output. Also scan Git history and the built image when
deploying to a shared registry; a clean current tree cannot erase an older secret.

## Checkpoint protection and provenance

The Human checkpoint must remain untracked by the first-party repository and absent
from Docker images. The host model directory is mounted read-only at `/models/lreca`.
Required identity is:

```text
filename: human_1_RCNN_ECA_parallel_089-0.9802.pt
size:     2395318 bytes
SHA256:   aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc
variant:  human_specific
commit:   0b4b48ab7870529a34028c6e30dfba42eddbf215
```

LRECA becomes ready only after the mounted file matches the expected SHA256 and the
loaded model reports the same identity. Missing/mismatched files keep the process
live, readiness false, and prediction unavailable. Public health/version/results may
return the safe filename, digest, variant, commit, and device; they must not return an
absolute path. Upstream source is fetched at the fixed commit during image build and
the scientific algorithm remains unmodified.

## Container and image controls

Configuration review shows:

- application runtimes use fixed non-root UIDs, read-only root filesystems, bounded
  tmpfs, dropped capabilities, and `no-new-privileges`;
- the migration container is one-shot and uses the same non-root backend image;
- no service mounts the Docker socket or uses host PID/network mode;
- PostgreSQL and Redis are fixed versions and use private named volumes;
- LRECA and SEG are explicitly `linux/amd64`; the model is a read-only runtime mount;
- `.dockerignore` excludes Git metadata, `.env`, models, checkpoints, local databases,
  user backups/exports, caches, and dependency/build directories;
- frontend uses a production standalone build rather than `next dev`.

These controls have passed daemon-free text/config tests only. Image package CVE
scanning, runtime UID/capability inspection, read-only filesystem probes, internal-port
scans, secret/image-layer scanning, and frontend bundle scanning remain required once
images can be built.

## HTTP headers and TLS

The local Caddy configuration sets content-type sniffing protection, strict referrer
policy, frame denial, a permissions policy, and a restrictive CSP; it removes the
Server header. Analysis APIs receive private/no-store cache control. The future Caddy
example adds HSTS for HTTPS.

No public TLS was created or tested. The production example is not loaded by
`compose.yaml`, port 443 is not published, and local Caddy state is temporary. A
future server override must persist Caddy certificate state and expose only 80/443.
Verify certificate issuance/renewal, redirects, Secure cookies, CSP behavior, and
browser console on the actual domain before enabling HSTS. Current status:
`PUBLIC_HTTPS_UNVERIFIED`.

## Scientific communication

Prediction results are computational estimates and should be interpreted alongside
experimental evidence. This is a scientific scope statement, not a medical
disclaimer. SEG is a low-complexity annotation and does not produce an LLPS score.
FuzDrop values exist only after validated manual import; DisMeta remains blocked.

## Release security checklist

Every item below is a future release acceptance gate. None of the container, restore,
network, or TLS items is marked complete while Docker remains unavailable.

- Docker reports Linux Containers and the Compose render is reviewed without sharing
  expanded secrets.
- Only Caddy listens on a host/public interface.
- Images contain no checkpoint, `.env`, private key, backup, export, or user sequence.
- Runtime users/capabilities/read-only filesystems match Compose.
- PostgreSQL and Redis require credentials and remain internal.
- LRECA wrong-hash readiness test fails closed and leaks no path.
- Frontend bundle contains no internal URL, secret, or server-only header.
- Two-session ownership, CSRF Origin, CORS, rate limit, queue cap, body cap, and
  no-store behavior pass through Caddy.
- Logs and error responses contain no complete sequence, credential, DSN, traceback,
  container hostname, or absolute path.
- Verify backup encryption, access, expiry, and an isolated restore drill.
- Public firewall, TLS, and GPU container support are labelled unverified until tested.
