"""Mock of Chris' agents: sends random washing protocols to the interface service whenever a slot is free.

It talks to the service over HTTP like the real agents and never reads the results.
"""

import logging
import random
import threading
import time

import httpx
from bluewasher_sila.hardware_comm.command_structure import program_to_str_list
from bluewasher_sila.hardware_comm.commands import Centrifugation, Dispense, Prime

logger = logging.getLogger(__name__)


def random_protocol(rng: random.Random) -> str:
    """One washing round: optionally prime, then 1-2 x (dispense, spin)."""
    channel = rng.randint(0, 6)
    steps = []
    if rng.random() < 0.3:
        steps.append(Prime(channel=channel, volume=rng.choice([10, 20, 50])))
    for _ in range(rng.randint(1, 2)):
        steps.append(Dispense(channel=channel, volume=rng.randint(20, 100), pressure=rng.randint(1, 5)))
        steps.append(Centrifugation(
            duration_in_ms=rng.randint(1, 20) * 1000,
            rpm=rng.choice([-1, 1]) * rng.randrange(400, 3501, 50),
            acceleration=rng.randrange(200, 1501, 100),
            deceleration=rng.randrange(200, 1001, 100),
        ))
    return "\n".join(program_to_str_list(steps))


def random_test(rng: random.Random) -> dict:
    n_washes = rng.randint(5, 12)
    coverage_checks = sorted(w for w in range(1, n_washes) if rng.random() < 0.3)
    return dict(protocol=random_protocol(rng), n_washes=n_washes, coverage_checks=coverage_checks)


class MockChris:
    def __init__(self, service_url: str, poll_interval: float = 0.25, seed: int | None = None):
        self.service_url = service_url
        self.poll_interval = poll_interval
        self.rng = random.Random(seed)
        self.submitted = 0
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def set_running(self, running: bool) -> None:
        if running:
            self._running.set()
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="mock-chris", daemon=True)
                self._thread.start()
        else:
            self._running.clear()

    def run_forever(self) -> None:
        self._running.set()
        self._loop()

    def _loop(self) -> None:
        with httpx.Client(base_url=self.service_url, timeout=10) as http:
            while True:
                self._running.wait()
                try:
                    self._submit_while_free(http)
                except httpx.HTTPError as e:
                    logger.warning("interface service not reachable: %s", e)
                time.sleep(self.poll_interval)

    def _submit_while_free(self, http: httpx.Client) -> None:
        response = http.get("/capacity")
        response.raise_for_status()
        for _ in range(response.json()["free"]):
            if not self.running:
                return
            test = random_test(self.rng)
            response = http.post("/tests", json=test)
            response.raise_for_status()
            self.submitted += 1
            logger.info(
                "mock Chris submitted %s: %d washes, coverage checks %s",
                response.json()["run_id"], test["n_washes"], test["coverage_checks"],
            )
