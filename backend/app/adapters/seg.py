"""Standard SEG annotation: no LLPS classifier, attribution, or ensemble score."""

import hashlib
import time

from app.adapters.base import BaseAnalysisAdapter
from app.core.config import Settings, get_settings
from app.schemas.analysis import AnalysisStatus, MethodCategory
from app.schemas.seg import SEGError, SEGHealth, SEGParameters, SEGRegion, SEGResult
from app.services.seg_parser import parse_seg_intervals
from app.services.seg_process import SEGProcess
from app.services.sequence_validation import normalize_sequence


class SEGAdapter(BaseAnalysisAdapter):
    """Run the independent NCBI executable using configured parameters and stdin."""

    method_id = "seg"
    category = MethodCategory.ANNOTATION
    implementation_module = 3

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self.parameters = SEGParameters(
            window=self.settings.seg_window,
            locut=self.settings.seg_locut,
            hicut=self.settings.seg_hicut,
        )
        self.process = SEGProcess(
            self.settings.seg_executable_path, self.settings.seg_timeout_seconds
        )

    async def load(self) -> None:
        try:
            await self.process.probe()
        except SEGError:
            self.process.metadata = None
            self.status = AnalysisStatus.UNAVAILABLE
            raise
        self.status = AnalysisStatus.READY

    async def healthcheck(self) -> SEGHealth:
        try:
            await self.load()
        except SEGError as error:
            return SEGHealth(
                status="unavailable",
                available=False,
                message=error.detail["message"],
                reason=error.detail["code"],
                parameters=self.parameters,
            )
        metadata = self.process.metadata
        assert metadata is not None
        return SEGHealth(
            status="ready",
            available=True,
            reason=None,
            message="Low-complexity region annotation is available.",
            version=metadata.version,
            application_version=metadata.application_version,
            executable_sha256=metadata.sha256,
            parameters=self.parameters,
        )

    async def analyze(self, sequence: str) -> SEGResult:
        started = time.perf_counter()
        canonical = normalize_sequence(sequence)
        try:
            raw, metadata = await self.process.annotate(canonical, self.parameters)
            regions = parse_seg_intervals(raw, len(canonical))
        except SEGError:
            self.status = AnalysisStatus.UNAVAILABLE
            raise
        self.status = AnalysisStatus.READY
        return SEGResult(
            version=metadata.version,
            application_version=metadata.application_version,
            executable_sha256=metadata.sha256,
            sequence_length=len(canonical),
            sequence_sha256=hashlib.sha256(canonical.encode("ascii")).hexdigest(),
            regions=regions,
            parameters=self.parameters,
            runtime_ms=(time.perf_counter() - started) * 1000,
        )

    async def predict_regions(self, sequence: str) -> list[SEGRegion]:
        """Expose the same annotations without introducing a second algorithm or validator."""
        return (await self.analyze(sequence)).regions

    async def close(self) -> None:
        await self.process.close()
        self.status = AnalysisStatus.UNAVAILABLE
