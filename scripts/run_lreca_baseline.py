"""Run the unchanged pinned Human demo before recording supplemental precision.

Invoke with the dedicated LRECA environment. This harness never patches or writes
to the upstream checkout. The official 240-row CSV remains the primary baseline;
the second subprocess calls the same official functions and duplicates each
sequence solely to avoid the upstream batch-size-one ``squeeze()`` defect.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from portable_evidence import (
    export_log,
    install_portable_excepthook,
    portable,
    portable_text,
    save_json,
)

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "external" / "lreca"
COMMIT = "0b4b48ab7870529a34028c6e30dfba42eddbf215"
CHECKPOINT_NAME = "human_1_RCNN_ECA_parallel_089-0.9802.pt"
CHECKPOINT_SHA256 = "aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc"
CHECKPOINT = UPSTREAM / "Demo" / "trained_model" / CHECKPOINT_NAME
DEMO = UPSTREAM / "Demo" / "code_for_model_testing" / "RCNN_ECA_3_human_test.py"
OUTPUT = ROOT / "docs" / "audit" / "lreca_baseline_cpu"
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "lreca" / "global_baseline.json"
REPORT = ROOT / "docs" / "lreca_baseline.md"
INPUTS = {
    "train_positive": UPSTREAM / "Data" / "pos_dataset" / "pos_word_list_human.txt",
    "train_negative": UPSTREAM / "Data" / "neg_dataset" / "neg_word_list_human.txt",
    "test_positive": UPSTREAM / "Demo/test_dataset/pos_dataset/pos_word_list_human_test.txt",
    "test_negative": UPSTREAM / "Demo/test_dataset/neg_dataset/neg_word_list_human_test.txt",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    save_json(path, value)


def verify_identity() -> None:
    commit = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True, encoding="utf-8"
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "status", "--porcelain"], text=True, encoding="utf-8"
    ).strip()
    if commit != COMMIT or dirty:
        raise RuntimeError("The upstream checkout must be clean at the pinned commit")
    if sha256(CHECKPOINT) != CHECKPOINT_SHA256 or CHECKPOINT.stat().st_size != 2395318:
        raise RuntimeError("The Human checkpoint differs from the Module 0 identity")


def runtime_information(torch, numpy, scipy, sklearn, pandas) -> dict:
    return {
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "pytorch": torch.__version__,
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "pandas": pandas.__version__,
        "device": "cpu",
        "cuda_available": torch.cuda.is_available(),
        "torch_cuda_build": torch.version.cuda,
        "cpu_threads": torch.get_num_threads(),
        "interop_threads": torch.get_num_interop_threads(),
        "platform": platform.platform(),
    }


def supplemental_predictions(output_dir: Path) -> None:
    """Load official functions in a child, only after its original demo passed."""
    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("official_returncode") != 0:
        raise RuntimeError("Run the original official demo successfully before supplementation")

    import numpy
    import pandas
    import scipy
    import sklearn
    import torch

    verify_identity()
    original_cwd = Path.cwd()
    sys.path.insert(0, str(DEMO.parent))
    spec = importlib.util.spec_from_file_location("lreca_official_human_demo", DEMO)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot resolve the official Human demo module")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        # The imported personal implementation changes cwd; keep that isolated.
        os.chdir(original_cwd)
    module.set_seed(1)
    vocabulary = module.build_vocabulary(
        module.read_sequences(INPUTS["train_positive"]),
        module.read_sequences(INPUTS["train_negative"]),
    )
    device = module.resolve_device("cpu")
    model = module.load_model(CHECKPOINT, vocabulary, device)
    positive = module.read_sequences(INPUTS["test_positive"], expected_count=120)
    negative = module.read_sequences(INPUTS["test_negative"], expected_count=120)
    combined = negative + positive
    order = []
    for start in range(0, len(combined), 32):
        # Match the stable, descending sort in the unchanged official collate_fn.
        order.extend(
            sorted(
                range(start, min(start + 32, len(combined))),
                key=lambda index: len(combined[index].replace(" ", "")),
                reverse=True,
            )
        )
    with (output_dir / "rcnn_ECA_human_test_roc_1.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        official_rows = list(csv.DictReader(handle))
    if len(official_rows) != 240:
        raise RuntimeError("Original official output must contain all 240 predictions")

    cases = []
    for name, original_index, expected_label, source in (
        ("human_positive_line_1", 120, 1, INPUTS["test_positive"]),
        ("human_negative_line_1", 0, 0, INPUTS["test_negative"]),
    ):
        official_row_index = order.index(original_index)
        official_row = official_rows[official_row_index]
        if int(official_row["y_true"]) != expected_label:
            raise RuntimeError("The reconstructed official row does not match its source class")
        source_sequence = combined[original_index]
        sequence = source_sequence.replace(" ", "").upper()
        encoded = module.encode_sequences([source_sequence, source_sequence], vocabulary)
        inputs, _, lengths = module.collate_fn(
            [(encoded[0], expected_label), (encoded[1], expected_label)]
        )
        started = time.perf_counter()
        with torch.inference_mode():
            logits = model(inputs.to(device), lengths.to(device))
            scores = torch.softmax(logits, dim=-1)[:, 1].cpu().tolist()
            predicted_labels = logits.argmax(dim=1).cpu().tolist()
        duration_ms = (time.perf_counter() - started) * 1000
        rounded_score = float(official_row["y_score"])
        if abs(scores[0] - rounded_score) > 0.000051:
            raise RuntimeError("Supplemental score differs from the rounded official demo result")
        if scores[0] != scores[1]:
            raise RuntimeError("Duplicated identical inputs produced different scores")
        cases.append(
            {
                "id": name,
                "source_file": source.relative_to(UPSTREAM).as_posix(),
                "source_line_1based": 1,
                "source_class": expected_label,
                "sequence": sequence,
                "length": len(sequence),
                "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                "official_csv_data_row_0based": official_row_index,
                "official_csv_file_line_1based": official_row_index + 2,
                "official_rounded_score": rounded_score,
                "supplemental_full_precision_score": scores[0],
                "supplemental_logits": logits[0].cpu().tolist(),
                "predicted_label": "P" if predicted_labels[0] == 1 else "N",
                "supplemental_batch_size": 2,
                "supplemental_batch_runtime_ms": duration_ms,
            }
        )
    write_json(
        output_dir / "supplemental_predictions.json",
        {
            "runtime": runtime_information(torch, numpy, scipy, sklearn, pandas),
            "vocabulary": vocabulary,
            "cases": cases,
            "original_batch_size": 32,
            "supplemental_source": "unchanged official Human demo functions",
            "source_mutated": False,
            "supplemental_batch_size_reason": "Avoid the upstream bare squeeze() batch-one defect",
        },
    )


def write_report(metadata: dict, supplemental: dict, summary_rows: list[dict]) -> None:
    metadata = portable(metadata)
    supplemental = portable(supplemental)
    first = supplemental["cases"][0]
    runtime = supplemental["runtime"]
    table_rows = "\n".join(
        f"| {case['id']} | {case['length']} | {case['official_rounded_score']:.4f} | "
        f"{case['supplemental_full_precision_score']:.12g} | {case['predicted_label']} | "
        f"{case['official_csv_file_line_1based']} |"
        for case in supplemental["cases"]
    )
    summary = summary_rows[0]
    report = f"""# LRECA Human official baseline

