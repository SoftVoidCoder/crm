let eplSummaryDB = null;
let eplWaybillsDB = [];
let eplDriversDB = [];
let eplVehiclesDB = [];
let eplWaybillDetailDB = null;
let eplSyncQueueDB = [];
let eplSyncConflictsDB = [];
let eplSelectedWaybillId = 0;
let eplWaybillFilter = 'all';
let eplDriverFilter = 'all';
let eplVehicleFilter = 'all';
let accountingActiveTab = 'waybills';
let editingEplWaybillId = 0;
let editingEplDriverId = 0;
let editingEplVehicleId = 0;
let eplLockedWaybillId = 0;
const eplBulkSelections = window.eplBulkSelections || { waybills: new Set() };
window.eplBulkSelections = eplBulkSelections;

function getEplBulkSet() {
    if (!eplBulkSelections.waybills) eplBulkSelections.waybills = new Set();
    return eplBulkSelections.waybills;
}

function getSelectedEplWaybillIds() {
    return Array.from(getEplBulkSet()).map(Number).filter(Boolean);
}

function getSelectedEplWaybills() {
    const ids = new Set(getSelectedEplWaybillIds());
    return eplWaybillsDB.filter(item => ids.has(Number(item.id || 0)));
}

function pruneSelectedEplWaybills(rows) {
    const validIds = new Set((rows || []).map(item => Number(item.id || 0)).filter(Boolean));
    Array.from(getEplBulkSet()).forEach(id => {
        if (!validIds.has(Number(id))) getEplBulkSet().delete(id);
    });
}

function toggleEplWaybillSelection(waybillId, checked) {
    const id = Number(waybillId || 0);
    if (!id) return;
    if (checked) getEplBulkSet().add(id);
    else getEplBulkSet().delete(id);
    renderEplBulkToolbar();
}

function clearEplBulkSelection() {
    getEplBulkSet().clear();
    renderEplWaybillsTable();
}

function selectVisibleEplWaybills() {
    getVisibleEplWaybills().forEach(item => {
        const id = Number(item.id || 0);
        if (id) getEplBulkSet().add(id);
    });
    renderEplWaybillsTable();
}

function renderEplBulkCheckbox(waybillId) {
    const id = Number(waybillId || 0);
    const checked = getEplBulkSet().has(id) ? 'checked' : '';
    return `<input type="checkbox" class="bulk-row-checkbox" ${checked} aria-label="Выбрать ЭПЛ" onchange="toggleEplWaybillSelection(${id}, this.checked)">`;
}

function renderEplBulkToolbar() {
    const mount = document.getElementById('eplBulkActionsMount');
    if (!mount) return;
    const rows = getSelectedEplWaybills();
    const count = rows.length;
    mount.innerHTML = `
        <div class="bulk-actions-bar ${count ? 'is-active' : ''}">
            <div class="bulk-actions-count">Выбрано: ${count}</div>
            <button class="btn-secondary" onclick="selectVisibleEplWaybills()">Выбрать видимые</button>
            <select id="eplBulkIntegrationStatus" class="auth-input bulk-actions-select" ${count ? '' : 'disabled'}>
                <option value="ready">Готов к 1С</option>
                <option value="queued">В очередь</option>
                <option value="sent">Отправлен</option>
                <option value="accepted">Принят</option>
                <option value="error">Ошибка</option>
            </select>
            <button class="btn-secondary" onclick="applyEplBulkIntegrationStatus()" ${count ? '' : 'disabled'}>Статус 1С</button>
            <input id="eplBulkDispatcherName" class="auth-input bulk-actions-input" placeholder="Диспетчер / ответственный" ${count ? '' : 'disabled'}>
            <button class="btn-secondary" onclick="assignEplBulkDispatcher()" ${count ? '' : 'disabled'}>Назначить</button>
            <button class="btn-secondary" onclick="exportSelectedEplWaybills()" ${count ? '' : 'disabled'}>Экспорт</button>
            <button class="btn-secondary" onclick="clearEplBulkSelection()" ${count ? '' : 'disabled'}>Снять выбор</button>
        </div>
    `;
}

function eplWaybillBulkPayload(item, overrides = {}) {
    return {
        number: item.number || '',
        issue_date: item.issue_date || '',
        shift_date: item.shift_date || '',
        waybill_type: item.waybill_type || 'truck',
        project_id: Number(item.project_id || 0),
        client_id: Number(item.client_id || 0),
        contract_id: Number(item.contract_id || 0),
        object_id: Number(item.object_id || 0),
        driver_id: Number(item.driver_id || 0),
        vehicle_id: Number(item.vehicle_id || 0),
        route_text: item.route_text || '',
        cargo: item.cargo || '',
        departure_point: item.departure_point || '',
        destination_point: item.destination_point || '',
        dispatcher_name: item.dispatcher_name || '',
        medical_name: item.medical_name || '',
        mechanic_name: item.mechanic_name || '',
        planned_departure: item.planned_departure || '',
        actual_departure: item.actual_departure || '',
        actual_return: item.actual_return || '',
        odometer_out: Number(item.odometer_out || 0),
        odometer_in: Number(item.odometer_in || 0),
        fuel_issued: Number(item.fuel_issued || 0),
        fuel_returned: Number(item.fuel_returned || 0),
        status: item.status || 'draft',
        integration_status: item.integration_status || 'draft',
        operator_name: item.operator_name || '1С-ЭДО',
        external_document_id: item.external_document_id || '',
        notes: item.notes || '',
        last_sync_error: item.last_sync_error || '',
        expected_version: Number(item.row_version || 0),
        ...overrides,
    };
}

async function applyEplBulkIntegrationStatus() {
    const rows = getSelectedEplWaybills();
    const status = document.getElementById('eplBulkIntegrationStatus')?.value || '';
    if (!rows.length) return customAlert('Сначала выбери ЭПЛ.');
    if (!status) return customAlert('Выбери статус 1С.');
    for (const row of rows) {
        const res = await apiCall(`/epl/waybills/${row.id}/actions`, 'POST', {
            stage: 'integration',
            integration_status: status,
            external_document_id: row.external_document_id || '',
            last_sync_error: status === 'error' ? 'Массово отмечено как ошибка' : '',
            comment: 'Массовое действие из реестра ЭПЛ',
            signer_name: currentUser?.name || '',
            signed_at: getEplTodayRuDate(),
            expected_version: getCurrentEplExpectedVersion(row.id),
        });
        if (!res || res.error) return customAlert(`Не удалось обновить ЭПЛ ${row.number || row.id}.`);
    }
    getEplBulkSet().clear();
    await renderAccounting();
    showToast('1С ЭПЛ', `Статус 1С обновлён: ${rows.length}`);
}

async function assignEplBulkDispatcher() {
    const rows = getSelectedEplWaybills();
    const dispatcher = document.getElementById('eplBulkDispatcherName')?.value.trim() || '';
    if (!rows.length) return customAlert('Сначала выбери ЭПЛ.');
    if (!dispatcher) return customAlert('Укажи диспетчера или ответственного.');
    for (const row of rows) {
        const res = await apiCall(`/epl/waybills/${row.id}`, 'PUT', eplWaybillBulkPayload(row, { dispatcher_name: dispatcher }));
        if (!res || res.error) return customAlert(`Не удалось назначить ответственного для ЭПЛ ${row.number || row.id}.`);
    }
    getEplBulkSet().clear();
    await renderAccounting();
    showToast('1С ЭПЛ', `Ответственный назначен: ${rows.length}`);
}

const eplWaybillFieldMap = {
    number: 'eplWaybillNumber',
    issue_date: 'eplWaybillIssueDate',
    shift_date: 'eplWaybillShiftDate',
    waybill_type: 'eplWaybillType',
    project_id: 'eplWaybillProjectId',
    client_id: 'eplWaybillClientId',
    driver_id: 'eplWaybillDriverId',
    vehicle_id: 'eplWaybillVehicleId',
    route_text: 'eplWaybillRouteText',
    cargo: 'eplWaybillCargo',
    departure_point: 'eplWaybillDeparturePoint',
    destination_point: 'eplWaybillDestinationPoint',
    dispatcher_name: 'eplWaybillDispatcherName',
    medical_name: 'eplWaybillMedicalName',
    mechanic_name: 'eplWaybillMechanicName',
    planned_departure: 'eplWaybillPlannedDeparture',
    actual_departure: 'eplWaybillActualDeparture',
    actual_return: 'eplWaybillActualReturn',
    odometer_out: 'eplWaybillOdometerOut',
    odometer_in: 'eplWaybillOdometerIn',
    fuel_issued: 'eplWaybillFuelIssued',
    fuel_returned: 'eplWaybillFuelReturned',
    status: { id: 'eplWaybillStatus', statusField: true },
    integration_status: { id: 'eplWaybillIntegrationStatus', statusField: true },
    operator_name: 'eplWaybillOperatorName',
    external_document_id: 'eplWaybillExternalId',
    notes: 'eplWaybillNotes',
};
const eplWaybillDraftFieldIds = ['eplWaybillNumber', 'eplWaybillIssueDate', 'eplWaybillShiftDate', 'eplWaybillType', 'eplWaybillProjectId', 'eplWaybillClientId', 'eplWaybillDriverId', 'eplWaybillVehicleId', 'eplWaybillRouteText', 'eplWaybillCargo', 'eplWaybillDeparturePoint', 'eplWaybillDestinationPoint', 'eplWaybillDispatcherName', 'eplWaybillMedicalName', 'eplWaybillMechanicName', 'eplWaybillPlannedDeparture', 'eplWaybillActualDeparture', 'eplWaybillActualReturn', 'eplWaybillOdometerOut', 'eplWaybillOdometerIn', 'eplWaybillFuelIssued', 'eplWaybillFuelReturned', 'eplWaybillStatus', 'eplWaybillIntegrationStatus', 'eplWaybillOperatorName', 'eplWaybillExternalId', 'eplWaybillNotes'];

function bindEplWaybillDraftAutosave() {
    if (typeof bindFormDraftAutosave !== 'function') return;
    bindFormDraftAutosave('epl_waybill', {
        formId: 'eplWaybillForm',
        fieldIds: eplWaybillDraftFieldIds,
        entityType: 'epl_waybill',
        title: 'Черновик ЭПЛ',
        sourceView: 'accounting',
        shouldSave: () => !editingEplWaybillId,
        shouldRestore: () => !editingEplWaybillId,
    });
}

function bindEplSmartHints() {
    if (typeof bindSmartFieldHints !== 'function') return;
    bindSmartFieldHints('eplWaybillForm', [
        {
            field: 'eplWaybillIssueDate',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'Дата оформления нужна в формате дд.мм.гггг.' },
        },
        {
            field: 'eplWaybillShiftDate',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'Дата рейса нужна в формате дд.мм.гггг.' },
        },
        {
            field: 'eplWaybillClientId',
            validate: value => Number(value || 0) === 0
                ? { tone: 'hint', message: 'Можно оставить без контрагента, но с клиентом ЭПЛ проще найти в досье.' }
                : null,
        },
    ]);
}

const eplDriverFieldMap = {
    full_name: 'eplDriverFullName',
    personnel_number: 'eplDriverPersonnelNumber',
    license_number: 'eplDriverLicenseNumber',
    license_category: 'eplDriverLicenseCategory',
    phone: 'eplDriverPhone',
    medical_valid_to: 'eplDriverMedicalValidTo',
    signature_profile: 'eplDriverSignatureProfile',
    status: { id: 'eplDriverStatus', statusField: true },
    comment: 'eplDriverComment',
};

const eplVehicleFieldMap = {
    registration_no: 'eplVehicleRegistrationNo',
    garage_number: 'eplVehicleGarageNumber',
    brand: 'eplVehicleBrand',
    model: 'eplVehicleModel',
    trailer_registration: 'eplVehicleTrailerRegistration',
    odometer: 'eplVehicleOdometer',
    carrying_capacity: 'eplVehicleCarryingCapacity',
    diagnostic_valid_to: 'eplVehicleDiagnosticValidTo',
    insurance_valid_to: 'eplVehicleInsuranceValidTo',
    status: { id: 'eplVehicleStatus', statusField: true },
    comment: 'eplVehicleComment',
};

async function applyAccountingFieldPermissions() {
    if (typeof applyFieldPermissionsWithFeedback === 'function') {
        await Promise.all([
            applyFieldPermissionsWithFeedback('accounting', 'epl_waybill', eplWaybillFieldMap, 'eplWaybillPolicyBanner'),
            applyFieldPermissionsWithFeedback('accounting', 'epl_driver', eplDriverFieldMap, 'eplDriverPolicyBanner'),
            applyFieldPermissionsWithFeedback('accounting', 'epl_vehicle', eplVehicleFieldMap, 'eplVehiclePolicyBanner'),
        ]);
    } else if (typeof applyFieldPermissionsToForm === 'function') {
        applyFieldPermissionsToForm('accounting', 'epl_waybill', eplWaybillFieldMap);
        applyFieldPermissionsToForm('accounting', 'epl_driver', eplDriverFieldMap);
        applyFieldPermissionsToForm('accounting', 'epl_vehicle', eplVehicleFieldMap);
    }
}

function eplEscapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getEplTodayRuDate() {
    const now = new Date();
    return `${String(now.getDate()).padStart(2, '0')}.${String(now.getMonth() + 1).padStart(2, '0')}.${now.getFullYear()}`;
}

function parseEplRuDate(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    const match = text.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?$/);
    if (!match) return null;
    const [, dd, mm, yyyy, hh = '00', min = '00'] = match;
    const date = new Date(Number(yyyy), Number(mm) - 1, Number(dd), Number(hh), Number(min), 0, 0);
    return Number.isNaN(date.getTime()) ? null : date;
}

function isEplDateExpiring(value, days = 30) {
    const date = parseEplRuDate(value);
    if (!date) return false;
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const threshold = new Date(now);
    threshold.setDate(threshold.getDate() + Number(days || 0));
    return date <= threshold;
}

function eplStatusLabel(status) {
    const map = {
        draft: 'Черновик',
        ready: 'Готов к выпуску',
        on_route: 'На линии',
        returned: 'Возврат',
        closed: 'Закрыт',
    };
    return map[status] || status || 'Без статуса';
}

function eplStatusClass(status) {
    if (status === 'closed') return 'status-completed';
    if (status === 'on_route') return 'status-active';
    if (status === 'returned') return 'status-active';
    return 'status-archived';
}

function eplIntegrationLabel(status) {
    const map = {
        draft: 'Черновик',
        collecting: 'Сбор титулов',
        ready: 'Готов к 1С',
        queued: 'В очереди',
        sent: 'Отправлен',
        accepted: 'Принят',
        error: 'Ошибка',
    };
    return map[status] || status || 'Черновик';
}

function eplIntegrationClass(status) {
    if (status === 'accepted') return 'status-completed';
    if (status === 'ready' || status === 'queued' || status === 'sent') return 'status-active';
    if (status === 'error') return 'status-overdue';
    return 'status-archived';
}

function eplStageLabel(stage) {
    const map = {
        medical_pretrip: 'Предрейсовый медосмотр',
        mechanic_pretrip: 'Предрейсовый техконтроль',
        dispatcher_departure: 'Выезд на линию',
        dispatcher_return: 'Возврат с линии',
        medical_posttrip: 'Послерейсовый медосмотр',
        mechanic_posttrip: 'Послерейсовый техконтроль',
        integration: 'Интеграция',
    };
    return map[stage] || stage || 'Этап';
}

function eplDriverStatusLabel(status) {
    const map = {
        active: 'Активен',
        vacation: 'Отпуск',
        blocked: 'Заблокирован',
        archived: 'Архив',
    };
    return map[status] || status || 'Без статуса';
}

function eplVehicleStatusLabel(status) {
    const map = {
        active: 'Активно',
        repair: 'Ремонт',
        reserve: 'Резерв',
        archived: 'Архив',
    };
    return map[status] || status || 'Без статуса';
}

function eplSyncStateLabel(state) {
    const map = {
        draft: 'Черновик',
        queued: 'В очереди',
        retry: 'Повтор',
        processing: 'Обработка',
        sent: 'Отправлен',
        accepted: 'Принят',
        failed: 'Ошибка',
        conflict: 'Конфликт',
    };
    return map[state] || state || 'Без статуса';
}

function eplSyncStateClass(state) {
    if (['sent', 'accepted'].includes(state)) return 'status-completed';
    if (['queued', 'retry', 'processing'].includes(state)) return 'status-active';
    if (['failed', 'conflict'].includes(state)) return 'status-overdue';
    return 'status-archived';
}

function formatEplTimestamp(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return '—';
    const date = new Date(value * 1000);
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('ru-RU');
}

function getEplWaybillById(waybillId) {
    return eplWaybillsDB.find(item => Number(item.id) === Number(waybillId)) || null;
}

function getCurrentEplExpectedVersion(forcedWaybillId = 0) {
    const waybillId = Number(forcedWaybillId || eplSelectedWaybillId || editingEplWaybillId || 0);
    if (!waybillId) return 0;
    const detailVersion = Number(eplWaybillDetailDB?.waybill?.id) === waybillId
        ? Number(eplWaybillDetailDB?.waybill?.row_version || 0)
        : 0;
    if (detailVersion) return detailVersion;
    return Number(getEplWaybillById(waybillId)?.row_version || 0);
}

async function releaseEplWaybillLock(waybillId = 0, silent = true) {
    const targetId = Number(waybillId || eplLockedWaybillId || 0);
    if (!targetId) return true;
    const res = await apiCall(`/epl/waybills/${targetId}/unlock`, 'POST');
    if (!res || res.error) {
        if (!silent) customAlert(res?.message || 'Не удалось освободить блокировку карточки ЭПЛ.');
        return false;
    }
    if (Number(eplLockedWaybillId) === targetId) eplLockedWaybillId = 0;
    return true;
}

window.addEventListener('pagehide', () => {
    const targetId = Number(eplLockedWaybillId || 0);
    if (!targetId) return;
    fetch(`/api/epl/waybills/${targetId}/unlock`, {
        method: 'POST',
        credentials: 'same-origin',
        keepalive: true,
    }).catch(() => {});
    eplLockedWaybillId = 0;
});

async function processEplSyncQueue() {
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('accounting', 'epl_waybill', 'sync_1c');
        if (!guard.allowed) return;
    }
    const res = await apiCall('/epl/sync_queue/process?limit=20', 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось обработать очередь 1С по ЭПЛ.');
    await renderAccounting();
    if (eplSelectedWaybillId) await openEplWaybillDetail(eplSelectedWaybillId);
    showToast('1С ЭПЛ', `Очередь обработана: ${Number(res.success || 0)} успешно, ${Number(res.failed || 0)} с проблемой`);
}

