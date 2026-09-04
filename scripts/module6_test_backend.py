"""Explicit test-only server for the browser partial-success scenario.

Run from the project root with --fail-seg. LRECA and all application services
remain real; only SEG.analyze is replaced with a deliberate runtime failure.
Importing this module never creates an application or starts a server.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]
TEST_NOTICE = (
    "MODULE 6 TEST ONLY: SEG analysis failure is injected; "
    "LRECA inference, SEG health, and analysis orchestration remain real."
)


class Module6InjectedSEGFailure(RuntimeError):
    """Recognizable private exception; normal orchestration publishes a safe error."""


def create_test_app(*, fail_seg: bool, settings: Settings | None = None) -> FastAPI:
    """No ungated app export, production setting, or alternative predictor."""
    if fail_seg is not True:
        raise ValueError("The test server requires explicit --fail-seg authorization.")

    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)

    from app.adapters.seg import SEGAdapter
    from app.core.config import Settings
    from app.main import create_app
    from app.schemas.seg import SEGResult
    from app.services.sequence_validation import normalize_sequence

    class FailingSEGAdapter(SEGAdapter):
        async def analyze(self, sequence: str) -> SEGResult:
            normalize_sequence(sequence)
            raise Module6InjectedSEGFailure("Module 6 browser test: deliberate SEG failure.")

    settings = settings or Settings(_env_file=ROOT / ".env")
    # Resolve configured relative runtime paths against this project, not the caller's cwd.
    updates = {}
    for field in ("lreca_python", "lreca_checkpoint", "lreca_repository"):
        value = Path(getattr(settings, field))
        if not value.is_absolute():
            updates[field] = ROOT / value
    seg_path = settings.seg_executable_path
    if not seg_path.is_absolute() and seg_path.parent != Path("."):
        updates["seg_executable_path"] = ROOT / seg_path
    if updates:
        settings = settings.model_copy(update=updates)
    # The normal factory creates the resident LRECA adapter during its own lifespan.
    return create_app(settings, seg_adapter=FailingSEGAdapter(settings))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=TEST_NOTICE)
    parser.add_argument(
        "--fail-seg", action="store_true", required=True,
        help="Explicitly inject SEG analysis failure for the Module 6 browser test.",
    )
    parser.add_argument("--port", type=int, default=8001, help="Loopback test port (default 8001).")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")

    import uvicorn

    print(TEST_NOTICE, flush=True)
    uvicorn.run(
        create_test_app(fail_seg=args.fail_seg),
        host="127.0.0.1", port=args.port, workers=1, access_log=False,
    )


if __name__ == "__main__":
    main()
