"""FastAPI service owning exactly one resident human-specific LRECA adapter."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.adapters.lreca import LRECAAdapter
from app.core.observability import ProductionHTTPMiddleware, configure_logging
from app.schemas.analysis import AnalysisStatus
from app.schemas.lreca import LRECAAnalyzeRequest, LRECAHealth, LRECAResult
from app.services.lreca_errors import (
    LRECA_ANALYSIS_FAILED_MESSAGE,
    LRECA_TIMEOUT_MESSAGE,
    LRECA_UNAVAILABLE_MESSAGE,
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from app.services.sequence_validation import (
    SequenceValidationError,
    ensure_sequence_length,
    normalize_sequence,
)
from lreca_runtime.metadata import resolve_project_path
from lreca_service.config import LRECAServiceSettings
from lreca_service.schemas import LRECALiveResponse, LRECAReadyResponse

logger = logging.getLogger("uvicorn.error.lreca.service")
_READY = {AnalysisStatus.READY, AnalysisStatus.RUNNING, AnalysisStatus.SUCCESS}


class LRECAAdapterProtocol(Protocol):
    async def load(self) -> None: ...

    async def healthcheck(self) -> LRECAHealth: ...

    async def analyze(
        self, sequence: str, *, include_attribution: bool, include_kde: bool
    ) -> LRECAResult: ...

    async def close(self) -> None: ...


def checkpoint_matches(path: Path, expected_sha256: str) -> bool:
    """Verify a mounted checkpoint without returning its path or actual digest."""

    checkpoint = resolve_project_path(path)
    if not checkpoint.is_file():
        return False
    digest = hashlib.sha256()
    try:
        with checkpoint.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return hmac.compare_digest(digest.hexdigest(), expected_sha256)


def create_app(
    settings: LRECAServiceSettings | None = None,
    *,
    adapter: LRECAAdapterProtocol | None = None,
) -> FastAPI:
    service_settings = settings or LRECAServiceSettings()
    configure_logging(
        service="llps-lreca",
        level=service_settings.log_level,
        structured=(
            service_settings.app_environment == "production"
            or service_settings.structured_logging
        ),
    )

    async def initialize(application: FastAPI, runtime: LRECAAdapterProtocol) -> None:
        try:
            verified = await asyncio.to_thread(
                checkpoint_matches,
                service_settings.lreca_checkpoint,
                service_settings.lreca_expected_checkpoint_sha256,
            )
        except Exception as error:
            verified = False
            logger.error(
                "LRECA checkpoint verification failed error_type=%s.",
                type(error).__name__,
            )
        application.state.checkpoint_verified = verified
        if not verified:
            logger.error("LRECA checkpoint is missing or failed SHA256 verification.")
            return
        application.state.load_attempts = 1
        try:
            await runtime.load()
            health = LRECAHealth.model_validate(await runtime.healthcheck())
            metadata = health.metadata
            identity_matches = (
                metadata is not None
                and health.device is not None
                and metadata.checkpoint_sha256
                == service_settings.lreca_expected_checkpoint_sha256
            )
            application.state.loaded = bool(health.loaded and identity_matches)
            application.state.ready = bool(
                application.state.loaded and health.status in _READY
            )
            if application.state.ready:
                logger.info(
                    "LRECA service ready model_variant=%s checkpoint=%s sha256=%s "
                    "repository_commit=%s device=%s",
                    metadata.model_variant,
                    metadata.checkpoint,
                    metadata.checkpoint_sha256,
                    metadata.commit,
                    health.device,
                )
            else:
                logger.error("LRECA service model identity or readiness check failed.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("LRECA service startup failed error_type=%s.", type(error).__name__)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime = adapter or LRECAAdapter(service_settings)  # type: ignore[arg-type]
        application.state.adapter = runtime
        application.state.checkpoint_verified = False
        application.state.loaded = False
        application.state.ready = False
        application.state.load_attempts = 0
        startup_task = asyncio.create_task(initialize(application, runtime))
        application.state.startup_task = startup_task
        try:
            # Serving starts immediately: live succeeds while ready remains false during load.
            yield
        finally:
            application.state.ready = False
            application.state.loaded = False
            if not startup_task.done():
                startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task
            try:
                await runtime.close()
            except Exception as error:
                logger.error(
                    "LRECA service shutdown failed error_type=%s.", type(error).__name__
                )

    application = FastAPI(
        title="LLPS Explorer LRECA Internal Service",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = service_settings
    application.state.adapter = adapter
    application.state.semaphore = asyncio.Semaphore(
        service_settings.lreca_max_concurrent_requests
    )
    application.state.checkpoint_verified = False
    application.state.loaded = False
    application.state.ready = False
    application.state.load_attempts = 0
    application.add_middleware(ProductionHTTPMiddleware)

    @application.get("/health/live", response_model=LRECALiveResponse)
    async def live() -> LRECALiveResponse:
        return LRECALiveResponse()

    async def ready_snapshot() -> LRECAReadyResponse:
        runtime = application.state.adapter
        if not application.state.ready or runtime is None:
            return LRECAReadyResponse(
                status="unavailable",
                ready=False,
                checkpoint_verified=application.state.checkpoint_verified,
                loaded=False,
            )
        try:
            health = LRECAHealth.model_validate(await runtime.healthcheck())
            metadata = health.metadata
            is_ready = bool(
                health.loaded
                and health.status in _READY
                and health.device is not None
                and metadata is not None
                and metadata.checkpoint_sha256
                == service_settings.lreca_expected_checkpoint_sha256
            )
        except Exception as error:
            logger.error("LRECA readiness probe failed error_type=%s.", type(error).__name__)
            is_ready = False
            health = None
            metadata = None
        if not is_ready:
            application.state.ready = False
            application.state.loaded = False
        return LRECAReadyResponse(
            status="ready" if is_ready else "unavailable",
            ready=is_ready,
            checkpoint_verified=application.state.checkpoint_verified,
            loaded=is_ready,
            device=health.device if is_ready and health is not None else None,
            metadata=metadata if is_ready else None,
        )

    @application.get(
        "/health/ready",
        response_model=LRECAReadyResponse,
        responses={503: {"model": LRECAReadyResponse}},
    )
    async def ready():
        snapshot = await ready_snapshot()
        if not snapshot.ready:
            return JSONResponse(status_code=503, content=snapshot.model_dump(mode="json"))
        return snapshot

    @application.post("/internal/v1/analyze", response_model=LRECAResult)
    async def analyze(payload: LRECAAnalyzeRequest) -> LRECAResult:
        if not application.state.ready or application.state.adapter is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "LRECA_UNAVAILABLE", "message": LRECA_UNAVAILABLE_MESSAGE},
            )
        try:
            sequence = ensure_sequence_length(
                normalize_sequence(payload.sequence),
                service_settings.analysis_max_sequence_length,
            )
            async with application.state.semaphore:
                return await application.state.adapter.analyze(
                    sequence,
                    include_attribution=payload.include_attribution,
                    include_kde=payload.include_kde and payload.include_attribution,
                )
        except SequenceValidationError as error:
            status_code = 413 if error.detail["code"] == "ANALYSIS_SEQUENCE_TOO_LONG" else 422
            raise HTTPException(status_code=status_code, detail=error.detail) from error
        except LRECAUnavailableError as error:
            application.state.ready = False
            application.state.loaded = False
            logger.error("LRECA runtime unavailable error_type=%s.", type(error).__name__)
            raise HTTPException(
                status_code=503,
                detail={"code": "LRECA_UNAVAILABLE", "message": LRECA_UNAVAILABLE_MESSAGE},
            ) from error
        except LRECATimeoutError as error:
            application.state.ready = False
            application.state.loaded = False
            logger.error("LRECA runtime timed out error_type=%s.", type(error).__name__)
            raise HTTPException(
                status_code=504,
                detail={"code": "LRECA_TIMEOUT", "message": LRECA_TIMEOUT_MESSAGE},
            ) from error
        except (LRECAAnalysisError, ValidationError) as error:
            logger.error("LRECA analysis failed error_type=%s.", type(error).__name__)
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "LRECA_ANALYSIS_FAILED",
                    "message": LRECA_ANALYSIS_FAILED_MESSAGE,
                },
            ) from error

    return application


app = create_app()
