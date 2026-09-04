# Module 6 报告：Analysis Workspace 前端

**Module 6 completed.** 真实浏览器 A–H、最终屏宽/键盘复查、质量 gate、隐私与范围核对全部通过。

本轮继承现有 Next.js、React、TypeScript、Tailwind 项目，将 Module 0 占位页更新为连接
Module 5 后端的分析工作区。前端版本为 `0.6.0`；前端单元测试 **123 项通过、0 skipped**，
全站 lint、TypeScript、production build 与 peer dependency 检查均通过，另有 **3 项**
独立故障测试入口的 pytest 和对应 Ruff 通过。记录见 [质量检查](audit/module6_checks/summary.json)。
实际浏览器提交和读取真实后端任务，A–H 已完成；最后的焦点/卡片改动后，同一质量 gate
已再次全部通过，没有将重复执行累计为新增测试。

命令见 [module6_commands.md](module6_commands.md)。历史 Module 0–5 文档、既有 `backend/`
与上游科学源保持不变；本轮不训练模型、不更换 predictor、不修改科学评分或区域算法。
相对 **287 个文件**的起点快照，共 **97 个变更：86 新增、11 修改、0 删除**，
其中计数包括封版生成的范围报告和变更清单。**274 个受保护历史文件逐字节不变**，
权重未被 Git 跟踪，上游保持固定 commit 且 tracked worktree clean，Git index 未改动，
`git diff --check` 通过。见 [范围核对](audit/module6_scope_review.json) 与
[变更清单](module6_changed_files.txt)。

## 1. 页面结构与输入

页面采用深蓝顶栏、约 320 px 分析侧栏和自适应结果区。顶栏提供 Analysis、Examples、
Documentation、About、会话 History 与主题切换；帮助内容通过轻量弹窗展示。
输入区支持单条 raw sequence 和 FASTA、可选名称、示例填入及清空；实时显示长度、
标准残基数、输入类型和验证状态。FASTA header 可作为默认名称，不推断物种、基因或 UniProt。

规范化规则移除空白并转为大写；只接受 `ACDEFGHIKLMNPQRSTVWY`，报告不支持的残基和位置，
不静默替换。前端校验用于及时反馈，后端校验仍为最终依据。已提交任务使用独立输入快照，
编辑中的新序列不会替换历史任务对应的序列、结果或解释数据。

## 2. Method integration UI

方法目录来自真实 `/api/v1/methods`，按实际能力分组，保留方法各自的科学含义。

| 方法 | 当前操作入口 | 展示语义 |
| --- | --- | --- |
| LRECA | Automatic analysis，可选 | Human-specific global score、P/N、模型归因及 KDE 区域 |
| SEG / LCR | Automatic analysis，可选 | Low-complexity region annotation，不含 LLPS score 或 P/N |
| FuzDrop | External result，先导入再明确启用 | 用户声明的官方结果，自动调用不可用 |
| DisMeta / IDR | Unavailable，禁止选择运行 | Integration blocked，无自动预测、导入或替代算法 |

FuzDrop 目录中的可用性表示手工导入路径可用，不表示官方远程自动接口已开通。
目录加载失败或后端报告不可用时，页面显示原因，不以预设成功能力替代真实状态。

## 3. FuzDrop import UX

原生 `<dialog>` 绑定当前 canonical sequence。支持可选 pLLPS、scores TSV 与 regions TSV
粘贴或 UTF-8 文件上传；至少提供一项。空 pLLPS 不转为 0，数值必须有限且在 `[0,1]`；
前端不自行解析或重建原生区域。上传使用 fatal UTF-8 解码，拒绝损坏编码、UTF-16 和二进制内容。
本地文本限制为 5 MiB；同源代理另限制完整 JSON 请求体，后端保留自己的配置上限与完整校验。

提交前必须分别确认官方来源声明与 1-based inclusive 坐标声明。请求严格使用既有
`source_declaration=official_fuzdrop_export`、`coordinate_system=one_based_inclusive`
及 Module 2 字段，不发明 CSV、JSON 原生导出格式。后端检查残基数、逐位序列、数值及区域坐标。
导入状态和来源始终说明：**用户声明，未独立验证官方网站来源**。

