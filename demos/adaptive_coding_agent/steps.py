"""Init-flow steps and demo-local contracts for the adaptive coding agent."""

from __future__ import annotations

import json
import shutil
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from harness import Goto, PolicyDecision, PolicyEngine, PolicyViolation
from harness.contracts import Contract, validate_value
from harness.llm_step import call_deepseek


PROJECT_DIR = Path(__file__).resolve().parent
SAMPLE_REPO_PATH = PROJECT_DIR / "sample_repo"
PROFILE_PATH = PROJECT_DIR / "project-profile.json"
SOURCE_SUFFIXES = {".py", ".toml"}


class InitInput(BaseModel):
    repo_path: str


class ScanOutput(BaseModel):
    repo_path: str
    scan_summary: str


class ClarifyingOutput(BaseModel):
    repo_path: str
    scan_summary: str
    questions_and_answers: dict[str, str]


class ProjectProfile(BaseModel):
    stack: str
    dependencies: list[str] = Field(default_factory=list)
    test_command: str
    lint_command: str
    conventions: list[str] = Field(default_factory=list)


SCAN_CONTRACT = Contract(InitInput, ScanOutput)
CLARIFY_CONTRACT = Contract(ScanOutput, ClarifyingOutput)
PROFILE_CONTRACT = Contract(ClarifyingOutput, ProjectProfile)


class StoryInput(BaseModel):
    project_profile: ProjectProfile
    story: str


class PlanOutput(BaseModel):
    project_profile: ProjectProfile
    story: str
    plan: str
    target_file: str


class CodeInput(PlanOutput):
    previous_code: str = ""
    failure_feedback: str = ""


class CodeOutput(BaseModel):
    project_profile: ProjectProfile
    story: str
    plan: str
    target_file: str
    new_code: str
    temp_repo_path: str


class GateOutput(CodeOutput):
    parity_output: str = ""
    generated_test: str = ""
    test_output: str = ""
    lint_output: str = ""


class ReviewOutput(GateOutput):
    review_summary: str


class ApplyOutput(BaseModel):
    applied: bool
    target_file: str


PLAN_CONTRACT = Contract(StoryInput, CodeInput)
CODE_CONTRACT = Contract(CodeInput, CodeOutput)
PARITY_CONTRACT = Contract(CodeOutput, GateOutput | CodeInput)
RUN_TESTS_CONTRACT = Contract(GateOutput, GateOutput | CodeInput)
QUALITY_CONTRACT = Contract(GateOutput, GateOutput | CodeInput)
REVIEW_CONTRACT = Contract(GateOutput, ReviewOutput)
APPLY_CONTRACT = Contract(ReviewOutput, ApplyOutput)


def scan_project(data: InitInput) -> dict[str, str]:
    """Summarize repository structure and local conventions with an LLM."""
    repo_path = Path(data.repo_path).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise ValueError(f"repo_path must be an existing directory: {repo_path}")

    file_listing = _project_file_listing(repo_path)
    pyproject_path = repo_path / "pyproject.toml"
    pyproject_text = (
        pyproject_path.read_text(encoding="utf-8")
        if pyproject_path.exists()
        else "(no pyproject.toml found)"
    )
    source_samples = _source_samples(repo_path)

    prompt = (
        "You are scanning a Python project to create reusable context for a "
        "future coding agent. Summarize the detected stack/framework, "
        "dependencies, apparent test command, apparent lint command, and "
        "coding conventions such as type-hint and docstring usage. Keep the "
        "answer concise but structured.\n\n"
        f"Repository path:\n{repo_path}\n\n"
        f"File listing:\n{file_listing}\n\n"
        f"pyproject.toml:\n{pyproject_text}\n\n"
        f"First lines of source/config files:\n{source_samples}"
    )
    return {"repo_path": str(repo_path), "scan_summary": call_deepseek(prompt)}


