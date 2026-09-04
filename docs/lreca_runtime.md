# LRECA 运行环境、生命周期与性能

验证日期：2026-09-03。固定上游 commit 为 `0b4b48ab7870529a34028c6e30dfba42eddbf215`。
本机已完成原始 Human demo、CPU/CUDA 推理、解释、HTTP 接口；Production 补充后完整后端测试为 125 项通过。
原始入口与命令见 [baseline](lreca_baseline.md)，科学计算定义见 [explainability](lreca_explainability.md)。

## 环境选择与实际验证

采用需求中方案 **B：独立依赖环境**。FastAPI 仍在 `.venv`；持久科学 worker 在
`.lreca-venv`。Adapter contract 不变，HTTP 进程不导入 Torch。

| 项目 | 官方环境 | 本机实际环境 |
|---|---|---|
| Python | README 3.8；YAML 3.8.18 | API 3.12.13；科学 worker 3.10.19 |
| PyTorch | 2.1.1+cu118 | **2.1.1+cu118** |
| CUDA build | 11.8 | 11.8，CUDA 实测可用 |
| GPU | 无固定要求 | NVIDIA GeForce RTX 3060 Laptop GPU，6 GB；driver 596.08 |
| NumPy | 1.23.0 | 1.23.0 |
| SciPy | 1.10.1 | 1.10.1 |
| scikit-learn | 1.3.2 | 1.3.2 |
| pandas | 2.0.3 | 2.0.3 |
| matplotlib / seaborn | 3.7.4 / 0.13.0 | 3.7.4 / 0.13.0 |
| 线程 | 官方入口未固定；本次 baseline 配置 4 | 默认 Torch/OMP/MKL 4 |
| 平台 | 原 YAML 含 Linux 专属依赖 | Windows x64，独立 venv |

本机 Windows 首先尝试官方 Python 3.8.18：项目内 Conda prefix 使用 conda-forge，初次遇到 Conda
缓存目录权限限制，经批准重试；随后 `pip=24.3.1` 与 `pip<25` 均遇到
`PackagesNotFoundError`，没有成功建立官方 3.8 环境。这不表示 Python 3.8 在其他环境无法安装。

同时检查方案 A：官方索引没有 API Python 3.12 所需的 Torch 2.1.1+cu118 wheel。
没有将 Torch 升到 2.2 或更高版本。最终利用本机已有的 Python 3.10.19 创建项目专属 venv，
保持 Torch、NumPy、SciPy 和 sklearn 的官方数值版本；经原始 demo 和 regression 验证后采用。
未修改全局 Python/Conda 配置，没有切换上游 commit 或替换 Human checkpoint。

上述 Python 3.10 隔离环境是本机 Windows 安装条件下的兼容处理，不表示 Linux 也需要经历
同一 Conda 失败过程。Linux 可以直接准备自己的受支持环境；为延续当前基准，首轮迁移仍建议
保持科学 worker Python 3.10.19 与相同数值包版本，并在目标平台重新验证。

