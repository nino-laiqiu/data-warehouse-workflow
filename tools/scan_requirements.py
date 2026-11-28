#!/usr/bin/env python3
"""需求雷达：扫描原始需求文档目录，发现新增/变更的文档，提醒是否需要开发。

它只做"发现"，不做"翻译"——翻译由 P1 的需求翻译者负责。
扫描状态记在 需求池/_scan_state.json（记录每个文件的 sha256），所以重复跑不会重复提醒。

用法:
    python tools/scan_requirements.py            # 扫描 + 更新状态；有新增/变更时退出码 2
    python tools/scan_requirements.py --dry-run  # 只看不写状态（巡检/调试用）
    python tools/scan_requirements.py --json     # 机器可读输出
    python tools/scan_requirements.py --inbox 其它目录

退出码: 0 = 无变化；2 = 有新增或变更（供 cron/CI 判断要不要提醒人）；1 = 出错
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INBOX = ROOT / "需求池"
STATE_NAME = "_scan_state.json"
SUFFIXES = {".md", ".txt", ".docx", ".doc", ".xlsx", ".xls", ".pdf", ".csv", ".pptx"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def title_of(path: Path) -> str:
    """尽量从文档里取一个像需求标题的字符串；取不到就用文件名。"""
    if path.suffix.lower() == ".md":
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("#"):
                    return line.lstrip("#").strip() or path.stem
                if line and not line.startswith(">"):
                    return line[:60]
        except OSError:
            pass
    return path.stem


def candidates(inbox: Path) -> list[Path]:
    out = []
    for p in sorted(inbox.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUFFIXES:
            continue
        if p.name.startswith(("~$", ".", "_")):
            continue
        if p.parent == inbox and p.name.lower() == "readme.md":
            continue  # 投放目录自己的说明，不是需求
        out.append(p)
    return out


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "files": {}}


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0

    inbox = DEFAULT_INBOX
    if "--inbox" in argv:
        inbox = Path(argv[argv.index("--inbox") + 1])
        if not inbox.is_absolute():
            inbox = ROOT / inbox
    dry = "--dry-run" in argv
    as_json = "--json" in argv
    quiet = "--quiet" in argv

    if not inbox.exists():
        print(f"扫描目录不存在: {inbox}", file=sys.stderr)
        return 1

    state_path = inbox / STATE_NAME
    state = load_state(state_path)
    known: dict = state.get("files", {})
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    new, changed, unchanged, seen = [], [], [], set()
    for p in candidates(inbox):
        rel = p.relative_to(inbox).as_posix()
        seen.add(rel)
        digest = sha256(p)
        size = p.stat().st_size
        old = known.get(rel)
        item = {"path": rel, "sha256": digest, "size": size, "title": title_of(p)}
        if old is None:
            item["first_seen"] = now
            new.append(item)
        elif old.get("sha256") != digest:
            item["first_seen"] = old.get("first_seen", now)
            item["changed_at"] = now
            changed.append(item)
        else:
            item["first_seen"] = old.get("first_seen", now)
            unchanged.append(item)
        known.setdefault(rel, {}).update(item)
        known[rel]["last_seen"] = now

    removed = [r for r in known if r not in seen]

    result = {
        "scanned_at": now,
        "inbox": str(inbox),
        "new": new, "changed": changed, "removed": removed,
        "counts": {"new": len(new), "changed": len(changed), "removed": len(removed), "unchanged": len(unchanged)},
    }

    if not dry:
        state.update({"version": 1, "files": known, "checked_at": now})
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if new or changed:
            (inbox / "_待确认.md").write_text(render_pending(result), encoding="utf-8")

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not quiet:
        c = result["counts"]
        print(f"需求雷达 {now[:10]}：新增 {c['new']}　变更 {c['changed']}　移除 {c['removed']}　未变 {c['unchanged']}")
        for it in new:
            print(f"  [新] {it['path']}　—　{it['title']}")
        for it in changed:
            print(f"  [变] {it['path']}　—　{it['title']}")
        for r in removed:
            print(f"  [删] {r}")
        if new or changed:
            print("")
            print("下一步（确认要开发之后）：")
            print("  1) 建需求目录：requirements/<短名>需求<YYYYMMDD>/反馈者/")
            print("  2) 把文档放进去并登记：python skills/sk-req-register/register.py --path ... --proposer ... --channel ... --submitted-at ...")
        elif not (new or changed or removed):
            print("  没有新需求。")

    return 2 if (new or changed) else 0


def render_pending(r: dict) -> str:
    lines = [
        "# 待确认的需求文档",
        "",
        f"> 由 `python tools/scan_requirements.py` 于 {r['scanned_at']} 生成。",
        "> 这里只列「发现」，不判断要不要做——确认要开发后，才建需求目录并登记。",
        "",
        "## 新增",
        "",
    ]
    lines += [f"- [ ] `{it['path']}`　{it['title']}" for it in r["new"]] or ["（无）"]
    lines += ["", "## 变更（同一份文档改过）", ""]
    lines += [f"- [ ] `{it['path']}`　{it['title']}（{it.get('changed_at', '')}）" for it in r["changed"]] or ["（无）"]
    if r["removed"]:
        lines += ["", "## 已消失", ""] + [f"- `{x}`" for x in r["removed"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