def ask_clarifying_questions(
    data: ScanOutput,
    answer_callback: Callable[[list[str]], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Ask short follow-up questions and collect human answers."""
    prompt = (
        "Based on this project scan, generate 2-4 short clarifying questions "
        "about coding conventions or commands that are ambiguous or not "
        "inferable. Return one question per line, with no numbering if possible."
        "\n\n"
        f"{data.scan_summary}"
    )
    questions = _parse_questions(call_deepseek(prompt))
    callback = answer_callback or _prompt_for_answers
    answers = callback(questions)
    return {
        "repo_path": data.repo_path,
        "scan_summary": data.scan_summary,
        "questions_and_answers": answers,
    }


def write_project_profile(data: ClarifyingOutput) -> dict[str, Any]:
    """Build, validate, and persist the reusable project profile JSON."""
    prompt = (
        "Create the final project profile as JSON only. It must match exactly "
        "this shape: "
        '{"stack": str, "dependencies": list[str], "test_command": str, '
        '"lint_command": str, "conventions": list[str]}.\n\n'
        "Project scan:\n"
        f"{data.scan_summary}\n\n"
        "Clarifying questions and answers:\n"
        f"{json.dumps(data.questions_and_answers, indent=2)}"
    )
    profile_data = _loads_json_object(call_deepseek(prompt))
    profile = validate_value(
        profile_data,
        ProjectProfile,
        step_name="write_project_profile",
        direction="output",
    )

    PROFILE_PATH.write_text(
        json.dumps(profile.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )
    return profile.model_dump()


def plan(data: StoryInput) -> dict[str, Any]:
    """Ask the LLM for a short implementation plan and target file."""
    prompt = (
        "Create a concise implementation plan for this story using the project "
        "profile. Return JSON only with keys: plan and target_file. target_file "
        "must be a relative path inside the repo.\n\n"
        f"Story:\n{data.story}\n\n"
        f"Project profile:\n{data.project_profile.model_dump_json(indent=2)}"
    )
    response = _loads_json_object(call_deepseek(prompt))
    target_file = str(response.get("target_file", "")).strip()
    if not target_file:
        raise ValueError("plan response must include target_file.")
    _safe_repo_relative_path(target_file)
    return {
        "project_profile": data.project_profile.model_dump(),
        "story": data.story,
        "plan": str(response.get("plan", "")).strip(),
        "target_file": target_file,
    }


def code(data: CodeInput) -> dict[str, Any]:
    """Write the proposed target file to a fresh temporary copy of sample_repo."""
    source_path = SAMPLE_REPO_PATH / _safe_repo_relative_path(data.target_file)
    if not source_path.exists():
        raise ValueError(f"target_file does not exist in sample_repo: {data.target_file}")

    current_code = source_path.read_text(encoding="utf-8")
    prompt = (
        "Return the FULL new contents of the target file only. Do not include "
        "markdown fences or explanations. Implement the story according to the "
        "plan and project conventions.\n\n"
        f"Story:\n{data.story}\n\n"
        f"Plan:\n{data.plan}\n\n"
        f"Target file:\n{data.target_file}\n\n"
        f"Project profile:\n{data.project_profile.model_dump_json(indent=2)}\n\n"
        f"Current code:\n{current_code}"
    )
    if data.failure_feedback:
        prompt += (
            "\n\nThe previous attempt failed a real execution gate. Use this "
            "exact feedback to fix the code:\n"
            f"{data.failure_feedback}\n\n"
            f"Previous attempted code:\n{data.previous_code}"
        )

    new_code = _strip_markdown_code_fence(call_deepseek(prompt))
    temp_repo_path = Path(tempfile.mkdtemp(prefix="lantern-story-"))
    shutil.copytree(
        SAMPLE_REPO_PATH,
        temp_repo_path,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".pytest_cache", "__pycache__", ".ruff_cache", ".git"
        ),
    )
    target_path = temp_repo_path / _safe_repo_relative_path(data.target_file)
    target_path.write_text(new_code, encoding="utf-8")

    return {
        "project_profile": data.project_profile.model_dump(),
        "story": data.story,
        "plan": data.plan,
        "target_file": data.target_file,
        "new_code": new_code,
        "temp_repo_path": str(temp_repo_path),
    }


def parity_check(data: CodeOutput) -> dict[str, Any] | Goto:
    """Run the existing test suite against the temp repo."""
    result = _run_project_command(data.project_profile.test_command, data.temp_repo_path)
    output = _completed_output(result)
    if result.returncode != 0:
        return _retry_code(data, output)
    gate_data = data.model_dump()
    gate_data["parity_output"] = output or "Existing tests passed."
    return gate_data


def run_tests(data: GateOutput) -> dict[str, Any] | Goto:
    """Generate and run a new story-specific test against the temp repo."""
    prompt = (
        "Generate exactly one pytest test function for this story. Return only "
        "Python code. It will be appended to tests/test_agent_story.py.\n\n"
        f"Story:\n{data.story}\n\n"
        f"Target file:\n{data.target_file}\n\n"
        f"New code:\n{data.new_code}"
    )
    generated_test = _strip_markdown_code_fence(call_deepseek(prompt))
    test_path = Path(data.temp_repo_path) / "tests" / "test_agent_story.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(generated_test.rstrip() + "\n", encoding="utf-8")

    result = _run_project_command(data.project_profile.test_command, data.temp_repo_path)
    output = _completed_output(result)
    if result.returncode != 0:
        return _retry_code(data, output)

    gate_data = data.model_dump()
    gate_data["generated_test"] = generated_test
    gate_data["test_output"] = output or "Generated story test passed."
    return gate_data


def quality_gate(data: GateOutput) -> dict[str, Any] | Goto:
    """Run the configured lint command against the temp repo."""
    result = _run_project_command(data.project_profile.lint_command, data.temp_repo_path)
    output = _completed_output(result)
    if result.returncode != 0:
        return _retry_code(data, output)
    gate_data = data.model_dump()
    gate_data["lint_output"] = output or "Quality gate passed."
    return gate_data


def review(data: GateOutput) -> dict[str, Any]:
    """Ask for a short human-readable review of the accepted temp change."""
    prompt = (
        "Write a short review summary of this final change. Include what "
        "changed, why, and confirm existing tests, generated story test, and "
        "lint all passed.\n\n"
        f"Story:\n{data.story}\n\n"
        f"Target file:\n{data.target_file}\n\n"
        f"Plan:\n{data.plan}"
    )
    review_data = data.model_dump()
    review_data["review_summary"] = call_deepseek(prompt)
    return review_data


def apply_change(
    data: ReviewOutput,
    policy_engine: PolicyEngine,
    action: str = "apply_adaptive_code_change",
) -> dict[str, Any]:
    """Copy the approved temp-file change over the real sample repo file."""
    try:
        if policy_engine.check(action) is PolicyDecision.REQUIRES_APPROVAL:
            if not policy_engine.request_approval(action):
                raise PolicyViolation("apply_change", action)

        relative_target = _safe_repo_relative_path(data.target_file)
        source_path = Path(data.temp_repo_path) / relative_target
        destination_path = SAMPLE_REPO_PATH / relative_target
        destination_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        return {"applied": True, "target_file": data.target_file}
    finally:
        shutil.rmtree(data.temp_repo_path, ignore_errors=True)


def _project_file_listing(repo_path: Path) -> str:
    paths = [
        path.relative_to(repo_path).as_posix()
        for path in repo_path.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(repo_path).parts)
        and "__pycache__" not in path.parts
    ]
    return "\n".join(sorted(paths))


def _source_samples(repo_path: Path) -> str:
    samples: list[str] = []
    for path in sorted(repo_path.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(repo_path).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()[:20]
        numbered = "\n".join(f"{index + 1}: {line}" for index, line in enumerate(lines))
        samples.append(f"--- {relative} ---\n{numbered}")
    return "\n\n".join(samples)


def _parse_questions(text: str) -> list[str]:
    questions: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = line.lstrip("-*0123456789. )")
        if line:
            questions.append(line)
    return questions[:4]


def _prompt_for_answers(questions: list[str]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for question in questions:
        answers[question] = input(f"{question} ")
    return answers


def _loads_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f"LLM response was not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object.")
    return parsed


def _safe_repo_relative_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must stay inside sample_repo: {path_text}")
    return path


def _strip_markdown_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return cleaned.rstrip() + "\n"


def _run_project_command(command: str, cwd: str | Path) -> subprocess.CompletedProcess[str]:
    args = shlex.split(command, posix=False)
    if args and args[0] == "python":
        args[0] = sys.executable
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        shell=False,
    )


def _completed_output(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout + result.stderr).strip()
    return output or f"Command exited with status {result.returncode}."


def _retry_code(data: CodeOutput | GateOutput, failure_feedback: str) -> Goto:
    shutil.rmtree(data.temp_repo_path, ignore_errors=True)
    return Goto(
        "code",
        {
            "project_profile": data.project_profile.model_dump(),
            "story": data.story,
            "plan": data.plan,
            "target_file": data.target_file,
            "previous_code": data.new_code,
            "failure_feedback": failure_feedback,
        },
    )
