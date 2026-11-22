-- ============================================================
-- track-1 / 02_etl_dws_user_profile_df.sql
-- 说明：一次性 join 出全部标签，写满分区；时间窗 [dt-N, dt-1]，不含当天
-- 幂等：INSERT OVERWRITE 覆盖分区，重跑结果一致
-- ============================================================

WITH dim_user AS (
  SELECT user_id, gender, birthday, city_level, register_time, member_level
  FROM (
    SELECT
      user_id, gender, birthday, city_level, register_time, member_level,
      ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY start_date DESC) AS rn
    FROM dim_user_df
    WHERE dt = '${dt}'
  ) t
  WHERE rn = 1
),
pay_all AS (
  SELECT user_id, order_id, pay_time, pay_amt
  FROM dwd_pay_flow_di
  WHERE dt <= date_sub('${dt}', 1)
    AND pay_amt > 0
    AND user_id NOT LIKE 'test\_%'
),
pay_30d AS (
  SELECT
    user_id,
    COUNT(DISTINCT order_id) AS order_cnt_30d,
    SUM(pay_amt)             AS gmv_30d
  FROM pay_all
  WHERE dt BETWEEN date_sub('${dt}', 30) AND date_sub('${dt}', 1)
  GROUP BY user_id
),
pay_90d AS (
  SELECT user_id, order_id, pay_amt
  FROM pay_all
  WHERE dt BETWEEN date_sub('${dt}', 90) AND date_sub('${dt}', 1)
),
item_90d AS (
  SELECT
    i.user_id,
    p.category_name,
    SUM(i.item_amt) AS cat_gmv,
    MIN(i.dt)       AS first_dt
  FROM (
    SELECT oi.order_id, o.user_id, oi.sku_id, oi.item_amt, oi.dt
    FROM dwd_order_item_di oi
    JOIN dwd_order_main_di o ON oi.order_id = o.order_id AND o.dt = oi.dt
    WHERE oi.dt BETWEEN date_sub('${dt}', 90) AND date_sub('${dt}', 1)
      AND o.order_status IN ('paid', 'shipped', 'completed')
  ) i
  JOIN dim_product_df p ON p.sku_id = i.sku_id AND p.dt = '${dt}'
  GROUP BY i.user_id, p.category_name
),
pref_cat AS (
  SELECT user_id, category_name AS preferred_category
  FROM (
    SELECT
      user_id, category_name,
      ROW_NUMBER() OVER (
        PARTITION BY user_id
        ORDER BY cat_gmv DESC, first_dt ASC, category_name ASC
      ) AS rn
    FROM item_90d
  ) t
  WHERE rn = 1
),
base AS (
  SELECT
    u.user_id,
    u.gender,
    CASE
      WHEN u.birthday IS NULL THEN 'UNKNOWN'
      WHEN CAST(DATEDIFF('${dt}', u.birthday) / 365 AS INT) BETWEEN 18 AND 24 THEN '18-24'
      WHEN CAST(DATEDIFF('${dt}', u.birthday) / 365 AS INT) BETWEEN 25 AND 34 THEN '25-34'
      WHEN CAST(DATEDIFF('${dt}', u.birthday) / 365 AS INT) BETWEEN 35 AND 44 THEN '35-44'
      WHEN CAST(DATEDIFF('${dt}', u.birthday) / 365 AS INT) >= 45 THEN '45+'
      ELSE 'UNKNOWN'
    END AS age_band,
    u.city_level,
    u.register_time,
    u.member_level,
    NVL(a.order_cnt_30d, 0) AS order_cnt_30d,
    NVL(a.gmv_30d, 0)       AS gmv_30d,
    f.first_pay_time,
    l.last_pay_time,
    h.total_order_cnt,
    pc.preferred_category
  FROM dim_user u
  LEFT JOIN pay_30d a  ON a.user_id = u.user_id
  LEFT JOIN pref_cat pc ON pc.user_id = u.user_id
  LEFT JOIN (
    SELECT user_id, MIN(pay_time) AS first_pay_time, MAX(pay_time) AS last_pay_time,
           COUNT(DISTINCT order_id) AS total_order_cnt
    FROM pay_all GROUP BY user_id
  ) f ON f.user_id = u.user_id
  LEFT JOIN (
    SELECT user_id, MAX(pay_time) AS last_pay_time FROM pay_all GROUP BY user_id
  ) l ON l.user_id = u.user_id
  LEFT JOIN (
    SELECT user_id, COUNT(DISTINCT order_id) AS total_order_cnt FROM pay_all GROUP BY user_id
  ) h ON h.user_id = u.user_id
)
INSERT OVERWRITE TABLE dws_user_profile_df PARTITION (dt = '${dt}')
SELECT
  user_id,
  NVL(gender, 'UNKNOWN')                                       AS basic_gender,
  age_band                                                     AS basic_age_band,
  NVL(city_level, 'UNKNOWN')                                   AS basic_city_level,
  CASE
    WHEN register_time IS NULL THEN 'UNKNOWN'
    WHEN DATEDIFF('${dt}', register_time) <= 7   THEN '0-7'
    WHEN DATEDIFF('${dt}', register_time) <= 30  THEN '8-30'
    WHEN DATEDIFF('${dt}', register_time) <= 90  THEN '31-90'
    WHEN DATEDIFF('${dt}', register_time) <= 365 THEN '91-365'
    ELSE '365+'
  END                                                          AS basic_register_days,
  NVL(member_level, 'UNKNOWN')                                 AS basic_member_level,
  CASE
    WHEN first_pay_time IS NULL THEN '未购'
    WHEN DATEDIFF('${dt}', first_pay_time) <= 30  THEN '0-30'
    WHEN DATEDIFF('${dt}', first_pay_time) <= 90  THEN '31-90'
    WHEN DATEDIFF('${dt}', first_pay_time) <= 180 THEN '91-180'
    ELSE '180+'
  END                                                          AS purchase_first_order_days,
  CASE
    WHEN order_cnt_30d = 0 THEN '0'
    WHEN order_cnt_30d = 1 THEN '1'
    WHEN order_cnt_30d <= 3 THEN '2-3'
    WHEN order_cnt_30d <= 9 THEN '4-9'
    ELSE '10+'
  END                                                          AS purchase_order_cnt_30d,
  CAST(NVL(gmv_30d, 0) AS DECIMAL(18,2))                       AS purchase_gmv_30d,
  CASE
    WHEN order_cnt_30d = 0 THEN '未购'
    WHEN gmv_30d / order_cnt_30d <= 50  THEN '0-50'
    WHEN gmv_30d / order_cnt_30d <= 100 THEN '50-100'
    WHEN gmv_30d / order_cnt_30d <= 300 THEN '100-300'
    ELSE '300+'
  END                                                          AS purchase_aov_band,
  CASE
    WHEN last_pay_time IS NULL THEN '未购'
    WHEN DATEDIFF('${dt}', last_pay_time) <= 7  THEN '0-7'
    WHEN DATEDIFF('${dt}', last_pay_time) <= 30 THEN '8-30'
    WHEN DATEDIFF('${dt}', last_pay_time) <= 90 THEN '31-90'
    ELSE '90+'
  END                                                          AS purchase_last_pay_days,
  CASE
    WHEN total_order_cnt IS NULL THEN '未购'
    WHEN total_order_cnt >= 2 THEN '是'
    ELSE '否'
  END                                                          AS purchase_is_repurchase,
  NVL(preferred_category, '无')                                AS purchase_preferred_category
FROM base;
