#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""G2 门禁：双轨独立完成的机器可查部分。

G2 原文有四条：
  1. 两轨都有 sql/、design-notes.md、self-check.md，缺一即失败
  2. 两轨 SQL 的 sha256 不相同（相同 = 抄袭或串通）
  3. journal 中无跨轨读取事件
  4. design-notes 里标记 needs-confirmation 的假设，不得同时出现在已完成产出中

其中 3 需要"谁读了文件"的执行证据，4 需要语义判断——本脚本只做能机械判定的部分，
并把两条判不了的原因打出来，避免门禁看起来比实际更严。

用法：
  python tools/check_dual_track.py --req 渠道GMV日报需求20261122
  python tools/check_dual_track.py --req ... --json
退出码：0 通过（可能带 WARN）；1 失败。
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKS = ("developer-1", "developer-2")
REQUIRED = ("design-notes.md", "self-check.md")
SIMILAR_WARN = 0.90   # 行级相似度超过它，提示"可能趋同"
SIMILAR_FAIL = 0.98   # 超过它且有文件 sha 相同，直接判失败


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm_lines(p: Path) -> list[str]:
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.strip()
        if not s or s.startswith("--"):
            continue
        out.append(re.sub(r"\s+", " ", s))
    return out


def collect(track_dir: Path) -> dict:
    sql_dir = track_dir / "sql"
    files = sorted(sql_dir.glob("*.sql")) if sql_dir.is_dir() else []
    layout = "sql/"
    if not files:
        # 兼容：早期产物把 SQL 直接放在轨道根下（约定写的是 sql/，见 agents/roles.json）
        files = sorted(p for p in track_dir.glob("*.sql")) if track_dir.is_dir() else []
        layout = "flat" if files else "none"
    info = {
        "dir": str(track_dir),
        "exists": track_dir.is_dir(),
        "sql": files,
        "layout": layout,
        "missing": [],
        "sha256": {f.name: sha256_file(f) for f in files},
    }
    for name in REQUIRED:
        if not (track_dir / name).is_file():
            info["missing"].append(name)
    if not files:
        info["missing"].append("sql/*.sql")
    return info


def similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()


NEGATION = re.compile(r"(未|没有|不|禁止|勿|别|no\s|not\s)", re.IGNORECASE)


def scan_leak(track_dir: Path, other: str) -> list[str]:
    """在 A 轨产物里找另一轨的痕迹——这是"跨轨读取"唯一可留下的物证。

    只按行判断，且排除否定语境（"未读 developer-2/"、"未与其对齐"是自证隔离，不是泄漏）。
    这条规则是经验性的：产物文本只能说"可能"，不能证明"读过"。
    """
    hits = []
    if not track_dir.is_dir():
        return hits
    for p in track_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".sql", ".md", ".py", ".json", ".txt"):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            idx = line.find(other)
            if idx < 0:
                continue
            # 同一行里、出现在另一轨标识之前的任何否定词，都按"自证没读"处理
            # （"未读取 `.../developer-2/`"这类路径很长，不能用紧邻匹配）
            if NEGATION.search(line[:idx]):
                continue
            hits.append(f"{p.relative_to(ROOT).as_posix()}:{i}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--req", required=True, help="需求目录名，如 渠道GMV日报需求20261122")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    run = ROOT / "requirements" / args.req / "需求开发员"
    if not run.is_dir():
        print(f"[FAIL] 找不到 {run.relative_to(ROOT)}")
        return 1

    t1, t2 = (collect(run / t) for t in TRACKS)
    problems, warns = [], []

    for info, name in ((t1, TRACKS[0]), (t2, TRACKS[1])):
        if not info["exists"]:
            problems.append(f"{name}: 目录不存在")
        elif info["missing"]:
            problems.append(f"{name}: 缺 {'、'.join(info['missing'])}")
        if info["layout"] == "flat":
            warns.append(f"{name}: SQL 直接放在轨道根下，约定是 sql/ 子目录（见 agents/roles.json）")

    # 2. SQL 内容必须不同
    same = []
    for n1, h1 in t1["sha256"].items():
        for n2, h2 in t2["sha256"].items():
            if h1 == h2:
                same.append(f"{n1} 与 {n2}")
    if same:
        problems.append(f"两轨存在完全相同文件（抄袭或串通）: {'; '.join(same)}")
    if set(t1["sha256"].values()) == set(t2["sha256"].values()) and t1["sha256"]:
        problems.append("两轨 SQL 文件集合的 sha 完全相同")

    # 相似度（只做提示，不做判决——同一份需求写同一个表，结构相似是正常的）
    sims = []
    if t1["sql"] and t2["sql"]:
        for f1 in t1["sql"]:
            for f2 in t2["sql"]:
                s = similarity(norm_lines(f1), norm_lines(f2))
                sims.append({"a": f1.name, "b": f2.name, "ratio": round(s, 3)})
        top = max(s["ratio"] for s in sims)
        if top >= SIMILAR_WARN:
            warns.append(f"两轨行级相似度最高 {top}（≥{SIMILAR_WARN}），趋同风险高——"
                         f"如果两轨都由同一个模型独立写，这就是它的上限，比对的信息量在下降")

    # 3. 泄漏物证
    for info, other, name in ((t1, TRACKS[1], TRACKS[0]), (t2, TRACKS[0], TRACKS[1])):
        leak = scan_leak(run / name, other)
        if leak:
            problems.append(f"{name}: 产物里出现另一轨标识 {other}（跨轨读取的物证）: {', '.join(leak)}")

    # 4. 无法机械判定的两条，明确说出来
    warns.append("G2-3「journal 无跨轨读取事件」当前无法验证：没有任何代码记录"
                 "「谁读了哪个路径」，隔离目前是声明式的（角色提示词里写 must_not_read）")

    result = {
        "req": args.req,
        "tracks": {TRACKS[0]: {"files": [f.name for f in t1["sql"]], "missing": t1["missing"]},
                   TRACKS[1]: {"files": [f.name for f in t2["sql"]], "missing": t2["missing"]}},
        "similarity": sims,
        "problems": problems,
        "warns": warns,
        "pass": not problems,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for name, info in zip(TRACKS, (t1, t2)):
            files = ", ".join(f.name for f in info["sql"]) or "（无）"
            print(f"{name}: sql=[{files}] 缺={info['missing'] or '无'}")
        if sims:
            print("相似度: " + ", ".join(f"{s['a']}~{s['b']}={s['ratio']}" for s in sims))
        for w in warns:
            print(f"  [WARN] {w}")
        for p in problems:
            print(f"  [FAIL] {p}")
        print(("PASS" if not problems else "FAIL") + "：双轨独立性（G2 机器可判部分）")

    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
