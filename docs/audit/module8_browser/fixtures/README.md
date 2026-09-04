# Module 8 浏览器测试材料

**所有 FuzDrop 数据均为 synthetic test-only：不是官方预测、官方服务响应或生物学证据。** 本目录仅用于真实本地导入流程、序列坐标、着色与跨视图交互验收，不用于预测准确性、实验验证或校准结论。

`human_positive_line_1.fasta` 是真实 LRECA Human 基线中的 248 aa 序列，用作本轮真实 LRECA / SEG 浏览器分析输入。已核对它与固定上游 Human 正样本测试文件第一行一致；第 243 位为 **R**。FASTA 本身不包含预测值、区域或实验结论。

| 文件 | 字节数 | 用途与边界 |
| --- | ---: | --- |
| [human_positive_line_1.fasta](human_positive_line_1.fasta) | 272 | 真实 LRECA / SEG 浏览器输入；未替换或合成其序列。 |
| [synthetic_fuzdrop_import_248aa.json](synthetic_fuzdrop_import_248aa.json) | 5175 | 合成导入请求：同一真实序列、人工 pLLPS 0.68、248 行人工 pDP / Sbind 与 3 个人工区域。最终 D 验收指定使用此版本，两个 TSV 均保留末尾换行。 |
| [synthetic_fuzdrop_scores_248aa.tsv](synthetic_fuzdrop_scores_248aa.tsv) | 3639 | 上述请求中的同一份合成逐残基 TSV；用于上传、pDP 着色、数值与位置对应验收。 |
| [synthetic_fuzdrop_regions_248aa.tsv](synthetic_fuzdrop_regions_248aa.tsv) | 104 | 上述请求中的 3 个人工区域；用于原样显示、重叠区域与选择联动验收，不是从 pDP 推断的科学区域。 |
| [synthetic_fuzdrop_global_only_248aa.json](synthetic_fuzdrop_global_only_248aa.json) | 383 | 仅提供人工 pLLPS 0.68，省略两个 TSV 字段；用于验证缺少残基和区域数据时禁用对应着色，不从全局分数补造数据。 |
| [synthetic_fuzdrop_browser_import_248aa.json](synthetic_fuzdrop_browser_import_248aa.json) | 5173 | **初步 D UI 输入，非最终验收输入**：人工 pLLPS 0.68，scores TSV 去掉最后一个换行后为 3638 字符，regions TSV 保留末尾换行。 |
| [synthetic_fuzdrop_global_only_042_248aa.json](synthetic_fuzdrop_global_only_042_248aa.json) | 383 | 本轮 E 实际手填及最终验收指定的人工 pLLPS **0.42**，不提供任一 TSV；与保留的旧 0.68 global-only 夹具明确区分。 |

初步 D 的浏览器提交内容与旧完整 JSON 仅有 `scores_tsv` 末尾换行这一处差异：248 行残基数据及数值不变，`regions_tsv` 和 pLLPS 0.68 不变。**最终 D 改为原完整 TSV，scores 为 3639 字符且包含末尾换行**；去换行版本只保留用于说明初步记录。E 使用 0.42，不能将旧 0.68 夹具写作本轮 E 的实际输入。最终 D / E 在显示明显 “Synthetic test data” 横幅的测试 profile 下重新验收，实际完成情况由最终浏览器证据记录。两个新增 JSON 记录提交字段，以便复现；其文件格式不声称是原始 HTTP 传输字节抓包。

JSON 中的 `source_declaration: "official_fuzdrop_export"` 与 `coordinate_system: "one_based_inclusive"` 是既有本地导入契约要求的测试声明。它们不证明真实官方来源，也不是官方原生坐标的新证据。FuzDrop 的 pLLPS、pDP、Sbind 和区域均由测试者人工构造；Sbind 是绑定模式熵字段，不应称为概率。文件不包含伪造的导入结果 ID 或 LRECA / SEG 推理输出；实际本地导入端点负责签发导入 ID。使用这些材料不要求调用外部 FuzDrop 服务。

[fixture_manifest.json](fixture_manifest.json) 记录以上 7 个载荷文件的相对文件名、字节数、完整 SHA-256、用途及限制。哈希针对各文件原始字节，不调整换行、BOM 或格式；README 与 manifest 本身不纳入载荷清单，避免自引用哈希。原有 5 个载荷保持与既有 [Module 7 材料](../../module7_browser/fixtures/README.md) 字节一致。旧完整 JSON 内嵌 TSV 与独立 TSV 内容一致；初步 D 版本仅保留上述已说明的换行差异。4 个 JSON 的序列均与 FASTA 一致。

本次只记录材料身份和用途，并新增 D、E 的提交字段复现文件，没有重新生成预测、修改原有 5 个载荷、发起外部请求或运行模型。真实浏览器验收结果由本轮其他证据文件单独记录；清单存在本身不代表相应交互已经通过。
