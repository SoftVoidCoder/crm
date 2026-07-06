import json
import time

from database import (
    create_erp_process_run,
    update_erp_process_run,
    get_erp_process_run,
    link_erp_entities,
    audit_log,
    create_notification,
    db_transaction,
    record_domain_event,
)


def _safe_int(value, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _today_display():
    return time.strftime("%d.%m.%Y")


def start_erp_process_record(
    data,
    *,
    actor: dict,
    load_project_payload_fn,
    can_edit_project_fn,
    resolve_master_context_fn,
    default_scenario_fn,
    autoroute_fn,
    request_obj,
):
    scenario = data.scenario or default_scenario_fn(data.request_type)
    if "request" not in scenario:
        scenario = ["request", *scenario]
    project = load_project_payload_fn(data.project_id) if data.project_id else None
    if project and not can_edit_project_fn(actor, project):
        return {"error": "forbidden"}

    with db_transaction(mode="immediate") as context_conn:
        context = resolve_master_context_fn(context_conn, data.project_id, data.client_id, data.contract_id, data.object_id)

    payload = {
        "target_role": data.target_role,
        "assignee_name": data.assignee_name,
        "approver_name": data.approver_name,
        "approver_role": data.approver_role,
        "priority": data.priority,
        "item_article": data.item_article,
        "item_name": data.item_name,
        "qty": data.qty,
        "unit": data.unit,
        "unit_price": data.unit_price,
        "supplier": data.supplier,
        "order_name": data.order_name,
        "responsible": data.responsible,
        "recipient_email": data.recipient_email,
        "comment": data.comment,
    }
    process_id = create_erp_process_run(
        title=data.title,
        project_id=context["project_id"],
        client_id=context["client_id"],
        contract_id=context["contract_id"],
        object_id=context["object_id"],
        request_type=data.request_type,
        scenario=scenario,
        due_date=data.due_date,
        amount=data.amount,
        currency=data.currency,
        status="new",
        current_stage="request",
        created_by=actor.get("email", ""),
        payload=payload,
    )

    now = int(time.time())
    with db_transaction(mode="immediate") as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO internal_requests (
                project_id, contract_id, object_id, title, request_type, target_role, assignee_name, priority, status, deadline,
                comment, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context["project_id"],
                context["contract_id"],
                context["object_id"],
                data.title,
                data.request_type,
                data.target_role,
                data.assignee_name,
                data.priority,
                "new",
                data.due_date,
                data.comment,
                actor.get("email", ""),
                now,
                now,
            ),
        )
        request_id = c.lastrowid

    update_erp_process_run(process_id, {"request_id": request_id, "status": "new", "current_stage": "request"}, actor.get("email", ""))
    link_erp_entities(
        process_id,
        "erp_process",
        process_id,
        "internal_request",
        request_id,
        "stage_request",
        context["project_id"],
        context["client_id"],
        actor.get("email", ""),
        {"title": data.title, "contract_id": context["contract_id"], "object_id": context["object_id"]},
    )
    audit_log(
        "erp_process_started",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="erp_process",
        entity_id=str(process_id),
        details={"title": data.title, "request_type": data.request_type, "scenario": scenario, "request_id": request_id},
    )
    audit_log(
        "internal_request_created",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="internal_request",
        entity_id=str(request_id),
        details={"title": data.title, "type": data.request_type, "status": "new", "process_id": process_id},
    )
    if data.assignee_name:
        create_notification(
            "Новый ERP-маршрут",
            f"{actor.get('name', 'Система')} запустил(а) процесс «{data.title}».",
            user_name=data.assignee_name,
            category="erp",
            entity_type="erp_process",
            entity_id=str(process_id),
        )
    record_domain_event(
        "erp_workflow",
        "process_started",
        entity_type="erp_process",
        entity_id=str(process_id),
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        payload={"title": data.title, "request_type": data.request_type, "request_id": request_id},
    )
    process = get_erp_process_run(process_id)
    autoroute_result = None
    if int(data.autoroute or 0) == 1:
        autoroute_result = autoroute_fn(process_id, actor, request_obj)
        process = get_erp_process_run(process_id) or process
    return {"status": "success", "id": process_id, "request_id": request_id, "process": process, "autoroute": autoroute_result}


