# Module 5 Report — Analysis Orchestrator, Capability Routing & Weighted Ensemble

## 结论

**Module 5 已完成。** 后端版本 **0.5.0**，完成能力目录、异步分析任务、方法级状态轮询、
FuzDrop 导入引用与 TTL、失败隔离及实验性加权评分。完整后端 **726 passed，0 skipped**；
真实 Uvicorn HTTP 验收通过。前端仍为 Module 0 占位页，未进入 Module 6。

实现说明见 [Orchestrator](orchestrator.md)，实际操作见 [命令记录](module5_commands.md)，
本轮范围见 [变更清单](module5_changed_files.txt) 与 [SHA256 范围复核](audit/module5_scope_review.json)。
相对 Module 4 快照共 **77** 个变更文件（61 新增、16 修改、0 删除，其中 37 个为 HTTP 验收证据）；
其余 **210** 个既有文件 SHA256 完全一致。

## 1. 自动运行的方法

**LRECA、SEG** 根据 `MethodRegistry` 的 `automatic_analysis_available` 与 integration_mode
运行，跨方法并发。LRECA 仍为固定 human-specific checkpoint，原生 global prediction、P/N、
Grad-CAM、KDE 和 critical regions 保留；启动时加载一次并驻留 scientific worker。
SEG 仍调用标准 NCBI BLAST+ 2.17.0+ 的 segmasker，只返回 LCR region_annotation。
不是把所有 selected_methods 都直接调用 analyze。

## 2. 需要导入的方法

**FuzDrop 仅支持手工导入**，自动调用仍不可用。目录中
`integration_mode=manual_import`、`automatic_analysis_available=false`、
`manual_import_available=true`、`available=true`。available 现在表示自动或手工至少一条路径可用。
`FUZDROP_MANUAL_IMPORT_ENABLED=false` 时手工路径和 available 均为 false。
原生 FuzDrop health/analyze 仍保留 Module 2 的 browser_protected / 503 契约。

## 3. 阻断的方法

**DisMeta 继续 INTEGRATION_BLOCKED**。目录为 integration_blocked，自动与导入均 false。
调度器不调用其 analyze，不新增 native parser，不使用其他 IDR predictor 替代。
独立 health/analyze 保留 Module 4 的 unknown / MODE F / 503；未选择时不产生 DisMeta warning。

## 4. Partial success 规则

全部所选方法成功为 success；至少一个成功而其他方法未成功为 partial_success。
没有成功时，存在执行失败为 failed；否则需要导入为 external_result_required；其余为 unavailable。
因此 LRECA success + FuzDrop external_result_required + SEG success + DisMeta unavailable
返回 partial_success。DisMeta only 正常返回 unavailable，FuzDrop only 缺引用返回
external_result_required，SEG only 正常分析且无 P/N 或 ensemble。

## 5. FuzDrop external result routing 与生命周期

既有 import endpoint 继续使用原严格 parser，成功响应保留原始字段并增加
`result_id / expires_at / validation_status=valid`。`ImportedMethodResult` 保存已验证结果、
序列 SHA256/长度、source、imported_at、坐标来源与验证状态。
analysis 接纳前核对实际规范化序列 hash 与长度；不匹配为 422
EXTERNAL_RESULT_SEQUENCE_MISMATCH，丢失/过期引用为 404 EXTERNAL_RESULT_NOT_FOUND。

同一有效引用可重复使用；已接纳的任务固定深拷贝，不受随后导入到期影响。
默认导入保留 3600 秒、最多 128 项，读不续期；满容量拒绝新导入，不驱逐未过期项。
后台最长 60 秒一次清理闲置过期数据。内存数据重启即失，当前只支持单个 Uvicorn worker。
导入验证仍是用户声明与格式校验，不提供官方网站来源认证。

## 6. Weighted ensemble 的前提

必须同时选择 LRECA 与 FuzDrop；两个方法均 success 且都有有效 numeric global score。
weights 恰含 lreca/fuzdrop，范围 [0,1]、有限数值、和为 1（绝对容差 1e-9）。
SEG/DisMeta 权重、缺选 predictor、无效权重均明确 422，不静默改变模式。

唯一 `EnsembleCalculator` 实现 `w_lreca * raw_lreca + w_fuzdrop * raw_fuzdrop`。
数学测试精确验证 **0.6 × 0.82 + 0.4 × 0.68 = 0.764**。
不重新归一化，零权重仍需双方法成功。缺 FuzDrop 引用为
`fuzdrop_external_result_required`；LRECA 失败为 `lreca_result_unavailable`。
FuzDrop 成功导入但未提供 pLLPS 时 ensemble 为 `fuzdrop_global_score_missing`。
这些情况 score/label 均为 null，不把另一方法改成 100%。

