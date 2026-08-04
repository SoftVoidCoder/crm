let purchasesDB = [];
let stockReservationsDB = [];
let salesDocsDB = [];
let productionOrdersDB = [];
let productionOperationsDB = [];
let productionBomDB = [];
let productionRoutesDB = [];
let supplySummaryDB = null;
let salesSummaryDB = null;
let productionSummaryDB = null;
let opsMasterDataDB = null;
let editingPurchaseId = 0;
let editingSalesId = 0;
let editingProductionId = 0;
let editingProductionOperationId = 0;
let editingProductionBomId = 0;
let editingProductionRouteId = 0;
let selectedProductionOrderId = 0;
let supplyListFilter = 'all';
let salesListFilter = 'all';
let productionListFilter = 'all';
window.supplyActiveWorkspaceTab = window.supplyActiveWorkspaceTab || 'purchase';
window.supplyActiveOperationMode = window.supplyActiveOperationMode || 'purchase';
window.__productionSecondaryExpanded = window.__productionSecondaryExpanded || false;
const opsEditLocks = {};

const purchaseFormFieldMap = {
    project_id: 'purchaseProjectId',
    client_id: 'purchaseClientId',
    legal_entity_id: 'purchaseLegalEntityId',
    business_unit_id: 'purchaseBusinessUnitId',
    item_name: 'purchaseItemName',
    item_article: 'purchaseItemArticle',
    supplier: 'purchaseSupplier',
    qty: 'purchaseQty',
    unit: 'purchaseUnit',
    unit_price: 'purchaseUnitPrice',
    expected_date: 'purchaseExpectedDate',
    status: { id: 'purchaseStatus', statusField: true },
    comment: 'purchaseComment',
};
const purchaseDraftFieldIds = ['purchaseProjectId', 'purchaseClientId', 'purchaseLegalEntityId', 'purchaseBusinessUnitId', 'purchaseItemName', 'purchaseItemArticle', 'purchaseSupplier', 'purchaseQty', 'purchaseUnit', 'purchaseUnitPrice', 'purchaseWarehouse', 'purchaseBinCode', 'purchaseBatchCode', 'purchaseExpectedDate', 'purchaseStatus', 'purchaseComment'];

const salesFormFieldMap = {
    project_id: 'salesProjectId',
    client_id: 'salesClientId',
    legal_entity_id: 'salesLegalEntityId',
    business_unit_id: 'salesBusinessUnitId',
    doc_type: 'salesDocType',
    doc_number: 'salesDocNumber',
    doc_date: 'salesDocDate',
    amount: 'salesAmount',
    currency: 'salesCurrency',
    status: { id: 'salesStatus', statusField: true },
    payment_status: { id: 'salesPaymentStatus', statusField: true },
    linked_payment_id: 'salesLinkedPayment',
    price_list_id: 'salesPriceListId',
    discount_percent: 'salesDiscountPercent',
    discount_amount: 'salesDiscountAmount',
    customer_order_no: 'salesCustomerOrderNo',
    shipment_status: { id: 'salesShipmentStatus', statusField: true },
    payment_due_date: 'salesPaymentDueDate',
    planned_ship_date: 'salesPlannedShipDate',
    reserve_status: { id: 'salesReserveStatus', statusField: true },
    reserve_qty: 'salesReserveQty',
    recipient_email: 'salesRecipientEmail',
    sent_status: { id: 'salesSentStatus', statusField: true },
    sent_at: 'salesSentAt',
    delivered_at: 'salesDeliveredAt',
    confirmed_at: 'salesConfirmedAt',
    comment: 'salesComment',
};

const productionOrderFieldMap = {
    project_id: 'productionProjectId',
    client_id: 'productionClientId',
    legal_entity_id: 'productionLegalEntityId',
    business_unit_id: 'productionBusinessUnitId',
    order_name: 'productionOrderName',
    responsible: 'productionResponsible',
    route_name: 'productionRouteName',
    stage: { id: 'productionStage', statusField: true },
    priority: 'productionPriority',
    planned_start: 'productionPlanStart',
    planned_finish: 'productionPlanFinish',
    actual_finish: 'productionActualFinish',
    planned_qty: 'productionPlannedQty',
    produced_qty: 'productionProducedQty',
    scrap_qty: 'productionScrapQty',
    planned_cost: 'productionPlannedCost',
    actual_cost: 'productionActualCost',
    labor_hours_plan: 'productionLaborHoursPlan',
    labor_hours_fact: 'productionLaborHoursFact',
    progress: 'productionProgress',
    comment: 'productionComment',
};
const productionDraftFieldIds = ['productionProjectId', 'productionClientId', 'productionLegalEntityId', 'productionBusinessUnitId', 'productionOrderName', 'productionResponsible', 'productionRouteName', 'productionStage', 'productionPriority', 'productionPlanStart', 'productionPlanFinish', 'productionActualFinish', 'productionPlannedQty', 'productionProducedQty', 'productionScrapQty', 'productionPlannedCost', 'productionActualCost', 'productionLaborHoursPlan', 'productionLaborHoursFact', 'productionProgress', 'productionComment'];

function bindPurchaseDraftAutosave() {
    if (typeof bindFormDraftAutosave !== 'function') return;
    bindFormDraftAutosave('purchase_order', {
        formId: 'purchaseForm',
        fieldIds: purchaseDraftFieldIds,
        entityType: 'purchase_order',
        title: 'Черновик закупки',
        sourceView: 'purchases',
        shouldSave: () => !editingPurchaseId,
        shouldRestore: () => !editingPurchaseId,
        afterRestore: () => syncOpsBusinessUnitOptions('purchaseLegalEntityId', 'purchaseBusinessUnitId'),
    });
}

function opsKnownWarehouseCell(warehouse, binCode) {
    const wh = String(warehouse || '').trim().toLowerCase();
    const bin = String(binCode || '').trim().toLowerCase();
    if (!bin) return true;
    const cells = Array.isArray(opsExtendedDB?.wmsCells) ? opsExtendedDB.wmsCells : [];
    if (!cells.length) return null;
    return cells.some(item => String(item.bin_code || '').trim().toLowerCase() === bin && (!wh || String(item.warehouse || '').trim().toLowerCase() === wh));
}

function bindPurchaseSmartHints() {
    if (typeof bindSmartFieldHints !== 'function') return;
    bindSmartFieldHints('purchaseForm', [
        {
            field: 'purchaseExpectedDate',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'План поставки нужен в формате дд.мм.гггг.' },
        },
        {
            field: 'purchaseUnitPrice',
            validate: value => {
                if (!String(value || '').trim()) return null;
                const price = Number(String(value).replace(',', '.')) || 0;
                if (!price) return { tone: 'error', message: 'Цена должна быть числом больше нуля.' };
                return { tone: 'hint', message: 'Если цена включает НДС, проверь это в счёте поставщика перед оплатой.' };
            },
        },
        {
            field: 'purchaseBinCode',
            validate: value => {
                const bin = String(value || '').trim();
                if (!bin) return null;
                const known = opsKnownWarehouseCell(document.getElementById('purchaseWarehouse')?.value, bin);
                if (known === false) return { tone: 'warning', message: 'Такая складская ячейка не найдена в WMS. Проверь код или сначала заведи ячейку.' };
                if (known === null) return { tone: 'hint', message: 'Ячейка будет записана как текст. WMS-справочник пока пуст.' };
                return { tone: 'hint', message: 'Ячейка найдена в WMS.' };
            },
        },
        {
            field: 'purchaseWarehouse',
            validate: () => {
                const bin = document.getElementById('purchaseBinCode')?.value || '';
                if (!bin) return null;
                const known = opsKnownWarehouseCell(document.getElementById('purchaseWarehouse')?.value, bin);
                if (known === false) window.setSmartFieldHint('purchaseBinCode', 'Такая складская ячейка не найдена для выбранного склада.', 'warning', 'purchaseForm');
                else if (known === true) window.setSmartFieldHint('purchaseBinCode', 'Ячейка найдена в WMS.', 'hint', 'purchaseForm');
                return null;
            },
        },
    ]);
}

function bindProductionDraftAutosave() {
    if (typeof bindFormDraftAutosave !== 'function') return;
    bindFormDraftAutosave('production_order', {
        formId: 'productionOrderForm',
        fieldIds: productionDraftFieldIds,
        entityType: 'production_order',
        title: 'Черновик производственного заказа',
        sourceView: 'production',
        shouldSave: () => !editingProductionId,
        shouldRestore: () => !editingProductionId,
        afterRestore: () => syncOpsBusinessUnitOptions('productionLegalEntityId', 'productionBusinessUnitId'),
    });
}

function bindProductionSmartHints() {
    if (typeof bindSmartFieldHints !== 'function') return;
    bindSmartFieldHints('productionOrderForm', [
        {
            field: 'productionPlanStart',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'Плановый старт нужен в формате дд.мм.гггг.' },
        },
        {
            field: 'productionPlanFinish',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'Плановый финиш нужен в формате дд.мм.гггг.' },
        },
        {
            field: 'productionActualFinish',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'Факт завершения нужен в формате дд.мм.гггг.' },
        },
    ]);
}

const opsBulkSelections = window.opsBulkSelections || {
    supply: new Set(),
    sales: new Set(),
    production: new Set(),
};
window.opsBulkSelections = opsBulkSelections;

function getOpsBulkSet(scope) {
    if (!opsBulkSelections[scope]) opsBulkSelections[scope] = new Set();
    return opsBulkSelections[scope];
}

function getOpsBulkIds(scope) {
    return Array.from(getOpsBulkSet(scope)).map(Number).filter(Boolean);
}

function clearOpsBulkSelection(scope) {
    getOpsBulkSet(scope).clear();
}

function pruneOpsBulkSelection(scope, rows) {
    const validIds = new Set((rows || []).map(item => Number(item.id || 0)).filter(Boolean));
    const selection = getOpsBulkSet(scope);
    Array.from(selection).forEach(id => {
        if (!validIds.has(Number(id))) selection.delete(id);
    });
}

function toggleOpsBulkSelection(scope, id, checked) {
    const selection = getOpsBulkSet(scope);
    const numericId = Number(id || 0);
    if (!numericId) return;
    if (checked) selection.add(numericId);
    else selection.delete(numericId);
    renderOpsBulkToolbar(scope);
}

function toggleOpsBulkSelectionAll(scope, ids, checked) {
    const selection = getOpsBulkSet(scope);
    (Array.isArray(ids) ? ids : []).map(Number).filter(Boolean).forEach(id => {
        if (checked) selection.add(id);
        else selection.delete(id);
    });
    if (scope === 'supply') renderSupply();
    else if (scope === 'sales') renderSales();
    else if (scope === 'production') renderProduction();
}

function renderOpsBulkCheckbox(scope, id) {
    const numericId = Number(id || 0);
    const checked = getOpsBulkSet(scope).has(numericId) ? 'checked' : '';
    return `<input type="checkbox" class="bulk-row-checkbox" ${checked} aria-label="Выбрать строку" onchange="toggleOpsBulkSelection('${scope}', ${numericId}, this.checked)">`;
}

function renderOpsBulkMaster(scope, rows) {
    const ids = (rows || []).map(item => Number(item.id || 0)).filter(Boolean);
    const selection = getOpsBulkSet(scope);
    const checked = ids.length && ids.every(id => selection.has(id)) ? 'checked' : '';
    return `<input type="checkbox" class="bulk-row-checkbox" ${checked} aria-label="Выбрать все строки" onchange="toggleOpsBulkSelectionAll('${scope}', [${ids.join(',')}], this.checked)">`;
}

function getOpsBulkRows(scope) {
    const ids = new Set(getOpsBulkIds(scope));
    const source = scope === 'supply'
        ? purchasesDB
        : scope === 'sales'
            ? salesDocsDB
            : productionOrdersDB;
    return (source || []).filter(item => ids.has(Number(item.id || 0)));
}

function getOpsBulkVisibleRows(scope) {
    if (scope === 'supply') return getVisiblePurchases();
    if (scope === 'sales') return getVisibleSalesDocs();
    if (scope === 'production') return getVisibleProductionOrders();
    return [];
}

function selectOpsBulkVisible(scope) {
    const rows = getOpsBulkVisibleRows(scope);
    const selection = getOpsBulkSet(scope);
    rows.forEach(item => {
        const id = Number(item.id || 0);
        if (id) selection.add(id);
    });
    if (scope === 'supply') renderSupply();
    else if (scope === 'sales') renderSales();
    else if (scope === 'production') renderProduction();
}

function opsBulkStatusOptions(scope) {
    const options = {
        supply: [
            ['planned', 'План'],
            ['ordered', 'Заказано'],
            ['in_transit', 'В пути'],
            ['received', 'Получено'],
        ],
        sales: [
            ['draft', 'Черновик'],
            ['issued', 'Выставлен'],
            ['signed', 'Подписан'],
            ['closed', 'Закрыт'],
        ],
        production: [
            ['queue', 'Очередь'],
            ['in_work', 'В работе'],
            ['otk', 'ОТК'],
            ['done', 'Готово'],
        ],
    };
    return (options[scope] || []).map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
}

function opsBulkTitle(scope) {
    return {
        supply: 'Закупки',
        sales: 'Продажи',
        production: 'Производство',
    }[scope] || 'Массовые действия';
}

function opsBulkEntityType(scope) {
    return {
        supply: 'purchase_order',
        sales: 'sales_document',
        production: 'production_order',
    }[scope] || '';
}

function renderOpsBulkToolbar(scope) {
    const mount = document.getElementById(`${scope}BulkActionsMount`);
    if (!mount) return;
    const rows = getOpsBulkRows(scope);
    const selectedCount = rows.length;
    mount.innerHTML = `
        <div class="bulk-actions-bar ${selectedCount ? 'is-active' : ''}">
            <div class="bulk-actions-count">Выбрано: ${selectedCount}</div>
            <button class="btn-secondary" onclick="selectOpsBulkVisible('${scope}')">Выбрать видимые</button>
            <select id="${scope}BulkStatus" class="auth-input bulk-actions-select" ${selectedCount ? '' : 'disabled'}>
                ${opsBulkStatusOptions(scope)}
            </select>
            <button class="btn-secondary" onclick="applyOpsBulkStatus('${scope}')" ${selectedCount ? '' : 'disabled'}>Сменить статус</button>
            <input id="${scope}BulkResponsible" class="auth-input bulk-actions-input" placeholder="Ответственный" ${selectedCount ? '' : 'disabled'}>
            <button class="btn-secondary" onclick="assignOpsBulkResponsible('${scope}')" ${selectedCount ? '' : 'disabled'}>Назначить</button>
            <button class="btn-secondary" onclick="sendOpsBulkToOneC('${scope}')" ${selectedCount ? '' : 'disabled'}>В 1C</button>
            <button class="btn-secondary" onclick="exportOpsBulkSelection('${scope}')" ${selectedCount ? '' : 'disabled'}>Экспорт</button>
            <button class="btn-danger" onclick="deleteOpsBulkSelection('${scope}')" ${selectedCount ? '' : 'disabled'}>Удалить</button>
            <button class="btn-secondary" onclick="clearOpsBulkAndRender('${scope}')" ${selectedCount ? '' : 'disabled'}>Снять выбор</button>
        </div>
    `;
}

function clearOpsBulkAndRender(scope) {
    clearOpsBulkSelection(scope);
    if (scope === 'supply') renderSupply();
    else if (scope === 'sales') renderSales();
    else if (scope === 'production') renderProduction();
}

function purchaseBulkPayload(item, overrides = {}) {
    return {
        project_id: Number(item.project_id || 0),
        client_id: Number(item.client_id || 0),
        contract_id: Number(item.contract_id || 0),
        object_id: Number(item.object_id || 0),
        legal_entity_id: Number(item.legal_entity_id || 0),
        business_unit_id: Number(item.business_unit_id || 0),
        item_name: item.item_name || '',
        item_article: item.item_article || '',
        supplier: item.supplier || '',
        supplier_id: Number(item.supplier_id || 0),
        qty: Number(item.qty || 0),
        unit: item.unit || 'шт',
        unit_price: Number(item.unit_price || 0),
        planned_unit_price: Number(item.planned_unit_price || 0),
        expected_date: item.expected_date || '',
        planned_delivery_date: item.planned_delivery_date || item.expected_date || '',
        received_date: item.received_date || '',
        delivered_qty: Number(item.delivered_qty || 0),
        request_status: item.request_status || 'draft',
        approval_status: item.approval_status || 'not_required',
        schedule_status: item.schedule_status || 'planned',
        lead_time_days: Number(item.lead_time_days || 0),
        status: item.status || 'planned',
        comment: item.comment || '',
        ...overrides,
    };
}

function salesBulkPayload(item, overrides = {}) {
    return {
        project_id: Number(item.project_id || 0),
        client_id: Number(item.client_id || 0),
        contract_id: Number(item.contract_id || 0),
        object_id: Number(item.object_id || 0),
        legal_entity_id: Number(item.legal_entity_id || 0),
        business_unit_id: Number(item.business_unit_id || 0),
        doc_type: item.doc_type || 'invoice',
        doc_number: item.doc_number || '',
        doc_date: item.doc_date || '',
        amount: Number(item.amount || 0),
        currency: item.currency || 'RUB',
        status: item.status || 'draft',
        payment_status: item.payment_status || 'planned',
        linked_payment_id: Number(item.linked_payment_id || 0),
        price_list_id: Number(item.price_list_id || 0),
        discount_percent: Number(item.discount_percent || 0),
        discount_amount: Number(item.discount_amount || 0),
        customer_order_no: item.customer_order_no || '',
        shipment_status: item.shipment_status || 'not_shipped',
        payment_due_date: item.payment_due_date || '',
        planned_ship_date: item.planned_ship_date || '',
        shipped_at: item.shipped_at || '',
        reserve_status: item.reserve_status || 'none',
        reserve_qty: Number(item.reserve_qty || 0),
        recipient_email: item.recipient_email || '',
        sent_status: item.sent_status || 'draft',
        sent_at: item.sent_at || '',
        delivered_at: item.delivered_at || '',
        confirmed_at: item.confirmed_at || '',
        comment: item.comment || '',
        ...overrides,
    };
}

function productionBulkPayload(item, overrides = {}) {
    return {
        project_id: Number(item.project_id || 0),
        client_id: Number(item.client_id || 0),
        contract_id: Number(item.contract_id || 0),
        object_id: Number(item.object_id || 0),
        legal_entity_id: Number(item.legal_entity_id || 0),
        business_unit_id: Number(item.business_unit_id || 0),
        order_name: item.order_name || '',
        responsible: item.responsible || '',
        route_name: item.route_name || '',
        stage: item.stage || 'queue',
        priority: item.priority || 'normal',
        planned_start: item.planned_start || '',
        planned_finish: item.planned_finish || '',
        actual_finish: item.actual_finish || '',
        planned_qty: Number(item.planned_qty || item.planned_qty_total || 0),
        produced_qty: Number(item.produced_qty || item.produced_qty_total || 0),
        scrap_qty: Number(item.scrap_qty || item.scrap_qty_total || 0),
        planned_cost: Number(item.planned_cost || item.planned_cost_total || 0),
        actual_cost: Number(item.actual_cost || item.actual_cost_total || 0),
        labor_hours_plan: Number(item.labor_hours_plan || 0),
        labor_hours_fact: Number(item.labor_hours_fact || 0),
        progress: Number(item.progress || 0),
        comment: item.comment || '',
        ...overrides,
    };
}

async function applyOpsBulkStatus(scope) {
    const statusValue = document.getElementById(`${scope}BulkStatus`)?.value || '';
    const rows = getOpsBulkRows(scope);
    if (!rows.length) return customAlert('Сначала выбери строки.');
    if (!statusValue) return customAlert('Выбери статус для массового изменения.');
    for (const row of rows) {
        const endpoint = scope === 'supply'
            ? `/purchases/${row.id}`
            : scope === 'sales'
                ? `/sales/documents/${row.id}`
                : `/production/orders/${row.id}`;
        const payload = scope === 'supply'
            ? purchaseBulkPayload(row, { status: statusValue })
            : scope === 'sales'
                ? salesBulkPayload(row, { status: statusValue })
                : productionBulkPayload(row, { stage: statusValue });
        const res = await apiCall(endpoint, 'PUT', payload);
        if (!res || res.error) return customAlert(`Не удалось обновить строку #${row.id}.`);
    }
    clearOpsBulkSelection(scope);
    if (scope === 'supply') await renderSupply();
    else if (scope === 'sales') await renderSales();
    else await renderProduction();
    showToast(opsBulkTitle(scope), `Статус обновлён у записей: ${rows.length}`);
}

async function assignOpsBulkResponsible(scope = 'production') {
    const responsible = document.getElementById(`${scope}BulkResponsible`)?.value.trim() || '';
    const rows = getOpsBulkRows(scope);
    if (!rows.length) return customAlert('Сначала выбери строки.');
    if (!responsible) return customAlert('Укажи ответственного.');
    const res = await apiCall('/workbench/bulk_actions', 'POST', {
        entity_type: opsBulkEntityType(scope),
        action: 'assign',
        ids: rows.map(row => Number(row.id)).filter(Boolean),
        assignee: responsible,
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось назначить ответственного.');
    clearOpsBulkSelection(scope);
    if (scope === 'supply') await renderSupply();
    else if (scope === 'sales') await renderSales();
    else await renderProduction();
    showToast(opsBulkTitle(scope), `Ответственный назначен: ${res.count || rows.length}`);
}

async function deleteOpsBulkSelection(scope) {
    const rows = getOpsBulkRows(scope);
    if (!rows.length) return customAlert('Сначала выбери строки.');
    const ok = await customConfirm(`Удалить выбранные записи (${rows.length})?`);
    if (!ok) return;
    const res = await apiCall('/workbench/bulk_actions', 'POST', {
        entity_type: opsBulkEntityType(scope),
        action: 'delete',
        ids: rows.map(row => Number(row.id)).filter(Boolean),
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось удалить выбранные записи.');
    clearOpsBulkSelection(scope);
    if (scope === 'supply') await renderSupply();
    else if (scope === 'sales') await renderSales();
    else await renderProduction();
    showToast(opsBulkTitle(scope), `Удалено записей: ${res.count || rows.length}`);
}

async function sendOpsBulkToOneC(scope) {
    const rows = getOpsBulkRows(scope);
    if (!rows.length) return customAlert('Сначала выбери строки.');
    const res = await apiCall('/workbench/bulk_actions', 'POST', {
        entity_type: opsBulkEntityType(scope),
        action: 'send_1c',
        ids: rows.map(row => Number(row.id)).filter(Boolean),
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось поставить записи в очередь 1C.');
    showToast(opsBulkTitle(scope), `В очередь 1C поставлено: ${res.queued ?? res.count ?? 0}`);
}

function exportOpsBulkSelection(scope) {
    const rows = getOpsBulkRows(scope);
    if (!rows.length) return customAlert('Сначала выбери строки для экспорта.');
    if (typeof XLSX === 'undefined') return customAlert('Модуль экспорта пока не загрузился. Обнови страницу и попробуй ещё раз.');
    const exportRows = rows.map(item => {
        if (scope === 'supply') {
            return {
                'Позиция': item.item_name || '',
                'Артикул': item.item_article || '',
                'Поставщик': item.supplier || '',
                'Количество': Number(item.qty || 0),
                'Сумма': Number(item.total_amount || 0),
                'Срок': item.expected_date || '',
                'Статус': financeStatusLabel(item.status),
            };
        }
        if (scope === 'sales') {
            return {
                'Документ': `${salesDocLabel(item.doc_type)} ${item.doc_number || ''}`,
                'Дата': item.doc_date || '',
                'Контрагент': item.client_name || '',
                'Сумма': Number(item.amount || 0),
                'Статус': financeStatusLabel(item.status),
                'Оплата': financeStatusLabel(item.payment_status),
            };
        }
        return {
            'Заказ': item.order_name || '',
            'Ответственный': item.responsible || '',
            'Стадия': productionStageLabel(item.stage),
            'Приоритет': productionPriorityLabel(item.priority),
            'Финиш': item.planned_finish || '',
            'Прогресс': Number(item.progress || 0),
        };
    });
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, opsBulkTitle(scope));
    XLSX.writeFile(workbook, `korda-${scope}-selected-${new Date().toISOString().slice(0, 10)}.xlsx`);
    showToast(opsBulkTitle(scope), `Выгружено строк: ${rows.length}`);
}

const wmsBulkSelections = window.wmsBulkSelections || {
    wms_putaway_task: new Set(),
    wms_pick_wave: new Set(),
    wms_pick_task: new Set(),
    wms_cycle_count: new Set(),
};
window.wmsBulkSelections = wmsBulkSelections;

function wmsBulkRowsByType(entityType) {
    const map = {
        wms_putaway_task: opsExtendedDB.wmsPutawayTasks || [],
        wms_pick_wave: opsExtendedDB.wmsPickWaves || [],
        wms_pick_task: opsExtendedDB.wmsPickTasks || [],
        wms_cycle_count: opsExtendedDB.wmsCycleCounts || [],
    };
    const selected = wmsBulkSelections[entityType] || new Set();
    return (map[entityType] || []).filter(row => selected.has(Number(row.id)));
}

function getWmsBulkAllRows() {
    return Object.keys(wmsBulkSelections).flatMap(entityType => wmsBulkRowsByType(entityType).map(row => ({ ...row, entity_type: entityType })));
}

function toggleWmsBulkSelection(entityType, id, checked) {
    if (!wmsBulkSelections[entityType]) wmsBulkSelections[entityType] = new Set();
    if (checked) wmsBulkSelections[entityType].add(Number(id));
    else wmsBulkSelections[entityType].delete(Number(id));
    renderWmsBulkToolbar();
}

function renderWmsBulkCheckbox(entityType, id) {
    if (!wmsBulkSelections[entityType]) wmsBulkSelections[entityType] = new Set();
    const checked = wmsBulkSelections[entityType].has(Number(id)) ? 'checked' : '';
    return `<input type="checkbox" class="bulk-row-checkbox" ${checked} aria-label="Выбрать WMS строку" onchange="toggleWmsBulkSelection('${entityType}', ${Number(id || 0)}, this.checked)">`;
}

function clearWmsBulkSelection() {
    Object.values(wmsBulkSelections).forEach(set => set.clear());
    refreshSupplyExtended();
}

function renderWmsBulkToolbar() {
    const mount = document.getElementById('wmsBulkActionsMount');
    if (!mount) return;
    const rows = getWmsBulkAllRows();
    const count = rows.length;
    mount.innerHTML = `
        <div class="bulk-actions-bar ${count ? 'is-active' : ''}">
            <div class="bulk-actions-count">WMS выбрано: ${count}</div>
            <select id="wmsBulkStatus" class="auth-input bulk-actions-select" ${count ? '' : 'disabled'}>
                <option value="open">Открыто</option>
                <option value="in_progress">В работе</option>
                <option value="released">Выпущено</option>
                <option value="done">Готово</option>
                <option value="closed">Закрыто</option>
                <option value="cancelled">Отменено</option>
            </select>
            <button class="btn-secondary" onclick="applyWmsBulkStatus()" ${count ? '' : 'disabled'}>Сменить статус</button>
            <input id="wmsBulkAssignee" class="auth-input bulk-actions-input" placeholder="Ответственный" ${count ? '' : 'disabled'}>
            <button class="btn-secondary" onclick="assignWmsBulk()" ${count ? '' : 'disabled'}>Назначить</button>
            <button class="btn-secondary" onclick="sendWmsBulkToOneC()" ${count ? '' : 'disabled'}>В 1C</button>
            <button class="btn-secondary" onclick="exportWmsBulkSelection()" ${count ? '' : 'disabled'}>Экспорт</button>
            <button class="btn-danger" onclick="deleteWmsBulkSelection()" ${count ? '' : 'disabled'}>Удалить</button>
            <button class="btn-secondary" onclick="clearWmsBulkSelection()" ${count ? '' : 'disabled'}>Снять выбор</button>
        </div>
    `;
}

async function applyWmsBulkGrouped(action, extra = {}) {
    const groups = Object.keys(wmsBulkSelections)
        .map(entityType => ({ entityType, ids: wmsBulkRowsByType(entityType).map(row => Number(row.id)).filter(Boolean) }))
        .filter(group => group.ids.length);
    if (!groups.length) return customAlert('Сначала выбери WMS строки.');
    let total = 0;
    for (const group of groups) {
        const res = await apiCall('/workbench/bulk_actions', 'POST', {
            entity_type: group.entityType,
            action,
            ids: group.ids,
            ...extra,
        });
        if (!res || res.error) return customAlert(res?.message || 'Массовое действие WMS не выполнено.');
        total += Number(res.count ?? res.queued ?? group.ids.length);
    }
    return total;
}

async function applyWmsBulkStatus() {
    const status = document.getElementById('wmsBulkStatus')?.value || '';
    if (!status) return customAlert('Выбери статус WMS.');
    const total = await applyWmsBulkGrouped('update_status', { status });
    if (total === undefined) return;
    clearWmsBulkSelection();
    showToast('WMS', `Статус обновлён: ${total}`);
}

async function assignWmsBulk() {
    const assignee = document.getElementById('wmsBulkAssignee')?.value.trim() || '';
    if (!assignee) return customAlert('Укажи ответственного.');
    const total = await applyWmsBulkGrouped('assign', { assignee });
    if (total === undefined) return;
    clearWmsBulkSelection();
    showToast('WMS', `Ответственный назначен: ${total}`);
}

async function deleteWmsBulkSelection() {
    const rows = getWmsBulkAllRows();
    if (!rows.length) return customAlert('Сначала выбери WMS строки.');
    if (!(await customConfirm(`Удалить выбранные WMS строки (${rows.length})?`))) return;
    const total = await applyWmsBulkGrouped('delete');
    if (total === undefined) return;
    clearWmsBulkSelection();
    showToast('WMS', `Удалено строк: ${total}`);
}

async function sendWmsBulkToOneC() {
    const total = await applyWmsBulkGrouped('send_1c');
    if (total === undefined) return;
    showToast('WMS', `В очередь 1C поставлено: ${total}`);
}

function exportWmsBulkSelection() {
    const rows = getWmsBulkAllRows();
    if (!rows.length) return customAlert('Сначала выбери WMS строки.');
    if (typeof XLSX === 'undefined') return customAlert('Модуль экспорта пока не загрузился.');
    const exportRows = rows.map(row => ({
        'Тип': row.entity_type,
        'ID': row.id,
        'Артикул': row.article || '',
        'Наименование': row.item_name || row.wave_number || row.count_number || '',
        'Склад': row.warehouse || row.source_warehouse || '',
        'Ячейка': row.bin_code || row.source_bin || '',
        'Статус': row.status || '',
        'Ответственный': row.assigned_to || '',
        'Количество': Number(row.qty || row.qty_total || 0),
    }));
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'WMS');
    XLSX.writeFile(workbook, `korda-wms-selected-${new Date().toISOString().slice(0, 10)}.xlsx`);
    showToast('WMS', `Выгружено строк: ${rows.length}`);
}

const productionOperationFieldMap = {
    sequence_no: 'productionOperationSequence',
    operation_name: 'productionOperationName',
    work_center: 'productionOperationWorkCenter',
    status: { id: 'productionOperationStatus', statusField: true },
    planned_hours: 'productionOperationPlannedHours',
    actual_hours: 'productionOperationActualHours',
    planned_qty: 'productionOperationPlannedQty',
    completed_qty: 'productionOperationCompletedQty',
    scrap_qty: 'productionOperationScrapQty',
    labor_rate: 'productionOperationLaborRate',
    material_cost: 'productionOperationMaterialCost',
    overhead_cost: 'productionOperationOverheadCost',
    started_at: 'productionOperationStartedAt',
    finished_at: 'productionOperationFinishedAt',
    note: 'productionOperationNote',
};

const productionBomFieldMap = {
    article: 'productionBomArticle',
    item_name: 'productionBomName',
    unit: 'productionBomUnit',
    qty_per_unit: 'productionBomQtyPerUnit',
    planned_qty: 'productionBomPlannedQty',
    actual_qty: 'productionBomActualQty',
    unit_cost: 'productionBomUnitCost',
    warehouse: 'productionBomWarehouse',
    bin_code: 'productionBomBin',
    note: 'productionBomNote',
};

const productionRouteFieldMap = {
    sequence_no: 'productionRouteSequence',
    operation_name: 'productionRouteOperation',
    work_center: 'productionRouteWorkCenter',
    planned_hours: 'productionRoutePlannedHours',
    planned_qty: 'productionRoutePlannedQty',
    labor_rate: 'productionRouteLaborRate',
    note: 'productionRouteNote',
};

async function applyOpsFieldPermissions() {
    if (typeof applyFieldPermissionsWithFeedback === 'function') {
        await Promise.all([
            applyFieldPermissionsWithFeedback('supply', 'purchase_order', purchaseFormFieldMap, 'supplyPolicyBanner'),
            applyFieldPermissionsWithFeedback('sales', 'sales_document', salesFormFieldMap, 'salesPolicyBanner'),
            applyFieldPermissionsWithFeedback('production', 'production_order', productionOrderFieldMap, 'productionPolicyBanner'),
        ]);
    } else if (typeof applyFieldPermissionsToForm === 'function') {
        applyFieldPermissionsToForm('supply', 'purchase_order', purchaseFormFieldMap);
        applyFieldPermissionsToForm('sales', 'sales_document', salesFormFieldMap);
        applyFieldPermissionsToForm('production', 'production_order', productionOrderFieldMap);
    }
    if (typeof applyFieldPermissionsToForm === 'function') {
        applyFieldPermissionsToForm('production', 'production_operation', productionOperationFieldMap);
        applyFieldPermissionsToForm('production', 'production_bom_item', productionBomFieldMap);
        applyFieldPermissionsToForm('production', 'production_route_template', productionRouteFieldMap);
    }
}

async function releaseOpsEditLock(entityType, force = 0) {
    const entityId = Number(opsEditLocks[entityType] || 0);
    if (!entityId) return;
    await apiCall('/locks/release', 'POST', {
        entity_type: entityType,
        entity_id: String(entityId),
        force: Number(force || 0),
    });
    delete opsEditLocks[entityType];
}

async function acquireOpsEditLock(entityType, entityId) {
    await releaseOpsEditLock(entityType);
    if (!entityId) return true;
    const res = await apiCall('/locks/acquire', 'POST', {
        entity_type: entityType,
        entity_id: String(entityId),
        force: 0,
    });
    if (!res || res.error) {
        const owner = res?.lock?.actor_name || res?.lock?.actor_email || 'другим пользователем';
        await customAlert(`Запись ${entityType} сейчас редактируется ${owner}.`);
        return false;
    }
    opsEditLocks[entityType] = Number(entityId || 0);
    return true;
}

async function loadOpsData() {
    const [supplySummary, purchases, reservations, salesSummary, salesDocs, productionSummary, productionOrders, productionOperations, productionBom, productionRoutes, stockDiscrepancies, financePayments, masterData] = await Promise.all([
        apiCall('/supply/summary'),
        apiCall('/purchases'),
        apiCall('/stock/reservations'),
        apiCall('/sales/summary'),
        apiCall('/sales/documents'),
        apiCall('/production/summary'),
        apiCall('/production/orders'),
        apiCall('/production/operations'),
        apiCall('/production/bom'),
        apiCall('/production/routes'),
        apiCall('/stock/discrepancy_acts'),
        apiCall('/finance/payments'),
        apiCall('/finance/master_data'),
    ]);
    supplySummaryDB = supplySummary && !supplySummary.error ? supplySummary : null;
    purchasesDB = Array.isArray(purchases) ? purchases : [];
    stockReservationsDB = Array.isArray(reservations) ? reservations : [];
    salesSummaryDB = salesSummary && !salesSummary.error ? salesSummary : null;
    salesDocsDB = Array.isArray(salesDocs) ? salesDocs : [];
    productionSummaryDB = productionSummary && !productionSummary.error ? productionSummary : null;
    productionOrdersDB = Array.isArray(productionOrders) ? productionOrders : [];
    productionOperationsDB = Array.isArray(productionOperations) ? productionOperations : [];
    productionBomDB = Array.isArray(productionBom) ? productionBom : [];
    productionRoutesDB = Array.isArray(productionRoutes) ? productionRoutes : [];
    stockDiscrepancyActsDB = Array.isArray(stockDiscrepancies) ? stockDiscrepancies : [];
    if (Array.isArray(financePayments)) financePaymentsDB = financePayments;
    opsMasterDataDB = masterData && !masterData.error ? masterData : null;
    if (opsMasterDataDB && typeof financeMasterDataDB !== 'undefined') financeMasterDataDB = opsMasterDataDB;
}

function populateOpsSelects() {
    const projectOptions = `<option value="0">Без проекта</option>${projectsDB.map(project => `<option value="${project.id}">${project.contract || 'Без договора'} · ${project.name}</option>`).join('')}`;
    const clientOptions = `<option value="0">Без контрагента</option>${clientsDB.map(client => `<option value="${client.id}">${client.name}</option>`).join('')}`;
    ['purchaseProjectId', 'salesProjectId', 'productionProjectId'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = projectOptions;
    });
    ['purchaseClientId', 'salesClientId', 'productionClientId'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = clientOptions;
    });
    const legalOptions = `<option value="0">Юрлицо</option>${(opsMasterDataDB?.legal_entities || []).map(item => `<option value="${item.id}">${item.short_name || item.name}</option>`).join('')}`;
    ['purchaseLegalEntityId', 'salesLegalEntityId', 'productionLegalEntityId'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = legalOptions;
    });
    const purchaseLegal = document.getElementById('purchaseLegalEntityId');
    if (purchaseLegal) purchaseLegal.onchange = () => syncOpsBusinessUnitOptions('purchaseLegalEntityId', 'purchaseBusinessUnitId');
    const salesLegal = document.getElementById('salesLegalEntityId');
    if (salesLegal) salesLegal.onchange = () => syncOpsBusinessUnitOptions('salesLegalEntityId', 'salesBusinessUnitId');
    const productionLegal = document.getElementById('productionLegalEntityId');
    if (productionLegal) productionLegal.onchange = () => syncOpsBusinessUnitOptions('productionLegalEntityId', 'productionBusinessUnitId');
    syncOpsBusinessUnitOptions('purchaseLegalEntityId', 'purchaseBusinessUnitId');
    syncOpsBusinessUnitOptions('salesLegalEntityId', 'salesBusinessUnitId');
    syncOpsBusinessUnitOptions('productionLegalEntityId', 'productionBusinessUnitId');
    const linkedPayment = document.getElementById('salesLinkedPayment');
    if (linkedPayment) {
        linkedPayment.innerHTML = `<option value="0">Без связанной оплаты</option>${financePaymentsDB.map(item => `
            <option value="${item.id}">${item.title} · ${formatMoney(item.amount, item.currency)}</option>
        `).join('')}`;
    }
    const salesPriceList = document.getElementById('salesPriceListId');
    if (salesPriceList) {
        const currentValue = salesPriceList.value || '0';
        salesPriceList.innerHTML = `<option value="0">Прайс-лист</option>${(opsExtendedDB.priceLists || []).map(item => `
            <option value="${item.id}">${item.name}${item.item_article ? ` · ${item.item_article}` : ''}</option>
        `).join('')}`;
        salesPriceList.value = currentValue;
    }
    const salesClient = document.getElementById('salesClientId');
    if (salesClient && !salesClient.dataset.termsBound) {
        salesClient.addEventListener('change', () => applySalesClientTerms());
        salesClient.dataset.termsBound = '1';
    }
}

function syncOpsBusinessUnitOptions(legalEntityId, businessUnitId, preferredValue = 0) {
    const legalEntity = Number(document.getElementById(legalEntityId)?.value || 0);
    const units = (opsMasterDataDB?.business_units || []).filter(item => !legalEntity || Number(item.legal_entity_id || 0) === legalEntity);
    const target = document.getElementById(businessUnitId);
    if (!target) return;
    target.innerHTML = `<option value="0">Подразделение</option>${units.map(item => `<option value="${item.id}">${item.name}</option>`).join('')}`;
    const fallback = preferredValue || units[0]?.id || 0;
    target.value = String(fallback);
}

function addDaysToDisplayDate(days, baseValue = '') {
    const raw = String(baseValue || '').trim();
    let baseDate = new Date();
    if (/^\d{2}\.\d{2}\.\d{4}$/.test(raw)) {
        const [dd, mm, yyyy] = raw.split('.');
        baseDate = new Date(Number(yyyy), Number(mm) - 1, Number(dd));
    }
    baseDate.setDate(baseDate.getDate() + Number(days || 0));
    return `${String(baseDate.getDate()).padStart(2, '0')}.${String(baseDate.getMonth() + 1).padStart(2, '0')}.${baseDate.getFullYear()}`;
}

function purchaseStatusClass(status) {
    if (status === 'received') return 'status-completed';
    if (status === 'in_transit') return 'status-active';
    return 'status-archived';
}

function salesDocLabel(type) {
    return { invoice: 'Счет', act: 'Акт', upd: 'УПД', invoice_fact: 'Счет-фактура' }[type] || type || 'Документ';
}

function salesSentLabel(status) {
    return {
        draft: 'Не отправлен',
        sent: 'Отправлен',
        delivered: 'Доставлен',
        confirmed: 'Подтвержден',
    }[status] || status || 'Не отправлен';
}

function salesSentClass(status) {
    if (status === 'confirmed' || status === 'delivered') return 'status-completed';
    if (status === 'sent') return 'status-active';
    return 'status-archived';
}

function productionStageLabel(stage) {
    return { queue: 'Очередь', in_work: 'В работе', in_progress: 'В работе', otk: 'ОТК', done: 'Готово' }[stage] || opsDisplayStatus(stage, 'Статус');
}

function productionPriorityLabel(priority) {
    return { normal: 'Обычный', high: 'Высокий', critical: 'Критичный' }[priority] || priority || 'Приоритет';
}

function opsEscape(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function opsParseDate(value) {
    const raw = String(value || '').trim();
    if (!raw) return null;
    const match = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})/);
    const iso = match ? `${match[3]}-${match[2]}-${match[1]}` : raw.slice(0, 10);
    const date = new Date(`${iso}T00:00:00`);
    return Number.isNaN(date.getTime()) ? null : date;
}

