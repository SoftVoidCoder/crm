import os, shutil, sqlite3, json, time
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from database import DB_NAME
from schemas import ClientData, ProjectData, ProjectUpdate, NomenclatureData, ContactData, StockMovement

# === ПОДКЛЮЧАЕМ МЕНЕДЖЕР WEBSOCKETS ===
from utils import manager 

router = APIRouter()

from pydantic import BaseModel
class ClaimData(BaseModel):
    proj_id: int
    number: str
    d_date: str
    initiator: str
    addressee: str
    amount: float
    status: str
    date_sent: str
    deadline: str
    date_answered: str

class CourtCaseData(BaseModel):
    proj_id: int
    number: str
    court_name: str
    plaintiff: str
    defendant: str
    amount: float
    instance: str
    stage: str
    next_hearing: str

def init_claims_table():
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS claims (id INTEGER PRIMARY KEY, proj_id INTEGER, number TEXT, d_date TEXT, initiator TEXT, addressee TEXT, amount REAL, status TEXT, date_sent TEXT, deadline TEXT, date_answered TEXT, files TEXT, history TEXT)''')
    conn.commit()

def init_courts_table():
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS court_cases (id INTEGER PRIMARY KEY, proj_id INTEGER, number TEXT, court_name TEXT, plaintiff TEXT, defendant TEXT, amount REAL, instance TEXT, stage TEXT, next_hearing TEXT, files TEXT, history TEXT)''')
    conn.commit()

@router.get("/api/claims")
def get_claims():
    init_claims_table(); conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM claims ORDER BY id DESC")
    return [dict(r) for r in c.fetchall()]

