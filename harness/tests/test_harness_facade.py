"""Tests for the beginner-friendly Harness façade and Agent protocol."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import Agent, Flow, Harness, Runtime, Step


def test_harness_wraps_custom_class_with_run_method(tmp_path: Path) -> None:
    class MyAgent:
        def run(self, input):
            return f"processed: {input}"

    harness = Harness(MyAgent(), checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    assert harness.run("hello") == "processed: hello"


def test_harness_wraps_plain_function(tmp_path: Path) -> None:
    def double(input):
        return input * 2

    harness = Harness(double, checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    assert harness.run(21) == 42


def test_harness_wraps_flow_identically_to_runtime(tmp_path: Path) -> None:
    flow = Flow(
        [
            Step("increment", lambda value: value + 1),
            Step("double", lambda value: value * 2),
        ]
    )

    harness = Harness(flow, checkpoint_path=tmp_path / "cp.json", retry_delay=0)
    direct = Runtime(checkpoint_path=tmp_path / "cp2.json", retry_delay=0)

    assert harness.run(2) == direct.run(flow, 2) == 6


def test_harness_supports_crash_resume(tmp_path: Path) -> None:
    class SimulatedCrash(BaseException):
        """Represents an abrupt process interruption, which Runtime should not catch."""

    calls = {"first": 0, "second": 0}
    crash = {"value": True}

    def first(value):
        calls["first"] += 1
        return value + 1

    def second(value):
        calls["second"] += 1
        if crash["value"]:
            crash["value"] = False
            raise SimulatedCrash("stop after the first completed step")
        return value * 2

    flow = Flow([Step("first", first), Step("second", second)])
    harness = Harness(
        flow,
        checkpoint_path=tmp_path / "cp.json",
        run_id="harness-resume",
        retry_delay=0,
    )

    with pytest.raises(SimulatedCrash):
        harness.run(2)

    assert harness.run(2) == 6
    assert calls == {"first": 1, "second": 2}


def test_wrapped_agent_needs_zero_harness_imports() -> None:
    # This class body intentionally references no harness types whatsoever.
    class BareAgent:
        def run(self, input):
            return input.upper()

    harness = Harness(BareAgent(), retry_delay=0)

    assert harness.run("abc") == "ABC"


def test_agent_protocol_is_importable() -> None:
    assert Agent is not None
