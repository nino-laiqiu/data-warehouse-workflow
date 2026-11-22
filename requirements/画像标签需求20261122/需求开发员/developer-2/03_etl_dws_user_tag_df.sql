-- ============================================================
-- track-2 / 03_etl_dws_user_tag_df.sql
-- 说明：一次算出 base（用户级标量），再 UNION ALL 展开成 12 个标签行
-- 依赖：Hive 2.x+（WITH 可以出现在 INSERT 之前）
-- ============================================================

WITH dim_user AS (
  SELECT user_id, gender, birthday, city_level, register_time, member_level
  FROM (
    SELECT user_id, gender, birthday, city_level, register_time, member_level,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY start_date DESC) AS rn
    FROM dim_user_df
    WHERE dt = '${dt}'
  ) t
  WHERE rn = 1
),
pay_all AS (
  SELECT user_id, order_id, pay_time, pay_amt
  FROM dwd_pay_flow_di
  WHERE dt <= date_sub('${dt}', 1) AND pay_amt > 0 AND user_id NOT LIKE 'test\_%'
),
pay_agg AS (
  SELECT
    user_id,
    COUNT(DISTINCT order_id)                                        AS cnt_total,
    COUNT(DISTINCT IF(dt >= date_sub('${dt}', 30), order_id, NULL))  AS cnt_30d,
    SUM(IF(dt >= date_sub('${dt}', 30), pay_amt, 0))                  AS gmv_30d,
    MIN(pay_time)                                                    AS first_pay_time,
    MAX(pay_time)                                                    AS last_pay_time
  FROM pay_all
  GROUP BY user_id
),
item_90d AS (
  SELECT
    o.user_id,
    p.category_name,
    SUM(oi.item_amt) AS cat_gmv,
    MIN(oi.dt)       AS first_dt
  FROM dwd_order_item_di oi
  JOIN dwd_order_main_di o
    ON oi.order_id = o.order_id AND o.dt = oi.dt
   AND o.order_status IN ('paid', 'shipped', 'completed')
  JOIN dim_product_df p ON p.sku_id = oi.sku_id AND p.dt = '${dt}'
  WHERE oi.dt BETWEEN date_sub('${dt}', 90) AND date_sub('${dt}', 1)
  GROUP BY o.user_id, p.category_name
),
pref_cat AS (
  SELECT user_id, category_name
  FROM (
    SELECT user_id, category_name,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY cat_gmv DESC, first_dt ASC, category_name ASC) AS rn
    FROM item_90d
  ) t
  WHERE rn = 1
),
base AS (
  SELECT
    u.user_id,
    NVL(u.gender, 'UNKNOWN')            AS gender,
    NVL(u.city_level, 'UNKNOWN')        AS city_level,
    NVL(u.member_level, 'UNKNOWN')      AS member_level,
    u.register_time,
    u.birthday,
    NVL(a.cnt_total, 0)                 AS cnt_total,
    NVL(a.cnt_30d, 0)                   AS cnt_30d,
    NVL(a.gmv_30d, 0)                   AS gmv_30d,
    a.first_pay_time,
    a.last_pay_time,
    NVL(pc.category_name, '无')         AS preferred_category
  FROM dim_user u
  LEFT JOIN pay_agg a  ON a.user_id = u.user_id
  LEFT JOIN pref_cat pc ON pc.user_id = u.user_id
)
INSERT OVERWRITE TABLE dws_user_tag_df PARTITION (dt = '${dt}')
SELECT user_id, tag_code, tag_value, tag_num, tag_category, dt FROM (
  SELECT user_id, 'basic_gender' AS tag_code, gender AS tag_value, CAST(NULL AS DECIMAL(18,2)) AS tag_num, 'basic' AS tag_category, '${dt}' AS dt FROM base
  UNION ALL
  SELECT user_id, 'basic_age_band', CASE WHEN birthday IS NULL THEN 'UNKNOWN' WHEN CAST(DATEDIFF('${dt}', birthday)/365 AS INT) BETWEEN 18 AND 24 THEN '18-24' WHEN CAST(DATEDIFF('${dt}', birthday)/365 AS INT) BETWEEN 25 AND 34 THEN '25-34' WHEN CAST(DATEDIFF('${dt}', birthday)/365 AS INT) BETWEEN 35 AND 44 THEN '35-44' WHEN CAST(DATEDIFF('${dt}', birthday)/365 AS INT) >= 45 THEN '45+' ELSE 'UNKNOWN' END, CAST(NULL AS DECIMAL(18,2)), 'basic', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'basic_city_level', city_level, CAST(NULL AS DECIMAL(18,2)), 'basic', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'basic_register_days', CASE WHEN register_time IS NULL THEN 'UNKNOWN' WHEN DATEDIFF('${dt}', register_time) <= 7 THEN '0-7' WHEN DATEDIFF('${dt}', register_time) <= 30 THEN '8-30' WHEN DATEDIFF('${dt}', register_time) <= 90 THEN '31-90' WHEN DATEDIFF('${dt}', register_time) <= 365 THEN '91-365' ELSE '365+' END, CAST(NULL AS DECIMAL(18,2)), 'basic', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'basic_member_level', member_level, CAST(NULL AS DECIMAL(18,2)), 'basic', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'purchase_first_order_days', CASE WHEN first_pay_time IS NULL THEN '未购' WHEN DATEDIFF('${dt}', first_pay_time) <= 30 THEN '0-30' WHEN DATEDIFF('${dt}', first_pay_time) <= 90 THEN '31-90' WHEN DATEDIFF('${dt}', first_pay_time) <= 180 THEN '91-180' ELSE '180+' END, CAST(NULL AS DECIMAL(18,2)), 'purchase', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'purchase_order_cnt_30d', CASE WHEN cnt_30d = 0 THEN '0' WHEN cnt_30d = 1 THEN '1' WHEN cnt_30d <= 3 THEN '2-3' WHEN cnt_30d <= 9 THEN '4-9' ELSE '10+' END, CAST(NULL AS DECIMAL(18,2)), 'purchase', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'purchase_gmv_30d', CAST(CAST(gmv_30d AS DECIMAL(18,2)) AS STRING), CAST(gmv_30d AS DECIMAL(18,2)), 'purchase', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'purchase_aov_band', CASE WHEN cnt_30d = 0 THEN '未购' WHEN gmv_30d / cnt_30d <= 50 THEN '0-50' WHEN gmv_30d / cnt_30d <= 100 THEN '50-100' WHEN gmv_30d / cnt_30d <= 300 THEN '100-300' ELSE '300+' END, CAST(NULL AS DECIMAL(18,2)), 'purchase', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'purchase_last_pay_days', CASE WHEN last_pay_time IS NULL THEN '未购' WHEN DATEDIFF('${dt}', last_pay_time) <= 7 THEN '0-7' WHEN DATEDIFF('${dt}', last_pay_time) <= 30 THEN '8-30' WHEN DATEDIFF('${dt}', last_pay_time) <= 90 THEN '31-90' ELSE '90+' END, CAST(NULL AS DECIMAL(18,2)), 'purchase', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'purchase_is_repurchase', CASE WHEN cnt_total = 0 THEN '未购' WHEN cnt_total >= 2 THEN '是' ELSE '否' END, CAST(NULL AS DECIMAL(18,2)), 'purchase', '${dt}' FROM base
  UNION ALL
  SELECT user_id, 'purchase_preferred_category', preferred_category, CAST(NULL AS DECIMAL(18,2)), 'purchase', '${dt}' FROM base
) t;
