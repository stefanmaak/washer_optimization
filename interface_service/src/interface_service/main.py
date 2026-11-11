import argparse
import logging
from pathlib import Path

import uvicorn

from interface_service.app import create_app
from interface_service.config import Settings
from interface_service.sim.settings import SimSettings


def main() -> None:
    defaults = Settings()
    parser = argparse.ArgumentParser(description="BlueWasher interface service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--data-dir", type=Path, default=defaults.data_dir)
    parser.add_argument("--max-parallel", type=int, default=defaults.max_parallel)
    parser.add_argument("--sim", action="store_true", help="run on a simulated cage2 with a GUI instead of the real one")
    parser.add_argument("--gui-port", type=int, default=defaults.sim.gui_port, help="port of the simulation GUI")
    parser.add_argument("--seed", type=int, default=None, help="seed of the simulated wash results and mock Chris")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("Scheduler logger", "laborchestrator", "pythonlab", "werkzeug", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = Settings(
        data_dir=args.data_dir,
        max_parallel=args.max_parallel,
        mode="sim" if args.sim else "platform",
        sim=SimSettings(gui_port=args.gui_port, seed=args.seed, service_url=f"http://localhost:{args.port}"),
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
