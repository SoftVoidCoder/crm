let contractRegistryDB = [];
let businessObjectsRegistryDB = [];
let contract360DB = null;
let currentContract360Id = 0;
let currentContract360Tab = 'overview';
let contractRegistrySelection = new Set();
let contractRegistryFilters = {
    search: '',
    folder: '',
    type: '',
    vat: '',
    risk: '',
    overdue: false,
    sort: 'end_date_asc',
};

function contractStateLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    return {
        draft: 'черновик',
        new: 'новый',
        active: 'активный',
        open: 'открыт',
        closed: 'закрыт',
        completed: 'завершён',
        done: 'выполнен',
        planned: 'запланирован',
        approved: 'согласован',
        pending: 'на согласовании',
        processing: 'в обработке',
        queued: 'в очереди',
        retry: 'повтор',
        failed: 'ошибка',
        conflict: 'конфликт',
        in_work: 'в работе',
        waiting_client: 'ожидает клиента',
        overdue: 'просрочен',
        incoming: 'входящий',
        outgoing: 'исходящий',
    }[normalized] || value || '—';
}

function contractEntityLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    return {
        contract: 'договор',
        project: 'проект',
        client: 'контрагент',
        document: 'документ',
        payment: 'оплата',
        expense: 'расход',
        request: 'заявка',
        production: 'производство',
        purchase: 'закупка',
        sales: 'реализация',
        resource: 'ресурс',
        service: 'сервис',
    }[normalized] || value || 'сущность';
}

function contractAuditActionLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    return {
        create: 'создание',
        update: 'изменение',
        delete: 'удаление',
        sync: 'синхронизация',
        link: 'связка',
        unlink: 'отвязка',
        approve: 'согласование',
        close: 'закрытие',
        open: 'открытие',
    }[normalized] || value || 'действие';
}

function contractTypeLabel(value) {
    return {
        standard: 'Стандартный',
        framework: 'Рамочный',
        service: 'Сервисный',
        supply: 'Поставка',
        construction: 'Подряд',
    }[String(value || '').trim().toLowerCase()] || (value || '—');
}

function contractVatLabel(value) {
    return {
        with_vat: 'С НДС',
        without_vat: 'Без НДС',
        mixed: 'Смешанный',
    }[String(value || '').trim().toLowerCase()] || (value || '—');
}

function contractRiskLabel(value) {
    return {
        low: 'Низкий',
        normal: 'Нормальный',
        attention: 'Под контролем',
        critical: 'Критичный',
    }[String(value || '').trim().toLowerCase()] || (value || '—');
}

function contractRiskClass(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (['low', 'normal', 'attention', 'critical'].includes(normalized)) return normalized;
    return 'normal';
}

function parseContractDate(value) {
    if (!value || typeof value !== 'string') return null;
    const parts = value.split('.');
    if (parts.length !== 3) return null;
    const date = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
    return Number.isNaN(date.getTime()) ? null : date;
}

function isContractOverdue(row) {
    if (Number(row?.is_overdue || 0)) return true;
    if (['closed', 'completed', 'done'].includes(String(row?.status || '').toLowerCase())) return false;
    const endDate = parseContractDate(row?.end_date || '');
    if (!endDate) return false;
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    return endDate < now;
}

function contractRegistryStorageKey() {
    const userKey = String(currentUser?.email || currentUser?.name || 'default')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9а-яё._-]+/gi, '_');
    return `korda_contract_registry_presets_v1:${userKey}`;
}

