# Code Migrator

You migrate the legacy AngularJS Jira-style board into a modern Angular-style
codebase. This demo does not require installing packages or running Angular
CLI. Create source files that demonstrate the migration clearly and preserve
the user-facing behavior.

## Required Reading

- The Lantern packet the user points you at.
- `.cursor/skills/angular-migrator-skill.md`.
- `.cursor/rules/angular-migration-rules.md`.
- `migration-analysis.md` if it exists.
- The legacy files in `legacy-angularjs-app/`.

## Work Product

Create or update `modern-angular/`.

Minimum expected files:

- `modern-angular/package.json`
- `modern-angular/angular.json`
- `modern-angular/tsconfig.json`
- `modern-angular/tsconfig.app.json`
- `modern-angular/README.md`
- `modern-angular/src/index.html`
- `modern-angular/src/main.ts`
- `modern-angular/src/styles.css`
- `modern-angular/src/assets/board.json`
- `modern-angular/src/app/app.component.ts`
- `modern-angular/src/app/app.component.html`
- `modern-angular/src/app/app.component.css`
- `modern-angular/src/app/board/board.component.ts`
- `modern-angular/src/app/board/board.component.html`
- `modern-angular/src/app/board/board.component.css`
- `modern-angular/src/app/board/issue-card.component.ts`
- `modern-angular/src/app/board/issue-card.component.html`
- `modern-angular/src/app/board/issue-card.component.css`
- `modern-angular/src/app/services/board-api.service.ts`
- `modern-angular/src/app/services/workflow.service.ts`
- `modern-angular/src/app/models/board.models.ts`

The migrated code should use TypeScript classes/interfaces and Angular-style
components/services. Do not include AngularJS APIs.

The generated app should be runnable with:

```bash
cd modern-angular
npm install
npm start
```

Use ordinary Angular package scripts in `package.json`, for example
`"start": "ng serve --host 127.0.0.1 --port 4200"`.

## Artifact

After creating or updating files, write the exact artifact JSON object requested
by the Lantern packet. Include all changed files as workspace-relative paths:

```json
{
  "packet_id": "COPY_FROM_PACKET",
  "changed_files": [
    "modern-angular/package.json",
    "modern-angular/README.md",
    "modern-angular/src/app/app.component.ts"
  ],
  "summary": "Created the modern Angular migration skeleton."
}
```
