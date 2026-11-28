# REQ-20261122-01 双轨比对报告（P3）

| 字段 | 值 |
|---|---|
| run_id | `20261122-01` |
| 需求编号 | `REQ-20261122-01` |
| 需求稿（唯一口径来源） | `requirements/渠道GMV日报需求20261122/需求分析员/REQ-20261122-01.md` |
| 轨道 A | `requirements/渠道GMV日报需求20261122/需求开发员/developer-1/` |
| 轨道 B | `requirements/渠道GMV日报需求20261122/需求开发员/developer-2/` |
| 机器比对 | 两轨 SQL 无相同文件；DDL 相似度 0.364、ETL 0.39；无跨轨泄漏（`tools/check_dual_track.py`，lead 已跑） |
| 裁决 | **取 A 轨，吸收 B 轨 2 处实现改进（渠道码空值/空白归一、AOV 18,4）** |
| 差异条数 | **8 条：口径 0 / 结构 1 / 实现 7**（裁决 a=6、b=1、merge=1） |

## 0. 结论先说

- 两轨在 **GMV、ORDER_CNT、AOV、CHANNEL** 四个指标口径上逐条一致，**没有需要退回 P1 的口径冲突**。
- 结构层只有一处差异：维表关联前的粒度（A 先聚合、B 直接 JOIN）。A 的做法直接服务于“同 dt+channel_code 只有一行”的验收，选 A。
- 实现层 A 更贴近仓库既有约定（未识别渠道归 `other`、严格按 `(order_id, pay_seq)` 去重、分区即归日）；B 有两处确实更好：渠道码空值/空白归一、AOV 保留 4 位。最终脚本 = A + 这两处，逐条改动见 `verdict.md`。

## 1. 第一层：口径（semantic）

### 1.1 逐条核对结果：0 条实质分歧

| 口径点 | 需求稿 / 本体依据 | A 轨 | B 轨 | 核对 |
|---|---|---|---|---|
| GMV 定义 | `ontology/metric/atomic/gmv.yaml` id `GMV`；REQ §2、§5 | `SUM(pay_amt)`，过滤 `pay_status='success' AND pay_amt>0` | 同 | 一致 |
| GMV 归日 | `GMV` caliber“按 `pay_time` 归日”；REQ §2、§5 | 依赖 `dt='${dt}'`（分区按 `pay_time`） | 同，另加 `TO_DATE(pay_time)=TO_DATE('${dt}')`（见 D6） | 归日字段一致，仅校验强度不同 |
| 退款不回冲 | `GMV` caliber“退款不回冲，跨天退款也不调整历史 GMV”；REQ §5 | 不读退款表、不做负值回冲 | 同 | 一致 |
| 不含运费 | REQ §5；`GMV` caliber | 只 `SUM(pay_amt)`，无运费列 | 同 | 一致 |
| 支付订单数 | `ontology/metric/atomic/order_cnt.yaml` id `ORDER_CNT`；REQ §2 | `COUNT(DISTINCT order_id)` | 同 | 一致 |
| AOV | `ontology/metric/derived/aov.yaml` id `AOV`（non_additive）；REQ §6.4 | 同层 `gmv / NULLIF(order_cnt,0)`，未做任何平均 | 同 | 一致 |
| 渠道取值 | `ontology/dict/channel.yaml` id `CHANNEL`；REQ §2“支付时刻渠道快照” | 取流水 `channel_code`，缺失归 `other`，非空非字典值保留原码 | 取流水 `channel_code`，缺失/空白归 `unknown`，非空非字典值保留原码 | 快照时点一致；兜底值不同见 D1 |
| 测试渠道 | REQ §5“不含 `channel_code='test'`” | `COALESCE(channel_code,'') <> 'test'` | `channel_code IS NULL OR channel_code <> 'test'` | 对 NULL 的写法不同，逻辑等价；空格/大小写变体见 D3 与遗留风险 |
| 币种 | REQ §5“只人民币” | 无币种字段，按人民币处理 | 同 | 一致 |

### 1.2 三条“疑似口径”为什么不构成口径冲突

1. **D1 `other` vs `unknown`**：两轨都同意“未识别渠道不丢行、聚成一个桶”，分歧只在桶的名字。`knowledge/wiki/03-事实表.md:125` 已经把仓库惯例钉为 `other`，B 的 `unknown` 是无依据偏离，不是另一套指标定义。不影响 GMV/订单数/归日，因此按实现层裁决，不回 P1。
2. **D3 空串/空白清洗**：这是“怎么表示缺失渠道”的异常处理，不是“渠道是什么”的口径。REQ §6.1 要求 `channel_code` 无空值，B 的 `NULLIF(TRIM(...))` 更直接地满足它，因此归实现层。
3. **D4 去重键的 NULL 退化**：两轨的主键都是 `(order_id, pay_seq)`（`knowledge/wiki/03-事实表.md:65,73`），B 只是在 `pay_seq` 为空时退化到 `pay_id`。同一主键下的降级路径，不是两套去重口径；且降级本身未经数据验证，因此按实现层裁决并留待确认。

