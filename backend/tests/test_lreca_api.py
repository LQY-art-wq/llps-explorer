"""API boundary tests use an explicit stub; real predictions are tested separately."""

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.lreca import (
    LRECAKDE,
    LRECACriticalRegion,
    LRECAHealth,
    LRECAResult,
    PublicLRECAModelMetadata,
)
from app.services.lreca_errors import (
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from app.services.sequence_validation import SequenceValidationError, normalize_sequence


class BoundaryStub:
    """In-memory routing fixture. It never represents scientific inference."""

    def __init__(self, *, load_error=None, analyze_error=None):
        self.load_error = load_error
        self.analyze_error = analyze_error
        self.loads = 0
        self.closes = 0
        self.loaded = False
        self.calls = []

    async def load(self):
        self.loads += 1
        if self.load_error is not None:
            raise self.load_error
        self.loaded = True

    async def close(self):
        self.closes += 1
        self.loaded = False

    async def healthcheck(self):
        return LRECAHealth(
            status="ready" if self.loaded else "unavailable",
            loaded=self.loaded,
            device="cpu" if self.loaded else None,
            message="API boundary stub; no scientific runtime.",
        )

    async def analyze(self, sequence, *, include_attribution=True, include_kde=True):
        self.calls.append((sequence, include_attribution, include_kde))
        if not self.loaded:
            raise LRECAUnavailableError("Boundary stub did not load.")
        if self.analyze_error is not None:
            raise self.analyze_error
        return boundary_result(sequence)


def boundary_result(sequence="ACDE"):
    """Synthetic payload for serializer assertions, never a regression baseline."""
    commit = "0b4b48ab7870529a34028c6e30dfba42eddbf215"
    checkpoint = "human_1_RCNN_ECA_parallel_089-0.9802.pt"
    sha256 = "aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc"
    return LRECAResult(
        repository_commit=commit,
        checkpoint=checkpoint,
        checkpoint_sha256=sha256,
        metadata={
            "repository": "https://github.com/ai-phasepro/LRECA",
            "commit": commit,
            "checkpoint": checkpoint,
            "checkpoint_sha256": sha256,
            "checkpoint_size_bytes": 2395318,
        },
        sequence=sequence,
        sequence_length=len(sequence),
        raw_score=0.25,
        calibrated_score=0.25,
        logits=[math.log(3), 0.0],
        threshold=0.5,
        label="N",
        device="cpu",
        runtime_ms=0.0,
        warnings=["API boundary fixture; not a model prediction."],
    )


def test_application_loads_once_and_closes_once_for_repeated_requests():
    adapter = BoundaryStub()
    application = create_app(lreca_adapter=adapter)
    assert adapter.loads == 0
    with TestClient(application) as client:
        assert adapter.loads == 1
        assert client.get("/api/v1/health").json()["analysis_enabled"] is True
        health = client.get("/api/v1/methods/lreca/health")
        assert health.status_code == 200
        assert health.json()["loaded"] is True
        for _ in range(3):
            response = client.post(
                "/api/v1/methods/lreca/analyze",
                json={"sequence": "ACDE", "include_attribution": False},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["method"] == "lreca"
            assert data["attribution_status"] == "not_requested"
            assert all(
                data[field] is None
                for field in ("residue_attribution", "top_residues", "kde", "critical_regions")
            )
        assert adapter.loads == 1
        assert adapter.closes == 0
    assert adapter.closes == 1
    assert len(adapter.calls) == 3


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({}, (True, True)),
        ({"include_attribution": False}, (False, False)),
        ({"include_kde": False}, (True, False)),
        ({"include_attribution": False, "include_kde": True}, (False, False)),
    ],
)
def test_explanation_switches_and_fasta_normalization(flags, expected):
    adapter = BoundaryStub()
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        response = client.post(
            "/api/v1/methods/lreca/analyze",
            json={"sequence": "\n>protein name with X/B in header\n ac d\tE\n", **flags},
        )
        assert response.status_code == 200
        assert response.json()["sequence"] == "ACDE"
        assert adapter.calls == [("ACDE", *expected)]


@pytest.mark.parametrize(
    "sequence,code,position,residue",
    [
        (" \t\n", "EMPTY_SEQUENCE", None, None),
        (">protein\n\n", "EMPTY_SEQUENCE", None, None),
        ("A" * 135 + "x", "INVALID_AMINO_ACID", 136, "X"),
        ("ac b e", "INVALID_AMINO_ACID", 3, "B"),
        (">one\nAC\n>two\nDE", "MULTIPLE_FASTA_RECORDS", None, None),
        ("AC\n>one\nDE", "INVALID_FASTA", None, None),
        (">\nACDE", "INVALID_FASTA", None, None),
        ("AßC", "INVALID_AMINO_ACID", 2, "ß"),
    ],
)
def test_validation_errors_have_no_prediction_payload(sequence, code, position, residue):
    adapter = BoundaryStub()
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        response = client.post("/api/v1/methods/lreca/analyze", json={"sequence": sequence})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail.get("position") == position
    assert detail.get("residue") == residue
    assert "raw_score" not in response.json()
    assert adapter.calls == []


