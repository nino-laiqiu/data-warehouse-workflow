# P3 监督者裁决报告

| 项目 | 内容 |
|---|---|
| 需求 | `REQ-20261122-01` 渠道 GMV 日报 |
| run_id | `20261122-01` |
| 阶段 | P3 双轨比对与裁决 |
| 监督者 | sup-1 |
| 日期 | 2026-11-28 |
| 输入轨道 | A = `developer-1`；B = `developer-2` |
| 比对前置 | `tools/check_dual_track.py` 已由 lead 执行：两轨 SQL 无相同文件；DDL 行级相似度 0.364、ETL 0.39；无跨轨泄漏 |
| 结论 | **采用 A 轨，吸收 B 轨 2 项实现改进；不退回 P1** |

---

## 1. 结论

### 1.1 一句话结论

**选 A 轨（developer-1）为主体**：A 在未识别渠道归 `other`、维表先聚合防扇出、严格按 `(order_id, pay_seq)` 去重三处更贴近知识库与需求验收；同时吸收 B 轨的**渠道码空值/空白归一**与 **AOV 存储精度 18,4** 两项实现改进，最终脚本共 6 处改动（C1–C6），不改变任何指标口径。

### 1.2 三层比较结果

| 层面 | 条数 | 结论 |
|---|---:|---|
| 口径（semantic） | 0 | 两轨对 GMV、ORDER_CNT、AOV、CHANNEL 的定义完全一致，无口径冲突，**不退回 P1** |
| 结构（structure） | 1 | S1：维表侧是否先聚合到渠道唯一；A 正确 |
| 实现（implementation） | 7 | D1–D7：兜底值、空值清洗、去重键/排序、归日过滤、AOV 精度；A 胜 6 条，B 胜 1 条，1 条合并 |

裁决分布：`a` = 6 条（S1、D1、D2、D4、D5、D6），`b` = 1 条（D7），`merge` = 1 条（D3）。

### 1.3 为什么是 A

1. **口径层没有分歧，先排除了“退回 P1”的理由。** 两轨都按 `pay_time` 归日、都只取 `pay_status='success' AND pay_amt>0`、都用 `SUM(pay_amt)` 与 `COUNT(DISTINCT order_id)`、都在明细层算 AOV 而不是平均日客单价。这些正是 `ontology/metric/atomic/gmv.yaml`（id `GMV`）、`order_cnt.yaml`（id `ORDER_CNT`）、`metric/derived/aov.yaml`（id `AOV`）与需求稿 §2/§5 的硬约束。
2. **结构层 A 更稳。** A 先把 `dim_channel_df` 聚合到 `channel_code` 唯一再 LEFT JOIN；B 直接关联。知识库明确维表主键是 `channel_id` 而非 `channel_code`（`knowledge/wiki/04-维表.md:59-64`），按 `channel_code` 关联不能假设唯一。B 的写法一旦维表同码多行，事实行会被放大，直接违反需求 §6.3“同 dt+channel_code 只有一行”。
3. **实现层 A 的默认值更贴仓库惯例。** 未识别渠道归 `other` 有明确知识库依据（`knowledge/wiki/03-事实表.md:125`「未识别渠道归 other，不要丢行，否则总数对不上」）；B 的 `unknown` 不在 `ontology/dict/channel.yaml` 的 CHANNEL 值域 `[app, mini_program, h5, pc]` 内，也没有仓库先例。
4. **A 的去重与归日更保守。** A 严格按声明主键 `(order_id, pay_seq)` 去重（`knowledge/wiki/03-事实表.md:65/73`、`knowledge/wiki/05-取数路径.md:33`），不引入 `pay_id` 可替代主键的未证实假设；A 只靠 `dt='${dt}'` 归日，信任“分区 dt 即 pay_time 日期”的契约（`knowledge/wiki/03-事实表.md:66`），不额外用 `TO_DATE` 静默丢行。

### 1.4 为什么不是 B，但吸收 B 两点

B 不是“一无是处”，它的两项实现比 A 好，已并入 final：

- **D3（merge）**：B 用 `NULLIF(TRIM(channel_code),'')` 同时处理 NULL、空串、前后空白。A 只 `COALESCE(channel_code,'other')`，空串会进入结果，而 A 自己的 self-check §3.1 却用 `channel_code=''` 断言 `empty_cnt=0`——SQL 不能保证该断言。final 采用 B 的归一化，但保留 A 的 `other` 兜底，并修掉 B 自认的 `' test '` 漏滤（见 C3/C4）。
- **D7（b）**：B 的 AOV 存储 `DECIMAL(18,4)` 比 A 的 `18,2` 少一次存储舍入。`AOV` 是派生比率、`non_additive`，2 位小数在落表时就丢了精度；4 位只多占极少空间，下游展示仍可再舍。`knowledge/wiki/01-命名与词根.md:53` 的 `DECIMAL(18,2)` 规则针对 `_amt` 金额字段，AOV 不是 `_amt`，不构成必须 2 位的依据。

