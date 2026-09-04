# Analysis export formats

Module 9 的下载由 FastAPI 从 persisted `AnalysisJob` 生成。前端只请求并保存服务端返回的 bytes，不重新计算 ensemble、KDE、coverage、ranking 或 regions。CSV 中逐位 region membership 只是对已保存的 1-based inclusive region boundaries 做包含关系映射。

## Endpoints and access control

| Format | Endpoint suffix | Media type | Filename suffix |
| --- | --- | --- | --- |
| Result JSON | `/export/json` | `application/json` | `_result.json` |
| Summary CSV | `/export/summary.csv` | `text/csv` | `_summary.csv` |
| Residues CSV | `/export/residues.csv` | `text/csv` | `_residues.csv` |
| Regions CSV | `/export/regions.csv` | `text/csv` | `_regions.csv` |
| FASTA | `/export/fasta` | `text/plain` | `.fasta` |

完整路径为 `GET /api/v1/analysis/{job_id}` 加上表中的 suffix。所有下载执行与 detail 相同的 owner check；过期、已删除或属于其他 session 的 job 返回 404。queued/running job 尚不是稳定快照，五种 endpoint 均返回 409 / `ANALYSIS_NOT_READY_FOR_EXPORT`；其他终态可按其实际保存内容导出。错误响应不包含 sequence。

数据库读取和 export byte construction 都由 FastAPI 在线程池执行，避免长 residue CSV 的同步构造阻塞 event loop。成功响应使用 `Content-Disposition: attachment`，并由同源 proxy 保留经过校验的 MIME type 和下载文件名。

所有文本使用 UTF-8。CSV 使用逗号分隔、标准 CSV quoting 和 LF 行结束；FASTA 也使用 LF，并以换行结束。

## Coordinate and missing-value contract

所有 `Position`、`Start` 和 `End` 均为 **1-based**。区域两端均包含在内：

```text
Length = End - Start + 1
```

空值的表示有意区分：

| 情况 | JSON | CSV / UI 语义 |
| --- | --- | --- |
| 数值或区域数据未提供 | `null` | CSV 空单元格；UI 显示 `N/A` 或具体状态 |
| 方法成功且确认没有区域 | `[]` | 每个 residue 的 membership 为 `false`；UI 可显示 No |
| DisMeta 被选择且正常保持 blocked | method status `unavailable` | `DisMeta_IDR_Status` 为 `Unavailable`，绝不写成 `false` 或 `0 regions` |
| DisMeta execution 因服务重启中断 | failed + `service_restart` / `ANALYSIS_INTERRUPTED` | `DisMeta_IDR_Status` 为 `Interrupted` |
| DisMeta 未选择 | 没有该 method execution | `DisMeta_IDR_Status` 为 `Not selected` |

FuzDrop 未导入、只导入 global 或没有某类 residue/region 字段时，对应 CSV 值为空；不能补成 0。空单元格表示没有可导出的值，并不等于 `false`。只有存在并且成功保存的原生 FuzDrop 字段才进入导出。
DisMeta residue status 来自 persisted method execution：除明确的 service-restart 中断外，其余状态将
下划线替换为空格并首字母大写，例如 `failed` → `Failed`。导出不根据空 region 数组推断 DisMeta 状态。

JSON 和 CSV 都不按 UI 的三位小数格式截断。JSON 直接序列化 persisted Pydantic payload；CSV 对 stored numeric value 使用运行时的完整 decimal string conversion。界面上的 `toFixed(3)` 只用于阅读，不改变下载数值。

## Result JSON

Result JSON 是紧凑的 UTF-8 JSON：

```json
{
  "export_metadata": {
    "format": "llps_analysis_result",
    "export_schema_version": "1.0",
    "coordinate_system": "one_based_inclusive"
  },
  "analysis": {
    "job_id": "analysis_example",
    "created_at": "2026-09-04T00:00:00Z",
    "updated_at": "2026-09-04T00:00:01Z",
    "completed_at": "2026-09-04T00:00:01Z",
    "expires_at": "2026-09-11T00:00:00Z",
    "status": "unavailable",
    "sequence": {
      "name": null,
      "length": 20,
      "sha256": "5a52efc76a4a4ceb3c992ff17426b3545634646080bb6acec132c47c278c9846"
    },
    "normalized_sequence": "ACDEFGHIKLMNPQRSTVWY",
    "selected_methods": ["dismeta"],
    "prediction_mode": "independent",
    "weights": null,
    "methods": {
      "dismeta": {
        "method": "dismeta",
        "status": "unavailable",
        "integration_mode": "integration_blocked",
        "runtime_ms": 0.0,
        "result": null,
        "error": null,
        "reason": "integration_contract_unverified",
        "warnings": ["The selected method's integration is blocked."]
      }
    },
    "ensemble": null,
    "warnings": [],
    "result_schema_version": "1.0"
  }
}
```

