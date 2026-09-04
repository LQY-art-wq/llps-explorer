"""Hash-checked, side-effect-free reuse of pinned official LRECA definitions.

Only the reviewed definitions are compiled. Upstream imports, module-level
filesystem operations, CLI entry points and output writers never execute.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from scipy import signal
from torch import nn
from torch.nn.utils.rnn import (
    pack_padded_sequence,
    pad_packed_sequence,
    pad_sequence,
)

SOURCE_FILES = {
    "personal": (
        "Demo/code_for_model_testing/RCNN_ECA_personal_test.py",
        "abcb72672a69a0758c08c557ca0e886d451a8f9aabf7f5bce92591e526cb7669",
    ),
    "human": (
        "Demo/code_for_model_testing/RCNN_ECA_3_human_test.py",
        "68a5b205d41f26610e08a3b2eccd326d22d74d4083ca7c33f2c64789a7093c4b",
    ),
    "saliency": (
        "Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/verify/"
        "RCNN_ECA_saliency_verify_gradCAM_fortest.py",
        "8645491541fb1cb56382b5b43bb6f704ec42bd0fb41aa32899f39f9fd2993815",
    ),
    "kde": (
        "Demo/code_for_model_testing/RCNN_ECA_saliency/LCRs_process/"
        "split_LCRs_segment_forsingle.py",
        "cd51cb2386fc0fbbad5f514788218d0087d3abd39e4dd128050054e98146b090",
    ),
}

HUMAN_DATA_FILES = (
    (
        "Data/pos_dataset/pos_word_list_human.txt",
        "1e3beca27c80a5fc59c41bbb5cc40f429a0619bd3dcc6172a42dbe85cd90ad32",
    ),
    (
        "Data/neg_dataset/neg_word_list_human.txt",
        "e793a6eaa512e42ab72dd236cdaf13d20e14c3971def800b3aabc261193da1ea",
    ),
)

DEFINITION_ALLOWLIST = {
    "personal": {"ECALayer", "RCNN", "collate_fn"},
    "human": {"read_sequences", "build_vocabulary", "encode_sequences"},
    "saliency": {
        "ECALayer",
        "RCNN",
        "create_cam",
        "calculate_outputs_and_gradients",
        "rescale_score_by_abs",
    },
    "kde": {"find_sequence_segmentpoint", "find_max_segment"},
}


def checked_file(repository: Path, relative_path: str, expected_sha256: str) -> Path:
    path = repository / relative_path
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"Pinned LRECA source checksum mismatch: {relative_path}")
    return path


def _feature_return_forward(class_node: ast.ClassDef) -> ast.ClassDef:
    """Retain pre-ECA features and keep the batch dimension; no weight changes."""
    node = copy.deepcopy(class_node)
    forward = next(item for item in node.body if getattr(item, "name", None) == "forward")
    captures = squeezes = returns = 0
    body: list[ast.stmt] = []
    for index, statement in enumerate(forward.body):
        body.append(statement)
        if (
            isinstance(statement, ast.Assign)
            and ast.unparse(statement.value) == "F.relu(out)"
            and index > 0
            and isinstance(forward.body[index - 1], ast.Assign)
            and ast.unparse(forward.body[index - 1].value) == "torch.cat((embed, out), 2)"
        ):
            body.append(ast.parse("out_all = out").body[0])
            captures += 1
        for child in ast.walk(statement):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "squeeze"
                and ast.unparse(child.func.value) == "self.globalmaxpool(out)"
                and not child.args
                and not child.keywords
            ):
                child.args = [ast.Constant(-1)]
                squeezes += 1
        if isinstance(statement, ast.Return) and ast.unparse(statement.value) == "out":
            statement.value = ast.Tuple(
                elts=[ast.Name("out", ast.Load()), ast.Name("out_all", ast.Load())],
                ctx=ast.Load(),
            )
            returns += 1
    if (captures, squeezes, returns) != (1, 1, 1):
        raise ValueError("Unexpected pinned RCNN forward structure; compatibility patch rejected")
    forward.body = body
    return node


def _configurable_prominence(function_node: ast.FunctionDef) -> ast.FunctionDef:
    node = copy.deepcopy(function_node)
    replacements = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and ast.unparse(child.func) == "signal.find_peaks":
            for keyword in child.keywords:
                if keyword.arg == "prominence" and isinstance(keyword.value, ast.Constant):
                    if keyword.value.value != 0.1:
                        raise ValueError("Unexpected pinned prominence default")
                    keyword.value = ast.Name("_lreca_prominence", ast.Load())
                    replacements += 1
    if replacements != 1:
        raise ValueError("Unexpected peak-finding structure; prominence patch rejected")
    return node


def load_definitions(
    repository: Path,
    source: str,
    names: set[str],
    *,
    feature_return: bool = False,
    prominence: float | None = None,
    device: torch.device | None = None,
) -> dict[str, Any]:
    """Extract explicit, checksum-pinned definitions; optional patches are counted."""
    if source not in DEFINITION_ALLOWLIST or not names <= DEFINITION_ALLOWLIST[source]:
        raise ValueError("An unreviewed upstream definition was requested")
    relative_path, expected_hash = SOURCE_FILES[source]
    path = checked_file(repository, relative_path, expected_hash)
    parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected: list[ast.stmt] = []
    for node in parsed.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)) or node.name not in names:
            continue
        if feature_return and source == "personal" and node.name == "RCNN":
            node = _feature_return_forward(node)
        if prominence is not None and source == "kde" and node.name == "find_sequence_segmentpoint":
            node = _configurable_prominence(node)
        selected.append(node)
    if {node.name for node in selected} != names:
        raise ValueError("A requested upstream definition was absent")
    namespace: dict[str, Any] = {
        "__name__": f"lreca_pinned_{source}",
        "np": np,
        "torch": torch,
        "nn": nn,
        "F": F,
        "Path": Path,
        "signal": signal,
        "pack_padded_sequence": pack_padded_sequence,
        "pad_packed_sequence": pad_packed_sequence,
        "pad_sequence": pad_sequence,
        "device": device or torch.device("cpu"),
        "_lreca_prominence": prominence,
    }
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace
