-- Kaori Cloud SQL storage.
--
-- Bronze: immutable canonical observations.
-- Silver: immutable trust snapshots and signed truth artifacts.
-- Gold:   kaori.truth_states, a replaceable latest-state projection.
--
-- DATABASE_URL is Cloud SQL Postgres. Lives in schema kaori — never in public
-- (missions, truths, profiles, …). Does not provision Cloud SQL.
-- Apply with `python -m kaori_db.migrate` as kaori_migration_owner.
-- API runtime connects as kaori_runtime and must not execute this file.

CREATE SCHEMA IF NOT EXISTS kaori;

CREATE OR REPLACE FUNCTION kaori.reject_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'kaori.' || TG_TABLE_NAME || ' is append-only',
        ERRCODE = '55000';
END;
$$;

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

DROP TRIGGER IF EXISTS signals_reject_mutation ON kaori.signals;
CREATE TRIGGER signals_reject_mutation
BEFORE UPDATE OR DELETE ON kaori.signals
FOR EACH ROW EXECUTE FUNCTION kaori.reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS kaori.observations (
    observation_id    UUID PRIMARY KEY,
    observation_hash  CHAR(64) NOT NULL UNIQUE
        CHECK (observation_hash ~ '^[0-9a-f]{64}$'),
    truthkey           TEXT NOT NULL,
    claim_type_id      TEXT NOT NULL,
    claim_type_hash    CHAR(64) NOT NULL
        CHECK (claim_type_hash ~ '^[0-9a-f]{64}$'),
    reporter_id        TEXT NOT NULL,
    reported_at        TIMESTAMPTZ NOT NULL,
    received_at        TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
    canonical          JSONB NOT NULL CHECK (jsonb_typeof(canonical) = 'object'),
    evidence_refs      JSONB NOT NULL CHECK (jsonb_typeof(evidence_refs) = 'array')
);

CREATE INDEX IF NOT EXISTS ix_observations_truthkey
    ON kaori.observations (truthkey);
CREATE INDEX IF NOT EXISTS ix_observations_truthkey_reporter
    ON kaori.observations (truthkey, reporter_id);
CREATE INDEX IF NOT EXISTS ix_observations_reported_at
    ON kaori.observations (reported_at);

DROP TRIGGER IF EXISTS observations_reject_mutation ON kaori.observations;
CREATE TRIGGER observations_reject_mutation
BEFORE UPDATE OR DELETE ON kaori.observations
FOR EACH ROW EXECUTE FUNCTION kaori.reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS kaori.trust_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    snapshot_hash  CHAR(64) NOT NULL
        CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    snapshot_time  TIMESTAMPTZ NOT NULL,
    artifact       JSONB NOT NULL CHECK (jsonb_typeof(artifact) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_trust_snapshots_hash
    ON kaori.trust_snapshots (snapshot_hash);

DROP TRIGGER IF EXISTS trust_snapshots_reject_mutation ON kaori.trust_snapshots;
CREATE TRIGGER trust_snapshots_reject_mutation
BEFORE UPDATE OR DELETE ON kaori.trust_snapshots
FOR EACH ROW EXECUTE FUNCTION kaori.reject_immutable_mutation();

-- Silver ledger. Each compile appends one signed immutable revision.
CREATE TABLE IF NOT EXISTS kaori.truth_artifacts (
    artifact_id          BIGSERIAL PRIMARY KEY,
    truthkey             TEXT NOT NULL,
    revision             BIGINT NOT NULL CHECK (revision > 0),
    state_hash           CHAR(64) NOT NULL UNIQUE
        CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    semantic_hash        CHAR(64) NOT NULL
        CHECK (semantic_hash ~ '^[0-9a-f]{64}$'),
    claim_type_id        TEXT NOT NULL,
    claim_type_hash      CHAR(64) NOT NULL
        CHECK (claim_type_hash ~ '^[0-9a-f]{64}$'),
    trust_snapshot_id    TEXT NOT NULL
        REFERENCES kaori.trust_snapshots(snapshot_id),
    trust_snapshot_hash  CHAR(64) NOT NULL
        CHECK (trust_snapshot_hash ~ '^[0-9a-f]{64}$'),
    status               TEXT NOT NULL,
    compiled_at          TIMESTAMPTZ NOT NULL,
    artifact             JSONB NOT NULL CHECK (jsonb_typeof(artifact) = 'object'),
    UNIQUE (truthkey, revision)
);

CREATE INDEX IF NOT EXISTS ix_truth_artifacts_truthkey_compiled
    ON kaori.truth_artifacts (truthkey, compiled_at DESC, artifact_id DESC);
CREATE INDEX IF NOT EXISTS ix_truth_artifacts_semantic_hash
    ON kaori.truth_artifacts (semantic_hash);

DROP TRIGGER IF EXISTS truth_artifacts_reject_mutation ON kaori.truth_artifacts;
CREATE TRIGGER truth_artifacts_reject_mutation
BEFORE UPDATE OR DELETE ON kaori.truth_artifacts
FOR EACH ROW EXECUTE FUNCTION kaori.reject_immutable_mutation();

-- Gold latest-state projection. It is the only mutable Kaori truth table.
-- Full TruthState.model_dump remains available for the existing GET contract.
CREATE TABLE IF NOT EXISTS kaori.truth_states (
    truthkey     TEXT PRIMARY KEY,
    artifact     JSONB NOT NULL,
    compiled_at  TIMESTAMPTZ NOT NULL,
    state_hash   CHAR(64),
    revision     BIGINT,
    artifact_id  BIGINT
);

-- Upgrade the pre-ledger table in place without rewriting existing rows.
ALTER TABLE kaori.truth_states ADD COLUMN IF NOT EXISTS state_hash CHAR(64);
ALTER TABLE kaori.truth_states ADD COLUMN IF NOT EXISTS revision BIGINT;
ALTER TABLE kaori.truth_states ADD COLUMN IF NOT EXISTS artifact_id BIGINT;

REVOKE UPDATE, DELETE ON kaori.signals FROM PUBLIC;
REVOKE UPDATE, DELETE ON kaori.observations FROM PUBLIC;
REVOKE UPDATE, DELETE ON kaori.trust_snapshots FROM PUBLIC;
REVOKE UPDATE, DELETE ON kaori.truth_artifacts FROM PUBLIC;
