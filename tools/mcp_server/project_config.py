"""Discover a project's configuration without relying on the server's cwd."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from br_plc_toolchain.config.loader import PROJECT_CONFIG_NAME as NAME, load_project_config

__all__ = ["NAME", "load_project_config"]
