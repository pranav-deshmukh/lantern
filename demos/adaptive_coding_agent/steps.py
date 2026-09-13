"""Init-flow steps and demo-local contracts for the adaptive coding agent."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

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
