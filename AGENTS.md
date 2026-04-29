# AGENTS.md

## 使用方式

本文只保留自动代理必须遵守的硬规则。详细运行命令、状态、路线和字段契约分别看：

- `docs/worklog.md`：先看这里，确认最近工作记录和下次入口。
- `docs/status.md`：当前状态、有效产物、当前下一步。
- `docs/runbook.md`：运行命令、校验命令、仓库维护规则。
- `docs/roadmap.md`：stage1 之后的长期路线和模块边界。
- `docs/schema.md` 与 `docs/schemas/`：字段契约和语义边界。
- `docs/artifacts.md`：staging / curated 核心产物登记。

开始新任务时，先读 `docs/worklog.md` 最新记录，再读 `docs/status.md`。

## 项目边界

- 文档和注释尽量使用中文。
- 项目目标是文件优先的离线流水线，用于识别“ASN 注册地与运营地可能不一致”的候选对象。
- 自动输出只用于构建嫌疑集、生成评分与案例材料、支持人工复核，不是最终裁定。
- 唯一分析单位是 `(asn, month)`，除非任务明确要求，不要改动。

## 目录与分层

不要随意修改关键目录名：

- `data/raw`：原始证据，只追加，不覆盖。
- `data/staging`：单源标准化结果，不做跨源融合、最终评分或最终标签。
- `data/curated`：融合结果、评分、标签建议。
- `reports`：案例卡、复核材料、试点统计。
- `configs`、`scripts`、`tests`、`docs`：工程配置、脚本、测试和文档。

新增或更新 `data/staging` / `data/curated` 核心产物时，必须同步更新 `docs/artifacts.md`，并尽量写同目录 `*.manifest.json`。

## 方法硬约束

必须严格遵守：

1. 不得直接用邻居国家推断运营国家。
2. `dominant_prefix_country` 仅是静态画像，不是最终运营国。
3. 行政冲突、静态地理冲突、连接结构异常必须分开处理。
4. 自动评分不能替代人工复核。
5. 边界型 ASN 不应自动判为异常。
6. 云厂商、CDN、骨干网、跨国集团需要解释性降权。

## 脚本职责

- `collect_*`：只获取数据、保存 raw evidence、记录 metadata 和抓取日志。
- `stage_*`：只做单源清洗、字段标准化和单源摘要指标。
- `build_*`：才允许做多源融合、嫌疑集构建、评分和标签建议。
- `validate_*` / `check_*`：只做校验，不改变业务产物。

所有阶段必须落盘到预定义目录，不要只打印结果。

## 编码要求

- 优先 Python 3.11+。
- 函数尽量带类型注解。
- I/O 与纯计算尽量分离。
- 大文件不要一次性全量读入内存。
- schema 不匹配时要显式报错。
- BGP AS_PATH 解析只接受合法单 ASN token，不要把 AS_SET 错误拼接成异常大整数。

## 完成前验证

任务完成前尽量运行：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all
```

如果某命令不适用或当前环境无法运行，必须在最终回复中明确说明。

## 完成定义

一个任务通常只有满足以下条件才算完成：

1. 代码或文档已实现。
2. 输出落到正确目录，字段符合 schema。
3. 测试和校验通过，或明确说明未运行原因。
4. 结果可回溯到 raw evidence。
5. 关键产物已更新 `docs/artifacts.md` 或 manifest。
6. 如修改源码、脚本、测试、配置、CI 或关键文档，已同步更新 `docs/worklog.md`。

## 执行偏好

- 先查现有文件和文档，再改代码。
- 新源域按 `schema -> collect -> stage -> validator -> build/report` 顺序推进。
- 任务过大时主动拆分，不要一次做难以验证的大改动。
- 长时间任务要有进度条或日志记录。
