#!/usr/bin/env python
"""校验工作流里声明的技能是否真实存在，以及技能目录是否都被调用。

检查五件事：
1. 每个 stage 必须显式写 `skills:`（可以为 `[]`），不许省略。
2. 同一 stage 内同一个技能不许重复出现。
3. 引用的技能要么有目录（已实现），要么被列为"待建"——两者都不算错，但都会报出来。
4. 有目录的技能必须有 SKILL.md，且 front matter 含 name / version / owner。
5. 有目录但没被任何 stage 引用的，是死技能 → 报错。

用法：
    python tools/check_skills.py
    python tools/check_skills.py --json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
PIPELINE = ROOT / "flow" / "pipeline.yaml"

STAGE_RE = re.compile(r"^\s*-\s+id:\s*([AP]\d+)\s*$")
SKILLS_RE = re.compile(r"^\s+skills:\s*\[(.*?)\]\s*$")


def parse_pipeline() -> tuple[dict[str, list[str]], list[str]]:
    """返回 {stage_id: [skill,...]} 与"忘了写 skills 的 stage"。"""
    stages: dict[str, list[str]] = {}
    missing: list[str] = []
    current: str | None = None
    stage_has_skills: dict[str, bool] = {}

    for raw in PIPELINE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m = STAGE_RE.match(line)
        if m:
            if current and not stage_has_skills.get(current):
                missing.append(current)
            current = m.group(1)
            stages.setdefault(current, [])
            stage_has_skills[current] = False
            continue
        m = SKILLS_RE.match(line)
        if m and current:
            inner = m.group(1).strip()
            names = [x.strip() for x in inner.split(",") if x.strip()]
            stages[current] = names
            stage_has_skills[current] = True

    if current and not stage_has_skills.get(current):
        missing.append(current)
    return stages, missing


def parse_front_matter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    stages, missing_skills_key = parse_pipeline()

    dirs = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir() and p.name.startswith("sk-"))
    referenced: dict[str, list[str]] = {}
    errors: list[str] = []
    dupes: list[str] = []

    for sid, names in stages.items():
        seen = set()
        for n in names:
            if n in seen:
                dupes.append(f"{sid} 重复引用 {n}")
            seen.add(n)
            referenced.setdefault(n, []).append(sid)

    for sid in missing_skills_key:
        errors.append(f"stage {sid} 没有声明 skills（没有就写 skills: []）")
    errors.extend(dupes)

    implemented = [n for n in referenced if n in dirs]
    planned = [n for n in referenced if n not in dirs]
    orphans = [d for d in dirs if d not in referenced]

    for name in implemented:
        skill_md = SKILLS_DIR / name / "SKILL.md"
        if not skill_md.exists():
            errors.append(f"{name}: 有目录但没有 SKILL.md")
            continue
        meta = parse_front_matter(skill_md)
        for field in ("name", "version", "owner"):
            if not meta.get(field):
                errors.append(f"{name}: SKILL.md front matter 缺少 {field}")
        if meta.get("name") and meta["name"] != name:
            errors.append(f"{name}: front matter name='{meta['name']}' 与目录名不一致")
        for req in ("schema.json", "validate.py"):
            if not (SKILLS_DIR / name / req).exists():
                errors.append(f"{name}: 缺少 {req}")

    for name in orphans:
        errors.append(f"{name}: 有目录但没有被任何 stage 引用（死技能）")

    result = {
        "stages": len(stages),
        "referenced": len(referenced),
        "implemented": implemented,
        "planned": planned,
        "orphans": orphans,
        "ok": not errors,
        "errors": errors,
    }

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not errors else 1

    print(f"扫描 {PIPELINE.relative_to(ROOT)}：{len(stages)} 个 stage，引用 {len(referenced)} 个技能")
    print(f"  已实现 {len(implemented)}：{', '.join(implemented) or '无'}")
    print(f"  待建   {len(planned)}：{', '.join(planned) or '无'}")
    if orphans:
        print(f"  未调用 {len(orphans)}：{', '.join(orphans)}")
    if errors:
        print(f"FAIL：{len(errors)} 个问题")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("PASS：技能引用与目录一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
