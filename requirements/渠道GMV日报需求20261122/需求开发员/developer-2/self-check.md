# self-check — dws_trade_channel_1d（developer-2 轨）

自查时间：2026-11-28　｜　环境：本机 Windows + python（无 Hive/Spark 实例，无法真跑引擎）

## 1. 交付物与结构检查

| 检查 | 命令 / 方式 | 结果 |
|---|---|---|
| 四个交付文件齐备 | `Get-ChildItem -Recurse -File` 于本轨目录 | 齐备：`sql/01_dws_trade_channel_1d.sql`(2181B)、`sql/02_etl_dws_trade_channel_1d.sql`(4166B)、`design-notes.md`、`self-check.md` |
| DDL 结构校验 | `python skills\sk-sql-ddl\validate.py --sql ...\01_dws_trade_channel_1d.sql` | `{"ok": true, "errors": []}` |
| DML 规则（sk-sql-dml / sk-sql-guard，无脚本，按判据人工核） | 逐条对照 SKILL.md | 通过：单条 `INSERT OVERWRITE`；分区 `(dt='${dt}')` 显式指定；目标列 5 列与 SELECT 输出 5 列同序；无 `SELECT *`；分区列只在 `PARTITIONED BY`；文件头有用途注释 + 四份 ontology 口径引用；无兜底假数据（缺上游分区时自然产出 0 行，不做 `COALESCE` 造数） |
| 双轨泄漏扫描（G2 的 scan_leak 项） | 对本轨全部文件 `Select-String -SimpleMatch 'developer-' + '-1'` | `leak_hits=0` |
| 与另一轨 SQL 不得同 sha256 | 只算本轨：01=`80aaabe944b9ad89…`、02=`c8b3453ff0e55648…`（完整 sha256 见下） | 本轨已异；**跨轨比对须由 lead 跑 `tools/check_dual_track.py`**——我不触碰另一轨目录，避免破坏双轨独立性 |

本轨文件 sha256（前 16 位）：
```
80aaabe944b9ad89  01_dws_trade_channel_1d.sql
c8b3453ff0e55648  02_etl_dws_trade_channel_1d.sql
0365abf8d41dec02  design-notes.md
```

## 2. 逻辑验证（sqlite 复算，非语法验证）

脚本：`.tmp/dev2/verify_logic.py`（临时件，不进交付）。做法与理由：

- **目标表结构不另写**：从交付的 DDL 文本里解析出 5 列（`channel_code/channel_name/gmv/order_cnt/aov`）在 sqlite 建表，避免"验证脚本自带一份影子 DDL、改 DDL 后验证仍绿"。
- 从 ETL 文本里**抽出 SELECT 部分**执行，`${dt}` 替换为 `'2026-11-22'`，`TO_DATE` 用 python 函数等价替代，`INSERT OVERWRITE ... PARTITION` 用 `DELETE` + `INSERT` 模拟静态分区覆盖。
- 脚本同时断言：ETL 单条语句（分号计数 = 1）、无 `SELECT *`、存在 `PARTITION (dt = '${dt}')` 头、SELECT 里无残留 `${`。

夹具 12 行支付流水，覆盖 9 类边界：

| # | 场景 | 期望 |
|---|---|---|
| 1 | 同 `(order_id, pay_seq)` 重复回调（P02/P03） | 只算一次 |
| 2 | 一单两笔流水 定金 100 + 尾款 50（P01/P02，同 order A1） | GMV 150、订单数 1 |
| 3 | `pay_status='failed'`（P06） | 排除 |
| 4 | `pay_amt = 0`（P07） | 排除 |
| 5 | `pay_time` 属前一日但 `dt` 错标为当日（P08） | 被 `TO_DATE` 卡掉 |
| 6 | `channel_code IS NULL`（P09，25 元） | 归 `unknown`，**不丢行** |
| 7 | `test` 渠道 999 元（P10） | 排除 |
| 8 | 字典外渠道 `xhs`（P11） | 保留原值 |
| 9 | `dt` 属前一日（P12，77 元） | 不在本分区 |

输出（证据文件 `.tmp/dev2/verify.out`）：

```
DDL 列: [('channel_code','STRING'), ('channel_name','STRING'), ('gmv','DECIMAL(18,2)'),
         ('order_cnt','BIGINT'), ('aov','DECIMAL(18,4)')]
run1:
   ('app', 'App 客户端', 180, 2, 90, '2026-11-22')
   ('mini_program', '小程序', 20, 1, 20, '2026-11-22')
   ('unknown', 'unknown', 25, 1, 25, '2026-11-22')
   ('xhs', 'xhs', 5, 1, 5, '2026-11-22')
run2 == run1: True
合计 gmv / order_cnt / 行数: (230, 5, 4)
空渠道行: 0 | 重复主键组: 0
RESULT: PASS
```

