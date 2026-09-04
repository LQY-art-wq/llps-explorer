# Module 8：Protein Sequence Viewer & Cross-linked Residue Exploration

Module 8 已实现实际氨基酸字母与现有 residue/region 数据的联合查看，并将 Sequence Viewer、Feature Viewer 和结果表格接到共同选择状态。它消费既有 normalized 数据，不改变 LRECA、Grad-CAM、KDE、SEG、FuzDrop 科学值或 ensemble 公式。

**Module 8 验收完成。** 最终完整前端测试为 **300 passed、0 failed、0 skipped**，lint、typecheck、production build 与 peer 检查均退出 0；Module 8 浏览器验收 **71/71**，原 Module 7 浏览器行为逐项重验 **28/28**，当前 API/科学对象检查 **263/263**，覆盖原 144 项断言的等价语义 **144/144**。D/E 已在显著标记 Synthetic test data 的测试 profile 下完成最终验收；最终客户端隐私扫描、范围审计和交付状态检查也均通过。原历史浏览器/断言脚本没有原样重执行；本轮行为观察和等价检查均另存记录。

## 1. Sequence Viewer architecture

[ProteinSequenceViewer](../frontend/src/components/protein-sequence-viewer.tsx) 展示真实 amino-acid letters，使用行组件与轻量 residue spans，不新增 chart、Canvas 或 SVG 绘制层。一个网格事件控制器处理 pointer，一处固定 inspector 展示当前残基证据；每个残基没有独立 tooltip provider、popover、observer 或 React state。

[results.tsx](../frontend/src/components/results.tsx) 先构建 Module 7 的 `FeatureViewerModel`，再构建 `SequenceViewerModel`。完整功能位于 Sequence Viewer tab；Overview 仅提供选中 residue/region 的 compact summary 和打开入口。两个完整 viewer 在当前作业中保留会话状态，新 job ID 重建结果会话。

[viewer-selection.ts](../frontend/src/lib/viewer-selection.ts) 在共同父级维护唯一的 `selectedResidue` / `selectedRegion`。Feature 与 Sequence 的 focus request 分开，保留已有 Feature zoom 与 Sequence scroll 的独立性。局部 hover/keyboard 状态只是临时查看状态，不成为另一份固定选择来源。

没有增加运行依赖或绘图库。前端 package 版本为 0.8.0，继续使用锁定的 Next.js 16.3.4、React 19.2.8、TypeScript 5.9.3、Node 24.19.0 和 pnpm 11.19.0。

## 2. Mapper design

[buildSequenceViewerModel](../frontend/src/lib/sequence-viewer-model.ts) 是纯展示映射，输入为 Module 7 已验证的 `FeatureViewerModel`，不直接读取正在编辑的 draft、未验证的导入文本或旧作业的 FuzDrop 数据。

每个 residue 保留 `position`、canonical AA、LRECA attribution、KDE density、LRECA critical membership、FuzDrop pDP/region membership、SEG membership 和 DisMeta status。区间 membership 和统一 tooltip 在 mapper 中预处理，hover 直接按 `position - 1` 读取，不遍历全部 native regions，也不重新执行科学计算。

mapper 检查 canonical sequence、长度、连续数据长度与有限值、方法与语义、1-based inclusive 区间及 backend primary 标志。无效可选轨道只影响自身输出，不使整个 viewer 崩溃；失败方法的陈旧 track 不被用于着色。输出复制隔离，冻结输入测试确认 mapper 不修改已有数据。

`No` 表示成功提供的区域输出在该位点无 membership；`N/A` 表示该输出或该位点没有值；`Not imported` 表示没有当前合格导入；`Unavailable` 表示集成不可用。`Pending`、`Failed`、`Not run`、`Invalid output` 也分别保留。合法 0 不被转换为缺失；成功的空 region list 与未提供 region list 不混用。

## 3. Residues per row and coordinates

[sequence-viewer-layout.ts](../frontend/src/lib/sequence-viewer-layout.ts) 固定每行 **50 residues**。每行显示 row start，每 10 位显示轻量刻度；等宽字体与固定 50 列 CSS grid 保证字母和坐标对齐。窄屏只改变控件布局或容器滚动，不让自动 word wrap 重新定义 residue 位置。

