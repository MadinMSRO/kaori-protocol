-- Append-only signal log for kaori-flow.SignalStore and compiled TruthStates.
-- DATABASE_URL is Cloud SQL Postgres. Lives in schema kaori — never in public
-- (missions, truths, profiles, …). Does not provision Cloud SQL.

CREATE SCHEMA IF NOT EXISTS kaori;

CREATE TABLE IF NOT EXISTS kaori.signals (
    signal_id      VARCHAR(64) PRIMARY KEY,
    signal_type    VARCHAR(64) NOT NULL,
    time           TIMESTAMPTZ NOT NULL,
    agent_id       VARCHAR(255) NOT NULL,
    object_id      VARCHAR(255) NOT NULL,
    context        JSONB,
    payload        JSONB NOT NULL,
    policy_version VARCHAR(64) NOT NULL,
    signature      VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS ix_signals_time ON kaori.signals (time);
CREATE INDEX IF NOT EXISTS ix_signals_agent_id ON kaori.signals (agent_id);
CREATE INDEX IF NOT EXISTS ix_signals_object_id ON kaori.signals (object_id);
CREATE INDEX IF NOT EXISTS ix_signals_signal_type ON kaori.signals (signal_type);

-- Full TruthState.model_dump (including evidence_refs). Upsert on truthkey.
-- Never the public truths table.
CREATE TABLE IF NOT EXISTS kaori.truth_states (
    truthkey    TEXT PRIMARY KEY,
    artifact    JSONB NOT NULL,
    compiled_at TIMESTAMPTZ NOT NULL
);

-- One immutable Observation per reporter per TruthKey. Idempotent on hash.
CREATE TABLE IF NOT EXISTS kaori.observations (
    observation_hash VARCHAR(64) PRIMARY KEY,
    truthkey         TEXT NOT NULL,
    reporter_id      VARCHAR(255) NOT NULL,
    claim_type_id    VARCHAR(255) NOT NULL,
    observation      JSONB NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (truthkey, reporter_id)
);

CREATE INDEX IF NOT EXISTS ix_observations_truthkey ON kaori.observations (truthkey);

-- Append-only history of every persisted TruthState artifact.
CREATE TABLE IF NOT EXISTS kaori.artifact_ledger (
    ledger_id    VARCHAR(64) PRIMARY KEY,
    truthkey     TEXT NOT NULL,
    artifact     JSONB NOT NULL,
    compiled_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_artifact_ledger_truthkey ON kaori.artifact_ledger (truthkey);
CREATE INDEX IF NOT EXISTS ix_artifact_ledger_compiled_at ON kaori.artifact_ledger (compiled_at);
