import time

import pytest
from fastapi.testclient import TestClient

from interface_service.app import create_app
from interface_service.config import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, mode="dummy", max_parallel=2, dummy_seconds_per_wash=0.01)
    with TestClient(create_app(settings)) as c:
        yield c


def wait_for(client: TestClient, run_id: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/tests/{run_id}").json()["status"]
        if status in ("finished", "failed"):
            return status
        time.sleep(0.02)
    raise TimeoutError(run_id)


def test_full_run(client):
    response = client.post("/tests", json={"protocol": "p", "n_washes": 3, "coverage_checks": [2]})
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    assert wait_for(client, run_id) == "finished"
    images = client.get(f"/tests/{run_id}/result").json()["images"]
    assert [img["after_wash"] for img in images] == [0, 2, 3]
    png = client.get(images[0]["image_url"])
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")


def test_capacity_limit(client):
    payload = {"protocol": "p", "n_washes": 100, "coverage_checks": []}
    assert client.post("/tests", json=payload).status_code == 201
    assert client.post("/tests", json=payload).status_code == 201
    assert client.get("/capacity").json() == {"max_parallel": 2, "active": 2, "free": 0}
    assert client.post("/tests", json=payload).status_code == 409


@pytest.mark.parametrize("checks", [[-1], [4], [1, 1]])
def test_invalid_coverage_checks(client, checks):
    response = client.post("/tests", json={"protocol": "p", "n_washes": 3, "coverage_checks": checks})
    assert response.status_code == 422


def test_unknown_and_unfinished_run(client):
    assert client.get("/tests/nope").status_code == 404
    run_id = client.post("/tests", json={"protocol": "p", "n_washes": 100, "coverage_checks": []}).json()["run_id"]
    assert client.get(f"/tests/{run_id}/result").status_code == 409
