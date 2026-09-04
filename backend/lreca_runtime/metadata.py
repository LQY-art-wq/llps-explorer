"""Verify the pinned model identity before loading weights (standard library only)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "https://github.com/ai-phasepro/LRECA"
PINNED_COMMIT = "0b4b48ab7870529a34028c6e30dfba42eddbf215"
CHECKPOINT_NAME = "human_1_RCNN_ECA_parallel_089-0.9802.pt"
CHECKPOINT_SHA256 = "aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc"
CHECKPOINT_SIZE_BYTES = 2395318
CHECKPOINT_RELATIVE_PATH = "Demo/trained_model/" + CHECKPOINT_NAME
# Keep reviewed paths and their complete audit hashes on separate lines.
# fmt: off
SOURCE_HASHES = {
    "Demo/code_for_model_testing/RCNN_ECA_personal_test.py":
        "abcb72672a69a0758c08c557ca0e886d451a8f9aabf7f5bce92591e526cb7669",
    "Demo/code_for_model_testing/RCNN_ECA_3_human_test.py":
        "68a5b205d41f26610e08a3b2eccd326d22d74d4083ca7c33f2c64789a7093c4b",
    "Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/verify/"
    "RCNN_ECA_saliency_verify_gradCAM_fortest.py":
        "8645491541fb1cb56382b5b43bb6f704ec42bd0fb41aa32899f39f9fd2993815",
    "Demo/code_for_model_testing/RCNN_ECA_saliency/LCRs_process/"
    "split_LCRs_segment_forsingle.py":
        "cd51cb2386fc0fbbad5f514788218d0087d3abd39e4dd128050054e98146b090",
    "Data/pos_dataset/pos_word_list_human.txt":
        "1e3beca27c80a5fc59c41bbb5cc40f429a0619bd3dcc6172a42dbe85cd90ad32",
    "Data/neg_dataset/neg_word_list_human.txt":
        "e793a6eaa512e42ab72dd236cdaf13d20e14c3971def800b3aabc261193da1ea",
}
# fmt: on


def resolve_project_path(path: str | Path) -> Path:
    # Relative configuration is rooted in the package's project layout, never
    # the process working directory or the current user's home directory.
    value = Path(path)
    return (value if value.is_absolute() else PROJECT_ROOT / value).resolve()


def _git(repository: Path, *arguments: str) -> str:
    # Trust only this configured directory for this read-only invocation. This
    # does not change global Git configuration or the original checkout.
    command = [
        "git",
        "--no-optional-locks",
        "-c",
        f"safe.directory={repository.as_posix()}",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository),
        *arguments,
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise ValueError(f"Unable to verify pinned LRECA repository: {result.stderr.strip()}")
    return result.stdout.strip()


def get_lreca_model_metadata(
    checkpoint_path: str | Path | None = None, repository_path: str | Path | None = None
) -> dict[str, Any]:
    repository = resolve_project_path(repository_path or "external/lreca")
    configured = str(checkpoint_path or repository / CHECKPOINT_RELATIVE_PATH)
    checkpoint = resolve_project_path(configured)
    commit = _git(repository, "rev-parse", "HEAD")
    if commit != PINNED_COMMIT:
        raise ValueError(f"LRECA commit mismatch: expected {PINNED_COMMIT}, got {commit}")
    if _git(repository, "status", "--porcelain=v1", "--untracked-files=no"):
        raise ValueError("Pinned LRECA tracked source has local modifications")
    if not checkpoint.is_file():
        raise FileNotFoundError(f"LRECA checkpoint is missing: {checkpoint}")
    size = checkpoint.stat().st_size
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if size != CHECKPOINT_SIZE_BYTES or digest != CHECKPOINT_SHA256:
        raise ValueError("LRECA checkpoint checksum or size does not match the Module 0 audit")
    source_files = {}
    for relative, expected in SOURCE_HASHES.items():
        path = repository / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Pinned LRECA source checksum mismatch: {relative}")
        source_files[relative] = {"sha256": actual, "size_bytes": path.stat().st_size}
    versions = {}
    for package in ("torch", "numpy", "scipy", "scikit-learn", "pandas", "psutil"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "repository": REPOSITORY,
        "commit": commit,
        "model_variant": "human_specific",
        "dataset5_mapping_status": "unconfirmed",
        "checkpoint": CHECKPOINT_NAME,
        "checkpoint_path": str(checkpoint),
        "configured_checkpoint_path": configured,
        "checkpoint_sha256": digest,
        "checkpoint_size_bytes": size,
        "source_files": source_files,
        "runtime": {"python": platform.python_version(), "packages": versions},
    }
