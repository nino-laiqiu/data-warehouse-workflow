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

追踪者（`chronicler`）横切全程，把每次对话、每次修改、每次门禁判定写进 `requirements/<需求目录>/需求开发员/journal.jsonl`；P6 的交付文档也由它汇总。

**编制 5 个角色**：需求分析员（P0/P1/P4）、开发者 1（P2/P5）、开发者 2（P2）、监督者（P3）、追踪者（全程 + P6）。为什么不设编排者/质量官/血缘负责人/文档负责人——见 [ADR-0003](memory/decisions/ADR-0003-five-agents.md)。

## 目录地图

| 目录 | 作用 | 谁写 | 规则 |
|---|---|---|---|
| `docs/` | 设计文档 | 人 | 参考物，不参与校验 |
| `需求池/` | 原始需求投放处：邮件导出、群聊记录、Excel，什么格式都丢进来 | 提出需求的任何人 | 只增不改；雷达扫这里，确认后才建需求目录 |
| `requirements/` | **一个需求一个顶层目录** `<短名>需求<YYYYMMDD>/`，里面再分 `反馈者/` `需求分析员/` `需求开发员/` | 需求方 / 翻译者 / 开发者 | 不许平铺；角色只能是需求的子目录；原件不许改 |
| `ontology/` | 对象 / 过程 / 指标 / 关系 / 约束 | 本体管理员（唯一） | 其余角色只读；改动只能走 `ontology_delta` |
| `knowledge/` | LLM 知识库：规范 / 方言 / 范例 / 踩坑；`wiki/` 是表与词根的索引页 | 任何人提 PR | 只回答"怎么写"，不定义口径 |
| `memory/` | 长期记忆：决策、口径裁决、评审结论 | 编排器 | 追加式，只增不改 |
| `skills/` | 技能：可被工作流按名字调用的一步操作 | 开发者 | `SKILL.md`（name/version/owner）+ `schema.json` + `validate.py` |
| `agents/` | 角色与权责 | 架构 | 不内联业务规则 |
| `contracts/` | 阶段交付物 JSON Schema | 架构 | 缺字段即硬失败 |
| `flow/` | 状态机 + 门禁 + **每个 stage 调用哪些技能** | 架构 | 技能调用关系只在这里维护 |
| `templates/` | DDL / DML / DAG / 文档模板 | 开发者 | 被 skills 引用，不单独使用 |
| `runs/` | A 线临时 run；B 线不用它（run 目录 = 需求目录） | 机器 | 不入库（`.gitignore`） |
| `tools/` | 工程脚本（同步、校验） | 开发者 | — |
| `db/` | MySQL 表结构（问答沉淀）+ 导出种子 | 追踪者 | 生产 DDL 的唯一副本，改结构先改这里 |
| `data/qa/` | 问答样本（JSONL），用于跑通链路 | 追踪者 | 只是样本，真实数据进 MySQL |
| `知识候选/` | 从问答里挖出来的候选，人审后转正 | 追踪者 | 自动生成勿手改；待审积压算巡检问题 |

## 三条硬边界

1. **口径只在 `ontology/` 定义**。agent 不得在对话、SQL 注释、文档里发明第二份口径。
2. **知识库不定义口径**，只回答"怎么写 / 怎么避坑"。两者混在一起，幻觉就有了入口。
3. **A 线产物永不进生产调度**，必须经 B 线固化。这是取数安全阀，不是流程洁癖。

## 快速开始

