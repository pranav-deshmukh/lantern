# Migration Rules

1. Always back up the source table before starting any migration.
2. Never rename a column that is referenced by an application query.
3. Add an index before backfilling more than 1,000 rows.
4. Verify row counts before and after every migration step.
5. Record a rollback plan before applying destructive changes.
