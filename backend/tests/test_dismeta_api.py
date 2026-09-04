"""Offline HTTP boundaries for the audited, blocked DisMeta integration."""

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as app_main
from app.adapters.dismeta import DisMetaAdapter
from app.core.config import Settings
from app.main import create_app
from app.schemas.dismeta import DISMETA_UNAVAILABLE_MESSAGE, DisMetaErrorDetail, DisMetaResult
from app.schemas.lreca import LRECAHealth
from app.schemas.seg import SEGHealth


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("sync")
        raise AssertionError("DisMeta tests must not contact an external service")

    async def deny_async(*args, **kwargs):
        attempts.append("async")
        raise AssertionError("DisMeta tests must not contact an external service")

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
            message="API test fixture only.",
        )


class SEGStub:
    def __init__(self):
        self.loads = self.closes = 0

    async def load(self):
        self.loads += 1

    async def close(self):
        self.closes += 1

    async def healthcheck(self):
        return SEGHealth(
            status="ready",
            available=True,
            reason=None,
            version="2.17.0",
            application_version="1.0.0",
            parameters={"window": 12, "locut": 2.2, "hicut": 2.5},
        )


class CountedDisMeta(DisMetaAdapter):
    def __init__(self, settings=None):
        super().__init__(settings or Settings(_env_file=None))
        self.loads = self.closes = 0
        self.received = []

    async def load(self):
        self.loads += 1
        await super().load()

    async def close(self):
        self.closes += 1
        await super().close()

    async def analyze(self, sequence):
        self.received.append(sequence)
        return await super().analyze(sequence)


def application(*, dismeta=None, lreca=None, seg=None, settings=None):
    app_settings = (settings or Settings(_env_file=None)).model_copy(
        update={"database_url": "sqlite://"}
    )
    return create_app(
        app_settings,
        lreca_adapter=lreca if lreca is not None else LRECAStub(),
        seg_adapter=seg if seg is not None else SEGStub(),
        dismeta_adapter=dismeta,
    )


def assert_blocked(payload):
    assert payload["status"] == "unavailable"
    assert payload["available"] is False
    assert payload["automatic_status"] == "unavailable"
    assert payload["manual_import_supported"] is False
    assert payload["integration_mode"] == "unknown"
    assert payload["audit_mode"] == "F"
    assert payload["decision"] == "INTEGRATION_BLOCKED"
    assert payload["reason"] == "integration_contract_unverified"
    assert payload["version"] is None
    assert payload["message"] == DISMETA_UNAVAILABLE_MESSAGE


def test_health_analyze_and_methods_preserve_audited_blocked_mode_and_other_lifecycles():
    dismeta, lreca, seg = CountedDisMeta(), LRECAStub(), SEGStub()
    with TestClient(application(dismeta=dismeta, lreca=lreca, seg=seg)) as client:
        for _ in range(2):
            health = client.get("/api/v1/methods/dismeta/health")
            assert health.status_code == 503
            assert_blocked(health.json())
            response = client.post(
                "/api/v1/methods/dismeta/analyze", json={"sequence": "\n>one protein\nac d e f g\n"}
            )
            assert response.status_code == 503
            result = response.json()
            assert_blocked(result)
            assert result["method"] == "dismeta"
            assert result["annotation_type"] == "IDR"
            assert result["semantic_type"] == "region_annotation"
            assert result["error"]["code"] == "DISMETA_UNAVAILABLE"
            assert result["error"]["message"] == DISMETA_UNAVAILABLE_MESSAGE
            assert all(
                result[field] is None
                for field in ("regions", "coverage", "region_count", "longest_region")
            )
            assert result["sequence_length"] == 6
            assert result["sequence_sha256"] == hashlib.sha256(b"ACDEFG").hexdigest()
            assert (
                not {"sequence", "global_score", "raw_score", "label", "threshold"} & result.keys()
            )
            methods = client.get("/api/v1/methods")
            assert methods.status_code == 200
            listing = {item["id"]: item for item in methods.json()["methods"]}
            entry = listing["dismeta"]
            assert entry["display_name"] == "Intrinsically Disordered Regions (IDR)"
            assert entry["category"] == "annotation"
            assert entry["capabilities"] == ["regions"]
            assert entry["semantic_types"] == ["region_annotation"]
            assert entry["available"] is entry["manual_import_available"] is False
            assert entry["manual_import_supported"] is False
            assert entry["reason"] == "integration_contract_unverified"
            assert entry["integration_mode"] == "integration_blocked"
            assert listing["lreca"]["available"] is listing["seg"]["available"] is True
            assert listing["fuzdrop"]["manual_import_available"] is True
            assert listing["fuzdrop"]["manual_import_supported"] is True
            assert client.get("/api/v1/health").json()["analysis_enabled"] is True
        assert dismeta.received == ["ACDEFG", "ACDEFG"]
        assert dismeta.loads == lreca.loads == seg.loads == 1
    assert dismeta.closes == lreca.closes == seg.closes == 1


