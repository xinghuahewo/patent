# AGENTS.md

## 项目目标
实现一个文件优先的离线流水线，用于识别“ASN 注册地与运营地可能不一致”的候选对象。

本项目的自动输出只用于：
- 构建嫌疑集
- 生成评分与案例材料
- 支持后续人工复核

自动结果不是最终裁定。

---

## 分析单位
唯一分析单位为：

- `(asn, month)`

其中：
- `asn` 为整数 ASN
- `month` 格式固定为 `YYYY-MM`

除非任务明确要求，不要改动这个分析单位。

---

## 目录契约
- `data/raw`：原始证据
- `data/staging`：单源标准化结果
- `data/curated`：融合结果、评分、标签建议
- `reports`：案例卡和人工复核材料
- `configs`：配置文件
- `scripts`：执行脚本
- `tests`：测试

不要随意修改这些关键目录名称。

---

## 分层规则
### raw
- 只追加，不覆盖
- 保存原始响应、抓取状态、抓取时间、来源和哈希

### staging
- 只做单源标准化
- 不做跨源融合
- 不做最终评分
- 不做最终标签建议

### curated
只允许在这一层做：
- 跨源融合
- 第一阶段嫌疑集构建
- 评分
- 标签建议

### reports
输出给人看的材料：
- Markdown/HTML 案例卡
- 复核材料
- 试点统计

---

## 硬性方法约束
以下规则必须严格遵守：

1. 不得直接用邻居国家推断运营国家
2. `dominant_prefix_country` 仅是静态画像，不是最终运营国
3. 行政冲突、静态地理冲突、连接结构异常必须分开处理
4. 自动评分不能替代人工复核
5. 边界型 ASN 不应自动判为异常
6. 云厂商、CDN、骨干网、跨国集团需要解释性降权

---

## 公共字段要求
所有核心输出记录应尽量包含：

- `record_id`
- `run_id`
- `schema_version`
- `parser_version`
- `asn`
- `analysis_month`
- `raw_evidence_path`
- `raw_evidence_sha256`

如某阶段确实不适用，需要明确说明原因。

---

## v1 优先范围
优先实现以下内容：

1. 工程骨架
2. `configs/pipeline.yaml`
3. `data/input/asn_months.csv`
4. schema 文档
5. `scripts/validate_outputs.py`
6. `scripts/collect_registry.py`
7. `scripts/stage_registry.py`
8. `scripts/collect_links.py`
9. `scripts/stage_links.py`
10. `scripts/build_stage1_suspects.py`

除非任务明确要求，先不要优先实现：
- 全量路径测量
- 数据库服务化
- 复杂平台化功能
- 最终自动裁定

---

## 脚本职责
### collect 脚本
只负责：
- 获取数据
- 保存 raw evidence
- 记录 metadata
- 输出抓取日志

### stage 脚本
只负责：
- 单源清洗
- 字段标准化
- 单源摘要指标

### build 脚本
才允许做：
- 多源融合
- 嫌疑集构建
- 评分
- 标签建议

---

## 输入输出约束
标准输入文件：

`data/input/asn_months.csv`

固定字段：
- `asn`
- `month`

所有阶段都必须落盘到预定义目录，不要只打印结果而不保存文件。

---

## 编码要求
- 优先 Python 3.11+
- 函数尽量带类型注解
- I/O 与纯计算尽量分离
- 大文件不要一次性全量读入内存
- schema 不匹配时要显式报错
- BGP AS_PATH 解析只接受合法单 ASN token
- 不要把 AS_SET 错误拼接成异常大整数

---

## 测试与校验
任务完成前应尽量运行：

- `pytest -q`
- `python scripts/validate_outputs.py --stage all`

如某命令尚未实现，需要明确说明，不要假装已可用。

---

## 完成定义
一个任务只有在以下条件全部满足时才算完成：

1. 代码已实现
2. 代码可运行
3. 输出落到正确目录
4. 输出字段符合 schema
5. 测试通过
6. 校验通过
7. 必要文档已更新
8. 结果可回溯到 raw evidence

---

## 执行偏好
处理复杂任务时，优先顺序为：

1. 阅读 `AGENTS.md`
2. 阅读 `README.md` 和相关 `docs/`
3. 检查现有目录与文件
4. 先补 schema / 校验器 / 样例
5. 再写采集与标准化脚本
6. 每完成一层就验证

如果任务过大，应主动拆分，不要一次做难以验证的大改动。
长时间任务一定要有进度条和日志记录。