B 的其他差异不采纳，理由逐条见第 2 节；B 的 `unknown`、`COALESCE(pay_seq, pay_id)`、`TO_DATE` 双重过滤、`pay_id` 排序都属于“用未证实的假设换确定性”，不适合作为默认实现。

### 1.5 是否退回 P1

**不退回。** 两轨没有口径冲突：GMV 是否含运费、退款是否回冲、订单数是否按订单去重、AOV 是否可加、渠道是否取支付时刻快照，五处完全一致。D1 的 `other` vs `unknown` 只是**未识别行的桶名**，两轨都保留行、都计入 GMV/ORDER_CNT，不改变任何指标总量，不构成口径冲突；它按实现差异裁决，同时把“CHANNEL 字典缺 other”作为本体缺口交 H2（见 H2-4）。

---

## 2. 差异与裁决（8 条，全覆盖）

> 完整逐条描述见同目录 `comparison.md`；此处给出裁决所需的压缩版。层面取值：口径 = semantic，结构 = structure，实现 = implementation。

| # | 层面 | A 轨怎么做 | B 轨怎么做 | 依据 | 裁决 |
|---|---|---|---|---|---|
| **S1** | 结构 | 维表先聚合到渠道唯一：`SELECT channel_code, MAX(channel_name) ... GROUP BY channel_code`，再 LEFT JOIN（A ETL L62-69） | 维表不聚合：`SELECT channel_code, channel_name ...`，直接 LEFT JOIN（B ETL L66-70），同码多行会放大事实行 | 需求 §6.3 同 dt+channel_code 只有一行；`knowledge/wiki/04-维表.md:59-64` 维表主键是 `channel_id`，按 `channel_code` 关联不能假定唯一；A self-check §3.3 把维表 JOIN 放大列为唯一键失败首因 | **a** |
| **D1** | 实现 | 未识别渠道兜底 `'other'`：`COALESCE(channel_code,'other')`（A ETL L43） | 兜底 `'unknown'`：`COALESCE(NULLIF(TRIM(f.channel_code),''),'unknown')`（B ETL L30、L62） | `knowledge/wiki/03-事实表.md:125`「未识别渠道归 other，不要丢行」；`ontology/dict/channel.yaml` CHANNEL 值域只有 app/mini_program/h5/pc，other/unknown 都不在字典内 | **a**（B 的 unknown 无仓库先例；字典缺口交 H2-4） |
| **D2** | 实现 | 维表未匹配时 `channel_name` 兜底 `'未识别'`：`COALESCE(c.channel_name,'未识别')`（A ETL L21） | 兜底为渠道码：`COALESCE(d.channel_name,p.channel_code)`（B ETL L21） | 需求 §4 只要求输出 channel_name，未规定兜底值；`knowledge/wiki/03-事实表.md:125` 的 other 约定只针对渠道码。A 把维表缺行显式暴露，channel_code 仍保留原码；B 把码复制进名称列会掩盖维表缺口 | **a**（若 H2 要代码兜底，只改一行） |
| **D3** | 实现 | 只处理 NULL：`COALESCE(channel_code,'other')`；空串/纯空白原样进入结果。A self-check §3.1 却用 `channel_code=''` 断言 `empty_cnt=0`，SQL 不能保证 | 用 `NULLIF(TRIM(channel_code),'')` 处理 NULL/空串/空白；但 test 过滤仍比较原始值，`' test '` 先通过、再在聚合处 TRIM 成 `'test'`，测试渠道漏进结果（B self-check §4.3 自认） | 需求 §6.1 channel_code 无空值；A self-check §3.1 的断言需要 SQL 真保证；B self-check §4.3 暴露了 TRIM 与 test 过滤不同源的新缺口 | **merge**：采用 B 的 `NULLIF(TRIM(...),'')`，保留 A 的 `other`；test 过滤用同一表达式（C3/C4） |
| **D4** | 实现 | 严格按声明主键去重：`PARTITION BY order_id, pay_seq`（A ETL L47） | `pay_seq` 为空时退化到 `pay_id`：`PARTITION BY order_id, COALESCE(pay_seq,pay_id)`（B ETL L46） | `knowledge/wiki/03-事实表.md:65` 主键 `order_id+pay_seq`；:73「必须按 (order_id, pay_seq) 去重」；`knowledge/wiki/05-取数路径.md:33` 同。没有证据表明 `pay_id` 可替代：重复回调若共享 `pay_id`，退化仍不能去重；若各自生成新 `pay_id`，退化会把重复回调留下 | **a**（`pay_seq` 可空性交 P4 首跑前确认，见 R2） |
| **D5** | 实现 | 去重并列键用金额：`ORDER BY pay_time DESC, pay_amt DESC`（A ETL L48） | 用 `pay_id`：`ORDER BY pay_time DESC, pay_id DESC`，理由“金额以最后到达的回调为准”（B ETL L47） | `knowledge/wiki/03-事实表.md:73` 重复回调是“同一笔流水落多条”，正常各列相同，并列键只影响脏数据。A 的键只用已选列、是确定全序；`pay_id` 在同一笔流水的重复行上可能相同，不能保证全序，且“越大越晚到”未证实 | **a**（金额不一致的重复回调可能高估，列入 R5，不用未证实假设掩盖） |
| **D6** | 实现 | 只靠 `dt='${dt}'` 过滤，信任分区按 pay_time 归日（A ETL L49） | 额外加 `TO_DATE(f0.pay_time)=TO_DATE('${dt}')`（B ETL L54） | `knowledge/wiki/03-事实表.md:66` 分区 dt 就是按 pay_time 归日；需求 §2/§5 归日字段是 pay_time。B self-check 夹具 P08 显示这层过滤会把“分区错标”的行静默丢掉（少算 GMV），而 A 会让偏差在需求 §6.2 的 ADS 对账暴露；`TO_DATE` 对 TIMESTAMP 的时区/类型行为 B 也未在真引擎验证（B self-check §4.1） | **a**（上游错标应由 DQ 暴露，不静默丢行） |
| **D7** | 实现 | `aov DECIMAL(18,2)`，ETL `CAST(... AS DECIMAL(18,2))`（A DDL L25、A ETL L25） | `DECIMAL(18,4)`，ETL `CAST(... AS DECIMAL(18,4))`（B DDL L23、B ETL L24） | `ontology/metric/derived/aov.yaml` id `AOV`：派生比率、`non_additive`；2 位在存储时就舍入，4 位只多占极少空间、下游展示仍可再舍。`knowledge/wiki/01-命名与词根.md:53` 的 `DECIMAL(18,2)` 规则针对 `_amt` 金额字段，AOV 不是 `_amt` | **b**（只改精度，不改除法逻辑；下游仍禁止 `AVG(aov)`） |

