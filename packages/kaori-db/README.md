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

`PostgresArtifactLedger` is the durable Observation intake and artifact history:

- table `kaori.observations` (`observation_hash` PK, unique `(truthkey, reporter_id)`)
- one immutable Observation per reporter per TruthKey; same hash is idempotent
- table `kaori.artifact_ledger` (append-only `ledger_id` PK) records every persisted TruthState
- `GET /v1/truth` still reads the current upsert in `kaori.truth_states`

Connect with `DATABASE_URL` only — Cloud SQL Postgres. Do not provision a Cloud SQL instance from this package.

Tables live in schema `kaori` (`CREATE SCHEMA IF NOT EXISTS kaori`). Do not put `signals`, `truth_states`, `observations`, or `artifact_ledger` in `public`. Do not write TruthState to `public.truths`. `ensure_schema()` creates the schema and tables; it does not provision a database.
