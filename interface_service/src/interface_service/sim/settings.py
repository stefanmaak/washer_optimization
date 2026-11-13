from dataclasses import dataclass, field
from pathlib import Path

LAB_CONFIG = Path(__file__).with_name("platform_config.yaml")


@dataclass
class WashModelParameters:
    wells: int = 384
    """Wells of the plate."""
    empty_rpm: float = 1000.0
    """Speed needed to empty a well (GentleSpin)."""
    empty_rpm_noise: float = 50.0
    """Standard deviation of the emptying threshold, rolled for every well independently."""
    safe_rpm: float = 1200.0
    """Speed the cells tolerate without extra loss (LightSpin, used for cell painting)."""
    min_loss: float = 2.0
    """Coverage loss per wash in percent, also the minimum."""
    loss_per_rotation: float = 0.01
    """Additional loss in percent per rotation above safe_rpm."""
    loss_noise: float = 0.2
    """Standard deviation of the loss in percent."""


@dataclass
class SimSettings:
    lab_config: Path = LAB_CONFIG
    """Minimal copy of cage2's platform config (devices used by the washing processes, Fridge with 1000 slots)."""
    move_duration: float = 0.5
    wash_duration: float = 1.0
    empty_check_duration: float = 1.0
    coverage_check_duration: float = 2.0
    scheduling_time_limit: float = 3.0
    """Computation time (real seconds) of the CP-Solver per rescheduling."""
    gui_host: str = "0.0.0.0"
    gui_port: int = 8050
    seed: int | None = None
    """Seed of the wash model noise and of mock Chris."""
    service_url: str = "http://localhost:8100"
    """Where mock Chris reaches the interface service."""
    wash_model: WashModelParameters = field(default_factory=WashModelParameters)