function opsIsPastDate(value) {
    const date = opsParseDate(value);
    if (!date) return false;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return date < today;
}

function opsIsThisWeek(value) {
    const date = opsParseDate(value);
    if (!date) return false;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const weekEnd = new Date(today);
    weekEnd.setDate(today.getDate() + 7);
    return date >= today && date <= weekEnd;
}

function opsRowMatchesQuery(item, fields) {
    const query = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
    if (!query) return true;
    const haystack = fields.map(field => item[field] || '').join(' ').toLowerCase();
    return haystack.includes(query);
}

function getVisiblePurchases() {
    return purchasesDB.filter(item => {
        if (!opsRowMatchesQuery(item, ['item_name', 'item_article', 'supplier', 'project_name', 'project_contract', 'client_name', 'comment', 'status'])) return false;
        if (supplyListFilter === 'this_week') return opsIsThisWeek(item.expected_date);
        if (supplyListFilter !== 'all' && supplyListFilter !== 'reservations') return item.status === supplyListFilter;
        return true;
    });
}

function getVisibleStockReservations() {
    return stockReservationsDB.filter(item => {
        if (!opsRowMatchesQuery(item, ['nomenclature_name', 'nomenclature_article', 'warehouse', 'bin_code', 'batch_code', 'project_name', 'client_name', 'status'])) return false;
        if (supplyListFilter === 'reservations') return !['fulfilled', 'cancelled'].includes(item.status || '');
        return true;
    });
}

function getVisibleSalesDocs() {
    return salesDocsDB.filter(item => {
        if (!opsRowMatchesQuery(item, ['doc_number', 'doc_type', 'project_name', 'project_contract', 'client_name', 'customer_order_no', 'recipient_email', 'comment', 'status', 'payment_status', 'shipment_status'])) return false;
        if (salesListFilter === 'draft') return item.status === 'draft';
        if (salesListFilter === 'unpaid') return item.payment_status !== 'paid';
        if (salesListFilter === 'overdue_payment') return item.payment_status !== 'paid' && opsIsPastDate(item.payment_due_date);
        if (salesListFilter === 'shipment_risk') return !['shipped', 'delivered'].includes(item.shipment_status || '') && opsIsPastDate(item.planned_ship_date);
        return true;
    });
}

function getVisibleProductionOrders() {
    return productionOrdersDB.filter(item => {
        if (!opsRowMatchesQuery(item, ['order_name', 'route_name', 'responsible', 'project_name', 'project_contract', 'client_name', 'comment', 'stage', 'priority'])) return false;
        if (productionListFilter === 'critical') return item.priority === 'critical';
        if (productionListFilter === 'late') return item.stage !== 'done' && opsIsPastDate(item.planned_finish);
        if (productionListFilter !== 'all') return item.stage === productionListFilter;
        return true;
    });
}

function productionOrderExecutionState(order) {
    const orderId = Number(order?.id || 0);
    const operations = productionOperationsDB.filter(item => Number(item.order_id) === orderId);
    const bomItems = productionBomDB.filter(item => Number(item.order_id) === orderId);
    const progress = Math.max(0, Math.min(100, Number(order?.progress || 0)));
    const plannedQty = Number(order?.planned_qty_total || order?.planned_qty || 0);
    const producedQty = Number(order?.produced_qty_total || order?.produced_qty || 0);
    const completedOperations = operations.filter(item => ['done', 'completed', 'otk'].includes(item.status || '')).length;
    const late = order?.stage !== 'done' && opsIsPastDate(order?.planned_finish);
    const materialGaps = bomItems.filter(item => {
        const planned = Number(item.planned_qty || 0);
        const actual = Number(item.actual_qty || 0);
        return planned > 0 && actual > 0 && actual < planned;
    }).length;
    const blockers = [];
    if (late) blockers.push('срыв срока');
    if (!order?.responsible) blockers.push('нет ответственного');
    if (Number(order?.scrap_qty_total || order?.scrap_qty || 0) > 0) blockers.push('есть брак');
    if (materialGaps) blockers.push(`материалы ${materialGaps}`);
    if (operations.length && completedOperations < operations.length && progress >= 80 && order?.stage !== 'done') blockers.push('ОТК/закрытие');
    if (!operations.length) blockers.push('нет операций');
    const materialReady = bomItems.length ? Math.round((bomItems.length - materialGaps) / bomItems.length * 100) : 100;
    const operationReady = operations.length ? Math.round(completedOperations / operations.length * 100) : progress;
    const tone = late || blockers.length > 2 ? 'risk' : (order?.stage === 'done' ? 'stable' : (progress >= 70 ? 'active' : 'attention'));
    return {
        progress,
        plannedQty,
        producedQty,
        operationsTotal: operations.length,
        completedOperations,
        materialReady,
        operationReady,
        late,
        materialGaps,
        blockers,
        tone,
    };
}

function renderOrderExecutionDashboard() {
    const mount = document.getElementById('orderExecutionDashboardMount');
    if (!mount) return;
    const states = productionOrdersDB.map(order => ({ order, state: productionOrderExecutionState(order) }));
    const activeOrders = states.filter(item => item.order.stage !== 'done');
    const lateOrders = activeOrders.filter(item => item.state.late);
    const otkOrders = states.filter(item => item.order.stage === 'otk');
    const materialRisk = activeOrders.filter(item => item.state.materialGaps > 0);
    const avgProgress = activeOrders.length ? Math.round(activeOrders.reduce((sum, item) => sum + item.state.progress, 0) / activeOrders.length) : 0;
    const stageRows = ['queue', 'in_work', 'otk', 'done'].map(stage => ({
        stage,
        label: productionStageLabel(stage),
        count: states.filter(item => item.order.stage === stage).length,
    }));
    const focusRows = activeOrders
        .sort((a, b) => {
            const ar = (a.state.late ? 1000 : 0) + a.state.blockers.length * 100 - a.state.progress;
            const br = (b.state.late ? 1000 : 0) + b.state.blockers.length * 100 - b.state.progress;
            return br - ar;
        })
        .slice(0, 6);
    mount.innerHTML = `
        <section class="ops-intelligence-card order-execution-card">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Дашборд выполнения заказа в реальном времени</h3>
                    <p class="section-subtitle">Сводка для директора: стадия, процент выполнения, сроки, материалы, ОТК и блокеры по активным заказам.</p>
                </div>
                <div class="view-actions">
                    <button class="btn-secondary" onclick="focusProductionQueue()">Очередь</button>
                    <button class="btn-secondary" onclick="renderProduction()">Обновить</button>
                </div>
            </div>
            <div class="ops-intelligence-metrics order-execution-metrics">
                <div><span>Активные</span><strong>${activeOrders.length}</strong></div>
                <div><span>Средний прогресс</span><strong>${avgProgress}%</strong></div>
                <div><span>Срыв срока</span><strong>${lateOrders.length}</strong></div>
                <div><span>ОТК</span><strong>${otkOrders.length}</strong></div>
                <div><span>Мат. риски</span><strong>${materialRisk.length}</strong></div>
                <div><span>Всего заказов</span><strong>${productionOrdersDB.length}</strong></div>
            </div>
            <div class="order-stage-strip">
                ${stageRows.map(item => `
                    <div class="order-stage-pill">
                        <span>${item.label}</span>
                        <strong>${item.count}</strong>
                    </div>
                `).join('')}
            </div>
            <div class="ops-intelligence-list order-execution-list">
                ${focusRows.length ? focusRows.map(({ order, state }) => `
                    <div class="ops-intelligence-item order-execution-item">
                        <div>
                            <strong>${opsEscape(order.order_name || `Заказ #${order.id}`)}</strong>
                            <span>${opsEscape(order.client_name || 'Клиент не указан')} · ${opsEscape(order.project_contract || order.project_name || 'без проекта')} · ${opsEscape(order.responsible || 'нет ответственного')}</span>
                            <div class="order-progress-line">
                                <i style="width:${state.progress}%"></i>
                            </div>
                            <small>План/факт: ${Number(state.plannedQty || 0).toLocaleString('ru-RU')} / ${Number(state.producedQty || 0).toLocaleString('ru-RU')} · операции ${state.completedOperations}/${state.operationsTotal} · материалы ${state.materialReady}%</small>
                            <em>${state.blockers.length ? state.blockers.map(opsEscape).join(' · ') : 'без критичных блокеров'}</em>
                        </div>
                        <div class="order-execution-side">
                            <span class="status-badge ${opsHealthBadgeClass(state.tone)}">${productionStageLabel(order.stage)}</span>
                            <button class="btn-secondary" onclick="selectProductionOrder(${Number(order.id || 0)}); renderProduction();">Открыть</button>
                        </div>
                    </div>
                `).join('') : '<div class="empty-state">Активных производственных заказов нет. Когда появятся заказы, здесь будет реальный контроль исполнения.</div>'}
            </div>
        </section>
    `;
}

function registerOpsSavedFilters(scope, mountId, defaultTitle, getFilter, setFilter, renderFn, presets) {
    if (typeof registerWorkbenchSavedFilterScope !== 'function') return;
    registerWorkbenchSavedFilterScope(scope, {
        mountId,
        defaultTitle,
        getPayload: () => ({ listFilter: getFilter(), query: document.getElementById('searchInput')?.value || '' }),
        applyPayload: payload => {
            setFilter(payload.listFilter || 'all');
            const searchInput = document.getElementById('searchInput');
            if (searchInput) searchInput.value = payload.query || '';
            renderFn();
        },
        presets: presets.map(item => ({
            ...item,
            payload: () => ({ listFilter: item.key, query: document.getElementById('searchInput')?.value || '' }),
        })),
        updateState: () => {
            presets.forEach(item => document.getElementById(item.id)?.classList.toggle('is-filter-active', getFilter() === item.key));
        },
    });
}

function renderSupplyRoleWorkbench(metrics = {}) {
    const mount = document.getElementById('supplyRoleWorkbenchMount');
    if (!mount || !currentUser) return;
    const role = String(currentUser.role || '').trim();
    if (role === 'Склад') {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Склад</div>
                    <h3 class="section-title">Единый экран склада</h3>
                    <p class="section-subtitle">Закупки, приход, резервы, остатки, партии, ячейки и качество должны читаться как один поток, а не как разрозненные блоки.</p>
                </div>
                <div class="role-workbench-stats">
                    <div class="role-workbench-stat"><span>Резервов</span><strong>${metrics.reserved_positions || 0}</strong></div>
                    <div class="role-workbench-stat"><span>Дефицитов</span><strong>${metrics.shortages || 0}</strong></div>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="presetSupplyMode('purchase')">Закупка</button>
                    <button class="btn-secondary" onclick="presetSupplyMode('reservation')">Резерв</button>
                    <button class="btn-secondary" onclick="navigateTo('nomenclature')">Остатки и ячейки</button>
                    <button class="btn-secondary" onclick="document.getElementById('stockQualityList')?.scrollIntoView({behavior:'smooth', block:'start'})">Качество</button>
                </div>
            </section>
        `;
        return;
    }
    mount.innerHTML = '';
}

function getSupplyWorkspacePanel(tab = 'purchase') {
    if (tab === 'registry') return 'registry';
    if (tab === 'control') return 'control';
    return 'editor';
}

function getSupplyEditorMeta() {
    const mode = window.supplyActiveOperationMode === 'reservation' ? 'reservation' : 'purchase';
    if (mode === 'reservation') {
        return {
            title: 'Резерв под проект',
            subtitle: 'Выбери проект, позицию и количество. При необходимости укажи склад, ячейку и партию, чтобы закрепить материал за проектом.',
            chip: 'Резерв',
            note: 'Режим резерва фиксирует потребность под проект и помогает держать остатки под контролем без отдельной длинной формы.',
        };
    }
    return {
        title: Number(editingPurchaseId || 0) > 0 ? 'Редактирование закупки' : 'Новая закупка',
        subtitle: 'Выбери проект и контрагента, затем укажи поставщика, материал, количество и срок поставки.',
        chip: 'Закупка',
        note: 'Режим закупки нужен для новой поставки: здесь фиксируются поставщик, сумма, срок и привязка к проекту.',
    };
}

function syncSupplyQuickSwitch() {
    const quickActive = window.supplyActiveWorkspaceTab === 'registry'
        ? 'registry'
        : (window.supplyActiveOperationMode === 'reservation' ? 'reservation' : 'purchase');
    document.querySelectorAll('#supplyView [data-supply-quick]').forEach(button => {
        const isActive = button.dataset.supplyQuick === quickActive;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
}

function syncSupplyEditorState() {
    const meta = getSupplyEditorMeta();
    const title = document.getElementById('supplyEditorTitle');
    const subtitle = document.getElementById('supplyEditorSubtitle');
    const chip = document.getElementById('supplyEditorChip');
    const note = document.getElementById('supplyFormModeNote');
    const purchaseBtn = document.getElementById('supplyPurchaseActionBtn');
    const reservationBtn = document.getElementById('supplyReservationActionBtn');
    if (title) title.textContent = meta.title;
    if (subtitle) subtitle.textContent = meta.subtitle;
    if (chip) chip.textContent = meta.chip;
    if (note) note.textContent = meta.note;
    if (purchaseBtn) {
        const purchasePrimary = window.supplyActiveOperationMode !== 'reservation';
        purchaseBtn.className = purchasePrimary ? 'btn-primary' : 'btn-secondary';
        purchaseBtn.textContent = Number(editingPurchaseId || 0) > 0 && purchasePrimary ? 'Сохранить изменения' : 'Сохранить закупку';
    }
    if (reservationBtn) {
        const reservationPrimary = window.supplyActiveOperationMode === 'reservation';
        reservationBtn.className = reservationPrimary ? 'btn-primary' : 'btn-secondary';
        reservationBtn.textContent = 'Создать резерв';
    }
}

function setSupplyOperationMode(mode = 'purchase') {
    window.supplyActiveOperationMode = mode === 'reservation' ? 'reservation' : 'purchase';
    syncSupplyEditorState();
    syncSupplyQuickSwitch();
}

window.switchSupplyWorkspaceTab = function(tab = 'purchase') {
    const view = document.getElementById('supplyView');
    if (!view) return;
    const allowed = new Set(['purchase', 'reservation', 'registry', 'control']);
    const activeTab = allowed.has(tab) ? tab : 'purchase';
    window.supplyActiveWorkspaceTab = activeTab;
    if (activeTab === 'purchase' || activeTab === 'reservation') {
        setSupplyOperationMode(activeTab);
    } else {
        syncSupplyEditorState();
        syncSupplyQuickSwitch();
    }
    const activePanel = getSupplyWorkspacePanel(activeTab);
    view.querySelectorAll('[data-supply-tab-button]').forEach(button => {
        const isActive = button.dataset.supplyTabButton === activeTab;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    view.querySelectorAll('[data-supply-panel]').forEach(panel => {
        const isActive = panel.dataset.supplyPanel === activePanel;
        panel.classList.toggle('is-active', isActive);
        panel.hidden = !isActive;
    });
};

window.openSupplyRegistry = function(filter = '') {
    if (typeof filter === 'string' && filter) supplyListFilter = filter;
    window.switchSupplyWorkspaceTab('registry');
};

window.openSupplyControl = function() {
    window.switchSupplyWorkspaceTab('control');
};

function renderProductionRoleWorkbench() {
    const mount = document.getElementById('productionRoleWorkbenchMount');
    const view = document.getElementById('productionView');
    if (!mount || !view || !currentUser) return;
    const role = String(currentUser.role || '').trim();
    const isProductionRole = role === 'Производство и ОТК' || role === 'Конструкторское бюро';
    view.classList.toggle('production-operational-mode', isProductionRole && !window.__productionSecondaryExpanded);
    if (isProductionRole) {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Цех</div>
                    <h3 class="section-title">Первый экран мастера</h3>
                    <p class="section-subtitle">Сначала очередь и заказ. Аналитика, norm/fact и инженерные детали должны идти ниже и только когда уже есть выбранный фокус.</p>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="focusProductionQueue()">Очередь цеха</button>
                    <button class="btn-secondary" onclick="focusProductionOrderForm()">Новый заказ</button>
                    <button class="btn-secondary" onclick="focusProductionOperations()">Операции</button>
                    <button class="btn-secondary" onclick="openSupplyFromProduction()">Материалы</button>
                    <button class="btn-secondary" onclick="toggleProductionSecondary()">${window.__productionSecondaryExpanded ? 'Скрыть аналитику' : 'Показать аналитику'}</button>
                </div>
            </section>
        `;
        return;
    }
    mount.innerHTML = '';
}

window.toggleProductionSecondary = function() {
    window.__productionSecondaryExpanded = !window.__productionSecondaryExpanded;
    renderProductionRoleWorkbench();
};

function projectAndClientMeta(item) {
    return `
        <div class="ops-table-cell">
            <div class="finance-row-title">${item.project_contract || item.project_name || 'Без проекта'}</div>
            <div class="finance-row-meta">${item.client_name || 'Без контрагента'}</div>
            <div class="finance-row-meta">${item.legal_entity_name || 'Без юрлица'}${item.business_unit_name ? ` · ${item.business_unit_name}` : ''}</div>
        </div>
    `;
}

