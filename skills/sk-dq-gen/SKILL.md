---
name: sk-dq-gen
version: 0.1.0
owner: 需求分析员
status: spec
stage: P4
---

# sk-dq-gen — 由表结构与口径生成质量规则

> 状态：**只有规格，没有实现**。本文定义"这个技能存在、什么时候被调用、凭什么算过"。
> 实现时要补：`schema.json`（输入输出契约）、`validate.py`（判据代码化）、至少 3 条正反用例。

## 什么时候被调用

B 线 P4；final SQL 定稿后

## 输入

final DDL + 口径（含时间窗与缺失值策略）+ 上游表

## 输出

dq_rules.json（契约已有）+ 可执行 dq_check.sql

## 判据（怎么算过）

- 必须覆盖 null / unique / monotonic 三类
- 每条规则一条只读 SQL 且含 ${dt}
- 期望值必须可机器判定（zero_rows 等）
- 跨表对账类要写阈值

## 失败怎么处理

口径缺失关键定义 → 停，回 P1；不许用宽泛规则凑数

## 不做什么

不执行检查（执行是 verify_live 的事）
