# LLPS Explorer 架构与 Module 10 部署边界

## 当前可运行范围

已完成 Module 0 工程骨架、Module 1 LRECA 真实推理与解释，以及 Module 2 FuzDrop 接入审计和
手工导入；Module 3 已实现标准 SEG 的 Low-complexity Regions (LCR) 注释。
Module 4 已完成 DisMeta 重审及 MODE F / UNKNOWN 的不可用边界，最终状态为 INTEGRATION_BLOCKED。
Module 5 已接入能力注册表、统一任务服务、导入结果引用和实验性 weighted ensemble。
Module 6 已实现连接真实后端的 Analysis Workspace、手工导入 UX、方法状态、基础结果表格和
JSON 下载。Module 7 已实现统一 Canvas Feature Viewer；Module 8 已实现真实序列字母、
逐位着色、残基/区域详情与 Feature / Sequence / 表格之间的双向选择联动。
Module 9 已实现 SQL 持久化、匿名 owner-scoped history、重启恢复、完整 Tables、主动删除、
retention 及 JSON/CSV/FASTA 下载。Module 10 已增加 Linux/Docker production-like 拓扑、
Redis/RQ 持久任务分发、独立 analysis worker、独立 LRECA service、Caddy 边界及 PostgreSQL
one-shot migration。由于当前机器没有 Docker/Linux 容器运行时，这些部署资产仅通过静态与宿主机
测试，容器拓扑尚未实际启动，最终状态为 `DEPLOYMENT_BLOCKED`。后端继续提供以下能力：

- LRECA health/analyze：真实 human-specific global prediction、Grad-CAM、KDE。
- FuzDrop health/analyze：MODE C、`available=false`、结构化 unavailable；不提交外部预测。
- FuzDrop import：纯本地解析和校验官方 TSV 格式；标记来源与坐标均为用户声明。
- SEG health/analyze：本地标准 NCBI segmasker 的就绪状态及 LCR 注释。
- DisMeta health/analyze：固定503、regions及统计为null，不提交外部请求或接受导入。
- `GET /api/v1/methods`：四种方法的能力和独立可用性；DisMeta 自动与手工导入均为false。
- `POST /api/v1/analysis` / `GET /api/v1/analysis/{job_id}`：提交任务并查询独立方法状态及可选加权结果。
- `GET /api/v1/analysis/history`：分页、状态/方法过滤的轻量 history summary。
- `DELETE /api/v1/analysis/{job_id}`：删除当前 owner 的 sequence、metadata 和结果。
- `GET /api/v1/analysis/{job_id}/export/*`：Result JSON、三种 CSV 和 FASTA。
- `GET /api/v1/config/public`：只公开当前 analysis retention days。

旧的服务级 health 保留兼容语义；新的 `/health/live` 仅表示进程存活，`/health/ready` 与
`/api/v1/system/status` 才检查数据库、Redis/RQ、worker、LRECA 和 SEG 的部署就绪状态。
数据库始终是任务的持久 source of truth。开发模式仍由单个 FastAPI 进程内的 asyncio tasks
执行；production 模式把 `job_id` 放入 Redis/RQ，由独立 worker 从 PostgreSQL 读取序列和输入。

## Production topology

