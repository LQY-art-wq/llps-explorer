# Module 1 命令与执行记录

执行日期：2026-09-03（Asia/Shanghai）。工作目录：
`${PROJECT_ROOT}`。
命令中的 `.venv` 是 API Python 3.12.13，`.lreca-venv` 是科学 Python 3.10.19。
开发机器路径已变量化；`LRECA_BOOTSTRAP_PYTHON` 代表当次使用的 3.10.19 解释器，重建前由环境提供。未脱敏历史记录在 `.audit/module1_private_evidence/` 私有归档。
除单独注明的安装失败外，下方验证命令均已实际执行；测试数据不是模拟模型输出。

## 通用编码与只读审计

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
git -C external/lreca rev-parse HEAD
git -C external/lreca status --porcelain
Get-FileHash -Algorithm SHA256 -LiteralPath 'external/lreca/Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt'
```

已读取固定 README、Human demo、两个 Human 词表文件、训练代码、模型构造、saliency、
single-sequence wrapper、statics 和 KDE 定义；对固定源码进行 `dataset5` 映射检索。
没有执行 `git pull` 或切换上游分支。metadata helper 另对运行时使用的六个源码/数据文件核对 SHA256。

Windows 目录所有者不同的只读 Git 调用使用精确目录的 `-c safe.directory=...`，并配合
`--no-optional-locks -c core.fsmonitor=false`；该选项只作用于单次调用，没有修改全局信任配置。

## 官方环境尝试与隔离环境

最先尝试官方 Python 3.8.18，项目内配置缓存和环境路径：

```powershell
$env:CONDA_PKGS_DIRS = Join-Path (Get-Location) '.tools/conda-pkgs'
$env:CONDA_ENVS_PATH = Join-Path (Get-Location) '.tools/conda-envs'
conda create --prefix .lreca-env --override-channels -c conda-forge --no-default-packages --yes python=3.8.18 pip=24.3.1
conda create --prefix .lreca-env --override-channels -c conda-forge --no-default-packages --yes python=3.8.18 'pip<25'
```

最初的缓存目录权限错误经批准重试；两个 pip 条件都因 `PackagesNotFoundError` 未能完成
3.8 环境创建。未将其表述为成功安装。API Python 3.12 的 Torch 2.1.1+cu118 wheel
兼容性检查也返回 no matching distribution，因此保留官方 Torch，使用隔离的 3.10 环境。

```powershell
& $env:LRECA_BOOTSTRAP_PYTHON -m venv .lreca-venv
```

先显式安装官方数值依赖，再下载官方 Torch wheel。下载命令运行在较新的 API pip 中，
为目标 Python 3.10 明确指定 ABI/platform，并不安装到 API 环境：

```powershell
.\.venv\Scripts\python.exe -m pip download --disable-pip-version-check --use-deprecated=legacy-certs --keyring-provider disabled --no-cache-dir --no-deps --only-binary=:all: --python-version 310 --implementation cp --abi cp310 --platform win_amd64 --dest .tools/wheels --index-url https://download.pytorch.org/whl/cu118 --retries 1 --timeout 30 'torch==2.1.1+cu118'
```

下载过程还保留了一个 CPU wheel 作为候选，但最终只安装并验证 cu118 版本。
旧版 worker pip 23.0.1 不支持 `legacy-certs` 选项，发现后改用其默认 CA bundle 校验；
没有禁用 TLS，也没有更改全局证书或凭据设置。

实际最终安装以固定上游 requirements 为约束，避免自动把科学依赖升级：

```powershell
.\.lreca-venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-cache-dir --index-url https://pypi.org/simple --retries 1 --timeout 20 -c external/lreca/requirements.txt '.tools/wheels/torch-2.1.1+cu118-cp310-cp310-win_amd64.whl' 'numpy==1.23.0' 'scipy==1.10.1' 'scikit-learn==1.3.2' 'pandas==2.0.3' 'matplotlib==3.7.4' 'seaborn==0.13.0' 'openpyxl==3.1.2'
.\.lreca-venv\Scripts\python.exe -m pip freeze --all
.\.lreca-venv\Scripts\python.exe -m pip check
```

辅助/传递依赖的实际版本全部保存在 `backend/requirements-lreca.lock.txt`，无损坏依赖。
运行时核实了 Python、Torch、CUDA availability、设备名称及数值库版本。

## 原始官方 demo：先于生产封装

```powershell
.\.lreca-venv\Scripts\python.exe scripts/run_lreca_baseline.py
```

脚本先独立执行未经修改的官方 Human demo，batch 32、CPU、240 条官方测试序列，
exit 0、12.2354938 s；只有此步骤成功后才开始生产 Adapter/core 封装。
实际子进程完整命令、cwd、环境、输入 hash 与 stdout/CSV 见
`docs/lreca_baseline.md`、`docs/audit/lreca_baseline_cpu/run_metadata.json`。
补充高精度回归仅在原始 demo 通过后进行，使用原始函数和重复输入 batch。

## 真实解释参考、集成与性能

```powershell
.\.lreca-venv\Scripts\python.exe scripts/verify_lreca_explainability.py
.\.venv\Scripts\python.exe -m pytest backend/tests/test_lreca_integration.py -v --junitxml=docs/audit/lreca_integration.junit.xml
.\.venv\Scripts\python.exe scripts/benchmark_lreca.py
```

- 解释参考：Human 正/负两条序列，对照原始 saliency 和同输入原始 KDE，成功生成 JSON fixture。
- 真实集成：20 passed，42.21 s，覆盖 CPU/CUDA、所有要求长度及 100 次调用生命周期。
- 性能：CPU/CUDA 20 组长度/模式、每组 1 次预热 + 3 次测量；单独测两种设备的 100 次归因/预测。
- 第一轮性能脚本因 CPU 的 CUDA-memory 为 null 而在统计层失败，修复后完整重跑成功；失败文件保留。
- API/输入契约测试用明确标注的 stub；IPC 边界测试用真实小型子进程，不把这些替代科学集成测试。

## 原始 Module 1 后端安装、测试与实际 HTTP

```powershell
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e ./backend
.\.venv\Scripts\python.exe -m pytest backend/tests -q --junitxml=docs/audit/module1_full_tests.junit.xml
.\.venv\Scripts\python.exe scripts/smoke_module1.py
```

后端 editable package 已更新为 0.1.0。完整后端测试 **90 passed，0 skipped，2 warnings，37.41 s**。
日志与 JUnit 保存在 `docs/audit/module1_full_tests.*`。两条 warning 是既有
Starlette TestClient/httpx 和 AnyIO alias 弃用提示，不是科学结果失败。

`smoke_module1.py` 实际启动 Uvicorn（本次端口 60128），通过 httpx/TCP 执行：

```text
GET  /api/v1/health                       -> 200
GET  /api/v1/methods/lreca/health          -> 200 / loaded true
POST /api/v1/methods/lreca/analyze         -> 200 / full prediction + attribution + KDE
POST /api/v1/methods/lreca/analyze         -> 200 / FASTA + global-only
POST /api/v1/methods/lreca/analyze         -> 422 / X at position 4
```

原始端口 60128 的实际 POST 输入/输出、模型日志和关闭日志当时保存在 `docs/audit/lreca_api_smoke/`。
Production 补充前已将其原始字节归档到 `.audit/module1_private_evidence/docs/audit/lreca_api_smoke/`；
该公开目录现保存补充验证的端口 64009 记录，历史记录与当前公开响应不混用。
服务结束时执行了应用 shutdown，worker 随之关闭；不是仅用 TestClient 模拟网络。

## 静态验证与差异检查

```powershell
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend/app backend/lreca_runtime scripts
.\.venv\Scripts\python.exe scripts/verify_sources.py
git --no-optional-locks -c core.quotepath=false diff --stat
git --no-optional-locks diff --check
```

Ruff、API/scientific runtime 编译、7 个 checkpoint 与 2 个词表来源的校验均通过。
另外已用 `git diff --no-index` 对照本轮前后的完整一方文件快照，并执行 whitespace check；
实际仅 Module 1 的差异保存在本机 `.audit/module1_exact.diff`，上游/依赖/缓存不参与比较。

项目当前尚无首个 Git commit；Module 0 文件已以 intent-to-add 进入索引，所以普通 Git diff
包含初始骨架。Module 1 专属变更清单与审阅另外对照本轮开始前的 51 个一方文件快照，
没有把依赖、缓存或未修改的 Module 0 文件算作本模块变更。完整清单见 `module1_changed_files.txt`。
不会通过新增 commit、切换分支或修改上游 source 来制造差异基线。

## Production Deployment Compatibility 补充验证

继续使用已经完成的 Human baseline、解释 fixture 和 CPU/GPU benchmark，没有再次运行
原始 demo 或性能脚本。新增检查聚焦部署路径、公开响应、常驻模型边界与权重存储。

最终完整后端验收从项目根目录执行（`.audit` 为不进入 Git 的原始日志目录）：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend scripts
.\.venv\Scripts\python.exe -m pytest backend/tests -q --junitxml=.audit/module1_production_final_tests.junit.xml 2>&1 | Tee-Object -FilePath .audit/module1_production_final_tests.log
.\.venv\Scripts\python.exe scripts/smoke_module1.py
```

