-- ============================================================
-- track-2 / 01_dim_tag_df.sql
-- 标签字典：标签的元数据都在这里，加标签不改表结构，只加一行
-- ============================================================

CREATE TABLE IF NOT EXISTS dim_tag_df (
  tag_code      STRING  COMMENT '标签编码，全局唯一，与宽表列名/事实表 tag_code 一致',
  tag_name      STRING  COMMENT '标签中文名',
  tag_category  STRING  COMMENT '标签大类：basic/purchase',
  value_type    STRING  COMMENT '值类型：enum/number',
  value_domain  STRING  COMMENT '值域描述，enum 用 | 分隔，number 写区间',
  is_derived    INT     COMMENT '是否派生标签：1 是 0 否',
  owner         STRING  COMMENT '标签责任人'
)
COMMENT '画像标签字典：新增标签只插一行，不ALTER任何表'
STORED AS ORC
TBLPROPERTIES ('orc.compress' = 'SNAPPY');
