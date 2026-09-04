import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.schemas.analysis import AnalysisStatus
from app.schemas.lreca import LRECAAnalyzeRequest, LRECAHealth, LRECAResult
from app.services.lreca_errors import (
    LRECA_ANALYSIS_FAILED_MESSAGE,
    LRECA_READY_MESSAGE,
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

router = APIRouter(prefix="/methods/lreca", tags=["lreca"])
READY_STATUSES = {AnalysisStatus.READY, AnalysisStatus.RUNNING, AnalysisStatus.SUCCESS}
logger = logging.getLogger("uvicorn.error.lreca.api")


async def get_lreca_health(request: Request) -> LRECAHealth:
    adapter = getattr(request.app.state, "lreca_adapter", None)
    if adapter is None:
        return LRECAHealth(status="unavailable", message=LRECA_UNAVAILABLE_MESSAGE)
    try:
        health = LRECAHealth.model_validate(await adapter.healthcheck())
        # Adapter diagnostics must never become an HTTP message, even if a
        # future adapter returns more detailed internal readiness text.
        return health.model_copy(
            update={
                "message": LRECA_READY_MESSAGE
                if health.status in READY_STATUSES
                else LRECA_UNAVAILABLE_MESSAGE
            }
        )
    except (LRECAUnavailableError, LRECATimeoutError, LRECAAnalysisError, ValidationError):
        logger.exception("LRECA health check failed; details are restricted to server logs.")
        return LRECAHealth(status="unavailable", message=LRECA_UNAVAILABLE_MESSAGE)


@router.get("/health", response_model=LRECAHealth, responses={503: {"model": LRECAHealth}})
async def lreca_health(request: Request):
    """Model readiness without running prediction, Grad-CAM, or KDE."""
    health = await get_lreca_health(request)
    if health.status not in READY_STATUSES:
        return JSONResponse(status_code=503, content=health.model_dump(mode="json"))
    return health


@router.post("/analyze", response_model=LRECAResult)
async def analyze_lreca(payload: LRECAAnalyzeRequest, request: Request) -> LRECAResult:
    """Analyze one protein with the already-loaded human-specific model."""
    if request.app.state.settings.analysis_queue_backend == "rq":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LRECA_ASYNC_ONLY",
                "message": "Submit LRECA through the asynchronous analysis API.",
            },
        )
    try:
        sequence = ensure_sequence_length(
            normalize_sequence(payload.sequence),
            request.app.state.settings.analysis_max_sequence_length,
        )
        adapter = getattr(request.app.state, "lreca_adapter", None)
        if adapter is None:
            raise LRECAUnavailableError("LRECA has not been initialized.")
        return await adapter.analyze(
            sequence,
            include_attribution=payload.include_attribution,
            include_kde=payload.include_kde and payload.include_attribution,
        )
    except SequenceValidationError as error:
        status_code = 413 if error.detail["code"] == "ANALYSIS_SEQUENCE_TOO_LONG" else 422
        raise HTTPException(status_code=status_code, detail=error.detail) from error
    except LRECAUnavailableError as error:
        logger.exception("LRECA is unavailable; details are restricted to server logs.")
        raise HTTPException(
            status_code=503,
            detail={"code": "LRECA_UNAVAILABLE", "message": LRECA_UNAVAILABLE_MESSAGE},
        ) from error
    except LRECATimeoutError as error:
        logger.exception("LRECA timed out; details are restricted to server logs.")
        raise HTTPException(
            status_code=504, detail={"code": "LRECA_TIMEOUT", "message": LRECA_TIMEOUT_MESSAGE}
        ) from error
    except LRECAAnalysisError as error:
        logger.exception("LRECA analysis failed; details are restricted to server logs.")
        raise HTTPException(
            status_code=500,
            detail={"code": "LRECA_ANALYSIS_FAILED", "message": LRECA_ANALYSIS_FAILED_MESSAGE},
        ) from error