成功后显示实际 `result_id`、序列匹配状态及实际提供的 pLLPS；无 pLLPS 时显示未提供。
用户按 Done 关闭后，仍须主动打开 “Use FuzDrop in this analysis”。导入不会自动勾选方法、
切换 weighted 模式或计算 ensemble。改输入、移除、替换、到期和旧请求响应均经过生命周期检查；
关闭弹窗会中止进行中的请求。提交时捕获接收回调，父工作区再次核对 revision、SHA256、
长度、canonical sequence 和有效期，防止旧序列导入覆盖新输入。

“Open Official FuzDrop” 只使用精确官方 HTTPS 白名单，新标签采用 `noopener noreferrer`，
不携带序列或查询参数。Copy Sequence 只执行用户主动复制；应用不向官方网站自动提交序列，
不处理 CAPTCHA 或浏览器保护。

浏览器实际确认导入成功、Done 焦点、关闭后未启用以及 weighted 仍禁用，见
[成功弹窗](audit/module6_browser/E_import_success.dom.txt) 和
[未自动启用](audit/module6_browser/E_import_not_enabled.dom.txt)。故意错配首位残基时展示
`FUZDROP_SEQUENCE_MISMATCH` 的安全错误；更换输入后显示 Sequence mismatch 并使引用失效，
见 [错误反馈](audit/module6_browser/E_mismatch_error.dom.txt) 和
[输入变更](audit/module6_browser/import_invalidation.dom.txt)。

## 4. DisMeta blocked UX

侧栏与 Annotation Summary 明确显示 DisMeta integration unavailable，采用中性不可用状态。
没有可勾选运行入口、导入入口、IDR 表格或模拟 IDR。未选择的 DisMeta 不会加入请求，
也不使正常 LRECA/SEG 分析变成失败。

## 5. Independent、weighted 与科学语义

Independent 保留每个方法的原始 score、label、threshold 与来源。Weighted 仅在 LRECA
可用且已选择、FuzDrop 导入有效并已明确启用、且导入提供 global score 时可用。
缺少任一前提会给出具体禁用原因。权重控件只包含 LRECA 和 FuzDrop，滑块与百分比输入联动，
提供 Equal weights，显示总和；不向 SEG 或 DisMeta 分配权重。

前端只组装 Module 5 请求，将权重交由后端验证和计算；页面不重新计算 ensemble。
Combined Score 取真实后端响应，明确标记 `Experimental weighted score` 与
`not_calibrated`，不称为经过跨方法校准的 LLPS probability。缺失或不可用的分数显示原因，
不填 0，也不把剩余方法静默改为 100%。

Grad-CAM 为 `model_attribution`，KDE 为 `derived_hotspot`，FuzDrop pDP 为
`residue_propensity`，其区域为 `region_prediction`，SEG 为 `region_annotation`。
这些数据在各自卡片和表格展示，不合并为同一含义的轨道，不重算坐标、排序或区域边界。
界面沿用后端规范化的 1-based inclusive 坐标。

## 6. 任务提交与 polling

Run Analysis 提交真实 `POST /api/v1/analysis`，收到 job ID 后读取
`GET /api/v1/analysis/{job_id}`。默认约 1 秒轮询，终态自动停止；卸载、切换任务或发起新任务
会中止旧轮询。重复提交有保护，响应按任务 epoch、序列 hash 与长度检查，避免较晚返回的旧任务
覆盖当前显示。轮询错误保留已取得结果，并提供恢复读取入口，不重复创建同一任务。

方法状态区分 queued、running、success、failed、unavailable、external_result_required、
skipped。History 只保存在当前标签页内存，刷新或离开后清除，不写入浏览器持久存储。
浏览器实际从 History 选择已完成的 B 任务，保留原 job ID 和原 SEG 科学结果；结果 tabs 的
ArrowRight、End、Home 键操作也已验证。

## 7. Partial success 与错误 UX

`partial_success` 保留正常结果区并提示 “Analysis completed with warnings”。
例如 LRECA 成功而 SEG 失败时，LRECA 分数、归因和 KDE 仍可查看，SEG 卡片显示失败原因。
Failed 与 External result required 使用不同文案；前端只显示稳定安全错误码及友好信息，
不渲染异常堆栈或原始内部错误。

