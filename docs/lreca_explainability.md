# LRECA Human 归因与 KDE 的原始行为及兼容层

核验日期：2026-09-03。固定上游 commit：`0b4b48ab7870529a34028c6e30dfba42eddbf215`。下文依据已经读取的官方源码及真实比较结果，保留其科学计算行为，并单独标明兼容处理。模型身份与类别映射见 [Human 身份说明](lreca_identity.md)。

## 原始路径和来源锚点

为了使行号可复查，下文使用 S、T2、T5、K 作为以下固定文件的简称。

| 简称 | 原始文件 | 关键行号 |
|---|---|---|
| W | [get_score_forsingle.py](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/get_score_forsingle.py) | 47–54：输入复制两份，顺序运行 S→T2→T5→K |
| S | [RCNN_ECA_saliency_verify_gradCAM_fortest.py](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/verify/RCNN_ECA_saliency_verify_gradCAM_fortest.py) | 295–310：特征；324–333：CAM；350–373：梯度目标；376–411：归一化；517–518：CSV 精度；568–569、604–607：mydata 默认 |
| T2 | [RCNN_ECA_statics2_fortest.py](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/statics/RCNN_ECA_statics2_fortest.py) | 41–46、59–66：从原始归因 CSV 复制逐位 score 到 `test_statics.csv` |
| T5 | [RCNN_ECA_statics5_fortest.py](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/statics/RCNN_ECA_statics5_fortest.py) | 19–34、38–59：按氨基酸类型做均值/总和；54 行 `/2` 补偿双份输入 |
| K | [split_LCRs_segment_forsingle.py](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/code_for_model_testing/RCNN_ECA_saliency/LCRs_process/split_LCRs_segment_forsingle.py) | 92–151：峰谷；154–191：平滑、分段和主区域；307–333：KDE 输入和拟合；249、288：原始坐标 |

S 默认的权重和词表是 mydata，不可把该默认路径直接接到 Human API。当前引擎从 Human demo 指定的模型、权重和词表出发，在同一驻留模型上完成分类和归因。参考 harness 则显式把原始 S 的模型参数替换为同一 Human state dict 和 Human 词表，其他科学函数保持原始定义。这个参考是 **Human-adapted original saliency reference**，与未改动的官方 Human classification demo 分开记录。

## Grad-CAM 的精确定义

对于长度 N 的序列，S 第 295–310 行得到的 `out_all` 是 embedding 与双向 LSTM 输出拼接后、ReLU 后、ECA 之前的张量，形状为 `[batch,N,712]`。模型继续经过 ECA 残差、全局最大池化及分类层，得到两个 logits `z0,z1`。

```text
c = argmax([z0, z1])
A[k,i] = out_all 的第 k 通道、第 i 个残基特征
g[k,i] = ∂zc / ∂A[k,i]
alpha[k] = (1/N) * sum_i g[k,i]
raw_cam[i] = sum_k alpha[k] * A[k,i]
```

梯度目标是选中类别的 **softmax 前 logit**。默认目标为原始 argmax，既可能是 class 1，也可能是 class 0；没有强制把负预测解释为“促 LLPS”贡献。API 因此返回 `attribution_target_class_index` 和 `attribution_target_label`。如果用户修改 classification threshold，归因目标仍保持官方 argmax 定义，并通过这两个字段明确标识。

`create_cam` 裁剪到真实长度后再求通道均值，用 float32 CAM 数组逐通道累加。没有对最终 CAM 再做 ReLU；raw CAM 可以有负值。没有使用 Grad-CAM++：原始函数虽然存在，该调用已被注释。

归一化直接复用 S 第 376–411 行的 `rescale_score_by_abs`。对非全零且有限的 raw CAM，其数学表达可写为：

```text
M = max_i abs(raw_cam[i])
normalized[i] = 0.5 + 0.5 * raw_cam[i] / M    (M > 0)
```

实际运行保留原始分支与数值运算顺序，而不是另写该简式。正的常量 CAM 映射为 1，负的常量 CAM 映射为 0。这是围绕 0.5 的绝对最大值缩放，**不是 min–max normalization，也不是 residue LLPS probability**。`semantic_type="model_attribution"`。

