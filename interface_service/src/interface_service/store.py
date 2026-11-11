"""SQLite persistence of runs, so the service can be stopped and resumed."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from interface_service.models import RunInfo, RunStatus, TestRequest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    request      TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    error        TEXT,
    images       TEXT
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(db_path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._con:
            self._con.execute(_SCHEMA)

    def close(self) -> None:
        self._con.close()

    def add(self, request: TestRequest) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._lock, self._con:
            self._con.execute(
                "INSERT INTO runs (run_id, status, request, submitted_at) VALUES (?, ?, ?, ?)",
                (run_id, RunStatus.WAITING, request.model_dump_json(), _now()),
            )
        return run_id

    def get(self, run_id: str) -> RunInfo | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else self._to_info(row)

    def images(self, run_id: str) -> list[dict]:
        """Images of a finished run as [{"after_wash": int, "file": path relative to image dir}]."""
        with self._lock:
            row = self._con.execute("SELECT images FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["images"]) if row and row["images"] else []

    def ids_with_status(self, *statuses: RunStatus) -> list[str]:
        marks = ",".join("?" * len(statuses))
        with self._lock:
            rows = self._con.execute(
                f"SELECT run_id FROM runs WHERE status IN ({marks}) ORDER BY submitted_at", statuses
            ).fetchall()
        return [r["run_id"] for r in rows]

    def mark_running(self, run_id: str) -> None:
        self._update(run_id, status=RunStatus.RUNNING, started_at=_now())

    def mark_finished(self, run_id: str, images: list[dict]) -> None:
        self._update(run_id, status=RunStatus.FINISHED, finished_at=_now(), images=json.dumps(images))

    def mark_failed(self, run_id: str, error: str) -> None:
        self._update(run_id, status=RunStatus.FAILED, finished_at=_now(), error=error)

    def _update(self, run_id: str, **fields: str) -> None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._con:
            self._con.execute(f"UPDATE runs SET {assignments} WHERE run_id = ?", (*fields.values(), run_id))

    @staticmethod
    def _to_info(row: sqlite3.Row) -> RunInfo:
        return RunInfo(
            run_id=row["run_id"],
            status=RunStatus(row["status"]),
            request=TestRequest.model_validate_json(row["request"]),
            submitted_at=row["submitted_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
        )
