#!/usr/bin/env python3
"""检查需求目录布局（G0/G1 的伴随门禁，防"又平铺回大目录"）。

    python tools/check_layout.py
    python tools/check_layout.py --json

约定：一个需求 = 一个目录名（<短名>需求<YYYYMMDD>），在三个角色目录下同名出现。

    requirements/反馈者/画像标签需求20261122/REQ-20261122-02.md
    requirements/需求分析员/画像标签需求20261122/REQ-20261122-02.md
    requirements/需求开发员/画像标签需求20261122/{developer-1,developer-2,监督者,journal.jsonl}

拦的是六类问题：
  1. REQ 文件平铺在角色目录或 requirements/ 根下
  2. 目录名不合规（缺"需求YYYYMMDD"或用了空格/标点）
  3. 登记簿里的路径不存在，或 requirement_dir 与所在目录不符
  4. 有原件但没有翻译稿
  5. 开了开发目录但缺 developer-1/developer-2/监督者/journal
  6. 角色目录下出现没被任何需求引用的孤儿目录

纯标准库，只读。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ_ROOT = ROOT / "requirements"
ROLES = ["反馈者", "需求分析员", "需求开发员"]
REGISTRY_REL = "requirements/反馈者/_registry.jsonl"
REQ_DIR_RE = re.compile(r"^[^\s/\\*?:<>|\"]+需求(\d{8})$")
REQ_ID_RE = re.compile(r"^REQ-(\d{8})-(\d{2})(?:-v(\d+))?$")


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    errors: list[str] = []
    warnings: list[str] = []

    registry = ROOT / REGISTRY_REL
    if not registry.exists():
        errors.append(f"登记簿不存在: {REGISTRY_REL}")
        rows = []
    else:
        rows = [json.loads(x) for x in registry.read_text(encoding="utf-8").splitlines() if x.strip()]

    # 1. 登记簿与磁盘对账
    dirs_by_req: dict[str, str] = {}
    for r in rows:
        req_id = r.get("req_id", "?")
        path = r.get("path")
        req_dir = r.get("requirement_dir")
        if not path:
            errors.append(f"[{req_id}] 登记条目缺 path")
            continue
        p = ROOT / path
        if not p.exists():
            errors.append(f"[{req_id}] 登记路径不存在: {path}")
            continue
        actual_dir = p.parent.name
        if req_dir and req_dir != actual_dir:
            errors.append(f"[{req_id}] requirement_dir={req_dir} 与实际目录 {actual_dir} 不一致")
        if not REQ_DIR_RE.fullmatch(actual_dir):
            errors.append(f"[{req_id}] 需求目录名不合规: {actual_dir}")
        else:
            d = REQ_DIR_RE.fullmatch(actual_dir).group(1)
            if not req_id.startswith(f"REQ-{d}-"):
                errors.append(f"[{req_id}] 目录日期 {d} 与需求编号日期不一致")
        dirs_by_req[req_id] = actual_dir

        # 4. 有原件必须有翻译稿
        if not (REQ_ROOT / "需求分析员" / actual_dir / f"{req_id}.md").exists():
            errors.append(f"[{req_id}] 缺翻译稿: requirements/需求分析员/{actual_dir}/{req_id}.md")

        # 5. 开发目录一旦开了，结构必须齐全
        dev = REQ_ROOT / "需求开发员" / actual_dir
        if dev.exists():
            for need in ("developer-1", "developer-2", "监督者"):
                if not (dev / need).exists():
                    errors.append(f"[{req_id}] 开发目录缺 {need}/: {dev.relative_to(ROOT).as_posix()}")
            if not (dev / "journal.jsonl").exists():
                errors.append(f"[{req_id}] 开发目录缺 journal.jsonl（追踪者的账本）")

    # 2. 三个角色目录下的子目录命名
    known_dirs = set(dirs_by_req.values())
    for role in ROLES:
        role_path = REQ_ROOT / role
        if not role_path.exists():
            errors.append(f"缺角色目录: requirements/{role}/")
            continue
        for d in sorted(p for p in role_path.iterdir() if p.is_dir()):
            if not REQ_DIR_RE.fullmatch(d.name):
                errors.append(f"目录名不合规: requirements/{role}/{d.name}（应为「<短名>需求<YYYYMMDD>」）")
                continue
            if d.name not in known_dirs:
                warnings.append(f"孤儿目录（还没有登记的需求）: requirements/{role}/{d.name}")

    # 3. 平铺的 REQ 文件
    for f in REQ_ROOT.rglob("REQ-*.md"):
        rel = f.relative_to(ROOT).as_posix()
        parts = f.relative_to(REQ_ROOT).parts
        if parts[0] == "templates":
            continue  # 模板不是需求
        if len(parts) != 3 or parts[0] not in ROLES:
            errors.append(f"REQ 文件位置不合规: {rel}（必须 requirements/<角色>/<需求目录>/REQ-*.md）")
            continue
        if not REQ_ID_RE.fullmatch(f.stem):
            errors.append(f"REQ 文件名不合规: {rel}")
        if parts[1] not in known_dirs:
            warnings.append(f"未登记目录下的 REQ 文件: {rel}")

    summary = {
        "ok": not errors,
        "requirements": len(rows),
        "role_dirs": {r: len([p for p in (REQ_ROOT / r).iterdir() if p.is_dir()]) if (REQ_ROOT / r).exists() else 0
                      for r in ROLES},
        "errors": errors,
        "warnings": warnings,
    }
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"检查 {len(rows)} 个需求；角色目录子目录数 {summary['role_dirs']}")
        for w in warnings:
            print(f"  [WARN] {w}")
        for e in errors:
            print(f"  [FAIL] {e}")
        print("PASS：需求目录布局合规" if not errors else f"FAIL：{len(errors)} 个问题")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
