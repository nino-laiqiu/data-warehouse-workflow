-- =============================================================================
-- 任务   : dws.dws_trade_channel_1d 日装载（T+1）
-- 目标   : 只覆盖 dt='${dt}' 这一个静态分区，不触碰历史分区
-- 粒度   : 天 × 渠道，dt + channel_code 唯一
-- 输入   : dwd.dwd_pay_flow_di   dt 分区按 pay_time 归日，GMV/订单数的唯一事实来源
--          dim.dim_channel_df    dt 快照分区，只取 channel_name，不参与指标计算
-- 口径   : GMV       = ontology/metric/atomic/gmv.yaml        id GMV
--          ORDER_CNT = ontology/metric/atomic/order_cnt.yaml  id ORDER_CNT
--          AOV       = ontology/metric/derived/aov.yaml       id AOV，non_additive
--          渠道      = ontology/dict/channel.yaml             id CHANNEL
-- 幂等   : 静态分区 INSERT OVERWRITE，同一 ${dt} 重跑任意次结果逐行一致；
--          去重采用确定性排序键，不依赖执行计划与文件顺序
-- 用法   : hive --hivevar dt=2026-11-22 -f 02_etl_dws_trade_channel_1d.sql
--          spark-sql --hivevar dt=2026-11-22 -f 02_etl_dws_trade_channel_1d.sql
--          调度必须显式传 dt，不设缺省值：缺省成"昨天"会把重跑变成写错分区
-- =============================================================================

INSERT OVERWRITE TABLE dws.dws_trade_channel_1d PARTITION (dt = '${dt}')
SELECT
    p.channel_code                                         AS channel_code,
    COALESCE(d.channel_name, p.channel_code)               AS channel_name,
    CAST(p.gmv AS DECIMAL(18,2))                           AS gmv,
    p.order_cnt                                            AS order_cnt,
    CAST(p.gmv / NULLIF(p.order_cnt, 0) AS DECIMAL(18,4))  AS aov
FROM (
    -- 第 2 层：按渠道聚合。
    -- GMV 可加，直接 SUM；订单数是去重计数，必须 COUNT(DISTINCT order_id)，
    -- 否则"定金 + 尾款"两笔流水会把一个订单算成两单。
    SELECT
        COALESCE(NULLIF(TRIM(f.channel_code), ''), 'unknown') AS channel_code,
        SUM(f.pay_amt)                                         AS gmv,
        COUNT(DISTINCT f.order_id)                             AS order_cnt
    FROM (
        -- 第 1 层：支付流水去重。
        -- 渠道会重发支付回调，同一笔流水落多行。流水键取 (order_id, pay_seq)
        -- ——这是 dwd_pay_flow_di 的声明主键；pay_seq 缺失时退化用 pay_id，
        -- 保证"同一订单的多笔真实流水"不会被折叠成一笔。
        -- 排序键 pay_time DESC, pay_id DESC 是为了让重跑取到同一行（幂等），
        -- 而不是取"金额更大"的那行：金额以最后到达的回调为准。
        SELECT
            f0.order_id,
            f0.pay_amt,
            f0.channel_code,
            f0.pay_time,
            ROW_NUMBER() OVER (
                PARTITION BY f0.order_id, COALESCE(f0.pay_seq, f0.pay_id)
                ORDER BY f0.pay_time DESC, f0.pay_id DESC
            ) AS rn
        FROM dwd.dwd_pay_flow_di f0
        WHERE f0.dt = '${dt}'
          -- 归日双重保险：分区本身按 pay_time 归日，再显式卡一次，
          -- 防上游分区错标把别的日子的支付算进来。TO_DATE 对 STRING /
          -- TIMESTAMP 两种存储都成立，不依赖 pay_time 的具体类型。
          AND TO_DATE(f0.pay_time) = TO_DATE('${dt}')
          AND f0.pay_status = 'success'
          AND f0.pay_amt > 0
          -- 'test' 是测试渠道，口径边界明确排除；NULL 必须显式放行
          -- （NULL <> 'test' 结果为 NULL，会把未识别渠道整行滤掉，静默丢 GMV）
          AND (f0.channel_code IS NULL OR f0.channel_code <> 'test')
    ) f
    WHERE f.rn = 1
    GROUP BY COALESCE(NULLIF(TRIM(f.channel_code), ''), 'unknown')
) p
-- 维表只补名称。用 LEFT JOIN 而不是 INNER：维表缺渠道时指标行仍要保留，
-- 否则 GMV 合计对不上上游。channel_name 兜底为 channel_code，避免空名称。
LEFT JOIN (
    SELECT channel_code, channel_name
    FROM dim.dim_channel_df
    WHERE dt = '${dt}'
) d
  ON p.channel_code = d.channel_code;
