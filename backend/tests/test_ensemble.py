"""Deterministic arithmetic on synthetic native DTOs; no prediction or external I/O."""

import hashlib
import warnings

import pytest
from pydantic import ValidationError

from app.schemas.fuzdrop import FuzDropResult
from app.schemas.lreca import LRECAResult, PublicLRECAModelMetadata
from app.schemas.orchestration import EnsembleResult, MethodExecution
from app.schemas.seg import SEGParameters, SEGRegion, SEGResult
from app.services.ensemble import EXPERIMENTAL_WEIGHTED_SCORE_WARNING, EnsembleCalculator
from app.services.fuzdrop_import import import_fuzdrop_result

SEQUENCE = "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEF"
WEIGHTS = {"lreca": 0.6, "fuzdrop": 0.4}


def lreca_result(score=0.82):
    metadata = PublicLRECAModelMetadata(
        repository="https://github.com/ai-phasepro/LRECA",
        commit="0" * 40,
        checkpoint="synthetic_contract_fixture.pt",
        checkpoint_sha256="0" * 64,
        checkpoint_size_bytes=1,
    )
    return LRECAResult(
        repository_commit=metadata.commit,
        checkpoint=metadata.checkpoint,
        checkpoint_sha256=metadata.checkpoint_sha256,
        metadata=metadata,
        sequence=SEQUENCE,
        sequence_length=len(SEQUENCE),
        raw_score=score,
        calibrated_score=score,
        threshold=0.5,
        label="P" if score > 0.5 else "N",
        logits=[0.0, 1.0],
        device="cpu",
        runtime_ms=1.0,
    )


def fuzdrop_result(score=0.68, *, regions=False):
    # Arbitrary scalar/regions exercise the real offline importer, not an official prediction.
    payload = {
        "sequence": SEQUENCE,
        "source_declaration": "official_fuzdrop_export",
        "coordinate_system": "one_based_inclusive",
    }
    if score is not None:
        payload["pLLPS"] = score
    if regions or score is None:
        payload["regions_tsv"] = "type\tstart\tend\nDroplet-promoting region\t1\t3\n"
    return import_fuzdrop_result(payload)


def success(method, result):
    return MethodExecution(
        method=method,
        status="success",
        result=result,
        integration_mode="manual_import" if method == "fuzdrop" else "local_automatic",
    )


def methods(lreca=0.82, fuzdrop=0.68):
    return {
        "lreca": success("lreca", lreca_result(lreca)),
        "fuzdrop": success("fuzdrop", fuzdrop_result(fuzdrop)),
    }


def test_requested_exact_arithmetic_and_experimental_semantics():
    result = EnsembleCalculator().calculate(methods(), WEIGHTS)
    assert result.score == 0.764
    assert result.label == "P"
    assert result.status == "success"
    assert result.weights == WEIGHTS
    assert result.threshold_operator == ">="
    assert result.calibration_status == "not_calibrated"
    assert result.interpretation_status == "experimental_weighted_score"
    assert "probability" not in result.model_dump()
    assert "experimental" in EXPERIMENTAL_WEIGHTED_SCORE_WARNING
    assert "not been calibrated" in EXPERIMENTAL_WEIGHTED_SCORE_WARNING


@pytest.mark.parametrize(
    ("score", "threshold", "label"),
    [
        (0.5, 0.5, "P"),
        (0.499999, 0.5, "N"),
        (0.500001, 0.5, "P"),
        (0.0, 0.0, "P"),
        (0.0, 0.5, "N"),
        (1.0, 1.0, "P"),
        (0.7, 0.8, "N"),
    ],
)
def test_configured_ensemble_threshold_is_inclusive(score, threshold, label):
    assert EnsembleCalculator(threshold).calculate(methods(score, score), WEIGHTS).label == label


@pytest.mark.parametrize("threshold", [-1, 1.1, True, "0.5", float("nan"), float("inf"), 10**400])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        EnsembleCalculator(threshold)


@pytest.mark.parametrize("remove", [True, False])
def test_missing_external_result_is_unavailable_without_renormalizing(remove):
    value = methods()
    if remove:
        value.pop("fuzdrop")
    else:
        value["fuzdrop"] = MethodExecution(
            method="fuzdrop", status="external_result_required", integration_mode="manual_import"
        )
    result = EnsembleCalculator().calculate(value, WEIGHTS)
    assert result.status == "unavailable"
    assert result.reason == "fuzdrop_external_result_required"
    assert result.score is None and result.label is None
    assert result.weights == WEIGHTS


