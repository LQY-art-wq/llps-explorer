# 模型与本地工具来源审计（Module 0 / Module 1）

审计日期：2026-09-03（Asia/Shanghai）。Module 0 完成源码审计；Module 1 已完成
固定 Human checkpoint 的官方原始 demo、真实 CPU/CUDA 推理、Grad-CAM 和 KDE 验证。
当前状态及证据见 [Module 1 报告](module1_report.md)、[Human 身份](lreca_identity.md)、
[官方基线](lreca_baseline.md) 和 [运行环境](lreca_runtime.md)。SEG 保持 Module 0 审计状态。

## 1. LRECA 来源及锁定版本

| 项目 | 审计结果 |
| --- | --- |
| 官方仓库 | [ai-phasepro/LRECA](https://github.com/ai-phasepro/LRECA) |
| 固定 commit | `0b4b48ab7870529a34028c6e30dfba42eddbf215` |
| commit 时间 | 2026-08-14 15:48:30 +08:00 |
| 本地目录 | `external/lreca/`，独立上游 checkout，未修改源码 |
| 源码 license | `LICENSE.md` 为 MIT；版权年份和权利人仍为占位符 |
| 授权边界 | README 特别说明第三方数据、预训练模型等受原始来源条款约束；不能把源码 MIT 自动扩展到所有材料 |
| 官方 Python | README：3.8；`requirements.yml`：3.8.18 |
| 官方 PyTorch | README 与 YAML：2.1.1+cu118；`requirements.txt` 没有固定 torch |
| 主要依赖 | NumPy 1.23.0、pandas 2.0.3、scikit-learn 1.3.2、SciPy 1.10.1、matplotlib 3.7.4、Biopython 1.81、openpyxl 3.1.2 |
| 依赖局限 | YAML 含 Linux/Conda 路径、CUDA 与 triton，不能直接当作 Windows 环境文件使用 |

依据：[固定版本 README](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/README.md)、[LICENSE.md](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/LICENSE.md)、[requirements.yml](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/requirements.yml)、[requirements.txt](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/requirements.txt)。

上游 README 指向论文题名 “Discovery of phase separation protein with single amino acid
attributions by unbiased deep-learning”。本轮成功读取的材料没有给出可独立核对的
论文 dataset5 编号定义。**human 模型的源码映射已确认；“论文 dataset5 = human”
的编号关系尚未完成独立论文核验，dataset5_mapping_status = unconfirmed。**
运行时使用 `model_variant = human_specific`，不将这两项证据合并表述。

## 2. Human checkpoint 候选与状态

仅发现一个名称为 human 且被人源测试入口明确指定的 checkpoint：

```text
LRECA_REPO=https://github.com/ai-phasepro/LRECA
LRECA_COMMIT=0b4b48ab7870529a34028c6e30dfba42eddbf215
LRECA_CHECKPOINT_PATH=external/lreca/Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt
LRECA_CHECKPOINT_SHA256=aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc
LRECA_MODEL_VARIANT=human_specific
dataset5_mapping_status=unconfirmed
```

上方路径相对于本项目根目录，部署时通过 `LRECA_CHECKPOINT_PATH` 指向挂载文件。
旧配置名 `LRECA_CHECKPOINT` 仍兼容。来源 manifest 中的 checkpoint 路径则相对于上游根目录；
两者的解析基准明确区分。模型 bytes 不进入本项目 Git，只有清单、文件名/哈希和获取说明。

文件大小 **2,395,318 bytes**。`RCNN_ECA_3_human_test.py` 的 `DEFAULT_MODEL` 直接指向它；
该入口使用 Human 正负样本及匹配的 512 维模型。默认候选无需在多个人源文件之间猜选。
Module 0 时已下载并核对 SHA256，未加载和推理；Module 1 身份复核确认 `human_specific`。
固定源码没有 dataset5 的明确编号映射，因此改正 Module 0 的 variant 命名，不在运行时冒称 dataset5。
机器可读记录：[external/lreca-source.json](../external/lreca-source.json)。
依据：[Human 测试入口](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py)。

### 全部 checkpoint 文件

以下用途由对应脚本和 README 判断，不由文件名中的数字推断指标或交叉验证含义。
所有文件完整 SHA256 已保存于 [checkpoint inventory](audit/lreca_checkpoints.json)。

| 仓库内文件 | bytes | 来源说明 / 可能用途 | 本项目默认 |
| --- | ---: | --- | --- |
| `Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt` | 2,395,318 | Human 测试入口明确指定的人源分类权重 | Module 1 已真实验证 |
| `Demo/trained_model/model_LLPS_0.pt` | 8,209,934 | LLPS/PDB 分类演示 | 否 |
| `Demo/trained_model/model_R_3.pt` | 4,339,162 | PhasepDB reviewed/PDB 分类演示 | 否 |
| `Demo/trained_model/model_high_2.pt` | 5,491,418 | PhasepDB high-throughput/PDB 分类演示 | 否 |
| `Demo/trained_model/model_mydata_1.pt` | 4,339,162 | in-house/PDB 分类演示 | 否 |
| `Demo/trained_model/mydata_1507_RCNN_ECA_089-0.9930.pt` | 2,393,227 | in-house 解释性模型相关权重 | 否 |
| `Demo/saliency_model/mydata_1507_RCNN_ECA_089-0.9930.pt` | 2,393,227 | Grad-CAM 演示实际加载；与上一文件 SHA256 相同 | 否 |

共有 **7 个文件、6 个不同 SHA256**。不得把 `mydata` saliency 权重标为 human，
也不得用 dataset1 权重作为缺失时的静默后备。

## 3. 推理入口、预处理与词表

官方人源演示入口（Module 1 已先执行原始 demo，完整命令见基线报告）：

```text
cd external/lreca/Demo
python code_for_model_testing/RCNN_ECA_3_human_test.py --device cpu
```

这个入口针对固定的 120 positive + 120 negative 演示样本，不是通用单序列 HTTP API。
模型类来自 `Demo/code_for_model_testing/RCNN_ECA_personal_test.py`。后者 import 时有
打印和 `os.chdir` 副作用，不应直接作为共享 FastAPI 模块导入。

人源入口读取 Human 训练文本，用 NumPy 的 legacy shuffle 分别以 seed 0 / 1 排序，
然后按正样本→负样本、残基首次出现的顺序分配编号，padding=0。这不是字母排序词表。
两个词表来源文件各有 980 行；其哈希及实际重建结果保存于
[lreca_human_vocabulary.json](audit/lreca_human_vocabulary.json)。审计重建使用本机
NumPy 2.3.5；Module 1 已在最终 NumPy 1.23.0 环境复用官方函数重建并验证完全一致。

```text
m:1 v:2 k:3 e:4 t:5 y:6 d:7 l:8 g:9 p:10
n:11 a:12 q:13 r:14 h:15 f:16 i:17 s:18 c:19 w:20
padding:0
```

训练文本为小写、空格分隔。演示编码移除普通空格；personal 输入处理包含转小写。
Module 1 API 已按用户约定解析 raw/单条 FASTA、去空白、ASCII 转大写、拒绝 B/J/O/U/X/Z，
再显式映射到上游小写词表。不能直接把任意用户字符交给 `dict.get` 后当 padding。
序列解析器在进入模型前运行。官方 `collate_fn` 按长度排序、padding 并使用真实长度；
将来输出必须恢复输入顺序，不能把排序后的分数配给排序前的蛋白。

## 4. 匹配模型及 global output

匹配 checkpoint 的源码构造为 `RCNN(21, 512, 100, 1, True)`：

1. Embedding：21×512，padding index 0。
2. 单层双向 LSTM，每方向 hidden size 100。
3. Embedding 与 BiLSTM 输出拼接形成 712 维特征，经 ReLU。
4. ECA：按实际长度做 average pooling，kernel size 5 的 Conv1d 和 sigmoid；残差相加。
5. 沿序列 global max pooling；MLP 712→128→32→2，含 dropout 0.2。

`forward` 返回两个 **logits**；人源入口取 `softmax(logits)[:, 1]` 作为 positive score，
label 0 为 negative，label 1 为 positive。README 对返回概率的概述需结合这一实际调用理解。
分类代码使用 `argmax`：P 对应正类 logit 严格较大，即正类概率 **>0.5**；精确平局归 0/N。
不存在已核实的额外校准器。Ensemble 的 calibration 不能在后续被默认为已完成。

依据：[匹配模型与 preprocessing](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_personal_test.py)、[Human 推理调用](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py)。

**版本内差异：** `RCNN_model/RCNN_ECA_3_human.py` 当前训练入口采用 embedding=1024，
默认 shuffle seeds=20/21；它不能替代上述 checkpoint 的 512 维、seed 0/1 推理定义。
另外，匹配模型 `globalmaxpool(...).squeeze()` 会在 batch=1 时去掉 batch 维，
会破坏单序列调用；Module 1 在自己的兼容层仅改为 `.squeeze(-1)`，保留 batch 维。
已与官方原始 batch 输出对照；上游源码未改动。

## 5. Grad-CAM 与 KDE

主要源码：

- [Grad-CAM method](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/method/RCNN_ECA_saliency_gradCAM.py)
- [single-sequence saliency demo](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/verify/RCNN_ECA_saliency_verify_gradCAM_fortest.py)
- [KDE / critical region implementation](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/LCRs_process/split_LCRs_segment_forsingle.py)
- [demo wrapper](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/get_score_forsingle.py)

Grad-CAM 对 ReLU 后、ECA 前拼接的 `out_all` 求目标 logit 梯度，沿真实序列长度平均
得到 channel weights，再逐 channel 乘 feature map 并相加，获得 residue contribution。
`create_cam` 没有末端 ReLU，原始 attribution 可以为负，不是 LLPS 概率。
当 target 未指定时，上游使用预测类别；正类解释与负类解释需明确 target_class。
默认演示实际加载 `mydata` 权重，不能用于解释 human classifier 的结果。

单序列 wrapper 把同一序列写成两行，使用共享 `Saliency_output/test.xlsx`、固定输出文件、
`os.system` 和 `os.rename` 串联多个脚本；该演示不是可并发使用的服务接口。
Module 1 已以持久 worker、无文件中间结果和有界串行 IPC 处理 batch=1 与并发请求隔离。
科学函数直接复用；没有将共享文件 wrapper 暴露为服务。

KDE 的输入是 **attribution 数值本身**，不是 residue position 加权点集。
它对 score values 使用 `KernelDensity`，通过 `GridSearchCV` 从
`logspace(-1, 1, 20)` 选 bandwidth，再在原 score values 上计算密度并还原到序列顺序。
之后用 Savitzky–Golay（window=50、polyorder=3）平滑，反转为峰谷信号，按谷分段并
选择累计值最大的区域；其 `LCRs_process` 目录名不代表 SEG low-complexity annotation。

Module 1 明确了短序列、常量/全零归因、目标类别、batch=1 和半开切片的处理。
固定 Savitzky–Golay window=50，因此小于 50 aa 时仅 KDE 不可用。
原始 `[left:right]` 以 `N-1` 为末端，遗漏最后一个残基：保留这一行为并输出 warning，
API 区间转为 `[left+1,right]`（1-based inclusive）。详情和实际参考对照见
[解释实现](lreca_explainability.md)。不改写成位置加权 KDE 或阈值连续区间。

## 6. SEG 固定实现（Module 3）

本节更新为 Module 3 的实际安装与源码核验结果；页首关于 SEG 的 Module 0 描述保留为历史记录。
**选定 NCBI BLAST+ 2.17.0+ 的 `segmasker` CLI**，已实际运行 Windows 官方二进制。
这是一种低复杂度区域（LCR）注释方法，semantic_type 为 `region_annotation`，不生成
LLPS probability、P/N 或 attribution，也不替代 LRECA 的 KDE derived hotspots。

| 项目 | 当前证据 |
| --- | --- |
| 来源 | [NCBI 官方 2.17.0 发行目录](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/) |
| 版本 | distribution `2.17.0+`；Windows 实际 Package `blast 2.17.0`、application `segmasker: 1.0.0`，分别记录 |
| Windows archive SHA256 | `ccde8788641e8f4137536aaadedfeac2f3599dbbc6166e701b5d89d19fa79038` |
| Windows executable SHA256 | `82f56232e2acf9a4ad3cd84efc6abd7387c1781f3b2f6727b9b1f12158c2381c` |
| defaults | window=12、locut=2.2、hicut=2.5；后端显式传参 |
| input/output | 单条 FASTA 经 stdin 输入，interval 经 stdout 返回，无共享临时文件 |
| coordinates | 固定版本源码及真实首尾用例确认 native 0-based inclusive；API 两端各加 1，length=end-start+1 |
| merge | 固定源默认 `overlaps=FALSE`；只在该开关为真时调用 merge。本地保留 native 区域，不重建或额外合并 |
| license / privacy | 保留发行包 PUBLIC DOMAIN / Government Work notice 及其他 notices；每个子进程显式设 `BLAST_USAGE_REPORT=false` |
| Linux | 官方 x64 archive/MD5 已确认，archive/binary SHA256 尚未实测，未下载或运行 Linux 包；不能称 Docker 验收完成 |

实际调用使用的参数形式（`segmasker` 由 `SEG_EXECUTABLE_PATH` 或 PATH 解析）：

```text
segmasker -in - -out - -infmt fasta -outfmt interval -window 12 -locut 2.2 -hicut 2.5
```

固定 [2.17.0 source ZIP](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-src.zip)
已通过官方 MD5，SHA256 为 `cdcd9e36f2b581eff9bd8364875a466289253b716d3a8014838a8305a9d11880`。
源码 `blast_seg.c:45–47` 给出默认值、2236 行关闭 overlaps、2321–2322 行条件调用 merge；
`segmask.cpp:75–87` 以 offset=0 使用 left/right，`mask_writer_int.cpp:52` 原样写出两端。
这些行号以固定发行源包为准，不能用会更新的在线 Doxygen 页面冒称同一版本。

已实跑的 100Q 用例输出 `0 - 99`；140-aa C 端用例输出 `100 - 139`，支持上述 inclusive
转换。人工构造序列用于验证工具行为，真实蛋白用例也不构成生物学 LLPS 验证。
官方用法：[NCBI masking applications](https://www.ncbi.nlm.nih.gov/sites/books/NBK569845/)；
usage reporting opt-out：[NCBI Privacy](https://www.ncbi.nlm.nih.gov/books/NBK569851/)。

安装脚本仅用标准库，复用经过 checksum 校验的缓存并拒绝覆盖不同内容的已有安装，不改 PATH。
完整版本、每个保留成员和固定源码的 SHA256 见 [seg-source.json](../external/seg-source.json)，
安装、配置、许可与 Linux 部署边界见 [SEG runtime](seg_runtime.md)。

## 7. 尚未确认的边界

- dataset5 编号仍需可引用论文/补充材料证明；这不影响已确认的 Human→checkpoint 映射。
- 官方 Python 3.8.18 未成功构建，本次使用已验证的独立 Python 3.10.19 / Torch 2.1.1+cu118 环境。
- 解释和 global score 使用同一个已加载 Human 权重与词表；target 为真实 argmax 类别，未做概率校准。
- 回归样例与 CPU/GPU 验证不构成独立生物学验证或通用模型质量结论。
