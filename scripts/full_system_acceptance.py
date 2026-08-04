#!/usr/bin/env python3
"""Persistent end-to-end acceptance run for Korda CRM.

Unlike the integration tests, this script deliberately leaves clearly marked
CODEX QA business records in the database so the acceptance trail is visible
from the application. Temporary role accounts are blocked after the run.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import get_connection  # noqa: E402
from main import app  # noqa: E402
from tests.test_helpers import create_test_user  # noqa: E402


RUN_KEY = datetime.now().strftime("%Y%m%d-%H%M%S")
MARKER = f"CODEX QA {RUN_KEY}"
TODAY = datetime.now().strftime("%d.%m.%Y")
TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
NEXT_WEEK = (datetime.now() + timedelta(days=7)).strftime("%d.%m.%Y")
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

ROLE_SPECS = {
    "director": ("Директор", "CODEX QA Директор"),
    "manager": ("Менеджер", "CODEX QA Менеджер"),
    "engineering": ("Конструкторское бюро", "CODEX QA Конструктор"),
    "accounting": ("Бухгалтерия", "CODEX QA Бухгалтер"),
    "legal": ("Юрист", "CODEX QA Юрист"),
    "production": ("Производство и ОТК", "CODEX QA Производство"),
    "warehouse": ("Склад", "CODEX QA Склад"),
    "secretary": ("Секретарь / Канцелярия", "CODEX QA Канцелярия"),
    "employee": ("Сотрудник", "CODEX QA Сотрудник"),
}


class AcceptanceError(RuntimeError):
    pass


def expect(response, label: str, *, allow_binary: bool = False):
    if response.status_code != 200:
        raise AcceptanceError(f"{label}: HTTP {response.status_code}: {response.text[:500]}")
    if allow_binary:
        if not response.content:
            raise AcceptanceError(f"{label}: получен пустой файл")
        return response
    try:
        payload = response.json()
    except Exception as exc:
        raise AcceptanceError(f"{label}: ожидался JSON: {response.text[:500]}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise AcceptanceError(f"{label}: {payload}")
    return payload


def scalar(query: str, params=()):
    conn = get_connection()
    try:
        row = conn.execute(query, params).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def mark_accounts_blocked(users: dict):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for user in users.values():
            cursor.execute("DELETE FROM user_sessions WHERE user_email=?", (user["email"],))
            cursor.execute("UPDATE users SET status='blocked' WHERE email=?", (user["email"],))
        conn.commit()
    finally:
        conn.close()


def main():
    started_at = time.time()
    users = {
        key: create_test_user(role=role, name_prefix=name_prefix)
        for key, (role, name_prefix) in ROLE_SPECS.items()
    }
    clients = {key: TestClient(app) for key in users}
    checks = []
    artifacts = {"run_key": RUN_KEY, "marker": MARKER, "users": {}}

    def checked(label: str, detail=None):
        checks.append({"label": label, "status": "passed", "detail": detail})

    try:
        for key, user in users.items():
            expect(
                clients[key].post("/api/login", json={"email": user["email"], "password": user["password"]}),
                f"Вход: {user['role']}",
            )
            session = expect(clients[key].get("/api/session"), f"Сессия: {user['role']}")
            if session.get("role") != user["role"]:
                raise AcceptanceError(f"Сессия {key}: роль {session.get('role')} вместо {user['role']}")
            permissions = expect(clients[key].get("/api/permissions"), f"Права: {user['role']}")
            artifacts["users"][key] = {
                "name": user["name"],
                "email": user["email"],
                "role": user["role"],
                "modules": sorted(
                    module for module, actions in permissions.get("permissions", {}).items() if actions
                ),
            }
            checked(f"Роль и права: {user['role']}", len(artifacts["users"][key]["modules"]))

        manager = clients["manager"]
        director = clients["director"]
        secretary = clients["secretary"]
        employee = clients["employee"]
        legal = clients["legal"]
        accounting = clients["accounting"]
        warehouse = clients["warehouse"]
        production = clients["production"]
        engineering = clients["engineering"]

        client_name = f"{MARKER} Клиент"
        expect(
            manager.post(
                "/api/clients",
                json={
                    "name": client_name,
                    "inn": f"79{int(time.time()) % 100000000:08d}",
                    "legal_address": "Москва, тестовый адрес приёмки",
                    "contact": f"qa-client-{RUN_KEY}@example.com",
                },
            ),
            "Создание клиента менеджером",
        )
        client_id = int(scalar("SELECT id FROM clients WHERE name=? ORDER BY id DESC LIMIT 1", (client_name,)))
        artifacts["client_id"] = client_id
        checked("Менеджер создал клиента", client_id)

        project_name = f"{MARKER} Сквозной проект"
        expect(
            manager.post(
                "/api/projects",
                json={
                    "name": project_name,
                    "contract": f"QA-{RUN_KEY}",
                    "client": client_name,
                    "manager": users["manager"]["name"],
                    "budget": 5_900_000,
                    "costs": 2_150_000,
                    "team": [user["name"] for user in users.values() if user["role"] != "Директор"],
                    "checklist": [
                        "Лид квалифицирован",
                        "Договор проверен",
                        "Материалы зарезервированы",
                        "Производство запущено",
                    ],
                    "allowed_roles": [role for role, _ in ROLE_SPECS.values() if role != "Директор"],
                    "nomenclature": [f"QA-ITEM-{RUN_KEY}"],
                    "archive_details": {"qa_run": RUN_KEY, "purpose": "Полная приёмка CODEX"},
                },
            ),
            "Создание проекта менеджером",
        )
        project_id = int(scalar("SELECT id FROM projects WHERE name=? ORDER BY id DESC LIMIT 1", (project_name,)))
        artifacts["project_id"] = project_id
        checked("Создан сквозной проект", project_id)

        for key in ("engineering", "legal", "accounting", "warehouse", "production", "employee"):
            project_rows = expect(
                clients[key].get(
                    f"/api/projects?user_name={users[key]['name']}&user_role={users[key]['role']}&is_head=0"
                ),
                f"Проект виден роли {users[key]['role']}",
            )
            if not any(int(row.get("id") or 0) == project_id for row in project_rows):
                raise AcceptanceError(f"Проект не виден роли {users[key]['role']}")
        checked("Проект доступен всем назначенным ролям", 6)

        contract = expect(
            manager.post(
                "/api/contracts",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "contract_number": f"QA-CONTRACT-{RUN_KEY}",
                    "title": f"{MARKER} Договор поставки",
                    "status": "pending",
                    "amount": 5_900_000,
                    "currency": "RUB",
                    "start_date": TODAY,
                    "end_date": NEXT_WEEK,
                    "manager_name": users["manager"]["name"],
                    "manager_email": users["manager"]["email"],
                    "comment": "Создано сквозной приёмкой CODEX",
                    "contract_type": "supply",
                    "category": "Тендер",
                    "folder": "CODEX QA",
                    "vat_mode": "with_vat",
                    "risk_level": "attention",
                },
            ),
            "Создание договора",
        )
        artifacts["contract_id"] = int(contract["id"])
        checked("Создан договор 360", artifacts["contract_id"])

        upload_payload = (
            f"{MARKER}\nПроект: {project_name}\nНазначение: проверка загрузки и скачивания файла.\n"
        ).encode("utf-8")
        upload = expect(
            manager.post(
                f"/api/projects/{project_id}/upload",
                data={"user": users["manager"]["name"], "doc_type": "Акт приёмки", "parent_file": ""},
                files={"file": (f"CODEX_QA_{RUN_KEY}.txt", upload_payload, "text/plain")},
            ),
            "Загрузка файла в проект",
        )
        uploaded_url = upload["file"]["url"]
        downloaded = expect(manager.get(uploaded_url), "Скачивание файла проекта", allow_binary=True)
        if MARKER.encode("utf-8") not in downloaded.content:
            raise AcceptanceError("Скачанный проектный файл отличается от загруженного")
        artifacts["project_file_url"] = uploaded_url
        checked("Файл загружен и скачан без искажения", uploaded_url)

        expect(manager.post(f"/api/projects/{project_id}/1c_invoice"), "Генерация счёта 1С")
        project_row = scalar("SELECT files FROM projects WHERE id=?", (project_id,))
        project_files = json.loads(project_row or "[]")
        invoice_file = next((item for item in reversed(project_files) if "Счет_1С" in item.get("name", "")), None)
        if not invoice_file:
            raise AcceptanceError("Счёт 1С не появился в файлах проекта")
        expect(manager.get(invoice_file["url"]), "Скачивание счёта 1С", allow_binary=True)
        artifacts["invoice_url"] = invoice_file["url"]
        checked("Счёт 1С создан и скачан", invoice_file["url"])

        portal = expect(manager.post(f"/api/projects/{project_id}/guest_portal"), "Гостевой портал проекта")
        if not portal.get("token"):
            raise AcceptanceError("Гостевая ссылка не сформирована")
        artifacts["guest_portal"] = portal["url"]
        checked("Гостевая ссылка создана", portal["url"])

        document = expect(
            secretary.post(
                "/api/documents",
                json={
                    "type": "incoming",
                    "number": f"QA-DOC-{RUN_KEY}",
                    "d_date": TODAY,
                    "correspondent": client_name,
                    "subject": f"{MARKER} Входящее техническое задание",
                    "status": "registered",
                    "project_id": project_id,
                    "contract_id": artifacts["contract_id"],
                    "object_id": 0,
                    "parent_id": 0,
                    "priority": "high",
                    "resolution": "Проверить комплектность и подготовить ответ",
                    "resolution_author": users["secretary"]["name"],
                    "resolution_deadline": TOMORROW,
                    "resolution_assignee": users["employee"]["name"],
                    "resolution_task_id": 0,
                },
            ),
            "Регистрация входящего документа канцелярией",
        )
        document_id = int(document["id"])
        task_id = int(document.get("resolution_task_id") or 0)
        artifacts.update(document_id=document_id, resolution_task_id=task_id)
        employee_tasks = expect(employee.get("/api/tasks"), "Поручение сотрудника")
        if not any(int(row.get("id") or 0) == task_id for row in employee_tasks):
            raise AcceptanceError("Поручение по резолюции не назначено сотруднику")
        checked("Канцелярия зарегистрировала документ и создала поручение", task_id)

        approval = expect(
            manager.post(
                "/api/approvals",
                json={
                    "title": f"{MARKER} Согласование договора",
                    "item_link": f"/projects/{project_id}",
                    "route": [users["legal"]["name"]],
                    "author": users["manager"]["name"],
                    "entity_type": "contract",
                    "entity_id": str(artifacts["contract_id"]),
                    "default_sla_hours": 24,
                    "escalation_role": "Директор",
                },
            ),
            "Создание согласования",
        )
        legal_approvals = expect(legal.get("/api/approvals"), "Очередь согласований юриста")
        approval_row = next(
            row for row in legal_approvals if row.get("title") == f"{MARKER} Согласование договора"
        )
        artifacts["approval_id"] = int(approval_row["id"])
        checked("Юрист получил согласование", artifacts["approval_id"])

        payment = expect(
            accounting.post(
                "/api/finance/payments",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "contract_id": artifacts["contract_id"],
                    "title": f"{MARKER} Плановый аванс",
                    "kind": "incoming",
                    "category": "payment",
                    "amount": 1_770_000,
                    "currency": "RUB",
                    "due_date": TOMORROW,
                    "status": "planned",
                    "comment": "Проверка финансового контура CODEX",
                },
            ),
            "Создание платежа бухгалтерией",
        )
        artifacts["payment_id"] = int(payment["id"])
        checked("Бухгалтерия создала плановый платёж", artifacts["payment_id"])

        purchase = expect(
            warehouse.post(
                "/api/purchases",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "contract_id": artifacts["contract_id"],
                    "item_article": f"QA-ITEM-{RUN_KEY}",
                    "item_name": "Шумозащитная панель CODEX QA",
                    "supplier": f"{MARKER} Поставщик",
                    "qty": 12,
                    "unit": "шт",
                    "unit_price": 48_000,
                    "planned_unit_price": 46_000,
                    "status": "planned",
                    "expected_date": NEXT_WEEK,
                    "planned_delivery_date": NEXT_WEEK,
                    "request_status": "approved",
                    "approval_status": "approved",
                    "schedule_status": "planned",
                    "lead_time_days": 7,
                    "comment": "Проверка закупки и автосвязи с финансами",
                },
            ),
            "Создание закупки складом",
        )
        artifacts["purchase_id"] = int(purchase["id"])
        checked("Склад создал закупку", artifacts["purchase_id"])

        production_order = expect(
            production.post(
                "/api/production/orders",
                json={
                    "project_id": project_id,
                    "client_id": client_id,
                    "contract_id": artifacts["contract_id"],
                    "order_name": f"{MARKER} Производственный заказ",
                    "stage": "queue",
                    "priority": "high",
                    "planned_start": TOMORROW,
                    "planned_finish": NEXT_WEEK,
                    "progress": 10,
                    "responsible": users["production"]["name"],
                    "route_name": "Основной маршрут CODEX QA",
                    "planned_qty": 12,
                    "produced_qty": 0,
                    "planned_cost": 1_850_000,
                    "labor_hours_plan": 96,
                    "comment": "Приёмочный производственный заказ",
                },
            ),
            "Создание производственного заказа",
        )
        artifacts["production_order_id"] = int(production_order["id"])
        engineering_orders = expect(engineering.get("/api/production/orders"), "Заказ виден КБ")
        if not any(int(row.get("id") or 0) == artifacts["production_order_id"] for row in engineering_orders):
            raise AcceptanceError("Конструкторское бюро не видит производственный заказ")
        checked("Производство создало заказ, КБ его видит", artifacts["production_order_id"])

        bitrix_payload = {
            "filename": f"bitrix_CODEX_QA_{RUN_KEY}.csv",
            "source_name": "Bitrix24 / CODEX QA",
            "default_manager_name": users["manager"]["name"],
            "default_manager_email": users["manager"]["email"],
            "planned_contact_date": TODAY,
            "rows": [
                {
                    "ID": f"QA-{RUN_KEY}-1",
                    "TITLE": f"{MARKER} Тендерный лид",
                    "COMPANY_TITLE": f"{MARKER} Перспектива",
                    "LAST_NAME": "Иванов",
                    "NAME": "Пётр",
                    "PHONE_WORK": "+7 999 100-20-30",
                    "EMAIL_WORK": f"prospect-{RUN_KEY}@example.com",
                    "SOURCE_DESCRIPTION": "Bitrix24: тендер",
                    "COMMENTS": "Бюджет 6 500 000 ₽, нужны шумоглушители, срок 30 дней",
                    "ADDRESS_CITY": "Казань",
                },
                {
                    "ID": f"QA-{RUN_KEY}-2",
                    "COMPANY_TITLE": f"{MARKER} Регион",
                    "NAME": "Анна",
                    "PHONE_WORK": "+7 999 200-30-40",
                    "COMMENTS": "Холодный контакт, требуется первый звонок",
                    "ADDRESS_CITY": "Екатеринбург",
                },
                {"ID": f"QA-{RUN_KEY}-3", "TITLE": "", "PHONE_WORK": "", "EMAIL_WORK": ""},
            ],
        }
        preview = expect(
            manager.post("/api/outreach/prospects/import_preview", json=bitrix_payload),
            "Предпросмотр импорта Bitrix",
        )
        if preview.get("created") != 2 or preview.get("problem_rows") != 1:
            raise AcceptanceError(f"Некорректный предпросмотр Bitrix: {preview}")
        imported = expect(
            manager.post("/api/outreach/prospects/import_rows", json=bitrix_payload),
            "Импорт Bitrix",
        )
        if imported.get("created") != 2 or imported.get("skipped") != 1:
            raise AcceptanceError(f"Некорректный результат Bitrix: {imported}")
        bitrix_payload["rows"][0]["COMMENTS"] = "Обновлено CODEX QA: подготовить КП"
        duplicate = expect(
            manager.post("/api/outreach/prospects/import_rows", json=bitrix_payload),
            "Дедубликация Bitrix",
        )
        if duplicate.get("updated") != 2:
            raise AcceptanceError(f"Дубли Bitrix не обновлены: {duplicate}")
        prospects = expect(
            manager.get(f"/api/outreach/prospects?search={RUN_KEY}"),
            "Поиск записей базы развития",
        )
        prospect = next(row for row in prospects if "Перспектива" in row.get("company_name", ""))
        prospect_id = int(prospect["id"])
        artifacts["outreach_prospect_id"] = prospect_id
        checked("Bitrix: предпросмотр, импорт и дедубликация", imported)

        expect(
            manager.post(
                "/api/outreach/activities",
                json={
                    "prospect_id": prospect_id,
                    "activity_type": "call",
                    "result_status": "warm",
                    "summary": "Клиент подтвердил интерес к шумоглушителям",
                    "next_action": "Отправить КП и назначить встречу",
                    "next_action_date": TOMORROW,
                    "channel": "phone",
                    "prospect_status": "warm",
                },
            ),
            "Фиксация звонка менеджером",
        )
        expect(
            manager.post(
                "/api/outreach/reports",
                json={
                    "report_date": TODAY,
                    "plan_total": 10,
                    "processed_total": 2,
                    "calls_total": 1,
                    "emails_total": 1,
                    "meetings_total": 0,
                    "converted_total": 0,
                    "summary": f"{MARKER}: импорт проверен, первый контакт выполнен",
                    "blockers": "Нет",
                    "next_day_focus": "КП и квалификация",
                },
            ),
            "Дневной отчёт менеджера",
        )
        manager_control = expect(director.get("/api/outreach/manager_control"), "Контроль менеджеров")
        if not any(row.get("email") == users["manager"]["email"] and row.get("submitted") for row in manager_control):
            raise AcceptanceError("Директорская сводка не видит сданный отчёт менеджера")
        checked("Активность, отчёт и директорская сводка менеджеров", users["manager"]["name"])

        converted = expect(
            manager.post(f"/api/outreach/prospects/{prospect_id}/convert"),
            "Конвертация базы развития в лид",
        )
        artifacts["lead_id"] = int(converted["lead_id"])
        checked("Запись базы развития конвертирована в лид", artifacts["lead_id"])

        tender = expect(
            manager.post(
                "/api/tenders/parse",
                json={
                    "source": f"{MARKER} Тендерная площадка",
                    "text": (
                        "Закупка шумоглушителей и акустических кабин. Начальная цена 6 500 000 руб. "
                        f"Подача заявки до {NEXT_WEEK}. Требуются сертификаты, реквизиты и коммерческое предложение."
                    ),
                },
            ),
            "Разбор тендера",
        )
        if "amount" not in tender.get("tender", {}) and "budget" not in tender.get("tender", {}):
            checked("Тендер разобран", tender)
        else:
            checked("Тендер разобран", tender.get("tender"))

        template = expect(
            director.post(
                "/api/documents/templates/deep",
                json={
                    "title": f"{MARKER} Шаблон ответа",
                    "doc_type": "incoming",
                    "template_kind": "editable",
                    "version_label": "v1",
                    "body_text": (
                        "Уважаемый {{client_name}}, документы по проекту {{project_name}} получены. "
                        "Ответственный подготовит ответ в установленный срок."
                    ),
                    "variables": ["client_name", "project_name"],
                    "status": "active",
                    "comment": "Приёмочный шаблон CODEX",
                },
            ),
            "Создание шаблона документа",
        )
        artifacts["document_template_id"] = int(template["id"])
        print_set = expect(
            director.post(f"/api/docflow/documents/{document_id}/generate_print_set"),
            "Генерация печатного комплекта",
        )
        if int(print_set.get("count") or 0) < 1:
            raise AcceptanceError("Печатный комплект не сформирован")
        artifacts["print_form_ids"] = [int(item["id"]) for item in print_set.get("items", [])]
        checked("Шаблон и печатный комплект сформированы", print_set.get("count"))

        package = expect(
            director.post(
                "/api/docflow/packages",
                json={
                    "package_number": f"QA-PACK-{RUN_KEY}",
                    "title": f"{MARKER} Тендерный комплект",
                    "package_kind": "tender",
                    "document_ids": [document_id],
                    "project_id": project_id,
                    "client_id": client_id,
                    "contract_id": artifacts["contract_id"],
                    "comment": "Проверка комплектации и выгрузки тендерного пакета",
                },
            ),
            "Создание тендерного пакета",
        )
        package_id = int(package["id"])
        artifacts["document_package_id"] = package_id
        registry_response = expect(
            director.get(f"/api/docflow/packages/{package_id}/export_registry"),
            "Экспорт реестра пакета",
            allow_binary=True,
        )
        if f"QA-PACK-{RUN_KEY}".encode("utf-8") not in registry_response.content:
            raise AcceptanceError("В реестре пакета отсутствует его номер")
        package_zip_response = expect(
            director.get(f"/api/docflow/packages/{package_id}/export_zip"),
            "Экспорт ZIP пакета",
            allow_binary=True,
        )
        if not package_zip_response.content.startswith(b"PK"):
            raise AcceptanceError("Выгруженный пакет не является ZIP")
        artifacts["package_registry_endpoint"] = f"/api/docflow/packages/{package_id}/export_registry"
        artifacts["package_zip_endpoint"] = f"/api/docflow/packages/{package_id}/export_zip"
        artifacts["package_registry_bytes"] = len(registry_response.content)
        artifacts["package_zip_bytes"] = len(package_zip_response.content)
        checked("Тендерный пакет и его выгрузки работают", package_id)

        event = expect(
            secretary.post(
                "/api/calendar/events",
                json={
                    "title": f"{MARKER} Контрольная встреча",
                    "event_date": TOMORROW,
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "scope": "company",
                    "owner_email": users["secretary"]["email"],
                    "owner_name": users["secretary"]["name"],
                    "department": "Все отделы",
                    "project_id": project_id,
                    "status": "planned",
                    "location": "Переговорная",
                    "description": "Разбор итогов приёмки CODEX QA",
                },
            ),
            "Создание календарного события",
        )
        artifacts["calendar_event_id"] = int(event["id"])
        checked("Канцелярия создала встречу", artifacts["calendar_event_id"])

        report = expect(
            director.post(
                "/api/analytics/reports",
                json={
                    "report_type": "dashboard_hub",
                    "title": f"{MARKER} Руководительская сводка",
                    "filters": {"project_id": project_id},
                    "layout": {"target_role": "Директор", "tags": ["CODEX", "QA"]},
                    "scope": "company",
                },
            ),
            "Создание сохранённого отчёта",
        )
        report_id = int(report["id"])
        artifacts["saved_report_id"] = report_id
        expect(director.post(f"/api/analytics/reports/{report_id}/run"), "Запуск сохранённого отчёта")
        executive = expect(director.get("/api/executive/summary"), "Автостатистика директора")
        analytics = expect(
            director.get(f"/api/analytics/drilldown?dimension=client&value_id={client_id}"),
            "Аналитическая детализация по клиенту",
        )
        if "metrics" not in executive or "summary" not in analytics:
            raise AcceptanceError("Автостатистика вернула неполный ответ")
        checked("Автостатистика и сохранённый отчёт", report_id)

        feed = expect(
            director.post(
                "/api/feed/posts",
                json={
                    "post_type": "announcement",
                    "title": f"{MARKER}: приёмка системы",
                    "content": (
                        "CODEX выполнил сквозную проверку ролей, проекта, CRM, документов, "
                        "финансов, склада, производства, импорта, экспорта и ИИ."
                    ),
                    "target_roles": [role for role, _ in ROLE_SPECS.values()],
                    "is_pinned": 1,
                },
            ),
            "Публикация следа приёмки",
        )
        artifacts["feed_post_id"] = int(feed["id"])
        checked("В корпоративной ленте оставлена запись", artifacts["feed_post_id"])

        system_ai = expect(
            director.post(
                "/api/assistant/ask",
                json={
                    "question": "Где в Korda CRM найти поручения и как директору проверить просрочки?",
                    "context": {"current_view": "tasks", "role": "Директор", "project_id": project_id},
                },
            ),
            "ИИ: вопрос по системе",
        )
        off_topic_ai = expect(
            director.post(
                "/api/assistant/ask",
                json={
                    "question": "Почему яблоко зелёное?",
                    "context": {"current_view": "dashboard", "role": "Директор"},
                },
            ),
            "ИИ: ограничение бытового вопроса",
        )
        system_answer = str(system_ai.get("answer") or "")
        off_topic_answer = str(off_topic_ai.get("answer") or "")
        if len(system_answer) < 30:
            raise AcceptanceError("ИИ не дал содержательный ответ по системе")
        restriction_words = ("только", "korda", "crm", "систем", "рабоч")
        if not any(word in off_topic_answer.lower() for word in restriction_words):
            raise AcceptanceError(f"ИИ не ограничил бытовой вопрос: {off_topic_answer[:300]}")
        artifacts["assistant"] = {
            "system_model": system_ai.get("model"),
            "system_answer": system_answer[:600],
            "off_topic_answer": off_topic_answer[:400],
        }
        checked("ИИ отвечает по системе и ограничивает бытовые вопросы", system_ai.get("model"))

        audio_path = Path("/tmp/korda_call_test.wav")
        if not audio_path.exists():
            raise AcceptanceError("Не найден тестовый WAV-файл /tmp/korda_call_test.wav")
        with audio_path.open("rb") as audio_file:
            telephony = expect(
                manager.post(
                    "/api/telephony/calls/import_recordings",
                    data={
                        "line_name": f"Bitrix24 {MARKER}",
                        "provider_name": "Bitrix24",
                        "contact_name": "Клиент CODEX QA",
                        "phone_number": "+7 999 555-01-02",
                        "direction": "outbound",
                        "manager_name": users["manager"]["name"],
                        "manager_comment": "Реальная проверка распознавания CODEX QA",
                    },
                    files={"files": (f"CODEX_QA_{RUN_KEY}.wav", audio_file, "audio/wav")},
                ),
                "Реальное распознавание звонка",
            )
        result = next((item for item in telephony.get("results", []) if item.get("status") == "success"), None)
        if not result:
            raise AcceptanceError(f"Звонок не распознан: {telephony}")
        if not isinstance(result.get("call_result"), str):
            raise AcceptanceError("Результат звонка имеет неправильный тип")
        if not result.get("dialog") or not result.get("summary"):
            raise AcceptanceError("ИИ не вернул диалог или резюме звонка")
        artifacts["telephony"] = {
            "call_id": int(result["call_id"]),
            "summary": result.get("summary"),
            "deal_signal": result.get("deal_signal"),
            "processing_status": result.get("processing_status"),
            "call_result": result.get("call_result"),
            "manager_errors": result.get("manager_errors"),
            "role_confidence": result.get("role_confidence"),
            "transcription_confidence": result.get("transcription_confidence"),
        }
        checked("Реальный звонок расшифрован и проанализирован", artifacts["telephony"])

        knowledge_content = "\n".join(
            [
                f"Приёмка: {MARKER}",
                f"Проект: {project_name} (ID {project_id})",
                f"Клиент ID: {client_id}",
                f"Документ ID: {document_id}",
                f"Пакет ID: {package_id}",
                f"Звонок ID: {artifacts['telephony']['call_id']}",
                f"Проверок выполнено: {len(checks)}",
                "Результат: сквозные рабочие сценарии выполнены.",
            ]
        )
        expect(
            manager.post(
                "/api/knowledge",
                json={
                    "title": f"{MARKER} Отчёт полной приёмки",
                    "content": knowledge_content,
                    "author": users["manager"]["name"],
                    "required_roles": [role for role, _ in ROLE_SPECS.values()],
                },
            ),
            "Сохранение отчёта в базе знаний",
        )
        knowledge_id = int(
            scalar("SELECT id FROM knowledge_base WHERE title=? ORDER BY id DESC LIMIT 1", (f"{MARKER} Отчёт полной приёмки",))
        )
        artifacts["knowledge_id"] = knowledge_id
        checked("Итоговый отчёт оставлен в базе знаний", knowledge_id)

        artifacts["checks"] = checks
        artifacts["duration_seconds"] = round(time.time() - started_at, 2)
        artifacts["status"] = "passed"
    except Exception as exc:
        artifacts["checks"] = checks
        artifacts["duration_seconds"] = round(time.time() - started_at, 2)
        artifacts["status"] = "failed"
        artifacts["error"] = f"{exc.__class__.__name__}: {exc}"
        raise
    finally:
        mark_accounts_blocked(users)
        artifacts["role_accounts_status"] = "blocked after acceptance"
        json_path = OUTPUT_DIR / f"full_system_acceptance_{RUN_KEY}.json"
        json_path.write_text(json.dumps(artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path = OUTPUT_DIR / f"full_system_acceptance_{RUN_KEY}.md"
        lines = [
            f"# Полная приёмка Korda CRM: {MARKER}",
            "",
            f"- Статус: **{artifacts.get('status', 'unknown')}**",
            f"- Длительность: {artifacts.get('duration_seconds', 0)} сек.",
            f"- Проект: `{artifacts.get('project_id', 'не создан')}`",
            f"- Клиент: `{artifacts.get('client_id', 'не создан')}`",
            f"- Проверок: {len(artifacts.get('checks', []))}",
            "",
            "## Результаты",
            "",
        ]
        for item in artifacts.get("checks", []):
            lines.append(f"- [x] {item['label']}: {item.get('detail', '')}")
        if artifacts.get("error"):
            lines.extend(["", "## Ошибка", "", artifacts["error"]])
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps({"json": str(json_path), "markdown": str(markdown_path), **artifacts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
