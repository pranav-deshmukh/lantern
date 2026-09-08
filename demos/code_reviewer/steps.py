"""Step functions and demo-local contracts for the automated code reviewer."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

from harness import Goto
from harness.llm_step import call_deepseek


PROJECT_DIR = Path(__file__).resolve().parent
SAMPLE_CODE_PATH = PROJECT_DIR / "sample_code.py"


# --- Demo-specific contracts (defined here, not in the harness package) ---
#
# Adjacent steps deliberately share a model class across their output/input
# boundary (review output == fix_issues input, fix output == lint input, lint
# output == apply input) so the harness can chain them without cross-model
# validation problems.


class ReviewInput(BaseModel):
    source_code: str


class ReviewOutput(BaseModel):
    source_code: str = ""
    review_notes: str
    previous_code: str = ""
    ruff_output: str = ""


class FixOutput(BaseModel):
    fixed_code: str
    review_notes: str


class LintOutput(BaseModel):
    fixed_code: str
    lint_result: str


class ApplyOutput(BaseModel):
    applied: bool


# --- Step functions ---


def review(data: ReviewInput) -> dict[str, str]:
    """Ask the model for a short human-readable review of the source code."""
    prompt = (
        "Review the following Python code and write a short human-readable "
        "summary (2-4 sentences) of its main style/lint issues. Do not rewrite "
        "the code.\n\n"
        f"{data.source_code}"
    )
    notes = call_deepseek(prompt)
    return {"source_code": data.source_code, "review_notes": notes}


def fix_issues(data: ReviewOutput) -> dict[str, str]:
    """Ask the model to rewrite the code, using real ruff output on retries."""
    # On the first pass the code to fix is the original source; on retries it
    # is the previous fixed version that still failed the linter.
    code_to_fix = data.previous_code or data.source_code

    prompt = (
        "Rewrite the following Python file to fix ALL style/lint issues while "
        "preserving its behavior exactly. Return only the fixed code, with no "
        "explanations, no prose, and no markdown fences.\n\n"
        "Review notes:\n"
        f"{data.review_notes}\n\n"
    )
    if data.ruff_output:
        prompt += (
            "Exact ruff output from the previous attempt:\n"
            f"{data.ruff_output}\n\n"
        )
    prompt += "Current code:\n" + code_to_fix

    fixed_code = call_deepseek(prompt)
    return {"fixed_code": fixed_code, "review_notes": data.review_notes}


def run_linter(data: FixOutput) -> dict[str, str] | Goto:
    """Run the real ``ruff check`` linter and loop back to fixing if needed."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(data.fixed_code)
        temp_path = Path(handle.name)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", str(temp_path)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_DIR),
        )
        output = (result.stdout + result.stderr).strip()
    finally:
        temp_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return Goto(
            "fix_issues",
            {
                "review_notes": data.review_notes,
                "previous_code": data.fixed_code,
                "ruff_output": output,
            },
        )

    return {"fixed_code": data.fixed_code, "lint_result": "clean"}


def apply_fix(data: LintOutput) -> dict[str, bool]:
    """Overwrite ``sample_code.py`` with the approved, lint-clean version."""
    SAMPLE_CODE_PATH.write_text(data.fixed_code, encoding="utf-8")
    return {"applied": True}
