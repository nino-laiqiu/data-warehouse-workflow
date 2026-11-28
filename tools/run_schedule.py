#!/usr/bin/env python3
"""定时任务执行器：读 flow/schedule.yaml，跑"现在该跑"的任务，并把结果留痕。

设计取的是"外面套一层"：仓库里只有一个零依赖的单命令执行器，
cron / Windows 任务计划程序 / DSH 定时 都只是调用它——换载体不用改代码。

用法:
    python tools/run_schedule.py --list            # 清单 + 上次结果
    python tools/run_schedule.py --due             # 只跑此刻到点的任务
    python tools/run_schedule.py --all             # 全部跑一遍（手动体检）
    python tools/run_schedule.py --task radar-daily --force
    python tools/run_schedule.py --due --dry-run   # 只说要跑什么，不真跑

结果落盘：runs/schedule/<YYYYMMDD-HHMMSS>.json 与 runs/schedule/index.jsonl
退出码：0 = 全部成功（含"没有到点的任务"）；1 = 有任务失败。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ontology" / "schema"))

SCHEDULE = ROOT / "flow" / "schedule.yaml"
OUT_DIR = ROOT / "runs" / "schedule"


def parse_cron(expr: str) -> dict:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron 必须是 5 段: {expr}")
    names = ["minute", "hour", "dom", "month", "dow"]
    return dict(zip(names, fields))


def field_match(spec: str, value: int) -> bool:
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part == "*":
            lo, hi = 0, 10 ** 9
        elif "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
        else:
            lo = hi = int(part)
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False


def due_now(cron: str, when: datetime) -> bool:
    c = parse_cron(cron)
    dow = (when.weekday() + 1) % 7  # 0 = 周日
    checks = [
        field_match(c["minute"], when.minute),
        field_match(c["hour"], when.hour),
        field_match(c["month"], when.month),
    ]
    dom_hit = field_match(c["dom"], when.day)
    dow_hit = field_match(c["dow"], dow)
    if c["dom"] != "*" and c["dow"] != "*":
        checks.append(dom_hit or dow_hit)
    else:
        checks.append(dom_hit and dow_hit)
    return all(checks)


def load() -> dict:
    import validate as v  # 复用本体校验器里的 YAML 子集解析器，避免第二套解析代码
    return v.parse_yaml(SCHEDULE.read_text(encoding="utf-8"))


def last_runs() -> dict:
    """每个 task 最近一次结果（读 index.jsonl，只留最后 200 行，够用且不爆内存）。"""
    idx = OUT_DIR / "index.jsonl"
    if not idx.exists():
        return {}
    lines = idx.read_text(encoding="utf-8").splitlines()[-200:]
    out = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        out[rec["task"]] = rec
    return out


def run_task(task: dict, dry: bool) -> dict:
    tid = task["id"]
    if task.get("status") == "manual":
        return {"task": tid, "skipped": "manual", "ok": True,
                "hint": task.get("on_result", ""), "command": task.get("command", "")}
    cmd = task["command"]
    if dry:
        return {"task": tid, "dry_run": True, "ok": True, "command": cmd}

    started = datetime.now().astimezone()
    proc = subprocess.run(cmd, cwd=str(ROOT), shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    dur = (datetime.now().astimezone() - started).total_seconds()
    ok_codes = {str(x) for x in task.get("ok_exit", [0])}
    ok = str(proc.returncode) in ok_codes
    rec = {
        "task": tid, "ts": started.isoformat(timespec="seconds"), "command": cmd,
        "exit": proc.returncode, "ok": ok, "duration_s": round(dur, 1),
        "stdout_tail": (proc.stdout or "").strip()[-1500:],
        "stderr_tail": (proc.stderr or "").strip()[-800:],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    (OUT_DIR / f"{stamp}-{tid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT_DIR / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"task": tid, "ts": rec["ts"], "exit": proc.returncode, "ok": ok,
                            "file": f"{stamp}-{tid}.json"}, ensure_ascii=False) + "\n")
    return rec


def main(argv: list[str]) -> int:
    if "--help" in argv or not argv:
        print(__doc__)
        return 0
    doc = load()
    tasks = doc.get("tasks", [])
    by_id = {t["id"]: t for t in tasks}
    last = last_runs()

    if "--list" in argv:
        print(f"共 {len(tasks)} 条任务（{doc.get('timezone', '?')}）\n")
        for t in tasks:
            prev = last.get(t["id"])
            when = f"上次 {prev['ts'][:16]} exit={prev['exit']} {'OK' if prev['ok'] else 'FAIL'}" if prev else "还没跑过"
            flag = "〔人工〕" if t.get("status") == "manual" else ""
            print(f"- {t['id']:<14}{t['cron']:<14}{flag}{t['name']}")
            print(f"  {t.get('description', '').strip()}")
            print(f"  {when}")
        return 0

    dry = "--dry-run" in argv
    now = datetime.now().astimezone()

    if "--task" in argv:
        tid = argv[argv.index("--task") + 1]
        if tid not in by_id:
            print(f"没有这个任务: {tid}", file=sys.stderr)
            return 1
        targets = [by_id[tid]]
    elif "--all" in argv:
        targets = tasks
    else:
        targets = [t for t in tasks if due_now(t["cron"], now)]
        if not targets:
            print(f"{now.strftime('%Y-%m-%d %H:%M')} 没有到点的任务（共 {len(tasks)} 条）")
            return 0

    print(f"执行 {len(targets)} 条任务 @ {now.isoformat(timespec='minutes')}" + ("（dry-run）" if dry else ""))
    failed = 0
    for t in targets:
        rec = run_task(t, dry)
        if rec.get("skipped") == "manual":
            print(f"  〔人工〕{t['id']}: 需人做——{rec.get('hint', '')}")
            continue
        if rec.get("dry_run"):
            print(f"  [DRY] {t['id']}: {rec['command']}")
            continue
        status = "OK" if rec["ok"] else "FAIL"
        print(f"  [{status}] {t['id']}　exit={rec['exit']}　{rec['duration_s']}s")
        if rec["stdout_tail"]:
            for line in rec["stdout_tail"].splitlines()[:4]:
                print(f"        {line[:110]}")
        if not rec["ok"]:
            failed += 1
            if rec["stderr_tail"]:
                print(f"        stderr: {rec['stderr_tail'].splitlines()[0][:110]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
