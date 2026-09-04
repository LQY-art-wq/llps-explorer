"""HTTP-independent capability routing and isolated execution of one analysis."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError

from app.schemas.lreca import LRECAResult
from app.schemas.methods import MethodDescriptor
from app.schemas.orchestration import AnalysisJob, AnalysisRequest, MethodExecution, StructuredError
from app.schemas.seg import SEGResult
from app.services.ensemble import EnsembleCalculator
from app.services.imported_results import DEFAULT_OWNER_ID, ImportedResultStore
from app.services.lreca_errors import LRECATimeoutError, LRECAUnavailableError
from app.services.method_registry import MethodRegistry

logger = logging.getLogger("uvicorn.error.analysis.orchestrator")
TERMINAL_METHOD_STATES = frozenset(
    {"success", "failed", "unavailable", "external_result_required", "skipped"}
)


@dataclass(frozen=True)
class PreparedAnalysis:
    """Validated inputs pinned at admission, independent of an HTTP connection."""

    request: AnalysisRequest
    descriptors: dict[str, MethodDescriptor]
    imported: dict[str, BaseModel]
    owner_id: str = DEFAULT_OWNER_ID


def overall_status(methods: dict[str, MethodExecution]) -> str:
    states = {item.status for item in methods.values()}
    if states == {"success"}:
        return "success"
    if "success" in states:
        return "partial_success"
    if "failed" in states:
        return "failed"
    if "external_result_required" in states:
        return "external_result_required"
    return "unavailable"


class AnalysisOrchestrator:
    def __init__(
        self,
        registry: MethodRegistry,
        imported_store: ImportedResultStore,
        *,
        ensemble: EnsembleCalculator,
        method_timeout_seconds: float = 150,
        job_timeout_seconds: float = 180,
    ) -> None:
        self.registry, self.imported_store, self.ensemble = registry, imported_store, ensemble
        self.method_timeout_seconds, self.job_timeout_seconds = (
            method_timeout_seconds,
            job_timeout_seconds,
        )
        self._owned: set[asyncio.Task] = set()
        self._draining: dict[str, set[asyncio.Task]] = {}
        self._closed = False

    async def prepare(
        self, request: AnalysisRequest, *, owner_id: str = DEFAULT_OWNER_ID
    ) -> PreparedAnalysis:
        request = AnalysisRequest.model_validate(request.model_dump(warnings=False))
        digest = hashlib.sha256(request.sequence.encode("ascii")).hexdigest()
        imported = {}
        for method, reference in request.external_results.items():
            record = self.imported_store.get(
                reference.result_id,
                sequence_sha256=digest,
                sequence_length=len(request.sequence),
                owner_id=owner_id,
            )
            imported[method] = record.normalized_result.model_copy(deep=True)
        descriptors = await asyncio.gather(
            *(self.registry.get(method) for method in request.selected_methods)
        )
        return PreparedAnalysis(request, {row.id: row for row in descriptors}, imported, owner_id)

    def _track(self, task: asyncio.Task) -> None:
        self._owned.add(task)

        def finished(done: asyncio.Task) -> None:
            self._owned.discard(done)
            for pending in self._draining.values():
                pending.discard(done)
            if not done.cancelled():
                done.exception()  # Retrieve errors without logging tracebacks or input.

        task.add_done_callback(finished)

    async def _bounded_call(self, method: str, sequence: str, timeout: float):
        if self._draining.get(method):
            raise MethodDrainingError
        adapter = self.registry.adapter_for(method)
        task = asyncio.create_task(adapter.analyze(sequence))
        self._track(task)
        try:
            done, _ = await asyncio.wait({task}, timeout=max(0, timeout))
            if done:
                try:
                    return task.result()
                except asyncio.CancelledError:
                    raise MethodCancelledError from None
            raise TimeoutError
        finally:
            if not task.done():
                # wait_for waits for cancellation cleanup; LRECA drains its RPC.
                # Publish the deadline now, retaining ownership until cleanup ends.
                self._draining.setdefault(method, set()).add(task)
                task.cancel()

    @staticmethod
    def _validate_native(method: str, native, sequence: str):
        schema = {"lreca": LRECAResult, "seg": SEGResult}.get(method)
        if schema is None or not isinstance(native, schema):
            raise InvalidMethodResult
        try:
            result = schema.model_validate(
                native.model_dump(warnings=False, exclude_computed_fields=True)
            )
        except (ValidationError, TypeError, ValueError):
            raise InvalidMethodResult from None
        digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if result.sequence_length != len(sequence):
            raise MethodSequenceMismatch
        if method == "lreca" and result.sequence != sequence:
            raise MethodSequenceMismatch
        if method == "lreca" and result.label != (
            "P" if result.raw_score > result.threshold else "N"
        ):
            raise InvalidMethodResult
        if method == "seg" and result.sequence_sha256 != digest:
            raise MethodSequenceMismatch
        return result

    async def run_analysis(
        self,
        prepared: PreparedAnalysis,
        job: AnalysisJob,
        on_update: Callable[[AnalysisJob], None],
    ) -> AnalysisJob:
        """A future queue worker can use this same service boundary."""
        current = job.model_copy(deep=True)
        deadline = time.monotonic() + self.job_timeout_seconds

        def publish(method: MethodExecution | None = None, **updates) -> None:
            nonlocal current
            if method is not None:
                methods = {**current.methods, method.method: method}
                updates["methods"] = methods
                logger.info(
                    "analysis_method job_id=%s method=%s status=%s runtime_ms=%.3f "
                    "sequence_length=%s sequence_sha256=%s",
                    current.job_id,
                    method.method,
                    method.status,
                    method.runtime_ms,
                    current.sequence.length,
                    current.sequence.sha256,
                )
                # Publish the last method result and the job terminal state in
                # one immutable snapshot. Otherwise a reader can observe every
                # method as terminal while the job remains "running" until the
                # orchestration task gets its next event-loop turn.
                if all(item.status in TERMINAL_METHOD_STATES for item in methods.values()):
                    updates["status"] = overall_status(methods)
                    if prepared.request.prediction_mode == "weighted":
                        updates["ensemble"] = self.ensemble.calculate(
                            methods, prepared.request.weights
                        )
                        updates["warnings"] = [
                            "This experimental weighted score is not a calibrated LLPS probability."
                        ]
                    else:
                        updates["ensemble"] = None
                        updates["warnings"] = []
            current = current.model_copy(
                update={**updates, "updated_at": datetime.now(timezone.utc)}, deep=True
            )
            on_update(current.model_copy(deep=True))

        async def execute(method: str) -> None:
            descriptor = prepared.descriptors[method]
            base = {"method": method, "integration_mode": descriptor.integration_mode}
            if descriptor.integration_mode == "integration_blocked":
                publish(
                    MethodExecution(
                        **base,
                        status="unavailable",
                        reason=descriptor.reason,
                        warnings=["The selected method's integration is blocked."],
                    )
                )
                return
            if descriptor.integration_mode == "manual_import":
                if not descriptor.manual_import_available:
                    publish(
                        MethodExecution(
                            **base, status="unavailable", reason="manual_import_disabled"
                        )
                    )
                elif method in prepared.imported:
                    publish(
                        MethodExecution(
                            **base,
                            status="success",
                            result=prepared.imported[method],
                        )
                    )
                else:
                    publish(
                        MethodExecution(
                            **base,
                            status="external_result_required",
                            reason="imported_result_required",
                            warnings=["Import a matching official result to use this method."],
                        )
                    )
                return
            if not descriptor.automatic_analysis_available or self._closed:
                publish(
                    MethodExecution(
                        **base, status="unavailable", reason="automatic_analysis_unavailable"
                    )
                )
                return
            publish(MethodExecution(**base, status="running"))
            started = time.perf_counter()
            error, native = None, None
            try:
                native = await self._bounded_call(
                    method,
                    prepared.request.sequence,
                    min(self.method_timeout_seconds, deadline - time.monotonic()),
                )
                native = self._validate_native(method, native, prepared.request.sequence)
            except TimeoutError:
                error = StructuredError(code="METHOD_TIMEOUT", message="Method deadline exceeded.")
            except MethodDrainingError:
                error = StructuredError(
                    code="METHOD_BUSY_AFTER_TIMEOUT",
                    message="A previous timed-out method call is still cleaning up.",
                )
            except InvalidMethodResult:
                error = StructuredError(
                    code="METHOD_RESULT_INVALID", message="Method returned an invalid result."
                )
            except MethodSequenceMismatch:
                error = StructuredError(
                    code="METHOD_RESULT_SEQUENCE_MISMATCH",
                    message="Method result does not match the requested sequence.",
                )
            except MethodCancelledError:
                error = StructuredError(
                    code="METHOD_EXECUTION_CANCELLED", message="Method execution was cancelled."
                )
            except (LRECAUnavailableError, LRECATimeoutError):
                error = StructuredError(
                    code="METHOD_TRANSIENT_FAILURE",
                    message="Method service is temporarily unavailable.",
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                error = StructuredError(
                    code="METHOD_EXECUTION_FAILED", message="Method execution failed."
                )
            publish(
                MethodExecution(
                    **base,
                    status="failed" if error else "success",
                    runtime_ms=(time.perf_counter() - started) * 1000,
                    result=None if error else native,
                    error=error,
                )
            )

        publish(status="running")
        tasks = [asyncio.create_task(execute(method)) for method in job.selected_methods]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if current.status in {"queued", "running"}:
            ensemble, warnings = None, []
            if prepared.request.prediction_mode == "weighted":
                ensemble = self.ensemble.calculate(current.methods, prepared.request.weights)
                warnings.append(
                    "This experimental weighted score is not a calibrated LLPS probability."
                )
            publish(status=overall_status(current.methods), ensemble=ensemble, warnings=warnings)
        return current

    async def close(self) -> None:
        self._closed = True
        pending = set(self._owned)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=1)
        # Adapter shutdown owns subprocess termination; never wait forever here.


class InvalidMethodResult(Exception):
    pass


class MethodSequenceMismatch(Exception):
    pass


class MethodDrainingError(Exception):
    pass


class MethodCancelledError(Exception):
    pass
