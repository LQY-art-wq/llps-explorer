"""Persistent Human LRECA inference using the pinned official scientific code."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import torch
from scipy import signal
from sklearn.model_selection import GridSearchCV
from sklearn.neighbors import KernelDensity

from .metadata import get_lreca_model_metadata, resolve_project_path
from .upstream import HUMAN_DATA_FILES, checked_file, load_definitions

ROOT = Path(__file__).resolve().parents[2]
STANDARD_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
KDE_VALUES_SEMANTICS = "maximum_smoothed_score_density_minus_smoothed_score_density"
TERMINAL_WARNING = (
    "UPSTREAM_TERMINAL_RESIDUE_OMITTED: preserved official half-open segmentation "
    "with terminal boundary N-1; the last residue is outside all candidate regions."
)


class LRECAEngine:
    """One loaded model per worker; no request keeps an activation or autograd graph."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = dict(config or {})
        self.repository = resolve_project_path(
            self.config.get("repository_path") or ROOT / "external/lreca"
        )
        self.threshold = float(self.config.get("threshold", 0.5))
        self.top_residues = int(self.config.get("top_residues", 10))
        self.prominence = float(self.config.get("kde_prominence", 0.1))
        if not 0 <= self.threshold <= 1 or self.top_residues < 1:
            raise ValueError("Invalid LRECA threshold or top-residue count")
        if not np.isfinite(self.prominence) or self.prominence < 0:
            raise ValueError("KDE prominence must be finite and nonnegative")
        self.model = None
        self.device = torch.device("cpu")
        self.metadata: dict[str, Any] = {}
        self.vocabulary: dict[str, int] = {}
        self._human: dict[str, Any] = {}
        self._personal: dict[str, Any] = {}
        self._saliency: dict[str, Any] = {}
        self._kde: dict[str, Any] = {}
        self._lock = threading.RLock()
        self.load_count = self.prediction_count = self.attribution_count = self.kde_count = 0

    def load(self) -> dict[str, Any]:
        with self._lock:
            if self.model is not None:
                return dict(self.metadata)
            requested_device = self.config.get("device", "auto")
            if requested_device not in {"auto", "cpu", "cuda"}:
                raise ValueError("LRECA device must be auto, cpu, or cuda")
            if requested_device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA was requested but is not available")
            self.device = torch.device(
                "cuda" if requested_device != "cpu" and torch.cuda.is_available() else "cpu"
            )
            threads = int(self.config.get("torch_threads", 4))
            if threads < 1:
                raise ValueError("torch_threads must be positive")
            torch.set_num_threads(threads)
            torch.manual_seed(1)
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
            metadata = get_lreca_model_metadata(
                checkpoint_path=self.config.get("checkpoint_path"),
                repository_path=str(self.repository),
            )
            self._human = load_definitions(
                self.repository, "human", {"read_sequences", "build_vocabulary", "encode_sequences"}
            )
            self._personal = load_definitions(
                self.repository,
                "personal",
                {"ECALayer", "RCNN", "collate_fn"},
                feature_return=True,
            )
            self._saliency = load_definitions(
                self.repository, "saliency", {"create_cam", "rescale_score_by_abs"}
            )
            self._kde = load_definitions(
                self.repository,
                "kde",
                {"find_sequence_segmentpoint", "find_max_segment"},
                prominence=self.prominence,
            )
            training = [
                self._human["read_sequences"](checked_file(self.repository, path, sha), 980)
                for path, sha in HUMAN_DATA_FILES
            ]
            self.vocabulary = self._human["build_vocabulary"](*training)
            model = self._personal["RCNN"](len(self.vocabulary) + 1, 512, 100, 1, True)
            checkpoint_path = metadata.get("checkpoint_path") or metadata.get(
                "checkpoint_absolute_path"
            )
            if not checkpoint_path:
                raise ValueError("Verified metadata must include the checkpoint absolute path")
            state_dict = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
            model.load_state_dict(state_dict, strict=True)
            model.to(self.device)
            model.device = self.device
            model.eval()
            self.model = model
            self.load_count += 1
            self.metadata = metadata
            return dict(self.metadata)

    @property
    def device_name(self) -> str:
        if self.device.type == "cuda":
            return f"cuda:{self.device.index or torch.cuda.current_device()}"
        return "cpu"

    @staticmethod
    def _sequence(sequence: str) -> str:
        # Only standard ASCII case conversion is permitted; Unicode characters
        # such as sharp-s must never silently expand into valid amino acids.
        normalized = "".join(sequence.split()).translate(
            str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        )
        if not normalized:
            raise ValueError("EMPTY_SEQUENCE")
        for position, residue in enumerate(normalized, start=1):
            if residue not in STANDARD_AMINO_ACIDS:
                raise ValueError(f"INVALID_AMINO_ACID: {residue} at position {position}")
        return normalized

    def _input(self, sequence: str) -> tuple[torch.Tensor, torch.Tensor]:
        if self.model is None:
            raise RuntimeError("LRECA model has not been loaded")
        encoded = self._human["encode_sequences"]([sequence.lower()], self.vocabulary)
        tokens, _, lengths = self._personal["collate_fn"]([(encoded[0], 0)])
        return tokens.to(self.device), lengths.to(self.device)

    def _synchronize(self) -> None:
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)

    def predict_global(self, sequence: str) -> dict[str, Any]:
        with self._lock:
            started = time.perf_counter()
            sequence = self._sequence(sequence)
            tokens, lengths = self._input(sequence)
            with torch.inference_mode():
                logits, _ = self.model(tokens, lengths)
                score = float(torch.softmax(logits, dim=-1)[0, 1].cpu())
                raw_logits = logits[0].cpu().tolist()
            self._synchronize()
            if not np.isfinite(score):
                raise RuntimeError("LRECA returned a nonfinite global score")
            self.prediction_count += 1
            return {
                "method": "lreca",
                "status": "success",
                "raw_score": score,
                "calibrated_score": score,
                "calibration_status": "not_calibrated",
                "score_semantics": "uncalibrated_positive_class_softmax",
                "positive_class_index": 1,
                "threshold": self.threshold,
                "threshold_operator": ">",
                "label": "P" if score > self.threshold else "N",
                "logits": raw_logits,
                "device": self.device_name,
                "runtime_ms": (time.perf_counter() - started) * 1000,
            }

    def compute_attribution(self, sequence: str) -> dict[str, Any]:
        with self._lock:
            started = time.perf_counter()
            sequence = self._sequence(sequence)
            tokens, lengths = self._input(sequence)
            # cuDNN eval-mode RNN backward is unsupported; the official saliency
            # script disables cuDNN too. Only this fresh gradient forward does so.
            with torch.enable_grad(), torch.backends.cudnn.flags(enabled=False):
                logits, features = self.model(tokens, lengths)
                target = int(logits.argmax(dim=1)[0].detach().cpu())
                chosen = logits[:, target]
                gradients = torch.autograd.grad(
                    chosen, features, torch.ones_like(chosen), retain_graph=False
                )[0]
                feature_array = features.detach().cpu().numpy().transpose(0, 2, 1)
                gradient_array = gradients.detach().cpu().numpy().transpose(0, 2, 1)
                cams: list[np.ndarray] = []
                self._saliency["create_cam"](feature_array, gradient_array, [len(sequence)], cams)
            self._synchronize()
            self.attribution_count += 1
            result: dict[str, Any] = {
                "status": "success",
                "semantic_type": "model_attribution",
                "normalization": "official_absolute_maximum_diverging_scale",
                "attribution_target_class_index": target,
                "attribution_target_label": "P" if target == 1 else "N",
                "residue_attribution": None,
                "top_residues": None,
                "warnings": [],
            }
            raw_cam = cams[0]
            if not np.isfinite(raw_cam).all() or not np.any(raw_cam):
                reason = (
                    "NONFINITE_GRAD_CAM"
                    if not np.isfinite(raw_cam).all()
                    else "ZERO_GRAD_CAM_NORMALIZATION_UNDEFINED"
                )
                result.update(status="unavailable", reason=reason, warnings=[reason])
            else:
                maximum, minimum = max(raw_cam), min(raw_cam)
                normalize = self._saliency["rescale_score_by_abs"]
                values = [float(normalize(value, maximum, minimum)) for value in raw_cam]
                result["residue_attribution"] = [
                    {"position": position, "aa": aa, "score": value}
                    for position, (aa, value) in enumerate(zip(sequence, values), start=1)
                ]
                sorted_residues = sorted(
                    result["residue_attribution"], key=lambda row: (-row["score"], row["position"])
                )[: self.top_residues]
                result["top_residues"] = [
                    {"rank": rank, **row} for rank, row in enumerate(sorted_residues, start=1)
                ]
            result["runtime_ms"] = (time.perf_counter() - started) * 1000
            return result

    def _empty_kde(self, status: str, reason: str) -> dict[str, Any]:
        return {
            "status": status,
            "reason": reason,
            "semantic_type": "derived_hotspot",
            "values": None,
            "values_semantics": KDE_VALUES_SEMANTICS,
            "prominence": self.prominence,
            "bandwidth": None,
            "regions": None,
            "warnings": [reason] if status == "unavailable" else [],
        }

    def compute_kde(self, scores: list[float]) -> dict[str, Any]:
        with self._lock:
            started = time.perf_counter()
            if len(scores) < 50:
                result = self._empty_kde("unavailable", "KDE_REQUIRES_50_RESIDUES")
                result["runtime_ms"] = (time.perf_counter() - started) * 1000
                return result
            source_scores = np.asarray(scores, dtype=np.float64)
            if not np.isfinite(source_scores).all() or np.any(
                (source_scores < 0) | (source_scores > 1)
            ):
                raise ValueError("KDE requires finite official normalized scores in [0, 1]")
            if not self._kde:
                raise RuntimeError("LRECA model has not been loaded")
            # Preserve the upstream pandas CSV float_format="%.4f" transition.
            rounded = np.asarray(
                [float("%.4f" % value) for value in scores]  # noqa: UP031
            ).reshape(-1, 1)
            grid = GridSearchCV(KernelDensity(), {"bandwidth": np.logspace(-1, 1, 20)})
            grid.fit(rounded)
            density = np.exp(grid.best_estimator_.score_samples(rounded))
            smoothed = signal.savgol_filter(density, 50, 3)
            processed = -1 * (smoothed - np.max(smoothed))
            self._kde["_lreca_prominence"] = self.prominence
            # The untouched function defines exact valley pruning, slices, sums,
            # and primary tie handling. Its active compute path performs no I/O.
            reference = self._kde["find_max_segment"](
                [["sequence"]], [list(range(len(scores)))], [density], ""
            )
            boundaries = reference[0][0]
            primary_index = int(reference[1][0])
            segment_scores = reference[6][0]
            regions = []
            warnings = [TERMINAL_WARNING]
            for index, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
                if right <= left:
                    warnings.append("UPSTREAM_EMPTY_SEGMENT_OMITTED")
                    continue
                regions.append(
                    {
                        "start": int(left) + 1,
                        "end": int(right),
                        "score": float(segment_scores[index]),
                        "is_primary": index == primary_index,
                    }
                )
            if not regions or sum(region["is_primary"] for region in regions) != 1:
                result = self._empty_kde("unavailable", "UPSTREAM_NO_VALID_PRIMARY_REGION")
                result["runtime_ms"] = (time.perf_counter() - started) * 1000
                return result
            if np.ptp(processed) < max(self.prominence, 1e-12):
                warnings.append("KDE_NO_DISTINCT_INTERIOR_PEAK_AT_CONFIGURED_PROMINENCE")
            self.kde_count += 1
            return {
                "status": "success",
                "semantic_type": "derived_hotspot",
                "values": processed.tolist(),
                "values_semantics": KDE_VALUES_SEMANTICS,
                "input_precision": "official_csv_4_decimal_places",
                "prominence": self.prominence,
                "bandwidth": float(grid.best_estimator_.bandwidth),
                "regions": regions,
                "warnings": warnings,
                "runtime_ms": (time.perf_counter() - started) * 1000,
            }

    def analyze(
        self, sequence: str, include_attribution: bool = True, include_kde: bool = True
    ) -> dict[str, Any]:
        with self._lock:
            started = time.perf_counter()
            sequence = self._sequence(sequence)
            global_result = self.predict_global(sequence)
            timings = {"global_ms": global_result["runtime_ms"]}
            warnings: list[str] = []
            attribution = {
                "status": "not_requested",
                "reason": None,
                "residue_attribution": None,
                "top_residues": None,
                "attribution_target_class_index": None,
                "attribution_target_label": None,
            }
            kde = None
            if include_attribution:
                attribution = self.compute_attribution(sequence)
                timings["attribution_ms"] = attribution["runtime_ms"]
                warnings.extend(attribution["warnings"])
                if not include_kde:
                    kde = None
                elif attribution["status"] != "success":
                    kde = self._empty_kde("unavailable", "KDE_REQUIRES_AVAILABLE_ATTRIBUTION")
                else:
                    kde = self.compute_kde(
                        [row["score"] for row in attribution["residue_attribution"]]
                    )
                    timings["kde_ms"] = kde["runtime_ms"]
                if kde is not None:
                    warnings.extend(kde["warnings"])
            return {
                **self.metadata,
                **global_result,
                "repository_commit": self.metadata.get("commit"),
                "sequence_length": len(sequence),
                "attribution_status": attribution["status"],
                "attribution_reason": attribution.get("reason"),
                "attribution_semantic_type": "model_attribution",
                "attribution_normalization": "official_absolute_maximum_diverging_scale",
                "attribution_target_class_index": attribution["attribution_target_class_index"],
                "attribution_target_label": attribution["attribution_target_label"],
                "residue_attribution": attribution["residue_attribution"],
                "top_residues": attribution["top_residues"],
                "kde": kde,
                "critical_regions": kde["regions"] if kde is not None else None,
                "warnings": list(dict.fromkeys(warnings)),
                "timings_ms": timings,
                "runtime_ms": (time.perf_counter() - started) * 1000,
            }

    def diagnostics(self) -> dict[str, Any]:
        memory = psutil.Process(os.getpid()).memory_info()
        modules = list(self.model.modules()) if self.model is not None else []
        hooks = {
            "forward": sum(len(module._forward_hooks) for module in modules),
            "forward_pre": sum(len(module._forward_pre_hooks) for module in modules),
            "backward": sum(len(module._backward_hooks) for module in modules),
        }
        result = {
            "loaded": self.model is not None,
            "device": self.device_name,
            "load_count": self.load_count,
            "prediction_count": self.prediction_count,
            "attribution_count": self.attribution_count,
            "kde_count": self.kde_count,
            "hook_counts": hooks,
            "hook_count": sum(hooks.values()),
            "forward_hook_count": hooks["forward"] + hooks["forward_pre"],
            "backward_hook_count": hooks["backward"],
            "vocabulary": self.vocabulary,
            "parameter_grad_count": sum(
                parameter.grad is not None for parameter in self.model.parameters()
            )
            if self.model is not None
            else 0,
            "rss_bytes": memory.rss,
            "peak_rss_bytes": getattr(memory, "peak_wset", None),
            "pid": os.getpid(),
            "cuda_available": torch.cuda.is_available(),
            "torch_threads": torch.get_num_threads(),
        }
        if self.device.type == "cuda":
            result.update(
                cuda_memory_allocated_bytes=torch.cuda.memory_allocated(self.device),
                cuda_memory_reserved_bytes=torch.cuda.memory_reserved(self.device),
                cuda_peak_memory_allocated_bytes=torch.cuda.max_memory_allocated(self.device),
                cuda_peak_memory_reserved_bytes=torch.cuda.max_memory_reserved(self.device),
                cuda_allocated_bytes=torch.cuda.memory_allocated(self.device),
                cuda_reserved_bytes=torch.cuda.memory_reserved(self.device),
                cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(self.device),
            )
        else:
            result.update(
                cuda_allocated_bytes=None,
                cuda_reserved_bytes=None,
                cuda_peak_allocated_bytes=None,
            )
        return result
