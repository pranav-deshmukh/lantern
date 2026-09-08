# Migration Skills

- Use idempotent DDL statements where possible.
- Prefer batched backfills over one long transaction.
- Keep migrations small and reversible.
- Test against a staging copy before touching production.
