"""Routing control-flow marker for non-linear flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Goto:
    """Control-flow marker returned by a step to jump to another step.

    ``target_step_name`` names the step to execute next and ``payload`` is the
    value passed to that step as its input. A step's output contract does not
    apply to a ``Goto``; the target step validates ``payload`` through its own
    input contract.
    """

    target_step_name: str
    payload: Any