### 2.1 为什么口径层是 0 条

逐项核对需求稿 §2/§5 与本体：

| 口径点 | A 轨 | B 轨 | 是否一致 |
|---|---|---|---|
| GMV 归日字段 | `pay_time`（分区 `dt`） | `pay_time`（额外 `TO_DATE` 仍是 `pay_time`） | 一致 |
| GMV 是否含运费 | 不含，只 `SUM(pay_amt)` | 不含，只 `SUM(pay_amt)` | 一致 |
| 退款是否回冲 | 不回冲，无退款列/负值扣减 | 不回冲，无退款列/负值扣减 | 一致 |
| 订单数去重 | `COUNT(DISTINCT order_id)` | `COUNT(DISTINCT order_id)` | 一致 |
| AOV 算法 | 同层 `gmv / order_cnt` | 同层 `gmv / order_cnt` | 一致 |
| AOV 可加性 | 注释明确“比率不可加” | 注释明确“比率不可加” | 一致 |
| 渠道时点 | 支付流水 `channel_code`，支付时刻快照 | 同 | 一致 |
| 支付成功/金额边界 | `pay_status='success' AND pay_amt>0` | 同 | 一致 |
| 测试渠道 | 排除 `'test'` | 排除 `'test'`（`' test '` 漏滤是缺陷，不是口径） | 一致 |

因此不存在“两轨口径冲突”，不需要退回 P1。D1/D2/D3 改变的是**未识别行的落桶与清洗**，不改变 GMV/ORDER_CNT/AOV 的定义；D4/D5/D6 改变的是**去重与归日的实现路径**，不改变“按支付流水、按 pay_time 归日”的口径。

### 2.2 已识别但不单列为实质差异的项

以下差异存在，但属于表述/等价写法，已在 `comparison.md` 的“非实质差异”清单记录，不影响裁决：

1. B 多投影一列 `pay_time`，A 不投影；该列只用于 B 的 `ROW_NUMBER` 排序，最终 SELECT 不输出。
2. 文件头注释、列 COMMENT 措辞不同（表 COMMENT 语义相同）。
3. test 过滤写法：A `COALESCE(channel_code,'') <> 'test'`，B `(channel_code IS NULL OR channel_code <> 'test')`；对 NULL/普通值等价，差异在 TRIM 时机，已归入 D3。
4. `GROUP BY` 用别名还是重复表达式，等价。
5. 表别名 `c` / `d`、缩进、空行不同。
6. B 的 `TO_DATE` 参数写法 `TO_DATE('${dt}')` 与 A 无此调用，已归入 D6。

这些不改变结果集，不作为独立裁决项；若 G3 复核要求“逐字差异也列出”，以 `comparison.md` 的非实质清单为准。

---

## 3. 相对 A 轨的逐条改动（C1–C6）

> 原则：只做选择与最小修补，不重写。final 的 6 处改动与 `comparison_report.json` 的 `changes` 数组一一对应。行号以 final 文件为准。

