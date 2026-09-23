"""Integration tests for executing LLM-backed agents through Lantern.

These tests validate the Agent -> Harness -> Runtime -> Step -> Trace contract
using fake agents (no network calls). Provider-level ``call_deepseek`` tests
are kept in this same file but clearly separated from the execution-path tests.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

# Tests run directly from the repository without requiring package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import harness.llm_step as llm_step
from harness import Flow, Goto, Harness, Runtime, Step
from harness.trace_viewer import load_traces


# ---------------------------------------------------------------------------
# Execution-path integration tests
# ---------------------------------------------------------------------------


def test_llm_backed_agent_runs_end_to_end_through_harness(tmp_path: Path) -> None:
    class FakeLLMAgent:
        def run(self, input):
            return f"LLM processed: {input}"

    trace_path = tmp_path / "trace.jsonl"
    harness = Harness(FakeLLMAgent(), trace_path=trace_path, retry_delay=0)

    result = harness.run("hello")

    # Original input -> agent unchanged; result -> caller unchanged.
    assert result == "LLM processed: hello"

    records = load_traces(str(trace_path))
    assert len(records) == 1
    assert records[0]["step_name"] == "agent"
    assert records[0]["input"] == "hello"
    assert records[0]["output"] == "LLM processed: hello"
    assert records[0]["succeeded"] is True


def test_context_aware_llm_agent_through_runtime(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("RULE ONE\n", encoding="utf-8")

    class FakeReviewAgent:
        def run(self, input, context):
            return {
                "input": input,
                "has_rules": context.rules is not None,
            }

    flow = Flow(
        [Step("review", FakeReviewAgent().run, rules_files=[str(rules)])]
    )
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    result = runtime.run(flow, "review this code")

    # The input string is NOT transformed into {"input": ..., "context": ...}.
    # Context is delivered separately to the opt-in ``context`` parameter.
    assert result == {"input": "review this code", "has_rules": True}
    assert result["input"] == "review this code"


def test_runtime_owns_retry_for_flaky_llm_agent(tmp_path: Path) -> None:
    calls = {"count": 0}

    class FlakyLLMAgent:
        def run(self, input):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("LLM transient failure")
            return f"success after retry: {input}"

    trace_path = tmp_path / "trace.jsonl"
    harness = Harness(
        FlakyLLMAgent(),
        trace_path=trace_path,
        max_retries=1,  # one retry => two attempts total
        retry_delay=0,
    )

    result = harness.run("task")

    assert result == "success after retry: task"
    assert calls["count"] == 2

    records = load_traces(str(trace_path))
    assert len(records) == 2
    assert records[0]["succeeded"] is False
    assert "LLM transient failure" in records[0]["error"]
    assert records[1]["succeeded"] is True
    assert records[1]["output"] == "success after retry: task"
    assert records[0]["input"] == "task"
    assert records[1]["input"] == "task"


def test_failure_feedback_loops_back_to_agent_via_goto(tmp_path: Path) -> None:
    attempts = {"count": 0}
    feedback_received: list[str] = []

    class CodeAgent:
        def run(self, input):
            attempts["count"] += 1
            if "failure_feedback" in input:
                feedback_received.append(input["failure_feedback"])
                return {"story": input["story"], "code": "fixed"}
            return {"story": input["story"], "code": "broken"}

    def check(data):
        if data["code"] != "fixed":
            return Goto(
                "code_agent",
                {
                    "story": data["story"],
                    "previous_code": data["code"],
                    "failure_feedback": "code failed validation",
                },
            )
        return data

    flow = Flow([Step("code_agent", CodeAgent().run), Step("check", check)])
    runtime = Runtime(
        checkpoint_path=tmp_path / "cp.json",
        max_jumps=10,
        retry_delay=0,
    )

    result = runtime.run(flow, {"story": "implement X"})

    assert result == {"story": "implement X", "code": "fixed"}
    assert attempts["count"] == 2
    assert feedback_received == ["code failed validation"]


def test_trace_records_expected_fields_for_llm_agent(tmp_path: Path) -> None:
    rules = tmp_path / "rules.md"
    rules.write_text("RULE\n", encoding="utf-8")

    class Agent:
        def run(self, input, context):
            return f"ok {input}"

    trace_path = tmp_path / "trace.jsonl"
    flow = Flow([Step("llm", Agent().run, rules_files=[str(rules)])])
    runtime = Runtime(
        trace_path=trace_path,
        checkpoint_path=tmp_path / "cp.json",
        run_id="trace-run",
        retry_delay=0,
    )

    runtime.run(flow, "hi")

    record = load_traces(str(trace_path))[0]
    assert record["run_id"] == "trace-run"
    assert record["step_name"] == "llm"
    assert record["input"] == "hi"
    assert record["output"] == "ok hi"
    assert isinstance(record["duration_ms"], (int, float))
    assert record["succeeded"] is True
    assert record["error"] is None
    assert record["context_files"] == [
        {"path": str(rules), "hash": hashlib.sha256(b"RULE\n").hexdigest()}
    ]


def test_byo_agent_remains_lantern_unaware(tmp_path: Path) -> None:
    class GreetingAgent:
        def run(self, input):
            return f"processed: {input}"

    trace_path = tmp_path / "trace.jsonl"
    harness = Harness(GreetingAgent(), trace_path=trace_path, retry_delay=0)

    result = harness.run("hi")

    assert result == "processed: hi"
    assert load_traces(str(trace_path))[0]["output"] == "processed: hi"


# ---------------------------------------------------------------------------
# Provider-level tests (mocked OpenAI client, no network)
# ---------------------------------------------------------------------------


def test_call_deepseek_configures_client_and_extracts_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessage:
        def __init__(self, content: str | None) -> None:
            self.content = content

    class FakeChoice:
        def __init__(self, content: str | None) -> None:
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content: str | None) -> None:
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, *, model: str, messages: list[dict[str, str]]) -> FakeResponse:
            captured["model"] = model
            captured["messages"] = messages
            return FakeResponse("assistant reply")

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = FakeChat()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(llm_step, "OpenAI", FakeClient)

    result = llm_step.call_deepseek("hello", model="deepseek-chat")

    assert result == "assistant reply"
    assert captured == {
        "api_key": "sk-test",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_call_deepseek_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        llm_step.call_deepseek("hello")


def test_call_deepseek_raises_when_response_has_no_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMessage:
        content = None

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, *, model, messages):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        def __init__(self, *, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(llm_step, "OpenAI", FakeClient)

    with pytest.raises(RuntimeError, match="no message content"):
        llm_step.call_deepseek("hello")
