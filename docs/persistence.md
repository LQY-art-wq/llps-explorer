# Analysis persistence

Module 9 将 analysis job 和已验证的 FuzDrop 导入从进程内字典迁移到关系数据库。数据库是历史记录的真实来源；缓存不是恢复任务所必需的组件。持久化层不改变 LRECA、FuzDrop、SEG、DisMeta 或 weighted ensemble 的科学计算。

## 为什么旧任务曾返回 404

Module 8 及更早版本只在当前 FastAPI 进程中保存任务和导入结果。后端重启会清空该进程的内存，因此旧 `job_id` 即使仍在浏览器会话中，也无法再次查询。Module 9 的 FastAPI 应用在启动时连接数据库，使用 `SQLAnalysisJobRepository` 和 `SQLImportedResultStore`，所以未删除且未过期的记录可在重启后继续读取。

## 数据库配置

数据库仅通过 `DATABASE_URL` 配置：

| 环境 | 当前约定 |
| --- | --- |
| 本地开发 | SQLite；示例为 `sqlite:///./backend/data/llps_explorer.db` |
| 生产目标 | PostgreSQL；接受 `postgresql://...` 或 `postgresql+psycopg://...` |

普通 `postgresql://` URL 会在进程内转换为 SQLAlchemy 2 使用的 `postgresql+psycopg://` URL。代码不依赖当前用户目录，也没有硬编码开发机绝对路径。未显式设置 `DATABASE_URL` 时，默认 SQLite 文件位置由 `pathlib.Path` 从项目目录推导。

SQLite 文件连接启用外键、30 秒 busy timeout 和 WAL；内存 SQLite 使用共享的 `StaticPool`。这些设置适合开发和测试，但 SQLite 不是面向公开高并发部署的最终数据库。生产 PostgreSQL 是 Module 10 的部署目标；Module 9 提供了可移植 schema、psycopg 驱动和迁移路径，没有在本模块部署正式 PostgreSQL。

持久化依赖锁定为 SQLAlchemy 2.0.43、Alembic 1.16.5 和 psycopg 3.2.10。Windows lock 通过 platform marker 使用 `psycopg-binary` 和 `tzdata`；Linux production 使用 `psycopg` 与系统 `libpq` runtime，容器安装由 Module 10 完成。

规范化后的单条蛋白序列受 `ANALYSIS_MAX_SEQUENCE_LENGTH` 限制，默认 50,000 aa，允许范围
1–1,000,000；长度按 canonical residues 计数，不含 FASTA header、换行或空白。统一 analysis endpoint、
四个单方法 analyze endpoint 和 FuzDrop import 使用同一限制；
超限返回 413 / `ANALYSIS_SEQUENCE_TOO_LONG`，并在创建 job/import 或启动科学方法前停止。

## Schema

数据库不保存 pickle。完整结果使用可由 Pydantic 校验的、JSON-compatible 的版本化结构，当前 `result_schema_version` 为 `1.0`。

| 表 | 用途 | 主要字段 |
| --- | --- | --- |
| `analysis_jobs` | 任务、输入和结果快照 | `job_id`、`owner_id`、时间戳、状态、sequence name/length/SHA256、`normalized_sequence`、方法、模式、权重、方法状态、ensemble、normalized results、warnings、`result_payload`、schema version、三个 summary score |
| `imported_results` | 已验证的 FuzDrop 导入 | `result_id`、`owner_id`、时间戳、sequence SHA256/length、normalized result、source、validation status、coordinate provenance |
| `analysis_job_imports` | 任务与导入结果的引用关系 | `job_id`、`result_id`；两个外键都使用 cascade delete |
| `analysis_job_methods` | 高效 method filter | `job_id`、`method` |

`result_payload` 保存当时返回的完整 `AnalysisJob` 快照，包括方法 provenance、残基值、区域、ensemble 和 warnings。历史列表只查询轻量 summary 列，不随列表请求传输完整残基数组。详情和导出再读取完整快照。

## Repository boundary

`AnalysisJobService` 依赖 `AnalysisJobRepository` protocol，而不依赖 SQLAlchemy session。该接口提供：

- `create_job`
- `update_job`
- `get_job`
- `list_jobs`
- `delete_job`
- `cleanup_expired_jobs`
- `recover_interrupted_jobs`
- `close`

`AnalysisOrchestrator` 继续只负责能力路由和科学方法组合，不导入 SQLAlchemy，也不解析数据库行。将 SQLite 改为 PostgreSQL 不需要重写 orchestrator 或核心模型代码。进程内实现仍用于隔离测试和兼容旧集成；正式 FastAPI lifespan 使用 SQL repository。

## Alembic migrations

迁移文件位于 `backend/app/persistence/alembic/versions/`：

1. `20260904_0001` 创建 jobs、imports 和引用表及索引。
2. `20260904_0002` 添加三个 history summary score、method 关系表及索引，并从已有 versioned JSON payload 在线回填旧行。

应用启动执行幂等的 Alembic `upgrade head`，不会 drop/create 全部表。也可在部署前从项目根目录显式执行：

```text
python -m alembic -c backend/alembic.ini upgrade head
```

升级已有数据库时应使用在线迁移，使 `0002` 能读取并回填已有行。离线 SQL 模式无法执行这一数据回填，只适合没有旧记录的新数据库准备。PostgreSQL offline DDL 已通过迁移生成检查；本模块没有连接正式 PostgreSQL server。生产部署可在启动 web 进程前只运行一次迁移；具体容器启动顺序留给 Module 10。

