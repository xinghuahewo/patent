可以。你现在要的“技术性”版本，不是再写一遍专利语言，而是把 **S1-S9 翻译成可实现的技术流程**：每一步具体拿什么数据、算什么字段、产出什么表、怎么进入下一步。你前面已经把工程口径收紧为 **AS-月**、**90 天 BGP + 30 天路径测量 + 周级设施快照**，并且连接层优先采用 **RIPEstat + CAIDA AS Rank** 双源，这正适合写成技术方案。 

下面我给你一版**技术性总稿**，结构上仍对应 S1-S9，但写法改成“模块—输入—处理—输出”。

---

# 技术方案：自治系统注册地与运营地不一致识别流程

## 0. 总体技术框架

系统目标是识别：

> **注册地在 A 国，但静态承载、设施落点、路径落点长期更偏向 B 国的 ASN。**

整个系统分两层：

### 第一层：低成本嫌疑集构建

用静态和半静态数据，从全量 ASN 中筛出嫌疑对象。

### 第二层：高成本主动确认

对高优先级嫌疑 ASN 做路径测量、设施核查和人工复核。

---

## 1. 分析单位与时间组织

### 1.1 分析单位

以 **AS-月** 作为最小分析单位。
也就是说，所有特征最终都要落到：

```text
(asn, month)
```

这能保证：

* 行政信息可按月对齐
* BGP 特征可按月聚合
* 路径测量可按月汇总
* 后续评分和审计简单

### 1.2 时间窗口

每个 `(asn, month)` 对应三类时间窗：

* **BGP 观测窗：前 90 天**

  * 用于前缀、AS_PATH、连接结构、波动特征
* **路径测量窗：前 30 天**

  * 用于 traceroute / Paris traceroute 结果
* **设施快照窗：周级采样**

  * 用于 PeeringDB / IXP / facility presence

这套时间组织是你前面已经确定的工程基线。

---

## 2. 数据层设计

## 2.1 行政注册数据层

### 输入源

* 五大 RIR delegated stats / delegated extended stats
* RDAP
* WHOIS

### 目标

建立两个核心国家字段：

* `allocated_country`
* `registered_country`

### 建议表结构

#### `asn_registry_baseline`

```text
asn
month
rir
allocated_country
allocated_date
allocation_status
registered_country
org_country
org_name
parent_org
rdap_source
whois_source
is_multivalue_country_conflict
is_large_crossborder_group
is_cloud_or_cdn_or_backbone
has_public_hosting_or_leasing_evidence
```

### 处理逻辑

1. 从 delegated stats 中筛 `type=asn`
2. 映射目标 ASN 到：

   * RIR
   * country code
   * date
   * status
3. 从 RDAP / WHOIS 解析：

   * org name
   * org country
   * parent org
   * entity country
4. 统一成月度基线表

### 输出

* `allocated_country`
* `registered_country`
* 行政冲突标签

---

## 2.2 静态运营地画像层

### 输入源

* BGP 起源前缀集合
* 多个 IP 地理位置库

### 目标

确定：

* `dominant_prefix_country`
* `candidate_operation_countries`

### 建议表结构

#### `asn_prefix_geo_monthly`

```text
asn
month
prefix
sample_ip_count
country_votes_json
dominant_country
coverage_ratio
is_stable_across_windows
```

#### `asn_geo_profile_monthly`

```text
asn
month
dominant_prefix_country
candidate_operation_countries_json
foreign_prefix_coverage_ratio
geo_conflict_flag
```

### 处理逻辑

1. 获取 ASN 起源前缀
2. 对每个前缀做：

   * 随机采样
   * 边界采样
3. 多库地理映射
4. 对单前缀投票得到 `dominant_country`
5. 汇总到 ASN 级，统计各国覆盖比例
6. 判断是否存在：

   * 异于注册国的主导国家
   * 连续窗口稳定存在的异国覆盖

### 输出

* `dominant_prefix_country`
* `foreign_prefix_coverage_ratio`
* `geo_conflict_flag`

---

## 2.3 连接结构画像层

你前面已经决定连接层只保留两类源：

* **RIPEstat**：观测邻居集合
* **CAIDA AS Rank**：provider / customer / peer 关系

这非常适合做月度结构画像。

### 建议表结构

