# LRECA Human 模型身份与分数语义

核验日期：2026-09-03。此文档描述固定上游版本的代码证据及真实运行记录；不把文件名、第五个列举项或训练脚本的最新参数当作 checkpoint 的训练历史证明。

## 身份结论

```json
{
  "repository": "https://github.com/ai-phasepro/LRECA",
  "commit": "0b4b48ab7870529a34028c6e30dfba42eddbf215",
  "model_variant": "human_specific",
  "dataset5_mapping_status": "unconfirmed",
  "checkpoint": "human_1_RCNN_ECA_parallel_089-0.9802.pt",
  "checkpoint_sha256": "aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc",
  "checkpoint_size_bytes": 2395318
}
```

当前可确认的是：**官方 Human demo 明确指定这份 checkpoint，配套 Human 正负序列来源，并选择与其匹配的 512 维模型实现；该原始 demo 已实际运行成功。** 本阶段结果使用 `human_specific`。没有找到能够把该权重直接映射为论文中“dataset5”的显式官方编号证据，故保持 `unconfirmed`，不输出 `dataset5` 模型别名。

默认权重位置（相对于项目根目录）：

`${PROJECT_ROOT}/external/lreca/Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt`

首选通过 `LRECA_CHECKPOINT_PATH` 配置实际位置；旧别名 `LRECA_CHECKPOINT` 仍兼容。
路径由 `pathlib.Path` 解析，可指向 Linux 容器的只读模型挂载目录。
`get_lreca_model_metadata()` 是内部 helper，同时记录配置路径、解析后路径、来源哈希及 worker 环境，供启动验证和服务端日志使用。
HTTP 使用独立的公开 metadata，仅包含本节 JSON 的 7 项身份字段，不返回内部路径、源码映射或 runtime 对象。
路径可配置，但 commit、模型权重字节及必要来源文件必须匹配已核验身份；不会因路径错误自动换用其他权重。

## 可追溯证据链

下表行号在本次交付时重新读取确认；全部指向固定 commit `0b4b48ab7870529a34028c6e30dfba42eddbf215` 的原始文件。

