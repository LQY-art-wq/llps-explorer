# Module 2 实际命令与验证记录

从项目根目录执行；所有位置由当前目录或 `pathlib.Path` 获得。下列 PowerShell 形式记录本机
Windows 执行方式，不是 production adapter 的实现。没有写入 Git index、创建 commit 或调用
受保护的 FuzDrop POST。审计时的原始缓存和全过程 diff 保留在被忽略的 `.audit/module2/` 及
`.audit/module2_*` 中，公开证据不包含开发机器绝对路径。

## 环境与阶段快照

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
git --no-optional-locks -c core.quotepath=false status --short
git --no-optional-locks ls-files -z --cached --others --exclude-standard
.\.venv\Scripts\python.exe .audit/module2_snapshot.py
```

快照在 Module 2 编辑前完成，共 114 个已存在的第一方文件；SHA256 与原始字节分别存于
`.audit/module2_start_files.json`、`.audit/module2_start_source.zip`。已完成的 LRECA 科学实现、
fixtures、测试和性能证据据此核对，未重新生成 baseline 或 benchmark。

## 官方只读审计

重新读取原 Module 0/1 审计，再用只读 GET helper 获取官方页面及页面明确链接的 bundle：

```powershell
.\.venv\Scripts\python.exe .audit/module2/public_get.py https://fuzdrop.bio.unipd.it/predictor
.\.venv\Scripts\python.exe .audit/module2/public_get.py https://fuzdrop.bio.unipd.it/main-es2015.7255cef9dd5f54e0fbb1.js
.\.venv\Scripts\python.exe .audit/module2/public_get.py https://fuzdrop.bio.unipd.it/help
.\.venv\Scripts\python.exe .audit/module2/public_get.py https://fuzdrop.bio.unipd.it/tutorial
.\.venv\Scripts\python.exe .audit/module2/public_get.py https://fuxreiterlab.github.io/contact.html
.\.venv\Scripts\python.exe .audit/module2/inspect_bundle.py
.\.venv\Scripts\python.exe .audit/module2/write_service_audit.py
```

这些 `.audit/` helpers 是本次工作区的私有审计工具，未作为生产抓取器发布。其 GET 限制为
官方公开站点；响应证据见 [http_observations.jsonl](audit/fuzdrop/http_observations.jsonl)。
原文缓存、固定字节 SHA256 和字符位置可用于复核，生产 adapter 不依赖缓存或网页结构。

还通过网页检索工具查看官方 help/tutorial、2022 NAR 论文/机构 PDF、2026 protocol 公开摘要与
reporting summary、作者软件/联系页面；查询词和检查过的 URL 记录在
[service_audit.json](audit/fuzdrop/service_audit.json)。未获取 CAPTCHA token，未执行任何
真实预测 POST，未安装本地 FuzDrop 程序，未代发邮件。结果分类为 C/browser_protected。

## 本地安装与定向检查

仅刷新已有 editable backend 的版本元数据为 0.2.0，不下载/升级依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e ./backend
.\.venv\Scripts\python.exe -m pytest backend/tests/test_fuzdrop_import.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/test_fuzdrop_api.py backend/tests/test_module0.py -q
```

解析器初版 80 项通过；独立复核发现十进制边界和可变 DTO 重验证问题后修复，最终 87 项导入
测试通过。API 与通用契约的定向结果为 47 passed，包含 load/health/analyze/close 故障隔离和
网络 transport 禁用检查。
这些测试使用明确的合成格式样例，未访问真实 FuzDrop。

## 最终门禁

```powershell
.\.venv\Scripts\python.exe -m ruff format --config backend/pyproject.toml scripts/smoke_module2.py
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend scripts
.\.venv\Scripts\python.exe -m compileall -q backend/app backend/lreca_runtime scripts
.\.venv\Scripts\python.exe -m pytest backend/tests -q --junitxml=.audit/module2_full_tests.junit.xml
.\.venv\Scripts\python.exe scripts/smoke_module2.py
git --no-optional-locks diff --stat
git --no-optional-locks diff --check
git --no-optional-locks diff --output=.audit/module2_current_index.diff
.\.venv\Scripts\python.exe .audit/module2_finalize.py
```

完整 pytest 由 `.audit/module2_run_validation.py` 调用上述同一命令并捕获原始 UTF-8 输出；
公开日志将开发机器路径替换为环境引用；JUnit 主机名和两个既有 LRECA 负面测试名称中的
合成 Windows 路径也以变量标记，数值、测试结果及原测试源码不变，原始文件和 SHA256 保留。
第一次 Ruff 指出新 smoke
脚本的两行字符串超长，拆行后重新检查通过；没有改变测试或科学期望来消除失败。

| 最终执行结果 | 记录 |
| --- | --- |
| Ruff | All checks passed |
| compileall | exit 0 |
| Full backend tests | **241 passed、0 failed、0 skipped、2 既有依赖 warning，47.36 s** |
| 实际 HTTP smoke | 7 项检查通过；health/methods 200、FuzDrop health/analyze 503、synthetic import 200、非法坐标 422、真实 LRECA 全链路 200；server_stopped=true |
| 普通 Git diff/check | 已读取并保存，whitespace 通过；包含历史 intent-to-add 文件，因此不用其总数作为 Module 2 清单 |
| Scoped diff / source guard | **44 文件：32 新增、12 修改、0 删除；58 个受保护文件未变** |

公开结果：[完整 pytest](audit/module2_full_tests.log)、[JUnit](audit/module2_full_tests.junit.xml)、
[验证汇总](audit/module2_test_verification_summary.json)、[HTTP 联测](audit/module2_api_smoke/summary.json)、
[差异检查](audit/module2_scope_review.json)。完整 diff 存于 `.audit/module2_exact.diff`。

`smoke_module2.py` 使用真正的临时本机 Uvicorn TCP listener 和 httpx，包含四种方法目录、
FuzDrop unavailable health/analyze、合成格式导入、非法坐标及一次真实 LRECA 预测/Grad-CAM/KDE。
脚本关闭自己启动的服务及其 LRECA worker。FuzDrop 提交数为 0，导入数据有明确 synthetic 标记。
无需启动前端，不产生正式部署，也不改变官方服务状态。

最终 diff 以完整 Module 1 快照为比较基准，另检查 Git 的普通 diff 和 whitespace。专属 guard
核对 LRECA 科学源码、原测试、fixtures、checkpoint manifest、lock、既有模型证据、前端、SEG、
DisMeta 和 orchestrator 保持原字节。清单只计本模块新增/改动；原始 Git index 保持不变。
