# Module 7 — Synthetic test data

本目录与 `/dev/feature-viewer` 仅供界面、坐标和渲染性能验收。合成值不是官方预测，不是模型推理、实验验证或校准数据；不得用于科研结论，也不会预填普通工作区。

## 真实组件的合成渲染夹具

测试页默认返回 404；只有 Next 服务端明确设置 `FEATURE_VIEWER_TEST_MODE=1` 才启用，设置不使用 `NEXT_PUBLIC_`。门禁按服务端请求读取。页面显著展示 “Synthetic test data”。普通工作区不使用该夹具。实际 HTTP 门禁和浏览器交互证据由本轮浏览器验收另行记录；纯函数开关测试不代表完成 HTTP 验收。

[夹具生成器](../../../../frontend/src/lib/feature-test-fixtures.ts) 生成 100、500、1000、2000、5000 aa，默认 5000 aa。序列是 `ACDEFGHIKLMNPQRSTVWY` 重复并截取到指定长度，SHA-256 根据该序列计算。它生成现有 `AnalysisJob` 与配对输入快照，经正式 `buildFeatureViewerModel` 映射，由同一个 `ProteinFeatureViewer` 显示六条轨道。

- LRECA attribution 使用明确的合成正弦值；KDE 使用包含大于 1 数值的合成余弦值，验证密度显示不会当作概率裁剪。这些值没有运行 Grad-CAM 或 KDE 算法。
- FuzDrop pDP 使用确定的合成周期数值，每 97 位保留一个 `null`；Sbind 可大于 1。区域包含重叠、完全重复、首尾及单残基边界，用于检测合并、去重或坐标偏移。
- SEG 使用人工指定的三个区间；不存在 DisMeta 伪造轨道。所有区间都是 1-based inclusive。
- 夹具中的模型身份、设备、固定时间和 `runtime_ms=0` 仅为 DTO 结构占位，不表示真实软件运行。模型 SHA 为零值、checkpoint 显式包含 `SYNTHETIC_RENDER_FIXTURE_NO_MODEL`，每项方法及作业均带合成警告。

切换长度或点击 “New analysis / reset state” 会生成新的作业 ID，并重挂载正式 Viewer 会话，清除选区、选中位点、视域及当前性能样本。页面显示组件首次挂载或交互 handler 至 React commit 的应用更新耗时；Canvas 另记录首次、最近和最大同步绘图执行时间。这些值不含后续屏幕呈现、GPU raster、推理或整页加载时间。宿主对 rAF 的限帧观测单独归档。最多保留当前分析最近 200 条样本，按事件统计数量、中位数、nearest-rank p95 和最大值；尚未测量显示 `Not measured`，不写入虚构的零耗时。

可选 “Malformed FuzDrop pDP · isolation test” 场景在内存中将一个合成 pDP 行的 `position` 故意改成 0；页面显著说明错误是人为注入。正式 mapper 必须将该轨道标为 `invalid`，其余五条轨道（含 FuzDrop regions）逐值保留。该损坏对象不是导入请求，不通过 backend parser，也不声称是已验证的官方结果。切换场景同样会生成新分析 ID 并重置会话。

## 真实本地导入流程的合成输入

[manifest](fixture_manifest.json) 记录所有素材的 SHA-256 与来源。以下输入沿用 Module 6 的真实 248 aa 序列及既有导入语法，所有 FuzDrop 分数和区间仍为合成。

| 文件 | 用途 |
| --- | --- |
| [human_positive_line_1.fasta](human_positive_line_1.fasta) | 原 LRECA 真实基线序列，原字节复制 |
| [synthetic_fuzdrop_import_248aa.json](synthetic_fuzdrop_import_248aa.json) | 完整合成导入请求：pLLPS 0.68、248 行 pDP/Sbind、3 个人工区间 |
| [synthetic_fuzdrop_scores_248aa.tsv](synthetic_fuzdrop_scores_248aa.tsv) | 同一请求的合成 residue TSV，支持文件上传验收 |
| [synthetic_fuzdrop_regions_248aa.tsv](synthetic_fuzdrop_regions_248aa.tsv) | 同一请求的合成 region TSV，支持文件上传验收 |
| [synthetic_fuzdrop_global_only_248aa.json](synthetic_fuzdrop_global_only_248aa.json) | 仅保留序列、必需声明与合成 pLLPS 0.68；不提供 residue 或 region 数据 |

JSON 中的 `official_fuzdrop_export` 和 `one_based_inclusive` 是既有请求契约要求的声明字面值；文件名、目录说明和测试页面明确这些输入是合成格式夹具，不能将声明误当成已独立核实的官方来源。它们不包含伪造的服务器结果 ID，也不调用外部 FuzDrop 服务。浏览器验收必须经真实本地导入端点取得结果 ID，再经真实 Analysis API 创建作业；global-only 情况应显示 residue-level data 未提供，绝不从 pLLPS 构造残基分数或区域。
