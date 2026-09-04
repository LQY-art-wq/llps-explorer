"""Durable queue admission, payload privacy, idempotency, and recovery tests."""

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from test_lreca_api import BoundaryStub
from test_orchestrator import SEQUENCE, completed, service_fixture
from test_seg_api import SEGStub

import app.worker as worker_module
from app.core.config import Settings
from app.persistence.database import Base
from app.schemas.orchestration import (
    AnalysisJob,
    AnalysisRequest,
    MethodExecution,
    SequenceMetadata,
)
from app.services.analysis_jobs import (
    AnalysisJobService,
    AnalysisServiceError,
    InMemoryAnalysisJobStore,
)
from app.services.analysis_queue import AnalysisQueueError, RQAnalysisQueue
from app.services.lreca_errors import (
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from app.services.persistent_repositories import SQLAnalysisJobRepository

OWNER_A = "a" * 64
OWNER_B = "b" * 64
OWNER_C = "c" * 64


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(value)
    try:
        yield value
    finally:
        value.dispose()


def queued_job(job_id: str, *, updated_at: datetime | None = None) -> AnalysisJob:
    now = datetime.now(timezone.utc)
    updated = updated_at or now
    return AnalysisJob(
        job_id=job_id,
        created_at=now,
        updated_at=updated,
        expires_at=now + timedelta(days=7),
        status="queued",
        sequence=SequenceMetadata(
            name=None,
            length=len(SEQUENCE),
            sha256=hashlib.sha256(SEQUENCE.encode("ascii")).hexdigest(),
        ),
        normalized_sequence=SEQUENCE,
        selected_methods=["seg"],
        methods={
            "seg": MethodExecution(
                method="seg", status="queued", integration_mode="local_automatic"
            )
        },
    )


class FakeRQQueue:
    def __init__(self):
        self.calls = []

    def enqueue_call(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    def __len__(self):
        return len(self.calls)


class FakeRedis:
    def ping(self):
        return True

    def close(self):
        return None


def test_rq_payload_contains_only_job_id_and_has_finite_retry():
    queue = FakeRQQueue()
    dispatcher = RQAnalysisQueue(
        "redis://unused:6379/0",
        connection=FakeRedis(),
        queue=queue,
        retry_max=2,
        retry_interval_seconds=7,
    )
    dispatcher.enqueue("analysis_private_id")
    assert len(queue.calls) == 1
    positional, options = queue.calls[0]
    assert positional == ("app.worker.execute_analysis_job",)
    assert options["args"] == ("analysis_private_id",)
    assert options["kwargs"] is None
    assert options["retry"].max == 2
    assert options["retry"].intervals == [7]
    assert SEQUENCE not in repr(queue.calls)


@pytest.mark.parametrize(
    "error,expected_code,retryable",
    [
        (
            LRECAUnavailableError("private transport detail"),
            "METHOD_TRANSIENT_FAILURE",
            True,
        ),
        (
            LRECATimeoutError("private timeout detail"),
            "METHOD_TRANSIENT_FAILURE",
            True,
        ),
        (
            LRECAAnalysisError("deterministic service rejection"),
            "METHOD_EXECUTION_FAILED",
            False,
        ),
    ],
)
def test_lreca_retry_classification_is_transient_only(error, expected_code, retryable):
    async def scenario():
        service, _, _, _ = await service_fixture(
            lreca=BoundaryStub(analyze_error=error)
        )
        try:
            result = await completed(
                service,
                {"sequence": SEQUENCE, "selected_methods": ["lreca"]},
            )
            assert result.methods["lreca"].error.code == expected_code
            assert worker_module._has_retryable_lreca_failure(result) is retryable
        finally:
            await service.close()
            await service.orchestrator.registry.close()

    asyncio.run(scenario())


def test_production_requires_durable_queue_redis_and_lreca_service():
    with pytest.raises(ValueError, match="ANALYSIS_QUEUE_BACKEND"):
        Settings(_env_file=None, environment="production")
    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings(
            _env_file=None,
            environment="production",
            analysis_queue_backend="rq",
        )
    production_base = {
        "environment": "production",
        "analysis_queue_backend": "rq",
        "redis_url": "redis://redis:6379/0",
        "lreca_service_url": "http://lreca:8100",
    }
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(_env_file=None, **production_base)
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(
            _env_file=None,
            **production_base,
            database_url="postgresql://llps:password@postgres/llps",
        )
    settings = Settings(
        _env_file=None,
        **production_base,
        database_url="postgresql://llps:password@postgres/llps",
        session_secret="module10-production-session-secret-over-32-chars",
    )
    assert settings.analysis_queue_backend == "rq"


class RecordingDispatcher:
    def __init__(self, *, fail: bool = False, workers: int = 1):
        self.job_ids = []
        self.fail = fail
        self.workers = workers
        self.closed = False

    def enqueue(self, job_id: str):
        self.job_ids.append(job_id)
        if self.fail:
            raise AnalysisQueueError("private redis detail")

    def ping(self):
        return True

    def depth(self):
        return len(self.job_ids)

    def worker_count(self):
        return self.workers

    def close(self):
        self.closed = True


def test_durable_service_persists_then_dispatches_without_local_execution():
    async def scenario():
        template, _, lreca, seg = await service_fixture()
        store = InMemoryAnalysisJobStore()
        dispatcher = RecordingDispatcher()
        service = AnalysisJobService(
            orchestrator=template.orchestrator,
            store=store,
            queue=dispatcher,
        )
        try:
            admitted = await service.submit(
                AnalysisRequest(sequence=SEQUENCE, selected_methods=["seg"])
            )
            assert dispatcher.job_ids == [admitted.job_id]
            assert service.get(admitted.job_id).status == "queued"
            assert not service._tasks
            assert not lreca.calls and not seg.received
        finally:
            await service.close()
        assert dispatcher.closed

    asyncio.run(scenario())


def test_failed_dispatch_removes_sql_admission_and_returns_safe_error():
    async def scenario():
        template, _, _, _ = await service_fixture()
        store = InMemoryAnalysisJobStore()
        service = AnalysisJobService(
            orchestrator=template.orchestrator,
            store=store,
            queue=RecordingDispatcher(fail=True),
        )
        try:
            with pytest.raises(AnalysisServiceError) as caught:
                await service.submit(
                    AnalysisRequest(sequence=SEQUENCE, selected_methods=["seg"])
                )
            assert caught.value.code == "ANALYSIS_QUEUE_UNAVAILABLE"
            assert not store._jobs
            assert "redis" not in caught.value.message.lower()
        finally:
            await service.close()

    asyncio.run(scenario())


def test_durable_health_requires_a_registered_worker():
    async def scenario():
        template, _, _, _ = await service_fixture()
        dispatcher = RecordingDispatcher(workers=0)
        service = AnalysisJobService(orchestrator=template.orchestrator, queue=dispatcher)
        try:
            assert await service.healthcheck() == {
                "ready": False,
                "queue": True,
                "worker": False,
                "depth": 0,
            }
            dispatcher.workers = 1
            assert (await service.healthcheck())["ready"] is True
        finally:
            await service.close()

    asyncio.run(scenario())


def test_sql_admission_distinguishes_owner_and_global_active_limits(engine):
    repository = SQLAnalysisJobRepository(
        engine,
        max_jobs=10,
        max_active_jobs=2,
        max_active_jobs_per_owner=1,
    )
    repository.create_job(queued_job("analysis_owner_a"), owner_id=OWNER_A)
    with pytest.raises(AnalysisServiceError) as owner_error:
        repository.create_job(queued_job("analysis_owner_a_second"), owner_id=OWNER_A)
    assert owner_error.value.code == "ANALYSIS_CONCURRENT_LIMIT"

    repository.create_job(queued_job("analysis_owner_b"), owner_id=OWNER_B)
    with pytest.raises(AnalysisServiceError) as global_error:
        repository.create_job(queued_job("analysis_owner_c"), owner_id=OWNER_C)
    assert global_error.value.code == "ANALYSIS_QUEUE_FULL"


def test_atomic_claim_allows_only_one_execution(engine):
    repository = SQLAnalysisJobRepository(engine)
    job = queued_job("analysis_atomic_claim")
    repository.create_job(job, owner_id=OWNER_A)

    def claim():
        with repository.execution_lock(job.job_id) as acquired:
            return repository.claim_queued_job(job.job_id) if acquired else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: claim(), range(2)))
    claimed = [item for item in claims if item is not None]
    assert len(claimed) == 1
    assert claimed[0].owner_id == OWNER_A
    assert claimed[0].job.status == "running"
    assert repository.get_job(job.job_id, owner_id=OWNER_A).status == "running"


