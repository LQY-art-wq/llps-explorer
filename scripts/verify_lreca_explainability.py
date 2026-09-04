"""Compare the Human adapter with original saliency/KDE definitions and save evidence.

Run only after the unchanged official Human classification demo has succeeded.
This reference deliberately replaces the saliency demo's mydata checkpoint and
vocabulary with the verified Human checkpoint/vocabulary; it is labeled as such.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

import numpy as np
import scipy
import sklearn
import torch
from portable_evidence import install_portable_excepthook, portable, save_json
from scipy import signal
from sklearn.model_selection import GridSearchCV
from sklearn.neighbors import KernelDensity

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from lreca_runtime.engine import LRECAEngine  # noqa: E402
from lreca_runtime.upstream import SOURCE_FILES, load_definitions  # noqa: E402


def original_kde_reference(repository: Path, normalized: list[float]) -> dict:
    """Original KDE definitions on explicit scores, separating batch-size roundoff."""
    rounded = np.asarray(
        [float("%.4f" % value) for value in normalized]  # noqa: UP031
    ).reshape(-1, 1)
    grid = GridSearchCV(KernelDensity(), {"bandwidth": np.logspace(-1, 1, 20)})
    grid.fit(rounded)
    density = np.exp(grid.best_estimator_.score_samples(rounded))
    smoothed = signal.savgol_filter(density, 50, 3)
    processed = -1 * (smoothed - np.max(smoothed))
    kde_namespace = load_definitions(
        repository, "kde", {"find_sequence_segmentpoint", "find_max_segment"}
    )
    segments = kde_namespace["find_max_segment"](
        [["human_reference"]], [list(range(len(normalized)))], [density], ""
    )
    boundaries = segments[0][0]
    primary = int(segments[1][0])
    regions = [
        {
            "start": int(left) + 1,
            "end": int(right),
            "score": float(segments[6][0][index]),
            "is_primary": index == primary,
        }
        for index, (left, right) in enumerate(pairwise(boundaries))
        if right > left
    ]
    return {
        "rounded_kde_input": rounded[:, 0].tolist(),
        "kde_values": processed.tolist(),
        "kde_bandwidth": float(grid.best_estimator_.bandwidth),
        "regions": regions,
    }


def original_reference(engine: LRECAEngine, sequence: str) -> dict:
    """Untouched official saliency model/functions, Human state, duplicated input."""
    device = torch.device("cpu")
    namespace = load_definitions(
        engine.repository,
        "saliency",
        {
            "ECALayer",
            "RCNN",
            "create_cam",
            "calculate_outputs_and_gradients",
            "rescale_score_by_abs",
        },
        device=device,
    )
    model = namespace["RCNN"](len(engine.vocabulary) + 1, 512, 100, 1, True)
    state = torch.load(engine.metadata["checkpoint_path"], map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.to(device).eval()
    encoded = engine._human["encode_sequences"](
        [sequence.lower(), sequence.lower()], engine.vocabulary
    )
    tokens, _, lengths = engine._personal["collate_fn"]([(value, 0) for value in encoded])
    started = time.perf_counter()
    with torch.backends.cudnn.flags(enabled=False):
        _, cams, targets = namespace["calculate_outputs_and_gradients"](
            tokens, lengths, model, None
        )
        with torch.no_grad():
            logits, _ = model(tokens, lengths)
            global_score = float(torch.softmax(logits, dim=-1)[0, 1])
    raw_cam = cams[0]
    minimum, maximum = min(raw_cam), max(raw_cam)
    normalized = np.asarray(
        [namespace["rescale_score_by_abs"](value, maximum, minimum) for value in raw_cam],
        dtype=np.float64,
    )
    return {
        "global_score": global_score,
        "target_class_index": int(targets[0, 0]),
        "raw_cam": raw_cam.tolist(),
        "normalized_attribution": normalized.tolist(),
        **original_kde_reference(engine.repository, normalized.tolist()),
        "runtime_ms": (time.perf_counter() - started) * 1000,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "backend/tests/fixtures/lreca/attribution_baseline.json",
    )
    args = parser.parse_args()
    global_fixture = json.loads(
        (ROOT / "backend/tests/fixtures/lreca/global_baseline.json").read_text(encoding="utf-8")
    )
    engine = LRECAEngine({"device": "cpu", "torch_threads": 4})
    metadata = engine.load()
    cases = [
        {
            "id": global_fixture["cases"][0]["id"],
            "sequence": global_fixture["cases"][0]["sequence"],
            "source_file": global_fixture["cases"][0]["source_file"],
            "source_line_1based": global_fixture["cases"][0]["source_line_1based"],
        }
    ]
    negative_source = "Demo/test_dataset/neg_dataset/neg_word_list_human_test.txt"
    negative_cases = []
    for line_number, source in enumerate(
        (engine.repository / negative_source).read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        sequence = "".join(source.split()).upper()
        if len(sequence) >= 50:
            negative_cases.append(
                {
                    "id": f"human_negative_line_{line_number}",
                    "sequence": sequence,
                    "source_file": negative_source,
                    "source_line_1based": line_number,
                }
            )
    if negative_cases:
        cases.append(min(negative_cases, key=lambda row: len(row["sequence"])))
    evidence = []
    for case in cases:
        sequence = case["sequence"]
        reference = original_reference(engine, sequence)
        actual = engine.analyze(sequence)
        attribution = np.asarray([row["score"] for row in actual["residue_attribution"]])
        same_input_kde = original_kde_reference(engine.repository, attribution.tolist())
        rounded = np.asarray(
            [float("%.4f" % value) for value in attribution]  # noqa: UP031
        )
        np.testing.assert_allclose(
            actual["raw_score"], reference["global_score"], rtol=0, atol=1e-6
        )
        np.testing.assert_allclose(
            attribution, reference["normalized_attribution"], rtol=0, atol=1e-5
        )
        np.testing.assert_array_equal(rounded, same_input_kde["rounded_kde_input"])
        np.testing.assert_allclose(
            actual["kde"]["values"], same_input_kde["kde_values"], rtol=0, atol=1e-10
        )
        assert actual["attribution_target_class_index"] == reference["target_class_index"]
        assert actual["kde"]["bandwidth"] == same_input_kde["kde_bandwidth"]
        assert actual["critical_regions"] == same_input_kde["regions"]
        evidence.append(
            {
                **case,
                "length": len(sequence),
                "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                "reference": reference,
                "same_input_kde_reference": same_input_kde,
                "comparison": {
                    "status": "passed",
                    "global_absolute_difference": abs(
                        actual["raw_score"] - reference["global_score"]
                    ),
                    "maximum_attribution_absolute_difference": float(
                        np.max(np.abs(attribution - reference["normalized_attribution"]))
                    ),
                    "duplicate_vs_single_rounded_input_difference_count": int(
                        np.count_nonzero(rounded != reference["rounded_kde_input"])
                    ),
                    "duplicate_vs_single_kde_maximum_absolute_difference": float(
                        np.max(
                            np.abs(np.asarray(actual["kde"]["values"]) - reference["kde_values"])
                        )
                    ),
                    "duplicate_vs_single_region_boundaries_equal": [
                        (region["start"], region["end"], region["is_primary"])
                        for region in actual["critical_regions"]
                    ]
                    == [
                        (region["start"], region["end"], region["is_primary"])
                        for region in reference["regions"]
                    ],
                    "same_input_rounded_kde_input_exact": True,
                    "kde_values_maximum_absolute_difference": float(
                        np.max(
                            np.abs(
                                np.asarray(actual["kde"]["values"]) - same_input_kde["kde_values"]
                            )
                        )
                    ),
                    "same_input_regions_exact": True,
                },
            }
        )
    output = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "reference_kind": "human_adapted_original_saliency_and_kde_definitions",
        "reference_scope": (
            "Pristine AST-extracted official saliency/KDE functions and duplicate-batch "
            "saliency model; original mydata checkpoint/vocabulary explicitly replaced by "
            "verified Human checkpoint/vocabulary. This is separate from the unchanged "
            "official Human classification demo baseline."
        ),
        "comparison_scope": (
            "Attribution is compared with the original duplicate-batch model using numerical "
            "tolerance. Single-batch floating-point roundoff can cross the official four-decimal "
            "CSV rounding boundary. Therefore same_input_kde_reference runs the untouched official "
            "KDE functions on production attribution scores; this comparison is exact. Original "
            "duplicate-batch KDE output and observed differences are retained separately."
        ),
        "model": metadata,
        "source_files": {path: sha for path, sha in SOURCE_FILES.values()},
        "runtime": {
            "python": platform.python_version(),
            "pytorch": torch.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
            "device": "cpu",
            "torch_threads": torch.get_num_threads(),
        },
        "tolerances": {
            "global_atol": 1e-6,
            "normalized_attribution_atol": 1e-5,
            "kde_atol": 1e-10,
        },
        "terminal_region_behavior": "Preserved upstream omission of residue N",
        "cases": evidence,
    }
    save_json(args.output, output)
    print(json.dumps({"status": "passed", "cases": len(evidence), "output": portable(args.output)}))


if __name__ == "__main__":
    install_portable_excepthook("verify_lreca_explainability")
    main()
