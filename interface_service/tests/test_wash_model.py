import random

import pytest

from interface_service.sim.settings import WashModelParameters
from interface_service.sim.wash_model import evaluate, expand_loops, speed_profile

PARAMS = WashModelParameters()


def spin(rpm: int, seconds: float, both_directions: bool = False) -> list[str]:
    lines = [f"rotormoveendless {rpm} 1000 600 600 1", f"wait {int(seconds * 1000)}"]
    if both_directions:
        lines += [f"rotormoveendless {-rpm} 1000 600 600 1", f"wait {int(seconds * 1000)}"]
    return lines + ["rotorwaitforpos"]


def mean_results(lines: list[str], n: int = 200) -> tuple[float, float]:
    rng = random.Random(0)
    results = [evaluate(lines, PARAMS, rng) for _ in range(n)]
    return sum(r.empty_wells for r in results) / n / PARAMS.wells, sum(r.loss for r in results) / n


def test_profile_ramps_and_reverses_through_zero():
    profile = speed_profile(spin(1200, 5, both_directions=True))
    assert profile[1] == pytest.approx((1.2, 1200))  # 1200 rpm at 1000 rpm/s
    assert (pytest.approx(8.2), 0.0) in [(pytest.approx(t), s) for t, s in profile]  # stop at 600 rpm/s
    assert profile[-1][1] == 0.0


@pytest.mark.parametrize(
    ("lines", "empty_fraction", "loss"),
    [
        (spin(800, 5), 0.0, 2.0),  # MagBeadSpin: not emptied
        (spin(1200, 5, both_directions=True), 1.0, 2.0),  # cell painting: emptied, minimal loss
        (spin(2000, 10, both_directions=True), 1.0, 5.0),
        (spin(3500, 10, both_directions=True), 1.0, 12.0),
    ],
)
def test_emptying_and_loss(lines, empty_fraction, loss):
    mean_empty_fraction, mean_loss = mean_results(lines)
    assert mean_empty_fraction == pytest.approx(empty_fraction, abs=0.01)
    assert mean_loss == pytest.approx(loss, abs=0.5)


def test_loss_never_below_minimum_and_no_spin_does_not_empty():
    rng = random.Random(1)
    result = evaluate(["dispense 50 2 1 0 2 0 1 3 5 500 100 1"], PARAMS, rng)
    assert result.empty_wells == 0
    assert result.loss == PARAMS.min_loss


def test_relative_move_turns_the_given_rotations():
    # 20000 = 10 rotations at up to 500 rpm
    profile = speed_profile(["rotormoverelfull 20000 500 600 600 600", "rotorwaitforpos"])
    rotations = sum((t2 - t1) * (s1 + s2) / 2 / 60 for (t1, s1), (t2, s2) in zip(profile, profile[1:]))
    assert rotations == pytest.approx(10)


def rotations(profile: list[tuple[float, float]]) -> float:
    return sum((t2 - t1) * (s1 + s2) / 2 / 60 for (t1, s1), (t2, s2) in zip(profile, profile[1:]))


def test_wells_are_emptied_independently_near_the_threshold():
    # 1000 rpm = empty_rpm: about half of the wells have a threshold below it
    result = evaluate(spin(1000, 5), PARAMS, random.Random(2))
    assert 0.3 * PARAMS.wells < result.empty_wells < 0.7 * PARAMS.wells


def test_nested_loops_are_expanded():
    lines = ["a", "loop 2", "b", "loop 3", "c", "endloop", "endloop", "d"]
    assert expand_loops(lines) == ["a"] + ["b", "c", "c", "c"] * 2 + ["d"]


def test_loop_multiplies_the_rotations():
    move = ["rotormoverelfull 2000 500 1000 1000 2000"]
    assert rotations(speed_profile(["loop 4", *move, "endloop"])) == pytest.approx(4 * rotations(speed_profile(move)))


def test_relative_moves_use_the_last_parameters_or_1000_rpm():
    # velocity 0 keeps the default of 1000 rpm; with these ramps 10 rotations reach it
    profile = speed_profile(["rotormoverelfull 0 0 3000 3000 2000", "rotormoverel 20000"])
    assert max(s for _, s in profile) == pytest.approx(1000)
    spin = ["rotormoveendless 300 1000 600 600 1", "wait 1000", "stopcentrifugation"]
    profile = speed_profile([*spin, "rotormoverel 20000"])
    assert profile[-2][1] == pytest.approx(300)
    assert rotations(profile) - rotations(speed_profile(spin)) == pytest.approx(10)


def test_rotormoveabs_moves_to_the_absolute_position():
    profile = speed_profile(["rotormoverelfull 1000 100 1000 1000 1000", "rotormoveabs -3000"])
    assert rotations(profile) == pytest.approx(0.5 + 2.0)


def test_shake_uses_the_parameters_set_before():
    # as in CellPainting_Wash_withDispense.prog: set parameters with a 1 unit move, then shake
    profile = speed_profile(["rotormoverelfull -1 3500 5000 5000 600", "rotorshake 1333"])
    assert rotations(profile) == pytest.approx((1 + 10 * 1333) / 2000)
    assert max(s for _, s in profile) < 500  # too short to get anywhere near 3500 rpm


def test_rotorstop_uses_the_quick_deceleration():
    profile = speed_profile(["rotormoveendless 2000 1000 500 2000 1", "wait 1000", "rotorstop"])
    assert profile[-1][0] - profile[-2][0] == pytest.approx(1.0)  # 2000 rpm at 2000 rpm/s


def test_rotorsetvelocity_changes_the_speed_of_a_running_rotor():
    profile = speed_profile(["rotormoveendless 1000 1000 500 2000 1", "wait 1000", "rotorsetvelocity 2000 1", "wait 1000"])
    assert max(s for _, s in profile) == pytest.approx(2000)


def test_rotorhome_does_not_use_the_current_parameters():
    profile = speed_profile(["rotormoverelfull 500 3000 1000 1000 1000", "rotorhome"])
    home = profile[-4:]
    assert max(s for _, s in home) <= 100
    assert rotations(home) == pytest.approx(0.25)
