"""Cross-run baseline comparison and anomaly detection from JSONL traces.

A trace record produced by :class:`Tracer` contains ``run_id``, ``step_name``,
``duration_ms``, ``succeeded``, and ``error``. This module compares one new
trace against statistics learned from past successful traces.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .trace_viewer import load_traces


class Baseline:
    """Duration statistics for step names observed in past successful runs.

    A *successful run* is a ``run_id`` whose every record has ``succeeded``
    equal to ``True``. Failed runs (or runs containing any failed attempt) are
    excluded from the baseline because their timings describe broken work and
    would skew the "normal" duration statistics.
    """

    def __init__(self, trace_files: Iterable[str | Path]) -> None:
        self._durations: dict[str, list[float]] = {}
        successful_runs = 0

        for trace_file in trace_files:
            for run_records in _group_by_run(load_traces(trace_file)).values():
                if not _is_successful_run(run_records):
                    continue
                successful_runs += 1
                for record in run_records:
                    step_name = record.get("step_name")
                    duration = record.get("duration_ms")
                    if not isinstance(step_name, str) or not isinstance(
                        duration, (int, float)
                    ):
                        continue
                    self._durations.setdefault(step_name, []).append(float(duration))

        if successful_runs == 0:
            raise ValueError(
                "Baseline requires at least one fully successful run; "
                "none of the provided trace files contained one."
            )

        # Sample standard deviation (n-1) is used because the traces are a
        # sample of all possible runs. A single data point has no spread, so
        # its standard deviation is stored as 0.0 rather than dividing by zero.
        self._averages = {
            name: statistics.mean(durations)
            for name, durations in self._durations.items()
        }
        self._stddevs = {
            name: statistics.stdev(durations) if len(durations) >= 2 else 0.0
            for name, durations in self._durations.items()
        }

    @property
    def known_step_names(self) -> frozenset[str]:
        """Return the set of step names observed in successful baseline runs."""
        return frozenset(self._durations)

    def is_known(self, step_name: str) -> bool:
        """Return whether ``step_name`` appeared in any successful baseline run."""
        return step_name in self._durations

    def sample_count(self, step_name: str) -> int:
        """Return how many successful occurrences were recorded for ``step_name``."""
        return len(self._durations.get(step_name, ()))

    def average_duration_ms(self, step_name: str) -> float | None:
        """Return the average duration in milliseconds for ``step_name``."""
        return self._averages.get(step_name)

    def stddev_duration_ms(self, step_name: str) -> float | None:
        """Return the standard deviation of durations for ``step_name``."""
        return self._stddevs.get(step_name)


def find_anomalies(new_trace_path: str | Path, baseline: Baseline) -> list[dict[str, Any]]:
    """Compare a new trace against ``baseline`` and return anomaly findings.

    Each finding is a dict with ``step_name``, ``reason``, and ``severity``.
    Severity scheme:

    * ``"critical"`` — the step failed (``succeeded`` is not ``True``).
    * ``"warning"``  — the step succeeded but took more than 2 standard
      deviations longer than its baseline average (only checked when the
      baseline has at least 2 data points for that step, since a standard
      deviation is not meaningful from a single point).
    * ``"info"``     — the step name was not seen in any baseline run.

    A failed record is reported only as a failure (``critical``): a failed
    attempt's duration is not comparable to successful baseline timings, and a
    failure already demands attention, so extra "slow"/"unrecognized" findings
    would only add noise.
    """
    if not isinstance(baseline, Baseline):
        raise TypeError("baseline must be a Baseline instance.")

    findings: list[dict[str, Any]] = []
    for record in load_traces(new_trace_path):
        step_name = record.get("step_name")
        if not isinstance(step_name, str) or not step_name:
            continue

        if record.get("succeeded") is not True:
            error = record.get("error") or "no error recorded"
            findings.append(
                {
                    "step_name": step_name,
                    "reason": f"Step '{step_name}' failed: {error}",
                    "severity": "critical",
                }
            )
            continue

        if not baseline.is_known(step_name):
            findings.append(
                {
                    "step_name": step_name,
                    "reason": f"Step '{step_name}' was not seen in any baseline run.",
                    "severity": "info",
                }
            )
            continue

        if baseline.sample_count(step_name) >= 2:
            duration = record.get("duration_ms")
            if isinstance(duration, (int, float)):
                average = baseline.average_duration_ms(step_name)
                stddev = baseline.stddev_duration_ms(step_name)
                if (
                    average is not None
                    and stddev is not None
                    and duration > average + 2 * stddev
                ):
                    findings.append(
                        {
                            "step_name": step_name,
                            "reason": (
                                f"Step '{step_name}' took {duration:.3f} ms, more than "
                                f"2 standard deviations above its baseline average of "
                                f"{average:.3f} ms."
                            ),
                            "severity": "warning",
                        }
                    )

    return findings


def _group_by_run(
    records: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group trace records by their ``run_id``, preserving first-seen order."""
    runs: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        run_id = record.get("run_id")
        if run_id is None:
            continue
        runs.setdefault(run_id, []).append(record)
    return runs


def _is_successful_run(records: list[dict[str, Any]]) -> bool:
    """Return whether every record in a run reports ``succeeded`` as ``True``."""
    return bool(records) and all(
        record.get("succeeded") is True for record in records
    )
