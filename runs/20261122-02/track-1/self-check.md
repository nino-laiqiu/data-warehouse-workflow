# track-1 自检

## 已逐条对照需求

| 需求条款 | 是否覆盖 | 位置 |
|---|---|---|
| 12 个标签全部产出 | 是 | 01 的 12 个 `tag` 列 |
| 粒度 用户 × 日 | 是 | 一用户一行 + `dt` 分区 |
| 缺失落 UNKNOWN 不留 NULL | 是，但 `purchase_gmv_30d` 例外（数值型用 0） | 02 各列 `NVL` |
| 时间窗 `[dt-N, dt-1]` | 是 | `pay_all` / `pay_30d` / `pay_90d` 的 `BETWEEN` |
| 含从未下单用户 | 是 | `dim_user LEFT JOIN` 事实侧 |
| 偏好品类并列取最早达成者 | 是 | `ORDER BY cat_gmv DESC, first_dt ASC` |
| 复购与订单数一致性（验收 5） | 是 | 都基于同一 `pay_all` |

## 自己发现的问题（已修 / 待修）

1. **已修**：最初直接用 `dim_user_df` 关联，SCD2 没去当前版本 → 用户会重复成多行、行数校验必挂。改为 `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY start_date DESC)`。
2. **已修**：`purchase_aov_band` 最初用 `AVG(pay_amt)` 算客单价，违反 `AOV` 的 non_additive 口径。改为 `gmv_30d / order_cnt_30d`。
3. **已修**：`gender` 直接透传，NULL 未兜底 → 违反验收 3。改为 `NVL(gender,'UNKNOWN')`。
4. **待修**：`base` 里对 `pay_all` 关联了三次（`f` / `l` / `h`），其中 `f` 已经算了 `last_pay_time` 与 `total_order_cnt`，`l`、`h` 完全重复。Hive 会对 `pay_all` 扫三遍。应合并成一次 subquery。
5. **已知偏差**：`purchase_gmv_30d` 用 0 而非 UNKNOWN，与"标签值一律字符串"的边界描述不一致。理由：数值型标签后续要参与求和/分档，0 更可用；已在裁决时登记为差异。

## 未做

- 未在真实集群执行（无 Hive 环境），只做了静态检查：括号配平、单语句、无 DROP/TRUNCATE、列 COMMENT 齐全、`STORED AS ORC`。
- 未评估数据倾斜：`preferred_category` 的 `JOIN dim_product_df` 若某类目 SKU 极多，需开 `hive.auto.convert.join`。