H 场景使用独立且显式开启的 `scripts/module6_test_backend.py --fail-seg`：保留真实 LRECA、
真实 SEG 加载/health 及原调度器，只让 SEG analyze 抛出特定测试异常。此入口不属于生产启动，
不构造 LRECA 成功响应，不添加生产失败开关。实际浏览器 H 通过专用前端 `3001` 连接专用
后端 `8001`，任务 `analysis_HEsw-VBCJjw4ssQ-6uxvvdk_22vR5_mW` 为 `partial_success`：
真实 LRECA 分数 `0.9999921321868896`、P、248 项 attribution/KDE 保留；SEG 为 failed，
安全错误码 `METHOD_EXECUTION_FAILED`，区域及统计未伪造。见
[H 页面](audit/module6_browser/H_partial_success.dom.txt)、
[截图](audit/module6_browser/H_partial_success.jpg) 和 [原始任务 JSON](audit/module6_browser/api/H_job.json)。

## 8. API 接入、结果摘要与下载

浏览器请求同源 `/api/v1`。Next 服务端代理只转发允许的路径与 JSON，读取必填、无默认值的
服务端 `BACKEND_URL`；不使用 `NEXT_PUBLIC_BACKEND_URL`，不把内部地址传入浏览器。
未知路由、错误 origin、过大请求体、非 JSON 响应或网络错误均返回安全结构化错误。
公开结果仅使用后端安全字段，不展示文件系统路径、checkpoint 绝对路径、密钥或内部服务 URL。

Overview 包含 Protein Information、Prediction Summary、方法状态和 Annotation Summary。
LRECA、FuzDrop、Annotations、Tables 分页展示真实字段；LRECA Top Residues、Critical Regions、
SEG LCR 与 FuzDrop regions 保留独立表格，长表分页而不改变原始数据。
Download 在浏览器下载当前 normalized analysis JSON 或 FuzDrop JSON，不提前实现复杂 PDF。
新导入的预览不会替换旧任务中的 FuzDrop 结果。

实际 F 场景点击 Download analysis JSON 后，在浏览器 Downloads 中找到生成文件；CUA 的
download-event 接口未返回事件，因此以真实下载文件本身核验。公开副本
[F_download.json](audit/module6_browser/api/F_download.json) 保留原始 **127055 字节**，
SHA256 为 `c088a62c232bb6a05f3a67e5e781f495aad8d8ee96378466126f6429f678ff5d`，
完整 JSON 对象与同源 GET 得到的 F 任务严格相等，未仅比较几个分数字段。

[最终 client 隐私扫描](audit/module6_browser/client_privacy.json) 检查 **10 个 production
JavaScript 文件，共 641654 字节**，未发现实际开发者路径、`BACKEND_URL` 配置变量、
正常/故障测试后端 target 或示例容器 target。该结论针对最终生产 client bundle；服务端
运行配置仍保留在服务端，不需要写入浏览器环境。

## 9. 响应式布局

Desktop 使用固定宽侧栏与 fluid 主区；较窄宽度调整卡片与表格布局，约 1100 px 以下侧栏转为
可打开/关闭的分析抽屉。表格和 tabs 支持横向滚动，弹窗限制视口内高度并可滚动，窄屏 TSV
双列调整为单列。方法颜色固定为 LRECA 蓝、FuzDrop 紫、SEG 绿；DisMeta 不可用保持中性灰。

最终构建已实际检查三个窗口宽度。窗口包含垂直滚动条，因此 document clientWidth 比窗口宽度
少 15 px；每种情况下 document 和 main 的 scrollWidth 均等于各自 clientWidth，没有横向溢出。

| 窗口宽度 | Document clientWidth | Main 宽度 | Sidebar | 实际截图 |
| --- | --- | --- | --- | --- |
| 1440 px | 1425 px | 1105 px | 320 px | [1440](audit/module6_browser/1440_final.jpg) |
| 1280 px | 1265 px | 945 px | 320 px | [1280](audit/module6_browser/1280_final.jpg) |
| 1024 px | 1009 px | 1009 px | 折叠 | [1024](audit/module6_browser/1024_final.jpg) |

1024 px 的 [打开抽屉](audit/module6_browser/1024_drawer.jpg) 和
[暗色主题](audit/module6_browser/1024_dark.jpg) 也已实测，操作区与结果区保持可访问。

## 10. Accessibility

