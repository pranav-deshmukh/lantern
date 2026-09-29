"""Core primitives for executing a sequence of plain Python functions."""

from __future__ import annotations

import inspect
import json
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .context import ExecutionContext, load_context_files
from .contracts import Contract, ContractViolationError, validate_value
from .events import Run
from .governance import PolicyDecision, PolicyEngine, PolicyViolation
from .routing import Goto
from .tracing import Tracer


def _accepts_context(function: Callable[..., Any]) -> bool:
    """Return whether ``function`` opts into receiving execution context.

    Opt-in is explicit and signature-based: the callable must declare a
    parameter named ``context``. Simple functions and BYO agents therefore
    remain completely unaware of Lantern.
    """
    try:
        return "context" in inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False


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
class Transition:
    """An explicit legal transition between two named steps in a flow."""

    source: str
    target: str


class IllegalTransitionError(RuntimeError):
    """Raised when a step attempts a transition the flow does not declare."""

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target
        super().__init__(
            f"Illegal transition from '{source}' to '{target}': "
            "the flow does not declare this transition."
        )


@dataclass(frozen=True)
class TransitionRecord:
    """A single observed movement in a run's execution history."""

    source: str | None
    target: str | None
    reason: str


@dataclass
class ExecutionState:
    """Authoritative execution state owned by the runtime.

    The agent never writes this. ``transition_history`` records every legal
    movement so the run can be reported and audited after the fact.
    """

    flow: Flow
    run_id: str
    status: str = "pending"
    current_step: str | None = None
    previous_step: str | None = None
    transition_history: list[TransitionRecord] = field(default_factory=list)


@dataclass(frozen=True)
class Step:
    """A named, single-input/single-output unit of work."""

    name: str
    function: Callable[[Any], Any]
    contract: Contract | None = None
    governed_action: str | None = None
    policy_engine: PolicyEngine | None = None
    rules_files: list[str] | None = None
    skills_files: list[str] | None = None

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
        for field_name in ("rules_files", "skills_files"):
            paths = getattr(self, field_name)
            if paths is not None and (
                not isinstance(paths, list)
                or not all(isinstance(path, str) for path in paths)
            ):
                raise TypeError(
                    f"{field_name} must be a list of path strings or None."
                )

    def with_governance(self, action: str, policy_engine: PolicyEngine) -> Step:
        """Return a copy that checks ``action`` against ``policy_engine`` on execution."""
        if not isinstance(policy_engine, PolicyEngine):
            raise TypeError("policy_engine must be a PolicyEngine instance.")
        return replace(self, governed_action=action, policy_engine=policy_engine)

    def execute(
        self,
        value: Any,
        *,
        _context: ExecutionContext | None = None,
        _event_emitter: Callable[[str, str | None, int | None, dict[str, Any]], None]
        | None = None,
    ) -> Any:
        """Run the wrapped function.

        The user's input is passed through unchanged. A function that declares
        a ``context`` parameter opts into receiving the execution context as a
        keyword argument (``function(value, context=context)``); otherwise it
        is called with ``value`` only, exactly as before.
        """
        self._check_governance(_event_emitter)

        if _context is None:
            _context = self.build_context()

        wants_context = _accepts_context(self.function)

        if self.contract is None:
            if wants_context:
                return self.function(value, context=_context)
            return self.function(value)

        validated_input = validate_value(
            value,
            self.contract.input_model,
            step_name=self.name,
            direction="input",
        )
        if wants_context:
            output = self.function(validated_input, context=_context)
        else:
            output = self.function(validated_input)
        if isinstance(output, Goto):
            return output
        return validate_value(
            output,
            self.contract.output_model,
            step_name=self.name,
            direction="output",
        )

    def build_context(self) -> ExecutionContext:
        """Build the execution context for this step.

        Rules and skills are loaded separately so the harness (and the trace)
        can distinguish them, while memory/experience remain available as
        extension points without changing the input contract.
        """
        return ExecutionContext(
            rules=load_context_files(self.rules_files) if self.rules_files else None,
            skills=load_context_files(self.skills_files) if self.skills_files else None,
        )

    def _check_governance(
        self,
        event_emitter: Callable[[str, str | None, int | None, dict[str, Any]], None]
        | None = None,
    ) -> None:
        if self.policy_engine is None or self.governed_action is None:
            return
        if self.policy_engine.check(self.governed_action) is PolicyDecision.REQUIRES_APPROVAL:
            if event_emitter is not None:
                event_emitter(
                    "human_approval_requested",
                    self.name,
                    None,
                    {"action": self.governed_action},
                )
            approved = self.policy_engine.request_approval(self.governed_action)
            if event_emitter is not None:
                event_emitter(
                    "human_approval_received",
                    self.name,
                    None,
                    {"action": self.governed_action, "approved": bool(approved)},
                )
            if not approved:
                raise PolicyViolation(self.name, self.governed_action)


