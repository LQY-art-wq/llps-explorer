"""SEG API boundary tests use explicit stubs, never scientific predictions."""

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as app_main
from app.adapters.fuzdrop_remote import FuzDropRemoteAdapter
from app.core.config import Settings
from app.main import create_app
from app.schemas.lreca import LRECAHealth
from app.schemas.seg import SEGError, SEGHealth, SEGResult
from app.services.seg_process import parse_seg_version


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("sync")
        raise AssertionError("SEG API tests must not contact external services")

    async def deny_async(*args, **kwargs):
        attempts.append("async")
        raise AssertionError("SEG API tests must not contact external services")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_async)
    yield
    assert attempts == []


class LRECAStub:
    def __init__(self, *, ready=True):
        self.ready = ready
        self.loads = self.closes = 0

    async def load(self):
        self.loads += 1

    async def close(self):
        self.closes += 1

    async def healthcheck(self):
        return LRECAHealth(
            status="ready" if self.ready else "unavailable",
            loaded=self.ready,
            device="cpu" if self.ready else None,
            message="Test fixture only.",
        )


PROVENANCE = {
    "version": "2.17.0",
    "application_version": "1.0.0",
    "executable_sha256": "0" * 64,
    "parameters": {"window": 12, "locut": 2.2, "hicut": 2.5},
}


class SEGStub:
    def __init__(self, *, regions=None):
        self.regions = [{"start": 2, "end": 4}] if regions is None else regions
        self.loads = self.closes = 0
        self.received = []

    async def load(self):
        self.loads += 1

    async def close(self):
        self.closes += 1

    async def healthcheck(self):
        return SEGHealth(
            status="ready", available=True, reason=None, message="Test only.", **PROVENANCE
        )

    async def analyze(self, sequence):
        self.received.append(sequence)
        return SEGResult(
            sequence_length=len(sequence),
            sequence_sha256=hashlib.sha256(sequence.encode("ascii")).hexdigest(),
            regions=self.regions,
            runtime_ms=1.5,
            **PROVENANCE,
        )


def application(*, seg=None, lreca=None):
    return create_app(
        Settings(_env_file=None, database_url="sqlite://"),
        lreca_adapter=lreca if lreca is not None else LRECAStub(),
        seg_adapter=seg if seg is not None else SEGStub(),
    )