## 7. Calibration 与科学语义

当前保留 `calibrated_score=raw_score`、`calibration_status=not_calibrated`；
ensemble 使用 `score` 字段和 `interpretation_status=experimental_weighted_score`。
没有概率校准、训练、模型替换或校准数据集。本模块不宣称 calibrated LLPS probability。

LRECA global 为 model_prediction，残基为 model_attribution，KDE 为 derived_hotspot；
FuzDrop global 为 model_prediction，残基为 residue_propensity；SEG/DisMeta 为 region_annotation。
这些归因、残基倾向和区域不跨方法数学融合；原生分数、P/N、参数、区域、坐标来源均保留。
所有残基和区域坐标继续为 **1-based inclusive**。

## 8. Ensemble threshold

后端配置 **ENSEMBLE_THRESHOLD=0.5**，操作符 **>=**，后端产生 P/N。
这是实验性评分的默认决策阈值，不是经过生物学验证的概率阈值。
LRECA 原生严格 `>0.5` 与 FuzDrop 原生 `>=0.60` 不变，独立方法标签不被 ensemble 覆盖。

## 9. Failure isolation、超时与日志

方法异常在调度边界转为安全 StructuredError；单个失败不取消其他有效方法。
测试覆盖 LRECA/SEG 双向失败、坏 DTO、错误序列、错误 LRECA 标签及 adapter 自取消。
默认每方法 150 秒、运行阶段总时限 180 秒，排队另有 180 秒上限；原 adapter 时限仍生效。
超时及时发布 METHOD_TIMEOUT，仍持有后台清理任务；同方法未清理完时报告
METHOD_BUSY_AFTER_TIMEOUT，迟到结果不会覆盖任务终态。

日志保留 job_id、method、status、runtime、sequence length/hash；异常文本、输入和 traceback
不进入调度错误响应。真实 server log 已验证无完整测试序列，并实际捕获方法生命周期日志。
生产时限要求 adapter 不阻塞事件循环；不受控同步计算应使用独立进程/服务监督。

## 10. API schema 与兼容性

- `POST /api/v1/analysis`：校验 sequence、selected_methods、prediction_mode、weights、
  external_results；成功接纳 **202**，返回 queued Job。
- `GET /api/v1/analysis/{job_id}`：**200** 当前快照；缺失/过期 **404**。
- `GET /api/v1/methods`：完整 capability registry，新增 automatic_analysis_available、
  method_supported、integration_status，清晰区分 import 与 blocked。
- `POST /api/v1/methods/fuzdrop/import`：兼容旧原生结果，添加可复用 ID 和期限。

Job 包含 ID、UTC 时刻、到期、状态、序列元数据、所选方法、模式/权重、methods、ensemble、warnings。
统一 MethodExecution 外壳内嵌原方法 schema，非成功结果为 null，SEG 不被塞入全局分数字段。
目录 mode 是调度层的新枚举；独立 method health 的历史 mode 并未重命名。
详细请求与错误例子见 [接口说明](orchestrator.md)。

## 11. Job status 与存储

方法状态 queued/running/success/failed/unavailable/external_result_required/skipped。
Job 支持 queued/running/success/partial_success/failed/unavailable/external_result_required。
方法可独立完成和被轮询，不依赖单次 HTTP 请求持续连接。
默认最多 128 个 job、4 个并行执行；终态结果从完成起保留 3600 秒并定期清理。
活动任务不在执行中途因 TTL 消失，关闭时清理自有任务和 store。

## 12. Future queue readiness

API 只负责提交与读取；`AnalysisJobService` 负责入队边界、容量、生命周期，
`AnalysisOrchestrator.run_analysis()` 负责相同的能力路由和结果合并。
`AnalysisJobStore` / `ImportedResultStore` 分离数据存储，未来可替换为 DB/Redis；
queue worker 可重用相同核心执行逻辑。当前没有强制引入 Celery/Kafka/Kubernetes。

## 13. Production Deployment Readiness

- Linux portability：本模块无硬编码 Windows 用户路径、Windows shell 或浏览器依赖；
  核心服务不依赖 HTTP Request；目标 Linux 运行尚未实测。
- Docker readiness：环境配置、存储边界、依赖锁与既有 adapter 边界可复用；未构建镜像或部署。
- Checkpoint：继续从 LRECA_CHECKPOINT_PATH 配置，只保留文件名、SHA256、manifest 与安装说明；
  大型权重和 external checkout 未被 Git 跟踪。
