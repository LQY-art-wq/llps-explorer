"""Deployment contract checks; these do not claim Linux execution on Windows."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from app.core.config import LRECA_PYTHON, PROJECT_ROOT, Settings
from lreca_runtime.metadata import CHECKPOINT_NAME, resolve_project_path

MODEL_SUFFIXES = {
    ".pt",
    ".pth",
    ".ckpt",
    ".safetensors",
    ".onnx",
    ".h5",
    ".hdf5",
    ".pkl",
    ".pickle",
    ".bin",
}


def git_read(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-c",
            f"safe.directory={PROJECT_ROOT.as_posix()}",
            *arguments,
        ],
        cwd=PROJECT_ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_checkpoint_path_environment_alias_precedence(monkeypatch, tmp_path):
    preferred = tmp_path / "mounted-models" / CHECKPOINT_NAME
    legacy = tmp_path / "legacy-models" / CHECKPOINT_NAME
    monkeypatch.setenv("LRECA_CHECKPOINT_PATH", str(preferred))
    monkeypatch.setenv("LRECA_CHECKPOINT", str(legacy))
    assert Settings(_env_file=None).lreca_checkpoint == preferred
    monkeypatch.delenv("LRECA_CHECKPOINT_PATH")
    assert Settings(_env_file=None).lreca_checkpoint == legacy


def test_relative_paths_do_not_depend_on_cwd_or_user_home(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: pytest.fail("No home lookup")))
    relative = Path("models") / "lreca" / CHECKPOINT_NAME
    assert resolve_project_path(relative) == (PROJECT_ROOT / relative).resolve()
    absolute = tmp_path / CHECKPOINT_NAME
    assert resolve_project_path(absolute) == absolute.resolve()


def test_default_worker_executable_is_composed_from_project_and_platform():
    relative = Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python"
    assert LRECA_PYTHON == PROJECT_ROOT / ".lreca-venv" / relative


def test_model_artifacts_are_ignored_at_every_project_location():
    candidates = [f"test-ignore-only/human{suffix}" for suffix in sorted(MODEL_SUFFIXES)] + [
        f"models/lreca/{CHECKPOINT_NAME}",
        f"backend/tests/fixtures/{CHECKPOINT_NAME}",
        f"external/lreca/Demo/trained_model/{CHECKPOINT_NAME}",
    ]
    # NUL delimiters avoid Windows text-mode CRLF translation and Git path quoting.
    result = git_read(
        "check-ignore", "--no-index", "-z", "--stdin", input_text="\0".join(candidates) + "\0"
    )
    assert result.returncode == 0, result.stderr
    assert set(filter(None, result.stdout.split("\0"))) == set(candidates)


def test_no_model_weights_are_tracked_by_the_project_repository():
    result = git_read("ls-files", "-z", "--cached")
    assert result.returncode == 0, result.stderr
    tracked = result.stdout.split("\0")
    assert not [name for name in tracked if Path(name).suffix.lower() in MODEL_SUFFIXES]
    assert not [name for name in tracked if name.startswith("external/lreca/")]


def test_runtime_contains_no_hardcoded_windows_drive_or_user_home_lookup():
    roots = (PROJECT_ROOT / "backend/app", PROJECT_ROOT / "backend/lreca_runtime")
    violations = []
    for root in roots:
        for path in root.rglob("*.py"):
            syntax = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(syntax):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                    if (
                        len(value) >= 3
                        and value[0].isalpha()
                        and value[1] == ":"
                        and (value[2] == "/" or ord(value[2]) == 92)
                    ):
                        violations.append(f"{path.name}:{node.lineno}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in {"home", "expanduser"}:
                        violations.append(f"{path.name}:{node.lineno}")
    assert violations == []


def test_future_docker_context_excludes_local_runtime_secrets_and_weights():
    lines = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    patterns = {line for line in lines if line and not line.startswith("#")}
    assert {".audit", ".venv", ".lreca-venv", ".env", "external/lreca"} <= patterns
    assert {f"**/*{suffix}" for suffix in MODEL_SUFFIXES} <= patterns