最终 pytest **125 passed、0 skipped、2 warnings，40.04 s**。首次补充测试为 124 passed / 1 failed：
新 Git 忽略测试将 LF 输入经 Windows 文本管道转成 CRLF，影响 Git 路径解析。改为 `git check-ignore
-z --stdin` 与 NUL 分隔后，相关 7 项测试在 0.38 s 内通过，再完整运行全部 125 项成功。
这是测试输入协议修复，模型和科学期望值未改变；完整失败与成功记录均未隐藏。

日志和 JUnit 的路径脱敏公开副本为 `docs/audit/module1_production_final_tests.*`；
[验证链 JSON](audit/module1_test_verification_summary.json) 列出首次失败、7 项重测、最终全量验证及准确计数。
实际调用是先完成本次 HTTP smoke，再运行最终完整 pytest；上面按用途列出命令，不表示调用时间线。

本次真实 HTTP smoke 只运行一次，UTC 09:24:35–09:24:40，临时端口 64009：
health/full/global-only 均 200，非法 X（位置 4）为 422，device 为实际 `cuda:0`。
248 aa 的分数仍为 0.9999921321868896，主区域仍为 81–127（47 aa）。
health/full/global-only 在进行审计导出之前断言响应没有实际内部路径，metadata 均且仅含 7 项公开字段。
输出见 [本次真实 HTTP 记录](audit/lreca_api_smoke/summary.json)，服务及其 worker 均已关闭。

补充静态与只读检查包括：

- 环境别名优先级、相对路径不依赖 cwd/home、按平台选择 worker 解释器路径。
- `git ls-files --cached` 中权重为 0；各目录下模型后缀均被 `.gitignore` 排除。
- `.dockerignore` 排除本地环境、私有审计、`.env`、上游 checkout 和权重。
- 固定上游 commit/clean 状态、6 个运行来源文件与 Git blob 的字节一致性。
- 一方运行代码无 Windows 本地路径硬编码、home 查找或 Windows shell 依赖。
  API 负向测试使用虚构跨平台路径验证拒绝行为，这些字符串不用于定位本地文件。
- Docker/Podman 命令未安装；只读 WSL 枚举确认无发行版。本次未构建镜像、安装 Linux 或部署服务器。

Linux 依赖、系统库、完整 pinned checkout 及未来服务拆分要求见 [运行环境](lreca_runtime.md)。
Module 0 历史文档仅做开发机器路径变量化；原始字节保留在私有审计归档，未重做该模块。
最终再次执行只读 Git diff、专属 Module 1 快照对比与 whitespace check，并更新变更清单。
