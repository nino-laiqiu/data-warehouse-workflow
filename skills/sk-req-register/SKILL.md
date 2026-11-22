---
name: sk-req-register
version: 0.1.0
owner: orchestrator
---

# SKILL: sk-req-register — 原始需求入库登记

## 这是什么

把一份放进 `requirements/inbox/` 的原始需求**登记在案**：校验模板完整性、算 `sha256`、分配编号、追加到登记簿。

**不是**什么：不改需求内容、不翻译需求、不判断需求合不合理。它只回答一个问题——"这份文件从此刻起是不是有了一个不可篡改的身份"。

## 为什么需要它

原始需求是**证据**。证据要能证明两件事：

1. 它是什么时候由谁提的（来源三要素）。
2. 它自入库以来**没有被改过**（sha256 对得上）。

没有第 2 条，"当初客户不是这么说的"这类争议永远扯不清——因为文件已经被人改过三个版本了。

## 输入

见 `schema.json`：`path`、`proposer`、`channel`、`submitted_at` 必填，`title` 可选。

## 输出

`requirements/inbox/_registry.jsonl` 追加一行：

```json
{"req_id":"REQ-20261122-01","path":"requirements/inbox/REQ-20261122-01.md","sha256":"…","proposer":"张敏","channel":"钉钉「数据需求」群","submitted_at":"2026-11-22 10:12","registered_at":"2026-11-22T16:20:03+08:00","title":"渠道 GMV 日报"}
```

同时把结果打印成 JSON：`{ok, req_id, sha256, path, registered}`。

## 硬规则

1. **幂等**：同一路径、同一 hash 重复登记 → 返回 `registered: false`，**不重复写行**。
2. **改过的文件不许重新登记**：同路径但 hash 不同 → 报错，要求另存为 `-v2`。这是唯一能发现"有人偷偷改了原始需求"的地方。
3. **来源三要素缺一不可**：提出人、渠道、提出时间。缺了就拒绝入库，不许填"不详"。
4. **模板五段必须齐**：缺段直接失败，不猜。
5. **只追加**：登记簿永不删除、永不回改。

## 自检（G0 门禁）

```bash
python skills/sk-req-register/validate.py
```

扫描 `inbox/REQ-*.md` 与登记簿对账：没登记的文件、hash 对不上的文件、登记了却找不到的文件、模板缺段的文件，全部报错。

## 失败时怎么办

返回 `{ok: false, errors: [...]}`。文档问题退回需求方补来源；hash 不一致则**停下来问人**——这可能意味着有人改过原件，也可能意味着有人想绕过登记，两种情况都不该由脚本自己决定。
