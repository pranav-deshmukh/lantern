# Analysis Skill

Use this skill when inspecting the legacy AngularJS board before migration.

## Analysis Checklist

- Identify all AngularJS entry points and dependency injection names.
- Trace data flow from `data/board.json` through services, controllers,
  directives, filters, and templates.
- List user workflows: filtering, moving issues, selecting issue detail,
  editing checklist progress, saving notes, and backlog promotion.
- Identify framework-specific risks, including digest cycle assumptions,
  two-way binding, directive isolate scopes, inline templates, and global
  browser APIs.
- Identify domain risks, including workflow transition rules and status values
  that do not appear as lanes.
- Propose a target component/service model for modern Angular.
- Recommend a migration sequence that can be verified after each step.

## Report Style

- Write the report as markdown.
- Use concrete file references.
- Keep findings actionable.
- Do not claim the migration is complete.
