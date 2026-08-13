from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


__version__ = "0.14.0"
SERVER_STARTED_AT = datetime.now(UTC).isoformat()


def _git_revision() -> str:
    root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


SERVER_RUNTIME = {
    "version": __version__,
    "git_revision": _git_revision(),
    "started_at": SERVER_STARTED_AT,
    "process_id": os.getpid(),
}
