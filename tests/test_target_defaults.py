from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import schemas  # noqa: E402
import server  # noqa: E402
import toolchain  # noqa: E402


class TargetDefaultTests(unittest.TestCase):
    def test_schema_does_not_advertise_an_implicit_target(self) -> None:
        for definition in schemas.TOOL_DEFINITIONS:
            with self.subTest(tool=definition["name"]):
                target_schema = definition["inputSchema"]["properties"]["target"]
                self.assertNotIn("default", target_schema)

    def test_server_rejects_target_change_without_explicit_selection(self) -> None:
        handler = Mock(return_value={"ok": True})
        with patch.dict(server.TOOLS, {"plc_start_arsim": handler}):
            result = server.handle_tools_call(
                {"name": "plc_start_arsim", "arguments": {"execute": True}}
            )

        payload = result["structuredContent"]
        self.assertTrue(result["isError"])
        self.assertTrue(
            any(
                item["keyword"] == "explicitTarget"
                for item in payload["validation_errors"]
            )
        )
        handler.assert_not_called()

    def test_explicit_environment_satisfies_target_selection(self) -> None:
        handler = Mock(return_value={"ok": True})
        with patch.dict(server.TOOLS, {"plc_start_arsim": handler}):
            result = server.handle_tools_call(
                {
                    "name": "plc_start_arsim",
                    "arguments": {"environment": "default_safe", "execute": True},
                }
            )

        self.assertFalse(result["isError"])
        handler.assert_called_once()

    @patch.object(toolchain, "run_plc_toolchain")
    def test_readonly_logger_falls_back_to_arsim(self, run_toolchain) -> None:
        run_toolchain.return_value = {"ok": True}

        result = toolchain.plc_read_logger({})

        self.assertEqual("arsim", result["target"])
        self.assertEqual("arsim", run_toolchain.call_args.kwargs["target"])

    @patch.object(toolchain, "run_plc_toolchain")
    def test_direct_target_change_handler_also_requires_selection(self, run_toolchain) -> None:
        with self.assertRaisesRegex(ValueError, "explicit non-empty target or environment"):
            toolchain.plc_start_arsim({"execute": True})

        run_toolchain.assert_not_called()

    def test_cli_default_is_arsim_and_state_changes_are_gated(self) -> None:
        script = (REPO_ROOT / "tools" / "plc_toolchain.ps1").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn('[string]$Target = "arsim"', script)
        self.assertIn('$PSBoundParameters.ContainsKey("Target")', script)
        for command in (
            "StartArsim",
            "Download",
            "WritePvi",
            "RunIoTestCase",
            "RunTestSuite",
            "ResetTestHarness",
            "RunArsimClosedLoop",
        ):
            self.assertIn(f'"{command}"', script)


if __name__ == "__main__":
    unittest.main()