API 返回归一化结果的完整浮点精度，逐残基 `position=1...N`，氨基酸与规范化序列一致。Top residues 仅按这些相同 score 降序排列；相等时按原始位置递增，默认 Top 10，由 `LRECA_TOP_RESIDUES` 控制。不会因为入选 Top residues 再调整分数。

全零 raw CAM 在原始 normalization 函数中没有返回分支，结果为 `None`。兼容层保留真实 global score，报告 `attribution_status="unavailable"`、`ZERO_GRAD_CAM_NORMALIZATION_UNDEFINED`，并令逐位归因、Top residues 及依赖归因的 KDE 数值为空。非有限 CAM 同样明确标记不可用；不会填入伪造的 0 或 0.5。

## 从归因到 KDE 的精度转换

W 把单条序列复制两份以绕开原始 `.squeeze()` 的 batch=1 维度问题。S 对归一化归因采用 `float_format="%.4f"` 写 CSV；T2 将原始逐位 score 行转存到 `test_statics.csv`。T2 另写的排序展示行不进入 KDE；T5 只输出氨基酸类型汇总，不是第二次归一化或 KDE 输入转换。T5 的 `/2` 是双份输入补偿，不能照搬到真正单条序列的逐位分数。

因此当前 API 虽返回完整精度的归因，KDE 输入必须先执行原始 CSV 的四位小数转换：

```python
rounded_score = float("%.4f" % normalized_score)
```

该中间精度通过 `kde.input_precision="official_csv_4_decimal_places"` 记录。不能把完整精度归因直接送入 KDE，再声称与原始文件流水线一致。

## KDE、峰谷和主区域

K 第 322–333 行把每个残基的归因值作为一维样本。**KDE 拟合发生在 score 空间，并非以 residue position 为横轴做加权核平滑。**

1. 以 `GridSearchCV(KernelDensity(), {"bandwidth": np.logspace(-1,1,20)})` 搜索带宽，保留 Gaussian kernel 和当前固定 scikit-learn 版本的默认 5-fold CV。交叉验证在序列顺序对应的 score 样本上执行，没有添加 shuffle。
2. 在同一批 score 值上调用 `score_samples`；逐位 `density = exp(log_density)`。得到 N 个值后，才按残基序列顺序处理该数组。
3. 使用原始 `signal.savgol_filter(density,50,3)`，保持默认边界模式；随后 `process_density_array = max(smoothed_density) - smoothed_density`。这里没有额外 min–max 缩放。
4. `signal.find_peaks(process_density_array,prominence=0.1)` 寻峰，再加入端点 0 和 N−1。`LRECA_KDE_PROMINENCE` 只替换这个 prominence 参数，默认保持 0.1。
5. 对相邻两个峰之间的闭区间找最小值；并列最小值取第一次出现的位置。实际传入的 `valley_ylimit=max(process_density_array)` 使这些局部最小值都满足上界筛选条件。`valley_xlimit=20`、`topk=3` 只出现在被注释的替代策略中，在活动代码中没有额外过滤作用。
6. 加入两端谷点；依照原始循环，仅当中间谷点值严格低于左比较边界 **或** 右比较边界时保留相应分界。严格比较和遍历顺序均保持不变。
7. 相邻谷点产生半开区间 `[left:right)`。候选分数是这个区间中 `process_density_array` 的**累加和**。原变量虽名为 `avg_score`，并未取均值；另算的 `trapz` 面积不参与当前主区域选择。
8. 主区域选择最大累加和；完全同分时选择更长区间；分数和长度都相等时保留先遇到的区间。有效候选中只标记一个 primary。

API 的 `kde.values` 返回用于分段的 N 个 `process_density_array` 值，通过 `values_semantics="maximum_smoothed_score_density_minus_smoothed_score_density"` 标识。原始 K 第 352 行传给 `save_density` 的却是 `log_density_list`，其 CSV 行名 `density` 容易引起混淆；本项目没有把这个命名当作数值定义。KDE/critical region 的语义为 `derived_hotspot`，不能写成校准概率、实验验证的 LLPS 区域或 SEG/LCR 注释。

