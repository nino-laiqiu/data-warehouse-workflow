---
name: sk-trial-run
version: 0.1.0
owner: 开发者1
status: spec
stage: P3B
---

# sk-trial-run — 把 final/ 脚本放进环境试跑并出质检报告

> 状态：**只有规格，没有实现**。可执行的工具已经存在（`tools/trial_run.py`），但还没有把它包成带输入输出契约与判据的 skill。
> 实现时要补：`schema.json`（输入输出契约）、`validate.py`（判据代码化）、至少 3 条正反用例（连通失败 / EXPLAIN 失败 / 结果为空）。

## 什么时候被调用

B 线 P3B，紧接 G3 裁决之后；对 `监督者/final/*.sql` 执行

## 输入

`requirements/<需求目录>/需求开发员/监督者/final/*.sql` + 可执行环境（沙箱库连接串或 `HQL_CMD`）+ 可选 `dq_rules.json`（用于取主键唯一与对账断言）

## 输出

`requirements/<需求目录>/需求开发员/试跑/试跑报告.json`（契约见 `contracts/trial_run.schema.json`）与同名 `.md`

## 判据（怎么算过）

- `verdict` 只能是 `passed` / `failed` / `blocked`；**没连环境只能写 `blocked`**，不许写 `passed`
- `passed` 的前提：环境连通 + 每条脚本 `executed` 或 `explained` + 结果类检查全部 `pass`
- 目标库必须像沙箱（名字含 tmp / shadow / dev / 试跑 等），正式库禁止试跑
- `blocked` 想放行，必须有 `waiver{reason≥10 字, approved_by, expires_at}`，且进 journal 待办

## 失败怎么处理

- 连不上 → `blocked`，报告里写清缺什么（`HQL_CMD` / 权限 / 库名），停下不往下走
- EXPLAIN 失败 → `failed`，把引擎报错前 300 字放进 `scripts[].error`
- 结果为空或对账超阈值 → `failed`，退回 P3 修 `final/`

## 不做什么

不改 SQL（只跑，不改）；不替代 G3 裁决；不把 `blocked` 包装成通过
