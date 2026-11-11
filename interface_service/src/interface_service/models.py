"""Request and response schemas of the HTTP API (also the source of the OpenAPI spec at /docs)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class RunStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class TestRequest(BaseModel):
    __test__ = False  # keep pytest from collecting this class

    protocol: str = Field(min_length=1, description="BlueWasher protocol to execute.")
    n_washes: int = Field(ge=1, description="How often the protocol is applied to the plate.")
    coverage_checks: list[int] = Field(
        description="Wash numbers (1..n_washes) after which a coverage check is done. "
        "The checks before the first wash (0) and after the last wash are always done and added if missing.",
    )

    @model_validator(mode="after")
    def _check_coverage_checks(self) -> "TestRequest":
        out_of_range = [c for c in self.coverage_checks if not 0 <= c <= self.n_washes]
        if out_of_range:
            raise ValueError(f"coverage_checks {out_of_range} not within 0..n_washes ({self.n_washes})")
        if len(set(self.coverage_checks)) != len(self.coverage_checks):
            raise ValueError("coverage_checks contains duplicates")
        self.coverage_checks = sorted(set(self.coverage_checks) | {0, self.n_washes})
        return self


class SubmitResponse(BaseModel):
    run_id: str


class Capacity(BaseModel):
    max_parallel: int
    active: int = Field(description="Runs that are waiting or running.")
    free: int = Field(description="Number of further tests accepted right now.")


class RunInfo(BaseModel):
    run_id: str
    status: RunStatus
    request: TestRequest
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class CoverageImage(BaseModel):
    after_wash: int
    image_url: str


class RunResult(BaseModel):
    run_id: str
    images: list[CoverageImage]
