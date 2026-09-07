"""Tests for the declarative YAML flow loader."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (
    ContractViolationError,
    Flow,
    PolicyViolation,
    Runtime,
    load_flow,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"

HELPER_MODULE_SOURCE = '''\
"""Helpers for the flow loader tests."""

from pydantic import BaseModel


class DoubleInput(BaseModel):
    value: int


class DoubleOutput(BaseModel):
    result: int


def double(data: DoubleInput) -> dict:
    return {"result": data.value * 2}


def identity(value):
    return value
'''


@pytest.fixture
def helper_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a real importable module for the contract/policy/missing tests."""
    module_path = tmp_path / "flow_spec_helpers.py"
    module_path.write_text(HELPER_MODULE_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return module_path


def test_migration_flow_yaml_runs_to_expected_result(tmp_path: Path) -> None:
    flow = load_flow(str(EXAMPLES_DIR / "migration_flow.yaml"))
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)

    result = runtime.run(flow, {})

    assert isinstance(flow, Flow)
    assert [step.name for step in flow.steps] == [
        "analyze",
        "plan",
        "migrate",
        "verify",
    ]
    assert result == {
        "table": "users",
        "compatibility": "ok",
        "risk": "low",
        "steps": ["create_index", "backfill", "validate"],
        "migrated_rows": 0,
        "status": "verified",
        "verified_rows": 0,
    }


def test_pr_review_flow_yaml_runs_to_expected_result(tmp_path: Path) -> None:
    flow = load_flow(str(EXAMPLES_DIR / "pr_review_flow.yaml"))
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", retry_delay=0)

    result = runtime.run(flow, {})

    assert [step.name for step in flow.steps] == ["read_diff", "review", "comment"]
    assert result == {
        "summary": "Reviewed 2 file(s) and posted 2 comment(s).",
    }


def test_missing_function_reports_the_bad_dotted_path(helper_module: Path) -> None:
    yaml_path = helper_module.parent / "bad_function.yaml"
    yaml_path.write_text(
        """\
steps:
  - name: broken
    function: flow_spec_helpers.nonexistent_function
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error_info:
        load_flow(str(yaml_path))

    message = str(error_info.value)
    assert "flow_spec_helpers.nonexistent_function" in message
    assert "broken" in message
    assert str(yaml_path) in message


def test_contract_section_attaches_a_working_contract(helper_module: Path) -> None:
    yaml_path = helper_module.parent / "contract_flow.yaml"
    yaml_path.write_text(
        """\
steps:
  - name: double
    function: flow_spec_helpers.double
    input_model: flow_spec_helpers.DoubleInput
    output_model: flow_spec_helpers.DoubleOutput
""",
        encoding="utf-8",
    )

    flow = load_flow(str(yaml_path))
    step = flow.steps[0]

    assert step.contract is not None
    assert step.contract.input_model.__name__ == "DoubleInput"
    assert step.contract.output_model.__name__ == "DoubleOutput"

    result = step.execute({"value": 3})
    assert result.model_dump() == {"result": 6}

    with pytest.raises(ContractViolationError, match="double"):
        step.execute({"value": "not an integer"})


def test_policies_section_attaches_governance_to_a_step(helper_module: Path) -> None:
    yaml_path = helper_module.parent / "governed_flow.yaml"
    yaml_path.write_text(
        """\
policies:
  - action_pattern: delete_*
    risk: high
    requires_approval: true
steps:
  - name: delete
    function: flow_spec_helpers.identity
    governed_action: delete_repo
""",
        encoding="utf-8",
    )

    flow = load_flow(
        str(yaml_path),
        approval_callback=lambda _action, _risk: False,
    )
    step = flow.steps[0]

    assert step.governed_action == "delete_repo"
    assert step.policy_engine is not None

    with pytest.raises(PolicyViolation, match="delete_repo"):
        step.execute("anything")
