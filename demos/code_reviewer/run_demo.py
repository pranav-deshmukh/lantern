"""Build and run the automated code reviewer demo flow."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from harness import (
    Contract,
    Flow,
    PolicyEngine,
    PolicyRule,
    Runtime,
    Step,
)
from harness.trace_viewer import print_trace

from steps import (
    ApplyOutput,
    FixOutput,
    LintOutput,
    ReviewInput,
    ReviewOutput,
    SAMPLE_CODE_PATH,
    apply_fix,
    fix_issues,
    review,
    run_linter,
)


def build_flow(
    approval_callback: Callable[[str, str], bool] | None = None,
) -> Flow:
    """Assemble the review -> fix -> lint -> apply flow with governance."""
    policy_engine = PolicyEngine(
        [PolicyRule("apply_code_fix", "high", requires_approval=True)],
        approval_callback=approval_callback,
    )

    return Flow(
        [
            Step("review", review, contract=Contract(ReviewInput, ReviewOutput)),
            Step("fix_issues", fix_issues, contract=Contract(ReviewOutput, FixOutput)),
            Step("run_linter", run_linter, contract=Contract(FixOutput, LintOutput)),
            Step(
                "apply_fix",
                apply_fix,
                contract=Contract(LintOutput, ApplyOutput),
            ).with_governance("apply_code_fix", policy_engine),
        ]
    )


def main() -> None:
    flow = build_flow()
    trace_path = Path(__file__).with_name("code_review_trace.jsonl")

    runtime = Runtime(
        trace_path=trace_path,
        max_retries=0,  # The Goto loop handles retries; don't auto-retry paid calls.
        retry_delay=0,
    )

    source_code = SAMPLE_CODE_PATH.read_text(encoding="utf-8")
    result = runtime.run(flow, {"source_code": source_code})

    print("Result:", result.model_dump() if hasattr(result, "model_dump") else result)
    print()
    print_trace(trace_path)


if __name__ == "__main__":
    main()
