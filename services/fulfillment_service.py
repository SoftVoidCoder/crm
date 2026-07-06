import json
import time
from datetime import datetime

from database import next_safe_table_id
from services.accounting_register_service import register_accounting_entry


def _safe_text(value) -> str:
    return str(value or "").strip()


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _now() -> int:
    return int(time.time())


def _row_dict(cursor) -> dict:
    row = cursor.fetchone()
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    columns = [item[0] for item in (cursor.description or [])]
    return {columns[idx]: row[idx] for idx in range(min(len(columns), len(row)))}


def _row_dicts(cursor) -> list[dict]:
    columns = [item[0] for item in (cursor.description or [])]
    result = []
    for row in cursor.fetchall():
        if isinstance(row, dict):
            result.append(dict(row))
        elif hasattr(row, "keys"):
            result.append({key: row[key] for key in row.keys()})
        else:
            result.append({columns[idx]: row[idx] for idx in range(min(len(columns), len(row)))})
    return result


def _insert(conn, table_name: str, payload: dict) -> int:
    payload = {"id": next_safe_table_id(conn, table_name), **payload}
    columns = list(payload.keys())
    conn.execute(
        f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(payload[column] for column in columns),
    )
    return _safe_int(payload["id"])


def _json(payload: dict) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


def _period_key(value: str = "") -> str:
    text = _safe_text(value)
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m")


def _article_available_qty(conn, article: str) -> float:
    article = _safe_text(article)
    if not article:
        return 0.0
    stock = _row_dict(conn.execute("SELECT COALESCE(SUM(qty), 0) AS qty FROM inventory_balances WHERE article=?", (article,))).get("qty")
    reserved = _row_dict(
        conn.execute(
            """
            SELECT COALESCE(SUM(qty - COALESCE(fulfilled_qty, 0)), 0) AS qty
            FROM stock_reservations
            WHERE nomenclature_article=? AND status IN ('reserved', 'partial')
            """,
            (article,),
        )
    ).get("qty")
    return max(round(_safe_float(stock) - _safe_float(reserved), 3), 0.0)


def _linked_supply_qty(conn, demand_type: str, demand_id: int, supply_type: str = "") -> float:
    params = [_safe_text(demand_type), _safe_int(demand_id)]
    where = "demand_type=? AND demand_id=? AND status NOT IN ('cancelled', 'rejected')"
    if supply_type:
        where += " AND supply_type=?"
        params.append(_safe_text(supply_type))
    row = _row_dict(conn.execute(f"SELECT COALESCE(SUM(qty), 0) AS qty FROM supply_demand_links WHERE {where}", tuple(params)))
    return round(_safe_float(row.get("qty")), 3)


def _shipped_qty(conn, customer_order_id: int) -> float:
    row = _row_dict(
        conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS qty FROM sales_shipments WHERE customer_order_id=? AND status='shipped'",
            (_safe_int(customer_order_id),),
        )
    )
    return round(_safe_float(row.get("qty")), 3)


def _invoiced_qty(order: dict) -> float:
    return _safe_float(order.get("qty")) if _safe_int(order.get("sales_document_id")) else 0.0


def _plan_status(demand_qty: float, shortage_qty: float, shipped_qty: float, invoiced_qty: float) -> str:
    if demand_qty > 0 and shipped_qty + 0.0001 >= demand_qty and invoiced_qty + 0.0001 >= demand_qty:
        return "closed"
    if shortage_qty > 0:
        return "shortage"
    if shipped_qty > 0:
        return "shipping"
    return "covered"


