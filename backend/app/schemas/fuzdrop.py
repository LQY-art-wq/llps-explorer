"""Contracts for unavailable automation and user-declared FuzDrop TSV imports."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.analysis import AdapterHealth, AnalysisResult
from app.schemas.coordinates import Region

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
NonnegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OfficialSiteURL = Literal[
    "https://fuzdrop.bio.unipd.it",
    "https://fuzdrop.bio.unipd.it/",
    "https://fuzdrop.bio.unipd.it/predictor",
]
OFFICIAL_SITE_URL = "https://fuzdrop.bio.unipd.it/predictor"
UNAVAILABLE_REASON = "official_service_requires_browser_verification"
PROGRAMMATIC_ACCESS_ERROR = "FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE"
UNAVAILABLE_MESSAGE = (
    "The official FuzDrop service requires browser verification. "
    "Automatic prediction is unavailable."
)


class FuzDropMode(str, Enum):
    """Reserved audit outcomes; this implementation only exposes mode C."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


IntegrationMode = Literal[
    "documented_api", "supported_http_service", "browser_protected", "unknown"
]
_MODE_INTEGRATION = {
    FuzDropMode.A: "documented_api",
    FuzDropMode.B: "supported_http_service",
    FuzDropMode.C: "browser_protected",
    FuzDropMode.D: "unknown",
}


def _validate_mode(mode: FuzDropMode, integration_mode: IntegrationMode) -> None:
    if _MODE_INTEGRATION[mode] != integration_mode:
        raise ValueError("mode and integration_mode must describe the same audited access class")


class FuzDropAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: str = Field(strict=True)


class FuzDropImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    sequence: str = Field(strict=True)
    source_declaration: Literal["official_fuzdrop_export"]
    coordinate_system: Literal["one_based_inclusive"]
    scores_tsv: str | None = Field(default=None, strict=True)
    regions_tsv: str | None = Field(default=None, strict=True)
    pLLPS: Probability | None = None
    retrieved_at: AwareDatetime | None = None

    @field_validator("retrieved_at", mode="before")
    @classmethod
    def require_declared_timezone(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("retrieved_at must be an ISO datetime with a timezone") from exc
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("retrieved_at must include an explicit timezone")
        return value

    @model_validator(mode="after")
    def require_import_content(self):
        if self.pLLPS is None and not any(
            text is not None and text.strip() for text in (self.scores_tsv, self.regions_tsv)
        ):
            raise ValueError("At least one TSV export or pLLPS value must be supplied")
        return self


class FuzDropErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class FuzDropHealth(AdapterHealth):
    method_id: Literal["fuzdrop"] = "fuzdrop"
    status: Literal["unavailable", "ready", "failed"] = "unavailable"
    message: str = UNAVAILABLE_MESSAGE
    available: bool = Field(default=False, strict=True)
    mode: FuzDropMode = FuzDropMode.C
    integration_mode: IntegrationMode = "browser_protected"
    reason: str | None = UNAVAILABLE_REASON
    manual_import_available: bool = True
    official_site_url: OfficialSiteURL = OFFICIAL_SITE_URL

    @model_validator(mode="after")
    def validate_access_state(self):
        _validate_mode(self.mode, self.integration_mode)
        if self.available and self.mode not in (FuzDropMode.A, FuzDropMode.B):
            raise ValueError("browser-protected or unknown access cannot be available")
        if self.available != (self.status == "ready"):
            raise ValueError("ready status and programmatic availability must agree")
        return self


class FuzDropUnavailableResult(AnalysisResult):
    method_id: Literal["fuzdrop"] = "fuzdrop"
    method: Literal["fuzdrop"] = "fuzdrop"
    status: Literal["unavailable"] = "unavailable"
    message: str = UNAVAILABLE_MESSAGE
    available: Literal[False] = False
    mode: FuzDropMode = FuzDropMode.C
    integration_mode: IntegrationMode = "browser_protected"
    reason: str = UNAVAILABLE_REASON
    manual_import_available: bool = True
    official_site_url: OfficialSiteURL = OFFICIAL_SITE_URL
    error: FuzDropErrorDetail = Field(
        default_factory=lambda: FuzDropErrorDetail(
            code=PROGRAMMATIC_ACCESS_ERROR, message=UNAVAILABLE_MESSAGE
        )
    )
    raw_score: None = None
    calibrated_score: None = None
    label: None = None
    threshold: None = None
    residue_propensity: None = None
    regions: None = None

    @model_validator(mode="after")
    def validate_access_mode(self):
        _validate_mode(self.mode, self.integration_mode)
        return self


class FuzDropResiduePropensity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=1, strict=True)
    aa: str = Field(pattern=r"^[ACDEFGHIKLMNPQRSTVWY]$")
    score: Probability | None
    score_name: Literal["pDP"] = "pDP"
    Sbind: NonnegativeFloat | None
    semantic_type: Literal["residue_propensity"] = "residue_propensity"
    Sbind_semantics: Literal["binding_mode_entropy"] = "binding_mode_entropy"