API、UI、selection 和 region endpoints 始终为整数 **1-based inclusive**：首位为 1，末位为 N，区间长度为 `end - start + 1`。内部字符串切片只在边界转换一次。

| Sequence length | Rows |
| ---: | ---: |
| 100 | 2 |
| 248 | 5 |
| 500 | 10 |
| 1000 | 20 |
| 2000 | 40 |
| 5000 | 100 |

真实 248 aa 样例的首位是 M1，末位是 T248，243 位是 **R243**。需求中的 Y243 是交互示例，不被写入真实序列或当作当前样例的氨基酸。

## 4. Color modes and legends

一次只选择一个 Color By。独立的 selected-residue outline 与 selected-region 上下边界叠加于底色，不依赖某个科学 score 才能看见。

| Color By | 启用条件与显示 |
| --- | --- |
| None | 始终可用；不显示无意义 legend。 |
| LRECA Attribution | 合格的 native attribution 数组；蓝色浅背景，使用原 0–1 值。 |
| LRECA Critical Regions | 存在合格 native regions；primary 较强背景与实线，candidate 较浅背景与虚线。 |
| FuzDrop Propensity | 当前验证导入实际提供 pDP；紫色浅背景，不使用全局 pLLPS 填充。 |
| FuzDrop Regions | 当前验证导入实际提供 regions；紫色区域标记。 |
| Low-complexity Regions — SEG | 当前成功 SEG 提供非空 native LCR regions；绿色标记。 |
| IDR — DisMeta | 始终 disabled，并标记 Unavailable。 |

默认优先使用 LRECA attribution；无该输出时依次选择已有的 FuzDrop propensity、LRECA critical regions、FuzDrop regions、SEG regions，全部缺失则为 None。SEG-only 的实际默认是 SEG。会话 key 包含分析身份和数据适合的默认模式，使异步结果到达及新作业不会沿用不适用的默认着色。

连续值只映射到显示透明度；背景透明度使用对应色系约 6%–34%，文字继续使用主题 text token，不按当前蛋白的最小值/最大值重新归一化。0、0.5、1 的原值不变。Legend 对应 Low/High attribution、Low/High propensity、Primary/Candidate 或 LCR；蓝、紫、绿和选择边界均复用既有 tokens。

## 5. LRECA mapping

LRECA attribution 来自真实 human-specific checkpoint 的 `residue_attribution[].score`；KDE 来自 `kde.values`，作为 contribution density 展示，不称为概率，也不裁剪到 1。critical regions 直接使用 native endpoints、score 和 `is_primary`，前端不找峰或重新选择 primary。

本轮 [A：LRECA-only](audit/module8_browser/api/case_a_lreca_only.json) 与 [B：LRECA+SEG](audit/module8_browser/api/case_b_lreca_seg.json) 的真实样例保留 global score `0.9999921321868896`、248 个 attribution 和 248 个 KDE 值。UI 的 `1.000 P` 是舍入显示，不把原 global score 改为精确 1。

| Position | AA | Attribution | 相关 native evidence |
| ---: | --- | ---: | --- |
| 1 | M | 0.534704502671957 | Candidate hotspot 1–80 |
| 106 | G | 1.0 | Rank 1；Primary hotspot 81–127 |
| 243 | R | 0.6613670140504837 | KDE 0.9147407283559308；Candidate hotspot 234–247 |
| 248 | T | 0.7122310847043991 | 不属于 native critical region；不补入末位 |

五个 critical intervals 为 1–80、81–127、128–188、189–233、234–247。唯一 primary 为 81–127，length 47，原 cumulative KDE score 为 `36.15997596307393`。这些值是本地模型输出，不是实验验证。

## 6. FuzDrop imported handling

只消费当前 job 中成功、匹配序列并经过后端导入校验的 FuzDrop normalized result。没有自动访问官方服务，Sbind 不替代 pDP，global pLLPS 不生成 residue 数组，region 也不从 pDP threshold 推导。来源声明保持 `user_declared_not_independently_verified`；通过本地格式/序列校验不代表官方来源已认证。

D 使用明确合成的 pLLPS **0.68**、248 行 pDP/Sbind 和 3 个区域。第 45 位 I45 的 pDP 为 0.1，仍同时属于 30–45 与 45–60 两个闭区间；这也说明区间来自输入，不是根据该位的 pDP 重新推断。第 243 位 R243 的合成 pDP 为 0.1，FuzDrop region membership 为 No。

E 实际使用合成 global pLLPS **0.42**，没有 residue/region 数据；两个 FuzDrop 着色选项显示 disabled — N/A。保留的旧 0.68 global-only fixture 与本轮 E 的 0.42 payload 是不同文件，不互相替代。

材料、SHA256 和用途见[夹具说明](audit/module8_browser/fixtures/README.md)与[manifest](audit/module8_browser/fixtures/fixture_manifest.json)。初步 D 提交的 scores TSV 去掉了最后一个 LF；最终 D 使用保留完整末尾换行的原 TSV，并通过两份原始 TSV 的 hash 核对。两者科学数值相同，但原始导入 hash 不同，不能宣称提交字节相等。E 的实际 0.42 payload 单独保存。

**D/E 已在显著显示 Synthetic test data 的测试 profile 下完成最终验收。** D 的 job 为 `analysis_-GuUfgG-Fs66lsFqz9r6kt3WJs4StncQ`，E 为 `analysis_oN1wotSFZlnShUNCgK8mJAZg4fFbTAME`；[D 响应快照](audit/module8_browser/api/case_d_fuzdrop_full.json)、[E 响应快照](audit/module8_browser/api/case_e_fuzdrop_global_only.json)与[浏览器场景](audit/module8_browser/browser_verification.json)记录一致。D 显示 6 条 Feature tracks；E 保留 LRECA attribution、KDE、critical regions 和 SEG 共 4 条，不新增 FuzDrop residue/region track。[API 等价检查](audit/module8_browser/api/regression_verification.json)核对 job、合成输入、导入 hash、normalized result 与 mapper。初步普通 profile 下的操作不作为满足测试标记要求的最终验收。所有 FuzDrop 数值始终是 synthetic test data，不是官方预测或生物学证据。

## 7. SEG mapping

SEG 着色使用真实 NCBI segmasker 结果，没有重新判断低复杂度或改变参数。真实样例 native regions 为 **72–85、89–119、196–247**，长度依次为 14、31、52；region count 3，longest 52，coverage 为 `97 / 248 = 0.3911290322580645`。

R243 的 SEG membership 为 Yes，属于 196–247；T248 为 No，不能把区域扩展到蛋白末端。SEG-only 正常显示完整序列并默认 SEG coloring，LRECA 选项显示 disabled — Not run。成功的空 SEG regions 显示 No，失败或缺失输出不转换为 No。证据见 [C：SEG-only](audit/module8_browser/api/case_c_seg_only.json)和 mapper tests。

SEG 仍是 region annotation，没有新增 P/N、classifier score 或 ensemble 权重。

## 8. DisMeta unavailable behavior

DisMeta 保持 `INTEGRATION_BLOCKED`。Color By 的 IDR — DisMeta 始终 disabled，help 与 residue details 明确显示 `DisMeta integration is currently unavailable.` / `Unavailable`。

没有 IDR mock、替代算法或假 region。界面明确说明 Unavailable 不等于该蛋白没有 IDR，避免把缺少集成结果写成阴性科学结论。

## 9. Residue selection and details

点击字母调用共同 `onResidueSelect(position)`，清除互斥的 region selection，并用独立 outline 标记选中残基。普通点击只更新 selection，保留当前 tab。鼠标 hover 与固定 selection 共用一处 residue inspector，展示 Position、AA、LRECA attribution、KDE density、critical membership、FuzDrop pDP/regions、SEG LCR 与 DisMeta 状态。

外部 selection 变化会清除旧 hover，并更新 keyboard position；这避免来自 Feature Viewer 或表格的新选择被先前悬停位置覆盖。显示值可舍入，数值 title、mapper 与下载对象保留原精度。

