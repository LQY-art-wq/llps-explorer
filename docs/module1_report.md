# Module 1：LRECA Human-Specific Real Inference & Explainability

**Module 1 completed.** 验证日期：2026-09-03（Asia/Shanghai）。
已完成真实 Human 推理、Grad-CAM、KDE、持久 Adapter、HTTP 接口与回归验证。
Production 补充已完成；最终完整后端测试 **125 passed / 0 skipped**，真实 Uvicorn HTTP POST 返回 **200**。
Linux/Docker 已完成代码与配置准备，尚未在目标平台运行或构建镜像。
本模块在此停止，未进入 Module 2。

## 1. Human checkpoint 身份证据

固定 README 第 18–24 行明确 Human 数据及其训练/demo 入口。
`Demo/code_for_model_testing/RCNN_ECA_3_human_test.py` 第 24–34 行把 Human 正负数据与
`human_1_RCNN_ECA_parallel_089-0.9802.pt` 直接关联，第 128–139 行按匹配维度严格加载。
本次使用该原始入口成功跑完 **120 positive + 120 negative**，然后才封装生产实现。
身份依据来自明确代码映射、数据和真实加载；不只依据文件名。

原始 CPU demo 用时 **12.2354938 s**，239/240 分类正确，TP=120、TN=119、FP=1、FN=0。
这些数字仅描述官方 demo 子集，未把它们当作论文完整 benchmark 或独立生物学验证。
完整输入、命令、日志与结果见 [lreca_baseline.md](lreca_baseline.md)。
逐条身份依据和 source hashes 见 [lreca_identity.md](lreca_identity.md)。

## 2. dataset5_mapping_status

`model_variant = "human_specific"`，`dataset5_mapping_status = "unconfirmed"`。
固定源码/README 的 Human 映射明确，但没有可独立核对的 dataset5 编号定义。
没有把 README 的第五个列表项目当成 dataset5 的证明。
已改正 Module 0 的候选命名；当前配置、manifest、metadata、API 与 fixtures 均保持该边界。

## 3. LRECA repository 与 commit

