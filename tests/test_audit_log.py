from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import locks  # noqa: E402
import server  # noqa: E402


class AuditLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.audit_dir = root / "audit"
        self.lock_dir = root / "locks"
        self.server_patches = [
            patch.object(server, "AUDIT_DIR", self.audit_dir),
            patch.object(server, "LOCK_DIR", self.lock_dir),
        ]
        for item in self.server_patches:
            item.start()
            self.addCleanup(item.stop)

    def records(self) -> list[dict]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.audit_dir.rglob("*.json"))
        ]

    def valid_write_arguments(self) -> dict:
        return {
            "target": "arsim",
            "execute": True,
            "name": "Harness:Input",
            "value": 123.456,
        }

    def test_success_is_locked_and_audited_without_values(self) -> None:
        handler = Mock(
            return_value={
                "ok": True,
                "tool": "plc_write_runtime_variable",
                "target": "arsim",
                "summary": "write completed",
                "data": {"report_path": "var/reports/write.json"},
                "logs": [],
                "warnings": [],
            }
        )
        with patch.dict(server.TOOLS, {"plc_write_runtime_variable": handler}):
            response = server.handle_tools_call(
                {
                    "name": "plc_write_runtime_variable",
                    "arguments": self.valid_write_arguments(),
                }
            )

        payload = response["structuredContent"]
        self.assertFalse(response["isError"])
        self.assertEqual(2, len(payload["audit"]))
        self.assertEqual([], list(self.lock_dir.glob("*.lock.json")))
        records = self.records()
        self.assertEqual({"started", "succeeded"}, {item["status"] for item in records})
        completed = next(item for item in records if item["status"] == "succeeded")
        self.assertEqual("arsim", completed["target"])
        self.assertEqual("trusted_role_unrestricted", completed["pvi_access_mode"])
        self.assertEqual("write completed", completed["result_summary"]["summary"])
        self.assertEqual("Harness:Input", completed["request_summary"]["name"])
        self.assertEqual("<redacted>", completed["request_summary"]["value"])
        audit_text = "\n".join(json.dumps(item) for item in records)
        self.assertNotIn("123.456", audit_text)

    def test_download_result_records_bypass_and_transfer_state(self) -> None:
        handler = Mock(
            return_value={
                "ok": True,
                "target": "arsim",
                "data": {
                    "download_ok": True,
                    "safety_bypassed": True,
                    "deployment_state": "runtime_reachable",
                    "stage": "RuntimeReachable",
                },
            }
        )
        arguments = {"target": "arsim", "execute": True, "bypass_download_safety": True}
        with patch.dict(server.TOOLS, {"plc_download_ruc": handler}):
            response = server.handle_tools_call(
                {"name": "plc_download_ruc", "arguments": arguments}
            )

        self.assertFalse(response["isError"])
        completed = next(item for item in self.records() if item["status"] == "succeeded")
        self.assertTrue(completed["result_summary"]["download_ok"])
        self.assertTrue(completed["result_summary"]["safety_bypassed"])
        self.assertEqual("runtime_reachable", completed["result_summary"]["deployment_state"])

    def test_handler_failure_is_audited(self) -> None:
        handler = Mock(side_effect=RuntimeError("simulated failure"))
        with patch.dict(server.TOOLS, {"plc_write_runtime_variable": handler}):
            response = server.handle_tools_call(
                {
                    "name": "plc_write_runtime_variable",
                    "arguments": self.valid_write_arguments(),
                }
            )

        self.assertTrue(response["isError"])
        records = self.records()
        self.assertEqual({"started", "failed"}, {item["status"] for item in records})
        failed = next(item for item in records if item["status"] == "failed")
        self.assertEqual("simulated failure", failed["error"])

    def test_validation_rejection_is_audited_without_execution(self) -> None:
        handler = Mock(return_value={"ok": True})
        arguments = self.valid_write_arguments()
        arguments.pop("target")
        with patch.dict(server.TOOLS, {"plc_write_runtime_variable": handler}):
            response = server.handle_tools_call(
                {"name": "plc_write_runtime_variable", "arguments": arguments}
            )

        self.assertTrue(response["isError"])
        self.assertEqual(["rejected"], [item["status"] for item in self.records()])
        handler.assert_not_called()

    def test_lock_conflict_is_audited_and_blocks_handler(self) -> None:
        arguments = self.valid_write_arguments()
        key = locks.lock_keys_for_tool("plc_write_runtime_variable", arguments)[0]
        held = locks.acquire_lock(key, directory=self.lock_dir)
        self.addCleanup(held.release)
        handler = Mock(return_value={"ok": True})

        with patch.dict(server.TOOLS, {"plc_write_runtime_variable": handler}):
            response = server.handle_tools_call(
                {"name": "plc_write_runtime_variable", "arguments": arguments}
            )

        payload = response["structuredContent"]
        self.assertTrue(response["isError"])
        self.assertIn("lock_conflict", payload)
        self.assertEqual({"started", "blocked"}, {item["status"] for item in self.records()})
        handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
