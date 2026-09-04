"""Check running local frontend/backend without submitting a scientific job."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def read(url: str) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": "LLPS-Explorer-Module0-Smoke/0.1"})
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read().decode("utf-8")


def local_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise argparse.ArgumentTypeError("Smoke targets must be local HTTP services")
    return value.rstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=local_url, default="http://127.0.0.1:3000")
    parser.add_argument("--backend", type=local_url, default="http://127.0.0.1:8000")
    args = parser.parse_args()
    checks = []

    for label, base in (("backend_health", args.backend), ("frontend_proxy_health", args.frontend)):
        status, body = read(base + "/api/v1/health")
        payload = json.loads(body)
        passed = status == 200 and payload == {
            "status": "ok",
            "version": "0.0.0",
            "module": 0,
            "analysis_enabled": False,
        }
        checks.append({"name": label, "passed": passed, "http_status": status, "body": payload})

    status, body = read(args.frontend)
    markers = [
        "LLPS Explorer",
        "Project foundation",
        "Analysis is not available yet.",
        "LRECA",
        "FuzDrop",
        "SEG",
        "DisMeta",
    ]
    checks.append(
        {
            "name": "frontend_page",
            "passed": status == 200 and all(marker in body for marker in markers),
            "http_status": status,
        }
    )

    status, body = read(args.backend + "/openapi.json")
    paths = set(json.loads(body)["paths"])
    checks.append(
        {
            "name": "health_only_api_contract",
            "passed": status == 200 and paths == {"/api/v1/health"},
            "paths": sorted(paths),
        }
    )

    report = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "frontend": args.frontend,
        "backend": args.backend,
        "checks": checks,
        "all_passed": all(check["passed"] for check in checks),
        "scientific_jobs_submitted": 0,
    }
    target = Path(__file__).resolve().parents[1] / "docs/audit/smoke_results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