Find position / residue 支持 `243` 或匹配 canonical sequence 的 `R243`，并定位包含它的行。标签不匹配、0、越界、小数或其他不合格格式给出错误，不猜测替代位置。本模块不引入 motif search、BLAST 或 alignment。

## 10. Region selection and details

Jump to region 只列出当前 mapper 中存在的 native regions。selection 保存 method、type、start、end，并可携带稳定 id；不同方法相同区间仍可区分。选择后定位 region start，整段使用独立上下边界高亮，底层 color mode 仍可见。

Region details 显示 Method、Region Type、Start、End、inclusive Length 和精确序列。完整区域字母默认视觉展开，放在有高度限制的容器中；字母文本 `aria-hidden`，另提供长度与复制方式说明，避免辅助技术被迫逐字读取长区域。

复制前再次确认 selection 对应当前 native region，拒绝陈旧或任意坐标构造的区域。1–1、N–N、1–N 和跨行区间的切片边界均由测试覆盖。

## 11. Feature Viewer cross-link

共享 selection 是双向联动核心，Feature zoom 不强制控制 Sequence 的整页布局。进入 Sequence tab 时，它定位并显示共同 selection；只有 View in Sequence / View in Feature Viewer 等明确操作才切 tab。

当前[联动记录](audit/module8_browser/crosslink_verification.json)包含下列观察：

| 操作 | 观察 |
| --- | --- |
| Feature 点击 243，再 View in Sequence | 源 tab 保持到明确跳转；Sequence 选择 R243，所在行起点 201。 |
| Sequence 点击 G106，再 View in Feature Viewer | 源 tab 保持到明确跳转；Feature 选择 106，visible range 81–131。 |
| Feature native region table 选择 SEG 89–119，再 View in Sequence | Sequence 高亮 31 个残基，保留原闭区间。 |
| Sequence dropdown 选择 SEG 196–247，再 View in Feature Viewer | Feature 选择原区间，visible range 176–248。 |

Feature 使用原有 `focusResidueDomain` / `focusRegionDomain`，没有复制 zoom 算法。区域 focus 的 20-residue margin 和序列边界 clamp 继续由 Module 7 负责。Feature 内的 hover、共享 cursor、pan、zoom、brush 与 track visibility 已纳入[原 28 项浏览器行为重验](audit/module8_browser/module7_regression_verification.json)，按原检查名称逐项记录为 28/28；这是当前生产构建中的实际 UI 行为观察，不是原历史浏览器脚本原样重执行。新增联动观察与这 28 项旧行为记录分别保留。

## 12. Table cross-link

LRECA Top Residues、LRECA Critical Regions、SEG LCR Regions、FuzDrop Regions 均提供 View in Feature 与 View in Sequence。FuzDrop residue table 在存在当前 job 时也提供两个目的地。表格操作写入同一个父级 selection，再为目标 viewer 发出独立 focus request。

| 当前记录中的源数据 | Sequence 与 Feature 对应结果 |
| --- | --- |
| LRECA Rank 1：G106，attribution 1.0 | 共同选择 106；Feature focus 81–131。 |
| LRECA candidate 1–80 | Sequence 高亮 80 位；Feature focus 1–100。 |
| SEG 89–119 | Sequence 高亮 31 位；Feature focus 69–139。 |
| 导入的 FuzDrop 30–45 | Sequence 高亮 16 位；Feature focus 10–65；最终表格补验使用显著标记的 synthetic test profile。 |

切换新分析时，父级以新 job ID 建立空 selection、空 focus targets 和 Overview tab。已有真实 LRECA+SEG → SEG-only 记录显示旧选择清除，Sequence 的默认 color 变为 SEG。相同作业内单纯切 tab 保留该作业的 viewer 状态。

FuzDrop Regions 表格的最终显著标记补验使用 job `analysis_fyX6SCedyUcspcfOWKSixl4WHeW0PFR5`。该 test-profile job 只包含 FuzDrop 导入，`model_inference_methods_run` 为空；页面显示 Synthetic test data 横幅。30–45 从表格跳到 Feature Viewer 后保持原区间并聚焦 10–65，跳到 Sequence Viewer 后高亮 16 位；console warning/error 为 0。该证据见[联动记录 case 6](audit/module8_browser/crosslink_verification.json)，不能解释为本轮执行了 LRECA、SEG 或官方 FuzDrop 推理。

