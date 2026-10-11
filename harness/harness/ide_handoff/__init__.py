"""Opt-in file-based handoff helpers for human-operated IDE agents."""

from .agent import (
    IdeHandoffConfig,
    IdeHandoffError,
    IdeHandoffStep,
    IdeHandoffTimeout,
    make_ide_handoff_step,
    new_run_id,
)
from .checks import PatternRule, make_pattern_check_step
from .handoff_decision import (
    HandoffDecisionError,
    goto_from_handoff,
    make_orchestrator_step,
)
from .packet import compose_ide_packet

__all__ = [
    "HandoffDecisionError",
    "IdeHandoffConfig",
    "IdeHandoffError",
    "IdeHandoffStep",
    "IdeHandoffTimeout",
    "PatternRule",
    "compose_ide_packet",
    "goto_from_handoff",
    "make_ide_handoff_step",
    "make_orchestrator_step",
    "make_pattern_check_step",
    "new_run_id",
]
