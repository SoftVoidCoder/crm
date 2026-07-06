from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _ensure_schema_migrations_table(conn):
    if getattr(conn, "_backend", "") == "postgres":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id BIGSERIAL PRIMARY KEY,
                migration_name TEXT NOT NULL UNIQUE,
                applied_at BIGINT NOT NULL
            )
            """
        )
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            migration_name TEXT NOT NULL UNIQUE,
            applied_at INTEGER NOT NULL
        )
        """
    )


def apply_sql_migrations(conn, now_ts: int):
    _ensure_schema_migrations_table(conn)
    applied = get_applied_migrations(conn)

    if not MIGRATIONS_DIR.exists():
        return []

    executed = []
    for migration_path in list_migration_files():
        migration_name = migration_path.name
        if migration_name in applied:
            continue
        sql = migration_path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (migration_name, applied_at) VALUES (?, ?)",
            (migration_name, now_ts),
        )
        executed.append(migration_name)
    return executed


def list_migration_files():
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def get_applied_migrations(conn):
    _ensure_schema_migrations_table(conn)
    return {
        row[0]
        for row in conn.execute("SELECT migration_name FROM schema_migrations").fetchall()
    }


def get_migration_status(conn):
    files = list_migration_files()
    applied = get_applied_migrations(conn)
    return {
        "files": [path.name for path in files],
        "applied": sorted(applied),
        "pending": [path.name for path in files if path.name not in applied],
    }