**口径结论：0 条实质差异，不退回 P1。**

## 2. 第二层：结构（structure）

### 2.1 差异

| # | 层面 | 差异点 | A 轨 | B 轨 | 依据 | 裁决 |
|---|---|---|---|---|---|---|
| S1 | 结构 | 维表侧关联粒度 | 先把 `dim_channel_df` 聚合到 `channel_code` 唯一（`GROUP BY channel_code, MAX(channel_name)`，A ETL L62-69），再 LEFT JOIN | 直接 `SELECT channel_code, channel_name` 后 LEFT JOIN（B ETL L66-70），维表同码多行会把事实行放大 | REQ §6.3“同 dt+channel_code 只有一行”；`knowledge/wiki/04-维表.md:59-64` 维表主键是 `channel_id` 而不是 `channel_code`，按 `channel_code` 关联不能假定唯一；A self-check §3.3 也把“维表 JOIN 放大”列为唯一键失败的首因 | **a** |

### 2.2 结构层一致项（无差异）

| 结构点 | A 轨 | B 轨 | 结论 |
|---|---|---|---|
| 表粒度 | 天 × 渠道，一个 `dt` 下每个 `channel_code` 一行 | 同 | 一致 |
| 主键 | 逻辑主键 `dt + channel_code`，ETL `GROUP BY` 保证 | 同 | 一致 |
| 分区 | `dt STRING`，静态分区 `PARTITION (dt='${dt}')` | 同 | 一致 |
| 输出列 | `channel_code, channel_name, gmv, order_cnt, aov`（+ 分区 `dt`） | 同 | 一致 |
| JOIN 方向 | 事实聚合结果 LEFT JOIN 维表（维表缺失不丢行） | 同 | 一致 |
| 周同比列 | 不落列，查询侧自关联 | 同 | 一致 |

**结构结论：只有 S1 一条，选 A。** 维表先聚合是“保证唯一键”的结构性动作，不是可选优化；B 依赖“`channel_code` 在维表里唯一”这一未经证实的假设。

## 3. 第三层：实现（implementation）

