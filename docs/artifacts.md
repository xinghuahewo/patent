# 产物目录

本文记录重要文件是怎么来的、说明什么、不能说明什么。忘记某个文件用途时，优先看这里。

每个长期保留的核心产物都应该同时具备：

- 本文中的人读说明。
- 同目录的 `*.manifest.json`，记录生产脚本、输入、输出、hash、行数和语义边界。

硬性规则：

- `data/staging` 下新增或更新核心数据产物时，必须登记到本文。
- `data/curated` 下新增或更新核心数据产物时，必须登记到本文。
- 能由脚本生成的 staging/curated 产物，应尽量在同目录写入 `*.manifest.json`。
- 临时调试文件不应长期留在 `data/staging` 或 `data/curated`；确需保留时也要登记其用途和清理条件。

## 阅读顺序

1. 先看本文，确认文件层级和语义边界。
2. 再看同目录 `*.manifest.json`，确认本次运行的具体输入、命令和 hash。
3. 最后再查 `docs/schema.md`，确认字段级契约。

## `data/staging/prefixes/asn_prefix_inventory_monthly.csv`

层级：`staging`

分析单位：`(asn, analysis_month)`

生产脚本：

```bash
python3 scripts/stage_prefixes.py --month 2026-03 --country IR
```

同名导出：

- `data/staging/prefixes/asn_prefix_inventory_monthly.parquet`

上游输入：

- `data/raw/prefixes/extracted/*.json`
- 本机 `rrc25` 月末 bview 解析结果

输出含义：

- 记录目标国家 ASN 在某个月份起源的 prefix 集合。
- 这是 prefix 缓存和后续 `prefix_geo` 的输入 substrate。

关键字段：

- `prefix_count_v4`
- `prefix_count_v6`
- `total_prefix_count`
- `prefixes_v4_json`
- `prefixes_v6_json`
- `raw_evidence_path`
- `raw_evidence_sha256`

不能说明：

- 不能说明 prefix delegated 国家。
- 不能说明运营国家。
- 不能直接构成异常候选。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage prefixes
```

## `data/staging/prefixes/asn_prefix_geo_monthly.csv`

层级：`staging`

分析单位：`(asn, analysis_month)`

生产脚本：

```bash
python3 scripts/stage_prefix_geo.py --country IR --month 2026-03
```

同名导出：

- `data/staging/prefixes/asn_prefix_geo_monthly.parquet`

上游输入：

- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`
- `data/raw/registry/delegated_monthly_go/nro_delegated_stats_2026-03_20260331.txt`

配套 manifest：

- `data/staging/prefixes/asn_prefix_geo_monthly.manifest.json`

输出含义：

- 将 ASN 起源 prefix 映射到本地 NRO delegated 快照中的 prefix-country。
- 输出每个 ASN 的静态 prefix 国家画像。

关键字段：

- `baseline_country`：来自 prefix inventory 的 `as_country`，当前试点为 `IR`。
- `dominant_prefix_country`：prefix 静态归属数量最多的国家。
- `foreign_prefix_coverage_ratio`：非 baseline country prefix 数量占比。
- `geo_conflict_flag`：静态 prefix 国家冲突线索。
- `geo_evidence_path` / `geo_evidence_sha256`：delegated 快照证据。

不能说明：

- `dominant_prefix_country` 不是运营国家。
- `geo_conflict_flag` 不是最终异常裁定。
- 未匹配 prefix 记为 `ZZ`，不触发冲突。
- 当前只是 `IR / 2026-03` 单月试点。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage prefix_geo
```

当前试点结果：

- 行数：`822`
- `geo_conflict_flag=true`：`35`

## `data/curated/stage1/asn_suspect_stage1.csv`

层级：`curated`

分析单位：`(asn, month)`

生产脚本：

```bash
python3 scripts/build_stage1_suspects.py
```

同名导出：

- `data/curated/stage1/asn_suspect_stage1.parquet`

上游输入：

- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/staging/links/asn_link_summary_monthly.csv`
- `data/staging/prefixes/asn_prefix_geo_monthly.csv`

配套 manifest：

- `data/curated/stage1/asn_suspect_stage1.manifest.json`
- `data/curated/stage1/manifest/*.json`

输出含义：

- 第一阶段候选集。
- 只把 registry、links、prefix_geo 的线索合并到统一 `(asn, month)` 表。
- 用于人工复核排序和后续 case material 构建。

关键字段：

- `allocated_country`
- `registered_country`
- `dominant_prefix_country`
- `admin_conflict_flag`
- `geo_conflict_flag`
- `topology_anomaly_flag`
- `border_as_flag`
- `suspect_level`
- `review_required_flag`
- `raw_evidence_path`
- `raw_evidence_sha256`

不能说明：

- 不是最终异常名单。
- `suspect_level` 不是最终风险等级。
- 单一 `geo_conflict_flag` 不能替代人工复核。
- 边界型 ASN、云厂商、CDN、骨干网、跨国集团仍需要解释性降权。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage stage1
```

当前试点结果：

- 行数：`827`
- 其中来自 `prefix_geo` 的 geo conflict 线索：`35`

## `reports/case_material/IR_2026-03/`

层级：`reports`

分析单位：`(asn, month)`

生产脚本：

```bash
python3 scripts/build_case_material.py --country IR --month 2026-03
```

核心文件：

- `reports/case_material/IR_2026-03/summary.md`
- `reports/case_material/IR_2026-03/review_queue.csv`
- `reports/case_material/IR_2026-03/manifest.json`
- `reports/case_material/IR_2026-03/cases/AS{asn}.md`

上游输入：

- `data/curated/stage1/asn_suspect_stage1.csv`
- `data/staging/prefixes/asn_prefix_geo_monthly.csv`
- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`

