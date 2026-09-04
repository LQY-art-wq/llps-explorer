"""Parser regressions anchored to actual standard-segmasker output bytes."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.seg import (
    SEGError,
    SEGHealth,
    SEGParameters,
    SEGRegion,
    SEGResult,
    SEGResultResponse,
    SEGUnavailableResult,
)
from app.services.seg_parser import parse_seg_intervals

FIXTURES = Path(__file__).parent / "fixtures" / "seg"
CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


def result_for(case_name):
    case = CASES[case_name]
    raw = (FIXTURES / case["raw_output_file"]).read_bytes()
    return SEGResult(
        version="2.17.0",
        application_version="1.0.0",
        sequence_length=case["sequence_length"],
        sequence_sha256=case["sequence_sha256"],
        regions=parse_seg_intervals(raw, case["sequence_length"]),
        parameters=SEGParameters(),
        runtime_ms=case["runtime_ms"],
    )


@pytest.mark.parametrize("case_name", list(CASES))
def test_actual_standard_segmasker_output_matches_frozen_coordinates(case_name):
    case = CASES[case_name]
    raw = (FIXTURES / case["raw_output_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == case["raw_stdout_sha256"]
    assert raw.decode("utf-8") == case["raw_stdout"]
    assert case["returncode"] == 0 and case["stderr"] == ""
    assert hashlib.sha256(case["sequence"].encode("ascii")).hexdigest() == case["sequence_sha256"]
    result = result_for(case_name)
    assert [{"start": r.start, "end": r.end, "length": r.length} for r in result.regions] == (
        case["expected_regions"]
    )
    assert all(1 <= r.start <= r.end <= case["sequence_length"] for r in result.regions)
    assert all(r.semantic_type == "region_annotation" for r in result.regions)
    assert result.region_count == len(case["expected_regions"])


def test_no_lcr_is_success_with_zero_statistics_not_an_unavailable_result():
    result = result_for("mixed_high_complexity")
    assert result.status == "success" and result.regions == []
    assert (result.coverage, result.region_count, result.longest_region) == (0.0, 0, 0)


def test_window_boundary_behavior_comes_from_the_actual_tool_not_a_parser_heuristic():
    assert result_for("short_homopolymer").regions == []
    result = result_for("window_homopolymer")
    assert (result.regions[0].start, result.regions[0].end, result.longest_region) == (1, 12, 12)
    assert result.coverage == 1.0


def test_multiple_native_regions_have_correct_union_coverage_and_longest_region():
    result = result_for("multiple_regions")
    assert result.region_count == 2
    assert result.longest_region == 40
    assert result.coverage == 80 / 180
    human = result_for("human_positive_real_sequence")
    assert human.coverage == 97 / 248
    assert human.longest_region == 52


def test_coverage_union_does_not_merge_or_reorder_native_records():
    # Synthetic protocol edge case; it is not labeled a genuine SEG run.
    raw = ">query\n7 - 9\n3 - 6\n0 - 4\n3 - 6\n"
    regions = parse_seg_intervals(raw, 10)
    result = SEGResult(
        version="2.17.0",
        application_version="1.0.0",
        sequence_length=10,
        sequence_sha256=hashlib.sha256(b"A" * 10).hexdigest(),
        regions=regions,
        parameters=SEGParameters(),
        runtime_ms=0.0,
    )
    assert [(r.start, r.end) for r in result.regions] == [(8, 10), (4, 7), (1, 5), (4, 7)]
    assert (result.coverage, result.region_count, result.longest_region) == (1.0, 4, 5)


def test_gapped_union_does_not_count_non_lcr_positions():
    result = SEGResult(
        version="2.17.0",
        application_version="1.0.0",
        sequence_length=10,
        sequence_sha256=hashlib.sha256(b"A" * 10).hexdigest(),
        regions=[SEGRegion(start=3, end=4), SEGRegion(start=7, end=9)],
        parameters=SEGParameters(),
        runtime_ms=0.0,
    )
    assert result.coverage == 0.5
    assert (result.region_count, result.longest_region) == (2, 3)


def test_lf_and_crlf_represent_the_same_native_intervals():
    raw = (FIXTURES / "multiple_regions.interval.txt").read_bytes()
    assert b"\r\n" in raw
    assert parse_seg_intervals(raw, 180) == parse_seg_intervals(raw.replace(b"\r\n", b"\n"), 180)
    assert parse_seg_intervals(raw.decode(), 180) == parse_seg_intervals(raw, 180)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        ">wrong\n",
        "0 - 4\n",
        ">query\n>query\n0 - 4\n",
        ">query\n0 - 4\n>other\n",
        ">query\n0 - 4\n\n",
        ">query\n0 4\n",
        ">query\n0\t-\t4\n",
        ">query\n0 - 4 extra\n",
        ">query\n0 - 4.0\n",
        ">query\nNaN - 4\n",
        "<html>failure</html>",
        ">query\r0 - 4\r",
        b">query\n\xff\n",
        "\ufeff>query\n",
        None,
    ],
)
def test_malformed_or_multiple_records_fail_with_safe_parse_error(raw):
    with pytest.raises(SEGError) as caught:
        parse_seg_intervals(raw, 10)
    assert caught.value.code == "SEG_PARSE_ERROR"
    assert caught.value.status_code == 502
    assert set(caught.value.detail) == {"code", "message"}


@pytest.mark.parametrize("line", ["-1 - 4", "5 - 4", "0 - 10", "10 - 10", "0 - " + "9" * 5000])
def test_native_coordinates_cannot_be_negative_reversed_or_out_of_bounds(line):
    with pytest.raises(SEGError) as caught:
        parse_seg_intervals(">query\n" + line + "\n", 10)
    assert caught.value.code == "SEG_INVALID_OUTPUT"


@pytest.mark.parametrize("length", [0, -1, True, 10.0, 2147483648])
def test_sequence_length_context_is_strict(length):
    with pytest.raises(SEGError) as caught:
        parse_seg_intervals(">query\n", length)
    assert caught.value.code == "SEG_INVALID_OUTPUT"


def test_identifier_validation_does_not_allow_header_injection_or_leak_raw_output():
    with pytest.raises(SEGError) as caught:
        parse_seg_intervals(">query\n", 10, expected_header="query\n>other")
    assert caught.value.code == "SEG_INVALID_OUTPUT"
    marker = "PRIVATE_SEQUENCE_AND_PATH_/private/tool"
    with pytest.raises(SEGError) as caught:
        parse_seg_intervals(">query\n" + marker, 10)
    assert marker not in str(caught.value.detail)


@pytest.mark.parametrize(
    "updates",
    [
        {"window": 0},
        {"window": True},
        {"window": 1.5},
        {"window": 2147483648},
        {"locut": -0.1},
        {"hicut": float("inf")},
        {"locut": float("nan")},
        {"locut": 3.0, "hicut": 2.0},
        {"input_format": "blastdb"},
        {"output_format": "fasta"},
        {"parse_seqids": True},
    ],
)
def test_parameters_reject_silent_native_coercion_and_unsupported_io(updates):
    with pytest.raises(ValidationError):
        SEGParameters(**updates)


def test_default_parameters_match_the_real_help_fixture():
    assert SEGParameters().model_dump() == {
        "window": 12,
        "locut": 2.2,
        "hicut": 2.5,
        "input_format": "fasta",
        "output_format": "interval",
        "parse_seqids": False,
    }
    help_text = (FIXTURES / "help.txt").read_text(encoding="utf-8")
    assert "Default = `12'" in help_text
    assert "Default = `2.2'" in help_text
    assert "Default = `2.5'" in help_text


def test_annotation_schema_roundtrip_has_no_classifier_or_raw_sequence_fields():
    result = result_for("human_positive_real_sequence")
    serialized = result.model_dump()
    assert SEGResult.model_validate(serialized).model_dump() == serialized
    assert TypeAdapter(SEGResultResponse).validate_python(serialized).model_dump() == serialized
    assert result.annotation_type == "LCR" and result.semantic_type == "region_annotation"
    assert not {"raw_score", "calibrated_score", "label", "threshold", "sequence", "raw_output"} & (
        serialized.keys()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("coverage", 2.0),
        ("coverage", True),
        pytest.param("coverage", 10**500, id="oversized-coverage"),
        ("region_count", 99),
        ("longest_region", None),
        ("raw_score", 0.5),
        ("label", "P"),
        ("version", "/private/executable"),
        ("application_version", "2.17.0+"),
        ("executable_sha256", "not-a-hash"),
        ("sequence_length", 1),
    ],
)
def test_result_rejects_forged_statistics_classifier_fields_and_private_metadata(field, value):
    serialized = result_for("multiple_regions").model_dump()
    serialized[field] = value
    with pytest.raises(ValidationError):
        SEGResult.model_validate(serialized)


def test_invalid_serialized_region_length_is_rejected():
    serialized = result_for("multiple_regions").model_dump()
    serialized["regions"][0]["length"] = 41
    with pytest.raises(ValidationError):
        SEGResult.model_validate(serialized)


def test_health_and_unavailable_results_separate_failure_from_empty_annotations():
    ready = SEGHealth(
        status="ready",
        available=True,
        message="SEG is ready.",
        reason=None,
        version="2.17.0",
        application_version="1.0.0",
        parameters=SEGParameters(),
    )
    assert SEGHealth.model_validate(ready.model_dump()).available is True
    with pytest.raises(ValidationError):
        SEGHealth(status="ready", available=True)
    with pytest.raises(ValidationError):
        SEGHealth(reason="/private/executable")
    unavailable = SEGUnavailableResult()
    assert unavailable.regions is unavailable.coverage is unavailable.longest_region is None
    assert unavailable.region_count is None
    assert (
        not {"raw_score", "calibrated_score", "label", "threshold"}
        & unavailable.model_dump().keys()
    )
    assert TypeAdapter(SEGResultResponse).validate_python(unavailable.model_dump()).status == (
        "unavailable"
    )
