"""Converte o schema interno de tools para o formato nativo OpenAI/Ollama."""

from __future__ import annotations

from typing import Any

_TYPE_MAP = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "list": "array",
    "array": "array",
    "dict": "object",
    "object": "object",
}


def _parameter_type(raw: str) -> dict[str, Any]:
    kind = (raw or "str").strip().lower()
    json_type = _TYPE_MAP.get(kind, "string")
    if json_type == "array":
        return {"type": "array", "items": {"type": "string"}}
    return {"type": json_type}


def to_openai_tools(schema: list[dict]) -> list[dict]:
    """Converte `tools_schema()` em `[{"type": "function", ...}]`."""
    converted: list[dict] = []
    for tool in schema or []:
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in tool.get("parameters") or []:
            if not isinstance(param, dict):
                continue
            pname = str(param.get("name") or "").strip()
            if not pname:
                continue
            prop = _parameter_type(str(param.get("type") or "str"))
            if param.get("description"):
                prop["description"] = str(param["description"])
            properties[pname] = prop
            if "default" not in param:
                required.append(pname)

        parameters: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            parameters["required"] = required

        converted.append({
            "type": "function",
            "function": {
                "name": name,
                "description": str(tool.get("description") or ""),
                "parameters": parameters,
            },
        })
    return converted
