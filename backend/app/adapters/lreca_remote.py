"""Server-side HTTP adapter for the internal LRECA inference service."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.adapters.base import BaseAnalysisAdapter
from app.schemas.analysis import AnalysisStatus, MethodCategory
from app.schemas.lreca import LRECAHealth, LRECAResult
from app.services.lreca_errors import (
    LRECA_READY_MESSAGE,
    LRECA_UNAVAILABLE_MESSAGE,
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from app.services.sequence_validation import normalize_sequence
from lreca_runtime.metadata import CHECKPOINT_SHA256
from lreca_service.schemas import LRECAReadyResponse


def _service_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("LRECA_SERVICE_URL must be an HTTP(S) origin without credentials or path")
    return value.rstrip("/")


class RemoteLRECAAdapter(BaseAnalysisAdapter):
    """Call the private LRECA service while preserving the Module 1 result schema."""

    method_id = "lreca"
    category = MethodCategory.PREDICTION
    implementation_module = 10

    def __init__(
        self,
        service_url: str,
        *,
        request_timeout_seconds: float = 150,
        connect_timeout_seconds: float = 5,
        expected_checkpoint_sha256: str = CHECKPOINT_SHA256,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__()
        if request_timeout_seconds <= 0 or connect_timeout_seconds <= 0:
            raise ValueError("LRECA service timeouts must be positive")
        if re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256) is None:
            raise ValueError("Expected LRECA checkpoint SHA256 is invalid")
        self.service_url = _service_origin(service_url)
        self.request_timeout_seconds = request_timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.expected_checkpoint_sha256 = expected_checkpoint_sha256
        self._client = client
        self._owns_client = client is None
        self._loaded = False
        self._health: LRECAHealth | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(
                self.request_timeout_seconds,
                connect=self.connect_timeout_seconds,
            )
            self._client = httpx.AsyncClient(
                base_url=self.service_url,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._http_client().request(method, path, **kwargs)
        except httpx.TimeoutException as error:
            self.status = AnalysisStatus.FAILED
            raise LRECATimeoutError("LRECA internal service request timed out.") from error
        except httpx.TransportError as error:
            self.status = AnalysisStatus.UNAVAILABLE
            self._loaded = False
            raise LRECAUnavailableError("LRECA internal service is unavailable.") from error

    def _validate_ready(self, response: httpx.Response) -> LRECAReadyResponse:
        if response.status_code == 503:
            self.status = AnalysisStatus.UNAVAILABLE
            self._loaded = False
            raise LRECAUnavailableError("LRECA internal service is not ready.")
        if response.status_code != 200:
            self.status = AnalysisStatus.UNAVAILABLE
            self._loaded = False
            raise LRECAUnavailableError("LRECA internal service health request failed.")
        try:
            readiness = LRECAReadyResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            self.status = AnalysisStatus.UNAVAILABLE
            self._loaded = False
            raise LRECAUnavailableError(
                "LRECA internal service returned an invalid health response."
            ) from error
        if (
            not readiness.ready
            or not readiness.loaded
            or not readiness.checkpoint_verified
            or readiness.metadata is None
            or readiness.device is None
            or readiness.metadata.checkpoint_sha256 != self.expected_checkpoint_sha256
        ):
            self.status = AnalysisStatus.UNAVAILABLE
            self._loaded = False
            raise LRECAUnavailableError("LRECA internal service model identity is not ready.")
        return readiness

    async def load(self) -> None:
        readiness = self._validate_ready(await self._request("GET", "/health/ready"))
        assert readiness.metadata is not None
        self._health = LRECAHealth(
            status=AnalysisStatus.READY,
            message=LRECA_READY_MESSAGE,
            loaded=True,
            device=readiness.device,
            metadata=readiness.metadata,
        )
        self._loaded = True
        self.status = AnalysisStatus.READY

    async def healthcheck(self) -> LRECAHealth:
        try:
            readiness = self._validate_ready(await self._request("GET", "/health/ready"))
        except (LRECAUnavailableError, LRECATimeoutError):
            self.status = AnalysisStatus.UNAVAILABLE
            self._loaded = False
            return LRECAHealth(
                status=AnalysisStatus.UNAVAILABLE,
                message=LRECA_UNAVAILABLE_MESSAGE,
                loaded=False,
            )
        assert readiness.metadata is not None
        self._loaded = True
        self.status = AnalysisStatus.READY
        self._health = LRECAHealth(
            status=AnalysisStatus.READY,
            message=LRECA_READY_MESSAGE,
            loaded=True,
            device=readiness.device,
            metadata=readiness.metadata,
        )
        return self._health

    async def analyze(
        self,
        sequence: str,
        *,
        include_attribution: bool = True,
        include_kde: bool = True,
    ) -> LRECAResult:
        if not self._loaded:
            raise LRECAUnavailableError("LRECA internal service has not passed readiness.")
        canonical = normalize_sequence(sequence)
        self.status = AnalysisStatus.RUNNING
        response = await self._request(
            "POST",
            "/internal/v1/analyze",
            json={
                "sequence": canonical,
                "include_attribution": include_attribution,
                "include_kde": include_kde and include_attribution,
            },
        )
        if response.status_code == 503:
            self._loaded = False
            self.status = AnalysisStatus.UNAVAILABLE
            raise LRECAUnavailableError("LRECA internal service became unavailable.")
        if response.status_code == 504:
            self._loaded = False
            self.status = AnalysisStatus.FAILED
            raise LRECATimeoutError("LRECA internal service analysis timed out.")
        if response.status_code != 200:
            self.status = AnalysisStatus.FAILED
            raise LRECAAnalysisError("LRECA internal service rejected the analysis request.")
        try:
            result = LRECAResult.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            self.status = AnalysisStatus.FAILED
            raise LRECAAnalysisError(
                "LRECA internal service returned an invalid analysis response."
            ) from error
        if (
            result.sequence != canonical
            or result.checkpoint_sha256 != self.expected_checkpoint_sha256
        ):
            self._loaded = False
            self.status = AnalysisStatus.UNAVAILABLE
            raise LRECAAnalysisError("LRECA internal service model identity changed.")
        self.status = AnalysisStatus.SUCCESS
        return result

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
        self._loaded = False
        self._health = None
        self.status = AnalysisStatus.UNAVAILABLE
