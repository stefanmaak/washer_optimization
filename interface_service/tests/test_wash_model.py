import random

import pytest

from interface_service.sim.settings import WashModelParameters
from interface_service.sim.wash_model import evaluate, speed_profile

PARAMS = WashModelParameters()


def spin(rpm: int, seconds: float, both_directions: bool = False) -> list[str]:
    lines = [f"rotormoveendless {rpm} 1000 600 600 1", f"wait {int(seconds * 1000)}"]
    if both_directions:
        lines += [f"rotormoveendless {-rpm} 1000 600 600 1", f"wait {int(seconds * 1000)}"]
    return lines + ["rotorwaitforpos"]


def mean_results(lines: list[str], n: int = 200) -> tuple[float, float]:
    rng = random.Random(0)
    results = [evaluate(lines, PARAMS, rng) for _ in range(n)]
    return sum(r.emptied for r in results) / n, sum(r.loss for r in results) / n


def test_profile_ramps_and_reverses_through_zero():
    profile = speed_profile(spin(1200, 5, both_directions=True))
    assert profile[1] == pytest.approx((1.2, 1200))  # 1200 rpm at 1000 rpm/s
    assert (pytest.approx(8.2), 0.0) in [(pytest.approx(t), s) for t, s in profile]  # stop at 600 rpm/s
    assert profile[-1][1] == 0.0


@pytest.mark.parametrize(
    ("lines", "emptied", "loss"),
    [
        (spin(800, 5), 0.0, 2.0),  # MagBeadSpin: not emptied
        (spin(1200, 5, both_directions=True), 1.0, 2.0),  # cell painting: emptied, minimal loss
        (spin(2000, 10, both_directions=True), 1.0, 5.0),
        (spin(3500, 10, both_directions=True), 1.0, 12.0),
    ],
)
def test_emptying_and_loss(lines, emptied, loss):
    emptied_rate, mean_loss = mean_results(lines)
    assert emptied_rate == pytest.approx(emptied, abs=0.01)
    assert mean_loss == pytest.approx(loss, abs=0.5)


def test_loss_never_below_minimum_and_no_spin_does_not_empty():
    rng = random.Random(1)
    result = evaluate(["dispense 50 2 1 0 2 0 1 3 5 500 100 1"], PARAMS, rng)
    assert not result.emptied
    assert result.loss == PARAMS.min_loss


def test_relative_move_turns_the_given_rotations():
    # 20000 = 10 rotations at up to 500 rpm
    profile = speed_profile(["rotormoverelfull 20000 500 600 600 600", "rotorwaitforpos"])
    rotations = sum((t2 - t1) * (s1 + s2) / 2 / 60 for (t1, s1), (t2, s2) in zip(profile, profile[1:]))
    assert rotations == pytest.approx(10)
