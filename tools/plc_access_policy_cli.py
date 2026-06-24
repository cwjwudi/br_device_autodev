#!/usr/bin/env python
"""Stable JSON command-line interface for the shared PLC access policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from plc_access_policy import evaluate_access_request


OPERATIONS = ("describe", "pvi_read", "pvi_write", "opcua_read")


def load_items(raw: str | None, items_file: str | None) -> list[Any]:
    if items_file:
        raw = Path(items_file).read_text(encoding="utf-8-sig")
    if raw in (None, ""):
        return []
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("--items-json must contain a JSON array.")
    return value


def load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Targets configuration must be a JSON object.")
    return value


def error_payload(args: argparse.Namespace, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": args.operation,
        "errors": [message],
        "blocked_reason": message,
        "policy_mode": None,
        "policy": None,
        "target": args.target,
        "target_role": None,
        "requested_items": [],
        "explicit": bool(args.explicit),
        "execute": bool(args.execute),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=OPERATIONS, required=True)
    parser.add_argument("--targets-file", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--items-json", default="[]")
    parser.add_argument("--items-file")
    parser.add_argument("--explicit", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        targets_path = Path(args.targets_file).resolve()
        config = load_config(targets_path)
        target_config = (config.get("targets") or {}).get(args.target)
        if not isinstance(target_config, dict):
            raise ValueError(
                f"Target '{args.target}' was not found in {targets_path}."
            )
        result = evaluate_access_request(
            operation=args.operation,
            config=config,
            target_name=args.target,
            target_config=target_config,
            targets_file=str(targets_path),
            requested_items=load_items(args.items_json, args.items_file),
            explicit=args.explicit,
            execute=args.execute,
        )
    except Exception as exc:
        result = error_payload(args, str(exc))

    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