def test_general_health_still_uses_only_lreca_readiness():
    with TestClient(application(lreca=LRECAStub(ready=False))) as client:
        health = client.get("/api/v1/health").json()
        assert health["analysis_enabled"] is False
        assert health["module"] == 10
        assert health["version"] == "0.10.0"
        assert client.get("/api/v1/methods/seg/health").status_code == 200


def test_import_is_absent_and_openapi_does_not_advertise_a_successful_predictor():
    with TestClient(application()) as client:
        response = client.post(
            "/api/v1/methods/dismeta/import", json={"sequence": "ACDEFG", "regions": []}
        )
        assert response.status_code == 404
        document = client.get("/openapi.json").json()
    assert "/api/v1/methods/dismeta/import" not in document["paths"]
    schemas = document["components"]["schemas"]
    assert "DisMetaResult" not in schemas
    assert set(schemas["DisMetaAnalyzeRequest"]["properties"]) == {"sequence"}
    for path, verb in (("health", "get"), ("analyze", "post")):
        responses = document["paths"][f"/api/v1/methods/dismeta/{path}"][verb]["responses"]
        assert "503" in responses and "200" not in responses
    for name in ("DisMetaHealth", "DisMetaUnavailableResult"):
        assert not {"api_key", "executable_path", "raw_output", "score", "label"} & set(
            schemas[name]["properties"]
        )


@pytest.mark.parametrize(
    "sequence,code,position",
    [
        ("", "EMPTY_SEQUENCE", None),
        (" \n\t", "EMPTY_SEQUENCE", None),
        (">one\nACD\n>two\nEFG", "MULTIPLE_FASTA_RECORDS", None),
        ("AC\n>later\nDE", "INVALID_FASTA", None),
        ("ac xde", "INVALID_AMINO_ACID", 3),
    ],
)
def test_invalid_sequence_reuses_shared_validation_before_adapter(sequence, code, position):
    dismeta = CountedDisMeta()
    with TestClient(application(dismeta=dismeta)) as client:
        response = client.post("/api/v1/methods/dismeta/analyze", json={"sequence": sequence})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    if position is not None:
        assert response.json()["detail"]["position"] == position
    assert dismeta.received == []


