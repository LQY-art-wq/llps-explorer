# Module 7：Unified Protein Feature Viewer

Module 7 已实现共享蛋白坐标的 Feature Viewer：真实 LRECA attribution、KDE、critical regions 与真实 SEG LCR 可以对齐显示；FuzDrop 只显示当前分析中已通过后端校验的导入数据；DisMeta 保持不可用。

前端完整测试为 **258 passed，0 failed，0 skipped**，lint、typecheck、production build 和 peer dependencies 检查通过。浏览器记录包含 **28/28 检查**，A–E 的真实 API/科学对象核对为 **144/144**。A–E 和三个屏宽在本模块首次 production build 实测；后续仅为避开宿主 rAF 限帧歧义而修订性能测量方法及说明，科学映射和交互实现不变。最终普通 production build 又从 UI 运行真实 LRECA+SEG，确认四条轨道、106/G 统一 tooltip 且没有 synthetic 横幅。证据分别见[质量检查](audit/module7_checks/summary.json)、[浏览器检查](audit/module7_browser/browser_verification.json)和[真实响应核对](audit/module7_browser/api/real_result_verification.json)。

## 1. 绘图技术与依赖

采用原生 Canvas 2D 与 React 受控组件，没有增加绘图库。现有依赖中没有适合这组共享坐标轨道的图表组件；单 Canvas 绘制静态轨道，少量 DOM overlay 绘制 cursor、selection 和 brush，避免长序列形成数万个 React/SVG 节点。

继续使用锁定的 Next.js 16.3.4、React 19.2.8、TypeScript 5.9.3、Node 24.19.0 与 pnpm 11.19.0；前端 package 版本为 0.7.0。ESLint 9.39.5 的既有 EOL 开发工具债务沿用 Module 6，没有关闭 lint 规则或宣称兼容 ESLint 10。

## 2. 组件架构

[results.tsx](../frontend/src/components/results.tsx) 将已提交 job 与配对输入快照交给纯 mapper；[ProteinFeatureViewer](../frontend/src/components/protein-feature-viewer.tsx) 管理全图/精简图、共享视域、显隐、inspector 与选择；[FeaturePlot](../frontend/src/components/feature-plot.tsx) 管理 pointer、keyboard、尺寸和 overlay；[Canvas renderer](../frontend/src/lib/feature-plot-renderer.ts) 只负责绘制、布局与命中检查。

完整 Feature Viewer tab 保持挂载，切换 tab 保留当前分析的 zoom/selection；新 job ID 重置会话。Overview 使用相同组件的 compact 模式，保持全长概览和点击联动，不吞掉页面滚轮执行无效缩放。

## 3. Feature mapper

[buildFeatureViewerModel](../frontend/src/lib/feature-viewer-model.ts) 复用既有 `buildViewerData` / `nativeResults`，消费 normalized AnalysisJob，不读取正在编辑的 draft 或未经校验的 TSV。配对 canonical sequence 优先；缺快照时仅使用合格的成功 LRECA/FuzDrop native 序列作为后备，SEG-only 使用配对快照。

mapper 检查执行状态、方法、长度、逐位 AA、1…N positions、有限数值、语义以及闭区间；FuzDrop/SEG hash 与 job 匹配，FuzDrop 来源与坐标声明符合导入契约。无效可选输出只影响自身轨道，输入保持不变，输出复制隔离。

## 4. 支持的轨道

| 顺序 | 轨道 | Native 数据与语义 |
| --- | --- | --- |
| 1 | LRECA Residue Attribution | `residue_attribution[].score`；`model_attribution` |
| 2 | LRECA KDE Contribution Density | `kde.values`；`derived_hotspot` |
| 3 | LRECA Critical Regions | `critical_regions`；原 `score` / `is_primary` |
| 4 | FuzDrop Residue Propensity | 导入 `residue_propensity[].score`，`score_name=pDP`；`residue_propensity` |
| 5 | FuzDrop Predicted Regions | 导入 DPR / aggregation hotspot；`region_prediction` |
| 6 | Low-complexity Regions — SEG | native regions；`region_annotation` |

Protein coordinate 始终显示。没有数据不生成假曲线或条带，DisMeta 图外状态不计入数据轨道。

## 5. 科学语义与数值保真

Attribution 解释模型，pDP 是导入的残基倾向，两者不能互换；KDE 是 contribution density，不是概率。前端不重新归一化、裁剪 KDE 到 1、求 KDE、找峰或计算 critical regions。SEG 没有 classifier score 或 P/N。

