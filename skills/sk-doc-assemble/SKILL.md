---
name: sk-doc-assemble
version: 0.1.0
owner: 追踪者
status: spec
stage: P6
---

# sk-doc-assemble — 把过程产物汇总成交付文档

> 状态：**只有规格，没有实现**。本文定义"这个技能存在、什么时候被调用、凭什么算过"。
> 实现时要补：`schema.json`（输入输出契约）、`validate.py`（判据代码化）、至少 3 条正反用例。

## 什么时候被调用

B 线 P6；所有 artifact 已定稿

## 输入

final SQL / dq_rules / lineage / 口径确认记录 / journal

## 输出

数据字典 + 上线单 + 口径变更说明（三件套）

## 判据（怎么算过）

- 每一列都有来源与口径出处
- 与需求原文的偏差必须逐条列出
- 上线单含回滚与验证命令
- 不许写没发生过的验证结论

## 失败怎么处理

缺口径出处 → 留 TODO 并标红，不许编

## 不做什么

不改 SQL、不改口径
