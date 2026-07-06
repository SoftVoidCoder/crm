#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import datetime, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from utils import hash_password


DIRECTOR_EMAIL = "ilyaosipov@yandex.ru"
DIRECTOR_PASSWORD = "12345"
DEMO_PASSWORD = "DemoPass123"

DEMO_USERS = {
    "director": {"email": DIRECTOR_EMAIL, "password": DIRECTOR_PASSWORD, "name": "Илья Осипов"},
    "manager": {"email": "manager.demo@korda.ru", "password": DEMO_PASSWORD, "name": "Марина Менеджер"},
    "legal": {"email": "legal.demo@korda.ru", "password": DEMO_PASSWORD, "name": "Юлия Юрист"},
    "accounting": {"email": "accounting.demo@korda.ru", "password": DEMO_PASSWORD, "name": "Борис Бухгалтер"},
    "office": {"email": "office.demo@korda.ru", "password": DEMO_PASSWORD, "name": "Анна Канцелярия"},
    "warehouse": {"email": "warehouse.demo@korda.ru", "password": DEMO_PASSWORD, "name": "Кирилл Склад"},
    "production": {"email": "production.demo@korda.ru", "password": DEMO_PASSWORD, "name": "Павел Производство"},
}


def now() -> datetime:
    return datetime.now()


def date_text(offset_days: int = 0) -> str:
    return (now() + timedelta(days=offset_days)).strftime("%d.%m.%Y")


def date_time_text(offset_days: int = 0, hour: int = 10, minute: int = 0) -> str:
    base = now() + timedelta(days=offset_days)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%d.%m.%Y %H:%M")


def unix_ts(offset_days: int = 0, hour: int = 10, minute: int = 0) -> int:
    base = now() + timedelta(days=offset_days)
    return int(base.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp())


def ensure_ok(response, label: str) -> dict:
    if response.status_code != 200:
        raise RuntimeError(f"{label}: HTTP {response.status_code} -> {response.text}")
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"{label}: {payload}")
    return payload


def login(email: str, password: str) -> TestClient:
    client = TestClient(app)
    ensure_ok(client.post("/api/login", json={"email": email, "password": password}), f"login:{email}")
    return client


def remove_file_by_url(url: str = "") -> None:
    if not url:
        return
    path = os.path.join(ROOT_DIR, url.lstrip("/"))
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def cleanup_debug_artifacts() -> None:
    conn = get_connection(row_factory=True)
    cur = conn.cursor()

    temp_docs = cur.execute(
        """
        SELECT id, file_url, resolution_task_id
        FROM documents
        WHERE number LIKE 'QA-SIGN-TMP-%'
           OR subject='Tmp sign'
           OR number='DEMO-SIGN-2026-001'
        ORDER BY id
        """
    ).fetchall()
    for row in temp_docs:
        doc_id = int(row["id"])
        resolution_task_id = int(row.get("resolution_task_id") or 0)
        file_rows = cur.execute("SELECT file_url FROM document_file_revisions WHERE document_id=?", (doc_id,)).fetchall()
        for file_row in file_rows:
            remove_file_by_url(file_row["file_url"])
        remove_file_by_url(row["file_url"])
        cur.execute("DELETE FROM edo_signature_registry WHERE entity_type='document' AND entity_id=?", (doc_id,))
        cur.execute("DELETE FROM document_legal_archive WHERE document_id=?", (doc_id,))
        cur.execute("DELETE FROM document_file_revisions WHERE document_id=?", (doc_id,))
        cur.execute("DELETE FROM document_registration_records WHERE document_id=?", (doc_id,))
        cur.execute("DELETE FROM document_lifecycle_events WHERE document_id=?", (doc_id,))
        cur.execute("DELETE FROM document_versions WHERE document_id=?", (doc_id,))
        cur.execute("DELETE FROM document_linked_tasks WHERE document_id=?", (doc_id,))
        cur.execute("DELETE FROM document_print_forms WHERE document_id=?", (doc_id,))
        cur.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        if resolution_task_id:
            cur.execute("DELETE FROM tasks WHERE id=?", (resolution_task_id,))

    cur.execute("DELETE FROM edo_certificates WHERE serial_number LIKE 'TMP-SERIAL-%' OR thumbprint LIKE 'TMP-THUMB-%'")
    cur.execute("DELETE FROM edo_certificates WHERE serial_number='DEMO-SIGN-SERIAL-001' OR thumbprint='DEMO-SIGN-CERT-001'")
    cur.execute("DELETE FROM tasks WHERE title='Резолюция по документу №DEMO-SIGN-2026-001'")
    cur.execute("DELETE FROM error_logs WHERE message LIKE '%_safe_int%'")

    cur.execute("DELETE FROM user_sessions WHERE user_email LIKE 'test_%@example.com'")
    cur.execute("DELETE FROM users WHERE email LIKE 'test_%@example.com'")
    conn.commit()
    conn.close()


