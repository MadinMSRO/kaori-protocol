# Kaori DB

Production `SignalStore` for Kaori Flow.

`PostgresSignalStore` implements `kaori_flow.store.SignalStore`:

- append-only
- idempotent on `signal_id`
- `get_all` / `get_for_agent` / `get_since` / `get_by_type`

Connect with `DATABASE_URL` only — week-1 that is the Liminal Supabase Postgres URL (Lovable project `3edd781a`), not Cloud SQL.

The table is `kaori.signals` (`CREATE SCHEMA IF NOT EXISTS kaori`). Do not put `signals` in `public`. `ensure_schema()` creates the schema and table; it does not provision a database or invent product tables. TruthState is not written to `public.truths`.
