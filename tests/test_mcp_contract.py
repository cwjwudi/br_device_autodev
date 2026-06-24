from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import schemas  # noqa: E402
import server  # noqa: E402
import toolchain  # noqa: E402
import version  # noqa: E402


VALID_RISK_LEVELS = {"readonly", "local_write", "project_write", "target_change"}


class McpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definitions = schemas.TOOL_DEFINITIONS
        cls.definitions_by_name = {item["name"]: item for item in cls.definitions}

    def test_tool_names_are_unique(self) -> None:
        names = [item["name"] for item in self.definitions]
        self.assertEqual(len(names), len(set(names)), "TOOL_DEFINITIONS contains duplicate names")

    def test_schema_and_handler_names_match(self) -> None:
        self.assertEqual(set(self.definitions_by_name), set(toolchain.TOOLS))

    def test_server_version_has_single_semver_source(self) -> None:
        self.assertRegex(version.__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(version.__version__, server.SERVER_INFO["version"])

    def test_every_registered_handler_is_callable(self) -> None:
        for name, handler in toolchain.TOOLS.items():
            with self.subTest(tool=name):
                self.assertTrue(callable(handler))

    def test_every_tool_has_closed_object_schema(self) -> None:
        for name, definition in self.definitions_by_name.items():
            with self.subTest(tool=name):
                schema = definition.get("inputSchema")
                self.assertIsInstance(schema, dict)
                self.assertEqual("object", schema.get("type"))
                self.assertIs(schema.get("additionalProperties"), False)
                self.assertIsInstance(schema.get("properties"), dict)

    def test_risk_classification_covers_every_tool(self) -> None:
        self.assertEqual(set(self.definitions_by_name), set(schemas.TOOL_RISK_LEVELS))
        self.assertTrue(set(schemas.TOOL_RISK_LEVELS.values()).issubset(VALID_RISK_LEVELS))
        self.assertEqual(set(self.definitions_by_name), set(schemas.TOOL_BACKENDS))

    def test_annotations_match_risk_classification(self) -> None:
        for name, definition in self.definitions_by_name.items():
            with self.subTest(tool=name):
                risk = schemas.TOOL_RISK_LEVELS[name]
                annotations = definition.get("annotations") or {}
                meta = definition.get("_meta") or {}
                self.assertEqual(risk == "readonly", annotations.get("readOnlyHint"))
                self.assertEqual(
                    risk in schemas.CONFIRMATION_REQUIRED_RISK_LEVELS,
                    annotations.get("destructiveHint"),
                )
                self.assertEqual(risk == "readonly", annotations.get("idempotentHint"))
                self.assertIs(annotations.get("openWorldHint"), False)
                self.assertEqual(risk, meta.get("br-automation/riskLevel"))
                self.assertEqual(schemas.TOOL_BACKENDS[name], meta.get("br-automation/backend"))

    def test_state_changing_tools_require_execute(self) -> None:
        for name, risk in schemas.TOOL_RISK_LEVELS.items():
            if risk not in schemas.CONFIRMATION_REQUIRED_RISK_LEVELS:
                continue
            with self.subTest(tool=name):
                schema = self.definitions_by_name[name]["inputSchema"]
                execute = schema["properties"].get("execute")
                self.assertIsInstance(execute, dict)
                self.assertEqual("boolean", execute.get("type"))
                self.assertIn("execute", schema.get("required") or [])

    def test_handler_required_arguments_are_declared(self) -> None:
        required_arguments = {
            "plc_add_project_library": {"library", "execute"},
            "plc_find_library_for_symbol": {"symbol"},
            "plc_plan_project_library": {"library"},
            "plc_run_io_test_case": {"case_name", "execute"},
            "plc_write_pvi": {"writes", "execute"},
        }
        for name, expected in required_arguments.items():
            with self.subTest(tool=name):
                schema = self.definitions_by_name[name]["inputSchema"]
                self.assertTrue(expected.issubset(set(schema.get("required") or [])))

    @patch.object(toolchain, "run_plc_toolchain")
    def test_start_arsim_confirmation_gate_blocks_execution(self, run_toolchain) -> None:
        result = toolchain.plc_start_arsim({"execute": False})

        self.assertFalse(result["ok"])
        self.assertFalse(result["data"]["executed"])
        self.assertIn("execute=true", result["summary"])
        run_toolchain.assert_not_called()

    @patch.object(toolchain, "run_plc_toolchain")
    def test_start_arsim_executes_after_confirmation(self, run_toolchain) -> None:
        run_toolchain.return_value = {
            "ok": True,
            "started_new_process": True,
            "process_id": 123,
        }

        result = toolchain.plc_start_arsim({"execute": True})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["executed"])
        run_toolchain.assert_called_once()


if __name__ == "__main__":
    unittest.main()