function contractReadPresets() {
    try {
        const raw = localStorage.getItem(contractRegistryStorageKey());
        const parsed = JSON.parse(raw || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function contractWritePresets(presets) {
    localStorage.setItem(contractRegistryStorageKey(), JSON.stringify(presets || []));
}

function contractParseCustomFields(value) {
    if (Array.isArray(value)) return value;
    if (typeof value !== 'string' || !value.trim()) return [];
    try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function contractDateSortValue(value, direction = 'asc') {
    const date = parseContractDate(value);
    if (date) return date.getTime();
    return direction === 'asc' ? Number.MAX_SAFE_INTEGER : Number.MIN_SAFE_INTEGER;
}

function contractRegistrySortRows(rows = []) {
    const sorted = rows.slice();
    sorted.sort((left, right) => {
        switch (contractRegistryFilters.sort) {
        case 'end_date_desc':
            return contractDateSortValue(right.end_date, 'desc') - contractDateSortValue(left.end_date, 'desc');
        case 'amount_desc':
            return Number(right.amount || 0) - Number(left.amount || 0);
        case 'number_asc':
            return String(left.contract_number || '').localeCompare(String(right.contract_number || ''), 'ru');
        case 'risk_desc': {
            const score = { critical: 4, attention: 3, normal: 2, low: 1 };
            return (score[String(right.risk_level || 'normal')] || 0) - (score[String(left.risk_level || 'normal')] || 0);
        }
        case 'end_date_asc':
        default:
            return contractDateSortValue(left.end_date, 'asc') - contractDateSortValue(right.end_date, 'asc');
        }
    });
    return sorted;
}

function getContractRegistryFiltersFromDom() {
    contractRegistryFilters = {
        search: document.getElementById('contractRegistrySearch')?.value?.trim() || '',
        folder: document.getElementById('contractRegistryFolder')?.value?.trim() || '',
        type: document.getElementById('contractRegistryType')?.value || '',
        vat: document.getElementById('contractRegistryVat')?.value || '',
        risk: document.getElementById('contractRegistryRisk')?.value || '',
        overdue: Boolean(document.getElementById('contractRegistryOverdue')?.checked),
        sort: document.getElementById('contractRegistrySort')?.value || 'end_date_asc',
    };
}

function getFilteredContractRegistryRows() {
    const search = String(contractRegistryFilters.search || '').toLowerCase();
    const folder = String(contractRegistryFilters.folder || '').toLowerCase();
    return contractRegistrySortRows((contractRegistryDB || []).filter(row => {
        if (contractRegistryFilters.type && String(row.contract_type || '') !== contractRegistryFilters.type) return false;
        if (contractRegistryFilters.vat && String(row.vat_mode || '') !== contractRegistryFilters.vat) return false;
        if (contractRegistryFilters.risk && String(row.risk_level || '') !== contractRegistryFilters.risk) return false;
        if (contractRegistryFilters.overdue && !isContractOverdue(row)) return false;
        if (folder && !String(row.folder || '').toLowerCase().includes(folder)) return false;
        if (search) {
            const haystack = [
                row.contract_number,
                row.title,
                row.client_name,
                row.project_name,
                row.manager_name,
                row.folder,
                row.category,
                row.contract_type,
            ].join(' ').toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    }));
}

function syncContractRegistrySelection() {
    const visibleIds = new Set((contractRegistryDB || []).map(row => Number(row.id || 0)));
    contractRegistrySelection = new Set(Array.from(contractRegistrySelection).filter(id => visibleIds.has(Number(id))));
}

function updateContractRegistrySelectionMeta(rows = []) {
    const meta = document.getElementById('contractRegistrySelectionMeta');
    if (!meta) return;
    const selectedRows = rows.filter(row => contractRegistrySelection.has(Number(row.id || 0)));
    const selectedTotal = selectedRows.reduce((sum, row) => sum + Number(row.amount || 0), 0);
    meta.innerText = `Выбрано: ${selectedRows.length} · Всего в фильтре: ${rows.length} · Сумма: ${formatMoney(selectedTotal, 'RUB')}`;
}

function fillContractRegistryPresetSelect() {
    const select = document.getElementById('contractRegistryPreset');
    if (!select) return;
    const currentValue = select.value || '';
    const presets = contractReadPresets();
    select.innerHTML = `<option value="">Пресет реестра</option>${presets.map(item => `
        <option value="${item.name}">${item.name}</option>
    `).join('')}`;
    select.value = presets.some(item => item.name === currentValue) ? currentValue : '';
}

function fillContractRegistryFiltersFromState() {
    const map = {
        contractRegistrySearch: contractRegistryFilters.search || '',
        contractRegistryFolder: contractRegistryFilters.folder || '',
        contractRegistryType: contractRegistryFilters.type || '',
        contractRegistryVat: contractRegistryFilters.vat || '',
        contractRegistryRisk: contractRegistryFilters.risk || '',
        contractRegistrySort: contractRegistryFilters.sort || 'end_date_asc',
    };
    Object.entries(map).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    const overdue = document.getElementById('contractRegistryOverdue');
    if (overdue) overdue.checked = Boolean(contractRegistryFilters.overdue);
}

function buildContractUpdatePayload(row, patch = {}) {
    return {
        project_id: Number(row.project_id || 0),
        client_id: Number(row.client_id || 0),
        object_id: Number(row.object_id || 0),
        contract_number: row.contract_number || '',
        title: row.title || '',
        status: patch.status ?? row.status ?? 'draft',
        amount: Number(row.amount || 0),
        currency: row.currency || 'RUB',
        start_date: row.start_date || '',
        end_date: row.end_date || '',
        manager_name: row.manager_name || '',
        manager_email: row.manager_email || '',
        comment: row.comment || '',
        custom_fields: contractParseCustomFields(row.custom_fields),
        contract_type: row.contract_type || 'standard',
        category: row.category || '',
        folder: patch.folder ?? row.folder ?? 'Все договоры',
        vat_mode: row.vat_mode || 'with_vat',
        risk_level: patch.risk_level ?? row.risk_level ?? 'normal',
    };
}

function renderContract360List(items, renderer, emptyText) {
    if (!Array.isArray(items) || !items.length) {
        return `<div class="empty-state">${emptyText}</div>`;
    }
    return items.map(renderer).join('');
}

function setContractHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

function contractCompactMeta(parts) {
    return parts
        .map(item => String(item || '').trim())
        .filter(Boolean)
        .join(' · ');
}

function contractItemAction(label, action, kind = 'secondary') {
    const cls = kind === 'primary' ? 'btn-primary' : 'btn-secondary';
    return `<button class="${cls}" onclick="${action}">${label}</button>`;
}

function contractDueStateLabel(status, dateValue) {
    if (!dateValue) return 'Срок не задан';
    return isContractOverdue({ status, end_date: dateValue }) ? 'Есть просрочка' : 'Срок в норме';
}

function renderContract360MiniMetrics(items = []) {
    if (!items.length) {
        return '<div class="empty-state">Индикаторы по этому разделу пока не сформированы.</div>';
    }
    return items.map(item => `
        <div class="contract360-mini-metric contract360-mini-metric--${item.tone || 'neutral'}">
            <div class="contract360-mini-metric__label">${item.label}</div>
            <div class="contract360-mini-metric__value">${item.value}</div>
            <div class="contract360-mini-metric__note">${item.note || ''}</div>
        </div>
    `).join('');
}

function renderContractRegistryCounters(rows = []) {
    const mount = document.getElementById('contract360RegistryCounters');
    if (!mount) return;
    const overdue = rows.filter(isContractOverdue).length;
    const critical = rows.filter(item => String(item.risk_level || '').toLowerCase() === 'critical').length;
    const approval = rows.filter(item => ['pending', 'approval', 'review'].includes(String(item.status || '').toLowerCase())).length;
    const active = rows.filter(item => String(item.status || '').toLowerCase() === 'active').length;
    const amount = rows.reduce((sum, item) => sum + Number(item.amount || 0), 0);
    const counters = [
        { label: 'Активные договоры', value: active, note: 'идут в исполнении', tone: active ? 'positive' : 'neutral' },
        { label: 'Просрочка', value: overdue, note: 'срок окончания уже прошёл', tone: overdue ? 'critical' : 'positive' },
        { label: 'Ждут согласования', value: approval, note: 'нужна юридическая или внутренняя виза', tone: approval ? 'warning' : 'neutral' },
        { label: 'Критичный риск', value: critical, note: 'требует внимания директора', tone: critical ? 'critical' : 'neutral' },
        { label: 'Портфель суммы', value: formatMoney(amount), note: `${rows.length} строк в реестре`, tone: 'accent' },
    ];
    mount.innerHTML = counters.map(item => `
        <article class="contract360-registry-counter contract360-registry-counter--${item.tone}">
            <div class="contract360-registry-counter__label">${item.label}</div>
            <div class="contract360-registry-counter__value">${item.value}</div>
            <div class="contract360-registry-counter__note">${item.note}</div>
        </article>
    `).join('');
}

window.switchContract360Tab = function(tabId = 'overview') {
    currentContract360Tab = tabId;
    const tabs = [
        'overview',
        'counterparties',
        'payments',
        'approvals',
        'files',
        'stages',
        'claims',
        'letters',
        'tasks',
        'costs',
        'access',
        'history',
        'registry',
    ];
    tabs.forEach(tab => {
        const button = document.getElementById(`contract360Tab${tab.charAt(0).toUpperCase()}${tab.slice(1)}`);
        const panel = document.getElementById(`contract360Panel${tab.charAt(0).toUpperCase()}${tab.slice(1)}`);
        const active = tab === currentContract360Tab;
        if (button) {
            button.classList.toggle('active', active);
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        }
        if (panel) {
            panel.hidden = !active;
            panel.classList.toggle('contract360-panel--active', active);
        }
    });
};

async function loadContractRegistry(projectId = 0, clientId = 0) {
    const contractsUrl = `/contracts${projectId ? `?project_id=${projectId}` : clientId ? `?client_id=${clientId}` : ''}`;
    const objectsUrl = `/business_objects${clientId ? `?client_id=${clientId}` : ''}`;
    const [contracts, objects] = await Promise.all([
        apiCall(contractsUrl),
        apiCall(objectsUrl),
    ]);
    contractRegistryDB = Array.isArray(contracts) ? contracts : [];
    businessObjectsRegistryDB = Array.isArray(objects) ? objects : [];
}

async function loadContractCard(contractId) {
    currentContract360Id = Number(contractId || 0);
    if (!currentContract360Id) {
        contract360DB = null;
        return null;
    }
    const data = await apiCall(`/contracts/${currentContract360Id}/card`);
    contract360DB = data && !data.error ? data : null;
    return contract360DB;
}

function populateContractCardSelects(contract) {
    const clientSelect = document.getElementById('contractCardClient');
    const managerSelect = document.getElementById('contractCardManager');
    if (clientSelect) {
        clientSelect.innerHTML = `<option value="0">Без контрагента</option>${clientsDB
            .slice()
            .sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ru'))
            .map(client => `<option value="${client.id}" ${Number(contract.client_id || 0) === Number(client.id) ? 'selected' : ''}>${client.name}</option>`)
            .join('')}`;
    }
    if (managerSelect) {
        const approvedUsers = (allUsersDB || []).filter(user => user.status === 'approved');
        managerSelect.innerHTML = `<option value="">Не выбран</option>${approvedUsers
            .map(user => `<option value="${user.name}" ${String(contract.manager_name || '') === String(user.name || '') ? 'selected' : ''}>${user.name} (${user.role || 'роль не задана'})</option>`)
            .join('')}`;
    }
}

function renderContractRegistry() {
    const registry = document.getElementById('contract360Registry');
    if (!registry) return;
    syncContractRegistrySelection();
    const rows = getFilteredContractRegistryRows();
    renderContractRegistryCounters(rows);
    updateContractRegistrySelectionMeta(rows);
    const allSelected = rows.length > 0 && rows.every(row => contractRegistrySelection.has(Number(row.id || 0)));
    registry.innerHTML = `
        <div class="table-shell contract-registry-table-shell">
            <table class="admin-table admin-table--dense crm-registry-table">
                <thead>
                    <tr>
                        <th style="width:44px;"><input type="checkbox" ${allSelected ? 'checked' : ''} onchange="toggleContractRegistryAll(this.checked)"></th>
                        <th>Договор</th>
                        <th>Контрагент</th>
                        <th>Папка / тип</th>
                        <th>Период</th>
                        <th class="is-num">Сумма</th>
                        <th>НДС</th>
                        <th>Риск</th>
                        <th>Статус</th>
                        <th>Менеджер</th>
                        <th>Быстрые действия</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(contract => `
                        <tr class="${Number(contract.id) === Number(currentContract360Id) ? 'is-selected' : ''}" onclick="openContractCard(${contract.id})">
                            <td onclick="event.stopPropagation()">
                                <input type="checkbox" ${contractRegistrySelection.has(Number(contract.id || 0)) ? 'checked' : ''} onchange="toggleContractRegistryRow(${contract.id}, this.checked)">
                            </td>
                            <td class="crm-title-cell">
                                <div class="contract-registry-title-cell">
                                    <strong>${contract.contract_number || 'Без номера'}</strong>
                                    <div class="table-subtext">${contract.title || 'Без названия'}</div>
                                </div>
                            </td>
                            <td class="crm-contact-cell">
                                <div>${contract.client_name || 'Без контрагента'}</div>
                                <div class="table-subtext">${contract.project_name || 'Без проекта'}</div>
                            </td>
                            <td class="crm-meta-cell">
                                <div>${contract.folder || 'Все договоры'}</div>
                                <div class="table-subtext">${contractTypeLabel(contract.contract_type)}${contract.category ? ` · ${contract.category}` : ''}</div>
                            </td>
                            <td class="crm-action-cell">
                                <div>${contract.start_date || '—'} → ${contract.end_date || '—'}</div>
                                <div class="table-subtext">${isContractOverdue(contract) ? 'Есть просрочка' : 'Срок в норме'}</div>
                            </td>
                            <td class="amount is-num crm-amount-cell">${formatMoney(Number(contract.amount || 0), contract.currency || 'RUB')}</td>
                            <td class="crm-meta-cell">${contractVatLabel(contract.vat_mode)}</td>
                            <td><span class="contract-risk contract-risk--${contractRiskClass(contract.risk_level)}">${contractRiskLabel(contract.risk_level)}</span></td>
                            <td><span class="crm-inline-pill crm-inline-pill--${isContractOverdue(contract) ? 'critical' : 'neutral'}">${contractStateLabel(contract.status)}</span></td>
                            <td class="crm-meta-cell">${contract.manager_name || '—'}</td>
                            <td class="crm-action-cell" onclick="event.stopPropagation()">
                                <div class="contract-row-actions">
                                    <button class="btn-secondary" onclick="openContractCard(${contract.id})">Открыть</button>
                                    <button class="btn-secondary" onclick="assignContractManager(${contract.id})">Назначить</button>
                                    <button class="btn-secondary" onclick="quickChangeContractStatus(${contract.id})">Статус</button>
                                    <button class="btn-secondary" onclick="quickCommentContract(${contract.id})">Комментарий</button>
                                    <button class="btn-secondary" onclick="createContractTask(${contract.id})">Задача</button>
                                    <button class="btn-secondary" onclick="openContractDocuments(${contract.id})">Документы</button>
                                    <button class="btn-secondary" onclick="createContractReminder(${contract.id})">Напомнить</button>
                                </div>
                            </td>
                        </tr>
                    `).join('') || '<tr><td colspan="11"><div class="empty-state">По текущему фильтру договоры не найдены.</div></td></tr>'}
                </tbody>
            </table>
        </div>
    `;
}

function fillContractMasterForm() {
    if (!contract360DB) return;
    const contract = contract360DB.contract || {};
    const objectData = contract360DB.object || {};
    populateContractCardSelects(contract);
    const valueMap = {
        contractCardNumber: contract.contract_number || '',
        contractCardStatus: contract.status || '',
        contractCardTitle: contract.title || '',
        contractCardAmount: contract.amount || 0,
        contractCardCurrency: contract.currency || 'RUB',
        contractCardType: contract.contract_type || 'standard',
        contractCardFolder: contract.folder || '',
        contractCardCategory: contract.category || '',
        contractCardVatMode: contract.vat_mode || 'with_vat',
        contractCardRiskLevel: contract.risk_level || 'normal',
        contractCardStartDate: contract.start_date || '',
        contractCardEndDate: contract.end_date || '',
        contractCardObjectName: objectData.name || '',
        contractCardObjectResponsible: objectData.responsible_name || '',
        contractCardObjectAddress: objectData.address || '',
        contractCardObjectCity: objectData.city || '',
        contractCardObjectRegion: objectData.region || '',
        contractCardComment: contract.comment || '',
    };
    Object.entries(valueMap).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
}

window.syncCurrentContractCard = async function() {
    if (!contract360DB?.contract?.project_id) {
        return customAlert('У этой карточки нет привязанного проекта для пересборки справочника.');
    }
    const res = await apiCall(`/projects/${contract360DB.contract.project_id}/contract_master/sync`, 'POST');
    if (!res || res.error) {
        return customAlert('Не удалось пересобрать связи договора.');
    }
    await loadContractRegistry();
    await loadContractCard(res.contract_id || currentContract360Id);
    await renderContract360();
    if (typeof loadProjects === 'function') await loadProjects();
    showToast('Контракт 360', 'Связи проекта, договора и объекта пересобраны');
};

window.saveContractMasterCard = async function() {
    if (!contract360DB?.contract?.id) {
        return customAlert('Сначала открой карточку договора.');
    }
    const contract = contract360DB.contract || {};
    const clientId = Number(document.getElementById('contractCardClient')?.value || contract.client_id || 0);
    const managerName = document.getElementById('contractCardManager')?.value || contract.manager_name || '';
    const manager = (allUsersDB || []).find(user => user.name === managerName) || {};
    const objectPayload = {
        client_id: clientId,
        name: document.getElementById('contractCardObjectName')?.value?.trim() || '',
        code: '',
        address: document.getElementById('contractCardObjectAddress')?.value?.trim() || '',
        city: document.getElementById('contractCardObjectCity')?.value?.trim() || '',
        region: document.getElementById('contractCardObjectRegion')?.value?.trim() || '',
        responsible_name: document.getElementById('contractCardObjectResponsible')?.value?.trim() || '',
        responsible_email: '',
        comment: '',
    };
    let objectId = Number(contract.object_id || 0);
    if (objectPayload.name) {
        const objectRes = objectId
            ? await apiCall(`/business_objects/${objectId}`, 'PUT', objectPayload)
            : await apiCall('/business_objects', 'POST', objectPayload);
        if (!objectRes || objectRes.error) {
            return customAlert('Не удалось сохранить объект.');
        }
        objectId = objectId || Number(objectRes.id || 0);
    }

    const payload = {
        project_id: Number(contract.project_id || 0),
        client_id: clientId,
        object_id: objectId,
        contract_number: document.getElementById('contractCardNumber')?.value?.trim() || '',
        title: document.getElementById('contractCardTitle')?.value?.trim() || '',
        status: document.getElementById('contractCardStatus')?.value?.trim() || 'draft',
        amount: Number(document.getElementById('contractCardAmount')?.value || 0),
        currency: document.getElementById('contractCardCurrency')?.value?.trim() || 'RUB',
        start_date: document.getElementById('contractCardStartDate')?.value?.trim() || '',
        end_date: document.getElementById('contractCardEndDate')?.value?.trim() || '',
        manager_name: managerName,
        manager_email: manager.email || '',
        comment: document.getElementById('contractCardComment')?.value?.trim() || '',
        contract_type: document.getElementById('contractCardType')?.value || 'standard',
        folder: document.getElementById('contractCardFolder')?.value?.trim() || 'Все договоры',
        category: document.getElementById('contractCardCategory')?.value?.trim() || '',
        vat_mode: document.getElementById('contractCardVatMode')?.value || 'with_vat',
        risk_level: document.getElementById('contractCardRiskLevel')?.value || 'normal',
        custom_fields: Array.isArray(contract.custom_fields) ? contract.custom_fields : [],
    };
    const res = await apiCall(`/contracts/${contract.id}`, 'PUT', payload);
    if (!res || res.error) {
        return customAlert('Не удалось сохранить справочник договора.');
    }
    await loadContractRegistry();
    await loadContractCard(contract.id);
    await renderContract360();
    if (typeof loadProjects === 'function') await loadProjects();
    showToast('Контракт 360', 'Справочник договора обновлён');
};

function findContractRegistryRow(contractId) {
    return contractRegistryDB.find(row => Number(row.id || 0) === Number(contractId || 0)) || null;
}

async function persistContractRegistryRow(contractId, patch = {}) {
    const row = findContractRegistryRow(contractId);
    if (!row) {
        await customAlert('Карточка договора не найдена в реестре.');
        return null;
    }
    const payload = {
        ...buildContractUpdatePayload(row, patch),
        manager_name: patch.manager_name ?? row.manager_name ?? '',
        manager_email: patch.manager_email ?? row.manager_email ?? '',
        comment: patch.comment ?? row.comment ?? '',
    };
    const res = await apiCall(`/contracts/${contractId}`, 'PUT', payload);
    if (!res || res.error) {
        await customAlert('Не удалось сохранить быстрое изменение по договору.');
        return null;
    }
    await loadContractRegistry();
    if (Number(currentContract360Id || 0) === Number(contractId || 0)) {
        await loadContractCard(contractId);
        await renderContract360();
    } else {
        renderContractRegistry();
    }
    return res;
}

window.assignContractManager = async function(contractId) {
    const row = findContractRegistryRow(contractId);
    if (!row) return;
    const nextManager = await customPrompt('Укажи ФИО менеджера для договора.', row.manager_name || '');
    if (nextManager === null) return;
    const matchedUser = (allUsersDB || []).find(user => String(user.name || '').trim() === String(nextManager || '').trim());
    await persistContractRegistryRow(contractId, {
        manager_name: String(nextManager || '').trim(),
        manager_email: matchedUser?.email || '',
    });
    showToast('Контракт 360', 'Менеджер договора обновлён');
};

window.quickChangeContractStatus = async function(contractId) {
    const row = findContractRegistryRow(contractId);
    if (!row) return;
    const labels = {
        draft: 'Черновик',
        active: 'Действует',
        pending: 'На согласовании',
        approved: 'Согласован',
        closed: 'Закрыт',
    };
    const aliases = Object.fromEntries(Object.entries(labels).flatMap(([code, label]) => [
        [code, code],
        [label.toLowerCase(), code],
    ]));
    const currentLabel = labels[String(row.status || '').toLowerCase()] || labels.draft;
    const entered = await customPrompt('Новый статус: Черновик, Действует, На согласовании, Согласован или Закрыт.', currentLabel);
    if (entered === null) return;
    const nextStatus = aliases[String(entered || '').trim().toLowerCase()];
    if (!nextStatus) {
        await customAlert('Выберите один из указанных статусов договора.');
        return;
    }
    await persistContractRegistryRow(contractId, { status: nextStatus });
    showToast('Контракт 360', 'Статус договора обновлён');
};

window.quickCommentContract = async function(contractId) {
    const row = findContractRegistryRow(contractId);
    if (!row) return;
    const nextComment = await customPrompt('Комментарий или резюме по договору.', row.comment || '');
    if (nextComment === null) return;
    await persistContractRegistryRow(contractId, { comment: nextComment });
    showToast('Контракт 360', 'Комментарий договора обновлён');
};

async function createContractTaskBase(contractId, titlePrefix) {
    const row = findContractRegistryRow(contractId);
    if (!row) return;
    const title = await customPrompt('Название задачи.', `${titlePrefix} ${row.contract_number || row.title || `#${contractId}`}`.trim());
    if (title === null || !String(title || '').trim()) return;
    const executor = await customPrompt('Исполнитель задачи.', row.manager_name || currentUser?.name || '');
    if (executor === null) return;
    const deadline = await customPrompt('Дедлайн задачи (дд.мм.гггг).', row.end_date || '');
    if (deadline === null) return;
    const description = contractCompactMeta([
        row.title || '',
        row.client_name || '',
        `Договор ${row.contract_number || `#${contractId}`}`,
    ]);
    const res = await apiCall('/tasks', 'POST', {
        title: String(title || '').trim(),
        description,
        author: currentUser?.name || 'Система',
        executor: String(executor || '').trim(),
        deadline: String(deadline || '').trim(),
        priority: isContractOverdue(row) ? 'high' : 'normal',
        project_id: Number(row.project_id || 0),
    });
    if (!res || res.error) {
        await customAlert('Не удалось создать задачу по договору.');
        return;
    }
    showToast('Контракт 360', 'Задача по договору создана');
};

window.createContractTask = async function(contractId) {
    await createContractTaskBase(contractId, 'Поручение по договору');
};

window.createContractReminder = async function(contractId) {
    await createContractTaskBase(contractId, 'Напоминание по договору');
};

window.openContractDocuments = function(contractId) {
    const row = findContractRegistryRow(contractId);
    navigateTo('documents');
    const search = document.getElementById('searchInput');
    if (search && row) {
        search.value = row.contract_number || row.title || '';
    }
    if (typeof renderDocuments === 'function') renderDocuments();
};

window.openContractCard = async function(contractId) {
    await loadContractRegistry();
    const data = await loadContractCard(contractId);
    if (!data) {
        return customAlert('Не удалось открыть карточку договора.');
    }
    navigateTo('contract360');
};

window.openContractCardForProject = async function(projectId) {
    const res = await apiCall(`/projects/${projectId}/contract_master/sync`, 'POST');
    if (!res || res.error) {
        return customAlert('Не удалось синхронизировать договор проекта.');
    }
    const project = (projectsDB || []).find(item => Number(item.id) === Number(projectId));
    if (project) {
        project.contract_id = Number(res.contract_id || 0);
        project.object_id = Number(res.object_id || 0);
    }
    await loadContractRegistry(projectId);
    const data = await loadContractCard(res.contract_id);
    if (!data) {
        return customAlert('Не удалось открыть карточку договора.');
    }
    navigateTo('contract360');
};

window.openProjectContractCard = async function() {
    if (!currentProjectId) {
        return customAlert('Сначала открой проект.');
    }
    return openContractCardForProject(currentProjectId);
};

window.applyContractRegistryFilters = function() {
    getContractRegistryFiltersFromDom();
    renderContractRegistry();
};

window.saveContractRegistryPreset = function() {
    const name = window.prompt('Название пресета для реестра договоров');
    if (!name || !name.trim()) return;
    getContractRegistryFiltersFromDom();
    const presets = contractReadPresets().filter(item => item.name !== name.trim());
    presets.push({ name: name.trim(), ...contractRegistryFilters });
    presets.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    contractWritePresets(presets);
    const select = document.getElementById('contractRegistryPreset');
    if (select) select.value = name.trim();
    renderContractRegistry();
};

window.applyContractRegistryPreset = function(name) {
    if (!name) {
        const select = document.getElementById('contractRegistryPreset');
        if (select) select.value = '';
        return;
    }
    const preset = contractReadPresets().find(item => item.name === name);
    if (!preset) return;
    contractRegistryFilters = {
        search: preset.search || '',
        folder: preset.folder || '',
        type: preset.type || '',
        vat: preset.vat || '',
        risk: preset.risk || '',
        overdue: Boolean(preset.overdue),
        sort: preset.sort || 'end_date_asc',
    };
    renderContractRegistry();
};

window.resetContractRegistryFilters = function() {
    contractRegistryFilters = {
        search: '',
        folder: '',
        type: '',
        vat: '',
        risk: '',
        overdue: false,
        sort: 'end_date_asc',
    };
    const select = document.getElementById('contractRegistryPreset');
    if (select) select.value = '';
    renderContractRegistry();
};

window.toggleContractRegistryRow = function(contractId, checked) {
    const numericId = Number(contractId || 0);
    if (checked) contractRegistrySelection.add(numericId);
    else contractRegistrySelection.delete(numericId);
    renderContractRegistry();
};

window.toggleContractRegistryAll = function(checked) {
    const rows = getFilteredContractRegistryRows();
    rows.forEach(row => {
        const numericId = Number(row.id || 0);
        if (checked) contractRegistrySelection.add(numericId);
        else contractRegistrySelection.delete(numericId);
    });
    renderContractRegistry();
};

window.exportContractRegistry = function(selectedOnly = false) {
    const rows = selectedOnly
        ? getFilteredContractRegistryRows().filter(row => contractRegistrySelection.has(Number(row.id || 0)))
        : getFilteredContractRegistryRows();
    if (!rows.length) {
        customAlert(selectedOnly ? 'Нет выбранных договоров для выгрузки.' : 'Нет договоров по текущему фильтру.');
        return;
    }
    const header = ['Номер', 'Название', 'Контрагент', 'Проект', 'Папка', 'Категория', 'Тип', 'Статус', 'НДС', 'Риск', 'Начало', 'Окончание', 'Сумма', 'Валюта', 'Менеджер'];
    const csvRows = rows.map(row => [
        row.contract_number || '',
        row.title || '',
        row.client_name || '',
        row.project_name || '',
        row.folder || '',
        row.category || '',
        contractTypeLabel(row.contract_type),
        contractStateLabel(row.status),
        contractVatLabel(row.vat_mode),
        contractRiskLabel(row.risk_level),
        row.start_date || '',
        row.end_date || '',
        Number(row.amount || 0),
        row.currency || 'RUB',
        row.manager_name || '',
    ]);
    const csv = [header, ...csvRows]
        .map(cols => cols.map(value => `"${String(value ?? '').replace(/"/g, '""')}"`).join(';'))
        .join('\n');
    const blob = new Blob(["\uFEFF" + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = selectedOnly ? 'contracts_selected.csv' : 'contracts_registry.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
};

window.applyContractRegistryBulkAction = async function() {
    const action = document.getElementById('contractRegistryBulkAction')?.value || '';
    const selectedRows = getFilteredContractRegistryRows().filter(row => contractRegistrySelection.has(Number(row.id || 0)));
    if (!action) return customAlert('Выбери массовое действие.');
    if (!selectedRows.length && action !== 'selection:clear') return customAlert('Сначала выдели договоры в реестре.');
    if (action === 'selection:clear') {
        contractRegistrySelection.clear();
        renderContractRegistry();
        return;
    }
    if (action === 'export:selected') {
        exportContractRegistry(true);
        return;
    }

    const [kind, rawValue] = action.split(':');
    let patch = {};
    if (kind === 'risk') patch = { risk_level: rawValue || 'normal' };
    if (kind === 'status') patch = { status: rawValue || 'draft' };
    if (kind === 'folder') {
        const nextFolder = rawValue === 'prompt'
            ? String(window.prompt('Новая папка для выбранных договоров', selectedRows[0]?.folder || '') || '').trim()
            : rawValue;
        if (!nextFolder) return;
        patch = { folder: nextFolder };
    }
    if (!Object.keys(patch).length) return;

    for (const row of selectedRows) {
        const response = await apiCall(`/contracts/${row.id}`, 'PUT', buildContractUpdatePayload(row, patch));
        if (!response || response.error) {
            return customAlert(`Не удалось обновить договор ${row.contract_number || row.id}.`);
        }
    }
    await loadContractRegistry();
    const bulkSelect = document.getElementById('contractRegistryBulkAction');
    if (bulkSelect) bulkSelect.value = '';
    renderContractRegistry();
};

async function ensureContractRegistryLoaded() {
    if (!contractRegistryDB.length) {
        await loadContractRegistry();
    }
}

async function ensureContractCardLoaded() {
    await ensureContractRegistryLoaded();
    if (!currentContract360Id && contractRegistryDB.length) {
        currentContract360Id = Number(contractRegistryDB[0].id || 0);
    }
    if (!currentContract360Id) {
        contract360DB = null;
        return null;
    }
    if (!contract360DB || Number(contract360DB.contract?.id || 0) !== Number(currentContract360Id)) {
        await loadContractCard(currentContract360Id);
    }
    return contract360DB;
}

async function renderContract360() {
    const emptyState = document.getElementById('contract360EmptyState');
    const content = document.getElementById('contract360Content');
    if (!emptyState || !content) return;
    if (!currentPermissions.projects || !currentPermissions.projects.includes('read')) {
        emptyState.style.display = 'block';
        emptyState.innerHTML = '<div class="empty-state">У тебя нет доступа к справочнику договоров.</div>';
        content.style.display = 'none';
        return;
    }
    const data = await ensureContractCardLoaded();
    fillContractRegistryFiltersFromState();
    fillContractRegistryPresetSelect();
    renderContractRegistry();
    if (!data) {
        emptyState.style.display = 'block';
        content.style.display = 'none';
        return;
    }
    emptyState.style.display = 'none';
    content.style.display = 'block';
    const {
        contract,
        client,
        object,
        projects,
        employees,
        finance,
        purchases,
        sales,
        production,
        expenses,
        requests,
        resources,
        service_cases,
        documents,
        erp_processes,
        audit,
        timeline,
        metrics,
        tasks = [],
        claims = [],
        courts = [],
    } = data;

    const numberEl = document.getElementById('contract360Number');
    const statusEl = document.getElementById('contract360Status');
    const heroMetaEl = document.getElementById('contract360HeroMeta');
    if (numberEl) numberEl.innerText = `${contract.contract_number || 'Без номера'} · ${contract.title || 'Без названия'}`;
    if (statusEl) statusEl.innerText = contractStateLabel(contract.status || 'draft');
    if (heroMetaEl) {
        heroMetaEl.innerText = `${client.name || 'Без контрагента'} · ${object.name || 'Без объекта'} · ${contract.manager_name || 'Менеджер не назначен'}`;
    }

    const metricsEl = document.getElementById('contract360Metrics');
    if (metricsEl && typeof window.renderEntitySummary === 'function') {
        const hasContractActivity = [
            Number(metrics.projects_total || 0),
            Number(metrics.documents_total || 0),
            Number(metrics.receivable_open || 0),
            Number(metrics.payable_open || 0),
            Number(metrics.margin || 0),
            Number(metrics.active_processes || 0),
        ].some(value => value > 0);
        const receivableOpen = Number(metrics.receivable_open || 0);
        const payableOpen = Number(metrics.payable_open || 0);
        const contractHeadline = hasContractActivity
            ? `${Number(metrics.projects_total || 0)} проектов в контуре · ${Number(metrics.active_processes || 0)} ERP-процессов`
            : 'Контур договора пока не наполнен операциями';
        const contractDescription = hasContractActivity
            ? `Финансовый срез: дебиторка ${formatMoney(receivableOpen, contract.currency || 'RUB')}, кредиторка ${formatMoney(payableOpen, contract.currency || 'RUB')} и маржа ${formatMoney(metrics.margin || 0, contract.currency || 'RUB')}.`
            : 'Когда по договору появятся проекты, документы и движения денег, здесь будет компактная управленческая сводка.';

        window.renderEntitySummary(metricsEl, {
            kind: 'contract',
            variant: 'contract',
            eyebrow: 'Короткий срез',
            headline: contractHeadline,
            description: contractDescription,
            primary: [
                {
                    label: 'Проекты в контуре',
                    value: Number(metrics.projects_total || 0),
                    note: 'связано с договором',
                    tone: Number(metrics.projects_total || 0) > 0 ? 'accent' : '',
                    hidden: Number(metrics.projects_total || 0) <= 0,
                },
                {
                    label: 'Открытая дебиторка',
                    value: formatMoney(receivableOpen, contract.currency || 'RUB'),
                    note: receivableOpen > 0 ? 'нужен контроль оплат' : 'входящий риск не открыт',
                    tone: receivableOpen > 0 ? 'warning' : 'positive',
                    hidden: receivableOpen <= 0,
                },
                {
                    label: 'Открытая кредиторка',
                    value: formatMoney(payableOpen, contract.currency || 'RUB'),
                    note: payableOpen > 0 ? 'есть обязательства к оплате' : 'исходящий риск не открыт',
                    tone: payableOpen > 0 ? 'warning' : 'positive',
                    hidden: payableOpen <= 0,
                },
            ],
            secondary: [
                { label: 'Документов', value: Number(metrics.documents_total || 0), hidden: Number(metrics.documents_total || 0) <= 0 },
                { label: 'Маржа по контуру', value: formatMoney(metrics.margin || 0, contract.currency || 'RUB'), hidden: Number(metrics.margin || 0) <= 0 },
                { label: 'ERP-процессов', value: Number(metrics.active_processes || 0), hidden: Number(metrics.active_processes || 0) <= 0 },
            ],
        });
    }

    fillContractMasterForm();
    switchContract360Tab(currentContract360Tab || 'overview');

    setContractHtml('contract360Counterparties', renderContract360List(
        [
            {
                title: client.name || 'Контрагент не задан',
                meta: contractCompactMeta([
                    client.inn ? `ИНН ${client.inn}` : '',
                    client.contact || '',
                    contract.contract_number ? `Договор ${contract.contract_number}` : '',
                ]),
                side: contractStateLabel(contract.status || 'draft'),
            },
            {
                title: object.name || 'Объект не задан',
                meta: contractCompactMeta([
                    object.address || '',
                    object.city || '',
                    object.region || '',
                    object.responsible_name ? `Ответственный: ${object.responsible_name}` : '',
                ]),
                side: object.responsible_email || 'Без e-mail',
            },
        ],
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title}</div>
                    <div class="client360-item-meta">${item.meta || 'Данные не заполнены'}</div>
                </div>
                <div class="client360-item-side">${item.side || '—'}</div>
            </div>
        `,
        'Контрагенты и объекты для этого договора пока не заполнены.'
    ));

    setContractHtml('contract360Projects', renderContract360List(
        projects,
        project => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${project.name || 'Проект'}</div>
                    <div class="client360-item-meta">${project.contract || 'Без номера'} · ${contractStateLabel(project.status || 'без статуса')}</div>
                </div>
                <div class="view-actions">
                    <button class="btn-secondary" onclick="openProject(${project.id})">Открыть проект</button>
                </div>
            </div>
        `,
        'К этому договору пока не привязан ни один проект.'
    ));

    setContractHtml('contract360Employees', renderContract360List(
        employees,
        employee => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${employee.name}</div>
                    <div class="client360-item-meta">${employee.role || 'Роль не задана'}${employee.email ? ` · ${employee.email}` : ''}</div>
                </div>
                <div class="client360-item-side">${employee.load_percent || 0}%</div>
            </div>
        `,
        'Связанные сотрудники пока не определены.'
    ));

    setContractHtml('contract360PaymentsSummary', renderContract360MiniMetrics([
        {
            label: 'Открытая дебиторка',
            value: formatMoney(Number(metrics.receivable_open || 0), contract.currency || 'RUB'),
            note: Number(metrics.receivable_open || 0) > 0 ? 'нужно контролировать поступление' : 'просроченных поступлений нет',
            tone: Number(metrics.receivable_open || 0) > 0 ? 'warning' : 'positive',
        },
        {
            label: 'Открытая кредиторка',
            value: formatMoney(Number(metrics.payable_open || 0), contract.currency || 'RUB'),
            note: Number(metrics.payable_open || 0) > 0 ? 'есть обязательства к оплате' : 'критичных выплат нет',
            tone: Number(metrics.payable_open || 0) > 0 ? 'warning' : 'positive',
        },
        {
            label: 'Доход по контуру',
            value: formatMoney(Number(metrics.revenue_total || 0), contract.currency || 'RUB'),
            note: `Маржа ${formatMoney(Number(metrics.margin || 0), contract.currency || 'RUB')}`,
            tone: Number(metrics.margin || 0) >= 0 ? 'accent' : 'critical',
        },
    ]));

    setContractHtml('contract360Finance', renderContract360List(
        finance,
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title || 'Финансовая операция'}</div>
                    <div class="client360-item-meta">${item.kind === 'incoming' ? 'Входящий' : 'Исходящий'} · ${contractStateLabel(item.status || 'planned')}</div>
                </div>
                <div class="client360-item-side">${formatMoney(item.amount || 0, item.currency || contract.currency || 'RUB')}</div>
            </div>
        `,
        'Финансовых операций по договору пока нет.'
    ));

    const paymentAlerts = [];
    if (Number(metrics.receivable_open || 0) > 0) {
        paymentAlerts.push({
            title: 'Контроль дебиторки',
            meta: `Открыто ${formatMoney(Number(metrics.receivable_open || 0), contract.currency || 'RUB')} по входящим платежам`,
            side: 'Требует оплаты',
        });
    }
    if (Number(metrics.payable_open || 0) > 0) {
        paymentAlerts.push({
            title: 'Контроль кредиторки',
            meta: `Открыто ${formatMoney(Number(metrics.payable_open || 0), contract.currency || 'RUB')} по исходящим обязательствам`,
            side: 'К оплате',
        });
    }
    finance
        .filter(item => isContractOverdue({ status: item.status, end_date: item.due_date || item.deadline || '' }))
        .slice(0, 5)
        .forEach(item => {
            paymentAlerts.push({
                title: item.title || 'Операция с риском просрочки',
                meta: contractCompactMeta([
                    item.due_date ? `Срок ${item.due_date}` : '',
                    item.kind === 'incoming' ? 'входящий платеж' : 'исходящий платеж',
                    formatMoney(item.amount || 0, item.currency || contract.currency || 'RUB'),
                ]),
                side: 'Просрочено',
            });
        });

    setContractHtml('contract360PenaltyFeed', renderContract360List(
        paymentAlerts,
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title}</div>
                    <div class="client360-item-meta">${item.meta}</div>
                </div>
                <div class="client360-item-side">${item.side}</div>
            </div>
        `,
        'Пени, просрочки и критичные отклонения по оплатам пока не выявлены.'
    ));

    setContractHtml('contract360Stages', renderContract360List(
        [
            ...(production || []).map(item => ({ ...item, _group: 'production' })),
            ...(resources || []).map(item => ({ ...item, _group: 'resource' })),
            ...(service_cases || []).map(item => ({ ...item, _group: 'service' })),
        ],
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${
                    item._group === 'production' ? (item.order_name || 'Производственный заказ') :
                    item._group === 'resource' ? (item.resource_name || 'Ресурс') :
                    (item.title || 'Сервисный кейс')
                }</div>
                <div class="client360-item-meta">${
                    item._group === 'production' ? `Производство · ${contractStateLabel(item.stage || '—')} · ${item.progress || 0}%` :
                    item._group === 'resource' ? `Ресурс · ${item.department || 'без отдела'} · ${item.load_percent || 0}%` :
                    `Сервис · ${contractStateLabel(item.status || '—')} · ${item.case_type || 'обращение'}`
                }</div>
            </div>
        `,
        'Производственные этапы, ресурсы и сервисные кейсы по договору пока не заведены.'
    ));

    setContractHtml('contract360Documents', renderContract360List(
        documents,
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${item.subject || 'Документ'}</div>
                <div class="client360-item-meta">${contractCompactMeta([
                    item.registration_number || item.number || '—',
                    item.type || 'Документ',
                    item.d_date || 'без даты',
                    item.file_url ? 'есть файл' : 'без файла',
                ])}</div>
            </div>
        `,
        'Документы по договору пока не привязаны.'
    ));

    setContractHtml('contract360Approvals', renderContract360List(
        erp_processes,
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title || 'ERP-процесс'}</div>
                    <div class="client360-item-meta">${item.stage_label || contractStateLabel(item.current_stage || 'этап')} · ${contractStateLabel(item.status || 'новый')}</div>
                </div>
                <div class="client360-item-side">${item.due_date || formatMoney(item.amount || 0, item.currency || contract.currency || 'RUB')}</div>
            </div>
        `,
        'Активных маршрутов согласования по договору пока нет.'
    ));

    const letters = (documents || []).filter(item => {
        const type = String(item.type || '').toLowerCase();
        return type === 'incoming' || type === 'outgoing' || type.startsWith('internal');
    });
    setContractHtml('contract360Letters', renderContract360List(
        letters,
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${item.subject || 'Письмо'}</div>
                <div class="client360-item-meta">${contractCompactMeta([
                    item.registration_number || item.number || 'без рег. номера',
                    item.sender_name || '',
                    item.recipient_name || '',
                    item.delivery_method || '',
                ])}</div>
                <div class="client360-item-meta">${contractCompactMeta([
                    item.resolution_deadline ? `Срок ответа ${item.resolution_deadline}` : '',
                    item.executor_name || item.resolution_assignee || '',
                    item.project_id ? `Проект #${item.project_id}` : '',
                ])}</div>
            </div>
        `,
        'Связанных писем по договору пока нет.'
    ));

    setContractHtml('contract360Tasks', renderContract360List(
        tasks,
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title || 'Задача'}</div>
                    <div class="client360-item-meta">${contractCompactMeta([
                        item.executor ? `Исполнитель: ${item.executor}` : '',
                        item.deadline ? `Срок ${item.deadline}` : '',
                        item.status || '',
                    ])}</div>
                </div>
                <div class="client360-item-side">${item.priority || 'normal'}</div>
            </div>
        `,
        'Задач по договору пока нет.'
    ));

    setContractHtml('contract360Costs', renderContract360List(
        [
            ...(purchases || []).map(item => ({ ...item, _group: 'purchase' })),
            ...(expenses || []).map(item => ({ ...item, _group: 'expense' })),
            ...(requests || []).map(item => ({ ...item, _group: 'request' })),
            ...(sales || []).map(item => ({ ...item, _group: 'sales' })),
        ],
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${
                    item._group === 'purchase' ? (item.item_name || 'Закупка') :
                    item._group === 'expense' ? (item.title || 'Расход') :
                    item._group === 'request' ? (item.title || 'Внутренняя заявка') :
                    `${item.doc_type || 'Документ'} ${item.doc_number || ''}`
                }</div>
                <div class="client360-item-meta">${
                    item._group === 'purchase' ? `Закупка · ${contractStateLabel(item.status || '—')}` :
                    item._group === 'expense' ? `Расход · ${contractStateLabel(item.status || '—')}` :
                    item._group === 'request' ? `Заявка · ${contractStateLabel(item.status || '—')}` :
                    `Реализация · ${contractStateLabel(item.status || '—')}`
                }</div>
                <div class="client360-item-meta">${
                    item._group === 'purchase' ? formatMoney(item.total_amount || 0, contract.currency || 'RUB') :
                    item._group === 'expense' ? formatMoney(item.amount || 0, item.currency || contract.currency || 'RUB') :
                    item._group === 'request' ? contractCompactMeta([item.target_role || '', item.deadline || '']) :
                    formatMoney(item.amount || 0, item.currency || contract.currency || 'RUB')
                }</div>
            </div>
        `,
        'Затраты, закупки и заявки по договору пока не заведены.'
    ));

    setContractHtml('contract360Claims', renderContract360List(
        claims,
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${item.number || 'Претензия'}</div>
                <div class="client360-item-meta">${contractCompactMeta([
                    item.addressee || '',
                    item.deadline ? `Ответ до ${item.deadline}` : '',
                    contractStateLabel(item.status || 'draft'),
                ])}</div>
                <div class="client360-item-meta">${formatMoney(item.amount || 0, contract.currency || 'RUB')}</div>
            </div>
        `,
        'Претензий по договорному контуру пока нет.'
    ));

    setContractHtml('contract360Courts', renderContract360List(
        courts,
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${item.number || 'Судебное дело'}</div>
                <div class="client360-item-meta">${contractCompactMeta([
                    item.court_name || '',
                    item.stage || '',
                    item.next_hearing ? `Следующее заседание ${item.next_hearing}` : '',
                ])}</div>
                <div class="client360-item-meta">${contractCompactMeta([
                    item.plaintiff || '',
                    item.defendant || '',
                    formatMoney(item.amount || 0, contract.currency || 'RUB'),
                ])}</div>
            </div>
        `,
        'Судебных дел по договору пока нет.'
    ));

    const accessRows = [];
    const accessRoles = new Set();
    projects.forEach(project => {
        (project.allowed_roles || []).forEach(role => accessRoles.add(role));
    });
    if (contract.manager_name) {
        accessRows.push({
            title: 'Ответственный менеджер',
            meta: contract.manager_name,
            side: contract.manager_email || 'Без e-mail',
        });
    }
    if (accessRoles.size) {
        accessRows.push({
            title: 'Разрешённые роли',
            meta: Array.from(accessRoles).join(', '),
            side: `${accessRoles.size} ролей`,
        });
    }
    employees.slice(0, 10).forEach(employee => {
        accessRows.push({
            title: employee.name,
            meta: contractCompactMeta([employee.role || '', employee.email || '']),
            side: `${employee.load_percent || 0}%`,
        });
    });
    setContractHtml('contract360Access', renderContract360List(
        accessRows,
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title}</div>
                    <div class="client360-item-meta">${item.meta}</div>
                </div>
                <div class="client360-item-side">${item.side}</div>
            </div>
        `,
        'Права доступа и состав рабочей группы по договору пока не определены.'
    ));

    setContractHtml('contract360ERP', renderContract360List(
        erp_processes,
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title || 'ERP-процесс'}</div>
                    <div class="client360-item-meta">${contractCompactMeta([
                        item.stage_label || contractStateLabel(item.current_stage || 'этап'),
                        contractStateLabel(item.status || 'новый'),
                        item.owner_name || '',
                    ])}</div>
                </div>
                <div class="client360-item-side">${item.due_date || '—'}</div>
            </div>
        `,
        'ERP-маршрутов по договору пока нет.'
    ));

    setContractHtml('contract360Audit', renderContract360List(
        audit,
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${contractAuditActionLabel(item.action || 'действие')}</div>
                <div class="client360-item-meta">${item.actor_name || item.actor_email || 'Система'} · ${contractEntityLabel(item.entity_type || 'сущность')} #${item.entity_id || ''}</div>
            </div>
        `,
        'Аудит по договору пока пуст.'
    ));

    setContractHtml('contract360Timeline', renderContract360List(
        timeline,
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${item.title || 'Событие'}</div>
                <div class="client360-item-meta">${item.meta || ''}</div>
                <div class="client360-item-meta">${item.time || ''}</div>
            </div>
        `,
        'Событий по договору пока нет.'
    ));
}
