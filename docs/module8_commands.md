# Module 8：命令与验收记录

以下命令均从项目相对目录执行，不包含用户绝对路径。命令模板用于复现；是否通过、退出码、测试数量和实际耗时以对应证据为准，不把历史 Module 7 结果或重复定向运行累加为本轮测试数量。

## 前端质量检查

环境沿用项目锁定的 Node.js / pnpm 和前端依赖；未为 Module 8 增加绘图、虚拟滚动或科学计算依赖。从 `frontend` 执行：

```powershell
pnpm test
pnpm lint
pnpm typecheck
pnpm build
pnpm peers check
```

`test` 实际执行 `node --experimental-strip-types --test tests/*.test.ts`；`typecheck` 执行 `next typegen && tsc --noEmit`。本轮本地记录器 `.audit/module8_validate.py` 按上述顺序运行，任一失败即停止后续项。公开输出为 `docs/audit/module8_checks/summary.json` 和对应的 `unit.log`、`lint.log`、`typecheck.log`、`build.log`、`peer_dependencies.log`；原始机器日志仅保存在忽略的 `.audit/module8/`，公开日志移除机器路径和终端控制字符。

本地审计记录器的调用方式：

```powershell
# cwd: project root
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$env:NEXT_TELEMETRY_DISABLED = '1'
& '.venv/Scripts/python.exe' .audit/module8_validate.py
```

此命令包含 production build，不是只读检查。开发时的定向测试可单独运行；它们已经包含在完整前端测试中：

```powershell
# cwd: frontend
node --experimental-strip-types --test tests/sequence-viewer-layout.test.ts
node --experimental-strip-types --test tests/sequence-viewer-model.test.ts
node --experimental-strip-types --test tests/sequence-crosslink-contract.test.ts
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js src/components/protein-sequence-viewer.tsx src/lib/sequence-viewer-layout.ts tests/sequence-viewer-layout.test.ts --max-warnings 0
```

本模块是前端显示与联动工作，不修改科学模型、推理参数、后端 DTO 或 ensemble。没有将历史 backend suite 记作本轮重新执行；已有后端文件与科学证据由冻结基线核对。

## 普通业务与独立测试启动

以下是已有依赖和配置就绪后的交互式启动模板。不要为重复验收无必要地启动多个模型 worker。后端使用单个 Uvicorn worker，`BACKEND_URL` 为 Next 服务端必填配置，不加 `NEXT_PUBLIC_` 前缀。

