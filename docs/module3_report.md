# Module 3 — SEG Low-Complexity Region Annotation

本模块把真实 **NCBI segmasker** 接入独立后端接口，输出 **Low-complexity Regions (LCR)**。
SEG 仅作 `region_annotation`，不产生 LLPS probability、P/N、归因或 ensemble 分数。
沿用 Module 1 LRECA 真实推理与解释，以及 Module 2 **MANUAL_IMPORT_ONLY** 边界。
本模块不实现 DisMeta、orchestrator、分析前端或正式部署。

## 1. SEG implementation

采用 [NCBI BLAST+ 2.17.0+ 官方发行包](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/)
内的标准 `segmasker`，没有重写 SEG 算法，没有修改 `external/lreca`。
Windows x64 官方二进制已经实际运行；先保存真实 stdout，再实现严格 parser。
来源、archive/executable SHA256、安装成员和运行状态保存在
[external/seg-source.json](../external/seg-source.json)。二进制、DLL 和下载缓存只在 Git 忽略的
`.tools/seg` 中，不进入本项目版本控制。

调用边界为 `HTTP route → SEGAdapter → SEGProcess → official CLI`，返回后由独立 parser
构造科学 DTO。`SEGAdapter` 继承 `BaseAnalysisAdapter`，实现 load/healthcheck/analyze/
predict_regions/close。load 检查可执行文件和版本；SEG 不需要 ML model load。
超时、执行失败或 SEG 启动失败不阻断独立 LRECA/FuzDrop 接口。

## 2. Version and identity

实际 Windows `-version` 输出为：

```text
segmasker: 1.0.0
 Package: blast 2.17.0, build Jul  1 2025 08:57:20
```

发行包名称含 `2.17.0+`；API 分开返回 `version=2.17.0` 与
`application_version=1.0.0`，两者均在运行时检查。Windows executable SHA256 为
`82f56232e2acf9a4ad3cd84efc6abd7387c1781f3b2f6727b9b1f12158c2381c`。
文件状态没有变化时复用 SHA256；health 仍执行轻量 `-version`，不运行长序列。
原始 help/version 与八份实际输出见 [fixture 说明](../backend/tests/fixtures/seg/README.md)。

## 3. License and source audit

发行包 LICENSE 声明 NCBI PUBLIC DOMAIN / United States Government Work，附免责和引用作者说明。
安装保留 LICENSE、README、BLAST_PRIVACY 等同包材料，不把此条款扩展解释为所有第三方库的统一许可。
固定 2.17.0 source ZIP 已实际下载、核对官方 MD5，并对七个审计成员计算 SHA256。
没有用随时间更新的网页源码替代固定发行源码，详见
[逐行源码审计](audit/seg/source_audit.md) 和 [source manifest](audit/seg/source_manifest.json)。

## 4. Invocation, privacy and lifecycle

```text
segmasker -in - -out - -infmt fasta -outfmt interval -window 12 -locut 2.2 -hicut 2.5
```

实际调用是参数列表形式的 async subprocess，不使用 shell。统一 validator 先解析单条 FASTA、
去空白、转大写并验证标准 20AA；传入子进程的是固定 `>query` 标题和标准化序列，序列只经 stdin。
用户标题不进入子进程，序列不进入 argv；生产调用无共享/永久 FASTA 临时文件。
每次注释启动轻量 CLI，模型加载一次的要求继续适用于独立 LRECA worker，不适用于无模型的 SEG。

