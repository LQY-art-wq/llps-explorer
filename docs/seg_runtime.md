# SEG 运行环境、来源与安装

Module 3 使用 **NCBI BLAST+ 2.17.0+ 发行包中的 `segmasker`**，调用真实命令行程序完成
蛋白质低复杂度区域（LCR）注释。SEG 返回 `region_annotation`，不产生 LLPS 分数、P/N 或
模型归因，也不参加 global-score ensemble。

Windows 官方包已下载、校验并实际执行；Linux x86-64 目前仅核实官方发行包和 MD5，
**没有下载 Linux 二进制包，也没有 Linux/Docker 实测**。机器可读来源与所有已知哈希见
[seg-source.json](../external/seg-source.json)。

## 固定版本与完整性

| 项目 | 已确认值 |
| --- | --- |
| implementation | `NCBI segmasker` |
| BLAST+ 发行版本 | `2.17.0+` |
| Windows `-version` 的 Package | `blast 2.17.0`；API 的 `version=2.17.0` |
| Windows application version | `segmasker: 1.0.0`；单独记录为 `application_version`，不能代替包版本 |
| 默认参数 | `window=12`、`locut=2.2`、`hicut=2.5` |
| 输入与输出 | `fasta` → `interval`；`-in -` / `-out -` 分别使用 stdin/stdout |
| Windows archive | `ncbi-blast-2.17.0+-x64-win64.tar.gz`，143,400,333 bytes |
| Windows archive MD5 | `dcd973097407a2910061ff4fb51b09fb`，与官方 `.md5` 一致 |
| Windows archive SHA256 | `ccde8788641e8f4137536aaadedfeac2f3599dbbc6166e701b5d89d19fa79038` |
| Windows segmasker.exe SHA256 | `82f56232e2acf9a4ad3cd84efc6abd7387c1781f3b2f6727b9b1f12158c2381c` |
| Linux archive | `ncbi-blast-2.17.0+-x64-linux.tar.gz`，官方目录标为 282M |
| Linux 官方 MD5 | `bdec166721de3b55f90a3badc83538e8` |
| Linux archive/binary SHA256 | 未下载，均为 null；不能使用 Windows 哈希替代 |

来源：[官方 2.17.0 目录](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/)、
[Windows MD5](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-x64-win64.tar.gz.md5)、
[Linux MD5](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-x64-linux.tar.gz.md5)。
Linux MD5 来自本轮读取的 70-byte 官方校验文本；它不是本项目计算出的 Linux archive SHA256。

## 安装与缓存复用

[setup_seg.py](../scripts/setup_seg.py) 只使用 Python 标准库，支持 `windows-x64` 和
`linux-x64`，默认在当前平台自动选择，默认目标为仓库内 `.tools/seg`。脚本不启动安装 GUI、
不执行下载的二进制、不修改全局 PATH，也不安装 Python 包。

从项目根目录运行，下面两条已在本机验收；Windows 大包完全复用已有缓存：

```powershell
.\.venv\Scripts\python.exe scripts/setup_seg.py --help
.\.venv\Scripts\python.exe scripts/setup_seg.py --platform windows-x64 --destination .tools/seg --archive .tools/seg/downloads/ncbi-blast-2.17.0+-x64-win64.tar.gz --offline
```

安装前已确认目标在本仓库 `.tools` 内，6 个原有文件与审计哈希相同。首次运行保留原文件，
只额外提取同包 `doc/README.txt`（151 bytes）；共保留 7 个文件。重复运行返回
`status=already_verified`、`files_created=0`、`cache_reused=true`、`network_used=false`。
这验证了本地安装和复用，不表示 Linux 分支已经执行。

| 参数 | 行为 |
| --- | --- |
| `--destination PATH` | 安装根目录；包自身仍保留 `ncbi-blast-2.17.0+` 子目录 |
| `--platform auto/windows-x64/linux-x64` | 自动识别或明确选择目标包；不推断 ARM 兼容性 |
| `--archive PATH` | 只读取指定的现有官方 archive；路径不存在时失败，不改用下载 |
| `--offline` | 禁止下载；可重复验收已有缓存 |