输入有明确 label，验证和任务信息使用适当的 live region；按钮和方法控件提供可访问名称，
不可用选择有说明。结果 tabs 实现 tablist/tabpanel 语义和键盘移动；抽屉管理焦点与 Escape。
FuzDrop 使用原生 modal dialog，并显式循环 Tab 首末控件，打开时设置初始焦点、成功后聚焦 Done、
关闭时恢复原触发位置。React 19 检查发现的 render 读 ref、effect 内同步重置表单问题已修复：
每次打开挂载独立导入会话，关闭卸载并取消请求。

代码已包含可见 focus 样式与 reduced-motion 支持。浏览器首次发现首个 Close 按 Shift+Tab
会使 activeElement 到 BODY，现已新增共享 `trapDialogFocus`，过滤隐藏、disabled、inert 和
负 tabIndex 控件，显式实现首尾循环；保留 Escape、取消请求和关闭恢复逻辑。
两个 TSV 文件控件补充唯一可访问名称，浏览器已确认分别为 Residue scores TSV file 与 Regions TSV file。
最终构建的实际键盘复查全部通过：

- 1024 px 抽屉初始焦点为 sequence-name，main/header 为 inert；Shift+Tab 从关闭按钮到 Run，
  Escape 关闭后返回 Analysis setup 触发按钮。
- Import modal 的 Close 与 Cancel 双向 Tab 循环通过，Escape 返回导入触发按钮；
  成功导入后的 Done 焦点及关闭后未自动启用在 E 场景另有记录。
- Documentation modal 的 Close/Done 首尾导航与 Escape 返回 Documentation 触发按钮通过。
- 结果 tabs 的 ArrowRight、End、Home 与 History 返回原任务均通过。

这些是本轮实际交互检查，不等同于完整无障碍认证。

## 11. 测试与真实浏览器验收

| 检查 | 当前记录 |
| --- | --- |
| 前端 unit tests | [123 passed、0 skipped](audit/module6_checks/unit.log)，覆盖输入、API/轮询、导入生命周期、表单、viewer 映射及代理配置 |
| 其中 FuzDrop form tests | 13 passed，已包含于上述总数，不重复累加 |
| TypeScript | [通过](audit/module6_checks/typecheck.log)，5.457 s |
| 全站 lint | [通过，0 warnings](audit/module6_checks/lint.log)，20.248 s，没有关闭规则 |
| Production build | [通过](audit/module6_checks/build.log)，17.186 s |
| Peer dependencies | [通过，无 peer 问题](audit/module6_checks/peer_dependencies.log)，0.904 s |
| 独立测试后端入口 | [3 pytest passed](audit/module6_checks/test_fixture.log)，命令 2.540 s；[Ruff 通过](audit/module6_checks/python_lint.log) |
| 历史保护 | [274 个受保护文件逐字节不变](audit/module6_scope_review.json)，既有后端、科学源及历史审计未改 |

[浏览器汇总](audit/module6_browser/summary.json) 记录八项场景、全部屏宽、键盘与附加流程检查，
浏览器控制台 warning/error 均为空。测试后已恢复 viewport，关闭 partial-fixture 标签，
正常预览标签保留。

真实浏览器使用运行中的 Next 前端与真实后端，逐项通过并保留证据：

| 场景 | 输入与判定 | 当前结果 |
| --- | --- | --- |
| A | LRECA only，真实 human-specific 推断 | [通过](audit/module6_browser/A_lreca_final.dom.txt)，CUDA score `0.9999921321868896`、P、248 attribution/KDE |
| B | SEG only，真实 LCR，无 P/N | [通过](audit/module6_browser/B_seg_regions.dom.txt)，3 区域、coverage `97/248`、最长 52 aa |
| C | LRECA + SEG，各自独立结果 | [通过](audit/module6_browser/C_pair_final.dom.txt)，两方法 success，无 ensemble |
| D | FuzDrop 未导入，禁止启用和 weighted | [通过](audit/module6_browser/D_G_no_import.dom.txt)，显示 Import required 与 weighted 禁用原因 |
| E | 导入明确标记的 synthetic-format FuzDrop fixture，成功后仍未启用 | [通过](audit/module6_browser/E_import_not_enabled.dom.txt)，pLLPS `0.68`、未开启使用开关 |
| F | 明确启用导入后 LRECA + FuzDrop weighted，显示真实后端 ensemble | [通过](audit/module6_browser/F_weighted_final.dom.txt)，后端 score `0.8719952793121338` |
| G | DisMeta unavailable，不允许运行或导入 | [通过](audit/module6_browser/D_G_no_import.dom.txt)，Analysis unavailable disabled |
| H | 独立测试后端的 SEG 故障注入，真实 LRECA 保留，显示 partial success | [通过](audit/module6_browser/H_partial_success.dom.txt)，LRECA success + SEG failed |

