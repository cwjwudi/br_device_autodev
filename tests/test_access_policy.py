from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from plc_access_policy import evaluate_access_request  # noqa: E402


class AccessPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.targets_path = Path(self.temp_dir.name) / "targets.json"
        self.config = {
            "access_policy": {
                "mode": "whitelist",
                "allow_dynamic_pvi_read": False,
                "allow_dynamic_pvi_write": False,
                "allow_dynamic_opcua_read": False,
                "allow_dynamic_opcua_write": False,
                "allowed_target_roles": ["arsim", "dedicated_test_plc"],
                "blocked_name_patterns": ["*safety*", "*system*"],
            },
            "pvi": {
                "enabled": True,
                "read_whitelist": [
                    {"scope": "task", "task": "Harness", "name": "Input"}
                ],
                "write_whitelist": [
                    {"scope": "task", "task": "Harness", "name": "Input"}
                ],
            },
            "opcua": {"validation_node_ids": ["ns=2;s=Harness.Output"]},
            "targets": {
                "arsim": {"ip": "127.0.0.1", "role": "arsim"},
                "production": {"ip": "192.0.2.1", "role": "production"},
            },
        }
        self.targets_path.write_text(
            json.dumps(self.config, indent=2), encoding="utf-8"
        )

    def evaluate(self, operation: str, items: list, **kwargs) -> dict:
        target = kwargs.pop("target", "arsim")
        return evaluate_access_request(
            operation=operation,
            config=self.config,
            target_name=target,
            target_config=self.config["targets"][target],
            targets_file=str(self.targets_path),
            requested_items=items,
            **kwargs,
        )

    def run_cli(self, operation: str, items: list, **kwargs) -> dict:
        target = kwargs.pop("target", "arsim")
        command = [
            sys.executable,
            str(TOOLS_DIR / "plc_access_policy_cli.py"),
            "--operation",
            operation,
            "--targets-file",
            str(self.targets_path),
            "--target",
            target,
            "--items-json",
            json.dumps(items),
        ]
        if kwargs.get("explicit"):
            command.append("--explicit")
        if kwargs.get("execute"):
            command.append("--execute")
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=False,
        )
        return json.loads(completed.stdout)

    def test_cli_and_python_return_the_same_policy_decision(self) -> None:
        cases = [
            ("pvi_read", ["Harness:Input"], {"explicit": True}),
            ("pvi_read", ["Safety:Input"], {"explicit": True}),
            ("pvi_write", ["Harness:Input"], {"execute": True}),
            ("opcua_read", ["ns=2;s=Harness.Output"], {"explicit": True}),
        ]
        compared_keys = {
            "ok",
            "errors",
            "blocked_reason",
            "policy_mode",
            "target_role",
            "requested_items",
        }
        for operation, items, kwargs in cases:
            with self.subTest(operation=operation, items=items):
                direct = self.evaluate(operation, items, **kwargs)
                cli = self.run_cli(operation, items, **kwargs)
                self.assertEqual(
                    {key: direct[key] for key in compared_keys},
                    {key: cli[key] for key in compared_keys},
                )

    def test_production_write_is_rejected_even_with_execute(self) -> None:
        result = self.evaluate(
            "pvi_write", ["Harness:Input"], target="production", execute=True
        )

        self.assertFalse(result["ok"])
        self.assertIn("production", " ".join(result["errors"]).lower())
        self.assertEqual("production", result["target_role"])

    def test_trusted_target_can_read_and_write_any_variable_name(self) -> None:
        for variable in ("Other:NotListed", "Safety:Enable", "sys:value", "Main:physicalIoOut"):
            with self.subTest(variable=variable):
                self.assertTrue(self.evaluate("pvi_read", [variable], explicit=True)["ok"])
                self.assertTrue(self.evaluate("pvi_write", [variable], execute=True)["ok"])

    def test_trusted_write_still_requires_execute(self) -> None:
        result = self.evaluate("pvi_write", ["Other:NotListed"], execute=False)
        self.assertFalse(result["ok"])
        self.assertIn("execute=true", " ".join(result["errors"]))

    def test_policy_payload_contains_required_contract_fields(self) -> None:
        result = self.run_cli("pvi_read", ["Safety:Input"], explicit=True)

        for key in (
            "ok",
            "errors",
            "policy_mode",
            "target_role",
            "requested_items",
            "blocked_reason",
        ):
            self.assertIn(key, result)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is unavailable")
    def test_powershell_read_path_uses_authoritative_policy(self) -> None:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(TOOLS_DIR / "plc_toolchain.ps1"),
                "-Command",
                "ReadPvi",
                "-Target",
                "arsim",
                "-TargetsPath",
                str(self.targets_path),
                "-PviVariable",
                "Safety:Input",
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=False,
        )

        self.assertNotIn("blocked_name_patterns", completed.stdout)
        self.assertNotIn("not in pvi.read_whitelist", completed.stdout)

    def test_powershell_has_no_duplicate_policy_engine(self) -> None:
        script = (TOOLS_DIR / "plc_toolchain.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("plc_access_policy_cli.py", script)
        self.assertNotIn("function Get-AccessPolicy", script)
        self.assertNotIn("function Test-PviReadAccess", script)
        self.assertNotIn("function Test-OpcUaReadAccess", script)


if __name__ == "__main__":
    unittest.main()
