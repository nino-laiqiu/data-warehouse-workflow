#!/usr/bin/env python
"""试跑质检（P3B / G3B）：把 final/ 脚本拿到能执行的环境里真跑一遍。

为什么要有它：G3 裁决通过只能说明"两份实现里选得对"，不能说明"这份 SQL 跑得动"。
在进入质量规则固化（P4）和血缘排期（P5）之前，先用一个便宜的办法验证三件事：
  1) 环境连得上（连不上就别谈通过，只能 blocked）；
  2) 每条脚本在引擎里能解释/能执行（EXPLAIN 不会执行数据，是最便宜的"跑得动"证据）；
  3) 跑出来的结果过得去（行数、主键唯一、与上游对账）——这三条不依赖 DQ 规则是否已写好。

三条纪律：
  - 没连环境 → verdict=blocked，**不许写 passed**；要放行只能在报告里写 waiver（人签）。
  - 默认只在沙箱库跑：target 不像沙箱（不含 tmp/shadow/试跑/dev）就必须显式 --allow-prod，且 G3B 会拒。
  - 只读校验用 SELECT，写操作用 --execute 显式打开；默认只 EXPLAIN。

用法：
    python tools/trial_run.py --req 画像标签需求20261122                        # 离线：只出计划，blocked
    python tools/trial_run.py --req 画像标签需求20261122 --mode sandbox --dt 20261127 --target dw_tmp_profile
    python tools/trial_run.py --req 画像标签需求20261122 --mode sandbox --execute   # 真跑 DDL/DML
    python tools/trial_run.py --req 画像标签需求20261122 --check                # G3B 门禁用：只验报告
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import validate_contracts as vc  # noqa: E402

SCHEMA = ROOT / "contracts" / "trial_run.schema.json"
REQ_ROOT = ROOT / "requirements"
DT_RE = re.compile(r"\$\{dt\}")
SANDBOX_WORDS = ("tmp", "shadow", "sandbox", "dev", "test", "试跑", "stg")


def find_req(name: str) -> Path:
    d = REQ_ROOT / name
    if not d.exists():
        raise SystemExit(f"需求目录不存在: {d}")
    return d


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect_scripts(req: Path) -> list[dict]:
    """final/ 下的脚本：`*etl*` 或含 INSERT 的算 dml，其余算 ddl。"""
    out = []
    final = req / "需求开发员" / "监督者" / "final"
    for p in sorted(final.glob("*.sql")):
        text = p.read_text(encoding="utf-8")
        kind = "dml" if (re.search(r"\bINSERT\b", text, re.I) or "etl" in p.name.lower()) else "ddl"
        out.append({"path": str(p.relative_to(ROOT)), "kind": kind,
                    "sha256": sha256_of(p), "status": "not_run", "_text": text})
    return out


def run_sql(cmd: list[str], sql: str, timeout: int = 600) -> tuple[str, int]:
    full = cmd + [DT_RE.sub("${dt}", sql)]
    try:
        r = subprocess.run(full, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except Exception as exc:  # 连不上、命令不存在、超时
        return f"{type(exc).__name__}: {exc}", 1
    return ((r.stdout or "") + (r.stderr or "")).strip(), r.returncode


def first_number(text: str) -> float | None:
    nums = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(nums[-1]) if nums else None


def target_table(req: Path) -> str | None:
    """从 final DDL 里抓目标表名。"""
    ddl = sorted((req / "需求开发员" / "监督者" / "final").glob("*.sql"))
    for p in ddl:
        m = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([\w.]+)`?", p.read_text(encoding="utf-8"), re.I)
        if m:
            return m.group(1)
    return None


def dq_of(req: Path) -> list[dict]:
    p = req / "需求开发员" / "质量" / "dq_rules.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))["payload"]["rules"]
    except Exception:
        return []


def build_checks(req: Path, scripts: list[dict], mode: str, target: str) -> list[dict]:
    checks: list[dict] = []
    checks.append({"id": "T001", "name": "环境连通（SELECT 1）", "category": "structure",
                   "sql": "SELECT 1", "expect": {"type": "equals", "value": 1}, "verdict": "skip"})
    for i, s in enumerate([x for x in scripts if x["kind"] == "ddl"], start=1):
        checks.append({"id": f"T10{i}", "name": f"DDL 可解释：{Path(s['path']).name}", "category": "executable",
                       "verdict": "skip"})
    for i, s in enumerate([x for x in scripts if x["kind"] == "dml"], start=1):
        checks.append({"id": f"T20{i}", "name": f"DML 可解释：{Path(s['path']).name}", "category": "executable",
                       "verdict": "skip"})
    tbl = target_table(req) or target
    if tbl:
        checks.append({"id": "T301", "name": "目标表当日有数据", "category": "quality",
                       "sql": f"SELECT COUNT(1) FROM {tbl} WHERE dt = '${{dt}}'",
                       "expect": {"type": "min_rows", "value": 1}, "verdict": "skip"})
    rules = dq_of(req)
    uniq = next((r for r in rules if r.get("category") == "unique"), None)
    if uniq:
        checks.append({"id": "T302", "name": "主键唯一（取 DQ 规则）", "category": "quality",
                       "sql": uniq.get("assert_sql", ""), "expect": uniq.get("expect", {"type": "zero_rows"}),
                       "verdict": "skip"})
    rec = next((r for r in rules if r.get("category") == "reconcile"), None)
    if rec:
        checks.append({"id": "T303", "name": "与上游对账（取 DQ 规则）", "category": "reconcile",
                       "sql": rec.get("assert_sql", ""), "expect": rec.get("expect", {"type": "ratio_le"}),
                       "verdict": "skip"})
    return checks


def judge(expect: dict, actual: float | None) -> bool:
    t = (expect or {}).get("type")
    if actual is None:
        return False
    if t in ("zero_rows", "zero_value"):
        return actual == 0
    if t == "min_rows":
        return actual >= float((expect or {}).get("value", 1))
    if t == "ratio_le":
        return abs(actual) <= float((expect or {}).get("value", 0.0001))
    if t == "equals":
        return actual == float((expect or {}).get("value", 0))
    return False


def write_report(req: Path, payload: dict) -> Path:
    d = req / "需求开发员" / "试跑"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"run_id": "R-" + datetime.now().strftime("%Y%m%d%H%M%S"),
           "stage": "P3B", "payload": payload}
    p = d / "试跑报告.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "试跑报告.md").write_text(render_md(payload), encoding="utf-8")
    return p


def render_md(pl: dict) -> str:
    env = pl["environment"]
    lines = [f"# 试跑质检报告 · {pl['requirement_id']}", "",
             f"- 生成时间：{pl['generated_at']}",
             f"- 模式：`{env['mode']}`　引擎：`{env['engine']}`　目标库：`{env['target']}`"
             f"　沙箱：{'是' if env['target_is_sandbox'] else '否'}",
             f"- 结论：**{pl['verdict']}**（passed / failed / blocked）", "",
             "## 脚本", "", "| 脚本 | 类型 | 状态 | sha256 前 8 位 |", "|---|---|---|---|"]
    for s in pl["scripts"]:
        lines.append(f"| `{Path(s['path']).name}` | {s['kind']} | {s['status']} | `{s['sha256'][:8]}` |")
    lines += ["", "## 检查项", "", "| id | 名称 | 类别 | 结论 | 证据 |", "|---|---|---|---|---|"]
    for c in pl["checks"]:
        lines.append(f"| {c['id']} | {c['name']} | {c['category']} | {c['verdict']} | {(c.get('evidence') or '').replace('|', '/')} |")
    if pl.get("waiver"):
        w = pl["waiver"]
        lines += ["", "## 豁免", "", f"- 理由：{w['reason']}", f"- 批准：{w['approved_by']}　到期：{w['expires_at']}"]
    if pl.get("notes"):
        lines += ["", "## 说明", "", pl["notes"]]
    lines += ["", "> blocked 不等于通过：它表示「没有环境证据」。要么补环境重跑，要么由人签豁免并把待办记进 journal。", ""]
    return "\n".join(lines)


def cmd_check(req: Path) -> int:
    p = req / "需求开发员" / "试跑" / "试跑报告.json"
    if not p.exists():
        print(f"[FAIL] 没有试跑报告：{p.relative_to(ROOT)}")
        print("       先跑 python tools/trial_run.py --req " + req.name)
        return 1
    doc = json.loads(p.read_text(encoding="utf-8"))
    errs = vc.validate_against(doc, SCHEMA)
    if errs:
        print("[FAIL] 试跑报告不符合契约：")
        for e in errs:
            print("   - " + e)
        return 1
    pl = doc["payload"]
    verdict = pl["verdict"]
    waiver = pl.get("waiver")
    if verdict == "failed":
        bad = [c["id"] for c in pl["checks"] if c["verdict"] == "fail"]
        print(f"[FAIL] 试跑失败，检查项：{', '.join(bad) or '（见报告）'}")
        return 1
    if verdict == "blocked" and not waiver:
        print("[FAIL] 试跑未连环境（blocked），且没有豁免：G3B 不放行。")
        print("       要么给 HQL_CMD 重跑，要么在报告里写 waiver(reason/approved_by/expires_at)。")
        return 1
    if pl["environment"]["mode"] != "offline" and not pl["environment"]["target_is_sandbox"] and not waiver:
        print("[FAIL] 目标库不像沙箱（名字里没有 tmp/shadow/dev/试跑 等），禁止在正式库试跑。")
        return 1
    if any(s["status"] == "failed" for s in pl["scripts"]):
        print("[FAIL] 有脚本执行失败，见 report.md")
        return 1
    tag = "WAIVED" if verdict == "blocked" and waiver else "PASS"
    print(f"[{tag}] 试跑报告合规：{len(pl['scripts'])} 个脚本，{len(pl['checks'])} 个检查项，verdict={verdict}")
    if tag == "WAIVED":
        print(f"       豁免到期 {pl['waiver']['expires_at']}，到期前必须补环境证据")
    return 0


def main(argv: list[str]) -> int:
    args = {"--req": "", "--mode": "offline", "--dt": "", "--target": "", "--engine": "hive"}
    flags = set()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in args and i + 1 < len(argv):
            args[a] = argv[i + 1]
            i += 2
            continue
        flags.add(a)
        i += 1
    if not args["--req"]:
        print(__doc__)
        return 2
    req = find_req(args["--req"])
    if "--check" in flags:
        return cmd_check(req)

    mode = args["--mode"]
    target = args["--target"] or os.environ.get("HQL_TARGET", "")
    dt = args["--dt"] or os.environ.get("HQL_DT", "")
    scripts = collect_scripts(req)
    if not scripts:
        print("[FAIL] 监督者/final/ 里没有脚本，P3 还没产出")
        return 1
    is_sandbox = any(w in (target or "").lower() for w in SANDBOX_WORDS)
    env = {"mode": mode, "engine": args["--engine"], "target": target or "（未指定）",
           "target_is_sandbox": is_sandbox}
    if dt:
        env["dt"] = dt
    checks = build_checks(req, scripts, mode, target)
    hql = os.environ.get("HQL_CMD", "").strip()

    if mode == "offline" or not hql:
        for s in scripts:
            s["status"] = "not_run"
        for c in checks:
            c["verdict"] = "skip"
            c["evidence"] = "离线模式：未连环境，没有任何执行证据"
        verdict = "blocked"
        notes = ("离线试跑：只列出计划，不产生证据。这不是通过——G3B 要求真连环境跑一遍，"
                 "或用 waiver 由人签放行并记待办。")
    else:
        cmd = hql.split()
        out, rc = run_sql(cmd, "SELECT 1", timeout=120)
        conn_ok = rc == 0
        checks[0]["actual"] = first_number(out)
        checks[0]["verdict"] = "pass" if conn_ok and judge(checks[0]["expect"], checks[0]["actual"]) else "fail"
        checks[0]["evidence"] = (out or "")[-200:]
        if conn_ok:
            env["connected_at"] = datetime.now().isoformat(timespec="seconds")
        # 解释：DDL 与 DML 都先 EXPLAIN（Hive 支持 EXPLAIN <statement>）
        idx_ddl = [c for c in checks if c["id"].startswith("T1")]
        idx_dml = [c for c in checks if c["id"].startswith("T2")]
        for c, s in zip(idx_ddl, [x for x in scripts if x["kind"] == "ddl"]):
            if not conn_ok:
                c["verdict"] = "blocked"
                c["evidence"] = "环境未连通"
                continue
            out2, rc2 = run_sql(cmd, "EXPLAIN " + s["_text"], timeout=300)
            c["verdict"] = "pass" if rc2 == 0 else "fail"
            c["evidence"] = (out2 or "")[-300:]
            s["status"] = "explained" if rc2 == 0 else "failed"
            if rc2 != 0:
                s["error"] = (out2 or "")[-300:]
        for c, s in zip(idx_dml, [x for x in scripts if x["kind"] == "dml"]):
            if not conn_ok:
                c["verdict"] = "blocked"
                c["evidence"] = "环境未连通"
                continue
            stmt = s["_text"] if "--execute" in flags else "EXPLAIN " + s["_text"]
            out2, rc2 = run_sql(cmd, stmt, timeout=900)
            c["verdict"] = "pass" if rc2 == 0 else "fail"
            c["evidence"] = (out2 or "")[-300:]
            s["status"] = ("executed" if "--execute" in flags else "explained") if rc2 == 0 else "failed"
            if rc2 != 0:
                s["error"] = (out2 or "")[-300:]
        # 结果类检查：只有真执行过才有意义
        for c in [x for x in checks if x["id"].startswith("T3")]:
            if "--execute" not in flags or not conn_ok:
                c["verdict"] = "skip"
                c["evidence"] = "未执行写操作，结果类检查跳过"
                continue
            out3, rc3 = run_sql(cmd, c["sql"], timeout=600)
            c["actual"] = first_number(out3)
            c["verdict"] = "pass" if rc3 == 0 and judge(c.get("expect", {}), c["actual"]) else "fail"
            c["evidence"] = (out3 or "")[-200:]
        verdict = "failed" if any(c["verdict"] == "fail" for c in checks) else "passed"
        notes = ("真机试跑：EXPLAIN 通过只代表「能解释」，--execute 才代表「写进去过」。"
                 "结果类检查只在执行后有效。")
        if not is_sandbox and "--allow-prod" not in flags:
            verdict = "blocked"
            notes += " 目标库不像沙箱，且未加 --allow-prod：拒绝在正式库试跑。"
        elif not is_sandbox:
            notes += " 已显式 --allow-prod：在非沙箱库试跑，风险自负。"

    payload = {"requirement_id": guess_req_id(req),
               "generated_at": datetime.now().isoformat(timespec="seconds"),
               "environment": env, "scripts": scripts, "checks": checks,
               "verdict": verdict, "notes": notes}
    for s in scripts:
        s.pop("_text", None)
    p = write_report(req, payload)
    print(f"试跑报告：{p.relative_to(ROOT)}（verdict={verdict}）")
    return 0 if verdict == "passed" else (2 if verdict == "blocked" else 1)


def guess_req_id(req: Path) -> str:
    reg = ROOT / "requirements" / "_registry.jsonl"
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("requirement_dir") == req.name:
                return rec.get("req_id") or rec.get("requirement_id") or ""
    m = re.search(r"REQ-\d{8}-\d{2}", req.name)
    return m.group(0) if m else ""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