逐项核对：
- `app` = 100 + 50 + 30 = **180**，订单数 **2**（A1/A2），重复回调 P03 未重复计；AOV = 180/2 = **90**（若误用 `AVG(日客单价)` 或 `COUNT(1)` 会得 180/3 = 60，此处为 90 说明去重与除法都对）。
- `mini_program` 只剩 P05 的 20 元 / 1 单（P06 failed、P07 零元被滤）。
- `unknown` = 25 / 1：空渠道未丢行、未产生空值。
- `test` 999 元与跨日 P08/P12 未进结果。
- 合计 GMV 230 = 180+20+25+5，无重复、无遗漏。
- `run2 == run1` + 空渠道行 0 + 重复主键组 0 → 覆盖验收 1/3/5。

## 3. 上线前必须跑的 DQ 校验（本机无库，未执行）

以下均以 `${dt}` 为目标分区，A/B/C/F 对应需求第 6 段验收。

**A. 分区行数与空渠道（验收 1）**
```sql
SELECT '${dt}' AS dt,
       COUNT(1) AS row_cnt,
       SUM(CASE WHEN channel_code IS NULL OR TRIM(channel_code) = '' THEN 1 ELSE 0 END) AS null_ch_cnt
FROM dws.dws_trade_channel_1d
WHERE dt = '${dt}';
-- 期望 row_cnt > 0 且 null_ch_cnt = 0
```

**B. 唯一键（验收 3）**
```sql
SELECT channel_code, COUNT(1) AS c
FROM dws.dws_trade_channel_1d
WHERE dt = '${dt}'
GROUP BY channel_code
HAVING COUNT(1) > 1;   -- 期望 0 行
```

**C. 与 ads 对账（验收 2，偏差 ≤ 0.01%）**
```sql
SELECT d.channel_code,
       d.gmv                                AS dws_gmv,
       a.gmv                                AS ads_gmv,
       ABS(d.gmv - a.gmv)                   AS diff_amt,
       ABS(d.gmv - a.gmv) / NULLIF(a.gmv, 0) AS diff_rate
FROM (SELECT channel_code, gmv FROM dws.dws_trade_channel_1d WHERE dt = '${dt}') d
FULL OUTER JOIN (SELECT channel_code, gmv FROM ads.ads_trade_metric_1d WHERE dt = '${dt}') a
  ON d.channel_code = a.channel_code
WHERE ABS(d.gmv - a.gmv) / NULLIF(a.gmv, 0) > 0.0001
   OR d.channel_code IS NULL OR a.channel_code IS NULL;   -- 期望 0 行
```
> 假设 `ads_trade_metric_1d` 的渠道列名同为 `channel_code`、金额列名为 `gmv`；列名不符时改 SELECT/JOIN 三处（待确认 §4-3）。

**D. 订单主表唯一性（需求把该表列为"校验订单唯一性"的输入，故在此校验）**
```sql
SELECT order_id, COUNT(1) AS c
FROM dwd.dwd_order_main_di
WHERE dt = '${dt}'
GROUP BY order_id
HAVING COUNT(1) > 1;   -- 期望 0 行；非 0 说明上游主键约束破了，需先修上游
```

**E. 去重退化监控（`pay_seq` 缺失比例）**
```sql
SELECT COUNT(1) AS rows_all,
       SUM(CASE WHEN pay_seq IS NULL THEN 1 ELSE 0 END) AS rows_pay_seq_null,
       SUM(CASE WHEN pay_seq IS NULL THEN 1 ELSE 0 END) / COUNT(1) AS null_rate
FROM dwd.dwd_pay_flow_di
WHERE dt = '${dt}';   -- null_rate 显著 > 0 时，去重键退化为 pay_id，需与上游确认
```

**F. 幂等（验收 5）**
```sql
-- 第一次跑完后存快照
SELECT CONCAT_WS('|', channel_code, CAST(gmv AS STRING), CAST(order_cnt AS STRING), CAST(aov AS STRING)) AS line
FROM dws.dws_trade_channel_1d WHERE dt = '${dt}' ORDER BY channel_code;
-- 同一 ${dt} 重跑 ETL 后，上述结果 diff 应为空
```