| 编号 | 文件:行 | A 轨原样 | final 改成 | 依据 | 对应差异 |
|---|---|---|---|---|---|
| **C1** | `final/01_dws_trade_channel_1d.sql:25` | `aov DECIMAL(18,2)` | `aov DECIMAL(18,4)` | AOV 是派生比率，2 位存储即舍入；`AOV` 本体 `non_additive`；`wiki/01:53` 的 18,2 只约束 `_amt` | D7 |
| **C2** | `final/01_dws_trade_channel_1d.sql:21` | 注释“缺失归 other，非空非字典值保留原码” | 注释“缺失或空白归 other，非空非字典值保留原码” | 与 C3 的 `NULLIF(TRIM(...),'')` 行为一致，避免注释承诺小于实现 | D3 |
| **C3** | `final/02_etl_dws_trade_channel_1d.sql:45` | `COALESCE(channel_code, 'other') AS channel_code` | `COALESCE(NULLIF(TRIM(channel_code), ''), 'other') AS channel_code` | 需求 §6.1 要求 channel_code 无空值；A 只处理 NULL，空串/纯空白会漏；B 的 `NULLIF(TRIM(...))` 正确，但兜底值保留 A 的 `other` | D3 |
| **C4** | `final/02_etl_dws_trade_channel_1d.sql:60` | `AND COALESCE(channel_code, '') <> 'test'` | `AND COALESCE(NULLIF(TRIM(channel_code), ''), 'other') <> 'test'` | 与 C3 同一套归一化；否则 `' test '` 先通过过滤、再被聚合处 TRIM 成 `'test'`，测试渠道漏进结果（B self-check §4.3 已暴露） | D3 |
| **C5** | `final/02_etl_dws_trade_channel_1d.sql:25` | `CAST(p.gmv / NULLIF(p.order_cnt, 0) AS DECIMAL(18,2)) AS aov` | `CAST(... AS DECIMAL(18,4)) AS aov` | 与 C1 的 DDL 精度对齐，避免“表 18,4、写入先被 CAST 成 18,2”的自相矛盾 | D7 |
| **C6** | `final/02_etl_dws_trade_channel_1d.sql:41-44、56-59` | 注释只描述 NULL 归 other / test 过滤 | 注释同步为“缺失、空串或纯空白归 other”“test 过滤与 SELECT 同一归一化，修掉 `' test '` 漏滤” | 注释必须描述 final 的真实行为，否则下一班人按旧注释维护会回退 | D3 |

### 3.1 没有改的部分（证明是最小修补）

以下 A 轨实现**原样保留**，不属于改动：

- 表名 `dws.dws_trade_channel_1d`、5 个字段名与顺序、`PARTITIONED BY (dt STRING)`、`STORED AS ORC`、`TBLPROPERTIES ('orc.compress'='SNAPPY')`。
- 单事实源 `dwd.dwd_pay_flow_di`，不 JOIN `dwd_order_main_di`（需求 §3 只把它用于订单唯一性校验）。
- 明细层 `SUM(pay_amt)`、`COUNT(DISTINCT order_id)`，AOV 在同层用 `gmv / NULLIF(order_cnt,0)` 计算。
- 流水级去重键 `(order_id, pay_seq)`、排序 `pay_time DESC, pay_amt DESC`、`rn=1`。
- 只靠 `dt='${dt}'` 归日，不加 `TO_DATE`。
- 维表 `GROUP BY channel_code, MAX(channel_name)` 防扇出。
- `channel_name` 兜底 `'未识别'`。
- 静态分区 `INSERT OVERWRITE ... PARTITION (dt='${dt}')`，无 `SELECT *`、无随机/时间函数、无 `LIMIT`。

### 3.2 改动与差异的对应关系

| 差异 | 裁决 | 是否改 final | 改动编号 |
|---|---|---|---|
| S1 维表粒度 | a | 否，保留 A | — |
| D1 other vs unknown | a | 否，保留 A 的 other | — |
| D2 name 兜底 | a | 否，保留 A 的 '未识别' | — |
| D3 空值/空白清洗 | merge | 是 | C2、C3、C4、C6 |
| D4 去重键 NULL 退化 | a | 否，保留 A 的严格主键 | — |
| D5 去重排序 | a | 否，保留 A 的 `pay_amt DESC` | — |
| D6 TO_DATE 双重归日 | a | 否，保留 A 的 `dt` 单过滤 | — |
| D7 AOV 精度 | b | 是 | C1、C5 |

---

## 4. 最终脚本与一致性核对

### 4.1 文件清单

| 文件 | 行数 | 说明 |
|---|---:|---|
| `requirements/渠道GMV日报需求20261122/需求开发员/监督者/final/01_dws_trade_channel_1d.sql` | 30 | DDL，A 轨 + C1/C2 |
| `requirements/渠道GMV日报需求20261122/需求开发员/监督者/final/02_etl_dws_trade_channel_1d.sql` | 74 | ETL，A 轨 + C3/C4/C5/C6 |

### 4.2 DDL 门禁（sk-sql-ddl，已执行）

命令：

```powershell
python skills\sk-sql-ddl\validate.py --sql "requirements\渠道GMV日报需求20261122\需求开发员\监督者\final\01_dws_trade_channel_1d.sql"
```

输出：

```json
{"ok": true, "errors": []}
```

### 4.3 契约门禁（comparison_report.json，已执行）

**注意：任务书给的第一种命令写法在本仓库会失败。** 原命令：

```powershell
python tools\validate_contracts.py contracts\comparison_report.schema.json requirements\渠道GMV日报需求20261122\需求开发员\监督者\comparison_report.json
```

实际输出（exit 1）：

