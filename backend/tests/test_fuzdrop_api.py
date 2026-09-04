"""MODE C API boundaries; synthetic parser inputs never authenticate an official result."""

import asyncio
import copy
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.fuzdrop as fuzdrop_api
from app.adapters.fuzdrop_remote import FuzDropRemoteAdapter
from app.core.config import Settings
from app.main import create_app
from app.schemas.analysis import AnalysisStatus
from app.schemas.lreca import LRECAHealth


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    """Deny network transports while allowing TestClient's in-memory ASGI transport."""
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("sync")
        raise AssertionError("FuzDrop unit tests must never contact an external service")

    async def deny_async(*args, **kwargs):
        attempts.append("async")
        raise AssertionError("FuzDrop unit tests must never contact an external service")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_async)
    yield
    assert attempts == []


class LocalLRECAStub:
    """Track application lifecycle without loading or changing the scientific model."""

    def __init__(self, *, ready=True):
        self.ready = ready
        self.loads = self.closes = 0
        self.loop_thread = None

    async def load(self):
        self.loads += 1

    async def close(self):
        self.closes += 1

    async def healthcheck(self):
        self.loop_thread = threading.get_ident()
        return LRECAHealth(
            status="ready" if self.ready else "unavailable",
            loaded=self.ready,
            device="cpu" if self.ready else None,
            message="Local API test fixture.",
        )


IMPORT_BODY = {
    "sequence": ">api_fixture\nacde",
    "source_declaration": "official_fuzdrop_export",
    "coordinate_system": "one_based_inclusive",
    "pLLPS": 0.65,
    "scores_tsv": (
        "position\tresidue\tpDP\tSbind\n"
        "1\tA\t0.3\t0.2\n2\tC\t0.5\t1.5\n3\tD\t0.9\t0.4\n4\tE\tundefined\t\n"
    ),
    "regions_tsv": (
        "type\tstart\tend\nDroplet-promoting region\t2\t4\nAggregation hot-spot\t3\t3\n"
    ),
}


def application(*, stub=None, **settings):
    settings.setdefault("database_url", "sqlite://")
    return create_app(Settings(_env_file=None, **settings), lreca_adapter=stub or LocalLRECAStub())


def test_mode_c_adapter_is_structurally_unavailable_without_any_remote_access():
    async def exercise():
        adapter = FuzDropRemoteAdapter(Settings(_env_file=None))
        for _ in range(2):
            await adapter.load()
            assert adapter.status == AnalysisStatus.UNAVAILABLE
        health = await adapter.healthcheck()
        result = await adapter.analyze("\n>one protein\n ac d e\n")
        assert health.available is False
        assert health.integration_mode == result.integration_mode == "browser_protected"
        assert health.reason == "official_service_requires_browser_verification"
        assert result.error.code == "FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE"
        assert result.status == "unavailable"
        assert result.raw_score is result.calibrated_score is result.residue_propensity is None
        await adapter.close()

    asyncio.run(exercise())


def test_api_health_analyze_and_catalog_distinguish_automatic_and_manual_availability():
    lreca = LocalLRECAStub()
    with TestClient(application(stub=lreca)) as client:
        assert lreca.loads == 1
        for _ in range(2):
            health = client.get("/api/v1/methods/fuzdrop/health")
            assert health.status_code == 503
            assert health.json()["available"] is False
            assert health.json()["manual_import_available"] is True
            response = client.post("/api/v1/methods/fuzdrop/analyze", json={"sequence": "ACDE"})
            assert response.status_code == 503
            result = response.json()
            assert result["method"] == "fuzdrop"
            assert result["error"]["code"] == "FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE"
            assert result["reason"] == "official_service_requires_browser_verification"
            assert result["raw_score"] is result["residue_propensity"] is result["regions"] is None
            listing = client.get("/api/v1/methods")
            assert listing.status_code == 200
            methods = {item["id"]: item for item in listing.json()["methods"]}
            assert set(methods) == {"lreca", "fuzdrop", "seg", "dismeta"}
            assert methods["lreca"]["available"] is True
            assert methods["fuzdrop"]["available"] is True
            assert methods["fuzdrop"]["manual_import_available"] is True
            assert methods["fuzdrop"]["capabilities"] == [
                "global_score",
                "residue_propensity",
                "regions",
            ]
            assert methods["seg"]["category"] == methods["dismeta"]["category"] == "annotation"
            assert methods["seg"]["available"] is methods["dismeta"]["available"] is False
            assert client.get("/api/v1/health").json()["analysis_enabled"] is True
        assert lreca.loads == 1
        assert lreca.closes == 0
    assert lreca.closes == 1