## 启动、重启和中断恢复

FastAPI lifespan 的相关顺序为：

1. 建立 SQLAlchemy engine。
2. 运行 Alembic 到 `head`。
3. 构造 SQL job/import repositories。
4. 恢复中断任务。
5. 清理过期任务和导入。
6. 启动低频 cleanup task，再接受业务请求。

未过期的终态任务在重启后保持原始 persisted result；重新打开历史任务只读取该快照，不重新运行 LRECA、SEG 或 ensemble。

启动时发现 `queued` 或 `running` 任务时，V1 不尝试分布式续跑。任务顶层状态改为 `interrupted`，当时仍为 queued/running 的方法改为 `failed`，并保存：

- `error.code = ANALYSIS_INTERRUPTED`
- `reason = service_restart`
- 安全、无输入内容的 warning

已经完成的方法结果继续保留。恢复过程不会把中断任务伪装为成功，也不会自动提交新计算。
真实双进程 restart 验收的脱敏摘要见 [restart summary](audit/module9_backend_restart/summary.json)，
对应五类下载校验见 [export evidence](audit/module9_backend_restart/exports.json)。

## History and ownership

当前没有账户系统。每个浏览器获得随机的匿名 session token；同源 Next.js proxy 通过 HttpOnly cookie 保存它，并以 `X-Analysis-Session` request header 转发给 FastAPI。FastAPI 不通过同名 response header 回显原 token；缺少或无效 token 时只通过 HttpOnly `Set-Cookie` 建立 session。后端只把 token 的 SHA256 保存为 `owner_id`：数据库不保存原 token，应用日志也不应记录它。IP 地址不参与所有权判断。

owner 条件应用于：

- history list
- job detail
- export
- delete
- FuzDrop import lookup and job binding

知道 `job_id` 本身不足以读取他人的任务。detail、export 或 delete 使用缺少、无效或属于另一 session 的凭据时，对外表现为 404，不泄漏记录是否存在；history list 对新的 owner 返回空列表。`DEV_DISABLE_JOB_OWNERSHIP=true` 只用于隔离的本地调试，默认关闭；当 `LLPS_ENVIRONMENT=production` 时若尝试启用，配置校验会拒绝应用启动。

历史列表有两个等价入口：

- `GET /api/v1/analysis`
- `GET /api/v1/analysis/history`

两者支持 `limit`（1–100，默认 50）、`offset`、`status` 和 `method`。结果按 `created_at`、`job_id` 倒序，只返回当前 owner 且未过期的 summary。完整任务由 `GET /api/v1/analysis/{job_id}` 返回。

每个 history item 只包含 `job_id`、sequence name/length、created/updated/completed/expires 时间戳、status、selected methods、prediction mode、可用的 LRECA/FuzDrop/ensemble score 和 result schema version；不包含 SHA256、canonical sequence、method payload 或 residue arrays。允许的 status filter 为 `queued`、`running`、`success`、`partial_success`、`failed`、`unavailable`、`external_result_required` 和 `interrupted`；method filter 为四个注册方法之一。

`POST /api/v1/analysis` 的 202 response 有意把 `normalized_sequence` 设为 null；同一 owner 后续读取 detail 时才获得为历史 Viewer 保存的 canonical sequence。该 sequence 会在前端按 length、alphabet 和 SHA256 重新核对后使用。

## Capacity admission

`ANALYSIS_MAX_JOBS` 和 `EXTERNAL_RESULT_MAX_ENTRIES` 是全站数据库容量上限，不是每个 owner 的独立配额；
默认各 128。创建新记录前会先物理删除相应类型的 expired rows，再对全表执行 count。达到上限时拒绝
新 job 或 import，不驱逐仍有效的其他 owner 数据。

同一进程内，job/import 各有独立的 re-entrant lock，把 cleanup、count 和 insert 包在一个 admission
临界区。job mutation lock 还覆盖显式删除、expired GET、cleanup、引用删除、orphan 判定和 transaction
commit，避免两个并发删除各自留下同一个共享 import。PostgreSQL 在同一 transaction 内取得固定的
`pg_advisory_xact_lock`，使所有使用本 repository 及相同 lock keys 的协作进程串行执行这些 job mutation
和 import admission。advisory lock 是协作协议；直接 SQL、外部工具或使用不同 lock key 的 writer
不受保护。SQLite 没有该跨进程 advisory lock，因此开发模式仍按单进程使用。

## Production boundary

当前 persistence schema、SQLAlchemy types、psycopg driver 和 migrations 按 PostgreSQL 目标设计，但本模块未进行正式 PostgreSQL 部署。任务执行仍由 web 进程内的 asyncio task 完成。每个进程的并发 semaphore 也是进程内状态；并且每个应用实例启动时都会恢复数据库中的 queued/running 任务。因此，在 Module 10 引入共享队列、lease/worker ownership 之前，应只运行一个负责 analysis execution 的 FastAPI worker。仅把 `DATABASE_URL` 改为 PostgreSQL 不会自动获得安全的多 worker 任务调度。

数据保存期限、主动删除和 FuzDrop orphan 规则见 [Data retention](data_retention.md)。下载契约见 [Export formats](export_formats.md)。
