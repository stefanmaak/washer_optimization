"""Toy model of what a BlueWasher protocol does to a plate with adherent cells.

The rotor commands (BlueWasher User Manual V2.0, device commands) are turned into a rotor speed profile:
- rotormoveendless <rpm> <acc> <dec> ...   ramps to |rpm| with acc [rpm/s], through 0 when the direction changes
- wait <ms>                                keeps the current speed
- stopcentrifugation, rotorwaitforpos, rotorhome, rotorstop and the end of the protocol stop the rotor with dec
- rotormoverelfull <dist> <rpm> <acc> <dec> ...   turns |dist|/2000 rotations (trapezoidal speed profile)
All other commands (dispense, prime, rack movements, ...) do not move the rotor.

From the profile:
- the wells are emptied if the rotor turns at least half a rotation at >= empty_rpm (GentleSpin, 1000 rpm)
- the coverage loss of the wash is min_loss + loss_per_rotation * (rotations counted above safe_rpm), safe_rpm being
  LightSpin (1200 rpm) as used by the cell painting protocols; both with noise.
"""

import math
import random
from dataclasses import dataclass

import numpy as np

from interface_service.sim.settings import WashModelParameters

ROTATION_DISTANCE = 2000  # rotormoverel distance of one revolution
DEFAULT_ACCELERATION = 1000.0  # rpm/s
DEFAULT_DECELERATION = 600.0  # rpm/s
STOP_COMMANDS = {"stopcentrifugation", "rotorwaitforpos", "rotorhome", "rotorstop"}


@dataclass
class WashResult:
    emptied: bool
    loss: float
    """Relative coverage loss of the wash in percent."""


def evaluate(lines: list[str], params: WashModelParameters, rng: random.Random) -> WashResult:
    times, speeds = zip(*speed_profile(lines))
    if times[-1] <= 0:
        return WashResult(emptied=False, loss=params.min_loss)
    t = np.linspace(0.0, times[-1], max(2, int(times[-1] * 1000)))  # 1 ms resolution
    rpm = np.interp(t, times, speeds)
    rotations = rpm * (t[1] - t[0]) / 60  # rotations per time step

    threshold = rng.gauss(params.empty_rpm, params.empty_rpm_noise)
    emptied = rotations[rpm >= threshold].sum() >= 0.5
    rotations_above_safe = (np.maximum(rpm - params.safe_rpm, 0.0) * (t[1] - t[0]) / 60).sum()
    loss = params.min_loss + params.loss_per_rotation * rotations_above_safe + rng.gauss(0.0, params.loss_noise)
    return WashResult(emptied=bool(emptied), loss=max(params.min_loss, float(loss)))


def speed_profile(lines: list[str]) -> list[tuple[float, float]]:
    """Rotor speed (absolute rpm) over time (s) as breakpoints of a piecewise linear function."""
    profile = _Profile()
    for line in lines:
        cmd, *args = line.split() or [""]
        values = [float(a) for a in args if _is_number(a)]
        cmd = cmd.lower()
        if cmd == "rotormoveendless" and values:
            profile.spin(values[0], *values[1:3])
        elif cmd == "wait" and values:
            profile.hold(values[0] / 1000)
        elif cmd in STOP_COMMANDS:
            profile.ramp_to(0.0, profile.dec)
        elif cmd == "rotormoverelfull" and len(values) >= 2:
            profile.relative_move(abs(values[0]) / ROTATION_DISTANCE, *values[1:4])
    profile.ramp_to(0.0, profile.dec)
    return profile.points


class _Profile:
    def __init__(self):
        self.t = 0.0
        self.speed = 0.0
        self.direction = 1
        self.dec = DEFAULT_DECELERATION
        self.points = [(0.0, 0.0)]

    def _add(self, dt: float, speed: float) -> None:
        self.t += dt
        self.speed = speed
        self.points.append((self.t, speed))

    def ramp_to(self, target: float, rate: float) -> None:
        if target != self.speed:
            self._add(abs(target - self.speed) / max(rate, 1.0), target)

    def hold(self, duration: float) -> None:
        self._add(duration, self.speed)

    def spin(self, rpm: float, acc: float = DEFAULT_ACCELERATION, dec: float | None = None) -> None:
        if dec is not None:
            self.dec = dec
        direction = 1 if rpm >= 0 else -1
        if direction != self.direction:
            self.ramp_to(0.0, self.dec)
            self.direction = direction
        self.ramp_to(abs(rpm), acc if abs(rpm) > self.speed else self.dec)

    def relative_move(self, rotations: float, rpm: float, acc: float = 0, dec: float = 0) -> None:
        """From standstill to standstill; triangular if the distance is too short to reach rpm."""
        self.ramp_to(0.0, self.dec)
        acc = acc or DEFAULT_ACCELERATION
        dec = dec or DEFAULT_DECELERATION
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
