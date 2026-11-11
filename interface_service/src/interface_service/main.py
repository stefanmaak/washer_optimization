import argparse
import logging
from pathlib import Path

import uvicorn

from interface_service.app import create_app
from interface_service.config import Settings


def main() -> None:
    defaults = Settings()
    parser = argparse.ArgumentParser(description="BlueWasher interface service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--data-dir", type=Path, default=defaults.data_dir)
    parser.add_argument("--max-parallel", type=int, default=defaults.max_parallel)
    parser.add_argument("--platform", action="store_true", help="use the real platform instead of the simulation")
    parser.add_argument("--sim-seconds-per-wash", type=float, default=defaults.sim_seconds_per_wash)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings(
        data_dir=args.data_dir,
        max_parallel=args.max_parallel,
        simulate=not args.platform,
        sim_seconds_per_wash=args.sim_seconds_per_wash,
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
