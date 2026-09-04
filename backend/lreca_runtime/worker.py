"""One persistent scientific process with a private JSON-lines pipe protocol."""

from __future__ import annotations

import contextlib
import json
import sys
import traceback
from typing import Any


def main() -> None:
    engine = None
    output = sys.stdout
    for line in sys.stdin:
        request_id = None
        operation = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            operation = request["operation"]
            payload: dict[str, Any] = request.get("payload", {})
            # Official definitions may print diagnostics; stdout is IPC only.
            with contextlib.redirect_stdout(sys.stderr):
                if operation == "shutdown":
                    result = {"closed": True}
                elif operation == "load":
                    if engine is None:
                        from .engine import LRECAEngine

                        engine = LRECAEngine(payload)
                    metadata = engine.load()
                    result = {"metadata": metadata, "device": engine.device_name, "loaded": True}
                elif engine is None or engine.model is None:
                    raise RuntimeError("LRECA must be loaded before inference")
                elif operation == "predict_global":
                    result = engine.predict_global(payload["sequence"])
                elif operation == "compute_attribution":
                    result = engine.compute_attribution(payload["sequence"])
                elif operation == "compute_kde":
                    result = engine.compute_kde(payload["scores"])
                elif operation == "analyze":
                    result = engine.analyze(
                        payload["sequence"],
                        include_attribution=payload.get("include_attribution", True),
                        include_kde=payload.get("include_kde", True),
                    )
                elif operation == "diagnostics":
                    result = engine.diagnostics()
                else:
                    raise ValueError(f"Unknown LRECA worker operation: {operation}")
            response = {"id": request_id, "ok": True, "result": result}
            serialized = json.dumps(response, ensure_ascii=True, allow_nan=False)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            serialized = json.dumps(
                {
                    "id": request_id,
                    "ok": False,
                    "error": {"type": type(error).__name__, "message": str(error)[:4000]},
                },
                ensure_ascii=True,
                allow_nan=False,
            )
        output.write(serialized + "\n")
        output.flush()
        if operation == "shutdown":
            break


if __name__ == "__main__":
    main()
