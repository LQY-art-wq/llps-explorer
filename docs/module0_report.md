# Module 0 交付报告

日期：2026-09-03（Asia/Shanghai）。范围：Repository / External Service Audit & Project Skeleton。

**Module 0 已完成；停止等待用户确认。没有进入 Module 1。**
骨架可以启动，科学方法均为 unavailable 占位。模型与外部服务的实际推理验证不在本轮完成范围内。

## 1. 初始项目与当前结构

初始工作目录为项目根目录（`${PROJECT_ROOT}`），为空，尚不是 Git repository。
首次 `git status`、`git branch`、`git log --oneline -5` 均返回 not a git repository。
没有既有 frontend/backend、package.json、Python 项目文件、Docker、README 或环境文件可继承。
本轮初始化 `main` 分支，没有创建 commit、remote、PR 或部署；没有删除或覆盖用户既有代码。

```text
.
├── frontend/                       Next.js / React / TypeScript / Tailwind，占位首页
├── backend/
│   ├── app/
│   │   ├── api/health.py            GET /api/v1/health
│   │   ├── adapters/               Base + LRECA / FuzDrop remote / SEG / DisMeta
│   │   ├── services/orchestrator.py Protocol 接口
│   │   ├── schemas/                状态、科学语义、1-based inclusive 坐标
│   │   ├── core/config.py
│   │   └── main.py
│   ├── tests/test_module0.py
│   ├── pyproject.toml
│   └── requirements.lock.txt
├── external/
│   ├── lreca/                      官方固定 commit，本地 checkout，Git 忽略
│   ├── lreca-source.json            已跟踪来源与权重元数据
│   └── README.md                    重建与哈希核验方式
├── docs/                           来源审计、架构、报告与实际验证记录
├── scripts/                        只读来源核验、GET 探测、本地 HTTP smoke check
└── README.md                       安装、启动与测试说明
```

项目依赖隔离在 `.venv/`、`frontend/node_modules/` 和 `.pnpm-store/`；没有改动系统 Python 包。
本机验证 Python **3.12.13**、Node **24.19.0**、pnpm **11.19.0**。
前端 Next **16.3.4** / React **19.2.8**，后端 FastAPI **0.141.1**。

## 2. LRECA repo / commit