## 13. Keyboard accessibility

Sequence area 只有一个 keyboard stop，支持 Tab 进入、Left/Right 移动 ±1、Up/Down 移动 ±50、Home/End 到当前行边界、Enter 选择、Escape 清除。位置始终 clamp 在 1…N，不产生 0 或 N+1；键盘移动会更新共同 selection 并滚动到对应行。

真实 248 aa 的记录为：Go 243 → Right 244 → Down clamp 248 → Right 仍 248 → Home 201 → End 248 → Up 198；在 1 按 Left 仍为 1。纯函数测试另外覆盖换行与末行边界。

视觉网格与完整区域字母文本使用 `aria-hidden`；有长度说明的可聚焦区域和 `aria-live` 选择摘要提供精简语义。颜色之外还有 AA、Position、membership 文本、primary/candidate 说明、outline/边界与可聚焦控件。

本轮是浏览器键盘交互与 DOM/ARIA 检查，不宣称完整 NVDA、JAWS、VoiceOver 实测或 WCAG 认证。原 28 项行为重验记录中的普通、测试和 harness 页面 console errors/warnings 均为空；最终 FuzDrop 表格补验的 console warning/error 也为 0。交付检查确认测试前端已关闭，普通 production profile 已恢复。

## 14. Copy functionality

提供 Copy Full Sequence、Copy Selected Region 与 Copy Residue Label。完整复制内容为 canonical AA 字母，不含行号、空格、刻度或 FASTA header；residue label 使用 AA 后接 1-based position。

选中区间通过 `sequence.slice(start - 1, end)` 转换闭区间，浏览器复制记录中 SEG 89–119 为 31 aa，实际 clipboard 内容精确为：

```text
PRSGRGTGRGGGGGGGGGAPRGRYGPPSRRS
```

Full sequence 复制长度为 248，Residue label 复制为 G106。缺少选择时相应按钮禁用；clipboard 成功或拒绝均提供状态反馈。单元测试覆盖首位、末位、1–1、N–N、1–N 以及 clipboard writer 的成功/失败分支；边界值不经过视觉坐标反推。

## 15. Long-sequence performance

显著标记 Synthetic test data 的 [Sequence harness](../frontend/src/components/sequence-viewer-fixture.tsx) 使用生产 mapper 和生产 component，测试 100、500、1000、2000、5000 aa。这些是合成 rendering fixtures，不运行长序列 LRECA/SEG 推理，也不是生物学预测验证。

采用按行 memoized rendering、简单 spans、dataset position 和统一事件控制器。hover 不遍历所有 native regions；selection 通常只改变相关行。没有每 residue tooltip/provider，也没有因理论预期而引入 virtualization。当前 5000 aa 操作可完成，未观察到不可用级停顿。

以下来自[性能记录](audit/module8_browser/performance.json)，单位 ms：

| aa | Rows / residue spans | 组件 mount→React commit，n=1 |
| ---: | ---: | ---: |
| 100 | 2 / 100 | 2.7 |
| 500 | 10 / 500 | 5.2 |
| 1000 | 20 / 1000 | 11.7 |
| 2000 | 40 / 2000 | 27.5 |
| 5000 | 100 / 5000 | 42.7 |

独立首次 5000 aa 组件观察为 **68.4 ms**，保留该较慢观察，不用后续较快值覆盖。它不等于浏览器冷缓存整页加载。上述 initial 计时开始于组件 mount，不包含此前 fixture 准备、mapper 构建或网络请求。

| 5000 aa 操作 | 样本数 | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Hover：handler→commit | 2 | 2.2 | 2.9 | 2.9 |
| Residue selection：handler→commit | 2 | 2.55 | 3.1 | 3.1 |
| Color mode：handler→commit | 3 | 21.2 | 35.0 | 35.0 |

Scroll 单独记录为 **35.2608 ms 的 Computer Use 操作往返**，容器 scrollTop 从 0 变为 5040；这与 application handler→commit 使用不同测量边界，不能合并计算同一延迟分布。

