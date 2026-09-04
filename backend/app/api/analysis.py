"""Submit and inspect analysis jobs without binding execution to the HTTP request."""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from app.api.session import analysis_owner
from app.schemas.orchestration import KNOWN_METHODS, AnalysisJob, AnalysisRequest
from app.schemas.persistence import HistoryResponse
from app.services.analysis_jobs import ACTIVE_JOB_STATES, AnalysisServiceError
from app.services.exports import (
    attachment_header,
    fasta_export,
    json_export,
    regions_csv,
    residues_csv,
    summary_csv,
)
from app.services.rate_limits import enforce_rate_limit

logger = logging.getLogger("uvicorn.error.analysis.api")
VALIDATION_MESSAGES = {
    "EMPTY_SELECTED_METHODS": "Select at least one method.",
    "UNKNOWN_METHOD": "A selected method is not supported.",
    "DUPLICATE_SELECTED_METHODS": "Select each method only once.",
    "INVALID_ENSEMBLE_WEIGHTS": "Ensemble weights must be finite values in [0, 1] and sum to one.",
    "INVALID_ENSEMBLE_METHOD": "Only LRECA and FuzDrop may have ensemble weights.",
    "INVALID_SEQUENCE_NAME": "The optional sequence name is invalid.",
    "INVALID_EXTERNAL_RESULT_METHOD": "Only FuzDrop supports imported result references.",
    "WEIGHTED_MODE_REQUIRES_LRECA_AND_FUZDROP": "Weighted mode requires LRECA and FuzDrop.",
    "EXTERNAL_RESULT_METHOD_NOT_SELECTED": "An imported result must belong to a selected method.",
    "INVALID_SEQUENCE_TYPE": "Sequence must be a string.",
    "MULTIPLE_FASTA_RECORDS": "Exactly one protein sequence is accepted per request.",
    "INVALID_FASTA": "The FASTA header is invalid.",
    "EMPTY_SEQUENCE": "Sequence must contain amino acids.",
    "INVALID_AMINO_ACID": "Sequence contains a nonstandard amino acid.",
    "INVALID_ANALYSIS_REQUEST": "The analysis request fields are invalid.",
}
SERVICE_ERRORS = {
    "ANALYSIS_CAPACITY_EXCEEDED": (503, "The analysis service is at capacity."),
    "ANALYSIS_QUEUE_FULL": (503, "The analysis queue is at capacity."),
    "ANALYSIS_CONCURRENT_LIMIT": (
        429,
        "This session has reached its active analysis limit.",
    ),
    "ANALYSIS_QUEUE_UNAVAILABLE": (503, "The analysis queue is currently unavailable."),
    "ANALYSIS_JOB_NOT_FOUND": (404, "The analysis job was not found or has expired."),
    "ANALYSIS_UNAVAILABLE": (503, "The analysis service is currently unavailable."),
    "ANALYSIS_SEQUENCE_TOO_LONG": (
        413,
        "The protein sequence exceeds the configured analysis length limit.",
    ),
    "ANALYSIS_NOT_READY_FOR_EXPORT": (
        409,
        "The analysis must reach a terminal state before it can be exported.",
    ),
    "EXTERNAL_RESULT_NOT_FOUND": (404, "The imported result was not found or has expired."),
    "EXTERNAL_RESULT_SEQUENCE_MISMATCH": (422, "The imported result does not match this sequence."),
    "EXTERNAL_RESULT_STORE_FULL": (503, "The imported result store is at capacity."),
    "EXTERNAL_RESULT_INVALID": (422, "The imported result is invalid."),
}
HISTORY_STATUSES = {
    "queued",
    "running",
    "success",
    "partial_success",
    "failed",
    "unavailable",
    "external_result_required",
    "interrupted",
}


class SafeAnalysisRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                code = next(
                    (
                        item["type"]
                        for item in error.errors()
                        if item["type"] in VALIDATION_MESSAGES
                    ),
                    "INVALID_ANALYSIS_REQUEST",
                )
                raise HTTPException(
                    status_code=422, detail={"code": code, "message": VALIDATION_MESSAGES[code]}
                ) from None

        return safe_handler


router = APIRouter(prefix="/analysis", tags=["analysis"], route_class=SafeAnalysisRoute)


def _service(request: Request):
    service = getattr(request.app.state, "analysis_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ANALYSIS_UNAVAILABLE",
                "message": SERVICE_ERRORS["ANALYSIS_UNAVAILABLE"][1],
            },
        )
    return service


