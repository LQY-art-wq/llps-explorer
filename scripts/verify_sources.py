"""Verify the Module 0 LRECA checkout and hashes without importing model code."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def verify() -> dict:
    manifest = json.loads((ROOT / "external/lreca-source.json").read_text(encoding="utf-8"))
    checkout = ROOT / manifest["local_checkout"]
    commit = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True, encoding="utf-8"
    ).strip()
    if commit != manifest["LRECA_COMMIT"]:
        raise ValueError(f"Unexpected LRECA commit: {commit}")
    dirty = subprocess.check_output(
        ["git", "-C", str(checkout), "status", "--porcelain"], text=True, encoding="utf-8"
    ).strip()
    if dirty:
        raise ValueError("The audited upstream checkout has local changes")
    inventory = json.loads((ROOT / manifest["checkpoint_inventory"]).read_text(encoding="utf-8"))
    for item in inventory:
        path = checkout / item["path"]
        if path.stat().st_size != item["size_bytes"] or sha256(path) != item["sha256"]:
            raise ValueError(f"Checkpoint checksum mismatch: {item['path']}")
    selected = checkout / manifest["LRECA_CHECKPOINT"]
    if sha256(selected) != manifest["LRECA_CHECKPOINT_SHA256"]:
        raise ValueError("Selected human checkpoint does not match its provenance")
    vocab = json.loads((ROOT / manifest["vocabulary_audit"]).read_text(encoding="utf-8"))
    for item in vocab["files"]:
        if sha256(checkout / item["path"]) != item["sha256"]:
            raise ValueError(f"Vocabulary source changed: {item['path']}")
    return {
        "status": "verified",
        "commit": commit,
        "checkpoints_verified": len(inventory),
        "vocabulary_source_files_verified": len(vocab["files"]),
        "selected_checkpoint_sha256": manifest["LRECA_CHECKPOINT_SHA256"],
        "inference_executed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
