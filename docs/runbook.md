# 运行手册

本文是唯一执行入口，记录怎么跑、怎么校验、怎么整理仓库。

长期技术路线见 `docs/roadmap.md`。本文只维护当前可运行命令和仓库维护规则。

下次打开仓库时先看 `docs/worklog.md`，再看 `docs/status.md`。

## 基本原则

- 统一分析单位是 `(asn, month)`。
- `raw` 只追加，不覆盖。
- `staging` 只做单源标准化。
- `curated` 才允许做融合、候选集、评分和标签建议。
- 自动结果只用于人工复核，不是最终裁定。

## 主线和旁线

新任务开始前必须先判定：

- 主线：会长期进入 stage1 的证据源或融合逻辑，例如 registry、links、prefix_geo。
- 旁线：专题分析或一次性报告，例如五年 delegated 行政分配变化。

主线可以进入日常 `--stage all`。旁线必须单独设命令和校验 stage，不得拖慢默认校验。

## 日常主线

```text
data/input/asn_months.csv
  -> data/raw/{registry,links,prefixes}
  -> data/staging/{registry,links,prefixes,prefix_geo}
  -> data/curated/stage1
```

默认离线/manifest 采集：

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

当前 `prefix_geo` 只做伊朗 `2026-03` 单月试点。代码保留参数化能力，但默认执行范围不要扩到其他国家或月份：

```bash
python3 scripts/stage_prefix_geo.py --country IR --month 2026-03
python3 scripts/validate_outputs.py --stage prefix_geo
python3 scripts/collect_registry_delegated_local.py --country IR --month 2026-03
python3 scripts/stage_registry.py --input data/input/asn_months_registry_IR_2026-03.csv
python3 scripts/build_stage1_suspects.py
```

`prefix_geo` 阶段只输出静态前缀地理画像，不直接做最终运营国裁定。`collect_registry_delegated_local.py` 只从本地 NRO delegated ASN 快照补 `allocated_country`，不会伪造 `registered_country`。

## 校验

日常快速校验：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all
```

`check_repo_rules.py` 检查文档入口、archive 状态、schema 登记、核心产物登记和 Git 大产物边界。`--stage all` 只覆盖 registry、links、prefixes、prefix_geo、stage1。

CI 只运行仓库规则检查和单元测试：

```bash
python3 scripts/check_repo_rules.py
pytest -q
```

原因是 CI 环境没有本机 `/home/bgpdata` bview 和已生成的 staging/curated 产物；完整产物校验仍在本机运行。

registry history 旁线校验：

```bash
python3 scripts/validate_outputs.py --stage registry_history
```

单阶段校验：

```bash
python3 scripts/validate_outputs.py --stage registry
python3 scripts/validate_outputs.py --stage links
python3 scripts/validate_outputs.py --stage prefixes
python3 scripts/validate_outputs.py --stage prefix_geo
python3 scripts/validate_outputs.py --stage stage1
```

## registry history 旁线

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

该旁线只表示 delegated 行政分配变化，不代表运营地异常裁定。

## 文档规则

顶层 docs 只保留：

- `docs/worklog.md`：最近工作记录和下次接手入口。
- `docs/status.md`：当前状态、有效产物、下一步。
- `docs/runbook.md`：运行命令、校验命令、维护规则。
- `docs/roadmap.md`：stage1 之后的长期技术路线和模块边界。
- `docs/schema.md`：核心输出字段契约。
- `docs/schemas/`：仍有效的细分 schema 和语义约束。
- `docs/artifacts.md`：重要产物的来源、含义、限制和校验命令。
- `docs/archive/`：已替代的历史计划、旧状态快照和早期说明。

`README.md` 只做入口页，不写长进度、历史日志或临时结论。

任务结束时，如果改变了流程、产物、验证结果或下一步，必须更新 `docs/status.md`。

任务结束时，如果修改了源码、脚本、测试、配置、CI 或关键文档，必须更新 `docs/worklog.md`，记录本次目标、改动、验证、遗留问题和下次入口。

`data/staging` 和 `data/curated` 下新增或更新核心数据产物时，必须同步更新 `docs/artifacts.md`。能由脚本生成的 staging/curated 产物，应尽量在同目录写入 `*.manifest.json`，记录生产脚本、输入、输出、hash、行数和语义边界。

新增文件必须满足自动检查：

- 顶层 `docs/` 只允许 `status.md`、`runbook.md`、`roadmap.md`、`schema.md`、`artifacts.md`、`schemas/`、`archive/`。
- 顶层 `docs/` 还必须包含 `worklog.md`，并具备固定接手入口结构。
- `docs/archive/` 中的历史文件必须在顶部声明 `状态：archived` 或 `状态：archived-source`，并说明 `归档原因`。
- `docs/schemas/*.md` 必须登记到 `docs/schemas/README.md`。
- `data/staging` 和 `data/curated` 下的核心 CSV/Parquet 必须登记到 `docs/artifacts.md`。
- `data/raw`、`data/staging`、`data/curated`、`reports`、`logs` 下的生成物不得进入 Git，目录 `.gitkeep` 除外。
- PR 中修改源码、文档、测试、配置或 CI 时，必须同步修改 `docs/worklog.md`。

## 产物规则

默认不进入 Git：

- `data/raw/`
- `data/staging/`
- `data/curated/`
- `reports/`
- `logs/`

提交时只提交脚本、配置、文档、测试和小规模输入样例。大 CSV、Parquet、raw dump、日志只记录路径和生成命令。

## 新源域模板

新增一个源域时，默认按这个顺序：

1. 写 `docs/schema.md` 中的新章节。
2. 实现 `scripts/collect_xxx.py`。
3. 实现 `scripts/stage_xxx.py`。
4. 在 `scripts/validate_outputs.py` 增加 `--stage xxx`。
5. 跑通 raw -> staging -> validator。
6. 稳定后再接入 `scripts/build_stage1_suspects.py`。
7. 更新 `docs/status.md`。

当前新增源域的具体范围是 `prefix_geo`，先用已有伊朗 `2026-03` prefix inventory 跑通 raw/staging/validator/stage1 融合链路，再考虑扩充国家或月份。

stage1 完成后的 case material、path、infra、final case fusion 不写进本文作为当前命令，除非对应模块已经实现并有可校验入口；设计边界先维护在 `docs/roadmap.md`。