@pytest.mark.parametrize("residue", list("BJOUXZ"))
def test_ambiguous_or_nonstandard_amino_acids_are_never_replaced(residue):
    with pytest.raises(SequenceValidationError) as caught:
        normalize_sequence("AC" + residue + "DE")
    assert caught.value.detail["code"] == "INVALID_AMINO_ACID"
    assert caught.value.detail["position"] == 3
    assert caught.value.detail["residue"] == residue


@pytest.mark.parametrize("body", [{"sequence": 123}, {"sequence": "ACDE", "include_kde": "false"}])
def test_json_types_are_not_silently_coerced(body):
    adapter = BoundaryStub()
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        response = client.post("/api/v1/methods/lreca/analyze", json=body)
    assert response.status_code == 422
    assert adapter.calls == []


def test_startup_failure_keeps_liveness_and_returns_503_without_scores():
    adapter = BoundaryStub(load_error=LRECAUnavailableError("Missing audited checkpoint."))
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        liveness = client.get("/api/v1/health")
        assert liveness.status_code == 200
        assert liveness.json()["analysis_enabled"] is False
        assert client.get("/api/v1/methods/lreca/health").status_code == 503
        response = client.post("/api/v1/methods/lreca/analyze", json={"sequence": "ACDE"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "LRECA_UNAVAILABLE"
        assert "raw_score" not in response.json()
        assert adapter.loads == 1
    assert adapter.closes == 1


@pytest.mark.parametrize(
    "error,status,code",
    [
        (LRECAUnavailableError("Worker exited."), 503, "LRECA_UNAVAILABLE"),
        (LRECATimeoutError("Worker timed out."), 504, "LRECA_TIMEOUT"),
        (LRECAAnalysisError("Real analysis failed."), 500, "LRECA_ANALYSIS_FAILED"),
    ],
)
def test_runtime_failures_have_explicit_status_and_no_score_fallback(error, status, code):
    adapter = BoundaryStub(analyze_error=error)
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        response = client.post("/api/v1/methods/lreca/analyze", json={"sequence": "ACDE"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "raw_score" not in response.json()


def test_environment_aliases_and_named_settings_match_user_configuration(monkeypatch):
    monkeypatch.setenv("LRECA_DEVICE", "cpu")
    monkeypatch.setenv("LRECA_CLASSIFICATION_THRESHOLD", "0.6")
    monkeypatch.setenv("LRECA_TOP_RESIDUES", "7")
    monkeypatch.setenv("LRECA_KDE_PROMINENCE", "0.2")
    settings = Settings(_env_file=None)
    assert settings.lreca_device == "cpu"
    assert settings.lreca_classification_threshold == 0.6
    assert settings.lreca_top_residues == 7
    assert settings.lreca_kde_prominence == 0.2
    assert Settings(lreca_device="auto", _env_file=None).lreca_device == "auto"


@pytest.mark.parametrize(
    "options",
    [
        {"lreca_device": "cuda:0"},
        {"lreca_classification_threshold": float("nan")},
        {"lreca_top_residues": 0},
        {"lreca_worker_timeout_seconds": 0},
    ],
)
def test_invalid_runtime_configuration_is_rejected(options):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **options)


def test_interval_serialization_preserves_verified_inclusive_length():
    region = LRECACriticalRegion(start=65, end=293, score=0.4, is_primary=True)
    assert region.length == 229
    assert LRECACriticalRegion.model_validate(region.model_dump()) == region
    with pytest.raises(ValidationError):
        LRECACriticalRegion(start=65, end=293, length=228, score=0.4, is_primary=True)


def test_unavailable_kde_is_explicit_without_fake_density_values():
    kde = LRECAKDE(
        status="unavailable",
        values=None,
        regions=None,
        values_semantics="processed_density",
        prominence=0.1,
        reason="Official smoothing requires at least 50 residues.",
    )
    assert kde.values is None
    with pytest.raises(ValidationError):
        LRECAKDE.model_validate({**kde.model_dump(), "values": [0.0], "regions": []})


def test_result_rejects_conflicting_identity_or_fake_calibration():
    payload = boundary_result().model_dump()
    with pytest.raises(ValidationError):
        LRECAResult.model_validate({**payload, "checkpoint_sha256": "0" * 64})
    with pytest.raises(ValidationError):
        LRECAResult.model_validate({**payload, "calibrated_score": 0.5})


PUBLIC_METADATA_FIELDS = {
    "repository",
    "commit",
    "model_variant",
    "dataset5_mapping_status",
    "checkpoint",
    "checkpoint_sha256",
    "checkpoint_size_bytes",
}
PRIVATE_SERVER_PATHS = (
    r"C:\private-server\models\human.pt",
    "/srv/private-server/models/human.pt",
    str(Path(__file__).resolve()),
)


def response_strings(response):
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, str):
            yield value

    return "\n".join(walk(response.json()))


@pytest.mark.parametrize(
    "private_field", ["checkpoint_path", "configured_checkpoint_path", "source_files", "runtime"]
)
def test_public_metadata_rejects_any_private_field(private_field):
    metadata = boundary_result().metadata.model_dump()
    assert set(metadata) == PUBLIC_METADATA_FIELDS
    with pytest.raises(ValidationError):
        PublicLRECAModelMetadata.model_validate(
            {**metadata, private_field: PRIVATE_SERVER_PATHS[0]}
        )


@pytest.mark.parametrize(
    "checkpoint", [r"C:\models\human.pt", "/srv/models/human.pt", "models/human.pt", "C:human.pt"]
)
def test_public_checkpoint_is_a_filename_never_a_filesystem_path(checkpoint):
    metadata = boundary_result().metadata.model_dump()
    with pytest.raises(ValidationError):
        PublicLRECAModelMetadata.model_validate({**metadata, "checkpoint": checkpoint})


def test_public_repository_cannot_be_replaced_by_a_local_directory():
    metadata = boundary_result().metadata.model_dump()
    with pytest.raises(ValidationError):
        PublicLRECAModelMetadata.model_validate({**metadata, "repository": "/srv/LRECA"})


def test_openapi_exposes_only_the_public_metadata_allowlist():
    with TestClient(create_app(lreca_adapter=BoundaryStub())) as client:
        specification = client.get("/openapi.json")
        assert specification.status_code == 200
        schemas = specification.json()["components"]["schemas"]
        assert "LRECAModelMetadata" not in schemas
        assert set(schemas["PublicLRECAModelMetadata"]["properties"]) == PUBLIC_METADATA_FIELDS
        for private_field in ("checkpoint_path", "configured_checkpoint_path", "source_files"):
            assert private_field not in specification.text
        assert all(path not in response_strings(specification) for path in PRIVATE_SERVER_PATHS)


@pytest.mark.parametrize(
    "error_type,status,code",
    [
        (LRECAUnavailableError, 503, "LRECA_UNAVAILABLE"),
        (LRECATimeoutError, 504, "LRECA_TIMEOUT"),
        (LRECAAnalysisError, 500, "LRECA_ANALYSIS_FAILED"),
    ],
)
def test_http_failure_messages_are_safe_while_internal_paths_remain_in_logs(
    error_type, status, code, caplog
):
    internal_message = "Private worker detail: " + " | ".join(PRIVATE_SERVER_PATHS)
    adapter = BoundaryStub(analyze_error=error_type(internal_message))
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        response = client.post("/api/v1/methods/lreca/analyze", json={"sequence": "ACDE"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "Private worker detail" not in response.text
    assert "Traceback" not in response.text
    assert all(path not in response_strings(response) for path in PRIVATE_SERVER_PATHS)
    assert all(path in caplog.text for path in PRIVATE_SERVER_PATHS)


@pytest.mark.parametrize("raises", [False, True])
def test_health_never_echoes_an_internal_adapter_message(raises, caplog):
    internal_message = "Private readiness detail: " + " | ".join(PRIVATE_SERVER_PATHS)

    class PrivateHealthStub(BoundaryStub):
        async def healthcheck(self):
            if raises:
                raise LRECAUnavailableError(internal_message)
            return LRECAHealth(status="unavailable", message=internal_message)

    with TestClient(create_app(lreca_adapter=PrivateHealthStub())) as client:
        response = client.get("/api/v1/methods/lreca/health")
        assert client.get("/api/v1/health").status_code == 200
    assert response.status_code == 503
    assert "Private readiness detail" not in response.text
    assert all(path not in response_strings(response) for path in PRIVATE_SERVER_PATHS)
    if raises:
        assert all(path in caplog.text for path in PRIVATE_SERVER_PATHS)


@pytest.mark.parametrize("device", ["cpu", "cuda", "cuda:0", "cuda:3"])
def test_public_device_name_accepts_cpu_and_cuda_without_fixing_a_gpu_index(device):
    health = LRECAHealth(status="ready", message="Ready.", loaded=True, device=device)
    result = LRECAResult.model_validate({**boundary_result().model_dump(), "device": device})
    assert health.device == result.device == device


@pytest.mark.parametrize(
    "device",
    [
        r"C:\private-server\models\human.pt",
        "/srv/private-server/model.pt",
        r"..\private-server\model.pt",
        "cuda:not-an-index",
    ],
)
def test_public_device_name_rejects_internal_paths_and_invalid_values(device):
    with pytest.raises(ValidationError):
        LRECAHealth(status="ready", message="Ready.", loaded=True, device=device)
    with pytest.raises(ValidationError):
        LRECAResult.model_validate({**boundary_result().model_dump(), "device": device})
