# Module 9：Results Tables, Export, Persistent Analysis History & Data Lifecycle

## 完成结论与范围

Module 9 已把 analysis job 和经过验证的 FuzDrop import 从进程内临时状态迁移到关系数据库，并完成 History、结果表格、正式下载、主动删除、到期清理、匿名 ownership 和跨后端重启恢复。开发数据库为 SQLite，生产目标为 PostgreSQL；业务层依赖 repository protocol，切换数据库不需要重写 `AnalysisOrchestrator` 或科学模型代码。

本模块没有修改 LRECA 模型、Grad-CAM、KDE、SEG 参数、FuzDrop 科学语义、DisMeta 状态或 weighted ensemble 公式。FuzDrop 仍为 `MANUAL_IMPORT_ONLY`；DisMeta 仍为 `INTEGRATION_BLOCKED`，不会生成 IDR。当前工作停在 Module 9，没有执行 Docker、Linux server、PostgreSQL 正式实例或公开部署。

## 1. 为什么历史任务之前会 404？

Module 8 及更早版本的 analysis jobs 和 imported results 保存在 FastAPI 进程内的 dictionary/store。后端退出后该内存状态消失，浏览器保留的 `job_id` 无法在新进程中找到，因此详情请求返回 404。这不是科学计算失败，也不代表蛋白为阴性。

Module 9 用 SQL repository 替换了正式应用生命周期中的进程内 store。数据库现在是 history、detail 和 export 的真实来源；内存实现只保留给隔离测试和兼容场景。

## 2. 现在存储在哪里？

开发环境默认通过 `DATABASE_URL` 使用项目相对路径的 SQLite；生产目标通过同一配置连接 `postgresql+psycopg`。SQLAlchemy 2.x 负责 ORM，Alembic 提供两次正式 migration：初始持久化 schema，以及 history summary/method 索引和旧记录回填。

数据库保存：

- analysis metadata、状态和 created/updated/completed/expires 时间；
- sequence name、length、SHA256，以及为恢复 Viewer 所需的 canonical normalized sequence；
- selected methods、prediction mode、weights、method states、ensemble、warnings；
- 完整的 versioned JSON-compatible result snapshot，当前 `result_schema_version=1.0`；
- 方法 provenance、残基数组、regions 和 history summary 索引；
- 已验证 FuzDrop import 及其与 jobs 的多对多引用。

数据库不使用 pickle，不依赖本地 JSON 文件作为生产持久层，也不硬编码开发机路径。完整 schema、repository boundary 和 migration 说明见 [persistence.md](persistence.md)。

## 3. backend restart 后是否保留？

是。未删除且未过期的终态 job 会从同一数据库原样恢复，打开 History 只读取 persisted snapshot，不重新执行 LRECA、SEG、KDE 或 ensemble。

两组真实验收相互独立：

- 浏览器验收创建真实 LRECA + SEG job `analysis_qRdLh232naWnfD4YndOlZl8WUmDuBn-B`。后端停止并以同一数据库启动新进程后，详情仍为 success；完整 persisted payload 在重启前后 SHA256 均为 `9b01fe3587be0d1a601aa5f51d3479cf5d0b15238e8f680d22b3d2841912fa0b`。History 可再次打开 Overview、Feature Viewer、Sequence Viewer、LRECA、Annotations 和 Tables，且未发出新的 analysis POST。
- 独立双进程 HTTP hard gate 创建另一个真实 248-aa LRECA + SEG job，跨两个实际 Uvicorn 进程后 payload bytes 完全一致，并验证五类下载、204 delete、delete 后 GET 404 和 history total 0。脱敏证据见 [restart summary](audit/module9_backend_restart/summary.json) 与 [export evidence](audit/module9_backend_restart/exports.json)。

启动时遗留的 `queued`/`running` job 不会永久挂起，也不会伪装为 completed。它们会恢复为 `interrupted`，对应未完成方法为 failed，并保存 `ANALYSIS_INTERRUPTED` / `service_restart`。

