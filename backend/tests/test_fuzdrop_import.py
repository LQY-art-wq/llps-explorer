"""Offline contract tests using synthetic format fixtures, never real predictions."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.fuzdrop import (
    FuzDropHealth,
    FuzDropImportRequest,
    FuzDropResult,
    FuzDropResultResponse,
    FuzDropUnavailableResult,
)
from app.services.fuzdrop_import import FuzDropImportError, import_fuzdrop_result

FIXTURES = Path(__file__).parent / "fixtures" / "fuzdrop"
# Arbitrary canonical pattern; this is not a biological example or a model output.
SYNTHETIC_SEQUENCE = "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEF"
SCORES = (FIXTURES / "synthetic_format_fixture_scores.tsv").read_text(encoding="utf-8")
REGIONS = (FIXTURES / "synthetic_format_fixture_regions.tsv").read_text(encoding="utf-8")


def payload(**updates):
    value = {
        "sequence": SYNTHETIC_SEQUENCE,
        "source_declaration": "official_fuzdrop_export",
        "coordinate_system": "one_based_inclusive",
        "scores_tsv": SCORES,
    }
    value.update(updates)
    return value


def score_cell(column: int, value: str, *, row: int = 1) -> str:
    lines = SCORES.splitlines()
    cells = lines[row].split("\t")
    cells[column] = value
    lines[row] = "\t".join(cells)
    return "\n".join(lines)


def assert_import_error(value, code, **kwargs):
    with pytest.raises(FuzDropImportError) as caught:
        import_fuzdrop_result(value, **kwargs)
    assert caught.value.detail["code"] == code
    return caught.value


def test_synthetic_format_fixture_is_imported_with_explicit_unverified_provenance():
    before = datetime.now(timezone.utc)
    result = import_fuzdrop_result(payload(regions_tsv=REGIONS, pLLPS=0.6))
    after = datetime.now(timezone.utc)
    assert result.status == "success"
    assert result.sequence == SYNTHETIC_SEQUENCE
    assert result.sequence_length == 45
    assert result.raw_score == result.calibrated_score == 0.6
    assert (result.label, result.threshold, result.threshold_operator) == ("P", 0.6, ">=")
    assert result.calibration_status == "not_calibrated"
    assert result.source == "manual_import_of_official_result"
    assert result.origin_verification == "user_declared_not_independently_verified"
    assert result.coordinate_verification == "user_declared_not_independently_verified"
    assert result.retrieved_at is result.service_version is None
    assert before <= result.imported_at <= after
    assert result.imported_at.utcoffset().total_seconds() == 0
    assert result.runtime_scope == "local_import_parsing"
    assert result.runtime_ms >= 0
    assert result.sequence_sha256 == hashlib.sha256(SYNTHETIC_SEQUENCE.encode()).hexdigest()
    assert result.raw_tsv_sha256 == {
        "scores_tsv": hashlib.sha256(SCORES.encode()).hexdigest(),
        "regions_tsv": hashlib.sha256(REGIONS.encode()).hexdigest(),
    }
    assert len(result.residue_propensity) == 45
    assert result.residue_propensity[0].model_dump() == {
        "position": 1,
        "aa": "A",
        "score": 0.0,
        "score_name": "pDP",
        "Sbind": 2.5,
        "semantic_type": "residue_propensity",
        "Sbind_semantics": "binding_mode_entropy",
    }
    assert "attribution" not in result.model_dump_json()


@pytest.mark.parametrize("score,label", [(0.0, "N"), (0.599999, "N"), (0.6, "P"), (1.0, "P")])
def test_global_only_threshold_boundary_without_inventing_residue_values(score, label):
    result = import_fuzdrop_result(payload(scores_tsv=None, pLLPS=score))
    assert result.label == label
    assert result.raw_score == result.calibrated_score == score
    assert "does not establish absence of condensation" in result.label_semantics
    assert result.residue_propensity is result.regions is None
    assert result.raw_tsv_sha256 == {}


def test_missing_global_is_null_not_a_residue_summary():
    result = import_fuzdrop_result(payload())
    assert result.residue_propensity is not None
    assert result.raw_score is result.calibrated_score is result.label is None
    assert result.threshold is result.threshold_operator is result.label_semantics is None
    assert result.regions is None


def test_region_order_duplicates_and_single_residues_are_retained_without_reconstruction():
    result = import_fuzdrop_result(payload(regions_tsv=REGIONS))
    assert [(r.official_type, r.start, r.end, r.length) for r in result.regions] == [
        ("Droplet-promoting region", 1, 1, 1),
        ("Droplet-promoting region", 1, 1, 1),
        ("Aggregation hot-spot", 45, 45, 1),
    ]
    assert all(r.semantic_type == "region_prediction" for r in result.regions)
    # The first native DPR remains present despite its synthetic pDP being zero.
    assert result.residue_propensity[0].score == 0
    region_rows = REGIONS.splitlines()
    reordered = "\n".join([region_rows[0], region_rows[-1], *region_rows[1:-1]])
    imported = import_fuzdrop_result(payload(regions_tsv=reordered))
    assert imported.regions[0].type == "aggregation_hotspot"


def test_header_only_regions_are_empty_while_omitted_regions_are_null():
    empty = import_fuzdrop_result(payload(scores_tsv=None, regions_tsv="type\tstart\tend"))
    assert empty.regions == []
    assert empty.residue_propensity is None
    assert empty.raw_score is None
    assert set(empty.raw_tsv_sha256) == {"regions_tsv"}
    assert import_fuzdrop_result(payload()).regions is None


def test_bom_crlf_and_fasta_normalization_preserve_original_tsv_hash():
    original = "\ufeff" + SCORES.replace("\n", "\r\n")
    sequence = ">synthetic_format_fixture\r\n" + SYNTHETIC_SEQUENCE.lower() + "\r\n"
    result = import_fuzdrop_result(payload(sequence=sequence, scores_tsv=original))
    assert result.sequence == SYNTHETIC_SEQUENCE
    assert result.raw_tsv_sha256["scores_tsv"] == hashlib.sha256(original.encode()).hexdigest()
    assert result.raw_tsv_sha256["scores_tsv"] != hashlib.sha256(SCORES.encode()).hexdigest()


@pytest.mark.parametrize("missing", ["", " ", "undefined"])
def test_empty_and_official_exporter_undefined_numeric_cells_remain_null(missing):
    first_missing = score_cell(2, missing)
    lines = first_missing.splitlines()
    cells = lines[1].split("\t")
    cells[3] = missing
    lines[1] = "\t".join(cells)
    result = import_fuzdrop_result(payload(scores_tsv="\n".join(lines)))
    assert result.residue_propensity[0].score is None
    assert result.residue_propensity[0].Sbind is None
    assert result.residue_propensity[1].score == 0.6


@pytest.mark.parametrize(
    "token", ["NaN", "Infinity", "-Infinity", "1e99999999999999999999999999", "null", "1_0"]
)
def test_nonfinite_or_unsupported_score_tokens_are_rejected(token):
    error = assert_import_error(
        payload(scores_tsv=score_cell(2, token)), "FUZDROP_INVALID_NUMERIC_VALUE"
    )
    assert error.detail["field"] == "pDP"
    assert error.detail["row"] == 2


@pytest.mark.parametrize(
    "column,token",
    [
        (2, "-0.1"),
        (2, "1.01"),
        (3, "-0.01"),
        (2, "-1e-999"),
        (3, "-1e-999"),
        (2, "1.00000000000000000000001"),
        (2, "1e999"),
    ],
)
def test_scientific_numeric_ranges_are_checked(column, token):
    assert_import_error(payload(scores_tsv=score_cell(column, token)), "FUZDROP_SCORE_OUT_OF_RANGE")


def test_sbind_is_nonnegative_entropy_and_is_not_clamped_as_a_probability():
    result = import_fuzdrop_result(payload(scores_tsv=score_cell(3, "20")))
    assert result.residue_propensity[0].Sbind == 20


def test_sbind_must_still_be_finite_after_conversion_to_response_float():
    assert_import_error(payload(scores_tsv=score_cell(3, "1e999")), "FUZDROP_INVALID_NUMERIC_VALUE")


@pytest.mark.parametrize("token", ["0", "2", "1.0", "undefined", "-1", "9" * 5000])
def test_residue_coordinates_must_be_complete_contiguous_integer_indices(token):
    assert_import_error(payload(scores_tsv=score_cell(0, token)), "FUZDROP_INVALID_COORDINATE")


@pytest.mark.parametrize("kind", ["missing", "extra", "header_only"])
def test_residue_count_must_match_complete_sequence(kind):
    rows = SCORES.splitlines()
    changed = {
        "missing": "\n".join(rows[:-1]),
        "extra": "\n".join(rows + [rows[-1]]),
        "header_only": rows[0],
    }[kind]
    assert_import_error(payload(scores_tsv=changed), "FUZDROP_RESIDUE_COUNT_MISMATCH")


@pytest.mark.parametrize("residue", ["C", "a", "X", "undefined"])
def test_exported_residue_mismatch_is_rejected(residue):
    assert_import_error(payload(scores_tsv=score_cell(1, residue)), "FUZDROP_SEQUENCE_MISMATCH")


@pytest.mark.parametrize(
    "start,end",
    [("0", "1"), ("5", "4"), ("1", "46"), ("undefined", "1"), ("1", "2.0"), ("-1", "5")],
)
def test_native_region_bounds_are_validated(start, end):
    regions = f"type\tstart\tend\nDroplet-promoting region\t{start}\t{end}"
    assert_import_error(payload(regions_tsv=regions), "FUZDROP_INVALID_COORDINATE")


def test_unknown_native_region_type_is_not_mapped_to_another_semantic_type():
    regions = "type\tstart\tend\ncritical region\t1\t5"
    assert_import_error(payload(regions_tsv=regions), "FUZDROP_INVALID_REGION_TYPE")


@pytest.mark.parametrize(
    "changed",
    [
        SCORES.replace("position\tresidue\tpDP\tSbind", "position\tresidue\tpDP"),
        SCORES.replace("\t", ","),
        SCORES.replace("Sbind", "Shae", 1),
        '{"result": []}',
    ],
)
def test_only_audited_tsv_headers_are_accepted(changed):
    assert_import_error(payload(scores_tsv=changed), "FUZDROP_SCHEMA_CHANGED")


def test_bad_tsv_row_and_bare_cr_return_structured_parse_errors():
    assert_import_error(payload(scores_tsv=SCORES + "\n"), "FUZDROP_PARSE_ERROR")
    assert_import_error(payload(scores_tsv=SCORES.replace("\n", "\r")), "FUZDROP_PARSE_ERROR")


@pytest.mark.parametrize(
    "updates",
    [
        {"source_declaration": "unknown"},
        {"coordinate_system": "zero_based_half_open"},
        {"pLLPS": -0.01},
        {"pLLPS": 1.01},
        {"pLLPS": float("nan")},
        {"pLLPS": float("inf")},
        {"pLLPS": True},
        {"pLLPS": "0.6"},
        {"scores_tsv": None, "regions_tsv": None, "pLLPS": None},
        {"scores_tsv": ""},
        {"scores_tsv": 1},
        {"unexpected": "ignored"},
        {"retrieved_at": "2026-09-03T10:00:00"},
        {"retrieved_at": 123},
    ],
)
def test_request_declarations_types_and_global_values_are_strict(updates):
    assert_import_error(payload(**updates), "FUZDROP_INVALID_IMPORT_REQUEST")


@pytest.mark.parametrize("field", ["source_declaration", "coordinate_system"])
def test_origin_and_coordinate_declarations_are_required(field):
    value = payload()
    del value[field]
    assert_import_error(value, "FUZDROP_INVALID_IMPORT_REQUEST")


@pytest.mark.parametrize(
    "field,value",
    [("source_declaration", "unknown"), ("coordinate_system", "zero_based_half_open")],
)
def test_mutated_request_instances_cannot_bypass_source_or_coordinate_declarations(field, value):
    request = FuzDropImportRequest(**payload())
    setattr(request, field, value)
    assert_import_error(request, "FUZDROP_INVALID_IMPORT_REQUEST")


def test_user_declared_retrieval_time_keeps_its_timezone_and_is_distinct_from_import_time():
    value = payload(retrieved_at="2020-01-02T03:04:05+08:00")
    result = import_fuzdrop_result(FuzDropImportRequest(**value))
    assert result.retrieved_at.isoformat() == "2020-01-02T03:04:05+08:00"
    assert result.imported_at > result.retrieved_at


def test_utf8_size_limit_includes_sequence_and_both_raw_exports():
    value = payload(regions_tsv=REGIONS)
    size = sum(len(value[field].encode()) for field in ("sequence", "scores_tsv", "regions_tsv"))
    assert import_fuzdrop_result(value, max_bytes=size).status == "success"
    error = assert_import_error(value, "FUZDROP_IMPORT_TOO_LARGE", max_bytes=size - 1)
    assert error.status_code == 413
    error = assert_import_error(payload(sequence="测"), "FUZDROP_IMPORT_TOO_LARGE", max_bytes=1)
    assert error.status_code == 413


@pytest.mark.parametrize("sequence", ["", ">a\nACD\n>b\nEFG", "ACDX", "ACDß"])
def test_invalid_sequence_errors_do_not_echo_residue_text(sequence):
    error = assert_import_error(payload(sequence=sequence), "FUZDROP_INVALID_SEQUENCE")
    assert set(error.detail) == {"code", "message", "field"}


def test_error_details_never_echo_untrusted_raw_text_or_paths():
    marker = "PRIVATE_SECRET_at_/internal/path"
    error = assert_import_error(
        payload(scores_tsv=score_cell(2, marker)), "FUZDROP_INVALID_NUMERIC_VALUE"
    )
    assert marker not in str(error.detail)
    assert error.status_code == 422
    assert_import_error(
        payload(scores_tsv=score_cell(2, "\ud800")), "FUZDROP_INVALID_TEXT_ENCODING"
    )


def test_manual_import_does_not_apply_new_remote_submission_length_limits():
    # Short synthetic input demonstrates local import semantics only.
    result = import_fuzdrop_result(payload(sequence="A", scores_tsv=None, pLLPS=0.5))
    assert result.sequence_length == 1


def test_unavailable_contract_cannot_claim_ready_or_leak_a_configured_url():
    health = FuzDropHealth()
    assert health.status == "unavailable" and health.available is False
    assert health.mode == "C" and health.integration_mode == "browser_protected"
    with pytest.raises(ValidationError):
        FuzDropHealth(available=True)
    with pytest.raises(ValidationError):
        FuzDropHealth(mode="A")
    with pytest.raises(ValidationError):
        FuzDropHealth(official_site_url="https://fuzdrop.bio.unipd.it@other.test/private")
    unavailable = FuzDropUnavailableResult()
    union = TypeAdapter(FuzDropResultResponse)
    assert union.validate_python(unavailable.model_dump()).status == "unavailable"
    assert unavailable.raw_score is unavailable.residue_propensity is None
    assert unavailable.error.code == "FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE"


def test_success_union_roundtrip_preserves_canonical_regions_and_native_labels():
    imported = import_fuzdrop_result(payload(regions_tsv=REGIONS))
    restored = TypeAdapter(FuzDropResultResponse).validate_python(imported.model_dump())
    assert restored.model_dump() == imported.model_dump()
    assert restored.regions[0].type == "droplet_promoting_region"
    assert restored.regions[0].official_type == "Droplet-promoting region"
    changed = imported.model_dump()
    changed["regions"][0]["length"] = 2
    with pytest.raises(ValidationError):
        FuzDropResult.model_validate(changed)


@pytest.mark.parametrize(
    "mode,integration", [("A", "documented_api"), ("B", "supported_http_service")]
)
def test_public_dto_reserves_audited_future_modes_without_enabling_the_current_adapter(
    mode, integration
):
    # Schema-only synthetic construction: no remote adapter or scientific result is exercised.
    health = FuzDropHealth(
        mode=mode, integration_mode=integration, available=True, status="ready", reason=None
    )
    assert health.available is True
    synthetic = import_fuzdrop_result(payload(scores_tsv=None, pLLPS=0.5)).model_dump()
    synthetic.update(
        mode=mode,
        integration_mode=integration,
        source="official_remote_service",
        source_declaration=None,
        origin_verification="official_service_response",
        coordinate_verification="verified_official_contract",
        imported_at=None,
        retrieved_at=datetime.now(timezone.utc),
        runtime_scope="official_remote_request",
        warnings=[],
    )
    assert FuzDropResult.model_validate(synthetic).source == "official_remote_service"
    synthetic.update(mode="C", integration_mode="browser_protected")
    with pytest.raises(ValidationError):
        FuzDropResult.model_validate(synthetic)


@pytest.mark.parametrize(
    "updates",
    [
        {"origin_verification": "official_service_response"},
        {"coordinate_verification": "verified_official_contract"},
        {"imported_at": None},
        {"runtime_scope": "official_remote_request"},
        {"service_version": "unverified-version"},
    ],
)
def test_manual_success_dto_cannot_upgrade_user_declarations_to_verified_results(updates):
    synthetic = import_fuzdrop_result(payload()).model_dump()
    synthetic.update(updates)
    with pytest.raises(ValidationError):
        FuzDropResult.model_validate(synthetic)
