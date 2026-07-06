from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import (
    DB_NAME,
    DATABASE_URL,
    get_connection,
    get_database_runtime_info,
    list_entity_locks,
    list_background_job_runs,
    list_recovery_workflow_runs,
)
from db_migrations import apply_sql_migrations, get_migration_status


def print_status():
    conn = get_connection()
    try:
        migration = get_migration_status(conn)
        table_count = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'"
        ).fetchone()[0]
    finally:
        conn.close()
    print(f"db_name: {DB_NAME}")
    print(f"tables: {table_count}")
    print(f"migrations_applied: {len(migration['applied'])}")
    print(f"migrations_pending: {len(migration['pending'])}")
    if migration["pending"]:
        print("pending_list:")
        for item in migration["pending"]:
            print(f"  - {item}")
    return 0


def print_runtime():
    runtime = get_database_runtime_info()
    print(f"backend: {runtime.get('backend')}")
    print(f"db_name: {runtime.get('db_name')}")
    print(f"integrity: {runtime.get('integrity', 'unknown')}")
    print(f"server_version: {runtime.get('server_version', '')}")
    print(f"migrations_applied: {runtime.get('migrations_applied', 0)}")
    print(f"migrations_pending: {runtime.get('migrations_pending', 0)}")
    print(f"active_locks: {len(list_entity_locks(limit=200))}")
    print(f"background_jobs: {len(list_background_job_runs(limit=50))}")
    print(f"recovery_runs: {len(list_recovery_workflow_runs(limit=50))}")
    return 0


def run_migrate():
    conn = get_connection()
    try:
        executed = apply_sql_migrations(conn, int(time.time()))
        conn.commit()
    finally:
        conn.close()
    if executed:
        print("applied:")
        for item in executed:
            print(f"  - {item}")
    else:
        print("no pending migrations")
    return 0


def run_integrity():
    conn = get_connection()
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()
    print("ok")
    return 0


def run_doctor():
    status_code = print_status()
    print_runtime()
    locks = list_entity_locks(limit=200)
    stale_locks = [row for row in locks if int(row.get("is_stale") or 0) == 1]
    bg = list_background_job_runs(limit=50)
    stale_jobs = [row for row in bg if int(row.get("is_stale") or 0) == 1]
    print(f"stale_locks: {len(stale_locks)}")
    print(f"stale_jobs: {len(stale_jobs)}")
    return status_code if status_code else 0


def run_backup(destination: str = ""):
    target = Path(destination).expanduser().resolve() if destination else ROOT / f"korda_backup_{int(time.time())}.sql"
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pg_dump", DATABASE_URL, "-f", str(target)], check=True)
    print(target)
    return 0


def run_checkpoint():
    print("checkpoint_managed_by_postgres")
    return 0


def run_export_json(target: str = ""):
    path = Path(target).expanduser().resolve() if target else ROOT / "db_export.json"
    conn = get_connection(row_factory=True)
    try:
        export_payload = {"generated_at": int(time.time()), "db_name": DB_NAME, "tables": {}}
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
            ).fetchall()
        ]
        for table in tables:
            rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()]
            export_payload["tables"][table] = rows
    finally:
        conn.close()
    path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Korda DB operational tool")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show migration and integrity status")
    sub.add_parser("runtime", help="Show database runtime and operations stats")
    sub.add_parser("doctor", help="Run extended operational health summary")
    sub.add_parser("migrate", help="Apply pending SQL migrations")
    sub.add_parser("integrity", help="Run basic PostgreSQL connectivity check")
    sub.add_parser("checkpoint", help="Show checkpoint status")
    export_parser = sub.add_parser("export-json", help="Export current PostgreSQL data to JSON")
    export_parser.add_argument("--target", default="", help="Target JSON file path")
    backup_parser = sub.add_parser("backup", help="Create PostgreSQL SQL dump")
    backup_parser.add_argument("--target", default="", help="Optional backup file path")
    args = parser.parse_args()

    if args.command == "status":
        raise SystemExit(print_status())
    if args.command == "migrate":
        raise SystemExit(run_migrate())
    if args.command == "runtime":
        raise SystemExit(print_runtime())
    if args.command == "doctor":
        raise SystemExit(run_doctor())
    if args.command == "integrity":
        raise SystemExit(run_integrity())
    if args.command == "checkpoint":
        raise SystemExit(run_checkpoint())
    if args.command == "export-json":
        raise SystemExit(run_export_json(args.target))
    if args.command == "backup":
        raise SystemExit(run_backup(args.target))


if __name__ == "__main__":
    main()
