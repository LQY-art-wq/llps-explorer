# Module 10：本地生产式 Linux/Docker 部署与未来服务器就绪报告

日期：2026-09-04  
应用版本：`0.10.0`  
最终状态：`DEPLOYMENT_BLOCKED`

## 结论与验收边界

Module 10 已完成可审查的生产部署实现、部署文档、静态检查和 Windows 主机侧回归，但当前电脑没有可用的 Docker CLI、Docker Compose、Docker Desktop 服务或其他 Linux 容器运行时。因此，要求的 Linux Docker stack 未能实际启动，不能达到 `PRODUCTION_READY_WITH_UNVERIFIED_ITEMS` 的硬性成功条件。

2026-09-04 的直接探测依次尝试了 `docker --version`、`docker compose version` 和 `docker info`；三条命令均在进程启动前以 `CommandNotFoundException` 结束。Docker daemon、Compose 和 Linux Containers 都未确认。机器审计结论为 `DOCKER_RUNTIME_UNAVAILABLE`，证据见 [docker_runtime_audit.json](audit/module10/docker_runtime_audit.json) 和 [docker_commands_attempt.log](audit/module10/docker_commands_attempt.log)。本报告把宿主机测试、静态配置检查和真实容器验收严格分开；没有运行的项目一律不记为通过。

没有购买服务器、域名或证书，没有配置公网 DNS、Nginx、Kubernetes 或正式 HTTPS，也没有自动安装 Docker。下一次验收应在具备 Docker Desktop Linux Containers 或 Ubuntu Docker Engine 的机器上继续执行 [deployment.md](deployment.md) 与 [operations.md](operations.md) 中的待执行步骤。

## 已实现的生产拓扑

[`compose.yaml`](../compose.yaml) 声明八个服务，其中 `migrate` 是 one-shot migration，其余七个为长驻服务：

