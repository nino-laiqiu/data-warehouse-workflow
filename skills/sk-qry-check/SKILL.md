---
name: sk-qry-check
version: 0.1.0
owner: 需求分析员（A 线兼岗）
status: spec
stage: A4
---

# sk-qry-check — 结果自检：这份结果能不能信

> 状态：**只有规格，没有实现**。本文定义"这个技能存在、什么时候被调用、凭什么算过"。
> 实现时要补：`schema.json`（输入输出契约）、`validate.py`（判据代码化）、至少 3 条正反用例。

## 什么时候被调用

A 线第 4 步；SQL 执行返回之后

## 输入

执行结果（行数、样例、耗时）+ intent + 口径

## 输出

check 契约（待实现）：sanity[] / consistency[] / caveats[] / confidence(high|medium|low)

## 判据（怎么算过）

- 空结果与 0 值要区分
- 行数与量级要落在一个合理区间
- 与既有 ADS 指标交叉核对，差异超阈值要说明
- 必须给出数据截止时间

## 失败怎么处理

自检不过 → 只出 caveat 降级，不许把 low 当 high 交付

## 不做什么

不下结论、不解释业务原因