## 坐标、末残基遗漏与短序列

K 以 0 和 N−1 为最后边界，却对候选采用 `[left:right)` 切片，所以**最后一个残基 N 没有进入任何候选区域**。这是原始端点与半开切片的组合行为，不是 API 换算产生的问题。本阶段保留这个行为，并在每个成功 KDE 结果中输出 `UPSTREAM_TERMINAL_RESIDUE_OMITTED` 警告；没有私自把终点改成 N。

坐标转换为：

```text
original Python slice: sequence[left:right]
public start = left + 1
public end   = right
public length = right - left = end - start + 1
round trip: sequence[start-1:end]
```

K 第 249、288 行原始导出的 `[left,right-1]` 是 **0-based inclusive**。转为公开 1-based inclusive 后，右端恰好为 `right`，不能再次加 1。零长度候选如出现会被显式跳过并警告；若没有有效 primary，整个 KDE 标为不可用，不输出非法 region。

固定 50 点 Savitzky–Golay 窗口要求 N≥50；N<5 还无法完成默认五折 CV。对于 N<50，本项目保留可运行的 global/attribution，KDE 返回 `unavailable`、`KDE_REQUIRES_50_RESIDUES` 和空数值字段，不改变窗口长度，也不因此给全局预测人为加上 50 aa 下限。已实际验证 N=1、49 的分类和归因成功、KDE 不可用，N=50 的完整流程成功。

常量的有效归因值会给出接近平坦的 KDE。原始峰谷算法仍可能产生候选及一个 primary；本项目保留其计算，同时在曲线幅度不足时报告无明显内部峰的警告。不能把这种 primary 解释为发现了一个突出的生物学热点。

## 兼容层、模型和计算图生命周期

[upstream.py](../backend/lreca_runtime/upstream.py) 先校验完整源码 SHA256，再解析 AST，只编译允许列表中的顶层 class/function definitions。没有导入执行整个旧脚本的 `os.chdir`、命令行入口、输出写盘或子进程调用。模型构造器、ECA、编码、padding、CAM normalization 和 KDE 分段函数均按审核后的定义复用。

| 调整 | 目的与不变量 |
|---|---|
| 在 Human 模型 forward 保存 pre-ECA 的 `out_all`，并返回 `(logits,out_all)` | 匹配官方 saliency 的特征点；不改变权重、特征运算或 logits 路径 |
| 将全局池化后的 `.squeeze()` 改成 `.squeeze(-1)` | 保留 batch=1 维度；生产不必重复输入两次 |
| 把峰函数中唯一的 `prominence=0.1` 替换为受配置控制的变量 | 默认数学行为不变；变更节点数量必须精确匹配，否则拒绝执行 |
| 归因采用局部 `autograd.grad(...,retain_graph=False)` | 原始代码传入 True，但不需要第二次反传；不保留不必要的计算图 |
| CUDA 归因 forward 局部禁用 cuDNN | 官方 saliency seed 设置也禁用 cuDNN；避免 eval-mode cuDNN LSTM backward 的限制，结束后恢复上下文 |

全局预测在 `model.eval()` 与 `torch.inference_mode()` 中运行；归因单独开启梯度。原始方法本就不注册 forward/backward hook，本实现同样无 hook，不把 activation 或 gradient graph 保存在模型对象上。服务启动时加载一次 Human state dict，后续请求复用内存中的模型。上游文件本身保持未修改。

## 数值对照与 fixture 解释

实际运行环境：Python 3.10.19、PyTorch 2.1.1+cu118、NumPy 1.23.0、SciPy 1.10.1、scikit-learn 1.3.2；下表为 CPU、4 Torch threads 的解释参考。源序列、raw CAM、完整精度归因、KDE 输入、曲线、候选和对比值均在 [attribution_baseline.json](../backend/tests/fixtures/lreca/attribution_baseline.json) 中。

