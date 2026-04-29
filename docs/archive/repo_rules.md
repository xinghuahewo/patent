# 仓库维护规则

状态：archived

归档原因：维护规则已合并到 `docs/runbook.md`，长期路线已收口到 `docs/roadmap.md`。本文只作为旧规则背景参考。

本规则用于防止仓库在持续采集、分析和报告迭代中再次变乱。后续新增功能、数据源或专题分析时，默认遵守本文。

## 1. 先判定主线或旁线

任何新任务开始前，必须先判定它属于：

- 主线：会长期进入 stage1 流水线的证据源或融合逻辑，例如 registry、links、prefix_geo。
- 旁线：一次性或专题分析，例如五年 delegated 行政分配变化分析。

主线可以进入 `docs/project_flow.md` 的日常流程。旁线必须有独立入口文档或独立章节，不得直接混进 stage1 主流程。

## 2. README 只做入口页

`README.md` 只保留：

- 项目目标
- 当前入口文档
- 目录结构
- 最小可运行命令
- 当前下一步

不要在 README 中堆历史进展、长日志、试跑记录、临时结论或大段分析报告。

## 3. 当前状态只收口到一个文件

当前进度、有效产物、验证状态和下一步统一写入：

```text
docs/current_status.md
```

任务结束时，如果改变了流程、产物、验证结果或下一步，必须更新这个文件。

旧状态文件、聊天记录、日志和报告不能作为唯一进度来源。

## 4. 每个新源域按固定模板落地

新增一个源域时，默认使用以下结构：

```text
docs/schema_xxx.md
scripts/collect_xxx.py
scripts/stage_xxx.py
data/raw/xxx/
data/staging/xxx/
```

只有当该源域完成 raw -> staging -> validator 后，才允许接入 `scripts/build_stage1_suspects.py`。

如果该源域只是专题分析，不进入 stage1，则必须在文档中明确写明“独立分析旁线”。

## 5. 大产物不进 Git

默认不进入 Git：

- `data/raw/`
- `data/staging/`
- `data/curated/`
- `reports/`
- `logs/`

这些目录中的文件可以保留在本机，但提交时只记录：

- 生成脚本
- 输入路径
- 输出路径
- 校验命令
- 小规模摘要或 README

不得把大 CSV、Parquet、raw dump、日志当作源码提交。

## 6. 校验必须分层

日常主线校验保持快速：

```bash
pytest -q
python3 scripts/validate_outputs.py --stage all
```

`--stage all` 只覆盖日常 stage1 主线。大分析、大表、历史任务必须单独设 stage，例如：

```bash
python3 scripts/validate_outputs.py --stage registry_history
```

以后新增 path、infra 或其他重型任务，也不得直接塞进默认 `all`。

## 7. 文档更新边界

不同文档职责如下：

- `README.md`：入口页。
- `docs/current_status.md`：当前状态和下一步。
- `docs/project_flow.md`：长期工程数据流。
- `docs/directory_layout.md`：目录边界和 Git 收纳规则。
- `docs/schema_*.md`：字段契约。
- `reports/`：运行报告和人工复核材料。

不要在多个文件里重复维护同一份状态说明。

## 8. 任务完成前检查

每个任务完成前至少检查：

1. 是否新增了主线或旁线入口。
2. 是否更新了 `docs/current_status.md`。
3. 是否把大产物留在 Git 忽略范围内。
4. 是否运行了对应测试和校验。
5. 是否说明了未完成项和下一步。

如果任务只产生一次性报告，也必须写明输入、脚本、输出和校验结果。
