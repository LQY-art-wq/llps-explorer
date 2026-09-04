"""HTTP job contracts and privacy; services and native methods are lightweight fixtures."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.analysis import SERVICE_ERRORS, router
from app.core.config import Settings
from app.schemas.orchestration import AnalysisJob, AnalysisRequest, MethodExecution
from app.services.analysis_jobs import AnalysisServiceError


def queued_job(payload):
    now = datetime.now(timezone.utc)
    modes = {
        "lreca": "local_automatic",
        "seg": "local_automatic",
        "fuzdrop": "manual_import",
        "dismeta": "integration_blocked",
    }
    return AnalysisJob(
        job_id="job_test",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        status="queued",
        sequence={
            "name": payload.sequence_name,
            "length": len(payload.sequence),
            "sha256": hashlib.sha256(payload.sequence.encode("ascii")).hexdigest(),
        },
        selected_methods=payload.selected_methods,
        prediction_mode=payload.prediction_mode,
        weights=payload.weights,
        methods={
            method: MethodExecution(method=method, status="queued", integration_mode=modes[method])
            for method in payload.selected_methods
        },
    )


class ServiceSpy:
    def __init__(self):
        self.payloads = []
        self.get_ids = []
        self.job = None

    async def submit(self, payload):
        self.payloads.append(payload)
        self.job = queued_job(payload)
        return self.job

    def get(self, job_id):
        self.get_ids.append(job_id)
        return self.job


def client_for(service):
    app = FastAPI()
    app.state.analysis_service = service
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_submit_returns_202_job_and_get_uses_the_service_snapshot():
    service = ServiceSpy()
    with client_for(service) as client:
        response = client.post(
            "/api/v1/analysis", json={"sequence": ">example\nac de fg", "selected_methods": ["seg"]}
        )
        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == "job_test"
        assert body["status"] == "queued"
        assert body["sequence"]["length"] == 6
        assert "ACDEFG" not in response.text
        assert service.payloads[0].sequence == "ACDEFG"
        assert isinstance(service.payloads[0], AnalysisRequest)
        fetched = client.get("/api/v1/analysis/job_test")
        assert fetched.status_code == 200
        assert fetched.json() == body
        assert service.get_ids == ["job_test"]


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"selected_methods": []}, "EMPTY_SELECTED_METHODS"),
        ({"selected_methods": ["unknown"]}, "UNKNOWN_METHOD"),
        ({"selected_methods": ["seg", "seg"]}, "DUPLICATE_SELECTED_METHODS"),
        ({"sequence": ""}, "EMPTY_SEQUENCE"),
        ({"sequence": "ACDX"}, "INVALID_AMINO_ACID"),
        ({"sequence": 123}, "INVALID_SEQUENCE_TYPE"),
        ({"prediction_mode": "weighted"}, "WEIGHTED_MODE_REQUIRES_LRECA_AND_FUZDROP"),
        ({"weights": {"seg": 1}}, "INVALID_ENSEMBLE_METHOD"),
        ({"weights": {"lreca": 0.2, "fuzdrop": 0.2}}, "INVALID_ENSEMBLE_WEIGHTS"),
        ({"external_results": {"dismeta": {"result_id": "x"}}}, "INVALID_EXTERNAL_RESULT_METHOD"),
        (
            {"external_results": {"fuzdrop": {"result_id": "x"}}},
            "EXTERNAL_RESULT_METHOD_NOT_SELECTED",
        ),
        ({"sequence_name": "bad\nname"}, "INVALID_SEQUENCE_NAME"),
        ({"unexpected_field": "private"}, "INVALID_ANALYSIS_REQUEST"),
    ],
)
def test_validation_preserves_safe_custom_codes_without_admitting_a_job(updates, code):
    service = ServiceSpy()
    with client_for(service) as client:
        response = client.post(
            "/api/v1/analysis", json={"sequence": "ACDEFG", "selected_methods": ["seg"], **updates}
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert set(response.json()["detail"]) == {"code", "message"}
    assert service.payloads == []


def test_validation_never_echoes_body_ctx_or_private_input(caplog):
    private = str(Path.cwd() / "private-analysis-request" / "source.fasta")
    with client_for(ServiceSpy()) as client:
        response = client.post(
            "/api/v1/analysis",
            json={"sequence": "ACDEFG", "selected_methods": ["seg"], "unexpected": private},
        )
    assert response.status_code == 422
    assert "private-analysis-request" not in response.text + caplog.text
    assert "ACDEFG" not in response.text + caplog.text
    assert not {"input", "ctx", "body"} & response.json()["detail"].keys()


@pytest.mark.parametrize("operation", ["submit", "get"])
@pytest.mark.parametrize("code", list(SERVICE_ERRORS))
def test_known_service_errors_keep_safe_status_and_message(operation, code, caplog):
    private = str(Path.cwd() / "private-analysis-service" / "input-sequence.txt")

    class FailingService:
        async def submit(self, payload):
            raise AnalysisServiceError(code, private, 200)

        def get(self, job_id):
            raise AnalysisServiceError(code, private, 200)

    with client_for(FailingService()) as client:
        response = (
            client.post(
                "/api/v1/analysis", json={"sequence": "ACDEFG", "selected_methods": ["seg"]}
            )
            if operation == "submit"
            else client.get("/api/v1/analysis/job_test")
        )
    assert response.status_code == SERVICE_ERRORS[code][0]
    assert response.json()["detail"] == {"code": code, "message": SERVICE_ERRORS[code][1]}
    assert "private-analysis-service" not in response.text + caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize("service_kind", ["absent", "exception", "invalid_snapshot"])
def test_missing_or_broken_service_returns_safe_unavailable(service_kind, caplog):
    private = str(Path.cwd() / "private-analysis-broken" / "input.txt")

    class BrokenService:
        async def submit(self, payload):
            if service_kind == "exception":
                raise RuntimeError(private)
            return queued_job(payload).model_copy(update={"job_id": private})

    with client_for(None if service_kind == "absent" else BrokenService()) as client:
        response = client.post(
            "/api/v1/analysis", json={"sequence": "ACDEFG", "selected_methods": ["seg"]}
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ANALYSIS_UNAVAILABLE"
    assert "private-analysis-broken" not in response.text + caplog.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"ensemble_threshold": -0.1},
        {"ensemble_threshold": float("nan")},
        {"analysis_method_timeout_seconds": 0},
        {"analysis_method_timeout_seconds": 3601},
        {"analysis_job_timeout_seconds": float("inf")},
        {"analysis_job_ttl_seconds": 86401},
        {"analysis_job_ttl_seconds": 1e-7},
        {"analysis_max_jobs": 0},
        {"analysis_max_concurrent_jobs": 129},
        {"analysis_max_sequence_length": 0},
        {"analysis_max_sequence_length": 1000001},
        {"analysis_max_jobs": 1, "analysis_max_concurrent_jobs": 2},
        {"external_result_ttl_seconds": 0},
        {"external_result_ttl_seconds": 1e-7},
        {"external_result_max_entries": 10001},
    ],
)
def test_operational_limits_are_finite_positive_and_bounded(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_operational_environment_aliases_are_explicit(monkeypatch):
    monkeypatch.setenv("ENSEMBLE_THRESHOLD", "0.6")
    monkeypatch.setenv("ANALYSIS_METHOD_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("ANALYSIS_JOB_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("ANALYSIS_JOB_TTL_SECONDS", "600")
    monkeypatch.setenv("ANALYSIS_MAX_JOBS", "64")
    monkeypatch.setenv("ANALYSIS_MAX_CONCURRENT_JOBS", "2")
    monkeypatch.setenv("ANALYSIS_MAX_SEQUENCE_LENGTH", "50000")
    monkeypatch.setenv("EXTERNAL_RESULT_TTL_SECONDS", "120")
    monkeypatch.setenv("EXTERNAL_RESULT_MAX_ENTRIES", "32")
    settings = Settings(_env_file=None)
    assert settings.ensemble_threshold == 0.6
    assert settings.analysis_method_timeout_seconds == 20
    assert settings.analysis_job_timeout_seconds == 30
    assert settings.analysis_job_ttl_seconds == 600
    assert settings.analysis_max_jobs == 64
    assert settings.analysis_max_concurrent_jobs == 2
    assert settings.analysis_max_sequence_length == 50000
    assert settings.external_result_ttl_seconds == 120
    assert settings.external_result_max_entries == 32
