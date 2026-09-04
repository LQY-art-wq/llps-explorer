"""SEG capability probe for a web process that never executes the native binary."""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.schemas.analysis import AnalysisStatus, MethodCategory
from app.schemas.seg import SEGError, SEGHealth, SEGParameters
from app.services.analysis_queue import AnalysisQueueError, RQAnalysisQueue


class QueuedSEGAdapter:
    """Advertise worker-owned SEG only while Redis has a registered queue worker."""

    method_id = "seg"
    category = MethodCategory.ANNOTATION
    implementation_module = 10

    def __init__(self, settings: Settings, queue: RQAnalysisQueue) -> None:
        self.settings = settings
        self.queue = queue
        self.status = AnalysisStatus.UNAVAILABLE
        self.parameters = SEGParameters(
            window=settings.seg_window,
            locut=settings.seg_locut,
            hicut=settings.seg_hicut,
        )

    async def healthcheck(self) -> SEGHealth:
        try:
            queue_ok, workers = await asyncio.gather(
                asyncio.to_thread(self.queue.ping),
                asyncio.to_thread(self.queue.worker_count),
            )
        except (AnalysisQueueError, OSError, TimeoutError):
            queue_ok, workers = False, 0
        available = bool(queue_ok and workers > 0)
        self.status = AnalysisStatus.READY if available else AnalysisStatus.UNAVAILABLE
        return SEGHealth(
            status="ready" if available else "unavailable",
            available=available,
            message=(
                "Worker-owned low-complexity annotation is available."
                if available
                else "No ready SEG analysis worker is registered."
            ),
            reason=None if available else "SEG_UNAVAILABLE",
            version="2.17.0" if available else None,
            application_version="1.0.0" if available else None,
            parameters=self.parameters,
        )

    async def load(self) -> None:
        health = await self.healthcheck()
        if not health.available:
            raise SEGError(
                "SEG_UNAVAILABLE",
                "No ready SEG analysis worker is registered.",
                status_code=503,
            )

    async def analyze(self, _sequence: str):
        raise SEGError(
            "SEG_UNAVAILABLE",
            "Direct SEG execution is disabled; submit an asynchronous analysis job.",
            status_code=409,
        )

    async def close(self) -> None:
        self.status = AnalysisStatus.UNAVAILABLE
