#!/usr/bin/env python3
"""本体校验器：不依赖任何第三方库，CI 里可直接跑。

用法：
    python ontology/schema/validate.py            # 校验整个 ontology/
    python ontology/schema/validate.py --json     # 机器可读输出
    python ontology/schema/validate.py --strict   # 若装了 PyYAML，用它交叉验证解析结果

为什么自带 YAML 解析器：目标机器上只有标准库。支持的 YAML 子集见下方 parse_yaml 的说明，
超出子集的写法会直接报错，而不是猜。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# 迷你 YAML 解析器：只支持本体文件里实际会用到的那一小撮语法
#   1. 注释以 # 开头（行首或前面是空格）
#   2. "key: value" 形式的映射，用 2 空格缩进嵌套
#   3. "- item" 形式的列表，元素可以是标量，也可以是 "key: value" 开头的映射
#   4. 行内列表 "key: [a, b, c]"
#   5. 单引号/双引号字符串；其余一律按字符串处理（不猜数字/布尔/日期）
# 明确不支持：锚点、多文档、块标量 | >、流式映射 {a: b}、多行字符串。
# 遇到不支持的写法抛 YamlSubsetError，宁可失败也不静默解析错。
# --------------------------------------------------------------------------


class YamlSubsetError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1] in " \t":
                return line[:i]
    return line


def _scalar(text: str):
    text = text.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in _split_inline(inner)]
    if text[0] in "{|>":
        raise YamlSubsetError(f"不支持块标量/流式写法: {text[:40]}")
    return text


def _split_inline(text: str) -> list[str]:
    parts, buf, quote = [], "", ""
    for ch in text:
        if quote:
            buf += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p for p in (p.strip() for p in parts) if p != ""]


def parse_yaml(text: str):
    lines = []
    for raw in text.splitlines():
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        if "\t" in raw:
            raise YamlSubsetError("缩进必须用空格，不能有 tab")
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip(), stripped))
    if not lines:
        raise YamlSubsetError("空文件")
    value, idx = _parse_block(lines, 0, lines[0][0])
    if idx != len(lines):
        raise YamlSubsetError(f"第 {idx + 1} 个有效行缩进不一致")
    return value


def _parse_block(lines, start, indent):
    """解析从 start 开始、缩进为 indent 的一块，返回 (值, 下一个未消费的下标)。"""
    if lines[start][1].startswith("- "):
        return _parse_list(lines, start, indent)
    return _parse_map(lines, start, indent)


def _parse_map(lines, start, indent):
    result: dict = {}
    i = start
    while i < len(lines):
        cur_indent, content, _ = lines[i]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise YamlSubsetError(f"缩进跳级: {content[:40]}")
        if content.startswith("- "):
            break
        if ":" not in content:
            raise YamlSubsetError(f"缺少冒号: {content[:40]}")
        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()
        if key in result:
            raise YamlSubsetError(f"重复的键: {key}")
        if rest:
            result[key] = _scalar(rest)
            i += 1
            continue
        # 值在下面：看下一行的缩进决定是列表还是映射
        if i + 1 < len(lines) and lines[i + 1][0] > cur_indent:
            child, i = _parse_block(lines, i + 1, lines[i + 1][0])
            result[key] = child
        else:
            result[key] = ""
            i += 1
    return result, i


def _parse_list(lines, start, indent):
    items: list = []
    i = start
    while i < len(lines):
        cur_indent, content, _ = lines[i]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise YamlSubsetError(f"列表项缩进跳级: {content[:40]}")
        if not content.startswith("- "):
            break
        rest = content[2:].strip()
        if not rest:
            raise YamlSubsetError("不支持空列表项后接嵌套块")
        if ":" in rest and not rest.startswith(("'", '"', "[")):
            # 列表项是一个映射，交给 _parse_map_item 逐字段收集
            item, j = _parse_map_item(lines, i, cur_indent, rest)
            items.append(item)
            i = j
            continue
        items.append(_scalar(rest))
        i += 1
    return items, i


def _parse_map_item(lines, start, item_indent, first_rest):
    """解析 "- key: value" 起始的映射项，后续同项字段缩进为 item_indent + 2。"""
    result: dict = {}
    key, _, rest = first_rest.partition(":")
    key, rest = key.strip(), rest.strip()
    result[key] = _scalar(rest) if rest else ""
    i = start + 1
    inner_indent = item_indent + 2
    while i < len(lines):
        cur_indent, content, _ = lines[i]
        if cur_indent < inner_indent:
            break
        if cur_indent > inner_indent:
            raise YamlSubsetError(f"列表项内缩进跳级: {content[:40]}")
        if content.startswith("- "):
            break
        k, _, r = content.partition(":")
        k, r = k.strip(), r.strip()
        if not r:
            if i + 1 < len(lines) and lines[i + 1][0] > cur_indent:
                child, i = _parse_block(lines, i + 1, lines[i + 1][0])
                result[k] = child
            else:
                result[k] = ""
                i += 1
            continue
        result[k] = _scalar(r)
        i += 1
    return result, i


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------


def _rel(path: Path) -> str:
    """相对工作区的 posix 路径，跨平台可读。"""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.files = 0

    def err(self, path: Path, msg: str) -> None:
        self.errors.append(f"{_rel(path)}: {msg}")

    def warn(self, path: Path, msg: str) -> None:
        self.warnings.append(f"{_rel(path)}: {msg}")


def load_meta(report: Report):
    path = SCHEMA_DIR / "meta-model.yaml"
    try:
        return parse_yaml(path.read_text(encoding="utf-8"))
    except (OSError, YamlSubsetError) as exc:
        report.err(path, f"元模型无法解析: {exc}")
        return None


def validate(meta: dict) -> Report:
    report = Report()
    id_pattern = re.compile(meta["id_pattern"])
    types = {t["name"]: t for t in meta["entity_types"]}
    kinds = set(meta.get("metric_kinds", []))
    statuses = set(meta.get("status_values", []))

    seen: dict[str, Path] = {}
    entities: dict[str, dict] = {}

    for name, spec in types.items():
        base = ROOT / spec["dir"]
        if not base.exists():
            report.warn(base, "目录不存在")
            continue
        for path in sorted(base.rglob("*.yaml")):
            rel_dir = path.parent.relative_to(ROOT / spec["dir"]).as_posix()
            kind_name = name
            if rel_dir != ".":
                if name == "metric" and rel_dir in kinds:
                    kind_name = rel_dir
                else:
                    report.err(path, f"未知子目录 {rel_dir}（metric 只允许 {sorted(kinds)}）")
                    continue
            report.files += 1
            try:
                doc = parse_yaml(path.read_text(encoding="utf-8"))
            except (OSError, YamlSubsetError) as exc:
                report.err(path, f"YAML 解析失败: {exc}")
                continue
            if not isinstance(doc, dict):
                report.err(path, "顶层必须是映射")
                continue

            missing = [f for f in spec["required"] if f not in doc or doc[f] in ("", [], None)]
            if missing:
                report.err(path, f"缺少必填字段 {missing}")

            eid = doc.get("id", "")
            if isinstance(eid, str):
                if not id_pattern.match(eid):
                    report.err(path, f"id 不符合命名规范: {eid!r}")
                if eid != path.stem.upper():
                    report.err(path, f"id {eid!r} 与文件名 {path.stem!r} 不一致")
                if eid in seen:
                    report.err(path, f"id 重复，已存在于 {seen[eid].relative_to(ROOT)}")
                seen[eid] = path
                entities[eid] = {"type": name, "kind": kind_name, "doc": doc, "path": path}

            status = doc.get("status", "draft")
            if status and status not in statuses:
                report.err(path, f"status 非法: {status!r}，允许 {sorted(statuses)}")

            if name == "metric":
                if doc.get("kind") not in kinds:
                    report.err(path, f"kind 必须是 {sorted(kinds)} 之一，当前 {doc.get('kind')!r}")
                if kind_name != doc.get("kind"):
                    report.err(path, f"目录 {kind_name} 与 kind {doc.get('kind')!r} 不一致")
                add = doc.get("additivity")
                if add not in set(meta.get("additivity_levels", [])):
                    report.err(path, f"additivity 非法: {add!r}")

    # 引用完整性：引用字段必须指向存在的实体
    ref_fields = {
        "metric": ["process", "objects", "derived_from"],
        "process": ["objects"],
        "link": ["from_object", "to_object"],
        "constraint": ["applies_to"],
    }
    for eid, info in entities.items():
        doc = info["doc"]
        for field in ref_fields.get(info["type"], []):
            value = doc.get(field)
            if value in (None, "", []):
                continue
            for ref in value if isinstance(value, list) else [value]:
                if not isinstance(ref, str) or not ref_pattern_ok(ref):
                    report.err(info["path"], f"{field} 含非法引用 {ref!r}")
                elif ref not in entities:
                    report.err(info["path"], f"{field} 引用了不存在的 ID {ref!r}")

    return report


def ref_pattern_ok(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value))


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    report = Report()
    meta = load_meta(report)
    if meta:
        r = validate(meta)
        report.errors += r.errors
        report.warnings += r.warnings
        report.files = r.files

    if as_json:
        print(json.dumps(
            {"ok": not report.errors, "files": report.files,
             "errors": report.errors, "warnings": report.warnings},
            ensure_ascii=False, indent=2))
    else:
        print(f"校验 {report.files} 个本体文件")
        for w in report.warnings:
            print(f"  WARN  {w}")
        for e in report.errors:
            print(f"  ERROR {e}")
        print("PASS" if not report.errors else f"FAIL（{len(report.errors)} 个错误）")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