```powershell
# cwd: project root; backend terminal
$env:PYTHONUTF8 = '1'
& '.venv/Scripts/python.exe' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

普通业务前端在另一终端使用已构建产物：

```powershell
# cwd: frontend; normal business profile
$env:BACKEND_URL = 'http://127.0.0.1:8000'
$env:FEATURE_VIEWER_TEST_MODE = '0'
$env:NEXT_TELEMETRY_DISABLED = '1'
pnpm start --hostname 127.0.0.1 --port 3000
```

普通环境也允许不设置 `FEATURE_VIEWER_TEST_MODE`。只有独立验收进程使用 `1`；其 `BACKEND_URL` 应指向该验收环境的真实本地后端。下面端口只是本机示例，不表示将线上业务后端用于合成测试：

```powershell
# cwd: frontend; separate explicit test profile
$env:BACKEND_URL = 'http://127.0.0.1:8000'
$env:FEATURE_VIEWER_TEST_MODE = '1'
$env:NEXT_TELEMETRY_DISABLED = '1'
pnpm start --hostname 127.0.0.1 --port 3001
```

两者可以复用同一 production build。测试路由 `/dev/sequence-viewer` 与既有 `/dev/feature-viewer` 按服务端请求检查开关；普通 profile 不开放，测试 profile 显示明确的 Synthetic test data 标记。开关与后端 target 都不是客户端配置。门禁证据见 [route_guards.json](audit/module8_browser/route_guards.json)。测试过程结束后，仅停止自己启动的测试进程，业务 profile 保持 `0` 或不设置。

上述路径是 Windows 虚拟环境布局；其他系统使用该平台实际的虚拟环境解释器，例如 `.venv/bin/python`。这不构成 Linux / Docker 实跑声明，也不能将 Windows 虚拟环境或 SEG 二进制直接复制到 Linux。

## 浏览器输入、联动与性能证据

[浏览器记录](audit/module8_browser/browser_verification.json)、[双向联动](audit/module8_browser/crosslink_verification.json)、[响应式记录](audit/module8_browser/responsive.json)分别记录真实页面操作。A 为真实 LRECA-only，B 为真实 LRECA+SEG，C 为真实 SEG-only。D/E 的 LRECA/SEG 仍由真实本地后端执行，FuzDrop 输入明确为 synthetic test-only，经真实本地导入端点校验，不能当作官方预测或生物学证据。

所有输入及其字节哈希见 [fixture README](audit/module8_browser/fixtures/README.md) 和 [manifest](audit/module8_browser/fixtures/fixture_manifest.json)：最终 D 指定使用原完整 scores TSV，保留末尾换行，人工 pLLPS 为 0.68；E 使用人工 pLLPS **0.42** 且不提供任何 TSV。保留的 0.68 global-only 夹具不是本轮 E 输入；去掉末尾换行的 D JSON 只记录初步 UI 输入，不作为最终 D 载荷。最终 D/E 在明确显示 Synthetic test data 的测试 profile 中验收，完成情况以最终浏览器记录为准。

`/dev/sequence-viewer` 使用正式 mapper 和 `ProteinSequenceViewer`，显示明确合成的 100、500、1000、2000、5000 aa，不调用科学模型。它记录 initial render、hover、selection、color 的 handler/mount 到 React commit 的应用执行时间，保留最近 200 条样本；没有样本时显示 Not measured。记录见 [performance.json](audit/module8_browser/performance.json)。scroll 记录是 Computer Use 操作往返及实际滚动位置，不能与组件执行时间、屏幕呈现或推理时间混用。独立首次观测与后续分长度观测分别保留，不取较快一次替代全部结果。

浏览器验收还检查普通点击不强制切 tab、显式 View 操作定位、新分析重置、真实区域复制、首尾残基、固定 50 aa/行、键盘边界和单一可访问入口。工具脚本通过不替代这些真实交互。

## 已保存 API 响应的离线核对

本地 `.audit/module8_api_verify.py` 不提交新任务、不发 HTTP、不导入后端或运行科学模型。它读取本轮已保存的 `case_a_lreca_only.json`、`case_b_lreca_seg.json`、`case_c_seg_only.json`、`case_d_fuzdrop_full.json`、`case_e_fuzdrop_global_only.json`、health、输入夹具及冻结证据，并在 Node 中运行生产纯 mapper：

```powershell
# cwd: project root; after final browser response files are saved
$env:PYTHONUTF8 = '1'
& '.venv/Scripts/python.exe' .audit/module8_api_verify.py
```

唯一公开输出为 `docs/audit/module8_browser/api/regression_verification.json`。比较完整 LRECA / SEG 原生结果时排除运行计时字段，不改变科学值或使用数值容差掩盖差异。Module 8 的 B 对应历史 Module 7 的 C，Module 8 的 C 对应历史 B；FuzDrop E 按实际 0.42 输入核对，不错误套用历史 0.68。旧 144 项证据本身保持冻结；本轮脚本报告等价语义覆盖情况，不宣称重新执行了历史断言程序。

## 客户端隐私与最终范围记录

以下本地审计工具仅在相应产物已经就绪时调用：

```powershell
# cwd: project root; inspect the completed production client build
& '.venv/Scripts/python.exe' .audit/module8_client_privacy.py

# read-only comparison against the original frozen Module 7 baseline
& '.venv/Scripts/python.exe' .audit/module8_finalize.py --check

# only after the final source/evidence freeze; writes two public reports
& '.venv/Scripts/python.exe' .audit/module8_finalize.py --write
```

客户端检查只读构建后的 `.next/static/**/*.js`，输出 `docs/audit/module8_browser/client_privacy.json`，不把检测到的机器路径或内部地址复制进报告。最终器的默认模式与 `--check` 均只读；`--write` 只生成 `docs/module8_changed_files.txt` 和 `docs/audit/module8_scope_review.json`。它使用原冻结文件哈希、源码 ZIP 和 Git index 哈希核对范围，不刷新基线、不修改 Git index、不将权重或环境目录纳入仓库。

`.audit/` 是本地、被 Git 忽略的证据脚本与原始日志目录，不属于发布源码。干净 checkout 不保证包含这些私有脚本；公开复现入口是前面的标准前端命令，公开 JSON / 日志用于查验本轮结果。不要将本节脚本名称误作已经发布的安装工具。

本模块完成后停在 **Module 8**。未进入后续导出扩展、Docker 或部署模块。
