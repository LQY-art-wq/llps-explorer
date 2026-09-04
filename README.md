# LLPS Explorer

蛋白质 biomolecular condensation / LLPS prediction and interpretation 项目。
**当前已完成 Module 0–10；Module 10 的代码与静态部署准备已完成，最终状态为 `DEPLOYMENT_BLOCKED`。**
DisMeta 的结论为 **MODE F / UNKNOWN → INTEGRATION_BLOCKED**：调用和原生结果契约尚未核实，
自动预测与手工导入均不启用，不使用其他工具冒充 DisMeta。
FuzDrop 的结论为 **MANUAL_IMPORT_ONLY**：官方提交需要浏览器验证，本站提供严格手工导入。
LRECA 后端继续支持真实预测、残基归因和 KDE 区域计算；SEG 独立提供
**Low-complexity Regions (LCR)** 注释。工作区支持输入、方法选择、导入、异步任务和结果摘要；
统一特征轨道继续复用 Module 7 实现；真实序列字母、颜色映射及双向联动见
[Module 8 报告](docs/module8_report.md)。Module 9 在不重算科学结果的前提下加入数据库历史、
恢复、删除和正式下载契约。Module 10 加入 PostgreSQL/Redis/RQ/独立 LRECA service/Caddy 的部署边界与运维文档；
当时本机没有 Docker CLI、Compose 或 daemon，因此 Linux 容器栈尚未执行，不能声称 production deployment complete。

## 当前提供的内容

- Next.js / React / TypeScript / Tailwind 分析工作区，支持 raw sequence / FASTA 和即时输入校验。
- Automatic analysis、External result、Unavailable 三组方法入口；FuzDrop 导入后仍须用户明确启用。
- Independent / Weighted 模式、权重、约 1 秒任务轮询、方法状态和 partial success 结果展示。
- Overview、Feature Viewer、Sequence Viewer、LRECA、FuzDrop、Annotations、Tables、Download 八个 tabs。
- 统一 Canvas Feature Viewer：共享 1-based inclusive 坐标、zoom/pan/brush、同步 cursor、残基/区域选择、轨道开关和表格定位。
- Protein Sequence Viewer：固定 50 aa/行、每 10 位刻度、单一 Color by、共享残基详情、严格位置跳转和键盘导航。
- Sequence Viewer 直接展示真实归因、导入 pDP 和原生区域；缺失、未导入、失败与不可用状态分开，DisMeta 着色始终禁用。
- Feature / Sequence / 方法表格共用受控选择；普通点击保留当前 tab，显式 View in Sequence / Feature Viewer 才切换并定位。
- 支持复制完整序列、选中原生区域及残基标签；新分析重置选择、聚焦目标和默认着色。
- Overview 共用紧凑全长绘图与选择摘要；完整序列仅显示在 Sequence Viewer tab，基础表格和 normalized JSON 下载保留。
- History 从持久数据库分页读取当前匿名 browser session 的任务，支持状态/方法筛选、打开、下载和永久删除。
- 历史任务使用保存的 `result_schema_version=1.0` 快照恢复全部结果视图，不重新运行模型或 ensemble。
- Download 对终态任务提供 Result JSON、Summary CSV、Residues CSV、Regions CSV 和 FASTA；queued/running 返回 409，坐标保持 1-based inclusive，数值不按 UI 精度截断。
- FastAPI：`POST /api/v1/methods/lreca/analyze`，默认返回全局预测、Grad-CAM 和 KDE。
- LRECA 模型在应用启动时加载一次；独立 Python 3.10 worker，自动选择 CUDA 或 CPU。
- 模型路径通过 `LRECA_CHECKPOINT_PATH` 配置，权重不进入本项目 Git；HTTP 仅返回公开模型身份信息。
- `GET /api/v1/health` 返回服务状态；`GET /api/v1/methods/lreca/health` 返回真实模型就绪状态。
- `GET /api/v1/methods` 分开报告方法的科学能力、自动调用可用性和手工导入可用性。
- `POST /api/v1/analysis` 返回 202 和任务 ID；`GET /api/v1/analysis/{job_id}` 查询各方法状态与结果。
- LRECA/SEG 自动执行；FuzDrop 使用同序列的已校验导入结果；DisMeta 保持 blocked，支持部分成功。
- `FuzDropRemoteAdapter` 的 load/healthcheck/analyze 完整，当前返回结构化 unavailable，不向官方提交序列。
- `POST /api/v1/methods/fuzdrop/import` 解析官方格式的 scores/regions TSV 和可选的手工复制 pLLPS。
- 导入逐位检查序列和 1-based inclusive 坐标，明确标记来源与坐标为用户声明，缺失数据保持 null。
- `POST /api/v1/methods/seg/analyze` 调用标准 NCBI segmasker，返回 LCR 区域、覆盖率与区域统计。
- `GET /api/v1/methods/seg/health` 独立检查可执行文件和版本；SEG 失败不影响 LRECA 或 FuzDrop。
- SEG 只输出 `region_annotation`，不产生 LLPS 分数或 P/N，也不参加 ensemble。
- DisMeta health/analyze 返回固定的结构化 503，不返回 IDR 区域或统计；方法目录准确标识不可用。
- FuzDrop 导入响应保留原科学字段，新增可复用的 `result_id`、`expires_at` 和 `validation_status`。
- `MethodRegistry`、`AnalysisOrchestrator`、repository-based 任务服务与独立 `EnsembleCalculator` 已接入。
- SQLAlchemy/Alembic 持久化保存 analysis jobs 和 FuzDrop imports；开发默认 SQLite，生产目标 PostgreSQL。
- 匿名 session 的随机 token 由 HttpOnly cookie 保存并随请求转发，后端不通过 `X-Analysis-Session` 响应 header 回显原 token，数据库仅保存 SHA256 owner key；detail、history、export 和 delete 均检查 ownership。
- 加权模式只接受成功的 LRECA 与有效 FuzDrop 全局结果；保留 `not_calibrated` 和实验性分数语义。
- 统一状态、科学方法分类/语义和 1-based inclusive 坐标契约及测试。
- 官方 LRECA 固定 commit 的本地 checkout、human checkpoint SHA256 和来源核验。

