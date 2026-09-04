# Module 4 — DisMeta IDR Annotation

**最终 integration mode：MODE F / UNKNOWN。最终决策：INTEGRATION_BLOCKED。**
本模块完成官方服务/科学语义重审，以及独立的结构化 unavailable 边界。
**没有宣称 DisMeta 自动预测或手工导入已接通，没有生成任何真实或伪造的 DisMeta IDR。**
网站名称使用 **Intrinsically Disordered Regions (IDR)**，method 为 DisMeta。
DisMeta 不输出 LLPS probability/P-N，也不进入 ensemble。

## 1. DisMeta 当前还能否正常使用？

本轮可通过检索工具读取 [官方表单](https://montelionelab.chem.rpi.edu/dismeta/)、
[软件页](https://montelionelab.chem.rpi.edu/index.php/our-software-2/) 和
[参考文献页](https://montelionelab.chem.rpi.edu/dismeta/references.html)。
从本机对三页进行 HTTPS GET 均在约 15 s 连接超时；正常 Chrome 导航/读取也发生工具超时，
没有获得原始 DOM/HTTP 状态或成功作业。具体记录见 [HTTP observations](audit/dismeta/http_observations.jsonl)。

这些事实不能证明全球服务已停用，也不能证明作业后端仍可用。因此没有选择 SERVICE_UNAVAILABLE，
也没有仅凭表单存在选择 BROWSER_ONLY。当前服务可运行性与接入契约均未得到可靠验证。

## 2. 本地还是远程？

确认的方法是 Huang / Acton / Montelione 的远程 disorder meta-server。
本次成功读取的官方资料没有提供可复现的 DisMeta 本地发行版、CLI、版本化源码/模型清单或安装契约。
论文提到某些组件在官方服务器本地运行，不等于可下载部署整个 DisMeta。
没有安装 metapredict、IUPred、ESPritz、MobiDB 或其他替代方法。

## 3. 是否允许程序化？

没有找到可据以实现的 DisMeta documented API 或明确支持第三方普通 HTTP 提交的说明。
这表示**没有确认支持**，并不宣称官方明确禁止一切自动访问。
原始 form action/method、cookie/session、JavaScript 和 CAPTCHA 条件未核实，未猜测 CGI 地址。
没有因公开表单或无验证码文字就假定无需保护，也没有把同站 RPF 的 SOAP 文档移作 DisMeta API。
许可、再部署和程序调用条款仍未知；一般联系方式不是 API/batch 授权。
20 个具体审计问题及来源见 [integration 文档](dismeta_integration.md) 和
[service audit](audit/dismeta/service_audit.json)。

## 4. Integration mode 与运行边界

| 层次 | 当前状态 |
| --- | --- |
| 审计分类 | MODE F / UNKNOWN |
| 交付决策 | INTEGRATION_BLOCKED |
| API integration_mode | unknown |
| automatic available | false |
| manual_import_supported / manual_import_available | false / false |
| reason | integration_contract_unverified |
| 错误码 | DISMETA_UNAVAILABLE |

`DisMetaAdapter` 实现 BaseAnalysisAdapter 的 load/healthcheck/analyze 和 close；全部为本地操作，
load 后保持 unavailable。analyze 仍复用统一 validator，合法输入返回安全诊断：长度、SHA256、
IDR 语义、固定不可用原因；regions/coverage/region_count/longest_region 均为 null。
这与成功但无 IDR 的 `[] / 0` 明确区分。`predict_regions` 返回 None，不伪造空区域预测。

`GET /api/v1/methods/dismeta/health` 和 `POST /api/v1/methods/dismeta/analyze` 均为固定 **503**
不可用响应；非法序列或请求为 **422**。API 严格重验 DTO 并重建公开响应，不信任自由错误文本或
被篡改的 ready 状态。OpenAPI 不暴露 DisMeta success schema。
方法目录只声明 annotation / regions / region_annotation，不能含 global_score 或 binary_label。
请求前部要求的统一 IDR 显示名优先于后文 `(DisMeta)` 示例。

## 5. 是否需要人工导入？

本轮**不启用导入**，`POST /api/v1/methods/dismeta/import` 不注册（404）。
当前没有可验证的原生结果格式、序列身份字段和 region 数据，不能让用户只交 coverage 或自编
regions 就标成官方预测。未来取得真实原生结果和格式依据后，才能设计来源声明、imported_at、
坐标声明、序列逐位校验及版本/job provenance。FuzDrop 已有导入实现不受此决定影响。

## 6. IDR region 定义

官方说明 DisMeta 汇总多个 disorder predictors 并展示 consensus；没有确认当前可执行的
二值化公式、有效组件分母、缺失处理、最短 IDR 或相邻区间合并规则。
原论文列历史 8 个组件，当前表单只列 4 个，不能混为固定版本。
没有从 SignalP、TMHMM、SEG 或论文构建设计删除片段补造 IDR，也没有采用自设多数票或 0.5 阈值。
历史实例/组件差异和关键解释见 [科学审计](audit/dismeta/scientific_audit.md)。

## 7. 是否有 residue-level score？

官方软件页确认有逐残基 consensus **图**；本轮未取得可逐位核验的原生数值文件、范围或概率定义。
因此 API 没有增加 `residue_disorder_score` 或把共识图解释为 LRECA attribution/LLPS contribution。
论文报告图只能证明历史输出存在，不能冒充当前成功运行的 parser fixture。

## 8. 坐标与区域统计

本项目预留的规范化契约统一 **1-based inclusive**，`length=end-start+1`、`1 <= start <= end <= N`。
coverage 为所有区域覆盖残基的并集大小/N；单独统计并集，保留输入区域的顺序、相邻、重叠和重复项。
region_count 为区域条目数；longest_region 为最大长度；规范化的成功无区域情况三项为 0。

`DisMetaResult` 仅是内部 **contract-only DTO**，用于上述通用坐标/数学契约测试。
没有任何现行 adapter、HTTP 或 import 从它生成成功结果；其测试数字明确是 synthetic contract cases。
当前 native machine coordinate 原点/闭合方式未知，没有实现 +1 转换或 native parser。
论文中蛋白 1–155 的编号解释不能替代机器文件坐标契约。

## 9. 参数与 threshold

当前页面仅说明工具采用默认设置；固定 DisMeta 版本、组件版本与详细参数集合未知。
没有配置或返回猜测的 threshold、共识概率或版本“2014”。2014 是论文年份，不是服务版本。
唯一新增环境配置 `DISMETA_OFFICIAL_SITE_URL` 只允许官方 `/dismeta` 入口（可带末尾斜杠），
用于用户参考链接，不作为提交地址；不存在可把模式切换为 ready 的环境开关。

## 10. Performance

没有可验证的本地 DisMeta 程序或受支持远程预测，因此本轮没有 DisMeta CPU/GPU benchmark
或典型预测 service latency。约 15 s 的 GET ConnectTimeout 只描述审计失败等待时间，不是预测耗时。
HTTP smoke 实测本地固定 503 边界往返 **2.8487 ms**，不能当作 DisMeta 计算性能或官方网络延迟。
原 LRECA CPU/GPU 与 SEG CPU 性能证据保留，未重新生成或覆盖。

## 11. Linux / Docker readiness

新增部分使用现有 Python/FastAPI/Pydantic，不增加外部二进制、模型、浏览器驱动或 Python 依赖。
API 已验证 Python 3.12.13，项目声明 >=3.10,<3.14；原锁文件不变。
核心边界没有 shell、文件路径拼接、个人目录或 Windows-only 运行依赖；配置来自环境。
没有安装 Docker、构建镜像或部署正式服务器。

审计脚本曾因环境中未使用的 ALL_PROXY 为 SOCKS 而缺少 socksio；后改为显式使用已有
HTTP(S)_PROXY，只避开初始化未使用的代理类型。没有新增包、修改全局网络设置或关闭 TLS。
这是本机一次性审计工具的兼容处理，生产 DisMeta boundary 没有 HTTP client，不依赖它。
若未来取得官方远程契约，只需新增独立 transport/parser 并验证目标容器；若取得官方本地版，
其 Linux dependencies/许可/模型文件另行固定，不能把当前状态宣称本地推理已可部署。

## 12. Privacy implications

当前生产边界不会发送任何序列到第三方，不保存 FASTA 临时文件，也不记录完整序列。
本轮官方 DisMeta 提交数 **0**、邮件数 **0**，没有登录、操作验证码或提交邮箱。
本机 HTTP smoke 的明确测试请求/结果作为开发审计证据保存，生产日志另查完整序列泄露。
未来如开放 remote，序列将发送到第三方 DisMeta 服务；必须写入网站 Privacy Notice 并明确其保留/使用政策。
届时 timeout、有限 retry、429 Retry-After、响应验证、schema change 与带来源的缓存才有实际契约基础。
当前不添加不会被调用的远程重试/缓存实现。

## 13. Verification 与 unresolved risks

完整后端门禁 **471 passed，0 failed，0 errors，0 skipped，51.48 s**。
两个 warning 为既有 FastAPI/Starlette TestClient 弃用提示，没有为本模块更新相关依赖。
Ruff 按现有项目配置检查整个 backend/scripts 通过；compileall 及导入检查通过，导入未加载 Torch。
[完整日志](audit/module4_full_tests.log)、[JUnit](audit/module4_full_tests.junit.xml)、
[分组计数和原始/公开证据 SHA256](audit/module4_test_verification_summary.json) 已保存。

| 组别 | 通过数 | 实际范围 |
| --- | ---: | --- |
| DisMeta API | 35 | 503/422、import未开放、隐私、伪造metadata拒绝、生命周期隔离、目录 |
| DisMeta contract | 48 | 不可用输入/生命周期、合成规范化坐标/并集/长度/统计；非真实预测 |
| LRECA | 107 | 原 API、CPU/CUDA真实推理/归因/KDE、portability、进程测试 |
| FuzDrop | 117 | 原 API 与严格手工导入边界 |
| SEG | 149 | 原 parser/process/真实二进制/API；仅一条过期DisMeta目录reason断言更新 |
| 其余通用契约 | 15 | 版本/路由/科学分类/统一坐标；移除不再适用的DisMeta PendingAdapter断言 |
| **总计** | **471** | **全部执行，无skip** |

实际 Uvicorn TCP 联测 **13项**通过，未用 TestClient 代替该检查：

| HTTP 检查 | 实际结果 |
| --- | --- |
| health / methods | 200 / 200；module=4，DisMeta unknown、auto/manual false、annotation/regions |
| DisMeta health / 合法248-aa analyze | 503 / 503；F、INTEGRATION_BLOCKED、DISMETA_UNAVAILABLE，区域统计均null |
| DisMeta 非法输入 / 未开放import | 422 / 404 |
| SEG health / 真实248-aa注释 | 200 / 200；3区域、coverage=97/248，保持冻结回归值 |
| SEG 无LCR / 非法输入 | 200（零统计） / 422 |
| FuzDrop health / 合成格式manual import | 503 / 200；DisMeta不可用后导入仍成功 |
| LRECA 真实prediction + Grad-CAM + KDE | 200；CUDA，p=0.9999921321868896，归因与KDE均248位 |

见 [实际HTTP摘要与响应](audit/module4_api_smoke/summary.json)。所有成功科学结果属于既有 LRECA/SEG；
FuzDrop输入为明确标注的合成格式样例，DisMeta始终没有成功结果。
测试服务与其worker已正常关闭，生产日志未包含完整测试序列，第三方DisMeta/FuzDrop提交数为0。

以完成 Module 3 的192文件快照为基准，本模块 **48个变更：新增34、修改14、删除0**。
178个保护文件按SHA256保持原字节；LRECA/FuzDrop实现与全部tests、SEG科学实现/真实fixtures/其余tests、
前端、锁文件、orchestrator和旧报告不变。SEG API只改一行目录reason，按原字节单次替换结果核对；
外部服务文档FuzDrop section单独验证字节相同。普通Git diff和模块精确diff已检查，whitespace通过，
Git index未改，详见 [scope review](audit/module4_scope_review.json)。

剩余外部条件是官方受支持调用方式、当前成功作业、真实原生导出、sequence identity、机器坐标、
consensus/region 规则、score 数值语义、版本/条款/限流及服务运行条件。
不把单次或本机网络失败扩大为全球停服判断，也不把 contract-only 测试计为 DisMeta scientific regression。

## 14. Recommendation 与停止边界

V1 明确展示 DisMeta **INTEGRATION_BLOCKED**；自动与手工导入均不可用，既有 LRECA、FuzDrop import
和 SEG 独立提供结果。若今后网站必须自动提供 IDR，需要用户另行决定是否增加或替换其他 predictor，
并使用真实方法名称；本轮没有作出该替换。

变更清单见 [module4_changed_files.txt](module4_changed_files.txt)，实际命令和证据链见
[module4_commands.md](module4_commands.md)。Module 4 完成审计及不可用边界后停止，不进入 Module 5。

Module 4 completed.
