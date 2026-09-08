"""Tests for agent context bundling (mechanical injection + auditability)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (
    Flow,
    MissingContextFileError,
    Runtime,
    Step,
    load_context_files,
    load_flow,
)
from harness.trace_viewer import load_traces


HELPER_MODULE_SOURCE = '''\
"""Helpers for the context bundling tests."""


def passthrough(data):
    return data
'''


@pytest.fixture
def helper_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a real importable module for YAML loader tests."""
    module_path = tmp_path / "ctx_helpers.py"
    module_path.write_text(HELPER_MODULE_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return module_path


def test_step_without_context_is_unchanged() -> None:
    received: dict[str, object] = {}

    def fn(value: object) -> object:
        received["value"] = value
        return value

    step = Step("plain", fn)

    result = step.execute({"a": 1})

    assert result == {"a": 1}
    assert received["value"] == {"a": 1}


def test_step_with_rules_files_injects_bundled_content(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("RULE ONE\n", encoding="utf-8")

    received: dict[str, object] = {}

    def fn(data: dict) -> dict:
        received["data"] = data
        return data

    step = Step("ctx", fn, rules_files=[str(rules)])

    result = step.execute({"input_value": 42})

    assert result["input"] == {"input_value": 42}
    assert result["context"] == f"--- {rules} ---\nRULE ONE\n"
    assert received["data"] == result


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


def test_trace_records_context_paths_and_hashes(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    content = "RULE A\nRULE B\n"
    rules.write_text(content, encoding="utf-8")
    manual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def fn(data: dict) -> dict:
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

    def fn(data: dict) -> dict:
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

    def fn(data: dict) -> dict:
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
    assert "RELATIVE RULE" in result["context"]