def _create_procurement_request(conn, order: dict, qty: float, actor_email: str) -> int:
    now = _now()
    return _insert(
        conn,
        "procurement_requests",
        {
            "project_id": _safe_int(order.get("project_id")),
            "client_id": _safe_int(order.get("client_id")),
            "contract_id": _safe_int(order.get("contract_id")),
            "object_id": _safe_int(order.get("object_id")),
            "legal_entity_id": _safe_int(order.get("legal_entity_id")),
            "business_unit_id": _safe_int(order.get("business_unit_id")),
            "request_number": f"REQ-SO-{order.get('id')}-{now}",
            "title": f"Обеспечение заказа {order.get('order_number') or order.get('id')}",
            "item_article": _safe_text(order.get("article")),
            "item_name": _safe_text(order.get("item_name") or order.get("article")),
            "qty": round(qty, 3),
            "unit": _safe_text(order.get("unit")) or "шт",
            "target_unit_price": _safe_float(order.get("unit_price")),
            "required_date": _safe_text(order.get("requested_ship_date")),
            "priority": "normal",
            "requested_by": actor_email,
            "status": "approved",
            "linked_purchase_id": 0,
            "selected_supplier_id": 0,
            "approved_by": actor_email,
            "approved_at": now,
            "comment": "Автоматически создано из дефицита заказа клиента",
            "created_by": actor_email,
            "created_at": now,
            "updated_at": now,
        },
    )


def _create_purchase_order(conn, order: dict, request_id: int, qty: float, actor_email: str) -> int:
    now = _now()
    unit_price = _safe_float(order.get("unit_price"))
    purchase_id = _insert(
        conn,
        "purchase_orders",
        {
            "project_id": _safe_int(order.get("project_id")),
            "client_id": _safe_int(order.get("client_id")),
            "legal_entity_id": _safe_int(order.get("legal_entity_id")),
            "business_unit_id": _safe_int(order.get("business_unit_id")),
            "item_article": _safe_text(order.get("article")),
            "item_name": _safe_text(order.get("item_name") or order.get("article")),
            "supplier": "Автообеспечение",
            "supplier_id": 0,
            "qty": round(qty, 3),
            "unit": _safe_text(order.get("unit")) or "шт",
            "unit_price": unit_price,
            "planned_unit_price": unit_price,
            "total_amount": round(qty * unit_price, 2),
            "status": "ordered",
            "expected_date": _safe_text(order.get("requested_ship_date")),
            "planned_delivery_date": _safe_text(order.get("requested_ship_date")),
            "received_date": "",
            "delivered_qty": 0,
            "request_status": "approved",
            "approval_status": "approved",
            "schedule_status": "planned",
            "lead_time_days": 0,
            "comment": f"Автозакупка по заказу клиента {order.get('order_number') or order.get('id')}",
            "created_by": actor_email,
            "created_at": now,
            "updated_at": now,
        },
    )
    if request_id:
        conn.execute("UPDATE procurement_requests SET linked_purchase_id=?, status='ordered', updated_at=? WHERE id=?", (purchase_id, now, request_id))
    return purchase_id


def _create_production_order(conn, order: dict, qty: float, actor_email: str) -> int:
    now = _now()
    return _insert(
        conn,
        "production_orders",
        {
            "project_id": _safe_int(order.get("project_id")),
            "client_id": _safe_int(order.get("client_id")),
            "legal_entity_id": _safe_int(order.get("legal_entity_id")),
            "business_unit_id": _safe_int(order.get("business_unit_id")),
            "order_name": f"Производство под заказ {order.get('order_number') or order.get('id')}",
            "stage": "queue",
            "priority": "normal",
            "planned_start": "",
            "planned_finish": _safe_text(order.get("requested_ship_date")),
            "actual_finish": "",
            "progress": 0,
            "responsible": "",
            "comment": f"Автопроизводство дефицита {order.get('article') or ''}, qty={round(qty, 3)}",
            "route_name": _safe_text(order.get("article")) or "Маршрут",
            "planned_qty": round(qty, 3),
            "produced_qty": 0,
            "scrap_qty": 0,
            "planned_cost": round(qty * _safe_float(order.get("unit_price")), 2),
            "actual_cost": 0,
            "labor_hours_plan": 0,
            "labor_hours_fact": 0,
            "created_by": actor_email,
            "created_at": now,
            "updated_at": now,
        },
    )