@router.post("/api/claims")
async def create_claim(data: ClaimData):
    init_claims_table(); conn = sqlite3.connect(DB_NAME); c = conn.cursor(); cid = int(time.time() * 1000)
    c.execute("INSERT INTO claims (id, proj_id, number, d_date, initiator, addressee, amount, status, date_sent, deadline, date_answered, files, history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cid, data.proj_id, data.number, data.d_date, data.initiator, data.addressee, data.amount, data.status, data.date_sent, data.deadline, data.date_answered, '[]', '[]'))
    conn.commit(); await manager.broadcast({"type": "claims"})
    return {"status": "success", "id": cid}

@router.put("/api/claims/{claim_id}")
async def update_claim(claim_id: int, data: ClaimData):
    init_claims_table(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE claims SET proj_id=?, number=?, d_date=?, initiator=?, addressee=?, amount=?, status=?, date_sent=?, deadline=?, date_answered=? WHERE id=?", (data.proj_id, data.number, data.d_date, data.initiator, data.addressee, data.amount, data.status, data.date_sent, data.deadline, data.date_answered, claim_id))
    conn.commit(); await manager.broadcast({"type": "claims"})
    return {"status": "success"}

@router.get("/api/court_cases")
def get_court_cases():
    init_courts_table(); conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM court_cases ORDER BY id DESC")
    return [dict(r) for r in c.fetchall()]

@router.post("/api/court_cases")
async def create_court_case(data: CourtCaseData):
    init_courts_table(); conn = sqlite3.connect(DB_NAME); c = conn.cursor(); cid = int(time.time() * 1000)
    c.execute("INSERT INTO court_cases (id, proj_id, number, court_name, plaintiff, defendant, amount, instance, stage, next_hearing, files, history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (cid, data.proj_id, data.number, data.court_name, data.plaintiff, data.defendant, data.amount, data.instance, data.stage, data.next_hearing, '[]', '[]'))
    conn.commit(); await manager.broadcast({"type": "court_cases"})
    return {"status": "success", "id": cid}

@router.put("/api/court_cases/{case_id}")
async def update_court_case(case_id: int, data: CourtCaseData):
    init_courts_table(); conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE court_cases SET proj_id=?, number=?, court_name=?, plaintiff=?, defendant=?, amount=?, instance=?, stage=?, next_hearing=? WHERE id=?", (data.proj_id, data.number, data.court_name, data.plaintiff, data.defendant, data.amount, data.instance, data.stage, data.next_hearing, case_id))
    conn.commit(); await manager.broadcast({"type": "court_cases"})
    return {"status": "success"}

@router.get("/api/test_server")
def test_server():
    return {"message": "БРАТУХА, СЕРВЕР ОБНОВИЛСЯ И ВИДИТ НОВЫЙ КОД!"}

@router.get("/api/clients")
def get_clients():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM clients"); return [dict(r) for r in c.fetchall()]

@router.post("/api/clients")
def create_client(data: ClientData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("INSERT INTO clients (name, inn, contact) VALUES (?, ?, ?)", (data.name, data.inn, data.contact)); conn.commit(); return {"status": "success"}

# === РОУТЕРЫ НСИ И СКЛАДА ===
@router.get("/api/nomenclature")
def get_nomenclature():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM nomenclature ORDER BY name ASC"); return [dict(r) for r in c.fetchall()]

@router.post("/api/nomenclature")
async def create_nomenclature(data: NomenclatureData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    # Сохраняем товар с базовым нулевым остатком и выбранной валютой
    c.execute("INSERT INTO nomenclature (name, article, unit, price, stock, currency) VALUES (?, ?, ?, ?, ?, ?)", (data.name, data.article, data.unit, data.price, data.stock, data.currency))
    conn.commit()
    return {"status": "success"}

@router.delete("/api/nomenclature/{article}")
async def delete_nomenclature(article: str):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("DELETE FROM nomenclature WHERE article=?", (article,))
    conn.commit()
    return {"status": "success"}

# === ВОТ ЭТОТ МАРШРУТ БЫЛ ПОТЕРЯН! ===
@router.post("/api/nomenclature/{article}/movement")
async def move_stock(article: str, data: StockMovement):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("SELECT stock FROM nomenclature WHERE article=?", (article,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Товар не найден")
    
    current_stock = row[0] or 0
    new_stock = current_stock + data.qty if data.type == 'add' else current_stock - data.qty
    
    c.execute("UPDATE nomenclature SET stock=? WHERE article=?", (new_stock, article))
    conn.commit()
    return {"status": "success", "new_stock": new_stock}
# ====================================

@router.get("/api/contacts")
def get_contacts():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM contacts ORDER BY name ASC"); return [dict(r) for r in c.fetchall()]

@router.post("/api/contacts")
def create_contact(data: ContactData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("INSERT INTO contacts (client_id, name, phone, email, position) VALUES (?, ?, ?, ?, ?)", (data.client_id, data.name, data.phone, data.email, data.position)); conn.commit(); return {"status": "success"}
# =========================

@router.get("/api/projects")
def get_projs(user_name: str = "", user_role: str = "", is_head: int = 0):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    subordinates = []
    if is_head == 1 and user_role != 'Директор':
        c.execute("SELECT name FROM users WHERE role=?", (user_role,))
        subordinates = [r['name'] for r in c.fetchall()]

    c.execute("SELECT * FROM projects")
    projs = []
    for p in c.fetchall():
        d = dict(p)
        for f in ['checkedState', 'comments', 'deadlines', 'chat', 'files', 'logs', 'team', 'checklist', 'escalations', 'archive_details', 'taskFiles', 'subtasks', 'time_logs', 'allowed_roles', 'nomenclature']: 
            if f in d: d[f] = json.loads(d[f]) if d[f] else ({} if f in ['checkedState', 'comments', 'deadlines', 'escalations', 'archive_details', 'taskFiles', 'subtasks'] else [])
        
        team = d.get('team', [])
        manager_name = d.get('manager', '')
        allowed_roles = d.get('allowed_roles', [])
        checked = d.get('checkedState', {})
        
        allowed = False
        
        if user_role == 'Директор': allowed = True
        elif user_name == manager_name or user_name in team: allowed = True
        elif user_role in allowed_roles: allowed = True
        elif is_head == 1 and (manager_name in subordinates or any(t in subordinates for t in team)): allowed = True
        elif user_role == 'Юрист' and "task_4_1" in checked: allowed = True
        elif user_role == 'Бухгалтерия' and "task_2_1" in checked: allowed = True
        elif user_role in ['Конструкторское бюро', 'Производство и ОТК']: allowed = True
        elif not team and not allowed_roles: allowed = True
        
        if allowed: projs.append(d)
    return projs

@router.post("/api/projects")
async def create_proj(data: ProjectData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO projects (id, name, contract, client, manager, status, progress, checkedState, comments, deadlines, budget, costs, chat, files, logs, team, checklist, escalations, archive_details, taskFiles, subtasks, time_logs, allowed_roles, nomenclature) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
              (int(time.time() * 1000), data.name, data.contract, data.client, data.manager, 'active', 0, '{}', '{}', '{}', data.budget, data.costs, '[]', '[]', '[]', json.dumps(data.team), json.dumps(data.checklist), '{}', '{}', '{}', '{}', '[]', json.dumps(data.allowed_roles), json.dumps(data.nomenclature)))
    conn.commit()
    await manager.broadcast({"type": "projects"}) 
    return {"status": "success"}

@router.put("/api/projects/{proj_id}")
async def update_proj(proj_id: int, data: ProjectUpdate):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE projects SET name=?, contract=?, client=?, manager=?, progress=?, status=?, checkedState=?, comments=?, deadlines=?, budget=?, costs=?, chat=?, files=?, logs=?, team=?, checklist=?, escalations=?, archive_details=?, taskFiles=?, subtasks=?, time_logs=?, allowed_roles=?, nomenclature=? WHERE id=?", 
              (data.name, data.contract, data.client, data.manager, data.progress, data.status, json.dumps(data.checkedState), json.dumps(data.comments), json.dumps(data.deadlines), data.budget, data.costs, json.dumps(data.chat), json.dumps(data.files), json.dumps(data.logs), json.dumps(data.team), json.dumps(data.checklist), json.dumps(data.escalations), json.dumps(data.archive_details), json.dumps(data.taskFiles), json.dumps(data.subtasks), json.dumps(data.time_logs), json.dumps(data.allowed_roles), json.dumps(data.nomenclature), proj_id))
    conn.commit()
    await manager.broadcast({"type": "projects"}) 
    return {"status": "success"}

@router.post("/api/projects/{proj_id}/upload")
async def upload_file(proj_id: int, file: UploadFile = File(...), user: str = Form(...), doc_type: str = Form(""), parent_file: str = Form("")):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    
    c.execute("SELECT files, logs FROM projects WHERE id=?", (proj_id,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Проект не найден")
        
    files = json.loads(row['files']) if row['files'] else []
    logs = json.loads(row['logs']) if row['logs'] else []
    
    base_filename = file.filename
    existing_files = [f for f in files if f.get('base_name', f['name']) == base_filename]
    version = len(existing_files) + 1
    
    if existing_files:
        latest_file = sorted(existing_files, key=lambda x: x.get('version', 1))[-1]
        if latest_file.get('lockedBy') and latest_file.get('lockedBy') != user:
            raise HTTPException(status_code=403, detail=f"Файл захвачен пользователем: {latest_file.get('lockedBy')}. Дождитесь освобождения.")

    file_path = f"uploads/{int(time.time())}_{file.filename.replace(' ', '_')}"
    with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    
    display_name = f"{base_filename} (v.{version})" if version > 1 else base_filename
    
    for f in files:
        if f.get('base_name', f['name']) == base_filename:
            f['lockedBy'] = None

    f_obj = {"name": display_name, "base_name": base_filename, "url": f"/{file_path}", "user": user, "time": time.strftime("%d.%m.%Y %H:%M"), "version": version, "lockedBy": None, "doc_type": doc_type, "parent": parent_file}
    files.append(f_obj)
    
    logs.insert(0, {"time": time.strftime("%d.%m.%Y %H:%M"), "user": user, "action": f"Загрузил файл: {display_name}" if version == 1 else f"Обновил версию файла: {display_name}"})
    
    c.execute("UPDATE projects SET files=?, logs=? WHERE id=?", (json.dumps(files), json.dumps(logs), proj_id))
    conn.commit()
    
    await manager.broadcast({"type": "projects"}) 
    return {"status": "success", "file": f_obj}

@router.post("/api/projects/{proj_id}/1c_invoice")
async def generate_1c_invoice(proj_id: int):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id=?", (proj_id,))
    row = c.fetchone()
    if not row: raise HTTPException(status_code=404)
    
    import asyncio; await asyncio.sleep(1.5) # Эмуляция задержки шлюза REST 1С
    
    filename = f"Счет_1С_{proj_id}_{int(time.time())}.txt"
    filepath = f"uploads/{filename}"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"СЧЕТ НА ОПЛАТУ (СГЕНЕРИРОВАНО ИНТЕГРАЦИЕЙ 1С:Предприятие)\nПроект: {row['name']}\nЗаказчик: {row['client']}\nСумма: {row['budget']} руб.\n\nСтатус: Ожидает оплаты")
    
    files = json.loads(row['files']) if row['files'] else []
    logs = json.loads(row['logs']) if row['logs'] else []
    
    f_obj = {"name": filename, "base_name": "Счет_1С", "url": f"/{filepath}", "user": "Интеграция 1С", "time": time.strftime("%d.%m.%Y %H:%M"), "version": 1, "lockedBy": None, "doc_type": "Счет на оплату", "parent": ""}
    files.append(f_obj)
    logs.insert(0, {"time": time.strftime("%d.%m.%Y %H:%M"), "user": "Система 1С", "action": f"🤖 Получен счет из 1С:Бухгалтерии"})
    
    c.execute("UPDATE projects SET files=?, logs=? WHERE id=?", (json.dumps(files), json.dumps(logs), proj_id))
    conn.commit()
    await manager.broadcast({"type": "projects"})
    return {"status": "success"}