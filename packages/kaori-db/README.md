# Kaori DB

Production `SignalStore` and TruthState persist for Kaori Flow / the Pattern B sidecar.

`PostgresSignalStore` implements `kaori_flow.store.SignalStore`:

- append-only
- idempotent on `signal_id`
- `get_all` / `get_for_agent` / `get_since` / `get_by_type`

`PostgresTruthStateStore` upserts compiled TruthStates:

- table `kaori.truth_states` (`truthkey` PK, `artifact` JSONB, `compiled_at`)
- `artifact` is the full `TruthState.model_dump` including content-bound `evidence_refs` (`{uri, sha256}`), `compile_inputs.observations`, and `consensus.votes` when a vote was recorded
- upsert on `truthkey`

Connect with `DATABASE_URL` only — Cloud SQL Postgres. Do not provision a Cloud SQL instance from this package.

Tables live in schema `kaori` (`CREATE SCHEMA IF NOT EXISTS kaori`). Do not put `signals` or `truth_states` in `public`. Do not write TruthState to `public.truths`. `ensure_schema()` creates the schema and both tables; it does not provision a database.
