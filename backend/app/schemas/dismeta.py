"""DisMeta annotation contracts; the current integration can only report unavailable.

DisMetaResult is a normalized, contract-only DTO. No current route, importer, or
predictor constructs successful DisMeta results from user-supplied regions.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.analysis import AdapterHealth, AnalysisResult
from app.schemas.coordinates import Region

DISMETA_UNAVAILABLE_MESSAGE = (
    "DisMeta integration is blocked until a supported invocation and result contract is verified."
)
DisMetaOfficialURL = Literal[
    "https://montelionelab.chem.rpi.edu/dismeta/",
    "https://montelionelab.chem.rpi.edu/dismeta",
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]


class DisMetaAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    sequence: str = Field(strict=True)


class DisMetaErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    code: Literal["DISMETA_UNAVAILABLE"] = "DISMETA_UNAVAILABLE"
    message: str = DISMETA_UNAVAILABLE_MESSAGE


class DisMetaHealth(AdapterHealth):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    method_id: Literal["dismeta"] = "dismeta"
    status: Literal["unavailable"] = "unavailable"
    available: Literal[False] = False
    automatic_status: Literal["unavailable"] = "unavailable"
    manual_import_supported: Literal[False] = False
    integration_mode: Literal["unknown"] = "unknown"
    audit_mode: Literal["F"] = "F"
    decision: Literal["INTEGRATION_BLOCKED"] = "INTEGRATION_BLOCKED"
    reason: Literal["integration_contract_unverified"] = "integration_contract_unverified"
    official_site_url: DisMetaOfficialURL = "https://montelionelab.chem.rpi.edu/dismeta/"
    version: None = None
    message: str = DISMETA_UNAVAILABLE_MESSAGE


class DisMetaUnavailableResult(AnalysisResult):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    method_id: Literal["dismeta"] = "dismeta"
    method: Literal["dismeta"] = "dismeta"
    status: Literal["unavailable"] = "unavailable"
    message: str = DISMETA_UNAVAILABLE_MESSAGE
    annotation_type: Literal["IDR"] = "IDR"
    semantic_type: Literal["region_annotation"] = "region_annotation"
    implementation: Literal["DisMeta"] = "DisMeta"
    error: DisMetaErrorDetail = Field(default_factory=DisMetaErrorDetail)
    available: Literal[False] = False
    automatic_status: Literal["unavailable"] = "unavailable"
    manual_import_supported: Literal[False] = False
    integration_mode: Literal["unknown"] = "unknown"
    audit_mode: Literal["F"] = "F"
    decision: Literal["INTEGRATION_BLOCKED"] = "INTEGRATION_BLOCKED"
    reason: Literal["integration_contract_unverified"] = "integration_contract_unverified"
    official_site_url: DisMetaOfficialURL = "https://montelionelab.chem.rpi.edu/dismeta/"
    version: None = None
    sequence_length: int | None = Field(default=None, ge=1, strict=True)
    sequence_sha256: Sha256 | None = None
    regions: None = None
    coverage: None = None
    region_count: None = None
    longest_region: None = None

    @model_validator(mode="after")
    def validate_sequence_diagnostics(self):
        if (self.sequence_length is None) != (self.sequence_sha256 is None):
            raise ValueError("DisMeta sequence length and hash must be supplied together")
        return self


class DisMetaRegion(Region):
    semantic_type: Literal["region_annotation"] = "region_annotation"

    @model_validator(mode="before")
    @classmethod
    def validate_serialized_length(cls, value):
        if isinstance(value, dict) and "length" in value:
            value = dict(value)
            length = value.pop("length")
            start, end = value.get("start"), value.get("end")
            if type(length) is not int or type(start) is not int or type(end) is not int:
                raise ValueError("IDR coordinates and length must be integers")
            if length != end - start + 1:
                raise ValueError("IDR length must equal end - start + 1")
        return value


def _covered_residues(regions: list[DisMetaRegion]) -> int:
    """Count the union without merging, filtering, or reordering returned regions."""
    if not regions:
        return 0
    intervals = sorted((region.start, region.end) for region in regions)
    start, end = intervals[0]
    covered = 0
    for next_start, next_end in intervals[1:]:
        if next_start <= end + 1:
            end = max(end, next_end)
        else:
            covered += end - start + 1
            start, end = next_start, next_end
    return covered + end - start + 1


class DisMetaResult(AnalysisResult):
    """Future normalized contract only, not a native format or import API.

    These coordinates describe already-normalized regions. No native origin,
    consensus threshold, score scale, or version is inferred by this DTO.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    method_id: Literal["dismeta"] = "dismeta"
    method: Literal["dismeta"] = "dismeta"
    status: Literal["success"] = "success"
    message: None = None
    annotation_type: Literal["IDR"] = "IDR"
    semantic_type: Literal["region_annotation"] = "region_annotation"
    implementation: Literal["DisMeta"] = "DisMeta"
    sequence_length: int = Field(ge=1, strict=True)
    sequence_sha256: Sha256
    regions: list[DisMetaRegion]
    runtime_ms: float = Field(ge=0, strict=True, allow_inf_nan=False)

    @computed_field
    @property
    def coverage(self) -> float:
        return _covered_residues(self.regions) / self.sequence_length

    @computed_field
    @property
    def region_count(self) -> int:
        return len(self.regions)

    @computed_field
    @property
    def longest_region(self) -> int:
        return max((region.length for region in self.regions), default=0)

    @model_validator(mode="after")
    def validate_region_bounds(self):
        if any(region.end > self.sequence_length for region in self.regions):
            raise ValueError("DisMeta normalized region must remain within the sequence")
        return self

    @model_validator(mode="wrap")
    @classmethod
    def validate_serialized_summaries(cls, value, handler):
        summaries = {}
        if isinstance(value, dict):
            value = dict(value)
            for name in ("coverage", "region_count", "longest_region"):
                if name in value:
                    summaries[name] = value.pop(name)
        result = handler(value)
        for name, provided in summaries.items():
            if name == "coverage":
                valid_type = type(provided) in (int, float) and 0 <= provided <= 1
            else:
                valid_type = type(provided) is int
            if not valid_type or provided != getattr(result, name):
                raise ValueError("DisMeta summaries must agree with the normalized regions")
        return result
