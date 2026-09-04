"""Validated orchestration envelopes without changing native scientific results."""

import hashlib
import math
import unicodedata
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.schemas.analysis import MethodId
from app.schemas.fuzdrop import FuzDropResult
from app.schemas.lreca import LRECAResult
from app.schemas.seg import SEGResult
from app.services.sequence_validation import SequenceValidationError, normalize_sequence

PredictionMode = Literal["independent", "weighted"]
ExecutionStatus = Literal[
    "queued", "running", "success", "failed", "unavailable", "external_result_required", "skipped"
]
IntegrationMode = Literal[
    "local_automatic", "remote_automatic", "manual_import", "integration_blocked"
]
JobStatus = Literal[
    "queued",
    "running",
    "success",
    "partial_success",
    "failed",
    "unavailable",
    "external_result_required",
    "interrupted",
]
FiniteNonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Threshold = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]
OpaqueId = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", strict=True)
]
KNOWN_METHODS = frozenset(("lreca", "fuzdrop", "seg", "dismeta"))
ENSEMBLE_METHODS = frozenset(("lreca", "fuzdrop"))
WEIGHT_SUM_ABSOLUTE_TOLERANCE = 1e-9


def validate_selected_methods(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PydanticCustomError("EMPTY_SELECTED_METHODS", "Select at least one supported method.")
    if any(type(method) is not str or method not in KNOWN_METHODS for method in value):
        raise PydanticCustomError("UNKNOWN_METHOD", "A selected method is unsupported.")
    if len(value) != len(set(value)):
        raise PydanticCustomError("DUPLICATE_SELECTED_METHODS", "Select each method only once.")
    return list(value)


def validate_ensemble_weights(value: object) -> dict[str, float]:
    """Validate, but never normalize, the two predictor weights."""
    if not isinstance(value, Mapping):
        raise PydanticCustomError("INVALID_ENSEMBLE_WEIGHTS", "Supply both predictor weights.")
    if any(key not in ENSEMBLE_METHODS for key in value):
        raise PydanticCustomError(
            "INVALID_ENSEMBLE_METHOD", "Only LRECA and FuzDrop can have prediction weights."
        )
    if set(value) != ENSEMBLE_METHODS:
        raise PydanticCustomError("INVALID_ENSEMBLE_WEIGHTS", "Supply both predictor weights.")
    for weight in value.values():
        if type(weight) not in (int, float) or not 0 <= weight <= 1 or not math.isfinite(weight):
            raise PydanticCustomError(
                "INVALID_ENSEMBLE_WEIGHTS", "Weights must be finite numbers from zero to one."
            )
    if not math.isclose(
        math.fsum(value.values()), 1.0, rel_tol=0.0, abs_tol=WEIGHT_SUM_ABSOLUTE_TOLERANCE
    ):
        raise PydanticCustomError("INVALID_ENSEMBLE_WEIGHTS", "Weights must sum to one.")
    return {key: float(weight) for key, weight in value.items()}


def validate_sequence_name(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or len(value) > 128
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise PydanticCustomError(
            "INVALID_SEQUENCE_NAME", "Sequence name must be safe text of at most 128 characters."
        )
    return value.strip() or None


class FrozenDTO(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", validate_default=True
    )


class ExternalResultReference(FrozenDTO):
    result_id: OpaqueId


class AnalysisRequest(FrozenDTO):
    sequence: str = Field(strict=True)
    sequence_name: str | None = Field(default=None, max_length=128, strict=True)
    selected_methods: list[MethodId] = Field(min_length=1)
    prediction_mode: PredictionMode = "independent"
    weights: dict[str, float] | None = None
    external_results: dict[str, ExternalResultReference] = Field(default_factory=dict)

    @field_validator("sequence", mode="before")
    @classmethod
    def normalize_input_sequence(cls, value):
        try:
            return normalize_sequence(value)
        except SequenceValidationError as error:
            raise PydanticCustomError(error.detail["code"], error.detail["message"]) from error

    @field_validator("sequence_name", mode="before")
    @classmethod
    def safe_sequence_name(cls, value):
        return validate_sequence_name(value)

    @field_validator("selected_methods", mode="before")
    @classmethod
    def known_unique_methods(cls, value):
        return validate_selected_methods(value)

    @field_validator("weights", mode="before")
    @classmethod
    def strict_weights(cls, value):
        return None if value is None else validate_ensemble_weights(value)

    @field_validator("external_results", mode="before")
    @classmethod
    def supported_external_results(cls, value):
        if not isinstance(value, dict) or any(key != "fuzdrop" for key in value):
            raise PydanticCustomError(
                "INVALID_EXTERNAL_RESULT_METHOD", "Only FuzDrop accepts external result references."
            )
        return value

    @model_validator(mode="after")
    def validate_routing(self):
        if self.prediction_mode == "weighted":
            if not ENSEMBLE_METHODS.issubset(self.selected_methods):
                raise PydanticCustomError(
                    "WEIGHTED_MODE_REQUIRES_LRECA_AND_FUZDROP",
                    "Weighted mode requires both LRECA and FuzDrop to be selected.",
                )
            if self.weights is None:
                raise PydanticCustomError(
                    "INVALID_ENSEMBLE_WEIGHTS", "Supply both predictor weights."
                )
        elif self.weights is not None:
            raise PydanticCustomError(
                "INVALID_ENSEMBLE_WEIGHTS", "Independent mode does not accept prediction weights."
            )
        if any(method not in self.selected_methods for method in self.external_results):
            raise PydanticCustomError(
                "EXTERNAL_RESULT_METHOD_NOT_SELECTED", "Select the referenced external method."
            )
        return self


class StructuredError(FrozenDTO):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", strict=True)
    message: str = Field(strict=True)


class MethodExecution(FrozenDTO):
    method: MethodId
    status: ExecutionStatus
    integration_mode: IntegrationMode
    runtime_ms: FiniteNonnegative = 0.0
    result: LRECAResult | FuzDropResult | SEGResult | None = None
    error: StructuredError | None = None
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("result", mode="before")
    @classmethod
    def revalidate_native_result(cls, value):
        return value.model_dump(warnings=False) if isinstance(value, BaseModel) else value

    @model_validator(mode="after")
    def validate_result_identity(self):
        if self.status == "success":
            if self.result is None or self.result.method != self.method or self.error is not None:
                raise ValueError("Successful method execution requires its matching native result")
        elif self.result is not None:
            raise ValueError("An unsuccessful method execution cannot carry a success result")
        return self


class EnsembleResult(FrozenDTO):
    status: Literal["success", "unavailable"]
    score: FiniteNonnegative | None = None
    label: Literal["P", "N"] | None = None
    weights: dict[str, float]
    threshold: Threshold
    threshold_operator: Literal[">="] = ">="
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    interpretation_status: Literal["experimental_weighted_score"] = "experimental_weighted_score"
    reason: str | None = None

    @field_validator("weights", mode="before")
    @classmethod
    def strict_weights(cls, value):
        return validate_ensemble_weights(value)

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.status == "success":
            if self.score is None or self.reason is not None:
                raise ValueError("A successful ensemble requires a score and no unavailable reason")
            if self.label != ("P" if self.score >= self.threshold else "N"):
                raise ValueError("Ensemble label must follow its configured threshold")
        elif self.score is not None or self.label is not None or not self.reason:
            raise ValueError("An unavailable ensemble requires a reason and null score/label")
        return self


class SequenceMetadata(FrozenDTO):
    name: str | None = Field(default=None, max_length=128, strict=True)
    length: int = Field(ge=1, strict=True)
    sha256: Sha256

    @field_validator("name", mode="before")
    @classmethod
    def safe_sequence_name(cls, value):
        return validate_sequence_name(value)


class AnalysisJob(FrozenDTO):
    job_id: OpaqueId
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    expires_at: AwareDatetime
    status: JobStatus
    sequence: SequenceMetadata
    normalized_sequence: str | None = Field(
        default=None, min_length=1, pattern=r"^[ACDEFGHIKLMNPQRSTVWY]+$"
    )
    selected_methods: list[MethodId]
    prediction_mode: PredictionMode = "independent"
    weights: dict[str, float] | None = None
    methods: dict[MethodId, MethodExecution]
    ensemble: EnsembleResult | None = None
    warnings: list[str] = Field(default_factory=list)
    result_schema_version: Literal["1.0"] = "1.0"

    @field_validator("selected_methods", mode="before")
    @classmethod
    def known_unique_methods(cls, value):
        return validate_selected_methods(value)

    @field_validator("weights", mode="before")
    @classmethod
    def strict_weights(cls, value):
        return None if value is None else validate_ensemble_weights(value)

    @model_validator(mode="after")
    def validate_job_identity(self):
        if set(self.methods) != set(self.selected_methods) or any(
            method != execution.method for method, execution in self.methods.items()
        ):
            raise ValueError("Job methods must match the selected methods and execution identities")
        if self.updated_at < self.created_at or self.expires_at <= self.created_at:
            raise ValueError("Job timestamps must have a valid creation/update/expiry order")
        if self.completed_at is not None and (
            self.completed_at < self.created_at or self.completed_at > self.updated_at
        ):
            raise ValueError("completed_at must fall within the job lifetime")
        if self.normalized_sequence is not None and (
            len(self.normalized_sequence) != self.sequence.length
            or hashlib.sha256(self.normalized_sequence.encode("ascii")).hexdigest()
            != self.sequence.sha256
        ):
            raise ValueError("Stored sequence must match the persisted sequence identity")
        if self.prediction_mode == "independent":
            if self.weights is not None or self.ensemble is not None:
                raise ValueError("Independent jobs cannot contain weights or an ensemble")
        elif not ENSEMBLE_METHODS.issubset(self.selected_methods) or self.weights is None:
            raise ValueError("Weighted jobs require both selected predictors and valid weights")
        if self.ensemble is not None and self.ensemble.weights != self.weights:
            raise ValueError("Ensemble weights must preserve the requested job weights")
        return self
