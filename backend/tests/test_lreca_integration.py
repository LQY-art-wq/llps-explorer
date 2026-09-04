"""Real pinned Human checkpoint regression, device, and lifecycle checks.

These tests deliberately start the persistent scientific worker. They never
substitute random weights, predictions, or mocked scientific output.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import pytest

from app.adapters.lreca import LRECAAdapter
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/lreca/global_baseline.json").read_text(encoding="utf-8")
)
SEQUENCE = FIXTURE["cases"][0]["sequence"]
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


def plain(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


class WorkerSession:
    """Keep the subprocess reader and its asyncio transports on a single loop."""

    def __init__(self, device: str, **settings):
        self.runner = asyncio.Runner()
        self.adapter = LRECAAdapter(settings=Settings(lreca_device=device, **settings))

    def call(self, awaitable):
        return self.runner.run(awaitable)

    def close(self):
        self.call(self.adapter.close())
        self.runner.close()


@pytest.fixture(scope="module")
def cpu():
    session = WorkerSession("cpu")
    try:
        session.call(session.adapter.load())
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def complete(cpu):
    return plain(cpu.call(cpu.adapter.analyze(SEQUENCE)))


def test_real_checkpoint_identity_and_official_vocabulary(cpu):
    health = plain(cpu.call(cpu.adapter.healthcheck()))
    assert health["status"] == "ready"
    metadata = plain(health["metadata"])
    assert metadata["model_variant"] == "human_specific"
    assert metadata["dataset5_mapping_status"] == "unconfirmed"
    assert metadata["checkpoint"] == FIXTURE["checkpoint"]
    assert metadata["checkpoint_sha256"] == FIXTURE["checkpoint_sha256"]
    assert metadata["commit"] == FIXTURE["repository_commit"]
    diagnostics = cpu.call(cpu.adapter.diagnostics())
    assert diagnostics["vocabulary"] == FIXTURE["vocabulary"]


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
def test_real_global_prediction_matches_original_official_demo(cpu, case):
    result = cpu.call(cpu.adapter.predict_global(case["sequence"]))
    assert result["raw_score"] == pytest.approx(
        case["supplemental_full_precision_score"], abs=FIXTURE["supplemental_absolute_tolerance"]
    )
    assert result["raw_score"] == pytest.approx(
        case["official_rounded_score"], abs=FIXTURE["official_rounded_absolute_tolerance"]
    )
    # A source-negative sample is a known official false positive: never replace
    # the actual predicted class with the benchmark's experimental/source label.
    assert result["label"] == case["predicted_label"]
    assert 0 <= result["raw_score"] <= 1


def test_repeated_global_scores_are_deterministic_and_uncalibrated(cpu):
    scores = [cpu.call(cpu.adapter.predict_global(SEQUENCE))["raw_score"] for _ in range(4)]
    assert all(score == scores[0] for score in scores)
    result = plain(cpu.call(cpu.adapter.analyze(SEQUENCE, include_attribution=False)))
    assert result["raw_score"] == scores[0]
    assert result["calibration_status"] == "not_calibrated"
    assert result["calibrated_score"] == result["raw_score"]
    assert not result["residue_attribution"]
    assert not result["top_residues"]
    assert not result["critical_regions"]
    assert not result["kde"] or result["kde"]["status"] != "success"


def test_attribution_positions_amino_acids_and_top_residues(complete):
    values = complete["residue_attribution"]
    assert len(values) == len(SEQUENCE)
    assert [item["position"] for item in values] == list(range(1, len(SEQUENCE) + 1))
    assert "".join(item["aa"] for item in values) == SEQUENCE
    assert all(math.isfinite(item["score"]) and 0 <= item["score"] <= 1 for item in values)
    assert all(item["semantic_type"] == "model_attribution" for item in values)
    expected = sorted(values, key=lambda item: (-item["score"], item["position"]))[:10]
    assert len(complete["top_residues"]) == 10
    for rank, (actual, original) in enumerate(zip(complete["top_residues"], expected), 1):
        assert actual["rank"] == rank
        assert actual["position"] == original["position"]
        assert actual["aa"] == original["aa"]
        assert actual["score"] == original["score"]


def test_negative_prediction_explains_its_actual_argmax_class(cpu):
    source = ROOT / "external/lreca/Demo/test_dataset/neg_dataset/neg_word_list_human_test.txt"
    sequence = source.read_text(encoding="utf-8").splitlines()[119].replace(" ", "").upper()
    result = plain(cpu.call(cpu.adapter.analyze(sequence, include_kde=False)))
    assert result["label"] == "N"
    assert result["raw_score"] < 0.5
    assert result["attribution_target_class_index"] == 0
    assert result["attribution_target_label"] == "N"
    assert len(result["residue_attribution"]) == len(sequence)


def assert_kde_coordinates(result: dict, length: int) -> None:
    kde = result["kde"]
    assert kde["status"] == "success"
    assert kde["semantic_type"] == "derived_hotspot"
    assert len(kde["values"]) == length
    assert all(math.isfinite(value) for value in kde["values"])
    regions = kde["regions"]
    assert regions
    assert sum(region["is_primary"] for region in regions) == 1
    for region in regions:
        assert 1 <= region["start"] <= region["end"] <= length
        assert region["length"] == region["end"] - region["start"] + 1
        assert math.isfinite(region["score"])


def test_real_kde_values_and_inclusive_coordinates(complete):
    assert_kde_coordinates(complete, len(SEQUENCE))
    assert complete["kde"]["prominence"] == 0.1
    assert complete["critical_regions"] == complete["kde"]["regions"]


def test_human_adapted_official_attribution_normalization_and_kde_regression(cpu):
    path = Path(__file__).parent / "fixtures/lreca/attribution_baseline.json"
    reference_fixture = json.loads(path.read_text(encoding="utf-8"))
    assert (
        reference_fixture["reference_kind"] == "human_adapted_original_saliency_and_kde_definitions"
    )
    assert len(reference_fixture["cases"]) >= 2
    tolerances = reference_fixture["tolerances"]
    for case in reference_fixture["cases"]:
        result = plain(cpu.call(cpu.adapter.analyze(case["sequence"])))
        expected = case["reference"]
        expected_kde = case["same_input_kde_reference"]
        actual_scores = [row["score"] for row in result["residue_attribution"]]
        assert result["raw_score"] == pytest.approx(
            expected["global_score"], rel=0, abs=tolerances["global_atol"]
        )
        assert result["attribution_target_class_index"] == expected["target_class_index"]
        assert actual_scores == pytest.approx(
            expected["normalized_attribution"],
            rel=0,
            abs=tolerances["normalized_attribution_atol"],
        )
        # Batch=1 versus the original duplicate-batch reference can differ by
        # float32 rounding, which can cross the upstream four-decimal CSV cut.
        # Test KDE against the pristine official functions on the identical
        # production input; retain the independent CAM comparison above.
        assert [float(f"{value:.4f}") for value in actual_scores] == expected_kde[
            "rounded_kde_input"
        ]
        assert result["kde"]["values"] == pytest.approx(
            expected_kde["kde_values"], rel=0, abs=tolerances["kde_atol"]
        )
        assert result["kde"]["bandwidth"] == expected_kde["kde_bandwidth"]
        assert len(result["critical_regions"]) == len(expected_kde["regions"])
        for actual, region in zip(result["critical_regions"], expected_kde["regions"]):
            assert actual["start"] == region["start"]
            assert actual["end"] == region["end"]
            assert actual["is_primary"] == region["is_primary"]
            assert actual["score"] == pytest.approx(region["score"], rel=0, abs=1e-10)


@pytest.mark.parametrize("length", [50, 100, 500, 1000, 2000])
def test_actual_supported_lengths_including_explainability(cpu, length):
    sequence = (AMINO_ACIDS * math.ceil(length / len(AMINO_ACIDS)))[:length]
    result = plain(cpu.call(cpu.adapter.analyze(sequence)))
    assert 0 <= result["raw_score"] <= 1
    assert result["device"] == "cpu"
    assert len(result["residue_attribution"]) == length
    assert_kde_coordinates(result, length)


@pytest.mark.parametrize("length", [1, 49])
def test_short_sequences_keep_real_global_attribution_and_explicit_kde_limit(cpu, length):
    sequence = (AMINO_ACIDS * math.ceil(length / len(AMINO_ACIDS)))[:length]
    result = plain(cpu.call(cpu.adapter.analyze(sequence)))
    assert 0 <= result["raw_score"] <= 1
    assert len(result["residue_attribution"]) == length
    assert result["kde"]["status"] == "unavailable"
    assert not result["kde"]["values"]
    assert not result["critical_regions"]
    assert result["warnings"]


def test_model_is_loaded_once_across_load_and_analysis_calls(cpu):
    before = cpu.call(cpu.adapter.diagnostics())
    cpu.call(cpu.adapter.load())
    cpu.call(cpu.adapter.load())
    cpu.call(cpu.adapter.predict_global(SEQUENCE))
    after = cpu.call(cpu.adapter.diagnostics())
    assert before["load_count"] == after["load_count"] == 1


def test_configured_threshold_top_count_and_kde_prominence(cpu):
    scores = [0.0] * 80 + [1.0] * 40 + [0.0] * 80
    default = cpu.call(cpu.adapter.compute_kde(scores))
    assert default["status"] == "success"
    assert default["prominence"] == 0.1
    session = WorkerSession(
        "cpu",
        lreca_kde_prominence=100.0,
        lreca_classification_threshold=1.0,
        lreca_top_residues=3,
    )
    try:
        session.call(session.adapter.load())
        changed = session.call(session.adapter.compute_kde(scores))
        assert changed["status"] == "success"
        assert changed["prominence"] == 100.0
        assert default["regions"] != changed["regions"]
        result = plain(session.call(session.adapter.analyze(SEQUENCE)))
        assert result["threshold"] == 1.0
        assert result["label"] == "N"
        assert len(result["top_residues"]) == 3
        # The official saliency target remains logits.argmax, independent of
        # a user-configured classification threshold applied to the probability.
        assert result["attribution_target_class_index"] == 1
    finally:
        session.close()


def test_one_hundred_real_attributions_do_not_accumulate_hooks_or_memory(cpu):
    for _ in range(20):
        cpu.call(cpu.adapter.compute_attribution(SEQUENCE))
    before = cpu.call(cpu.adapter.diagnostics())
    samples = []
    for index in range(100):
        cpu.call(cpu.adapter.compute_attribution(SEQUENCE))
        if (index + 1) % 20 == 0:
            samples.append(cpu.call(cpu.adapter.diagnostics()))
    after = samples[-1]
    for sample in samples:
        assert sample["forward_hook_count"] == before["forward_hook_count"]
        assert sample["backward_hook_count"] == before["backward_hook_count"]
        assert sample["load_count"] == 1
    # Bound obvious retained-graph growth after warm-up; a worker need not
    # return allocator caches to the operating system after every request.
    assert after["rss_bytes"] - before["rss_bytes"] < 64 * 1024 * 1024


def test_repeated_global_predictions_do_not_show_obvious_memory_growth(cpu):
    for _ in range(20):
        cpu.call(cpu.adapter.predict_global(SEQUENCE))
    before = cpu.call(cpu.adapter.diagnostics())
    for _ in range(100):
        cpu.call(cpu.adapter.predict_global(SEQUENCE))
    after = cpu.call(cpu.adapter.diagnostics())
    assert after["load_count"] == 1
    assert after["rss_bytes"] - before["rss_bytes"] < 32 * 1024 * 1024


def test_cuda_real_inference_and_explainability(cpu):
    diagnostics = cpu.call(cpu.adapter.diagnostics())
    if not diagnostics["cuda_available"]:
        pytest.skip("The actual scientific worker reports that CUDA is unavailable")
    session = WorkerSession("cuda")
    try:
        session.call(session.adapter.load())
        result = plain(session.call(session.adapter.analyze(SEQUENCE)))
        assert result["device"].startswith("cuda")
        assert result["raw_score"] == pytest.approx(
            FIXTURE["cases"][0]["supplemental_full_precision_score"], abs=1e-5
        )
        assert len(result["residue_attribution"]) == len(SEQUENCE)
        assert_kde_coordinates(result, len(SEQUENCE))
        for _ in range(20):
            session.call(session.adapter.compute_attribution(SEQUENCE))
        before = session.call(session.adapter.diagnostics())
        for _ in range(100):
            session.call(session.adapter.compute_attribution(SEQUENCE))
        after = session.call(session.adapter.diagnostics())
        assert after["forward_hook_count"] == before["forward_hook_count"]
        assert after["backward_hook_count"] == before["backward_hook_count"]
        assert after["load_count"] == 1
        assert after["cuda_allocated_bytes"] - before["cuda_allocated_bytes"] < 16 * 1024 * 1024
    finally:
        session.close()
