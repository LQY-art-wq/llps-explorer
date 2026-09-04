from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

MethodId = Literal["lreca", "fuzdrop", "seg", "dismeta"]


class AnalysisStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class MethodCategory(str, Enum):
    PREDICTION = "phase_separation_prediction"
    ANNOTATION = "sequence_feature_annotation"


class SemanticType(str, Enum):
    MODEL_PREDICTION = "model_prediction"
    MODEL_ATTRIBUTION = "model_attribution"
    RESIDUE_PROPENSITY = "residue_propensity"
    DERIVED_HOTSPOT = "derived_hotspot"
    REGION_ANNOTATION = "region_annotation"
    REGION_PREDICTION = "region_prediction"


class AdapterHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: MethodId
    status: AnalysisStatus
    message: str


class AnalysisResult(BaseModel):
    """Envelope only. Scientific payloads will be added in their own modules.

    No score defaults or fabricated predictions belong in a Module 0 result.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: MethodId
    status: AnalysisStatus
    message: str | None = None
