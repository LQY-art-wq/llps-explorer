"""Verify the Module 2 API over loopback HTTP, with no FuzDrop submissions.

Run with the backend Python environment from the project root. The import case
uses explicitly synthetic format fixtures; only the LRECA case is real inference.
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
from portable_evidence import install_portable_excepthook, portable, portable_text, save_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "audit" / "module2_api_smoke"
PRIVATE = ROOT / ".audit" / "module2"


def save_response(name: str, response: httpx.Response) -> dict:
    payload = response.json()
    assert portable(payload) == payload, "API response exposed a workstation path"
    save_json(OUTPUT / name, {"http_status": response.status_code, "body": payload})
    return payload


def main() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.path.insert(0, str(ROOT / "backend"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    fixture_dir = ROOT / "backend" / "tests" / "fixtures"
    lreca_fixture = json.loads(
        (fixture_dir / "lreca" / "global_baseline.json").read_text(encoding="utf-8")
    )
    lreca_case = lreca_fixture["cases"][0]
    scores = (fixture_dir / "fuzdrop" / "synthetic_format_fixture_scores.tsv").read_text(
        encoding="utf-8"
    )
    regions = (fixture_dir / "fuzdrop" / "synthetic_format_fixture_regions.tsv").read_text(
        encoding="utf-8"
    )
    synthetic_sequence = "ACDEFGHIKLMNPQRSTVWY" * 2 + "ACDEF"
    manual_request = {
        "sequence": synthetic_sequence,
        "source_declaration": "official_fuzdrop_export",
        "coordinate_system": "one_based_inclusive",
        "scores_tsv": scores,
        "regions_tsv": regions,
    }
    save_json(
        OUTPUT / "synthetic_import_request.json",
        {
            "fixture_provenance": "synthetic_format_fixture_not_official_prediction",
            "note": (
                "Declaration exercises the import contract; these data were invented for testing."
            ),
            "request_body": manual_request,
        },
    )
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_path = PRIVATE / "module2_api_server.log"
    log_config["handlers"] = {
        "default": {
            "class": "logging.FileHandler",
            "formatter": "default",
            "filename": str(log_path),
            "encoding": "utf-8",
            "mode": "w",
        }
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
    thread = threading.Thread(target=server.run, name="module2-loopback-http-server")
    summary = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "transport": "actual Uvicorn TCP listener / httpx / loopback only",
        "status": "running",
        "backend_python": sys.version,
        "fuzdrop_fixture_provenance": "synthetic_format_fixture_not_official_prediction",
        "real_fuzdrop_prediction_executed": False,
        "fuzdrop_submission_requests_sent": 0,
        "checks": {},
    }
    thread.start()
    try:
        deadline = time.monotonic() + 130
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("Backend startup did not finish; inspect the private server log")
            time.sleep(0.05)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=120, trust_env=False
        ) as client:
            live = client.get("/api/v1/health")
            live_body = save_response("health.json", live)
            assert live.status_code == 200
            assert live_body["module"] == 2 and live_body["analysis_enabled"] is True
            summary["checks"]["liveness"] = live.status_code

            methods = client.get("/api/v1/methods")
            methods_body = save_response("methods.json", methods)
            assert methods.status_code == 200
            directory = {item["id"]: item for item in methods_body["methods"]}
            assert directory["lreca"]["available"] is True
            assert directory["fuzdrop"]["available"] is False
            assert directory["fuzdrop"]["manual_import_available"] is True
            assert directory["fuzdrop"]["integration_mode"] == "browser_protected"
            summary["checks"]["methods_directory"] = methods.status_code

            health = client.get("/api/v1/methods/fuzdrop/health")
            health_body = save_response("fuzdrop_health.json", health)
            assert health.status_code == 503 and health_body["status"] == "unavailable"
            assert health_body["available"] is False and health_body["mode"] == "C"
            summary["checks"]["fuzdrop_unavailable_health"] = health.status_code

            analyze = client.post(
                "/api/v1/methods/fuzdrop/analyze", json={"sequence": synthetic_sequence}
            )
            analyze_body = save_response("fuzdrop_analyze.json", analyze)
            assert analyze.status_code == 503
            assert analyze_body["error"]["code"] == "FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE"
            assert all(
                analyze_body[key] is None
                for key in (
                    "raw_score",
                    "calibrated_score",
                    "label",
                    "residue_propensity",
                    "regions",
                )
            )
            summary["checks"]["fuzdrop_unavailable_analyze"] = analyze.status_code

            imported = client.post("/api/v1/methods/fuzdrop/import", json=manual_request)
            imported_body = save_response("synthetic_import_response.json", imported)
            assert imported.status_code == 200
            assert imported_body["source"] == "manual_import_of_official_result"
            assert (
                imported_body["origin_verification"] == "user_declared_not_independently_verified"
            )
            assert (
                imported_body["coordinate_verification"]
                == "user_declared_not_independently_verified"
            )
            assert imported_body["runtime_scope"] == "local_import_parsing"
            assert imported_body["raw_score"] is None and imported_body["label"] is None
            assert imported_body["retrieved_at"] is None
            residues = imported_body["residue_propensity"]
            assert len(residues) == len(synthetic_sequence)
            assert all(
                row["position"] == position and row["aa"] == synthetic_sequence[position - 1]
                for position, row in enumerate(residues, start=1)
            )
            assert residues[1]["score"] == 0.6 and residues[1]["score_name"] == "pDP"
            assert residues[1]["semantic_type"] == "residue_propensity"
            assert len(imported_body["regions"]) == 3
            assert imported_body["regions"][0] == imported_body["regions"][1]
            assert all(
                region["length"] == region["end"] - region["start"] + 1
                for region in imported_body["regions"]
            )
            summary["checks"]["synthetic_manual_import"] = imported.status_code

            invalid_request = {
                **manual_request,
                "scores_tsv": scores.replace("1\tA\t", "0\tA\t", 1),
            }
            invalid = client.post("/api/v1/methods/fuzdrop/import", json=invalid_request)
            invalid_body = save_response("invalid_coordinates_response.json", invalid)
            assert invalid.status_code == 422
            assert invalid_body["detail"]["code"] == "FUZDROP_INVALID_COORDINATE"
            summary["checks"]["invalid_manual_coordinates"] = invalid.status_code

            prediction = client.post(
                "/api/v1/methods/lreca/analyze", json={"sequence": lreca_case["sequence"]}
            )
            prediction_body = save_response("lreca_regression_response.json", prediction)
            assert prediction.status_code == 200
            assert prediction_body["checkpoint_sha256"] == lreca_fixture["checkpoint_sha256"]
            assert prediction_body["repository_commit"] == lreca_fixture["repository_commit"]
            assert (
                abs(prediction_body["raw_score"] - lreca_case["supplemental_full_precision_score"])
                <= 1e-5
            )
            assert len(prediction_body["residue_attribution"]) == len(lreca_case["sequence"])
            assert len(prediction_body["kde"]["values"]) == len(lreca_case["sequence"])
            assert sum(region["is_primary"] for region in prediction_body["critical_regions"]) == 1
            summary["checks"]["lreca_real_prediction_gradcam_kde"] = prediction.status_code
            summary["lreca"] = {
                "device": prediction_body["device"],
                "sequence_length": prediction_body["sequence_length"],
                "raw_score": prediction_body["raw_score"],
                "checkpoint_sha256": prediction_body["checkpoint_sha256"],
                "primary_region": next(
                    region for region in prediction_body["critical_regions"] if region["is_primary"]
                ),
            }
            summary["status"] = "success"
    except Exception as error:
        summary.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        server.should_exit = True
        thread.join(timeout=130)
        summary["server_stopped"] = not thread.is_alive()
        summary["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save_json(OUTPUT / "summary.json", summary)
        if log_path.exists():
            (OUTPUT / "server.log").write_text(
                "# Portable export; original log: .audit/module2/module2_api_server.log\n"
                + portable_text(log_path.read_text(encoding="utf-8")),
                encoding="utf-8",
                newline="\n",
            )
    if thread.is_alive():
        raise RuntimeError("Backend shutdown did not finish")
    print(json.dumps(portable(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    install_portable_excepthook("smoke_module2")
    main()
