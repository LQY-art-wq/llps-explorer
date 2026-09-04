"""Independent SEG annotation API with safe public errors and diagnostics."""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.schemas.seg import (
    SEGAnalyzeRequest,
    SEGError,
    SEGErrorDetail,
    SEGHealth,
    SEGResult,
    SEGResultResponse,
    SEGUnavailableResult,
)
from app.services.sequence_validation import (
    SequenceValidationError,
    ensure_sequence_length,
    normalize_sequence,
)

logger = logging.getLogger("uvicorn.error.seg.api")

SEG_MESSAGES = {
    "SEG_EXECUTABLE_NOT_FOUND": "The configured SEG executable is unavailable.",
    "SEG_EXECUTION_FAILED": "SEG annotation could not be completed.",
    "SEG_TIMEOUT": "SEG annotation exceeded the configured time limit.",
    "SEG_PARSE_ERROR": "SEG output could not be parsed.",
    "SEG_INVALID_OUTPUT": "SEG output failed validation.",
    "SEG_UNAVAILABLE": "SEG annotation is currently unavailable.",
}
SEG_STATUS_CODES = {
    "SEG_EXECUTABLE_NOT_FOUND": 503,
    "SEG_EXECUTION_FAILED": 502,
    "SEG_TIMEOUT": 504,
    "SEG_PARSE_ERROR": 502,
    "SEG_INVALID_OUTPUT": 502,
    "SEG_UNAVAILABLE": 503,
}
SEG_READY_MESSAGE = "SEG low-complexity region annotation is available."


def _safe_seg_status_code(code: str, requested_status: int | None = None) -> int:
    # Only the version-validation failure has a second permitted HTTP meaning.
    # Native interval validation remains SEG_INVALID_OUTPUT / 502 by default.
    if code == "SEG_INVALID_OUTPUT" and type(requested_status) is int and requested_status == 503:
        return 503
    return SEG_STATUS_CODES[code]


def safe_seg_failure(error: Exception) -> tuple[str, int]:
    if isinstance(error, SEGError) and error.code in SEG_MESSAGES:
        return error.code, _safe_seg_status_code(error.code, error.status_code)
    code = "SEG_INVALID_OUTPUT" if isinstance(error, ValidationError) else "SEG_EXECUTION_FAILED"
    return code, SEG_STATUS_CODES[code]


def _failure_response(code: str, status_code: int | None = None) -> JSONResponse:
    code = code if code in SEG_MESSAGES else "SEG_UNAVAILABLE"
    status_code = _safe_seg_status_code(code, status_code)
    result = SEGUnavailableResult(
        status="unavailable" if status_code == 503 else "failed",
        message=SEG_MESSAGES[code],
        error=SEGErrorDetail(code=code, message=SEG_MESSAGES[code]),
    )
    return JSONResponse(status_code=status_code, content=result.model_dump(mode="json"))


class SEGRoute(APIRoute):
    """Avoid FastAPI's default validation echo of full submitted sequences."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "SEG_INVALID_REQUEST",
                        "message": "Supply exactly one protein sequence as a string.",
                    },
                ) from error

        return safe_handler


router = APIRouter(prefix="/methods/seg", tags=["seg"], route_class=SEGRoute)


async def get_seg_health(request: Request) -> SEGHealth:
    adapter = getattr(request.app.state, "seg_adapter", None)
    code = getattr(request.app.state, "seg_startup_error_code", "SEG_UNAVAILABLE")
    if adapter is not None:
        try:
            reply = await adapter.healthcheck()
            # Revalidate even DTO instances, including fields carrying provenance.
            health = SEGHealth.model_validate(
                reply.model_dump() if isinstance(reply, SEGHealth) else reply
            )
            code = health.reason if health.reason in SEG_MESSAGES else "SEG_UNAVAILABLE"
            return health.model_copy(
                update={
                    "message": SEG_READY_MESSAGE if health.available else SEG_MESSAGES[code],
                    "reason": None if health.available else code,
                }
            )
        except Exception as error:
            code, _ = safe_seg_failure(error)
            logger.warning("SEG health failed (%s; %s).", type(error).__name__, code)
    code = code if code in SEG_MESSAGES else "SEG_UNAVAILABLE"
    return SEGHealth(status="unavailable", available=False, message=SEG_MESSAGES[code], reason=code)


@router.get("/health", response_model=SEGHealth, responses={503: {"model": SEGHealth}})
async def seg_health(request: Request):
    health = await get_seg_health(request)
    return JSONResponse(
        status_code=200 if health.available else 503, content=health.model_dump(mode="json")
    )


@router.post(
    "/analyze",
    response_model=SEGResultResponse,
    responses={
        502: {"model": SEGUnavailableResult},
        503: {"model": SEGUnavailableResult},
        504: {"model": SEGUnavailableResult},
    },
)
async def analyze_seg(payload: SEGAnalyzeRequest, request: Request):
    """Annotate one protein; SEG never produces an LLPS score or class label."""
    if request.app.state.settings.analysis_queue_backend == "rq":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SEG_ASYNC_ONLY",
                "message": "Submit SEG through the asynchronous analysis endpoint.",
            },
        )
    try:
        sequence = ensure_sequence_length(
            normalize_sequence(payload.sequence),
            request.app.state.settings.analysis_max_sequence_length,
        )
    except SequenceValidationError as error:
        status_code = 413 if error.detail["code"] == "ANALYSIS_SEQUENCE_TOO_LONG" else 422
        raise HTTPException(status_code=status_code, detail=error.detail) from error
    adapter = getattr(request.app.state, "seg_adapter", None)
    if adapter is None:
        return _failure_response(
            getattr(request.app.state, "seg_startup_error_code", "SEG_UNAVAILABLE"),
            getattr(request.app.state, "seg_startup_error_status", None),
        )
    try:
        reply = await adapter.analyze(sequence)
        return SEGResult.model_validate(
            reply.model_dump() if isinstance(reply, SEGResult) else reply
        )
    except Exception as error:
        code, status_code = safe_seg_failure(error)
        logger.warning("SEG annotation failed (%s; %s).", type(error).__name__, code)
        return _failure_response(code, status_code)
