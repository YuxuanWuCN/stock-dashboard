#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 openapi.json 生成 src/types/api.ts

用法：
    python3 scripts/gen-api-types.py          # 或 npm run api:types

生成内容分两段：
1. Schemas —— components.schemas 里的每个 schema 一个 interface / type；
2. 接口 DTO —— 每个 operation 的 Query / Request / Response 类型别名。

约定：
- 只认 spec 里显式声明的 required，不猜。没有 required 的对象 = 全字段可选
  （所以 spec 那边必须把 required 写全，否则生成出来满屏 `?`）。
- `nullable: true` 只在**引用处**体现为 `| null`，与被引用类型本身的定义解耦。
- 名字叫 `Error` 的 schema 重命名为 `ApiError`，避免遮蔽 TS 内置的 Error。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "openapi.json"
OUT_PATH = ROOT / "src" / "types" / "api.ts"

#: schema 名 → 生成的 TS 类型名
RENAME = {"Error": "ApiError"}

SPEC: Dict[str, Any] = {}


def resolve(schema: Any) -> Dict[str, Any]:
    """把 ``$ref`` 解析成目标 schema（不追 allOf）。"""
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema:
        node: Any = SPEC
        for part in schema["$ref"][2:].split("/"):
            node = node[part]
        schema = node
        seen += 1
        if seen > 16:
            break
    return schema if isinstance(schema, dict) else {}


def ref_type_name(ref: str) -> str:
    return RENAME.get(ref.rsplit("/", 1)[-1], ref.rsplit("/", 1)[-1])


def literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "null"
    return str(value)


def indent_block(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in text.splitlines())


def prop_key(name: str) -> str:
    return name if name.isidentifier() else literal(name)


def jsdoc(description: Optional[str], example: Any = None, indent: int = 0) -> str:
    """生成 JSDoc 注释块；没有内容返回空串。"""
    lines: List[str] = []
    if description:
        cleaned = " ".join(str(description).split()).replace("*/", "*\\/")
        lines.append(cleaned)
    if example is not None:
        rendered = json.dumps(example, ensure_ascii=False)
        if len(rendered) > 120:
            rendered = rendered[:117] + "..."
        lines.append(f"@example {rendered}")
    if not lines:
        return ""
    pad = " " * indent
    body = "\n".join(f"{pad} * {line}" for line in lines)
    return f"{pad}/**\n{body}\n{pad} */\n"


def needs_parens(expr: str) -> bool:
    return " | " in expr or " & " in expr


def type_of(schema: Any, indent: int = 0) -> str:
    """把 JSON Schema 片段转成 TS 类型表达式。"""
    if not isinstance(schema, dict):
        return "unknown"

    # $ref：可空性看被引用目标
    if "$ref" in schema:
        name = ref_type_name(schema["$ref"])
        target = resolve(schema)
        return f"{name} | null" if target.get("nullable") or schema.get("nullable") else name

    # allOf：交叉类型（本项目用于给 $ref 叠加 nullable）
    if "allOf" in schema:
        parts = [type_of(part, indent) for part in schema["allOf"]]
        expr = " & ".join(parts) if parts else "unknown"
        if needs_parens(expr):
            expr = f"({expr})"
        return f"{expr} | null" if schema.get("nullable") else expr

    # 枚举：字面量联合
    if "enum" in schema:
        expr = " | ".join(literal(v) for v in schema["enum"])
        return f"{expr} | null" if schema.get("nullable") else expr

    kind = schema.get("type")
    if kind == "array":
        inner = type_of(schema.get("items"), indent)
        expr = f"({inner})[]" if needs_parens(inner) else f"{inner}[]"
    elif kind == "object" or "properties" in schema or "additionalProperties" in schema:
        expr = object_body(schema, indent)
    elif kind in ("integer", "number"):
        expr = "number"
    elif kind == "boolean":
        expr = "boolean"
    elif kind == "string":
        expr = "string"
    else:
        expr = "unknown"

    if schema.get("nullable") and not expr.endswith("| null"):
        expr = f"({expr}) | null" if needs_parens(expr) else f"{expr} | null"
    return expr


