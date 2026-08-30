from pydantic import ValidationError


def schema_name_for(schema: type) -> str:
    raw = "".join(char if char.isalnum() or char in "_-" else "_" for char in schema.__name__)
    return (raw or "Response")[:64]


def format_schema_retry_feedback(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        lines = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ()))
            lines.append(f"- {loc or '?'}: {err.get('msg', 'inválido')}")
        detail = "\n".join(lines) or str(exc)
    else:
        detail = str(exc)
    return (
        "La respuesta anterior no cumplió el esquema:\n"
        f"{detail}\n\n"
        "Generá nuevamente el JSON corrigiendo exclusivamente esos errores."
    )


def _force_additional_properties_false(node: dict) -> None:
    if not isinstance(node, dict):
        return
    if "$ref" in node:
        return
    if node.get("type") == "object" or "properties" in node:
        props = node.get("properties") or {}
        node["additionalProperties"] = False
        if props:
            node["required"] = list(props.keys())
        for child in props.values():
            if isinstance(child, dict):
                _force_additional_properties_false(child)
    if isinstance(node.get("items"), dict):
        _force_additional_properties_false(node["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            if isinstance(child, dict):
                _force_additional_properties_false(child)


def pydantic_json_schema(schema: type) -> dict:
    raw = schema.model_json_schema()
    defs = raw.pop("$defs", None) or raw.pop("definitions", None)
    _force_additional_properties_false(raw)
    if defs:
        for item in defs.values():
            if isinstance(item, dict):
                _force_additional_properties_false(item)
        raw["$defs"] = defs
    raw.pop("$schema", None)
    raw.pop("title", None)
    return raw


def openai_json_schema_format(schema: type) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name_for(schema),
            "strict": True,
            "schema": pydantic_json_schema(schema),
        },
    }
