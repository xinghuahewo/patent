# 执行计划（v1）

## 1. 目标

将“ASN 注册地与运营地不一致识别”的方法落地为一套文件优先的离线工程流水线。

本阶段目标不是自动做出最终认定，而是：

1. 形成统一工程骨架；
2. 建立可回溯的原始证据采集与标准化流程；
3. 构建第一阶段嫌疑集；
4. 为后续设施确认、路径确认和人工复核提供结构化输入。

---

## 2. 分析单位

统一分析单位为：

- `(asn, month)`

其中：
- `asn`：自治系统编号
- `month`：格式固定为 `YYYY-MM`

所有输出文件、聚合逻辑、评分逻辑和案例卡都应围绕这一分析单位组织。

---

## 3. 工程范围

### 3.1 v1 优先实现
v1 先实现：

- 工程骨架
- 配置文件
- 输入样例
- schema 文档
- 统一校验器
- registry 数据采集与标准化
- links 数据采集与标准化
- 第一阶段嫌疑集构建

### 3.2 v1 暂不优先
以下内容放在后续阶段：

- 全量 traceroute / Paris traceroute
- 设施与路径的大规模确认
- 数据库服务化
- 可视化平台
- 自动最终裁定

---

## 4. 数据分层

### raw
用于保存原始证据。

特征：
- 只追加
- 不覆盖
- 保存原始响应
- 保存抓取元数据

### staging
用于保存单源标准化结果。

特征：
- 只做单源清洗
- 不做跨源融合
- 不做最终标签

### curated
用于保存融合结果。

特征：
- 可做多源融合
- 可做嫌疑集构建
- 可做评分与标签建议

### reports
用于保存给人看的材料。

特征：
- 案例卡
- 试点报告
- 人工复核材料

---

## 5. 目录契约

约定目录如下：

- `configs/`
- `data/input/`
- `data/raw/`
- `data/staging/`
- `data/curated/`
- `reports/`
- `scripts/`
- `tests/`
- `docs/`

后续实现默认遵循这一目录契约，不应随意更改。

---

## 6. 时间语义

不同证据必须区分以下时间字段：

- `analysis_month`
- `observation_time`
- `fetch_time`
- `window_start`
- `window_end`

其中：
- `analysis_month` 表示归属月份
- `observation_time` 表示外部数据的观测时间
- `fetch_time` 表示本系统抓取时间
- `window_start/window_end` 表示聚合窗口范围

不得混淆这些时间语义。

---

## 7. 数据获取设计

### 7.1 registry 类
用于建立行政注册基线。

优先数据源：
- delegated / delegated extended
- RDAP
- WHOIS

目标：
- 获取原始注册与分配信息
- 建立 allocated_country / registered_country / rir / org_name 等基础字段

### 7.2 links 类
用于建立连接结构画像。

优先数据源：
- RIPEstat neighbours
- CAIDA AS Rank

目标：
- 获取 observed neighbours、关系类型和结构摘要
- 计算邻居数量、provider 数量、neighbor churn、provider switch 等指标

### 7.3 后续数据源
后续阶段可引入：

- BGP 前缀与 Geo 数据
- PeeringDB / facility / IXP
- traceroute / Paris traceroute

但这些不是 v1 第一优先级。

### 7.4 当前新增试点：本机 bview 前缀集合缓存

为避免每次查询都重新解析整份 `bview`，当前新增一个更小的单源步骤：

- 使用本机 `rrc25` 月末 `bview.*.gz`
- 先按国家子集一次性扫描并缓存前缀集合
- 当前默认试点国家为 `IR`
- 当前 ASN 子集来源为 `/home/experiment/info/as_entity.csv`

这一层只输出前缀集合缓存，不直接输出 `dominant_prefix_country`。

---

## 8. 关键方法约束

在实现中必须遵守以下规则：

1. 不得直接用邻居国家推断运营国家
2. `dominant_prefix_country` 不应单独等于最终运营地
3. 行政冲突、静态地理冲突、结构异常应分开处理
4. 边界型 ASN 不能自动视为异常
5. 云厂商、CDN、骨干网、跨国集团应考虑解释性降权
6. 自动评分不替代人工复核

