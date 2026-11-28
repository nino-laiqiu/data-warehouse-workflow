---
name: sk-sql-guard
version: 0.1.0
owner: 开发者1
status: spec
stage: P2
---

# sk-sql-guard — B 线写 SQL 的红线审核（比 A 线多三条）

> 状态：**只有规格，没有实现**。本文定义"这个技能存在、什么时候被调用、凭什么算过"。
> 实现时要补：`schema.json`（输入输出契约）、`validate.py`（判据代码化）、至少 3 条正反用例。

## 什么时候被调用

P2 产出后、G2 之前；P3 裁决后的 final 也要过

## 输入

一条 SQL + 目标表 DDL

## 输出

pass / violations[]

## 判据（怎么算过）

- A 线六条全部适用
- 写入必须带分区且分区列在列定义之后
- 目标表列与 SELECT 列数、顺序一致
- 禁用 SELECT * 写入（列序漂移风险）

## 失败怎么处理

任一不过 → 打回同一轨重写，不许跨轨借代码

## 不做什么

不改写 SQL；不评价方案优劣
