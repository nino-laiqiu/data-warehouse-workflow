-- ============================================================
-- final / 04_dim_tag_df_data.sql
-- 标签字典初始化：12 行，一次全量覆盖
-- 说明：宽表方案的列名必须与这里的 tag_code 一致，加标签两处都要改，
--       因此这张字典同时充当"宽表列名"的唯一权威
-- ============================================================

INSERT OVERWRITE TABLE dim_tag_df
SELECT tag_code, tag_name, tag_category, value_type, value_domain, is_derived, owner FROM (
            SELECT 'basic_gender' AS tag_code, '性别' AS tag_name, 'basic' AS tag_category, 'enum' AS value_type, '男|女|UNKNOWN' AS value_domain, 0 AS is_derived, 'ontology-admin' AS owner
  UNION ALL SELECT 'basic_age_band', '年龄段', 'basic', 'enum', '18-24|25-34|35-44|45+|UNKNOWN', 1, 'ontology-admin'
  UNION ALL SELECT 'basic_city_level', '城市等级', 'basic', 'enum', '1线|2线|3线|4线及以下|UNKNOWN', 0, 'ontology-admin'
  UNION ALL SELECT 'basic_register_days', '注册天数档', 'basic', 'enum', '0-7|8-30|31-90|91-365|365+', 1, 'ontology-admin'
  UNION ALL SELECT 'basic_member_level', '会员等级', 'basic', 'enum', 'V0|V1|V2|V3|UNKNOWN', 0, 'ontology-admin'
  UNION ALL SELECT 'purchase_first_order_days', '首单距今天数档', 'purchase', 'enum', '未购|0-30|31-90|91-180|180+', 1, 'ontology-admin'
  UNION ALL SELECT 'purchase_order_cnt_30d', '近30天订单数档', 'purchase', 'enum', '0|1|2-3|4-9|10+', 1, 'ontology-admin'
  UNION ALL SELECT 'purchase_gmv_30d', '近30天GMV', 'purchase', 'number', '[0, +inf)', 1, 'ontology-admin'
  UNION ALL SELECT 'purchase_aov_band', '客单价档', 'purchase', 'enum', '未购|0-50|50-100|100-300|300+', 1, 'ontology-admin'
  UNION ALL SELECT 'purchase_last_pay_days', '最近支付距今天数档', 'purchase', 'enum', '未购|0-7|8-30|31-90|90+', 1, 'ontology-admin'
  UNION ALL SELECT 'purchase_is_repurchase', '是否复购', 'purchase', 'enum', '是|否|未购', 1, 'ontology-admin'
  UNION ALL SELECT 'purchase_preferred_category', '偏好品类', 'purchase', 'enum', '类目名|无', 1, 'ontology-admin'
) t;
