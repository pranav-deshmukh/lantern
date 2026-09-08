"""Stub step function for the context bundling example."""

from __future__ import annotations


def echo_context(data: dict) -> dict:
    """Report which context files were injected into this step's input."""
    context = data.get("context", "")
    received_files = [
        name
        for name in ("migration-rules.md", "migration-skills.md")
        if name in context
    ]
    return {
        "received_files": received_files,
        "context_length": len(context),
    }
