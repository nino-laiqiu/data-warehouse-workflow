---
name: sk-ont-validate
version: 0.1.0
owner: 需求分析员
status: spec
stage: P2
---

# sk-ont-validate — 校验本体变更提案（ontology_delta）

> 状态：**只有规格，没有实现**。实现时要补 `schema.json`、`validate.py` 与正反用例。

## 什么时候被调用

B 线 P2 一开始：需求里出现本体里没有的业务名词，或已有对象缺字段时，先出 `ontology_delta` 提案，再动 SQL。

## 输入

`ontology_delta.json`（契约已有：[contracts/ontology_delta.schema.json](../contracts/ontology_delta.schema.json)）

## 输出

pass / violations[]：op 合法性、kind 枚举、target 是否存在、字段是否已存在、impact 是否写清、migration 是否可执行

## 判据（怎么算过）

- `op` ∈ add|update|deprecate|rename，`kind` ∈ object|process|metric|dict|dict_value|link|constraint
- `target` 符合 `^[A-Za-z][A-Za-z0-9_]{2,63}$`，且与 `op` 匹配（add 不许已存在，update/deprecate 必须已存在）
- `reason` ≥10 字，写清为什么现有本体不够用
- `impact` 必须点出受影响的表/列/规则，`migration` 必须可执行（重跑哪条命令）

## 失败怎么处理

提案不合法 → 打回需求分析员；本体里已有同名对象 → 改成 update 而不是 add。

## 不做什么

不写本体文件（只有人能改 `ontology/`），只校验提案。
