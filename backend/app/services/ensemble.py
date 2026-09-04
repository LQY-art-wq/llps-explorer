"""One experimental global-score calculation; native annotations stay independent."""

import math
from collections.abc import Mapping

from app.schemas.fuzdrop import FuzDropResult
from app.schemas.lreca import LRECAResult
from app.schemas.orchestration import EnsembleResult, MethodExecution, validate_ensemble_weights

EXPERIMENTAL_WEIGHTED_SCORE_WARNING = (
    "The weighted score is experimental and has not been calibrated on a shared dataset."
)


class EnsembleCalculator:
    def __init__(self, threshold: float = 0.5) -> None:
        if (
            type(threshold) not in (int, float)
            or not 0 <= threshold <= 1
            or not math.isfinite(threshold)
        ):
            raise ValueError("Ensemble threshold must be a finite number from zero to one")
        self.threshold = float(threshold)

    def calculate(
        self, methods: Mapping[str, MethodExecution], weights: Mapping[str, float]
    ) -> EnsembleResult:
        validated_weights = validate_ensemble_weights(weights)

        def unavailable(reason: str) -> EnsembleResult:
            return EnsembleResult(
                status="unavailable",
                weights=validated_weights,
                threshold=self.threshold,
                reason=reason,
            )

        fuzdrop = methods.get("fuzdrop")
        if fuzdrop is None or fuzdrop.status == "external_result_required":
            return unavailable("fuzdrop_external_result_required")
        lreca = methods.get("lreca")
        if lreca is None or lreca.status != "success" or not isinstance(lreca.result, LRECAResult):
            return unavailable("lreca_result_unavailable")
        if (
            fuzdrop.status != "success"
            or not isinstance(fuzdrop.result, FuzDropResult)
            or fuzdrop.result.source != "manual_import_of_official_result"
        ):
            return unavailable("fuzdrop_result_unavailable")

        scores: dict[str, float] = {}
        for method, result in (("lreca", lreca.result), ("fuzdrop", fuzdrop.result)):
            raw = result.raw_score
            if raw is None:
                return unavailable(f"{method}_global_score_missing")
            if type(raw) not in (int, float) or not 0 <= raw <= 1 or not math.isfinite(raw):
                return unavailable(f"{method}_global_score_invalid")
            if (
                result.calibration_status != "not_calibrated"
                or type(result.calibrated_score) not in (int, float)
                or result.calibrated_score != raw
            ):
                return unavailable(f"{method}_score_calibration_mismatch")
            scores[method] = raw

        # No weight renormalization, missing-result substitution, or residue/region fusion.
        score = (
            validated_weights["lreca"] * scores["lreca"]
            + validated_weights["fuzdrop"] * scores["fuzdrop"]
        )
        return EnsembleResult(
            status="success",
            score=score,
            label="P" if score >= self.threshold else "N",
            weights=validated_weights,
            threshold=self.threshold,
        )
