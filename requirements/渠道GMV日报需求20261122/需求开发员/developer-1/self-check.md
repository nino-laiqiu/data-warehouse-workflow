# 自检报告 · dws_trade_channel_1d（developer-1）

## 0. 结论先说

- 交付 4 件：`sql/01_dws_trade_channel_1d.sql`、`sql/02_etl_dws_trade_channel_1d.sql`、`design-notes.md`、本文件。
- **能做文本级校验的全部通过**（9 项，见 §2），DDL 校验器返回 `{"ok": true, "errors": []}`。
- **一条真实执行都没做**：本机没有 Hive/Spark，`$env:HQL_CMD` 为空（见 §1）。所以需求稿第 6 段的五条验收标准，我给出的是**可执行断言 SQL**（§3），不是"已验证通过"。请不要把 §3 当成已完成项。
- 8 条待确认（§5），其中 **H1（金额字段名）、H2（`pay_seq` 去重键）、H5（线上同名表）** 会直接决定脚本能否跑通，**H8（渠道列名 `channel_code` vs `channel_id`）** 会影响两轨比对，建议在 P3 门禁前先定。
- 本轨全程未读取 `requirements/渠道GMV日报需求20261122/需求开发员/developer-2/` 下任何文件，也未与其做任何口径对齐（独立轨道要求）。

## 1. 校验环境与限制

| 项 | 状态 | 对自检的影响 |
|---|---|---|
| Python | ✅ 3.13.7 | 可跑 `skills/sk-sql-ddl/validate.py` 与本地静态检查脚本 |
| Hive / Spark CLI | ❌ 无 | 无法编译、无法执行、无法看执行计划 |
| `$env:HQL_CMD` | ❌ 空 | 仓库约定的集群执行入口不可用（见 `docs/现网验证.md`） |
| `sqlglot` / `sqlparse` | ❌ 均未安装 | 做不了 AST 级校验，只能做文本级/正则级 |
| 文件沙箱 | workspace-write | 原生命令加管道或 `>` 会被拒；一律 `Start-Process ... -RedirectStandardOutput .tmp\xx.txt` 再读文件 |

**结论**：本次自检的强度是"结构正确 + 口径可追溯 + 关键片段齐全"，不等于"能跑通"。语法/类型/权限类问题只能靠 §3 在测试环境暴露。

## 2. 已执行的检查与结果

| # | 检查项 | 方法 | 结果 |
|---|---|---|---|
| 1 | DDL 结构合法性（首语句、单语句、禁 DROP/TRUNCATE/ALTER、字段 COMMENT、括号配平、`STORED AS`、分区列不重复出现在普通列） | `python skills\sk-sql-ddl\validate.py --sql <DDL>` | ✅ `{"ok": true, "errors": []}` |
| 2 | DDL 与 DML 的列名、顺序、类型是否一致（防错位写入） | `.tmp/check_deliverables.py` 文本解析 | ✅ DDL 5 列 `channel_code, channel_name, gmv, order_cnt, aov`＝`STRING, STRING, DECIMAL(18,2), BIGINT, DECIMAL(18,2)`；DML 输出 5 列同名同序＋分区 `dt` |
| 3 | 是否 `SELECT *` | 脚本扫 `SELECT *` | ✅ 无 |
| 4 | 是否静态分区覆盖（不能全表覆盖） | 扫 `INSERT OVERWRITE TABLE ... PARTITION (dt = '${dt}')` | ✅ 有，且分区值是变量而非字面量 |
| 5 | 非确定性函数（`rand` / `now` / `current_timestamp` / `unix_timestamp()`） | 扫关键字 | ✅ 全部为 0 次（幂等前提，见 §3.5） |
| 6 | `LIMIT` / 采样 | 扫关键字 | ✅ 无 |
| 7 | 口径关键片段是否真的写进 SQL（逐条对 ontology 落地） | 文本命中检查 | ✅ 7/7：`SUM(d.pay_amt)`、`COUNT(DISTINCT d.order_id)`、`ROW_NUMBER() OVER`、`PARTITION BY order_id, pay_seq`、`pay_status = 'success'`、`pay_amt > 0`、`COALESCE(channel_code, '') <> 'test'`、`NULLIF(p.order_cnt, 0)`、`LEFT JOIN` 维表前先 `GROUP BY channel_code` |
| 8 | 需求稿 §4 字段清单 × §5 边界条件，与脚本逐条对照 | 人工逐行 | ✅ 输出 6 列（含 `dt`）与 REQ §4 完全一致；§5 五条边界在 WHERE/COALESCE 中逐条落位 |
| 9 | 与旧模板 `templates/dml/dws_trade_channel_1d.sql` 的差异是否都有理由 | 人工逐行 | ✅ 6 行差异已写入 `design-notes.md` §8，每条给了替代依据 |

