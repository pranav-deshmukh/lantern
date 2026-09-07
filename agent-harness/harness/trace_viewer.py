"""Small terminal viewer for JSONL trace files."""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


def print_trace(trace_path: str | Path) -> None:
    """Print a concise, grouped summary of the trace records in ``trace_path``."""
    runs: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

    with Path(trace_path).open("r", encoding="utf-8") as trace_file:
        for line in trace_file:
            if not line.strip():
                continue
            record = json.loads(line)
            runs.setdefault(record["run_id"], []).append(record)

    for run_id, records in runs.items():
        print(f"Run {run_id}")
        total_duration = 0.0
        for record in records:
            duration = record["duration_ms"]
            total_duration += duration
            status = "✓" if record["succeeded"] else "✗"
            print(f"  {status} {record['step_name']} ({duration:.3f} ms)")
            if record["error"]:
                print(f"    {record['error']}")
        print(f"Total duration: {total_duration:.3f} ms")
