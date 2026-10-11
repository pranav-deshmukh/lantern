"""Markdown packet composition for file-based IDE handoff steps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.context import ExecutionContext


def compose_ide_packet(
    task: Any,
    context: ExecutionContext | None = None,
    *,
    step_name: str,
    run_id: str,
    packet_id: str,
    artifact_path: str | Path,
    extra_instructions: str | None = None,
    invoke_hint: str | None = None,
    feedback: str | None = None,
) -> str:
    """Return the markdown instructions handed to a human-driven IDE agent."""
    artifact_text = str(artifact_path)
    task_text = task if isinstance(task, str) else json.dumps(task, indent=2, default=str)
    sections = [
        "# Lantern IDE Handoff",
        "",
        f"Step name: {step_name}",
        f"Run id: {run_id}",
        f"Packet id: {packet_id}",
    ]
    if invoke_hint:
        sections.extend(["", "## Invoke Hint", invoke_hint])
    sections.extend(
        [
            "",
            "## Artifact",
            f"Write the result as a single JSON OBJECT to this exact path: `{artifact_text}`",
            f'Include `"packet_id": "{packet_id}"` in that object.',
            'If you edited files, include `"changed_files"` as a list of workspace-relative paths.',
        ]
    )
    if context is not None and context.as_text():
        sections.extend(["", "## Bundled Rules and Skills", context.as_text()])
    if extra_instructions:
        sections.extend(["", "## Extra Instructions", extra_instructions])
    if feedback:
        sections.extend(["", "## Fix these before finishing", feedback])
    sections.extend(["", "## Task", task_text])
    return "\n".join(sections) + "\n"
