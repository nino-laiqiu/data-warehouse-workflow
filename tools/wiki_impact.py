#!/usr/bin/env python3
"""知识库变更的影响分析与变更登记。

规则（用户 m02256）：
  - **新增**：直接新增，不用分析。
  - **改老口径/改已有页面**：必须先跑影响分析，再登记到 knowledge/index.md（变了什么、什么时间）。
  - 没登记的改动视为"偷偷改口径"——`--check` 会拦住。

用法:
    python tools/wiki_impact.py --changed                 # 找出被改过的知识文件，列影响面
    python tools/wiki_impact.py --path knowledge/wiki/03-事实表.md
    python tools/wiki_impact.py --stamp --note "补了退款回冲说明"   # 更新指纹 + 写 index.md
    python tools/wiki_impact.py --check                   # CI/巡检用：有未登记改动就退出码 1

指纹存在 knowledge/index/chunks.jsonl 的 sha256 字段；人看的变更记录在 knowledge/index.md。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "knowledge"
CHUNKS = KB / "index" / "chunks.jsonl"
INDEX_MD = KB / "index.md"
# 会"引用知识"的地方——影响面就从这些地方找
REFS_ROOTS = ["knowledge", "requirements", "contracts", "docs", "tools", "flow", "agents"]
KB_SUFFIXES = {".md"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_chunks() -> list[dict]:
    if not CHUNKS.exists():
        return []
    out = []
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"[WARN] chunks.jsonl 有一行不是 JSON，已跳过: {line[:60]}")
    return out


def save_chunks(chunks: list[dict]) -> None:
    CHUNKS.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")



def is_meta(p: Path) -> bool:
    """knowledge/ 根下的 README.md 与 index.md 是导航页，不是知识条目，不参与指纹与影响分析。"""
    return p.parent == KB and p.name in {"README.md", "index.md"}


def knowledge_pages() -> list[Path]:
    return sorted(p for p in KB.rglob("*.md") if not is_meta(p))


def import_targets(path: Path) -> list[str]:
    """谁在 md 里链接到它（相对链接，按文件名兜底匹配）。"""
    hits = []
    for p in knowledge_pages():
        if p == path:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if f"({path.name})" in text or f"({path.name}#" in text:
            hits.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    return hits


def text_refs(rel: str) -> list[str]:
    """还有谁在正文/代码里提到这个知识文件（按 knowledge/ 路径匹配，不按文件名）。"""
    needles = {rel, "knowledge/" + rel, "knowledge\\" + rel}
    hits = []
    for root in REFS_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in {".md", ".json", ".py", ".yaml", ".yml", ".sql", ".txt"}:
                continue
            own = str(p.relative_to(ROOT)).replace("\\", "/")
            if own == "knowledge/" + rel:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(n in text for n in needles):
                hits.append(own)
    return sorted(set(hits))


def analyze(rel: str, chunk: dict | None) -> dict:
    path = KB / rel
    if chunk is None:
        status = "新增"
    elif not chunk.get("sha256"):
        status = "未建指纹"
    elif chunk["sha256"] == sha(path):
        status = "未变"
    else:
        status = "修改"
    return {
        "path": rel,
        "status": status,
        "chunk": chunk.get("id") if chunk else None,
        "title": (chunk or {}).get("title") or path.stem,
        "linked_by": import_targets(path),
        "referenced_by": text_refs(rel),
    }


def render(items: list[dict]) -> str:
    lines = []
    for it in items:
        icon = {"新增": "🟢", "修改": "🟠", "未建指纹": "🔵", "未变": "⚪"}[it["status"]]
        lines.append(f"{icon} {it['path']}　[{it['status']}]　{it['title']}")
        if it["status"] == "新增":
            lines.append("    新增 → 直接新增即可，不用影响分析（跑 --stamp 建指纹）")
            continue
        if it["status"] == "未建指纹":
            lines.append("    首次建指纹：--stamp 即可，不用写 note")
            continue
        if it["linked_by"]:
            lines.append(f"    被这些页面链接：{', '.join(it['linked_by'])}")
        if it["referenced_by"]:
            lines.append(f"    被这些文件引用：{', '.join(it['referenced_by'][:8])}"
                         + (" …" if len(it["referenced_by"]) > 8 else ""))
        if not it["linked_by"] and not it["referenced_by"]:
            lines.append("    没有其它文件引用它——影响面为零，但仍要登记变更")
        lines.append("    改的是老口径 → 必须 `--stamp --note \"变了什么\"`，否则 --check 会拦")
    return "\n".join(lines)


def append_index_note(items: list[dict], note: str) -> None:
    day = date.today().isoformat()
    rows = []
    for it in items:
        impact = ", ".join((it["linked_by"] + it["referenced_by"])[:5]) or "无引用"
        rows.append(f"| {day} | `{it['path']}` | {note} | {impact} | 人 |")
    text = INDEX_MD.read_text(encoding="utf-8") if INDEX_MD.exists() else "# 知识库索引\n\n## 变更记录\n\n| 日期 | 文档 | 变了什么 | 影响面 | 谁改的 |\n|---|---|---|---|---|\n"
    if "## 变更记录" not in text:
        text += "\n## 变更记录\n\n| 日期 | 文档 | 变了什么 | 影响面 | 谁改的 |\n|---|---|---|---|---|\n"
    text = text.rstrip() + "\n" + "\n".join(rows) + "\n"
    INDEX_MD.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    if "--help" in argv or not argv:
        print(__doc__)
        return 0
    chunks = load_chunks()
    by_path = {c.get("path", ""): c for c in chunks}

    def rel_of(p: Path) -> str:
        return str(p.relative_to(ROOT)).replace("\\", "/")[len("knowledge/"):]

    targets: list[Path] = []
    if "--path" in argv:
        for i, a in enumerate(argv):
            if a == "--path":
                p = Path(argv[i + 1])
                targets.append(p if p.is_absolute() else ROOT / p)
    elif "--stamp" in argv:
        for p in knowledge_pages():
            c = by_path.get(rel_of(p))
            if c is None or not c.get("sha256") or c["sha256"] != sha(p):
                targets.append(p)
    elif "--changed" in argv or "--check" in argv:
        for p in knowledge_pages():
            c = by_path.get(rel_of(p))
            if c and c.get("sha256") and c["sha256"] != sha(p):
                targets.append(p)
    if "--changed" not in argv and "--check" not in argv and "--stamp" not in argv and not targets:
        print("给一个 --path，或者用 --changed / --check / --stamp", file=sys.stderr)
        return 1

    items = [analyze(rel_of(p), by_path.get(rel_of(p))) for p in targets]

    if "--json" in argv:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        if items:
            print(render(items))
        elif "--stamp" in argv:
            print("没有要建指纹的文件。")
        else:
            print("没有发现未登记的改动（chunks 里都有指纹，说明没被改过）。")

    if "--check" in argv:
        if items:
            print(f"\n[FAIL] {len(items)} 个知识文件改过但没登记（先跑 --stamp --note \"变了什么\"）")
            return 1
        print("[OK  ] 知识库没有未登记的改动")
        return 0

    if "--stamp" in argv:
        note = argv[argv.index("--note") + 1] if "--note" in argv else ""
        new_files = [it for it in items if it["status"] == "新增"]
        changed = [it for it in items if it["status"] == "修改"]
        if changed and not note:
            print("[FAIL] 改的是已有内容，必须写 --note \"变了什么\"（会写进 knowledge/index.md）", file=sys.stderr)
            return 1
        next_id = max([int(c["id"].split("-")[1]) for c in chunks if c.get("id", "").startswith("k-")] or [0]) + 1
        for it in items:
            c = by_path.get(it["path"])
            if c is None:
                c = {"id": f"k-{next_id:04d}", "path": it["path"], "title": it["title"],
                     "tags": [], "verified_by": None}
                next_id += 1
                chunks.append(c)
                by_path[it["path"]] = c
            c["sha256"] = sha(ROOT / "knowledge" / it["path"])
            c["updated"] = date.today().isoformat()
        save_chunks(chunks)
        if note and (changed or new_files):
            append_index_note([i for i in items if i["status"] != "未变"] or items, note)
        print(f"已登记 {len(items)} 个文件（新增 {len(new_files)} / 修改 {len(changed)}）"
              + ("，并写入 knowledge/index.md" if note else ""))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
