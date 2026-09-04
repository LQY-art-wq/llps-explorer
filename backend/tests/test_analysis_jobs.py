"""Deadlines, progress, admission, expiry, and cleanup for the process-local runner."""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import pytest
from test_lreca_api import BoundaryStub, boundary_result
from test_orchestrator import SEQUENCE, completed, imported_fixture, service_fixture

from app.schemas.orchestration import AnalysisRequest
from app.services.analysis_jobs import (
    AnalysisJobService,
    AnalysisServiceError,
    InMemoryAnalysisJobStore,
)


@pytest.mark.parametrize("method_timeout,job_timeout", [(0.02, 1), (1, 0.02)])
def test_deadline_publishes_without_waiting_for_adapter_cancellation_cleanup(
    method_timeout,
    job_timeout,
):
    async def scenario():
        release, cancelled = asyncio.Event(), asyncio.Event()

        class Draining(BoundaryStub):
            async def analyze(self, sequence):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release.wait()  # Models an outstanding worker RPC drain.
                    return boundary_result(sequence)

        service, _, _, _ = await service_fixture(
            lreca=Draining(),
            method_timeout_seconds=method_timeout,
            job_timeout_seconds=job_timeout,
        )
        try:
            started = time.monotonic()
            job = await completed(
                service, {"sequence": SEQUENCE, "selected_methods": ["lreca", "seg"]}
            )
            assert time.monotonic() - started < 0.5
            assert job.status == "partial_success"
            assert job.methods["lreca"].error.code == "METHOD_TIMEOUT"
            assert job.methods["seg"].status == "success"
            assert cancelled.is_set() and service.orchestrator._owned
            followup = await completed(
                service, {"sequence": SEQUENCE, "selected_methods": ["lreca", "seg"]}
            )
            assert followup.methods["lreca"].error.code == "METHOD_BUSY_AFTER_TIMEOUT"
            release.set()
            await asyncio.sleep(0.01)
            assert service.get(job.job_id).methods["lreca"].status == "failed"
            assert not service.orchestrator._owned
        finally:
            release.set()
            await service.close()

    asyncio.run(scenario())


def test_jobs_survive_submitter_cancellation_and_snapshots_do_not_mutate_storage():
    async def scenario():
        service, store, _, _ = await service_fixture()
        reference = store.put(imported_fixture())
        try:
            submitted = asyncio.Event()
            admitted_jobs = []

            async def submitter():
                admitted_jobs.append(
                    await service.submit(
                        AnalysisRequest(
                            sequence=SEQUENCE,
                            selected_methods=["fuzdrop"],
                            external_results={"fuzdrop": {"result_id": reference.result_id}},
                        )
                    )
                )
                submitted.set()
                await asyncio.Event().wait()

            task = asyncio.create_task(submitter())
            await submitted.wait()
            admitted = admitted_jobs[0]
            task.cancel()  # Simulate a caller disconnecting after admission.
            with pytest.raises(asyncio.CancelledError):
                await task
            admitted.methods.clear()
            for _ in range(100):
                result = service.get(admitted.job_id)
                if result.status not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.002)
            assert result.status == "success"
            result.methods["fuzdrop"].result.warnings.append("caller-only mutation")
            result.methods.clear()
            saved = service.get(admitted.job_id)
            assert "caller-only mutation" not in saved.methods["fuzdrop"].result.warnings
            assert len(saved.methods) == 1
        finally:
            await service.close()

    asyncio.run(scenario())


def test_terminal_job_ttl_capacity_and_idle_cleanup():
    async def scenario():
        original, imports, _, _ = await service_fixture()
        job_store = InMemoryAnalysisJobStore(max_jobs=1)
        service = AnalysisJobService(
            orchestrator=original.orchestrator,
            store=job_store,
            ttl_seconds=0.04,
            cleanup_interval_seconds=0.01,
        )
        await service.start()
        try:
            job = await completed(service, {"sequence": SEQUENCE, "selected_methods": ["seg"]})
            with pytest.raises(AnalysisServiceError) as error:
                await service.submit(AnalysisRequest(sequence=SEQUENCE, selected_methods=["seg"]))
            assert error.value.code == "ANALYSIS_CAPACITY_EXCEEDED"
            await asyncio.sleep(0.08)
            assert not job_store._jobs  # No read/new request was needed to remove expired bytes.
            with pytest.raises(AnalysisServiceError) as error:
                service.get(job.job_id)
            assert error.value.code == "ANALYSIS_JOB_NOT_FOUND"
            assert (
                await completed(service, {"sequence": SEQUENCE, "selected_methods": ["seg"]})
            ).status == "success"
        finally:
            await service.close()
        assert service._sweeper is None and not job_store._jobs
        with pytest.raises(AnalysisServiceError) as error:
            await service.submit(AnalysisRequest(sequence=SEQUENCE, selected_methods=["seg"]))
        assert error.value.http_status == 503
        imports.close()

    asyncio.run(scenario())