@dataclass
class _ResumeState:
    """The next step to run after a checkpoint resume, plus run bookkeeping."""

    next_index: int | None
    value: Any
    jumps: int
    reached_via_jump: bool
    jumped_from: str | None


class Flow:
    """An ordered collection of steps with optional explicit transitions.

    The step list defines the primary linear path (each step's next step is
    the following one in the list). ``transitions`` declares additional legal
    edges such as recovery loops or branches. When ``transitions`` is empty the
    flow keeps the legacy behavior (any named ``Goto`` is allowed) so existing
    callers remain unchanged.
    """

    def __init__(
        self,
        steps: Iterable[Step],
        *,
        transitions: Iterable[Transition | tuple[str, str]] = (),
    ) -> None:
        self.steps = list(steps)
        if not all(isinstance(step, Step) for step in self.steps):
            raise TypeError("A Flow may only contain Step objects.")

        self.transitions = [self._coerce_transition(item) for item in transitions]
        self._transition_set = {(t.source, t.target) for t in self.transitions}
        if self.transitions:
            self._validate_transitions()

    @staticmethod
    def _coerce_transition(item: Transition | tuple[str, str]) -> Transition:
        if isinstance(item, Transition):
            return item
        if isinstance(item, tuple) and len(item) == 2 and all(
            isinstance(part, str) for part in item
        ):
            return Transition(item[0], item[1])
        raise TypeError(
            "transitions must be Transition instances or (source, target) pairs."
        )

    def _validate_transitions(self) -> None:
        """Reject obviously invalid declared workflows before execution."""
        if not self.steps:
            raise ValueError("A flow with explicit transitions must have at least one step.")

        names = [step.name for step in self.steps]
        if len(set(names)) != len(names):
            raise ValueError(
                "A flow with explicit transitions requires unique step names."
            )

        for transition in self.transitions:
            if transition.source not in names:
                raise ValueError(
                    f"Transition source '{transition.source}' is not a step in the flow."
                )
            if transition.target not in names:
                raise ValueError(
                    f"Transition target '{transition.target}' is not a step in the flow."
                )

    def is_transition_allowed(self, source: str, target: str) -> bool:
        """Return whether moving from ``source`` to ``target`` is legal.

        When explicit transitions are declared the declared graph is fully
        authoritative: a transition is legal only if it is explicitly listed,
        including the ordinary next-in-list step. When no transitions are
        declared (legacy mode) every named target is allowed.
        """
        if not self.transitions:
            return True
        return (source, target) in self._transition_set

    def _index_of(self, name: str) -> int | None:
        for index, step in enumerate(self.steps):
            if step.name == name:
                return index
        return None


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
        self.last_run: Run | None = None

    def run(self, flow: Flow, initial_input: Any) -> Any:
        """Run ``flow`` and return its final value.

        The final value is returned for backwards compatibility. The complete
        execution record (status, result, error, timing, and ordered events)
        is available afterwards as ``runtime.last_run``.
        """
        if not isinstance(flow, Flow):
            raise TypeError("flow must be a Flow instance.")

        run = Run(
            run_id=self.run_id,
            flow=flow,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.last_run = run
        self.state = ExecutionState(flow=flow, run_id=self.run_id, status="running")
        run.emit("run_started")

        try:
            result = self._run_flow(flow, initial_input, run)
        except IllegalTransitionError as error:
            run.status = "rejected"
            run.finished_at = datetime.now(timezone.utc).isoformat()
            run.error = error
            run.emit(
                "run_failed",
                data={"reason": "illegal_transition", "error": str(error)},
            )
            self.state.status = "rejected"
            raise
        except BaseException as error:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc).isoformat()
            run.error = error
            run.emit(
                "run_failed",
                data={"error": f"{type(error).__name__}: {error}"},
            )
            if self.state.status == "running":
                self.state.status = "failed"
            raise

        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        run.result = result
        run.emit("run_completed")
        self.state.status = "completed"
        return result

    def _run_flow(self, flow: Flow, initial_input: Any, run: Run) -> Any:
        resume = self._resume_state(flow, initial_input)
        if resume.next_index is None:
            self.state.status = "completed"
            return resume.value

        index = resume.next_index
        value = resume.value
        jumps = resume.jumps

        if resume.reached_via_jump:
            previous_step = resume.jumped_from
            reason = "goto"
        elif index > 0:
            previous_step = flow.steps[index - 1].name
            reason = "resume"
        else:
            previous_step = None
            reason = "start"

        self.state.current_step = flow.steps[index].name
        self.state.previous_step = previous_step
        run.emit(
            "transition",
            step=flow.steps[index].name,
            attempt=1,
            data={"source": previous_step, "target": flow.steps[index].name, "reason": reason},
        )

        while True:
            step = flow.steps[index]

            value, completed_attempt = self._execute_with_retries(
                step,
                value,
                run=run,
                previous_step=previous_step,
                reason=reason,
            )

            if isinstance(value, Goto):
                target = value.target_step_name
                if not flow.is_transition_allowed(step.name, target):
                    self.state.status = "rejected"
                    self.state.transition_history.append(
                        TransitionRecord(step.name, target, "rejected")
                    )
                    run.emit(
                        "transition",
                        step=step.name,
                        attempt=completed_attempt,
                        data={"source": step.name, "target": target, "reason": "rejected"},
                    )
                    raise IllegalTransitionError(step.name, target)

                jumps += 1
                if jumps > self.max_jumps:
                    raise MaxJumpsExceeded(
                        self.max_jumps, step.name, target
                    )

                target_index = self._step_index_or_none(flow, target)
                if target_index is None:
                    raise GotoTargetError(step.name, target)

                # Persist the completed step *with its Goto output* so a
                # resume knows the next step is the jump target, not the
                # next step in list order.
                self._write_checkpoint(
                    index, step.name, value, jumps=jumps, output_is_goto=True
                )
                self.state.transition_history.append(
                    TransitionRecord(step.name, target, "goto")
                )
                run.emit(
                    "goto",
                    step=step.name,
                    attempt=completed_attempt,
                    data={"target": target},
                )
                run.emit(
                    "transition",
                    step=target,
                    attempt=1,
                    data={"source": step.name, "target": target, "reason": "goto"},
                )

                previous_step = step.name
                reason = "goto"
                index = target_index
                value = value.payload
            else:
                if index + 1 < len(flow.steps):
                    next_name = flow.steps[index + 1].name
                    if not flow.is_transition_allowed(step.name, next_name):
                        self.state.status = "rejected"
                        self.state.transition_history.append(
                            TransitionRecord(step.name, next_name, "rejected")
                        )
                        run.emit(
                            "transition",
                            step=step.name,
                            attempt=completed_attempt,
                            data={
                                "source": step.name,
                                "target": next_name,
                                "reason": "rejected",
                            },
                        )
                        raise IllegalTransitionError(step.name, next_name)

                self._write_checkpoint(index, step.name, value, jumps=jumps)

                if index + 1 >= len(flow.steps):
                    self.state.transition_history.append(
                        TransitionRecord(step.name, None, "complete")
                    )
                    self.state.current_step = step.name
                    self.state.previous_step = previous_step
                    self.state.status = "completed"
                    return value

                self.state.transition_history.append(
                    TransitionRecord(
                        step.name, flow.steps[index + 1].name, "sequential"
                    )
                )
                next_name = flow.steps[index + 1].name
                run.emit(
                    "transition",
                    step=next_name,
                    attempt=1,
                    data={"source": step.name, "target": next_name, "reason": "sequential"},
                )
                previous_step = step.name
                reason = "sequential"
                index = index + 1

            self.state.current_step = flow.steps[index].name
            self.state.previous_step = previous_step

    def _execute_with_retries(
        self,
        step: Step,
        value: Any,
        *,
        run: Run,
        previous_step: str | None = None,
        reason: str = "start",
    ) -> tuple[Any, int]:
        """Execute one step, allowing the initial attempt plus max_retries retries."""
        context = step.build_context()
        context_files = context.audit_entries()
        reached_via_jump = reason == "goto"
        jumped_from = previous_step if reached_via_jump else None

        for attempt in range(1, self.max_retries + 2):
            transition = {
                "from": previous_step,
                "to": step.name,
                "reason": reason,
                "attempt": attempt,
            }
            started_at = time.perf_counter()
            run.emit("step_started", step=step.name, attempt=attempt)
            try:
                result = self.tracer.execute(
                    run_id=self.run_id,
                    step_name=step.name,
                    input_value=value,
                    operation=lambda: step.execute(
                        value,
                        _context=context,
                        _event_emitter=lambda event_type, event_step, event_attempt, data: run.emit(
                            event_type,
                            step=event_step,
                            attempt=event_attempt or attempt,
                            data=data,
                        ),
                    ),
                    reached_via_jump=reached_via_jump,
                    jumped_from=jumped_from,
                    context_files=context_files,
                    transition=transition,
                )
                run.emit(
                    "step_completed",
                    step=step.name,
                    attempt=attempt,
                    data={"duration_ms": self._duration_ms(started_at)},
                )
                return result, attempt
            except PolicyViolation:
                # A denied approval is terminal; retrying cannot change it.
                run.emit(
                    "step_failed",
                    step=step.name,
                    attempt=attempt,
                    data={
                        "reason": "policy_violation",
                        "error": "PolicyViolation",
                        "duration_ms": self._duration_ms(started_at),
                    },
                )
                raise
            except Exception as error:
                duration_ms = self._duration_ms(started_at)
                if isinstance(error, ContractViolationError):
                    run.emit(
                        "contract_failed",
                        step=step.name,
                        attempt=attempt,
                        data={"direction": error.direction, "error": str(error)},
                    )
                    reason = "contract_failure"
                else:
                    reason = "exception"
                run.emit(
                    "step_failed",
                    step=step.name,
                    attempt=attempt,
                    data={
                        "reason": reason,
                        "error": f"{type(error).__name__}: {error}",
                        "duration_ms": duration_ms,
                    },
                )
                if attempt == self.max_retries + 1:
                    raise StepExecutionError(step.name, attempt, error) from error
                run.emit(
                    "retry_started",
                    step=step.name,
                    attempt=attempt + 1,
                    data={"previous_attempt": attempt, "reason": reason},
                )
                time.sleep(self.retry_delay)

        # The loop always returns or raises; this is only for type checkers.
        raise AssertionError("unreachable")

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 3)

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
                target_index, goto.payload, jumps, True, step_name
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

        return _ResumeState(step_index + 1, output, jumps, False, None)

    @staticmethod
    def _fresh_state(flow: Flow, initial_input: Any) -> _ResumeState:
        if not flow.steps:
            return _ResumeState(None, initial_input, 0, False, None)
        return _ResumeState(0, initial_input, 0, False, None)

    @staticmethod
    def _step_index_or_none(flow: Flow, step_name: str) -> int | None:
        # Traces carry no step position, and a flow is allowed to reuse a step
        # name, so a name lookup resolves to the first matching step.
        for index, step in enumerate(flow.steps):
            if step.name == step_name:
                return index
        return None

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
