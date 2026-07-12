"""Runtime variable access decisions with immutable safety rules."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any

from br_plc_toolchain.backends.pvi.values import values_equal
from br_plc_toolchain.config.loader import IMMUTABLE_SAFETY_BASELINE


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
    def _blocked(self, variable: str) -> str | None:
        lowered = variable.lower()
        for pattern in IMMUTABLE_SAFETY_BASELINE["blocked_name_patterns"]:
            if fnmatch.fnmatch(lowered, str(pattern).lower()):
                return str(pattern)
        return None

    def authorize_read(self, *, config: dict[str, Any], variable: str) -> AccessDecision:
        role = str((config.get("target") or {}).get("role") or "unregistered").lower()
        if role == "production" and not config.get("access", {}).get("dynamic_read", False):
            return AccessDecision(False, "read", "denied", ("Production profile disables dynamic reads",))
        if not config.get("access", {}).get("dynamic_read", True):
            return AccessDecision(False, "read", "denied", ("Dynamic read is disabled by the profile",))
        return AccessDecision(True, "read", "readonly", ("Runtime discovery read is enabled",))

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
        blocked = self._blocked(variable)
        if role == "production":
            return AccessDecision(False, "write", "denied", ("Production writes are permanently denied",))
        if blocked:
            return AccessDecision(
                False, "write", "denied", (f"Variable matches immutable blocked pattern {blocked!r}",)
            )
        if not writable:
            return AccessDecision(False, "write", "denied", ("PVI reports the variable is not writable",))
        if not execute:
            return AccessDecision(False, "write", "denied", ("Variable writes require execute=true",))

        same_value = values_equal(current_value, requested_value)
        access = config.get("access") or {}
        if same_value:
            if access.get("same_value_write", False):
                return AccessDecision(
                    True,
                    "same_value_write",
                    "low",
                    ("Target profile permits same-value write verification",),
                )
            return AccessDecision(False, "write", "denied", ("Profile disables same-value writes",))

        if not access.get("changed_value_write", False):
            return AccessDecision(False, "write", "denied", ("Profile disables changed-value writes",))
        if access.get("changed_value_requires_session", True) and not session_valid:
            return AccessDecision(
                False,
                "changed_value_write",
                "target_change",
                ("Changed-value write requires an active target-bound test session",),
                requires_session=True,
            )
        return AccessDecision(
            True,
            "changed_value_write",
            "target_change",
            ("Dedicated test session permits changed-value write",),
            requires_session=True,
        )

    @staticmethod
    def require(decision: AccessDecision) -> None:
        if not decision.allowed:
            raise AccessDenied("; ".join(decision.reasons))