---

## 9. v1 核心输出

### 9.1 registry 基线
输出：
- `asn_registry_baseline_monthly`

### 9.2 links 画像
输出：
- `asn_link_summary_monthly`

### 9.3 stage1 嫌疑集
输出：
- `asn_suspect_stage1`

---

## 10. 推荐实现顺序

### Step 1：工程骨架与校验器
实现：
- 目录结构
- `configs/pipeline.yaml`
- `data/input/asn_months.csv`
- schema 文档
- `scripts/validate_outputs.py`

### Step 2：registry 原始数据获取
实现：
- `scripts/collect_registry.py`

要求：
- 保存原始 delegated / RDAP / WHOIS 结果
- 保存抓取日志与 metadata
- raw 层只追加

### Step 3：registry 标准化
实现：
- `scripts/stage_registry.py`

要求：
- 输出 `asn_registry_baseline_monthly`
- 统一字段与类型
- 形成行政冲突相关标记

### Step 4：links 原始数据获取
实现：
- `scripts/collect_links.py`

要求：
- 保存 RIPEstat / AS Rank 原始结果
- 保存元数据与哈希

### Step 5：links 标准化
实现：
- `scripts/stage_links.py`

要求：
- 输出 `asn_link_summary_monthly`
- 计算结构摘要指标
- 不做运营国家推断

### Step 6：构建第一阶段嫌疑集
实现：
- `scripts/build_stage1_suspects.py`

要求：
- 融合 registry 和 links 结果
- 为后续接入 prefix_geo 留出接口
- 输出 `asn_suspect_stage1`

### Step 5.5：本机 bview 前缀集合缓存
实现：

- `scripts/collect_prefixes.py`
- `scripts/stage_prefixes.py`

要求：

- 不从网上下载 MRT 文件
- 从 `/home/bgpdata/data/ripe/rrc25/YYYY.MM/` 选择当月最后一个 `bview`
- 用 `as_entity.csv` 选出目标国家 ASN 子集
- 对整份 `bview` 只扫描一次
- 为每个 `(asn, month)` 落 raw evidence 和 staging
- 暂不接入 geo 和最终评分

---

## 11. 公共字段约束

所有核心输出记录应尽量包含：

- `record_id`
- `run_id`
- `schema_version`
- `parser_version`
- `asn`
- `analysis_month`
- `raw_evidence_path`
- `raw_evidence_sha256`

如果阶段不适用，应明确说明。

---

## 12. 输入输出约束

### 输入
主输入文件：

- `data/input/asn_months.csv`

固定字段：
- `asn`
- `month`

### 输出
所有阶段都必须把结果落盘到指定目录，不应只返回终端输出。

---

## 13. 校验要求

校验器应至少检查：

- 文件是否存在
- 必填字段是否齐全
- ASN 格式是否合法
- month 格式是否正确
- 国家码格式是否合理
- `run_id/schema_version/parser_version` 是否存在
- `raw_evidence_path` 和 `raw_evidence_sha256` 是否存在

后续还应支持证据链校验。

---

## 14. 测试要求

至少应覆盖：

- 输入文件解析
- 时间格式校验
- 国家码格式校验
- registry 字段解析
- links 关系归一化
- churn / provider switch 计算
- stage1 优先级分层

---

## 15. 完成定义

一个阶段任务只有在以下条件都满足时才算完成：

1. 脚本已实现
2. 脚本可运行
3. 输出文件落到正确目录
4. 输出字段符合 schema
5. 测试通过
6. 校验通过
7. 文档已同步更新
8. 结果可回溯到 raw evidence

---

## 16. 当前建议

当前最建议优先完成：

1. `configs/pipeline.yaml`
2. `data/input/asn_months.csv`
3. `scripts/validate_outputs.py`
4. `scripts/collect_registry.py`
5. `scripts/stage_registry.py`
6. `scripts/collect_links.py`
7. `scripts/stage_links.py`
8. `scripts/build_stage1_suspects.py`

在第一阶段嫌疑集稳定前，不建议优先实现更复杂的确认阶段。
