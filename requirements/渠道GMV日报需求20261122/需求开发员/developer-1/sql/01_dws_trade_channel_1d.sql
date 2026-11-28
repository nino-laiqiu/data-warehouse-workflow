-- =============================================================================
-- 表名   : dws.dws_trade_channel_1d
-- 粒度   : 天 × 渠道，一个 dt 下每个 channel_code 一行
-- 主键   : dt + channel_code（逻辑主键，由 ETL 的 GROUP BY 保证唯一）
-- 分区   : dt STRING，yyyy-MM-dd，按 pay_time 归日
-- 上游   : dwd.dwd_pay_flow_di   支付流水（GMV / 订单数的事实来源）
--          dim.dim_channel_df    渠道维表（渠道编码转名称）
-- 下游   : ads.ads_trade_metric_1d、渠道日报取数、上周同日对比查询
-- 口径   : GMV       见 ontology/metric/atomic/gmv.yaml       id=GMV
--          ORDER_CNT 见 ontology/metric/atomic/order_cnt.yaml id=ORDER_CNT
--          AOV       见 ontology/metric/derived/aov.yaml      id=AOV
--          渠道值域  见 ontology/dict/channel.yaml            id=CHANNEL
-- 说明   : 1. GMV 按 pay_time 归日、不含运费、退款不回冲，本表不引入退款列。
--          2. aov 是行级冗余列，只对本行成立；跨天或跨渠道汇总时
--             必须 SUM(gmv)/SUM(order_cnt) 重算，禁止 AVG(aov)。
--          3. 本表不做周同比列，上周同日对比由查询侧 dt 与 date_sub(dt,7)
--             自关联实现，避免为了一个展示列回刷 7 个历史分区。
-- =============================================================================

CREATE EXTERNAL TABLE IF NOT EXISTS dws.dws_trade_channel_1d (
  channel_code  STRING         COMMENT '渠道编码，取自支付流水的支付时刻快照；缺失归 other，非空非字典值保留原码',
  channel_name  STRING         COMMENT '渠道名称，来自 dim_channel_df；维表未匹配归 未识别',
  gmv           DECIMAL(18,2)  COMMENT '成交额，单位元；SUM(pay_amt)，不含运费，退款不回冲，口径见本体 GMV',
  order_cnt     BIGINT         COMMENT '支付订单数，单位笔；按 order_id 去重计数，口径见本体 ORDER_CNT',
  aov           DECIMAL(18,2)  COMMENT '客单价，单位元每单；gmv 除以 order_cnt，比率不可加，口径见本体 AOV'
)
COMMENT '渠道交易日报：天乘渠道粒度，一个渠道一天一行；GMV 按支付时间归日，退款不回冲'
PARTITIONED BY (dt STRING COMMENT '分区日期 yyyy-MM-dd，按支付流水的 pay_time 归日')
STORED AS ORC
TBLPROPERTIES ('orc.compress' = 'SNAPPY');