未执行的检查（明确列出，不含糊）：真机编译、真机执行、执行计划、数据量/耗时、权限、分区是否真实存在、ADS 侧真实字段名。

### 2.1 对照三份技能判据逐条过一遍

三份技能都只有规格（`SKILL.md`），没有 `validate.py` 实现，所以这一节是人工逐条核对，不是脚本结果。

**`skills/sk-sql-ddl/SKILL.md` 六条硬规则**

| # | 规则 | 结果 |
|---|---|---|
| 1 | 表级 + 每个字段级都要 `COMMENT` | ✅ 1 个表 COMMENT + 5 个字段 COMMENT + 1 个分区 COMMENT |
| 2 | 必须 `STORED AS`（默认 ORC） | ✅ `STORED AS ORC`，另加 `TBLPROPERTIES ('orc.compress'='SNAPPY')` |
| 3 | 分区字段不得同时出现在非分区列 | ✅ `dt` 只在 `PARTITIONED BY` 出现；validate.py 的 `check_partition_not_in_columns` 也判过 |
| 4 | 列名只允许 `[a-z][a-z0-9_]*` | ✅ `channel_code`/`channel_name`/`gmv`/`order_cnt`/`aov` |
| 5 | 不生成 `DROP TABLE`/`TRUNCATE`/`LOCATION` | ✅ 三者都没有 |
| 6 | 保留字冲突时不自动加反引号 | ✅ 5 个列名均非 Hive 保留字，无需反引号，也没加 |

**`skills/sk-sql-dml/SKILL.md` 四条判据**

| # | 判据 | 结果 |
|---|---|---|
| 1 | `INSERT OVERWRITE` 指定分区，不许全表覆盖 | ✅ `PARTITION (dt = '${dt}')` 静态分区 |
| 2 | 重跑同参数结果一致 | ✅ 无随机/时间/采样/`LIMIT`；去重排序键全为确定列（推理见 `design-notes.md` §5，实测见 §3.5） |
| 3 | 字段数/类型与 DDL 一致 | ✅ 5 列同名同序（§2 第 2 项） |
| 4 | 每条 SQL 带用途注释与口径引用 | ✅ 文件头 15 行注释（用途/粒度/事实源/维表源/四份 ontology 引用/参数/重跑/说明）+ 语句内 6 处中文注释 |

**`skills/sk-sql-guard/SKILL.md` 三条（"比 A 线多三条"）**

| # | 判据 | 结果 |
|---|---|---|
| 1 | 写入必须带分区，且分区列在列定义之后 | ✅ DDL 的 `PARTITIONED BY` 在列定义之后；DML 的 `PARTITION` 子句在表名之后 |
| 2 | 目标表列与 SELECT 列数、顺序一致 | ✅ 5 = 5，顺序 `channel_code, channel_name, gmv, order_cnt, aov` |
| 3 | 禁用 `SELECT *` 写入 | ✅ 输出端全部显式列名 |

## 3. 需在测试环境执行的验收断言（REQ §6 逐条）

以下 SQL 请在测试/预发环境按 `${dt}` 跑，结果回填本表。**这是本次交付唯一未完成的证据缺口。**

### 3.1 验收标准 1：分区非空 + `channel_code` 无空值

```sql
SELECT COUNT(1)                                           AS row_cnt,
       SUM(CASE WHEN channel_code IS NULL THEN 1 ELSE 0 END) AS null_cnt,
       SUM(CASE WHEN channel_code = '' THEN 1 ELSE 0 END)   AS empty_cnt
FROM dws.dws_trade_channel_1d
WHERE dt = '${dt}';
```

期望：`row_cnt > 0`、`null_cnt = 0`、`empty_cnt = 0`。
若不通过：先查上游该 `dt` 分区是否有数据（上游空 → 0 行属正常，由调度拦截，不是本脚本的问题）。

