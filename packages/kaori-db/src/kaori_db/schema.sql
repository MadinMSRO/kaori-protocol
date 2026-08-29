-- Append-only signal log for kaori-flow.SignalStore.
-- Apply against the database named in DATABASE_URL. Does not provision hosting.

CREATE TABLE IF NOT EXISTS signals (
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

CREATE INDEX IF NOT EXISTS ix_signals_time ON signals (time);
CREATE INDEX IF NOT EXISTS ix_signals_agent_id ON signals (agent_id);
CREATE INDEX IF NOT EXISTS ix_signals_object_id ON signals (object_id);
CREATE INDEX IF NOT EXISTS ix_signals_signal_type ON signals (signal_type);
