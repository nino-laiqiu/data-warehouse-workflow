# 数仓智能开发工作流

用「业务本体 + 记忆 + LLM 知识库 + Skills + Agents」把数仓开发从"写 SQL"变成"可校验的流水线"。

- 目标平台：Hive 3.x / Spark SQL 3.x
- 建模方法论：Kimball 维度建模 + OneData 原子/派生指标
- 样板域：常规电商交易（用户 / 商品 / 订单 / 支付）——选它是因为结构简单、人人都懂，适合当模板

## 两条泳道

| | A 线：取数分析 | B 线：数仓开发 |
|---|---|---|
| 使用者 | 数据分析师、运营、业务方 | 数仓开发工程师 |
| 起点 | 一个业务问题 | 一份原始需求 |
| 耗时 | 分钟级 | 天级 |
| 门禁 | GA1~GA3（轻） | G0~G6（重） |
| 产物 | SQL + 结论 + 口径说明 | 合格脚本 + 对比报告 + 表 + 指标 + 血缘 |

两条线共享同一份本体与知识库（约 80%），分化在起点、门禁强度与产物形态（约 20%）。
连接点是**晋升机制**：A 线的高频问题 → 指标化提案 → 进入 B 线固化。

### B 线是双轨制

```
原始需求 → 需求翻译 → ┌ developer-1 → track-1 ┐ → 监督比对 → 合格脚本
（只增不改）  （8 段）  └ developer-2 → track-2 ┘   （裁决+报告）
```

同一份翻译稿，两个人**独立实现、互不可见**，第三人比对裁决。理由见 [ADR-0002](memory/decisions/ADR-0002-dual-track.md)：
一个人写一个人自检，发现不了"口径理解偏差"——两份 SQL 都能跑，数字差 3%，谁也不知道谁对。
双轨的代价是成本 ×2，所以只用在建表和指标口径这类一次做错、长期返工的事上。

追踪者（`chronicler`）横切全程，把每次对话、每次修改、每次门禁判定写进 `runs/<run_id>/journal.jsonl`。

## 目录地图

| 目录 | 作用 | 谁写 | 规则 |
|---|---|---|---|
| `docs/` | 设计文档 | 人 | 参考物，不参与校验 |
| `requirements/` | `inbox/` 原始需求（只增不改）+ `normalized/` 翻译稿 | 需求方 / 翻译者 | 原始文件不许改，改了就没法回溯 |
| `ontology/` | 对象 / 过程 / 指标 / 关系 / 约束 | 本体管理员（唯一） | 其余角色只读；改动只能走 `ontology_delta` |
| `knowledge/` | LLM 知识库：规范 / 方言 / 范例 / 踩坑；`wiki/` 是表与词根的索引页 | 任何人提 PR | 只回答"怎么写"，不定义口径 |
| `memory/` | 长期记忆：决策、口径裁决、评审结论 | 编排器 | 追加式，只增不改 |
| `skills/` | 技能：可被工作流按名字调用的一步操作 | 开发者 | `SKILL.md`（name/version/owner）+ `schema.json` + `validate.py` |
| `agents/` | 角色与权责 | 架构 | 不内联业务规则 |
| `contracts/` | 阶段交付物 JSON Schema | 架构 | 缺字段即硬失败 |
| `flow/` | 状态机 + 门禁 + **每个 stage 调用哪些技能** | 架构 | 技能调用关系只在这里维护 |
| `templates/` | DDL / DML / DAG / 文档模板 | 开发者 | 被 skills 引用，不单独使用 |
| `runs/` | 单次运行的产物与指纹 | 机器 | 不入库（`.gitignore`） |
| `tools/` | 工程脚本（同步、校验） | 开发者 | — |

## 三条硬边界

1. **口径只在 `ontology/` 定义**。agent 不得在对话、SQL 注释、文档里发明第二份口径。
2. **知识库不定义口径**，只回答"怎么写 / 怎么避坑"。两者混在一起，幻觉就有了入口。
3. **A 线产物永不进生产调度**，必须经 B 线固化。这是取数安全阀，不是流程洁癖。

## 快速开始

```bash
# 1. 校验本体（纯标准库，无 LLM 依赖，CI 可直接跑）
python ontology/schema/validate.py

# 2. 校验契约（标准库实现的 JSON Schema 子集）
python tools/validate_contracts.py runs/<run_id>/intent.json --schema contracts/intent.schema.json

# 3. 校验 skill 产物：输入契约 + 生成的 SQL 一起查
python skills/sk-sql-ddl/validate.py --input runs/<run_id>/model_design.json --sql out.sql

# 4. git push 不通时的备用上传通道（走 GitHub API）
node tools/push_file.mjs README.md README.md "docs: update readme"

# 5. 校验 wiki 内部链接（改完 wiki 必跑）
python tools/check_wiki.py

# 6. 校验技能引用：工作流里写了什么技能，就必须有什么目录（反过来也查）
python tools/check_skills.py
```

五个校验器都不依赖第三方库（本机没有 PyYAML / jsonschema），失败时返回非 0 退出码与机器可读原因。

## 当前状态

**v0.4 —— B 线改为双轨制，骨架与本体已落地，契约待填内容。**

| 阶段 | 产出 | 状态 |
|---|---|---|
| M0 设计定稿 | [`docs/设计文档-数仓智能开发工作流.md`](docs/设计文档-数仓智能开发工作流.md) | 待评审 |
| M1 骨架 | 目录 + 校验器 + 一份示例 skill/agent | ✅ |
| M1 本体 + 知识库 | `ontology/` `knowledge/` 填内容 | ✅ 14 个本体文件 + 6 页 wiki |
| M2 角色与流程 | `requirements/` `agents/`(11 角色) `flow/`(P0–P6 / G0–G6) | ✅ 本版（双轨制） |
| M2a A 线最小闭环 | `skills/sk-qry-*` | 未开始 |
| M2b B 线 Skills | `skills/sk-req-*` `sk-sql-*` `sk-ont-validate` | 未开始（仅 sk-sql-ddl 已实现） |
| M3 契约落地 | `contracts/` 9 个 schema | 未开始（模板 + 2 个已写） |
| M4 电商域闭环 | `runs/` | 未开始 |

先读设计文档第 7 章（两条流水线）。注意：第 9 章的端到端走查是用 Push 域写的（比电商复杂），
本仓库的模板实现换成**电商交易域**——结构一样，但更适合当起点。
