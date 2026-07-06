import html
import time

from database import get_connection


def _safe(value) -> str:
    return html.escape(str(value or ""))


def _money(value, currency: str = "RUB") -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,.2f}".replace(",", " ") + f" {_safe(currency or 'RUB')}"


def _row(conn, sql: str, params: tuple = ()) -> dict:
    found = conn.execute(sql, params).fetchone()
    return dict(found) if found else {}


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _page(title: str, meta: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{_safe(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color:#111827; margin:32px; }}
    .top {{ display:flex; justify-content:space-between; gap:24px; border-bottom:2px solid #111827; padding-bottom:16px; margin-bottom:24px; }}
    h1 {{ font-size:24px; margin:0 0 6px; }}
    h2 {{ font-size:16px; margin:24px 0 10px; }}
    .muted {{ color:#667085; font-size:12px; }}
    .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:12px 24px; margin:14px 0 22px; }}
    .field {{ border-bottom:1px solid #d0d5dd; padding:7px 0; }}
    .label {{ color:#667085; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
    .value {{ font-size:14px; margin-top:3px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
    th, td {{ border:1px solid #d0d5dd; padding:8px; font-size:13px; text-align:left; vertical-align:top; }}
    th {{ background:#f2f4f7; }}
    .total {{ text-align:right; font-size:18px; font-weight:700; margin-top:18px; }}
    .sign {{ display:grid; grid-template-columns:1fr 1fr; gap:48px; margin-top:48px; }}
    .sign div {{ border-top:1px solid #111827; padding-top:8px; font-size:12px; color:#475467; }}
    .print-btn {{ position:fixed; right:24px; top:18px; }}
    @media print {{ .print-btn {{ display:none; }} body {{ margin:14mm; }} }}
  </style>
</head>
<body>
  <button class="print-btn" onclick="window.print()">Печать</button>
  <div class="top"><div><h1>{_safe(title)}</h1><div class="muted">{_safe(meta)}</div></div><div class="muted">KORDA · {time.strftime('%d.%m.%Y %H:%M')}</div></div>
  {body}
</body>
</html>"""


def _fields(items: list[tuple[str, object]]) -> str:
    return '<div class="grid">' + ''.join(
        f'<div class="field"><div class="label">{_safe(label)}</div><div class="value">{_safe(value)}</div></div>'
        for label, value in items
    ) + '</div>'


def _sales_print(conn, form_type: str, entity_id: int) -> tuple[str, str, str]:
    row = _row(
        conn,
        """
        SELECT s.*, COALESCE(c.name, '') AS client_name, COALESCE(p.name, '') AS project_name
        FROM sales_documents_extended s
        LEFT JOIN clients c ON c.id=s.client_id
        LEFT JOIN projects p ON p.id=s.project_id
        WHERE s.id=?
        """,
        (entity_id,),
    )
    if not row:
        return "", "", ""
    title_map = {"invoice": "Счёт", "act": "Акт", "upd": "УПД / реестр", "registry": "УПД / реестр"}
    title = f"{title_map.get(form_type, 'Печатная форма')} №{row.get('doc_number') or row.get('id')}"
    body = _fields([
        ("Дата", row.get("doc_date")),
        ("Контрагент", row.get("client_name") or "не указан"),
        ("Проект", row.get("project_name") or "не указан"),
        ("Статус", row.get("status")),
        ("Оплата", row.get("payment_status")),
    ])
    body += f"""
    <table><thead><tr><th>№</th><th>Наименование</th><th>Количество</th><th>Цена</th><th>Сумма</th></tr></thead>
    <tbody><tr><td>1</td><td>{_safe(row.get('comment') or row.get('doc_type') or 'Работы / услуги')}</td><td>1</td><td>{_money(row.get('amount'), row.get('currency'))}</td><td>{_money(row.get('amount'), row.get('currency'))}</td></tr></tbody></table>
    <div class="total">Итого: {_money(row.get('amount'), row.get('currency'))}</div>
    <div class="sign"><div>Исполнитель</div><div>Заказчик</div></div>
    """
    return title, "Продажи", body


def _purchase_order_print(conn, entity_id: int) -> tuple[str, str, str]:
    row = _row(
        conn,
        """
        SELECT po.*, COALESCE(p.name, '') AS project_name, COALESCE(c.name, '') AS client_name
        FROM purchase_orders po
        LEFT JOIN projects p ON p.id=po.project_id
        LEFT JOIN clients c ON c.id=po.client_id
        WHERE po.id=?
        """,
        (entity_id,),
    )
    if not row:
        return "", "", ""
    total = row.get("total_amount") or (float(row.get("qty") or 0) * float(row.get("unit_price") or 0))
    body = _fields([
        ("Поставщик", row.get("supplier") or "не выбран"),
        ("Проект", row.get("project_name") or "не указан"),
        ("Срок поставки", row.get("expected_date")),
        ("Статус", row.get("status")),
    ])
    body += f"""
    <table><thead><tr><th>Артикул</th><th>Позиция</th><th>Количество</th><th>Ед.</th><th>Цена</th><th>Сумма</th></tr></thead>
    <tbody><tr><td>{_safe(row.get('item_article'))}</td><td>{_safe(row.get('item_name'))}</td><td>{_safe(row.get('qty'))}</td><td>{_safe(row.get('unit') or 'шт')}</td><td>{_money(row.get('unit_price'))}</td><td>{_money(total)}</td></tr></tbody></table>
    <div class="total">Итого: {_money(total)}</div><div class="sign"><div>Снабжение</div><div>Поставщик</div></div>
    """
    return f"Заказ поставщику №{entity_id}", "Закупки", body


def _stock_document_print(conn, entity_id: int) -> tuple[str, str, str]:
    row = _row(conn, "SELECT * FROM inventory_documents WHERE id=?", (entity_id,))
    if not row:
        row = _row(conn, "SELECT * FROM inventory_acts WHERE id=?", (entity_id,))
    if not row:
        return "", "", ""
    body = _fields([
        ("Тип", row.get("doc_type") or "inventory"),
        ("Номер", row.get("doc_number") or row.get("id")),
        ("Склад", row.get("warehouse")),
        ("Ячейка", row.get("bin_code")),
        ("Статус", row.get("status")),
    ])
    body += f"""
    <table><thead><tr><th>Артикул</th><th>Партия</th><th>Серия</th><th>Учёт</th><th>Факт</th><th>Коррекция</th></tr></thead>
    <tbody><tr><td>{_safe(row.get('article'))}</td><td>{_safe(row.get('batch_code'))}</td><td>{_safe(row.get('serial_no'))}</td><td>{_safe(row.get('qty') or row.get('expected_qty'))}</td><td>{_safe(row.get('counted_qty'))}</td><td>{_safe(row.get('adjustment_qty'))}</td></tr></tbody></table>
    <div class="sign"><div>Кладовщик</div><div>Ответственный</div></div>
    """
    return f"Складской документ №{row.get('doc_number') or entity_id}", "Склад", body


def _production_sheet_print(conn, entity_id: int) -> tuple[str, str, str]:
    row = _row(conn, "SELECT * FROM production_orders WHERE id=?", (entity_id,))
    if not row:
        return "", "", ""
    operations = _rows(conn, "SELECT * FROM production_operations WHERE order_id=? ORDER BY sequence_no, id", (entity_id,))
    bom = _rows(conn, "SELECT * FROM production_bom_items WHERE order_id=? ORDER BY id", (entity_id,))
    body = _fields([
        ("Заказ", row.get("order_name")),
        ("Ответственный", row.get("responsible")),
        ("Маршрут", row.get("route_name")),
        ("Плановый финиш", row.get("planned_finish")),
        ("Стадия", row.get("stage")),
        ("Прогресс", f"{row.get('progress') or 0}%"),
    ])
    body += "<h2>Операции</h2><table><thead><tr><th>№</th><th>Операция</th><th>РЦ</th><th>План часов</th><th>Статус</th></tr></thead><tbody>"
    body += ''.join(f"<tr><td>{_safe(op.get('sequence_no'))}</td><td>{_safe(op.get('operation_name'))}</td><td>{_safe(op.get('work_center'))}</td><td>{_safe(op.get('planned_hours'))}</td><td>{_safe(op.get('status'))}</td></tr>" for op in operations) or '<tr><td colspan="5">Операции не заведены</td></tr>'
    body += "</tbody></table><h2>Материалы</h2><table><thead><tr><th>Артикул</th><th>Материал</th><th>План</th><th>Факт</th><th>Склад</th></tr></thead><tbody>"
    body += ''.join(f"<tr><td>{_safe(item.get('article'))}</td><td>{_safe(item.get('item_name'))}</td><td>{_safe(item.get('planned_qty'))}</td><td>{_safe(item.get('actual_qty'))}</td><td>{_safe(item.get('warehouse'))}/{_safe(item.get('bin_code'))}</td></tr>" for item in bom) or '<tr><td colspan="5">Спецификация не заполнена</td></tr>'
    body += "</tbody></table><div class=\"sign\"><div>Мастер</div><div>ОТК</div></div>"
    return f"Производственный лист №{entity_id}", "Производство", body


def _package_registry_print(conn, entity_id: int) -> tuple[str, str, str]:
    package = _row(conn, "SELECT * FROM document_packages WHERE id=?", (entity_id,))
    if not package:
        return "", "", ""
    items = _rows(conn, "SELECT * FROM document_package_items WHERE package_id=? ORDER BY order_no, id", (entity_id,))
    body = _fields([
        ("Пакет", package.get("package_number") or package.get("id")),
        ("Название", package.get("title")),
        ("Статус", package.get("status")),
        ("Подписант", package.get("signed_by")),
        ("Комментарий", package.get("comment")),
    ])
    body += "<table><thead><tr><th>№</th><th>Тип</th><th>ID</th><th>Роль</th><th>Статус</th><th>Checksum</th></tr></thead><tbody>"
    body += ''.join(f"<tr><td>{_safe(item.get('order_no'))}</td><td>{_safe(item.get('entity_type'))}</td><td>{_safe(item.get('entity_id'))}</td><td>{_safe(item.get('item_role'))}</td><td>{_safe(item.get('item_status'))}</td><td>{_safe(item.get('checksum'))}</td></tr>" for item in items) or '<tr><td colspan="6">Пакет пуст</td></tr>'
    body += "</tbody></table><div class=\"sign\"><div>Составил</div><div>Проверил</div></div>"
    return f"Реестр пакета документов №{package.get('package_number') or entity_id}", "Документы", body


def build_print_form(form_type: str, entity_id: int) -> dict:
    form_type = str(form_type or "").strip()
    entity_id = int(entity_id or 0)
    conn = get_connection(row_factory=True)
    try:
        if form_type in {"invoice", "act", "upd", "registry"}:
            title, meta, body = _sales_print(conn, form_type, entity_id)
        elif form_type == "purchase_order":
            title, meta, body = _purchase_order_print(conn, entity_id)
        elif form_type == "stock_document":
            title, meta, body = _stock_document_print(conn, entity_id)
        elif form_type == "production_sheet":
            title, meta, body = _production_sheet_print(conn, entity_id)
        elif form_type == "package_registry":
            title, meta, body = _package_registry_print(conn, entity_id)
        else:
            return {"error": "unsupported_print_form"}
    finally:
        conn.close()
    if not title:
        return {"error": "not_found"}
    return {"title": title, "html": _page(title, meta, body)}
