# 范例：从一句问话到一条可信 SQL（GMV 分渠道）

这是知识库里的"范例"层：它教的是**怎么写**，不定义口径。口径在 `ontology/metric/atomic/gmv.yaml`。

## 1. 问题

> 昨天 App 和小程序的 GMV 各是多少？

## 2. 口径命中（不在本文件里解释口径）

查 `ontology/`：命中 `GMV`（唯一）。如果命中多个，停下来问人，不要自己挑一个。
`GMV` 告诉我们的硬约束：

- 按 `pay_time` 归日，不是 `create_time`
- 不含运费，退款不回冲

## 3. SQL

```sql
SELECT
    o.channel                                   AS channel,
    SUM(p.pay_amount)                           AS gmv,
    COUNT(DISTINCT p.order_id)                  AS order_cnt,
    SUM(p.pay_amount) / COUNT(DISTINCT p.order_id) AS aov
FROM dwd_pay_flow_di p
LEFT JOIN dwd_order_main_di o
       ON p.order_id = o.order_id
WHERE p.dt = '${bizdate}'
  AND p.pay_status = 'success'
GROUP BY o.channel;
```

## 4. 为什么这么写（可复用的三条经验）

1. **比率不要先在子查询里算完再平均**。`SUM/COUNT` 在明细层算，任何粒度都成立。
2. **LEFT JOIN 的方向由事实表决定**：支付流水是事实，订单是维度，反过来会把未支付订单混进来。
3. **`COUNT(DISTINCT order_id)` 而不是 `COUNT(1)`**：一个订单可能有多条支付流水（分次支付、重试）。

## 5. 自检（A4 要回答的问题）

- 结果为空：是当天真的没成交，还是分区没产出？（先查 `dt` 分区是否存在，再下结论）
- 量级异常：与上周同日比偏差 >50% 时，标记"待确认"，不要直接解释成"大促"
- 渠道合计 ≠ 全站合计：说明存在 NULL 渠道，要单独列出来，不要静默丢弃

## 6. 这一条该沉淀成什么

- 如果被 3 个人问过 → 提 `memory/decisions/` 提案，走 B 线 P4 固化成 ADS 表。
- 如果这条 SQL 被复用 5 次以上 → 提 PR 进 `templates/dml/`，不要留在聊天记录里。
