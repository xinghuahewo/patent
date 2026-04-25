# schema_registry_region_changes

## 1. 目的

本文件定义 `registry delegated` 五年连续变化分析的输出合同。

该分析只使用本地 NRO delegated stats 月末快照，目标是生成 ASN 在固定窗口内的行政分配状态、连续区间、完整轨迹、变化事件和人工复核候选。

自动结果只用于复核候选，不代表最终异常裁定，也不推断运营国家。

## 2. 输入

原始输入目录：

- `data/raw/registry/delegated_monthly_go/`

固定窗口：

- `2021-04` 到 `2026-03`

要求：

- 60 个 `nro_delegated_stats_*.txt`
- `index.csv` 中的 `raw_evidence_sha256` 与本地文件一致
- 每月文件包含五大 RIR：`afrinic/apnic/arin/lacnic/ripencc`

`iana` 行保留在 raw 文件中，但包含巨大 `available/reserved` ASN 区间，因此不展开到 ASN 月度状态，也不参与跨 RIR 判断。

## 3. 输出

raw 验收报告：

- `reports/asn_region_changes/raw_inventory_check.csv`

staging 单源月度状态：

- `data/staging/registry/asn_delegated_monthly.csv`
- `data/staging/registry/asn_delegated_monthly.parquet`

curated 连续区间、轨迹和事件：

- `data/curated/registry/asn_region_state_segments.csv`
- `data/curated/registry/asn_region_state_segments.parquet`
- `data/curated/registry/asn_region_trajectories.csv`
- `data/curated/registry/asn_region_trajectories.parquet`
- `data/curated/registry/asn_region_change_events.csv`
- `data/curated/registry/asn_region_change_events.parquet`

报告与复核清单：

- `reports/asn_region_changes/summary.md`
- `reports/asn_region_changes/top_changed_asns.csv`
- `reports/asn_region_changes/country_transition_matrix.csv`
- `reports/asn_region_changes/rir_transition_matrix.csv`
- `reports/asn_region_changes/region_transition_matrix.csv`
- `reports/asn_region_changes/high_priority_review_candidates.csv`

## 4. 月度状态表

表名：`asn_delegated_monthly`

字段：

| 字段名 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| record_id | string | 是 | `delegated_{asn}_{analysis_month}` |
| run_id | string | 是 | 运行批次 |
| schema_version | string | 是 | schema 版本 |
| parser_version | string | 是 | 解析器版本 |
| asn | int | 是 | 展开后的单 ASN |
| analysis_month | string | 是 | `YYYY-MM` |
| rir | string | 是 | 五大 RIR 之一 |
| country | string | 是 | delegated 国家码 |
| region | string | 是 | 固定国家到大区映射，未知为 `unknown` |
| status | string | 是 | delegated 状态 |
| allocation_date | string | 是 | delegated 日期字段 |
| raw_evidence_path | string | 是 | 月度 raw 文件 |
| raw_evidence_sha256 | string | 是 | 月度 raw 文件 SHA256 |
| raw_line | string | 是 | 原始 delegated 行 |

## 5. 连续状态区间表

表名：`asn_region_state_segments`

相同状态定义为：

- `rir + country + region + status` 全部一致

缺月单独输出 `status=gap` 区间，并切断前后状态。

## 6. 完整轨迹表

表名：`asn_region_trajectories`

`trajectory_type` 只能为：

- `stable`
- `single_country_move`
- `multi_country_move`
- `cross_region_move`
- `cross_rir_move`
- `oscillation`
- `temporary_revert`
- `appeared_late`
- `disappeared_early`
- `data_gap`

序列字段保留完整顺序路径，例如：

- `US -> NL -> DE`

## 7. 变化事件表

表名：`asn_region_change_events`

每条事件来自两个连续区间的边界，或来自窗口边界上的出现/消失。

`change_type` 支持组合：

- `rir_change`
- `country_change`
- `region_change`
- `status_change`
- `appeared`
- `disappeared`
- `gap_start`
- `gap_end`

## 8. 校验

运行：

```bash
python3 scripts/validate_outputs.py --stage delegated_monthly
python3 scripts/validate_outputs.py --stage region_segments
python3 scripts/validate_outputs.py --stage region_trajectories
python3 scripts/validate_outputs.py --stage region_change_events
python3 scripts/validate_outputs.py --stage all
```

校验器会检查 schema、月份格式、允许值、区间时长、事件类型、Parquet 是否存在，以及 raw evidence SHA256 是否匹配。
