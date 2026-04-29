# schema_registry

## 1. 目的

本文件定义 registry 标准化阶段的输出合同。

该阶段的目标是把多个 registry 类原始证据统一整理成按 `(asn, month)` 聚合的行政注册基线，用于后续：

- 行政冲突识别
- 基础组织属性标记
- 嫌疑集构建的输入之一

本阶段只负责 registry 类证据的标准化，不负责最终评分，不负责最终标签，不负责运营国家推断。

---

## 2. 对应输出

标准输出表名：

- `asn_registry_baseline_monthly`

建议落盘位置：

- `data/staging/registry/asn_registry_baseline_monthly.parquet`

可选导出：

- `data/staging/registry/asn_registry_baseline_monthly.csv`

---

## 3. 输入来源

本表由以下原始证据标准化后生成：

- delegated / delegated extended
- RDAP
- WHOIS

原始证据应位于：

- `data/raw/registry/`

---

## 4. 主键与粒度

主分析粒度为：

- `(asn, analysis_month)`

建议主键字段：

- `record_id`

建议唯一性约束：

- 同一 `run_id` 下，`asn + analysis_month` 唯一
- 如果存在多条冲突记录，不应直接重复输出，应在标准化阶段先合并或标注冲突

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
| allocated_country | string | 否 | RIR delegated 分配国家 |
| registered_country | string | 否 | RDAP/WHOIS 提取的注册国家 |
| registered_rir | string | 否 | 所属 RIR |
| org_name | string | 否 | 注册组织名称 |
| parent_org | string | 否 | 上级组织或归属组织 |
| allocation_date | string | 否 | 分配日期 |
| allocation_status | string | 否 | 分配状态 |
| admin_conflict_flag | bool | 是 | 是否存在行政冲突 |
| multi_country_registry_flag | bool | 是 | registry 国家字段是否多值冲突 |
| cloud_or_cdn_flag | bool | 是 | 是否可能为云厂商或 CDN |
| crossborder_group_flag | bool | 是 | 是否可能为跨国集团 |
| hosting_or_lease_hint_flag | bool | 是 | 是否存在托管/租赁提示 |
| evidence_summary | string | 否 | 模板化证据摘要 |
| raw_evidence_path | string | 是 | 原始证据路径或索引路径 |
| raw_evidence_sha256 | string | 是 | 原始证据哈希 |
| source_snapshot_time | string | 否 | 源快照时间 |
| fetch_time | string | 是 | 抓取时间 |

---

## 6. 字段语义说明

### 6.1 `allocated_country`
表示 delegated 数据中的分配国家。  
这是行政分配层面的国家，不等于运营地。

### 6.2 `registered_country`
表示从 RDAP 或 WHOIS 中提取出的注册国家。  
如果 RDAP 与 WHOIS 不一致，应优先记录冲突，不要直接静默覆盖。

### 6.3 `admin_conflict_flag`
用于表示行政层面是否出现不一致，例如：

- `allocated_country != registered_country`
- registry 字段内部多值冲突
- 同一 ASN 对应组织归属呈现明显跨国矛盾

该字段只表示“需要关注的行政冲突”，不表示最终异常。

### 6.4 `multi_country_registry_flag`
表示同一阶段内从 registry 类数据提取出的国家字段存在多值冲突。

### 6.5 `cloud_or_cdn_flag`
表示该 ASN 可能属于云厂商、CDN 或类似网络。  
这是后续解释性降权的重要依据之一。

### 6.6 `crossborder_group_flag`
表示该 ASN 可能属于跨国集团或跨国运营实体。  
该字段用于减少对正常跨境企业的误报。

### 6.7 `hosting_or_lease_hint_flag`
表示 registry 文本中存在托管、租赁、代管、上级组织映射等提示。  
该字段只作为解释性线索，不是结论。

---

## 7. 值格式要求

### 7.1 `analysis_month`
必须为：

- `YYYY-MM`

示例：
- `2026-03`

### 7.2 国家字段
以下字段若非空，应使用统一国家码格式：

- `allocated_country`
- `registered_country`