def test_stale_running_job_is_requeued_and_can_be_claimed_again(engine):
    repository = SQLAnalysisJobRepository(engine)
    job = queued_job("analysis_stale_recovery")
    repository.create_job(job, owner_id=OWNER_A)
    claim = repository.claim_queued_job(job.job_id, now=job.created_at)
    assert claim is not None
    recovered = repository.requeue_stale_running_jobs(
        stale_before=job.created_at + timedelta(seconds=1),
        now=job.created_at + timedelta(seconds=2),
    )
    assert recovered == [job.job_id]
    queued = repository.get_job(job.job_id, owner_id=OWNER_A)
    assert queued.status == "queued"
    assert queued.methods["seg"].status == "queued"
    assert repository.claim_queued_job(job.job_id) is not None


def test_exhausted_worker_failure_becomes_structured_interrupted(engine):
    repository = SQLAnalysisJobRepository(engine)
    job = queued_job("analysis_worker_interrupted")
    repository.create_job(job, owner_id=OWNER_A)
    assert repository.claim_queued_job(job.job_id) is not None
    assert repository.interrupt_job(job.job_id)
    result = repository.get_job(job.job_id, owner_id=OWNER_A)
    assert result.status == "interrupted"
    assert result.completed_at is not None
    assert result.methods["seg"].status == "failed"
    assert result.methods["seg"].error.code == "ANALYSIS_WORKER_INTERRUPTED"
    assert result.methods["seg"].reason == "worker_interrupted"