def normalize_demo_records() -> None:
    conn = get_connection(row_factory=True)
    cur = conn.cursor()

    team = json.dumps(
        [
            DEMO_USERS["director"]["name"],
            DEMO_USERS["manager"]["name"],
            DEMO_USERS["production"]["name"],
            DEMO_USERS["legal"]["name"],
        ],
        ensure_ascii=False,
    )
    allowed_roles = json.dumps(["Директор", "Менеджер", "Бухгалтерия", "Юрист"], ensure_ascii=False)
    for project_id in (1, 2, 3, 4, 5, 6):
        cur.execute(
            "UPDATE projects SET manager=?, team=?, allowed_roles=? WHERE id=?",
            (DEMO_USERS["manager"]["name"], team, allowed_roles, project_id),
        )
    for contract_id in (1, 2, 3, 4, 5):
        cur.execute(
            "UPDATE contract_master SET manager_name=?, manager_email=? WHERE id=?",
            (DEMO_USERS["manager"]["name"], DEMO_USERS["manager"]["email"], contract_id),
        )

    cur.execute(
        "DELETE FROM contract_master WHERE project_id NOT IN (SELECT id FROM projects) AND project_id <> 0"
    )

    payment_templates = [
        {
            "title": "Поступление аванса по проекту DEMO-ERP-SALES",
            "kind": "incoming",
            "category": "payment",
            "amount": 985000.0,
            "status": "planned",
            "project_id": 1,
            "client_id": 1,
            "contract_id": 1,
            "due_date": date_text(1),
            "comment": "Авансовый платёж от клиента",
        },
        {
            "title": "Оплата поставщику кабеля",
            "kind": "outgoing",
            "category": "purchase",
            "amount": 256500.0,
            "status": "issued",
            "project_id": 1,
            "client_id": 1,
            "contract_id": 1,
            "due_date": date_text(2),
            "comment": "Закупка материалов под продажи и монтаж",
        },
        {
            "title": "Поступление по этапу производства",
            "kind": "incoming",
            "category": "payment",
            "amount": 1240000.0,
            "status": "planned",
            "project_id": 2,
            "client_id": 1,
            "contract_id": 2,
            "due_date": date_text(3),
            "comment": "Оплата после подтверждения готовности партии",
        },
        {
            "title": "Закупка комплектующих шкафа",
            "kind": "outgoing",
            "category": "purchase",
            "amount": 348000.0,
            "status": "approved",
            "project_id": 2,
            "client_id": 1,
            "contract_id": 2,
            "due_date": date_text(4),
            "comment": "Поставка электрощитового оборудования",
        },
        {
            "title": "Поступление по акту КС-2",
            "kind": "incoming",
            "category": "invoice",
            "amount": 640000.0,
            "status": "issued",
            "project_id": 4,
            "client_id": 1,
            "contract_id": 4,
            "due_date": date_text(5),
            "comment": "Закрытие сервисного этапа",
        },
        {
            "title": "Закупка расходников для монтажа",
            "kind": "outgoing",
            "category": "payment",
            "amount": 42000.0,
            "status": "planned",
            "project_id": 4,
            "client_id": 1,
            "contract_id": 4,
            "due_date": date_text(6),
            "comment": "Резерв под сервисные работы",
        },
        {
            "title": "Оплата поставщику ткани",
            "kind": "outgoing",
            "category": "payment",
            "amount": 65000.0,
            "status": "planned",
            "project_id": 2,
            "client_id": 1,
            "contract_id": 2,
            "due_date": date_text(7),
            "comment": "Постоплата за утепляющие материалы",
        },
        {
            "title": "Реализация по проекту путевых листов",
            "kind": "incoming",
            "category": "invoice",
            "amount": 185000.0,
            "status": "planned",
            "project_id": 6,
            "client_id": 2,
            "contract_id": 0,
            "due_date": date_text(8),
            "comment": "Оплата логистического контура",
        },
    ]
    payment_rows = cur.execute("SELECT id FROM finance_payments WHERE id <> 1 ORDER BY id DESC").fetchall()
    for row, data in zip(payment_rows, payment_templates):
        cur.execute(
            """
            UPDATE finance_payments
            SET title=?, kind=?, category=?, amount=?, status=?, project_id=?, client_id=?, contract_id=?, due_date=?, comment=?, paid_date=''
            WHERE id=?
            """,
            (
                data["title"],
                data["kind"],
                data["category"],
                data["amount"],
                data["status"],
                data["project_id"],
                data["client_id"],
                data["contract_id"],
                data["due_date"],
                data["comment"],
                int(row["id"]),
            ),
        )

    cur.execute(
        """
        UPDATE sales_quotes
        SET responsible=?, valid_until=?, comment='Коммерческое предложение для демонстрации полного sales-cycle'
        WHERE id=1
        """,
        (DEMO_USERS["manager"]["name"], date_text(14)),
    )
    cur.execute(
        """
        UPDATE sales_documents_extended
        SET responsible=?, sent_status='delivered', recipient_email=?, sent_at=?, delivered_at=?, payment_due_date=?, shipment_status='shipped'
        WHERE id=1
        """,
        (
            DEMO_USERS["manager"]["name"],
            "demo.erp@korda.local",
            date_time_text(0, 11, 15),
            date_time_text(0, 11, 34),
            date_text(10),
        ),
    )
    cur.execute(
        """
        UPDATE internal_requests
        SET target_role='Склад', assignee_name=?, deadline=?, comment='Внутренняя заявка для демонстрации кросс-функционального маршрута'
        WHERE id=1
        """,
        (DEMO_USERS["warehouse"]["name"], date_text(3)),
    )
    cur.execute(
        """
        UPDATE expense_requests
        SET approver_name=?, approved_by=?, due_date=?, comment='Согласованная расходная заявка по сервисному проекту'
        WHERE id=1
        """,
        (DEMO_USERS["director"]["name"], DEMO_USERS["director"]["email"], date_text(4)),
    )
    cur.execute(
        """
        UPDATE production_orders
        SET responsible=?, planned_start=?, planned_finish=?, comment='Производственный заказ для показа загрузки и статуса выпуска'
        WHERE id=1
        """,
        (DEMO_USERS["production"]["name"], date_text(-2), date_text(5)),
    )
    cur.execute(
        """
        UPDATE service_cases
        SET responsible=?, sla_deadline=?, resolution='Сервисный кейс с контролем SLA и статусом клиента'
        WHERE id=1
        """,
        (DEMO_USERS["production"]["name"], date_text(2)),
    )
    cur.execute(
        """
        UPDATE resource_allocations
        SET resource_name=?, date_from=?, date_to=?, comment='Плановая загрузка монтажного ресурса'
        WHERE id=1
        """,
        (DEMO_USERS["production"]["name"], date_text(0), date_text(6)),
    )
    cur.execute(
        """
        UPDATE documents
        SET resolution_author=?, resolution_assignee=?, resolution_deadline=?
        WHERE number='DEMO-DOC-001'
        """,
        (DEMO_USERS["director"]["name"], DEMO_USERS["office"]["name"], date_text(2)),
    )
    cur.execute(
        """
        UPDATE tasks
        SET author=?, executor=?, deadline=?, description='Подготовить комплект УПД, архив и регистрационную карту документа.'
        WHERE title='Демо поручение по документам'
        """,
        (DEMO_USERS["director"]["name"], DEMO_USERS["office"]["name"], date_text(2)),
    )

    cur.execute("DELETE FROM approval_action_log")
    cur.execute("DELETE FROM approval_sla_events")
    cur.execute("DELETE FROM approvals")
    created_at_pending = date_time_text(0, 9, 45)
    created_at_completed = date_time_text(-1, 16, 10)
    cur.execute(
        """
        INSERT INTO approvals (
            title, item_link, route, current_step, status, history, author, created_at,
            entity_type, entity_id, route_rules, route_context, current_stage_key, current_assignees,
            approval_state, due_at, completed_at, required_comment_on_reject, required_comment_on_return,
            last_action_at, escalation_role
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """,
        (
            "Демо: согласование допсоглашения по проекту DEMO-ERP-DOC",
            "/app",
            json.dumps([DEMO_USERS["legal"]["name"], DEMO_USERS["accounting"]["name"], DEMO_USERS["director"]["name"]], ensure_ascii=False),
            0,
            "pending",
            json.dumps([], ensure_ascii=False),
            DEMO_USERS["manager"]["name"],
            created_at_pending,
            "contract",
            "DEMO-ERP-DOC",
            json.dumps([], ensure_ascii=False),
            json.dumps({"project": "DEMO-ERP-DOC"}, ensure_ascii=False),
            "legal_review",
            json.dumps([DEMO_USERS["legal"]["name"]], ensure_ascii=False),
            json.dumps({"stage": "legal_review"}, ensure_ascii=False),
            unix_ts(2, 18, 0),
            0,
            unix_ts(0, 9, 45),
            "Юрист",
        ),
    )
    completed_history = [
        {"action": "approve", "actor": DEMO_USERS["legal"]["name"], "time": date_time_text(-1, 16, 20)},
        {"action": "approve", "actor": DEMO_USERS["accounting"]["name"], "time": date_time_text(-1, 16, 45)},
        {"action": "approve", "actor": DEMO_USERS["director"]["name"], "time": date_time_text(-1, 17, 5)},
    ]
    cur.execute(
        """
        INSERT INTO approvals (
            title, item_link, route, current_step, status, history, author, created_at,
            entity_type, entity_id, route_rules, route_context, current_stage_key, current_assignees,
            approval_state, due_at, completed_at, required_comment_on_reject, required_comment_on_return,
            last_action_at, escalation_role
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """,
        (
            "Демо: согласование расхода на сервисный выезд",
            "/app",
            json.dumps([DEMO_USERS["legal"]["name"], DEMO_USERS["accounting"]["name"], DEMO_USERS["director"]["name"]], ensure_ascii=False),
            2,
            "completed",
            json.dumps(completed_history, ensure_ascii=False),
            DEMO_USERS["manager"]["name"],
            created_at_completed,
            "expense_request",
            "1",
            json.dumps([], ensure_ascii=False),
            json.dumps({"project": "DEMO-ERP-SVC"}, ensure_ascii=False),
            "completed",
            json.dumps([], ensure_ascii=False),
            json.dumps({"stage": "completed"}, ensure_ascii=False),
            unix_ts(-1, 18, 0),
            unix_ts(-1, 17, 5),
            unix_ts(-1, 17, 5),
            "Директор",
        ),
    )
    conn.commit()
    conn.close()