| # | 层面 | 差异点 | A 轨 | B 轨 | 依据 | 裁决 |
|---|---|---|---|---|---|---|
| D1 | 实现 | 未识别渠道的兜底值 | `COALESCE(channel_code,'other')`；DDL 注释“缺失归 other，非空非字典值保留原码”（A ETL L43、DDL L21） | `COALESCE(NULLIF(TRIM(f.channel_code),''),'unknown')`；DDL 注释“未识别渠道落 unknown”（B ETL L30、L62、DDL L19） | `knowledge/wiki/03-事实表.md:125`「未识别渠道归 other，不要丢行，否则总数对不上」；`ontology/dict/channel.yaml` 的 `CHANNEL` 值域只有 app/mini_program/h5/pc，`other`/`unknown` 都不在字典内（本体缺口，见 H2-4） | **a**（用 `other`） |
| D2 | 实现 | 维表未匹配时 `channel_name` 的兜底 | `COALESCE(c.channel_name,'未识别')`（A ETL L21） | `COALESCE(d.channel_name, p.channel_code)`，名称缺失时复制渠道码（B ETL L21） | REQ §4 只要求输出 `channel_name`，未规定兜底；`knowledge/wiki/03-事实表.md:125` 的 `other` 约定只针对渠道码。A 的“未识别”把“维表缺行”显式暴露出来，且 `channel_code` 列仍保留原码；B 把码复制进名称列会掩盖维表缺口 | **a** |
| D3 | 实现 | 渠道码空值/空白的清洗强度 | 只处理 NULL：`COALESCE(channel_code,'other')`；空串 `''` 会原样进入结果，纯空白更不会处理 | `NULLIF(TRIM(channel_code),'')` 同时处理 NULL、空串、前后空白；但 test 过滤仍用原始值，`' test '` 先通过过滤、再在聚合处被 TRIM 成 `'test'`，测试渠道会漏进结果（B self-check §4.3 自认） | REQ §6.1“`channel_code` 无空值”；A self-check §3.1 用 `channel_code=''` 断言 `empty_cnt=0`，但 A 的 SQL 并不能保证；B self-check §4.3 暴露了 TRIM 与过滤不同源的新缺口 | **merge**：采用 B 的 `NULLIF(TRIM(...),'')` 归一，但保留 A 的 `other`；并把同一表达式用于 test 过滤，保证 `' test '` 也被排除。见 `verdict.md` C3/C4 |
| D4 | 实现 | 去重键在 `pay_seq` 为空时的退化 | `PARTITION BY order_id, pay_seq`，严格按声明主键（A ETL L45） | `PARTITION BY order_id, COALESCE(pay_seq, pay_id)`，空值退化到 `pay_id`（B ETL L46） | `knowledge/wiki/03-事实表.md:65` 主键 `order_id + pay_seq`；:73“必须按 (order_id, pay_seq) 去重”；`knowledge/wiki/05-取数路径.md:33` 同。没有证据表明 `pay_id` 可以替代：重复回调若共享 `pay_id`，退化仍不能去重；若各自生成新 `pay_id`，退化会把重复回调留下 | **a**（严格按声明主键；`pay_seq` 可空性作为 P4 首跑前确认项，见遗留风险 R2，不在脚本里猜） |
| D5 | 实现 | 去重排序的并列打破键 | `ORDER BY pay_time DESC, pay_amt DESC`（A ETL L46） | `ORDER BY pay_time DESC, pay_id DESC`，理由“金额以最后到达的回调为准”（B ETL L47） | `knowledge/wiki/03-事实表.md:73` 重复回调是“同一笔流水落多条”，正常情况各列相同，并列键只影响脏数据；A 的键只用已选列、是确定的全序，且不引入“`pay_id` 越大越晚到”的未证实假设；`pay_id` 在同一笔流水的重复行上可能相同，无法保证全序 | **a** |
| D6 | 实现 | 归日是否再加一层 `TO_DATE` 过滤 | 只靠 `dt='${dt}'`（分区按 `pay_time` 归日） | 再加 `TO_DATE(f0.pay_time)=TO_DATE('${dt}')`（B ETL L54） | `knowledge/wiki/03-事实表.md:66` 分区 `dt` 就是按 `pay_time` 归日；REQ §2/§5 的归日字段是 `pay_time`。B self-check 夹具 P08 显示这层过滤会把“分区错标”的行**静默丢掉**（少算 GMV），而 A 的做法会让偏差在 ADS 对账（REQ §6.2）暴露；`TO_DATE` 对 TIMESTAMP 的时区/类型行为 B 也未在真引擎验证（B self-check §4.1） | **a**（信任分区契约；上游错标用 DQ 暴露，不静默丢行） |
| D7 | 实现 | `aov` 存储精度 | DDL `DECIMAL(18,2)`，ETL `CAST(... AS DECIMAL(18,2))`（A DDL L25、ETL L25） | DDL `DECIMAL(18,4)`，ETL `CAST(... AS DECIMAL(18,4))`（B DDL L23、ETL L24） | `ontology/metric/derived/aov.yaml` id `AOV`：派生比率、non_additive；2 位小数在存储时就舍入，4 位只多占极少空间、下游展示仍可再舍。`knowledge/wiki/01-命名与词根.md:53` 的 `DECIMAL(18,2)` 规则针对 `_amt` 金额字段，`aov` 不是 `_amt`；且 AOV 的正确用法是 `SUM(gmv)/SUM(order_cnt)` 重算，精度不改变不可加性 | **b**（采用 18,4） |

### 3.1 不计入裁决表的非实质差异（已逐条核对，避免“漏报”）

| 项 | A 轨 | B 轨 | 处理 |
|---|---|---|---|
| 去重子查询多投影 `pay_time` | 不投影（A ETL L38-43） | 投影 `f0.pay_time`（B ETL L44），下游未使用 | 不选 B 的写法；窗口 `ORDER BY` 可直接引用源列，多一列只会加宽 shuffle。无正确性影响 |
| 文件头与列注释措辞 | 引用四份 ontology id，解释“不落周同比列” | 增加 `hive --hivevar` 用法与“不设缺省 dt”说明；`gmv`/`order_cnt`/表注释措辞不同 | 沿用 A 的注释风格（可追溯性更强）；B 的用法说明有运维价值，但不改执行逻辑。final 只同步本次改动涉及的注释 |
| test 过滤的 NULL 写法 | `COALESCE(channel_code,'') <> 'test'` | `channel_code IS NULL OR channel_code <> 'test'` | 逻辑等价，不构成差异；D3 统一归一化后两者都收敛到同一表达式 |
| `GROUP BY` 用别名还是表达式 | `GROUP BY d.channel_code` | `GROUP BY COALESCE(NULLIF(TRIM(f.channel_code),''),'unknown')` | 等价写法；final 沿用 A 的“先投影、再按别名聚合”，可读性更好 |
| 表别名、空格、`CAST` 书写位置 | `d`/`c` | `f`/`d` | 无语义差异 |
| 静态分区写法 | `PARTITION (dt = '${dt}')` | `PARTITION (dt='${dt}')` | 等价 |

### 3.2 验证质量对比（不作为裁决项）

