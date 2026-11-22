#!/usr/bin/env python3
"""sk-req-register 的门禁（G0）：对账 requirements/ 下的原始需求与登记簿。

    python skills/sk-req-register/validate.py
    python skills/sk-req-register/validate.py --json

只读，不修改任何文件。检查五件事：
  1. 每个 REQ-*.md 都在 <需求目录>/反馈者/ 下（不许平铺）
  2. 每个 REQ-*.md 都登记过
  3. 登记时的 sha256 与当前文件一致（发现原件被改）
  4. 登记簿里的路径都真实存在
  5. 模板五段与来源三要素齐全
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import register as reg  # noqa: E402  同目录复用模板检查与 hash 逻辑


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    root = reg.repo_root()
    inbox = root / reg.REQ_ROOT_REL
    registry_path = root / reg.REGISTRY_REL

    errors: list[str] = []
    warnings: list[str] = []

    if not inbox.exists():
        print(json.dumps({"ok": False, "errors": [f"目录不存在: {inbox}"]}, ensure_ascii=False, indent=2))
        return 1

    try:
        rows = reg.load_registry(registry_path)
    except SystemExit as e:
        print(json.dumps({"ok": False, "errors": [str(e)]}, ensure_ascii=False, indent=2))
        return 1

    by_path = {}
    for r in rows:
        missing = [k for k in ("req_id", "path", "sha256", "proposer", "channel", "submitted_at", "registered_at")
                   if not r.get(k)]
        if missing:
            errors.append(f"登记簿条目缺字段 {missing}: {r.get('req_id', '?')}")
        by_path[r.get("path")] = r

    files = []
    for p in sorted(inbox.rglob("REQ-*.md")):
        if not p.is_file():
            continue
        rel = p.resolve().relative_to(root.resolve()).as_posix()
        parts = p.relative_to(inbox).parts
        if parts[0] == "templates":
            continue                      # 模板不是需求
        if p.parent.name == "需求分析员":
            continue                      # 翻译稿不是原件，归 G1 管
        if p.parent.name != "反馈者":
            errors.append(f"目录不合规: {rel} —— 原始需求必须在 <需求目录>/反馈者/ 下，不允许平铺")
            continue
        if len(parts) != 3:
            errors.append(f"目录不合规: {rel} —— 原始需求必须在 <需求目录>/反馈者/ 下，不允许平铺")
            continue
        files.append(p)

    for f in files:
        rel = f.resolve().relative_to(root.resolve()).as_posix()
        row = by_path.get(rel)
        if not row:
            errors.append(f"未登记: {rel}（跑 register.py 登记后 G0 才过）")
            continue
        digest = reg.sha256_of(f)
        if digest != row.get("sha256"):
            errors.append(f"hash 不一致: {rel} —— 原件在登记后被修改过（登记 {row.get('sha256')[:12]}… 当前 {digest[:12]}…）")
        for e in reg.check_template(f.read_text(encoding="utf-8")):
            errors.append(f"{rel}: {e}")

    on_disk = {f.resolve().relative_to(root.resolve()).as_posix() for f in files}
    for rel in by_path:
        if rel not in on_disk:
            errors.append(f"登记了但文件不存在: {rel}（删了原件？不许删，用 withdrawn 标记）")

    summary = {"ok": not errors, "files": len(files), "registry_entries": len(rows),
               "errors": errors, "warnings": warnings}
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"检查 {len(files)} 个原始需求、{len(rows)} 条登记")
        for e in errors:
            print(f"  [FAIL] {e}")
        print("PASS：入库存档、目录布局与登记簿一致" if not errors else f"FAIL：{len(errors)} 个问题")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
