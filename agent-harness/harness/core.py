"""Core primitives for executing a sequence of plain Python functions."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .contracts import Contract, validate_value
from .governance import PolicyDecision, PolicyEngine, PolicyViolation
from .routing import Goto
from .tracing import Tracer


class GotoTargetError(ValueError):
    """Raised when a step's ``Goto`` names a step that does not exist."""

    def __init__(self, step_name: str, target_step_name: str) -> None:
        self.step_name = step_name
        self.target_step_name = target_step_name
        super().__init__(
            f"Step '{step_name}' returned Goto to unknown step '{target_step_name}'."
        )


class MaxJumpsExceeded(RuntimeError):
    """Raised when a flow makes too many jumps in one run."""

    def __init__(self, max_jumps: int, step_name: str, target_step_name: str) -> None:
        self.max_jumps = max_jumps
        self.step_name = step_name
        self.target_step_name = target_step_name
        super().__init__(
            f"Flow exceeded max_jumps={max_jumps} at step '{step_name}' while "
            f"jumping to '{target_step_name}'; possible infinite loop."
        )


@dataclass(frozen=True)
class Step:
    """A named, single-input/single-output unit of work."""

    name: str
    function: Callable[[Any], Any]
    contract: Contract | None = None
    governed_action: str | None = None
    policy_engine: PolicyEngine | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Step name must be a non-empty string.")
        if not callable(self.function):
            raise TypeError("Step function must be callable.")
        if self.contract is not None and not isinstance(self.contract, Contract):
            raise TypeError("Step contract must be a Contract or None.")
        if (self.governed_action is None) != (self.policy_engine is None):
            raise ValueError("A governed step requires both an action and a policy engine.")
        if self.governed_action is not None and not self.governed_action:
            raise ValueError("A governed action must be a non-empty string.")

    def with_governance(self, action: str, policy_engine: PolicyEngine) -> Step:
        """Return a copy that checks ``action`` against ``policy_engine`` on execution."""
        if not isinstance(policy_engine, PolicyEngine):
            raise TypeError("policy_engine must be a PolicyEngine instance.")
        return replace(self, governed_action=action, policy_engine=policy_engine)

    def execute(self, value: Any) -> Any:
        """Run the wrapped function with the output from the preceding step.

        A function may return a :class:`Goto` marker instead of a plain value.
        ``Goto`` is control flow rather than step output, so it bypasses this
        step's output contract; the target step validates the payload through
        its own input contract.
        """
        self._check_governance()
        if self.contract is None:
            return self.function(value)

        validated_input = validate_value(
            value,
            self.contract.input_model,
            step_name=self.name,
            direction="input",
        )
        output = self.function(validated_input)
        if isinstance(output, Goto):
            return output
        return validate_value(
            output,
            self.contract.output_model,
            step_name=self.name,
            direction="output",
        )

    def _check_governance(self) -> None:
        if self.policy_engine is None or self.governed_action is None:
            return
        if self.policy_engine.check(self.governed_action) is PolicyDecision.REQUIRES_APPROVAL:
            if not self.policy_engine.request_approval(self.governed_action):
                raise PolicyViolation(self.name, self.governed_action)


