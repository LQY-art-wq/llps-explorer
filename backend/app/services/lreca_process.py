"""Serialized, bounded IPC to a separately pinned Python/Torch environment."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

from app.services.lreca_errors import (
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)


class LRECAProcess:
    """The caller owns this child process; no model weights cross the pipe."""

    def __init__(self, python: Path, backend: Path, *, timeout: float, threads: int):
        self.python = python
        self.backend = backend
        self.timeout = timeout
        self.threads = threads
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._messages: queue.Queue[str | None] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=80)
        self._readers: list[threading.Thread] = []
        self._request_id = 0

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _read_stdout(self, process: subprocess.Popen[str], messages: queue.Queue) -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                messages.put(line)
        finally:
            messages.put(None)

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        assert process.stderr is not None
        for line in process.stderr:
            self._stderr.append(line.rstrip()[:2000])

    def start(self, config: dict[str, Any], startup_timeout: float) -> dict[str, Any]:
        with self._lock:
            if self.alive:
                return self.rpc("load", config, timeout=startup_timeout)
            self._stop()
            if not self.python.is_file():
                raise LRECAUnavailableError(
                    f"LRECA Python is missing: {self.python}. See docs/lreca_runtime.md."
                )
            environment = os.environ.copy()
            environment.update(
                PYTHONUTF8="1",
                PYTHONDONTWRITEBYTECODE="1",
                PYTHONNOUSERSITE="1",
                CUBLAS_WORKSPACE_CONFIG=":4096:8",
                OMP_NUM_THREADS=str(self.threads),
                MKL_NUM_THREADS=str(self.threads),
            )
            self._messages = queue.Queue()
            self._stderr.clear()
            try:
                self._process = subprocess.Popen(
                    [str(self.python), "-u", "-m", "lreca_runtime.worker"],
                    cwd=self.backend,
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                    bufsize=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self._readers = [
                    threading.Thread(
                        target=self._read_stdout, args=(self._process, self._messages), daemon=True
                    ),
                    threading.Thread(target=self._read_stderr, args=(self._process,), daemon=True),
                ]
                for reader in self._readers:
                    reader.start()
                return self.rpc("load", config, timeout=startup_timeout)
            except (LRECATimeoutError, LRECAUnavailableError):
                self._stop()
                raise
            except (OSError, LRECAAnalysisError) as error:
                self._stop()
                raise LRECAUnavailableError(f"LRECA startup failed: {error}") from error

    def rpc(
        self, operation: str, payload: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if not self.alive:
                raise LRECAUnavailableError("LRECA worker is not running; restart the application.")
            self._request_id += 1
            request_id = self._request_id
            request = json.dumps(
                {"id": request_id, "operation": operation, "payload": payload or {}},
                allow_nan=False,
            )
            try:
                assert self._process is not None and self._process.stdin is not None
                self._process.stdin.write(request + "\n")
                self._process.stdin.flush()
                line = self._messages.get(timeout=timeout if timeout is not None else self.timeout)
            except queue.Empty as error:
                self._stop()
                raise LRECATimeoutError(
                    f"LRECA {operation} exceeded its time limit; "
                    "worker stopped to discard late data."
                ) from error
            except (BrokenPipeError, OSError) as error:
                self._stop()
                raise LRECAUnavailableError("The LRECA worker pipe closed unexpectedly.") from error
            if line is None:
                detail = "\n".join(list(self._stderr)[-8:])[-4000:]
                self._stop()
                raise LRECAUnavailableError(f"LRECA worker exited unexpectedly. {detail}")
            try:
                response = json.loads(line)
                if response["id"] != request_id:
                    raise ValueError("request identifier mismatch")
                if not isinstance(response["ok"], bool):
                    raise ValueError("invalid response status")
            except (KeyError, TypeError, ValueError) as error:
                self._stop()
                raise LRECAUnavailableError(
                    "LRECA returned an invalid protocol response."
                ) from error
            if not response["ok"]:
                error_payload = response.get("error")
                if not isinstance(error_payload, dict) or not isinstance(
                    error_payload.get("message"), str
                ):
                    self._stop()
                    raise LRECAUnavailableError("LRECA returned an invalid error envelope.")
                raise LRECAAnalysisError(error_payload["message"])
            result = response.get("result")
            if not isinstance(result, dict):
                self._stop()
                raise LRECAUnavailableError("LRECA returned an invalid result envelope.")
            return result

    def _stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for reader in self._readers:
            reader.join(timeout=1)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        self._readers = []

    def close(self) -> None:
        with self._lock:
            try:
                if self.alive:
                    self.rpc("shutdown", timeout=5)
                    assert self._process is not None
                    self._process.wait(timeout=5)
            except (
                LRECAAnalysisError,
                LRECATimeoutError,
                LRECAUnavailableError,
                subprocess.TimeoutExpired,
            ):
                pass
            finally:
                self._stop()
