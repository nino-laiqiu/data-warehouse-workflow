#!/usr/bin/env python3
"""追踪者的记账器：往 journal.jsonl 里追加 / 校验 / 查待办。

六类事件（详细口径见 docs/追踪.md）：
  conversation  问答记录：人问了什么、结论是什么（不存逐字原文）
  query         查询 SQL：查了什么、为什么查、查出什么（SQL 全文 + sha256）
  artifact      修改事件：哪个文件、改前改后哈希、改了什么
  progress      进展：走到哪个阶段、started/done/blocked、下一步
  todo          待办：谁办、状态、关单时追加同 todo_id 的 done/dropped
  gate          门禁：G0-G6 / GA1-GA3 的判定与理由

用法：
  python tools/journal.py append --req 画像标签需求20261122 --type progress \
      --actor chronicler --stage P5 --state blocked --summary "卡在 H3 放行" --next "等人签字"
  python tools/journal.py append --req 画像标签需求20261122 --type query \
      --actor requirement-translator --sql-file .tmp/q.sql --purpose "核对 GMV" --result "1.2 亿"
  python tools/journal.py append --req ... --type todo --text "签 H3" --owner nino --status open
  python tools/journal.py append --req ... --type todo --todo-id T-20261128-01 --text "签 H3" --owner nino --status done
  python tools/journal.py check --req 画像标签需求20261122
  python tools/journal.py todos --req 画像标签需求20261122 [--all]
  python tools/journal.py show --req ... [--type query] [--tail 5]

退出码：0 正常；1 有错误（check 失败、追加的条目不合规）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ_ROOT = ROOT / "requirements"
TZ = timezone(timedelta(hours=8))
TYPES = ["conversation", "query", "artifact", "progress", "todo", "gate"]

# 每类的必填字段（schema 只管结构，这里管"这一类必须写什么"）
REQUIRED_BY_TYPE = {
    "conversation": ["summary"],
    "query": ["sql", "purpose", "result_summary"],
    "artifact": ["path", "hash_after"],
    "progress": ["stage", "state", "summary"],
    "todo": ["text", "owner", "status"],
    "gate": ["gate", "result"],
}


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def req_dir(name: str) -> Path:
    p = REQ_ROOT / name
    if not p.is_dir():
        raise SystemExit(f"找不到需求目录：requirements/{name}")
    return p


def journal_of(req: str) -> Path:
    d = req_dir(req) / "需求开发员"
    d.mkdir(parents=True, exist_ok=True)
    return d / "journal.jsonl"


def run_id_of(req: str) -> str:
    fb = req_dir(req) / "反馈者"
    for f in sorted(fb.glob("REQ-*.md")) if fb.exists() else []:
        stem = f.stem  # REQ-20261122-02
        parts = stem.split("-")
        if len(parts) == 3:
            return f"{parts[1]}-{parts[2]}"
    return req


def read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{i} 不是合法 JSON：{e}")
    return out


def validate_entry(e: dict) -> list[str]:
    errs: list[str] = []
    for k in ("ts", "run_id", "type", "actor"):
        if not e.get(k):
            errs.append(f"缺必填字段 {k}")
    t = e.get("type")
    if t not in TYPES:
        errs.append(f"type={t} 不在 {TYPES}")
        return errs
    for k in REQUIRED_BY_TYPE[t]:
        v = e.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            errs.append(f"{t} 类缺必填字段 {k}")
    if t == "progress" and e.get("state") == "blocked" and not e.get("next"):
        errs.append("progress=blocked 时必须写 next（卡在哪、等谁）")
    if t == "gate" and e.get("result") in ("fail", "waived") and not e.get("reason"):
        errs.append("gate= fail/waived 时必须写 reason（机器可读的失败原因）")
    if t == "todo":
        if e.get("status") == "open" and not e.get("todo_id"):
            errs.append("todo 关单/追踪需要 todo_id（T-YYYYMMDD-NN）")
        if e.get("status") in ("done", "dropped") and not e.get("todo_id"):
            errs.append("todo 关单必须带 todo_id 指向原条目")
    return errs


def cmd_append(a: argparse.Namespace) -> int:
    e: dict = {
        "ts": now(),
        "run_id": run_id_of(a.req),
        "type": a.type,
        "actor": a.actor,
    }
    if a.summary: e["summary"] = a.summary
    if a.question: e["question"] = a.question
    if a.answer: e["answer"] = a.answer
    if a.purpose: e["purpose"] = a.purpose
    if a.result: e["result_summary"] = a.result
    if a.engine: e["engine"] = a.engine
    if a.rowcount is not None: e["rowcount"] = a.rowcount
    if a.duration_ms is not None: e["duration_ms"] = a.duration_ms
    if a.path: e["path"] = a.path
    if a.hash_before is not None: e["hash_before"] = a.hash_before
    if a.hash_after: e["hash_after"] = a.hash_after
    if a.diff: e["diff_summary"] = a.diff
    if a.stage: e["stage"] = a.stage
    if a.state: e["state"] = a.state
    if a.next: e["next"] = a.next
    if a.text: e["text"] = a.text
    if a.owner: e["owner"] = a.owner
    if a.status: e["status"] = a.status
    if a.due: e["due"] = a.due
    if a.gate: e["gate"] = a.gate
    if a.gate_result: e["result"] = a.gate_result
    if a.reason: e["reason"] = a.reason
    if a.todo_id: e["todo_id"] = a.todo_id
    if a.refs: e["refs"] = a.refs

    if a.sql_file:
        p = Path(a.sql_file)
        if not p.is_absolute():
            p = ROOT / p
        sql = p.read_text(encoding="utf-8")
        e["sql"] = sql
        e["sql_hash"] = sha(sql)
    elif a.type == "query":
        raise SystemExit("query 必须给 --sql-file（把 SQL 存文件，别内联进命令行）")

    errs = validate_entry(e)
    if errs:
        for x in errs:
            print(f"[FAIL] {x}", file=sys.stderr)
        return 1

    jp = journal_of(a.req)
    with jp.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"已追加 {e['type']} 事件 → {jp.relative_to(ROOT)}")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    jp = journal_of(a.req)
    entries = read_entries(jp)
    errs = []
    for i, e in enumerate(entries, 1):
        for x in validate_entry(e):
            errs.append(f"第 {i} 行：{x}")
    for x in errs:
        print(f"[FAIL] {x}")
    if not errs:
        print(f"PASS：{len(entries)} 条事件全部合法（{jp.relative_to(ROOT)}）")
    return 1 if errs else 0


def open_todos(entries: list[dict]) -> list[dict]:
    state: dict[str, dict] = {}
    for e in entries:
        if e.get("type") != "todo":
            continue
        tid = e.get("todo_id") or f"anon-{e.get('ts')}"
        if e.get("status") == "open":
            state[tid] = e
        else:
            state.pop(tid, None)
    return list(state.values())


def cmd_todos(a: argparse.Namespace) -> int:
    jp = journal_of(a.req)
    entries = read_entries(jp)
    if a.all:
        for e in entries:
            if e.get("type") == "todo":
                print(f"{e.get('todo_id', '-'):<16} {e.get('status', '-'):<8} {e.get('owner', '-'):<24} {e.get('text', '')}")
        return 0
    todos = open_todos(entries)
    if not todos:
        print("没有未关闭的待办。")
        return 0
    print(f"{len(todos)} 条未关闭待办：")
    for e in todos:
        due = f"（due {e['due']}）" if e.get("due") else ""
        print(f"  {e.get('todo_id', '-'):<16} {e.get('owner', '-'):<24} {e.get('text', '')}{due}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    entries = read_entries(journal_of(a.req))
    if a.type:
        entries = [e for e in entries if e.get("type") == a.type]
    for e in entries[-a.tail:]:
        head = f"{e.get('ts')} {e.get('type'):<12} {e.get('actor', '-'):<24}"
        body = (e.get("summary") or e.get("text") or e.get("path")
                or e.get("purpose") or e.get("gate") or "")
        print(f"{head} {body}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="追踪者的记账器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("append", help="追加一条事件")
    p.add_argument("--req", required=True)
    p.add_argument("--type", required=True, choices=TYPES)
    p.add_argument("--actor", required=True)
    p.add_argument("--summary"); p.add_argument("--question"); p.add_argument("--answer")
    p.add_argument("--sql-file"); p.add_argument("--purpose"); p.add_argument("--result")
    p.add_argument("--engine", choices=["hive", "spark", "presto", "other"])
    p.add_argument("--rowcount", type=int); p.add_argument("--duration-ms", dest="duration_ms", type=int)
    p.add_argument("--path"); p.add_argument("--hash-before", dest="hash_before")
    p.add_argument("--hash-after", dest="hash_after"); p.add_argument("--diff")
    p.add_argument("--stage"); p.add_argument("--state", choices=["started", "done", "blocked"])
    p.add_argument("--next"); p.add_argument("--text"); p.add_argument("--owner")
    p.add_argument("--status", choices=["open", "done", "dropped"]); p.add_argument("--due")
    p.add_argument("--gate"); p.add_argument("--gate-result", dest="gate_result", choices=["pass", "fail", "waived"])
    p.add_argument("--reason"); p.add_argument("--todo-id", dest="todo_id")
    p.add_argument("--refs", nargs="*")
    p.set_defaults(func=cmd_append)

    p = sub.add_parser("check", help="校验整个 journal")
    p.add_argument("--req", required=True)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("todos", help="未关闭的待办")
    p.add_argument("--req", required=True)
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_todos)

    p = sub.add_parser("show", help="按时间看事件")
    p.add_argument("--req", required=True)
    p.add_argument("--type", choices=TYPES)
    p.add_argument("--tail", type=int, default=10)
    p.set_defaults(func=cmd_show)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
