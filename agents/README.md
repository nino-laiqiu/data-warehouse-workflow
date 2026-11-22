# agents/ —— 角色与权责

一个 agent 定义的是**谁有权做什么**，不是"怎么做好"。后者属于 skills 与 knowledge。

## 为什么要拆这么细

如果同一个 agent 既写本体又审本体，它就有动机让自己的输出过关。所以写权限与审权限必须落在不同角色上。这是流程的信任基础，不是官僚主义。

## 角色矩阵

| 角色 | 能写 | 只读 | 禁止 |
|---|---|---|---|
| `orchestrator` | `runs/`、`memory/` | 全部 | 改本体、写 SQL |
| `req-analyst` | P1 需求单 | 本体、知识库 | 直接写 SQL |
| `ontology-admin` | `ontology/`（唯一） | 全部 | 写 SQL、改知识库 |
| `modeler` | P3 模型设计 | 本体、知识库 | 直接改本体（只能提 delta） |
| `metric-admin` | P4 指标定义 | 本体、P3 | 自定义口径不落本体 |
| `developer` | P5 SQL、P6 DQ | 本体、知识库、契约 | 改口径、改门禁 |
| `quality-officer` | P6 规则、GA3 报告 | 全部 | 改 SQL 让其通过 |
| `auditor` | 门禁报告 | 全部 | 任何写入 |

关键约束：**只有 `ontology-admin` 写 `ontology/`**。建模师想加维度，提交 `ontology_delta`，由本体管理员评审合并。

## 文件格式

每个 agent 一个 `<role>.md`，开头是 YAML front matter：

```yaml
---
role: modeler
model: default
can_write: [runs/P3_model_design]
mounted_skills: [sk-sql-ddl]
gates: [G2]
---
```

正文写：职责边界、输入输出、什么时候该停下问人（HITL）。

## 与 HITL 的关系

全流程只有 3 个人工卡点：H1 口径确认（P4）、H2 建表评审（P3）、H3 上线放行（P7）。
agent 不得自行增加卡点——卡点一多，人就绕开系统走了。
