"""Actual local HTTP evidence for Module 5; synthetic FuzDrop values are format tests."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import platform
import socket
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn
from portable_evidence import portable, portable_text, save_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "audit" / "module5_api_smoke"
PRIVATE = ROOT / ".audit" / "module5"
TERMINAL = {"success", "partial_success", "failed", "unavailable", "external_result_required"}
SYNTHETIC_NOTICE = (
    "FuzDrop pLLPS, pDP, Sbind and regions in this smoke run are synthetic official-format "
    "inputs only, not official predictions, biological validation or calibration data."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_response(name: str, response: httpx.Response) -> dict:
    body = response.json()
    assert portable(body) == body, "Public API exposed an internal workstation path"
    save_json(OUTPUT / name, {"http_status": response.status_code, "body": body})
    return body


def run_job(client: httpx.Client, name: str, request: dict, summary: dict) -> dict:
    save_json(OUTPUT / f"{name}_request.json", {"request_body": request})
    started = time.perf_counter()
    response = client.post("/api/v1/analysis", json=request)
    initial = save_response(f"{name}_initial.json", response)
    assert response.status_code == 202, "Analysis admission did not return 202"
    job_id = initial["job_id"]
    progress = []

    def record(body: dict, status: int) -> None:
        progress.append({
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "http_status": status,
            "job_status": body["status"],
            "methods": {key: item["status"] for key, item in body["methods"].items()},
        })

    record(initial, response.status_code)
    deadline = time.monotonic() + 230
    while True:
        response = client.get(f"/api/v1/analysis/{job_id}")
        body = response.json()
        assert response.status_code == 200, "Admitted job was not retrievable"
        assert portable(body) == body, "Job response exposed an internal workstation path"
        record(body, response.status_code)
        if body["status"] in TERMINAL:
            save_response(f"{name}_final.json", response)
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Local analysis did not reach a terminal state before the smoke limit"
            )
        time.sleep(0.05)
    save_json(
        OUTPUT / f"{name}_progress.json",
        {"job_id": job_id, "observation_type": "actual HTTP snapshots", "observations": progress},
    )
    assert set(body["methods"]) == set(request["selected_methods"])
    summary["cases"][name] = {
        "job_id": job_id,
        "admission_http_status": 202,
        "final_http_status": 200,
        "status": body["status"],
        "method_statuses": {key: item["status"] for key, item in body["methods"].items()},
        "client_wall_ms": (time.perf_counter() - started) * 1000,
        "observed_snapshots": len(progress),
        "final_response": f"{name}_final.json",
    }
    return body


def native(job: dict, method: str) -> dict:
    execution = job["methods"][method]
    assert execution["status"] == "success", f"{method} did not succeed"
    assert execution["result"]["method"] == method
    return execution["result"]


def check_lreca(job: dict, sequence: str, baseline: dict) -> dict:
    result = native(job, "lreca")
    assert result["model_variant"] == "human_specific"
    assert result["dataset5_mapping_status"] == "unconfirmed"
    assert result["checkpoint_sha256"] == baseline["checkpoint_sha256"]
    assert result["repository_commit"] == baseline["repository_commit"]
    assert result["checkpoint"] == baseline["checkpoint"]
    assert abs(
        result["raw_score"] - baseline["cases"][0]["supplemental_full_precision_score"]
    ) <= 1e-5
    assert result["sequence"] == sequence and result["sequence_length"] == len(sequence) == 248
    assert result["raw_score"] == result["calibrated_score"]
    assert result["calibration_status"] == "not_calibrated"
    attribution = result["residue_attribution"]
    assert len(attribution) == 248
    for position, residue in enumerate(attribution, 1):
        assert residue["position"] == position and residue["aa"] == sequence[position - 1]
        assert residue["semantic_type"] == "model_attribution" and 0 <= residue["score"] <= 1
    assert result["kde"]["status"] == "success"
    assert result["kde"]["semantic_type"] == "derived_hotspot"
    assert len(result["kde"]["values"]) == 248
    assert all(math.isfinite(value) for value in result["kde"]["values"])
    assert result["critical_regions"] == result["kde"]["regions"]
    assert sum(region["is_primary"] for region in result["critical_regions"]) == 1
    for region in result["critical_regions"]:
        assert 1 <= region["start"] <= region["end"] <= len(sequence)
        assert region["length"] == region["end"] - region["start"] + 1
    return result


def check_seg(job: dict, case: dict) -> dict:
    result = native(job, "seg")
    assert result["annotation_type"] == "LCR" and result["semantic_type"] == "region_annotation"
    assert result["sequence_length"] == case["sequence_length"] == 248
    assert result["sequence_sha256"] == case["sequence_sha256"]
    assert [{key: row[key] for key in ("start", "end", "length")} for row in result["regions"]] == (
        case["expected_regions"]
    )
    assert result["region_count"] == 3 and result["longest_region"] == 52
    assert result["coverage"] == 97 / 248
    assert result["version"] == "2.17.0" and result["application_version"] == "1.0.0"
    assert not {"raw_score", "calibrated_score", "label", "probability"} & result.keys()
    return result


def synthetic_import(sequence: str) -> dict:
    scores = ["position\tresidue\tpDP\tSbind"]
    for position, residue in enumerate(sequence, 1):
        scores.append(
            f"{position}\t{residue}\t{(position % 11) / 10:.1f}\t{(position % 7) / 4:.2f}"
        )
    return {
        "sequence": sequence,
        "source_declaration": "official_fuzdrop_export",
        "coordinate_system": "one_based_inclusive",
        "pLLPS": 0.68,
        "scores_tsv": "\n".join(scores) + "\n",
        "regions_tsv": (
            "type\tstart\tend\n"
            "Droplet-promoting region\t30\t45\n"
            "Droplet-promoting region\t45\t60\n"
            "Aggregation hot-spot\t40\t42\n"
        ),
    }


def main() -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    fixtures = ROOT / "backend" / "tests" / "fixtures"
    cases = json.loads((fixtures / "seg" / "cases.json").read_text(encoding="utf-8"))
    case = cases["human_positive_real_sequence"]
    sequence = case["sequence"]
    baseline = json.loads((fixtures / "lreca" / "global_baseline.json").read_text(encoding="utf-8"))
    assert sequence == baseline["cases"][0]["sequence"]
    assert hashlib.sha256(sequence.encode("ascii")).hexdigest() == case["sequence_sha256"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = PRIVATE / f"api_smoke_{run_id}.log"
    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["handlers"] = {
        "default": {
            "class": "logging.FileHandler", "formatter": "default",
            "filename": str(log_path), "encoding": "utf-8", "mode": "x",
        }
    }
    log_config["loggers"]["uvicorn.access"]["handlers"] = ["default"]
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        "app.main:app", host="127.0.0.1", port=port, log_config=log_config, log_level="info"
    ))
    thread = threading.Thread(target=server.run, name="module5-loopback-http-server")
    summary = {
        "started_at_utc": utc_now(),
        "command": [portable(Path(sys.executable)), "scripts/smoke_module5.py"],
        "backend_python": platform.python_version(),
        "observed_platform": platform.platform(),
        "transport": "actual Uvicorn TCP listener / httpx / loopback only",
        "http_client_trust_env": False,
        "official_remote_submissions_sent_by_script": 0,
        "status": "running",
        "data_provenance": {
            "sequence_kind": "real sequence reused from the official LRECA human baseline",
            "sequence_sha256": case["sequence_sha256"],
            "sequence_length": len(sequence),
            "sequence_fixture": (
                "backend/tests/fixtures/seg/cases.json#human_positive_real_sequence"
            ),
            "lreca_and_seg": "real local model and official executable inference",
            "fuzdrop": SYNTHETIC_NOTICE,
            "dismeta": "blocked boundary; no prediction or substitute",
        },
        "cases": {},
        "checks": {},
    }
    save_json(
        OUTPUT / "input_provenance.json",
        {"sequence": sequence, **summary["data_provenance"], "fuzdrop_notice": SYNTHETIC_NOTICE},
    )
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
            response = client.get("/api/v1/health")
            health = save_response("health.json", response)
            assert response.status_code == 200 and health["module"] == 5
            response = client.get("/api/v1/methods")
            methods = save_response("methods.json", response)
            directory = {row["id"]: row for row in methods["methods"]}
            assert response.status_code == 200
            assert directory["lreca"]["automatic_analysis_available"] is True
            assert directory["seg"]["automatic_analysis_available"] is True
            assert directory["fuzdrop"]["available"] is True
            assert directory["fuzdrop"]["automatic_analysis_available"] is False
            assert directory["fuzdrop"]["manual_import_available"] is True
            assert directory["fuzdrop"]["integration_mode"] == "manual_import"
            assert directory["dismeta"]["integration_mode"] == "integration_blocked"
            assert directory["dismeta"]["available"] is False
            assert directory["dismeta"]["manual_import_available"] is False
            summary["checks"]["methods_routing"] = "passed"

            common = {"sequence": sequence, "prediction_mode": "independent"}
            a = run_job(client, "a_real_lreca_seg", {
                **common, "selected_methods": ["lreca", "seg"],
            }, summary)
            assert a["status"] == "success" and a["ensemble"] is None
            lreca_a, seg_a = check_lreca(a, sequence, baseline), check_seg(a, case)
            assert a["warnings"] == [] and "dismeta" not in a["methods"]
            summary["real_lreca"] = {key: lreca_a[key] for key in (
                "checkpoint", "checkpoint_sha256", "repository_commit", "model_variant",
                "dataset5_mapping_status", "raw_score", "label", "device", "runtime_ms",
            )}
            summary["real_lreca"].update(attribution_count=248, kde_count=248)
            summary["real_seg"] = {key: seg_a[key] for key in (
                "version", "application_version", "regions", "coverage", "region_count",
                "longest_region", "runtime_ms", "executable_sha256",
            )}

            weighted = {
                "sequence": sequence, "prediction_mode": "weighted",
                "weights": {"lreca": 0.6, "fuzdrop": 0.4},
            }
            b = run_job(client, "b_weighted_without_import", {
                **weighted, "selected_methods": ["lreca", "fuzdrop"],
            }, summary)
            assert b["status"] == "partial_success"
            check_lreca(b, sequence, baseline)
            assert b["methods"]["fuzdrop"]["status"] == "external_result_required"
            assert b["methods"]["fuzdrop"]["result"] is None
            assert b["ensemble"]["status"] == "unavailable" and b["ensemble"]["score"] is None
            assert b["ensemble"]["reason"] == "fuzdrop_external_result_required"

            import_body = synthetic_import(sequence)
            save_json(OUTPUT / "synthetic_fuzdrop_import_request.json", {
                "fixture_kind": "synthetic_official_format_not_official_prediction",
                "notice": SYNTHETIC_NOTICE, "request_body": import_body,
            })
            response = client.post("/api/v1/methods/fuzdrop/import", json=import_body)
            imported = save_response("synthetic_fuzdrop_import_response.json", response)
            assert response.status_code == 200 and imported["validation_status"] == "valid"
            assert imported["sequence_sha256"] == case["sequence_sha256"]
            assert imported["source"] == "manual_import_of_official_result"
            assert imported["origin_verification"] == "user_declared_not_independently_verified"
            assert imported["coordinate_verification"] == imported["origin_verification"]
            assert imported["raw_score"] == imported["calibrated_score"] == 0.68
            assert len(imported["residue_propensity"]) == 248
            imported_native = {
                key: value for key, value in imported.items()
                if key not in {"result_id", "expires_at", "validation_status"}
            }
            reference = {"fuzdrop": {"result_id": imported["result_id"]}}

            c = run_job(client, "c_real_plus_synthetic_weighted", {
                **weighted, "selected_methods": ["lreca", "fuzdrop", "seg"],
                "external_results": reference,
            }, summary)
            assert c["status"] == "success"
            lreca_c = check_lreca(c, sequence, baseline)
            check_seg(c, case)
            assert native(c, "fuzdrop") == imported_native
            expected_score = math.fsum((0.6 * lreca_c["calibrated_score"], 0.4 * 0.68))
            ensemble = c["ensemble"]
            assert ensemble["status"] == "success"
            assert abs(ensemble["score"] - expected_score) <= 1e-12
            assert ensemble["weights"] == {"lreca": 0.6, "fuzdrop": 0.4}
            assert ensemble["calibration_status"] == "not_calibrated"
            assert ensemble["interpretation_status"] == "experimental_weighted_score"
            assert "probability" not in ensemble
            assert lreca_c["residue_attribution"] == lreca_a["residue_attribution"]
            assert lreca_c["kde"]["values"] == lreca_a["kde"]["values"]
            assert lreca_c["critical_regions"] == lreca_a["critical_regions"]
            assert native(c, "seg")["regions"] == seg_a["regions"]
            assert len(native(c, "fuzdrop")["regions"]) == 3
            summary["weighted_formula_check"] = {
                "lreca_score": lreca_c["calibrated_score"],
                "fuzdrop_score": 0.68, "fuzdrop_score_kind": "synthetic_format_only",
                "weights": ensemble["weights"], "expected_score": expected_score,
                "observed_score": ensemble["score"], "absolute_tolerance": 1e-12,
                "native_explainability_and_regions_preserved": True,
            }

            d = run_job(client, "d_dismeta_only", {
                **common, "selected_methods": ["dismeta"],
            }, summary)
            assert d["status"] == "unavailable"
            assert d["methods"]["dismeta"]["status"] == "unavailable"
            assert d["methods"]["dismeta"]["result"] is None and d["ensemble"] is None

            for label, references in (("without", {}), ("with", reference)):
                job = run_job(client, f"all_four_{label}_import", {
                    **common, "selected_methods": ["lreca", "fuzdrop", "seg", "dismeta"],
                    "external_results": references,
                }, summary)
                assert job["status"] == "partial_success" and job["ensemble"] is None
                check_lreca(job, sequence, baseline)
                check_seg(job, case)
                assert job["methods"]["dismeta"]["status"] == "unavailable"
                assert job["methods"]["fuzdrop"]["status"] == (
                    "success" if references else "external_result_required"
                )
                if references:
                    assert native(job, "fuzdrop") == imported_native

            reused = run_job(client, "import_reused_independent", {
                **common, "selected_methods": ["fuzdrop"], "external_results": reference,
            }, summary)
            assert reused["status"] == "success" and reused["ensemble"] is None
            assert native(reused, "fuzdrop") == imported_native
            changed_sequence = "A" + sequence[1:]
            response = client.post("/api/v1/analysis", json={
                "sequence": changed_sequence, "selected_methods": ["fuzdrop"],
                "external_results": reference,
            })
            mismatch = save_response("sequence_mismatch.json", response)
            assert response.status_code == 422
            assert mismatch["detail"]["code"] == "EXTERNAL_RESULT_SEQUENCE_MISMATCH"
            summary["checks"]["sequence_mismatch"] = 422

            response = client.post("/api/v1/analysis", json={
                "sequence": sequence, "selected_methods": ["fuzdrop"],
                "external_results": {"fuzdrop": {"result_id": "fuzdrop_result_" + "0" * 32}},
            })
            missing = save_response("missing_import.json", response)
            assert response.status_code == 404
            assert missing["detail"]["code"] == "EXTERNAL_RESULT_NOT_FOUND"
            summary["checks"]["missing_import"] = 404
            summary["checks"]["reference_reuse"] = "passed"
            summary["checks"]["native_scientific_fields_preserved"] = "passed"
            summary["status"] = "success"
    except Exception as error:
        summary.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        server.should_exit = True
        thread.join(timeout=130)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=5)
        summary["server_stopped"] = not thread.is_alive()
        summary["finished_at_utc"] = utc_now()
        raw_logs = log_path.read_bytes() if log_path.exists() else b""
        logs = raw_logs.decode("utf-8")
        summary["logs_contain_full_test_sequences"] = any(
            value in logs for value in (sequence, "A" + sequence[1:])
        )
        summary["method_lifecycle_logs_observed"] = "analysis_method job_id=" in logs
        summary["raw_server_log"] = {
            "private_path": log_path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(raw_logs).hexdigest(), "bytes": len(raw_logs),
        }
        if not summary["server_stopped"] or summary["logs_contain_full_test_sequences"]:
            summary["status"] = "failed"
        save_json(OUTPUT / "summary.json", summary)
        (OUTPUT / "server.log").write_text(
            "# Sanitized exported log; original bytes retained at "
            + log_path.relative_to(ROOT).as_posix() + "\n"
            + portable_text(logs).replace("\r\n", "\n").replace("\r", "\n"),
            encoding="utf-8", newline="\n",
        )
    assert summary["server_stopped"], "Backend shutdown did not finish"
    assert not summary["logs_contain_full_test_sequences"], "Production log included a sequence"
    assert summary["method_lifecycle_logs_observed"], "Method lifecycle evidence was not logged"
    print(json.dumps(portable(summary), ensure_ascii=False, indent=2))


def portable_failure_hook(exception_type, exception, tb) -> None:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    failure = "".join(traceback.format_exception(exception_type, exception, tb))
    digest = hashlib.sha256(failure.encode("utf-8")).hexdigest()
    path = PRIVATE / f"smoke_failure_{digest}.log"
    if not path.exists():
        path.write_text(failure, encoding="utf-8", newline="\n")
    sys.stderr.write(portable_text(failure))


if __name__ == "__main__":
    sys.excepthook = portable_failure_hook
    main()
