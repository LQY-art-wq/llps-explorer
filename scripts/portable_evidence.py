"""Export reproducible evidence without embedding a workstation's home path.

Execution still uses resolved local paths. Only public provenance strings use
${PROJECT_ROOT}, ${USERPROFILE} (Windows), or ${HOME} (other platforms).
Original exported logs remain byte-for-byte available in the ignored archive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ARCHIVE = ROOT / ".audit" / "module1_private_evidence"


def portable_text(value: str) -> str:
    replacements = []
    sources = [(ROOT, "${PROJECT_ROOT}")]
    for name in (
        "USERPROFILE",
        "HOME",
        "LRECA_REPOSITORY",
        "LRECA_CHECKPOINT_PATH",
        "LRECA_CHECKPOINT",
        "LRECA_PYTHON",
    ):
        configured = os.environ.get(name)
        if configured and Path(configured).is_absolute():
            sources.append((Path(configured), "${" + name + "}"))
    for path, reference in sources:
        variants = {str(path), path.as_posix()}
        variants.update(json.dumps(item, ensure_ascii=False)[1:-1] for item in tuple(variants))
        variants.update(json.dumps(item, ensure_ascii=True)[1:-1] for item in tuple(variants))
        replacements.extend((item, reference) for item in variants)
    result = value
    for literal, reference in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        result = re.sub(re.escape(literal), lambda _: reference, result, flags=re.IGNORECASE)
    if result.startswith("${") and "\n" not in result:
        result = result.replace("\\", "/")
    return result


def portable(value):
    if isinstance(value, Path):
        return portable_text(str(value))
    if isinstance(value, str):
        return portable_text(value)
    if isinstance(value, dict):
        return {portable_text(str(key)): portable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [portable(item) for item in value]
    return value


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(portable(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def archive_original(path: Path) -> dict:
    source = path.resolve()
    relative = source.relative_to(ROOT)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    target = PRIVATE_ARCHIVE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw:
        target = target.with_name(f"{target.name}.{digest}")
    if not target.exists():
        with target.open("xb") as handle:
            handle.write(raw)
    if target.read_bytes() != raw:
        raise RuntimeError("Evidence archive did not preserve the original bytes")
    return {
        "source": relative.as_posix(),
        "original_sha256": digest,
        "original_size_bytes": len(raw),
        "private_archive": target.relative_to(ROOT).as_posix(),
    }


def export_log(path: Path) -> dict | None:
    raw = path.read_bytes()
    original = raw.decode("utf-8")
    sanitized = portable_text(original)
    if sanitized == original and original.startswith("# Sanitized exported log:"):
        return None
    record = archive_original(path)
    header = (
        "# Sanitized exported log: workstation paths replaced with environment references.\n"
        f"# Original bytes retained privately: {record['private_archive']}\n"
    )
    path.write_text(header + sanitized, encoding="utf-8", newline="\n")
    return record


def install_portable_excepthook(script_name: str) -> None:
    """Keep full raw tracebacks private while exporting useful relative traces."""

    def hook(exception_type, exception, tb):
        original = "".join(traceback.format_exception(exception_type, exception, tb))
        raw = original.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        target = PRIVATE_ARCHIVE / "exceptions" / f"{script_name}.{digest}.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as handle:
                handle.write(raw)
        sys.stderr.write(
            "# Sanitized exported traceback; original bytes retained privately at "
            + target.relative_to(ROOT).as_posix()
            + "\n"
            + portable_text(original)
        )

    sys.excepthook = hook
