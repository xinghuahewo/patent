# 长期路线

状态：active

角色：长期技术路线。本文回答 stage1 完成后继续做什么，以及后续模块之间如何衔接。当前状态和下一小步仍以 `docs/status.md` 为准；运行命令仍以 `docs/runbook.md` 为准。

## 总体目标

本项目识别的是“ASN 注册地与运营地可能不一致”的候选对象。自动输出只用于构建嫌疑集、汇总证据、排序复核优先级，不直接给出最终裁定。

统一分析单位保持为：

```text
(asn, month)
```

长期方法分两层：

- 第一层：低成本嫌疑集构建，使用 registry、prefix_geo、links 等静态或半静态证据生成 stage1 候选。
- 第二层：高成本主动确认，对高优先级候选做 case material、路径测量、设施确认和人工复核。

## 时间组织

每个 `(asn, month)` 对应三类窗口：

- BGP 观测窗：前 90 天，用于 prefix、AS_PATH、连接结构和波动特征。
- 路径测量窗：前 30 天，用于 traceroute / Paris traceroute 结果。
- 设施快照窗：周级采样，用于 PeeringDB、IXP 和 facility presence。

当前主线还没有正式接入 path / infra，这些窗口是后续模块设计基线，不代表已有产物。

## 第一层：stage1 候选构建

stage1 只做候选集，不做最终定性。

当前主线证据：

- registry：行政分配和注册对象基线，输出 `admin_conflict_flag` 及解释性降权线索。
- prefix_geo：静态 prefix-country 画像，输出 `dominant_prefix_country`、覆盖比例和 `geo_conflict_flag`。
- links：连接结构画像，输出 `topology_anomaly_flag` 和 `border_as_flag`。

关键边界：

- 不得直接用邻居国家推断运营国家。
- `dominant_prefix_country` 只是静态画像，不是最终运营国家。
- 行政冲突、静态地理冲突、连接结构异常必须分开处理。
- `border_as_flag` 主要用于避免误判边界型 ASN，不应自动当作风险证据。
- 云厂商、CDN、骨干网、跨国集团、托管或租赁线索需要解释性降权。

stage1 输出：

```text
data/curated/stage1/asn_suspect_stage1.csv
```

stage1 完成后，它应作为以下流程输入：

- 精查优先级排序。
- case material / 人工复核材料生成。
- path 测量目标选择。
- infra 设施确认目标选择。
- 最终案例融合。

## 第二层：case material

case material 是 stage1 之后最小、最稳妥的下一层，不等同于最终报告平台化。

目标：

- 为候选 ASN 生成可人工阅读的证据卡。
- 展示哪个信号触发、哪个信号未触发。
- 保留 raw evidence 路径和 hash。
- 明确解释性降权线索。
- 标注证据不足或需要继续测量的原因。

建议输出：

```text
reports/case_material/
```

case material 可以先只覆盖当前试点国家和月份，不要一开始扩展成全量平台。

## 第三层：路径确认

path 模块只对高优先级或抽样候选运行，不进入默认 `--stage all`。

输入：

- stage1 高优先级候选 ASN。
- 代表性目标 IP。
- 多国家、多 ASN 视角探针。

方法：

- traceroute / Paris traceroute。
- 多探针、多时点测量。
- 聚焦进入目标 ASN 前后的边界 hop。

建议 staging 输出：

```text
data/staging/path/asn_path_measurement_monthly.csv
```

关键字段：

- `border_ingress_country`
- `last_stable_country`
- `multi_probe_agreement`
- `measurement_time`
- `confidence_score`
- `raw_evidence_path`
- `raw_evidence_sha256`

语义边界：

- 单次 traceroute 不能定性。
- 路径落点需要多探针、多时点稳定支持。
- 路径确认结果仍是证据，不是自动裁定。

## 第四层：设施确认

infra 模块用于确认 ASN 在哪些国家长期有公开设施或交换点 presence。

输入源候选：

- PeeringDB。
- IXP presence。
- facility presence。

建议 staging 输出：

```text
data/staging/infra/asn_infra_presence_weekly.csv
data/staging/infra/asn_infra_profile_monthly.csv
```

关键字段：

- `country`
- `ixp_count`
- `facility_count`
- `presence_score`
- `dominant_infra_country`
- `shared_ixp_country_set_json`
- `raw_evidence_path`
- `raw_evidence_sha256`

语义边界：

- PeeringDB / facility 信息可能过旧或不完整。
- 设施 presence 需要和 registry、prefix_geo、path 一起解释。
- 设施国家不是单独的最终运营国家裁定。

## 第五层：多源融合与人工复核

最终融合层只能在 curated 或 reports 层进行，不得回写 staging 语义。

需要融合的国家字段包括：

- `allocated_country`
- `registered_country`
- `dominant_prefix_country`
- `dominant_infra_country`
- `last_stable_country`

建议评分字段：

```text
GeoMismatchScore
MismatchScore
```

评分只能用于复核优先级，不替代人工复核。

建议最终案例表：

```text
data/curated/final/asn_case_final.csv
```

建议 `final_label` 取值：

```text
normal_border_as
explainable_crossborder
suspected_offshore_like
insufficient_evidence
```

最终流程必须是：

```text
自动评分 -> 案例卡 -> 人工复核 -> 最终标签
```

不能变成：

```text
自动评分 -> 直接定性
```

## 后续实施顺序

当前 stage1 已接入 registry、links、prefixes、prefix_geo。后续建议按以下顺序推进：

1. 为已生成的 stage1 / prefix_geo 候选生成小范围 case material。
2. 扩展 `registered_country` 覆盖，优先改善 registry 证据完整性。
3. 只对高优先级候选设计 path 试点，不进入默认全量校验。
4. 设计 infra staging schema 和小样本采集。
5. 在 path / infra 均有可校验证据后，再设计 final case fusion。

任何新增源域必须遵守：

- 先 schema。
- 再 collect / stage。
- 再 validator。
- 再接入 build 或 report。
- 新增 staging / curated 核心产物必须登记到 `docs/artifacts.md`。