def _create_supply_link(conn, plan_id: int, order: dict, supply_type: str, supply_id: int, supply_number: str, qty: float, actor_email: str) -> int:
    now = _now()
    return _insert(
        conn,
        "supply_demand_links",
        {
            "demand_type": "sales_customer_order",
            "demand_id": _safe_int(order.get("id")),
            "demand_number": _safe_text(order.get("order_number")),
            "supply_type": supply_type,
            "supply_id": _safe_int(supply_id),
            "supply_number": _safe_text(supply_number),
            "item_article": _safe_text(order.get("article")),
            "item_name": _safe_text(order.get("item_name") or order.get("article")),
            "unit": _safe_text(order.get("unit")) or "шт",
            "qty": round(qty, 3),
            "status": "planned",
            "link_kind": "auto_shortage",
            "source_plan_id": _safe_int(plan_id),
            "details_json": _json({"auto_created": True}),
            "created_by": actor_email,
            "created_at": now,
            "updated_at": now,
        },
    )


def build_fulfillment_plan_for_customer_order(conn, order_id: int, actor_email: str = "", strategy: str = "purchase", auto_create: bool = True) -> dict:
    order = _row_dict(conn.execute("SELECT * FROM sales_customer_orders WHERE id=?", (_safe_int(order_id),)))
    if not order:
        return {"error": "order_not_found"}

    now = _now()
    demand_qty = _safe_float(order.get("qty"))
    available_qty = _article_available_qty(conn, order.get("article"))
    linked_purchase_qty = _linked_supply_qty(conn, "sales_customer_order", order.get("id"), "purchase_order")
    linked_production_qty = _linked_supply_qty(conn, "sales_customer_order", order.get("id"), "production_order")
    covered_qty = available_qty + linked_purchase_qty + linked_production_qty
    shortage_qty = max(round(demand_qty - covered_qty, 3), 0.0)
    shipped_qty = _shipped_qty(conn, order.get("id"))
    invoiced_qty = _invoiced_qty(order)
    status = _plan_status(demand_qty, shortage_qty, shipped_qty, invoiced_qty)

    existing = _row_dict(
        conn.execute(
            "SELECT id, created_at FROM fulfillment_plan WHERE demand_type='sales_customer_order' AND demand_id=? AND item_article=? ORDER BY id DESC LIMIT 1",
            (_safe_int(order.get("id")), _safe_text(order.get("article"))),
        )
    )
    plan_payload = {
        "demand_type": "sales_customer_order",
        "demand_id": _safe_int(order.get("id")),
        "demand_number": _safe_text(order.get("order_number")),
        "project_id": _safe_int(order.get("project_id")),
        "client_id": _safe_int(order.get("client_id")),
        "contract_id": _safe_int(order.get("contract_id")),
        "object_id": _safe_int(order.get("object_id")),
        "legal_entity_id": _safe_int(order.get("legal_entity_id")),
        "business_unit_id": _safe_int(order.get("business_unit_id")),
        "item_article": _safe_text(order.get("article")),
        "item_name": _safe_text(order.get("item_name") or order.get("article")),
        "unit": _safe_text(order.get("unit")) or "шт",
        "demand_qty": round(demand_qty, 3),
        "available_qty": round(available_qty, 3),
        "reserved_qty": round(max(available_qty - shortage_qty, 0.0), 3),
        "shortage_qty": round(shortage_qty, 3),
        "planned_purchase_qty": round(linked_purchase_qty, 3),
        "planned_production_qty": round(linked_production_qty, 3),
        "linked_supply_qty": round(linked_purchase_qty + linked_production_qty, 3),
        "shipped_qty": round(shipped_qty, 3),
        "invoiced_qty": round(invoiced_qty, 3),
        "status": status,
        "strategy": strategy or "purchase",
        "need_by_date": _safe_text(order.get("requested_ship_date")),
        "details_json": _json({"currency": order.get("currency") or "RUB", "amount": _safe_float(order.get("amount"))}),
        "created_by": actor_email,
        "created_at": _safe_int(existing.get("created_at")) or now,
        "updated_at": now,
    }
    if existing:
        assignments = ", ".join(f"{key}=?" for key in plan_payload if key not in {"created_at"})
        conn.execute(
            f"UPDATE fulfillment_plan SET {assignments} WHERE id=?",
            tuple(plan_payload[key] for key in plan_payload if key not in {"created_at"}) + (_safe_int(existing.get("id")),),
        )
        plan_id = _safe_int(existing.get("id"))
    else:
        plan_id = _insert(conn, "fulfillment_plan", plan_payload)

    created_supply = {}
    if auto_create and shortage_qty > 0 and not _linked_supply_qty(conn, "sales_customer_order", order.get("id")):
        if strategy == "production":
            production_id = _create_production_order(conn, order, shortage_qty, actor_email)
            _create_supply_link(conn, plan_id, order, "production_order", production_id, f"PRD-{production_id}", shortage_qty, actor_email)
            created_supply = {"production_order_id": production_id}
        else:
            request_id = _create_procurement_request(conn, order, shortage_qty, actor_email)
            purchase_id = _create_purchase_order(conn, order, request_id, shortage_qty, actor_email)
            _create_supply_link(conn, plan_id, order, "purchase_order", purchase_id, f"PO-{purchase_id}", shortage_qty, actor_email)
            created_supply = {"procurement_request_id": request_id, "purchase_order_id": purchase_id}
        linked_purchase_qty = _linked_supply_qty(conn, "sales_customer_order", order.get("id"), "purchase_order")
        linked_production_qty = _linked_supply_qty(conn, "sales_customer_order", order.get("id"), "production_order")
        shortage_qty = max(round(demand_qty - available_qty - linked_purchase_qty - linked_production_qty, 3), 0.0)
        conn.execute(
            """
            UPDATE fulfillment_plan
            SET shortage_qty=?, planned_purchase_qty=?, planned_production_qty=?, linked_supply_qty=?, status=?, updated_at=?
            WHERE id=?
            """,
            (
                shortage_qty,
                linked_purchase_qty,
                linked_production_qty,
                linked_purchase_qty + linked_production_qty,
                _plan_status(demand_qty, shortage_qty, shipped_qty, invoiced_qty),
                now,
                plan_id,
            ),
        )

    return {"status": "success", "id": plan_id, "shortage_qty": shortage_qty, **created_supply}