这些是少量操作的验收观察，不是统计充分的 benchmark。n=2/3 时 nearest-rank p95 等于最大值；不推断普遍帧率、屏幕绘制/GPU 完成时间、整页响应时间或模型推理速度。当前环境结果支持暂不引入 virtualization，但不保证任意设备上的相同耗时。

## 16. Responsive behavior

三种要求宽度的[响应式记录](audit/module8_browser/responsive.json)保持原位置、50 个固定 residue columns、可读刻度、选中 outline 和固定 inspector。较窄环境使用容器内滚动，不重新排列 residue 编号。

| Viewport | Document scroll width | Sequence grid client / scroll width | 观察 |
| --- | ---: | ---: | --- |
| 1440×900 | 1425 | 1007 / 1006 | 50 位与控件可见，无页面横向溢出。 |
| 1280×900 | 1265 | 846 / 909 | **网格容器内有横向滚动**；页面没有横向溢出。 |
| 1024×900 | 1009 | 910 / 910 | 侧栏折叠，控件换行，仍保持 50 位。 |

工具栏在 1279px 断点改为两列，避免侧栏尚未折叠的窄桌面区间溢出；760px 以下为单列控件。该 CSS 修复不改变数据坐标。不同主题继续使用既有 text/background tokens，浅色强调避免高 score 背景遮住字母。

普通 production profile 已重新运行真实 LRECA+SEG，最终 IAB job 为 `analysis_sxzzqxs-dUcQiz-umFLpbTD1MvYrrFhU`。已在 1440 px 视口实际查看最终截图：选中 R243，显示真实 LRECA/SEG 数值与 membership，FuzDrop 为 Not imported，没有 Synthetic 横幅。[最终响应快照](audit/module8_browser/api/final_display_combined.json)通过当前 GET 200 保存，完整 native LRECA/SEG 对象与本轮 B 对照一致，见[补充核对](audit/module8_browser/api/final_display_verification.json)。此前 Chrome 连接在测试页清理期间断开，已完成的观察保留；最终 IAB viewport 已 reset 并保留 R243 页面。截图用于实际视觉检查，没有把二进制截图复制进公共项目产物。

## 17. Tests, regression and evidence

最终门禁已完整执行前端测试：**300 passed、0 failed、0 skipped**。其中原 Module 7 的 **258 项**保持不变，本模块新增 **42 项**；重复定向运行不重复累计。

| 新增测试文件 | Tests | 主要范围 |
| --- | ---: | --- |
| [sequence-viewer-model.test.ts](../frontend/tests/sequence-viewer-model.test.ts) | 22 | 真实历史响应映射、LRECA/SEG/FuzDrop 各组合、global-only、partial success、缺失值、malformed 隔离、输入不变与 5 长度。 |
| [sequence-viewer-layout.test.ts](../frontend/tests/sequence-viewer-layout.test.ts) | 11 | 固定行、1/N、位置解析、键盘夹边、inclusive slicing 和 clipboard。 |
| [sequence-crosslink-contract.test.ts](../frontend/tests/sequence-crosslink-contract.test.ts) | 9 | 共同 selection、两个独立 focus request、普通点击不切 tab、明确导航、清除与新会话重置。 |

冻结基线中 12 个旧前端测试文件 SHA 均未改变。旧测试继续覆盖 Module 7 mapper、坐标、绘制/hit test、view state 与集成契约；这证明本轮完整 unit suite 包含原 258 项，但不把 unit tests 当作旧浏览器检查或实时 API 验证的替代。

新增 mapper tests 使用冻结的 Module 7 A–E 响应和 Module 6 H partial-success 响应；其中旧 B=SEG-only、旧 C=LRECA+SEG。本轮浏览器场景的 **B=LRECA+SEG、C=SEG-only**，对照时必须交换映射，不能仅凭字母直接比较。

