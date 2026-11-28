-- ============================================================
-- 由 tools/dq_to_sql.py 从 dq_rules.json 生成，不要手改
-- 需求：REQ-20261122-02　规则：12 条　目标表：dws_user_profile_df
-- 用法：hive -hivevar dt=2026-11-21 -f dq_check.sql
-- 判定：每条断言返回 0（或 0 行）= 通过
-- ============================================================

-- DQ-001 用户粒度唯一 [unique/block]
-- 期望：返回 0
-- 说明：一个用户一行是这张表的定义；出现重复说明上游 dim_user_df 去重失效或 join 放大了
-- 失败动作：阻断下游，回查 dim_user_df 的 ROW_NUMBER 去重
SELECT COUNT(1) FROM (SELECT user_id FROM dws_user_profile_df WHERE dt = '${dt}' GROUP BY user_id HAVING COUNT(1) > 1) t;

-- DQ-002 13 列不允许 NULL [null/block]
-- 期望：返回 0
-- 说明：ETL 里每个字段都套了 NVL，理论上不可能为 NULL；一旦出现说明新加了列没做兜底
-- 失败动作：阻断下游
SELECT COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}' AND (user_id IS NULL OR basic_gender IS NULL OR basic_age_band IS NULL OR basic_city_level IS NULL OR basic_register_days IS NULL OR basic_member_level IS NULL OR purchase_first_order_days IS NULL OR purchase_order_cnt_30d IS NULL OR purchase_gmv_30d IS NULL OR purchase_aov_band IS NULL OR purchase_last_pay_days IS NULL OR purchase_is_repurchase IS NULL OR purchase_preferred_category IS NULL);

-- DQ-003 枚举值域合法 [domain/block]
-- 期望：返回 0
-- 说明：值域必须与 dim_tag_df.tag_value 一致；两处不一致会导致圈人条件查不出人
-- 失败动作：阻断下游
SELECT COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}' AND (basic_gender NOT IN ('男','女','UNKNOWN') OR basic_age_band NOT IN ('<18','18-24','25-34','35-44','45+','UNKNOWN') OR basic_city_level NOT IN ('1线','2线','3线','4线及以下','UNKNOWN') OR basic_register_days NOT IN ('0-7','8-30','31-90','91-365','365+') OR basic_member_level NOT IN ('V0','V1','V2','V3','UNKNOWN') OR purchase_first_order_days NOT IN ('未购','0-7','8-30','31-90','90+') OR purchase_order_cnt_30d NOT IN ('0','1','2-3','4-9','10+') OR purchase_aov_band NOT IN ('未购','<50','50-100','100-300','300-1000','1000+') OR purchase_last_pay_days NOT IN ('0-7','8-30','31-90','90+','未购') OR purchase_is_repurchase NOT IN ('是','否','未购'));

-- DQ-004 GMV 非负 [range/block]
-- 期望：返回 0
-- 说明：退款在 ODS 里是负数流水，这里只取 pay_amt > 0 的支付流水，不该出现负 GMV
-- 失败动作：阻断下游
SELECT COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}' AND purchase_gmv_30d < 0;

-- DQ-005 未购用户的四个购买标签互相自洽 [reconcile/block]
-- 期望：返回 0
-- 说明：未购是终身状态（total_order_cnt = 0），近 30 天没买不等于未购，因此只查单向蕴含
-- 失败动作：阻断下游
SELECT COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}' AND purchase_is_repurchase = '未购' AND (purchase_order_cnt_30d <> '0' OR purchase_last_pay_days <> '未购' OR purchase_aov_band <> '未购' OR purchase_first_order_days <> '未购');

-- DQ-006 行数等于当日用户数 [volume/block]
-- 期望：返回 0
-- 说明：宽表是全量快照，多一个少一个都说明 join 丢行或放大
-- 失败动作：阻断下游
SELECT ABS((SELECT COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}') - (SELECT COUNT(DISTINCT user_id) FROM dim_user_df WHERE dt = '${dt}'));

-- DQ-007 分区非空 [freshness/block]
-- 期望：行数 >= 1
-- 说明：空分区通常意味着上游依赖没就绪，调度却硬跑了
-- 失败动作：告警并阻断下游
SELECT COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}';

