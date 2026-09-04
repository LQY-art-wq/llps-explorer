"""Verify DisMeta's blocked boundary and prior real methods over local HTTP."""

from __future__ import annotations

import copy
import json
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
OUTPUT = ROOT / "docs" / "audit" / "module4_api_smoke"
PRIVATE = ROOT / ".audit" / "module4"


def save_response(name: str, response: httpx.Response) -> dict:
    payload = response.json()
    assert portable(payload) == payload, "Public API exposed an internal path"
    save_json(OUTPUT / name, {"http_status": response.status_code, "body": payload})
    return payload


def main() -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    fixtures = ROOT / "backend" / "tests" / "fixtures"
    cases = json.loads((fixtures / "seg" / "cases.json").read_text(encoding="utf-8"))
    real_case = cases["human_positive_real_sequence"]
    real_sequence = real_case["sequence"]
    no_lcr_sequence = cases["mixed_high_complexity"]["sequence"]
    baseline = json.loads((fixtures / "lreca" / "global_baseline.json").read_text(encoding="utf-8"))
    save_json(
        OUTPUT / "real_sequence_request.json",
        {
            "fixture_kind": "real_sequence_from_existing_official_human_baseline",
            "sequence_source": "backend/tests/fixtures/lreca/global_baseline.json / cases[0]",
            "note": "Local HTTP only; DisMeta must remain unavailable and return no IDR data.",
            "request_body": {"sequence": real_sequence},
        },
    )
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    log_path = PRIVATE / "api_server.log"
    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
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
            "app.main:app", host="127.0.0.1", port=port, log_config=log_config, log_level="info"
        )
    )
    thread = threading.Thread(target=server.run, name="module4-loopback-http-server")
    summary = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "transport": "actual Uvicorn TCP listener / httpx / loopback only",
        "status": "running",
        "fuzdrop_submission_requests_sent": 0,
        "dismeta_submission_requests_sent": 0,
        "dismeta_integration_mode": "unknown",
        "dismeta_final_decision": "INTEGRATION_BLOCKED",
        "checks": {},
    }
    thread.start()
    try:
        deadline = time.monotonic() + 130
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("Backend startup did not finish")
            time.sleep(0.05)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=120, trust_env=False
        ) as client:
            live = client.get("/api/v1/health")
            body = save_response("health.json", live)
            assert live.status_code == 200 and body["module"] == 4
            summary["checks"]["liveness"] = live.status_code

            methods = client.get("/api/v1/methods")
            body = save_response("methods.json", methods)
            directory = {row["id"]: row for row in body["methods"]}
            assert methods.status_code == 200
            assert directory["seg"]["available"] is True
            assert directory["seg"]["category"] == "annotation"
            assert directory["seg"]["capabilities"] == ["regions"]
            assert directory["seg"]["semantic_types"] == ["region_annotation"]
            assert directory["seg"]["display_name"] == "Low-complexity Regions (LCR)"
            assert directory["lreca"]["available"] is True
            assert directory["fuzdrop"]["available"] is False
            assert directory["fuzdrop"]["manual_import_available"] is True
            assert directory["dismeta"]["available"] is False
            assert directory["dismeta"]["manual_import_supported"] is False
            assert directory["dismeta"]["integration_mode"] == "unknown"
            assert directory["dismeta"]["capabilities"] == ["regions"]
            assert directory["dismeta"]["display_name"] == "Intrinsically Disordered Regions (IDR)"
            assert directory["dismeta"]["semantic_types"] == ["region_annotation"]
            summary["checks"]["methods_directory"] = methods.status_code

            dismeta_health = client.get("/api/v1/methods/dismeta/health")
            body = save_response("dismeta_health.json", dismeta_health)
            assert dismeta_health.status_code == 503 and body["available"] is False
            assert body["audit_mode"] == "F" and body["decision"] == "INTEGRATION_BLOCKED"
            assert body["manual_import_supported"] is False
            summary["checks"]["dismeta_health_unavailable"] = dismeta_health.status_code

            started = time.perf_counter()
            dismeta = client.post(
                "/api/v1/methods/dismeta/analyze", json={"sequence": real_sequence}
            )
            summary["dismeta_local_boundary_latency_ms"] = (time.perf_counter() - started) * 1000
            body = save_response("dismeta_unavailable_response.json", dismeta)
            assert dismeta.status_code == 503 and body["error"]["code"] == "DISMETA_UNAVAILABLE"
            assert body["status"] == "unavailable" and body["integration_mode"] == "unknown"
            assert body["annotation_type"] == "IDR" and body["semantic_type"] == "region_annotation"
            assert (
                body["regions"]
                is body["coverage"]
                is body["region_count"]
                is body["longest_region"]
                is None
            )
            assert body["sequence_length"] == 248
            assert body["sequence_sha256"] == real_case["sequence_sha256"]
            assert not {"raw_score", "label", "probability", "residue_disorder_score"} & body.keys()
            summary["checks"]["dismeta_analyze_unavailable"] = dismeta.status_code

            invalid_dismeta = client.post(
                "/api/v1/methods/dismeta/analyze", json={"sequence": "ACDX"}
            )
            body = save_response("dismeta_invalid_sequence.json", invalid_dismeta)
            assert (
                invalid_dismeta.status_code == 422
                and body["detail"]["code"] == "INVALID_AMINO_ACID"
            )
            summary["checks"]["dismeta_invalid_sequence"] = invalid_dismeta.status_code

            no_import = client.post("/api/v1/methods/dismeta/import", json={"coverage": 0.5})
            save_response("dismeta_import_not_enabled.json", no_import)
            assert no_import.status_code == 404
            summary["checks"]["dismeta_import_not_enabled"] = no_import.status_code

            health = client.get("/api/v1/methods/seg/health")
            body = save_response("seg_health.json", health)
            assert health.status_code == 200 and body["available"] is True
            assert body["version"] == "2.17.0" and body["application_version"] == "1.0.0"
            summary["checks"]["seg_health"] = health.status_code

            response = client.post("/api/v1/methods/seg/analyze", json={"sequence": real_sequence})
            body = save_response("real_seg_response.json", response)
            assert response.status_code == 200
            assert body["semantic_type"] == "region_annotation" and body["annotation_type"] == "LCR"
            assert [
                {key: row[key] for key in ("start", "end", "length")} for row in body["regions"]
            ] == real_case["expected_regions"]
            assert body["region_count"] == 3 and body["longest_region"] == 52
            assert body["coverage"] == 97 / 248
            assert not {"raw_score", "calibrated_score", "label", "probability"} & body.keys()
            assert "sequence" not in body
            summary["checks"]["real_seg_annotation"] = response.status_code
            summary["seg_result"] = {
                key: body[key]
                for key in (
                    "version",
                    "application_version",
                    "sequence_length",
                    "sequence_sha256",
                    "regions",
                    "coverage",
                    "region_count",
                    "longest_region",
                    "parameters",
                    "runtime_ms",
                    "executable_sha256",
                )
            }

            no_lcr = client.post("/api/v1/methods/seg/analyze", json={"sequence": no_lcr_sequence})
            body = save_response("no_lcr_response.json", no_lcr)
            assert no_lcr.status_code == 200 and body["regions"] == []
            assert body["coverage"] == body["region_count"] == body["longest_region"] == 0
            summary["checks"]["no_lcr_annotation"] = no_lcr.status_code

            invalid = client.post("/api/v1/methods/seg/analyze", json={"sequence": "ACDX"})
            body = save_response("invalid_sequence_response.json", invalid)
            assert invalid.status_code == 422 and body["detail"]["code"] == "INVALID_AMINO_ACID"
            summary["checks"]["invalid_sequence"] = invalid.status_code

            fuzdrop = client.get("/api/v1/methods/fuzdrop/health")
            body = save_response("fuzdrop_health.json", fuzdrop)
            assert fuzdrop.status_code == 503 and body["integration_mode"] == "browser_protected"
            assert body["available"] is False and body["manual_import_available"] is True
            summary["checks"]["fuzdrop_manual_boundary_preserved"] = fuzdrop.status_code

            synthetic_import = {
                "sequence": real_sequence,
                "source_declaration": "official_fuzdrop_export",
                "coordinate_system": "one_based_inclusive",
                "pLLPS": 0.2,
            }
            save_json(
                OUTPUT / "synthetic_fuzdrop_import_request.json",
                {
                    "fixture_kind": "synthetic_format_only_not_official_prediction",
                    "request_body": synthetic_import,
                },
            )
            imported = client.post("/api/v1/methods/fuzdrop/import", json=synthetic_import)
            body = save_response("synthetic_fuzdrop_import_response.json", imported)
            assert imported.status_code == 200 and body["method"] == "fuzdrop"
            summary["checks"]["fuzdrop_import_after_dismeta_unavailable"] = imported.status_code

            lreca = client.post("/api/v1/methods/lreca/analyze", json={"sequence": real_sequence})
            body = save_response("lreca_regression_response.json", lreca)
            assert lreca.status_code == 200
            assert body["checkpoint_sha256"] == baseline["checkpoint_sha256"]
            assert (
                abs(body["raw_score"] - baseline["cases"][0]["supplemental_full_precision_score"])
                <= 1e-5
            )
            assert (
                len(body["residue_attribution"]) == len(body["kde"]["values"]) == len(real_sequence)
            )
            summary["checks"]["real_lreca_prediction_gradcam_kde"] = lreca.status_code
            summary["lreca_raw_score"] = body["raw_score"]
            summary["lreca_device"] = body["device"]
            summary["status"] = "success"
    except Exception as error:
        summary.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        server.should_exit = True
        thread.join(timeout=130)
        summary["server_stopped"] = not thread.is_alive()
        summary["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        logs = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        summary["logs_contain_full_test_sequences"] = any(
            sequence in logs for sequence in (real_sequence, no_lcr_sequence)
        )
        save_json(OUTPUT / "summary.json", summary)
        (OUTPUT / "server.log").write_text(
            "# Portable export; original log: .audit/module4/api_server.log\n"
            + portable_text(logs),
            encoding="utf-8",
            newline="\n",
        )
    assert not thread.is_alive(), "Backend shutdown did not finish"
    assert not summary["logs_contain_full_test_sequences"], "Production log included a sequence"
    print(json.dumps(portable(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    install_portable_excepthook("smoke_module4")
    main()
