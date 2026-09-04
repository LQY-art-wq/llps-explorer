from abc import ABC, abstractmethod
from typing import ClassVar

from app.schemas.analysis import (
    AdapterHealth,
    AnalysisResult,
    AnalysisStatus,
    MethodCategory,
    MethodId,
)


class BaseAnalysisAdapter(ABC):
    method_id: ClassVar[MethodId]
    category: ClassVar[MethodCategory]

    def __init__(self) -> None:
        self.status = AnalysisStatus.UNAVAILABLE

    @abstractmethod
    async def load(self) -> None:
        """Prepare the selected method without running a prediction."""
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self) -> AdapterHealth:
        """Report method readiness independently of service liveness."""
        raise NotImplementedError

    @abstractmethod
    async def analyze(self, sequence: str) -> AnalysisResult:
        """Accept a validated canonical sequence; return one-based coordinates."""
        raise NotImplementedError


class PendingAdapter(BaseAnalysisAdapter):
    """Shared placeholder behavior, deliberately incapable of producing scores."""

    implementation_module: ClassVar[int]

    async def load(self) -> None:
        raise NotImplementedError(
            f"{self.method_id} is pending Module {self.implementation_module}"
        )

    async def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(
            method_id=self.method_id,
            status=AnalysisStatus.UNAVAILABLE,
            message=f"Implementation is pending Module {self.implementation_module}.",
        )

    async def analyze(self, sequence: str) -> AnalysisResult:
        raise NotImplementedError(
            f"{self.method_id} is pending Module {self.implementation_module}"
        )