上例是一个只选择 blocked DisMeta 的最小 unavailable snapshot；成功方法的 `result` 由对应严格 native schema 填充。`analysis` 与 job detail 使用同一个 scientific representation，包含完整 canonical sequence、残基级数据、regions、method provenance、weights、ensemble 和 warnings。`export_schema_version` 描述导出 envelope；`result_schema_version` 描述 persisted analysis payload，两者当前均为 `1.0`。

公开 payload 不包含匿名 session token、owner hash、数据库 URL、服务器绝对路径、内部 service URL 或 secret。

## Summary CSV

恰好一行 analysis data，列顺序为：

```text
Sequence_Name
Length
LRECA_Score
LRECA_Label
FuzDrop_Score
FuzDrop_Label
Ensemble_Score
Ensemble_Label
LCR_Coverage
Analysis_Timestamp
Model_Provenance
Result_Schema_Version
```

`Analysis_Timestamp` 为 job `created_at` 的 ISO 8601 值。`Model_Provenance` 是一个放在 CSV 单元格中的紧凑 JSON object，只收集当前结果实际存在的来源信息：

- LRECA：model variant、repository commit、checkpoint filename/SHA256、threshold、KDE prominence。
- SEG：implementation、version、parameters。
- FuzDrop：source、coordinate verification。

缺少的方法或 score 留空。SEG coverage 是后端 persisted result，不在导出时重算。
为防止 spreadsheet formula injection，`Sequence_Name` 若以 `=`、`+`、`-` 或 `@` 开头，会在 summary
CSV 单元格前加一个单引号。该保护只改变电子表格打开时的文本表示，不改变数据库或 Result JSON
中的原 sequence name；其他 summary 字段是受控 label、number、timestamp 或序列化 provenance。

## Residues CSV

每个 canonical sequence residue 一行，顺序与序列完全一致：

```text
Position
AA
LRECA_Attribution
LRECA_KDE
LRECA_Critical_Region
LRECA_Primary_Region
FuzDrop_Propensity
FuzDrop_Region
SEG_LCR
DisMeta_IDR_Status
```

`Position` 从 1 到 sequence length；`AA` 是该位置的真实 uppercase amino-acid letter。Attribution、KDE 和 pDP 值直接来自 persisted residue arrays。三个 region membership 列及 primary 列只根据已保存 region boundaries 输出 lowercase `true` / `false`；对应 region set 未提供时留空。

生成 residues CSV 需要 persisted `normalized_sequence`。若 versioned record 缺少该字段，导出失败而不会伪造 AA。

## Regions CSV

仅为真实存在的 persisted regions 输出行，列顺序为：

```text
Method
Region_Type
Start
End
Length
Score
Primary
Source
```

| Method | Region type/source mapping | Score / Primary |
| --- | --- | --- |
| LRECA | `Primary KDE hotspot` 或 `Candidate KDE hotspot`; source `LRECA KDE` | 使用 stored region score；primary 为 `true`/`false` |
| FuzDrop | 使用 imported `official_type`; source `manual_import_of_official_result` | 当前留空 |
| SEG | type `LCR`; source `NCBI segmasker` | 当前留空 |

DisMeta 不生成 region row。不能把没有 DisMeta row 解释为“检测到 0 个 IDR”；其 unavailable 状态由 JSON method status 和 residues CSV 的 `DisMeta_IDR_Status` 表达。Region rows 保留各方法 persisted 顺序，不合并、去重或重排。

## FASTA

FASTA body 为：

```text
>safe_sequence_name|job_id
CANONICALSEQUENCE...
```

sequence 每 60 residues 换行。若没有 sequence name，header 使用 `analysis_{job_id}`；下载文件名仍使用安全的 `protein` fallback。FASTA 只包含 uppercase canonical sequence，不恢复原 FASTA header、原始空白或换行。

## Safe filenames

文件名结构为 `{safe_name}_{job_id}{suffix}`。后端对 sequence name 先做 Unicode NFKC normalization，将连续空白改为 `_`，只保留 Unicode alphanumeric、`.`、`_`、`-`，去掉两端标点，并限制 safe stem 为 64 characters。空结果使用 `protein`。路径分隔符、control characters 和 `..` 不能形成路径。

`Content-Disposition` 同时提供 ASCII fallback 和 RFC 5987 UTF-8 filename，因而中文等安全名称可保留。前端再次拒绝包含 `/`、`\\`、control characters、`.`、`..` 或超长值的响应文件名；失败时使用由 `job_id` 生成的 fallback。sequence name 也经过同一 sanitizer 后才进入 FASTA header，避免 header/path injection。

## Viewer image export

Feature Viewer 是原生 Canvas 2D 交互视图，当前没有稳定、已采用的 SVG export contract。Module 9 未重写 Module 7 viewer，也没有提供 PNG/SVG endpoint。正式最低导出集合是 JSON、summary/residues/regions CSV 和 FASTA；Canvas 图形导出可在后续模块单独设计，但不得改变现有 scientific data contract。

保存与 owner 规则见 [Analysis persistence](persistence.md)，到期和删除规则见 [Data retention](data_retention.md)。
