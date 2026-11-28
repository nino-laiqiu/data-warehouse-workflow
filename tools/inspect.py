#!/usr/bin/env python3
"""全仓巡检：一条命令跑完全部门禁 + 卫生指标，产出周报。

只读：不修改任何业务文件，只在 runs/inspection/<YYYY-Www>/ 下写报告。

用法:
    python tools/inspect.py                  # 打印摘要 + 写 report.md / report.json
    python tools/inspect.py --no-write       # 只打印
    python tools/inspect.py --json           # 额外把 report.json 打到 stdout

退出码: 0 = 无阻断问题；1 = 有 FAIL；2 = 用法错误
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ["G0", "G1", "G2", "G3", "G4", "G5", "G6"]
HITL = {"G1": "H1 口径确认", "G3": "H2 裁决评审", "G5": "H3 上线放行"}
DESIGNED_CONTRACTS = [
    "intent", "analysis", "requirement", "ontology_delta", "model_design",
    "metric_spec", "dq_rules", "lineage", "comparison_report",
]


# ---------- 基础工具 ----------

def run(cmd: list[str]) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180, env=env)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as exc:  # noqa: BLE001
        return 99, "", f"调用失败: {exc}"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def requirement_dirs() -> list[Path]:
    base = ROOT / "requirements"
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir()
                  if p.is_dir() and p.name != "templates" and not p.name.startswith("_"))


def dev_dir(req: Path) -> Path | None:
    d = req / "需求开发员"
    return d if d.exists() else None


# ---------- 门禁组 ----------

def build_checks() -> list[dict]:
    py = lambda *parts: ["./" + "/".join(parts)]  # noqa: E731
    checks: list[dict] = []

    def add(name, group, cmd, optional=False):
        checks.append({"name": name, "group": group, "cmd": cmd, "optional": optional})

    add("本体校验", "门禁", py("ontology", "schema", "validate.py"))
    add("角色定义", "门禁", py("tools", "check_agents.py"))
    add("目录布局", "门禁", py("tools", "check_layout.py"))
    add("技能引用", "门禁", py("tools", "check_skills.py"))
    add("知识链接", "门禁", py("tools", "check_wiki.py"))
    add("知识变更登记", "门禁", py("tools", "wiki_impact.py") + ["--check"])
    add("需求登记 G0", "门禁", py("skills", "sk-req-register", "validate.py"))

    for req in requirement_dirs():
        norm = req / "需求分析员"
        for doc in sorted(norm.glob("REQ-*.md")) if norm.exists() else []:
            add(f"翻译稿 G1 {req.name}", "门禁", py("skills", "sk-req-validate", "validate.py") + ["--doc", rel(doc)])

        d = dev_dir(req)
        if not d:
            continue
        for f in sorted(d.rglob("dq_rules.json")):
            add(f"质量规则 G4 {req.name}", "门禁", py("tools", "check_dq.py") + [rel(f)])
        for f in sorted(d.rglob("lineage.json")):
            add(f"血缘 G5 {req.name}", "门禁", py("tools", "check_lineage.py") + [rel(f)])
        for f in sorted(d.rglob("comparison_report.json")):
            add(f"对比报告 {req.name}", "门禁", py("tools", "validate_contracts.py") + [rel(f)])
        for f in sorted(d.rglob("journal.jsonl")):
            add(f"留痕格式 {req.name}", "门禁",
                py("tools", "validate_contracts.py") + [rel(f), "--lines",
                                                       "--schema", "contracts/journal_entry.schema.json"])
        review_dir = norm / "_review"
        if review_dir.exists():
            for f in sorted(review_dir.glob("*.json")):
                add(f"审阅状态 {f.stem}", "门禁",
                    py("tools", "req_review.py") + ["check", "--req-id", f.stem])
        if (d / "journal.jsonl").exists():
            add(f"留痕完整性 {req.name}", "门禁",
                py("tools", "journal.py") + ["check", "--req", req.name])
    return checks


def run_checks(checks: list[dict]) -> list[dict]:
    out = []
    for c in checks:
        rc, so, se = run(c["cmd"])
        ok = rc == 0
        reason = ""
        if not ok:
            text = se or so
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            reason = next((ln for ln in lines if "FAIL" in ln or "错误" in ln or "失败" in ln), lines[0] if lines else f"退出码 {rc}")
        out.append({**c, "ok": ok, "reason": reason[:300]})
    return out


# ---------- 资产指标 ----------

def ontology_stats() -> dict:
    entity_dirs = ["dict", "object", "process", "metric", "link", "constraint"]
    files: list[Path] = []
    for d in entity_dirs:
        p = ROOT / "ontology" / d
        if p.exists():
            files += sorted(p.rglob("*.yaml"))
    status: dict[str, int] = {}
    stale = []
    cutoff = date.today() - timedelta(days=90)
    for f in files:
        m = re.search(r"^status:\s*(\S+)", read(f), re.M)
        s = (m.group(1).strip() if m else "unknown")
        status[s] = status.get(s, 0) + 1
        if s == "draft" and datetime.fromtimestamp(f.stat().st_mtime).date() < cutoff:
            stale.append(rel(f))
    return {"files": len(files), "status": status, "stale_draft": stale}


def skill_stats() -> dict:
    impl, spec = [], []
    for d in sorted((ROOT / "skills").iterdir()):
        md = d / "SKILL.md"
        if not md.exists():
            continue
        head = md.read_text(encoding="utf-8")[:400]
        (spec if "status: spec" in head else impl).append(d.name)
    pipe = ROOT / "flow" / "pipeline.yaml"
    refs: set[str] = set()
    order: dict[str, int] = {}
    if pipe.exists():
        text = read(pipe)
        for m in re.finditer(r"^\s+skills:\s*\[(.*?)\]", text, re.M):
            for s in m.group(1).split(","):
                s = s.strip().strip("'\"")
                if s:
                    refs.add(s)
                    order.setdefault(s, len(order))
    # 按在工作流里第一次出现的顺序排，越靠前越该先补
    pending = sorted((r for r in refs if not (ROOT / "skills" / r / "SKILL.md").exists()),
                     key=lambda s: (order.get(s, 999), s))
    orphan = sorted(set(impl) - refs)
    return {"implemented": impl, "spec_only": spec, "referenced": sorted(refs),
            "pending": pending, "orphan": orphan}


def contract_stats() -> dict:
    files = sorted(p.stem.replace(".schema", "") for p in (ROOT / "contracts").glob("*.schema.json"))
    files = [f for f in files if f != "_template"]
    missing = [c for c in DESIGNED_CONTRACTS if c not in files]
    return {"have": files, "missing": missing, "designed": len(DESIGNED_CONTRACTS)}


def knowledge_stats() -> dict:
    base = ROOT / "knowledge"
    md = [p for p in base.rglob("*.md") if p.name != "README.md"]
    idx = base / "index" / "chunks.jsonl"
    chunks = []
    if idx.exists():
        for ln in read(idx).splitlines():
            ln = ln.strip()
            if ln:
                try:
                    chunks.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    indexed = {c.get("path", "") for c in chunks}
    uncovered = [rel(p) for p in md if not any(rel(p).endswith(i) for i in indexed)]
    return {"files": len(md), "chunks": len(chunks), "uncovered": uncovered}



def qa_stats() -> dict:
    """问答沉淀挖出来的候选：待审积压是最容易烂掉的地方。"""
    base = ROOT / "知识候选"
    cands: list[dict] = []
    for f in sorted(base.glob("*/candidates.jsonl")):
        for ln in read(f).splitlines():
            ln = ln.strip()
            if ln:
                try:
                    cands.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    pending = [c for c in cands if c.get("status") == "pending"]
    oldest_days = 0
    if pending:
        stamps = sorted(c.get("created_at", "") for c in pending if c.get("created_at"))
        if stamps:
            try:
                d = datetime.strptime(stamps[0], "%Y%m%d")
                oldest_days = (datetime.now() - d).days
            except ValueError:
                oldest_days = 0
    return {"total": len(cands), "pending": len(pending), "oldest_days": oldest_days, "items": pending}

def journal_stats() -> dict:
    rows = []
    for req in requirement_dirs():
        for f in sorted(req.rglob("journal.jsonl")):
            entries = []
            for ln in read(f).splitlines():
                ln = ln.strip()
                if ln:
                    try:
                        entries.append(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
            gates = {}
            for e in entries:
                if e.get("type") == "gate" and e.get("gate"):
                    gates[e["gate"]] = e.get("result")
            last = max((e.get("ts", "") for e in entries), default="")
            passed = [g for g in GATES if gates.get(g) in ("pass", "waived")]
            waived = [g for g in GATES if gates.get(g) == "waived"]
            reached = passed[-1] if passed else "—"
            waiting = [g for g in GATES if g not in gates]
            anomalies = []
            if passed:
                first = GATES.index(passed[0])
                for i in range(first, len(GATES)):
                    if GATES[i] not in gates:
                        later = [g for g in passed if GATES.index(g) > i]
                        if later:
                            anomalies.append(f"{GATES[i]} 未过但 {'、'.join(later)} 已过（门禁顺序倒挂）")
            todos: dict[str, dict] = {}
            for e in entries:
                if e.get("type") == "todo" and e.get("todo_id"):
                    todos[e["todo_id"]] = e
            open_todos = [k for k, v in todos.items() if v.get("status") == "open"]

            blocked = [e for e in entries
                       if e.get("type") == "progress" and e.get("state") == "blocked"]
            blocked_days = 0
            if blocked:
                try:
                    from datetime import datetime
                    ts = max(e.get("ts", "") for e in blocked)
                    blocked_days = (datetime.now().astimezone()
                                    - datetime.fromisoformat(ts)).days
                except ValueError:
                    blocked_days = 0

            rows.append({
                "requirement": req.name,
                "events": len(entries),
                "open_todos": open_todos,
                "blocked_days": blocked_days,
                "gates": gates,
                "reached": reached,
                "passed_count": len(passed),
                "waiting": waiting,
                "anomalies": anomalies,
                "waived": waived,
                "last_ts": last,
            })
    return {"requirements": rows}


def hygiene_stats() -> dict:
    empties = []
    for d in ROOT.rglob("*"):
        if d.is_dir() and ".git" not in d.parts and ".tmp" not in d.parts and "node_modules" not in d.parts:
            try:
                if not any(d.iterdir()):
                    empties.append(rel(d))
            except OSError:
                pass
    return {"empty_dirs": empties}


# ---------- 报告 ----------

def collect() -> dict:
    checks = run_checks(build_checks())
    ont = ontology_stats()
    sk = skill_stats()
    ct = contract_stats()
    kn = knowledge_stats()
    qa = qa_stats()
    jr = journal_stats()
    hy = hygiene_stats()

    problems: list[dict] = []
    for c in checks:
        if not c["ok"]:
            problems.append({"level": "block", "where": c["name"], "detail": c["reason"]})
    for r in jr["requirements"]:
        for a in r["anomalies"]:
            problems.append({"level": "anomaly", "where": r["requirement"], "detail": a})
        for g in r["waiting"]:
            days = ""
            if r["last_ts"]:
                try:
                    days = (datetime.now().astimezone() - datetime.fromisoformat(r["last_ts"])).days
                    days = f"{days} 天"
                except ValueError:
                    days = ""
            problems.append({"level": "hitl" if g in HITL else "gap",
                             "where": f"{r['requirement']} · {g}",
                             "detail": (f"未过门，需 {HITL[g]}" if g in HITL else "未过门") + (f"（已挂 {days}）" if days else "")})
        for g in r.get("waived", []):
            problems.append({"level": "stale", "where": f"{r['requirement']} · {g}",
                             "detail": "有条件放行（waived）：到期前必须补现网证据，否则视为未放行"})
    for f in ont["stale_draft"]:
        problems.append({"level": "stale", "where": f, "detail": "status: draft 超过 90 天，需复审判定"})
    if sk["pending"]:
        problems.append({"level": "gap", "where": "技能", "detail": f"{len(sk['pending'])} 个技能被工作流引用但未实现: " + ", ".join(sk["pending"])})
    if sk.get("spec_only"):
        problems.append({"level": "info", "where": "技能",
                         "detail": f"{len(sk['spec_only'])} 个技能只有规格（status: spec），实现待排期: "
                                   + ", ".join(sk["spec_only"])})
    if ct["missing"]:
        problems.append({"level": "gap", "where": "契约", "detail": f"缺 {len(ct['missing'])} 个设计契约: " + ", ".join(ct["missing"])})
    if kn["uncovered"]:
        problems.append({"level": "gap", "where": "知识索引", "detail": f"{len(kn['uncovered'])} 个知识文件没有 chunk 索引"})
    if qa["pending"]:
        problems.append({"level": "gap", "where": "知识候选",
                         "detail": f"{qa['pending']} 条候选待审（最老一条 {qa['oldest_days']} 天）：" + ", ".join(c["candidate_id"] for c in qa["items"][:4])})
    if hy["empty_dirs"]:
        problems.append({"level": "info", "where": "空目录", "detail": ", ".join(hy["empty_dirs"])})

    total = len(checks)
    passed = sum(1 for c in checks if c["ok"])
    weights = {"block": 10, "anomaly": 4, "hitl": 3, "gap": 2, "stale": 1, "info": 0}
    penalty = sum(weights.get(p["level"], 1) for p in problems)
    score = max(0, 100 - (0 if total == 0 else (total - passed) * 10) - penalty)

    week = isoweek()
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "week": week,
        "summary": {"checks_total": total, "checks_passed": passed, "score": score,
                    "block": sum(1 for p in problems if p["level"] == "block")},
        "checks": checks,
        "ontology": ont, "skills": sk, "contracts": ct, "knowledge": kn,
        "journals": jr, "hygiene": hy, "problems": problems,
        "hitl_backlog": [p for p in problems if p["level"] == "hitl"],
        "trend": trend(week, score, problems),
    }


def trend(week: str, score: int, problems: list[dict]) -> dict:
    """和上一份报告比：分数变化 + 新增 / 消失的问题。"""
    base = ROOT / "runs" / "inspection"
    if not base.exists():
        return {"prev_week": None}
    prev_dirs = sorted(d for d in base.iterdir() if d.is_dir() and d.name != week)
    if not prev_dirs:
        return {"prev_week": None}
    f = prev_dirs[-1] / "report.json"
    if not f.exists():
        return {"prev_week": None}
    try:
        prev = json.loads(read(f))
    except json.JSONDecodeError:
        return {"prev_week": None}
    prev_keys = {(p.get("where"), p.get("detail")) for p in prev.get("problems", [])}
    cur_keys = {(p.get("where"), p.get("detail")) for p in problems}
    return {
        "prev_week": prev.get("week"),
        "score_delta": score - prev.get("summary", {}).get("score", score),
        "new": [f"{w}: {d}" for w, d in sorted(cur_keys - prev_keys)],
        "resolved": [f"{w}: {d}" for w, d in sorted(prev_keys - cur_keys)],
    }


def isoweek() -> str:
    t = date.today().isocalendar()
    return f"{t.year}-W{t.week:02d}"


def render_md(r: dict) -> str:
    s = r["summary"]
    lines = [
        f"# 数仓工作流巡检报告 · {r['week']}",
        "",
        f"> 生成时间 {r['generated_at']}　|　健康分 **{s['score']}**　|　门禁 {s['checks_passed']}/{s['checks_total']}　|　阻断问题 {s['block']} 条",
        "",
        "## 一、门禁",
        "",
        "| 检查 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for c in r["checks"]:
        mark = "✅" if c["ok"] else "❌"
        lines.append(f"| {c['name']} | {mark} | {c['reason'] or '—'} |")

    lines += ["", "## 二、需求闭环", "",
              "| 需求 | 事件 | 已过门禁 | 最远 | 未过门 | 未关待办 | 卡住天数 | 最后留痕 |",
              "|---|---|---|---|---|---|---|---|"]
    for j in r["journals"]["requirements"]:
        waiting = "、".join(j["waiting"]) or "—"
        todos = "、".join(j.get("open_todos") or []) or "0"
        stuck = j.get("blocked_days") or 0
        stuck_s = f"{stuck} 天" + (" ⚠️" if stuck > 5 else "") if stuck else "—"
        lines.append(f"| {j['requirement']} | {j['events']} | {j['passed_count']}/7 | {j['reached']} | {waiting} | {todos} | {stuck_s} | {j['last_ts'] or '—'} |")

    o, k = r["ontology"], r["knowledge"]
    status = "、".join(f"{x} {y}" for x, y in sorted(o["status"].items()))
    lines += [
        "", "## 三、资产",
        "",
        f"- **本体**：{o['files']} 个文件（{status}）",
        f"- **契约**：设计契约 {len([c for c in r['contracts']['have'] if c in DESIGNED_CONTRACTS])}/{r['contracts']['designed']}（缺：{'、'.join(r['contracts']['missing']) or '无'}），另有 {len([c for c in r['contracts']['have'] if c not in DESIGNED_CONTRACTS])} 个附加契约（留痕/验证/问答/模板）",
        f"- **技能**：已实现 {len(r['skills']['implemented'])}，被引用 {len(r['skills']['referenced'])}，待建 {len(r['skills']['pending'])}",
        f"- **知识**：{k['files']} 个文件，索引 {k['chunks']} 条，未索引 {len(k['uncovered'])} 个",
        "",
        "## 四、问题清单",
        "",
    ]
    if not r["problems"]:
        lines.append("无。")
    else:
        icon = {"block": "🔴", "anomaly": "🟣", "hitl": "🟡", "gap": "🟠", "stale": "🔵", "info": "⚪"}
        for p in r["problems"]:
            lines.append(f"- {icon.get(p['level'], '·')} **{p['where']}**：{p['detail']}")

    t = r.get("trend", {})
    lines += ["", "## 五、与上周对比", ""]
    if t.get("prev_week"):
        d = t["score_delta"]
        arrow = f"（+{d}）" if d > 0 else (f"（{d}）" if d < 0 else "（持平）")
        lines.append(f"上周 `{t['prev_week']}` → 本周 `{r['week']}`：健康分 {s['score'] - d} → {s['score']} {arrow}")
        if t["new"]:
            lines += ["", "**新增问题**", ""] + [f"- {x}" for x in t["new"]]
        if t["resolved"]:
            lines += ["", "**已消失问题**", ""] + [f"- {x}" for x in t["resolved"]]
        if not t["new"] and not t["resolved"]:
            lines += ["", "问题清单没有变化。"]
    else:
        lines.append("首次巡检，下周开始可以对比趋势。")

    lines += ["", "## 六、等人签字", ""]
    if r["hitl_backlog"]:
        lines += [f"- {p['where']}：{p['detail']}" for p in r["hitl_backlog"]]
    else:
        lines.append("无积压。")

    lines += ["", "## 七、下周建议", ""]
    recs = []
    if any(p["level"] == "anomaly" for p in r["problems"]):
        recs.append("门禁顺序倒挂 = 有阶段没真正过就跳到了下一步；要么补签，要么把那条 pass 改成 waived 并写明理由。")
    if r["hitl_backlog"]:
        recs.append("先把挂着的人工卡点清掉——它卡住的不止一个需求，是整条线的可信度。")
    if r["skills"]["pending"]:
        recs.append(f"补 1 个待建技能，优先 `{r['skills']['pending'][0]}`（被工作流直接引用，缺它就得手工做）。")
    if r["contracts"]["missing"]:
        recs.append(f"补契约 `{r['contracts']['missing'][0]}`，它挡着对应阶段没法自动验。")
    if r["knowledge"]["uncovered"]:
        recs.append("给未索引的知识文件补 chunk，否则 LLM 检索不到它们，等于白写。")
    recs.append("跑一次 `python tools/inspect.py` 对比上周分数，看是进步还是原地踏步。")
    lines += [f"{i}. {t}" for i, t in enumerate(recs, 1)]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    report = collect()
    md = render_md(report)

    s = report["summary"]
    print(f"巡检 {report['week']}　健康分 {s['score']}　门禁 {s['checks_passed']}/{s['checks_total']}　阻断 {s['block']}")
    for p in report["problems"][:12]:
        print(f"  [{p['level']}] {p['where']}: {p['detail']}")
    if len(report["problems"]) > 12:
        print(f"  …… 另有 {len(report['problems']) - 12} 条，见报告")

    if "--no-write" not in argv:
        out = ROOT / "runs" / "inspection" / report["week"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text(md, encoding="utf-8")
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告: {rel(out / 'report.md')}")

    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if s["block"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
