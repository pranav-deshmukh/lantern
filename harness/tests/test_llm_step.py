"""Tests for the real LLM-backed step (mocked; no live API calls)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import Runtime, load_flow
from harness.llm_step import call_deepseek
from harness.trace_viewer import load_traces

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def test_summarize_flow_runs_end_to_end_with_mocked_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"prompt": None}

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        calls["prompt"] = prompt
        assert model == "deepseek-chat"
        return "A single-sentence summary."

    monkeypatch.setattr("harness.llm_step.call_deepseek", fake_call_deepseek)

    flow = load_flow(str(EXAMPLES_DIR / "summarize_flow.yaml"))
    assert [step.name for step in flow.steps] == ["read_input", "summarize"]
    assert all(step.contract is not None for step in flow.steps)

    trace_path = tmp_path / "trace.jsonl"
    runtime = Runtime(
        checkpoint_path=tmp_path / "checkpoint.json",
        trace_path=trace_path,
        retry_delay=0,
    )

    result = runtime.run(
        flow, {"text": "The quick brown fox jumps over the lazy dog."}
    )

    assert result.model_dump() == {"summary": "A single-sentence summary."}
    assert "quick brown fox" in calls["prompt"]

    records = load_traces(str(trace_path))
    assert [record["step_name"] for record in records] == ["read_input", "summarize"]
    assert all(record["succeeded"] is True for record in records)


def test_call_deepseek_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        call_deepseek("hello")
