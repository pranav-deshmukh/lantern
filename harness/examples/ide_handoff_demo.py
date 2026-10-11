"""Manual IDE handoff demo.

Run this file, open the printed packet, then write the requested artifact JSON
by hand to watch deterministic checks either pass or loop back with feedback.
"""

from __future__ import annotations

from pathlib import Path

from harness import Flow, Runtime, Step
from harness.ide_handoff import (
    IdeHandoffConfig,
    PatternRule,
    make_ide_handoff_step,
    make_pattern_check_step,
    new_run_id,
)


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = new_run_id()


def main() -> None:
    config = IdeHandoffConfig(
        workspace=ROOT,
        run_id=RUN_ID,
        invoke_hint="@migration-orchestrator prepare the requested migration",
    )
    handoff = make_ide_handoff_step("ide_work", config)
    check = make_pattern_check_step(
        [
            PatternRule(
                "no-todo",
                r"TODO",
                "forbid",
                "*.md",
                "Example convention: remove TODO markers before finishing.",
            ),
            PatternRule(
                "has-rollback",
                r"rollback",
                "require",
                "*.md",
                "Example convention: document a rollback plan.",
            ),
        ],
        base_dir=ROOT,
        retry_target="ide_work",
    )
    flow = Flow(
        [
            Step(
                "ide_work",
                handoff,
                rules_files=[
                    str(ROOT / "examples" / "context_bundling" / "migration-rules.md")
                ],
                skills_files=[
                    str(ROOT / "examples" / "context_bundling" / "migration-skills.md")
                ],
            ),
            Step("pattern_check", check),
        ]
    )
    runtime = Runtime(
        checkpoint_path=ROOT / ".lantern" / "ide_handoff_demo.checkpoint.json",
        run_id=RUN_ID,
        retry_delay=0,
    )
    print(runtime.run(flow, {"request": "Draft a migration note in a markdown file."}))


if __name__ == "__main__":
    main()