本记录由 `scripts/run_lreca_baseline.py` 在真实官方运行成功后生成。
生成时间：{metadata["finished_at_utc"]}。

## 身份与执行顺序

- Repository: https://github.com/ai-phasepro/LRECA
- Commit: `{COMMIT}`
- Variant: `human_specific`；`dataset5_mapping_status=unconfirmed`。
- Checkpoint: `{CHECKPOINT_NAME}`，{CHECKPOINT.stat().st_size} bytes。
- SHA256: `{CHECKPOINT_SHA256}`。
- 配置 / 实际路径：`{portable(CHECKPOINT)}`。
- 首先独立运行未改动的官方 Human demo，batch=32、CPU、全部 120 正例及 120 负例。
- 仅在官方进程返回 0 后，第二个独立进程调用官方原始函数补充高精度分数。
- 两个阶段前后均检查固定 commit、上游工作树无改动及 checkpoint hash。

## 命令

外层命令（项目目录）：

```powershell
.\\.lreca-venv\\Scripts\\python.exe scripts/run_lreca_baseline.py
```

实际原始官方命令：

```text
{subprocess.list2cmdline(metadata["official_command"])}
```

工作目录：`{metadata["official_cwd"]}`。

环境变量：`PYTHONDONTWRITEBYTECODE=1`、`CUBLAS_WORKSPACE_CONFIG=:4096:8`、
`OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4`、`PYTHONUTF8=1`。
官方进程 wall time：**{metadata["official_wall_seconds"]:.3f} s**。

