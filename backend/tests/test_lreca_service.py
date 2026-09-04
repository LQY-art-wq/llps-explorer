"""Deployment-boundary tests; synthetic adapters never run scientific inference."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.lreca_remote import RemoteLRECAAdapter
from app.api.lreca import analyze_lreca
from app.core.config import Settings
from app.main import create_lreca_adapter
from app.schemas.lreca import LRECAAnalyzeRequest, LRECAHealth, LRECAResult
from app.services.lreca_errors import (
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from lreca_service.config import LRECAServiceSettings
from lreca_service.main import create_app

COMMIT = "0b4b48ab7870529a34028c6e30dfba42eddbf215"
CHECKPOINT = "human_1_RCNN_ECA_parallel_089-0.9802.pt"


def public_metadata(sha256: str) -> dict:
    return {
        "repository": "https://github.com/ai-phasepro/LRECA",
        "commit": COMMIT,
        "checkpoint": CHECKPOINT,
        "checkpoint_sha256": sha256,
        "checkpoint_size_bytes": 12,
    }


def result_payload(sequence: str, sha256: str) -> dict:
    return LRECAResult(
        repository_commit=COMMIT,
        checkpoint=CHECKPOINT,
        checkpoint_sha256=sha256,
        metadata=public_metadata(sha256),
        sequence=sequence,
        sequence_length=len(sequence),
        raw_score=0.25,
        calibrated_score=0.25,
        logits=[math.log(3), 0.0],
        threshold=0.5,
        label="N",
        device="cpu",
        runtime_ms=1.0,
        warnings=["HTTP-boundary fixture; not a model prediction."],
    ).model_dump(mode="json")


class ServiceAdapterStub:
    def __init__(
        self,
        sha256: str,
        *,
        load_error: Exception | None = None,
        load_delay: float = 0,
    ):
        self.sha256 = sha256
        self.load_error = load_error
        self.load_delay = load_delay
        self.loads = 0
        self.closes = 0
        self.loaded = False
        self.calls: list[tuple[str, bool, bool]] = []

    async def load(self) -> None:
        self.loads += 1
        if self.load_delay:
            import asyncio

            await asyncio.sleep(self.load_delay)
        if self.load_error is not None:
            raise self.load_error
        self.loaded = True

    async def healthcheck(self) -> LRECAHealth:
        return LRECAHealth(
            status="ready" if self.loaded else "unavailable",
            message="Synthetic service adapter.",
            loaded=self.loaded,
            device="cpu" if self.loaded else None,
            metadata=public_metadata(self.sha256) if self.loaded else None,
        )

    async def analyze(
        self, sequence: str, *, include_attribution: bool, include_kde: bool
    ) -> LRECAResult:
        self.calls.append((sequence, include_attribution, include_kde))
        return LRECAResult.model_validate(result_payload(sequence, self.sha256))

    async def close(self) -> None:
        self.closes += 1
        self.loaded = False


def service_settings(checkpoint: Path, sha256: str, **options) -> LRECAServiceSettings:
    return LRECAServiceSettings(
        _env_file=None,
        lreca_checkpoint=checkpoint,
        lreca_expected_checkpoint_sha256=sha256,
        **options,
    )


def wait_until(predicate, timeout: float = 2) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for service initialization")
        time.sleep(0.01)


def test_service_verifies_then_loads_once_and_reuses_model(tmp_path):
    checkpoint = tmp_path / CHECKPOINT
    checkpoint.write_bytes(b"verified-fixture")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    adapter = ServiceAdapterStub(digest, load_delay=0.1)
    application = create_app(service_settings(checkpoint, digest), adapter=adapter)

    with TestClient(application) as client:
        assert client.get("/health/live").json() == {"status": "live"}
        assert client.get("/health/ready").status_code == 503
        wait_until(lambda: application.state.ready)
        assert adapter.loads == 1
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checkpoint_verified"] is True
        assert str(checkpoint.resolve()) not in ready.text
        for _ in range(3):
            response = client.post(
                "/internal/v1/analyze",
                json={
                    "sequence": ">protein\nac de",
                    "include_attribution": False,
                    "include_kde": True,
                },
            )
            assert response.status_code == 200
            assert response.json()["sequence"] == "ACDE"
        assert adapter.loads == 1
        assert application.state.load_attempts == 1
    assert adapter.closes == 1
    assert adapter.calls == [("ACDE", False, False)] * 3


def test_bad_sha_keeps_process_live_but_never_loads_or_predicts(tmp_path):
    checkpoint = tmp_path / CHECKPOINT
    checkpoint.write_bytes(b"unknown-weights")
    expected = hashlib.sha256(b"expected-weights").hexdigest()
    adapter = ServiceAdapterStub(expected)
    application = create_app(service_settings(checkpoint, expected), adapter=adapter)

    with TestClient(application) as client:
        wait_until(lambda: application.state.startup_task.done())
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
        analyze = client.post("/internal/v1/analyze", json={"sequence": "ACDE"})
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "unavailable",
        "ready": False,
        "checkpoint_verified": False,
        "loaded": False,
        "device": None,
        "metadata": None,
    }
    assert analyze.status_code == 503
    assert analyze.json()["detail"]["code"] == "LRECA_UNAVAILABLE"
    assert adapter.loads == 0
    assert adapter.closes == 1


def test_startup_failure_is_unready_without_exposing_checkpoint_path(tmp_path, caplog):
    checkpoint = tmp_path / CHECKPOINT
    checkpoint.write_bytes(b"verified-fixture")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    private_detail = f"failed at {checkpoint.resolve()}"
    adapter = ServiceAdapterStub(digest, load_error=LRECAUnavailableError(private_detail))

    with TestClient(create_app(service_settings(checkpoint, digest), adapter=adapter)) as client:
        wait_until(lambda: client.app.state.startup_task.done())
        live = client.get("/health/live")
        ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 503
    assert str(checkpoint.resolve()) not in live.text + ready.text
    assert str(checkpoint.resolve()) not in caplog.text


def test_service_enforces_one_model_process_per_container(tmp_path):
    with pytest.raises(ValidationError):
        service_settings(tmp_path / CHECKPOINT, "0" * 64, lreca_model_processes=2)


def test_internal_contract_forbids_extra_fields_and_enforces_length(tmp_path):
    checkpoint = tmp_path / CHECKPOINT
    checkpoint.write_bytes(b"verified-fixture")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    adapter = ServiceAdapterStub(digest)
    settings = service_settings(checkpoint, digest, analysis_max_sequence_length=3)

    with TestClient(create_app(settings, adapter=adapter)) as client:
        wait_until(lambda: client.app.state.ready)
        extra = client.post(
            "/internal/v1/analyze", json={"sequence": "ACD", "server_path": "/models/x"}
        )
        too_long = client.post("/internal/v1/analyze", json={"sequence": "ACDE"})
    assert extra.status_code == 422
    assert too_long.status_code == 413
    assert too_long.json()["detail"]["code"] == "ANALYSIS_SEQUENCE_TOO_LONG"


@pytest.mark.anyio
async def test_remote_adapter_preserves_schema_flags_and_safe_metadata():
    sha256 = hashlib.sha256(b"expected").hexdigest()
    requests: list[tuple[str, str, dict | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/health/ready":
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "ready": True,
                    "checkpoint_verified": True,
                    "loaded": True,
                    "device": "cpu",
                    "metadata": public_metadata(sha256),
                },
            )
        return httpx.Response(200, json=result_payload(body["sequence"], sha256))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://lreca:8001"
    )
    adapter = RemoteLRECAAdapter(
        "http://lreca:8001", expected_checkpoint_sha256=sha256, client=client
    )
    await adapter.load()
    result = await adapter.analyze("ac de", include_attribution=False, include_kde=True)
    health = await adapter.healthcheck()
    await adapter.close()
    assert result.sequence == "ACDE"
    assert health.loaded is True
    assert requests[1] == (
        "POST",
        "/internal/v1/analyze",
        {"sequence": "ACDE", "include_attribution": False, "include_kde": False},
    )
    assert "/models/" not in json.dumps(result.model_dump(mode="json"))
    assert not client.is_closed
    await client.aclose()


@pytest.mark.anyio
async def test_remote_adapter_rejects_unready_or_wrong_model_identity():
    expected = hashlib.sha256(b"expected").hexdigest()
    other = hashlib.sha256(b"other").hexdigest()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "ready": True,
                "checkpoint_verified": True,
                "loaded": True,
                "device": "cpu",
                "metadata": public_metadata(other),
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://lreca:8001"
    ) as client:
        adapter = RemoteLRECAAdapter(
            "http://lreca:8001", expected_checkpoint_sha256=expected, client=client
        )
        with pytest.raises(LRECAUnavailableError):
            await adapter.load()


@pytest.mark.anyio
async def test_remote_transport_timeout_is_typed_and_does_not_echo_url():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret internal endpoint", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://lreca:8001"
    ) as client:
        adapter = RemoteLRECAAdapter("http://lreca:8001", client=client)
        with pytest.raises(LRECATimeoutError, match="request timed out") as caught:
            await adapter.load()
    assert "http://" not in str(caught.value)


@pytest.mark.anyio
async def test_remote_transport_failure_is_typed_and_safe():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private network detail", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://lreca:8001"
    ) as client:
        adapter = RemoteLRECAAdapter("http://lreca:8001", client=client)
        with pytest.raises(LRECAUnavailableError) as caught:
            await adapter.load()
    assert "private network detail" not in str(caught.value)
    assert "http://" not in str(caught.value)


@pytest.mark.parametrize(
    "service_url",
    ["file:///models/lreca", "http://user:pass@lreca:8001", "http://lreca:8001/private"],
)
def test_remote_service_url_must_be_a_safe_origin(service_url):
    with pytest.raises(ValueError):
        RemoteLRECAAdapter(service_url)


def test_main_backend_selects_remote_adapter_when_service_is_configured():
    settings = Settings(
        _env_file=None,
        lreca_service_url="http://lreca:8001",
        lreca_service_timeout_seconds=33,
        lreca_service_connect_timeout_seconds=4,
    )
    adapter = create_lreca_adapter(settings)
    assert isinstance(adapter, RemoteLRECAAdapter)
    assert adapter.request_timeout_seconds == 33
    assert adapter.connect_timeout_seconds == 4


@pytest.mark.anyio
async def test_rq_mode_rejects_synchronous_public_lreca_inference():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/methods/lreca/analyze",
            "headers": [],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    settings=SimpleNamespace(analysis_queue_backend="rq")
                )
            ),
        }
    )
    with pytest.raises(HTTPException) as caught:
        await analyze_lreca(LRECAAnalyzeRequest(sequence="ACDE"), request)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "LRECA_ASYNC_ONLY"


@pytest.mark.anyio
async def test_remote_http_analysis_failure_is_deterministic_not_transport_error():
    sha256 = hashlib.sha256(b"expected").hexdigest()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "ready": True,
                    "checkpoint_verified": True,
                    "loaded": True,
                    "device": "cpu",
                    "metadata": public_metadata(sha256),
                },
            )
        return httpx.Response(500, json={"detail": {"code": "LRECA_ANALYSIS_FAILED"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://lreca:8001"
    ) as client:
        adapter = RemoteLRECAAdapter(
            "http://lreca:8001", expected_checkpoint_sha256=sha256, client=client
        )
        await adapter.load()
        with pytest.raises(LRECAAnalysisError):
            await adapter.analyze("ACDE")
