"""Capability and failure matrix using explicitly synthetic adapter results."""

import asyncio
import logging
import time

import pytest
from test_lreca_api import BoundaryStub, boundary_result
from test_seg_api import SEGStub

from app.schemas.orchestration import AnalysisRequest
from app.services.analysis_jobs import AnalysisJobService, AnalysisServiceError
from app.services.ensemble import EnsembleCalculator
from app.services.fuzdrop_import import import_fuzdrop_result
from app.services.imported_results import InMemoryImportedResultStore
from app.services.method_registry import MethodRegistry
from app.services.orchestrator import AnalysisOrchestrator

SEQUENCE = "ACDEFGHIKLMNPQRSTVWY"


class NeverAutomatic:
    async def healthcheck(self):
        raise AssertionError("Manual and blocked adapters must not be consulted")

    async def analyze(self, sequence):
        raise AssertionError("Manual and blocked adapters must not run")


def imported_fixture(sequence=SEQUENCE, **updates):
    return import_fuzdrop_result(
        {
            "sequence": sequence,
            "pLLPS": 0.68,
            "source_declaration": "official_fuzdrop_export",
            "coordinate_system": "one_based_inclusive",
            **updates,
        }
    )


async def service_fixture(*, lreca=None, seg=None, manual=True, **options):
    lreca = lreca if lreca is not None else BoundaryStub()
    seg = seg if seg is not None else SEGStub()
    await lreca.load()
    await seg.load()
    registry = MethodRegistry(
        {"lreca": lreca, "seg": seg, "fuzdrop": NeverAutomatic(), "dismeta": NeverAutomatic()},
        manual_import_enabled=manual,
    )
    store = InMemoryImportedResultStore()
    service = AnalysisJobService(
        orchestrator=AnalysisOrchestrator(
            registry,
            store,
            ensemble=EnsembleCalculator(),
            **options,
        )
    )
    return service, store, lreca, seg


async def completed(service, request):
    admitted = await service.submit(AnalysisRequest(**request))
    assert admitted.status == "queued"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.get(admitted.job_id)
        if job.status not in {"queued", "running"}:
            return job
        await asyncio.sleep(0.001)
    raise AssertionError("Synthetic analysis failed to finish")


@pytest.mark.parametrize(
    "methods,with_import,mode,status,states",
    [
        (["lreca"], False, "independent", "success", ["success"]),
        (["seg"], False, "independent", "success", ["success"]),
        (
            ["fuzdrop"],
            False,
            "independent",
            "external_result_required",
            ["external_result_required"],
        ),
        (["fuzdrop"], True, "independent", "success", ["success"]),
        (["dismeta"], False, "independent", "unavailable", ["unavailable"]),
        (["lreca", "seg"], False, "independent", "success", ["success", "success"]),
        (["lreca", "fuzdrop"], True, "independent", "success", ["success", "success"]),
        (
            ["lreca", "fuzdrop"],
            False,
            "independent",
            "partial_success",
            ["success", "external_result_required"],
        ),
        (["lreca", "fuzdrop"], True, "weighted", "success", ["success", "success"]),
        (
            ["lreca", "fuzdrop"],
            False,
            "weighted",
            "partial_success",
            ["success", "external_result_required"],
        ),
        (
            ["lreca", "fuzdrop", "seg", "dismeta"],
            True,
            "weighted",
            "partial_success",
            ["success", "success", "success", "unavailable"],
        ),
        (
            ["lreca", "fuzdrop", "seg", "dismeta"],
            False,
            "weighted",
            "partial_success",
            ["success", "external_result_required", "success", "unavailable"],
        ),
    ],
)
def test_required_routing_matrix(methods, with_import, mode, status, states):
    async def scenario():
        service, store, lreca, seg = await service_fixture()
        request = {"sequence": SEQUENCE, "selected_methods": methods, "prediction_mode": mode}
        if mode == "weighted":
            request["weights"] = {"lreca": 0.6, "fuzdrop": 0.4}
        native = None
        if with_import:
            native = imported_fixture()
            reference = store.put(native)
            request["external_results"] = {"fuzdrop": {"result_id": reference.result_id}}
        try:
            job = await completed(service, request)
            assert job.status == status
            assert [job.methods[method].status for method in methods] == states
            assert set(job.methods) == set(methods)
            assert len(lreca.calls) == int("lreca" in methods)
            assert len(seg.received) == int("seg" in methods)
            if with_import:
                assert job.methods["fuzdrop"].result == native
            if mode == "independent":
                assert job.ensemble is None
            elif with_import:
                assert job.ensemble.status == "success"
                assert job.ensemble.score == pytest.approx(0.422, abs=1e-15)
                assert job.ensemble.weights == request["weights"]
                assert job.ensemble.calibration_status == "not_calibrated"
            else:
                assert job.ensemble.status == "unavailable"
                assert job.ensemble.reason == "fuzdrop_external_result_required"
                assert job.ensemble.score is job.ensemble.label is None
            if "seg" in methods:
                result = job.methods["seg"].result.model_dump()
                assert not {"label", "raw_score", "global_score", "probability"} & result.keys()
            if "dismeta" not in methods:
                assert "dismeta" not in " ".join(job.warnings).lower()
        finally:
            await service.close()
            await service.orchestrator.registry.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["lreca", "seg"])
