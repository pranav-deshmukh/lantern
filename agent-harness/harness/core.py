"""Core primitives for executing a sequence of plain Python functions."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .contracts import Contract, validate_value


@dataclass(frozen=True)
class Step:
    """A named, single-input/single-output unit of work."""

    name: str
    function: Callable[[Any], Any]
    contract: Contract | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Step name must be a non-empty string.")
        if not callable(self.function):
            raise TypeError("Step function must be callable.")
        if self.contract is not None and not isinstance(self.contract, Contract):
            raise TypeError("Step contract must be a Contract or None.")

    def execute(self, value: Any) -> Any:
        """Run the wrapped function with the output from the preceding step."""
        if self.contract is None:
            return self.function(value)

        validated_input = validate_value(
            value,
            self.contract.input_model,
            step_name=self.name,
            direction="input",
        )
        output = self.function(validated_input)
        return validate_value(
            output,
            self.contract.output_model,
            step_name=self.name,
            direction="output",
        )


class Flow:
    """An ordered collection of steps."""

    def __init__(self, steps: Iterable[Step]) -> None:
        self.steps = list(steps)
        if not all(isinstance(step, Step) for step in self.steps):
            raise TypeError("A Flow may only contain Step objects.")


class StepExecutionError(RuntimeError):
    """Raised when a step cannot complete within the configured retry limit."""

    def __init__(self, step_name: str, attempts: int, cause: Exception) -> None:
        self.step_name = step_name
        self.attempts = attempts
        self.cause = cause
        message = (
            f"Step '{step_name}' failed after {attempts} attempt(s): "
            f"{type(cause).__name__}: {cause}"
        )
        super().__init__(message)


class Runtime:
    """Execute flows with retries and a JSON checkpoint after each completed step.

    A runtime owns a ``run_id``. Reusing that ID with the same checkpoint path
    resumes the saved output at the next step.
    """

    def __init__(
        self,
        *,
        max_retries: int = 2,
        retry_delay: float = 0.05,
        checkpoint_path: str | Path = ".harness_checkpoint.json",
        run_id: str | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater.")
        if retry_delay < 0:
            raise ValueError("retry_delay must be zero or greater.")

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.checkpoint_path = Path(checkpoint_path)
        self.run_id = run_id or str(uuid.uuid4())

    def run(self, flow: Flow, initial_input: Any) -> Any:
        """Run ``flow`` from its start or resume it from this runtime's checkpoint."""
        if not isinstance(flow, Flow):
            raise TypeError("flow must be a Flow instance.")

        next_index, value = self._resume_state(flow, initial_input)

        for index in range(next_index, len(flow.steps)):
            step = flow.steps[index]
            value = self._execute_with_retries(step, value)
            self._write_checkpoint(index, step.name, value)

        return value

    def _execute_with_retries(self, step: Step, value: Any) -> Any:
        """Execute one step, allowing the initial attempt plus max_retries retries."""
        for attempt in range(1, self.max_retries + 2):
            try:
                return step.execute(value)
            except Exception as error:
                if attempt == self.max_retries + 1:
                    raise StepExecutionError(step.name, attempt, error) from error
                time.sleep(self.retry_delay)

        # The loop always returns or raises; this is only for type checkers.
        raise AssertionError("unreachable")

    def _resume_state(self, flow: Flow, initial_input: Any) -> tuple[int, Any]:
        """Return the next step index and its input from a matching checkpoint."""
        if not self.checkpoint_path.exists():
            return 0, initial_input

        checkpoint = self._read_checkpoint()
        if checkpoint.get("run_id") != self.run_id:
            return 0, initial_input

        step_index = checkpoint.get("step_index")
        if not isinstance(step_index, int) or step_index < 0:
            raise ValueError("Checkpoint has an invalid step_index.")
        if step_index >= len(flow.steps):
            raise ValueError("Checkpoint step_index is outside the supplied flow.")

        # A name check prevents silently resuming a differently ordered flow.
        if checkpoint.get("step_name") != flow.steps[step_index].name:
            raise ValueError("Checkpoint step name does not match the supplied flow.")
        if "output" not in checkpoint:
            raise ValueError("Checkpoint is missing the previous step output.")

        output = checkpoint["output"]
        completed_step = flow.steps[step_index]
        if completed_step.contract is not None:
            # Checkpoints store models as JSON objects. Rebuild the same Pydantic
            # output object that the next step would receive during a live run.
            output = completed_step.contract.output_model.model_validate(output)

        return step_index + 1, output

    def _read_checkpoint(self) -> dict[str, Any]:
        try:
            with self.checkpoint_path.open("r", encoding="utf-8") as checkpoint_file:
                data = json.load(checkpoint_file)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Could not read checkpoint '{self.checkpoint_path}': {error}") from error

        if not isinstance(data, dict):
            raise ValueError("Checkpoint must contain a JSON object.")
        return data

    def _write_checkpoint(self, step_index: int, step_name: str, output: Any) -> None:
        """Atomically replace the checkpoint so completed work is recoverable."""
        checkpoint = {
            "run_id": self.run_id,
            "step_index": step_index,
            "step_name": step_name,
            "output": output,
        }
        temporary_path = self.checkpoint_path.with_name(
            f"{self.checkpoint_path.name}.tmp"
        )
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_path.open("w", encoding="utf-8") as checkpoint_file:
                json.dump(checkpoint, checkpoint_file, default=self._json_default)
            temporary_path.replace(self.checkpoint_path)
        except (OSError, TypeError) as error:
            raise RuntimeError(
                f"Could not write checkpoint '{self.checkpoint_path}': {error}"
            ) from error

    @staticmethod
    def _json_default(value: Any) -> Any:
        """Serialize Pydantic outputs while retaining ordinary JSON behavior."""
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
