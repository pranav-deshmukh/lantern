"""Flow enforcement v1: Lantern—not the agent—owns workflow transitions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (
    Contract,
    Flow,
    Goto,
    IllegalTransitionError,
    Runtime,
    Step,
    StepExecutionError,
    Transition,
)
from harness.trace_viewer import load_traces


def test_sequential_flow_executes_in_declared_order(tmp_path: Path) -> None:
    order: list[str] = []

    def make(name: str, result: int):
        def fn(value: int) -> int:
            order.append(name)
            return result

        return fn

    flow = Flow(
        [
            Step("A", make("A", 1)),
            Step("B", make("B", 2)),
            Step("C", make("C", 3)),
        ],
        transitions=[Transition("A", "B"), Transition("B", "C")],
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    result = runtime.run(flow, 0)

    assert result == 3
    assert order == ["A", "B", "C"]


def test_skipped_step_is_rejected(tmp_path: Path) -> None:
    # A -> B -> C is declared; the agent attempts A -> C (skipping B).
    flow = Flow(
        [
            Step("A", lambda value: Goto("C", value)),
            Step("B", lambda value: value),
            Step("C", lambda value: value),
        ],
        transitions=[Transition("A", "B"), Transition("B", "C")],
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    with pytest.raises(IllegalTransitionError, match="A.*C"):
        runtime.run(flow, 0)

    assert runtime.state.status == "rejected"


def test_undeclared_sequential_next_is_rejected(tmp_path: Path) -> None:
    # B -> C is NOT declared, so even though C is immediately after B in the
    # step list, a plain return from B must not advance to C.
    flow = Flow(
        [
            Step("A", lambda value: value),
            Step("B", lambda value: value),
            Step("C", lambda value: value),
            Step("D", lambda value: value),
        ],
        transitions=[Transition("A", "B"), Transition("B", "D")],
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    with pytest.raises(IllegalTransitionError, match="B.*C"):
        runtime.run(flow, 0)


def test_valid_branch_can_select_declared_target(tmp_path: Path) -> None:
    def build_flow(select_d: bool):
        order: list[str] = []

        def make(name: str):
            def fn(value: int) -> int:
                order.append(name)
                if name == "B" and select_d:
                    return Goto("D", value)
                return value

            return fn

        flow = Flow(
            [
                Step("A", make("A")),
                Step("B", make("B")),
                Step("C", make("C")),
                Step("D", make("D")),
            ],
            transitions=[
                Transition("A", "B"),
                Transition("B", "C"),
                Transition("B", "D"),
                Transition("C", "D"),
            ],
        )
        return flow, order

    flow, order = build_flow(select_d=False)
    Runtime(checkpoint_path=tmp_path / "cp1.json", retry_delay=0).run(flow, 0)
    assert order == ["A", "B", "C", "D"]

    flow, order = build_flow(select_d=True)
    Runtime(checkpoint_path=tmp_path / "cp2.json", retry_delay=0).run(flow, 0)
    assert order == ["A", "B", "D"]


def test_invalid_branch_is_rejected(tmp_path: Path) -> None:
    flow = Flow(
        [
            Step("A", lambda value: value),
            Step("B", lambda value: Goto("X", value)),
            Step("C", lambda value: value),
            Step("D", lambda value: value),
            Step("X", lambda value: value),
        ],
        transitions=[Transition("A", "B"), Transition("B", "D")],
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    with pytest.raises(IllegalTransitionError, match="B.*X"):
        runtime.run(flow, 0)


def test_goto_recovery_loop(tmp_path: Path) -> None:
    order: list[str] = []
    quality_checks = {"count": 0}

    def classify(value: int) -> int:
        order.append("classify")
        return value

    def draft(value: int) -> int:
        order.append("draft")
        return value

    def quality_check(value: int) -> int:
        order.append("quality_check")
        quality_checks["count"] += 1
        if quality_checks["count"] == 1:
            return Goto("draft", value)
        return value

    def approve(value: int) -> int:
        order.append("approve")
        return value

    flow = Flow(
        [
            Step("classify", classify),
            Step("draft", draft),
            Step("quality_check", quality_check),
            Step("approve", approve),
        ],
        transitions=[
            Transition("classify", "draft"),
            Transition("draft", "quality_check"),
            Transition("quality_check", "draft"),
            Transition("quality_check", "approve"),
        ],
    )
    runtime = Runtime(
        checkpoint_path=tmp_path / "cp.json", max_jumps=10, retry_delay=0
    )

    result = runtime.run(flow, 0)

    assert result == 0
    assert order == ["classify", "draft", "quality_check", "draft", "quality_check", "approve"]
    reasons = [record.reason for record in runtime.state.transition_history]
    assert "goto" in reasons


def test_agent_cannot_bypass_flow(tmp_path: Path) -> None:
    order: list[str] = []

    def a(value: int) -> dict:
        order.append("A")
        # The agent tries to suggest skipping B; Lantern must ignore this.
        return {"output": value, "next_step": "C"}

    def b(value: dict) -> dict:
        order.append("B")
        return value

    def c(value: dict) -> dict:
        order.append("C")
        return value

    flow = Flow(
        [
            Step("A", a),
            Step("B", b),
            Step("C", c),
        ],
        transitions=[Transition("A", "B"), Transition("B", "C")],
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    result = runtime.run(flow, 0)

    assert order == ["A", "B", "C"]
    assert result == {"output": 0, "next_step": "C"}


def test_contract_failure_prevents_advancement(tmp_path: Path) -> None:
    class NumberInput(BaseModel):
        value: int

    class NumberOutput(BaseModel):
        result: int

    order: list[str] = []

    def a(value: NumberInput) -> dict:
        order.append("A")
        return {"wrong_field": "not a number"}

    def b(value: int) -> int:
        order.append("B")
        return value

    flow = Flow(
        [
            Step("A", a, contract=Contract(NumberInput, NumberOutput)),
            Step("B", b),
        ],
        transitions=[Transition("A", "B")],
    )
    runtime = Runtime(
        checkpoint_path=tmp_path / "cp.json", max_retries=0, retry_delay=0
    )

    with pytest.raises(StepExecutionError):
        runtime.run(flow, {"value": 1})

    assert order == ["A"]  # B never ran
    assert runtime.state.status == "failed"


def test_rules_are_scoped_to_the_correct_step(tmp_path: Path) -> None:
    draft_rules = tmp_path / "draft_rules.md"
    draft_rules.write_text("DRAFT RULE\n", encoding="utf-8")
    review_rules = tmp_path / "review_rules.md"
    review_rules.write_text("REVIEW RULE\n", encoding="utf-8")

    received: dict[str, str | None] = {}

    def draft(value: object, context) -> object:
        received["draft"] = context.rules.as_text() if context.rules else None
        return value

    def review(value: object, context) -> object:
        received["review"] = context.rules.as_text() if context.rules else None
        return value

    flow = Flow(
        [
            Step("draft", draft, rules_files=[str(draft_rules)]),
            Step("review", review, rules_files=[str(review_rules)]),
        ],
        transitions=[Transition("draft", "review")],
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    runtime.run(flow, "x")

    assert received["draft"] == f"--- {draft_rules} ---\nDRAFT RULE\n"
    assert received["review"] == f"--- {review_rules} ---\nREVIEW RULE\n"


def test_trace_records_transitions(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    quality_checks = {"count": 0}

    def a(value: int) -> int:
        return value

    def b(value: int) -> int:
        return value

    def c(value: int) -> int:
        quality_checks["count"] += 1
        if quality_checks["count"] == 1:
            return Goto("B", value)
        return value

    flow = Flow(
        [
            Step("A", a),
            Step("B", b),
            Step("C", c),
        ],
        transitions=[Transition("A", "B"), Transition("B", "C"), Transition("C", "B")],
    )
    runtime = Runtime(
        trace_path=trace_path,
        checkpoint_path=tmp_path / "cp.json",
        max_jumps=10,
        retry_delay=0,
    )

    runtime.run(flow, 0)

    records = load_traces(str(trace_path))
    assert [record["step_name"] for record in records] == ["A", "B", "C", "B", "C"]
    assert records[0]["transition"] == {"from": None, "to": "A", "reason": "start", "attempt": 1}
    assert records[1]["transition"] == {"from": "A", "to": "B", "reason": "sequential", "attempt": 1}
    assert records[2]["transition"] == {"from": "B", "to": "C", "reason": "sequential", "attempt": 1}
    assert records[3]["transition"] == {"from": "C", "to": "B", "reason": "goto", "attempt": 1}
    assert records[4]["transition"] == {"from": "B", "to": "C", "reason": "sequential", "attempt": 1}


def test_legacy_flow_without_transitions_allows_any_goto(tmp_path: Path) -> None:
    # Backward compatibility: no declared transitions -> previous behavior.
    flow = Flow(
        [
            Step("A", lambda value: Goto("C", value)),
            Step("B", lambda value: value),
            Step("C", lambda value: value),
        ]
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    result = runtime.run(flow, 0)

    assert result == 0


def test_flow_validation_rejects_invalid_declarations() -> None:
    def fn(value):
        return value

    with pytest.raises(ValueError, match="unique step names"):
        Flow(
            [Step("A", fn), Step("A", fn)],
            transitions=[Transition("A", "B")],
        )

    with pytest.raises(ValueError, match="not a step"):
        Flow([Step("A", fn)], transitions=[Transition("A", "B")])