## 4. production 推荐 PostgreSQL 是否已兼容？

代码和 schema 已兼容 PostgreSQL：接受 PostgreSQL URL、使用 psycopg 3、可执行 Alembic migration，并在 capacity admission 使用 transaction advisory lock 协调采用相同 repository 协议的多个进程。SQLite 的外键、WAL、busy timeout 和进程内 lock 只服务于单进程开发。

本模块没有连接真实 PostgreSQL server，因此结论是“代码与 migration ready，正式运行尚未验证”。此外，任务执行仍是 web 进程内 asyncio task；在 Module 10 引入共享 queue、lease 和 worker ownership 前，FastAPI analysis worker 必须保持单实例/单 worker。仅切换 `DATABASE_URL` 不能自动获得安全的多 worker 调度。

## 5. sequence 保存多久？

默认 7 天，由 `ANALYSIS_RETENTION_DAYS` 配置，允许 1–3650 天。`expires_at` 在创建时固定；打开、轮询或下载不会延长期限。前端从安全的 public config endpoint 读取实际天数并显示 `Analyses are retained for X days.`，不会把 7 写死在 UI。

保存的是 uppercase canonical sequence，用于历史恢复和逐残基导出；原始 FASTA header、空白与换行格式不保存。启动清理、默认每小时的低频清理和读取时到期检查会物理删除过期 metadata、sequence、results、links 及符合 orphan 规则的 import。详情见 [data_retention.md](data_retention.md)。

## 6. 如何删除？

用户可在 History 中点击 Delete 并确认，或由同一 owner 调用 `DELETE /api/v1/analysis/{job_id}`。成功返回 204；随后 detail、export 和 history 均不再返回该 job，GET 表现为 404。删除的是数据库中的 sequence、metadata 和完整 result，而不是只隐藏 UI 行。

若 job 引用了 FuzDrop import，删除引用后仅在该 import 不再被任何其他 job 使用时删除 import；仍被其他 job 引用的 import 保留。当前查看的 job 被删除后，前端清除对应 persisted workspace state，不保留可继续下载的旧缓存。

## 7. history ownership 怎么保证？

当前没有账户系统，因此使用匿名 browser session ownership：

- session token 由密码学安全随机源生成；
- Next.js 同源 proxy 用 HttpOnly cookie 保存 token，并仅在服务端转发；每次 proxy 响应都会续写同一 token，3650 天 Max-Age 覆盖后端允许的最长 retention；
- FastAPI 不通过 `X-Analysis-Session` response header 回显原 token；
- 数据库只保存 token 的 SHA256 owner key，不保存原 token，IP 不作为身份；
- history、detail、export、delete、FuzDrop import lookup 和 job binding 全部使用 owner 条件；
- 缺少、无效或其他 owner 的凭据对详情、导出和删除统一表现为 404，不泄漏 job 是否存在；新 owner 的 history 为空。

`DEV_DISABLE_JOB_OWNERSHIP` 默认关闭；production 配置若尝试开启，应用启动校验会拒绝。production client JavaScript 的脱敏扫描确认不含 session header、内部 backend target 或开发机路径，见 [client privacy evidence](audit/module9_browser/client_privacy.json)。

## 8. FuzDrop import 如何持久化？

通过本地严格验证的 import 保存到 `imported_results`，包含 result ID、owner、created/expires 时间、sequence SHA256/length、完整 normalized result、source、validation status 和 coordinate provenance。引用关系单独保存在 join table；绑定时继续校验 owner、有效期、sequence length 和 SHA256。

同一 owner 的多个 jobs 可以引用一个 import。每个已创建 job 还会把当时经过验证的 FuzDrop normalized result 复制进自己的 versioned snapshot，因此 import 后来过期不会改写历史 job，也不会触发重新访问 FuzDrop。`source=manual_import_of_official_result` 仍是用户来源声明，不是本站对官方来源的独立认证。

