"""Example client for the BlueWasher interface service.

    python client.py --url http://localhost:8100
"""

import argparse
import time

import httpx


class InterfaceClient:
    def __init__(self, base_url: str):
        self._http = httpx.Client(base_url=base_url)

    def capacity(self) -> dict:
        """{"max_parallel": int, "active": int, "free": int}"""
        response = self._http.get("/capacity")
        response.raise_for_status()
        return response.json()

    def test(self, protocol: str, n_washes: int, coverage_checks: list[int]) -> str:
        """Submit a test and return its run_id."""
        payload = {"protocol": protocol, "n_washes": n_washes, "coverage_checks": coverage_checks}
        response = self._http.post("/tests", json=payload)
        response.raise_for_status()
        return response.json()["run_id"]

    def status(self, run_id: str) -> dict:
        """Run info; its "status" is one of "waiting", "running", "finished", "failed"."""
        response = self._http.get(f"/tests/{run_id}")
        response.raise_for_status()
        return response.json()

    def result(self, run_id: str) -> list[dict]:
        """[{"after_wash": int, "image_url": str}] of a finished run."""
        response = self._http.get(f"/tests/{run_id}/result")
        response.raise_for_status()
        return response.json()["images"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8100")
    args = parser.parse_args()

    client = InterfaceClient(args.url)
    print("capacity:", client.capacity())

    run_id = client.test(protocol="example protocol", n_washes=12, coverage_checks=[4, 8])
    print("submitted run", run_id)

    while (info := client.status(run_id))["status"] not in ("finished", "failed"):
        time.sleep(2)
    print("run ended with status", info["status"])

    if info["status"] == "finished":
        for image in client.result(run_id):
            print(f"after wash {image['after_wash']:2d}: {image['image_url']}")


if __name__ == "__main__":
    main()
