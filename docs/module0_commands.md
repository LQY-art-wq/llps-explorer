# Module 0 命令与验证记录

日期：2026-09-03。工作目录：`${PROJECT_ROOT}`。
以下按任务整理关键命令；重复的文件读取、搜索和同一检查的重跑合并说明。
Module 1 Production 补充仅将历史机器路径变量化，未重做 Module 0。`API_BOOTSTRAP_PYTHON`、`NODE_BIN`、`PNPM_COMMAND` 分别代表当次使用的解释器、Node 目录及 pnpm 命令路径；重建时由本机环境提供。原始记录私有归档于 `.audit/module1_private_evidence/`。
科学 inference/SEG 命令仅在来源文档中作为候选展示，**没有执行**。

## 1. 初始检查

```powershell
pwd
git status
git branch
git log --oneline -5
```

结果：工作目录正确，目录为空，Git 三项均为 `fatal: not a git repository`。
检查了 frontend/backend、package.json、pyproject.toml/requirements、Dockerfile/compose、README、
.gitignore 和 environment files，均不存在。系统 Python 为 Anaconda 3.13.9；没有可用的 npm 或 py launcher。

通过 Codex runtime 查询工具确认可用 Python 3.12.13、Node 24.19.0、pnpm 11.19.0。
后续中文文本读取与命令输出统一使用：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
```

文件检索使用 `rg --files`、`rg`，文件读取使用 `Get-Content -LiteralPath ... -Encoding UTF8`。
未删除任何既有代码。

## 2. Git 初始化和 LRECA 获取

```powershell
git init -b main
git clone --depth 1 --no-tags https://github.com/ai-phasepro/LRECA.git external/lreca
```

第一次 clone 在 Windows Schannel 证书后端出现 `SEC_E_NO_CREDENTIALS`，没有获得可用 checkout。
下列命令成功；只切换该命令的证书后端，没有禁用 TLS 校验或修改全局 Git 配置：

```powershell
git -c http.sslBackend=openssl -c core.autocrlf=false clone --depth 1 --no-tags https://github.com/ai-phasepro/LRECA.git external/lreca
git -C external/lreca rev-parse HEAD
git -C external/lreca status --porcelain
```

结果：`0b4b48ab7870529a34028c6e30dfba42eddbf215`，上游工作区 clean。
随后读取 README、requirements、Human test/model/training、Grad-CAM/KDE、wrapper、结果说明和 LICENSE。
Python 只用于 checkpoint bytes/SHA256 清点、训练文件哈希和词表重建，不执行 `torch.load`。
完整清单保存在 `docs/audit/lreca_checkpoints.json` 和 `lreca_human_vocabulary.json`。

可重复运行的来源检查已执行两次并通过：

```powershell
.\.venv\Scripts\python.exe scripts/verify_sources.py
```

结果：7 个 checkpoint、2 个词表来源文件、固定 commit 及 clean checkout 均通过；`inference_executed=false`。

## 3. 公开来源 GET 探测

使用 `python scripts/probe_source.py <official-url>` 对明确的公开来源做低频 GET。
逐次 URL、UTC 时间、状态、错误、大小、SHA256 与缓存位置完整保存在
[http_observations.jsonl](audit/http_observations.jsonl)。本轮共 15 条记录。

代表性实际调用：

```powershell
python scripts/probe_source.py https://fuzdrop.bio.unipd.it/
python scripts/probe_source.py https://fuzdrop.bio.unipd.it/main-es2015.7255cef9dd5f54e0fbb1.js
python scripts/probe_source.py https://montelionelab.chem.rpi.edu/dismeta/
python scripts/probe_source.py http://predict.phasep.pro/guide/
python scripts/probe_source.py https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/
```

| 检查 | 实际结果 |
| --- | --- |
| FuzDrop 首页/公开脚本 | GET 200；脚本第一次超过本地 4 MiB 上限，改本地上限为 16 MiB 后完整保存 |
| FuzDrop 官方 Programs 条款入口 | GET 200，只读，没有点击 I Agree 或下载程序 |
| DisMeta 主页面 | 本机 2 次 HTTPS 握手超时；HTTP 也超时 |
| DisMeta 作者 PDF | HTTPS 握手超时 |
| PhaSePred 首页/Guide | GET 200；示例 FUS result 请求超时 |
| NCBI BLAST+ 发行目录/interval writer | GET 200，只读；没有下载 SEG 包 |

另使用网页检索工具读取官方方法论文、DisMeta 表单/参考资料、NCBI 默认参数源码、Next.js/FastAPI 文档，
以及包注册表版本信息。检索与本机 GET 的证据层级分别记录在来源文档中。
FuzDrop 浏览器页面读取超时；从官方首页明确引用的公开 JS 获得验证码和 request shape 证据。
没有调用 `submit_protein`、提交邮箱/序列、破解隐藏服务或绕过验证码。

## 4. Python 隔离环境与安装

```powershell
& $env:API_BOOTSTRAP_PYTHON -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'
```

首次安装停在构建依赖阶段；普通 setuptools/wheel 安装也曾停滞。两次均中断本轮启动的安装进程。
诊断时用 Python faulthandler 和 pip 详细输出，改用命令级 `legacy-certs`、禁用 keyring、禁用缓存后成功。
这些选项没有关闭证书验证，未设置 trusted-host、未修改全局 pip 配置。
不能仅据这一次组合成功断定到底是哪一项系统初始化导致停滞。

成功安装 setuptools/wheel 的诊断调用：

```powershell
.\.venv\Scripts\python.exe -c "import faulthandler; faulthandler.dump_traceback_later(25); from pip._internal.cli.main import main; raise SystemExit(main(['install','--disable-pip-version-check','--index-url','https://pypi.org/simple','--retries','0','--timeout','15','--use-deprecated=legacy-certs','--keyring-provider','disabled','--no-cache-dir','-v','setuptools','wheel']))"
```

成功安装后端与测试依赖的命令：

```powershell
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --index-url https://pypi.org/simple --retries 1 --timeout 15 --use-deprecated=legacy-certs --keyring-provider disabled --no-cache-dir --no-build-isolation -e './backend[dev]'
.\.venv\Scripts\python.exe -m pip freeze --all
```

依据该环境输出创建 `backend/requirements.lock.txt`，去掉本机 editable 路径，保留第三方运行、测试和构建工具版本。
本机 editable package 为 `llps-explorer-backend==0.0.0`，没有安装 torch 或任何替代注释算法。
未来重建方式见 README；本轮验证平台仅 Windows x64 / Python 3.12.13。

## 5. 前端安装、类型检查与构建

在 `frontend/` 中运行以下命令；PATH 只在该进程中补充 bundled Node：

```powershell
$env:PATH = $env:NODE_BIN + [System.IO.Path]::PathSeparator + $env:PATH
$env:NEXT_TELEMETRY_DISABLED = '1'
& $env:PNPM_COMMAND install
& $env:PNPM_COMMAND typecheck
& $env:PNPM_COMMAND build
```

install 成功；期间一次连接重置自动重试成功。`pnpm-lock.yaml` 与包版本已固定。
production build 成功。最终 typecheck 使用 `next typegen && tsc --noEmit`，再次执行通过，
确保没有现成 `.next/types` 的 checkout 也会先生成 Next 所需类型。
最终读取已安装包的 engines：pnpm 11.19.0 要求 Node >=22.13，Next.js 要求 >=20.9；
项目统一取较高下限 >=22.13，README 与 package.json 已同步。本机 Node 24.19.0 满足要求。

## 6. Python 检查与修复

从项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend scripts
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml --fix backend scripts
.\.venv\Scripts\python.exe -m ruff format --config backend/pyproject.toml backend scripts
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend/app backend/tests scripts
.\.venv\Scripts\python.exe -m pip check
```