### 3.2 验收标准 2：与 `ads_trade_metric_1d` 同日同渠道 GMV 偏差 ≤ 0.01%

```sql
-- 先比对双方值域，确认"键对得上"，否则后面算的偏差是假差异
SELECT 'dws' AS src, channel_code AS channel_key, COUNT(1) AS cnt
FROM dws.dws_trade_channel_1d WHERE dt = '${dt}' GROUP BY channel_code
UNION ALL
SELECT 'ads', channel_id, COUNT(1)
FROM ads.ads_trade_metric_1d WHERE dt = '${dt}' AND channel_id <> 'ALL' GROUP BY channel_id;

-- 对账：本表 channel_code ↔ ADS channel_id（按值对齐，列名不同）
SELECT COALESCE(m.channel_code, a.channel_id) AS channel_key,
       m.gmv        AS dws_gmv,
       a.gmv        AS ads_gmv,
       COALESCE(m.gmv, 0) - COALESCE(a.gmv, 0)                          AS diff_amt,
       CASE WHEN COALESCE(a.gmv, 0) = 0 THEN NULL
            ELSE ABS(COALESCE(m.gmv, 0) - a.gmv) / a.gmv END            AS diff_rate
FROM (SELECT channel_code, gmv FROM dws.dws_trade_channel_1d WHERE dt = '${dt}') m
FULL OUTER JOIN
     (SELECT channel_id, gmv FROM ads.ads_trade_metric_1d
       WHERE dt = '${dt}' AND channel_id <> 'ALL') a
  ON m.channel_code = a.channel_id
ORDER BY channel_key;
```

期望：每行 `diff_rate <= 0.0001`（0.01%）。
偏差超标的排查顺序：① ADS 是否也做了流水去重（本表去重后只会 ≤ ADS，见 `design-notes.md` §10.1）；② `'other'` 行两边是否都归了；③ ADS 的 `dt` 是否也按 `pay_time`。

### 3.3 验收标准 3：同 `dt` + `channel_code` 唯一

```sql
SELECT dt, channel_code, COUNT(1) AS cnt
FROM dws.dws_trade_channel_1d
WHERE dt = '${dt}'
GROUP BY dt, channel_code
HAVING COUNT(1) > 1;
```

期望：0 行。这是 `GROUP BY d.channel_code` 的直接结果；若出现，说明维表 JOIN 把行放大了（说明有人把维表预聚合删了）。

### 3.4 验收标准 4：`aov` 必须可重算，不能是平均出来的

```sql
-- (a) 行级一致性：aov 与 gmv/order_cnt 在舍入误差内相等
SELECT COUNT(1) AS bad_rows
FROM dws.dws_trade_channel_1d
WHERE dt = '${dt}'
  AND ABS(aov - gmv / order_cnt) > 0.01;

-- (b) 反例：跨渠道汇总时 AVG(aov) 与 SUM(gmv)/SUM(order_cnt) 显著不等，
--     用来向评审证明"对日客单价求平均"是错的（预期两者不相等）
SELECT SUM(gmv) / SUM(order_cnt)   AS aov_correct,
       AVG(aov)                    AS aov_wrong_if_avg
FROM dws.dws_trade_channel_1d
WHERE dt = '${dt}';
```

期望：(a) `bad_rows = 0`；(b) 两列不相等（若恰好相等只说明渠道间结构恰好一致，不能反证 AVG 可用）。

### 3.5 验收标准 5：同分区重跑结果一致（幂等）

```sql
-- 跑第一次后落快照：表内自校验用校验和
SELECT COUNT(1) AS cnt, SUM(gmv) AS gmv_sum, SUM(order_cnt) AS order_sum,
       SUM(CAST(order_cnt AS DECIMAL(18,2)) * aov) AS aov_weighted_sum
FROM dws.dws_trade_channel_1d WHERE dt = '${dt}';
-- 同参数再跑一次 ETL，重跑上面这条，三个数值必须与第一次完全一致
```

更严格的做法（Hive 2+/Spark 均支持）：重跑前后各 `CREATE TABLE tmp_snap AS SELECT ... ORDER BY channel_code`，再 `SELECT COUNT(1) FROM snap_before FULL OUTER JOIN snap_after ON ... WHERE <任一侧为空>`，期望 0 行。

### 3.6 附加 DQ（自查"我有没有算错"，不是需求验收项）

