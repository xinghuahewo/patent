# schema_links

## 1. 目的

本文件定义 links 标准化阶段的输出合同。

该阶段的目标是把连接结构类原始证据统一整理成按 `(asn, month)` 聚合的连接结构画像，用于后续：

- 结构异常识别
- 边界型特征识别
- 第一阶段嫌疑集构建的辅助输入

本阶段只负责 links 类证据的标准化与结构摘要，不负责最终评分，不负责最终标签，不负责运营国家推断。

---

## 2. 对应输出

标准输出表名：

- `asn_link_summary_monthly`

建议落盘位置：

- `data/staging/links/asn_link_summary_monthly.parquet`

可选导出：

- `data/staging/links/asn_link_summary_monthly.csv`

---

## 3. 输入来源

本表由以下原始证据标准化后生成：

- RIPEstat neighbours
- CAIDA AS Rank

原始证据应位于：

- `data/raw/links/`

---

## 4. 主键与粒度

主分析粒度为：

- `(asn, analysis_month)`

建议主键字段：

- `record_id`

建议唯一性约束：

- 同一 `run_id` 下，`asn + analysis_month` 唯一

如同一月存在多次抓取，不应简单重复输出，应在标准化阶段按窗口聚合或选择稳定规则后输出单条月度记录。

---

## 5. 字段定义

| 字段名 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| record_id | string | 是 | 记录唯一 ID |
| run_id | string | 是 | 本次运行批次 |
| schema_version | string | 是 | schema 版本 |
| parser_version | string | 是 | 解析器版本 |
| asn | int | 是 | ASN |
| analysis_month | string | 是 | 归属月份，格式 `YYYY-MM` |
| window_start | string | 是 | 本月聚合窗口起点 |
| window_end | string | 是 | 本月聚合窗口终点 |
| observed_neighbor_count | int | 否 | 观测到的邻居总数 |
| provider_count | int | 否 | provider 邻居数 |
| customer_count | int | 否 | customer 邻居数 |
| peer_count | int | 否 | peer 邻居数 |
| unknown_count | int | 否 | 关系未知邻居数 |
| new_neighbor_count | int | 否 | 相比上一窗口新增的邻居数 |
| lost_neighbor_count | int | 否 | 相比上一窗口消失的邻居数 |
| neighbor_churn_rate | float | 否 | 邻居波动率 |
| provider_switch_count | int | 否 | provider 切换次数 |
| link_instability_flag | bool | 是 | 是否存在链路结构不稳定 |
| border_as_flag | bool | 是 | 是否为边界型 ASN |
| topology_anomaly_flag | bool | 是 | 是否存在结构异常 |
| evidence_summary | string | 否 | 模板化证据摘要 |
| raw_evidence_path | string | 是 | 原始证据路径或索引路径 |
| raw_evidence_sha256 | string | 是 | 原始证据哈希 |

---

## 6. 字段语义说明

### 6.1 `observed_neighbor_count`
表示在本分析窗口内观察到的邻居总数。  
这是连接结构规模指标，不代表国家分布，也不代表运营地。

### 6.2 `provider_count / customer_count / peer_count / unknown_count`
表示按关系类型统计的邻居数量。  
这些字段只用于结构摘要和异常识别，不得直接推出地理结论。

### 6.3 `new_neighbor_count`
表示相对上一分析窗口新增的邻居数。

### 6.4 `lost_neighbor_count`
表示相对上一分析窗口消失的邻居数。

### 6.5 `neighbor_churn_rate`
表示邻居波动率。  
建议按标准化集合变化计算，不应随意自定义不稳定口径。

### 6.6 `provider_switch_count`
表示 provider 侧发生替换、切换或显著变化的次数。  
该字段是结构变化信号之一，但不是最终异常结论。

### 6.7 `link_instability_flag`
表示该 ASN 在当前窗口内是否表现出明显的连接结构不稳定。

### 6.8 `border_as_flag`
表示该 ASN 是否更接近“边界型”结构。  
该字段用于区分正常国际出口或边缘接入类型对象，避免误判。

### 6.9 `topology_anomaly_flag`
表示是否出现值得关注的连接结构异常。  
该字段只表示“异常性线索”，不等于运营地异常。

---

## 7. 值格式要求

### 7.1 `analysis_month`
必须为：

- `YYYY-MM`

### 7.2 窗口时间
以下字段建议使用标准时间格式：

- `window_start`
- `window_end`

### 7.3 计数字段
以下字段若非空，应为非负整数：

- `observed_neighbor_count`
- `provider_count`
- `customer_count`
- `peer_count`
- `unknown_count`
- `new_neighbor_count`
- `lost_neighbor_count`
- `provider_switch_count`

