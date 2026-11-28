#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
chat.py —— 对话界面的 P1 最小实现（CLI + 可选 HTTP）。

四个动作与 docs/对话界面.md 的端点一一对应：

    chat    <问题>                               POST /v1/chat
    review  answer --req-id .. --id Q1 --text .. POST /v1/review/{req_id}/answer
    journal --run R-xxxx [--type gate]           GET  /v1/run/{run_id}/journal
    task    --role developer-1 --req <需求目录>   POST /v1/task

设计取舍（写在代码里，避免以后有人"顺手"改成更聪明的样子）：

1. **不用 LLM**。规则引擎能答就答，答不了就明说"暂不支持"——编一个看起来合理的 SQL
   比报错危险得多。`caveats` 里会写清楚这一轮是规则命中，不是模型生成。
2. **SQL 必须可见**。分析师看不到 SQL 的答案不可信，所以 answer 里带 sql。
3. **每轮问答落 qa_record**。走 tools/qa_store.py，断了不影响回答（写不进去只警告）。
4. **不改任何东西**。review/task 只是转发到既有脚本；chat 只读不写。

用法：
    python tools/chat.py chat "近30天各渠道GMV"
    python tools/chat.py chat "最近一周城市等级维度的支付用户数"
    python tools/chat.py review answer --req-id REQ-20261122-02 --id Q1 --text "终身" --by 需求方
    python tools/chat.py journal --run R-20261128-110000 --type gate
    python tools/chat.py task --role developer-1 --req 画像标签需求20261122 --stage P2
    python tools/chat.py serve --port 8765          # 暴露同样四个端点
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# ---------------------------------------------------------------- 规则表
# 只写"能确定答对"的：指标 × 维度。没写的组合一律拒绝，不猜。

METRICS = {
    "GMV": {
        "keywords": ["gmv", "成交额", "交易额", "销售额", "支付金额"],
        "table": "dwd_pay_flow_di",
        "expr": "SUM(p.{col})",
        "col": "pay_amt",
        "desc": "按支付时间统计的成交金额（不含运费，退款不回冲）",
        "ontology": "GMV",
    },
    "ORDER_CNT": {
        "keywords": ["订单数", "订单量", "多少单"],
        "table": "dwd_order_main_di",
        "expr": "COUNT(DISTINCT p.order_id)",
        "col": None,
        "desc": "支付成功的订单数（订单粒度去重）",
        "ontology": "ORDER_CNT",
    },
    "PAY_USER_CNT": {
        "keywords": ["支付用户数", "付款人数", "买家数", "用户数"],
        "table": "dwd_pay_flow_di",
        "expr": "COUNT(DISTINCT p.user_id)",
        "col": None,
        "desc": "有支付行为的去重用户数",
        "ontology": "USER",
    },
}

DIMS = {
    "渠道": {
        "keywords": ["渠道"],
        "join": "LEFT JOIN dim_channel_df d ON d.channel_code = p.channel_code AND d.dt = '${dt}'",
        "value": "d.channel_name",
        "desc": "渠道（app / 小程序 / h5 / pc）",
    },
    "城市等级": {
        "keywords": ["城市等级", "城市线级", "几线城市"],
        "join": "LEFT JOIN dim_user_df d ON d.user_id = p.user_id AND d.dt = '${dt}' AND d.is_current = 1",
        "value": "NVL(d.city_level, 'UNKNOWN')",
        "desc": "用户注册地城市等级",
    },
    "日期": {
        "keywords": ["每天", "按天", "每日", "趋势"],
        "join": None,
        "value": "p.dt",
        "desc": "按支付日期",
    },
}

WINDOWS = [
    (r"(近|最近|过去)\s*7\s*天|一周|最近一周", 7, "近 7 天"),
    (r"(近|最近|过去)\s*30\s*天|一个月|上个月|上月|最近一个月", 30, "近 30 天"),
    (r"(近|最近|过去)\s*90\s*天|三个月|一季度", 90, "近 90 天"),
]

FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|MERGE)\b", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_id() -> str:
    return "R-" + datetime.now().strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- 解析
def parse_question(q: str) -> dict:
    low = q.lower()
    metric = None
    for name, spec in METRICS.items():
        if any(k in low for k in spec["keywords"]):
            metric = name
            break

    dim = None
    for name, spec in DIMS.items():
        if any(k in low for k in spec["keywords"]):
            dim = name
            break

    days, window_desc = 30, "近 30 天（默认）"
    for pattern, d, desc in WINDOWS:
        if re.search(pattern, q):
            days, window_desc = d, desc
            break

    return {"metric": metric, "dim": dim, "days": days, "window": window_desc}


