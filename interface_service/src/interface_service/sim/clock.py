import threading
import time
from datetime import datetime, timedelta


class SimClock:
    """Simulation time: starts at the real time and runs `speed` times faster; can be held."""

    def __init__(self, speed: float = 1.0):
        self._lock = threading.Lock()
        self._sim_base = datetime.now()
        self._wall_base = time.monotonic()
        self._speed = speed
        self._held = False

    def now(self) -> datetime:
        with self._lock:
            return self._now()

    def _now(self) -> datetime:
        if self._held:
            return self._sim_base
        return self._sim_base + timedelta(seconds=(time.monotonic() - self._wall_base) * self._speed)

    def _rebase(self) -> None:
        self._sim_base = self._now()
        self._wall_base = time.monotonic()

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, speed: float) -> None:
        with self._lock:
            self._rebase()
            self._speed = speed

    @property
    def held(self) -> bool:
        return self._held

    def hold(self) -> None:
        with self._lock:
            self._rebase()
            self._held = True

    def release(self) -> None:
        with self._lock:
            self._rebase()
            self._held = False
