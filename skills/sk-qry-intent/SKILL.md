---
name: sk-qry-intent
version: 0.1.0
owner: 需求分析员（A 线兼岗）
status: spec
stage: A1
---

# sk-qry-intent — 把一句人话变成可执行的取数意图

> 状态：**只有规格，没有实现**。本文定义"这个技能存在、什么时候被调用、凭什么算过"。
> 实现时要补：`schema.json`（输入输出契约）、`validate.py`（判据代码化）、至少 3 条正反用例。

## 什么时候被调用

A 线第 1 步；用户提问后、找表之前

## 输入

自然语言问句 + 当前用户的表权限范围

## 输出

intent 契约（待实现）：metric(本体 id) / dims[] / window{days, anchor} / filters[] / grain / unknown_terms[]

## 判据（怎么算过）

- 指标必须命中 ontology/metric 的 id，不许自造
- 时间窗必须明确（默认 30 天且要在 caveats 里说明）
- 未定义的业务术语进 unknown_terms，不猜
- 维度必须来自本体或维表文档

## 失败怎么处理

解析不出指标 → 直接拒绝并回问，不许用相近指标顶替；有 unknown_terms → 先澄清再进 A2

## 不做什么

不写 SQL、不选表、不估算结果大小