def test_reference_is_pinned_for_accepted_job_even_if_import_store_expires():
    async def scenario():
        service, store, _, _ = await service_fixture()
        record = store.put(imported_fixture())
        await service._semaphore.acquire()
        # Occupy all slots so the accepted job remains queued until after import removal.
        for _ in range(3):
            await service._semaphore.acquire()
        job = await service.submit(
            AnalysisRequest(
                sequence=SEQUENCE,
                selected_methods=["fuzdrop"],
                external_results={"fuzdrop": {"result_id": record.result_id}},
            )
        )
        store.close()
        service._semaphore.release()
        try:
            await asyncio.sleep(0.02)
            result = service.get(job.job_id)
            assert result.status == "success"
            assert result.methods["fuzdrop"].result.sequence_sha256 == record.sequence_sha256
        finally:
            await service.close()

    asyncio.run(scenario())


def test_queue_timeout_and_shutdown_clear_owned_jobs():
    async def scenario():
        service, _, _, _ = await service_fixture(job_timeout_seconds=0.02)
        for _ in range(4):
            await service._semaphore.acquire()
        job = await completed(service, {"sequence": SEQUENCE, "selected_methods": ["seg"]})
        assert job.status == "failed"
        assert job.methods["seg"].error.code == "ANALYSIS_QUEUE_TIMEOUT"
        await service.close()
        assert not service._tasks

    asyncio.run(scenario())


def test_missing_import_rejected_before_job_or_adapter_creation():
    async def scenario():
        service, _, lreca, seg = await service_fixture()
        try:
            with pytest.raises(AnalysisServiceError) as error:
                await service.submit(
                    AnalysisRequest(
                        sequence=SEQUENCE,
                        selected_methods=["lreca", "seg", "fuzdrop"],
                        external_results={"fuzdrop": {"result_id": "missing_import"}},
                    )
                )
            assert error.value.code == "EXTERNAL_RESULT_NOT_FOUND"
            assert not lreca.calls and not seg.received and not service._tasks
        finally:
            await service.close()

    asyncio.run(scenario())


def test_active_snapshot_is_removed_when_retention_expires():
    async def scenario():
        service, _, _, _ = await service_fixture()
        try:
            job = await service.submit(AnalysisRequest(sequence=SEQUENCE, selected_methods=["seg"]))
            future = datetime.now(timezone.utc) + timedelta(days=1)
            store = InMemoryAnalysisJobStore(clock=lambda: future)
            store.add(job)
            store.purge_expired()
            assert not store._jobs
            with pytest.raises(AnalysisServiceError) as error:
                store.get(job.job_id)
            assert error.value.code == "ANALYSIS_JOB_NOT_FOUND"
        finally:
            await service.close()

    asyncio.run(scenario())


def test_sequence_length_limit_rejects_before_adapter_execution():
    async def scenario():
        template, imports, lreca, seg = await service_fixture()
        service = AnalysisJobService(
            orchestrator=template.orchestrator,
            max_sequence_length=4,
        )
        try:
            with pytest.raises(AnalysisServiceError) as error:
                await service.submit(
                    AnalysisRequest(sequence="ACDEF", selected_methods=["lreca", "seg"])
                )
            assert error.value.code == "ANALYSIS_SEQUENCE_TOO_LONG"
            assert error.value.http_status == 413
            assert not service._tasks and not lreca.calls and not seg.received
        finally:
            await service.close()
            imports.close()

    asyncio.run(scenario())


def test_sequence_length_limit_counts_canonical_residues_not_wrapped_fasta_bytes():
    async def scenario():
        template, imports, _, seg = await service_fixture()
        service = AnalysisJobService(
            orchestrator=template.orchestrator,
            max_sequence_length=8,
        )
        try:
            request = AnalysisRequest(
                sequence=">wrapped boundary\nACDE\nFGHI\n",
                selected_methods=["seg"],
            )
            admitted = await completed(service, request.model_dump())
            assert admitted.sequence.length == 8
            assert admitted.normalized_sequence == "ACDEFGHI"
            assert admitted.status == "success"
            assert seg.received == ["ACDEFGHI"]
        finally:
            await service.close()
            imports.close()

    asyncio.run(scenario())


def test_periodic_cleanup_logs_only_error_type_and_retries(caplog):
    private_error = "ACDEFGHIKLMNPQRSTVWY-private-cleanup-payload"

    async def scenario():
        template, imports, _, _ = await service_fixture()
        repository = InMemoryAnalysisJobStore()
        service = AnalysisJobService(
            orchestrator=template.orchestrator,
            store=repository,
            ttl_seconds=1,
            cleanup_interval_seconds=0.005,
        )
        await service.start()
        original_cleanup = repository.cleanup_expired_jobs
        retried = asyncio.Event()
        calls = 0

        def flaky_cleanup():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError(private_error)
            original_cleanup()
            retried.set()
            return 0

        repository.cleanup_expired_jobs = flaky_cleanup
        try:
            await asyncio.wait_for(retried.wait(), timeout=0.2)
            assert calls >= 2
            assert service._sweeper is not None and not service._sweeper.done()
        finally:
            await service.close()
            imports.close()

    with caplog.at_level(logging.WARNING, logger="uvicorn.error.analysis.cleanup"):
        asyncio.run(scenario())
    assert "RuntimeError" in caplog.text
    assert private_error not in caplog.text
