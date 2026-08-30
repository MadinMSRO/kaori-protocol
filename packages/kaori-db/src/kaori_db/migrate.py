"""
Apply Kaori schema and role grants.

This is the only supported DDL entrypoint for production. The API runtime
must connect with kaori_runtime privileges and must not call ensure_schema().

Usage (do not run against production from this agent):

    python -m kaori_db.migrate
    python -m kaori_db.migrate --schema-only
    python -m kaori_db.migrate --database-url "$DATABASE_URL"
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine

from kaori_db.store import apply_sql_file, require_kaori_schema


def migrate(database_url: str, *, with_roles: bool = True) -> None:
    """Apply schema.sql, then roles.sql, then confirm required tables exist."""
    engine = create_engine(database_url)
    try:
        apply_sql_file(engine, "schema.sql")
        if with_roles:
            apply_sql_file(engine, "roles.sql")
        require_kaori_schema(engine)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply the Kaori Postgres schema as the migration owner."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres URL (defaults to DATABASE_URL)",
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Apply schema.sql without creating/granting roles",
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    migrate(args.database_url, with_roles=not args.schema_only)
    print("Kaori schema applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
