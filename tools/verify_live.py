#!/usr/bin/env python3
"""现网验证：把 dq_rules.json 的断言拿到生产库跑一遍，产出可复查的报告。

    # 1) 只生成待执行清单（不连库，报告标记 offline，不得作为上线依据）
    python tools/verify_live.py --req 画像标签需求20261122 --offline

    # 2) 真连现网（引擎命令从环境变量取，避免把连接串写进仓库）
    set HQL_CMD=beeline -u jdbc:hive2://... -e
    python tools/verify_live.py --req 画像标签需求20261122 --engine hive --dt 20261127

报告落在 <需求开发员>/交付/验证报告.json 与 验证报告.md，
契约见 contracts/verification_report.schema.json。

设计要点：
- **规则不重写**：验证用的是 dq_rules.json 里的 assert_sql，改规则就重跑，不另写一份"验证 SQL"。
- **offline 一律 pending**：没连库就没有证据，报告不许写成 pass，H3 不许签。
- **每条都要证据**：数值、耗时、执行时点，方便事后对账。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ_ROOT = ROOT / "requirements"
DT_RE = re.compile(r"\$\{dt\}")


def now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def find_req(name: str) -> Path:
    d = REQ_ROOT / name
    if not d.exists():
        raise SystemExit(f"需求目录不存在: {d}")
    return d


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def run_sql(cmd: list[str], sql: str, timeout: int = 600) -> tuple[str, int]:
    full = cmd + [DT_RE.sub("${dt}", sql)]
    t0 = time.time()
    r = subprocess.run(full, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    return out.strip(), int(time.time() - t0)


def number(text: str) -> float | None:
    """从引擎输出里抓最后一个数字（beeline 会带表头/日志）。"""
    nums = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(nums[-1]) if nums else None


def judge(expect: dict, actual: float | None, second: float | None) -> tuple[bool, str]:
    if actual is None:
        return False, "没解析出数值"
    t = expect.get("type")
    if t == "zero_rows":
        return actual == 0, f"actual={actual:g}"
    if t == "zero_value":
        return actual == 0, f"actual={actual:g}"
    if t == "min_rows":
        v = expect.get("value", 1)
        return actual >= v, f"actual={actual:g} 期望 >= {v}"
    if t == "ratio_le":
        v = expect.get("value", 0.0001)
        return abs(actual) <= v, f"actual={actual:g} 期望 <= {v}"
    if t == "rerun_equal":
        if second is None:
            return False, "第二次执行缺失"
        return abs(actual - second) < 1e-9, f"第一次={actual:g} 第二次={second:g}"
    return False, f"未知 expect.type: {t}"


def build(req: Path, mode: str, engine: str, target: str, dt: str,
          cmd: list[str] | None) -> dict:
    dev = req / "需求开发员"
    dq_files = sorted(dev.rglob("dq_rules.json"))
    if not dq_files:
        raise SystemExit("找不到 dq_rules.json（先跑 P4）")
    dq = load_json(dq_files[0])
    payload = dq["payload"]
    rules = payload["rules"]

    checks, notes = [], []
    if mode == "offline":
        notes.append("离线生成：未连接现网，所有条目 verdict=skip，报告不得作为 H3 放行依据。")

    for i, r in enumerate(rules, 1):
        exp = r.get("expect", {})
        sql = r["assert_sql"]
        if "${dt}" in sql and not dt:
            notes.append(f"{r['id']}: SQL 用了 ${{dt}} 但没传 --dt，无法执行")
        item = {
            "id": f"V{i:03d}",
            "rule_id": r["id"],
            "category": r.get("category", ""),
            "sql": sql,
            "expect": json.dumps(exp, ensure_ascii=False),
            "verdict": "skip",
            "actual": "",
            "evidence": "",
        }
        if mode == "online" and cmd:
            sql_dt = DT_RE.sub(dt or "", sql)
            try:
                out, sec = run_sql(cmd, sql_dt)
            except subprocess.TimeoutExpired:
                item["actual"] = "timeout"
                item["verdict"] = "fail"
                item["evidence"] = f"{now()} 超时"
                checks.append(item)
                continue
            actual = number(out)
            second = None
            if exp.get("type") == "rerun_equal":
                out2, _ = run_sql(cmd, sql_dt)
                second = number(out2)
            ok, why = judge(exp, actual, second)
            item["actual"] = why
            item["verdict"] = "pass" if ok else "fail"
            item["evidence"] = f"{now()} 耗时 {sec}s｜{target}｜输出末行: {out.splitlines()[-1][:120] if out else '空'}"
        checks.append(item)

    passed = sum(1 for c in checks if c["verdict"] == "pass")
    failed = sum(1 for c in checks if c["verdict"] == "fail")
    skipped = sum(1 for c in checks if c["verdict"] == "skip")
    verdict = "pending" if mode == "offline" else ("pass" if failed == 0 and passed else "fail")

    return {
        "run_id": f"{datetime.now():%Y%m%d}-01",
        "stage": "P6",
        "payload": {
            "requirement_id": payload["requirement_id"],
            "generated_at": now(),
            "environment": {
                "mode": mode,
                "engine": engine,
                "target": target,
                "queried_at": now() if mode == "online" else "",
                "note": "，".join(notes)[:500],
            },
            "checks": checks,
            "summary": {"total": len(checks), "passed": passed, "failed": failed,
                        "skipped": skipped, "verdict": verdict},
            "signoff": {"status": "pending"},
            "notes": notes,
        },
    }


def render_md(rep: dict) -> str:
    p = rep["payload"]
    env, s = p["environment"], p["summary"]
    icon = {"pass": "✅", "fail": "❌", "skip": "⏭️"}
    head = [
        f"# 现网验证报告 {p['requirement_id']}",
        "",
        f"- 生成时间：{p['generated_at']}",
        f"- 环境：**{env['mode']}**（引擎 {env['engine']}，目标 {env['target'] or '—'}）",
        f"- 结论：**{s['verdict']}**　通过 {s['passed']} / 失败 {s['failed']} / 跳过 {s['skipped']}（共 {s['total']}）",
        f"- 签署：{p['signoff']['status']}",
        "",
    ]
    if p["signoff"]["status"] == "waived":
        w = p["signoff"]["waiver"]
        head += [f"> ⚠️ **有条件放行（waived）**：{w['reason']}",
                 f"> 到期 **{w['expires_at']}**，跟进待办 {w.get('followup_todo') or '（未登记）'}；到期未补证据即视为未放行。", ""]
    if env["mode"] == "offline":
        head += ["> ⚠️ 这是离线生成的清单，**没有任何现网证据**。H3 放行前必须重新以 online 模式跑一次。", ""]
    rows = ["| # | 规则 | 类别 | 期望 | 实际 | 结论 | 证据 |", "|---|---|---|---|---|---|---|"]
    for c in p["checks"]:
        rows.append(f"| {c['id']} | {c['rule_id']} | {c.get('category', '')} | {c['expect']} "
                    f"| {c['actual']} | {icon.get(c['verdict'], c['verdict'])} {c['verdict']} | {c['evidence']} |")
    tail = ["", "## 怎么用", "",
            "- `fail` 任一条 → 不许上线，先修数据或改规则；",
            "- 全为 `skip` → 报告只是清单，不算验证；",
            "- 上线后把本报告与 `交付/上线单.md` 一起归档，事后对账就看它。"]
    return "\n".join(head + rows + tail) + "\n"


def main(argv: list[str]) -> int:
    a = {}
    i = 0
    while i < len(argv):
        t = argv[i]
        if t.startswith("--"):
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt and not nxt.startswith("--"):
                a[t] = nxt
                i += 2
            else:
                a[t] = True
                i += 1
        else:
            i += 1
    if "--req" not in a:
        print(__doc__)
        return 2
    req = find_req(a["--req"])
    offline = "--offline" in a
    mode = "offline" if offline else "online"
    engine = a.get("--engine", "none" if offline else "hive")
    target = a.get("--target", os.environ.get("HQL_TARGET", ""))

    cmd = None
    if not offline:
        env_cmd = os.environ.get("HQL_CMD", "")
        if not env_cmd:
            print("[FAIL] 需要 HQL_CMD（如 beeline -u jdbc:hive2://... -e），"
                  "或用 --offline 只生成清单", file=sys.stderr)
            return 2
        cmd = env_cmd.split()

    rep = build(req, mode, engine, target, a.get("--dt", ""), cmd)

    if "--waive" in a:
        reason, until = a.get("--reason", ""), a.get("--until", "")
        if len(reason) < 10 or not until:
            print("[FAIL] --waive 需要 --reason（≥10 字，写清为什么没有现网证据）与 --until YYYY-MM-DD", file=sys.stderr)
            return 2
        rep["payload"]["signoff"] = {
            "status": "waived",
            "by": a.get("--by", "nino"),
            "at": now(),
            "waiver": {"reason": reason, "expires_at": until,
                       "followup_todo": a.get("--followup", ""), "approver": a.get("--by", "nino")},
        }
    out_dir = req / "需求开发员" / "交付"
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / "验证报告.json", out_dir / "验证报告.md"
    jp.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mp.write_text(render_md(rep), encoding="utf-8")

    s = rep["payload"]["summary"]
    print(f"验证报告 → {jp.relative_to(ROOT).as_posix()}")
    print(f"  {s['verdict']}：通过 {s['passed']} / 失败 {s['failed']} / 跳过 {s['skipped']}（共 {s['total']}）")
    if mode == "offline":
        print("  离线模式不产生证据，H3 不得据此放行")
    return 0 if s["verdict"] != "fail" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
