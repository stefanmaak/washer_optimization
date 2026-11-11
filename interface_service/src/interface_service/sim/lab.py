"""Simulated cage2: a simplified orchestrator executing the generated pythonLab processes with fixed step durations.

Reused from the real system: the pythonLab reader and the scheduling structures of laborchestrator and the
CP-Solver of labscheduler (Python API). Not reused: the orchestrator's worker, timers, database and SiLA parts.

Execution: a step starts at its scheduled start once its predecessors are finished and runs for its fixed duration,
so execution never deviates from the schedule. Adding a process triggers a rescheduling. While the scheduler computes,
running steps finish but no new step starts; the new schedule starts after the computation time at the earliest.

Time is simulation time (SimClock), which can run faster than real time. The scheduler always gets
scheduling_time_limit seconds of real time, which is speed times as much simulation time. It computes in real time
(datetime.now()), so the problem is shifted into its time frame and the schedule back. If it needs longer than its
time limit, the clock is held until the schedule arrives, so no step starts late.
"""

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import networkx as nx
from labscheduler.dev_tools.utilities import parse_jobshop_from_yaml_file
from labscheduler.scheduler_implementation import Scheduler
from labscheduler.structures import MoveOperation, Operation, RequiredMachine
from laborchestrator import workflowgraph as wfg
from laborchestrator.orchestrator_interface import ProcessExecutionState
from laborchestrator.pythonlab_reader import PythonLabReader
from laborchestrator.structures import (
    MoveStep,
    ProcessStep,
    Schedule,
    ScheduledAssignment,
    SchedulingInstance,
    SMProcess,
    StepStatus,
    UsedDevice,
)

from interface_service.sim.clock import SimClock
from interface_service.sim.settings import SimSettings
from interface_service.sim.wash_model import evaluate

logger = logging.getLogger(__name__)

TICK = 0.01  # seconds (real time) between two iterations of the execution loop
WASHER_TYPE = "WasherDispenserServiceResource"


@dataclass
class SimRun:
    """State of the plate of one process and what the squids measured."""

    number: int
    process_name: str
    coverage: float = 100.0
    washes: int = 0
    last_emptied: bool = True
    coverage_points: list[tuple[int, float]] = field(default_factory=list)  # (washes done, coverage in %)
    failed_empty_checks: list[int] = field(default_factory=list)  # washes done at a failed empty check
    finished_at: datetime | None = None
    finished_wall: float | None = None
    """time.monotonic() when the run finished (fading in the GUI happens in real time)."""


@dataclass
class GanttBar:
    run: int
    device: str
    step: str
    start: datetime
    finish: datetime
    planned: bool
    finished_wall: float | None
    """time.monotonic() when the run of this bar finished (for fading it out)."""


