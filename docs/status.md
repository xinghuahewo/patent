# 当前状态

更新时间：2026-04-29

本文是唯一当前状态入口。历史计划、旧状态快照和早期说明已归档到 `docs/archive/`。

长期技术路线入口是 `docs/roadmap.md`。本文只记录当前运行状态和下一小步。

最近工作记录和下次接手入口见 `docs/worklog.md`。

## 当前结论

- v1 最小闭环已经实现：registry、links、prefixes、prefix_geo、stage1、validator。
- 日常主线已经能快速校验：registry `827` rows、links `5` rows、prefixes `822` rows、prefix_geo `822` rows、stage1 `827` rows。
- prefixes 已完成 `2026-03` 伊朗本机 `rrc25` bview 全量缓存。
- prefix_geo 已完成 `2026-03` 伊朗单月试点，使用本地 NRO delegated 快照做静态 prefix-country 画像。
- registry 已用本地 NRO delegated ASN 快照补齐伊朗 `2026-03` 试点的 `allocated_country`；`registered_country` 仍只来自 RDAP/registry，不做推断填充。
- 五年 delegated 行政分配变化分析已经完成，作为独立 registry history 旁线保留。
- 当前主线仍然不要扩到 path、infra、case report；下一步应先复核 prefix_geo 的候选解释口径。
- stage1 之后的长期路线已经收口到 `docs/roadmap.md`，包括 case material、path、infra、final case fusion 和人工复核闭环。

## 有效产物

产物说明入口：

- `docs/artifacts.md`

日常 stage1 主线：

- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/staging/registry/asn_registry_baseline_monthly.manifest.json`
- `data/staging/links/asn_link_summary_monthly.csv`
- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`
- `data/staging/prefixes/asn_prefix_geo_monthly.csv`
- `data/staging/prefixes/asn_prefix_geo_monthly.manifest.json`
- `data/curated/stage1/asn_suspect_stage1.csv`
- `data/curated/stage1/asn_suspect_stage1.manifest.json`

registry history 旁线：

- `data/staging/registry/asn_delegated_monthly.csv`
- `data/curated/registry/asn_region_state_segments.csv`
- `data/curated/registry/asn_region_trajectories.csv`
- `data/curated/registry/asn_region_change_events.csv`
- `reports/asn_region_changes/summary_clean.md`

以上默认都是本机运行产物，不进入 Git。

## 验证状态

最近验证命令：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- `python3 scripts/check_repo_rules.py`：`passed`
- `pytest -q`：`31 passed`
- `registry`：`ok`，`827` rows
- `links`：`ok`，`5` rows
- `prefixes`：`ok`，`822` rows
- `prefix_geo`：`ok`，`822` rows
- `stage1`：`ok`，`827` rows

## 当前缺口

- prefix_geo 和 delegated registry 目前只完成 `IR / 2026-03` 试点，尚未扩展到其他国家或月份。
- `registered_country` 覆盖仍不足；当前 `827` 条 registry 记录中只有 `2` 条来自 RDAP 的 `registered_country` 非空。
- prefix_geo 只是静态画像，尚未生成面向人工复核的解释型 case card。
- case card / 人工复核报告尚未系统化生成。
- infra / path 证据还没有进入正式流水线。

## 下一步

下一步只围绕已生成的 `prefix_geo` 结果做人工复核材料或小范围解释增强，不要同时扩到 path、infra、case report 平台化。

这里的“下一步”是当前增量，不是长期终点；完整后续路线见 `docs/roadmap.md`。

当前试点结果：

- 国家：`IR`
- 月份：`2026-03`
- 输入：`822` 条伊朗 ASN prefix inventory
- 输出：`822` 条 prefix_geo 画像
- `geo_conflict_flag=true`：`35` 条
- stage1 合并后输出：`827` 条候选记录
- registry delegated 补齐后输出：`827` 条 registry baseline，其中 `allocated_country=IR` 为 `789` 条，`allocated_country=ZZ` 为 `28` 条