@pytest.mark.parametrize("status", ["failed", "unavailable", "queued", "running", "skipped"])
def test_lreca_must_succeed_even_with_zero_lreca_weight(status):
    value = methods()
    value["lreca"] = MethodExecution(
        method="lreca", status=status, integration_mode="local_automatic"
    )
    result = EnsembleCalculator().calculate(value, {"lreca": 0, "fuzdrop": 1})
    assert result.reason == "lreca_result_unavailable"
    assert result.score is None


def test_both_predictors_required_even_with_zero_fuzdrop_weight():
    value = methods()
    value["fuzdrop"] = MethodExecution(
        method="fuzdrop", status="external_result_required", integration_mode="manual_import"
    )
    result = EnsembleCalculator().calculate(value, {"lreca": 1, "fuzdrop": 0})
    assert result.reason == "fuzdrop_external_result_required"


def test_region_only_fuzdrop_import_cannot_create_a_global_score():
    value = methods(fuzdrop=None)
    assert isinstance(value["fuzdrop"].result, FuzDropResult)
    assert value["fuzdrop"].result.regions
    result = EnsembleCalculator().calculate(value, WEIGHTS)
    assert result.reason == "fuzdrop_global_score_missing"
    assert result.score is None and result.label is None


def test_fuzdrop_failure_is_not_promoted_to_success():
    value = methods()
    value["fuzdrop"] = MethodExecution(
        method="fuzdrop", status="failed", integration_mode="manual_import"
    )
    assert EnsembleCalculator().calculate(value, WEIGHTS).reason == "fuzdrop_result_unavailable"


def test_available_zero_weights_are_preserved_and_both_valid_results_required():
    result = EnsembleCalculator().calculate(methods(), {"lreca": 0, "fuzdrop": 1})
    assert result.score == 0.68
    assert result.weights == {"lreca": 0.0, "fuzdrop": 1.0}


def test_tolerance_never_renormalizes_or_clips_the_arithmetic():
    weights = {"lreca": 0.6, "fuzdrop": 0.4000000005}
    result = EnsembleCalculator().calculate(methods(1.0, 1.0), weights)
    assert result.score == weights["lreca"] + weights["fuzdrop"]
    assert result.weights == weights


def test_native_calibrated_scores_cannot_differ_even_by_tiny_amount():
    for native in (lreca_result(), fuzdrop_result()):
        payload = native.model_dump()
        payload["calibrated_score"] = native.raw_score + 1e-12
        with pytest.raises(ValidationError):
            type(native).model_validate(payload)


def test_calculator_defends_against_bypassed_mutated_calibration():
    value = methods()
    tampered = value["lreca"].result.model_copy(update={"calibrated_score": 0.1})
    value["lreca"] = value["lreca"].model_copy(update={"result": tampered})
    assert (
        EnsembleCalculator().calculate(value, WEIGHTS).reason == "lreca_score_calibration_mismatch"
    )


def test_malformed_native_dto_is_rejected_without_serializer_warning_leak():
    bad = fuzdrop_result().model_copy(update={"message": "private-path-and-sequence-marker"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValidationError):
            success("fuzdrop", bad)
    assert not caught


def test_annotations_and_native_results_are_not_fused_or_modified():
    value = methods()
    value["fuzdrop"] = success("fuzdrop", fuzdrop_result(regions=True))
    value["seg"] = success(
        "seg",
        SEGResult(
            version="2.17.0",
            application_version="1.0.0",
            sequence_length=len(SEQUENCE),
            sequence_sha256=hashlib.sha256(SEQUENCE.encode()).hexdigest(),
            regions=[SEGRegion(start=1, end=len(SEQUENCE))],
            parameters=SEGParameters(),
            runtime_ms=0,
        ),
    )
    value["dismeta"] = MethodExecution(
        method="dismeta", status="unavailable", integration_mode="integration_blocked"
    )
    before = {name: item.model_dump() for name, item in value.items()}
    result = EnsembleCalculator(threshold=0.9).calculate(value, WEIGHTS)
    assert result.score == 0.764 and result.label == "N"
    assert {name: item.model_dump() for name, item in value.items()} == before
    assert (
        not {"regions", "coverage", "residue_propensity", "attribution"}
        & result.model_dump().keys()
    )


@pytest.mark.parametrize("method", ["seg", "dismeta"])
def test_direct_calculator_rejects_annotation_weights(method):
    with pytest.raises(ValueError):
        EnsembleCalculator().calculate(methods(), {"lreca": 0.6, "fuzdrop": 0.4, method: 0})


def test_unavailable_ensemble_cannot_contain_a_fake_score():
    with pytest.raises(ValidationError):
        EnsembleResult(
            status="unavailable",
            score=0.5,
            weights=WEIGHTS,
            threshold=0.5,
            reason="fuzdrop_external_result_required",
        )