## 文档

- [最终 Git 冻结审计](docs/final_git_audit.md) / [GitHub push 与远端安全验证](docs/github_push_report.md)
- [Module 10 部署准备、验证边界与最终阻塞状态](docs/module10_report.md)
- [部署](docs/deployment.md) / [运维](docs/operations.md) / [安全](docs/security.md) / [备份恢复](docs/backup_restore.md)
- [Module 9 完整报告与最终风险](docs/module9_report.md)
- [Module 9 命令与验收证据索引](docs/module9_commands.md)
- [Analysis persistence、repository、迁移与重启恢复](docs/persistence.md)
- [Raw sequence、FuzDrop import、到期与删除策略](docs/data_retention.md)
- [JSON、CSV、FASTA 和安全文件名契约](docs/export_formats.md)
- [Module 8 序列查看器与联动报告](docs/module8_report.md)
- [Module 8 变更清单](docs/module8_changed_files.txt) / [命令与验证](docs/module8_commands.md)
- [Module 8 浏览器测试材料及 synthetic 边界](docs/audit/module8_browser/fixtures/README.md)
- [Module 7 统一特征查看器报告](docs/module7_report.md)
- [Module 7 变更清单](docs/module7_changed_files.txt) / [命令与验证](docs/module7_commands.md)
- [Module 6 前端报告与验收状态](docs/module6_report.md)
- [Module 6 变更清单](docs/module6_changed_files.txt) / [命令与验证](docs/module6_commands.md)
- [Module 5 完整报告](docs/module5_report.md)
- [能力路由、任务生命周期与 ensemble](docs/orchestrator.md)
- [Module 5 变更清单](docs/module5_changed_files.txt) / [实际命令与验证](docs/module5_commands.md)
- [Module 4 完整报告与最终决策](docs/module4_report.md)
- [DisMeta 官方接入审计、接口及生产边界](docs/dismeta_integration.md)
- [Module 4 变更清单](docs/module4_changed_files.txt) / [实际命令与验证](docs/module4_commands.md)
- [Module 3 完整报告](docs/module3_report.md)
- [SEG 来源、安装、参数、坐标与运行环境](docs/seg_runtime.md)
- [Module 3 变更清单](docs/module3_changed_files.txt) / [实际命令与验证](docs/module3_commands.md)
- [Module 2 完整报告与最终接入决策](docs/module2_report.md)
- [FuzDrop 接口、格式与导入限制](docs/fuzdrop_integration.md)
- [Module 2 变更清单](docs/module2_changed_files.txt) / [实际命令与验证](docs/module2_commands.md)
- [Module 1 完整报告](docs/module1_report.md)
- [LRECA 安装、配置与 CPU/GPU 性能](docs/lreca_runtime.md)
- [Human 身份证据](docs/lreca_identity.md) / [Grad-CAM 与 KDE 定义](docs/lreca_explainability.md)
- [官方原始 demo 基线](docs/lreca_baseline.md) / [Module 1 实际命令](docs/module1_commands.md)
- [Module 0 交付报告与风险](docs/module0_report.md)
- [LRECA / SEG 来源、checkpoint 与科学代码审计](docs/model_sources.md)
- [FuzDrop / DisMeta 外部服务审计](docs/external_services.md)
- [架构、范围、数据语义和坐标约定](docs/architecture.md)
- [实际执行命令与验证记录](docs/module0_commands.md)
- [上游 checkout 的恢复方式](external/README.md)