实际 Torch wheel 来自 [PyTorch 官方 CUDA 11.8 索引](https://download.pytorch.org/whl/cu118/torch/)。
[官方历史安装说明](https://docs.pytorch.org/get-started/previous-versions/)列出 2.1.1 的 CUDA 11.8 发行组合。
本机已执行 `pip check`，没有损坏依赖。`cloudpickle` 为审计辅助依赖，`psutil` 用于真实进程内存测量。

## Windows 开发兼容处理与 Linux 适用性

| 已用处理 | 本机原因与范围 | Linux 是否需要 |
|---|---|---|
| 独立 Python 3.10 环境 | 官方 3.8 Conda 尝试失败，API 3.12 无匹配 Torch wheel；保留 Torch/数值包版本 | 不需要重现 Windows 的安装失败；首轮迁移保留 3.10 与相同数值版本，并独立解析 Linux 依赖 |
| Git 单次 `http.sslBackend=openssl` | clone 的 Schannel 后端报 `SEC_E_NO_CREDENTIALS`；保持 TLS 校验，未改全局配置 | 不作为 Linux 必需项；Linux 使用其正常可用的 Git TLS/CA 配置 |
| API pip 单次 `legacy-certs`、禁用 keyring/缓存 | 本机默认凭据/证书初始化停滞后采用的安装诊断组合；worker 旧 pip 不支持 `legacy-certs`，使用其默认 CA bundle | 不作为 Linux 必需项；按目标 pip 与 CA 环境安装，不关闭 TLS 校验 |
| 显式下载 `win_amd64` wheel | API pip 为 Python 3.10 下载兼容的 Windows Torch wheel，再安装到科学 venv | 不可复制该 wheel 或 Windows venv；必须选择对应 Linux wheel |
| `CREATE_NO_WINDOW` 平台分支 | Windows 隐藏自建科学 worker 窗口；通信仍用标准 Python 管道 | Linux 分支不设置该标志，无专属 Windows Python 包依赖 |
| 精确目录 `safe.directory` 与只读 Git 参数 | 沙盒账户/目录所有权不同；每次仅信任配置解析出的具体源码 checkout，不改全局信任 | 容器 UID 与挂载目录不同也可能需要；当前包装层已保留只读调用方式，实际挂载待 Linux 验证 |

安装命令和当次失败原因见 [Module 1 命令记录](module1_commands.md) 与
[Module 0 命令记录](module0_commands.md)。这些处理不修改 `external/lreca`。
AST 提取避免上游脚本顶层文件操作、`.squeeze(-1)` 保留单样本 batch 维，以及 CUDA Grad-CAM
局部禁用 cuDNN 以支持 eval LSTM 的反向梯度，均属于跨平台兼容包装；Linux 仍保留这些处理，
不应把它们作为 Windows 特例删掉。具体函数与科学语义见 [解释性说明](lreca_explainability.md)。

## 重建依赖

两个 lock 文件分别管理 API 和科学 worker；不要把它们安装进同一个环境。
本机 `.venv` 和 `.lreca-venv` 已可直接使用。以下为重建命令示例，Python 解释器路径应指向相应版本：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
# 用 Python 3.12 建立 API 环境，再执行：
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e ./backend

# 先把 LRECA_BOOTSTRAP_PYTHON 设置为本机 Python 3.10.19 解释器的完整路径。
# 此变量只用于本重建示例，不是应用运行配置。
& $env:LRECA_BOOTSTRAP_PYTHON -m venv .lreca-venv
.\.lreca-venv\Scripts\python.exe -m pip install -r backend/requirements-lreca.lock.txt
.\.lreca-venv\Scripts\python.exe -m pip check
```

worker lock 来自本轮真实安装清单，`torch==2.1.1+cu118` 替代了 `pip freeze` 中机器特定的
本地 wheel 路径。它是 Windows / Python 3.10 已验证清单，不是完整解析过的 Linux lock。
Linux wheel 的平台依赖需要在目标平台另行解析、固定并验证，不能把 Windows freeze 直接
声明为 Linux 安装通过记录。
若 `.lreca-venv` 尚不存在，不要用 API Python 3.12 为它创建环境。

权重和原始仓库恢复方法见 [external/README.md](../external/README.md)；它们不进入本项目 Git。
本次下载的 wheel 只在被忽略的 `.tools/wheels/` 中缓存；没有把大体积环境或 checkpoint 写进交付清单。

## 配置与启动

配置示例为 [backend/.env.example](../backend/.env.example)。`.env` 从启动工作目录读取；
从项目根目录启动时将示例复制为根目录 `.env`，或直接设置进程环境变量。
路径默认按项目根目录解析，不依赖启动目录。

| 配置 | 默认值 | 含义 |
|---|---|---|
| `LRECA_DEVICE` | `auto` | auto 使用可用 CUDA，否则 CPU；也可显式 cpu/cuda |
| `LRECA_CLASSIFICATION_THRESHOLD` | `0.5` | `raw_score > threshold` 为 P，否则 N |
| `LRECA_TOP_RESIDUES` | `10` | 原始归因分数降序，平局按位置升序 |
| `LRECA_KDE_PROMINENCE` | `0.1` | 官方峰谷分段的 prominence |
| `LRECA_TORCH_THREADS` | `4` | Torch、OMP、MKL 计算线程 |
| `LRECA_WORKER_TIMEOUT_SECONDS` | `120` | 一次科学计算 RPC 的等待上限 |
| `LRECA_STARTUP_TIMEOUT_SECONDS` | `120` | worker 初始化及模型加载等待上限 |
| `LRECA_PYTHON` | Windows 为 `.lreca-venv/Scripts/python.exe`；Linux 为 `.lreca-venv/bin/python` | 科学环境解释器 |
| `LRECA_REPOSITORY` | 项目 `external/lreca` | 必须为固定且未修改的完整上游 Git checkout，含 `.git` |
| `LRECA_CHECKPOINT_PATH` | `external/lreca/Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt` | 首选权重路径配置；SHA256/size 必须与审计一致 |
| `LRECA_CHECKPOINT` | 未设置 | 旧别名；与首选名同时设置时以 `LRECA_CHECKPOINT_PATH` 为准 |

显式指定 `cuda` 但设备不可用时会报告不可用；`auto` 在 CUDA 不可用时选择 CPU。
设备由 Torch 选择，没有写死 GPU 编号；响应中的 `cuda:0` 是本机实际解析结果。

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

从 [本地 API 文档](http://127.0.0.1:8000/docs) 可调用接口。内部模型启动日志包含 checkpoint
文件名、配置/解析后路径、完整 SHA256、字节数、commit 和 device，便于服务端定位问题。
公开导出的证据日志将本机目录替换为环境引用，原始字节保存在被忽略的私有审计归档中；
本次导出日志见 [server_stdout.log](audit/lreca_api_smoke/server_stdout.log)。停止前台服务用 Ctrl+C。

HTTP 成功结果与健康检查中的 `metadata` 使用独立、严格的公开 DTO，只允许下列 **7 项**：
`repository`、`commit`、`model_variant`、`dataset5_mapping_status`、`checkpoint`、
`checkpoint_sha256`、`checkpoint_size_bytes`。其中 checkpoint 仅为文件名；`device` 是结果/健康
响应的顶层字段。配置路径、解析后路径、源码路径映射和内部 runtime 对象不属于公开 metadata。
内部异常、完整 traceback 和诊断可以记录私有路径；HTTP 错误与健康消息使用安全描述，
不直接转发这些内部内容。模型来源仍为 Human-specific，dataset5 映射仍为 `unconfirmed`。

## 生命周期和故障语义

每个 FastAPI 应用进程在 lifespan startup 调用一次 `LRECAAdapter.load()`；模型持续保留于
一个常驻 worker 子进程，Windows 启动时隐藏窗口。重复 `load()` 在就绪时直接返回，
每次请求不会重新初始化模型。多 Uvicorn workers 各有自己的模型实例。
全局预测用 `eval()` 与 `inference_mode()`；归因仅局部开启梯度，无 hook、无参数梯度累积、
不保留输出图。健康检查只检查已加载标志和存活的 worker，不进行预测或 Grad-CAM。

Adapter 使用异步锁，worker pipe 使用请求 ID 和串行锁。科学计算不会阻塞 ASGI 主事件循环，
不同请求不会交叉读取回复。取消请求仍等到有界 RPC 完成再释放 worker 所有权；取消启动或
启动失败会关闭子进程。超时、进程退出、无效协议会关闭/标记不可用，不在下一次预测中偷偷重载。
应用关闭通过 shutdown 消息结束 worker；必要时只终止自己创建的子进程。

非法输入返回 422，模型不可用 503，超时 504，真实计算失败 500。小于 50 aa 时，
可用的全局预测与归因正常返回；KDE 为 `unavailable`，数值/regions 为 null 并解释原因。
`include_attribution=false` 完全跳过归因及 KDE，相关字段为 null；未做 calibration。

## Linux 与未来容器部署边界

本轮已经完成静态可移植性审阅，尚未实际运行 Linux。当前机器没有 Docker/Podman 命令，
WSL 可执行文件存在，但只读枚举显示没有已安装的发行版。本轮未安装或启动这些环境，
未构建容器，也未把 Windows 的 CPU/GPU 通过结果计作 Linux 通过。

科学核心使用 Torch、NumPy、SciPy、scikit-learn 与 psutil，AST loader 不运行上游脚本的
顶层文件操作。进程通信使用标准 Python 管道，Windows 窗口标志有平台分支，路径由项目根或
显式配置解析。当前代码具备继续容器化的结构条件；未来即使拆成独立推理 service，改变的也是
进程部署和 transport，模型加载、归因与 KDE 核心可以继续复用。

首个 Linux 验证目标建议为 **x86_64、glibc** 环境，保持 CPython 3.10.19、
`torch==2.1.1+cu118`、`numpy==1.23.0`、`scipy==1.10.1`、`scikit-learn==1.3.2`、
`pandas==2.0.3` 与 `psutil==5.9.6`。官方索引提供对应 CPython 3.10/Linux x86_64 的
Torch 2.1.1+cu118 wheel；本结论不扩展到 ARM64、Alpine/musl 或其他架构。
[PyTorch 历史版本](https://docs.pytorch.org/get-started/previous-versions/)、
[官方 CUDA 11.8 wheel 索引](https://download.pytorch.org/whl/cu118/torch/)。

Linux 应以目标 wheel 元数据解析完整传递依赖并另行锁定来源、版本和哈希。PyTorch 2.1.1
构建源码允许添加发布 wheel 依赖，并含 Linux/Triton 分支；是否引入 CUDA runtime/Triton
以及精确依赖版本，以目标 wheel 为准，不能从 Windows 清单推断已全部固定。
[PyTorch v2.1.1 构建源码](https://github.com/pytorch/pytorch/blob/v2.1.1/setup.py)。
CPU 环境可继续使用当前构建并显式选择 `cpu`；若改为官方 2.1.1 CPU wheel，应形成独立清单并
重新比较真实基准。无需为了迁移升级科学算法依赖。

容器除 Python 环境外需要可执行的 Git、证书信任链，以及所选 CPython/科学 wheel 所需的
glibc、C/C++、OpenMP 共享运行库。上游 [requirements.yml](../external/lreca/requirements.yml)
包含 `ld_impl_linux-64`、`libgcc-ng`、`libgomp`、`libstdcxx-ng`，说明原方案包含 Linux 环境。
这些 Conda build pins 不能原样套作任意发行版的系统包版本；在 Debian/Ubuntu 类镜像中应核对
`libstdc++6`、`libgomp1` 等运行库是否满足，目标镜像的动态链接仍待实测。核心推理无需 GUI。

GPU 容器还需要宿主机 NVIDIA driver、受支持的容器引擎及配置 GPU 访问的 NVIDIA Container
Toolkit。宿主机不必另装完整 CUDA Toolkit；驱动必须与实际 GPU 和 CUDA 11.8 兼容，容器内的
用户态 CUDA 依赖由选定镜像/wheel 环境提供。[NVIDIA Container Toolkit 安装说明](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)、
[NVIDIA 官方说明](https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/README.md)。
CUDA 11.x 的历史 minor-version compatibility 下限不能代替目标 GPU 的完整验收；应采用仍受
维护的兼容驱动。[NVIDIA CUDA 兼容性说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)。
CPU 部署不需要 GPU driver 或 Container Toolkit。

源码与模型应按以下边界提供给未来容器：

- 保留完整、tracked clean 的固定 Git checkout，包含 `.git`，HEAD 为
  `0b4b48ab7870529a34028c6e30dfba42eddbf215`。当前运行时确实检查 Git、源码/数据哈希及
  checkpoint 哈希，单独源码 ZIP 或只有权重不足以启动。
- 仓库与 checkpoint 可以只读挂载，并通过 `LRECA_REPOSITORY`、`LRECA_CHECKPOINT_PATH`
  指定容器内位置；Git 使用只读检查参数。只读挂载的实际 Linux 行为仍待验证。
- 原始文件必须保留字节和文件名大小写。已确认 6 个固定源码/数据文件与 Git blob 字节一致；
  两份 `pos_word_list_human.txt` / `neg_word_list_human.txt` 在 Git 中原本各含 980 个 CRLF。
  不得对这两个数据文件执行 `dos2unix` 或统一 LF，否则会破坏固定哈希。
- 当前 [.dockerignore](../.dockerignore) 已排除 `external/lreca`、本地环境、模型、权重、私有
  审计和 `.env` 等构建上下文内容。未来必须通过单独的固定来源准备或挂载提供原始仓库和权重，
  不能假设它们会随普通代码构建上下文自动进入镜像。本轮没有 Dockerfile 或镜像构建产物。
- 保留类似 `backend` 与 `external/lreca` 的项目布局，或为源码/模型/解释器显式配置路径；
  不要把 Windows 虚拟环境复制到 Linux，也不要仅安装 Python 包后假设外部源码自动存在。

未来 Linux 验收应复用现有真实 Human demo、正负解释 fixture、HTTP smoke、短序列/零 CAM
分支以及 worker 回收测试；GPU 目标还需设备可见性和内存验证。当前诊断中的 RSS 可继续使用，
但 Windows `peak_wset` 在 Linux 不存在时 `peak_rss_bytes` 为 null，不能当作 Linux 峰值内存。
跨平台浮点差异尤其可能跨过 KDE 四位小数边界，应使用 full-precision reference 与
same-input KDE 两层比较定位，保留固定平滑和官方区间语义，不能通过改算法掩盖差异。

## 长度与实际性能

模型使用官方编码、padding、PackedSequence 和真实长度，未发现算法给出的固定最大长度，
API 未增加无依据的最大值。实际完整验证 **50、100、500、1000、2000 aa**；
另外验证 1/49 aa 全局与归因成功、KDE 明确不可用，以及 4486 aa 官方负样本的全局回归。
这只是已测范围，不代表所有更长序列都具有相同资源占用或运行时间。

以下为 `ACDEFGHIKLMNPQRSTVWY` 重复到指定长度的**合成输入**性能测试，不是生物学 benchmark。
每个 device/length/mode 先预热 1 次，再测 3 次；表格为 Adapter 端到端 wall time 平均值，
包含序列化与结果契约验证，不含首次加载。全局/完整模式都使用同一持久模型。

| 长度 aa | CPU global ms | CPU global+CAM+KDE ms | CUDA global ms | CUDA global+CAM+KDE ms |
|---:|---:|---:|---:|---:|
| 50 | 5.313 | 89.593 | 5.727 | 81.656 |
| 100 | 15.468 | 112.136 | 5.369 | 96.766 |
| 500 | 37.764 | 410.552 | 17.475 | 363.562 |
| 1000 | 86.853 | 1085.733 | 32.103 | 1038.957 |
| 2000 | 150.881 | 3650.193 | 64.025 | 3676.974 |

2000 aa 的 KDE 在两个 device 下均约 **3100 ms**；它在 CPU 上运行。因此 CUDA 明显改善
global 模式，对完整流程的收益有限。没有 OOM 或超时。保留原始 GridSearchCV 行为，未为提速改变算法。

科学 worker **进程生命周期峰值** RSS：CPU **527.332 MiB**，CUDA **779.648 MiB**；
CUDA peak allocated **124.979 MiB**。这些是整个 worker 启动后的累计峰值，不能当成各次请求
增量内存；不包括父 API 进程。CPU 的 CUDA 内存字段为 null。每个长度的前后 RSS、峰值、阶段
耗时和三个原始样本均保存在 [lreca_performance.json](audit/lreca_performance.json)。

## 100 次归因与内存验证

使用固定的 248 aa Human 正例，每种设备各先预热 20 次，然后连续归因 100 次，
不保留每次完整结果；每 20 次记录诊断。随后全局预测也预热 20 次并调用 100 次。

| 观察项 | CPU | CUDA |
|---|---:|---:|
| 模型加载次数 | 1 | 1 |
| forward / backward hooks（始终） | 0 / 0 | 0 / 0 |
| 100 次归因 RSS 净变化 bytes | +643072 | -274432 |
| 归因 CUDA allocated 净变化 bytes | 不适用 | 0 |
| 100 次 global RSS 净变化 bytes | 0 | +4096 |

未观察到明显 hook 或内存累积；这是预热后有限次调用的证据，不是对所有长时间运行的形式证明。
通过门槛为归因 RSS 增长 <64 MiB、CUDA allocated 增长 <16 MiB、global RSS 增长 <32 MiB，
并要求 hook 数不变与 `load_count=1`。详细采样和实际值均保留，不用阈值替代实际报告。

首次性能统计脚本错误地对 CPU 的 null CUDA 内存做减法，导致脚本失败；模型测试没有失败。
修正统计层后完整重跑成功，原失败记录保留为 `lreca_performance_failed_harness.json` 和对应日志。

## 复现验证

```powershell
.\.lreca-venv\Scripts\python.exe scripts/run_lreca_baseline.py
.\.lreca-venv\Scripts\python.exe scripts/verify_lreca_explainability.py
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe scripts/benchmark_lreca.py
.\.venv\Scripts\python.exe scripts/smoke_module1.py
```

最后一个脚本启动真实 Uvicorn，在本机空闲 TCP 端口发送 HTTP 请求并保存响应，结束时关闭服务。
本次 `POST /api/v1/methods/lreca/analyze` 返回 200，实际 device 为 `cuda:0`；
global-only 返回 200，含 X 的无效序列返回 422。证据见 [HTTP summary](audit/lreca_api_smoke/summary.json)。