```text
[FAIL] contracts\comparison_report.schema.json
        找不到对应 schema（期望按契约名匹配 contracts/<name>.schema.json）
```

原因：`tools/validate_contracts.py` 的用法是 `validate_contracts.py <doc> [--schema contracts/x.schema.json]`，第一个位置参数是**文档**，schema 只认 `--schema`；把 schema 放第一位会被当成文档，且第二个位置参数不被识别，`_guess_schema` 按 `comparison_report.schema` 找不到 `contracts/comparison_report.schema.schema.json`。这是**命令写法问题，不是报告不合规**。

可执行且通过的命令：

```powershell
python tools\validate_contracts.py "requirements\渠道GMV日报需求20261122\需求开发员\监督者\comparison_report.json" --schema "contracts\comparison_report.schema.json" --json
```

输出（路径中文在控制台显示为乱码，但 `ok` 为 true）：

```json
[
  {
    "file": "requirements\\...\\comparison_report.json",
    "schema": "contracts\\comparison_report.schema.json",
    "ok": true,
    "errors": []
  }
]
```

### 4.4 DDL 与 ETL 列一致性（人工核对）

| 顺序 | DDL 列 | 类型 | ETL 输出别名 | 表达式 |
|---:|---|---|---|---|
| 1 | `channel_code` | STRING | `channel_code` | `p.channel_code`（已归一） |
| 2 | `channel_name` | STRING | `channel_name` | `COALESCE(c.channel_name,'未识别')` |
| 3 | `gmv` | DECIMAL(18,2) | `gmv` | `CAST(p.gmv AS DECIMAL(18,2))` |
| 4 | `order_cnt` | BIGINT | `order_cnt` | `p.order_cnt`（`COUNT(DISTINCT ...)`） |
| 5 | `aov` | DECIMAL(18,4) | `aov` | `CAST(p.gmv / NULLIF(p.order_cnt,0) AS DECIMAL(18,4))` |

结论：5 列同名同序、类型匹配；`dt` 只在 `PARTITION` 子句，未出现在普通列定义中；无 `SELECT *`；单条 `INSERT OVERWRITE` 静态分区。

### 4.5 未执行的真实性声明

**没有在 Hive/Spark 上编译或执行过 final SQL。** 本机无 Hive/Spark，所有“通过”仅指静态 DDL 校验、契约校验和人工列一致性核对；需求 §6 的 5 条验收（分区行数、ADS 偏差、唯一键、AOV 算法、幂等）**一条都没有真跑**。P4 首跑前不得把本报告当作运行验证。

---

## 5. 遗留风险

> 按严重度排序；R1–R4 为高，R5–R9 为中，R10–R12 为低，R13–R14 为需求边界风险（R13 高、R14 中）。

