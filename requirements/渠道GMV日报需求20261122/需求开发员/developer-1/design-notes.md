# 设计说明 · dws_trade_channel_1d（渠道 GMV 日报）

- 需求：`REQ-20261122-01`（`requirements/渠道GMV日报需求20261122/需求分析员/REQ-20261122-01.md`）
- 轨道：developer-1（独立轨道，未与 developer-2 做任何对齐）
- 交付：`sql/01_dws_trade_channel_1d.sql`（DDL）、`sql/02_etl_dws_trade_channel_1d.sql`（DML）

## 1. 一句话方案

**单事实源 + 单层聚合**：只从 `dwd.dwd_pay_flow_di` 的 `${dt}` 分区取数，流水级去重后按 `channel_code` 一次 `GROUP BY`，同一层同时产出 `gmv` 与 `order_cnt`，`aov` 由这两个值当场相除；渠道名在聚合之后才左关联维表。

链路：`dwd_pay_flow_di(dt=${dt})` → 流水去重 → 按渠道聚合 → 左关联 `dim_channel_df(dt=${dt})` → `dws_trade_channel_1d(dt=${dt})`。

## 2. 为什么是这个实现结构

### 2.1 事实只认支付流水，不认订单主表

`ontology/object/order.yaml` 写明「订单金额是应付，不是实付，实付要看支付流水」，`ontology/metric/atomic/gmv.yaml` 的 caliber 是「以支付流水为准，按 pay_time 归日」。所以：

- GMV 的分子只能是 `dwd_pay_flow_di.pay_amt`，不能用 `dwd_order_main_di.order_amount`/`pay_amt`（后者是下单口径，含未支付订单，且订单主表的 `pay_amt` 与流水口径不同）。
- 归日只认 `dt`（= `pay_time` 所在日期，见 `knowledge/wiki/03-事实表.md:66`），不按 `create_time`。跨天支付（23:59 下单、00:01 支付，或定金/尾款跨天）自然落到支付那天，**不需要任何回看窗口**。

### 2.2 渠道取自支付流水的 `channel_code`，不从订单主表 join

需求稿第 2 段要求「下单渠道，取支付时刻的渠道快照」。三个候选里选 `dwd_pay_flow_di.channel_code`：

| 候选 | 结论 | 理由 |
|---|---|---|
| `dwd_pay_flow_di.channel_code` | **采用** | 就是"支付时刻的渠道快照"，事件时间与归日键同源，无跨分区问题 |
| `dwd_order_main_di` 的渠道列 | 不用 | ① 列名在本仓库自相矛盾：模板 `templates/ddl/dwd_order_main_di.sql:13` 叫 `channel`，`knowledge/wiki/03-事实表.md:36` 叫 `channel_id`，猜错即全表报错；② 该表分区按 `create_time`，要拿跨天支付的渠道必须回看 N 天分区，N 无依据，且会引入扇出 |
| `dwd_pay_flow_di.pay_channel` | 不用 | 语义是支付方式（微信/支付宝/银联，`knowledge/wiki/03-事实表.md:70`），不是交易渠道（app/mini_program/h5/pc），混用会把"渠道"变成"支付工具" |

`dwd_order_main_di` 在本方案里只用于**订单唯一性校验**（见 `self-check.md` 的 DQ 断言），不参与 GMV 计算。

### 2.3 一层聚合，不建中间表

当天数据量是"一个分区的支付流水"，聚合后最多几行。拆 tmp 表只会多一次落盘、多一个需要清理的分区，收益为零。所以整条链路是一条 `INSERT OVERWRITE ... SELECT`，用两层内联子查询表达（不用 `WITH`，规避 Hive/Spark 在 `INSERT ... WITH` 上的语法差异）。

### 2.4 不落"上周同日"列

需求稿第 1 段的"支持与上周同日对比"由查询侧 `dt` 与 `date_sub(dt, 7)` 自关联实现。若落成 `gmv_wow` 列：每天要多读一个 7 天前分区；历史分区被回刷时，两边的对比值会互相不一致（A 分区存着旧 B 分区算出的值）。对比是查询能力，不是本表的粒度。

