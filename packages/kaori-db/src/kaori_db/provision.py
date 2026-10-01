"""
Prepare a Kaori database for a deployment: the schema, the roles, and the API's own login.

    ADMIN_DATABASE_URL=...  RUNTIME_DATABASE_URL=...  python -m kaori_db.provision

ADMIN_DATABASE_URL is a user allowed to create schemas and roles (on Cloud SQL, a built-in
user, a member of cloudsqlsuperuser). RUNTIME_DATABASE_URL is the URL the API will use; its
user name and password define the login role, which is created, or has its password set, and is
made a member of kaori_runtime only: append-only on the ledger, no DDL. Safe to run again.
Prints no secrets.
"""
from __future__ import annotations

import os
import re
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from kaori_db.migrate import migrate


def provision(admin_url: str, runtime_url: str) -> str:
    runtime = make_url(runtime_url)
    role, password = runtime.username or "", runtime.password or ""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"runtime user must be a plain lower-case name, got {role!r}")
    if len(password) < 16 or "'" in password:
        raise ValueError("runtime password must be at least 16 characters, without quotes")

    migrate(admin_url)
    engine = create_engine(admin_url)
    try:
        with engine.begin() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
            conn.execute(text(f"{'ALTER' if exists else 'CREATE'} ROLE {role} LOGIN PASSWORD '{password}'"))
            conn.execute(text(f"GRANT kaori_runtime TO {role}"))
    finally:
        engine.dispose()
    return f"schema applied; login {role} {'updated' if exists else 'created'} (kaori_runtime only)"


def main() -> int:
    admin, runtime = os.environ.get("ADMIN_DATABASE_URL"), os.environ.get("RUNTIME_DATABASE_URL")
    if not admin or not runtime:
        print("ADMIN_DATABASE_URL and RUNTIME_DATABASE_URL are required", file=sys.stderr)
        return 2
    print(provision(admin, runtime))
    return 0


if __name__ == "__main__":
    sys.exit(main())
