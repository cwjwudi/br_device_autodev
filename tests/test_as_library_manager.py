from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from as_library_manager import (  # noqa: E402
    add_project_library,
    find_library_for_symbol,
    plan_library_add,
    rollback_transaction,
)


PACKAGE_NS = "http://br-automation.co.at/AS/Package"


def write_library(
    directory: Path,
    name: str,
    *,
    version: str | None = None,
    dependencies: list[tuple[str, str | None, str | None]] | None = None,
    function_name: str | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    attributes = f' Version="{version}"' if version else ""
    dependency_xml = ""
    if dependencies:
        entries = []
        for dependency, minimum, maximum in dependencies:
            version_attributes = ""
            if minimum:
                version_attributes += f' FromVersion="{minimum}"'
            if maximum:
                version_attributes += f' ToVersion="{maximum}"'
            entries.append(f'    <Dependency ObjectName="{dependency}"{version_attributes} />')
        dependency_xml = "\n  <Dependencies>\n" + "\n".join(entries) + "\n  </Dependencies>"
    function_file = f"{name}.fun"
    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Library xmlns="http://br-automation.co.at/AS/Library"{attributes} Description="{name} test library">\n'
        "  <Files>\n"
        f"    <File>{function_file}</File>\n"
        "  </Files>"
        f"{dependency_xml}\n"
        "</Library>\n"
    )
    (directory / "binary.lby").write_text(manifest, encoding="utf-8")
    declaration = function_name or f"{name}Function"
    (directory / function_file).write_text(
        f"FUNCTION_BLOCK {declaration}\nEND_FUNCTION_BLOCK\n",
        encoding="utf-8",
    )


class LibraryManagerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()
        self.project_root = self.repo_root / "Demo"
        self.project_path = self.project_root / "Demo.apj"
        self.libraries_dir = self.project_root / "Logical" / "Libraries"
        self.libraries_dir.mkdir(parents=True)

        self.project_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<Project xmlns="http://br-automation.co.at/AS/Project">\n'
            "  <TechnologyPackages />\n"
            "</Project>\n",
            encoding="utf-8",
        )
        self.original_package = (
            '<?xml version="1.0" encoding="utf-8"?>\r\n'
            '<?AutomationStudio FileVersion="4.9"?>\r\n'
            '<Package xmlns="http://br-automation.co.at/AS/Package">\r\n'
            "  <Objects>\r\n"
            '    <Object Type="Library" Language="binary">runtime</Object>\r\n'
            "  </Objects>\r\n"
            "</Package>\r\n"
        )
        self.package_path = self.libraries_dir / "Package.pkg"
        self.package_path.write_bytes(self.original_package.encode("utf-8"))
        write_library(self.libraries_dir / "runtime", "runtime")

        self.install_root = self.repo_root / "FakeAS"
        self.core_root = self.install_root / "AS" / "Library_2"
        write_library(self.core_root / "runtime", "runtime")
        write_library(
            self.core_root / "AsTCP",
            "AsTCP",
            dependencies=[("runtime", None, None)],
            function_name="TcpOpen",
        )

        self.targets_file = self.repo_root / "tools" / "targets.json"
        self.targets_file.parent.mkdir(parents=True)
        self.targets_file.write_text(
            json.dumps(
                {
                    "automation_studio": {
                        "build_exe": str(self.install_root / "bin-en" / "BR.AS.Build.exe"),
                    }
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_finds_exact_symbol_and_dependency(self) -> None:
        result = find_library_for_symbol(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "TcpOpen",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["AsTCP"], [item["name"] for item in result["matches"]])
        self.assertEqual("function_block", result["matches"][0]["matched_symbols"][0]["kind"])
        self.assertEqual("runtime", result["matches"][0]["dependencies"][0]["name"])

    def test_plan_only_adds_missing_library(self) -> None:
        result = plan_library_add(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "AsTCP",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["AsTCP"], [item["name"] for item in result["libraries_to_add"]])

    def test_plan_repairs_package_entry_with_missing_directory(self) -> None:
        package = self.original_package.replace(
            "  </Objects>",
            '    <Object Type="Library" Language="binary">AsTCP</Object>\r\n  </Objects>',
        )
        self.package_path.write_bytes(package.encode("utf-8"))

        result = plan_library_add(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "AsTCP",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["AsTCP"], [item["name"] for item in result["libraries_to_add"]])

    def test_explicit_version_must_match_existing_library(self) -> None:
        write_library(self.libraries_dir / "AsTCP", "AsTCP", version="2.0", function_name="TcpOpen")
        package = self.original_package.replace(
            "  </Objects>",
            '    <Object Type="Library" Language="binary">AsTCP</Object>\r\n  </Objects>',
        )
        self.package_path.write_bytes(package.encode("utf-8"))

        result = plan_library_add(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "AsTCP",
            "1.0",
        )

        self.assertFalse(result["ok"])
        self.assertTrue(any("does not match requested version 1.0" in item for item in result["errors"]))

    def test_add_requires_execute_without_mutating_project(self) -> None:
        result = add_project_library(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "AsTCP",
            None,
            False,
        )

        self.assertFalse(result["ok"])
        self.assertFalse((self.libraries_dir / "AsTCP").exists())
        self.assertEqual(self.original_package.encode("utf-8"), self.package_path.read_bytes())

    def test_add_and_rollback_are_transactional(self) -> None:
        result = add_project_library(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "AsTCP",
            None,
            True,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["executed"])
        self.assertTrue((self.libraries_dir / "AsTCP" / "binary.lby").is_file())
        root = ET.parse(self.package_path).getroot()
        names = [
            (element.text or "").strip()
            for element in root.findall(f".//{{{PACKAGE_NS}}}Object")
        ]
        self.assertEqual(["runtime", "AsTCP"], names)

        rollback = rollback_transaction(self.repo_root, result["transaction_id"])
        self.assertTrue(rollback["ok"])
        self.assertFalse((self.libraries_dir / "AsTCP").exists())
        self.assertEqual(self.original_package.encode("utf-8"), self.package_path.read_bytes())

    def test_existing_library_is_a_noop(self) -> None:
        first = add_project_library(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "AsTCP",
            None,
            True,
        )
        self.assertTrue(first["ok"])

        second = add_project_library(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "AsTCP",
            None,
            True,
        )
        self.assertTrue(second["ok"])
        self.assertTrue(second["already_satisfied"])
        self.assertFalse(second["executed"])

    def test_concurrent_project_edit_is_blocked(self) -> None:
        lock_path = self.libraries_dir / ".as_library_manager.lock"
        lock_path.write_text("pid=123 transaction=other\n", encoding="utf-8")
        try:
            result = add_project_library(
                self.repo_root,
                self.project_path,
                self.targets_file,
                "AsTCP",
                None,
                True,
            )
        finally:
            lock_path.unlink()

        self.assertFalse(result["ok"])
        self.assertTrue(any("another library transaction" in item for item in result["errors"]))
        self.assertFalse((self.libraries_dir / "AsTCP").exists())

    def test_rejects_missing_technology_package(self) -> None:
        mp_report = (
            self.install_root
            / "AS"
            / "TechnologyPackages"
            / "mappServices"
            / "6.5.1"
            / "Library"
            / "MpReport"
            / "V6.5.1"
        )
        write_library(mp_report, "MpReport", version="6.5.1", function_name="MpReportCore")

        result = plan_library_add(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "MpReport",
        )

        self.assertFalse(result["ok"])
        self.assertTrue(any("requires Technology Package mappServices 6.5.1" in item for item in result["errors"]))

    def test_rejects_safety_related_library(self) -> None:
        result = plan_library_add(
            self.repo_root,
            self.project_path,
            self.targets_file,
            "SafetyBase",
        )

        self.assertFalse(result["ok"])
        self.assertTrue(any("Safety-related" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
