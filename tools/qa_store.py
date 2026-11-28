#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""问答沉淀：SQLite 本地镜像 + MySQL 导出。

分析师每问一次，就把「问题 / 回答 / SQL / 反馈」落一行。这是知识库最有价值的原料：
真实问法（业务术语到底怎么被叫出来）、真实追问（哪里没讲清楚）、真实纠错（口径哪里错了）。

生产落 MySQL（db/schema_mysql.sql），本地用 SQLite 镜像跑通同一条链路，
换存储只需要改 QA_DB 或换掉 connect() 里的驱动，其余代码不动。

用法：
    python tools/qa_store.py init
    python tools/qa_store.py ingest --file data/qa/sample.jsonl
    python tools/qa_store.py stats
    python tools/qa_store.py recent --n 5
    python tools/qa_store.py export-sql --out db/qa_seed.sql
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_contracts as vc  # noqa: E402

SCHEMA = ROOT / "contracts" / "qa_record.schema.json"
DB_PATH = pathlib.Path(os.environ.get("QA_DB") or (ROOT / ".data" / "qa.db"))
CST = timezone(timedelta(hours=8))

DDL = [
    """CREATE TABLE IF NOT EXISTS qa_session (
        session_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        user_hash  TEXT,
        channel    TEXT,
        turn_cnt   INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS qa_turn (
        qa_id      TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_no    INTEGER NOT NULL,
        asked_at   TEXT NOT NULL,
        question   TEXT NOT NULL,
        answer     TEXT NOT NULL,
        sql_text   TEXT,
        sql_hash   TEXT,
        intent     TEXT,
        tables     TEXT,
        feedback   INTEGER NOT NULL DEFAULT 0,
        feedback_note TEXT,
        model      TEXT,
        latency_ms INTEGER,
        ingested_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_turn_session ON qa_turn(session_id, turn_no)",
    "CREATE INDEX IF NOT EXISTS idx_turn_asked ON qa_turn(asked_at)",
]


def now_iso() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    conn = connect()
    with conn:
        for stmt in DDL:
            conn.execute(stmt)
    conn.close()
    print(f"已初始化 {DB_PATH}")


def load_schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def read_jsonl(path: pathlib.Path) -> list[dict]:
    out: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{i} 不是合法 JSON：{e}")
    return out


def ingest(path: pathlib.Path, dry: bool) -> int:
    schema = load_schema()
    recs = read_jsonl(path)
    conn = None if dry else connect()
    added = skipped = 0
    errors: list[str] = []

    for rec in recs:
        qa_id = str(rec.get("qa_id", "?"))
        errs = vc.validate_against(rec, SCHEMA)
        if errs:
            errors.extend(f"{qa_id}: {e}" for e in errs)
            continue
        if dry:
            added += 1
            continue

        old = conn.execute("SELECT question, answer, sql_hash FROM qa_turn WHERE qa_id=?", (qa_id,)).fetchone()
        if old is not None:
            same = old["question"] == rec["question"] and old["answer"] == rec["answer"] \
                and (old["sql_hash"] or None) == (rec.get("sql_hash") or None)
            if same:
                skipped += 1
                continue
            errors.append(f"{qa_id}: 已存在且内容不同——问答记录只追加，不能改。请用新的 qa_id")
            continue

        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO qa_session (session_id, started_at, user_hash, channel)
                   VALUES (?,?,?,?)""",
                (rec["session_id"], rec["ts"], rec.get("user_hash"), rec.get("channel")),
            )
            conn.execute(
                """INSERT INTO qa_turn
                   (qa_id, session_id, turn_no, asked_at, question, answer, sql_text, sql_hash,
                    intent, tables, feedback, feedback_note, model, latency_ms, ingested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    qa_id, rec["session_id"], rec["turn_no"], rec["ts"], rec["question"], rec["answer"],
                    rec.get("sql_text"), rec.get("sql_hash"), rec.get("intent"),
                    json.dumps(rec.get("tables") or [], ensure_ascii=False) if rec.get("tables") else None,
                    rec.get("feedback", 0), rec.get("feedback_note"), rec.get("model"),
                    rec.get("latency_ms"), now_iso(),
                ),
            )
            conn.execute(
                """UPDATE qa_session SET turn_cnt =
                   (SELECT COUNT(1) FROM qa_turn WHERE session_id = ?) WHERE session_id = ?""",
                (rec["session_id"], rec["session_id"]),
            )
        added += 1

    if conn is not None:
        conn.close()

    print(f"读入 {len(recs)} 条：新增 {added}、跳过 {skipped}、错误 {len(errors)}")
    for e in errors:
        print(f"  [FAIL] {e}")
    return 1 if errors else 0


def stats() -> int:
    conn = connect()
    t = conn.execute("SELECT COUNT(1) c FROM qa_turn").fetchone()["c"]
    s = conn.execute("SELECT COUNT(1) c FROM qa_session").fetchone()["c"]
    print(f"问答库 {DB_PATH}")
    print(f"  会话 {s} 个，轮次 {t} 条")
    if not t:
        conn.close()
        return 0

    print("  反馈分布：", end="")
    for r in conn.execute("SELECT feedback, COUNT(1) c FROM qa_turn GROUP BY feedback"):
        print(f"{ {1: '有用', -1: '无用', 0: '未评'}.get(r['feedback'], r['feedback'])} {r['c']}", end="  ")
    print()

    rows = conn.execute(
        "SELECT tables, COUNT(1) c FROM qa_turn WHERE tables IS NOT NULL AND tables<>'[]' GROUP BY tables ORDER BY c DESC LIMIT 5"
    ).fetchall()
    if rows:
        print("  最常查的表组合：")
        for r in rows:
            print(f"    {r['c']:>3}× {', '.join(json.loads(r['tables']))}")

    same = conn.execute(
        """SELECT COUNT(1) c FROM (
               SELECT session_id, COUNT(1) n FROM qa_turn GROUP BY session_id HAVING n > 1)"""
    ).fetchone()["c"]
    print(f"  有多轮追问的会话：{same} 个（追问越多，说明第一版回答越不够用）")
    conn.close()
    return 0


def recent(n: int) -> int:
    conn = connect()
    rows = conn.execute(
        "SELECT qa_id, asked_at, session_id, turn_no, question, feedback FROM qa_turn ORDER BY asked_at DESC LIMIT ?",
        (n,),
    ).fetchall()
    for r in rows:
        mark = {1: "[+]", -1: "[-]", 0: "   "}.get(r["feedback"], "   ")
        print(f"{mark} {r['asked_at']}  {r['session_id']}#{r['turn_no']}  {r['question']}")
    conn.close()
    return 0


def sql_lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def export_sql(out: pathlib.Path) -> int:
    conn = connect()
    sessions = conn.execute("SELECT * FROM qa_session ORDER BY started_at").fetchall()
    turns = conn.execute("SELECT * FROM qa_turn ORDER BY asked_at").fetchall()
    conn.close()

    lines = [
        "-- 由 tools/qa_store.py export-sql 生成：把本地镜像灌进 MySQL",
        "-- 用法：mysql -h<host> -u<user> -p dw_qa < db/qa_seed.sql",
        "SET NAMES utf8mb4;",
        "",
    ]
    for r in sessions:
        lines.append(
            "INSERT INTO qa_session (session_id, started_at, user_hash, channel, turn_cnt) "
            f"VALUES ({sql_lit(r['session_id'])}, {sql_lit(r['started_at'])}, {sql_lit(r['user_hash'])}, "
            f"{sql_lit(r['channel'])}, {int(r['turn_cnt'])}) ON DUPLICATE KEY UPDATE turn_cnt=VALUES(turn_cnt);"
        )
    lines.append("")
    for r in turns:
        lines.append(
            "INSERT INTO qa_turn (qa_id, session_id, turn_no, asked_at, question, answer, sql_text, "
            "sql_hash, intent, tables_json, feedback, feedback_note, model, latency_ms, ingested_at) VALUES ("
            f"{sql_lit(r['qa_id'])}, {sql_lit(r['session_id'])}, {int(r['turn_no'])}, {sql_lit(r['asked_at'])}, "
            f"{sql_lit(r['question'])}, {sql_lit(r['answer'])}, {sql_lit(r['sql_text'])}, {sql_lit(r['sql_hash'])}, "
            f"{sql_lit(r['intent'])}, {sql_lit(r['tables'])}, {int(r['feedback'])}, {sql_lit(r['feedback_note'])}, "
            f"{sql_lit(r['model'])}, {sql_lit(r['latency_ms'])}, {sql_lit(r['ingested_at'])}) "
            "ON DUPLICATE KEY UPDATE qa_id=VALUES(qa_id);"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"导出 {len(sessions)} 会话 / {len(turns)} 轮 → {out}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="问答沉淀本地存储")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建库建表")

    p = sub.add_parser("ingest", help="导入 JSONL")
    p.add_argument("--file", required=True)
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("stats", help="看总量与分布")

    p = sub.add_parser("recent", help="看最近几条")
    p.add_argument("--n", type=int, default=10)

    p = sub.add_parser("export-sql", help="导出 MySQL INSERT")
    p.add_argument("--out", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "init":
        init()
        return 0
    if args.cmd == "ingest":
        return ingest(pathlib.Path(args.file), args.dry_run)
    if args.cmd == "stats":
        return stats()
    if args.cmd == "recent":
        return recent(args.n)
    if args.cmd == "export-sql":
        return export_sql(pathlib.Path(args.out))
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
