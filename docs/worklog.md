# 工作日志

状态：active

角色：固定接手入口。每次完成一个任务或改变下一步时，都要在这里补一条最新记录。下次打开仓库时，先读本文，再读 `docs/status.md`、`docs/runbook.md` 和相关代码。

维护规则：

- 每次修改源码、脚本、测试、配置、CI 或关键文档时，必须新增一条“最近一次工作记录”。
- 记录必须写清楚：做了什么、改了哪些文件、验证结果、遗留问题、下次先看哪里。
- 不在这里复制长日志；长日志保留在 `logs/` 或 `reports/`，本文只写路径和结论。
- 如果只是生成大产物，不进 Git，也要记录产物路径和校验命令。

## 当前接手入口

当前仓库文档入口已经拆成：

- `docs/worklog.md`：先看这里，确认最近一次改动和下次入口。
- `docs/status.md`：当前状态、有效产物、下一小步。
- `docs/runbook.md`：当前可运行命令、校验命令和维护规则。
- `docs/roadmap.md`：stage1 之后的长期路线。
- `docs/schema.md` 与 `docs/schemas/`：字段契约和语义边界。
- `docs/artifacts.md`：staging / curated 核心产物登记。

当前主线仍是 `registry + links + prefixes + prefix_geo -> stage1`。当前下一小步仍围绕已生成的 `prefix_geo` / `stage1` 候选做人工复核材料或解释增强，不要直接扩到 path、infra 或平台化 case report。

## 最近一次工作记录

### 2026-05-05：对 35 条 case 候选补跑 RDAP registry 证据

任务背景：

- 用户确认下一步应直接补证，不继续绕报告模板。
- 目标只针对 `reports/case_material/IR_2026-03/review_queue.csv` 中 `35` 条候选补 registry / RDAP 证据，不扩国家、不扩月份、不进入 path / infra。

本次完成：

- 从 `review_queue.csv` 生成临时输入 `data/input/asn_months_case_IR_2026-03.csv`。
- 运行在线 registry 采集：`python3 scripts/collect_registry.py --online --input data/input/asn_months_case_IR_2026-03.csv`。
- 发现 RIPE RDAP 返回的实体地址里有国家名称 label，但现有解析器只接受两位国家码，导致 `registered_country` 没有填充。
- 修复 `scripts/collect_registry.py`，从 RDAP vCard `adr` 的 `label` 中解析常见国家名别名，例如 `GREECE -> GR`、`IRAN, ISLAMIC REPUBLIC OF -> IR`。
- 新增对应单元测试。
- 重新补跑 35 条 RDAP，重建 registry staging、stage1 和 case material。

涉及文件：

- `scripts/collect_registry.py`
- `tests/test_staging_normalization.py`
- `docs/status.md`
- `docs/artifacts.md`
- `docs/worklog.md`

生成或更新产物：

- `data/raw/registry/manifest/*_20260505T1437*.json`
- `data/raw/registry/rdap/*_manual_2026_04_23_01*.json`
- `data/raw/_logs/collect_registry_manual_2026_04_23_01_20260505T143837Z.json`
- `data/staging/registry/asn_registry_baseline_monthly.csv`
- `data/curated/stage1/asn_suspect_stage1.csv`
- `reports/case_material/IR_2026-03/`

结果：

- 35 条候选 RDAP 请求全部成功。
- 修复解析后，35 条 case 候选中 `registered_country` 非空 `31` 条，仍缺失 `4` 条：`212328`、`61176`、`205997`、`216125`。
- registry 全表仍为 `827` 行，`registered_country` 非空从此前 `2` 条提升到 `33` 条。
- case material 重建后仍为 `35` 条：`medium_review=9`、`low_review=26`、`high_review=0`。

验证结果：

