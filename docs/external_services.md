# 外部服务审计（Module 2 FuzDrop / Module 4 DisMeta）

审计日期：2026-09-03（Asia/Shanghai）。Module 2 重新核对了 FuzDrop 的官方页面、公开脚本、
Help/Tutorial、论文与补充资料，并建立不可自动调用、仅本地手工导入的边界。没有提交蛋白序列、
发送邮件、处理验证码、登录、探测隐藏接口或绕过限流；也没有下载或安装 FuzDrop 本地程序。

本轮 FuzDrop GET 时间、状态、哈希见 [Module 2 HTTP 观察](audit/fuzdrop/http_observations.jsonl)，
对应的 [服务审计](audit/fuzdrop/service_audit.json) 与 [导出格式审计](audit/fuzdrop/export_format_evidence.json)
提供逐项结论和公开脚本锚点。缓存位于被忽略的 `.audit/module2/http/`。
历史 [Module 0 HTTP 观察](audit/http_observations.jsonl)
及 `.audit/http/` 缓存继续保留。Module 4 仅重新审计下方 DisMeta；FuzDrop 第 1 节保留
Module 2 原文，本轮没有重审 FuzDrop。DisMeta 的 [Module 4 服务审计](audit/dismeta/service_audit.json)、
[HTTP 观察](audit/dismeta/http_observations.jsonl)及[科学审计](audit/dismeta/scientific_audit.md)
区分当前检索正文、失败的实时访问和历史方法证据。第 3 节的其他服务仍属历史审计范围。

## 1. FuzDrop：MODE C / MANUAL_IMPORT_ONLY

**最终选择：`MANUAL_IMPORT_ONLY`。** 自动 integration_mode 为 `browser_protected`，
`available=false`，`reason=official_service_requires_browser_verification`；自动分析的
错误码为 `FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE`。
当前网站不自动提交 FuzDrop；支持范围是纯本地解析、验证和标准化用户提供的已审核官方 TSV 格式。
来源仅为用户声明，未认证其确实由官方生成；本轮没有取得真实预测结果下载，也没有提交预测。
具体使用与契约见 [FuzDrop integration](fuzdrop_integration.md)。

这一模式无需再等用户批准或官方开通 API 才能交付。未来取得 API 授权、配额和响应样例属于升级
自动接入的外部条件，不影响本模块完成 unavailable/manual boundary。

### 本轮官方资源与访问证据

