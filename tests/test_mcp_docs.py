from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER_DIR = REPO_ROOT / "tools" / "mcp_server"
sys.path.insert(0, str(MCP_SERVER_DIR))

from schemas import TOOL_DEFINITIONS  # noqa: E402
from tool_visibility import disabled_definitions, visible_definitions  # noqa: E402
from version import __version__  # noqa: E402


START_MARKER = "<!-- BEGIN GENERATED MCP TOOL CATALOG -->"
END_MARKER = "<!-- END GENERATED MCP TOOL CATALOG -->"
CATALOG_PATH = REPO_ROOT / "skills" / "br-plc-toolchain" / "references" / "mcp-tools.md"


class McpDocumentationTests(unittest.TestCase):
    def test_generated_documentation_is_current(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "maintenance" / "generate_mcp_docs.py"), "--check"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_catalog_contains_every_tool_once(self) -> None:
        catalog = CATALOG_PATH.read_text(encoding="utf-8")
        hidden_names = {item["name"] for item in disabled_definitions()}
        for definition in visible_definitions():
            token = f"| `{definition['name']}` |"
            with self.subTest(tool=definition["name"]):
                self.assertEqual(1, catalog.count(token))
        for definition in TOOL_DEFINITIONS:
            if definition["name"] not in hidden_names:
                continue
            token = f"`{definition['name']}`"
            with self.subTest(tool=definition["name"]):
                self.assertEqual(1, catalog.count(token))

    def test_catalog_records_server_version(self) -> None:
        catalog = CATALOG_PATH.read_text(encoding="utf-8")
        self.assertIn(f"MCP server version: `{__version__}`", catalog)

    def test_embedded_catalog_markers_are_unique(self) -> None:
        paths = [
            REPO_ROOT / "README.md",
            REPO_ROOT / "tools" / "mcp_server" / "README_FOR_LOCAL.md",
            REPO_ROOT / "docs" / "PLC_MCP_SKILL_PROMPT_ROADMAP.md",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8-sig")
            with self.subTest(path=path.name):
                self.assertEqual(1, text.count(START_MARKER))
                self.assertEqual(1, text.count(END_MARKER))

    def test_skill_and_agents_link_to_canonical_catalog(self) -> None:
        expected = "skills/br-plc-toolchain/references/mcp-tools.md"
        for relative in ("AGENTS.md", "skills/br-plc-toolchain/SKILL.md"):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8-sig")
            with self.subTest(path=relative):
                self.assertIn(expected, text)
                self.assertNotIn("| `plc_build_project` |", text)


if __name__ == "__main__":
    unittest.main()