```bash
pytest -q tests/test_staging_normalization.py tests/test_case_material.py
python3 -m py_compile scripts/collect_registry.py
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- 局部测试：21 passed
- `py_compile`：passed
- `check_repo_rules.py`：passed
- `pytest -q`：37 passed
- `validate_outputs.py --stage all --no-progress`：registry、links、prefixes、prefix_geo、stage1 全部 ok

遗留问题：

- `212328`、`61176`、`205997`、`216125` 的 RDAP 响应仍未提供可解析国家，后续若要继续补证，应考虑 whois 或 RIR 组织对象补充，不要把 delegated country 当 registered country。
- `high_review` 仍为 `0`，说明补证后仍未出现同时满足高优先级阈值的候选；这不是正常/异常裁定。

下次打开先看：

1. `reports/case_material/IR_2026-03/review_queue.csv`
2. `reports/case_material/IR_2026-03/cases/`
3. `scripts/collect_registry.py` 的 RDAP country label 解析逻辑

### 2026-05-05：生成 IR 2026-03 case material

任务背景：

- 下一阶段计划要求先把现有 `IR / 2026-03` 的 `35` 条 `geo_conflict_flag=true` 候选整理成人工复核材料，不扩展 path、infra、其他国家或月份。

本次完成：

- 新增 `scripts/build_case_material.py`，从 stage1、prefix_geo、registry、prefix inventory 生成复核队列、summary、manifest 和逐 ASN case card。
- 新增 `tests/test_case_material.py`，覆盖筛选范围、缺失 `registered_country` 不生成最终裁定、`ZZ` / unmapped 多时降级、case card 必须包含“不能说明什么”和 raw evidence 引用。
- 生成 `reports/case_material/IR_2026-03/`：`review_queue.csv` `35` 行，`cases/` `35` 张卡，`medium_review=10`、`low_review=25`、`high_review=0`。
- 新增 `docs/schemas/schema_case_material.md`，并更新 `docs/schema.md`、`docs/schemas/README.md`、`docs/artifacts.md`、`docs/runbook.md`、`docs/status.md`。
- 修正 `docs/schemas/schema_stage1.md` 中 prefix_geo 仍是后续接入的旧表述。

涉及文件：

- `scripts/build_case_material.py`
- `tests/test_case_material.py`
- `docs/schema.md`
- `docs/schemas/README.md`
- `docs/schemas/schema_case_material.md`
- `docs/schemas/schema_stage1.md`
- `docs/artifacts.md`
- `docs/runbook.md`
- `docs/status.md`
- `docs/worklog.md`

生成产物：

- `reports/case_material/IR_2026-03/summary.md`
- `reports/case_material/IR_2026-03/review_queue.csv`
- `reports/case_material/IR_2026-03/manifest.json`
- `reports/case_material/IR_2026-03/cases/`

验证结果：

```bash
python3 scripts/build_case_material.py --country IR --month 2026-03
python3 -m py_compile scripts/build_case_material.py
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- `build_case_material.py`：saved `35` case material rows
- `py_compile`：passed
- `check_repo_rules.py`：passed
- `pytest -q`：35 passed
- `validate_outputs.py --stage all --no-progress`：registry、links、prefixes、prefix_geo、stage1 全部 ok

遗留问题：

- 当前 `registered_country` 覆盖不足，导致本次没有 `high_review`；这只是证据状态和复核优先级，不是正常/异常结论。
- path / infra 证据仍未进入正式流水线。

下次打开先看：

1. `reports/case_material/IR_2026-03/summary.md`
2. `reports/case_material/IR_2026-03/review_queue.csv`
3. `docs/schemas/schema_case_material.md`

### 2026-05-05：补充任务类型收口清单

任务背景：

- 用户指出一次任务后可能需要改很多文件，担心靠记忆会漏。

本次完成：

- 在 `docs/runbook.md` 新增“任务类型收口清单”。
- 按任务类型列出必须检查或更新的文件：所有非纯查询任务、新源域、融合逻辑、报告/case material、执行命令或仓库规则、长期路线、字段语义。
- 明确以后按清单收口，不靠记忆判断要改哪些文件。

涉及文件：

- `docs/runbook.md`
- `docs/worklog.md`

验证结果：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- `check_repo_rules.py`：passed
- `pytest -q`：31 passed
- `validate_outputs.py --stage all --no-progress`：registry、links、prefixes、prefix_geo、stage1 全部 ok

遗留问题：

- `scripts/check_repo_rules.py` 目前只能自动检查其中一部分规则；任务类型清单仍需要执行者按 runbook 人工核对。

下次打开先看：

1. `docs/worklog.md` 最新记录。
2. `docs/runbook.md` 的“任务类型收口清单”。
3. `docs/status.md` 的“当前缺口”和“下一步”。

### 2026-04-29：收尾前更新 gitignore 并准备提交

任务背景：

- 用户要求更新 `.gitignore` 并提交今天的仓库整理工作。

本次完成：

- 更新 `.gitignore`，将 `data/input` 改成显式白名单：只跟踪 `asn_months.csv` 和 `asn_months_registry_IR_2026-03.csv`，避免后续误提交临时或大输入文件。
- 确认 raw、staging、curated、reports、logs、缓存和 npm 占位文件继续被忽略。

涉及文件：

- `.gitignore`
- `docs/worklog.md`

验证结果：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- `check_repo_rules.py`：passed
- `pytest -q`：31 passed
- `validate_outputs.py --stage all --no-progress`：registry、links、prefixes、prefix_geo、stage1 全部 ok

遗留问题：

- 无。

下次打开先看：

