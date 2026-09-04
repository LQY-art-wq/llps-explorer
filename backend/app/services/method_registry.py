"""Capability metadata and bounded local readiness checks, independent of HTTP."""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from app.schemas.analysis import AnalysisStatus
from app.schemas.lreca import LRECAHealth
from app.schemas.methods import MethodDescriptor
from app.schemas.seg import SEGHealth

logger = logging.getLogger("uvicorn.error.method_registry")
METHOD_IDS = ("lreca", "fuzdrop", "seg", "dismeta")
READY_STATUSES = {AnalysisStatus.READY, AnalysisStatus.RUNNING, AnalysisStatus.SUCCESS}
HEALTH_TIMEOUT_SECONDS = 2.0


class MethodRegistry:
    def __init__(self, adapters: Mapping[str, Any], *, manual_import_enabled: bool = True):
        self._adapters = {method: adapters.get(method) for method in METHOD_IDS}
        self._manual_import_enabled = manual_import_enabled
        self._health_tasks: dict[str, asyncio.Task] = {}
        self._closed = False

    def adapter_for(self, method_id: str) -> Any | None:
        return self._adapters.get(method_id)

    def _consume_health_task(self, method_id: str, task: asyncio.Task) -> None:
        if self._health_tasks.get(method_id) is task:
            self._health_tasks.pop(method_id, None)
        if not task.cancelled():
            task.exception()

    async def _local_health(self, method_id: str):
        adapter = self.adapter_for(method_id)
        if self._closed or adapter is None:
            return None
        task = self._health_tasks.get(method_id)
        try:
            if task is None:
                task = asyncio.create_task(adapter.healthcheck())
                self._health_tasks[method_id] = task
                task.add_done_callback(
                    lambda completed: self._consume_health_task(method_id, completed)
                )
            done, _ = await asyncio.wait({task}, timeout=HEALTH_TIMEOUT_SECONDS)
            if not done:
                task.cancel()
                logger.warning("Method readiness timed out (%s).", method_id)
                return None
            if task.cancelled():
                return None
            reply = task.result()
            schema = LRECAHealth if method_id == "lreca" else SEGHealth
            # Suppress serializer diagnostics for an already-corrupt DTO, then
            # validate every field before inspecting readiness or provenance.
            return schema.model_validate(
                reply.model_dump(warnings=False) if isinstance(reply, schema) else reply
            )
        except asyncio.CancelledError:
            if task is not None:
                task.cancel()
            raise
        except Exception as error:
            logger.warning(
                "Method readiness unavailable (%s; %s).", method_id, type(error).__name__
            )
            return None

    def _official_url(self, method_id: str) -> str:
        allowed = (
            (
                "https://fuzdrop.bio.unipd.it/predictor",
                "https://fuzdrop.bio.unipd.it/",
                "https://fuzdrop.bio.unipd.it",
            )
            if method_id == "fuzdrop"
            else (
                "https://montelionelab.chem.rpi.edu/dismeta/",
                "https://montelionelab.chem.rpi.edu/dismeta",
            )
        )
        try:
            settings = getattr(self.adapter_for(method_id), "settings", None)
            configured = getattr(settings, f"{method_id}_official_site_url", None)
            return configured if configured in allowed else allowed[0]
        except Exception:
            return allowed[0]

    async def get(self, method_id: str) -> MethodDescriptor:
        if method_id not in METHOD_IDS:
            raise KeyError("Unknown method")
        if method_id == "lreca":
            health = await self._local_health(method_id)
            ready = health is not None and health.loaded and health.status in READY_STATUSES
            return MethodDescriptor(
                id="lreca",
                name="LRECA",
                display_name="LRECA",
                category="prediction",
                available=ready,
                automatic_analysis_available=ready,
                integration_mode="local_automatic",
                integration_status="ready" if ready else "unavailable",
                capabilities=["global_score", "residue_attribution", "critical_regions"],
                semantic_types=["model_prediction", "model_attribution", "derived_hotspot"],
                manual_import_supported=False,
                reason=None if ready else "model_unavailable",
                message=None if ready else "The local LRECA model is currently unavailable.",
            )
        if method_id == "seg":
            health = await self._local_health(method_id)
            ready = health is not None and health.available
            return MethodDescriptor(
                id="seg",
                name="SEG",
                display_name="Low-complexity Regions (LCR)",
                category="annotation",
                available=ready,
                automatic_analysis_available=ready,
                integration_mode="local_automatic",
                integration_status="ready" if ready else "unavailable",
                capabilities=["regions"],
                semantic_types=["region_annotation"],
                manual_import_supported=False,
                reason=None if ready else "SEG_UNAVAILABLE",
                message=None if ready else "SEG annotation is currently unavailable.",
            )
        if method_id == "fuzdrop":
            enabled = self._manual_import_enabled
            return MethodDescriptor(
                id="fuzdrop",
                name="FuzDrop",
                display_name="FuzDrop",
                category="prediction",
                available=enabled,
                automatic_analysis_available=False,
                integration_mode="manual_import",
                integration_status="manual_import_only" if enabled else "unavailable",
                capabilities=["global_score", "residue_propensity", "regions"],
                semantic_types=["model_prediction", "residue_propensity", "region_prediction"],
                manual_import_available=enabled,
                manual_import_supported=True,
                official_site_url=self._official_url(method_id),
                reason="manual_import_only" if enabled else "manual_import_disabled",
                message="Official FuzDrop results are available through validated manual import."
                if enabled
                else "Manual FuzDrop result import is disabled by server configuration.",
            )
        return MethodDescriptor(
            id="dismeta",
            name="DisMeta",
            display_name="Intrinsically Disordered Regions (IDR)",
            category="annotation",
            available=False,
            automatic_analysis_available=False,
            integration_mode="integration_blocked",
            integration_status="blocked",
            capabilities=["regions"],
            semantic_types=["region_annotation"],
            manual_import_supported=False,
            official_site_url=self._official_url(method_id),
            reason="integration_contract_unverified",
            message=(
                "DisMeta integration is blocked until a supported invocation "
                "and result contract is verified."
            ),
        )

    async def list_methods(self) -> list[MethodDescriptor]:
        return list(await asyncio.gather(*(self.get(method) for method in METHOD_IDS)))

    async def close(self) -> None:
        self._closed = True
        tasks = list(self._health_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=HEALTH_TIMEOUT_SECONDS)
