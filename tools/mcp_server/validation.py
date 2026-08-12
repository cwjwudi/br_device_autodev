from __future__ import annotations

import re
from typing import Any


ValidationError = dict[str, Any]


def _error(path: str, keyword: str, message: str, **details: Any) -> ValidationError:
    result: ValidationError = {
        "path": path,
        "keyword": keyword,
        "message": message,
    }
    result.update(details)
    return result


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[ValidationError]:
    """Validate the JSON Schema subset used by the MCP tool contracts."""
    if not schema:
        return []

    errors: list[ValidationError] = []
    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else list(expected or [])
    if expected_types and not any(_matches_type(value, item) for item in expected_types):
        expected_label = " or ".join(expected_types)
        return [
            _error(
                path,
                "type",
                f"Expected {expected_label}, received {_type_name(value)}.",
                expected=expected_types,
                actual=_type_name(value),
            )
        ]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(
            _error(
                path,
                "enum",
                f"Value must be one of {schema['enum']!r}.",
                allowed=schema["enum"],
            )
        )

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                errors.append(
                    _error(
                        f"{path}.{name}",
                        "required",
                        f"Required property '{name}' is missing.",
                        property=name,
                    )
                )

        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            child_path = f"{path}.{name}"
            if name in properties:
                errors.extend(validate_json_schema(item, properties[name], child_path))
            elif additional is False:
                errors.append(
                    _error(
                        child_path,
                        "additionalProperties",
                        f"Unknown property '{name}' is not allowed.",
                        property=name,
                    )
                )
            elif isinstance(additional, dict):
                errors.extend(validate_json_schema(item, additional, child_path))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(
                _error(
                    path,
                    "minItems",
                    f"Array must contain at least {schema['minItems']} item(s).",
                    minimum=schema["minItems"],
                    actual=len(value),
                )
            )
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(
                _error(
                    path,
                    "maxItems",
                    f"Array must contain at most {schema['maxItems']} item(s).",
                    maximum=schema["maxItems"],
                    actual=len(value),
                )
            )
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_json_schema(item, items_schema, f"{path}[{index}]"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(
                _error(
                    path,
                    "minLength",
                    f"String must contain at least {schema['minLength']} character(s).",
                    minimum=schema["minLength"],
                    actual=len(value),
                )
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(
                _error(
                    path,
                    "maxLength",
                    f"String must contain at most {schema['maxLength']} character(s).",
                    maximum=schema["maxLength"],
                    actual=len(value),
                )
            )
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            errors.append(
                _error(
                    path,
                    "pattern",
                    f"String does not match pattern {schema['pattern']!r}.",
                    pattern=schema["pattern"],
                    actual=value,
                )
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(
                _error(
                    path,
                    "minimum",
                    f"Value must be greater than or equal to {schema['minimum']}.",
                    minimum=schema["minimum"],
                    actual=value,
                )
            )
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(
                _error(
                    path,
                    "maximum",
                    f"Value must be less than or equal to {schema['maximum']}.",
                    maximum=schema["maximum"],
                    actual=value,
                )
            )

    return errors
