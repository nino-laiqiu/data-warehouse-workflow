-- ============================================================
-- track-2 / 02_dws_user_tag_df.sql
-- 标签事实表（长表 / EAV）：用户 × 标签 × 日 一行，12 个标签 = 12 行
-- 注意：dt 只出现在 PARTITIONED BY 里，不能再写进列定义（Hive 会报重复列）
-- ============================================================

CREATE TABLE IF NOT EXISTS dws_user_tag_df (
  user_id       STRING  COMMENT '用户ID',
  tag_code      STRING  COMMENT '标签编码，对应 dim_tag_df.tag_code',
  tag_value     STRING  COMMENT '标签值，字符串形式；数值型同时写入 tag_num',
  tag_num       DECIMAL(18,2) COMMENT '数值型标签的数值，非数值型为NULL',
  tag_category  STRING  COMMENT '标签大类：basic/purchase（冗余，避免每次查字典）'
)
COMMENT '用户标签事实表：一行一个用户的一个标签，缺标签不落行'
PARTITIONED BY (dt STRING COMMENT '日期分区，格式 yyyy-MM-dd，快照日')
STORED AS ORC
TBLPROPERTIES ('orc.compress' = 'SNAPPY');
