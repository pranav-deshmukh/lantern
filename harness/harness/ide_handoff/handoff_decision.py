"""Validated routing helpers for orchestrator IDE handoff artifacts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from harness.routing import Goto

from .agent import IdeHandoffConfig, IdeHandoffStep


class HandoffDecisionError(ValueError):
    """Raised when an orchestrator artifact names an invalid next step."""


def goto_from_handoff(artifact: dict[str, Any], *, valid_step_names: set[str]) -> Goto:
    """Build a validated ``Goto`` from an orchestrator artifact.

    If ``payload`` is absent, the payload is the artifact without
    ``next_step``, ``packet_id``, and ``handoff``.
    """
    next_step = artifact.get("next_step")
    if not isinstance(next_step, str):
        raise HandoffDecisionError("Handoff artifact requires string 'next_step'.")
    if next_step not in valid_step_names:
        raise HandoffDecisionError(
            f"Invalid next_step '{next_step}'; valid steps are {sorted(valid_step_names)}."
        )
    if "payload" in artifact:
        payload = artifact["payload"]
    else:
        payload = {
            key: value
            for key, value in artifact.items()
            if key not in {"next_step", "packet_id", "handoff"}
        }
    return Goto(next_step, payload)


def make_orchestrator_step(
    step_name: str,
    config: IdeHandoffConfig,
    valid_step_names: set[str],
    **kwargs: Any,
) -> Callable[..., Goto]:
    """Return an IDE handoff step that emits a validated ``Goto``."""
    handoff = IdeHandoffStep(step_name, config, **kwargs)

    def run(task: Any, context: Any = None) -> Goto:
        artifact = handoff.run(task, context=context)
        return goto_from_handoff(artifact, valid_step_names=valid_step_names)

    return run
