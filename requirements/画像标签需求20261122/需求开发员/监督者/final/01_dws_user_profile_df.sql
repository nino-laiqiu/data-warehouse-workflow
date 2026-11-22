-- ============================================================
-- final / 01_dws_user_profile_df.sql
-- 来源：track-1（宽表方案），未经改动，按 verdict.md 直接采用
-- 依据：requirements/画像标签需求20261122/需求分析员/REQ-20261122-02.md（12 个标签）
-- 列名规范：与 dim_tag_df.tag_code 一一对应
-- ============================================================

CREATE TABLE IF NOT EXISTS dws_user_profile_df (
  user_id                  STRING  COMMENT '用户ID',
  basic_gender             STRING  COMMENT '性别：男/女/UNKNOWN',
  basic_age_band           STRING  COMMENT '年龄段：18-24/25-34/35-44/45+/UNKNOWN',
  basic_city_level         STRING  COMMENT '城市等级：1线/2线/3线/4线及以下/UNKNOWN',
  basic_register_days      STRING  COMMENT '注册天数档：0-7/8-30/31-90/91-365/365+',
  basic_member_level       STRING  COMMENT '会员等级：V0/V1/V2/V3/UNKNOWN',
  purchase_first_order_days STRING COMMENT '首单距今天数档：未购/0-30/31-90/91-180/180+',
  purchase_order_cnt_30d   STRING  COMMENT '近30天订单数档：0/1/2-3/4-9/10+',
  purchase_gmv_30d         DECIMAL(18,2) COMMENT '近30天GMV（元）',
  purchase_aov_band        STRING  COMMENT '客单价档：0-50/50-100/100-300/300+/未购',
  purchase_last_pay_days   STRING  COMMENT '最近支付距今天数档：0-7/8-30/31-90/90+/未购',
  purchase_is_repurchase   STRING  COMMENT '是否复购：是/否/未购',
  purchase_preferred_category STRING COMMENT '偏好品类（近90天GMV最高），无则无'
)
COMMENT '用户画像宽表：T+1 全量快照，一个用户一行，标签缺失一律落 UNKNOWN'
PARTITIONED BY (dt STRING COMMENT '日期分区，格式 yyyy-MM-dd，快照日')
STORED AS ORC
TBLPROPERTIES ('orc.compress' = 'SNAPPY');