首次没有缓存且未指定 `--archive/--offline` 时，脚本通过验证证书的 HTTPS 读取固定官方
MD5 文件和 archive；重定向也只允许官方 HTTPS 主机。它检查发行包 MD5，Windows 还校验
已审计的 archive 和 executable SHA256。后续正确缓存直接复用；错误缓存不被静默覆盖。
Linux 首次实际获取时会计算并输出 SHA256，当前提交的 manifest 仍如实保留未实测状态。

脚本只提取 `segmasker`、同包 `bin/lib/lib64` 中的平台动态库，以及 LICENSE/README/NOTICE
等说明文件。手工读取 tar 内容，不调用 `extractall`；拒绝越界路径、重复目标和文件系统链接
目标。包内合法库链接只在选定成员内解析为普通文件；不会在目标目录创建符号链接。
若已有选定文件内容不同，安装失败并要求另选目标，不覆盖其他安装。其余 BLAST 可执行程序
和数据库不在安装范围。

## 后端配置与调用

| 环境变量 | 默认值与含义 |
| --- | --- |
| `SEG_EXECUTABLE_PATH` | `segmasker`；命令名经 PATH 查找，也可指定实际二进制路径 |
| `SEG_WINDOW` | `12`，正整数 |
| `SEG_LOCUT` | `2.2`，有限非负数 |
| `SEG_HICUT` | `2.5`，有限非负数且不小于 locut |
| `SEG_TIMEOUT_SECONDS` | `10`，正数；子进程执行时间限制 |

配置名为 `SEG_EXECUTABLE_PATH`。安装脚本不修改 PATH，因此本仓库 Windows 安装可在后端
启动前配置：

```powershell
$env:SEG_EXECUTABLE_PATH = '.tools/seg/ncbi-blast-2.17.0+/bin/segmasker.exe'
```

这条相对路径要求从项目根目录启动。其他部署工作目录应配置其明确路径或受控 PATH；
不得把开发用户目录写入代码。后端的 `.env` 读取规则仍见现有启动文档。

`GET /api/v1/methods/seg/health` 做轻量版本/可执行性检查；就绪为 200，不可用为 503。
后端同时要求 Package 2.17.0 和 application 1.0.0；文件未变化时复用二进制 SHA256，
版本检查仍执行轻量 `-version`。重新加载失败时不保留旧的就绪元数据。
`POST /api/v1/methods/seg/analyze` 仅接收一条 `sequence`，参数由服务端配置。
后端显式传入 `-window/-locut/-hicut` 和 FASTA/interval 格式，使用独立 stdin/stdout，
不用 shell 拼接命令或共享 FASTA 临时文件。Windows 子进程使用隐藏窗口；超时或取消时回收
自己的子进程。实际接口和错误契约见 [SEG API](../backend/app/api/seg.py)、
[schema](../backend/app/schemas/seg.py) 与 [process runner](../backend/app/services/seg_process.py)。

可执行文件缺失/不可用返回结构化错误；执行失败或 annotation interval 坏输出为 502，
版本验证失败为 503 unavailable，超时为 504，非法请求为 422。
失败的区域与统计值为 null；成功且没有 LCR 时 `regions=[]`，coverage、region_count 和
longest_region 均为 0。HTTP 不返回二进制路径、内部目录、原始 stderr 或完整输入。

## 科学语义与原生坐标

固定 2.17.0 源包已另行读取并通过官方 MD5 验证，archive SHA256 为
`cdcd9e36f2b581eff9bd8364875a466289253b716d3a8014838a8305a9d11880`。
源码依据是该发行版本，精确成员路径和文件 SHA256 保存在来源 manifest：

- `c++/src/algo/blast/core/blast_seg.c:45–47`：默认 12/2.2/2.5；2236 行设置
  `overlaps=FALSE`，2321–2322 行仅在该开关为真时调用 merge。
- `c++/src/algo/segmask/segmask.cpp:75–87`：offset=0，原样使用 left/right。
- `c++/src/objtools/seqmasks_io/mask_writer_int.cpp:52`：输出 `first - second`；
  core 的 2073 行使用 `rightend-leftend+1` 计算长度。

