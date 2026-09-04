# PostgreSQL backup and restore

Analysis jobs, canonical protein sequences, method results, imported FuzDrop data,
ownership digests, and expiry timestamps are stored in PostgreSQL. Redis is not the
scientific source of truth and does not replace a PostgreSQL backup.

The repository provides [`scripts/backup_db.sh`](../scripts/backup_db.sh) and
[`scripts/restore_db.sh`](../scripts/restore_db.sh). They are POSIX shell scripts for
an already running Compose stack. Because the audited Windows host had no Docker
runtime, neither script nor a restore drill has been executed in Module 10. Treat the
procedures below as pending acceptance, not verified recovery capability.

## Data and privacy scope

A database backup contains privacy-sensitive research data, including complete
canonical protein sequences and possibly unpublished sequences, full analysis
results, user-imported FuzDrop results, and anonymous ownership digests. A dump is not
an anonymized export.

The application's default seven-day cleanup does not delete old dump files. For
unpublished sequence workloads, set backup retention no longer than the configured
analysis retention unless a documented research/data-retention requirement calls for
a longer period. With the default, a practical starting policy is:

- encrypted daily backups retained for at most seven days;
- at least one encrypted off-host copy in a separate failure domain;
- deletion of expired local and off-host copies through an audited lifecycle rule;
- access restricted to named operators who can administer the database;
- restore logs and tickets contain filenames/checksums, not sequences or credentials.

If policy requires longer backups, document purpose, owner, expiry date, storage
location, access list, and deletion verification. Never allow the primary database to
delete a sequence after seven days while an untracked backup retains it forever.

## Backup prerequisites

Before a backup:

1. Confirm `postgres` is healthy and there is sufficient destination space.
2. Confirm the destination directory is outside Git and excluded from cloud sync
   unless that sync is explicitly approved and encrypted.
3. Set restrictive filesystem permissions and use encrypted storage.
4. Do not place the database password on a command line; the script reads credentials
   already present inside the PostgreSQL container.

The script uses `umask 077`, refuses to overwrite an existing destination, writes a
temporary partial file, runs `pg_dump` in compressed custom format with ownership and
privileges omitted, checks that the result is nonempty, and then publishes it with an
atomic rename.

## Create a backup

Run from a POSIX shell in the repository root:

```sh
./scripts/backup_db.sh
```

The default destination is `backups/llps-explorer-<UTC timestamp>.dump`. To select an
explicit protected location:

```sh
./scripts/backup_db.sh /secure/llps-backups/llps-explorer-before-update.dump
```

Verify the artifact immediately:

```sh
test -s /secure/llps-backups/llps-explorer-before-update.dump
sha256sum /secure/llps-backups/llps-explorer-before-update.dump
docker compose exec -T postgres pg_restore --list </secure/llps-backups/llps-explorer-before-update.dump >/dev/null
```

Record UTC time, deployed Git revision, database schema revision, PostgreSQL image
version, dump size, SHA256, encryption status, retention expiry, and operator. Do not
record database credentials or sequence contents.

On Windows, use a trusted POSIX environment such as a configured WSL distribution or
Git Bash. Do not use a PowerShell version that can transform redirected binary output.
The audited host did not have an available Docker runtime, so its local shell path was
not exercised.

## Restore behavior

Restore is destructive. The script requires the literal confirmation flag:

```sh
./scripts/restore_db.sh /secure/llps-backups/llps-explorer-before-update.dump --confirm-replace
```

It performs these steps:

1. rejects missing or empty input;
2. validates the archive with `pg_restore --list` before interrupting services;
3. stops backend and worker so writes do not race the replacement;
4. restores with `--clean --if-exists --no-owner --no-privileges` in one transaction;
5. runs the one-shot Alembic migration service;
6. restarts backend and worker, including cleanup on startup.

The trap attempts to restart backend and worker if the restore fails after they were
stopped. That does not prove the old database is usable after every failure mode;
inspect PostgreSQL and application readiness before reopening traffic.

## Test restore without touching the development database

Never use the active development or production database for the first restore test.
Use a separate checkout or deployment directory, a distinct Compose project name, a
distinct `.env`, and distinct named volumes. Do not expose its PostgreSQL port.

Suggested drill:

1. Start an isolated stack with a new PostgreSQL volume and new test-only secrets.
2. Create a clearly identified test analysis through the isolated Caddy endpoint;
   record its job ID, owner browser session, status, result digest, and exports.
3. Create a dump and validate its archive list and SHA256.
4. Delete the isolated project and its volumes only after confirming this is the test
   project.
5. Recreate a clean isolated stack and run the restore script against it.
6. Require migration success, PostgreSQL/Redis/backend/worker/LRECA readiness, and
   retrieval of the same owned job and exports with the same scientific values.
7. Verify a different anonymous session still receives 404 for the restored job.
8. Delete the test stack and backup according to the test-data retention policy.

Use a visibly unique project name, for example:

```sh
export COMPOSE_PROJECT_NAME=llps-restore-test
docker compose --env-file .env.restore-test config --quiet
docker compose --env-file .env.restore-test up -d
```

Confirm `docker compose ls`, `docker compose ps`, and volume names before any
`down --volumes`. The restore helper uses the environment's active Compose project;
keep `COMPOSE_PROJECT_NAME` and the test environment active when invoking it.

This entire restore drill is still pending because Docker was unavailable during
Module 10.

## Retention after restore

Rows retain their original `expires_at` values. Restoring an older dump can briefly
reintroduce already-expired sequence data. Backend startup runs expiry cleanup and
then repeats it at `ANALYSIS_CLEANUP_INTERVAL_SECONDS` (default 3,600 seconds), but an
operator must verify that expired rows and eligible imported results are gone before
declaring the restore complete.

The backup file itself remains unaffected by that cleanup. Its lifecycle must be
enforced by storage policy. Restoring a dump does not extend consent or create a new
retention basis.

## Recovery by failure type

| Failure | Recovery source | Notes |
| --- | --- | --- |
| backend/frontend/LRECA container loss | immutable image/config plus checkpoint mount | database remains in PostgreSQL |
| Redis restart/data loss | PostgreSQL plus worker recovery scan | completed results remain; queued/stale-running recovery must be verified |
| PostgreSQL container restart | `postgres-data` named volume | persistence across restart remains to be Docker-tested |
| PostgreSQL volume loss/corruption | verified encrypted `pg_dump` archive | restore is destructive and requires downtime |
| checkpoint loss | separately controlled audited model file | never restore an unknown model; verify filename, size, and SHA256 |
| bad application update | prior images/revision plus compatible DB or matching backup | do not downgrade across an incompatible migration without restore |

Redis AOF improves queue durability but is not a substitute for the PostgreSQL dump.
The LRECA checkpoint should be backed up under its own model-artifact policy and
verified against SHA256
`aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc`;
do not mix it into database dumps or Git.

## Backup acceptance checklist

- Dump creation exits 0, is nonempty, and `pg_restore --list` succeeds.
- SHA256 and metadata are recorded without secrets or sequence content.
- At-rest and off-host encryption and access control are confirmed.
- Isolated restore completes in a single transaction and Alembic reaches head.
- Known history and every export are byte/value checked after restore.
- Anonymous ownership remains isolated after restore.
- Expired data is removed and backup expiry is scheduled.
- A measured recovery time objective and recovery point objective are recorded from
  the drill instead of guessed.

Until these checks run on a working Linux Docker stack, backup/restore status remains
unverified.
