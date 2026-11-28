# design-notes — dws_trade_channel_1d（渠道 GMV 日报）

- 需求：`requirements/渠道GMV日报需求20261122/需求分析员/REQ-20261122-01.md`（REQ-20261122-01）
- 交付：`sql/01_dws_trade_channel_1d.sql`（DDL）、`sql/02_etl_dws_trade_channel_1d.sql`（日装载 DML）
- 粒度：天 × 渠道；唯一键 `dt + channel_code`；分区 `dt STRING`（`yyyy-MM-dd`）
- 口径来源只有 `ontology/`：`metric/atomic/gmv.yaml`(GMV)、`metric/atomic/order_cnt.yaml`(ORDER_CNT)、`metric/derived/aov.yaml`(AOV)、`dict/channel.yaml`(CHANNEL)。SQL 注释里只引用这四个 id，不另写一套定义。

---

## 1. 为什么是这个实现结构

**单条 `INSERT OVERWRITE ... PARTITION (dt = '${dt}')` + 两级子查询，不用 CTE，不 JOIN 订单主表。**

1. **一条语句、一个静态分区**。`INSERT OVERWRITE` 指定 `dt` 时只重写该分区，历史分区不被触碰——这是"按天补数"最省的写法，也是幂等的基础。用 `INSERT INTO` 会累积重复行，直接违反验收标准第 3 条。
2. **不用 `WITH ... INSERT`**。目标引擎按 Hive/Spark SQL 双兼容考虑，`WITH` 子句挂在 `INSERT` 前面的写法在不同 Hive 版本（尤其 1.x/2.x）支持不一致，容易在调度机上直接语法报错。两级派生表（`f0` → `f` → `p`）在任何版本都能跑，代价只是多一层缩进。
3. **不把 `dwd_order_main_di` 拼进指标链路**。需求稿把它列为输入，用途写的是"校验订单唯一性"，不是"取数"：
   - 它按 `create_time` 分区，`dt='${dt}'` 的订单里有一部分在次日才支付，把它们 JOIN 进来会**漏掉跨天支付的 GMV**；
   - 它的 `channel` 是**下单时点**的渠道，而本需求要的是**支付时刻**的渠道快照（见 §3）；
   - 它的 `order_amt` 是应付金额，不等于 `pay_amt`，混用会把运费/优惠算进 GMV。
   
   所以订单唯一性放到 DQ 校验里做（self-check §3），不进主链路。这也让 ETL 只依赖一张事实表 + 一张维表，链路短、可解释。
4. **维表只补名称，且必须带 `dt`**。`dim_channel_df` 是 `_df` 全量快照，按 `dt` 分区；漏掉 `dt` 条件会让每个渠道匹配到多天的多行，行数直接翻倍。这里用 `LEFT JOIN`：维表缺渠道时指标行必须保留（丢行 = GMV 合计对不上上游），`channel_name` 兜底成 `channel_code`。维表不参与任何指标计算，只做名称翻译。
5. **输出列严格等于需求契约**：`channel_code / channel_name / gmv / order_cnt / aov`。不塞下单量、退款额等"顺手"字段——`dws_trade_channel_1d` 在本需求范围里只承载渠道日报三指标，多一列就多一份口径维护成本。

## 2. 去重怎么处理

**重复来源有两类，处理方式不同：**

| 重复类型 | 现象 | 处理 |
|---|---|---|
| 重复回调 | 同一笔支付流水被渠道重发，`(order_id, pay_seq)` 相同但落多行 | `ROW_NUMBER() OVER (PARTITION BY order_id, COALESCE(pay_seq, pay_id) ...)` 取 `rn = 1` |
| 一单多笔流水 | 定金 100 + 尾款 50，两笔流水都是真实支付 | **不能**在流水层折叠，必须保留两行；订单数在聚合层用 `COUNT(DISTINCT order_id)` 收口 |

- 流水键取 `(order_id, pay_seq)`，这是 `dwd_pay_flow_di` 的声明主键（wiki 03-事实表）。`pay_seq` 为 NULL 时退化用 `pay_id`，保证同一订单的多笔真实流水不会被误折叠成一笔。
- 排序键 `ORDER BY pay_time DESC, pay_id DESC` 是**确定性**的：同一份输入无论跑几次、无论文件顺序如何，`rn = 1` 都落在同一行。这里刻意不按"金额最大"取——金额以最后到达的回调为准，按金额取会在补发一条更小金额的回调时改变历史结果，破坏幂等。
- 订单数用 `COUNT(DISTINCT order_id)` 而不是 `COUNT(1)`：wiki 02-度量 明确把"用 COUNT(1) 被重复回调打高"列为最易错点。
- 去重发生在**过滤之后**：先卡 `pay_status='success'`、`pay_amt > 0`、非 `test` 渠道，再 `ROW_NUMBER`。顺序反了会把"失败的重复回调"也纳入排序，虽然结果通常一样，但让 `rn` 的含义变得依赖数据巧合。

