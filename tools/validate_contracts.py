#!/usr/bin/env python3
"""契约校验：用标准库实现 JSON Schema 的一个子集。

    python tools/validate_contracts.py requirements/<需求目录>/需求开发员/            # 校验整个目录
    python tools/validate_contracts.py doc.json --schema contracts/intent.schema.json
    python tools/validate_contracts.py doc.json --schema contracts/intent.schema.json --json
    python tools/validate_contracts.py journal.jsonl --schema contracts/journal_entry.schema.json --lines
      # --lines：一行一个 JSON（journal.jsonl 这类追加式账本），逐行校验并报行号

支持的子集（够了，不追求完整）：
    type / required / properties / additionalProperties:false /
    enum / pattern / minLength / minItems / items / $ref 到本文件内 #/definitions/x

不支持：oneOf/anyOf/allOf、$ref 跨文件、format、依赖关系。
遇到不支持的组合直接报错，不静默放过——契约校验最怕"看起来过了"。

为什么不用 jsonschema 库：目标机器只有标准库。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}

SUPPORTED_KEYWORDS = {
    "$schema", "$comment", "$id", "title", "description", "$ref", "definitions",
    "type", "required", "properties", "additionalProperties", "enum",
    "pattern", "minLength", "minItems", "items",
}


def check_type(value, expected: str) -> bool:
    py = TYPES.get(expected)
    if py is None:
        raise ValueError(f"不支持的 type: {expected}")
    if expected == "integer" and isinstance(value, bool):
        return False
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, py)


def validate(value, schema: dict, root: dict, path: str = "$") -> list[str]:
    errs: list[str] = []

    unknown = set(schema) - SUPPORTED_KEYWORDS
    if unknown:
        errs.append(f"{path}: schema 使用了不受支持的关键字 {sorted(unknown)}")
        return errs

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/definitions/"):
            errs.append(f"{path}: 只支持 #/definitions/ 形式的 $ref，当前 {ref!r}")
            return errs
        name = ref.split("/")[-1]
        target = root.get("definitions", {}).get(name)
        if target is None:
            errs.append(f"{path}: $ref 指向不存在的定义 {name!r}")
            return errs
        return validate(value, target, root, path)

    if "type" in schema and not check_type(value, schema["type"]):
        errs.append(f"{path}: 类型应为 {schema['type']}，实际 {type(value).__name__}")
        return errs

    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: 取值 {value!r} 不在 {schema['enum']} 内")

    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: {value!r} 不匹配 {schema['pattern']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: 长度 {len(value)} < {schema['minLength']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: 元素数 {len(value)} < {schema['minItems']}")
        if "items" in schema:
            for i, item in enumerate(value):
                errs += validate(item, schema["items"], root, f"{path}[{i}]")

    if isinstance(value, dict):
        for field in schema.get("required", []):
            if field not in value:
                errs.append(f"{path}: 缺少必填字段 {field!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errs += validate(value[key], sub, root, f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                errs.append(f"{path}: 出现未定义字段 {sorted(extra)}")
    return errs


def validate_file(doc_path: Path, schema_path: Path) -> list[str]:
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    return validate_against(doc, schema_path)


def validate_against(doc, schema_path: Path) -> list[str]:
    root = json.loads(schema_path.read_text(encoding="utf-8"))
    return validate(doc, root, root)


def validate_jsonl(doc_path: Path, schema_path: Path) -> list[str]:
    """一行一个 JSON（journal.jsonl 这类追加式账本）。"""
    errs: list[str] = []
    for n, line in enumerate(doc_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            errs.append(f"第 {n} 行 JSON 解析失败: {exc}")
            continue
        errs.extend(f"第 {n} 行: {e}" for e in validate_against(doc, schema_path))
    return errs


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    lines_mode = "--lines" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2

    schema_arg = None
    if "--schema" in argv:
        schema_arg = argv[argv.index("--schema") + 1]
        args = [a for a in args if a != schema_arg]

    target = Path(args[0])
    if target.is_dir():
        pattern = "*.jsonl" if lines_mode else "*.json"
        targets = sorted(target.rglob(pattern))
    else:
        targets = [target]

    results = []
    for doc_path in targets:
        schema_path = Path(schema_arg) if schema_arg else _guess_schema(doc_path)
        if schema_path is None or not schema_path.exists():
            results.append({"file": str(doc_path), "ok": False,
                            "errors": [f"找不到对应 schema（期望按契约名匹配 contracts/<name>.schema.json）"]})
            continue
        try:
            errs = validate_jsonl(doc_path, schema_path) if lines_mode else validate_file(doc_path, schema_path)
        except json.JSONDecodeError as exc:
            errs = [f"JSON 解析失败: {exc}"]
        results.append({"file": str(doc_path), "schema": str(schema_path), "ok": not errs, "errors": errs})

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "OK  " if r["ok"] else "FAIL"
            print(f"[{mark}] {r['file']}")
            for e in r["errors"]:
                print(f"        {e}")
    return 0 if all(r["ok"] for r in results) else 1


def _guess_schema(doc_path: Path) -> Path | None:
    """按文件名猜 schema：runs/<id>/intent.json → contracts/intent.schema.json。"""
    name = doc_path.stem
    if "_" in name:
        return Path("contracts") / f"{name.rsplit('_', 1)[0]}.schema.json"
    return Path("contracts") / f"{name}.schema.json"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
