"""Conversion between pvipy values and MCP-safe JSON values."""

from __future__ import annotations

import datetime as dt
import math
from enum import Enum
from typing import Any

INTEGER_TYPES = {
    "u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64",
    "usint", "sint", "uint", "int", "udint", "dint", "ulint", "lint",
}
FLOAT_TYPES = {"f32", "f64", "real", "lreal"}
BOOLEAN_TYPES = {"boolean", "bool"}


def json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return {"name": value.name, "value": json_safe(value.value)}
    if isinstance(value, bytes):
        return value.rstrip(b"\x00").decode("utf-8", errors="replace")
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return int(value.total_seconds() * 1000)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def coerce_write_value(value: Any, data_type: str) -> Any:
    dtype = data_type.lower().split("[", 1)[0]
    if isinstance(value, list):
        return [coerce_write_value(item, dtype) for item in value]
    if isinstance(value, dict):
        raise ValueError("Structure writes are not supported by pvipy")
    if dtype in BOOLEAN_TYPES:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
            raise ValueError(f"Cannot convert {value!r} to BOOL")
        return bool(value)
    if dtype in INTEGER_TYPES:
        return int(value)
    if dtype in FLOAT_TYPES:
        return float(value)
    if dtype == "string":
        if not isinstance(value, (str, bytes)):
            raise ValueError("STRING writes require a string")
        return value.encode("utf-8") if isinstance(value, str) else value
    if dtype == "wstring":
        return str(value)
    if dtype in {"dt", "date_and_time"} and isinstance(value, str):
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dtype == "date" and isinstance(value, str):
        return dt.date.fromisoformat(value)
    if dtype in {"tod", "time_of_day"} and isinstance(value, str):
        return dt.time.fromisoformat(value)
    if dtype == "time":
        return dt.timedelta(milliseconds=int(value))
    return value


def values_equal(requested: Any, actual: Any) -> bool:
    left = json_safe(requested)
    right = json_safe(actual)
    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return all(values_equal(a, b) for a, b in zip(left, right))
    return left == right