function resetPurchaseForm() {
    releaseOpsEditLock('purchase_order');
    editingPurchaseId = 0;
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('purchaseForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('purchaseForm');
    [['purchaseProjectId', '0'], ['purchaseClientId', '0'], ['purchaseLegalEntityId', '0'], ['purchaseBusinessUnitId', '0'], ['purchaseItemName', ''], ['purchaseItemArticle', ''], ['purchaseSupplier', ''], ['purchaseQty', ''], ['purchaseUnit', 'шт'], ['purchaseUnitPrice', ''], ['purchaseWarehouse', ''], ['purchaseBinCode', ''], ['purchaseBatchCode', ''], ['purchaseExpectedDate', ''], ['purchaseStatus', 'planned'], ['purchaseComment', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    syncOpsBusinessUnitOptions('purchaseLegalEntityId', 'purchaseBusinessUnitId');
    void applyOpsFieldPermissions();
    if (typeof clearFormDraft === 'function') clearFormDraft('purchase_order');
    syncSupplyEditorState();
}

function resetSalesForm() {
    releaseOpsEditLock('sales_document');
    editingSalesId = 0;
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('salesForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('salesForm');
    [['salesProjectId', '0'], ['salesClientId', '0'], ['salesLegalEntityId', '0'], ['salesBusinessUnitId', '0'], ['salesDocType', 'invoice'], ['salesDocNumber', ''], ['salesDocDate', ''], ['salesAmount', ''], ['salesCurrency', 'RUB'], ['salesStatus', 'draft'], ['salesPaymentStatus', 'planned'], ['salesLinkedPayment', '0'], ['salesPriceListId', '0'], ['salesDiscountPercent', ''], ['salesDiscountAmount', ''], ['salesCustomerOrderNo', ''], ['salesShipmentStatus', 'not_shipped'], ['salesPaymentDueDate', ''], ['salesPlannedShipDate', ''], ['salesReserveStatus', 'none'], ['salesReserveQty', ''], ['salesRecipientEmail', ''], ['salesSentStatus', 'draft'], ['salesSentAt', ''], ['salesDeliveredAt', ''], ['salesConfirmedAt', ''], ['salesComment', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    syncOpsBusinessUnitOptions('salesLegalEntityId', 'salesBusinessUnitId');
    void applyOpsFieldPermissions();
}

function getClientTermsForSales(clientId) {
    return (opsExtendedDB.clientTerms || []).find(item => Number(item.client_id || 0) === Number(clientId || 0) && String(item.status || 'active') !== 'archived') || null;
}

function applySalesClientTerms() {
    const clientId = Number(document.getElementById('salesClientId')?.value || 0);
    const terms = getClientTermsForSales(clientId);
    if (!terms) return;
    const priceListEl = document.getElementById('salesPriceListId');
    const discountPercentEl = document.getElementById('salesDiscountPercent');
    const discountAmountEl = document.getElementById('salesDiscountAmount');
    const paymentDueDateEl = document.getElementById('salesPaymentDueDate');
    const reserveStatusEl = document.getElementById('salesReserveStatus');
    if (priceListEl && Number(priceListEl.value || 0) === 0 && Number(terms.price_list_id || 0) > 0) {
        priceListEl.value = String(terms.price_list_id);
    }
    if (discountPercentEl && !String(discountPercentEl.value || '').trim() && Number(terms.discount_percent || 0) > 0) {
        discountPercentEl.value = String(terms.discount_percent || 0);
    }
    if (discountAmountEl && !String(discountAmountEl.value || '').trim() && Number(terms.discount_amount || 0) > 0) {
        discountAmountEl.value = String(terms.discount_amount || 0);
    }
    if (paymentDueDateEl && !String(paymentDueDateEl.value || '').trim() && Number(terms.payment_delay_days || 0) > 0) {
        paymentDueDateEl.value = addDaysToDisplayDate(Number(terms.payment_delay_days || 0), document.getElementById('salesDocDate')?.value || '');
    }
    if (reserveStatusEl && Number(terms.credit_limit || 0) > 0 && reserveStatusEl.value === 'none') {
        reserveStatusEl.value = 'reserved';
    }
}

function resetProductionForm() {
    releaseOpsEditLock('production_order');
    editingProductionId = 0;
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('productionOrderForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('productionOrderForm');
    [['productionProjectId', '0'], ['productionClientId', '0'], ['productionLegalEntityId', '0'], ['productionBusinessUnitId', '0'], ['productionOrderName', ''], ['productionResponsible', ''], ['productionRouteName', ''], ['productionStage', 'queue'], ['productionPriority', 'normal'], ['productionPlanStart', ''], ['productionPlanFinish', ''], ['productionActualFinish', ''], ['productionPlannedQty', '0'], ['productionProducedQty', '0'], ['productionScrapQty', '0'], ['productionPlannedCost', '0'], ['productionActualCost', '0'], ['productionLaborHoursPlan', '0'], ['productionLaborHoursFact', '0'], ['productionProgress', '0'], ['productionComment', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    syncOpsBusinessUnitOptions('productionLegalEntityId', 'productionBusinessUnitId');
    void applyOpsFieldPermissions();
    if (typeof clearFormDraft === 'function') clearFormDraft('production_order');
}

function resetProductionOperationForm() {
    releaseOpsEditLock('production_operation');
    editingProductionOperationId = 0;
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('productionOperationForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('productionOperationForm');
    [['productionOperationSequence', '1'], ['productionOperationName', ''], ['productionOperationWorkCenter', ''], ['productionOperationStatus', 'planned'], ['productionOperationPlannedHours', '0'], ['productionOperationActualHours', '0'], ['productionOperationPlannedQty', '0'], ['productionOperationCompletedQty', '0'], ['productionOperationScrapQty', '0'], ['productionOperationLaborRate', '0'], ['productionOperationMaterialCost', '0'], ['productionOperationOverheadCost', '0'], ['productionOperationStartedAt', ''], ['productionOperationFinishedAt', ''], ['productionOperationNote', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    void applyOpsFieldPermissions();
}

function resetProductionBomForm() {
    releaseOpsEditLock('production_bom_item');
    editingProductionBomId = 0;
    [['productionBomArticle', ''], ['productionBomName', ''], ['productionBomUnit', 'шт'], ['productionBomQtyPerUnit', '0'], ['productionBomPlannedQty', '0'], ['productionBomActualQty', '0'], ['productionBomUnitCost', '0'], ['productionBomWarehouse', 'Основной склад'], ['productionBomBin', 'A-01'], ['productionBomNote', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    void applyOpsFieldPermissions();
}

function resetProductionRouteForm() {
    releaseOpsEditLock('production_route_template');
    editingProductionRouteId = 0;
    [['productionRouteSequence', '1'], ['productionRouteOperation', ''], ['productionRouteWorkCenter', ''], ['productionRoutePlannedHours', '0'], ['productionRoutePlannedQty', '0'], ['productionRouteLaborRate', '0'], ['productionRouteNote', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    applyOpsFieldPermissions();
}

async function editPurchase(id) {
    const item = purchasesDB.find(row => row.id === id);
    if (!item) return;
    const lockOk = await acquireOpsEditLock('purchase_order', id);
    if (!lockOk) return;
    editingPurchaseId = id;
    document.getElementById('purchaseProjectId').value = String(item.project_id || 0);
    document.getElementById('purchaseClientId').value = String(item.client_id || 0);
    document.getElementById('purchaseLegalEntityId').value = String(item.legal_entity_id || 0);
    syncOpsBusinessUnitOptions('purchaseLegalEntityId', 'purchaseBusinessUnitId', item.business_unit_id || 0);
    document.getElementById('purchaseItemName').value = item.item_name || '';
    document.getElementById('purchaseItemArticle').value = item.item_article || '';
    document.getElementById('purchaseSupplier').value = item.supplier || '';
    document.getElementById('purchaseQty').value = item.qty || '';
    document.getElementById('purchaseUnit').value = item.unit || 'шт';
    document.getElementById('purchaseUnitPrice').value = item.unit_price || '';
    document.getElementById('purchaseWarehouse').value = '';
    document.getElementById('purchaseBinCode').value = '';
    document.getElementById('purchaseBatchCode').value = '';
    document.getElementById('purchaseExpectedDate').value = item.expected_date || '';
    document.getElementById('purchaseStatus').value = item.status || 'planned';
    document.getElementById('purchaseComment').value = item.comment || '';
    setSupplyOperationMode('purchase');
    window.switchSupplyWorkspaceTab('purchase');
    applyOpsFieldPermissions();
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#purchaseForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('purchaseExpectedDate');
}

function duplicatePurchase(id) {
    const item = purchasesDB.find(row => Number(row.id) === Number(id));
    if (!item) return;
    resetPurchaseForm();
    document.getElementById('purchaseProjectId').value = String(item.project_id || 0);
    document.getElementById('purchaseClientId').value = String(item.client_id || 0);
    document.getElementById('purchaseLegalEntityId').value = String(item.legal_entity_id || 0);
    syncOpsBusinessUnitOptions('purchaseLegalEntityId', 'purchaseBusinessUnitId', item.business_unit_id || 0);
    document.getElementById('purchaseItemName').value = item.item_name || '';
    document.getElementById('purchaseItemArticle').value = item.item_article || '';
    document.getElementById('purchaseSupplier').value = item.supplier || '';
    document.getElementById('purchaseQty').value = item.qty || '';
    document.getElementById('purchaseUnit').value = item.unit || 'шт';
    document.getElementById('purchaseUnitPrice').value = item.unit_price || '';
    document.getElementById('purchaseExpectedDate').value = item.expected_date || '';
    document.getElementById('purchaseStatus').value = 'planned';
    document.getElementById('purchaseComment').value = item.comment ? `${item.comment} (копия)` : '';
    setSupplyOperationMode('purchase');
    window.switchSupplyWorkspaceTab('purchase');
    applyOpsFieldPermissions();
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#purchaseForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('purchaseExpectedDate');
    showToast('Склад', 'Форма похожей закупки подготовлена');
}

async function editSalesDocument(id) {
    const item = salesDocsDB.find(row => row.id === id);
    if (!item) return;
    const lockOk = await acquireOpsEditLock('sales_document', id);
    if (!lockOk) return;
    editingSalesId = id;
    document.getElementById('salesProjectId').value = String(item.project_id || 0);
    document.getElementById('salesClientId').value = String(item.client_id || 0);
    document.getElementById('salesLegalEntityId').value = String(item.legal_entity_id || 0);
    syncOpsBusinessUnitOptions('salesLegalEntityId', 'salesBusinessUnitId', item.business_unit_id || 0);
    document.getElementById('salesDocType').value = item.doc_type || 'invoice';
    document.getElementById('salesDocNumber').value = item.doc_number || '';
    document.getElementById('salesDocDate').value = item.doc_date || '';
    document.getElementById('salesAmount').value = item.amount || '';
    document.getElementById('salesCurrency').value = item.currency || 'RUB';
    document.getElementById('salesStatus').value = item.status || 'draft';
    document.getElementById('salesPaymentStatus').value = item.payment_status || 'planned';
    document.getElementById('salesLinkedPayment').value = String(item.linked_payment_id || 0);
    document.getElementById('salesPriceListId').value = String(item.price_list_id || 0);
    document.getElementById('salesDiscountPercent').value = item.discount_percent || '';
    document.getElementById('salesDiscountAmount').value = item.discount_amount || '';
    document.getElementById('salesCustomerOrderNo').value = item.customer_order_no || '';
    document.getElementById('salesShipmentStatus').value = item.shipment_status || 'not_shipped';
    document.getElementById('salesPaymentDueDate').value = item.payment_due_date || '';
    document.getElementById('salesPlannedShipDate').value = item.planned_ship_date || '';
    document.getElementById('salesReserveStatus').value = item.reserve_status || 'none';
    document.getElementById('salesReserveQty').value = item.reserve_qty || '';
    document.getElementById('salesRecipientEmail').value = item.recipient_email || '';
    document.getElementById('salesSentStatus').value = item.sent_status || 'draft';
    document.getElementById('salesSentAt').value = item.sent_at || '';
    document.getElementById('salesDeliveredAt').value = item.delivered_at || '';
    document.getElementById('salesConfirmedAt').value = item.confirmed_at || '';
    document.getElementById('salesComment').value = item.comment || '';
    applyOpsFieldPermissions();
}

function duplicateSalesDocument(id) {
    const item = salesDocsDB.find(row => Number(row.id) === Number(id));
    if (!item) return;
    resetSalesForm();
    document.getElementById('salesProjectId').value = String(item.project_id || 0);
    document.getElementById('salesClientId').value = String(item.client_id || 0);
    document.getElementById('salesLegalEntityId').value = String(item.legal_entity_id || 0);
    syncOpsBusinessUnitOptions('salesLegalEntityId', 'salesBusinessUnitId', item.business_unit_id || 0);
    document.getElementById('salesDocType').value = item.doc_type || 'invoice';
    document.getElementById('salesDocNumber').value = item.doc_number ? `${item.doc_number}-COPY` : '';
    document.getElementById('salesDocDate').value = '';
    document.getElementById('salesAmount').value = item.amount || '';
    document.getElementById('salesCurrency').value = item.currency || 'RUB';
    document.getElementById('salesStatus').value = 'draft';
    document.getElementById('salesPaymentStatus').value = 'planned';
    document.getElementById('salesLinkedPayment').value = '0';
    document.getElementById('salesPriceListId').value = String(item.price_list_id || 0);
    document.getElementById('salesDiscountPercent').value = item.discount_percent || '';
    document.getElementById('salesDiscountAmount').value = item.discount_amount || '';
    document.getElementById('salesCustomerOrderNo').value = item.customer_order_no || '';
    document.getElementById('salesShipmentStatus').value = 'not_shipped';
    document.getElementById('salesPaymentDueDate').value = '';
    document.getElementById('salesPlannedShipDate').value = '';
    document.getElementById('salesReserveStatus').value = item.reserve_status || 'none';
    document.getElementById('salesReserveQty').value = item.reserve_qty || '';
    document.getElementById('salesRecipientEmail').value = item.recipient_email || '';
    document.getElementById('salesSentStatus').value = 'draft';
    document.getElementById('salesSentAt').value = '';
    document.getElementById('salesDeliveredAt').value = '';
    document.getElementById('salesConfirmedAt').value = '';
    document.getElementById('salesComment').value = item.comment ? `${item.comment} (копия)` : '';
    applyOpsFieldPermissions();
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#salesForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('salesDocNumber');
    showToast('Реализация', 'Форма похожего документа подготовлена');
}

async function editProductionOrder(id) {
    const item = productionOrdersDB.find(row => row.id === id);
    if (!item) return;
    const lockOk = await acquireOpsEditLock('production_order', id);
    if (!lockOk) return;
    editingProductionId = id;
    document.getElementById('productionProjectId').value = String(item.project_id || 0);
    document.getElementById('productionClientId').value = String(item.client_id || 0);
    document.getElementById('productionLegalEntityId').value = String(item.legal_entity_id || 0);
    syncOpsBusinessUnitOptions('productionLegalEntityId', 'productionBusinessUnitId', item.business_unit_id || 0);
    document.getElementById('productionOrderName').value = item.order_name || '';
    document.getElementById('productionResponsible').value = item.responsible || '';
    document.getElementById('productionRouteName').value = item.route_name || '';
    document.getElementById('productionStage').value = item.stage || 'queue';
    document.getElementById('productionPriority').value = item.priority || 'normal';
    document.getElementById('productionPlanStart').value = item.planned_start || '';
    document.getElementById('productionPlanFinish').value = item.planned_finish || '';
    document.getElementById('productionActualFinish').value = item.actual_finish || '';
    document.getElementById('productionPlannedQty').value = item.planned_qty || item.planned_qty_total || 0;
    document.getElementById('productionProducedQty').value = item.produced_qty || item.produced_qty_total || 0;
    document.getElementById('productionScrapQty').value = item.scrap_qty || item.scrap_qty_total || 0;
    document.getElementById('productionPlannedCost').value = item.planned_cost || 0;
    document.getElementById('productionActualCost').value = item.actual_cost_total || item.actual_cost || 0;
    document.getElementById('productionLaborHoursPlan').value = item.labor_hours_plan || 0;
    document.getElementById('productionLaborHoursFact').value = item.labor_hours_total || item.labor_hours_fact || 0;
    document.getElementById('productionProgress').value = item.progress || 0;
    document.getElementById('productionComment').value = item.comment || '';
    applyOpsFieldPermissions();
}

function duplicateProductionOrder(id) {
    const item = productionOrdersDB.find(row => Number(row.id) === Number(id));
    if (!item) return;
    resetProductionForm();
    document.getElementById('productionProjectId').value = String(item.project_id || 0);
    document.getElementById('productionClientId').value = String(item.client_id || 0);
    document.getElementById('productionLegalEntityId').value = String(item.legal_entity_id || 0);
    syncOpsBusinessUnitOptions('productionLegalEntityId', 'productionBusinessUnitId', item.business_unit_id || 0);
    document.getElementById('productionOrderName').value = `${item.order_name || 'Производственный заказ'} (копия)`;
    document.getElementById('productionResponsible').value = item.responsible || '';
    document.getElementById('productionRouteName').value = item.route_name || '';
    document.getElementById('productionStage').value = 'queue';
    document.getElementById('productionPriority').value = item.priority || 'normal';
    document.getElementById('productionPlanStart').value = '';
    document.getElementById('productionPlanFinish').value = '';
    document.getElementById('productionActualFinish').value = '';
    document.getElementById('productionPlannedQty').value = item.planned_qty || item.planned_qty_total || 0;
    document.getElementById('productionProducedQty').value = 0;
    document.getElementById('productionScrapQty').value = 0;
    document.getElementById('productionPlannedCost').value = item.planned_cost_total || item.planned_cost || 0;
    document.getElementById('productionActualCost').value = 0;
    document.getElementById('productionLaborHoursPlan').value = item.labor_hours_plan || 0;
    document.getElementById('productionLaborHoursFact').value = 0;
    document.getElementById('productionProgress').value = 0;
    document.getElementById('productionComment').value = item.comment ? `${item.comment} (копия)` : '';
    applyOpsFieldPermissions();
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#productionOrderForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('productionOrderName');
    showToast('Производство', 'Форма похожего заказа подготовлена');
}

async function editProductionOperation(id) {
    const item = productionOperationsDB.find(row => row.id === id);
    if (!item) return;
    const lockOk = await acquireOpsEditLock('production_operation', id);
    if (!lockOk) return;
    selectedProductionOrderId = Number(item.order_id || 0);
    editingProductionOperationId = id;
    document.getElementById('productionOperationSequence').value = item.sequence_no || 1;
    document.getElementById('productionOperationName').value = item.operation_name || '';
    document.getElementById('productionOperationWorkCenter').value = item.work_center || '';
    document.getElementById('productionOperationStatus').value = item.status || 'planned';
    document.getElementById('productionOperationPlannedHours').value = item.planned_hours || 0;
    document.getElementById('productionOperationActualHours').value = item.actual_hours || 0;
    document.getElementById('productionOperationPlannedQty').value = item.planned_qty || 0;
    document.getElementById('productionOperationCompletedQty').value = item.completed_qty || 0;
    document.getElementById('productionOperationScrapQty').value = item.scrap_qty || 0;
    document.getElementById('productionOperationLaborRate').value = item.labor_rate || 0;
    document.getElementById('productionOperationMaterialCost').value = item.material_cost || 0;
    document.getElementById('productionOperationOverheadCost').value = item.overhead_cost || 0;
    document.getElementById('productionOperationStartedAt').value = item.started_at || '';
    document.getElementById('productionOperationFinishedAt').value = item.finished_at || '';
    document.getElementById('productionOperationNote').value = item.note || '';
    applyOpsFieldPermissions();
}

async function editProductionBomItem(id) {
    const item = productionBomDB.find(row => row.id === id);
    if (!item) return;
    const lockOk = await acquireOpsEditLock('production_bom_item', id);
    if (!lockOk) return;
    selectedProductionOrderId = Number(item.order_id || 0);
    editingProductionBomId = id;
    document.getElementById('productionBomArticle').value = item.article || '';
    document.getElementById('productionBomName').value = item.item_name || item.nomenclature_name || '';
    document.getElementById('productionBomUnit').value = item.unit || 'шт';
    document.getElementById('productionBomQtyPerUnit').value = item.qty_per_unit || 0;
    document.getElementById('productionBomPlannedQty').value = item.planned_qty || 0;
    document.getElementById('productionBomActualQty').value = item.actual_qty || 0;
    document.getElementById('productionBomUnitCost').value = item.unit_cost || 0;
    document.getElementById('productionBomWarehouse').value = item.warehouse || 'Основной склад';
    document.getElementById('productionBomBin').value = item.bin_code || 'A-01';
    document.getElementById('productionBomNote').value = item.note || '';
    applyOpsFieldPermissions();
}

async function editProductionRouteItem(id) {
    const item = productionRoutesDB.find(row => row.id === id);
    if (!item) return;
    const lockOk = await acquireOpsEditLock('production_route_template', id);
    if (!lockOk) return;
    selectedProductionOrderId = Number(item.order_id || 0);
    editingProductionRouteId = id;
    document.getElementById('productionRouteSequence').value = item.sequence_no || 1;
    document.getElementById('productionRouteOperation').value = item.operation_name || '';
    document.getElementById('productionRouteWorkCenter').value = item.work_center || '';
    document.getElementById('productionRoutePlannedHours').value = item.planned_hours || 0;
    document.getElementById('productionRoutePlannedQty').value = item.planned_qty || 0;
    document.getElementById('productionRouteLaborRate').value = item.labor_rate || 0;
    document.getElementById('productionRouteNote').value = item.note || '';
    applyOpsFieldPermissions();
}

async function deletePurchase(id) {
    if (!(await customConfirm('Удалить закупку и связанную оплату безвозвратно?'))) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('supply', 'purchase_order', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/purchases/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось удалить закупку.'));
    if (editingPurchaseId === id) resetPurchaseForm();
    await renderSupply();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Склад', 'Закупка удалена');
}

async function deleteSalesDocument(id) {
    if (!(await customConfirm('Удалить документ реализации и связанную оплату?'))) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('sales', 'sales_document', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/sales/documents/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось удалить документ реализации.'));
    if (editingSalesId === id) resetSalesForm();
    await renderSales();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Реализация', 'Документ удалён');
}

async function deleteProductionOrder(id) {
    if (!(await customConfirm('Удалить производственный заказ безвозвратно?'))) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('production', 'production_order', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/production/orders/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось удалить производственный заказ.'));
    if (editingProductionId === id) resetProductionForm();
    await renderProduction();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Производство', 'Производственный заказ удалён');
}

async function savePurchase() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('purchaseForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('purchaseForm');
    const payload = {
        project_id: Number(document.getElementById('purchaseProjectId').value || 0),
        client_id: Number(document.getElementById('purchaseClientId').value || 0),
        legal_entity_id: Number(document.getElementById('purchaseLegalEntityId').value || 0),
        business_unit_id: Number(document.getElementById('purchaseBusinessUnitId').value || 0),
        item_name: document.getElementById('purchaseItemName').value.trim(),
        item_article: document.getElementById('purchaseItemArticle').value.trim(),
        supplier: document.getElementById('purchaseSupplier').value.trim(),
        qty: Number((document.getElementById('purchaseQty').value || '').replace(',', '.')) || 0,
        unit: document.getElementById('purchaseUnit').value.trim() || 'шт',
        unit_price: Number((document.getElementById('purchaseUnitPrice').value || '').replace(',', '.')) || 0,
        expected_date: document.getElementById('purchaseExpectedDate').value.trim(),
        status: document.getElementById('purchaseStatus').value,
        comment: document.getElementById('purchaseComment').value.trim(),
        received_date: '',
    };
    const errors = [];
    if (!payload.item_name) errors.push({ field: 'purchaseItemName', message: 'Укажите позицию или материал.' });
    if (!payload.supplier) errors.push({ field: 'purchaseSupplier', message: 'Укажите поставщика.' });
    if (!payload.qty) errors.push({ field: 'purchaseQty', message: 'Укажите количество.' });
    if (!payload.expected_date) errors.push({ field: 'purchaseExpectedDate', message: 'Укажите плановую дату поставки.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'purchaseForm');
        return;
    }
    if (editingPurchaseId) {
        const lockOk = await acquireOpsEditLock('purchase_order', editingPurchaseId);
        if (!lockOk) return;
    }
    const endpoint = editingPurchaseId ? `/purchases/${editingPurchaseId}` : '/purchases';
    const method = editingPurchaseId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (editingPurchaseId) await releaseOpsEditLock('purchase_order');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось сохранить закупку.'));
    if (typeof markWorkflowFocus === 'function') markWorkflowFocus('purchase', Number(res.id || editingPurchaseId || 0));
    resetPurchaseForm();
    supplyListFilter = 'all';
    await renderSupply();
    window.switchSupplyWorkspaceTab('registry');
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Склад', 'Закупка сохранена');
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('[data-purchase-id].workflow-row-highlight, [data-purchase-id]');
}

async function saveReservation() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('purchaseForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('purchaseForm');
    const payload = {
        project_id: Number(document.getElementById('purchaseProjectId').value || 0),
        legal_entity_id: Number(document.getElementById('purchaseLegalEntityId').value || 0),
        business_unit_id: Number(document.getElementById('purchaseBusinessUnitId').value || 0),
        nomenclature_article: document.getElementById('purchaseItemArticle').value.trim(),
        nomenclature_name: document.getElementById('purchaseItemName').value.trim(),
        qty: Number((document.getElementById('purchaseQty').value || '').replace(',', '.')) || 0,
        status: 'reserved',
        warehouse: document.getElementById('purchaseWarehouse').value.trim(),
        bin_code: document.getElementById('purchaseBinCode').value.trim(),
        batch_code: document.getElementById('purchaseBatchCode').value.trim(),
        comment: document.getElementById('purchaseComment').value.trim(),
    };
    const errors = [];
    if (!payload.nomenclature_name) errors.push({ field: 'purchaseItemName', message: 'Укажите позицию для резерва.' });
    if (!payload.qty) errors.push({ field: 'purchaseQty', message: 'Укажите количество для резерва.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'purchaseForm');
        return;
    }
    const res = await apiCall('/stock/reservations', 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось создать резерв.');
    if (typeof clearFormDraft === 'function') clearFormDraft('purchase_order');
    supplyListFilter = 'reservations';
    await renderSupply();
    window.switchSupplyWorkspaceTab('registry');
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Склад', 'Резерв создан');
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#stockReservationsList', { block: 'center' });
}

window.presetSupplyMode = function(mode = 'purchase') {
    const safeMode = mode === 'reservation' ? 'reservation' : 'purchase';
    setSupplyOperationMode(safeMode);
    window.switchSupplyWorkspaceTab(safeMode);
    const statusEl = document.getElementById('purchaseStatus');
    if (statusEl) statusEl.value = 'planned';
    const commentEl = document.getElementById('purchaseComment');
    if (safeMode === 'reservation') {
        if (commentEl && !commentEl.value.trim()) commentEl.value = 'Резерв под проект';
    } else if (commentEl && commentEl.value.trim() === 'Резерв под проект' && !editingPurchaseId) {
        commentEl.value = '';
    }
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#purchaseForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('purchaseProjectId');
};

async function fulfillReservation(id) {
    const item = stockReservationsDB.find(row => row.id === id);
    if (!item) return;
    const defaultQty = String(item.remaining_qty || item.qty || 0);
    const qtyRaw = await customPrompt(`Сколько списать по резерву #${id}?`, defaultQty);
    if (!qtyRaw) return;
    const qty = Number(String(qtyRaw).replace(',', '.'));
    if (!qty || qty <= 0) return customAlert('Нужно указать корректное количество.');
    const payload = {
        qty,
        warehouse: item.warehouse || '',
        bin_code: item.bin_code || '',
        batch_code: item.batch_code || '',
        serial_no: item.serial_no || '',
        comment: `Исполнение резерва #${id}`,
    };
    const res = await apiCall(`/stock/reservations/${id}/fulfill`, 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось исполнить резерв.');
    await renderSupply();
    if (typeof loadNSI === 'function') {
        await loadNSI();
        if (typeof renderNomenclature === 'function' && document.getElementById('nomenclatureView')?.style.display === 'block') renderNomenclature();
    }
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Склад', 'Резерв исполнен и списан со склада');
}

async function saveSalesDocument() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('salesForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('salesForm');
    const payload = {
        project_id: Number(document.getElementById('salesProjectId').value || 0),
        client_id: Number(document.getElementById('salesClientId').value || 0),
        legal_entity_id: Number(document.getElementById('salesLegalEntityId').value || 0),
        business_unit_id: Number(document.getElementById('salesBusinessUnitId').value || 0),
        doc_type: document.getElementById('salesDocType').value,
        doc_number: document.getElementById('salesDocNumber').value.trim(),
        doc_date: document.getElementById('salesDocDate').value.trim(),
        amount: Number((document.getElementById('salesAmount').value || '').replace(',', '.')) || 0,
        currency: document.getElementById('salesCurrency').value,
        status: document.getElementById('salesStatus').value,
        payment_status: document.getElementById('salesPaymentStatus').value,
        linked_payment_id: Number(document.getElementById('salesLinkedPayment').value || 0),
        price_list_id: Number(document.getElementById('salesPriceListId').value || 0),
        discount_percent: Number((document.getElementById('salesDiscountPercent').value || '').replace(',', '.')) || 0,
        discount_amount: Number((document.getElementById('salesDiscountAmount').value || '').replace(',', '.')) || 0,
        customer_order_no: document.getElementById('salesCustomerOrderNo').value.trim(),
        shipment_status: document.getElementById('salesShipmentStatus').value,
        payment_due_date: document.getElementById('salesPaymentDueDate').value.trim(),
        planned_ship_date: document.getElementById('salesPlannedShipDate').value.trim(),
        reserve_status: document.getElementById('salesReserveStatus').value,
        reserve_qty: Number((document.getElementById('salesReserveQty').value || '').replace(',', '.')) || 0,
        recipient_email: document.getElementById('salesRecipientEmail').value.trim(),
        sent_status: document.getElementById('salesSentStatus').value,
        sent_at: document.getElementById('salesSentAt').value.trim(),
        delivered_at: document.getElementById('salesDeliveredAt').value.trim(),
        confirmed_at: document.getElementById('salesConfirmedAt').value.trim(),
        comment: document.getElementById('salesComment').value.trim(),
    };
    const errors = [];
    if (!payload.doc_number) errors.push({ field: 'salesDocNumber', message: 'Укажите номер документа.' });
    if (!payload.amount) errors.push({ field: 'salesAmount', message: 'Укажите сумму документа.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'salesForm');
        return;
    }
    if (editingSalesId) {
        const lockOk = await acquireOpsEditLock('sales_document', editingSalesId);
        if (!lockOk) return;
    }
    const endpoint = editingSalesId ? `/sales/documents/${editingSalesId}` : '/sales/documents';
    const method = editingSalesId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (editingSalesId) await releaseOpsEditLock('sales_document');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось сохранить документ реализации.'));
    if (typeof markWorkflowFocus === 'function') markWorkflowFocus('sales', Number(res.id || editingSalesId || 0));
    resetSalesForm();
    await renderSales();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Реализация', 'Документ сохранён');
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('[data-sales-id].workflow-row-highlight, [data-sales-id]');
}

window.presetSalesDocument = function(docType = 'invoice') {
    const typeEl = document.getElementById('salesDocType');
    const statusEl = document.getElementById('salesStatus');
    if (typeEl) typeEl.value = docType;
    if (statusEl) statusEl.value = docType === 'act' ? 'signed' : 'draft';
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#salesForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('salesDocNumber');
};

async function saveProductionOrder() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('productionOrderForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('productionOrderForm');
    const payload = {
        project_id: Number(document.getElementById('productionProjectId').value || 0),
        client_id: Number(document.getElementById('productionClientId').value || 0),
        legal_entity_id: Number(document.getElementById('productionLegalEntityId').value || 0),
        business_unit_id: Number(document.getElementById('productionBusinessUnitId').value || 0),
        order_name: document.getElementById('productionOrderName').value.trim(),
        responsible: document.getElementById('productionResponsible').value.trim(),
        route_name: document.getElementById('productionRouteName').value.trim(),
        stage: document.getElementById('productionStage').value,
        priority: document.getElementById('productionPriority').value,
        planned_start: document.getElementById('productionPlanStart').value.trim(),
        planned_finish: document.getElementById('productionPlanFinish').value.trim(),
        actual_finish: document.getElementById('productionActualFinish').value.trim(),
        planned_qty: Number((document.getElementById('productionPlannedQty').value || '').replace(',', '.')) || 0,
        produced_qty: Number((document.getElementById('productionProducedQty').value || '').replace(',', '.')) || 0,
        scrap_qty: Number((document.getElementById('productionScrapQty').value || '').replace(',', '.')) || 0,
        planned_cost: Number((document.getElementById('productionPlannedCost').value || '').replace(',', '.')) || 0,
        actual_cost: Number((document.getElementById('productionActualCost').value || '').replace(',', '.')) || 0,
        labor_hours_plan: Number((document.getElementById('productionLaborHoursPlan').value || '').replace(',', '.')) || 0,
        labor_hours_fact: Number((document.getElementById('productionLaborHoursFact').value || '').replace(',', '.')) || 0,
        progress: Number(document.getElementById('productionProgress').value || 0) || 0,
        comment: document.getElementById('productionComment').value.trim(),
    };
    const errors = [];
    if (!payload.order_name) errors.push({ field: 'productionOrderName', message: 'Укажите название производственного заказа.' });
    if (!payload.responsible) errors.push({ field: 'productionResponsible', message: 'Укажите ответственного.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'productionOrderForm');
        return;
    }
    if (editingProductionId) {
        const lockOk = await acquireOpsEditLock('production_order', editingProductionId);
        if (!lockOk) return;
    }
    const endpoint = editingProductionId ? `/production/orders/${editingProductionId}` : '/production/orders';
    const method = editingProductionId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (editingProductionId) await releaseOpsEditLock('production_order');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось сохранить производственный заказ.'));
    selectedProductionOrderId = Number(res.id || editingProductionId || selectedProductionOrderId || 0);
    if (typeof markWorkflowFocus === 'function') markWorkflowFocus('production', selectedProductionOrderId);
    resetProductionForm();
    await renderProduction();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Производство', 'Производственный заказ сохранён');
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('[data-production-id].workflow-row-highlight, [data-production-id]');
}

window.presetProductionFlow = function(mode = 'order') {
    if (mode === 'order') {
        if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#productionOrderForm', { block: 'center' });
        if (typeof focusFieldById === 'function') focusFieldById('productionOrderName');
    }
};

function getSelectedProductionOrder() {
    return productionOrdersDB.find(item => Number(item.id) === Number(selectedProductionOrderId)) || null;
}

function selectProductionOrder(orderId) {
    selectedProductionOrderId = Number(orderId || 0);
    if (!selectedProductionOrderId && productionOrdersDB.length) {
        selectedProductionOrderId = Number(productionOrdersDB[0].id);
    }
}

async function saveProductionOperation() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('productionOperationForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('productionOperationForm');
    if (!selectedProductionOrderId) return customAlert('Сначала выбери производственный заказ.');
    const payload = {
        order_id: Number(selectedProductionOrderId || 0),
        sequence_no: Number(document.getElementById('productionOperationSequence').value || 1) || 1,
        operation_name: document.getElementById('productionOperationName').value.trim(),
        work_center: document.getElementById('productionOperationWorkCenter').value.trim(),
        status: document.getElementById('productionOperationStatus').value,
        planned_hours: Number((document.getElementById('productionOperationPlannedHours').value || '').replace(',', '.')) || 0,
        actual_hours: Number((document.getElementById('productionOperationActualHours').value || '').replace(',', '.')) || 0,
        planned_qty: Number((document.getElementById('productionOperationPlannedQty').value || '').replace(',', '.')) || 0,
        completed_qty: Number((document.getElementById('productionOperationCompletedQty').value || '').replace(',', '.')) || 0,
        scrap_qty: Number((document.getElementById('productionOperationScrapQty').value || '').replace(',', '.')) || 0,
        labor_rate: Number((document.getElementById('productionOperationLaborRate').value || '').replace(',', '.')) || 0,
        material_cost: Number((document.getElementById('productionOperationMaterialCost').value || '').replace(',', '.')) || 0,
        overhead_cost: Number((document.getElementById('productionOperationOverheadCost').value || '').replace(',', '.')) || 0,
        started_at: document.getElementById('productionOperationStartedAt').value.trim(),
        finished_at: document.getElementById('productionOperationFinishedAt').value.trim(),
        note: document.getElementById('productionOperationNote').value.trim(),
    };
    const errors = [];
    if (!payload.operation_name) errors.push({ field: 'productionOperationName', message: 'Укажите название операции.' });
    if (!payload.work_center) errors.push({ field: 'productionOperationWorkCenter', message: 'Укажите участок или рабочий центр.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'productionOperationForm');
        return;
    }
    if (editingProductionOperationId) {
        const lockOk = await acquireOpsEditLock('production_operation', editingProductionOperationId);
        if (!lockOk) return;
    }
    const endpoint = editingProductionOperationId ? `/production/operations/${editingProductionOperationId}` : '/production/operations';
    const method = editingProductionOperationId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (editingProductionOperationId) await releaseOpsEditLock('production_operation');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось сохранить производственную операцию.'));
    resetProductionOperationForm();
    await renderProduction();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Производство', 'Операция сохранена');
}

async function deleteProductionOperation(id) {
    if (!(await customConfirm('Удалить производственную операцию безвозвратно?'))) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('production', 'production_operation', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/production/operations/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось удалить операцию.'));
    if (editingProductionOperationId === id) resetProductionOperationForm();
    await renderProduction();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Производство', 'Операция удалена');
}

async function saveProductionBomItem() {
    if (!selectedProductionOrderId) return customAlert('Сначала выбери производственный заказ.');
    const payload = {
        order_id: Number(selectedProductionOrderId || 0),
        article: document.getElementById('productionBomArticle').value.trim(),
        item_name: document.getElementById('productionBomName').value.trim(),
        unit: document.getElementById('productionBomUnit').value.trim() || 'шт',
        qty_per_unit: Number((document.getElementById('productionBomQtyPerUnit').value || '').replace(',', '.')) || 0,
        planned_qty: Number((document.getElementById('productionBomPlannedQty').value || '').replace(',', '.')) || 0,
        actual_qty: Number((document.getElementById('productionBomActualQty').value || '').replace(',', '.')) || 0,
        unit_cost: Number((document.getElementById('productionBomUnitCost').value || '').replace(',', '.')) || 0,
        warehouse: document.getElementById('productionBomWarehouse').value.trim(),
        bin_code: document.getElementById('productionBomBin').value.trim(),
        note: document.getElementById('productionBomNote').value.trim(),
    };
    if (!payload.article && !payload.item_name) return customAlert('Укажи материал или артикул.');
    if (editingProductionBomId) {
        const lockOk = await acquireOpsEditLock('production_bom_item', editingProductionBomId);
        if (!lockOk) return;
    }
    const endpoint = editingProductionBomId ? `/production/bom/${editingProductionBomId}` : '/production/bom';
    const method = editingProductionBomId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (editingProductionBomId) await releaseOpsEditLock('production_bom_item');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось сохранить строку спецификации.'));
    resetProductionBomForm();
    await renderProduction();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Производство', 'Спецификация сохранена');
}

async function deleteProductionBomItem(id) {
    if (!(await customConfirm('Удалить материал из спецификации?'))) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('production', 'production_bom_item', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/production/bom/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось удалить строку спецификации.'));
    if (editingProductionBomId === id) resetProductionBomForm();
    await renderProduction();
    showToast('Производство', 'Строка спецификации удалена');
}

async function saveProductionRouteItem() {
    if (!selectedProductionOrderId) return customAlert('Сначала выбери производственный заказ.');
    const payload = {
        order_id: Number(selectedProductionOrderId || 0),
        sequence_no: Number(document.getElementById('productionRouteSequence').value || 1) || 1,
        operation_name: document.getElementById('productionRouteOperation').value.trim(),
        work_center: document.getElementById('productionRouteWorkCenter').value.trim(),
        planned_hours: Number((document.getElementById('productionRoutePlannedHours').value || '').replace(',', '.')) || 0,
        planned_qty: Number((document.getElementById('productionRoutePlannedQty').value || '').replace(',', '.')) || 0,
        labor_rate: Number((document.getElementById('productionRouteLaborRate').value || '').replace(',', '.')) || 0,
        note: document.getElementById('productionRouteNote').value.trim(),
    };
    if (!payload.operation_name) return customAlert('Укажи операцию маршрута.');
    if (editingProductionRouteId) {
        const lockOk = await acquireOpsEditLock('production_route_template', editingProductionRouteId);
        if (!lockOk) return;
    }
    const endpoint = editingProductionRouteId ? `/production/routes/${editingProductionRouteId}` : '/production/routes';
    const method = editingProductionRouteId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (editingProductionRouteId) await releaseOpsEditLock('production_route_template');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось сохранить маршрутный шаблон.'));
    resetProductionRouteForm();
    await renderProduction();
    showToast('Производство', 'Шаблон маршрута сохранён');
}

async function deleteProductionRouteItem(id) {
    if (!(await customConfirm('Удалить шаблон маршрута?'))) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('production', 'production_route_template', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/production/routes/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось удалить шаблон маршрута.'));
    if (editingProductionRouteId === id) resetProductionRouteForm();
    await renderProduction();
    showToast('Производство', 'Шаблон маршрута удалён');
}

async function applyProductionRouteTemplates() {
    if (!selectedProductionOrderId) return customAlert('Сначала выбери производственный заказ.');
    const res = await apiCall(`/production/orders/${selectedProductionOrderId}/apply_route`, 'POST', {});
    if (!res || res.error) return customAlert(res?.error || 'Не удалось развернуть маршрут.');
    await renderProduction();
    showToast('Производство', `Маршрут развёрнут: ${res.created || 0} операций`);
}

async function renderSupply() {
    if (typeof loadProjects === 'function' && (!Array.isArray(projectsDB) || !projectsDB.length)) {
        try { await loadProjects(); } catch (_e) {}
    }
    if (typeof loadClients === 'function' && (!Array.isArray(clientsDB) || !clientsDB.length)) {
        try { await loadClients(); } catch (_e) {}
    }
    await loadOpsData();
    populateOpsSelects();
    applyOpsFieldPermissions();
    bindPurchaseDraftAutosave();
    bindPurchaseSmartHints();
    syncSupplyEditorState();
    if (typeof window.switchSupplyWorkspaceTab === 'function') {
        window.switchSupplyWorkspaceTab(window.supplyActiveWorkspaceTab || 'purchase');
    }
    const metrics = supplySummaryDB?.metrics || {};
    renderSupplyRoleWorkbench(metrics);
    const metricsGrid = document.getElementById('supplyMetricsGrid');
    const cockpitMount = document.getElementById('supplyCockpitMount');
    const tbody = document.getElementById('purchasesTable');
    const reservationsList = document.getElementById('stockReservationsList');
    if (!metricsGrid || !tbody || !reservationsList) return;
    registerOpsSavedFilters(
        'supply',
        'supplySavedFiltersMount',
        supplyListFilter === 'this_week' ? 'Поставки на этой неделе' : 'Мой фильтр склада',
        () => supplyListFilter,
        value => { supplyListFilter = value || 'all'; },
        renderSupply,
        [
            { id: 'supplyFilterAllBtn', key: 'all', label: 'Все' },
            { id: 'supplyFilterThisWeekBtn', key: 'this_week', label: 'Эта неделя' },
            { id: 'supplyFilterInTransitBtn', key: 'in_transit', label: 'В пути' },
            { id: 'supplyFilterReceivedBtn', key: 'received', label: 'Получено' },
            { id: 'supplyFilterReservationsBtn', key: 'reservations', label: 'Резервы' },
        ]
    );
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">План закупок</div><div class="metric-value">${formatMoney(metrics.planned_purchases || 0)}</div></div>
        <div class="metric-card warning"><div class="metric-title">В пути</div><div class="metric-value">${formatMoney(metrics.in_transit || 0)}</div></div>
        <div class="metric-card success"><div class="metric-title">Получено</div><div class="metric-value">${formatMoney(metrics.received_total || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">Резервов под проекты</div><div class="metric-value">${metrics.reserved_positions || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Зарезервировано, шт</div><div class="metric-value">${Number(metrics.reserved_qty || 0).toLocaleString('ru-RU')}</div></div>
        <div class="metric-card success"><div class="metric-title">Свободный остаток</div><div class="metric-value">${Number(metrics.free_stock_qty || 0).toLocaleString('ru-RU')}</div></div>
        <div class="metric-card warning"><div class="metric-title">Партий на складе</div><div class="metric-value">${metrics.lot_positions || 0}</div></div>
        <div class="metric-card danger"><div class="metric-title">Дефициты</div><div class="metric-value">${metrics.shortages || 0}</div></div>
    `;
    if (cockpitMount) cockpitMount.innerHTML = renderSupplyCockpit(metrics);
    const visiblePurchases = getVisiblePurchases();
    const visibleReservations = getVisibleStockReservations();
    pruneOpsBulkSelection('supply', visiblePurchases);
    renderOpsBulkToolbar('supply');
    tbody.innerHTML = visiblePurchases.length ? visiblePurchases.map(item => `
        <tr data-purchase-id="${item.id}" class="${typeof isWorkflowFocused === 'function' && isWorkflowFocused('purchase', item.id) ? 'workflow-row-highlight' : ''}">
            <td>${renderOpsBulkCheckbox('supply', item.id)}</td>
            <td><div class="finance-row-title">${item.item_name}</div><div class="finance-row-meta">${item.item_article || 'Без артикула'} · ${item.qty || 0} ${item.unit || 'шт'}</div></td>
            <td>${projectAndClientMeta(item)}</td>
            <td><div class="finance-row-title">${item.supplier || '—'}</div><div class="finance-row-meta">${item.comment || 'Без комментария'}</div></td>
            <td><div class="finance-row-title">${formatMoney(item.total_amount || 0)}</div><div class="finance-row-meta">${item.unit_price ? `${formatMoney(item.unit_price || 0)} / ${item.unit || 'шт'}` : 'Цена не указана'}</div></td>
            <td><div class="finance-row-title">${item.expected_date || '—'}</div><div class="finance-row-meta">${item.received_date || 'Ожидается'}</div></td>
            <td><span class="status-badge ${purchaseStatusClass(item.status)}">${financeStatusLabel(item.status)}</span><div class="finance-row-meta">${item.linked_payment_id ? `Оплата #${item.linked_payment_id} · ${financeStatusLabel(item.linked_payment_status || 'planned')} · 1С ${opsDisplayStatus(item.linked_payment_exchange_state || 'draft')}` : 'Оплата создаётся автоматически'}</div></td>
            <td><div class="view-actions">${typeof renderEntityFavoriteButton === 'function' ? renderEntityFavoriteButton('purchase_order', item.id, item.item_name || item.item_article || `Закупка #${item.id}`, `${item.supplier || ''} · ${formatMoney(item.total_amount || 0)} · ${financeStatusLabel(item.status)}`, 'supply', 'renderSupply') : ''}${typeof renderEntityWatchButton === 'function' ? renderEntityWatchButton('purchase_order', item.id, item.item_name || item.item_article || `Закупка #${item.id}`, `${item.supplier || ''} · срок ${item.expected_date || '—'}`, 'supply', 'renderSupply', 'overdue') : ''}<button class="btn-secondary" onclick="openEntityCard('purchase_order', ${item.id})">Карточка</button><button class="btn-secondary" onclick="editPurchase(${item.id})">Редактировать</button><button class="btn-secondary" onclick="duplicatePurchase(${item.id})">Создать похожую</button><button class="btn-danger" onclick="deletePurchase(${item.id})">Удалить</button></div></td>
        </tr>
    `).join('') : '<tr><td colspan="8" class="nsi-empty-row">Закупок по текущему фильтру нет.</td></tr>';
    reservationsList.innerHTML = visibleReservations.length ? visibleReservations.slice(0, 8).map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.nomenclature_name}</div>
                <div class="client360-item-meta">${item.nomenclature_article || 'Без артикула'} · ${item.qty} шт · остаток к выдаче ${item.remaining_qty || 0}</div>
                <div class="client360-item-meta">${item.warehouse || 'Источник не выбран'} / ${item.bin_code || 'ячейка не указана'}${item.batch_code ? ` · партия ${item.batch_code}` : ''}${item.serial_no ? ` · серийный ${item.serial_no}` : ''}</div>
            </div>
            <div class="view-actions">
                <span class="status-badge ${item.status === 'fulfilled' ? 'status-completed' : item.status === 'shortage' ? 'status-overdue' : 'status-active'}">${opsDisplayStatus(item.status)}</span>
                ${Number(item.remaining_qty || 0) > 0 && item.status !== 'shortage' ? `<button class="btn-secondary" onclick="fulfillReservation(${item.id})">Исполнить</button>` : ''}
            </div>
        </div>
    `).join('') : '<div class="empty-state">Резервов под проекты по текущему фильтру нет.</div>';
}

async function renderSales() {
    await loadOpsData();
    populateOpsSelects();
    applyOpsFieldPermissions();
    const metrics = salesSummaryDB?.metrics || {};
    const metricsGrid = document.getElementById('salesMetricsGrid');
    const cockpitMount = document.getElementById('salesCockpitMount');
    const tbody = document.getElementById('salesDocumentsTable');
    if (!metricsGrid || !tbody) return;
    registerOpsSavedFilters(
        'sales',
        'salesSavedFiltersMount',
        salesListFilter === 'overdue_payment' ? 'Просроченные оплаты продаж' : 'Мой фильтр продаж',
        () => salesListFilter,
        value => { salesListFilter = value || 'all'; },
        renderSales,
        [
            { id: 'salesFilterAllBtn', key: 'all', label: 'Все' },
            { id: 'salesFilterUnpaidBtn', key: 'unpaid', label: 'Не оплачено' },
            { id: 'salesFilterOverdueBtn', key: 'overdue_payment', label: 'Просрочка оплаты' },
            { id: 'salesFilterShipmentRiskBtn', key: 'shipment_risk', label: 'Риск отгрузки' },
            { id: 'salesFilterDraftBtn', key: 'draft', label: 'Черновики' },
        ]
    );
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">Черновики</div><div class="metric-value">${metrics.drafts || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Выставлено</div><div class="metric-value">${metrics.issued || 0}</div></div>
        <div class="metric-card success"><div class="metric-title">Подписано</div><div class="metric-value">${metrics.signed || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Сумма реализации</div><div class="metric-value">${formatMoney(metrics.amount_total || 0)}</div></div>
    `;
    if (cockpitMount) cockpitMount.innerHTML = renderSalesCockpit(metrics);
    const visibleSalesDocs = getVisibleSalesDocs();
    pruneOpsBulkSelection('sales', visibleSalesDocs);
    renderOpsBulkToolbar('sales');
    tbody.innerHTML = visibleSalesDocs.length ? visibleSalesDocs.map(item => `
        <tr data-sales-id="${item.id}" class="${typeof isWorkflowFocused === 'function' && isWorkflowFocused('sales', item.id) ? 'workflow-row-highlight' : ''}">
            <td>${renderOpsBulkCheckbox('sales', item.id)}</td>
            <td><div class="finance-row-title">${salesDocLabel(item.doc_type)} ${item.doc_number || ''}</div><div class="finance-row-meta">${item.doc_date || ''}</div></td>
            <td>${projectAndClientMeta(item)}</td>
            <td><div class="finance-row-title">${formatMoney(item.amount, item.currency)}</div><div class="finance-row-meta">${item.comment || 'Без комментария'}</div></td>
            <td><span class="status-badge ${financeStatusClass(item.status)}">${financeStatusLabel(item.status)}</span><div class="finance-row-meta">${item.price_list_name || 'без прайса'}${Number(item.discount_percent || 0) > 0 || Number(item.discount_amount || 0) > 0 ? ` · скидка ${item.discount_percent || 0}% / ${formatMoney(item.discount_amount || 0, item.currency)}` : ''}</div></td>
            <td>
                <div><span class="status-badge ${salesSentClass(item.sent_status)}">${salesSentLabel(item.sent_status)}</span></div>
                <div class="finance-row-meta">${item.recipient_email || 'Получатель не задан'}</div>
                <div class="finance-row-meta">${item.confirmed_at || item.delivered_at || item.sent_at || 'Дата отправки не зафиксирована'}</div>
                <div class="finance-row-meta">${item.customer_order_no || 'Без номера заказа'}${item.planned_ship_date ? ` · отгр. ${item.planned_ship_date}` : ''}</div>
            </td>
            <td><div><span class="status-badge ${financeStatusClass(item.payment_status)}">${financeStatusLabel(item.payment_status)}</span></div><div class="finance-row-meta">${item.linked_payment_id ? `Связана с оплатой #${item.linked_payment_id} · ${financeStatusLabel(item.linked_payment_status || item.payment_status)} · 1С ${opsDisplayStatus(item.linked_payment_exchange_state || 'draft')}` : 'Оплата создаётся автоматически'}</div><div class="finance-row-meta">${item.payment_due_date || 'Срок оплаты не задан'}${item.reserve_status && item.reserve_status !== 'none' ? ` · резерв ${item.reserve_qty || 0}` : ''}</div></td>
            <td><div class="view-actions">${typeof renderEntityFavoriteButton === 'function' ? renderEntityFavoriteButton('sales_document', item.id, `${salesDocLabel(item.doc_type)} ${item.doc_number || `#${item.id}`}`, `${item.client_name || ''} · ${formatMoney(item.amount, item.currency)} · ${financeStatusLabel(item.status)}`, 'sales', 'renderSales') : ''}<button class="btn-secondary" onclick="openEntityCard('sales_document', ${item.id})">Карточка</button><button class="btn-secondary" onclick="editSalesDocument(${item.id})">Редактировать</button><button class="btn-secondary" onclick="duplicateSalesDocument(${item.id})">Создать похожий</button><button class="btn-danger" onclick="deleteSalesDocument(${item.id})">Удалить</button></div></td>
        </tr>
    `).join('') : '<tr><td colspan="8" class="nsi-empty-row">Документов реализации по текущему фильтру нет.</td></tr>';
}

function opsHealthBadgeClass(bucket) {
    if (['stable', 'active', 'ok', 'delivered'].includes(String(bucket || ''))) return 'status-completed';
    if (['risk', 'overdue', 'late', 'expired', 'failed'].includes(String(bucket || ''))) return 'status-overdue';
    return 'status-active';
}

function opsDisplayStatus(value, fallback = 'Статус') {
    const raw = String(value || '').trim();
    if (!raw) return fallback;
    const labels = {
        draft: 'Черновик',
        active: 'Активно',
        archived: 'Архив',
        planned: 'Запланировано',
        partial: 'Частично',
        delivered: 'Доставлено',
        late: 'Опаздывает',
        done: 'Выполнено',
        in_progress: 'В работе',
        otk: 'ОТК',
        ready: 'Готово',
        stable: 'Стабильно',
        attention: 'Требует внимания',
        risk: 'Риск',
        expired: 'Истёк',
        open: 'Открыто',
        closed: 'Закрыто',
        approved: 'Согласовано',
        resolved: 'Решено',
        released: 'Выпущено',
        hold: 'Удержание',
        queued: 'В очереди',
        retry: 'Повтор',
        processing: 'Обработка',
        synced: 'Синхронизировано',
        failed: 'Ошибка',
        conflict: 'Конфликт',
        fulfilled: 'Исполнено',
        shortage: 'Дефицит',
        not_shipped: 'Не отгружено',
        shipped: 'Отгружено',
        collecting: 'Сбор титулов',
        sent: 'Отправлено',
        accepted: 'Принято',
        error: 'Ошибка',
        none: 'Не задано',
    };
    if (labels[raw]) return labels[raw];
    if (typeof financeTranslateLabel === 'function') return financeTranslateLabel(raw, fallback);
    if (typeof enterpriseStatusLabel === 'function') return enterpriseStatusLabel(raw);
    return raw.replace(/_/g, ' ');
}

function salesQuoteStageLabel(stage) {
    const labels = {
        draft: 'Черновик',
        proposal: 'Отправлено',
        negotiation: 'Переговоры',
        won: 'Выиграно',
        lost: 'Проиграно',
    };
    return labels[String(stage || 'draft')] || String(stage || 'Черновик');
}

function renderSalesCockpit(metrics = {}) {
    const summary = opsExtendedDB.salesSummary || {};
    const pipeline = Array.isArray(summary.pipeline) ? summary.pipeline : [];
    const clientHealth = Array.isArray(summary.client_health) ? summary.client_health : [];
    const priceLifecycle = Array.isArray(summary.price_lifecycle) ? summary.price_lifecycle : [];
    const planFact = Array.isArray(summary.plan_fact) ? summary.plan_fact : [];
    const quotes = Array.isArray(opsExtendedDB.quotes) ? opsExtendedDB.quotes : [];
    const topQuotes = quotes.slice(0, 4).map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.title || item.quote_number || 'КП'}</div>
                <div class="client360-item-meta">${item.client_name || 'без клиента'} · ${salesQuoteStageLabel(item.stage)}${item.probability ? ` · ${item.probability}%` : ''}${item.days_to_valid_until != null ? ` · ${item.days_to_valid_until} дн.` : ''}</div>
            </div>
            <div class="view-actions">
                <span class="client360-item-side">${formatMoney(item.amount || 0, item.currency || 'RUB')}</span>
                <button class="btn-secondary" onclick="prefillSalesFromQuoteX(${item.id})">В реализацию</button>
            </div>
        </div>
    `).join('');
    const alerts = [
        Number(metrics.overdue_docs || 0) ? `<div class="client360-item"><div><div class="client360-item-title">Просрочены сроки оплаты</div><div class="client360-item-meta">Документов: ${metrics.overdue_docs || 0}</div></div><div class="client360-item-side danger-text">${formatMoney(metrics.overdue_receivables || 0)}</div></div>` : '',
        Number(metrics.shipment_risk_docs || 0) ? `<div class="client360-item"><div><div class="client360-item-title">Срыв плановой отгрузки</div><div class="client360-item-meta">Документов: ${metrics.shipment_risk_docs || 0}</div></div><div class="client360-item-side">${metrics.shipment_risk_docs || 0}</div></div>` : '',
        Number(metrics.customer_risk_clients || 0) ? `<div class="client360-item"><div><div class="client360-item-title">Клиенты в зоне риска</div><div class="client360-item-meta">Оплаты, возвраты, сроки сервиса</div></div><div class="client360-item-side">${metrics.customer_risk_clients || 0}</div></div>` : '',
    ].filter(Boolean).join('');
    return `
        <div class="section-header">
            <div>
                <h3 class="section-title">Коммерческий пульт</h3>
                <p class="section-subtitle">Первый экран для продаж: воронка, план-факт, состояние клиентов, прайсы и сигналы по оплате и отгрузке.</p>
            </div>
            <div class="view-actions">
                <button class="btn-secondary" onclick="document.getElementById('salesExtendedMount')?.scrollIntoView({behavior:'smooth', block:'start'})">К КП и прайсам</button>
                <button class="btn-secondary" onclick="document.getElementById('salesProjectId')?.focus()">Новый документ</button>
            </div>
        </div>
        <div class="project-ops-grid">
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Поток и план-факт</h4>
                <div class="ops-summary-grid">
                    <div class="ops-summary-stat"><div class="ops-summary-label">Активные КП</div><div class="ops-summary-value">${metrics.quotes_active || 0}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">План продаж</div><div class="ops-summary-value">${formatMoney(metrics.sales_plan_amount || 0)}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Факт продаж</div><div class="ops-summary-value">${formatMoney(metrics.sales_fact_amount || 0)}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Отклонение</div><div class="ops-summary-value">${formatMoney(metrics.sales_plan_delta || 0)}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Прайсы / версии</div><div class="ops-summary-value">${metrics.price_lists || 0} / ${metrics.price_list_versions || 0}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Высокие скидки</div><div class="ops-summary-value">${metrics.high_discount_docs || 0}</div></div>
                </div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Коммерческие сигналы</h4>
                <div class="project-ops-summary-list">${alerts || '<div class="empty-state">Критичных коммерческих сигналов сейчас нет.</div>'}</div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Воронка и состояние клиентов</h4>
                <div class="client360-list">${renderSimpleList(pipeline.slice(0, 5), 'Воронка пока пустая.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.label}</div>
                            <div class="client360-item-meta">${item.count || 0} шт. · ${formatMoney(item.amount || 0)}</div>
                        </div>
                        <span class="status-badge ${item.stage === 'won' ? 'status-completed' : item.stage === 'lost' ? 'status-overdue' : 'status-active'}">${item.stage}</span>
                    </div>
                `)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(clientHealth.slice(0, 4), 'Клиентский health пока не собран.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.client_name || 'Клиент'}</div>
                            <div class="client360-item-meta">${Array.isArray(item.reasons) ? item.reasons.join(' · ') : 'цикл стабилен'} · выручка ${formatMoney(item.revenue || 0)}</div>
                        </div>
                        <span class="status-badge ${opsHealthBadgeClass(item.health_bucket)}">${item.health_score || 0}</span>
                    </div>
                `)}</div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Прайсы и быстрые КП</h4>
                <div class="client360-list">${renderSimpleList(priceLifecycle.slice(0, 4), 'Прайсы пока не настроены.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.name}</div>
                            <div class="client360-item-meta">${item.item_article || 'без артикула'} · ${formatMoney(item.base_price || 0, item.currency || 'RUB')} · v${item.version_no || 1}/${item.version_total || 1}</div>
                        </div>
                        <span class="status-badge ${opsHealthBadgeClass(item.lifecycle_state === 'expired' ? 'risk' : item.lifecycle_state === 'active' ? 'stable' : 'attention')}">${opsDisplayStatus(item.lifecycle_state || 'active')}</span>
                    </div>
                `)}</div>
                <div class="client360-list" style="margin-top:12px;">${topQuotes || '<div class="empty-state">Коммерческих предложений пока нет.</div>'}</div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">План-факт по направлениям</h4>
                <div class="client360-list">${renderSimpleList(planFact.slice(0, 4), 'Планов продаж пока нет.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.period_key || 'Период'}</div>
                            <div class="client360-item-meta">${item.client_id ? `client #${item.client_id}` : (item.project_id ? `project #${item.project_id}` : 'общий план')} · план ${formatMoney(item.target_amount || 0)} · факт ${formatMoney(item.actual_amount || 0)}</div>
                        </div>
                        <span class="status-badge ${opsHealthBadgeClass(Number(item.delta || 0) >= 0 ? 'stable' : 'attention')}">${formatMoney(item.delta || 0)}</span>
                    </div>
                `)}</div>
            </div>
        </div>
    `;
}

function renderSupplyCockpit(metrics = {}) {
    const summary = opsExtendedDB.supplySummary || {};
    const supplierHealth = Array.isArray(summary.supplier_health) ? summary.supplier_health : [];
    const planFact = Array.isArray(summary.plan_fact) ? summary.plan_fact : [];
    const scheduleAlerts = Array.isArray(summary.schedule_alerts) ? summary.schedule_alerts : [];
    const riskPurchases = Array.isArray(summary.late_purchases) ? summary.late_purchases : [];
    return `
        <div class="section-header">
            <div>
                <h3 class="section-title">Пульт снабжения</h3>
                <p class="section-subtitle">План-факт закупки, здоровье поставщиков, графики поставок и сигналы по недопоставке, срокам и цене.</p>
            </div>
            <div class="view-actions">
                <button class="btn-secondary" onclick="document.getElementById('supplyExtendedMount')?.scrollIntoView({behavior:'smooth', block:'start'})">К поставщикам и графикам</button>
                <button class="btn-secondary" onclick="presetSupplyMode('purchase')">Новая закупка</button>
            </div>
        </div>
        <div class="project-ops-grid">
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">План и исполнение</h4>
                <div class="ops-summary-grid">
                    <div class="ops-summary-stat"><div class="ops-summary-label">План</div><div class="ops-summary-value">${formatMoney(metrics.purchase_plan_amount || 0)}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Факт</div><div class="ops-summary-value">${formatMoney(metrics.purchase_fact_amount || 0)}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Отклонение</div><div class="ops-summary-value">${formatMoney(metrics.purchase_plan_delta || 0)}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Недопоставка</div><div class="ops-summary-value">${metrics.underdelivery_cases || 0} / ${Number(metrics.underdelivery_qty || 0).toLocaleString('ru-RU')}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Опоздания</div><div class="ops-summary-value">${metrics.late_deliveries || 0}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Цена vs план</div><div class="ops-summary-value">${formatMoney(metrics.price_variance_total || 0)}</div></div>
                </div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Поставщики в фокусе</h4>
                <div class="client360-list">${renderSimpleList(supplierHealth.slice(0, 5), 'Поставщики пока не оценены.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.supplier_name || 'Поставщик'}</div>
                            <div class="client360-item-meta">${Array.isArray(item.reasons) ? item.reasons.join(' · ') : 'цикл поставок стабильный'} · рейтинг ${item.rating || 0} · надёжность ${item.reliability_percent || 0}%</div>
                        </div>
                        <span class="status-badge ${opsHealthBadgeClass(item.health_bucket)}">${item.health_score || 0}</span>
                    </div>
                `)}</div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Графики и риски</h4>
                <div class="client360-list">${renderSimpleList(scheduleAlerts.slice(0, 4), 'Просроченных графиков поставки сейчас нет.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.supplier_name || `Закупка #${item.purchase_id}`}</div>
                            <div class="client360-item-meta">${item.scheduled_date || 'без даты'} · остаток ${Number(item.remaining_qty || 0).toLocaleString('ru-RU')} · опоздание ${item.late_days || 0} дн.</div>
                        </div>
                        <span class="status-badge ${opsHealthBadgeClass(item.risk_status)}">${opsDisplayStatus(item.risk_status || 'stable')}</span>
                    </div>
                `)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(riskPurchases.slice(0, 4), 'Критичных закупок по срокам сейчас нет.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.item_name || item.item_article || 'Закупка'}</div>
                            <div class="client360-item-meta">${item.supplier_name || item.supplier || 'поставщик не задан'} · опоздание ${item.delivery_delay_days || 0} дн. · недопоставка ${Number(item.underdelivery_qty || 0).toLocaleString('ru-RU')}</div>
                        </div>
                        <span class="status-badge ${opsHealthBadgeClass(item.delivery_delay_days > 0 ? 'risk' : 'attention')}">${formatMoney(item.total_amount || 0, item.currency || 'RUB')}</span>
                    </div>
                `)}</div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">План-факт по позициям</h4>
                <div class="client360-list">${renderSimpleList(planFact.slice(0, 4), 'Планы закупок пока не заведены.', item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.period_key || 'Период'} · ${item.item_article || 'без артикула'}</div>
                            <div class="client360-item-meta">${item.supplier_name || 'без поставщика'} · план ${formatMoney(item.target_amount || 0)} · факт ${formatMoney(item.fact_amount || 0)}</div>
                        </div>
                        <span class="status-badge ${opsHealthBadgeClass(Number(item.delta_amount || 0) <= 0 ? 'stable' : 'attention')}">${formatMoney(item.delta_amount || 0)}</span>
                    </div>
                `)}</div>
            </div>
        </div>
    `;
}

async function renderProduction() {
    await loadOpsData();
    populateOpsSelects();
    applyOpsFieldPermissions();
    bindProductionDraftAutosave();
    bindProductionSmartHints();
    renderProductionRoleWorkbench();
    const metrics = productionSummaryDB?.metrics || {};
    const metricsGrid = document.getElementById('productionMetricsGrid');
    const tbody = document.getElementById('productionOrdersTable');
    const operationsTbody = document.getElementById('productionOperationsTable');
    const caption = document.getElementById('productionOperationsCaption');
    const bomTbody = document.getElementById('productionBomTable');
    const routesTbody = document.getElementById('productionRoutesTable');
    const bomCaption = document.getElementById('productionBomCaption');
    const routeCaption = document.getElementById('productionRouteCaption');
    const bottlenecksList = document.getElementById('productionBottlenecksList');
    const discrepanciesList = document.getElementById('productionDiscrepanciesList');
    const cockpitTarget = document.getElementById('productionCockpitMount');
    if (!metricsGrid || !tbody || !operationsTbody || !bomTbody || !routesTbody) return;
    registerOpsSavedFilters(
        'production',
        'productionSavedFiltersMount',
        productionListFilter === 'critical' ? 'Критичные производственные заказы' : 'Мой фильтр производства',
        () => productionListFilter,
        value => { productionListFilter = value || 'all'; },
        renderProduction,
        [
            { id: 'productionFilterAllBtn', key: 'all', label: 'Все' },
            { id: 'productionFilterQueueBtn', key: 'queue', label: 'Очередь' },
            { id: 'productionFilterInWorkBtn', key: 'in_work', label: 'В работе' },
            { id: 'productionFilterCriticalBtn', key: 'critical', label: 'Критичные' },
            { id: 'productionFilterLateBtn', key: 'late', label: 'Срыв срока' },
        ]
    );
    if (!selectedProductionOrderId && productionOrdersDB.length) {
        selectedProductionOrderId = Number(productionOrdersDB[0].id);
    }
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">Очередь</div><div class="metric-value">${metrics.queue || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">В работе</div><div class="metric-value">${metrics.in_work || 0}</div></div>
        <div class="metric-card success"><div class="metric-title">Готово</div><div class="metric-value">${metrics.done || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Средний прогресс</div><div class="metric-value">${metrics.avg_progress || 0}%</div></div>
        <div class="metric-card"><div class="metric-title">Операций</div><div class="metric-value">${metrics.operations_total || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Позиций спецификации</div><div class="metric-value">${metrics.bom_items_total || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Шаблонов маршрута</div><div class="metric-value">${metrics.route_templates_total || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Трудозатраты факт</div><div class="metric-value">${Number(metrics.labor_hours_fact || 0).toLocaleString('ru-RU')} ч</div></div>
        <div class="metric-card warning"><div class="metric-title">Фактическая себестоимость</div><div class="metric-value">${formatMoney(metrics.actual_cost_total || 0)}</div></div>
        <div class="metric-card warning"><div class="metric-title">Материалы план</div><div class="metric-value">${formatMoney(metrics.planned_material_cost || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">Материалы факт</div><div class="metric-value">${formatMoney(metrics.actual_material_cost || 0)}</div></div>
        <div class="metric-card danger"><div class="metric-title">Брак</div><div class="metric-value">${Number(metrics.scrap_qty_total || 0).toLocaleString('ru-RU')}</div></div>
    `;
    if (bottlenecksList) {
        const bottlenecks = Array.isArray(productionSummaryDB?.bottlenecks) ? productionSummaryDB.bottlenecks : [];
        bottlenecksList.innerHTML = bottlenecks.length ? bottlenecks.map(item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.work_center || 'Без участка'}</div>
                    <div class="client360-item-meta">Активно: ${item.in_progress || 0} · всего операций: ${item.operations || 0}</div>
                </div>
                <div class="client360-item-side">${Number(item.hours || 0).toLocaleString('ru-RU')} ч</div>
            </div>
        `).join('') : `
            <div class="empty-action-state">
                <div class="empty-state">Узких мест по участкам пока не видно.</div>
                <div class="empty-state-actions">
                    <button class="btn-secondary" onclick="focusProductionQueue()">Открыть очередь</button>
                    <button class="btn-secondary" onclick="focusProductionDeepSection()">Глубокий контур</button>
                </div>
            </div>
        `;
    }
    if (discrepanciesList) {
        discrepanciesList.innerHTML = stockDiscrepancyActsDB.length ? stockDiscrepancyActsDB.slice(0, 8).map(item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.nomenclature_name || item.article || 'Материал'}</div>
                    <div class="client360-item-meta">${item.doc_number || 'Акт'} · ${item.warehouse || 'Склад'}${item.bin_code ? ` / ${item.bin_code}` : ''}</div>
                    <div class="client360-item-meta">${item.reason || 'Расхождение остатков'} · корректировка ${Number(item.adjustment_qty || 0).toLocaleString('ru-RU')} ${item.unit || 'шт'}</div>
                </div>
                <div class="client360-item-side">${item.created_at ? new Date(Number(item.created_at) * 1000).toLocaleDateString('ru-RU') : '—'}</div>
            </div>
        `).join('') : `
            <div class="empty-action-state">
                <div class="empty-state">Материальных расхождений сейчас нет.</div>
                <div class="empty-state-actions">
                    <button class="btn-secondary" onclick="openSupplyFromProduction()">Открыть склад</button>
                </div>
            </div>
        `;
    }
    const selectedOrder = getSelectedProductionOrder();
    renderOrderExecutionDashboard();
    if (cockpitTarget) {
        const selectedOperations = selectedOrder ? productionOperationsDB.filter(item => Number(item.order_id) === Number(selectedOrder.id)) : [];
        const selectedBomItems = selectedOrder ? productionBomDB.filter(item => Number(item.order_id) === Number(selectedOrder.id)) : [];
        const inWorkOrders = productionOrdersDB.filter(item => item.stage === 'in_work').length;
        const criticalOrders = productionOrdersDB.filter(item => item.priority === 'critical').length;
        const totalScrap = Number(metrics.scrap_qty_total || 0).toLocaleString('ru-RU');
        const terminalMetrics = opsExtendedDB.terminalSummary?.metrics || {};
        const productionTerminalEvents = Array.isArray(opsExtendedDB.terminalSummary?.production_events) ? opsExtendedDB.terminalSummary.production_events : [];
        const productionTerminalScans = Array.isArray(opsExtendedDB.terminalSummary?.scans) ? opsExtendedDB.terminalSummary.scans.filter(item => item.terminal_type === 'production') : [];
        cockpitTarget.innerHTML = `
            <section class="surface-card surface-card--padded erp-cockpit-card">
                <div class="erp-cockpit-heading">
                    <div>
                        <h3 class="section-title">Пульт производства</h3>
                        <p class="section-subtitle">Быстрый ответ для цеха: где перегруз, сколько критичных заказов и что сейчас выбрано в фокус.</p>
                    </div>
                    <span class="ops-section-chip">Цех</span>
                </div>
                <div class="erp-cockpit-stats">
                    <div class="erp-cockpit-stat">
                        <div class="erp-cockpit-label">В работе / критичных</div>
                        <div class="erp-cockpit-value">${inWorkOrders} / ${criticalOrders}</div>
                    </div>
                    <div class="erp-cockpit-stat">
                        <div class="erp-cockpit-label">Брак / трудозатраты</div>
                        <div class="erp-cockpit-value">${totalScrap} / ${Number(metrics.labor_hours_fact || 0).toLocaleString('ru-RU')} ч</div>
                    </div>
                    <div class="erp-cockpit-stat">
                        <div class="erp-cockpit-label">Себестоимость факт</div>
                        <div class="erp-cockpit-value">${formatMoney(metrics.actual_cost_total || 0)}</div>
                    </div>
                </div>
            </section>
            <section class="surface-card surface-card--padded erp-cockpit-card">
                <div class="erp-cockpit-heading">
                    <div>
                        <h3 class="section-title">Текущий заказ</h3>
                        <p class="section-subtitle">${selectedOrder ? 'Выбранный заказ собран в одном блоке: этап, выпуск, операции и материалы.' : 'Выбери заказ из очереди, и здесь появится его короткая карта.'}</p>
                    </div>
                </div>
                ${selectedOrder ? `
                    <div class="erp-cockpit-highlight">
                        <div class="erp-cockpit-highlight-title">${selectedOrder.order_name || 'Заказ'}</div>
                        <div class="erp-cockpit-highlight-meta">${productionStageLabel(selectedOrder.stage)} · ${selectedOrder.progress || 0}% · ${selectedOrder.responsible || 'Ответственный не задан'}</div>
                    </div>
                    <div class="erp-cockpit-alerts">
                        <div class="erp-cockpit-alert">Операций: ${selectedOperations.length}</div>
                        <div class="erp-cockpit-alert">Позиций спецификации: ${selectedBomItems.length}</div>
                        <div class="erp-cockpit-alert">План / факт: ${Number(selectedOrder.planned_qty_total || selectedOrder.planned_qty || 0).toLocaleString('ru-RU')} / ${Number(selectedOrder.produced_qty_total || selectedOrder.produced_qty || 0).toLocaleString('ru-RU')}</div>
                    </div>
                ` : '<div class="empty-state">Нет активного заказа в фокусе.</div>'}
            </section>
            <section class="surface-card surface-card--padded erp-cockpit-card">
                <div class="erp-cockpit-heading">
                    <div>
                        <h3 class="section-title">Цеховой RF-режим</h3>
                        <p class="section-subtitle">Оперативное исполнение с терминала: старт, выпуск, брак и ОТК по операции или штрихкоду OP-123.</p>
                    </div>
                    <span class="ops-section-chip">RF</span>
                </div>
                <div class="erp-cockpit-stats">
                    <div class="erp-cockpit-stat"><div class="erp-cockpit-label">Терминалы цеха</div><div class="erp-cockpit-value">${terminalMetrics.production_sessions || 0}</div></div>
                    <div class="erp-cockpit-stat"><div class="erp-cockpit-label">Сканов цеха</div><div class="erp-cockpit-value">${productionTerminalScans.length}</div></div>
                    <div class="erp-cockpit-stat"><div class="erp-cockpit-label">Событий исполнения</div><div class="erp-cockpit-value">${terminalMetrics.production_events || productionTerminalEvents.length}</div></div>
                </div>
                <div class="finance-form-grid" style="margin-top:12px;">
                    <input id="productionTerminalCodeX" class="auth-input" style="margin:0;" placeholder="Терминал, например SHOP-01">
                    <input id="productionTerminalOperationIdX" class="auth-input" style="margin:0;" placeholder="Операция ID или OP-123">
                    <select id="productionTerminalActionX" class="auth-input" style="margin:0;"><option value="production_start">Старт</option><option value="production_complete">Выпуск</option><option value="production_scrap">Брак</option><option value="quality_hold">ОТК hold</option></select>
                    <input id="productionTerminalQtyX" class="auth-input" style="margin:0;" placeholder="Количество">
                    <input id="productionTerminalHoursX" class="auth-input" style="margin:0;" placeholder="Факт часов">
                    <button class="btn-primary" onclick="submitProductionTerminalEventX()">Записать событие</button>
                </div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(productionTerminalEvents.slice(0, 4), 'Цеховых терминальных событий пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.operation_name || item.event_type || 'Операция'} · ${item.qty || 0}</div><div class="client360-item-meta">${item.order_name || `Заказ #${item.order_id || 0}`} · ${item.executor_name || item.created_by || 'исполнитель'}</div></div><span class="status-badge ${opsHealthBadgeClass(item.event_type === 'scrap' || item.event_type === 'quality_hold' ? 'attention' : 'stable')}">${opsDisplayStatus(item.event_type || 'done')}</span></div>`)}</div>
            </section>
        `;
    }
    const visibleProductionOrders = getVisibleProductionOrders();
    pruneOpsBulkSelection('production', visibleProductionOrders);
    renderOpsBulkToolbar('production');
    tbody.innerHTML = visibleProductionOrders.length ? visibleProductionOrders.map(item => `
        <tr data-production-id="${item.id}" class="${typeof isWorkflowFocused === 'function' && isWorkflowFocused('production', item.id) ? 'workflow-row-highlight' : ''}">
            <td>${renderOpsBulkCheckbox('production', item.id)}</td>
            <td><div class="finance-row-title">${item.order_name}</div><div class="finance-row-meta">${productionPriorityLabel(item.priority)} · ${item.route_name || 'Маршрут не указан'}</div><div class="finance-row-meta">${item.bom_items_count || 0} BOM · ${item.comment || 'Без комментария'}</div></td>
            <td>${projectAndClientMeta(item)}</td>
            <td><div class="finance-row-title">${item.responsible || '—'}</div><div class="finance-row-meta">${item.planned_start || 'Старт не задан'} · ${Number(item.labor_hours_total || item.labor_hours_fact || 0).toLocaleString('ru-RU')} ч</div></td>
            <td><div class="finance-row-title">${item.planned_finish || '—'}</div><div class="finance-row-meta">${item.actual_finish || 'Факт не закрыт'} · ${formatMoney(item.actual_cost_total || item.actual_cost || 0)}</div><div class="finance-row-meta">План ${formatMoney(item.planned_cost_total || item.planned_cost || 0)} · мат. ${formatMoney(item.planned_material_cost || 0)}</div></td>
            <td><span class="status-badge ${purchaseStatusClass(item.stage === 'done' ? 'received' : item.stage === 'in_work' ? 'in_transit' : 'planned')}">${productionStageLabel(item.stage)}</span></td>
            <td>${item.progress || 0}%<div class="finance-row-meta">${Number(item.produced_qty_total || item.produced_qty || 0).toLocaleString('ru-RU')} / ${Number(item.planned_qty_total || item.planned_qty || 0).toLocaleString('ru-RU')} шт · брак ${Number(item.scrap_qty_total || item.scrap_qty || 0).toLocaleString('ru-RU')}</div></td>
            <td><div class="view-actions">${typeof renderEntityFavoriteButton === 'function' ? renderEntityFavoriteButton('production_order', item.id, item.order_name || `Производственный заказ #${item.id}`, `${productionStageLabel(item.stage)} · ${item.responsible || ''}`, 'production', 'renderProduction') : ''}${typeof renderEntityWatchButton === 'function' ? renderEntityWatchButton('production_order', item.id, item.order_name || `Производственный заказ #${item.id}`, `${productionStageLabel(item.stage)} · ${item.responsible || ''}`, 'production', 'renderProduction', 'stage_changed') : ''}<button class="btn-secondary" onclick="openEntityCard('production_order', ${item.id})">Карточка</button><button class="btn-secondary" onclick="selectProductionOrder(${item.id}); renderProduction();">Операции</button><button class="btn-secondary" onclick="editProductionOrder(${item.id})">Редактировать</button><button class="btn-secondary" onclick="duplicateProductionOrder(${item.id})">Создать похожий</button><button class="btn-danger" onclick="deleteProductionOrder(${item.id})">Удалить</button></div></td>
        </tr>
    `).join('') : '<tr><td colspan="8" class="nsi-empty-row">Производственных заказов по текущему фильтру нет.</td></tr>';

    if (caption) {
        caption.textContent = selectedOrder ? `Заказ: ${selectedOrder.order_name}` : 'Заказ не выбран';
    }
    if (bomCaption) bomCaption.textContent = selectedOrder ? `Заказ: ${selectedOrder.order_name}` : 'Заказ не выбран';
    if (routeCaption) routeCaption.textContent = selectedOrder ? `Заказ: ${selectedOrder.order_name}` : 'Заказ не выбран';
    const operations = selectedOrder ? productionOperationsDB.filter(item => Number(item.order_id) === Number(selectedOrder.id)) : [];
    const bomItems = selectedOrder ? productionBomDB.filter(item => Number(item.order_id) === Number(selectedOrder.id)) : [];
    const routeItems = selectedOrder ? productionRoutesDB.filter(item => Number(item.order_id) === Number(selectedOrder.id)) : [];
    operationsTbody.innerHTML = selectedOrder
        ? (operations.length ? operations.map(item => `
            <tr>
                <td><div class="finance-row-title">#${item.sequence_no || 1} · ${item.operation_name || 'Операция'}</div><div class="finance-row-meta">${item.note || 'Без комментария'}</div></td>
                <td>${item.work_center || 'Не указан'}<div class="finance-row-meta">${item.started_at || '—'} → ${item.finished_at || '—'}</div></td>
                <td>${Number(item.planned_hours || 0).toLocaleString('ru-RU')} / ${Number(item.actual_hours || 0).toLocaleString('ru-RU')} ч</td>
                <td>${Number(item.completed_qty || 0).toLocaleString('ru-RU')} / ${Number(item.planned_qty || 0).toLocaleString('ru-RU')}<div class="finance-row-meta">Брак ${Number(item.scrap_qty || 0).toLocaleString('ru-RU')}</div></td>
                <td><span class="status-badge ${item.status === 'done' ? 'status-completed' : item.status === 'in_progress' || item.status === 'otk' ? 'status-active' : 'status-archived'}">${opsDisplayStatus(item.status || 'planned')}</span></td>
                <td>${formatMoney(item.actual_cost || 0)}<div class="finance-row-meta">Труд ${formatMoney((Number(item.actual_hours || 0) * Number(item.labor_rate || 0)) || 0)}</div></td>
                <td><div class="view-actions"><button class="btn-secondary" onclick="editProductionOperation(${item.id})">Редактировать</button><button class="btn-danger" onclick="deleteProductionOperation(${item.id})">Удалить</button></div></td>
            </tr>
        `).join('') : '<tr><td colspan="7" class="nsi-empty-row">Для выбранного заказа операции пока не заведены.</td></tr>')
        : '<tr><td colspan="7" class="nsi-empty-row">Сначала создай или выбери производственный заказ.</td></tr>';
    bomTbody.innerHTML = selectedOrder
        ? (bomItems.length ? bomItems.map(item => `
            <tr>
                <td><div class="finance-row-title">${item.item_name || item.nomenclature_name || item.article}</div><div class="finance-row-meta">${item.article || 'без артикула'} · ${item.unit || 'шт'}</div></td>
                <td>${Number(item.qty_per_unit || 0).toLocaleString('ru-RU')} / ${Number(item.planned_qty || 0).toLocaleString('ru-RU')} / ${Number(item.actual_qty || 0).toLocaleString('ru-RU')}</td>
                <td>${item.warehouse || '—'}<div class="finance-row-meta">${item.bin_code || 'ячейка не указана'}</div></td>
                <td>${formatMoney(item.actual_cost || item.planned_cost || 0)}<div class="finance-row-meta">${formatMoney(item.unit_cost || 0)} / ${item.unit || 'шт'}</div></td>
                <td><div class="view-actions"><button class="btn-secondary" onclick="editProductionBomItem(${item.id})">Редактировать</button><button class="btn-danger" onclick="deleteProductionBomItem(${item.id})">Удалить</button></div></td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="nsi-empty-row">Для выбранного заказа спецификация ещё не заполнена.</td></tr>')
        : '<tr><td colspan="5" class="nsi-empty-row">Сначала выбери заказ.</td></tr>';
    routesTbody.innerHTML = selectedOrder
        ? (routeItems.length ? routeItems.map(item => `
            <tr>
                <td><div class="finance-row-title">#${item.sequence_no || 1} · ${item.operation_name || 'Этап'}</div><div class="finance-row-meta">${item.note || 'Без комментария'}</div></td>
                <td>${item.work_center || 'Не указан'}</td>
                <td>${Number(item.planned_hours || 0).toLocaleString('ru-RU')} ч<div class="finance-row-meta">Выпуск ${Number(item.planned_qty || 0).toLocaleString('ru-RU')}</div></td>
                <td>${formatMoney(item.planned_cost || 0)}</td>
                <td><div class="view-actions"><button class="btn-secondary" onclick="editProductionRouteItem(${item.id})">Редактировать</button><button class="btn-danger" onclick="deleteProductionRouteItem(${item.id})">Удалить</button></div></td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="nsi-empty-row">Для выбранного заказа шаблон маршрута ещё не создан.</td></tr>')
        : '<tr><td colspan="5" class="nsi-empty-row">Сначала выбери заказ.</td></tr>';
}

async function renderProjectOpsSummary() {
    if (!currentProjectId) return;
    const container = document.getElementById('projectOpsSummary');
    if (!container) return;
    const data = await apiCall(`/projects/${currentProjectId}/ops`);
    if (!data || data.error) {
        container.innerHTML = '<div class="empty-state">Операционный контур для проекта пока недоступен.</div>';
        return;
    }
    const purchaseHtml = (data.purchases || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${item.item_name}</div><div class="client360-item-meta">${opsDisplayStatus(item.status, '—')} · ${item.expected_date || 'без срока'}</div></div><div class="client360-item-side">${formatMoney(item.total_amount || 0)}</div></div>`).join('') || '<div class="empty-state">Нет закупок</div>';
    const salesHtml = (data.sales || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${salesDocLabel(item.doc_type)} ${item.doc_number || ''}</div><div class="client360-item-meta">${opsDisplayStatus(item.status, '—')} · ${salesSentLabel(item.sent_status)}</div><div class="client360-item-meta">${item.recipient_email || 'Получатель не задан'}</div></div><div class="client360-item-side">${formatMoney(item.amount || 0, item.currency)}</div></div>`).join('') || '<div class="empty-state">Нет документов</div>';
    const productionHtml = (data.production || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${item.order_name}</div><div class="client360-item-meta">${productionStageLabel(item.stage)} · ${item.responsible || 'без ответственного'}</div></div><div class="client360-item-side">${item.progress || 0}%</div></div>`).join('') || '<div class="empty-state">Нет производственных заказов</div>';
    const reserveHtml = (data.reservations || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${item.nomenclature_name}</div><div class="client360-item-meta">${item.qty} шт · ${opsDisplayStatus(item.status, '—')}</div></div></div>`).join('') || '<div class="empty-state">Нет резервов</div>';
    const expenseHtml = (data.expenses || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${item.title}</div><div class="client360-item-meta">${opsDisplayStatus(item.status, '—')} · ${item.approver_name || item.approver_role || 'без согласующего'}</div></div><div class="client360-item-side">${formatMoney(item.amount || 0, item.currency)}</div></div>`).join('') || '<div class="empty-state">Нет запросов на оплату</div>';
    const requestHtml = (data.requests || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${item.title}</div><div class="client360-item-meta">${item.target_role || 'без отдела'} · ${item.assignee_name || 'исполнитель не задан'}</div></div><span class="status-badge ${typeof enterpriseStatusClass === 'function' ? enterpriseStatusClass(item.status) : 'status-active'}">${typeof enterpriseStatusLabel === 'function' ? enterpriseStatusLabel(item.status) : (item.status || 'new')}</span></div>`).join('') || '<div class="empty-state">Нет внутренних заявок</div>';
    const resourceHtml = (data.resources || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${item.resource_name}</div><div class="client360-item-meta">${item.department || 'без отдела'} · ${item.date_from || '—'} → ${item.date_to || '—'}</div></div><div class="client360-item-side">${item.load_percent || 0}%</div></div>`).join('') || '<div class="empty-state">Нет загрузок ресурсов</div>';
    const serviceHtml = (data.service || []).slice(0, 3).map(item => `<div class="client360-item"><div><div class="client360-item-title">${item.title}</div><div class="client360-item-meta">${opsDisplayStatus(item.status, '—')} · ${item.responsible || 'без ответственного'}</div></div><div class="client360-item-side">${item.sla_deadline || '—'}</div></div>`).join('') || '<div class="empty-state">Нет сервисных кейсов</div>';
    const eplHtml = (data.epl_waybills || []).slice(0, 3).map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.number || 'ЭПЛ'}</div>
                <div class="client360-item-meta">${item.route_text || 'Маршрут не указан'} · ${opsDisplayStatus(item.status || 'draft')} · 1С ${opsDisplayStatus(item.integration_status || 'draft')}</div>
                <div class="client360-item-meta">${item.driver_name || 'Водитель не выбран'} · ${item.vehicle_label || 'ТС не выбрано'}</div>
            </div>
            <div class="view-actions">
                <button class="btn-secondary" onclick="typeof openEplModuleForWaybill === 'function' && openEplModuleForWaybill(${item.id})">Карточка</button>
            </div>
        </div>
    `).join('') || '<div class="empty-state">По этой сделке ЭПЛ пока не заведены</div>';
    container.innerHTML = `
        <div class="ops-summary-grid">
            <div class="ops-summary-stat"><div class="ops-summary-label">Открытые поступления</div><div class="ops-summary-value">${formatMoney(data.finance?.incoming_open || 0)}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Открытые выплаты</div><div class="ops-summary-value">${formatMoney(data.finance?.outgoing_open || 0)}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Закупок</div><div class="ops-summary-value">${(data.purchases || []).length}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Производство</div><div class="ops-summary-value">${(data.production || []).length}</div></div>
        </div>
        <div class="ops-summary-grid">
            <div class="ops-summary-stat"><div class="ops-summary-label">Контракт</div><div class="ops-summary-value">${formatMoney(data.budget?.contract_total || 0)}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Факт расходов</div><div class="ops-summary-value">${formatMoney(data.budget?.budget_fact || 0)}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Открытые затраты</div><div class="ops-summary-value">${formatMoney(data.budget?.open_expenses || 0)}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Маржа</div><div class="ops-summary-value">${formatMoney(data.budget?.margin_estimate || 0)}</div></div>
        </div>
        <div class="ops-summary-grid">
            <div class="ops-summary-stat"><div class="ops-summary-label">ЭПЛ всего</div><div class="ops-summary-value">${data.epl_metrics?.total || 0}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">ЭПЛ на линии</div><div class="ops-summary-value">${data.epl_metrics?.on_route || 0}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Готово к 1С</div><div class="ops-summary-value">${data.epl_metrics?.ready || 0}</div></div>
            <div class="ops-summary-stat"><div class="ops-summary-label">Проблемные ЭПЛ</div><div class="ops-summary-value">${data.epl_metrics?.blocked || 0}</div></div>
        </div>
        <div class="surface-card surface-card--soft surface-card--padded">
            <h4 class="section-title">Финансы</h4>
            <div class="project-ops-summary-list">
                <div class="client360-item"><div><div class="client360-item-title">Открытые поступления</div></div><div class="client360-item-side">${formatMoney(data.finance?.incoming_open || 0)}</div></div>
                <div class="client360-item"><div><div class="client360-item-title">Открытые выплаты</div></div><div class="client360-item-side">${formatMoney(data.finance?.outgoing_open || 0)}</div></div>
                <div class="client360-item"><div><div class="client360-item-title">Оплачено всего</div></div><div class="client360-item-side">${formatMoney(data.finance?.paid_total || 0)}</div></div>
            </div>
        </div>
        <div class="project-ops-grid">
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Закупки</h4><div class="project-ops-summary-list">${purchaseHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Реализация</h4><div class="project-ops-summary-list">${salesHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Производство</h4><div class="project-ops-summary-list">${productionHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Резервы</h4><div class="project-ops-summary-list">${reserveHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Затраты</h4><div class="project-ops-summary-list">${expenseHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Внутренние заявки</h4><div class="project-ops-summary-list">${requestHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Ресурсы</h4><div class="project-ops-summary-list">${resourceHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">Сервис</h4><div class="project-ops-summary-list">${serviceHtml}</div></div>
            <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title">1С ЭПЛ</h4><div class="project-ops-summary-list">${eplHtml}</div></div>
        </div>
    `;
}

window.resetProductionBomForm = resetProductionBomForm;
window.resetProductionRouteForm = resetProductionRouteForm;
window.duplicatePurchase = duplicatePurchase;
window.duplicateSalesDocument = duplicateSalesDocument;
window.duplicateProductionOrder = duplicateProductionOrder;
window.saveProductionBomItem = saveProductionBomItem;
window.deleteProductionBomItem = deleteProductionBomItem;
window.editProductionBomItem = editProductionBomItem;
window.saveProductionRouteItem = saveProductionRouteItem;
window.deleteProductionRouteItem = deleteProductionRouteItem;
window.editProductionRouteItem = editProductionRouteItem;
window.applyProductionRouteTemplates = applyProductionRouteTemplates;

const opsExtendedDB = {
    salesSummary: null,
    quotes: [],
    salesReturns: [],
    salesPlans: [],
    priceLists: [],
    clientTerms: [],
    customerOrders: [],
    salesShipments: [],
    salesPaymentSchedules: [],
    salesDealMargins: [],
    supplySummary: null,
    procurementRequests: [],
    procurementTenders: [],
    procurementBids: [],
    purchaseReceipts: [],
    purchaseDocuments: [],
    suppliers: [],
    purchasePlans: [],
    deliverySchedules: [],
    supplierReturns: [],
    supplierDiscrepancies: [],
    stockSummary: null,
    inventoryActs: [],
    regradingDocs: [],
    qualityReports: [],
    stockPolicy: null,
    wmsSummary: null,
    terminalSummary: null,
    wmsCells: [],
    wmsPutawayTasks: [],
    wmsPickWaves: [],
    wmsPickTasks: [],
    wmsCycleCounts: [],
    wmsCycleCountLines: [],
    wmsLotPositions: [],
};

const baseLoadOpsData = loadOpsData;
loadOpsData = async function loadOpsDataExtended() {
    await baseLoadOpsData();
    const [
        salesExtendedSummary,
        quotes,
        salesReturns,
        salesPlans,
        priceLists,
        clientTerms,
        customerOrders,
        salesShipments,
        salesPaymentSchedules,
        salesDealMargins,
        supplyExtendedSummary,
        procurementRequests,
        procurementTenders,
        procurementBids,
        purchaseReceipts,
        purchaseDocuments,
        suppliers,
        purchasePlans,
        deliverySchedules,
        supplierReturns,
        supplierDiscrepancies,
        stockExtendedSummary,
        inventoryActs,
        regradingDocs,
        qualityReports,
        stockPolicy,
        wmsSummary,
        terminalSummary,
        wmsCells,
        wmsPutawayTasks,
        wmsPickWaves,
        wmsPickTasks,
        wmsCycleCounts,
        wmsCycleCountLines,
    ] = await Promise.all([
        apiCall('/sales/extended_summary'),
        apiCall('/sales/quotes'),
        apiCall('/sales/returns'),
        apiCall('/sales/plans'),
        apiCall('/sales/price_lists'),
        apiCall('/sales/client_terms'),
        apiCall('/sales/customer_orders'),
        apiCall('/sales/shipments'),
        apiCall('/sales/payment_schedules'),
        apiCall('/sales/deal_margins'),
        apiCall('/supply/extended_summary'),
        apiCall('/procurement/requests'),
        apiCall('/procurement/tenders'),
        apiCall('/procurement/tender_bids'),
        apiCall('/procurement/receipts'),
        apiCall('/procurement/documents'),
        apiCall('/suppliers'),
        apiCall('/purchase/plans'),
        apiCall('/purchase/delivery_schedules'),
        apiCall('/purchase/returns'),
        apiCall('/purchase/discrepancy_acts'),
        apiCall('/stock/extended_summary'),
        apiCall('/stock/inventory_acts'),
        apiCall('/stock/regrading'),
        apiCall('/stock/quality_reports'),
        apiCall('/stock/policy'),
        apiCall('/wms/summary'),
        apiCall('/terminal/summary'),
        apiCall('/wms/cells'),
        apiCall('/wms/putaway_tasks'),
        apiCall('/wms/pick_waves'),
        apiCall('/wms/pick_tasks'),
        apiCall('/wms/cycle_counts'),
        apiCall('/wms/cycle_count_lines'),
    ]);
    opsExtendedDB.salesSummary = salesExtendedSummary && !salesExtendedSummary.error ? salesExtendedSummary : null;
    opsExtendedDB.quotes = Array.isArray(quotes) ? quotes : [];
    opsExtendedDB.salesReturns = Array.isArray(salesReturns) ? salesReturns : [];
    opsExtendedDB.salesPlans = Array.isArray(salesPlans) ? salesPlans : [];
    opsExtendedDB.priceLists = Array.isArray(priceLists) ? priceLists : [];
    opsExtendedDB.clientTerms = Array.isArray(clientTerms) ? clientTerms : [];
    opsExtendedDB.customerOrders = Array.isArray(customerOrders) ? customerOrders : [];
    opsExtendedDB.salesShipments = Array.isArray(salesShipments) ? salesShipments : [];
    opsExtendedDB.salesPaymentSchedules = Array.isArray(salesPaymentSchedules) ? salesPaymentSchedules : [];
    opsExtendedDB.salesDealMargins = Array.isArray(salesDealMargins) ? salesDealMargins : [];
    opsExtendedDB.supplySummary = supplyExtendedSummary && !supplyExtendedSummary.error ? supplyExtendedSummary : null;
    opsExtendedDB.procurementRequests = Array.isArray(procurementRequests) ? procurementRequests : [];
    opsExtendedDB.procurementTenders = Array.isArray(procurementTenders) ? procurementTenders : [];
    opsExtendedDB.procurementBids = Array.isArray(procurementBids) ? procurementBids : [];
    opsExtendedDB.purchaseReceipts = Array.isArray(purchaseReceipts) ? purchaseReceipts : [];
    opsExtendedDB.purchaseDocuments = Array.isArray(purchaseDocuments) ? purchaseDocuments : [];
    opsExtendedDB.suppliers = Array.isArray(suppliers) ? suppliers : [];
    opsExtendedDB.purchasePlans = Array.isArray(purchasePlans) ? purchasePlans : [];
    opsExtendedDB.deliverySchedules = Array.isArray(deliverySchedules) ? deliverySchedules : [];
    opsExtendedDB.supplierReturns = Array.isArray(supplierReturns) ? supplierReturns : [];
    opsExtendedDB.supplierDiscrepancies = Array.isArray(supplierDiscrepancies) ? supplierDiscrepancies : [];
    opsExtendedDB.stockSummary = stockExtendedSummary && !stockExtendedSummary.error ? stockExtendedSummary : null;
    opsExtendedDB.inventoryActs = Array.isArray(inventoryActs) ? inventoryActs : [];
    opsExtendedDB.regradingDocs = Array.isArray(regradingDocs) ? regradingDocs : [];
    opsExtendedDB.qualityReports = Array.isArray(qualityReports) ? qualityReports : [];
    opsExtendedDB.stockPolicy = stockPolicy && !stockPolicy.error ? stockPolicy : null;
    opsExtendedDB.wmsSummary = wmsSummary && !wmsSummary.error ? wmsSummary : null;
    opsExtendedDB.terminalSummary = terminalSummary && !terminalSummary.error ? terminalSummary : null;
    opsExtendedDB.wmsCells = Array.isArray(wmsCells) ? wmsCells : [];
    opsExtendedDB.wmsPutawayTasks = Array.isArray(wmsPutawayTasks) ? wmsPutawayTasks : [];
    opsExtendedDB.wmsPickWaves = Array.isArray(wmsPickWaves) ? wmsPickWaves : [];
    opsExtendedDB.wmsPickTasks = Array.isArray(wmsPickTasks) ? wmsPickTasks : [];
    opsExtendedDB.wmsCycleCounts = Array.isArray(wmsCycleCounts) ? wmsCycleCounts : [];
    opsExtendedDB.wmsCycleCountLines = Array.isArray(wmsCycleCountLines) ? wmsCycleCountLines : [];
    opsExtendedDB.wmsLotPositions = Array.isArray(wmsSummary?.lot_positions) ? wmsSummary.lot_positions : [];
};

function renderOpsExtendedMetrics(metrics = {}) {
    return `
        <div class="metrics-grid" style="margin-bottom:16px;">
            ${Object.entries(metrics).map(([label, value]) => `
                <div class="metric-card">
                    <div class="metric-title">${label}</div>
                    <div class="metric-value">${typeof value === 'number' ? Number.isInteger(value) ? value : formatMoney(value) : value}</div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderSimpleList(items, emptyText, mapper) {
    return items.length ? items.map(mapper).join('') : `<div class="empty-state">${emptyText}</div>`;
}

function explainExtendedOpsError(errorCode) {
    const raw = String(errorCode || '').trim();
    if (!raw) return 'Не удалось выполнить операцию.';
    const map = {
        forbidden: 'Недостаточно прав для этой операции.',
        forbidden_scope: 'Операция недоступна в текущем контуре юрлица или подразделения.',
        nomenclature_not_found: 'Номенклатура не найдена. Сначала заведи позицию в НСИ.',
        insufficient_stock: 'Недостаточно остатка на складе для проведения операции.',
        insufficient_wms_stock: 'В выбранной WMS-ячейке недостаточно остатка, партии или серии.',
        payment_not_found: 'Связанная оплата не найдена. Проверь финансовую привязку.',
        not_found: 'Запись не найдена. Возможно, её уже удалили.',
        validation_error: 'Проверь заполнение полей и попробуй ещё раз.',
    };
    if (map[raw]) return map[raw];
    if (raw.startsWith('period_closed:')) {
        const periodKey = raw.split(':')[1] || '';
        return periodKey ? `Период ${periodKey} уже закрыт, изменения запрещены.` : 'Период уже закрыт, изменения запрещены.';
    }
    if (raw.startsWith('integrity_error:')) {
        return 'Операция конфликтует с уже существующими данными. Проверь уникальные поля и связи.';
    }
    if (raw.startsWith('locked:')) {
        return 'Запись сейчас редактирует другой пользователь. Повтори попытку чуть позже.';
    }
    return raw;
}

async function saveExtendedOpsRecord(path, payload, successTitle) {
    const res = await apiCall(path, 'POST', payload);
    if (!res || res.error) {
        await customAlert(explainExtendedOpsError(res?.error));
        return false;
    }
    showToast('Система', successTitle || 'Сохранено');
    return true;
}

async function deleteExtendedOpsRecord(path, successTitle) {
    const res = await apiCall(path, 'DELETE');
    if (!res || res.error) {
        await customAlert(explainExtendedOpsError(res?.error));
        return false;
    }
    showToast('Система', successTitle || 'Удалено');
    return true;
}

function salesExtendedMarkup() {
    const metrics = opsExtendedDB.salesSummary?.metrics || {};
    const pipeline = Array.isArray(opsExtendedDB.salesSummary?.pipeline) ? opsExtendedDB.salesSummary.pipeline : [];
    const clientHealth = Array.isArray(opsExtendedDB.salesSummary?.client_health) ? opsExtendedDB.salesSummary.client_health : [];
    const overdue = Array.isArray(opsExtendedDB.salesSummary?.overdue) ? opsExtendedDB.salesSummary.overdue : [];
    const shipmentRisk = Array.isArray(opsExtendedDB.salesSummary?.shipment_risk) ? opsExtendedDB.salesSummary.shipment_risk : [];
    const clientOptions = ((typeof clientsDB !== 'undefined' && Array.isArray(clientsDB)) ? clientsDB : []).map(client => `<option value="${client.id}">${client.name}</option>`).join('');
    const projectOptions = ((typeof projectsDB !== 'undefined' && Array.isArray(projectsDB)) ? projectsDB : []).map(project => `<option value="${project.id}">${project.name}</option>`).join('');
    const priceListOptions = opsExtendedDB.priceLists.map(item => `<option value="${item.id}">${item.name}${item.version_no ? ` v${item.version_no}` : ''}</option>`).join('');
    const salesDocumentOptions = salesDocsDB.map(item => `<option value="${item.id}">${salesDocLabel(item.doc_type)} ${item.doc_number || item.id}</option>`).join('');
    const quoteOptions = opsExtendedDB.quotes.map(item => `<option value="${item.id}">${item.quote_number || `КП #${item.id}`} · ${item.title || ''}</option>`).join('');
    const customerOrderOptions = opsExtendedDB.customerOrders.map(item => `<option value="${item.id}">${item.order_number || `Заказ #${item.id}`} · ${item.item_name || item.article || ''}</option>`).join('');
    return `
        <div class="section-header"><div><h3 class="section-title">Расширенные продажи</h3><p class="section-subtitle">Коммерческие предложения, ценовая политика, план-факт, состояние клиентов и сроки сервиса по деньгам и отгрузке.</p></div></div>
        ${renderOpsExtendedMetrics({
            'Активные КП': metrics.quotes_active || 0,
            'Возвраты': metrics.returns_total || 0,
            'План продаж': metrics.sales_plan_amount || 0,
            'Факт продаж': metrics.sales_fact_amount || 0,
            'Просрочено': metrics.overdue_receivables || 0,
            'Риск клиентов': metrics.customer_risk_clients || 0,
            'Заказы клиентов': metrics.customer_orders_open || 0,
            'Отгрузки': metrics.shipments_pending || 0,
            'График оплат': metrics.payment_schedule_open || 0,
            'Маржа сделок': `${formatMoney(metrics.deal_margin_amount || 0)} / ${metrics.deal_margin_percent || 0}%`,
        })}
        <div class="finance-layout">
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Заказ клиента → резерв → отгрузка → оплата</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="salesOrderQuoteIdX" class="auth-input" style="margin:0;"><option value="0">КП-основание</option>${quoteOptions}</select>
                    <select id="salesOrderClientIdX" class="auth-input" style="margin:0;"><option value="0">Клиент заказа</option>${clientOptions}</select>
                    <select id="salesOrderProjectIdX" class="auth-input" style="margin:0;"><option value="0">Проект заказа</option>${projectOptions}</select>
                    <input id="salesOrderArticleX" class="auth-input" style="margin:0;" placeholder="Артикул">
                    <input id="salesOrderItemNameX" class="auth-input" style="margin:0;" placeholder="Позиция">
                    <input id="salesOrderQtyX" class="auth-input" style="margin:0;" placeholder="Количество">
                    <input id="salesOrderUnitPriceX" class="auth-input" style="margin:0;" placeholder="Цена">
                    <input id="salesOrderAmountX" class="auth-input" style="margin:0;" placeholder="Сумма">
                    <input id="salesOrderShipDateX" class="auth-input" style="margin:0;" placeholder="Дата отгрузки">
                    <button class="btn-primary" onclick="saveSalesCustomerOrderX()">Создать заказ</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="salesOpsOrderIdX" class="auth-input" style="margin:0;"><option value="0">Заказ для операций</option>${customerOrderOptions}</select>
                    <input id="salesOpsWarehouseX" class="auth-input" style="margin:0;" placeholder="Склад">
                    <input id="salesOpsBinX" class="auth-input" style="margin:0;" placeholder="Ячейка">
                    <input id="salesOpsBatchX" class="auth-input" style="margin:0;" placeholder="Партия">
                    <button class="btn-secondary" onclick="reserveSalesCustomerOrderX()">Резерв</button>
                    <button class="btn-secondary" onclick="createSalesDocumentFromOrderX()">Реализация</button>
                    <input id="salesScheduleDueDateX" class="auth-input" style="margin:0;" placeholder="Срок оплаты">
                    <input id="salesScheduleAmountX" class="auth-input" style="margin:0;" placeholder="Сумма платежа">
                    <button class="btn-secondary" onclick="saveSalesPaymentScheduleX()">График оплаты</button>
                    <button class="btn-secondary" onclick="recalculateSalesDealMarginX()">Маржа</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="salesShipmentOrderIdX" class="auth-input" style="margin:0;"><option value="0">Заказ для отгрузки</option>${customerOrderOptions}</select>
                    <select id="salesShipmentDocIdX" class="auth-input" style="margin:0;"><option value="0">Документ реализации</option>${salesDocumentOptions}</select>
                    <input id="salesShipmentQtyX" class="auth-input" style="margin:0;" placeholder="Кол-во отгрузки">
                    <input id="salesShipmentWarehouseX" class="auth-input" style="margin:0;" placeholder="Склад отгрузки">
                    <input id="salesShipmentBinX" class="auth-input" style="margin:0;" placeholder="Ячейка">
                    <input id="salesShipmentBatchX" class="auth-input" style="margin:0;" placeholder="Партия">
                    <input id="salesShipmentCarrierX" class="auth-input" style="margin:0;" placeholder="Перевозчик">
                    <button class="btn-secondary" onclick="saveSalesShipmentX()">Задание отгрузки</button>
                </div>
                <div class="client360-list">${renderSimpleList(opsExtendedDB.customerOrders.slice(0, 5), 'Заказов клиентов пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.order_number || `Заказ #${item.id}`}</div><div class="client360-item-meta">${item.client_name || 'без клиента'} · ${item.article || ''} · ${item.qty || 0} · резерв ${item.reserve_status || 'none'}</div></div><div class="view-actions"><span class="client360-item-side">${formatMoney(item.amount || 0, item.currency || 'RUB')}</span>${typeof renderEntityFavoriteButton === 'function' ? renderEntityFavoriteButton('customer_order', item.id, item.order_number || `Заказ #${item.id}`, `${item.client_name || ''} · ${item.article || ''} · ${formatMoney(item.amount || 0, item.currency || 'RUB')}`, 'sales', 'renderSales') : ''}<button class="btn-secondary" onclick="reserveSalesCustomerOrderX(${item.id})">Резерв</button><button class="btn-secondary" onclick="createSalesDocumentFromOrderX(${item.id})">Документ</button><button class="btn-danger" onclick="deleteSalesCustomerOrderX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.salesShipments.slice(0, 4), 'Отгрузок пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.shipment_number || `Отгрузка #${item.id}`}</div><div class="client360-item-meta">${item.customer_order_number || ''} · ${item.article || ''} · ${item.qty || 0} · ${item.warehouse || ''}/${item.bin_code || ''}</div></div><div class="view-actions"><span class="status-badge ${item.status === 'shipped' ? 'status-completed' : 'status-active'}">${opsDisplayStatus(item.status || 'planned')}</span><button class="btn-secondary" onclick="shipSalesShipmentX(${item.id})">Отгрузить</button><button class="btn-danger" onclick="deleteSalesShipmentX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.salesPaymentSchedules.slice(0, 4), 'Графиков оплат пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.schedule_number || `Платёж #${item.id}`}</div><div class="client360-item-meta">${item.customer_order_number || item.sales_doc_number || ''} · срок ${item.due_date || 'не задан'} · просрочка ${item.overdue_days || 0} дн.</div></div><div class="view-actions"><span class="client360-item-side">${formatMoney(item.amount || 0, item.currency || 'RUB')}</span><button class="btn-secondary" onclick="markSalesPaymentSchedulePaidX(${item.id})">Оплачено</button><button class="btn-danger" onclick="deleteSalesPaymentScheduleX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.salesDealMargins.slice(0, 4), 'Расчётов маржи пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.customer_order_number || item.sales_doc_number || 'Сделка'}</div><div class="client360-item-meta">выручка ${formatMoney(item.revenue_amount || 0)} · себестоимость ${formatMoney((item.purchase_cost_amount || 0) + (item.direct_cost_amount || 0))}</div></div><span class="status-badge ${opsHealthBadgeClass(Number(item.margin_percent || 0) >= 20 ? 'stable' : 'warning')}">${item.margin_percent || 0}%</span></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">КП и pipeline</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="salesQuoteClientIdX" class="auth-input" style="margin:0;"><option value="0">Клиент</option>${clientOptions}</select>
                    <select id="salesQuoteProjectIdX" class="auth-input" style="margin:0;"><option value="0">Проект</option>${projectOptions}</select>
                    <input id="salesQuoteTitleX" class="auth-input" style="margin:0;" placeholder="Коммерческое предложение">
                    <input id="salesQuoteAmountX" class="auth-input" style="margin:0;" placeholder="Сумма КП">
                    <select id="salesQuoteStageX" class="auth-input" style="margin:0;"><option value="draft">Черновик</option><option value="proposal">Отправлено</option><option value="negotiation">Переговоры</option><option value="won">Выиграно</option><option value="lost">Проиграно</option></select>
                    <input id="salesQuoteProbabilityX" class="auth-input" style="margin:0;" placeholder="Вероятность %">
                    <input id="salesQuoteValidUntilX" class="auth-input" style="margin:0;" placeholder="Действует до">
                    <input id="salesQuoteResponsibleX" class="auth-input" style="margin:0;" placeholder="Ответственный">
                    <input id="salesQuoteCommentX" class="auth-input" style="margin:0; grid-column:1 / -1;" placeholder="Комментарий к КП">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-primary" onclick="saveSalesQuoteX()">Сохранить КП</button>
                </div>
                <div class="client360-list">${renderSimpleList(pipeline, 'Стадии пока пусты.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.label}</div><div class="client360-item-meta">${item.count || 0} шт. · ${formatMoney(item.amount || 0)}</div></div><span class="status-badge ${item.stage === 'won' ? 'status-completed' : item.stage === 'lost' ? 'status-overdue' : 'status-active'}">${item.stage}</span></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">План продаж и ценовая политика</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="salesPlanPeriodX" class="auth-input" style="margin:0;" placeholder="Период 2026-04">
                    <input id="salesPlanManagerX" class="auth-input" style="margin:0;" placeholder="Менеджер">
                    <select id="salesPlanClientIdX" class="auth-input" style="margin:0;"><option value="0">Клиент плана</option>${clientOptions}</select>
                    <select id="salesPlanProjectIdX" class="auth-input" style="margin:0;"><option value="0">Проект плана</option>${projectOptions}</select>
                    <input id="salesPlanAmountX" class="auth-input" style="margin:0;" placeholder="План продаж">
                    <input id="salesPlanDocsX" class="auth-input" style="margin:0;" placeholder="План документов">
                    <select id="salesPlanStatusX" class="auth-input" style="margin:0;"><option value="draft">Черновик</option><option value="active">Активно</option><option value="done">Выполнено</option></select>
                    <input id="salesPlanCommentX" class="auth-input" style="margin:0;" placeholder="Комментарий к плану">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-secondary" onclick="saveSalesPlanX()">Сохранить план</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="priceListNameX" class="auth-input" style="margin:0;" placeholder="Прайс-лист">
                    <input id="priceListArticleX" class="auth-input" style="margin:0;" placeholder="Артикул">
                    <input id="priceListItemNameX" class="auth-input" style="margin:0;" placeholder="Номенклатура">
                    <input id="priceListBasePriceX" class="auth-input" style="margin:0;" placeholder="Базовая цена">
                    <input id="priceListMinPriceX" class="auth-input" style="margin:0;" placeholder="Мин. цена">
                    <select id="priceListCurrencyX" class="auth-input" style="margin:0;"><option value="RUB">Рубль</option><option value="USD">Доллар</option><option value="EUR">Евро</option></select>
                    <input id="priceListValidFromX" class="auth-input" style="margin:0;" placeholder="Действует с">
                    <input id="priceListValidToX" class="auth-input" style="margin:0;" placeholder="Действует до">
                    <select id="priceListStatusX" class="auth-input" style="margin:0;"><option value="active">Активно</option><option value="draft">Черновик</option><option value="archived">Архив</option></select>
                    <input id="priceListCommentX" class="auth-input" style="margin:0; grid-column:1 / -1;" placeholder="Комментарий к прайсу">
                </div>
                <div class="finance-actions-row">
                    <button class="btn-secondary" onclick="savePriceListX()">Сохранить прайс</button>
                </div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Условия клиентов и их состояние</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="clientTermsClientIdX" class="auth-input" style="margin:0;"><option value="0">Клиент</option>${clientOptions}</select>
                    <select id="clientTermsPriceListIdX" class="auth-input" style="margin:0;"><option value="0">Прайс-лист</option>${priceListOptions}</select>
                    <input id="clientTermsDiscountX" class="auth-input" style="margin:0;" placeholder="Скидка %">
                    <input id="clientTermsDiscountAmountX" class="auth-input" style="margin:0;" placeholder="Скидка суммой">
                    <input id="clientTermsPaymentDelayX" class="auth-input" style="margin:0;" placeholder="Отсрочка, дней">
                    <input id="clientTermsCreditLimitX" class="auth-input" style="margin:0;" placeholder="Кредитный лимит">
                    <select id="clientTermsShipmentPriorityX" class="auth-input" style="margin:0;"><option value="normal">Обычный</option><option value="priority">Приоритетный</option><option value="critical">Критичный</option></select>
                    <select id="clientTermsStatusX" class="auth-input" style="margin:0;"><option value="active">Активно</option><option value="draft">Черновик</option><option value="archived">Архив</option></select>
                    <input id="clientTermsCommentX" class="auth-input" style="margin:0; grid-column:1 / -1;" placeholder="Комментарий по условиям">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-secondary" onclick="saveClientTermsX()">Сохранить условия</button>
                </div>
                <div class="client360-list">${renderSimpleList(clientHealth.slice(0, 8), 'Условий и оценки состояния пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.client_name || 'Клиент'}</div><div class="client360-item-meta">${Array.isArray(item.reasons) ? item.reasons.join(' · ') : 'цикл стабилен'} · выручка ${formatMoney(item.revenue || 0)}</div></div><span class="status-badge ${opsHealthBadgeClass(item.health_bucket)}">${item.health_score || 0}</span></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">КП, планы, прайсы</h4>
                <div class="client360-list">${renderSimpleList(opsExtendedDB.quotes.slice(0, 6), 'Коммерческих предложений пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.title || item.quote_number}</div><div class="client360-item-meta">${item.client_name || 'без клиента'} · ${salesQuoteStageLabel(item.stage)}${item.probability ? ` · ${item.probability}%` : ''}</div></div><div class="view-actions"><span class="client360-item-side">${formatMoney(item.amount || 0, item.currency || 'RUB')}</span><button class="btn-secondary" onclick="prefillSalesFromQuoteX(${item.id})">В реализацию</button><button class="btn-danger" onclick="deleteSalesQuoteX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.salesPlans.slice(0, 4), 'Планов пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.period_key}</div><div class="client360-item-meta">План ${formatMoney(item.target_amount || 0)} · факт ${formatMoney(item.actual_amount || 0)}</div></div><button class="btn-danger" onclick="deleteSalesPlanX(${item.id})">Удалить</button></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.priceLists.slice(0, 4), 'Прайсов пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.name}</div><div class="client360-item-meta">${item.item_article || 'без артикула'} · ${formatMoney(item.base_price || 0, item.currency || 'RUB')} · v${item.version_no || 1}/${item.version_total || 1}</div></div><button class="btn-danger" onclick="deletePriceListX(${item.id})">Удалить</button></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.clientTerms.slice(0, 4), 'Условий клиентов пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.client_name || 'Клиент'}</div><div class="client360-item-meta">${item.price_list_name || 'без прайса'} · скидка ${item.discount_percent || 0}% · отсрочка ${item.payment_delay_days || 0} дн.</div></div><button class="btn-danger" onclick="deleteClientTermsX(${item.id})">Удалить</button></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Возвраты и сроки сервиса</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="salesReturnClientIdX" class="auth-input" style="margin:0;"><option value="0">Клиент возврата</option>${clientOptions}</select>
                    <select id="salesReturnDocumentIdX" class="auth-input" style="margin:0;"><option value="0">Документ реализации</option>${salesDocumentOptions}</select>
                    <input id="salesReturnArticleX" class="auth-input" style="margin:0;" placeholder="Артикул возврата">
                    <input id="salesReturnItemNameX" class="auth-input" style="margin:0;" placeholder="Позиция возврата">
                    <input id="salesReturnQtyX" class="auth-input" style="margin:0;" placeholder="Кол-во">
                    <input id="salesReturnAmountX" class="auth-input" style="margin:0;" placeholder="Сумма возврата">
                    <select id="salesReturnStatusX" class="auth-input" style="margin:0;"><option value="draft">Черновик</option><option value="approved">Согласовано</option><option value="closed">Закрыто</option></select>
                    <input id="salesReturnReasonX" class="auth-input" style="margin:0;" placeholder="Причина возврата">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-secondary" onclick="saveSalesReturnX()">Сохранить возврат</button>
                </div>
                <div class="client360-list">${renderSimpleList(opsExtendedDB.salesReturns.slice(0, 6), 'Возвратов пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.item_name || item.article || 'Возврат'}</div><div class="client360-item-meta">${item.client_name || 'без клиента'} · ${item.return_number || ''} · ${item.qty || 0} · ${formatMoney(item.amount || 0, item.currency || 'RUB')}</div></div><button class="btn-danger" onclick="deleteSalesReturnX(${item.id})">Удалить</button></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(overdue.slice(0, 4), 'Просрочек по оплате сейчас нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${salesDocLabel(item.doc_type)} ${item.doc_number || ''}</div><div class="client360-item-meta">${item.client_name || 'без клиента'} · ${item.payment_due_date || 'без срока'} · ${item.overdue_days || 0} дн.</div></div><span class="status-badge status-overdue">${formatMoney(item.amount || 0, item.currency || 'RUB')}</span></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(shipmentRisk.slice(0, 4), 'Рисков по отгрузке сейчас нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${salesDocLabel(item.doc_type)} ${item.doc_number || ''}</div><div class="client360-item-meta">${item.client_name || 'без клиента'} · план ${item.planned_ship_date || 'не задан'} · ${item.shipment_late_days || 0} дн.</div></div><span class="status-badge status-active">${opsDisplayStatus(item.shipment_status || 'ready')}</span></div>`)}</div>
            </section>
        </div>
    `;
}

function formatStockCostMethodLabel(value) {
    return {
        fifo: 'ФИФО',
        lifo: 'ЛИФО',
        average: 'средняя себестоимость',
    }[value] || 'ФИФО';
}

function supplyExtendedMarkup() {
    const metrics = opsExtendedDB.supplySummary?.metrics || {};
    const stockMetrics = opsExtendedDB.stockSummary?.metrics || {};
    const wmsMetrics = opsExtendedDB.wmsSummary?.metrics || {};
    const terminalMetrics = opsExtendedDB.terminalSummary?.metrics || {};
    const terminalScans = Array.isArray(opsExtendedDB.terminalSummary?.scans) ? opsExtendedDB.terminalSummary.scans : [];
    const policy = opsExtendedDB.stockPolicy || {};
    const supplierHealth = Array.isArray(opsExtendedDB.supplySummary?.supplier_health) ? opsExtendedDB.supplySummary.supplier_health : [];
    const scheduleAlerts = Array.isArray(opsExtendedDB.supplySummary?.schedule_alerts) ? opsExtendedDB.supplySummary.schedule_alerts : [];
    const planFact = Array.isArray(opsExtendedDB.supplySummary?.plan_fact) ? opsExtendedDB.supplySummary.plan_fact : [];
    const procurementSla = Array.isArray(opsExtendedDB.supplySummary?.procurement_sla) ? opsExtendedDB.supplySummary.procurement_sla : [];
    const projectOptions = ((typeof projectsDB !== 'undefined' && Array.isArray(projectsDB)) ? projectsDB : []).map(project => `<option value="${project.id}">${project.name}</option>`).join('');
    const supplierOptions = opsExtendedDB.suppliers.map(item => `<option value="${item.id}">${item.supplier_name}</option>`).join('');
    const procurementRequestOptions = opsExtendedDB.procurementRequests.map(item => `<option value="${item.id}">#${item.id} · ${item.title || item.item_name || 'заявка'}</option>`).join('');
    const procurementTenderOptions = opsExtendedDB.procurementTenders.map(item => `<option value="${item.id}">#${item.id} · ${item.title || item.tender_number || 'тендер'}</option>`).join('');
    const purchaseOptions = purchasesDB.map(item => `<option value="${item.id}">#${item.id} · ${item.item_name || item.item_article || 'позиция'}</option>`).join('');
    const stockReservationOptions = ((typeof stockReservationsDB !== 'undefined' && Array.isArray(stockReservationsDB)) ? stockReservationsDB : []).filter(item => !['fulfilled', 'cancelled'].includes(item.status || '')).map(item => `<option value="${item.id}">#${item.id} · ${item.nomenclature_article || ''} · ${item.qty || 0}</option>`).join('');
    return `
        <div class="section-header"><div><h3 class="section-title">Расширенное снабжение и склад</h3><p class="section-subtitle">Поставщики, план закупок, графики поставки, состояние поставщиков, возвраты и расхождения в одном управляемом контуре.</p></div></div>
        ${renderOpsExtendedMetrics({
            'Заявки открыты': metrics.procurement_requests_open || 0,
            'Тендеры открыты': metrics.procurement_tenders_open || 0,
            'Риски по срокам': metrics.procurement_sla_risks || 0,
            'План закупок': metrics.purchase_plan_amount || 0,
            'Факт закупок': metrics.purchase_fact_amount || 0,
            'Опоздания': metrics.late_deliveries || 0,
            'Приемки': metrics.purchase_receipts || 0,
            'Документы': metrics.purchase_documents || 0,
            'Инв. акты': stockMetrics.inventory_acts || 0,
            'Брак / удержание': stockMetrics.quality_holds || 0,
            'WMS ячейки': wmsMetrics.cells || stockMetrics.wms_cells || 0,
            'Размещение WMS': wmsMetrics.putaway_open || stockMetrics.wms_putaway_open || 0,
            'Подбор WMS': wmsMetrics.pick_tasks_open || stockMetrics.wms_pick_tasks_open || 0,
            'Партии/серии': `${wmsMetrics.lot_positions || stockMetrics.wms_lot_positions || 0}/${wmsMetrics.serial_positions || stockMetrics.wms_serial_positions || 0}`,
        })}
        <div class="finance-actions-row" style="margin-bottom:16px;">
            <select id="stockCostMethodX" class="auth-input" style="margin:0; max-width:220px;"><option value="fifo">ФИФО</option><option value="lifo">ЛИФО</option><option value="average">Средняя себестоимость</option></select>
            <select id="stockNegativePolicyX" class="auth-input" style="margin:0; max-width:220px;"><option value="0">Без минуса</option><option value="1">Разрешить минус</option></select>
            <button class="btn-secondary" onclick="saveStockPolicyX()">Сохранить политику</button>
            <span class="finance-row-meta">Текущая политика: ${formatStockCostMethodLabel(policy.cost_method || 'fifo')} / минусовые остатки ${policy.allow_negative_stock ? 'разрешены' : 'запрещены'}</span>
        </div>
        <div class="finance-layout">
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Закупочный контур и сроки</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="procReqTitleX" class="auth-input" style="margin:0;" placeholder="Заявка / потребность">
                    <select id="procReqProjectIdX" class="auth-input" style="margin:0;"><option value="0">Проект</option>${projectOptions}</select>
                    <input id="procReqArticleX" class="auth-input" style="margin:0;" placeholder="Артикул">
                    <input id="procReqItemNameX" class="auth-input" style="margin:0;" placeholder="Позиция">
                    <input id="procReqQtyX" class="auth-input" style="margin:0;" placeholder="Количество">
                    <input id="procReqTargetPriceX" class="auth-input" style="margin:0;" placeholder="Целевая цена">
                    <input id="procReqRequiredDateX" class="auth-input" style="margin:0;" placeholder="Нужна дата">
                    <select id="procReqPriorityX" class="auth-input" style="margin:0;"><option value="normal">Обычная</option><option value="high">Высокая</option><option value="urgent">Срочная</option></select>
                    <button class="btn-secondary" onclick="saveProcurementRequestX()">Заявка</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="procTenderRequestIdX" class="auth-input" style="margin:0;"><option value="0">Заявка для тендера</option>${procurementRequestOptions}</select>
                    <input id="procTenderTitleX" class="auth-input" style="margin:0;" placeholder="Тендер / RFQ">
                    <input id="procTenderDueDateX" class="auth-input" style="margin:0;" placeholder="Срок сбора предложений">
                    <button class="btn-secondary" onclick="saveProcurementTenderX()">Тендер</button>
                    <select id="procBidTenderIdX" class="auth-input" style="margin:0;"><option value="0">Тендер для ставки</option>${procurementTenderOptions}</select>
                    <select id="procBidSupplierIdX" class="auth-input" style="margin:0;"><option value="0">Поставщик</option>${supplierOptions}</select>
                    <input id="procBidPriceX" class="auth-input" style="margin:0;" placeholder="Цена ставки">
                    <input id="procBidLeadTimeX" class="auth-input" style="margin:0;" placeholder="Срок поставки, дней">
                    <input id="procBidScoreX" class="auth-input" style="margin:0;" placeholder="Оценка">
                    <button class="btn-secondary" onclick="saveProcurementBidX()">Ставка</button>
                    <button class="btn-primary" onclick="awardProcurementTenderX()">Выбрать лучшего</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="procReceiptPurchaseIdX" class="auth-input" style="margin:0;"><option value="0">Заказ для приемки</option>${purchaseOptions}</select>
                    <input id="procReceiptDateX" class="auth-input" style="margin:0;" placeholder="Дата приемки">
                    <input id="procReceiptAcceptedQtyX" class="auth-input" style="margin:0;" placeholder="Принято">
                    <input id="procReceiptRejectedQtyX" class="auth-input" style="margin:0;" placeholder="Отклонено">
                    <input id="procReceiptWarehouseX" class="auth-input" style="margin:0;" placeholder="Склад">
                    <button class="btn-secondary" onclick="savePurchaseReceiptX()">Приемка</button>
                    <select id="procDocPurchaseIdX" class="auth-input" style="margin:0;"><option value="0">Заказ для документа</option>${purchaseOptions}</select>
                    <select id="procDocTypeX" class="auth-input" style="margin:0;"><option value="invoice">Счет</option><option value="upd">УПД</option><option value="act">Акт</option></select>
                    <input id="procDocNumberX" class="auth-input" style="margin:0;" placeholder="Номер документа">
                    <input id="procDocAmountX" class="auth-input" style="margin:0;" placeholder="Сумма">
                    <button class="btn-secondary" onclick="savePurchaseDocumentX()">Документ</button>
                </div>
                <div class="client360-list">${renderSimpleList(procurementSla.slice(0, 5), 'По срокам закупок пока нет рисков.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.request_number || `Заявка #${item.request_id}`} · ${item.title || ''}</div><div class="client360-item-meta">${opsDisplayStatus(item.status || '')} · возраст ${item.age_days || 0} дн. · ${Array.isArray(item.risks) ? item.risks.join(', ') : ''}</div></div><span class="status-badge ${opsHealthBadgeClass(item.risk_level || 'stable')}">${opsDisplayStatus(item.risk_level || 'stable')}</span></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.procurementRequests.slice(0, 4), 'Заявок на закупку пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.title || item.item_name || 'Заявка'}</div><div class="client360-item-meta">${item.item_article || ''} · ${item.qty || 0} ${item.unit || ''} · ${item.status || ''}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProcurementRequestX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.procurementTenders.slice(0, 4), 'Тендеров пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.tender_number || `Тендер #${item.id}`}</div><div class="client360-item-meta">${item.request_title || ''} · ${item.status || ''}</div></div><div class="view-actions"><button class="btn-secondary" onclick="awardProcurementTenderX(${item.id})">Выбрать</button><button class="btn-danger" onclick="deleteProcurementTenderX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.purchaseReceipts.slice(0, 3), 'Приемок пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.receipt_number || `Приемка #${item.id}`}</div><div class="client360-item-meta">${item.article || ''} · принято ${item.accepted_qty || 0} · ${item.quality_status || ''}</div></div><button class="btn-danger" onclick="deletePurchaseReceiptX(${item.id})">Удалить</button></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.purchaseDocuments.slice(0, 3), 'Счетов/УПД/актов поставщика пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.doc_type || 'doc'} ${item.doc_number || ''}</div><div class="client360-item-meta">${item.supplier_name || 'без поставщика'} · ${formatMoney(item.amount || 0, item.currency || 'RUB')} · ${item.status || ''}</div></div><button class="btn-danger" onclick="deletePurchaseDocumentX(${item.id})">Удалить</button></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Поставщики и их состояние</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="supplierNameX" class="auth-input" style="margin:0;" placeholder="Поставщик">
                    <input id="supplierInnX" class="auth-input" style="margin:0;" placeholder="ИНН">
                    <input id="supplierCategoryX" class="auth-input" style="margin:0;" placeholder="Категория">
                    <input id="supplierLeadTimeX" class="auth-input" style="margin:0;" placeholder="Срок, дней">
                    <input id="supplierRatingX" class="auth-input" style="margin:0;" placeholder="Рейтинг 0-5">
                    <input id="supplierReliabilityX" class="auth-input" style="margin:0;" placeholder="Надёжность %">
                    <input id="supplierPaymentTermsX" class="auth-input" style="margin:0;" placeholder="Условия оплаты">
                    <input id="supplierCommentX" class="auth-input" style="margin:0;" placeholder="Комментарий по поставщику">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-primary" onclick="saveSupplierX()">Сохранить поставщика</button>
                </div>
                <div class="client360-list">${renderSimpleList(supplierHealth.length ? supplierHealth : opsExtendedDB.suppliers.slice(0, 8), 'Поставщиков пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.supplier_name}</div><div class="client360-item-meta">${item.inn || ''} · срок ${item.lead_time_days || 0} дн. · рейтинг ${item.rating || 0} / надёжность ${item.reliability_percent || 0}%</div></div><div class="view-actions"><span class="status-badge ${opsHealthBadgeClass(item.health_bucket || (Number(item.reliability_percent || 0) >= 85 ? 'stable' : 'attention'))}">${item.health_score || item.reliability_percent || 0}</span><button class="btn-danger" onclick="deleteSupplierX(${item.id || item.supplier_id})">Удалить</button></div></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">План закупки и графики</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="purchasePlanPeriodX" class="auth-input" style="margin:0;" placeholder="Период 2026-04">
                    <select id="purchasePlanSupplierIdX" class="auth-input" style="margin:0;"><option value="0">Поставщик плана</option>${supplierOptions}</select>
                    <select id="purchasePlanProjectIdX" class="auth-input" style="margin:0;"><option value="0">Проект плана</option>${projectOptions}</select>
                    <input id="purchasePlanArticleX" class="auth-input" style="margin:0;" placeholder="Артикул">
                    <input id="purchasePlanItemNameX" class="auth-input" style="margin:0;" placeholder="Позиция">
                    <input id="purchasePlanQtyX" class="auth-input" style="margin:0;" placeholder="Плановое количество">
                    <input id="purchasePlanUnitX" class="auth-input" style="margin:0;" value="шт" placeholder="Ед. изм.">
                    <input id="purchasePlanTargetUnitPriceX" class="auth-input" style="margin:0;" placeholder="План цена">
                    <input id="purchasePlanAmountX" class="auth-input" style="margin:0;" placeholder="План закупки">
                    <select id="purchasePlanStatusX" class="auth-input" style="margin:0;"><option value="draft">Черновик</option><option value="active">Активно</option><option value="done">Выполнено</option></select>
                    <input id="purchasePlanCommentX" class="auth-input" style="margin:0; grid-column:1 / -1;" placeholder="Комментарий по плану">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-secondary" onclick="savePurchasePlanX()">Сохранить план закупки</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="deliverySchedulePurchaseIdX" class="auth-input" style="margin:0;"><option value="0">Закупка</option>${purchaseOptions}</select>
                    <select id="deliveryScheduleSupplierIdX" class="auth-input" style="margin:0;"><option value="0">Поставщик</option>${supplierOptions}</select>
                    <input id="deliveryScheduleDateX" class="auth-input" style="margin:0;" placeholder="Дата поставки">
                    <input id="deliveryScheduleQtyX" class="auth-input" style="margin:0;" placeholder="Плановое количество">
                    <input id="deliveryScheduleDeliveredQtyX" class="auth-input" style="margin:0;" placeholder="Фактическое количество">
                    <select id="deliveryScheduleStatusX" class="auth-input" style="margin:0;"><option value="planned">Запланировано</option><option value="partial">Частично</option><option value="delivered">Доставлено</option><option value="late">Опаздывает</option></select>
                    <input id="deliveryScheduleTransportX" class="auth-input" style="margin:0;" placeholder="Транспорт / трек">
                    <input id="deliveryScheduleCommentX" class="auth-input" style="margin:0;" placeholder="Комментарий к графику">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-secondary" onclick="saveDeliveryScheduleX()">Сохранить график</button>
                </div>
                <div class="client360-list">${renderSimpleList(planFact.slice(0, 4), 'Планов закупки пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.period_key}</div><div class="client360-item-meta">${item.item_article || ''} · план ${formatMoney(item.target_amount || 0)} · факт ${formatMoney(item.fact_amount || 0)}</div></div><span class="status-badge ${opsHealthBadgeClass(Number(item.delta_amount || 0) <= 0 ? 'stable' : 'attention')}">${formatMoney(item.delta_amount || 0)}</span></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(scheduleAlerts.slice(0, 4), 'Графиков поставки пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.supplier_name || `Закупка #${item.purchase_id}`}</div><div class="client360-item-meta">${item.scheduled_date || ''} · ${item.delivered_qty || 0}/${item.planned_qty || 0} · остаток ${item.remaining_qty || 0}</div></div><button class="btn-danger" onclick="deleteDeliveryScheduleX(${item.id})">Удалить</button></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Возвраты, расхождения и сроки сервиса</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="supplierReturnPurchaseIdX" class="auth-input" style="margin:0;"><option value="0">Закупка возврата</option>${purchaseOptions}</select>
                    <select id="supplierReturnSupplierIdX" class="auth-input" style="margin:0;"><option value="0">Поставщик</option>${supplierOptions}</select>
                    <input id="supplierReturnArticleX" class="auth-input" style="margin:0;" placeholder="Артикул возврата">
                    <input id="supplierReturnItemNameX" class="auth-input" style="margin:0;" placeholder="Позиция">
                    <input id="supplierReturnQtyX" class="auth-input" style="margin:0;" placeholder="Количество возврата">
                    <input id="supplierReturnAmountX" class="auth-input" style="margin:0;" placeholder="Сумма">
                    <select id="supplierReturnStatusX" class="auth-input" style="margin:0;"><option value="draft">Черновик</option><option value="approved">Согласовано</option><option value="closed">Закрыто</option></select>
                    <input id="supplierReturnReasonX" class="auth-input" style="margin:0;" placeholder="Причина возврата">
                    <input id="supplierReturnWarehouseX" class="auth-input" style="margin:0;" placeholder="Склад">
                    <input id="supplierReturnBinX" class="auth-input" style="margin:0;" placeholder="Ячейка">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-secondary" onclick="saveSupplierReturnX()">Сохранить возврат</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="supplierDiscPurchaseIdX" class="auth-input" style="margin:0;"><option value="0">Закупка акта</option>${purchaseOptions}</select>
                    <select id="supplierDiscSupplierIdX" class="auth-input" style="margin:0;"><option value="0">Поставщик</option>${supplierOptions}</select>
                    <input id="supplierDiscArticleX" class="auth-input" style="margin:0;" placeholder="Артикул акта">
                    <input id="supplierDiscItemNameX" class="auth-input" style="margin:0;" placeholder="Позиция">
                    <input id="supplierDiscPlanQtyX" class="auth-input" style="margin:0;" placeholder="Плановое количество">
                    <input id="supplierDiscFactQtyX" class="auth-input" style="margin:0;" placeholder="Фактическое количество">
                    <input id="supplierDiscPlanPriceX" class="auth-input" style="margin:0;" placeholder="План цена">
                    <input id="supplierDiscFactPriceX" class="auth-input" style="margin:0;" placeholder="Факт цена">
                    <select id="supplierDiscStatusX" class="auth-input" style="margin:0;"><option value="open">Открыто</option><option value="resolved">Решено</option><option value="closed">Закрыто</option></select>
                    <input id="supplierDiscReasonX" class="auth-input" style="margin:0;" placeholder="Причина расхождения">
                    <input id="supplierDiscCommentX" class="auth-input" style="margin:0; grid-column:1 / -1;" placeholder="Комментарий к акту">
                </div>
                <div class="finance-actions-row" style="margin-bottom:12px;">
                    <button class="btn-secondary" onclick="saveSupplierDiscrepancyX()">Сохранить акт</button>
                </div>
                <div class="client360-list">${renderSimpleList(opsExtendedDB.supplierReturns.slice(0, 4), 'Возвратов поставщику пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.item_name || item.article || 'Возврат'}</div><div class="client360-item-meta">${item.supplier_name || 'без поставщика'} · ${item.qty || 0} · ${formatMoney(item.amount || 0, item.currency || 'RUB')}</div></div><button class="btn-danger" onclick="deleteSupplierReturnX(${item.id})">Удалить</button></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.supplierDiscrepancies.slice(0, 4), 'Актов расхождений пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.item_name || item.article || 'Акт'}</div><div class="client360-item-meta">${item.supplier_name || 'без поставщика'} · отклонение количества ${item.qty_gap || 0} · отклонение цены ${item.price_gap || 0}</div></div><button class="btn-danger" onclick="deleteSupplierDiscrepancyX(${item.id})">Удалить</button></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">RF-терминал склада</h4>
                <p class="section-subtitle" style="margin-bottom:10px;">Handheld-сценарий для кладовщика: скан задания, действие, журнал результата и очередь WMS в одном месте.</p>
                <div class="ops-summary-grid" style="margin-bottom:12px;">
                    <div class="ops-summary-stat"><div class="ops-summary-label">Активные терминалы</div><div class="ops-summary-value">${terminalMetrics.warehouse_sessions || 0}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Сканы за сутки</div><div class="ops-summary-value">${terminalMetrics.scans_today || 0}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">Ошибки скана</div><div class="ops-summary-value">${terminalMetrics.scan_errors || 0}</div></div>
                    <div class="ops-summary-stat"><div class="ops-summary-label">WMS очередь</div><div class="ops-summary-value">${terminalMetrics.wms_open_tasks || 0}</div></div>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="warehouseTerminalCodeX" class="auth-input" style="margin:0;" placeholder="Терминал, например RF-01">
                    <input id="warehouseTerminalScanX" class="auth-input" style="margin:0;" placeholder="Штрихкод: PUTAWAY-1 / PICK-1 / COUNT-1">
                    <select id="warehouseTerminalActionX" class="auth-input" style="margin:0;"><option value="lookup">Проверить</option><option value="complete_putaway">Разместить</option><option value="pick">Подобрать</option><option value="cycle_count">Пересчитать</option></select>
                    <input id="warehouseTerminalQtyX" class="auth-input" style="margin:0;" placeholder="Факт для пересчета">
                    <button class="btn-secondary" onclick="startWarehouseTerminalX()">Открыть смену</button>
                    <button class="btn-primary" onclick="submitWarehouseTerminalScanX()">Скан</button>
                </div>
                <div class="client360-list">${renderSimpleList(terminalScans.filter(item => item.terminal_type === 'warehouse').slice(0, 5), 'Складских сканов пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.scan_value || 'scan'} · ${item.action_name || 'lookup'}</div><div class="client360-item-meta">${item.entity_type || 'без объекта'} #${item.entity_id || 0} · ${item.created_by || 'оператор'}</div></div><span class="status-badge ${opsHealthBadgeClass(item.result_status === 'error' ? 'risk' : 'stable')}">${opsDisplayStatus(item.result_status || 'success')}</span></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">WMS: адресное хранение, размещение и подбор</h4>
                <div id="wmsBulkActionsMount"></div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="wmsCellWarehouseX" class="auth-input" style="margin:0;" placeholder="Склад ячейки">
                    <input id="wmsCellBinX" class="auth-input" style="margin:0;" placeholder="Ячейка">
                    <input id="wmsCellZoneX" class="auth-input" style="margin:0;" placeholder="Зона">
                    <select id="wmsCellTypeX" class="auth-input" style="margin:0;"><option value="storage">Хранение</option><option value="pick">Подбор</option><option value="receiving">Приемка</option><option value="shipping">Отгрузка</option></select>
                    <input id="wmsCellCapacityX" class="auth-input" style="margin:0;" placeholder="Вместимость, шт">
                    <input id="wmsCellAbcX" class="auth-input" style="margin:0;" placeholder="ABC">
                    <button class="btn-secondary" onclick="saveWmsCellX()">Сохранить ячейку</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="wmsPutawayArticleX" class="auth-input" style="margin:0;" placeholder="Артикул размещения">
                    <input id="wmsPutawayNameX" class="auth-input" style="margin:0;" placeholder="Наименование">
                    <input id="wmsPutawayQtyX" class="auth-input" style="margin:0;" placeholder="Количество">
                    <input id="wmsPutawaySourceWhX" class="auth-input" style="margin:0;" placeholder="Из склада">
                    <input id="wmsPutawaySourceBinX" class="auth-input" style="margin:0;" placeholder="Из ячейки">
                    <input id="wmsPutawayTargetWhX" class="auth-input" style="margin:0;" placeholder="В склад">
                    <input id="wmsPutawayTargetBinX" class="auth-input" style="margin:0;" placeholder="В ячейку">
                    <input id="wmsPutawayBatchX" class="auth-input" style="margin:0;" placeholder="Партия">
                    <input id="wmsPutawaySerialX" class="auth-input" style="margin:0;" placeholder="Серия">
                    <button class="btn-secondary" onclick="saveWmsPutawayTaskX()">Задание размещения</button>
                </div>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <select id="wmsWaveReservationIdX" class="auth-input" style="margin:0;"><option value="0">Резерв для волны</option>${stockReservationOptions}</select>
                    <select id="wmsWavePriorityX" class="auth-input" style="margin:0;"><option value="normal">Обычная волна</option><option value="high">Высокий приоритет</option><option value="urgent">Срочная</option></select>
                    <input id="wmsWaveShipDateX" class="auth-input" style="margin:0;" placeholder="План отгрузки">
                    <button class="btn-secondary" onclick="saveWmsPickWaveX()">Создать волну</button>
                    <input id="wmsCountWarehouseX" class="auth-input" style="margin:0;" placeholder="Склад пересчета">
                    <input id="wmsCountBinX" class="auth-input" style="margin:0;" placeholder="Ячейка пересчета">
                    <input id="wmsCountArticleX" class="auth-input" style="margin:0;" placeholder="Артикул строки">
                    <input id="wmsCountExpectedX" class="auth-input" style="margin:0;" placeholder="Учёт">
                    <input id="wmsCountFactX" class="auth-input" style="margin:0;" placeholder="Факт">
                    <button class="btn-secondary" onclick="saveWmsCycleCountX()">Пересчет WMS</button>
                </div>
                <div class="client360-list">${renderSimpleList(opsExtendedDB.wmsCells.slice(0, 5), 'Ячейки WMS пока не заведены.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.warehouse || 'Склад'} · ${item.bin_code || 'ячейка'}</div><div class="client360-item-meta">${item.zone_name || 'без зоны'} · загрузка ${item.load_percent || 0}% · свободно ${item.free_qty || 0}</div></div><div class="view-actions"><span class="status-badge ${opsHealthBadgeClass(item.risk_level || 'stable')}">${opsDisplayStatus(item.status || 'active')}</span><button class="btn-danger" onclick="deleteWmsCellX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.wmsPutawayTasks.slice(0, 4), 'Заданий размещения пока нет.', item => `<div class="client360-item"><div class="bulk-list-select">${renderWmsBulkCheckbox('wms_putaway_task', item.id)}</div><div><div class="client360-item-title">${item.article || 'Артикул'} · ${item.qty || 0}</div><div class="client360-item-meta">${item.source_warehouse || ''}/${item.source_bin || ''} → ${item.target_warehouse || ''}/${item.target_bin || ''} · партия ${item.batch_code || '-'}</div></div><div class="view-actions"><span class="status-badge ${opsHealthBadgeClass(item.status === 'done' ? 'stable' : 'attention')}">${opsDisplayStatus(item.status || 'open')}</span><button class="btn-secondary" onclick="completeWmsPutawayTaskX(${item.id})">Разместить</button><button class="btn-danger" onclick="deleteWmsPutawayTaskX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.wmsPickWaves.slice(0, 4), 'Волн подбора пока нет.', item => `<div class="client360-item"><div class="bulk-list-select">${renderWmsBulkCheckbox('wms_pick_wave', item.id)}</div><div><div class="client360-item-title">${item.wave_number || `Волна #${item.id}`}</div><div class="client360-item-meta">${opsDisplayStatus(item.status || 'draft')} · задач ${item.tasks_done || 0}/${item.tasks_total || 0} · подобрано ${item.picked_total || 0}/${item.qty_total || 0}</div></div><div class="view-actions"><button class="btn-secondary" onclick="releaseWmsPickWaveX(${item.id})">В работу</button><button class="btn-danger" onclick="deleteWmsPickWaveX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.wmsPickTasks.slice(0, 5), 'Заданий подбора пока нет.', item => `<div class="client360-item"><div class="bulk-list-select">${renderWmsBulkCheckbox('wms_pick_task', item.id)}</div><div><div class="client360-item-title">${item.article || 'Артикул'} · ${item.qty || 0}</div><div class="client360-item-meta">${item.warehouse || ''}/${item.bin_code || ''} · подобрано ${item.picked_qty || 0} · резерв #${item.reservation_id || 0}</div></div><div class="view-actions"><span class="status-badge ${opsHealthBadgeClass(item.status === 'done' ? 'stable' : 'attention')}">${opsDisplayStatus(item.status || 'open')}</span><button class="btn-secondary" onclick="pickWmsTaskX(${item.id})">Подобрать</button><button class="btn-danger" onclick="deleteWmsPickTaskX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.wmsCycleCounts.slice(0, 4), 'Циклических пересчетов пока нет.', item => `<div class="client360-item"><div class="bulk-list-select">${renderWmsBulkCheckbox('wms_cycle_count', item.id)}</div><div><div class="client360-item-title">${item.count_number || `Пересчет #${item.id}`}</div><div class="client360-item-meta">${item.warehouse || ''}/${item.bin_code || ''} · строк ${item.lines_total || 0} · расхождений ${item.variance_lines || 0}</div></div><div class="view-actions"><span class="status-badge ${opsHealthBadgeClass(item.status === 'closed' ? 'stable' : 'attention')}">${opsDisplayStatus(item.status || 'draft')}</span><button class="btn-secondary" onclick="closeWmsCycleCountX(${item.id})">Закрыть</button><button class="btn-danger" onclick="deleteWmsCycleCountX(${item.id})">Удалить</button></div></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.wmsLotPositions.slice(0, 5), 'Партийных/серийных остатков пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.article || 'Артикул'} · ${item.qty || 0}</div><div class="client360-item-meta">${item.warehouse || ''}/${item.bin_code || ''} · партия ${item.batch_code || '-'} · серия ${item.serial_no || '-'}</div></div><span class="status-badge status-active">Партия</span></div>`)}</div>
            </section>
            <section class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title">Складовой контроль</h4>
                <div class="finance-form-grid" style="margin-bottom:12px;">
                    <input id="inventoryActArticleX" class="auth-input" style="margin:0;" placeholder="Артикул инвентаризации">
                    <input id="inventoryActExpectedQtyX" class="auth-input" style="margin:0;" placeholder="Учётное количество">
                    <input id="inventoryActCountedQtyX" class="auth-input" style="margin:0;" placeholder="Фактическое количество">
                    <button class="btn-secondary" onclick="saveInventoryActX()">Инв. акт</button>
                    <input id="regradingFromArticleX" class="auth-input" style="margin:0;" placeholder="Из артикула">
                    <input id="regradingToArticleX" class="auth-input" style="margin:0;" placeholder="В артикул">
                    <input id="regradingQtyX" class="auth-input" style="margin:0;" placeholder="Количество пересортицы">
                    <button class="btn-secondary" onclick="saveRegradingX()">Пересортица</button>
                    <input id="qualityArticleX" class="auth-input" style="margin:0;" placeholder="Артикул качества">
                    <input id="qualityQtyX" class="auth-input" style="margin:0;" placeholder="Количество удержания">
                    <select id="qualityStatusX" class="auth-input" style="margin:0;"><option value="open">Открыто</option><option value="hold">Удержание</option><option value="released">Выпущено</option></select>
                    <button class="btn-secondary" onclick="saveQualityReportX()">Качество</button>
                </div>
                <div class="client360-list">${renderSimpleList(opsExtendedDB.inventoryActs.slice(0, 4), 'Инвентаризационных актов пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.article}</div><div class="client360-item-meta">учет ${item.expected_qty || 0} · факт ${item.counted_qty || 0} · коррекция ${item.adjustment_qty || 0}</div></div><button class="btn-danger" onclick="deleteInventoryActX(${item.id})">Удалить</button></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.regradingDocs.slice(0, 4), 'Пересортицы пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.from_article} → ${item.to_article}</div><div class="client360-item-meta">${item.qty || 0} · ${item.reason || 'regrading'}</div></div><button class="btn-danger" onclick="deleteRegradingX(${item.id})">Удалить</button></div>`)}</div>
                <div class="client360-list" style="margin-top:12px;">${renderSimpleList(opsExtendedDB.qualityReports.slice(0, 4), 'Отчётов по качеству пока нет.', item => `<div class="client360-item"><div><div class="client360-item-title">${item.article}</div><div class="client360-item-meta">${item.qty || 0} · ${item.quality_status || item.status || ''}</div></div><button class="btn-danger" onclick="deleteQualityReportX(${item.id})">Удалить</button></div>`)}</div>
            </section>
        </div>
    `;
}

const baseRenderSales = renderSales;
renderSales = async function renderSalesExtended() {
    await baseRenderSales();
    const mount = document.getElementById('salesExtendedMount');
    if (mount) mount.innerHTML = salesExtendedMarkup();
};

const baseRenderSupply = renderSupply;
renderSupply = async function renderSupplyExtended() {
    await baseRenderSupply();
    const mount = document.getElementById('supplyExtendedMount');
    if (mount) {
        mount.innerHTML = supplyExtendedMarkup();
        const costMethod = document.getElementById('stockCostMethodX');
        const negative = document.getElementById('stockNegativePolicyX');
        if (costMethod) costMethod.value = opsExtendedDB.stockPolicy?.cost_method || 'fifo';
        if (negative) negative.value = String(opsExtendedDB.stockPolicy?.allow_negative_stock || 0);
        renderWmsBulkToolbar();
    }
    if (typeof window.switchSupplyWorkspaceTab === 'function') {
        window.switchSupplyWorkspaceTab(window.supplyActiveWorkspaceTab || 'purchase');
    }
};

async function refreshSalesExtended() { await renderSales(); }
async function refreshSupplyExtended() { await renderSupply(); }

async function saveSalesQuoteX() {
    if (!(await saveExtendedOpsRecord('/sales/quotes', {
        project_id: Number(document.getElementById('salesQuoteProjectIdX')?.value || 0),
        client_id: Number(document.getElementById('salesQuoteClientIdX')?.value || 0),
        title: document.getElementById('salesQuoteTitleX')?.value.trim() || '',
        amount: Number(document.getElementById('salesQuoteAmountX')?.value || 0),
        stage: document.getElementById('salesQuoteStageX')?.value || 'draft',
        probability: Number(document.getElementById('salesQuoteProbabilityX')?.value || 0),
        valid_until: document.getElementById('salesQuoteValidUntilX')?.value.trim() || '',
        responsible: document.getElementById('salesQuoteResponsibleX')?.value.trim() || '',
        comment: document.getElementById('salesQuoteCommentX')?.value.trim() || '',
    }, 'КП сохранено'))) return;
    await refreshSalesExtended();
}
async function saveSalesPlanX() {
    if (!(await saveExtendedOpsRecord('/sales/plans', {
        period_key: document.getElementById('salesPlanPeriodX')?.value.trim() || '',
        manager_name: document.getElementById('salesPlanManagerX')?.value.trim() || '',
        client_id: Number(document.getElementById('salesPlanClientIdX')?.value || 0),
        project_id: Number(document.getElementById('salesPlanProjectIdX')?.value || 0),
        target_amount: Number(document.getElementById('salesPlanAmountX')?.value || 0),
        target_docs: Number(document.getElementById('salesPlanDocsX')?.value || 0),
        status: document.getElementById('salesPlanStatusX')?.value || 'draft',
        comment: document.getElementById('salesPlanCommentX')?.value.trim() || '',
    }, 'План продаж сохранён'))) return;
    await refreshSalesExtended();
}
async function savePriceListX() {
    if (!(await saveExtendedOpsRecord('/sales/price_lists', {
        name: document.getElementById('priceListNameX')?.value.trim() || '',
        currency: document.getElementById('priceListCurrencyX')?.value || 'RUB',
        valid_from: document.getElementById('priceListValidFromX')?.value.trim() || '',
        valid_to: document.getElementById('priceListValidToX')?.value.trim() || '',
        item_article: document.getElementById('priceListArticleX')?.value.trim() || '',
        item_name: document.getElementById('priceListItemNameX')?.value.trim() || '',
        base_price: Number(document.getElementById('priceListBasePriceX')?.value || 0),
        min_price: Number(document.getElementById('priceListMinPriceX')?.value || 0),
        status: document.getElementById('priceListStatusX')?.value || 'active',
        comment: document.getElementById('priceListCommentX')?.value.trim() || '',
    }, 'Прайс сохранён'))) return;
    await refreshSalesExtended();
}
async function saveClientTermsX() {
    if (!(await saveExtendedOpsRecord('/sales/client_terms', {
        client_id: Number(document.getElementById('clientTermsClientIdX')?.value || 0),
        price_list_id: Number(document.getElementById('clientTermsPriceListIdX')?.value || 0),
        discount_percent: Number(document.getElementById('clientTermsDiscountX')?.value || 0),
        discount_amount: Number(document.getElementById('clientTermsDiscountAmountX')?.value || 0),
        payment_delay_days: Number(document.getElementById('clientTermsPaymentDelayX')?.value || 0),
        credit_limit: Number(document.getElementById('clientTermsCreditLimitX')?.value || 0),
        shipment_priority: document.getElementById('clientTermsShipmentPriorityX')?.value || 'normal',
        status: document.getElementById('clientTermsStatusX')?.value || 'active',
        comment: document.getElementById('clientTermsCommentX')?.value.trim() || '',
    }, 'Условия клиента сохранены'))) return;
    await refreshSalesExtended();
}
async function saveSalesReturnX() {
    if (!(await saveExtendedOpsRecord('/sales/returns', {
        client_id: Number(document.getElementById('salesReturnClientIdX')?.value || 0),
        sales_document_id: Number(document.getElementById('salesReturnDocumentIdX')?.value || 0),
        article: document.getElementById('salesReturnArticleX')?.value.trim() || '',
        item_name: document.getElementById('salesReturnItemNameX')?.value.trim() || '',
        qty: Number(document.getElementById('salesReturnQtyX')?.value || 0),
        amount: Number(document.getElementById('salesReturnAmountX')?.value || 0),
        status: document.getElementById('salesReturnStatusX')?.value || 'draft',
        reason: document.getElementById('salesReturnReasonX')?.value.trim() || '',
    }, 'Возврат клиента сохранён'))) return;
    await refreshSalesExtended();
}
async function saveSalesCustomerOrderX() {
    const qty = Number(document.getElementById('salesOrderQtyX')?.value || 0);
    const unitPrice = Number(document.getElementById('salesOrderUnitPriceX')?.value || 0);
    if (!(await saveExtendedOpsRecord('/sales/customer_orders', {
        quote_id: Number(document.getElementById('salesOrderQuoteIdX')?.value || 0),
        client_id: Number(document.getElementById('salesOrderClientIdX')?.value || 0),
        project_id: Number(document.getElementById('salesOrderProjectIdX')?.value || 0),
        article: document.getElementById('salesOrderArticleX')?.value.trim() || '',
        item_name: document.getElementById('salesOrderItemNameX')?.value.trim() || '',
        qty,
        unit_price: unitPrice,
        amount: Number(document.getElementById('salesOrderAmountX')?.value || 0) || (qty * unitPrice),
        requested_ship_date: document.getElementById('salesOrderShipDateX')?.value.trim() || '',
        status: 'confirmed',
        comment: 'Заказ клиента из контура продаж',
    }, 'Заказ клиента создан'))) return;
    await refreshSalesExtended();
}
async function reserveSalesCustomerOrderX(orderId = 0) {
    const selectedOrderId = Number(orderId || document.getElementById('salesOpsOrderIdX')?.value || 0);
    if (!selectedOrderId) return customAlert('Выбери заказ клиента для резерва.');
    const res = await apiCall(`/sales/customer_orders/${selectedOrderId}/reserve`, 'POST', {
        warehouse: document.getElementById('salesOpsWarehouseX')?.value.trim() || '',
        bin_code: document.getElementById('salesOpsBinX')?.value.trim() || '',
        batch_code: document.getElementById('salesOpsBatchX')?.value.trim() || '',
        comment: 'Резерв по заказу клиента',
    });
    if (!res || res.error) return customAlert(explainExtendedOpsError(res?.error || 'Не удалось зарезервировать товар.'));
    showToast('Продажи', res.reserve_status === 'reserved' ? 'Товар зарезервирован' : 'Создан резерв с дефицитом');
    await refreshSalesExtended();
}
async function createSalesDocumentFromOrderX(orderId = 0) {
    const selectedOrderId = Number(orderId || document.getElementById('salesOpsOrderIdX')?.value || 0);
    if (!selectedOrderId) return customAlert('Выбери заказ клиента для реализации.');
    const res = await apiCall(`/sales/customer_orders/${selectedOrderId}/create_document`, 'POST', {});
    if (!res || res.error) return customAlert(explainExtendedOpsError(res?.error || 'Не удалось создать реализацию.'));
    showToast('Продажи', res.already_created ? `Реализация уже есть #${res.id}` : `Реализация создана #${res.id}`);
    await refreshSalesExtended();
}
async function saveSalesShipmentX() {
    const orderId = Number(document.getElementById('salesShipmentOrderIdX')?.value || 0);
    const order = opsExtendedDB.customerOrders.find(item => Number(item.id) === orderId);
    if (!(await saveExtendedOpsRecord('/sales/shipments', {
        customer_order_id: orderId,
        sales_document_id: Number(document.getElementById('salesShipmentDocIdX')?.value || 0) || Number(order?.sales_document_id || 0),
        reservation_id: Number(order?.reservation_id || 0),
        article: order?.article || '',
        item_name: order?.item_name || '',
        qty: Number(document.getElementById('salesShipmentQtyX')?.value || 0) || Number(order?.qty || 0),
        warehouse: document.getElementById('salesShipmentWarehouseX')?.value.trim() || '',
        bin_code: document.getElementById('salesShipmentBinX')?.value.trim() || '',
        batch_code: document.getElementById('salesShipmentBatchX')?.value.trim() || '',
        planned_ship_date: order?.requested_ship_date || '',
        carrier: document.getElementById('salesShipmentCarrierX')?.value.trim() || '',
        status: 'planned',
        comment: 'Задание отгрузки по заказу клиента',
    }, 'Задание отгрузки создано'))) return;
    await refreshSalesExtended();
}
async function shipSalesShipmentX(id) {
    const res = await apiCall(`/sales/shipments/${id}/ship`, 'POST', {});
    if (!res || res.error) return customAlert(explainExtendedOpsError(res?.error || 'Не удалось провести отгрузку.'));
    showToast('Продажи', 'Отгрузка проведена');
    await refreshSalesExtended();
}
async function saveSalesPaymentScheduleX() {
    const orderId = Number(document.getElementById('salesOpsOrderIdX')?.value || 0);
    const order = opsExtendedDB.customerOrders.find(item => Number(item.id) === orderId);
    if (!orderId) return customAlert('Выбери заказ клиента для графика оплат.');
    if (!(await saveExtendedOpsRecord('/sales/payment_schedules', {
        customer_order_id: orderId,
        sales_document_id: Number(order?.sales_document_id || 0),
        due_date: document.getElementById('salesScheduleDueDateX')?.value.trim() || '',
        amount: Number(document.getElementById('salesScheduleAmountX')?.value || 0) || Number(order?.amount || 0),
        currency: order?.currency || 'RUB',
        status: 'planned',
        comment: 'Плановая дебиторка по заказу клиента',
    }, 'График оплаты создан'))) return;
    await refreshSalesExtended();
}
async function markSalesPaymentSchedulePaidX(id) {
    const res = await apiCall(`/sales/payment_schedules/${id}/mark_paid`, 'POST', {});
    if (!res || res.error) return customAlert(explainExtendedOpsError(res?.error || 'Не удалось отметить оплату.'));
    showToast('Продажи', 'Платеж отмечен оплаченным');
    await refreshSalesExtended();
}
async function recalculateSalesDealMarginX(orderId = 0) {
    const selectedOrderId = Number(orderId || document.getElementById('salesOpsOrderIdX')?.value || 0);
    if (!selectedOrderId) return customAlert('Выбери заказ клиента для расчета маржи.');
    const res = await apiCall('/sales/deal_margins/recalculate', 'POST', { customer_order_id: selectedOrderId });
    if (!res || res.error) return customAlert(explainExtendedOpsError(res?.error || 'Не удалось рассчитать маржу.'));
    showToast('Продажи', 'Маржа сделки пересчитана');
    await refreshSalesExtended();
}

async function prefillSalesFromQuoteX(id) {
    const quote = (opsExtendedDB.quotes || []).find(item => Number(item.id) === Number(id));
    if (!quote) return customAlert('Коммерческое предложение не найдено.');
    const clientId = Number(quote.client_id || 0);
    const terms = getClientTermsForSales(clientId);
    const discountPercent = Number(terms?.discount_percent || 0);
    const discountAmount = Number(terms?.discount_amount || 0);
    const quoteAmount = Number(quote.amount || 0);
    const calcDiscount = discountAmount || (discountPercent > 0 ? (quoteAmount * discountPercent / 100) : 0);
    const finalAmount = Math.max(quoteAmount - calcDiscount, 0);
    const priceListId = Number(terms?.price_list_id || 0);
    const salesDocType = document.getElementById('salesDocType');
    const salesProjectId = document.getElementById('salesProjectId');
    const salesClientId = document.getElementById('salesClientId');
    const salesAmount = document.getElementById('salesAmount');
    const salesDocNumber = document.getElementById('salesDocNumber');
    const salesDocDate = document.getElementById('salesDocDate');
    const salesComment = document.getElementById('salesComment');
    const salesPriceListId = document.getElementById('salesPriceListId');
    const salesDiscountPercent = document.getElementById('salesDiscountPercent');
    const salesDiscountAmount = document.getElementById('salesDiscountAmount');
    const salesPaymentDueDate = document.getElementById('salesPaymentDueDate');
    if (salesDocType) salesDocType.value = 'invoice';
    if (salesProjectId) salesProjectId.value = String(Number(quote.project_id || 0));
    if (salesClientId) salesClientId.value = String(clientId);
    if (salesAmount) salesAmount.value = String(finalAmount || quoteAmount || 0);
    if (salesDocNumber && !String(salesDocNumber.value || '').trim()) salesDocNumber.value = `INV-${quote.quote_number || quote.id}`;
    if (salesDocDate && !String(salesDocDate.value || '').trim()) salesDocDate.value = quote.valid_until || '';
    if (salesComment) salesComment.value = [salesComment.value, `Из КП ${quote.quote_number || quote.id}: ${quote.title || ''}`].filter(Boolean).join('\n').trim();
    if (salesPriceListId && priceListId > 0) salesPriceListId.value = String(priceListId);
    if (salesDiscountPercent) salesDiscountPercent.value = discountPercent ? String(discountPercent) : '';
    if (salesDiscountAmount) salesDiscountAmount.value = calcDiscount ? String(calcDiscount) : '';
    if (salesPaymentDueDate && terms?.payment_delay_days) salesPaymentDueDate.value = addDaysToDisplayDate(Number(terms.payment_delay_days || 0), document.getElementById('salesDocDate')?.value || '');
    applySalesClientTerms();
    const formCard = document.querySelector('#salesView .ops-form-card');
    if (formCard) formCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    showToast('Продажи', 'КП перенесено в форму реализации');
}

async function saveSupplierX() {
    if (!(await saveExtendedOpsRecord('/suppliers', {
        supplier_name: document.getElementById('supplierNameX')?.value.trim() || '',
        inn: document.getElementById('supplierInnX')?.value.trim() || '',
        category: document.getElementById('supplierCategoryX')?.value.trim() || '',
        lead_time_days: Number(document.getElementById('supplierLeadTimeX')?.value || 0),
        rating: Number(document.getElementById('supplierRatingX')?.value || 0),
        reliability_percent: Number(document.getElementById('supplierReliabilityX')?.value || 100),
        payment_terms: document.getElementById('supplierPaymentTermsX')?.value.trim() || '',
        comment: document.getElementById('supplierCommentX')?.value.trim() || '',
    }, 'Поставщик сохранён'))) return;
    await refreshSupplyExtended();
}
async function savePurchasePlanX() {
    const qtyPlan = Number(document.getElementById('purchasePlanQtyX')?.value || 0);
    const targetUnitPrice = Number(document.getElementById('purchasePlanTargetUnitPriceX')?.value || 0);
    const targetAmount = Number(document.getElementById('purchasePlanAmountX')?.value || 0) || (qtyPlan * targetUnitPrice);
    if (!(await saveExtendedOpsRecord('/purchase/plans', {
        period_key: document.getElementById('purchasePlanPeriodX')?.value.trim() || '',
        supplier_id: Number(document.getElementById('purchasePlanSupplierIdX')?.value || 0),
        project_id: Number(document.getElementById('purchasePlanProjectIdX')?.value || 0),
        item_article: document.getElementById('purchasePlanArticleX')?.value.trim() || '',
        item_name: document.getElementById('purchasePlanItemNameX')?.value.trim() || '',
        qty_plan: qtyPlan,
        unit: document.getElementById('purchasePlanUnitX')?.value.trim() || 'шт',
        target_unit_price: targetUnitPrice,
        target_amount: targetAmount,
        status: document.getElementById('purchasePlanStatusX')?.value || 'draft',
        comment: document.getElementById('purchasePlanCommentX')?.value.trim() || '',
    }, 'План закупки сохранён'))) return;
    await refreshSupplyExtended();
}
async function saveDeliveryScheduleX() {
    if (!(await saveExtendedOpsRecord('/purchase/delivery_schedules', {
        purchase_id: Number(document.getElementById('deliverySchedulePurchaseIdX')?.value || 0),
        supplier_id: Number(document.getElementById('deliveryScheduleSupplierIdX')?.value || 0),
        planned_qty: Number(document.getElementById('deliveryScheduleQtyX')?.value || 0),
        delivered_qty: Number(document.getElementById('deliveryScheduleDeliveredQtyX')?.value || 0),
        scheduled_date: document.getElementById('deliveryScheduleDateX')?.value.trim() || '',
        status: document.getElementById('deliveryScheduleStatusX')?.value || 'planned',
        transport_no: document.getElementById('deliveryScheduleTransportX')?.value.trim() || '',
        comment: document.getElementById('deliveryScheduleCommentX')?.value.trim() || '',
    }, 'График поставки сохранён'))) return;
    await refreshSupplyExtended();
}
async function saveSupplierReturnX() {
    if (!(await saveExtendedOpsRecord('/purchase/returns', {
        purchase_id: Number(document.getElementById('supplierReturnPurchaseIdX')?.value || 0),
        supplier_id: Number(document.getElementById('supplierReturnSupplierIdX')?.value || 0),
        article: document.getElementById('supplierReturnArticleX')?.value.trim() || '',
        item_name: document.getElementById('supplierReturnItemNameX')?.value.trim() || '',
        qty: Number(document.getElementById('supplierReturnQtyX')?.value || 0),
        amount: Number(document.getElementById('supplierReturnAmountX')?.value || 0),
        status: document.getElementById('supplierReturnStatusX')?.value || 'draft',
        reason: document.getElementById('supplierReturnReasonX')?.value.trim() || '',
        warehouse: document.getElementById('supplierReturnWarehouseX')?.value.trim() || '',
        bin_code: document.getElementById('supplierReturnBinX')?.value.trim() || '',
    }, 'Возврат поставщику сохранён'))) return;
    await refreshSupplyExtended();
}
async function saveSupplierDiscrepancyX() {
    if (!(await saveExtendedOpsRecord('/purchase/discrepancy_acts', {
        purchase_id: Number(document.getElementById('supplierDiscPurchaseIdX')?.value || 0),
        supplier_id: Number(document.getElementById('supplierDiscSupplierIdX')?.value || 0),
        article: document.getElementById('supplierDiscArticleX')?.value.trim() || '',
        item_name: document.getElementById('supplierDiscItemNameX')?.value.trim() || '',
        planned_qty: Number(document.getElementById('supplierDiscPlanQtyX')?.value || 0),
        actual_qty: Number(document.getElementById('supplierDiscFactQtyX')?.value || 0),
        planned_unit_price: Number(document.getElementById('supplierDiscPlanPriceX')?.value || 0),
        actual_unit_price: Number(document.getElementById('supplierDiscFactPriceX')?.value || 0),
        status: document.getElementById('supplierDiscStatusX')?.value || 'open',
        reason: document.getElementById('supplierDiscReasonX')?.value.trim() || '',
        comment: document.getElementById('supplierDiscCommentX')?.value.trim() || '',
    }, 'Акт расхождений сохранён'))) return;
    await refreshSupplyExtended();
}
async function saveInventoryActX() {
    if (!(await saveExtendedOpsRecord('/stock/inventory_acts', { article: document.getElementById('inventoryActArticleX')?.value.trim() || '', expected_qty: Number(document.getElementById('inventoryActExpectedQtyX')?.value || 0), counted_qty: Number(document.getElementById('inventoryActCountedQtyX')?.value || 0) }, 'Инвентаризационный акт сохранён'))) return;
    await refreshSupplyExtended();
}
async function saveRegradingX() {
    if (!(await saveExtendedOpsRecord('/stock/regrading', { from_article: document.getElementById('regradingFromArticleX')?.value.trim() || '', to_article: document.getElementById('regradingToArticleX')?.value.trim() || '', qty: Number(document.getElementById('regradingQtyX')?.value || 0) }, 'Пересортица сохранена'))) return;
    await refreshSupplyExtended();
}
async function saveQualityReportX() {
    if (!(await saveExtendedOpsRecord('/stock/quality_reports', { article: document.getElementById('qualityArticleX')?.value.trim() || '', qty: Number(document.getElementById('qualityQtyX')?.value || 0), quality_status: document.getElementById('qualityStatusX')?.value || 'open', status: document.getElementById('qualityStatusX')?.value || 'open' }, 'Отчёт качества сохранён'))) return;
    await refreshSupplyExtended();
}
async function saveStockPolicyX() {
    if (!(await saveExtendedOpsRecord('/stock/policy', { cost_method: document.getElementById('stockCostMethodX')?.value || 'fifo', allow_negative_stock: Number(document.getElementById('stockNegativePolicyX')?.value || 0) }, 'Складская политика обновлена'))) return;
    await refreshSupplyExtended();
}
async function saveWmsCellX() {
    if (!(await saveExtendedOpsRecord('/wms/cells', {
        warehouse: document.getElementById('wmsCellWarehouseX')?.value.trim() || '',
        bin_code: document.getElementById('wmsCellBinX')?.value.trim() || '',
        zone_name: document.getElementById('wmsCellZoneX')?.value.trim() || '',
        cell_type: document.getElementById('wmsCellTypeX')?.value || 'storage',
        capacity_qty: Number(document.getElementById('wmsCellCapacityX')?.value || 0),
        abc_class: document.getElementById('wmsCellAbcX')?.value.trim() || '',
        status: 'active',
    }, 'WMS-ячейка сохранена'))) return;
    await refreshSupplyExtended();
}
async function saveWmsPutawayTaskX() {
    if (!(await saveExtendedOpsRecord('/wms/putaway_tasks', {
        article: document.getElementById('wmsPutawayArticleX')?.value.trim() || '',
        item_name: document.getElementById('wmsPutawayNameX')?.value.trim() || '',
        qty: Number(document.getElementById('wmsPutawayQtyX')?.value || 0),
        source_warehouse: document.getElementById('wmsPutawaySourceWhX')?.value.trim() || '',
        source_bin: document.getElementById('wmsPutawaySourceBinX')?.value.trim() || '',
        target_warehouse: document.getElementById('wmsPutawayTargetWhX')?.value.trim() || '',
        target_bin: document.getElementById('wmsPutawayTargetBinX')?.value.trim() || '',
        batch_code: document.getElementById('wmsPutawayBatchX')?.value.trim() || '',
        serial_no: document.getElementById('wmsPutawaySerialX')?.value.trim() || '',
        priority: 'normal',
        comment: 'Задание адресного размещения',
    }, 'Задание размещения создано'))) return;
    await refreshSupplyExtended();
}
async function completeWmsPutawayTaskX(id) {
    const res = await apiCall(`/wms/putaway_tasks/${id}/complete`, 'POST', {});
    if (!res || res.error) {
        await customAlert(explainExtendedOpsError(res?.error || 'Не удалось разместить товар.'));
        return;
    }
    showToast('WMS', 'Товар размещён по ячейкам');
    await refreshSupplyExtended();
}
async function saveWmsPickWaveX() {
    const reservationId = Number(document.getElementById('wmsWaveReservationIdX')?.value || 0);
    if (!(await saveExtendedOpsRecord('/wms/pick_waves', {
        reservation_ids: reservationId ? [reservationId] : [],
        priority: document.getElementById('wmsWavePriorityX')?.value || 'normal',
        planned_ship_date: document.getElementById('wmsWaveShipDateX')?.value.trim() || '',
        comment: 'Волна подбора из WMS',
    }, 'Волна подбора создана'))) return;
    await refreshSupplyExtended();
}
async function releaseWmsPickWaveX(id) {
    const res = await apiCall(`/wms/pick_waves/${id}/release`, 'POST', {});
    if (!res || res.error) {
        await customAlert(explainExtendedOpsError(res?.error || 'Не удалось выпустить волну.'));
        return;
    }
    showToast('WMS', 'Волна подбора выпущена в работу');
    await refreshSupplyExtended();
}
async function pickWmsTaskX(id) {
    const res = await apiCall(`/wms/pick_tasks/${id}/pick`, 'POST', {});
    if (!res || res.error) {
        await customAlert(explainExtendedOpsError(res?.error || 'Не удалось выполнить подбор.'));
        return;
    }
    showToast('WMS', 'Задание подбора выполнено');
    await refreshSupplyExtended();
}
async function saveWmsCycleCountX() {
    const countRes = await apiCall('/wms/cycle_counts', 'POST', {
        warehouse: document.getElementById('wmsCountWarehouseX')?.value.trim() || '',
        bin_code: document.getElementById('wmsCountBinX')?.value.trim() || '',
        comment: 'Циклический пересчет WMS',
    });
    if (!countRes || countRes.error) {
        await customAlert(explainExtendedOpsError(countRes?.error || 'Не удалось создать пересчет.'));
        return;
    }
    const article = document.getElementById('wmsCountArticleX')?.value.trim() || '';
    if (article) {
        const lineRes = await apiCall(`/wms/cycle_counts/${countRes.id}/lines`, 'POST', {
            article,
            warehouse: document.getElementById('wmsCountWarehouseX')?.value.trim() || '',
            bin_code: document.getElementById('wmsCountBinX')?.value.trim() || '',
            expected_qty: Number(document.getElementById('wmsCountExpectedX')?.value || 0),
            counted_qty: Number(document.getElementById('wmsCountFactX')?.value || 0),
            comment: 'Ручная строка пересчета',
        });
        if (!lineRes || lineRes.error) {
            await customAlert(explainExtendedOpsError(lineRes?.error || 'Пересчет создан, но строка не добавлена.'));
            return;
        }
    }
    showToast('WMS', 'Циклический пересчет создан');
    await refreshSupplyExtended();
}
async function closeWmsCycleCountX(id) {
    const res = await apiCall(`/wms/cycle_counts/${id}/close`, 'POST', {});
    if (!res || res.error) {
        await customAlert(explainExtendedOpsError(res?.error || 'Не удалось закрыть пересчет.'));
        return;
    }
    showToast('WMS', `Пересчет закрыт, документов: ${res.posted_documents || 0}`);
    await refreshSupplyExtended();
}
async function startWarehouseTerminalX() {
    const res = await apiCall('/terminal/sessions', 'POST', {
        terminal_code: document.getElementById('warehouseTerminalCodeX')?.value.trim() || 'RF-01',
        terminal_type: 'warehouse',
        current_zone: 'WMS',
    });
    if (!res || res.error) return customAlert(explainExtendedOpsError(res?.error || 'Не удалось открыть смену терминала.'));
    showToast('RF-терминал', 'Складская смена открыта');
    await refreshSupplyExtended();
}
async function submitWarehouseTerminalScanX() {
    const actionName = document.getElementById('warehouseTerminalActionX')?.value || 'lookup';
    const payload = {};
    const countedQty = Number(document.getElementById('warehouseTerminalQtyX')?.value || 0);
    if (actionName === 'cycle_count') payload.counted_qty = countedQty;
    const res = await apiCall('/terminal/scan', 'POST', {
        terminal_code: document.getElementById('warehouseTerminalCodeX')?.value.trim() || 'RF-01',
        terminal_type: 'warehouse',
        scan_kind: 'barcode',
        scan_value: document.getElementById('warehouseTerminalScanX')?.value.trim() || '',
        action_name: actionName,
        payload,
    });
    if (!res || res.error || res.status === 'error') return customAlert(explainExtendedOpsError(res?.result?.error || res?.error || 'Не удалось обработать скан.'));
    showToast('RF-терминал', 'Скан обработан');
    await refreshSupplyExtended();
}
async function submitProductionTerminalEventX() {
    const rawOperation = document.getElementById('productionTerminalOperationIdX')?.value.trim() || '';
    const operationId = Number(rawOperation.replace(/^OP-/i, '') || 0);
    const actionName = document.getElementById('productionTerminalActionX')?.value || 'production_start';
    const qty = Number(document.getElementById('productionTerminalQtyX')?.value || 0);
    const actualHours = Number(document.getElementById('productionTerminalHoursX')?.value || 0);
    const res = await apiCall('/terminal/scan', 'POST', {
        terminal_code: document.getElementById('productionTerminalCodeX')?.value.trim() || 'SHOP-01',
        terminal_type: 'production',
        scan_kind: 'barcode',
        scan_value: operationId ? `OP-${operationId}` : rawOperation,
        action_name: actionName,
        payload: { qty, scrap_qty: actionName === 'production_scrap' ? qty : 0, actual_hours: actualHours },
    });
    if (!res || res.error || res.status === 'error') return customAlert(explainExtendedOpsError(res?.result?.error || res?.error || 'Не удалось записать событие цеха.'));
    showToast('Цеховой терминал', 'Событие производства записано');
    await renderProduction();
}
async function saveProcurementRequestX() {
    const qty = Number(document.getElementById('procReqQtyX')?.value || 0);
    const targetPrice = Number(document.getElementById('procReqTargetPriceX')?.value || 0);
    if (!(await saveExtendedOpsRecord('/procurement/requests', {
        project_id: Number(document.getElementById('procReqProjectIdX')?.value || 0),
        title: document.getElementById('procReqTitleX')?.value.trim() || '',
        item_article: document.getElementById('procReqArticleX')?.value.trim() || '',
        item_name: document.getElementById('procReqItemNameX')?.value.trim() || '',
        qty,
        unit: 'шт',
        target_unit_price: targetPrice,
        required_date: document.getElementById('procReqRequiredDateX')?.value.trim() || '',
        priority: document.getElementById('procReqPriorityX')?.value || 'normal',
        status: 'approved',
        comment: 'Заявка из закупочного контура',
    }, 'Заявка на закупку сохранена'))) return;
    await refreshSupplyExtended();
}
async function saveProcurementTenderX() {
    if (!(await saveExtendedOpsRecord('/procurement/tenders', {
        request_id: Number(document.getElementById('procTenderRequestIdX')?.value || 0),
        title: document.getElementById('procTenderTitleX')?.value.trim() || '',
        due_date: document.getElementById('procTenderDueDateX')?.value.trim() || '',
        status: 'collecting_bids',
        criteria: { price_weight: 50, lead_time_weight: 30, reliability_weight: 20 },
        comment: 'RFQ из закупочного контура',
    }, 'Тендер закупки сохранен'))) return;
    await refreshSupplyExtended();
}
async function saveProcurementBidX() {
    const supplierId = Number(document.getElementById('procBidSupplierIdX')?.value || 0);
    const supplier = opsExtendedDB.suppliers.find(item => Number(item.id) === supplierId);
    if (!(await saveExtendedOpsRecord('/procurement/tender_bids', {
        tender_id: Number(document.getElementById('procBidTenderIdX')?.value || 0),
        supplier_id: supplierId,
        supplier_name: supplier?.supplier_name || '',
        price: Number(document.getElementById('procBidPriceX')?.value || 0),
        lead_time_days: Number(document.getElementById('procBidLeadTimeX')?.value || 0),
        score: Number(document.getElementById('procBidScoreX')?.value || 0),
        status: 'submitted',
        comment: 'Предложение поставщика',
    }, 'Ставка поставщика сохранена'))) return;
    await refreshSupplyExtended();
}
async function awardProcurementTenderX(tenderId = 0) {
    const selectedTenderId = Number(tenderId || document.getElementById('procBidTenderIdX')?.value || 0);
    if (!selectedTenderId) {
        await customAlert('Выбери тендер для выбора поставщика.');
        return;
    }
    const res = await apiCall(`/procurement/tenders/${selectedTenderId}/award`, 'POST', {
        bid_id: 0,
        decision_comment: 'Автовыбор лучшей ставки по score/цене/сроку',
        create_purchase: 1,
    });
    if (!res || res.error) {
        await customAlert(explainExtendedOpsError(res?.error || 'Не удалось выбрать поставщика.'));
        return;
    }
    showToast('Снабжение', res.purchase_id ? `Поставщик выбран, заказ #${res.purchase_id} создан` : 'Поставщик выбран');
    await refreshSupplyExtended();
}
async function savePurchaseReceiptX() {
    if (!(await saveExtendedOpsRecord('/procurement/receipts', {
        purchase_id: Number(document.getElementById('procReceiptPurchaseIdX')?.value || 0),
        receipt_date: document.getElementById('procReceiptDateX')?.value.trim() || '',
        accepted_qty: Number(document.getElementById('procReceiptAcceptedQtyX')?.value || 0),
        rejected_qty: Number(document.getElementById('procReceiptRejectedQtyX')?.value || 0),
        warehouse: document.getElementById('procReceiptWarehouseX')?.value.trim() || '',
        quality_status: Number(document.getElementById('procReceiptRejectedQtyX')?.value || 0) > 0 ? 'partial' : 'accepted',
        status: 'posted',
        comment: 'Приемка поставки',
    }, 'Приемка закупки проведена'))) return;
    await refreshSupplyExtended();
}
async function savePurchaseDocumentX() {
    const purchaseId = Number(document.getElementById('procDocPurchaseIdX')?.value || 0);
    const purchase = purchasesDB.find(item => Number(item.id) === purchaseId);
    if (!(await saveExtendedOpsRecord('/procurement/documents', {
        purchase_id: purchaseId,
        doc_type: document.getElementById('procDocTypeX')?.value || 'invoice',
        doc_number: document.getElementById('procDocNumberX')?.value.trim() || '',
        amount: Number(document.getElementById('procDocAmountX')?.value || 0) || Number(purchase?.total_amount || 0),
        vat_amount: 0,
        status: 'accepted',
        comment: 'Документ поставщика',
    }, 'Документ поставщика сохранен'))) return;
    await refreshSupplyExtended();
}

async function deleteSalesQuoteX(id) { if (await deleteExtendedOpsRecord(`/sales/quotes/${id}`, 'КП удалено')) await refreshSalesExtended(); }
async function deleteSalesPlanX(id) { if (await deleteExtendedOpsRecord(`/sales/plans/${id}`, 'План удалён')) await refreshSalesExtended(); }
async function deletePriceListX(id) { if (await deleteExtendedOpsRecord(`/sales/price_lists/${id}`, 'Прайс удалён')) await refreshSalesExtended(); }
async function deleteClientTermsX(id) { if (await deleteExtendedOpsRecord(`/sales/client_terms/${id}`, 'Условия удалены')) await refreshSalesExtended(); }
async function deleteSalesReturnX(id) { if (await deleteExtendedOpsRecord(`/sales/returns/${id}`, 'Возврат удалён')) await refreshSalesExtended(); }
async function deleteSalesCustomerOrderX(id) { if (await deleteExtendedOpsRecord(`/sales/customer_orders/${id}`, 'Заказ клиента удалён')) await refreshSalesExtended(); }
async function deleteSalesShipmentX(id) { if (await deleteExtendedOpsRecord(`/sales/shipments/${id}`, 'Отгрузка удалена')) await refreshSalesExtended(); }
async function deleteSalesPaymentScheduleX(id) { if (await deleteExtendedOpsRecord(`/sales/payment_schedules/${id}`, 'График оплаты удалён')) await refreshSalesExtended(); }
async function deleteSupplierX(id) { if (await deleteExtendedOpsRecord(`/suppliers/${id}`, 'Поставщик удалён')) await refreshSupplyExtended(); }
async function deletePurchasePlanX(id) { if (await deleteExtendedOpsRecord(`/purchase/plans/${id}`, 'План закупки удалён')) await refreshSupplyExtended(); }
async function deleteDeliveryScheduleX(id) { if (await deleteExtendedOpsRecord(`/purchase/delivery_schedules/${id}`, 'График удалён')) await refreshSupplyExtended(); }
async function deleteSupplierReturnX(id) { if (await deleteExtendedOpsRecord(`/purchase/returns/${id}`, 'Возврат удалён')) await refreshSupplyExtended(); }
async function deleteSupplierDiscrepancyX(id) { if (await deleteExtendedOpsRecord(`/purchase/discrepancy_acts/${id}`, 'Акт удалён')) await refreshSupplyExtended(); }
async function deleteInventoryActX(id) { if (await deleteExtendedOpsRecord(`/stock/inventory_acts/${id}`, 'Инвентаризационный акт удалён')) await refreshSupplyExtended(); }
async function deleteRegradingX(id) { if (await deleteExtendedOpsRecord(`/stock/regrading/${id}`, 'Пересортица удалена')) await refreshSupplyExtended(); }
async function deleteQualityReportX(id) { if (await deleteExtendedOpsRecord(`/stock/quality_reports/${id}`, 'Отчёт качества удалён')) await refreshSupplyExtended(); }
async function deleteWmsCellX(id) { if (await deleteExtendedOpsRecord(`/wms/cells/${id}`, 'WMS-ячейка удалена')) await refreshSupplyExtended(); }
async function deleteWmsPutawayTaskX(id) { if (await deleteExtendedOpsRecord(`/wms/putaway_tasks/${id}`, 'Задание размещения удалено')) await refreshSupplyExtended(); }
async function deleteWmsPickWaveX(id) { if (await deleteExtendedOpsRecord(`/wms/pick_waves/${id}`, 'Волна подбора удалена')) await refreshSupplyExtended(); }
async function deleteWmsPickTaskX(id) { if (await deleteExtendedOpsRecord(`/wms/pick_tasks/${id}`, 'Задание подбора удалено')) await refreshSupplyExtended(); }
async function deleteWmsCycleCountX(id) { if (await deleteExtendedOpsRecord(`/wms/cycle_counts/${id}`, 'Пересчет WMS удален')) await refreshSupplyExtended(); }
async function deleteProcurementRequestX(id) { if (await deleteExtendedOpsRecord(`/procurement/requests/${id}`, 'Заявка удалена')) await refreshSupplyExtended(); }
async function deleteProcurementTenderX(id) { if (await deleteExtendedOpsRecord(`/procurement/tenders/${id}`, 'Тендер удален')) await refreshSupplyExtended(); }
async function deleteProcurementBidX(id) { if (await deleteExtendedOpsRecord(`/procurement/tender_bids/${id}`, 'Ставка удалена')) await refreshSupplyExtended(); }
async function deletePurchaseReceiptX(id) { if (await deleteExtendedOpsRecord(`/procurement/receipts/${id}`, 'Приемка удалена')) await refreshSupplyExtended(); }
async function deletePurchaseDocumentX(id) { if (await deleteExtendedOpsRecord(`/procurement/documents/${id}`, 'Документ удален')) await refreshSupplyExtended(); }

window.saveSalesQuoteX = saveSalesQuoteX;
window.saveSalesPlanX = saveSalesPlanX;
window.savePriceListX = savePriceListX;
window.saveClientTermsX = saveClientTermsX;
window.saveSalesReturnX = saveSalesReturnX;
window.saveSalesCustomerOrderX = saveSalesCustomerOrderX;
window.reserveSalesCustomerOrderX = reserveSalesCustomerOrderX;
window.createSalesDocumentFromOrderX = createSalesDocumentFromOrderX;
window.saveSalesShipmentX = saveSalesShipmentX;
window.shipSalesShipmentX = shipSalesShipmentX;
window.saveSalesPaymentScheduleX = saveSalesPaymentScheduleX;
window.markSalesPaymentSchedulePaidX = markSalesPaymentSchedulePaidX;
window.recalculateSalesDealMarginX = recalculateSalesDealMarginX;
window.prefillSalesFromQuoteX = prefillSalesFromQuoteX;
window.saveSupplierX = saveSupplierX;
window.savePurchasePlanX = savePurchasePlanX;
window.saveDeliveryScheduleX = saveDeliveryScheduleX;
window.saveSupplierReturnX = saveSupplierReturnX;
window.saveSupplierDiscrepancyX = saveSupplierDiscrepancyX;
window.saveInventoryActX = saveInventoryActX;
window.saveRegradingX = saveRegradingX;
window.saveQualityReportX = saveQualityReportX;
window.saveStockPolicyX = saveStockPolicyX;
window.saveWmsCellX = saveWmsCellX;
window.saveWmsPutawayTaskX = saveWmsPutawayTaskX;
window.completeWmsPutawayTaskX = completeWmsPutawayTaskX;
window.saveWmsPickWaveX = saveWmsPickWaveX;
window.releaseWmsPickWaveX = releaseWmsPickWaveX;
window.pickWmsTaskX = pickWmsTaskX;
window.saveWmsCycleCountX = saveWmsCycleCountX;
window.closeWmsCycleCountX = closeWmsCycleCountX;
window.startWarehouseTerminalX = startWarehouseTerminalX;
window.submitWarehouseTerminalScanX = submitWarehouseTerminalScanX;
window.submitProductionTerminalEventX = submitProductionTerminalEventX;
window.saveProcurementRequestX = saveProcurementRequestX;
window.saveProcurementTenderX = saveProcurementTenderX;
window.saveProcurementBidX = saveProcurementBidX;
window.awardProcurementTenderX = awardProcurementTenderX;
window.savePurchaseReceiptX = savePurchaseReceiptX;
window.savePurchaseDocumentX = savePurchaseDocumentX;
window.deleteSalesQuoteX = deleteSalesQuoteX;
window.deleteSalesPlanX = deleteSalesPlanX;
window.deletePriceListX = deletePriceListX;
window.deleteClientTermsX = deleteClientTermsX;
window.deleteSalesReturnX = deleteSalesReturnX;
window.deleteSalesCustomerOrderX = deleteSalesCustomerOrderX;
window.deleteSalesShipmentX = deleteSalesShipmentX;
window.deleteSalesPaymentScheduleX = deleteSalesPaymentScheduleX;
window.deleteSupplierX = deleteSupplierX;
window.deletePurchasePlanX = deletePurchasePlanX;
window.deleteDeliveryScheduleX = deleteDeliveryScheduleX;
window.deleteSupplierReturnX = deleteSupplierReturnX;
window.deleteSupplierDiscrepancyX = deleteSupplierDiscrepancyX;
window.deleteInventoryActX = deleteInventoryActX;
window.deleteRegradingX = deleteRegradingX;
window.deleteQualityReportX = deleteQualityReportX;
window.deleteWmsCellX = deleteWmsCellX;
window.deleteWmsPutawayTaskX = deleteWmsPutawayTaskX;
window.deleteWmsPickWaveX = deleteWmsPickWaveX;
window.deleteWmsPickTaskX = deleteWmsPickTaskX;
window.deleteWmsCycleCountX = deleteWmsCycleCountX;
window.deleteProcurementRequestX = deleteProcurementRequestX;
window.deleteProcurementTenderX = deleteProcurementTenderX;
window.deleteProcurementBidX = deleteProcurementBidX;
window.deletePurchaseReceiptX = deletePurchaseReceiptX;
window.deletePurchaseDocumentX = deletePurchaseDocumentX;

window.savePurchase = savePurchase;
window.saveReservation = saveReservation;
window.resetPurchaseForm = resetPurchaseForm;
window.editPurchase = editPurchase;
window.duplicatePurchase = duplicatePurchase;
window.deletePurchase = deletePurchase;
window.fulfillReservation = fulfillReservation;
window.renderSupply = renderSupply;
