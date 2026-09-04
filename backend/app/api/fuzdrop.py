"""Official FuzDrop availability and local user-result import; no submission transport."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from app.api.session import analysis_owner
from app.schemas.fuzdrop import (
    UNAVAILABLE_MESSAGE,
    UNAVAILABLE_REASON,
    FuzDropAnalyzeRequest,
    FuzDropErrorDetail,
    FuzDropHealth,
    FuzDropImportRequest,
    FuzDropMode,
    FuzDropResultResponse,
    FuzDropUnavailableResult,
)
from app.schemas.imported_results import FuzDropImportResponse, ImportedMethodResult
from app.services.fuzdrop_import import FuzDropImportError, import_fuzdrop_result
from app.services.imported_results import ImportedResultError
from app.services.rate_limits import enforce_rate_limit
from app.services.sequence_validation import (
    SequenceValidationError,
    ensure_sequence_length,
    normalize_sequence,
)

logger = logging.getLogger("uvicorn.error.fuzdrop.api")


class FuzDropRoute(APIRoute):
    """Keep validation responses free of full sequences, exports, and extra input."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            is_import = request.url.path.endswith("/import")
            if is_import:
                content_length = request.headers.get("content-length")
                if content_length is not None and content_length.isdecimal():
                    maximum = request.app.state.settings.fuzdrop_import_max_bytes
                    if int(content_length) > maximum:
                        raise HTTPException(
                            status_code=413,
                            detail={
                                "code": "FUZDROP_IMPORT_TOO_LARGE",
                                "message": (
                                    "The import exceeds the configured operational byte limit."
                                ),
                            },
                        )
            try:
                return await handler(request)
            except RequestValidationError as error:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "FUZDROP_INVALID_IMPORT_REQUEST"
                        if is_import
                        else "FUZDROP_INVALID_ANALYZE_REQUEST",
                        "message": "The import declaration or supplied fields are invalid."
                        if is_import
                        else "Supply exactly one protein sequence as a string.",
                    },
                ) from error

        return safe_handler


router = APIRouter(prefix="/methods/fuzdrop", tags=["fuzdrop"], route_class=FuzDropRoute)


async def get_fuzdrop_health(request: Request) -> FuzDropHealth:
    adapter = getattr(request.app.state, "fuzdrop_adapter", None)
    settings = request.app.state.settings
    if adapter is not None:
        try:
            health = FuzDropHealth.model_validate(await adapter.healthcheck())
            manual_available = (
                health.manual_import_available and settings.fuzdrop_manual_import_enabled
            )
            if health.mode == FuzDropMode.C:
                message = UNAVAILABLE_MESSAGE
                reason = UNAVAILABLE_REASON
            elif health.available:
                message = "The official FuzDrop automatic service is available."
                reason = None
            else:
                message = "The official FuzDrop automatic service is unavailable."
                reason = "programmatic_service_unavailable"
            if manual_available:
                message += " Official results can be imported manually."
            return health.model_copy(
                update={
                    "message": message,
                    "reason": reason,
                    "manual_import_available": manual_available,
                }
            )
        except Exception:
            logger.exception("FuzDrop health failed; internal details remain in server logs.")
    return FuzDropHealth(
        official_site_url=settings.fuzdrop_official_site_url,
        manual_import_available=settings.fuzdrop_manual_import_enabled,
    )


def unavailable_result(
    request: Request, result: FuzDropUnavailableResult | None = None
) -> FuzDropUnavailableResult:
    """Expose controlled public failures without forwarding private adapter diagnostics."""
    settings = request.app.state.settings
    common = {
        "official_site_url": settings.fuzdrop_official_site_url,
        "manual_import_available": settings.fuzdrop_manual_import_enabled,
    }
    if result is None or result.mode == FuzDropMode.C:
        return FuzDropUnavailableResult(**common)
    messages = {
        "FUZDROP_TIMEOUT": "The official FuzDrop request exceeded its time limit.",
        "FUZDROP_RATE_LIMITED": "The official FuzDrop service is currently rate limited.",
        "FUZDROP_AUTH_FAILED": "The official FuzDrop service could not authorize the request.",
        "FUZDROP_BAD_RESPONSE": "The official FuzDrop response could not be validated.",
        "FUZDROP_PARSE_ERROR": "The official FuzDrop response could not be parsed.",
        "FUZDROP_SCHEMA_CHANGED": "The official FuzDrop response format is unsupported.",
        "FUZDROP_UNAVAILABLE": "The official FuzDrop service is unavailable.",
        "FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE": "Supported programmatic access is unavailable.",
    }
    code = result.error.code if result.error.code in messages else "FUZDROP_UNAVAILABLE"
    return FuzDropUnavailableResult(
        **common,
        mode=result.mode,
        integration_mode=result.integration_mode,
        reason="programmatic_service_unavailable",
        message=messages[code],
        error=FuzDropErrorDetail(code=code, message=messages[code]),
    )


