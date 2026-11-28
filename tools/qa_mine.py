#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从问答沉淀里挖候选知识。

不猜语义，只认四种机械信号——它们的共同点是"分析师已经用行为告诉我们这里有问题"：

  1. correction  下一轮出现了纠正（不对/应该是/口径是…）—— 上次回答错了或没讲清
  2. faq         同一个问题被 ≥3 个不同会话问过 —— 该写进 wiki
  3. term        问了「X 是什么 / X 怎么算」而知识库和本体里都没有 X —— 术语缺口
  4. join        同一组表被反复一起查 —— 该补一条取数路径

产出 `知识候选/<YYYY-Www>/candidates.{jsonl,md}`，只做提案，不碰 knowledge/ 与 ontology/。
转正用 tools/qa_promote.py。

用法：
    python tools/qa_mine.py
    python tools/qa_mine.py --week 2026-W48 --min-repeat 3
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from itertools import combinations

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import qa_store  # noqa: E402

OUT_ROOT = ROOT / "知识候选"
CST = timezone(timedelta(hours=8))

CORRECTION_WORDS = ["不对", "不是", "错了", "应该是", "不准确", "答错", "重新算", "口径是", "你搞错"]
TERM_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9]{1,11})(?:是什么|怎么算|怎么定义|指什么|的口径)")
SQL_TABLE_RE = re.compile(r"(?:from|join)\s+([a-z_][a-z0-9_]*)", re.I)
NOISE = {"这个", "那个", "我们", "他们", "怎么", "什么", "为什么", "数据", "指标", "口径"}


def norm_question(q: str) -> str:
    return re.sub(r"[\s，。？?！!、,.]", "", q).lower()


def load_corpus() -> str:
    """知识库 + 本体的全文，用来判断某个术语是不是已经写过了。"""
    parts: list[str] = []
    for base in ("knowledge", "ontology"):
        for p in (ROOT / base).rglob("*"):
            if p.suffix.lower() in {".md", ".yaml", ".yml"} and p.is_file():
                parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def load_turns(db: pathlib.Path) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM qa_turn ORDER BY session_id, turn_no")]
    conn.close()
    for r in rows:
        r["tables"] = json.loads(r["tables"]) if r["tables"] else []
    return rows


def detect_corrections(turns: list[dict]) -> list[dict]:
    out: list[dict] = []
    by_session: dict[str, list[dict]] = {}
    for t in turns:
        by_session.setdefault(t["session_id"], []).append(t)
    for sid, seq in by_session.items():
        seq.sort(key=lambda x: x["turn_no"])
        for prev, cur in zip(seq, seq[1:]):
            if any(w in cur["question"] for w in CORRECTION_WORDS):
                out.append({
                    "kind": "correction",
                    "key": f"correction:{norm_question(cur['question'])[:40]}",
                    "title": f"纠正：{cur['question'][:40]}",
                    "evidence": [
                        {"qa_id": prev["qa_id"], "note": f"上一轮问：{prev['question'][:60]}"},
                        {"qa_id": cur["qa_id"], "note": f"被纠正：{cur['question'][:60]}"},
                    ],
                    "suggestion": "把上一轮的错误口径写进 04_踩坑，或在 knowledge 里补正例；如果错在本体口径，提 ontology_delta",
                })
    return out


def detect_faq(turns: list[dict], min_repeat: int) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for t in turns:
        groups.setdefault(norm_question(t["question"]), []).append(t)
    out: list[dict] = []
    for key, seq in groups.items():
        sessions = {t["session_id"] for t in seq}
        if len(sessions) >= min_repeat:
            out.append({
                "kind": "faq",
                "key": f"faq:{key[:40]}",
                "title": f"高频问：{seq[0]['question'][:40]}",
                "evidence": [{"qa_id": t["qa_id"], "note": f"{t['session_id']} 问：{t['question'][:60]}"} for t in seq[:5]],
                "suggestion": "写进 wiki 的取数路径/度量页，并在指标页加一条「常见问法」",
            })
    return out


