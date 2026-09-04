# Module 2 — FuzDrop Official Remote Service Integration

审计日期：2026-09-03。最终决策：**MANUAL_IMPORT_ONLY**。

FuzDrop 当前分类为 **MODE C / browser_protected**，本站 **不能自动运行 FuzDrop**。
已实现稳定的 unavailable adapter、方法目录、结构化错误和严格手工导入。手工导入仅验证用户
提供的数据符合已审核的官方格式与本项目坐标契约，不认证数据确由官方生成。本轮没有提交
真实 FuzDrop 预测，也没有取得真实官方结果文件；测试样例均明确标记为合成格式数据。

## 1. FuzDrop official service audit

在 production implementation 前重新检查官方 predictor、help/tutorial、网页明确链接的公开
前端文件、示例、作者联系/软件页、2022 论文，以及 2026 protocol 的公开页面和 supplementary
reporting summary。未将订阅全文视作已读，也未把作者新发布的本地程序当成远程 API。

本轮直接执行 5 次只读 GET：predictor、其 main bundle、help、tutorial、作者 contact。
均返回 200，无 Set-Cookie；这些 GET 不能证明预测 POST 不需要会话或认证。
公开 bundle 为 `main-es2015.7255cef9dd5f54e0fbb1.js`，4,448,622 bytes，SHA256：

```text
4fc6d31326fd0cadf530e50b5f6cdc59d2fa447ef8abaeac079244d07b508124
```

它与 Module 0 记录的 bundle 一致，本轮重新取得其字节后核对提交和导出实现。证据包含 UTC
时间、URL、响应状态、SHA256 及代码字符位置，见 [HTTP observations](audit/fuzdrop/http_observations.jsonl)、
[service audit](audit/fuzdrop/service_audit.json)、[export evidence](audit/fuzdrop/export_format_evidence.json)。
完整资源列表和证据限制见 [external services](external_services.md)。

## 2. Integration mode

| 模式 | 本轮判断 |
| --- | --- |
| A — documented_api | 在已检查官方资料中未确认 |
| B — supported_http_service | 未确认无需绕过验证码的受支持程序化提交契约 |
| **C — browser_protected** | **当前官方页面的提交链路明确依赖 reCAPTCHA v3** |
| D — unknown | 提交流程已有 C 类证据；API 的潜在其他授权途径仍未知 |

公开配置不能把 C 改成 A/B。`available=false` 表示本站无法自动调用；
`manual_import_available=true` 仅表示本地导入入口开启；capabilities 表示官方科学结果可能
包含什么。这三个概念分别表达，不因导入成功将自动 availability 改为 true。

## 3. CAPTCHA findings

