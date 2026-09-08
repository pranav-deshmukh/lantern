"""Agent Context Bundling: mechanical injection plus auditability.

Lantern guarantees that a step's declared context files were actually read and
delivered to the agent, and records exactly what was delivered (file paths plus
SHA-256 hashes) in the trace. It does NOT guarantee that the agent complied with
the content of those files — that is the agent/prompt's responsibility. Nothing
in this module implies rule-following enforcement.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class MissingContextFileError(FileNotFoundError):
    """Raised when a declared context file cannot be found."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Context file not found: {path}")


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