| 质量/验收项 | 最终状态与证据 |
| --- | --- |
| 完整前端 tests | 最终 **300/300**，失败 0、跳过 0，退出码 0；[汇总](audit/module8_checks/summary.json)、[日志](audit/module8_checks/unit.log)。 |
| Lint | 完整项目 `eslint . --max-warnings 0` 退出码 0；[日志](audit/module8_checks/lint.log)。 |
| Typecheck / production build / peer dependencies | 最终三项均退出码 0；[typecheck](audit/module8_checks/typecheck.log)、[production build](audit/module8_checks/build.log)、[peer 检查](audit/module8_checks/peer_dependencies.log)。 |
| Module 8 呈现与浏览器验收 | [browser_verification.json](audit/module8_browser/browser_verification.json)：**71/71**，失败项为空，包含最终 test-profile D/E。A–J、额外 1000 aa 和 7 个联动流程不另外重复加总。 |
| 原 Module 7 浏览器 28 项 | [module7_regression_verification.json](audit/module8_browser/module7_regression_verification.json)：**28/28**，按原 28 个名称映射到当前构建的实际 UI 观察；原历史脚本没有原样重执行。 |
| 当前 API/科学对象检查与原 144 项覆盖 | [regression_verification.json](audit/module8_browser/api/regression_verification.json)：当前检查 **263/263**，失败 0；原 144 项等价语义覆盖 **144/144**，未重验 0，原历史断言代码没有原样重执行。144 是 263 内的覆盖映射，不另加到通过总数。 |
| 3 个补充 UI 回归/最终页面作业快照 | [final_display_verification.json](audit/module8_browser/api/final_display_verification.json)：独立快照检查 **50/50**；3 个 job 中 2 个当前 GET 200、1 个当前 GET 404，后者使用此前保存的同 ID 成功响应。不是 3/3 当前在线可读，也不并入 263 项。 |
| 最终 client 隐私扫描 | [client_privacy.json](audit/module8_browser/client_privacy.json)：最终 production build 的 **14** 个 JavaScript assets、**818,499 bytes**；本地路径、`BACKEND_URL` setting、normal/test/example backend targets 共 **5/5** 检查通过。扫描范围只包括最终客户端 JavaScript。 |
| 范围审计 | [module8_scope_review.json](audit/module8_scope_review.json)：`final_write` **passed**；54 个变更为 47 A + 7 M + 0 D，395 个受保护文件 SHA 不变，checkpoint weights 未被跟踪，git index 前后 SHA 相同，violations 为空。 |
| 交付状态 | [module8_delivery.json](audit/module8_delivery.json)：**7/7**。普通根页面与 API health 为 200；两个 test routes 均为 404；普通 HTML 无 synthetic marker；临时 test frontend 已关闭，backend 保持运行且未为本检查重启。 |
| 变更与执行记录 | [module8_changed_files.txt](module8_changed_files.txt) 与 [module8_commands.md](module8_commands.md) 已生成；范围审计确认新增/修改行空白检查与 git diff 检查通过。 |

历史 [Module 7 浏览器 28/28](audit/module7_browser/browser_verification.json) 和 [API 144/144](audit/module7_browser/api/real_result_verification.json) 作为 SHA 未变的受保护基准保留。当前通过结论来自新的 28 项 UI 行为记录与 263 项 API/科学对象检查，不只是旧文件存在。原 144 项逐项映射到当前断言，涵盖科学对象、模型身份、执行状态、job 与 browser 关联、轨道和测试标记；`historical_assertion_code_reexecuted=false` 明确区分等价回归与历史代码原样复跑。E 的合成 pLLPS 从历史 0.68/P 改为本轮 0.42/N，按当前输入核对阈值、label、未校准映射和 global-only 缺失状态，没有复用历史数值作为新预测。

当前回归脚本离线读取保存的 JSON/TSV/FASTA 与冻结文件，不提交作业、不执行推理、不发 HTTP 请求。A–E 响应捕获步骤另行对 5 个已有浏览器作业执行只读 GET，保留对应 job 与 profile；不能把这两步合称为脚本重新跑了 5 次推理。科学对象比较仅排除 `runtime_ms` / `timings_ms`，使用完整 LRECA/SEG native result 的精确深层 JSON 相等，不设数值容差；JSON 的 1 与 1.0 视为相同数值，布尔和字符串仍严格区分。

