"""Private, shell-free transport for the pinned NCBI SEG executable."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.schemas.seg import SEGError, SEGParameters

EXPECTED_PACKAGE_VERSION = "2.17.0"
EXPECTED_APPLICATION_VERSION = "1.0.0"
_APPLICATION_VERSION = re.compile(r"^segmasker:\s+([0-9]+\.[0-9]+\.[0-9]+)\s*$", re.MULTILINE)
_PACKAGE_VERSION = re.compile(r"^\s*Package:\s+blast\s+([0-9]+\.[0-9]+\.[0-9]+),", re.MULTILINE)


@dataclass(frozen=True)
class SEGExecutable:
    """Internal metadata; the filesystem path never belongs in a public DTO."""

    path: Path
    version: str
    application_version: str
    sha256: str
    file_signature: tuple[int, int]


def parse_seg_version(raw: bytes) -> tuple[str, str]:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise SEGError(
            "SEG_INVALID_OUTPUT", "SEG version output is invalid.", status_code=503
        ) from error
    application = _APPLICATION_VERSION.search(text)
    package = _PACKAGE_VERSION.search(text)
    if application is None or package is None:
        raise SEGError(
            "SEG_INVALID_OUTPUT",
            "SEG package and application versions are required.",
            status_code=503,
        )
    if (
        package.group(1) != EXPECTED_PACKAGE_VERSION
        or application.group(1) != EXPECTED_APPLICATION_VERSION
    ):
        raise SEGError(
            "SEG_INVALID_OUTPUT",
            "The configured SEG package version is unsupported.",
            status_code=503,
        )
    return package.group(1), application.group(1)


def resolve_seg_executable(configured: Path) -> Path:
    """Resolve an explicit configured path, or a command name from PATH."""
    candidate = Path(configured)
    if not candidate.is_absolute() and candidate.parent == Path("."):
        discovered = shutil.which(str(candidate))
        if discovered is None:
            raise SEGError(
                "SEG_EXECUTABLE_NOT_FOUND", "The SEG executable is unavailable.", status_code=503
            )
        candidate = Path(discovered)
    try:
        candidate = candidate.resolve(strict=True)
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise OSError("Executable is not a runnable file")
    except OSError as error:
        raise SEGError(
            "SEG_EXECUTABLE_NOT_FOUND", "The SEG executable is unavailable.", status_code=503
        ) from error
    return candidate


class SEGProcess:
    """Own each child process through completion, timeout, cancellation, and close."""

    def __init__(self, executable: Path, timeout_seconds: float) -> None:
        self.configured_executable = executable
        self.timeout_seconds = timeout_seconds
        self.metadata: SEGExecutable | None = None
        self._active: set[asyncio.subprocess.Process] = set()
        self._closed = False

    async def _run(self, arguments: list[str], *, stdin: bytes | None = None) -> bytes:
        if self._closed:
            raise SEGError("SEG_EXECUTION_FAILED", "SEG has been stopped.", status_code=503)
        options = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        # The distribution documents this opt-out. Do not modify the parent environment.
        environment = dict(os.environ, BLAST_USAGE_REPORT="false")
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                **options,
            )
        except FileNotFoundError as error:
            raise SEGError(
                "SEG_EXECUTABLE_NOT_FOUND", "The SEG executable is unavailable.", status_code=503
            ) from error
        except OSError as error:
            raise SEGError("SEG_EXECUTION_FAILED", "SEG could not be started.") from error
        self._active.add(process)
        communication = asyncio.create_task(process.communicate(input=stdin))
        try:
            if self._closed:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await asyncio.shield(communication)
                raise SEGError("SEG_EXECUTION_FAILED", "SEG has been stopped.", status_code=503)
            try:
                stdout, _stderr = await asyncio.wait_for(
                    asyncio.shield(communication), timeout=self.timeout_seconds
                )
            except (asyncio.TimeoutError, asyncio.CancelledError) as error:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await asyncio.shield(communication)
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise SEGError(
                    "SEG_TIMEOUT", "SEG exceeded its execution time limit.", status_code=504
                ) from error
            if process.returncode != 0:
                # External stderr can contain user input or internal paths: never forward or log it.
                raise SEGError("SEG_EXECUTION_FAILED", "SEG exited unsuccessfully.")
            return stdout
        finally:
            self._active.discard(process)

    async def probe(self) -> SEGExecutable:
        """Check existence/runnability and read the package version with a light command."""
        path = resolve_seg_executable(self.configured_executable)
        raw = await self._run([str(path), "-version"])
        version, application_version = parse_seg_version(raw)
        try:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            prior = self.metadata
            if (
                prior is not None
                and prior.path == path
                and prior.file_signature == signature
                and prior.version == version
                and prior.application_version == application_version
            ):
                return prior
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as error:
            raise SEGError(
                "SEG_EXECUTABLE_NOT_FOUND", "The SEG executable is unavailable.", status_code=503
            ) from error
        self.metadata = SEGExecutable(
            path=path,
            version=version,
            application_version=application_version,
            sha256=digest.hexdigest(),
            file_signature=signature,
        )
        return self.metadata

    async def annotate(
        self, sequence: str, parameters: SEGParameters
    ) -> tuple[bytes, SEGExecutable]:
        metadata = self.metadata
        if metadata is not None:
            try:
                stat = metadata.path.stat()
                unchanged = (stat.st_size, stat.st_mtime_ns) == metadata.file_signature
            except OSError:
                unchanged = False
        else:
            unchanged = False
        if not unchanged:
            metadata = await self.probe()
        assert metadata is not None
        arguments = [
            str(metadata.path),
            "-in",
            "-",
            "-out",
            "-",
            "-infmt",
            "fasta",
            "-outfmt",
            "interval",
            "-window",
            str(parameters.window),
            "-locut",
            str(parameters.locut),
            "-hicut",
            str(parameters.hicut),
        ]
        # Only our fixed identifier is transmitted; a user FASTA header never reaches the process.
        raw = await self._run(arguments, stdin=f">query\n{sequence}\n".encode("ascii"))
        return raw, metadata

    async def close(self) -> None:
        self._closed = True
        active = tuple(self._active)
        for process in active:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        if active:
            await asyncio.gather(*(process.wait() for process in active), return_exceptions=True)