## 本地安装（PowerShell）

前端使用 pnpm 11.19.0 和 Node.js >=22.13；本机验证 Node 24.19.0。
Node 下限取 pnpm 11 的要求，不能只使用 Next.js 的 >=20.9 下限。
后端本机验证 Python 3.12.13；科学 worker 单独使用 Python 3.10.19、PyTorch 2.1.1+cu118。
两套依赖分别锁定。完整安装步骤与 Python 3.8 尝试记录见 [运行环境](docs/lreca_runtime.md)。

从项目根目录执行，中文统一使用 UTF-8：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e ./backend
pnpm --dir frontend install --frozen-lockfile
```

还需按运行环境文档建立 `.lreca-venv`，安装 `backend/requirements-lreca.lock.txt`。
本工作区这两套环境已建立并验证。启动时缺少 worker、权重或 hash 不一致会报告不可用。

SEG 另需标准 **NCBI BLAST+ 2.17.0+** 中的 `segmasker`，无需 Torch 或 CUDA。
从项目根目录运行安装脚本；已有正确缓存会复用，脚本不修改全局 PATH：

```powershell
.\.venv\Scripts\python.exe scripts/setup_seg.py --destination .tools/seg
```

随后通过 `SEG_EXECUTABLE_PATH` 指向安装结果，或让 `segmasker` 可从受控 PATH 发现。
本机被 Git 忽略的根目录 `.env` 已配置
`SEG_EXECUTABLE_PATH=.tools/seg/ncbi-blast-2.17.0+/bin/segmasker.exe`，需从根目录启动。
其他机器按实际安装位置配置，代码不会自动回退到开发缓存。离线安装、官方来源校验和
Linux/Docker 安装策略见 [SEG 运行环境](docs/seg_runtime.md)。Windows 官方程序已实跑；
Linux/Docker 尚未实测，不能直接复制 Windows 二进制或虚拟环境。

`requirements.lock.txt` 记录本轮隔离环境中解析的依赖和开发工具版本。
首次建立骨架时使用 `pip install -e './backend[dev]'`，后续按 lock 安装。
若本机 pip 的默认证书/凭据初始化停滞，本轮已验证以下**仅作用于该次命令**的方式：

```powershell
.\.venv\Scripts\python.exe -m pip install --use-deprecated=legacy-certs --keyring-provider disabled --no-cache-dir -r backend/requirements.lock.txt
```

该选项使用 pip 的 CA bundle 校验证书；没有关闭 TLS 验证或修改全局配置。
本机没有 npm/py launcher；开发用解释器与 pnpm 路径由环境提供，见命令记录。

Linux Server + Docker 的运行前提和兼容处理已记录在 [Production Deployment Readiness](docs/module1_report.md#production-deployment-readiness)。
核心推理可复用于独立 LRECA 服务；当前 Linux 与容器尚未实测，Windows 虚拟环境不能直接复制过去。

## 启动

本地开发默认使用 `sqlite:///./backend/data/llps_explorer.db`；也可在启动后端前通过
`DATABASE_URL` 选择其他 SQLite 文件或 PostgreSQL。应用启动会使用 Alembic 升级到当前 schema，
不会 drop/create 现有表。数据库和迁移细节见 [Analysis persistence](docs/persistence.md)。

