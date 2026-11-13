"""Toy model of what a BlueWasher protocol does to a plate with adherent cells.

The rotor commands (BlueWasher User Manual V2.0, 6.2 and 6.6) are turned into a rotor speed profile. Positions and
distances are in rotor units, 2000 being one revolution.
- loop <n> ... endloop                         repeats the block n times (nestable)
- rotormoveendless <rpm> <acc> <dec> <qdec>    ramps to |rpm| with acc [rpm/s], through 0 when the direction changes
- rotorsetvelocity <rpm>                       changes the speed of a running rotor (acc when faster, dec when slower)
- wait <ms>                                    keeps the current speed
- stopcentrifugation, rotorwaitforpos          stop the rotor with dec (in its home position)
- rotorstop, stopall                           stop the rotor with qdec
- rotormoverelfull <dist> <rpm> <acc> <dec> <qdec>   turns |dist| units (trapezoidal speed profile)
- rotormoverel <dist>                          as rotormoverelfull with the current parameters
- rotormoveabs <pos>                           as rotormoverel to the absolute position pos (home = 0)
- rotorshake <dist>                            5 shakes, each |dist| out and back, with the current parameters
- rotorhome                                    back to the home position at 100 rpm, 1000 rpm/s (own parameters)
rotormoveendless and rotormoverelfull set the current parameters (speed, acc, dec, qdec) used by the moves after
them; until then 1000 rpm, 1000 rpm/s, 600 rpm/s and 2000 rpm/s. The end of the protocol stops the rotor with dec.
All other commands (dispense, prime, rack movements, ...) do not move the rotor.

From the profile:
- every well of the plate has its own emptying threshold around empty_rpm (GentleSpin, 1000 rpm). It is emptied if the
  rotor turns at least half a rotation at or above that threshold.
- the coverage loss of the wash is min_loss + loss_per_rotation * (rotations counted above safe_rpm), safe_rpm being
  LightSpin (1200 rpm) as used by the cell painting protocols; with noise.
"""

import math
import random
from dataclasses import dataclass

import numpy as np

from interface_service.sim.settings import WashModelParameters

ROTATION_DISTANCE = 2000  # rotormoverel distance of one revolution
DEFAULT_VELOCITY = 1000.0  # rpm
DEFAULT_ACCELERATION = 1000.0  # rpm/s
DEFAULT_DECELERATION = 600.0  # rpm/s
DEFAULT_QUICK_DECELERATION = 2000.0  # rpm/s
HOME_VELOCITY = 100.0  # rpm, rotorhome does not use the current parameters
HOME_ACCELERATION = 1000.0  # rpm/s
SHAKES = 5
MAX_LOOP_DEPTH = 9


@dataclass
class WashResult:
    empty_wells: int
    """Number of wells of the plate that were emptied."""
    loss: float
    """Relative coverage loss of the wash in percent."""


def evaluate(lines: list[str], params: WashModelParameters, rng: random.Random) -> WashResult:
    times, speeds = zip(*speed_profile(lines))
    loss_noise = rng.gauss(0.0, params.loss_noise)
    thresholds = np.array([rng.gauss(params.empty_rpm, params.empty_rpm_noise) for _ in range(params.wells)])
    if times[-1] <= 0:
        return WashResult(empty_wells=0, loss=params.min_loss)
    t = np.linspace(0.0, times[-1], max(2, int(times[-1] * 1000)))  # 1 ms resolution
    rpm = np.interp(t, times, speeds)
    rotations = rpm * (t[1] - t[0]) / 60  # rotations per time step

    # rotations at or above each threshold: cumulated over the speeds sorted from fast to slow
    order = np.argsort(-rpm)
    rotations_from_fastest = np.cumsum(rotations[order])
    n_at_or_above = np.searchsorted(-rpm[order], -thresholds, side="right")
    rotations_above_threshold = np.where(n_at_or_above > 0, rotations_from_fastest[n_at_or_above - 1], 0.0)
    empty_wells = int((rotations_above_threshold >= 0.5).sum())

    rotations_above_safe = (np.maximum(rpm - params.safe_rpm, 0.0) * (t[1] - t[0]) / 60).sum()
    loss = params.min_loss + params.loss_per_rotation * rotations_above_safe + loss_noise
    return WashResult(empty_wells=empty_wells, loss=max(params.min_loss, float(loss)))


def expand_loops(lines: list[str]) -> list[str]:
    """Replaces every loop <n> ... endloop block by n copies of its lines. An unclosed loop runs to the end."""
    stack: list[tuple[int, list[str]]] = [(1, [])]
    for line in lines:
        cmd, *args = line.split() or [""]
        cmd = cmd.lower()
        if cmd == "loop":
            count = int(float(args[0])) if args and _is_number(args[0]) else 1
            if len(stack) > MAX_LOOP_DEPTH:
                raise ValueError(f"more than {MAX_LOOP_DEPTH} nested loops")
            stack.append((max(count, 0), []))
        elif cmd == "endloop" and len(stack) > 1:
            count, body = stack.pop()
            stack[-1][1].extend(body * count)
        else:
            stack[-1][1].append(line)
    while len(stack) > 1:
        count, body = stack.pop()
        stack[-1][1].extend(body * count)
    return stack[0][1]