def ensure_pending_registration() -> None:
    email = "new.manager.demo@korda.ru"
    anonymous = TestClient(app)
    conn = get_connection(row_factory=True)
    cur = conn.cursor()
    row = cur.execute("SELECT email, status FROM users WHERE email=?", (email,)).fetchone()
    if row:
        cur.execute(
            "UPDATE users SET name=?, role=NULL, status='pending', password=? WHERE email=?",
            ("Денис Демонстрационный", hash_password("StrongPass123"), email),
        )
        conn.commit()
        conn.close()
        return
    conn.close()
    ensure_ok(
        anonymous.post(
            "/api/register",
            json={"name": "Денис Демонстрационный", "email": email, "password": "StrongPass123"},
        ),
        "register_demo_pending_user",
    )


def ensure_demo_mailboxes(director_client: TestClient) -> None:
    conn = get_connection(row_factory=True)
    cur = conn.cursor()
    demo_addresses = ["director-demo@korda-demo.ru", "tender-office@korda-demo.ru"]
    account_rows = cur.execute(
        "SELECT id FROM email_accounts WHERE address IN (?, ?)",
        (demo_addresses[0], demo_addresses[1]),
    ).fetchall()
    account_ids = [int(row["id"]) for row in account_rows]
    if account_ids:
        for account_id in account_ids:
            cur.execute("DELETE FROM email_attachments WHERE message_id IN (SELECT id FROM email_messages WHERE account_id=?)", (account_id,))
            cur.execute("DELETE FROM email_messages WHERE account_id=?", (account_id,))
        cur.execute("DELETE FROM email_accounts WHERE id IN (?, ?)", tuple(account_ids[:2]) if len(account_ids) >= 2 else (account_ids[0], account_ids[0]))
    conn.commit()
    conn.close()

    accounts_payload = [
        {
            "label": "Директор / Общая почта",
            "address": demo_addresses[0],
            "login": demo_addresses[0],
            "password": "demo-mail-pass",
            "imap_host": "imap.yandex.ru",
            "imap_port": 993,
            "smtp_host": "smtp.yandex.ru",
            "smtp_port": 465,
            "smtp_login": demo_addresses[0],
            "smtp_password": "demo-mail-pass",
            "inbox_folder": "INBOX",
            "archive_folder": "Archive",
            "is_default": 1,
            "is_active": 0,
        },
        {
            "label": "Тендеры и канцелярия",
            "address": demo_addresses[1],
            "login": demo_addresses[1],
            "password": "demo-mail-pass",
            "imap_host": "imap.yandex.ru",
            "imap_port": 993,
            "smtp_host": "smtp.yandex.ru",
            "smtp_port": 465,
            "smtp_login": demo_addresses[1],
            "smtp_password": "demo-mail-pass",
            "inbox_folder": "INBOX",
            "archive_folder": "Archive",
            "is_default": 0,
            "is_active": 0,
        },
    ]
    for index, payload in enumerate(accounts_payload, start=1):
        ensure_ok(director_client.post("/api/email/accounts", json=payload), f"create_mailbox_{index}")

    conn = get_connection(row_factory=True)
    cur = conn.cursor()
    accounts = cur.execute(
        "SELECT id, address FROM email_accounts WHERE address IN (?, ?) ORDER BY id ASC",
        (demo_addresses[0], demo_addresses[1]),
    ).fetchall()
    account_map = {row["address"]: int(row["id"]) for row in accounts}

    messages = [
        {
            "account_id": account_map[demo_addresses[0]],
            "uid": "demo-mail-001",
            "folder": "INBOX",
            "subject": "Подписанное допсоглашение по проекту DEMO-ERP-DOC",
            "sender": "ООО Демо Контур ERP",
            "sender_email": "contracts@demo-erp.ru",
            "body_preview": "Во вложении подписанное допсоглашение и печатная форма.",
            "body_text": "Во вложении подписанное допсоглашение и печатная форма для загрузки в CRM.",
            "received_at": date_time_text(0, 9, 12),
            "is_read": 0,
            "is_archived": 0,
            "created_at": unix_ts(0, 9, 12),
        },
        {
            "account_id": account_map[demo_addresses[0]],
            "uid": "demo-mail-002",
            "folder": "INBOX",
            "subject": "RE: график оплат по проекту DEMO-ERP-FIN",
            "sender": "Борис Бухгалтер",
            "sender_email": DEMO_USERS["accounting"]["email"],
            "body_preview": "Подтвердил план-факт и обновил сумму постоплаты.",
            "body_text": "План-факт по проекту сверил, постоплату перенес на следующую неделю.",
            "received_at": date_time_text(-1, 15, 40),
            "is_read": 1,
            "is_archived": 0,
            "created_at": unix_ts(-1, 15, 40),
        },
        {
            "account_id": account_map[demo_addresses[1]],
            "uid": "demo-mail-003",
            "folder": "Archive",
            "subject": "Архив: замечания юриста по редакции договора",
            "sender": "Юлия Юрист",
            "sender_email": DEMO_USERS["legal"]["email"],
            "body_preview": "Замечания отработаны, письмо можно убрать в архив.",
            "body_text": "Замечания отработаны, новая версия сохранена в карточке договора.",
            "received_at": date_time_text(-2, 12, 5),
            "is_read": 1,
            "is_archived": 1,
            "created_at": unix_ts(-2, 12, 5),
        },
        {
            "account_id": account_map[demo_addresses[1]],
            "uid": "demo-mail-004",
            "folder": "INBOX",
            "subject": "Новая закупка для проекта DEMO-ERP-PROD",
            "sender": "Кирилл Склад",
            "sender_email": DEMO_USERS["warehouse"]["email"],
            "body_preview": "Поступила заявка на резерв материалов под производственный заказ.",
            "body_text": "Нужно зарезервировать кабель и расходники под производственный заказ DEMO-ERP-PROD.",
            "received_at": date_time_text(0, 11, 4),
            "is_read": 0,
            "is_archived": 0,
            "created_at": unix_ts(0, 11, 4),
        },
    ]
    for item in messages:
        cur.execute(
            """
            INSERT INTO email_messages (
                account_id, uid, folder, subject, sender, sender_email, body_preview, body_text,
                received_at, is_read, is_archived, is_deleted, created_at, synced_at, delivery_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'received')
            """,
            (
                item["account_id"],
                item["uid"],
                item["folder"],
                item["subject"],
                item["sender"],
                item["sender_email"],
                item["body_preview"],
                item["body_text"],
                item["received_at"],
                item["is_read"],
                item["is_archived"],
                item["created_at"],
                item["created_at"],
            ),
        )
    first_message_id = int(
        cur.execute("SELECT id FROM email_messages WHERE uid='demo-mail-001' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    )
    cur.execute(
        """
        INSERT INTO email_attachments (message_id, filename, stored_path, mime_type, size, created_at)
        VALUES (?, 'demo-addendum.pdf', '/generated/demo-addendum.pdf', 'application/pdf', 248320, ?)
        """,
        (first_message_id, unix_ts(0, 9, 13)),
    )
    conn.commit()
    conn.close()


def ensure_demo_chat(clients: dict[str, TestClient]) -> None:
    director_client = clients["director"]
    chats = ensure_ok(director_client.get("/api/chats"), "list_chats")
    chat = next((item for item in chats if item.get("name") == "Демо: Координация запуска"), None)
    if not chat:
        ensure_ok(
            director_client.post(
                "/api/chats",
                json={
                    "name": "Демо: Координация запуска",
                    "creator": "",
                    "participants": [
                        DEMO_USERS["manager"]["name"],
                        DEMO_USERS["legal"]["name"],
                        DEMO_USERS["accounting"]["name"],
                        DEMO_USERS["office"]["name"],
                    ],
                },
            ),
            "create_demo_chat",
        )
        chats = ensure_ok(director_client.get("/api/chats"), "list_chats_after_create")
        chat = next((item for item in chats if item.get("name") == "Демо: Координация запуска"), None)
    if not chat:
        raise RuntimeError("demo chat was not created")

    chat_id = int(chat["id"])
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM global_messages WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

    messages = [
        ("manager", "Собрала пакет по проекту DEMO-ERP-DOC. Нужны финальные визы юриста и бухгалтерии."),
        ("legal", "Проверила формулировки. Можно подписывать, риск по штрафам снят."),
        ("accounting", "План оплат обновлён. Аванс и постоплата заведены в финконтур."),
        ("office", "Письмо зарегистрировала, скан и архивная карточка приложены."),
        ("director", "Оставляем чат в демо-базе как пример кросс-функциональной координации."),
    ]
    for role_key, text in messages:
        ensure_ok(
            clients[role_key].post(
                f"/api/chats/{chat_id}/messages",
                json={"user": "", "role": "", "text": text},
            ),
            f"chat_message_{role_key}",
        )


def ensure_demo_tasks(director_client: TestClient, manager_client: TestClient, legal_client: TestClient) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE title LIKE 'Демо: %'")
    conn.commit()
    conn.close()

    tasks = [
        {
            "title": "Демо: Подготовить финальный пакет клиенту",
            "description": "Собрать договор, УПД, маршрут согласования и архивную карточку.",
            "executor": DEMO_USERS["manager"]["name"],
            "deadline": date_text(1),
            "priority": "high",
            "project_id": 5,
        },
        {
            "title": "Демо: Проверить юридические правки по договору",
            "description": "Сверить редакцию клиента с шаблоном компании и подтвердить подпись.",
            "executor": DEMO_USERS["legal"]["name"],
            "deadline": date_text(2),
            "priority": "high",
            "project_id": 5,
        },
        {
            "title": "Демо: Сверить поступление аванса",
            "description": "Проверить план-факт оплат по проекту DEMO-ERP-FIN и обновить статус платежа.",
            "executor": DEMO_USERS["accounting"]["name"],
            "deadline": date_text(3),
            "priority": "normal",
            "project_id": 3,
        },
    ]
    for payload in tasks:
        ensure_ok(
            director_client.post(
                "/api/tasks",
                json={
                    "title": payload["title"],
                    "description": payload["description"],
                    "author": DEMO_USERS["director"]["name"],
                    "executor": payload["executor"],
                    "deadline": payload["deadline"],
                    "recurrence": "none",
                    "priority": payload["priority"],
                    "project_id": payload["project_id"],
                },
            ),
            f"task_{payload['title']}",
        )

    task_list = ensure_ok(director_client.get("/api/tasks"), "list_tasks")
    title_to_id = {item.get("title"): int(item.get("id")) for item in task_list if item.get("title", "").startswith("Демо: ")}
    if "Демо: Подготовить финальный пакет клиенту" in title_to_id:
        ensure_ok(
            manager_client.put(
                f"/api/tasks/{title_to_id['Демо: Подготовить финальный пакет клиенту']}",
                json={"status": "done", "executor": DEMO_USERS["manager"]["name"], "history": []},
            ),
            "task_done_manager",
        )
    if "Демо: Проверить юридические правки по договору" in title_to_id:
        ensure_ok(
            legal_client.put(
                f"/api/tasks/{title_to_id['Демо: Проверить юридические правки по договору']}",
                json={"status": "В работе", "executor": DEMO_USERS["legal"]["name"], "history": []},
            ),
            "task_in_progress_legal",
        )


def ensure_signed_demo_document(director_client: TestClient) -> None:
    created = ensure_ok(
        director_client.post(
            "/api/documents",
            json={
                "type": "outgoing",
                "number": "DEMO-SIGN-2026-001",
                "d_date": date_text(0),
                "correspondent": "ООО Демо Контур ERP",
                "subject": "Подписанное допсоглашение к проекту DEMO-ERP-DOC",
                "status": "draft",
                "project_id": 5,
                "contract_id": 5,
                "object_id": 0,
                "parent_id": 0,
                "priority": "high",
                "resolution": "Проверить, подписать и отправить клиенту в архив.",
                "resolution_author": DEMO_USERS["director"]["name"],
                "resolution_deadline": date_text(1),
                "resolution_assignee": DEMO_USERS["legal"]["name"],
                "resolution_task_id": 0,
            },
        ),
        "create_signed_demo_document",
    )
    document_id = int(created["id"])
    ensure_ok(
        director_client.post(
            f"/api/documents/{document_id}/upload",
            data={"comment": "Финальная редакция для демонстрации юридически значимого документооборота", "make_current": "1"},
            files={"file": ("demo_addendum.txt", io.BytesIO(b"demo legal package\nrevision 1\n"), "text/plain")},
        ),
        "upload_signed_demo_document",
    )
    certificate = ensure_ok(
        director_client.post(
            "/api/docflow/certificates",
            json={
                "owner_name": DEMO_USERS["director"]["name"],
                "owner_email": DEMO_USERS["director"]["email"],
                "signer_role": "Директор",
                "provider_name": "КриптоПро",
                "thumbprint": "DEMO-SIGN-CERT-001",
                "serial_number": "DEMO-SIGN-SERIAL-001",
                "valid_from": date_text(-30),
                "valid_to": date_text(365),
                "status": "active",
                "comment": "Демо сертификат для показа ЭП",
            },
        ),
        "create_demo_certificate",
    )
    certificate_id = int(certificate["id"])
    ensure_ok(
        director_client.post(
            f"/api/docflow/documents/{document_id}/signatures",
            json={
                "certificate_id": certificate_id,
                "signature_kind": "КЭП",
                "signature_provider": "КриптоПро",
                "comment": "Документ подписан для демонстрации полного docflow-контура",
            },
        ),
        "sign_demo_document",
    )
    ensure_ok(
        director_client.post(
            f"/api/docflow/documents/{document_id}/verify_signatures",
            json={"comment": "Контрольная проверка подписи", "force": 1},
        ),
        "verify_demo_document_signature",
    )
    ensure_ok(
        director_client.post(
            f"/api/docflow/documents/{document_id}/archive_legal",
            json={"comment": "Архивирование подписанного документа для демонстрации"},
        ),
        "archive_demo_document",
    )


def main() -> None:
    cleanup_debug_artifacts()
    normalize_demo_records()
    ensure_pending_registration()

    clients = {
        "director": login(DEMO_USERS["director"]["email"], DEMO_USERS["director"]["password"]),
        "manager": login(DEMO_USERS["manager"]["email"], DEMO_USERS["manager"]["password"]),
        "legal": login(DEMO_USERS["legal"]["email"], DEMO_USERS["legal"]["password"]),
        "accounting": login(DEMO_USERS["accounting"]["email"], DEMO_USERS["accounting"]["password"]),
        "office": login(DEMO_USERS["office"]["email"], DEMO_USERS["office"]["password"]),
    }
    ensure_demo_mailboxes(clients["director"])
    ensure_demo_chat(clients)
    ensure_demo_tasks(clients["director"], clients["manager"], clients["legal"])
    ensure_signed_demo_document(clients["director"])

    conn = get_connection(row_factory=True)
    cur = conn.cursor()
    summary = {
        "projects": cur.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"],
        "pending_users": cur.execute("SELECT COUNT(*) AS c FROM users WHERE status='pending'").fetchone()["c"],
        "mailboxes": cur.execute("SELECT COUNT(*) AS c FROM email_accounts").fetchone()["c"],
        "emails": cur.execute("SELECT COUNT(*) AS c FROM email_messages").fetchone()["c"],
        "tasks": cur.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"],
        "approvals": cur.execute("SELECT COUNT(*) AS c FROM approvals").fetchone()["c"],
        "documents": cur.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"],
        "chat_messages": cur.execute("SELECT COUNT(*) AS c FROM global_messages").fetchone()["c"],
    }
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
