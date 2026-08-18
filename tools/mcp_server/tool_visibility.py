"""Tool visibility filtering shared by the MCP server and doc generation.

Loads config/mcp/tool_filter.json once and exposes the set of tools that
should be hidden from tools/list and rejected on tools/call. The tool
implementations remain registered in TOOLS so internal orchestration
(e.g. plc_run_arsim_closed_loop) keeps working; only the MCP surface is
trimmed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from schemas import TOOL_DEFINITIONS


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILTER_PATH = REPO_ROOT / "config" / "mcp" / "tool_filter.json"


@lru_cache(maxsize=1)
def load_disabled_tools(path: Path = DEFAULT_FILTER_PATH) -> frozenset[str]:
    """Read the disabled tool names from the filter file. Missing file => empty set."""
    if not path.exists():
        return frozenset()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    tools = data.get("disabled_tools")
    if not isinstance(tools, list):
        return frozenset()
    return frozenset(str(item) for item in tools if isinstance(item, str) and item)


def is_tool_visible(name: str, disabled: frozenset[str] | None = None) -> bool:
    return name not in (disabled if disabled is not None else load_disabled_tools())


def visible_definitions(disabled: frozenset[str] | None = None) -> list[dict]:
    """TOOL_DEFINITIONS filtered to the visible surface, preserving order."""
    disabled = disabled if disabled is not None else load_disabled_tools()
    if not disabled:
        return list(TOOL_DEFINITIONS)
    return [definition for definition in TOOL_DEFINITIONS if definition["name"] not in disabled]


def disabled_definitions(disabled: frozenset[str] | None = None) -> list[dict]:
    """Definitions hidden from the MCP surface, preserving order."""
    disabled = disabled if disabled is not None else load_disabled_tools()
    if not disabled:
        return []
    return [definition for definition in TOOL_DEFINITIONS if definition["name"] in disabled]
