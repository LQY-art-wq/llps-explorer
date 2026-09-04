"""Validated lifecycle metadata for reusable, user-declared external results."""

import hashlib
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.fuzdrop import FuzDropMode, FuzDropResult
from app.services.sequence_validation import normalize_sequence

ResultId = Annotated[str, Field(pattern=r"^fuzdrop_result_[0-9a-f]{32}$", strict=True)]
SequenceSha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]


def _plain_model_data(value):
    """Revalidate nested models without serializing potentially corrupt DTOs.

    Pydantic's native FuzDrop DTOs do not all revalidate model instances.
    Reading their data into ordinary containers avoids both instance bypasses
    and serializer warnings that could contain private, invalid field values.
    """
    if isinstance(value, BaseModel):
        data = dict(value.__dict__)
        if value.__pydantic_extra__:
            data.update(value.__pydantic_extra__)
        return {key: _plain_model_data(item) for key, item in data.items()}
    if isinstance(value, dict):
        return {key: _plain_model_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_model_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_plain_model_data(item) for item in value)
    return value


def validate_imported_fuzdrop_result(value) -> FuzDropResult:
    """Validate native fields and identity without authenticating their origin."""
    native = FuzDropResult.model_validate(_plain_model_data(value))
    if (
        native.source != "manual_import_of_official_result"
        or native.mode != FuzDropMode.C
        or native.integration_mode != "browser_protected"
    ):
        raise ValueError("Only the audited manual FuzDrop import is supported")
    canonical = normalize_sequence(native.sequence)
    if canonical != native.sequence or hashlib.sha256(canonical.encode("ascii")).hexdigest() != (
        native.sequence_sha256
    ):
        raise ValueError("Imported FuzDrop sequence identity is inconsistent")
    if native.raw_score is None and native.residue_propensity is None and native.regions is None:
        raise ValueError("Imported FuzDrop data must contain an actually supplied result")
    return native


class ImportedCoordinateProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    coordinate_system: Literal["one_based_inclusive"] = "one_based_inclusive"
    coordinate_verification: Literal["user_declared_not_independently_verified"] = (
        "user_declared_not_independently_verified"
    )


class ImportedMethodResult(BaseModel):
    """An expiring reference to a validated import, not independently verified data."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    result_id: ResultId
    method: Literal["fuzdrop"] = "fuzdrop"
    sequence_sha256: SequenceSha256
    sequence_length: int = Field(ge=1, strict=True)
    normalized_result: FuzDropResult
    source: Literal["manual_import_of_official_result"] = "manual_import_of_official_result"
    imported_at: AwareDatetime
    expires_at: AwareDatetime
    coordinate_provenance: ImportedCoordinateProvenance
    validation_status: Literal["valid"] = "valid"

    @field_validator("normalized_result", mode="before")
    @classmethod
    def validate_native_result(cls, value):
        return validate_imported_fuzdrop_result(value)

    @model_validator(mode="after")
    def validate_identity(self):
        native = self.normalized_result
        if (
            self.sequence_sha256 != native.sequence_sha256
            or self.sequence_length != native.sequence_length
            or self.source != native.source
            or self.imported_at != native.imported_at
            or self.coordinate_provenance.coordinate_system != native.coordinate_system
            or self.coordinate_provenance.coordinate_verification != native.coordinate_verification
        ):
            raise ValueError("Imported result envelope must match the native result")
        if (
            self.imported_at.utcoffset().total_seconds() != 0
            or self.expires_at.utcoffset().total_seconds() != 0
            or self.expires_at <= self.imported_at
        ):
            raise ValueError("Imported result lifetime must use UTC and end after import")
        return self


class FuzDropImportResponse(FuzDropResult):
    """Backward-compatible native response with a reusable external-result reference."""

    result_id: ResultId
    expires_at: AwareDatetime
    validation_status: Literal["valid"] = "valid"

    @model_validator(mode="after")
    def validate_expiry(self):
        if (
            self.source != "manual_import_of_official_result"
            or self.imported_at is None
            or self.expires_at.utcoffset().total_seconds() != 0
            or self.expires_at <= self.imported_at
        ):
            raise ValueError("An import reference requires a valid UTC lifetime")
        return self
