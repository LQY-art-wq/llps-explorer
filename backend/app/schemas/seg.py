"""SEG is a region annotation method, with no classifier or probability fields."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.analysis import AdapterHealth, AnalysisResult
from app.schemas.coordinates import Region

NonnegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Version = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32, strict=True)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]
SEGErrorCode = Literal[
    "SEG_EXECUTABLE_NOT_FOUND",
    "SEG_EXECUTION_FAILED",
    "SEG_TIMEOUT",
    "SEG_PARSE_ERROR",
    "SEG_INVALID_OUTPUT",
    "SEG_UNAVAILABLE",
]


class SEGAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    sequence: str = Field(strict=True)


class SEGParameters(BaseModel):
    """Explicit CLI parameters; reject values the native tool would silently coerce."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    window: int = Field(default=12, ge=1, le=2147483647, strict=True)
    locut: NonnegativeFloat = 2.2
    hicut: NonnegativeFloat = 2.5
    input_format: Literal["fasta"] = "fasta"
    output_format: Literal["interval"] = "interval"
    parse_seqids: Literal[False] = False

    @model_validator(mode="after")
    def validate_cutoff_order(self):
        if self.locut > self.hicut:
            raise ValueError("SEG locut must not exceed hicut")
        return self


class SEGRegion(Region):
    semantic_type: Literal["region_annotation"] = "region_annotation"

    @model_validator(mode="before")
    @classmethod
    def validate_serialized_length(cls, value):
        if isinstance(value, dict) and "length" in value:
            value = dict(value)
            length = value.pop("length")
            start, end = value.get("start"), value.get("end")
            if type(length) is not int or type(start) is not int or type(end) is not int:
                raise ValueError("region coordinates and length must be integers")
            if length != end - start + 1:
                raise ValueError("region length must equal end - start + 1")
        return value


class SEGErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    code: SEGErrorCode
    message: str


class SEGError(ValueError):
    """Public-safe process/parser failure; callers must supply fixed safe messages."""

    def __init__(self, code: SEGErrorCode, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = SEGErrorDetail(code=code, message=message).model_dump()


class SEGHealth(AdapterHealth):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    method_id: Literal["seg"] = "seg"
    status: Literal["ready", "unavailable", "failed"] = "unavailable"
    available: bool = Field(default=False, strict=True)
    message: str = "The SEG executable is unavailable."
    reason: SEGErrorCode | None = "SEG_UNAVAILABLE"
    implementation: Literal["NCBI segmasker"] = "NCBI segmasker"
    version: Version | None = None
    application_version: Version | None = None
    executable_sha256: Sha256 | None = None
    parameters: SEGParameters | None = None

    @model_validator(mode="after")
    def validate_readiness(self):
        if self.available != (self.status == "ready"):
            raise ValueError("SEG ready status and availability must agree")
        if self.available and (
            self.version is None
            or self.application_version is None
            or self.parameters is None
            or self.reason is not None
        ):
            raise ValueError("ready SEG requires version, parameters, and no failure reason")
        return self


class SEGUnavailableResult(AnalysisResult):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    method_id: Literal["seg"] = "seg"
    method: Literal["seg"] = "seg"
    status: Literal["unavailable", "failed"] = "unavailable"
    message: str = "The SEG executable is unavailable."
    annotation_type: Literal["LCR"] = "LCR"
    semantic_type: Literal["region_annotation"] = "region_annotation"
    implementation: Literal["NCBI segmasker"] = "NCBI segmasker"
    error: SEGErrorDetail = Field(
        default_factory=lambda: SEGErrorDetail(
            code="SEG_UNAVAILABLE", message="The SEG executable is unavailable."
        )
    )
    version: Version | None = None
    application_version: Version | None = None
    executable_sha256: Sha256 | None = None
    parameters: SEGParameters | None = None
    regions: None = None
    coverage: None = None
    region_count: None = None
    longest_region: None = None


def _covered_residues(regions: list[SEGRegion]) -> int:
    """Union count only; never change the native region list or its ordering."""
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


class SEGResult(AnalysisResult):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    method_id: Literal["seg"] = "seg"
    method: Literal["seg"] = "seg"
    status: Literal["success"] = "success"
    message: None = None
    annotation_type: Literal["LCR"] = "LCR"
    semantic_type: Literal["region_annotation"] = "region_annotation"
    implementation: Literal["NCBI segmasker"] = "NCBI segmasker"
    version: Version
    application_version: Version
    sequence_length: int = Field(ge=1, le=2147483647, strict=True)
    sequence_sha256: Sha256
    regions: list[SEGRegion]
    parameters: SEGParameters
    runtime_ms: NonnegativeFloat
    executable_sha256: Sha256 | None = None

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
    def validate_bounds(self):
        if any(region.end > self.sequence_length for region in self.regions):
            raise ValueError("SEG region bounds must stay within the sequence")
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
                raise ValueError("SEG summary values must be derived from native regions")
        return result


SEGResultResponse = Annotated[SEGResult | SEGUnavailableResult, Field(discriminator="status")]
