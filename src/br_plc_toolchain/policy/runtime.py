"""Runtime variable access decisions with immutable safety rules."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any

from br_plc_toolchain.backends.pvi.values import values_equal


def pvi_write_error(config: dict[str, Any], role: str, variable: str, *, execute: bool, writable: bool) -> str | None:
    if (config.get("pvi") or {}).get("enabled") is False:
        return "PVI is disabled"
    if role == "production":
        return "Production writes are permanently denied"
    if not execute:
        return "Variable writes require execute=true"
    if not writable:
        return "PVI reports the variable is not writable"
    pvi = config.get("pvi") or {}
    mode = pvi.get("write_policy", "whitelist")
    if role == "arsim" and mode != "blacklist":
        return None
    if mode not in ("whitelist", "blacklist"):
        return "Invalid PVI write policy"
    entries = pvi.get("write_whitelist" if mode == "whitelist" else "write_blacklist", [])
    if not isinstance(entries, list):
        return "PVI write policy entries must be a list"
    names = []
    for entry in entries:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append(f"{entry['task']}:{entry['name']}" if entry.get("task") else entry["name"])
        elif isinstance(entry, dict) and isinstance(entry.get("variable"), str):
            names.append(entry["variable"])
        else:
            return "Invalid PVI write policy entry"
    var = variable.lower()
    matched = any(fnmatch.fnmatchcase(var, name.lower()) or var.startswith(name.lower() + ".")
                  or var.startswith(name.lower() + "[") for name in names)
    if mode == "whitelist" and not matched:
        return "Variable is not in the PVI write whitelist"
    if mode == "blacklist" and matched:
        return "Variable matches the PVI write blacklist"
    return None


class AccessDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    operation: str
    risk: str
    reasons: tuple[str, ...]
    requires_session: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "operation": self.operation,
            "risk": self.risk,
            "reasons": list(self.reasons),
            "requires_session": self.requires_session,
        }


class RuntimePolicy:
    def authorize_read(self, *, config: dict[str, Any], variable: str) -> AccessDecision:
        if (config.get("pvi") or {}).get("enabled") is False:
            return AccessDecision(False, "read", "denied", ("PVI is disabled",))
        return AccessDecision(True, "read", "readonly", ("PVI reads are enabled",))

    def authorize_write(
        self,
        *,
        config: dict[str, Any],
        variable: str,
        current_value: Any,
        requested_value: Any,
        writable: bool,
        execute: bool,
        session_valid: bool,
    ) -> AccessDecision:
        role = str((config.get("target") or {}).get("role") or "unregistered").lower()
        error = pvi_write_error(config, role, variable, execute=execute, writable=writable)
        if error:
            return AccessDecision(False, "write", "denied", (error,))
        same_value = values_equal(current_value, requested_value)
        return AccessDecision(
            True,
            "same_value_write" if same_value else "changed_value_write",
            "low" if same_value else "target_change",
            ("PVI write policy permits the variable",),
        )

    @staticmethod
    def require(decision: AccessDecision) -> None:
        if not decision.allowed:
            raise AccessDenied("; ".join(decision.reasons))
