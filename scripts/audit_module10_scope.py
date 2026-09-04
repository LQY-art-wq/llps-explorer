"""Audit Module 10 changes against its immutable pre-module SHA256 manifest.

The Module 10 baseline is ``.audit/module10_baseline_files.json``.  Git status
is deliberately not used to reconstruct or infer that baseline.  Git is used
only for two independent integrity checks: first-party weight tracking and the
pinned upstream LRECA checkout state.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / ".audit" / "module10_baseline_files.json"
REPORT_PATH = ROOT / "docs" / "audit" / "module10" / "scope_review.json"
CHANGED_FILES_PATH = ROOT / "docs" / "module10_changed_files.txt"
GENERATED_OUTPUTS = {
    REPORT_PATH.relative_to(ROOT).as_posix(),
    CHANGED_FILES_PATH.relative_to(ROOT).as_posix(),
}

WEIGHT_SUFFIXES = {".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".h5", ".hdf5"}
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![a-z0-9])[a-z]:[\\/](?![\\/])")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

# These files own scientific formulas, coordinates, source identity, or an
# audited external-service policy. Deployment wrappers and HTTP wiring are
# intentionally absent from this set and are classified separately below.
FROZEN_SCIENCE: dict[str, tuple[str, str]] = {
    "backend/lreca_runtime/engine.py": ("lreca", "model inference and attribution engine"),
    "backend/lreca_runtime/metadata.py": ("lreca", "checkpoint and upstream identity"),
    "backend/lreca_runtime/upstream.py": ("lreca", "pinned upstream compatibility loader"),
    "backend/lreca_runtime/worker.py": ("lreca", "isolated scientific runtime entrypoint"),
    "backend/app/services/lreca_process.py": ("lreca", "LRECA process boundary"),
    "backend/app/schemas/lreca.py": ("lreca", "prediction and explainability contract"),
    "external/lreca-source.json": ("lreca", "pinned source and checkpoint manifest"),
    "backend/app/adapters/seg.py": ("seg", "SEG parameters and executable contract"),
    "backend/app/services/seg_parser.py": ("seg", "SEG interval parser"),
    "backend/app/services/seg_process.py": ("seg", "SEG subprocess semantics"),
    "backend/app/schemas/seg.py": ("seg", "SEG parameter and coordinate contract"),
    "external/seg-source.json": ("seg", "SEG source manifest"),
    "backend/app/adapters/fuzdrop_remote.py": (
        "fuzdrop",
        "official-service no-automation policy",
    ),
    "backend/app/services/fuzdrop_import.py": (
        "fuzdrop",
        "official export parsing and validation policy",
    ),
    "backend/app/schemas/fuzdrop.py": ("fuzdrop", "official result contract"),
    "backend/app/adapters/dismeta.py": ("dismeta", "audited unavailable boundary"),
    "backend/app/schemas/dismeta.py": ("dismeta", "unavailable-result contract"),
    "backend/app/services/ensemble.py": ("ensemble", "weighted ensemble formula"),
    "backend/app/schemas/orchestration.py": (
        "ensemble",
        "ensemble weights and orchestration result contract",
    ),
    "backend/app/schemas/coordinates.py": (
        "coordinates",
        "shared one-based coordinate contract",
    ),
}

# Regression fixtures and focused contract tests are part of the scientific
# evidence chain as well. Listing them explicitly keeps the review auditable.
FROZEN_SCIENCE.update(
    {
        "backend/requirements-lreca.lock.txt": (
            "lreca",
            "validated scientific runtime dependency lock",
        ),
        "backend/tests/fixtures/lreca/global_baseline.json": (
            "lreca",
            "global prediction regression baseline",
        ),
        "backend/tests/fixtures/lreca/attribution_baseline.json": (
            "lreca",
            "Grad-CAM and KDE regression baseline",
        ),
        "backend/tests/fixtures/fuzdrop/README.md": (
            "fuzdrop",
            "official export fixture provenance",
        ),
        "backend/tests/fixtures/fuzdrop/synthetic_format_fixture_regions.tsv": (
            "fuzdrop",
            "official region export contract fixture",
        ),
        "backend/tests/fixtures/fuzdrop/synthetic_format_fixture_scores.tsv": (
            "fuzdrop",
            "official residue export contract fixture",
        ),
        "backend/tests/test_fuzdrop_import.py": (
            "fuzdrop",
            "official import policy regression test",
        ),
        "backend/tests/test_fuzdrop_api.py": (
            "fuzdrop",
            "official service boundary regression test",
        ),
        "backend/tests/test_dismeta_contract.py": (
            "dismeta",
            "unavailable-boundary contract regression test",
        ),
        "docs/audit/dismeta/scientific_source_evidence.json": (
            "dismeta",
            "scientific source audit evidence",
        ),
        "backend/tests/test_ensemble.py": (
            "ensemble",
            "weighted formula regression test",
        ),
    }
)

for _seg_fixture in (
    "README.md",
    "all_low_complexity.interval.txt",
    "c_terminal.interval.txt",
    "cases.json",
    "help.txt",
    "human_positive_real_sequence.interval.txt",
    "mixed_high_complexity.interval.txt",
    "multiple_regions.interval.txt",
    "n_terminal.interval.txt",
    "short_homopolymer.interval.txt",
    "version.txt",
    "window_homopolymer.interval.txt",
):
    FROZEN_SCIENCE[f"backend/tests/fixtures/seg/{_seg_fixture}"] = (
        "seg",
        "SEG parser and coordinate regression fixture",
    )

# Module 10 may change process boundaries, persistence, deployment wiring,
# security controls, health endpoints, and their tests. Exact paths keep the
# exception narrow so a scientific implementation does not become implicitly
# editable merely because it lives under backend/app.
DEPLOYMENT_ADAPTATION_EXACT: dict[str, str] = {
    ".dockerignore": "container build context",
    ".env.example": "production environment template",
    ".gitignore": "runtime secret, data, and checkpoint exclusions",
    "compose.yaml": "local production-like service topology",
    "docs/architecture.md": "production topology documentation",
    "docs/backup_restore.md": "production backup and restore runbook",
    "docs/deployment.md": "production deployment runbook",
    "docs/operations.md": "production operations runbook",
    "docs/security.md": "production security runbook",
    "backend/.env.example": "backend production configuration template",
    "backend/app/__init__.py": "application package metadata",
    "backend/app/adapters/lreca.py": "checkpoint-path log privacy hardening",
    "backend/app/adapters/lreca_remote.py": "remote LRECA service adapter",
    "backend/app/adapters/seg_queued.py": "queued SEG adapter wrapper",
    "backend/app/api/analysis.py": "durable analysis submission API",
    "backend/app/api/fuzdrop.py": "production API policy and rate-limit wiring",
    "backend/app/api/health.py": "liveness and readiness endpoints",
    "backend/app/api/lreca.py": "LRECA service-boundary API wiring",
    "backend/app/api/seg.py": "production SEG API wiring",
    "backend/app/api/session.py": "production session security",
    "backend/app/api/system.py": "runtime capability endpoint",
    "backend/app/core/config.py": "environment-backed production settings",
    "backend/app/core/observability.py": "structured operational logging",
    "backend/app/main.py": "application lifecycle and dependency wiring",
    "backend/app/services/analysis_jobs.py": "durable job lifecycle",
    "backend/app/services/analysis_queue.py": "Redis-backed queue boundary",
    "backend/app/services/orchestrator.py": "atomic job-state publication",
    "backend/app/services/persistent_repositories.py": "database concurrency guards",
    "backend/app/services/rate_limits.py": "production request limits",
    "backend/app/worker.py": "independent durable queue worker",
    "backend/pyproject.toml": "production Python dependencies",
    "backend/requirements-lreca-service.lock.txt": "pinned LRECA service dependencies",
    "backend/requirements.lock.txt": "pinned backend and worker dependencies",
    "backend/tests/test_dismeta_api.py": "production-boundary regression coverage",
    "backend/tests/test_lreca_process.py": "service-boundary regression coverage",
    "backend/tests/test_lreca_service.py": "independent LRECA service coverage",
    "backend/tests/test_module0.py": "deployment portability regression coverage",
    "backend/tests/test_module10_queue.py": "durable queue regression coverage",
    "backend/tests/test_module10_security.py": "production security regression coverage",
    "frontend/next.config.ts": "container frontend configuration",
    "frontend/package.json": "frontend production scripts and dependencies",
    "frontend/src/components/workspace.tsx": "production runtime status presentation",
    "frontend/tests/module10-production.test.ts": "production frontend regression coverage",
    "scripts/audit_docker_runtime.ps1": "Docker runtime audit harness",
    "scripts/audit_module10_scope.py": "Module 10 scope audit",
    "scripts/backup_db.sh": "PostgreSQL backup operation",
    "scripts/restore_db.sh": "PostgreSQL restore operation",
    "scripts/verify_deployment_static.py": "deployment static verification",
}

DEPLOYMENT_ADAPTATION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("docker/", "container image or reverse-proxy asset"),
    ("backend/lreca_service/", "independent LRECA service boundary"),
    ("docs/audit/module10/", "Module 10 generated audit evidence"),
    ("docs/module10", "Module 10 documentation or changed-file inventory"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    command = [
        "git",
        "--no-optional-locks",
        "-c",
        f"safe.directory={repository.resolve().as_posix()}",
        "-c",
        "core.quotepath=false",
        "-C",
        str(repository),
        *arguments,
    ]
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )


def require_git_output(repository: Path, *arguments: str) -> bytes:
    result = run_git(repository, *arguments)
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Git integrity check failed: {error}")
    return result.stdout


def git_inventory() -> dict[str, str]:
    """Hash the current first-party inventory without consulting Git status."""

    raw = require_git_output(
        ROOT,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    names = sorted({item for item in raw.decode("utf-8").split("\0") if item})
    inventory: dict[str, str] = {}
    for name in names:
        path = ROOT / Path(name)
        if path.is_file():
            inventory[Path(name).as_posix()] = sha256_file(path)
    return inventory


def load_baseline() -> dict[str, str]:
    raw: Any = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("Module 10 baseline must be a path-to-SHA256 object")
    baseline: dict[str, str] = {}
    for name, digest in raw.items():
        if not isinstance(name, str) or not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(
            digest
        ):
            raise ValueError("Module 10 baseline contains an invalid entry")
        baseline[Path(name).as_posix()] = digest
    return baseline


def deployment_reason(name: str) -> str | None:
    if name in GENERATED_OUTPUTS:
        return "Module 10 generated audit output"
    if name in DEPLOYMENT_ADAPTATION_EXACT:
        return DEPLOYMENT_ADAPTATION_EXACT[name]
    for prefix, reason in DEPLOYMENT_ADAPTATION_PREFIXES:
        if name.startswith(prefix):
            return reason
    return None


def classify_change(name: str) -> tuple[str, str]:
    if name in FROZEN_SCIENCE:
        domain, role = FROZEN_SCIENCE[name]
        return "frozen_science", f"{domain}: {role}"
    reason = deployment_reason(name)
    if reason is not None:
        return "deployment_adaptation", reason
    return "unexpected", "not in the reviewed Module 10 deployment adaptation allowlist"


def collect_changes(baseline: dict[str, str], current: dict[str, str]) -> list[dict[str, Any]]:
    # Generated outputs cannot hash themselves. Exclude them from the byte
    # comparison and add stable, explicit records after the comparison.
    names = (set(baseline) | set(current)) - GENERATED_OUTPUTS
    changes: list[dict[str, Any]] = []
    for name in sorted(names):
        before, after = baseline.get(name), current.get(name)
        if before == after:
            continue
        status = "added" if before is None else "deleted" if after is None else "modified"
        classification, reason = classify_change(name)
        changes.append(
            {
                "path": name,
                "status": status,
                "baseline_sha256": before,
                "current_sha256": after,
                "classification": classification,
                "reason": reason,
            }
        )
    for name in sorted(GENERATED_OUTPUTS):
        if name not in baseline:
            changes.append(
                {
                    "path": name,
                    "status": "added",
                    "baseline_sha256": None,
                    "current_sha256": None,
                    "classification": "deployment_adaptation",
                    "reason": "Module 10 generated audit output; self-hash intentionally omitted",
                    "generated_output": True,
                }
            )
    return sorted(changes, key=lambda row: row["path"])


def frozen_science_review(
    baseline: dict[str, str], current: dict[str, str]
) -> list[dict[str, Any]]:
    review = []
    for name, (domain, role) in FROZEN_SCIENCE.items():
        before = baseline.get(name)
        after = current.get(name)
        if before is None:
            state = "missing_from_baseline"
        elif after is None:
            state = "deleted"
        elif before != after:
            state = "modified"
        else:
            state = "unchanged"
        review.append(
            {
                "domain": domain,
                "role": role,
                "path": name,
                "baseline_sha256": before,
                "current_sha256": after,
                "status": state,
            }
        )
    return review


def parse_lreca_source_hashes(metadata_path: Path) -> dict[str, str]:
    tree = ast.parse(metadata_path.read_text(encoding="utf-8"), filename=metadata_path.name)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SOURCE_HASHES" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict) and all(
                isinstance(name, str) and isinstance(digest, str)
                for name, digest in value.items()
            ):
                return value
    raise ValueError("Could not read SOURCE_HASHES from LRECA metadata")


def parse_lreca_string_constant(metadata_path: Path, constant_name: str) -> str:
    tree = ast.parse(metadata_path.read_text(encoding="utf-8"), filename=metadata_path.name)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == constant_name for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError(f"Could not read {constant_name} from LRECA metadata")


def lreca_upstream_review() -> dict[str, Any]:
    checkout = ROOT / "external" / "lreca"
    manifest_path = ROOT / "external" / "lreca-source.json"
    metadata_path = ROOT / "backend" / "lreca_runtime" / "metadata.py"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_commit = manifest["LRECA_COMMIT"]
    expected_checkpoint_sha256 = manifest["LRECA_CHECKPOINT_SHA256"]
    checkpoint_relative = Path(manifest["LRECA_CHECKPOINT"])
    metadata_commit = parse_lreca_string_constant(metadata_path, "PINNED_COMMIT")
    metadata_checkpoint_sha256 = parse_lreca_string_constant(
        metadata_path, "CHECKPOINT_SHA256"
    )

    current_commit = require_git_output(checkout, "rev-parse", "HEAD").decode("utf-8").strip()
    status_lines = [
        line
        for line in require_git_output(
            checkout, "status", "--porcelain=v1", "--untracked-files=all"
        )
        .decode("utf-8", errors="replace")
        .splitlines()
        if line
    ]

    source_files = []
    for name, expected_digest in sorted(parse_lreca_source_hashes(metadata_path).items()):
        path = checkout / Path(name)
        actual_digest = sha256_file(path) if path.is_file() else None
        source_files.append(
            {
                "path": Path("external/lreca") / Path(name),
                "expected_sha256": expected_digest,
                "current_sha256": actual_digest,
                "status": "unchanged" if actual_digest == expected_digest else "mismatch",
            }
        )
    for row in source_files:
        row["path"] = Path(row["path"]).as_posix()

    checkpoint = checkout / checkpoint_relative
    checkpoint_digest = sha256_file(checkpoint) if checkpoint.is_file() else None
    checks_pass = (
        current_commit == expected_commit
        and metadata_commit == expected_commit
        and metadata_checkpoint_sha256 == expected_checkpoint_sha256
        and not status_lines
        and all(row["status"] == "unchanged" for row in source_files)
        and checkpoint_digest == expected_checkpoint_sha256
    )
    return {
        "status": "pass" if checks_pass else "fail",
        "checkout": "external/lreca",
        "expected_commit": expected_commit,
        "current_commit": current_commit,
        "metadata_commit": metadata_commit,
        "metadata_checkpoint_sha256": metadata_checkpoint_sha256,
        "working_tree_clean": not status_lines,
        "working_tree_entries": status_lines,
        "reviewed_source_files": source_files,
        "checkpoint": {
            "filename": checkpoint.name,
            "expected_sha256": expected_checkpoint_sha256,
            "current_sha256": checkpoint_digest,
            "status": "verified" if checkpoint_digest == expected_checkpoint_sha256 else "mismatch",
        },
    }


def checkpoint_tracking_review(current: dict[str, str]) -> dict[str, Any]:
    raw = require_git_output(ROOT, "ls-files", "-z", "--cached")
    tracked = sorted({item for item in raw.decode("utf-8").split("\0") if item})
    tracked_weights = [name for name in tracked if Path(name).suffix.lower() in WEIGHT_SUFFIXES]
    checkpoint_name = "human_1_RCNN_ECA_parallel_089-0.9802.pt"
    checkpoint_relative_path = (
        "external/lreca/Demo/trained_model/" + checkpoint_name
    )
    checkpoint_matches = [name for name in tracked if Path(name).name == checkpoint_name]
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required_ignore_rules = ["*.pt", "*.pth", "*.ckpt", "*.safetensors", "external/lreca/"]
    missing_ignore_rules = [rule for rule in required_ignore_rules if rule not in gitignore.splitlines()]
    unignored_weights = [
        name for name in current if Path(name).suffix.lower() in WEIGHT_SUFFIXES
    ]
    checkpoint_is_ignored = (
        run_git(ROOT, "check-ignore", "-q", "--", checkpoint_relative_path).returncode == 0
    )
    passed = (
        not tracked_weights
        and not checkpoint_matches
        and not unignored_weights
        and not missing_ignore_rules
        and checkpoint_is_ignored
    )
    return {
        "status": "pass" if passed else "fail",
        "scope": "first-party repository only; external/lreca is an ignored pinned checkout",
        "checkpoint_filename": checkpoint_name,
        "checkpoint_tracked_by_first_party_git": bool(checkpoint_matches),
        "checkpoint_path_ignored_by_first_party_git": checkpoint_is_ignored,
        "first_party_tracked_weight_files": tracked_weights,
        "first_party_unignored_weight_files": sorted(unignored_weights),
        "required_gitignore_rules": required_ignore_rules,
        "missing_gitignore_rules": missing_ignore_rules,
    }


def is_production_asset(name: str) -> bool:
    exact = {
        ".dockerignore",
        ".env.example",
        "compose.yaml",
        "compose.yml",
        "docker-compose.yml",
        "backend/.env.example",
        "backend/pyproject.toml",
        "backend/requirements.lock.txt",
        "backend/requirements-lreca-service.lock.txt",
        "frontend/next.config.ts",
        "frontend/package.json",
        "scripts/backup_db.sh",
        "scripts/restore_db.sh",
        "scripts/verify_deployment_static.py",
    }
    prefixes = (
        "backend/app/",
        "backend/lreca_runtime/",
        "backend/lreca_service/",
        "docker/",
        "frontend/src/",
    )
    return name in exact or name.startswith(prefixes)


def windows_absolute_path_review(current: dict[str, str]) -> dict[str, Any]:
    findings = []
    scanned = 0
    for name in sorted(current):
        if not is_production_asset(name):
            continue
        path = ROOT / Path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), start=1):
            if WINDOWS_ABSOLUTE_PATH.search(line):
                # Do not copy an internal absolute path into public audit output.
                findings.append({"path": name, "line": line_number})
    return {
        "status": "pass" if not findings else "fail",
        "scope": "production backend/frontend code, LRECA runtime/service, and deployment assets",
        "files_scanned": scanned,
        "findings": findings,
    }


def render_changed_files(changes: Iterable[dict[str, Any]], baseline_count: int) -> str:
    rows = list(changes)
    grouped = {
        status: [row["path"] for row in rows if row["status"] == status]
        for status in ("added", "modified", "deleted")
    }
    lines = [
        "Module 10 changed files",
        "",
        "Baseline: .audit/module10_baseline_files.json",
        f"Baseline files: {baseline_count}",
        "Comparison: baseline SHA256 manifest versus current file bytes; Git status is not used.",
        (
            f"Summary: {len(grouped['added'])} added, {len(grouped['modified'])} modified, "
            f"{len(grouped['deleted'])} deleted"
        ),
        "",
    ]
    for status, label in (("added", "ADDED"), ("modified", "MODIFIED"), ("deleted", "DELETED")):
        lines.append(f"[{label}]")
        lines.extend(grouped[status] or ["(none)"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    baseline = load_baseline()
    current = git_inventory()
    changes = collect_changes(baseline, current)
    frozen = frozen_science_review(baseline, current)
    lreca = lreca_upstream_review()
    checkpoint = checkpoint_tracking_review(current)
    windows_paths = windows_absolute_path_review(current)

    frozen_violations = [row["path"] for row in frozen if row["status"] != "unchanged"]
    unexpected = [row for row in changes if row["classification"] == "unexpected"]
    violations = []
    if frozen_violations:
        violations.append("frozen_science_changed")
    if unexpected:
        violations.append("unexpected_change_outside_deployment_allowlist")
    if checkpoint["status"] != "pass":
        violations.append("checkpoint_or_model_weight_tracked_or_unignored")
    if lreca["status"] != "pass":
        violations.append("external_lreca_checkout_changed_or_identity_mismatch")
    if windows_paths["status"] != "pass":
        violations.append("production_asset_contains_windows_absolute_path")

    counts = {
        status: sum(row["status"] == status for row in changes)
        for status in ("added", "modified", "deleted")
    }
    deployment_adaptations = [
        {
            "path": row["path"],
            "status": row["status"],
            "reason": row["reason"],
        }
        for row in changes
        if row["classification"] == "deployment_adaptation"
    ]
    report = {
        "module": 10,
        "audit_date": datetime.now(UTC).date().isoformat(),
        "status": "pass" if not violations else "fail",
        "baseline": {
            "source": ".audit/module10_baseline_files.json",
            "file_count": len(baseline),
            "comparison_method": (
                "immutable baseline SHA256 manifest versus current bytes; current Git status is not "
                "used as the Module 10 baseline"
            ),
        },
        "summary": {
            **counts,
            "total_changed": len(changes),
            "frozen_science_files_reviewed": len(frozen),
            "frozen_science_violations": len(frozen_violations),
            "unexpected_changes": len(unexpected),
        },
        "changes": changes,
        "deployment_adaptations": deployment_adaptations,
        "unexpected_changes": unexpected,
        "frozen_science_review": frozen,
        "checks": {
            "checkpoint_git_tracking": checkpoint,
            "external_lreca": lreca,
            "windows_absolute_paths": windows_paths,
        },
        "generated_outputs": sorted(GENERATED_OUTPUTS),
        "violations": violations,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHANGED_FILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHANGED_FILES_PATH.write_text(
        render_changed_files(changes, len(baseline)), encoding="utf-8", newline="\n"
    )
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status": report["status"], **report["summary"]}, ensure_ascii=False))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
