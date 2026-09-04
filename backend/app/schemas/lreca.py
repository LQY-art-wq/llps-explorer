"""Public contracts for the audited human-specific LRECA model."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.analysis import AdapterHealth, AnalysisResult
from app.schemas.coordinates import Region

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonnegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
AminoAcid = Annotated[str, Field(pattern=r"^[ACDEFGHIKLMNPQRSTVWY]$")]
CheckpointFilename = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
LRECARepository = Literal["https://github.com/ai-phasepro/LRECA"]
DeviceName = Annotated[str, Field(pattern=r"^(?:cpu|cuda(?::[0-9]+)?)$", strict=True)]


class LRECAAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: str = Field(strict=True)
    include_attribution: bool = Field(default=True, strict=True)
    include_kde: bool = Field(default=True, strict=True)


class LRECAModelMetadata(BaseModel):
    """Private startup identity; never reference this DTO in HTTP contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: LRECARepository
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    model_variant: Literal["human_specific"] = "human_specific"
    dataset5_mapping_status: Literal["unconfirmed"] = "unconfirmed"
    checkpoint: CheckpointFilename
    checkpoint_path: str
    configured_checkpoint_path: str
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_size_bytes: int = Field(gt=0, strict=True)
    source_files: dict[str, Any] | None = None
    runtime: dict[str, Any] | None = None