def test_annotation_api_normalizes_sequence_and_only_reports_lcr_fields():
    seg, lreca = SEGStub(), LRECAStub()
    with TestClient(application(seg=seg, lreca=lreca)) as client:
        response = client.post(
            "/api/v1/methods/seg/analyze", json={"sequence": "\n>one protein\n ac d e f g\n"}
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["method"] == "seg"
        assert result["annotation_type"] == "LCR"
        assert result["semantic_type"] == "region_annotation"
        assert result["implementation"] == "NCBI segmasker"
        assert result["regions"] == [
            {"start": 2, "end": 4, "length": 3, "semantic_type": "region_annotation"}
        ]
        assert result["coverage"] == 0.5
        assert result["region_count"] == 1
        assert result["longest_region"] == 3
        assert result["parameters"]["window"] == 12
        assert result["runtime_ms"] == 1.5
        for field in ("raw_score", "calibrated_score", "global_score", "label", "threshold"):
            assert field not in result
        assert seg.received == ["ACDEFG"]
        assert seg.loads == lreca.loads == 1
    assert seg.closes == lreca.closes == 1


def test_no_lcr_is_success_with_empty_regions_and_zero_summaries():
    with TestClient(application(seg=SEGStub(regions=[]))) as client:
        response = client.post("/api/v1/methods/seg/analyze", json={"sequence": "ACDEFG"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["regions"] == []
    assert result["coverage"] == result["region_count"] == result["longest_region"] == 0


def test_methods_reports_seg_readiness_and_does_not_change_lreca_liveness_semantics():
    with TestClient(application(lreca=LRECAStub(ready=False))) as client:
        seg_health = client.get("/api/v1/methods/seg/health")
        assert seg_health.status_code == 200
        assert seg_health.json()["available"] is True
        listing = client.get("/api/v1/methods")
        assert listing.status_code == 200
        methods = {item["id"]: item for item in listing.json()["methods"]}
        assert methods["seg"]["name"] == "SEG"
        assert methods["seg"]["display_name"] == "Low-complexity Regions (LCR)"
        assert methods["seg"]["category"] == "annotation"
        assert methods["seg"]["available"] is True
        assert methods["seg"]["capabilities"] == ["regions"]
        assert methods["seg"]["semantic_types"] == ["region_annotation"]
        assert methods["seg"]["integration_mode"] == "local_automatic"
        assert methods["lreca"]["available"] is False
        assert methods["fuzdrop"]["available"] is True
        assert methods["fuzdrop"]["manual_import_available"] is True
        assert methods["dismeta"]["reason"] == "integration_contract_unverified"
        assert client.get("/api/v1/health").json()["analysis_enabled"] is False


@pytest.mark.parametrize(
    "sequence,code,position",
    [
        ("", "EMPTY_SEQUENCE", None),
        (" \n\t", "EMPTY_SEQUENCE", None),
        (">one\nACD\n>two\nEFG", "MULTIPLE_FASTA_RECORDS", None),
        ("AC\n>later\nDE", "INVALID_FASTA", None),
        ("ac xde", "INVALID_AMINO_ACID", 3),
        ("ACDE; echo secret", "INVALID_AMINO_ACID", 5),
    ],
)
def test_invalid_sequences_fail_before_the_adapter(sequence, code, position):
    seg = SEGStub()
    with TestClient(application(seg=seg)) as client:
        response = client.post("/api/v1/methods/seg/analyze", json={"sequence": sequence})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    if position is not None:
        assert response.json()["detail"]["position"] == position
    assert seg.received == []


@pytest.mark.parametrize("body", [{}, {"sequence": 12}, {"sequence": "ACDE", "window": 6}])
def test_request_fields_are_strict_and_only_allow_sequence(body):
    with TestClient(application()) as client:
        response = client.post("/api/v1/methods/seg/analyze", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SEG_INVALID_REQUEST"


def test_request_validation_does_not_echo_private_input(caplog):
    private_input = str(Path.cwd() / "private-api-test" / "private-sequence.fasta")
    body = {"sequence": "ACDEFG", "unexpected_private": private_input}
    with TestClient(application()) as client:
        response = client.post("/api/v1/methods/seg/analyze", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SEG_INVALID_REQUEST"
    assert "private-api-test" not in response.text
    assert "private-api-test" not in caplog.text
    assert "input" not in response.json()["detail"]


@pytest.mark.parametrize(
    "code,status",
    [
        ("SEG_EXECUTABLE_NOT_FOUND", 503),
        ("SEG_UNAVAILABLE", 503),
        ("SEG_TIMEOUT", 504),
        ("SEG_EXECUTION_FAILED", 502),
        ("SEG_PARSE_ERROR", 502),
        ("SEG_INVALID_OUTPUT", 502),
    ],
)
def test_adapter_failures_have_safe_structured_envelopes_and_no_private_logs(code, status, caplog):
    private_detail = str(Path.cwd() / "private-seg-diagnostic" / "raw-sequence-output.txt")

    class FailingSEG(SEGStub):
        async def analyze(self, sequence):
            raise SEGError(code, private_detail, status_code=status)

    with TestClient(application(seg=FailingSEG())) as client:
        response = client.post("/api/v1/methods/seg/analyze", json={"sequence": "ACDEFG"})
    assert response.status_code == status
    result = response.json()
    assert result["status"] == ("unavailable" if status == 503 else "failed")
    assert result["error"]["code"] == code
    assert result["regions"] is result["coverage"] is result["longest_region"] is None
    assert "private-seg-diagnostic" not in response.text
    assert "private-seg-diagnostic" not in caplog.text
    assert "Traceback" not in caplog.text
    assert code in caplog.text


@pytest.mark.parametrize("phase", ["startup", "analyze"])
def test_unsupported_executable_version_remains_unavailable_in_analysis_response(phase):
    unsupported_version = b"segmasker: 1.0.0\nPackage: blast 2.16.0, build test\n"

    class UnsupportedVersionSEG(SEGStub):
        async def load(self):
            await super().load()
            if phase == "startup":
                parse_seg_version(unsupported_version)

        async def analyze(self, sequence):
            parse_seg_version(unsupported_version)

    seg = UnsupportedVersionSEG()
    with TestClient(application(seg=seg)) as client:
        response = client.post("/api/v1/methods/seg/analyze", json={"sequence": "ACDEFG"})
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
        assert response.json()["error"]["code"] == "SEG_INVALID_OUTPUT"
        if phase == "startup":
            health = client.get("/api/v1/methods/seg/health")
            assert health.status_code == 503
            assert health.json()["reason"] == "SEG_INVALID_OUTPUT"
            assert health.json()["available"] is False
        assert client.get("/api/v1/health").json()["analysis_enabled"] is True
    assert seg.loads == seg.closes == 1


@pytest.mark.parametrize(
    "code,requested_status,expected_status",
    [
        ("SEG_INVALID_OUTPUT", 200, 502),
        ("SEG_INVALID_OUTPUT", 301, 502),
        ("SEG_INVALID_OUTPUT", 504, 502),
        ("SEG_PARSE_ERROR", 503, 502),
        ("SEG_TIMEOUT", 503, 504),
        ("SEG_EXECUTION_FAILED", 200, 502),
    ],
)
def test_adapter_status_cannot_override_the_allowed_error_combinations(
    code, requested_status, expected_status
):
    class UnexpectedStatusSEG(SEGStub):
        async def analyze(self, sequence):
            raise SEGError(code, "Test only.", status_code=requested_status)

    with TestClient(application(seg=UnexpectedStatusSEG())) as client:
        response = client.post("/api/v1/methods/seg/analyze", json={"sequence": "ACDEFG"})
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == code
    assert response.json()["status"] == "failed"


def test_seg_constructor_failure_preserves_other_startup_and_shutdown(monkeypatch, caplog):
    settings, lreca = Settings(_env_file=None), LRECAStub()
    private_detail = str(Path.cwd() / "private-seg-constructor" / "runtime-config.json")

    class CountedFuzDrop(FuzDropRemoteAdapter):
        def __init__(self):
            super().__init__(settings)
            self.loads = self.closes = 0

        async def load(self):
            self.loads += 1
            await super().load()

        async def close(self):
            self.closes += 1
            await super().close()

    def fail_constructor(*args, **kwargs):
        raise RuntimeError(private_detail)

    monkeypatch.setattr(app_main, "SEGAdapter", fail_constructor)
    fuzdrop = CountedFuzDrop()
    with TestClient(create_app(settings, lreca_adapter=lreca, fuzdrop_adapter=fuzdrop)) as client:
        health = client.get("/api/v1/methods/seg/health")
        assert health.status_code == 503
        assert health.json()["available"] is False
        methods = client.get("/api/v1/methods")
        assert methods.status_code == 200
        listing = {item["id"]: item for item in methods.json()["methods"]}
        assert listing["lreca"]["available"] is True
        assert listing["fuzdrop"]["manual_import_available"] is True
        assert listing["seg"]["available"] is False
        assert client.get("/api/v1/health").json()["analysis_enabled"] is True
        assert lreca.loads == fuzdrop.loads == 1
        assert "private-seg-constructor" not in health.text + methods.text
    assert lreca.closes == fuzdrop.closes == 1
    assert "private-seg-constructor" not in caplog.text
    assert "SEG shutdown failed" not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize("phase", ["load", "health", "analyze", "close"])
def test_seg_failure_isolation_preserves_other_methods_and_cleanup(phase, caplog):
    private_detail = str(Path.cwd() / "private-seg-diagnostic" / "secret-output.txt")

    class FailingSEG(SEGStub):
        async def load(self):
            await super().load()
            if phase == "load":
                raise SEGError("SEG_EXECUTABLE_NOT_FOUND", private_detail, status_code=503)

        async def healthcheck(self):
            if phase == "health":
                raise RuntimeError(private_detail)
            return await super().healthcheck()

        async def analyze(self, sequence):
            if phase == "analyze":
                raise RuntimeError(private_detail)
            return await super().analyze(sequence)

        async def close(self):
            await super().close()
            if phase == "close":
                raise RuntimeError(private_detail)

    seg, lreca = FailingSEG(), LRECAStub()
    with TestClient(application(seg=seg, lreca=lreca)) as client:
        health = client.get("/api/v1/methods/seg/health")
        analysis = client.post("/api/v1/methods/seg/analyze", json={"sequence": "ACDEFG"})
        if phase in {"load", "health"}:
            assert health.status_code == 503
        if phase == "load":
            assert analysis.status_code == 503
            assert analysis.json()["error"]["code"] == "SEG_EXECUTABLE_NOT_FOUND"
        if phase == "analyze":
            assert analysis.status_code == 502
            assert analysis.json()["error"]["code"] == "SEG_EXECUTION_FAILED"
        methods = client.get("/api/v1/methods")
        assert methods.status_code == 200
        listing = {item["id"]: item for item in methods.json()["methods"]}
        assert listing["lreca"]["available"] is True
        assert listing["fuzdrop"]["manual_import_available"] is True
        imported = client.post(
            "/api/v1/methods/fuzdrop/import",
            json={
                "sequence": "ACDEFG",
                "source_declaration": "official_fuzdrop_export",
                "coordinate_system": "one_based_inclusive",
                "pLLPS": 0.2,
            },
        )
        assert imported.status_code == 200
        assert client.get("/api/v1/health").json()["analysis_enabled"] is True
        assert seg.loads == lreca.loads == 1
        for response in (health, analysis, methods):
            assert "private-seg-diagnostic" not in response.text
    assert seg.closes == lreca.closes == 1
    assert "private-seg-diagnostic" not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize("field", ["message", "reason", "version", "application_version"])
def test_health_filters_adapter_diagnostics_and_revalidates_provenance(field, caplog):
    private_detail = str(Path.cwd() / "private-health-diagnostic" / "segmasker")

    class UnsafeHealthSEG(SEGStub):
        async def healthcheck(self):
            return (await super().healthcheck()).model_copy(update={field: private_detail})

    with TestClient(application(seg=UnsafeHealthSEG())) as client:
        response = client.get("/api/v1/methods/seg/health")
        methods = client.get("/api/v1/methods")
    assert response.status_code == (200 if field == "message" else 503)
    assert "private-health-diagnostic" not in response.text
    assert "private-health-diagnostic" not in methods.text
    assert "private-health-diagnostic" not in caplog.text


def test_openapi_seg_contract_has_no_server_path_or_classifier_fields():
    with TestClient(application()) as client:
        document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    for name in ("SEGResult", "SEGHealth", "SEGUnavailableResult"):
        properties = schemas[name]["properties"]
        assert not {"executable_path", "raw_output", "raw_score", "label", "global_score"} & set(
            properties
        )
    assert set(schemas["SEGAnalyzeRequest"]["properties"]) == {"sequence"}


def test_seg_configuration_defaults_and_environment_overrides(monkeypatch):
    for name in (
        "SEG_EXECUTABLE_PATH",
        "SEG_WINDOW",
        "SEG_LOCUT",
        "SEG_HICUT",
        "SEG_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.seg_executable_path == Path("segmasker")
    assert (defaults.seg_window, defaults.seg_locut, defaults.seg_hicut) == (12, 2.2, 2.5)
    assert defaults.seg_timeout_seconds == 10
    assert Settings(_env_file=None, seg_window=2147483647).seg_window == 2147483647
    executable = Path.cwd() / "configured-executable" / "segmasker"
    monkeypatch.setenv("SEG_EXECUTABLE_PATH", str(executable))
    monkeypatch.setenv("SEG_WINDOW", "15")
    monkeypatch.setenv("SEG_LOCUT", "1.8")
    monkeypatch.setenv("SEG_HICUT", "2.4")
    monkeypatch.setenv("SEG_TIMEOUT_SECONDS", "3.5")
    configured = Settings(_env_file=None)
    assert configured.seg_executable_path == executable
    assert (configured.seg_window, configured.seg_locut, configured.seg_hicut) == (15, 1.8, 2.4)
    assert configured.seg_timeout_seconds == 3.5


@pytest.mark.parametrize(
    "overrides",
    [
        {"seg_window": 0},
        {"seg_window": -1},
        {"seg_window": 1.5},
        {"seg_window": 2147483648},
        {"seg_locut": -0.1},
        {"seg_hicut": -0.1},
        {"seg_locut": 3, "seg_hicut": 2},
        {"seg_locut": float("nan")},
        {"seg_hicut": float("inf")},
        {"seg_timeout_seconds": 0},
        {"seg_timeout_seconds": float("inf")},
    ],
)
def test_invalid_seg_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)