## 9. DisMeta blocked 状态如何持久化？

如果 job 选择 DisMeta，persisted method execution 保存 `status=unavailable`、`integration_mode=integration_blocked`、reason 和 warning；result/regions 仍为 null。History 重新打开和 JSON export 会恢复这一本来状态。Tables 显示 `Unavailable`，residues CSV 的 `DisMeta_IDR_Status` 也为 `Unavailable`，不会显示 `False` 或 `IDR Regions: 0`，更不会由其他方法生成 IDR。

服务重启中断的 execution 单独表示为 `Interrupted`，未选择 DisMeta 则为 `Not selected`；这三种情况不混淆。

## 10. JSON / CSV / FASTA 输出定义

所有下载均由 FastAPI 从 persisted result 生成，前端不重算任何科学值。五类正式 endpoint 为 Result JSON、Summary CSV、Residues CSV、Regions CSV 和 FASTA；全部校验 owner，对 queued/running 返回 409，成功响应带正确 MIME 和 attachment filename。

- JSON：export envelope 和完整 analysis snapshot，含 schema version、sequence metadata/canonical sequence、方法结果与 provenance、残基数据、regions、weights、ensemble 和 warnings；不含 token、owner hash、服务器路径、内部 URL 或 secret。
- Summary CSV：一条 analysis summary，含方法/ensemble score 和 label、SEG coverage、时间、provenance 与 schema version。
- Residues CSV：每个 canonical residue 一行，10 列，包含 Position、AA、LRECA attribution/KDE/region membership、FuzDrop propensity/region、SEG LCR 和 DisMeta status。
- Regions CSV：仅输出 persisted native regions，列为 Method、Region_Type、Start、End、Length、Score、Primary、Source。
- FASTA：安全名称与 job ID 组成 header，canonical sequence 每 60 aa 换行。

所有坐标为 **1-based、start/end inclusive**；JSON 保留 persisted precision，CSV 不按 UI 的三位小数截断。未提供值留空/null，不伪造 0；安全文件名和 spreadsheet formula injection 防护均有测试。完整契约见 [export_formats.md](export_formats.md)。Feature Viewer 当前使用 Canvas 2D，没有稳定的 SVG contract，因此 Module 9 没有提供 PNG/SVG；这符合“现有库稳定支持时再做”的范围条件。

## 11. 旧 Viewer 是否可从 history 完整恢复？

可以。History list 只返回轻量 summary；Open 再获取同一 owner 的完整 versioned snapshot。前端会核对 persisted canonical sequence 的 length、alphabet 和 SHA256，然后恢复 Overview、Feature Viewer、Sequence Viewer、LRECA、FuzDrop（仅当旧结果真实存在）、Annotations 和 Tables。新打开历史记录会重置暂存 selection/focus，随后仍保持 Module 8 的 Feature ↔ Sequence ↔ Table 双向联动。

真实浏览器验收中，248-aa job 跨后端重启后恢复了 4 条 Feature tracks、Sequence Viewer、prediction summary、10 条 LRECA top residues、5 个 LRECA regions、3 个 SEG regions和 248 行分页 residue table；Table → Sequence 和 Sequence → Feature 的 1-based focus 均通过。下载按钮对应请求为 200。记录见 [browser verification](audit/module9_browser/browser_verification.json) 和 [restart verification](audit/module9_browser/restart_verification.json)。

## 12. Linux / Docker readiness

Module 9 的数据库、路径和 migration 代码使用环境变量、SQLAlchemy URL 与 `pathlib`，没有写死 Windows 绝对路径或反斜杠路径拼接。Python package 支持 3.10–3.13；生产目标依赖 SQLAlchemy 2.0.43、Alembic 1.16.5、psycopg 3.2.10，并需要 Linux `libpq` runtime。Next.js build 也使用服务端 `BACKEND_URL`，不会把内部 target 打入客户端 JavaScript。