#### `asn_links_normalized`

```text
asn
neighbor_asn
observation_time
month
source
relation_type_normalized
is_directly_observed
confidence_score
```

#### `asn_links_fused`

```text
asn
neighbor_asn
month
neighbor_observed_by_ripestat
relationship_from_asrank
relationship_final
source_agreement
combined_confidence
```

#### `asn_link_summary_monthly`

```text
asn
month
observed_neighbor_count
provider_count
customer_count
peer_count
unknown_count
new_neighbor_count
lost_neighbor_count
neighbor_churn_rate
provider_switch_count
ripestat_only_count
asrank_only_count
both_sources_count
```

### 处理逻辑

1. 拉 RIPEstat ASN neighbours
2. 拉 CAIDA AS Rank links
3. 按 `(asn, neighbor_asn, month)` 融合
4. 聚合出月度结构特征

### 核心指标

#### 邻居波动率

```text
neighbor_churn_rate =
(new_neighbor_count + lost_neighbor_count) / max(prev_month_neighbor_count, 1)
```

#### provider 切换次数

```text
provider_switch_count =
本月 provider 集合 与 上月 provider 集合 的差异次数
```

### 输出

* `observed_neighbor_count`
* `provider_count / customer_count / peer_count`
* `neighbor_churn_rate`
* `provider_switch_count`

### 重要限制

连接结构层只回答：

* 是否异常
* 是否像边界型网络
* 是否长期依赖少量上游

**不能直接回答运营国家。**
这也是你前面已经反复校正过的逻辑。

---

## 3. 第一阶段嫌疑集构建逻辑

## 3.1 行政冲突判定

### 条件

满足以下任一项即可：

* `allocated_country != registered_country`
* 历史分配国家出现跨国变化
* RDAP / WHOIS 对象国家存在稳定多值冲突

### 输出

```text
admin_conflict_flag = 1
```

---

## 3.2 静态地理冲突判定

### 条件

满足以下全部项：

* `dominant_prefix_country != registered_country`
* 异国覆盖比例超过阈值 `T_geo`
* 在至少两个连续窗口内稳定存在

### 输出

```text
geo_conflict_flag = 1
```

---

## 3.3 结构异常判定

### 条件示例

满足其中一项即可：

* `observed_neighbor_count` 很低
* `provider_count` 极少且长期稳定单点依赖
* `neighbor_churn_rate > T_churn`
* `provider_switch_count > T_provider_switch`

### 输出

```text
topology_anomaly_flag = 1
```

---

## 3.4 边界型 ASN 识别

边界型不是嫌疑结论，而是一个中间标签。

### 条件示例

* 跨境连接明显
* provider / peer 结构表现出国际出口特征
* 本地融入度弱但并非一定异常

### 输出

```text
border_as_flag = 1
```

---

## 3.5 第一阶段嫌疑分层

### 高优先级

```text
admin_conflict_flag = 1
and geo_conflict_flag = 1
and topology_anomaly_flag = 1 or border_as_flag = 1
```

### 中优先级

* 行政冲突 + 地理冲突
* 或 地理冲突 + 结构异常
* 或 单类强证据连续稳定存在

### 低优先级

* 单类弱证据
* 存在合理解释标签

### 建议表结构

#### `asn_suspect_stage1`

```text
asn
month
allocated_country
registered_country
dominant_prefix_country
admin_conflict_flag
geo_conflict_flag
topology_anomaly_flag
border_as_flag
suspect_level
evidence_summary
```

这部分基本就是你前面“构建嫌疑集步骤”的技术落地版。

---

## 4. 第二阶段主动确认逻辑

## 4.1 路径测量模块

### 输入

* 高优先级嫌疑 ASN
* 代表性目标 IP
* 多国家探针

### 方法

* traceroute / Paris traceroute
* 多探针、多时点测量
* 聚焦进入 ASN 之前和之后的边界 hop

### 输出表

#### `asn_path_measurement_monthly`

```text
asn
month
probe_id
target_ip
border_ingress_country
last_stable_country
hop_count
measurement_time
confidence_score
```

### 汇总字段

```text
BorderIngressCountry
LastStableCountry
MultiProbeAgreement
```

---

## 4.2 设施与交换点模块

### 输入

