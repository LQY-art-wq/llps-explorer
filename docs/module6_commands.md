# Module 6 命令与验证记录

**Module 6 completed.** 真实浏览器 A–H、最终屏宽/键盘复查、质量 gate、隐私与范围核对通过。

路径均相对项目根目录，未写入开发者 home。Windows PowerShell 读取中文与输出使用 UTF-8；
后端沿用 `.venv`，真实 LRECA 继续由既有 `.lreca-venv` 科学 worker 运行。
本轮不重新运行官方 baseline/benchmark，不更换模型或既有后端依赖。

## 环境与依赖

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
node --version
pnpm --version
```

本轮使用 Node **24.19.0** 原生 TypeScript stripping 执行单元测试；项目声明
`node >=22.13.0 <27`、`pnpm@11.19.0`。前端 `package.json` 为 ES module。
部署/其他机器使用锁文件安装的等价入口：

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
```

`frontend/pnpm-workspace.yaml` 明确设置 `allowBuilds.unrs-resolver: false`。
postinstall 未执行，正常 optional 预编译 binding 在本机可用；没有运行绕过策略的 build 脚本。
其他目标平台须验证其 optional binding 是否可取得，不能据此宣称已经完成 Linux 容器验收。

依赖兼容过程保留两阶段事实：

1. ESLint `10.9.1` 尝试未通过：`react/display-name` 调用 `context.getFilename` 失败，
   React/import/jsx-a11y peer 范围仍止于 ESLint 9。
2. 最终锁定 ESLint **9.39.5** 与 eslint-config-next **16.3.4**；lint 规则未关闭。
   ESLint 9 的 EOL 状态列入开发工具依赖债务；[peer 检查](audit/module6_checks/peer_dependencies.log)
   返回 `No peer dependency issues found`。

## 前端标准检查入口

以下在 `frontend/` 执行，`pnpm test` 即本项目 unit test 入口，没有名为 `unit` 的另一个脚本。

```powershell
pnpm lint
pnpm test
pnpm typecheck
pnpm build
pnpm peers check
```

对应实际脚本：

| 入口 | package script | 当前记录 |
| --- | --- | --- |
| `pnpm lint` | `eslint . --max-warnings 0` | [通过，0 warnings](audit/module6_checks/lint.log) |
| `pnpm test` | `node --experimental-strip-types --test tests/*.test.ts` | [123 passed、0 skipped](audit/module6_checks/unit.log) |
| `pnpm typecheck` | `next typegen && tsc --noEmit` | [通过](audit/module6_checks/typecheck.log) |
| `pnpm build` | `next build` | [通过](audit/module6_checks/build.log) |
| `pnpm peers check` | pnpm 内建依赖检查 | [通过](audit/module6_checks/peer_dependencies.log) |

每项实际 cwd、command、exit code 与耗时见 [检查汇总](audit/module6_checks/summary.json)。
焦点和卡片最后修改后已再次运行同一 gate，全部 exit 0。最终命令耗时：unit 2.292 s、
lint 20.248 s、typecheck 5.457 s、build 17.186 s、peer check 0.904 s、pytest 2.540 s、
Ruff 0.883 s；不把多次相同测试累计为新测试数。

开发期为避开依赖安装中的命令解析干扰，直接使用当前已安装的 CLI；没有通过 `pnpm exec`
临时下载另一套 lint 工具。FuzDrop 三个自有文件的实际定向检查为：

```powershell
node node_modules/eslint/bin/eslint.js src/components/fuzdrop-import-dialog.tsx src/lib/fuzdrop-form.ts tests/fuzdrop-import.test.ts
node --test tests/fuzdrop-import.test.ts
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

该轮结果：lint **0 errors / 0 warnings**，表单测试 **13 passed / 0 skipped**，tsc exit 0。
13 项包含在 123 项整体测试中，不额外累计。React 19 规则发现的渲染读 ref、effect 同步重置
状态和依赖警告已通过会话挂载/卸载设计修复，没有屏蔽规则。

真实浏览器发现 native dialog 首个 Close 按 Shift+Tab 后焦点到 BODY，随后新增共享
`trapDialogFocus` 并补充两个文件输入的唯一 aria-label，执行以下定向检查均通过：

```powershell
node node_modules/eslint/bin/eslint.js src/lib/focus.ts src/components/fuzdrop-import-dialog.tsx
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