def test_methods_remains_available_if_local_lreca_model_is_unavailable():
    with TestClient(application(stub=LocalLRECAStub(ready=False))) as client:
        response = client.get("/api/v1/methods")
        assert response.status_code == 200
        assert not any(
            method["automatic_analysis_available"] for method in response.json()["methods"]
        )
        assert client.get("/api/v1/health").json()["analysis_enabled"] is False


def test_valid_import_normalizes_only_supplied_official_fields_and_preserves_provenance():
    with TestClient(application()) as client:
        response = client.post("/api/v1/methods/fuzdrop/import", json=IMPORT_BODY)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["sequence"] == "ACDE"
        assert result["raw_score"] == result["calibrated_score"] == 0.65
        assert result["threshold"] == 0.6 and result["label"] == "P"
        assert result["source"] == "manual_import_of_official_result"
        assert result["origin_verification"] == "user_declared_not_independently_verified"
        assert result["coordinate_verification"] == "user_declared_not_independently_verified"
        assert result["retrieved_at"] is None
        assert result["imported_at"] is not None
        assert result["runtime_scope"] == "local_import_parsing"
        assert result["residue_propensity"][0]["score"] == 0.3
        assert result["residue_propensity"][0]["score_name"] == "pDP"
        assert result["residue_propensity"][0]["semantic_type"] == "residue_propensity"
        assert result["residue_propensity"][3]["score"] is None
        assert result["regions"][0]["type"] == "droplet_promoting_region"
        assert result["regions"][0]["official_type"] == "Droplet-promoting region"
        assert result["regions"][0]["length"] == 3
        assert result["regions"][1]["type"] == "aggregation_hotspot"
        assert result["regions"][1]["length"] == 1
        assert client.get("/api/v1/methods/fuzdrop/health").json()["available"] is False


def test_residue_only_import_does_not_invent_global_score_or_regions():
    body = copy.deepcopy(IMPORT_BODY)
    body.pop("pLLPS")
    body.pop("regions_tsv")
    with TestClient(application()) as client:
        response = client.post("/api/v1/methods/fuzdrop/import", json=body)
    assert response.status_code == 200
    result = response.json()
    assert all(
        result[field] is None
        for field in ("raw_score", "calibrated_score", "label", "threshold", "regions")
    )
    assert len(result["residue_propensity"]) == 4


def test_disabled_import_is_advertised_and_rejected_without_affecting_lreca():
    with TestClient(application(fuzdrop_manual_import_enabled=False)) as client:
        health = client.get("/api/v1/methods/fuzdrop/health").json()
        assert health["manual_import_available"] is False
        assert "can be imported" not in health["message"]
        methods = {item["id"]: item for item in client.get("/api/v1/methods").json()["methods"]}
        assert methods["fuzdrop"]["manual_import_available"] is False
        assert "can be imported" not in methods["fuzdrop"]["message"]
        assert methods["lreca"]["available"] is True
        analysis = client.post("/api/v1/methods/fuzdrop/analyze", json={"sequence": "ACDE"})
        assert analysis.status_code == 503
        assert analysis.json()["manual_import_available"] is False
        assert "can be imported" not in analysis.json()["message"]
        assert "can be imported" not in analysis.json()["error"]["message"]
        response = client.post("/api/v1/methods/fuzdrop/import", json=IMPORT_BODY)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "FUZDROP_MANUAL_IMPORT_DISABLED"


