"""Pydantic-backed input and output contracts for steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class Contract:
    """The Pydantic models that define a step's input and output shapes."""

    input_model: type[BaseModel]
    output_model: type[BaseModel]

    def __post_init__(self) -> None:
        for field_name, model in (
            ("input_model", self.input_model),
            ("output_model", self.output_model),
        ):
            if not isinstance(model, type) or not issubclass(model, BaseModel):
                raise TypeError(f"{field_name} must be a Pydantic BaseModel subclass.")


class ContractViolationError(ValueError):
    """Raised when a step value does not satisfy one side of its contract."""

    def __init__(self, step_name: str, direction: str, cause: ValidationError) -> None:
        self.step_name = step_name
        self.direction = direction
        self.cause = cause
        super().__init__(
            f"Contract violation in step '{step_name}' for {direction}: {cause}"
        )


def validate_value(
    value: Any,
    model: type[BaseModel],
    *,
    step_name: str,
    direction: str,
) -> BaseModel:
    """Validate a value and add step context to Pydantic validation errors."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise ContractViolationError(step_name, direction, error) from error
