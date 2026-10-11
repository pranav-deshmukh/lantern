"""File-based handoff step for human-operated IDE agents."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.context import ExecutionContext

from .packet import compose_ide_packet


class IdeHandoffError(RuntimeError):
    """Raised when a handoff packet or artifact cannot be processed."""


class IdeHandoffTimeout(IdeHandoffError):
    """Raised when the expected handoff artifact is not produced in time."""


@dataclass(frozen=True)
class IdeHandoffConfig:
    """Configuration for an IDE handoff step.

    ``run_id`` must equal the run_id given to ``Runtime``, and the
    ``step_name`` passed to ``IdeHandoffStep`` must equal the ``Step`` name, so
    resume finds the same directory.
    """

    workspace: str | Path
    run_id: str
    packet_root: str | Path = ".lantern/handoff"
    extra_instructions: str | None = None
    invoke_hint: str | None = None
    poll_seconds: float = 1.0
    timeout_seconds: float | None = None
    partial_write_grace_seconds: float = 2.0


def new_run_id() -> str:
    """Return a short random run id suitable for Runtime and handoff config."""
    return uuid.uuid4().hex[:12]


class IdeHandoffStep:
    """A callable step that writes a packet and waits for ``artifact.json``."""

    def __init__(
        self,
        step_name: str,
        config: IdeHandoffConfig,
        *,
        artifact_waiter: Callable[[Path, str], None] | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self.step_name = step_name
        self.config = config
        self.artifact_waiter = artifact_waiter
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.notify = notify or print

    @property
    def directory(self) -> Path:
        return (
            Path(self.config.workspace)
            / Path(self.config.packet_root)
            / self.config.run_id
            / self.step_name
        )

    @property
    def packet_path(self) -> Path:
        return self.directory / "packet.md"

    @property
    def artifact_path(self) -> Path:
        return self.directory / "artifact.json"

    @property
    def state_path(self) -> Path:
        return self.directory / "current.json"

    def write_packet(self, task: Any, context: ExecutionContext | None = None) -> Path:
        """Write ``packet.md`` for a fresh visit and return its path."""
        original_task, feedback = self._split_task_and_feedback(task)
        packet_id = uuid.uuid4().hex
        self._write_current(packet_id, self._task_hash(task), consumed=False)
        self._write_packet_file(packet_id, original_task, context, feedback)
        return self.packet_path

    def wait_for_artifact(self, packet_id: str) -> dict[str, Any]:
        """Poll until the current packet's JSON object artifact is available."""
        started = self.clock()
        invalid_since: float | None = None

        while True:
            if self.artifact_waiter is not None:
                self.artifact_waiter(self.artifact_path, packet_id)

            if self.artifact_path.exists():
                try:
                    with self.artifact_path.open("r", encoding="utf-8-sig") as artifact:
                        parsed = json.load(artifact)
                    invalid_since = None
                except json.JSONDecodeError as error:
                    if invalid_since is None:
                        invalid_since = self.clock()
                    if self.clock() - invalid_since >= self.config.partial_write_grace_seconds:
                        raise IdeHandoffError(
                            f"Artifact '{self.artifact_path}' is not valid JSON: {error}"
                        ) from error
                else:
                    if not isinstance(parsed, dict):
                        raise IdeHandoffError(
                            f"Artifact '{self.artifact_path}' must contain a JSON object."
                        )
                    if "packet_id" not in parsed:
                        raise IdeHandoffError(
                            f"Artifact '{self.artifact_path}' requires field 'packet_id'."
                        )
                    if parsed["packet_id"] != packet_id:
                        self._check_timeout(started)
                        self.sleep(self.config.poll_seconds)
                        continue
                    self._mark_consumed(packet_id)
                    return parsed

            self._check_timeout(started)
            self.sleep(self.config.poll_seconds)

    def run(self, task: Any, context: ExecutionContext | None = None) -> dict[str, Any]:
        """Write or resume a packet, wait for its artifact, and return the object."""
        original_task, feedback = self._split_task_and_feedback(task)
        task_hash = self._task_hash(task)
        state = self._read_current()

        if (
            state is not None
            and state.get("task_hash") == task_hash
            and state.get("consumed") is False
            and isinstance(state.get("packet_id"), str)
        ):
            packet_id = state["packet_id"]
            if not self.packet_path.exists():
                self._write_packet_file(packet_id, original_task, context, feedback)
        else:
            packet_id = uuid.uuid4().hex
            self._write_current(packet_id, task_hash, consumed=False)
            self._write_packet_file(packet_id, original_task, context, feedback)
            self.notify(
                "Lantern IDE handoff waiting: "
                f"step={self.step_name}; packet={self.packet_path}; "
                f"artifact={self.artifact_path}"
                + (
                    f"; invoke_hint={self.config.invoke_hint}"
                    if self.config.invoke_hint
                    else ""
                )
            )

        artifact = self.wait_for_artifact(packet_id)
        artifact["handoff"] = {
            "step_name": self.step_name,
            "packet_id": packet_id,
            "original_task": original_task,
        }
        return artifact

    def _write_packet_file(
        self,
        packet_id: str,
        original_task: Any,
        context: ExecutionContext | None,
        feedback: str | None,
    ) -> None:
        packet = compose_ide_packet(
            original_task,
            context,
            step_name=self.step_name,
            run_id=self.config.run_id,
            packet_id=packet_id,
            artifact_path=self.artifact_path,
            extra_instructions=self.config.extra_instructions,
            invoke_hint=self.config.invoke_hint,
            feedback=feedback,
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.packet_path.write_text(packet, encoding="utf-8")

    def _read_current(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        try:
            with self.state_path.open("r", encoding="utf-8-sig") as state_file:
                state = json.load(state_file)
        except (OSError, json.JSONDecodeError) as error:
            raise IdeHandoffError(f"Could not read state '{self.state_path}': {error}") from error
        if not isinstance(state, dict):
            raise IdeHandoffError(f"State '{self.state_path}' must contain a JSON object.")
        return state

    def _write_current(self, packet_id: str, task_hash: str, *, consumed: bool) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f"{self.state_path.name}.tmp")
        with temporary.open("w", encoding="utf-8") as state_file:
            json.dump(
                {"packet_id": packet_id, "task_hash": task_hash, "consumed": consumed},
                state_file,
            )
        os.replace(temporary, self.state_path)

    def _mark_consumed(self, packet_id: str) -> None:
        # If the process dies after this point but before Runtime checkpoints,
        # resume starts a new visit and waits instead of returning stale data.
        self._write_current(packet_id, self._read_current()["task_hash"], consumed=True)
        consumed_path = self.directory / f"artifact.consumed-{packet_id}.json"
        last_error: PermissionError | None = None
        for _ in range(4):
            try:
                os.replace(self.artifact_path, consumed_path)
                return
            except PermissionError as error:
                last_error = error
                self.sleep(self.config.poll_seconds)
        raise IdeHandoffError(
            f"Could not consume artifact '{self.artifact_path}': {last_error}"
        ) from last_error

    def _check_timeout(self, started: float) -> None:
        if (
            self.config.timeout_seconds is not None
            and self.clock() - started >= self.config.timeout_seconds
        ):
            raise IdeHandoffTimeout(f"Timed out waiting for artifact '{self.artifact_path}'.")

    @staticmethod
    def _task_hash(task: Any) -> str:
        payload = json.dumps(task, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _split_task_and_feedback(task: Any) -> tuple[Any, str | None]:
        if isinstance(task, dict) and "task" in task and "feedback" in task:
            return task["task"], str(task["feedback"])
        return task, None


def make_ide_handoff_step(
    step_name: str,
    config: IdeHandoffConfig,
    **kwargs: Any,
) -> Callable[..., dict[str, Any]]:
    """Return a bound ``run`` method directly usable as a ``Step`` function."""
    return IdeHandoffStep(step_name, config, **kwargs).run