def test_worker_loads_sequence_from_sql_and_persists_result(tmp_path, monkeypatch):
    database_path = tmp_path / "worker.sqlite3"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )
    database_engine = worker_module.create_database_engine(settings.database_url)
    Base.metadata.create_all(database_engine)
    repository = SQLAnalysisJobRepository(database_engine)
    job = queued_job("analysis_sql_worker")
    repository.create_job(job, owner_id=OWNER_A)
    database_engine.dispose()

    class ConfiguredSEGStub(SEGStub):
        def __init__(self, _settings):
            super().__init__()

    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_module, "SEGAdapter", ConfiguredSEGStub)
    assert worker_module.execute_analysis_job(job.job_id) == "success"

    reopened_engine = worker_module.create_database_engine(settings.database_url)
    try:
        stored = SQLAnalysisJobRepository(reopened_engine).get_job(
            job.job_id, owner_id=OWNER_A
        )
        assert stored.status == "success"
        assert stored.completed_at is not None
        assert stored.methods["seg"].status == "success"
        assert stored.methods["seg"].result.sequence_sha256 == job.sequence.sha256
    finally:
        reopened_engine.dispose()


def test_worker_startup_preflights_worker_owned_seg(monkeypatch):
    instances = []

    class ConfiguredSEGStub(SEGStub):
        def __init__(self, _settings):
            super().__init__()
            instances.append(self)

    monkeypatch.setattr(worker_module, "SEGAdapter", ConfiguredSEGStub)
    asyncio.run(
        worker_module._verify_worker_dependencies(Settings(_env_file=None))
    )
    assert len(instances) == 1
    assert instances[0].loads == 1
    assert instances[0].closes == 1
