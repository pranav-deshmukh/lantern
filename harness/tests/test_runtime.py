"""Tests for the plain-Python harness runtime."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import Flow, Runtime, Step, StepExecutionError


def test_three_step_flow_runs_end_to_end(tmp_path: Path) -> None:
    flow = Flow(
        [
            Step("increment", lambda value: value + 1),
            Step("double", lambda value: value * 2),
            Step("format", lambda value: f"result={value}"),
        ]
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    runtime = Runtime(
        run_id="end-to-end", checkpoint_path=checkpoint_path, retry_delay=0
    )

    assert runtime.run(flow, 2) == "result=6"
    assert json.loads(checkpoint_path.read_text(encoding="utf-8")) == {
        "run_id": "end-to-end",
        "step_index": 2,
        "step_name": "format",
        "output": "result=6",
    }


def test_step_is_retried_until_its_third_attempt(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def flaky_step(value: int) -> int:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("not ready")
        return value + 10

    runtime = Runtime(
        run_id="retry", checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0
    )

    assert runtime.run(Flow([Step("flaky", flaky_step)]), 5) == 15
    assert attempts["count"] == 3


def test_always_failing_step_names_the_step_and_cause(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def always_fail(_: object) -> object:
        attempts["count"] += 1
        raise RuntimeError("database unavailable")

    runtime = Runtime(
        run_id="failure", checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0
    )

    with pytest.raises(StepExecutionError, match="persist") as error_info:
        runtime.run(Flow([Step("persist", always_fail)]), "input")

    assert "database unavailable" in str(error_info.value)
    assert isinstance(error_info.value.__cause__, RuntimeError)
    assert attempts["count"] == 3  # One initial attempt and two retries.


def test_run_resumes_after_an_interruption_without_repeating_completed_steps(
    tmp_path: Path,
) -> None:
    class SimulatedCrash(BaseException):
        """Represents an abrupt process interruption, which Runtime should not catch."""

    calls = {"first": 0, "second": 0, "third": 0}
    should_crash = {"value": True}

    def first(value: int) -> int:
        calls["first"] += 1
        return value + 1

    def second(value: int) -> int:
        calls["second"] += 1
        return value * 2

    def third(value: int) -> int:
        calls["third"] += 1
        if should_crash["value"]:
            should_crash["value"] = False
            raise SimulatedCrash("stop after the second completed step")
        return value - 3

    flow = Flow([Step("first", first), Step("second", second), Step("third", third)])
    runtime = Runtime(
        run_id="resume", checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0
    )

    with pytest.raises(SimulatedCrash):
        runtime.run(flow, 4)

    # The checkpoint created after step two supplies the input for step three.
    assert runtime.run(flow, 4) == 7
    assert calls == {"first": 1, "second": 1, "third": 2}
