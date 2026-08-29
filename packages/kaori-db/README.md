# Kaori DB

Production `SignalStore` for Kaori Flow.

`PostgresSignalStore` implements `kaori_flow.store.SignalStore`:

- append-only
- idempotent on `signal_id`
- `get_all` / `get_for_agent` / `get_since` / `get_by_type`

Connect with `DATABASE_URL` only. Schema is the `signals` table in `src/kaori_db/schema.sql`. This package does not provision a database or invent product tables.
