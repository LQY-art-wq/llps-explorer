"""SQLAlchemy repository implementations; the database is the source of truth."""

from __future__ import annotations

import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.persistence.database import (
    AnalysisJobRow,
    ImportedResultRow,
    JobImportRow,
    JobMethodRow,
)
from app.schemas.imported_results import ImportedCoordinateProvenance, ImportedMethodResult
from app.schemas.orchestration import AnalysisJob, MethodExecution, StructuredError
from app.schemas.persistence import HistoryItem, HistoryResponse
from app.services.analysis_jobs import ACTIVE_JOB_STATES, AnalysisServiceError
from app.services.imported_results import (
    _SHA256,
    DEFAULT_OWNER_ID,
    ImportedResultStore,
    _error,
    _utc_now,
    validate_imported_fuzdrop_result,
)

_JOB_MUTATION_LOCK = threading.RLock()
_IMPORT_CAPACITY_LOCK = threading.RLock()
_POSTGRES_JOB_MUTATION_LOCK = 0x4C4C50534A4F4253
_POSTGRES_IMPORT_CAPACITY_LOCK = 0x4C4C5053494D5054
_EXECUTION_LOCK_STRIPES = tuple(threading.Lock() for _ in range(64))


@dataclass(frozen=True)
class ClaimedAnalysisJob:
    """Private worker envelope; never exposed through the HTTP API."""

    job: AnalysisJob
    owner_id: str
    import_result_ids: tuple[str, ...]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lock_postgres_transaction(session: Session, lock_key: int) -> None:
    """Serialize a mutation across cooperating PostgreSQL processes."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
        )


def _delete_job_and_orphan_imports(session: Session, row: AnalysisJobRow) -> None:
    import_ids = list(
        session.scalars(select(JobImportRow.result_id).where(JobImportRow.job_id == row.job_id))
    )
    owner_id = row.owner_id
    session.delete(row)
    session.flush()
    for result_id in set(import_ids):
        references = session.scalar(
            select(func.count())
            .select_from(JobImportRow)
            .where(JobImportRow.result_id == result_id)
        )
        if references == 0:
            session.execute(
                delete(ImportedResultRow).where(
                    ImportedResultRow.result_id == result_id,
                    ImportedResultRow.owner_id == owner_id,
                )
            )


def _method_results(job: AnalysisJob) -> dict:
    return {
        name: execution.result.model_dump(mode="json", warnings=False)
        for name, execution in job.methods.items()
        if execution.result is not None
    }


def _job_values(job: AnalysisJob, owner_id: str) -> dict:
    payload = job.model_dump(mode="json", warnings=False)
    return {
        "job_id": job.job_id,
        "owner_id": owner_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "expires_at": job.expires_at,
        "status": job.status,
        "sequence_name": job.sequence.name,
        "sequence_length": job.sequence.length,
        "sequence_sha256": job.sequence.sha256,
        "normalized_sequence": job.normalized_sequence,
        "selected_methods": list(job.selected_methods),
        "prediction_mode": job.prediction_mode,
        "weights": job.weights,
        "method_states": {
            name: execution.model_dump(mode="json", warnings=False, exclude={"result"})
            for name, execution in job.methods.items()
        },
        "ensemble_result": (
            job.ensemble.model_dump(mode="json", warnings=False) if job.ensemble else None
        ),
        "normalized_results": _method_results(job),
        "warnings": list(job.warnings),
        "result_payload": payload,
        "result_schema_version": job.result_schema_version,
        "lreca_score": _score(job, "lreca"),
        "fuzdrop_score": _score(job, "fuzdrop"),
        "ensemble_score": job.ensemble.score if job.ensemble else None,
    }


def _score(job: AnalysisJob, method: str) -> float | None:
    execution = job.methods.get(method)
    if execution is None or execution.result is None:
        return None
    return getattr(execution.result, "raw_score", None)


def _history_row(row: AnalysisJobRow) -> HistoryItem:
    return HistoryItem(
        job_id=row.job_id,
        sequence_name=row.sequence_name,
        sequence_length=row.sequence_length,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
        completed_at=_as_utc(row.completed_at) if row.completed_at else None,
        expires_at=_as_utc(row.expires_at),
        status=row.status,
        selected_methods=row.selected_methods,
        prediction_mode=row.prediction_mode,
        lreca_score=row.lreca_score,
        fuzdrop_score=row.fuzdrop_score,
        ensemble_score=row.ensemble_score,
        result_schema_version=row.result_schema_version,
    )


class SQLAnalysisJobRepository:
    """Transactional analysis repository compatible with SQLite and PostgreSQL."""

    def __init__(
        self,
        engine: Engine,
        *,
        max_jobs: int = 128,
        max_active_jobs: int | None = None,
        max_active_jobs_per_owner: int | None = None,
    ) -> None:
        self.engine = engine
        self.max_jobs = max_jobs
        self.max_active_jobs = max_active_jobs
        self.max_active_jobs_per_owner = max_active_jobs_per_owner

    def create_job(
        self,
        job: AnalysisJob,
        *,
        owner_id: str = DEFAULT_OWNER_ID,
        import_result_ids: tuple[str, ...] = (),
    ) -> None:
        values = _job_values(job, owner_id)
        if values["normalized_sequence"] is None:
            raise ValueError("Persistent jobs require the normalized sequence")
        now = _utc_now()
        with _JOB_MUTATION_LOCK:
            with Session(self.engine) as session, session.begin():
                _lock_postgres_transaction(session, _POSTGRES_JOB_MUTATION_LOCK)
                expired_rows = list(
                    session.scalars(
                        select(AnalysisJobRow).where(AnalysisJobRow.expires_at <= now)
                    )
                )
                for expired_row in expired_rows:
                    _delete_job_and_orphan_imports(session, expired_row)
                stored_count = session.scalar(select(func.count()).select_from(AnalysisJobRow))
                if stored_count is not None and stored_count >= self.max_jobs:
                    raise AnalysisServiceError(
                        "ANALYSIS_CAPACITY_EXCEEDED", "Analysis storage capacity reached.", 503
                    )
                active_filter = AnalysisJobRow.status.in_(ACTIVE_JOB_STATES)
                if self.max_active_jobs is not None:
                    active_count = session.scalar(
                        select(func.count()).select_from(AnalysisJobRow).where(active_filter)
                    )
                    if active_count is not None and active_count >= self.max_active_jobs:
                        raise AnalysisServiceError(
                            "ANALYSIS_QUEUE_FULL", "Analysis queue capacity reached.", 503
                        )
                if self.max_active_jobs_per_owner is not None:
                    owner_active_count = session.scalar(
                        select(func.count())
                        .select_from(AnalysisJobRow)
                        .where(active_filter, AnalysisJobRow.owner_id == owner_id)
                    )
                    if (
                        owner_active_count is not None
                        and owner_active_count >= self.max_active_jobs_per_owner
                    ):
                        raise AnalysisServiceError(
                            "ANALYSIS_CONCURRENT_LIMIT",
                            "This session has reached its active analysis limit.",
                            429,
                        )
                session.add(AnalysisJobRow(**values))
                for method in job.selected_methods:
                    session.add(JobMethodRow(job_id=job.job_id, method=method))
                for result_id in import_result_ids:
                    owned_import = session.scalar(
                        select(ImportedResultRow).where(
                            ImportedResultRow.result_id == result_id,
                            ImportedResultRow.owner_id == owner_id,
                            ImportedResultRow.expires_at > now,
                        )
                    )
                    if owned_import is None:
                        raise _error("EXTERNAL_RESULT_NOT_FOUND")
                    # The immutable validated result is the durable input
                    # snapshot for queued execution. Keep it at least as long
                    # as the accepted analysis that references it.
                    if _as_utc(owned_import.expires_at) < _as_utc(job.expires_at):
                        owned_import.expires_at = job.expires_at
                    session.add(JobImportRow(job_id=job.job_id, result_id=result_id))

    def add(
        self,
        job: AnalysisJob,
        owner_id: str = DEFAULT_OWNER_ID,
        import_result_ids: tuple[str, ...] = (),
    ) -> None:
        self.create_job(job, owner_id=owner_id, import_result_ids=import_result_ids)

    def update_job(self, job: AnalysisJob) -> None:
        with Session(self.engine) as session, session.begin():
            owner_id = session.scalar(
                select(AnalysisJobRow.owner_id).where(AnalysisJobRow.job_id == job.job_id)
            )
            if owner_id is None:
                return
            values = {
                key: value
                for key, value in _job_values(job, owner_id).items()
                if key != "job_id"
            }
            session.execute(
                update(AnalysisJobRow)
                .where(AnalysisJobRow.job_id == job.job_id)
                .values(**values)
            )

    def update(self, job: AnalysisJob) -> None:
        self.update_job(job)

    @staticmethod
    def _execution_lock_key(job_id: str) -> int:
        # PostgreSQL accepts a signed bigint.  The id itself never reaches SQL
        # text or logs, and a stable digest keeps the lock portable.
        unsigned = int.from_bytes(sha256(job_id.encode("ascii")).digest()[:8], "big")
        return unsigned if unsigned < (1 << 63) else unsigned - (1 << 64)

    @contextmanager
    def execution_lock(self, job_id: str) -> Iterator[bool]:
        """Try to own one execution across workers without holding row locks."""
        bind = self.engine
        if bind.dialect.name == "postgresql":
            connection = bind.connect()
            key = self._execution_lock_key(job_id)
            acquired = bool(
                connection.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": key}
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": key}
                    )
                connection.close()
            return

        lock_index = self._execution_lock_key(job_id) % len(_EXECUTION_LOCK_STRIPES)
        lock = _EXECUTION_LOCK_STRIPES[lock_index]
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()

    def claim_queued_job(
        self, job_id: str, *, now: datetime | None = None
    ) -> ClaimedAnalysisJob | None:
        """Atomically transition queued -> running and return private SQL inputs."""
        now = _as_utc(now or _utc_now())
        with _JOB_MUTATION_LOCK:
            with Session(self.engine) as session, session.begin():
                _lock_postgres_transaction(session, _POSTGRES_JOB_MUTATION_LOCK)
                statement = select(AnalysisJobRow).where(AnalysisJobRow.job_id == job_id)
                if session.get_bind().dialect.name == "postgresql":
                    statement = statement.with_for_update()
                row = session.scalar(statement)
                if row is None or row.status != "queued":
                    return None
                if _as_utc(row.expires_at) <= now:
                    _delete_job_and_orphan_imports(session, row)
                    return None
                job = AnalysisJob.model_validate(row.result_payload)
                running = job.model_copy(
                    update={"status": "running", "updated_at": now}, deep=True
                )
                values = _job_values(running, row.owner_id)
                for key, value in values.items():
                    if key != "job_id":
                        setattr(row, key, value)
                import_ids = tuple(
                    session.scalars(
                        select(JobImportRow.result_id)
                        .where(JobImportRow.job_id == job_id)
                        .order_by(JobImportRow.result_id)
                    )
                )
                return ClaimedAnalysisJob(running, row.owner_id, import_ids)

    def requeue_job(
        self,
        job_id: str,
        *,
        now: datetime | None = None,
        stale_before: datetime | None = None,
    ) -> bool:
        """Reset a nonterminal execution for one finite RQ retry."""
        now = _as_utc(now or _utc_now())
        with Session(self.engine) as session, session.begin():
            statement = select(AnalysisJobRow).where(AnalysisJobRow.job_id == job_id)
            if session.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None or row.status not in (
                *ACTIVE_JOB_STATES,
                "failed",
                "partial_success",
            ):
                return False
            if stale_before is not None and (
                row.status != "running" or _as_utc(row.updated_at) > _as_utc(stale_before)
            ):
                return False
            job = AnalysisJob.model_validate(row.result_payload)
            methods = {
                name: (
                    execution
                    if execution.status in {"success", "unavailable", "external_result_required"}
                    else MethodExecution(
                        method=name,
                        integration_mode=execution.integration_mode,
                        status="queued",
                    )
                )
                for name, execution in job.methods.items()
            }
            queued = job.model_copy(
                update={
                    "status": "queued",
                    "methods": methods,
                    "ensemble": None,
                    "updated_at": now,
                    "completed_at": None,
                },
                deep=True,
            )
            values = _job_values(queued, row.owner_id)
            for key, value in values.items():
                if key != "job_id":
                    setattr(row, key, value)
            return True

    def interrupt_job(
        self,
        job_id: str,
        *,
        code: str = "ANALYSIS_WORKER_INTERRUPTED",
        message: str = "Analysis worker stopped before completing the job.",
        reason: str = "worker_interrupted",
        now: datetime | None = None,
    ) -> bool:
        """Publish a terminal, structured outcome after retries are exhausted."""
        now = _as_utc(now or _utc_now())
        with Session(self.engine) as session, session.begin():
            statement = select(AnalysisJobRow).where(AnalysisJobRow.job_id == job_id)
            if session.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None or row.status not in ACTIVE_JOB_STATES:
                return False
            job = AnalysisJob.model_validate(row.result_payload)
            methods = {
                name: (
                    execution
                    if execution.status not in {"queued", "running"}
                    else MethodExecution(
                        method=name,
                        integration_mode=execution.integration_mode,
                        status="failed",
                        runtime_ms=execution.runtime_ms,
                        error=StructuredError(code=code, message=message),
                        reason=reason,
                    )
                )
                for name, execution in job.methods.items()
            }
            interrupted = job.model_copy(
                update={
                    "status": "interrupted",
                    "methods": methods,
                    "updated_at": now,
                    "completed_at": now,
                    "warnings": [*job.warnings, message],
                },
                deep=True,
            )
            values = _job_values(interrupted, row.owner_id)
            for key, value in values.items():
                if key != "job_id":
                    setattr(row, key, value)
            return True

    def requeue_stale_running_jobs(
        self, *, stale_before: datetime, now: datetime | None = None
    ) -> list[str]:
        """Recover work whose SQL heartbeat outlived its worker lease."""
        stale_before = _as_utc(stale_before)
        now = _as_utc(now or _utc_now())
        recovered: list[str] = []
        with Session(self.engine) as session:
            job_ids = list(
                session.scalars(
                    select(AnalysisJobRow.job_id).where(
                        AnalysisJobRow.status == "running",
                        AnalysisJobRow.updated_at <= stale_before,
                        AnalysisJobRow.expires_at > now,
                    )
                )
            )
        for job_id in job_ids:
            if self.requeue_job(job_id, now=now, stale_before=stale_before):
                recovered.append(job_id)
        return recovered

    def queued_job_ids(self, *, limit: int = 1000) -> list[str]:
        now = _utc_now()
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(AnalysisJobRow.job_id)
                    .where(
                        AnalysisJobRow.status == "queued",
                        AnalysisJobRow.expires_at > now,
                    )
                    .order_by(AnalysisJobRow.created_at, AnalysisJobRow.job_id)
                    .limit(limit)
                )
            )

    def get_job(self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID) -> AnalysisJob:
        now = _utc_now()
        missing = False
        expired = False
        payload = None
        with Session(self.engine) as session:
            row = session.scalar(
                select(AnalysisJobRow).where(
                    AnalysisJobRow.job_id == job_id, AnalysisJobRow.owner_id == owner_id
                )
            )
            if row is None:
                missing = True
            elif _as_utc(row.expires_at) <= now:
                expired = True
            else:
                payload = row.result_payload
        if expired:
            # Re-query inside the shared mutation boundary so the job deletion,
            # link deletion, orphan count, and transaction commit are atomic with
            # respect to all cooperating deletion paths.
            with _JOB_MUTATION_LOCK:
                with Session(self.engine) as session, session.begin():
                    _lock_postgres_transaction(session, _POSTGRES_JOB_MUTATION_LOCK)
                    row = session.scalar(
                        select(AnalysisJobRow).where(
                            AnalysisJobRow.job_id == job_id,
                            AnalysisJobRow.owner_id == owner_id,
                            AnalysisJobRow.expires_at <= now,
                        )
                    )
                    if row is not None:
                        _delete_job_and_orphan_imports(session, row)
            missing = True
        if missing:
            raise AnalysisServiceError(
                "ANALYSIS_JOB_NOT_FOUND", "Analysis job is missing or expired.", 404
            )
        assert payload is not None
        return AnalysisJob.model_validate(payload)

    def get(self, job_id: str, owner_id: str = DEFAULT_OWNER_ID) -> AnalysisJob:
        return self.get_job(job_id, owner_id=owner_id)

    def list_jobs(
        self,
        *,
        owner_id: str = DEFAULT_OWNER_ID,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        method: str | None = None,
    ) -> HistoryResponse:
        now = _utc_now()
        statement = (
            select(AnalysisJobRow)
            .where(AnalysisJobRow.owner_id == owner_id, AnalysisJobRow.expires_at > now)
            .order_by(AnalysisJobRow.created_at.desc(), AnalysisJobRow.job_id.desc())
        )
        if status is not None:
            statement = statement.where(AnalysisJobRow.status == status)
        if method is not None:
            statement = statement.join(
                JobMethodRow,
                (JobMethodRow.job_id == AnalysisJobRow.job_id)
                & (JobMethodRow.method == method),
            )
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        with Session(self.engine) as session:
            total = session.scalar(count_statement) or 0
            rows = list(session.scalars(statement.offset(offset).limit(limit)))
        return HistoryResponse(
            items=[_history_row(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def delete_job(self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID) -> bool:
        with _JOB_MUTATION_LOCK:
            with Session(self.engine) as session, session.begin():
                _lock_postgres_transaction(session, _POSTGRES_JOB_MUTATION_LOCK)
                row = session.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.job_id == job_id,
                        AnalysisJobRow.owner_id == owner_id,
                    )
                )
                if row is None:
                    return False
                _delete_job_and_orphan_imports(session, row)
                return True

    def cleanup_expired_jobs(self, *, now: datetime | None = None) -> int:
        now = _as_utc(now or _utc_now())
        with _JOB_MUTATION_LOCK:
            with Session(self.engine) as session, session.begin():
                _lock_postgres_transaction(session, _POSTGRES_JOB_MUTATION_LOCK)
                rows = list(
                    session.scalars(
                        select(AnalysisJobRow).where(AnalysisJobRow.expires_at <= now)
                    )
                )
                for row in rows:
                    _delete_job_and_orphan_imports(session, row)
                return len(rows)

    def purge_expired(self) -> None:
        self.cleanup_expired_jobs()

    def recover_interrupted_jobs(self, *, now: datetime | None = None) -> int:
        now = _as_utc(now or _utc_now())
        with Session(self.engine) as session, session.begin():
            rows = list(
                session.scalars(
                    select(AnalysisJobRow).where(AnalysisJobRow.status.in_(ACTIVE_JOB_STATES))
                )
            )
            for row in rows:
                job = AnalysisJob.model_validate(row.result_payload)
                methods = {}
                for name, execution in job.methods.items():
                    if execution.status in {"queued", "running"}:
                        methods[name] = MethodExecution(
                            method=name,
                            integration_mode=execution.integration_mode,
                            status="failed",
                            runtime_ms=execution.runtime_ms,
                            error=StructuredError(
                                code="ANALYSIS_INTERRUPTED",
                                message="Analysis was interrupted by a service restart.",
                            ),
                            reason="service_restart",
                        )
                    else:
                        methods[name] = execution
                recovered = job.model_copy(
                    update={
                        "status": "interrupted",
                        "methods": methods,
                        "updated_at": now,
                        "completed_at": now,
                        "warnings": [
                            *job.warnings,
                            "Analysis was interrupted by a service restart (service_restart).",
                        ],
                    },
                    deep=True,
                )
                values = _job_values(recovered, row.owner_id)
                for key, value in values.items():
                    if key != "job_id":
                        setattr(row, key, value)
            return len(rows)

    def close(self) -> None:
        # Engine lifetime is owned by the application, not one repository.
        return None


class SQLImportedResultStore(ImportedResultStore):
    """Persistent validated imports with session ownership and bounded retention."""

    ownership_enforced = True

    def __init__(self, engine: Engine, *, ttl_seconds: float, max_entries: int = 128) -> None:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
            or ttl_seconds > 3650 * 86400
        ):
            raise ValueError("ttl_seconds must be a finite positive retention duration")
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.engine = engine
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = max_entries
        self._closed = False

    @property
    def cleanup_interval_seconds(self) -> float:
        return min(60.0, self._ttl_seconds)

    def put(self, result, owner_id: str = DEFAULT_OWNER_ID) -> ImportedMethodResult:
        if self._closed:
            raise _error("EXTERNAL_RESULT_STORE_FULL")
        try:
            native = validate_imported_fuzdrop_result(result)
        except Exception as error:
            raise _error("EXTERNAL_RESULT_INVALID") from error
        now = _utc_now()
        imported = ImportedMethodResult(
            result_id="fuzdrop_result_" + uuid4().hex,
            sequence_sha256=native.sequence_sha256,
            sequence_length=native.sequence_length,
            normalized_result=native,
            source=native.source,
            imported_at=native.imported_at,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
            coordinate_provenance=ImportedCoordinateProvenance(
                coordinate_system=native.coordinate_system,
                coordinate_verification=native.coordinate_verification,
            ),
        )
        with _IMPORT_CAPACITY_LOCK:
            with Session(self.engine) as session, session.begin():
                _lock_postgres_transaction(session, _POSTGRES_IMPORT_CAPACITY_LOCK)
                session.execute(
                    delete(ImportedResultRow).where(ImportedResultRow.expires_at <= now)
                )
                count = session.scalar(select(func.count()).select_from(ImportedResultRow))
                if count is not None and count >= self._max_entries:
                    raise _error("EXTERNAL_RESULT_STORE_FULL")
                session.add(
                    ImportedResultRow(
                        result_id=imported.result_id,
                        owner_id=owner_id,
                        created_at=imported.imported_at,
                        expires_at=imported.expires_at,
                        sequence_sha256=imported.sequence_sha256,
                        sequence_length=imported.sequence_length,
                        normalized_result=imported.normalized_result.model_dump(
                            mode="json", warnings=False
                        ),
                        source=imported.source,
                        validation_status=imported.validation_status,
                        coordinate_provenance=imported.coordinate_provenance.model_dump(
                            mode="json"
                        ),
                    )
                )
        return imported.model_copy(deep=True)

    def get(
        self,
        result_id: str,
        *,
        sequence_sha256: str | None = None,
        sequence_length: int | None = None,
        owner_id: str = DEFAULT_OWNER_ID,
    ) -> ImportedMethodResult:
        if self._closed or not isinstance(result_id, str):
            raise _error("EXTERNAL_RESULT_NOT_FOUND")
        now = _utc_now()
        missing = False
        imported = None
        with Session(self.engine) as session:
            row = session.scalar(
                select(ImportedResultRow).where(
                    ImportedResultRow.result_id == result_id,
                    ImportedResultRow.owner_id == owner_id,
                )
            )
            if row is None:
                missing = True
            elif _as_utc(row.expires_at) <= now:
                session.delete(row)
                session.commit()
                missing = True
            else:
                imported = ImportedMethodResult(
                    result_id=row.result_id,
                    sequence_sha256=row.sequence_sha256,
                    sequence_length=row.sequence_length,
                    normalized_result=row.normalized_result,
                    source=row.source,
                    imported_at=_as_utc(row.created_at),
                    expires_at=_as_utc(row.expires_at),
                    coordinate_provenance=row.coordinate_provenance,
                    validation_status=row.validation_status,
                )
        if missing:
            raise _error("EXTERNAL_RESULT_NOT_FOUND")
        assert imported is not None
        if sequence_sha256 is not None and (
            not isinstance(sequence_sha256, str)
            or _SHA256.fullmatch(sequence_sha256) is None
            or sequence_sha256 != imported.sequence_sha256
        ):
            raise _error("EXTERNAL_RESULT_SEQUENCE_MISMATCH")
        if sequence_length is not None and (
            type(sequence_length) is not int or sequence_length != imported.sequence_length
        ):
            raise _error("EXTERNAL_RESULT_SEQUENCE_MISMATCH")
        return imported.model_copy(deep=True)

    def purge_expired(self) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(
                delete(ImportedResultRow).where(ImportedResultRow.expires_at <= _utc_now())
            )

    def close(self) -> None:
        self._closed = True
