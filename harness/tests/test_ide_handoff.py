"""Tests for the opt-in IDE handoff package."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (  # noqa: E402
    Flow,
    GotoTargetError,
    IllegalTransitionError,
    Runtime,
    Step,
    Transition,
)
from harness.context import ExecutionContext, ContextBundle  # noqa: E402
from harness.ide_handoff import (  # noqa: E402
    HandoffDecisionError,
    IdeHandoffConfig,
    IdeHandoffError,
    IdeHandoffStep,
    IdeHandoffTimeout,
    PatternRule,
    compose_ide_packet,
    goto_from_handoff,
    make_ide_handoff_step,
    make_orchestrator_step,
    make_pattern_check_step,
)
from harness.routing import Goto  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.01)


def _config(tmp_path: Path, run_id: str = "run") -> IdeHandoffConfig:
    return IdeHandoffConfig(
        workspace=tmp_path,
        run_id=run_id,
        poll_seconds=0.01,
        timeout_seconds=0.1,
        partial_write_grace_seconds=0.03,
    )


def _write_artifact(path: Path, packet_id: str, **extra: Any) -> None:
    payload = {"packet_id": packet_id, **extra}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _packet_id(step: IdeHandoffStep) -> str:
    return json.loads(step.state_path.read_text(encoding="utf-8"))["packet_id"]


def test_import_harness_does_not_import_ide_handoff() -> None:
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); "
        "import harness; "
        "print('harness.ide_handoff' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_ide_handoff_imports_are_stdlib_or_harness() -> None:
    package = Path(__file__).resolve().parents[1] / "harness" / "ide_handoff"
    allowed = set(sys.stdlib_module_names) | {"harness"}
    for module_path in package.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in allowed
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert (node.module or "").split(".")[0] in allowed


def test_hybrid_flow_through_runtime(tmp_path: Path) -> None:
    def first(value: dict[str, Any]) -> dict[str, Any]:
        return {"task": value["task"].upper()}

    def waiter(path: Path, packet_id: str) -> None:
        if not path.exists():
            _write_artifact(path, packet_id, changed_files=[])

    handoff = make_ide_handoff_step(
        "ide", _config(tmp_path), artifact_waiter=waiter, sleep=lambda _: None, notify=lambda _: None
    )
    check = make_pattern_check_step([], base_dir=tmp_path, retry_target="ide")
    flow = Flow([Step("first", first), Step("ide", handoff), Step("check", check)])

    result = Runtime(checkpoint_path=tmp_path / "cp.json", run_id="run", retry_delay=0).run(
        flow, {"task": "hello"}
    )

    assert result["handoff"]["original_task"] == {"task": "HELLO"}


def test_compose_packet_sections() -> None:
    context = ExecutionContext(
        rules=ContextBundle([("rules.md", "RULES", "abc")]),
        skills=ContextBundle([("skills.md", "SKILLS", "def")]),
    )

    packet = compose_ide_packet(
        {"x": 1},
        context,
        step_name="ide",
        run_id="run",
        packet_id="packet",
        artifact_path="artifact.json",
        invoke_hint="@do-it",
        feedback="fix this",
    )
    no_context = compose_ide_packet(
        "plain task",
        None,
        step_name="ide",
        run_id="run",
        packet_id="packet",
        artifact_path="artifact.json",
    )

    assert "Step name: ide" in packet
    assert "Run id: run" in packet
    assert "Packet id: packet" in packet
    assert "@do-it" in packet
    assert "artifact.json" in packet
    assert '"x": 1' in packet
    assert "RULES" in packet and "SKILLS" in packet
    assert "Fix these before finishing" in packet and "fix this" in packet
    assert "Bundled Rules and Skills" not in no_context
    assert "Fix these before finishing" not in no_context


def test_flow_packet_includes_context_and_task(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("USE THE RULE\n", encoding="utf-8")

    def waiter(path: Path, packet_id: str) -> None:
        _write_artifact(path, packet_id, changed_files=[])

    handoff = make_ide_handoff_step(
        "ide", _config(tmp_path), artifact_waiter=waiter, sleep=lambda _: None, notify=lambda _: None
    )
    flow = Flow([Step("ide", handoff, rules_files=[str(rules)])])

    Runtime(checkpoint_path=tmp_path / "cp.json", run_id="run", retry_delay=0).run(
        flow, {"task": "write docs"}
    )

    packet = (
        tmp_path / ".lantern" / "handoff" / "run" / "ide" / "packet.md"
    ).read_text(encoding="utf-8")
    assert "USE THE RULE" in packet
    assert "write docs" in packet


def test_consumed_artifact_not_reused_for_different_or_identical_loopback(tmp_path: Path) -> None:
    clock = FakeClock()
    artifacts = [{"n": 1}, {"n": 2}, {"n": 2}]

    def waiter(path: Path, packet_id: str) -> None:
        if not path.exists():
            _write_artifact(path, packet_id, changed_files=[], **artifacts.pop(0))

    handoff_step = IdeHandoffStep(
        "ide", _config(tmp_path), artifact_waiter=waiter, sleep=clock.sleep, clock=clock, notify=lambda _: None
    )

    first = handoff_step.run({"task": "one"})
    first_packet = first["handoff"]["packet_id"]
    second = handoff_step.run({"task": "two"})
    second_packet = second["handoff"]["packet_id"]
    third = handoff_step.run({"task": "two"})
    third_packet = third["handoff"]["packet_id"]

    assert [first["n"], second["n"], third["n"]] == [1, 2, 2]
    assert len({first_packet, second_packet, third_packet}) == 3


def test_stale_artifact_is_ignored(tmp_path: Path) -> None:
    clock = FakeClock()
    calls = {"count": 0}

    def waiter(path: Path, packet_id: str) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            _write_artifact(path, "old", changed_files=[])
        elif calls["count"] == 2:
            _write_artifact(path, packet_id, changed_files=[], ok=True)

    step = IdeHandoffStep(
        "ide", _config(tmp_path), artifact_waiter=waiter, sleep=clock.sleep, clock=clock, notify=lambda _: None
    )

    assert step.run("task")["ok"] is True
    assert calls["count"] == 2


def test_missing_packet_id_and_non_object_artifacts_are_loud(tmp_path: Path) -> None:
    def no_packet(path: Path, packet_id: str) -> None:
        path.write_text(json.dumps({"changed_files": []}), encoding="utf-8")

    step = IdeHandoffStep(
        "ide", _config(tmp_path, "missing"), artifact_waiter=no_packet, sleep=lambda _: None, notify=lambda _: None
    )
    with pytest.raises(IdeHandoffError, match="packet_id"):
        step.run("task")

    def array(path: Path, packet_id: str) -> None:
        path.write_text(json.dumps(["not", "object"]), encoding="utf-8")

    step = IdeHandoffStep(
        "ide", _config(tmp_path, "array"), artifact_waiter=array, sleep=lambda _: None, notify=lambda _: None
    )
    with pytest.raises(IdeHandoffError, match="artifact.json"):
        step.run("task")


def test_resume_reuses_packet_without_rewrite_and_accepts_finished_artifact(tmp_path: Path) -> None:
    class Interrupt(Exception):
        pass

    calls = {"count": 0}

    def interrupt_once(path: Path, packet_id: str) -> None:
        calls["count"] += 1
        raise Interrupt("down")

    step = IdeHandoffStep(
        "ide", _config(tmp_path), artifact_waiter=interrupt_once, sleep=lambda _: None, notify=lambda _: None
    )
    with pytest.raises(Interrupt):
        step.run({"task": "resume"})
    packet_id = _packet_id(step)
    before = step.packet_path.stat().st_mtime_ns
    _write_artifact(step.artifact_path, packet_id, changed_files=[], ok=True)

    resumed = IdeHandoffStep(
        "ide", _config(tmp_path), artifact_waiter=None, sleep=lambda _: None, notify=lambda _: None
    )
    assert resumed.run({"task": "resume"})["ok"] is True
    assert resumed.packet_path.stat().st_mtime_ns == before


def test_bom_artifact_parses(tmp_path: Path) -> None:
    def waiter(path: Path, packet_id: str) -> None:
        path.write_text("\ufeff" + json.dumps({"packet_id": packet_id, "changed_files": []}), encoding="utf-8")

    step = IdeHandoffStep(
        "ide", _config(tmp_path), artifact_waiter=waiter, sleep=lambda _: None, notify=lambda _: None
    )
    assert step.run("task")["packet_id"]


def test_rename_retry_and_persistent_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_replace = os.replace
    attempts = {"count": 0}

    def waiter(path: Path, packet_id: str) -> None:
        if not path.exists():
            _write_artifact(path, packet_id, changed_files=[])

    def flaky_replace(src: str | Path, dst: str | Path) -> None:
        if str(src).endswith("artifact.json") and attempts["count"] == 0:
            attempts["count"] += 1
            raise PermissionError("locked")
        original_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    step = IdeHandoffStep(
        "ide", _config(tmp_path, "retry"), artifact_waiter=waiter, sleep=lambda _: None, notify=lambda _: None
    )
    step.run("task")
    assert attempts["count"] == 1

    def always_locked(src: str | Path, dst: str | Path) -> None:
        if str(src).endswith("artifact.json"):
            raise PermissionError("locked")
        original_replace(src, dst)

    monkeypatch.setattr(os, "replace", always_locked)
    step = IdeHandoffStep(
        "ide", _config(tmp_path, "locked"), artifact_waiter=waiter, sleep=lambda _: None, notify=lambda _: None
    )
    with pytest.raises(IdeHandoffError, match="artifact.json"):
        step.run("task")


def test_partial_write_later_completes_and_grace_failure(tmp_path: Path) -> None:
    clock = FakeClock()
    calls = {"count": 0}

    def completes(path: Path, packet_id: str) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            path.write_text('{"packet_id":', encoding="utf-8")
        elif calls["count"] == 2:
            _write_artifact(path, packet_id, changed_files=[], ok=True)

    step = IdeHandoffStep(
        "ide", _config(tmp_path, "partial"), artifact_waiter=completes, sleep=clock.sleep, clock=clock, notify=lambda _: None
    )
    assert step.run("task")["ok"] is True

    def never(path: Path, packet_id: str) -> None:
        path.write_text('{"packet_id":', encoding="utf-8")

    clock = FakeClock()
    step = IdeHandoffStep(
        "ide", _config(tmp_path, "broken"), artifact_waiter=never, sleep=clock.sleep, clock=clock, notify=lambda _: None
    )
    with pytest.raises(IdeHandoffError, match="artifact.json"):
        step.run("task")


def test_timeout_and_notify(tmp_path: Path) -> None:
    clock = FakeClock()
    notes: list[str] = []
    step = IdeHandoffStep(
        "ide",
        _config(tmp_path),
        sleep=clock.sleep,
        clock=clock,
        notify=notes.append,
    )

    with pytest.raises(IdeHandoffTimeout, match="artifact.json"):
        step.run("task")

    assert len(notes) == 1
    assert "packet=" in notes[0] and "artifact=" in notes[0]


def test_goto_from_handoff_payloads_and_invalid_target() -> None:
    goto = goto_from_handoff(
        {"next_step": "build", "packet_id": "p", "handoff": {}, "x": 1},
        valid_step_names={"build"},
    )
    assert goto.target_step_name == "build"
    assert goto.payload == {"x": 1}

    explicit = goto_from_handoff(
        {"next_step": "build", "payload": {"y": 2}},
        valid_step_names={"build"},
    )
    assert explicit.payload == {"y": 2}

    with pytest.raises(HandoffDecisionError, match="bad.*build"):
        goto_from_handoff({"next_step": "bad"}, valid_step_names={"build"})


def test_orchestrator_step_jumps_in_real_flow(tmp_path: Path) -> None:
    calls: list[str] = []

    def waiter(path: Path, packet_id: str) -> None:
        _write_artifact(path, packet_id, next_step="second", payload={"skip": True})

    orchestrator = make_orchestrator_step(
        "orchestrate",
        _config(tmp_path),
        {"first", "second"},
        artifact_waiter=waiter,
        sleep=lambda _: None,
        notify=lambda _: None,
    )

    def first(value: dict[str, Any]) -> dict[str, Any]:
        calls.append("first")
        return value

    def second(value: dict[str, Any]) -> dict[str, Any]:
        calls.append("second")
        return value

    flow = Flow([Step("orchestrate", orchestrator), Step("first", first), Step("second", second)])
    result = Runtime(checkpoint_path=tmp_path / "cp.json", run_id="run", retry_delay=0).run(flow, "task")

    assert result == {"skip": True}
    assert calls == ["second"]


def test_orchestrator_respects_runtime_transition_errors(tmp_path: Path) -> None:
    def waiter(path: Path, packet_id: str) -> None:
        _write_artifact(path, packet_id, next_step="second", payload={})

    orchestrator = make_orchestrator_step(
        "orchestrate",
        _config(tmp_path),
        {"second", "missing"},
        artifact_waiter=waiter,
        sleep=lambda _: None,
        notify=lambda _: None,
    )
    flow = Flow(
        [Step("orchestrate", orchestrator), Step("first", lambda v: v), Step("second", lambda v: v)],
        transitions=[Transition("orchestrate", "first")],
    )
    with pytest.raises(IllegalTransitionError):
        Runtime(checkpoint_path=tmp_path / "cp.json", run_id="run", retry_delay=0).run(flow, "task")

    def missing_waiter(path: Path, packet_id: str) -> None:
        _write_artifact(path, packet_id, next_step="missing", payload={})

    missing = make_orchestrator_step(
        "orchestrate",
        _config(tmp_path, "missing-run"),
        {"missing"},
        artifact_waiter=missing_waiter,
        sleep=lambda _: None,
        notify=lambda _: None,
    )
    with pytest.raises(GotoTargetError):
        Runtime(checkpoint_path=tmp_path / "cp2.json", run_id="missing-run", retry_delay=0).run(
            Flow([Step("orchestrate", missing)]), "task"
        )


def test_pattern_checks_report_and_pass(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    bad = tmp_path / "bad.md"
    good.write_text("hello\nrequired\n", encoding="utf-8")
    bad.write_text("hello\nFORBID\n", encoding="utf-8")
    artifact = {"changed_files": ["good.md", "bad.md", "missing.md"]}
    check = make_pattern_check_step(
        [
            PatternRule("no-forbid", "FORBID", "forbid", "*.md", "remove it"),
            PatternRule("must-have", "required", "require", "*.md", "add it"),
            PatternRule("no-match-glob", "x", "require", "*.py"),
        ],
        base_dir=tmp_path,
        retry_target="ide",
    )

    result = check(artifact)

    assert isinstance(result, Goto)
    assert result.payload["task"] is None
    assert "feedback" in result.payload
    assert any(v["file"] == "bad.md" and v.get("line") == 2 for v in result.payload["violations"])
    assert any(v["file"] == "missing.md" for v in result.payload["violations"])

    clean = {"changed_files": ["good.md"]}
    assert check(clean) is clean

    provider_check = make_pattern_check_step(
        [PatternRule("provider-catches", "FORBID", "forbid", "*.md")],
        base_dir=tmp_path,
        retry_target="ide",
        files_provider=lambda _: ["bad.md"],
    )
    assert isinstance(provider_check({"changed_files": []}), Goto)


def test_full_loop_feedback_and_non_nested_tasks(tmp_path: Path) -> None:
    clock = FakeClock()
    target = tmp_path / "out.md"
    visits: list[str] = []

    def waiter(path: Path, packet_id: str) -> None:
        visits.append(packet_id)
        if len(visits) < 4:
            target.write_text("TODO\n", encoding="utf-8")
        else:
            target.write_text("clean\n", encoding="utf-8")
        _write_artifact(path, packet_id, changed_files=["out.md"])

    handoff = make_ide_handoff_step(
        "ide",
        _config(tmp_path),
        artifact_waiter=waiter,
        sleep=clock.sleep,
        clock=clock,
        notify=lambda _: None,
    )
    check = make_pattern_check_step(
        [PatternRule("no-todo", "TODO", "forbid", "*.md", "no TODOs")],
        base_dir=tmp_path,
        retry_target="ide",
    )
    flow = Flow([Step("ide", handoff), Step("check", check)])

    result = Runtime(
        checkpoint_path=tmp_path / "cp.json",
        run_id="run",
        retry_delay=0,
        max_jumps=10,
    ).run(flow, {"request": "fix"})

    assert result["changed_files"] == ["out.md"]
    assert len(visits) == 4
    assert len(set(visits)) == 4
    packet = (tmp_path / ".lantern" / "handoff" / "run" / "ide" / "packet.md").read_text(
        encoding="utf-8"
    )
    assert "out.md:1 [no-todo]" in packet
    assert '"request": "fix"' in packet
    assert '"violations"' not in packet