async function retryEplSync(syncId) {
    const res = await apiCall(`/epl/sync_queue/${syncId}/retry`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось поставить синк на повтор.');
    await renderAccounting();
    if (eplSelectedWaybillId) await openEplWaybillDetail(eplSelectedWaybillId);
    showToast('1С ЭПЛ', 'Повторная отправка поставлена в очередь');
}

async function replaySelectedEplSync() {
    if (!eplSelectedWaybillId) return customAlert('Сначала выбери карточку ЭПЛ.');
    let comment = await customPrompt('Коротко укажи причину повторной отправки или оставь поле пустым.', '');
    if (comment === null) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('accounting', 'epl_waybill', 'sync_1c', { reason: comment });
        if (!guard.allowed) return;
        comment = guard.reason || comment;
    }
    const res = await apiCall(`/epl/waybills/${eplSelectedWaybillId}/sync/replay`, 'POST', {
        expected_version: getCurrentEplExpectedVersion(),
        signer_name: currentUser?.name || '',
        signed_at: getEplTodayRuDate(),
        comment: (comment || '').trim(),
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось повторно отправить ЭПЛ.');
    await renderAccounting();
    await openEplWaybillDetail(eplSelectedWaybillId);
    showToast('1С ЭПЛ', 'Повторная отправка поставлена в очередь');
}

async function reopenSelectedEplWaybill() {
    if (!eplSelectedWaybillId) return customAlert('Сначала выбери карточку ЭПЛ.');
    let comment = await customPrompt('Напиши причину переоткрытия.', '');
    if (comment === null) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('accounting', 'epl_waybill', 'update', { statusName: 'reopen', reason: comment });
        if (!guard.allowed) return;
        comment = guard.reason || comment;
    }
    const res = await apiCall(`/epl/waybills/${eplSelectedWaybillId}/reopen`, 'POST', {
        expected_version: getCurrentEplExpectedVersion(),
        comment: (comment || '').trim(),
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось переоткрыть ЭПЛ.');
    await renderAccounting();
    await openEplWaybillDetail(eplSelectedWaybillId);
    showToast('1С ЭПЛ', 'Переоткрытие выполнено');
}

function accountingCanRead() {
    return currentPermissions.finance && currentPermissions.finance.includes('read');
}

function accountingCanCreate() {
    return currentPermissions.finance && currentPermissions.finance.includes('create');
}

function accountingCanUpdate() {
    return currentPermissions.finance && currentPermissions.finance.includes('update');
}

function accountingCanDelete() {
    return currentPermissions.finance && currentPermissions.finance.includes('delete');
}

function groupAccountingOptionalFields() {
    const groups = [
        {
            form: document.getElementById('eplWaybillForm'),
            ids: [
                'eplWaybillNumber', 'eplWaybillIssueDate',
                'eplWaybillDispatcherName', 'eplWaybillMedicalName',
                'eplWaybillMechanicName', 'eplWaybillActualDeparture', 'eplWaybillActualReturn',
                'eplWaybillOdometerOut', 'eplWaybillOdometerIn', 'eplWaybillFuelIssued',
                'eplWaybillFuelReturned', 'eplWaybillStatus', 'eplWaybillIntegrationStatus', 'eplWaybillOperatorName',
                'eplWaybillExternalId',
            ],
        },
        {
            form: document.getElementById('accountingDriversPanel')?.querySelector('.finance-form-grid'),
            ids: ['eplDriverSignatureProfile', 'eplDriverStatus'],
        },
        {
            form: document.getElementById('accountingVehiclesPanel')?.querySelector('.finance-form-grid'),
            ids: ['eplVehicleStatus'],
        },
    ];

    groups.forEach(({ form, ids }) => {
        if (!form) return;
        const existing = form.querySelector(':scope > .accounting-optional-fields');
        if (existing) {
            existing.hidden = true;
            form.querySelectorAll(':scope > div').forEach(wrapper => {
                if (wrapper.querySelector('.form-error') && !wrapper.querySelector('input, select, textarea')) {
                    wrapper.hidden = true;
                }
            });
            return;
        }
        const fields = ids.map(id => document.getElementById(id)).filter(Boolean);
        if (!fields.length) return;
        const details = document.createElement('details');
        details.className = 'accounting-optional-fields';
        details.hidden = true;
        const summary = document.createElement('summary');
        summary.textContent = 'Дополнительные данные';
        const grid = document.createElement('div');
        grid.className = 'accounting-optional-fields__grid';
        fields.forEach(field => {
            const wrapper = field.parentElement?.matches('.ui-date-field, .ui-client-picker, [data-field-wrap]') ? field.parentElement : field;
            grid.appendChild(wrapper);
        });
        details.append(summary, grid);
        form.appendChild(details);
        form.querySelectorAll(':scope > div').forEach(wrapper => {
            if (wrapper.querySelector('.form-error') && !wrapper.querySelector('input, select, textarea')) {
                wrapper.hidden = true;
            }
        });
    });

    const setStepCopy = (panelId, title, subtitle) => {
        const panel = document.getElementById(panelId);
        const heading = panel?.querySelector('.ops-form-card .section-title');
        const description = panel?.querySelector('.ops-form-card .section-subtitle');
        if (heading) heading.textContent = title;
        if (description) description.textContent = subtitle;
    };
    setStepCopy(
        'accountingDriversPanel',
        'Шаг 1. Водитель',
        'Укажите ФИО, водительское удостоверение и срок медицинского допуска.'
    );
    setStepCopy(
        'accountingVehiclesPanel',
        'Шаг 2. Транспорт',
        'Укажите госномер, марку и модель автомобиля.'
    );
    setStepCopy(
        'accountingWaybillsPanel',
        'Шаг 3. Путевой лист',
        'Выберите дату рейса, водителя и транспорт, затем укажите маршрут.'
    );

    const setListCopy = (panelId, title, subtitle) => {
        const panel = document.getElementById(panelId);
        const heading = panel?.querySelector('.ops-list-card .section-title');
        const description = panel?.querySelector('.ops-list-card .section-subtitle');
        if (heading) heading.textContent = title;
        if (description) description.textContent = subtitle;
    };
    setListCopy('accountingDriversPanel', 'Сохранённые водители', 'Откройте запись, если данные водителя нужно изменить.');
    setListCopy('accountingVehiclesPanel', 'Сохранённый транспорт', 'Откройте запись, если данные автомобиля нужно изменить.');
    setListCopy('accountingWaybillsPanel', 'Созданные ЭПЛ', 'Откройте карточку, чтобы продолжить оформление рейса.');

    const labelField = (form, id, label, { required = false, wide = false } = {}) => {
        const field = document.getElementById(id);
        if (!form || !field) return;
        if (field.closest('.accounting-optional-fields')) return;
        if (field.closest('.epl-form-field')) return;
        const directChild = [...form.children].find(child => child === field || child.contains(field));
        if (!directChild) return;
        let wrapper = directChild;
        if (directChild === field || directChild.matches('.ui-date-field, .ui-client-picker')) {
            wrapper = document.createElement('div');
            form.insertBefore(wrapper, directChild);
            wrapper.appendChild(directChild);
        }
        wrapper.classList.add('epl-form-field');
        if (wide) wrapper.classList.add('epl-form-field--wide');
        const caption = document.createElement('span');
        caption.className = 'epl-form-field__label';
        caption.textContent = `${label}${required ? ' *' : ''}`;
        wrapper.prepend(caption);
    };

    const driverForm = document.getElementById('accountingDriversPanel')?.querySelector('.finance-form-grid');
    [
        ['eplDriverFullName', 'ФИО водителя', { required: true }],
        ['eplDriverPersonnelNumber', 'Табельный номер'],
        ['eplDriverPhone', 'Телефон'],
        ['eplDriverLicenseNumber', 'Номер водительского удостоверения', { required: true }],
        ['eplDriverLicenseCategory', 'Категория', { required: true }],
        ['eplDriverMedicalValidTo', 'Медицинский допуск до', { required: true }],
        ['eplDriverComment', 'Комментарий', { wide: true }],
    ].forEach(([id, label, options]) => labelField(driverForm, id, label, options));

    const vehicleForm = document.getElementById('accountingVehiclesPanel')?.querySelector('.finance-form-grid');
    [
        ['eplVehicleRegistrationNo', 'Госномер', { required: true }],
        ['eplVehicleGarageNumber', 'Гаражный номер'],
        ['eplVehicleBrand', 'Марка', { required: true }],
        ['eplVehicleModel', 'Модель', { required: true }],
        ['eplVehicleTrailerRegistration', 'Прицеп / полуприцеп'],
        ['eplVehicleOdometer', 'Текущий пробег, км'],
        ['eplVehicleCarryingCapacity', 'Грузоподъёмность, т'],
        ['eplVehicleDiagnosticValidTo', 'Диагностика действует до'],
        ['eplVehicleInsuranceValidTo', 'Страховка действует до'],
        ['eplVehicleComment', 'Комментарий', { wide: true }],
    ].forEach(([id, label, options]) => labelField(vehicleForm, id, label, options));

    const waybillForm = document.getElementById('eplWaybillForm');
    [
        ['eplWaybillShiftDate', 'Дата рейса', { required: true }],
        ['eplWaybillType', 'Тип транспорта'],
        ['eplWaybillProjectId', 'Проект'],
        ['eplWaybillClientId', 'Клиент / контрагент'],
        ['eplWaybillDriverId', 'Водитель', { required: true }],
        ['eplWaybillVehicleId', 'Транспорт', { required: true }],
        ['eplWaybillDeparturePoint', 'Откуда'],
        ['eplWaybillDestinationPoint', 'Куда'],
        ['eplWaybillPlannedDeparture', 'Плановый выезд'],
        ['eplWaybillCargo', 'Груз / назначение рейса'],
        ['eplWaybillRouteText', 'Маршрут / задание', { required: true, wide: true }],
        ['eplWaybillNotes', 'Комментарий', { wide: true }],
    ].forEach(([id, label, options]) => labelField(waybillForm, id, label, options));
}

async function loadAccountingModuleData() {
    const [summary, drivers, vehicles, waybills, syncQueue, syncConflicts] = await Promise.all([
        apiCall('/epl/summary'),
        apiCall('/epl/drivers'),
        apiCall('/epl/vehicles'),
        apiCall('/epl/waybills'),
        apiCall('/epl/sync_queue?limit=120'),
        apiCall('/epl/sync_conflicts?limit=120'),
    ]);
    eplSummaryDB = summary && !summary.error ? summary : null;
    eplDriversDB = Array.isArray(drivers) ? drivers : [];
    eplVehiclesDB = Array.isArray(vehicles) ? vehicles : [];
    eplWaybillsDB = Array.isArray(waybills) ? waybills : [];
    eplSyncQueueDB = Array.isArray(syncQueue) ? syncQueue : [];
    eplSyncConflictsDB = Array.isArray(syncConflicts) ? syncConflicts : [];
    if (eplSelectedWaybillId && !eplWaybillsDB.some(item => Number(item.id) === Number(eplSelectedWaybillId))) {
        eplSelectedWaybillId = 0;
        eplWaybillDetailDB = null;
        eplLockedWaybillId = 0;
    }
}

function populateEplSelects() {
    const projectSelect = document.getElementById('eplWaybillProjectId');
    const clientSelect = document.getElementById('eplWaybillClientId');
    const driverSelect = document.getElementById('eplWaybillDriverId');
    const vehicleSelect = document.getElementById('eplWaybillVehicleId');
    if (projectSelect) {
        projectSelect.innerHTML = `<option value="0">Без проекта</option>${projectsDB.map(project => `
            <option value="${project.id}">${eplEscapeHtml(project.contract || 'Без договора')} · ${eplEscapeHtml(project.name || 'Проект')}</option>
        `).join('')}`;
    }
    if (clientSelect) {
        clientSelect.innerHTML = `<option value="0">Без контрагента</option>${clientsDB
            .slice()
            .sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ru'))
            .map(client => `<option value="${client.id}">${eplEscapeHtml(client.name || 'Контрагент')}</option>`)
            .join('')}`;
    }
    if (driverSelect) {
        driverSelect.innerHTML = `<option value="0">Выбери водителя</option>${eplDriversDB
            .map(driver => `<option value="${driver.id}">${eplEscapeHtml(driver.full_name || 'Водитель')}</option>`)
            .join('')}`;
    }
    if (vehicleSelect) {
        vehicleSelect.innerHTML = `<option value="0">Выбери ТС</option>${eplVehiclesDB
            .map(vehicle => {
                const label = vehicle.registration_no || [vehicle.brand, vehicle.model].filter(Boolean).join(' ') || vehicle.garage_number || 'ТС';
                return `<option value="${vehicle.id}">${eplEscapeHtml(label)}</option>`;
            })
            .join('')}`;
    }
}

function resetEplWaybillForm(options = {}) {
    editingEplWaybillId = 0;
    const defaults = {
        eplWaybillNumber: '',
        eplWaybillIssueDate: getEplTodayRuDate(),
        eplWaybillShiftDate: getEplTodayRuDate(),
        eplWaybillType: 'truck',
        eplWaybillProjectId: '0',
        eplWaybillClientId: '0',
        eplWaybillDriverId: '0',
        eplWaybillVehicleId: '0',
        eplWaybillRouteText: '',
        eplWaybillCargo: '',
        eplWaybillDeparturePoint: '',
        eplWaybillDestinationPoint: '',
        eplWaybillDispatcherName: currentUser?.name || '',
        eplWaybillMedicalName: '',
        eplWaybillMechanicName: '',
        eplWaybillPlannedDeparture: '',
        eplWaybillActualDeparture: '',
        eplWaybillActualReturn: '',
        eplWaybillOdometerOut: '',
        eplWaybillOdometerIn: '',
        eplWaybillFuelIssued: '',
        eplWaybillFuelReturned: '',
        eplWaybillStatus: 'draft',
        eplWaybillIntegrationStatus: 'draft',
        eplWaybillOperatorName: '1С-ЭДО',
        eplWaybillExternalId: '',
        eplWaybillNotes: '',
    };
    Object.entries(defaults).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    if (!options.keepDraft && typeof clearFormDraft === 'function') clearFormDraft('epl_waybill');
}

function resetEplDriverForm() {
    editingEplDriverId = 0;
    const defaults = {
        eplDriverFullName: '',
        eplDriverPersonnelNumber: '',
        eplDriverLicenseNumber: '',
        eplDriverLicenseCategory: '',
        eplDriverPhone: '',
        eplDriverMedicalValidTo: '',
        eplDriverSignatureProfile: 'УНЭП',
        eplDriverStatus: 'active',
        eplDriverComment: '',
    };
    Object.entries(defaults).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
}

function resetEplVehicleForm() {
    editingEplVehicleId = 0;
    const defaults = {
        eplVehicleRegistrationNo: '',
        eplVehicleGarageNumber: '',
        eplVehicleBrand: '',
        eplVehicleModel: '',
        eplVehicleTrailerRegistration: '',
        eplVehicleOdometer: '',
        eplVehicleCarryingCapacity: '',
        eplVehicleDiagnosticValidTo: '',
        eplVehicleInsuranceValidTo: '',
        eplVehicleStatus: 'active',
        eplVehicleComment: '',
    };
    Object.entries(defaults).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
}

function switchAccountingTab(tabName) {
    if (accountingActiveTab === 'waybills' && tabName !== 'waybills' && eplLockedWaybillId) {
        releaseEplWaybillLock(eplLockedWaybillId, true);
    }
    accountingActiveTab = tabName;
    const tabs = ['waybills', 'drivers', 'vehicles', 'integration'];
    tabs.forEach(tab => {
        const btn = document.getElementById(`accountingTab${tab.charAt(0).toUpperCase()}${tab.slice(1)}`);
        const panel = document.getElementById(`accounting${tab.charAt(0).toUpperCase()}${tab.slice(1)}Panel`);
        if (btn) btn.classList.toggle('active', tab === tabName);
        if (panel) panel.style.display = tab === tabName ? 'block' : 'none';
    });
    const hint = document.getElementById('accountingStepHint');
    if (hint) {
        hint.textContent = tabName === 'drivers'
            ? 'Шаг 1. Заполните данные водителя и его действующие допуски.'
            : tabName === 'vehicles'
                ? 'Шаг 2. Заполните основные данные и документы транспорта.'
                : 'Шаг 3. Свяжите водителя и транспорт с рейсом, заполните маршрут и сохраните ЭПЛ.';
    }
    if (tabName === 'waybills' && !eplWaybillDetailDB && eplWaybillsDB.length) {
        ensureEplWaybillDetail();
    }
    if (tabName === 'integration') {
        renderIntegrationPanel();
    }
}

function setEplWaybillFilter(filter) {
    eplWaybillFilter = filter;
    renderEplWaybillsTable();
}

function updateEplWaybillFilterButtons() {
    const map = {
        all: 'eplFilterAllBtn',
        on_route: 'eplFilterOnRouteBtn',
        ready: 'eplFilterReadyBtn',
        blocked: 'eplFilterBlockedBtn',
    };
    Object.values(map).forEach(id => document.getElementById(id)?.classList.remove('is-filter-active'));
    document.getElementById(map[eplWaybillFilter] || map.all)?.classList.add('is-filter-active');
}

function registerEplSavedFilters() {
    if (typeof registerWorkbenchSavedFilterScope !== 'function') return;
    registerWorkbenchSavedFilterScope('accounting_epl', {
        mountId: 'eplSavedFiltersMount',
        defaultTitle: eplWaybillFilter === 'blocked' ? 'Проблемные ЭПЛ' : 'Мой фильтр ЭПЛ',
        getPayload: () => ({
            eplWaybillFilter,
            query: document.getElementById('searchInput')?.value || '',
        }),
        applyPayload: payload => {
            eplWaybillFilter = payload.eplWaybillFilter || 'all';
            const searchInput = document.getElementById('searchInput');
            if (searchInput) searchInput.value = payload.query || '';
            renderEplWaybillsTable();
        },
        presets: [
            { id: 'eplFilterAllBtn', key: 'all', label: 'Все', payload: () => ({ eplWaybillFilter: 'all', query: document.getElementById('searchInput')?.value || '' }) },
            { id: 'eplFilterOnRouteBtn', key: 'on_route', label: 'На линии', payload: () => ({ eplWaybillFilter: 'on_route', query: document.getElementById('searchInput')?.value || '' }) },
            { id: 'eplFilterReadyBtn', key: 'ready', label: 'Готовы', payload: () => ({ eplWaybillFilter: 'ready', query: document.getElementById('searchInput')?.value || '' }) },
            { id: 'eplFilterBlockedBtn', key: 'blocked', label: 'Проблемные', payload: () => ({ eplWaybillFilter: 'blocked', query: document.getElementById('searchInput')?.value || '' }) },
        ],
        updateState: updateEplWaybillFilterButtons,
    });
}

function setEplDriverFilter(filter) {
    eplDriverFilter = filter;
    renderEplDriversTable();
}

function setEplVehicleFilter(filter) {
    eplVehicleFilter = filter;
    renderEplVehiclesTable();
}

function getVisibleEplWaybills() {
    const query = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
    return eplWaybillsDB.filter(item => {
        const byFilter = eplWaybillFilter === 'all'
            || (eplWaybillFilter === 'blocked' && Array.isArray(item.missing_stages) && item.missing_stages.length)
            || item.status === eplWaybillFilter;
        if (!byFilter) return false;
        if (!query) return true;
        const haystack = [
            item.number,
            item.driver_name,
            item.vehicle_label,
            item.route_text,
            item.project_label,
            item.client_label,
            item.integration_status,
        ].join(' ').toLowerCase();
        return haystack.includes(query);
    });
}

function getVisibleEplDrivers() {
    const query = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
    return eplDriversDB.filter(item => {
        const byFilter = eplDriverFilter === 'all'
            || (eplDriverFilter === 'expiring' && isEplDateExpiring(item.medical_valid_to, 30))
            || item.status === eplDriverFilter;
        if (!byFilter) return false;
        if (!query) return true;
        const haystack = [
            item.full_name,
            item.personnel_number,
            item.license_number,
            item.phone,
            item.status,
        ].join(' ').toLowerCase();
        return haystack.includes(query);
    });
}

function getVisibleEplVehicles() {
    const query = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
    return eplVehiclesDB.filter(item => {
        const byFilter = eplVehicleFilter === 'all'
            || (eplVehicleFilter === 'expiring' && isEplDateExpiring(item.diagnostic_valid_to, 30))
            || item.status === eplVehicleFilter;
        if (!byFilter) return false;
        if (!query) return true;
        const haystack = [
            item.registration_no,
            item.garage_number,
            item.brand,
            item.model,
            item.status,
        ].join(' ').toLowerCase();
        return haystack.includes(query);
    });
}

function renderAccountingMetrics() {
    const target = document.getElementById('eplMetricsGrid');
    if (!target) return;
    const metrics = eplSummaryDB?.metrics || {};
    target.innerHTML = `
        <div class="metric-card"><div class="metric-title">Всего ЭПЛ</div><div class="metric-value">${metrics.waybills_total || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">На линии</div><div class="metric-value">${metrics.on_route || 0}</div></div>
        <div class="metric-card success"><div class="metric-title">Готовы к 1С</div><div class="metric-value">${metrics.ready_for_1c || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Проблемные</div><div class="metric-value">${metrics.blocked || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Активных водителей</div><div class="metric-value">${metrics.drivers_active || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Активных ТС</div><div class="metric-value">${metrics.vehicles_active || 0}</div></div>
    `;
}

function renderAccountingPulse() {
    const recentTarget = document.getElementById('eplRecentList');
    const alertsTarget = document.getElementById('eplAlertsDigest');
    if (recentTarget) {
        const rows = Array.isArray(eplSummaryDB?.recent) ? eplSummaryDB.recent : [];
        recentTarget.innerHTML = rows.length ? rows.map(item => `
            <div class="accounting-log-item">
                <div class="finance-row-title">${eplEscapeHtml(item.number || 'ЭПЛ')} · ${eplEscapeHtml(item.driver_name || 'Без водителя')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(item.shift_date || 'Без даты')} · ${eplEscapeHtml(item.route_text || 'Маршрут не указан')}</div>
                <div class="accounting-inline-badges">
                    <span class="status-badge ${eplStatusClass(item.status)}">${eplEscapeHtml(eplStatusLabel(item.status))}</span>
                    <span class="status-badge ${eplIntegrationClass(item.integration_status)}">${eplEscapeHtml(eplIntegrationLabel(item.integration_status))}</span>
                </div>
                <div class="accounting-action-row" style="margin-top:8px;">
                    <button class="btn-secondary" onclick="openEplWaybillDetail(${item.id}); switchAccountingTab('waybills')">Открыть ЭПЛ</button>
                </div>
            </div>
        `).join('') : '<div class="empty-state">Последних ЭПЛ пока нет.</div>';
    }
    if (alertsTarget) {
        const rows = Array.isArray(eplSummaryDB?.alerts) ? eplSummaryDB.alerts : [];
        alertsTarget.innerHTML = rows.length ? rows.map(item => `
            <div class="accounting-log-item ${item.level === 'danger' ? 'accounting-log-item--danger' : ''}">
                <div class="finance-row-title">${eplEscapeHtml(item.title || 'Сигнал')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(item.text || '')}</div>
            </div>
        `).join('') : '<div class="empty-state">Критичных сигналов нет.</div>';
    }
}

function editEplWaybill(waybillId) {
    const item = eplWaybillsDB.find(row => Number(row.id) === Number(waybillId));
    if (!item) return;
    editingEplWaybillId = Number(waybillId);
    document.getElementById('eplWaybillNumber').value = item.number || '';
    document.getElementById('eplWaybillIssueDate').value = item.issue_date || '';
    document.getElementById('eplWaybillShiftDate').value = item.shift_date || '';
    document.getElementById('eplWaybillType').value = item.waybill_type || 'truck';
    document.getElementById('eplWaybillProjectId').value = String(item.project_id || 0);
    document.getElementById('eplWaybillClientId').value = String(item.client_id || 0);
    document.getElementById('eplWaybillDriverId').value = String(item.driver_id || 0);
    document.getElementById('eplWaybillVehicleId').value = String(item.vehicle_id || 0);
    document.getElementById('eplWaybillRouteText').value = item.route_text || '';
    document.getElementById('eplWaybillCargo').value = item.cargo || '';
    document.getElementById('eplWaybillDeparturePoint').value = item.departure_point || '';
    document.getElementById('eplWaybillDestinationPoint').value = item.destination_point || '';
    document.getElementById('eplWaybillDispatcherName').value = item.dispatcher_name || '';
    document.getElementById('eplWaybillMedicalName').value = item.medical_name || '';
    document.getElementById('eplWaybillMechanicName').value = item.mechanic_name || '';
    document.getElementById('eplWaybillPlannedDeparture').value = item.planned_departure || '';
    document.getElementById('eplWaybillActualDeparture').value = item.actual_departure || '';
    document.getElementById('eplWaybillActualReturn').value = item.actual_return || '';
    document.getElementById('eplWaybillOdometerOut').value = item.odometer_out || '';
    document.getElementById('eplWaybillOdometerIn').value = item.odometer_in || '';
    document.getElementById('eplWaybillFuelIssued').value = item.fuel_issued || '';
    document.getElementById('eplWaybillFuelReturned').value = item.fuel_returned || '';
    document.getElementById('eplWaybillStatus').value = item.status || 'draft';
    document.getElementById('eplWaybillIntegrationStatus').value = item.integration_status || 'draft';
    document.getElementById('eplWaybillOperatorName').value = item.operator_name || '1С-ЭДО';
    document.getElementById('eplWaybillExternalId').value = item.external_document_id || '';
    document.getElementById('eplWaybillNotes').value = item.notes || '';
}

function duplicateEplWaybill(waybillId) {
    const item = eplWaybillsDB.find(row => Number(row.id) === Number(waybillId));
    if (!item) return;
    resetEplWaybillForm();
    document.getElementById('eplWaybillNumber').value = '';
    document.getElementById('eplWaybillIssueDate').value = getEplTodayRuDate();
    document.getElementById('eplWaybillShiftDate').value = getEplTodayRuDate();
    document.getElementById('eplWaybillType').value = item.waybill_type || 'truck';
    document.getElementById('eplWaybillProjectId').value = String(item.project_id || 0);
    document.getElementById('eplWaybillClientId').value = String(item.client_id || 0);
    document.getElementById('eplWaybillDriverId').value = String(item.driver_id || 0);
    document.getElementById('eplWaybillVehicleId').value = String(item.vehicle_id || 0);
    document.getElementById('eplWaybillRouteText').value = item.route_text || '';
    document.getElementById('eplWaybillCargo').value = item.cargo || '';
    document.getElementById('eplWaybillDeparturePoint').value = item.departure_point || '';
    document.getElementById('eplWaybillDestinationPoint').value = item.destination_point || '';
    document.getElementById('eplWaybillDispatcherName').value = item.dispatcher_name || currentUser?.name || '';
    document.getElementById('eplWaybillMedicalName').value = item.medical_name || '';
    document.getElementById('eplWaybillMechanicName').value = item.mechanic_name || '';
    document.getElementById('eplWaybillPlannedDeparture').value = item.planned_departure || '';
    document.getElementById('eplWaybillActualDeparture').value = '';
    document.getElementById('eplWaybillActualReturn').value = '';
    document.getElementById('eplWaybillOdometerOut').value = item.odometer_out || '';
    document.getElementById('eplWaybillOdometerIn').value = '';
    document.getElementById('eplWaybillFuelIssued').value = item.fuel_issued || '';
    document.getElementById('eplWaybillFuelReturned').value = '';
    document.getElementById('eplWaybillStatus').value = 'draft';
    document.getElementById('eplWaybillIntegrationStatus').value = 'draft';
    document.getElementById('eplWaybillOperatorName').value = item.operator_name || '1С-ЭДО';
    document.getElementById('eplWaybillExternalId').value = '';
    document.getElementById('eplWaybillNotes').value = item.notes ? `${item.notes} (копия)` : '';
    switchAccountingTab('waybills');
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#eplWaybillForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('eplWaybillNumber');
    showToast('1С ЭПЛ', 'Форма похожего путевого листа подготовлена');
}

function editEplDriver(driverId) {
    const item = eplDriversDB.find(row => Number(row.id) === Number(driverId));
    if (!item) return;
    editingEplDriverId = Number(driverId);
    document.getElementById('eplDriverFullName').value = item.full_name || '';
    document.getElementById('eplDriverPersonnelNumber').value = item.personnel_number || '';
    document.getElementById('eplDriverLicenseNumber').value = item.license_number || '';
    document.getElementById('eplDriverLicenseCategory').value = item.license_category || '';
    document.getElementById('eplDriverPhone').value = item.phone || '';
    document.getElementById('eplDriverMedicalValidTo').value = item.medical_valid_to || '';
    document.getElementById('eplDriverSignatureProfile').value = item.signature_profile || 'УНЭП';
    document.getElementById('eplDriverStatus').value = item.status || 'active';
    document.getElementById('eplDriverComment').value = item.comment || '';
}

function editEplVehicle(vehicleId) {
    const item = eplVehiclesDB.find(row => Number(row.id) === Number(vehicleId));
    if (!item) return;
    editingEplVehicleId = Number(vehicleId);
    document.getElementById('eplVehicleRegistrationNo').value = item.registration_no || '';
    document.getElementById('eplVehicleGarageNumber').value = item.garage_number || '';
    document.getElementById('eplVehicleBrand').value = item.brand || '';
    document.getElementById('eplVehicleModel').value = item.model || '';
    document.getElementById('eplVehicleTrailerRegistration').value = item.trailer_registration || '';
    document.getElementById('eplVehicleOdometer').value = item.odometer || '';
    document.getElementById('eplVehicleCarryingCapacity').value = item.carrying_capacity || '';
    document.getElementById('eplVehicleDiagnosticValidTo').value = item.diagnostic_valid_to || '';
    document.getElementById('eplVehicleInsuranceValidTo').value = item.insurance_valid_to || '';
    document.getElementById('eplVehicleStatus').value = item.status || 'active';
    document.getElementById('eplVehicleComment').value = item.comment || '';
}

async function openEplWaybillDetail(waybillId) {
    const targetId = Number(waybillId);
    if (eplLockedWaybillId && Number(eplLockedWaybillId) !== targetId) {
        await releaseEplWaybillLock(eplLockedWaybillId, true);
    }
    eplSelectedWaybillId = targetId;
    const data = await apiCall(`/epl/waybills/${eplSelectedWaybillId}`);
    eplWaybillDetailDB = data && !data.error ? data : null;
    if (eplWaybillDetailDB?.waybill && accountingCanUpdate()) {
        const lockRes = await apiCall(`/epl/waybills/${eplSelectedWaybillId}/lock`, 'POST');
        if (!lockRes?.error && lockRes?.waybill) {
            eplWaybillDetailDB.waybill = lockRes.waybill;
            eplLockedWaybillId = Number(lockRes.waybill.id || eplSelectedWaybillId);
        } else if (lockRes?.error === 'validation_error' && lockRes?.message) {
            customAlert(lockRes.message);
        }
    }
    renderSelectedEplWaybill();
}

async function ensureEplWaybillDetail() {
    const visibleRows = getVisibleEplWaybills();
    if (!visibleRows.length) {
        if (eplLockedWaybillId) await releaseEplWaybillLock(eplLockedWaybillId, true);
        eplSelectedWaybillId = 0;
        eplWaybillDetailDB = null;
        renderSelectedEplWaybill();
        return;
    }
    if (!eplSelectedWaybillId) {
        eplWaybillDetailDB = null;
        renderSelectedEplWaybill();
        return;
    }
    if (!eplWaybillDetailDB || Number(eplWaybillDetailDB.waybill?.id) !== Number(eplSelectedWaybillId)) {
        await openEplWaybillDetail(eplSelectedWaybillId);
        return;
    }
    const listRow = getEplWaybillById(eplSelectedWaybillId);
    if (listRow && Number(listRow.row_version || 0) !== Number(eplWaybillDetailDB.waybill?.row_version || 0)) {
        await openEplWaybillDetail(eplSelectedWaybillId);
        return;
    }
    renderSelectedEplWaybill();
}

function renderEplWaybillsTableLegacy() {
    const tbody = document.getElementById('eplWaybillsTable');
    const hint = document.getElementById('eplWaybillRegistryHint');
    if (!tbody) return;
    registerEplSavedFilters();
    updateEplWaybillFilterButtons();
    const rows = getVisibleEplWaybills();
    if (hint) {
        hint.innerText = rows.length
            ? `Показано путевых листов: ${rows.length}. Выделенный ЭПЛ можно сразу подписывать по этапам и переводить в контур 1С.`
            : 'По текущему фильтру путевых листов нет. Создай новую карточку или смени фильтр.';
    }
    if (!rows.length) {
        pruneSelectedEplWaybills(rows);
        renderEplBulkToolbar();
        tbody.innerHTML = '<tr><td colspan="7" class="nsi-empty-row">Путевых листов пока нет.</td></tr>';
        return;
    }
    pruneSelectedEplWaybills(rows);
    renderEplBulkToolbar();
    tbody.innerHTML = rows.map(item => `
        <tr>
            <td>${renderEplBulkCheckbox(item.id)}</td>
            <td>
                <div class="finance-row-title">${eplEscapeHtml(item.number || 'ЭПЛ')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(item.shift_date || '')} · <span class="status-badge ${eplStatusClass(item.status)}">${eplEscapeHtml(eplStatusLabel(item.status))}</span></div>
            </td>
            <td>
                <div class="finance-row-title">${eplEscapeHtml(item.driver_name || 'Водитель не выбран')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(item.vehicle_label || 'ТС не выбрано')}</div>
            </td>
            <td>
                <div class="finance-row-title">${eplEscapeHtml(item.route_text || 'Маршрут не указан')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(item.project_label || item.client_label || 'Без проекта и контрагента')}</div>
            </td>
            <td>
                <div class="finance-row-title">${item.readiness_percent || 0}%</div>
                <div class="finance-row-meta">${Array.isArray(item.missing_stages) && item.missing_stages.length ? eplEscapeHtml(item.missing_stages.slice(0, 2).join(', ')) : 'Титулы заполнены'}</div>
            </td>
            <td>
                <span class="status-badge ${eplIntegrationClass(item.integration_status)}">${eplEscapeHtml(eplIntegrationLabel(item.integration_status))}</span>
                <div class="finance-row-meta">${item.external_document_id ? eplEscapeHtml(item.external_document_id) : 'Идентификатор ещё не присвоен'}</div>
            </td>
            <td>
                <div style="display:flex; gap:6px; flex-wrap:wrap;">
                    ${typeof renderEntityFavoriteButton === 'function' ? renderEntityFavoriteButton('epl_waybill', item.id, item.number || `ЭПЛ #${item.id}`, `${item.driver_name || ''} · ${item.vehicle_label || ''} · ${item.shift_date || ''}`, 'accounting', 'renderEplWaybillsTable') : ''}
                    <button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="openEntityCard('epl_waybill', ${item.id})">Обзор</button>
                    <button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="openEplWaybillDetail(${item.id})">Карточка</button>
                    <button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="editEplWaybill(${item.id})">Ред.</button>
                    <button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="duplicateEplWaybill(${item.id})">Похожий</button>
                    ${item.qr_code ? `<button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="window.open('${item.qr_code}', '_blank')">QR</button>` : ''}
                    ${item.can_send_to_1c ? `<button class="btn-success" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="updateSelectedWaybillIntegration('queued', ${item.id})">В 1С</button>` : ''}
                    ${accountingCanDelete() ? `<button class="btn-danger" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="deleteEplWaybill(${item.id})">Удалить</button>` : ''}
                </div>
            </td>
        </tr>
    `).join('');
}

function renderEplDriversTableLegacy() {
    const tbody = document.getElementById('eplDriversTable');
    if (!tbody) return;
    const rows = getVisibleEplDrivers();
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="nsi-empty-row">Водители ещё не заведены.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(item => `
        <tr>
            <td><div class="finance-row-title">${eplEscapeHtml(item.full_name || 'Водитель')}</div><div class="finance-row-meta">${eplEscapeHtml(item.phone || 'Телефон не указан')}</div></td>
            <td>${eplEscapeHtml(item.license_number || '—')}<div class="finance-row-meta">${eplEscapeHtml(item.license_category || '')}</div></td>
            <td>${eplEscapeHtml(item.medical_valid_to || '—')}${isEplDateExpiring(item.medical_valid_to, 30) ? '<div class="finance-row-meta" style="color:#d54f4f;">Срок скоро истечёт</div>' : ''}</td>
            <td><span class="status-badge ${item.status === 'active' ? 'status-completed' : item.status === 'blocked' ? 'status-overdue' : 'status-archived'}">${eplEscapeHtml(eplDriverStatusLabel(item.status))}</span></td>
            <td><div style="display:flex; gap:6px; flex-wrap:wrap;"><button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="editEplDriver(${item.id})">Ред.</button>${accountingCanDelete() ? `<button class="btn-danger" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="deleteEplDriver(${item.id})">Удалить</button>` : ''}</div></td>
        </tr>
    `).join('');
}

function renderEplVehiclesTableLegacy() {
    const tbody = document.getElementById('eplVehiclesTable');
    if (!tbody) return;
    const rows = getVisibleEplVehicles();
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="nsi-empty-row">Транспорт ещё не заведён.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(item => `
        <tr>
            <td><div class="finance-row-title">${eplEscapeHtml(item.registration_no || item.garage_number || 'ТС')}</div><div class="finance-row-meta">${eplEscapeHtml([item.brand, item.model].filter(Boolean).join(' ') || 'Модель не указана')}</div></td>
            <td>${Number(item.odometer || 0).toLocaleString('ru-RU')}</td>
            <td>${eplEscapeHtml(item.diagnostic_valid_to || '—')}${isEplDateExpiring(item.diagnostic_valid_to, 30) ? '<div class="finance-row-meta" style="color:#d54f4f;">Пора продлить</div>' : ''}</td>
            <td><span class="status-badge ${item.status === 'active' ? 'status-completed' : item.status === 'repair' ? 'status-overdue' : 'status-archived'}">${eplEscapeHtml(eplVehicleStatusLabel(item.status))}</span></td>
            <td><div style="display:flex; gap:6px; flex-wrap:wrap;"><button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="editEplVehicle(${item.id})">Ред.</button>${accountingCanDelete() ? `<button class="btn-danger" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="deleteEplVehicle(${item.id})">Удалить</button>` : ''}</div></td>
        </tr>
    `).join('');
}

function getStageSignatureMeta(stageKey) {
    const signatures = Array.isArray(eplWaybillDetailDB?.signatures) ? eplWaybillDetailDB.signatures : [];
    return signatures.find(item => item.stage === stageKey) || null;
}

function eplStageOptionSet(stageKey) {
    if (stageKey.startsWith('medical')) return [{ value: 'passed', label: 'Допущен' }, { value: 'rejected', label: 'Не допущен' }];
    if (stageKey.startsWith('mechanic')) return [{ value: 'passed', label: 'Исправно' }, { value: 'rejected', label: 'Неисправно' }];
    if (stageKey === 'dispatcher_departure') return [{ value: 'departed', label: 'Выезд открыт' }, { value: 'blocked', label: 'Выезд отклонён' }];
    if (stageKey === 'dispatcher_return') return [{ value: 'returned', label: 'Возврат подтверждён' }, { value: 'incident', label: 'Инцидент / сбой' }];
    return [{ value: 'done', label: 'Готово' }];
}

function getEplStageBlockingMessage(waybill, stageKey) {
    const isDone = key => {
        const metaMap = {
            medical_pretrip: 'medical_pretrip_status',
            mechanic_pretrip: 'mechanic_pretrip_status',
            dispatcher_departure: 'dispatcher_departure_status',
            dispatcher_return: 'dispatcher_return_status',
            medical_posttrip: 'medical_posttrip_status',
            mechanic_posttrip: 'mechanic_posttrip_status',
        };
        const value = String(waybill?.[metaMap[key]] || '').toLowerCase();
        return ['passed', 'departed', 'returned', 'done', 'signed', 'completed', 'fit', 'approved', 'ok'].includes(value);
    };
    if (stageKey === 'mechanic_pretrip' && !isDone('medical_pretrip')) return 'Сначала проведи предрейсовый медосмотр.';
    if (stageKey === 'dispatcher_departure' && (!isDone('medical_pretrip') || !isDone('mechanic_pretrip'))) return 'Сначала закрой оба предрейсовых титула.';
    if (stageKey === 'dispatcher_return' && !isDone('dispatcher_departure')) return 'Сначала нужно зафиксировать выезд на линию.';
    if (stageKey === 'medical_posttrip' && !isDone('dispatcher_return')) return 'Послерейсовый медосмотр доступен только после возврата.';
    if (stageKey === 'mechanic_posttrip' && !isDone('medical_posttrip')) return 'Сначала закрой послерейсовый медосмотр.';
    return '';
}

function buildEplStageCard(stageKey, waybill) {
    const stageMap = {
        medical_pretrip: { statusKey: 'medical_pretrip_status', timeKey: 'medical_pretrip_at' },
        mechanic_pretrip: { statusKey: 'mechanic_pretrip_status', timeKey: 'mechanic_pretrip_at' },
        dispatcher_departure: { statusKey: 'dispatcher_departure_status', timeKey: 'dispatcher_departure_at' },
        dispatcher_return: { statusKey: 'dispatcher_return_status', timeKey: 'dispatcher_return_at' },
        medical_posttrip: { statusKey: 'medical_posttrip_status', timeKey: 'medical_posttrip_at' },
        mechanic_posttrip: { statusKey: 'mechanic_posttrip_status', timeKey: 'mechanic_posttrip_at' },
    };
    const config = stageMap[stageKey];
    const signatureMeta = getStageSignatureMeta(stageKey);
    const statusValue = waybill[config.statusKey] || signatureMeta?.status_mark || '';
    const timeValue = waybill[config.timeKey] || signatureMeta?.signed_at || '';
    const signerValue = signatureMeta?.signer_name || (stageKey.includes('medical')
        ? (waybill.medical_name || currentUser?.name || '')
        : stageKey.includes('mechanic')
            ? (waybill.mechanic_name || currentUser?.name || '')
            : (waybill.dispatcher_name || currentUser?.name || ''));
    const commentValue = signatureMeta?.comment || '';
    const blockMessage = getEplStageBlockingMessage(waybill, stageKey);
    const options = eplStageOptionSet(stageKey).map(item => `
        <option value="${item.value}" ${item.value === statusValue ? 'selected' : ''}>${eplEscapeHtml(item.label)}</option>
    `).join('');
    return `
        <div class="accounting-stage-card">
            <div class="accounting-stage-header">
                <div class="finance-row-title">${eplEscapeHtml(eplStageLabel(stageKey))}</div>
                <span class="status-badge ${statusValue ? 'status-completed' : 'status-archived'}">${eplEscapeHtml(statusValue || 'Не подписан')}</span>
            </div>
            <div class="accounting-stage-meta">Время: ${eplEscapeHtml(timeValue || 'Не отмечено')}</div>
            ${blockMessage ? `<div class="accounting-stage-warning">${eplEscapeHtml(blockMessage)}</div>` : ''}
            <div class="accounting-stage-form">
                <select id="eplStageStatus_${stageKey}" class="auth-input" style="margin:0;">${options}</select>
                <input id="eplStageTime_${stageKey}" class="auth-input" style="margin:0;" value="${eplEscapeHtml(timeValue || getEplTodayRuDate())}" placeholder="Дата / время">
                <input id="eplStageSigner_${stageKey}" class="auth-input" style="margin:0;" value="${eplEscapeHtml(signerValue)}" placeholder="Кто подписывает">
                <textarea id="eplStageComment_${stageKey}" class="auth-input" style="margin:0; min-height:76px; grid-column:1 / -1;" placeholder="Комментарий по титулу">${eplEscapeHtml(commentValue)}</textarea>
            </div>
            <div class="accounting-action-row">
                <button class="btn-secondary" onclick="markEplStage('${stageKey}')">Отметить</button>
            </div>
        </div>
    `;
}

function renderSelectedEplWaybillLegacy() {
    const title = document.getElementById('eplSelectedWaybillTitle');
    const body = document.getElementById('eplWaybillDetailBody');
    if (!title || !body) return;
    const detail = eplWaybillDetailDB;
    if (!detail || !detail.waybill) {
        title.innerText = 'Карточка титулов ЭПЛ';
        body.innerHTML = '<div class="empty-state">Выбери путевой лист в реестре, чтобы увидеть титулы, QR и журнал событий.</div>';
        return;
    }
    const waybill = detail.waybill;
    const signatures = Array.isArray(detail.signatures) ? detail.signatures : [];
    const syncQueue = Array.isArray(detail.sync_queue) ? detail.sync_queue : [];
    const syncHistory = Array.isArray(detail.sync_history) ? detail.sync_history : [];
    const syncConflicts = Array.isArray(detail.sync_conflicts) ? detail.sync_conflicts : [];
    const lockOwner = waybill.active_lock?.name || waybill.active_lock?.email || '';
    title.innerText = `ЭПЛ ${waybill.number || waybill.id}`;
    body.innerHTML = `
        <div class="finance-layout">
            <div class="surface-card surface-card--padded">
                <div class="section-title">${eplEscapeHtml(waybill.route_text || 'Маршрут не указан')}</div>
                <div class="section-subtitle">${eplEscapeHtml(waybill.driver_name || 'Водитель не выбран')} · ${eplEscapeHtml(waybill.vehicle_label || 'ТС не выбрано')}</div>
                <div class="accounting-stack" style="margin-top:14px;">
                    <div class="finance-row-meta">Дата рейса: ${eplEscapeHtml(waybill.shift_date || '—')}</div>
                    <div class="finance-row-meta">Выезд: ${eplEscapeHtml(waybill.actual_departure || waybill.planned_departure || '—')}</div>
                    <div class="finance-row-meta">Возврат: ${eplEscapeHtml(waybill.actual_return || '—')}</div>
                    <div class="finance-row-meta">Пробег: ${Number(waybill.mileage || 0).toLocaleString('ru-RU')} км</div>
                    <div class="finance-row-meta">Топливо: ${Number(waybill.fuel_issued || 0).toLocaleString('ru-RU')} / остаток ${Number(waybill.fuel_returned || 0).toLocaleString('ru-RU')}</div>
                    <div class="finance-row-meta">Внешний идентификатор: ${eplEscapeHtml(waybill.external_document_id || 'не присвоен')}</div>
                    <div class="finance-row-meta">Версия карточки: ${Number(waybill.row_version || 0)}</div>
                    ${lockOwner ? `<div class="finance-row-meta">Блокировка: ${eplEscapeHtml(lockOwner)} · ${eplEscapeHtml(formatEplTimestamp(waybill.active_lock?.at || 0))}</div>` : ''}
                </div>
            </div>
            <div class="surface-card surface-card--padded">
                <div class="section-title">QR и интеграция</div>
                <div class="section-subtitle">Готовность: ${waybill.readiness_percent || 0}% · ${eplEscapeHtml(eplIntegrationLabel(waybill.integration_status))} · Очередь: ${eplEscapeHtml(eplSyncStateLabel(waybill.sync_queue_state || 'draft'))}</div>
                <div class="accounting-stack" style="margin-top:14px;">
                    ${waybill.qr_code ? `<img class="accounting-qr-preview" src="${waybill.qr_code}" alt="QR">` : '<div class="empty-state">QR ещё не сформирован.</div>'}
                    ${waybill.last_sync_error ? `<div class="accounting-stage-warning">Ошибка 1С: ${eplEscapeHtml(waybill.last_sync_error)}</div>` : ''}
                    ${Array.isArray(waybill.missing_stages) && waybill.missing_stages.length ? `<div class="accounting-stage-warning">Не закрыты титулы: ${eplEscapeHtml(waybill.missing_stages.join(', '))}</div>` : ''}
                    ${waybill.sync_queue_state ? `<div class="finance-row-meta">Последняя очередь: ${eplEscapeHtml(eplSyncStateLabel(waybill.sync_queue_state))} · повторов ${Number(waybill.sync_retry_count || 0)} · ${eplEscapeHtml(formatEplTimestamp(waybill.sync_updated_at || 0))}</div>` : ''}
                    <div class="accounting-action-row">
                        <button class="btn-secondary" onclick="updateSelectedWaybillIntegration('ready')">Готов к 1С</button>
                        <button class="btn-secondary" onclick="updateSelectedWaybillIntegration('queued')">В очередь</button>
                        <button class="btn-secondary" onclick="updateSelectedWaybillIntegration('sent')">Отправлен</button>
                        <button class="btn-secondary" onclick="updateSelectedWaybillIntegration('accepted')">Принят</button>
                        <button class="btn-danger" onclick="updateSelectedWaybillIntegration('error')">Ошибка</button>
                        <button class="btn-secondary" onclick="processEplSyncQueue()">Обработать</button>
                        <button class="btn-secondary" onclick="replaySelectedEplSync()">Повторить</button>
                        <button class="btn-secondary" onclick="reopenSelectedEplWaybill()">Переоткрыть</button>
                    </div>
                </div>
            </div>
        </div>
        <div class="accounting-stage-grid">
            ${['medical_pretrip', 'mechanic_pretrip', 'dispatcher_departure', 'dispatcher_return', 'medical_posttrip', 'mechanic_posttrip'].map(stage => buildEplStageCard(stage, waybill)).join('')}
        </div>
        <div class="finance-layout">
            <div class="surface-card surface-card--padded">
                <div class="section-title">Журнал титулов и обмена</div>
                <div class="accounting-stack" style="margin-top:14px;">
                    ${signatures.length ? signatures.map(item => `
                        <div class="accounting-log-item">
                            <div class="finance-row-title">${eplEscapeHtml(eplStageLabel(item.stage))}</div>
                            <div class="finance-row-meta">${eplEscapeHtml(item.signer_role || 'Роль не указана')} · ${eplEscapeHtml(item.signer_name || 'Подписант не указан')} · ${eplEscapeHtml(item.signed_at || '—')}</div>
                            <div class="finance-row-meta">${eplEscapeHtml(item.status_mark || '')}${item.comment ? ` · ${eplEscapeHtml(item.comment)}` : ''}</div>
                        </div>
                    `).join('') : '<div class="empty-state">Журнал действий пока пуст.</div>'}
                </div>
            </div>
            <div class="surface-card surface-card--padded">
                <div class="section-title">Очередь 1С и восстановление</div>
                <div class="accounting-stack" style="margin-top:14px;">
                    ${syncQueue.length ? syncQueue.map(item => `
                        <div class="accounting-log-item">
                            <div class="finance-row-title"><span class="status-badge ${eplSyncStateClass(item.state)}">${eplEscapeHtml(eplSyncStateLabel(item.state))}</span></div>
                            <div class="finance-row-meta">Идентификатор очереди: ${Number(item.id || 0)} · повторов ${Number(item.retry_count || 0)} · ${eplEscapeHtml(formatEplTimestamp(item.updated_at))}</div>
                            ${item.last_error ? `<div class="finance-row-meta" style="color:#d54f4f;">${eplEscapeHtml(item.last_error)}</div>` : ''}
                            <div class="accounting-action-row" style="margin-top:10px;">
                                ${['failed', 'conflict', 'retry'].includes(item.state) ? `<button class="btn-secondary" onclick="retryEplSync(${item.id})">Повторить</button>` : ''}
                            </div>
                        </div>
                    `).join('') : '<div class="empty-state">Записей очереди по этой карточке пока нет.</div>'}
                    ${syncConflicts.length ? `<div class="accounting-stage-warning">Есть конфликты синхронизации: ${syncConflicts.length}</div>` : ''}
                    ${syncHistory.length ? syncHistory.slice(0, 8).map(item => `
                        <div class="accounting-log-item">
                            <div class="finance-row-title">${eplEscapeHtml(eplSyncStateLabel(item.state || 'log'))}</div>
                            <div class="finance-row-meta">${eplEscapeHtml(item.message || '')} · ${eplEscapeHtml(formatEplTimestamp(item.created_at))}</div>
                        </div>
                    `).join('') : '<div class="empty-state">История синхронизации пока пустая.</div>'}
                </div>
            </div>
        </div>
    `;
}

function renderEplDriversTable() {
    const tbody = document.getElementById('eplDriversTable');
    if (!tbody) return;
    const header = tbody.closest('table')?.querySelector('thead tr');
    if (header) header.innerHTML = '<th>Водитель</th><th>Удостоверение</th><th>Категория</th><th>Меддопуск до</th><th>Действие</th>';
    const rows = getVisibleEplDrivers();
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="nsi-empty-row">Водителей пока нет. Заполните форму слева.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(item => `
        <tr>
            <td><strong>${eplEscapeHtml(item.full_name || 'Водитель')}</strong></td>
            <td>${eplEscapeHtml(item.license_number || 'Не указано')}</td>
            <td>${eplEscapeHtml(item.license_category || 'Не указана')}</td>
            <td>${eplEscapeHtml(item.medical_valid_to || 'Не указано')}</td>
            <td><button class="btn-secondary" onclick="editEplDriver(${item.id})">Редактировать</button></td>
        </tr>
    `).join('');
}

function renderEplVehiclesTable() {
    const tbody = document.getElementById('eplVehiclesTable');
    if (!tbody) return;
    const header = tbody.closest('table')?.querySelector('thead tr');
    if (header) header.innerHTML = '<th>Госномер</th><th>Марка</th><th>Модель</th><th>Состояние</th><th>Действие</th>';
    const rows = getVisibleEplVehicles();
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="nsi-empty-row">Транспорта пока нет. Заполните форму слева.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(item => `
        <tr>
            <td><strong>${eplEscapeHtml(item.registration_no || item.garage_number || 'Транспорт')}</strong></td>
            <td>${eplEscapeHtml(item.brand || 'Не указана')}</td>
            <td>${eplEscapeHtml(item.model || 'Не указана')}</td>
            <td><span class="status-badge ${item.status === 'active' ? 'status-completed' : 'status-archived'}">${eplEscapeHtml(eplVehicleStatusLabel(item.status))}</span></td>
            <td><button class="btn-secondary" onclick="editEplVehicle(${item.id})">Редактировать</button></td>
        </tr>
    `).join('');
}

function renderEplWaybillsTable() {
    const tbody = document.getElementById('eplWaybillsTable');
    if (!tbody) return;
    const rows = getVisibleEplWaybills();
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="nsi-empty-row">Путевых листов пока нет. Заполните четыре основных поля слева.</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(item => `
        <tr>
            <td></td>
            <td><strong>${eplEscapeHtml(item.number || `ЭПЛ №${item.id}`)}</strong><div class="finance-row-meta">${eplEscapeHtml(item.shift_date || '')}</div></td>
            <td><strong>${eplEscapeHtml(item.driver_name || 'Водитель не выбран')}</strong><div class="finance-row-meta">${eplEscapeHtml(item.vehicle_label || 'Транспорт не выбран')}</div></td>
            <td>${eplEscapeHtml(item.route_text || 'Маршрут не указан')}</td>
            <td><span class="status-badge ${eplStatusClass(item.status)}">${eplEscapeHtml(eplStatusLabel(item.status))}</span></td>
            <td></td>
            <td><button class="btn-primary" onclick="openEplWaybillDetail(${item.id})">Открыть карточку</button></td>
        </tr>
    `).join('');
}

function eplCompactStageDone(waybill, stageKey) {
    const fieldMap = {
        medical_pretrip: 'medical_pretrip_status',
        mechanic_pretrip: 'mechanic_pretrip_status',
        dispatcher_departure: 'dispatcher_departure_status',
        dispatcher_return: 'dispatcher_return_status',
        medical_posttrip: 'medical_posttrip_status',
        mechanic_posttrip: 'mechanic_posttrip_status',
    };
    const value = String(waybill?.[fieldMap[stageKey]] || '').toLowerCase();
    return ['passed', 'departed', 'returned', 'done', 'signed', 'completed', 'fit', 'approved', 'ok'].includes(value);
}

function getEplCompactWorkStep(waybill) {
    if (!eplCompactStageDone(waybill, 'medical_pretrip') || !eplCompactStageDone(waybill, 'mechanic_pretrip')) return 'admission';
    if (!eplCompactStageDone(waybill, 'dispatcher_departure')) return 'departure';
    if (!eplCompactStageDone(waybill, 'dispatcher_return') || !eplCompactStageDone(waybill, 'medical_posttrip') || !eplCompactStageDone(waybill, 'mechanic_posttrip')) return 'return';
    return 'complete';
}

async function saveEplCompactStage(stage, statusValue) {
    const waybillId = Number(eplSelectedWaybillId || 0);
    if (!waybillId) return false;
    const result = await apiCall(`/epl/waybills/${waybillId}/actions`, 'POST', {
        stage,
        signer_name: currentUser?.name || 'Ответственный сотрудник',
        signed_at: getEplTodayRuDate(),
        status_value: statusValue,
        comment: '',
        expected_version: Number(eplWaybillDetailDB?.waybill?.row_version || 0),
    });
    if (!result || result.error) {
        await customAlert(result?.message || 'Не удалось сохранить этап ЭПЛ.');
        return false;
    }
    const fresh = await apiCall(`/epl/waybills/${waybillId}`);
    if (fresh && !fresh.error) eplWaybillDetailDB = fresh;
    return true;
}

async function completeEplCompactStep(stepName) {
    const sequences = {
        admission: [['medical_pretrip', 'passed'], ['mechanic_pretrip', 'passed']],
        departure: [['dispatcher_departure', 'departed']],
        return: [['dispatcher_return', 'returned'], ['medical_posttrip', 'passed'], ['mechanic_posttrip', 'passed']],
    };
    const sequence = sequences[stepName] || [];
    for (const [stage, statusValue] of sequence) {
        if (eplCompactStageDone(eplWaybillDetailDB?.waybill, stage)) continue;
        if (!await saveEplCompactStage(stage, statusValue)) return;
    }
    await renderAccounting();
    await openEplWaybillDetail(eplSelectedWaybillId);
    document.querySelector('.accounting-detail-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    showToast('ЭПЛ', 'Этап сохранён');
}

function editFullEplCard(waybillId) {
    const waybill = eplWaybillsDB.find(row => Number(row.id) === Number(waybillId));
    if (!waybill) return;
    editEplDriver(waybill.driver_id);
    editEplVehicle(waybill.vehicle_id);
    editEplWaybill(waybill.id);
    switchAccountingTab('drivers');
    document.querySelector('.accounting-quick-flow')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    showToast('ЭПЛ', 'Данные карточки открыты для редактирования');
}

function eplCardValue(value, fallback = 'Не указано') {
    const prepared = String(value ?? '').trim();
    return eplEscapeHtml(prepared || fallback);
}

function eplWaybillTypeLabel(value) {
    return ({ truck: 'Грузовой', passenger: 'Пассажирский', special: 'Спецтехника' })[value] || 'Не указан';
}

function renderSelectedEplWaybill() {
    const title = document.getElementById('eplSelectedWaybillTitle');
    const body = document.getElementById('eplWaybillDetailBody');
    if (!title || !body) return;
    const subtitle = title.closest('.section-header')?.querySelector('.section-subtitle');
    if (subtitle) subtitle.textContent = 'Основные данные и одно следующее действие по рейсу.';
    const waybill = eplWaybillDetailDB?.waybill;
    if (!waybill) {
        title.innerText = 'Карточка ЭПЛ';
        body.innerHTML = '<div class="empty-state">Создайте путевой лист или откройте его из списка.</div>';
        return;
    }

    const workStep = getEplCompactWorkStep(waybill);
    const stepInfo = {
        admission: { title: 'Подтвердить допуск к рейсу', text: 'Подтвердите медосмотр и исправность транспорта.', button: 'Подтвердить допуск' },
        departure: { title: 'Отметить выезд', text: 'Водитель и транспорт готовы. Зафиксируйте начало рейса.', button: 'Отметить выезд' },
        return: { title: 'Завершить рейс', text: 'После возвращения подтвердите возврат и закрытие осмотров.', button: 'Завершить рейс' },
        complete: { title: 'Рейс завершён', text: 'Все обязательные этапы ЭПЛ закрыты.', button: '' },
    }[workStep];
    const progress = [
        { key: 'admission', label: 'Допуск', done: workStep !== 'admission' },
        { key: 'departure', label: 'Выезд', done: ['return', 'complete'].includes(workStep) },
        { key: 'return', label: 'Возврат', done: workStep === 'complete' },
    ];
    const driver = eplDriversDB.find(item => Number(item.id) === Number(waybill.driver_id)) || {};
    const vehicle = eplVehiclesDB.find(item => Number(item.id) === Number(waybill.vehicle_id)) || {};
    const project = (Array.isArray(projectsDB) ? projectsDB : []).find(item => Number(item.id) === Number(waybill.project_id)) || {};
    const client = (Array.isArray(clientsDB) ? clientsDB : []).find(item => Number(item.id) === Number(waybill.client_id)) || {};
    const projectName = project.name || project.contract || '';
    const clientName = client.name || waybill.client_name || '';
    const odometer = Number(vehicle.odometer || 0);
    const capacity = Number(vehicle.carrying_capacity || 0);

    title.innerText = `Карточка ЭПЛ ${waybill.number || `№${waybill.id}`}`;
    body.innerHTML = `
        <div class="epl-result-card">
            <div class="epl-result-card__top">
                <div>
                    <span class="status-badge ${eplStatusClass(waybill.status)}">${eplEscapeHtml(eplStatusLabel(waybill.status))}</span>
                    <h2>${eplEscapeHtml(waybill.route_text || 'Маршрут не указан')}</h2>
                    <p>${eplCardValue(waybill.number, `ЭПЛ №${waybill.id}`)} · рейс ${eplCardValue(waybill.shift_date, 'без даты')}</p>
                </div>
                <button class="btn-secondary" onclick="editFullEplCard(${Number(waybill.id)})">Редактировать данные</button>
            </div>
            <div class="epl-result-card__facts">
                <div><span>Тип</span><strong>${eplEscapeHtml(eplWaybillTypeLabel(waybill.waybill_type))}</strong></div>
                <div><span>Дата рейса</span><strong>${eplEscapeHtml(waybill.shift_date || 'Не указана')}</strong></div>
                <div><span>Водитель</span><strong>${eplEscapeHtml(waybill.driver_name || driver.full_name || 'Не выбран')}</strong></div>
                <div><span>Транспорт</span><strong>${eplEscapeHtml(waybill.vehicle_label || vehicle.registration_no || 'Не выбран')}</strong></div>
                <div><span>Готовность</span><strong>${Number(waybill.readiness_percent || 0)}%</strong></div>
            </div>

            <div class="epl-card-sections">
                <section class="epl-card-section epl-card-section--wide">
                    <div class="epl-card-section__heading"><div><span>Шаг 3</span><h3>Маршрут и задание</h3></div></div>
                    <div class="epl-card-data-grid">
                        <div><span>Маршрут / задание</span><strong>${eplCardValue(waybill.route_text)}</strong></div>
                        <div><span>Груз / назначение</span><strong>${eplCardValue(waybill.cargo)}</strong></div>
                        <div><span>Откуда</span><strong>${eplCardValue(waybill.departure_point)}</strong></div>
                        <div><span>Куда</span><strong>${eplCardValue(waybill.destination_point)}</strong></div>
                        <div><span>Плановый выезд</span><strong>${eplCardValue(waybill.planned_departure)}</strong></div>
                        <div><span>Проект</span><strong>${eplCardValue(projectName, 'Без проекта')}</strong></div>
                        <div><span>Клиент / контрагент</span><strong>${eplCardValue(clientName, 'Не выбран')}</strong></div>
                        <div><span>Комментарий</span><strong>${eplCardValue(waybill.notes)}</strong></div>
                    </div>
                </section>

                <section class="epl-card-section">
                    <div class="epl-card-section__heading"><div><span>Шаг 1</span><h3>Водитель</h3></div></div>
                    <div class="epl-card-data-grid epl-card-data-grid--single">
                        <div><span>ФИО</span><strong>${eplCardValue(driver.full_name || waybill.driver_name)}</strong></div>
                        <div><span>Табельный номер</span><strong>${eplCardValue(driver.personnel_number)}</strong></div>
                        <div><span>Телефон</span><strong>${eplCardValue(driver.phone)}</strong></div>
                        <div><span>Удостоверение</span><strong>${eplCardValue(driver.license_number)}</strong></div>
                        <div><span>Категория</span><strong>${eplCardValue(driver.license_category)}</strong></div>
                        <div><span>Меддопуск до</span><strong>${eplCardValue(driver.medical_valid_to)}</strong></div>
                        <div><span>Комментарий</span><strong>${eplCardValue(driver.comment)}</strong></div>
                    </div>
                </section>

                <section class="epl-card-section">
                    <div class="epl-card-section__heading"><div><span>Шаг 2</span><h3>Транспорт</h3></div></div>
                    <div class="epl-card-data-grid epl-card-data-grid--single">
                        <div><span>Госномер</span><strong>${eplCardValue(vehicle.registration_no || waybill.vehicle_label)}</strong></div>
                        <div><span>Гаражный номер</span><strong>${eplCardValue(vehicle.garage_number)}</strong></div>
                        <div><span>Марка и модель</span><strong>${eplCardValue([vehicle.brand, vehicle.model].filter(Boolean).join(' '))}</strong></div>
                        <div><span>Прицеп</span><strong>${eplCardValue(vehicle.trailer_registration)}</strong></div>
                        <div><span>Текущий пробег</span><strong>${odometer ? `${odometer.toLocaleString('ru-RU')} км` : 'Не указан'}</strong></div>
                        <div><span>Грузоподъёмность</span><strong>${capacity ? `${capacity.toLocaleString('ru-RU')} т` : 'Не указана'}</strong></div>
                        <div><span>Диагностика до</span><strong>${eplCardValue(vehicle.diagnostic_valid_to)}</strong></div>
                        <div><span>Страховка до</span><strong>${eplCardValue(vehicle.insurance_valid_to)}</strong></div>
                        <div><span>Комментарий</span><strong>${eplCardValue(vehicle.comment)}</strong></div>
                    </div>
                </section>
            </div>

            <div class="epl-card-workflow">
                <div class="epl-card-workflow__heading"><span>Работа по рейсу</span><strong>Текущий этап и следующее действие</strong></div>
            <div class="epl-simple-progress">
                ${progress.map((item, index) => `<div class="epl-simple-progress__item ${item.done ? 'is-done' : item.key === workStep ? 'is-current' : ''}"><span>${item.done ? '✓' : index + 1}</span><strong>${item.label}</strong></div>`).join('')}
            </div>
            <div class="epl-next-action ${workStep === 'complete' ? 'is-complete' : ''}">
                <div><span>Следующее действие</span><strong>${stepInfo.title}</strong><p>${stepInfo.text}</p></div>
                ${stepInfo.button ? `<button class="btn-primary" onclick="completeEplCompactStep('${workStep}')">${stepInfo.button}</button>` : (waybill.qr_code ? `<button class="btn-secondary" onclick="openSelectedEplQr()">Открыть QR-код</button>` : '')}
            </div>
            </div>
        </div>
    `;
}

function renderIntegrationPanel() {
    const queue = document.getElementById('eplIntegrationQueue');
    const conflicts = document.getElementById('eplIntegrationConflicts');
    const alerts = document.getElementById('eplAlertsList');
    if (queue) {
        const rows = eplSyncQueueDB.slice(0, 30);
        queue.innerHTML = rows.length ? rows.map(item => {
            const payload = item.payload || {};
            return `
            <div class="accounting-log-item">
                <div class="finance-row-title">${eplEscapeHtml(payload.number || 'ЭПЛ')} · ${eplEscapeHtml(payload.driver_name || 'Без водителя')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(payload.route_text || 'Маршрут не указан')} · <span class="status-badge ${eplSyncStateClass(item.state)}">${eplEscapeHtml(eplSyncStateLabel(item.state))}</span></div>
                <div class="finance-row-meta">Попыток: ${Number(item.retry_count || 0)} · Обновлено: ${eplEscapeHtml(formatEplTimestamp(item.updated_at))}</div>
                ${item.last_error ? `<div class="finance-row-meta" style="color:#d54f4f;">Ошибка: ${eplEscapeHtml(item.last_error)}</div>` : ''}
                <div class="accounting-action-row" style="margin-top:10px;">
                    <button class="btn-secondary" onclick="openEplWaybillDetail(${Number(item.entity_id || 0)}); switchAccountingTab('waybills')">Карточка</button>
                                ${['failed', 'conflict', 'retry'].includes(item.state) ? `<button class="btn-secondary" onclick="retryEplSync(${item.id})">Повторить</button>` : ''}
                </div>
            </div>
        `; }).join('') : '<div class="empty-state">В очереди 1С по ЭПЛ сейчас ничего нет.</div>';
    }
    if (conflicts) {
        const rows = eplSyncConflictsDB.slice(0, 20);
        conflicts.innerHTML = rows.length ? rows.map(item => `
            <div class="accounting-log-item">
                <div class="finance-row-title">ЭПЛ ${eplEscapeHtml(item.payload?.number || item.entity_id || '—')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(item.message || 'Конфликт синхронизации')} · ${eplEscapeHtml(formatEplTimestamp(item.created_at))}</div>
                <div class="accounting-action-row" style="margin-top:10px;">
                    <button class="btn-secondary" onclick="openEplWaybillDetail(${Number(item.entity_id || 0)}); switchAccountingTab('waybills')">Карточка</button>
                </div>
            </div>
        `).join('') : '<div class="empty-state">Конфликтов синхронизации по ЭПЛ сейчас нет.</div>';
    }
    if (alerts) {
        const rows = eplSummaryDB?.alerts || [];
        alerts.innerHTML = rows.length ? rows.map(item => `
            <div class="accounting-log-item">
                <div class="finance-row-title">${eplEscapeHtml(item.title || 'Сигнал')}</div>
                <div class="finance-row-meta">${eplEscapeHtml(item.text || '')}</div>
            </div>
        `).join('') : '<div class="empty-state">Критичных сигналов по ЭПЛ сейчас нет.</div>';
    }
}

async function markEplStage(stageKey) {
    if (!eplSelectedWaybillId) return customAlert('Сначала выбери карточку ЭПЛ.');
    const waybill = eplWaybillDetailDB?.waybill || {};
    const blockMessage = getEplStageBlockingMessage(waybill, stageKey);
    if (blockMessage) return customAlert(blockMessage);
    const signer = document.getElementById(`eplStageSigner_${stageKey}`)?.value.trim() || '';
    const signedAt = document.getElementById(`eplStageTime_${stageKey}`)?.value.trim() || getEplTodayRuDate();
    const statusValue = document.getElementById(`eplStageStatus_${stageKey}`)?.value || '';
    const comment = document.getElementById(`eplStageComment_${stageKey}`)?.value.trim() || '';
    if (!signer) return customAlert('Укажи подписанта для титула.');
    const res = await apiCall(`/epl/waybills/${eplSelectedWaybillId}/actions`, 'POST', {
        stage: stageKey,
        signer_name: signer,
        signed_at: signedAt,
        status_value: statusValue,
        comment,
        expected_version: getCurrentEplExpectedVersion(),
    });
    if (!res || res.error) {
        return customAlert(res?.message || 'Не удалось зафиксировать титул ЭПЛ.');
    }
    await renderAccounting();
    await openEplWaybillDetail(eplSelectedWaybillId);
    showToast('1С ЭПЛ', `Этап «${eplStageLabel(stageKey)}» сохранён`);
}

async function updateSelectedWaybillIntegration(status, forcedWaybillId = 0) {
    const waybillId = Number(forcedWaybillId || eplSelectedWaybillId || 0);
    if (!waybillId) return customAlert('Сначала выбери карточку ЭПЛ.');
    const externalId = ['sent', 'accepted'].includes(status)
        ? await customPrompt('Укажи внешний идентификатор из 1С или оператора ЭДО (можно оставить пустым).', '')
        : '';
    if (externalId === null) return;
    const comment = status === 'error'
        ? await customPrompt('Кратко укажи причину ошибки интеграции.', '')
        : '';
    if (comment === null) return;
    const res = await apiCall(`/epl/waybills/${waybillId}/actions`, 'POST', {
        stage: 'integration',
        integration_status: status,
        external_document_id: (externalId || '').trim(),
        last_sync_error: status === 'error' ? (comment || '').trim() : '',
        comment: (comment || '').trim(),
        signer_name: currentUser?.name || '',
        signed_at: getEplTodayRuDate(),
        expected_version: getCurrentEplExpectedVersion(waybillId),
    });
    if (!res || res.error) {
        return customAlert(res?.message || 'Не удалось обновить статус интеграции.');
    }
    await renderAccounting();
    await openEplWaybillDetail(waybillId);
    showToast('1С ЭПЛ', `Статус интеграции обновлён: ${eplIntegrationLabel(status)}`);
}

function openSelectedEplQr() {
    const qrUrl = eplWaybillDetailDB?.waybill?.qr_code;
    if (!qrUrl) return customAlert('У выбранного ЭПЛ пока нет QR-кода.');
    window.open(qrUrl, '_blank');
}

function openSelectedEplProject() {
    const projectId = Number(eplWaybillDetailDB?.waybill?.project_id || 0);
    if (!projectId) return customAlert('У выбранного ЭПЛ нет привязки к проекту.');
    if (typeof openProject === 'function') openProject(projectId);
}

window.openEplModuleForWaybill = async function openEplModuleForWaybill(waybillId) {
    navigateTo('accounting');
    switchAccountingTab('waybills');
    if (Number(waybillId) > 0) {
        await openEplWaybillDetail(waybillId);
    }
};

async function seedEplDemoData(force = false) {
    const res = await apiCall(`/epl/demo-seed?force=${force ? 1 : 0}`, 'POST');
    if (!res || res.error) {
        return customAlert(res?.message || 'Не удалось подготовить пример ЭПЛ.');
    }
    if (typeof loadClients === 'function') await loadClients();
    if (typeof loadProjects === 'function') await loadProjects();
    await renderAccounting();
    showToast('1С ЭПЛ', `Пример обновлён: ${res.created || 0} создано, ${res.updated || 0} обновлено`);
}

async function saveEplWaybill() {
    const wasEditing = !!editingEplWaybillId;
    const targetWaybillId = Number(editingEplWaybillId || 0);
    const payload = {
        number: document.getElementById('eplWaybillNumber').value.trim(),
        issue_date: document.getElementById('eplWaybillIssueDate').value.trim(),
        shift_date: document.getElementById('eplWaybillShiftDate').value.trim(),
        waybill_type: document.getElementById('eplWaybillType').value,
        project_id: Number(document.getElementById('eplWaybillProjectId').value || 0),
        client_id: Number(document.getElementById('eplWaybillClientId').value || 0),
        driver_id: Number(document.getElementById('eplWaybillDriverId').value || 0),
        vehicle_id: Number(document.getElementById('eplWaybillVehicleId').value || 0),
        route_text: document.getElementById('eplWaybillRouteText').value.trim(),
        cargo: document.getElementById('eplWaybillCargo').value.trim(),
        departure_point: document.getElementById('eplWaybillDeparturePoint').value.trim(),
        destination_point: document.getElementById('eplWaybillDestinationPoint').value.trim(),
        dispatcher_name: document.getElementById('eplWaybillDispatcherName').value.trim(),
        medical_name: document.getElementById('eplWaybillMedicalName').value.trim(),
        mechanic_name: document.getElementById('eplWaybillMechanicName').value.trim(),
        planned_departure: document.getElementById('eplWaybillPlannedDeparture').value.trim(),
        actual_departure: document.getElementById('eplWaybillActualDeparture').value.trim(),
        actual_return: document.getElementById('eplWaybillActualReturn').value.trim(),
        odometer_out: Number((document.getElementById('eplWaybillOdometerOut').value || '').replace(',', '.')) || 0,
        odometer_in: Number((document.getElementById('eplWaybillOdometerIn').value || '').replace(',', '.')) || 0,
        fuel_issued: Number((document.getElementById('eplWaybillFuelIssued').value || '').replace(',', '.')) || 0,
        fuel_returned: Number((document.getElementById('eplWaybillFuelReturned').value || '').replace(',', '.')) || 0,
        status: document.getElementById('eplWaybillStatus').value,
        integration_status: document.getElementById('eplWaybillIntegrationStatus').value,
        operator_name: document.getElementById('eplWaybillOperatorName').value.trim(),
        external_document_id: document.getElementById('eplWaybillExternalId').value.trim(),
        notes: document.getElementById('eplWaybillNotes').value.trim(),
        last_sync_error: '',
        expected_version: editingEplWaybillId ? getCurrentEplExpectedVersion(editingEplWaybillId) : 0,
    };
    if (!payload.shift_date || !payload.driver_id || !payload.vehicle_id || !payload.route_text) {
        return customAlert('Для ЭПЛ заполни дату рейса, водителя, транспорт и маршрут.');
    }
    const endpoint = editingEplWaybillId ? `/epl/waybills/${editingEplWaybillId}` : '/epl/waybills';
    const method = editingEplWaybillId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.message || 'Не удалось сохранить путевой лист.'));
    resetEplWaybillForm();
    await renderAccounting();
    if (res.id) await openEplWaybillDetail(res.id);
    else if (targetWaybillId) await openEplWaybillDetail(targetWaybillId);
    document.querySelector('.accounting-detail-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    showToast('1С ЭПЛ', wasEditing ? 'Карточка ЭПЛ обновлена' : 'Путевой лист создан');
}

async function saveEplDriver() {
    const wasEditing = !!editingEplDriverId;
    const payload = {
        full_name: document.getElementById('eplDriverFullName').value.trim(),
        personnel_number: document.getElementById('eplDriverPersonnelNumber').value.trim(),
        license_number: document.getElementById('eplDriverLicenseNumber').value.trim(),
        license_category: document.getElementById('eplDriverLicenseCategory').value.trim(),
        phone: document.getElementById('eplDriverPhone').value.trim(),
        medical_valid_to: document.getElementById('eplDriverMedicalValidTo').value.trim(),
        signature_profile: document.getElementById('eplDriverSignatureProfile').value,
        status: document.getElementById('eplDriverStatus').value,
        comment: document.getElementById('eplDriverComment').value.trim(),
    };
    if (!payload.full_name || !payload.license_number || !payload.license_category || !payload.medical_valid_to) {
        return customAlert('Заполни ФИО, номер и категорию водительского удостоверения, а также срок медицинского допуска.');
    }
    const endpoint = editingEplDriverId ? `/epl/drivers/${editingEplDriverId}` : '/epl/drivers';
    const method = editingEplDriverId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось сохранить водителя.');
    resetEplDriverForm();
    await renderAccounting();
    switchAccountingTab('vehicles');
    showToast('1С ЭПЛ', wasEditing ? 'Водитель обновлён' : 'Водитель создан');
}

async function saveEplVehicle() {
    const wasEditing = !!editingEplVehicleId;
    const payload = {
        registration_no: document.getElementById('eplVehicleRegistrationNo').value.trim(),
        garage_number: document.getElementById('eplVehicleGarageNumber').value.trim(),
        brand: document.getElementById('eplVehicleBrand').value.trim(),
        model: document.getElementById('eplVehicleModel').value.trim(),
        trailer_registration: document.getElementById('eplVehicleTrailerRegistration').value.trim(),
        odometer: Number((document.getElementById('eplVehicleOdometer').value || '').replace(',', '.')) || 0,
        carrying_capacity: Number((document.getElementById('eplVehicleCarryingCapacity').value || '').replace(',', '.')) || 0,
        diagnostic_valid_to: document.getElementById('eplVehicleDiagnosticValidTo').value.trim(),
        insurance_valid_to: document.getElementById('eplVehicleInsuranceValidTo').value.trim(),
        status: document.getElementById('eplVehicleStatus').value,
        comment: document.getElementById('eplVehicleComment').value.trim(),
    };
    if (!payload.registration_no || !payload.brand || !payload.model) {
        return customAlert('Заполни госномер, марку и модель транспорта.');
    }
    const endpoint = editingEplVehicleId ? `/epl/vehicles/${editingEplVehicleId}` : '/epl/vehicles';
    const method = editingEplVehicleId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось сохранить транспорт.');
    resetEplVehicleForm();
    await renderAccounting();
    switchAccountingTab('waybills');
    showToast('1С ЭПЛ', wasEditing ? 'Транспорт обновлён' : 'Транспорт создан');
}

async function deleteEplWaybill(waybillId) {
    const confirmed = await customConfirm('Удалить путевой лист безвозвратно?');
    if (!confirmed) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('accounting', 'epl_waybill', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/epl/waybills/${waybillId}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось удалить ЭПЛ.');
    if (Number(eplSelectedWaybillId) === Number(waybillId)) {
        eplSelectedWaybillId = 0;
        eplWaybillDetailDB = null;
    }
    await renderAccounting();
    showToast('1С ЭПЛ', 'Путевой лист удалён');
}

async function deleteEplDriver(driverId) {
    const confirmed = await customConfirm('Удалить водителя из справочника?');
    if (!confirmed) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('accounting', 'epl_driver', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/epl/drivers/${driverId}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось удалить водителя.');
    await renderAccounting();
    showToast('1С ЭПЛ', 'Водитель удалён');
}

async function deleteEplVehicle(vehicleId) {
    const confirmed = await customConfirm('Удалить транспорт из справочника?');
    if (!confirmed) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('accounting', 'epl_vehicle', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/epl/vehicles/${vehicleId}`, 'DELETE');
    if (!res || res.error) return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось удалить транспорт.');
    await renderAccounting();
    showToast('1С ЭПЛ', 'Транспорт удалён');
}

function exportEplWaybills(rowsOverride = null) {
    if (typeof XLSX === 'undefined') {
        return customAlert('Модуль экспорта ещё не загрузился. Обнови страницу и попробуй снова.');
    }
    const rows = Array.isArray(rowsOverride) ? rowsOverride : getVisibleEplWaybills();
    if (!rows.length) {
        return customAlert('Нет путевых листов для выгрузки.');
    }
    const exportRows = rows.map(item => ({
        'ЭПЛ': item.number || '',
        'Дата рейса': item.shift_date || '',
        'Водитель': item.driver_name || '',
        'ТС': item.vehicle_label || '',
        'Маршрут': item.route_text || '',
        'Статус': eplStatusLabel(item.status),
        'Готовность %': item.readiness_percent || 0,
        'Интеграция': eplIntegrationLabel(item.integration_status),
        'Внешний идентификатор': item.external_document_id || '',
        'Пробег': Number(item.mileage || 0),
    }));
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'EPL');
    XLSX.writeFile(workbook, `korda-epl-${new Date().toISOString().slice(0, 10)}.xlsx`);
    showToast('1С ЭПЛ', `Выгружено ЭПЛ: ${exportRows.length}`);
}

function exportSelectedEplWaybills() {
    const rows = getSelectedEplWaybills();
    if (!rows.length) return customAlert('Сначала выбери ЭПЛ для экспорта.');
    exportEplWaybills(rows);
}

async function renderAccounting() {
    const view = document.getElementById('accountingView');
    if (!view) return;
    if (!accountingCanRead()) {
        if (eplLockedWaybillId) await releaseEplWaybillLock(eplLockedWaybillId, true);
        view.innerHTML = '<div class="surface-card surface-card--padded"><div class="empty-state">У тебя нет доступа к разделу 1С ЭПЛ.</div></div>';
        return;
    }
    await loadAccountingModuleData();
    groupAccountingOptionalFields();
    if (!eplDriversDB.length) accountingActiveTab = 'drivers';
    else if (!eplVehiclesDB.length) accountingActiveTab = 'vehicles';
    populateEplSelects();
    await applyAccountingFieldPermissions();
    renderAccountingMetrics();
    renderAccountingPulse();
    renderEplWaybillsTable();
    renderEplDriversTable();
    renderEplVehiclesTable();
    renderIntegrationPanel();
    switchAccountingTab(accountingActiveTab || 'waybills');
    if (!document.getElementById('eplWaybillIssueDate').value) {
        resetEplWaybillForm({ keepDraft: true });
    }
    bindEplWaybillDraftAutosave();
    bindEplSmartHints();
    if (accountingActiveTab === 'waybills') {
        await ensureEplWaybillDetail();
    } else {
        renderSelectedEplWaybill();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', groupAccountingOptionalFields, { once: true });
} else {
    groupAccountingOptionalFields();
}