| 来源 | 已确认内容 | 不能由它单独推出的内容 |
|---|---|---|
| [README.md 第 18–24 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/README.md#L18) | 五组 dataset-specific 代码中明确列出 balanced Human 数据集；Human 数据、训练脚本和 demo 对应关系清楚 | 列表第五项不等于论文明确命名的 dataset5；不证明每条数据的人类物种注释已逐条审计 |
| [Human demo 第 24–34 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py#L24) | 注释明确说明匹配的 personal/human 512 维实现；显式引用 Human 正负训练/测试文件和唯一指定的 Human checkpoint | 不能据此恢复完整原始训练历史或作者未提供的编号体系 |
| [Human demo 第 86–102 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py#L86) | 官方说明与第一轮 Human 训练的词表一致：正负样本分别按 0/1 seed 打乱，按正类再负类首次出现顺序编号 | 不能换成当前 Human 训练脚本的默认 20/21 seed |
| [Human demo 第 119–139 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py#L119) | 权重读取、embedding shape 检查，以及 `RCNN(21,512,100,1,True)` 的严格 state-dict 加载路径 | 权重张量形状能证明架构兼容，不能自行证明 dataset5 编号或物种来源 |
| [真实原始 demo 记录](audit/lreca_baseline_cpu/run_metadata.json) | 固定源码、指定 Human checkpoint、CPU、240 条 demo 输入实际完成，退出码 0，上游未修改 | 这是公开 demo 的复现，不能当作新独立外部验证或实验验证 |

在已固定仓库的 Markdown、Python、YAML、JSON、文本配置和脚本中检索了 `dataset5`、`dataset_5`、`dataset-5`、`species-matched`、`human-specific` 等明确编号/术语，未找到直接的 dataset5 映射。README 第 6 行仅给出配套论文题名；本阶段未取得并逐段核对论文全文/补充材料。因而“论文 dataset5 身份已验证”不在本报告的结论范围内。

## 架构选择与当前训练脚本的差异

生产运行复用的是 [personal classifier 中的 RCNN 定义](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_personal_test.py#L272)，这是 Human demo 明确导入的模型。其结构为 embedding 21×512（padding index 0）、双向 LSTM（每个方向 hidden size 100）、拼接得到 712 个通道、ReLU、kernel size 5 的 ECA 加残差、全局最大池化，以及 712→128→32→2 分类层。严格加载的是同一份 Human state dict。

同一 commit 的 [Human 训练脚本第 35–36 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/RCNN_model/RCNN_ECA_3_human.py#L35) 默认 seed 为 20/21，[第 174、383 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/RCNN_model/RCNN_ECA_3_human.py#L174) 使用 embedding 1024。因此不能把当前训练脚本的默认配置直接套在所交付的 512 维权重上，也不能把本次运行写成重新训练或精确恢复了该权重的全部训练过程。

解释性 demo 默认使用另一份 mydata 权重及 mydata 词表。这是独立的上游默认值；本项目的分类和归因始终使用已经核验的 **同一份 Human 权重与 Human 词表**。解释性参考计算明确标记为 Human-adapted original reference，详见 [解释性说明](lreca_explainability.md)。

## 词表、编码与类别映射

Human 正/负词表来源各 980 条，直接复用官方 `read_sequences`、`build_vocabulary`、`encode_sequences`，并复用原始 `collate_fn` 的 0 padding、长度排序与真实长度张量。模型继续使用 `pack_padded_sequence`/`pad_packed_sequence`。API 清理空白、接受 ASCII 大小写并移除单条 FASTA header 后，保留标准 20 种氨基酸；进入官方编码函数时转为它所用的小写符号。

| 氨基酸 | Index | 氨基酸 | Index | 氨基酸 | Index | 氨基酸 | Index |
|---|---:|---|---:|---|---:|---|---:|
| M | 1 | Y | 6 | N | 11 | F | 16 |
| V | 2 | D | 7 | A | 12 | I | 17 |
| K | 3 | L | 8 | Q | 13 | S | 18 |
| E | 4 | G | 9 | R | 14 | C | 19 |
| T | 5 | P | 10 | H | 15 | W | 20 |

Index 0 仅用于 padding。`X/B/J/O/U/Z` 没有被编码为 0、删除或替换；输入验证应报告残基与清理后序列中的 1-based 位置。

类别来源不仅是 `softmax[:,1]` 的习惯约定：[Human demo 第 169–174 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py#L169) 显式构造负例 label 0、正例 label 1；[Human 训练脚本第 314–316 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/RCNN_model/RCNN_ECA_3_human.py#L314) 的 train/validation/test 标签也使用相同映射。Demo [第 186–193 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py#L186) 以 `argmax` 取分类，并输出 `softmax(logits)[:,1]`。

对于两个 logits `z0,z1`：

```text
raw_score = exp(z1) / (exp(z0) + exp(z1))
positive_class_index = 1
calibrated_score = raw_score
calibration_status = "not_calibrated"
label = "P" if raw_score > configured_threshold else "N"
```

实现使用数值稳定的 PyTorch softmax，而非直接计算上述指数式。默认 `LRECA_CLASSIFICATION_THRESHOLD=0.5`；输出 `threshold_operator=">"`。两个 logits 相同的官方 argmax 返回 class 0，故阈值相等时归 N。`calibrated_score` 只是当前未校准状态下的同值占位字段，不能描述为已经校准的概率。

## 真实 baseline 与解释基准的区分

未改动的官方 Human demo 使用 120 正例和 120 负例，CPU 实际耗时 12.2354938 秒（包含该命令的完整运行开销），输出文件和 stdout/stderr 已保存。原始 CSV 用四位小数保存分数；补充提取保存了同一官方模型的较高精度 logits/score，并记录了使用的 batch size。

- [原始 demo 元数据](audit/lreca_baseline_cpu/run_metadata.json)
- [原始 240 条分数](audit/lreca_baseline_cpu/rcnn_ECA_human_test_roc_1.csv)
- [global regression fixture](../backend/tests/fixtures/lreca/global_baseline.json)
- [Human 解释性参考 fixture](../backend/tests/fixtures/lreca/attribution_baseline.json)

## 文件哈希

下列路径以 `external/lreca/` 为根。哈希为完整文件 SHA256；demo 输入哈希也保存在真实 baseline 元数据中。

| 文件 | SHA256 |
|---|---|
| `Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt` | `aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc` |
| `README.md` | `e152c7a9b6e85d5ba49b4ad1bf0d56c56ce864300c9e554c691d94b854a0dfdf` |
| `Demo/code_for_model_testing/RCNN_ECA_3_human_test.py` | `68a5b205d41f26610e08a3b2eccd326d22d74d4083ca7c33f2c64789a7093c4b` |
| `Demo/code_for_model_testing/RCNN_ECA_personal_test.py` | `abcb72672a69a0758c08c557ca0e886d451a8f9aabf7f5bce92591e526cb7669` |
| `RCNN_model/RCNN_ECA_3_human.py` | `7cf9692f229f7416e916bff3004ffd13eebcc4bbc9c3630153abc0134f8b5904` |
| `Data/pos_dataset/pos_word_list_human.txt` | `1e3beca27c80a5fc59c41bbb5cc40f429a0619bd3dcc6172a42dbe85cd90ad32` |
| `Data/neg_dataset/neg_word_list_human.txt` | `e793a6eaa512e42ab72dd236cdaf13d20e14c3971def800b3aabc261193da1ea` |
| `Demo/test_dataset/pos_dataset/pos_word_list_human_test.txt` | `0fefb299e2ae8cbbd3cddc1e39955f4255b902b6168acd325c22e45c2c3a70e3` |
| `Demo/test_dataset/neg_dataset/neg_word_list_human_test.txt` | `0739c49b4acfd17193ec9694f87cccaf831a752d6f11c903459fc3c46cef6c79` |

运行前的核心来源校验见 [metadata.py](../backend/lreca_runtime/metadata.py)。解释性函数的独立源码哈希见 [upstream.py](../backend/lreca_runtime/upstream.py)。