```sql
-- DQ-A 重复回调量级：不去重 vs 去重后的 GMV 差额。这个差额就是 3.2 里对不上 ADS 时可解释的量
SELECT (SELECT SUM(pay_amt) FROM dwd.dwd_pay_flow_di
         WHERE dt = '${dt}' AND pay_status = 'success' AND pay_amt > 0
           AND COALESCE(channel_code, '') <> 'test')                AS gmv_before_dedup,
       (SELECT SUM(gmv) FROM dws.dws_trade_channel_1d WHERE dt = '${dt}') AS gmv_after_dedup;

-- DQ-B 订单唯一性（REQ §3 给 dwd_order_main_di 的用途就是"校验订单唯一性"）
SELECT COUNT(1) AS dup_order_cnt FROM (
  SELECT order_id FROM dwd.dwd_order_main_di WHERE dt = '${dt}'
  GROUP BY order_id HAVING COUNT(1) > 1
) t;

-- DQ-C 现金流水的订单是否都能在主表找到（找不到 = 主表分区比 pay_time 窄，属上游问题）
SELECT COUNT(DISTINCT p.order_id) AS orphan_orders
FROM (SELECT DISTINCT order_id FROM dwd.dwd_pay_flow_di
       WHERE dt = '${dt}' AND pay_status = 'success' AND pay_amt > 0) p
LEFT JOIN (SELECT DISTINCT order_id FROM dwd.dwd_order_main_di WHERE dt = '${dt}') o
  ON p.order_id = o.order_id
WHERE o.order_id IS NULL;
```

## 4. 已知问题（实现层面的局限，已接受）

1. **表结构窄**：只有 5 个指标列，没有下单量、退款额、支付笔数、支付人数。与旧同名表（`knowledge/wiki/03-事实表.md:121` 记的那套列：`order_cnt`/`pay_order_cnt`/`gmv`/`pay_qty`/`pay_user_cnt`/`refund_amt`）不兼容。这是 REQ §4 的字段清单决定的，不是我漏了；但如果线上老表还在用，见 H5。
2. **`aov` 的误用挡不住**：本表只能保证"行内 aov 可由 gmv/order_cnt 重算出"（§3.4a），挡不住下游写 `AVG(aov)`。防线上误用靠注释、文档和取数路径约定（`knowledge/wiki/05-取数路径.md:39` 已示范正确写法）。
3. **跨渠道支付的订单**：一笔订单可有多次支付（如先 app 下单、后 h5 支付）。本表按"支付时刻快照"把每一笔流水归到它当时的渠道，于是同一 `order_id` 可能出现在两个渠道的 `order_cnt` 里。这符合需求稿第 2 段的定义，但**渠道维度的 `order_cnt` 之和可能大于全站去重订单数**，使用时不能直接把各渠道 `order_cnt` 相加当全站订单数（GMV 相加没问题，它是可加的）。这一点评审时容易踩，已在此声明。
4. **两个非字典值 `'other'` / `'未识别'`**：严格说它们不在 `ontology/dict/channel.yaml` 的值域内，属于"实现层兜底值"。要合规需提 `ontology_delta`（H3）。

## 5. 待确认（不确定的地方，我没有猜着写死）

