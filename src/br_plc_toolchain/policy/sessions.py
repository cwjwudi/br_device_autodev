"""Short-lived write authorization sessions for ARsim and dedicated test PLCs."""

from __future__ import annotations

import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class TestSession:
    session_id: str
    target_key: str
    target_name: str
    role: str
    mode: str
    created_at: datetime
    expires_at: datetime
    fingerprint: dict[str, Any]

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["created_at"] = self.created_at.isoformat()
        result["expires_at"] = self.expires_at.isoformat()
        result["expired"] = self.expired
        return result


class TestSessionManager:
    def __init__(self, clock: Callable[[], datetime] | None = None):
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sessions: dict[str, TestSession] = {}
        self._lock = threading.RLock()

    def open(
        self,
        *,
        target_key: str,
        target_name: str,
        role: str,
        ttl_minutes: int,
        fingerprint: dict[str, Any],
        execute: bool,
    ) -> TestSession:
        normalized_role = role.lower()
        if not execute:
            raise PermissionError("Opening a read-write test session requires execute=true")
        if normalized_role not in {"arsim", "dedicated_test_plc"}:
            raise PermissionError(f"Target role {role!r} cannot open a read-write test session")
        ttl = max(1, min(int(ttl_minutes), 8 * 60))
        now = self._clock()
        session = TestSession(
            session_id=f"pvi-test-{secrets.token_urlsafe(18)}",
            target_key=target_key,
            target_name=target_name,
            role=normalized_role,
            mode="read_write",
            created_at=now,
            expires_at=now + timedelta(minutes=ttl),
            fingerprint=dict(fingerprint),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def require(
        self,
        session_id: str | None,
        *,
        target_key: str,
        fingerprint: dict[str, Any] | None = None,
    ) -> TestSession:
        if not session_id:
            raise PermissionError("Changed-value writes require an active test session")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise PermissionError("Unknown test session")
            if self._clock() >= session.expires_at:
                self._sessions.pop(session_id, None)
                raise PermissionError("Test session has expired")
            if session.target_key != target_key:
                raise PermissionError("Test session belongs to a different target")
            if fingerprint is not None and session.fingerprint != fingerprint:
                self._sessions.pop(session_id, None)
                raise PermissionError("PVI_SESSION_FINGERPRINT_MISMATCH: target identity changed")
            return session

    def close(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def close_target(self, target_key: str) -> int:
        with self._lock:
            ids = [key for key, value in self._sessions.items() if value.target_key == target_key]
            for key in ids:
                self._sessions.pop(key, None)
            return len(ids)

    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            expired = [key for key, value in self._sessions.items() if self._clock() >= value.expires_at]
            for key in expired:
                self._sessions.pop(key, None)
            return [value.to_dict() for value in self._sessions.values()]

