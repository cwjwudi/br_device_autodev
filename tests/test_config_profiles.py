from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"


def load_json(name: str) -> dict:
    return json.loads((TOOLS_DIR / name).read_text(encoding="utf-8-sig"))


class ConfigProfileTests(unittest.TestCase):
    def test_repository_default_is_conservative(self) -> None:
        config = load_json("plc_targets.local.json")
        policy = config["access_policy"]

        self.assertEqual("whitelist", policy["mode"])
        for key in (
            "allow_dynamic_pvi_read",
            "allow_dynamic_pvi_write",
            "allow_dynamic_opcua_read",
            "allow_dynamic_opcua_write",
        ):
            self.assertIs(policy[key], False, key)
        self.assertTrue(config["targets"]["arsim"]["allow_auto_download"])
        for name, target in config["targets"].items():
            if target["role"] != "arsim":
                self.assertIs(target["allow_auto_download"], False, name)

    def test_explicit_profiles_have_expected_risk_modes(self) -> None:
        expected = {
            "plc_targets.dev.example.json": ("dev_agent_directed", "agent_directed"),
            "plc_targets.test.example.json": ("test_whitelist", "whitelist"),
            "plc_targets.readonly.example.json": ("readonly_diagnostics", "whitelist"),
        }
        for filename, (profile_name, mode) in expected.items():
            with self.subTest(profile=filename):
                config = load_json(filename)
                self.assertEqual(profile_name, config["profile"]["name"])
                self.assertEqual(mode, config["access_policy"]["mode"])
                self.assertNotIn(
                    "production",
                    {role.lower() for role in config["access_policy"]["allowed_target_roles"]},
                )

    def test_only_development_profile_enables_dynamic_access(self) -> None:
        profiles = {
            name: load_json(name)
            for name in (
                "plc_targets.dev.example.json",
                "plc_targets.test.example.json",
                "plc_targets.readonly.example.json",
            )
        }
        for filename, config in profiles.items():
            enabled = any(
                config["access_policy"][key]
                for key in (
                    "allow_dynamic_pvi_read",
                    "allow_dynamic_pvi_write",
                    "allow_dynamic_opcua_read",
                    "allow_dynamic_opcua_write",
                )
            )
            self.assertEqual(filename == "plc_targets.dev.example.json", enabled)

    def test_environment_names_express_profile_risk(self) -> None:
        environments = load_json("plc_environments.json")
        expected_paths = {
            "default_safe": "tools\\plc_targets.local.json",
            "dev_agent_directed": "tools\\plc_targets.dev.example.json",
            "test_whitelist": "tools\\plc_targets.test.example.json",
            "readonly_diagnostics": "tools\\plc_targets.readonly.example.json",
        }

        for name, targets_path in expected_paths.items():
            with self.subTest(environment=name):
                self.assertIn(name, environments)
                self.assertEqual(targets_path, environments[name]["targets_path"])


if __name__ == "__main__":
    unittest.main()
