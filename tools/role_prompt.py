#!/usr/bin/env python3
"""把 agents/roles.json 里的角色，组装成一段可以直接交给 DSH subagent 的提示词。

为什么要有这一步：角色定义如果只存在于 md 里，每个编排者都得凭记忆复制粘贴，
隔离规则（must_not_read）、输入输出路径、门禁编号迟早漏。这里让"派活"变成
一次函数调用，提示词还能同时落盘进需求目录，作为"我真的这样派的活"的证据。

用法:
    python tools/role_prompt.py --role developer-1 --req 画像标签需求20261122
    python tools/role_prompt.py --role supervisor --req 画像标签需求20261122 --json
    python tools/role_prompt.py --role developer-1 --req 画像标签需求20261122 --write

--write 会写 <需求目录>/需求开发员/prompts/<role>.md（同一角色重派会覆盖，旧的进 journal）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROLES_FILE = ROOT / "agents" / "roles.json"

HARD_RULES = """## 硬规则（违反任何一条，这次产出就算废）

1. **口径只从 `ontology/` 来**。不许在 SQL 注释、文档、对话里发明第二份口径；发现本体缺东西，写 ontology_delta 提案，不许自己补。
2. **只写你自己目录**（见下"可写"）。别人的目录只读；`journal.jsonl` 只能追加，不能改历史。
3. **不确定就写进"待确认"，不要猜**。猜出来的字段名、枚举值、时间窗，会在下游变成事故。
4. **交付前自查**：文件在不在、能不能跑、和输入是否对得上。自查看 `self-check.md` 或产物里的"已知问题"段。
5. **不许改契约字段名**。`contracts/*.schema.json` 是接口，要改走提案。
"""


def load() -> dict:
    return json.loads(ROLES_FILE.read_text(encoding="utf-8"))


def resolve(template: str, req_dir: str) -> str:
    run = f"requirements/{req_dir}/需求开发员"
    return (template.replace("<需求目录>", f"requirements/{req_dir}")
                    .replace("<run>", run)
                    .replace("<run_id>", req_dir)
                    .replace("<短名>", req_dir.replace("需求", "").replace("20261122", "")))


def build(doc: dict, role: dict, req_dir: str) -> str:
    path = lambda s: resolve(s, req_dir)
    lines = [
        f"# 你是「{role['name']}」（`{role['id']}`）",
        "",
        f"阶段：{' / '.join(role['stages'])}　门禁：{role.get('gate') or '无（' + role.get('gate_reason', '') + '）'}",
        f"本次需求目录：`requirements/{req_dir}/`",
        "",
        "## 职责",
        "",
        role.get("notes", ""),
        "",
        "## 可写",
        "",
    ]
    lines += [f"- `{path(w)}`" for w in role.get("writes", [])] or ["- （只读角色，不写文件）"]
    if role.get("inputs"):
        lines += ["", "## 必读输入", ""] + [f"- `{path(x)}`" for x in role["inputs"]]
    if role.get("outputs"):
        lines += ["", "## 交付物（缺一样 G 就过不了）", ""] + [f"- `{path(x)}`" for x in role["outputs"]]
    if role.get("must_not_read"):
        lines += ["", "## 禁止读（读了就破坏设计）", ""] + [f"- `{path(x)}`" for x in role["must_not_read"]]
    lines += ["", "## 可用工具", "", "、".join(role.get("tools", [])), "", HARD_RULES]
    lines += [
        "## 交付格式",
        "",
        "先写文件，再回一段结构化总结：",
        "",
        "1. 做了什么（一句话）",
        "2. 交付物清单（路径 + 一句话说明）",
        "3. 已知问题 / 待确认（没有就写「无」）",
        "4. 需要谁接力（下一个角色 + 需要它看什么）",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if "--help" in argv or not argv:
        print(__doc__)
        return 0
    role_id = req = None
    for flag in ("--role", "--req"):
        if flag in argv:
            val = argv[argv.index(flag) + 1]
            if flag == "--role":
                role_id = val
            else:
                req = val
    if not role_id or not req:
        print("必须同时给 --role 与 --req", file=sys.stderr)
        return 1

    doc = load()
    role = next((r for r in doc["roles"] if r["id"] == role_id), None)
    if role is None:
        print(f"没有这个角色: {role_id}\n可选: {', '.join(r['id'] for r in doc['roles'])}", file=sys.stderr)
        return 1
    req_dir = Path(req).name
    if not (ROOT / "requirements" / req_dir).is_dir():
        print(f"需求目录不存在: requirements/{req_dir}", file=sys.stderr)
        return 1

    prompt = build(doc, role, req_dir)
    if "--json" in argv:
        print(json.dumps({
            "role": role_id,
            "name": role["name"],
            "gate": role.get("gate"),
            "tools": role.get("tools", []),
            "must_not_read": [resolve(x, req_dir) for x in role.get("must_not_read", [])],
            "prompt": prompt,
        }, ensure_ascii=False, indent=2))
        return 0

    if "--write" in argv:
        out = ROOT / "requirements" / req_dir / "需求开发员" / "prompts" / f"{role_id}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(prompt, encoding="utf-8")
        print(f"已写入 {out.relative_to(ROOT)}（{len(prompt)} 字）")
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
