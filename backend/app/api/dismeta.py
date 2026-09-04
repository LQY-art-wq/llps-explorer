"""Expose the audited DisMeta blocked boundary without a submission transport."""

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.schemas.dismeta import (
    DISMETA_UNAVAILABLE_MESSAGE,
    DisMetaAnalyzeRequest,
    DisMetaHealth,
    DisMetaUnavailableResult,
)
from app.services.sequence_validation import (
    SequenceValidationError,
    ensure_sequence_length,
    normalize_sequence,
)

logger = logging.getLogger("uvicorn.error.dismeta.api")


class DisMetaRoute(APIRoute):
    """Keep request validation from echoing input sequences or unrecognized fields."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "DISMETA_INVALID_REQUEST",
                        "message": "Supply exactly one protein sequence as a string.",
                    },
                ) from error

        return safe_handler


router = APIRouter(prefix="/methods/dismeta", tags=["dismeta"], route_class=DisMetaRoute)


def _unavailable_result(request: Request, sequence: str) -> DisMetaUnavailableResult:
    return DisMetaUnavailableResult(
        official_site_url=request.app.state.settings.dismeta_official_site_url,
        sequence_length=len(sequence),
        sequence_sha256=hashlib.sha256(sequence.encode("ascii")).hexdigest(),
    )


async def get_dismeta_health(request: Request) -> DisMetaHealth:
    adapter = getattr(request.app.state, "dismeta_adapter", None)
    if adapter is not None:
        try:
            reply = await adapter.healthcheck()
            # The DTO uses revalidate_instances='always'; validate before any
            # serialization could emit warnings containing corrupt private fields.
            DisMetaHealth.model_validate(reply)
        except Exception as error:
            logger.warning("DisMeta health unavailable (%s).", type(error).__name__)
    # Public availability is the audited contract, never free-form adapter diagnostics.
    return DisMetaHealth(
        official_site_url=request.app.state.settings.dismeta_official_site_url,
        message=DISMETA_UNAVAILABLE_MESSAGE,
    )


@router.get("/health", response_model=DisMetaHealth, status_code=503)
async def dismeta_health(request: Request) -> DisMetaHealth:
    return await get_dismeta_health(request)


@router.post("/analyze", response_model=DisMetaUnavailableResult, status_code=503)
async def analyze_dismeta(
    payload: DisMetaAnalyzeRequest, request: Request
) -> DisMetaUnavailableResult:
    """Validate one protein and report the unverified integration contract."""
    try:
        sequence = ensure_sequence_length(
            normalize_sequence(payload.sequence),
            request.app.state.settings.analysis_max_sequence_length,
        )
    except SequenceValidationError as error:
        status_code = 413 if error.detail["code"] == "ANALYSIS_SEQUENCE_TOO_LONG" else 422
        raise HTTPException(status_code=status_code, detail=error.detail) from error
    adapter = getattr(request.app.state, "dismeta_adapter", None)
    if adapter is not None:
        try:
            reply = await adapter.analyze(sequence)
            DisMetaUnavailableResult.model_validate(reply)
        except Exception as error:
            logger.warning("DisMeta annotation unavailable (%s).", type(error).__name__)
    return _unavailable_result(request, sequence)