@pytest.mark.parametrize("body", [{}, {"sequence": 42}, {"sequence": "ACDEFG", "regions": []}])
def test_request_accepts_only_a_sequence_string(body):
    with TestClient(application()) as client:
        response = client.post("/api/v1/methods/dismeta/analyze", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DISMETA_INVALID_REQUEST"


def test_request_error_does_not_echo_private_input_or_log_it(caplog):
    secret = str(Path.cwd() / "private-dismeta-input" / "submitted-sequence.fasta")
    with TestClient(application()) as client:
        response = client.post(
            "/api/v1/methods/dismeta/analyze", json={"sequence": "ACDEFG", "unexpected": secret}
        )
    assert response.status_code == 422
    assert "private-dismeta-input" not in response.text + caplog.text
    assert "input" not in response.json()["detail"]


@pytest.mark.parametrize("phase", ["constructor", "load", "health", "analyze", "close"])
def test_dismeta_failure_isolated_from_other_methods_and_private_diagnostics(
    phase, monkeypatch, caplog
):
    secret = str(Path.cwd() / "private-dismeta-diagnostic" / "unverified-output.txt")

    class FailingDisMeta(CountedDisMeta):
        async def load(self):
            await super().load()
            if phase == "load":
                raise RuntimeError(secret)

        async def healthcheck(self):
            if phase == "health":
                raise RuntimeError(secret)
            return await super().healthcheck()

        async def analyze(self, sequence):
            if phase == "analyze":
                raise RuntimeError(secret)
            return await super().analyze(sequence)

        async def close(self):
            await super().close()
            if phase == "close":
                raise RuntimeError(secret)

    def fail_constructor(*args, **kwargs):
        raise RuntimeError(secret)

    dismeta, lreca, seg = FailingDisMeta(), LRECAStub(), SEGStub()
    if phase == "constructor":
        monkeypatch.setattr(app_main, "DisMetaAdapter", fail_constructor)
    with TestClient(
        application(dismeta=None if phase == "constructor" else dismeta, lreca=lreca, seg=seg)
    ) as client:
        health = client.get("/api/v1/methods/dismeta/health")
        response = client.post("/api/v1/methods/dismeta/analyze", json={"sequence": "ACDEFG"})
        assert health.status_code == response.status_code == 503
        assert_blocked(health.json())
        assert_blocked(response.json())
        listing = client.get("/api/v1/methods")
        assert listing.status_code == 200
        methods = {item["id"]: item for item in listing.json()["methods"]}
        assert methods["lreca"]["available"] is methods["seg"]["available"] is True
        assert methods["fuzdrop"]["manual_import_available"] is True
        assert methods["dismeta"]["available"] is False
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
        assert lreca.loads == seg.loads == 1
        for reply in (health, response, listing):
            assert "private-dismeta-diagnostic" not in reply.text
    assert lreca.closes == seg.closes == 1
    if phase != "constructor":
        assert dismeta.loads == dismeta.closes == 1
    assert "private-dismeta-diagnostic" not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize(
    "field", ["message", "reason", "version", "official_site_url", "available"]
)
def test_health_dto_is_revalidated_and_free_form_messages_are_not_forwarded(field, caplog, recwarn):
    secret = str(Path.cwd() / "private-dismeta-health" / "diagnostic.txt")

    class UnsafeHealth(CountedDisMeta):
        async def healthcheck(self):
            return (await super().healthcheck()).model_copy(
                update={field: True if field == "available" else secret}
            )

    with TestClient(application(dismeta=UnsafeHealth())) as client:
        response = client.get("/api/v1/methods/dismeta/health")
        listing = client.get("/api/v1/methods")
    assert response.status_code == 503
    assert_blocked(response.json())
    assert "private-dismeta-health" not in response.text + listing.text + caplog.text
    assert not any("Pydantic serializer warnings" in str(warning.message) for warning in recwarn)
    if field != "message":
        assert "ValidationError" in caplog.text


@pytest.mark.parametrize("kind", ["private_error", "invented_regions", "success_dto"])
def test_adapter_cannot_expose_diagnostics_or_unverified_scientific_results(kind, caplog, recwarn):
    secret = str(Path.cwd() / "private-dismeta-result" / "diagnostic.txt")

    class UnsafeResult(CountedDisMeta):
        async def analyze(self, sequence):
            result = await super().analyze(sequence)
            if kind == "private_error":
                return result.model_copy(
                    update={"message": secret, "error": DisMetaErrorDetail(message=secret)}
                )
            if kind == "invented_regions":
                return result.model_copy(update={"regions": []})
            return DisMetaResult(
                sequence_length=len(sequence),
                sequence_sha256=hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                regions=[],
                runtime_ms=0.01,
            )

    with TestClient(application(dismeta=UnsafeResult())) as client:
        response = client.post("/api/v1/methods/dismeta/analyze", json={"sequence": "ACDEFG"})
    assert response.status_code == 503
    assert_blocked(response.json())
    assert response.json()["regions"] is None
    assert response.json()["error"]["message"] == DISMETA_UNAVAILABLE_MESSAGE
    assert "private-dismeta-result" not in response.text + caplog.text
    assert not any("Pydantic serializer warnings" in str(warning.message) for warning in recwarn)
    if kind != "private_error":
        assert "ValidationError" in caplog.text


@pytest.mark.parametrize(
    "url",
    ["https://montelionelab.chem.rpi.edu/dismeta", "https://montelionelab.chem.rpi.edu/dismeta/"],
)
def test_only_audited_official_links_are_configurable_and_never_enable_access(url):
    settings = Settings(_env_file=None, dismeta_official_site_url=url)
    with TestClient(application(settings=settings)) as client:
        response = client.get("/api/v1/methods/dismeta/health")
    assert response.status_code == 503
    assert response.json()["official_site_url"] == url
    assert_blocked(response.json())


@pytest.mark.parametrize(
    "url",
    [
        "http://montelionelab.chem.rpi.edu/dismeta/",
        "https://example.com/dismeta/",
        "https://montelionelab.chem.rpi.edu/",
        "https://montelionelab.chem.rpi.edu/dismeta/?token=secret",
        "https://montelionelab.chem.rpi.edu/dismeta/#secret",
        "https://user:secret@montelionelab.chem.rpi.edu/dismeta/",
        str(Path.cwd() / "private-dismeta" / "index.html"),
    ],
)
def test_unverified_urls_or_paths_cannot_be_configured(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dismeta_official_site_url=url)


def test_environment_only_configures_a_link_without_an_api_or_enable_switch(monkeypatch):
    monkeypatch.setenv("DISMETA_OFFICIAL_SITE_URL", "https://montelionelab.chem.rpi.edu/dismeta")
    monkeypatch.setenv("DISMETA_ENABLED", "true")
    monkeypatch.setenv("DISMETA_API_URL", "https://example.com/submit")
    settings = Settings(_env_file=None)
    assert settings.dismeta_official_site_url == "https://montelionelab.chem.rpi.edu/dismeta"
    assert not any(
        name in type(settings).model_fields
        for name in (
            "dismeta_enabled",
            "dismeta_api_url",
            "dismeta_api_key",
            "dismeta_manual_import_enabled",
        )
    )
    with TestClient(application(settings=settings)) as client:
        assert (
            client.post("/api/v1/methods/dismeta/analyze", json={"sequence": "ACDEFG"}).status_code
            == 503
        )