[官方固定 source ZIP](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-src.zip)。
完整逐行依据见 [源码审计](audit/seg/source_audit.md) 与
[源码证据 manifest](audit/seg/source_manifest.json)。
这些源码证据与实际 Windows 首尾用例共同确认 native interval 为 **0-based inclusive**。
例如 100 个 Q 输出 `0 - 99`，API 为 `[1,100]`；C 端 140-aa 用例输出 `100 - 139`，
API 为 `[101,140]`。转换只对两端各加 1，长度保持 `end-start+1`。

默认 native merge 开关关闭；本地 parser 保留原生区域的顺序和重复项，不新增 merge、
最短长度过滤或重分段。`region_count` 是原生条目数，`longest_region` 是最大条目长度；
`coverage` 是区间并集覆盖残基数除以 N，范围 0–1。并集仅用于统计，不改写返回的区域列表。
短于默认 12-aa 窗口的 11Q 用例实际返回空区域，12Q 返回 `[1,12]`；这只是工具行为验证，
不应据此解释为 LLPS 阴性或生物学证据。

[回归 fixture](../backend/tests/fixtures/seg/README.md) 保存实际 Windows CLI stdout，并保留其
CRLF 字节；Linux 输出允许 LF 换行差异，比较的是相同区间内容。该格式兼容规则不代表已运行
Linux 二进制。输入可以是人工构造的边界用例，输出仍来自真实 SEG，并非合成响应。

## 本机性能记录

[性能原始记录](audit/seg/performance.json) 在 Windows CPU、Python 3.12.13 上对五种长度分别
预热 1 次、测量 5 次。下表为实际中位数；耗时包含新建 CLI 子进程、stdin、解析及结果校验：

| 序列长度（aa） | 中位耗时（ms） |
| ---: | ---: |
| 100 | 40.2523 |
| 500 | 36.6625 |
| 1000 | 39.5880 |
| 2000 | 36.7700 |
| 5000 | 40.0375 |

本组测量未出现随长度增加的异常耗时增长；它不是纯算法计时、Linux 性能或生物学验证。
这些既有记录未因编写运行文档而重新生成。

## 许可、隐私与部署边界

发行包 LICENSE 是 NCBI 的 PUBLIC DOMAIN / United States Government Work notice。
安装保留 LICENSE、BLAST_PRIVACY、README 及同包其他说明；该记录不替代对第三方附带材料
的具体条款核对。`BLAST_PRIVACY` 指向 [官方 usage-reporting 说明](https://www.ncbi.nlm.nih.gov/books/NBK569851/)。
后端对每个 SEG 子进程显式设置 **`BLAST_USAGE_REPORT=false`**，不修改用户全局环境。
因此运行边界不能仅凭“本地工具”推断；这里使用官方给出的 opt-out 配置。

未来 Linux/Docker 应选 x86-64、glibc 环境及 Python ≥3.10，保留 CA certificates 以供安装阶段
验证 TLS。Linux 包的 ELF loader、系统共享库版本和同包动态库依赖尚未实测；需在目标镜像中
检查 `ldd/readelf` 并安装实际需要的系统库，不能把 Windows DLL 或 Windows venv 复制过去。
SEG 路径本身不需要 Torch/CUDA；与 LRECA 同服务部署时，后者的科学环境仍单独管理。

以下仅为未来 Dockerfile 的安装策略片段，**本模块没有据此构建或部署镜像**；基础镜像和系统
库须先完成上述目标平台验证：

```dockerfile
COPY external/seg-source.json /opt/llps/external/seg-source.json
COPY scripts/setup_seg.py /opt/llps/scripts/setup_seg.py
RUN python /opt/llps/scripts/setup_seg.py --platform linux-x64 --destination /opt/seg
ENV SEG_EXECUTABLE_PATH=/opt/seg/ncbi-blast-2.17.0+/bin/segmasker
ENV BLAST_USAGE_REPORT=false
```

镜像构建时从固定官方源安装，不把本机 `.tools` 缓存放进 build context；生产二进制可只读挂载。
如果目标包依赖其 `lib/lib64`，需按实际 loader 结果配置库搜索路径；本模块未假定已验证某组
Linux shared-library pins，也未运行 Linux 二进制。独立 SEG 服务只需调整部署/transport 边界，
无需重新实现 SEG 算法。
