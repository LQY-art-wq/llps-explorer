"""Test-only injection guard and wiring; no model, executable, or HTTP server is run."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.adapters.seg import SEGAdapter
from app.core.config import Settings
from app.services.sequence_validation import SequenceValidationError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "module6_test_backend.py"
spec = importlib.util.spec_from_file_location("module6_test_backend", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_failure_server_requires_explicit_opt_in_before_application_creation(monkeypatch):
    import app.main

    calls = []
    monkeypatch.setattr(app.main, "create_app", lambda *args, **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError, match="--fail-seg"):
        module.create_test_app(fail_seg=False)
    with pytest.raises(SystemExit) as error:
        module.main([])
    assert error.value.code == 2
    assert calls == []


def test_injection_changes_only_seg_analysis_and_keeps_the_real_factory_defaults(monkeypatch):
    import app.main

    calls = []

    def capture(settings, **kwargs):
        calls.append((settings, kwargs))
        return "unstarted-test-application"

    monkeypatch.setattr(app.main, "create_app", capture)
    result = module.create_test_app(fail_seg=True, settings=Settings(_env_file=None))
    assert result == "unstarted-test-application"
    settings, kwargs = calls[0]
    assert set(kwargs) == {"seg_adapter"}  # LRECA remains the actual factory default.
    adapter = kwargs["seg_adapter"]
    assert adapter.settings is settings
    assert isinstance(adapter, SEGAdapter)
    assert adapter.load.__func__ is SEGAdapter.load
    assert adapter.healthcheck.__func__ is SEGAdapter.healthcheck
    assert adapter.close.__func__ is SEGAdapter.close
    with pytest.raises(module.Module6InjectedSEGFailure, match="deliberate SEG failure"):
        asyncio.run(adapter.analyze("ACD"))
    with pytest.raises(SequenceValidationError):
        asyncio.run(adapter.analyze("ACX"))


def test_relative_paths_are_project_relative_and_bare_seg_command_stays_on_path(monkeypatch):
    import app.main

    calls = []
    monkeypatch.setattr(app.main, "create_app", lambda settings, **kwargs: calls.append(settings))
    settings = Settings(
        _env_file=None, lreca_python=Path("runtime/python"),
        lreca_checkpoint=Path("weights/human.pt"), lreca_repository=Path("external/lreca"),
        seg_executable_path=Path("segmasker"),
    )
    module.create_test_app(fail_seg=True, settings=settings)
    assert calls[0].lreca_python == module.ROOT / "runtime" / "python"
    assert calls[0].lreca_checkpoint == module.ROOT / "weights" / "human.pt"
    assert calls[0].seg_executable_path == Path("segmasker")
    module.create_test_app(
        fail_seg=True,
        settings=settings.model_copy(update={"seg_executable_path": Path("tools/segmasker")}),
    )
    assert calls[1].seg_executable_path == module.ROOT / "tools" / "segmasker"
