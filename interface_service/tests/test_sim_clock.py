import time

import pytest

from interface_service.sim.clock import SimClock


def elapsed(clock: SimClock, real_seconds: float) -> float:
    start = clock.now()
    time.sleep(real_seconds)
    return (clock.now() - start).total_seconds()


def test_speed_and_hold():
    clock = SimClock(speed=10)
    assert elapsed(clock, 0.1) == pytest.approx(1.0, abs=0.3)
    clock.speed = 1
    assert elapsed(clock, 0.1) == pytest.approx(0.1, abs=0.05)
    clock.hold()
    assert elapsed(clock, 0.05) == 0
    clock.release()
    assert elapsed(clock, 0.05) == pytest.approx(0.05, abs=0.03)
