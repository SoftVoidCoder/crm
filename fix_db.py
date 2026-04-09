import sqlite3

def restore_database():
    conn = sqlite3.connect("korda_v2.db")
    c = conn.cursor()

    print("Начинаю восстановление базы данных...")

    # Восстанавливаем таблицу пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (email TEXT PRIMARY KEY, name TEXT, role TEXT, status TEXT, signature TEXT, password TEXT)''')
    
    # Восстанавливаем таблицу клиентов
    c.execute('''CREATE TABLE IF NOT EXISTS clients
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, inn TEXT, contact TEXT)''')

    # Восстанавливаем таблицу проектов (с правильными колонками из логов)
    c.execute('''CREATE TABLE IF NOT EXISTS projects
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, contract TEXT, client TEXT, manager TEXT, 
                  status TEXT, progress REAL, checkedState TEXT, comments TEXT, deadlines TEXT, 
                  budget REAL, costs REAL, chat TEXT, files TEXT, logs TEXT, team TEXT)''')

    # Возвращаем твой аккаунт Директора, чтобы сразу пустило в систему
    c.execute('''INSERT OR IGNORE INTO users (email, name, password, role, status) 
                 VALUES ('ilyu5haosipow@yandex.ru', 'Илья Осипов', '123456', 'Директор', 'approved')''')

    conn.commit()
    conn.close()
    print("✅ База korda_v2.db успешно восстановлена! Аккаунт Директора создан.")

if __name__ == "__main__":
    restore_database()