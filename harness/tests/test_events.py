"""Tests for run records and graph-ready structured runtime events."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pydantic import BaseModel

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (
    Contract,
    Flow,
    Goto,
    PolicyEngine,
    PolicyRule,
    Runtime,
    Step,
    StepExecutionError,
    Transition,
)


def test_completed_run_exposes_ordered_lifecycle_and_summary(tmp_path: Path) -> None:
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)

    assert runtime.run(Flow([Step("increment", lambda value: value + 1)]), 1) == 2

    run = runtime.last_run
    assert run is not None
    assert run.status == "completed"
    assert run.result == 2
    assert run.error is None
    assert run.started_at is not None
    assert run.finished_at is not None
    assert [event.type for event in run.events] == [
        "run_started",
        "transition",
        "step_started",
        "step_completed",
        "run_completed",
    ]
    assert all(event.run_id == run.run_id for event in run.events)
    assert run.summary().total_steps == 1
    assert run.summary().total_attempts == 1
    assert run.summary().duration_ms is not None
    with pytest.raises(TypeError):
        run.events[1].data["reason"] = "changed"  # type: ignore[index]


def test_retry_events_preserve_both_attempts(tmp_path: Path) -> None:
    calls = {"count": 0}

    def flaky(value: int) -> int:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("try again")
        return value + 1

    runtime = Runtime(max_retries=1, checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)
    assert runtime.run(Flow([Step("flaky", flaky)]), 1) == 2

    run = runtime.last_run
    assert run is not None
    assert [(event.type, event.attempt) for event in run.events] == [
        ("run_started", None),
        ("transition", 1),
        ("step_started", 1),
        ("step_failed", 1),
        ("retry_started", 2),
        ("step_started", 2),
        ("step_completed", 2),
        ("run_completed", None),
    ]
    assert run.summary().retries == 1
    assert run.summary().failures == 1


def test_goto_events_reconstruct_actual_trajectory_and_transition(tmp_path: Path) -> None:
    checks = {"count": 0}

    def check(value: int) -> int | Goto:
        checks["count"] += 1
        return Goto("draft", value) if checks["count"] == 1 else value

    flow = Flow(
        [Step("draft", lambda value: value), Step("check", check), Step("approve", lambda value: value)],
        transitions=[
            Transition("draft", "check"),
            Transition("check", "draft"),
            Transition("check", "approve"),
        ],
    )
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)
    runtime.run(flow, 1)

    run = runtime.last_run
    assert run is not None
    assert [event.step for event in run.events if event.type == "step_started"] == [
        "draft",
        "check",
        "draft",
        "check",
        "approve",
    ]
    goto = next(event for event in run.events if event.type == "goto")
    assert goto.step == "check"
    assert goto.data == {"target": "draft"}
    recovery = next(
        event
        for event in run.events
        if event.type == "transition" and event.data["reason"] == "goto"
    )
    assert recovery.data == {"source": "check", "target": "draft", "reason": "goto"}
    assert run.summary().recoveries == 1


def test_contract_failure_is_distinct_from_step_failure(tmp_path: Path) -> None:
    class Input(BaseModel):
        value: int

    class Output(BaseModel):
        result: int

    runtime = Runtime(max_retries=0, checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)
    step = Step("produce", lambda _: {"wrong": "shape"}, contract=Contract(Input, Output))

    with pytest.raises(StepExecutionError):
        runtime.run(Flow([step]), {"value": 1})

    run = runtime.last_run
    assert run is not None
    assert run.status == "failed"
    assert [event.type for event in run.events][-3:] == [
        "contract_failed",
        "step_failed",
        "run_failed",
    ]
    assert run.summary().contract_failures == 1


def test_failed_run_preserves_original_error(tmp_path: Path) -> None:
    runtime = Runtime(max_retries=0, checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)

    with pytest.raises(StepExecutionError) as error_info:
        runtime.run(Flow([Step("broken", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))]), 1)

    run = runtime.last_run
    assert run is not None
    assert run.status == "failed"
    assert run.error is error_info.value
    assert run.events[-1].type == "run_failed"


def test_human_approval_events_are_recorded(tmp_path: Path) -> None:
    engine = PolicyEngine(
        [PolicyRule("delete_*", "high", requires_approval=True)],
        approval_callback=lambda *_: True,
    )
    step = Step("delete", lambda value: value).with_governance("delete_repo", engine)
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)

    runtime.run(Flow([step]), "ok")

    run = runtime.last_run
    assert run is not None
    assert [event.type for event in run.events if event.type.startswith("human_")] == [
        "human_approval_requested",
        "human_approval_received",
    ]
    assert run.summary().human_interventions == 1
