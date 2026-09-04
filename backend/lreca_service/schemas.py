"""Small health contracts for the internal-only LRECA service."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.lreca import DeviceName, PublicLRECAModelMetadata


class LRECALiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["live"] = "live"


class LRECAReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "unavailable"]
    ready: bool
    checkpoint_verified: bool
    loaded: bool
    device: DeviceName | None = None
    metadata: PublicLRECAModelMetadata | None = None

    @model_validator(mode="after")
    def validate_state(self):
        if self.ready:
            if (
                self.status != "ready"
                or not self.checkpoint_verified
                or not self.loaded
                or self.device is None
                or self.metadata is None
            ):
                raise ValueError("ready requires a verified, loaded model identity")
        elif self.status != "unavailable" or self.loaded:
            raise ValueError("an unavailable service cannot report a loaded model")
        return self
