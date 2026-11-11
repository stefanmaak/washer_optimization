"""Backends that actually execute a test. The simulated one is used until the platform is connected."""

import asyncio
import logging
import struct
import zlib
from abc import ABC, abstractmethod
from pathlib import Path

from interface_service.config import Settings
from interface_service.models import TestRequest
from interface_service.name_pool import NamePool
from interface_service.process_generation import ProcessParameters, generate_process_source

logger = logging.getLogger(__name__)


class Backend(ABC):
    @abstractmethod
    async def execute(self, run_id: str, request: TestRequest, out_dir: Path) -> list[tuple[int, Path]]:
        """Execute one test and save the coverage images into out_dir.

        Returns (after_wash, image_path) for every entry of request.coverage_checks.
        Raising an exception marks the run as failed.
        """


class PlatformBackend(Backend):
    """Executes tests on the real platform (orchestrator + BlueWasher + imager).

    Each test stores its protocol on the BlueWasher under a name from the name pool and adds an orchestrator
    process that runs the protocol by that name. The name stays reserved until the process has ended.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.names = NamePool(settings.protocol_names)
        self._bluewasher = None

    async def execute(self, run_id: str, request: TestRequest, out_dir: Path) -> list[tuple[int, Path]]:
        name = self.names.acquire()
        logger.info("run %s uses protocol name %s", run_id, name)
        try:
            await asyncio.to_thread(self._save_protocol, name, protocol_lines(request.protocol))
            return await self._run_process(run_id, name, request, out_dir)
        finally:
            self.names.release(name)

    def _save_protocol(self, name: str, lines: list[str]) -> None:
        """Store the protocol on the BlueWasher, overwriting the previous protocol with this name."""
        self._bluewasher_client().BlueProtocolExecutionService.SaveProtocol(ProtocolName=name, Content=lines)

    async def _run_process(
        self, run_id: str, protocol_name: str, request: TestRequest, out_dir: Path
    ) -> list[tuple[int, Path]]:
        """Add the generated process to the orchestrator, wait until it has ended, collect the images."""
        source = generate_process_source(run_id, request, self._process_parameters(protocol_name))
        (out_dir / "process.py").write_text(source)
        raise NotImplementedError("orchestrator integration not implemented yet")

    def _process_parameters(self, protocol_name: str) -> ProcessParameters:
        """Each protocol name has its own plate position in Hotel2 and its own squid."""
        s = self.settings
        slot = s.protocol_names.index(protocol_name)
        return ProcessParameters(
            protocol_name=protocol_name,
            start_position=s.start_positions[slot],
            squid=s.squids[slot],
            empty_check_protocol=s.empty_check_protocol,
            coverage_check_protocol=s.coverage_check_protocol,
            squid_project=s.squid_project,
        )

    def _bluewasher_client(self):
        if self._bluewasher is None:
            from sila2.client import SilaClient

            self._bluewasher = SilaClient.discover(server_name=self.settings.bluewasher_server_name, insecure=True, timeout=10)
        return self._bluewasher


def protocol_lines(protocol: str) -> list[str]:
    """Device commands of a protocol in .prog format, without comments and empty lines."""
    stripped = (line.strip() for line in protocol.splitlines())
    return [line for line in stripped if line and not line.startswith("#")]


class SimulatedBackend(Backend):
    def __init__(self, seconds_per_wash: float):
        self.seconds_per_wash = seconds_per_wash

    async def execute(self, run_id: str, request: TestRequest, out_dir: Path) -> list[tuple[int, Path]]:
        images = []
        for wash in range(request.n_washes + 1):
            if wash > 0:
                await asyncio.sleep(self.seconds_per_wash)
                logger.debug("run %s: wash %d/%d done", run_id, wash, request.n_washes)
            if wash in request.coverage_checks:
                path = out_dir / f"wash_{wash:02d}.png"
                path.write_bytes(_gray_png(64, 64, value=max(0, 200 - 10 * wash)))
                images.append((wash, path))
        return images


def _gray_png(width: int, height: int, value: int) -> bytes:
    """Minimal grayscale PNG as placeholder image, avoids an imaging dependency."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + bytes([value]) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