| # | 风险 | 影响 | 触发条件 | 处置 | 责任阶段 |
|---|---|---|---|---|---|
| **R1** | 未编译、未执行 | 5 条验收全部未验证；字段名/类型/函数任一不兼容，首跑即失败 | 本机无 Hive/Spark | P4 在开发集群先 `EXPLAIN`/试跑一个小分区，再跑全量 | P4 |
| **R2** | `pay_seq` 可空性未证实 | D4 严格按 `(order_id, pay_seq)` 去重；若 `pay_seq` 有 NULL，同一订单多笔流水可能被合并（GMV 少算），重复回调也可能无法去重 | `pay_seq IS NULL` 存在 | 首跑前查 `SELECT COUNT(*) FROM dwd_pay_flow_di WHERE dt='...' AND pay_seq IS NULL`；若 >0，回 P3 重裁决 D4，不得在 final 里擅自加 `COALESCE(pay_seq,pay_id)` | P4 首跑前 |
| **R3** | 维表列名/分区与知识库不一致 | 需求 §3 写 `dim_channel_df(channel_code, channel_name)`；`knowledge/wiki/04-维表.md:59-64` 写主键 `channel_id`，字段 `channel_id, channel_name, channel_type, is_paid`。若实际是 `channel_id`，ETL 编译失败；若维表无 `dt` 分区，`WHERE dt` 失败 | 线上维表结构与需求稿不一致 | H2-3 先定列名；P4 用 `DESC dim_channel_df` 核对；若确为 `channel_id`，按 A self-check H8 的 3 处（DDL 列名 + ETL 两处 `AS`）同步，并检查维表 SELECT/JOIN 的列名；由 P1/P2 重出，不能由监督者改口径 | H2/P4 |
| **R4** | 线上同名旧表 | `CREATE EXTERNAL TABLE IF NOT EXISTS` 会静默跳过；`knowledge/wiki/03-事实表.md:116/121` 记录旧 `dws_trade_channel_1d` 是 `dt+channel_id` 结构、列不同。ETL 按 5 列插入会失败或写错 | 线上已存在同名旧表 | H2-2 定：确认无表 / DROP 重建 / 换新表名并迁历史；禁止用 `IF NOT EXISTS` 假装建表成功 | H2 |
| **R5** | 渠道码大小写未归一 | final 只 `TRIM`，不做 `LOWER()`；`'TEST'`/`'Test'` 不会被 `<> 'test'` 排除，测试 GMV 进入结果；`'APP'` 会与 `app` 分成两行、维表匹配失败（name 落 `'未识别'`），渠道维度被拆散。B self-check §4.3 自认未归一 | 上游存在大小写变体 | P4 先确认 `channel_code` 枚举；若确有变体，H2 决定是否 `LOWER(TRIM(...))`（会改变渠道码大小写语义，监督者未擅自加） | P4/H2 |
| **R6** | ADS 对账列名与 `'ALL'` 行 | 需求 §6.2 要与 `ads_trade_metric_1d` 同日同渠道比 GMV；`knowledge/wiki/05-取数路径.md:39` 说 ADS 用 `channel_id` 且要 `channel_id <> 'ALL'`。直接按 `channel_code` 对账会对不上 | ADS 列名/合计行未处理 | P4 写对账 SQL 时做 `channel_code→channel_id` 映射并排除 `'ALL'`；不改 ADS 口径（需求 §7） | P4 |
| **R7** | `other` 不在 CHANNEL 字典 | 本体/字典校验可能判 `other` 非法；ADS 若用别的兜底桶，对账出现差异 | 下游按 CHANNEL 值域做校验 | H2-4 决定是否补 `other` 进 CHANNEL（建议补，作为 ontology delta）；`channel_name='未识别'` 只作名称兜底，不字典化 | H2 |
| **R8** | 跨渠道订单重复计 order_cnt | 同一 `order_id` 在多个渠道支付，会出现在多个渠道的 `order_cnt`；各渠道 `order_cnt` 之和可能大于全站去重订单数。GMV 可加不受影响 | 存在跨渠道支付订单 | 这是“支付时刻渠道快照”口径的固有结果，不是 bug；在指标说明/下游注明渠道 AOV 的分母是渠道口径；若业务要全站订单数，另出指标，不在本表改 | P4/文档 |
| **R9** | 金额/状态字段名与枚举 | `pay_amt` vs `pay_amount`（A self-check H1）；`pay_status='success'` 是否为真实枚举（B 待确认 #3）。不符则编译失败或 0 行 | 上游字段名/枚举与需求稿不一致 | P4 首跑前 `DESC dwd_pay_flow_di` + `SELECT pay_status, COUNT(*) ... GROUP BY pay_status`；0 行也是失败，不是“当天没交易” | P4 |
| **R10** | AOV 下游误用 | 18,4 不防 `AVG(aov)`；若 BI/ADS 对日客单价求平均，小单量渠道权重被放大（`knowledge/04_踩坑/aov-vs-arpu.md`） | 下游图省事直接平均 | 在表 COMMENT/指标说明写明“跨天跨渠道必须 `SUM(gmv)/SUM(order_cnt)`”；P4 检查 ADS 取数 SQL | P4 |
| **R11** | 空日/上游缺分区 | ETL 写出 0 行；需求 §6.1 要求每 dt 分区行数 >0。若调度不区分“上游没来”和“当天没交易”，会漏报 | 上游分区缺失/延迟 | 调度侧加前置分区存在性检查；0 行时告警，不造兜底假数据（final 头部注释已声明） | P4 |
| **R12** | DQ 断言只查空串 | A 的验收 1 断言用 `channel_code=''`，纯空白不会报警；final 已处理空白，但 DQ 脚本未同步 | DQ 直接沿用 A 的断言 | P4 把 DQ 改成 `TRIM(channel_code)=''` 或直接复用 final 的归一化表达式 | P4 |
| **R13** | 取消订单未显式排除 | 两轨都只靠 `pay_status='success' AND pay_amt>0`，没有显式排除“支付后取消”的订单。若取消后 `pay_status` 仍为 `success`（知识库只说退款不改变 `pay_status`，没说取消），本表会把取消订单计入 GMV/订单数，违反 REQ §5“不含取消订单” | 取消订单仍有 success 流水 | P4 先查 `pay_status` 是否有 `cancel`/`closed` 等枚举；若支付后取消仍为 `success`，需 P1 明确“取消但已支付”是否计入（与“退款不回冲”的边界），P3 不自行加过滤 | P4/P1 |
| **R14** | 币种/运费假设 | 两轨都假设 `pay_amt` 已是人民币、不含运费；SQL 无币种/运费字段可校验 | 上游有多币种或运费包含在 `pay_amt` | P1 补口径/字段；P4 在首跑前抽查金额构成，P3 不自行加过滤 | P1/P4 |

### 5.1 需要 P1 澄清的共同口径边界（不是两轨冲突）

以下三项两轨做法一致，因此不构成“两轨口径冲突”，监督者**不退回 P1、也不自行调和**；但若 H2/P4 认为必须显式落地，需 P1 补需求：

1. **取消订单**：REQ §5 要求“不含取消订单”，但 §3 的 `dwd_pay_flow_di` 字段清单没有订单状态，`dwd_order_main_di` 又被限定为“仅校验订单唯一性”。两轨都只能靠 `pay_status='success'` 间接排除；支付后取消是否仍为 `success` 未证实（R13）。
2. **币种/运费**：REQ §5 要求“只人民币、不含运费”，两轨都假设 `pay_amt` 已满足，无字段可校验（R14）。
3. **`pay_seq` 可空性**：两轨主键都写 `(order_id, pay_seq)`，B 在 NULL 时退化 `pay_id`、A 严格；若 `pay_seq` 确实可空，严格去重可能合并真实分次支付（R2），这需要上游数据事实，不是 H2 能拍板的方案选择。