## 3. 去重怎么处理（三层，各管一件事）

| 层 | 问题 | 做法 | 如果漏了会怎样 |
|---|---|---|---|
| 流水级 | 渠道重发支付通知，同一笔流水落多条（`knowledge/wiki/03-事实表.md:73`） | `ROW_NUMBER() OVER (PARTITION BY order_id, pay_seq ORDER BY pay_time DESC, pay_amt DESC)` 取 `rn=1` | GMV 与订单数同时虚高（`COUNT(1)` 的经典坑） |
| 订单级 | 一个订单多笔流水（定金/尾款、分次支付） | `COUNT(DISTINCT order_id)` | 用 `COUNT(1)` 会把流水笔数当订单数；反之按 `order_id` 去重流水会**少算 GMV** |
| 维表级 | `dim_channel_df` 同码多行（SCD 残留、脏数据） | 先 `GROUP BY channel_code` + `MAX(channel_name)` 再 `LEFT JOIN` | 事实行被放大成多行，直接违反验收标准 3 |

两个被明确否决的写法：

- ❌ `PARTITION BY order_id` 去重：会把定金/尾款的第二笔流水合并掉，GMV 少算，而且少算的量随支付节奏变化，不可解释。
- ❌ `COUNT(DISTINCT order_id)` 但不做流水去重：订单数看起来对，GMV 仍然被重复回调放大——**两个指标的去重不能互相替代**。

去重键取 `(order_id, pay_seq)`：这是 `knowledge/wiki/03-事实表.md:65` 写明的流水主键，也是该文档要求的去重方式。取 `rn=1` 的排序键用 `pay_time DESC, pay_amt DESC`（都是确定值），保证重跑取到同一行——不用 `rand()`，否则幂等直接失效。

## 4. AOV 怎么算（比率不可加）

`ontology/metric/derived/aov.yaml` 的 `additivity: non_additive`，caliber 要求「分子 GMV、分母 ORDER_CNT 必须同维度同时间范围；跨天汇总要用 SUM(GMV)/SUM(ORDER_CNT)，不能 AVG(日客单价)」。

实现上做了三件事：

1. **同一层算完分子分母再相除**：`gmv`、`order_cnt` 由同一个 `GROUP BY channel_code` 产出，`aov = gmv / order_cnt`。不存在"先算日 AOV 再平均"的路径，因为本脚本里根本没有 `AVG`。
2. **只把 `aov` 当行级冗余列**：DDL 的列注释、表注释都写明"跨天/跨渠道汇总必须 `SUM(gmv)/SUM(order_cnt)` 重算"。这一列只服务"看这一行"的场景（对应 `knowledge/wiki/03-事实表.md:172` 对 `ads_trade_metric_1d.aov` 的同款警告）。
3. **除零保护**：`NULLIF(p.order_cnt, 0)`。实际上 `pay_amt > 0` 且 `pay_status='success'` 保证了 `order_cnt ≥ 1`，这是防御性写法，不是兜底假数据。

舍入：结果 `CAST(... AS DECIMAL(18,2))`，与金额列同精度（元，两位小数）。舍入只影响展示，不影响任何下游加总——下游必须回到 `gmv`/`order_cnt` 重算。

另外：**没有引入 `REFUND_RATE`**。需求稿第 2 段已与需求方确认「退款不回冲」，退款是独立指标，本表不建退款列、不做净额扣减。

## 5. 幂等怎么保证

| 手段 | 作用 |
|---|---|
| `INSERT OVERWRITE TABLE ... PARTITION (dt = '${dt}')` 静态分区 | 只重写目标分区。同参数重跑 = 用同一份源数据覆盖同一分区，结果必然一致；不产生重复行，不需要先删 |
| 源侧只读 `dt = '${dt}'` 单分区 | 源数据是已落定的历史分区，不随重跑时刻变化 |
| `ROW_NUMBER` 排序键全为确定值（`pay_time`、`pay_amt`） | 重复流水的"取哪一条"在每次执行中相同，不会因执行计划变化而换行 |
| 无 `rand()` / `current_timestamp` / `now()` / 变量时间窗 | 脚本里不存在"运行时刻"这个输入 |
| 无 `LIMIT`、无采样 | 结果集完全由源分区决定 |

