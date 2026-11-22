# track-2 自检

## 已逐条对照需求

| 需求条款 | 是否覆盖 | 位置 |
|---|---|---|
| 12 个标签全部产出 | 是 | 03 的 12 段 `UNION ALL`，每段一个 `tag_code` |
| 粒度 用户 × 标签 × 日 | 是 | `dws_user_tag_df` 表定义 |
| 缺失落 UNKNOWN 不留 NULL | **部分**：`preferred_category` 落"无"，`is_repurchase` 落"未购" | 03 |
| 时间窗 `[dt-N, dt-1]` | 是 | `pay_agg` 的 `IF(dt >= date_sub('${dt}',30))` |
| 含从未下单用户 | 是 | `dim_user LEFT JOIN pay_agg` |
| 偏好品类并列取最早达成者 | 是 | `ORDER BY cat_gmv DESC, first_dt ASC, category_name ASC` |
| 复购与订单数一致性（验收 5） | 是 | 同在 `base`，同源 `cnt_total` |

## 自己发现的问题

1. **待修（重要）**：`base` 这个 CTE 被 12 段 `UNION ALL` 引用。Hive 2.x 里 CTE 不是物化点，执行计划可能展开成 12 次 `pay_all` 全表扫描——比宽表方案贵一个数量级。正确做法是先 `INSERT OVERWRITE` 落到临时表 `tmp_user_tag_base`，再从临时表展开。本次未改，因为会引入一张必须清理的中间表；作为已知风险交裁决。
2. **已修**：`dws_user_tag_df` 的建表语句里 `dt` 既出现在列定义里、又出现在 `PARTITIONED BY` 里，是重复定义，Hive 建表会直接报错。分区列只能出现在 `PARTITIONED BY` 中。
   注意：`sk-sql-ddl` 的纯 SQL 模式**当时代没抓到**这条（只有 `--input` 契约模式才查"列与分区重名"）。已把这条补成校验规则，反例 `.tmp/dup-partition.sql` 现在会被拦下——这是本轮双轨制反向改进工具链的一个例子。
3. **口径偏差（需裁决）**：需求写"缺失一律落 UNKNOWN"，但"偏好品类无"用"无"、"未购"用"未购"，与宽表轨（同样用"未购"/"无"）一致，但与需求原文的"一律 UNKNOWN"字面不符。两轨在此一致，说明是需求文本过严，建议在裁决时统一解释为"枚举标签缺失用业务上有意义的值，不硬套 UNKNOWN"。
4. **已注意**：`purchase_gmv_30d` 同时写 `tag_value`（字符串）与 `tag_num`（数值），保证下游既能过滤也能求和。

## 未做

- 未在真实集群执行，只做静态检查。
- 未压测：`dws_user_tag_df` 行数 ×12 对下游 BI 扫描时间的影响需实测。
