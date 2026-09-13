"""Tests for the adaptive coding agent init flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import run_init
import steps
from harness import ContractViolationError, Runtime, StepExecutionError


SCAN_SUMMARY = (
    "Python package using pytest and ruff. Tests appear to run with "
    "`python -m pytest`; lint appears to run with `python -m ruff check .`. "
    "Type hints and docstrings are used inconsistently."
)
QUESTIONS = "\n".join(
    [
        "Should new code include type hints even when nearby code omits them?",
        "Should public helpers have docstrings?",
    ]
)
VALID_PROFILE = {
    "stack": "Python package with pytest and ruff",
    "dependencies": ["pytest", "ruff"],
    "test_command": "python -m pytest",
    "lint_command": "python -m ruff check .",
    "conventions": [
        "Prefer type hints for new public functions.",
        "Use concise docstrings for public modules and helpers.",
    ],
}


def test_full_init_flow_writes_valid_project_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter([SCAN_SUMMARY, QUESTIONS, json.dumps(VALID_PROFILE)])

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        return next(responses)

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)
    profile_path = tmp_path / "project-profile.json"
    monkeypatch.setattr(steps, "PROFILE_PATH", profile_path)

    flow = run_init.build_flow(
        answer_callback=lambda questions: {question: "Yes." for question in questions}
    )
    runtime = Runtime(
        checkpoint_path=tmp_path / "checkpoint.json",
        trace_path=tmp_path / "trace.jsonl",
        max_retries=0,
        retry_delay=0,
    )

    result = runtime.run(flow, {"repo_path": str(steps.SAMPLE_REPO_PATH)})

    assert result.model_dump() == VALID_PROFILE
    assert profile_path.exists()
    assert json.loads(profile_path.read_text(encoding="utf-8")) == VALID_PROFILE


def test_ask_clarifying_questions_uses_provided_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(steps, "call_deepseek", lambda _prompt: QUESTIONS)
    callback_questions: list[str] = []

    def answer_callback(questions: list[str]) -> dict[str, str]:
        callback_questions.extend(questions)
        return {question: "Yes." for question in questions}

    result = steps.ask_clarifying_questions(
        steps.ScanOutput(repo_path="repo", scan_summary=SCAN_SUMMARY),
        answer_callback=answer_callback,
    )

    assert callback_questions == [
        "Should new code include type hints even when nearby code omits them?",
        "Should public helpers have docstrings?",
    ]
    assert result["questions_and_answers"] == {
        question: "Yes." for question in callback_questions
    }


def test_malformed_profile_response_raises_contract_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed_profile: dict[str, Any] = {
        "stack": "Python package",
        "dependencies": ["pytest", "ruff"],
        "lint_command": "python -m ruff check .",
        "conventions": ["Use the existing mixed style deliberately."],
    }
    responses = iter([SCAN_SUMMARY, QUESTIONS, json.dumps(malformed_profile)])
    monkeypatch.setattr(steps, "call_deepseek", lambda _prompt: next(responses))
    profile_path = tmp_path / "project-profile.json"
    monkeypatch.setattr(steps, "PROFILE_PATH", profile_path)

    flow = run_init.build_flow(
        answer_callback=lambda questions: {question: "Yes." for question in questions}
    )
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", max_retries=0)

    with pytest.raises(StepExecutionError) as error:
        runtime.run(
            flow,
            {"repo_path": str(steps.SAMPLE_REPO_PATH)},
        )

    assert isinstance(error.value.cause, ContractViolationError)
    assert error.value.cause.step_name == "write_project_profile"
    assert "test_command" in str(error.value.cause)
    assert not profile_path.exists()


def test_written_project_profile_json_matches_required_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(steps, "call_deepseek", lambda _prompt: json.dumps(VALID_PROFILE))
    profile_path = tmp_path / "project-profile.json"
    monkeypatch.setattr(steps, "PROFILE_PATH", profile_path)

    result = steps.write_project_profile(
        steps.ClarifyingOutput(
            repo_path=str(steps.SAMPLE_REPO_PATH),
            scan_summary=SCAN_SUMMARY,
            questions_and_answers={"Use type hints?": "Yes."},
        )
    )

    written = json.loads(profile_path.read_text(encoding="utf-8"))
    assert written == result
    assert set(written) == {
        "stack",
        "dependencies",
        "test_command",
        "lint_command",
        "conventions",
    }
    steps.ProjectProfile.model_validate(written)
