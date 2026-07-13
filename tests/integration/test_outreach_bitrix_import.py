from fastapi.testclient import TestClient

from main import app
from database import get_connection
from tests.test_helpers import create_test_user, run_db_cleanup


def test_outreach_import_accepts_bitrix_export_columns_and_deduplicates():
    director = create_test_user(role="Директор", name_prefix="Bitrix Import Director")
    filename = "bitrix_export_test.csv"
    marker = "BITRIX_IMPORT_TEST"
    rows = [
        {
            "ID": "1001",
            "TITLE": f"Лид Северный Контур {marker}",
            "COMPANY_TITLE": f"ООО Северный Контур {marker}",
            "LAST_NAME": "Петрова",
            "NAME": "Ирина",
            "SECOND_NAME": "Алексеевна",
            "PHONE_WORK": "+7 927 333-78-90",
            "EMAIL_WORK": f"petrova-{marker.lower()}@example.com",
            "POST": "Главный инженер",
            "SOURCE_DESCRIPTION": "Bitrix24: выставка",
            "ASSIGNED_BY_NAME": "Марина Менеджер",
            "COMMENTS": "Просит КП и звонок после обеда",
            "ADDRESS_CITY": "Казань",
            "WEB_WORK": "https://sever-kontur.example",
        },
        {
            "CONTACT_ID": "1002",
            "Компания": f"ООО ТурбоКит {marker}",
            "Полное имя": "Павел Сурков",
            "Мобильный телефон": "+7 831 500-11-77",
            "Рабочий e-mail": f"surkov-{marker.lower()}@example.com",
            "Должность": "Директор по эксплуатации",
            "Источник": "Bitrix24: холодная база",
            "Ответственный": "Илья Осипов",
            "Комментарии": "Интерес к сервисному договору",
            "Город": "Нижний Новгород",
        },
        {
            "ID": "1003",
            "TITLE": "",
            "PHONE_WORK": "",
            "EMAIL_WORK": "",
        },
    ]

    try:
        with TestClient(app) as client:
            login = client.post("/api/login", json={"email": director["email"], "password": director["password"]})
            assert login.status_code == 200

            payload = {
                "filename": filename,
                "source_name": "Bitrix24 export",
                "default_manager_name": "Руководитель продаж",
                "planned_contact_date": "12.07.2026",
                "rows": rows,
            }
            preview = client.post("/api/outreach/prospects/import_preview", json=payload)
            assert preview.status_code == 200
            preview_json = preview.json()
            assert preview_json["recognized_columns"] >= 10
            assert preview_json["columns_total"] >= preview_json["recognized_columns"]
            assert preview_json["created"] == 2
            assert preview_json["updated"] == 0
            assert preview_json["skipped"] == 1
            assert preview_json["problem_rows"] == 1

            first = client.post("/api/outreach/prospects/import_rows", json=payload)
            assert first.status_code == 200
            assert first.json()["created"] == 2
            assert first.json()["updated"] == 0
            assert first.json()["skipped"] == 1

            second_payload = {**payload, "rows": [{**rows[0], "COMMENTS": "Обновлённый комментарий"}, rows[1], rows[2]]}
            second_preview = client.post("/api/outreach/prospects/import_preview", json=second_payload)
            assert second_preview.status_code == 200
            assert second_preview.json()["created"] == 0
            assert second_preview.json()["updated"] == 2
            assert second_preview.json()["skipped"] == 1

            second = client.post("/api/outreach/prospects/import_rows", json=second_payload)
            assert second.status_code == 200
            assert second.json()["created"] == 0
            assert second.json()["updated"] == 2
            assert second.json()["skipped"] == 1

            conn = get_connection(row_factory=True)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM outreach_prospects WHERE source_file=? ORDER BY company_name", (filename,))
                imported = [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

            assert len(imported) == 2
            by_email = {row["email"]: row for row in imported}
            lead = by_email[f"petrova-{marker.lower()}@example.com"]
            assert lead["company_name"] == f"ООО Северный Контур {marker}"
            assert lead["contact_name"] == "Петрова Ирина Алексеевна"
            assert lead["phone"] == "+7 927 333-78-90"
            assert lead["position"] == "Главный инженер"
            assert lead["source_name"] == "Bitrix24: выставка"
            assert lead["manager_name"] == "Марина Менеджер"
            assert lead["notes"] == "Обновлённый комментарий"
            assert lead["city"] == "Казань"
            assert lead["website"] == "https://sever-kontur.example"

            contact = by_email[f"surkov-{marker.lower()}@example.com"]
            assert contact["company_name"] == f"ООО ТурбоКит {marker}"
            assert contact["contact_name"] == "Павел Сурков"
            assert contact["phone"] == "+7 831 500-11-77"
            assert contact["position"] == "Директор по эксплуатации"
            assert contact["source_name"] == "Bitrix24: холодная база"
            assert contact["manager_name"] == "Илья Осипов"
            assert contact["planned_contact_date"] == "12.07.2026"
    finally:
        run_db_cleanup(
            [
                ("DELETE FROM outreach_activities WHERE prospect_id IN (SELECT id FROM outreach_prospects WHERE source_file=? OR company_name LIKE ?)", (filename, f"%{marker}%")),
                ("DELETE FROM outreach_prospects WHERE source_file=? OR company_name LIKE ?", (filename, f"%{marker}%")),
                ("DELETE FROM outreach_import_batches WHERE source_filename=?", (filename,)),
                ("DELETE FROM user_sessions WHERE user_email=?", (director["email"],)),
                ("DELETE FROM users WHERE email=?", (director["email"],)),
            ]
        )
