from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


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
            "access_policy": {
                "mode": "agent_directed",
                "allow_dynamic_pvi_read": True,
                "allow_dynamic_pvi_write": True,
                "allow_dynamic_opcua_read": True,
                "allowed_target_roles": ["arsim"],
            },
            "pvi": {"enabled": True, "read_whitelist": [], "write_whitelist": []},
            "opcua": {"validation_node_ids": []},
        }

    def create_build_artifacts(self, *, newer_than_source: bool = True) -> Path:
        header = (
            self.project_root
            / "Temp"
            / "Includes"
            / "Harness"
            / "Variablesvar.h"
        )
        header.parent.mkdir(parents=True)
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
        symbol_map.parent.mkdir(parents=True)
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
        self.assertEqual("low", catalog["confidence"])
        self.assertTrue(catalog["warnings"])
        variable = next(item for item in catalog["variables"] if item["name"] == "Input")
        self.assertEqual("source_scan", variable["catalog_source"])
        self.assertEqual("low", variable["confidence"])

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
