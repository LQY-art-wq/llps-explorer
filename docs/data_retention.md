# Data retention and privacy

Module 9 为历史查看保存规范化蛋白序列和分析结果，但不会永久保留。保存期限、所有权和删除规则均由后端执行；前端从公开配置读取期限并显示给用户。

## Retention configuration

`ANALYSIS_RETENTION_DAYS` 控制新 analysis job 和新 FuzDrop import 的保存期限：

- 默认值：`7`
- 允许范围：1–3650 天
- job 的 `expires_at = created_at + configured lifetime`
- import 的 `expires_at = backend acceptance time + configured lifetime`

任务状态更新、历史打开或下载不会延长 `expires_at`。改变环境变量只影响之后创建的记录；已有记录保留创建时写入的绝对到期时间。

`GET /api/v1/config/public` 只公开 `analysis_retention_days`，不会公开 `DATABASE_URL`、内部路径、模型路径或其他服务端配置。History UI 使用该返回值显示 `Analyses are retained for X days.`，不在前端写死 X。

## What is stored

为恢复 Feature Viewer、Sequence Viewer、Tables 和科学导出，job 在期限内保存：

- sequence name（如用户提供）、length、SHA256 和 uppercase canonical `normalized_sequence`
- selected methods、prediction mode 和 weights
- 每个方法的状态、原生 normalized result、provenance、errors 和 warnings
- ensemble 结果及 `result_schema_version`
- created/updated/completed/expires 时间戳
- 匿名 owner token 的 SHA256；不保存原 token

只保存 SHA256 无法恢复逐位视图，所以 raw canonical sequence 是有意保存的数据。原始输入的空白、换行和 FASTA 包装形式不保存；历史恢复时只能标记为 persisted canonical sequence，不能声称恢复了原输入格式。

已验证的 FuzDrop import 另存 sequence SHA256/length、完整 normalized result、source、validation status 和用户声明的 coordinate provenance。应用不保存 Python pickle，也不把 synthetic scientific results 自动写入 production 数据库。
未过期 import 与 jobs 使用同一数据库，因此后端重启后仍可由同一 owner 引用；进程关闭不会主动清空它们。
超过 `ANALYSIS_MAX_SEQUENCE_LENGTH` 的规范化序列在任何 analysis endpoint 或 FuzDrop import
进入执行/持久化前即以 413 拒绝，因此不会留下 job、import 或部分 scientific result。

## Cleanup

基本清理不依赖 cron：

1. 后端启动时先恢复中断任务，再清理所有已过期 jobs 和 imports。
2. 运行期间按 `ANALYSIS_CLEANUP_INTERVAL_SECONDS` 周期清理；默认 3600 秒，最大 86400 秒。
3. job/import 读取也检查到期时间；读取 expired job 会先提交 job 和 orphan import 的物理删除，再返回 404。
4. history query 始终排除 `expires_at` 已到的记录。

到期优先于状态：cleanup 也物理删除仍标为 queued/running 的 expired row，运行协程之后的 update
不会重新创建已删除记录。若服务重启，active row 会先按 `service_restart` 恢复为 `interrupted`，随后
同一启动流程仍会删除已经到期的记录。

周期 sweeper 捕获单次数据库/cleanup 异常，只记录异常类型，不记录异常正文、连接 URL、sequence 或
payload，并在下一 interval 自动重试；一次瞬时失败不会永久终止 retention task。

删除 job row 会通过外键 cascade 删除 method 和 import-link rows；`normalized_sequence`、完整结果和 metadata 与 job row 一并消失。当前实现没有额外的文件型结果副本或独立 cache 需要清除。

## Manual delete

`DELETE /api/v1/analysis/{job_id}` 要求同一 anonymous owner。成功返回 204；之后 detail、download 和 history 都不再返回该 job。删除的是存储的 sequence、metadata 和结果，而非仅从 History UI 隐藏。

同源 proxy 会在每次响应中以滑动方式续写同一匿名 token 的 HttpOnly cookie，Max-Age 为 3650 天，覆盖后端允许的最长 retention；续期 cookie 不会改变 job 或 import 已保存的 `expires_at`。清除浏览器 cookie 不等于删除服务器数据，它会让该浏览器无法再证明 owner 身份；记录仍按原期限清理。当前没有账户恢复或 token 找回流程，因此需要立即删除时应在仍持有原 browser session 时操作。

## FuzDrop reference and orphan rules

一个已验证 import 可以由同一 owner 的多个 jobs 引用。引用关系保存在 `analysis_job_imports`，绑定 job 前还会检查 import 未过期且 sequence SHA256/length 相同。

- 删除或到期清理一个 job 时，先删除它的引用；只有该 import 已无任何 job 引用时，才同时删除 import。
- 显式删除、expired GET、cleanup 和创建前过期清理共享同一 job mutation 临界区直到事务提交；PostgreSQL 协作进程使用同一 transaction advisory lock，因此并发删除最后几个共享引用不会遗留 orphan。
- 若仍有其他 job 引用，同一 import 保留，避免误删其他历史任务所需的数据。
- import 自己到达 `expires_at` 后会被清理，其引用行随外键一起删除。
- job 接受 import 时已经把经过校验的 FuzDrop normalized result 复制进自身 versioned result snapshot。因此 import 后来过期，不会改写仍在保存期内的既有 job 结果，也不会触发重新导入或重新计算。
- 未绑定任何 job 的 import 仍保存到自己的到期时间；没有公开的独立 import delete endpoint。

这些规则只管理经过本地格式和序列匹配校验的导入。`source=manual_import_of_official_result` 仍是用户来源声明，不代表服务独立认证了官方来源，也不启用自动 FuzDrop 请求。

## Logging policy

生产日志不得写入完整 sequence、原匿名 session token、导入原文、结果 payload 或数据库 URL 凭据。当前 analysis API 的失败日志只记录异常类型和安全错误码；orchestrator 的运行日志记录 job ID、method、status、runtime、sequence length 和 SHA256，不记录完整 sequence。模型启动诊断可能记录仅服务端可见的 checkpoint 路径，因此生产日志仍须限制访问并在集中采集前制定路径脱敏规则。HTTP 响应不返回数据库路径、模型绝对路径或 secret。

匿名 token 只经 request header/cookie 进入后端；FastAPI 不把 `X-Analysis-Session` 原 token 写回 response
header，新 session 仅以 HttpOnly cookie bootstrap。数据库只保存高熵 token 的 SHA256 owner key；
应用日志不记录原 token。

若 Module 10 增加反向代理、APM、SQL debug logging 或集中日志，仍需保留此边界：关闭 request-body 和敏感 header 记录，并对连接 URL 凭据脱敏。Module 9 本身不建立数据库备份；未来若启用备份，备份期限和销毁策略也应覆盖未发表序列。

## Scientific state after expiry or delete

到期或主动删除只改变数据是否可访问，不产生任何科学结论。404 不能解释为预测失败或蛋白为阴性。DisMeta 的 persisted state 仍是 `Unavailable` / `INTEGRATION_BLOCKED`，不会因为保存、清理或恢复历史而生成 IDR。

数据库结构、迁移和重启恢复见 [Analysis persistence](persistence.md)。导出中的 sequence 与空值语义见 [Export formats](export_formats.md)。