这些条件使代码具备 Linux/Docker 迁移基础，但本模块没有 build/run container，也没有在 Linux、正式 PostgreSQL、reverse proxy 或 HTTPS 下实测。LRECA worker/checkpoint 与 Linux SEG `segmasker` 仍需按既有 runtime 文档在 Module 10 配置。核心 persistence、export 和 inference 代码不需要因为容器化重写；部署边界、运行时依赖和 worker 模型需要在 Module 10 落地。

## 13. Unresolved risks

1. **匿名公开服务的滥用防护**：当前全站 `ANALYSIS_MAX_JOBS` 和 `EXTERNAL_RESULT_MAX_ENTRIES` 默认各 128，可限制存储增长，但匿名用户可轮换 cookie/session 绕过基于 owner 的公平性并占满全局容量。Module 10 公开部署前需要 trusted edge rate limiting、配额或账户认证；Module 9 没有把匿名 token 描述成抗滥用系统。
2. **PostgreSQL 尚未实跑**：schema、driver、migration 和 advisory-lock 路径已准备，仍需对真实 PostgreSQL 做 migration、并发和 restart 验收。
3. **多 worker 调度尚未建立**：analysis task 仍住在 web 进程；公开扩容前需要共享 queue、lease、幂等 worker ownership 与故障恢复。当前部署只能使用一个 analysis worker。
4. **Linux/Docker 尚未部署**：需要验证容器内 PyTorch/LRECA、checkpoint mount、SEG binary、`libpq` 和资源限制，不能复制 Windows 虚拟环境或可执行文件。
5. **匿名 session 不可恢复**：清除 HttpOnly cookie 或换浏览器后，没有账户/token recovery；服务器数据仍按期限清理。需要立即删除时必须仍持有原 session。
6. **备份与集中日志策略待部署定义**：Module 9 没有建立数据库备份。Module 10 若加入备份、proxy/APM 或 SQL debug logging，必须把未发表序列、敏感 headers 和数据库凭据纳入保留与脱敏政策。
7. **Viewer 图片导出**：Canvas Feature Viewer 尚无稳定 PNG/SVG export contract；本模块的正式可复现数据出口是 JSON、三类 CSV 和 FASTA。

## 质量与真实验收

| Gate | 最终状态 | 证据/说明 |
| --- | --- | --- |
| Backend full pytest | 775 passed | `docs/audit/module9_checks/backend_pytest.log`；不把定向测试重复累加 |
| Ruff / compileall / pip check | 通过 | 最终命令与记录索引见 [module9_commands.md](module9_commands.md) |
| Frontend unit tests | 321 passed | `docs/audit/module9_checks/frontend_unit.log` |
| Frontend lint / typecheck / production build / peer check | 通过 | `docs/audit/module9_checks/` 对应日志 |
| Module 8 API/science regression | 263/263 passed | [module8_api_regression.json](audit/module9_checks/module8_api_regression.json)；没有修改冻结 Module 0–8 evidence |
| 双进程后端 restart hard gate | 通过 | persisted payload 精确一致；五类 export 200；DELETE 204；后续 GET 404、history 0 |
| 真实浏览器 A–K | 通过 | 生产页面完成真实运行、History、恢复、下载与主任务删除；浏览器 DELETE 返回 204，同 session 刷新后主任务消失。额外 5000-aa job 由验收 teardown 清理，重载后默认筛选显示 `No saved analyses yet.` 和 `0 saved analyses` |
| 5000-aa export | 通过 | SEG-only residues CSV 5000 行，首行为 1/A、末行为 5000/A；点击到返回 423 ms，页面保持可交互，见 [long export](audit/module9_browser/long_export.json) |

浏览器、restart 和导出证据均为脱敏摘要：不记录 anonymous session token、owner hash、完整 sequence、服务器绝对路径或内部 service URL。精确复现命令和证据索引见 [module9_commands.md](module9_commands.md)。
