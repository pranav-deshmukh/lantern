# Angular Code Migration Cursor Demo

This demo uses Lantern's opt-in IDE handoff path to coordinate a manual Cursor
migration of a legacy AngularJS Jira-style board.

## What Is In Here

- `legacy-angularjs-app/`: a static AngularJS 1.x board with controllers,
  services, directives, filters, mock data, localStorage, and workflow logic.
- `flow.yaml`: human-readable flow wiring for the Cursor migration.
- `.cursor/agents/`: Cursor agent instruction files:
  - `migration-orchestrator.md`
  - `legacy-analyzer.md`
  - `code-migrator.md`
- `.cursor/skills/`: reusable skill files:
  - `analysis-skill.md`
  - `angular-migrator-skill.md`
- `.cursor/rules/angular-migration-rules.md`: rules for the migrator.
- `run_cursor_migration_flow.py`: Lantern flow runner.

The executable flow is built in `run_cursor_migration_flow.py`, specifically
inside `build_flow()`. `flow.yaml` mirrors that wiring for review: which agent,
skills, rules, transitions, and deterministic checks belong to each step. The
current Lantern YAML loader does not yet instantiate IDE handoff steps directly,
so the Python runner is the source of execution.

## How To Test With Cursor

Open this folder in Cursor:

```bash
cd demos/angular_code_migration
```

## Run The Legacy App

The legacy app is intentionally a plain AngularJS 1.x static app. Do not open
`index.html` directly, because the app loads `data/board.json` over HTTP.
Serve it with Python instead:

```bash
python demos/angular_code_migration/run_legacy_app.py
```

Then open:

```text
http://127.0.0.1:8765/
```

No npm install or Angular CLI install is needed for the legacy app. It loads
AngularJS 1.7.9 from Google's CDN, so you do need internet access unless you
replace that CDN script with a local AngularJS file.

## Run The Migrated App

The migrated app does not exist until the Cursor `code-migrator` step creates
`modern-angular/`.

After the migration flow completes, run:

```bash
cd demos/angular_code_migration/modern-angular
npm install
npm start
```

Then open:

```text
http://127.0.0.1:4200/
```

If `modern-angular/package.json` is missing, the migrator did not create a
runnable Angular project. Re-run the `code-migrator` packet and tell it to
follow `.cursor/agents/code-migrator.md` exactly.

## Run The Lantern Migration Flow

In a terminal from the repository root, start a fresh Lantern run:

```bash
python demos/angular_code_migration/run_cursor_migration_flow.py --fresh --run-id cursor-demo
```

Lantern will print a packet path and wait for `artifact.json`.

In Cursor, call the orchestrator once:

```text
@migration-orchestrator read .lantern/handoff/cursor-demo/migration-orchestrator/packet.md and drive the Lantern flow until it completes. Use the worker agent files in .cursor/agents when the flow advances to legacy-analyzer or code-migrator. Only stop if you need a human decision or if Lantern has not produced the next packet yet.
```

That is the intended test. The orchestrator should keep reading the next
Lantern packet and writing the next artifact as the flow advances.

See `CALL_ORCHESTRATOR.md` for the same prompt in copy-friendly form.

## Debugging Packet By Packet

If Cursor stops or you want to inspect each step manually, you can drive the
same flow one packet at a time.

For the first packet:

1. Open the printed `packet.md`.
2. In Cursor chat, call the orchestrator agent, for example:

   ```text
   @migration-orchestrator read .lantern/handoff/<RUN_ID>/migration-orchestrator/packet.md and follow it exactly
   ```

3. The agent should write `artifact.json` at the exact path from the packet.
   Its `next_step` should usually be `legacy-analyzer`.

Lantern then prints the analyzer packet.

For the analyzer packet:

```text
@legacy-analyzer read .lantern/handoff/<RUN_ID>/legacy-analyzer/packet.md and follow it exactly
```

That should create `migration-analysis.md` and write the analyzer artifact.

Lantern then prints the migrator packet.

For the migrator packet:

```text
@code-migrator read .lantern/handoff/<RUN_ID>/code-migrator/packet.md and follow it exactly
```

That should create `modern-angular/` and write the migrator artifact.

## What Lantern Checks

The deterministic check step scans the migrator's `changed_files`.

It sends work back to `code-migrator` if migrated files contain AngularJS API
patterns such as `angular.module`, `ng-controller`, `$scope`, `$http`, `$q`, or
`$timeout`.

It also requires `modern-angular/README.md` to mention Angular CLI wiring.

If a check fails, Lantern writes a new `code-migrator/packet.md` containing
the exact violation text. Call the code migrator agent again with that packet.

## Artifact Rules

Every Cursor-produced artifact must be a single JSON object and must include
the exact `packet_id` from the packet.

Example:

```json
{
  "packet_id": "copy-the-packet-id",
  "changed_files": ["migration-analysis.md"],
  "summary": "Created the analysis report."
}
```

If Cursor omits `packet_id`, Lantern fails loudly. If Cursor uses an old
`packet_id`, Lantern treats the artifact as stale and keeps waiting.
