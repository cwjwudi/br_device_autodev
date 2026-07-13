from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = REPO_ROOT / "tools" / "mcp_server"
sys.path.insert(0, str(MCP_DIR))

import diagnostics  # noqa: E402
import schemas  # noqa: E402
import server  # noqa: E402
import toolchain  # noqa: E402


class McpDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.project_root = self.root / "Project"
        self.project_root.mkdir()
        self.project = self.project_root / "Demo.apj"
        self.project.write_text("<Project />", encoding="utf-8")
        physical = self.project_root / "Physical" / "sim"
        physical.mkdir(parents=True)
        (physical / "Hardware.hw").write_text("<Hardware />", encoding="utf-8")
        self.build_exe = self.root / "BR.AS.Build.exe"
        self.transfer_exe = self.root / "PVITransfer.exe"
        self.loader_exe = self.root / "ar000loader.exe"
        for path in (self.build_exe, self.transfer_exe, self.loader_exe):
            path.write_bytes(b"")
        self.targets = self.root / "targets.json"
        self.targets.write_text(
            json.dumps(
                {
                    "automation_studio": {
                        "build_exe": str(self.build_exe),
                        "pvi_transfer_exe": str(self.transfer_exe),
                    },
                    "targets": {
                        "arsim": {
                            "ip": "127.0.0.1",
                            "role": "arsim",
                            "arsim_loader_exe": str(self.loader_exe),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.options = {
            "environment": "test",
            "target": "arsim",
            "project_path": str(self.project),
            "config": "sim",
            "targets_path": str(self.targets),
        }
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()

    def write_report(self, name: str, payload: dict, *, age_seconds: int = 0) -> Path:
        path = self.reports_dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        timestamp = time.time() - age_seconds
        os.utime(path, (timestamp, timestamp))
        return path

    def test_environment_validation_checks_project_config_and_target(self) -> None:
        result = diagnostics.validate_environment(self.options)

        self.assertTrue(result["ok"])
        self.assertEqual("arsim", result["target"])
        self.assertEqual("arsim", result["target_role"])
        self.assertTrue(all(item["ok"] for item in result["checks"]))

    def test_environment_validation_reports_missing_target(self) -> None:
        options = dict(self.options, target="missing")

        result = diagnostics.validate_environment(options)

        self.assertFalse(result["ok"])
        self.assertTrue(any(item["name"] == "target" and not item["ok"] for item in result["checks"]))

    def test_environment_validation_rejects_as4_project_with_as6_toolchain(self) -> None:
        self.project.write_text(
            '<?xml version="1.0"?>\n<?AutomationStudio Version="4.12.6.99"?>\n<Project />',
            encoding="utf-8",
        )
        result = diagnostics.validate_environment(self.options)
        self.assertFalse(result["ok"])
        mismatch = next(
            item for item in result["checks"] if item["name"] == "project_toolchain_compatibility"
        )
        self.assertFalse(mismatch["ok"])

    def test_doctor_reports_all_dependencies_as_structured_checks(self) -> None:
        generated = self.root / "generated"
        with (
            patch.object(diagnostics, "GENERATED_DIR", generated),
            patch.object(diagnostics.shutil, "which", return_value=str(self.root / "powershell.exe")),
            patch.object(diagnostics.importlib.util, "find_spec", return_value=object()),
        ):
            result = diagnostics.run_doctor(self.options)

        self.assertTrue(result["ok"])
        names = {item["name"] for item in result["checks"]}
        self.assertTrue(
            {
                "python",
                "powershell",
                "build_exe",
                "pvi_transfer_exe",
                "pvi_dll",
                "pvi_python",
                "arsim_loader",
                "generated_write",
            }.issubset(names)
        )

    def test_report_listing_filters_kind_status_and_limit(self) -> None:
        self.write_report(
            "new_io_test.json",
            {"command": "RunTestSuite", "ok": False, "target": "arsim"},
        )
        self.write_report(
            "old_io_test.json",
            {"command": "RunTestSuite", "ok": True, "target": "arsim"},
            age_seconds=10,
        )
        self.write_report(
            "verification.json",
            {"command": "RunVerificationSuite", "ok": True},
        )

        failed = diagnostics.list_reports(
            limit=1, kind="io_test", status="failed", reports_dir=self.reports_dir
        )

        self.assertEqual(1, failed["count"])
        self.assertEqual("new_io_test.json", failed["reports"][0]["name"])
        self.assertNotIn("data", failed["reports"][0])

    def test_report_summary_is_compact_and_omits_values(self) -> None:
        report = self.write_report(
            "io_test.json",
            {
                "command": "RunTestSuite",
                "ok": False,
                "target": "arsim",
                "failure_stage": "assert",
                "failure_stages": ["assert"],
                "huge_log": "DO_NOT_RETURN",
                "cases": [
                    {
                        "name": "case_one",
                        "ok": False,
                        "failure_stage": "assert",
                        "failure_stages": ["assert"],
                        "writes": [{"variable": "Harness:Input", "value": 999}],
                        "checks": [
                            {"ok": False, "actual": 999, "expected": 1}
                        ],
                    }
                ],
            },
        )

        result = diagnostics.read_report_summary(report.name, self.reports_dir)
        encoded = json.dumps(result)

        self.assertTrue(result["ok"])
        self.assertEqual("assert", result["summary"]["failure_stage"])
        self.assertEqual(1, result["summary"]["case_results"][0]["checks_failed"])
        self.assertNotIn("DO_NOT_RETURN", encoded)
        self.assertNotIn("999", encoded)

    def test_report_path_traversal_is_rejected(self) -> None:
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "must stay inside"):
            diagnostics.read_report_summary(str(outside), self.reports_dir)

    def test_new_tools_are_readonly_and_server_validates_report_limit(self) -> None:
        names = {
            "plc_doctor",
            "plc_validate_environment",
            "plc_list_reports",
            "plc_read_report_summary",
        }
        self.assertTrue(names.issubset(toolchain.TOOLS))
        self.assertTrue(all(schemas.TOOL_RISK_LEVELS[name] == "readonly" for name in names))

        response = server.handle_tools_call(
            {"name": "plc_list_reports", "arguments": {"limit": 101}}
        )
        self.assertTrue(response["isError"])
        self.assertEqual(
            "maximum",
            response["structuredContent"]["validation_errors"][0]["keyword"],
        )


if __name__ == "__main__":
    unittest.main()
