-- =============================================================================
-- 用途   : 渠道 GMV 日报 T+1 装载，写 dws.dws_trade_channel_1d 的 dt='${dt}' 分区
-- 粒度   : 天 × 渠道；目标分区内 channel_code 唯一（GROUP BY 保证）
-- 事实源 : dwd.dwd_pay_flow_di（支付流水，按 pay_time 归日，分区即 pay_time 日期）
-- 维表源 : dim.dim_channel_df（channel_code -> channel_name）
-- 口径   : GMV       见 ontology/metric/atomic/gmv.yaml       id=GMV
--          ORDER_CNT 见 ontology/metric/atomic/order_cnt.yaml id=ORDER_CNT
--          AOV       见 ontology/metric/derived/aov.yaml      id=AOV，non_additive
--          渠道      见 ontology/dict/channel.yaml            id=CHANNEL
-- 参数   : ${dt}  业务日期，格式 yyyy-MM-dd，等于 pay_time 所在日期
-- 重跑   : 静态分区 INSERT OVERWRITE，重跑同一 ${dt} 结果一致（幂等）；
--          迟到数据（T+1 补报）只需重跑对应 dt，不需要回刷其他分区。
-- 说明   : 本脚本只读不写上游；上游分区不存在时会写出 0 行，由调度侧前置检查拦截，
--          不在此处造兜底假数据。
-- =============================================================================

INSERT OVERWRITE TABLE dws.dws_trade_channel_1d PARTITION (dt = '${dt}')
SELECT
    -- 列顺序与 01_dws_trade_channel_1d.sql 的 DDL 严格一致，不使用 SELECT *
    p.channel_code                                              AS channel_code,
    COALESCE(c.channel_name, '未识别')                          AS channel_name,
    CAST(p.gmv AS DECIMAL(18,2))                                AS gmv,
    p.order_cnt                                                 AS order_cnt,
    -- AOV：分子分母都来自本行同渠道同一天的同一批流水，比率不可加，不在这里做任何平均
    CAST(p.gmv / NULLIF(p.order_cnt, 0) AS DECIMAL(18,4))        AS aov
FROM (
    -- 第二层：按渠道汇总。SUM(pay_amt) 是可加的 GMV，COUNT(DISTINCT order_id) 是订单数，
    -- 两者在同一层算完，杜绝"先算日客单价再平均"的写法
    SELECT
        d.channel_code,
        SUM(d.pay_amt)             AS gmv,
        COUNT(DISTINCT d.order_id) AS order_cnt
    FROM (
        -- 第一层：流水级去重。渠道重发支付通知会在同一 (order_id, pay_seq) 下落多条完全相同的流水，
        -- 不去重会让 GMV 和订单数同时虚高。去重键取支付流水主键 order_id + pay_seq，
        -- 不能只按 order_id 去重，否则定金/尾款这类多笔流水会被合并、GMV 少算。
        -- 排序键用 pay_time DESC, pay_amt DESC：均为确定值，保证重跑取到同一行，幂等不依赖额外随机因子。
        SELECT
            order_id,
            pay_amt,
            -- 渠道缺失、空串或纯空白统一归 'other'，与仓库既有惯例一致
            -- （knowledge/wiki/03-事实表.md:125「未识别渠道归 other，不要丢行」），
            -- 也便于与 ads_trade_metric_1d 对账。'other' 尚未登记进 CHANNEL 字典，见 self-check.md 待确认 H3。
            -- 归一化与 P3 裁决 D3 一致：不能让空 channel_code 进入结果（REQ §6.1）。
            COALESCE(NULLIF(TRIM(channel_code), ''), 'other') AS channel_code,
            ROW_NUMBER() OVER (
                PARTITION BY order_id, pay_seq
                ORDER BY pay_time DESC, pay_amt DESC
            ) AS rn
        FROM dwd.dwd_pay_flow_di
        WHERE dt = '${dt}'
          -- 支付成功。未支付、支付失败、已关闭的流水没有成功状态，天然被排除
          AND pay_status = 'success'
          -- 口径边界：需求稿第 5 段要求"支付成功且 pay_amt > 0"。退款不回冲 = 不在这里做任何负值回冲或净额扣减
          AND pay_amt > 0
          -- 排除测试渠道。必须用 COALESCE 包一层：NULL <> 'test' 结果为 NULL，
          -- 直接写 channel_code <> 'test' 会把渠道缺失的行静默丢掉，违反"不丢行"原则。
          -- 这里与 SELECT 使用同一套归一化表达式：否则 ' test ' 会先通过过滤，再在聚合处被 TRIM 成 'test'，
          -- 测试渠道会漏进结果（B 轨自检 §4.3 已暴露该缺口，P3 裁决 D3 一并修掉）。
          AND COALESCE(NULLIF(TRIM(channel_code), ''), 'other') <> 'test'
    ) d
    WHERE d.rn = 1
    GROUP BY d.channel_code
) p
-- 维表先按渠道聚合再关联，防止维表同码多行把事实行放大（放大即违反"同一 dt+channel_code 只有一行"）
LEFT JOIN (
    SELECT
        channel_code,
        MAX(channel_name) AS channel_name
    FROM dim.dim_channel_df
    WHERE dt = '${dt}'
    GROUP BY channel_code
) c
ON p.channel_code = c.channel_code;
