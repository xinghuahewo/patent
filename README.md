# ASN 注册地与运营地不一致识别系统

## 1. 项目简介

本项目用于实现一套文件优先的离线流水线，用于识别“ASN 注册地与运营地可能不一致”的候选对象。

系统的自动输出仅用于：

- 构建第一阶段嫌疑集
- 生成结构化证据与案例材料
- 支持后续人工复核

本项目不以自动结果替代人工结论。

---

## 2. 分析单位

本项目统一以 `(asn, month)` 为分析单位。

- `asn`：自治系统编号
- `month`：格式固定为 `YYYY-MM`

---

## 3. 当前范围（v1）

v1 优先实现以下内容：

1. 工程骨架
2. 配置文件
3. 输入样例
4. schema 文档
5. 校验器
6. registry 数据采集与标准化
7. links 数据采集与标准化
8. 第一阶段嫌疑集构建

v1 暂不优先：

- 全量 traceroute / Paris traceroute
- 数据库服务化
- 可视化平台
- 自动最终裁定

当前另外增加一个独立单源试点：

- `prefixes`：基于本机 `rrc25` 的月末 `bview`，按月预计算目标国家 ASN 子集的前缀集合缓存
- `registry delegated region changes`：基于本地 NRO delegated stats 月末快照，分析 ASN 近五年的行政分配国家/RIR/大区连续变化

---

## 4. 目录结构

```text id="0r1tgt"
.
├─ AGENTS.md
├─ README.md
├─ configs/
│  ├─ pipeline.yaml
│  ├─ schemas/
│  └─ source_catalog.yaml
├─ data/
│  ├─ input/
│  │  └─ asn_months.csv
│  ├─ raw/
│  ├─ staging/
│  └─ curated/
├─ reports/
├─ scripts/
├─ tests/
└─ docs/
```

---

## 5. 数据分层
data/raw/

保存原始证据。
规则：只追加，不覆盖。

data/staging/

保存单源标准化结果。
规则：只做单源清洗与字段标准化，不做跨源融合。

data/curated/

保存融合结果。
规则：只在这一层做嫌疑集构建、评分和标签建议。

reports/

保存案例卡、复核材料和试点报告。

---

## 6. 当前核心输出
registry 基线
asn_registry_baseline_monthly
links 画像
asn_link_summary_monthly
第一阶段嫌疑集
asn_suspect_stage1

---

## 7.开发顺序

推荐按以下顺序实现：

AGENTS.md
configs/pipeline.yaml
data/input/asn_months.csv
docs/execution_plan.md
docs/schema_registry.md
docs/schema_links.md
scripts/validate_outputs.py
scripts/collect_registry.py
scripts/stage_registry.py
scripts/collect_links.py
scripts/stage_links.py
scripts/build_stage1_suspects.py

---

## 8.当前状态

当前仓库已具备 v1 第一阶段最小闭环：

1. `scripts/collect_registry.py`
2. `scripts/stage_registry.py`
3. `scripts/collect_links.py`
4. `scripts/stage_links.py`
5. `scripts/build_stage1_suspects.py`
6. `scripts/validate_outputs.py`
7. `scripts/collect_prefixes.py`
8. `scripts/stage_prefixes.py`

默认采集模式仍为离线 raw manifest：脚本会为每个 `(asn, month)` 保存可回溯的 raw evidence、状态和哈希，但不会伪造 registry 国家或 links 结构事实。

registry 已支持真实在线采集：

```bash
python scripts/collect_registry.py --online
```

在线模式会下载五大 RIR delegated 快照、按 ASN 查询 RDAP，并把完整源响应保存到 `data/raw/registry/delegated/` 与 `data/raw/registry/rdap/`。`data/raw/registry/manifest/` 中的每条 `(asn, month, run_id)` manifest 只索引和摘要这些 raw evidence。WHOIS 暂保留配置入口，本版本不把 WHOIS 作为成功条件。

links 也已支持真实在线采集：

```bash
python scripts/collect_links.py --online
```

在线模式会按 ASN 抓取 RIPEstat neighbours 当前/上一窗口快照和 CAIDA AS Rank links/relationships，并把完整源响应保存到 `data/raw/links/ripestat/` 与 `data/raw/links/asrank/`。`stage_links.py` 只读取 raw evidence，不联网。

prefixes 试点走本机文件，不在线下载：

```bash
python scripts/collect_prefixes.py --month 2026-03 --country IR
python scripts/stage_prefixes.py
```

如果要做长期批处理，可以直接跑多线程批处理器：

```bash
python scripts/collect_prefixes_batch.py --month 2026-03 --country IR --threads 8 --stage-after
```

它会对单个月份的 `bview` 做一次多 worker 解析，写 raw evidence，并在同一批次结束后调用 `stage_prefixes.py`。

这条线默认读取：

- 本机月末快照：`/home/bgpdata/data/ripe/rrc25/YYYY.MM/bview.*.gz`
- ASN 子集来源：`/home/experiment/info/as_entity.csv`

Collector 会对目标月份的 `bview` 扫描一次，筛出 `as_entity.csv` 中目标国家的 ASN（默认 `IR`），并为每个 `(asn, month)` 写入 raw evidence。这样后续试点挑几个伊朗 ASN 时，可以直接复用 `data/staging/prefixes/asn_prefix_inventory_monthly.csv`，不需要再次全量解析 `bview`。

registry delegated 近五年连续变化分析复用已下载的本地 raw 快照，不重新下载：

```bash
python3 scripts/analyze_asn_region_changes.py
```

默认读取：

- `data/raw/registry/delegated_monthly_go/`
- 窗口：`2021-04` 到 `2026-03`

输出包括：

- raw 验收：`reports/asn_region_changes/raw_inventory_check.csv`
- ASN 月度状态：`data/staging/registry/asn_delegated_monthly.{csv,parquet}`
- 连续区间：`data/curated/registry/asn_region_state_segments.{csv,parquet}`
- 完整轨迹：`data/curated/registry/asn_region_trajectories.{csv,parquet}`
- 变化事件：`data/curated/registry/asn_region_change_events.{csv,parquet}`
- 复核报告：`reports/asn_region_changes/summary.md`

这条线只分析 delegated 行政分配变化。`iana` 行保留在 raw 文件中，但不会展开为 ASN 月度状态，也不会参与跨 RIR 变化判断。

第一阶段输出位于：

- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/staging/links/asn_link_summary_monthly.csv`
- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`
- `data/curated/stage1/asn_suspect_stage1.csv`

如果环境安装了 pandas 和 pyarrow，也会同步输出对应 `.parquet` 文件。

建议验证命令：

```bash
pytest -q
python scripts/collect_prefixes.py --month 2026-03 --country IR --pilot-limit 10
python scripts/stage_prefixes.py
python scripts/validate_outputs.py --stage all
```
