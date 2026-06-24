from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import schemas  # noqa: E402
import server  # noqa: E402
from validation import validate_json_schema  # noqa: E402


class JsonSchemaValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = {
            item["name"]: item["inputSchema"] for item in schemas.TOOL_DEFINITIONS
        }

    def assert_has_error(self, errors, *, path: str, keyword: str) -> None:
        self.assertTrue(
            any(item["path"] == path and item["keyword"] == keyword for item in errors),
            errors,
        )

    def test_required_and_min_length_are_validated(self) -> None:
        schema = self.schemas["plc_find_library_for_symbol"]
        missing = validate_json_schema({}, schema)
        empty = validate_json_schema({"symbol": ""}, schema)

        self.assert_has_error(missing, path="$.symbol", keyword="required")
        self.assert_has_error(empty, path="$.symbol", keyword="minLength")

    def test_type_enum_and_minimum_are_validated(self) -> None:
        logger_errors = validate_json_schema(
            {"format": ".txt"}, self.schemas["plc_read_logger"]
        )
        build_errors = validate_json_schema(
            {"timeout_seconds": 0, "build_ruc_package": "yes"},
            self.schemas["plc_build_project"],
        )

        self.assert_has_error(logger_errors, path="$.format", keyword="enum")
        self.assert_has_error(build_errors, path="$.timeout_seconds", keyword="minimum")
        self.assert_has_error(build_errors, path="$.build_ruc_package", keyword="type")

    def test_unknown_and_nested_properties_are_validated(self) -> None:
        errors = validate_json_schema(
            {
                "execute": True,
                "unknown": 1,
                "writes": [{"value": True, "extra": "blocked"}],
            },
            self.schemas["plc_write_pvi"],
        )

        self.assert_has_error(errors, path="$.unknown", keyword="additionalProperties")
        self.assert_has_error(errors, path="$.writes[0].variable", keyword="required")
        self.assert_has_error(
            errors, path="$.writes[0].extra", keyword="additionalProperties"
        )

    def test_valid_arguments_have_no_errors(self) -> None:
        errors = validate_json_schema(
            {
                "execute": True,
                "timeout_seconds": 30,
                "writes": [{"variable": "LQR:bLqrEnable", "value": False}],
            },
            self.schemas["plc_write_pvi"],
        )

        self.assertEqual([], errors)


class McpServerValidationTests(unittest.TestCase):
    def test_invalid_arguments_are_rejected_before_handler(self) -> None:
        handler = Mock(return_value={"ok": True})
        with patch.dict(server.TOOLS, {"plc_probe_target": handler}):
            result = server.handle_tools_call(
                {"name": "plc_probe_target", "arguments": {"unexpected": True}}
            )

        self.assertTrue(result["isError"])
        self.assertFalse(result["structuredContent"]["ok"])
        self.assertEqual("plc_probe_target", result["structuredContent"]["tool"])
        self.assertIn("validation_errors", result["structuredContent"])
        handler.assert_not_called()

    def test_non_object_arguments_are_rejected_by_schema(self) -> None:
        result = server.handle_tools_call(
            {"name": "plc_probe_target", "arguments": []}
        )

        payload = result["structuredContent"]
        self.assertTrue(result["isError"])
        self.assertEqual("type", payload["validation_errors"][0]["keyword"])
        self.assertEqual("$", payload["validation_errors"][0]["path"])

    def test_valid_arguments_reach_handler(self) -> None:
        handler = Mock(return_value={"ok": True, "tool": "plc_probe_target"})
        with patch.dict(server.TOOLS, {"plc_probe_target": handler}):
            result = server.handle_tools_call(
                {"name": "plc_probe_target", "arguments": {"target": "arsim"}}
            )

        self.assertFalse(result["isError"])
        handler.assert_called_once_with({"target": "arsim"})


if __name__ == "__main__":
    unittest.main()