def build_sql(parsed: dict) -> str:
    m = METRICS[parsed["metric"]]
    d = DIMS[parsed["dim"]]
    measure = m["expr"].format(col=m["col"])
    join = (d["join"] + "\n") if d["join"] else ""
    return (
        "SELECT\n"
        f"  {d['value']} AS dim_value,\n"
        f"  {measure} AS metric_value\n"
        f"FROM {m['table']} p\n"
        f"{join}"
        f"WHERE p.dt BETWEEN date_sub('${{dt}}', {parsed['days']}) AND date_sub('${{dt}}', 1)\n"
        f"GROUP BY {d['value']}\n"
        "ORDER BY metric_value DESC\n"
        "LIMIT 2000"
    )


def guard_sql(sql: str) -> list:
    """A 线的五条护栏，AST 级检查要等 sk-sql-guard，这里先做能确定拦住的部分。"""
    problems = []
    body = sql.strip()
    if not re.match(r"^(SELECT|WITH)\b", body, re.I):
        problems.append("不是只读查询（必须以 SELECT/WITH 开头）")
    if "${dt}" not in body:
        problems.append("没有 dt 过滤（扫描全表）")
    if re.search(r"SELECT\s+\*", body, re.I):
        problems.append("用了 SELECT *")
    if len(re.findall(r"\bJOIN\b", body, re.I)) > 3:
        problems.append("JOIN 超过 3 个")
    if "LIMIT" not in body.upper():
        problems.append("没有 LIMIT")
    if FORBIDDEN.search(body):
        problems.append("含写操作关键字")
    return problems


# ---------------------------------------------------------------- 四个动作
def act_chat(question: str) -> dict:
    rid = run_id()
    parsed = parse_question(question)
    caveats = [f"引擎：规则匹配（非 LLM 生成）", f"时间窗：{parsed['window']}"]

    if not parsed["metric"]:
        return _refuse(rid, question,
                       "没识别出指标（支持：" + "、".join(k for s in METRICS.values() for k in s["keywords"][:3]) + "）",
                       caveats)
    if not parsed["dim"]:
        return _refuse(rid, question,
                       "没识别出维度（支持：渠道 / 城市等级 / 按天）", caveats)

    sql = build_sql(parsed)
    problems = guard_sql(sql)
    if problems:
        return _refuse(rid, question, "生成的 SQL 没过护栏：" + "；".join(problems), caveats)

    m, d = METRICS[parsed["metric"]], DIMS[parsed["dim"]]
    answer = (
        f"{parsed['window']}、按「{d['desc']}」拆分的 {parsed['metric']}。\n"
        f"口径：{m['desc']}（本体 {m['ontology']}）。\n"
        f"表：{m['table']}，时间窗 [dt-{parsed['days']}, dt-1]，不含当天。"
    )
    caveats.append("结果未执行：CLI 只生成 SQL，执行请走集群或 A3 之后的链路")
    if parsed.get("dim") == "城市等级":
        caveats.append("城市等级取的是 dim_user_df.city_level（注册地），不是收货地址——测试期口径，见 T-20261128-02")

    record = {
        "qa_id": f"Q{datetime.now():%Y%m%d}-{int(datetime.now().timestamp()) % 10000:04d}",
        "ts": now_iso(),
        "session_id": "cli-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
        "turn_no": 1,
        "question": question,
        "answer": answer,
        "sql_text": sql,
        "intent": "取数",
        "tables": sorted({m["table"]} | ({"dim_channel_df"} if parsed["dim"] == "渠道" else
                                        {"dim_user_df"} if parsed["dim"] == "城市等级" else set())),
        "user_hash": hashlib.sha256(b"cli:anonymous").hexdigest()[:16],
        "model": "rules-v0",
    }
    saved = _save_qa(record)
    if not saved:
        caveats.append("问答未入库（qa_store 不可用），不影响本次回答")

    return {"run_id": rid, "question": question, "answer": answer, "sql": sql,
            "caveats": caveats, "refused": False}


def _refuse(rid: str, question: str, why: str, caveats: list) -> dict:
    """答不了就明说。宁可不答，也不能编一条看起来对的 SQL。"""
    return {
        "run_id": rid,
        "question": question,
        "answer": f"这条我答不了：{why}。\n换个问法，或把口径补进本体后再问。",
        "sql": None,
        "caveats": caveats + ["未生成 SQL：不确定的答案不生成"],
        "refused": True,
    }


def _save_qa(record: dict) -> bool:
    try:
        tmp = ROOT / ".tmp" / "chat_qa.jsonl"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        r = subprocess.run([PY, str(ROOT / "tools" / "qa_store.py"), "ingest", "--file", str(tmp)],
                           capture_output=True, text=True, encoding="utf-8")
        return r.returncode == 0
    except Exception:
        return False


