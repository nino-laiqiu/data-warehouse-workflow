#!/usr/bin/env python3
"""需求分析员的对话式翻译：草稿 → 逐条问答 → 轮次 → 确认。

    python tools/req_review.py init   --req-id REQ-20261122-02 --draft
    python tools/req_review.py ask    --req-id REQ-20261122-02 --id Q1 --text "「未购」是终身态还是近30天？"
    python tools/req_review.py answer --req-id REQ-20261122-02 --id Q1 --text "终身态，只认有没有付过款"
    python tools/req_review.py round  --req-id REQ-20261122-02 --note "第 1 轮：补了时间窗定义"
    python tools/req_review.py confirm --req-id REQ-20261122-02
    python tools/req_review.py status --req-id REQ-20261122-02
    python tools/req_review.py check  --req-id REQ-20261122-02
    python tools/req_review.py list

状态机：draft（初稿，没人看过）→ review（在对话中）→ confirmed（可交付）。
规则只有一条硬的：**还有未回答的阻断问题，就不许 confirm**。

状态文件：requirements/<需求目录>/需求分析员/_review/<REQ>.json
纯标准库、只读除状态文件外不碰别的。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ_ROOT = ROOT / "requirements"
REQ_ID_RE = re.compile(r"^REQ-(\d{8})-(\d{2})(?:-v(\d+))?$")
STATUSES = ("draft", "review", "confirmed")


def now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def req_dir(req_id: str) -> Path:
    """按登记簿定位需求目录；登记簿找不到才按日期猜（多个候选就报错）。"""
    m = REQ_ID_RE.match(req_id)
    if not m:
        raise SystemExit(f"需求编号不合规: {req_id}（应形如 REQ-20261122-02）")
    reg = ROOT / "requirements" / "_registry.jsonl"
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("req_id") == req_id and row.get("requirement_dir"):
                d = REQ_ROOT / row["requirement_dir"]
                if d.exists():
                    return d
    date = m.group(1)
    hits = [d for d in REQ_ROOT.iterdir() if d.is_dir() and d.name.endswith(date)
            and (d / "反馈者").exists()]
    if len(hits) != 1:
        raise SystemExit(f"按日期 {date} 找到 {len(hits)} 个需求目录，无法定位: "
                         + ", ".join(sorted(h.name for h in hits)))
    return hits[0]


def state_path(req_id: str) -> Path:
    return req_dir(req_id) / "需求分析员" / "_review" / f"{req_id}.json"


def load(req_id: str) -> dict:
    p = state_path(req_id)
    if not p.exists():
        raise SystemExit(f"没有审阅状态文件: {p.relative_to(ROOT).as_posix()}\n先跑 init")
    return json.loads(p.read_text(encoding="utf-8"))


def save(req_id: str, st: dict) -> Path:
    p = state_path(req_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = now()
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


# ---------- 命令 ----------

def cmd_init(a: dict) -> int:
    req_id = a["--req-id"]
    d = req_dir(req_id)
    doc = d / "需求分析员" / f"{req_id}.md"
    p = state_path(req_id)
    if p.exists() and "--force" not in a:
        print(f"已存在: {rel(p)}（要重置加 --force）")
        return 1
    st = {
        "requirement_id": req_id,
        "doc": rel(doc) if doc.exists() else None,
        "status": "draft",
        "round": 0,
        "questions": [],
        "rounds": [],
        "created": now(),
        "updated": now(),
    }
    save(req_id, st)
    print(f"初始化 {req_id} → draft（{rel(p)}）")
    return 0


def cmd_ask(a: dict) -> int:
    req_id, qid, text = a["--req-id"], a["--id"], a["--text"]
    if not re.fullmatch(r"Q\d{1,3}", qid):
        print(f"问题编号应形如 Q1: {qid}", file=sys.stderr)
        return 2
    st = load(req_id)
    if any(q["id"] == qid for q in st["questions"]):
        print(f"{qid} 已存在", file=sys.stderr)
        return 1
    st["questions"].append({
        "id": qid,
        "text": text,
        "blocking": "--non-blocking" not in a,
        "answer": "",
        "answered_by": "",
        "answered_at": "",
        "asked_at": now(),
    })
    if st["status"] == "draft":
        st["status"] = "review"
    save(req_id, st)
    print(f"+ {qid} {'[阻断]' if '--non-blocking' not in a else '[非阻断]'} {text}")
    return 0


def cmd_answer(a: dict) -> int:
    st0 = load(a['--req-id'])
    if st0.get('status') == 'confirmed':
        print('已确认的需求不能直接改答案——先 reopen 回到复核态，改完再 confirm。', file=sys.stderr)
        return 1
    req_id, qid, text = a["--req-id"], a["--id"], a["--text"]
    st = load(req_id)
    q = next((x for x in st["questions"] if x["id"] == qid), None)
    if not q:
        print(f"没有 {qid}", file=sys.stderr)
        return 1
    q["answer"] = text
    q["answered_by"] = a.get("--by", "nino")
    q["answered_at"] = now()
    save(req_id, st)
    print(f"= {qid} ← {text}")
    return 0


def cmd_round(a: dict) -> int:
    req_id = a["--req-id"]
    st = load(req_id)
    open_q = [q["id"] for q in st["questions"] if q["blocking"] and not q["answer"]]
    st["round"] = int(st["round"]) + 1
    st["rounds"].append({
        "no": st["round"],
        "at": now(),
        "by": a.get("--by", "nino"),
        "note": a.get("--note", ""),
        "open_blocking": open_q,
    })
    save(req_id, st)
    left = f"，仍有 {len(open_q)} 个阻断问题未答" if open_q else "，阻断问题已清零"
    print(f"第 {st['round']} 轮记录完成{left}")
    return 0


def cmd_promote(a: dict) -> int:
    """把 _draft/<REQ>.md 提升为正式翻译稿位置。"""
    req_id = a["--req-id"]
    st = load(req_id)
    d = req_dir(req_id)
    draft = d / "需求分析员" / "_draft" / f"{req_id}.md"
    target = d / "需求分析员" / f"{req_id}.md"
    if not draft.exists():
        print(f"没有草案: {rel(draft)}", file=sys.stderr)
        return 1
    if target.exists():
        hist = d / "需求分析员" / "_history"
        hist.mkdir(parents=True, exist_ok=True)
        n = len(list(hist.glob(f"{req_id}-v*.md"))) + 1
        backup = hist / f"{req_id}-v{n}.md"
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"旧稿已留档: {rel(backup)}")
    target.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
    st["doc"] = rel(target)
    st.setdefault("history", []).append({"at": now(), "event": "promote", "note": rel(draft)})
    save(req_id, st)
    print(f"草案 → 正式位置: {rel(target)}")
    return 0


def cmd_confirm(a: dict) -> int:
    req_id = a["--req-id"]
    st = load(req_id)
    open_q = [q["id"] for q in st["questions"] if q["blocking"] and not q["answer"]]
    if open_q:
        print(f"不许确认：还有 {len(open_q)} 个阻断问题未回答（{', '.join(open_q)}）",
              file=sys.stderr)
        return 1
    if int(st["round"]) < 1:
        print("不许确认：至少走完 1 轮对话（round）", file=sys.stderr)
        return 1
    st["status"] = "confirmed"
    st["confirmed_at"] = now()
    save(req_id, st)
    print(f"确认 {req_id}：可交付（G1 会按正式稿校验）")
    return 0


def cmd_reopen(a: dict) -> int:
    req_id = a["--req-id"]
    st = load(req_id)
    st["status"] = "review"
    st.setdefault("history", []).append({"at": now(), "event": "reopen", "note": a.get("--note", "")})
    save(req_id, st)
    print(f"{req_id} 重新进入 review（--note 建议写清为什么要复核）")
    return 0


def cmd_status(a: dict) -> int:
    for req_id in ([a["--req-id"]] if "--req-id" in a else []):
        print(json.dumps(summary(load(req_id)), ensure_ascii=False, indent=2))
    return 0


def cmd_list(a: dict) -> int:
    rows = []
    for d in sorted(REQ_ROOT.iterdir()) if REQ_ROOT.exists() else []:
        rd = d / "需求分析员" / "_review"
        if not rd.exists():
            continue
        for f in sorted(rd.glob("*.json")):
            rows.append(summary(json.loads(f.read_text(encoding="utf-8"))))
    if not rows:
        print("没有审阅状态文件")
        return 0
    print(f"{'需求编号':<16}{'状态':<11}{'轮次':<5}{'未答阻断':<9}文档")
    for r in rows:
        print(f"{r['requirement_id']:<16}{r['status']:<11}{r['round']:<5}"
              f"{len(r['open_blocking']):<9}{r['doc'] or '（无）'}")
    return 0


def cmd_check(a: dict) -> int:
    req_id = a["--req-id"]
    st = load(req_id)
    errs = []
    if st.get("status") not in STATUSES:
        errs.append(f"status 非法: {st.get('status')}")
    doc = st.get("doc")
    if doc and not (ROOT / doc).exists():
        errs.append(f"文档不存在: {doc}")
    if not doc:
        errs.append("还没有指向翻译稿（init 时文档不存在，写完后重跑 init --force 或手工填 doc）")
    if st.get("status") == "confirmed":
        open_q = [q["id"] for q in st["questions"] if q["blocking"] and not q["answer"]]
        if open_q:
            errs.append(f"已确认但仍有未答阻断问题: {', '.join(open_q)}")
        if int(st.get("round", 0)) < 1:
            errs.append("已确认但没走过任何一轮对话")
    ids = [q["id"] for q in st["questions"]]
    if len(ids) != len(set(ids)):
        errs.append("问题编号重复")
    if errs:
        for e in errs:
            print(f"  [FAIL] {e}")
        print(f"FAIL：{len(errs)} 个问题")
        return 1
    s = summary(st)
    print(f"PASS：{req_id} status={s['status']} round={s['round']} "
          f"问题 {s['questions']} 个（未答阻断 {len(s['open_blocking'])}）")
    return 0


def summary(st: dict) -> dict:
    open_blocking = [q["id"] for q in st["questions"] if q["blocking"] and not q["answer"]]
    return {
        "requirement_id": st["requirement_id"],
        "status": st["status"],
        "round": int(st.get("round", 0)),
        "doc": st.get("doc"),
        "questions": len(st["questions"]),
        "open_blocking": open_blocking,
        "unanswered_nonblocking": [q["id"] for q in st["questions"]
                                   if not q["blocking"] and not q["answer"]],
        "updated": st.get("updated"),
    }


def parse_args(rest: list[str]) -> dict:
    """把 --k v / --flag 解析成 dict，flag 记 True。"""
    out: dict = {}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("--"):
            nxt = rest[i + 1] if i + 1 < len(rest) else None
            if nxt is not None and not nxt.startswith("--"):
                out[tok] = nxt
                i += 2
            else:
                out[tok] = True
                i += 1
        else:
            i += 1
    return out


COMMANDS = {
    "init": cmd_init, "ask": cmd_ask, "answer": cmd_answer, "round": cmd_round,
    "promote": cmd_promote,
    "confirm": cmd_confirm, "reopen": cmd_reopen, "status": cmd_status,
    "list": cmd_list, "check": cmd_check,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    a = parse_args(rest)
    try:
        return COMMANDS[cmd](a)
    except KeyError as e:
        print(f"缺参数: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