---

## 6. 需要人拍板的问题（H2）

> G3 的 H2 是“方案裁决评审”。以下 4 项需要 H2 明确回答；前 3 项不定，P4 不应开工。

### H2-1 是否批准本裁决（A 轨 + C1–C6）

- **要定什么**：接受“A 轨为主体、吸收 B 的 D3/D7”这一整体方案，还是改选 B、或退回 P3 重比。
- **选项**：
  1. **批准**（推荐）：按 final 进入 P4；C1–C6 已记账，差异 8 条已全覆盖。
  2. 改选 B：需接受 `unknown`、维表不聚合、`TO_DATE` 双重过滤、`pay_id` 排序四项与知识库/需求验收的冲突，监督者不建议。
  3. 退回 P3：仅在认为 8 条差异有漏项时；请指出具体漏项，不要泛泛“再比比”。
- **监督者建议**：批准。

### H2-2 线上同名表 `dws.dws_trade_channel_1d` 怎么处理

- **要定什么**：`CREATE EXTERNAL TABLE IF NOT EXISTS` 在旧表存在时会静默跳过；旧表是 `dt+channel_id` 结构（`knowledge/wiki/03-事实表.md:116/121`），与 final 的 5 列不兼容。
- **选项**：
  1. **确认线上无此表**，按 final 直接建（推荐，若确认无表）。
  2. **DROP 旧表重建**：需先备份/迁移历史分区，属于破坏性操作，必须 H2 签字。
  3. **换新表名**（如 `dws_trade_channel_1d_v2`）并迁移/双写：最安全，但需求 §4 指定了表名，需同步改需求/下游。
- **监督者建议**：先让 P4 用 `SHOW TABLES`/`DESC` 确认；有旧表则选 3，不用 `IF NOT EXISTS` 假装成功。

### H2-3 `channel_code` 还是 `channel_id`（需求与知识库的命名冲突）

- **要定什么**：需求 §3/§4 写 `channel_code`；`knowledge/wiki/04-维表.md:59-64` 与 `knowledge/wiki/05-取数路径.md:39` 的 ADS 用 `channel_id`。这是**需求稿与知识库的冲突**，不是两轨冲突；监督者无权改口径。
- **选项**：
  1. **以需求稿为准**，本表保留 `channel_code`，P4 在 ADS 对账/下游做 `channel_code→channel_id` 映射（推荐，改动最小）。
  2. **回 P1 把需求改成 `channel_id`**，与仓库命名/ADS 对齐；需 P1/P2 重出受影响的 DDL/ETL。
  3. 表内同时保留两列：违反“最小改动”，且需求 §4 未要求，不建议。
- **监督者建议**：按“需求稿是唯一口径来源”，默认选 1（保留 `channel_code`，P4 在对账/下游做 `channel_code→channel_id` 映射）；若 H2 认为必须与仓库/ADS 统一，则选 2 并回 P1 修订需求，不能由 P3/P4 私自改名。

### H2-4 `other` 与 `'未识别'` 是否进入 CHANNEL 字典

- **要定什么**：`ontology/dict/channel.yaml` 的 CHANNEL 值域只有 `[app, mini_program, h5, pc]`；final 会把未识别渠道写成 `other`、名称写 `'未识别'`。
- **选项**：
  1. **补 `other` 进 CHANNEL**（推荐）：作为 ontology delta，注明“未识别/缺失渠道的兜底桶，不参与渠道枚举校验”；`'未识别'` 只作 `channel_name` 兜底，不字典化。
  2. 维持字典不变，接受 `other` 为“字典外合法兜底”：需在下游校验白名单放行，文档注明。
  3. 改用 `unknown`：与 `knowledge/wiki/03-事实表.md:125` 的仓库惯例冲突，不建议。
- **监督者建议**：选 1，由 H2 授权更新本体字典；这是唯一需要动本体的点。

### H2-5（可一并定）渠道码（含 test）是否大小写归一

- **要定什么**：final 只排除小写 `'test'`、只做 `TRIM` 不做 `LOWER()`；若上游有 `'TEST'`/`'Test'`，测试渠道会漏滤；`'APP'` 也会与 `app` 拆成两行，维表匹配失败。
- **选项**：1. 先由 P4 确认 `channel_code` 枚举，确有变体再加 `LOWER(TRIM(...))`（推荐）；2. 现在就加 `LOWER()`，但会改变渠道码大小写语义（渠道码本应小写，风险低）；3. 不处理，接受漏滤/拆渠道风险。
- **监督者建议**：选 1，不在没有证据时改语义。

---

## 7. 门禁缺口（无法自动验证的检查项）

### 7.1 `sk-sql-guard` 无实现，G3 的“final 过 sk-sql-guard”无法执行

