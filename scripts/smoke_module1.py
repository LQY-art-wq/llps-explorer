"""Start actual Uvicorn, POST over TCP, save real responses, then stop cleanly.

Run with the backend environment: .venv/Scripts/python.exe scripts/smoke_module1.py
This is not FastAPI TestClient; the requests use the loopback HTTP listener.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn
from portable_evidence import export_log, install_portable_excepthook, portable, save_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/audit/lreca_api_smoke"


def save(name: str, value: object) -> None:
    if name in {"health.json", "response.json", "global_only_response.json"}:
        assert portable(value) == value, "Public API responses must not expose workstation paths"
    save_json(OUTPUT / name, value)


def main() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.path.insert(0, str(ROOT / "backend"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(
        (ROOT / "backend/tests/fixtures/lreca/global_baseline.json").read_text(encoding="utf-8")
    )
    case = fixture["cases"][0]
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["handlers"] = {
        "default": {
            "class": "logging.FileHandler",
            "formatter": "default",
            "filename": str(OUTPUT / "server_stdout.log"),
            "encoding": "utf-8",
            "mode": "w",
        },
    }
    log_config["loggers"]["uvicorn.access"]["handlers"] = ["default"]
    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:app",
            host="127.0.0.1",
            port=port,
            log_config=log_config,
            log_level="info",
        )
    )
    thread = threading.Thread(target=server.run, name="module1-actual-http-server")
    summary = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "transport": "actual Uvicorn TCP listener / httpx",
        "status": "running",
        "backend_python": sys.version,
    }
    thread.start()
    try:
        deadline = time.monotonic() + 130
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("Backend did not start; inspect server_stdout.log")
            time.sleep(0.05)
        with httpx.Client(base_url=base_url, timeout=120, trust_env=False) as client:
            live = client.get("/api/v1/health")
            health = client.get("/api/v1/methods/lreca/health")
            save("health.json", {"liveness": live.json(), "model": health.json()})
            assert live.status_code == health.status_code == 200
            assert health.json()["loaded"] is True
            assert live.json()["analysis_enabled"] is True
            request = {"sequence": case["sequence"]}
            save("request.json", request)
            response = client.post("/api/v1/methods/lreca/analyze", json=request)
            save("response.json", response.json())
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["checkpoint_sha256"] == fixture["checkpoint_sha256"]
            assert result["repository_commit"] == fixture["repository_commit"]
            assert abs(result["raw_score"] - case["supplemental_full_precision_score"]) <= 1e-5
            assert len(result["residue_attribution"]) == len(case["sequence"])
            assert len(result["kde"]["values"]) == len(case["sequence"])
            assert sum(region["is_primary"] for region in result["critical_regions"]) == 1
            global_response = client.post(
                "/api/v1/methods/lreca/analyze",
                json={
                    "sequence": ">official_human_positive\n" + case["sequence"].lower(),
                    "include_attribution": False,
                    "include_kde": True,
                },
            )
            save("global_only_response.json", global_response.json())
            assert global_response.status_code == 200
            global_result = global_response.json()
            assert global_result["raw_score"] == result["raw_score"]
            assert global_result["attribution_status"] == "not_requested"
            assert all(
                global_result[key] is None
                for key in (
                    "residue_attribution",
                    "top_residues",
                    "kde",
                    "critical_regions",
                )
            )
            invalid = client.post("/api/v1/methods/lreca/analyze", json={"sequence": "ACDX"})
            save("validation_response.json", invalid.json())
            assert invalid.status_code == 422
            assert invalid.json()["detail"]["code"] == "INVALID_AMINO_ACID"
            assert invalid.json()["detail"]["position"] == 4
            summary.update(
                status="success",
                full_status_code=response.status_code,
                global_only_status_code=global_response.status_code,
                invalid_status_code=invalid.status_code,
                device=result["device"],
                sequence_length=result["sequence_length"],
                raw_score=result["raw_score"],
                primary_region=next(r for r in result["critical_regions"] if r["is_primary"]),
                checkpoint_sha256=result["checkpoint_sha256"],
            )
    except Exception as error:
        summary.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        server.should_exit = True
        thread.join(timeout=130)
        summary["server_stopped"] = not thread.is_alive()
        summary["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save("summary.json", summary)
        export_log(OUTPUT / "server_stdout.log")
    if thread.is_alive():
        raise RuntimeError("Backend shutdown did not finish")
    print(json.dumps(portable(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    install_portable_excepthook("smoke_module1")
    main()