class FuzDropRegion(Region):
    type: Literal["droplet_promoting_region", "aggregation_hotspot"]
    official_type: Literal["Droplet-promoting region", "Aggregation hot-spot"]
    semantic_type: Literal["region_prediction"] = "region_prediction"

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

    @model_validator(mode="after")
    def validate_native_type_mapping(self):
        expected = {
            "Droplet-promoting region": "droplet_promoting_region",
            "Aggregation hot-spot": "aggregation_hotspot",
        }[self.official_type]
        if self.type != expected:
            raise ValueError("canonical region type must preserve the official type")
        return self


class FuzDropResult(AnalysisResult):
    method_id: Literal["fuzdrop"] = "fuzdrop"
    method: Literal["fuzdrop"] = "fuzdrop"
    status: Literal["success"] = "success"
    message: None = None
    mode: FuzDropMode = FuzDropMode.C
    integration_mode: IntegrationMode = "browser_protected"
    semantic_type: Literal["model_prediction"] = "model_prediction"
    sequence: str = Field(min_length=1, pattern=r"^[ACDEFGHIKLMNPQRSTVWY]+$")
    sequence_length: int = Field(ge=1, strict=True)
    raw_score: Probability | None = None
    calibrated_score: Probability | None = None
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    score_semantics: Literal["official_pLLPS"] = "official_pLLPS"
    label: Literal["P", "N"] | None = None
    label_semantics: str | None = None
    threshold: Literal[0.6] | None = None
    threshold_operator: Literal[">="] | None = None
    residue_propensity: list[FuzDropResiduePropensity] | None = None
    regions: list[FuzDropRegion] | None = None
    source: Literal["manual_import_of_official_result", "official_remote_service"] = (
        "manual_import_of_official_result"
    )
    source_declaration: Literal["official_fuzdrop_export"] | None = "official_fuzdrop_export"
    origin_verification: Literal[
        "user_declared_not_independently_verified", "official_service_response"
    ] = "user_declared_not_independently_verified"
    coordinate_system: Literal["one_based_inclusive"] = "one_based_inclusive"
    coordinate_verification: Literal[
        "user_declared_not_independently_verified", "verified_official_contract"
    ] = "user_declared_not_independently_verified"
    official_site_url: OfficialSiteURL = OFFICIAL_SITE_URL
    service_version: str | None = None
    retrieved_at: AwareDatetime | None = None
    imported_at: AwareDatetime | None = None
    sequence_sha256: Sha256
    raw_tsv_sha256: dict[Literal["scores_tsv", "regions_tsv"], Sha256]
    raw_response_sha256: Sha256 | None = None
    runtime_ms: NonnegativeFloat
    runtime_scope: Literal["local_import_parsing", "official_remote_request"] = (
        "local_import_parsing"
    )
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result_consistency(self):
        _validate_mode(self.mode, self.integration_mode)
        if self.source == "manual_import_of_official_result":
            if (
                self.source_declaration != "official_fuzdrop_export"
                or self.origin_verification != "user_declared_not_independently_verified"
                or self.coordinate_verification != "user_declared_not_independently_verified"
                or self.imported_at is None
                or self.imported_at.utcoffset().total_seconds() != 0
                or self.runtime_scope != "local_import_parsing"
                or self.service_version is not None
                or self.raw_response_sha256 is not None
            ):
                raise ValueError("manual import must retain unverified provenance and local timing")
        elif (
            self.mode not in (FuzDropMode.A, FuzDropMode.B)
            or self.source_declaration is not None
            or self.origin_verification != "official_service_response"
            or self.coordinate_verification != "verified_official_contract"
            or self.imported_at is not None
            or self.retrieved_at is None
            or self.runtime_scope != "official_remote_request"
        ):
            raise ValueError("remote results require an audited programmatic mode and provenance")
        if self.sequence_length != len(self.sequence):
            raise ValueError("sequence_length must match sequence")
        if self.raw_score != self.calibrated_score:
            raise ValueError("uncalibrated scores must be identical")
        if self.raw_score is None:
            if any(
                value is not None
                for value in (
                    self.label,
                    self.label_semantics,
                    self.threshold,
                    self.threshold_operator,
                )
            ):
                raise ValueError("missing pLLPS requires null label and threshold")
        elif (
            self.threshold != 0.6
            or self.threshold_operator != ">="
            or self.label != ("P" if self.raw_score >= 0.6 else "N")
        ):
            raise ValueError("label must follow the official droplet-driver threshold")
        if self.residue_propensity is not None:
            if len(self.residue_propensity) != self.sequence_length:
                raise ValueError("residue propensity must cover the complete sequence")
            for position, residue in enumerate(self.residue_propensity, start=1):
                if residue.position != position or residue.aa != self.sequence[position - 1]:
                    raise ValueError("residue propensity must match sequence and positions")
        if self.regions is not None and any(
            region.end > self.sequence_length for region in self.regions
        ):
            raise ValueError("region bounds must remain within the sequence")
        expected_hash_keys = set()
        if self.residue_propensity is not None:
            expected_hash_keys.add("scores_tsv")
        if self.regions is not None:
            expected_hash_keys.add("regions_tsv")
        if (
            self.source == "manual_import_of_official_result"
            and set(self.raw_tsv_sha256) != expected_hash_keys
        ):
            raise ValueError("raw TSV hashes must match the supplied exports")
        return self


FuzDropSuccessResult = FuzDropResult
FuzDropResultResponse = Annotated[
    FuzDropResult | FuzDropUnavailableResult, Field(discriminator="status")
]