## 真实运行环境

- Python {runtime["python"]}；PyTorch {runtime["pytorch"]}。
- NumPy {runtime["numpy"]}；SciPy {runtime["scipy"]}；scikit-learn {runtime["scikit_learn"]}；
  pandas {runtime["pandas"]}。
- Device: `{runtime["device"]}`；PyTorch CUDA build: `{runtime["torch_cuda_build"]}`；
  CUDA available: `{runtime["cuda_available"]}`。本 baseline 实际计算仅使用 CPU。
- CPU computation threads: {runtime["cpu_threads"]}。
- Runtime executable: `{runtime["python_executable"]}`。

## 输入与输出

四个官方输入文件的完整路径、SHA256、行数保存在
`docs/audit/lreca_baseline_cpu/run_metadata.json`；原始序列仍保留在固定的上游测试文件中。
原始 stdout / stderr 与官方生成的 240 行 CSV 一并保存在同目录。

官方汇总 CSV：accuracy={summary["acc"]}、sensitivity={summary["sen"]}、
specificity={summary["spe"]}、AUC={summary["auc"]}。
这些是当前 demo 的 240 条测试结果，不代表论文完整数据集的重新评估。

| Fixture | Length | Official CSV score | Supplemental score | Predicted label | CSV file line |
|---|---:|---:|---:|---|---:|
{table_rows}

`human_negative_line_1` 来自 negative 测试集，但官方模型真实预测为 P；
它是这次 240 条 demo 的唯一错误分类。本 fixture 保留该结果，不将来源标签当作模型预测。

固定短 sequence（来源 `{first["source_file"]}:1`；{first["length"]} aa）：

```text
{first["sequence"]}
```

完整两条 fixture、sequence hash、logits、原始输出行对应和高精度分数在
`backend/tests/fixtures/lreca/global_baseline.json`。

## 分数语义、精度及来源限制

官方 Human demo 第 169–173 行将 negative 标为 0、positive 标为 1；
第 192–193 行以 argmax 生成预测标签，以 softmax(logits)[:, 1] 生成正类分数。
默认 0.5 阈值的精确 tie 属于 N；没有进行 probability calibration。

官方 CSV 第 203–204 行只保存 4 位小数，因此官方 CSV 回归绝对容差采用 `5.1e-5`；
同环境补充 full-precision 回归绝对容差采用 `1e-5`。
补充结果是单次原始官方函数推理，每条序列复制为 batch=2；没有修改权重或 forward。
这样避免原始 `.squeeze()` 在 batch=1 时移除 batch 维度。

官方 collate_fn 会在每个 batch 内按长度降序排序，即使 shuffle=False。
记录的 CSV 行号由此排序重建并用类别标签校验，不能按原始序列行直接配对。