输出含义：

- 将 `IR / 2026-03` stage1 中 `geo_conflict_flag=true` 的候选整理成人工复核队列。
- 每个候选生成一张 Markdown case card，保留 raw evidence 路径和 hash。
- 用 `review_priority` 和 `evidence_status` 辅助人工排序。

关键字段：

- `asn`
- `month`
- `review_priority`
- `evidence_status`
- `trigger_reason`
- `weakness_flags`
- `raw_evidence_path`
- `raw_evidence_sha256`

不能说明：

- 不能说明最终运营国。
- 不能作为异常裁定。
- `dominant_prefix_country` 仍只是静态 prefix delegated 画像。
- 缺失数据只进入 `evidence_status` 或 `weakness_flags`，不得补假值。

当前试点结果：

- 队列行数：`35`
- case card 数：`35`
- high_review：`0`
- medium_review：`10`
- low_review：`25`

## `data/staging/registry/asn_registry_baseline_monthly.csv`

层级：`staging`

分析单位：`(asn, analysis_month)`

生产脚本：

```bash
python3 scripts/collect_registry.py
python3 scripts/stage_registry.py
```

同名导出：

- `data/staging/registry/asn_registry_baseline_monthly.parquet`

当前伊朗 `2026-03` prefix_geo 试点的离线 delegated 补齐命令：

```bash
python3 scripts/collect_registry_delegated_local.py --country IR --month 2026-03
python3 scripts/stage_registry.py --input data/input/asn_months_registry_IR_2026-03.csv
```

配套 manifest：

- `data/staging/registry/asn_registry_baseline_monthly.manifest.json`

输出含义：

- ASN delegated / RDAP / registry 行政信息的月度 baseline。
- 用于识别行政注册层面的冲突线索。

不能说明：

- 不能直接说明运营国家。
- 默认离线模式下可能只是 raw manifest，不代表真实在线采集完整成功。
- 本地 delegated 补齐只补 `allocated_country`，不会补 `registered_country`。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage registry
```

当前试点结果：

- 行数：`827`
- `allocated_country=IR`：`789`
- `allocated_country=ZZ`：`28`，对应 delegated 中 `available` 或 `reserved`
- `registered_country` 非空：`2`，仍只来自 RDAP/registry 证据

## `data/staging/links/asn_link_summary_monthly.csv`

层级：`staging`

分析单位：`(asn, analysis_month)`

生产脚本：

```bash
python3 scripts/collect_links.py
python3 scripts/stage_links.py
```

同名导出：

- `data/staging/links/asn_link_summary_monthly.parquet`

输出含义：

- ASN 连接结构和邻居变化摘要。
- 用于识别连接结构异常或边界型 ASN 线索。

不能说明：

- 不能直接用邻居国家推断运营国家。
- `topology_anomaly_flag` 是异常性线索，不是最终结论。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage links
```

## `data/staging/registry/asn_delegated_monthly.csv`

层级：`staging`

分析单位：`(asn, analysis_month)`

生产脚本：

```bash
python3 scripts/analyze_asn_region_changes.py
```

同名导出：

- `data/staging/registry/asn_delegated_monthly.parquet`

输出含义：

- 从 5 年 NRO delegated 月末快照展开得到 ASN 月度行政分配状态。
- 这是 registry history 旁线的基础表。

不能说明：

- 只表示 delegated 行政分配状态，不代表运营地异常。
- `ZZ`、`available`、`reserved`、`gap` 等状态需要单独解释。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage registry_history
```

## `data/curated/registry/asn_region_state_segments.csv`

层级：`curated`

分析单位：`(asn, segment_index)`

生产脚本：

```bash
python3 scripts/analyze_asn_region_changes.py
```

同名导出：

- `data/curated/registry/asn_region_state_segments.parquet`

输出含义：

- 将连续月份中相同 delegated 行政状态压缩成区间。
- 用于查看 ASN 在五年窗口内的稳定状态段。

不能说明：

- 只表示 delegated 行政分配状态连续性，不代表运营地异常。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage registry_history
```

## `data/curated/registry/asn_region_trajectories.csv`

层级：`curated`

分析单位：`asn`

生产脚本：

```bash
python3 scripts/analyze_asn_region_changes.py
```

同名导出：

- `data/curated/registry/asn_region_trajectories.parquet`

输出含义：

- 汇总每个 ASN 在五年窗口内的完整 delegated 国家、RIR、大区、状态轨迹。
- 用于识别需要进一步人工查看的行政分配变化模式。

不能说明：

- 轨迹变化不等于注册地与运营地不一致。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage registry_history
```

## `data/curated/registry/asn_region_change_events.csv`

层级：`curated`

分析单位：`asn` 的相邻状态变化事件

生产脚本：

```bash
python3 scripts/analyze_asn_region_changes.py
```

同名导出：

- `data/curated/registry/asn_region_change_events.parquet`

输出含义：

- 记录 ASN delegated 行政分配状态在五年窗口内的变化事件。
- 作为 `reports/asn_region_changes/summary_clean.md` 的上游证据之一。

不能说明：

- 原始事件流包含 `ZZ`、`available`、`reserved`、`gap` 等噪声，需要清洗解释。
- 变化事件不是运营地异常裁定。

校验命令：

```bash
python3 scripts/validate_outputs.py --stage registry_history
```
