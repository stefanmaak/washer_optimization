"""Mock of Chris' agents as standalone program: sends random washing protocols whenever a slot is free.

The service started with --sim has the same mock built in (Start button in its GUI).

    python mock_chris.py --url http://localhost:8100
"""

import argparse
import logging

from interface_service.sim.mock_chris import MockChris


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8100")
    parser.add_argument("--poll", type=float, default=0.25, help="seconds between two capacity checks")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    MockChris(args.url, args.poll, args.seed).run_forever()


if __name__ == "__main__":
    main()
