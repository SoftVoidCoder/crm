// ==========================================
// ЯДРО НСИ И СКЛАДА (Номенклатура и Контакты)
// ==========================================

let nomenclatureDB = [];
let contactsDB = [];
let selectedProjectNomenclature = [];
let stockMovementsDB = [];
let stockBalancesDB = [];
let stockLotsDB = [];
let nsiMasterDataDB = { warehouses: [], units: [], groups: [], positions: [], characteristics: [], storage_cells: [], income_expense_articles: [], financial_responsibility_centers: [], operation_types: [], employees: [], bank_accounts: [], legal_entities: [], business_units: [], defaults: {} };
let inventoryDocumentsDB = [];
let stockDiscrepancyActsDB = [];
let nsiReconciliationRunsDB = [];
let nsiMasterEditState = { type: '', id: 0 };
let stockExtendedSummaryDB = { metrics: {}, acts: [], quality: [], regrading: [], journal: [], discrepancy_reasons: [], quality_statuses: [], cost_alerts: [] };
let stockJournalDB = [];
let stockInventoryActsDB = [];
let stockQualityReportsDB = [];
let stockRegradingDB = [];

// Загрузка справочников из БД
async function loadNSI() {
    nomenclatureDB = await apiCall('/nomenclature') || [];
    contactsDB = await apiCall('/contacts') || [];
    stockMovementsDB = await apiCall('/stock/movements') || [];
    stockBalancesDB = await apiCall('/stock/balances') || [];
    stockLotsDB = await apiCall('/stock/lots') || [];
    nsiMasterDataDB = await apiCall('/nsi/master_data') || { warehouses: [], units: [], groups: [] };
    inventoryDocumentsDB = await apiCall('/stock/documents') || [];
    stockDiscrepancyActsDB = await apiCall('/stock/discrepancy_acts') || [];
    stockExtendedSummaryDB = await apiCall('/stock/extended_summary') || { metrics: {} };
    stockJournalDB = await apiCall('/stock/journal?limit=120') || [];
    stockInventoryActsDB = await apiCall('/stock/inventory_acts') || [];
    stockQualityReportsDB = await apiCall('/stock/quality_reports') || [];
    stockRegradingDB = await apiCall('/stock/regrading') || [];
    const reconciliationRuns = await apiCall('/integration/1c/reconciliation?limit=10');
    nsiReconciliationRunsDB = Array.isArray(reconciliationRuns) ? reconciliationRuns : [];
}

// Запускаем загрузку данных с задержкой
setTimeout(async () => { 
    if (currentUser && currentUser.status === 'approved') {
        await loadNSI();
        if(document.getElementById('nomenclatureView')?.style.display === 'block') renderNomenclature();
        if(document.getElementById('contactsView')?.style.display === 'block') renderContacts();
    }
}, 1500);

// --- СКЛАД: ДОБАВЛЕНИЕ НОВОЙ ПОЗИЦИИ ---
async function addNomenclature() {
    const name = document.getElementById('addNomName').value.trim();
    const article = document.getElementById('addNomArticle').value.trim();
    const unit = document.getElementById('addNomUnit').value.trim();
    const group_name = document.getElementById('addNomGroup')?.value || '';
    const default_warehouse = document.getElementById('addNomWarehouse')?.value || '';
    const price = parseFloat(document.getElementById('addNomPrice').value) || 0;
    const currency = document.getElementById('addNomCurrency') ? document.getElementById('addNomCurrency').value : 'RUB';

    if (!name) return customAlert("Введите наименование продукции!");

    await apiCall('/nomenclature', 'POST', { name, article, unit, price, stock: 0, currency, group_name, default_warehouse });
    document.getElementById('addNomName').value = '';
    document.getElementById('addNomArticle').value = '';
    document.getElementById('addNomPrice').value = '0';
    
    await loadNSI();
    renderNomenclature();
    showToast("Склад", "Новая позиция добавлена в номенклатуру");
}

async function importNomenclatureFile() {
    const fileInput = document.getElementById('nomenclatureImportFile');
    const file = fileInput?.files?.[0];
    if (!file) return customAlert('Выберите CSV или JSON файл с номенклатурой.');
    const formData = new FormData();
    formData.append('upload', file);
    const res = await apiCall('/nomenclature/import', 'POST', formData);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось импортировать номенклатуру.');
    if (fileInput) fileInput.value = '';
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', `Импорт завершён: +${res.created || 0}, обновлено ${res.updated || 0}`);
}

async function mergeNomenclaturePrompt() {
    const masterArticle = await customPrompt('Артикул master-позиции', '');
    if (!masterArticle) return;
    const duplicatesRaw = await customPrompt('Артикулы дублей через запятую', '');
    if (!duplicatesRaw) return;
    const duplicateArticles = duplicatesRaw.split(',').map(item => item.trim()).filter(Boolean);
    if (!duplicateArticles.length) return customAlert('Нужен хотя бы один артикул дубля.');
    const res = await apiCall('/nomenclature/merge', 'POST', { master_article: masterArticle.trim(), duplicate_articles: duplicateArticles });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось объединить номенклатуру.');
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', `Объединено позиций: ${res.merged || 0}`);
}

async function saveNSIMasterRecord() {
    const entityType = document.getElementById('nsiMasterEntityType')?.value;
    const name = document.getElementById('nsiMasterName')?.value.trim();
    const code = document.getElementById('nsiMasterCode')?.value.trim();
    if (!entityType || !name) return customAlert('Укажи тип справочника и наименование.');
    const res = await apiCall(`/nsi/master_data/${encodeURIComponent(entityType)}`, 'POST', { name, code, is_active: 1, comment: '' });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить запись справочника.');
    document.getElementById('nsiMasterName').value = '';
    document.getElementById('nsiMasterCode').value = '';
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', 'Запись справочника добавлена');
}

