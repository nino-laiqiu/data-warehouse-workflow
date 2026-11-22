# contracts/ —— 阶段交付物契约

每个阶段交给下一阶段的东西，必须是**符合 JSON Schema 的结构化文档**，不是一段自然语言。

## 为什么不用自然语言

自然语言交接是幻觉的主要入口。上游说"按天聚合"，下游可能理解成 `dt` 分区，也可能理解成 `event_date` 字段——两边都不算错，但拼起来就是错的。契约把"按天"变成 `"time_grain": "day"` 这个枚举值，缺字段直接硬失败。

## 清单

| 契约 | 线 | 产出阶段 | 消费者 |
|---|---|---|---|
| `intent.schema.json` | A | A1 意图解析 | A2 |
| `analysis.schema.json` | A | A5 结论生成 | 人 |
| `requirement.schema.json` | B | P1 需求受理 | P2 |
| `ontology_delta.schema.json` | B | P2 本体对齐 | 本体管理员 |
| `model_design.schema.json` | B | P3 维度建模 | P4 |
| `metric_spec.schema.json` | B | P4 指标定义 | P5 |
| `dq_rules.schema.json` | B | P6 质量规则 | P7 |
| `lineage.schema.json` | B | P7 血缘调度 | 调度平台 |
| `gate_report.schema.json` | 双线 | 每个门禁 | 编排器 |

## 写法约定

- `additionalProperties: false`：宁可报错，不要静默塞进未知字段。
- 必填字段全列在 `required`，不给"默认值"。
- ID 一律用 `pattern` 约束，不用自由字符串。
- 每个 schema 顶部注释写清"缺了会怎样"。

## 校验

```bash
python tools/validate_contracts.py requirements/<需求目录>/需求开发员/
```

门禁不通过时，编排器不得进入下一阶段——这条没有例外，也没有"先跑起来再说"。
