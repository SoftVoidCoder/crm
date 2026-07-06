import json
import time
from datetime import datetime


def safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def safe_text(value) -> str:
    return str(value or "").strip()


def now_ts() -> int:
    return int(time.time())


def json_dump(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def row_dict(cursor) -> dict:
    row = cursor.fetchone()
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(zip([col[0] for col in cursor.description], row))


def row_dicts(cursor) -> list[dict]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(row) for row in rows]
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def normalize_date(value: str) -> str:
    text = safe_text(value)
    if not text:
        return ""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def policy_settings(conn) -> dict:
    row = row_dict(conn.execute("SELECT cost_method, allow_negative_stock, auto_pick_strategy FROM warehouse_policies WHERE id=1"))
    return {
        "cost_method": safe_text(row.get("cost_method")).lower() or "fifo",
        "auto_pick_strategy": safe_text(row.get("auto_pick_strategy")).lower() or "best_fit",
        "allow_negative_stock": safe_int(row.get("allow_negative_stock")),
    }


def upsert_unit_conversion(conn, data: dict, actor_email: str = "") -> int:
    now = now_ts()
    article = safe_text(data.get("article"))
    from_unit = safe_text(data.get("from_unit")) or "шт"
    to_unit = safe_text(data.get("to_unit")) or "шт"
    factor = safe_float(data.get("factor")) or 1
    existing = row_dict(conn.execute("SELECT id FROM unit_conversions WHERE article=? AND from_unit=? AND to_unit=?", (article, from_unit, to_unit)))
    if existing:
        conn.execute(
            """
            UPDATE unit_conversions
            SET factor=?, is_base=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (factor, safe_int(data.get("is_base")), safe_text(data.get("comment")), now, safe_int(existing.get("id"))),
        )
        return safe_int(existing.get("id"))
    cur = conn.execute(
        """
        INSERT INTO unit_conversions (article, from_unit, to_unit, factor, is_base, comment, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (article, from_unit, to_unit, factor, safe_int(data.get("is_base")), safe_text(data.get("comment")), actor_email, now, now),
    )
    return safe_int(getattr(cur, "lastrowid", 0)) or safe_int(row_dict(conn.execute("SELECT id FROM unit_conversions WHERE article=? AND from_unit=? AND to_unit=?", (article, from_unit, to_unit))).get("id"))


def upsert_item_package(conn, data: dict, actor_email: str = "") -> int:
    now = now_ts()
    article = safe_text(data.get("article"))
    package_code = safe_text(data.get("package_code")) or "BASE"
    existing = row_dict(conn.execute("SELECT id FROM item_packages WHERE article=? AND package_code=?", (article, package_code)))
    values = (
        article,
        package_code,
        safe_text(data.get("package_name")) or package_code,
        safe_text(data.get("unit")) or "шт",
        safe_float(data.get("qty_per_package")) or 1,
        safe_float(data.get("weight_kg")),
        safe_float(data.get("volume_m3")),
        safe_text(data.get("barcode")),
        safe_int(data.get("is_default")),
        safe_text(data.get("comment")),
        actor_email,
        now,
        now,
    )
    if existing:
        conn.execute(
            """
            UPDATE item_packages
            SET package_name=?, unit=?, qty_per_package=?, weight_kg=?, volume_m3=?, barcode=?,
                is_default=?, comment=?, updated_at=?
            WHERE id=?
            """,
            (*values[2:10], now, safe_int(existing.get("id"))),
        )
        return safe_int(existing.get("id"))
    cur = conn.execute(
        """
        INSERT INTO item_packages (
            article, package_code, package_name, unit, qty_per_package, weight_kg, volume_m3, barcode,
            is_default, comment, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return safe_int(getattr(cur, "lastrowid", 0)) or safe_int(row_dict(conn.execute("SELECT id FROM item_packages WHERE article=? AND package_code=?", (article, package_code))).get("id"))


def qty_to_base(conn, article: str, qty: float, unit: str = "", package_code: str = "", package_qty: float = 0) -> tuple[float, dict]:
    article = safe_text(article)
    unit = safe_text(unit) or "шт"
    package_code = safe_text(package_code)
    qty = safe_float(qty)
    package_qty = safe_float(package_qty)
    details = {"input_qty": qty, "input_unit": unit, "package_code": package_code, "package_qty": package_qty}
    if package_code:
        package = row_dict(conn.execute("SELECT * FROM item_packages WHERE article=? AND package_code=?", (article, package_code)))
        if package:
            base_qty = (package_qty or qty) * (safe_float(package.get("qty_per_package")) or 1)
            details.update({"package_unit": package.get("unit"), "qty_per_package": package.get("qty_per_package"), "base_qty": base_qty})
            return round(base_qty, 6), details
    conversion = row_dict(conn.execute("SELECT * FROM unit_conversions WHERE article=? AND from_unit=? ORDER BY is_base DESC, id DESC LIMIT 1", (article, unit)))
    if conversion:
        base_qty = qty * (safe_float(conversion.get("factor")) or 1)
        details.update({"to_unit": conversion.get("to_unit"), "factor": conversion.get("factor"), "base_qty": base_qty})
        return round(base_qty, 6), details
    details["base_qty"] = qty
    return round(qty, 6), details


def update_lot_expiration(conn, article: str, warehouse: str, bin_code: str, batch_code: str, serial_no: str, expiration_date: str):
    expiration = normalize_date(expiration_date)
    if not expiration:
        return
    conn.execute(
        """
        UPDATE inventory_lots
        SET lot_expiration_date=?, updated_at=?
        WHERE article=? AND warehouse=? AND bin_code=? AND batch_code=? AND serial_no=?
        """,
        (expiration, now_ts(), safe_text(article), safe_text(warehouse), safe_text(bin_code), safe_text(batch_code), safe_text(serial_no)),
    )


def receipt_cost_layer(conn, article: str, item_name: str, warehouse: str, bin_code: str, batch_code: str, serial_no: str, qty: float, unit_cost: float, actor_email: str = "", source_type: str = "", source_id: int = 0, lot_expiration_date: str = "", unit: str = "шт", details: dict | None = None) -> int:
    qty = round(safe_float(qty), 6)
    if qty <= 0:
        return 0
    unit_cost = round(safe_float(unit_cost), 6)
    amount = round(qty * unit_cost, 2)
    expiration = normalize_date(lot_expiration_date)
    now = now_ts()
    cur = conn.execute(
        """
        INSERT INTO inventory_cost_layers (
            article, item_name, warehouse, bin_code, batch_code, serial_no, lot_expiration_date,
            layer_kind, qty, remaining_qty, unit, unit_cost, amount, source_type, source_id,
            cost_method, status, details_json, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'receipt', ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
        """,
        (
            safe_text(article),
            safe_text(item_name) or safe_text(article),
            safe_text(warehouse),
            safe_text(bin_code),
            safe_text(batch_code),
            safe_text(serial_no),
            expiration,
            qty,
            qty,
            safe_text(unit) or "шт",
            unit_cost,
            amount,
            safe_text(source_type),
            safe_int(source_id),
            policy_settings(conn).get("cost_method"),
            json_dump(details or {}),
            actor_email,
            now,
            now,
        ),
    )
    update_lot_expiration(conn, article, warehouse, bin_code, batch_code, serial_no, expiration)
    return safe_int(getattr(cur, "lastrowid", 0))


def bootstrap_cost_layers(conn, article: str, actor_email: str = ""):
    article = safe_text(article)
    if not article:
        return
    existing = row_dict(conn.execute("SELECT COALESCE(SUM(remaining_qty), 0) AS qty FROM inventory_cost_layers WHERE article=? AND remaining_qty > 0", (article,)))
    if safe_float(existing.get("qty")) > 0:
        return
    item = row_dict(conn.execute("SELECT name, price, unit FROM nomenclature WHERE article=?", (article,)))
    unit_cost = safe_float(item.get("price"))
    rows = row_dicts(conn.execute(
        """
        SELECT article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date, qty
        FROM inventory_lots
        WHERE article=? AND qty > 0
        ORDER BY updated_at ASC, id ASC
        """,
        (article,),
    ))
    for row in rows:
        receipt_cost_layer(
            conn,
            article,
            item.get("name") or article,
            row.get("warehouse") or "",
            row.get("bin_code") or "",
            row.get("batch_code") or "",
            row.get("serial_no") or "",
            safe_float(row.get("qty")),
            unit_cost,
            actor_email,
            "bootstrap_inventory_lot",
            0,
            row.get("lot_expiration_date") or "",
            item.get("unit") or "шт",
            {"bootstrap": True},
        )


def average_unit_cost(conn, article: str, warehouse: str = "", bin_code: str = "") -> float:
    clauses = ["article=?", "remaining_qty > 0"]
    params = [safe_text(article)]
    if warehouse:
        clauses.append("warehouse=?")
        params.append(safe_text(warehouse))
    if bin_code:
        clauses.append("bin_code=?")
        params.append(safe_text(bin_code))
    row = row_dict(conn.execute(
        f"SELECT COALESCE(SUM(remaining_qty * unit_cost), 0) AS amount, COALESCE(SUM(remaining_qty), 0) AS qty FROM inventory_cost_layers WHERE {' AND '.join(clauses)}",
        tuple(params),
    ))
    qty = safe_float(row.get("qty"))
    return round(safe_float(row.get("amount")) / qty, 6) if qty else 0.0


def _cost_layer_order(policy: dict) -> str:
    method = policy.get("cost_method") or "fifo"
    strategy = policy.get("auto_pick_strategy") or "best_fit"
    if strategy == "fefo":
        return "CASE WHEN lot_expiration_date='' THEN 1 ELSE 0 END ASC, lot_expiration_date ASC, created_at ASC, id ASC"
    if method == "lifo":
        return "created_at DESC, id DESC"
    if strategy == "largest_first":
        return "remaining_qty DESC, created_at ASC, id ASC"
    return "created_at ASC, id ASC"


def consume_cost_layers(conn, article: str, qty: float, warehouse: str = "", bin_code: str = "", batch_code: str = "", serial_no: str = "", actor_email: str = "", source_type: str = "", source_id: int = 0, movement_id: int = 0, details: dict | None = None) -> tuple[list[dict], float]:
    qty = round(safe_float(qty), 6)
    if qty <= 0:
        return [], 0
    bootstrap_cost_layers(conn, article, actor_email)
    policy = policy_settings(conn)
    method = policy.get("cost_method") or "fifo"
    if method == "average":
        unit_cost = average_unit_cost(conn, article, warehouse, bin_code)
        return _consume_cost_layers_fifo(conn, article, qty, warehouse, bin_code, batch_code, serial_no, actor_email, source_type, source_id, movement_id, details, unit_cost_override=unit_cost)
    return _consume_cost_layers_fifo(conn, article, qty, warehouse, bin_code, batch_code, serial_no, actor_email, source_type, source_id, movement_id, details)


def _consume_cost_layers_fifo(conn, article: str, qty: float, warehouse: str, bin_code: str, batch_code: str, serial_no: str, actor_email: str, source_type: str, source_id: int, movement_id: int, details: dict | None, unit_cost_override: float = 0) -> tuple[list[dict], float]:
    policy = policy_settings(conn)
    clauses = ["article=?", "remaining_qty > 0"]
    params = [safe_text(article)]
    for field, value in (("warehouse", warehouse), ("bin_code", bin_code), ("batch_code", batch_code), ("serial_no", serial_no)):
        if safe_text(value):
            clauses.append(f"{field}=?")
            params.append(safe_text(value))
    rows = row_dicts(conn.execute(
        f"""
        SELECT *
        FROM inventory_cost_layers
        WHERE {' AND '.join(clauses)}
        ORDER BY {_cost_layer_order(policy)}
        """,
        tuple(params),
    ))
    remaining = round(safe_float(qty), 6)
    consumed = []
    now = now_ts()
    for layer in rows:
        if remaining <= 0:
            break
        available = safe_float(layer.get("remaining_qty"))
        used = min(available, remaining)
        unit_cost = safe_float(unit_cost_override) or safe_float(layer.get("unit_cost"))
        amount = round(used * unit_cost, 2)
        conn.execute(
            "UPDATE inventory_cost_layers SET remaining_qty=?, status=?, updated_at=? WHERE id=?",
            (round(available - used, 6), "closed" if available - used <= 0.000001 else "open", now, safe_int(layer.get("id"))),
        )
        conn.execute(
            """
            INSERT INTO inventory_cost_layers (
                article, item_name, warehouse, bin_code, batch_code, serial_no, lot_expiration_date,
                layer_kind, qty, remaining_qty, unit, unit_cost, amount, source_type, source_id, movement_id,
                cost_method, status, details_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'issue', ?, 0, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?, ?, ?)
            """,
            (
                safe_text(article),
                layer.get("item_name") or safe_text(article),
                layer.get("warehouse") or "",
                layer.get("bin_code") or "",
                layer.get("batch_code") or "",
                layer.get("serial_no") or "",
                layer.get("lot_expiration_date") or "",
                -round(used, 6),
                layer.get("unit") or "шт",
                unit_cost,
                -amount,
                safe_text(source_type),
                safe_int(source_id),
                safe_int(movement_id),
                policy.get("cost_method") or "fifo",
                json_dump({"source_layer_id": layer.get("id"), **(details or {})}),
                actor_email,
                now,
                now,
            ),
        )
        consumed.append({
            "layer_id": safe_int(layer.get("id")),
            "warehouse": layer.get("warehouse") or "",
            "bin_code": layer.get("bin_code") or "",
            "batch_code": layer.get("batch_code") or "",
            "serial_no": layer.get("serial_no") or "",
            "lot_expiration_date": layer.get("lot_expiration_date") or "",
            "qty": round(used, 6),
            "unit_cost": unit_cost,
            "amount": amount,
        })
        remaining = round(remaining - used, 6)
    if remaining > 0 and policy.get("allow_negative_stock"):
        unit_cost = safe_float(unit_cost_override) or average_unit_cost(conn, article) or 0
        consumed.append({"qty": remaining, "unit_cost": unit_cost, "amount": round(remaining * unit_cost, 2), "negative": True})
        remaining = 0
    return consumed, remaining


def transfer_cost_layers(conn, allocations: list[dict], article: str, item_name: str, target_warehouse: str, target_bin: str, actor_email: str = "", source_type: str = "", source_id: int = 0, lot_expiration_date: str = "") -> list[int]:
    created = []
    for allocation in allocations or []:
        qty = safe_float(allocation.get("qty"))
        unit_cost = safe_float(allocation.get("unit_cost"))
        if unit_cost <= 0:
            unit_cost = average_unit_cost(conn, article, allocation.get("warehouse") or "", allocation.get("bin_code") or "")
        created_id = receipt_cost_layer(
            conn,
            article,
            item_name,
            target_warehouse,
            target_bin,
            allocation.get("batch_code") or "",
            allocation.get("serial_no") or "",
            qty,
            unit_cost,
            actor_email=actor_email,
            source_type=source_type or "transfer",
            source_id=source_id,
            lot_expiration_date=allocation.get("lot_expiration_date") or lot_expiration_date,
            details={"source_allocation": allocation},
        )
        if created_id:
            created.append(created_id)
    return created


def costing_summary(conn, article: str = "") -> dict:
    params = []
    where = "WHERE remaining_qty > 0"
    if article:
        where += " AND article=?"
        params.append(safe_text(article))
    rows = row_dicts(conn.execute(
        f"""
        SELECT article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date,
               COALESCE(SUM(remaining_qty), 0) AS remaining_qty,
               COALESCE(SUM(remaining_qty * unit_cost), 0) AS amount,
               CASE WHEN COALESCE(SUM(remaining_qty), 0) > 0 THEN COALESCE(SUM(remaining_qty * unit_cost), 0) / SUM(remaining_qty) ELSE 0 END AS avg_unit_cost
        FROM inventory_cost_layers
        {where}
        GROUP BY article, warehouse, bin_code, batch_code, serial_no, lot_expiration_date
        ORDER BY article ASC, lot_expiration_date ASC, warehouse ASC, bin_code ASC
        """,
        tuple(params),
    ))
    return {
        "rows": rows,
        "totals": {
            "positions": len(rows),
            "remaining_qty": round(sum(safe_float(row.get("remaining_qty")) for row in rows), 6),
            "amount": round(sum(safe_float(row.get("amount")) for row in rows), 2),
        },
    }


def choose_putaway_cell(conn, article: str, qty: float, warehouse: str = "") -> dict:
    qty = safe_float(qty)
    params = []
    query = """
        SELECT c.*, COALESCE(b.qty, 0) AS current_qty
        FROM wms_cell_profiles c
        LEFT JOIN (
            SELECT warehouse, bin_code, COALESCE(SUM(qty), 0) AS qty
            FROM inventory_balances
            GROUP BY warehouse, bin_code
        ) b ON b.warehouse=c.warehouse AND b.bin_code=c.bin_code
        WHERE c.status='active'
    """
    if safe_text(warehouse):
        query += " AND c.warehouse=?"
        params.append(safe_text(warehouse))
    rows = row_dicts(conn.execute(query, tuple(params)))
    candidates = []
    for row in rows:
        capacity = safe_float(row.get("capacity_qty"))
        current = safe_float(row.get("current_qty"))
        free = max(capacity - current, 0) if capacity > 0 else 999999
        if free + 0.0001 < qty:
            continue
        candidates.append({**row, "free_qty": round(free, 6), "fit_gap": round(free - qty, 6)})
    if not candidates:
        return {}
    strategy = policy_settings(conn).get("auto_pick_strategy") or "best_fit"
    if strategy == "best_fit":
        candidates.sort(key=lambda row: (row["fit_gap"], row.get("warehouse") or "", row.get("bin_code") or ""))
    else:
        candidates.sort(key=lambda row: (-(safe_float(row.get("capacity_qty")) or row["free_qty"]), row.get("warehouse") or "", row.get("bin_code") or ""))
    return candidates[0]


def pick_lot_order_sql(policy: dict, requested_qty: float = 0) -> str:
    strategy = policy.get("auto_pick_strategy") or "best_fit"
    if strategy == "fefo":
        return "CASE WHEN lot_expiration_date='' THEN 1 ELSE 0 END ASC, lot_expiration_date ASC, updated_at ASC, id ASC"
    if strategy == "fifo" or policy.get("cost_method") == "fifo":
        return "updated_at ASC, id ASC"
    if strategy == "largest_first":
        return "qty DESC, updated_at ASC, id ASC"
    if strategy == "best_fit":
        qty = safe_float(requested_qty)
        return f"CASE WHEN qty >= {qty} THEN 0 ELSE 1 END ASC, ABS(qty - {qty}) ASC, updated_at ASC, id ASC"
    return "updated_at ASC, id ASC"
