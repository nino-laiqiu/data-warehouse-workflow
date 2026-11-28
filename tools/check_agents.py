#!/usr/bin/env python3
"""校验 agents/roles.json 与 flow/pipeline.yaml、flow/gates.yaml 的一致性。

查的是"角色定义"这一层，不是角色写得对不对：
  1. 结构：必填字段、id 规范、id 不重复、tools 取自词表、stages 取自 P0–P6 / A1–A6 / ALL
  2. 分工：任何角色都不能直接写 ontology/（只有人能改）；developer-1 与 developer-2 必须互设 must_not_read
  3. 接线：pipeline 里出现的 agent 必须在 roles.json 里；每个 stage 必须有人负责（ALL 不算）
  4. 门禁：role.gate 必须在 gates.yaml 里真的存在
  5. 编制：当前约定 5 个角色（需求分析员 / 开发者1 / 开发者2 / 监督者 / 追踪者），见 memory/decisions/ADR-0003-five-agents.md

退出码：0 通过；1 有错误。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROLES = ROOT / "agents" / "roles.json"
PIPELINE = ROOT / "flow" / "pipeline.yaml"
GATES = ROOT / "flow" / "gates.yaml"
STAGE_RE = re.compile(r"^(P[0-6]|A[1-6])$")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")
REQUIRED = ["id", "name", "stages", "gate", "tools", "writes", "notes"]


def main() -> int:
    errors: list[str] = []
    warns: list[str] = []

    if not ROLES.exists():
        print(f"缺少 {ROLES.relative_to(ROOT)}", file=sys.stderr)
        return 1
    doc = json.loads(ROLES.read_text(encoding="utf-8"))
    vocab = set(doc.get("tools", []))
    roles = doc.get("roles", [])
    if not roles:
        errors.append("roles 为空")
    by_id = {}
    for r in roles:
        rid = r.get("id", "?")
        for k in REQUIRED:
            if k not in r:
                errors.append(f"{rid}: 缺字段 {k}")
        if not ID_RE.match(rid):
            errors.append(f"{rid}: id 不合规（小写字母开头，允许数字与连字符，3–32 位）")
        if rid in by_id:
            errors.append(f"{rid}: id 重复")
        by_id[rid] = r
        bad_tools = [t for t in r.get("tools", []) if t not in vocab]
        if bad_tools:
            errors.append(f"{rid}: tools 里有词表外的工具 {bad_tools}（词表 {sorted(vocab)}）")
        for st in r.get("stages", []):
            if st != "ALL" and not STAGE_RE.match(st):
                errors.append(f"{rid}: stage {st} 不是 P0–P6 / A1–A6 / ALL")
        if r.get("gate") is None and not r.get("gate_reason"):
            errors.append(f"{rid}: gate 为 null 时要写 gate_reason")
        if not r.get("writes"):
            errors.append(f"{rid}: writes 为空——角色必须有写入边界（只读角色写 [] 并说明）")

    # 分工：本体谁都不能自动写（只有人能改，改前要走 ontology_delta 提案）
    ontology_writers = [r["id"] for r in roles if any("ontology/" in w for w in r.get("writes", []))]
    if ontology_writers:
        errors.append(f"任何角色都不得直接写 ontology/（只有人能改），违规角色：{ontology_writers}")

    # 编制：5 个角色（改编制先改 memory/decisions/ADR-0003-five-agents.md 与这条检查）
    if len(roles) != 5:
        errors.append(f"角色编制应为 5 个，当前 {len(roles)} 个：{[r['id'] for r in roles]}")

    # 分工：双轨隔离必须双向
    for a, b in (("developer-1", "developer-2"), ("developer-2", "developer-1")):
        if a not in by_id or b not in by_id:
            continue
        forbidden = by_id[a].get("must_not_read", [])
        if not any(b in f for f in forbidden):
            errors.append(f"{a}: must_not_read 里没有 {b} 的目录——双轨隔离形同虚设")

    # 接线：pipeline 的 agent 必须在 roles.json
    text = PIPELINE.read_text(encoding="utf-8") if PIPELINE.exists() else ""
    if not text:
        errors.append("缺少 flow/pipeline.yaml")
    used = set()
    for line in text.splitlines():
        m = re.search(r"^\s*agent:\s*(.+)$", line)
        if not m:
            continue
        raw = m.group(1).strip()
        for cut in ("（", "(", "#"):
            if cut in raw:
                raw = raw.split(cut, 1)[0]
        for name in re.split(r"[∥|,，/\s]+", raw):
            name = name.strip().strip("\"'")
            if ID_RE.match(name):
                used.add(name)
    for name in sorted(used - set(by_id)):
        errors.append(f"pipeline 里的 agent {name} 在 roles.json 里没有定义")

    # 接线：每个 stage 必须有人（ALL 不算覆盖）
    covered = {}
    for r in roles:
        for st in r.get("stages", []):
            if st == "ALL":
                for s in ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "A1", "A2", "A3", "A4", "A5", "A6"]:
                    covered.setdefault(s, []).append(r["id"])
            else:
                covered.setdefault(st, []).append(r["id"])
    for st in ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]:
        if st not in covered:
            warns.append(f"stage {st} 没有常驻角色（可在 pipeline 里标「无（skill 直调）」）")

    # 门禁存在性
    gates_text = GATES.read_text(encoding="utf-8") if GATES.exists() else ""
    for r in roles:
        g = r.get("gate")
        if g and g not in gates_text:
            errors.append(f"{r['id']}: gate {g} 在 flow/gates.yaml 里找不到")

    # 散文卡片：有更好，不强制（提示词由 role_prompt.py 生成）
    for r in roles:
        card = ROOT / "agents" / f"{r['id']}.md"
        if not card.exists() and r["id"] not in {"developer-1", "developer-2"}:
            warns.append(f"{r['id']}: 缺散文卡片 agents/{r['id']}.md（不影响运行，只影响人读）")

    for w in warns:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[FAIL] {e}")
    if errors:
        print(f"\n{len(errors)} 个错误")
        return 1
    print(f"[OK  ] 角色 {len(roles)} 个，pipeline 引用 {len(used)} 个角色，覆盖 {len(covered)} 个 stage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