def test_import_runs_in_a_worker_thread_and_does_not_reuse_the_lreca_event_loop(monkeypatch):
    lreca = LocalLRECAStub()
    parser_threads = []
    original_parser = fuzdrop_api.import_fuzdrop_result

    def record_parser_thread(*args, **kwargs):
        parser_threads.append(threading.get_ident())
        return original_parser(*args, **kwargs)

    monkeypatch.setattr(fuzdrop_api, "import_fuzdrop_result", record_parser_thread)
    with TestClient(application(stub=lreca)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.post("/api/v1/methods/fuzdrop/import", json=IMPORT_BODY).status_code == 200
    assert len(parser_threads) == 1
    assert parser_threads[0] != lreca.loop_thread
    assert lreca.loads == lreca.closes == 1


@pytest.mark.parametrize(
    "field,value,code",
    [
        (
            "scores_tsv",
            "position\tresidue\tpDP\tSbind\n1\tA\t1.2\t0\n",
            "FUZDROP_RESIDUE_COUNT_MISMATCH",
        ),
        (
            "regions_tsv",
            "type\tstart\tend\nDroplet-promoting region\t0\t4\n",
            "FUZDROP_INVALID_COORDINATE",
        ),
        ("scores_tsv", "not\tthe\tofficial\tcolumns\n", "FUZDROP_SCHEMA_CHANGED"),
    ],
)
def test_import_parser_errors_have_stable_422_codes(field, value, code):
    body = {**IMPORT_BODY, field: value}
    with TestClient(application()) as client:
        response = client.post("/api/v1/methods/fuzdrop/import", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert "Traceback" not in response.text


def test_import_size_limit_is_operational_and_returns_413():
    with TestClient(application(fuzdrop_import_max_bytes=64)) as client:
        response = client.post("/api/v1/methods/fuzdrop/import", json=IMPORT_BODY)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "FUZDROP_IMPORT_TOO_LARGE"


@pytest.mark.parametrize("endpoint", ["import", "analyze"])
def test_schema_validation_errors_do_not_echo_raw_sequence_tsv_or_private_extra_input(endpoint):
    sensitive_marker = str(Path.cwd() / "private-server" / "sensitive-export.tsv")
    body = {"sequence": 42, "unexpected": sensitive_marker, "scores_tsv": "PRIVATE_EXPORT_TEXT"}
    with TestClient(application()) as client:
        response = client.post(f"/api/v1/methods/fuzdrop/{endpoint}", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == f"FUZDROP_INVALID_{endpoint.upper()}_REQUEST"
    assert "private-server" not in response.text
    assert "PRIVATE_EXPORT_TEXT" not in response.text
    assert "input" not in response.json()["detail"]


def test_unexpected_import_failure_has_safe_http_error_and_private_server_log(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise RuntimeError(f"private server detail {Path.cwd() / 'internal-models' / 'secret.pt'}")

    monkeypatch.setattr(fuzdrop_api, "import_fuzdrop_result", fail)
    with TestClient(application()) as client:
        response = client.post("/api/v1/methods/fuzdrop/import", json=IMPORT_BODY)
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "FUZDROP_IMPORT_FAILED"
    assert "internal-models" not in response.text
    assert "Traceback" not in response.text
    assert "internal-models" in caplog.text


@pytest.mark.parametrize(
    "site",
    [
        "https://fuzdrop.bio.unipd.it",
        "https://fuzdrop.bio.unipd.it/",
        "https://fuzdrop.bio.unipd.it/predictor",
    ],
)
def test_only_official_https_site_links_can_be_configured(site):
    settings = Settings(_env_file=None, fuzdrop_official_site_url=site)
    assert settings.fuzdrop_official_site_url == site


@pytest.mark.parametrize(
    "site",
    [
        "http://fuzdrop.bio.unipd.it/predictor",
        "https://example.com/predictor",
        "https://fuzdrop.bio.unipd.it/predictor?token=secret",
        "https://fuzdrop.bio.unipd.it/predictor#secret",
        "https://user:secret@fuzdrop.bio.unipd.it/predictor",
        "https://fuzdrop.bio.unipd.it/private",
        str(Path.cwd() / "private-server" / "index.html"),
    ],
)
def test_other_hosts_protocols_credentials_queries_and_paths_are_rejected(site):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, fuzdrop_official_site_url=site)


def test_fuzdrop_environment_settings_do_not_create_automatic_access(monkeypatch):
    monkeypatch.setenv("FUZDROP_OFFICIAL_SITE_URL", "https://fuzdrop.bio.unipd.it/")
    monkeypatch.setenv("FUZDROP_MANUAL_IMPORT_ENABLED", "false")
    monkeypatch.setenv("FUZDROP_IMPORT_MAX_BYTES", "4096")
    settings = Settings(_env_file=None)
    assert settings.fuzdrop_official_site_url == "https://fuzdrop.bio.unipd.it/"
    assert settings.fuzdrop_manual_import_enabled is False
    assert settings.fuzdrop_import_max_bytes == 4096
    assert not hasattr(settings, "fuzdrop_api_key")
    assert not hasattr(settings, "fuzdrop_api_url")


@pytest.mark.parametrize("phase", ["load", "health", "analyze", "unsafe_health", "close"])
def test_fuzdrop_failures_are_isolated_from_lreca_and_do_not_expose_internal_details(phase):
    settings = Settings(_env_file=None, database_url="sqlite://")
    lreca = LocalLRECAStub()
    private_detail = (
        f"private-fuzdrop-diagnostic {Path.cwd() / 'internal-service' / 'private-token.txt'}"
    )

    class FailingFuzDrop(FuzDropRemoteAdapter):
        def __init__(self):
            super().__init__(settings)
            self.loads = self.closes = 0

        async def load(self):
            self.loads += 1
            if phase == "load":
                raise RuntimeError(private_detail)
            await super().load()

        async def healthcheck(self):
            if phase == "health":
                raise RuntimeError(private_detail)
            health = await super().healthcheck()
            if phase == "unsafe_health":
                return health.model_copy(
                    update={"message": private_detail, "reason": private_detail}
                )
            return health

        async def analyze(self, sequence):
            if phase == "analyze":
                raise RuntimeError(private_detail)
            return await super().analyze(sequence)

        async def close(self):
            self.closes += 1
            if phase == "close":
                raise RuntimeError(private_detail)
            await super().close()

    fuzdrop = FailingFuzDrop()
    with TestClient(create_app(settings, lreca_adapter=lreca, fuzdrop_adapter=fuzdrop)) as client:
        health = client.get("/api/v1/methods/fuzdrop/health")
        assert health.status_code == 503
        assert health.json()["integration_mode"] == "browser_protected"
        assert health.json()["reason"] == "official_service_requires_browser_verification"
        analysis = client.post("/api/v1/methods/fuzdrop/analyze", json={"sequence": "ACDE"})
        assert analysis.status_code == 503
        assert analysis.json()["error"]["code"] == "FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE"
        methods = client.get("/api/v1/methods")
        assert methods.status_code == 200
        listing = {method["id"]: method for method in methods.json()["methods"]}
        assert listing["lreca"]["available"] is True
        assert listing["fuzdrop"]["available"] is True
        assert client.get("/api/v1/health").json()["analysis_enabled"] is True
        assert client.post("/api/v1/methods/fuzdrop/import", json=IMPORT_BODY).status_code == 200
        for response in (health, analysis, methods):
            assert "private-fuzdrop-diagnostic" not in response.text
            assert "internal-service" not in response.text
            assert "Traceback" not in response.text
        assert lreca.loads == fuzdrop.loads == 1
    assert lreca.closes == fuzdrop.closes == 1
