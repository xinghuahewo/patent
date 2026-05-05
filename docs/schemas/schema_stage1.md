# schema_stage1

## 1. 目的

本文件定义第一阶段嫌疑集输出合同。

该阶段的目标是基于前序标准化结果，构建一个“需要进一步关注或确认”的 ASN 候选集合，用于后续：

- 精查优先级排序
- 设施与路径确认的目标选择
- 人工复核队列生成

本阶段输出的是候选集合，不是最终认定结果。

---

## 2. 对应输出

标准输出表名：

- `asn_suspect_stage1`

建议落盘位置：

- `data/curated/stage1/asn_suspect_stage1.parquet`

可选导出：

- `data/curated/stage1/asn_suspect_stage1.csv`

---

## 3. 输入来源

本表由以下标准化结果融合后生成：

- `asn_registry_baseline_monthly`
- `asn_link_summary_monthly`

当前 v1 已接入：

- `asn_prefix_geo_monthly`

如果缺少 prefix_geo 输入，脚本仍应显式保持默认空值或失败，不得伪造地理结论。

---

## 4. 主键与粒度

主分析粒度为：

- `(asn, month)`

建议主键字段：

- `record_id`

建议唯一性约束：

- 同一 `run_id` 下，`asn + month` 唯一

---

## 5. 字段定义

| 字段名 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| record_id | string | 是 | 记录唯一 ID |
| run_id | string | 是 | 本次运行批次 |
| schema_version | string | 是 | schema 版本 |
| parser_version | string | 是 | 解析器版本 |
| asn | int | 是 | ASN |
| month | string | 是 | 归属月份，格式 `YYYY-MM` |
| allocated_country | string | 否 | registry 分配国家 |
| registered_country | string | 否 | registry 注册国家 |
| dominant_prefix_country | string | 否 | 静态画像主导国家；v1 可为空 |
| admin_conflict_flag | bool | 是 | 是否存在行政冲突 |
| geo_conflict_flag | bool | 是 | 是否存在静态地理冲突；v1 可固定为 false 或空逻辑生成 |
| topology_anomaly_flag | bool | 是 | 是否存在结构异常 |
| border_as_flag | bool | 是 | 是否为边界型 ASN |
| suspect_level | string | 是 | `high` / `medium` / `low` |
| review_required_flag | bool | 是 | 是否需要进入后续确认或人工复核 |
| evidence_summary | string | 否 | 模板化证据摘要 |

---

## 6. 字段语义说明

### 6.1 `admin_conflict_flag`
来源于 registry 阶段。  
表示行政分配信息与注册信息之间存在不一致或冲突线索。

### 6.2 `geo_conflict_flag`
来源于 prefix geo 阶段。  
表示静态地理画像与行政基线之间存在冲突。

注意：
- v1 当前接入 `prefix_geo`
- 若某次运行没有可用 geo 数据，应使用稳定、显式的默认逻辑或直接失败
- 不要伪造地理结论

### 6.3 `topology_anomaly_flag`
来源于 links 阶段。  
表示连接结构存在值得关注的异常线索。

### 6.4 `border_as_flag`
表示该 ASN 更接近边界型网络。  
该字段不能直接解释为风险，更多用于避免误判。

### 6.5 `suspect_level`
表示第一阶段候选优先级，而不是最终风险结论。

允许值：
- `high`
- `medium`
- `low`

### 6.6 `review_required_flag`
表示该对象是否应进入下一步确认、抽样精查或人工复核。

---

## 7. 允许做的事

允许：

- 融合 registry 与 links 结果
- 读取前序 flag
- 生成第一阶段候选集合
- 输出候选优先级
- 输出证据摘要

---

## 8. 禁止做的事

禁止：

- 输出最终标签
- 输出最终评分
- 直接认定 ASN 异常
- 仅凭单个弱信号就给出高优先级
- 把 `border_as_flag` 直接当作风险证据
- 用 links 直接推出运营国家

---

## 9. suspect_level 建议规则

建议采用可解释、规则化的优先级逻辑。

### high
建议满足：
- `admin_conflict_flag = true`
- `topology_anomaly_flag = true`

如果后续接入 geo，也可允许：
- 行政冲突 + 地理冲突
- 行政冲突 + 地理冲突 + 结构异常

### medium
建议满足以下任一类：
- 三个冲突/异常标记中任意两个为 true
- 行政冲突为 true，但结构证据不足
- 结构异常明显，但行政冲突不充分

### low
建议用于：
- 仅存在单一弱信号
- 边界型特征较明显，但无足够冲突支撑
- 需要保留观察，但不优先进入精查

---

## 10. `review_required_flag` 建议规则

建议：

- `high` → `true`
- `medium` → `true`
- `low` → 可按配置决定，默认 `false`

如果项目采用试点模式，也可对部分 `low` 做抽样复核。

---

## 11. evidence_summary 建议格式

建议使用模板化摘要，避免完全自由文本。

示例：

- `allocated=US; registered=DE; admin_conflict=1; topology_anomaly=1; level=high`
- `allocated=GB; registered=GB; topology_anomaly=1; border_as=1; level=medium`
- `admin_conflict=0; topology_anomaly=0; border_as=1; level=low`

---

## 12. 质量校验规则

至少应校验：

1. `asn` 为正整数
2. `month` 符合 `YYYY-MM`
3. 必填字段不为空
4. 布尔字段为布尔值
5. `suspect_level` 属于允许值集合
6. `(asn, month, run_id)` 不重复

---

## 13. 最小样例

```json id="8l8kdb"
{
  "record_id": "stage1_3491_2026-03",
  "run_id": "manual_2026_04_23_01",
  "schema_version": "v1",
  "parser_version": "v1",
  "asn": 3491,
  "month": "2026-03",
  "allocated_country": "US",
  "registered_country": "DE",
  "dominant_prefix_country": null,
  "admin_conflict_flag": true,
  "geo_conflict_flag": false,
  "topology_anomaly_flag": true,
  "border_as_flag": false,
  "suspect_level": "high",
  "review_required_flag": true,
  "evidence_summary": "allocated=US; registered=DE; admin_conflict=1; topology_anomaly=1; level=high"
}
```

---

## 14. 与后续阶段的关系

本表是第一阶段候选输出，将作为以下流程输入：

- 后续精查目标筛选
- 设施确认
- 路径确认
- 人工复核队列
- 最终案例融合

该表不应被当作最终结论表使用。

## 15. 实现提醒

实现 `build_stage1_suspects.py` 时应注意：

1. 先保持规则简单、稳定、可解释
2. 优先复用前序阶段已有 flag
3. 不要把优先级写成最终风险认定
4. 保证输出可重复、可校验
5. 为后续接入 geo 输入预留字段，但不要强依赖未实现数据
