"""Measure real CPU/CUDA LRECA requests and persistent-worker lifecycle behavior.

Run with the backend environment, not the isolated scientific interpreter:
    .venv/Scripts/python.exe scripts/benchmark_lreca.py

All timed length-series inputs are explicitly synthetic canonical-AA patterns.
One untimed warm-up precedes three recorded requests for each length and mode.
"""

from __future__ import annotations

import asyncio
import json
import math
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from portable_evidence import install_portable_excepthook, portable, save_json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.lreca import LRECAAdapter  # noqa: E402
from app.core.config import Settings  # noqa: E402

OUTPUT = ROOT / "docs" / "audit" / "lreca_performance.json"
PATTERN = "ACDEFGHIKLMNPQRSTVWY"
LENGTHS = [50, 100, 500, 1000, 2000]
REPETITIONS = 3
GLOBAL_FIXTURE = json.loads(
    (ROOT / "backend/tests/fixtures/lreca/global_baseline.json").read_text(encoding="utf-8")
)


def plain(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def write_report(report: dict) -> None:
    save_json(OUTPUT, report)


def summarize_timings(samples: list[float]) -> dict:
    return {
        "samples": samples,
        "mean": statistics.mean(samples),
        "min": min(samples),
        "max": max(samples),
    }


async def measure_case(adapter: LRECAAdapter, device: str, length: int, full: bool) -> dict:
    sequence = (PATTERN * math.ceil(length / len(PATTERN)))[:length]
    await adapter.analyze(sequence, include_attribution=full, include_kde=full)
    before = await adapter.diagnostics()
    wall_ms = []
    worker_ms = []
    stage_timings = []
    scores = []
    statuses = []
    for _ in range(REPETITIONS):
        started = time.perf_counter()
        result = plain(await adapter.analyze(sequence, include_attribution=full, include_kde=full))
        wall_ms.append((time.perf_counter() - started) * 1000)
        worker_ms.append(result["runtime_ms"])
        # Preserve real per-stage timing if the implementation exposes it. A
        # missing field remains unavailable rather than a fabricated zero.
        stage_timings.append(result.get("timings_ms"))
        scores.append(result["raw_score"])
        statuses.append(result["status"])
        if not 0 <= result["raw_score"] <= 1:
            raise RuntimeError("The real model returned an invalid global score")
        if full:
            if len(result["residue_attribution"]) != length:
                raise RuntimeError("The real attribution output has the wrong length")
            if result["kde"]["status"] != "success" or len(result["kde"]["values"]) != length:
                raise RuntimeError("A requested full benchmark did not complete real KDE")
        elif result["residue_attribution"] or result["kde"]:
            raise RuntimeError("Global-only unexpectedly returned computed explainability")
    after = await adapter.diagnostics()
    stage_means = None
    if all(isinstance(value, dict) for value in stage_timings):
        stage_names = set.intersection(*(set(value) for value in stage_timings))
        stage_means = {
            name: statistics.mean(value[name] for value in stage_timings)
            for name in sorted(stage_names)
        }
    return {
        "device": after["device"],
        "requested_device": device,
        "length": length,
        "mode": "global_attribution_kde" if full else "global_only",
        "input_kind": "synthetic canonical-AA repeated pattern",
        "pattern": PATTERN,
        "warmup_requests": 1,
        "measured_requests": REPETITIONS,
        "end_to_end_wall_ms": summarize_timings(wall_ms),
        "worker_runtime_ms": summarize_timings(worker_ms),
        "stage_runtime_ms": stage_timings,
        "stage_mean_runtime_ms": stage_means,
        "scores": scores,
        "statuses": statuses,
        "diagnostics_before": before,
        "diagnostics_after": after,
        "rss_before_bytes": before.get("rss_bytes"),
        "rss_after_bytes": after.get("rss_bytes"),
        "process_lifetime_peak_rss_bytes": after.get("peak_rss_bytes"),
        "cuda_lifetime_peak_allocated_bytes": after.get("cuda_peak_allocated_bytes"),
        "memory_measurement_note": (
            "RSS is the scientific worker's process memory. Peak fields, if available, "
            "are cumulative since worker startup, not isolated per-request peaks. "
            "CUDA allocated/reserved memory are reported separately in diagnostics."
        ),
    }


async def measure_lifecycle(adapter: LRECAAdapter, device: str) -> dict:
    sequence = GLOBAL_FIXTURE["cases"][0]["sequence"]
    for _ in range(20):
        await adapter.compute_attribution(sequence)
    before = await adapter.diagnostics()
    samples = []
    started = time.perf_counter()
    for index in range(100):
        await adapter.compute_attribution(sequence)
        if (index + 1) % 20 == 0:
            samples.append(
                {"attribution_calls": index + 1, "diagnostics": await adapter.diagnostics()}
            )
    attribution_wall_seconds = time.perf_counter() - started
    after = samples[-1]["diagnostics"]
    hooks_stable = all(
        item["diagnostics"]["forward_hook_count"] == before["forward_hook_count"]
        and item["diagnostics"]["backward_hook_count"] == before["backward_hook_count"]
        for item in samples
    )
    rss_growth = after["rss_bytes"] - before["rss_bytes"]
    cuda_before = before.get("cuda_allocated_bytes")
    cuda_after = after.get("cuda_allocated_bytes")
    cuda_growth = (
        cuda_after - cuda_before if cuda_before is not None and cuda_after is not None else None
    )
    for _ in range(20):
        await adapter.predict_global(sequence)
    prediction_before = await adapter.diagnostics()
    started = time.perf_counter()
    for _ in range(100):
        await adapter.predict_global(sequence)
    prediction_wall_seconds = time.perf_counter() - started
    prediction_after = await adapter.diagnostics()
    prediction_rss_growth = prediction_after["rss_bytes"] - prediction_before["rss_bytes"]
    await adapter.load()
    await adapter.load()
    final = await adapter.diagnostics()
    passed = (
        hooks_stable
        and rss_growth < 64 * 1024 * 1024
        and (device != "cuda" or (cuda_growth is not None and cuda_growth < 16 * 1024 * 1024))
        and prediction_rss_growth < 32 * 1024 * 1024
        and final["load_count"] == 1
    )
    return {
        "device": final["device"],
        "requested_device": device,
        "source_fixture": GLOBAL_FIXTURE["cases"][0]["id"],
        "sequence_length": len(sequence),
        "attribution_warmup": 20,
        "attribution_measured_calls": 100,
        "attribution_wall_seconds": attribution_wall_seconds,
        "attribution_before": before,
        "attribution_samples": samples,
        "attribution_rss_growth_bytes": rss_growth,
        "attribution_cuda_allocated_growth_bytes": cuda_growth,
        "hooks_stable": hooks_stable,
        "prediction_warmup": 20,
        "prediction_measured_calls": 100,
        "prediction_wall_seconds": prediction_wall_seconds,
        "prediction_before": prediction_before,
        "prediction_after": prediction_after,
        "prediction_rss_growth_bytes": prediction_rss_growth,
        "final": final,
        "passed": passed,
        "interpretation": (
            "Warm-up precedes measurement. This bounds obvious growth over the measured "
            "request count; it is not a proof against all possible long-running leaks."
        ),
    }


async def benchmark() -> None:
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "backend_python": platform.python_version(),
        "backend_python_executable": sys.executable,
        "repository_commit": GLOBAL_FIXTURE["repository_commit"],
        "checkpoint_sha256": GLOBAL_FIXTURE["checkpoint_sha256"],
        "lengths": LENGTHS,
        "warmup_requests_per_case": 1,
        "measured_requests_per_case": REPETITIONS,
        "cases": [],
        "lifecycle": [],
        "devices": {},
    }
    write_report(report)
    cuda_available = False
    try:
        for device in ("cpu", "cuda"):
            if device == "cuda" and not cuda_available:
                report["devices"]["cuda"] = {
                    "status": "unavailable",
                    "reason": "The actual scientific worker reports CUDA unavailable",
                }
                continue
            adapter = LRECAAdapter(settings=Settings(lreca_device=device))
            try:
                await adapter.load()
                diagnostics = await adapter.diagnostics()
                cuda_available = bool(diagnostics["cuda_available"])
                report["devices"][device] = diagnostics
                for length in LENGTHS:
                    for full in (False, True):
                        row = await measure_case(adapter, device, length, full)
                        report["cases"].append(row)
                        write_report(report)
                        print(
                            f"{row['device']} length={length} mode={row['mode']} "
                            f"mean_wall_ms={row['end_to_end_wall_ms']['mean']:.3f}",
                            flush=True,
                        )
                lifecycle = await measure_lifecycle(adapter, device)
                report["lifecycle"].append(lifecycle)
                write_report(report)
                if not lifecycle["passed"]:
                    raise RuntimeError(f"{device}: a real lifecycle invariant failed")
            finally:
                await adapter.close()
        report["status"] = "success"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_report(report)
    print(
        json.dumps({"status": report["status"], "report": portable(OUTPUT)}, indent=2), flush=True
    )


if __name__ == "__main__":
    install_portable_excepthook("benchmark_lreca")
    asyncio.run(benchmark())
