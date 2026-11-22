-- =============================================================================
-- 表名   : dwd.dwd_order_main_di
-- 粒度   : 一笔订单一行（order_id 唯一）
-- 上游   : ods.ods_order_main_di
-- 下游   : dws.dws_trade_channel_1d / ads.ads_trade_metric_1d
-- 说明   : 订单主表。order_amount 是应付金额，实付看支付流水，两者不要混
-- =============================================================================

CREATE EXTERNAL TABLE IF NOT EXISTS dwd.dwd_order_main_di (
  order_id        STRING        COMMENT '订单ID，主键',
  user_id         STRING        COMMENT '下单用户ID',
  shop_id         STRING        COMMENT '店铺ID',
  channel         STRING        COMMENT '下单渠道 app/mini_program/h5/pc',
  order_status    STRING        COMMENT '订单状态，见本体 ORDER_STATUS',
  order_amount    DECIMAL(18,2) COMMENT '应付金额（不含运费）',
  freight_amount  DECIMAL(18,2) COMMENT '运费',
  discount_amount DECIMAL(18,2) COMMENT '优惠金额',
  create_time     TIMESTAMP     COMMENT '下单时间，下单指标的事件时间',
  pay_time        TIMESTAMP     COMMENT '支付时间，未支付为 NULL；GMV 按此归日'
)
COMMENT '订单主表：一笔订单一行，下单与支付都在这张表上'
PARTITIONED BY (dt STRING COMMENT '分区日期 yyyy-MM-dd，按 create_time 归日')
STORED AS ORC
TBLPROPERTIES ('orc.compress' = 'SNAPPY');