```text
Browser
   |
   v
Caddy                    [唯一发布主机端口]
   |-- / ---------------> Next.js production server
   `-- /api/* ----------> FastAPI backend
                              |-- PostgreSQL [结果与任务的 source of truth]
                              `-- Redis / RQ [job_id 与协调状态]
                                         |
                                         v
                                  analysis worker
                                     |-- private LRECA service
                                     |       `-- resident human-specific model
                                     `-- NCBI segmasker

FuzDrop: validated manual import only
DisMeta: INTEGRATION_BLOCKED
```

只有 Caddy 声明主机 `ports`；frontend、backend、worker、LRECA、PostgreSQL 和 Redis 仅在 Compose 网络中通信。应用容器配置为非 root、只读根文件系统、移除 Linux capabilities、启用 `no-new-privileges`，临时写入使用有限的 `tmpfs`。这些结论来自配置审查，尚未由真实容器运行验证。

## 主要实现

### 配置、镜像与启动门禁

- 根目录 [`.env.example`](../.env.example) 只提供安全占位值和可配置项；`.env`、模型权重、备份、导出、私钥和证书已加入 Git/Docker 忽略规则。
- production 配置对数据库、Redis、session secret、LRECA 服务和 checkpoint 身份执行 fail-fast；拒绝弱占位 secret、通配 CORS 和 HTTPS 下不安全 cookie。开发模式仍可继续使用原来的 Windows、SQLite 和进程内任务执行方式。
- backend/worker 使用 Python `3.12.13-slim-bookworm`，LRECA 使用 Python `3.10.19-slim-bookworm` 与冻结的 PyTorch 运行环境，frontend 使用 Node `24.19.0` 和 pnpm `11.19.0`，PostgreSQL、Redis 和 Caddy 都使用固定版本标签；没有使用 `latest`。
- `migrate` 独立运行 `alembic upgrade head`，成功后 backend/worker 才启动；web 进程不执行 drop/create，也不让多个 web worker 并发迁移。
- Next.js Dockerfile 使用 multi-stage production build 和 standalone server，不依赖 host `node_modules`。主机侧真实执行了 production build，但 Docker image build 未执行。

### LRECA 独立服务

- 新增独立私有 FastAPI 服务，提供 `/health/live`、`/health/ready` 和 `/internal/v1/analyze`。浏览器与主 backend 不直接加载模型，worker 通过内部 adapter 调用该服务。
- startup 生命周期为：定位只读挂载的 checkpoint、计算并比对 SHA256、加载一次、选择配置设备、执行 `model.eval()`、设置 ready。SHA 不一致时保持 live、拒绝 ready 和推理。
- checkpoint 文件名为 `human_1_RCNN_ECA_parallel_089-0.9802.pt`，预期 SHA256 为 `aa625942a726d24c15022f9486d0fc26e91ee0435ad554a8cd259825d8d7bbcc`；第一方主仓库不跟踪权重、权重不 COPY 进镜像，通过 `${LRECA_MODEL_DIR}` 只读挂载到 `/models/lreca`。
- LRECA source stage 改为 blob-filtered sparse checkout，只保留六个 hash-audited source/data 文件；移除 remote 后逐个确认上游 Git tree 中的模型 blob 不存在，再复制到 runtime stage。静态门禁已覆盖这一构造，最终 image layer 仍需 Docker build 后扫描。
- `LRECA_DEVICE=auto|cpu|cuda` 继续受支持。默认 Compose 使用 CPU；当前 Compose 未申请 GPU device，GPU passthrough 必须以后用 NVIDIA Container Toolkit 和单独 override 实测。
- 默认一个 LRECA model process、单次受控推理并发、四个 Torch threads。以后每张 GPU 维持一个模型进程，通过队列扩展，避免多 Uvicorn worker 重复占用 VRAM。
- 内部响应复用现有 normalized LRECA schema，保留 global prediction、Grad-CAM、KDE 和 1-based 坐标；公共元数据只返回 filename、SHA256、variant、repository commit 和 device，不返回服务器绝对路径。

以上行为已由宿主机单元/集成测试覆盖，但 startup SHA、resident load 和真实 inference 尚未在 Linux container 内运行。

### Redis/RQ worker 与持久任务

- production 提交路径先在 SQL 中创建 `queued` job，再向 Redis/RQ 只提交 `job_id`，立即返回给现有 frontend polling。完整蛋白序列不会额外复制到 queue payload。
- worker 从 PostgreSQL 读取输入，调用 LRECA service 与本地 SEG，沿用 FuzDrop 合法手工导入、DisMeta blocked routing 和冻结的 weighted ensemble，最后把完整状态与结果写回 PostgreSQL。
- 有限 retry 默认最多两次；transport/临时 worker 故障可重试，validation error 与 deterministic scientific failure 不无限重试。
- PostgreSQL advisory lock 用于 production 的同一 `job_id` 执行互斥；SQLite 开发模式保留进程内锁。状态守卫与确定性 queue job ID 防止重复创建冲突结果。
- worker 启动与 maintenance 扫描过期 `running` job，可安全重排或写入结构化 `interrupted`。周期 retention 由 backend 的 `AnalysisJobService` cleanup loop 执行，并通过 PostgreSQL advisory lock 避免多进程重复清理。Redis AOF 配置预期改善 queue state 持久性，但 PostgreSQL 始终是已完成结果的 source of truth。
- worker healthcheck 验证当前 RQ worker 注册、目标 queue、worker state 与 heartbeat；web readiness 同时检查 PostgreSQL、Redis/RQ、可用 worker、LRECA 与 SEG。

真实 Redis、RQ、worker kill/restart、AOF 恢复和 PostgreSQL advisory lock 尚未在容器中执行。现有测试证明代码路径和状态转换，不等同于生产恢复演练。

### SEG、FuzDrop 与 DisMeta

- worker Dockerfile 定义在 build time 安装固定 NCBI BLAST+ `2.17.0+` Linux x64 包，并使用已审计 MD5；构建时将执行 `segmasker -version` 和 12 个 Q 的真实 probe，预期原生 `0-11` 输出对外转为 1-based inclusive `1-12`。
- runtime 继续使用参数数组、`shell=False`、stdin、安全临时边界、timeout 和结构化错误；SEG 参数 `window=12`、`locut=2.2`、`hicut=2.5` 未变。
- 因未构建 worker image，Linux 动态库、版本、probe 和 frozen SEG fixtures 尚未真实验证。
- FuzDrop 继续只接受后端严格验证的官方格式手工导入，不自动访问官方站点、不绕过 reCAPTCHA；没有合法 import 时不生成预测，也不计算 weighted ensemble。格式、sequence/hash 与坐标校验只能验证导入契约，结果来源和 1-based inclusive 坐标仍是用户声明，不能证明文件确实来自官网。
- DisMeta 继续为 `INTEGRATION_BLOCKED`，没有 mock、替代 IDR predictor 或伪造结果。

### PostgreSQL、Redis、Caddy、前端与安全边界

- PostgreSQL `16.10-bookworm` 使用命名卷；Redis `7.4.5-alpine` 使用命名卷、密码与 AOF。数据库保存 job、canonical sequence、结果、导入、ownership digest 和过期时间。
- Caddy 是唯一入口，把 `/` 转发到 Next standalone，把 `/api/*` 转发到 backend；加入 request/body 限制和安全响应头。local 配置使用 HTTP，未来域名示例单独保存在 `docker/caddy/Caddyfile.production.example`，不会假装已获得证书。
- backend 增加 JSON structured logging、request ID、可信代理/Origin 检查、安全状态与版本 endpoint。已测路径不会主动把 secret、完整 sequence、DSN、内部 URL 或 checkpoint 绝对路径写入日志/API；formatter 仍可能记录第三方异常 message/traceback，因此生产环境必须限制日志访问、保留期和导出位置，并在容器运行时继续审计。
- Redis 固定窗口限流按匿名 owner/IP 的 HMAC key 工作，返回结构化 `429`；队列与 per-owner admission limit 返回结构化容量错误。当前只用 fake Redis/单元测试验证，没有真实 Redis 压力或 Caddy 端到端验收。
- browser bundle 扫描了 14 个生产 JavaScript 资产、共 840,196 bytes，服务器内部 hostname、模型路径和私有绝对路径命中为 0；证据见 [frontend_bundle_privacy.json](audit/module10/frontend_bundle_privacy.json)。
- About/Methods 页面已显示真实 capability 与 provenance，Privacy 页面说明匿名 ownership、七天默认 retention、手工 FuzDrop 与敏感 sequence/backup 边界，并保留 prediction 不是实验验证的科学说明。现有证据来自 source、unit tests 和 host production build；尚未通过 Caddy 做 browser E2E。

### 备份、恢复与数据生命周期

- [backup_db.sh](../scripts/backup_db.sh) 使用 `pg_dump` custom format、`umask 077`、临时文件与原子改名，并拒绝覆盖现有目标。
- [restore_db.sh](../scripts/restore_db.sh) 要求显式 `--confirm-replace`，先校验 archive，停止写入服务，在单事务中恢复，再运行 migration 并重启服务。
- 备份包含完整蛋白序列、结果、手工导入和 ownership digest，属于敏感研究数据；默认建议加密日备份、异地副本和最长七天的可审计清理。应用 retention 不会自动删除 dump。
- 脚本与隐私策略已静态审查；没有真实 PostgreSQL dump 或隔离 restore drill，因此不能声称 RPO/RTO 或恢复能力已验证。完整程序见 [backup_restore.md](backup_restore.md)。

## 已实际执行的验证

| 范围 | 结果 | 证据与解释 |
| --- | --- | --- |
| Docker 环境探测 | **blocked** | CLI/Compose/daemon/Linux Containers 均不可用；[runtime audit](audit/module10/docker_runtime_audit.json) |
| Backend 完整测试 | **816 passed, 0 failed** | [log](audit/module10/backend_full_final.log)、[JUnit](audit/module10/backend_full_final.junit.xml) |
| Module 10 backend 聚焦测试 | **35 passed, 0 failed** | [log](audit/module10/backend_module10_final.log)、[JUnit](audit/module10/backend_module10_final.junit.xml) |
| Frontend 完整测试 | **324 passed, 0 failed** | [log](audit/module10/frontend_tests_final.log) |
| Module 8 saved API/science artifact regression | **263/263 passed** | 离线读取保存的 JSON/TSV/FASTA 与 frozen bytes；0 HTTP、0 新 job、0 模型推理；[JSON](audit/module10/module8_api_regression.json)、[log](audit/module10/module8_api_regression.log) |
| Backend Ruff / compileall / pip check | **passed** | [Ruff](audit/module10/backend_lint_final.log)、[compileall](audit/module10/compileall_final.log)、[pip check](audit/module10/pip_check_final.log) |
| Backend wheel | **passed** | `llps_explorer_backend-0.10.0-py3-none-any.whl`；[log](audit/module10/backend_wheel_final.log) |
| Frontend lint / typecheck / production build | **passed** | [lint](audit/module10/frontend_lint_final.log)、[typecheck](audit/module10/frontend_typecheck_final.log)、[build](audit/module10/frontend_build_final.log) |
| Deployment static verifier | **93/93 passed** | 只检查源文件和约束，不需要 daemon；[log](audit/module10/deployment_static_final.log) |
| LRECA sparse source host probe | **passed** | 六个 allowlisted 文件、clean Git identity、七个 upstream weight blob 均未获取；不是 Docker build/image scan；[JSON](audit/module10/lreca_sparse_source_probe.json) |
| Compose YAML | **parsed; 7/7 selected invariants** | PyYAML 语法与选定拓扑检查，不是 Compose schema/daemon 验证；[JSON](audit/module10/compose_yaml_parse.json) |
| Browser bundle privacy | **passed** | 14 assets、0 forbidden findings；[JSON](audit/module10/frontend_bundle_privacy.json) |
| Module 10 scope freeze | **passed** | 见 [scope_review.json](audit/module10/scope_review.json) 与 [changed files](module10_changed_files.txt) |

完整命令、初次回归发现、修复说明和下一次 Docker 待执行命令见 [module10_commands.md](module10_commands.md)。初次完整 backend run 曾发现一个 job 最终状态发布竞态和一条过时的绝对路径日志断言；竞态通过同一 immutable snapshot 原子发布最终 method/job 状态解决，日志测试改为要求安全 filename/SHA 并拒绝 absolute path。后续审查又修正了 LRECA source transitive weight copy、health module 号和 transient retry 分类，并更新两条旧 module 断言；最终完整套件为 816/816。

## 科学与范围冻结审计

审计以 Module 10 开始时保存的 532 文件 SHA256 manifest 为基线，不使用当前 Git status 猜测基线。最终审计结果为：65 个新增、25 个修改、0 个删除，共 90 个 Module 10 变更；新增数包含保留的测试/审计证据。43 个冻结科学文件全部逐字节未变；unexpected change 和 violation 均为 0。

保持不变的冻结边界包括 LRECA architecture/checkpoint identity/positive-class mapping/threshold/Grad-CAM/KDE、SEG 参数与解析、FuzDrop 手工导入政策、DisMeta blocked 状态、weighted ensemble formula、calibration status 和 1-based coordinate contract。`external/lreca` 保持 commit `0b4b48ab7870529a34028c6e30dfba42eddbf215`、工作树 clean，六个审计源文件 hash 未变。checkpoint 实际 SHA 与 manifest 一致。实际 `git ls-files` 敏感文件审计对模型权重、`.env`、backup/export、PEM/key 返回空；131 个 production/deployment 文件的 Windows absolute path 命中为 0。

Module 8 冻结回归为 263/263，但该 wrapper 只离线读取保存的 JSON/TSV/FASTA 和当前 mapper/frozen bytes；它发出 0 个 HTTP request、创建 0 个新 job、执行 0 次模型推理。它证明保存证据与当前映射/冻结字节仍一致，不能替代当前 HTTP/API、模型推理或 Linux Docker scientific regression。

## 性能依据与初始服务器建议

本轮没有 Docker/Linux benchmark。以下是 Module 1 的 Windows 主机已测数据，用于给出保守的初始容量目标：

| Sequence length | CPU global | CPU full | CUDA global | CUDA full |
| ---: | ---: | ---: | ---: | ---: |
| 50 | 5.313 ms | 89.593 ms | 5.727 ms | 81.656 ms |
| 100 | 15.468 ms | 112.136 ms | 5.369 ms | 96.766 ms |
| 500 | 37.764 ms | 410.552 ms | 17.475 ms | 363.562 ms |
| 1000 | 86.853 ms | 1085.733 ms | 32.103 ms | 1038.957 ms |
| 2000 | 150.881 ms | 3650.193 ms | 64.025 ms | 3676.974 ms |

`full` 包含 global prediction、Grad-CAM 和 KDE。2,000 aa 时 KDE 单独约 3.1 秒且运行在 CPU，因此 CUDA 显著缩短 global prediction，却没有改善完整请求。已测 lifetime peak RSS 为 CPU 527.332 MiB、CUDA 779.648 MiB，CUDA peak allocated memory 为 124.979 MiB；这些数字不包含 API、PostgreSQL、Redis、Next.js 与容器开销。

初始容量测试目标为 **8 vCPU、16 GB RAM、80 GB SSD、CPU 模式**，配一个 RQ worker、一个 resident LRECA model process 和单次 LRECA 推理并发。最低 pilot 可从 4 vCPU/8 GB/40 GB SSD 起步，但必须下调 Compose memory limits 并只用于单用户验收。GPU 暂不作为首发硬要求；4 GB VRAM 与 6–8 GB 仅是待测试的候选起点，并非已验证容量。当前没有 Linux p95、queue depth、database growth、image size、容器总 RSS、OOM 或并发负载数据，服务器规格必须由这些实测修订。

## 最终 30 项回答

1. **Docker Desktop 是否真实可用？** 否。CLI、Compose、Desktop 服务/进程和 daemon 均未找到，状态为 `DOCKER_RUNTIME_UNAVAILABLE`。
2. **是否确认 Linux Containers？** 否。没有可用容器 runtime，无法查询或启动 Linux Containers。
3. **实际启动了哪些 services？** Module 10 Docker 服务一个也未启动。Compose 静态声明 `reverse-proxy`、`frontend`、`migrate`、`backend`、`worker`、`lreca`、`postgres`、`redis`。
4. **PostgreSQL 是否真实运行？** 否。固定 image、healthcheck、命名卷和应用连接已配置，但 container 未启动。
5. **Alembic 是否真实迁移？** 没有在 fresh PostgreSQL container 中运行。one-shot `migrate` service 已实现；宿主机迁移相关回归通过，不等同于生产迁移。
6. **Redis 是否真实运行？** 否。密码、AOF、命名卷、healthcheck 已配置，但 container 未启动。
7. **Queue 是否真实运行？** 否。RQ submission、只传 `job_id`、admission、retry 和状态同步通过测试，但没有连接真实 Redis/RQ runtime。
8. **Worker 是否真实异步执行？** 没有在独立 container 中执行。worker entrypoint、healthcheck、数据库读取、orchestration 与持久化路径已实现并由宿主机测试覆盖。
9. **LRECA 是否已拆成独立 service？** 代码与部署边界已拆分，内部 API 和 remote adapter 已实现；该 service 尚未在 Docker 中实际启动。
10. **Checkpoint 是否 startup SHA256 verify？** startup 校验和 mismatch-not-ready 行为已实现并通过宿主机测试；尚未在 container startup 现场验证。
11. **LRECA 是否只加载一次？** resident single-load 生命周期、并发门与测试已实现；Docker process 内的真实多请求 load-count 仍待验收。
12. **CPU Docker inference 是否通过？** 否，未运行，属于硬性阻塞项。
13. **GPU Docker 是否测试？** 否，状态为 `GPU_DOCKER_NOT_TESTED`；当前 Compose 也未申请 GPU device。
14. **SEG 是否在 Linux container 真实运行？** 否。固定安装、版本门禁和真实 12-Q build probe 已写入 worker image，但 image 未构建/运行。
15. **Frontend 是否 production mode？** 宿主机 Next.js production build 与 standalone generation 已真实通过；Docker production container 未 build/start，因此容器级答案为未验证。
16. **Caddy localhost reverse proxy 是否真实通过？** 否。路由与 headers 通过静态检查，`http://localhost` 未经真实 Caddy container 验收。
17. **History 是否跨 container restart 保持？** 未验证。Module 9 SQL persistence 主机回归通过，PostgreSQL named-volume container restart 未执行。
18. **Worker restart 如何恢复？** 设计为有限 RQ retry，加 PostgreSQL source-of-truth、同 job execution lock、stale-running maintenance；可安全 requeue 时重排，否则标记结构化 `interrupted`，避免永久 `running`。worker kill/restart drill 未执行。
19. **Redis restart 有什么行为？** 设计上已完成结果从 PostgreSQL 恢复，不依赖 Redis；Compose 已配置 Redis AOF，预期改善 queue state 持久性，queued/running job 由 RQ retry 与 SQL recovery 协调。真实 AOF replay、Redis restart、in-flight 行为和重复执行检查未运行，因此这些仍是待验证行为。
20. **Ownership 是否跨 session 验证？** 应用层匿名 owner isolation 与 Module 9/当前回归通过；通过 Caddy、两个真实浏览器 session 和容器重启的 production-like 验收未执行。
21. **Retention 是否周期执行？** backend cleanup loop、可配置周期、PostgreSQL advisory lock 与测试已实现；Docker backend lifecycle 下的周期执行和短 TTL 实测未执行。
22. **Rate limit 是否真实验证？** structured `429` 和 Redis limiter 由 fake Redis/单元测试验证；真实 Redis、代理 IP 与并发请求验收未执行。
23. **Backup / restore 是否真实通过？** 否。安全脚本与隔离 drill 文档已完成，仅作静态审查，未产生/恢复实际 dump。
24. **Linux Docker scientific regression 是否与 frozen baseline 一致？** 未验证。263/263 仅是离线保存 artifact/mapper/frozen-byte 回归，冻结 science hash 全部一致；没有当前 HTTP、模型推理或 Linux LRECA/SEG 输出证据。
25. **当前推荐服务器 CPU / RAM 是多少？** 初始容量测试目标为 8 vCPU / 16 GB RAM / 80 GB SSD；4 vCPU / 8 GB 只作为减配的单用户 pilot。两者都需由 Linux 实测确认。
26. **是否推荐 GPU？依据是什么？** 首次部署不要求 GPU。Windows benchmark 显示 2,000 aa global inference 从 150.881 ms 降到 64.025 ms，但包含 KDE 的完整请求约 3.65–3.68 s，瓶颈主要是 CPU KDE；只有 global/attribution 吞吐成为实际瓶颈并完成 Linux GPU 验证后才建议使用。
27. **未来 Ubuntu 服务器还需要做什么？** 安装并验证 Docker Engine/Compose；配置专用用户、防火墙、`.env` secrets 和只读 checkpoint；执行 Compose schema/build/up、fresh migration、全服务 health、真实 LRECA CPU/SEG、科学 regression、browser E2E、ownership、retention、rate limit、restart/recovery、backup/restore、安全与负载测试；建立监控、备份与更新回滚流程。
28. **未来域名 / HTTPS 还需要做什么？** 配置 DNS A/AAAA、80/443 firewall、production Caddy override 与持久 `/data`/`/config`；把 public URL/CORS/cookie 改为精确 HTTPS origin；验证证书签发与续期、HTTP 跳转、Secure cookie、security headers、Origin policy 和浏览器行为。
29. **当前仍有哪些未验证项？** Docker/Compose/daemon/Linux Containers、Compose schema、所有 image build/layer scan、八个 service、fresh PostgreSQL/Alembic、真实 Redis/RQ/worker、LRECA CPU/GPU container inference、SEG Linux、Caddy headers与浏览器 console、完整 browser E2E、5,000-aa queue/viewer/CSV E2E、FuzDrop synthetic manual-import Docker E2E、DisMeta blocked Docker E2E、volume persistence、restart/recovery、OOM 与 graceful shutdown、两 session ownership、周期 retention、真实 rate/queue/body limits、backup/restore、Linux scientific regression、安全 runtime、Linux p95/负载/镜像大小/总 RSS、Ubuntu host、DNS、firewall 和 HTTPS。50,000 aa 只是 abuse ceiling，不是已验证的生产或科学能力。
30. **最终状态是 A / B / C 哪一个？** **C：`DEPLOYMENT_BLOCKED`**。原因是 Linux Docker stack 的核心流程无法运行，尚未满足用户定义的 Module 10 硬性成功条件。

## 下一次可继续的明确入口

安装并启动 Docker Desktop 的 Linux Containers 后，从 [module10_commands.md](module10_commands.md) 的 “Commands for the next Windows Docker Desktop run” 开始。只有完整 Docker flow、恢复、数据生命周期、安全、scientific regression 和 production build/container 验收全部真实通过，才能把状态提升为 `PRODUCTION_READY_WITH_UNVERIFIED_ITEMS`。未来真实 Ubuntu、DNS、HTTPS、production firewall 和可选 GPU 仍需保留为明确未验证项。

Module 10 completed.

DEPLOYMENT_BLOCKED
