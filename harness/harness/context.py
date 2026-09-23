"""Agent Context Bundling: mechanical injection plus auditability.

Lantern guarantees that a step's declared context files were actually read,
delivered to any function that opts in via a ``context`` parameter, and
recorded in the trace (file paths plus SHA-256 hashes). It does NOT guarantee
that the agent complied with the content of those files — that is the
agent/prompt's responsibility. Nothing in this module implies rule-following
enforcement.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class MissingContextFileError(FileNotFoundError):
    """Raised when a declared context file cannot be found."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Context file not found: {path}")


@dataclass(frozen=True)
class ExecutionContext:
    """Execution metadata that is separate from a step's user input.

    The harness owns this object and passes it to a function only when that
    function explicitly opts in by declaring a ``context`` parameter. Simple
    functions and BYO agents never see it. New kinds of context (memory,
    experience, trace, metadata) can be added here without changing the
    user-facing input contract.
    """

    rules: ContextBundle | None = None
    skills: ContextBundle | None = None
    memory: ContextBundle | None = None
    experience: ContextBundle | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_text(self) -> str:
        """Concatenate all available context files into one string."""
        sections: list[str] = []
        for bundle in (self.rules, self.skills, self.memory, self.experience):
            if bundle is not None:
                sections.append(bundle.as_text())
        return "\n\n".join(sections)

    def audit_entries(self) -> list[dict[str, str]]:
        """Return the combined ``(path, hash)`` entries for tracing."""
        entries: list[dict[str, str]] = []
        for bundle in (self.rules, self.skills, self.memory, self.experience):
            if bundle is not None:
                entries.extend(bundle.audit_entries())
        return entries


@dataclass(frozen=True)
class ContextBundle:
    """The contents and hashes of a set of context files.

    ``files`` is a list of ``(file_path, content, content_hash)`` tuples. The
    hash is the SHA-256 hex digest of the UTF-8 encoded file content.
    """

    files: list[tuple[str, str, str]]

    def as_text(self) -> str:
        """Concatenate all files with clear per-file separators."""
        return "\n\n".join(
            f"--- {file_path} ---\n{content}"
            for file_path, content, _ in self.files
        )

    def audit_entries(self) -> list[dict[str, str]]:
        """Return ``(path, hash)`` pairs for trace auditability."""
        return [
            {"path": file_path, "hash": content_hash}
            for file_path, _, content_hash in self.files
        ]


def load_context_files(paths: list[str]) -> ContextBundle:
    """Read each file and compute its SHA-256 hash.

    Raises :class:`MissingContextFileError` naming the exact path if any file
    does not exist.
    """
    files: list[tuple[str, str, str]] = []
    for path_str in paths:
        path = Path(path_str)
        if not path.is_file():
            raise MissingContextFileError(path_str)
        content = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        files.append((path_str, content, content_hash))
    return ContextBundle(files)
