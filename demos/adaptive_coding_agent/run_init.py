"""Build and run the adaptive coding agent one-time init flow."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from functools import partial

from harness import Flow, Runtime, Step
from harness.trace_viewer import print_trace

from steps import (
    CLARIFY_CONTRACT,
    PROFILE_CONTRACT,
    SCAN_CONTRACT,
    PROFILE_PATH,
    SAMPLE_REPO_PATH,
    ask_clarifying_questions,
    scan_project,
    write_project_profile,
)


def build_flow(
    answer_callback: Callable[[list[str]], dict[str, str]] | None = None,
) -> Flow:
    """Assemble scan -> clarify -> write-profile for the init workflow."""
    clarify_step = (
        ask_clarifying_questions
        if answer_callback is None
        else partial(ask_clarifying_questions, answer_callback=answer_callback)
    )

    return Flow(
        [
            Step("scan_project", scan_project, contract=SCAN_CONTRACT),
            Step(
                "ask_clarifying_questions",
                clarify_step,
                contract=CLARIFY_CONTRACT,
            ),
            Step(
                "write_project_profile",
                write_project_profile,
                contract=PROFILE_CONTRACT,
            ),
        ]
    )


def main() -> None:
    trace_path = Path(__file__).with_name("init_trace.jsonl")
    checkpoint_path = Path(__file__).with_name(".init_checkpoint.json")

    runtime = Runtime(
        trace_path=trace_path,
        checkpoint_path=checkpoint_path,
        max_retries=0,
        retry_delay=0,
    )
    result = runtime.run(build_flow(), {"repo_path": str(SAMPLE_REPO_PATH)})

    print(f"Wrote {PROFILE_PATH}")
    print("Result:", result.model_dump() if hasattr(result, "model_dump") else result)
    print()
    print_trace(trace_path)


if __name__ == "__main__":
    main()
