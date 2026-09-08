"""Pydantic-backed input and output contracts for steps."""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any, Union, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError


def is_base_model_type(model: Any) -> bool:
    """Return whether ``model`` is a Pydantic ``BaseModel`` subclass."""
    return isinstance(model, type) and issubclass(model, BaseModel)


def is_union_type(model: Any) -> bool:
    """Return whether ``model`` is a typing ``Union`` of multiple types."""
    return get_origin(model) is Union or isinstance(model, types.UnionType)


@dataclass(frozen=True)
class Contract:
    """The Pydantic models that define a step's input and output shapes."""

    input_model: type[BaseModel]
    output_model: Any

    def __post_init__(self) -> None:
        if not is_base_model_type(self.input_model):
            raise TypeError("input_model must be a Pydantic BaseModel subclass.")
        if not is_base_model_type(self.output_model) and not is_union_type(
            self.output_model
        ):
            raise TypeError(
                "output_model must be a Pydantic BaseModel subclass or a Union of them."
            )


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
    model: Any,
    *,
    step_name: str,
    direction: str,
) -> Any:
    """Validate a value and add step context to Pydantic validation errors.

    ``model`` may be a ``BaseModel`` subclass or a ``Union`` (which can include
    dataclasses such as :class:`Goto`); ``TypeAdapter`` validates both.
    """
    try:
        return TypeAdapter(model).validate_python(value)
    except ValidationError as error:
        raise ContractViolationError(step_name, direction, error) from error
