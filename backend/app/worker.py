"""RQ entry point for SQL-backed analysis jobs.

Run the production worker with ``python -m app.worker``.  Each Redis message
contains only a job id; all scientific inputs and outputs remain in SQL.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from rq import Queue, Worker, get_current_job
from rq.job import Job
from rq.serializers import JSONSerializer

from app.adapters.dismeta import DisMetaAdapter
from app.adapters.fuzdrop_remote import FuzDropRemoteAdapter
from app.adapters.lreca import LRECAAdapter
from app.adapters.seg import SEGAdapter
from app.core.config import Settings, get_settings
from app.core.observability import configure_logging
from app.persistence.database import create_database_engine
from app.schemas.orchestration import AnalysisJob, AnalysisRequest
from app.services.analysis_jobs import ACTIVE_JOB_STATES
from app.services.analysis_queue import RQAnalysisQueue, queue_from_settings
from app.services.ensemble import EnsembleCalculator
from app.services.imported_results import ImportedResultError
from app.services.method_registry import MethodRegistry
from app.services.orchestrator import AnalysisOrchestrator
from app.services.persistent_repositories import (
    ClaimedAnalysisJob,
    SQLAnalysisJobRepository,
    SQLImportedResultStore,
)

logger = logging.getLogger("llps.analysis.worker")
_JOB_ID = re.compile(r"^analysis_[A-Za-z0-9_-]{1,119}$")
_RETRYABLE_METHOD_ERRORS = frozenset(
    {"METHOD_TRANSIENT_FAILURE", "METHOD_BUSY_AFTER_TIMEOUT"}
)


class AnalysisWorkerError(RuntimeError):
    """Safe retryable error; its message contains no sequence or service URL."""


class PermanentAnalysisWorkerError(RuntimeError):
    """Invalid persisted input that must not be retried."""


async def _verify_worker_dependencies(settings: Settings) -> None:
    """Fail startup unless worker-owned SEG and the private LRECA service are ready."""
    seg = SEGAdapter(settings)
    lreca = None
    try:
        await seg.load()
        seg_health = await seg.healthcheck()
        if not seg_health.available:
            raise AnalysisWorkerError("SEG worker dependency is unavailable.")
        if settings.lreca_service_url is not None:
            lreca = await _build_lreca_adapter(settings)
    finally:
        await seg.close()
        if lreca is not None:
            await lreca.close()


def _validate_job_id(job_id: object) -> str:
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise PermanentAnalysisWorkerError("RQ payload must contain one valid analysis job id.")
    return job_id


def _repository(settings: Settings) -> tuple[Any, SQLAnalysisJobRepository]:
    engine = create_database_engine(settings.database_url)
    repository = SQLAnalysisJobRepository(
        engine,
        max_jobs=settings.analysis_max_jobs,
        max_active_jobs=settings.analysis_queue_max_jobs,
        max_active_jobs_per_owner=settings.analysis_owner_active_job_limit,
    )
    return engine, repository


async def _build_lreca_adapter(settings: Settings):
    if settings.lreca_service_url is None:
        adapter = LRECAAdapter(settings)
    else:
        # Kept local to the worker so development installations can import the
        # API without constructing an HTTP client or loading Torch.
        from app.adapters.lreca_remote import RemoteLRECAAdapter

        adapter = RemoteLRECAAdapter(
            settings.lreca_service_url,
            request_timeout_seconds=settings.lreca_service_timeout_seconds,
            connect_timeout_seconds=settings.lreca_service_connect_timeout_seconds,
            expected_checkpoint_sha256=settings.lreca_checkpoint_sha256,
        )
    await adapter.load()
    health = await adapter.healthcheck()
    if not health.loaded:
        raise AnalysisWorkerError("LRECA internal service is not ready.")
    return adapter


def _request_from_claim(claim: ClaimedAnalysisJob) -> AnalysisRequest:
    job = claim.job
    if job.normalized_sequence is None:
        raise PermanentAnalysisWorkerError("Persisted analysis sequence is unavailable.")
    if len(claim.import_result_ids) > 1 or (
        claim.import_result_ids and "fuzdrop" not in job.selected_methods
    ):
        raise PermanentAnalysisWorkerError("Persisted imported-result links are invalid.")
    external_results = (
        {"fuzdrop": {"result_id": claim.import_result_ids[0]}}
        if claim.import_result_ids
        else {}
    )
    return AnalysisRequest(
        sequence=job.normalized_sequence,
        sequence_name=job.sequence.name,
        selected_methods=job.selected_methods,
        prediction_mode=job.prediction_mode,
        weights=job.weights,
        external_results=external_results,
    )


def _with_completion(job: AnalysisJob) -> AnalysisJob:
    if job.status in ACTIVE_JOB_STATES:
        return job
    return job.model_copy(
        update={"completed_at": job.completed_at or job.updated_at}, deep=True
    )


def _has_retryable_lreca_failure(job: AnalysisJob) -> bool:
    execution = job.methods.get("lreca")
    return bool(
        execution is not None
        and execution.status == "failed"
        and execution.error is not None
        and execution.error.code in _RETRYABLE_METHOD_ERRORS
    )


async def _run_claimed_job(
    settings: Settings,
    repository: SQLAnalysisJobRepository,
    claim: ClaimedAnalysisJob,
) -> AnalysisJob:
    request = _request_from_claim(claim)
    retention_seconds = settings.analysis_retention_days * 86400
    imported_store = SQLImportedResultStore(
        repository.engine,
        ttl_seconds=retention_seconds,
        max_entries=settings.external_result_max_entries,
    )
    lreca = None
    fuzdrop = FuzDropRemoteAdapter(settings)
    seg = SEGAdapter(settings)
    dismeta = DisMetaAdapter(settings)
    registry = None
    orchestrator = None
    try:
        if "lreca" in request.selected_methods:
            lreca = await _build_lreca_adapter(settings)
        await fuzdrop.load()
        if "seg" in request.selected_methods:
            try:
                await seg.load()
            except Exception as error:
                logger.warning("SEG worker initialization failed (%s).", type(error).__name__)
        await dismeta.load()
        registry = MethodRegistry(
            {
                "lreca": lreca,
                "fuzdrop": fuzdrop,
                "seg": seg,
                "dismeta": dismeta,
            },
            manual_import_enabled=settings.fuzdrop_manual_import_enabled,
        )
        orchestrator = AnalysisOrchestrator(
            registry,
            imported_store,
            ensemble=EnsembleCalculator(settings.ensemble_threshold),
            method_timeout_seconds=settings.analysis_method_timeout_seconds,
            job_timeout_seconds=settings.analysis_job_timeout_seconds,
        )
        try:
            prepared = await orchestrator.prepare(request, owner_id=claim.owner_id)
        except (ImportedResultError, ValueError) as error:
            raise PermanentAnalysisWorkerError("Persisted analysis inputs are invalid.") from error

        def persist(snapshot: AnalysisJob) -> None:
            repository.update_job(_with_completion(snapshot))

        return await orchestrator.run_analysis(prepared, claim.job, persist)
    finally:
        if orchestrator is not None:
            await orchestrator.close()
        if registry is not None:
            await registry.close()
        await dismeta.close()
        await seg.close()
        await fuzdrop.close()
        if lreca is not None:
            await lreca.close()
        imported_store.close()


def execute_analysis_job(job_id: str) -> str:
    """RQ callable.  Its sole argument is the opaque SQL job id."""
    job_id = _validate_job_id(job_id)
    settings = get_settings()
    engine, repository = _repository(settings)
    try:
        with repository.execution_lock(job_id) as acquired:
            if not acquired:
                return "execution_already_owned"
            claim = repository.claim_queued_job(job_id)
            if claim is None:
                return "job_not_queued"
            logger.info(
                "Analysis job claimed",
                extra={
                    "job_id": job_id,
                    "status": "running",
                    "sequence_length": claim.job.sequence.length,
                    "sequence_sha256": claim.job.sequence.sha256,
                },
            )
            try:
                result = asyncio.run(_run_claimed_job(settings, repository, claim))
            except PermanentAnalysisWorkerError:
                repository.interrupt_job(
                    job_id,
                    code="ANALYSIS_INPUT_INVALID",
                    message="Persisted analysis inputs failed validation.",
                    reason="persisted_input_invalid",
                )
                return "invalid_persisted_input"
            except Exception:
                # RQ's finite Retry policy and exception handler decide whether
                # this returns to queued or becomes terminal interrupted.
                raise AnalysisWorkerError("Analysis worker execution failed.") from None

            rq_job = get_current_job()
            retries_left = int(getattr(rq_job, "retries_left", 0) or 0)
            if _has_retryable_lreca_failure(result) and retries_left > 0:
                repository.requeue_job(job_id)
                raise AnalysisWorkerError("Transient LRECA transport failure.")
            logger.info(
                "Analysis job completed",
                extra={
                    "job_id": job_id,
                    "status": result.status,
                    "sequence_length": claim.job.sequence.length,
                    "sequence_sha256": claim.job.sequence.sha256,
                },
            )
            return result.status
    finally:
        engine.dispose()


def _job_id_from_rq(job: Job) -> str | None:
    try:
        if job.func_name != "app.worker.execute_analysis_job" or len(job.args) != 1:
            return None
        return _validate_job_id(job.args[0])
    except (PermanentAnalysisWorkerError, TypeError, ValueError):
        return None


def sync_rq_failure(job: Job, *_error: object) -> bool:
    """Keep SQL aligned with normal failures and abandoned RQ executions."""
    job_id = _job_id_from_rq(job)
    if job_id is None:
        return True
    settings = get_settings()
    engine, repository = _repository(settings)
    try:
        retries_left = int(getattr(job, "retries_left", 0) or 0)
        if retries_left > 0:
            repository.requeue_job(job_id)
        else:
            repository.interrupt_job(
                job_id,
                code="ANALYSIS_WORKER_INTERRUPTED",
                message="Analysis worker stopped before completing the job.",
                reason="worker_retries_exhausted",
            )
    finally:
        engine.dispose()
    return True


def sync_killed_work_horse(job: Job, *_details: object) -> None:
    sync_rq_failure(job)


class AnalysisWorker(Worker):
    """RQ worker with SQL recovery integrated into its maintenance cycle."""

    def __init__(self, *args, settings: Settings, dispatcher: RQAnalysisQueue, **kwargs) -> None:
        self.analysis_settings = settings
        self.dispatcher = dispatcher
        super().__init__(*args, **kwargs)

    def run_maintenance_tasks(self) -> None:
        super().run_maintenance_tasks()
        engine, repository = _repository(self.analysis_settings)
        try:
            now = datetime.now(timezone.utc)
            stale_before = now - timedelta(
                seconds=self.analysis_settings.analysis_worker_recovery_timeout_seconds
            )
            recovered = repository.requeue_stale_running_jobs(
                stale_before=stale_before, now=now
            )
            queued = repository.queued_job_ids(
                limit=self.analysis_settings.analysis_queue_max_jobs
            )
            for job_id in dict.fromkeys([*recovered, *queued]):
                self.dispatcher.enqueue(job_id)
        except Exception as error:
            logger.warning("Analysis recovery scan failed (%s).", type(error).__name__)
        finally:
            engine.dispose()


def main() -> int:
    settings = get_settings()
    configure_logging(
        service="llps-worker",
        level=settings.log_level,
        structured=settings.environment == "production" or settings.structured_logging,
    )
    if settings.analysis_queue_backend != "rq":
        raise SystemExit("The standalone worker requires ANALYSIS_QUEUE_BACKEND=rq.")
    try:
        asyncio.run(_verify_worker_dependencies(settings))
    except Exception as error:
        logger.error("Worker dependency check failed error_type=%s.", type(error).__name__)
        raise SystemExit("Worker dependencies are unavailable; startup stopped.") from None
    dispatcher = queue_from_settings(settings)
    if not dispatcher.ping():
        raise SystemExit("Redis is unavailable; analysis worker did not start.")
    queue = Queue(
        name=settings.analysis_queue_name,
        connection=dispatcher.redis,
        serializer=JSONSerializer,
    )
    worker = AnalysisWorker(
        [queue],
        settings=settings,
        dispatcher=dispatcher,
        connection=dispatcher.redis,
        serializer=JSONSerializer,
        exception_handlers=[sync_rq_failure],
        work_horse_killed_handler=sync_killed_work_horse,
        maintenance_interval=settings.analysis_worker_maintenance_interval_seconds,
        log_job_description=False,
    )
    try:
        worker.work(with_scheduler=True)
        return 0
    finally:
        dispatcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
