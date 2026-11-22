#!/usr/bin/env python3
"""把 dq_rules.json 渲染成可批量执行的 dq_check.sql。

    python tools/dq_to_sql.py requirements/画像标签需求20261122/需求开发员/质量/dq_rules.json

为什么要生成、不手写：规则改一处、SQL 和元数据不同步，是数据质量最常见的腐化方式。
唯一事实源是 dq_rules.json，dq_check.sql 每次重新生成，不手改。

跑法（Hive）：
    hive -hivevar dt=2026-11-21 -f dq_check.sql
判定：每条断言返回 0 或 0 行 = 通过；返回非 0 / 有行 = 失败。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECT_TEXT = {
    "zero_rows": "返回 0 行",
    "zero_value": "返回 0",
    "ratio_le": "比值 <= {value}",
    "min_rows": "行数 >= {value}",
    "rerun_equal": "重跑两次指纹一致",
}


def render(doc: dict) -> str:
    payload = doc["payload"]
    rules = payload["rules"]
    out: list[str] = [
        "-- " + "=" * 60,
        "-- 由 tools/dq_to_sql.py 从 dq_rules.json 生成，不要手改",
        f"-- 需求：{payload['requirement_id']}　规则：{len(rules)} 条　"
        f"目标表：{', '.join(payload['targets'])}",
        "-- 用法：hive -hivevar dt=2026-11-21 -f dq_check.sql",
        "-- 判定：每条断言返回 0（或 0 行）= 通过",
        "-- " + "=" * 60,
        "",
    ]
    for r in rules:
        expect = EXPECT_TEXT[r["expect"]["type"]].format(**r["expect"])
        out.append(f"-- {r['id']} {r['name']} [{r['category']}/{r['severity']}]")
        out.append(f"-- 期望：{expect}")
        if r.get("desc"):
            out.append(f"-- 说明：{r['desc']}")
        if r.get("on_fail"):
            out.append(f"-- 失败动作：{r['on_fail']}")
        out.append(r["assert_sql"].strip().rstrip(";") + ";")
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    src = Path(args[0])
    out_path = Path(argv[argv.index("--out") + 1]) if "--out" in argv else src.with_name("dq_check.sql")
    doc = json.loads(src.read_text(encoding="utf-8"))
    out_path.write_text(render(doc), encoding="utf-8", newline="\n")
    print(f"已生成 {out_path}（{len(doc['payload']['rules'])} 条规则）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
