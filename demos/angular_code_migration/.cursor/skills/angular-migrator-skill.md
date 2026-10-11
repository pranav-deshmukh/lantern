# Angular Migrator Skill

Use this skill when converting the legacy AngularJS board to a modern
Angular-style application.

## Migration Mapping

- AngularJS module -> Angular application/module bootstrap notes.
- Controller-as view models -> component classes with explicit state.
- Directive templates -> components with `@Input` and `@Output`.
- Factories/services -> injectable services.
- Filters -> component methods, pure pipes, or service helpers.
- `$http` -> `HttpClient`-style service boundary, or a mock async service for
  this no-install demo.
- `$q`/`$timeout` -> `Promise`, `Observable`, or explicit async wrappers.
- `window.localStorage` access -> small persistence method isolated in a
  component or service.

## Expected Modernization Choices

- Define interfaces for `Project`, `BoardLane`, `Issue`, `ChecklistItem`, and
  `Member`.
- Keep board state in one board component.
- Move workflow transition rules into `WorkflowService`.
- Keep data access in `BoardApiService`.
- Preserve the four visible lanes and backlog/issue-inspector behavior where
  practical.
- Include notes in `modern-angular/README.md` explaining what remains to wire
  into a real Angular CLI project.

## Migration Output Style

- Prefer clear, reviewable files over clever abstractions.
- Keep generated files small enough for a human to inspect.
- Include comments only when they explain a migration decision.
- Use workspace-relative paths in `changed_files`.