**迟到数据**：T+1 补报的流水只影响它自己的 `pay_time` 分区，重跑对应 `dt` 即可修正，不需要回刷其他分区。这也是"不落周同比列"的另一个原因——落列会让迟到数据变成跨分区一致性问题。

## 6. 空值、值域与边界

| 情况 | 处理 | 理由 |
|---|---|---|
| `channel_code` 为 NULL | 归 `'other'` | 验收标准 1 要求 `channel_code` 无空值；且不能丢行（丢了 GMV 合计对不上，见 `knowledge/wiki/03-事实表.md:125`）。用 `'other'` 而不是自造 `'unknown'`，是跟仓库既有惯例与 ADS 对齐，避免对账时凭空多出一条差异 |
| 渠道码非空但维表无此行 | 保留原码，`channel_name` 归 `'未识别'` | 新增渠道要先改字典再加维表行（`knowledge/wiki/04-维表.md:64`）；在字典/维表补齐前，保留原码才能定位问题渠道，归到 `'other'` 反而抹掉了线索 |
| `channel_code = 'test'` | 过滤 | 需求稿第 5 段明确排除 |
| 其他非字典值（如旧码、拼写错） | 不静默改写成 `'other'` | 静默归并会让"渠道消失"，宁可让它在日报上带着原码露出来 |

⚠️ 一个容易写错的地方：`AND channel_code <> 'test'` 在 Hive 里对 NULL 求值为 NULL，会把渠道缺失的行**整行丢掉**。脚本里写的是 `COALESCE(channel_code, '') <> 'test'`，就是为了保住这些行。

## 7. 与需求稿第 6 段五条验收标准的逐条对应

| # | 验收标准 | 实现上怎么保证 | 怎么验（断言见 `self-check.md` §2） |
|---|---|---|---|
| 1 | 每个 `dt` 分区行数 > 0，且 `channel_code` 无空值 | 只要当天有成功支付流水就必然出行；`COALESCE(channel_code,'other')` 保证无 NULL；`test` 过滤用 COALESCE 包住，不误伤 NULL 行 | `SELECT COUNT(1) ... WHERE dt='${dt}'` 与 `SUM(CASE WHEN channel_code IS NULL THEN 1 ELSE 0 END)` |
| 2 | 与 `ads_trade_metric_1d` 同日同渠道 GMV 偏差 ≤ 0.01% | 事实源、归日键、不含运费、退款不回冲四项与 ADS 同口径（都源自支付流水 + `pay_time`）。ADS 侧要取渠道行并排掉合计行：`dt='${dt}' AND channel_id <> 'ALL'`（`knowledge/wiki/05-取数路径.md:39` 就是这个写法）。注意 ADS 的列名叫 `channel_id`、本表叫 `channel_code`，对账按**值**对齐，不按列名 | 全外关联后算 `ABS(diff)/ads.gmv`，按渠道逐行看；`'other'` 行单独核对 |
| 3 | 同一 `dt`+`channel_code` 只有一行 | `GROUP BY d.channel_code` 直接在聚合层保证唯一；维表先聚合再 JOIN，杜绝维表扇出 | `GROUP BY dt, channel_code HAVING COUNT(1) > 1` 应为 0 行 |
| 4 | `aov` 用 `SUM(gmv)/SUM(order_cnt)`，不允许对日客单价求平均 | 脚本内无 `AVG`；`aov` 与分子分母同层产出；DDL 与表注释写明"跨行汇总必须重算" | 行级一致性：`ABS(aov - gmv/order_cnt) <= 0.01`；跨渠道重算：`SUM(gmv)/SUM(order_cnt)` 与按渠道 AOV 的简单平均明显不等（证明两者不可混用） |
| 5 | 重跑同一分区结果一致（幂等） | 静态分区 `INSERT OVERWRITE` + 确定性排序键 + 无随机/时间函数（见 §5） | 重跑两次后比对 `COUNT(1)`、`SUM(gmv)`、`SUM(order_cnt)` 与整行 `EXCEPT` 结果（断言见 `self-check.md` §2.5） |