@dataclass
class _ResumeState:
    """The next step to run after a checkpoint resume, plus run bookkeeping."""

    next_step_name: str | None
    value: Any
    jumps: int
    reached_via_jump: bool
    jumped_from: str | None


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
        trace_path: str | Path | None = None,
        run_id: str | None = None,
        max_jumps: int = 50,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater.")
        if retry_delay < 0:
            raise ValueError("retry_delay must be zero or greater.")
        if max_jumps < 0:
            raise ValueError("max_jumps must be zero or greater.")

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_jumps = max_jumps
        self.checkpoint_path = Path(checkpoint_path)
        self.run_id = run_id or str(uuid.uuid4())
        self.tracer = Tracer(trace_path)

    def run(self, flow: Flow, initial_input: Any) -> Any:
        """Run ``flow`` from its start or resume it from this runtime's checkpoint.

        Execution is not strictly linear: a step that returns :class:`Goto`
        jumps to the named step next, carrying the ``Goto`` payload as that
        step's input.
        """
        if not isinstance(flow, Flow):
            raise TypeError("flow must be a Flow instance.")

        state = self._resume_state(flow, initial_input)
        if state.next_step_name is None:
            return state.value

        next_name = state.next_step_name
        value = state.value
        jumps = state.jumps
        reached_via_jump = state.reached_via_jump
        jumped_from = state.jumped_from

        while True:
            index = self._step_index(flow, next_name)
            step = flow.steps[index]

            value = self._execute_with_retries(
                step,
                value,
                reached_via_jump=reached_via_jump,
                jumped_from=jumped_from,
            )

            if isinstance(value, Goto):
                jumps += 1
                if jumps > self.max_jumps:
                    raise MaxJumpsExceeded(
                        self.max_jumps, step.name, value.target_step_name
                    )

                target_index = self._step_index_or_none(flow, value.target_step_name)
                if target_index is None:
                    raise GotoTargetError(step.name, value.target_step_name)

                # Persist the completed step *with its Goto output* so a
                # resume knows the next step is the jump target, not the
                # next step in list order.
                self._write_checkpoint(
                    index, step.name, value, jumps=jumps, output_is_goto=True
                )

                next_name = value.target_step_name
                value = value.payload
                reached_via_jump = True
                jumped_from = step.name
            else:
                self._write_checkpoint(index, step.name, value, jumps=jumps)

                if index + 1 >= len(flow.steps):
                    return value

                next_name = flow.steps[index + 1].name
                reached_via_jump = False
                jumped_from = None

    def _execute_with_retries(
        self,
        step: Step,
        value: Any,
        *,
        reached_via_jump: bool = False,
        jumped_from: str | None = None,
    ) -> Any:
        """Execute one step, allowing the initial attempt plus max_retries retries."""
        for attempt in range(1, self.max_retries + 2):
            try:
                return self.tracer.execute(
                    run_id=self.run_id,
                    step_name=step.name,
                    input_value=value,
                    operation=lambda: step.execute(value),
                    reached_via_jump=reached_via_jump,
                    jumped_from=jumped_from,
                )
            except PolicyViolation:
                # A denied approval is terminal; retrying cannot change it.
                raise
            except Exception as error:
                if attempt == self.max_retries + 1:
                    raise StepExecutionError(step.name, attempt, error) from error
                time.sleep(self.retry_delay)

        # The loop always returns or raises; this is only for type checkers.
        raise AssertionError("unreachable")

    def _resume_state(self, flow: Flow, initial_input: Any) -> _ResumeState:
        """Return the next step, its input, and jump bookkeeping.

        For a fresh run this is the first step with ``initial_input``. For a
        matching checkpoint it follows the *actual* execution path: the next
        step in the list for a plain output, or the ``Goto`` target when the
        checkpointed output was a jump.
        """
        if not self.checkpoint_path.exists():
            return self._fresh_state(flow, initial_input)

        checkpoint = self._read_checkpoint()
        if checkpoint.get("run_id") != self.run_id:
            return self._fresh_state(flow, initial_input)

        step_index = checkpoint.get("step_index")
        if not isinstance(step_index, int) or step_index < 0:
            raise ValueError("Checkpoint has an invalid step_index.")
        if step_index >= len(flow.steps):
            raise ValueError("Checkpoint step_index is outside the supplied flow.")

        step_name = checkpoint.get("step_name")
        if step_name != flow.steps[step_index].name:
            raise ValueError("Checkpoint step name does not match the supplied flow.")
        if "output" not in checkpoint:
            raise ValueError("Checkpoint is missing the previous step output.")

        jumps = checkpoint.get("jumps", 0)
        if not isinstance(jumps, int) or jumps < 0:
            raise ValueError("Checkpoint has an invalid jumps count.")

        completed_step = flow.steps[step_index]
        output = checkpoint["output"]
        output_is_goto = checkpoint.get("output_is_goto", False)

        if output_is_goto:
            goto = Goto(
                target_step_name=output["target_step_name"],
                payload=output["payload"],
            )
            target_index = self._step_index_or_none(flow, goto.target_step_name)
            if target_index is None:
                raise GotoTargetError(step_name, goto.target_step_name)
            return _ResumeState(
                next_step_name=goto.target_step_name,
                value=goto.payload,
                jumps=jumps,
                reached_via_jump=True,
                jumped_from=step_name,
            )

        if completed_step.contract is not None:
            # Checkpoints store models as JSON objects. Rebuild the same Pydantic
            # output object that the next step would receive during a live run.
            output = validate_value(
                output,
                completed_step.contract.output_model,
                step_name=step_name,
                direction="output",
            )

        if step_index + 1 >= len(flow.steps):
            return _ResumeState(None, output, jumps, False, None)

        return _ResumeState(
            next_step_name=flow.steps[step_index + 1].name,
            value=output,
            jumps=jumps,
            reached_via_jump=False,
            jumped_from=None,
        )

    @staticmethod
    def _fresh_state(flow: Flow, initial_input: Any) -> _ResumeState:
        if not flow.steps:
            return _ResumeState(None, initial_input, 0, False, None)
        return _ResumeState(flow.steps[0].name, initial_input, 0, False, None)

    @staticmethod
    def _step_index_or_none(flow: Flow, step_name: str) -> int | None:
        # Traces carry no step position, and a flow is allowed to reuse a step
        # name, so a name lookup resolves to the first matching step.
        for index, step in enumerate(flow.steps):
            if step.name == step_name:
                return index
        return None

    @classmethod
    def _step_index(cls, flow: Flow, step_name: str) -> int:
        index = cls._step_index_or_none(flow, step_name)
        if index is None:
            raise ValueError(f"Unknown step '{step_name}'.")
        return index

    def _read_checkpoint(self) -> dict[str, Any]:
        try:
            with self.checkpoint_path.open("r", encoding="utf-8") as checkpoint_file:
                data = json.load(checkpoint_file)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Could not read checkpoint '{self.checkpoint_path}': {error}") from error

        if not isinstance(data, dict):
            raise ValueError("Checkpoint must contain a JSON object.")
        return data

    def _write_checkpoint(
        self,
        step_index: int,
        step_name: str,
        output: Any,
        *,
        jumps: int = 0,
        output_is_goto: bool = False,
    ) -> None:
        """Atomically replace the checkpoint so completed work is recoverable.

        The completed step is recorded by name (not just list index) because a
        ``Goto`` makes execution non-linear. ``output_is_goto`` and ``jumps``
        are persisted only when they are meaningful so ordinary linear
        checkpoints keep the historical four-key shape.
        """
        checkpoint: dict[str, Any] = {
            "run_id": self.run_id,
            "step_index": step_index,
            "step_name": step_name,
            "output": output,
        }
        if output_is_goto:
            checkpoint["output_is_goto"] = True
        if jumps:
            checkpoint["jumps"] = jumps

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
        """Serialize Pydantic outputs and Goto markers for JSON checkpoints."""
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, Goto):
            return {
                "target_step_name": value.target_step_name,
                "payload": value.payload,
            }
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