对浏览器创建的 A/B/C/F/H 任务随后进行同源 GET，只读取既有任务，不重新提交分析；
[API 与下载核对](audit/module6_browser/api/verification.json) 当前 **110 项检查通过**，
核对模型身份、完整序列、baseline 分数、248 位解释、SEG 坐标、方法语义、导入文本 SHA256
以及下载对象。SEG 原生规范化区域为 **72–85、89–119、196–247**。F 场景使用后端返回的
`0.6 × 0.9999921321868896 + 0.4 × 0.68 = 0.8719952793121338`，P，threshold `0.5`，
保留 `not_calibrated` 和 `experimental_weighted_score`；此公式只作验收复核，未在前端替代后端计算。
最终构建再次运行 C 场景，完整 LRECA/SEG 科学对象与此前 C 严格相等，只有 job、时间和耗时字段
随新任务变化；248 项 attribution/KDE 与原生 SEG summary 复核通过。

浏览器素材见 [fixture 说明](audit/module6_browser/fixtures/README.md) 与
[manifest](audit/module6_browser/fixtures/fixture_manifest.json)。248-aa 序列复用已有真实
LRECA baseline；FuzDrop pLLPS `0.68`、pDP、Sbind 和区域都是**合成格式测试数据**，
不声称为官方预测或生物学验证。填写来源声明仅用于本次明确测试契约，不能赋予合成数据真实来源。

## 12. Production readiness 与依赖边界

前端已采用环境配置和同源服务端代理；`pnpm start` 为 `next start`，无固定 localhost 绑定。
未来 Linux/Docker 可在运行环境提供 `BACKEND_URL` 和监听参数；当前未进行 Docker 或公开生产部署。
既有后端的内存 job/import store 与单 worker 限制不因前端更新而改变，重启后的引用仍会失效。

[进程清理](audit/module6_browser/cleanup.json) 确认 H 的专用前端、测试后端及其科学 worker
全部停止；正常 `3000 → 8000` 本地预览继续保留。没有遗留故障注入服务供正常工作区使用。

开发工具兼容记录：尝试 ESLint `10.9.1` 时，现有 React lint 插件触发
`react/display-name` 的 `context.getFilename` 错误，React/import/jsx-a11y 插件的 peer
支持仍止于 9。最终锁定 **ESLint `9.39.5` + eslint-config-next `16.3.4`**；
没有关闭 lint 规则来掩盖问题。ESLint 9 已属 EOL 开发工具，列为待插件支持新主版本后处理的
依赖债务，当前不能宣称完整支持 ESLint 10。

`unrs-resolver` 的 postinstall 由 `allowBuilds: false` 明确禁用，当前通过普通 optional
预编译 native binding 工作；这是依赖安装策略，不是 Windows 专用 workaround，也不表示所有
未来平台已验证。`package.json` 使用 `type=module`；依赖及 lockfile 保留精确版本。
跨平台 native optional 包、生产代理/HTTPS、长期运行和部署环境仍需在目标环境验证。

## 13. Module 7/8 留接口与停止边界

Feature Viewer 与 Sequence Viewer 目前是明确占位组件。`viewer-data.ts` 已将实际任务的
sequence、LRECA attribution/KDE/critical regions、FuzDrop residue propensity/regions、
SEG regions 分别组织为 props；缺失为 null，真实空区域列表与未提供分开，保留来源和语义类型。
为后续联动保留 residue/region selection 与 focus request，不构造完整多轨图或复杂序列着色。

本轮停止于 Analysis Workspace、基础表格、JSON 下载和上述占位接口。
不进入 Module 7，不实现 DisMeta 替代、FuzDrop 自动化、新模型训练或生产部署。
Module 6 completed. 已完成 A–H、最终 C 科学对象复核、完整下载、屏宽、键盘、隐私与范围检查，
测试专用服务已停止。工作停在 Module 6，不进入 Module 7。
