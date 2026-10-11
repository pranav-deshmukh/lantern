"""Deterministic file-pattern checks for IDE handoff outputs."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.routing import Goto


@dataclass(frozen=True)
class PatternRule:
    """A regex rule applied to matching workspace-relative POSIX paths.

    A ``require`` rule only checks files matched by ``glob``. If no files match
    a rule's glob, that rule produces no violation.
    """

    name: str
    pattern: str
    mode: str
    glob: str
    message: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"forbid", "require"}:
            raise ValueError("PatternRule mode must be 'forbid' or 'require'.")
        re.compile(self.pattern)


def make_pattern_check_step(
    rules: Iterable[PatternRule],
    *,
    base_dir: str | Path,
    retry_target: str,
    files_key: str = "changed_files",
    files_provider: Callable[[dict[str, Any]], Iterable[str]] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any] | Goto]:
    """Return a deterministic verifier step.

    By default it reads the handoff artifact's self-reported file list, which
    can omit files. ``files_provider`` lets callers supply a trusted list such
    as a git diff.
    """
    rule_list = list(rules)
    root = Path(base_dir)

    def check(artifact: dict[str, Any]) -> dict[str, Any] | Goto:
        file_names = (
            list(files_provider(artifact))
            if files_provider is not None
            else list(artifact.get(files_key, []))
        )
        violations: list[dict[str, Any]] = []
        for rule in rule_list:
            matched = [name for name in file_names if fnmatch.fnmatch(_posix(name), rule.glob)]
            for name in matched:
                path = root / Path(name)
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError as error:
                    violations.append(
                        {
                            "file": _posix(name),
                            "rule": rule.name,
                            "message": rule.message or f"Could not read file: {error}",
                        }
                    )
                    continue

                regex = re.compile(rule.pattern)
                if rule.mode == "forbid":
                    for line_number, line in enumerate(text.splitlines(), start=1):
                        for match in regex.finditer(line):
                            violations.append(
                                {
                                    "file": _posix(name),
                                    "line": line_number,
                                    "rule": rule.name,
                                    "matched": match.group(0),
                                    "message": rule.message,
                                }
                            )
                elif regex.search(text) is None:
                    violations.append(
                        {
                            "file": _posix(name),
                            "rule": rule.name,
                            "message": rule.message,
                        }
                    )

        if not violations:
            return artifact

        feedback = _format_feedback(violations)
        original_task = None
        handoff = artifact.get("handoff")
        if isinstance(handoff, dict) and "original_task" in handoff:
            original_task = handoff["original_task"]
        return Goto(
            retry_target,
            {"task": original_task, "feedback": feedback, "violations": violations},
        )

    return check


def _format_feedback(violations: list[dict[str, Any]]) -> str:
    lines = ["Pattern check violations:"]
    for violation in violations:
        line = violation.get("line")
        location = violation["file"] if line is None else f"{violation['file']}:{line}"
        detail = f"{location} [{violation['rule']}]"
        if violation.get("matched") is not None:
            detail += f" matched {violation['matched']!r}"
        if violation.get("message"):
            detail += f" - {violation['message']}"
        lines.append(detail)
    return "\n".join(lines)


def _posix(path: str) -> str:
    return Path(path).as_posix()
