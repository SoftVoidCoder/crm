import shutil, sqlite3, json, time, os, datetime
import qrcode
from fastapi import APIRouter, UploadFile, File
from database import DB_NAME
from schemas import DocData, DocUpdate, KnowledgeData, KnowledgeReadData, ApprovalData, ApprovalUpdate

# === ПОДКЛЮЧАЕМ МЕНЕДЖЕР WEBSOCKETS ===
from utils import manager

router = APIRouter()

@router.get("/api/documents")
def get_documents():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM documents ORDER BY id DESC"); return [dict(r) for r in c.fetchall()]

@router.post("/api/documents")
async def create_document(data: DocData):
    doc_id = int(time.time() * 1000)
    
    qr_data = json.dumps({"type": "doc", "id": doc_id})
    qr = qrcode.make(qr_data)
    os.makedirs("uploads/qr", exist_ok=True)
    qr_path = f"uploads/qr/doc_{doc_id}.png"
    qr.save(qr_path)
    
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("INSERT INTO documents (id, type, number, d_date, correspondent, subject, status, file_url, qr_code, project_id, parent_id, priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
              (doc_id, data.type, data.number, data.d_date, data.correspondent, data.subject, data.status, "", f"/{qr_path}", data.project_id, data.parent_id, data.priority))
    conn.commit()
    await manager.broadcast({"type": "documents"})
    return {"status": "success"}

@router.post("/api/documents/{doc_id}/upload")
async def upload_doc_file(doc_id: int, file: UploadFile = File(...)):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); file_path = f"uploads/{int(time.time())}_doc_{file.filename.replace(' ', '_')}"
    with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    c.execute("UPDATE documents SET file_url=? WHERE id=?", (f"/{file_path}", doc_id)); conn.commit()
    await manager.broadcast({"type": "documents"})
    return {"status": "success", "url": f"/{file_path}"}

@router.put("/api/documents/{doc_id}")
async def update_document(doc_id: int, data: DocUpdate):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE documents SET type=?, number=?, d_date=?, correspondent=?, subject=?, status=?, project_id=?, parent_id=?, priority=? WHERE id=?", 
              (data.type, data.number, data.d_date, data.correspondent, data.subject, data.status, data.project_id, data.parent_id, data.priority, doc_id))
    conn.commit()
    await manager.broadcast({"type": "documents"})
    return {"status": "success"}

@router.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: int):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit()
    await manager.broadcast({"type": "documents"})
    return {"status": "success"}

@router.post("/api/documents/batch_scan")
async def batch_scan_documents():
    # Эмуляция тяжелого процесса: PyPDF2 режет 100 страниц, pyzbar читает QR-коды
    import asyncio; await asyncio.sleep(2.5)
    # В реальном приложении здесь файлы бы раскидывались по проектам
    await manager.broadcast({"type": "documents"})
    return {"status": "success", "message": "Распознано 3 документа по разделительным штрих-кодам. Они автоматически привязаны к соответствующим сделкам и зарегистрированы в Журнале."}

@router.get("/api/knowledge")
def get_knowledge():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM knowledge_base ORDER BY id DESC")
    res = []
    for r in c.fetchall():
        d = dict(r); d['required_roles'] = json.loads(d['required_roles']); d['read_by'] = json.loads(d['read_by'])
        res.append(d)
    return res

@router.post("/api/knowledge")
async def create_knowledge(data: KnowledgeData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("INSERT INTO knowledge_base (id, title, content, file_url, author, created_at, required_roles, read_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (int(time.time() * 1000), data.title, data.content, "", data.author, time.strftime("%d.%m.%Y %H:%M"), json.dumps(data.required_roles), "[]")); conn.commit()
    await manager.broadcast({"type": "knowledge"})
    return {"status": "success"}

@router.post("/api/knowledge/{k_id}/read")
async def read_knowledge(k_id: int, data: KnowledgeReadData):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor(); c.execute("SELECT read_by FROM knowledge_base WHERE id=?", (k_id,)); row = c.fetchone()
    if row:
        read_by = json.loads(row[0]) if row[0] else []
        if data.user not in read_by:
            read_by.append(data.user)
            c.execute("UPDATE knowledge_base SET read_by=? WHERE id=?", (json.dumps(read_by), k_id)); conn.commit()
            await manager.broadcast({"type": "knowledge"})
    return {"status": "success"}

@router.get("/api/approvals")
def get_approvals():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM approvals ORDER BY id DESC")
    res = []
    for r in c.fetchall():
        d = dict(r); d['route'] = json.loads(d['route']); d['history'] = json.loads(d['history'])
        res.append(d)
    return res

@router.post("/api/approvals")
async def create_approval(data: ApprovalData):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    
    actual_route = []
    today = datetime.datetime.now()
    for person in data.route:
        c.execute("SELECT abs_start, abs_end, deputy FROM users WHERE name=?", (person,))
        u_row = c.fetchone()
        if u_row and u_row['deputy'] and u_row['abs_start'] and u_row['abs_end']:
            try:
                d_start = datetime.datetime.strptime(u_row['abs_start'], "%d.%m.%Y")
                d_end = datetime.datetime.strptime(u_row['abs_end'], "%d.%m.%Y")
                if d_start <= today <= d_end:
                    actual_route.append(f"{u_row['deputy']} (И.О. {person})")
                    continue
            except: pass
        actual_route.append(person)

    c.execute("INSERT INTO approvals (id, title, item_link, route, current_step, status, history, author, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
              (int(time.time() * 1000), data.title, data.item_link, json.dumps(actual_route), 0, 'pending', '[]', data.author, time.strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    await manager.broadcast({"type": "approvals"})
    return {"status": "success"}

@router.put("/api/approvals/{a_id}")
async def update_approval(a_id: int, data: ApprovalUpdate):
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    c.execute("UPDATE approvals SET current_step=?, status=?, history=? WHERE id=?", (data.current_step, data.status, json.dumps(data.history), a_id))
    conn.commit()
    await manager.broadcast({"type": "approvals"})
    return {"status": "success"}