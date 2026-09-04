"""Offline parsing of user-declared exports; never contacts the FuzDrop service."""

import hashlib
import math
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.schemas.fuzdrop import (
    OFFICIAL_SITE_URL,
    FuzDropImportRequest,
    FuzDropRegion,
    FuzDropResiduePropensity,
    FuzDropResult,
    OfficialSiteURL,
)
from app.services.sequence_validation import SequenceValidationError, normalize_sequence

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_INTEGER = re.compile(r"[0-9]+\Z")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_REGION_TYPES = {
    "Droplet-promoting region": "droplet_promoting_region",
    "Aggregation hot-spot": "aggregation_hotspot",
}


class FuzDropImportError(ValueError):
    """A safe public error with no raw input, URL, or internal-path echo."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        row: int | None = None,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail: dict[str, str | int] = {"code": code, "message": message}
        if field is not None:
            self.detail["field"] = field
        if row is not None:
            self.detail["row"] = row


def _rows(text: str, header: tuple[str, ...], field: str) -> list[list[str]]:
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if "\r" in normalized:
        raise FuzDropImportError(
            "FUZDROP_PARSE_ERROR", "TSV must use LF or CRLF line endings.", field=field
        )
    lines = normalized.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines or tuple(lines[0].split("\t")) != header:
        raise FuzDropImportError(
            "FUZDROP_SCHEMA_CHANGED", "TSV columns do not match the official export.", field=field
        )
    rows = []
    for row_number, line in enumerate(lines[1:], start=2):
        cells = line.split("\t")
        if len(cells) != len(header):
            raise FuzDropImportError(
                "FUZDROP_PARSE_ERROR",
                "TSV row has an invalid number of columns.",
                field=field,
                row=row_number,
            )
        rows.append(cells)
    return rows


def _coordinate(cell: str, *, field: str, row: int) -> int:
    token = cell.strip()
    if not _INTEGER.fullmatch(token):
        raise FuzDropImportError(
            "FUZDROP_INVALID_COORDINATE",
            "Coordinates must be positive integers.",
            field=field,
            row=row,
        )
    # Bound integer parsing independently of Python's configurable digit limit.
    if len(token) > 12:
        raise FuzDropImportError(
            "FUZDROP_INVALID_COORDINATE",
            "Coordinate exceeds the supported sequence.",
            field=field,
            row=row,
        )
    value = int(token)
    if value < 1:
        raise FuzDropImportError(
            "FUZDROP_INVALID_COORDINATE",
            "Coordinates must be positive integers.",
            field=field,
            row=row,
        )
    return value


def _score(cell: str, *, probability: bool, field: str, row: int) -> float | None:
    token = cell.strip()
    # The official optional-toString exporter serializes missing numeric cells
    # as literal "undefined". Empty cells are an explicit import tolerance.
    if token in {"", "undefined"}:
        return None
    if not _NUMBER.fullmatch(token):
        raise FuzDropImportError(
            "FUZDROP_INVALID_NUMERIC_VALUE",
            "Numeric cells must be finite numbers or missing.",
            field=field,
            row=row,
        )
    try:
        exact_value = Decimal(token)
    except InvalidOperation as exc:
        raise FuzDropImportError(
            "FUZDROP_INVALID_NUMERIC_VALUE",
            "Numeric cells must be finite numbers or missing.",
            field=field,
            row=row,
        ) from exc
    # Check the supplied decimal before float rounding can turn a negative
    # value into -0.0 or a value just above one into 1.0.
    if exact_value < 0 or (probability and exact_value > 1):
        raise FuzDropImportError(
            "FUZDROP_SCORE_OUT_OF_RANGE",
            "Numeric value is outside its valid range.",
            field=field,
            row=row,
        )
    value = float(token)
    if not math.isfinite(value):
        raise FuzDropImportError(
            "FUZDROP_INVALID_NUMERIC_VALUE",
            "Numeric cells must be finite numbers or missing.",
            field=field,
            row=row,
        )
    return value


def _residues(text: str, sequence: str) -> list[FuzDropResiduePropensity]:
    rows = _rows(text, ("position", "residue", "pDP", "Sbind"), "scores_tsv")
    if len(rows) != len(sequence):
        raise FuzDropImportError(
            "FUZDROP_RESIDUE_COUNT_MISMATCH",
            "The scores export must contain exactly one row per sequence residue.",
            field="scores_tsv",
        )
    result = []
    for position, cells in enumerate(rows, start=1):
        row = position + 1
        if _coordinate(cells[0], field="position", row=row) != position:
            raise FuzDropImportError(
                "FUZDROP_INVALID_COORDINATE",
                "Residue positions must be consecutive from 1 to N.",
                field="position",
                row=row,
            )
        if cells[1] != sequence[position - 1]:
            raise FuzDropImportError(
                "FUZDROP_SEQUENCE_MISMATCH",
                "Exported residues do not match the supplied sequence.",
                field="residue",
                row=row,
            )
        result.append(
            FuzDropResiduePropensity(
                position=position,
                aa=cells[1],
                score=_score(cells[2], probability=True, field="pDP", row=row),
                Sbind=_score(cells[3], probability=False, field="Sbind", row=row),
            )
        )
    return result


def _regions(text: str, length: int) -> list[FuzDropRegion]:
    rows = _rows(text, ("type", "start", "end"), "regions_tsv")
    result = []
    for row, (region_type, start_cell, end_cell) in enumerate(rows, start=2):
        if region_type not in _REGION_TYPES:
            raise FuzDropImportError(
                "FUZDROP_INVALID_REGION_TYPE",
                "Region type is not an official exported type.",
                field="type",
                row=row,
            )
        start = _coordinate(start_cell, field="start", row=row)
        end = _coordinate(end_cell, field="end", row=row)
        if not 1 <= start <= end <= length:
            raise FuzDropImportError(
                "FUZDROP_INVALID_COORDINATE",
                "Region bounds must lie within the supplied sequence.",
                field="regions_tsv",
                row=row,
            )
        result.append(
            FuzDropRegion(
                type=_REGION_TYPES[region_type], official_type=region_type, start=start, end=end
            )
        )
    return result


def import_fuzdrop_result(
    payload: FuzDropImportRequest | dict,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    official_site_url: OfficialSiteURL = OFFICIAL_SITE_URL,
) -> FuzDropResult:
    """Validate supplied TSV data only; success never authenticates its origin."""
    started = time.perf_counter()
    try:
        request = FuzDropImportRequest.model_validate(payload)
    except ValidationError as exc:
        raise FuzDropImportError(
            "FUZDROP_INVALID_IMPORT_REQUEST",
            "The import declaration or supplied fields are invalid.",
        ) from exc
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    supplied_texts = [request.sequence, request.scores_tsv, request.regions_tsv]
    try:
        encoded_size = sum(len(text.encode("utf-8")) for text in supplied_texts if text is not None)
    except UnicodeEncodeError as exc:
        raise FuzDropImportError(
            "FUZDROP_INVALID_TEXT_ENCODING", "Import text must be valid UTF-8."
        ) from exc
    if encoded_size > max_bytes:
        raise FuzDropImportError(
            "FUZDROP_IMPORT_TOO_LARGE",
            "The import exceeds the configured size limit.",
            status_code=413,
        )
    try:
        sequence = normalize_sequence(request.sequence)
    except SequenceValidationError as exc:
        raise FuzDropImportError(
            "FUZDROP_INVALID_SEQUENCE",
            "Supply exactly one valid standard-amino-acid sequence.",
            field="sequence",
        ) from exc
    residues = _residues(request.scores_tsv, sequence) if request.scores_tsv is not None else None
    regions = (
        _regions(request.regions_tsv, len(sequence)) if request.regions_tsv is not None else None
    )
    global_score = request.pLLPS
    return FuzDropResult(
        sequence=sequence,
        sequence_length=len(sequence),
        raw_score=global_score,
        calibrated_score=global_score,
        label=None if global_score is None else ("P" if global_score >= 0.6 else "N"),
        label_semantics=None
        if global_score is None
        else (
            "P meets the official droplet-driver threshold; "
            "N is below that threshold and does not establish absence of condensation."
        ),
        threshold=None if global_score is None else 0.6,
        threshold_operator=None if global_score is None else ">=",
        residue_propensity=residues,
        regions=regions,
        official_site_url=official_site_url,
        retrieved_at=request.retrieved_at,
        imported_at=datetime.now(timezone.utc),
        sequence_sha256=hashlib.sha256(sequence.encode("ascii")).hexdigest(),
        raw_tsv_sha256={
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in (
                ("scores_tsv", request.scores_tsv),
                ("regions_tsv", request.regions_tsv),
            )
            if text is not None
        },
        runtime_ms=(time.perf_counter() - started) * 1000,
        warnings=[
            "The imported data origin is user-declared and has not been independently verified.",
            "The coordinate convention is user-declared; no genuine official export was available "
            "to independently verify native indexing or endpoint inclusivity.",
        ],
    )
