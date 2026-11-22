# requirements/ —— 一个需求一个目录，角色是它的子目录

B 线从这开始。**需求是顶层，角色是需求的子目录**——不是反过来：

```
requirements/
├── _registry.jsonl                  全局登记簿（跨需求：编号占用、原件 hash）
├── templates/                       模板，不是需求
├── 画像标签需求20261122/             ← 一个需求的总目录，名字只出现一次
│   ├── 反馈者/
│   │   └── REQ-20261122-02.md       原话 + 来源 + sha256
│   ├── 需求分析员/
│   │   └── REQ-20261122-02.md       8 段合同，待确认项为空
│   └── 需求开发员/
│       ├── developer-1/             （轨 A：SQL + design-notes.md + self-check.md）
│       ├── developer-2/             （轨 B：同上，互不可见）
│       ├── 监督者/                   （comparison.md、verdict.md、comparison_report.json、final/）
│       └── journal.jsonl            （追踪者的账本）
└── 渠道GMV日报需求20261122/
    ├── 反馈者/REQ-20261122-01.md
    └── 需求分析员/REQ-20261122-01.md
```

为什么是这个方向：需求是**唯一的主角**，三个角色只是它在不同阶段的样子。
按角色排的话，一个人要回答"这个需求全貌是什么"，得横跨三个顶层目录去拼；
按需求排，一个 `ls` 就看到全部，归档、交接、销毁也都是一个目录的事。

## 三条硬规则

1. **目录即需求身份**：目录名 `<短名>需求<YYYYMMDD>`，例如 `画像标签需求20261122`。编号 `REQ-YYYYMMDD-NN` 写在里面，目录日期必须与编号日期一致。
2. **不许平铺**：任何 `REQ-*.md` 必须落在 `<需求目录>/<角色>/` 下。平铺在 `requirements/` 根下、塞进需求目录根下，`tools/check_layout.py` 和 `register.py` 双双判 FAIL。
3. **run 目录 = 需求目录**：B 线不另建 `runs/<run_id>/`，开发过程就长在 `<需求目录>/需求开发员/` 里。`runs/` 只留给 A 线临时跑。

## 为什么不用"交易域需求"这种名字

名字会变，编号不会。目录里的编号 `REQ-20261122-02` 是唯一标识；目录名前面那截中文只是给人看的。两者对不上会被 `check_layout.py` 与 `register.py` 同时拦下。

## 反馈者：原始需求

| 规则 | 说明 |
|---|---|
| 只增不改 | 改了就没有证据价值。修订 = 另存 `-v2` 文件 |
| 不许删 | 撤销的需求标 `status: withdrawn`，文件留着 |
| 必须写来源 | 提出人、渠道（群/邮件/会议）、时间。写"来源不详"一律不收 |
| 必须算 hash | `register.py` 把 `sha256` 写进登记簿，用于证明"这份原件没被改过" |
| 必须用模板 | [templates/REQ-template.md](templates/REQ-template.md)，缺段 G0 就拦 |

## 登记簿：`requirements/_registry.jsonl`

Append-only，一行一条，**全局一份**。它回答的是跨需求的问题："这个编号有没有被占用""这份原件有没有被改过"——所以它不能塞进某一个需求的目录里。

```bash
# 登记（幂等：重复登记不会写第二行）
python skills/sk-req-register/register.py \
  --path "requirements/渠道GMV日报需求20261122/反馈者/REQ-20261122-01.md" \
  --proposer 张敏 --channel 钉钉-数据需求群 --submitted-at 2026-11-22T10:12

# G0 门禁：对账（未登记 / hash 变了 / 目录不对 / 模板缺段，全部拦）
python skills/sk-req-register/validate.py

# 布局门禁：需求目录结构、角色子目录、开发目录是否齐全
python tools/check_layout.py
```

条目字段：`req_id`、`path`、`requirement_dir`、`sha256`、`proposer`、`channel`、`submitted_at`、`registered_at`、`title`；历史搬迁过的条目还会有 `path_before` 与 `moved_at`——**搬过家要留痕，否则"当初的文件在哪"就说不清了**。

改过原件的文件**不允许重新登记**，必须另存 `-v2`。这是唯一能发现"有人偷偷改证据"的机制。

## 需求分析员：翻译稿

用 [templates/REQ-translation-template.md](templates/REQ-translation-template.md)，8 段缺一不可：

```bash
python skills/sk-req-validate/validate.py \
  --doc "requirements/渠道GMV日报需求20261122/需求分析员/REQ-20261122-01.md"
```

这条命令就是 G1。它拦四类东西：段没写全、待确认项非空、引用了本体里不存在的 id、验收标准不可断言。

翻译稿里**「待确认项」不为空就不许开工**——让开发者去猜口径，等于把返工提前变成必然。

## 流转（都在同一个需求目录里发生）

```
<需求目录>/反馈者/REQ-xxx.md                  原话 + 来源 + sha256
   │  P0 需求入库                              gate G0（+ check_layout）
   ▼
<需求目录>/需求分析员/REQ-xxx.md              8 段合同，待确认项为空
   │  P1 需求翻译                              gate G1（含 HITL：口径确认）
   ▼
<需求目录>/需求开发员/developer-1/  ∥  developer-2/     互不可见
   │  P2 双轨开发                              gate G2
   ▼
<需求目录>/需求开发员/监督者/{comparison.md,verdict.md,final/}
   │  P3 监督比对                              gate G3（含 HITL：方案裁决）
   ▼
P4 质量规则 → P5 血缘调度 → P6 文档交付
```

同一个需求从提出到上线，所有东西都在这一个目录名下；跨需求找东西靠 `_registry.jsonl`。