def act_review_answer(req_id: str, qa_id: str, text: str, by: str) -> dict:
    cmd = [PY, str(ROOT / "tools" / "req_review.py"), "answer",
           "--req-id", req_id, "--id", qa_id, "--text", text, "--by", by]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "").strip()
    status = subprocess.run([PY, str(ROOT / "tools" / "req_review.py"), "status", "--req-id", req_id],
                            capture_output=True, text=True, encoding="utf-8")
    try:
        st = json.loads(status.stdout)
    except Exception:
        st = {}
    return {"ok": r.returncode == 0, "detail": out or (r.stderr or "").strip(),
            "open_blocking": st.get("open_blocking", []), "status": st.get("status")}


def act_journal(run_id_: str, type_: str | None) -> dict:
    """journal 只读：界面能看见状态，但不能改状态。"""
    files = sorted(ROOT.glob("requirements/*/需求开发员/journal.jsonl"))
    events = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if type_ and e.get("type") != type_:
                continue
            events.append(e)
    return {"run_id": run_id_, "count": len(events), "events": events[-50:]}


def act_task(role: str, req: str, stage: str) -> dict:
    cmd = [PY, str(ROOT / "tools" / "role_prompt.py"), "--role", role, "--req", req, "--write"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    prompt_path = None
    if r.returncode == 0:
        cands = sorted((ROOT / "requirements" / req / "需求开发员" / "prompts").glob(f"{role}.md"))
        prompt_path = str(cands[0].relative_to(ROOT)) if cands else None
    return {"ok": r.returncode == 0, "role": role, "stage": stage,
            "prompt_path": prompt_path,
            "detail": (r.stdout or r.stderr or "").strip()[:400]}


# ---------------------------------------------------------------- HTTP
def serve(port: int) -> int:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

        def do_POST(self):
            try:
                data = self._body()
                if self.path == "/v1/chat":
                    self._send(200, act_chat(data.get("question", "")))
                elif self.path.startswith("/v1/review/") and self.path.endswith("/answer"):
                    req_id = self.path.split("/")[3]
                    self._send(200, act_review_answer(req_id, data["qa_id"], data["text"], data.get("by", "需求方")))
                elif self.path == "/v1/task":
                    self._send(200, act_task(data["role"], data["req_id"], data.get("stage", "")))
                else:
                    self._send(404, {"error": "unknown endpoint"})
            except Exception as exc:  # 界面不能因为一个坏请求挂掉
                self._send(400, {"error": str(exc)})

        def do_GET(self):
            if self.path.startswith("/v1/run/"):
                rid = self.path.split("/")[3].split("?")[0]
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                self._send(200, act_journal(rid, (qs.get("type") or [None])[0]))
            else:
                self._send(404, {"error": "unknown endpoint"})

        def log_message(self, fmt, *args):
            pass

    print(f"对话界面正跑在 http://127.0.0.1:{port}（端点见 docs/对话界面.md）")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
    return 0


# ---------------------------------------------------------------- CLI
def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="对话界面 P1：chat / review / journal / task / serve")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chat", help="POST /v1/chat")
    c.add_argument("question")
    c.add_argument("--json", action="store_true")

    rv = sub.add_parser("review", help="POST /v1/review/{req}/answer")
    rv_sub = rv.add_subparsers(dest="action", required=True)
    ans = rv_sub.add_parser("answer")
    ans.add_argument("--req-id", required=True)
    ans.add_argument("--id", required=True)
    ans.add_argument("--text", required=True)
    ans.add_argument("--by", default="需求方")

    j = sub.add_parser("journal", help="GET /v1/run/{run}/journal")
    j.add_argument("--run", default="")
    j.add_argument("--type", choices=["conversation", "query", "artifact", "progress", "todo", "gate"])

    t = sub.add_parser("task", help="POST /v1/task")
    t.add_argument("--role", required=True)
    t.add_argument("--req", required=True)
    t.add_argument("--stage", default="")

    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)

    a = ap.parse_args(argv)

    if a.cmd == "serve":
        return serve(a.port)

    if a.cmd == "chat":
        res = act_chat(a.question)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"问：{res['question']}\n")
            print(res["answer"])
            if res["sql"]:
                print("\n--- SQL ---\n" + res["sql"])
            print("\n[提醒]")
            for x in res["caveats"]:
                print("  - " + x)
        return 0 if not res["refused"] else 3

    if a.cmd == "review":
        res = act_review_answer(a.req_id, a.id, a.text, a.by)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    if a.cmd == "journal":
        res = act_journal(a.run, a.type)
        print(f"{res['count']} 条事件" + (f"（最近 {len(res['events'])} 条）" if res["count"] else ""))
        for e in res["events"]:
            print(f"  {e.get('ts','')[:19]}  {e.get('type'):<12} {e.get('actor','')}")
        return 0

    if a.cmd == "task":
        res = act_task(a.role, a.req, a.stage)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