@router.get("/health", response_model=FuzDropHealth, responses={503: {"model": FuzDropHealth}})
async def fuzdrop_health(request: Request):
    """Report the audited browser-protected mode without contacting the official site."""
    health = await get_fuzdrop_health(request)
    return JSONResponse(
        status_code=200 if health.available else 503, content=health.model_dump(mode="json")
    )


@router.post(
    "/analyze",
    response_model=FuzDropResultResponse,
    responses={503: {"model": FuzDropUnavailableResult}},
)
async def analyze_fuzdrop(payload: FuzDropAnalyzeRequest, request: Request):
    try:
        sequence = ensure_sequence_length(
            normalize_sequence(payload.sequence),
            request.app.state.settings.analysis_max_sequence_length,
        )
    except SequenceValidationError as error:
        status_code = 413 if error.detail["code"] == "ANALYSIS_SEQUENCE_TOO_LONG" else 422
        raise HTTPException(status_code=status_code, detail=error.detail) from error
    adapter = getattr(request.app.state, "fuzdrop_adapter", None)
    if adapter is None:
        result = unavailable_result(request)
    else:
        try:
            result = await adapter.analyze(sequence)
        except Exception:
            logger.exception("FuzDrop analysis failed; internal details remain in server logs.")
            result = unavailable_result(request)
    if result.status == "unavailable":
        result = unavailable_result(request, result)
        return JSONResponse(status_code=503, content=result.model_dump(mode="json"))
    return result


@router.post("/import", response_model=FuzDropImportResponse)
async def import_fuzdrop(
    payload: FuzDropImportRequest,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> FuzDropImportResponse:
    """Parse an explicitly user-supplied official export entirely inside this backend."""
    await enforce_rate_limit(request, owner_id, "fuzdrop_import")
    settings = request.app.state.settings
    if not settings.fuzdrop_manual_import_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "FUZDROP_MANUAL_IMPORT_DISABLED",
                "message": "Manual FuzDrop result import is disabled by server configuration.",
            },
        )
    try:
        normalized_for_limit = normalize_sequence(payload.sequence)
    except SequenceValidationError:
        # Preserve the established FuzDrop import error contract below for
        # malformed sequence content; this preflight only enforces payload size.
        normalized_for_limit = None
    if normalized_for_limit is not None:
        try:
            ensure_sequence_length(normalized_for_limit, settings.analysis_max_sequence_length)
        except SequenceValidationError as error:
            raise HTTPException(status_code=413, detail=error.detail) from error
    try:
        result = await run_in_threadpool(
            import_fuzdrop_result,
            payload,
            max_bytes=settings.fuzdrop_import_max_bytes,
            official_site_url=settings.fuzdrop_official_site_url,
        )
    except FuzDropImportError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except Exception as error:
        logger.exception("FuzDrop import failed; internal details remain in server logs.")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "FUZDROP_IMPORT_FAILED",
                "message": "FuzDrop result import could not be completed.",
            },
        ) from error
    if result.sequence_length > settings.analysis_max_sequence_length:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "ANALYSIS_SEQUENCE_TOO_LONG",
                "message": "The protein sequence exceeds the configured analysis length limit.",
            },
        )
    try:
        store = request.app.state.imported_result_store
        if getattr(store, "ownership_enforced", False):
            imported_value = await run_in_threadpool(store.put, result, owner_id)
        else:
            imported_value = await run_in_threadpool(store.put, result)
        imported = ImportedMethodResult.model_validate(imported_value)
        return FuzDropImportResponse(
            **imported.normalized_result.model_dump(),
            result_id=imported.result_id,
            expires_at=imported.expires_at,
            validation_status=imported.validation_status,
        )
    except ImportedResultError as error:
        raise HTTPException(status_code=error.http_status, detail=error.detail) from error
    except Exception as error:
        # A storage failure must not expose or log the retained scientific payload.
        logger.warning("FuzDrop import storage failed (%s).", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "EXTERNAL_RESULT_STORE_FULL",
                "message": "Imported result storage is unavailable or at capacity.",
            },
        ) from error
