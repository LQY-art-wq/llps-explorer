"""Method support, automatic execution, and result import are separate capabilities."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import MethodId


class MethodDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    id: MethodId
    name: str
    display_name: str | None = None
    category: Literal["prediction", "annotation"]
    available: bool = Field(description="Whether an automatic or manual-import path is usable.")
    method_supported: bool = True
    automatic_analysis_available: bool = False
    integration_status: Literal["ready", "manual_import_only", "blocked", "unavailable"]
    integration_mode: Literal[
        "local_automatic", "remote_automatic", "manual_import", "integration_blocked"
    ]
    capabilities: list[
        Literal[
            "global_score",
            "residue_attribution",
            "critical_regions",
            "residue_propensity",
            "regions",
            "low_complexity_regions",
            "disorder_regions",
        ]
    ]
    semantic_types: list[
        Literal[
            "model_prediction",
            "model_attribution",
            "derived_hotspot",
            "residue_propensity",
            "region_prediction",
            "region_annotation",
        ]
    ]
    manual_import_available: bool = False
    manual_import_supported: bool | None = None
    official_site_url: (
        Literal[
            "https://fuzdrop.bio.unipd.it",
            "https://fuzdrop.bio.unipd.it/",
            "https://fuzdrop.bio.unipd.it/predictor",
            "https://montelionelab.chem.rpi.edu/dismeta/",
            "https://montelionelab.chem.rpi.edu/dismeta",
        ]
        | None
    ) = None
    reason: str | None = None
    message: str | None = None


class MethodsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    methods: list[MethodDescriptor]
