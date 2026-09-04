"""Real-pipe lifecycle regressions with a tiny, explicitly non-scientific worker."""

import asyncio
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.lreca import LRECAAdapter
from app.core.config import Settings
from app.main import create_app
from app.services.lreca_errors import (
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from app.services.lreca_process import LRECAProcess
from lreca_runtime.metadata import get_lreca_model_metadata

WORKER_SOURCE = r'''
"""IPC test fixture: no Torch, checkpoint loading, or scientific prediction."""
import json
import os
import sys
import time
from pathlib import Path

metadata = json.loads(Path("fixture-metadata.json").read_text(encoding="utf-8"))
loaded = False
loads = 0
configuration = {}

for line in sys.stdin:
    request = json.loads(line)
    request_id = request["id"]
    operation = request["operation"]
    payload = request["payload"]
    try:
        if operation == "shutdown":
            result = {"closed": True}
        elif operation == "load":
            if not Path(payload["checkpoint_path"]).is_file():
                raise FileNotFoundError("IPC fixture: checkpoint is missing")
            if not loaded:
                loaded = True
                loads += 1
                configuration = payload
            options_path = Path("fixture-options.json")
            options = json.loads(options_path.read_text()) if options_path.exists() else {}
            Path("load-started.txt").write_text("IPC fixture received load", encoding="utf-8")
            time.sleep(options.get("load_delay", 0))
            result = {"metadata": metadata, "device": "cpu",
                      "loaded": not options.get("bad_readiness", False)}
        elif operation == "crash":
            print("Intentional IPC fixture exit", file=sys.stderr, flush=True)
            os._exit(7)
        elif operation == "delay":
            time.sleep(payload["seconds"])
            result = {"token": payload["token"]}
        elif operation == "malformed":
            print("not a JSON response", flush=True)
            continue
        elif operation == "wrong_id":
            print(json.dumps({"id": request_id + 1, "ok": True, "result": {}}), flush=True)
            continue
        elif operation == "bad_error":
            response = {"id": request_id, "ok": False, "error": payload["error"]}
            print(json.dumps(response), flush=True)
            continue
        elif operation == "bad_result":
            result = []
        elif operation == "analysis_error":
            raise ArithmeticError("Intentional IPC test error, not scientific computation")
        elif operation == "echo":
            print("fixture diagnostic on stderr", file=sys.stderr, flush=True)
            time.sleep(payload.get("seconds", 0))
            result = {"token": payload["token"], "pid": os.getpid()}
        elif operation == "diagnostics":
            result = {"load_count": loads, "configuration": configuration,
                      "omp_threads": os.environ.get("OMP_NUM_THREADS"),
                      "mkl_threads": os.environ.get("MKL_NUM_THREADS"),
                      "utf8": os.environ.get("PYTHONUTF8"), "pid": os.getpid()}
        elif operation == "analyze":
            options_path = Path("fixture-options.json")
            options = json.loads(options_path.read_text()) if options_path.exists() else {}
            mode = options.get("analysis_mode")
            private_detail = str(Path("private-worker-directory/internal-model.pt").resolve())
            if mode == "crash":
                print("Private worker stderr: " + private_detail, file=sys.stderr, flush=True)
                time.sleep(0.05)
                os._exit(7)
            if mode == "failure":
                raise OSError("Private worker error: " + private_detail)
            if mode == "timeout":
                time.sleep(0.5)
            sequence = payload["sequence"]
            result = {**metadata, "method": "lreca", "status": "success",
                      "repository_commit": metadata["commit"],
                      "sequence_length": len(sequence), "raw_score": 0.25,
                      "calibrated_score": 0.25, "calibration_status": "not_calibrated",
                      "threshold": configuration["threshold"], "label": "N",
                      "logits": [1.0986122886681098, 0.0], "device": "cpu", "runtime_ms": 0.0,
                      "attribution_status": "not_requested",
                      "warnings": ["IPC_BOUNDARY_FIXTURE_NOT_SCIENTIFIC:" + sequence]}
        else:
            raise ValueError("Unknown fixture operation")
        response = {"id": request_id, "ok": True, "result": result}
    except Exception as error:
        response = {"id": request_id, "ok": False,
                    "error": {"type": type(error).__name__, "message": str(error)}}
    print(json.dumps(response, allow_nan=False), flush=True)
    if operation == "shutdown":
        break
'''


@pytest.fixture
def pipe_fixture(tmp_path):
    package = tmp_path / "lreca_runtime"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "worker.py").write_text(WORKER_SOURCE, encoding="utf-8")
    checkpoint = tmp_path / "human_1_RCNN_ECA_parallel_089-0.9802.pt"
    checkpoint.write_text("IPC fixture only. This is not a model checkpoint.", encoding="utf-8")
    metadata = {
        "repository": "https://github.com/ai-phasepro/LRECA",
        "commit": "0b4b48ab7870529a34028c6e30dfba42eddbf215",
        "model_variant": "human_specific",
        "dataset5_mapping_status": "unconfirmed",
        "checkpoint": checkpoint.name,
        "checkpoint_path": str(checkpoint),
        "configured_checkpoint_path": str(checkpoint),
        "checkpoint_sha256": "aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc",
        "checkpoint_size_bytes": 2395318,
        "source_files": {str(tmp_path / "private-source-file.py"): {"sha256": "fixture"}},
        "runtime": {"executable": str(Path(sys.executable).resolve())},
    }
    (tmp_path / "fixture-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    processes = []

    def make_process(*, timeout=2):
        process = LRECAProcess(Path(sys.executable), tmp_path, timeout=timeout, threads=2)
        processes.append(process)
        return process

    def make_adapter(**options):
        settings = Settings(
            _env_file=None,
            lreca_python=Path(sys.executable),
            lreca_checkpoint=checkpoint,
            lreca_device="cpu",
            lreca_classification_threshold=0.6,
            lreca_top_residues=7,
            lreca_kde_prominence=0.2,
            lreca_torch_threads=2,
            lreca_startup_timeout_seconds=10,
            **options,
        )
        adapter = LRECAAdapter(settings)
        # Only substitute the child package. Production client/protocol remain real.
        adapter._process.backend = tmp_path
        processes.append(adapter._process)
        return adapter

    yield {
        "backend": tmp_path,
        "checkpoint": checkpoint,
        "config": {"checkpoint_path": str(checkpoint), "threshold": 0.6},
        "process": make_process,
        "adapter": make_adapter,
    }
    for process in processes:
        process.close()


def test_actual_metadata_rejects_missing_checkpoint_without_importing_torch(tmp_path):
    with pytest.raises(FileNotFoundError, match="checkpoint is missing"):
        get_lreca_model_metadata(checkpoint_path=tmp_path / "missing.pt")
    assert "torch" not in sys.modules


def test_missing_python_is_an_explicit_unavailable_startup(tmp_path):
    process = LRECAProcess(tmp_path / "missing-python.exe", tmp_path, timeout=1, threads=1)
    with pytest.raises(LRECAUnavailableError, match="Python is missing"):
        process.start({}, startup_timeout=1)
    assert not process.alive
    process.close()


def test_checkpoint_startup_failure_stops_child_and_does_not_return_metadata(pipe_fixture):
    process = pipe_fixture["process"]()
    with pytest.raises(LRECAUnavailableError, match="checkpoint is missing"):
        process.start({"checkpoint_path": "missing-checkpoint.pt"}, startup_timeout=10)
    assert not process.alive


def test_stderr_diagnostics_and_concurrent_replies_cannot_cross_requests(pipe_fixture):
    process = pipe_fixture["process"]()
    process.start(pipe_fixture["config"], startup_timeout=10)
    tokens = [f"protein-{index}-中文" for index in range(12)]
    with ThreadPoolExecutor(max_workers=6) as executor:
        replies = list(executor.map(lambda token: process.rpc("echo", {"token": token}), tokens))
    assert [reply["token"] for reply in replies] == tokens
    assert len({reply["pid"] for reply in replies}) == 1
    assert process.alive


def test_timeout_stops_child_and_late_reply_cannot_enter_a_restarted_session(pipe_fixture):
    process = pipe_fixture["process"](timeout=0.1)
    process.start(pipe_fixture["config"], startup_timeout=10)
    first_pid = process.rpc("echo", {"token": "before"})["pid"]
    with pytest.raises(LRECATimeoutError):
        process.rpc("delay", {"seconds": 0.7, "token": "late-old-response"})
    assert not process.alive
    with pytest.raises(LRECAUnavailableError):
        process.rpc("echo", {"token": "must-not-reload"})
    process.start(pipe_fixture["config"], startup_timeout=10)
    reply = process.rpc("echo", {"token": "fresh"})
    assert reply["token"] == "fresh"
    assert reply["pid"] != first_pid


def test_worker_crash_is_unavailable_and_never_implicitly_restarts(pipe_fixture):
    process = pipe_fixture["process"]()
    process.start(pipe_fixture["config"], startup_timeout=10)
    with pytest.raises(LRECAUnavailableError):
        process.rpc("crash")
    assert not process.alive
    with pytest.raises(LRECAUnavailableError):
        process.rpc("echo", {"token": "not-restarted"})


@pytest.mark.parametrize("operation", ["malformed", "wrong_id", "bad_result"])
def test_invalid_protocol_responses_stop_the_worker(pipe_fixture, operation):
    process = pipe_fixture["process"]()
    process.start(pipe_fixture["config"], startup_timeout=10)
    with pytest.raises(LRECAUnavailableError):
        process.rpc(operation)
    assert not process.alive


@pytest.mark.parametrize("invalid_error", [None, [], "invalid error object"])
def test_malformed_error_envelopes_fail_closed(pipe_fixture, invalid_error):
    process = pipe_fixture["process"]()
    process.start(pipe_fixture["config"], startup_timeout=10)
    with pytest.raises(LRECAUnavailableError):
        process.rpc("bad_error", {"error": invalid_error})
    assert not process.alive


def test_reported_analysis_error_preserves_a_healthy_worker_for_the_next_request(pipe_fixture):
    process = pipe_fixture["process"]()
    process.start(pipe_fixture["config"], startup_timeout=10)
    with pytest.raises(LRECAAnalysisError, match="Intentional IPC test error"):
        process.rpc("analysis_error")
    assert process.alive
    assert process.rpc("echo", {"token": "recovered"})["token"] == "recovered"


def test_adapter_config_and_repeated_load_reach_one_persistent_worker(pipe_fixture):
    async def exercise():
        adapter = pipe_fixture["adapter"]()
        await adapter.load()
        first = await adapter.diagnostics()
        await adapter.load()
        second = await adapter.diagnostics()
        assert second["load_count"] == 1
        assert second["pid"] == first["pid"]
        assert second["configuration"] == {
            "repository_path": str(adapter.settings.lreca_repository.resolve()),
            "checkpoint_path": str(pipe_fixture["checkpoint"]),
            "device": "cpu",
            "threshold": 0.6,
            "top_residues": 7,
            "kde_prominence": 0.2,
            "torch_threads": 2,
        }
        assert second["omp_threads"] == second["mkl_threads"] == "2"
        assert second["utf8"] == "1"
        await adapter.close()
        assert not (await adapter.healthcheck()).loaded

    asyncio.run(exercise())


def test_concurrent_adapter_requests_keep_responses_with_their_original_sequence(pipe_fixture):
    async def exercise():
        adapter = pipe_fixture["adapter"]()
        await adapter.load()
        sequences = ["ACDE" * length for length in range(1, 9)]
        responses = await asyncio.gather(
            *(adapter.analyze(sequence, include_attribution=False) for sequence in sequences)
        )
        for sequence, response in zip(sequences, responses):
            assert response.sequence == sequence
            assert response.sequence_length == len(sequence)
            assert response.warnings == ["IPC_BOUNDARY_FIXTURE_NOT_SCIENTIFIC:" + sequence]
        assert (await adapter.diagnostics())["load_count"] == 1
        await adapter.close()

    asyncio.run(exercise())


def test_cancelled_adapter_request_keeps_ownership_until_reply_is_consumed(pipe_fixture):
    async def exercise():
        adapter = pipe_fixture["adapter"]()
        await adapter.load()
        pending = asyncio.create_task(adapter._call("delay", {"seconds": 0.2, "token": "old"}))
        await asyncio.sleep(0.05)
        pending.cancel()
        successor = asyncio.create_task(adapter._call("echo", {"token": "new"}))
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert (await successor)["token"] == "new"
        assert (await adapter.healthcheck()).loaded
        await adapter.close()

    asyncio.run(exercise())


def test_adapter_rejects_false_readiness_and_cleans_up_the_child(pipe_fixture):
    (pipe_fixture["backend"] / "fixture-options.json").write_text(
        json.dumps({"bad_readiness": True}), encoding="utf-8"
    )

    async def exercise():
        adapter = pipe_fixture["adapter"]()
        with pytest.raises(LRECAUnavailableError, match="did not confirm"):
            await adapter.load()
        assert not adapter._process.alive
        assert not (await adapter.healthcheck()).loaded
        with pytest.raises(LRECAUnavailableError):
            await adapter.predict_global("ACDE")
        await adapter.close()

    asyncio.run(exercise())


def test_close_finishes_without_leaving_a_live_child(pipe_fixture):
    process = pipe_fixture["process"]()
    process.start(pipe_fixture["config"], startup_timeout=10)
    started = time.monotonic()
    process.close()
    assert time.monotonic() - started < 3
    assert not process.alive
    process.close()


def test_cancelled_load_cleans_up_the_worker_before_releasing_ownership(pipe_fixture):
    (pipe_fixture["backend"] / "fixture-options.json").write_text(
        json.dumps({"load_delay": 0.3}), encoding="utf-8"
    )

    async def exercise():
        adapter = pipe_fixture["adapter"]()
        pending = asyncio.create_task(adapter.load())
        deadline = asyncio.get_running_loop().time() + 5
        while not (pipe_fixture["backend"] / "load-started.txt").exists():
            if asyncio.get_running_loop().time() > deadline:
                pytest.fail("The IPC fixture did not start within its bounded startup window")
            await asyncio.sleep(0.01)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not adapter._process.alive
        assert not (await adapter.healthcheck()).loaded
        await adapter.close()

    asyncio.run(exercise())


def assert_http_has_no_private_paths(response, pipe_fixture):
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, str):
            yield value

    payload = "\n".join(walk(response.json()))
    assert "checkpoint_path" not in payload
    assert "configured_checkpoint_path" not in payload
    assert "source_files" not in payload
    assert str(pipe_fixture["backend"]) not in payload
    assert str(Path(sys.executable).resolve()) not in payload
    assert "private-worker-directory" not in payload
    assert "private-source-file" not in payload


