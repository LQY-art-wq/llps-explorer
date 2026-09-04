# Module 5 实际命令与验证

执行目录为项目根目录；记录只使用相对路径。Windows PowerShell 中文 I/O 使用 UTF-8，
Python 进程设置 `PYTHONUTF8=1`。以下 `python` 指本项目 `.venv` 的解释器；
科学计算由既有独立 `.lreca-venv` worker 执行，未更换模型或依赖。

## 起点、实现与增量检查

1. 阅读 Module 5 用户附件以及既有 registry、API、schema、adapter 和测试。
2. 运行私有 `.audit/module5_snapshot.py`，保存 Module 4 完成后的 **226** 个第一方文件 SHA256
   和原文归档；没有改 Git index。
3. 分别实现/检查请求与评分、导入存储、registry/API、orchestrator/job 生命周期。
4. 按新文件范围执行以下定向测试（包含开发中修正，最终以完整 gate 为准）：

```text
python -m pytest backend/tests/test_analysis_request.py backend/tests/test_ensemble.py -q
python -m pytest backend/tests/test_imported_results.py -q
python -m pytest backend/tests/test_orchestrator.py backend/tests/test_analysis_jobs.py -q
python -m pytest backend/tests/test_analysis_api.py backend/tests/test_method_registry.py backend/tests/test_module0.py backend/tests/test_fuzdrop_api.py backend/tests/test_seg_api.py backend/tests/test_dismeta_api.py -q
```

开发期间已处理的具体问题：并行接线时缺少 cleanup 构造参数、一个合成 TSV 的列顺序错误、
测试对短时间异步完成的假设、DTO 序列化警告可能携带输入、LRECA 原生标签一致性、
Python 3.10 取消 API 差异，以及直接服务构造的超大 TTL。没有修改原生科学算法来让测试通过。

## 完整后端回归

```text
python .audit/module5_run_validation.py
```

内部实际执行：

```text
python -m pytest backend/tests -q --junitxml=.audit/module5_full_tests.junit.xml
```

结果：**726 passed，0 skipped，2 warnings，49.88 秒**。两条 warning 来自既有
Starlette/httpx 和 anyio 弃用提示，没有为此更换已锁定依赖。
保留原始私有 stdout/JUnit，并输出去内部路径、hostname 的公开副本：

- [完整日志](audit/module5_full_tests.log)
- [JUnit](audit/module5_full_tests.junit.xml)
- [分组、计数和证据 SHA256](audit/module5_test_verification_summary.json)

运行 `.audit/module5_enrich_validation.py` 从同一次 JUnit 提取分组和 hash；不是重跑测试。

## Ruff、编译、导入与版本

```text
python -m ruff check --config backend/pyproject.toml backend scripts
python -m compileall -q backend/app backend/lreca_runtime scripts
python -c "import sys; import app.main; from app.services.orchestrator import AnalysisOrchestrator; from app.services.analysis_jobs import AnalysisJobService; assert 'torch' not in sys.modules; print('Module 5 imports passed; Torch not imported by API')"
python -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e ./backend
```

最终检查通过；可编辑项目元数据更新为 **0.5.0**，没有解析或升级依赖。
服务与核心 schema 可直接导入，API 导入不会加载 PyTorch。
检查结果见 [技术验证](audit/module5_checks.json)。

## 真实 HTTP E2E

```text
python scripts/smoke_module5.py
```

脚本启动自己管理的实际 Uvicorn TCP listener，在 loopback 地址使用 HTTP 客户端提交、轮询，
最后关闭服务与科学 worker。不是 TestClient，也不是替代模型。
LRECA/SEG 使用既有真实 248-aa 样本；FuzDrop 输入明确标记为合成格式测试 fixture，
不会冒称真实官方预测。请求不会发送到 FuzDrop/DisMeta。

结果和各请求响应见 [HTTP 验收记录](audit/module5_api_smoke/summary.json)。
必须验证 LRECA+SEG、缺 FuzDrop 导入、导入后加权、DisMeta blocked 四类要求。

## Git 与范围复核

```text
git --no-optional-locks diff --stat
git --no-optional-locks diff --check
python .audit/module5_finalize.py
```

该工作区尚无初始提交，普通 diff 包含之前模块相对骨架的累计变化；因此本轮实际清单以
Module 5 启动时 226 文件快照为基准。私有 finalizer 再做完整 before/after
`git diff --no-index` 与 whitespace check，未改动 index。
它校验既有科学代码、fixture、依赖锁、前端和历史报告未变，并比较旧测试中允许改动的目录/
版本断言，确认没有删除科学回归。
二进制、checkpoint、外部 checkout、环境、缓存和本地 `.env` 均不计入第一方源代码。

参见 [范围复核](audit/module5_scope_review.json) 和 [变更清单](module5_changed_files.txt)。
没有执行 commit/push、正式部署、浏览器自动提交、模型训练或 Module 6 开发。
