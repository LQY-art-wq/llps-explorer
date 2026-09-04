# NCBI BLAST+ 2.17.0 SEG 源码与格式证据

本审计核对了官方固定发行源码 ZIP，而非用持续更新的 Doxygen 网页代替发行源码。
源码身份、成员 SHA256 与逐项行号见 [source_manifest.json](source_manifest.json)。
配套的 8 份 Windows 标准二进制输出见 [真实运行 fixture 索引](../../../backend/tests/fixtures/seg/cases.json)。

## 固定版本与许可证

- 官方源码：[ncbi-blast-2.17.0+-src.zip](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-src.zip)。
- 大小：34,012,171 bytes。
- [官方 MD5 文件](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-src.zip.md5) 与完整下载一致：`2f22ff35cffa5a29a27a1424d4edb1e9`。
- 本地计算 SHA256：`cdcd9e36f2b581eff9bd8364875a466289253b716d3a8014838a8305a9d11880`。
- ZIP 成员 `c++/scripts/projects/blast/LICENSE` 及相关源文件顶部均声明 NCBI PUBLIC DOMAIN / United States Government Work，允许公众使用与复制，附免责及引用作者说明。发行包附带的其他 notices 仍应随安装保留。
- 分发名称为 `2.17.0+`；实际 `-version` 的 Package 为 `blast 2.17.0`，application 为 `segmasker: 1.0.0`。`segmasker.cpp:70–73` 同样设置内部 application version 1.0.0，不能把两种版本混用。

以下成员路径均相对于 ZIP 的 `ncbi-blast-2.17.0+-src/c++/`，行号为原始成员中的一基行号。

## 默认参数与标准输入输出

`src/algo/blast/core/blast_seg.c:45–47` 明确默认 `window=12`、`locut=2.2`、`hicut=2.5`。
`SegParametersNewAa`（2225–2238）还设置 `period=1`、`hilenmin=0`、`overlaps=FALSE`、
`maxtrim=50`、`maxbogus=2`。`src/algo/segmask/segmask.cpp:41–51` 只覆盖 CLI 暴露的三个参数。
核心会修正某些非法参数（`blast_seg.c:2247–2266`）；本项目在调用前拒绝非法配置，避免记录值与实际值不同。

`src/app/segmasker/segmasker.cpp:111–116` 将 `-in`、`-out` 默认设为 `-`。
其 159–163 行读取蛋白 FASTA 或蛋白 BLAST 数据库；本项目仅使用 FASTA。
`src/objtools/seqmasks_io/mask_cmdline_args.cpp:40–50` 列出 `infmt=fasta`、`outfmt=interval` 为首个默认格式。
本项目可复现调用为：

```text
segmasker -in - -out - -infmt fasta -outfmt interval -window 12 -locut 2.2 -hicut 2.5
```

序列通过 stdin 传入一个固定 `>query` FASTA 记录；原用户 header 在统一序列验证时移除。
`parse_seqids` 保持 false。上述命令不包含用户序列，不需要 shell 或永久临时 FASTA 文件。

## 原生坐标与单记录格式

`src/objtools/seqmasks_io/mask_writer.cpp:54–65` 写出 `>` 开头的记录标题；
`mask_writer_int.cpp:40–52` 在标题后逐行原样写出 `first - second`。
无 LCR 时仍写标题，不写区间；因此空 stdout 不是合法的“无 LCR”。

坐标链为：

1. `blast_seg.c:2070–2073` 形成首尾位置，区间长度使用 `rightend-leftend+1`。
2. `blast_seg.c:2170–2171` 将内部 begin/end 原样写入 BLAST left/right。
3. `segmask.cpp:75–87` 调用 offset 为 0，并将 left/right 原样放入输出数组。
4. `mask_writer_int.cpp:52` 直接打印这两个数值。

固定 Windows 二进制进一步确认：100 aa 全低复杂度输出 `0 - 99`；
N-terminal 用例为 `0 - 39`；C-terminal 用例为 `100 - 139`，序列长 140。
原始 CRLF bytes 与 SHA256 均保存在 fixture 中。
由此确认 native 坐标为 **0-based inclusive**；API 将两端各加一，仍为闭区间，
`length=end-start+1`。Linux LF 与 Windows CRLF 仅作为换行差异处理。

## 不合并原生区域；覆盖率单独求并集

固定发行源码 `blast_seg.c:2236` 的 `overlaps=FALSE`，而 2320–2322 行只有在该选项为 true 时
才调用 `s_MergeSegs`。`CSegMasker` 没有修改这个选项，interval writer 也没有合并或排序逻辑。
因此本项目保留原始区间顺序、相邻区间、重叠与重复记录，不用额外合并改变区域定义。

`region_count` 是保留区间数；`longest_region` 是这些区间长度的最大值，无区间时为 0。
`coverage` 独立计算所有区间覆盖残基的并集大小，再除以序列长度，避免重叠或重复导致重复计数。
这只是覆盖率计算，不改变返回的原生区域列表。SEG 仅提供 LCR 注释，没有 LLPS 概率、P/N 或 ensemble 分数。

## Linux / Docker 安装核验范围

[官方 2.17.0 发行目录](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/) 提供 Linux x86-64 和 AArch64 包。
当前安装 helper 支持 Windows x64 与 Linux x64；Linux x64 包的
[官方 MD5](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-x64-linux.tar.gz.md5)
为 `bdec166721de3b55f90a3badc83538e8`。

Docker 构建阶段可使用本项目安装 helper 的 `--platform linux-x64 --destination /opt/seg`，
按固定 manifest 下载和校验官方 archive，保留库文件与 notices，再通过 `SEG_EXECUTABLE_PATH`
指定安装后的 `bin/segmasker`。调用层使用 Python 子进程与 stdin，不依赖 PowerShell 或个人目录。
准确安装命令与部署检查见 [SEG 运行环境](../../seg_runtime.md)。

本审计没有下载或执行 Linux 二进制，也没有测定该包的 ELF 动态库依赖。
Linux 包下载完整性、目标镜像依赖、`-version` 与真实 fixture 一致性应在目标镜像构建验证时检查；
本轮已经实际验证的平台是 Windows x64。
