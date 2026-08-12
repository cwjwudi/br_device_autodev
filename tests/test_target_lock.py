from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "mcp_server"))

import locks  # noqa: E402
import schemas  # noqa: E402


class TargetLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.lock_dir = Path(self.temp_dir.name)

    def test_same_resource_cannot_be_locked_twice(self) -> None:
        first = locks.acquire_lock("target:test:arsim", directory=self.lock_dir)
        self.addCleanup(first.release)

        with self.assertRaises(locks.LockConflict) as caught:
            locks.acquire_lock("target:test:arsim", directory=self.lock_dir)

        self.assertEqual("target:test:arsim", caught.exception.key)
        self.assertEqual(first.path, caught.exception.path)

    def test_different_resources_can_be_locked_together(self) -> None:
        with locks.acquire_locks(
            ["target:test:arsim", "project:test:x1685"], directory=self.lock_dir
        ) as acquired:
            self.assertEqual(2, len(acquired))
            self.assertEqual(2, len(list(self.lock_dir.glob("*.lock.json"))))

        self.assertEqual([], list(self.lock_dir.glob("*.lock.json")))

    def test_released_resource_can_be_reacquired(self) -> None:
        first = locks.acquire_lock("target:test:arsim", directory=self.lock_dir)
        first.release()

        second = locks.acquire_lock("target:test:arsim", directory=self.lock_dir)
        second.release()

    def test_stale_lock_is_reclaimed(self) -> None:
        key = "target:test:arsim"
        path = locks.lock_path(key, self.lock_dir)
        path.write_text(
            json.dumps({"key": key, "token": "old", "created_epoch": time.time() - 10}),
            encoding="utf-8",
        )

        current = locks.acquire_lock(
            key, directory=self.lock_dir, stale_after_seconds=1
        )
        self.addCleanup(current.release)

        self.assertNotEqual("old", current.token)

    def test_lock_classification_covers_target_changes_and_builds(self) -> None:
        target_changes = {
            name
            for name, risk in schemas.TOOL_RISK_LEVELS.items()
            if risk == "target_change"
        }
        self.assertEqual(target_changes, locks.TARGET_SCOPED_TOOLS)
        self.assertIn("plc_build_project", locks.PROJECT_SCOPED_TOOLS)
        self.assertIn("plc_add_project_library", locks.PROJECT_SCOPED_TOOLS)

    def test_closed_loop_locks_project_and_target(self) -> None:
        keys = locks.lock_keys_for_tool(
            "plc_run_arsim_closed_loop",
            {"target": "arsim", "project_path": "C:\\workspace\\Demo.apj"},
        )

        self.assertEqual(2, len(keys))
        self.assertTrue(any(key.startswith("project:") for key in keys))
        self.assertTrue(any(key.startswith("target:") for key in keys))


if __name__ == "__main__":
    unittest.main()
