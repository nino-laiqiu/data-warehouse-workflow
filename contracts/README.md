# contracts/ —— 阶段交付物契约

每个阶段交给下一阶段的东西，必须是**符合 JSON Schema 的结构化文档**，不是一段自然语言。

## 为什么不用自然语言

自然语言交接是幻觉的主要入口。上游说"按天拆分"，下游可能理解成 `dt` 分区，也可能理解成 `event_date` 字段——两边都不算错，但拼起来就是错的。契约把"按天"变成 `"granularity": "day"` 这个枚举值，缺字段直接硬失败。

## 九个设计契约（全部已就位）

| 契约 | 线 | 产出阶段 | 消费者 | 判据（一句话） |
|---|---|---|---|---|
| `intent.schema.json` | A | A1 意图解析 | A2 | 指标/维度都能对到本体 id；阻断歧义不许往下走 |
| `analysis.schema.json` | A | A5 结论生成 | 人 | 每句结论有 evidence；claims 里没有 causal 这个值 |
| `requirement.schema.json` | B | P1 需求翻译 | P2 | 验收标准可断言；阻断问题为零；status=confirmed |
| `ontology_delta.schema.json` | B | P1/P2 本体对齐 | 人（本体只能人改） | 每条变更带 why 与影响面 |
| `model_design.schema.json` | B | P2 双轨开发 | P3 监督者 | 粒度+主键能唯一确定一行；字段有来源 |
| `metric_spec.schema.json` | B | P4 指标定义 | P5 | 口径能落成一条 SQL；加性写清楚 |
| `dq_rules.schema.json` | B | P4 质量规则 | P5 | 每条规则可执行、可机器判定 |
| `lineage.schema.json` | B | P5 血缘调度 | 调度平台 | 无孤立节点、schedule 边不成环、回滚可执行 |
| `comparison_report.schema.json` | B | P3 监督比对 | 人（H2）＋P5 | 差异全覆盖，每条有依据引用 |

每个契约都有示例：`contracts/examples/<name>.example.json`，全部通过 `validate_contracts.py`。

## 附加契约（不属于九个设计契约，但同样强制）

| 契约 | 用途 | 判据 |
|---|---|---|
| `journal_entry.schema.json` | 六类留痕事件（conversation/query/artifact/progress/todo/gate） | 每类必填字段齐；todo 必须有编号 |
| `verification_report.schema.json` | 现网/离线验证报告 | 没有证据不许写 pass；豁免只改签署不改证据 |
| `qa_record.schema.json` | 问答沉淀 | qa_id 唯一、只追加 |
| `qa_ingest_request.schema.json` | 问答采集接口载荷 | 1..500 条/批，ingest 幂等 |
| `_template.schema.json` | 新契约的公共骨架 | run_id + stage + payload |

## 写法约定

- `additionalProperties: false`：宁可报错，不要静默塞进未知字段。
- 必填字段全列在 `required`，不给"默认值"。
- ID 一律用 `pattern` 约束，不用自由字符串。
- 每条 schema 的 `description` 写"判据"，不写"用途"——判据能被执行，用途只能被阅读。

校验器只支持 JSON Schema 的一个子集（`type/required/properties/additionalProperties/enum/pattern/minLength/minItems/maxItems/items/minimum/maximum/$ref/definitions`）。用了不支持的词，校验器会直接报错，而不是忽略——这是故意的。

## 校验

```bash
python tools/validate_contracts.py contracts/examples/model_design.example.json --schema contracts/model_design.schema.json

# JSONL（如 journal.jsonl）逐行校验
python tools/validate_contracts.py requirements/<需求目录>/需求开发员/journal.jsonl --lines --schema contracts/journal_entry.schema.json
```

注意参数顺序：**第一个位置参数是数据文件**，schema 用 `--schema` 指定（写反了会把 schema 当数据校验，报一堆看不懂的错）。

门禁不通过时，编排器不得进入下一阶段——这条没有例外，也没有"先跑起来再说"。