def object_body(schema: Dict[str, Any], indent: int) -> str:
    """对象类型：有 properties 就展开成字面量，否则退化成 Record。"""
    props: Dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    additional = schema.get("additionalProperties")

    if not props:
        value = type_of(additional, indent) if isinstance(additional, dict) else "unknown"
        return f"Record<string, {value}>"

    lines = ["{"]
    for name, sub in props.items():
        doc = ""
        if isinstance(sub, dict):
            doc = jsdoc(sub.get("description"), sub.get("example"), indent + 2)
        optional = "" if name in required else "?"
        lines.append(f"{doc}{' ' * (indent + 2)}{prop_key(name)}{optional}: {type_of(sub, indent + 2)}")
    lines.append(" " * indent + "}")
    expr = "\n".join(lines)
    if additional is True:
        expr += " & Record<string, unknown>"
    return expr


def emit_schema(name: str, schema: Dict[str, Any]) -> str:
    target = RENAME.get(name, name)
    doc = jsdoc(schema.get("description"))

    if "allOf" in schema:
        return f"{doc}export type {target} = {type_of(schema)}"

    if schema.get("type") == "object" or "properties" in schema:
        props: Dict[str, Any] = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        body: List[str] = [f"{doc}export interface {target} {{"]
        for prop, sub in props.items():
            prop_doc = jsdoc(sub.get("description"), sub.get("example"), 2) if isinstance(sub, dict) else ""
            optional = "" if prop in required else "?"
            body.append(f"{prop_doc}  {prop_key(prop)}{optional}: {type_of(sub, 2)}")
        if schema.get("additionalProperties") is True:
            body.append("  [key: string]: unknown")
        body.append("}")
        return "\n".join(body)

    return f"{doc}export type {target} = {type_of(schema)}"


def emit_operations(paths: Dict[str, Any]) -> str:
    """按 operationId 生成 Query / Request / Response 类型别名。"""
    blocks: List[str] = []
    for path, item in paths.items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or f"{method}{path}"
            base = op_id[0].upper() + op_id[1:]
            header = f"/** {method.upper()} {path} —— {op.get('summary', '')} */"
            lines: List[str] = [header]

            params = [p for p in (op.get("parameters") or []) if p.get("in") in ("query", "path")]
            if params:
                lines.append(f"export interface {base}Query {{")
                for param in params:
                    schema = param.get("schema") or {}
                    doc = jsdoc(param.get("description"), schema.get("example"), 2)
                    optional = "" if param.get("required") else "?"
                    lines.append(f"{doc}  {prop_key(param['name'])}{optional}: {type_of(schema, 2)}")
                lines.append("}")

            body = op.get("requestBody")
            if isinstance(body, dict):
                content = (body.get("content") or {}).get("application/json")
                if content:
                    resolver = "unknown"
                    lines.append(f"export type {base}Request = {type_of(content.get('schema'), 0) if content.get('schema') else resolver}")

            ok = op.get("responses", {}).get("200")
            if isinstance(ok, dict):
                content = (ok.get("content") or {}).get("application/json")
                schema = (content or {}).get("schema")
                lines.append(f"export type {base}Response = {type_of(schema, 0) if schema else 'unknown'}")

            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main() -> int:
    global SPEC
    if not SPEC_PATH.exists():
        print(f"找不到 {SPEC_PATH}，请先运行 npm run api:spec 拉取规格。", file=sys.stderr)
        return 1
    SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    schemas: Dict[str, Any] = SPEC.get("components", {}).get("schemas", {})
    info = SPEC.get("info", {})

    parts: List[str] = [
        "/**",
        " * 后端接口类型 —— 由 openapi.json 自动生成，请勿手工修改。",
        " *",
        f" * 来源 spec：{info.get('title', '')} v{info.get('version', '')}"
        f"（OpenAPI {SPEC.get('openapi')}）",
        f" * schema 数：{len(schemas)}",
        " *",
        " * 重新生成：npm run api:spec && npm run api:types",
        " */",
        "",
        "/* ------------------------------------------------------------------ Schemas */",
        "",
    ]
    for name, schema in schemas.items():
        parts.append(emit_schema(name, resolve(schema)))
        parts.append("")

    parts.append("/* ------------------------------------------------------------------ 接口 DTO */")
    parts.append("")
    parts.append(emit_operations(SPEC.get("paths", {})))
    parts.append("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(parts), encoding="utf-8")
    print(f"已生成 {OUT_PATH.relative_to(ROOT)}（{len(schemas)} 个 schema）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
