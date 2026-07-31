from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _CircuitState:
    failures: int = 0
    open_until: float = 0.0


@dataclass
class EvolutionCircuitBreaker:
    """Fail-fast gate for non-critical Evolution calls (profiles, lists).

    Send paths should keep trying; profile/group lookups must not pin workers.
    """

    failure_threshold: int = 5
    open_seconds: float = 30.0
    _states: dict[str, _CircuitState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            if state.open_until > now:
                return False
            if state.open_until and state.open_until <= now:
                state.failures = 0
                state.open_until = 0.0
            return True

    def record_success(self, key: str) -> None:
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            state.failures = 0
            state.open_until = 0.0

    def record_failure(self, key: str) -> None:
        with self._lock:
            state = self._states.setdefault(key, _CircuitState())
            state.failures += 1
            if state.failures >= self.failure_threshold:
                state.open_until = time.monotonic() + self.open_seconds


evolution_circuit = EvolutionCircuitBreaker()