- 官方仓库：[ai-phasepro/LRECA](https://github.com/ai-phasepro/LRECA)。
- 固定 commit：`0b4b48ab7870529a34028c6e30dfba42eddbf215`。
- 本地 checkout：`external/lreca/`，来源核验确认无本地改动。
- 源码 MIT；LICENSE 的版权占位符和 README 的第三方材料条款已记录。
- 已实际阅读 README、demo、human inference、匹配模型、训练入口、requirements、Grad-CAM、KDE、wrapper 和结果说明。

完整分析见 [model_sources.md](model_sources.md)。

## 3. Human-specific checkpoint

```text
LRECA_CHECKPOINT=Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt
LRECA_CHECKPOINT_SHA256=aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc
LRECA_MODEL_VARIANT=human_specific_dataset5
```

文件 **2,395,318 bytes**，是 human demo 明确指定的唯一 human 候选。
总共核验 **7 个 checkpoint 文件、6 个不同 SHA256**，以及 **2 个词表来源文件**。
Human 词表已按上游 seed 0/1 的规则重建并记录；模型匹配定义为 embedding=512。

**状态：已下载、来源/哈希已核验，未反序列化、未推理。**
“human → checkpoint”有源码直接证据；“论文 dataset5 = human”的编号关系来自用户需求，
尚缺独立论文/补充材料对照。没有改用 dataset1 或 mydata 权重。

## 4. FuzDrop 分类

**C：browser interaction；HIGH TECHNICAL RISK。**

官网和明确引用的公开前端脚本可读取。前端先执行 reCAPTCHA v3，再提交携带 captcha token
的 JSON POST。没有核实 A 类文档化第三方 API，也没有核实 B 类允许普通程序化提交的服务契约。
本轮没有提交序列、取得验证码 token、绕过认证或限流，也没有实现 DOM scraper。

前端预期字段包括 global `pLLPS`、residue `pDP`/`Shae` 及 native DPR/hotspot regions；
这些是静态客户端证据，尚非本轮成功响应 fixture。最大长度、配额和自动化使用许可仍未知。
官方 2026 方法资料提到本地程序，但本项目继续遵守用户指定的 **remote-only** 范围。
详细 18 项契约与来源见 [external_services.md](external_services.md)。

## 5. SEG 候选

候选为 **NCBI BLAST+ 2.17.0+ 的 segmasker 二进制**，以 subprocess 调用。
参数显式固定 `window=12`、`locut=2.2`、`hicut=2.5`；相关源码为 NCBI public domain notice。
输出为 LCR intervals，不生成 LLPS probability 或 P/N。
官方发行目录和源码已读取；本轮没有下载二进制或执行 SEG。
Module 3 再固定包哈希、验证真实输出和首尾坐标。

## 6. DisMeta 调用方式

确认的是 Huang / Acton / Montelione 的官方 **DisMeta meta-server / web form**。
表单要求 Email、蛋白标识、序列及 SignalP organism。没有获得可靠的本地 CLI、
公开 API、许可与当前机器输出契约。本机直接 HTTP(S) 访问超时，尚未验证作业成功。

**HIGH TECHNICAL RISK**：当前 IDR consensus 阈值、有效 predictor 分母、缺失处理和区间定义未知。
保留 unavailable；没有私自替换 metapredict、IUPred、ESPritz 或 MobiDB。

## 7. Changed files

本轮新增 **51 个项目文件**。完整逐文件清单见 [module0_changed_files.txt](module0_changed_files.txt)。

| 分组 | 变更与作用 |
| --- | --- |
| 根目录 | README、Git ignore/换行规则、Python 版本提示 |
| frontend | 固定版本和 lock、Next.js 配置、TypeScript、Tailwind、环境样例、Module 0 占位页 |
| backend | 可安装 Python package、健康接口、adapter/调度接口、状态与语义、坐标模型、19 项测试、依赖 lock |
| external | 来源清单、固定 commit/checkpoint/SHA256、重建说明；上游源码不合并进本项目 Git |
| docs | 必需的三份审计/架构文档、交付报告、命令/变更清单、checkpoint/词表/HTTP/smoke 证据 |
| scripts | GET-only 审计、上游哈希核验、本地运行检查 |

Git intent-to-add 使新增文本完整显示在 `git diff` 中，可直接审查；没有提交 commit。
`.venv`、node_modules、构建缓存、公开页面缓存与上游 checkpoint 均不进入本项目 diff。

## 8. 实际执行的命令

完整记录、路径和失败处理见 [module0_commands.md](module0_commands.md)。主要操作包括：

- `pwd` / `git status` / `git branch` / `git log --oneline -5`；初始文件与 runtime 检查。
- `git init -b main`；使用 OpenSSL 证书后端 clone 官方 LRECA，再核对 commit 和 SHA256。
- 建立本地 Python 3.12 venv、安装锁定依赖；`pnpm install`、`typecheck`、`build`。
- `pytest`、`ruff check`、`compileall`、`pip check`、`scripts/verify_sources.py`。
- 实际启动 Uvicorn 和 Next.js production server，再执行 `scripts/smoke_module0.py`。
- 浏览器读取本地首页并检查截图；`git diff --check` 和文件清单审查。

## 9. 测试与实际运行结果

| 检查 | 结果 | 验证范围 |
| --- | --- | --- |
| pytest | **19 passed**，2 个上游弃用警告 | package import、可实例化测试 subclass、4 个 unavailable adapter、科学分类、坐标首尾/半开转换/非法输入、health-only API |
| Ruff | **All checks passed** | 本项目 Python 文件；初次发现的导入顺序和长行已修复 |
| compileall | **通过** | backend app/tests 与 scripts |
| pip check | **No broken requirements found** | 当前隔离环境的依赖一致性 |
| frontend typecheck | **通过** | Next route type generation + TypeScript |
| frontend build | **通过** | Next.js production build |
| 本地 HTTP smoke | **4/4 通过** | 后端 health、前端代理 health、真实首页 HTML、仅含 health 的 OpenAPI |
| 浏览器检查 | **通过** | 本地页标题、两类方法分组、四个 Pending、健康链接及截图布局；未发现遮挡/溢出 |
| LRECA 来源检查 | **通过** | 固定 commit、clean checkout、7 个 checkpoint 和 2 个词表文件哈希 |
| git diff --check | **通过** | 新增文件的可审查 diff 与空白检查 |

实际 HTTP 证据见 [smoke_results.json](audit/smoke_results.json)。
健康接口明确返回 `analysis_enabled: false`，测试确认 `/api/v1/analyze` 不存在。
两个弃用警告来自 Starlette 的 httpx TestClient 兼容层与 AnyIO BlockingPortal alias，
没有屏蔽警告；不影响本轮 19 项测试，后续依赖升级时处理。

## 10. 当前风险

1. **LRECA 科学环境未验证**：上游 Python 3.8 / Torch 2.1.1，与本轮 Python 3.12 API 环境不同。
2. **同仓库科学定义不一致**：当前 human 训练脚本为 1024 维，checkpoint 对应测试类为 512 维；
   Grad-CAM demo 默认 mydata，且单序列 `.squeeze()`、固定临时文件和 KDE 短序列边界需要后续处理。
3. **FuzDrop 自动化未获支持契约**：验证码、权限、配额、最大长度、成功响应/坐标尚未固定。
4. **DisMeta 可靠接入未证实**：页面可检索不等于服务器可成功处理作业；当前输出/IDR 定义仍待确认。
5. **许可证与适用范围**：LRECA 源码 MIT 不自动涵盖全部第三方材料；远程服务许可不能从页面可访问推断。
6. **验证边界**：本轮证明工程骨架和来源完整性，不证明模型预测正确、服务生产可用或 ensemble 已校准。

## 11. 需要用户确认的事项与停止点

- **本轮交付确认**：审查 Module 0 后，由用户明确指示是否进入 Module 1。
- **NEEDS USER CONFIRMATION（来源）**：若要求独立核对 dataset5 论文编号，请提供可引用的论文/补充材料；
  当前唯一 human 候选的源码对应关系清晰，已按该候选记录，未换用其他模型。
- **后续接入前的外部条件**：FuzDrop 需要官方支持的自动化方式/许可/配额；DisMeta 需要有效官方契约与真实输出。
  用户可以提供已有资料。本轮不代发联系邮件，也不请求用未经支持的 scraper 替代。

Module 0 以此停止；不运行 LRECA 推理，不继续实现 Module 1–10。
