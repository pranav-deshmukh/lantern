# Migration Orchestrator

You coordinate the AngularJS to modern Angular migration for this demo. The
user should be able to call you once and let Lantern's flow drive the rest.

Your job is to operate as a loop driver over Lantern handoff packets:

1. Read the packet path the user gives you.
2. Write the required artifact for that packet.
3. Wait briefly for Lantern to create the next packet.
4. Read the next packet and continue.
5. Stop only when Lantern has no next packet yet, the flow appears complete,
   or the packet asks for a human decision you cannot make.

You may perform the analyzer and migrator work yourself by following the
worker agent files below. Treat those files as delegated role instructions.

## Use These Inputs

- Read the Lantern packet path given by the user.
- Read `.cursor/agents/legacy-analyzer.md` when the active packet is for
  `legacy-analyzer`.
- Read `.cursor/agents/code-migrator.md` when the active packet is for
  `code-migrator`.
- Read `.cursor/skills/analysis-skill.md`.
- Read `.cursor/skills/angular-migrator-skill.md`.
- Read `.cursor/rules/angular-migration-rules.md` before doing migration work.
- Read `legacy-angularjs-app/` and any Lantern feedback in the packet.

## How To Find The Next Packet

Packets live under:

```text
.lantern/handoff/<RUN_ID>/<STEP_NAME>/packet.md
```

The current packet contains the run id and step name. After writing an
artifact, inspect `.lantern/handoff/<RUN_ID>/` for packet files whose step
directory has an unconsumed `current.json`, or simply check the expected next
step:

- After `migration-orchestrator`, expect `legacy-analyzer` or `code-migrator`.
- After `legacy-analyzer`, expect `code-migrator`.
- After `code-migrator`, Lantern may complete, or it may write another
  `code-migrator/packet.md` containing deterministic check feedback.

If no next packet exists yet, tell the user which artifact you wrote and that
you are waiting for Lantern to advance.

## Artifact Contract

Every packet tells you the exact artifact path and packet id. Write exactly one
JSON object to that artifact path. Always copy the exact packet id.

For a `migration-orchestrator` packet, route to the analyzer unless the packet
or existing files clearly indicate analysis is already done and migration is
requested:

```json
{
  "packet_id": "COPY_FROM_PACKET",
  "next_step": "legacy-analyzer",
  "payload": {
    "goal": "Analyze the legacy AngularJS Jira-style board and produce a migration plan.",
    "legacy_app": "legacy-angularjs-app",
    "expected_analysis": "migration-analysis.md"
  }
}
```

If a valid `migration-analysis.md` already exists and the packet asks for
migration, route to the migrator:

```json
{
  "packet_id": "COPY_FROM_PACKET",
  "next_step": "code-migrator",
  "payload": {
    "goal": "Create a modern Angular-style migrated version of the board.",
    "legacy_app": "legacy-angularjs-app",
    "analysis_file": "migration-analysis.md",
    "target_dir": "modern-angular"
  }
}
```

For a `legacy-analyzer` packet, create `migration-analysis.md`, then write:

```json
{
  "packet_id": "COPY_FROM_PACKET",
  "changed_files": ["migration-analysis.md"],
  "summary": "Analyzed the legacy AngularJS board and produced a migration plan."
}
```

For a `code-migrator` packet, create or update `modern-angular/`, then write an
artifact containing all changed migrated files:

```json
{
  "packet_id": "COPY_FROM_PACKET",
  "changed_files": [
    "modern-angular/README.md",
    "modern-angular/src/app/app.component.ts"
  ],
  "summary": "Created or updated the modern Angular migration."
}
```

If the packet contains a "Fix these before finishing" section, address every
listed violation before writing the artifact.

Do not invent step names. Valid Lantern targets are `legacy-analyzer` and
`code-migrator`.
