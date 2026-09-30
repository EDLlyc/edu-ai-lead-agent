#!/usr/bin/env python3
"""Create or update the SELECT-only database role used by the local ops and repair MCP servers.

Industrial defaults, idempotent:
- least privilege: SELECT on the listed tables only; a few tables column by column, without
  recipient identifiers or raw payloads; no schema CREATE, no role inheritance, not a superuser;
- guard rails on the role: read-only default transactions, 5 s statement timeout, 30 s idle
  in transaction, 1 s lock timeout, at most 4 connections;
- the password is generated here and sent only as a SCRAM-SHA-256 verifier over stdin, so the
  plain password never reaches the server, its logs or any command line;
- the local connection string is written to a 0600 file outside the repository.

Production is reached only through `ops_db_tunnel.sh` (127.0.0.1:15432 -> the server's
127.0.0.1:5432); the database port is never exposed.

Usage:
  python scripts/ops/ops_readonly_role.py --target local
  python scripts/ops/ops_readonly_role.py --target production [--rotate]
  python scripts/ops/ops_readonly_role.py --target production --print-sql
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.infrastructure.db.ops_reader import OPS_READ_COLUMNS, OPS_READ_TABLES

ROLE = "edu_ai_ops_ro"
DATABASE = "edu_ai"
TARGETS = {
    "local": {
        "port": 5432,
        "command": [
            "docker",
            "exec",
            "-i",
            "edu-ai-lead-agent-postgres-1",
            "psql",
            "-U",
            "edu_ai",
            "-d",
            DATABASE,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-f",
            "-",
        ],
    },
    "production": {
        "port": 15432,
        "command": [
            "ssh",
            "-o",
            "BatchMode=yes",
            "edu-ai-production",
            (
                "cd /opt/edu-ai-lead-agent && sudo -n docker compose -p edu-ai-lead-agent "
                "exec -T postgres psql -U edu_ai -d edu_ai -v ON_ERROR_STOP=1 -q -f -"
            ),
        ],
    },
}


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def scram_verifier(password: str, iterations: int = 4096) -> str:
    """The SCRAM-SHA-256 verifier PostgreSQL stores, computed client side (RFC 7677)."""

    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return (
        f"SCRAM-SHA-256${iterations}:{_b64(salt)}${_b64(stored_key)}:{_b64(server_key)}"
    )


def _guarded(statement: str, table: str, *, strict: bool) -> str:
    missing = (
        f"RAISE EXCEPTION 'table public.{table} is missing'"
        if strict
        else f"RAISE NOTICE 'skipping missing table public.{table}'"
    )
    return (
        f"DO $$ BEGIN IF to_regclass('public.{table}') IS NULL THEN {missing}; "
        f"ELSE EXECUTE $grant${statement}$grant$; END IF; END $$;"
    )


def render_sql(verifier: str, *, strict: bool = True) -> str:
    table_grants = "\n".join(
        _guarded(
            f"GRANT SELECT ON TABLE public.{table} TO {ROLE}", table, strict=strict
        )
        for table in OPS_READ_TABLES
    )
    column_grants = "\n".join(
        _guarded(
            f"GRANT SELECT ({', '.join(columns)}) ON TABLE public.{table} TO {ROLE}",
            table,
            strict=strict,
        )
        for table, columns in OPS_READ_COLUMNS.items()
    )
    return f"""BEGIN;
-- Give up rather than queue behind (and in front of) the workers' table locks.
SET LOCAL lock_timeout = '3s';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
    CREATE ROLE {ROLE};
  END IF;
END
$$;
ALTER ROLE {ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION
  NOBYPASSRLS CONNECTION LIMIT 4 PASSWORD '{verifier}';
ALTER ROLE {ROLE} SET default_transaction_read_only = on;
ALTER ROLE {ROLE} SET statement_timeout = '5s';
ALTER ROLE {ROLE} SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE {ROLE} SET lock_timeout = '1s';
-- Start from nothing on every run, table and column privileges alike.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE};
DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT DISTINCT table_name, column_name FROM information_schema.column_privileges
    WHERE grantee = '{ROLE}' AND table_schema = 'public'
  LOOP
    EXECUTE format('REVOKE ALL (%I) ON TABLE public.%I FROM {ROLE}',
                   item.column_name, item.table_name);
  END LOOP;
END
$$;
-- Temporary tables come from PUBLIC by default. Every application role here is a superuser
-- (unaffected), so this only removes TEMP from non-superuser roles such as this one.
REVOKE TEMPORARY ON DATABASE {DATABASE} FROM PUBLIC;
GRANT CONNECT ON DATABASE {DATABASE} TO {ROLE};
GRANT USAGE ON SCHEMA public TO {ROLE};
{table_grants}
{column_grants}
COMMIT;
SELECT count(*) AS granted_tables FROM information_schema.role_table_grants
  WHERE grantee = '{ROLE}' AND privilege_type = 'SELECT';
"""


def env_file_for(target: str) -> Path:
    return Path.home() / ".config" / "edu-ai" / f"ops-db.{target}.env"


def read_existing_password(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith("OPS_DATABASE_URL="):
            credentials = line.split("://", 1)[1].split("@", 1)[0]
            return credentials.split(":", 1)[1]
    return None


def write_env_file(path: Path, password: str, port: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    url = f"postgresql+asyncpg://{ROLE}:{quote(password, safe='')}@127.0.0.1:{port}/{DATABASE}"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(f"OPS_DATABASE_URL={url}\n")
    os.chmod(path, 0o600)


SERVER_ENV = "/opt/edu-ai-lead-agent/scripts/ops-readonly.env"


def install_server_env(password: str) -> None:
    """Write the compose-network connection string on the server (root 0600) over SSH stdin."""

    url = f"postgresql+asyncpg://{ROLE}:{quote(password, safe='')}@postgres:5432/{DATABASE}"
    subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "edu-ai-production",
            f"sudo -n sh -c 'umask 077; cat > {SERVER_ENV}.tmp && mv {SERVER_ENV}.tmp {SERVER_ENV}'",
        ],
        input=f"OPS_DATABASE_URL={url}\n",
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    )
    print(f"server connection string written to {SERVER_ENV} (root 0600)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--rotate", action="store_true", help="generate a new password")
    parser.add_argument(
        "--install-server-env",
        action="store_true",
        help="production only: also write the in-network connection string for server jobs",
    )
    parser.add_argument(
        "--print-sql", action="store_true", help="print the SQL; apply nothing"
    )
    args = parser.parse_args()
    target = TARGETS[args.target]
    env_file = env_file_for(args.target)

    if args.print_sql:
        print(render_sql("<scram-verifier>", strict=args.target == "production"))
        return 0
    existing = None if args.rotate else read_existing_password(env_file)
    password = existing or secrets.token_urlsafe(32)
    # Production must have every table; a local development database may lag behind.
    sql = render_sql(scram_verifier(password), strict=args.target == "production")
    completed = subprocess.run(
        target["command"],
        input=sql,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        # psql may echo a failing statement; never print the verifier.
        print(
            re.sub(r"SCRAM-SHA-256\$\S+", "<verifier>", completed.stderr)[-2000:],
            file=sys.stderr,
        )
        return completed.returncode
    write_env_file(env_file, password, int(target["port"]))
    if args.install_server_env:
        if args.target != "production":
            parser.error("--install-server-env applies to production only")
        install_server_env(password)
    print(completed.stdout.strip())
    print(f"role {ROLE} ready on {args.target}; connection string in {env_file} (0600)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
