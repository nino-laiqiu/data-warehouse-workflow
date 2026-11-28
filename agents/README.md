# agents/ —— 角色与权责

一个 agent 定义的是**谁有权做什么**，不是"怎么做好"。后者属于 skills 与 knowledge。

## 为什么要拆

如果同一个 agent 既写 SQL 又评 SQL，它就有动机让自己的输出过关。B 线用**双轨制**把这件事做到极致：两个人独立做同一件事，再由第三人比对裁决。

## 为什么是 5 个

编制 = 需求分析员、开发者 1、开发者 2、监督者、追踪者。这五个是**不可合并**的：

- 开发者 1 与 2 必须互相看不见，否则会趋同，比对就没有信息量；
- 监督者必须不写方案，否则它评的是自己的东西；
- 追踪者必须不判对错，否则它记的是对自己有利的版本；
- 需求分析员必须不写 SQL，否则它会为了好写而把口径解释得更好写。

其余职责（登记、质量规则、血缘调度、交付文档）**不需要独立角色**——它们要么是定义侧的延伸（验收标准 → DQ 规则），要么是实现侧的延伸（最终脚本 → 调度），要么是记录侧的延伸（journal → 交付文档）。加角色只会让交接次数变多、责任变模糊。决定过程见 [`memory/decisions/ADR-0003-five-agents.md`](../memory/decisions/ADR-0003-five-agents.md)。

## 角色矩阵（5 个）

| 角色 | 阶段 | 能写 | 禁止 |
|---|---|---|---|
| `requirement-translator` 需求分析员 | P0 / P1 / P4 / A5 | `需求分析员/`、`质量/` | 改原始需求、写 SQL 产物、裁决方案 |
| `developer-1` 开发者 1 | P2 / P5 | `developer-1/`、`血缘/` | **读 `developer-2/`**（直到 G3 通过） |
| `developer-2` 开发者 2 | P2 | `developer-2/` | **读 `developer-1/`**、P3 之后不得再改 |
| `supervisor` 监督者 | P3 | `监督者/`（含 `final/`） | 改口径、和稀泥、重写脚本 |
| `chronicler` 追踪者 | 全程 + P6 | `journal.jsonl`、`交付/` | 改任何产物、参与决策 |

四条关键约束：

1. **本体谁都不能自动改**。任何角色写 `ontology/` 都是违规（`check_agents.py` 会拦）；有意见就提 `ontology_delta` 提案，由人评审后手改。
2. **双轨必须隔离**：`developer-1` 与 `developer-2` 互不可见。任何一方读取另一轨的目录视为违规，`chronicler` 会记录，G2 判失败。
3. **追踪者只写不判**：它记录一切，但不参与决策。
4. **监督者不改口径**：发现两边口径不一致，退回 P1 翻译，不许自己拍一个。

## 文件格式

- `roles.json` —— 机器可读部分（阶段、门禁、可写、禁读、输入输出），`tools/check_agents.py` 校验它，`tools/role_prompt.py` 拿它生成 subagent 提示词。
- `<role>.md` —— 人读的散文说明，开头是 YAML front matter：

```yaml
---
role: developer-1
model: default
can_write: [requirements/<需求目录>/需求开发员/developer-1]
mounted_skills: [sk-sql-ddl, sk-sql-dml, sk-sql-guard]
gates: [G2]
reads: [requirements/<需求目录>/需求分析员, ontology, knowledge]
must_not_read: [requirements/<需求目录>/需求开发员/developer-2]
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
