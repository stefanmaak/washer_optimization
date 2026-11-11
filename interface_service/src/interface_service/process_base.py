"""Base class of the generated washing processes.

Only pythonLab resources, named like the devices in cage2's platform config. It does not depend on cage2's
lab_adaption (whose BasicProcess imports the Echo SiLA client). It has to live in its own module: the pythonLab reader
takes the first PLProcess subclass defined in a process source, which must be the generated process itself.
"""

from pythonlab.process import PLProcess
from pythonlab.resource import LabwareResource
from pythonlab.resources.services.labware_storage import LabwareStorageResource
from pythonlab.resources.services.microscope import MicroscopeServiceResource
from pythonlab.resources.services.moving import MoverServiceResource
from pythonlab.resources.services.washer_dispenser import WasherDispenserServiceResource


class WashingProcess(PLProcess):
    """Devices of cage2 used by the washing optimization and the one lidded plate of a test."""

    def __init__(self, process_name: str, priority: int = 7):
        self.name = process_name
        super().__init__(priority=priority)

    def create_resources(self):
        self.hotel2 = LabwareStorageResource(proc=self, name="Hotel2")
        self.fridge = LabwareStorageResource(proc=self, name="Fridge")
        self.robot_arm = MoverServiceResource(proc=self, name="PFonRail")
        self.bluewasher = WasherDispenserServiceResource(proc=self, name="BlueWasher")
        # Squid3 is not used
        self.squid1 = MicroscopeServiceResource(proc=self, name="Squid1")
        self.squid2 = MicroscopeServiceResource(proc=self, name="Squid2")
        self.squid4 = MicroscopeServiceResource(proc=self, name="Squid4")
        self.plate = LabwareResource(proc=self, name=f"{self.name}_plate", lidded=True, filled=False)

    def init_service_resources(self):
        super().init_service_resources()

    def process(self):
        raise NotImplementedError
