# schema_case_material

状态：active

## 1. 目的

本文件定义 stage1 之后人工复核材料的输出契约。

case material 的目标是把已有候选整理成可阅读、可排队、可回溯的人工复核材料。它只服务人工复核，不生成最终运营国，也不生成异常裁定。

## 2. 对应输出

标准输出目录：

- `reports/case_material/IR_2026-03/`

当前试点只覆盖：

- 国家：`IR`
- 月份：`2026-03`
- 触发条件：stage1 与 prefix_geo 均为 `geo_conflict_flag=true`

目录结构：

```text
reports/case_material/IR_2026-03/
  summary.md
  review_queue.csv
  manifest.json
  cases/AS{asn}.md
```

## 3. 输入来源

本报告读取：

- `data/curated/stage1/asn_suspect_stage1.csv`
- `data/staging/prefixes/asn_prefix_geo_monthly.csv`
- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/staging/prefixes/asn_prefix_inventory_monthly.csv`

## 4. 主键与粒度

主分析粒度：

- `(asn, month)`

当前每个候选 ASN 生成一张 Markdown case card。

## 5. `review_queue.csv` 必备字段

| 字段名 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| asn | int | 是 | ASN |
| month | string | 是 | 归属月份，格式 `YYYY-MM` |
| review_priority | string | 是 | `high_review` / `medium_review` / `low_review` |
| evidence_status | string | 是 | `evidence_ready` / `partial_evidence` / `insufficient_evidence` |
| trigger_reason | string | 是 | 进入复核队列的触发线索 |
| weakness_flags | string | 是 | 分号分隔的证据弱点或解释性降权线索，可为空 |
| raw_evidence_path | string | 是 | stage1 证据 manifest 或上游 raw evidence 路径 |
| raw_evidence_sha256 | string | 是 | 对应证据 hash |

允许扩展辅助字段，例如：

- `allocated_country`
- `registered_country`
- `dominant_prefix_country`
- `prefix_count`
- `mapped_prefix_count`
- `unmapped_prefix_count`
- `foreign_prefix_coverage_ratio`
- 各上游源的 `raw_evidence_path` / `raw_evidence_sha256`

## 6. 复核优先级

`high_review` 建议满足：

- dominant prefix country 是明确真实国家。
- foreign prefix coverage 较高。
- prefix 数量足够。
- registry 信息不属于明显不足状态。
- 没有边界型 ASN、云厂商、CDN、骨干网、跨国集团等解释性降权线索。

`medium_review` 用于：

- geo conflict 成立，但 prefix 数量较少。
- registry 信息不足，例如 `registered_country` 缺失。
- 当前证据可复核，但不足以进入最高优先级。

`low_review` 用于：

- `ZZ` / unmapped 多。
- prefix 数量过少或映射比例过低。
- 解释性风险较高，需要先降权或补充证据。

## 7. 证据状态

- `evidence_ready`：必要证据较完整。
- `partial_evidence`：有可复核线索，但存在缺失或弱点。
- `insufficient_evidence`：证据弱点较重，只能保留为低优先级线索。

缺失数据只能进入 `evidence_status` 或 `weakness_flags`，不得补假值。

## 8. 禁止做的事

禁止：

- 输出最终运营国字段。
- 输出异常裁定字段。
- 把 `dominant_prefix_country` 当作运营国家。
- 把 `geo_conflict_flag` 当作最终异常结论。
- 用邻居国家推断运营国家。
- 覆盖或修改上游 raw evidence。

## 9. 运行命令

```bash
python3 scripts/build_case_material.py --country IR --month 2026-03
```
