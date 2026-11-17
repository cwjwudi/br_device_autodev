from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "mcp_server"))
from tool_visibility import disabled_definitions, visible_definitions
from version import __version__


def test_generated_readme_catalog_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "maintenance" / "generate_mcp_docs.py"), "--check"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_readme_catalog_covers_tools_and_version() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"MCP server version: `{__version__}`" in text
    assert text.count("<!-- BEGIN GENERATED MCP TOOL CATALOG -->") == 1
    assert text.count("<!-- END GENERATED MCP TOOL CATALOG -->") == 1
    for definition in visible_definitions():
        assert text.count(f"| `{definition['name']}` |") == 1
    for definition in disabled_definitions():
        assert f"`{definition['name']}`" in text