def test_success_and_health_publish_only_safe_identity_from_private_worker_metadata(
    pipe_fixture, caplog
):
    caplog.set_level(logging.INFO, logger="uvicorn.error.lreca")
    adapter = pipe_fixture["adapter"]()
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        for response in (
            client.get("/api/v1/methods/lreca/health"),
            client.post(
                "/api/v1/methods/lreca/analyze",
                json={"sequence": "ACDE", "include_attribution": False},
            ),
        ):
            assert response.status_code == 200
            assert_http_has_no_private_paths(response, pipe_fixture)
            assert set(response.json()["metadata"]) == {
                "repository",
                "commit",
                "model_variant",
                "dataset5_mapping_status",
                "checkpoint",
                "checkpoint_sha256",
                "checkpoint_size_bytes",
            }
        # Private state is retained for logging/operation, separate from the HTTP DTO.
        assert adapter._metadata.checkpoint_path == str(pipe_fixture["checkpoint"])
        assert adapter._metadata.runtime["executable"] == str(Path(sys.executable).resolve())
    assert str(pipe_fixture["checkpoint"]) not in caplog.text
    assert pipe_fixture["checkpoint"].name in caplog.text
    assert "sha256=" in caplog.text


def test_missing_checkpoint_details_remain_private_in_startup_health_and_503(pipe_fixture, caplog):
    adapter = pipe_fixture["adapter"]()
    adapter.settings.lreca_checkpoint = pipe_fixture["backend"] / "private-missing-checkpoint.pt"
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        for response in (
            client.get("/api/v1/methods/lreca/health"),
            client.post("/api/v1/methods/lreca/analyze", json={"sequence": "ACDE"}),
        ):
            assert response.status_code == 503
            assert_http_has_no_private_paths(response, pipe_fixture)
            assert "private-missing-checkpoint" not in response.text
        assert client.get("/api/v1/health").status_code == 200
    assert "checkpoint is missing" in caplog.text


@pytest.mark.parametrize("mode,status", [("crash", 503), ("failure", 500), ("timeout", 504)])
def test_worker_stderr_and_runtime_failures_never_leak_server_paths_in_http(
    pipe_fixture, mode, status, caplog
):
    (pipe_fixture["backend"] / "fixture-options.json").write_text(
        json.dumps({"analysis_mode": mode}), encoding="utf-8"
    )
    adapter = pipe_fixture["adapter"](lreca_worker_timeout_seconds=0.1)
    with TestClient(create_app(lreca_adapter=adapter)) as client:
        response = client.post("/api/v1/methods/lreca/analyze", json={"sequence": "ACDE"})
        assert response.status_code == status
        assert_http_has_no_private_paths(response, pipe_fixture)
        assert "raw_score" not in response.json()
        health = client.get("/api/v1/methods/lreca/health")
        assert_http_has_no_private_paths(health, pipe_fixture)
    if mode in {"crash", "failure"}:
        assert "private-worker-directory" in caplog.text
