# 知识库索引

> 给人看的入口。机器检索用 [`index/chunks.jsonl`](index/chunks.jsonl)（id / 路径 / 标题 / 标签 / sha256）。
>
> **规则**：新增一个知识页 → 直接加；**改已有页面的内容（尤其是口径、公式、字段含义）→ 先跑影响分析，再登记变更**：
>
> ```
> python tools/wiki_impact.py --changed                    # 看影响面
> python tools/wiki_impact.py --stamp --note "补了退款回冲说明"   # 更新指纹 + 写进下面这张表
> ```
>
> 没登记的改动 `--check` 会拦住（巡检里也会报）。

## 目录导航

| 层 | 内容 | 入口 |
|---|---|---|
| 规范 | 命名、分层、建模约定 | [`01_规范/`](01_规范/) |
| 方言 | Hive / Spark SQL 写法差异与坑 | [`02_方言/`](02_方言/) |
| 范例 | 从问句到可信 SQL 的完整走查 | [`03_范例/example-gmv-by-channel.md`](03_范例/example-gmv-by-channel.md) |
| 踩坑 | 踩过一次就必须写下来 | [`04_踩坑/hive-partition-duplicate-column.md`](04_踩坑/hive-partition-duplicate-column.md) |
| 历史 | 口径变更的历史原因 | [`05_历史/`](05_历史/) |
| wiki | 常用表 / 词根 / 指标 / 取数路径速查 | [`wiki/README.md`](wiki/README.md) |

## 变更记录

> 只追加。每条写清"变了什么、什么时候、影响了谁"——三个月后回看，这是唯一能解释"为什么当初这么改"的地方。

| 日期 | 文档 | 变了什么 | 影响面 | 谁改的 |
|---|---|---|---|---|
| 2026-11-22 | `wiki/*.md` | 建立知识库：词根、指标、10 张事实表、6 张维表、取数路径 | 无（初建） | 人 |
| 2026-11-28 | `04_踩坑/hive-partition-duplicate-column.md` | 补充「检查落在哪」：check_partition_not_in_columns 的实现位置 + 纯 SQL 模式也生效 + 反例文件 | knowledge/index.md | 人 |