## 8. 与旧模板 `templates/dml/dws_trade_channel_1d.sql` 的差异（逐条判断，未照抄）

旧模板是同名目标表的早期写法。逐条看过，**没有一条是"可以直接照抄"的**：

| 旧模板写法 | 判断 | 依据 |
|---|---|---|
| `SUM(p.pay_amount)`、`p.pay_status='success'` | 字段名不采用，语义采用 | 本仓库对金额字段有三种写法：`pay_amt`（REQ 第 3 段 / `knowledge/wiki/02`）、`pay_amount`（模板 / 范例）、`order_amount`（订单应付）。按需求稿取 `pay_amt`；字段名差异列入待确认 H1 |
| 以 `dwd_order_main_di` 为主表、`LEFT JOIN` 支付流水 | 反了，不采用 | 主表决定口径。以订单为主表会把"当日下单但未支付"带进来，且订单分区按 `create_time`，跨天支付直接漏。事实表必须是支付流水（`knowledge/03_范例/example-gmv-by-channel.md:36` 同结论） |
| `LEFT JOIN` 支付流水后直接 `SUM`，无流水去重 | 不采用 | 重复回调会让 GMV 虚高（`knowledge/wiki/03-事实表.md:73`） |
| 输出 `channel` / `order_create_cnt` / `order_create_amt` / `pay_order_cnt` / `pay_amt` / `aov` | 不采用 | 本需求的输出字段由 REQ 第 4 段钉死：`channel_code`/`channel_name`/`gmv`/`order_cnt`/`aov`(＋分区 `dt`)。模板还混着"下单量"列，属于上一版目标表的遗留结构。注意旧结构的主键列是 `channel_id`（`knowledge/wiki/03-事实表.md:116`）、ADS 也是 `channel_id`，本表按 REQ 用 `channel_code` —— 命名偏差见 `self-check.md` 待确认 H8 |
| `SUM(...)/NULLIF(COUNT(DISTINCT ...),0)` 算 AOV | 采用（写法等价） | 除零保护的思路是对的，与本方案一致 |
| 只扫 `o.dt = '${bizdate}'` 一个分区 | 不采用（本方案不需要） | 本方案 `dt` 就是支付日期，单一分区即完整 |

> 由此引出一个必须确认的问题：线上若已有同名 `dws_trade_channel_1d` 且是模板那套列，本 DDL 的 `IF NOT EXISTS` 不会生效，ETL 会因列数不匹配失败。见待确认 H5。

## 9. 不做什么

- 不做分城市、分品类（REQ 第 7 段）。
- 不做实时，只 T+1。
- 不建新 ADS 表，不改 `ads_trade_metric_1d` 任何口径。
- 不引入退款/退款率列（需求已确认"先看毛的"）。
- 不在 SQL 注释或本文档里重写口径定义——全部指向 `ontology/`，本文只写"怎么实现"。

## 10. 已知风险

1. **与 ADS 的偏差方向是单向的**：本表去了重，ADS 若未去重，本表 GMV 会 ≤ ADS GMV。偏差若超过 0.01%，根因大概率在 ADS 侧未去重，而不是本表漏算——但这条要拿数据说话，见 `self-check.md` 待确认 H2。
2. **`pay_seq` 的可用性**：去重键依赖它（见 H2/H1）。缺失时去重逻辑必须整体换键，不能只改一个字段名。
3. **`dim_channel_df` 的 `dt` 分区**：脚本按"维表每日快照"写死 `WHERE dt = '${dt}'`（`knowledge/wiki/04-维表.md:3`、`tools/chat.py:78` 都是这个用法）。若该表实际是静态无分区表，去掉该行即可，其余逻辑不受影响（见 H4）。
4. **ADS 的渠道值域未核实**：`ads_trade_metric_1d` 的列名是 `channel_id`、还有一个 `'ALL'` 合计行（`knowledge/wiki/05-取数路径.md:39`）。对账前必须先比对双方的 `distinct` 渠道值域（是否都含 `'other'`、大小写是否一致），否则验收标准 2 的偏差会被"键对不上"污染成假差异（见 H7）。
