# DisMeta 接入与当前不可用边界

审计日期：2026-09-03。**Integration MODE F / UNKNOWN；最终决策 INTEGRATION_BLOCKED。**
自动分析和手工导入均未启用：`available=false`、`manual_import_supported=false`。
本模块完成的是可独立失败的本地 unavailable 边界，没有接通 DisMeta 作业服务。
证据见 [服务审计](audit/dismeta/service_audit.json)、[本机 HTTP 观察](audit/dismeta/http_observations.jsonl)
和 [科学审计](audit/dismeta/scientific_audit.md)。

## 官方身份与访问证据

本项目的 DisMeta 是 Huang、Acton、Montelione 的 disorder meta-server，产品名称为
**Intrinsically Disordered Regions (IDR)**。它属于 `region_annotation`，不产生 LLPS 概率、
P/N 或 ensemble 权重，也不以其他 IDR predictor 替代。
[官方软件页](https://montelionelab.chem.rpi.edu/index.php/our-software-2/)和
[官方参考文献](https://montelionelab.chem.rpi.edu/dismeta/references.html)确认方法身份。

检索工具能读取[官方页面](https://montelionelab.chem.rpi.edu/dismeta/)的解析正文：输入包括邮箱、
蛋白名称/NESG target ID（标签要求不超过 10 字符）、letters-only 序列及 SignalP organism 选项。
这不等于取得了可核验的原始表单 HTML，也不证明当前作业后端成功运行。
`form action`、HTTP request method、session、cookie、JavaScript 和 CAPTCHA 要求均未确认。
未猜测 CGI/API 地址，也未尝试提交。

本轮主审计对官方首页、references、lab 软件页各做一次 HTTPS GET，共 **3 次**，均约 15 秒后
`ConnectTimeout`，没有成功 HTTP 响应或状态码。审计客户端初次初始化曾因未使用的
`ALL_PROXY=socks5` 触发缺少 `socksio`；随后仅为审计 helper 显式采用现有 HTTP(S) scheme proxy，
并设 `trust_env=False`，避免初始化未用的 SOCKS 配置。没有安装新包、修改全局环境或关闭 TLS 验证。
该初始化失败不是第四次 HTTP 请求。

Chrome 打开官方页面的工具调用约 36.7 秒后超时；随后状态清单中存在审计 tab，但读取该 tab
的无障碍树又约 34.7 秒后超时。没有取得浏览器 HTTP 状态或 DOM，不能写成浏览器已显示错误页、
服务已关闭或确定无法在其他网络使用。科学同伴另有一次作者出版物页直接 GET 失败，
它不计入上述三条主审计记录，见[科学来源证据](audit/dismeta/scientific_source_evidence.json)。

原作者稿的方法和图注来自本轮 PMC 索引全文；直接打开 PMC 得到验证页面，未继续操作。
这与 DisMeta 自身是否需要 CAPTCHA 是两个不同问题。没有下载原始 PDF 或当前官方结果。

## 20 项审计结果

| 项目 | 结论 |
| --- | --- |
| 1. 官方页面 | 官方 DisMeta 根页面可通过检索工具读取正文；实时作业能力未验证。 |
| 2. 原始论文 | 已读原作者稿索引全文；公开历史应用不能充当本轮计算结果。 |
| 3. documentation | 官网、软件页、references 和原论文可用于身份/历史方法说明；没有得到当前可运行接口契约。 |
| 4. form action | 未确认，未取得原始表单 HTML。 |
| 5. request method | 未确认，不猜 POST/GET 或 CGI 地址。 |
| 6. session | 未确认。 |
| 7. cookie | 未确认；没有成功响应可据以判断 Set-Cookie。 |
| 8. JavaScript | 是否为提交必需条件未确认。 |
| 9. CAPTCHA | DisMeta 自身要求未确认，没有尝试绕过或复用验证。 |
| 10. API | 已读官方材料未提供明确的 DisMeta API 文档或第三方自动调用支持；不宣称全互联网不存在。 |
| 11. CLI | 未确认官方 DisMeta CLI。 |
| 12. local implementation | 未得到可固定版本的 DisMeta 发行包、完整源码/依赖/模型数据清单或部署许可。 |
| 13. batch | 未确认批量提交格式、配额、限流值或批处理契约。 |
| 14. 输入格式 | 网页标签提供邮箱、名称/target ID、序列和 organism；没有核实完整服务端输入校验。 |
| 15. 输出格式 | 说明存在各 predictor 结果及逐残基 consensus 图；未取得当前机器导出文件或 parser schema。 |
| 16. IDR regions | 确认 disorder consensus 用途；当前精确原生区间定义未知。 |
| 17. residue scores | 有逐残基图的说明，尚无逐位可校验的数值文件；范围和概率含义未知。 |
| 18. component predictors | 当前可检索页面列 DISEMBL、DISOPRED2、GlobPlot2、VSL2；历史论文列 8 个，不能当成当前运行组成。 |
| 19. threshold / consensus | 当前公式、阈值/比较符、有效分母、失败组件处理、最短长度和 merge 规则未确认。 |
| 20. Terms / access | 未取得自动调用、本地再部署或再分发的明确条款；也没有据此认定官方禁止自动化。 |

论文所谓本地组件指官方服务器内部安装；未发表的自动构建设计工作也不是可下载的 DisMeta。
论文的在线免费使用描述不等于程序化调用授权。同站其他软件的 API/许可不能转用于 DisMeta。
[官方 Contact](https://montelionelab.chem.rpi.edu/index.php/contact/)提供一般邮箱
`montelionelab@rpi.edu`，没有公开 DisMeta API/batch 申请流程或授权承诺；本轮未联系。

## 分类与当前 API

A LOCAL 缺少可部署官方实现；B DOCUMENTED_API 缺少文档；C SUPPORTED_HTTP_SERVICE 缺少
官方明确支持普通程序提交的依据。现有证据也不能证明 D BROWSER_ONLY 或 E UNAVAILABLE，
所以选择 **F UNKNOWN**。这是一项已完成的接入边界，不要求用户现在提供授权才能交付。

| 本项目接口 | 当前行为 |
| --- | --- |
| `GET /api/v1/methods` | DisMeta 为 `category=annotation`、`integration_mode=unknown`、自动/手工均不可用；`capabilities=["regions"]` 描述目标能力，不表示已有预测。 |
| `GET /api/v1/methods/dismeta/health` | HTTP 503；`audit_mode=F`、`decision=INTEGRATION_BLOCKED`、`reason=integration_contract_unverified`。不访问外站。 |
| `POST /api/v1/methods/dismeta/analyze` | 仅接收 `sequence`；复用统一序列验证后 HTTP 503，`error.code=DISMETA_UNAVAILABLE`。不发送序列。 |
| 请求结构错误 | HTTP 422，`DISMETA_INVALID_REQUEST`；序列错误保留统一 validator 的 code。不会回显整条序列或任意额外输入。 |
| `/api/v1/methods/dismeta/import` | 未注册；没有原生导出契约，不能通过提交自编区域或 coverage 声称得到 DisMeta 结果。 |

Unavailable 结果的 `regions`、`coverage`、`region_count`、`longest_region` 和版本保持 `null`；
不填 `[]` 或 0，因为没有计算不等于不存在 IDR。公开结果只带序列长度和
SHA256 等允许的诊断，不返回完整序列。异常采用固定安全消息，不泄露内部路径或服务诊断。
DisMeta 初始化、health、analysis 或 close 失败不得阻断其他独立方法。

唯一配置为 `DISMETA_OFFICIAL_SITE_URL`，仅接受 `https://montelionelab.chem.rpi.edu/dismeta/`
及不带末尾斜线的同一 URL；用于显示官方来源，不是可执行 endpoint。不存在配置开关可以把
当前模式改成 ready，也没有虚构的 API key、timeout、retry 或 cache 配置。

## 科学契约与验证边界

未来规范化结果的项目约定是 1-based inclusive，`length=end-start+1`；coverage 由所有区域
覆盖残基的 union 除以序列长度，region_count 按返回区域数，longest_region 在已计算且明确无
区域时为 0。union 只用于覆盖率统计，不改变原始区域的顺序、重复或相邻关系。
这些是 **contract-only DTO** 的验证规则，不是已确认的 DisMeta 原生坐标或解析算法。

当前没有 native parser、真实运行 fixture、逐残基数值输出或科学回归测试。合同测试中的区域
仅用于检查坐标、边界和派生统计，不能标为真实 DisMeta 预测。不会从论文图片提取近似边界、
自行设置 0.5/多数票阈值，或把 SignalP/TMHMM/SEG 区域当成 native IDR。
详细依据见[科学审计](audit/dismeta/scientific_audit.md)。

## 14 项交付结论与后续条件

| 问题 | 本模块结论 |
| --- | --- |
| 1. 当前还能否正常使用？ | 官方资料可检索，作业是否可成功完成未知；未证明服务全球关闭。 |
| 2. 本地还是远程？ | 官方描述的是远程 meta-server；本项目当前仅实现本地不可用边界。 |
| 3. 是否允许程序化？ | 未取得明确支持契约或权限说明，不能自动提交。 |
| 4. Integration mode？ | MODE F / UNKNOWN；INTEGRATION_BLOCKED。 |
| 5. 是否需要人工导入？ | 当前不启用导入；真实官方输出格式和来源验证基础仍缺失。 |
| 6. IDR 定义？ | Disorder consensus；当前精确原生分段规则未知。 |
| 7. Residue score？ | 有历史逐残基图说明，没有可验证的当前数值导出。 |
| 8. 坐标？ | 机器导出坐标未知；1-based inclusive 仅为项目未来规范化契约。 |
| 9. 参数/threshold？ | 页面声明默认设置；具体版本、共识阈值和分母等未知。 |
| 10. Performance？ | 无成功预测，典型服务延迟和 CPU runtime 未知；约 15 秒连接超时不是服务计算耗时。 |
| 11. Linux/Docker？ | 当前边界无新增 runtime 依赖、硬编码用户路径或外站客户端；未部署 Linux/Docker，也未验证 DisMeta 本地计算。 |
| 12. Privacy？ | 当前 0 sequence submission、0 email；只记录允许的状态、长度/哈希等诊断。未来远程模式会向第三方发送序列，必须写入网站 Privacy Notice。 |
| 13. 未解决风险？ | 作业可用性、调用支持/条款、组件版本、原生输出和定义均未确定。 |
| 14. Recommendation？ | 保持独立不可用边界，取得支持契约和真实输出后再选择接入路径；更换 predictor 需要用户另行决定，不能冒充 DisMeta。 |

将来若确认 B/C，才增加后端 `httpx.AsyncClient`、timeout、响应验证、有界重试和缓存。
connection failure、502/503/504 可有限指数退避；429 尊重 Retry-After，400/401/403 不自动重试。
cache key 包含规范化序列、方法、参数和 integration mode 的 SHA256，记录 retrieved_at、
服务版本（已知时）及 provenance。真实 integration tests 应 opt-in，默认测试不得访问外站。
若确认 A，需要另行固定 DisMeta 实现、许可、Linux 依赖与模型数据；若确认 D 且取得真实导出，
才设计验证序列身份、原生坐标、区域和 provenance 的手工导入。当前没有实现这些未来组件。