def advance_erp_process_record(
    process_id: int,
    data,
    *,
    actor: dict,
    can_access_process_fn,
    resolve_master_context_fn,
    insert_approval_step_fn,
    stage_label_fn,
):
    process = get_erp_process_run(process_id)
    if not process:
        return {"error": "not_found"}
    if not can_access_process_fn(actor, process):
        return {"error": "forbidden"}
    target_stage = (data.target_stage or "").strip()
    if target_stage not in {"approval", "reserve", "purchase", "production", "shipment", "payment", "done"}:
        return {"error": "invalid_stage"}
    if target_stage == "done" and process.get("payment_id") and not actor.get("_can_mark_paid"):
        return {"error": "payment_rights_required"}

    payload = dict(process.get("payload") or {})
    for key, value in {
        "approver_name": data.approver_name,
        "approver_role": data.approver_role,
        "item_article": data.item_article,
        "item_name": data.item_name,
        "qty": data.qty,
        "unit": data.unit,
        "unit_price": data.unit_price,
        "supplier": data.supplier,
        "order_name": data.order_name,
        "responsible": data.responsible,
        "recipient_email": data.recipient_email,
        "comment": data.comment,
        "payment_kind": data.payment_kind,
    }.items():
        if value not in ("", None, 0, 0.0):
            payload[key] = value
    amount = _safe_float(data.amount) or _safe_float(process.get("amount"))
    currency = data.currency or process.get("currency") or "RUB"
    due_date = data.due_date or process.get("due_date") or payload.get("due_date") or ""
    project_id = _safe_int(process.get("project_id"))
    client_id = _safe_int(process.get("client_id"))
    contract_id = _safe_int(process.get("contract_id"))
    object_id = _safe_int(process.get("object_id"))
    title = process.get("title") or "ERP процесс"

    created_entity = None
    with db_transaction(mode="immediate") as conn:
        context = resolve_master_context_fn(conn, project_id, client_id, contract_id, object_id)
        project_id = context["project_id"]
        client_id = context["client_id"]
        contract_id = context["contract_id"]
        object_id = context["object_id"]
        c = conn.cursor()

        if process.get("approval_id") and target_stage != "approval":
            c.execute(
                "UPDATE approvals SET status='approved', current_step=1, history=? WHERE id=?",
                (json.dumps([{"event": "approved_via_erp", "at": time.strftime("%d.%m.%Y %H:%M"), "by": actor.get("name", "")}]), process.get("approval_id")),
            )

        if target_stage == "approval":
            if not actor.get("_can_approval_route"):
                return {"error": "forbidden"}
            if not process.get("approval_id"):
                approval_id = insert_approval_step_fn(conn, f"Согласование: {title}", actor.get("name", ""), payload.get("approver_name") or data.approver_name or payload.get("approver_role") or data.approver_role, item_link=f"/erp/process/{process_id}")
                created_entity = ("approval_id", approval_id, "approval", "stage_approval")
        elif target_stage == "reserve":
            if not actor.get("_can_supply_reserve"):
                return {"error": "forbidden"}
            if not process.get("reservation_id"):
                c.execute(
                    """
                    INSERT INTO stock_reservations (project_id, nomenclature_article, nomenclature_name, qty, status, comment, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, payload.get("item_article", ""), payload.get("item_name", title), _safe_float(payload.get("qty") or data.qty or 1), "reserved", payload.get("comment", ""), actor.get("email", ""), int(time.time())),
                )
                created_entity = ("reservation_id", c.lastrowid, "stock_reservation", "stage_reserve")
        elif target_stage == "purchase":
            if not actor.get("_can_supply_write"):
                return {"error": "forbidden"}
            if not process.get("purchase_id"):
                qty = _safe_float(payload.get("qty") or data.qty or 1)
                unit_price = _safe_float(payload.get("unit_price") or data.unit_price)
                if not unit_price and qty:
                    unit_price = round(amount / qty, 2) if amount else 0
                total_amount = round(qty * unit_price, 2)
                c.execute(
                    """
                    INSERT INTO purchase_orders (
                        project_id, client_id, contract_id, object_id, item_article, item_name, supplier, qty, unit, unit_price,
                        total_amount, status, expected_date, received_date, comment, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, client_id, contract_id, object_id, payload.get("item_article", ""), payload.get("item_name", title), payload.get("supplier", ""),
                        qty, payload.get("unit", "шт"), unit_price, total_amount, data.status or "ordered", due_date, "",
                        payload.get("comment", ""), actor.get("email", ""), int(time.time()), int(time.time()),
                    ),
                )
                created_entity = ("purchase_id", c.lastrowid, "purchase", "stage_purchase")
        elif target_stage == "production":
            if not actor.get("_can_production_write"):
                return {"error": "forbidden"}
            if not process.get("production_id"):
                c.execute(
                    """
                    INSERT INTO production_orders (
                        project_id, client_id, contract_id, object_id, order_name, stage, priority, planned_start, planned_finish,
                        actual_finish, progress, responsible, comment, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, client_id, contract_id, object_id, payload.get("order_name", f"Производство: {title}"), data.status or "queue",
                        "high" if process.get("request_type") == "production" else "normal", _today_display(), due_date, "", 0,
                        payload.get("responsible", ""), payload.get("comment", ""), actor.get("email", ""), int(time.time()), int(time.time()),
                    ),
                )
                created_entity = ("production_id", c.lastrowid, "production_order", "stage_production")
        elif target_stage == "shipment":
            if not actor.get("_can_sales_ship"):
                return {"error": "forbidden"}
            if not process.get("sales_doc_id"):
                c.execute(
                    """
                    INSERT INTO sales_documents_extended (
                        project_id, client_id, contract_id, object_id, doc_type, doc_number, doc_date, amount, currency, status,
                        payment_status, linked_payment_id, comment, recipient_email, sent_status, sent_at, delivered_at, confirmed_at, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, client_id, contract_id, object_id, "invoice", f"ERP-{process_id}", _today_display(), amount, currency, data.status or "issued",
                        "planned", 0, payload.get("comment", ""), payload.get("recipient_email", ""), "draft", "", "", "",
                        actor.get("email", ""), int(time.time()), int(time.time()),
                    ),
                )
                created_entity = ("sales_doc_id", c.lastrowid, "sales_document", "stage_shipment")
        elif target_stage == "payment":
            if not actor.get("_can_finance_write"):
                return {"error": "forbidden"}
            if not process.get("payment_id"):
                payment_kind = payload.get("payment_kind") or data.payment_kind or ("outgoing" if process.get("request_type") in {"purchase", "expense", "payment"} else "incoming")
                payment_status = data.status or ("planned" if target_stage == "payment" else "paid")
                paid_date = _today_display() if payment_status == "paid" else ""
                c.execute(
                    """
                    INSERT INTO finance_payments (
                        project_id, client_id, contract_id, object_id, title, kind, category, amount, currency, due_date,
                        paid_date, status, comment, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, client_id, contract_id, object_id, f"Оплата: {title}", payment_kind, "erp", amount, currency, due_date, paid_date,
                        payment_status, payload.get("comment", ""), actor.get("email", ""), int(time.time()), int(time.time()),
                    ),
                )
                payment_id = c.lastrowid
                if process.get("sales_doc_id"):
                    c.execute("UPDATE sales_documents_extended SET linked_payment_id=?, payment_status=? WHERE id=?", (payment_id, "paid" if payment_status == "paid" else "planned", process.get("sales_doc_id")))
                created_entity = ("payment_id", payment_id, "finance_payment", "stage_payment")
        elif target_stage == "done":
            if process.get("request_id"):
                c.execute("UPDATE internal_requests SET status='done', updated_at=? WHERE id=?", (int(time.time()), process.get("request_id")))
            if process.get("payment_id") and actor.get("_can_mark_paid"):
                c.execute("UPDATE finance_payments SET status='paid', paid_date=?, updated_at=? WHERE id=?", (_today_display(), int(time.time()), process.get("payment_id")))
            if process.get("production_id"):
                c.execute("UPDATE production_orders SET stage='done', progress=100, actual_finish=?, updated_at=? WHERE id=?", (_today_display(), int(time.time()), process.get("production_id")))
            if process.get("purchase_id"):
                c.execute("UPDATE purchase_orders SET status='received', received_date=?, updated_at=? WHERE id=?", (_today_display(), int(time.time()), process.get("purchase_id")))
            if process.get("sales_doc_id"):
                c.execute("UPDATE sales_documents_extended SET status='signed', payment_status='paid', updated_at=? WHERE id=?", (int(time.time()), process.get("sales_doc_id")))

    updates = {
        "payload": payload,
        "status": "done" if target_stage == "done" else ("pending" if target_stage == "approval" else "in_progress"),
        "current_stage": target_stage,
        "client_id": client_id,
        "contract_id": contract_id,
        "object_id": object_id,
        "amount": amount,
        "currency": currency,
        "due_date": due_date,
    }
    if created_entity:
        updates[created_entity[0]] = created_entity[1]
        link_erp_entities(
            process_id,
            "erp_process",
            process_id,
            created_entity[2],
            created_entity[1],
            created_entity[3],
            project_id,
            client_id,
            actor.get("email", ""),
            {"stage": target_stage, "note": data.note, "contract_id": contract_id, "object_id": object_id},
        )
        audit_log(
            f"{created_entity[2]}_created",
            actor_email=actor.get("email", ""),
            actor_name=actor.get("name", ""),
            entity_type=created_entity[2],
            entity_id=str(created_entity[1]),
            details={"process_id": process_id, "stage": target_stage, "title": title},
        )
    updated_process = update_erp_process_run(process_id, updates, actor.get("email", ""))
    audit_log(
        "erp_process_advanced",
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        entity_type="erp_process",
        entity_id=str(process_id),
        details={"target_stage": target_stage, "note": data.note, "created_entity": created_entity[2] if created_entity else ""},
    )
    assignee_name = payload.get("assignee_name", "")
    approver_name = payload.get("approver_name", "")
    if target_stage == "approval" and approver_name:
        create_notification("ERP: этап согласования", f"Процесс «{title}» ожидает твоего решения.", user_name=approver_name, category="erp", entity_type="erp_process", entity_id=str(process_id))
    if target_stage in {"purchase", "production", "shipment", "payment"} and assignee_name:
        create_notification("ERP: новый этап процесса", f"Процесс «{title}» переведен на этап «{stage_label_fn(target_stage)}».", user_name=assignee_name, category="erp", entity_type="erp_process", entity_id=str(process_id))
    record_domain_event(
        "erp_workflow",
        "process_advanced",
        entity_type="erp_process",
        entity_id=str(process_id),
        actor_email=actor.get("email", ""),
        actor_name=actor.get("name", ""),
        payload={"target_stage": target_stage, "created_entity": created_entity[2] if created_entity else "", "title": title},
    )
    return {"status": "success", "process": updated_process}
