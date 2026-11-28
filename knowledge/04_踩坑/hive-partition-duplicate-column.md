# Hive 分区列不能在列定义里再写一遍

## 症状

```sql
CREATE TABLE dws_x_df (
  user_id STRING COMMENT '用户ID',
  dt      STRING COMMENT '日期'          -- ← 错
)
PARTITIONED BY (dt STRING COMMENT '日期分区')
```

Hive 建表报错（重复列 / 语义冲突），或者在某些版本里静默建成一个"分区列不是分区列"的表，后续 `PARTITION (dt=...)` 写入全部异常。

## 原因

`PARTITIONED BY` 里的列会被 Hive 追加到表结构末尾，且**不存储在数据文件里**。同一个列名在数据列里再定义一次，等于声明了两个同名列。

## 正确写法

分区列只出现在 `PARTITIONED BY`：

```sql
CREATE TABLE dws_x_df (
  user_id STRING COMMENT '用户ID'
)
PARTITIONED BY (dt STRING COMMENT '日期分区')
```

写入时显式给分区值：`INSERT OVERWRITE TABLE dws_x_df PARTITION (dt = '${dt}')`。

## 怎么防

`python skills/sk-sql-ddl/validate.py --sql xxx.sql` 会检查这条（2026-11-22 补充）。
这个错误来自 REQ-20261122-02 双轨开发里 track-2 的产出，是"双轨制顺手改进工具链"的实例。

## 检查落在哪

实现是 `skills/sk-sql-ddl/validate.py` 的 `check_partition_not_in_columns()`：解析 `PARTITIONED BY (...)` 里的列名集合，与前面的列定义行求交，命中就报
`分区列 X 同时出现在列定义里，Hive 会报重复列`。

**纯 SQL 模式也会跑**（不给 `--input` 也一样），所以 CI 只拿一份 DDL 就能拦。反例放在 `.tmp/dup-partition.sql`，改这个检查时拿它回归。
