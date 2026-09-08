"""Tests for dynamic Goto routing, jump limits, resume, tracing, and loader unions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Union, get_origin

import pytest
from pydantic import BaseModel

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (
    Contract,
    Flow,
    Goto,
    GotoTargetError,
    MaxJumpsExceeded,
    Runtime,
    Step,
    load_flow,
)
from harness.trace_viewer import load_traces


def test_plain_value_still_proceeds_sequentially(tmp_path: Path) -> None:
    flow = Flow(
        [
            Step("increment", lambda value: value + 1),
            Step("double", lambda value: value * 2),
            Step("format", lambda value: f"result={value}"),
        ]
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    assert runtime.run(flow, 2) == "result=6"


def test_goto_jumps_back_and_reexecutes_target_with_payload(tmp_path: Path) -> None:
    start_inputs: list[dict[str, int]] = []
    loop_calls = {"count": 0}

    def start(value: dict[str, int]) -> dict[str, int]:
        start_inputs.append(value)
        return {"n": value["n"] + 1}

    def loop(value: dict[str, int]) -> dict[str, int] | Goto:
        loop_calls["count"] += 1
        if value["n"] < 3:
            return Goto("start", value)
        return value

    def finish(value: dict[str, int]) -> int:
        return value["n"] * 10

    flow = Flow(
        [
            Step("start", start),
            Step("loop", loop),
            Step("finish", finish),
        ]
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    assert runtime.run(flow, {"n": 0}) == 30
    assert start_inputs == [{"n": 0}, {"n": 1}, {"n": 2}]
    assert loop_calls["count"] == 3


def test_loop_exceeding_max_jumps_raises(tmp_path: Path) -> None:
    def ping(value: object) -> Goto:
        return Goto("pong", value)

    def pong(value: object) -> Goto:
        return Goto("ping", value)

    flow = Flow([Step("ping", ping), Step("pong", pong)])
    runtime = Runtime(
        max_jumps=5, checkpoint_path=tmp_path / "cp.json", retry_delay=0
    )

    with pytest.raises(MaxJumpsExceeded) as error_info:
        runtime.run(flow, 0)

    message = str(error_info.value)
    assert "max_jumps=5" in message
    assert "infinite loop" in message


def test_goto_to_unknown_step_raises(tmp_path: Path) -> None:
    flow = Flow([Step("a", lambda value: Goto("missing", value))])
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    with pytest.raises(GotoTargetError, match="missing"):
        runtime.run(flow, 0)


def test_resume_after_crash_rehydrates_goto_checkpoint(tmp_path: Path) -> None:
    class SimulatedCrash(BaseException):
        """Represents an interruption after the gate step has checkpointed."""

    class NumberIn(BaseModel):
        n: int

    class NumberOut(BaseModel):
        n: int

    calls = {"start": 0, "gate": 0, "work": 0}
    crash = {"value": True}

    def start(data: NumberIn) -> dict[str, int]:
        calls["start"] += 1
        return {"n": data.n + 1}

    def gate(data: NumberOut) -> dict[str, int] | Goto:
        calls["gate"] += 1
        if data.n < 2:
            return Goto("work", {"n": data.n})
        return {"n": data.n}

    def work(data: NumberIn) -> dict[str, int]:
        calls["work"] += 1
        if crash["value"]:
            crash["value"] = False
            raise SimulatedCrash("stop after gate")
        return {"n": data.n * 10}

    flow = Flow(
        [
            Step("start", start, contract=Contract(NumberIn, NumberOut)),
            Step("gate", gate, contract=Contract(NumberOut, Union[NumberOut, Goto])),
            Step("work", work, contract=Contract(NumberIn, NumberOut)),
        ]
    )
    runtime = Runtime(
        checkpoint_path=tmp_path / "cp.json", run_id="routing-resume", retry_delay=0
    )

    with pytest.raises(SimulatedCrash):
        runtime.run(flow, {"n": 0})

    checkpoint = json.loads((tmp_path / "cp.json").read_text(encoding="utf-8"))
    assert checkpoint["step_name"] == "gate"
    assert checkpoint["output_is_goto"] is True
    assert checkpoint["jumps"] == 1

    result = runtime.run(flow, {"n": 0})

    assert result.model_dump() == {"n": 10}
    assert calls == {"start": 1, "gate": 1, "work": 2}


def test_trace_records_jump_metadata(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"

    def start(value: dict[str, int]) -> dict[str, int]:
        return {"n": value["n"] + 1}

    def loop(value: dict[str, int]) -> dict[str, int] | Goto:
        if value["n"] < 2:
            return Goto("start", {"n": value["n"] + 1})
        return value

    flow = Flow([Step("start", start), Step("loop", loop)])
    runtime = Runtime(
        checkpoint_path=tmp_path / "cp.json",
        trace_path=trace_path,
        retry_delay=0,
    )

    runtime.run(flow, {"n": 0})

    records = load_traces(str(trace_path))
    assert [record["step_name"] for record in records] == [
        "start",
        "loop",
        "start",
        "loop",
    ]
    assert records[0]["reached_via_jump"] is False
    assert records[0]["jumped_from"] is None
    assert records[1]["reached_via_jump"] is False
    assert records[2]["reached_via_jump"] is True
    assert records[2]["jumped_from"] == "loop"
    assert records[3]["reached_via_jump"] is False


HELPER_MODULE_SOURCE = '''\
"""Helpers for the routing loader test."""

from typing import Union

from pydantic import BaseModel

from harness import Goto


class NumberIn(BaseModel):
    n: int


class VerifyPassed(BaseModel):
    status: str


VerifyOutput = Union[VerifyPassed, Goto]


def verify(data):
    if data.n < 1:
        return {"target_step_name": "verify", "payload": {"n": data.n + 1}}
    return {"status": "passed"}
'''


@pytest.fixture
def helper_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    module_path = tmp_path / "routing_helpers.py"
    module_path.write_text(HELPER_MODULE_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return module_path


def test_loader_accepts_union_output_model_and_coerces_goto(
    helper_module: Path,
) -> None:
    yaml_path = helper_module.parent / "union_flow.yaml"
    yaml_path.write_text(
        """\
steps:
  - name: verify
    function: routing_helpers.verify
    input_model: routing_helpers.NumberIn
    output_model: routing_helpers.VerifyOutput
""",
        encoding="utf-8",
    )

    flow = load_flow(str(yaml_path))
    step = flow.steps[0]

    assert get_origin(step.contract.output_model) is Union

    runtime = Runtime(
        checkpoint_path=helper_module.parent / "cp.json", retry_delay=0
    )
    result = runtime.run(flow, {"n": 0})

    assert result.model_dump() == {"status": "passed"}
