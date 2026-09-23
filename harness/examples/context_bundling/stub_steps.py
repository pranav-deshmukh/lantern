"""Stub step function for the context bundling example."""

from __future__ import annotations


def echo_context(data: dict, context=None) -> dict:
    """Report which context files were delivered to this execution."""
    text = context.as_text() if context is not None else ""
    received_files = [
        name
        for name in ("migration-rules.md", "migration-skills.md")
        if name in text
    ]
    return {
        "received_files": received_files,
        "context_length": len(text),
    }
