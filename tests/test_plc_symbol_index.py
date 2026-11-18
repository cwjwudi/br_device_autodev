from __future__ import annotations

import os
import json
import concurrent.futures
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import plc_symbol_index as symbol_index  # noqa: E402


class PlcSymbolIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.project_root = Path(self.temp_dir.name) / "Project"
        self.source = self.project_root / "Logical" / "Harness" / "Variables.var"
        self.source.parent.mkdir(parents=True)
        self.source.write_text(
            "VAR\n    Input : REAL;\n    Output : ARRAY[0..1] OF REAL;\nEND_VAR\n",
            encoding="utf-8",
        )
        self.targets_file = Path(self.temp_dir.name) / "targets.json"
        self.config = {
            "pvi": {"enabled": True, "read_whitelist": ["Harness:Input"], "write_whitelist": []},
            "opcua": {"validation_node_ids": []},
        }
        self.targets_file.write_text(json.dumps(self.config), encoding="utf-8")

    def create_build_artifacts(self, *, newer_than_source: bool = True) -> Path:
        header = (
            self.project_root
            / "Temp"
            / "Includes"
            / "Harness"
            / "Variablesvar.h"
        )
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text(
            "\n".join(
                [
                    "/* Automation Studio generated header file */",
                    "_BUR_LOCAL float Input;",
                    "_BUR_LOCAL float Output[2];",
                    '__asm__("iecfile \\\"Logical/Harness/Variables.var\\\" scope \\\"local\\\"");',
                ]
            ),
            encoding="utf-8",
        )
        symbol_map = self.project_root / "Temp" / "Objects" / "Symbols.map"
        symbol_map.parent.mkdir(parents=True, exist_ok=True)
        symbol_map.write_bytes(b"build-symbol-evidence")
        now = time.time()
        if newer_than_source:
            os.utime(self.source, (now - 20, now - 20))
            os.utime(header, (now, now))
            os.utime(symbol_map, (now, now))
        else:
            os.utime(header, (now - 20, now - 20))
            os.utime(symbol_map, (now - 20, now - 20))
            os.utime(self.source, (now, now))
        return header

    def build(self) -> dict:
        return symbol_index.build_catalog(
            self.config,
            str(self.targets_file),
            project_root=self.project_root,
        )

    def test_source_scan_is_low_confidence_fallback(self) -> None:
        catalog = self.build()

        self.assertEqual("source_scan", catalog["catalog_source"])
        self.assertNotIn("access_policy", catalog)
        self.assertEqual("low", catalog["confidence"])
        self.assertTrue(catalog["warnings"])
        variable = next(item for item in catalog["variables"] if item["name"] == "Input")
        self.assertEqual("source_scan", variable["catalog_source"])
        self.assertEqual("low", variable["confidence"])

    def test_large_source_catalog_resolves_path_per_file(self) -> None:
        self.source.write_text(
            "VAR\n" + "".join(f"    Point{i:05d} : DINT;\n" for i in range(11000)) + "END_VAR\n",
            encoding="utf-8",
        )
        with patch.object(symbol_index, "relative_path", wraps=symbol_index.relative_path) as resolve:
            catalog = self.build()
        self.assertEqual(11001, len(catalog["variables"]))  # includes configured Harness:Input
        self.assertLess(resolve.call_count, 10)

    def test_cache_reuses_and_refreshes_source_config_and_file_set(self) -> None:
        cache = self.project_root / ".br-auto-dev" / "plc_symbol_catalog.json"
        first, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        saved = cache.read_bytes()
        with patch.object(symbol_index, "build_catalog", wraps=symbol_index.build_catalog) as build:
            second, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("hit", status)
        build.assert_not_called()
        self.assertEqual(saved, cache.read_bytes())
        self.assertEqual(first["generated_at"], second["generated_at"])

        original_stat = self.source.stat()
        self.source.write_text("VAR\n    Other : REAL;\n    Output : ARRAY[0..1] OF REAL;\nEND_VAR\n", encoding="utf-8")
        os.utime(self.source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        refreshed, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertIn("Harness:Other", [item["pvi"] for item in refreshed["variables"]])

        added = self.project_root / "Logical" / "Global.var"
        added.write_text("VAR\n    GlobalPoint : DINT;\nEND_VAR\n", encoding="utf-8")
        refreshed, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertIn("GlobalPoint", [item["pvi"] for item in refreshed["variables"]])
        added.unlink()
        refreshed, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertNotIn("GlobalPoint", [item["pvi"] for item in refreshed["variables"]])

        self.config["pvi"]["write_whitelist"] = ["Harness:Other"]
        self.targets_file.write_text(json.dumps(self.config), encoding="utf-8")
        refreshed, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertIn("write", next(item for item in refreshed["variables"] if item["pvi"] == "Harness:Other")["access"])
        cache.write_text("{broken", encoding="utf-8")
        self.assertEqual("rebuilt", symbol_index.cached_catalog(self.targets_file, self.project_root, cache)[1])

    def test_cache_does_not_reuse_unchanged_generated_headers_after_source_change(self) -> None:
        self.create_build_artifacts()
        cache = self.project_root / ".br-auto-dev" / "plc_symbol_catalog.json"
        first, _ = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("automation_studio_build_artifacts", first["catalog_source"])
        old = self.source.stat()
        self.source.write_text("VAR\n    Other : REAL;\nEND_VAR\n", encoding="utf-8")
        os.utime(self.source, ns=(old.st_atime_ns, old.st_mtime_ns))
        updated, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertEqual("source_scan", updated["catalog_source"])
        self.assertIn("Harness:Other", [item["pvi"] for item in updated["variables"]])
        self.assertEqual("hit", symbol_index.cached_catalog(self.targets_file, self.project_root, cache)[1])
        self.targets_file.write_text(json.dumps({"pvi": {}}), encoding="utf-8")
        updated, _ = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("source_scan", updated["catalog_source"])
        self.create_build_artifacts()
        updated, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertEqual("automation_studio_build_artifacts", updated["catalog_source"])

    def test_cache_retries_when_source_changes_during_build(self) -> None:
        cache = self.project_root / ".br-auto-dev" / "plc_symbol_catalog.json"
        original_build = symbol_index.build_catalog
        builds = 0

        def change_during_build(*args, **kwargs):
            nonlocal builds
            result = original_build(*args, **kwargs)
            builds += 1
            if builds == 1:
                self.source.write_text("VAR\n    ChangedDuringBuild : REAL;\nEND_VAR\n", encoding="utf-8")
            return result

        with patch.object(symbol_index, "build_catalog", side_effect=change_during_build):
            catalog, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertEqual(2, builds)
        self.assertIn("Harness:ChangedDuringBuild", [item["pvi"] for item in catalog["variables"]])
        self.assertIn("Harness:ChangedDuringBuild", [item["pvi"] for item in json.loads(cache.read_text(encoding="utf-8"))["variables"]])

    def test_separate_projects_keep_separate_catalogs(self) -> None:
        other = Path(self.temp_dir.name) / "Other"
        (other / "Logical").mkdir(parents=True)
        (other / "Logical" / "Global.var").write_text("VAR\n    OtherProject : DINT;\nEND_VAR\n", encoding="utf-8")
        first = self.project_root / ".br-auto-dev" / "plc_symbol_catalog.json"
        second = other / ".br-auto-dev" / "plc_symbol_catalog.json"
        a, _ = symbol_index.cached_catalog(self.targets_file, self.project_root, first)
        b, _ = symbol_index.cached_catalog(self.targets_file, other, second)
        self.assertNotIn("OtherProject", [item["pvi"] for item in a["variables"]])
        self.assertIn("OtherProject", [item["pvi"] for item in b["variables"]])
        self.assertEqual("hit", symbol_index.cached_catalog(self.targets_file, self.project_root, first)[1])

    def test_cache_retries_replacement_and_handles_concurrent_writers(self) -> None:
        cache = self.project_root / ".br-auto-dev" / "plc_symbol_catalog.json"
        replace = os.replace
        attempts = 0

        def temporarily_locked(source, target):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise PermissionError("cache is temporarily in use")
            return replace(source, target)

        with patch.object(symbol_index.os, "replace", side_effect=temporarily_locked):
            catalog, status = symbol_index.cached_catalog(self.targets_file, self.project_root, cache)
        self.assertEqual("rebuilt", status)
        self.assertEqual(3, attempts)
        cache.unlink()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(lambda _: symbol_index.cached_catalog(self.targets_file, self.project_root, cache), range(5)))
        self.assertTrue(all(result[0]["variables"] == catalog["variables"] for result in results))
        self.assertEqual(catalog["variables"], json.loads(cache.read_text(encoding="utf-8"))["variables"])

    def test_stdio_list_works_while_client_input_remains_open(self) -> None:
        project = self.project_root / "Demo.apj"
        project.write_text('<Project xmlns="http://br-automation.co.at/AS/Project"/>', encoding="utf-8")
        (self.project_root.parent / "br-auto-dev.json").write_text(json.dumps({
            "project_path": "Project/Demo.apj", "config": "Sim", "toolchain": "as6_default",
            "target": "arsim", "targets": {"arsim": {"ip": "127.0.0.1", "role": "arsim"}},
        }), encoding="utf-8")
        override_dir = self.project_root.parent / "override"
        override_dir.mkdir()
        override_targets = override_dir / "targets.json"
        override_targets.write_text(json.dumps(self.config), encoding="utf-8")
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "plc_list_variables", "arguments": {"project_path": str(project), "limit": 1,
                                                          "targets_path": str(override_targets)},
        }}
        process = subprocess.Popen([sys.executable, str(REPO_ROOT / "tools/mcp_server/server.py")],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, encoding="utf-8", cwd=REPO_ROOT)
        try:
            assert process.stdin and process.stdout
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
            response = json.loads(lines.get(timeout=10))
            first = response["result"]["structuredContent"]
            self.assertTrue(first["ok"])
            self.assertEqual("rebuilt", first["data"]["cache_status"])
            self.assertEqual(self.project_root.parent / ".br-auto-dev" / "plc_symbol_catalog.json",
                             Path(first["data"]["catalog_path"]))
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
            second = json.loads(lines.get(timeout=10))["result"]["structuredContent"]
            self.assertEqual("hit", second["data"]["cache_status"])
            self.source.write_text("VAR\n    Changed : REAL;\nEND_VAR\n", encoding="utf-8")
            cache = Path(first["data"]["catalog_path"])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if any(item["pvi"] == "Harness:Changed" for item in json.loads(cache.read_text(encoding="utf-8"))["variables"]):
                    break
                time.sleep(0.1)
            else:
                self.fail("cache did not refresh after the source changed")
            request["params"]["name"] = "plc_search_variables"
            request["params"]["arguments"]["query"] = "Changed"
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
            changed = json.loads(lines.get(timeout=10))["result"]["structuredContent"]["data"]
            self.assertEqual("hit", changed["cache_status"])
            self.assertEqual("Harness:Changed", changed["variables"][0]["pvi"])
        finally:
            process.terminate()
            process.wait(timeout=5)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()

    def test_fresh_build_headers_are_preferred_with_high_confidence(self) -> None:
        header = self.create_build_artifacts(newer_than_source=True)

        catalog = self.build()

        self.assertEqual("automation_studio_build_artifacts", catalog["catalog_source"])
        self.assertEqual("high", catalog["confidence"])
        self.assertIn(symbol_index.relative_path(header), catalog["generated_from"])
        variable = next(item for item in catalog["variables"] if item["name"] == "Output")
        self.assertEqual("task", variable["scope"])
        self.assertEqual("Harness", variable["task"])
        self.assertEqual("REAL[2]", variable["type"])
        self.assertEqual("automation_studio_generated_header", variable["catalog_source"])
        self.assertEqual("high", variable["confidence"])

    def test_stale_build_headers_fall_back_to_source_scan(self) -> None:
        self.create_build_artifacts(newer_than_source=False)

        catalog = self.build()

        self.assertEqual("source_scan", catalog["catalog_source"])
        self.assertEqual("low", catalog["confidence"])
        self.assertTrue(any("older" in warning for warning in catalog["warnings"]))

    def test_config_only_variable_records_configured_provenance(self) -> None:
        self.source.unlink()
        self.config["pvi"]["read_whitelist"] = [
            {"scope": "task", "task": "Harness", "name": "Configured", "type": "BOOL"}
        ]

        catalog = self.build()

        variable = next(
            item for item in catalog["variables"] if item["pvi"] == "Harness:Configured"
        )
        self.assertEqual("target_config", variable["catalog_source"])
        self.assertEqual("configured", variable["confidence"])
        self.assertEqual([str(self.targets_file.resolve())], variable["generated_from"])

    def test_filter_preserves_catalog_provenance(self) -> None:
        self.create_build_artifacts(newer_than_source=True)
        catalog = self.build()

        result = symbol_index.filter_catalog(
            catalog, query="Input", module="Harness", access="read"
        )

        self.assertEqual(catalog["catalog_source"], result["catalog_source"])
        self.assertEqual(catalog["confidence"], result["confidence"])
        self.assertEqual(1, result["count"])
        self.assertTrue(any("not live PVI permissions" in warning for warning in result["warnings"]))

    def test_filter_paginates_without_losing_match_counts(self) -> None:
        catalog = self.build()

        first = symbol_index.filter_catalog(
            catalog, query=None, module=None, access=None, offset=0, limit=1
        )
        second = symbol_index.filter_catalog(
            catalog, query=None, module=None, access=None, offset=1, limit=1
        )

        self.assertEqual(1, first["count"])
        self.assertEqual(2, first["matched_count"])
        self.assertEqual(2, first["total_count"])
        self.assertTrue(first["truncated"])
        self.assertEqual(1, first["next_offset"])
        self.assertEqual(1, second["count"])
        self.assertFalse(second["truncated"])
        self.assertIsNone(second["next_offset"])


if __name__ == "__main__":
    unittest.main()
