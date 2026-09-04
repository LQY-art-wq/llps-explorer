import asyncio
import importlib
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.base import BaseAnalysisAdapter
from app.adapters.dismeta import DisMetaAdapter
from app.adapters.fuzdrop_remote import FuzDropRemoteAdapter
from app.adapters.lreca import LRECAAdapter
from app.adapters.seg import SEGAdapter
from app.main import create_app
from app.schemas.analysis import (
    AdapterHealth,
    AnalysisResult,
    AnalysisStatus,
    MethodCategory,
)
from app.schemas.coordinates import Region, ResiduePosition
from app.schemas.lreca import LRECAHealth
from app.schemas.seg import SEGHealth


def test_package_import_has_no_scientific_runtime_side_effects():
    for name in ("app", "app.main", "app.services.orchestrator", "app.adapters.lreca"):
        assert importlib.import_module(name) is not None
    assert "torch" not in sys.modules


def test_base_contract_accepts_a_minimal_test_subclass():
    class ExampleAdapter(BaseAnalysisAdapter):
        method_id = "lreca"
        category = MethodCategory.PREDICTION

        async def load(self):
            self.status = AnalysisStatus.READY

        async def healthcheck(self):
            return AdapterHealth(method_id=self.method_id, status=self.status, message="Test only")

        async def analyze(self, sequence: str):
            return AnalysisResult(method_id=self.method_id, status=AnalysisStatus.SUCCESS)

    async def exercise():
        adapter = ExampleAdapter()
        assert adapter.status == AnalysisStatus.UNAVAILABLE
        await adapter.load()
        assert (await adapter.healthcheck()).status == AnalysisStatus.READY
        assert (await adapter.analyze("ACDE")).status == AnalysisStatus.SUCCESS

    asyncio.run(exercise())
    with pytest.raises(TypeError):
        BaseAnalysisAdapter()


def test_annotations_and_predictions_are_separate():
    assert {SEGAdapter.category, DisMetaAdapter.category} == {MethodCategory.ANNOTATION}
    assert {LRECAAdapter.category, FuzDropRemoteAdapter.category} == {MethodCategory.PREDICTION}
    with pytest.raises(ValidationError):
        AnalysisResult(method_id="seg", status="success", llps_probability=0.5)


def test_inclusive_region_length_and_python_slice_round_trip():
    region = Region(start=65, end=293)
    assert region.model_dump() == {"start": 65, "end": 293, "length": 229}
    assert region.to_zero_based_half_open() == (64, 293)
    assert Region.from_zero_based_half_open(64, 293) == region
    sequence = "A" * 300
    start, end = region.to_zero_based_half_open()
    assert len(sequence[start:end]) == 229


def test_single_residue_and_last_residue_are_not_lost():
    sequence = "ACDEFG"
    for position in (1, len(sequence)):
        region = Region(start=position, end=position)
        assert region.length == 1
        start, end = region.to_zero_based_half_open()
        assert sequence[start:end] == sequence[position - 1]


@pytest.mark.parametrize("start,end", [(0, 1), (2, 1), (1.5, 3), (True, 3)])
def test_invalid_public_regions_are_rejected(start, end):
    with pytest.raises(ValidationError):
        Region(start=start, end=end)


@pytest.mark.parametrize("start,end", [(-1, 1), (3, 3), (4, 2), (True, 3)])
def test_invalid_internal_regions_are_rejected(start, end):
    with pytest.raises(ValueError):
        Region.from_zero_based_half_open(start, end)


def test_zero_based_residue_position_is_not_a_valid_api_coordinate():
    with pytest.raises(ValidationError):
        ResiduePosition(position=0)


def test_health_is_liveness_only_and_only_authorized_analysis_endpoints_exist():
    class UnavailableAdapter:
        async def load(self):
            pass

        async def close(self):
            pass

        async def healthcheck(self):
            return LRECAHealth(status="unavailable", message="API boundary test only.")

    class UnavailableSEG:
        async def load(self):
            pass

        async def close(self):
            pass

        async def healthcheck(self):
            return SEGHealth()

    with TestClient(
        create_app(lreca_adapter=UnavailableAdapter(), seg_adapter=UnavailableSEG())
    ) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "version": "0.10.0",
            "module": 10,
            "analysis_enabled": False,
        }
        assert set(client.get("/openapi.json").json()["paths"]) == {
            "/api/v1/health",
            "/api/v1/methods/lreca/health",
            "/api/v1/methods/lreca/analyze",
            "/api/v1/methods/fuzdrop/health",
            "/api/v1/methods/fuzdrop/analyze",
            "/api/v1/methods/fuzdrop/import",
            "/api/v1/methods/seg/health",
            "/api/v1/methods/seg/analyze",
            "/api/v1/methods/dismeta/health",
            "/api/v1/methods/dismeta/analyze",
            "/api/v1/methods",
            "/api/v1/config/public",
            "/api/v1/analysis",
            "/api/v1/analysis/history",
            "/api/v1/analysis/{job_id}",
            "/api/v1/analysis/{job_id}/export/json",
            "/api/v1/analysis/{job_id}/export/summary.csv",
            "/api/v1/analysis/{job_id}/export/residues.csv",
            "/api/v1/analysis/{job_id}/export/regions.csv",
            "/api/v1/analysis/{job_id}/export/fasta",
        }
        assert client.post("/api/v1/analyze", json={"sequence": "ACDE"}).status_code == 404