def test_failures_are_isolated_and_private(method, caplog):
    private = "/srv/private/model " + SEQUENCE

    class FailedSEG(SEGStub):
        async def analyze(self, sequence):
            raise RuntimeError(private)

    async def scenario():
        service, _, _, _ = await service_fixture(
            lreca=BoundaryStub(analyze_error=RuntimeError(private)) if method == "lreca" else None,
            seg=FailedSEG() if method == "seg" else None,
        )
        try:
            job = await completed(
                service, {"sequence": SEQUENCE, "selected_methods": ["lreca", "seg"]}
            )
            assert job.status == "partial_success"
            assert job.methods[method].error.code == "METHOD_EXECUTION_FAILED"
            assert job.methods["seg" if method == "lreca" else "lreca"].status == "success"
            assert private not in job.model_dump_json()
            assert SEQUENCE not in caplog.text
        finally:
            await service.close()

    with caplog.at_level(logging.INFO, logger="uvicorn.error.analysis.orchestrator"):
        asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["independent", "weighted"])
def test_import_reuse_and_sequence_mismatch_before_execution(mode):
    async def scenario():
        service, store, lreca, _ = await service_fixture()
        reference = store.put(imported_fixture())
        request = {
            "sequence": SEQUENCE,
            "selected_methods": ["lreca", "fuzdrop"],
            "prediction_mode": mode,
            "external_results": {"fuzdrop": {"result_id": reference.result_id}},
        }
        if mode == "weighted":
            request["weights"] = {"lreca": 0.6, "fuzdrop": 0.4}
        try:
            first, second = await completed(service, request), await completed(service, request)
            assert first.job_id != second.job_id
            assert first.methods["fuzdrop"].result == second.methods["fuzdrop"].result
            request["sequence"] = SEQUENCE[::-1]
            with pytest.raises(AnalysisServiceError) as error:
                await service.submit(AnalysisRequest(**request))
            assert error.value.code == "EXTERNAL_RESULT_SEQUENCE_MISMATCH"
            assert len(lreca.calls) == 2
        finally:
            await service.close()

    asyncio.run(scenario())


def test_automatic_methods_run_concurrently_and_publish_independent_progress():
    async def scenario():
        lreca_started, seg_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class SlowLRECA(BoundaryStub):
            async def analyze(self, sequence):
                lreca_started.set()
                await seg_started.wait()
                await release.wait()
                return boundary_result(sequence)

        class FastSEG(SEGStub):
            async def analyze(self, sequence):
                seg_started.set()
                await lreca_started.wait()
                return await super().analyze(sequence)

        service, _, _, _ = await service_fixture(lreca=SlowLRECA(), seg=FastSEG())
        try:
            job = await service.submit(
                AnalysisRequest(sequence=SEQUENCE, selected_methods=["lreca", "seg"])
            )
            await asyncio.wait_for(seg_started.wait(), 1)
            for _ in range(100):
                current = service.get(job.job_id)
                if current.methods["seg"].status == "success":
                    break
                await asyncio.sleep(0.001)
            assert current.status == "running"
            assert current.methods["lreca"].status == "running"
            assert current.methods["seg"].status == "success"
            release.set()
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("global_missing", [False, True])
def test_weighted_no_fallback_after_lreca_failure_or_missing_import_score(global_missing):
    async def scenario():
        service, store, _, _ = await service_fixture(
            lreca=None if global_missing else BoundaryStub(analyze_error=RuntimeError("failed"))
        )
        native = imported_fixture(
            **({"pLLPS": None, "regions_tsv": "type\tstart\tend\n"} if global_missing else {})
        )
        reference = store.put(native)
        try:
            job = await completed(
                service,
                {
                    "sequence": SEQUENCE,
                    "selected_methods": ["lreca", "fuzdrop"],
                    "prediction_mode": "weighted",
                    "weights": {"lreca": 0.0, "fuzdrop": 1.0},
                    "external_results": {"fuzdrop": {"result_id": reference.result_id}},
                },
            )
            assert job.ensemble.status == "unavailable"
            assert job.ensemble.score is None
            assert job.ensemble.reason == (
                "fuzdrop_global_score_missing" if global_missing else "lreca_result_unavailable"
            )
        finally:
            await service.close()

    asyncio.run(scenario())


def test_manual_disabled_and_auto_unavailable_are_not_execution_failures():
    async def scenario():
        service, _, _, _ = await service_fixture(manual=False)
        try:
            job = await completed(service, {"sequence": SEQUENCE, "selected_methods": ["fuzdrop"]})
            assert job.status == "unavailable"
            assert job.methods["fuzdrop"].reason == "manual_import_disabled"
        finally:
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("behavior", ["wrong_sequence", "invalid", "self_cancel", "wrong_label"])
def test_bad_native_result_is_a_method_failure(behavior):
    class Broken(BoundaryStub):
        async def analyze(self, sequence):
            if behavior == "self_cancel":
                raise asyncio.CancelledError
            if behavior == "wrong_sequence":
                return boundary_result(sequence[::-1])
            if behavior == "wrong_label":
                return boundary_result(sequence).model_copy(update={"label": "P"})
            return boundary_result(sequence).model_copy(update={"raw_score": float("nan")})

    async def scenario():
        service, _, _, _ = await service_fixture(lreca=Broken())
        try:
            job = await completed(
                service, {"sequence": SEQUENCE, "selected_methods": ["lreca", "seg"]}
            )
            assert job.status == "partial_success"
            assert job.methods["seg"].status == "success"
            assert (
                job.methods["lreca"].error.code
                == {
                    "wrong_sequence": "METHOD_RESULT_SEQUENCE_MISMATCH",
                "invalid": "METHOD_RESULT_INVALID",
                "wrong_label": "METHOD_RESULT_INVALID",
                    "self_cancel": "METHOD_EXECUTION_CANCELLED",
                }[behavior]
            )
        finally:
            await service.close()

    asyncio.run(scenario())
