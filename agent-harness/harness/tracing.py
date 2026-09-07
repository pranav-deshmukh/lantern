"""Automatic JSONL tracing for runtime step executions."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel


Result = TypeVar("Result")


class Tracer:
    """Record each step execution attempt and optionally append it to a JSONL file."""

    def __init__(self, trace_path: str | Path | None = None) -> None:
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self.records: list[dict[str, Any]] = []

    def execute(
        self,
        *,
        run_id: str,
        step_name: str,
        input_value: Any,
        operation: Callable[[], Result],
    ) -> Result:
        """Run an operation and persist a trace record whether it succeeds or fails."""
        timestamp = datetime.now(timezone.utc).isoformat()
        started_at = time.perf_counter()

        try:
            output = operation()
        except BaseException as error:
            self._record(
                run_id=run_id,
                step_name=step_name,
                input_value=input_value,
                output_value=None,
                timestamp=timestamp,
                duration_ms=self._duration_ms(started_at),
                succeeded=False,
                error_message=f"{type(error).__name__}: {error}",
            )
            raise

        self._record(
            run_id=run_id,
            step_name=step_name,
            input_value=input_value,
            output_value=output,
            timestamp=timestamp,
            duration_ms=self._duration_ms(started_at),
            succeeded=True,
            error_message=None,
        )
        return output

    def _record(
        self,
        *,
        run_id: str,
        step_name: str,
        input_value: Any,
        output_value: Any,
        timestamp: str,
        duration_ms: float,
        succeeded: bool,
        error_message: str | None,
    ) -> None:
        record = {
            "run_id": run_id,
            "step_name": step_name,
            "input": self._json_value(input_value),
            "output": self._json_value(output_value),
            "duration_ms": duration_ms,
            "timestamp": timestamp,
            "succeeded": succeeded,
            "error": error_message,
        }
        self.records.append(record)

        if self.trace_path is not None:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as trace_file:
                trace_file.write(json.dumps(record) + "\n")
                trace_file.flush()

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 3)

    @staticmethod
    def _json_value(value: Any) -> Any:
        """Convert arbitrary values to a stable JSON-compatible representation."""
        return json.loads(json.dumps(value, default=Tracer._json_default))

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return repr(value)
