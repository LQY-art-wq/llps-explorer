"""Thread-safe, bounded, process-local storage for validated external imports."""

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from time import monotonic
from uuid import uuid4

from app.schemas.fuzdrop import FuzDropResult
from app.schemas.imported_results import (
    ImportedCoordinateProvenance,
    ImportedMethodResult,
    validate_imported_fuzdrop_result,
)

_ERROR_STATUS = {
    "EXTERNAL_RESULT_NOT_FOUND": 404,
    "EXTERNAL_RESULT_SEQUENCE_MISMATCH": 422,
    "EXTERNAL_RESULT_STORE_FULL": 503,
    "EXTERNAL_RESULT_INVALID": 422,
}
_ERROR_MESSAGE = {
    "EXTERNAL_RESULT_NOT_FOUND": "The imported result does not exist or has expired.",
    "EXTERNAL_RESULT_SEQUENCE_MISMATCH": "The imported result belongs to a different sequence.",
    "EXTERNAL_RESULT_STORE_FULL": "Imported result storage is unavailable or at capacity.",
    "EXTERNAL_RESULT_INVALID": "The imported result failed validation.",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
DEFAULT_OWNER_ID = "local_test_owner"


class ImportedResultError(ValueError):
    """A fixed public error, without submitted data or internal storage details."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        if code not in _ERROR_STATUS or http_status != _ERROR_STATUS[code]:
            raise ValueError("Unsupported imported-result error code or status")
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = {"code": code, "message": message}


def _error(code: str) -> ImportedResultError:
    return ImportedResultError(code, _ERROR_MESSAGE[code], _ERROR_STATUS[code])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImportedResultStore(ABC):
    """Replaceable storage boundary; references survive reads but not expiration.

    A process-local implementation is lost on restart. Missing, expired, and
    closed-store references all return EXTERNAL_RESULT_NOT_FOUND. Capacity
    pressure must reject new imports rather than evict unexpired references.
    """

    @abstractmethod
    def put(
        self, result: FuzDropResult, owner_id: str = DEFAULT_OWNER_ID
    ) -> ImportedMethodResult:
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        result_id: str,
        *,
        sequence_sha256: str | None = None,
        sequence_length: int | None = None,
        owner_id: str = DEFAULT_OWNER_ID,
    ) -> ImportedMethodResult:
        raise NotImplementedError

    @abstractmethod
    def purge_expired(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class _Entry:
    result: ImportedMethodResult
    deadline: float
    owner_id: str


class InMemoryImportedResultStore(ImportedResultStore):
    """TTL is measured monotonically from admission; reads never renew it.

    expires_at is the corresponding UTC timestamp for clients. Expired entries
    are purged on put/get and by the application's periodic lifecycle sweeper
    through purge_expired. close clears all entries and permanently closes this
    instance. Every successful read/write returns an isolated deep copy.
    """

    def __init__(self, ttl_seconds: float = 3600, max_entries: int = 128) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ValueError("ttl_seconds must be a finite positive duration")
        try:
            ttl = float(ttl_seconds)
            if not math.isfinite(ttl) or ttl <= 0:
                raise ValueError("ttl_seconds must be a finite positive duration")
            lifetime = timedelta(seconds=ttl)
            if lifetime <= timedelta(0):
                raise ValueError("ttl_seconds must be representable as a positive UTC duration")
            _utc_now() + lifetime
        except (OverflowError, ValueError) as error:
            raise ValueError("ttl_seconds must be a finite positive duration") from error
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self._ttl_seconds = ttl
        self._lifetime = lifetime
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._lock = RLock()
        self._closed = False

    @property
    def cleanup_interval_seconds(self) -> float:
        return min(60.0, self._ttl_seconds)

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if now >= entry.deadline]
        for key in expired:
            del self._entries[key]

    def purge_expired(self) -> None:
        with self._lock:
            self._purge_expired(monotonic())

    def put(
        self, result: FuzDropResult, owner_id: str = DEFAULT_OWNER_ID
    ) -> ImportedMethodResult:
        with self._lock:
            now = monotonic()
            self._purge_expired(now)
            if self._closed:
                raise _error("EXTERNAL_RESULT_STORE_FULL")
            try:
                native = validate_imported_fuzdrop_result(result)
                now = monotonic()
                self._purge_expired(now)
                result_id = "fuzdrop_result_" + uuid4().hex
                while result_id in self._entries:
                    result_id = "fuzdrop_result_" + uuid4().hex
                imported = ImportedMethodResult(
                    result_id=result_id,
                    sequence_sha256=native.sequence_sha256,
                    sequence_length=native.sequence_length,
                    normalized_result=native,
                    source=native.source,
                    imported_at=native.imported_at,
                    expires_at=_utc_now() + self._lifetime,
                    coordinate_provenance=ImportedCoordinateProvenance(
                        coordinate_system=native.coordinate_system,
                        coordinate_verification=native.coordinate_verification,
                    ),
                )
            except Exception as error:
                raise _error("EXTERNAL_RESULT_INVALID") from error
            if len(self._entries) >= self._max_entries:
                raise _error("EXTERNAL_RESULT_STORE_FULL")
            self._entries[result_id] = _Entry(imported, now + self._ttl_seconds, owner_id)
            return imported.model_copy(deep=True)

    def get(
        self,
        result_id: str,
        *,
        sequence_sha256: str | None = None,
        sequence_length: int | None = None,
        owner_id: str = DEFAULT_OWNER_ID,
    ) -> ImportedMethodResult:
        with self._lock:
            self._purge_expired(monotonic())
            if self._closed or not isinstance(result_id, str):
                raise _error("EXTERNAL_RESULT_NOT_FOUND")
            entry = self._entries.get(result_id)
            if entry is None or entry.owner_id != owner_id:
                raise _error("EXTERNAL_RESULT_NOT_FOUND")
            result = entry.result
            if sequence_sha256 is not None and (
                not isinstance(sequence_sha256, str)
                or _SHA256.fullmatch(sequence_sha256) is None
                or sequence_sha256 != result.sequence_sha256
            ):
                raise _error("EXTERNAL_RESULT_SEQUENCE_MISMATCH")
            if sequence_length is not None and (
                type(sequence_length) is not int or sequence_length != result.sequence_length
            ):
                raise _error("EXTERNAL_RESULT_SEQUENCE_MISMATCH")
            return result.model_copy(deep=True)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._entries.clear()
