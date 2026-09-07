"""Tests for policy matching, approvals, and governed steps."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (
    Flow,
    PolicyDecision,
    PolicyEngine,
    PolicyRule,
    PolicyViolation,
    Runtime,
    Step,
)


def test_action_with_no_matching_rule_is_allowed() -> None:
    engine = PolicyEngine([])

    assert engine.check("create_repo") is PolicyDecision.ALLOW


def test_non_approval_rule_allows_without_calling_callback() -> None:
    callback_calls = {"count": 0}

    def callback(_: str, __: str) -> bool:
        callback_calls["count"] += 1
        return False

    engine = PolicyEngine(
        [PolicyRule("read_*", "low", requires_approval=False)], callback
    )
    step = Step("read", lambda value: value).with_governance("read_repo", engine)

    assert step.execute("ok") == "ok"
    assert callback_calls["count"] == 0


def test_approved_action_runs_the_step_function() -> None:
    calls = {"count": 0}
    engine = PolicyEngine(
        [PolicyRule("delete_*", "high", requires_approval=True)],
        approval_callback=lambda action, risk: action == "delete_repo" and risk == "high",
    )

    def delete(value: str) -> str:
        calls["count"] += 1
        return value.upper()

    step = Step("delete", delete).with_governance("delete_repo", engine)

    assert step.execute("done") == "DONE"
    assert calls["count"] == 1


def test_denied_action_raises_without_running_the_step() -> None:
    calls = {"count": 0}
    engine = PolicyEngine(
        [PolicyRule("delete_*", "critical", requires_approval=True)],
        approval_callback=lambda _action, _risk: False,
    )

    def delete(value: str) -> str:
        calls["count"] += 1
        return value

    step = Step("delete", delete).with_governance("delete_repo", engine)

    with pytest.raises(PolicyViolation, match="delete_repo"):
        step.execute("never used")

    assert calls["count"] == 0


def test_denied_action_is_not_retried_by_runtime(tmp_path: Path) -> None:
    callback_calls = {"count": 0}

    def deny(_: str, __: str) -> bool:
        callback_calls["count"] += 1
        return False

    engine = PolicyEngine(
        [PolicyRule("delete_*", "high", requires_approval=True)], deny
    )
    step = Step("delete", lambda value: value).with_governance("delete_repo", engine)
    runtime = Runtime(
        max_retries=2,
        checkpoint_path=tmp_path / "checkpoint.json",
        retry_delay=0,
    )

    with pytest.raises(PolicyViolation):
        runtime.run(Flow([step]), "input")

    assert callback_calls["count"] == 1


def test_trailing_wildcard_matches_only_the_expected_action_prefix() -> None:
    engine = PolicyEngine([PolicyRule("delete_*", "high", requires_approval=True)])

    assert engine.check("delete_repo") is PolicyDecision.REQUIRES_APPROVAL
    assert engine.check("create_repo") is PolicyDecision.ALLOW