class SimLab:
    def __init__(self, settings: SimSettings, empty_check_protocol: str, coverage_check_protocol: str):
        self.settings = settings
        self.empty_check_protocol = empty_check_protocol
        self.coverage_check_protocol = coverage_check_protocol
        self.rng = random.Random(settings.seed)

        self.scheduler = Scheduler(algorithm="CP-Solver", labconfig_path="")
        self.scheduler.configure_job_shop(parse_jobshop_from_yaml_file(settings.lab_config.read_text()))

        self.clock = SimClock()
        self._schedule_deadline: datetime | None = None
        self.jssp = SchedulingInstance()
        self.washer_protocols: dict[str, list[str]] = {}
        self.runs: dict[str, SimRun] = {}  # by process name
        self.scheduling = False
        self.version = 0
        """Increases whenever measurements change (lets the GUI skip redrawing the coverage plot)."""
        self._active: list[SMProcess] = []
        self._reschedule_needed = False
        self._lock = threading.RLock()

    # --- used by the backend and the GUI -----------------------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._loop, name="sim-lab", daemon=True).start()

    def save_protocol(self, name: str, lines: list[str]) -> None:
        """Simulated BlueWasher: stores a protocol, overwriting the previous one with the same name."""
        with self._lock:
            self.washer_protocols[name] = list(lines)

    def add_process(self, source: str) -> str:
        """Parses a pythonLab process, adds it to the lab and triggers a rescheduling. Returns its name."""
        process = PythonLabReader.read_process(src=source)
        _set_move_origins(process)
        for step in process.steps:
            step.duration = self._duration(step)
        with self._lock:
            process.status = ProcessExecutionState.RUNNING
            self.jssp.add_process(process)
            self._active.append(process)
            self.runs[process.name] = SimRun(number=len(self.runs) + 1, process_name=process.name)
            self._reschedule_needed = True
            self.version += 1
        logger.info("added process %s as run %d", process.name, self.runs[process.name].number)
        return process.name

    def is_finished(self, process_name: str) -> bool:
        with self._lock:
            return self.runs[process_name].finished_at is not None

    @property
    def active_runs(self) -> int:
        with self._lock:
            return len(self._active)

    def runs_snapshot(self) -> list[SimRun]:
        with self._lock:
            return [
                SimRun(
                    number=r.number,
                    process_name=r.process_name,
                    coverage=r.coverage,
                    washes=r.washes,
                    coverage_points=list(r.coverage_points),
                    failed_empty_checks=list(r.failed_empty_checks),
                    finished_at=r.finished_at,
                )
                for r in self.runs.values()
            ]

    def gantt_bars(self, keep_finished: float) -> list[GanttBar]:
        """Executed, running and planned steps of all active runs and of runs finished within the last keep_finished
        seconds (real time)."""
        now = self.clock.now()
        bars = []
        with self._lock:
            for run in self.runs.values():
                if run.finished_wall is not None and time.monotonic() - run.finished_wall > keep_finished:
                    continue
                for step in self.jssp.process_by_name[run.process_name].steps:
                    device = step.main_device.name or "?"
                    if step.start is not None:
                        finish = step.finish or now
                        bars.append(GanttBar(run.number, device, step.name, step.start, finish, False,
                                             run.finished_wall))
                    elif step.name in self.jssp.schedule:
                        start = self.jssp.schedule[step.name].start
                        finish = start + timedelta(seconds=step.duration)
                        bars.append(GanttBar(run.number, device, step.name, start, finish, True, None))
        return bars

    # --- execution ---------------------------------------------------------------------------------------------

    def _duration(self, step: ProcessStep) -> float:
        s = self.settings
        if step.function == "move":
            return s.move_duration
        protocol = step.data.get("protocol")
        if protocol == self.empty_check_protocol:
            return s.empty_check_duration
        if protocol == self.coverage_check_protocol:
            return s.coverage_check_duration
        return s.wash_duration

    def _loop(self) -> None:
        while True:
            try:
                self._tick()
            except Exception:
                logger.exception("error in the simulation loop")
            time.sleep(TICK)

    def _tick(self) -> None:
        now = self.clock.now()
        with self._lock:
            if self.scheduling and not self.clock.held and now >= self._schedule_deadline:
                self.clock.hold()  # the scheduler needs longer than its time limit
                now = self.clock.now()
            for process in list(self._active):
                for step in process.steps:
                    if step.status == StepStatus.RUNNING and now >= step.start + timedelta(seconds=step.duration):
                        self._finish(step, now)
            if self._reschedule_needed and not self.scheduling:
                self._reschedule_needed = False
                self.scheduling = True
                threading.Thread(target=self._reschedule, name="sim-scheduling", daemon=True).start()
            if self.scheduling or self._reschedule_needed:
                return
            steps = self.jssp.step_by_id
            for process in self._active:
                for step in process.steps:
                    assign = self.jssp.schedule.get(step.name)
                    if step.status != StepStatus.WAITING or assign is None or assign.start > now:
                        continue
                    required = [idx for idx in step.prior + assign.machine_prior if idx in steps]
                    if all(steps[idx].status == StepStatus.FINISHED for idx in required):
                        step.status = StepStatus.RUNNING
                        step.start = now

    def _finish(self, step: ProcessStep, now: datetime) -> None:
        step.status = StepStatus.FINISHED
        step.finish = now
        run = self.runs[step.process_name]
        protocol = step.data.get("protocol")
        if step.function == "run_protocol" and step.main_device.device_type.__name__ == WASHER_TYPE:
            result = evaluate(self.washer_protocols[protocol], self.settings.wash_model, self.rng)
            run.washes += 1
            run.coverage *= 1 - result.loss / 100
            run.last_emptied = result.emptied
        elif protocol == self.empty_check_protocol:
            if not run.last_emptied:
                run.failed_empty_checks.append(run.washes)
                self.version += 1
        elif protocol == self.coverage_check_protocol:
            run.coverage_points.append((run.washes, run.coverage))
            self.version += 1
        process = self.jssp.process_by_name[step.process_name]
        if all(s.status == StepStatus.FINISHED for s in process.steps):
            run.finished_at = now
            run.finished_wall = time.monotonic()
            self._active.remove(process)
            logger.info("run %d (%s) finished", run.number, run.process_name)

    def _reschedule(self) -> None:
        try:
            computation_time = self.settings.scheduling_time_limit  # real time
            with self._lock:
                sim_now = self.clock.now()
                self._schedule_deadline = sim_now + timedelta(seconds=computation_time * self.clock.speed)
                # the solver plans from datetime.now() + computation_time on, which is the deadline in simulation time
                shift = datetime.now() + timedelta(seconds=computation_time) - self._schedule_deadline
                operations = self._scheduling_problem(shift)
            if not operations:
                return
            start = time.time()
            schedule, quality = self.scheduler.compute_schedule(operations, computation_time)
            logger.info("scheduled %d operations in %.1f s: %s", len(operations), time.time() - start, quality.name)
            if schedule is None:
                logger.error("the scheduler found no schedule")
                return
            with self._lock:
                self.jssp.set_schedule(_orchestrator_schedule(schedule, shift))
        except Exception:
            logger.exception("rescheduling failed")
        finally:
            with self._lock:
                self.scheduling = False
                if self.clock.held:
                    self.clock.release()

    def _scheduling_problem(self, shift: timedelta) -> list[Operation]:
        """Operations for all unfinished steps plus the finished steps they directly depend on (they tell where the
        plates are). Same conversion as orchestrator (create_sila_structure_from_jobs) and labscheduler SiLA server
        (ComputeSchedule) do, without the SiLA structures in between. Times are shifted into the solver's frame."""
        steps = {s.name: s for p in self._active for s in p.steps}
        jobs = {idx: s for idx, s in steps.items() if s.status != StepStatus.FINISHED}
        for job in list(jobs.values()):
            jobs.update({idx: steps[idx] for idx in job.prior if idx in steps})
        if not jobs:
            return []
        graph = wfg.create_sila_structure_from_jobs(jobs.values(), nx.compose_all([p.wfg for p in self._active]))

        operations = {}
        for node in graph.Nodes:
            machines = [
                RequiredMachine(type=r.Type, tag=r.Tag, preferred=None if r.Preferred == "None" else r.Preferred)
                for r in node.RequiredResources
            ]
            op_class = MoveOperation if any(m.tag == "target" for m in machines) else Operation
            job = jobs[node.Idx]
            op = op_class(
                name=node.Idx, duration=node.Duration, required_machines=machines, labware=node.Labware,
                start=job.start + shift if job.start else None, finish=job.finish + shift if job.finish else None,
            )
            if node.WaitToStartCost:
                op.wait_to_start_costs = node.WaitToStartCost
            operations[node.Idx] = op
        for edge in graph.Edges:
            op = operations[edge.Head]
            op.preceding_operations.append(edge.Tail)
            # unset values become numbers on the SiLA way, the solver needs numbers
            op.wait_cost[edge.Tail] = edge.WaitCost or 0.0
            op.max_wait[edge.Tail] = float("inf") if edge.MaxWaitingTime is None else edge.MaxWaitingTime
            op.min_wait[edge.Tail] = edge.MinWaitingTime or 0.0
        return list(operations.values())


def _set_move_origins(process: SMProcess) -> None:
    """Every move starts where the plate's previous move ended, the first one at the plate's start device. This is
    what the orchestrator's WFGManager.set_origins does after adding a process (not imported: its module loads
    sila2). The reader's origins are dropped first, as in the orchestrator."""
    location = {c.name: c.start_device for c in process.containers}
    order = list(nx.topological_sort(process.wfg))
    for step in sorted(process.steps, key=lambda st: order.index(st.name)):
        if isinstance(step, MoveStep):
            step.used_devices = [d for d in step.used_devices if d.tag != "origin"]
            here = location[step.cont]
            step.used_devices.append(UsedDevice(here.device_type, tag="origin", preferred=here.preferred))
            location[step.cont] = step.target_device


def _orchestrator_schedule(schedule, shift: timedelta) -> Schedule:
    result = Schedule()
    for idx, assign in schedule.items():
        if "dummy" not in idx:
            result[idx] = ScheduledAssignment(
                start=assign.start - shift,
                machine_prior=list(assign.machine_precedences),
                participating=dict(assign.machines_to_use),
            )
    return result
