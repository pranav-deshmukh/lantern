"""Run and structured event model for execution observability.

A ``Run`` is the coherent record of one runtime execution. It owns an ordered,
immutable-by-convention list of ``Event`` objects, each of which is small and
free of sensitive input/output payloads. This stream is the API boundary for
the future execution-graph UI: the UI reconstructs *what actually happened*
from events, not from logs or agent output.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Event:
    """A single ordered, structured runtime occurrence.

    Events are frozen and belong to exactly one run. ``data`` carries small
    structured context (targets, reasons, counts) but never arbitrary user
    input/output.
    """

    event_id: str
    run_id: str
    type: str
    timestamp: str
    step: str | None = None
    attempt: int | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A frozen dataclass alone does not protect a mutable dict. Copy and
        # wrap the payload so an emitted event cannot be changed in place.
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "step": self.step,
            "attempt": self.attempt,
            "data": dict(self.data),
        }


@dataclass
class Run:
    """A coherent record of one runtime execution."""

    run_id: str
    flow: Any
    status: str = "running"
    started_at: str | None = None
    finished_at: str | None = None
    result: Any = None
    error: BaseException | None = None
    events: list[Event] = field(default_factory=list)

    def emit(
        self,
        type: str,
        *,
        step: str | None = None,
        attempt: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> Event:
        """Append a new event to this run and return it."""
        event = Event(
            event_id=str(uuid.uuid4()),
            run_id=self.run_id,
            type=type,
            timestamp=utc_now(),
            step=step,
            attempt=attempt,
            data=dict(data or {}),
        )
        self.events.append(event)
        return event

    def summary(self) -> "RunSummary":
        """Derive summary metrics from this run's immutable event history."""
        return summarize(self)


@dataclass(frozen=True)
class RunSummary:
    """Metrics derived from a run's events."""

    status: str
    total_steps: int
    total_attempts: int
    retries: int
    recoveries: int
    failures: int
    contract_failures: int
    human_interventions: int
    duration_ms: float | None


def summarize(run: Run) -> RunSummary:
    events = run.events
    distinct_steps = {event.step for event in events if event.step is not None}
    return RunSummary(
        status=run.status,
        total_steps=len(distinct_steps),
        total_attempts=sum(1 for event in events if event.type == "step_started"),
        retries=sum(1 for event in events if event.type == "retry_started"),
        recoveries=sum(1 for event in events if event.type == "goto"),
        failures=sum(1 for event in events if event.type == "step_failed"),
        contract_failures=sum(1 for event in events if event.type == "contract_failed"),
        human_interventions=sum(
            1 for event in events if event.type == "human_approval_requested"
        ),
        duration_ms=_duration_ms(run),
    )


def _duration_ms(run: Run) -> float | None:
    if not run.started_at or not run.finished_at:
        return None
    try:
        started = datetime.fromisoformat(run.started_at)
        finished = datetime.fromisoformat(run.finished_at)
    except ValueError:
        return None
    return (finished - started).total_seconds() * 1000
