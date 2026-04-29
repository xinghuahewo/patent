# 目录整理说明

状态：archived

归档原因：目录与 Git 收纳规则已合并到 `docs/runbook.md`。本文只作为旧整理说明背景参考。

本文说明当前仓库目录边界，避免源码、运行产物和分析报告继续混在一起。

## 应进入 Git 的内容

- `AGENTS.md`：工程规则和执行约束。
- `README.md`：项目入口和快速运行命令。
- `configs/`：可复用配置。
- `docs/`：schema、执行计划、当前状态、工程流转说明。
- `scripts/`：采集、标准化、融合、校验脚本。
- `tests/`：单元测试和规则测试。
- `data/input/asn_months.csv`：小规模样例输入。
- 各运行目录下的 `.gitkeep`。

## 默认不进入 Git 的内容

- `data/raw/`：原始证据和下载缓存，可能很大，只追加保留在本机。
- `data/staging/`：标准化中间表，可由 raw 和脚本重建。
- `data/curated/`：融合结果和候选集，可重建。
- `reports/`：运行报告、case card、矩阵 CSV 和校验报告。
- `logs/`：运行日志。
- Python 缓存、pytest 缓存、临时文件、`.codex/`。

## 当前主线和旁线

日常主线：

```text
data/input/asn_months.csv
  -> data/raw/{registry,links,prefixes}
  -> data/staging/{registry,links,prefixes}
  -> data/curated/stage1
```

独立分析旁线：

```text
data/raw/registry/delegated_monthly_go
  -> data/staging/registry/asn_delegated_monthly.*
  -> data/curated/registry/asn_region_*.*
  -> reports/asn_region_changes
```

旁线用于五年 delegated 行政分配变化分析，不直接等同于“运营地异常”裁定。

## 清理原则

- 不删除 raw evidence。
- 不覆盖 staging/curated 结果，除非明确重新运行同一阶段。
- 大文件只保留本机路径和说明，不提交到 Git。
- 文档中只保留当前有效命令；历史试跑日志留在 `logs/` 或 `data/raw/_logs/`。
