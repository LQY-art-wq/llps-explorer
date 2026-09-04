# Module 9：命令与验收记录

本文中的路径都相对于项目根目录，不包含开发机绝对路径。命令以跨平台的 `python`、`pnpm` 和环境变量为入口；Windows 与 POSIX 只在环境变量语法上分别给出示例。生产 secret 应由部署平台注入，不要写入仓库或命令历史。

## Runtime 与安装

后端项目要求 Python `>=3.10,<3.14`，本轮开发解释器为 Python 3.12；LRECA 科学 worker 继续使用 Module 1 锁定的独立 Python/PyTorch 环境。持久化主要版本为 SQLAlchemy 2.0.43、Alembic 1.16.5 和 psycopg 3.2.10。前端要求 Node.js `>=22.13,<27`、pnpm 11.19.0，本轮 production build 使用 Next.js 16.3.4。

从项目根目录安装锁定依赖：

```text
python -m pip install -r backend/requirements.lock.txt
python -m pip install --no-deps --no-build-isolation -e ./backend
pnpm --dir frontend install --frozen-lockfile
```

Linux PostgreSQL runtime 还需系统 `libpq`；Windows 开发依赖通过 package marker 使用 `psycopg-binary` 和 `tzdata`。LRECA checkpoint、PyTorch/CUDA 和 SEG 安装继续按 `docs/lreca_runtime.md` 与 `docs/seg_runtime.md` 配置，不把模型权重或平台专用二进制写入 Git。

## 环境配置

复制后端示例后按环境覆盖值：

```text
backend/.env.example
```

Module 9 相关默认值：

```dotenv
DATABASE_URL=sqlite:///./backend/data/llps_explorer.db
ANALYSIS_RETENTION_DAYS=7
ANALYSIS_CLEANUP_INTERVAL_SECONDS=3600
DEV_DISABLE_JOB_OWNERSHIP=false
ANALYSIS_MAX_JOBS=128
ANALYSIS_MAX_CONCURRENT_JOBS=4
ANALYSIS_MAX_SEQUENCE_LENGTH=50000
EXTERNAL_RESULT_MAX_ENTRIES=128
```

PowerShell 临时设置示例：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$env:DATABASE_URL = 'sqlite:///./backend/data/llps_explorer.db'
$env:ANALYSIS_RETENTION_DAYS = '7'
$env:DEV_DISABLE_JOB_OWNERSHIP = 'false'
```

POSIX shell 的等价语法：

```sh
export PYTHONUTF8=1
export DATABASE_URL='sqlite:///./backend/data/llps_explorer.db'
export ANALYSIS_RETENTION_DAYS=7
export DEV_DISABLE_JOB_OWNERSHIP=false
```

PostgreSQL 只需替换数据库 URL；下例凭据是占位符：

```sh
export DATABASE_URL='postgresql+psycopg://app:replace_me@db/llps'
```

公开 production 必须保持 ownership enabled。若 `LLPS_ENVIRONMENT=production` 且 `DEV_DISABLE_JOB_OWNERSHIP=true`，应用应拒绝启动。

## Alembic migration

查看和升级当前数据库：

```text
python -m alembic -c backend/alembic.ini current
python -m alembic -c backend/alembic.ini history
python -m alembic -c backend/alembic.ini upgrade head
```

应用 lifespan 也会幂等执行 `upgrade head`，不会 drop/create 全库。正式部署建议在 web process 之前以单独步骤完成 migration。`20260904_0002` 会在线读取并回填已有 JSON payload；升级有旧记录的数据库时不要用 offline SQL 代替在线 migration。

本轮已对 fresh SQLite migration 和 PostgreSQL DDL 生成路径执行检查；没有连接正式 PostgreSQL server，因此不能把 DDL 检查表述为 PostgreSQL runtime acceptance。

## 本地启动

后端从项目根目录启动，当前 task executor 只支持一个 analysis worker：

```text
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

前端的 `BACKEND_URL` 是仅服务端可见的必填配置，不加 `NEXT_PUBLIC_` 前缀。PowerShell 示例：

```powershell
$env:BACKEND_URL = 'http://127.0.0.1:8000'
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:FEATURE_VIEWER_TEST_MODE = '0'
pnpm --dir frontend dev
```

POSIX shell 示例：

```sh
BACKEND_URL='http://127.0.0.1:8000' NEXT_TELEMETRY_DISABLED=1 FEATURE_VIEWER_TEST_MODE=0 pnpm --dir frontend dev
```

生产 build 的本地验收：

```text
pnpm --dir frontend build
pnpm --dir frontend start --hostname 127.0.0.1 --port 3000
```

这些是 loopback 开发/验收命令，不是 Linux、Docker、reverse proxy、TLS 或公开部署完成声明。

## 最终质量门

从项目根目录执行：

