"""Refresh catalogs while the MCP server is running."""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from plc_symbol_index import cached_catalog, catalog_fingerprints  # noqa: E402

LOG = logging.getLogger(__name__)


class CatalogWatcher:
    def __init__(self, interval: float = 2.0):
        self._interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._projects: dict[Path, tuple[Path, Path, dict]] = {}
        self._thread = threading.Thread(target=self._run, name="catalog-watch", daemon=True)
        self._thread.start()

    def register(self, targets: Path, project: Path, output: Path) -> None:
        catalog = json.loads(output.read_text(encoding="utf-8"))
        fingerprints = catalog["_cache"]["fingerprints"]
        with self._lock:
            self._projects[output] = (targets, project, fingerprints)

    def _run(self) -> None:
        failures: set[Path] = set()
        while not self._stop.wait(self._interval):
            with self._lock:
                projects = list(self._projects.items())
            for output, (targets, project, previous) in projects:
                try:
                    if catalog_fingerprints(project, targets) != previous:
                        catalog, _ = cached_catalog(targets, project, output)
                        with self._lock:
                            if self._projects.get(output) == (targets, project, previous):
                                self._projects[output] = (targets, project, catalog["_cache"]["fingerprints"])
                    failures.discard(output)
                except Exception:
                    if output not in failures:
                        LOG.exception("Could not refresh variable catalog %s", output)
                        failures.add(output)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
