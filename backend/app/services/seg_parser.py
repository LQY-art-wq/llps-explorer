"""Parse the real NCBI interval format; this module does not implement SEG."""

import re

from app.schemas.seg import SEGError, SEGRegion

_INTERVAL = re.compile(r"(-?[0-9]+) - (-?[0-9]+)\Z")
_HEADER = re.compile(r"[A-Za-z0-9_.:-]+\Z")


def parse_seg_intervals(
    raw: str | bytes, sequence_length: int, expected_header: str = "query"
) -> list[SEGRegion]:
    """Convert zero-based closed intervals to one-based closed intervals.

    Preserve native ordering, duplicates, overlaps, and adjacent segments.
    SEG's default overlap-merging option is disabled; coverage is computed
    separately from the union in SEGResult.
    """
    if type(sequence_length) is not int or not 1 <= sequence_length <= 2147483647:
        raise SEGError(
            "SEG_INVALID_OUTPUT", "A valid sequence length is required to check SEG output."
        )
    if not isinstance(expected_header, str) or not _HEADER.fullmatch(expected_header):
        raise SEGError("SEG_INVALID_OUTPUT", "The expected SEG record identifier is invalid.")
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SEGError("SEG_PARSE_ERROR", "SEG output is not valid UTF-8 text.") from exc
    if not isinstance(raw, str):
        raise SEGError("SEG_PARSE_ERROR", "SEG output must be text or bytes.")
    normalized = raw.replace("\r\n", "\n")
    if "\r" in normalized:
        raise SEGError("SEG_PARSE_ERROR", "SEG output contains invalid line endings.")
    lines = normalized.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != ">" + expected_header:
        raise SEGError("SEG_PARSE_ERROR", "SEG output must contain the expected single record.")
    regions = []
    for line in lines[1:]:
        match = _INTERVAL.fullmatch(line)
        if match is None:
            raise SEGError("SEG_PARSE_ERROR", "SEG output contains an invalid interval record.")
        tokens = match.groups()
        if any(len(token) > 11 for token in tokens):
            raise SEGError("SEG_INVALID_OUTPUT", "SEG coordinates exceed the supported sequence.")
        start, end = map(int, tokens)
        if not 0 <= start <= end < sequence_length:
            raise SEGError(
                "SEG_INVALID_OUTPUT", "SEG coordinates are outside the supplied sequence."
            )
        regions.append(SEGRegion(start=start + 1, end=end + 1))
    return regions
