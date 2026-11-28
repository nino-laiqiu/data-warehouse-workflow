-- =============================================================================
-- 表名   : dws.dws_trade_channel_1d
-- 粒度   : 天 × 渠道，一个 dt + channel_code 只有一行
-- 主键   : dt + channel_code
-- 分区   : dt STRING 'yyyy-MM-dd'，按支付时间 pay_time 归日（T+1）
-- 上游   : dwd.dwd_pay_flow_di    GMV / 支付订单数的事实来源
--          dim.dim_channel_df     只取渠道名称，不参与指标计算
-- 下游   : 渠道日报、上周同日对比、ads 层
-- 口径   : GMV       = ontology/metric/atomic/gmv.yaml        id GMV
--          ORDER_CNT = ontology/metric/atomic/order_cnt.yaml  id ORDER_CNT
--          AOV       = ontology/metric/derived/aov.yaml       id AOV，non_additive
--          渠道      = ontology/dict/channel.yaml             id CHANNEL
-- 说明   : aov 是派生比率，只对"本行"成立。跨天/跨渠道汇总必须回到
--          分子分母，用 SUM(gmv)/SUM(order_cnt) 重算，禁止 AVG(aov)。
--          本表不存运费、退款、下单量，也不做城市/品类拆分。
-- =============================================================================

CREATE EXTERNAL TABLE IF NOT EXISTS dws.dws_trade_channel_1d (
  channel_code  STRING         COMMENT '渠道码，值域见本体 CHANNEL 字典；未识别渠道落 unknown，不丢行',
  channel_name  STRING         COMMENT '渠道名称，取自 dim_channel_df；维表缺行时兜底为 channel_code',
  gmv           DECIMAL(18,2)  COMMENT '成交总额，单位元；支付成功、不含运费、退款不回冲，按 pay_time 归日',
  order_cnt     BIGINT         COMMENT '支付订单数，按 order_id 去重；部分退款不重复计入，一个订单只计 1',
  aov           DECIMAL(18,4)  COMMENT '客单价=GMV/ORDER_CNT，单位元；比率不可加，保留 4 位仅为减少舍入，禁止据此跨维度加总'
)
COMMENT '渠道交易日报：天 × 渠道，含 GMV / 支付订单数 / 客单价，用于渠道日报与上周同日对比'
PARTITIONED BY (dt STRING COMMENT '分区日期 yyyy-MM-dd，按支付时间 pay_time 归日')
STORED AS ORC
TBLPROPERTIES ('orc.compress' = 'SNAPPY');
