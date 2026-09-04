"""Offline request/DTO contracts, not scientific prediction fixtures."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.orchestration import (
    AnalysisJob,
    AnalysisRequest,
    MethodExecution,
    SequenceMetadata,
)


def request(**updates):
    payload = {"sequence": "ACDEFGHIK", "selected_methods": ["lreca", "fuzdrop"]}
    payload.update(updates)
    return AnalysisRequest.model_validate(payload)


def assert_request_error(code, **updates):
    with pytest.raises(ValidationError) as caught:
        request(**updates)
    assert code in {item["type"] for item in caught.value.errors()}


def test_defaults_and_shared_fasta_normalization():
    result = request(sequence=">one sequence\n acd e\nFGHIK\n", sequence_name="  蛋白 A  ")
    assert result.sequence == "ACDEFGHIK"
    assert result.sequence_name == "蛋白 A"
    assert result.prediction_mode == "independent"
    assert result.weights is None
    assert result.external_results == {}


@pytest.mark.parametrize("method", ["lreca", "fuzdrop", "seg", "dismeta"])
def test_each_single_method_is_a_valid_independent_request(method):
    assert request(selected_methods=[method]).selected_methods == [method]


@pytest.mark.parametrize(
    ("selected", "code"),
    [
        ([], "EMPTY_SELECTED_METHODS"),
        (None, "EMPTY_SELECTED_METHODS"),
        (["seg", "seg"], "DUPLICATE_SELECTED_METHODS"),
        (["other"], "UNKNOWN_METHOD"),
        (["LRECA"], "UNKNOWN_METHOD"),
        ([1], "UNKNOWN_METHOD"),
    ],
)
def test_selected_method_errors(selected, code):
    assert_request_error(code, selected_methods=selected)


@pytest.mark.parametrize(
    ("sequence", "code"),
    [
        (None, "INVALID_SEQUENCE_TYPE"),
        (123, "INVALID_SEQUENCE_TYPE"),
        (" ", "EMPTY_SEQUENCE"),
        (">a\nACD\n>b\nEFG", "MULTIPLE_FASTA_RECORDS"),
        (">\nACD", "INVALID_FASTA"),
        ("ACD\n>a\nEFG", "INVALID_FASTA"),
        ("ACBX", "INVALID_AMINO_ACID"),
        ("aßc", "INVALID_AMINO_ACID"),
    ],
)
def test_existing_sequence_error_codes_preserved(sequence, code):
    assert_request_error(code, sequence=sequence)


@pytest.mark.parametrize("name", ["x" * 129, "line\nnext", "tab\tvalue", "x\x00y", "x\u202ey", 5])
def test_unsafe_or_long_sequence_names_rejected(name):
    assert_request_error("INVALID_SEQUENCE_NAME", sequence_name=name)


def test_optional_blank_name_and_max_length():
    assert request(sequence_name="  ").sequence_name is None
    assert request(sequence_name="名" * 128).sequence_name == "名" * 128


def test_weighted_request_preserves_requested_weights_and_annotations():
    result = request(
        selected_methods=["seg", "fuzdrop", "lreca", "dismeta"],
        prediction_mode="weighted",
        weights={"lreca": 0.6, "fuzdrop": 0.4},
    )
    assert result.weights == {"lreca": 0.6, "fuzdrop": 0.4}
    assert result.selected_methods == ["seg", "fuzdrop", "lreca", "dismeta"]


@pytest.mark.parametrize("selected", [["lreca"], ["fuzdrop"], ["seg", "dismeta"]])
def test_weighted_requires_both_selected_predictors(selected):
    assert_request_error(
        "WEIGHTED_MODE_REQUIRES_LRECA_AND_FUZDROP",
        selected_methods=selected,
        prediction_mode="weighted",
        weights={"lreca": 0.6, "fuzdrop": 0.4},
    )


@pytest.mark.parametrize("method", ["seg", "dismeta", "other"])
def test_annotations_and_unknown_methods_cannot_receive_weights(method):
    assert_request_error(
        "INVALID_ENSEMBLE_METHOD",
        prediction_mode="weighted",
        weights={"lreca": 0.6, "fuzdrop": 0.4, method: 0},
    )


@pytest.mark.parametrize(
    "weights",
    [
        None,
        {},
        {"lreca": 1},
        {"fuzdrop": 1},
        {"lreca": 0.6, "fuzdrop": 0.6},
        {"lreca": -0.1, "fuzdrop": 1.1},
        {"lreca": "0.6", "fuzdrop": 0.4},
        {"lreca": True, "fuzdrop": 0},
        {"lreca": float("nan"), "fuzdrop": 0.4},
        {"lreca": float("inf"), "fuzdrop": 0.4},
        {"lreca": 10**400, "fuzdrop": 0},
        [0.6, 0.4],
    ],
)
def test_invalid_weights_are_rejected_without_coercion(weights):
    assert_request_error("INVALID_ENSEMBLE_WEIGHTS", prediction_mode="weighted", weights=weights)


def test_tolerance_is_absolute_and_weights_are_not_normalized():
    supplied = {"lreca": 0.6, "fuzdrop": 0.4000000005}
    assert request(prediction_mode="weighted", weights=supplied).weights == supplied
    assert_request_error(
        "INVALID_ENSEMBLE_WEIGHTS",
        prediction_mode="weighted",
        weights={"lreca": 0.6, "fuzdrop": 0.400000002},
    )


@pytest.mark.parametrize("weights", [{"lreca": 0.6, "fuzdrop": 0.4}, {}])
def test_independent_rejects_non_null_weights(weights):
    assert_request_error("INVALID_ENSEMBLE_WEIGHTS", weights=weights)


def test_external_reference_is_an_id_not_an_import_payload():
    value = request(external_results={"fuzdrop": {"result_id": "fuzdrop_result_abc-123"}})
    assert value.external_results["fuzdrop"].result_id == "fuzdrop_result_abc-123"
    with pytest.raises(ValidationError):
        request(external_results={"fuzdrop": {"result_id": "abc", "pLLPS": 0.9}})


@pytest.mark.parametrize("method", ["lreca", "seg", "dismeta", "other"])
def test_external_references_only_support_fuzdrop(method):
    assert_request_error(
        "INVALID_EXTERNAL_RESULT_METHOD", external_results={method: {"result_id": "abc"}}
    )


def test_external_reference_requires_method_selection():
    assert_request_error(
        "EXTERNAL_RESULT_METHOD_NOT_SELECTED",
        selected_methods=["seg"],
        external_results={"fuzdrop": {"result_id": "abc"}},
    )


@pytest.mark.parametrize(
    "identifier", ["", "../secret", "https://example.test", "id\nnext", "x" * 129]
)
def test_external_id_is_bounded_opaque_text(identifier):
    with pytest.raises(ValidationError):
        request(external_results={"fuzdrop": {"result_id": identifier}})


def test_request_forbids_extra_fields_and_copies_input_containers():
    with pytest.raises(ValidationError):
        request(calibrated_probability=0.9)
    selected = ["lreca", "fuzdrop"]
    external = {"fuzdrop": {"result_id": "abc"}}
    value = request(selected_methods=selected, external_results=external)
    selected.append("seg")
    external["fuzdrop"]["result_id"] = "changed"
    assert value.selected_methods == ["lreca", "fuzdrop"]
    assert value.external_results["fuzdrop"].result_id == "abc"
    with pytest.raises(ValidationError):
        value.sequence = "ACD"


def job_payload():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        "job_id": "analysis_abc",
        "created_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(minutes=10),
        "status": "queued",
        "sequence": SequenceMetadata(length=3, sha256=hashlib.sha256(b"ACD").hexdigest()),
        "selected_methods": ["seg"],
        "methods": {
            "seg": MethodExecution(
                method="seg", status="queued", integration_mode="local_automatic"
            )
        },
    }


def test_job_serialization_contains_metadata_without_raw_sequence():
    value = AnalysisJob(**job_payload())
    assert value.sequence.length == 3
    assert "ACD" not in value.model_dump_json()
    assert AnalysisJob.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("field", ["created_at", "updated_at", "expires_at"])
def test_job_timestamps_require_timezones(field):
    payload = job_payload()
    payload[field] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError):
        AnalysisJob(**payload)


def test_job_requires_exact_selected_method_identities():
    payload = job_payload()
    payload["methods"] = {}
    with pytest.raises(ValidationError):
        AnalysisJob(**payload)


def test_method_cannot_report_unverified_dismeta_success():
    with pytest.raises(ValidationError):
        MethodExecution(method="dismeta", status="success", integration_mode="integration_blocked")
