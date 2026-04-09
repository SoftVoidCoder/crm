import sqlite3

DB_NAME = "korda_v2.db"

def init_db():
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, password TEXT, name TEXT, role TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT, contract TEXT, client TEXT, manager TEXT, status TEXT, progress INTEGER, checkedState TEXT, comments TEXT, deadlines TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, inn TEXT, contact TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS meetings (id INTEGER PRIMARY KEY, title TEXT, m_date TEXT, m_time TEXT, participants TEXT, agenda TEXT, decisions TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS global_chats (id INTEGER PRIMARY KEY, name TEXT, type TEXT, creator TEXT, participants TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS global_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user TEXT, role TEXT, text TEXT, time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, type TEXT, number TEXT, d_date TEXT, correspondent TEXT, subject TEXT, status TEXT, file_url TEXT, qr_code TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT, description TEXT, author TEXT, executor TEXT, deadline TEXT, status TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS knowledge_base (id INTEGER PRIMARY KEY, title TEXT, content TEXT, file_url TEXT, author TEXT, created_at TEXT, required_roles TEXT, read_by TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS approvals (id INTEGER PRIMARY KEY, title TEXT, item_link TEXT, route TEXT, current_step INTEGER, status TEXT, history TEXT, author TEXT, created_at TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS nomenclature (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, article TEXT, unit TEXT, price REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, name TEXT, phone TEXT, email TEXT, position TEXT)''')

    c.execute("SELECT COUNT(*) FROM global_chats")
    if c.fetchone()[0] == 0:
        default_chats = [(1, 'Общий чат (Вся компания)', 'system', 'system', '[]'), (2, 'Совещания и Планерки', 'system', 'system', '[]'), (3, 'Конструкторское бюро', 'role', 'system', '["Конструкторское бюро"]'), (4, 'Производство и ОТК', 'role', 'system', '["Производство и ОТК"]'), (5, 'Менеджеры (Логистика)', 'role', 'system', '["Менеджер"]'), (6, 'Бухгалтерия', 'role', 'system', '["Бухгалтерия"]'), (7, 'Юристы', 'role', 'system', '["Юрист"]')]
        c.executemany("INSERT INTO global_chats VALUES (?, ?, ?, ?, ?)", default_chats)

    for col, default in [('budget', 'REAL DEFAULT 0'), ('costs', 'REAL DEFAULT 0'), ('chat', "TEXT DEFAULT '[]'"), ('files', "TEXT DEFAULT '[]'"), ('logs', "TEXT DEFAULT '[]'"), ('team', "TEXT DEFAULT '[]'"), ('checklist', "TEXT DEFAULT '[]'"), ('escalations', "TEXT DEFAULT '{}'"), ('archive_details', "TEXT DEFAULT '{}'"), ('taskFiles', "TEXT DEFAULT '{}'"), ('subtasks', "TEXT DEFAULT '{}'"), ('time_logs', "TEXT DEFAULT '[]'"), ('allowed_roles', "TEXT DEFAULT '[]'"), ('nomenclature', "TEXT DEFAULT '[]'")]:
        try: c.execute(f"ALTER TABLE projects ADD COLUMN {col} {default}")
        except: pass
        
    for col, default in [('signature', "TEXT DEFAULT ''"), ('vacation_until', "TEXT DEFAULT ''"), ('deputy', "TEXT DEFAULT ''"), ('abs_start', "TEXT DEFAULT ''"), ('abs_end', "TEXT DEFAULT ''"), ('abs_type', "TEXT DEFAULT ''"), ('abs_reason', "TEXT DEFAULT ''"), ('is_head', "INTEGER DEFAULT 0"), ('hourly_rate', "INTEGER DEFAULT 500")]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {default}")
        except: pass

    try: c.execute("ALTER TABLE documents ADD COLUMN qr_code TEXT DEFAULT ''")
    except: pass
    
    try: c.execute("ALTER TABLE documents ADD COLUMN project_id INTEGER DEFAULT 0")
    except: pass

    try: c.execute("ALTER TABLE documents ADD COLUMN parent_id INTEGER DEFAULT 0")
    except: pass

    try: c.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'none'")
    except: pass

    try: c.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'normal'")
    except: pass
    try: c.execute("ALTER TABLE tasks ADD COLUMN project_id INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE tasks ADD COLUMN history TEXT DEFAULT '[]'")
    except: pass
    try: c.execute("ALTER TABLE documents ADD COLUMN priority TEXT DEFAULT 'normal'")
    except: pass

    # === МИГРАЦИЯ ДЛЯ СКЛАДА ===
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN stock REAL DEFAULT 0")
    except: pass
        
    try: c.execute("ALTER TABLE nomenclature ADD COLUMN currency TEXT DEFAULT 'RUB'")
    except: pass
        
    c.execute("SELECT * FROM users WHERE email='ilyu5haosipow@yandex.ru'")
    if not c.fetchone(): c.execute("INSERT INTO users (email, password, name, role, status, is_head) VALUES ('ilyu5haosipow@yandex.ru', '123', 'Илья Осипов', 'Директор', 'approved', 1)")
    conn.commit(); conn.close()