1. `docs/worklog.md` 最新记录。
2. `docs/status.md` 的“当前缺口”和“下一步”。

### 2026-04-29：精简 AGENTS 代理规则

任务背景：

- 用户指出 `AGENTS.md` 内容偏多，和 `docs/runbook.md`、`docs/status.md`、`docs/artifacts.md` 有重复。

本次完成：

- 将 `AGENTS.md` 精简为代理硬规则和文档索引。
- 删除 v1 旧计划、长字段说明和重复的完成定义细节，改由 `docs/runbook.md`、`docs/schema.md`、`docs/artifacts.md` 承接。
- 保留关键约束：先读 `docs/worklog.md`，保持 `(asn, month)`，遵守 raw/staging/curated 分层，完成前运行规则检查、测试和主线校验。

涉及文件：

- `AGENTS.md`
- `docs/worklog.md`

验证结果：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- `check_repo_rules.py`：passed
- `pytest -q`：31 passed
- `validate_outputs.py --stage all --no-progress`：registry、links、prefixes、prefix_geo、stage1 全部 ok

遗留问题：

- 无。

下次打开先看：

1. `docs/worklog.md` 最新记录。
2. `docs/status.md` 的“当前缺口”和“下一步”。

### 2026-04-29：同步 AGENTS 接手规则

任务背景：

- 用户询问新增 worklog / CI 规则后是否需要更新 `AGENTS.md`。

本次完成：

- 更新 `AGENTS.md`，要求新任务先读 `docs/worklog.md`，任务完成前运行 `python3 scripts/check_repo_rules.py`，并在修改源码、脚本、测试、配置、CI 或关键文档时同步更新 worklog。
- 将测试与校验命令统一为 `python3`。

涉及文件：

- `AGENTS.md`
- `docs/worklog.md`

验证结果：

```bash
python3 scripts/check_repo_rules.py
python3 -m py_compile scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- `check_repo_rules.py`：passed
- `py_compile`：passed
- `pytest -q`：31 passed
- `validate_outputs.py --stage all --no-progress`：registry、links、prefixes、prefix_geo、stage1 全部 ok

遗留问题：

- 无。

下次打开先看：

1. `docs/worklog.md` 最新记录。
2. `docs/status.md` 的“当前缺口”和“下一步”。

### 2026-04-29：补齐仓库规则检查与 CI

任务背景：

- 用户指出新增文件缺少强制规则，选择用 Git / CI 卡住。

本次完成：

- 新增 `scripts/check_repo_rules.py`，检查文档入口、archive 状态、schema 登记、核心产物登记和 Git 大产物边界。
- 新增 `.github/workflows/quality.yml`，push / PR 时运行仓库规则检查和 `pytest -q`。
- 更新 `README.md`、`docs/runbook.md`、`docs/status.md`，加入规则检查命令。
- 补齐 `docs/artifacts.md` 中 Parquet 与 registry history curated 产物登记。
- 将文档结构调整为 `status.md`、`runbook.md`、`roadmap.md`、`schema.md`、`schemas/`、`artifacts.md`、`archive/`。

验证结果：

```bash
python3 scripts/check_repo_rules.py
pytest -q
python3 scripts/validate_outputs.py --stage all --no-progress
```

结果：

- `check_repo_rules.py`：passed
- `pytest -q`：31 passed
- `validate_outputs.py --stage all --no-progress`：registry、links、prefixes、prefix_geo、stage1 全部 ok

遗留问题：

- CI 不跑 `validate_outputs.py --stage all`，因为 GitHub runner 没有本机 `/home/bgpdata` bview 和本机生成的 staging / curated 产物。
- `docs/worklog.md` 本次新增后，后续每次改动都必须更新；PR 场景下规则检查可强制要求 worklog 变化。

下次打开先看：

1. `docs/worklog.md` 的最新一条记录。
2. `docs/status.md` 的“下一步”。
3. 如果要做代码改动，先跑 `python3 scripts/check_repo_rules.py` 确认规则基线干净。

## 下次打开先做什么

默认顺序：

1. 读 `docs/worklog.md` 最新记录。
2. 读 `docs/status.md` 的“当前缺口”和“下一步”。
3. 若任务涉及执行命令，读 `docs/runbook.md`。
4. 若任务涉及新增源域或字段，读 `docs/schema.md` 与 `docs/schemas/`。
5. 若任务涉及 stage1 后续方向，读 `docs/roadmap.md`。
6. 开始改动前先跑：

```bash
python3 scripts/check_repo_rules.py
```

## 记录模板

### YYYY-MM-DD：一句话任务名

任务背景：

- 

本次完成：

- 

涉及文件：

- 

验证结果：

```bash

```

遗留问题：

- 

下次打开先看：

1. 
