"""Bounded local job runner and replaceable result store; no HTTP dependencies."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.schemas.orchestration import (
    AnalysisJob,
    AnalysisRequest,
    MethodExecution,
    SequenceMetadata,
    StructuredError,
)
from app.schemas.persistence import HistoryResponse
from app.services.analysis_queue import AnalysisQueue
from app.services.history import history_item
from app.services.imported_results import DEFAULT_OWNER_ID, ImportedResultError
from app.services.orchestrator import (
    TERMINAL_METHOD_STATES,
    AnalysisOrchestrator,
    PreparedAnalysis,
    overall_status,
)

ACTIVE_JOB_STATES = frozenset({"queued", "running"})
logger = logging.getLogger("uvicorn.error.analysis.cleanup")


class AnalysisServiceError(ValueError):
    def __init__(self, code: str, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status
        self.detail = {"code": code, "message": message}


class AnalysisJobRepository(Protocol):
    """Persistence boundary used by orchestration, independent of SQLAlchemy."""

    def create_job(
        self,
        job: AnalysisJob,
        *,
        owner_id: str = DEFAULT_OWNER_ID,
        import_result_ids: tuple[str, ...] = (),
    ) -> None: ...
    def update_job(self, job: AnalysisJob) -> None: ...
    def get_job(
        self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID
    ) -> AnalysisJob: ...
    def list_jobs(
        self,
        *,
        owner_id: str = DEFAULT_OWNER_ID,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        method: str | None = None,
    ) -> HistoryResponse: ...
    def delete_job(self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID) -> bool: ...
    def cleanup_expired_jobs(self) -> int: ...
    def recover_interrupted_jobs(self) -> int: ...
    def close(self) -> None: ...


# Backward-compatible name retained for integrations written before Module 9.
AnalysisJobStore = AnalysisJobRepository


class InMemoryAnalysisJobStore:
    def __init__(
        self,
        *,
        max_jobs: int = 128,
        max_active_jobs: int | None = None,
        max_active_jobs_per_owner: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._max_jobs, self._clock = max_jobs, clock
        self._max_active_jobs = max_active_jobs
        self._max_active_jobs_per_owner = max_active_jobs_per_owner
        self._jobs: dict[str, AnalysisJob] = {}
        self._owners: dict[str, str] = {}
        self._lock = threading.RLock()

    def purge_expired(self) -> None:
        with self._lock:
            self._purge()

    def _purge(self) -> None:
        now = self._clock()
        for job_id, job in list(self._jobs.items()):
            if now >= job.expires_at:
                del self._jobs[job_id]
                self._owners.pop(job_id, None)

    def create_job(
        self,
        job: AnalysisJob,
        *,
        owner_id: str = DEFAULT_OWNER_ID,
        import_result_ids: tuple[str, ...] = (),
    ) -> None:
        with self._lock:
            self._purge()
            if len(self._jobs) >= self._max_jobs:
                raise AnalysisServiceError(
                    "ANALYSIS_CAPACITY_EXCEEDED", "Analysis storage capacity reached.", 503
                )
            active = sum(job.status in ACTIVE_JOB_STATES for job in self._jobs.values())
            if self._max_active_jobs is not None and active >= self._max_active_jobs:
                raise AnalysisServiceError(
                    "ANALYSIS_QUEUE_FULL", "Analysis queue capacity reached.", 503
                )
            owner_active = sum(
                job.status in ACTIVE_JOB_STATES and self._owners.get(job_id) == owner_id
                for job_id, job in self._jobs.items()
            )
            if (
                self._max_active_jobs_per_owner is not None
                and owner_active >= self._max_active_jobs_per_owner
            ):
                raise AnalysisServiceError(
                    "ANALYSIS_CONCURRENT_LIMIT",
                    "This session has reached its active analysis limit.",
                    429,
                )
            self._jobs[job.job_id] = job.model_copy(deep=True)
            self._owners[job.job_id] = owner_id

    def add(
        self,
        job: AnalysisJob,
        owner_id: str = DEFAULT_OWNER_ID,
        import_result_ids: tuple[str, ...] = (),
    ) -> None:
        self.create_job(job, owner_id=owner_id, import_result_ids=import_result_ids)

    def update_job(self, job: AnalysisJob) -> None:
        with self._lock:
            if job.job_id in self._jobs:
                self._jobs[job.job_id] = job.model_copy(deep=True)

    def update(self, job: AnalysisJob) -> None:
        self.update_job(job)

    def get_job(
        self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID
    ) -> AnalysisJob:
        with self._lock:
            self._purge()
            if job_id not in self._jobs or self._owners.get(job_id) != owner_id:
                raise AnalysisServiceError(
                    "ANALYSIS_JOB_NOT_FOUND", "Analysis job is missing or expired.", 404
                )
            return self._jobs[job_id].model_copy(deep=True)

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
        with self._lock:
            self._purge()
            jobs = [
                job.model_copy(deep=True)
                for job_id, job in self._jobs.items()
                if self._owners.get(job_id) == owner_id
                and (status is None or job.status == status)
                and (method is None or method in job.selected_methods)
            ]
        jobs.sort(key=lambda item: (item.created_at, item.job_id), reverse=True)
        return HistoryResponse(
            items=[history_item(job) for job in jobs[offset : offset + limit]],
            total=len(jobs),
            limit=limit,
            offset=offset,
        )

    def delete_job(self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID) -> bool:
        with self._lock:
            if self._owners.get(job_id) != owner_id:
                return False
            del self._jobs[job_id]
            del self._owners[job_id]
            return True

    def cleanup_expired_jobs(self) -> int:
        with self._lock:
            before = len(self._jobs)
            self._purge()
            return before - len(self._jobs)

    def recover_interrupted_jobs(self) -> int:
        # Process-local storage cannot survive the restart it would need to recover from.
        return 0

    def close(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._owners.clear()


class AnalysisJobService:
    ownership_enforced = True

    def __init__(
        self,
        *,
        orchestrator: AnalysisOrchestrator,
        ttl_seconds: float = 3600,
        max_jobs: int = 128,
        max_concurrent_jobs: int = 4,
        max_sequence_length: int = 50000,
        store: AnalysisJobRepository | None = None,
        cleanup_interval_seconds: float = 60,
        queue: AnalysisQueue | None = None,
    ) -> None:
        if (
            type(ttl_seconds) not in (int, float)
            or not 0.000001 <= ttl_seconds <= 3650 * 86400
            or not math.isfinite(ttl_seconds)
        ):
            raise ValueError("Retention must be a finite duration from 1 us to 3650 days")
        if (
            type(cleanup_interval_seconds) not in (int, float)
            or not 0.000001 <= cleanup_interval_seconds <= 86400
            or not math.isfinite(cleanup_interval_seconds)
        ):
            raise ValueError("Cleanup interval must be a finite duration up to one day")
        for value in (max_jobs, max_concurrent_jobs):
            if type(value) is not int or value < 1:
                raise ValueError("Job limits must be positive integers")
        if type(max_sequence_length) is not int or not 1 <= max_sequence_length <= 1000000:
            raise ValueError("Maximum sequence length must be an integer from 1 to 1000000")
        self.orchestrator, self.ttl_seconds = orchestrator, ttl_seconds
        self.max_sequence_length = max_sequence_length
        self.store = store if store is not None else InMemoryAnalysisJobStore(max_jobs=max_jobs)
        self.queue = queue
        self._semaphore = asyncio.Semaphore(max_concurrent_jobs)
        self._tasks: set[asyncio.Task] = set()
        self._job_tasks: dict[str, asyncio.Task] = {}
        self._closed = False
        self._cleanup_interval = min(cleanup_interval_seconds, ttl_seconds)
        self._sweeper: asyncio.Task | None = None

    async def start(self) -> None:
        if not self._closed and self._sweeper is None:
            # Queue workers own recovery in durable mode.  The legacy local
            # runner retains Module 9's restart-to-interrupted policy.
            if self.queue is None:
                self.store.recover_interrupted_jobs()
            self.store.cleanup_expired_jobs()
            self.orchestrator.imported_store.purge_expired()
            self._sweeper = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self._cleanup_interval)
            try:
                self.store.cleanup_expired_jobs()
                self.orchestrator.imported_store.purge_expired()
            except Exception as error:
                # Retry on the next interval without logging database URLs, payloads,
                # sequences, or exception text that might contain private details.
                logger.warning(
                    "Analysis retention cleanup failed (%s); it will retry.",
                    type(error).__name__,
                )

    async def submit(
        self, request: AnalysisRequest, *, owner_id: str = DEFAULT_OWNER_ID
    ) -> AnalysisJob:
        if self._closed:
            raise AnalysisServiceError("ANALYSIS_UNAVAILABLE", "Analysis service is closing.", 503)
        # Revalidation canonicalizes even a model constructed by an internal
        # caller without normal validation. This provides an early admission
        # check before imported-result lookup or capability discovery.
        request = AnalysisRequest.model_validate(request.model_dump(warnings=False))
        self._ensure_sequence_within_limit(request.sequence)
        try:
            prepared = await self.orchestrator.prepare(request, owner_id=owner_id)
        except ImportedResultError as error:
            raise AnalysisServiceError(error.code, error.message, error.http_status) from None
        # Enforce the limit on the canonical sequence produced by the request
        # validation path. FASTA headers and line wrapping are transport syntax,
        # not residues, and therefore must not consume the configured budget.
        self._ensure_sequence_within_limit(prepared.request.sequence)
        if self._closed:
            raise AnalysisServiceError("ANALYSIS_UNAVAILABLE", "Analysis service is closing.", 503)
        now = datetime.now(timezone.utc)
        job = AnalysisJob(
            job_id="analysis_" + secrets.token_urlsafe(24),
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            status="queued",
            sequence=SequenceMetadata(
                name=prepared.request.sequence_name,
                length=len(prepared.request.sequence),
                sha256=hashlib.sha256(prepared.request.sequence.encode("ascii")).hexdigest(),
            ),
            normalized_sequence=prepared.request.sequence,
            selected_methods=prepared.request.selected_methods,
            prediction_mode=prepared.request.prediction_mode,
            weights=prepared.request.weights,
            methods={
                method: MethodExecution(
                    method=method,
                    status="queued",
                    integration_mode=prepared.descriptors[method].integration_mode,
                )
                for method in prepared.request.selected_methods
            },
        )
        import_ids = tuple(reference.result_id for reference in request.external_results.values())
        self.store.create_job(job, owner_id=owner_id, import_result_ids=import_ids)
        if self.queue is not None:
            try:
                await asyncio.to_thread(self.queue.enqueue, job.job_id)
            except Exception:
                # Do not leave an accepted-looking job that has never reached
                # Redis.  SQL was persisted before dispatch, as required, and
                # deletion also releases any imported-result association.
                self.store.delete_job(job.job_id, owner_id=owner_id)
                raise AnalysisServiceError(
                    "ANALYSIS_QUEUE_UNAVAILABLE", "Analysis queue is unavailable.", 503
                ) from None
            return job.model_copy(deep=True)

        task = asyncio.create_task(self._execute(prepared, job.job_id, owner_id))
        self._tasks.add(task)
        self._job_tasks[job.job_id] = task

        def finished(done: asyncio.Task) -> None:
            self._tasks.discard(done)
            if self._job_tasks.get(job.job_id) is done:
                self._job_tasks.pop(job.job_id, None)

        task.add_done_callback(finished)
        return job.model_copy(deep=True)

    def _ensure_sequence_within_limit(self, sequence: str) -> None:
        if len(sequence) > self.max_sequence_length:
            raise AnalysisServiceError(
                "ANALYSIS_SEQUENCE_TOO_LONG",
                (
                    "Protein sequence exceeds the configured "
                    f"{self.max_sequence_length}-residue limit."
                ),
                413,
            )

    def get(self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID) -> AnalysisJob:
        return self.store.get_job(job_id, owner_id=owner_id)

    def list(
        self,
        *,
        owner_id: str = DEFAULT_OWNER_ID,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        method: str | None = None,
    ) -> HistoryResponse:
        return self.store.list_jobs(
            owner_id=owner_id, limit=limit, offset=offset, status=status, method=method
        )

    def delete(self, job_id: str, *, owner_id: str = DEFAULT_OWNER_ID) -> None:
        if not self.store.delete_job(job_id, owner_id=owner_id):
            raise AnalysisServiceError(
                "ANALYSIS_JOB_NOT_FOUND", "Analysis job is missing or expired.", 404
            )
        task = self._job_tasks.pop(job_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def healthcheck(self) -> dict[str, bool | int | None]:
        if self.queue is None:
            return {"ready": True, "queue": True, "worker": None, "depth": 0}
        queue_ok = await asyncio.to_thread(self.queue.ping)
        if not queue_ok:
            return {"ready": False, "queue": False, "worker": False, "depth": None}
        try:
            depth, workers = await asyncio.gather(
                asyncio.to_thread(self.queue.depth),
                asyncio.to_thread(self.queue.worker_count),
            )
        except Exception:
            return {"ready": False, "queue": False, "worker": False, "depth": None}
        worker_ok = workers > 0
        return {
            "ready": queue_ok and worker_ok,
            "queue": queue_ok,
            "worker": worker_ok,
            "depth": depth,
        }

    def _update(self, job: AnalysisJob) -> None:
        # Retention is fixed at admission; updates never silently extend sequence storage.
        terminal = job.status not in ACTIVE_JOB_STATES
        self.store.update_job(
            job.model_copy(
                update={
                    "completed_at": job.completed_at or (job.updated_at if terminal else None),
                },
                deep=True,
            )
        )

    def _abort(self, job_id: str, owner_id: str, code: str, message: str) -> None:
        try:
            job = self.get(job_id, owner_id=owner_id)
        except AnalysisServiceError as error:
            # A user may delete an active job just before its cancelled runner
            # publishes the terminal snapshot. Deletion wins; the runner must
            # finish quietly and must never recreate the row.
            if error.code == "ANALYSIS_JOB_NOT_FOUND":
                return
            raise
        methods = {}
        for name, current in job.methods.items():
            if current.status in TERMINAL_METHOD_STATES:
                methods[name] = current
            else:
                methods[name] = MethodExecution(
                    method=name,
                    integration_mode=current.integration_mode,
                    status="failed",
                    runtime_ms=current.runtime_ms,
                    error=StructuredError(code=code, message=message),
                )
        ensemble = None
        if job.prediction_mode == "weighted":
            ensemble = self.orchestrator.ensemble.calculate(methods, job.weights)
        self._update(
            job.model_copy(
                update={
                    "status": overall_status(methods),
                    "methods": methods,
                    "ensemble": ensemble,
                    "updated_at": datetime.now(timezone.utc),
                },
                deep=True,
            )
        )

    async def _execute(self, prepared: PreparedAnalysis, job_id: str, owner_id: str) -> None:
        acquired = False
        try:
            # A separate bounded admission wait prevents an indefinitely queued job.
            await asyncio.wait_for(
                self._semaphore.acquire(), timeout=self.orchestrator.job_timeout_seconds
            )
            acquired = True
            await self.orchestrator.run_analysis(
                prepared, self.get(job_id, owner_id=owner_id), self._update
            )
        except (TimeoutError, asyncio.TimeoutError):
            self._abort(
                job_id, owner_id, "ANALYSIS_QUEUE_TIMEOUT", "Analysis queue deadline exceeded."
            )
        except asyncio.CancelledError:
            # Preserve the active snapshot during shutdown. Startup recovery marks it
            # interrupted with a stable service_restart reason in the next process.
            if not self._closed:
                self._abort(
                    job_id, owner_id, "ANALYSIS_CANCELLED", "Analysis execution was cancelled."
                )
        except Exception:
            self._abort(
                job_id, owner_id, "ANALYSIS_EXECUTION_FAILED", "Analysis execution failed."
            )
        finally:
            if acquired:
                self._semaphore.release()

    async def close(self) -> None:
        self._closed = True
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
            self._sweeper = None
        pending = set(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._job_tasks.clear()
        await self.orchestrator.close()
        if self.queue is not None:
            self.queue.close()
        self.store.close()
