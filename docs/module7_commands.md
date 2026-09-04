# Module 7：命令与验收记录

所有路径按项目相对位置表达。命令记录与浏览器/API 证据相互补充；Node 测试时间不替代图形交互性能，production build 成功也不替代真实浏览器验收。

## 完整质量检查

从 `frontend` 执行，环境 Node 24.19.0、pnpm 11.19.0、Windows。最终记录起止为 2026-09-03 14:37:04–14:37:32 UTC；[summary.json](audit/module7_checks/summary.json)保存退出码、时间和命令，全部通过。

| 命令 | 结果 | wall seconds | 日志 |
| --- | --- | --- | --- |
| `pnpm test` | 258 passed / 0 failed / 0 skipped | 1.851 | [unit.log](audit/module7_checks/unit.log) |
| `pnpm lint` | exit 0 | 11.461 | [lint.log](audit/module7_checks/lint.log) |
| `pnpm typecheck` | exit 0 | 4.336 | [typecheck.log](audit/module7_checks/typecheck.log) |
| `pnpm build` | exit 0 | 9.390 | [build.log](audit/module7_checks/build.log) |
| `pnpm peers check` | exit 0 | 0.903 | [peer_dependencies.log](audit/module7_checks/peer_dependencies.log) |

`pnpm test` 实际使用 `node --experimental-strip-types --test tests/*.test.ts`；`typecheck` 使用 `next typegen && tsc --noEmit`。258 项包含原 123 项及新增 135 项，没有把重复定向运行相加。后端未改，本模块未重新运行历史 726 项 backend tests。

## 定向检查入口

这些命令用于开发时定位具体风险，属于上面整套测试的子集：

```powershell
# cwd: frontend
node --experimental-strip-types --test tests/feature-harness.test.ts
node --experimental-strip-types --test tests/feature-viewer-model.test.ts tests/viewer-data.test.ts
node --experimental-strip-types --test tests/feature-integration-contract.test.ts
node --experimental-strip-types --test tests/feature-coordinates.test.ts tests/feature-view-state.test.ts
node node_modules/typescript/bin/tsc --noEmit --incremental false

node node_modules/eslint/bin/eslint.js src/app/dev/feature-viewer/page.tsx src/components/feature-viewer-fixture.tsx src/lib/feature-test-fixtures.ts tests/feature-harness.test.ts --max-warnings 0
```

没有新增绘图库、安装替代科学 predictor、修改模型权重或关闭 lint 规则。

## 本地配置与启动

Next 必须配置 server-only `BACKEND_URL`，没有默认后端地址，不使用 `NEXT_PUBLIC_BACKEND_URL`。可复制 `frontend/.env.example` 为 `.env.local` 后按实际环境设置。普通环境保持 `FEATURE_VIEWER_TEST_MODE=0` 或未设置。两项配置按服务端请求/运行时使用，更改后重启 Next 即可，不必只为切换目标重建。

以下为可复现的本地交互式启动模板；端口可以按本机实际分配，示例不代表部署。已有服务运行时应复用，避免重复模型 worker。

