import asyncio
from pathlib import Path

import pytest

from interface_service.config import Settings
from interface_service.backend import PlatformBackend, protocol_lines
from interface_service.models import TestRequest
from interface_service.name_pool import NamePool


def test_released_name_is_reused_but_names_in_use_are_not():
    pool = NamePool(["p_0", "p_1", "p_2"])
    a, b, c = pool.acquire(), pool.acquire(), pool.acquire()
    assert {a, b, c} == {"p_0", "p_1", "p_2"}
    with pytest.raises(RuntimeError):
        pool.acquire()

    # runs do not have to end in the order they started
    pool.release(b)
    assert pool.acquire() == b
    assert pool.in_use == {a, b, c}


def test_release_of_unused_name_fails():
    pool = NamePool(["p_0"])
    with pytest.raises(ValueError):
        pool.release("p_0")


def test_protocol_lines_strips_comments_and_blank_lines():
    prog = "#/ header\n# comment\n\nrackhome\n  prime 10 3 1 1 5  \n"
    assert protocol_lines(prog) == ["rackhome", "prime 10 3 1 1 5"]


class FakePlatformBackend(PlatformBackend):
    """Records saved protocols instead of talking to the BlueWasher; processes run until released."""

    def __init__(self, names: list[str]):
        super().__init__(Settings(max_parallel=len(names), protocol_name_prefix="p"))
        self.saved: dict[str, list[str]] = {}
        self.running: dict[str, str] = {}  # run_id -> protocol name
        self.finish: dict[str, asyncio.Event] = {}

    def _save_protocol(self, name, lines):
        assert name not in self.running.values(), f"protocol {name} of a running process overwritten"
        self.saved[name] = lines

    async def _run_process(self, run_id, protocol_name, request, out_dir):
        self.running[run_id] = protocol_name
        self.finish[run_id] = asyncio.Event()
        await self.finish[run_id].wait()
        del self.running[run_id]
        return []


def test_platform_backend_never_overwrites_protocol_of_running_process():
    async def scenario():
        backend = FakePlatformBackend(["p_0", "p_1", "p_2"])
        request = TestRequest(protocol="rackhome", n_washes=1, coverage_checks=[1])

        def start(run_id):
            return asyncio.create_task(backend.execute(run_id, request, Path(".")))

        tasks = {r: start(r) for r in "ABC"}
        await asyncio.sleep(0.05)
        assert sorted(backend.running.values()) == ["p_0", "p_1", "p_2"]

        # B ends first, D must get B's name, not the one of A
        backend.finish["B"].set()
        await tasks.pop("B")
        tasks["D"] = start("D")
        await asyncio.sleep(0.05)
        assert backend.running["D"] == "p_1"

        for run_id in tasks:
            backend.finish[run_id].set()
        await asyncio.gather(*tasks.values())
        assert backend.names.in_use == set()

    asyncio.run(scenario())


def test_name_is_released_when_process_fails():
    class FailingBackend(FakePlatformBackend):
        async def _run_process(self, run_id, protocol_name, request, out_dir):
            raise RuntimeError("process failed")

    backend = FailingBackend(["p_0"])
    request = TestRequest(protocol="rackhome", n_washes=1, coverage_checks=[])
    with pytest.raises(RuntimeError):
        asyncio.run(backend.execute("A", request, Path(".")))
    assert backend.names.in_use == set()
