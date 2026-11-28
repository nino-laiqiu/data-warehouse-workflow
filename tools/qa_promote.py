#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把候选知识转正。

两种去处，都要人做一次判断：

  --kind knowledge  → 生成 knowledge/<目录>/<slug>.md（带证据原文，结论留空等人填）
  --kind ontology   → 生成 ontology_delta 提案（只提案，不改本体；本体只能人改）

工具不替你下结论，它只负责把「证据搬到位、格式对齐、路径正确」。
转正后必须跑：

    python tools/wiki_impact.py --stamp --note "为什么加这条"
    python tools/check_wiki.py && python tools/inspect.py --no-write

用法：
    python tools/qa_promote.py --list
    python tools/qa_promote.py --id C-20261128-01 --kind knowledge --dir 04_踩坑 \
        --slug gmv-vs-order-amt --title "GMV 与订单金额不是一回事"
    python tools/qa_promote.py --id C-20261128-03 --kind ontology --target TAG
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "知识候选"
CST = timezone(timedelta(hours=8))
KIND_DIRS = ["01_规范", "02_方言", "03_范例", "04_踩坑", "05_历史"]


def latest_dir() -> pathlib.Path | None:
    if not OUT_ROOT.exists():
        return None
    dirs = [d for d in OUT_ROOT.iterdir() if d.is_dir() and (d / "candidates.jsonl").exists()]
    return sorted(dirs)[-1] if dirs else None


def load(dir_path: pathlib.Path) -> list[dict]:
    p = dir_path / "candidates.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def save(dir_path: pathlib.Path, cands: list[dict]) -> None:
    p = dir_path / "candidates.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cands) + "\n", encoding="utf-8")


def mark(cands: list[dict], cid: str, status: str, path: str) -> dict | None:
    for c in cands:
        if c["candidate_id"] == cid:
            c["status"] = status
            c["promoted_path"] = path
            return c
    return None


def list_cands(dir_path: pathlib.Path) -> int:
    cands = load(dir_path)
    if not cands:
        print("这一周没有候选")
        return 0
    print(f"{dir_path.relative_to(ROOT)}　共 {len(cands)} 条")
    for c in sorted(cands, key=lambda x: x["candidate_id"]):
        print(f"  {c['candidate_id']:<14} {c['status']:<9} {c['kind']:<10} {c['title']}")
    return 0


def promote_knowledge(c: dict, kind_dir: str, slug: str, title: str, conclusion: str, owner: str) -> pathlib.Path:
    if kind_dir not in KIND_DIRS:
        raise SystemExit(f"--dir 必须是 {KIND_DIRS} 之一")
    target = ROOT / "knowledge" / kind_dir / f"{slug}.md"
    if target.exists():
        raise SystemExit(f"已存在：{target.relative_to(ROOT)}——不要覆盖，换 slug 或直接改原文件")
    today = datetime.now(CST).strftime("%Y-%m-%d")
    rows = "\n".join(f"| `{e['qa_id']}` | {e['note']} |" for e in c["evidence"])
    body = f"""# {title}

> 来源：分析师问答沉淀（{len(c['evidence'])} 条证据，见文末）
> 归集：{today}　状态：**草案**（待 {owner} 复核转正）
> 候选编号：`{c['candidate_id']}`

## 结论

{conclusion or "（待填：一句话说清是什么、怎么算、什么时候不适用）"}

## 为什么值得写

{c['suggestion']}

## 证据（分析师原话）

| qa_id | 现场 |
|---|---|
{rows}
"""
    target.write_text(body, encoding="utf-8")
    return target


def promote_ontology(c: dict, target_name: str, reason: str, out_dir: pathlib.Path) -> pathlib.Path:
    payload = {
        "run_id": f"qa-promote-{datetime.now(CST).strftime('%Y%m%d')}",
        "stage": "P4",
        "payload": {
            "requirement_id": "REQ-20261122-02",
            "proposer": "chronicler",
            "reason": reason or f"问答沉淀发现术语缺口：{c['title']}",
            "changes": [
                {
                    "op": "update",
                    "kind": "object",
                    "target": target_name,
                    "field": "value_domain",
                    "why": f"{c['suggestion']}；证据 {len(c['evidence'])} 条",
                }
            ],
            "impact": "待评估：影响引用该本体的口径、DQ 规则与下游宽表",
        },
    }
    dest = out_dir / "promoted"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{c['candidate_id']}-ontology-delta.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="候选知识转正")
    ap.add_argument("--file", help="指定 candidates.jsonl；默认取最新一周")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--id")
    ap.add_argument("--kind", choices=["knowledge", "ontology"])
    ap.add_argument("--dir", default="04_踩坑", help=f"knowledge 子目录：{KIND_DIRS}")
    ap.add_argument("--slug", help="文件名（不带 .md），小写连字符")
    ap.add_argument("--title")
    ap.add_argument("--conclusion", default="", help="知识结论；留空则写占位符，等人补")
    ap.add_argument("--target", help="ontology 变更目标 id，如 TAG")
    ap.add_argument("--reason", default="")
    ap.add_argument("--owner", default="待定")
    ap.add_argument("--reject", action="store_true", help="标记为 rejected，不生成文件")
    args = ap.parse_args(argv)

    dir_path = pathlib.Path(args.file).parent if args.file else latest_dir()
    if not dir_path:
        print("[FAIL] 没有 知识候选/<周>/candidates.jsonl，先跑 python tools/qa_mine.py")
        return 1

    cands = load(dir_path)
    if args.list or not args.id:
        return list_cands(dir_path)

    c = next((x for x in cands if x["candidate_id"] == args.id), None)
    if not c:
        print(f"[FAIL] 没有候选 {args.id}（看 --list）")
        return 1
    if c["status"] != "pending":
        print(f"[FAIL] {args.id} 已经 {c['status']}：{c.get('promoted_path')}")
        return 1

    if args.reject:
        mark(cands, args.id, "rejected", "")
        save(dir_path, cands)
        print(f"已驳回 {args.id}")
        return 0

    if not args.kind:
        raise SystemExit("转正需要 --kind knowledge|ontology")

    if args.kind == "knowledge":
        if not args.slug or not args.title:
            raise SystemExit("knowledge 转正需要 --slug 与 --title")
        path = promote_knowledge(c, args.dir, args.slug, args.title, args.conclusion, args.owner)
        mark(cands, args.id, "promoted", str(path.relative_to(ROOT)))
        save(dir_path, cands)
        print(f"{args.id} → {path.relative_to(ROOT)}")
        print("接着跑：")
        print(f'  python tools/wiki_impact.py --stamp --note "{args.title}"')
        print("  python tools/check_wiki.py && python tools/inspect.py --no-write")
        return 0

    if not args.target:
        raise SystemExit("ontology 转正需要 --target，如 TAG")
    path = promote_ontology(c, args.target, args.reason, dir_path)
    mark(cands, args.id, "promoted", str(path.relative_to(ROOT)))
    save(dir_path, cands)
    print(f"{args.id} → {path.relative_to(ROOT)}（提案，不是变更）")
    print("下一步：人工评审后改 ontology/，再跑 python ontology/schema/validate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
