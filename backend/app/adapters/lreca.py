"""API adapter for the persistent, pinned Human LRECA scientific runtime."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.adapters.base import BaseAnalysisAdapter
from app.core.config import Settings, get_settings
from app.schemas.analysis import AnalysisStatus, MethodCategory
from app.schemas.lreca import (
    LRECAKDE,
    LRECAHealth,
    LRECAModelMetadata,
    LRECAResult,
    PublicLRECAModelMetadata,
    ResidueAttribution,
    TopResidue,
)
from app.services.lreca_errors import (
    LRECA_READY_MESSAGE,
    LRECA_UNAVAILABLE_MESSAGE,
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from app.services.lreca_process import LRECAProcess
from app.services.sequence_validation import normalize_sequence
from lreca_runtime.metadata import resolve_project_path

# Inherit the server's INFO handler so the documented Uvicorn command logs identity.
logger = logging.getLogger("uvicorn.error.lreca")


class LRECAAdapter(BaseAnalysisAdapter):
    """Load once at startup; serialize requests without blocking the ASGI loop."""

    method_id = "lreca"
    category = MethodCategory.PREDICTION
    implementation_module = 1

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self._process = LRECAProcess(
            resolve_project_path(self.settings.lreca_python),
            Path(__file__).resolve().parents[2],
            timeout=self.settings.lreca_worker_timeout_seconds,
            threads=self.settings.lreca_torch_threads,
        )
        self._lock = asyncio.Lock()
        self._loaded = False
        self._metadata: LRECAModelMetadata | None = None
        self._device: str | None = None
        self._last_error: str | None = None

    async def load(self) -> None:
        async with self._lock:
            if self._loaded and self._process.alive:
                return
            self.status = AnalysisStatus.LOADING
            self._loaded = False
            config = {
                "repository_path": str(resolve_project_path(self.settings.lreca_repository)),
                "checkpoint_path": str(self.settings.lreca_checkpoint),
                "device": self.settings.lreca_device,
                "threshold": self.settings.lreca_classification_threshold,
                "top_residues": self.settings.lreca_top_residues,
                "kde_prominence": self.settings.lreca_kde_prominence,
                "torch_threads": self.settings.lreca_torch_threads,
            }
            startup = asyncio.create_task(
                asyncio.to_thread(
                    self._process.start, config, self.settings.lreca_startup_timeout_seconds
                )
            )
            try:
                result = await asyncio.shield(startup)
                self._metadata = LRECAModelMetadata.model_validate(result["metadata"])
                self._device = result["device"]
                self._loaded = result["loaded"] is True
                if not self._loaded:
                    raise LRECAUnavailableError("LRECA worker did not confirm model readiness")
            except asyncio.CancelledError:
                try:
                    await startup
                except (LRECAUnavailableError, LRECATimeoutError, LRECAAnalysisError):
                    pass
                finally:
                    await asyncio.to_thread(self._process.close)
                    self._loaded = False
                    self.status = AnalysisStatus.UNAVAILABLE
                raise
            except (KeyError, ValidationError) as error:
                await asyncio.to_thread(self._process.close)
                self.status = AnalysisStatus.UNAVAILABLE
                self._last_error = "LRECA startup metadata is invalid"
                raise LRECAUnavailableError(self._last_error) from error
            except (LRECAUnavailableError, LRECATimeoutError, LRECAAnalysisError) as error:
                await asyncio.to_thread(self._process.close)
                self._loaded = False
                self.status = AnalysisStatus.UNAVAILABLE
                self._last_error = str(error)
                raise
            self.status = AnalysisStatus.READY
            self._last_error = None
            logger.info(
                "LRECA loaded checkpoint=%s sha256=%s size_bytes=%s "
                "repository_commit=%s device=%s",
                self._metadata.checkpoint,
                self._metadata.checkpoint_sha256,
                self._metadata.checkpoint_size_bytes,
                self._metadata.commit,
                self._device,
            )

    async def healthcheck(self) -> LRECAHealth:
        ready = self._loaded and self._process.alive
        return LRECAHealth(
            status=AnalysisStatus.READY if ready else AnalysisStatus.UNAVAILABLE,
            message=LRECA_READY_MESSAGE if ready else LRECA_UNAVAILABLE_MESSAGE,
            loaded=ready,
            device=self._device,
            metadata=PublicLRECAModelMetadata.from_private(self._metadata)
            if self._metadata is not None
            else None,
        )

    async def _call(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._lock:
            if not self._loaded or not self._process.alive:
                raise LRECAUnavailableError(
                    self._last_error or "LRECA is not loaded; initialize it at application startup."
                )
            self.status = AnalysisStatus.RUNNING
            task = asyncio.create_task(asyncio.to_thread(self._process.rpc, operation, payload))
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                # Keep ownership until the in-flight computation is complete.
                # The RPC time limit bounds this wait after caller cancellation.
                try:
                    await task
                except (LRECAAnalysisError, LRECATimeoutError, LRECAUnavailableError):
                    pass
                self.status = AnalysisStatus.READY if self._process.alive else AnalysisStatus.FAILED
                raise
            except (LRECAUnavailableError, LRECATimeoutError, LRECAAnalysisError) as error:
                self.status = AnalysisStatus.FAILED
                self._last_error = str(error)
                if not self._process.alive:
                    self._loaded = False
                raise
            self.status = AnalysisStatus.SUCCESS
            self._last_error = None
            return result

    async def analyze(
        self, sequence: str, *, include_attribution: bool = True, include_kde: bool = True
    ) -> LRECAResult:
        sequence = normalize_sequence(sequence)
        result = await self._call(
            "analyze",
            {
                "sequence": sequence,
                "include_attribution": include_attribution,
                "include_kde": include_kde and include_attribution,
            },
        )
        assert self._metadata is not None
        # The worker's local identity stays private. Only explicitly allowed
        # model identity fields are ever included in an HTTP-facing result.
        metadata_only = {
            "repository",
            "commit",
            "checkpoint_path",
            "configured_checkpoint_path",
            "checkpoint_size_bytes",
            "source_files",
            "runtime",
        }
        payload = {key: value for key, value in result.items() if key not in metadata_only}
        payload.update(
            metadata=PublicLRECAModelMetadata.from_private(self._metadata), sequence=sequence
        )
        try:
            return LRECAResult.model_validate(payload)
        except ValidationError as error:
            self.status = AnalysisStatus.FAILED
            raise LRECAAnalysisError("LRECA result failed scientific schema validation") from error

    async def predict_global(self, sequence: str) -> dict[str, Any]:
        result = await self.analyze(sequence, include_attribution=False, include_kde=False)
        return result.model_dump(mode="json")

    async def compute_attribution(self, sequence: str) -> dict[str, Any]:
        result = await self._call("compute_attribution", {"sequence": normalize_sequence(sequence)})
        try:
            if result["residue_attribution"] is not None:
                result["residue_attribution"] = [
                    ResidueAttribution.model_validate(row).model_dump(mode="json")
                    for row in result["residue_attribution"]
                ]
                result["top_residues"] = [
                    TopResidue.model_validate(row).model_dump(mode="json")
                    for row in result["top_residues"]
                ]
        except (KeyError, ValidationError) as error:
            raise LRECAAnalysisError("LRECA attribution failed schema validation") from error
        return result

    async def compute_kde(self, scores: list[float]) -> dict[str, Any]:
        result = await self._call("compute_kde", {"scores": scores})
        try:
            return LRECAKDE.model_validate(result).model_dump(mode="json")
        except ValidationError as error:
            raise LRECAAnalysisError("LRECA KDE failed schema validation") from error

    async def diagnostics(self) -> dict[str, Any]:
        return await self._call("diagnostics")

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._process.close)
            self._loaded = False
            self.status = AnalysisStatus.UNAVAILABLE
