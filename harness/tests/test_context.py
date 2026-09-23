"""Tests for agent context bundling (mechanical injection + auditability)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (
    ExecutionContext,
    Flow,
    Goto,
    Harness,
    MissingContextFileError,
    Runtime,
    Step,
    load_context_files,
    load_flow,
)
from harness.trace_viewer import load_traces


HELPER_MODULE_SOURCE = '''\
"""Helpers for the context bundling tests."""


def passthrough(data, context=None):
    return {
        "data": data,
        "context": context.as_text() if context is not None else "",
    }
'''


@pytest.fixture
def helper_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a real importable module for YAML loader tests."""
    module_path = tmp_path / "ctx_helpers.py"
    module_path.write_text(HELPER_MODULE_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return module_path


# --- Simple components: input passes through unchanged ---


def test_step_without_context_is_unchanged() -> None:
    received: dict[str, object] = {}

    def fn(value: object) -> object:
        received["value"] = value
        return value

    step = Step("plain", fn)

    result = step.execute({"a": 1})

    assert result == {"a": 1}
    assert received["value"] == {"a": 1}


def test_simple_function_input_is_not_transformed_by_context(tmp_path: Path) -> None:
    """Declaring context files must not change the input shape of a simple fn."""
    rules = tmp_path / "rules.md"
    rules.write_text("RULE ONE\n", encoding="utf-8")

    received: dict[str, object] = {}

    def fn(value: object) -> object:
        received["value"] = value
        return value

    step = Step("simple", fn, rules_files=[str(rules)])

    result = step.execute("hello")

    assert result == "hello"
    assert received["value"] == "hello"


# --- Context-aware components opt in via a ``context`` parameter ---


def test_context_aware_step_receives_context_without_corrupting_input(
    tmp_path: Path,
) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("RULE ONE\n", encoding="utf-8")

    received: dict[str, object] = {}

    def fn(value: object, context: ExecutionContext) -> object:
        received["value"] = value
        received["context"] = context
        return value

    step = Step("ctx", fn, rules_files=[str(rules)])

    result = step.execute("hello")

    assert result == "hello"
    assert received["value"] == "hello"
    assert received["context"].rules.as_text() == f"--- {rules} ---\nRULE ONE\n"


# --- Context primitives ---


def test_load_context_files_raises_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MissingContextFileError, match="nope.md"):
        load_context_files([str(tmp_path / "nope.md")])