* PeeringDB
* IXP presence
* facility presence

### 目标

确认该 ASN 在哪些国家长期有设施落点

### 输出表

#### `asn_infra_presence_weekly`

```text
asn
week
country
ixp_count
facility_count
presence_score
```

#### `asn_infra_profile_monthly`

```text
asn
month
dominant_infra_country
shared_ixp_country_set_json
facility_presence_count_by_country_json
```

### 汇总字段

* `dominant_infra_country`
* `shared_ixp_country_set`

---

## 5. 多源证据融合与评分

这一层是整个系统的核心。

### 5.1 需要融合的国家字段

* `allocated_country`
* `registered_country`
* `dominant_prefix_country`
* `dominant_infra_country`
* `last_stable_country`

### 5.2 基本思想

如果一个 ASN：

* 注册在美国
* 但主前缀国是德国
* 主设施国是德国
* 路径稳定落点也是德国

那么它比“只出现一条德国线索”的 ASN 更值得怀疑。

---

## 5.3 建议评分字段

#### `GeoMismatchScore`

用于衡量地理不一致程度：

```text
GeoMismatchScore =
w1 * I(dominant_prefix_country != registered_country)
+ w2 * I(dominant_infra_country != registered_country)
+ w3 * I(last_stable_country != registered_country)
+ w4 * foreign_prefix_coverage_ratio
```

#### `MismatchScore`

综合地理冲突、行政冲突和行为异常：

```text
MismatchScore =
a1 * admin_conflict_flag
+ a2 * GeoMismatchScore
+ a3 * topology_anomaly_flag
+ a4 * border_as_flag
- a5 * explainable_business_flag
```

其中：

```text
explainable_business_flag = 1
```

表示：

* 跨国集团
* 云厂商
* CDN
* 骨干网
* 公开租赁 / 托管

这些对象需要降权。

---

## 6. 分类输出逻辑

### 分类一：正常边界型自治系统

* 边界型明显
* 但注册国、主前缀国、主设施国基本一致
* 或存在明确合理解释

### 分类二：可解释跨国运营自治系统

* 存在异国特征
* 但可由业务结构解释
* 如跨国云厂商、CDN、骨干网

### 分类三：疑似离岸运营自治系统

* 行政、静态地理、路径、设施多个层面共同偏离注册国
* 且缺乏合理解释

### 分类四：证据不足待复核

* 证据链不闭合
* 测量数据不充分
* 存在冲突但无法稳定确认

---

## 7. 最终结果表设计

#### `asn_case_final`

```text
asn
month
allocated_country
registered_country
dominant_prefix_country
dominant_infra_country
last_stable_country
admin_conflict_flag
geo_conflict_flag
topology_anomaly_flag
border_as_flag
GeoMismatchScore
MismatchScore
final_label
evidence_summary
review_status
reviewer_note
```

### `final_label` 建议取值

```text
normal_border_as
explainable_crossborder
suspected_offshore_like
insufficient_evidence
```

---

## 8. 人工复核闭环

这一步不能省。

系统自动化做的是：

* 生成候选
* 汇总证据
* 排优先级

人工复核做的是：

* 检查是否有合理解释
* 检查地理库误差
* 检查 traceroute 异常
* 检查设施 presence 是否过旧或缺失

所以最终流程不是：

```text
自动评分 -> 直接定性
```

而是：

```text
自动评分 -> 案例卡 -> 人工复核 -> 最终标签
```

这也和你前面已经确定的闭环一致。

---

# 一句技术性概括

你可以把整套技术方案概括成：

> 系统以 AS-月 为统一分析单位，先从 RIR delegated stats 与 RDAP/WHOIS 构建行政注册基线，再从起源前缀与多库地理映射构建静态运营地画像，同时结合 RIPEstat 与 CAIDA AS Rank 形成月度连接结构画像；在此基础上构建第一阶段嫌疑自治系统集合，并对高优先级目标进一步执行多探针路径测量与设施 presence 核查，最终通过多源证据融合、评分与人工复核输出自治系统注册地与运营地不一致的确认结果。

下一步最合适的是，我直接把这版继续展开成 **模块接口级别**，也就是：

* 输入 JSON 结构
* 数据表 DDL
* 每个模块的伪代码
* 每一步的阈值配置文件格式。