| 编号 | 待确认的问题 | 我已按此实现（假设） | 依据 | 若假设不成立，改哪里 |
|---|---|---|---|---|
| **H1** | `dwd_pay_flow_di` 的金额字段到底叫 `pay_amt` 还是 `pay_amount`？ | `pay_amt` | REQ §3、`knowledge/wiki/02-度量与指标.md:8-9`、`knowledge/wiki/03-事实表.md:70` 都写 `pay_amt`；但 `templates/dml/dws_trade_channel_1d.sql` 和 `knowledge/03_范例/example-gmv-by-channel.md:22` 写 `pay_amount` | 全文替换 2 处（`SUM(d.pay_amt)`、`AND pay_amt > 0`）。字段不存在会编译期报错，属显式失败，不会静默算错 |
| **H2** | `pay_seq` 是否真实存在？重复回调的判定键是否真是 `(order_id, pay_seq)`？ | 是，按 `(order_id, pay_seq)` 去重、`rn=1` | `knowledge/wiki/03-事实表.md:65`（主键）、`:73`（"重复回调必须按 (order_id, pay_seq) 去重"） | 无 `pay_seq` → 退化为 `(order_id, pay_time, pay_amt)`，语义变弱（金额时间都相同的真实分次支付会被误并）；若真正的唯一键是 `trade_no`/`pay_id`，直接换 `PARTITION BY trade_no` 更准 |
| **H3** | `'other'`（渠道缺失）与 `'未识别'`（维表未匹配）要不要进 CHANNEL 字典？ | 先用，未入字典 | `knowledge/wiki/03-事实表.md:125`「未识别渠道归 other，不要丢行」；但 `ontology/dict/channel.yaml` 只有 app/mini_program/h5/pc | 提 `ontology_delta` 把 `other` 补进 CHANNEL；`'未识别'` 只出现在 `channel_name`，建议只由维表 owner 确认，不入字典 |
| **H4** | `dim_channel_df` 真的是按 `dt` 分区的全量快照吗？ | 是，用 `WHERE dt = '${dt}'` | `knowledge/wiki/04-维表.md:3`、`tools/chat.py:78` | 若是无分区静态表 → 删掉 `WHERE dt = '${dt}'` 一行，其余逻辑不变 |
| **H5** | 线上是否已存在同名 `dws_trade_channel_1d`（且是旧模板那套列）？ | 不存在，或允许重建 | 模板与 wiki 都有旧结构记录；本需求是"新设计" | `CREATE EXTERNAL TABLE IF NOT EXISTS` 在表已存在时会**静默跳过**，随后 ETL 因列数不匹配失败（显式失败，可接受）。需 DBA 确认：DROP 重建（要迁旧分区）还是改用新表名 |
| **H6** | `order_cnt` 要求"支付成功订单"还是"已结清订单"？ | 支付成功即计 1 单（`COUNT(DISTINCT order_id)`），不要求结清 | `ontology/metric/atomic/order_cnt.yaml`、REQ §2 | `knowledge/wiki/03-事实表.md:74` 提示"部分支付：一个订单多笔流水，`SUM(pay_amt)` 要按 `order_id` 汇总后再判断是否结清"。若产品要结清口径，分母需改成结清订单数（要 join 订单表比对 `order_amt` 与累计实付），AOV 会整体上移 |
| **H7** | `ads_trade_metric_1d` 的渠道值域与列名 | 列名 `channel_id`，取值与本表 `channel_code` 同一套，合计行是 `'ALL'` | `knowledge/wiki/05-取数路径.md:39`（`channel_id<>'ALL'` + `SUM(gmv)/SUM(order_cnt)`） | 对账前先跑 §3.2 的第一段 SQL 比对值域；不一致就要加映射（这一步不做，验收标准 2 的偏差不可信） |
| **H8** | 本表渠道列叫 `channel_code`（REQ §4 钉的），但仓库既有表统一叫 `channel_id`——`dws_trade_channel_1d` 旧结构主键就是 `dt`+`channel_id`（`knowledge/wiki/03-事实表.md:116`），ADS 也是 `channel_id`。要不要改成 `channel_id` 以方便同名 join？ | 按 REQ §4 用 `channel_code` | REQ 是唯一需求来源，且支付流水上的字段名确实是 `channel_code` | 若评审要求与 ADS/旧表对齐：改 3 处（DDL 列名 + DML 的两处 `AS`），逻辑不变。**但必须有人明确决定**，否则两轨会一个叫 `channel_code` 一个叫 `channel_id`，比对时看着像口径分歧 |

## 6. 交付物自检清单

- [x] `sql/01_dws_trade_channel_1d.sql`：DDL 通过 `sk-sql-ddl/validate.py`（`ok: true`）
- [x] `sql/02_etl_dws_trade_channel_1d.sql`：单条 `INSERT OVERWRITE ... PARTITION (dt = '${dt}')`，列与 DDL 同名同序，无 `SELECT *`
- [x] `design-notes.md`：实现结构理由 / 去重三层 / AOV 不可加 / 幂等 / 五条验收逐条对应 / 与旧模板差异 / 风险，七项齐
- [x] `self-check.md`：本文件
- [x] 未读取 developer-2 目录，未与其对齐
- [ ] 真机执行与五条验收实测 —— **本机无法完成**，需 Hive/Spark 权限（§3 已备好断言 SQL）
- [ ] 三处外部依赖确认（H1 字段名、H2 去重键、H5 线上表）—— 需 P4/数仓 owner 答复