```bash
# 0. B 线入口：G0 原始需求对账（未登记 / hash 不一致 / 模板缺段都会拦）
python skills/sk-req-register/validate.py

# 0.5 G1 翻译稿可开工校验（8 段 / 待确认项为空 / 本体引用真实）
python skills/sk-req-validate/validate.py --doc requirements/渠道GMV日报需求20261122/需求分析员/REQ-20261122-01.md

# 1. 校验本体（纯标准库，无 LLM 依赖，CI 可直接跑）
python ontology/schema/validate.py

# 2. 校验契约（标准库实现的 JSON Schema 子集）
python tools/validate_contracts.py requirements/<需求目录>/需求开发员/model_design.json --schema contracts/model_design.schema.json

# 3. 校验 skill 产物：输入契约 + 生成的 SQL 一起查
python skills/sk-sql-ddl/validate.py --input requirements/<需求目录>/需求开发员/model_design.json --sql out.sql

# 4. 写入 GitHub：走 API 通道，不用 git push（细节见 docs/推送流程.md）
& .\tools\push.ps1 -Message "feat: 改了什么" -All

# 5. 校验 wiki 内部链接（改完 wiki 必跑）
python tools/check_wiki.py

# 6. 校验技能引用：工作流里写了什么技能，就必须有什么目录（反过来也查）
python tools/check_skills.py

# 7. 校验需求目录布局：三个角色目录同名、开发目录结构齐全、没有平铺
python tools/check_layout.py

# 8. G4：质量规则可执行（覆盖空值/重复/单调性、全部单条只读 SQL）
python tools/check_dq.py requirements/画像标签需求20261122/需求开发员/质量/dq_rules.json

# 9. G5：血缘无孤立节点、调度无环、回滚可执行
python tools/check_lineage.py requirements/画像标签需求20261122/需求开发员/血缘/lineage.json

# 10. 从 dq_rules.json 重新生成 dq_check.sql（规则改了就重跑，不手改 SQL）
python tools/dq_to_sql.py requirements/画像标签需求20261122/需求开发员/质量/dq_rules.json

# 11. 全仓巡检：一条命令跑完全部门禁 + 卫生指标 + 问题清单，出周报
python tools/inspect.py

# 12. 需求雷达：扫 需求池/ 有没有新增或改过的需求文档（有则退出码 2）
python tools/scan_requirements.py

# 13. 校验角色定义：5 个角色的分工、双轨隔离、pipeline 接线、编制是否仍是 5 个
python tools/check_agents.py

# 14. 生成某个角色的 subagent 提示词（--write 同时落盘为派活证据）
python tools/role_prompt.py --role developer-1 --req 画像标签需求20261122 --write

# 15. 定时任务：看清单 / 跑此刻到点的 / 全跑一遍
python tools/run_schedule.py --list
python tools/run_schedule.py --due

# 16. 知识库改老口径：看影响面 → 登记变更；--check 拦住"改了没登记"
python tools/wiki_impact.py --changed
python tools/wiki_impact.py --stamp --note "补了退款回冲说明"

# 17. 需求分析员的对话式翻译：初稿 → 逐条问答 → 轮次 → 确认 → 提升为正式稿
python tools/req_review.py status --req-id REQ-20261122-02
python tools/req_review.py answer --req-id REQ-20261122-02 --id Q1 --text "终身，只认有没有付过款"
python tools/req_review.py round  --req-id REQ-20261122-02 --note "第 1 轮：补了时间窗与缺失值"
python tools/req_review.py promote --req-id REQ-20261122-02
python tools/req_review.py confirm --req-id REQ-20261122-02

# 18. 现网验证：把 DQ 断言拿到生产库跑一遍（--offline 只出待执行清单，不能当放行依据）
python tools/verify_live.py --req 画像标签需求20261122 --offline

# 19. 问答沉淀：入库 → 挖候选 → 转正（分析师问答是知识库最好的原料）
python tools/qa_store.py init
python tools/qa_store.py ingest --file data/qa/sample.jsonl
python tools/qa_store.py stats
python tools/qa_mine.py --week 2026-W48
python tools/qa_promote.py --list

# 20. 追踪：追加六类事件 / 看未关待办 / 校验全部事件 / 回放最近几条
python tools/journal.py append --req 画像标签需求20261122 --type query --actor chronicler   --sql-file .tmp/smoke.sql --purpose "核对 GMV 与 ADS 一致性" --result "差异 0.003%"
python tools/journal.py todos --req 画像标签需求20261122
python tools/journal.py check --req 画像标签需求20261122
python tools/journal.py show  --req 画像标签需求20261122 --tail 10

# 21. 对话界面（P1）：CLI 与本地 HTTP 共用一套契约，四个动作
python tools/chat.py chat "近30天城市等级支付用户数"        # → SQL + caveats + 落一条 qa_record
python tools/chat.py journal --run R-1 --type gate         # → 只看门禁事件
python tools/chat.py task --role developer-1 --req 画像标签需求20261122 --stage P2
python tools/chat.py serve --port 8765                     # 同契约的本地 HTTP（POST /v1/chat 等四端点）
```

