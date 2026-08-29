-- Append-only signal log for kaori-flow.SignalStore.
-- Week-1 target: Liminal Supabase Postgres (DATABASE_URL).
-- Lives in schema kaori — never in public (missions, truths, profiles, …).
-- Does not provision Cloud SQL or invent product tables.

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
