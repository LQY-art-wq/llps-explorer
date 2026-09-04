"""Audited unavailable boundary; no substitute, remote submission, or import."""

import hashlib

from app.adapters.base import BaseAnalysisAdapter
from app.core.config import Settings, get_settings
from app.schemas.analysis import AnalysisStatus, MethodCategory
from app.schemas.dismeta import DisMetaHealth, DisMetaUnavailableResult
from app.services.sequence_validation import normalize_sequence


class DisMetaAdapter(BaseAnalysisAdapter):
    """MODE F / UNKNOWN: a completed boundary for an unverified external contract."""

    method_id = "dismeta"
    category = MethodCategory.ANNOTATION
    implementation_module = 4

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()

    async def load(self) -> None:
        # No network, model, or subprocess can be started in the audited mode.
        self.status = AnalysisStatus.UNAVAILABLE

    async def healthcheck(self) -> DisMetaHealth:
        return DisMetaHealth(official_site_url=self.settings.dismeta_official_site_url)

    async def analyze(self, sequence: str) -> DisMetaUnavailableResult:
        canonical = normalize_sequence(sequence)
        return DisMetaUnavailableResult(
            official_site_url=self.settings.dismeta_official_site_url,
            sequence_length=len(canonical),
            sequence_sha256=hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        )

    async def predict_regions(self, sequence: str) -> None:
        # None means no prediction is available; [] would falsely mean no IDR.
        return (await self.analyze(sequence)).regions

    async def close(self) -> None:
        self.status = AnalysisStatus.UNAVAILABLE
