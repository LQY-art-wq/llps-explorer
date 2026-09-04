# Module 4 实际命令与验证记录

从项目根目录执行，PowerShell 中文使用 UTF-8。没有修改 Git index、提交/回滚既有文件，
没有调用猜测的外部 job endpoint、发送邮件或运行替代预测器。

## 起始快照与官方审计

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe .audit/module4_snapshot.py
.venv/Scripts/python.exe .audit/module4_probe.py https://montelionelab.chem.rpi.edu/dismeta/ https://montelionelab.chem.rpi.edu/dismeta/references.html https://montelionelab.chem.rpi.edu/index.php/our-software-2/
```

起始快照为完成 Module 3 的 **192 个文件**：`.audit/module4_start_files.json` 和
`.audit/module4_start_source.zip`。GET 使用三条已明确的官方 URL，TLS 验证始终开启。
第一次 helper 在 httpx 初始化阶段因未安装 SOCKS 支持而失败，尚未发出 HTTP；仅修改该私有审计
helper，显式沿用环境已有 HTTP(S)_PROXY，避开未使用的 ALL_PROXY。没有安装新依赖或修改环境。
重试后三个 GET 均 ConnectTimeout，约 15 s；没有获得原始 HTML/状态/cookie/form action。
[原始观察记录](audit/dismeta/http_observations.jsonl) 保存日期、URL、失败类型和耗时。

检索工具成功读取官方主页、软件/参考文献页和原论文的 PMC 索引全文；未将索引文本称为原始HTTP字节。
直接 PMC/PubMed 出现浏览器验证时没有继续操作，作者机构索引直接 GET 握手超时。
一次 Chrome 正常导航超时约 36.7 s，后续 AX 读取超时约 34.7 s；没有操作表单或得到可核查DOM。
这些浏览器工具超时不是服务HTTP状态码，也不能证明官方已停服。
科学正文、来源质量和私有解析文本 SHA256 见
[scientific source evidence](audit/dismeta/scientific_source_evidence.json)。

## 定向实现验证

```powershell
.venv/Scripts/python.exe -m pytest backend/tests/test_dismeta_contract.py -q
.venv/Scripts/python.exe -m pytest backend/tests/test_dismeta_api.py backend/tests/test_module0.py -q
```

contract 48 passed / 0.45 s；API 与通用契约 50 passed / 1.57 s（两个既有依赖 warning）。
这些是 unavailable/输入/失败隔离/隐私和明确合成的坐标数学契约测试，**不是 DisMeta 预测回归**。
无原生格式依据，因此没有编造 raw output fixture，也没有创建自动或 manual import parser。

```powershell
.venv/Scripts/python.exe -m ruff format --config backend/pyproject.toml backend/app/schemas/dismeta.py backend/app/adapters/dismeta.py backend/tests/test_dismeta_contract.py scripts/smoke_module4.py
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e ./backend
```

格式化只处理本轮新建/实现文件。editable install 仅刷新项目 0.4.0 元数据，没有更新依赖锁。
早先复制 smoke helper 的内联 Python 命令发生引号 SyntaxError，未执行任何文件写入；
改用 PowerShell literal here-string 后成功，旧 smoke_module3.py 未修改。

## 完整后端门禁与实际 HTTP

```powershell
.venv/Scripts/python.exe .audit/module4_run_validation.py
.venv/Scripts/python.exe -m ruff check --config backend/pyproject.toml backend scripts
.venv/Scripts/python.exe -m compileall -q backend/app backend/lreca_runtime scripts
.venv/Scripts/python.exe -c "from app.main import app; from app.adapters.dismeta import DisMetaAdapter; from app.schemas.dismeta import DisMetaHealth; import sys; assert 'torch' not in sys.modules; print('FastAPI/DisMeta import passed; no scientific runtime loaded')"
.venv/Scripts/python.exe scripts/smoke_module4.py
```

validation 实际执行 `python -m pytest backend/tests -q --junitxml=.audit/module4_full_tests.junit.xml`。
原 stdout/stderr 和 JUnit 留在 `.audit`；公开版本隐藏内部路径、hostname、旧合成Windows负面测试路径，
log 另统一LF、去行末空白并增加来源行。没有改变原测试证据字节。
最终 [log](audit/module4_full_tests.log)、[JUnit](audit/module4_full_tests.junit.xml) 与
[统计/证据SHA256](audit/module4_test_verification_summary.json) 提供实际计数及耗时。
最终为 **471 passed、0 skipped、2 warnings、51.48 s**；Ruff、compile/import通过。

smoke 启动临时 loopback Uvicorn/TCP，通过实际 HTTP 验证 DisMeta 503、非法输入422、import404、
methods，并在同次运行检查真实 SEG、LRECA prediction/Grad-CAM/KDE 和合成格式 FuzDrop manual import。
FuzDrop 合成输入明确标注为格式测试，DisMeta 没有成功预测或第三方请求。
记录 [HTTP summary](audit/module4_api_smoke/summary.json) 以及服务/worker关闭和日志隐私状态。
实际13项检查通过，本地DisMeta unavailable往返2.8487 ms（不是官方预测延迟）；服务已关闭，日志不含完整测试序列。

## 差异与保护验证

```powershell
.venv/Scripts/python.exe .audit/module4_finalize.py
git --no-optional-locks diff --stat
git --no-optional-locks diff --check
git --no-optional-locks diff --no-ext-diff --no-textconv --output=.audit/module4_git.diff
```

模块实际范围以192文件快照为准，不把包含旧scaffold的普通Git diff当作本模块文件数。
scoped no-index diff、whitespace与保护文件SHA256结果见
[scope review](audit/module4_scope_review.json)；完整清单见
[module4_changed_files.txt](module4_changed_files.txt)。
既有 SEG test_seg_api.py 仅更新 DisMeta 目录 reason 的一行过期断言；其他既有科学实现、SEG真实
输出/测试、LRECA/FuzDrop tests和旧报告保持原字节。外部服务文档的 FuzDrop section 原文单独核对不变。

Module 4 决策与局限见 [module4_report.md](module4_report.md)。