-- DQ-008 近 30 天 GMV 与源表对得上 [reconcile/block]
-- 期望：比值 <= 0.0001
-- 说明：允许 0.01% 的差异（dim 里缺席的用户），超出说明过滤条件两处不一致
-- 失败动作：阻断下游
SELECT ABS(SUM(purchase_gmv_30d) - (SELECT SUM(pay_amt) FROM dwd_pay_flow_di WHERE dt BETWEEN date_sub('${dt}', 30) AND date_sub('${dt}', 1) AND pay_amt > 0 AND user_id NOT LIKE 'test\_%')) / NULLIF(SUM(purchase_gmv_30d), 0) FROM dws_user_profile_df WHERE dt = '${dt}';

-- DQ-009 UNKNOWN 占比不超过 5% [null/warn]
-- 期望：返回 0 行
-- 说明：UNKNOWN 兜底会掩盖维度缺失；超过 5% 说明 dim 源头采集有问题，不是标签本身的问题
-- 失败动作：告警，不阻断
SELECT col, ratio FROM (SELECT 'basic_gender' AS col, SUM(CASE WHEN basic_gender = 'UNKNOWN' THEN 1 ELSE 0 END) / COUNT(1) AS ratio FROM dws_user_profile_df WHERE dt = '${dt}' UNION ALL SELECT 'basic_age_band', SUM(CASE WHEN basic_age_band = 'UNKNOWN' THEN 1 ELSE 0 END) / COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}' UNION ALL SELECT 'basic_city_level', SUM(CASE WHEN basic_city_level = 'UNKNOWN' THEN 1 ELSE 0 END) / COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}' UNION ALL SELECT 'basic_member_level', SUM(CASE WHEN basic_member_level = 'UNKNOWN' THEN 1 ELSE 0 END) / COUNT(1) FROM dws_user_profile_df WHERE dt = '${dt}') t WHERE ratio > 0.05;

-- DQ-010 首单距今天数只增不减 [monotonic/block]
-- 期望：返回 0
-- 说明：首单时间写死不变，距今天数必然单调变大；回退说明 pay_all 的 scan 范围被悄悄改了
-- 失败动作：阻断下游
SELECT COUNT(1) FROM (SELECT a.user_id, CASE a.purchase_first_order_days WHEN '0-7' THEN 1 WHEN '8-30' THEN 2 WHEN '31-90' THEN 3 ELSE 4 END AS cur_r, CASE b.purchase_first_order_days WHEN '0-7' THEN 1 WHEN '8-30' THEN 2 WHEN '31-90' THEN 3 ELSE 4 END AS prev_r FROM (SELECT user_id, purchase_first_order_days FROM dws_user_profile_df WHERE dt = '${dt}') a JOIN (SELECT user_id, purchase_first_order_days FROM dws_user_profile_df WHERE dt = date_sub('${dt}', 1)) b ON a.user_id = b.user_id WHERE a.purchase_first_order_days <> '未购' AND b.purchase_first_order_days <> '未购') t WHERE cur_r < prev_r;

-- DQ-011 重跑指纹一致 [volume/block]
-- 期望：重跑两次指纹一致
-- 说明：INSERT OVERWRITE 的幂等性验证：同 dt 连跑两次，四个指纹必须完全相同
-- 失败动作：阻断发布
SELECT COUNT(1) AS row_cnt, COUNT(DISTINCT user_id) AS user_cnt, SUM(purchase_gmv_30d) AS gmv_sum, SUM(CASE WHEN purchase_is_repurchase = '是' THEN 1 ELSE 0 END) AS repeat_cnt FROM dws_user_profile_df WHERE dt = '${dt}';

-- DQ-012 宽表用户都能在维表里找到 [reconcile/block]
-- 期望：返回 0
-- 说明：反向一致性：宽表里出现维表没有的用户，说明下游圈人时关联不上
-- 失败动作：阻断下游
SELECT COUNT(1) FROM (SELECT user_id FROM dws_user_profile_df WHERE dt = '${dt}') p LEFT JOIN (SELECT DISTINCT user_id FROM dim_user_df WHERE dt = '${dt}') d ON p.user_id = d.user_id WHERE d.user_id IS NULL;
