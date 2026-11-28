---
name: sk-sql-dml
version: 0.1.0
owner: 开发者1/开发者2
status: spec
stage: P2
---

# sk-sql-dml — 生成幂等的分区写入 SQL

> 状态：**只有规格，没有实现**。本文定义"这个技能存在、什么时候被调用、凭什么算过"。
> 实现时要补：`schema.json`（输入输出契约）、`validate.py`（判据代码化）、至少 3 条正反用例。

## 什么时候被调用

B 线 P2；两轨各自产出 DML

## 输入

model_design + 目标表 DDL + 上游表

## 输出

一条 INSERT OVERWRITE ... PARTITION 语句 + 重跑说明

## 判据（怎么算过）

- INSERT OVERWRITE 指定分区，不许全表覆盖
- 重跑同参数结果一致（幂等）
- 字段数/类型与 DDL 一致
- 每条 SQL 带用途注释与口径引用

## 失败怎么处理

上游缺分区 → 返回依赖缺口，不写兜底假数据

## 不做什么

不建表、不改 DDL（那是 sk-sql-ddl）
