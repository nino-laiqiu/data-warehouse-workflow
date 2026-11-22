#!/usr/bin/env python3
"""G5 门禁：血缘完整、调度不成环、回滚可执行。

    python tools/check_lineage.py requirements/画像标签需求20261122/需求开发员/血缘/lineage.json

G5 的三条检查落成代码：
  1. 血缘图完整，无孤立表 —— 没有上游的节点必须在 sources 里；没有下游的节点必须是 ads 层或 sinks
  2. 依赖已声明且不成环 —— 只看 schedule 边做拓扑排序，data 边不管（数据可以是双向引用）
  3. 回滚方案已写 —— strategy/retention/steps 齐全，且步骤里要出现"重跑"和"质检"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_contracts import validate_against  # noqa: E402


def find_cycle(nodes: list[str], edges: list[tuple[str, str]]) -> list[str] | None:
    """返回环上的一条路径；无环返回 None。"""
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    stack: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return stack[stack.index(v):] + [v]
            if color.get(v, WHITE) == WHITE:
                found = dfs(v)
                if found:
                    return found
        stack.pop()
        color[u] = BLACK
        return None

    for n in list(adj):
        if color[n] == WHITE:
            found = dfs(n)
            if found:
                return found
    return None


def check(doc_path: Path) -> list[str]:
    problems: list[str] = []
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"JSON 解析失败: {exc}"]

    problems += validate_against(doc, Path("contracts/lineage.schema.json"))
    if problems:
        return problems

    p = doc["payload"]
    nodes = p["nodes"]
    edges = p["edges"]
    ids = [n["id"] for n in nodes]
    by_id = {n["id"]: n for n in nodes}
    sources = set(p.get("sources", []))
    sinks = set(p.get("sinks", []))

    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        problems.append(f"节点 id 重复: {sorted(dup)}")

    for e in edges:
        for end in (e["from"], e["to"]):
            if end not in by_id:
                problems.append(f"边 {e['from']} -> {e['to']} 引用了不存在的节点 {end!r}")
        if e["from"] == e["to"]:
            problems.append(f"自环: {e['from']}")

    out_deg = {i: 0 for i in ids}
    in_deg = {i: 0 for i in ids}
    for e in edges:
        if e["from"] in out_deg:
            out_deg[e["from"]] += 1
        if e["to"] in in_deg:
            in_deg[e["to"]] += 1

    for n in nodes:
        if in_deg[n["id"]] == 0 and n["id"] not in sources:
            problems.append(f"孤立表：{n['id']} 没有任何上游（若为外部源表请加进 sources）")
        if out_deg[n["id"]] == 0:
            if n["layer"] != "ads" and n["id"] not in sinks:
                problems.append(f"断链：{n['id']} 没有任何下游，也没进 sinks")

    sched = [(e["from"], e["to"]) for e in edges if e["type"] == "schedule"]
    cycle = find_cycle(ids, sched)
    if cycle:
        problems.append("调度依赖成环: " + " -> ".join(cycle))

    task_ids = {n["id"] for n in nodes if n["type"] == "task"}
    for t in task_ids:
        if not any(a == t or b == t for a, b in sched):
            problems.append(f"任务 {t} 没有任何调度依赖（没进 schedule 边）")

    rb = p["rollback"]
    text = " ".join(rb["steps"])
    if "重跑" not in text:
        problems.append("回滚步骤里没有『重跑』，等于没有恢复手段")
    if "质检" not in text and "校验" not in text:
        problems.append("回滚步骤里没有『质检』，恢复后无法确认是否真的恢复")

    return problems


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    path = Path(args[0])
    problems = check(path)
    if as_json:
        print(json.dumps({"file": str(path), "ok": not problems, "errors": problems},
                         ensure_ascii=False, indent=2))
    else:
        doc = json.loads(path.read_text(encoding="utf-8"))
        p = doc["payload"]
        tbl = sum(1 for n in p["nodes"] if n["type"] == "table")
        print(f"节点 {len(p['nodes'])} 个（表 {tbl} / 任务 {len(p['nodes']) - tbl}），"
              f"边 {len(p['edges'])} 条，DAG {p['schedule']['dag_id']} @ {p['schedule']['cron']}")
        for x in problems:
            print(f"  ✗ {x}")
        print("PASS" if not problems else f"FAIL（{len(problems)} 处）")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