class PublicLRECAModelMetadata(BaseModel):
    """Explicit HTTP allowlist: no local paths, source maps, or runtime objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: LRECARepository
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    model_variant: Literal["human_specific"] = "human_specific"
    dataset5_mapping_status: Literal["unconfirmed"] = "unconfirmed"
    checkpoint: CheckpointFilename
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_size_bytes: int = Field(gt=0, strict=True)

    @classmethod
    def from_private(cls, metadata: LRECAModelMetadata) -> "PublicLRECAModelMetadata":
        return cls(
            repository=metadata.repository,
            commit=metadata.commit,
            model_variant=metadata.model_variant,
            dataset5_mapping_status=metadata.dataset5_mapping_status,
            checkpoint=metadata.checkpoint,
            checkpoint_sha256=metadata.checkpoint_sha256,
            checkpoint_size_bytes=metadata.checkpoint_size_bytes,
        )


class ResidueAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=1, strict=True)
    aa: AminoAcid
    score: Probability
    semantic_type: Literal["model_attribution"] = "model_attribution"


class TopResidue(ResidueAttribution):
    rank: int = Field(ge=1, strict=True)


class LRECACriticalRegion(Region):
    score: FiniteFloat
    is_primary: bool
    semantic_type: Literal["derived_hotspot"] = "derived_hotspot"

    @model_validator(mode="before")
    @classmethod
    def validate_serialized_length(cls, value):
        # Accept an existing API interval without trusting its derived length.
        if isinstance(value, dict) and "length" in value:
            value = dict(value)
            length = value.pop("length")
            start, end = value.get("start"), value.get("end")
            if type(length) is not int or type(start) is not int or type(end) is not int:
                raise ValueError("region coordinates and length must be integers")
            if length != end - start + 1:
                raise ValueError("region length must equal end - start + 1")
        return value


class LRECAKDE(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["success", "unavailable"]
    semantic_type: Literal["derived_hotspot"] = "derived_hotspot"
    values: list[FiniteFloat] | None
    values_semantics: str
    prominence: NonnegativeFloat
    regions: list[LRECACriticalRegion] | None
    bandwidth: NonnegativeFloat | None = None
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    input_precision: Literal["official_csv_4_decimal_places"] | None = None
    runtime_ms: NonnegativeFloat | None = None

    @model_validator(mode="after")
    def validate_availability(self):
        if self.status == "success":
            if self.values is None or self.regions is None:
                raise ValueError("successful KDE requires density values and regions")
        elif self.values is not None or self.regions is not None:
            raise ValueError("unavailable KDE cannot expose invented values or regions")
        return self


class LRECAHealth(AdapterHealth):
    method_id: Literal["lreca"] = "lreca"
    model_variant: Literal["human_specific"] = "human_specific"
    device: DeviceName | None = None
    loaded: bool = False
    metadata: PublicLRECAModelMetadata | None = None


class LRECAResult(AnalysisResult):
    method_id: Literal["lreca"] = "lreca"
    method: Literal["lreca"] = "lreca"
    status: Literal["success"] = "success"
    message: None = None
    semantic_type: Literal["model_prediction"] = "model_prediction"
    model_variant: Literal["human_specific"] = "human_specific"
    dataset5_mapping_status: Literal["unconfirmed"] = "unconfirmed"
    repository_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint: CheckpointFilename
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: PublicLRECAModelMetadata
    sequence: str = Field(min_length=1, pattern=r"^[ACDEFGHIKLMNPQRSTVWY]+$")
    sequence_length: int = Field(ge=1, strict=True)
    raw_score: Probability
    calibrated_score: Probability
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    score_semantics: Literal["uncalibrated_positive_class_softmax"] = (
        "uncalibrated_positive_class_softmax"
    )
    positive_class_index: Literal[1] = 1
    threshold: Probability
    threshold_operator: Literal[">"] = ">"
    logits: list[FiniteFloat] = Field(min_length=2, max_length=2)
    label: Literal["P", "N"]
    device: DeviceName
    runtime_ms: NonnegativeFloat
    attribution_status: Literal["success", "unavailable", "not_requested"] = "not_requested"
    attribution_reason: str | None = None
    attribution_semantic_type: Literal["model_attribution"] = "model_attribution"
    attribution_normalization: Literal["official_absolute_maximum_diverging_scale"] = (
        "official_absolute_maximum_diverging_scale"
    )
    attribution_target_class_index: Literal[0, 1] | None = None
    attribution_target_label: Literal["P", "N"] | None = None
    residue_attribution: list[ResidueAttribution] | None = None
    top_residues: list[TopResidue] | None = None
    kde: LRECAKDE | None = None
    critical_regions: list[LRECACriticalRegion] | None = None
    warnings: list[str] = Field(default_factory=list)
    timings_ms: dict[str, NonnegativeFloat] | None = None

    @model_validator(mode="after")
    def validate_result_consistency(self):
        if len(self.sequence) != self.sequence_length:
            raise ValueError("sequence_length must match the canonical sequence")
        if self.raw_score != self.calibrated_score:
            raise ValueError("not_calibrated requires identity score passthrough")
        if (
            self.repository_commit != self.metadata.commit
            or self.checkpoint != self.metadata.checkpoint
            or self.checkpoint_sha256 != self.metadata.checkpoint_sha256
        ):
            raise ValueError("top-level provenance must match model metadata")
        if self.residue_attribution is not None:
            if len(self.residue_attribution) != self.sequence_length:
                raise ValueError("attribution must contain exactly one value per residue")
            for position, residue in enumerate(self.residue_attribution, start=1):
                if residue.position != position or residue.aa != self.sequence[position - 1]:
                    raise ValueError("attribution positions and amino acids must match sequence")
        if self.top_residues is not None:
            if self.residue_attribution is None:
                raise ValueError("top residues require residue attribution")
            seen_positions: set[int] = set()
            for rank, residue in enumerate(self.top_residues, start=1):
                if residue.rank != rank or residue.position > self.sequence_length:
                    raise ValueError("top residue ranks or positions are invalid")
                source = self.residue_attribution[residue.position - 1]
                if residue.aa != source.aa or residue.score != source.score:
                    raise ValueError("top residues must preserve the original attribution score")
                if residue.position in seen_positions:
                    raise ValueError("top residues must have unique positions")
                seen_positions.add(residue.position)
        if self.kde is not None and self.kde.values is not None:
            if len(self.kde.values) != self.sequence_length:
                raise ValueError("KDE must contain exactly one density value per residue")
        for regions in (self.critical_regions, self.kde.regions if self.kde else None):
            if regions is None:
                continue
            if any(region.end > self.sequence_length for region in regions):
                raise ValueError("critical regions must remain within the sequence")
            if regions and sum(region.is_primary for region in regions) != 1:
                raise ValueError("nonempty critical regions must identify exactly one primary")
        return self
