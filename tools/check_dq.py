#!/usr/bin/env python3
"""G4 门禁：检查 dq_rules.json 是否"可执行"。

    python tools/check_dq.py requirements/画像标签需求20261122/需求开发员/质量/dq_rules.json

除了契约结构，这里额外卡三件 G4 明确要求的事：
  1. 至少覆盖 空值(null) / 重复(unique) / 单调性(monotonic) 三类
  2. 每条规则必须是单条只读 SELECT，且带 ${dt} 分区占位——否则没法按天跑
  3. 只有零行/零值/阈值这类"能被机器判定"的期望，不接受"人工检查"
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_contracts import validate_against  # noqa: E402

REQUIRED_CATEGORIES = {"null", "unique", "monotonic"}
READONLY_START = re.compile(r"^(SELECT|WITH)\b", re.I)
FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", re.I)
ALLOWED_EXPECT = {"zero_rows", "zero_value", "ratio_le", "min_rows", "rerun_equal"}


def check(doc_path: Path) -> list[str]:
    problems: list[str] = []
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"JSON 解析失败: {exc}"]

    problems += validate_against(doc, Path("contracts/dq_rules.schema.json"))
    if problems:
        return problems  # 结构都不对，后面的语义检查没意义

    payload = doc["payload"]
    rules = payload["rules"]
    targets = set(payload["targets"])

    ids = [r["id"] for r in rules]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        problems.append(f"规则 id 重复: {sorted(dup)}")

    cats = {r["category"] for r in rules}
    missing = REQUIRED_CATEGORIES - cats
    if missing:
        problems.append(f"G4 要求覆盖 空值/重复/单调性，缺: {sorted(missing)}")

    if not any(r["severity"] == "block" for r in rules):
        problems.append("一条 block 规则都没有，等于没有门禁")

    for r in rules:
        rid, sql = r["id"], r["assert_sql"].strip()

        if not READONLY_START.match(sql):
            problems.append(f"{rid}: assert_sql 必须以 SELECT/WITH 开头")
        if sql.rstrip(";").count(";") > 0:
            problems.append(f"{rid}: assert_sql 必须是单条语句")
        if "${dt}" not in sql:
            problems.append(f"{rid}: 缺 ${{dt}} 分区占位，没法按天跑")
        if FORBIDDEN.search(sql):
            problems.append(f"{rid}: 断言里出现写操作关键字，只能是只读查询")
        if r["target"] not in targets:
            problems.append(f"{rid}: target {r['target']!r} 不在 targets 里")
        if r["target"] not in sql:
            problems.append(f"{rid}: 断言没查 {r['target']}")
        if r["expect"]["type"] not in ALLOWED_EXPECT:
            problems.append(f"{rid}: 期望类型 {r['expect']['type']!r} 无法机器判定")
        if r["expect"]["type"] in {"ratio_le", "min_rows"} and "value" not in r["expect"]:
            problems.append(f"{rid}: 期望类型 {r['expect']['type']} 必须给 value")

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
        rules = doc["payload"]["rules"]
        blocks = sum(1 for r in rules if r["severity"] == "block")
        print(f"规则 {len(rules)} 条（block {blocks} / warn {len(rules) - blocks}）"
              f"，类别 {sorted({r['category'] for r in rules})}")
        for p in problems:
            print(f"  ✗ {p}")
        print("PASS" if not problems else f"FAIL（{len(problems)} 处）")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
