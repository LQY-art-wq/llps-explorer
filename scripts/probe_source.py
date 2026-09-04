"""Low-volume, GET-only audit of explicitly supplied public source URLs.

This does not submit sequences, discover hidden endpoints, or execute page code.
TLS verification remains enabled. No cookies or credentials are persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 16 * 1024 * 1024


def probe(url: str) -> dict:
    record = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "method": "GET",
        "url": url,
    }
    request = Request(url, headers={"User-Agent": "LLPS-Explorer-Module0-Audit/0.1"})
    try:
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read(MAX_BYTES + 1)
            record.update(
                status=response.status,
                final_url=response.url,
                content_type=response.headers.get("Content-Type"),
                set_cookie_present=bool(response.headers.get("Set-Cookie")),
                retry_after=response.headers.get("Retry-After"),
                allow=response.headers.get("Allow"),
                rate_limit_remaining=response.headers.get("X-RateLimit-Remaining"),
                bytes=len(body),
            )
            if len(body) > MAX_BYTES:
                record["error"] = "Response exceeds the 16 MiB audit limit; not cached."
            else:
                filename = hashlib.sha256(url.encode()).hexdigest()[:16] + ".txt"
                target = ROOT / ".audit" / "http" / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                record["sha256"] = hashlib.sha256(body).hexdigest()
                record["cache"] = target.relative_to(ROOT).as_posix()
    except (URLError, TimeoutError, OSError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    output = ROOT / "docs" / "audit" / "http_observations.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    for url in args.urls:
        if not url.startswith(("https://", "http://")):
            parser.error("Only explicitly supplied HTTP(S) source URLs are accepted.")
        print(json.dumps(probe(url), ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