[官方 Predictor](https://fuzdrop.bio.unipd.it/predictor) 在 10:31:53 UTC 返回 GET 200，2529 bytes，
SHA256 `980bcc84421cdb06c1e30c07f3b7262e511f17c0db7c572f3ffffabcec84b546`。
其明确引用的 [公开 bundle](https://fuzdrop.bio.unipd.it/main-es2015.7255cef9dd5f54e0fbb1.js)
在 10:32:23 UTC 返回 GET 200，4,448,622 bytes，SHA256
`4fc6d31326fd0cadf530e50b5f6cdc59d2fa447ef8abaeac079244d07b508124`，与 Module 0 完全相同。

[Help](https://fuzdrop.bio.unipd.it/help) 和 [Tutorial](https://fuzdrop.bio.unipd.it/tutorial)
是 SPA 路由，正文证据来自同一官方 bundle 的模板。网页表单由 Angular 提交处理器调用 JSON POST，
不是已确认可独立使用的传统 form-action 接口。当前处理器先运行 reCAPTCHA v3，再构造
`protein`（FASTA）和 `captcha` 字段；观察到的地址是
`https://fuzpred.bio.unipd.it/api/submit_protein`。这些仅为静态审计事实，未调用该提交地址，
也未将它配置成 production API。

| 问题 | 结论 |
| --- | --- |
| A. documented API？ | 在本次检查的官方资源中，未确认面向第三方的稳定、文档化程序接口；不宣称整个互联网不存在任何授权 API。 |
| B. 公开 HTTP POST interface？ | 公开前端可观察到正常网页使用的 JSON POST；它与 reCAPTCHA 流程绑定。仅有 endpoint 不能证明支持第三方自动化，所以不归为 supported_http_service。 |
| C. 需要 reCAPTCHA token？ | 当前已知官方提交流程需要：`recaptchaV3Service.execute` 后将 token 放入 `captcha`。没有尝试无 token 请求、复用 token 或绕过验证。 |
| D. browser session/cookie？ | Predictor/bundle GET 没有 Set-Cookie；提交阶段 session、cookie 及其他认证要求仍未核实，不能据此宣称 POST 无认证或无状态。 |
| E. 无 CAPTCHA 的 documented endpoint？ | 未确认。不存在可据此上线的免浏览器验证程序契约，自动 analyze 保持 structured unavailable。 |
| F. batch/API access 申请方式？ | 未发现远程 batch/API 申请表、key 发放流程或承诺；[作者 Contact](https://fuxreiterlab.github.io/contact.html) 提供一般联系渠道，可以用于未来由用户确认支持方式，本轮未联系。 |

官方网页输入为单条序列/UniProt accession，最少 45 aa；当前没有确认远程最大长度、数值 rate
limit 或 SLA。未做压力测试，未观察到限流不表示无限额。官方例子 p53/P04637、RAF1/P04049
只证明页面提供例子，不证明本项目成功计算过这些例子。

[2022 NAR 论文](https://academic.oup.com/nar/article/50/W1/W337/6591523)明确描述 pDP/Sbind
和区域坐标的 TSV 下载，没有给出可支持本项目自动提交的 API 契约。
[2026 Nature Protocols](https://www.nature.com/articles/s41596-025-01267-0) 的公开 Code availability
说明 Linux/macOS 本地程序支持多序列和 proteomes，指向 [Programs](https://fuxreiterlab.github.io/servers_programs.html)；
这不等于远程 batch/API。该文全文为订阅内容，未声称逐段读过其 protocol/Box 1。
本次实际读取的 [Reporting Summary](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41596-025-01267-0/MediaObjects/41596_2025_1267_MOESM1_ESM.pdf)
仅指向软件/数据来源，没有远程 API 或坐标协议。官方主页的 proteome supplementary 数据入口也是
已发表结果，不是任意批量提交服务。本模块未点击本地程序 I Agree、下载程序或安装 Espritz。

### 科学字段与导入边界

| 字段 | 保留的官方含义 |
| --- | --- |
| 全局 `pLLPS` | spontaneous droplet formation/LLPS 的 model prediction。driver 阈值 **pLLPS >= 0.60**，含等号。产品 P/N 中的 N 仅表示未达到 driver 阈值，不排除 client 或其他条件下的 LLPS。 |
| 残基 `pDP` | 0–1 的 droplet-promoting propensity；统一输出为 `residue_propensity[].score`，`score_name=pDP`，semantic_type 为 `residue_propensity`。不是 contribution、attribution 或 Grad-CAM；不与 LRECA 归因平均或加权。 |
| `Sbind` | binding-mode diversity/context-dependence，客户端使用 `Shae` 字段；不能称为 LLPS probability。 |
| DPR | 官方 droplet-promoting region，semantic_type 为 `region_prediction`；保留实际导入的原生区域，禁止从 pDP 重建后冒充官方区域。 |
| aggregation hot-spot | 与 DPR 不同的区域类型，不能混为同一标签。 |
| 校准/缺失 | 未做本项目概率校准。只有 pLLPS 存在才可 identity passthrough；缺失保持 null，不从残基分数、覆盖率或区域长度补算全局分数。 |

官方 residue TSV 表头为 `position / residue / pDP / Sbind`；region TSV 为 `type / start / end`。
**pLLPS 不包含在这两类 TSV 中**，只可从同一官方结果另行复制为可选输入。
论文和当前模板支持字段含义/导出格式，但本轮未得到真实结果文件验证所有机器值和坐标。
导入来源未认证，原生坐标基准未被实测确认；当前契约要求显式声明 1-based inclusive 并做逐位
AA、位置和边界校验，不自动猜测或 +1 修复。缺失文件与明确空区域列表必须区分。

DPR 长度存在三种证据，必须同时记录：

- 当前 Tutorial 写连续至少 **5** 个 pDP≥0.60 残基。
- 2022 NAR 正文、Figure 2 与 Table 1 都写连续至少 **10** 个；不只是 client 判据才用 10。
- 当前图形 DPR 过滤是 `end-start>=10`，而 TSV 导出直接保留全部 native regions，没有该过滤。

三者不能强行合并。导入既不采用教程或论文阈值重新分段，也不按图形可见蓝条或长度过滤删除
官方 TSV 条目。API 区间只有在声明并校验 1-based inclusive 后按 `length=end-start+1` 派生长度。
统一区域 `type` 为 `droplet_promoting_region` / `aggregation_hotspot`；`official_type` 保留
原 TSV 标签，名称映射不改变区域内容。

当前结果页标记预测数据为 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，
应保留来源与该许可标识。这是官方显示的标记，不是本项目对具体使用情形的法律结论，
也不是自动调用授权；论文自身与本地软件的许可不能替代该数据标记。

### 当前可靠性与未来自动接入条件

MODE C 的 load/healthcheck/analyze 不访问外站；analyze 返回结构化不可用，手工 import 只处理
本地输入。当前不实现外部 HTTP 重试、连接池或结果缓存，也不提供虚构的已可用 API key 配置。
默认测试不访问真实 FuzDrop，合成格式测试不标成 live official prediction。

未来只有确认 A/B 后才添加后端 `httpx.AsyncClient` 连接池、明确的 timeout 和响应校验；
connection errors、502/503/504 可有限指数退避，429 尊重 Retry-After，400/401/403 不自动重试。
缓存键需包含规范化序列 SHA256、方法、服务模式/版本和参数，并保存响应来源及 retrieved_at。
需要的凭据只放后端环境，不使用 NEXT_PUBLIC，也不让浏览器直接访问 FuzDrop。

自动升级还需官方提供可支持的契约、验证码之外的授权机制、使用范围、配额、输入限制及真实
响应样例；这些是未来外部条件。本模块不为此发邮件，不安装本地替代程序，不实现前端、
ensemble 或其他方法。FuzDrop 不可用不得影响已经工作的 LRECA。

## 2. DisMeta：MODE F / UNKNOWN，INTEGRATION_BLOCKED

确认的是 Huang / Acton / Montelione 的 **DisMeta**，不是 Rostlab 的 MetaDisorder、
GeneSilico MetaDisorder 或 metapredict。名称相近的搜索结果不作为替代实现。

来源：[实验室软件页](https://montelionelab.chem.rpi.edu/index.php/our-software-2/)、
[当前官方表单](https://montelionelab.chem.rpi.edu/dismeta/)、
[官方参考文献](https://montelionelab.chem.rpi.edu/dismeta/references.html)、
[方法书章机构记录](https://www.researchwithrutgers.org/en/publications/dismeta-a-meta-server-for-construct-design-and-optimization/)。

**最终分类 MODE F / UNKNOWN；交付决策 INTEGRATION_BLOCKED。** 自动分析和手工导入均为 false。
完成的是独立 unavailable 边界，不要求现在等待用户授权；未来的接入升级需要新的外部依据。
完整 20 项审计、14 项结论及接口说明见 [DisMeta integration](dismeta_integration.md)。

| 项目 | Module 4 审计结果 |
| --- | --- |
| 当前形式 | 官方描述为远程 disorder meta-server / web form；本项目未验证作业成功 |
| 本地程序 / CLI | 未获得可复现的官方 DisMeta 安装包、命令行、固定版本和部署许可；论文中的组件本地安装指官方服务器内部 |
| API / HTTP / batch | 已读官方材料没有给出 DisMeta 文档化 API、明确支持第三方普通 HTTP 提交或 batch 契约；不宣称全网不存在，也不认定官方禁止自动化 |
| 页面输入 | 可检索正文列邮箱、名称/NESG target ID（不超过 10 字符）、letters-only 序列、SignalP organism；服务端校验未确认 |
| 表单与保护机制 | 未取得原始 HTML 或成功提交响应；action、method、session、cookie、JavaScript、CAPTCHA 要求均未确认，不猜 endpoint |
| 当前列出的 disorder predictors | 页面正文列 DISEMBL、DISOPRED2、GlobPlot2、VSL2，并说明默认设置；不把网页名单当作成功运行证明 |
| 历史方法差异 | 本轮读到的 2014 原作者稿索引全文描述 8 个 predictors；历史组成不能替代当前服务版本 |
| 输出形式 | 官方说明各 predictor 结果及逐残基 consensus 图；没有当前真实机器导出、原生 parser schema 或可逐位核验的数值文件 |
| IDR 定义 | 当前共识公式、阈值/比较符、分母、缺失处理、最短长度、merge 规则和机器坐标未知；不自行生成 region/score |
| 本机 HTTP | 主审计 3 次 HTTPS GET 均约 15 秒 ConnectTimeout，无成功 HTTP 状态或原始页面；初始化 SOCKS 配置问题已在审计 helper 局部处理，未关闭 TLS |
| 浏览器 | 打开及随后 AX 读取均工具超时；中间状态仅确认 tab 存在，没有 HTTP/DOM，不能称显示错误页或服务关闭 |
| license / contact | 未取得自动调用、再部署或再分发的明确条款；[官方 Contact](https://montelionelab.chem.rpi.edu/index.php/contact/)仅提供一般联系渠道，未联系 |

原作者稿方法/图注来自 PMC 索引全文；直接打开 PMC 时遇验证页面，未处理验证。
作者出版物页另一次直接 GET 失败的记录见[科学证据](audit/dismeta/scientific_source_evidence.json)，
不计入主审计的 3 条 GET。PMC 验证不证明 DisMeta 自身需要 CAPTCHA；连接超时也不能证明全球停服。
本轮 0 sequence submission、0 email，没有真实 DisMeta 预测或导入结果。

本地 health/analyze 不访问外站，返回 HTTP 503 的 `DISMETA_UNAVAILABLE` 分析边界；
未注册 import 接口。未计算的 regions/coverage/count 等保持 null。`DISMETA_OFFICIAL_SITE_URL`
只允许官方 `/dismeta` 根 URL（末尾斜线可选），不能通过配置开启 ready。
未来 1-based inclusive、union coverage 等仅是规范化 DTO 合同，不是已确认的 native parser。
当前没有 remote client、retry/cache 或新增 DisMeta runtime 依赖，也没有 Linux/Docker 部署验证。
DisMeta 只属于 IDR annotation，不输出 P/N、不参与 ensemble，也不替换成其他 predictor。

## 3. 证据的实际覆盖

- LRECA：官方仓库 clone 成功，固定 commit，源码/依赖/7 个 checkpoint 文件已读取或做哈希核验。
- FuzDrop：首页和其明确引用的前端 bundle 成功 GET；依据静态前端确认请求形状与验证码依赖。
  浏览器读取曾超时；没有声称浏览器提交成功，更没有服务端成功响应。
- DisMeta（Module 4）：官方正文和原作者稿索引全文可读；主审计 3 次 HTTPS GET 均连接超时，
  浏览器也未取得 HTTP/DOM。未提交作业、未取得原生导出，结论为 MODE F / INTEGRATION_BLOCKED，
  自动分析与手工导入均未启用。
- PhaSePred：首页及 Guide 可从本机 GET，Guide 明确描述四层信息结构；示例结果页请求超时。
- 服务审计失败不会被标为“模型测试失败”，骨架通过测试也不会被标为“外部服务已接通”。