- 事实：`skills/sk-sql-guard/SKILL.md` 的 frontmatter 是 `status: spec`，正文第 11 行写明“只有规格，没有实现”；目录下没有 `validate.py`、`schema.json`、用例。
- 影响：G3 的 checks 中“final/ 全部脚本通过 sk-sql-guard”**没有可执行入口**，无法给出工具回执。
- 替代：用 `sk-sql-ddl` 校验 DDL + 人工核对 guard 的三条核心判据。人工核对结果：

| sk-sql-guard 判据 | final 核对 | 结果 |
|---|---|---|
| 写入必须带分区，且分区列在列定义之后 | `INSERT OVERWRITE ... PARTITION (dt='${dt}')`；DDL 中 `dt` 只在 `PARTITIONED BY`，不在普通列 | 通过 |
| 目标表列与 SELECT 列数、顺序一致 | 5 列 vs 5 列，同名同序（见 4.4） | 通过 |
| 禁用 `SELECT *` 写入 | final ETL 显式列名，无 `SELECT *` | 通过 |
| 单条写入语句、静态分区 | 单条 `INSERT OVERWRITE`，`dt` 为字面量参数 | 通过 |
| 无 `DROP`/`TRUNCATE`/`ALTER` | final 两个文件均无 | 通过 |

- **这不是“已通过 sk-sql-guard”**，只是“在工具缺失下用等价人工检查代替”。G3 复核若要求工具回执，需先实现 `skills/sk-sql-guard/validate.py`（超出监督者可写范围）。

### 7.2 无 Hive/Spark，5 条验收未执行

- 本机没有 Hive/Spark，无法编译、`EXPLAIN` 或试跑；需求 §6 的 5 条验收（分区行数 >0、ADS 偏差 ≤0.01%、唯一键、AOV 用 SUM/SUM、重跑幂等）**全部未验证**。
- 已做的最强验证是：DDL 静态校验 + ETL/DDL 列一致性人工核对 + B 轨用 sqlite 对 12 行夹具的复算（B self-check，非 Hive，不能替代真引擎）。
- 因此本报告的“通过”只覆盖静态门禁；P4 必须真跑，不能引用本报告声称验收通过。

### 7.3 契约校验命令的写法问题

- 任务书给的 `python tools\validate_contracts.py contracts\comparison_report.schema.json <report>` 在本仓库失败（exit 1），原因见 4.3：该工具是“文档在前、schema 用 `--schema`”。
- 正确命令已执行并通过：`python tools\validate_contracts.py "<report>" --schema "contracts\comparison_report.schema.json" --json` → `ok: true`。
- 建议 lead 在 G3 复核时使用正确命令；若要保留任务书写法，需改 `tools/validate_contracts.py` 的参数解析（超出监督者可写范围，且会影响其他契约校验）。

### 7.4 相关工具缺口（不直接属于 G3，但影响可复现性）

- `skills/sk-sql-dml` 同样只有 `SKILL.md`，没有 `validate.py`；本报告对 ETL 的 DML 检查是人工核对，不是工具回执。
- `tools/check_dual_track.py` 的机器比对结果是 lead 提供的输入，监督者未重跑；若 G3 要求可复现，应由 lead 保留其运行日志。

---

## 8. 交付物清单

| 交付物 | 路径 | 状态 | 证据 |
|---|---|---|---|
| 差异表 | `requirements/渠道GMV日报需求20261122/需求开发员/监督者/comparison.md` | 已写 | 8 条实质差异（0/1/7）+ 非实质清单 + 验证质量对比 |
| 机器可读报告 | `.../监督者/comparison_report.json` | 已写，契约通过 | `ok: true, errors: []`（正确命令，见 4.3） |
| 裁决报告 | `.../监督者/verdict.md` | 本文件 | — |
| 最终 DDL | `.../监督者/final/01_dws_trade_channel_1d.sql` | 已写 | `sk-sql-ddl` `{"ok": true, "errors": []}` |
| 最终 ETL | `.../监督者/final/02_etl_dws_trade_channel_1d.sql` | 已写 | 人工列一致性 + 单语句静态分区核对（未真跑） |

---

## 9. 下一步

1. **H2 先答 H2-1/H2-2/H2-3/H2-4**；H2-3 若选“回 P1”，本裁决的 DDL/ETL 字段名需 P1/P2 重出，P3 不自行改名。
2. H2 批准后进入 **P4**，首跑前按 R2/R3/R9 做三项上游确认（`pay_seq` 空值、维表列名/分区、`pay_amt`/`pay_status` 枚举），再在小分区试跑。
3. 试跑通过后按需求 §6 跑 5 条验收；ADS 对账按 R6 做 `channel_id` 映射并排除 `'ALL'`。
4. 若验收 2 的偏差 >0.01%，先查 `other` 桶、test 变体、跨渠道订单三项，不要直接改 GMV 口径；口径问题回 P1，实现问题回 P3。

---

**裁决生效条件**：H2 批准 H2-1，且 H2-2/H2-3/H2-4 有明确结论。未获 H2 批准前，final 仅作为 P3 建议稿，不得直接上生产。
