"""Shared step functions used by the example flow YAML files."""

from __future__ import annotations

from typing import Any

# Migration-style flow steps


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "table": data.get("table", "users"),
        "compatibility": "ok",
        "risk": "low",
    }


def plan(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "steps": ["create_index", "backfill", "validate"],
    }


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "migrated_rows": data.get("rows", 0),
    }


def verify(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "status": "verified",
        "verified_rows": data.get("migrated_rows", 0),
    }


# PR-review-style flow steps


def read_diff(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "files": data.get("files", ["main.py", "README.md"]),
        "lines_changed": data.get("lines_changed", 42),
    }


def review(data: dict[str, Any]) -> dict[str, Any]:
    files = data.get("files", [])
    comments = [
        {"file": file_name, "line": 1, "body": "Looks good"}
        for file_name in files
    ]
    return {**data, "comments": comments}


def comment(data: dict[str, Any]) -> dict[str, Any]:
    files = data.get("files", [])
    comments = data.get("comments", [])
    return {
        "summary": (
            f"Reviewed {len(files)} file(s) and posted "
            f"{len(comments)} comment(s)."
        ),
    }