- A 轨：`sk-sql-ddl/validate.py` 通过；做了文本级 DDL/DML 一致性、无 `SELECT *`、静态分区、无随机函数检查；给出 REQ §6 五条验收的可执行断言 SQL，但**未在 Hive/Spark 执行**（A self-check §1、§3）。
- B 轨：同样通过 DDL 校验；额外用 sqlite 对 12 行夹具复算，覆盖重复回调、定金/尾款、失败/零元、跨日错标、空渠道、test、字典外渠道等 9 类边界，run2==run1（B self-check §2）。这是比 A 更强的**逻辑证据**，但 sqlite 不是 Hive，`TO_DATE`/`ROW_NUMBER`/ORC 行为仍是“按文档应当如此”，不能替代真机验证。
- 两轨都明确声明“未真跑”，没有把断言 SQL 当成已通过；这一点一致，不构成差异。

### 3.3 两轨共同的未覆盖点（不计入差异条数，但影响需求 §5 合规）

1. **取消订单**：两轨都只靠 `pay_status='success' AND pay_amt>0`，没有显式排除“支付后取消”的订单。若取消后 `pay_status` 仍为 `success`（知识库只说退款不改变 `pay_status`，没说取消），本表会把取消订单计入 GMV/订单数，与 REQ §5“不含取消订单”冲突。需求稿 §3 的 `dwd_pay_flow_di` 字段清单也没有订单状态列，`dwd_order_main_di` 又被限定为“仅校验订单唯一性”；这是**需求边界与输入字段的共同缺口**，不是两轨谁对谁错。需 P1 明确取消订单的判定字段/枚举，或确认“支付后取消”仍按退款不回冲计入。
2. **币种与运费**：两轨都假设 `pay_amt` 已是人民币、且不含运费；SQL 没有币种/运费字段可校验。若上游不成立，需 P1 补口径，P3 不自行加过滤。
3. **外部依赖**：`pay_seq` 可空性、`pay_status` 枚举、维表列名 `channel_code`/`channel_id` 是两轨共同依赖，见 `verdict.md` R2/R3/R9；它们不构成两轨差异，但会让 final 首跑失败或算错。

## 4. 汇总

| 层面 | 条数 | 裁决分布 |
|---|---|---|
| 口径 semantic | 0 | — |
| 结构 structure | 1（S1） | a=1 |
| 实现 implementation | 7（D1-D7） | a=5、b=1、merge=1 |
| **合计** | **8** | **a=6、b=1、merge=1** |

- 每条裁决都带依据：本体 id（`GMV`/`ORDER_CNT`/`AOV`/`CHANNEL`）、需求稿段落（§2/§4/§5/§6）、知识库条目（`knowledge/wiki/03-事实表.md`、`04-维表.md`、`05-取数路径.md`、`01-命名与词根.md`）或两轨 self-check 的具体条目。
- 没有“两版都好”的中间结论：物理结构、去重键、归日校验、兜底值都明确选了一边；只有 D3 是真正的合并（B 的归一化 + A 的 `other`），且合并理由可验证。
- 改动只落在 D3、D7 两处，外加注释同步；没有重写 A 的聚合结构、没有改指标公式、没有引入新表/新列。

## 5. 相对 A 轨的改动（C1–C6，逐条记账）

| 编号 | 文件:行 | 改动 | 对应差异 |
|---|---|---|---|
| C1 | `final/01_dws_trade_channel_1d.sql:25` | `aov DECIMAL(18,2)` → `DECIMAL(18,4)` | D7 |
| C2 | `final/01_dws_trade_channel_1d.sql:21` | `channel_code` 注释“缺失归 other” → “缺失或空白归 other” | D3 |
| C3 | `final/02_etl_dws_trade_channel_1d.sql:45` | `COALESCE(channel_code,'other')` → `COALESCE(NULLIF(TRIM(channel_code),''),'other')` | D3 |
| C4 | `final/02_etl_dws_trade_channel_1d.sql:60` | test 过滤改用与 C3 相同的归一化表达式 | D3 |
| C5 | `final/02_etl_dws_trade_channel_1d.sql:25` | `CAST(... AS DECIMAL(18,2))` → `DECIMAL(18,4)` | D7 |
| C6 | `final/02_etl_dws_trade_channel_1d.sql:41-44、56-59` | 注释同步 C3/C4 的新行为 | D3 |

未改动项：表名/5 列/分区/ORC/SNAPPY、单事实源、`SUM(pay_amt)`、`COUNT(DISTINCT order_id)`、`(order_id,pay_seq)` 去重、`pay_time DESC, pay_amt DESC` 排序、`dt='${dt}'` 单过滤、维表 `GROUP BY` 防扇出、`'未识别'` 名称兜底、静态分区 `INSERT OVERWRITE`。完整理由与风险见 `verdict.md`。
