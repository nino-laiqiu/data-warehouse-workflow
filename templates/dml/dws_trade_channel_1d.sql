-- =============================================================================
-- 目标表 : dws.dws_trade_channel_1d
-- 粒度   : 日 × 渠道
-- 上游   : dwd.dwd_order_main_di / dwd.dwd_pay_flow_di
-- 说明   : GMV 按支付时间归日；下单量另起一列，不要合并
-- =============================================================================

INSERT OVERWRITE TABLE dws.dws_trade_channel_1d PARTITION (dt = '${bizdate}')
SELECT
    o.channel                                        AS channel,
    COUNT(DISTINCT o.order_id)                       AS order_create_cnt,
    SUM(o.order_amount)                              AS order_create_amt,
    COUNT(DISTINCT CASE WHEN p.pay_status = 'success' THEN p.order_id END)
                                                     AS pay_order_cnt,
    SUM(CASE WHEN p.pay_status = 'success' THEN p.pay_amount ELSE 0 END)
                                                     AS pay_amt,
    SUM(CASE WHEN p.pay_status = 'success' THEN p.pay_amount ELSE 0 END)
        / NULLIF(COUNT(DISTINCT CASE WHEN p.pay_status = 'success' THEN p.order_id END), 0)
                                                     AS aov
FROM dwd.dwd_order_main_di o
LEFT JOIN dwd.dwd_pay_flow_di p
       ON o.order_id = p.order_id
      AND p.dt = '${bizdate}'
WHERE o.dt = '${bizdate}'
GROUP BY o.channel;
