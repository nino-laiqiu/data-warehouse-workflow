#!/usr/bin/env python
"""校验 flow/pipeline.yaml 的派活顺序：谁必须等谁、谁允许并行。

为什么需要这个：文档里"P2 双轨 → P3 裁决"是段落顺序，机器读不出来。
一旦编排器（或人）按文档顺序脑补，就可能把监督者和两个开发者一起放出去——
监督者拿到的是两份半成品，比对结论没有意义。所以顺序必须写进结构，并且被校验。

检查六件事：
1. 每个 stage 必须显式写 `depends_on:`（可以为 `[]`），不许省略。
2. depends_on 里的 stage 必须存在，不许自依赖。
3. 依赖必须指向文档顺序更靠前的 stage（保证无环，且执行序 = 文件顺序）。
4. 只有 `parallel_tracks` 声明的 stage 允许并行，且并行成员必须是不同角色。
5. 监督者（agent 含 supervisor）不得与任何 stage 并行，必须依赖全部开发者 stage。
6. 门禁 id 必须在 flow/gates.yaml 里出现过。

用法：
    python tools/check_pipeline.py
    python tools/check_pipeline.py --json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "flow" / "pipeline.yaml"
GATES = ROOT / "flow" / "gates.yaml"

STAGE_RE = re.compile(r"^\s*-\s+id:\s*([AP]\d+)\s*$")
KV_RE = re.compile(r"^\s+([a-z_]+):\s*(.*?)\s*$")


def strip_comment(line: str) -> str:
    # 行内注释：管道里没有需要保留的 #，直接按 # 截断
    return line.split("#", 1)[0].rstrip()


def parse_list(value: str) -> list[str]:
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [x.strip().strip("'\"") for x in v.split(",") if x.strip().strip("'\"")]


def parse_pipeline() -> list[dict]:
    stages: list[dict] = []
    current: dict | None = None
    for raw in PIPELINE.read_text(encoding="utf-8").splitlines():
        line = strip_comment(raw)
        if not line.strip():
            continue
        m = STAGE_RE.match(line)
        if m:
            current = {"id": m.group(1), "keys": set()}
            stages.append(current)
            continue
        m = KV_RE.match(line)
        if m and current is not None:
            key, val = m.group(1), m.group(2)
            current["keys"].add(key)
            current[key] = val
            continue
    return stages


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    stages = parse_pipeline()
    errs: list[str] = []
    warns: list[str] = []

    order = {s["id"]: i for i, s in enumerate(stages)}
    gates_text = GATES.read_text(encoding="utf-8")

    if not stages:
        errs.append("pipeline.yaml 里没解析出任何 stage")
    if len(order) != len(stages):
        errs.append("stage id 有重复")

    by_id = {s["id"]: s for s in stages}

    for s in stages:
        sid = s["id"]
        if "depends_on" not in s:
            errs.append(f"{sid}: 缺 depends_on（没有前置就写 []）")
            continue
        deps = parse_list(s.get("depends_on", ""))
        for d in deps:
            if d not in by_id:
                errs.append(f"{sid}: depends_on 指向不存在的 stage {d}")
                continue
            if d == sid:
                errs.append(f"{sid}: 依赖了自己")
                continue
            if order[d] >= order[sid]:
                errs.append(f"{sid}: 依赖 {d} 排在自己后面（顺序有环或写反了）")

        gate = s.get("gate", "")
        if gate and gate not in ("无", "—") and gate not in gates_text:
            errs.append(f"{sid}: gate {gate} 在 flow/gates.yaml 里找不到")

    # 并行：只允许 parallel_tracks 声明的 stage
    for s in stages:
        tracks = parse_list(s.get("parallel_tracks", ""))
        if not tracks:
            continue
        if len(tracks) < 2:
            errs.append(f"{s['id']}: parallel_tracks 少于两个，不构成并行")
        if len(set(tracks)) != len(tracks):
            errs.append(f"{s['id']}: parallel_tracks 里有重复角色")
        if any("supervisor" in t for t in tracks):
            errs.append(f"{s['id']}: 监督者不能出现在并行轨道里")

    # 监督者：串行，且必须依赖"双轨并行"所在的那个 stage（不是所有含开发者的 stage——P5 是裁决后的落地）
    parallel_owner = {s["id"] for s in stages if parse_list(s.get("parallel_tracks", ""))}
    parallel_stages = sorted(parallel_owner)
    for s in stages:
        if "supervisor" not in s.get("agent", ""):
            continue
        sid = s["id"]
        if sid in parallel_owner:
            errs.append(f"{sid}: 监督者所在 stage 声明了并行")
        deps = set(parse_list(s.get("depends_on", "")))
        if not parallel_owner:
            errs.append(f"{sid}: 找不到声明 parallel_tracks 的 stage，无法确认监督者等谁")
        for po in sorted(parallel_owner):
            if po not in deps:
                errs.append(f"{sid}: 监督者必须依赖双轨 stage {po}，当前 depends_on={sorted(deps) or '[]'}")
        # 监督者不得反过来被并行 stage 依赖（那就成了循环）
        for other in stages:
            if other["id"] != sid and sid in parse_list(other.get("depends_on", "")) and other["id"] in deps:
                errs.append(f"{sid}: 与 {other['id']} 互相依赖")

    # 并行 stage 之间不得互相依赖
    for s in stages:
        tracks = parse_list(s.get("parallel_tracks", ""))
        if len(tracks) >= 2:
            deps = parse_list(s.get("depends_on", ""))
            if any(d == s["id"] for d in deps):
                errs.append(f"{s['id']}: 并行 stage 依赖了自己")

    lines = [f"stage {len(stages)} 个：" + " → ".join(s["id"] for s in stages)]
    for s in stages:
        deps = parse_list(s.get("depends_on", ""))
        tracks = parse_list(s.get("parallel_tracks", ""))
        note = ""
        if tracks:
            note = "  ∥ " + " / ".join(tracks)
        elif "supervisor" in s.get("agent", ""):
            note = "  （串行：等全部开发者交付后开始）"
        lines.append(f"  {s['id']:<3} depends_on={deps or '[]'}{note}")

    if as_json:
        print(json.dumps({"stages": len(stages), "errors": errs, "warnings": warns,
                          "order": [s["id"] for s in stages]}, ensure_ascii=False, indent=2))
    else:
        for line in lines:
            print(line)
        for w in warns:
            print(f"[WARN] {w}")
        for e in errs:
            print(f"[FAIL] {e}")
        if not errs:
            print(f"[OK  ] 派活顺序合法（{len(stages)} 个 stage，"
                  f"并行组 {len(parallel_stages)} 个：{', '.join(parallel_stages) or '无'}）")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
