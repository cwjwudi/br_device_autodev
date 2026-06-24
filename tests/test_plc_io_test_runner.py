from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import plc_io_test_runner as runner  # noqa: E402


def successful_reset() -> dict:
    return {"ok": True, "executed": True, "writes": []}


class PlcIoTestRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.args = SimpleNamespace(
            target="arsim",
            targets_file="targets.json",
            suite="suite.json",
            case_name=None,
            reset_only=False,
            execute=True,
            report_dir=None,
            settle_ms=0,
            port=11169,
            pvi_dll_dir=None,
            cpu_name="arsim",
            manager_timeout=5,
            communication_timeout_ms=2500,
            connect_wait_ms=0,
            variable_wait_ms=0,
            write_wait_ms=0,
        )
        self.config = {
            "_targets_file": "targets.json",
            "pvi": {
                "enabled": True,
                "read_whitelist": [
                    {"scope": "task", "task": "Harness", "name": "Output"}
                ],
                "write_whitelist": [
                    {"scope": "task", "task": "Harness", "name": "Input"}
                ],
                "restore_writes": [
                    {"variable": "Harness:Input", "value": 0}
                ],
            },
            "access_policy": {"mode": "whitelist"},
        }
        self.target_config = {"ip": "127.0.0.1", "role": "arsim"}
        self.case = {
            "name": "fixture_case",
            "writes": [{"variable": "Harness:Input", "value": 1}],
            "readback": ["Harness:Output"],
            "checks": [{"variable": "Harness:Output", "expected": 1}],
        }
        self.read_success = {
            "ok": True,
            "variables": [
                {
                    "ok": True,
                    "scope": "task",
                    "task": "Harness",
                    "name": "Output",
                    "value": 1,
                }
            ],
        }

    def test_suite_structure_rejects_duplicate_names_and_invalid_items(self) -> None:
        errors = runner.validate_suite_structure(
            {
                "cases": [
                    {"name": "same", "writes": [], "checks": []},
                    {
                        "name": "same",
                        "settle_ms": -1,
                        "writes": [{"variable": "Harness:Input"}],
                        "checks": ["bad"],
                    },
                ]
            }
        )

        self.assertTrue(any("Duplicate" in error for error in errors))
        self.assertTrue(any("settle_ms" in error for error in errors))
        self.assertTrue(any("declare value" in error for error in errors))
        self.assertTrue(any("checks" in error for error in errors))

    @patch.object(runner, "reset_harness", return_value=successful_reset())
    @patch.object(runner, "validate_case_access", return_value=["blocked input"])
    def test_validation_failure_has_stage_and_restore_record(self, _validate, _reset) -> None:
        report = runner.run_case(
            self.args, self.config, self.target_config, self.case
        )

        self.assertEqual("validation", report["failure_stage"])
        self.assertEqual(["validation"], report["failure_stages"])
        self.assertEqual("after_validation_failure", report["reset_records"][0]["phase"])

    @patch.object(runner, "reset_harness", return_value=successful_reset())
    @patch.object(runner, "run_writes", return_value={"ok": False, "error": "write denied"})
    @patch.object(runner, "validate_case_access", return_value=[])
    def test_write_failure_is_distinct(self, _validate, _write, _reset) -> None:
        report = runner.run_case(
            self.args, self.config, self.target_config, self.case
        )

        self.assertEqual("write", report["failure_stage"])
        self.assertIn("write", report["failure_stages"])
        self.assertEqual("after_case", report["reset_records"][-1]["phase"])

    @patch.object(runner, "reset_harness", return_value=successful_reset())
    @patch.object(runner, "run_reads", return_value={"ok": False, "error": "read timeout", "variables": []})
    @patch.object(runner, "run_writes", return_value={"ok": True})
    @patch.object(runner, "validate_case_access", return_value=[])
    def test_read_and_assert_failures_are_both_reported(
        self, _validate, _write, _read, _reset
    ) -> None:
        report = runner.run_case(
            self.args, self.config, self.target_config, self.case
        )

        self.assertEqual("read", report["failure_stage"])
        self.assertEqual(["read", "assert"], report["failure_stages"])

    @patch.object(runner, "reset_harness", return_value=successful_reset())
    @patch.object(runner, "run_reads")
    @patch.object(runner, "run_writes", return_value={"ok": True})
    @patch.object(runner, "validate_case_access", return_value=[])
    def test_assert_failure_is_distinct(self, _validate, _write, read, _reset) -> None:
        read.return_value = self.read_success
        case = dict(self.case)
        case["checks"] = [{"variable": "Harness:Output", "expected": 2}]

        report = runner.run_case(
            self.args, self.config, self.target_config, case
        )

        self.assertEqual("assert", report["failure_stage"])
        self.assertEqual(["assert"], report["failure_stages"])

    @patch.object(runner, "run_reads")
    @patch.object(runner, "run_writes", return_value={"ok": True})
    @patch.object(runner, "validate_case_access", return_value=[])
    def test_restore_failure_overrides_success(self, _validate, _write, read) -> None:
        read.return_value = self.read_success
        with patch.object(
            runner,
            "reset_harness",
            side_effect=[successful_reset(), {"ok": False, "error": "restore failed"}],
        ):
            report = runner.run_case(
                self.args, self.config, self.target_config, self.case
            )

        self.assertFalse(report["ok"])
        self.assertEqual("restore", report["failure_stage"])
        self.assertIn("restore", report["failure_stages"])

    def test_pre_suite_reset_failure_skips_cases_and_attempts_final_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite_path = root / "suite.json"
            suite_path.write_text(
                json.dumps(
                    {
                        "name": "fixture_suite",
                        "fixture": {"name": "Harness", "dedicated": True},
                        "cases": [self.case],
                    }
                ),
                encoding="utf-8",
            )
            self.args.suite = str(suite_path)
            self.args.report_dir = str(root / "reports")
            case_runner = Mock()
            with (
                patch.object(
                    runner,
                    "load_target_config",
                    return_value=(self.config, self.target_config),
                ),
                patch.object(
                    runner,
                    "reset_harness",
                    side_effect=[
                        {"ok": False, "error": "pre reset failed"},
                        successful_reset(),
                    ],
                ),
                patch.object(runner, "run_case", case_runner),
            ):
                report = runner.run(self.args)

        self.assertFalse(report["ok"])
        self.assertEqual("restore", report["failure_stage"])
        self.assertEqual(0, report["cases_executed"])
        self.assertEqual(1, report["cases_skipped"])
        self.assertEqual(2, len(report["reset_records"]))
        case_runner.assert_not_called()

    def test_invalid_suite_cli_writes_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets_path = root / "targets.json"
            targets_path.write_text(
                json.dumps(
                    {
                        "pvi": {"enabled": True, "restore_writes": []},
                        "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}},
                    }
                ),
                encoding="utf-8",
            )
            suite_path = root / "invalid.json"
            suite_path.write_text("{not-json", encoding="utf-8")
            reports = root / "reports"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "plc_io_test_runner.py"),
                    "--target",
                    "arsim",
                    "--targets-file",
                    str(targets_path),
                    "--suite",
                    str(suite_path),
                    "--report-dir",
                    str(reports),
                ],
                cwd=REPO_ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=30,
                check=False,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(1, completed.returncode)
            self.assertEqual("validation", payload["failure_stage"])
            self.assertTrue(Path(payload["report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
