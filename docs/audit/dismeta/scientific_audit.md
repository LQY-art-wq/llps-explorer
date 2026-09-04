# DisMeta 科学语义审计

审计日期：2026-09-03。结论为 **MODE F / UNKNOWN**；项目决策为 **INTEGRATION_BLOCKED**。
现有证据足以确认方法身份和历史用途，尚不足以建立真实自动计算或手工导入契约。
本次没有提交蛋白、发送邮件、操作验证码，也没有生成预测结果。

## 方法身份与历史版本

DisMeta 是 Huang、Acton、Montelione 的 disorder meta-server，用于构建设计。
2014 方法章节（首次在线发表于 2013-10-12）与当前官网描述均不能支持 LLPS 概率、
P/N 或 ensemble 权重。[原始章节](https://link.springer.com/protocol/10.1007/978-1-62703-691-7_1)；
[官方软件页](https://montelionelab.chem.rpi.edu/index.php/our-software-2/)。

原作者稿 Materials §2.1 列出历史 8 个 disorder predictors；当前可检索官方表单只列 4 个，
并声明使用默认参数。具体名单见 [来源证据 JSON](scientific_source_evidence.json)。
历史 Fig. 1 所谓本地安装指 **官方服务器内部**，不等于存在可再部署的 DisMeta 发行包。
不能把历史组成或组件自己的可下载性当作当前 DisMeta 实现。[原作者稿](https://pmc.ncbi.nlm.nih.gov/articles/PMC4115584/)；
[官方表单](https://montelionelab.chem.rpi.edu/dismeta/)。

## 原生结果与不能补出的定义

| 项目 | 已确认 | 仍未确认 / 实现边界 |
| --- | --- | --- |
| disorder consensus | 原文采用保守的共识识别策略；官网说明按残基绘图 | 没有确认当前数值公式、分母、缺失组件处理、二值阈值或等号规则 |
| IDR regions | 论文报告存在 disorder consensus 区域 | 当前原生区域列表、最短长度、邻接/重叠合并规则未知；不得自行阈值化或合并 |
| residue scores | 官方软件页确认逐残基 consensus 图 | 未取得可逐位校验的原生数值文件；数值范围、归一化和概率含义未知 |
| 坐标 | 原文 SyR11 的全长 155 与编号 1–155 一致 | 这只支持论文叙述中的 1-based 闭区间解释，不能证明未知机器导出的原点和端点定义 |
| 输出下载 | 原论文包含真实历史报告图 | 未取得当前官方 TSV/CSV/JSON/文本 export 或其字段契约；图像不是 parser fixture |
| 当前参数 | 表单说明各工具用默认设置 | 没有固定的组件版本、DisMeta 版本、运行参数集合或可复现本地环境 |

上述论文证据锚点为 Introduction、Materials §2.1、Methods §3.1–3.5 和 Figs. 1–7；
逐残基绘图描述来自 [官方软件页](https://montelionelab.chem.rpi.edu/index.php/our-software-2/)。
未发现阈值定义并不证明作者从未使用阈值，只表示不能据本次已读材料安全实现。

## 已公开实例的边界

论文 Fig. 2–7 有 ER541、SyR11、ER553、WR33、HR4626、PgR37 的历史报告。
这些可证明历史科学应用，不能证明当前服务完成了这些作业。
例如 Methods §3.2 / Fig. 3 的 SyR11，信号肽 1–29 被 disorder consensus 判为 ordered，
而约 25–49 为 disordered。构建设计综合多个注释后删除的片段，
不能整体改称原生 DisMeta IDR。[原作者稿](https://pmc.ncbi.nlm.nih.gov/articles/PMC4115584/)。

因此，本项目不能把 SignalP、TMHMM、SEG 区域或论文中的近似边界补入 native IDR；
也不能用其他 predictor 冒充 DisMeta。当前没有可以标为真实 DisMeta
运行输出的 fixture，手工导入同样缺少可验证的格式基础。

## 本地实现、访问与证据质量

成功读取的官方材料未提供 DisMeta CLI、公开源码发行包、版本化模型/数据清单、
Linux/Docker 安装契约或面向第三方的程序化提交支持。
论文 Introduction 提到的自动构建设计软件属于当时未发表工作，不能当作 DisMeta 安装说明；
Conclusion 的在线开放描述也不等于自动化授权。
服务访问与使用范围另见本轮主审计；网络超时不能单独证明全球服务已关闭。
[官方软件页](https://montelionelab.chem.rpi.edu/index.php/our-software-2/)；
[原作者稿](https://pmc.ncbi.nlm.nih.gov/articles/PMC4115584/)。

本轮原作者稿正文来自检索工具返回的 PMC **索引全文**，包括方法及图注。
直接打开 PMC/PubMed 时得到浏览器验证页面，未继续验证；
作者机构索引的一次直接 HTTPS GET 在 TLS 握手阶段超时。
Springer 仅取得公开摘要/书目信息。本报告没有声称下载了原始 PDF、
当前官方结果或原始 HTML。公开来源 JSON 区分这些访问方式；
私有保存的是工具返回的解析/索引文本，其哈希不是官方响应字节哈希。

后续开放接入前，至少需要一份明确可使用的官方接入说明，以及包含序列身份、
原生 region/score 数据、坐标及 consensus 规则的真实结果样本。
在此之前，自动分析和导入均保持不可用；规范化 DTO 的合同测试不代表真实 DisMeta 推断通过。
