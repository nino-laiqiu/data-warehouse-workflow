# dws_user_profile_df · 数据字典

用户画像宽表，T+1 全量快照，一个用户一行。对应需求 `REQ-20261122-02`。

- 粒度：`user_id`（当日 `dim_user_df` 的全部用户）
- 分区：`dt`（`yyyy-MM-dd`，快照日）
- 存储：ORC + SNAPPY，`INSERT OVERWRITE` 覆盖，可重跑
- 更新：每天 03:00 产出，`dt` 分区内的业务数据口径为 `[dt-N, dt-1]`，**不含当天**

## 字段

| 列 | 类型 | 含义 | 值域 | 来源 |
|---|---|---|---|---|
| `user_id` | STRING | 用户 ID | — | `dim_user_df.user_id` |
| `basic_gender` | STRING | 性别 | 男 / 女 / UNKNOWN | `dim_user_df.gender` |
| `basic_age_band` | STRING | 年龄段 | 18-24 / 25-34 / 35-44 / 45+ / UNKNOWN | `birthday` 按 `dt` 折算年龄 |
| `basic_city_level` | STRING | 城市等级 | 1线 / 2线 / 3线 / 4线及以下 / UNKNOWN | `dim_user_df.city_level` |
| `basic_register_days` | STRING | 注册天数档 | 0-7 / 8-30 / 31-90 / 91-365 / 365+ | `register_time` |
| `basic_member_level` | STRING | 会员等级 | V0 / V1 / V2 / V3 / UNKNOWN | `dim_user_df.member_level` |
| `purchase_first_order_days` | STRING | 首单距今天数档（终身首单） | 未购 / 0-30 / 31-90 / 91-180 / 180+ | `dwd_pay_flow_di.min(pay_time)` |
| `purchase_order_cnt_30d` | STRING | 近 30 天订单数档 | 0 / 1 / 2-3 / 4-9 / 10+ | `COUNT(DISTINCT order_id)` |
| `purchase_gmv_30d` | DECIMAL(18,2) | 近 30 天 GMV（元） | ≥ 0 | `SUM(pay_amt)`，`pay_amt > 0` |
| `purchase_aov_band` | STRING | 客单价档 | 0-50 / 50-100 / 100-300 / 300+ / 未购 | 近 30 天 GMV ÷ 订单数 |
| `purchase_last_pay_days` | STRING | 最近支付距今天数档 | 0-7 / 8-30 / 31-90 / 90+ / 未购 | `dwd_pay_flow_di.max(pay_time)` |
| `purchase_is_repurchase` | STRING | 是否复购（终身 ≥2 单） | 是 / 否 / 未购 | `COUNT(DISTINCT order_id)` 全量 |
| `purchase_preferred_category` | STRING | 偏好品类（近 90 天 GMV 最高） | 品类名 / 无 | `dwd_order_item_di` × `dim_product_df` |

## 三个容易踩的口径

1. **`未购` 是终身状态，`0` 只是近 30 天**。`purchase_order_cnt_30d = '0'` 的人可能两年前买过，此时 `purchase_is_repurchase` 是 `是/否`，不是 `未购`。
2. **`UNKNOWN` 只出现在基础画像**，购买类标签用 `未购`/`无` 表达"没有值"，因为"没有性别"和"没有购买"是两种不同的缺失。
3. **`purchase_gmv_30d` 是金额，不是档位**。想按金额分层自己写 `CASE`，不要用 `purchase_aov_band` 代替。

## 圈人示例

```sql
-- 近 30 天有购买、客单价 100 以上的女性用户
SELECT user_id
FROM dws_user_profile_df
WHERE dt = '2026-11-21'
  AND basic_gender = '女'
  AND purchase_order_cnt_30d <> '0'
  AND purchase_aov_band IN ('100-300', '300+');

-- 流失预警：曾经买过、但最近 90 天没买
SELECT user_id
FROM dws_user_profile_df
WHERE dt = '2026-11-21'
  AND purchase_is_repurchase IN ('是', '否')
  AND purchase_last_pay_days = '90+';
```

## 已知边界

- 只覆盖**有账号的用户**；设备级行为（未登录）不在本表。
- 偏好品类依赖 `dim_product_df` 的品类归属，品类体系调整后历史分区不会重算。
- 注册天数档 `365+` 不细分，需要精确天数请回 `dim_user_df`。
- 下游 `ads_user_segment` 读本表做圈人，**变更列名或值域必须先通知运营平台**。
