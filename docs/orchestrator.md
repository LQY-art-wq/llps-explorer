# Analysis Orchestrator（Module 5）

Module 5 提供异步任务、能力路由、导入结果引用和实验性加权评分。前端仍为原有占位页。
`GET /api/v1/methods` 是当前能力目录；方法独立端点继续保留 Module 1–4 的原生契约。

## 架构与部署边界

```text
POST /api/v1/analysis                  POST /methods/fuzdrop/import
          |                            strict existing parser
          v                                      |
AnalysisJobService admission <-------- ImportedResultStore (TTL)
  sequence validation / reference identity / snapshot pinning
          |
          v
local bounded runner  [future: HTTP -> queue -> same worker boundary]
          |
          v
AnalysisOrchestrator.run_analysis() <--- MethodRegistry
          |
          +-------- LRECA automatic -> resident model worker -> CPU / CUDA
          +-------- SEG automatic   -> standard segmasker process
          +-------- FuzDrop         -> validated imported result copy
          `-------- DisMeta         -> integration_blocked, no adapter call
          |
          v
method snapshots / independent native results
          |
          v
optional EnsembleCalculator (LRECA + FuzDrop global scores only)
          |
          v
AnalysisJobStore (TTL) <------------ GET /api/v1/analysis/{job_id}
```

`AnalysisOrchestrator.prepare()` 校验输入并取得导入快照；`run_analysis(prepared, job, on_update)`
不依赖 FastAPI Request。`AnalysisJobStore` 和 `ImportedResultStore` 是可替换的存储接口。
未来队列 worker 可恢复经过验证的输入并调用相同调度逻辑，将状态写入共享 DB/Redis。
本模块没有引入 Celery、Kafka、数据库或分布式锁。

## 方法目录

| 方法 | category | integration_mode | automatic | manual import | available |
| --- | --- | --- | --- | --- | --- |
| LRECA | prediction | local_automatic | 取决于模型就绪 | false | 自动可用时 true |
| FuzDrop | prediction | manual_import | false | 默认 true | 默认 true |
| SEG | annotation | local_automatic | 取决于标准程序就绪 | false | 自动可用时 true |
| DisMeta | annotation | integration_blocked | false | false | false |

四种方法的 `method_supported=true` 仅表示本项目识别其科学方法，不保证接入就绪。
`available = automatic_analysis_available OR manual_import_available`。
FuzDrop 的 `integration_status=manual_import_only`；禁用导入时变为 unavailable。
DisMeta 的 `integration_status=blocked`、`reason=integration_contract_unverified`。
目录只对本地自动方法做最长 2 秒的就绪检查；FuzDrop 和 DisMeta 不产生网络调用。

目录是 Module 5 调度契约。独立 FuzDrop health/analyze 仍为 `browser_protected` / 503，
独立 DisMeta health/analyze 仍为 `unknown` / `INTEGRATION_BLOCKED` / 503；这与目录的调度模式
是不同层级。原生结果中的 `integration_mode`、科学来源和 coordinate provenance 不被改写。

## 请求、轮询与原生结果

`POST /api/v1/analysis` 成功接纳返回 HTTP **202** 和完整 queued Job。示例：

```json
{
  "sequence": "ACDEFGHIKLMNPQRSTVWY",
  "sequence_name": "example",
  "selected_methods": ["lreca", "seg"],
  "prediction_mode": "independent",
  "weights": null,
  "external_results": {}
}
```

这是格式示例，不是科研阳性样本。序列重用单条 FASTA / 标准 20 氨基酸的既有校验；
去空白、ASCII 大写后生成 SHA256。方法列表不能为空、重复或包含未知名称。
`sequence_name` 可省略，最长 128 字符，不接受控制字符。独立模式拒绝非空 weights。

`GET /api/v1/analysis/{job_id}` 返回 HTTP 200 当前快照，包括：

- `job_id / created_at / updated_at / expires_at / status`；时间为带时区的 UTC。
- `sequence: {name, length, sha256}`，以及 `selected_methods / prediction_mode / weights`。
- `methods`：仅包含请求选择的方法，每项有 `method / status / integration_mode / runtime_ms /
  result / error / reason / warnings`；逐方法 queued、running、terminal 状态可分别轮询。
- `ensemble`：独立模式为 null；加权模式在任务完成后为成功评分或明确 unavailable。
- `warnings`：任务级固定解释；未选择 DisMeta 时不产生 DisMeta 提示。

`methods.*.result` 就是各方法已验证的原生成功 DTO。SEG 没有全局分数或 P/N；失败、待导入、
不可用状态的 result 为 null。LRECA / FuzDrop 原生 payload 为支持残基定位会保留各自序列，
顶层只重复必要元数据。原生科学分数、归因、KDE、区域顺序及 1-based inclusive 坐标不变。
Job 的最终结果由 methods 与 ensemble 构成，不再重复嵌套一份相同结果。

## FuzDrop 导入、身份和数据生命周期

现有 `POST /api/v1/methods/fuzdrop/import` 继续返回完整 FuzDrop 原生字段，额外提供
`result_id / expires_at / validation_status="valid"`。原有 `status="success"` 保留，
没有把原生状态改为 valid。解析仍由原先严格 parser 完成。仅校验格式和用户声明，
不认证数据确由官方网站产生；合成测试 fixture 也不会被描述为真实预测。

导入后分析使用以下附加字段，无需重复上传 TSV：

```json
{
  "selected_methods": ["lreca", "fuzdrop"],
  "prediction_mode": "weighted",
  "weights": {"lreca": 0.6, "fuzdrop": 0.4},
  "external_results": {"fuzdrop": {"result_id": "fuzdrop_result_REPLACE_WITH_RETURNED_ID"}}
}
```

将这些字段与实际 sequence 合并提交。存储的 `ImportedMethodResult` 包含 method、result_id、
真实重算的 sequence_sha256、sequence_length、normalized_result、source、imported_at、
expires_at、coordinate_provenance、validation_status。
提交分析时先核对 SHA256 与长度；错误序列为 **422 EXTERNAL_RESULT_SEQUENCE_MISMATCH**，
不存在或已过期为 **404 EXTERNAL_RESULT_NOT_FOUND**，且不会启动自动方法。
引用可重复使用；读取不续期。未提供引用是合法任务，FuzDrop 为 external_result_required。

默认导入 TTL **3600 秒**、最多 **128** 项；容量满为 503，不挤出尚未过期项。
TTL 从入库计时，使用单调时钟，导入原始时间仍保留。接纳的任务固定一份已验证结果副本，
导入随后过期不使正在运行的任务失效；新提交再用过期引用会被拒绝。
每次存取清理过期导入，应用还运行最长 **60 秒**一次的清理循环，空闲时也会移除过期数据。

Job 默认最多 **128** 项，同时执行最多 **4** 个；终态结果从完成起保留 **3600 秒**。
queued/running 不在执行中途过期，它们受排队与运行时限约束。过期 Job 返回
**404 ANALYSIS_JOB_NOT_FOUND**；容量满返回 **503 ANALYSIS_CAPACITY_EXCEEDED**。
所有返回值深拷贝，调用者修改快照不会污染后续轮询或引用。
应用关闭会取消自有任务、清理 stores，然后关闭 adapters；进程重启会丢失所有本地任务和引用。

## 状态与失败隔离

| 请求的方法最终状态 | Job 最终状态 |
| --- | --- |
| 全部 success | success |
| 至少一个 success，另有非成功方法 | partial_success |
| 没有 success，至少一个执行 failed | failed |
| 没有 success/failed，但需要外部导入 | external_result_required |
| 其余全不可用或 skipped | unavailable |

方法状态为 queued、running、success、failed、unavailable、external_result_required、skipped。
当前路由不需要主动生成 skipped。DisMeta only 返回正常 Job + unavailable；
FuzDrop only 没有引用为 external_result_required，有引用且导入开启为 success；SEG only 合法。
如果两方法成功但 FuzDrop 没有 pLLPS，Job 仍按方法成功规则为 success，ensemble 单独 unavailable。

本地方法并发执行，异常转换为固定错误，不返回 traceback、异常文本或内部路径。
METHOD_EXECUTION_FAILED、METHOD_RESULT_INVALID、METHOD_RESULT_SEQUENCE_MISMATCH、
METHOD_EXECUTION_CANCELLED 只影响对应方法。异常标签或不匹配序列不会成为成功结果。

默认方法时限 **150 秒**，运行阶段总时限 **180 秒**（两者取更小的剩余时间）；
排队等待另有最长 **180 秒**，超时为 ANALYSIS_QUEUE_TIMEOUT。
原生 LRECA RPC 120 秒、SEG 子进程 10 秒的限制仍有效，通常先结束或报告原生错误。
调度超时为 METHOD_TIMEOUT，保留其他成功结果。清理可能晚于 Job 完成：LRECA 会等待已有 RPC，
SEG 会终止自己的子进程。调度器持有这些清理任务；同方法仍在清理时新任务收到
METHOD_BUSY_AFTER_TIMEOUT，清理结束后可恢复，不把迟到结果写回已完成 Job。
关闭调度器对残留 adapter 清理最多等待 1 秒，然后由 adapter 关闭其实际进程。

时限适用于遵守 async 接口、不会长时间阻塞事件循环的 adapters；未来不受控的同步算法应放在
独立进程/服务并由进程监督器终止，不能靠取消 Python coroutine 强制中止任意同步死循环。

## Ensemble 的唯一数学定义

只有选择 LRECA + FuzDrop、两者 success 且都有有效全局分数时才计算：

`score = weights.lreca * lreca.raw_score + weights.fuzdrop * fuzdrop.raw_score`

唯一实现是 `EnsembleCalculator`；0.82 / 0.68 与 0.6 / 0.4 得到 **0.764**。
当前两方法均 `calibrated_score == raw_score`、`calibration_status=not_calibrated`。
ensemble 返回 `score`，不返回 probability；
`interpretation_status=experimental_weighted_score` 明确说明尚未经共享数据集校准。

权重必须恰好包含两种 predictor，各为有限数值且在 [0,1]；和的绝对容差为 **1e-9**。
不归一化、不裁剪；容差允许的极小和偏差也保留在公式中。零权重同样要求两个成功输入。
SEG/DisMeta 权重为 INVALID_ENSEMBLE_METHOD；缺键、非数值、越界、错误和为
INVALID_ENSEMBLE_WEIGHTS；缺选一个 predictor 为 WEIGHTED_MODE_REQUIRES_LRECA_AND_FUZDROP。
这些均为 422，不静默切换模式。

缺 FuzDrop 引用：`fuzdrop_external_result_required`；LRECA 非成功：`lreca_result_unavailable`；
FuzDrop 无 pLLPS：`fuzdrop_global_score_missing`。此时 ensemble 的 score/label 均为 null。
不把剩余方法权重变成 100%，不从 pDP、归因、KDE、SEG 或 DisMeta 产生全局分数。

`ENSEMBLE_THRESHOLD` 默认 **0.5**，操作符 **>=**，由后端给出 P/N。
它是实验性产品决策阈值，不是生物学验证或概率校准；不改变原生 LRECA 的 `>0.5` 和
FuzDrop 的 `>=0.60` 分类规则，也不覆盖原生各自 label。

## 配置、日志和生产准备

完整示例见 [backend/.env.example](../backend/.env.example)。新增配置：
ENSEMBLE_THRESHOLD、ANALYSIS_METHOD_TIMEOUT_SECONDS、ANALYSIS_JOB_TIMEOUT_SECONDS、
ANALYSIS_JOB_TTL_SECONDS、ANALYSIS_MAX_JOBS、ANALYSIS_MAX_CONCURRENT_JOBS、
EXTERNAL_RESULT_TTL_SECONDS、EXTERNAL_RESULT_MAX_ENTRIES。配置拒绝非有限或越界值。

方法日志记录 job_id、method、status、runtime_ms、sequence_length、sequence_sha256，
不记录完整序列、TSV 或异常堆栈。HTTP 错误使用固定消息，丢弃校验错误中的输入与上下文。
公开结果只有 checkpoint 文件名、SHA256、模型/程序版本，无服务器内部绝对路径。

本模块无新增第三方依赖、Windows 专属代码、浏览器运行依赖或用户目录假设。
API 环境 Python 3.12.13；worker Python 3.10.19 / PyTorch 2.1.1+cu118 /
NumPy 1.23.0 / SciPy 1.10.1 保持原锁定。CPU/CUDA 自动配置与模型启动一次、驻留复用的生命周期
不变，配置和科学兼容细节见 [LRECA runtime](lreca_runtime.md)、[SEG runtime](seg_runtime.md)。

当前应以 **单个 Uvicorn worker** 运行；多 worker/多副本需要共享 stores、队列、任务认领及恢复。
本模块没有持久化、认证/租户隔离或失败重启恢复；随机 ID 是难猜的引用，不是访问控制。
对公网部署前应在 Deployment Module 增加这些部署策略，并评估容量、日志与数据保留政策。
Linux/Docker 代码边界已准备，目标系统与镜像尚未实测。需要安装目标平台依赖和标准 SEG，
通过环境变量挂载校验过的 checkpoint。核心 inference 不需要重写，只需要容器化和改变部署边界。

本模块不部署正式服务器，不配置域名、Nginx 或 Kubernetes，不实现 Module 6 前端。
