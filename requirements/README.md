# requirements/ —— 原始需求与翻译稿

两条泳道里，只有 B 线从这里开始。目录分成两半，因为它们是两种不同性质的东西：

| 目录 | 是什么 | 规则 |
|---|---|---|
| `inbox/` | 原始需求：谁、什么时候、通过什么渠道提的，原样存档 | **只增不改**。要改就新加一个 `-v2` 文件 |
| `normalized/` | 翻译稿：需求翻译者产出的规范化 MD，开发者只读这一份 | 由 `requirement-translator` 生成，带 front matter |

## 为什么必须分开

原始需求是**证据**，翻译稿是**合同**。

混在一起的后果很具体：三个月后有人说"当初不是这么说的"，你翻出来的文件已经被翻译者改过三版，无法判断哪句是客户原话、哪句是翻译者的理解。分开之后，原始文件带 `sha256`，任何争议都能回到原件。

## 命名

```
inbox/REQ-20261122-01.md          # 原始需求
inbox/REQ-20261122-01-v2.md       # 补充/修订，不覆盖原文件
normalized/REQ-20261122-01.md     # 翻译稿，front matter 里引用原始文件与 hash
```

`REQ-<日期>-<序号>`，序号当天递增。不用"交易域需求"这种名字——名字会变，编号不会。

## 入库五条

1. **必须写来源**：提出人、渠道（群/邮件/会议）、时间。写"来源不详"的需求一律不收。
2. **不许改**：改了就没有证据价值。修订 = 新文件。
3. **不许删**：被撤销的需求标记 `status: withdrawn`，文件留着。
4. **必须算 hash**：`sk-req-register` 会算 `sha256` 写进 `_registry.jsonl`，用于事后证明"翻译稿基于哪个版本"。
5. **必须用模板**：见 [templates/REQ-template.md](templates/REQ-template.md)，缺段落在 G0 门禁就拦。

## 登记簿：`inbox/_registry.jsonl`

Append-only，一行一条。它是唯一能回答"这份原件有没有被人改过"的地方：

```bash
# 登记（幂等：重复登记不会写第二行）
python skills/sk-req-register/register.py \
  --path requirements/inbox/REQ-20261122-01.md \
  --proposer 张敏 --channel 钉钉-数据需求群 --submitted-at 2026-11-22T10:12

# G0 门禁：对账（原件 hash 变了、没登记、模板缺段，全部拦）
python skills/sk-req-register/validate.py
```

改过原件的文件**不允许重新登记**——必须另存 `-v2`。这是唯一能发现"有人偷偷改证据"的机制。

## 翻译稿

用 [templates/REQ-translation-template.md](templates/REQ-translation-template.md)，8 段缺一不可：

```
python skills/sk-req-validate/validate.py --doc requirements/normalized/REQ-20261122-01.md
```

这条命令就是 G1。它拦的是四类东西：段没写全、待确认项非空、引用了本体里不存在的 id、验收标准不可断言。


## 流转

```
inbox/REQ-xxx.md
   │  P0 需求入库（登记 + hash）              gate G0
   ▼
normalized/REQ-xxx.md（翻译稿，8 段齐全）
   │  P1 需求翻译                              gate G1（含 HITL：口径确认）
   ▼
两条独立开发轨（P2，互不可见）
   │
   ▼
P3 监督比对 → 合格脚本 + 对比报告 + 裁决书
```

翻译稿里**「待确认项」不为空就不许开工**——这是 G1 最重要的一条。让开发者去猜口径，等于把返工提前变成了必然。
