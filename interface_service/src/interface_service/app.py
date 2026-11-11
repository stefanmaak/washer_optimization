from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.staticfiles import StaticFiles

from interface_service.backend import PlatformBackend, SimulatedBackend
from interface_service.config import Settings
from interface_service.models import (
    Capacity,
    CoverageImage,
    RunInfo,
    RunResult,
    RunStatus,
    SubmitResponse,
    TestRequest,
)
from interface_service.runner import Runner
from interface_service.store import RunStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.image_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = RunStore(settings.db_path)
        if settings.simulate:
            backend = SimulatedBackend(settings.sim_seconds_per_wash)
        else:
            backend = PlatformBackend(settings)
        runner = Runner(store, backend, settings.image_dir, settings.max_parallel)
        app.state.store = store
        app.state.runner = runner
        await runner.start()
        yield
        await runner.stop()
        store.close()

    app = FastAPI(title="BlueWasher interface service", version="0.1.0", lifespan=lifespan)
    app.mount("/images", StaticFiles(directory=settings.image_dir), name="images")

    def get_run(request: Request, run_id: str) -> RunInfo:
        info = request.app.state.store.get(run_id)
        if info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown run_id {run_id}")
        return info

    @app.post("/tests", status_code=status.HTTP_201_CREATED)
    def submit_test(test: TestRequest, request: Request) -> SubmitResponse:
        """Submit a test. Rejected with 409 if the platform has no free capacity."""
        runner: Runner = request.app.state.runner
        if runner.free_slots() == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "no free capacity, check GET /capacity")
        run_id = request.app.state.store.add(test)
        runner.enqueue(run_id)
        return SubmitResponse(run_id=run_id)

    @app.get("/capacity")
    def capacity(request: Request) -> Capacity:
        runner: Runner = request.app.state.runner
        active = runner.active_count()
        return Capacity(max_parallel=runner.max_parallel, active=active, free=max(0, runner.max_parallel - active))

    @app.get("/tests/{run_id}")
    def run_status(run_id: str, request: Request) -> RunInfo:
        return get_run(request, run_id)

    @app.get("/tests/{run_id}/result")
    def run_result(run_id: str, request: Request) -> RunResult:
        info = get_run(request, run_id)
        if info.status != RunStatus.FINISHED:
            raise HTTPException(status.HTTP_409_CONFLICT, f"run {run_id} is {info.status}, not finished")
        images = [
            CoverageImage(after_wash=img["after_wash"], image_url=str(request.url_for("images", path=img["file"])))
            for img in request.app.state.store.images(run_id)
        ]
        return RunResult(run_id=run_id, images=images)

    return app
