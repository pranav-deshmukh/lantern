"""Tests for automatic runtime tracing and the trace viewer."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import Flow, Runtime, Step, StepExecutionError
from harness.trace_viewer import print_trace


def _read_trace(trace_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]


def test_three_step_flow_writes_one_trace_line_per_step(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    runtime = Runtime(
        checkpoint_path=tmp_path / "checkpoint.json",
        trace_path=trace_path,
        run_id="three-steps",
        retry_delay=0,
    )
    flow = Flow(
        [
            Step("increment", lambda value: value + 1),
            Step("double", lambda value: value * 2),
            Step("format", lambda value: f"value={value}"),
        ]
    )

    assert runtime.run(flow, 2) == "value=6"

    records = _read_trace(trace_path)
    assert len(records) == 3
    assert [record["step_name"] for record in records] == [
        "increment",
        "double",
        "format",
    ]
    assert all(record["succeeded"] is True for record in records)


def test_exhausted_failure_is_written_to_the_trace(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"

    def fail(_: object) -> object:
        raise RuntimeError("service unavailable")

    runtime = Runtime(
        max_retries=0,
        checkpoint_path=tmp_path / "checkpoint.json",
        trace_path=trace_path,
        run_id="failure",
        retry_delay=0,
    )

    with pytest.raises(StepExecutionError):
        runtime.run(Flow([Step("persist", fail)]), "input")

    records = _read_trace(trace_path)
    assert len(records) == 1
    assert records[0]["succeeded"] is False
    assert "service unavailable" in str(records[0]["error"])


def test_trace_viewer_prints_step_names_in_trace_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trace_path = tmp_path / "sample.jsonl"
    trace_path.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {
                    "run_id": "viewer-run",
                    "step_name": "first",
                    "duration_ms": 1.5,
                    "succeeded": True,
                    "error": None,
                },
                {
                    "run_id": "viewer-run",
                    "step_name": "second",
                    "duration_ms": 2.5,
                    "succeeded": False,
                    "error": "RuntimeError: failed",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print_trace(trace_path)

    output = capsys.readouterr().out
    assert "viewer-run" in output
    assert output.index("first") < output.index("second")


def test_retries_write_one_trace_record_per_attempt(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    attempts = {"count": 0}

    def flaky(value: int) -> int:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("try again")
        return value + 1

    runtime = Runtime(
        checkpoint_path=tmp_path / "checkpoint.json",
        trace_path=trace_path,
        run_id="retries",
        retry_delay=0,
    )

    assert runtime.run(Flow([Step("flaky", flaky)]), 4) == 5

    records = _read_trace(trace_path)
    assert len(records) == 3
    assert [record["succeeded"] for record in records] == [False, False, True]
