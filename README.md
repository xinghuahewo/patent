# ASN 注册地与运营地不一致识别系统

本项目是一套文件优先的离线流水线，用于识别“ASN 注册地与运营地可能不一致”的候选对象。

自动输出只用于构建嫌疑集、生成证据材料和支持人工复核，不代表最终裁定。

统一分析单位是 `(asn, month)`。

## 当前入口

- 当前状态：`docs/status.md`
- 工作日志：`docs/worklog.md`
- 运行手册：`docs/runbook.md`
- 长期路线：`docs/roadmap.md`
- 字段契约：`docs/schema.md`
- 细分 schema：`docs/schemas/`
- 产物目录：`docs/artifacts.md`
- 历史文档：`docs/archive/`

## 目录结构

```text
configs/      配置文件
data/input/   小规模输入样例
data/raw/     原始证据，本机保留，不进 Git
data/staging/ 单源标准化输出，本机保留，不进 Git
data/curated/ 融合结果和候选集，本机保留，不进 Git
docs/         工程文档和 schema
reports/      运行报告和人工复核材料，本机保留，不进 Git
scripts/      采集、标准化、融合、校验脚本
tests/        测试
```

## 日常主线

当前 stage1 主线是：

```text
data/input/asn_months.csv
  -> collect_registry.py / collect_links.py / collect_prefixes_batch.py
  -> stage_registry.py / stage_links.py / stage_prefixes.py / stage_prefix_geo.py
  -> build_stage1_suspects.py
  -> validate_outputs.py
```

核心输出：

- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/staging/links/asn_link_summary_monthly.csv`
- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`
- `data/staging/prefixes/asn_prefix_geo_monthly.csv`
- `data/curated/stage1/asn_suspect_stage1.csv`

## 常用命令

离线/默认采集：

```bash
python3 scripts/collect_registry.py
python3 scripts/stage_registry.py
python3 scripts/collect_links.py
python3 scripts/stage_links.py
python3 scripts/build_stage1_suspects.py
```

真实在线采集：

```bash
python3 scripts/collect_registry.py --online
python3 scripts/collect_links.py --online
```

本机 `rrc25` prefix 缓存：

```bash
python3 scripts/collect_prefixes_batch.py --month 2026-03 --country IR --threads 2 --stage-after
```

伊朗 `2026-03` prefix 静态地理画像：

```bash
python3 scripts/stage_prefix_geo.py --country IR --month 2026-03
python3 scripts/build_stage1_suspects.py
```

日常验证：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all
```

`check_repo_rules.py` 会检查文档入口、archive 状态、schema 登记、核心产物登记和 Git 大产物边界。`--stage all` 只校验日常 stage1 主线。五年 delegated 历史分析是大表旁线，需要显式运行：

每次改动源码、脚本、测试、配置、CI 或关键文档时，同步更新 `docs/worklog.md`，否则 PR 规则检查会失败。

```bash
python3 scripts/validate_outputs.py --stage registry_history
```

## 独立分析任务

五年 ASN delegated 行政分配变化分析复用本地 raw 快照：

```bash
python3 scripts/analyze_asn_region_changes.py
python3 scripts/build_clean_region_change_report.py
```

默认读取：

- `data/raw/registry/delegated_monthly_go/`

主要输出：

- `data/staging/registry/asn_delegated_monthly.{csv,parquet}`
- `data/curated/registry/asn_region_state_segments.{csv,parquet}`
- `data/curated/registry/asn_region_trajectories.{csv,parquet}`
- `data/curated/registry/asn_region_change_events.{csv,parquet}`
- `reports/asn_region_changes/summary_clean.md`

这条线只表示 delegated 行政分配变化，不代表运营地异常裁定。

## 当前下一步

`prefix_geo` 已完成伊朗 `2026-03` 单月试点。下一步优先围绕已生成的 geo 候选结果做人工复核材料或解释增强，暂不扩到 path、infra 或平台化 case report。

stage1 之后的长期路线见 `docs/roadmap.md`，不要从 `docs/status.md` 推断完整工程终点。
