"""Audited browser-protected boundary; no automatic submission is performed."""

from app.adapters.base import BaseAnalysisAdapter
from app.core.config import Settings, get_settings
from app.schemas.analysis import AnalysisStatus, MethodCategory
from app.schemas.fuzdrop import FuzDropHealth, FuzDropUnavailableResult
from app.services.sequence_validation import normalize_sequence


class FuzDropRemoteAdapter(BaseAnalysisAdapter):
    """Keep a stable interface until supported official programmatic access exists."""

    method_id = "fuzdrop"
    category = MethodCategory.PREDICTION
    implementation_module = 2

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()

    async def load(self) -> None:
        # MODE C has no transport, API credentials, remote health probe, or model.
        self.status = AnalysisStatus.UNAVAILABLE

    async def healthcheck(self) -> FuzDropHealth:
        return FuzDropHealth(
            message=self._availability_message(),
            official_site_url=self.settings.fuzdrop_official_site_url,
            manual_import_available=self.settings.fuzdrop_manual_import_enabled,
        )

    async def analyze(self, sequence: str) -> FuzDropUnavailableResult:
        normalize_sequence(sequence)
        return FuzDropUnavailableResult(
            message=self._availability_message(),
            official_site_url=self.settings.fuzdrop_official_site_url,
            manual_import_available=self.settings.fuzdrop_manual_import_enabled,
        )

    async def close(self) -> None:
        # Deliberately no network client or other resource to close in MODE C.
        self.status = AnalysisStatus.UNAVAILABLE

    def _availability_message(self) -> str:
        message = (
            "The official FuzDrop service requires browser verification. "
            "Automatic prediction is unavailable."
        )
        if self.settings.fuzdrop_manual_import_enabled:
            message += " Official results can be imported manually."
        return message
