import json
import time
from collections import defaultdict
from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from database import audit_log, get_connection, next_safe_table_id
from services.inventory_costing_service import (
    choose_putaway_cell,
    consume_cost_layers,
    costing_summary as inventory_costing_summary,
    pick_lot_order_sql,
    qty_to_base,
    receipt_cost_layer,
    transfer_cost_layers,
    update_lot_expiration,
    upsert_item_package,
    upsert_unit_conversion,
)
from services.production_costing_service import complete_operation_costing
from services.fulfillment_service import (
    build_fulfillment_plan_for_customer_order,
    refresh_fulfillment_for_customer_order,
    run_three_way_match_for_purchase,
)
from schemas import (
    SalesQuoteData,
    CustomerReturnData,
    SalesPlanData,
    PriceListData,
    ClientSalesTermData,
    SupplierRegistryData,
    PurchasePlanData,
    ProcurementAwardData,
    ProcurementRequestData,
    ProcurementTenderBidData,
    ProcurementTenderData,
    PurchaseDocumentData,
    PurchaseReceiptData,
    SalesCustomerOrderData,
    SalesCustomerOrderReserveData,
    SalesDealMarginData,
    SalesPaymentScheduleData,
    SalesShipmentData,
    SupplierDeliveryScheduleData,
    SupplierReturnData,
    SupplierDiscrepancyActData,
    InventoryActData,
    InventoryRegradingData,
    WarehouseQualityReportData,
    WarehousePolicyData,
    WarehouseBulkActionData,
    WMSCellProfileData,
    WMSPutawayTaskData,
    WMSPickWaveData,
    WMSPickTaskData,
    WMSCycleCountData,
    WMSCycleCountLineData,
    InventoryDocumentData,
    ItemPackageData,
    ProductionExecutionEventData,
    TerminalScanData,
    TerminalSessionData,
    UnitConversionData,
)


