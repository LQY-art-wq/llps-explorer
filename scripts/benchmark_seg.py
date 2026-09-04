"""Measure the real standard SEG adapter on explicitly artificial CPU workloads."""

from __future__ import annotations

import asyncio
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from portable_evidence import install_portable_excepthook, portable, save_json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.seg import SEGAdapter  # noqa: E402
from app.core.config import get_settings  # noqa: E402


async def benchmark() -> dict:
    adapter = SEGAdapter(get_settings())
    started = time.perf_counter()
    await adapter.load()
    startup_ms = (time.perf_counter() - started) * 1000
    records = []
    block = "Q" * 40 + "ACDEFGHIKLMNPQRSTVWY" * 3 + "P" * 30 + "GS" * 20
    try:
        health = await adapter.healthcheck()
        for length in (100, 500, 1000, 2000, 5000):
            sequence = (block * ((length + len(block) - 1) // len(block)))[:length]
            await adapter.analyze(sequence)
            samples = []
            outputs = []
            for _ in range(5):
                before = time.perf_counter()
                result = await adapter.analyze(sequence)
                samples.append((time.perf_counter() - before) * 1000)
                outputs.append(result.model_dump(exclude={"runtime_ms"}))
            assert all(value == outputs[0] for value in outputs)
            records.append(
                {
                    "sequence_length": length,
                    "sequence_sha256": result.sequence_sha256,
                    "warmup_calls": 1,
                    "measured_calls": len(samples),
                    "end_to_end_ms": samples,
                    "median_ms": statistics.median(samples),
                    "min_ms": min(samples),
                    "max_ms": max(samples),
                    "region_count": result.region_count,
                    "longest_region": result.longest_region,
                    "coverage": result.coverage,
                }
            )
        return {
            "measured_at_utc": datetime.now(timezone.utc).isoformat(),
            "implementation": "NCBI segmasker",
            "version": health.version,
            "application_version": health.application_version,
            "executable_sha256": health.executable_sha256,
            "parameters": adapter.parameters.model_dump(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "device": "CPU",
            "workload": "artificial low-complexity and mixed-composition blocks; no LLPS claim",
            "workload_block": block,
            "timing_scope": "adapter end-to-end including child creation, stdin, parsing and DTO",
            "startup_probe_and_hash_ms": startup_ms,
            "results": records,
            "notes": [
                "Each measured annotation uses a fresh official CLI process; there is no ML model.",
                "This is a Windows CPU measurement, not a Linux/Docker or biological benchmark.",
                "No protein sequence is sent to an external service; usage reporting is disabled.",
            ],
        }
    finally:
        await adapter.close()


def main() -> None:
    result = asyncio.run(benchmark())
    save_json(ROOT / "docs" / "audit" / "seg" / "performance.json", result)
    print(json.dumps(portable(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    install_portable_excepthook("benchmark_seg")
    main()
