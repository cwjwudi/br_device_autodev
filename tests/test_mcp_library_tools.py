from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import schemas  # noqa: E402
import toolchain  # noqa: E402


class McpLibraryToolTests(unittest.TestCase):
    def test_library_tools_are_exposed(self) -> None:
        names = {item["name"] for item in schemas.TOOL_DEFINITIONS}
        self.assertIn("plc_find_library_for_symbol", names)
        self.assertIn("plc_plan_project_library", names)
        self.assertIn("plc_add_project_library", names)
        self.assertIn("plc_add_project_library", toolchain.TOOLS)

    @patch.object(toolchain, "run_plc_toolchain")
    @patch.object(toolchain, "run_library_manager")
    def test_failed_validation_build_rolls_back(self, manager, build) -> None:
        manager.side_effect = [
            {
                "ok": True,
                "executed": True,
                "requested_library": "AsTCP",
                "added_libraries": ["AsTCP"],
                "transaction_id": "a" * 32,
            },
            {
                "ok": True,
                "command": "RollbackLibraryAdd",
                "transaction_id": "a" * 32,
            },
        ]
        build.return_value = {
            "ok": False,
            "parsed_errors": 1,
            "parsed_warnings": 0,
            "error_lines": ["unknown symbol"],
        }

        result = toolchain.plc_add_project_library(
            {
                "library": "AsTCP",
                "execute": True,
                "project_path": "PrintDemo\\Huitong_FrontEval.apj",
                "targets_path": "tools\\plc_targets.local.json",
            }
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["data"]["rollback"]["ok"])
        self.assertFalse(result["data"]["validated_by_build"])
        self.assertEqual("rollback", manager.call_args_list[1].args[0])

    @patch.object(toolchain, "run_plc_toolchain")
    @patch.object(toolchain, "run_library_manager")
    def test_build_exception_still_rolls_back(self, manager, build) -> None:
        manager.side_effect = [
            {
                "ok": True,
                "executed": True,
                "requested_library": "AsTCP",
                "added_libraries": ["AsTCP"],
                "transaction_id": "b" * 32,
            },
            {"ok": True, "command": "RollbackLibraryAdd"},
        ]
        build.side_effect = toolchain.ToolchainError("build timed out")

        result = toolchain.plc_add_project_library(
            {"library": "AsTCP", "execute": True}
        )

        self.assertFalse(result["ok"])
        self.assertIn("could not complete", result["data"]["build"]["error"])
        self.assertTrue(result["data"]["rollback"]["ok"])

    def test_stdio_server_executes_isolated_library_add(self) -> None:
        generated = REPO_ROOT / "tools" / ".generated"
        generated.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=generated, prefix="mcp_library_test_") as temp_name:
            temp_root = Path(temp_name)
            project_root = temp_root / "Demo"
            libraries_dir = project_root / "Logical" / "Libraries"
            libraries_dir.mkdir(parents=True)
            project_path = project_root / "Demo.apj"
            project_path.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<Project xmlns="http://br-automation.co.at/AS/Project"><TechnologyPackages /></Project>\n',
                encoding="utf-8",
            )
            (libraries_dir / "Package.pkg").write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<?AutomationStudio FileVersion="4.9"?>\n'
                '<Package xmlns="http://br-automation.co.at/AS/Package"><Objects /></Package>\n',
                encoding="utf-8",
            )

            install_root = temp_root / "FakeAS"
            library_dir = install_root / "AS" / "Library_2" / "AsTCP"
            library_dir.mkdir(parents=True)
            (library_dir / "binary.lby").write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<Library xmlns="http://br-automation.co.at/AS/Library" Description="TCP test">\n'
                "  <Files><File>AsTCP.fun</File></Files>\n"
                "</Library>\n",
                encoding="utf-8",
            )
            (library_dir / "AsTCP.fun").write_text(
                "FUNCTION_BLOCK TcpOpen\nEND_FUNCTION_BLOCK\n",
                encoding="utf-8",
            )
            targets_path = temp_root / "targets.json"
            targets_path.write_text(
                json.dumps(
                    {
                        "automation_studio": {
                            "build_exe": str(install_root / "bin-en" / "BR.AS.Build.exe")
                        }
                    }
                ),
                encoding="utf-8",
            )

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "plc_add_project_library",
                    "arguments": {
                        "library": "AsTCP",
                        "project_path": str(project_path),
                        "targets_path": str(targets_path),
                        "execute": True,
                        "rebuild": False,
                    },
                },
            }
            completed = subprocess.run(
                [sys.executable, str(REPO_ROOT / "tools" / "mcp_server" / "server.py")],
                cwd=REPO_ROOT,
                input=json.dumps(request) + "\n",
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            response = json.loads(completed.stdout)
            structured = response["result"]["structuredContent"]
            self.assertTrue(structured["ok"])
            self.assertTrue((libraries_dir / "AsTCP" / "binary.lby").is_file())
            transaction_path = Path(structured["data"]["transaction_path"]).resolve()
            self.assertEqual(
                str(generated.resolve()),
                os.path.commonpath([str(transaction_path), str(generated.resolve())]),
            )
            shutil.rmtree(transaction_path)


if __name__ == "__main__":
    unittest.main()
