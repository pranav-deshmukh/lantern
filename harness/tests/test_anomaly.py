"""Tests for baseline comparison and anomaly detection over JSONL traces."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import Baseline, find_anomalies, load_traces


def _write_trace(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _baseline_records(*durations: float, step_name: str = "increment") -> list[dict[str, object]]:
    return [
        {
            "run_id": f"run-{index}",
            "step_name": step_name,
            "duration_ms": duration,
            "succeeded": True,
            "error": None,
        }
        for index, duration in enumerate(durations, start=1)
    ]


def test_load_traces_reads_all_jsonl_records(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    records = [
        {"run_id": "a", "step_name": "first", "succeeded": True},
        {"run_id": "a", "step_name": "second", "succeeded": False},
    ]
    _write_trace(trace_path, records)

    assert load_traces(str(trace_path)) == records


def test_run_matching_baseline_has_no_anomalies(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.jsonl"
    _write_trace(baseline_path, _baseline_records(10.0, 11.0, 12.0))

    new_path = tmp_path / "new.jsonl"
    _write_trace(
        new_path,
        [
            {
                "run_id": "new-run",
                "step_name": "increment",
                "duration_ms": 11.0,
                "succeeded": True,
                "error": None,
            }
        ],
    )

    findings = find_anomalies(new_path, Baseline([baseline_path]))

    assert findings == []


def test_slow_step_is_flagged_with_step_name_in_reason(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.jsonl"
    _write_trace(baseline_path, _baseline_records(10.0, 11.0, 12.0))

    new_path = tmp_path / "new.jsonl"
    _write_trace(
        new_path,
        [
            {
                "run_id": "new-run",
                "step_name": "increment",
                "duration_ms": 20.0,
                "succeeded": True,
                "error": None,
            }
        ],
    )

    findings = find_anomalies(new_path, Baseline([baseline_path]))

    assert len(findings) == 1
    assert findings[0]["step_name"] == "increment"
    assert "increment" in findings[0]["reason"]
    assert findings[0]["severity"] == "warning"


def test_unrecognized_step_is_flagged(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.jsonl"
    _write_trace(baseline_path, _baseline_records(10.0, step_name="known"))

    new_path = tmp_path / "new.jsonl"
    _write_trace(
        new_path,
        [
            {
                "run_id": "new-run",
                "step_name": "mystery",
                "duration_ms": 10.0,
                "succeeded": True,
                "error": None,
            }
        ],
    )

    findings = find_anomalies(new_path, Baseline([baseline_path]))

    assert len(findings) == 1
    assert findings[0]["step_name"] == "mystery"
    assert "mystery" in findings[0]["reason"]
    assert findings[0]["severity"] == "info"


def test_failed_step_is_flagged_regardless_of_duration(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.jsonl"
    _write_trace(baseline_path, _baseline_records(10.0, 11.0, 12.0))

    new_path = tmp_path / "new.jsonl"
    _write_trace(
        new_path,
        [
            {
                "run_id": "new-run",
                "step_name": "increment",
                "duration_ms": 5.0,
                "succeeded": False,
                "error": "RuntimeError: boom",
            }
        ],
    )

    findings = find_anomalies(new_path, Baseline([baseline_path]))

    assert len(findings) == 1
    assert findings[0]["step_name"] == "increment"
    assert "increment" in findings[0]["reason"]
    assert "boom" in findings[0]["reason"]
    assert findings[0]["severity"] == "critical"


def test_baseline_with_zero_successful_runs_raises(tmp_path: Path) -> None:
    trace_path = tmp_path / "only_failures.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "run_id": "failed-1",
                "step_name": "increment",
                "duration_ms": 10.0,
                "succeeded": False,
                "error": "boom",
            },
            {
                "run_id": "failed-2",
                "step_name": "increment",
                "duration_ms": 10.0,
                "succeeded": False,
                "error": "boom",
            },
        ],
    )

    with pytest.raises(ValueError, match="successful"):
        Baseline([trace_path])


def test_duplicate_step_names_count_as_separate_samples(tmp_path: Path) -> None:
    # Traces record only step_name, not step position, so repeated occurrences
    # of one name in a run are treated as independent observations of that step.
    trace_path = tmp_path / "duplicate_names.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "run_id": "single-run",
                "step_name": "increment",
                "duration_ms": 10.0,
                "succeeded": True,
                "error": None,
            },
            {
                "run_id": "single-run",
                "step_name": "increment",
                "duration_ms": 20.0,
                "succeeded": True,
                "error": None,
            },
        ],
    )

    baseline = Baseline([trace_path])

    assert baseline.sample_count("increment") == 2
    assert baseline.average_duration_ms("increment") == 15.0
