from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


def load_json(path: str) -> dict:
    return json.loads((CONFIG_DIR / path).read_text(encoding="utf-8-sig"))


class ConfigProfileTests(unittest.TestCase):
    def test_repository_default_is_conservative(self) -> None:
        config = load_json("targets/default-safe.json")
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

    def test_legacy_cli_examples_are_grouped_under_config_examples(self) -> None:
        expected = {
            "examples/targets/development.example.json": ("dev_agent_directed", "agent_directed"),
            "examples/targets/office-test.example.json": ("test_whitelist", "whitelist"),
            "examples/targets/readonly.example.json": ("readonly_diagnostics", "whitelist"),
        }
        for path, (profile_name, mode) in expected.items():
            with self.subTest(profile=path):
                config = load_json(path)
                self.assertEqual(profile_name, config["profile"]["name"])
                self.assertEqual(mode, config["access_policy"]["mode"])
                self.assertNotIn(
                    "production",
                    {role.lower() for role in config["access_policy"]["allowed_target_roles"]},
                )

    def test_only_development_legacy_example_enables_dynamic_access(self) -> None:
        paths = (
            "examples/targets/development.example.json",
            "examples/targets/office-test.example.json",
            "examples/targets/readonly.example.json",
        )
        for path in paths:
            config = load_json(path)
            enabled = any(
                config["access_policy"][key]
                for key in (
                    "allow_dynamic_pvi_read",
                    "allow_dynamic_pvi_write",
                    "allow_dynamic_opcua_read",
                    "allow_dynamic_opcua_write",
                )
            )
            self.assertEqual(path.endswith("development.example.json"), enabled)

    def test_environment_paths_use_structured_config_tree(self) -> None:
        environments = load_json("environments/environments.json")
        self.assertEqual(
            "config\\targets\\default-safe.json",
            environments["default_safe"]["targets_path"],
        )
        self.assertEqual("office-test", environments["office_test_233"]["access_profile"])
        self.assertEqual("arsim-development", environments["local_arsim"]["access_profile"])
        for environment in environments.values():
            path = environment.get("targets_path")
            if path:
                self.assertTrue(path.startswith("config\\"), path)


if __name__ == "__main__":
    unittest.main()
