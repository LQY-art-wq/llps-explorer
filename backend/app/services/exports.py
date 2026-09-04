"""Pure export mappings over persisted normalized results; no scientific recomputation."""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from urllib.parse import quote

from app.schemas.orchestration import AnalysisJob


def _execution_result(job: AnalysisJob, method: str):
    execution = job.methods.get(method)
    return execution.result if execution is not None else None


def _inside(position: int, regions) -> bool:
    return bool(regions) and any(region.start <= position <= region.end for region in regions)


def _membership(position: int, regions) -> str:
    if regions is None:
        return ""
    return str(_inside(position, regions)).lower()


def _value(value) -> str:
    return "" if value is None else str(value)


def _spreadsheet_safe(value: str | None) -> str:
    text = value or ""
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _dismeta_status(job: AnalysisJob) -> str:
    execution = job.methods.get("dismeta")
    if execution is None:
        return "Not selected"
    if execution.reason == "service_restart" or (
        execution.error is not None and execution.error.code == "ANALYSIS_INTERRUPTED"
    ):
        return "Interrupted"
    return execution.status.replace("_", " ").capitalize()


def safe_stem(sequence_name: str | None) -> str:
    name = unicodedata.normalize("NFKC", sequence_name or "protein")
    name = re.sub(r"\s+", "_", name)
    name = "".join(character for character in name if character.isalnum() or character in "._-")
    name = name.strip("._-")[:64]
    return name or "protein"


def attachment_header(job: AnalysisJob, suffix: str) -> str:
    stem = safe_stem(job.sequence.name)
    filename = f"{stem}_{job.job_id}{suffix}"
    ascii_stem = "".join(c for c in stem if c.isascii() and (c.isalnum() or c in "._-"))
    ascii_name = f"{ascii_stem or 'protein'}_{job.job_id}{suffix}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def json_export(job: AnalysisJob) -> bytes:
    payload = {
        "export_metadata": {
            "format": "llps_analysis_result",
            "export_schema_version": "1.0",
            "coordinate_system": "one_based_inclusive",
        },
        "analysis": job.model_dump(mode="json", warnings=False),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _csv(rows: list[list[object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def residues_csv(job: AnalysisJob) -> bytes:
    sequence = job.normalized_sequence
    if sequence is None:
        raise ValueError("Persisted sequence is unavailable")
    lreca = _execution_result(job, "lreca")
    fuzdrop = _execution_result(job, "fuzdrop")
    seg = _execution_result(job, "seg")
    attribution = {
        residue.position: residue.score
        for residue in (getattr(lreca, "residue_attribution", None) or [])
    }
    kde_values = getattr(getattr(lreca, "kde", None), "values", None)
    critical = getattr(lreca, "critical_regions", None)
    fuz_propensity = {
        residue.position: residue.score
        for residue in (getattr(fuzdrop, "residue_propensity", None) or [])
    }
    fuz_regions = getattr(fuzdrop, "regions", None)
    seg_regions = getattr(seg, "regions", None)
    dismeta_status = _dismeta_status(job)
    rows: list[list[object]] = [
        [
            "Position",
            "AA",
            "LRECA_Attribution",
            "LRECA_KDE",
            "LRECA_Critical_Region",
            "LRECA_Primary_Region",
            "FuzDrop_Propensity",
            "FuzDrop_Region",
            "SEG_LCR",
            "DisMeta_IDR_Status",
        ]
    ]
    for position, aa in enumerate(sequence, start=1):
        primary = (
            ""
            if critical is None
            else str(
                any(
                    region.start <= position <= region.end and region.is_primary
                    for region in critical
                )
            ).lower()
        )
        rows.append(
            [
                position,
                aa,
                _value(attribution.get(position)),
                _value(kde_values[position - 1] if kde_values is not None else None),
                _membership(position, critical),
                primary,
                _value(fuz_propensity.get(position)),
                _membership(position, fuz_regions),
                _membership(position, seg_regions),
                dismeta_status,
            ]
        )
    return _csv(rows)


def regions_csv(job: AnalysisJob) -> bytes:
    rows: list[list[object]] = [
        ["Method", "Region_Type", "Start", "End", "Length", "Score", "Primary", "Source"]
    ]
    lreca = _execution_result(job, "lreca")
    for region in getattr(lreca, "critical_regions", None) or []:
        rows.append(
            [
                "LRECA",
                "Primary KDE hotspot" if region.is_primary else "Candidate KDE hotspot",
                region.start,
                region.end,
                region.length,
                region.score,
                str(region.is_primary).lower(),
                "LRECA KDE",
            ]
        )
    fuzdrop = _execution_result(job, "fuzdrop")
    for region in getattr(fuzdrop, "regions", None) or []:
        rows.append(
            [
                "FuzDrop",
                region.official_type,
                region.start,
                region.end,
                region.length,
                "",
                "",
                "manual_import_of_official_result",
            ]
        )
    seg = _execution_result(job, "seg")
    for region in getattr(seg, "regions", None) or []:
        rows.append(
            ["SEG", "LCR", region.start, region.end, region.length, "", "", "NCBI segmasker"]
        )
    return _csv(rows)


def summary_csv(job: AnalysisJob) -> bytes:
    lreca = _execution_result(job, "lreca")
    fuzdrop = _execution_result(job, "fuzdrop")
    seg = _execution_result(job, "seg")
    provenance = {}
    if lreca is not None:
        provenance["lreca"] = {
            "model_variant": lreca.model_variant,
            "repository_commit": lreca.repository_commit,
            "checkpoint": lreca.checkpoint,
            "checkpoint_sha256": lreca.checkpoint_sha256,
            "threshold": lreca.threshold,
            "kde_prominence": lreca.kde.prominence if lreca.kde else None,
        }
    if seg is not None:
        provenance["seg"] = {
            "implementation": seg.implementation,
            "version": seg.version,
            "parameters": seg.parameters.model_dump(mode="json"),
        }
    if fuzdrop is not None:
        provenance["fuzdrop"] = {
            "source": fuzdrop.source,
            "coordinate_verification": fuzdrop.coordinate_verification,
        }
    headers = [
        "Sequence_Name",
        "Length",
        "LRECA_Score",
        "LRECA_Label",
        "FuzDrop_Score",
        "FuzDrop_Label",
        "Ensemble_Score",
        "Ensemble_Label",
        "LCR_Coverage",
        "Analysis_Timestamp",
        "Model_Provenance",
        "Result_Schema_Version",
    ]
    return _csv(
        [
            headers,
            [
                _spreadsheet_safe(job.sequence.name),
                job.sequence.length,
                _value(getattr(lreca, "raw_score", None)),
                _value(getattr(lreca, "label", None)),
                _value(getattr(fuzdrop, "raw_score", None)),
                _value(getattr(fuzdrop, "label", None)),
                _value(job.ensemble.score if job.ensemble else None),
                _value(job.ensemble.label if job.ensemble else None),
                _value(getattr(seg, "coverage", None)),
                job.created_at.isoformat(),
                json.dumps(provenance, ensure_ascii=False, separators=(",", ":")),
                job.result_schema_version,
            ],
        ]
    )


def fasta_export(job: AnalysisJob) -> bytes:
    sequence = job.normalized_sequence
    if sequence is None:
        raise ValueError("Persisted sequence is unavailable")
    name = safe_stem(job.sequence.name) if job.sequence.name else f"analysis_{job.job_id}"
    lines = [f">{name}|{job.job_id}"]
    lines.extend(sequence[index : index + 60] for index in range(0, len(sequence), 60))
    return ("\n".join(lines) + "\n").encode("utf-8")