| 官方样本 | 长度 | 归因目标 | 与原始双份模型的归因最大绝对差 | 四位小数输入差异数 | 主区域 |
|---|---:|---:|---:|---:|---|
| Human positive line 1 | 248 | 1 / P | 1.1920929e-7 | 0 / 248 | 81–127 |
| Human negative line 120 | 529 | 0 / N | 3.2782555e-7 | 2 / 529 | 47–246 |

单条与双份 batch 的浮点运算产生很小的差异。在第二条样本中，两项归因跨过四位小数的舍入边界，使整条 KDE 曲线的最大差异达到 `9.3513077e-5`，但候选边界和 primary 完全相同。没有通过悄悄改归因分数、改变小数位数或在生产中重复计算来消除这个现象。

fixture 把两类比较分开：

- `reference`：未经改动的原始 saliency class/functions，显式装入 Human checkpoint/vocabulary，使用原始双份输入；完整保存其归因和后续 KDE。
- `same_input_kde_reference`：将生产单份 batch 得到的归因输入到未经改动的官方 KDE 定义，使比较输入完全相同。两条样本的 KDE 曲线和候选 region 分数/primary 都得到零差异。

归因的 regression tolerance 为绝对 `1e-5`，global 为 `1e-6`；同输入 KDE 为 `1e-10`。这些不同层次不能混用：测试不能对第二条样本的单份 batch 曲线强行要求与原始双份输入结果 bitwise 相同。

复现命令：[verify_lreca_explainability.py](../scripts/verify_lreca_explainability.py)，使用项目的 `.lreca-venv/Scripts/python.exe` 执行。另已真实运行一条 CUDA 248 aa 全流程，其 global score 与主区域和该 CPU 结果一致；广泛的性能/生命周期验证以主报告和 runtime 文档中的结果为准。

## Paper description 与 repository implementation 的核验边界

已读取的 [README 第 6、22 行](https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/README.md#L6) 将代码关联到论文题名，并描述 AA/AA segment 贡献计算；[Demo 结果说明](<https://github.com/ai-phasepro/LRECA/blob/0b4b48ab7870529a34028c6e30dfba42eddbf215/Demo/Explanation of the results.txt>) 将若干归因/KDE 输出与图 3、5、6 关联。这些是官方仓库提供的说明。

**本阶段没有逐段阅读并核对论文全文和补充材料，故不能宣称论文公式与仓库代码完全一致，也不能把上述端点行为认定为论文要求。** 本项目目前能确认的是固定 commit 的实际代码行为及复现结果。需要后续论文原文证据才能把 score-space KDE、50 点窗口、prominence、并列规则、末残基遗漏分别标记为“论文一致”或“论文与实现不同”。现在全部按已经验证的代码执行并透明记录。

## 解释性源码完整 SHA256

路径以 `external/lreca/` 为根；对应文件在上面的来源表中给出了可打开链接。

| 文件 | SHA256 |
|---|---|
| `Demo/code_for_model_testing/RCNN_ECA_saliency/get_score_forsingle.py` | `e71e6608014a04aace7d04ee2af16b8ac30e65a812926b92195207aa130498c4` |
| `Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/verify/RCNN_ECA_saliency_verify_gradCAM_fortest.py` | `8645491541fb1cb56382b5b43bb6f704ec42bd0fb41aa32899f39f9fd2993815` |
| `Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/statics/RCNN_ECA_statics2_fortest.py` | `6462f4fa988a15e7455ffb0505061fc5bfb4f3804b5ff6c5b97c6af58ddbf1e1` |
| `Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/statics/RCNN_ECA_statics5_fortest.py` | `be0e9547f66103ef85bf54b3370f12f92f6912720f1b75d06c5a895f2ccf4a07` |
| `Demo/code_for_model_testing/RCNN_ECA_saliency/LCRs_process/split_LCRs_segment_forsingle.py` | `cd51cb2386fc0fbbad5f514788218d0087d3abd39e4dd128050054e98146b090` |
| `Demo/Explanation of the results.txt` | `03be5c6b445d0867fc0b264177e774d9a50e409d13993a45af9d13df334b35c9` |

Human 模型、词表数据及 checkpoint 的完整哈希单列在 [身份文档](lreca_identity.md)。
