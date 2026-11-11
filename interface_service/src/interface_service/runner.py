"""Runs submitted tests in the background, at most max_parallel at a time."""

import asyncio
import logging
from pathlib import Path

from interface_service.backend import Backend
from interface_service.models import RunStatus
from interface_service.store import RunStore

logger = logging.getLogger(__name__)


class Runner:
    def __init__(self, store: RunStore, backend: Backend, image_dir: Path, max_parallel: int):
        self.store = store
        self.backend = backend
        self.image_dir = image_dir
        self.max_parallel = max_parallel
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []

    def active_count(self) -> int:
        return len(self.store.ids_with_status(RunStatus.WAITING, RunStatus.RUNNING))

    def free_slots(self) -> int:
        return max(0, self.max_parallel - self.active_count())

    def enqueue(self, run_id: str) -> None:
        self._queue.put_nowait(run_id)

    async def start(self) -> None:
        # A run that was running when the service stopped cannot be resumed on the platform.
        for run_id in self.store.ids_with_status(RunStatus.RUNNING):
            self.store.mark_failed(run_id, "interrupted by service restart")
        for run_id in self.store.ids_with_status(RunStatus.WAITING):
            self.enqueue(run_id)
        self._workers = [asyncio.create_task(self._work(), name=f"worker-{i}") for i in range(self.max_parallel)]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _work(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._execute(run_id)
            finally:
                self._queue.task_done()

    async def _execute(self, run_id: str) -> None:
        info = self.store.get(run_id)
        if info is None or info.status != RunStatus.WAITING:
            return
        self.store.mark_running(run_id)
        out_dir = self.image_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        logger.info("run %s started", run_id)
        try:
            images = await self.backend.execute(run_id, info.request, out_dir)
        except asyncio.CancelledError:
            self.store.mark_failed(run_id, "cancelled by service shutdown")
            raise
        except Exception as e:
            logger.exception("run %s failed", run_id)
            self.store.mark_failed(run_id, repr(e))
            return
        self.store.mark_finished(
            run_id,
            [{"after_wash": w, "file": p.relative_to(self.image_dir).as_posix()} for w, p in images],
        )
        logger.info("run %s finished", run_id)