- Repository：[ai-phasepro/LRECA](https://github.com/ai-phasepro/LRECA)。
- Commit：`0b4b48ab7870529a34028c6e30dfba42eddbf215`。
- 本地：`external/lreca`，固定上游独立 checkout。
- 未 pull、未切换 branch、未覆盖上游 source。所有兼容处理都位于本项目 `backend/lreca_runtime/`。

## 4. checkpoint SHA256 与启动记录

文件：`human_1_RCNN_ECA_parallel_089-0.9802.pt`，大小 **2,395,318 bytes**。

```text
aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc
```

`get_lreca_model_metadata()` 校验固定 commit、未修改的 tracked source、checkpoint size/hash
以及六个运行源码/词表文件的完整 hash。不同 checkpoint 不会被静默接受。
配置/解析后路径只进入内部 metadata 和服务端启动日志。API 的独立公开 metadata 仅含
repository、commit、model_variant、dataset5_mapping_status、checkpoint filename、SHA256、size。
成功响应、健康检查和错误响应均不公开服务器内部路径；保留完整身份信息用于追溯模型版本。
本机实际文件在项目 `external/lreca/Demo/trained_model/` 下。

## 5. Runtime environment

API Python **3.12.13**；独立科学 worker Python **3.10.19**。
科学栈保持官方关键版本：PyTorch **2.1.1+cu118**、NumPy **1.23.0**、SciPy **1.10.1**、
scikit-learn **1.3.2**、pandas **2.0.3**。

先尝试官方 Python 3.8.18 环境，Conda 求解未完成；API 3.12 没有匹配的 Torch 2.1.1 wheel。
因此采用需求方案 B，保持 Torch 版本并独立环境，而没有整体升级科学依赖。
两套环境 lock、安装失败与成功记录见 [lreca_runtime.md](lreca_runtime.md)。

CPU 与本机 RTX 3060 Laptop GPU 均实测通过。默认 `auto` 选择可用 CUDA，否则 CPU；
本次 API 实际返回 `cuda:0`，程序没有写死设备编号。

## 6. Global prediction semantics

Human 模型返回两个 logits；`raw_score = softmax(logits)[1]`。
API 返回真实 logits 和未校准正类分数；`calibrated_score == raw_score`，
`calibration_status = "not_calibrated"`。没有概率校准、加权 ensemble 或其他模型替代。

实际 HTTP 样例为官方 Human positive line 1，248 aa：

```json
{
  "method": "lreca",
  "status": "success",
  "model_variant": "human_specific",
  "dataset5_mapping_status": "unconfirmed",
  "raw_score": 0.9999921321868896,
  "calibrated_score": 0.9999921321868896,
  "calibration_status": "not_calibrated",
  "threshold": 0.5,
  "label": "P",
  "device": "cuda:0",
  "sequence_length": 248
}
```

以上为便于阅读的字段摘录；完整真实响应含 metadata、逐残基数组、KDE 数值和阶段耗时，
见 [response.json](audit/lreca_api_smoke/response.json)。

## 7. Positive class mapping 与预处理

Human demo 第 169–173 行把 negative 标为 **0**，positive 标为 **1**；第 192–193 行
将 argmax 用于类别，将 softmax 的第 1 类用于正类分数。模型及训练标签也与此一致。

直接复用 Human demo 的 `read_sequences`、`build_vocabulary`、`encode_sequences`，
以及 personal 模型的 `collate_fn`、padding、PackedSequence 与真实长度处理。
两个 Human 训练文本各 980 条，legacy shuffle seeds=0/1，正→负、首次出现顺序得到：

```text
m1 v2 k3 e4 t5 y6 d7 l8 g9 p10 n11 a12 q13 r14 h15 f16 i17 s18 c19 w20
padding0
```

逐字符索引已与官方函数实测一致。没有使用当前 1024-dimension / seeds20/21 训练入口替代
该 checkpoint 需要的 512-dimension / seeds0/1 demo 预处理。
API 接受 raw/单条 FASTA，去空白、ASCII 大写，拒绝非标准残基并返回 1-based 错误位置。

## 8. Threshold

`LRECA_CLASSIFICATION_THRESHOLD=0.5`；**score > threshold 为 P，否则 N**。
该 tie 规则对应默认二分类 argmax 的 class 0 优先。阈值可配置，前端没有硬编码它。
实测 threshold=1.0 生效；这只改变 classification label，不改变 Grad-CAM 的真实 argmax 目标。

## 9. Grad-CAM implementation

复用固定官方 saliency 的 `create_cam` 与 `rescale_score_by_abs`。对 embedding+BiLSTM
拼接后 ReLU、ECA 之前的 712 维特征求目标 logit 梯度，目标为原始 **argmax 类别**，
可为 0/N 或 1/P。对梯度沿真实序列长度平均，再与特征逐通道累加；原始 CAM 不另加最终 ReLU。

归一化等价于 `0.5 + raw_cam / (2 * max(abs(raw_cam)))`，保留官方正负含义，
不是另行发明的 min-max。全零 raw CAM 的官方归一化未定义时，归因显式不可用，不伪造零数组。
每个 score 与输入位置/AA 对齐；Top residues 仅排序相同分数，默认 10，平局按位置升序。

通过 hash-checked AST 只复用审核过的函数/类，避开原脚本的 cwd/文件操作副作用。
兼容调整为返回 pre-ECA 特征、`.squeeze(-1)` 保留 batch 维、局部梯度/设备管理，权重未变。
解释时使用同一个已加载 Human 模型，未混入默认 `mydata` saliency checkpoint。

两条正/负解释参考的归因最大绝对差为 **3.28e-7**，低于固定容差 `1e-5`。
默认归因不使用 forward/backward hooks。两种设备各预热 20 次后连续调用 100 次，
hook 始终 0/0、加载次数始终 1，CUDA allocated 净增长 0。

## 10. KDE implementation

保留真实代码流程：归因先按官方 CSV 精度保留四位小数；对 **score values** 拟合 Gaussian KDE，
GridSearchCV 默认五折在 `logspace(-1,1,20)` 选择 bandwidth；在相同 score values 求密度，
Savitzky–Golay window=50/polyorder=3 平滑，`max(smoothed)-smoothed` 得到 processed density。
再按 prominence=0.1 寻峰、谷间分段、累计 processed density，取最大段；并列先取较长段，
仍并列保持较早候选。实际分段函数直接来自官方源码。

`kde.values` 明确表示 processed density，不是原始 score、实验 propensity 或位置加权 KDE。
同输入下，两条参考序列的曲线、候选区间及 primary 与未经修改的官方函数完全一致。

原始端点为 N-1，使用 `[left:right]` 会遗漏最后一个残基。保留该行为并在响应 warning 中说明；
公开区间转换为 `[left+1,right]`，保证 **1-based、inclusive、length=end-start+1**。
248 aa HTTP 样例的唯一主区域为 **81–127，47 aa**，累计分数 **36.15997596307393**。
KDE N<50 显式不可用；模型本身仍支持已测试的 1 aa 输入。

## 11. Paper vs repository differences

README 关联论文题名，但本次没有取得可逐段核对的论文全文/补充材料；题名检索也没有定位到
可独立确认的对应全文。因此 **paper-code 一致性未确认**，不冒称已证明全部公式一致。
已明确核实并保留的代码行为包括 score-space KDE、四位小数输入、50 点窗口、argmax 归因、
绝对最大值归一化和末残基遗漏。上述实现细节不是自行推测的“论文修正”。

单条与官方双份 batch 的浮点差在负例中让 2/529 项跨过四位小数舍入边界，KDE 曲线最大差
约 9.35e-5，而边界不变。fixture 保留双份原参考，同时单独做**完全相同输入**的 KDE 回归；
没有扩大容差掩盖算法差异。详细证据见 [解释文档](lreca_explainability.md)。

## 12. Performance results

每组 1 次预热 + 3 次测量；输入为指定长度的合成标准 AA 序列；下表单位 ms。

| aa | CPU global | CPU full | CUDA global | CUDA full |
|---:|---:|---:|---:|---:|
| 50 | 5.313 | 89.593 | 5.727 | 81.656 |
| 100 | 15.468 | 112.136 | 5.369 | 96.766 |
| 500 | 37.764 | 410.552 | 17.475 | 363.562 |
| 1000 | 86.853 | 1085.733 | 32.103 | 1038.957 |
| 2000 | 150.881 | 3650.193 | 64.025 | 3676.974 |

full = global + Grad-CAM + KDE。2000 aa 的 KDE 约 3100 ms，是主要耗时；CPU/GPU 均无 OOM。
科学 worker 生命周期峰值 RSS：CPU 527.332 MiB、CUDA 779.648 MiB；CUDA peak allocated
124.979 MiB。这些不是单请求增量峰值。100 次归因后 RSS 净变化为 CPU +643072 bytes、
CUDA -274432 bytes；100 次 global 为 CPU 0、CUDA +4096 bytes，未观察到明显持续增长。
方法、阈值、每轮采样与内存限制见 [运行环境与性能](lreca_runtime.md)。

## 13. Tests 与实际启动

最终 `pytest backend/tests`：**125 passed、0 skipped、2 既有依赖弃用 warnings，40.04 s**。
保留全部原始科学回归，并新增公开 metadata/错误/设备字段的路径隔离、环境配置与可移植性检查。
按文件计数：API 56、真实科学集成 20、可移植性 7、真实进程/IPC 24、Module 0 契约 18，共 125 项。
fixtures 包含固定完整序列、原始 global baseline、正/负 CAM 和 KDE；未保存无必要二进制数据。

| 验证领域 | 覆盖 |
|---|---|
| 身份 | 固定 filename、SHA256、commit、官方 AA vocabulary、错误 checkpoint 拒绝 |
| 预测 | 官方两条基线、重复确定性、合法分数、未校准、正负类别 |
| 归因 | N 个位置/AA、官方归一化参考、真实负类目标、Top 排序原值 |
| KDE | N 个密度值、1-based inclusive、主区域唯一、prominence 配置 |
| 输入 | 空序列、X/B 等非法残基、空白、大小写、FASTA、多 FASTA、Unicode |
| 设备/长度 | CPU/CUDA；50/100/500/1000/2000 完整计算；1/49 KDE 限制 |
| 生命周期 | 加载一次；两设备 100 次归因，内存/hook；连续 global 不明显增长 |
| 故障/并发 | 超时终止、晚回复隔离、崩溃不可用、取消加载/请求、失败启动清理 |
| HTTP | 真实 TCP 的 health=200、full=200、global-only=200、非法残基=422 |
| 路径与配置 | 首选/旧环境变量优先级；不依赖 cwd/home；无 Windows drive 硬编码 |
| 生产边界 | 公开 metadata 白名单、路径型 device 拒绝、错误消息隔离、权重 Git 忽略和 Docker context 排除 |

最终完整日志：[tests](audit/module1_production_final_tests.log)、[JUnit](audit/module1_production_final_tests.junit.xml)。
新增 Git 忽略规则测试最初因 Windows 文本输入的 CRLF 转换失败；改为 Git `-z` 的 NUL 分隔后，
7 项相关测试重测通过，随后完整 125 项全部通过。未改变模型或科学期望值；首次失败、局部重测与
最终成功均保留在 [验证链记录](audit/module1_test_verification_summary.json)。
此前 90 项原始模块回归和 CPU/GPU benchmark 仍作为历史证据保留，没有重做 baseline 或性能测量。
实际服务日志与完整请求/响应：[HTTP audit](audit/lreca_api_smoke/summary.json)。
本次补充后的真实 TCP 响应在路径导出处理之前完成无泄露断言；health/full/global 的 metadata
均且仅含 7 项公开字段。私有日志保留原字节，公开审计日志明确标为路径脱敏导出。
服务和本次创建的模型 worker 已正常关闭；不是只验证 import 或模拟返回值。

## Production Deployment Readiness

| 要求 | 当前状态与证据边界 |
|---|---|
| Linux portability status | 应用与科学 runtime 的文件路径由环境配置及 `pathlib.Path` 解析；不依赖开发用户目录或 Windows shell。静态检查通过，Linux 尚未实测。 |
| Docker readiness | 已提供 `.dockerignore`、两套依赖记录和容器运行前提。当前未建立 Dockerfile、构建镜像或部署服务器；本机无 Docker/Podman 或可用 WSL 发行版。 |
| Checkpoint configuration | 首选 `LRECA_CHECKPOINT_PATH`，旧名 `LRECA_CHECKPOINT` 兼容且优先级已测。例：`/models/lreca/human_1_RCNN_ECA_parallel_089-0.9802.pt`。`LRECA_REPOSITORY` 与 `LRECA_PYTHON` 分别配置固定源码 checkout 和 worker 解释器。 |
| Model loading lifecycle | 每个 FastAPI 进程 startup 调用 Adapter load，常驻科学 worker 仅加载一次并复用 RAM/VRAM；HTTP 请求不执行重复 `torch.load`。多个 API worker 各有自己的实例。shutdown 回收其所属 worker。 |
| CPU support | 当前 Windows CPU 的真实预测、归因、KDE、长度及生命周期测试通过；`LRECA_DEVICE=cpu` 不要求 GPU，`auto` 在 CUDA 不可用时回退 CPU。 |
| GPU support | 当前 RTX 3060 Laptop / CUDA 11.8 已实测；`LRECA_DEVICE=cuda` 选择可用 CUDA，未硬编码设备编号。未来 Linux GPU 容器需要兼容宿主驱动与 NVIDIA Container Toolkit，仍需目标机器验证。 |
| Windows-specific dependency | 核心 inference 无 Windows 专属包；隐藏子进程窗口的标志仅在 Windows 分支启用。Python 3.10 隔离环境和本机安装/证书兼容处理及 Linux 适用性已记录。Windows lock 不冒充完整 Linux lock。 |
| Future independent LRECA service | HTTP/公开 DTO、Adapter/IPC、科学 engine、固定模型兼容层已分离。独立服务可复用 engine 的 load/predict/attribution/KDE；只需替换通信与部署边界。 |

**核心 inference 不需要重写，只需要容器化和改变部署边界。** 独立服务的传输包装、镜像和
目标平台依赖解析/验证留给 Deployment Module；当前未把这些未执行事项计为验收通过。

本项目 Git 索引中模型权重为 **0**。`.gitignore` 同时忽略上游 checkout、模型目录及
`.pt/.pth/.ckpt/.safetensors/.onnx/.h5/.hdf5/.pkl/.pickle/.bin`，包括放入其他目录的权重。
Git 中保留模型文件名、SHA256、manifest 和获取说明；官方仓库自身原有的权重记录不作修改。
上游 commit 与 tracked source 保持原样，所有兼容处理均在本项目 wrapper/service 中。

未来容器必须提供完整且 clean 的 pinned checkout（含 `.git`），并保留来源文件字节；
两份 Human 词表原有 CRLF，不能在迁移时统一改为 LF。源码和权重可以分别通过只读挂载配置。
依赖版本、系统库、CUDA 要求、平台差异及尚待进行的 Linux 验证见 [lreca_runtime.md](lreca_runtime.md)。
历史审计的开发机器路径已变量化，原始日志/文档私有归档于被忽略的 `.audit/module1_private_evidence/`；
科学数值未修改。此次补充没有改变 Human 身份、正类映射、Grad-CAM、KDE 或 1-based 坐标定义。

## 14. Changed files

本模块共变更 **78 个文件：新增 63、修改 15、删除 0**；其余 36 个 Module 0 文件未改动。
完整逐文件清单见 [module1_changed_files.txt](module1_changed_files.txt)，实际命令见
[module1_commands.md](module1_commands.md)。核心交付为：

- `backend/app/adapters/lreca.py`、科学 worker/core/metadata/兼容层与 IPC service。
- API、sequence validation、严格结果契约、配置和 startup/shutdown 生命周期。
- 官方 baseline/解释 fixtures、科学集成/API/进程测试、性能与真实 HTTP 验证脚本。
- 运行环境 lock、checkpoint manifest 状态、科学说明与完整审计报告。
- 生产环境配置、Git/Docker context 权重排除、公开响应隐私契约及部署前提记录。

清单以本轮开始前的 Module 0 快照为基准。普通 Git diff 因当前仓库尚无首个 commit，
同时包含已 intent-to-add 的原始骨架；专属清单排除未改动文件、上游、环境与缓存。
前端、FuzDrop、SEG、DisMeta 和 orchestrator 未增加实现。

## 15. Unresolved issues 与停止边界

- dataset5 编号及论文全文逐项对照仍未确认，响应已明确使用 Human 身份。
- 官方 Python 3.8.18 本机未构建成功；本次真实验证环境为 3.10.19，不宣称原 3.8 环境复刻。
- KDE 原始末端遗漏和 N≥50 要求保留，结果有明确 warning/unavailable 语义。
- batch/device 浮点与四位舍入可能造成细小 KDE 差异；已分层记录参考与容差。
- 长序列完整计算主要受 CPU KDE 影响；没有添加无来源的最大长度，超过已测范围需另行验证。
- 未开展概率校准或独立生物学验证，当前指标仅用于实现一致性与工程验证。
- Linux 运行、容器镜像、Linux 传递依赖锁定及目标 GPU 的实际验收尚未进行，属于后续 Deployment Module。

以上边界不影响本模块的真实推理与交付完成。没有进入 FuzDrop、SEG、DisMeta、ensemble、
复杂图表或前端 Feature Viewer 的实现。Module 1 到此停止。
