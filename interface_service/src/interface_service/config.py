from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from interface_service.sim.settings import SimSettings

DEFAULT_SQUIDS = ["Squid1", "Squid2", "Squid4"]  # Squid3 is not used


@dataclass
class Settings:
    data_dir: Path = Path("./service_data")
    """Holds the SQLite database and the images of all runs."""
    max_parallel: int = 3
    """Number of tests (orchestrator processes) the platform can run at the same time."""
    protocol_name_prefix: str = "washopt"
    """Protocols are stored on the BlueWasher as <prefix>_0 .. <prefix>_<max_parallel - 1>."""
    bluewasher_server_name: str = "BlueWasher"
    """SiLA server name used to discover the BlueWasher server."""
    start_positions: list[int] | None = None
    """Hotel2 position of the plate for each protocol name (same order). Default: 0 .. max_parallel - 1."""
    squids: list[str] | None = None
    """Squid used by each protocol name (same order). Default: the first max_parallel of Squid1, Squid2, Squid4."""
    empty_check_protocol: str = "empty_check"
    """Squid protocol checking whether the wells are empty."""
    coverage_check_protocol: str = "coverage_check"
    """Squid protocol imaging the cell coverage."""
    squid_project: str = "washing_optimization"
    """Squid project the images are stored under."""
    mode: Literal["platform", "sim", "dummy"] = "platform"
    """platform: real cage2, sim: simulated cage2 with GUI, dummy: minimal backend for unit tests."""
    sim: SimSettings = field(default_factory=SimSettings)
    """Settings of the simulated cage2 (mode sim)."""
    dummy_seconds_per_wash: float = 2.0
    """Duration of one wash in the dummy backend."""

    @property
    def protocol_names(self) -> list[str]:
        return [f"{self.protocol_name_prefix}_{i}" for i in range(self.max_parallel)]

    def __post_init__(self):
        if self.start_positions is None:
            self.start_positions = list(range(self.max_parallel))
        if len(self.start_positions) != self.max_parallel:
            raise ValueError(f"need one start position per parallel process, got {self.start_positions}")
        if self.squids is None:
            self.squids = DEFAULT_SQUIDS[: self.max_parallel]
        if len(self.squids) != self.max_parallel:
            raise ValueError(f"need one squid per parallel process, got {self.squids}")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "runs.sqlite"

    @property
    def image_dir(self) -> Path:
        return self.data_dir / "images"
