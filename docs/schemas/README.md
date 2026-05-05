# 拆分 Schema 说明

状态：active

本目录保存仍然有效的细分字段契约和语义约束。`docs/schema.md` 是总览入口；当实现或修改某个具体源域时，应同时查阅本目录对应文件。

当前文件：

- `schema_registry.md`：registry staging 输出契约。
- `schema_links.md`：links staging 输出契约。
- `schema_prefixes.md`：prefix inventory staging 输出契约。
- `schema_stage1.md`：stage1 候选集输出契约。
- `schema_case_material.md`：人工复核 case material 输出契约。
- `schema_registry_region_changes.md`：五年 delegated 行政分配变化旁线输出契约。

维护规则：

- 新增源域时，优先在本目录补充细分 schema，再更新 `docs/schema.md` 总览。
- 字段、语义边界或禁止解释发生变化时，必须同步更新对应细分 schema。
- 过期且已被完整替代的 schema 才能移动到 `docs/archive/`。
