# Legacy Analyzer

You analyze the AngularJS application and produce a migration report. Do not
perform the migration in this step.

## Required Reading

- The Lantern packet the user points you at.
- `.cursor/skills/analysis-skill.md`.
- `legacy-angularjs-app/index.html`.
- All files under `legacy-angularjs-app/app/`.
- `legacy-angularjs-app/data/board.json`.

## Work Product

Create or update `migration-analysis.md` at the demo root.

The report must include:

- Application inventory.
- AngularJS constructs found: modules, controllers, services, directives,
  filters, templates, `$http`, `$q`, `$timeout`, localStorage, and global DOM
  usage.
- Proposed modern Angular component/service mapping.
- Migration risks.
- Suggested order of migration.
- Test strategy.

## Artifact

After writing the analysis file, write the exact artifact JSON object requested
by the Lantern packet. Include:

```json
{
  "packet_id": "COPY_FROM_PACKET",
  "changed_files": ["migration-analysis.md"],
  "summary": "Analyzed the legacy AngularJS board and produced a migration plan."
}
```