真实 248 aa 样例保留 LRECA global score `0.9999921321868896`、248 个 attribution 与 248 个 KDE 值，KDE 最大值为 `1.5558930042329748`。primary hotspot 为 81–127，length 47，原 cumulative score 为 `36.15997596307393`。native critical regions 最后结束于 247，第 248 位没有被前端补入区域。SEG 保留 72–85、89–119、196–247，覆盖 97/248，count 3，longest 52。

五个保存的作业响应与 Module 6 科学对象逐字段相等：仅排除跨运行变化的 `runtime_ms` / `timings_ms`，D 导入另排除新 `imported_at`。原 GET 响应字节与 SHA 保留于[API 证据](audit/module7_browser/api/real_result_verification.json)。文本舍入仅用于显示，原值和下载对象不被改写。

## 6. FuzDrop 导入处理

只有当前 job 中成功、匹配序列的 validated imported result 可以生成轨道。pDP 不从 global pLLPS 推导，Sbind 不替代 pDP；原 region 顺序、重叠、重复和边界全部保留，不合并或重建。Global-only 导入不产生 residue/region 图。

浏览器 D/E 均在显著标记 **Synthetic test data** 的隔离环境中验收：使用真实 248 aa 序列，但 FuzDrop pLLPS 0.68、pDP、Sbind 和 region 值明确合成。D 提供完整合成导出，E 仅提供 global score；两者经过真实本地导入端点与 Analysis API。后端验证结构和序列，不是认证官方来源，也不是 FuzDrop 科学预测验证；`origin_verification` 保持 `user_declared_not_independently_verified`。素材和 hash 见[夹具说明](audit/module7_browser/fixtures/README.md)。

D 的第 45 位保留 pDP `0.1`，同时属于 30–45、45–60 两个闭区间，length 均为 16。E 的 FuzDrop 显示 `N/A`，同位置 SEG 的 `No` 与 DisMeta 的 `Unavailable` 独立显示。

## 7. DisMeta、缺失和失败状态

DisMeta 始终显示 `IDR — DisMeta · Unavailable`，没有 mock IDR、替代算法或“没有 IDR”的假结论。`No`、`N/A`、`Not imported`、`Unavailable`、`Pending`、`Failed`、`Not selected`、`Invalid output` 保持区别；合法零值仍是数值，成功且空 region list 与缺失 list 不混用。

真实历史 H partial-success 响应经集成测试确认保留 LRECA、不给失败 SEG 生成条带。本轮浏览器还验证了明确合成的 malformed pDP 场景：一个 residue position 故意置为 0，只产生该轨道的 validation issue，其余五条正常；新分析清除旧缩放和选择。[异常隔离截图](audit/module7_browser/malformed_track_isolation.jpg)

## 8. 共享坐标

对外始终是整数 1-based inclusive，region length=`end-start+1`。一份 `ResidueDomain` 控制轴、曲线、区域、cursor、selection 和 brush。内部 half-cell edges 仅用于像素几何，不更改 native 坐标；首尾残基都位于画布内，单残基视域 1–1 也能选择。

远景小区间具有最小 3 CSS px 可点击宽度，绘制与命中共用 bounds；点击仍返回原区间，hover 夹到原端点范围，不把视觉宽度当作新增残基。重复区域保留独立 ID，最多三条紧凑 lanes 用于显示重叠，全部源记录仍可从表格访问。纯函数实现见[坐标模块](../frontend/src/lib/feature-coordinates.ts)。

## 9. Zoom、pan 与视域保持

完整视图支持 wheel/trackpad zoom、横向 pan、缩放按钮、drag pan、brush、start/end 表单、navigator 和 reset。视域限制在 1…N，pan 保持跨度，所有轨道同步；高频域更新按 rAF 合并，pointer capture 与取消事件清理旧手势。

真实浏览器 wheel 后共享域为 73–175，pan 后为 52–154，brush 后为 63–124。屏幕整数像素拖动可能落在相邻 cell 边界，纯坐标测试另外验证精确往返。切换 tab 保留视域与 residue 106，new analysis 恢复全域与空选择。隐藏轨道不隐藏坐标轴，也不修改科学结果。

## 10. 同步 cursor 与 residue 选择

所有可见轨道共用一条 hover guideline，固定选择另有标识。hover 更新 inspector/overlay，memoized Canvas 不重新绘制所有残基；真实点击 106 后 cursor、固定选择与 AA 一致为 106/G，draw count 不增加。

首尾 keyboard 验证得到 1/M 和 248/T；合成 5000 aa 的 1–1、5000–5000 区域也可点击，focus margin 在序列边界截住。选择不改变原数组或 top residue 排序。

## 11. 统一 tooltip / inspector

图下固定 inspector 避免遮挡轨道，并提供文字等价。一个 position 展示 canonical AA、全部 continuous 值、区域 membership，以及每条命中区域的 label/start/end/inclusive length；原始浮点保留，屏幕文本舍入不回流。

