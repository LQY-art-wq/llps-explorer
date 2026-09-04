# FuzDrop 接入与手工结果导入

Module 2 的最终模式为 **`MANUAL_IMPORT_ONLY`**。FuzDrop 自动调用的
`integration_mode=browser_protected`、`available=false`；本网站不会自动向官方提交序列。
用户可以自行在 [官方 FuzDrop](https://fuzdrop.bio.unipd.it/predictor) 完成预测，再把结果交给
本站的纯本地 parser。当前范围是严格处理已审核的官方 TSV 格式，不是抓取结果网页。

**来源仅由用户声明，本站未认证其确实由官方生成。** 本轮没有提交预测，也没有取得真实结果
下载。格式依据来自官方论文及本轮重新 GET 的公开导出实现；测试中的合成格式样本明确不是
真实 FuzDrop 预测。调用能力 A–F、资源哈希与来源见 [外部服务审计](external_services.md)。
机器可读证据保存在 [访问审计](audit/fuzdrop/service_audit.json) 和
[导出格式审计](audit/fuzdrop/export_format_evidence.json)。

## 为什么自动预测不可用

官方网页当前先执行 reCAPTCHA v3，再通过 JSON POST 发送 protein 与 captcha token。
虽然公开前端可见 POST 地址，本次未确认面向第三方、免 CAPTCHA 的 documented API 或
supported HTTP service。GET 没有 Set-Cookie 也不能证明提交无认证；cookie/session、配额和
远程 batch 访问仍未核实。不推断全互联网不存在 API，也不把这个受保护的网页接口接成后台调用。

MODE C 的 load、healthcheck、analyze 均不发外部网络请求。analyze 返回结构化 unavailable，
不生成分数、不抛出服务器 traceback；手工导入不改变自动 availability。官方具有全局、残基及
区域输出能力，与本站当前不能自动计算是两个不同属性。

当前不提供虚构 API key 配置，也不实现外部 HTTP 重试、连接池或结果缓存。无需等待新的用户
审批才能使用已授权的 unavailable/manual boundary。没有下载或安装官方本地程序，没有实现
前端、验证码自动化、替代 FuzDrop 算法或 ensemble，也没有改变 LRECA 科学实现。

## 本站接口与配置

所有路径都属于本站后端，与官方提交地址无关：

| 接口 | 当前行为 |
| --- | --- |
| `GET /api/v1/methods/fuzdrop/health` | HTTP 503；`status=unavailable`、`mode=C`、`integration_mode=browser_protected`、`available=false`，同时提供 `manual_import_available` 和官方页面链接 |
| `POST /api/v1/methods/fuzdrop/analyze` | JSON 仅接受 `sequence`；有效序列返回同类 HTTP 503，`reason=official_service_requires_browser_verification`、`error.code=FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE`，科学数值为 null |
| `POST /api/v1/methods/fuzdrop/import` | JSON 接受下方导入字段；成功 HTTP 200，`status=success` 仅表示本地解析和契约校验通过 |
| `GET /api/v1/methods` | FuzDrop 保持 `available=false`，列出官方输出能力 `global_score`、`residue_propensity`、`regions` 及手工导入是否开启 |

服务级 `GET /api/v1/health` 是本站存活检查，不代表 FuzDrop 可以自动预测。
导入字段、格式、坐标或数值无效时返回 422；超过本地大小限制返回 413
`FUZDROP_IMPORT_TOO_LARGE`；管理员关闭导入时返回 503 `FUZDROP_MANUAL_IMPORT_DISABLED`。
意外解析错误返回 500 `FUZDROP_IMPORT_FAILED` 和安全消息，内部异常留在服务器日志。
请求 schema 错误分别使用 `FUZDROP_INVALID_IMPORT_REQUEST` 与
`FUZDROP_INVALID_ANALYZE_REQUEST`，不回显完整序列、TSV 或额外输入字段。
接口和字段的可执行契约见 [API](../backend/app/api/fuzdrop.py)、
[schema](../backend/app/schemas/fuzdrop.py) 与 [parser](../backend/app/services/fuzdrop_import.py)。

| 后端环境配置 | 默认值与作用 |
| --- | --- |
| `FUZDROP_OFFICIAL_SITE_URL` | `https://fuzdrop.bio.unipd.it/predictor`；只允许配置为该官方 predictor URL 或同域根 URL，作为用户访问链接，不是可调用 API |
| `FUZDROP_MANUAL_IMPORT_ENABLED` | `true`；控制手工导入入口，不开启自动预测 |
| `FUZDROP_IMPORT_MAX_BYTES` | `5242880`（5 MiB）；本地导入大小保护，不是 FuzDrop 科学序列长度限制 |

原始序列和 TSV 的 UTF-8 文本大小受 parser 校验；HTTP 入口还会检查声明的 Content-Length，
因此 JSON 的包装开销也可能触发限制。这不是流式上传限制或官方配额；生产入口可另设请求体上限。

## 手工准备的数据

在官方结果页，用户可通过 Download 保存两种 TSV：

| 输入 | 精确表头/内容 |
| --- | --- |
| `scores_tsv` | `position`、`residue`、`pDP`、`Sbind`，以制表符分隔 |
| `regions_tsv` | `type`、`start`、`end`，以制表符分隔；类型为 `Droplet-promoting region` 或 `Aggregation hot-spot` |
| 可选 `pLLPS` | 从同一结果页另外复制的全局数值；**不在上述 TSV 文件中** |
| `sequence` | 与官方结果对应的同一条完整蛋白序列，供位置/AA 核对 |

官方 [2022 NAR 论文的 Download options](https://academic.oup.com/nar/article/50/W1/W337/6591523)
描述这两种 TSV 下载；当前 [官方 bundle](https://fuzdrop.bio.unipd.it/main-es2015.7255cef9dd5f54e0fbb1.js)
给出精确表头和字段拼接。本站只解析提交的文本，不打开用户 URL 或请求官方服务器。

`FuzDropImportRequest` 的字段如下：

| 字段 | 要求 |
| --- | --- |
| `sequence` | 必填；规范化后仍必须为一条标准氨基酸序列 |
| `source_declaration` | 必填，固定为 `official_fuzdrop_export`；这是用户声明，不是认证凭据 |
| `coordinate_system` | 必填，固定为 `one_based_inclusive`；用户确认所提供数据采用此坐标制 |
| `scores_tsv` | 可选的原始 TSV 文本 |
| `regions_tsv` | 可选的原始 TSV 文本 |
| `pLLPS` | 可选，有限的 0–1 数值 |
| `retrieved_at` | 可选；若提供必须带显式时区。未知时保持 null，不以导入时间代替 |

scores TSV、regions TSV 或 pLLPS 至少提供一项实际内容。文件支持 UTF-8 BOM、LF 和 CRLF。
数据列必须匹配审核格式；官方导出实现对缺失数值可写出字面量 `undefined`，parser 将其与
空白数值单元均保留为 null，不填 0。pDP 必须有限且在 0–1；Sbind 必须为非负有限值，
不能按概率限制到 0–1。

提供 scores TSV 时，残基位置必须完整、顺序为 1..N，AA 与规范化序列逐位相同。重复、缺失、
乱序、残基不匹配或非法分数均返回结构化错误；不通过排序、裁剪、插值或重新归一化修复。

区域要求整数 `1 <= start <= end <= N`，公开坐标为 **1-based inclusive**，长度为
`end-start+1`。保留导入标签、顺序及重复条目；不做最短长度过滤或从 pDP 重新分段。
未提供 regions 文件为 null；提供只有正确表头的空 regions 文件为 `[]`，两者含义不同。

本轮尚未用真实机器输出确认官方 native `position/start/end` 的坐标基准。当前通过显式用户
声明和严格边界/AA 校验接受满足上述契约的数据，不宣称所有官方输出版本天然满足该约定，
也不自动猜测 0/1-based 或 inclusive/exclusive 后执行 +1 修复。

## 分数与区域的科学含义

| 数据 | 本站保留的语义 |
| --- | --- |
| 全局 pLLPS | `model_prediction`：自发 droplet formation/LLPS 的预测倾向。按官方 **pLLPS >= 0.60** 映射 P；N 只表示未达到 droplet-driver 阈值，不排除 droplet-client 或特定条件下的 LLPS |
| 残基 pDP | 返回在 `residue_propensity[].score`，`score_name=pDP`、`semantic_type=residue_propensity`：残基参与 droplet interactions 的倾向。不是 contribution、attribution、Grad-CAM，也不与 LRECA 归因直接合并 |
| Sbind | binding-mode diversity/context-dependence；不是 LLPS probability，不能代替 pDP |
| DPR / aggregation hot-spot | `region_prediction`；保持两种官方类型，不把聚集热点与 droplet-promoting region 合并 |

每个残基保留 `position`、`aa`、`score` 和 `Sbind`；Sbind 的字段说明为
`Sbind_semantics=binding_mode_entropy`。区域的统一 `type` 分别为
`droplet_promoting_region` 与 `aggregation_hotspot`，`official_type` 同时保留 TSV 原标签
`Droplet-promoting region` 与 `Aggregation hot-spot`。这个名称映射不改变区域坐标、顺序或数量。

pLLPS 存在时 `raw_score=calibrated_score=pLLPS`，`calibration_status=not_calibrated`，阈值为
0.60、比较符为 `>=`。pLLPS 缺失时 raw/calibrated/label/threshold/比较符均为 null。
不得从 pDP 均值、最大值、区域长度或覆盖率生成全局分数。[官方全局与残基定义](https://academic.oup.com/nar/article/50/W1/W337/6591523)。

当前 Tutorial 对 DPR 写连续至少 5 个 pDP≥0.60 残基；2022 论文正文、Figure 2、Table 1 写至少
10 个；当前图形代码又使用 `end-start>=10` 过滤蓝条，而 TSV 导出没有该过滤。这些差异尚未
得到统一的服务版本解释。因此本站保留导入区域，不按教程、论文或图形规则重建/过滤结果。
[官方 Tutorial](https://fuzdrop.bio.unipd.it/tutorial)、[NAR 论文](https://academic.oup.com/nar/article/50/W1/W337/6591523)、
[当前公开实现](https://fuzdrop.bio.unipd.it/main-es2015.7255cef9dd5f54e0fbb1.js)。

## 来源、时间与许可

结果来源明确为 `manual_import_of_official_result`，`origin_verification` 与
`coordinate_verification` 均为 `user_declared_not_independently_verified`。
`service_version` 未核实时为 null。
服务器生成 UTC `imported_at`；用户提供的 `retrieved_at` 与导入时间分开。`runtime_ms` 仅表示
本地导入解析耗时，`runtime_scope=local_import_parsing`，不是官方推理耗时。

`sequence_sha256` 对规范化序列计算；`raw_tsv_sha256` 保留原始 UTF-8 文本哈希，包括 BOM 和
换行差异，用于追溯用户提供的输入，不用于声称结果已经官方签名或认证。测试 fixture 的名称及
说明明确标注 synthetic format，不把 parser 正确性包装成 live official prediction 通过；见
[fixture 说明](../backend/tests/fixtures/fuzdrop/README.md)。

当前官方结果页将 predicted data 标为 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)。
本站记录这一来源许可标识；这不是对具体使用情形的法律结论，也不是自动提交授权。论文许可和
作者本地软件许可不能替代该数据标记。[官方结果模板来源](https://fuzdrop.bio.unipd.it/main-es2015.7255cef9dd5f54e0fbb1.js)。

## 未来 A/B 接入条件

只有官方明确提供可支持的程序契约后，才考虑切换到 `documented_api` 或
`supported_http_service`。需要核实 endpoint/method、payload、鉴权、版本、session、输入限制、
配额、许可及真实响应样例；[作者 Contact](https://fuxreiterlab.github.io/contact.html) 是一般联系
渠道，不保证能申请到 API，本模块没有代发邮件。
公共 DTO 预留 A/B/C/D 的模式和对应来源约束；当前 adapter 与 import 执行路径仍固定 MODE C，
不存在通过请求字段或配置切换到自动模式的入口。

未来自动模式才添加后端 `httpx.AsyncClient` 连接池、timeout、响应/schema 校验及有限重试：
connection errors、502/503/504 可以指数退避，429 尊重 Retry-After，400/401/403 不自动重试。
缓存键包含规范化序列 SHA256、FuzDrop、服务模式/版本和参数，结果保存来源与 retrieved_at。
真实远程集成测试应 opt-in，默认 pytest 不访问外站；凭据仅在后端环境，不能暴露给前端或
使用 NEXT_PUBLIC，也不让浏览器直接提交 FuzDrop。

[2026 Nature Protocols](https://www.nature.com/articles/s41596-025-01267-0) 描述的 Linux/macOS
多序列本地程序是另一种部署途径，不是已经可用的远程 API，本模块没有下载或实施它。
当前本地 parser 和不可用 adapter 不依赖 Windows 专属路径；实际 Linux 容器部署仍需目标环境
验证。本模块完成后停止，不进入后续方法或前端模块。
