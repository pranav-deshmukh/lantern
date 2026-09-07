"""Tests for Pydantic-backed step contracts."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pydantic import BaseModel

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import Contract, ContractViolationError, Flow, Runtime, Step


class NumberInput(BaseModel):
    value: int


class NumberOutput(BaseModel):
    result: int


def test_step_with_valid_contract_returns_validated_output() -> None:
    step = Step(
        "increment",
        lambda data: {"result": data.value + 1},
        contract=Contract(NumberInput, NumberOutput),
    )

    result = step.execute({"value": 4})

    assert result == NumberOutput(result=5)


def test_invalid_output_raises_contract_violation_with_step_name() -> None:
    step = Step(
        "produce-number",
        lambda _: {"wrong_field": "not a number"},
        contract=Contract(NumberInput, NumberOutput),
    )

    with pytest.raises(ContractViolationError) as error_info:
        step.execute({"value": 4})

    message = str(error_info.value)
    assert "produce-number" in message
    assert "output" in message


def test_invalid_input_raises_contract_violation_with_step_name() -> None:
    step = Step(
        "consume-number",
        lambda data: {"result": data.value + 1},
        contract=Contract(NumberInput, NumberOutput),
    )

    with pytest.raises(ContractViolationError) as error_info:
        step.execute({"value": "not an integer"})

    message = str(error_info.value)
    assert "consume-number" in message
    assert "input" in message


def test_compatible_contracts_run_end_to_end_in_a_flow(tmp_path: Path) -> None:
    class FirstOutput(BaseModel):
        value: int

    class SecondOutput(BaseModel):
        message: str

    first_step = Step(
        "create-value",
        lambda data: {"value": data.value * 2},
        contract=Contract(NumberInput, FirstOutput),
    )
    second_step = Step(
        "format-value",
        lambda data: {"message": f"value={data.value}"},
        contract=Contract(FirstOutput, SecondOutput),
    )
    runtime = Runtime(
        checkpoint_path=tmp_path / "checkpoint.json", run_id="contract-flow", retry_delay=0
    )

    result = runtime.run(Flow([first_step, second_step]), {"value": 3})

    assert result == SecondOutput(message="value=6")