async function archiveNSIMasterRecord(entityType, id) {
    if (!(await customConfirm('Архивировать запись справочника?'))) return;
    const res = await apiCall(`/nsi/master_data/${encodeURIComponent(entityType)}/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось архивировать запись.');
    await loadNSI();
    renderNomenclature();
}

async function editNSIMasterRecord(entityType, id) {
    const collection = nsiMasterDataDB[entityType] || [];
    const item = collection.find(row => Number(row.id) === Number(id));
    if (!item) return customAlert('Запись справочника не найдена.');
    const name = await customPrompt('Наименование записи', item.name || '');
    if (name === null) return;
    const code = await customPrompt('Код записи', item.code || '');
    if (code === null) return;
    const comment = await customPrompt('Комментарий', item.comment || '');
    if (comment === null) return;
    const res = await apiCall(`/nsi/master_data/${encodeURIComponent(entityType)}/${id}`, 'PUT', {
        name: String(name || '').trim(),
        code: String(code || '').trim(),
        comment: String(comment || '').trim(),
        is_active: Number(item.is_active || 0) === 1 ? 1 : 0,
    });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось обновить запись справочника.');
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', 'Запись справочника обновлена');
}

async function createInventoryDocument() {
    const doc_type = document.getElementById('inventoryDocType')?.value || 'inventory';
    const article = document.getElementById('inventoryDocArticle')?.value.trim();
    const qty = parseFloat(document.getElementById('inventoryDocQty')?.value || '0') || 0;
    const counted_qty = parseFloat(document.getElementById('inventoryDocCountedQty')?.value || '0') || 0;
    const warehouse = document.getElementById('inventoryDocWarehouse')?.value.trim() || '';
    const bin_code = document.getElementById('inventoryDocBin')?.value.trim() || '';
    const target_warehouse = document.getElementById('inventoryDocTargetWarehouse')?.value.trim() || '';
    const target_bin = document.getElementById('inventoryDocTargetBin')?.value.trim() || '';
    const reason = document.getElementById('inventoryDocReason')?.value.trim() || '';
    if (!article) return customAlert('Укажи артикул номенклатуры.');
    const res = await apiCall('/stock/documents', 'POST', {
        doc_type, article, qty, counted_qty, warehouse, bin_code, target_warehouse, target_bin, reason, comment: reason
    });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось провести складской документ.');
    ['inventoryDocArticle', 'inventoryDocReason'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('inventoryDocQty').value = '0';
    document.getElementById('inventoryDocCountedQty').value = '0';
    await loadNSI();
    renderNomenclature();
    showToast('Склад', `Документ ${res.doc_number || ''} проведён`);
}

async function createInventoryAct() {
    const article = document.getElementById('inventoryActArticle')?.value.trim() || '';
    const nom = nomenclatureDB.find(item => item.article === article);
    const payload = {
        article,
        item_name: document.getElementById('inventoryActName')?.value.trim() || nom?.name || '',
        expected_qty: parseFloat(document.getElementById('inventoryActExpectedQty')?.value || '0') || 0,
        counted_qty: parseFloat(document.getElementById('inventoryActCountedQty')?.value || '0') || 0,
        warehouse: document.getElementById('inventoryActWarehouse')?.value.trim() || '',
        bin_code: document.getElementById('inventoryActBin')?.value.trim() || '',
        comment: document.getElementById('inventoryActComment')?.value.trim() || '',
    };
    if (!payload.article) return customAlert('Укажи артикул для инвентаризационного акта.');
    const res = await apiCall('/stock/inventory_acts', 'POST', payload);
    if (!res || res.error) return customAlert(resolveWarehouseError(res?.error) || 'Не удалось создать инвентаризационный акт.');
    ['inventoryActArticle', 'inventoryActName', 'inventoryActComment'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    ['inventoryActExpectedQty', 'inventoryActCountedQty'].forEach(id => { const el = document.getElementById(id); if (el) el.value = '0'; });
    await loadNSI();
    renderNomenclature();
    showToast('Склад', 'Инвентаризационный акт создан');
}

async function createWarehouseQualityReport() {
    const article = document.getElementById('warehouseQualityArticle')?.value.trim() || '';
    const nom = nomenclatureDB.find(item => item.article === article);
    const payload = {
        article,
        item_name: document.getElementById('warehouseQualityName')?.value.trim() || nom?.name || '',
        qty: parseFloat(document.getElementById('warehouseQualityQty')?.value || '0') || 0,
        warehouse: document.getElementById('warehouseQualityWarehouse')?.value.trim() || '',
        bin_code: document.getElementById('warehouseQualityBin')?.value.trim() || '',
        quality_status: document.getElementById('warehouseQualityStatus')?.value || 'hold',
        decision: document.getElementById('warehouseQualityDecision')?.value || 'inspect',
        defect_kind: document.getElementById('warehouseQualityDefect')?.value.trim() || '',
        status: 'open',
        comment: document.getElementById('warehouseQualityDefect')?.value.trim() || '',
    };
    if (!payload.article) return customAlert('Укажи артикул для кейса качества.');
    const res = await apiCall('/stock/quality_reports', 'POST', payload);
    if (!res || res.error) return customAlert(resolveWarehouseError(res?.error) || 'Не удалось создать кейс качества.');
    ['warehouseQualityArticle', 'warehouseQualityName', 'warehouseQualityDefect'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const qtyEl = document.getElementById('warehouseQualityQty');
    if (qtyEl) qtyEl.value = '0';
    await loadNSI();
    renderNomenclature();
    showToast('Склад', 'Кейс качества зарегистрирован');
}

async function createRegradingDocument() {
    const fromArticle = document.getElementById('regradingFromArticle')?.value.trim() || '';
    const toArticle = document.getElementById('regradingToArticle')?.value.trim() || '';
    const fromNom = nomenclatureDB.find(item => item.article === fromArticle);
    const toNom = nomenclatureDB.find(item => item.article === toArticle);
    const payload = {
        from_article: fromArticle,
        to_article: toArticle,
        from_name: fromNom?.name || '',
        to_name: toNom?.name || '',
        qty: parseFloat(document.getElementById('regradingQty')?.value || '0') || 0,
        warehouse: document.getElementById('regradingWarehouse')?.value.trim() || '',
        bin_code: document.getElementById('regradingBin')?.value.trim() || '',
        reason: document.getElementById('regradingReason')?.value.trim() || '',
        comment: document.getElementById('regradingReason')?.value.trim() || '',
        status: 'posted',
    };
    if (!payload.from_article || !payload.to_article) return customAlert('Укажи исходный и целевой артикул для пересортицы.');
    const res = await apiCall('/stock/regrading', 'POST', payload);
    if (!res || res.error) return customAlert(resolveWarehouseError(res?.error) || 'Не удалось провести пересортицу.');
    ['regradingFromArticle', 'regradingToArticle', 'regradingReason'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const qtyEl = document.getElementById('regradingQty');
    if (qtyEl) qtyEl.value = '0';
    await loadNSI();
    renderNomenclature();
    showToast('Склад', 'Пересортица проведена');
}

function renderNSIMasterSelects() {
    const units = nsiMasterDataDB.units || [];
    const groups = nsiMasterDataDB.groups || [];
    const warehouses = nsiMasterDataDB.warehouses || [];
    const fill = (id, items, placeholder, fallback = '') => {
        const el = document.getElementById(id);
        if (!el) return;
        const current = el.value;
        el.innerHTML = [`<option value="">${placeholder}</option>`]
            .concat(items.filter(item => Number(item.is_active || 0) === 1).map(item => `<option value="${item.name}">${item.name}</option>`))
            .join('');
        if (current && Array.from(el.options).some(opt => opt.value === current)) {
            el.value = current;
        } else if (fallback && Array.from(el.options).some(opt => opt.value === fallback)) {
            el.value = fallback;
        }
    };
    fill('addNomUnit', units, 'Выбери ед. изм.', 'шт');
    fill('addNomGroup', groups, 'Без группы');
    fill('addNomWarehouse', warehouses, 'Без склада', 'Основной склад');
}

function renderNSIMasterLists() {
    const container = document.getElementById('nsiMasterDataLists');
    if (!container) return;
    const sections = [
        ['warehouses', 'Склады'],
        ['units', 'Единицы измерения'],
        ['groups', 'Группы номенклатуры'],
    ];
    container.innerHTML = sections.map(([key, title]) => `
        <div class="client360-item client360-item--stack">
            <div class="client360-item-title">${title}</div>
            <div class="client360-list" style="margin-top:12px;">
                ${(nsiMasterDataDB[key] || []).length ? (nsiMasterDataDB[key] || []).map(item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.name}</div>
                            <div class="client360-item-meta">${item.code || 'Без кода'}${Number(item.is_active || 0) === 1 ? '' : ' · в архиве'}</div>
                        </div>
                        <div class="client360-item-side">
                            <button class="btn-secondary" style="padding:4px 10px;" onclick="editNSIMasterRecord('${key}', ${item.id})">Изменить</button>
                            ${Number(item.is_active || 0) === 1 ? `<button class="btn-secondary" style="padding:4px 10px;" onclick="archiveNSIMasterRecord('${key}', ${item.id})">Архив</button>` : ''}
                        </div>
                    </div>
                `).join('') : '<div class="empty-state">Пока пусто.</div>'}
            </div>
        </div>
    `).join('');
}

function renderInventoryDocuments() {
    const container = document.getElementById('inventoryDocumentsList');
    if (!container) return;
    container.innerHTML = inventoryDocumentsDB.length ? inventoryDocumentsDB.slice(0, 14).map(doc => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${doc.doc_number} · ${doc.nomenclature_name || doc.article}</div>
                <div class="client360-item-meta">${doc.doc_type} · ${doc.warehouse || '—'}${doc.bin_code ? ` / ${doc.bin_code}` : ''}${doc.target_warehouse ? ` → ${doc.target_warehouse}${doc.target_bin ? ` / ${doc.target_bin}` : ''}` : ''}</div>
                <div class="client360-item-meta">Кол-во: ${Number(doc.qty || 0).toLocaleString('ru-RU')} ${doc.unit || 'шт'} · Корректировка: ${Number(doc.adjustment_qty || 0).toLocaleString('ru-RU')}</div>
            </div>
            <div class="client360-item-side">
                <div>${new Date((doc.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
                <button class="btn-secondary" style="margin-top:8px; padding:4px 8px; font-size:11px; min-height:unset;" onclick="openEntityCard('inventory_document', ${doc.id})">Карточка</button>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Складские документы ещё не проводились.</div>';
}

function prefillInventoryAdjustmentFromDiscrepancy(docId) {
    const item = stockDiscrepancyActsDB.find(row => Number(row.id) === Number(docId));
    if (!item) return customAlert('Акт расхождения не найден.');
    const adjustment = Number(item.adjustment_qty || 0);
    const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    };
    setValue('inventoryDocType', adjustment >= 0 ? 'receipt_adjustment' : 'writeoff');
    setValue('inventoryDocArticle', item.article || '');
    setValue('inventoryDocQty', Math.abs(adjustment || Number(item.counted_qty || 0) || Number(item.qty || 0)));
    setValue('inventoryDocCountedQty', Number(item.counted_qty || 0));
    setValue('inventoryDocWarehouse', item.warehouse || 'Основной склад');
    setValue('inventoryDocBin', item.bin_code || 'A-01');
    setValue('inventoryDocTargetWarehouse', item.target_warehouse || '');
    setValue('inventoryDocTargetBin', item.target_bin || '');
    setValue('inventoryDocReason', `Корректировка по ${item.doc_number || 'акту'}: ${item.reason || 'расхождение остатков'}`);
    showToast('Склад', 'Форма корректировки заполнена по акту расхождения');
}

function renderDiscrepancyActs() {
    const container = document.getElementById('inventoryDiscrepancyActsList');
    if (!container) return;
    container.innerHTML = stockDiscrepancyActsDB.length ? stockDiscrepancyActsDB.slice(0, 16).map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.doc_number || 'Акт'} · ${item.nomenclature_name || item.article || 'Номенклатура'}</div>
                <div class="client360-item-meta">${item.warehouse || 'Склад'}${item.bin_code ? ` / ${item.bin_code}` : ''} · ${item.reason || 'Расхождение остатков'}</div>
                <div class="client360-item-meta">Учёт: ${Number(item.qty || 0).toLocaleString('ru-RU')} · подсчёт: ${Number(item.counted_qty || 0).toLocaleString('ru-RU')} · корректировка: ${Number(item.adjustment_qty || 0).toLocaleString('ru-RU')} ${item.unit || 'шт'}</div>
            </div>
            <div class="view-actions">
                <button class="btn-secondary" onclick="prefillInventoryAdjustmentFromDiscrepancy(${item.id})">Внести корректировку</button>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Актов расхождений пока нет.</div>';
}

function resolveWarehouseError(errorCode) {
    const map = {
        insufficient_stock: 'Недостаточно остатка на складе для этой операции.',
        article_required: 'Укажи артикул номенклатуры.',
        qty_required: 'Укажи количество больше нуля.',
        invalid_type: 'Тип складской операции не поддерживается.',
        bulk_action_invalid: 'Выбери корректные записи и тип bulk-действия.',
        bulk_action_not_supported: 'Это bulk-действие пока не поддерживается для выбранного типа.',
        forbidden: 'Недостаточно прав для складской операции.',
    };
    return map[errorCode] || errorCode || 'Не удалось выполнить складскую операцию.';
}

function stockSeverityBadgeClass(level) {
    if (level === 'warning') return 'status-waiting';
    if (level === 'success') return 'status-completed';
    if (level === 'attention') return 'status-review';
    return 'status-neutral';
}

function renderStockCockpit() {
    const mount = document.getElementById('stockCockpitMount');
    if (!mount) return;
    const summary = stockExtendedSummaryDB || { metrics: {} };
    const metrics = summary.metrics || {};
    const reasonRows = summary.discrepancy_reasons || [];
    const qualityRows = summary.quality_statuses || [];
    const costAlerts = summary.cost_alerts || [];
    mount.innerHTML = `
        <div class="nsi-stock-cockpit">
            <div class="metrics-grid" style="margin-bottom:16px;">
                <div class="metric-card"><div class="metric-title">Журнал склада</div><div class="metric-value">${metrics.journal_entries || 0}</div><div class="client360-item-meta">Всех событий</div></div>
                <div class="metric-card ${metrics.negative_balance_positions ? 'warning' : ''}"><div class="metric-title">Отрицательные остатки</div><div class="metric-value">${metrics.negative_balance_positions || 0}</div><div class="client360-item-meta">${metrics.strict_negative_control ? 'жёсткий контроль включён' : 'разрешены политикой'}</div></div>
                <div class="metric-card ${metrics.discrepancy_cases ? 'warning' : ''}"><div class="metric-title">Расхождения</div><div class="metric-value">${metrics.discrepancy_cases || 0}</div><div class="client360-item-meta">Акты и корректировки</div></div>
                <div class="metric-card ${metrics.quality_holds ? 'warning' : ''}"><div class="metric-title">Удержание качества</div><div class="metric-value">${metrics.quality_holds || 0}</div><div class="client360-item-meta">Открытые кейсы качества</div></div>
                <div class="metric-card ${metrics.zero_cost_positions ? 'warning' : ''}"><div class="metric-title">Без себестоимости</div><div class="metric-value">${metrics.zero_cost_positions || 0}</div><div class="client360-item-meta">Позиции с остатком и нулевой ценой</div></div>
            </div>
            <div class="ops-grid-two">
                <div class="client360-item client360-item--stack">
                    <div class="client360-item-title">Причины расхождений</div>
                    <div class="client360-list" style="margin-top:12px;">
                        ${reasonRows.length ? reasonRows.slice(0, 5).map(item => `
                            <div class="client360-item">
                                <div><div class="client360-item-title">${item.reason}</div><div class="client360-item-meta">Кейсов: ${item.count}</div></div>
                                <div class="client360-item-side">${Number(item.qty || 0).toLocaleString('ru-RU')}</div>
                            </div>
                        `).join('') : '<div class="empty-state">Причины расхождений пока не накопились.</div>'}
                    </div>
                </div>
                <div class="client360-item client360-item--stack">
                    <div class="client360-item-title">Качество и себестоимость</div>
                    <div class="client360-list" style="margin-top:12px;">
                        ${qualityRows.length ? qualityRows.slice(0, 4).map(item => `
                            <div class="client360-item">
                                <div><div class="client360-item-title">${item.status}</div><div class="client360-item-meta">Кейсов: ${item.count}</div></div>
                                <div class="client360-item-side">${Number(item.qty || 0).toLocaleString('ru-RU')}</div>
                            </div>
                        `).join('') : '<div class="empty-state">Кейсов качества пока нет.</div>'}
                        ${costAlerts.map(item => `
                            <div class="client360-item">
                                <div><div class="client360-item-title">${item.title}</div><div class="client360-item-meta">${item.state === 'warning' ? 'Требует контроля' : 'ОК'}</div></div>
                                <div class="client360-item-side">${item.value}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderInventoryActs() {
    const container = document.getElementById('inventoryActsList');
    if (!container) return;
    container.innerHTML = stockInventoryActsDB.length ? stockInventoryActsDB.slice(0, 12).map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.item_name || item.article || 'Инвентаризация'} · акт #${item.id}</div>
                <div class="client360-item-meta">${item.warehouse || 'Склад'}${item.bin_code ? ` / ${item.bin_code}` : ''}</div>
                <div class="client360-item-meta">Учёт: ${Number(item.expected_qty || 0).toLocaleString('ru-RU')} · факт: ${Number(item.counted_qty || 0).toLocaleString('ru-RU')} · корректировка: ${Number(item.adjustment_qty || 0).toLocaleString('ru-RU')}</div>
            </div>
            <div class="view-actions">
                <button class="btn-secondary" onclick="printStockEntity('inventory_act', ${item.id})">Печать</button>
                <button class="btn-secondary" onclick="deleteStockEntity('inventory_act', ${item.id})">Удалить</button>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Инвентаризационных актов пока нет.</div>';
}

function renderStockQuality() {
    const container = document.getElementById('stockQualityList');
    if (!container) return;
    container.innerHTML = stockQualityReportsDB.length ? stockQualityReportsDB.slice(0, 10).map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.item_name || item.article || 'Качество'} · #${item.id}</div>
                <div class="client360-item-meta">${item.warehouse || 'Склад'}${item.bin_code ? ` / ${item.bin_code}` : ''} · ${formatWarehouseQualityLabel(item.quality_status || 'hold')} · ${formatWarehouseQualityLabel(item.decision || 'inspect')}</div>
                <div class="client360-item-meta">${item.defect_kind || 'Причина не указана'}</div>
            </div>
            <div class="view-actions">
                <button class="btn-secondary" onclick="printStockEntity('quality_report', ${item.id})">Печать</button>
                <button class="btn-secondary" onclick="bulkStockActionDirect('quality_report', 'close', [${item.id}])">Закрыть</button>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Открытых кейсов качества пока нет.</div>';
}

function renderStockRegrading() {
    const container = document.getElementById('stockRegradingList');
    if (!container) return;
    container.innerHTML = stockRegradingDB.length ? stockRegradingDB.slice(0, 10).map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">Пересортица #${item.id}</div>
                <div class="client360-item-meta">${item.warehouse || 'Склад'}${item.bin_code ? ` / ${item.bin_code}` : ''}</div>
                <div class="client360-item-meta">${item.from_article || '—'} → ${item.to_article || '—'} · ${Number(item.qty || 0).toLocaleString('ru-RU')}</div>
            </div>
            <div class="view-actions">
                <button class="btn-secondary" onclick="printStockEntity('regrading_doc', ${item.id})">Печать</button>
                <button class="btn-secondary" onclick="deleteStockEntity('regrading_doc', ${item.id})">Удалить</button>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Документов пересортицы пока нет.</div>';
}

function getFilteredStockJournalRows() {
    const filterValue = document.getElementById('stockJournalEntityType')?.value || '';
    return filterValue ? stockJournalDB.filter(item => item.entity_type === filterValue) : stockJournalDB.slice();
}

function renderStockJournal() {
    const container = document.getElementById('stockJournalList');
    if (!container) return;
    const rows = getFilteredStockJournalRows();
    container.innerHTML = rows.length ? rows.slice(0, 40).map(item => `
        <div class="client360-item stock-journal-row">
            <div style="display:flex; gap:10px; align-items:flex-start;">
                <input type="checkbox" class="stock-journal-check" data-entity-type="${item.entity_type}" value="${item.entity_id}">
                <div>
                    <div class="client360-item-title">${item.title}</div>
                    <div class="client360-item-meta">${item.subtitle || ''}</div>
                    <div class="client360-item-meta">${item.warehouse || '—'}${item.bin_code ? ` / ${item.bin_code}` : ''} · ${item.reason || 'Без причины'}</div>
                </div>
            </div>
            <div class="client360-item-side">
                <span class="status-badge ${stockSeverityBadgeClass(item.severity)}">${formatStockJournalStatus(item.status || item.journal_type)}</span>
                <div class="client360-item-meta" style="margin-top:6px;">${Number(item.qty || 0).toLocaleString('ru-RU')}</div>
            </div>
        </div>
    `).join('') : '<div class="empty-state">В журнале склада пока нет записей по выбранному фильтру.</div>';
}

async function printStockEntity(entityType, id) {
    const routeMap = {
        inventory_document: `/stock/documents/${id}/print`,
        inventory_act: `/stock/inventory_acts/${id}/print`,
        quality_report: `/stock/quality_reports/${id}/print`,
        regrading_doc: `/stock/regrading/${id}/print`,
        discrepancy_act: `/stock/discrepancy_acts/${id}/print`,
    };
    const route = routeMap[entityType];
    if (!route) return customAlert('Для этого типа печатная форма пока не поддерживается.');
    const res = await apiCall(route);
    if (!res || res.error) return customAlert(resolveWarehouseError(res?.error) || 'Не удалось подготовить печатную форму.');
    return customAlert([res.title || 'Печатная форма'].concat(res.lines || []).join('\n'));
}

async function deleteStockEntity(entityType, id) {
    if (!(await customConfirm('Удалить выбранную складскую запись?'))) return;
    return bulkStockActionDirect(entityType, 'delete', [id]);
}

async function bulkStockActionDirect(entityType, action, ids) {
    const res = await apiCall('/stock/bulk_action', 'POST', { entity_type: entityType, action, ids });
    if (!res || res.error) return customAlert(resolveWarehouseError(res?.error) || 'Не удалось выполнить групповое действие.');
    if (action === 'print') {
        return customAlert((res.documents || []).map(item => [item.title].concat(item.lines || []).join('\n')).join('\n\n'));
    }
    await loadNSI();
    renderNomenclature();
    showToast('Склад', `Обработано записей: ${res.count || 0}`);
}

async function applyStockBulkAction(action) {
    const checked = Array.from(document.querySelectorAll('.stock-journal-check:checked'));
    if (!checked.length) return customAlert('Отметь записи в едином журнале склада.');
    const entityTypes = [...new Set(checked.map(node => node.dataset.entityType || ''))];
    if (entityTypes.length !== 1) return customAlert('Для bulk-действия выбери записи только одного типа.');
    return bulkStockActionDirect(entityTypes[0], action, checked.map(node => Number(node.value || 0)).filter(Boolean));
}

window.switchNSIWorkspaceTab = function(tab = 'items') {
    const view = document.getElementById('nomenclatureView');
    if (!view) return;
    const allowed = new Set(['items', 'directories', 'documents', 'journal']);
    const activeTab = allowed.has(tab) ? tab : 'items';
    window.nsiActiveWorkspaceTab = activeTab;
    view.querySelectorAll('[data-nsi-tab-button]').forEach(button => {
        const isActive = button.dataset.nsiTabButton === activeTab;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    view.querySelectorAll('[data-nsi-panel]').forEach(panel => {
        panel.classList.toggle('is-active', panel.dataset.nsiPanel === activeTab);
    });
    view.querySelectorAll('[data-nsi-panel-group]').forEach(group => {
        group.classList.toggle('is-active', !!group.querySelector('[data-nsi-panel].is-active'));
    });
};

function syncNSIWorkspaceTab() {
    window.switchNSIWorkspaceTab(window.nsiActiveWorkspaceTab || 'items');
}

function renderNSIIntegrityBrief() {
    const mount = document.getElementById('nsiIntegrityBriefMount');
    if (!mount) return;
    const rows = Array.isArray(nomenclatureDB) ? nomenclatureDB : [];
    const balances = Array.isArray(stockBalancesDB) ? stockBalancesDB : [];
    const movements = Array.isArray(stockMovementsDB) ? stockMovementsDB : [];
    const lots = Array.isArray(stockLotsDB) ? stockLotsDB : [];
    const noArticle = rows.filter(item => !String(item.article || '').trim()).length;
    const noGroup = rows.filter(item => !String(item.group_name || '').trim()).length;
    const noWarehouse = rows.filter(item => !String(item.default_warehouse || '').trim()).length;
    const zeroStock = rows.filter(item => Number(item.stock || 0) <= 0).length;
    const issueCount = noArticle + noGroup + noWarehouse;
    const flowState = [
        `${balances.length} остатков`,
        `${lots.length} партий/ячеек`,
        `${movements.length} движений`,
    ].join(' · ');
    mount.innerHTML = `
        <div class="nsi-integrity-card ${issueCount ? 'nsi-integrity-card--warn' : ''}">
            <div>
                <div class="nsi-integrity-title">${issueCount ? 'Есть что привести в порядок' : 'НСИ связана со складом корректно'}</div>
                <div class="nsi-integrity-text">Проверка карточек, складов, ячеек, остатков и движений: ${flowState}.</div>
            </div>
            <div class="nsi-integrity-pills">
                <span class="nsi-status-pill ${noArticle ? 'nsi-status-pill--warn' : 'nsi-status-pill--ok'}">Артикул: ${noArticle ? `без артикула ${noArticle}` : 'ОК'}</span>
                <span class="nsi-status-pill ${noGroup ? 'nsi-status-pill--warn' : 'nsi-status-pill--ok'}">Группа: ${noGroup ? `не задана ${noGroup}` : 'ОК'}</span>
                <span class="nsi-status-pill ${noWarehouse ? 'nsi-status-pill--warn' : 'nsi-status-pill--ok'}">Склад: ${noWarehouse ? `не выбран ${noWarehouse}` : 'ОК'}</span>
                <span class="nsi-status-pill ${zeroStock ? 'nsi-status-pill--muted' : 'nsi-status-pill--ok'}">Нулевой остаток: ${zeroStock}</span>
            </div>
        </div>
    `;
}

// --- СКЛАД: ОТРИСОВКА ОСТАТКОВ ---
window.renderNomenclature = function() {
    const tbody = document.getElementById('nomenclatureListTable');
    const cardsList = document.getElementById('nomenclatureListCards');
    const movementsList = document.getElementById('stockMovementsList');
    const balancesList = document.getElementById('stockBalancesList');
    bindNSIMasterViewControls();
    bindStockJournalControls();
    renderNSIMasterSelects();
    renderNSIMasterSummaryCards();
    renderNSIMasterLists();
    renderStockCockpit();
    renderInventoryDocuments();
    renderInventoryActs();
    renderStockQuality();
    renderStockRegrading();
    renderDiscrepancyActs();
    renderStockJournal();
    renderNSIIntegrityBrief();
    syncNSIWorkspaceTab();
    syncInventoryDocumentForm();
    if (!tbody && !cardsList) return;
    
    if (!nomenclatureDB || nomenclatureDB.length === 0) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 20px; color: var(--secondary);">Справочник пуст. Добавьте продукцию выше.</td></tr>';
        if (cardsList) cardsList.innerHTML = '<div class="empty-state nsi-product-empty">Пока нет позиций. Добавь первый материал через форму выше.</div>';
    }

    const renderNomenclaturePrice = (n) => {
        const curSym = { RUB: '₽', USD: '$', EUR: '€', CNY: '¥' };
        const sym = curSym[n.currency || 'RUB'] || '₽';
        const price = Number(n.price || 0);
        let priceHtml = `${price.toLocaleString('ru-RU')} ${sym}`;
        if (n.currency && n.currency !== 'RUB') {
            const rubEquivalent = price * (window.exchangeRates[n.currency] || 1);
            priceHtml += `<br><span style="font-size:10px; color:var(--secondary)">~ ${rubEquivalent.toLocaleString('ru-RU', {maximumFractionDigits:2})} ₽</span>`;
        }
        return priceHtml;
    };

    if (cardsList && nomenclatureDB.length) {
        cardsList.innerHTML = nomenclatureDB.map(n => {
            const stock = Number(n.stock || 0);
            const stockTone = stock > 0 ? 'ok' : 'warn';
            return `
                <article class="nsi-product-card">
                    <div class="nsi-product-main">
                        <div class="nsi-product-icon">${nsiEscape(String(n.name || '?').slice(0, 1).toUpperCase())}</div>
                        <div class="nsi-product-copy">
                            <h4>${nsiEscape(n.name || 'Без названия')}</h4>
                            <div class="nsi-product-tags">
                                ${formatNSICompactCode(n.article, 'Артикул')}
                                <span class="nsi-code-chip">${nsiEscape(n.group_name || 'Без группы')}</span>
                                <span class="nsi-code-chip">${nsiEscape(n.default_warehouse || 'Склад не выбран')}</span>
                            </div>
                        </div>
                    </div>
                    <div class="nsi-product-facts">
                        <div>
                            <span>Цена</span>
                            <strong>${renderNomenclaturePrice(n)}</strong>
                        </div>
                        <div>
                            <span>Остаток</span>
                            <strong class="nsi-stock-${stockTone}">${stock.toLocaleString('ru-RU')} ${nsiEscape(n.unit || 'шт')}</strong>
                        </div>
                    </div>
                    <div class="nsi-product-actions">
                        <button class="btn-success" onclick='moveStock(${nsiJSString(n.article)}, "add")'>Приход</button>
                        <button class="btn-secondary" onclick='moveStock(${nsiJSString(n.article)}, "remove")'>Расход</button>
                        <button class="btn-secondary" onclick='moveStock(${nsiJSString(n.article)}, "transfer")'>Переместить</button>
                        <button class="btn-danger" onclick='deleteNomenclature(${nsiJSString(n.article)})' title="Удалить позицию">Удалить</button>
                    </div>
                </article>
            `;
        }).join('');
    }

    if (tbody && nomenclatureDB.length) {
        tbody.innerHTML = nomenclatureDB.map(n => `
        <tr>
            <td><b>${nsiEscape(n.name)}</b></td>
            <td>${nsiEscape(n.article)}</td>
            <td>${nsiEscape(n.group_name || 'Без группы')}<br><span style="font-size:11px;color:var(--secondary);">${nsiEscape(n.default_warehouse || 'Без склада')}</span></td>
            <td>${renderNomenclaturePrice(n)}</td>
            <td><b style="color:var(--primary); font-size:16px;">${Number(n.stock || 0).toLocaleString('ru-RU')}</b> <span style="font-size:11px;color:var(--secondary);">${nsiEscape(n.unit)}</span></td>
            <td style="text-align: right; display:flex; gap:6px; justify-content:flex-end;">
                <button class="btn-success" style="padding: 4px 8px; font-size: 11px;" onclick='moveStock(${nsiJSString(n.article)}, "add")' title="Оприходовать товар">Приход</button>
                <button class="btn-secondary" style="padding: 4px 8px; font-size: 11px;" onclick='moveStock(${nsiJSString(n.article)}, "remove")' title="Списать товар">Расход</button>
                <button class="btn-secondary" style="padding: 4px 8px; font-size: 11px;" onclick='moveStock(${nsiJSString(n.article)}, "transfer")' title="Переместить между ячейками">Переместить</button>
                <button class="btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick='deleteNomenclature(${nsiJSString(n.article)})' title="Удалить карточку товара">Удалить</button>
            </td>
        </tr>
        `).join('');
    }

    if (balancesList) {
        const groupedBalances = new Map();
        stockBalancesDB.forEach(item => {
            const key = item.article || 'Без артикула';
            if (!groupedBalances.has(key)) {
                groupedBalances.set(key, {
                    article: item.article || '',
                    name: item.nomenclature_name || item.article || 'Позиция',
                    unit: item.unit || 'шт',
                    items: [],
                });
            }
            groupedBalances.get(key).items.push(item);
        });
        const groupedLots = new Map();
        stockLotsDB.forEach(item => {
            const key = item.article || 'Без артикула';
            if (!groupedLots.has(key)) groupedLots.set(key, []);
            groupedLots.get(key).push(item);
        });
        balancesList.innerHTML = groupedBalances.size ? Array.from(groupedBalances.values()).slice(0, 16).map(group => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${nsiEscape(group.name)}</div>
                <div class="client360-item-meta">${formatNSICompactCode(group.article, 'Артикул')} <span class="nsi-code-chip">${group.items.length} ячеек хранения</span></div>
                <div class="client360-list" style="margin-top:12px;">
                    ${group.items.map(item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${nsiEscape(item.warehouse || 'Без склада')}</div>
                                <div class="client360-item-meta">${nsiEscape(item.bin_code || 'Общая ячейка')}</div>
                            </div>
                            <div class="client360-item-side">${Number(item.qty || 0).toLocaleString('ru-RU')} ${group.unit}</div>
                        </div>
                    `).join('')}
                    ${(groupedLots.get(group.article || '') || []).length ? (groupedLots.get(group.article || '') || []).map(item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">Партия ${nsiEscape(item.batch_code || 'общая')}${item.serial_no ? ` / серийный ${nsiEscape(item.serial_no)}` : ''}</div>
                                <div class="client360-item-meta">${formatNSIWarehousePath(item.warehouse || 'Без склада', item.bin_code || 'Общая ячейка')}</div>
                            </div>
                            <div class="client360-item-side">${Number(item.qty || 0).toLocaleString('ru-RU')} ${group.unit}</div>
                        </div>
                    `).join('') : ''}
                </div>
            </div>
        `).join('') : '<div class="empty-state">Остатков по складам и ячейкам пока нет.</div>';
    }

    if (movementsList) {
        movementsList.innerHTML = stockMovementsDB.length ? stockMovementsDB.slice(0, 18).map(m => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${nsiEscape(m.name || m.article)}</div>
                    <div class="client360-item-meta">${formatNSIMovementType(m.movement_type)} · ${Number(m.qty || 0).toLocaleString('ru-RU')} ед.</div>
                    <div class="client360-item-meta">${formatNSIWarehousePath(m.from_warehouse || '—', m.from_bin || '')} → ${formatNSIWarehousePath(m.to_warehouse || '—', m.to_bin || '')}</div>
                    <div class="client360-item-meta">${m.batch_code ? `Партия ${nsiEscape(m.batch_code)}` : 'Партия не указана'}${m.serial_no ? ` · серийный ${nsiEscape(m.serial_no)}` : ''}</div>
                </div>
                <div class="client360-item-side">${new Date((m.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
            </div>
        `).join('') : '<div class="empty-state">История движения пока пуста.</div>';
    }
};
window.editNSIMasterRecord = editNSIMasterRecord;
window.prefillInventoryAdjustmentFromDiscrepancy = prefillInventoryAdjustmentFromDiscrepancy;

// --- СКЛАД: ОПРИХОДОВАНИЕ И СПИСАНИЕ ---
window.moveStock = async function(article, type) {
    const nom = nomenclatureDB.find(x => x.article === article);
    if (!nom) return;
    
    const actionName = type === 'add' ? 'Оприходование (Приход)' : type === 'remove' ? 'Списание (Расход)' : 'Перемещение между ячейками';
    const qtyStr = await customPrompt(`${actionName}\nТовар: ${nom.name}\nУкажите количество:`, "1");
    if (!qtyStr) return;
    
    const qty = parseFloat(qtyStr);
    if (isNaN(qty) || qty <= 0) return customAlert("Введите корректное число больше нуля");

    if (type === 'remove' && (nom.stock || 0) < qty) {
        if (!(await customConfirm(`⚠️ На складе всего ${nom.stock || 0} ${nom.unit}.\nВы хотите списать ${qty} ${nom.unit} и уйти в минус?`))) return;
    }

    const fromWarehouse = await customPrompt("Склад / зона откуда", type === 'add' ? 'Поступление' : 'Основной склад');
    if (fromWarehouse === null) return;
    const fromBin = await customPrompt("Ячейка откуда", type === 'add' ? 'Приемка' : 'A-01');
    if (fromBin === null) return;
    const batchCode = await customPrompt("Партия / batch", type === 'add' ? `LOT-${new Date().toISOString().slice(0,10)}` : '');
    if (batchCode === null) return;
    const serialNo = await customPrompt("Серийный номер (если есть)", '');
    if (serialNo === null) return;
    let toWarehouse = '';
    let toBin = '';
    if (type === 'add') {
        toWarehouse = await customPrompt("Склад / зона куда", 'Основной склад');
        if (toWarehouse === null) return;
        toBin = await customPrompt("Ячейка куда", 'A-01');
        if (toBin === null) return;
    } else if (type === 'transfer') {
        toWarehouse = await customPrompt("Склад / зона куда", 'Монтаж');
        if (toWarehouse === null) return;
        toBin = await customPrompt("Ячейка куда", 'M-01');
        if (toBin === null) return;
    }
    const comment = await customPrompt("Комментарий к движению", "");
    if (comment === null) return;

    const res = await apiCall(`/nomenclature/${encodeURIComponent(article)}/movement_detailed`, 'POST', {
        qty: qty,
        type: type,
        from_warehouse: fromWarehouse || '',
        from_bin: fromBin || '',
        to_warehouse: toWarehouse || '',
        to_bin: toBin || '',
        batch_code: batchCode || '',
        serial_no: serialNo || '',
        comment: comment || ''
    });
    if (res && res.status === 'success') {
        await loadNSI();
        renderNomenclature();
        showToast("Склад", "Остатки успешно обновлены");
    } else {
        customAlert("Ошибка при обновлении остатков");
    }
};

window.deleteNomenclature = async function(article) {
    if (!(await customConfirm(`Удалить позицию (Арт: ${article}) из базы?`))) return;
    
    const res = await apiCall(`/nomenclature/${encodeURIComponent(article)}`, 'DELETE');
    if (res && res.status === 'success') {
        await loadNSI(); 
        renderNomenclature(); 
        showToast("Успех", "Позиция удалена из справочника");
    } else {
        customAlert("Ошибка при удалении");
    }
};

window.saveNSIMasterRecord = saveNSIMasterRecord;
window.archiveNSIMasterRecord = archiveNSIMasterRecord;
window.createInventoryDocument = createInventoryDocument;

// --- КОНТАКТЫ ---
async function addContact() {
    const name = document.getElementById('addContactName').value.trim();
    const clientId = parseInt(document.getElementById('addContactClient').value) || 0;
    const phone = document.getElementById('addContactPhone').value.trim();
    const email = document.getElementById('addContactEmail').value.trim();
    const position = document.getElementById('addContactPosition').value.trim();

    if (!name || !clientId) return customAlert("Введите ФИО и выберите Контрагента!");

    await apiCall('/contacts', 'POST', { client_id: clientId, name, phone, email, position });
    document.getElementById('addContactName').value = '';
    document.getElementById('addContactPhone').value = '';
    document.getElementById('addContactEmail').value = '';
    document.getElementById('addContactPosition').value = '';
    
    await loadNSI();
    renderContacts();
    showToast("НСИ", "Контакт успешно добавлен");
}

window.renderContacts = function() {
    const ccSel = document.getElementById('addContactClient');
    if (ccSel && typeof clientsDB !== 'undefined') {
        const currentVal = ccSel.value; 
        ccSel.innerHTML = '<option value="">Выберите контрагента</option>' + 
                          clientsDB.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
        ccSel.value = currentVal;
    }

    const tbody = document.getElementById('contactsListTable');
    if (!tbody) return;
    
    if (contactsDB.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px; color: var(--secondary);">Нет добавленных контактов.</td></tr>';
        return;
    }

    tbody.innerHTML = contactsDB.map(c => {
        const clientObj = clientsDB.find(x => x.id === c.client_id);
        const cName = clientObj ? clientObj.name : 'Неизвестно';
        return `<tr><td><b>${c.name}</b></td><td><span class="status-badge" style="background:var(--bg);">${cName}</span></td><td>${c.position}</td><td>${c.phone}</td><td>${c.email}</td></tr>`;
    }).join('');
};

// ==========================================
// ИНТЕГРАЦИЯ НСИ В СОЗДАНИЕ ПРОЕКТА
// ==========================================

window.addNomToProjectList = function() {
    const input = document.getElementById('newProjNomInput');
    const qtyInp = document.getElementById('newProjNomQty');
    if (!input || !qtyInp) return;

    const name = input.value.trim();
    const qty = parseInt(qtyInp.value) || 1;

    if(!name) return;

    const nom = nomenclatureDB.find(n => n.name === name);
    
    // Предупреждаем менеджера, если товара не хватает на складе (но разрешаем добавить)
    if (nom && (nom.stock || 0) < qty) {
        showToast("Внимание", `Запрошено: ${qty}, На складе: ${nom.stock || 0}`, "error");
    }

    selectedProjectNomenclature.push({ 
        name: name, 
        qty: qty, 
        price: nom ? nom.price : 0, 
        unit: nom ? nom.unit : 'шт',
        article: nom ? nom.article : ''
    });
    
    input.value = ''; qtyInp.value = '';
    updateProjectNomList();
};

window.updateProjectNomList = function() {
    const list = document.getElementById('newProjNomList');
    if(!list) return;
    if(selectedProjectNomenclature.length === 0) {
        list.innerHTML = '<div class="project-create-help">Пока ничего не добавлено. Выбери позиции из номенклатуры и добавь их в состав проекта.</div>';
        return;
    }
    list.innerHTML = selectedProjectNomenclature.map((item, index) =>
        `<div style="display:flex; justify-content:space-between; align-items:center; gap:12px; background:var(--card-bg); padding:10px 12px; border-radius:12px; border:1px solid var(--border);">
            <div style="display:flex; flex-direction:column; gap:4px; min-width:0;">
                <span style="font-weight:700; color:var(--text);">${item.name}</span>
                <span style="font-size:12px; color:var(--secondary);">${item.qty} ${item.unit}${item.article ? ` · Арт. ${item.article}` : ''}</span>
            </div>
            <span style="color:var(--danger); cursor:pointer; font-weight:bold; font-size: 16px; flex-shrink:0;" onclick="selectedProjectNomenclature.splice(${index}, 1); updateProjectNomList();">×</span>
        </div>`
    ).join('');
};

window.createNewProject = function() { 
    const sel = document.getElementById('newProjClient');
    if(sel) {
        sel.innerHTML = '<option value="">Свободный ввод или выберите из базы</option>' + clientsDB.map(c => `<option value="${c.name}">${c.name} (ИНН: ${c.inn})</option>`).join('');
        
        sel.onchange = (e) => {
            const clientObj = clientsDB.find(x => x.name === e.target.value);
            const cSel = document.getElementById('newProjContact');
            const cWrap = document.getElementById('newProjContactWrap');
            if (clientObj) {
                const clientContacts = contactsDB.filter(x => x.client_id === clientObj.id);
                if(clientContacts.length > 0) {
                    if (cWrap) cWrap.style.display = 'flex';
                    cSel.innerHTML = '<option value="">Выберите контактное лицо</option>' + clientContacts.map(c => `<option value="${c.name}">${c.name} (${c.position})</option>`).join('');
                } else {
                    if (cWrap) cWrap.style.display = 'none';
                    cSel.value = '';
                }
            } else {
                if (cWrap) cWrap.style.display = 'none';
                cSel.value = '';
            }
        };
    }
    
    const tDiv = document.getElementById('newProjTeam');
    if(tDiv) {
        tDiv.innerHTML = allUsersDB.filter(u => u.role !== 'Директор').map(u => 
            `<label style="display:flex; gap:10px; align-items:flex-start; margin-bottom:8px; cursor:pointer; padding:8px 10px; border-radius:12px; background:var(--surface-muted);">
                <input type="checkbox" value="${u.name}" class="team-cb-new" style="margin-top:2px;">
                <span style="display:flex; flex-direction:column; gap:2px;">
                    <b style="font-size:13px;">${u.name}</b>
                    <span style="color:var(--secondary); font-size:12px;">${u.role}</span>
                </span>
            </label>`
        ).join('');
    }
    
    const nextNumber = projectsDB.length + 1;
    const currentYear = new Date().getFullYear();
    if (document.getElementById('newProjContract')) document.getElementById('newProjContract').value = `${currentYear}-КРД-${String(nextNumber).padStart(3, '0')}`;
    
    if (document.getElementById('newProjName')) document.getElementById('newProjName').value = '';
    if (document.getElementById('newProjManager')) document.getElementById('newProjManager').value = currentUser.name;
    if (document.getElementById('newProjBudget')) document.getElementById('newProjBudget').value = '';
    if (document.getElementById('newProjContactWrap')) document.getElementById('newProjContactWrap').style.display = 'none';
    if (document.getElementById('newProjContact')) document.getElementById('newProjContact').value = '';
    window.pendingProjectArchiveDetails = {};

    selectedProjectNomenclature = [];
    updateProjectNomList();
    
    // ДОБАВИЛИ ПОКАЗ ОСТАТКОВ ПРИ ВЫБОРЕ
    const dl = document.getElementById('nomDataList');
    if(dl) dl.innerHTML = nomenclatureDB.map(n => `<option value="${n.name}">Арт. ${n.article} | Склад: ${n.stock || 0} ${n.unit} | ${n.price} ₽</option>`).join('');

    if (window.ProjectRolesManager) window.ProjectRolesManager.renderSelector('newProjRoles');
    document.getElementById('createProjectModal').style.display = 'flex';
    if (typeof focusFieldById === 'function') focusFieldById('newProjName');
};

window.submitNewProject = async function() {
    const name = document.getElementById('newProjName').value.trim();
    if(!name) return customAlert("Введите наименование!");

    const contract = document.getElementById('newProjContract').value.trim();
    const client = document.getElementById('newProjClient').value;
    const manager = document.getElementById('newProjManager').value.trim();
    const budget = parseFloat(document.getElementById('newProjBudget').value) || 0;

    const team = Array.from(document.querySelectorAll('.team-cb-new:checked')).map(cb => cb.value);
    const roles = Array.from(document.querySelectorAll('.role-cb-newProjRoles:checked')).map(cb => cb.value);

    const contactSelect = document.getElementById('newProjContact');
    let finalClient = client;
    if (client && contactSelect && contactSelect.value) finalClient += ` (Контакт: ${contactSelect.value})`;

    const isEmptyChecked = document.getElementById('isEmptyChecklist') ? document.getElementById('isEmptyChecklist').checked : false;
    let dynamicChecklist = [];
    
    if (!isEmptyChecked && typeof checklistTemplate !== 'undefined') {
        dynamicChecklist = JSON.parse(JSON.stringify(checklistTemplate));
        if (budget >= 3000000) {
            dynamicChecklist.splice(3, 0, {
                title: "3.1. [АВТО] Фин. контроль крупной сделки",
                responsibles: "Директор, Бухгалтерия",
                tasks: [
                    "Смета и маржинальность сделки свыше 3 млн руб. проверена и утверждена Директором.",
                    "Проведена расширенная проверка надежности контрагента."
                ]
            });
        }
    }

    const req = {
        name: name,
        contract: contract,
        client: finalClient,
        manager: manager,
        budget: budget,
        costs: 0,
        team: team,
        checklist: dynamicChecklist,
        allowed_roles: roles,
        nomenclature: selectedProjectNomenclature,
        archive_details: window.pendingProjectArchiveDetails || {}
    };

    const res = await apiCall('/projects', 'POST', req);
    if(res && res.status === 'success') {
        document.getElementById('createProjectModal').style.display = 'none';
        await loadProjects();
        if(typeof renderDashboard === 'function') renderDashboard();
        const createdId = Number(res.id || 0) || Number((projectsDB.find(item => item.contract === contract && item.name === name) || {}).id || 0);
        showToast("Успех", "Проект успешно создан");
        if (createdId && typeof openProject === 'function') {
            openProject(createdId);
        }
    } else {
        customAlert("Ошибка при создании");
    }
};

function resetNSIMasterForm() {
    nsiMasterEditState = { type: '', id: 0 };
    const defaults = nsiMasterDataDB?.defaults || {};
    [
        'nsiMasterName',
        'nsiMasterCode',
        'nsiMasterPersonnelNumber',
        'nsiMasterEmail',
        'nsiMasterPhone',
        'nsiMasterDepartmentName',
        'nsiMasterCharacteristicType',
        'nsiMasterZoneName',
        'nsiMasterModuleName',
        'nsiMasterManagerName',
        'nsiMasterBankName',
        'nsiMasterAccountNumber',
        'nsiMasterBik',
        'nsiMasterComment',
    ].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = String(value);
    };
    setValue('nsiMasterWarehouseId', defaults.warehouse_id || 0);
    setValue('nsiMasterLegalEntityId', defaults.legal_entity_id || 0);
    setValue('nsiMasterBusinessUnitId', defaults.business_unit_id || 0);
    setValue('nsiMasterPositionId', defaults.position_id || 0);
    setValue('nsiMasterArticleKind', 'expense');
    setValue('nsiMasterCurrency', 'RUB');
    setValue('nsiMasterFlowKind', '');
    const saveBtn = document.getElementById('nsiMasterSaveBtn');
    if (saveBtn) saveBtn.textContent = 'Добавить';
}

function syncNSIMasterForm() {
    const entityType = document.getElementById('nsiMasterEntityType')?.value || 'warehouses';
    document.querySelectorAll('[data-nsi-field]').forEach(node => {
        const allowed = (node.dataset.nsiField || '').split(',').includes(entityType);
        node.style.display = allowed ? '' : 'none';
    });
}

async function saveNSIMasterRecord() {
    const entityType = document.getElementById('nsiMasterEntityType')?.value;
    const payload = {
        name: document.getElementById('nsiMasterName')?.value.trim() || '',
        code: document.getElementById('nsiMasterCode')?.value.trim() || '',
        personnel_number: document.getElementById('nsiMasterPersonnelNumber')?.value.trim() || '',
        email: document.getElementById('nsiMasterEmail')?.value.trim() || '',
        phone: document.getElementById('nsiMasterPhone')?.value.trim() || '',
        department_name: document.getElementById('nsiMasterDepartmentName')?.value.trim() || '',
        characteristic_type: document.getElementById('nsiMasterCharacteristicType')?.value.trim() || '',
        warehouse_id: Number(document.getElementById('nsiMasterWarehouseId')?.value || 0),
        zone_name: document.getElementById('nsiMasterZoneName')?.value.trim() || '',
        article_kind: document.getElementById('nsiMasterArticleKind')?.value || 'expense',
        module_name: document.getElementById('nsiMasterModuleName')?.value.trim() || '',
        flow_kind: document.getElementById('nsiMasterFlowKind')?.value.trim() || '',
        legal_entity_id: Number(document.getElementById('nsiMasterLegalEntityId')?.value || 0),
        business_unit_id: Number(document.getElementById('nsiMasterBusinessUnitId')?.value || 0),
        position_id: Number(document.getElementById('nsiMasterPositionId')?.value || 0),
        manager_name: document.getElementById('nsiMasterManagerName')?.value.trim() || '',
        bank_name: document.getElementById('nsiMasterBankName')?.value.trim() || '',
        account_number: document.getElementById('nsiMasterAccountNumber')?.value.trim() || '',
        bik: document.getElementById('nsiMasterBik')?.value.trim() || '',
        currency: document.getElementById('nsiMasterCurrency')?.value || 'RUB',
        comment: document.getElementById('nsiMasterComment')?.value.trim() || '',
        is_active: 1,
    };
    if (!entityType || !payload.name) return customAlert('Укажи тип справочника и наименование.');
    const editingId = nsiMasterEditState.id;
    const method = editingId ? 'PUT' : 'POST';
    const endpoint = editingId
        ? `/nsi/master_data/${encodeURIComponent(entityType)}/${editingId}`
        : `/nsi/master_data/${encodeURIComponent(entityType)}`;
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(resolveNSIMasterError(res?.error) || 'Не удалось сохранить запись справочника.');
    resetNSIMasterForm();
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', editingId ? 'Запись справочника обновлена' : 'Запись справочника добавлена');
}

async function archiveNSIMasterRecord(entityType, id) {
    if (!(await customConfirm('Архивировать запись справочника?'))) return;
    const res = await apiCall(`/nsi/master_data/${encodeURIComponent(entityType)}/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(resolveNSIMasterError(res?.error) || 'Не удалось архивировать запись.');
    await loadNSI();
    renderNomenclature();
}

async function editNSIMasterRecord(entityType, id) {
    const collection = nsiMasterDataDB[entityType] || [];
    const item = collection.find(row => Number(row.id) === Number(id));
    if (!item) return customAlert('Запись справочника не найдена.');
    nsiMasterEditState = { type: entityType, id: Number(id) };
    const setValue = (inputId, value) => {
        const el = document.getElementById(inputId);
        if (el) el.value = value == null ? '' : String(value);
    };
    setValue('nsiMasterEntityType', entityType);
    setValue('nsiMasterName', item.full_name || item.name || '');
    setValue('nsiMasterCode', item.code || '');
    setValue('nsiMasterPersonnelNumber', item.personnel_number || '');
    setValue('nsiMasterEmail', item.email || '');
    setValue('nsiMasterPhone', item.phone || '');
    setValue('nsiMasterDepartmentName', item.department_name || '');
    setValue('nsiMasterCharacteristicType', item.characteristic_type || '');
    setValue('nsiMasterWarehouseId', item.warehouse_id || nsiMasterDataDB?.defaults?.warehouse_id || 0);
    setValue('nsiMasterZoneName', item.zone_name || '');
    setValue('nsiMasterArticleKind', item.article_kind || 'expense');
    setValue('nsiMasterModuleName', item.module_name || '');
    setValue('nsiMasterFlowKind', item.flow_kind || '');
    setValue('nsiMasterLegalEntityId', item.legal_entity_id || nsiMasterDataDB?.defaults?.legal_entity_id || 0);
    setValue('nsiMasterBusinessUnitId', item.business_unit_id || nsiMasterDataDB?.defaults?.business_unit_id || 0);
    setValue('nsiMasterPositionId', item.position_id || nsiMasterDataDB?.defaults?.position_id || 0);
    setValue('nsiMasterManagerName', item.manager_name || '');
    setValue('nsiMasterBankName', item.bank_name || '');
    setValue('nsiMasterAccountNumber', item.account_number || '');
    setValue('nsiMasterBik', item.bik || '');
    setValue('nsiMasterCurrency', item.currency || 'RUB');
    setValue('nsiMasterComment', item.comment || '');
    syncNSIMasterForm();
    const saveBtn = document.getElementById('nsiMasterSaveBtn');
    if (saveBtn) saveBtn.textContent = 'Сохранить изменения';
}

async function runNSIMasterReconciliation() {
    const res = await apiCall('/integration/1c/reconciliation/run', 'POST');
    if (!res || res.error) return customAlert(resolveNSIMasterError(res?.error) || 'Не удалось запустить сверку с 1С.');
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', `Сверка завершена, найдено расхождений: ${res.mismatch_count || 0}`);
}

function getNSIMasterEntityTitles() {
    return {
        warehouses: 'Склады и зоны',
        units: 'Единицы измерения',
        groups: 'Группы номенклатуры',
        employees: 'Сотрудники',
        positions: 'Должности',
        characteristics: 'Характеристики',
        storage_cells: 'Ячейки хранения',
        income_expense_articles: 'Статьи доходов и расходов',
        financial_responsibility_centers: 'Центры ответственности',
        operation_types: 'Виды операций',
        bank_accounts: 'Банковские счета',
    };
}

function getLatestNSIReconciliationEntities() {
    return nsiReconciliationRunsDB?.[0]?.summary?.entities || {};
}

function normalizeNSIText(value) {
    return String(value || '').trim().toLowerCase();
}

function nsiEscape(value) {
    if (typeof escapeHtml === 'function') return escapeHtml(value);
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function nsiJSString(value) {
    return JSON.stringify(String(value ?? ''));
}

function formatNSIFlowKind(value) {
    const labels = {
        incoming: 'Входящий поток',
        outgoing: 'Исходящий поток',
        internal: 'Внутренний поток',
        income: 'Доходная статья',
        expense: 'Расходная статья',
        nsi: 'НСИ и справочники',
        sale: 'Продажи',
        sales: 'Продажи',
        supply: 'Закупки и склад',
        warehouse: 'Склад',
        production: 'Производство',
        accounting: 'Бухгалтерия',
        finance: 'Финансы',
    };
    const raw = String(value || '').trim().toLowerCase();
    return labels[raw] || value || 'Не указано';
}

function formatNSISyncBadge(value, active = 1) {
    if (Number(active || 0) !== 1) {
        return '<span class="nsi-status-pill nsi-status-pill--muted">В архиве</span>';
    }
    const raw = String(value || 'draft').toLowerCase();
    const tone = raw === 'synced' ? 'ok' : raw === 'failed' || raw === 'conflict' ? 'danger' : raw === 'queued' || raw === 'retry' || raw === 'processing' ? 'warn' : 'muted';
    return `<span class="nsi-status-pill nsi-status-pill--${tone}">${nsiEscape(formatNSIExchangeState(raw))}</span>`;
}

function formatNSICompactCode(value, label = 'Код') {
    const raw = String(value || '').trim();
    if (!raw) return `<span class="nsi-code-chip nsi-code-chip--empty">${label} не задан</span>`;
    return `<span class="nsi-code-chip">${label}: ${nsiEscape(raw)}</span>`;
}

function formatNSIWarehousePath(warehouse, bin) {
    const parts = [warehouse || 'Склад не указан', bin || 'Ячейка не указана'].filter(Boolean);
    return parts.map(nsiEscape).join(' / ');
}

function formatNSIMovementType(value) {
    const labels = {
        add: 'Приход',
        remove: 'Расход',
        transfer: 'Перемещение',
        inventory: 'Инвентаризация',
        writeoff: 'Списание',
        receipt_adjustment: 'Корректировка прихода',
    };
    return labels[String(value || '').toLowerCase()] || formatNSIFlowKind(value);
}

function formatNSIItemMeta(entityType, item) {
    const code = item.code || item.personnel_number || item.bik || '';
    if (entityType === 'employees') return [item.position_name || 'Должность не указана', item.business_unit_name || item.legal_entity_name || 'Контур не указан', item.email || 'почта не указана'].filter(Boolean);
    if (entityType === 'positions') return [item.department_name || 'Подразделение не указано'];
    if (entityType === 'characteristics') return [item.characteristic_type || 'Тип характеристики не указан'];
    if (entityType === 'storage_cells') return [item.warehouse_name || 'Склад не указан', item.zone_name || 'Зона не указана'];
    if (entityType === 'income_expense_articles') return [formatNSIFlowKind(item.article_kind), item.comment || ''];
    if (entityType === 'financial_responsibility_centers') return [item.legal_entity_name || 'Юрлицо не указано', item.business_unit_name || 'Подразделение не указано', item.manager_name || 'Руководитель не указан'];
    if (entityType === 'operation_types') return [formatNSIFlowKind(item.module_name), formatNSIFlowKind(item.flow_kind)];
    if (entityType === 'bank_accounts') return [item.bank_name || 'Банк не указан', item.account_number || 'Счёт не указан', item.currency || ''];
    return [code ? `Код: ${code}` : '', item.comment || ''].filter(Boolean);
}

function getNSIMasterIssueIndex() {
    const entities = getLatestNSIReconciliationEntities();
    const issueIndex = {};
    Object.entries(entities).forEach(([entityType, meta]) => {
        const entityMap = new Map();
        (meta?.issues || []).forEach(issue => {
            const keys = [
                String(issue.row_id || '').trim(),
                String(issue.entity_id || '').trim(),
            ].filter(Boolean);
            keys.forEach(key => {
                if (!entityMap.has(key)) entityMap.set(key, []);
                entityMap.get(key).push(issue);
            });
        });
        issueIndex[entityType] = entityMap;
    });
    return issueIndex;
}

function collectNSIMasterSearchText(entityType, item) {
    return normalizeNSIText([
        item.name,
        item.full_name,
        item.code,
        item.personnel_number,
        item.email,
        item.phone,
        item.department_name,
        item.characteristic_type,
        item.zone_name,
        item.module_name,
        item.flow_kind,
        item.bank_name,
        item.account_number,
        item.bik,
        item.manager_name,
        item.position_name,
        item.legal_entity_name,
        item.business_unit_name,
        item.warehouse_name,
        entityType,
    ].join(' '));
}

function formatNSIReconciliationIssue(issue) {
    const issueLabels = {
        missing_external_id: 'Нет внешнего идентификатора 1С',
        conflict: 'Конфликт обмена',
        failed: 'Ошибка обмена',
        external_id_mismatch: 'Идентификатор 1С расходится с очередью',
        no_sync_trace: 'Нет следа синка',
    };
    const state = issue?.state ? ` · статус ${formatNSIExchangeState(issue.state)}` : '';
    const error = issue?.last_error ? ` · ${issue.last_error}` : '';
    return `${issueLabels[issue?.issue] || issue?.issue || 'Проблема обмена'}${state}${error}`;
}

function formatNSIExchangeState(value) {
    const labels = {
        draft: 'черновик',
        active: 'активно',
        synced: 'синхронизировано',
        queued: 'в очереди',
        retry: 'повтор',
        processing: 'обработка',
        failed: 'ошибка',
        conflict: 'конфликт',
        archived: 'архив',
    };
    return labels[String(value || '').toLowerCase()] || value || 'черновик';
}

function formatWarehouseQualityLabel(value) {
    const labels = {
        hold: 'на удержании',
        repair: 'на ремонте',
        scrap: 'брак',
        return: 'возврат',
        inspect: 'проверить',
        rework: 'доработать',
        release: 'разрешить выпуск',
        writeoff: 'списать',
    };
    return labels[String(value || '').toLowerCase()] || value || 'не задано';
}

function formatStockJournalStatus(value) {
    const labels = {
        inventory_document: 'Складской документ',
        inventory_act: 'Инвентаризационный акт',
        quality_report: 'Контроль качества',
        regrading_doc: 'Пересортица',
        discrepancy_act: 'Акт расхождений',
        inventory: 'Инвентаризация',
        receipt: 'Приход',
        issue: 'Расход',
        transfer: 'Перемещение',
        writeoff: 'Списание',
        adjustment: 'Корректировка',
        open: 'Открыто',
        closed: 'Закрыто',
        draft: 'Черновик',
        posted: 'Проведено',
        active: 'Активно',
        hold: 'Удержание',
        released: 'Выпущено',
        failed: 'Ошибка',
    };
    const raw = String(value || '').toLowerCase();
    return labels[raw] || formatNSIExchangeState(raw);
}

function resolveNSIMasterError(errorCode) {
    const map = {
        name_required: 'Укажи наименование записи справочника.',
        warehouse_required: 'Для ячейки хранения нужно выбрать склад.',
        article_kind_invalid: 'Для статьи доходов / расходов нужно выбрать корректный тип.',
        legal_entity_required: 'Для этой записи нужно указать юрлицо.',
        business_unit_required: 'Для этой записи нужно указать подразделение.',
        position_required: 'Для сотрудника нужно выбрать должность из справочника.',
        module_name_required: 'Для вида операции нужно указать модуль.',
        flow_kind_required: 'Для вида операции нужно указать поток.',
        bank_name_required: 'Для банковского счёта нужно указать банк.',
        account_number_required: 'Для банковского счёта нужно указать номер счёта.',
        bik_required: 'Для банковского счёта нужно указать БИК.',
        forbidden_scope: 'Запись выходит за пределы доступного контура по юрлицу или подразделению.',
        sync_not_supported: 'Для этого справочника синхронизация с 1С ещё не настроена.',
        invalid_entity_type: 'Неизвестный тип справочника.',
        not_found: 'Запись справочника не найдена.',
        forbidden: 'Недостаточно прав для этой операции.',
    };
    return map[errorCode] || errorCode || 'Не удалось выполнить операцию со справочником.';
}

function getNSIMasterFormHints() {
    return {
        warehouses: 'Склад как главная запись: единый справочник для остатков, перемещений, инвентаризаций и производственного потока.',
        units: 'Единица измерения должна быть единой для номенклатуры, продаж, закупок и производства.',
        groups: 'Группа номенклатуры нужна для отчётности, прайсов, аналитики и сопоставления с 1С.',
        storage_cells: 'Ячейка хранения должна жить как отдельная сущность, а не как свободный текст в документах склада.',
        characteristics: 'Характеристика номенклатуры должна быть нормализована для спецификаций, партий и продаж.',
        positions: 'Должность — отдельный слой справочников для сотрудников, ЭПЛ, ролей и ресурсов.',
        employees: 'Сотрудник должен быть связан с юрлицом, подразделением и должностью, чтобы потом не было “свободных ФИО” в процессах.',
        income_expense_articles: 'Статьи ДР используются в бюджетах, казначействе, план-факте и управленческой аналитике.',
        financial_responsibility_centers: 'ЦФО — отдельный контур управленческого учёта, план-факта и лимитов.',
        operation_types: 'Вид операции должен быть единым для закупок, продаж, склада, производства и обмена с 1С.',
        bank_accounts: 'Банковский счёт как главная запись: юрлицо, банк, БИК и валюта должны быть единым источником данных.',
    };
}

function syncInventoryDocumentForm() {
    const docType = document.getElementById('inventoryDocType')?.value || 'inventory';
    const countedWrap = document.getElementById('inventoryDocCountedQtyWrap');
    const targetWarehouseWrap = document.getElementById('inventoryDocTargetWarehouseWrap');
    const targetBinWrap = document.getElementById('inventoryDocTargetBinWrap');
    if (countedWrap) countedWrap.style.display = docType === 'inventory' ? '' : 'none';
    if (targetWarehouseWrap) targetWarehouseWrap.style.display = docType === 'transfer' ? '' : 'none';
    if (targetBinWrap) targetBinWrap.style.display = docType === 'transfer' ? '' : 'none';
    const hint = document.getElementById('inventoryDocHint');
    if (hint) {
        const hints = {
            inventory: 'Инвентаризация: система сравнивает учётный остаток с фактическим подсчётом и формирует расхождение.',
            writeoff: 'Списание: фиксируй склад, ячейку и причину, чтобы потом аналитика расхождений не оставалась пустой.',
            transfer: 'Перемещение: обязательно укажи и исходный, и целевой склад/ячейку из справочника.',
            receipt_adjustment: 'Приходная корректировка: используй её для доведения учёта до факта после расхождений или приёмки.',
        };
        hint.textContent = hints[docType] || '';
    }
}

function bindNSIMasterViewControls() {
    const search = document.getElementById('nsiMasterSearch');
    const onlyActive = document.getElementById('nsiMasterOnlyActive');
    const onlyIssues = document.getElementById('nsiMasterOnlyIssues');
    if (search && !search.dataset.bound) {
        search.dataset.bound = '1';
        search.addEventListener('input', () => renderNSIMasterLists());
    }
    if (onlyActive && !onlyActive.dataset.bound) {
        onlyActive.dataset.bound = '1';
        onlyActive.addEventListener('change', () => renderNSIMasterLists());
    }
    if (onlyIssues && !onlyIssues.dataset.bound) {
        onlyIssues.dataset.bound = '1';
        onlyIssues.addEventListener('change', () => renderNSIMasterLists());
    }
}

function bindStockJournalControls() {
    const filter = document.getElementById('stockJournalEntityType');
    if (filter && !filter.dataset.bound) {
        filter.dataset.bound = '1';
        filter.addEventListener('change', () => renderStockJournal());
    }
}

async function queueNSIMasterRecordSync(entityType, id) {
    const res = await apiCall(`/nsi/master_data/${encodeURIComponent(entityType)}/${id}/sync`, 'POST');
    if (!res || res.error) return customAlert(resolveNSIMasterError(res?.error) || 'Не удалось поставить запись в очередь обмена.');
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', 'Запись поставлена в очередь синхронизации с 1С');
}

async function queueNSIMasterEntitySync(entityType) {
    const res = await apiCall(`/nsi/master_data/${encodeURIComponent(entityType)}/sync_failed`, 'POST');
    if (!res || res.error) return customAlert(resolveNSIMasterError(res?.error) || 'Не удалось повторно поставить проблемные записи в очередь.');
    await loadNSI();
    renderNomenclature();
    showToast('НСИ', `В очередь поставлено записей: ${res.queued || 0}`);
}

function renderNSIMasterSummaryCards() {
    const container = document.getElementById('nsiMasterSummaryCards');
    if (!container) return;
    const latest = getLatestNSIReconciliationEntities();
    const cards = [
        ['warehouses', 'Склады'],
        ['storage_cells', 'Ячейки'],
        ['groups', 'Группы'],
        ['operation_types', 'Операции'],
        ['employees', 'Сотрудники'],
        ['bank_accounts', 'Счета'],
    ];
    container.innerHTML = cards.map(([key, title]) => {
        const rows = nsiMasterDataDB[key] || [];
        const issues = latest[key]?.mismatches || 0;
        const active = rows.filter(item => Number(item.is_active || 0) === 1).length;
        return `
            <div class="metric-card nsi-summary-card ${issues ? 'warning' : ''}">
                <div class="metric-title">${title}</div>
                <div class="metric-value">${active}</div>
                <div class="client360-item-meta">Всего ${rows.length} · ${issues ? `${issues} нужно проверить` : 'обмен без ошибок'}</div>
            </div>
        `;
    }).join('');
}

function renderNSIReconciliation() {
    const container = document.getElementById('nsiReconciliationList');
    if (!container) return;
    const titles = getNSIMasterEntityTitles();
    const lastRun = nsiReconciliationRunsDB[0] || {};
    const latest = nsiReconciliationRunsDB[0]?.summary?.entities || {};
    const rows = Object.keys(titles)
        .filter(key => latest[key])
        .map(key => `
            <div class="client360-item client360-item--stack">
                <div>
                    <div class="client360-item-title">${titles[key]}</div>
                    <div class="client360-item-meta">Записей: ${latest[key].rows || 0} · Несостыковок: ${latest[key].mismatches || 0}</div>
                </div>
                <div class="finance-actions-row" style="margin:10px 0 0;">
                    <button class="btn-secondary" onclick="queueNSIMasterEntitySync('${key}')">Повторить синхронизацию проблемных</button>
                </div>
                ${(latest[key].issues || []).length ? `
                    <div class="client360-list" style="margin-top:12px;">
                        ${(latest[key].issues || []).slice(0, 4).map(issue => `
                            <div class="client360-item">
                                <div>
                                    <div class="client360-item-title">${issue.entity_id || 'Запись'}</div>
                                    <div class="client360-item-meta">${formatNSIReconciliationIssue(issue)}</div>
                                </div>
                                <div class="client360-item-side">${latest[key].mismatches ? 'Требует внимания' : 'В норме'}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : `<div class="client360-item-meta" style="margin-top:10px;">${latest[key].mismatches ? 'Несостыковки найдены, но без детализированных записей.' : 'Справочник синхронизирован ровно.'}</div>`}
            </div>
        `);
    container.innerHTML = rows.length
        ? `${lastRun.created_at ? `<div class="client360-item-meta" style="margin-bottom:10px;">Последняя сверка: ${new Date((lastRun.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>` : ''}${rows.join('')}`
        : '<div class="empty-state">Сверка с 1С ещё не запускалась или для вашего доступа она недоступна.</div>';
}

function renderNSIMasterSelects() {
    const units = nsiMasterDataDB.units || [];
    const groups = nsiMasterDataDB.groups || [];
    const warehouses = nsiMasterDataDB.warehouses || [];
    const storageCells = nsiMasterDataDB.storage_cells || [];
    const legalEntities = nsiMasterDataDB.legal_entities || [];
    const businessUnits = nsiMasterDataDB.business_units || [];
    const positions = nsiMasterDataDB.positions || [];
    const defaults = nsiMasterDataDB?.defaults || {};
    const defaultWarehouse = warehouses.find(item => Number(item.id || 0) === Number(defaults.warehouse_id || 0));
    const targetWarehouse = warehouses.find(item => item.name === 'Монтаж') || warehouses.find(item => item.id !== defaultWarehouse?.id) || defaultWarehouse;
    const fill = (id, items, placeholder, fallback = '', valueField = 'name', labelField = 'name') => {
        const el = document.getElementById(id);
        if (!el) return;
        const current = el.value;
        el.innerHTML = [`<option value="">${placeholder}</option>`]
            .concat(items.filter(item => Number(item.is_active || 0) === 1 || item.is_active === undefined).map(item => `<option value="${item[valueField]}">${item[labelField] || item.name || item.full_name || item.code}</option>`))
            .join('');
        if (current && Array.from(el.options).some(opt => opt.value === current)) {
            el.value = current;
        } else if (fallback && Array.from(el.options).some(opt => opt.value === String(fallback))) {
            el.value = String(fallback);
        }
    };
    fill('addNomUnit', units, 'Выбери ед. изм.', 'шт');
    fill('addNomGroup', groups, 'Без группы');
    fill('addNomWarehouse', warehouses, 'Без склада', 'Основной склад');
    fill('nsiMasterWarehouseId', warehouses, 'Склад ячейки', defaults.warehouse_id || 0, 'id', 'name');
    fill('nsiMasterLegalEntityId', legalEntities, 'Юрлицо', defaults.legal_entity_id || 0, 'id', 'short_name');
    fill('nsiMasterBusinessUnitId', businessUnits, 'Подразделение', defaults.business_unit_id || 0, 'id', 'name');
    fill('nsiMasterPositionId', positions, 'Должность', defaults.position_id || 0, 'id', 'name');
    fill('inventoryDocWarehouse', warehouses, 'Склад', defaultWarehouse?.name || 'Основной склад', 'name', 'name');
    fill('inventoryDocTargetWarehouse', warehouses, 'Склад назначения', targetWarehouse?.name || '', 'name', 'name');
    fill('inventoryActWarehouse', warehouses, 'Склад', defaultWarehouse?.name || 'Основной склад', 'name', 'name');
    fill('warehouseQualityWarehouse', warehouses, 'Склад', defaultWarehouse?.name || 'Основной склад', 'name', 'name');
    fill('regradingWarehouse', warehouses, 'Склад', defaultWarehouse?.name || 'Основной склад', 'name', 'name');
    const storageOptions = document.getElementById('nsiStorageCellOptions');
    if (storageOptions) {
        storageOptions.innerHTML = storageCells
            .filter(item => Number(item.is_active || 0) === 1)
            .map(item => `<option value="${item.name}">${[item.warehouse_name || '', item.zone_name || '', item.code || ''].filter(Boolean).join(' · ')}</option>`)
            .join('');
    }
    syncNSIMasterForm();
    syncInventoryDocumentForm();
}

function renderNSIMasterLists() {
    const container = document.getElementById('nsiMasterDataLists');
    if (!container) return;
    bindNSIMasterViewControls();
    const search = normalizeNSIText(document.getElementById('nsiMasterSearch')?.value || '');
    const onlyActive = !!document.getElementById('nsiMasterOnlyActive')?.checked;
    const onlyIssues = !!document.getElementById('nsiMasterOnlyIssues')?.checked;
    const issueIndex = getNSIMasterIssueIndex();
    const sections = [
        ['warehouses', 'Склады'],
        ['storage_cells', 'Ячейки хранения'],
        ['units', 'Единицы измерения'],
        ['groups', 'Группы номенклатуры'],
        ['characteristics', 'Характеристики номенклатуры'],
        ['positions', 'Должности'],
        ['employees', 'Сотрудники'],
        ['income_expense_articles', 'Статьи доходов и расходов'],
        ['financial_responsibility_centers', 'ЦФО'],
        ['operation_types', 'Виды операций'],
        ['bank_accounts', 'Банковские счета'],
    ];
    const metaText = (key, item) => {
        const meta = formatNSIItemMeta(key, item);
        return meta.length ? meta.map(nsiEscape).join(' · ') : 'Дополнительные данные не заполнены';
    };
    const titleText = (key, item) => key === 'employees' ? (item.full_name || item.name || 'Сотрудник') : (item.name || 'Запись');
    container.innerHTML = sections.map(([key, title]) => {
        const items = (nsiMasterDataDB[key] || []).filter(item => {
            const active = Number(item.is_active || 0) === 1;
            const issueList = issueIndex[key]?.get(String(item.id || '')) || issueIndex[key]?.get(String(item.code || item.personnel_number || '')) || [];
            if (onlyActive && !active) return false;
            if (onlyIssues && !issueList.length) return false;
            if (search && !collectNSIMasterSearchText(key, item).includes(search)) return false;
            return true;
        });
        const total = (nsiMasterDataDB[key] || []).length;
        const mismatchCount = getLatestNSIReconciliationEntities()[key]?.mismatches || 0;
        return `
            <div class="client360-item client360-item--stack nsi-directory-card">
                <div class="nsi-directory-header">
                    <div>
                        <div class="client360-item-title">${nsiEscape(title)}</div>
                        <div class="client360-item-meta">Всего ${total} · показано ${items.length} · ${mismatchCount ? `${mismatchCount} требуют внимания` : 'синхронизация в порядке'}</div>
                    </div>
                    <div class="view-actions">
                        <button class="btn-secondary" onclick="queueNSIMasterEntitySync('${key}')">Повторить обмен</button>
                    </div>
                </div>
                <div class="client360-list" style="margin-top:12px;">
                    ${items.length ? items.map(item => {
                        const issueList = issueIndex[key]?.get(String(item.id || '')) || issueIndex[key]?.get(String(item.code || item.personnel_number || '')) || [];
                        return `
                            <div class="client360-item nsi-master-row ${issueList.length ? 'nsi-master-item--problem' : ''}">
                                <div>
                                    <div class="client360-item-title">${nsiEscape(titleText(key, item))}</div>
                                    <div class="client360-item-meta">${metaText(key, item)}</div>
                                    <div class="nsi-row-badges">
                                        ${formatNSICompactCode(item.code || item.personnel_number || item.bik || '', key === 'employees' ? 'Табельный' : key === 'bank_accounts' ? 'БИК' : 'Код')}
                                        ${formatNSISyncBadge(item.exchange_state, item.is_active)}
                                        ${item.external_sync_id ? `<span class="nsi-code-chip">1С: ${nsiEscape(item.external_sync_id)}</span>` : ''}
                                    </div>
                                    ${issueList.length ? `<div class="nsi-master-issue-list">${issueList.slice(0, 2).map(issue => `<span class="nsi-master-issue-chip">${formatNSIReconciliationIssue(issue)}</span>`).join('')}</div>` : ''}
                                </div>
                                <div class="client360-item-side nsi-master-actions">
                                    <button class="btn-secondary" style="padding:4px 10px;" onclick="editNSIMasterRecord('${key}', ${item.id})">Редактировать</button>
                                    <button class="btn-secondary" style="padding:4px 10px;" onclick="queueNSIMasterRecordSync('${key}', ${item.id})">Обмен с 1С</button>
                                    ${Number(item.is_active || 0) === 1 ? `<button class="btn-secondary" style="padding:4px 10px;" onclick="archiveNSIMasterRecord('${key}', ${item.id})">Архив</button>` : ''}
                                </div>
                            </div>
                        `;
                    }).join('') : '<div class="empty-state">По текущему фильтру записей нет.</div>'}
                </div>
            </div>
        `;
    }).join('');
    renderNSIReconciliation();
}

function syncNSIMasterForm() {
    const entityType = document.getElementById('nsiMasterEntityType')?.value || 'warehouses';
    document.querySelectorAll('[data-nsi-field]').forEach(node => {
        const allowed = (node.dataset.nsiField || '').split(',').includes(entityType);
        node.style.display = allowed ? '' : 'none';
    });
    const hint = document.getElementById('nsiMasterFormHint');
    if (hint) {
        hint.textContent = getNSIMasterFormHints()[entityType] || 'Заполни главную запись так, чтобы её можно было безопасно использовать в продажах, закупках, складе и 1С.';
    }
}

window.resetNSIMasterForm = resetNSIMasterForm;
window.syncNSIMasterForm = syncNSIMasterForm;
window.runNSIMasterReconciliation = runNSIMasterReconciliation;
window.syncInventoryDocumentForm = syncInventoryDocumentForm;
window.queueNSIMasterRecordSync = queueNSIMasterRecordSync;
window.queueNSIMasterEntitySync = queueNSIMasterEntitySync;
window.createInventoryAct = createInventoryAct;
window.createWarehouseQualityReport = createWarehouseQualityReport;
window.createRegradingDocument = createRegradingDocument;
window.applyStockBulkAction = applyStockBulkAction;
window.printStockEntity = printStockEntity;
window.deleteStockEntity = deleteStockEntity;
window.bulkStockActionDirect = bulkStockActionDirect;