第 106 位同时显示真实 LRECA primary hotspot 和 SEG 89–119 membership；D 的第 45 位枚举两个 FuzDrop 区间。未提供、未导入、失败和不可用不被转换成假 0。

## 12. Region 选择与表格联动

点击图区或 region table 后显示 method、type、start、end、length；LRECA 另显示原 cumulative KDE score 和 backend primary 标志。只根据 `is_primary` 强调主区间，不重新选峰。

真实 SEG 89–119 显示 length 31 并 focus 到 69–139；LRECA 81–127 focus 到 61–147；D 的 FuzDrop 30–45 显示 length 16 并 focus 到 10–65。表格/Overview 选择导航到全图，图区内 hover/click 不发起新分析。

## 13. 长序列与实际性能

测试页用明确合成的 100、500、1000、2000、5000 aa，通过同一 mapper/Viewer 渲染六轨道，没有运行长序列科学推理。每种长度均为一个 Canvas、被测 Viewer 子树 225 个 DOM 节点。5 次 hover 前后 static draw count 都为 4，证明这些 hover 没有重画静态轨道。

Performance API 分两类记录：application 从初始组件 mount 或交互 handler 到 React commit；Canvas 为绘制函数的同步实际执行。它们**不代表屏幕呈现、GPU 完成、整页加载或模型推理时间**，也不覆盖此前 rAF 调度排队的全部延迟。每长度 initial n=1、zoom n=3、hover n=5，是少量操作验收记录，不是统计严谨的 benchmark；nearest-rank p95 在如此少的样本下等于最大值。

以下单位均为 ms，表内仅为显示舍入，原精度见[完整观测](audit/module7_browser/browser_verification.json)：

| aa | Mount→commit，n=1 | Zoom median / p95 / max，n=3 | Hover median / p95 / max，n=5 | Canvas first / latest / max |
| --- | --- | --- | --- | --- |
| 100 | 4.90 | 1.60 / 2.20 / 2.20 | 2.30 / 3.00 / 3.00 | 0.90 / 0.70 / 1.30 |
| 500 | 5.80 | 1.90 / 2.00 / 2.00 | 2.60 / 3.40 / 3.40 | 1.50 / 1.20 / 1.50 |
| 1000 | 4.60 | 1.60 / 1.70 / 1.70 | 2.40 / 3.20 / 3.20 | 2.00 / 1.50 / 2.00 |
| 2000 | 4.40 | 1.70 / 3.00 / 3.00 | 2.70 / 4.00 / 4.00 | 4.70 / 2.40 / 4.70 |
| 5000 | 4.20 | 2.00 / 2.20 / 2.20 | 2.40 / 3.10 / 3.10 | 9.70 / 3.70 / 9.70 |

独立保留的冷 5000 aa 观测为 mount→commit **10.30 ms**、首次 Canvas **13.80 ms**，未用后续较快样本替换。5000 aa 的缩放、hover、首尾单残基区域、单 cell 视域及 new-analysis reset 均完成，未出现应用操作无法完成的卡死；这些执行时间不等价于对任意宿主的屏幕帧率保证。[5000 aa 截图](audit/module7_browser/performance_5000.jpg)、[末端区域截图](audit/module7_browser/J_5000_last_region.jpg)

早期 IAB 隐藏宿主的 double-rAF zoom/hover 曾接近 2 秒，原观察仍保存在[后台限帧记录](audit/module7_browser/background_throttling_observation.json)。它反映宿主调度限制，未删除、改写或混入上述 application/Canvas 执行时间。

绘制没有科学抽样、分桶、额外平滑或补齐；null 保持线段缺口，无逐残基 React tooltip 或大规模初始动画。完整 PNG/SVG 导出不属于本模块，当前没有图像导出按钮。后续 PNG 可从同一 Canvas 导出；Canvas 不提供原生矢量 SVG 导出，SVG 需要复用相同 FeatureViewerModel 和坐标模块增加矢量绘制层，无需更改科学模型。

## 14. 响应式结果

以下来自真实 C 场景；三种宽度均使用一个 Canvas，label 的 scrollWidth/Height 与 clientWidth/Height 相等，固定 inspector 不遮图。

| 视口宽度 | Document client / scroll width | Plot width | 结果 |
| --- | --- | --- | --- |
| 1440 | 1425 / 1425 | 829.60 | 无横向溢出，标签完整 |
| 1280 | 1265 / 1265 | 669.60 | 无横向溢出，标签完整 |
| 1024 | 1009 / 1009 | 733.60 | 侧栏折叠，无横向溢出，标签完整 |