def detect_terms(turns: list[dict], corpus: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for t in turns:
        for m in TERM_RE.finditer(t["question"]):
            term = m.group(1)
            if term in NOISE or term in seen or len(term) < 2:
                continue
            if term in corpus:
                continue
            seen.add(term)
            out.append({
                "kind": "term",
                "key": f"term:{term}",
                "title": f"术语缺口：{term}",
                "evidence": [{"qa_id": t["qa_id"], "note": t["question"][:80]}],
                "suggestion": f"在知识库或本体里补「{term}」的定义与口径；补完再加问答里的真实叫法",
            })
    return out


def detect_joins(turns: list[dict], min_exec: int) -> list[dict]:
    counter: dict[tuple[str, str], list[str]] = {}
    for t in turns:
        tabs = t["tables"] or sorted({m.group(1).lower() for m in SQL_TABLE_RE.finditer(t["sql_text"] or "")})
        tabs = sorted({x for x in tabs if x not in {"select"}})
        for a, b in combinations(tabs, 2):
            counter.setdefault((a, b), []).append(t["qa_id"])
    out: list[dict] = []
    for (a, b), ids in counter.items():
        if len(ids) >= min_exec:
            out.append({
                "kind": "join",
                "key": f"join:{a}+{b}",
                "title": f"高频 join：{a} × {b}",
                "evidence": [{"qa_id": i, "note": f"{a} join {b}"} for i in ids[:5]],
                "suggestion": "在 03_事实表.md 或 05_取数路径.md 里补一条这两个表怎么关联、按什么键、要不要去重",
            })
    return out


def merge(existing: list[dict], found: list[dict], today: str) -> list[dict]:
    """同一 key 复用旧编号与状态，新候选按类型顺序编号。"""
    by_key = {c["key"]: c for c in existing}
    merged: list[dict] = []
    for f in found:
        old = by_key.pop(f["key"], None)
        if old:
            old["evidence"] = f["evidence"]
            old["hit_count"] = len(f["evidence"])
            old["title"] = f["title"]
            merged.append(old)
        else:
            f["candidate_id"] = ""
            f["status"] = "pending"
            f["promoted_path"] = ""
            f["created_at"] = today
            f["hit_count"] = len(f["evidence"])
            merged.append(f)
    merged.extend(by_key.values())  # 这周没再出现的老候选保留，状态不动
    n = 0
    for c in merged:
        if not c.get("candidate_id"):
            n += 1
            c["candidate_id"] = f"C-{today}-{n:02d}"
    return merged


def write_md(cands: list[dict], path: pathlib.Path) -> None:
    lines = ["# 知识候选（问答挖掘）", "",
             "> 自动生成，勿手改。转正：`python tools/qa_promote.py --id C-... --kind knowledge ...`", ""]
    kinds = {"correction": "🟥 纠正", "faq": "🟦 高频", "term": "🟨 术语", "join": "🟩 关联"}
    for c in sorted(cands, key=lambda x: x["candidate_id"]):
        lines.append(f"## {c['candidate_id']} {kinds.get(c['kind'], c['kind'])}　{c['title']}")
        lines.append("")
        lines.append(f"- 命中：{c['hit_count']} 次　状态：**{c['status']}**")
        lines.append(f"- 建议：{c['suggestion']}")
        lines.append("- 证据：")
        for e in c["evidence"]:
            lines.append(f"  - `{e['qa_id']}` {e['note']}")
        if c.get("promoted_path"):
            lines.append(f"- 已转正到：`{c['promoted_path']}`")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="从问答里挖候选知识")
    ap.add_argument("--week", help="输出目录，如 2026-W48；默认本周")
    ap.add_argument("--min-repeat", type=int, default=3, help="同问跨会话命中阈值")
    ap.add_argument("--min-join", type=int, default=3, help="同表组合命中阈值")
    args = ap.parse_args(argv)

    if not qa_store.DB_PATH.exists():
        print(f"[FAIL] 没有问答库：{qa_store.DB_PATH}，先跑 init + ingest")
        return 1

    now = datetime.now(CST)
    week = args.week or f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    out_dir = OUT_ROOT / week
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "candidates.jsonl"

    existing: list[dict] = []
    if jsonl.exists():
        existing = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]

    turns = load_turns(qa_store.DB_PATH)
    if not turns:
        print("[FAIL] 问答库是空的")
        return 1

    corpus = load_corpus()
    found = (
        detect_corrections(turns)
        + detect_faq(turns, args.min_repeat)
        + detect_terms(turns, corpus)
        + detect_joins(turns, args.min_join)
    )
    cands = merge(existing, found, now.strftime("%Y%m%d"))

    jsonl.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cands) + "\n", encoding="utf-8")
    write_md(cands, out_dir / "candidates.md")

    pending = sum(1 for c in cands if c["status"] == "pending")
    print(f"扫了 {len(turns)} 轮问答 → 候选 {len(cands)} 条（待审 {pending}）")
    for k in ("correction", "faq", "term", "join"):
        n = sum(1 for c in cands if c["kind"] == k)
        if n:
            print(f"  {k:<10} {n}")
    print(f"输出：{out_dir.relative_to(ROOT)}/candidates.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
