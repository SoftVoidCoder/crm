from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_migrations import MIGRATIONS_DIR
from database import init_db, get_connection, get_database_runtime_info


def check_env():
    secret = os.getenv("KORDA_APP_SECRET", "")
    if not secret:
        return False, "KORDA_APP_SECRET is not configured"
    return True, "env ok"


def check_db():
    conn = get_connection()
    try:
        conn.execute("SELECT 1")
        conn.execute("SELECT COUNT(*) FROM users")
        conn.execute("SELECT COUNT(*) FROM schema_migrations")
        runtime = get_database_runtime_info()
    finally:
        conn.close()
    return True, f"db ok ({runtime.get('current_database', '')})"


def check_static():
    required = [
        ROOT / "static" / "core.js",
        ROOT / "static" / "app_api.js",
        ROOT / "static" / "app_shell.js",
        ROOT / "static" / "style.css",
        ROOT / "templates" / "index.html",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        return False, f"missing assets: {', '.join(missing)}"
    return True, "static ok"


def check_migrations():
    if not MIGRATIONS_DIR.exists():
        return False, "migrations directory is missing"
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        return False, "no sql migrations found"
    return True, f"{len(sql_files)} migration(s)"


def main():
    init_db()
    checks = [
        ("env", check_env),
        ("db", check_db),
        ("static", check_static),
        ("migrations", check_migrations),
    ]
    failed = False
    for name, fn in checks:
        ok, message = fn()
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}: {message}")
        if not ok:
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