def test_missing_file_in_yaml_fails_at_load_time(
    tmp_path: Path, helper_module: Path
) -> None:
    flow_dir = tmp_path / "flows"
    flow_dir.mkdir()
    yaml_path = flow_dir / "broken.yaml"
    yaml_path.write_text(
        """\
steps:
  - name: ctx_step
    function: ctx_helpers.passthrough
    rules_files:
      - missing-rules.md
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error_info:
        load_flow(str(yaml_path))

    message = str(error_info.value)
    assert "broken.yaml" in message
    assert "ctx_step" in message
    assert "missing-rules.md" in message


# --- Extensibility ---


def test_execution_context_has_extensible_fields() -> None:
    context = ExecutionContext()

    assert context.rules is None
    assert context.skills is None
    assert context.memory is None
    assert context.experience is None
    assert context.metadata == {}
    assert context.as_text() == ""
    assert context.audit_entries() == []


def test_adding_context_kinds_does_not_change_input_contract(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("R\n", encoding="utf-8")
    skills = tmp_path / "skills.md"
    skills.write_text("S\n", encoding="utf-8")

    received: dict[str, object] = {}

    def fn(value: object, context: ExecutionContext) -> object:
        received["value"] = value
        received["rules"] = context.rules.as_text() if context.rules else None
        received["skills"] = context.skills.as_text() if context.skills else None
        return value

    step = Step(
        "ctx",
        fn,
        rules_files=[str(rules)],
        skills_files=[str(skills)],
    )

    result = step.execute({"n": 1})

    assert result == {"n": 1}
    assert received["value"] == {"n": 1}
    assert received["rules"] == f"--- {rules} ---\nR\n"
    assert received["skills"] == f"--- {skills} ---\nS\n"


# --- Backwards compatibility: BYO agents stay Lantern-unaware ---


def test_byo_agent_with_run_method_needs_no_context_knowledge() -> None:
    class BareAgent:
        def run(self, input):
            return f"processed: {input}"

    harness = Harness(BareAgent())

    assert harness.run("hi") == "processed: hi"


# --- Isolation ---


def test_context_does_not_leak_between_steps(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("SECRET\n", encoding="utf-8")

    seen: list[str | None] = []

    def first(value: object, context: ExecutionContext) -> object:
        seen.append(context.rules.as_text() if context.rules else None)
        return value

    def second(value: object, context: ExecutionContext) -> object:
        seen.append(context.rules.as_text() if context.rules else None)
        return value

    flow = Flow(
        [
            Step("first", first, rules_files=[str(rules)]),
            Step("second", second),
        ]
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    runtime.run(flow, "x")

    assert seen[0] == f"--- {rules} ---\nSECRET\n"
    assert seen[1] is None  # The second step has no rules, so nothing leaks.


# --- Runtime paths: retries and Goto with context ---


def test_context_through_runtime_retry_and_goto(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("RULE\n", encoding="utf-8")

    attempts = {"count": 0}
    seen_contexts: list[str | None] = []

    def work(value: object, context: ExecutionContext) -> object:
        attempts["count"] += 1
        seen_contexts.append(context.rules.as_text() if context.rules else None)
        if attempts["count"] < 3:
            raise ValueError("try again")
        return Goto("finish", value)

    def finish(value: object) -> object:
        return value

    flow = Flow(
        [
            Step("work", work, rules_files=[str(rules)]),
            Step("finish", finish),
        ]
    )
    runtime = Runtime(
        checkpoint_path=tmp_path / "cp.json",
        trace_path=tmp_path / "trace.jsonl",
        max_retries=2,
        retry_delay=0,
    )

    result = runtime.run(flow, "payload")

    assert result == "payload"
    assert attempts["count"] == 3
    assert seen_contexts == [f"--- {rules} ---\nRULE\n"] * 3

    records = load_traces(str(tmp_path / "trace.jsonl"))
    assert [record["step_name"] for record in records] == [
        "work",
        "work",
        "work",
        "finish",
    ]
    assert all(
        record["context_files"] == [{"path": str(rules), "hash": hashlib.sha256(b"RULE\n").hexdigest()}]
        for record in records
        if record["step_name"] == "work"
    )


# --- Tracing: paths + hashes (auditability) ---


def test_trace_records_context_paths_and_hashes(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    content = "RULE A\nRULE B\n"
    rules.write_text(content, encoding="utf-8")
    manual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def fn(data: object) -> object:
        return data

    step = Step("ctx", fn, rules_files=[str(rules)])
    trace_path = tmp_path / "trace.jsonl"
    runtime = Runtime(
        checkpoint_path=tmp_path / "cp.json",
        trace_path=trace_path,
        retry_delay=0,
    )

    runtime.run(Flow([step]), {"n": 1})

    records = load_traces(str(trace_path))
    assert len(records) == 1
    assert records[0]["context_files"] == [
        {"path": str(rules), "hash": manual_hash}
    ]


def test_same_file_produces_same_hash_across_runs(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("SAME CONTENT\n", encoding="utf-8")

    def fn(data: object) -> object:
        return data

    step = Step("ctx", fn, rules_files=[str(rules)])
    trace1 = tmp_path / "t1.jsonl"
    trace2 = tmp_path / "t2.jsonl"
    Runtime(
        checkpoint_path=tmp_path / "cp1.json", trace_path=trace1, retry_delay=0
    ).run(Flow([step]), {"n": 1})
    Runtime(
        checkpoint_path=tmp_path / "cp2.json", trace_path=trace2, retry_delay=0
    ).run(Flow([step]), {"n": 1})

    hash1 = load_traces(str(trace1))[0]["context_files"][0]["hash"]
    hash2 = load_traces(str(trace2))[0]["context_files"][0]["hash"]

    assert hash1 == hash2


def test_changed_file_produces_different_hash(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("VERSION ONE\n", encoding="utf-8")

    def fn(data: object) -> object:
        return data

    step = Step("ctx", fn, rules_files=[str(rules)])
    trace1 = tmp_path / "t1.jsonl"
    trace2 = tmp_path / "t2.jsonl"
    Runtime(
        checkpoint_path=tmp_path / "cp1.json", trace_path=trace1, retry_delay=0
    ).run(Flow([step]), {"n": 1})

    rules.write_text("VERSION TWO\n", encoding="utf-8")
    Runtime(
        checkpoint_path=tmp_path / "cp2.json", trace_path=trace2, retry_delay=0
    ).run(Flow([step]), {"n": 1})

    hash1 = load_traces(str(trace1))[0]["context_files"][0]["hash"]
    hash2 = load_traces(str(trace2))[0]["context_files"][0]["hash"]

    assert hash1 != hash2


def test_yaml_relative_context_paths_resolve_from_yaml_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, helper_module: Path
) -> None:
    flow_dir = tmp_path / "nested"
    flow_dir.mkdir()
    rules = flow_dir / "rules.md"
    rules.write_text("RELATIVE RULE\n", encoding="utf-8")

    yaml_path = flow_dir / "ctx_flow.yaml"
    yaml_path.write_text(
        """\
steps:
  - name: ctx_step
    function: ctx_helpers.passthrough
    rules_files:
      - rules.md
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)  # Run from a directory unrelated to the YAML.

    flow = load_flow(str(yaml_path))
    step = flow.steps[0]

    assert step.rules_files == [str(rules.resolve())]

    result = step.execute({"n": 1})
    assert result["data"] == {"n": 1}
    assert "RELATIVE RULE" in result["context"]
