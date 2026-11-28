# 知识候选

从**分析师问答**里挖出来的、值得进知识库的东西。自动生成，不手改。

- 谁生成：`python tools/qa_mine.py`（四个机械信号：纠正 / 高频问 / 术语缺口 / 高频 join）
- 谁裁决：人。`python tools/qa_promote.py --list` 看清单
- 转正去向：`knowledge/<目录>/` 或 `ontology_delta` 提案
- 驳回也要显式 `--reject`，不要靠"自然沉底"——沉底的候选三个月后会原样再被问一遍

四类信号的含义与整条链路见 [docs/问答沉淀.md](../docs/问答沉淀.md)。

```bash
python tools/qa_mine.py --week 2026-W48
python tools/qa_promote.py --list
python tools/qa_promote.py --id C-20261128-01 --kind knowledge \
    --dir 04_踩坑 --slug aov-vs-arpu --title "客单价 AOV 与人均消费额 ARPU 不是一回事"
python tools/wiki_impact.py --stamp --note "新增：AOV 与 ARPU 的区分"
```
