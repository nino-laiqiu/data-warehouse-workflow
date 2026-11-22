# agents/ —— 角色与权责

一个 agent 定义的是**谁有权做什么**，不是"怎么做好"。后者属于 skills 与 knowledge。

## 为什么要拆这么细

如果同一个 agent 既写 SQL 又评 SQL，它就有动机让自己的输出过关。B 线用**双轨制**把这件事做到极致：两个人独立做同一件事，再由第三人比对裁决。

## 角色矩阵（11 个）

| 角色 | 能写 | 只读 | 禁止 |
|---|---|---|---|
| `orchestrator` | `runs/`、派活记录 | 全部 | 改本体、写 SQL、改裁决 |
| `requirement-translator` | `requirements/normalized/` | `inbox/`、本体、知识库 | 改原始需求、自定义口径 |
| `chronicler`（追踪者） | `runs/<run_id>/journal.jsonl` | 全部 | 改任何产物、参与决策 |
| `developer-1` | `runs/<run_id>/track-1/` | 翻译稿、本体、知识库 | **读 track-2**、改翻译稿 |
| `developer-2` | `runs/<run_id>/track-2/` | 翻译稿、本体、知识库 | **读 track-1**、改翻译稿 |
| `supervisor`（监督者） | `final/`、`comparison.md`、`verdict.md` | 两轨全部 | 改口径、重写脚本 |
| `ontology-admin` | `ontology/`（唯一） | 全部 | 写 SQL |
| `quality-officer` | `dq_rules` | 全部 | 改 SQL 让其通过 |
| `lineage-steward` | `lineage` | 全部 | 改调度依赖以外的东西 |
| `doc-writer` | 交付文档 | 全部 | 改产物 |
| `analyst-writer`（A 线） | 结论 | 查询结果 | 因果断言、改 SQL |

四条关键约束：

1. **只有 `ontology-admin` 写本体**。别人有意见就提 `ontology_delta`。
2. **双轨必须隔离**：`developer-1` 与 `developer-2` 互不可见。任何一方读取另一轨的目录视为违规，`chronicler` 会记录。
3. **追踪者只写不判**：它记录一切，但不参与决策。让它评判，它就会记录对自己有利的版本。
4. **监督者不改口径**：发现两边口径不一致，退回 P1 翻译，不许自己拍一个。

## 文件格式

每个 agent 一个 `<role>.md`，开头是 YAML front matter：

```yaml
---
role: developer-1
model: default
can_write: [runs/<run_id>/track-1]
mounted_skills: [sk-sql-ddl, sk-sql-dml, sk-sql-guard]
gates: [G2]
reads: [requirements/normalized, ontology, knowledge]
must_not_read: [runs/<run_id>/track-2]
---
```

正文写：职责边界、输入输出、什么时候该停下问人。

## 与 HITL 的关系

全流程只有 3 个人工卡点：

| 卡点 | 位置 | 人在决定什么 |
|---|---|---|
| H1 口径确认 | P1 翻译完成 | "这个口径对吗" |
| H2 方案裁决评审 | P3 比对完成 | "选 A 还是合，理由成立吗" |
| H3 上线放行 | P5 血缘调度后 | "能不能上生产" |

agent 不得自行增加卡点——卡点一多，人就绕开系统走了。
