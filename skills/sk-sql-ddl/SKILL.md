# SKILL: sk-sql-ddl — 生成 Hive 建表语句

## 这是什么

给一份结构化的表设计（契约 `model_design`），产出一段可以直接执行的 `CREATE TABLE` 语句。

**不是**什么：不做维度建模决策，不猜分区字段，不决定分桶键。这些必须由上游契约给出；
缺字段就失败，不要"合理推断"。

## 输入

见 `schema.json`。最小区分为 `table_name`、`comment`、`columns[]`、`partitioned_by[]`。

## 输出

纯文本 SQL，单条语句，UTF-8。

## 硬规则

1. 必须显式 `COMMENT`（表级 + 每个字段级），缺少则失败。
2. 必须 `STORED AS` 写明格式，默认 `ORC`，但要来自输入，不来自我的偏好。
3. 分区字段不得同时出现在非分区列里。
4. 列名只允许 `[a-z][a-z0-9_]*`。
5. 不生成 `DROP TABLE`、不生成 `TRUNCATE`、不加 `LOCATION`（路径由调度侧管理）。
6. 保留字冲突时抛错，不自动加反引号掩盖。

## 自检

```bash
python skills/sk-sql-ddl/validate.py --input <契约.json> --sql <产出.sql>
```

校验器只做结构与规则检查（列名、分区重复、注释缺失、语句条数），
**不做语义/AST 分析**；语义校验等 sqlglot 接入后补。

## 失败时怎么办

返回结构化错误 `{ok: false, errors: [...]}`，把判断权交回上游 agent，不要重试着"猜一个"。
