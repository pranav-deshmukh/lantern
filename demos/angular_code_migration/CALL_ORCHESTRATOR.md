# Cursor Prompt: Start Migration

Open `demos/angular_code_migration` as the Cursor workspace.

In a normal terminal, start Lantern from the repository root:

```bash
python demos/angular_code_migration/run_cursor_migration_flow.py --fresh --run-id cursor-demo
```

Leave that terminal running. It will print the first packet path:

```text
.lantern/handoff/cursor-demo/migration-orchestrator/packet.md
```

Then in Cursor chat, send one message:

```text
@migration-orchestrator read .lantern/handoff/cursor-demo/migration-orchestrator/packet.md and drive the Lantern flow until it completes. Use the worker agent files in .cursor/agents when the flow advances to legacy-analyzer or code-migrator. Only stop if you need a human decision or if Lantern has not produced the next packet yet.
```

Expected behavior:

1. The orchestrator writes the first artifact to route the flow.
2. Lantern advances to `legacy-analyzer`.
3. The orchestrator reads the analyzer packet, follows
   `.cursor/agents/legacy-analyzer.md`, creates `migration-analysis.md`, and
   writes the analyzer artifact.
4. Lantern advances to `code-migrator`.
5. The orchestrator reads the migrator packet, follows
   `.cursor/agents/code-migrator.md`, creates `modern-angular/`, and writes the
   migrator artifact.
6. Lantern runs deterministic checks. If there are violations, it writes a new
   `code-migrator` packet with exact feedback. The orchestrator should fix and
   continue.
