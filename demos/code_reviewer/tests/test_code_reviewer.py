"""Tests for the code-reviewer demo (mocks the LLM, runs ruff for real)."""

from __future__ import annotations

from pathlib import Path

import pytest

import run_demo
import steps
from harness import PolicyViolation, Runtime


CLEAN_CODE = "def double(x):\n    return x * 2\n"


def test_clean_first_attempt_completes_without_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix_calls = {"count": 0}

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Review the following" in prompt:
            return "Unused imports and a bare except need attention."
        fix_calls["count"] += 1
        return CLEAN_CODE

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)
    target = tmp_path / "sample_code.py"
    monkeypatch.setattr(steps, "SAMPLE_CODE_PATH", target)

    flow = run_demo.build_flow(approval_callback=lambda _action, _risk: True)
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    result = runtime.run(flow, {"source_code": "original code"})

    assert result.model_dump() == {"applied": True}
    assert fix_calls["count"] == 1
    assert target.read_text(encoding="utf-8") == CLEAN_CODE


def test_real_ruff_loop_retries_until_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix_prompts: list[str] = []

    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Review the following" in prompt:
            return "There is an unused import to remove."
        fix_prompts.append(prompt)
        if len(fix_prompts) == 1:
            return "import os\n\ndef double(x):\n    return x * 2\n"
        return CLEAN_CODE

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)
    target = tmp_path / "sample_code.py"
    monkeypatch.setattr(steps, "SAMPLE_CODE_PATH", target)

    flow = run_demo.build_flow(approval_callback=lambda _action, _risk: True)
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    result = runtime.run(flow, {"source_code": "original code"})

    assert result.model_dump() == {"applied": True}
    assert len(fix_prompts) == 2
    # The second fix attempt received the REAL ruff output from the first lint.
    assert "F401" in fix_prompts[1]
    assert target.read_text(encoding="utf-8") == CLEAN_CODE


def test_denied_approval_stops_flow_without_writing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
        if "Review the following" in prompt:
            return "Nothing major to report."
        return CLEAN_CODE

    monkeypatch.setattr(steps, "call_deepseek", fake_call_deepseek)
    target = tmp_path / "sample_code.py"
    target.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr(steps, "SAMPLE_CODE_PATH", target)

    flow = run_demo.build_flow(approval_callback=lambda _action, _risk: False)
    runtime = Runtime(checkpoint_path=tmp_path / "cp.json", retry_delay=0)

    with pytest.raises(PolicyViolation, match="apply_code_fix"):
        runtime.run(flow, {"source_code": "original code"})

    assert target.read_text(encoding="utf-8") == "ORIGINAL"
