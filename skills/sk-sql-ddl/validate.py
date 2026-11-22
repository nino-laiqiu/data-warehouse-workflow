#!/usr/bin/env python3
"""sk-sql-ddl 的自检器：纯标准库，检查 DDL 的结构与硬规则。

    python skills/sk-sql-ddl/validate.py --input contract.json --sql out.sql
    python skills/sk-sql-ddl/validate.py --sql out.sql            # 只查 SQL 自身规则

只做结构检查，不做语义分析（不接 AST）。它能拦住的是"少写注释、分区列重复、
一次生成两条语句"这类低级错，拦不住"类型不匹配"。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TYPE_ENUM = None  # 从 schema.json 读，避免两处维护


def load_schema() -> dict:
    path = Path(__file__).resolve().parent / "schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def check_contract(contract: dict, schema: dict) -> list[str]:
    errs: list[str] = []
    for field in schema["required"]:
        if field not in contract:
            errs.append(f"契约缺少字段 {field}")
    if errs:
        return errs

    if not re.fullmatch(schema["properties"]["table_name"]["pattern"], contract["table_name"]):
        errs.append("table_name 必须形如 db.table 且全小写")

    cols = contract.get("columns") or []
    if not cols:
        errs.append("columns 不能为空")

    part_names = set()
    for p in contract.get("partitioned_by") or []:
        if p["name"] in part_names:
            errs.append(f"分区字段重复: {p['name']}")
        part_names.add(p["name"])

    col_names = set()
    for c in cols:
        name = c.get("name", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            errs.append(f"列名非法: {name!r}")
        if name in part_names:
            errs.append(f"列 {name} 同时出现在普通列与分区列")
        if name in col_names:
            errs.append(f"列名重复: {name}")
        col_names.add(name)
        if not c.get("comment"):
            errs.append(f"列 {name} 缺少 COMMENT")

    if not contract.get("comment"):
        errs.append("表缺少 COMMENT")
    if not contract.get("partitioned_by"):
        errs.append("必须显式声明分区字段（不允许无分区表）")
    return errs


def check_sql(sql: str) -> list[str]:
    errs: list[str] = []
    # 去掉开头的注释块：带表头注释的 DDL 是常态，不能因此判失败
    lines = sql.splitlines()
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
        lines.pop(0)
    body = "\n".join(lines).strip()
    if not body:
        return ["SQL 为空"]
    upper = body.upper()
    if not upper.startswith("CREATE TABLE") and not upper.startswith("CREATE EXTERNAL TABLE"):
        errs.append("必须以 CREATE TABLE 开头")
    statements = [s for s in body.split(";") if s.strip()]
    if len(statements) > 1:
        errs.append(f"一次只允许一条语句，实际 {len(statements)} 条")
    for banned in ("DROP TABLE", "TRUNCATE", "ALTER TABLE"):
        if re.search(rf"\b{banned}\b", upper):
            errs.append(f"禁止出现 {banned}")

    # 每个字段行都必须带 COMMENT
    col_lines = [ln for ln in body.splitlines()
                 if re.match(r"^\s{2,}[a-z][a-z0-9_]*\s+\S", ln) and "PARTITIONED BY" not in ln.upper()]
    for ln in col_lines:
        if "COMMENT" not in ln.upper():
            errs.append(f"字段缺少 COMMENT: {ln.strip()[:60]}")

    if body.count("(") != body.count(")"):
        errs.append("括号不配平")
    if "STORED AS" not in upper:
        errs.append("必须显式 STORED AS")
    errs += check_partition_not_in_columns(body)
    return errs


def check_partition_not_in_columns(body: str) -> list[str]:
    """分区列不能同时出现在普通列定义里。

    这条规则是从 runs/20261122-02 的双轨比对里长出来的：track-2 的
    `dws_user_tag_df` 把 dt 既写成普通列又写进 PARTITIONED BY，Hive 建表
    直接报错，但契约检查（--input 模式）才管，纯 SQL 模式漏了。
    """
    errs: list[str] = []
    m = re.search(r"PARTITIONED\s+BY\s*\(([^)]*)\)", body, re.IGNORECASE)
    if not m:
        return errs
    part_names = {
        part.strip().split()[0].lower()
        for part in m.group(1).split(",")
        if part.strip()
    }
    head = body[: m.start()]
    for ln in head.splitlines():
        hit = re.match(r"^\s{2,}([a-z][a-z0-9_]*)\s+[A-Za-z]", ln)
        if hit and hit.group(1).lower() in part_names:
            errs.append(f"分区列 {hit.group(1)} 同时出现在列定义里，Hive 会报重复列")
    return errs


def main(argv: list[str]) -> int:
    args = dict(zip(argv[::2], argv[1::2]))
    sql_path = args.get("--sql")
    if not sql_path:
        print("用法: validate.py --sql <out.sql> [--input <contract.json>]", file=sys.stderr)
        return 2

    errors: list[str] = []
    if "--input" in args:
        contract = json.loads(Path(args["--input"]).read_text(encoding="utf-8"))
        errors += check_contract(contract, load_schema())
    errors += check_sql(Path(sql_path).read_text(encoding="utf-8"))

    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