最初 Ruff 找到 4 个 import 排序项和 3 个长行；自动排序/格式化后通过，未格式化或更改上游源码。
修复后 pytest 再次通过：**19 passed, 2 warnings in 0.65s**。
警告来自 Starlette 的 httpx compatibility 和 AnyIO deprecated alias，未隐藏。
compileall 无错误，pip check 为 `No broken requirements found`。

## 7. 真正启动与 HTTP / 浏览器检查

后端，从项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

前端，在 `frontend/` 中使用第 5 节的 PATH 和 telemetry 环境：

```powershell
& $env:PNPM_COMMAND start
```

输出确认 FastAPI startup complete，Next.js 在 `127.0.0.1:3000` ready。
两端运行期间，从根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_module0.py
```

结果 **4/4 通过**：后端健康响应、Next 同源代理、首页内容、只含 health 的 OpenAPI。
记录时间 `2026-09-03T08:13:51.875489+00:00`，详见 [smoke_results.json](audit/smoke_results.json)。
健康响应 `analysis_enabled=false`，没有调用科学作业。

通过浏览器工具读取 `http://127.0.0.1:3000/` 的实际 accessibility tree 并检查截图，
确认两类方法、四个 Pending 和 unavailable 提示正确，当前视口未发现布局遮挡或溢出。
验收结束后用 Ctrl+C 停止本轮启动的两个服务，不影响其他进程。

## 8. 最终 Git 审查

```powershell
git add --intent-to-add .
git diff --check
git diff --stat
git status --short --untracked-files=all
git branch
git log --oneline -5
```

新增文本已进入可审查的 working-tree diff。`git diff --check` 无空白错误。
当前分支 main，尚无 commit，因此最终 log 的“没有提交”提示符合本轮状态。
逐文件清单另存为 [module0_changed_files.txt](module0_changed_files.txt)。没有创建远端或提交。

实际索引登记遇到两项本机环境限制：沙盒将 `.git` 设为只读；提升权限后账户从
沙盒账户变为开发账户，Git 因所有权差异拒绝操作。核对仓库绝对路径、HEAD 和 config
确认是本轮新建仓库后，通过权限审查，以下仅对本次命令信任该具体目录的调用成功：

```powershell
git -c "safe.directory=$((Get-Location).Path)" add --intent-to-add .
```

未添加全局 `safe.directory`，未变更目录权限或所有权。索引只登记新增文件，未创建 commit。

最终本地一致性检查确认：51 个变更文件与 manifest 完全相符；依赖 lock 与隔离环境版本一致；
README、docs 与 external README 的本地文档链接均存在；3000/8000 端口均已停止监听。
将四个审计/清单文件统一成 UTF-8 / LF 后，`git diff --check` 无错误或换行警告。
smoke 脚本也显式按 LF 写出后续记录；最后的 Ruff 和 compileall 再次通过。
