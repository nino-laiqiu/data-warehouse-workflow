-- ============================================================
-- final / 03_etl_dws_user_profile_df.sql
-- 来源：track-1，按 verdict.md 修了三处
--   1) 合并 f/l/h 三次 pay_all 扫描为一次 pay_meta
--   2) 删掉从未被引用的 pay_90d CTE
--   3) 列名与 dim_tag_df.tag_code 对齐（注释标注 tag_code）
-- 幂等：INSERT OVERWRITE 覆盖分区
-- ============================================================

WITH dim_user AS (
  SELECT user_id, gender, birthday, city_level, register_time, member_level
  FROM (
    SELECT user_id, gender, birthday, city_level, register_time, member_level,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY start_date DESC) AS rn
    FROM dim_user_df
    WHERE dt = '${dt}'
      AND is_test = 0
  ) t
  WHERE rn = 1
),
pay_all AS (
  SELECT user_id, order_id, pay_time, pay_amt, dt
  FROM dwd_pay_flow_di
  WHERE dt <= date_sub('${dt}', 1)
    AND pay_amt > 0
),
pay_30d AS (
  SELECT user_id,
         COUNT(DISTINCT order_id) AS order_cnt_30d,
         SUM(pay_amt)             AS gmv_30d
  FROM pay_all
  WHERE dt BETWEEN date_sub('${dt}', 30) AND date_sub('${dt}', 1)
  GROUP BY user_id
),
pay_meta AS (
  SELECT user_id,
         MIN(pay_time)            AS first_pay_time,
         MAX(pay_time)            AS last_pay_time,
         COUNT(DISTINCT order_id) AS total_order_cnt
  FROM pay_all
  GROUP BY user_id
),
pref_cat AS (
  SELECT user_id, category_name
  FROM (
    SELECT i.user_id, i.category_name,
           ROW_NUMBER() OVER (
             PARTITION BY i.user_id
             ORDER BY i.cat_gmv DESC, i.cate_l1_id ASC
           ) AS rn
    FROM (
      SELECT o.user_id, p.category_name, p.cate_l1_id,
             SUM(oi.item_amt) AS cat_gmv
      FROM dwd_order_item_di oi
      JOIN dwd_order_main_di o
        ON oi.order_id = o.order_id AND o.dt = oi.dt
       AND o.order_status IN ('paid', 'shipped', 'completed')
      JOIN dim_product_df p ON p.sku_id = oi.sku_id AND p.dt = '${dt}'
      WHERE oi.dt BETWEEN date_sub('${dt}', 30) AND date_sub('${dt}', 1)
      GROUP BY o.user_id, p.category_name, p.cate_l1_id
    ) i
  ) x
  WHERE rn = 1
),
base AS (
  SELECT
    u.user_id,
    NVL(u.gender, 'UNKNOWN')                                   AS gender,
    u.birthday,
    NVL(u.city_level, 'UNKNOWN')                               AS city_level,
    u.register_time,
    NVL(u.member_level, 'UNKNOWN')                             AS member_level,
    NVL(a.order_cnt_30d, 0)                                    AS order_cnt_30d,
    NVL(a.gmv_30d, 0)                                          AS gmv_30d,
    m.first_pay_time,
    m.last_pay_time,
    NVL(m.total_order_cnt, 0)                                  AS total_order_cnt,
    NVL(pc.category_name, '无')                                AS preferred_category
  FROM dim_user u
  LEFT JOIN pay_30d  a  ON a.user_id = u.user_id
  LEFT JOIN pay_meta m  ON m.user_id = u.user_id
  LEFT JOIN pref_cat pc ON pc.user_id = u.user_id
)
INSERT OVERWRITE TABLE dws_user_profile_df PARTITION (dt = '${dt}')
SELECT
  user_id,
  gender                                                       AS basic_gender,
  CASE
    WHEN birthday IS NULL THEN 'UNKNOWN'
    WHEN CAST(DATEDIFF('${dt}', birthday) / 365 AS INT) < 18 THEN '<18'
    WHEN CAST(DATEDIFF('${dt}', birthday) / 365 AS INT) BETWEEN 18 AND 24 THEN '18-24'
    WHEN CAST(DATEDIFF('${dt}', birthday) / 365 AS INT) BETWEEN 25 AND 34 THEN '25-34'
    WHEN CAST(DATEDIFF('${dt}', birthday) / 365 AS INT) BETWEEN 35 AND 44 THEN '35-44'
    WHEN CAST(DATEDIFF('${dt}', birthday) / 365 AS INT) >= 45 THEN '45+'
    ELSE 'UNKNOWN'
  END                                                          AS basic_age_band,
  city_level                                                   AS basic_city_level,
  CASE
    WHEN register_time IS NULL THEN 'UNKNOWN'
    WHEN DATEDIFF('${dt}', register_time) <= 7   THEN '0-7'
    WHEN DATEDIFF('${dt}', register_time) <= 30  THEN '8-30'
    WHEN DATEDIFF('${dt}', register_time) <= 90  THEN '31-90'
    WHEN DATEDIFF('${dt}', register_time) <= 365 THEN '91-365'
    ELSE '365+'
  END                                                          AS basic_register_days,
  member_level                                                 AS basic_member_level,
  CASE
    WHEN first_pay_time IS NULL THEN '未购'
    WHEN DATEDIFF('${dt}', first_pay_time) <= 7   THEN '0-7'
    WHEN DATEDIFF('${dt}', first_pay_time) <= 30  THEN '8-30'
    WHEN DATEDIFF('${dt}', first_pay_time) <= 90  THEN '31-90'
    ELSE '90+'
  END                                                          AS purchase_first_order_days,
  CASE
    WHEN order_cnt_30d = 0  THEN '0'
    WHEN order_cnt_30d = 1  THEN '1'
    WHEN order_cnt_30d <= 3 THEN '2-3'
    WHEN order_cnt_30d <= 9 THEN '4-9'
    ELSE '10+'
  END                                                          AS purchase_order_cnt_30d,
  CAST(gmv_30d AS DECIMAL(18, 2))                              AS purchase_gmv_30d,
  CASE
    WHEN order_cnt_30d = 0                       THEN '未购'
    WHEN gmv_30d / order_cnt_30d < 50            THEN '<50'
    WHEN gmv_30d / order_cnt_30d < 100           THEN '50-100'
    WHEN gmv_30d / order_cnt_30d < 300           THEN '100-300'
    WHEN gmv_30d / order_cnt_30d < 1000          THEN '300-1000'
    ELSE '1000+'
  END                                                          AS purchase_aov_band,
  CASE
    WHEN last_pay_time IS NULL THEN '未购'
    WHEN DATEDIFF('${dt}', last_pay_time) <= 7  THEN '0-7'
    WHEN DATEDIFF('${dt}', last_pay_time) <= 30 THEN '8-30'
    WHEN DATEDIFF('${dt}', last_pay_time) <= 90 THEN '31-90'
    ELSE '90+'
  END                                                          AS purchase_last_pay_days,
  CASE
    WHEN total_order_cnt = 0  THEN '未购'
    WHEN total_order_cnt >= 2 THEN '是'
    ELSE '否'
  END                                                          AS purchase_is_repurchase,
  preferred_category                                           AS purchase_preferred_category
FROM base;
