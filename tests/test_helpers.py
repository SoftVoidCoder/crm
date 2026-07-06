import time
import secrets

from database import get_connection
from utils import hash_password


def create_test_user(role="Менеджер", status="approved", name_prefix="Test User"):
    ts = int(time.time() * 1000)
    suffix = secrets.token_hex(3)
    email = f"test_{role.lower().replace(' ', '_')}_{ts}_{suffix}@example.com"
    password = "Testpass123"
    name = f"{name_prefix} {ts}"
    last_error = None
    for _ in range(5):
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO users (email, password, name, role, status, is_head)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (email, hash_password(password), name, role, status),
            )
            conn.commit()
            last_error = None
            break
        except Exception as exc:
            conn.rollback()
            last_error = exc
            time.sleep(0.2)
        finally:
            conn.close()
    if last_error:
        raise last_error
    return {"email": email, "password": password, "name": name, "role": role}


def delete_test_user(email: str):
    last_error = None
    for _ in range(5):
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("DELETE FROM user_sessions WHERE user_email=?", (email,))
            c.execute("DELETE FROM users WHERE email=?", (email,))
            conn.commit()
            last_error = None
            return
        except Exception as exc:
            conn.rollback()
            last_error = exc
            time.sleep(0.2)
        finally:
            conn.close()
    if last_error:
        raise last_error


def allocate_test_project_id() -> int:
    # Keep generated ids inside PostgreSQL INTEGER columns used by project links.
    return 1_900_000_000 + (int(time.time() * 1000) % 190_000_000) + secrets.randbelow(1000)


def run_db_cleanup(statements, retries: int = 10, delay: float = 0.2):
    last_error = None
    for _ in range(retries):
        conn = get_connection()
        try:
            c = conn.cursor()
            for query, params in statements:
                c.execute(query, params)
            conn.commit()
            return
        except Exception as exc:
            conn.rollback()
            last_error = exc
            time.sleep(delay)
        finally:
            conn.close()
    if last_error:
        raise last_error