独立故障测试入口另执行以下命令，结果为 **3 passed**、Ruff 通过：

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_module6_test_backend.py -q
.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml scripts/module6_test_backend.py backend/tests/test_module6_test_backend.py
```

## 启动真实后端与前端

下列是可复现的本地启动入口；实际浏览器 A–G 使用 `3000 → 8000`，H 使用独立 `3001 → 8001`。
本地 loopback 地址只是操作示例，不是浏览器 bundle 或前端源码中的固定 API target。

后端终端，在项目根目录：

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

前端终端，开发模式：

```powershell
Set-Location frontend
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
$env:BACKEND_URL = 'http://127.0.0.1:8000'
pnpm dev
```

如用 production build 做本地浏览器验收，在同样设置服务端环境变量后：

```powershell
pnpm build
pnpm start --hostname 127.0.0.1 --port 3000
```

`pnpm start` 本身是 `next start`，没有固定绑定主机。`BACKEND_URL` 必填且无默认值，
只由 Next 服务端读取；不能使用 `NEXT_PUBLIC_` 前缀向浏览器公开内部地址。
修改运行时 `BACKEND_URL` 后重启 Next 即可，不需要仅为 target 变化重新 build。
浏览器始终请求同源 `/api/v1`；代理仅转发允许的 JSON 路径，不回传上游 URL、内部路径或堆栈。
未来容器可设置其内部服务地址，但本轮没有运行 Docker production deployment。

## 真实浏览器 A–G

浏览器从实际运行的 Next 页面操作，使用
[真实序列与合成 FuzDrop 格式素材说明](audit/module6_browser/fixtures/README.md)。

1. A：只选择 LRECA，记录真实 job 创建、轮询、human-specific score、P/N 与解释摘要。
2. B：只选择 SEG，记录实际 LCR 区域、覆盖率、数量与最长区间；不得出现 LLPS P/N。
3. C：LRECA + SEG，核对原生结果分别展示。
4. D：FuzDrop 未导入，检查不能启用该方法及 weighted，显示原因。
5. E：使用明确标记的 synthetic-format TSV 与 pLLPS `0.68` 完成导入；导入后仍未选择 FuzDrop。
6. F：用户明确启用导入，再选择 weighted；展示后端 ensemble，前端不计算科学分数。
7. G：DisMeta 显示 unavailable，运行和导入均无入口。

A–G 均已在真实浏览器通过，DOM 证据及既有任务响应如下：

| 场景 | 实际结果与证据 |
| --- | --- |
| A | [LRECA success](audit/module6_browser/A_lreca_final.dom.txt)，job `analysis_W8l-lBcO6Z_1ny4fL0Kbp9HNtDPNTUKe` |
| B | [SEG success](audit/module6_browser/B_seg_regions.dom.txt)，job `analysis_EkIcjZMi2a3_0HQUWJUnwBWbJBMlOmJU` |
| C | [双方法 success](audit/module6_browser/C_pair_final.dom.txt)，job `analysis_JudSoFFg8_5GoHWD12DMxi-WfM2xaUtN` |
| D/G | [未导入 FuzDrop / blocked DisMeta](audit/module6_browser/D_G_no_import.dom.txt)，控件禁用原因正确 |
| E | [成功导入](audit/module6_browser/E_import_success.dom.txt) 后[仍未启用](audit/module6_browser/E_import_not_enabled.dom.txt) |
| F | [Weighted success](audit/module6_browser/F_weighted_final.dom.txt)，job `analysis_Uodx6jZdPTwux5xqQzibn7JftE95jypS` |

LRECA 实际 CUDA 分数为 `0.9999921321868896`，P，248 项 attribution/KDE。
SEG 为 72–85、89–119、196–247 三个区间，coverage `97/248`，最长 52 aa。
F 的后端 `0.6/0.4` 加权值为 `0.8719952793121338`，并保留 `not_calibrated` 和
`experimental_weighted_score`。上述 FuzDrop 数值仅用于软件契约测试，不能登记为官方预测。

浏览器完成后通过同源 proxy GET 读取既有任务，核对脚本未提交新分析。
[verification.json](audit/module6_browser/api/verification.json) 保存 **110 项通过的检查**、
全部响应文件 SHA256、实际下载文件核对及 H 的追加记录。原生下载事件未被 CUA 返回；
实际 Downloads 文件存在，已原字节复制至 [F_download.json](audit/module6_browser/api/F_download.json)，
127055 字节，SHA256 `c088a62c232bb6a05f3a67e5e781f495aad8d8ee96378466126f6429f678ff5d`。
解析后的完整对象与同源 GET 任务严格相等，不以工具事件缺失判定下载失败，也不伪造下载事件。

额外浏览器检查留下 [残基错配错误](audit/module6_browser/E_mismatch_error.dom.txt)、
[输入变更后引用失效](audit/module6_browser/import_invalidation.dom.txt) 和
[非法残基输入](audit/module6_browser/invalid_residue.dom.txt)。
History 实测选回原 B 任务时保留原 job ID 和 SEG 结果；结果 tabs 的 ArrowRight、End、Home
键操作已通过浏览器检查。
最终 production build 又运行 C，完整 LRECA/SEG 科学对象与之前任务相同；变化仅限新任务身份、
时间和耗时。对应 11 项追加核对保存在 verification.json 的 `C_final_build` 记录。

## H：显式测试后端的 partial success

使用独立终端从项目根目录启动，不替换正常生产入口：

```powershell
.venv\Scripts\python.exe scripts/module6_test_backend.py --fail-seg --port 8001
```

该脚本必须显式传 `--fail-seg`。它保留真实 LRECA 推断、SEG load/health、原始任务服务与调度器，
只让 SEG analyze 产生指定测试异常。启动提示明确标记 TEST ONLY，既有生产 config/main 无故障开关。

H 使用专用前端进程：

```powershell
Set-Location frontend
$env:BACKEND_URL = 'http://127.0.0.1:8001'
pnpm start --hostname 127.0.0.1 --port 3001
```

在浏览器选择 LRECA + SEG，已确认 `partial_success`、真实 LRECA 成功卡及 SEG 失败卡。
验收后停止测试后端和该前端进程，恢复正常后端 target。不是向生产服务注入 mock 结果。

H job 为 `analysis_HEsw-VBCJjw4ssQ-6uxvvdk_22vR5_mW`；LRECA score
`0.9999921321868896`，P，248 项 attribution/KDE；SEG 为 failed，result null，
错误码 `METHOD_EXECUTION_FAILED`，ensemble null。页面仍展示成功预测，没有变成整页错误。
证据：[DOM](audit/module6_browser/H_partial_success.dom.txt)、
[截图](audit/module6_browser/H_partial_success.jpg)、[H_job.json](audit/module6_browser/api/H_job.json)。

## 响应式、键盘与最终范围检查

最终构建已实际检查 1440、1280、1024 px：document clientWidth 分别为 1425、1265、1009，
main 宽度分别为 1105、945、1009；前两种 sidebar 为 320 px，1024 时折叠。
document/main 的 scrollWidth 均等于对应 clientWidth，没有横向溢出。
证据：[1440](audit/module6_browser/1440_final.jpg)、[1280](audit/module6_browser/1280_final.jpg)、
[1024](audit/module6_browser/1024_final.jpg)、[1024 抽屉](audit/module6_browser/1024_drawer.jpg)、
[1024 暗色主题](audit/module6_browser/1024_dark.jpg)。

最终键盘复查结果：1024 抽屉初焦点 sequence-name，main/header inert，Shift+Tab 从 Close 到 Run，
Escape 返回 Analysis setup；Import modal Close/Cancel 双向 Tab 与 Escape 返回触发按钮通过；
Documentation modal Close/Done 首尾导航及 Escape 返回 Documentation 通过。
两个 TSV file label 区分、结果 tabs 键盘与 History 原任务复现均已验证。

已完成的 A–H、最终 C 科学复核、下载、质量检查、屏宽和键盘证据按上文保存。
[浏览器汇总](audit/module6_browser/summary.json) 记录所有八项场景通过，控制台无 warning/error，
viewport override 已 reset，partial-fixture 标签已关闭，正常预览标签保留。

## Client 隐私、进程清理与封版范围

[Client 隐私检查](audit/module6_browser/client_privacy.json) 扫描最终
`frontend/.next/static/**/*.js`：**10 个文件、641654 字节**。实际本机路径、`BACKEND_URL`
变量、正常/故障测试后端 target 及示例容器 target 均未进入这批 production client JavaScript。
没有为验证而把实际内部路径或地址列表写入公开报告。

[清理记录](audit/module6_browser/cleanup.json) 确认 H 专用前端及其测试后端/科学 worker 均已停止。
正常 `3000 → 8000` 本地预览保留；保留预览不代表公开部署或 Linux/Docker 验收。

范围核验与封版输出入口，从项目根目录执行：

```powershell
.venv\Scripts\python.exe .audit/module6_finalize.py --check
.venv\Scripts\python.exe .audit/module6_finalize.py --write
```

`--check` 为只读检查，已通过；`--write` 仅在文档冻结后生成
[变更清单](module6_changed_files.txt) 和 [范围报告](audit/module6_scope_review.json)。
从 **287 个文件**的起点快照得到 **97 个变更：86 新增、11 修改、0 删除**，
计数包含上述两个输出；**274 个受保护历史文件 SHA256 不变**。
权重未 track、上游固定 commit 且 tracked worktree clean、Git index 无变化，`git diff --check` 通过。
3 处原有机器日志空白保留为非阻断观察，未为了检查通过而修改原始日志；新改源码和文档行的空白检查通过。

Module 6 completed. 停止于本阶段，不进入 Module 7。