截图：[1440](audit/module7_browser/C_combined_1440.jpg)、[1280](audit/module7_browser/C_combined_1280.jpg)、[1024](audit/module7_browser/C_combined_1024.jpg)、[最终构建真实 C](audit/module7_browser/C_final_build_1440.jpg)。本次实际环境为 Windows 与本地 IAB；没有 Linux/Docker 或其他浏览器实测声明。

## 15. Accessibility、语义颜色和测试门禁

区域除颜色外还有标题、legend、primary/candidate 说明、文字 inspector、可聚焦表格按钮与详情。Plot 支持 Left/Right、Home/End、Enter；表单可直接定位 residue/interval，keyboard 首尾、table→plot focus 和键盘 track visibility 已实测。最终构建也验证第 97 位缺失 pDP 显示 N/A、深色 Canvas 跟随 tokens 且保留 residue 106 选择，普通页面 console 无应用 error/warning。这里不声称通过完整屏幕阅读器或 WCAG 认证。颜色复用 design tokens：LRECA 蓝色系、FuzDrop 紫色、SEG 绿色。

普通配置 `/dev/feature-viewer` 实测为 404 且不含 fixture payload；仅服务端 `FEATURE_VIEWER_TEST_MODE=1` 时为 200，并显著显示 Synthetic test data。[HTTP 门禁](audit/module7_browser/route_guards.json)不同于纯函数开关测试。普通工作区不预填合成结果。

`BACKEND_URL` 仍为必须配置的 server-only 目标，浏览器只访问同源 `/api/v1`；生产 client 的本机路径与内部目标扫描见[隐私检查](audit/module7_browser/client_privacy.json)。

## 16. 测试、真实数据证据与范围

完整 **258 项**由原 Module 6 的 123 项和本模块新增 135 项组成：mapper 91、坐标/Canvas 20、view state 3、integration contract 7、harness 14。全部通过且无跳过；重复定向执行没有重复计数。新增测试覆盖值保真、partial success、malformed 可选轨道隔离、坐标往返、paint/hit 一致、重复/重叠/primary、输入不变与输出隔离、5 长度及测试门禁。

| 检查 | 结果 | wall seconds |
| --- | --- | --- |
| Frontend tests | 258 passed / 0 failed / 0 skipped | 1.851 |
| Lint | passed | 11.461 |
| Typecheck | passed | 4.336 |
| Production build | passed | 9.390 |
| Peer dependencies | passed | 0.903 |

命令与日志入口见[执行记录](module7_commands.md)。A=LRECA、B=SEG、C=LRECA+SEG；D/E 的本地 LRECA/SEG 为真实运行，FuzDrop 分别是明确合成的完整/global-only 导入。API 证据保存五个原 GET 响应并通过 144 项核对，没有将测试 FuzDrop 称作官方预测。

后端、模型锁、上游科学实现和旧测试保持冻结，本模块没有更改 weighted ensemble、科学阈值、checkpoint 或导入 parser。**后端 726 项没有因本模块重新运行，历史通过结果不冒称为本轮通过。**

## 17. Module 8 接口与停止边界

共享接口为 `selectedResidue` / `onResidueSelect`、`selectedRegion` / `onRegionSelect`、`onSelectionClear` 和 `ViewerFocusRequest {start,end,requestId}`。单点 focus 使用 `start=end=position`，region focus 使用原闭区间；内部 `focusResidueDomain` / `focusRegionDomain` 及已实现的 table→plot 联动可直接复用。

`ProteinSequenceViewerPlaceholder` 仍只承载接口，没有实现完整逐残基 Sequence Viewer。本模块没有加入 DisMeta replacement、FuzDrop 自动访问绕过、模型训练、概率校准或服务器部署。交付范围到 Module 7 为止，不进入 Module 8。

## 最终状态与范围审计

最终普通工作区与真实后端 health 均为 HTTP 200，普通配置的测试路由仍为 404，临时测试预览已停止。测试 tab 已关闭，viewport override 已还原，页面恢复浅色并保留最终真实 C 分析；见[最终就绪记录](audit/module7_browser/final_readiness.json)。

变更清单按本模块开始时冻结的 373 个一方文件及其逐文件 SHA256/ZIP 比较，未刷新基线。旧后端、原科学文档/验收资料、原前端测试、上游 pinned source 和模型身份文件均核对保留；模型权重不在 Git 中，Git index 与开始时一致。[完整范围审计](audit/module7_scope_review.json)和[变更清单](module7_changed_files.txt)包含最终计数与逐文件摘要。原始机器日志的空白符作为非阻断记录保留，没有改写日志来隐藏结果。

Module 7 completed.
