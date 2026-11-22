# skills/ —— 技能

一个 skill 是**能被工作流按名字调用的一步操作**。

不是"一段介绍能力的文档"，也不是 agent 的职责描述。判断标准很简单：能不能在一行 YAML 里写 `skills: [sk-qry-intent]`，然后有人（agent 或脚本）真的去执行它。

## 一个技能由三样东西组成

| 文件 | 给谁看 | 作用 |
|---|---|---|
| `SKILL.md` | 人 + LLM | 做什么、输入输出、**不做什么** |
| `schema.json` | 机器 | 输入契约（JSON Schema） |
| `validate.py` | 机器 | 产物是否合规，返回 PASS/FAIL |

`prompt.md`、`examples/` 可选。

## 调用约定：写在工作流里

技能的调用关系**不写在 skill 自己身上**，写在 [flow/pipeline.yaml](../flow/pipeline.yaml) 的 stage 上：

```yaml
- id: A1
  name: 意图解析
  agent: 无（skill 直调）      # 谁执行
  skills: [sk-qry-intent]      # 按顺序调用，空数组 = 纯 agent 判断
  in: 自然语言问题
  out: intent
  gate: GA1
```

三条规则：

1. `skills:` 是**有序列表**，按写的顺序执行。写 `[]` 表示这一步没有可调用的技能，靠 agent 判断——这是合法的，但要显式写出来，不能省。
2. 每个名字必须在 `skills/<name>/SKILL.md` 里真实存在。引用一个不存在的技能 = 工作流跑不通，所以 [tools/check_skills.py](../tools/check_skills.py) 会拦。
3. 反过来也拦：建了目录却没人调用的技能是死技能，要么接进某个 stage，要么删掉。

## 目录约定

```
skills/<sk-域-动作>/
├── SKILL.md          # 头部 front matter: name / version / owner
├── schema.json       # 输入契约
├── validate.py       # 产物校验
├── prompt.md         # 可选
└── examples/         # 可选，validate.py 用它自测
```

`SKILL.md` 头部：

```markdown
---
name: sk-sql-ddl
version: 0.1.0
owner: model-designer
---
```

`version` 会被记进 `run_meta.json` 的四元组指纹；没有版本号的技能，跑出来的结果无法复现。

## 命名

`sk-<域>-<动作>`，全小写连字符。域取 `req` `ont` `sql` `qry` `dq` `doc`，动作用动词原形（`register` `validate` `ddl` `dml` `guard` `diff` `intent` `locate`）。

两条线共用的技能不另起域名：SQL 生成与门禁两条线都要用，就都叫 `sk-sql-*`。

## 技能清单

| 技能 | 线 | 被哪个 stage 调用 | 做什么 | 状态 |
|---|---|---|---|---|
| `sk-req-register` | B | P0 | 登记原始需求：校验模板、算 sha256、生成编号 | 待建 |
| `sk-req-validate` | B | P1 | 翻译稿 8 段齐全、「待确认项」为空 | 待建 |
| `sk-ont-validate` | B | P1 | 引用的本体 id 存在且未 deprecated | 待建 |
| `sk-sql-ddl` | 共用 | P2 | 表设计 → Hive DDL | ✅ 已实现 |
| `sk-sql-dml` | 共用 | P2 | 指标口径 → 聚合 DML | 待建 |
| `sk-sql-guard` | 共用 | P2 / A3 | SQL 静态门禁（只读、dt、LIMIT、无 SELECT *） | 待建 |
| `sk-sql-diff` | B | P3 | 两轨 SQL 差异提取 → comparison_report 的 differences | 待建 |
| `sk-qry-intent` | A | A1 | 自然语言 → 结构化取数意图 | 待建 |
| `sk-qry-locate` | A | A2 | 意图 → 候选表（ADS→DWS→DWD→ODS） | 待建 |
| `sk-qry-gen` | A | A3 | 意图 + 表 → SELECT 语句 | 待建 |
| `sk-qry-check` | A | A4 | 结果自检（行数、空值、量级异常） | 待建 |

`sk-sql-guard` 两条线共用：A3 拿它拦"分析师写出 UPDATE"，P2 拿它拦"开发者漏了 dt 分区"。同一个门禁，规则只有一份。

> 这张表是"当前状态"，**不是**调用关系的权威来源。改调用关系只改 `pipeline.yaml`，然后跑 `python tools/check_skills.py`，表里的"被哪个 stage 调用"以校验结果为准。

## 新增一个技能

1. 建目录 `skills/sk-域-动作/`，写 `SKILL.md`（先写"不做什么"，再写做什么）。
2. 补 `schema.json` + `validate.py`，用 `examples/` 里一个真实输入自测通过。
3. 在 `flow/pipeline.yaml` 对应的 stage 的 `skills:` 里加上名字。
4. `python tools/check_skills.py` 必须 PASS。

第 3 步不能省——没接进工作流的技能等于没有。

## 写好的四条建议（不是硬门槛）

1. **单职责**：一个技能做一件事。"生成 DDL 并顺便建表并顺便调度"拆成三个。
2. **输入结构化**：字段可枚举，不接受"帮我把这个域设计一下"。
3. **输出可判定**：能脚本判 PASS/FAIL，别让另一个 LLM 打分。
4. **幂等**：同输入同产物（时间戳、随机 ID 要显式声明）。

反例：`设计整个电商交易域模型` —— 这是 agent 的判断，写成 skill 只会得到一个不可验证的黑箱。