终端 1，从项目根目录启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

终端 2，首次启动前端时先复制服务端环境配置；已有 `.env.local` 时保留并检查其中的 target：

```powershell
if (-not (Test-Path frontend/.env.local)) {
    Copy-Item frontend/.env.example frontend/.env.local
}
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:FEATURE_VIEWER_TEST_MODE = '0'
pnpm --dir frontend dev
```

也可不创建文件，改为在启动 Next 的同一终端设置
`$env:BACKEND_URL = 'http://127.0.0.1:8000'` 后运行 `pnpm --dir frontend dev`。
`BACKEND_URL` 是**必填、无默认值的服务端配置**，不能加 `NEXT_PUBLIC_` 前缀。
修改运行时 target 后重启 Next 即可，无需仅为 `BACKEND_URL` 重新 build。
普通业务环境将 `FEATURE_VIEWER_TEST_MODE` 保持为 `0` 或不设置；仅独立验收环境使用 `1`，
显式启用带 Synthetic test data 标记的测试入口。测试数据不会预填普通工作区。

打开 [本地分析工作区](http://127.0.0.1:3000)；
[本地 API 文档](http://127.0.0.1:8000/docs) 可提交真实 LRECA 预测和 SEG 注释请求。
工作区通过同源 `/api/v1` 服务端代理读取方法目录、导入结果及提交/查询任务，浏览器不会获得
后端内部 URL、文件路径或密钥。打开官方 FuzDrop 是用户主动访问新标签，本站不自动提交序列。
后端读取 `LLPS_APP_NAME`、`LLPS_ENVIRONMENT`、`DATABASE_URL`、`ANALYSIS_RETENTION_DAYS`、
`ANALYSIS_CLEANUP_INTERVAL_SECONDS`、`ANALYSIS_MAX_SEQUENCE_LENGTH`、`DEV_DISABLE_JOB_OWNERSHIP`、
`LRECA_*`、三项 `FUZDROP_*`
导入配置、`SEG_*`、`DISMETA_OFFICIAL_SITE_URL`、`ENSEMBLE_THRESHOLD` 及其余 operational limits；
完整配置见 `backend/.env.example`。
`.env` 从启动工作目录读取；从根目录启动时可复制该示例到根目录 `.env`。

LRECA 请求正文为 `{"sequence":"ACDEFGHIKLMNPQRSTVWY..."}`；省略选项时默认计算解释。
`include_attribution=false` 可只计算全局分数，此时归因、Top residues、KDE、critical regions 均为 null。
上例中的省略号仅表示较长序列，实际请求只能含标准 20 种氨基酸，可输入单条 FASTA。
规范化后的单条序列默认最多 50,000 aa；`ANALYSIS_MAX_SEQUENCE_LENGTH` 可配置为 1–1,000,000。
长度按 canonical residue 数计算，FASTA header、换行和空白不计入。
统一 analysis、四个单方法 analyze 及 FuzDrop import 都在执行或持久化前应用该限制，超限返回
413 / `ANALYSIS_SEQUENCE_TOO_LONG`。这与 FuzDrop import 的请求字节上限是两个独立限制。

FuzDrop health/analyze 返回 HTTP 503 和 `browser_protected`，表示自动预测不可用。
手工导入默认开启；输入需声明 `source_declaration=official_fuzdrop_export` 和
`coordinate_system=one_based_inclusive`。官方 TSV 不含全局 pLLPS；没有另行提供时全局结果为 null。
导入成功仅表示本地格式校验通过，不认证数据确由官方生成。本轮未取得真实 FuzDrop 输出，
合成样例只用于格式测试。请求字段与实际科学语义见 [导入文档](docs/fuzdrop_integration.md)。

SEG 的 `POST /api/v1/methods/seg/analyze` 仅接收 `sequence`，同样支持单条 FASTA。
默认 `SEG_WINDOW=12`、`SEG_LOCUT=2.2`、`SEG_HICUT=2.5`，执行超时为
`SEG_TIMEOUT_SECONDS=10`；这些参数只由服务端配置。返回坐标为 1-based inclusive，
coverage 使用区域并集覆盖残基数除以序列长度。成功且没有 LCR 时区域为空、统计值为 0；
程序不可用或执行失败时返回结构化错误，不能解释为 LLPS 阴性。
方法目录单独报告 SEG 的 `available`、`capabilities=["regions"]` 和
`semantic_types=["region_annotation"]`；服务级 `analysis_enabled` 仍只反映 LRECA 就绪状态。

DisMeta 的 `GET /api/v1/methods/dismeta/health` 与 `POST /api/v1/methods/dismeta/analyze`
返回 503 / `DISMETA_UNAVAILABLE`（health 使用固定不可用原因）；非法输入仍校验并返回 422。
当前没有 `/dismeta/import` 路由。`DISMETA_OFFICIAL_SITE_URL` 仅用于指向已核实的官方入口，
不能通过配置开启自动调用。DisMeta 不可用结果中的区域与统计为 null，不能显示为“无 IDR”。
官方资料和原生格式仍存在缺口；详见 [DisMeta integration](docs/dismeta_integration.md)。

## 统一分析任务

向 `POST /api/v1/analysis` 提交序列与 `selected_methods`，例如：

```json
{"sequence":"ACDEFGHIKLMNPQRSTVWY","selected_methods":["seg"],"prediction_mode":"independent"}
```

接口返回 202；用返回的 `job_id` 查询 `GET /api/v1/analysis/{job_id}`。
各方法独立报告状态；部分方法成功、其他方法失败或不可用时，任务为 `partial_success`。
选中 FuzDrop 时，将导入响应中的 ID 放入 `external_results.fuzdrop.result_id`；服务会检查
序列长度与 SHA256。不提供导入结果时返回 `external_result_required`，不会调用官方服务。
只有选中 DisMeta 时才报告其 blocked 状态；未选中时不产生相关警告。

`prediction_mode=weighted` 要求同时选择 LRECA/FuzDrop，并提供例如
`weights={"lreca":0.6,"fuzdrop":0.4}`。两者全局结果都成功才计算；缺少导入、分数或任一失败，
ensemble 为 unavailable，不把另一方法自动改成 100%。默认 `ENSEMBLE_THRESHOLD=0.5`，
返回 `score` 与后端计算的 P/N，并标记 `calibration_status=not_calibrated`、
`interpretation_status=experimental_weighted_score`，不称为已校准 LLPS 概率。SEG/DisMeta 不参与加权。

方法目录的 `available` 表示“可自动运行或可经手工导入使用”：LRECA/SEG 为 `local_automatic`，
FuzDrop 为 `manual_import`，DisMeta 为 `integration_blocked`。自动能力需读取
`automatic_analysis_available`；FuzDrop 导入开启时 `available=true`，仍不能自动提交。
单方法 health 的旧契约保持不变：FuzDrop 仍为 `browser_protected`，DisMeta 仍为 `unknown`。

当前 FastAPI 使用 SQLAlchemy repository：开发默认写入 SQLite，生产目标是通过 `DATABASE_URL`
连接 PostgreSQL。任务与 FuzDrop 导入默认保留 7 天；期限由 `ANALYSIS_RETENTION_DAYS` 配置，
创建时固定，不因打开或下载而延长。Alembic 在启动时迁移到 `head`；未过期的终态任务可跨重启读取，
在本地 inline 模式中，遗留 queued/running 任务会以 `service_restart` 明确恢复为 `interrupted`；Module 10
生产拓扑改用 Redis/RQ、独立 worker、PostgreSQL source-of-truth、有限重试和 stale-running recovery，
但该 Docker 路径尚未真实运行。启动与周期 cleanup 会删除过期数据，主动
`DELETE /api/v1/analysis/{job_id}` 会删除该 owner 的 sequence 和结果，并只清理无其他 job 引用的
FuzDrop import。详情见 [持久化](docs/persistence.md)、[数据期限](docs/data_retention.md)、
[编排文档](docs/orchestrator.md)及 [Module 10 报告](docs/module10_report.md)。

`ANALYSIS_MAX_JOBS` 与 `EXTERNAL_RESULT_MAX_ENTRIES` 是全站容量，而非每个 anonymous owner 的配额。
当前进程用锁串行 capacity count + insert；PostgreSQL 还对协作进程使用 transaction advisory lock。
直接绕过 repository 的数据库写入不受这项协作锁保护。

## 验证

从根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend/app backend/tests
.\.venv\Scripts\python.exe -m compileall -q backend/app
pnpm --dir frontend test
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
python scripts/verify_sources.py
.\.venv\Scripts\python.exe scripts/smoke_module5.py
```

Module 5 的 [smoke_module5.py](scripts/smoke_module5.py) 启动实际 Uvicorn，只向本机后端发送
HTTP 请求并关闭服务，验证真实 LRECA/SEG 任务、FuzDrop 缺少导入及有效导入后的加权结果，
以及 DisMeta blocked 路由和方法目录。FuzDrop 合成格式样例仅用于软件验证，不认证官方来源。
运行前需安装和配置 SEG 与 LRECA。脚本不向 FuzDrop 提交预测，默认 pytest 同样不访问真实 FuzDrop。
不向 DisMeta 提交序列，默认 pytest 同样不请求该服务。这是无需启动前端的后端 HTTP 验收入口；
Module 6 的真实浏览器 A–H、响应式、键盘及构建记录见 [前端报告](docs/module6_report.md)。
Module 8 的序列查看器、跨视图选择、复制、键盘、五种长度及响应式记录见
[当前命令与证据索引](docs/module8_commands.md)。这些前端检查不重新定义后端科学结果。
`smoke_module0.py` 至 `smoke_module4.py` 保留为冻结的历史阶段验收脚本。

Module 0 历史命令：

```powershell
python scripts/smoke_module0.py
```

要检验生产模式工作区，先 build，在配置好 `BACKEND_URL` 后以
`pnpm --dir frontend start --hostname 127.0.0.1 --port 3000` 代替 dev。
普通生产启动保持 `FEATURE_VIEWER_TEST_MODE=0`；`/dev/feature-viewer` 和
`/dev/sequence-viewer` 不向普通业务开放。合成输入与性能 harness 的独立测试启动见 Module 8 命令记录。
生产 `start` 脚本本身是 `next start`，监听 hostname 可由 CLI 选择，没有固定 localhost。
Linux/Docker 和正式 PostgreSQL 部署仍未实测，不能将本地 production build 验收等同于容器部署完成。
用 Ctrl+C 停止自己启动的进程。本地 SQLite 随后端自动打开，无需另行启动 Docker、PostgreSQL、
队列或部署服务。

## 后续模块

| 模块 | 范围 |
| --- | --- |
| 1（已完成） | LRECA human-specific backend |
| 2（已完成） | FuzDrop MODE C unavailable boundary + strict manual import |
| 3（已完成） | 标准 SEG / Low-complexity Regions (LCR) 独立注释 |
| 4（已完成审计与边界） | DisMeta / IDR：MODE F，INTEGRATION_BLOCKED |
| 5（已实现） | 能力路由、分析任务、导入结果引用与实验性加权分数 |
| 6（已实现，验收见报告） | 真实 Analysis Workspace、导入 UX、任务状态、基础表格与 JSON 下载 |
| 7（已实现） | Unified protein feature viewer |
| 8（已实现，验收见报告） | Protein sequence viewer、残基/区域详情与跨视图联动 |
| 9（已实现） | 完整 Tables、JSON/CSV/FASTA、持久历史、重启恢复、删除、retention 与匿名 ownership |
| 10（代码与静态准备已完成；动态验收 blocked） | Linux/Docker 部署拓扑、队列/worker、独立 LRECA service、Caddy 与运维材料；本机无 Docker runtime，未执行容器验收 |

FuzDrop 自动访问的结论为 `browser_protected`；手工导入不改变自动调用状态。
DisMeta 的可靠调用及结果契约未确认。Module 10 最终状态为 `DEPLOYMENT_BLOCKED`；后续只有在具备 Docker/Linux runtime 后才能继续动态部署验收。