## 3. 渠道取值与空值

- 渠道取**支付流水上的 `channel_code`**，即支付时刻的快照，不取订单主表的下单渠道。这是需求"取支付时刻的渠道快照"的直接实现，也是与旧模板最大的差别之一（旧模板 `GROUP BY o.channel`，渠道来自下单时点）。
- `test` 渠道按口径边界排除。**注意 NULL 必须显式放行**：`channel_code <> 'test'` 在 `channel_code IS NULL` 时结果是 NULL，整行被 `WHERE` 滤掉，未识别渠道的 GMV 会静默消失。所以写成 `(channel_code IS NULL OR channel_code <> 'test')`。
- 空渠道不丢行：聚合时 `COALESCE(NULLIF(TRIM(channel_code), ''), 'unknown')` 归到 `unknown`，满足"channel_code 无空值"且不丢 GMV。
- **`'unknown'` 不在 ontology CHANNEL 值域内**（值域只有 app / mini_program / h5 / pc）。这是 wiki 03「未识别渠道归 other，不要丢行」与需求"渠道无空值"两条约束的折中：需要一个非空占位值。选 `unknown` 而不是 wiki 写的 `other`，理由是 `other` 容易被读成"其他渠道"这个真实业务分类。**这一项列入待确认**（self-check §4-1）：若口径负责人要求统一用 `other`，只改一处 `COALESCE` 字面量即可。

## 4. AOV 怎么算（比率不可加）

- 本行：`aov = gmv / NULLIF(order_cnt, 0)`，`CAST` 成 `DECIMAL(18,4)`。
- **绝不对日客单价求平均**。AOV 在 `ontology/metric/derived/aov.yaml` 里是 `non_additive`：`AVG(日 aov)` 会让订单量小的渠道/日期被过度加权，结果既不是 GMV/订单数，也没有业务含义。跨天、跨渠道汇总时必须回到 `SUM(gmv) / SUM(order_cnt)` 重算。
- 因此 DDL 里 `aov` 的注释写明"仅对本行成立，跨维度汇总请用 SUM(gmv)/SUM(order_cnt) 重算"，防止下游直接 `SUM(aov)`。
- `NULLIF(order_cnt, 0)` 是除零保护。理论上 `pay_amt > 0` 过滤后 `order_cnt ≥ 1`，但保护不能省：一旦上游口径变化（例如允许 0 元支付），没有 `NULLIF` 的语句会整批任务失败。
- 精度：`gmv` 落 `DECIMAL(18,2)`（分），`aov` 落 `DECIMAL(18,4)`。AOV 比 GMV 多两位，是为了在"客单价 ≈ 几十元"的量级上保留分以下的区分度，同时避免用 DOUBLE 引入浮点误差。

## 5. 幂等怎么保证

四个层面叠加，任一层单独都能兜住大部分场景：

1. **分区级覆盖**：`INSERT OVERWRITE ... PARTITION (dt = '${dt}')` 只重写目标分区，重跑 = 用同一份输入覆盖同一分区，不追加。
2. **确定性去重**：`ROW_NUMBER` 的排序键 `pay_time DESC, pay_id DESC` 全序且与执行计划无关，同输入必得同一 `rn = 1` 行。
3. **无随机/无时间函数**：SQL 里没有 `rand()`、`current_date`、`unix_timestamp()` 之类的运行时变量；`${dt}` 由调度显式传入，不设缺省值（缺省成"昨天"会把重跑写成错分区）。
4. **聚合可交换**：`SUM` / `COUNT(DISTINCT)` 与输入顺序无关，Spark 的多分区并行不影响结果。

验证：sqlite 逐行复算，同一夹具连跑两遍，`run2 == run1` 为 True（self-check §2）。

## 6. 与需求稿第 6 段五条验收标准的对应

