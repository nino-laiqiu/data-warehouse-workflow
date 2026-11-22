#!/usr/bin/env python
"""校验 wiki 内部链接：Markdown 里的相对链接必须指向真实存在的文件。

用法：
    python tools/check_wiki.py            # 检查 knowledge/wiki/
    python tools/check_wiki.py --all      # 检查仓库内所有 .md
    python tools/check_wiki.py --json     # 机器可读输出

设计取舍：
- 只校验相对路径链接（http/https/mailto/#锚点 跳过）。
- 代码块里的内容不解析，避免把 SQL 里的方括号当链接。
- 链接里的 #anchor 与 :行号 后缀忽略，只校验文件是否存在。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "knowledge" / "wiki"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE_RE = re.compile(r"```.*?```", re.S)


def strip_fences(text: str) -> str:
    return FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def check_file(md: Path) -> tuple[int, list[str]]:
    raw = md.read_text(encoding="utf-8")
    text = strip_fences(raw)
    checked = 0
    errors: list[str] = []
    for m in LINK_RE.finditer(text):
        target = m.group(1).strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
            continue
        # 去掉 anchor 与行号后缀
        path_part = target.split("#")[0]
        if path_part.endswith(".md") is False and ":" in path_part:
            path_part = path_part.split(":")[0]
        if not path_part:
            continue
        checked += 1
        resolved = (md.parent / path_part).resolve()
        if not resolved.exists():
            errors.append(f"{md.relative_to(ROOT)} -> {target}（目标不存在）")
    return checked, errors


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    targets = (
        sorted(ROOT.rglob("*.md"))
        if "--all" in argv
        else sorted(WIKI.rglob("*.md"))
    )
    # 排除依赖目录与临时目录
    targets = [p for p in targets if not {".tmp", "node_modules", ".git"} & set(p.parts)]

    if not targets:
        print("没有找到 Markdown 文件", file=sys.stderr)
        return 1

    total_links = 0
    all_errors: list[str] = []
    for md in targets:
        checked, errors = check_file(md)
        total_links += checked
        all_errors.extend(errors)

    if as_json:
        print(json.dumps(
            {"files": len(targets), "links": total_links, "ok": not all_errors, "errors": all_errors},
            ensure_ascii=False, indent=2,
        ))
        return 0 if not all_errors else 1

    print(f"检查 {len(targets)} 个文件、{total_links} 条相对链接")
    if all_errors:
        print(f"FAIL：{len(all_errors)} 条链接失效")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    print("PASS：所有相对链接均可解析")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
