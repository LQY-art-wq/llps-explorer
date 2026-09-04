# Module 3 实际执行命令与证据

所有命令从仓库根目录执行。PowerShell 中文输出设置 UTF-8；本文使用相对路径或配置变量，
不写开发用户绝对路径。`.audit` 是私有忽略证据目录，`.tools` 是忽略的官方工具缓存。

## 初始边界与官方工具获取

读取当前模块请求、Module 0/1/2 文档、原实现与测试，保存完成 Module 2 的 146 文件 SHA256
快照和源码 ZIP：`.audit/module3_start_files.json`、`.audit/module3_start_source.zip`。
全过程不修改 Git index、提交或回滚既有用户文件。

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe .audit/module3_snapshot.py
.venv/Scripts/python.exe .audit/module3_acquire_seg.py
.venv/Scripts/python.exe .audit/module3_probe_seg.py
```

获取官方 Windows 2.17.0+ tar 与校验文本，143,400,333 bytes；MD5 与官方一致，计算 archive
和 executable SHA256。只提取 segmasker、同包 DLL 与说明材料，真实执行 `-version`、`-help`
及八个输入，将原始 stdout 字节先保存，再实现 parser。没有执行 GUI installer 或改变全局 PATH。
另实际读取固定版本 source ZIP 及七个相关成员，核对默认参数/坐标/合并语义：
[source audit](audit/seg/source_audit.md)。Linux 仅读取发行目录与官方 MD5 文本。

公开可复用安装工具完成后，本机实际执行：

```powershell
.venv/Scripts/python.exe scripts/setup_seg.py --help
.venv/Scripts/python.exe scripts/setup_seg.py --platform windows-x64 --destination .tools/seg --archive .tools/seg/downloads/ncbi-blast-2.17.0+-x64-win64.tar.gz --offline
```

offline 安装执行两次：第一次复用原 6 文件，仅增加同包 doc/README.txt；第二次 files_created=0。
两次均无网络请求。没有重新下载 Windows 大包。机器记录见
[seg-source.json](../external/seg-source.json)。ignored 根 `.env` 配置为仓库相对 executable 路径，
其他部署通过 `SEG_EXECUTABLE_PATH` 或 PATH 配置。

## 定向实现检查

```powershell
.venv/Scripts/python.exe -m pytest backend/tests/test_seg_parser.py -q
.venv/Scripts/python.exe -m pytest backend/tests/test_seg_api.py backend/tests/test_module0.py -q
.venv/Scripts/python.exe -m pytest backend/tests/test_seg_process.py backend/tests/test_seg_integration.py -q
```

最终定向结果分别为 67 passed、65 passed、33 passed，均无 skip。API/通用定向检查初次为
55 passed；最后增加窗口溢出、构造失败隔离和版本状态映射检查后为 65 passed。首次 integration helper
取错仓库父目录，导致 13 项标为 executable missing 而跳过；修正测试发现路径后真实二进制用例
全部执行通过。该问题发生在测试定位代码，未修改科学输出或用模拟 SEG 响应代替真实执行。
进程测试包含实际子进程超时、任务取消和关闭后的回收；测试用 Python 小进程仅用于进程失败行为，
与官方 SEG 科学回归明确区分。

## 性能与后端安装元数据

```powershell
.venv/Scripts/python.exe scripts/benchmark_seg.py
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e ./backend
```

五种长度、每种一次预热和五次计时，中位数约 37–40 ms。完整原始数据见
[performance.json](audit/seg/performance.json)。editable install 仅刷新 0.3.0 项目元数据，
未升级依赖或修改锁文件。

## 完整门禁

```powershell
.venv/Scripts/python.exe .audit/module3_run_validation.py
.venv/Scripts/python.exe -m ruff check --config backend/pyproject.toml backend scripts
.venv/Scripts/python.exe -m compileall -q backend/app backend/lreca_runtime scripts
.venv/Scripts/python.exe -c "from app.main import app; from app.adapters.seg import SEGAdapter; from app.schemas.seg import SEGResult; print('SEG and FastAPI import check passed')"
.venv/Scripts/python.exe scripts/smoke_module3.py
```

validation helper 实际执行 `python -m pytest backend/tests -q --junitxml=.audit/module3_full_tests.junit.xml`，
原始 stdout/stderr 和 JUnit 留在 `.audit`；公开导出替换内部路径、hostname 与既有 LRECA
负面路径测试的合成 Windows 路径标识。公开 log 另统一 LF、去行末空白并加来源说明首行；
不改原测试文件或原始证据字节。结果见
[完整日志](audit/module3_full_tests.log)、[JUnit](audit/module3_full_tests.junit.xml) 和
[验证摘要](audit/module3_test_verification_summary.json)。

首次全套为 379 passed、0 skipped、2 warnings、63.94 s。最终审查补齐 `SEG_WINDOW` 的 native
整数上限、把 SEG 构造纳入独立初始化保护，并保留版本不支持的 503 状态；新增 10 个相关测试。
修复后再次运行完整套件，最终为 **389 passed、0 skipped、2 warnings、50.32 s**，与最终日志/JUnit 一致。第一次原日志另存
`.audit/module3_initial_full_tests.log` 和 `.audit/module3_initial_full_tests.junit.xml`，未覆盖丢弃。

曾直接运行未指定项目配置的 `ruff check backend scripts`，其父目录规则报告 11 项额外规则问题，
涉及既有脚本及新脚本；未为此改动受保护旧脚本。按 README 规定显式使用
`--config backend/pyproject.toml` 后，整个 backend/scripts 门禁通过。compile/import 检查通过。

smoke 启动实际临时 loopback Uvicorn/TCP 服务，通过真实 HTTP 验证 SEG health/methods/
真实序列/无区域/非法序列，并检查既有 FuzDrop 不可用状态和 LRECA prediction/Grad-CAM/KDE。
只向本地后端发 HTTP，官方 FuzDrop 提交数为 0；完成后关闭自己启动的服务及 worker。
输出见 [实际 HTTP 摘要](audit/module3_api_smoke/summary.json)。

## 变更与保护范围复核

```powershell
.venv/Scripts/python.exe .audit/module3_finalize.py
git --no-optional-locks diff --stat
git --no-optional-locks diff --check
git --no-optional-locks diff --no-ext-diff --no-textconv --output=.audit/module3_git.diff
```

普通 diff 因尚无首次提交包含历史 scaffold；精确模块范围以本轮开始的 146 文件快照为基准。
finalize helper 对原字节快照执行 no-index diff、whitespace check、保护文件 SHA256 和范围检查，
差异保存在 `.audit/module3_exact.diff`，公开范围摘要见
[module3_scope_review.json](audit/module3_scope_review.json)。真实 CRLF stdout fixture 不做文本
换行转换，scoped whitespace 检查将 CR 视为合法行尾。首次检查指出官方 `help.txt` 最后有一个
空行；与最初 probe 原字节核对后保留，并只对该已知源码格式记录例外，其他 whitespace 项仍检查。
`.gitattributes` 同步说明这一原始输出规则。未新增模型权重或官方二进制到 Git。

最终计数、HTTP 结果和停止边界见 [module3_report.md](module3_report.md)。