```text
Browser
   |
   v
Caddy                         [only host-published service]
   |-- / ----------------------> Next.js production server
   `-- /api/* -----------------> FastAPI backend
                                    |-- PostgreSQL [jobs, results, ownership]
                                    `-- Redis/RQ   [job_id only]
                                              |
                                              v
                                      analysis worker
                                         |-- private LRECA service
                                         |       `-- one resident human model process
                                         `-- NCBI segmasker 2.17.0+

FuzDrop: validated manual import only
DisMeta: integration blocked
```

Compose 声明 `reverse-proxy`、`frontend`、`migrate`、`backend`、`worker`、`lreca`、
`postgres` 和 `redis` 八项服务。只有 Caddy 发布主机端口；PostgreSQL、Redis、worker 与
LRECA 只在内部网络可见。Checkpoint 通过只读 bind mount 注入 LRECA，不由第一方主仓库跟踪，
也不进入镜像。
LRECA 在启动期验证 SHA256，加载一次并驻留；默认一个 model process、一次受控推理并发。
这些是已审查的配置约束，尚不是 Docker 运行证据；详见 [deployment](deployment.md)。

## 开发模式组件关系

```text
Frontend (Next.js / React / TypeScript / Tailwind)
    |
    | same-origin /api/v1/* -> Next.js server-side proxy
    v
FastAPI
    |
    +-- method-specific HTTP routes          [current]
    |      |
    |      +-- LRECAAdapter
    |      |      `-- resident Python worker -> pinned human model / CPU or CUDA
    |      |
    |      +-- FuzDropRemoteAdapter           [MODE C: local unavailable response]
    |      |
    |      +-- FuzDrop import service         [local TSV parsing; no HTTP transport]
    |      |
    |      +-- DisMetaAdapter                [MODE F: local unavailable response]
    |      |
    |      `-- SEGAdapter                    [local LCR annotation]
    |             +-- SEG process service -> standard segmasker CLI / stdin
    |             `-- SEG parser -> 1-based inclusive LCR regions / summaries
    |
    +-- AnalysisJobService -> AnalysisJobRepository
    |      |                         `-- SQLAlchemy -> SQLite development / PostgreSQL target
    |      +-- startup recovery / retention cleanup / capacity admission locks
    |      `-- persisted history / detail / delete / export
    |
    `-- AnalysisOrchestrator <- MethodRegistry
           +-- LRECA / SEG                    [local automatic execution]
           +-- SQLImportedResultStore         [validated ID + matching sequence]
           +-- FuzDrop imported snapshot      [manual import only]
           +-- DisMeta                        [blocked status; no adapter call]
           `-- EnsembleCalculator             [optional experimental weighted score]
```

LRECA 模型由应用 lifespan 启动一次并驻留在科学 worker，HTTP 请求复用该进程；FuzDrop 的
load/healthcheck/analyze 均已实现，当前无网络 client，analyze 返回固定结构化不可用结果。
手工导入服务与 HTTP、远程 adapter 分离，HTTP 将解析委托给线程池。公共 FuzDrop DTO 预留
A/B/C/D 模式与对应来源，但当前执行路径固定 C；环境或请求字段不能开启未经证实的自动接口。
将来确认官方 A/B 契约后可替换 adapter 内部通信，复用调用接口和科学结果结构。

SEG 不加载机器学习模型。独立 `SEGAdapter` 在启动时确认可执行文件与版本，healthcheck 使用
轻量版本命令；每次 analyze 通过独立子进程的 stdin 输入 FASTA，解析服务只处理该请求的
stdout。调用使用参数数组，不使用 shell 或共享永久 FASTA 文件；超时与取消会回收自己的进程。
SEG 的初始化、健康检查、分析或关闭失败均在独立边界处理，不阻断已有方法的生命周期。

DisMeta 已从 PendingAdapter 改为独立的 audited unavailable boundary。当前没有 DisMeta HTTP
transport、native parser、模型、阈值或import；公开结果固定 F/unknown/INTEGRATION_BLOCKED，
只有合法输入的长度和SHA可作诊断。内部 DisMetaResult 仅是尚未接入HTTP的规范化坐标数学契约，
不能作为成功预测或原始导入格式。构造/load/health/analyze/close失败都不会阻断既有方法。
`MethodRegistry` 独立于 HTTP：按能力和接入模式路由，LRECA/SEG 使用有时限的本地就绪检查，
FuzDrop/DisMeta 不通过注册表调用远程方法。目录的 `available` 表示自动运行或手工导入至少有
一条可用路径；`method_supported`、`automatic_analysis_available`、`manual_import_available`
和 `integration_status` 分别描述支持、执行能力与当前状态。

目录模式统一为 `local_automatic`（LRECA/SEG）、`manual_import`（FuzDrop）及
`integration_blocked`（DisMeta）。FuzDrop 导入开启时目录 `available=true`，自动能力仍为 false；
DisMeta 支持其方法身份但接入状态为 blocked。单方法 health 继续保留既有契约：FuzDrop
`browser_protected`、DisMeta `unknown` 及各自的 unavailable 结果，不与目录模式混用。

## 目录与职责

```text
.
├── frontend/
│   ├── src/app/                    # 工作区入口、布局、固定颜色 tokens
│   │   └── api/v1/[...path]/       # 同源服务端代理；读取运行时 BACKEND_URL
│   ├── src/components/            # workspace、results、import dialog、Feature / Sequence Viewer
│   ├── src/lib/                   # contracts、API/polling、纯 mapper / selection / 坐标与布局
│   ├── tests/                     # Node 原生 unit tests
│   ├── next.config.ts              # Next 运行配置；不内嵌后端 URL
│   ├── package.json
│   └── pnpm-lock.yaml
├── backend/
│   ├── app/
│   │   ├── api/                   # history/export/delete、session、config、health/method routes
│   │   ├── adapters/
│   │   │   ├── base.py
│   │   │   ├── lreca.py
│   │   │   ├── fuzdrop_remote.py
│   │   │   ├── seg.py
│   │   │   └── dismeta.py
│   │   ├── persistence/           # SQLAlchemy tables 与 Alembic migrations
│   │   ├── services/              # repository、SQL stores、history/export、orchestrator
│   │   │                         # 以及既有 LRECA IPC / FuzDrop parser / SEG process + parser
│   │   ├── schemas/               # 方法结果、来源、语义、坐标、history/public config
│   │   ├── core/config.py
│   │   └── main.py
│   ├── tests/
│   ├── lreca_runtime/              # 独立环境中的模型、归因、KDE、worker
│   ├── alembic.ini
│   └── pyproject.toml
├── external/
│   ├── lreca/                      # 上游只读用途 checkout，不纳入本项目 Git
│   ├── lreca-source.json            # commit / checkpoint / SHA256 / variant
│   └── seg-source.json              # 固定发行包、版本、来源与已验证哈希
├── docs/
│   ├── model_sources.md
│   ├── external_services.md
│   ├── architecture.md
│   ├── persistence.md
│   ├── data_retention.md
│   ├── export_formats.md
│   └── audit/                      # 实际探测及验证记录
├── scripts/                        # 来源核验、SEG 安装、GET 审计、本地 smoke check
└── README.md
```

不创建 `external/fuzdrop/`。Analysis Workspace、统一多轨视图、实际序列字母视图、持久 History、
完整 Tables 及正式数据下载已实现；复杂 motif search、alignment、Canvas 图形导出、Docker 与部署
不属于 Module 9。

## 前端工作区与数据流

`workspace.tsx` 管理页面布局、输入和方法操作，`use-workspace.ts` 连接真实方法目录、
analysis 提交/轮询、持久 history 与 export/delete actions。`sequence.ts`、`analysis-state.ts` 提供可独立测试的输入、
导入生命周期、请求构建和能力判断；`api.ts` 只使用同源 API，按安全错误码显示友好消息。
默认约 1 秒轮询，终态停止；新任务、历史任务切换和卸载会取消旧读取。History 通过后端 summary
API 分页读取当前 anonymous owner 的未过期任务，默认 UI page size 为 20，并支持 status/method filter。
打开任务再读取完整 persisted snapshot；保存的 canonical sequence 会校验 length 与 SHA256，再绑定到
Viewer。已提交任务的输入快照与当前编辑区分离，防止结果与序列错配。

方法按 automatic、manual import、blocked 分组。FuzDrop 弹窗使用既有 import contract，
用户须确认官方来源及 1-based inclusive 坐标声明；来源仍为未独立认证的用户声明。
文件使用 fatal UTF-8 解码，保留原 TSV；完整 scientific parsing 继续由后端完成。
导入成功后不自动启用方法或 weighted。改输入、关闭、替换、到期以及响应竞态由取消信号、
revision、序列 SHA256/长度与有效期检查处理。DisMeta 无可选运行或导入入口。

`results.tsx` 实现 Overview、Feature Viewer、Sequence Viewer、LRECA、FuzDrop、Annotations、
Tables、Download 八个 tabs。Tables 包含 prediction summary、LRECA top residues/critical regions、
真实 imported FuzDrop、SEG LCR、DisMeta status 及分页的 residue-level data；它保留各方法原生顺序、
空值和科学语义。前端不计算 ensemble，不重建区域，不把 attribution、pDP、KDE 或 annotation 合为
同类数值。Download 请求后端 persisted snapshot 的 JSON、summary/residues/regions CSV 和 FASTA；
只有终态任务可导出，数据库读取和 byte construction 均在线程池完成，不阻塞 event loop。
partial success 保留已成功方法的结果。

`viewer-data.ts` 从任务结果及绑定的输入快照提供 sequence、LRECA attribution/KDE/critical
regions、FuzDrop propensity/regions 与 SEG regions，保留 null 与空数组的区别。
Module 7 的 `feature-viewer-model.ts` 在此契约上进行逐轨验证，保留 native precision、null、区域顺序和 primary 标记。
`ProteinFeatureViewer` 使用共享坐标和原生 Canvas 2D；静态轨道绘图与 cursor/selection overlay 分离，
Overview 共用固定全长变体，完整 tab 支持 zoom/pan/brush、统一 tooltip、轨道开关和表格定位。
`feature-coordinates.ts` 是闭区间与像素坐标的唯一来源；不在前端重新计算科学输出。
`buildSequenceViewerModel` 复用经过验证的 FeatureViewerModel，一次性生成真实残基字母、
原始 attribution / KDE / pDP 数值、原生区域 membership 与统一 tooltip。它不重新 normalize、
重算科学算法或从全局分数补造逐位数据。合法空区域仍表示 No；缺少输出、未导入、失败与不可用分别保留。
Color by 一次只启用一个可用模式；区域着色要求非空原生区域，DisMeta 始终禁用。

`ProteinSequenceViewer` 使用固定 50 aa/行和每 10 位刻度，monospace 字符不会因 CSS 自动换行
改变位置。行组件复用渲染，单一事件委托处理残基 hover/click；没有逐残基 tooltip、state 或 observer。
`sequence-viewer-layout.ts` 负责行定位、严格位置/残基标签解析、键盘 ±1/±50 与复制闭区间切片。
选中残基有独立 outline，选中区域保留覆盖标记；着色不替代详情中的文本语义。

`results.tsx` 与 `viewer-selection.ts` 为两个 Viewer 和方法表格维护单一 selection。
Feature 与 Sequence 的 focus request 分开：普通点击只同步选择，不强制切 tab；显式 View 操作
才切换目标 tab 并定位。Sequence tab 激活后滚动到相应行，Feature 定位继续使用 Module 7 的
focusResidue / focusRegion，不复制 zoom 算法。新任务和历史任务重挂载会话，避免残留旧序列选择。
Overview 仅展示紧凑图和当前选择摘要，不重复渲染完整 Sequence Viewer。

Next 的 route handler 仅转发 allowlist 中的 `/api/v1` JSON 和五种 export 路径，读取**必填、无默认值**
的服务端 `BACKEND_URL`。该值不使用 `NEXT_PUBLIC_`，不进入浏览器 bundle；错误不暴露上游地址或
内部路径。proxy 生成高熵 anonymous token，存入 HttpOnly/SameSite cookie，并只通过
`X-Analysis-Session` 请求 header 发给后端；后端不通过同名响应 header 回显原 token，新 session 只通过
HttpOnly `Set-Cookie` 建立。下载响应还校验 MIME type 和 attachment filename。
首次本地启动先复制 `frontend/.env.example` 到 `frontend/.env.local`，或在启动进程环境中设置；
修改 target 后重启 Next 即可，不需为该变量重新 build。`start=next start` 不固定 hostname，
部署方可用 CLI 选择监听地址；当前 Linux/Docker 部署尚未实测。

## 科学分类与数据语义

| 方法 | 分类 | 允许的输出语义 | 颜色 |
| --- | --- | --- | --- |
| LRECA | phase_separation_prediction | model_prediction / model_attribution / derived_hotspot | blue `#2563eb` |
| FuzDrop | phase_separation_prediction | model_prediction / residue_propensity / region_prediction | purple `#7c3aed` |
| SEG / LCR | sequence_feature_annotation | region_annotation | green `#15803d` |
| DisMeta / IDR（当前不可用） | sequence_feature_annotation | region_annotation | orange `#c2410c` |

`AnalysisResult` 是通用 envelope，LRECA、FuzDrop 和 SEG 均有各自的严格科学 payload。方法目录的
`category=prediction/annotation` 是面向接口的简写，不改变上表分类。缺失数据用 null/N/A，
不能伪造为 0。FuzDrop pDP 是 residue propensity，不是 LRECA attribution。
FuzDrop pLLPS 的 droplet-driver 阈值为 **>=0.60**；N 不能解释为蛋白绝不发生 LLPS。
未提供 pLLPS 时不从 pDP 或区域推导全局分数，未经校准的结果明确保留 `not_calibrated`。
Residues CSV 的 DisMeta 状态读取 persisted execution：正常 blocked 为 `Unavailable`，service restart
为 `Interrupted`，其他状态按其实际名称输出；它从不由空区域推导 `false` 或“0 IDR”。

SEG 的唯一科学输出是 `annotation_type=LCR`、`semantic_type=region_annotation`。
`SEGResult` 不包含 global score、LLPS probability、threshold 或 P/N 字段。
成功且没有 LCR 时 `regions=[]`，coverage、region_count、longest_region 都为 0；
执行失败时这些科学字段为 null。coverage 计算所有区域的并集覆盖比例，region_count 与
longest_region 分别取保留的原生条目数和最大长度，不把统计并集改写为区域合并。

SEG 接口为 `POST /api/v1/methods/seg/analyze`，仅接收 `sequence`；
`GET /api/v1/methods/seg/health` 就绪返回 200，不可用返回 503。分析缺少可执行文件为 503，
超时为 504，执行失败或输出解析/验证失败为 502，非法输入为 422；失败使用结构化安全错误。
方法目录的显示名统一为 **Low-complexity Regions (LCR)**，`name=SEG`、
`category=annotation`、`integration_mode=local_automatic`、`capabilities=["regions"]`、
`semantic_types=["region_annotation"]`，可用性来自当前 SEG 健康状态。

原 adapter 继续管理自身的加载与执行状态。统一 `MethodExecution` 增加 queued/running/success/
failed/unavailable/external_result_required/skipped 外壳，内部 `result` 仍由原方法 DTO 管理。
成功结果保留原科学语义，注释不会被放进 global-score 字段。

## 输入与坐标约定

当前后端输入是一条 raw amino-acid sequence 或 FASTA，FASTA header 与 sequence 分开。
去除空白、换行并转大写；只接受 `ACDEFGHIKLMNPQRSTVWY`，非法字符需报告位置，
不能静默替换 B/J/O/U/X/Z。不能伪造 organism、UniProt accession 或输入未提供的 protein name。
规范化后长度由 `ANALYSIS_MAX_SEQUENCE_LENGTH` 限制，默认 50,000 aa，可配置范围 1–1,000,000；
长度只计算 canonical residues，不计 FASTA header、换行或空白。
统一任务、LRECA/FuzDrop/SEG/DisMeta analyze 和 FuzDrop import 超限均返回 413
`ANALYSIS_SEQUENCE_TOO_LONG`，且不会启动科学方法或写入 job/import。

API 和 UI 全部为 **1-based**；region 为 **start inclusive、end inclusive**：

```text
API [65, 293] -> length = 293 - 65 + 1 = 229
Python slice [64:293] -> 同样包含 229 个残基
API [1, 1] -> length = 1
```

`Region` 的 length 是派生字段，不能由调用方随意填写。非法零坐标、逆序、浮点数、
布尔值及空 Python 半开区间被拒绝。外部服务若用其他约定，必须在对应 adapter 明确转换。
基础 Region 不持有 sequence_length；当前 LRECA/FuzDrop/SEG 结果契约另外验证 `end <= sequence_length`
及 residue 数组和序列的逐位对齐。FuzDrop 当前官方 native 坐标未通过 live export 验证，导入
要求显式 `one_based_inclusive` 用户声明；不猜测坐标转换，也不重建、去重或过滤 native regions。
详细限制见 [FuzDrop integration](fuzdrop_integration.md)。

SEG 原生 `interval` 为 **0-based inclusive**，parser 对 start/end 各加 1，保留条目顺序和
重复项，不额外 merge 或过滤。该转换由固定版本源码与真实首尾输出共同核实；
来源、回归样例及平台限制见 [SEG runtime](seg_runtime.md)。

## 任务、导入结果与失败隔离

`POST /api/v1/analysis` 校验单序列、所选方法、模式、权重与外部引用，返回 202 和 `AnalysisJob`；
执行由任务服务持有，独立于 HTTP 请求生命周期。`GET /api/v1/analysis/{job_id}` 返回当前快照。
LRECA 与 SEG 可并发，但每个自动 adapter 的并发调用受独立保护；某一方法失败不会取消另一方法。
默认单方法期限 150 秒、执行期限 180 秒，入队等待另有同样的 180 秒上限。

FuzDrop import 保留原响应字段，并增加 `result_id`、`expires_at`、`validation_status=valid`。
后续请求用 `external_results.fuzdrop.result_id` 引用，不重复传完整导入文本。任务接收前验证
引用存在、尚未过期、序列长度与 SHA256 匹配，随后保留经过校验的独立快照。
缺少引用时方法为 `external_result_required`，不会调用 FuzDrop analyze，也不记为执行故障。
DisMeta 被选中时返回 unavailable/blocked；未选中时不添加相关警告，更不替换 IDR 预测器。

所有所选方法成功为 success；有成功且另有失败或不可用为 partial_success。没有成功时，若有
执行失败则为 failed，否则有待导入的方法为 external_result_required，其余为 unavailable。
因此只选 SEG、只选 FuzDrop 或只选 DisMeta 都有明确结果，不要求运行 LRECA。

## 实验性 weighted ensemble

independent 模式不产生 ensemble。weighted 模式要求同时选择 LRECA/FuzDrop，两者都有成功的
全局分数；权重只允许这两个 predictor，范围 0–1、总和在规定容差内等于 1，不自动归一化。
单一 `EnsembleCalculator` 计算加权和，默认 `ENSEMBLE_THRESHOLD=0.5`，按 >= 阈值生成 P/N。
缺少 FuzDrop 导入或全局分数、任一 predictor 失败时，ensemble 为 unavailable，保留独立结果。
SEG 与 DisMeta 永不参与加权。

当前 `calibrated_score=raw_score` 仅是未校准的兼容字段；加权结果继续标记
`calibration_status=not_calibrated`、`interpretation_status=experimental_weighted_score`，
返回 `score`，不宣称为已校准的 LLPS probability。既有 LRECA/FuzDrop 单方法阈值保持不变。

LRECA attribution、LRECA KDE 与 FuzDrop residue propensity 分别展示，不能逐位平均。
不对剩余权重自动归一化；结构化错误使用安全消息，不返回完整输入、内部路径或异常 traceback。

## 存储生命周期与部署边界

FastAPI lifespan 根据 `DATABASE_URL` 建立 SQLAlchemy engine，并用 Alembic 迁移到 `head`。开发默认
SQLite，生产目标 PostgreSQL。`AnalysisJobService` 依赖 `AnalysisJobRepository` protocol；SQL 实现
持久保存完整 versioned result snapshot，orchestrator 不依赖 ORM。`analysis_job_methods` 支持
method filter，summary score columns 支持轻量 history，完整残基数组只在 detail/export 读取。

新 job 和 FuzDrop import 的保存期由 `ANALYSIS_RETENTION_DAYS` 控制，默认 7 天，从各自创建时固定
计算，不因打开或下载而续期。启动与定期 sweeper 物理清理所有过期 job，包括遗留的 active row；
过期 detail 读取会先提交 job 与 orphan import 删除，再返回 404。瞬时 cleanup 失败只记录异常类型，
并在下一周期重试。主动删除会移除 job、sequence 和 result；关联 import 只有在无其他 job 引用时
才随 job 删除。import 自己到期后
会独立清理，而已接受 job 内复制的 normalized FuzDrop snapshot 保持到 job 自己到期。

未过期终态任务可跨重启读取。开发模式启动时发现 queued/running job 会标记为 `interrupted`；
仍活跃的方法写入 `ANALYSIS_INTERRUPTED` 和 `reason=service_restart`。Production 的 RQ worker
使用有限 retry、RQ heartbeat/abandoned-job recovery、SQL 状态 guard 和 PostgreSQL advisory
execution lock；超时的 running row 会重新排队，重试耗尽后写入结构化 `interrupted`，避免永久 running。

匿名 session token 由浏览器保存并通过 `X-Analysis-Session` 转发；数据库只保存 token SHA256。
history/detail/export/delete 和 import binding 全部按 owner 查询，job ID 不作为独立授权凭据。
开发模式默认最多并发 4 个进程内 analysis tasks。Production 模式默认一个 RQ analysis worker、
一个 LRECA model process、`LRECA_MAX_CONCURRENT_REQUESTS=1`；FastAPI 只创建、查询和导出任务，
不在 HTTP request 内阻塞运行 Grad-CAM。RQ payload 只有 `job_id`，完整序列不会额外复制到 Redis。
`ANALYSIS_MAX_JOBS` 和 `EXTERNAL_RESULT_MAX_ENTRIES` 分别限制全站 job/import 总数；进程锁串行
同一进程的 count + insert，PostgreSQL transaction advisory lock 还串行使用同一 repository 的协作进程。
外部程序或直接 SQL 等非协作写入不遵守该 advisory lock，SQLite 也不提供这项跨进程 admission lock。
完整说明见 [persistence](persistence.md)、[data retention](data_retention.md)、
[export formats](export_formats.md) 和 [orchestrator](orchestrator.md)。

## 运行环境分离

本机已验证：FastAPI 使用 Python 3.12.13；LRECA worker 使用 Python 3.10.19、PyTorch 2.1.1+cu118、
NumPy 1.23.0、SciPy 1.10.1。两套依赖隔离，科学计算通过私有 JSON-lines IPC 调用，HTTP API
只返回公开模型身份，不返回内部文件路径。上游参考 Python 3.8.18 与本机环境的区别及 workaround
见 [LRECA runtime](lreca_runtime.md)。

FuzDrop unavailable adapter 和 parser 使用后端现有依赖，不需要浏览器、CUDA 或 Windows 专属库，
没有新增包。三项 FuzDrop 配置均来自后端环境，不能设置任意远程提交 URL。生产代码使用
`pathlib.Path`；未来 Linux/Docker 必须重建目标平台依赖并实测，本轮未构建镜像或部署服务器。
LRECA 核心 inference 不需要重写，只需容器化与改变部署边界。

SEG 独立调用 NCBI BLAST+ 2.17.0+ 发行包的 `segmasker`；API 分别保存 Package
`version=2.17.0` 与 `application_version=1.0.0`。配置 `SEG_EXECUTABLE_PATH` 默认为命令名
`segmasker`，经 PATH 发现；也可指定安装路径，没有开发缓存自动回退。固定默认参数为
`SEG_WINDOW=12`、`SEG_LOCUT=2.2`、`SEG_HICUT=2.5`、`SEG_TIMEOUT_SECONDS=10`，
服务端校验正窗口、有限非负阈值和 hicut 不小于 locut；请求不能覆盖参数。

[setup_seg.py](../scripts/setup_seg.py) 可按固定来源安装 Windows x64 或 Linux x64 包，
复用通过校验的缓存，且不修改全局 PATH。本机 ignored `.env` 使用项目内相对路径并从根目录
启动；未来 Linux 可显式配置 `/usr/bin/segmasker` 或独立安装目录。
Windows 官方程序已实跑，Linux/Docker 安装策略已形成，但目标二进制、动态库与镜像尚未实测。
SEG 不需要 Torch/CUDA；每个子进程显式设置 `BLAST_USAGE_REPORT=false`，不记录完整序列、
原始输出或内部路径。详见 [安装、许可与运行边界](seg_runtime.md)。

## PhaSePred 产品参考

本机实际读取了 [PhaSePred 首页](http://predict.phasep.pro/) 与
[官方 Guide](http://predict.phasep.pro/guide/)。Guide 确认四层结构：

1. Protein Information。
2. Prediction / Related Scores。
3. 可缩放的 Protein Feature Viewer（参考站采用 neXtProt feature viewer）。
4. 独立的 Protein Sequence Viewer 与区间高亮。

本项目保留上述信息层级，将方法限定为 LRECA/FuzDrop/SEG/DisMeta，主输入仍为序列。
Module 6 已实现工作区与 Overview/Feature Viewer/Sequence Viewer/LRECA/FuzDrop/Annotations/
Tables/Download 八个分区、基础表格及数据联动接口。Module 7 已实现完整 Feature Viewer，
共享残基位置轴，支持 zoom/pan/brush/hover/cursor 和表格定位。Module 8 已将 Sequence Viewer
占位替换为固定分行的真实序列检查界面，并完成两个 Viewer 与方法表格的受控选择接口。
Module 9 完成结果表格、服务端数据导出和持久 History；历史打开复用保存的科学快照，不重新执行模型。

V1 没有人源蛋白组参考分布，Proteome Context 默认隐藏；不生成 percentile、ranking 或 radar。
Module 7 选用原生 Canvas 2D，Module 8 使用轻量残基 spans，均不增加 ECharts/D3/Plotly。
测试路由 `/dev/feature-viewer` 与 `/dev/sequence-viewer` 仅由服务端
`FEATURE_VIEWER_TEST_MODE=1` 显式启用，否则返回 404；普通业务使用 `0` 或不设置该变量。
独立测试入口清楚标记 Synthetic test data，与正式 mapper 和 Viewer 共用实现，普通工作流不会
加载默认合成结果。性能 harness 不运行科学模型，其应用更新耗时不等于推理或屏幕呈现耗时。

## 模块交付门禁

每个模块都必须：实际运行 → 本模块测试 → 修复 → 报告变更文件、命令、结果和风险 → 停止。
只有得到用户下一步指令后才进入下一个模块。当前门禁为 **Module 10**，不进入任何 Module 11。
当前前端入口为实际 Analysis Workspace。Module 8 冻结边界见
[Module 8 报告](module8_report.md)、[命令记录](module8_commands.md) 和
[变更清单](module8_changed_files.txt)；Module 9 的最终测试数字与端到端证据由本模块验收报告记录，
不在本架构文档中预填未验证结果。
既有后端真实 HTTP 验收入口 [smoke_module5.py](../scripts/smoke_module5.py) 检查真实 LRECA/SEG 任务、
FuzDrop 导入引用及实验性加权结果、DisMeta blocked 路由与目录。0–4 的 smoke 脚本保留为冻结的
历史阶段验收。DisMeta 请求当前不会发送至第三方；
若未来采用远程模式，必须增加经核实的 transport/parser、可靠性/缓存与隐私声明。
当前代码无 DisMeta 额外平台依赖，不代表官方算法已能部署到 Linux/Docker。
Module 10 的容器运行时缺口、命令和部署边界见 [报告](module10_report.md)、
[命令记录](module10_commands.md) 与 [变更清单](module10_changed_files.txt)。Module 5 的结果、命令与改动见 [报告](module5_report.md)、[命令记录](module5_commands.md) 和
[变更清单](module5_changed_files.txt)，DisMeta 接入前提见 [integration](dismeta_integration.md)。
FuzDrop 自动调用仍不可用，手工导入只保证格式与结构
校验，其已完成结论继续为 **MANUAL_IMPORT_ONLY**；详见 [Module 2 report](module2_report.md)。