十五个校验器（另有问答沉淀与候选转正两条链路） + 需求雷达 + 调度执行器都不依赖第三方库（本机没有 PyYAML / jsonschema），失败时返回非 0 退出码与机器可读原因。

推送通道的原理、失败排查表、新窗口冷启动清单，见 [`docs/推送流程.md`](docs/推送流程.md)。
角色怎么被 subagent 真跑，见 [`docs/角色运行.md`](docs/角色运行.md)；
第二遍双轨（渠道 GMV 日报）用 subagent 真跑后的复盘——隔离/门禁/手工过门三个问题的实测结论，见 [`docs/复盘-第二遍双轨.md`](docs/复盘-第二遍双轨.md)；定时怎么接，见 [`docs/调度.md`](docs/调度.md)；
外部系统（含其他问答系统）怎么把分析师问答送进来，见 [`docs/问答采集接口.md`](docs/问答采集接口.md)；
人怎么进入这套工作流（取数问答 / 口径澄清 / 派活），见 [`docs/对话界面.md`](docs/对话界面.md)；
14 个技能的判据与排期，见 [`docs/技能清单.md`](docs/技能清单.md)。
七个核心能力（多智能体协作 / 知识库驱动 / 需求自动化 / 全过程留痕 / 记忆体系 / 开发规范 / 定时巡检）的定义与缺口，见 [`docs/核心能力与自动化.md`](docs/核心能力与自动化.md)。
九类核心资产（双轨工作流 / agents / skills / wiki / 记忆 / 追踪 / 定时任务 / 全局规范 / 问答沉淀，加本体作底座）各自的维护者、判据与校验命令，见 [`docs/核心资产.md`](docs/核心资产.md)；全仓约法见 [`docs/全局规范.md`](docs/全局规范.md)。

## 当前状态

**v0.7 —— 需求优先的目录结构；一个需求从 P0 跑到 P6；角色由 subagent 真跑，定时在外面套一层。**

| 阶段 | 产出 | 状态 |
|---|---|---|
| M0 设计定稿 | [`docs/设计文档-数仓智能开发工作流.md`](docs/设计文档-数仓智能开发工作流.md) | 待评审 |
| M1 骨架 | 目录 + 校验器 + 一份示例 skill/agent | ✅ |
| M1 本体 + 知识库 | `ontology/` `knowledge/` 填内容 | ✅ 17 个本体文件 + 6 页 wiki |
| M2 角色与流程 | `requirements/` `agents/`(5 角色) `flow/`(P0–P6 / G0–G6) | ✅ 本版（双轨制） |
| M2a A 线最小闭环 | `skills/sk-qry-*` | 未开始 |
| M2b B 线 Skills | `skills/sk-req-*` `sk-sql-*` `sk-ont-validate` | 部分（已实现 sk-req-register / sk-req-validate / sk-sql-ddl） |
| M3 契约落地 | `contracts/` 9 个设计契约 + 5 个附加契约 | ✅ 9/9（每个契约都有 example 且过校验） |
| M4 电商域闭环 | `requirements/画像标签需求20261122/需求开发员/` | ✅ P0–P6 全跑通（REQ-20261122-02，H3 待人工放行） |
| M4b 第二遍双轨 | `requirements/渠道GMV日报需求20261122/需求开发员/` | 🟡 P0–P3 跑通（subagent 真跑，H2 待裁决；G3 因 sk-sql-guard 无实现而挂起） |
| M5 巡检器 | `tools/inspect.py` 一条命令出门禁矩阵 + 周报 | ✅ 12 项门禁，首份周报 `runs/inspection/2026-W48/` |
| M5b 运行载体 | 角色 → subagent 提示词（`agents/roles.json` + `tools/role_prompt.py`） | ✅ |
| M5c 调度载体 | `flow/schedule.yaml` + `tools/run_schedule.py`（cron / 任务计划程序 / DSH 定时都调它） | ✅ |

先读设计文档第 7 章（两条流水线）。注意：第 9 章的端到端走查是用 Push 域写的（比电商复杂），
本仓库的模板实现换成**电商交易域**——结构一样，但更适合当起点。