每个子进程显式设置 `BLAST_USAGE_REPORT=false`，依据
[NCBI 官方 usage-reporting 文档](https://www.ncbi.nlm.nih.gov/books/NBK569851/)，不修改全局环境。
stdout/stderr 在进程内处理，公共 API 不返回原始输出、内部路径或完整输入。
生产错误日志仅含错误类型与固定 code；超时、请求任务取消、应用关闭均回收自己的子进程。
原始 fixture 和 smoke 请求只作为明确的开发测试证据保存。

## 5. Parameters and configuration

| 环境变量 | 默认值 | 验证及作用 |
| --- | --- | --- |
| `SEG_EXECUTABLE_PATH` | `segmasker` | PATH 命令或显式路径，使用 pathlib |
| `SEG_WINDOW` | 12 | 正整数，符合 native integer 范围 |
| `SEG_LOCUT` | 2.2 | 有限非负数 |
| `SEG_HICUT` | 2.5 | 有限非负数，且不小于 locut |
| `SEG_TIMEOUT_SECONDS` | 10 | 正的进程执行时间限制 |

12/2.2/2.5 同时由实际 `-help` 和固定源码确认。输入 `fasta`、输出 `interval`、
`parse_seqids=false` 保存在结果 parameters。官方内部 `period=1`、`hilenmin=0`、
`overlaps=FALSE`、`maxtrim=50`、`maxbogus=2` 保持原样，不增加自己的算法开关。
前端没有高级参数表单；请求不允许覆盖这些服务端配置。

## 6. Coordinate mapping and regression fixtures

实际原始格式为标题后逐行 `start - end`，坐标是 **0-based inclusive**。
API 对两端各加一，统一为 **1-based inclusive**，`length=end-start+1`，且 `1 <= start <= end <= N`。
没有区域时原生输出仍有 `>query` 标题；空 stdout、第二条 FASTA 记录、错误标题、坏区间或越界
都不能冒充成功。原始 Windows CRLF 字节由 `.gitattributes` 保留；Linux LF 可被解析，
这项格式兼容规则不表示 Linux 已实测。

| 真实 CLI fixture 的输入类型 | API 区间 |
| --- | --- |
| 100Q，明显低复杂度 | 1–100 |
| 标准 20AA 混合，100 aa | 无 LCR |
| N 端 40Q + 混合序列，140 aa | 1–40 |
| 混合序列 + C 端 40Q，140 aa | 101–140 |
| 两端低复杂度、180 aa | 1–40、141–180 |
| 11Q，短于默认 window | 无 LCR |
| 12Q，等于默认 window | 1–12 |
| 既有官方 human baseline 的真实 248-aa 序列 | 72–85、89–119、196–247 |

八份输出均由本机真实标准二进制生成；人工输入仅用于软件行为测试，没有 LLPS 性质声明。
真实序列来自既有 `global_baseline.json` cases[0]，未补造蛋白名称或 accession。
严格回归按 [cases.json](../backend/tests/fixtures/seg/cases.json) 的输出/序列 SHA256 核对。

## 7. Output schema and API

`POST /api/v1/methods/seg/analyze` 接收 `{"sequence":"..."}`；实际序列只能含标准氨基酸。
返回 method/status/annotation_type/semantic_type/implementation/version/application_version、
sequence_length/sequence_sha256、regions、coverage/region_count/longest_region、parameters、
runtime_ms 和 executable_sha256。成功和失败 DTO 都不含 LLPS score、label 或 probability 字段。
完整实际响应见 [真实 SEG response](audit/module3_api_smoke/real_seg_response.json)。

`GET /api/v1/methods` 中 SEG 的 category 为 `annotation`，capabilities 只有 `regions`，
semantic_types 只有 `region_annotation`。按本请求最前面的统一命名要求，display_name 使用
**Low-complexity Regions (LCR)**，方法 name 为 SEG；不采用后文示例中的 `(SEG)` 显示名。
独立 `GET /api/v1/methods/seg/health` 就绪为 200，不可用为 503。

| 错误 | HTTP / 语义 |
| --- | --- |
| 非法/空序列、非法请求 | 422；复用统一 sequence validation，隐藏请求正文回显 |
| `SEG_EXECUTABLE_NOT_FOUND` / `SEG_UNAVAILABLE` | 503 unavailable |
| `SEG_EXECUTION_FAILED` | 502 failed |
| `SEG_TIMEOUT` | 504 failed |
| `SEG_PARSE_ERROR` / `SEG_INVALID_OUTPUT` | 坏 interval 为 502 failed；不支持的版本为 503 unavailable，health 不可用也为 503 |

失败区域和统计为 null；成功且无 LCR 时 `regions=[]`、coverage=0、region_count=0、longest_region=0。
未知异常转换为固定安全错误，不返回 traceback/stderr。服务级 health 的 `analysis_enabled`
沿用 LRECA 就绪含义，各方法是否可用以方法目录及其独立 health 为准。

## 8. Coverage, region count and longest region

coverage = 属于至少一个 LCR 的残基数 / N。统计时对闭区间求并集，正确处理重叠、相邻、重复、
乱序与嵌套；结果限制在 0–1。只为计数求并集，不修改 regions 列表。
官方默认关闭原生合并开关，因此 parser 保留 native 顺序和条目，不擅自 merge 或过滤。
region_count 是保留的条目数；longest_region 是最大条目长度，无 LCR 则为 0。

真实 248-aa 用例的三个区域分别长 14、31、52 aa，union 覆盖 97 aa，
coverage=`97/248=0.3911290322580645`（39.11%），region_count=3，longest_region=52。
这些是 LCR 注释统计，不能转换成蛋白发生 LLPS 的概率。

## 9. CPU runtime

Windows 11 x64、API Python 3.12.13；每种长度预热一次、测量五次，采用相同固定参数。
耗时覆盖启动 CLI、stdin/stdout、解析与 DTO 验证，是端到端 CPU 计时，不是纯算法计时。

| aa | 中位 ms | 最小 ms | 最大 ms |
| ---: | ---: | ---: | ---: |
| 100 | 40.2523 | 36.4321 | 45.1501 |
| 500 | 36.6625 | 36.1793 | 39.5494 |
| 1000 | 39.5880 | 35.6288 | 47.6117 |
| 2000 | 36.7700 | 32.6416 | 37.7158 |
| 5000 | 40.0375 | 38.9433 | 44.1180 |

首次 probe+hash 为 58.0605 ms；本组没有异常随长度增长的耗时。相近总耗时与进程启动成本相符，
没有据此推断 Linux 速度或算法复杂度。SEG 不使用 GPU，LRECA 原 CPU/GPU 测试另行保留。
原始样本、环境和序列哈希见 [performance.json](audit/seg/performance.json)。

## 10. Linux / Docker readiness

| 项目 | 当前结论 |
| --- | --- |
| Linux portability | pathlib、stdin、参数列表和 async subprocess；无个人目录、PowerShell 调用依赖或 Windows 路径解析 |
| Windows-specific behavior | 仅在 Windows 设置标准库 `CREATE_NO_WINDOW`；Linux 跳过此分支，无额外 Windows Python 依赖 |
| Installation | 官方固定 Linux x64 tar + 校验，`setup_seg.py --platform linux-x64 --destination /opt/seg` |
| Executable config | `SEG_EXECUTABLE_PATH` 或受控 PATH；本机 ignored .env 仅写仓库相对路径 |
| CPU / GPU | SEG 为 CPU CLI，不要求 Torch/CUDA；不改变 LRECA 科学 worker 环境 |
| Dependencies | API Python >=3.10,<3.14；本机 3.12.13，现有后端依赖锁未修改；安装 helper 仅标准库 |
| System libraries | Linux x64/glibc 基础镜像、安装时 CA certificates；目标 ELF loader/共享库需实测确定 |
| Future service boundary | HTTP、adapter、process、parser、schema 分离；独立 SEG service 只改变部署/通信边界，无需重写 SEG 核心算法 |

Linux 官方包与 MD5 已核实；没有下载 Linux 大包或运行 Linux executable，其 SHA256 如实保留 null。
[seg_runtime.md](seg_runtime.md) 提供可重复安装、路径配置和 Dockerfile 安装策略片段。
目标镜像仍需检查动态库、版本与真实 fixtures。本模块未构建镜像或正式部署。

## 11. Tests and actual HTTP verification

最终完整后端套件为 **389 passed、0 failed、0 errors、0 skipped，50.32 s**。
两个 warning 来自既有 FastAPI/Starlette TestClient 依赖弃用提示，没有因本模块升级这些依赖。
Ruff 按现有 `backend/pyproject.toml` 配置检查整个 backend/scripts 通过；compileall 和
FastAPI/SEG import 检查通过。完整 [日志](audit/module3_full_tests.log)、
[JUnit](audit/module3_full_tests.junit.xml)、[分组计数及原始证据 SHA256](audit/module3_test_verification_summary.json)
均已保存。

| 测试组 | 通过数量 |
| --- | ---: |
| SEG parser/schema/冻结原始输出回归 | 67 |
| SEG process / 发现、版本、stdin、超时和取消清理 | 20 |
| SEG 真实二进制 integration | 13 |
| SEG API / 配置、错误、隐私、隔离 | 49 |
| 原 LRECA API / real integration / portability / process | 107 |
| 原 FuzDrop API / manual import | 117 |
| 其余通用契约 | 16 |
| **总计** | **389** |

覆盖请求列出的全部 22 类行为：发现/版本、低/高复杂度、N/C 端、多区域、零/非零/重叠覆盖率、
count/longest、1-based/边界/长度、非法/空输入、FASTA、执行失败/缺失/超时及无 shell 注入。
补充检查空 stdout 不能充当无 LCR、窗口整数溢出、构造失败隔离、版本不支持为 unavailable、
伪造统计/内部路径不进入公共 DTO。没有改写原 LRECA/FuzDrop 测试来迎合新实现。

实际 Uvicorn TCP 联测共八项，未以 TestClient 代替该检查：

| HTTP 检查 | 实际结果 |
| --- | --- |
| 服务 health / methods directory | 200 / 200；module=3，SEG available=true 且仅 regions 能力 |
| SEG health | 200；package=2.17.0、application=1.0.0 |
| SEG 真实 248-aa 序列 | 200；72–85、89–119、196–247，coverage=97/248，runtime_ms=48.8101 |
| 高复杂度人工用例 | 200；空区域，三个统计均为 0 |
| 非法序列 | 422；INVALID_AMINO_ACID |
| FuzDrop health | 503；browser_protected，manual_import_available=true |
| LRECA 真实同序列预测 + Grad-CAM + KDE | 200；CUDA，p=0.9999921321868896，归因与 KDE 均为 248 位 |

请求、响应、无路径泄露断言和停止状态见 [HTTP summary](audit/module3_api_smoke/summary.json)。
官方 FuzDrop 提交数为 0；生产日志未包含完整测试序列；本次服务及其 worker 已关闭。
完整回归继续执行原 LRECA CPU/CUDA 科学测试；没有重做或覆盖原 Module 1 性能证据。

## 12. Changed files and preservation

以完成 Module 2 时的 **146 文件快照**为本模块差异基准。完整清单见
[module3_changed_files.txt](module3_changed_files.txt)，具体命令见
[module3_commands.md](module3_commands.md)。版本标识更新为 0.3.0 / module=3。
主要新增 SEG runner/parser/schema/API、真实 fixtures、测试、安装/性能/smoke 工具和审计文档；
公共启动、配置和方法目录仅添加 SEG 所需接线。

最终差异为 **61 个文件：新增 46、修改 15、删除 0**，详见
[scope review](audit/module3_scope_review.json)。61 个变更文件均经过交付检查，85 个本地文档链接有效，
16 个 JSON 与 JUnit 可解析，八份 native interval 和 help/version 原字节保持一致。
**131 个受保护的既有文件按 SHA256 确认保持原字节**，包括 LRECA/FuzDrop 实现、测试、
fixtures、科学锁文件、旧模块报告/审计、前端、DisMeta 和 orchestrator。
另外 15 个既有文件只作 SEG 实现/接线、版本标识与当前文档更新；旧 Module 0 占位断言仅移除
已被真实 SEG 替代的一项，通用 API 版本/路由检查同步更新。
普通 Git diff 与 scoped diff 均已检查；真实 help 原始末尾空行作为已核对字节的格式例外保留，
其余 whitespace 检查通过。Git index 未更改；因仓库尚无首次提交，普通 diff 包含历史 scaffold，
不能把其总数当作本模块改动。

## 13. Unresolved risks and stopping boundary

- Linux/Docker 尚未实际运行；Linux binary SHA256、共享库依赖与跨平台 fixture 一致性留待目标镜像验收。
- 性能记录仅代表本机 Windows CPU 和本组输入；服务当前没有统一队列、并发配额或网关限制。
- SEG 只注释序列低复杂度，不能证明或排除 LLPS；FuzDrop 仍是 MANUAL_IMPORT_ONLY。
- LRECA 的既有科学限制、未校准分数和 FuzDrop 的来源声明限制保持原样，未借本模块扩大结论。

Module 3 的完成门禁为真实 CLI、1-based 区域、原始回归、结构化失败、独立 API、配置化路径、
Linux/Docker 安装文档及完整后端回归。上述门禁均已达到；本模块在此停止，不进入 Module 4。

Module 3 completed.
