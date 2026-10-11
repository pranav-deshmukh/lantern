"""Run the manual Cursor-driven Angular migration flow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))

from harness import Flow, Runtime, Step  # noqa: E402
from harness.ide_handoff import (  # noqa: E402
    IdeHandoffConfig,
    PatternRule,
    make_ide_handoff_step,
    make_orchestrator_step,
    make_pattern_check_step,
    new_run_id,
)


DEMO_ROOT = Path(__file__).resolve().parent
CURSOR = DEMO_ROOT / ".cursor"


def build_flow(run_id: str) -> Flow:
    orchestrator_config = IdeHandoffConfig(
        workspace=DEMO_ROOT,
        run_id=run_id,
        invoke_hint="@migration-orchestrator read the packet and choose the next Lantern step",
    )
    analyzer_config = IdeHandoffConfig(
        workspace=DEMO_ROOT,
        run_id=run_id,
        invoke_hint="@legacy-analyzer analyze the AngularJS app and write the artifact",
    )
    migrator_config = IdeHandoffConfig(
        workspace=DEMO_ROOT,
        run_id=run_id,
        invoke_hint="@code-migrator migrate the app and write the artifact",
    )

    orchestrator = make_orchestrator_step(
        "migration-orchestrator",
        orchestrator_config,
        {"legacy-analyzer", "code-migrator"},
    )
    analyzer = make_ide_handoff_step("legacy-analyzer", analyzer_config)
    migrator = make_ide_handoff_step("code-migrator", migrator_config)
    check = make_pattern_check_step(
        [
            PatternRule(
                "no-angularjs-api",
                r"angular\.module|ng-controller|\$scope|\$http|\$q|\$timeout",
                "forbid",
                "modern-angular/**",
                "Migrated files must not use AngularJS APIs.",
            ),
            PatternRule(
                "readme-documents-cli-wiring",
                r"Angular CLI|CLI",
                "require",
                "modern-angular/README.md",
                "README must explain how this maps into a real Angular CLI project.",
            ),
        ],
        base_dir=DEMO_ROOT,
        retry_target="code-migrator",
    )

    return Flow(
        [
            Step(
                "migration-orchestrator",
                orchestrator,
                skills_files=[
                    str(CURSOR / "skills" / "analysis-skill.md"),
                    str(CURSOR / "skills" / "angular-migrator-skill.md"),
                ],
            ),
            Step(
                "legacy-analyzer",
                analyzer,
                skills_files=[str(CURSOR / "skills" / "analysis-skill.md")],
            ),
            Step(
                "code-migrator",
                migrator,
                rules_files=[str(CURSOR / "rules" / "angular-migration-rules.md")],
                skills_files=[str(CURSOR / "skills" / "angular-migrator-skill.md")],
            ),
            Step("deterministic-migration-check", check),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=new_run_id())
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    checkpoint = DEMO_ROOT / ".lantern" / "cursor-migration.checkpoint.json"
    if args.fresh and checkpoint.exists():
        checkpoint.unlink()

    print(f"Demo root: {DEMO_ROOT}")
    print(f"Run id: {args.run_id}")
    print("Open this folder in Cursor, then follow each packet as Lantern prints it.")

    runtime = Runtime(
        checkpoint_path=checkpoint,
        trace_path=DEMO_ROOT / ".lantern" / "cursor-migration.trace.jsonl",
        run_id=args.run_id,
        retry_delay=0,
        max_jumps=10,
    )
    result = runtime.run(
        build_flow(args.run_id),
        {
            "goal": "Migrate the legacy AngularJS Jira-style board to a modern Angular-style codebase.",
            "legacy_app": "legacy-angularjs-app",
            "cursor_agents": [
                ".cursor/agents/migration-orchestrator.md",
                ".cursor/agents/legacy-analyzer.md",
                ".cursor/agents/code-migrator.md",
            ],
            "target_dir": "modern-angular",
        },
    )
    print("Flow completed.")
    print(result)


if __name__ == "__main__":
    main()