```powershell
# cwd: project root; PowerShell UTF-8
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
& '.venv/Scripts/python.exe' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

在单独终端启动已经构建的普通前端：

```powershell
# cwd: frontend
$env:BACKEND_URL = 'http://127.0.0.1:8000'
$env:FEATURE_VIEWER_TEST_MODE = '0'
pnpm start --hostname 127.0.0.1 --port 3000
```

仅在独立验收环境启用合成 harness：

```powershell
# cwd: frontend; explicit test profile, example port
$env:BACKEND_URL = 'http://127.0.0.1:8000'
$env:FEATURE_VIEWER_TEST_MODE = '1'
pnpm start --hostname 127.0.0.1 --port 3001
```

同一生产构建的 `/dev/feature-viewer` 在普通 profile 实测为 404，test profile 为 200，见[门禁记录](audit/module7_browser/route_guards.json)。测试页与测试工作区有显著 Synthetic test data 横幅，不在普通工作区预填数据。CLI 的 hostname 可按部署环境选择，本模块没有 Linux/Docker 或正式部署实测声明。

## 真实浏览器与 API

[浏览器记录](audit/module7_browser/browser_verification.json)包含 28 项通过检查：A 真实 LRECA、B 真实 SEG、C 两方法同图；D/E 的 LRECA/SEG 仍真实，FuzDrop 是明确合成且经过真实本地导入端点的完整/global-only 输入。另验证共享坐标、cursor、wheel/pan/brush、visibility、表格联动、三种屏宽、五长度、首尾单残基区间、malformed 可选轨道隔离与 new-analysis reset。

A–E 与 1440/1280/1024 在本模块首次 production build 验收；后续为区分宿主 rAF 限帧与应用执行时间而修改计时定义及说明，科学映射及原值保留规则不变。最终普通 production build 从 UI 再运行真实 C，记录于 `scenarios.C_final` 与 [C_final_build_1440.jpg](audit/module7_browser/C_final_build_1440.jpg)，确认无 synthetic 横幅、106/G tooltip、深色主题及无 console error/warning。同轮测试 profile 另验证 nullable pDP 和 keyboard track visibility。深色检查后已恢复浅色和视口。

[API 核对](audit/module7_browser/api/real_result_verification.json)对五个已经由浏览器创建的 job 只读 GET，全部 HTTP 200，144/144 checks；保存 `A_job.json` 至 `E_job.json` 原响应字节和 SHA。核对阶段 `submitted_new_jobs=0`、`official_remote_requests=0`，与此前浏览器创建这些本地分析作业是不同步骤。

D 的完整请求与 E 的 global-only 请求见[夹具目录](audit/module7_browser/fixtures/README.md)。FuzDrop pLLPS/pDP/Sbind/regions 均为合成格式测试数据，来源不是独立认证的官方预测；素材不预造 result ID。真实 LRECA/SEG 对象与 Module 6 参考保持相等，跨次运行时间不要求相等。

## 性能采样定义

Harness 调用同一 production mapper 和 Viewer，生成明确合成的 100、500、1000、2000、5000 aa。无需对长序列执行任何科学模型。Performance API 分别记录：

- 初始组件 mount/交互 handler 到 React commit：每长度 initial n=1、zoom n=3、hover n=5。
- Canvas 绘制函数同步实际执行：first/latest/max/count；未完成有效绘制不产生成功样本。

原始属性包括 `data-profile-kind/count/median-ms/p95-ms/max-ms`、`data-profile-latest-kind/ms` 及 Canvas 的 `data-static-first-draw-ms`、`data-static-last-draw-ms`、`data-static-draw-max-ms`、`data-static-draw-count`。DOM 属性保留原浮点，显示文本才舍入。每长度一个 Canvas、225 个被测 Viewer DOM 节点，hover 前后 draw count 相同。

详细五长度表见[报告第 13 节](module7_report.md#13-长序列与实际性能)。这只是少量操作验收，不是统计严谨的 benchmark；不测 screen presentation、GPU 完成、模型推理或完整端到端等待。5000 aa 分长度记录的首次 Canvas 为 9.70 ms，独立冷观测首次 Canvas **13.80 ms**、mount→commit **10.30 ms**，两者均保留。

IAB 隐藏宿主早期约 2 秒的 double-rAF 限帧观测保存在[原记录](audit/module7_browser/background_throttling_observation.json)。测量定义变更有明确说明，没有删除较慢记录或把后台调度延迟混入同步执行时间。

## 隐私和范围

浏览器只访问同源 `/api/v1`。生产 bundle 扫描结果见[client_privacy.json](audit/module7_browser/client_privacy.json)，检查真实本机路径、BACKEND_URL 设置及内部 backend targets 不进入 client JS。测试保护、科学模型锁和原测试冻结不通过改变 backend 来规避。

本模块不训练模型，不重算 attribution/KDE/regions，不改变 weighted ensemble，不接入 DisMeta replacement，也不绕过 FuzDrop 服务保护。完成 Module 7 的交付范围后停止，不进入 Module 8。

## 最终清理与文件审计

停止测试预览前先核对其进程属于本项目 Next `start` 且端口为 3001，随后只停止该进程树。普通 3000 预览和已有真实 8000 后端保留；测试 tab 关闭、viewport override 清除、浅色恢复。普通工作区/health 200、测试路由 404、测试服务已停止以及最终真实 job success，见[final_readiness.json](audit/module7_browser/final_readiness.json)。临时进程 PID 和宿主路径仅在忽略的本地审计目录中保存。

本地只读核对和最终报告生成使用本模块审计脚本：

```powershell
# cwd: project root; private audit scripts, no staging/commit
& '.venv/Scripts/python.exe' .audit/module7_client_privacy.py
& '.venv/Scripts/python.exe' .audit/module7_finalize.py --check
& '.venv/Scripts/python.exe' .audit/module7_finalize.py --write
```

这些脚本不属于发布代码；其输出分别归档为 client privacy、[范围审计](audit/module7_scope_review.json)与[变更清单](module7_changed_files.txt)。原 373 文件 manifest/ZIP、Git index 起始 SHA、历史科学文件与测试均作为不变基线；没有更新基线、删除旧证据或将权重加入仓库。

浏览器全页截图在长 harness 页面出现宿主 capture 失败，改用同一浏览器的 viewport 截图保留证据；没有改用截图时间作为绘图性能。正式 C 的全页截图保存成功，五长度图与计时原始 DOM 记录齐全。
