#!/usr/bin/env python3
"""sk-req-validate：G1 门禁——翻译稿能不能开工。

    python skills/sk-req-validate/validate.py --doc requirements/normalized/REQ-20261122-01.md
    python skills/sk-req-validate/validate.py --doc ... --json

纯标准库、只读。检查 8 段、待确认项、sha256 溯源、本体引用、验收标准可断言。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = [
    "一句话目标", "口径", "输入表与字段", "输出表",
    "口径边界", "验收标准", "不做什么", "待确认项",
]

EMPTY_MARKERS = {"", "无", "暂无", "无。", "-", "—", "none", "None", "N/A", "（无）", "(无)", "✓"}

SHA_RE = re.compile(r"sha256[^0-9a-f]{0,40}([0-9a-f]{64})")
REQ_RE = re.compile(r"REQ-\d{8}-\d{2}")
ONT_PATH_RE = re.compile(r"ontology/[A-Za-z0-9_./-]+\.ya?ml")
ID_RE = re.compile(r"`([A-Z][A-Z0-9_]{2,63})`")
TABLE_RE = re.compile(r"\b(?:ods|dwd|dws|ads|dim)_[a-z0-9_]+\b")
ASSERT_TOKENS = ("%", ">", "<", "≥", "≤", "偏差", "非空", "行数", "=", "不超过", "至少")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def split_sections(text: str) -> dict[int, tuple[str, str]]:
    """返回 {编号: (标题, 正文)}。"""
    out: dict[int, tuple[str, str]] = {}
    marks = list(re.finditer(r"^##\s*(\d+)\.\s*(.+)$", text, re.M))
    for i, m in enumerate(marks):
        num = int(m.group(1))
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[num] = (m.group(2).strip(), text[m.end():end])
    return out


def ontology_ids(root: Path) -> set[str]:
    ids = set()
    onto = root / "ontology"
    if not onto.exists():
        return ids
    for p in onto.rglob("*.yaml"):
        for m in re.finditer(r"^id:\s*([A-Z][A-Z0-9_]{2,63})\s*$", p.read_text(encoding="utf-8"), re.M):
            ids.add(m.group(1))
    return ids


def load_registry(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    by_req: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        by_req[row["req_id"]] = row
    return by_req


def main(argv: list[str]) -> int:
    args = dict(zip(argv[::2], argv[1::2]))
    doc_arg = args.get("--doc")
    if not doc_arg:
        print("用法: validate.py --doc requirements/normalized/REQ-*.md [--registry PATH] [--json]", file=sys.stderr)
        return 2

    root = repo_root()
    doc_path = Path(doc_arg)
    if not doc_path.is_absolute():
        doc_path = root / doc_path
    if not doc_path.exists():
        print(json.dumps({"ok": False, "errors": [f"文件不存在: {doc_path}"]}, ensure_ascii=False, indent=2))
        return 1

    text = doc_path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    sections = split_sections(text)
    for i, kw in enumerate(REQUIRED_SECTIONS, 1):
        if i not in sections:
            errors.append(f"缺少第 {i} 段「{kw}」")
        elif kw not in sections[i][0]:
            errors.append(f"第 {i} 段标题应为「{kw}」，实际是「{sections[i][0]}」")

    # 1. 目标不能是空话
    goal = sections.get(1, ("", ""))[1].strip()
    if 1 in sections and len(goal) < 10:
        errors.append("第 1 段「一句话目标」为空或过短")

    # 2. 待确认项必须为空
    if 8 in sections:
        pending = sections[8][1].strip()
        stripped = re.sub(r"^[-*>\s]+", "", pending).strip()
        if stripped not in EMPTY_MARKERS:
            first = stripped.splitlines()[0][:80]
            errors.append(f"第 8 段「待确认项」不为空：{first}——有歧义就不许进 P2")

    # 3. 溯源：编号 + sha256 必须与登记簿一致
    req_ids = REQ_RE.findall(text)
    if not req_ids:
        errors.append("文档里没有引用原始需求编号 REQ-YYYYMMDD-NN")
    hashes = SHA_RE.findall(text)
    if not hashes:
        errors.append("没有引用原始需求的 sha256（溯源断了，没法和原件对账）")
    if req_ids and hashes:
        registry_path = Path(args["--registry"]) if "--registry" in args else root / "requirements/inbox/_registry.jsonl"
        registry = load_registry(registry_path if registry_path.is_absolute() else root / registry_path)
        row = registry.get(req_ids[0])
        if not row:
            errors.append(f"登记簿里找不到 {req_ids[0]}（先跑 sk-req-register）")
        elif row["sha256"] not in hashes:
            errors.append(f"引用的 sha256 与登记簿不一致：登记 {row['sha256'][:12]}…，文档写 {hashes[0][:12]}…——可能基于旧版原件")

    # 4. 本体引用必须真实存在
    ids = ontology_ids(root)
    for m in set(ONT_PATH_RE.findall(text)):
        if not (root / m).exists():
            errors.append(f"引用了不存在的本体文件: {m}")
    for m in sorted(set(ID_RE.findall(text))):
        if ids and m not in ids:
            errors.append(f"引用了本体里没有的 id: `{m}`——要么改引用，要么提 ontology_delta")

    # 5. 输入/输出表
    if 3 in sections and not TABLE_RE.search(sections[3][1]):
        errors.append("第 3 段「输入表与字段」没有出现任何表名（dwd_/dws_/ads_/dim_/ods_）")
    if 4 in sections and not TABLE_RE.search(sections[4][1]):
        errors.append("第 4 段「输出表」没有出现任何表名")

    # 6. 验收标准必须可断言
    if 6 in sections:
        body = sections[6][1]
        if not re.search(r"\d", body):
            errors.append("第 6 段「验收标准」没有数字——不可断言的验收标准等于没有")
        if not any(t in body for t in ASSERT_TOKENS):
            errors.append("第 6 段「验收标准」没有比较条件（>/</%/偏差/非空 等）")

    result = {"ok": not errors, "doc": doc_path.name, "sections": len(sections),
              "errors": errors, "warnings": warnings}
    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{doc_path.name}: {len(sections)}/8 段")
        for e in errors:
            print(f"  [FAIL] {e}")
        print("PASS：翻译稿可开工（G1）" if not errors else f"FAIL：{len(errors)} 个问题")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