补充 50 项核对单独保留三个实际 UI 作业的身份与科学对象。LRECA-only `analysis_jw0X0JFvXAwaIeswtIBee2qTj7wRYXKI` 当前 GET 返回 404；[其快照](audit/module8_browser/api/regression_lreca_only.json)来自此前保存的同一 job 响应，不推测 404 原因，也不称其为当前 GET 200。SEG-only `analysis_JRTO0NEQ2aKg37IzBP22gRrsrIHt5qr5` 与最终 combined job 当前 GET 均为 200。补充记录以 `passed_with_recorded_fresh_GET_404` 明确区分快照科学一致性与当前服务可读性，并确认没有改写主 A–E 快照及 263 项报告。

本轮保存的 A–E 文件是 API 响应对象的 JSON 快照，不称为未经处理的原始 HTTP/GET 传输字节。材料与响应文件 hash 各自针对所保存文件的字节，不能跨不同序列化方式或不同末尾换行宣称原始传输相同。

本模块没有更改后端 schema、模型或后端科学代码，因此不为本模块重新执行完整后端 726 项 suite；其历史结果不计入本轮测试总数。如最终范围审计发现后端 schema 修改，则该判断失效，必须按原要求执行完整 backend suite。

## 18. Unresolved issues, production compatibility and stopping boundary

当前没有已确认的阻断性代码问题或未完成的 Module 8 验收项。实现审查发现的 hover 残留、Color By 状态折叠、窄桌面工具栏溢出和完整区域文本的辅助技术暴露已修复；最终完整 tests、lint、typecheck、production build、peer 检查、客户端隐私扫描、浏览器/API 验收、范围审计和交付状态检查均通过。

最终普通 frontend 使用本轮 production build 与 `FEATURE_VIEWER_TEST_MODE=0` 重启；根页面和 API health 为 200，两个 test routes 为 404，HTML 无 synthetic marker。临时 3001 test frontend 已关闭。backend 保持运行，未因最终交付检查重启；最终 IAB 保留正常 profile 的 R243 页面。

本模块纯前端，使用浏览器标准 API 和相对代码导入，没有新增 Windows 文件路径依赖，也没有向 UI 添加 server/checkpoint 绝对路径或 internal service URL。`BACKEND_URL` 仍由服务器配置，浏览器使用同源 API。普通 `/dev/sequence-viewer` 与 `/dev/feature-viewer` 已记录为 404；仅服务器显式启用测试模式时 fixture routes 才可用并显示 Synthetic test data，见[route guards](audit/module8_browser/route_guards.json)。最终客户端 JavaScript 隐私扫描 5/5 通过。

相对本模块开始的 435-file 冻结基线，最终范围审计记录 54 个变更文件：47 个新增、7 个修改、0 个删除；395 个受保护文件 SHA 不变。Pinned LRECA upstream 与 manifest commit 一致且 tracked worktree clean，没有 checkpoint weights 被跟踪，没有 private runtime artifacts 进入 first-party inventory，git index 未被 finalizer 修改，violations 为空。Checkpoint、Grad-CAM、KDE、SEG 参数、DisMeta state 和 ensemble formula 都不属于本模块变更范围。

补充回归中，LRECA-only job `analysis_jw0X0JFvXAwaIeswtIBee2qTj7wRYXKI` 的当前 GET 返回 404；报告只依据此前保存的同一 job 成功响应核对其科学对象，不推测 404 原因，也不称它当前在线可读。这是已记录的当前可读性观察边界，不影响当前最终 combined job 的 GET 200、Module 8 功能验收或 263 项主回归结论。

FuzDrop 的 MANUAL_IMPORT_ONLY 和 DisMeta 的 INTEGRATION_BLOCKED 是既有能力边界，不以伪造数据掩盖。FuzDrop 浏览器验收只使用显著标记的 synthetic imports，没有调用官方远程预测；DisMeta 继续明确显示 Unavailable，不解释为 No IDR。本轮浏览器与性能观察来自 Windows 本地环境；没有 Linux/Docker 实机运行、服务器购买、域名、Nginx 或 Kubernetes 部署，不对未测试平台作完成声明。

**Module 8 completed.** 工作范围止于 Module 8，不进入后续 Module。
