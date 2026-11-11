import asyncio
from pathlib import Path

from interface_service.backend import PlatformBackend
from interface_service.config import Settings
from interface_service.sim.lab import SimLab


class SimBackend(PlatformBackend):
    """The platform backend (name pool, process generation) running on the simulated cage2.

    Results contain no images: the measurements are only shown in the simulation GUI.
    """

    def __init__(self, settings: Settings, lab: SimLab):
        super().__init__(settings)
        self.lab = lab

    def _save_protocol(self, name: str, lines: list[str]) -> None:
        self.lab.save_protocol(name, lines)

    async def _execute_process(self, source: str, out_dir: Path) -> list[tuple[int, Path]]:
        name = await asyncio.to_thread(self.lab.add_process, source)
        while not self.lab.is_finished(name):
            await asyncio.sleep(0.2)
        return []
