-- Least-privilege PostgreSQL roles for Kaori.
-- Applied only by `python -m kaori_db.migrate` (migration owner).
-- The API runtime must connect as a member of kaori_runtime, never as
-- the schema owner.
--
-- kaori_migration_owner: DDL + full table rights for schema application.
-- kaori_runtime: SELECT/INSERT on immutable Bronze/Silver tables, plus
-- SELECT/INSERT/UPDATE on the Gold truth_states projection only.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kaori_migration_owner') THEN
        CREATE ROLE kaori_migration_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kaori_runtime') THEN
        CREATE ROLE kaori_runtime NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA kaori TO kaori_migration_owner, kaori_runtime;
GRANT CREATE ON SCHEMA kaori TO kaori_migration_owner;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA kaori TO kaori_migration_owner;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA kaori TO kaori_migration_owner;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA kaori TO kaori_migration_owner;

GRANT SELECT, INSERT ON kaori.signals TO kaori_runtime;
GRANT SELECT, INSERT ON kaori.observations TO kaori_runtime;
GRANT SELECT, INSERT ON kaori.trust_snapshots TO kaori_runtime;
GRANT SELECT, INSERT ON kaori.truth_artifacts TO kaori_runtime;
GRANT SELECT, INSERT, UPDATE ON kaori.truth_states TO kaori_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA kaori TO kaori_runtime;

REVOKE UPDATE, DELETE ON kaori.signals FROM kaori_runtime;
REVOKE UPDATE, DELETE ON kaori.observations FROM kaori_runtime;
REVOKE UPDATE, DELETE ON kaori.trust_snapshots FROM kaori_runtime;
REVOKE UPDATE, DELETE ON kaori.truth_artifacts FROM kaori_runtime;
REVOKE DELETE ON kaori.truth_states FROM kaori_runtime;

REVOKE UPDATE, DELETE ON kaori.signals FROM PUBLIC;
REVOKE UPDATE, DELETE ON kaori.observations FROM PUBLIC;
REVOKE UPDATE, DELETE ON kaori.trust_snapshots FROM PUBLIC;
REVOKE UPDATE, DELETE ON kaori.truth_artifacts FROM PUBLIC;
