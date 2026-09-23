"""Tests for the adaptive coding agent per-story flow."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_story
import steps
from harness import PolicyViolation, Runtime


STORY = "Make clamp cap values above the maximum."
TARGET_FILE = "src/lantern_sample/math_tools.py"
ORIGINAL_MATH_TOOLS = '''"""Small numeric helpers."""


def percentage(part: float, whole: float) -> float:
    """Return part as a percentage of whole, rounded for display."""
    if whole == 0:
        return 0.0
    return round((part / whole) * 100, 1)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Return value constrained to the inclusive range."""
    if value < minimum:
        return minimum
    return value
'''
PASSING_MATH_TOOLS = '''"""Small numeric helpers."""


def percentage(part: float, whole: float) -> float:
    """Return part as a percentage of whole, rounded for display."""
    if whole == 0:
        return 0.0
    return round((part / whole) * 100, 1)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Return value constrained to the inclusive range."""
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value
'''
BREAKS_EXISTING_TEST = '''"""Small numeric helpers."""


def percentage(part: float, whole: float) -> float:
    """Return part as a percentage of whole, rounded for display."""
    return round((part / whole) * 100, 1)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Return value constrained to the inclusive range."""
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value
'''
LINTY_MATH_TOOLS = '''"""Small numeric helpers."""

import os


def percentage(part: float, whole: float) -> float:
    """Return part as a percentage of whole, rounded for display."""
    if whole == 0:
        return 0.0
    return round((part / whole) * 100, 1)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Return value constrained to the inclusive range."""
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value
'''
STORY_TEST = """from lantern_sample.math_tools import clamp


def test_clamp_caps_values_above_maximum() -> None:
    assert clamp(12, 0, 10) == 10
