# Prefixes Schema

## 1. 目标

`prefixes` 阶段只解决一个问题：

- 从本机 `bview` 月末快照中，按月预计算目标国家 ASN 子集的前缀集合缓存

本阶段不做：

- prefix geo
- 运营国家推断
- stage1 融合

---

## 2. 数据来源

### 2.1 本机 bview

- 根目录：`/home/bgpdata/data/ripe/rrc25`
- 月目录：`YYYY.MM`
- 快照选择：当月最后一个 `bview.*.gz`

### 2.2 ASN 子集来源

- 文件：`/home/experiment/info/as_entity.csv`
- 默认国家过滤字段：`as_country`
- 当前试点国家：`IR`

---

## 3. Raw

### 3.1 单 ASN raw evidence

目录：

- `data/raw/prefixes/extracted/`

每条记录对应：

- `(asn, analysis_month, run_id)`

核心字段：

- `record_id`
- `run_id`
- `schema_version`
- `parser_version`
- `asn`
- `analysis_month`
- `filter_country`
- `fetch_time`
- `source_snapshot_time`
- `source_collector`
- `sources.bview.raw_response_path`
- `sources.bview.raw_response_sha256`
- `sources.as_entity.raw_response_path`
- `sources.as_entity.raw_response_sha256`
- `normalized.prefixes_v4`
- `normalized.prefixes_v6`
- `normalized.prefix_count_v4`
- `normalized.prefix_count_v6`
- `normalized.total_prefix_count`

### 3.2 月批次 manifest

目录：

- `data/raw/prefixes/manifest/`

用途：

- 记录本月扫描使用的 bview 快照
- 记录目标国家与 ASN 数量
- 记录扫描统计与写出的 raw 文件列表

---

## 4. Staging

输出：

- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`
- `data/staging/prefixes/asn_prefix_inventory_monthly.parquet`

每条记录仍对应：

- `(asn, analysis_month, run_id)`

字段：

- `record_id`
- `run_id`
- `schema_version`
- `parser_version`
- `asn`
- `analysis_month`
- `filter_country`
- `as_name`
- `as_country`
- `global_rank`
- `source_collector`
- `source_snapshot_time`
- `prefix_count_v4`
- `prefix_count_v6`
- `total_prefix_count`
- `prefixes_v4_json`
- `prefixes_v6_json`
- `fetch_time`
- `raw_evidence_path`
- `raw_evidence_sha256`

---

## 5. 约束

1. 只接受合法单 ASN origin token
2. 遇到 AS_SET / 聚合 token 不强行解析
3. staging 只读取 raw evidence，不重新跑 `bgpdump`
4. `prefixes` 阶段只给出“前缀集合缓存”，不输出 `dominant_prefix_country`
5. 伊朗 ASN 只作为当前试点子集，不代表最终唯一目标国家方案