```text
python -m pytest backend/tests -q --disable-warnings
python -m ruff check --config backend/pyproject.toml backend/app backend/tests
python -m compileall -q backend/app
python -m pip check
pnpm --dir frontend test
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
pnpm --dir frontend peers check
```

Module 9 持久化、history、ownership、export、retention、restart recovery 和 filename 的集中测试位于：

```text
backend/tests/test_module9_persistence.py
frontend/tests/history-state.test.ts
frontend/tests/session-bootstrap.test.ts
```

测试总数只取最终完整 suite 的 summary，不把定向重跑或历史 Module 0–8 数字累加。最终完整后端 suite 为 775 passed，前端完整 suite 为 321 passed；lint、typecheck、production build 和 peer dependency check 均通过。精确输出保存在 `docs/audit/module9_checks/`。

## Restart hard gate 复现步骤

该流程必须使用同一个 `DATABASE_URL` 和同一个 anonymous browser/client session：

1. 启动第一个单 worker 后端进程。
2. 提交真实 LRECA + SEG analysis，轮询到终态并保存 `job_id` 与完整响应 hash。
3. 正常停止第一个后端进程。
4. 以同一代码和数据库启动第二个独立后端进程。
5. 使用同一 owner session 获取相同 job；确认 status、schema、完整 payload hash 与方法结果完全一致。
6. 打开前端 History；确认只发 GET，不重新 POST，恢复 Feature Viewer、Sequence Viewer 和 Tables。
7. 分别下载 Result JSON、Summary CSV、Residues CSV、Regions CSV 和 FASTA，检查 MIME、attachment filename、行数、AA、1-based inclusive 坐标、精度与 unavailable/null 语义。
8. 删除 job，确认返回 204；随后 detail 为 404 且 history 不再包含它。

公开 hard-gate 摘要不保存 raw session credential、owner hash、完整 sequence、数据库位置或进程路径。实际通过结果见：

- `docs/audit/module9_backend_restart/summary.json`
- `docs/audit/module9_backend_restart/exports.json`
- `docs/audit/module9_browser/restart_verification.json`
- `docs/audit/module9_browser/browser_verification.json`

## 5000-aa export gate

使用规范化后恰好 5000 aa 的测试序列创建 SEG-only job。验收条件：

1. job 成功且页面可打开；
2. Residues CSV 恰好 5000 data rows；
3. Position 从 1 连续到 5000，首末 AA 与输入一致；
4. 表头是正式 10 列 contract；
5. 浏览器点击下载后页面仍可交互，后端返回 200；
6. 没有把完整测试序列写进公开证据。

本轮实测点击到返回为 423 ms，首行为 1/A、末行为 5000/A。脱敏结果见 `docs/audit/module9_browser/long_export.json`。

## 证据索引

| Evidence | 内容 |
| --- | --- |
| `docs/audit/module9_backend_restart/summary.json` | 两个真实 Uvicorn 进程、跨 restart payload exact match、ownership cookie、delete lifecycle |
| `docs/audit/module9_backend_restart/exports.json` | 五类 export 的 HTTP/MIME/attachment、行数、坐标与序列一致性 |
| `docs/audit/module9_browser/browser_verification.json` | 生产页面 A–K、History、Tables、viewer 恢复与下载按钮 |
| `docs/audit/module9_browser/restart_verification.json` | 浏览器 job 的跨后端 restart hash 和 restored workspace |
| `docs/audit/module9_browser/long_export.json` | 5000-aa residue export 与 responsiveness |
| `docs/audit/module9_browser/client_privacy.json` | production client JavaScript 脱敏扫描 |
| `docs/audit/module9_checks/backend_pytest.log` | 775 个后端测试 |
| `docs/audit/module9_checks/backend_quality.log` | Ruff、compileall、依赖和应用导入检查 |
| `docs/audit/module9_checks/migrations.log` | fresh SQLite migration 与 PostgreSQL offline DDL 检查 |
| `docs/audit/module9_checks/module8_api_regression.json` | 当前实现对冻结 Module 8 科学/API 行为的 263/263 覆盖 |
| `docs/audit/module9_checks/frontend_unit.log` | 321 个前端测试 |
| `docs/audit/module9_checks/frontend_lint.log` | ESLint |
| `docs/audit/module9_checks/frontend_typecheck.log` | Next type generation + TypeScript |
| `docs/audit/module9_checks/frontend_build.log` | production build |
| `docs/audit/module9_checks/frontend_peers.log` | peer dependency check |
| `docs/audit/module9_scope_review.json` | Module 8 frozen baseline 范围、路径、权重与 Git index 审计 |
| `docs/module9_changed_files.txt` | 相对 Module 8 frozen baseline 的完整变更清单 |

本轮未刷新或改写 Module 0–8 的冻结 evidence。scope review 与 changed-files 清单在代码、测试和文档冻结后生成；两者均计入最终变更总数。
