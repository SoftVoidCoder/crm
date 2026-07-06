from database import init_db


def restore_database():
    init_db()
    print("PostgreSQL schema initialized successfully.")


if __name__ == "__main__":
    restore_database()