- 模型：保持启动加载一次、驻留 RAM/VRAM，后续任务复用；本轮没有修改核心模型代码。
- CPU/GPU：既有回归继续通过；本轮真实 HTTP 使用本机 CUDA，未更改 auto/cpu/cuda 配置。
  历史 CPU/GPU benchmark 保留在 [LRECA runtime](lreca_runtime.md)，本轮 HTTP 时延不冒充新 benchmark。
- 环境：API Python 3.12.13；worker Python 3.10.19、PyTorch 2.1.1+cu118、NumPy 1.23.0、
  SciPy 1.10.1；无新增依赖，锁文件不变，无新增 Windows workaround。
- 将来拆独立 LRECA/SEG service：**核心 inference 不需要重写，只需要容器化和改变部署边界**；
  适配通信、共享存储、任务认领/恢复与进程监督属于后续部署工作。

## 14. 测试与真实 HTTP 证据

完整 pytest **726 passed / 0 failed / 0 skipped，49.88 秒**，2 条既有依赖弃用 warning。
**471** 项原有测试全部保留通过；新增 **255** 项：

| 新增测试组 | 数量 |
| --- | ---: |
| analysis request | 66 |
| imported results | 65 |
| analysis API | 46 |
| ensemble | 34 |
| orchestrator | 24 |
| method registry | 12 |
| job lifecycle | 8 |

要求的 23 类场景以及 duplicate methods、expired/missing imports、零权重、阈值等边界已覆盖。
旧测试仅 7 个函数中的目录可用性/mode、版本和新增路由断言随新契约更新；
没有删除测试或修改科学算法、原生 parser、checkpoint、数据 fixture。
Ruff、compile/import 和 Git diff/whitespace 检查通过。
详见 [pytest 证据](audit/module5_test_verification_summary.json)、[技术检查](audit/module5_checks.json)。

真实 E2E 使用独立 Uvicorn TCP 服务和 HTTP 客户端，**7 个任务**全部经历 202 接纳、200 轮询终态：

| HTTP 场景 | 最终结果 |
| --- | --- |
| A：真实 LRECA + SEG | success |
| B：LRECA + FuzDrop weighted，无 import | partial_success；ensemble unavailable |
| C：真实 LRECA + 合成格式 FuzDrop import + SEG，weighted | success；公式精确一致 |
| D：DisMeta only | unavailable，不是 500 |
| 四方法，无 import | partial_success |
| 四方法，有 import | partial_success |
| 单独 FuzDrop 复用引用，independent | success；无 ensemble |

另验证 import HTTP200、错序列引用 422、缺失引用 404。
248-aa 真实样本：LRECA score **0.9999921321868896**、P、CUDA、248 位 attribution/KDE；
SEG 区域 **72–85、89–119、196–247**，覆盖 **97/248 = 0.3911290322580645**。
human checkpoint SHA256 为
`aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc`。

合成 FuzDrop pLLPS **0.68**，权重 0.6/0.4，结果精确为 **0.8719952793121338**。
这里的 FuzDrop pLLPS/pDP/Sbind/regions 都是明确标注的格式测试输入，**不是官方真实预测或校准数据**。
原始归因、KDE、FuzDrop 原生字段和 SEG 区间逐项保留。
[E2E 摘要与响应文件](audit/module5_api_smoke/summary.json) 含模型身份、公开 provenance、
完整计时和日志 hash；测试服务器已关闭，没有向 FuzDrop/DisMeta 提交序列。

## 15. 未解决事项与边界

1. FuzDrop 自动提交仍不可用，真实官方输出未在本轮获取；不绕过浏览器验证。
2. DisMeta 调用与原生结果契约未确认，继续 blocked。
3. 未做共享数据集 probability calibration；默认 ensemble threshold 仅是实验性决策规则。
4. 当前内存实现需单 worker，重启丢失任务/引用；公共部署仍需共享存储、认证/租户隔离、
   队列恢复与数据保留策略。随机 ID 不是认证机制。
5. Linux/Docker 未实际运行；需要重新安装目标平台环境、SEG 二进制并验证 GPU/驱动条件。
6. human-specific 模型身份延续已有验证，checkpoint 与某个 dataset5 文件的精确训练映射
   仍为 unconfirmed，不把文件名当成训练数据映射证据。
7. 两条既有依赖弃用 warning 保留，未为消除提示升级已锁定依赖。

本模块在上述明确边界内完成。没有开发复杂前端、Feature Viewer、替代预测器、训练/校准或正式部署。

Module 5 completed.