def register_extended_ops_routes(router, helpers: dict):
    require_approved_user = helpers["require_approved_user"]
    has_permission = helpers["has_permission"]
    _resolve_master_context = helpers["_resolve_master_context"]
    _normalize_spaces = helpers["_normalize_spaces"]
    _safe_float = helpers["_safe_float"]
    _safe_int = helpers["_safe_int"]
    _normalize_stock_location = helpers["_normalize_stock_location"]
    _upsert_inventory_balance = helpers["_upsert_inventory_balance"]
    _upsert_inventory_lot = helpers["_upsert_inventory_lot"]
    _available_reserved_qty = helpers["_available_reserved_qty"]
    _bootstrap_inventory_lots_for_article = helpers["_bootstrap_inventory_lots_for_article"]
    _load_inventory_document_rows = helpers["_load_inventory_document_rows"]
    _load_inventory_balances = helpers["_load_inventory_balances"]
    _next_inventory_doc_number = helpers["_next_inventory_doc_number"]
    _apply_inventory_document = helpers["_apply_inventory_document"]
    _filter_scope_rows_for_actor = helpers["_filter_scope_rows_for_actor"]

    def _rows(sql: str, params: tuple = ()):
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute(sql, params)
        result = [dict(row) for row in c.fetchall()]
        conn.close()
        return result

    def _insert(conn, table: str, payload: dict):
        if "id" not in payload:
            payload = {"id": next_safe_table_id(conn, table), **payload}
        keys = list(payload.keys())
        conn.execute(
            f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            tuple(payload[key] for key in keys),
        )
        return payload["id"]

    def _delete(table: str, row_id: int):
        conn = get_connection()
        conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
        conn.commit()
        conn.close()

    def _api_error(status_code: int, error: str, **payload):
        return JSONResponse(status_code=status_code, content={"error": error, **payload})

    def _parse_date(value: str):
        value = (value or "").strip()
        if not value:
            return None
        for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, pattern)
            except ValueError:
                continue
        return None

    def _days_between(left: str, right: str = "") -> int:
        left_dt = _parse_date(left)
        right_dt = _parse_date(right) or datetime.now()
        if not left_dt:
            return 0
        return (right_dt.date() - left_dt.date()).days

    def _policy_settings(c=None):
        close_conn = False
        if c is None:
            conn = get_connection()
            c = conn.cursor()
            close_conn = True
        c.execute("SELECT cost_method, allow_negative_stock, auto_pick_strategy, comment FROM warehouse_policies WHERE id=1")
        row = c.fetchone()
        if close_conn:
            conn.close()
        if not row:
            return {"cost_method": "fifo", "allow_negative_stock": 0, "auto_pick_strategy": "best_fit", "comment": ""}
        return {"cost_method": row[0] or "fifo", "allow_negative_stock": _safe_int(row[1]), "auto_pick_strategy": row[2] or "best_fit", "comment": row[3] or ""}

    def _next_code(prefix: str) -> str:
        return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def _json_load(raw_value, default):
        if raw_value in (None, ""):
            return default
        try:
            return json.loads(raw_value)
        except Exception:
            return default

    def _lifecycle_state(valid_from: str = "", valid_to: str = "", status: str = "") -> str:
        value = (status or "").strip().lower()
        if value in {"archived", "closed", "inactive"}:
            return "archived"
        if value == "draft":
            return "draft"
        today = datetime.now().date()
        start_dt = _parse_date(valid_from)
        end_dt = _parse_date(valid_to)
        if end_dt and end_dt.date() < today:
            return "expired"
        if start_dt and start_dt.date() > today:
            return "upcoming"
        return "active"

    def _health_bucket(score: float) -> str:
        numeric = round(_safe_float(score), 1)
        if numeric >= 85:
            return "stable"
        if numeric >= 65:
            return "attention"
        return "risk"

    def _label_stage(stage: str) -> str:
        labels = {
            "draft": "Черновик",
            "proposal": "Отправлено",
            "negotiation": "Переговоры",
            "won": "Выиграно",
            "lost": "Проиграно",
        }
        return labels.get((stage or "").strip().lower(), stage or "Черновик")

    def _score_sales_clients(sales_rows, quote_rows, terms_rows, return_rows):
        client_names = {item["id"]: item["name"] for item in _rows("SELECT id, name FROM clients")}
        grouped = {}
        for row in sales_rows:
            client_id = _safe_int(row.get("client_id"))
            if client_id <= 0:
                continue
            bucket = grouped.setdefault(client_id, {
                "client_id": client_id,
                "client_name": row.get("client_name") or client_names.get(client_id) or f"Клиент #{client_id}",
                "revenue": 0.0,
                "overdue_amount": 0.0,
                "overdue_docs": 0,
                "shipment_risk_docs": 0,
                "high_discount_docs": 0,
                "terms_count": 0,
                "quotes": 0,
                "returns": 0,
            })
            if row.get("status") in {"issued", "signed", "closed"}:
                bucket["revenue"] += _safe_float(row.get("amount"))
            if _safe_int(row.get("is_overdue")):
                bucket["overdue_docs"] += 1
                bucket["overdue_amount"] += _safe_float(row.get("amount"))
            if _safe_int(row.get("shipment_late_days")) > 0:
                bucket["shipment_risk_docs"] += 1
            if _safe_float(row.get("discount_percent")) >= 10 or _safe_float(row.get("discount_amount")) > 0:
                bucket["high_discount_docs"] += 1
        for row in quote_rows:
            client_id = _safe_int(row.get("client_id"))
            if client_id <= 0:
                continue
            bucket = grouped.setdefault(client_id, {
                "client_id": client_id,
                "client_name": client_names.get(client_id) or f"Клиент #{client_id}",
                "revenue": 0.0,
                "overdue_amount": 0.0,
                "overdue_docs": 0,
                "shipment_risk_docs": 0,
                "high_discount_docs": 0,
                "terms_count": 0,
                "quotes": 0,
                "returns": 0,
            })
            bucket["quotes"] += 1
        for row in terms_rows:
            client_id = _safe_int(row.get("client_id"))
            if client_id <= 0:
                continue
            bucket = grouped.setdefault(client_id, {
                "client_id": client_id,
                "client_name": row.get("client_name") or client_names.get(client_id) or f"Клиент #{client_id}",
                "revenue": 0.0,
                "overdue_amount": 0.0,
                "overdue_docs": 0,
                "shipment_risk_docs": 0,
                "high_discount_docs": 0,
                "terms_count": 0,
                "quotes": 0,
                "returns": 0,
            })
            bucket["terms_count"] += 1
        for row in return_rows:
            client_id = _safe_int(row.get("client_id"))
            if client_id <= 0:
                continue
            bucket = grouped.setdefault(client_id, {
                "client_id": client_id,
                "client_name": row.get("client_name") or client_names.get(client_id) or f"Клиент #{client_id}",
                "revenue": 0.0,
                "overdue_amount": 0.0,
                "overdue_docs": 0,
                "shipment_risk_docs": 0,
                "high_discount_docs": 0,
                "terms_count": 0,
                "quotes": 0,
                "returns": 0,
            })
            bucket["returns"] += 1
        result = []
        for bucket in grouped.values():
            score = 100
            score -= bucket["overdue_docs"] * 15
            score -= bucket["shipment_risk_docs"] * 10
            score -= bucket["returns"] * 8
            score -= bucket["high_discount_docs"] * 4
            if bucket["revenue"] > 0 and bucket["overdue_docs"] == 0:
                score += 5
            score = max(0, min(100, score))
            reasons = []
            if bucket["overdue_docs"]:
                reasons.append(f"просрочка {bucket['overdue_docs']}")
            if bucket["shipment_risk_docs"]:
                reasons.append(f"риск отгрузки {bucket['shipment_risk_docs']}")
            if bucket["returns"]:
                reasons.append(f"возвраты {bucket['returns']}")
            if bucket["high_discount_docs"]:
                reasons.append(f"скидки {bucket['high_discount_docs']}")
            bucket["health_score"] = round(score, 1)
            bucket["health_bucket"] = _health_bucket(score)
            bucket["reasons"] = reasons or ["стабильный цикл"]
            result.append(bucket)
        result.sort(key=lambda item: (item["health_score"], -item["revenue"], item["client_name"]))
        return result

    def _score_suppliers(purchase_rows, supplier_rows, schedules, return_rows, discrepancy_rows):
        suppliers = {}
        for row in supplier_rows:
            supplier_id = _safe_int(row.get("id"))
            suppliers[supplier_id] = dict(row)
        grouped = {}
        for supplier_id, row in suppliers.items():
            grouped[supplier_id] = {
                "supplier_id": supplier_id,
                "supplier_name": row.get("supplier_name") or f"Поставщик #{supplier_id}",
                "rating": _safe_float(row.get("rating")) or 0,
                "reliability_percent": _safe_float(row.get("reliability_percent")) or 100,
                "lead_time_days": _safe_int(row.get("lead_time_days")),
                "orders_total": 0,
                "late_deliveries": 0,
                "underdelivery_cases": 0,
                "price_variance_total": 0.0,
                "returns_total": 0,
                "discrepancies_total": 0,
            }
        for row in purchase_rows:
            supplier_id = _safe_int(row.get("supplier_id"))
            if supplier_id <= 0:
                continue
            bucket = grouped.setdefault(supplier_id, {
                "supplier_id": supplier_id,
                "supplier_name": row.get("supplier_name") or row.get("supplier") or f"Поставщик #{supplier_id}",
                "rating": 0,
                "reliability_percent": 100,
                "lead_time_days": 0,
                "orders_total": 0,
                "late_deliveries": 0,
                "underdelivery_cases": 0,
                "price_variance_total": 0.0,
                "returns_total": 0,
                "discrepancies_total": 0,
            })
            bucket["orders_total"] += 1
            if _safe_int(row.get("delivery_delay_days")) > 0:
                bucket["late_deliveries"] += 1
            if _safe_float(row.get("underdelivery_qty")) > 0:
                bucket["underdelivery_cases"] += 1
            bucket["price_variance_total"] += abs(_safe_float(row.get("price_variance")))
        for row in return_rows:
            supplier_id = _safe_int(row.get("supplier_id"))
            if supplier_id > 0:
                grouped.setdefault(supplier_id, {
                    "supplier_id": supplier_id,
                    "supplier_name": row.get("supplier_name") or f"Поставщик #{supplier_id}",
                    "rating": 0,
                    "reliability_percent": 100,
                    "lead_time_days": 0,
                    "orders_total": 0,
                    "late_deliveries": 0,
                    "underdelivery_cases": 0,
                    "price_variance_total": 0.0,
                    "returns_total": 0,
                    "discrepancies_total": 0,
                })["returns_total"] += 1
        for row in discrepancy_rows:
            supplier_id = _safe_int(row.get("supplier_id"))
            if supplier_id > 0:
                grouped.setdefault(supplier_id, {
                    "supplier_id": supplier_id,
                    "supplier_name": row.get("supplier_name") or f"Поставщик #{supplier_id}",
                    "rating": 0,
                    "reliability_percent": 100,
                    "lead_time_days": 0,
                    "orders_total": 0,
                    "late_deliveries": 0,
                    "underdelivery_cases": 0,
                    "price_variance_total": 0.0,
                    "returns_total": 0,
                    "discrepancies_total": 0,
                })["discrepancies_total"] += 1
        schedule_by_supplier = defaultdict(list)
        for row in schedules:
            schedule_by_supplier[_safe_int(row.get("supplier_id"))].append(row)
        result = []
        for bucket in grouped.values():
            supplier_id = bucket["supplier_id"]
            late_schedules = len([item for item in schedule_by_supplier.get(supplier_id, []) if _safe_int(item.get("late_days")) > 0])
            score = 100
            score -= max(0, 80 - bucket["rating"] * 16)
            score -= max(0, 90 - bucket["reliability_percent"]) * 0.6
            score -= bucket["late_deliveries"] * 10
            score -= bucket["underdelivery_cases"] * 8
            score -= bucket["returns_total"] * 6
            score -= bucket["discrepancies_total"] * 6
            score -= late_schedules * 5
            score = max(0, min(100, score))
            reasons = []
            if bucket["late_deliveries"] or late_schedules:
                reasons.append(f"срывы сроков {bucket['late_deliveries'] + late_schedules}")
            if bucket["underdelivery_cases"]:
                reasons.append(f"недопоставка {bucket['underdelivery_cases']}")
            if bucket["discrepancies_total"]:
                reasons.append(f"акты {bucket['discrepancies_total']}")
            if bucket["returns_total"]:
                reasons.append(f"возвраты {bucket['returns_total']}")
            bucket["health_score"] = round(score, 1)
            bucket["health_bucket"] = _health_bucket(score)
            bucket["reasons"] = reasons or ["ритм поставок стабильный"]
            bucket["price_variance_total"] = round(bucket["price_variance_total"], 2)
            result.append(bucket)
        result.sort(key=lambda item: (item["health_score"], item["lead_time_days"], item["supplier_name"]))
        return result

    def _procurement_request_rows(actor=None):
        rows = _rows(
            """
            SELECT
                pr.*,
                COALESCE(p.name, '') AS project_name,
                COALESCE(cl.name, '') AS client_name,
                COALESCE(sr.supplier_name, '') AS selected_supplier_name,
                COALESCE(po.status, '') AS purchase_status,
                COALESCE(po.expected_date, '') AS purchase_expected_date,
                COALESCE(po.received_date, '') AS purchase_received_date
            FROM procurement_requests pr
            LEFT JOIN projects p ON p.id = pr.project_id
            LEFT JOIN clients cl ON cl.id = pr.client_id
            LEFT JOIN supplier_registry sr ON sr.id = pr.selected_supplier_id
            LEFT JOIN purchase_orders po ON po.id = pr.linked_purchase_id
            ORDER BY pr.updated_at DESC, pr.id DESC
            """
        )
        return _filter_scope_rows_for_actor(actor, rows) if actor else rows

    def _procurement_tender_rows():
        rows = _rows(
            """
            SELECT
                t.*,
                COALESCE(pr.title, '') AS request_title,
                COALESCE(pr.item_article, '') AS item_article,
                COALESCE(pr.item_name, '') AS item_name,
                COALESCE(sr.supplier_name, '') AS selected_supplier_name
            FROM procurement_tenders t
            LEFT JOIN procurement_requests pr ON pr.id = t.request_id
            LEFT JOIN supplier_registry sr ON sr.id = t.selected_supplier_id
            ORDER BY t.updated_at DESC, t.id DESC
            """
        )
        for row in rows:
            row["criteria"] = _json_load(row.get("criteria_json"), {})
        return rows

    def _procurement_bid_rows():
        return _rows(
            """
            SELECT
                b.*,
                COALESCE(t.tender_number, '') AS tender_number,
                COALESCE(sr.supplier_name, b.supplier_name, '') AS registry_supplier_name
            FROM procurement_tender_bids b
            LEFT JOIN procurement_tenders t ON t.id = b.tender_id
            LEFT JOIN supplier_registry sr ON sr.id = b.supplier_id
            ORDER BY b.tender_id DESC, b.score DESC, b.price ASC, b.id DESC
            """
        )

    def _purchase_receipt_rows():
        return _rows(
            """
            SELECT
                r.*,
                COALESCE(po.item_name, '') AS purchase_item_name,
                COALESCE(sr.supplier_name, '') AS supplier_name
            FROM purchase_receipts r
            LEFT JOIN purchase_orders po ON po.id = r.purchase_id
            LEFT JOIN supplier_registry sr ON sr.id = r.supplier_id
            ORDER BY r.created_at DESC, r.id DESC
            """
        )

    def _purchase_document_rows():
        return _rows(
            """
            SELECT
                d.*,
                COALESCE(po.item_name, '') AS purchase_item_name,
                COALESCE(sr.supplier_name, '') AS supplier_name
            FROM purchase_documents d
            LEFT JOIN purchase_orders po ON po.id = d.purchase_id
            LEFT JOIN supplier_registry sr ON sr.id = d.supplier_id
            ORDER BY d.created_at DESC, d.id DESC
            """
        )

    def _sales_customer_order_rows():
        return _rows(
            """
            SELECT
                o.*,
                COALESCE(cl.name, '') AS client_name,
                COALESCE(p.name, '') AS project_name,
                COALESCE(q.quote_number, '') AS quote_number,
                COALESCE(sd.doc_number, '') AS sales_doc_number,
                COALESCE(sr.status, '') AS reservation_status,
                COALESCE(sr.fulfilled_qty, 0) AS reserved_fulfilled_qty
            FROM sales_customer_orders o
            LEFT JOIN clients cl ON cl.id = o.client_id
            LEFT JOIN projects p ON p.id = o.project_id
            LEFT JOIN sales_quotes q ON q.id = o.quote_id
            LEFT JOIN sales_documents_extended sd ON sd.id = o.sales_document_id
            LEFT JOIN stock_reservations sr ON sr.id = o.reservation_id
            ORDER BY o.created_at DESC, o.id DESC
            """
        )

    def _sales_shipment_rows():
        return _rows(
            """
            SELECT
                s.*,
                COALESCE(o.order_number, '') AS customer_order_number,
                COALESCE(sd.doc_number, '') AS sales_doc_number
            FROM sales_shipments s
            LEFT JOIN sales_customer_orders o ON o.id = s.customer_order_id
            LEFT JOIN sales_documents_extended sd ON sd.id = s.sales_document_id
            ORDER BY s.created_at DESC, s.id DESC
            """
        )

    def _sales_payment_schedule_rows():
        rows = _rows(
            """
            SELECT
                ps.*,
                COALESCE(o.order_number, '') AS customer_order_number,
                COALESCE(sd.doc_number, '') AS sales_doc_number,
                COALESCE(fp.status, '') AS payment_status,
                COALESCE(fp.paid_date, '') AS finance_paid_date
            FROM sales_payment_schedules ps
            LEFT JOIN sales_customer_orders o ON o.id = ps.customer_order_id
            LEFT JOIN sales_documents_extended sd ON sd.id = ps.sales_document_id
            LEFT JOIN finance_payments fp ON fp.id = ps.payment_id
            ORDER BY ps.due_date ASC, ps.id DESC
            """
        )
        for row in rows:
            due = row.get("due_date") or ""
            status = row.get("status") or "planned"
            row["overdue_days"] = max(_days_between(due), 0) if due and status not in {"paid", "closed"} else 0
            if row["overdue_days"] > 0 and status == "planned":
                row["status_effective"] = "overdue"
            else:
                row["status_effective"] = status
        return rows

    def _sales_deal_margin_rows():
        return _rows(
            """
            SELECT
                m.*,
                COALESCE(o.order_number, '') AS customer_order_number,
                COALESCE(o.article, '') AS article,
                COALESCE(o.item_name, '') AS item_name,
                COALESCE(sd.doc_number, '') AS sales_doc_number
            FROM sales_deal_margins m
            LEFT JOIN sales_customer_orders o ON o.id = m.customer_order_id
            LEFT JOIN sales_documents_extended sd ON sd.id = m.sales_document_id
            ORDER BY m.updated_at DESC, m.id DESC
            """
        )

    def _best_procurement_bid(tender_id: int):
        bids = [row for row in _procurement_bid_rows() if _safe_int(row.get("tender_id")) == _safe_int(tender_id)]
        if not bids:
            return None
        return sorted(bids, key=lambda row: (-_safe_float(row.get("score")), _safe_float(row.get("price")), _safe_int(row.get("lead_time_days"))))[0]

    def _create_purchase_from_request(conn, request_row: dict, actor: dict, supplier_id: int = 0, bid_row: dict | None = None):
        now = now_ts()
        supplier_name = (bid_row or {}).get("supplier_name") or ""
        if supplier_id:
            row = conn.execute("SELECT supplier_name FROM supplier_registry WHERE id=?", (_safe_int(supplier_id),)).fetchone()
            if row:
                supplier_name = row[0] if not isinstance(row, dict) else row.get("supplier_name", supplier_name)
        unit_price = _safe_float((bid_row or {}).get("price")) or _safe_float(request_row.get("target_unit_price"))
        qty = _safe_float(request_row.get("qty"))
        purchase_id = _insert(conn, "purchase_orders", {
            "project_id": _safe_int(request_row.get("project_id")),
            "client_id": _safe_int(request_row.get("client_id")),
            "contract_id": _safe_int(request_row.get("contract_id")),
            "object_id": _safe_int(request_row.get("object_id")),
            "legal_entity_id": _safe_int(request_row.get("legal_entity_id")),
            "business_unit_id": _safe_int(request_row.get("business_unit_id")),
            "item_article": request_row.get("item_article") or "",
            "item_name": request_row.get("item_name") or request_row.get("title") or "",
            "supplier": supplier_name,
            "supplier_id": _safe_int(supplier_id),
            "qty": qty,
            "unit": request_row.get("unit") or "шт",
            "unit_price": unit_price,
            "planned_unit_price": _safe_float(request_row.get("target_unit_price")),
            "total_amount": round(qty * unit_price, 2),
            "status": "ordered",
            "expected_date": request_row.get("required_date") or "",
            "planned_delivery_date": request_row.get("required_date") or "",
            "received_date": "",
            "delivered_qty": 0,
            "request_status": "approved",
            "approval_status": "approved",
            "schedule_status": "planned",
            "lead_time_days": _safe_int((bid_row or {}).get("lead_time_days")),
            "comment": f"Создано из заявки {request_row.get('request_number') or request_row.get('id')}",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.execute(
            "UPDATE procurement_requests SET status='ordered', linked_purchase_id=?, selected_supplier_id=?, updated_at=? WHERE id=?",
            (purchase_id, _safe_int(supplier_id), now, _safe_int(request_row.get("id"))),
        )
        return purchase_id

    def _procurement_sla_rows(request_rows, tender_rows, purchase_rows, receipt_rows, document_rows):
        tender_by_request = defaultdict(list)
        purchase_by_id = {_safe_int(row.get("id")): row for row in purchase_rows}
        receipts_by_purchase = defaultdict(list)
        docs_by_purchase = defaultdict(list)
        for row in tender_rows:
            tender_by_request[_safe_int(row.get("request_id"))].append(row)
        for row in receipt_rows:
            receipts_by_purchase[_safe_int(row.get("purchase_id"))].append(row)
        for row in document_rows:
            docs_by_purchase[_safe_int(row.get("purchase_id"))].append(row)

        result = []
        for request_row in request_rows:
            created_at = _safe_int(request_row.get("created_at"))
            age_days = max(0, int((now_ts() - created_at) / 86400)) if created_at else 0
            linked_purchase_id = _safe_int(request_row.get("linked_purchase_id"))
            purchase = purchase_by_id.get(linked_purchase_id, {})
            tenders = tender_by_request.get(_safe_int(request_row.get("id")), [])
            receipts = receipts_by_purchase.get(linked_purchase_id, [])
            docs = docs_by_purchase.get(linked_purchase_id, [])
            status = request_row.get("status") or "draft"
            risks = []
            if status in {"draft", "new"} and age_days > 2:
                risks.append("заявка не согласована >2 дн.")
            if status not in {"ordered", "received", "closed", "cancelled"} and not tenders and age_days > 3:
                risks.append("тендер не запущен >3 дн.")
            if status in {"approved", "tender", "awarded"} and linked_purchase_id <= 0 and age_days > 5:
                risks.append("заказ поставщику не создан >5 дн.")
            if linked_purchase_id and purchase and (purchase.get("status") or "") not in {"received", "closed"} and _safe_int(purchase.get("delivery_delay_days")) > 0:
                risks.append(f"поставка просрочена {_safe_int(purchase.get('delivery_delay_days'))} дн.")
            if linked_purchase_id and purchase and _safe_float(purchase.get("delivered_qty")) < _safe_float(purchase.get("qty")) and (purchase.get("status") or "") in {"received", "partial"}:
                risks.append("неполная приемка")
            if linked_purchase_id and receipts and not docs and age_days > 7:
                risks.append("нет счета/УПД после приемки")
            result.append({
                "request_id": _safe_int(request_row.get("id")),
                "request_number": request_row.get("request_number") or f"PR-{request_row.get('id')}",
                "title": request_row.get("title") or request_row.get("item_name") or "Заявка",
                "status": status,
                "age_days": age_days,
                "tenders": len(tenders),
                "linked_purchase_id": linked_purchase_id,
                "receipts": len(receipts),
                "documents": len(docs),
                "risk_level": "risk" if risks else ("warning" if status not in {"received", "closed", "cancelled"} and age_days > 3 else "stable"),
                "risks": risks or ["Сроки в норме"],
            })
        result.sort(key=lambda row: (row["risk_level"] == "risk", row["age_days"]), reverse=True)
        return result

    def _wms_cell_rows():
        cells = _rows("SELECT * FROM wms_cell_profiles ORDER BY warehouse ASC, zone_name ASC, bin_code ASC")
        balances = _rows(
            """
            SELECT warehouse, bin_code, COALESCE(SUM(qty), 0) AS current_qty, COUNT(*) AS article_positions
            FROM inventory_balances
            GROUP BY warehouse, bin_code
            """
        )
        balance_by_cell = {(row.get("warehouse") or "", row.get("bin_code") or ""): row for row in balances}
        for row in cells:
            balance = balance_by_cell.get((row.get("warehouse") or "", row.get("bin_code") or ""), {})
            current_qty = round(_safe_float(balance.get("current_qty")), 3)
            capacity = _safe_float(row.get("capacity_qty"))
            free_qty = round(capacity - current_qty, 3) if capacity > 0 else 0
            load_percent = round((current_qty / capacity) * 100, 1) if capacity > 0 else 0
            row["current_qty"] = current_qty
            row["free_qty"] = free_qty
            row["load_percent"] = load_percent
            row["article_positions"] = _safe_int(balance.get("article_positions"))
            row["risk_level"] = "risk" if capacity > 0 and current_qty > capacity else ("warning" if load_percent >= 85 else "stable")
        return cells

    def _wms_putaway_rows():
        return _rows("SELECT * FROM wms_putaway_tasks ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'done' THEN 2 ELSE 3 END, priority DESC, created_at DESC, id DESC")

    def _wms_pick_wave_rows():
        rows = _rows(
            """
            SELECT
                w.*,
                COUNT(t.id) AS tasks_total,
                SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) AS tasks_done,
                COALESCE(SUM(t.qty), 0) AS qty_total,
                COALESCE(SUM(t.picked_qty), 0) AS picked_total
            FROM wms_pick_waves w
            LEFT JOIN wms_pick_tasks t ON t.wave_id = w.id
            GROUP BY w.id
            ORDER BY w.created_at DESC, w.id DESC
            """
        )
        for row in rows:
            row["completion_percent"] = 100 if _safe_float(row.get("qty_total")) <= 0 else round((_safe_float(row.get("picked_total")) / max(_safe_float(row.get("qty_total")), 0.0001)) * 100, 1)
        return rows

    def _wms_pick_task_rows():
        return _rows(
            """
            SELECT
                t.*,
                COALESCE(w.wave_number, '') AS wave_number,
                COALESCE(r.status, '') AS reservation_status
            FROM wms_pick_tasks t
            LEFT JOIN wms_pick_waves w ON w.id = t.wave_id
            LEFT JOIN stock_reservations r ON r.id = t.reservation_id
            ORDER BY CASE t.status WHEN 'open' THEN 0 WHEN 'partial' THEN 1 WHEN 'done' THEN 2 ELSE 3 END, t.created_at DESC, t.id DESC
            """
        )

    def _wms_cycle_count_rows():
        rows = _rows(
            """
            SELECT
                c.*,
                COUNT(l.id) AS lines_total,
                SUM(CASE WHEN ABS(COALESCE(l.variance_qty, 0)) > 0.0001 THEN 1 ELSE 0 END) AS variance_lines,
                COALESCE(SUM(ABS(l.variance_qty)), 0) AS variance_abs_qty
            FROM wms_cycle_counts c
            LEFT JOIN wms_cycle_count_lines l ON l.count_id = c.id
            GROUP BY c.id
            ORDER BY CASE c.status WHEN 'draft' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'closed' THEN 2 ELSE 3 END, c.created_at DESC, c.id DESC
            """
        )
        return rows

    def _wms_cycle_count_line_rows(count_id: int = 0):
        if count_id:
            return _rows("SELECT * FROM wms_cycle_count_lines WHERE count_id=? ORDER BY id ASC", (_safe_int(count_id),))
        return _rows("SELECT * FROM wms_cycle_count_lines ORDER BY created_at DESC, id DESC LIMIT 200")

    def _wms_lot_position_rows(limit: int = 120):
        return _rows(
            """
            SELECT article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date, qty, updated_at
            FROM inventory_lots
            WHERE ABS(COALESCE(qty, 0)) > 0.0001
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )

    def _wms_expected_qty(c, article: str, warehouse: str, bin_code: str, batch_code: str = "", serial_no: str = "") -> float:
        if batch_code or serial_no:
            c.execute(
                """
                SELECT COALESCE(SUM(qty), 0)
                FROM inventory_lots
                WHERE article=? AND warehouse=? AND bin_code=? AND batch_code=? AND serial_no=?
                """,
                (article, warehouse, bin_code, batch_code or "", serial_no or ""),
            )
        else:
            c.execute(
                "SELECT COALESCE(SUM(qty), 0) FROM inventory_balances WHERE article=? AND warehouse=? AND bin_code=?",
                (article, warehouse, bin_code),
            )
        row = c.fetchone()
        if isinstance(row, dict):
            return _safe_float(next(iter(row.values()), 0))
        return _safe_float(row[0] if row else 0)

    def _record_stock_movement(c, article: str, item_name: str, qty: float, movement_type: str, from_warehouse: str = "", from_bin: str = "", to_warehouse: str = "", to_bin: str = "", batch_code: str = "", serial_no: str = "", actor_email: str = "", comment: str = "", reason: str = "", reservation_id: int = 0, document_id: int = 0, document_type: str = "", lot_expiration_date: str = "", unit_cost: float = 0, cost_amount: float = 0):
        c.execute(
            """
            INSERT INTO stock_movements (
                article, name, qty, movement_type, from_warehouse, from_bin, to_warehouse, to_bin,
                comment, actor_email, created_at, batch_code, serial_no, reservation_id, document_id, document_type, reason,
                lot_expiration_date, unit_cost, cost_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article,
                item_name or article,
                round(_safe_float(qty), 3),
                movement_type,
                from_warehouse or "",
                from_bin or "",
                to_warehouse or "",
                to_bin or "",
                comment or "",
                actor_email or "",
                now_ts(),
                batch_code or "",
                serial_no or "",
                _safe_int(reservation_id),
                _safe_int(document_id),
                document_type or "",
                reason or "",
                lot_expiration_date or "",
                _safe_float(unit_cost),
                _safe_float(cost_amount),
            ),
        )
        return getattr(c, "lastrowid", 0)

    def _create_sales_receivable_payment(conn, order_row: dict, schedule_payload: dict, actor: dict):
        now = now_ts()
        amount = _safe_float(schedule_payload.get("amount"))
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO finance_payments (
                project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id,
                source_document_type, source_document_id, title, kind, category, amount, currency, due_date,
                paid_date, status, comment, exchange_state, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'sales_payment_schedule', 0, ?, 'incoming', 'receivable', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _safe_int(order_row.get("project_id")),
                _safe_int(order_row.get("client_id")),
                _safe_int(order_row.get("contract_id")),
                _safe_int(order_row.get("object_id")),
                _safe_int(order_row.get("legal_entity_id")),
                _safe_int(order_row.get("business_unit_id")),
                schedule_payload.get("title") or f"Оплата по заказу {order_row.get('order_number') or order_row.get('id')}",
                amount,
                schedule_payload.get("currency") or order_row.get("currency") or "RUB",
                schedule_payload.get("due_date") or "",
                schedule_payload.get("paid_date") or "",
                schedule_payload.get("status") or "planned",
                schedule_payload.get("comment") or "",
                "synced" if (schedule_payload.get("status") or "") == "paid" else "queued",
                actor.get("email", ""),
                now,
                now,
            ),
        )
        return c.lastrowid

    def _create_sales_document_for_order(conn, order_row: dict, actor: dict):
        now = now_ts()
        c = conn.cursor()
        doc_number = f"INV-{order_row.get('order_number') or order_row.get('id')}"
        c.execute(
            """
            INSERT INTO sales_documents_extended (
                project_id, client_id, contract_id, object_id, legal_entity_id, business_unit_id, doc_type, doc_number, doc_date, amount, currency, status,
                payment_status, linked_payment_id, customer_order_no, shipment_status, payment_due_date, planned_ship_date, shipped_at, reserve_status, reserve_qty, price_list_id, discount_percent, discount_amount,
                comment, recipient_email, sent_status, sent_at, delivered_at, confirmed_at, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'invoice', ?, ?, ?, ?, 'issued', 'planned', 0, ?, 'ready', ?, ?, '', ?, ?, 0, 0, 0, ?, '', 'draft', '', '', '', ?, ?, ?)
            """,
            (
                _safe_int(order_row.get("project_id")),
                _safe_int(order_row.get("client_id")),
                _safe_int(order_row.get("contract_id")),
                _safe_int(order_row.get("object_id")),
                _safe_int(order_row.get("legal_entity_id")),
                _safe_int(order_row.get("business_unit_id")),
                doc_number,
                datetime.now().strftime("%d.%m.%Y"),
                _safe_float(order_row.get("amount")),
                order_row.get("currency") or "RUB",
                order_row.get("order_number") or "",
                order_row.get("requested_ship_date") or "",
                order_row.get("requested_ship_date") or "",
                order_row.get("reserve_status") or "none",
                _safe_float(order_row.get("qty")),
                order_row.get("comment") or "Создано из заказа клиента",
                actor.get("email", ""),
                now,
                now,
            ),
        )
        document_id = c.lastrowid
        c.execute("UPDATE sales_customer_orders SET sales_document_id=?, updated_at=? WHERE id=?", (document_id, now, _safe_int(order_row.get("id"))))
        return document_id

    def _calculate_sales_margin(conn, order_row: dict, direct_cost_amount: float = 0, discount_amount: float = 0, actor_email: str = ""):
        c = conn.cursor()
        article = order_row.get("article") or ""
        qty = _safe_float(order_row.get("qty"))
        revenue = _safe_float(order_row.get("amount"))
        purchase_unit_cost = 0.0
        if article:
            c.execute("SELECT COALESCE(SUM(total_amount), 0), COALESCE(SUM(qty), 0) FROM purchase_orders WHERE item_article=?", (article,))
            row = c.fetchone()
            if isinstance(row, dict):
                values = list(row.values())
                purchase_total = _safe_float(values[0] if values else 0)
                purchase_qty = _safe_float(values[1] if len(values) > 1 else 0)
            else:
                purchase_total = _safe_float(row[0] if row else 0)
                purchase_qty = _safe_float(row[1] if row else 0)
            if purchase_qty > 0:
                purchase_unit_cost = purchase_total / purchase_qty
            else:
                c.execute("SELECT price FROM nomenclature WHERE article=? ORDER BY id DESC LIMIT 1", (article,))
                price_row = c.fetchone()
                purchase_unit_cost = _safe_float((price_row.get("price") if isinstance(price_row, dict) else price_row[0]) if price_row else 0)
        purchase_cost = round(purchase_unit_cost * qty, 2)
        direct_cost = _safe_float(direct_cost_amount)
        discount = _safe_float(discount_amount)
        margin = round(revenue - purchase_cost - direct_cost - discount, 2)
        margin_percent = round((margin / revenue) * 100, 2) if revenue > 0 else 0
        now = now_ts()
        c.execute(
            "DELETE FROM sales_deal_margins WHERE customer_order_id=? AND sales_document_id=?",
            (_safe_int(order_row.get("id")), _safe_int(order_row.get("sales_document_id"))),
        )
        payload = {
            "purchase_unit_cost": round(purchase_unit_cost, 2),
            "qty": qty,
            "article": article,
            "order_number": order_row.get("order_number") or "",
        }
        margin_id = _insert(conn, "sales_deal_margins", {
            "customer_order_id": _safe_int(order_row.get("id")),
            "sales_document_id": _safe_int(order_row.get("sales_document_id")),
            "revenue_amount": revenue,
            "direct_cost_amount": direct_cost,
            "purchase_cost_amount": purchase_cost,
            "discount_amount": discount,
            "margin_amount": margin,
            "margin_percent": margin_percent,
            "status": "risk" if margin_percent < 10 else "calculated",
            "calculation_json": json.dumps(payload, ensure_ascii=False),
            "created_by": actor_email,
            "created_at": now,
            "updated_at": now,
        })
        return margin_id

    def _warehouse_discrepancy_rows(limit: int = 120):
        return _rows(
            """
            SELECT
                d.*,
                COALESCE(n.name, '') AS nomenclature_name,
                COALESCE(n.unit, 'шт') AS unit
            FROM inventory_documents d
            LEFT JOIN nomenclature n ON n.article = d.article
            WHERE ABS(COALESCE(d.adjustment_qty, 0)) > 0.0001
            ORDER BY d.created_at DESC, d.id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )

    def _aggregate_reason_rows(rows, field_name: str, qty_field: str = "qty"):
        grouped = defaultdict(lambda: {"reason": "", "count": 0, "qty": 0.0})
        for row in rows:
            reason = (row.get(field_name) or "Без причины").strip() or "Без причины"
            bucket = grouped[reason]
            bucket["reason"] = reason
            bucket["count"] += 1
            bucket["qty"] += abs(_safe_float(row.get(qty_field)))
        return sorted(grouped.values(), key=lambda item: (item["count"], item["qty"]), reverse=True)

    def _aggregate_quality_rows(rows):
        grouped = defaultdict(lambda: {"status": "", "count": 0, "qty": 0.0})
        for row in rows:
            status = (row.get("quality_status") or row.get("status") or "open").strip() or "open"
            bucket = grouped[status]
            bucket["status"] = status
            bucket["count"] += 1
            bucket["qty"] += abs(_safe_float(row.get("qty")))
        return sorted(grouped.values(), key=lambda item: (item["count"], item["qty"]), reverse=True)

    def _stock_journal_rows(limit: int = 120):
        docs = _load_inventory_document_rows(limit)
        acts = _rows("SELECT * FROM inventory_acts ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),))
        quality = _rows("SELECT * FROM warehouse_quality_reports ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),))
        regrading = _rows("SELECT * FROM inventory_regrading_docs ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),))
        discrepancies = _warehouse_discrepancy_rows(limit)
        movements = _rows(
            """
            SELECT id, article, name, qty, movement_type, from_warehouse, from_bin, to_warehouse, to_bin, reason, comment, created_at
            FROM stock_movements
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )
        rows = []
        for row in docs:
            rows.append({
                "entity_type": "inventory_document",
                "entity_id": _safe_int(row.get("id")),
                "journal_type": "document",
                "title": row.get("doc_number") or f"Документ #{row.get('id')}",
                "subtitle": f"{row.get('doc_type') or 'inventory'} · {row.get('nomenclature_name') or row.get('article') or 'Номенклатура'}",
                "warehouse": row.get("warehouse") or "",
                "bin_code": row.get("bin_code") or "",
                "qty": _safe_float(row.get("qty")),
                "status": row.get("status") or "",
                "reason": row.get("reason") or "",
                "created_at": _safe_int(row.get("created_at")),
                "severity": "warning" if abs(_safe_float(row.get("adjustment_qty"))) > 0.0001 else ("success" if row.get("status") == "posted" else "neutral"),
                "can_print": True,
                "can_delete": False,
            })
        for row in acts:
            rows.append({
                "entity_type": "inventory_act",
                "entity_id": _safe_int(row.get("id")),
                "journal_type": "inventory_act",
                "title": f"Акт инвентаризации #{row.get('id')}",
                "subtitle": row.get("item_name") or row.get("article") or "Номенклатура",
                "warehouse": row.get("warehouse") or "",
                "bin_code": row.get("bin_code") or "",
                "qty": _safe_float(row.get("counted_qty")),
                "status": row.get("status") or "",
                "reason": row.get("comment") or "",
                "created_at": _safe_int(row.get("created_at")),
                "severity": "warning" if abs(_safe_float(row.get("adjustment_qty"))) > 0.0001 else "success",
                "can_print": True,
                "can_delete": True,
            })
        for row in regrading:
            rows.append({
                "entity_type": "regrading_doc",
                "entity_id": _safe_int(row.get("id")),
                "journal_type": "regrading",
                "title": f"Пересортица #{row.get('id')}",
                "subtitle": f"{row.get('from_name') or row.get('from_article') or 'Источник'} -> {row.get('to_name') or row.get('to_article') or 'Приёмник'}",
                "warehouse": row.get("warehouse") or "",
                "bin_code": row.get("bin_code") or "",
                "qty": _safe_float(row.get("qty")),
                "status": row.get("status") or "",
                "reason": row.get("reason") or "",
                "created_at": _safe_int(row.get("created_at")),
                "severity": "attention" if (row.get("status") or "") not in {"posted", "closed"} else "success",
                "can_print": True,
                "can_delete": True,
            })
        for row in quality:
            rows.append({
                "entity_type": "quality_report",
                "entity_id": _safe_int(row.get("id")),
                "journal_type": "quality",
                "title": f"Качество #{row.get('id')}",
                "subtitle": row.get("item_name") or row.get("article") or "Номенклатура",
                "warehouse": row.get("warehouse") or "",
                "bin_code": row.get("bin_code") or "",
                "qty": _safe_float(row.get("qty")),
                "status": row.get("status") or "",
                "reason": row.get("defect_kind") or row.get("decision") or "",
                "created_at": _safe_int(row.get("created_at")),
                "severity": "warning" if (row.get("status") or "") not in {"closed", "released"} else "success",
                "can_print": True,
                "can_delete": False,
            })
        for row in discrepancies:
            rows.append({
                "entity_type": "discrepancy_act",
                "entity_id": _safe_int(row.get("id")),
                "journal_type": "discrepancy",
                "title": row.get("doc_number") or f"Акт расхождения #{row.get('id')}",
                "subtitle": row.get("nomenclature_name") or row.get("article") or "Номенклатура",
                "warehouse": row.get("warehouse") or "",
                "bin_code": row.get("bin_code") or "",
                "qty": abs(_safe_float(row.get("adjustment_qty"))),
                "status": row.get("status") or "",
                "reason": row.get("reason") or "",
                "created_at": _safe_int(row.get("created_at")),
                "severity": "warning",
                "can_print": True,
                "can_delete": False,
            })
        for row in movements:
            rows.append({
                "entity_type": "stock_movement",
                "entity_id": _safe_int(row.get("id")),
                "journal_type": "movement",
                "title": row.get("name") or row.get("article") or "Движение",
                "subtitle": row.get("movement_type") or "movement",
                "warehouse": row.get("to_warehouse") or row.get("from_warehouse") or "",
                "bin_code": row.get("to_bin") or row.get("from_bin") or "",
                "qty": _safe_float(row.get("qty")),
                "status": "posted",
                "reason": row.get("reason") or row.get("comment") or "",
                "created_at": _safe_int(row.get("created_at")),
                "severity": "neutral",
                "can_print": False,
                "can_delete": False,
            })
        rows.sort(key=lambda item: (item.get("created_at") or 0, item.get("entity_id") or 0), reverse=True)
        return rows[: max(1, min(limit, 500))]

    def _print_payload(title: str, lines: list[str], entity_type: str = "", entity_id: int = 0):
        return {"status": "success", "title": title, "lines": lines, "html": "<br>".join(lines), "entity_type": entity_type, "entity_id": entity_id}

    def _print_inventory_document_payload(doc_id: int):
        rows = _rows("SELECT d.*, COALESCE(n.name, '') AS item_name, COALESCE(n.unit, 'шт') AS unit FROM inventory_documents d LEFT JOIN nomenclature n ON n.article = d.article WHERE d.id=?", (doc_id,))
        if not rows:
            return None
        row = rows[0]
        return _print_payload(
            f"Складской документ {row.get('doc_number') or doc_id}",
            [
                f"Тип: {row.get('doc_type') or ''}",
                f"Документ: {row.get('doc_number') or doc_id}",
                f"Номенклатура: {row.get('item_name') or row.get('article') or ''}",
                f"Склад: {row.get('warehouse') or ''}",
                f"Ячейка: {row.get('bin_code') or ''}",
                f"Количество: {row.get('qty') or 0}",
                f"Подсчёт: {row.get('counted_qty') or 0}",
                f"Корректировка: {row.get('adjustment_qty') or 0}",
                f"Статус: {row.get('status') or ''}",
                f"Причина: {row.get('reason') or ''}",
                f"Комментарий: {row.get('comment') or ''}",
            ],
            "inventory_document",
            doc_id,
        )

    def _print_inventory_act_payload(row_id: int):
        rows = _rows("SELECT * FROM inventory_acts WHERE id=?", (row_id,))
        if not rows:
            return None
        row = rows[0]
        return _print_payload(
            f"Акт инвентаризации #{row.get('id')}",
            [
                f"Акт: #{row.get('id')}",
                f"Номенклатура: {row.get('item_name') or row.get('article') or ''}",
                f"Склад: {row.get('warehouse') or ''}",
                f"Ячейка: {row.get('bin_code') or ''}",
                f"Учётный остаток: {row.get('expected_qty') or 0}",
                f"Фактический остаток: {row.get('counted_qty') or 0}",
                f"Корректировка: {row.get('adjustment_qty') or 0}",
                f"Статус: {row.get('status') or ''}",
                f"Комментарий: {row.get('comment') or ''}",
            ],
            "inventory_act",
            row_id,
        )

    def _print_regrading_payload(row_id: int):
        rows = _rows("SELECT * FROM inventory_regrading_docs WHERE id=?", (row_id,))
        if not rows:
            return None
        row = rows[0]
        return _print_payload(
            f"Пересортица #{row.get('id')}",
            [
                f"Документ: Пересортица #{row.get('id')}",
                f"Склад: {row.get('warehouse') or ''}",
                f"Ячейка: {row.get('bin_code') or ''}",
                f"Из: {row.get('from_name') or row.get('from_article') or ''}",
                f"В: {row.get('to_name') or row.get('to_article') or ''}",
                f"Количество: {row.get('qty') or 0}",
                f"Причина: {row.get('reason') or ''}",
                f"Статус: {row.get('status') or ''}",
                f"Комментарий: {row.get('comment') or ''}",
            ],
            "regrading_doc",
            row_id,
        )

    def _print_quality_payload(row_id: int):
        rows = _rows("SELECT * FROM warehouse_quality_reports WHERE id=?", (row_id,))
        if not rows:
            return None
        row = rows[0]
        return _print_payload(
            f"Качество #{row.get('id')}",
            [
                f"Отчёт качества: #{row.get('id')}",
                f"Номенклатура: {row.get('item_name') or row.get('article') or ''}",
                f"Склад: {row.get('warehouse') or ''}",
                f"Ячейка: {row.get('bin_code') or ''}",
                f"Количество: {row.get('qty') or 0}",
                f"Статус качества: {row.get('quality_status') or ''}",
                f"Дефект: {row.get('defect_kind') or ''}",
                f"Решение: {row.get('decision') or ''}",
                f"Статус: {row.get('status') or ''}",
                f"Комментарий: {row.get('comment') or ''}",
            ],
            "quality_report",
            row_id,
        )

    def _print_discrepancy_payload(row_id: int):
        row = next((item for item in _warehouse_discrepancy_rows(300) if _safe_int(item.get("id")) == _safe_int(row_id)), None)
        if not row:
            return None
        return _print_payload(
            f"Акт расхождения {row.get('doc_number') or row_id}",
            [
                f"Акт расхождения: {row.get('doc_number') or row_id}",
                f"Номенклатура: {row.get('nomenclature_name') or row.get('article') or ''}",
                f"Склад: {row.get('warehouse') or ''}",
                f"Ячейка: {row.get('bin_code') or ''}",
                f"Учётный остаток: {row.get('qty') or 0}",
                f"Фактический остаток: {row.get('counted_qty') or 0}",
                f"Корректировка: {row.get('adjustment_qty') or 0}",
                f"Причина: {row.get('reason') or ''}",
                f"Статус: {row.get('status') or ''}",
            ],
            "discrepancy_act",
            row_id,
        )

    def enhanced_load_purchase_rows():
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT
                po.*,
                COALESCE(p.name, '') AS project_name,
                COALESCE(p.contract, '') AS project_contract,
                COALESCE(cl.name, '') AS client_name,
                COALESCE(le.short_name, le.name, '') AS legal_entity_name,
                COALESCE(bu.name, '') AS business_unit_name,
                COALESCE(fp.id, 0) AS linked_payment_id,
                COALESCE(fp.status, '') AS linked_payment_status,
                COALESCE(fp.exchange_state, '') AS linked_payment_exchange_state,
                COALESCE(sr.supplier_name, po.supplier, '') AS supplier_name,
                COALESCE(sr.rating, 0) AS supplier_rating,
                COALESCE(sr.reliability_percent, 100) AS supplier_reliability
            FROM purchase_orders po
            LEFT JOIN projects p ON p.id = po.project_id
            LEFT JOIN clients cl ON cl.id = po.client_id
            LEFT JOIN legal_entities le ON le.id = po.legal_entity_id
            LEFT JOIN business_units bu ON bu.id = po.business_unit_id
            LEFT JOIN finance_payments fp ON fp.source_document_type='purchase_order' AND fp.source_document_id = po.id
            LEFT JOIN supplier_registry sr ON sr.id = po.supplier_id
            ORDER BY po.created_at DESC, po.id DESC
            """
        )
        rows = [dict(row) for row in c.fetchall()]
        conn.close()
        for row in rows:
            planned_unit_price = _safe_float(row.get("planned_unit_price")) or _safe_float(row.get("unit_price"))
            row["price_variance"] = round(_safe_float(row.get("unit_price")) - planned_unit_price, 2)
            row["underdelivery_qty"] = round(max(_safe_float(row.get("qty")) - _safe_float(row.get("delivered_qty")), 0), 3)
            plan_date = row.get("planned_delivery_date") or row.get("expected_date") or ""
            row["delivery_delay_days"] = max(_days_between(plan_date, row.get("received_date")), 0) if row.get("received_date") else max(_days_between(plan_date), 0) if plan_date and row.get("status") not in {"received"} else 0
        return rows

    def enhanced_load_sales_rows():
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT
                sd.*,
                COALESCE(p.name, '') AS project_name,
                COALESCE(p.contract, '') AS project_contract,
                COALESCE(cl.name, '') AS client_name,
                COALESCE(le.short_name, le.name, '') AS legal_entity_name,
                COALESCE(bu.name, '') AS business_unit_name,
                COALESCE(fp.status, '') AS linked_payment_status,
                COALESCE(fp.exchange_state, '') AS linked_payment_exchange_state,
                COALESCE(pl.name, '') AS price_list_name
            FROM sales_documents_extended sd
            LEFT JOIN projects p ON p.id = sd.project_id
            LEFT JOIN clients cl ON cl.id = sd.client_id
            LEFT JOIN legal_entities le ON le.id = sd.legal_entity_id
            LEFT JOIN business_units bu ON bu.id = sd.business_unit_id
            LEFT JOIN finance_payments fp ON fp.id = sd.linked_payment_id
            LEFT JOIN price_lists pl ON pl.id = sd.price_list_id
            ORDER BY sd.created_at DESC, sd.id DESC
            """
        )
        rows = [dict(row) for row in c.fetchall()]
        conn.close()
        for row in rows:
            due = row.get("payment_due_date") or ""
            row["overdue_days"] = max(_days_between(due), 0) if due and row.get("payment_status") != "paid" else 0
            row["is_overdue"] = 1 if row["overdue_days"] > 0 else 0
            ship_date = row.get("planned_ship_date") or ""
            row["shipment_late_days"] = max(_days_between(ship_date, row.get("shipped_at")), 0) if ship_date and row.get("shipped_at") else max(_days_between(ship_date), 0) if ship_date and row.get("shipment_status") not in {"shipped", "delivered"} else 0
        return rows

    def policy_pick_inventory_source(c, article: str, qty: float):
        _bootstrap_inventory_lots_for_article(c, article)
        policy = _policy_settings(c)
        order_by = pick_lot_order_sql(policy, qty)
        c.execute(f"SELECT warehouse, bin_code, batch_code, serial_no, lot_expiration_date, qty FROM inventory_lots WHERE article=? AND qty > 0 ORDER BY {order_by}", (article,))
        lots = []
        for row in c.fetchall():
            if isinstance(row, dict):
                warehouse = row.get("warehouse")
                bin_code = row.get("bin_code")
                batch_code = row.get("batch_code")
                serial_no = row.get("serial_no")
                lot_expiration_date = row.get("lot_expiration_date")
                lot_qty = row.get("qty")
            else:
                warehouse, bin_code, batch_code, serial_no, lot_expiration_date, lot_qty = row
            free_qty = round(_safe_float(lot_qty) - _available_reserved_qty(c, article, warehouse, bin_code, batch_code, serial_no), 3)
            if free_qty <= 0:
                continue
            lots.append({"warehouse": warehouse or "Основной склад", "bin_code": bin_code or "A-01", "batch_code": batch_code or "", "serial_no": serial_no or "", "lot_expiration_date": lot_expiration_date or "", "qty": round(_safe_float(lot_qty), 3), "free_qty": free_qty})
        if not lots:
            return None
        return next((item for item in lots if item["free_qty"] >= qty), lots[0])

    def policy_consume_inventory_lots(c, article: str, qty: float, warehouse: str = "", bin_code: str = "", batch_code: str = "", serial_no: str = ""):
        _bootstrap_inventory_lots_for_article(c, article)
        policy = _policy_settings(c)
        clauses = ["article=?", "qty > 0"]
        params = [article]
        if warehouse:
            clauses.append("warehouse=?")
            params.append(warehouse)
        if bin_code:
            clauses.append("bin_code=?")
            params.append(bin_code)
        if batch_code:
            clauses.append("batch_code=?")
            params.append(batch_code)
        if serial_no:
            clauses.append("serial_no=?")
            params.append(serial_no)
        order_by = pick_lot_order_sql(policy, qty)
        c.execute(f"SELECT id, warehouse, bin_code, batch_code, serial_no, lot_expiration_date, qty FROM inventory_lots WHERE {' AND '.join(clauses)} ORDER BY {order_by}", tuple(params))
        remaining = round(_safe_float(qty), 3)
        allocations = []
        for row in c.fetchall():
            if isinstance(row, dict):
                lot_id = row.get("id")
                lot_wh = row.get("warehouse")
                lot_bin = row.get("bin_code")
                lot_batch = row.get("batch_code")
                lot_serial = row.get("serial_no")
                lot_expiration_date = row.get("lot_expiration_date")
                lot_qty = row.get("qty")
            else:
                lot_id, lot_wh, lot_bin, lot_batch, lot_serial, lot_expiration_date, lot_qty = row
            if remaining <= 0:
                break
            available = round(_safe_float(lot_qty), 3)
            if available <= 0:
                continue
            used = min(available, remaining)
            c.execute("UPDATE inventory_lots SET qty=?, updated_at=? WHERE id=?", (round(available - used, 3), int(time.time()), lot_id))
            allocations.append({"warehouse": lot_wh or "Основной склад", "bin_code": lot_bin or "A-01", "batch_code": lot_batch or "", "serial_no": lot_serial or "", "lot_expiration_date": lot_expiration_date or "", "qty": round(used, 3)})
            remaining = round(remaining - used, 3)
        if remaining > 0 and not _safe_int(policy.get("allow_negative_stock")):
            return None, remaining
        if remaining > 0:
            allocations.append({"warehouse": warehouse or "Основной склад", "bin_code": bin_code or "A-01", "batch_code": batch_code or "", "serial_no": serial_no or "", "lot_expiration_date": "", "qty": remaining})
        return allocations, 0

    helpers["_load_purchase_rows"] = enhanced_load_purchase_rows
    helpers["_load_sales_rows"] = enhanced_load_sales_rows
    helpers["_pick_inventory_source"] = policy_pick_inventory_source
    helpers["_consume_inventory_lots"] = policy_consume_inventory_lots

    def _simple_create_route(path: str, table: str, schema_cls, module_name: str, payload_factory, delete_permission: str = "delete"):
        @router.post(path)
        def create_item(data: schema_cls, request: Request):
            actor = require_approved_user(request)
            if not actor or not has_permission(actor, module_name, "create"):
                return {"error": "forbidden"}
            conn = get_connection()
            row_id = _insert(conn, table, payload_factory(data, actor))
            conn.commit()
            conn.close()
            return {"status": "success", "id": row_id}

        @router.delete(f"{path}" + "/{row_id}")
        def delete_item(row_id: int, request: Request):
            actor = require_approved_user(request)
            if not actor or not has_permission(actor, module_name, delete_permission):
                return {"error": "forbidden"}
            _delete(table, row_id)
            return {"status": "success"}

    def now_ts():
        return int(time.time())

    def _terminal_payload(row: dict) -> dict:
        return {
            "id": _safe_int(row.get("id")),
            "terminal_code": row.get("terminal_code") or "",
            "terminal_type": row.get("terminal_type") or "warehouse",
            "device_uid": row.get("device_uid") or "",
            "operator_name": row.get("operator_name") or "",
            "current_zone": row.get("current_zone") or "",
            "status": row.get("status") or "active",
            "last_seen_at": _safe_int(row.get("last_seen_at")),
            "created_by": row.get("created_by") or "",
            "created_at": _safe_int(row.get("created_at")),
            "updated_at": _safe_int(row.get("updated_at")),
        }

    def _terminal_scan_payload(row: dict) -> dict:
        result = _json_load(row.get("result_json"), {})
        return {
            "id": _safe_int(row.get("id")),
            "session_id": _safe_int(row.get("session_id")),
            "terminal_type": row.get("terminal_type") or "",
            "scan_kind": row.get("scan_kind") or "",
            "scan_value": row.get("scan_value") or "",
            "entity_type": row.get("entity_type") or "",
            "entity_id": _safe_int(row.get("entity_id")),
            "action_name": row.get("action_name") or "",
            "result_status": row.get("result_status") or "",
            "result": result,
            "created_by": row.get("created_by") or "",
            "created_at": _safe_int(row.get("created_at")),
        }

    def _ensure_terminal_session(conn, data: TerminalSessionData | TerminalScanData, actor: dict) -> dict:
        c = conn.cursor()
        session_id = _safe_int(getattr(data, "session_id", 0))
        if session_id:
            row = c.execute("SELECT * FROM terminal_sessions WHERE id=?", (session_id,)).fetchone()
            if row:
                return dict(row)
        terminal_code = _normalize_spaces(getattr(data, "terminal_code", "") or "") or f"TERM-{actor.get('role', 'user')}"
        row = c.execute("SELECT * FROM terminal_sessions WHERE terminal_code=? ORDER BY updated_at DESC, id DESC LIMIT 1", (terminal_code,)).fetchone()
        now = now_ts()
        if row:
            session = dict(row)
            c.execute(
                """
                UPDATE terminal_sessions
                SET terminal_type=?, device_uid=?, operator_name=?, current_zone=?, status='active',
                    last_seen_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    getattr(data, "terminal_type", "") or session.get("terminal_type") or "warehouse",
                    getattr(data, "device_uid", "") or session.get("device_uid") or "",
                    getattr(data, "operator_name", "") or actor.get("name", ""),
                    getattr(data, "current_zone", "") or session.get("current_zone") or "",
                    now,
                    now,
                    _safe_int(session.get("id")),
                ),
            )
            session.update({
                "terminal_type": getattr(data, "terminal_type", "") or session.get("terminal_type") or "warehouse",
                "operator_name": getattr(data, "operator_name", "") or actor.get("name", ""),
                "last_seen_at": now,
                "updated_at": now,
            })
            return session
        session_id = _insert(conn, "terminal_sessions", {
            "terminal_code": terminal_code,
            "terminal_type": getattr(data, "terminal_type", "") or "warehouse",
            "device_uid": getattr(data, "device_uid", "") or "",
            "operator_name": getattr(data, "operator_name", "") or actor.get("name", ""),
            "current_zone": getattr(data, "current_zone", "") or "",
            "status": getattr(data, "status", "") or "active",
            "last_seen_at": now,
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        return dict(c.execute("SELECT * FROM terminal_sessions WHERE id=?", (session_id,)).fetchone() or {})

    def _json_response_payload(value):
        if isinstance(value, JSONResponse):
            try:
                return json.loads(value.body.decode("utf-8"))
            except Exception:
                return {"error": "response_parse_failed"}
        return value if isinstance(value, dict) else {"result": value}

    def _log_terminal_scan(conn, session: dict, data: TerminalScanData, actor: dict, result: dict):
        result_status = "error" if result.get("error") else result.get("status", "success")
        row_id = _insert(conn, "terminal_scan_events", {
            "session_id": _safe_int(session.get("id")),
            "terminal_type": data.terminal_type or session.get("terminal_type") or "",
            "scan_kind": data.scan_kind or "barcode",
            "scan_value": data.scan_value or "",
            "entity_type": data.entity_type or "",
            "entity_id": _safe_int(data.entity_id),
            "action_name": data.action_name or "lookup",
            "result_status": result_status,
            "result_json": json.dumps(result, ensure_ascii=False),
            "created_by": actor.get("email", ""),
            "created_at": now_ts(),
        })
        return row_id

    def _resolve_terminal_entity(scan_value: str, entity_type: str = "", entity_id: int = 0) -> tuple[str, int]:
        if entity_type and entity_id:
            return entity_type, _safe_int(entity_id)
        raw = _normalize_spaces(scan_value).upper()
        patterns = [
            ("PUTAWAY-", "wms_putaway_task"),
            ("PICK-", "wms_pick_task"),
            ("COUNT-", "wms_cycle_count_line"),
            ("OP-", "production_operation"),
            ("JOB-", "production_job"),
        ]
        for prefix, kind in patterns:
            if raw.startswith(prefix):
                return kind, _safe_int(raw.replace(prefix, "", 1))
        return entity_type or "", _safe_int(entity_id)

    def _terminal_lookup_payload(conn, entity_type: str, entity_id: int) -> dict:
        table_map = {
            "wms_putaway_task": "wms_putaway_tasks",
            "wms_pick_task": "wms_pick_tasks",
            "wms_cycle_count_line": "wms_cycle_count_lines",
            "production_operation": "production_operations",
            "production_job": "production_jobs",
            "production_order": "production_orders",
        }
        table_name = table_map.get(entity_type or "")
        if not table_name or not entity_id:
            return {}
        return dict(conn.execute(f"SELECT * FROM {table_name} WHERE id=?", (_safe_int(entity_id),)).fetchone() or {})

    def _production_operation_row(conn, operation_id: int) -> dict:
        return dict(conn.execute("SELECT * FROM production_operations WHERE id=?", (_safe_int(operation_id),)).fetchone() or {})

    def _sync_terminal_production_rollup(conn, order_id: int):
        order_id = _safe_int(order_id)
        if not order_id:
            return
        operations = [dict(row) for row in conn.execute("SELECT * FROM production_operations WHERE order_id=?", (order_id,)).fetchall()]
        if not operations:
            return
        planned_qty = sum(_safe_float(row.get("planned_qty")) for row in operations)
        completed_qty = sum(_safe_float(row.get("completed_qty")) for row in operations)
        scrap_qty = sum(_safe_float(row.get("scrap_qty")) for row in operations)
        actual_hours = sum(_safe_float(row.get("actual_hours")) for row in operations)
        operation_cost = sum((_safe_float(row.get("actual_hours")) * _safe_float(row.get("labor_rate"))) + _safe_float(row.get("material_cost")) + _safe_float(row.get("overhead_cost")) for row in operations)
        costing_row = dict(conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN layer_type IN ('material','labor') THEN actual_amount ELSE 0 END), 0)
                + COALESCE(SUM(CASE WHEN layer_type='overhead' THEN overhead_amount ELSE 0 END), 0) AS actual_cost
            FROM production_cost_layers
            WHERE production_order_id=? AND layer_type IN ('material', 'labor', 'overhead')
            """,
            (order_id,),
        ).fetchone() or {})
        actual_cost = max(_safe_float(costing_row.get("actual_cost")), round(operation_cost, 2))
        all_done = all((row.get("status") or "") == "done" for row in operations)
        any_work = any((row.get("status") or "") in {"in_progress", "otk", "done"} for row in operations)
        progress = 100 if all_done else round((completed_qty / max(planned_qty, 0.0001)) * 100, 1) if planned_qty > 0 else 0
        stage = "done" if all_done else ("in_work" if any_work else "queue")
        finished_at = datetime.now().strftime("%d.%m.%Y") if all_done else ""
        conn.execute(
            """
            UPDATE production_orders
            SET stage=?, progress=?, produced_qty=?, scrap_qty=?, labor_hours_fact=?, actual_cost=?,
                actual_finish=CASE WHEN ?!='' THEN ? ELSE actual_finish END, updated_at=?
            WHERE id=?
            """,
            (stage, progress, completed_qty, scrap_qty, actual_hours, actual_cost, finished_at, finished_at, now_ts(), order_id),
        )

    def _apply_terminal_production_event(conn, data: ProductionExecutionEventData, actor: dict) -> dict:
        c = conn.cursor()
        operation = _production_operation_row(conn, data.operation_id)
        job = {}
        if data.job_id:
            job = dict(c.execute("SELECT * FROM production_jobs WHERE id=?", (_safe_int(data.job_id),)).fetchone() or {})
        order_id = _safe_int(data.order_id) or _safe_int(operation.get("order_id")) or _safe_int(job.get("order_id"))
        if data.operation_id and not operation:
            return {"error": "operation_not_found"}
        if data.job_id and not job:
            return {"error": "job_not_found"}
        if not order_id:
            return {"error": "order_not_found"}
        now = now_ts()
        now_text = datetime.now().strftime("%d.%m.%Y %H:%M")
        event_type = (data.event_type or "start").strip().lower()
        qty = _safe_float(data.qty)
        scrap_qty = _safe_float(data.scrap_qty)
        if operation:
            planned_qty = _safe_float(operation.get("planned_qty"))
            completed_qty = _safe_float(operation.get("completed_qty"))
            current_scrap = _safe_float(operation.get("scrap_qty"))
            actual_hours = _safe_float(data.payload.get("actual_hours")) if isinstance(data.payload, dict) else 0
            if event_type in {"start", "resume"}:
                c.execute("UPDATE production_operations SET status='in_progress', started_at=CASE WHEN started_at='' THEN ? ELSE started_at END, updated_at=? WHERE id=?", (now_text, now, _safe_int(data.operation_id)))
            elif event_type in {"complete", "finish"}:
                target_qty = qty or planned_qty or completed_qty
                c.execute(
                    """
                    UPDATE production_operations
                    SET status='done', completed_qty=?, scrap_qty=?, actual_hours=CASE WHEN ?>0 THEN ? ELSE actual_hours END,
                        finished_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (round(target_qty, 3), round(current_scrap + scrap_qty, 3), actual_hours, actual_hours, now_text, now, _safe_int(data.operation_id)),
                )
                complete_operation_costing(conn, _safe_int(data.operation_id), actor.get("email", ""))
            elif event_type == "scrap":
                c.execute("UPDATE production_operations SET scrap_qty=?, status=CASE WHEN status='planned' THEN 'in_progress' ELSE status END, updated_at=? WHERE id=?", (round(current_scrap + scrap_qty, 3), now, _safe_int(data.operation_id)))
            elif event_type in {"quality_hold", "otk"}:
                c.execute("UPDATE production_operations SET status='otk', updated_at=? WHERE id=?", (now, _safe_int(data.operation_id)))
        if job:
            if event_type in {"start", "resume"}:
                c.execute("UPDATE production_jobs SET status='in_progress', started_at=CASE WHEN started_at='' THEN ? ELSE started_at END, updated_at=? WHERE id=?", (now_text, now, _safe_int(data.job_id)))
            elif event_type in {"complete", "finish"}:
                c.execute("UPDATE production_jobs SET status='done', completed_qty=CASE WHEN ?>0 THEN ? ELSE planned_qty END, finished_at=?, updated_at=? WHERE id=?", (qty, qty, now_text, now, _safe_int(data.job_id)))
        event_id = _insert(conn, "production_execution_events", {
            "order_id": order_id,
            "operation_id": _safe_int(data.operation_id),
            "job_id": _safe_int(data.job_id),
            "event_type": event_type,
            "qty": qty,
            "scrap_qty": scrap_qty,
            "work_center": data.work_center or operation.get("work_center") or job.get("work_center") or "",
            "executor_name": data.executor_name or actor.get("name", ""),
            "payload_json": json.dumps(data.payload or {}, ensure_ascii=False),
            "created_by": actor.get("email", ""),
            "created_at": now,
        })
        _sync_terminal_production_rollup(conn, order_id)
        return {"status": "success", "id": event_id, "order_id": order_id, "event_type": event_type}

    @router.get("/api/sales/extended_summary")
    def get_sales_extended_summary(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        sales_rows = _filter_scope_rows_for_actor(actor, enhanced_load_sales_rows())
        quote_rows = _rows(
            """
            SELECT q.*, COALESCE(cl.name, '') AS client_name, COALESCE(p.name, '') AS project_name
            FROM sales_quotes q
            LEFT JOIN clients cl ON cl.id = q.client_id
            LEFT JOIN projects p ON p.id = q.project_id
            ORDER BY q.created_at DESC, q.id DESC
            """
        )
        return_rows = _rows(
            """
            SELECT r.*, COALESCE(cl.name, '') AS client_name, COALESCE(sd.doc_number, '') AS sales_doc_number
            FROM customer_returns r
            LEFT JOIN clients cl ON cl.id = r.client_id
            LEFT JOIN sales_documents_extended sd ON sd.id = r.sales_document_id
            ORDER BY r.created_at DESC, r.id DESC
            """
        )
        plan_rows = _rows("SELECT * FROM sales_plans ORDER BY period_key DESC, id DESC")
        price_rows = _rows("SELECT * FROM price_lists ORDER BY updated_at DESC, id DESC")
        order_rows = _sales_customer_order_rows()
        shipment_rows = _sales_shipment_rows()
        payment_schedule_rows = _sales_payment_schedule_rows()
        margin_rows = _sales_deal_margin_rows()
        terms_rows = _rows(
            """
            SELECT t.*, COALESCE(c.name, '') AS client_name, COALESCE(p.name, '') AS price_list_name
            FROM client_sales_terms t
            LEFT JOIN clients c ON c.id=t.client_id
            LEFT JOIN price_lists p ON p.id=t.price_list_id
            ORDER BY t.updated_at DESC, t.id DESC
            """
        )
        funnel = {"draft": {"count": 0, "amount": 0}, "proposal": {"count": 0, "amount": 0}, "negotiation": {"count": 0, "amount": 0}, "won": {"count": 0, "amount": 0}, "lost": {"count": 0, "amount": 0}}
        for row in quote_rows:
            stage = (row.get("stage") or "draft").strip()
            bucket = funnel.setdefault(stage, {"count": 0, "amount": 0})
            bucket["count"] += 1
            bucket["amount"] = round(_safe_float(bucket["amount"]) + _safe_float(row.get("amount")), 2)
        overdue = [row for row in sales_rows if _safe_int(row.get("is_overdue"))]
        overdue_schedules = [row for row in payment_schedule_rows if _safe_int(row.get("overdue_days")) > 0 and (row.get("status") or "") != "paid"]
        shipment_risk = [row for row in sales_rows if _safe_int(row.get("shipment_late_days")) > 0]
        order_shipment_risk = [row for row in order_rows if (row.get("requested_ship_date") or "") and (row.get("status") or "") not in {"shipped", "closed", "cancelled"} and _days_between(row.get("requested_ship_date")) > 0]
        high_discount_docs = [row for row in sales_rows if _safe_float(row.get("discount_percent")) >= 10 or _safe_float(row.get("discount_amount")) > 0]
        plan_total = round(sum(_safe_float(item.get("target_amount")) for item in plan_rows), 2)
        fact_total = round(sum(_safe_float(item.get("amount")) for item in sales_rows if item.get("status") in {"issued", "signed", "closed"}), 2)
        for row in plan_rows:
            actual_amount = round(sum(_safe_float(item.get("amount")) for item in sales_rows if ((row.get("project_id") and _safe_int(item.get("project_id")) == _safe_int(row.get("project_id"))) or (row.get("client_id") and _safe_int(item.get("client_id")) == _safe_int(row.get("client_id")))) and item.get("status") in {"issued", "signed", "closed"}), 2)
            row["actual_amount"] = actual_amount
            row["plan_fact_delta"] = round(actual_amount - _safe_float(row.get("target_amount")), 2)
        client_health = _score_sales_clients(sales_rows, quote_rows, terms_rows, return_rows)
        price_groups = defaultdict(list)
        for row in price_rows:
            price_groups[(row.get("name") or "").strip().lower()].append(row)
        price_lifecycle = []
        for rows in price_groups.values():
            ordered = sorted(rows, key=lambda item: (_safe_int(item.get("updated_at")), _safe_int(item.get("id"))))
            total = len(ordered)
            for version_no, row in enumerate(ordered, start=1):
                lifecycle = _lifecycle_state(row.get("valid_from"), row.get("valid_to"), row.get("status"))
                price_lifecycle.append({
                    "id": row.get("id"),
                    "name": row.get("name") or "Прайс",
                    "item_article": row.get("item_article") or "",
                    "status": row.get("status") or "active",
                    "lifecycle_state": lifecycle,
                    "version_no": version_no,
                    "version_total": total,
                    "base_price": _safe_float(row.get("base_price")),
                    "currency": row.get("currency") or "RUB",
                    "valid_from": row.get("valid_from") or "",
                    "valid_to": row.get("valid_to") or "",
                })
        plan_fact_rows = sorted(plan_rows, key=lambda item: abs(_safe_float(item.get("actual_amount")) - _safe_float(item.get("target_amount"))), reverse=True)
        return {
            "metrics": {
                "quotes_total": len(quote_rows),
                "quotes_active": len([row for row in quote_rows if (row.get("stage") or "") in {"proposal", "negotiation"}]),
                "returns_total": len(return_rows),
                "overdue_receivables": round(sum(_safe_float(item.get("amount")) for item in overdue), 2),
                "overdue_docs": len(overdue),
                "shipment_risk_docs": len(shipment_risk),
                "high_discount_docs": len(high_discount_docs),
                "sales_plan_amount": plan_total,
                "sales_fact_amount": fact_total,
                "sales_plan_delta": round(fact_total - plan_total, 2),
                "price_lists": len([row for row in price_lifecycle if row.get("lifecycle_state") == "active"]),
                "price_list_versions": len([rows for rows in price_groups.values() if len(rows) > 1]),
                "client_terms": len([row for row in terms_rows if (row.get("status") or "active") == "active"]),
                "customers_scored": len(client_health),
                "customer_risk_clients": len([row for row in client_health if row.get("health_bucket") != "stable"]),
                "customer_orders_open": len([row for row in order_rows if (row.get("status") or "") not in {"closed", "cancelled"}]),
                "customer_orders_amount": round(sum(_safe_float(row.get("amount")) for row in order_rows if (row.get("status") or "") not in {"cancelled"}), 2),
                "shipments_pending": len([row for row in shipment_rows if (row.get("status") or "") not in {"shipped", "cancelled"}]),
                "payment_schedule_open": len([row for row in payment_schedule_rows if (row.get("status") or "") not in {"paid", "closed"}]),
                "payment_schedule_overdue": len(overdue_schedules),
                "scheduled_receivables": round(sum(max(_safe_float(row.get("amount")) - _safe_float(row.get("paid_amount")), 0) for row in payment_schedule_rows if (row.get("status") or "") != "paid"), 2),
                "deal_margin_amount": round(sum(_safe_float(row.get("margin_amount")) for row in margin_rows), 2),
                "deal_margin_percent": round((sum(_safe_float(row.get("margin_amount")) for row in margin_rows) / max(sum(_safe_float(row.get("revenue_amount")) for row in margin_rows), 0.0001)) * 100, 2) if margin_rows else 0,
            },
            "funnel": funnel,
            "pipeline": [{"stage": stage, "label": _label_stage(stage), "count": data.get("count", 0), "amount": round(_safe_float(data.get("amount")), 2)} for stage, data in funnel.items()],
            "client_health": client_health[:8],
            "price_lifecycle": sorted(price_lifecycle, key=lambda item: (item.get("name") or "", -_safe_int(item.get("version_no"))))[:8],
            "plan_fact": [{
                **row,
                "delta": round(_safe_float(row.get("actual_amount")) - _safe_float(row.get("target_amount")), 2),
            } for row in plan_fact_rows[:8]],
            "overdue": overdue[:10],
            "shipment_risk": (shipment_risk + order_shipment_risk)[:10],
            "customer_orders": order_rows[:12],
            "shipments": shipment_rows[:12],
            "payment_schedules": payment_schedule_rows[:12],
            "deal_margins": margin_rows[:12],
        }

    @router.get("/api/supply/extended_summary")
    def get_supply_extended_summary(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        purchase_rows = _filter_scope_rows_for_actor(actor, enhanced_load_purchase_rows())
        plan_rows = _rows("SELECT * FROM purchase_plans ORDER BY period_key DESC, id DESC")
        discrepancy_rows = _rows(
            """
            SELECT a.*, COALESCE(sr.supplier_name, '') AS supplier_name
            FROM supplier_discrepancy_acts a
            LEFT JOIN supplier_registry sr ON sr.id = a.supplier_id
            ORDER BY a.created_at DESC, a.id DESC
            """
        )
        return_rows = _rows(
            """
            SELECT r.*, COALESCE(sr.supplier_name, '') AS supplier_name
            FROM supplier_returns r
            LEFT JOIN supplier_registry sr ON sr.id = r.supplier_id
            ORDER BY r.created_at DESC, r.id DESC
            """
        )
        schedule_rows = _rows("SELECT * FROM supplier_delivery_schedules ORDER BY scheduled_date DESC, id DESC")
        supplier_rows = _rows("SELECT * FROM supplier_registry ORDER BY is_active DESC, updated_at DESC, id DESC")
        procurement_requests = _procurement_request_rows(actor)
        allowed_request_ids = {_safe_int(row.get("id")) for row in procurement_requests}
        procurement_tenders = [row for row in _procurement_tender_rows() if _safe_int(row.get("request_id")) in allowed_request_ids]
        procurement_bids = [row for row in _procurement_bid_rows() if any(_safe_int(tender.get("id")) == _safe_int(row.get("tender_id")) for tender in procurement_tenders)]
        allowed_purchase_ids = {_safe_int(row.get("id")) for row in purchase_rows}
        purchase_receipts = [row for row in _purchase_receipt_rows() if _safe_int(row.get("purchase_id")) in allowed_purchase_ids]
        purchase_documents = [row for row in _purchase_document_rows() if _safe_int(row.get("purchase_id")) in allowed_purchase_ids]
        late_rows = [row for row in purchase_rows if _safe_int(row.get("delivery_delay_days")) > 0]
        under_rows = [row for row in purchase_rows if _safe_float(row.get("underdelivery_qty")) > 0.0001]
        schedule_alerts = []
        for row in schedule_rows:
            planned = _safe_float(row.get("planned_qty"))
            delivered = _safe_float(row.get("delivered_qty"))
            remaining = round(max(planned - delivered, 0), 3)
            late_days = max(_days_between(row.get("scheduled_date")), 0) if remaining > 0 and (row.get("status") or "") not in {"delivered", "closed"} else 0
            if late_days or remaining > 0:
                schedule_alerts.append({**row, "remaining_qty": remaining, "late_days": late_days})
        supplier_health = _score_suppliers(purchase_rows, supplier_rows, schedule_alerts, return_rows, discrepancy_rows)
        plan_fact_rows = []
        for row in plan_rows:
            fact_amount = round(sum(_safe_float(item.get("total_amount")) for item in purchase_rows if (not row.get("project_id") or _safe_int(item.get("project_id")) == _safe_int(row.get("project_id"))) and (not row.get("supplier_id") or _safe_int(item.get("supplier_id")) == _safe_int(row.get("supplier_id"))) and (item.get("item_article") or "") == (row.get("item_article") or "")), 2)
            plan_fact_rows.append({
                **row,
                "fact_amount": fact_amount,
                "delta_amount": round(fact_amount - _safe_float(row.get("target_amount")), 2),
            })
        plan_total = round(sum(_safe_float(item.get("target_amount")) for item in plan_rows), 2)
        fact_total = round(sum(_safe_float(item.get("total_amount")) for item in purchase_rows), 2)
        procurement_sla = _procurement_sla_rows(procurement_requests, procurement_tenders, purchase_rows, purchase_receipts, purchase_documents)
        return {
            "metrics": {
                "purchase_plan_amount": plan_total,
                "purchase_fact_amount": fact_total,
                "purchase_plan_delta": round(fact_total - plan_total, 2),
                "procurement_requests_open": len([row for row in procurement_requests if row.get("status") not in {"ordered", "received", "closed", "cancelled"}]),
                "procurement_tenders_open": len([row for row in procurement_tenders if row.get("status") not in {"awarded", "closed", "cancelled"}]),
                "procurement_sla_risks": len([row for row in procurement_sla if row.get("risk_level") == "risk"]),
                "purchase_receipts": len(purchase_receipts),
                "purchase_documents": len(purchase_documents),
                "late_deliveries": len(late_rows),
                "overdue_schedules": len([row for row in schedule_alerts if _safe_int(row.get("late_days")) > 0]),
                "underdelivery_cases": len(under_rows),
                "underdelivery_qty": round(sum(_safe_float(item.get("underdelivery_qty")) for item in under_rows), 3),
                "price_variance_total": round(sum(abs(_safe_float(item.get("price_variance"))) for item in purchase_rows), 2),
                "supplier_returns": len(return_rows),
                "supplier_discrepancies": len(discrepancy_rows),
                "suppliers_total": len(_rows("SELECT id FROM supplier_registry WHERE is_active=1")),
                "supplier_risk_total": len([row for row in supplier_health if row.get("health_bucket") != "stable"]),
            },
            "late_purchases": late_rows[:10],
            "schedule_alerts": sorted(schedule_alerts, key=lambda item: (_safe_int(item.get("late_days")) * -1, -_safe_float(item.get("remaining_qty"))))[:10],
            "supplier_health": supplier_health[:8],
            "plan_fact": sorted(plan_fact_rows, key=lambda item: abs(_safe_float(item.get("delta_amount"))), reverse=True)[:8],
            "procurement_requests": procurement_requests[:10],
            "procurement_tenders": procurement_tenders[:10],
            "procurement_bids": procurement_bids[:10],
            "procurement_sla": procurement_sla[:10],
            "purchase_receipts": purchase_receipts[:10],
            "purchase_documents": purchase_documents[:10],
            "discrepancies": discrepancy_rows[:10],
            "returns": return_rows[:10],
        }

    @router.get("/api/stock/extended_summary")
    def get_stock_extended_summary(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        acts = _rows("SELECT * FROM inventory_acts ORDER BY created_at DESC, id DESC")
        quality = _rows("SELECT * FROM warehouse_quality_reports ORDER BY created_at DESC, id DESC")
        regrading = _rows("SELECT * FROM inventory_regrading_docs ORDER BY created_at DESC, id DESC")
        balances = _load_inventory_balances()
        discrepancies = _warehouse_discrepancy_rows(120)
        journal = _stock_journal_rows(60)
        policy = _policy_settings()
        wms_cells = _wms_cell_rows()
        wms_putaway = _wms_putaway_rows()
        wms_pick_waves = _wms_pick_wave_rows()
        wms_pick_tasks = _wms_pick_task_rows()
        wms_cycle_counts = _wms_cycle_count_rows()
        wms_cycle_lines = _wms_cycle_count_line_rows()
        wms_lot_positions = _wms_lot_position_rows(120)
        negative_positions = [row for row in balances if _safe_float(row.get("qty")) < 0]
        zero_cost_positions = _rows("SELECT article, name, stock, price, default_warehouse FROM nomenclature WHERE COALESCE(stock, 0) > 0.0001 AND COALESCE(price, 0) <= 0 ORDER BY stock DESC, name ASC LIMIT 20")
        return {
            "metrics": {
                "inventory_acts": len(acts),
                "regrading_docs": len(regrading),
                "quality_holds": len([row for row in quality if (row.get("status") or "") not in {"closed", "released"}]),
                "negative_balance_positions": len(negative_positions),
                "posted_docs": len([row for row in _load_inventory_document_rows(40) if row.get("status") == "posted"]),
                "journal_entries": len(journal),
                "discrepancy_cases": len(discrepancies),
                "zero_cost_positions": len(zero_cost_positions),
                "strict_negative_control": 0 if _safe_int(policy.get("allow_negative_stock")) else 1,
                "wms_cells": len(wms_cells),
                "wms_putaway_open": len([row for row in wms_putaway if (row.get("status") or "") not in {"done", "cancelled"}]),
                "wms_pick_tasks_open": len([row for row in wms_pick_tasks if (row.get("status") or "") not in {"done", "cancelled"}]),
                "wms_cycle_counts_open": len([row for row in wms_cycle_counts if (row.get("status") or "") != "closed"]),
                "wms_lot_positions": len([row for row in wms_lot_positions if row.get("batch_code")]),
                "wms_serial_positions": len([row for row in wms_lot_positions if row.get("serial_no")]),
                "wms_overfilled_cells": len([row for row in wms_cells if row.get("risk_level") == "risk"]),
            },
            "policy": policy,
            "acts": acts[:10],
            "quality": quality[:10],
            "regrading": regrading[:10],
            "journal": journal[:20],
            "negative_positions": negative_positions[:10],
            "zero_cost_positions": zero_cost_positions[:10],
            "discrepancy_reasons": _aggregate_reason_rows(discrepancies, "reason", "adjustment_qty")[:8],
            "quality_statuses": _aggregate_quality_rows(quality)[:8],
            "cost_alerts": [
                {"title": "Метод себестоимости", "value": (policy.get("cost_method") or "fifo").upper(), "state": "warning" if (policy.get("cost_method") or "fifo").lower() not in {"fifo", "average"} else "stable"},
                {"title": "Отрицательные остатки", "value": "разрешены" if _safe_int(policy.get("allow_negative_stock")) else "запрещены", "state": "warning" if _safe_int(policy.get("allow_negative_stock")) else "stable"},
                {"title": "Позиции без цены", "value": len(zero_cost_positions), "state": "warning" if zero_cost_positions else "stable"},
            ],
            "wms_cells": wms_cells[:50],
            "wms_putaway_tasks": wms_putaway[:40],
            "wms_pick_waves": wms_pick_waves[:40],
            "wms_pick_tasks": wms_pick_tasks[:60],
            "wms_cycle_counts": wms_cycle_counts[:40],
            "wms_cycle_count_lines": wms_cycle_lines[:80],
            "wms_lot_positions": wms_lot_positions[:80],
        }

    @router.get("/api/stock/journal")
    def get_stock_journal(request: Request, limit: int = 120):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _stock_journal_rows(limit)

    _simple_create_route("/api/sales/quotes", "sales_quotes", SalesQuoteData, "sales", lambda data, actor: {
        "project_id": data.project_id, "client_id": data.client_id, "contract_id": data.contract_id, "object_id": data.object_id, "title": data.title, "quote_number": data.quote_number or _next_code("KP"), "stage": data.stage,
        "amount": data.amount, "currency": data.currency, "valid_until": data.valid_until, "responsible": data.responsible, "probability": data.probability, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts(),
    })
    _simple_create_route("/api/sales/plans", "sales_plans", SalesPlanData, "sales", lambda data, actor: {
        "period_key": data.period_key, "manager_name": data.manager_name, "client_id": data.client_id, "project_id": data.project_id, "target_amount": data.target_amount, "target_docs": data.target_docs, "actual_amount": data.actual_amount,
        "status": data.status, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts(),
    })
    _simple_create_route("/api/sales/price_lists", "price_lists", PriceListData, "sales", lambda data, actor: {
        "name": data.name, "currency": data.currency, "valid_from": data.valid_from, "valid_to": data.valid_to, "item_article": data.item_article, "item_name": data.item_name, "unit": data.unit, "base_price": data.base_price, "min_price": data.min_price,
        "status": data.status, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts(),
    })
    _simple_create_route("/api/sales/client_terms", "client_sales_terms", ClientSalesTermData, "sales", lambda data, actor: {
        "client_id": data.client_id, "price_list_id": data.price_list_id, "discount_percent": data.discount_percent, "discount_amount": data.discount_amount, "payment_delay_days": data.payment_delay_days, "credit_limit": data.credit_limit,
        "shipment_priority": data.shipment_priority, "status": data.status, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts(),
    })

    @router.get("/api/sales/customer_orders")
    def get_sales_customer_orders(request: Request, client_id: int = 0, project_id: int = 0):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        rows = _filter_scope_rows_for_actor(actor, _sales_customer_order_rows())
        if client_id:
            rows = [row for row in rows if _safe_int(row.get("client_id")) == _safe_int(client_id)]
        if project_id:
            rows = [row for row in rows if _safe_int(row.get("project_id")) == _safe_int(project_id)]
        return rows

    @router.post("/api/sales/customer_orders")
    def create_sales_customer_order(data: SalesCustomerOrderData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "create"):
            return {"error": "forbidden"}
        now = now_ts()
        conn = get_connection(row_factory=True)
        quote = {}
        if _safe_int(data.quote_id):
            row = conn.execute("SELECT * FROM sales_quotes WHERE id=?", (_safe_int(data.quote_id),)).fetchone()
            quote = dict(row) if row else {}
        context = _resolve_master_context(conn, data.project_id or _safe_int(quote.get("project_id")), data.client_id or _safe_int(quote.get("client_id")), data.contract_id or _safe_int(quote.get("contract_id")), data.object_id or _safe_int(quote.get("object_id")))
        order_amount = _safe_float(data.amount) or round(_safe_float(data.qty) * _safe_float(data.unit_price), 2) or _safe_float(quote.get("amount"))
        order_id = _insert(conn, "sales_customer_orders", {
            "quote_id": _safe_int(data.quote_id),
            "sales_document_id": _safe_int(data.sales_document_id),
            "project_id": context["project_id"],
            "client_id": context["client_id"],
            "contract_id": context["contract_id"],
            "object_id": context["object_id"],
            "legal_entity_id": _safe_int(data.legal_entity_id),
            "business_unit_id": _safe_int(data.business_unit_id),
            "order_number": data.order_number or _next_code("SO"),
            "article": _normalize_spaces(data.article),
            "item_name": data.item_name or data.article or quote.get("title") or "Заказ клиента",
            "qty": data.qty,
            "unit": data.unit or "шт",
            "unit_price": data.unit_price,
            "amount": order_amount,
            "currency": data.currency or quote.get("currency") or "RUB",
            "status": data.status or "confirmed",
            "requested_ship_date": data.requested_ship_date,
            "payment_terms": data.payment_terms,
            "reserve_status": "none",
            "reservation_id": 0,
            "comment": data.comment or quote.get("comment") or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        if quote:
            conn.execute("UPDATE sales_quotes SET stage='won', updated_at=? WHERE id=?", (now, _safe_int(data.quote_id)))
        fulfillment = build_fulfillment_plan_for_customer_order(conn, order_id, actor.get("email", ""), strategy="purchase", auto_create=True)
        conn.commit()
        conn.close()
        return {"status": "success", "id": order_id, "fulfillment": fulfillment}

    @router.get("/api/fulfillment/plans")
    def get_fulfillment_plans(request: Request, status: str = "", demand_type: str = "", demand_id: int = 0):
        actor = require_approved_user(request)
        if not actor or not (has_permission(actor, "sales", "read") or has_permission(actor, "supply", "read")):
            return {"error": "forbidden"}
        rows = _filter_scope_rows_for_actor(actor, _rows("SELECT * FROM fulfillment_plan ORDER BY updated_at DESC, id DESC"))
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if demand_type:
            rows = [row for row in rows if row.get("demand_type") == demand_type]
        if demand_id:
            rows = [row for row in rows if _safe_int(row.get("demand_id")) == _safe_int(demand_id)]
        return rows

    @router.get("/api/fulfillment/supply_links")
    def get_supply_demand_links(request: Request, demand_type: str = "", demand_id: int = 0, supply_type: str = "", supply_id: int = 0):
        actor = require_approved_user(request)
        if not actor or not (has_permission(actor, "sales", "read") or has_permission(actor, "supply", "read")):
            return {"error": "forbidden"}
        rows = _rows("SELECT * FROM supply_demand_links ORDER BY updated_at DESC, id DESC")
        if demand_type:
            rows = [row for row in rows if row.get("demand_type") == demand_type]
        if demand_id:
            rows = [row for row in rows if _safe_int(row.get("demand_id")) == _safe_int(demand_id)]
        if supply_type:
            rows = [row for row in rows if row.get("supply_type") == supply_type]
        if supply_id:
            rows = [row for row in rows if _safe_int(row.get("supply_id")) == _safe_int(supply_id)]
        return rows

    @router.post("/api/sales/customer_orders/{order_id}/fulfillment_plan")
    def rebuild_sales_customer_order_fulfillment(order_id: int, request: Request, strategy: str = "purchase", auto_create: bool = True):
        actor = require_approved_user(request)
        if not actor or not (has_permission(actor, "sales", "update") or has_permission(actor, "supply", "create")):
            return {"error": "forbidden"}
        if strategy not in {"purchase", "production"}:
            return _api_error(400, "invalid_strategy")
        conn = get_connection(row_factory=True)
        result = build_fulfillment_plan_for_customer_order(conn, order_id, actor.get("email", ""), strategy=strategy, auto_create=auto_create)
        if result.get("error"):
            conn.rollback()
            conn.close()
            return _api_error(404, result.get("error"))
        conn.commit()
        conn.close()
        return result

    @router.post("/api/sales/customer_orders/{order_id}/reserve")
    def reserve_sales_customer_order(order_id: int, data: SalesCustomerOrderReserveData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute("SELECT * FROM sales_customer_orders WHERE id=?", (_safe_int(order_id),))
        order = c.fetchone()
        if not order:
            conn.close()
            return _api_error(404, "not_found")
        article = _normalize_spaces(order.get("article") or "")
        qty = _safe_float(data.qty) or _safe_float(order.get("qty"))
        warehouse = _normalize_spaces(data.warehouse)
        bin_code = _normalize_spaces(data.bin_code)
        batch_code = _normalize_spaces(data.batch_code)
        serial_no = _normalize_spaces(data.serial_no)
        source = None
        if article and not (warehouse or bin_code or batch_code or serial_no):
            source = policy_pick_inventory_source(c, article, qty)
            if source:
                warehouse = source.get("warehouse") or ""
                bin_code = source.get("bin_code") or ""
                batch_code = source.get("batch_code") or ""
                serial_no = source.get("serial_no") or ""
        available_free_qty = 0.0
        if article and warehouse:
            _bootstrap_inventory_lots_for_article(c, article)
            c.execute(
                "SELECT COALESCE(SUM(qty), 0) FROM inventory_lots WHERE article=? AND warehouse=? AND bin_code=? AND batch_code=? AND serial_no=?",
                (article, warehouse, bin_code or "A-01", batch_code, serial_no),
            )
            available_free_qty = round(_safe_float(c.fetchone()[0]) - _available_reserved_qty(c, article, warehouse, bin_code or "A-01", batch_code, serial_no), 3)
        status = "reserved" if available_free_qty + 0.0001 >= qty else "shortage"
        reservation_id = _insert(conn, "stock_reservations", {
            "project_id": _safe_int(order.get("project_id")),
            "legal_entity_id": _safe_int(order.get("legal_entity_id")),
            "business_unit_id": _safe_int(order.get("business_unit_id")),
            "nomenclature_article": article,
            "nomenclature_name": order.get("item_name") or article,
            "qty": qty,
            "status": status,
            "comment": data.comment or f"Резерв по заказу {order.get('order_number') or order_id}",
            "created_by": actor.get("email", ""),
            "created_at": now_ts(),
            "warehouse": warehouse,
            "bin_code": bin_code or "A-01",
            "batch_code": batch_code,
            "serial_no": serial_no,
            "fulfilled_qty": 0,
            "released_at": 0,
            "released_by": "",
        })
        c.execute("UPDATE sales_customer_orders SET reserve_status=?, reservation_id=?, status=CASE WHEN status='draft' THEN 'confirmed' ELSE status END, updated_at=? WHERE id=?", (status, reservation_id, now_ts(), _safe_int(order_id)))
        conn.commit()
        conn.close()
        return {"status": "success", "id": reservation_id, "reserve_status": status, "available_free_qty": available_free_qty}

    @router.post("/api/sales/customer_orders/{order_id}/create_document")
    def create_sales_document_from_order(order_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "create"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute("SELECT * FROM sales_customer_orders WHERE id=?", (_safe_int(order_id),))
        order = c.fetchone()
        if not order:
            conn.close()
            return _api_error(404, "not_found")
        if _safe_int(order.get("sales_document_id")):
            conn.close()
            return {"status": "success", "id": _safe_int(order.get("sales_document_id")), "already_created": True}
        document_id = _create_sales_document_for_order(conn, dict(order), actor)
        c.execute("UPDATE sales_customer_orders SET sales_document_id=?, updated_at=? WHERE id=?", (document_id, now_ts(), _safe_int(order_id)))
        refresh_fulfillment_for_customer_order(conn, order_id, actor.get("email", ""))
        conn.commit()
        conn.close()
        return {"status": "success", "id": document_id}

    @router.delete("/api/sales/customer_orders/{row_id}")
    def delete_sales_customer_order(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "delete"):
            return {"error": "forbidden"}
        _delete("sales_customer_orders", row_id)
        return {"status": "success"}

    @router.get("/api/sales/shipments")
    def get_sales_shipments(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        return _sales_shipment_rows()

    @router.post("/api/sales/shipments")
    def create_sales_shipment(data: SalesShipmentData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "create"):
            return {"error": "forbidden"}
        now = now_ts()
        conn = get_connection(row_factory=True)
        order = {}
        if _safe_int(data.customer_order_id):
            row = conn.execute("SELECT * FROM sales_customer_orders WHERE id=?", (_safe_int(data.customer_order_id),)).fetchone()
            order = dict(row) if row else {}
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        shipment_id = _insert(conn, "sales_shipments", {
            "customer_order_id": _safe_int(data.customer_order_id),
            "sales_document_id": _safe_int(data.sales_document_id) or _safe_int(order.get("sales_document_id")),
            "reservation_id": _safe_int(data.reservation_id) or _safe_int(order.get("reservation_id")),
            "shipment_number": data.shipment_number or _next_code("SHP"),
            "article": _normalize_spaces(data.article or order.get("article") or ""),
            "item_name": data.item_name or order.get("item_name") or data.article,
            "qty": data.qty or _safe_float(order.get("qty")),
            "warehouse": warehouse,
            "bin_code": bin_code,
            "batch_code": data.batch_code or "",
            "serial_no": data.serial_no or "",
            "planned_ship_date": data.planned_ship_date or order.get("requested_ship_date") or "",
            "shipped_at": data.shipped_at or "",
            "status": data.status or "planned",
            "carrier": data.carrier or "",
            "tracking_no": data.tracking_no or "",
            "comment": data.comment or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.commit()
        conn.close()
        return {"status": "success", "id": shipment_id}

    @router.post("/api/sales/shipments/{shipment_id}/ship")
    def ship_sales_shipment(shipment_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not (has_permission(actor, "sales", "update") or has_permission(actor, "supply", "update")):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute("SELECT * FROM sales_shipments WHERE id=?", (_safe_int(shipment_id),))
        shipment = c.fetchone()
        if not shipment:
            conn.close()
            return _api_error(404, "not_found")
        if shipment.get("status") == "shipped":
            conn.close()
            return {"status": "success", "already_shipped": True}
        article = _normalize_spaces(shipment.get("article") or "")
        qty = _safe_float(shipment.get("qty"))
        warehouse, bin_code = _normalize_stock_location(shipment.get("warehouse"), shipment.get("bin_code"))
        allocations, missing = policy_consume_inventory_lots(c, article, qty, warehouse, bin_code, shipment.get("batch_code") or "", shipment.get("serial_no") or "")
        if missing > 0 or not allocations:
            conn.rollback()
            conn.close()
            return _api_error(409, "insufficient_stock")
        _upsert_inventory_balance(c, article, warehouse, bin_code, -qty)
        for allocation in allocations:
            _record_stock_movement(c, article, shipment.get("item_name") or article, allocation.get("qty", 0), "remove", warehouse, bin_code, "", "", allocation.get("batch_code", ""), allocation.get("serial_no", ""), actor.get("email", ""), shipment.get("comment") or "Отгрузка клиенту", "sales_shipment", _safe_int(shipment.get("reservation_id")), _safe_int(shipment_id), "sales_shipment")
        shipped_at = datetime.now().strftime("%d.%m.%Y")
        reservation_id = _safe_int(shipment.get("reservation_id"))
        if reservation_id:
            c.execute("SELECT qty, fulfilled_qty FROM stock_reservations WHERE id=?", (reservation_id,))
            reservation = c.fetchone()
            if reservation:
                reservation_qty = _safe_float(reservation.get("qty"))
                fulfilled_qty = min(round(_safe_float(reservation.get("fulfilled_qty")) + qty, 3), reservation_qty)
                reservation_status = "fulfilled" if fulfilled_qty + 0.0001 >= reservation_qty else "partial"
                c.execute("UPDATE stock_reservations SET fulfilled_qty=?, status=?, released_at=?, released_by=? WHERE id=?", (fulfilled_qty, reservation_status, now_ts() if reservation_status == "fulfilled" else 0, actor.get("email", "") if reservation_status == "fulfilled" else "", reservation_id))
        c.execute("UPDATE sales_shipments SET status='shipped', shipped_at=?, updated_at=? WHERE id=?", (shipped_at, now_ts(), _safe_int(shipment_id)))
        if _safe_int(shipment.get("customer_order_id")):
            c.execute("UPDATE sales_customer_orders SET status='shipped', updated_at=? WHERE id=?", (now_ts(), _safe_int(shipment.get("customer_order_id"))))
            refresh_fulfillment_for_customer_order(conn, _safe_int(shipment.get("customer_order_id")), actor.get("email", ""))
        if _safe_int(shipment.get("sales_document_id")):
            c.execute("UPDATE sales_documents_extended SET status='shipped', shipment_status='shipped', shipped_at=?, updated_at=? WHERE id=?", (shipped_at, now_ts(), _safe_int(shipment.get("sales_document_id"))))
        conn.commit()
        conn.close()
        return {"status": "success", "id": _safe_int(shipment_id)}

    @router.delete("/api/sales/shipments/{row_id}")
    def delete_sales_shipment(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "delete"):
            return {"error": "forbidden"}
        _delete("sales_shipments", row_id)
        return {"status": "success"}

    @router.get("/api/sales/payment_schedules")
    def get_sales_payment_schedules(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        return _sales_payment_schedule_rows()

    @router.post("/api/sales/payment_schedules")
    def create_sales_payment_schedule(data: SalesPaymentScheduleData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "create"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        order = {}
        if _safe_int(data.customer_order_id):
            c.execute("SELECT * FROM sales_customer_orders WHERE id=?", (_safe_int(data.customer_order_id),))
            row = c.fetchone()
            order = dict(row) if row else {}
        if not order and _safe_int(data.sales_document_id):
            c.execute("SELECT * FROM sales_documents_extended WHERE id=?", (_safe_int(data.sales_document_id),))
            doc = c.fetchone()
            order = dict(doc) if doc else {}
            order["order_number"] = order.get("customer_order_no") or order.get("doc_number") or data.sales_document_id
        if not order:
            conn.close()
            return _api_error(404, "not_found")
        payment_id = _safe_int(data.payment_id) or _create_sales_receivable_payment(conn, order, {"amount": data.amount, "currency": data.currency, "due_date": data.due_date, "paid_date": data.paid_date, "status": data.status, "comment": data.comment}, actor)
        now = now_ts()
        schedule_id = _insert(conn, "sales_payment_schedules", {
            "customer_order_id": _safe_int(data.customer_order_id),
            "sales_document_id": _safe_int(data.sales_document_id) or _safe_int(order.get("sales_document_id")) or _safe_int(order.get("id")),
            "payment_id": payment_id,
            "schedule_number": data.schedule_number or _next_code("PAY-SCH"),
            "due_date": data.due_date,
            "amount": data.amount,
            "currency": data.currency or order.get("currency") or "RUB",
            "status": data.status or "planned",
            "paid_amount": data.paid_amount,
            "paid_date": data.paid_date,
            "comment": data.comment,
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        c.execute("UPDATE finance_payments SET source_document_id=?, updated_at=? WHERE id=?", (schedule_id, now, payment_id))
        conn.commit()
        conn.close()
        return {"status": "success", "id": schedule_id, "payment_id": payment_id}

    @router.post("/api/sales/payment_schedules/{schedule_id}/mark_paid")
    def mark_sales_payment_schedule_paid(schedule_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute("SELECT * FROM sales_payment_schedules WHERE id=?", (_safe_int(schedule_id),))
        row = c.fetchone()
        if not row:
            conn.close()
            return _api_error(404, "not_found")
        paid_date = datetime.now().strftime("%d.%m.%Y")
        amount = _safe_float(row.get("amount"))
        c.execute("UPDATE sales_payment_schedules SET status='paid', paid_amount=?, paid_date=?, updated_at=? WHERE id=?", (amount, paid_date, now_ts(), _safe_int(schedule_id)))
        if _safe_int(row.get("payment_id")):
            c.execute("UPDATE finance_payments SET status='paid', paid_date=?, updated_at=? WHERE id=?", (paid_date, now_ts(), _safe_int(row.get("payment_id"))))
        conn.commit()
        conn.close()
        return {"status": "success", "id": _safe_int(schedule_id)}

    @router.delete("/api/sales/payment_schedules/{row_id}")
    def delete_sales_payment_schedule(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "delete"):
            return {"error": "forbidden"}
        _delete("sales_payment_schedules", row_id)
        return {"status": "success"}

    @router.get("/api/sales/deal_margins")
    def get_sales_deal_margins(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        return _sales_deal_margin_rows()

    @router.post("/api/sales/deal_margins/recalculate")
    def recalculate_sales_deal_margin(data: SalesDealMarginData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        order = None
        if _safe_int(data.customer_order_id):
            c.execute("SELECT * FROM sales_customer_orders WHERE id=?", (_safe_int(data.customer_order_id),))
            order = c.fetchone()
        if not order and _safe_int(data.sales_document_id):
            c.execute("SELECT * FROM sales_customer_orders WHERE sales_document_id=? ORDER BY id DESC LIMIT 1", (_safe_int(data.sales_document_id),))
            order = c.fetchone()
        if not order:
            conn.close()
            return _api_error(404, "not_found")
        margin_id = _calculate_sales_margin(conn, dict(order), data.direct_cost_amount, data.discount_amount, actor.get("email", ""))
        conn.commit()
        conn.close()
        return {"status": "success", "id": margin_id}

    _simple_create_route("/api/suppliers", "supplier_registry", SupplierRegistryData, "supply", lambda data, actor: {
        "supplier_name": data.supplier_name, "legal_entity_name": data.legal_entity_name, "inn": data.inn, "category": data.category, "rating": data.rating, "lead_time_days": data.lead_time_days, "reliability_percent": data.reliability_percent,
        "payment_terms": data.payment_terms, "comment": data.comment, "is_active": data.is_active, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts(),
    })
    _simple_create_route("/api/purchase/plans", "purchase_plans", PurchasePlanData, "supply", lambda data, actor: {
        "period_key": data.period_key, "supplier_id": data.supplier_id, "project_id": data.project_id, "item_article": data.item_article, "item_name": data.item_name, "qty_plan": data.qty_plan, "unit": data.unit, "target_unit_price": data.target_unit_price,
        "target_amount": data.target_amount, "status": data.status, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts(),
    })
    _simple_create_route("/api/stock/quality_reports", "warehouse_quality_reports", WarehouseQualityReportData, "nsi", lambda data, actor: {
        "warehouse": data.warehouse, "bin_code": data.bin_code, "article": data.article, "item_name": data.item_name, "qty": data.qty, "quality_status": data.quality_status, "defect_kind": data.defect_kind, "decision": data.decision, "status": data.status,
        "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts(),
    })

    @router.get("/api/sales/quotes")
    def get_sales_quotes(request: Request, project_id: int = 0, client_id: int = 0):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        rows = _rows(
            """
            SELECT q.*, COALESCE(cl.name, '') AS client_name, COALESCE(p.name, '') AS project_name
            FROM sales_quotes q
            LEFT JOIN clients cl ON cl.id = q.client_id
            LEFT JOIN projects p ON p.id = q.project_id
            ORDER BY q.created_at DESC, q.id DESC
            """
        )
        if project_id:
            rows = [row for row in rows if _safe_int(row.get("project_id")) == project_id]
        if client_id:
            rows = [row for row in rows if _safe_int(row.get("client_id")) == client_id]
        for row in rows:
            valid_until = _parse_date(row.get("valid_until"))
            days_left = (valid_until.date() - datetime.now().date()).days if valid_until else None
            row["days_to_valid_until"] = days_left
            if days_left is None:
                row["validity_state"] = "active"
            elif days_left < 0:
                row["validity_state"] = "expired"
            elif days_left <= 7:
                row["validity_state"] = "attention"
            else:
                row["validity_state"] = "active"
        return rows

    @router.get("/api/sales/plans")
    def get_sales_plans(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        rows = _rows("SELECT * FROM sales_plans ORDER BY period_key DESC, id DESC")
        sales = enhanced_load_sales_rows()
        for row in rows:
            row["actual_amount"] = round(sum(_safe_float(item.get("amount")) for item in sales if ((row.get("project_id") and _safe_int(item.get("project_id")) == _safe_int(row.get("project_id"))) or (row.get("client_id") and _safe_int(item.get("client_id")) == _safe_int(row.get("client_id")))) and item.get("status") in {"issued", "signed", "closed"}), 2)
            row["plan_fact_delta"] = round(_safe_float(row.get("actual_amount")) - _safe_float(row.get("target_amount")), 2)
        return rows

    @router.get("/api/sales/price_lists")
    def get_price_lists(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        rows = _rows("SELECT * FROM price_lists ORDER BY updated_at DESC, id DESC")
        groups = defaultdict(list)
        for row in rows:
            groups[(row.get("name") or "").strip().lower()].append(row)
        for grouped_rows in groups.values():
            ordered = sorted(grouped_rows, key=lambda item: (_safe_int(item.get("updated_at")), _safe_int(item.get("id"))))
            total = len(ordered)
            for version_no, row in enumerate(ordered, start=1):
                row["version_no"] = version_no
                row["version_total"] = total
                row["lifecycle_state"] = _lifecycle_state(row.get("valid_from"), row.get("valid_to"), row.get("status"))
        return rows

    @router.get("/api/sales/client_terms")
    def get_client_terms(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        return _rows("SELECT t.*, COALESCE(c.name, '') AS client_name, COALESCE(p.name, '') AS price_list_name FROM client_sales_terms t LEFT JOIN clients c ON c.id=t.client_id LEFT JOIN price_lists p ON p.id=t.price_list_id ORDER BY t.updated_at DESC, t.id DESC")

    @router.get("/api/suppliers")
    def get_suppliers(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        rows = _rows("SELECT * FROM supplier_registry ORDER BY is_active DESC, updated_at DESC, id DESC")
        purchase_rows = enhanced_load_purchase_rows()
        return_rows = _rows("SELECT * FROM supplier_returns ORDER BY created_at DESC, id DESC")
        discrepancy_rows = _rows("SELECT * FROM supplier_discrepancy_acts ORDER BY created_at DESC, id DESC")
        schedule_rows = _rows("SELECT * FROM supplier_delivery_schedules ORDER BY scheduled_date DESC, id DESC")
        health_rows = {item["supplier_id"]: item for item in _score_suppliers(purchase_rows, rows, schedule_rows, return_rows, discrepancy_rows)}
        for row in rows:
            health = health_rows.get(_safe_int(row.get("id")), {})
            row["orders_total"] = health.get("orders_total", 0)
            row["late_deliveries"] = health.get("late_deliveries", 0)
            row["underdelivery_cases"] = health.get("underdelivery_cases", 0)
            row["price_variance_total"] = health.get("price_variance_total", 0)
            row["returns_total"] = health.get("returns_total", 0)
            row["discrepancies_total"] = health.get("discrepancies_total", 0)
            row["health_score"] = health.get("health_score", round(_safe_float(row.get("reliability_percent")) or 0, 1))
            row["health_bucket"] = health.get("health_bucket", _health_bucket(row["health_score"]))
            row["health_reasons"] = health.get("reasons", [])
        return rows

    @router.get("/api/purchase/plans")
    def get_purchase_plans(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        rows = _rows("SELECT pp.*, COALESCE(sr.supplier_name, '') AS supplier_name, COALESCE(p.name, '') AS project_name FROM purchase_plans pp LEFT JOIN supplier_registry sr ON sr.id = pp.supplier_id LEFT JOIN projects p ON p.id = pp.project_id ORDER BY pp.period_key DESC, pp.id DESC")
        purchases = enhanced_load_purchase_rows()
        for row in rows:
            matched = [item for item in purchases if (not row.get("project_id") or _safe_int(item.get("project_id")) == _safe_int(row.get("project_id"))) and (not row.get("supplier_id") or _safe_int(item.get("supplier_id")) == _safe_int(row.get("supplier_id"))) and (item.get("item_article") or "") == (row.get("item_article") or "")]
            row["fact_amount"] = round(sum(_safe_float(item.get("total_amount")) for item in matched), 2)
            row["fact_qty"] = round(sum(_safe_float(item.get("qty")) for item in matched), 3)
            row["variance_amount"] = round(_safe_float(row.get("fact_amount")) - _safe_float(row.get("target_amount")), 2)
            row["variance_qty"] = round(_safe_float(row.get("fact_qty")) - _safe_float(row.get("qty_plan")), 3)
        return rows

    @router.get("/api/procurement/requests")
    def get_procurement_requests(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        return _procurement_request_rows(actor)

    @router.post("/api/procurement/requests")
    def create_procurement_request(data: ProcurementRequestData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        now = now_ts()
        conn = get_connection()
        context = _resolve_master_context(conn, data.project_id, data.client_id, data.contract_id, data.object_id)
        request_id = _insert(conn, "procurement_requests", {
            "project_id": context["project_id"],
            "client_id": context["client_id"],
            "contract_id": context["contract_id"],
            "object_id": context["object_id"],
            "legal_entity_id": _safe_int(data.legal_entity_id),
            "business_unit_id": _safe_int(data.business_unit_id),
            "request_number": data.request_number or _next_code("PR"),
            "title": data.title or data.item_name or "Заявка на закупку",
            "item_article": data.item_article,
            "item_name": data.item_name,
            "qty": data.qty,
            "unit": data.unit or "шт",
            "target_unit_price": data.target_unit_price,
            "required_date": data.required_date,
            "priority": data.priority or "normal",
            "requested_by": data.requested_by or actor.get("name", ""),
            "status": data.status or "draft",
            "linked_purchase_id": 0,
            "selected_supplier_id": 0,
            "approved_by": actor.get("name", "") if data.status in {"approved", "tender"} else "",
            "approved_at": now if data.status in {"approved", "tender"} else 0,
            "comment": data.comment,
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.commit()
        conn.close()
        return {"status": "success", "id": request_id}

    @router.get("/api/procurement/tenders")
    def get_procurement_tenders(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        allowed_request_ids = {_safe_int(row.get("id")) for row in _procurement_request_rows(actor)}
        return [row for row in _procurement_tender_rows() if _safe_int(row.get("request_id")) in allowed_request_ids]

    @router.post("/api/procurement/tenders")
    def create_procurement_tender(data: ProcurementTenderData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        request_row = next((row for row in _procurement_request_rows(actor) if _safe_int(row.get("id")) == _safe_int(data.request_id)), None)
        if not request_row:
            return _api_error(404, "request_not_found")
        now = now_ts()
        conn = get_connection()
        tender_id = _insert(conn, "procurement_tenders", {
            "request_id": _safe_int(data.request_id),
            "tender_number": data.tender_number or _next_code("RFQ"),
            "title": data.title or request_row.get("title") or "Тендер закупки",
            "due_date": data.due_date,
            "status": data.status or "draft",
            "criteria_json": json.dumps(data.criteria or {}, ensure_ascii=False),
            "selected_supplier_id": 0,
            "selected_bid_id": 0,
            "decision_comment": data.comment or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.execute("UPDATE procurement_requests SET status='tender', updated_at=? WHERE id=?", (now, _safe_int(data.request_id)))
        conn.commit()
        conn.close()
        return {"status": "success", "id": tender_id}

    @router.get("/api/procurement/tender_bids")
    def get_procurement_tender_bids(request: Request, tender_id: int = 0):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        allowed_tenders = {_safe_int(row.get("id")) for row in get_procurement_tenders(request)}
        rows = [row for row in _procurement_bid_rows() if _safe_int(row.get("tender_id")) in allowed_tenders]
        if tender_id:
            rows = [row for row in rows if _safe_int(row.get("tender_id")) == _safe_int(tender_id)]
        return rows

    @router.post("/api/procurement/tender_bids")
    def create_procurement_tender_bid(data: ProcurementTenderBidData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        allowed_tender_ids = {_safe_int(row.get("id")) for row in get_procurement_tenders(request)}
        if _safe_int(data.tender_id) not in allowed_tender_ids:
            return _api_error(404, "tender_not_found")
        supplier_name = data.supplier_name
        if data.supplier_id:
            supplier_row = next((row for row in _rows("SELECT id, supplier_name FROM supplier_registry") if _safe_int(row.get("id")) == _safe_int(data.supplier_id)), None)
            supplier_name = supplier_name or (supplier_row or {}).get("supplier_name", "")
        now = now_ts()
        normalized_score = _safe_float(data.score)
        if normalized_score <= 0:
            normalized_score = max(0, 100 - min(_safe_float(data.price) / 1000, 50) - min(_safe_int(data.lead_time_days) * 2, 30))
        conn = get_connection()
        bid_id = _insert(conn, "procurement_tender_bids", {
            "tender_id": _safe_int(data.tender_id),
            "supplier_id": _safe_int(data.supplier_id),
            "supplier_name": supplier_name,
            "price": data.price,
            "currency": data.currency or "RUB",
            "lead_time_days": data.lead_time_days,
            "payment_terms": data.payment_terms,
            "warranty_terms": data.warranty_terms,
            "score": round(normalized_score, 2),
            "status": data.status or "submitted",
            "comment": data.comment,
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.execute("UPDATE procurement_tenders SET status='collecting_bids', updated_at=? WHERE id=?", (now, _safe_int(data.tender_id)))
        conn.commit()
        conn.close()
        return {"status": "success", "id": bid_id}

    @router.post("/api/procurement/tenders/{tender_id}/award")
    def award_procurement_tender(tender_id: int, data: ProcurementAwardData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "update"):
            return {"error": "forbidden"}
        tender = next((row for row in get_procurement_tenders(request) if _safe_int(row.get("id")) == _safe_int(tender_id)), None)
        if not tender:
            return _api_error(404, "tender_not_found")
        bid = next((row for row in _procurement_bid_rows() if _safe_int(row.get("id")) == _safe_int(data.bid_id)), None) if data.bid_id else _best_procurement_bid(tender_id)
        if not bid:
            return _api_error(404, "bid_not_found")
        request_row = next((row for row in _procurement_request_rows(actor) if _safe_int(row.get("id")) == _safe_int(tender.get("request_id"))), None)
        if not request_row:
            return _api_error(404, "request_not_found")
        now = now_ts()
        conn = get_connection()
        purchase_id = 0
        supplier_id = _safe_int(bid.get("supplier_id"))
        conn.execute("UPDATE procurement_tender_bids SET status=CASE WHEN id=? THEN 'awarded' ELSE 'rejected' END, updated_at=? WHERE tender_id=?", (_safe_int(bid.get("id")), now, _safe_int(tender_id)))
        conn.execute("UPDATE procurement_tenders SET status='awarded', selected_supplier_id=?, selected_bid_id=?, decision_comment=?, updated_at=? WHERE id=?", (supplier_id, _safe_int(bid.get("id")), data.decision_comment or "Выбран лучший поставщик", now, _safe_int(tender_id)))
        conn.execute("UPDATE procurement_requests SET status='awarded', selected_supplier_id=?, approved_by=?, approved_at=?, updated_at=? WHERE id=?", (supplier_id, actor.get("name", ""), now, now, _safe_int(request_row.get("id"))))
        if _safe_int(data.create_purchase):
            purchase_id = _create_purchase_from_request(conn, request_row, actor, supplier_id, bid)
        conn.commit()
        conn.close()
        return {"status": "success", "id": _safe_int(bid.get("id")), "purchase_id": purchase_id}

    @router.post("/api/procurement/requests/{request_id}/create_purchase")
    def create_purchase_from_procurement_request(request_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        request_row = next((row for row in _procurement_request_rows(actor) if _safe_int(row.get("id")) == _safe_int(request_id)), None)
        if not request_row:
            return _api_error(404, "request_not_found")
        if _safe_int(request_row.get("linked_purchase_id")):
            return {"status": "success", "id": _safe_int(request_row.get("linked_purchase_id")), "already_created": True}
        tender = next((row for row in _procurement_tender_rows() if _safe_int(row.get("request_id")) == _safe_int(request_id) and _safe_int(row.get("selected_bid_id"))), None)
        bid = next((row for row in _procurement_bid_rows() if _safe_int(row.get("id")) == _safe_int((tender or {}).get("selected_bid_id"))), None) if tender else None
        supplier_id = _safe_int(request_row.get("selected_supplier_id")) or _safe_int((bid or {}).get("supplier_id"))
        conn = get_connection()
        purchase_id = _create_purchase_from_request(conn, request_row, actor, supplier_id, bid)
        conn.commit()
        conn.close()
        return {"status": "success", "id": purchase_id}

    @router.get("/api/procurement/receipts")
    def get_purchase_receipts(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        allowed_purchase_ids = {_safe_int(row.get("id")) for row in _filter_scope_rows_for_actor(actor, enhanced_load_purchase_rows())}
        return [row for row in _purchase_receipt_rows() if _safe_int(row.get("purchase_id")) in allowed_purchase_ids]

    @router.post("/api/procurement/receipts")
    def create_purchase_receipt(data: PurchaseReceiptData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        purchase = next((row for row in _filter_scope_rows_for_actor(actor, enhanced_load_purchase_rows()) if _safe_int(row.get("id")) == _safe_int(data.purchase_id)), None)
        if not purchase:
            return _api_error(404, "purchase_not_found")
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        article = _normalize_spaces(data.article or purchase.get("item_article") or "")
        item_name = data.item_name or purchase.get("item_name") or article
        request_id = _safe_int(data.request_id) or next((_safe_int(row.get("id")) for row in _procurement_request_rows(actor) if _safe_int(row.get("linked_purchase_id")) == _safe_int(data.purchase_id)), 0)
        now = now_ts()
        conn = get_connection()
        c = conn.cursor()
        receipt_id = _insert(conn, "purchase_receipts", {
            "purchase_id": _safe_int(data.purchase_id),
            "request_id": request_id,
            "supplier_id": _safe_int(data.supplier_id) or _safe_int(purchase.get("supplier_id")),
            "receipt_number": data.receipt_number or _next_code("RCV"),
            "receipt_date": data.receipt_date or datetime.now().strftime("%d.%m.%Y"),
            "article": article,
            "item_name": item_name,
            "accepted_qty": data.accepted_qty,
            "rejected_qty": data.rejected_qty,
            "warehouse": warehouse,
            "bin_code": bin_code,
            "quality_status": data.quality_status or "accepted",
            "status": data.status or "posted",
            "comment": data.comment,
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        if _safe_float(data.accepted_qty) > 0 and data.status != "draft":
            _upsert_inventory_balance(c, article, warehouse, bin_code, _safe_float(data.accepted_qty))
            lot_code = data.receipt_number or f"RCV-{receipt_id}"
            _upsert_inventory_lot(c, article, warehouse, bin_code, lot_code, "", _safe_float(data.accepted_qty), data.lot_expiration_date or "")
            receipt_cost_layer(conn, article, item_name, warehouse, bin_code, lot_code, "", _safe_float(data.accepted_qty), _safe_float(data.unit_cost) or _safe_float(purchase.get("unit_price")) or _safe_float(purchase.get("planned_unit_price")), actor.get("email", ""), "purchase_receipt", receipt_id, data.lot_expiration_date or "", purchase.get("unit") or "шт", {"purchase_id": _safe_int(data.purchase_id)})
        delivered_qty = _safe_float(purchase.get("delivered_qty")) + _safe_float(data.accepted_qty)
        planned_qty = _safe_float(purchase.get("qty"))
        purchase_status = "received" if planned_qty > 0 and delivered_qty >= planned_qty else "partial"
        received_date = data.receipt_date or datetime.now().strftime("%d.%m.%Y") if purchase_status == "received" else purchase.get("received_date") or ""
        conn.execute("UPDATE purchase_orders SET delivered_qty=?, status=?, received_date=?, schedule_status=?, updated_at=? WHERE id=?", (round(delivered_qty, 3), purchase_status, received_date, purchase_status, now, _safe_int(data.purchase_id)))
        if request_id and purchase_status == "received":
            conn.execute("UPDATE procurement_requests SET status='received', updated_at=? WHERE id=?", (now, request_id))
        matching = run_three_way_match_for_purchase(conn, data.purchase_id, actor.get("email", ""))
        conn.commit()
        conn.close()
        return {"status": "success", "id": receipt_id, "matching": matching}

    @router.get("/api/procurement/documents")
    def get_purchase_documents(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        allowed_purchase_ids = {_safe_int(row.get("id")) for row in _filter_scope_rows_for_actor(actor, enhanced_load_purchase_rows())}
        return [row for row in _purchase_document_rows() if _safe_int(row.get("purchase_id")) in allowed_purchase_ids]

    @router.post("/api/procurement/documents")
    def create_purchase_document(data: PurchaseDocumentData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        purchase = next((row for row in _filter_scope_rows_for_actor(actor, enhanced_load_purchase_rows()) if _safe_int(row.get("id")) == _safe_int(data.purchase_id)), None)
        if not purchase:
            return _api_error(404, "purchase_not_found")
        request_id = _safe_int(data.request_id) or next((_safe_int(row.get("id")) for row in _procurement_request_rows(actor) if _safe_int(row.get("linked_purchase_id")) == _safe_int(data.purchase_id)), 0)
        amount = _safe_float(data.amount) or _safe_float(purchase.get("total_amount"))
        now = now_ts()
        conn = get_connection()
        document_id = _insert(conn, "purchase_documents", {
            "purchase_id": _safe_int(data.purchase_id),
            "request_id": request_id,
            "supplier_id": _safe_int(data.supplier_id) or _safe_int(purchase.get("supplier_id")),
            "doc_type": data.doc_type or "invoice",
            "doc_number": data.doc_number or _next_code((data.doc_type or "INV").upper()),
            "doc_date": data.doc_date or datetime.now().strftime("%d.%m.%Y"),
            "amount": amount,
            "vat_amount": data.vat_amount,
            "currency": data.currency or "RUB",
            "status": data.status or "draft",
            "payment_due_date": data.payment_due_date,
            "linked_payment_id": _safe_int(data.linked_payment_id),
            "file_ref": data.file_ref,
            "comment": data.comment,
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        matching = run_three_way_match_for_purchase(conn, data.purchase_id, actor.get("email", ""))
        conn.commit()
        conn.close()
        return {"status": "success", "id": document_id, "matching": matching}

    @router.get("/api/procurement/three_way_matches")
    def get_three_way_matches(request: Request, purchase_id: int = 0, status: str = ""):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        allowed_purchase_ids = {_safe_int(row.get("id")) for row in _filter_scope_rows_for_actor(actor, enhanced_load_purchase_rows())}
        rows = [row for row in _rows("SELECT * FROM three_way_matches ORDER BY updated_at DESC, id DESC") if _safe_int(row.get("purchase_id")) in allowed_purchase_ids]
        if purchase_id:
            rows = [row for row in rows if _safe_int(row.get("purchase_id")) == _safe_int(purchase_id)]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    @router.get("/api/procurement/invoice_matches")
    def get_invoice_matching_results(request: Request, invoice_id: int = 0, status: str = ""):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        rows = _rows("SELECT * FROM invoice_matching_results ORDER BY updated_at DESC, id DESC")
        if invoice_id:
            rows = [row for row in rows if _safe_int(row.get("invoice_id")) == _safe_int(invoice_id)]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    @router.post("/api/procurement/purchases/{purchase_id}/three_way_match")
    def rebuild_three_way_match(purchase_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "update"):
            return {"error": "forbidden"}
        purchase = next((row for row in _filter_scope_rows_for_actor(actor, enhanced_load_purchase_rows()) if _safe_int(row.get("id")) == _safe_int(purchase_id)), None)
        if not purchase:
            return _api_error(404, "purchase_not_found")
        conn = get_connection(row_factory=True)
        result = run_three_way_match_for_purchase(conn, purchase_id, actor.get("email", ""))
        if result.get("error"):
            conn.rollback()
            conn.close()
            return _api_error(404, result.get("error"))
        conn.commit()
        conn.close()
        return result

    @router.get("/api/stock/quality_reports")
    def get_quality_reports(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _rows("SELECT * FROM warehouse_quality_reports ORDER BY created_at DESC, id DESC")

    @router.get("/api/stock/policy")
    def get_stock_policy(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _policy_settings()

    @router.post("/api/stock/policy")
    def save_stock_policy(data: WarehousePolicyData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO warehouse_policies (id, cost_method, allow_negative_stock, auto_pick_strategy, comment, updated_by, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                cost_method=EXCLUDED.cost_method,
                allow_negative_stock=EXCLUDED.allow_negative_stock,
                auto_pick_strategy=EXCLUDED.auto_pick_strategy,
                comment=EXCLUDED.comment,
                updated_by=EXCLUDED.updated_by,
                updated_at=EXCLUDED.updated_at
            """,
            ((data.cost_method or "fifo").lower(), int(data.allow_negative_stock or 0), data.auto_pick_strategy or "best_fit", data.comment or "", actor.get("email", ""), now_ts()),
        )
        conn.commit()
        conn.close()
        return {"status": "success"}

    @router.get("/api/stock/cost_layers")
    def get_stock_cost_layers(request: Request, article: str = ""):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        try:
            payload = inventory_costing_summary(conn, article)
        finally:
            conn.close()
        return payload

    @router.get("/api/stock/unit_conversions")
    def get_unit_conversions(request: Request, article: str = ""):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        params = []
        query = "SELECT * FROM unit_conversions"
        if article:
            query += " WHERE article=?"
            params.append(article)
        query += " ORDER BY article ASC, from_unit ASC, to_unit ASC"
        return _rows(query, tuple(params))

    @router.post("/api/stock/unit_conversions")
    def save_unit_conversion(data: UnitConversionData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        try:
            payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
            record_id = upsert_unit_conversion(conn, payload, actor.get("email", ""))
            conn.commit()
        finally:
            conn.close()
        return {"status": "success", "id": record_id}

    @router.get("/api/stock/item_packages")
    def get_item_packages(request: Request, article: str = ""):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        params = []
        query = "SELECT * FROM item_packages"
        if article:
            query += " WHERE article=?"
            params.append(article)
        query += " ORDER BY article ASC, is_default DESC, package_code ASC"
        return _rows(query, tuple(params))

    @router.post("/api/stock/item_packages")
    def save_item_package(data: ItemPackageData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        try:
            payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
            record_id = upsert_item_package(conn, payload, actor.get("email", ""))
            conn.commit()
        finally:
            conn.close()
        return {"status": "success", "id": record_id}

    @router.get("/api/wms/summary")
    def get_wms_summary(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        cells = _wms_cell_rows()
        putaway = _wms_putaway_rows()
        waves = _wms_pick_wave_rows()
        tasks = _wms_pick_task_rows()
        counts = _wms_cycle_count_rows()
        lot_positions = _wms_lot_position_rows(120)
        conn = get_connection(row_factory=True)
        try:
            costing = inventory_costing_summary(conn)
        finally:
            conn.close()
        return {
            "metrics": {
                "cells": len(cells),
                "overfilled_cells": len([row for row in cells if row.get("risk_level") == "risk"]),
                "putaway_open": len([row for row in putaway if (row.get("status") or "") not in {"done", "cancelled"}]),
                "pick_waves_open": len([row for row in waves if (row.get("status") or "") not in {"done", "cancelled"}]),
                "pick_tasks_open": len([row for row in tasks if (row.get("status") or "") not in {"done", "cancelled"}]),
                "cycle_counts_open": len([row for row in counts if (row.get("status") or "") != "closed"]),
                "lot_positions": len([row for row in lot_positions if row.get("batch_code")]),
                "serial_positions": len([row for row in lot_positions if row.get("serial_no")]),
                "inventory_cost_amount": costing.get("totals", {}).get("amount", 0),
            },
            "cells": cells[:50],
            "putaway_tasks": putaway[:40],
            "pick_waves": waves[:40],
            "pick_tasks": tasks[:60],
            "cycle_counts": counts[:40],
            "cycle_count_lines": _wms_cycle_count_line_rows()[:80],
            "lot_positions": lot_positions[:80],
            "cost_layers": costing.get("rows", [])[:80],
        }

    @router.get("/api/wms/cells")
    def get_wms_cells(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _wms_cell_rows()

    @router.post("/api/wms/cells")
    def save_wms_cell(data: WMSCellProfileData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        now = now_ts()
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO wms_cell_profiles (warehouse, bin_code, zone_name, cell_type, capacity_qty, capacity_weight, abc_class, status, comment, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(warehouse, bin_code) DO UPDATE SET zone_name=excluded.zone_name, cell_type=excluded.cell_type, capacity_qty=excluded.capacity_qty, capacity_weight=excluded.capacity_weight, abc_class=excluded.abc_class, status=excluded.status, comment=excluded.comment, updated_at=excluded.updated_at
            """,
            (warehouse, bin_code, data.zone_name or "", data.cell_type or "storage", data.capacity_qty, data.capacity_weight, data.abc_class or "", data.status or "active", data.comment or "", actor.get("email", ""), now, now),
        )
        row = conn.execute("SELECT id FROM wms_cell_profiles WHERE warehouse=? AND bin_code=?", (warehouse, bin_code)).fetchone()
        conn.commit()
        conn.close()
        return {"status": "success", "id": row[0] if row else 0}

    @router.delete("/api/wms/cells/{row_id}")
    def delete_wms_cell(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        _delete("wms_cell_profiles", row_id)
        return {"status": "success"}

    @router.get("/api/wms/putaway_tasks")
    def get_wms_putaway_tasks(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _wms_putaway_rows()

    @router.post("/api/wms/putaway_tasks")
    def create_wms_putaway_task(data: WMSPutawayTaskData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "create"):
            return {"error": "forbidden"}
        source_warehouse, source_bin = _normalize_stock_location(data.source_warehouse, data.source_bin)
        conn = get_connection()
        target = {}
        if not (data.target_warehouse or data.target_bin):
            target = choose_putaway_cell(conn, data.article, data.qty, data.source_warehouse or "")
        target_warehouse, target_bin = _normalize_stock_location(data.target_warehouse or target.get("warehouse"), data.target_bin or target.get("bin_code"))
        now = now_ts()
        row_id = _insert(conn, "wms_putaway_tasks", {
            "receipt_id": _safe_int(data.receipt_id),
            "article": _normalize_spaces(data.article),
            "item_name": data.item_name or data.article,
            "qty": data.qty,
            "source_warehouse": source_warehouse,
            "source_bin": source_bin,
            "target_warehouse": target_warehouse,
            "target_bin": target_bin,
            "batch_code": data.batch_code or "",
            "serial_no": data.serial_no or "",
            "lot_expiration_date": data.lot_expiration_date or "",
            "priority": data.priority or "normal",
            "status": data.status or "open",
            "assigned_to": data.assigned_to or "",
            "completed_at": 0,
            "comment": data.comment or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.post("/api/wms/putaway_tasks/{task_id}/complete")
    def complete_wms_putaway_task(task_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute("SELECT * FROM wms_putaway_tasks WHERE id=?", (_safe_int(task_id),))
        task = c.fetchone()
        if not task:
            conn.close()
            return _api_error(404, "not_found")
        if (task.get("status") or "") == "done":
            conn.close()
            return {"status": "success", "already_done": True}
        article = _normalize_spaces(task.get("article") or "")
        qty = _safe_float(task.get("qty"))
        source_warehouse, source_bin = _normalize_stock_location(task.get("source_warehouse"), task.get("source_bin"))
        target_warehouse, target_bin = _normalize_stock_location(task.get("target_warehouse"), task.get("target_bin"))
        available = _wms_expected_qty(c, article, source_warehouse, source_bin, task.get("batch_code") or "", task.get("serial_no") or "")
        if qty <= 0 or available + 0.0001 < qty:
            conn.close()
            return _api_error(409, "insufficient_stock", available_qty=round(available, 3))
        cost_allocations, cost_missing = consume_cost_layers(conn, article, qty, source_warehouse, source_bin, task.get("batch_code") or "", task.get("serial_no") or "", actor.get("email", ""), "wms_putaway", _safe_int(task_id), details={"task_id": _safe_int(task_id)})
        if cost_missing > 0:
            conn.rollback()
            conn.close()
            return _api_error(409, "insufficient_cost_layers", missing_qty=round(cost_missing, 3))
        allocations, missing = policy_consume_inventory_lots(c, article, qty, source_warehouse, source_bin, task.get("batch_code") or "", task.get("serial_no") or "")
        if missing > 0 or not allocations:
            conn.rollback()
            conn.close()
            return _api_error(409, "insufficient_stock")
        _upsert_inventory_balance(c, article, source_warehouse, source_bin, -qty)
        _upsert_inventory_balance(c, article, target_warehouse, target_bin, qty)
        for allocation in allocations:
            expiration = allocation.get("lot_expiration_date") or task.get("lot_expiration_date") or ""
            _upsert_inventory_lot(c, article, target_warehouse, target_bin, allocation.get("batch_code", ""), allocation.get("serial_no", ""), allocation.get("qty", 0), expiration)
            cost_match = next((row for row in cost_allocations if row.get("batch_code") == allocation.get("batch_code") and row.get("serial_no") == allocation.get("serial_no")), {})
            _record_stock_movement(c, article, task.get("item_name") or article, allocation.get("qty", 0), "move", source_warehouse, source_bin, target_warehouse, target_bin, allocation.get("batch_code", ""), allocation.get("serial_no", ""), actor.get("email", ""), task.get("comment") or "WMS putaway", "wms_putaway", 0, _safe_int(task_id), "wms_putaway", expiration, cost_match.get("unit_cost", 0), cost_match.get("amount", 0))
        transfer_cost_layers(conn, cost_allocations, article, task.get("item_name") or article, target_warehouse, target_bin, actor.get("email", ""), "wms_putaway", _safe_int(task_id), task.get("lot_expiration_date") or "")
        c.execute("UPDATE wms_putaway_tasks SET status='done', completed_at=?, updated_at=? WHERE id=?", (now_ts(), now_ts(), _safe_int(task_id)))
        conn.commit()
        conn.close()
        return {"status": "success", "id": _safe_int(task_id)}

    @router.delete("/api/wms/putaway_tasks/{row_id}")
    def delete_wms_putaway_task(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        _delete("wms_putaway_tasks", row_id)
        return {"status": "success"}

    @router.get("/api/wms/pick_waves")
    def get_wms_pick_waves(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _wms_pick_wave_rows()

    @router.post("/api/wms/pick_waves")
    def create_wms_pick_wave(data: WMSPickWaveData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "create"):
            return {"error": "forbidden"}
        now = now_ts()
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        wave_id = _insert(conn, "wms_pick_waves", {
            "wave_number": data.wave_number or _next_code("WAVE"),
            "project_id": _safe_int(data.project_id),
            "source_type": data.source_type or "reservation",
            "status": "draft",
            "priority": data.priority or "normal",
            "planned_ship_date": data.planned_ship_date or "",
            "assigned_to": data.assigned_to or "",
            "comment": data.comment or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        for reservation_id in [row_id for row_id in (data.reservation_ids or []) if _safe_int(row_id) > 0]:
            c.execute("SELECT * FROM stock_reservations WHERE id=?", (_safe_int(reservation_id),))
            reservation = c.fetchone()
            if not reservation:
                continue
            qty = max(_safe_float(reservation.get("qty")) - _safe_float(reservation.get("fulfilled_qty")), 0)
            if qty <= 0:
                continue
            warehouse, bin_code = _normalize_stock_location(reservation.get("warehouse"), reservation.get("bin_code"))
            source = policy_pick_inventory_source(c, reservation.get("nomenclature_article") or "", qty) if not (reservation.get("warehouse") or reservation.get("bin_code") or reservation.get("batch_code") or reservation.get("serial_no")) else None
            if source:
                warehouse, bin_code = source.get("warehouse"), source.get("bin_code")
            _insert(conn, "wms_pick_tasks", {
                "wave_id": wave_id,
                "reservation_id": _safe_int(reservation_id),
                "article": _normalize_spaces(reservation.get("nomenclature_article") or ""),
                "item_name": reservation.get("nomenclature_name") or reservation.get("nomenclature_article") or "",
                "qty": qty,
                "picked_qty": 0,
                "warehouse": warehouse,
                "bin_code": bin_code,
                "batch_code": reservation.get("batch_code") or (source or {}).get("batch_code", ""),
                "serial_no": reservation.get("serial_no") or (source or {}).get("serial_no", ""),
                "lot_expiration_date": (source or {}).get("lot_expiration_date", ""),
                "status": "open",
                "assigned_to": data.assigned_to or "",
                "picked_at": 0,
                "comment": f"Резерв #{reservation_id}",
                "created_by": actor.get("email", ""),
                "created_at": now,
                "updated_at": now,
            })
        conn.commit()
        conn.close()
        return {"status": "success", "id": wave_id}

    @router.post("/api/wms/pick_waves/{wave_id}/release")
    def release_wms_pick_wave(wave_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        conn = get_connection()
        conn.execute("UPDATE wms_pick_waves SET status='released', updated_at=? WHERE id=?", (now_ts(), _safe_int(wave_id)))
        conn.commit()
        conn.close()
        return {"status": "success", "id": _safe_int(wave_id)}

    @router.delete("/api/wms/pick_waves/{row_id}")
    def delete_wms_pick_wave(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        conn = get_connection()
        conn.execute("DELETE FROM wms_pick_tasks WHERE wave_id=?", (_safe_int(row_id),))
        conn.execute("DELETE FROM wms_pick_waves WHERE id=?", (_safe_int(row_id),))
        conn.commit()
        conn.close()
        return {"status": "success"}

    @router.get("/api/wms/pick_tasks")
    def get_wms_pick_tasks(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _wms_pick_task_rows()

    @router.post("/api/wms/pick_tasks")
    def create_wms_pick_task(data: WMSPickTaskData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "create"):
            return {"error": "forbidden"}
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        now = now_ts()
        conn = get_connection()
        row_id = _insert(conn, "wms_pick_tasks", {
            "wave_id": _safe_int(data.wave_id),
            "reservation_id": _safe_int(data.reservation_id),
            "article": _normalize_spaces(data.article),
            "item_name": data.item_name or data.article,
            "qty": data.qty,
            "picked_qty": data.picked_qty,
            "warehouse": warehouse,
            "bin_code": bin_code,
            "batch_code": data.batch_code or "",
            "serial_no": data.serial_no or "",
            "lot_expiration_date": data.lot_expiration_date or "",
            "status": data.status or "open",
            "assigned_to": data.assigned_to or "",
            "picked_at": 0,
            "comment": data.comment or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.post("/api/wms/pick_tasks/{task_id}/pick")
    def pick_wms_task(task_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute("SELECT * FROM wms_pick_tasks WHERE id=?", (_safe_int(task_id),))
        task = c.fetchone()
        if not task:
            conn.close()
            return _api_error(404, "not_found")
        article = _normalize_spaces(task.get("article") or "")
        qty_total = _safe_float(task.get("qty"))
        qty_left = round(max(qty_total - _safe_float(task.get("picked_qty")), 0), 3)
        if qty_left <= 0:
            conn.close()
            return {"status": "success", "already_done": True}
        warehouse, bin_code = _normalize_stock_location(task.get("warehouse"), task.get("bin_code"))
        available = _wms_expected_qty(c, article, warehouse, bin_code, task.get("batch_code") or "", task.get("serial_no") or "")
        if available + 0.0001 < qty_left:
            conn.close()
            return _api_error(409, "insufficient_stock", available_qty=round(available, 3))
        cost_allocations, cost_missing = consume_cost_layers(conn, article, qty_left, warehouse, bin_code, task.get("batch_code") or "", task.get("serial_no") or "", actor.get("email", ""), "wms_pick", _safe_int(task_id), details={"task_id": _safe_int(task_id)})
        if cost_missing > 0:
            conn.rollback()
            conn.close()
            return _api_error(409, "insufficient_cost_layers", missing_qty=round(cost_missing, 3))
        allocations, missing = policy_consume_inventory_lots(c, article, qty_left, warehouse, bin_code, task.get("batch_code") or "", task.get("serial_no") or "")
        if missing > 0 or not allocations:
            conn.rollback()
            conn.close()
            return _api_error(409, "insufficient_stock")
        _upsert_inventory_balance(c, article, warehouse, bin_code, -qty_left)
        for allocation in allocations:
            cost_match = next((row for row in cost_allocations if row.get("batch_code") == allocation.get("batch_code") and row.get("serial_no") == allocation.get("serial_no")), {})
            _record_stock_movement(c, article, task.get("item_name") or article, allocation.get("qty", 0), "remove", warehouse, bin_code, "", "", allocation.get("batch_code", ""), allocation.get("serial_no", ""), actor.get("email", ""), task.get("comment") or "WMS pick", "wms_pick", _safe_int(task.get("reservation_id")), _safe_int(task_id), "wms_pick", allocation.get("lot_expiration_date", ""), cost_match.get("unit_cost", 0), cost_match.get("amount", 0))
        picked_qty = round(_safe_float(task.get("picked_qty")) + qty_left, 3)
        status = "done" if picked_qty + 0.0001 >= qty_total else "partial"
        c.execute("UPDATE wms_pick_tasks SET picked_qty=?, status=?, picked_at=?, updated_at=? WHERE id=?", (picked_qty, status, now_ts(), now_ts(), _safe_int(task_id)))
        reservation_id = _safe_int(task.get("reservation_id"))
        if reservation_id:
            c.execute("SELECT qty, fulfilled_qty FROM stock_reservations WHERE id=?", (reservation_id,))
            reservation = c.fetchone()
            if reservation:
                reservation_qty = _safe_float(reservation.get("qty"))
                fulfilled_qty = min(round(_safe_float(reservation.get("fulfilled_qty")) + qty_left, 3), reservation_qty)
                reservation_status = "fulfilled" if fulfilled_qty + 0.0001 >= reservation_qty else "partial"
                c.execute("UPDATE stock_reservations SET fulfilled_qty=?, status=?, released_at=?, released_by=? WHERE id=?", (fulfilled_qty, reservation_status, now_ts() if reservation_status == "fulfilled" else 0, actor.get("email", "") if reservation_status == "fulfilled" else "", reservation_id))
        if _safe_int(task.get("wave_id")):
            c.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done FROM wms_pick_tasks WHERE wave_id=?", (_safe_int(task.get("wave_id")),))
            wave_state = c.fetchone()
            if wave_state and _safe_int(wave_state.get("total")) > 0 and _safe_int(wave_state.get("total")) == _safe_int(wave_state.get("done")):
                c.execute("UPDATE wms_pick_waves SET status='done', updated_at=? WHERE id=?", (now_ts(), _safe_int(task.get("wave_id"))))
        conn.commit()
        conn.close()
        return {"status": "success", "id": _safe_int(task_id), "picked_qty": picked_qty}

    @router.delete("/api/wms/pick_tasks/{row_id}")
    def delete_wms_pick_task(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        _delete("wms_pick_tasks", row_id)
        return {"status": "success"}

    @router.get("/api/wms/cycle_counts")
    def get_wms_cycle_counts(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _wms_cycle_count_rows()

    @router.post("/api/wms/cycle_counts")
    def create_wms_cycle_count(data: WMSCycleCountData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "create"):
            return {"error": "forbidden"}
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        now = now_ts()
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        count_id = _insert(conn, "wms_cycle_counts", {
            "count_number": data.count_number or _next_code("CC"),
            "warehouse": warehouse,
            "zone_name": data.zone_name or "",
            "bin_code": bin_code,
            "status": "draft",
            "planned_date": data.planned_date or datetime.now().strftime("%d.%m.%Y"),
            "started_at": now,
            "closed_at": 0,
            "assigned_to": data.assigned_to or "",
            "comment": data.comment or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        lot_rows = _rows(
            """
            SELECT l.article, COALESCE(n.name, l.article) AS item_name, l.warehouse, l.bin_code, l.batch_code, l.serial_no, l.qty
            FROM inventory_lots l
            LEFT JOIN nomenclature n ON n.article = l.article
            WHERE l.warehouse=? AND l.bin_code=? AND ABS(COALESCE(l.qty, 0)) > 0.0001
            ORDER BY l.article, l.batch_code, l.serial_no
            """,
            (warehouse, bin_code),
        )
        balance_rows = []
        if not lot_rows:
            balance_rows = _rows(
                """
                SELECT b.article, COALESCE(n.name, b.article) AS item_name, b.warehouse, b.bin_code, '' AS batch_code, '' AS serial_no, b.qty
                FROM inventory_balances b
                LEFT JOIN nomenclature n ON n.article = b.article
                WHERE b.warehouse=? AND b.bin_code=? AND ABS(COALESCE(b.qty, 0)) > 0.0001
                ORDER BY b.article
                """,
                (warehouse, bin_code),
            )
        for row in lot_rows or balance_rows:
            _insert(conn, "wms_cycle_count_lines", {
                "count_id": count_id,
                "article": row.get("article") or "",
                "item_name": row.get("item_name") or row.get("article") or "",
                "warehouse": row.get("warehouse") or warehouse,
                "bin_code": row.get("bin_code") or bin_code,
                "batch_code": row.get("batch_code") or "",
                "serial_no": row.get("serial_no") or "",
                "expected_qty": _safe_float(row.get("qty")),
                "counted_qty": _safe_float(row.get("qty")),
                "variance_qty": 0,
                "status": "draft",
                "comment": "Автоснимок WMS",
                "created_by": actor.get("email", ""),
                "created_at": now,
                "updated_at": now,
            })
        conn.commit()
        conn.close()
        return {"status": "success", "id": count_id}

    @router.get("/api/wms/cycle_count_lines")
    def get_wms_cycle_count_lines(request: Request, count_id: int = 0):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _wms_cycle_count_line_rows(count_id)

    @router.post("/api/wms/cycle_counts/{count_id}/lines")
    def create_wms_cycle_count_line(count_id: int, data: WMSCycleCountLineData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        conn = get_connection()
        c = conn.cursor()
        article = _normalize_spaces(data.article)
        expected_qty = _safe_float(data.expected_qty)
        if expected_qty == 0:
            expected_qty = _wms_expected_qty(c, article, warehouse, bin_code, data.batch_code or "", data.serial_no or "")
        variance = round(_safe_float(data.counted_qty) - expected_qty, 3)
        now = now_ts()
        row_id = _insert(conn, "wms_cycle_count_lines", {
            "count_id": _safe_int(count_id) or _safe_int(data.count_id),
            "article": article,
            "item_name": data.item_name or article,
            "warehouse": warehouse,
            "bin_code": bin_code,
            "batch_code": data.batch_code or "",
            "serial_no": data.serial_no or "",
            "expected_qty": expected_qty,
            "counted_qty": data.counted_qty,
            "variance_qty": variance,
            "status": data.status or "draft",
            "comment": data.comment or "",
            "created_by": actor.get("email", ""),
            "created_at": now,
            "updated_at": now,
        })
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.post("/api/wms/cycle_counts/{count_id}/close")
    def close_wms_cycle_count(count_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        c.execute("SELECT * FROM wms_cycle_counts WHERE id=?", (_safe_int(count_id),))
        count_row = c.fetchone()
        if not count_row:
            conn.close()
            return _api_error(404, "not_found")
        lines = _wms_cycle_count_line_rows(_safe_int(count_id))
        now = now_ts()
        posted_docs = 0
        for line in lines:
            expected_qty = _safe_float(line.get("expected_qty"))
            counted_qty = _safe_float(line.get("counted_qty"))
            variance = round(counted_qty - expected_qty, 3)
            article = _normalize_spaces(line.get("article") or "")
            warehouse, bin_code = _normalize_stock_location(line.get("warehouse"), line.get("bin_code"))
            if abs(variance) > 0.0001:
                _upsert_inventory_balance(c, article, warehouse, bin_code, variance)
                _upsert_inventory_lot(c, article, warehouse, bin_code, line.get("batch_code") or "", line.get("serial_no") or "", variance)
                doc_number = _next_inventory_doc_number("inventory")
                c.execute(
                    """
                    INSERT INTO inventory_documents (doc_type, doc_number, article, warehouse, bin_code, batch_code, serial_no, target_warehouse, target_bin, qty, counted_qty, adjustment_qty, reason, comment, status, actor_email, created_at, updated_at)
                    VALUES ('inventory', ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?, 'wms_cycle_count', ?, 'posted', ?, ?, ?)
                    """,
                    (doc_number, article, warehouse, bin_code, line.get("batch_code") or "", line.get("serial_no") or "", expected_qty, counted_qty, variance, line.get("comment") or f"WMS cycle count #{count_id}", actor.get("email", ""), now, now),
                )
                document_id = c.lastrowid
                _insert(conn, "inventory_acts", {
                    "warehouse": warehouse,
                    "bin_code": bin_code,
                    "article": article,
                    "item_name": line.get("item_name") or article,
                    "expected_qty": expected_qty,
                    "counted_qty": counted_qty,
                    "batch_code": line.get("batch_code") or "",
                    "serial_no": line.get("serial_no") or "",
                    "adjustment_qty": variance,
                    "status": "posted",
                    "comment": f"WMS cycle count #{count_id}",
                    "linked_document_id": document_id,
                    "created_by": actor.get("email", ""),
                    "created_at": now,
                    "updated_at": now,
                })
                _record_stock_movement(c, article, line.get("item_name") or article, abs(variance), "adjustment", warehouse, bin_code, warehouse, bin_code, line.get("batch_code") or "", line.get("serial_no") or "", actor.get("email", ""), f"WMS cycle count #{count_id}", "wms_cycle_count", 0, document_id, "inventory_document")
                posted_docs += 1
            c.execute("UPDATE wms_cycle_count_lines SET variance_qty=?, status='posted', updated_at=? WHERE id=?", (variance, now, _safe_int(line.get("id"))))
        c.execute("UPDATE wms_cycle_counts SET status='closed', closed_at=?, updated_at=? WHERE id=?", (now, now, _safe_int(count_id)))
        conn.commit()
        conn.close()
        return {"status": "success", "id": _safe_int(count_id), "posted_documents": posted_docs}

    @router.delete("/api/wms/cycle_counts/{row_id}")
    def delete_wms_cycle_count(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        conn = get_connection()
        conn.execute("DELETE FROM wms_cycle_count_lines WHERE count_id=?", (_safe_int(row_id),))
        conn.execute("DELETE FROM wms_cycle_counts WHERE id=?", (_safe_int(row_id),))
        conn.commit()
        conn.close()
        return {"status": "success"}

    @router.delete("/api/wms/cycle_count_lines/{row_id}")
    def delete_wms_cycle_count_line(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        _delete("wms_cycle_count_lines", row_id)
        return {"status": "success"}

    @router.get("/api/terminal/summary")
    def get_terminal_summary(request: Request):
        actor = require_approved_user(request)
        if not actor or not (has_permission(actor, "nsi", "read") or has_permission(actor, "production", "read")):
            return {"error": "forbidden"}
        sessions = [_terminal_payload(row) for row in _rows("SELECT * FROM terminal_sessions ORDER BY last_seen_at DESC, id DESC LIMIT 60")]
        scans = [_terminal_scan_payload(row) for row in _rows("SELECT * FROM terminal_scan_events ORDER BY created_at DESC, id DESC LIMIT 120")]
        production_events = _rows(
            """
            SELECT pe.*, COALESCE(po.order_name, '') AS order_name, COALESCE(poo.operation_name, '') AS operation_name
            FROM production_execution_events pe
            LEFT JOIN production_orders po ON po.id = pe.order_id
            LEFT JOIN production_operations poo ON poo.id = pe.operation_id
            ORDER BY pe.created_at DESC, pe.id DESC
            LIMIT 80
            """
        )
        wms_open = len([row for row in _wms_putaway_rows() if (row.get("status") or "") not in {"done", "cancelled"}]) + len([row for row in _wms_pick_task_rows() if (row.get("status") or "") not in {"done", "cancelled"}])
        return {
            "metrics": {
                "sessions_active": len([row for row in sessions if row.get("status") == "active"]),
                "warehouse_sessions": len([row for row in sessions if row.get("terminal_type") == "warehouse"]),
                "production_sessions": len([row for row in sessions if row.get("terminal_type") == "production"]),
                "scans_today": len([row for row in scans if _safe_int(row.get("created_at")) >= now_ts() - 86400]),
                "scan_errors": len([row for row in scans if row.get("result_status") == "error"]),
                "wms_open_tasks": wms_open,
                "production_events": len(production_events),
            },
            "sessions": sessions,
            "scans": scans,
            "production_events": production_events,
            "wms_queue": {
                "putaway": _wms_putaway_rows()[:20],
                "pick": _wms_pick_task_rows()[:30],
                "cycle_count_lines": _wms_cycle_count_line_rows()[:30],
            },
        }

    @router.post("/api/terminal/sessions")
    def create_terminal_session(data: TerminalSessionData, request: Request):
        actor = require_approved_user(request)
        if not actor or not (has_permission(actor, "nsi", "read") or has_permission(actor, "production", "read")):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        try:
            session = _ensure_terminal_session(conn, data, actor)
            conn.commit()
        finally:
            conn.close()
        audit_log("terminal_session_started", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="terminal_session", entity_id=str(session.get("id")), details={"terminal_type": session.get("terminal_type"), "terminal_code": session.get("terminal_code")})
        return {"status": "success", "session": _terminal_payload(session), "id": _safe_int(session.get("id"))}

    @router.post("/api/terminal/production/events")
    def create_terminal_production_event(data: ProductionExecutionEventData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "production", "update"):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        try:
            result = _apply_terminal_production_event(conn, data, actor)
            if result.get("error"):
                conn.rollback()
                return result
            conn.commit()
        finally:
            conn.close()
        audit_log("terminal_production_event", actor_email=actor.get("email", ""), actor_name=actor.get("name", ""), entity_type="production_execution_event", entity_id=str(result.get("id")), details=result)
        return result

    @router.post("/api/terminal/scan")
    def process_terminal_scan(data: TerminalScanData, request: Request):
        actor = require_approved_user(request)
        terminal_type = (data.terminal_type or "warehouse").strip().lower()
        if terminal_type == "warehouse" and not (actor and has_permission(actor, "nsi", "update")):
            return {"error": "forbidden"}
        if terminal_type == "production" and not (actor and has_permission(actor, "production", "update")):
            return {"error": "forbidden"}
        conn = get_connection(row_factory=True)
        try:
            session = _ensure_terminal_session(conn, data, actor)
            entity_type, entity_id = _resolve_terminal_entity(data.scan_value, data.entity_type, data.entity_id)
            data.entity_type = entity_type
            data.entity_id = entity_id
            action_name = (data.action_name or "lookup").strip().lower()
            result = {"status": "success", "action_name": action_name, "entity_type": entity_type, "entity_id": entity_id}
            if action_name in {"complete_putaway", "putaway_done"} and entity_type == "wms_putaway_task":
                result = _json_response_payload(complete_wms_putaway_task(entity_id, request))
            elif action_name in {"pick_task", "pick"} and entity_type == "wms_pick_task":
                result = _json_response_payload(pick_wms_task(entity_id, request))
            elif action_name in {"count_line", "cycle_count"} and entity_type == "wms_cycle_count_line":
                line = dict(conn.execute("SELECT * FROM wms_cycle_count_lines WHERE id=?", (_safe_int(entity_id),)).fetchone() or {})
                if not line:
                    result = {"error": "count_line_not_found"}
                else:
                    counted_qty = _safe_float((data.payload or {}).get("counted_qty"))
                    expected_qty = _safe_float(line.get("expected_qty"))
                    variance = round(counted_qty - expected_qty, 3)
                    conn.execute("UPDATE wms_cycle_count_lines SET counted_qty=?, variance_qty=?, status='counted', updated_at=? WHERE id=?", (counted_qty, variance, now_ts(), _safe_int(entity_id)))
                    result = {"status": "success", "id": _safe_int(entity_id), "variance_qty": variance}
            elif action_name in {"production_start", "production_complete", "production_scrap", "quality_hold"} and entity_type in {"production_operation", "production_job"}:
                event_type = {
                    "production_start": "start",
                    "production_complete": "complete",
                    "production_scrap": "scrap",
                    "quality_hold": "quality_hold",
                }[action_name]
                event = ProductionExecutionEventData(
                    operation_id=entity_id if entity_type == "production_operation" else 0,
                    job_id=entity_id if entity_type == "production_job" else 0,
                    event_type=event_type,
                    qty=_safe_float((data.payload or {}).get("qty")),
                    scrap_qty=_safe_float((data.payload or {}).get("scrap_qty")),
                    executor_name=(data.payload or {}).get("executor_name") or actor.get("name", ""),
                    payload=data.payload or {},
                )
                result = _apply_terminal_production_event(conn, event, actor)
            else:
                result["lookup"] = _terminal_lookup_payload(conn, entity_type, entity_id) if entity_id else {}
            scan_id = _log_terminal_scan(conn, session, data, actor, result)
            conn.commit()
        finally:
            conn.close()
        return {"status": "success" if not result.get("error") else "error", "scan_id": scan_id, "session_id": _safe_int(session.get("id")), "result": result}

    @router.post("/api/purchase/delivery_schedules")
    def create_delivery_schedule(data: SupplierDeliveryScheduleData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        conn = get_connection()
        row_id = _insert(conn, "supplier_delivery_schedules", {"purchase_id": data.purchase_id, "supplier_id": data.supplier_id, "scheduled_date": data.scheduled_date, "planned_qty": data.planned_qty, "delivered_qty": data.delivered_qty, "status": data.status, "transport_no": data.transport_no, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts()})
        conn.execute("UPDATE purchase_orders SET delivered_qty = COALESCE(delivered_qty, 0) + ?, schedule_status=?, updated_at=? WHERE id=?", (_safe_float(data.delivered_qty), "partial" if _safe_float(data.delivered_qty) < _safe_float(data.planned_qty) else "delivered", now_ts(), data.purchase_id))
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.get("/api/purchase/delivery_schedules")
    def get_delivery_schedules(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        rows = _rows("SELECT ds.*, COALESCE(po.item_name, '') AS item_name, COALESCE(sr.supplier_name, '') AS supplier_name FROM supplier_delivery_schedules ds LEFT JOIN purchase_orders po ON po.id = ds.purchase_id LEFT JOIN supplier_registry sr ON sr.id = ds.supplier_id ORDER BY ds.scheduled_date DESC, ds.id DESC")
        for row in rows:
            remaining = round(max(_safe_float(row.get("planned_qty")) - _safe_float(row.get("delivered_qty")), 0), 3)
            late_days = max(_days_between(row.get("scheduled_date")), 0) if remaining > 0 and (row.get("status") or "") not in {"delivered", "closed"} else 0
            row["remaining_qty"] = remaining
            row["late_days"] = late_days
            row["completion_percent"] = 100 if _safe_float(row.get("planned_qty")) <= 0 else round((_safe_float(row.get("delivered_qty")) / max(_safe_float(row.get("planned_qty")), 0.0001)) * 100, 1)
            row["risk_status"] = "late" if late_days > 0 else ("partial" if remaining > 0 else "stable")
        return rows

    @router.post("/api/purchase/returns")
    def create_supplier_return(data: SupplierReturnData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return _api_error(403, "forbidden")
        conn = get_connection()
        c = conn.cursor()
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        allocations, missing = policy_consume_inventory_lots(c, _normalize_spaces(data.article), _safe_float(data.qty), warehouse, bin_code)
        if missing > 0:
            conn.close()
            return _api_error(409, "insufficient_stock")
        _upsert_inventory_balance(c, _normalize_spaces(data.article), warehouse, bin_code, -_safe_float(data.qty))
        row_id = _insert(conn, "supplier_returns", {"purchase_id": data.purchase_id, "supplier_id": data.supplier_id, "article": _normalize_spaces(data.article), "item_name": data.item_name, "qty": data.qty, "amount": data.amount, "currency": data.currency, "warehouse": warehouse, "bin_code": bin_code, "status": data.status, "reason": data.reason, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts()})
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.get("/api/purchase/returns")
    def get_supplier_returns(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        return _rows("SELECT r.*, COALESCE(sr.supplier_name, '') AS supplier_name FROM supplier_returns r LEFT JOIN supplier_registry sr ON sr.id = r.supplier_id ORDER BY r.created_at DESC, r.id DESC")

    @router.post("/api/purchase/discrepancy_acts")
    def create_supplier_discrepancy_act(data: SupplierDiscrepancyActData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "create"):
            return {"error": "forbidden"}
        conn = get_connection()
        row_id = _insert(conn, "supplier_discrepancy_acts", {"purchase_id": data.purchase_id, "supplier_id": data.supplier_id, "act_number": data.act_number or _next_code("DISC"), "article": data.article, "item_name": data.item_name, "planned_qty": data.planned_qty, "actual_qty": data.actual_qty, "planned_unit_price": data.planned_unit_price, "actual_unit_price": data.actual_unit_price, "status": data.status, "reason": data.reason, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts()})
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.get("/api/purchase/discrepancy_acts")
    def get_supplier_discrepancy_acts(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "read"):
            return {"error": "forbidden"}
        rows = _rows("SELECT a.*, COALESCE(sr.supplier_name, '') AS supplier_name FROM supplier_discrepancy_acts a LEFT JOIN supplier_registry sr ON sr.id = a.supplier_id ORDER BY a.created_at DESC, a.id DESC")
        for row in rows:
            row["qty_gap"] = round(_safe_float(row.get("planned_qty")) - _safe_float(row.get("actual_qty")), 3)
            row["price_gap"] = round(_safe_float(row.get("actual_unit_price")) - _safe_float(row.get("planned_unit_price")), 2)
        return rows

    @router.post("/api/stock/inventory_acts")
    def create_inventory_act(data: InventoryActData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return _api_error(403, "forbidden")
        conn = get_connection(row_factory=True)
        c = conn.cursor()
        article = _normalize_spaces(data.article)
        c.execute("SELECT name FROM nomenclature WHERE article=?", (article,))
        row = c.fetchone()
        if not row:
            c.execute(
                "INSERT INTO nomenclature (article, name, unit, price, stock, currency, group_name, default_warehouse, exchange_state, external_sync_id) VALUES (?, ?, 'шт', 0, 0, 'RUB', '', '', 'queued', '')",
                (article, data.item_name or article),
            )
            c.execute("SELECT name FROM nomenclature WHERE article=?", (article,))
            row = c.fetchone()
        doc_number = _next_inventory_doc_number("inventory")
        inventory_doc = InventoryDocumentData(doc_type="inventory", doc_number=doc_number, article=article, warehouse=data.warehouse, bin_code=data.bin_code, batch_code=data.batch_code, serial_no=data.serial_no, qty=data.expected_qty, counted_qty=data.counted_qty, reason="inventory_act", comment=data.comment)
        c.execute("INSERT INTO inventory_documents (doc_type, doc_number, article, warehouse, bin_code, batch_code, serial_no, target_warehouse, target_bin, qty, counted_qty, adjustment_qty, reason, comment, status, actor_email, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, 0, ?, ?, 'draft', ?, ?, ?)", ("inventory", doc_number, article, data.warehouse or "", data.bin_code or "", data.batch_code or "", data.serial_no or "", data.expected_qty, data.counted_qty, "inventory_act", data.comment or "", actor.get("email", ""), now_ts(), now_ts()))
        document_id = c.lastrowid
        result = _apply_inventory_document(conn, document_id, article, data.item_name or row["name"], inventory_doc, actor.get("email", ""))
        act_id = _insert(conn, "inventory_acts", {"warehouse": data.warehouse or "", "bin_code": data.bin_code or "", "article": article, "item_name": data.item_name or row["name"], "expected_qty": data.expected_qty, "counted_qty": data.counted_qty, "batch_code": data.batch_code or "", "serial_no": data.serial_no or "", "adjustment_qty": result.get("adjustment_qty", 0), "status": data.status or "posted", "comment": data.comment, "linked_document_id": document_id, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts()})
        conn.commit()
        conn.close()
        return {"status": "success", "id": act_id, "linked_document_id": document_id}

    @router.get("/api/stock/inventory_acts")
    def get_inventory_acts(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _rows("SELECT * FROM inventory_acts ORDER BY created_at DESC, id DESC")

    @router.post("/api/stock/regrading")
    def create_regrading(data: InventoryRegradingData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "update"):
            return _api_error(403, "forbidden")
        conn = get_connection()
        c = conn.cursor()
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        allocations, missing = policy_consume_inventory_lots(c, _normalize_spaces(data.from_article), _safe_float(data.qty), warehouse, bin_code)
        if missing > 0:
            conn.close()
            return _api_error(409, "insufficient_stock")
        _upsert_inventory_balance(c, _normalize_spaces(data.from_article), warehouse, bin_code, -_safe_float(data.qty))
        _upsert_inventory_balance(c, _normalize_spaces(data.to_article), warehouse, bin_code, _safe_float(data.qty))
        for allocation in allocations or [{"batch_code": "", "serial_no": "", "qty": _safe_float(data.qty)}]:
            _upsert_inventory_lot(c, _normalize_spaces(data.to_article), warehouse, bin_code, allocation.get("batch_code", ""), allocation.get("serial_no", ""), allocation.get("qty", data.qty))
        row_id = _insert(conn, "inventory_regrading_docs", {"warehouse": warehouse, "bin_code": bin_code, "from_article": _normalize_spaces(data.from_article), "from_name": data.from_name, "to_article": _normalize_spaces(data.to_article), "to_name": data.to_name, "qty": data.qty, "status": data.status or "posted", "reason": data.reason, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts()})
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.get("/api/stock/regrading")
    def get_regrading(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        return _rows("SELECT * FROM inventory_regrading_docs ORDER BY created_at DESC, id DESC")

    @router.post("/api/sales/returns")
    def create_customer_return(data: CustomerReturnData, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "create"):
            return {"error": "forbidden"}
        conn = get_connection()
        c = conn.cursor()
        article = _normalize_spaces(data.article)
        warehouse, bin_code = _normalize_stock_location(data.warehouse, data.bin_code)
        if article:
            _upsert_inventory_balance(c, article, warehouse, bin_code, _safe_float(data.qty))
            _upsert_inventory_lot(c, article, warehouse, bin_code, "", "", _safe_float(data.qty))
        row_id = _insert(conn, "customer_returns", {"project_id": data.project_id, "client_id": data.client_id, "sales_document_id": data.sales_document_id, "return_number": data.return_number or _next_code("RET"), "article": article, "item_name": data.item_name, "qty": data.qty, "amount": data.amount, "currency": data.currency, "warehouse": warehouse, "bin_code": bin_code, "status": data.status, "reason": data.reason, "comment": data.comment, "created_by": actor.get("email", ""), "created_at": now_ts(), "updated_at": now_ts()})
        conn.commit()
        conn.close()
        return {"status": "success", "id": row_id}

    @router.get("/api/sales/returns")
    def get_customer_returns(request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "read"):
            return {"error": "forbidden"}
        return _rows("SELECT r.*, COALESCE(cl.name, '') AS client_name, COALESCE(sd.doc_number, '') AS sales_doc_number FROM customer_returns r LEFT JOIN clients cl ON cl.id = r.client_id LEFT JOIN sales_documents_extended sd ON sd.id = r.sales_document_id ORDER BY r.created_at DESC, r.id DESC")

    @router.get("/api/stock/documents/{doc_id}/print")
    def print_inventory_document(doc_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        payload = _print_inventory_document_payload(doc_id)
        if not payload:
            return {"error": "not_found"}
        return payload

    @router.get("/api/stock/inventory_acts/{row_id}/print")
    def print_inventory_act(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        payload = _print_inventory_act_payload(row_id)
        if not payload:
            return {"error": "not_found"}
        return payload

    @router.get("/api/stock/regrading/{row_id}/print")
    def print_regrading(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        payload = _print_regrading_payload(row_id)
        if not payload:
            return {"error": "not_found"}
        return payload

    @router.get("/api/stock/quality_reports/{row_id}/print")
    def print_quality_report(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        payload = _print_quality_payload(row_id)
        if not payload:
            return {"error": "not_found"}
        return payload

    @router.get("/api/stock/discrepancy_acts/{row_id}/print")
    def print_discrepancy_act(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "read"):
            return {"error": "forbidden"}
        payload = _print_discrepancy_payload(row_id)
        if not payload:
            return {"error": "not_found"}
        return payload

    @router.post("/api/stock/bulk_action")
    def apply_stock_bulk_action(data: WarehouseBulkActionData, request: Request):
        actor = require_approved_user(request)
        if not actor:
            return {"error": "forbidden"}
        entity_type = (data.entity_type or "").strip()
        action = (data.action or "").strip()
        ids = [int(row_id) for row_id in (data.ids or []) if _safe_int(row_id) > 0]
        if not entity_type or not action or not ids:
            return _api_error(400, "bulk_action_invalid")
        if action == "print":
            if not has_permission(actor, "nsi", "read"):
                return {"error": "forbidden"}
            printers = {
                "inventory_document": _print_inventory_document_payload,
                "inventory_act": _print_inventory_act_payload,
                "regrading_doc": _print_regrading_payload,
                "quality_report": _print_quality_payload,
                "discrepancy_act": _print_discrepancy_payload,
            }
            printer = printers.get(entity_type)
            if not printer:
                return _api_error(400, "bulk_action_not_supported")
            documents = [payload for payload in (printer(row_id) for row_id in ids) if payload]
            return {"status": "success", "count": len(documents), "documents": documents}
        if action == "delete":
            if not has_permission(actor, "nsi", "delete"):
                return {"error": "forbidden"}
            table_name = {"inventory_act": "inventory_acts", "regrading_doc": "inventory_regrading_docs"}.get(entity_type)
            if not table_name:
                return _api_error(400, "bulk_action_not_supported")
            conn = get_connection()
            conn.executemany(f"DELETE FROM {table_name} WHERE id=?", [(row_id,) for row_id in ids])
            conn.commit()
            conn.close()
            return {"status": "success", "count": len(ids)}
        if entity_type == "quality_report" and action in {"close", "release"}:
            if not has_permission(actor, "nsi", "update"):
                return {"error": "forbidden"}
            next_status = "closed" if action == "close" else "released"
            next_decision = "close" if action == "close" else "release"
            conn = get_connection()
            conn.executemany(
                "UPDATE warehouse_quality_reports SET status=?, decision=?, updated_at=? WHERE id=?",
                [(next_status, next_decision, now_ts(), row_id) for row_id in ids],
            )
            conn.commit()
            conn.close()
            return {"status": "success", "count": len(ids)}
        return _api_error(400, "bulk_action_not_supported")

    @router.delete("/api/purchase/delivery_schedules/{row_id}")
    def delete_delivery_schedule(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("supplier_delivery_schedules", row_id)
        return {"status": "success"}

    @router.delete("/api/procurement/requests/{row_id}")
    def delete_procurement_request(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("procurement_requests", row_id)
        return {"status": "success"}

    @router.delete("/api/procurement/tenders/{row_id}")
    def delete_procurement_tender(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("procurement_tenders", row_id)
        return {"status": "success"}

    @router.delete("/api/procurement/tender_bids/{row_id}")
    def delete_procurement_tender_bid(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("procurement_tender_bids", row_id)
        return {"status": "success"}

    @router.delete("/api/procurement/receipts/{row_id}")
    def delete_purchase_receipt(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("purchase_receipts", row_id)
        return {"status": "success"}

    @router.delete("/api/procurement/documents/{row_id}")
    def delete_purchase_document(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("purchase_documents", row_id)
        return {"status": "success"}

    @router.delete("/api/purchase/returns/{row_id}")
    def delete_supplier_return(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("supplier_returns", row_id)
        return {"status": "success"}

    @router.delete("/api/purchase/discrepancy_acts/{row_id}")
    def delete_supplier_discrepancy(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "supply", "delete"):
            return {"error": "forbidden"}
        _delete("supplier_discrepancy_acts", row_id)
        return {"status": "success"}

    @router.delete("/api/stock/inventory_acts/{row_id}")
    def delete_inventory_act(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        _delete("inventory_acts", row_id)
        return {"status": "success"}

    @router.delete("/api/stock/regrading/{row_id}")
    def delete_regrading(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "nsi", "delete"):
            return {"error": "forbidden"}
        _delete("inventory_regrading_docs", row_id)
        return {"status": "success"}

    @router.delete("/api/sales/returns/{row_id}")
    def delete_customer_return(row_id: int, request: Request):
        actor = require_approved_user(request)
        if not actor or not has_permission(actor, "sales", "delete"):
            return {"error": "forbidden"}
        _delete("customer_returns", row_id)
        return {"status": "success"}
