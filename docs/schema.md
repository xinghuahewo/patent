# Schema 汇总

本文是当前核心输出字段契约入口。细分 schema 仍然有效，位于 `docs/schemas/`。

本文用于快速总览字段；实现或修改具体源域时，必须同时查看对应细分 schema 中的语义边界、禁止解释和校验规则。

所有核心输出记录应尽量包含：

- `record_id`
- `run_id`
- `schema_version`
- `parser_version`
- `asn`
- `analysis_month` 或 stage1 的 `month`
- `raw_evidence_path`
- `raw_evidence_sha256`

## registry: `asn_registry_baseline_monthly`

输出路径：

- `data/staging/registry/asn_registry_baseline_monthly.csv`

字段：

```text
record_id, run_id, schema_version, parser_version, asn, analysis_month,
allocated_country, registered_country, registered_rir, org_name, parent_org,
allocation_date, allocation_status, admin_conflict_flag,
multi_country_registry_flag, cloud_or_cdn_flag, crossborder_group_flag,
hosting_or_lease_hint_flag, evidence_summary, raw_evidence_path,
raw_evidence_sha256, source_snapshot_time, fetch_time
```

语义约束：

- `allocated_country` 来自 delegated 分配国家。
- `registered_country` 来自 RDAP/registry 注册信息。
- `admin_conflict_flag` 只表示行政冲突线索，不表示最终异常。
- 云厂商、CDN、骨干网、跨国集团相关字段只用于解释性降权。

## links: `asn_link_summary_monthly`

输出路径：

- `data/staging/links/asn_link_summary_monthly.csv`

字段：

```text
record_id, run_id, schema_version, parser_version, asn, analysis_month,
window_start, window_end, observed_neighbor_count, provider_count,
customer_count, peer_count, unknown_count, new_neighbor_count,
lost_neighbor_count, neighbor_churn_rate, provider_switch_count,
link_instability_flag, border_as_flag, topology_anomaly_flag,
evidence_summary, raw_evidence_path, raw_evidence_sha256
```

语义约束：

- links 只描述连接结构，不能直接推断运营国家。
- `border_as_flag` 主要用于避免误判边界型 ASN。
- `topology_anomaly_flag` 是异常性线索，不是最终结论。

## prefixes: `asn_prefix_inventory_monthly`

输出路径：

- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`

字段：

```text
record_id, run_id, schema_version, parser_version, asn, analysis_month,
filter_country, as_name, as_country, global_rank, source_collector,
source_snapshot_time, prefix_count_v4, prefix_count_v6, total_prefix_count,
prefixes_v4_json, prefixes_v6_json, fetch_time, raw_evidence_path,
raw_evidence_sha256
```

语义约束：

- 当前 prefixes 只给出 ASN 起源前缀集合缓存。
- 本阶段不输出 `dominant_prefix_country`。
- 本阶段不输出 `geo_conflict_flag`。
- BGP AS_PATH 解析只接受合法单 ASN token，不得把 AS_SET 拼成异常大整数。

## prefix_geo: `asn_prefix_geo_monthly`

输出路径：

- `data/staging/prefixes/asn_prefix_geo_monthly.csv`

字段：

```text
record_id, run_id, schema_version, parser_version, asn, analysis_month,
baseline_country, prefix_count, mapped_prefix_count, unmapped_prefix_count,
dominant_prefix_country, dominant_prefix_country_ratio,
foreign_prefix_count, foreign_prefix_coverage_ratio, geo_conflict_flag,
raw_evidence_path, raw_evidence_sha256, geo_evidence_path,
geo_evidence_sha256, evidence_summary
```

语义约束：

- `prefix_geo` 是单源静态地理画像，只使用起源 prefix 和 delegated prefix-country 证据。
- 当前试点默认范围是 `IR / 2026-03`，输入来自 `data/staging/prefixes/asn_prefix_inventory_monthly.csv`。
- delegated 证据默认使用 `data/raw/registry/delegated_monthly_go/nro_delegated_stats_2026-03_20260331.txt`。
- 每个起源 prefix 使用最长覆盖 delegated block 决定国家；未匹配记为 `ZZ`。
- `dominant_prefix_country` 仅表示 prefix 静态归属最多的国家，不等于运营国家。
- `foreign_prefix_coverage_ratio` 按 prefix count 计算，不按 IPv6 地址空间权重计算。
- `geo_conflict_flag` 只在 dominant country 是真实国家、不同于 `baseline_country`，且外国外前缀占比达到阈值时为 true。
- `geo_conflict_flag` 是人工复核线索，不是最终异常裁定。

## stage1: `asn_suspect_stage1`

输出路径：

- `data/curated/stage1/asn_suspect_stage1.csv`

字段：

```text
record_id, run_id, schema_version, parser_version, asn, month,
allocated_country, registered_country, dominant_prefix_country,
admin_conflict_flag, geo_conflict_flag, topology_anomaly_flag,
border_as_flag, suspect_level, review_required_flag, evidence_summary,
raw_evidence_path, raw_evidence_sha256
```

语义约束：

- stage1 输出候选集，不是最终裁定。
- `suspect_level` 只能用于复核优先级。
- `geo_conflict_flag` 来自 `prefix_geo` 静态画像，只能作为候选集线索。
- 边界型 ASN 不应自动判为异常。

## case material: `reports/case_material/IR_2026-03/`

输出路径：

- `reports/case_material/IR_2026-03/summary.md`
- `reports/case_material/IR_2026-03/review_queue.csv`
- `reports/case_material/IR_2026-03/manifest.json`
- `reports/case_material/IR_2026-03/cases/AS{asn}.md`

字段：

```text
asn, month, review_priority, evidence_status, trigger_reason,
weakness_flags, raw_evidence_path, raw_evidence_sha256
```

语义约束：

- 当前只覆盖 `IR / 2026-03` 且 `geo_conflict_flag=true` 的 stage1 候选。
- `review_priority` 只表示人工复核队列优先级。
- `evidence_status` 只描述证据完整度，不表示真假判断。
- `weakness_flags` 记录缺失证据、unmapped 多、prefix 数量少或解释性降权线索。
- case material 不输出最终运营国字段。
- case material 不输出异常裁定字段。

## registry history

该部分是独立旁线，不进入日常 stage1 主流程。

### `asn_delegated_monthly`

输出路径：

- `data/staging/registry/asn_delegated_monthly.csv`

必备字段：

```text
record_id, run_id, schema_version, parser_version, asn, analysis_month,
rir, country, region, status, allocation_date, raw_evidence_path,
raw_evidence_sha256, raw_line
```

### `asn_region_state_segments`

输出路径：

- `data/curated/registry/asn_region_state_segments.csv`

必备字段：

```text
record_id, run_id, schema_version, parser_version, asn, segment_index,
start_month, end_month, duration_months, rir, country, region, status,
start_raw_evidence_path, start_raw_evidence_sha256,
end_raw_evidence_path, end_raw_evidence_sha256
```

### `asn_region_trajectories`

输出路径：

- `data/curated/registry/asn_region_trajectories.csv`

必备字段：

```text
record_id, run_id, schema_version, parser_version, asn, first_seen_month,
last_seen_month, observed_months, missing_months, segment_count,
rir_sequence, country_sequence, region_sequence, status_sequence,
changed_rir_count, changed_country_count, changed_region_count,
max_stable_months, trajectory_type, first_raw_evidence_path,
first_raw_evidence_sha256, last_raw_evidence_path, last_raw_evidence_sha256
```

### `asn_region_change_events`

输出路径：

- `data/curated/registry/asn_region_change_events.csv`

字段：

```text
record_id, run_id, schema_version, parser_version, asn, from_month,
to_month, from_rir, to_rir, from_country, to_country, from_region,
to_region, from_status, to_status, change_type, from_duration_months,
to_duration_months, from_raw_evidence_path, from_raw_evidence_sha256,
to_raw_evidence_path, to_raw_evidence_sha256
```

语义约束：

- 只表示 delegated 行政分配状态变化。
- 排除或单独解释 `ZZ`、`available`、`reserved`、`gap` 等状态噪声。
- 不代表运营地异常裁定。