本 baseline 仅覆盖 global prediction；Grad-CAM/KDE 回归另行验证。
原始 checkpoint 加载时出现 PyTorch `TypedStorage is deprecated` 警告，进程成功完成；
原始 stderr 已保留。
runtime 差异与官方 Python3.8 环境安装尝试见 `docs/lreca_runtime.md`。
"""
    REPORT.write_text(portable_text(report), encoding="utf-8", newline="\n")


def run_baseline() -> None:
    verify_identity()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
            "OMP_NUM_THREADS": "4",
            "MKL_NUM_THREADS": "4",
        }
    )
    command = [
        sys.executable,
        str(DEMO),
        "--device",
        "cpu",
        "--batch-size",
        "32",
        "--output-dir",
        str(OUTPUT),
    ]
    metadata = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/ai-phasepro/LRECA",
        "repository_commit": COMMIT,
        "model_variant": "human_specific",
        "dataset5_mapping_status": "unconfirmed",
        "checkpoint": CHECKPOINT_NAME,
        "checkpoint_path": str(CHECKPOINT),
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_size_bytes": CHECKPOINT.stat().st_size,
        "official_command": command,
        "official_cwd": str(UPSTREAM / "Demo"),
        "inputs": {
            name: {
                "path": str(path),
                "sha256": sha256(path),
                "sequence_count": len(path.read_text(encoding="utf-8").splitlines()),
            }
            for name, path in INPUTS.items()
        },
    }
    print("Running unchanged official Human demo first (CPU, batch=32).", flush=True)
    started = time.perf_counter()
    with (
        (OUTPUT / "demo_stdout.log").open("w", encoding="utf-8") as stdout,
        (OUTPUT / "demo_stderr.log").open("w", encoding="utf-8") as stderr,
    ):
        result = subprocess.run(
            command, cwd=UPSTREAM / "Demo", env=env, stdout=stdout, stderr=stderr, check=False
        )
    metadata["official_returncode"] = result.returncode
    metadata["official_wall_seconds"] = time.perf_counter() - started
    for name in ("demo_stdout.log", "demo_stderr.log"):
        export_log(OUTPUT / name)
    write_json(OUTPUT / "run_metadata.json", metadata)
    if result.returncode:
        raise RuntimeError(f"Official demo failed; inspect {OUTPUT / 'demo_stderr.log'}")
    verify_identity()
    print("Original official demo passed; recording supplemental precision.", flush=True)
    supplement_command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--supplement",
        str(OUTPUT),
    ]
    try:
        with (
            (OUTPUT / "supplement_stdout.log").open("w", encoding="utf-8") as stdout,
            (OUTPUT / "supplement_stderr.log").open("w", encoding="utf-8") as stderr,
        ):
            subprocess.run(
                supplement_command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, check=True
            )
    finally:
        for name in ("supplement_stdout.log", "supplement_stderr.log"):
            export_log(OUTPUT / name)
    verify_identity()
    supplemental = json.loads(
        (OUTPUT / "supplemental_predictions.json").read_text(encoding="utf-8")
    )
    metadata["supplemental_command"] = supplement_command
    metadata["runtime"] = supplemental["runtime"]
    metadata["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["upstream_unchanged"] = True
    write_json(OUTPUT / "run_metadata.json", metadata)
    fixture = {
        "schema_version": 1,
        "repository": metadata["repository"],
        "repository_commit": COMMIT,
        "model_variant": "human_specific",
        "dataset5_mapping_status": "unconfirmed",
        "checkpoint": CHECKPOINT_NAME,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_size_bytes": CHECKPOINT.stat().st_size,
        "runtime": supplemental["runtime"],
        "score_semantics": "softmax(logits)[:, 1], positive LLPS class; uncalibrated",
        "positive_class_index": 1,
        "threshold": 0.5,
        "threshold_operator": ">",
        "vocabulary": supplemental["vocabulary"],
        "official_rounded_absolute_tolerance": 0.000051,
        "supplemental_absolute_tolerance": 0.00001,
        "cases": supplemental["cases"],
    }
    write_json(FIXTURE, fixture)
    with (OUTPUT / "result.csv").open(encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    write_report(metadata, supplemental, summary_rows)
    print(
        json.dumps(
            {
                "status": "success",
                "official_wall_seconds": metadata["official_wall_seconds"],
                "official_prediction_count": 240,
                "fixture": portable(FIXTURE),
                "report": portable(REPORT),
                "cases": [
                    {"id": case["id"], "score": case["supplemental_full_precision_score"]}
                    for case in supplemental["cases"]
                ],
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supplement", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.supplement is not None:
        supplemental_predictions(args.supplement.resolve())
    else:
        run_baseline()


if __name__ == "__main__":
    install_portable_excepthook("run_lreca_baseline")
    main()
