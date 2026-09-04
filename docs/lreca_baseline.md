# LRECA Human official baseline

本记录由 `scripts/run_lreca_baseline.py` 在真实官方运行成功后生成。
Production 补充阶段仅将开发机器路径转换为 `${PROJECT_ROOT}` 等引用；未重跑 demo，所有输入、分数、时间和版本保留原值。原始字节已归档至被忽略的 `.audit/module1_private_evidence/`。
生成时间：2026-09-03T08:44:11.084579+00:00。

## 身份与执行顺序

- Repository: https://github.com/ai-phasepro/LRECA
- Commit: `0b4b48ab7870529a34028c6e30dfba42eddbf215`
- Variant: `human_specific`；`dataset5_mapping_status=unconfirmed`。
- Checkpoint: `human_1_RCNN_ECA_parallel_089-0.9802.pt`，2395318 bytes。
- SHA256: `aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc`。
- 配置 / 实际路径：`${PROJECT_ROOT}/external/lreca/Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt`。
- 首先独立运行未改动的官方 Human demo，batch=32、CPU、全部 120 正例及 120 负例。
- 仅在官方进程返回 0 后，第二个独立进程调用官方原始函数补充高精度分数。
- 两个阶段前后均检查固定 commit、上游工作树无改动及 checkpoint hash。

## 命令

外层命令（项目目录）：

```powershell
.\.lreca-venv\Scripts\python.exe scripts/run_lreca_baseline.py
```

实际官方命令的路径变量化记录（不是新执行记录）：

```text
${PROJECT_ROOT}\.lreca-venv\Scripts\python.exe ${PROJECT_ROOT}\external\lreca\Demo\code_for_model_testing\RCNN_ECA_3_human_test.py --device cpu --batch-size 32 --output-dir ${PROJECT_ROOT}\docs\audit\lreca_baseline_cpu
```

工作目录：`${PROJECT_ROOT}\external\lreca\Demo`。

环境变量：`PYTHONDONTWRITEBYTECODE=1`、`CUBLAS_WORKSPACE_CONFIG=:4096:8`、
`OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4`、`PYTHONUTF8=1`。
官方进程 wall time：**12.235 s**。

## 真实运行环境

- Python 3.10.19；PyTorch 2.1.1+cu118。
- NumPy 1.23.0；SciPy 1.10.1；scikit-learn 1.3.2；
  pandas 2.0.3。
- Device: `cpu`；PyTorch CUDA build: `11.8`；
  CUDA available: `True`。本 baseline 实际计算仅使用 CPU。
- CPU computation threads: 4。
- Runtime executable: `${PROJECT_ROOT}\.lreca-venv\Scripts\python.exe`。

## 输入与输出

四个官方输入文件的完整路径、SHA256、行数保存在
`docs/audit/lreca_baseline_cpu/run_metadata.json`；原始序列仍保留在固定的上游测试文件中。
stdout / stderr 的路径脱敏导出与官方生成的 240 行 CSV 一并保存在同目录；未脱敏日志仅在私有归档。

官方汇总 CSV：accuracy=0.9958、sensitivity=1.0000、
specificity=0.9917、AUC=0.9992。
这些是当前 demo 的 240 条测试结果，不代表论文完整数据集的重新评估。

| Fixture | Length | Official CSV score | Supplemental score | Predicted label | CSV file line |
|---|---:|---:|---:|---|---:|
| human_positive_line_1 | 248 | 1.0000 | 0.999992132187 | P | 128 |
| human_negative_line_1 | 4486 | 0.9949 | 0.994876563549 | P | 2 |

`human_negative_line_1` 来自 negative 测试集，但官方模型真实预测为 P；
它是这次 240 条 demo 的唯一错误分类。本 fixture 保留该结果，不将来源标签当作模型预测。

固定短 sequence（来源 `Demo/test_dataset/pos_dataset/pos_word_list_human_test.txt:1`；248 aa）：

```text
MSGGGVIRGPAGNNDCRIYVGNLPPDIRTKDIEDVFYKYGAIRDIDLKNRRGGPPFAFVEFEDPRDAEDAVYGRDGYDYDGYRLRVEFPRSGRGTGRGGGGGGGGGAPRGRYGPPSRRSENRVVVSGLPPSGSWQDLKDHMREAGDVCYADVYRDGTGVVEFVRKEDMTYAVRKLDNTKFRSHEGETAYIRVKVDGPRSPSYGRSRSRSRSRSRSRSRSNSRSRSYSPRRSRGSPRYSPRHSRSRSRT
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