"""


@pytest.fixture()
def isolated_sample_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "sample_repo"
    shutil.copytree(
        steps.SAMPLE_REPO_PATH,
        repo,
        ignore=shutil.ignore_patterns(
            ".pytest_cache", "__pycache__", ".ruff_cache", ".git"
        ),
    )
    monkeypatch.setattr(steps, "SAMPLE_REPO_PATH", repo)
    return repo


@pytest.fixture()
def project_profile() -> steps.ProjectProfile:
    return steps.ProjectProfile(
        stack="Python package with pytest and ruff",
        dependencies=["pytest", "ruff"],
        test_command="python -m pytest",
        lint_command="python -m ruff check .",
        conventions=[
            "Prefer type hints for new public functions.",
            "Use concise docstrings for public helpers.",
        ],
    )


def test_story_flow_completes_without_loop_on_first_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_sample_repo: Path,
    project_profile: steps.ProjectProfile,
) -> None:
    calls = {"code": 0}
    final_temp_path = {"value": ""}

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Return JSON only with keys: plan and target_file" in prompt:
            return json.dumps({"plan": "Update clamp.", "target_file": TARGET_FILE})
        if "Return the FULL new contents" in prompt:
            calls["code"] += 1
            return PASSING_MATH_TOOLS
        if "Generate exactly one pytest test function" in prompt:
            return STORY_TEST
        if "Write a short review summary" in prompt:
            return "Updated clamp; all gates passed."
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)
    original = (isolated_sample_repo / TARGET_FILE).read_text(encoding="utf-8")

    flow = run_story.build_flow(approval_callback=lambda _action, _risk: True)
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", max_retries=0)
    result = runtime.run(
        flow,
        {"project_profile": project_profile.model_dump(), "story": STORY},
    )
    final_temp_path["value"] = _last_apply_input(runtime)["temp_repo_path"]

    assert result.model_dump() == {"applied": True, "target_file": TARGET_FILE}
    assert calls["code"] == 1
    assert (isolated_sample_repo / TARGET_FILE).read_text(encoding="utf-8") != original
    assert not Path(final_temp_path["value"]).exists()


def test_parity_check_catches_real_existing_test_failure_and_loops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_sample_repo: Path,
    project_profile: steps.ProjectProfile,
) -> None:
    code_attempts = iter([BREAKS_EXISTING_TEST, PASSING_MATH_TOOLS])
    failure_feedback: list[str] = []

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Return JSON only with keys: plan and target_file" in prompt:
            return json.dumps({"plan": "Update clamp.", "target_file": TARGET_FILE})
        if "Return the FULL new contents" in prompt:
            if "previous attempt failed" in prompt:
                failure_feedback.append(prompt)
            return next(code_attempts)
        if "Generate exactly one pytest test function" in prompt:
            return STORY_TEST
        if "Write a short review summary" in prompt:
            return "Updated clamp after fixing regression; all gates passed."
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)

    result = Runtime(checkpoint_path=tmp_path / "checkpoint.json", max_retries=0).run(
        run_story.build_flow(approval_callback=lambda _action, _risk: True),
        {"project_profile": project_profile.model_dump(), "story": STORY},
    )

    assert result.applied is True
    assert len(failure_feedback) == 1
    assert "ZeroDivisionError" in failure_feedback[0]
    assert (isolated_sample_repo / TARGET_FILE).read_text(encoding="utf-8") == PASSING_MATH_TOOLS


def test_quality_gate_catches_real_lint_failure_and_loops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_sample_repo: Path,
    project_profile: steps.ProjectProfile,
) -> None:
    code_attempts = iter([LINTY_MATH_TOOLS, PASSING_MATH_TOOLS])
    failure_feedback: list[str] = []

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Return JSON only with keys: plan and target_file" in prompt:
            return json.dumps({"plan": "Update clamp.", "target_file": TARGET_FILE})
        if "Return the FULL new contents" in prompt:
            if "previous attempt failed" in prompt:
                failure_feedback.append(prompt)
            return next(code_attempts)
        if "Generate exactly one pytest test function" in prompt:
            return STORY_TEST
        if "Write a short review summary" in prompt:
            return "Updated clamp after fixing lint; all gates passed."
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)

    result = Runtime(checkpoint_path=tmp_path / "checkpoint.json", max_retries=0).run(
        run_story.build_flow(approval_callback=lambda _action, _risk: True),
        {"project_profile": project_profile.model_dump(), "story": STORY},
    )

    assert result.applied is True
    assert len(failure_feedback) == 1
    assert "F401" in failure_feedback[0]
    assert (isolated_sample_repo / TARGET_FILE).read_text(encoding="utf-8") == PASSING_MATH_TOOLS


def test_three_independent_gates_can_each_jump_back_to_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_sample_repo: Path,
    project_profile: steps.ProjectProfile,
) -> None:
    attempts = iter(
        [
            BREAKS_EXISTING_TEST,
            ORIGINAL_MATH_TOOLS,
            LINTY_MATH_TOOLS,
            PASSING_MATH_TOOLS,
        ]
    )
    code_prompts: list[str] = []

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Return JSON only with keys: plan and target_file" in prompt:
            return json.dumps({"plan": "Update clamp.", "target_file": TARGET_FILE})
        if "Return the FULL new contents" in prompt:
            code_prompts.append(prompt)
            return next(attempts)
        if "Generate exactly one pytest test function" in prompt:
            return STORY_TEST
        if "Write a short review summary" in prompt:
            return "Final attempt passed parity, generated test, and lint."
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)
    runtime = Runtime(
        checkpoint_path=tmp_path / "checkpoint.json",
        trace_path=tmp_path / "trace.jsonl",
        max_retries=0,
        max_jumps=10,
    )

    result = runtime.run(
        run_story.build_flow(approval_callback=lambda _action, _risk: True),
        {"project_profile": project_profile.model_dump(), "story": STORY},
    )

    assert result.model_dump() == {"applied": True, "target_file": TARGET_FILE}
    assert len(code_prompts) == 4
    assert "ZeroDivisionError" in code_prompts[1]
    assert "assert clamp(12, 0, 10) == 10" in code_prompts[2]
    assert "F401" in code_prompts[3]
    assert (isolated_sample_repo / TARGET_FILE).read_text(encoding="utf-8") == PASSING_MATH_TOOLS


def test_denied_approval_leaves_real_file_unchanged_and_cleans_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_sample_repo: Path,
    project_profile: steps.ProjectProfile,
) -> None:
    temp_path = {"value": ""}

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Return JSON only with keys: plan and target_file" in prompt:
            return json.dumps({"plan": "Update clamp.", "target_file": TARGET_FILE})
        if "Return the FULL new contents" in prompt:
            return PASSING_MATH_TOOLS
        if "Generate exactly one pytest test function" in prompt:
            return STORY_TEST
        if "Write a short review summary" in prompt:
            return "Updated clamp; all gates passed."
        raise AssertionError(f"Unexpected prompt: {prompt}")

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)
    original = (isolated_sample_repo / TARGET_FILE).read_text(encoding="utf-8")
    runtime = Runtime(checkpoint_path=tmp_path / "checkpoint.json", max_retries=0)

    with pytest.raises(PolicyViolation):
        runtime.run(
            run_story.build_flow(approval_callback=lambda _action, _risk: False),
            {"project_profile": project_profile.model_dump(), "story": STORY},
        )

    temp_path["value"] = _last_apply_input(runtime)["temp_repo_path"]
    assert (isolated_sample_repo / TARGET_FILE).read_text(encoding="utf-8") == original
    assert not Path(temp_path["value"]).exists()


def _last_apply_input(runtime: Runtime) -> dict[str, str]:
    apply_records = [
        record
        for record in runtime.tracer.records
        if record["step_name"] == "apply_change"
    ]
    assert apply_records
    return apply_records[-1]["input"]