公开前端先调用 `recaptchaV3Service.execute`，再在回调中提交 protein 与 captcha token。
序列和 accession 两条提交分支都在该保护流程中。p53/RAF1 示例只填入 accession，不提供
已完成结果的公共下载。该观察来自 [官方 predictor](https://fuzdrop.bio.unipd.it/predictor)
明确链接的 [公开前端文件](https://fuzdrop.bio.unipd.it/main-es2015.7255cef9dd5f54e0fbb1.js)。

本轮未获取、重用或破解 token，没有自动提交受保护请求；没有使用 stealth、Selenium、
Playwright、CAPTCHA 自动化或生产 DOM scraper。FuzDrop 预测提交请求数为 **0**。

## 4. API / HTTP evidence

| 问题 | 证据结论 |
| --- | --- |
| A. Documented API？ | 未确认公开、稳定、可程序化的官方 API 文档 |
| B. 公开 HTTP POST？ | 官方客户端可见 JSON POST，字段为 protein/captcha；它是受保护页面的调用观察，不是可接入承诺 |
| C. reCAPTCHA？ | 当前 UI flow 需要 reCAPTCHA v3 token |
| D. Cookie/session？ | 预测提交的要求未知；匿名 GET 没有 Set-Cookie 不构成反证 |
| E. 免 CAPTCHA documented endpoint？ | 已检查资料中未确认 |
| F. Batch/API 申请渠道？ | 有一般作者 Contact；未确认专门的远程 API/batch 申请契约，未代发联系邮件 |

观察到的受保护地址仅保存在审计资料；production adapter 没有该地址或任何提交 transport。
未探测隐藏路径、试发空 POST、模拟真实预测、测试验证码失败分支或测定限流。
配额、SLA、服务版本和鉴权细节保持 unknown。
[官方 help](https://fuzdrop.bio.unipd.it/help)、[tutorial](https://fuzdrop.bio.unipd.it/tutorial)、
[作者 Contact](https://fuxreiterlab.github.io/contact.html)。

## 5. Automatic integration feasibility

**V1 当前不能自动计算 FuzDrop。** `FuzDropRemoteAdapter.load/healthcheck/analyze/close` 已完整
实现，C 模式不创建 HTTP client，也不执行远程 health probe。合法 analyze 请求返回 HTTP 503，
`status=unavailable`、`reason=official_service_requires_browser_verification`，科学分数为 null。

FuzDrop 生命周期、health 或 analyze 的异常被限制在该方法边界，安全 fallback 仍报告 C 类不可用；
LRECA 启动/关闭和可用性继续独立。手工 TSV 解析运行在本地线程池，不占用 LRECA 的科学 worker。
未来在确认 A/B 契约后可替换 adapter 通信实现，公共 DTO 已预留模式、来源和远程检索时间语义。
当前未执行该未来接口，也未实现 orchestrator 或 ensemble。

## 6. Result schema 与科学语义

| 数据 | 当前规范与限制 |
| --- | --- |
| 全局 pLLPS | `semantic_type=model_prediction`；可选手工复制自同一官方结果页，两个 TSV 均不含该值 |
| 阈值 | 官方 droplet-driver **pLLPS >= 0.60**；P 达到该阈值，N 不等于排除 droplet-client 或条件依赖的 LLPS |
| 未校准分数 | 有 pLLPS 时 raw_score=calibrated_score，calibration_status=not_calibrated；缺失时分数、标签、阈值为 null |
| 残基 pDP | `residue_propensity[]` 含 position、aa、score；score_name=pDP，semantic_type=residue_propensity；不是 attribution/contribution/Grad-CAM |
| Sbind | 独立保留 binding-mode entropy；非负有限值，不按概率限制到 1 |
| 区域 | `type=droplet_promoting_region/aggregation_hotspot`，保留 official_type；semantic_type=region_prediction |
| 坐标 | 1-based inclusive，length=end-start+1；完整残基数组必须逐位匹配 sequence |
| 来源 | manual_import_of_official_result；origin/coordinate_verification 均为 user_declared_not_independently_verified |
| 时间与追溯 | UTC imported_at、可选带时区 retrieved_at、规范化序列 SHA256、原始 TSV SHA256；service_version 未知为 null |
| 耗时 | runtime_scope=local_import_parsing；runtime_ms 不是官方模型推理时间 |

全局/残基定义及阈值来自 [2022 NAR 官方论文](https://academic.oup.com/nar/article/50/W1/W337/6591523)。
本地不计算 FuzDrop 替代分数，不从 pDP 均值或区域覆盖率生成 pLLPS，不将 pDP 与 LRECA 归因平均。

2022 论文写 DPR 至少 10 个连续残基，当前教程写至少 5 个，图形代码又有自己的长度过滤。
TSV 导出直接转发区域列表，没有该图形过滤。因此导入保留条目顺序、重复项和短区域，
不凭其中任何一条规则重建科学结果。差异的证据位置见 [格式审计](audit/fuzdrop/export_format_evidence.json)。

## 7. Error handling 与 API

| 本站接口 | 状态及输出 |
| --- | --- |
| GET /api/v1/health | 200；module=2、version=0.2.0，analysis_enabled 反映 LRECA |
| GET /api/v1/methods | 200；四种方法目录，FuzDrop available=false，科学 capabilities 独立列出 |
| GET /api/v1/methods/fuzdrop/health | 503；unavailable、browser_protected、手工导入开关及官方站点链接 |
| POST /api/v1/methods/fuzdrop/analyze | 503；FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE；不生成科学数值 |
| POST /api/v1/methods/fuzdrop/import | 合法导入 200；格式/声明/数值/序列/坐标错误 422；大小超限 413；关闭导入 503 |

parser 错误细分为 schema change、invalid numeric value、score out of range、residue count mismatch、
invalid coordinate、sequence mismatch、invalid region type 等稳定 `FUZDROP_*` code。
不会回显完整 TSV、额外输入或服务器路径；未知错误采用安全消息，详细诊断只留服务器日志。
接口层不将 FuzDrop 故障传播为其他方法失败。

模式 A/B 的 timeout/429/5xx 等 transport 当前不存在，因而未虚构网络失败测试；未来 adapter 的
公共失败 code 已有保留位置，实际 HTTP 行为必须在获得官方契约后测试。

## 8. Cache strategy

C 模式没有远程请求，**当前不建立远程缓存、retry、连接池或 API key 配置**。
manual import 每次解析用户输入并记录本地导入时间、原始文本哈希，不将其当作官方响应缓存。

若未来确认 A/B，再按用户要求添加后端 cache abstraction：键包括 normalized sequence、fuzdrop、
mode、参数及可用的服务版本；值保留 retrieved_at、版本与 provenance。连接错误/502/503/504
可做有限指数退避，429 尊重 Retry-After，400/401/403 不自动重试。默认测试使用 mock HTTP，
真实远程测试必须 opt-in。这些是未来准入条件，本轮没有提前实现或声称验证通过。

## 9. Manual import strategy

输入须包含 sequence，以及显式的 `source_declaration=official_fuzdrop_export`、
`coordinate_system=one_based_inclusive`；至少提供一个 TSV 或 pLLPS。官方导出表头严格为：

```text
position<TAB>residue<TAB>pDP<TAB>Sbind
type<TAB>start<TAB>end
```

`<TAB>` 在此仅表示实际制表符。格式依据为论文 Download options 和本轮官方公开 exporter。
支持 BOM、LF/CRLF；数值 `undefined`（官方可产生）和空白单元（明确的导入容错）保持 null。
NaN/Infinity、越界分数、不完整/重复/乱序 residue 坐标、AA 不符、越界/反向区域均拒绝。
先精确检查 TSV 十进制数值范围，防止负数或略大于 1 的值经浮点舍入绕过校验。

未提供区域是 null，正确表头的空区域文件是 []。未提供 pLLPS 不推导全局结果。原始文本哈希
保留 BOM/换行差异；导入不排序、去重、裁剪、插值、重新归一化或猜测 0/1-based 转换。
直接调用 parser 时也重新验证已有请求对象，防止来源/坐标声明被修改后绕过契约。

**真实官方导出及原生坐标尚未验证。** 当前要求用户确认数据为 1-based inclusive，并校验
1..N 与序列相符。region-only 输入的起点约定尤其依赖用户声明。新格式或无法确认坐标的数据
不能通过本契约静默修复。详细操作与字段见 [fuzdrop_integration.md](fuzdrop_integration.md)。

## 10. Tests

最终完整后端测试 **241 passed，0 failed，0 skipped，2 warnings，47.36 s**。
两条 warning 来自现有 TestClient/httpx 与 AnyIO 依赖弃用提示；未为消除提示升级依赖。
原始输出私有保存，公开 [test log](audit/module2_full_tests.log)、
[JUnit](audit/module2_full_tests.junit.xml) 与 [验证汇总](audit/module2_test_verification_summary.json)
保留实际结果。

| 测试组 | 通过数 | 主要覆盖 |
| --- | ---: | --- |
| FuzDrop import | 87 | 合法导入、缺失值、精确数值范围、行数/AA/坐标、保留区域、来源声明与对象重验证 |
| FuzDrop API | 30 | Mode C health/analyze、方法目录、导入开关/错误/大小限制、禁用外部 HTTP、故障隔离 |
| 既有 LRECA API | 56 | 公开结果、解释选项、校验、元数据与错误边界 |
| 既有 LRECA scientific integration | 20 | 真实 human checkpoint 推理、Grad-CAM、KDE、CPU/CUDA |
| 既有 LRECA process | 24 | 启动/常驻、超时、取消、故障与清理 |
| 既有 LRECA portability | 7 | 环境路径、模型身份公开字段、Git 权重排除 |
| Module 0 通用契约 | 17 | 更新当前路由/版本，继续检查科学分类与坐标 |
| **总计** | **241** | **全部通过，无跳过** |

API 定向检查另有 **47 passed**（30 FuzDrop API + 17 通用契约）。Ruff 与 compileall 通过。
真正的 Uvicorn TCP 联测同样通过，未以 TestClient 代替该检查：

| 实际 HTTP 检查 | 状态 |
| --- | ---: |
| 服务 health / methods directory | 200 / 200 |
| FuzDrop health / analyze | 503 / 503，结构化 unavailable |
| 合成格式 manual import | 200；45 个残基，原样保留 3 条区域，缺失全局分数为 null |
| 非法坐标 import | 422 |
| 真实 LRECA prediction + Grad-CAM + KDE | 200；248 aa，CUDA，p=0.9999921321868896，主区域 81–127（47 aa） |

完整请求/响应与停止状态见 [HTTP smoke summary](audit/module2_api_smoke/summary.json)。
FuzDrop 数据始终标记为 synthetic format，官方预测提交数 0。LRECA 结果对应原 Human baseline；
新服务和其 worker 已正常关闭。API 公共响应在保存前已通过无开发路径泄露断言。

LRECA 科学源码、checkpoint manifest、科学环境 lock、baseline/解释 fixtures，以及全部既有
`test_lreca_*` 文件均保留原字节。Module 0 测试仅更新版本/路由和取消已不适用的 FuzDrop
PendingAdapter 断言，不改 SEG/DisMeta 占位行为。完整回归继续覆盖真实 prediction、Grad-CAM、
KDE、CPU/CUDA 及进程生命周期；本模块未重做或覆盖 Module 1 baseline/benchmark。

## 11. Production Deployment Readiness

| 项目 | 当前状态 |
| --- | --- |
| Linux portability | FuzDrop runtime 无 shell 调用、文件系统假设、开发用户目录或 Windows 专属库；parser 为纯 Python 数据处理。静态检查通过，Linux 未实测 |
| Docker readiness | 新增部分沿用后端依赖，无浏览器驱动/模型权重需求；本轮未创建镜像或部署，目标容器仍需验收 |
| Python / dependencies | API 本机 CPython 3.12.13；项目声明 >=3.10,<3.14；FastAPI 0.141.1、Pydantic 2.13.5、pydantic-settings 2.15.0、Uvicorn 0.52.4；未增加依赖包，锁文件未改 |
| Configuration | FUZDROP_OFFICIAL_SITE_URL、FUZDROP_MANUAL_IMPORT_ENABLED、FUZDROP_IMPORT_MAX_BYTES；仅后端环境读取 |
| URL / credentials | 只允许官方 HTTPS predictor/root 用户链接；无任意请求目标，无 API key/token；前端没有直接调用或凭据 |
| Import limit | 默认 5 MiB，属于本地运行限制；HTTP 检查声明 Content-Length，parser 检查解码文本 UTF-8 大小。不是流式网关限制或科学长度上限 |
| Lifecycle / isolation | FuzDrop load/close 无远程资源；LRECA 每进程启动一次常驻 worker；FuzDrop 错误不阻断 LRECA |
| Scientific runtime | LRECA 原 Python 3.10.19 / Torch 2.1.1+cu118 / NumPy 1.23.0 / SciPy 1.10.1 保留；CPU/GPU 要求见原运行环境记录 |
| System dependencies | FuzDrop 新增路径仅需现有 Python/后端包，无 OS binary 或 CUDA；将来网络 transport 才涉及 TLS/连接配置；LRECA 的 Git/科学库/GPU 前提维持 Module 1 |
| Future service boundary | FuzDrop HTTP、schema、local parser、adapter 分离；LRECA 核心 inference 无须重写，只需容器化和改变部署边界 |

两套环境、Windows 安装 workaround 和 Linux/GPU 限制详见 [lreca_runtime.md](lreca_runtime.md)。
本轮没有购买服务器、配置域名/Nginx/Kubernetes，也没有将 Windows venv 当作 Linux 环境。

## 12. Unresolved issues

- 未确认受支持的官方自动 API、远程 batch 申请约定、预测 session/配额/SLA。
- 没有真实 FuzDrop 导出或预测，不能宣称 live integration 或官方结果准确性已验证。
- native coordinate origin/inclusivity 仍需真实导出验证；当前人工声明和严格检查不等于来源认证。
- DPR 的教程、论文和图形过滤存在差异，未确认对应服务版本；通过保留 native 数据避免本地猜测。
- 官方 predicted-data 页面标记 CC BY-NC-SA 4.0；本项目保留该来源标记，未将其视为 API 授权。
- Linux/Docker 实际运行留待 Deployment Module；manual parser 不包含持久化、流式上传或复杂 UI。
- LRECA Module 1 已列明的 dataset5 编号、KDE 限制、未校准等科学边界保持原样。

## 13. Recommendation 与停止边界

**采用 MANUAL_IMPORT_ONLY。** V1 可展示 FuzDrop 的官方站点链接及手工导入入口，同时明确
Automatic access currently unavailable。导入结果单独展示 global pLLPS、residue pDP 与 native
regions，并显示来源/坐标仅由用户声明。自动模式必须等待可支持的官方调用证据。

Module 2 完成后停止。未实现 Module 3 SEG、DisMeta、orchestrator、ensemble、分析前端或部署。
最终差异以 Module 2 开始时的 114 文件快照为基准：**44 个文件，新增 32、修改 12、删除 0**。
58 个受保护的既有文件按 SHA256 验证保持原字节；scoped diff 与 Git whitespace 检查通过，
见 [scope review](audit/module2_scope_review.json)。完整清单见
[module2_changed_files.txt](module2_changed_files.txt)，实际命令与日志见
[module2_commands.md](module2_commands.md)。Git index 未更改；普通 diff 因仓库尚无首次提交而
包含历史骨架，不能拿其总数替代本模块清单。

Module 2 completed.
