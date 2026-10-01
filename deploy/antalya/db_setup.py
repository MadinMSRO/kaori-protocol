"""
Prepare the Antalya ledger database (Supabase Postgres) and print the API's DATABASE_URL.

Run by deploy.sh in Cloud Shell, as the Supabase admin (`postgres`):

    ADMIN_DATABASE_URL=... RUNTIME_LOGIN=kaori_api_antalya.<project-ref> python db_setup.py

1. Applies the Kaori schema and roles (kaori_db.migrate).
2. Creates (or re-keys) the login role the API uses, a member of kaori_runtime only:
   append-only on the ledger, no DDL.
3. Prints the API's connection URL on stdout, for Secret Manager. Nothing else goes to stdout.

MIGRATE_ONLY=1 stops after step 1 (the role and its password are left as they are).

RUNTIME_LOGIN is the user name as the pooler expects it. Supabase's pooler wants
`<role>.<project-ref>`; the role itself is the part before the dot.
"""
from __future__ import annotations

import os
import secrets
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from kaori_db.migrate import migrate


def main() -> int:
    admin_url = os.environ["ADMIN_DATABASE_URL"]
    login = os.environ.get("RUNTIME_LOGIN", "kaori_api_antalya")
    role = login.split(".", 1)[0]
    if not role.replace("_", "").isalnum():
        print(f"bad role name {role!r}", file=sys.stderr)
        return 2

    migrate(admin_url)
    print("schema and roles applied", file=sys.stderr)
    if os.environ.get("MIGRATE_ONLY") == "1":
        return 0

    password = secrets.token_hex(24)
    engine = create_engine(admin_url)
    try:
        with engine.begin() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
            verb = "ALTER" if exists else "CREATE"
            conn.execute(text(f"{verb} ROLE {role} LOGIN PASSWORD '{password}'"))
            conn.execute(text(f"GRANT kaori_runtime TO {role}"))
            # the runtime role sees only the kaori schema
            conn.execute(text(f"ALTER ROLE {role} SET search_path = kaori"))
        print(f"login role {role} {'re-keyed' if exists else 'created'}", file=sys.stderr)
    finally:
        engine.dispose()

    runtime = make_url(admin_url).set(username=login, password=password)
    print(runtime.render_as_string(hide_password=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
