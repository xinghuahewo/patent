# 当前状态

状态：archived

归档原因：旧状态快照。当前状态请看 `docs/status.md`，长期路线请看 `docs/roadmap.md`，字段契约请看 `docs/schema.md` 和 `docs/schemas/`。

更新时间：2026-04-29

本文是当前工作区的状态入口。更详细的数据流见 `docs/project_flow.md`，字段契约见各 `docs/schema_*.md`。

## 已完成

- v1 最小闭环已经实现：`registry -> staging`、`links -> staging`、`stage1 suspects`、`validate_outputs.py`。
- registry 支持真实在线采集：delegated + RDAP。默认仍可走离线 raw manifest。
- links 支持真实在线采集：RIPEstat neighbours + CAIDA AS Rank。
- prefixes 已完成 `2026-03` 伊朗本机 `rrc25` bview 全量缓存，当前 staging 有 `822` 条 `(asn, month)` 前缀集合记录。
- 五年 delegated 行政分配变化分析已作为独立分析任务完成，清洗报告在 `reports/asn_region_changes/summary_clean.md`。

## 当前有效产物

日常 stage1 主线：

- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/staging/links/asn_link_summary_monthly.csv`
- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`
- `data/curated/stage1/asn_suspect_stage1.csv`

独立 registry history 分析：

- `data/staging/registry/asn_delegated_monthly.csv`
- `data/curated/registry/asn_region_state_segments.csv`
- `data/curated/registry/asn_region_trajectories.csv`
- `data/curated/registry/asn_region_change_events.csv`
- `reports/asn_region_changes/summary_clean.md`

这些文件默认视为本机运行产物，不进入 Git。

## 验证状态

最近一次轻量验证：

```bash
pytest -q
python3 scripts/validate_outputs.py --stage all
```

结果：

- `pytest -q`：`22 passed`
- `registry`：`ok`，`5` rows
- `links`：`ok`，`5` rows
- `prefixes`：`ok`，`822` rows
- `stage1`：`ok`，`5` rows

日常全量校验现在只覆盖 stage1 主线：

```bash
python3 scripts/validate_outputs.py --stage all
```

五年 delegated 历史大表需要显式校验：

```bash
python3 scripts/validate_outputs.py --stage registry_history
```

## 当前缺口

- prefixes 目前只有 ASN 起源前缀集合，没有 prefix 到国家的映射。
- `dominant_prefix_country`、`foreign_prefix_coverage_ratio`、`geo_conflict_flag` 尚未落成 staging 输出。
- `build_stage1_suspects.py` 还没有真正消费 prefix geo 信号。
- case card / 人工复核报告尚未系统化生成。
- infra / path 证据还没有进入正式流水线。

## 下一步

建议下一步只做一个源域：`prefix_geo`。

目标：

1. 明确 prefix 到国家的证据源。
2. 新增 `data/staging/prefixes/asn_prefix_geo_monthly.csv`。
3. 输出 `dominant_prefix_country`、覆盖比例和 `geo_conflict_flag`。
4. 更新 `scripts/validate_outputs.py` 校验 prefix geo。
5. 更新 `scripts/build_stage1_suspects.py`，将 geo 信号并入 stage1。