def speed_profile(lines: list[str]) -> list[tuple[float, float]]:
    """Rotor speed (absolute rpm) over time (s) as breakpoints of a piecewise linear function."""
    profile = _Profile()
    for line in expand_loops(lines):
        cmd, *args = line.split() or [""]
        values = [float(a) for a in args if _is_number(a)]
        cmd = cmd.lower()
        if cmd == "rotormoveendless" and values:
            profile.set_parameters(abs(values[0]), *values[1:4])
            profile.spin(values[0])
        elif cmd == "rotorsetvelocity" and values:
            profile.set_velocity(values[0])
        elif cmd == "wait" and values:
            profile.hold(values[0] / 1000)
        elif cmd in ("stopcentrifugation", "rotorwaitforpos"):
            profile.stop(profile.dec)
        elif cmd in ("rotorstop", "stopall"):
            profile.stop(profile.qdec)
        elif cmd == "rotormoverelfull" and values:
            profile.set_parameters(*values[1:5])
            profile.relative_move(values[0])
        elif cmd == "rotormoverel" and values:
            profile.relative_move(values[0])
        elif cmd == "rotormoveabs" and values:
            profile.relative_move(values[0] - profile.position)
        elif cmd == "rotorshake" and values:
            for _ in range(SHAKES):
                profile.relative_move(abs(values[0]))
                profile.relative_move(-abs(values[0]))
        elif cmd == "rotorhome":
            profile.home()
    profile.stop(profile.dec)
    return profile.points


class _Profile:
    def __init__(self):
        self.t = 0.0
        self.speed = 0.0
        self.direction = 1
        self.position = 0.0  # rotor units relative to the home position, only tracked while not spinning endless
        self.velocity = DEFAULT_VELOCITY
        self.acc = DEFAULT_ACCELERATION
        self.dec = DEFAULT_DECELERATION
        self.qdec = DEFAULT_QUICK_DECELERATION
        self.points = [(0.0, 0.0)]

    def set_parameters(self, velocity: float = 0, acc: float = 0, dec: float = 0, qdec: float = 0) -> None:
        """Values of 0 keep the current parameter."""
        self.velocity = abs(velocity) or self.velocity
        self.acc = acc or self.acc
        self.dec = dec or self.dec
        self.qdec = qdec or self.qdec

    def _add(self, dt: float, speed: float) -> None:
        self.t += dt
        self.speed = speed
        self.points.append((self.t, speed))

    def ramp_to(self, target: float, rate: float) -> None:
        if target != self.speed:
            self._add(abs(target - self.speed) / max(rate, 1.0), target)

    def hold(self, duration: float) -> None:
        self._add(duration, self.speed)

    def stop(self, rate: float) -> None:
        """Endless rotations stop in the home position."""
        if self.speed > 0:
            self.ramp_to(0.0, rate)
            self.position = 0.0

    def spin(self, rpm: float) -> None:
        direction = 1 if rpm >= 0 else -1
        if direction != self.direction:
            self.ramp_to(0.0, self.dec)
            self.direction = direction
        self.ramp_to(abs(rpm), self.acc if abs(rpm) > self.speed else self.dec)

    def set_velocity(self, rpm: float) -> None:
        self.velocity = abs(rpm)
        if self.speed > 0:
            self.spin(rpm)

    def relative_move(self, distance: float) -> None:
        """From standstill to standstill with the current parameters; triangular if too short to reach the speed."""
        self._move(abs(distance) / ROTATION_DISTANCE, self.velocity, self.acc, self.dec)
        self.position += distance

    def home(self) -> None:
        offset = self.position % ROTATION_DISTANCE
        self._move(min(offset, ROTATION_DISTANCE - offset) / ROTATION_DISTANCE, HOME_VELOCITY, HOME_ACCELERATION,
                   HOME_ACCELERATION)
        self.position = 0.0

    def _move(self, rotations: float, rpm: float, acc: float, dec: float) -> None:
        self.stop(self.dec)
        if rotations <= 0 or rpm <= 0:
            return
        ramp_rotations = rpm**2 * (1 / acc + 1 / dec) / 120  # rotations while ramping up and down
        if ramp_rotations > rotations:
            rpm = math.sqrt(120 * rotations / (1 / acc + 1 / dec))
            ramp_rotations = rotations
        self._add(rpm / acc, rpm)
        self.hold((rotations - ramp_rotations) * 60 / rpm)
        self._add(rpm / dec, 0.0)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