**G. 渠道值域（口径 CHANNEL = app/mini_program/h5/pc）**
```sql
SELECT channel_code, COUNT(1) AS c
FROM dws.dws_trade_channel_1d
WHERE dt = '${dt}'
  AND channel_code NOT IN ('app', 'mini_program', 'h5', 'pc')
GROUP BY channel_code;   -- 期望只有 'unknown'（或空），出现别的值需回上游查渠道枚举
```

**H. GMV 溯源（与去重后流水合计对齐，用于定位是去重错还是聚合错）**
```sql
SELECT SUM(gmv) AS dws_gmv FROM dws.dws_trade_channel_1d WHERE dt = '${dt}';
-- 对照：按 (order_id, pay_seq) 去重后的 SUM(pay_amt)，口径同 ETL
```

## 4. 已知问题

1. **未在真实引擎执行**。本机无 Hive/Spark，只做了 sqlite 语义复算；`TO_DATE` 对 `TIMESTAMP` 类型入参的行为、`ROW_NUMBER` 在超大分区下的倾斜、ORC 写入均为"按文档应当如此"，需在测试 env 首跑确认。
2. **空分区语义**。若某日全部流水被过滤（全失败/全 `test`），`INSERT OVERWRITE` 产出 0 行、分区可能不存在。验收 1 要求"行数 > 0"，说明空日本身算异常；本实现**不写 0 值占位行**（避免造数），由 DQ-A 报警，由数据值班确认是"真无交易"还是"上游缺分区"。
3. **渠道大小写/空格未归一**。`test` 过滤比较的是原始值（仅大小写敏感），聚合处才有 `TRIM`；若上游出现 `TEST`/` test `，测试渠道可能漏滤。归一化需要先确认上游是否保证小写（wiki 与 ontology 均用小写），故未擅自 `LOWER`。
4. **`dim_channel_df` 当日分区缺失**。`LEFT JOIN` 会让 `channel_name` 兜底为 `channel_code`，任务不失败但报表名称变成代码；建议把"维表当日分区存在"加入调度前置依赖检查。
5. **多币种**。需求明确只处理人民币，故无币种字段；若未来接入外币，`SUM(pay_amt)` 会直接混币种，属口径变更，需回 ontology 走 delta。
6. **跨轨一致性（G2）未由我执行**。`tools/check_dual_track.py` 会读两轨产物，我只自检本轨；sha 不同、leak=0 已单独验证，剩余比对交 lead。
7. **`aov` 下游误用风险**。DDL 注释已写"跨维度重算"，但若下游 BI 层直接 `SUM(aov)`，SQL 层挡不住；建议在 ADS 或 BI 语义层加一条同名指标定义约束。

## 5. 待确认

| # | 事项 | 现状 | 影响面 |
|---|---|---|---|
| 1 | 未识别渠道占位值用 `unknown` 还是 `other` | wiki 03 写 `other`，ontology CHANNEL 值域无占位值；SQL 暂用 `unknown` | 改 1 处 `COALESCE` 字面量（ETL 第 30、62 行） |
| 2 | 维表渠道键名 `channel_code` vs `channel_id` | 需求稿写 `channel_code`，wiki 04 写 `channel_id`；SQL 按需求用 `channel_code` | 若实际是 `channel_id`，改 ETL 第 67、71 行两处 + 子查询列名 |
| 3 | `pay_status = 'success'` 的枚举 | 全仓无 `pay_status` 字典，字面量取自现状约定 | 若上游用 `SUCCESS`/`1`/`paid`，ETL 过滤条件失效、产出 0 行（不会错数），需上游确认 |
| 4 | 与 `ads_trade_metric_1d` 的列名与偏差 | 仅给出对账 SQL，未实测 | 验收 2 无法在本机闭环，需测试 env 首跑 |
| 5 | 退款/取消订单的排除方式 | 本实现靠 `pay_status='success'` 隐含排除；若 `dwd_pay_flow_di` 存在"支付成功后又退款"的行（`pay_status` 变为 `refunded`），历史分区会被重刷改变 | 需确认支付流水表是否保留原始成功记录；GMV"退款不回冲"要求退款不改变已成功流水的状态 |
| 6 | 测试渠道是否只有 `channel_code='test'` 一种标识 | 按需求只排除该值 | 若还有 `is_test` 标记列或内部账号，需补充过滤 |

以上 6 项均**未写死进 SQL 作为既成口径**：1/2 按需求稿或 wiki 择一并在 design-notes §8 标注，3/5 依赖上游事实、无法从 ontology 推出，4 需真实数据。
