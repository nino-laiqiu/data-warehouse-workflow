# skills/ —— 可判定的原子动作

一个 skill 是**一件能被脚本判定对错的事**，不是一个「能力」。

## 准入四条（缺一不可）

1. **输入是结构化的**：有 `schema.json`，字段可枚举，不接受"帮我把这个域设计一下"这类输入。
2. **输出可脚本校验**：`validate.py` 能给出 PASS/FAIL，而不是让另一个 LLM 打分。
3. **幂等**：同样的输入重复执行，产物一致（时间戳、随机 ID 除外，且必须显式声明）。
4. **单职责**：一个 skill 只做一件事。"生成 DDL 并顺便建表并顺便调度"不合格。

反例：`设计整个 Push 域模型` —— 这是 agent 的判断，不是 skill。

## 目录约定

```
skills/<sk-域-动作>/
├── SKILL.md          # 人读：做什么、什么时候用、边界在哪
├── schema.json       # 机读：输入输出契约（JSON Schema）
├── validate.py       # 判定：输出是否合规
├── prompt.md         # 可选：LLM 提示词模板
└── examples/         # 可选：输入输出样例，validate.py 用它自测
```

## 命名

`sk-<域>-<动作>`，全小写连字符。域取本体里的域（`sql` `qry` `ont` `dq`），动作用动词原形（`ddl` `dml` `intent` `locate` `guard`）。

已规划：

| skill | 线 | 职责 | 状态 |
|---|---|---|---|
| `sk-sql-ddl` | B | 表结构 → Hive DDL | ✅ 示例 |
| `sk-sql-dml` | B | 指标口径 → 聚合 DML | 待建 |
| `sk-qry-intent` | A | 自然语言 → 结构化取数意图 | 待建 |
| `sk-qry-locate` | A | 意图 → 候选表（ADS>DWS>DWD>ODS） | 待建 |
| `sk-qry-guard` | A | SQL AST 安全门禁 | 待建 |
| `sk-ont-validate` | B | 本体文件合规校验 | 待建 |

## 版本与引用

skill 的版本写在 `SKILL.md` 头部的 `version:` 字段。每次 run 的 `run_meta.json` 必须记录用到的 skill 版本——这是四元组指纹的一部分，缺了就没法复现。