| # | 验收标准 | 本实现如何满足 | 验证位置 |
|---|---|---|---|
| 1 | 每个 dt 分区行数 > 0，`channel_code` 无空值 | 只要当日有 `pay_status='success' AND pay_amt>0` 的流水就必产出至少一行（空渠道被 `COALESCE(...,'unknown')` 兜住，不会因空值丢行）；`channel_code` 是 `GROUP BY` 键且已 `COALESCE`，不可能为 NULL/空串 | self-check §3-A、§3-B；sqlite 夹具中空渠道行归入 `unknown`，空渠道行数 = 0 |
| 2 | 与 `ads_trade_metric_1d` 同日同渠道 GMV 偏差 ≤ 0.01% | 两条链路同源 `SUM(pay_amt)`、同按 `pay_time` 归日、同排除 `test` 渠道；差异只可能来自"重复回调是否去重"和"退款是否回冲"，本实现在这两点上与 ontology 一致（去重、不回冲） | self-check §3-C 给出对账 SQL；实际偏差需在有数据的 env 跑，当前无库，列为待确认 §4-3 |
| 3 | 同一 `dt + channel_code` 只有一行 | `GROUP BY COALESCE(NULLIF(TRIM(channel_code),''),'unknown')` 单键聚合，天然唯一；维表 `LEFT JOIN` 前已按 `dt` 过滤且 `channel_code` 在快照内唯一 | self-check §3-B；sqlite 重复主键组 = 0 |
| 4 | `aov` 用 `SUM(gmv)/SUM(order_cnt)`，不允许对日客单价求平均 | 在**同一聚合层**用聚合后的 `p.gmv / p.order_cnt` 计算，不存在"先算日 AOV 再平均"的路径；DDL 注释禁止下游 `SUM(aov)` | §4 上文；sqlite 断言 app = 180/2 = 90 |
| 5 | 重跑同一分区结果一致 | §5 四层保障 | self-check §2 `run2 == run1: True`；§3-F 幂等比对 SQL |

## 7. 与旧模板 `templates/dml/dws_trade_channel_1d.sql` 的差异（为什么没照抄）

旧模板可跑，但直接照抄会同时违反需求契约和三条口径，逐条列明：

| 旧模板做法 | 问题 | 本实现 |
|---|---|---|
| `FROM dwd_order_main_di o LEFT JOIN dwd_pay_flow_di p` | 以订单主表为驱动：无支付订单也进结果（`pay_amt` 为 NULL），且按 `create_time` 分区会漏掉跨天支付 | 以支付流水为唯一驱动表，只出"当日有成功支付"的渠道 |
| `GROUP BY o.channel` | 渠道取下单时点，不是支付时刻快照 | 取 `dwd_pay_flow_di.channel_code` |
| 未对 `(order_id, pay_seq)` 去重 | 重复回调使 GMV 与订单数同时虚高 | `ROW_NUMBER` 去重后再聚合 |
| 输出 `pay_amt / order_create_cnt / pay_order_cnt ...` | 列名与需求契约（`channel_code/channel_name/gmv/order_cnt/aov`）不一致，且把下单量与支付量混在一张表 | 严格 5 列，只做渠道支付日报 |
| `aov` 直接相除无 `NULLIF` | 分母为 0 时任务失败或产出 NULL 语义不明 | `NULLIF(order_cnt, 0)` + 明确 CAST |
| 分区变量 `${bizdate}` | 与本需求约定的 `${dt}` 不一致，调度传参对不上 | `${dt}`，且不设缺省 |
| 未处理未识别渠道 | 空渠道要么丢行、要么写空值，违反验收 1 | `COALESCE(...,'unknown')` 收口 |

同时保留了旧模板值得沿用的部分：`INSERT OVERWRITE` 静态分区、文件头注释块（表/粒度/输入/口径/用法）、`_1d` 命名与 `dt` 分区约定。

## 8. 待确认（未落进 SQL 的部分）

1. 未识别渠道占位值用 `unknown` 还是 `other`（见 §3）。
2. 维表键名：需求写 `channel_code`，wiki 04 写 `channel_id`。SQL 按需求用 `channel_code`，若实际宽表列名是 `channel_id` 需改 2 处（ETL 第 67 行子查询列名、第 71 行 JOIN 条件）。
3. `pay_status='success'` 的取值：全仓无 `pay_status` 字典，该字面量取自 `dwd_pay_flow_di` 的现状约定，需上游确认枚举完整值（是否有 `SUCCESS`/`1` 等变体）。
4. 与 `ads_trade_metric_1d` 的实际偏差未在本机验证（无库）。

详见 `self-check.md` §4。