建议统一为两位大写国家码。

### 7.3 布尔字段
以下字段必须为显式布尔值，不要使用字符串代替：

- `admin_conflict_flag`
- `multi_country_registry_flag`
- `cloud_or_cdn_flag`
- `crossborder_group_flag`
- `hosting_or_lease_hint_flag`

---

## 8. 标准化规则

### 8.1 多源合并原则
对于 delegated、RDAP、WHOIS：

- 原始证据必须保留
- 合并时优先标准化字段，不要丢弃冲突信息
- 若多个源返回国家不一致，应通过 flag 体现，而不是简单覆盖

### 8.2 缺失值处理
允许以下字段为空：

- `allocated_country`
- `registered_country`
- `org_name`
- `parent_org`
- `allocation_date`
- `allocation_status`

但公共字段、主键字段和证据链字段不能缺失。

### 8.3 文本清洗
组织名、上级组织名等文本字段可做：
- 去首尾空白
- 连续空白压缩
- 基本编码清洗

不要在本阶段做过强的语义归并。

---

## 9. 本阶段允许做的事

允许：

- 解析 delegated / RDAP / WHOIS
- 统一字段名与类型
- 合并多源 registry 结果
- 标记行政冲突
- 标记基础组织属性
- 输出证据摘要

---

## 10. 本阶段禁止做的事

禁止：

- 推断最终运营国家
- 计算最终评分
- 输出最终标签
- 使用 links / geo / path / infra 数据
- 做跨源大融合
- 因为单个字段异常就直接认定 ASN 异常

---

## 11. evidence_summary 建议格式

建议使用模板化摘要，避免完全自由文本。

示例：

- `allocated_country=US; registered_country=DE; admin_conflict=1`
- `allocated_country=GB; registered_country=GB; crossborder_group=1`
- `registered_country missing; delegated_country=NL; multi_country_registry=1`

模板化摘要便于：
- 搜索
- 审计
- 案例卡自动生成

---

## 12. 质量校验规则

至少应校验：

1. `asn` 为正整数
2. `analysis_month` 符合 `YYYY-MM`
3. 必填字段不为空
4. 布尔字段为布尔值
5. 国家码字段格式合理
6. `raw_evidence_path` 非空
7. `raw_evidence_sha256` 非空
8. `(asn, analysis_month, run_id)` 不重复

---

## 13. 最小样例

```json id="xi5v9t"
{
  "record_id": "reg_3491_2026-03",
  "run_id": "manual_2026_04_23_01",
  "schema_version": "v1",
  "parser_version": "v1",
  "asn": 3491,
  "analysis_month": "2026-03",
  "allocated_country": "US",
  "registered_country": "DE",
  "registered_rir": "ARIN",
  "org_name": "Example Network",
  "parent_org": "Example Group",
  "allocation_date": "1995-01-01",
  "allocation_status": "assigned",
  "admin_conflict_flag": true,
  "multi_country_registry_flag": false,
  "cloud_or_cdn_flag": false,
  "crossborder_group_flag": true,
  "hosting_or_lease_hint_flag": false,
  "evidence_summary": "allocated_country=US; registered_country=DE; admin_conflict=1; crossborder_group=1",
  "raw_evidence_path": "data/raw/registry/manifest/3491_2026-03.json",
  "raw_evidence_sha256": "example_sha256_value",
  "source_snapshot_time": "2026-03-31T00:00:00Z",
  "fetch_time": "2026-04-23T10:00:00Z"
}
```

---

## 14. 与后续阶段的关系

本表将作为以下阶段输入之一：

- build_stage1_suspects.py
- 后续案例融合阶段

后续阶段可读取：

- allocated_country
- registered_country
- admin_conflict_flag
- 解释性标记字段

但不得回写或篡改本表原始语义。

---

## 15. 实现提醒

实现 stage_registry.py 时应注意：

1. raw 证据要可回溯
2. 冲突信息不要被静默覆盖
3. 输出要稳定、可重复
4. 字段命名要与 schema 保持一致
5. 本阶段不要越界做最终判定
