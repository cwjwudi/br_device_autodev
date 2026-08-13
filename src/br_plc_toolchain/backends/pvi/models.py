"""PVI backend data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Scope = Literal["task", "global"]


@dataclass(frozen=True, slots=True)
class PviTarget:
    name: str
    ip: str
    role: str = "unregistered"
    port: int = 11169
    cpu_name: str | None = None
    manager_timeout_s: int = 5
    communication_timeout_ms: int = 2500
    startup_wait_s: float = 5.0
    variable_link_wait_s: float = 0.25
    request_timeout_s: float = 15.0
    event_poll_s: float = 0.02
    pvi_dll_path: str | None = None

    @property
    def key(self) -> str:
        return f"{self.name}@{self.ip}:{self.port}"

    @property
    def pvi_object_name(self) -> str:
        return self.cpu_name or self.name.replace("-", "_")


@dataclass(frozen=True, slots=True)
class VariableRef:
    name: str
    scope: Scope = "task"
    task: str | None = None

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Variable name must not be empty")
        if self.scope not in {"task", "global"}:
            raise ValueError("scope must be 'task' or 'global'")
        if self.scope == "task" and not self.task:
            raise ValueError("task is required for task variables")

    @property
    def key(self) -> tuple[str, str | None, str]:
        return self.scope, self.task, self.name

    @property
    def canonical(self) -> str:
        return f"{self.task}:{self.name}" if self.scope == "task" else self.name


def parse_variable_ref(spec: str) -> VariableRef:
    """Parse the compact MCP variable spelling into a validated reference.

    A plain name is a global variable.  A single task separator denotes a
    task variable (for example ``Main:bEnable``).  PVI paths containing
    colons are intentionally left as global names; task variables should use
    the explicit ``task:name`` form at the MCP boundary.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("Variable name must be a non-empty string")
    text = spec.strip()
    if ":" in text and not text.startswith("::"):
        task, name = text.split(":", 1)
        if task and name and ":" not in task:
            ref = VariableRef(name=name, scope="task", task=task)
            ref.validate()
            return ref
    ref = VariableRef(name=text, scope="global")
    ref.validate()
    return ref

