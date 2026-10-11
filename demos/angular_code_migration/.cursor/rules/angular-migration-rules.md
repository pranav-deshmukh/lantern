# Angular Migration Rules

The code migrator must follow these rules:

1. Do not modify files under `legacy-angularjs-app/`.
2. Put migrated code under `modern-angular/`.
3. Do not use AngularJS APIs in migrated files: no `angular.module`, no
   `ng-controller`, no `$scope`, no `$http`, no `$q`, no `$timeout`, no
   AngularJS directive definitions.
4. Preserve the board domain model: project members, lanes, issues, checklist
   progress, assignees, priorities, and workflow transitions.
5. Include a `modern-angular/README.md` describing what was migrated, what is
   intentionally mocked, and how a real Angular CLI project would wire it.
6. Every artifact must include the exact `packet_id` and a complete
   `changed_files` list using workspace-relative paths.