def refresh_fulfillment_for_customer_order(conn, order_id: int, actor_email: str = "") -> dict:
    return build_fulfillment_plan_for_customer_order(conn, order_id, actor_email, auto_create=False)


def _latest_invoice(conn, purchase_id: int) -> dict:
    return _row_dict(
        conn.execute(
            """
            SELECT * FROM purchase_documents
            WHERE purchase_id=? AND doc_type IN ('invoice', 'upd', 'bill') AND status NOT IN ('cancelled', 'rejected')
            ORDER BY doc_date DESC, updated_at DESC, id DESC LIMIT 1
            """,
            (_safe_int(purchase_id),),
        )
    )


def _receipt_totals(conn, purchase_id: int) -> dict:
    row = _row_dict(
        conn.execute(
            """
            SELECT
                COALESCE(SUM(accepted_qty), 0) AS qty,
                COALESCE(MAX(id), 0) AS receipt_id
            FROM purchase_receipts
            WHERE purchase_id=? AND status!='draft'
            """,
            (_safe_int(purchase_id),),
        )
    )
    return {"qty": _safe_float(row.get("qty")), "receipt_id": _safe_int(row.get("receipt_id"))}


def _matching_status(ordered_qty: float, received_qty: float, expected_amount: float, invoice_amount: float, invoice_id: int) -> tuple[str, str]:
    qty_ok = abs(received_qty - ordered_qty) <= 0.0001
    amount_ok = abs(invoice_amount - expected_amount) <= max(1.0, expected_amount * 0.01)
    if not invoice_id or received_qty <= 0:
        return "pending", "waiting_receipt_or_invoice"
    if qty_ok and amount_ok:
        return "matched", ""
    if received_qty < ordered_qty:
        return "partial", "receipt_qty_less_than_order"
    return "mismatch", "invoice_or_receipt_variance"