def _safe_failure(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    code = (
        error.code
        if isinstance(error, AnalysisServiceError) and error.code in SERVICE_ERRORS
        else "ANALYSIS_UNAVAILABLE"
    )
    status, message = SERVICE_ERRORS[code]
    logger.warning("Analysis request unavailable (%s; %s).", type(error).__name__, code)
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _ownership_enabled(service) -> bool:
    return getattr(service, "ownership_enforced", False)


def _get_owned(service, job_id: str, owner_id: str) -> AnalysisJob:
    if _ownership_enabled(service):
        return service.get(job_id, owner_id=owner_id)
    return service.get(job_id)


@router.get("/history", response_model=HistoryResponse)
async def analysis_history(
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    method: str | None = Query(default=None),
) -> HistoryResponse:
    service = _service(request)
    if status is not None and status not in HISTORY_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_HISTORY_STATUS", "message": "History status is invalid."},
        )
    if method is not None and method not in KNOWN_METHODS:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_HISTORY_METHOD", "message": "History method is invalid."},
        )
    try:
        return service.list(
            owner_id=owner_id, limit=limit, offset=offset, status=status, method=method
        )
    except Exception as error:
        raise _safe_failure(error) from None


@router.get("", response_model=HistoryResponse)
async def list_analysis(
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    method: str | None = Query(default=None),
) -> HistoryResponse:
    return await analysis_history(request, response, owner_id, limit, offset, status, method)


@router.post("", response_model=AnalysisJob, status_code=202)
async def submit_analysis(
    payload: AnalysisRequest,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> AnalysisJob:
    service = _service(request)
    try:
        await enforce_rate_limit(request, owner_id, "analysis_submit")
        submitted = (
            await service.submit(payload, owner_id=owner_id)
            if _ownership_enabled(service)
            else await service.submit(payload)
        )
        job = AnalysisJob.model_validate(submitted)
        return job.model_copy(update={"normalized_sequence": None}, deep=True)
    except Exception as error:
        raise _safe_failure(error) from None


@router.get("/{job_id}", response_model=AnalysisJob)
async def get_analysis(
    job_id: str,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> AnalysisJob:
    service = _service(request)
    try:
        return AnalysisJob.model_validate(_get_owned(service, job_id, owner_id))
    except Exception as error:
        raise _safe_failure(error) from None


@router.delete("/{job_id}", status_code=204)
async def delete_analysis(
    job_id: str,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> Response:
    service = _service(request)
    try:
        await enforce_rate_limit(request, owner_id, "analysis_delete")
        if _ownership_enabled(service):
            service.delete(job_id, owner_id=owner_id)
        else:
            service.delete(job_id)
        return Response(status_code=204)
    except Exception as error:
        raise _safe_failure(error) from None


def _download(job: AnalysisJob, body: bytes, media_type: str, suffix: str) -> Response:
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": attachment_header(job, suffix)},
    )


def _load_export_job(service, job_id: str, owner_id: str) -> AnalysisJob:
    job = AnalysisJob.model_validate(_get_owned(service, job_id, owner_id))
    if job.status in ACTIVE_JOB_STATES:
        raise AnalysisServiceError(
            "ANALYSIS_NOT_READY_FOR_EXPORT",
            "The analysis must reach a terminal state before it can be exported.",
            409,
        )
    return job


async def _build_export(
    request: Request,
    job_id: str,
    owner_id: str,
    builder: Callable[[AnalysisJob], bytes],
    media_type: str,
    suffix: str,
) -> Response:
    await enforce_rate_limit(request, owner_id, "analysis_export")
    service = _service(request)
    job = await run_in_threadpool(_load_export_job, service, job_id, owner_id)
    body = await run_in_threadpool(builder, job)
    return _download(job, body, media_type, suffix)


@router.get("/{job_id}/export/json")
async def download_json(
    job_id: str,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> Response:
    try:
        return await _build_export(
            request, job_id, owner_id, json_export, "application/json", "_result.json"
        )
    except Exception as error:
        raise _safe_failure(error) from None


@router.get("/{job_id}/export/summary.csv")
async def download_summary_csv(
    job_id: str,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> Response:
    try:
        return await _build_export(
            request, job_id, owner_id, summary_csv, "text/csv", "_summary.csv"
        )
    except Exception as error:
        raise _safe_failure(error) from None


@router.get("/{job_id}/export/residues.csv")
async def download_residues_csv(
    job_id: str,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> Response:
    try:
        return await _build_export(
            request, job_id, owner_id, residues_csv, "text/csv", "_residues.csv"
        )
    except Exception as error:
        raise _safe_failure(error) from None


@router.get("/{job_id}/export/regions.csv")
async def download_regions_csv(
    job_id: str,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> Response:
    try:
        return await _build_export(
            request, job_id, owner_id, regions_csv, "text/csv", "_regions.csv"
        )
    except Exception as error:
        raise _safe_failure(error) from None


@router.get("/{job_id}/export/fasta")
async def download_fasta(
    job_id: str,
    request: Request,
    response: Response,
    owner_id: str = Depends(analysis_owner),
) -> Response:
    try:
        return await _build_export(
            request, job_id, owner_id, fasta_export, "text/plain", ".fasta"
        )
    except Exception as error:
        raise _safe_failure(error) from None
