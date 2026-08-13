from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "tools" / "plc_toolchain.ps1"


class DownloadConfigurationIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8-sig")

    def test_probe_does_not_use_automation_studio_config_as_runtime_id(self) -> None:
        self.assertIn("automation_studio_config = if ($Config)", self.script)
        self.assertIn(
            'configuration_id = if ($targetConfig.configuration_id) { [string]$targetConfig.configuration_id } else { $null }',
            self.script,
        )
        self.assertNotIn(
            'configuration_id = if ($targetConfig.configuration_id) { [string]$targetConfig.configuration_id } else { $Config }',
            self.script,
        )

    def test_bound_arsim_uses_hardware_configuration_id_as_expected_metadata(self) -> None:
        self.assertIn("function Get-ProjectConfigurationMetadata", self.script)
        self.assertIn('configuration_id_source = "project_hardware"', self.script)
        self.assertIn("function Test-ArsimProjectBinding", self.script)
        self.assertIn("$probe.expected_configuration_id", self.script)

    def test_unknown_target_id_is_not_reported_as_a_mismatch(self) -> None:
        self.assertIn('errorCodes.Add("TARGET_METADATA_UNKNOWN")', self.script)
        self.assertIn(
            "it was not inferred from the Automation Studio config name '$Config'",
            self.script,
        )

    def test_bound_arsim_reads_version_and_partition_from_its_media(self) -> None:
        self.assertIn("function Get-BoundArsimMediaMetadata", self.script)
        self.assertIn('"RPSHD\\SYSROM\\prjver.sys"', self.script)
        self.assertIn('"SYSTEM\\TOC\\fscfg.xml"', self.script)
        self.assertIn('partition_layout_source = "bound_arsim_media_sha256"', self.script)

    def test_transfer_payload_partition_and_safe_policy_are_verified(self) -> None:
        self.assertIn('"FDATA\\SYSTEM\\TOC\\fscfg.xml"', self.script)
        self.assertIn('$packagePartitionLayoutSource = "transfer_payload_sha256"', self.script)
        self.assertIn("function Get-TransferPolicy", self.script)
        self.assertIn('$transferPolicy.install_mode -eq "Consistent"', self.script)
        self.assertIn('$transferPolicy.install_restriction -eq "AllowUpdatesWithoutDataLoss"', self.script)


if __name__ == "__main__":
    unittest.main()