def _sync_purchase_accounting(conn, purchase: dict, invoice: dict, actor_email: str) -> int:
    invoice_id = _safe_int(invoice.get("id"))
    amount = _safe_float(invoice.get("amount"))
    if not invoice_id or amount <= 0:
        return 0
    now = _now()
    doc_date = _safe_text(invoice.get("doc_date")) or datetime.now().strftime("%d.%m.%Y")
    conn.execute("DELETE FROM accounting_entries WHERE source_type='purchase_document' AND source_id=?", (invoice_id,))
    for table_name in ("accounting_registers", "tax_registers", "vat_purchase_book", "vat_sales_book"):
        conn.execute(f"DELETE FROM {table_name} WHERE source_type='purchase_document' AND source_id=?", (invoice_id,))
    entry_payload = {
        "source_type": "purchase_document",
        "source_id": invoice_id,
        "entry_date": doc_date,
        "period_key": _period_key(doc_date),
        "legal_entity_id": _safe_int(purchase.get("legal_entity_id")),
        "business_unit_id": _safe_int(purchase.get("business_unit_id")),
        "project_id": _safe_int(purchase.get("project_id")),
        "client_id": _safe_int(purchase.get("client_id")),
        "contract_id": _safe_int(purchase.get("contract_id")),
        "object_id": _safe_int(purchase.get("object_id")),
        "treasury_article_id": 0,
        "vat_rate_id": 0,
        "account_debit": "41",
        "account_credit": "60",
        "amount": round(amount, 2),
        "vat_amount": round(_safe_float(invoice.get("vat_amount")), 2),
        "currency": invoice.get("currency") or purchase.get("currency") or "RUB",
        "description": f"Счёт поставщика {invoice.get('doc_number') or invoice_id} по закупке {purchase.get('id')}",
        "posted_by": actor_email,
        "created_at": now,
    }
    conn.execute(
        """
        INSERT INTO accounting_entries (
            source_type, source_id, entry_date, period_key, legal_entity_id, business_unit_id, project_id, client_id,
            contract_id, object_id, treasury_article_id, vat_rate_id, account_debit, account_credit, amount, vat_amount,
            currency, description, posted_by, created_at
        ) VALUES ('purchase_document', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, '41', '60', ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_payload["source_id"],
            entry_payload["entry_date"],
            entry_payload["period_key"],
            entry_payload["legal_entity_id"],
            entry_payload["business_unit_id"],
            entry_payload["project_id"],
            entry_payload["client_id"],
            entry_payload["contract_id"],
            entry_payload["object_id"],
            entry_payload["amount"],
            entry_payload["vat_amount"],
            entry_payload["currency"],
            entry_payload["description"],
            entry_payload["posted_by"],
            entry_payload["created_at"],
        ),
    )
    entry_row = _row_dict(conn.execute("SELECT id FROM accounting_entries WHERE source_type='purchase_document' AND source_id=? ORDER BY id DESC LIMIT 1", (invoice_id,)))
    entry_payload["id"] = _safe_int(entry_row.get("id"))
    register_accounting_entry(conn, entry_payload, actor_email)
    return _safe_int(entry_payload.get("id"))


def run_three_way_match_for_purchase(conn, purchase_id: int, actor_email: str = "") -> dict:
    purchase = _row_dict(conn.execute("SELECT * FROM purchase_orders WHERE id=?", (_safe_int(purchase_id),)))
    if not purchase:
        return {"error": "purchase_not_found"}
    invoice = _latest_invoice(conn, purchase_id)
    receipts = _receipt_totals(conn, purchase_id)
    ordered_qty = _safe_float(purchase.get("qty"))
    received_qty = _safe_float(receipts.get("qty"))
    unit_price = _safe_float(purchase.get("unit_price")) or _safe_float(purchase.get("planned_unit_price"))
    ordered_amount = _safe_float(purchase.get("total_amount")) or round(ordered_qty * unit_price, 2)
    received_amount = round(received_qty * unit_price, 2)
    invoice_amount = _safe_float(invoice.get("amount"))
    invoice_id = _safe_int(invoice.get("id"))
    status, discrepancy_type = _matching_status(ordered_qty, received_qty, ordered_amount, invoice_amount, invoice_id)
    qty_variance = round(received_qty - ordered_qty, 3)
    amount_variance = round(invoice_amount - ordered_amount, 2)
    vat_amount = _safe_float(invoice.get("vat_amount"))
    expected_vat = round(ordered_amount * 20 / 120, 2) if vat_amount else 0.0
    vat_variance = round(vat_amount - expected_vat, 2)
    now = _now()
    details = {
        "discrepancy_type": discrepancy_type,
        "ordered_amount": ordered_amount,
        "received_amount": received_amount,
        "invoice_amount": invoice_amount,
    }
    match_id = _insert(
        conn,
        "three_way_matches",
        {
            "purchase_id": _safe_int(purchase_id),
            "receipt_id": _safe_int(receipts.get("receipt_id")),
            "invoice_id": invoice_id,
            "supplier_id": _safe_int(purchase.get("supplier_id")) or _safe_int(invoice.get("supplier_id")),
            "item_article": _safe_text(purchase.get("item_article")),
            "item_name": _safe_text(purchase.get("item_name") or purchase.get("item_article")),
            "unit": _safe_text(purchase.get("unit")) or "шт",
            "ordered_qty": round(ordered_qty, 3),
            "received_qty": round(received_qty, 3),
            "invoiced_qty": round(ordered_qty if invoice_id else 0, 3),
            "ordered_amount": round(ordered_amount, 2),
            "received_amount": round(received_amount, 2),
            "invoice_amount": round(invoice_amount, 2),
            "vat_amount": round(vat_amount, 2),
            "qty_variance": qty_variance,
            "amount_variance": amount_variance,
            "vat_variance": vat_variance,
            "status": status,
            "discrepancy_json": _json(details),
            "created_by": actor_email,
            "created_at": now,
            "updated_at": now,
        },
    )
    invoice_match_id = 0
    if invoice_id:
        invoice_match_id = _insert(
            conn,
            "invoice_matching_results",
            {
                "invoice_type": "purchase_document",
                "invoice_id": invoice_id,
                "match_type": "three_way",
                "source_type": "purchase_order",
                "source_id": _safe_int(purchase_id),
                "counterparty_id": _safe_int(purchase.get("supplier_id")) or _safe_int(invoice.get("supplier_id")),
                "expected_amount": round(ordered_amount, 2),
                "invoice_amount": round(invoice_amount, 2),
                "amount_variance": amount_variance,
                "expected_qty": round(ordered_qty, 3),
                "actual_qty": round(received_qty, 3),
                "qty_variance": qty_variance,
                "status": status,
                "discrepancy_type": discrepancy_type,
                "details_json": _json(details),
                "created_by": actor_email,
                "created_at": now,
                "updated_at": now,
            },
        )
        _sync_purchase_accounting(conn, purchase, invoice, actor_email)
    conn.execute(
        "UPDATE supply_demand_links SET status=?, updated_at=? WHERE supply_type='purchase_order' AND supply_id=?",
        ("received" if status == "matched" else status, now, _safe_int(purchase_id)),
    )
    for link in _row_dicts(conn.execute("SELECT demand_id FROM supply_demand_links WHERE supply_type='purchase_order' AND supply_id=?", (_safe_int(purchase_id),))):
        refresh_fulfillment_for_customer_order(conn, link.get("demand_id"), actor_email)
    if status == "mismatch":
        existing_act = _row_dict(
            conn.execute(
                "SELECT id FROM supplier_discrepancy_acts WHERE purchase_id=? AND article=? AND status='open' ORDER BY id DESC LIMIT 1",
                (_safe_int(purchase_id), _safe_text(purchase.get("item_article"))),
            )
        )
        if not existing_act:
            _insert(
                conn,
                "supplier_discrepancy_acts",
                {
                    "purchase_id": _safe_int(purchase_id),
                    "supplier_id": _safe_int(purchase.get("supplier_id")),
                    "act_number": f"DISC-{purchase_id}-{now}",
                    "article": _safe_text(purchase.get("item_article")),
                    "item_name": _safe_text(purchase.get("item_name")),
                    "planned_qty": round(ordered_qty, 3),
                    "actual_qty": round(received_qty, 3),
                    "planned_unit_price": round(unit_price, 2),
                    "actual_unit_price": round(invoice_amount / ordered_qty, 2) if ordered_qty else 0,
                    "status": "open",
                    "reason": discrepancy_type,
                    "comment": "Автоматически создано three-way match",
                    "created_by": actor_email,
                    "created_at": now,
                    "updated_at": now,
                },
            )
    return {"status": status, "id": match_id, "invoice_matching_id": invoice_match_id, "qty_variance": qty_variance, "amount_variance": amount_variance}
