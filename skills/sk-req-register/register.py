#!/usr/bin/env python3
"""sk-req-register：把原始需求登记进 requirements/inbox/_registry.jsonl。

    python skills/sk-req-register/register.py \
        --path requirements/inbox/REQ-20261122-01.md \
        --proposer 张敏 --channel "钉钉「数据需求」群" --submitted-at "2026-11-22 10:12"

纯标准库。幂等：同路径同 hash 重复登记不会重复写行。
同路径 hash 不同 → 拒绝登记（原件可能被改过，要求另存 -v2）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REQ_ID_RE = re.compile(r"^REQ-(\d{8})-(\d{2})(?:-v(\d+))?$")

# 模板五段（顺序即编号）
REQUIRED_SECTIONS = ["原始描述", "需求方想要的数", "提到的业务名词", "附件", "不在本次范围"]
# 来源三要素
REQUIRED_META = ["提出人", "渠道", "提出时间"]

REGISTRY_REL = "requirements/inbox/_registry.jsonl"
CST = timezone(timedelta(hours=8))


def repo_root() -> Path:
    """从 skills/sk-req-register/ 往上两级。"""
    return Path(__file__).resolve().parents[2]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_registry(registry: Path) -> list[dict]:
    if not registry.exists():
        return []
    rows = []
    for i, line in enumerate(registry.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"登记簿第 {i} 行不是合法 JSON: {e}")
    return rows


def check_template(text: str) -> list[str]:
    errs: list[str] = []
    headings = {int(n): t.strip() for n, t in re.findall(r"^##\s*(\d+)\.\s*(.+)$", text, re.M)}
    for i, kw in enumerate(REQUIRED_SECTIONS, 1):
        if i not in headings:
            errs.append(f"缺少第 {i} 段「{kw}」")
        elif kw not in headings[i]:
            errs.append(f"第 {i} 段标题应为「{kw}」，实际是「{headings[i]}」")

    for key in REQUIRED_META:
        value = meta_value(text, key)
        if value is None:
            errs.append(f"缺少表格行「{key}」")
        elif not value:
            errs.append(f"「{key}」为空（不许填'不详'，写不出就别入库）")

    body = section_body(text, 1)
    if len(body.strip()) < 10:
        errs.append("第 1 段「原始描述」为空或过短——原话贴进来，转述放第 2 段")

    if "-- 待填 --" in text or "TODO" in text.upper():
        errs.append("文档里还有 待填/TODO 占位符")
    return errs


def meta_value(text: str, key: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(f"| {key}") and not stripped.startswith(f"|{key}"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == key:
            return cells[1]
    return None


def section_body(text: str, num: int) -> str:
    m = re.search(rf"^##\s*{num}\.\s*.+$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^##\s*\d+\.", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="原始需求入库登记")
    ap.add_argument("--path", required=True, help="requirements/inbox/REQ-*.md")
    ap.add_argument("--proposer", required=True)
    ap.add_argument("--channel", required=True)
    ap.add_argument("--submitted-at", required=True, dest="submitted_at")
    ap.add_argument("--title")
    ap.add_argument("--registry", default=None, help="默认 requirements/inbox/_registry.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="只检查不写登记簿")
    args = ap.parse_args(argv)

    root = repo_root()
    path = Path(args.path)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        print(json.dumps({"ok": False, "errors": [f"文件不存在: {path}"]}, ensure_ascii=False, indent=2))
        return 1

    rel = path.resolve().relative_to(root.resolve()).as_posix()
    req_id = path.stem
    if not REQ_ID_RE.fullmatch(req_id):
        print(json.dumps({"ok": False, "errors": [f"文件名必须形如 REQ-YYYYMMDD-NN，实际 {req_id}"]},
                         ensure_ascii=False, indent=2))
        return 1

    errors = check_template(path.read_text(encoding="utf-8"))
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    registry_path = Path(args.registry) if args.registry else root / REGISTRY_REL
    rows = load_registry(registry_path)
    digest = sha256_of(path)

    same_path = [r for r in rows if r.get("path") == rel]
    if same_path:
        last = same_path[-1]
        if last.get("sha256") == digest:
            print(json.dumps({"ok": True, "req_id": req_id, "sha256": digest, "path": rel,
                              "registered": False, "note": "已登记过，hash 一致，幂等返回"},
                             ensure_ascii=False, indent=2))
            return 0
        print(json.dumps({"ok": False, "path": rel, "registered": False,
                          "errors": ["登记簿里的 hash 与当前文件不一致：原始需求被改过。"
                                     "不允许重新登记，请另存为 -v2 文件并说明改了什么"]},
                         ensure_ascii=False, indent=2))
        return 1

    for r in rows:
        if r.get("req_id") == req_id and r.get("path") != rel:
            print(json.dumps({"ok": False, "errors": [f"编号 {req_id} 已被 {r.get('path')} 占用"]},
                             ensure_ascii=False, indent=2))
            return 1

    entry = {
        "req_id": req_id,
        "path": rel,
        "sha256": digest,
        "proposer": args.proposer.strip(),
        "channel": args.channel.strip(),
        "submitted_at": args.submitted_at.strip(),
        "registered_at": datetime.now(CST).replace(microsecond=0).isoformat(),
        "title": (args.title or first_title(path)).strip(),
    }
    if not args.dry_run:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        with registry_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(json.dumps({"ok": True, "req_id": req_id, "sha256": digest, "path": rel,
                      "registered": not args.dry_run, "entry": entry,
                      "registry": registry_path.relative_to(root).as_posix()},
                     ensure_ascii=False, indent=2))
    return 0


def first_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