### 7.4 比例字段
以下字段若非空，应在合理范围内：

- `neighbor_churn_rate`

建议范围：
- `0.0 <= neighbor_churn_rate <= 1.0`

### 7.5 布尔字段
以下字段必须为显式布尔值：

- `link_instability_flag`
- `border_as_flag`
- `topology_anomaly_flag`

---

## 8. 标准化规则

### 8.1 多源合并原则
RIPEstat 与 AS Rank 可共同用于构造结构摘要，但必须注意：

- 原始证据必须保留
- 关系类型映射要统一
- 不能因为来源差异而静默丢弃冲突
- 若不同源统计不同，应允许在摘要中保留差异线索

### 8.2 聚合原则
本表是月度摘要表，应对窗口内多次观测做标准化聚合，不应把每次观测直接原样输出成多条月记录。

### 8.3 缺失值处理
允许以下字段为空：

- `provider_count`
- `customer_count`
- `peer_count`
- `unknown_count`
- `new_neighbor_count`
- `lost_neighbor_count`
- `neighbor_churn_rate`
- `provider_switch_count`

但公共字段、主键字段和证据链字段不能缺失。

---

## 9. 允许做的事

允许：

- 解析 RIPEstat neighbours
- 解析 AS Rank links / relationship 信息
- 统一关系类型命名
- 生成月度结构摘要
- 计算 churn / provider switch 等结构指标
- 标记边界型和结构异常

---

## 10. 禁止做的事

禁止：

- 直接根据邻居国家推断运营国家
- 输出最终评分
- 输出最终标签
- 使用 registry / geo / path / infra 数据做跨源融合
- 因为连接结构异常就直接认定 ASN 异常
- 把边界型 ASN 自动视为可疑对象

---

## 11. 关于边界型 ASN 的特别说明

`border_as_flag` 的存在，是为了识别这类对象：

- 国际边界接入明显
- 正常跨境互联较多
- 结构上看起来不像典型内向型网络

因此：

- `border_as_flag = true` 不代表异常
- 在后续嫌疑集构建中，应把它更多作为“解释性或分类性特征”，而不是直接当作风险信号

---

## 12. evidence_summary 建议格式

建议使用模板化摘要，避免完全自由文本。

示例：

- `neighbors=34; providers=2; peers=20; churn=0.18; border_as=1`
- `neighbors=5; providers=1; provider_switch=2; topology_anomaly=1`
- `neighbors=48; peers=35; border_as=1; topology_anomaly=0`

---

## 13. 质量校验规则

至少应校验：

1. `asn` 为正整数
2. `analysis_month` 符合 `YYYY-MM`
3. `window_start <= window_end`
4. 必填字段不为空
5. 计数字段为非负整数
6. `neighbor_churn_rate` 在合理范围内
7. 布尔字段为布尔值
8. `raw_evidence_path` 非空
9. `raw_evidence_sha256` 非空
10. `(asn, analysis_month, run_id)` 不重复

---

## 14. 最小样例

```json id="ng58eg"
{
  "record_id": "link_3491_2026-03",
  "run_id": "manual_2026_04_23_01",
  "schema_version": "v1",
  "parser_version": "v1",
  "asn": 3491,
  "analysis_month": "2026-03",
  "window_start": "2026-03-01T00:00:00Z",
  "window_end": "2026-03-31T23:59:59Z",
  "observed_neighbor_count": 34,
  "provider_count": 2,
  "customer_count": 6,
  "peer_count": 20,
  "unknown_count": 6,
  "new_neighbor_count": 3,
  "lost_neighbor_count": 2,
  "neighbor_churn_rate": 0.15,
  "provider_switch_count": 1,
  "link_instability_flag": false,
  "border_as_flag": true,
  "topology_anomaly_flag": false,
  "evidence_summary": "neighbors=34; providers=2; peers=20; churn=0.15; border_as=1",
  "raw_evidence_path": "data/raw/links/manifest/3491_2026-03.json",
  "raw_evidence_sha256": "example_sha256_value"
}
```

---

## 15. 与后续阶段的关系

本表将作为以下阶段输入之一：

- `uild_stage1_suspects.py`

后续阶段可读取：

- 邻居规模信息
- `churn` / `provider switch`
- `border_as_flag`
- `topology_anomaly_flag`

但不得把本表中结构字段直接解释为运营国家。

## 16. 实现提醒

实现 `stage_links.py` 时应注意：

1. 关系类型映射要稳定
2. 聚合规则要固定
3. `churn` 的口径要可复现
4. `border_as_flag` 不是风险标签
5. 本阶段不要越界做地理推断或最终判定