let currentLeadViewMode = 'registry';
let currentLeadSearch = '';
let currentLeadStage = '';
let currentLeadResponsible = '';
let currentLeadSort = 'due_asc';
let currentLeadId = 0;
let editingLeadId = 0;

let currentDealViewMode = 'registry';
let currentDealSearch = '';
let currentDealStage = '';
let currentDealResponsible = '';
let currentDealSort = 'due_asc';
let currentDealId = 0;
let editingDealId = 0;

function crmEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function crmFormatMoney(value, currency = 'RUB') {
    if (typeof formatMoney === 'function') return formatMoney(value || 0, currency || 'RUB');
    return `${Number(value || 0).toLocaleString('ru-RU')} ${currency || 'RUB'}`;
}

function crmParseRuDate(value) {
    const raw = String(value || '').trim();
    const match = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    if (!match) return null;
    const date = new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]));
    return Number.isNaN(date.getTime()) ? null : date;
}

function crmDaysUntil(value) {
    const date = crmParseRuDate(value);
    if (!date) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((date - today) / 86400000);
}

function crmToneByDueDate(value) {
    const days = crmDaysUntil(value);
    if (days === null) return 'neutral';
    if (days < 0) return 'critical';
    if (days <= 1) return 'attention';
    return 'positive';
}

function crmStageLabel(stage) {
    const map = {
        new: 'Новый',
        qualified: 'Квалифицирован',
        proposal: 'КП / предложение',
        won: 'Конвертирован',
        lost: 'Потерян',
        qualification: 'Квалификация',
        negotiation: 'Переговоры',
    };
    return map[String(stage || '')] || (stage || 'Без стадии');
}

function crmPriorityLabel(priority) {
    return {
        low: 'Низкий',
        normal: 'Нормальный',
        high: 'Высокий',
    }[String(priority || '')] || 'Нормальный';
}

function crmActivityLabel(type) {
    return {
        note: 'Заметка',
        call: 'Звонок',
        email: 'Письмо',
        meeting: 'Встреча',
        task: 'Задача',
    }[String(type || '')] || 'Активность';
}

function crmCollectResponsibles(rows = []) {
    return Array.from(new Set((rows || []).map(row => String(row.responsible || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ru'));
}

function crmPresetStorageKey(entityType) {
    const userKey = String(currentUser?.email || currentUser?.name || 'default')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9а-яё._-]+/gi, '_');
    return `korda_crm_ops_presets_v1:${userKey}:${entityType}`;
}

function crmReadPresets(entityType) {
    try {
        const raw = localStorage.getItem(crmPresetStorageKey(entityType));
        const parsed = JSON.parse(raw || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function crmWritePresets(entityType, presets) {
    localStorage.setItem(crmPresetStorageKey(entityType), JSON.stringify(presets || []));
}

function crmFillPresetSelect(selectId, presets = []) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const currentValue = el.value || '';
    el.innerHTML = `<option value="">Пресет фильтра</option>${presets.map(item => `
        <option value="${crmEscape(item.name)}">${crmEscape(item.name)}</option>
    `).join('')}`;
    el.value = presets.some(item => item.name === currentValue) ? currentValue : '';
}

function crmDateSortValue(value, direction = 'asc') {
    const date = crmParseRuDate(value);
    if (date) return date.getTime();
    return direction === 'asc' ? Number.MAX_SAFE_INTEGER : Number.MIN_SAFE_INTEGER;
}

function crmTextCompare(left, right) {
    return String(left || '').localeCompare(String(right || ''), 'ru');
}

function crmSortLeadRows(rows = []) {
    const sorted = rows.slice();
    sorted.sort((left, right) => {
        switch (currentLeadSort) {
        case 'due_desc':
            return crmDateSortValue(right.next_action_date, 'desc') - crmDateSortValue(left.next_action_date, 'desc');
        case 'budget_desc':
            return Number(right.budget || 0) - Number(left.budget || 0);
        case 'title_asc':
            return crmTextCompare(left.title, right.title);
        case 'probability_desc':
            return Number(right.probability || 0) - Number(left.probability || 0);
        case 'due_asc':
        default:
            return crmDateSortValue(left.next_action_date, 'asc') - crmDateSortValue(right.next_action_date, 'asc');
        }
    });
    return sorted;
}

function crmSortDealRows(rows = []) {
    const sorted = rows.slice();
    sorted.sort((left, right) => {
        switch (currentDealSort) {
        case 'due_desc':
            return crmDateSortValue(right.next_action_date, 'desc') - crmDateSortValue(left.next_action_date, 'desc');
        case 'amount_desc':
            return Number(right.amount || 0) - Number(left.amount || 0);
        case 'title_asc':
            return crmTextCompare(left.title, right.title);
        case 'margin_desc':
            return Number(right.margin_percent || 0) - Number(left.margin_percent || 0);
        case 'due_asc':
        default:
            return crmDateSortValue(left.next_action_date, 'asc') - crmDateSortValue(right.next_action_date, 'asc');
        }
    });
    return sorted;
}

function fillResponsibleSelect(selectId, rows = [], currentValue = '') {
    const el = document.getElementById(selectId);
    if (!el) return;
    const options = crmCollectResponsibles(rows).map(name => `<option value="${crmEscape(name)}" ${currentValue === name ? 'selected' : ''}>${crmEscape(name)}</option>`).join('');
    el.innerHTML = `<option value="">Все ответственные</option>${options}`;
    el.value = currentValue || '';
}

function leadRowsFiltered() {
    return crmSortLeadRows((crmLeadsDB || []).filter(row => {
        if (currentLeadStage && String(row.stage || '') !== currentLeadStage) return false;
        if (currentLeadResponsible && String(row.responsible || '') !== currentLeadResponsible) return false;
        if (currentLeadSearch) {
            const haystack = [row.title, row.client_name, row.contact_name, row.source, row.next_action].join(' ').toLowerCase();
            if (!haystack.includes(currentLeadSearch.toLowerCase())) return false;
        }
        return true;
    }));
}

function dealRowsFiltered() {
    return crmSortDealRows((crmDealsDB || []).filter(row => {
        if (currentDealStage && String(row.stage || '') !== currentDealStage) return false;
        if (currentDealResponsible && String(row.responsible || '') !== currentDealResponsible) return false;
        if (currentDealSearch) {
            const haystack = [row.title, row.client_name, row.contract_number, row.next_action].join(' ').toLowerCase();
            if (!haystack.includes(currentDealSearch.toLowerCase())) return false;
        }
        return true;
    }));
}

function renderLeadSummary() {
    const rows = leadRowsFiltered();
    const mount = document.getElementById('leadSummaryStrip');
    if (!mount) return;
    const hot = rows.filter(row => crmToneByDueDate(row.next_action_date) === 'critical' || String(row.priority || '') === 'high').length;
    const qualified = rows.filter(row => ['qualified', 'proposal'].includes(String(row.stage || ''))).length;
    const budget = rows.reduce((sum, row) => sum + Number(row.budget || 0), 0);
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Лиды в контуре</div><div class="crm-summary-value">${rows.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Тёплые лиды</div><div class="crm-summary-value">${qualified}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Нужен быстрый шаг</div><div class="crm-summary-value">${hot}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Потенциал</div><div class="crm-summary-value">${crmFormatMoney(budget)}</div></div>
    `;
}

function renderDealSummary() {
    const rows = dealRowsFiltered();
    const mount = document.getElementById('dealSummaryStrip');
    if (!mount) return;
    const pipeline = rows.reduce((sum, row) => sum + Number(row.amount || 0), 0);
    const hot = rows.filter(row => crmToneByDueDate(row.next_action_date) === 'critical' || String(row.stage || '') === 'negotiation').length;
    const won = rows.filter(row => String(row.stage || '') === 'won').length;
    const avgMargin = rows.length ? Math.round(rows.reduce((sum, row) => sum + Number(row.margin_percent || 0), 0) / rows.length) : 0;
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Сделок в работе</div><div class="crm-summary-value">${rows.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Горячие переговоры</div><div class="crm-summary-value">${hot}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Выиграно</div><div class="crm-summary-value">${won}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Pipeline</div><div class="crm-summary-value">${crmFormatMoney(pipeline)}</div><div class="crm-summary-meta">ср. маржа ${avgMargin}%</div></div>
    `;
}

function renderCrmActivities(entityType, entityId, activities = []) {
    if (!activities.length) {
        return `<div class="empty-state">Активностей пока нет.</div>`;
    }
    return activities.map(item => `
        <div class="crm-activity-item">
            <div class="crm-activity-main">
                <div class="crm-activity-title">${crmEscape(item.subject || crmActivityLabel(item.activity_type))}</div>
                <div class="crm-activity-meta">${crmEscape(crmActivityLabel(item.activity_type))} · ${crmEscape(item.owner_name || 'не назначен')} · ${crmEscape(item.due_date || 'без срока')}</div>
                <div class="crm-activity-text">${crmEscape(item.summary || '')}</div>
            </div>
            <button class="btn-secondary" onclick="toggleCrmActivityStatus(${item.id}, '${crmEscape(entityType)}', ${entityId}, '${item.status === 'done' ? 'open' : 'done'}')">${item.status === 'done' ? 'Открыть' : 'Готово'}</button>
        </div>
    `).join('');
}

function renderLeadDetail(row) {
    if (!row) {
        return `<div class="empty-state">Выбери лид из списка или открой создание нового.</div>`;
    }
    return `
        <div class="crm-detail-card">
            <div class="crm-detail-head">
                <div>
                    <div class="crm-detail-title">${crmEscape(row.title || 'Без названия')}</div>
                    <div class="crm-detail-meta">${crmEscape(row.client_name || 'Без клиента')} · ${crmEscape(row.contact_name || 'Без контакта')}</div>
                </div>
                <div class="crm-badge crm-badge--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</div>
            </div>
            <div class="crm-detail-grid">
                <div><span class="crm-detail-label">Источник</span><strong>${crmEscape(row.source || '—')}</strong></div>
                <div><span class="crm-detail-label">Ответственный</span><strong>${crmEscape(row.responsible || '—')}</strong></div>
                <div><span class="crm-detail-label">Потенциал</span><strong>${crmFormatMoney(row.budget, row.currency)}</strong></div>
                <div><span class="crm-detail-label">Вероятность</span><strong>${Math.round(Number(row.probability || 0))}%</strong></div>
                <div><span class="crm-detail-label">Следующий шаг</span><strong>${crmEscape(row.next_action || '—')}</strong></div>
                <div><span class="crm-detail-label">Дата шага</span><strong>${crmEscape(row.next_action_date || '—')}</strong></div>
            </div>
            <div class="crm-detail-actions">
                <button class="btn-secondary" onclick="openLeadEditor(${row.id})">Редактировать</button>
                <button class="btn-secondary" onclick="convertLeadToDeal(${row.id})">Конвертировать в сделку</button>
            </div>
            <div class="crm-tags">${(row.tags || []).map(tag => `<span class="crm-tag">${crmEscape(tag)}</span>`).join('')}</div>
            <div class="crm-detail-note">${crmEscape(row.comment || 'Комментарий не заполнен.')}</div>
            <div class="crm-activity-block">
                <div class="section-header"><div><h3 class="section-title">Активности</h3><p class="section-subtitle">Следующий шаг, звонки, письма и внутренние задачи.</p></div></div>
                <div class="crm-activity-form">
                    <select id="leadActivityType" class="auth-input">
                        <option value="call">Звонок</option>
                        <option value="email">Письмо</option>
                        <option value="meeting">Встреча</option>
                        <option value="task">Задача</option>
                        <option value="note">Заметка</option>
                    </select>
                    <input id="leadActivitySubject" class="auth-input" type="text" placeholder="Тема активности">
                    <input id="leadActivityDueDate" class="auth-input" type="text" placeholder="дд.мм.гггг">
                    <textarea id="leadActivitySummary" class="auth-input" rows="3" placeholder="Что нужно сделать"></textarea>
                    <button class="btn-primary" onclick="createCrmActivity('lead', ${row.id})">Добавить активность</button>
                </div>
                <div class="crm-activity-list">${renderCrmActivities('lead', row.id, row.activities || [])}</div>
            </div>
        </div>
    `;
}

function renderDealDetail(row) {
    if (!row) {
        return `<div class="empty-state">Выбери сделку из списка или открой создание новой.</div>`;
    }
    return `
        <div class="crm-detail-card">
            <div class="crm-detail-head">
                <div>
                    <div class="crm-detail-title">${crmEscape(row.title || 'Без названия')}</div>
                    <div class="crm-detail-meta">${crmEscape(row.client_name || 'Без клиента')} · ${crmEscape(row.contract_number || 'Без номера КП')}</div>
                </div>
                <div class="crm-badge crm-badge--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</div>
            </div>
            <div class="crm-detail-grid">
                <div><span class="crm-detail-label">Сумма</span><strong>${crmFormatMoney(row.amount, row.currency)}</strong></div>
                <div><span class="crm-detail-label">Маржа</span><strong>${Math.round(Number(row.margin_percent || 0))}%</strong></div>
                <div><span class="crm-detail-label">Вероятность</span><strong>${Math.round(Number(row.probability || 0))}%</strong></div>
                <div><span class="crm-detail-label">Ответственный</span><strong>${crmEscape(row.responsible || '—')}</strong></div>
                <div><span class="crm-detail-label">Следующий шаг</span><strong>${crmEscape(row.next_action || '—')}</strong></div>
                <div><span class="crm-detail-label">План закрытия</span><strong>${crmEscape(row.expected_close_date || '—')}</strong></div>
            </div>
            <div class="crm-detail-actions">
                <button class="btn-secondary" onclick="openDealEditor(${row.id})">Редактировать</button>
            </div>
            <div class="crm-tags">${(row.tags || []).map(tag => `<span class="crm-tag">${crmEscape(tag)}</span>`).join('')}</div>
            <div class="crm-detail-note">${crmEscape(row.comment || 'Комментарий не заполнен.')}</div>
            <div class="crm-activity-block">
                <div class="section-header"><div><h3 class="section-title">Активности</h3><p class="section-subtitle">Коммерческие шаги по текущей сделке.</p></div></div>
                <div class="crm-activity-form">
                    <select id="dealActivityType" class="auth-input">
                        <option value="call">Звонок</option>
                        <option value="email">Письмо</option>
                        <option value="meeting">Встреча</option>
                        <option value="task">Задача</option>
                        <option value="note">Заметка</option>
                    </select>
                    <input id="dealActivitySubject" class="auth-input" type="text" placeholder="Тема активности">
                    <input id="dealActivityDueDate" class="auth-input" type="text" placeholder="дд.мм.гггг">
                    <textarea id="dealActivitySummary" class="auth-input" rows="3" placeholder="Что нужно сделать"></textarea>
                    <button class="btn-primary" onclick="createCrmActivity('deal', ${row.id})">Добавить активность</button>
                </div>
                <div class="crm-activity-list">${renderCrmActivities('deal', row.id, row.activities || [])}</div>
            </div>
        </div>
    `;
}

function renderLeadRegistry() {
    const rows = leadRowsFiltered();
    if (!currentLeadId && rows.length) currentLeadId = Number(rows[0].id || 0);
    const selected = rows.find(row => Number(row.id) === Number(currentLeadId)) || null;
    return `
        <div class="crm-registry-layout">
            <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 340px;">
                        <col style="width: 160px;">
                        <col style="width: 220px;">
                        <col style="width: 320px;">
                        <col style="width: 160px;">
                        <col style="width: 180px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Лид</th>
                            <th>Источник</th>
                            <th>Ответственный</th>
                            <th>Следующее действие</th>
                            <th class="is-num">Потенциал</th>
                            <th>Стадия</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr class="${Number(row.id) === Number(currentLeadId) ? 'is-selected' : ''}" onclick="selectLeadRow(${row.id})">
                                <td class="crm-title-cell"><strong>${crmEscape(row.title || '—')}</strong><div class="table-subtext">${crmEscape(row.client_name || '—')}</div></td>
                                <td class="crm-meta-cell"><span class="crm-cell-single">${crmEscape(row.source || '—')}</span></td>
                                <td class="crm-meta-cell"><span class="crm-cell-single">${crmEscape(row.responsible || '—')}</span></td>
                                <td class="crm-action-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span><div class="table-subtext">${crmEscape(row.next_action || '—')}</div></td>
                                <td class="is-num amount crm-amount-cell">${crmFormatMoney(row.budget, row.currency)}</td>
                                <td class="crm-stage-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</span></td>
                            </tr>
                        `).join('') || '<tr><td colspan="6"><div class="empty-state">Лиды по текущему фильтру не найдены.</div></td></tr>'}
                    </tbody>
                </table>
            </div>
            ${renderLeadDetail(selected)}
        </div>
    `;
}

function renderDealRegistry() {
    const rows = dealRowsFiltered();
    if (!currentDealId && rows.length) currentDealId = Number(rows[0].id || 0);
    const selected = rows.find(row => Number(row.id) === Number(currentDealId)) || null;
    return `
        <div class="crm-registry-layout">
            <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 360px;">
                        <col style="width: 240px;">
                        <col style="width: 320px;">
                        <col style="width: 170px;">
                        <col style="width: 120px;">
                        <col style="width: 180px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Сделка</th>
                            <th>Клиент</th>
                            <th>Следующее действие</th>
                            <th class="is-num">Сумма</th>
                            <th class="is-num">Маржа</th>
                            <th>Стадия</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr class="${Number(row.id) === Number(currentDealId) ? 'is-selected' : ''}" onclick="selectDealRow(${row.id})">
                                <td class="crm-title-cell"><strong>${crmEscape(row.title || '—')}</strong><div class="table-subtext">${crmEscape(row.contract_number || 'без номера')}</div></td>
                                <td class="crm-meta-cell"><span class="crm-cell-single">${crmEscape(row.client_name || '—')}</span></td>
                                <td class="crm-action-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span><div class="table-subtext">${crmEscape(row.next_action || '—')}</div></td>
                                <td class="is-num amount crm-amount-cell">${crmFormatMoney(row.amount, row.currency)}</td>
                                <td class="is-num crm-amount-cell">${Math.round(Number(row.margin_percent || 0))}%</td>
                                <td class="crm-stage-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</span></td>
                            </tr>
                        `).join('') || '<tr><td colspan="6"><div class="empty-state">Сделки по текущему фильтру не найдены.</div></td></tr>'}
                    </tbody>
                </table>
            </div>
            ${renderDealDetail(selected)}
        </div>
    `;
}

function renderKanban(columns, rows, entityType) {
    return `
        <div class="crm-kanban">
            ${columns.map(column => `
                <div class="crm-kanban-column">
                    <div class="crm-kanban-head">
                        <div class="crm-kanban-title">${crmEscape(column.label)}</div>
                        <div class="crm-kanban-count">${rows.filter(row => String(row.stage || '') === column.key).length}</div>
                    </div>
                    <div class="crm-kanban-cards">
                        ${rows.filter(row => String(row.stage || '') === column.key).map(row => `
                            <button class="crm-kanban-card" onclick="${entityType === 'lead' ? `selectLeadRow(${row.id})` : `selectDealRow(${row.id})`}">
                                <div class="crm-kanban-card-title">${crmEscape(row.title || '—')}</div>
                                <div class="crm-kanban-card-meta">${crmEscape(row.client_name || '—')}</div>
                                <div class="crm-kanban-card-footer">
                                    <span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span>
                                    <strong>${entityType === 'lead' ? crmFormatMoney(row.budget, row.currency) : crmFormatMoney(row.amount, row.currency)}</strong>
                                </div>
                            </button>
                        `).join('') || '<div class="empty-state">Пусто</div>'}
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function openLeadEditor(leadId = 0) {
    editingLeadId = Number(leadId || 0);
    const panel = document.getElementById('leadEditorPanel');
    if (!panel) return;
    const row = (crmLeadsDB || []).find(item => Number(item.id) === editingLeadId) || { tags: [] };
    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="crm-editor-grid">
            <input id="leadFormTitle" class="auth-input" type="text" placeholder="Название лида" value="${crmEscape(row.title || '')}">
            <input id="leadFormClient" class="auth-input" type="text" placeholder="Компания" value="${crmEscape(row.client_name || '')}">
            <input id="leadFormContact" class="auth-input" type="text" placeholder="Контакт" value="${crmEscape(row.contact_name || '')}">
            <input id="leadFormEmail" class="auth-input" type="text" placeholder="Email" value="${crmEscape(row.contact_email || '')}">
            <input id="leadFormPhone" class="auth-input" type="text" placeholder="Телефон" value="${crmEscape(row.contact_phone || '')}">
            <input id="leadFormSource" class="auth-input" type="text" placeholder="Источник" value="${crmEscape(row.source || '')}">
            <select id="leadFormStage" class="auth-input">
                <option value="new" ${row.stage === 'new' ? 'selected' : ''}>Новый</option>
                <option value="qualified" ${row.stage === 'qualified' ? 'selected' : ''}>Квалифицирован</option>
                <option value="proposal" ${row.stage === 'proposal' ? 'selected' : ''}>КП / предложение</option>
                <option value="won" ${row.stage === 'won' ? 'selected' : ''}>Конвертирован</option>
                <option value="lost" ${row.stage === 'lost' ? 'selected' : ''}>Потерян</option>
            </select>
            <input id="leadFormResponsible" class="auth-input" type="text" placeholder="Ответственный" value="${crmEscape(row.responsible || currentUser?.name || '')}">
            <input id="leadFormNextAction" class="auth-input" type="text" placeholder="Следующее действие" value="${crmEscape(row.next_action || '')}">
            <input id="leadFormNextActionDate" class="auth-input" type="text" placeholder="дд.мм.гггг" value="${crmEscape(row.next_action_date || '')}">
            <input id="leadFormBudget" class="auth-input" type="number" placeholder="Потенциал" value="${crmEscape(row.budget || 0)}">
            <input id="leadFormProbability" class="auth-input" type="number" placeholder="Вероятность %" value="${crmEscape(row.probability || 0)}">
            <input id="leadFormTags" class="auth-input" type="text" placeholder="Теги через запятую" value="${crmEscape((row.tags || []).join(', '))}">
            <textarea id="leadFormComment" class="auth-input" rows="3" placeholder="Комментарий">${crmEscape(row.comment || '')}</textarea>
        </div>
        <div class="crm-editor-actions">
            <button class="btn-secondary" onclick="closeLeadEditor()">Скрыть</button>
            <button class="btn-primary" onclick="saveLead()">Сохранить</button>
        </div>
    `;
}

function openDealEditor(dealId = 0) {
    editingDealId = Number(dealId || 0);
    const panel = document.getElementById('dealEditorPanel');
    if (!panel) return;
    const row = (crmDealsDB || []).find(item => Number(item.id) === editingDealId) || { tags: [] };
    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="crm-editor-grid">
            <input id="dealFormTitle" class="auth-input" type="text" placeholder="Название сделки" value="${crmEscape(row.title || '')}">
            <input id="dealFormClient" class="auth-input" type="text" placeholder="Компания" value="${crmEscape(row.client_name || '')}">
            <input id="dealFormContract" class="auth-input" type="text" placeholder="Номер КП / договора" value="${crmEscape(row.contract_number || '')}">
            <select id="dealFormStage" class="auth-input">
                <option value="qualification" ${row.stage === 'qualification' ? 'selected' : ''}>Квалификация</option>
                <option value="proposal" ${row.stage === 'proposal' ? 'selected' : ''}>Предложение</option>
                <option value="negotiation" ${row.stage === 'negotiation' ? 'selected' : ''}>Переговоры</option>
                <option value="won" ${row.stage === 'won' ? 'selected' : ''}>Выиграно</option>
                <option value="lost" ${row.stage === 'lost' ? 'selected' : ''}>Потеряно</option>
            </select>
            <input id="dealFormResponsible" class="auth-input" type="text" placeholder="Ответственный" value="${crmEscape(row.responsible || currentUser?.name || '')}">
            <input id="dealFormNextAction" class="auth-input" type="text" placeholder="Следующее действие" value="${crmEscape(row.next_action || '')}">
            <input id="dealFormNextActionDate" class="auth-input" type="text" placeholder="дд.мм.гггг" value="${crmEscape(row.next_action_date || '')}">
            <input id="dealFormExpectedCloseDate" class="auth-input" type="text" placeholder="План закрытия" value="${crmEscape(row.expected_close_date || '')}">
            <input id="dealFormAmount" class="auth-input" type="number" placeholder="Сумма" value="${crmEscape(row.amount || 0)}">
            <input id="dealFormMargin" class="auth-input" type="number" placeholder="Маржа %" value="${crmEscape(row.margin_percent || 0)}">
            <input id="dealFormProbability" class="auth-input" type="number" placeholder="Вероятность %" value="${crmEscape(row.probability || 0)}">
            <input id="dealFormTags" class="auth-input" type="text" placeholder="Теги через запятую" value="${crmEscape((row.tags || []).join(', '))}">
            <textarea id="dealFormComment" class="auth-input" rows="3" placeholder="Комментарий">${crmEscape(row.comment || '')}</textarea>
        </div>
        <div class="crm-editor-actions">
            <button class="btn-secondary" onclick="closeDealEditor()">Скрыть</button>
            <button class="btn-primary" onclick="saveDeal()">Сохранить</button>
        </div>
    `;
}

function closeLeadEditor() {
    editingLeadId = 0;
    const panel = document.getElementById('leadEditorPanel');
    if (panel) panel.style.display = 'none';
}

function closeDealEditor() {
    editingDealId = 0;
    const panel = document.getElementById('dealEditorPanel');
    if (panel) panel.style.display = 'none';
}

function selectLeadRow(id) {
    currentLeadId = Number(id || 0);
    renderLeads();
}

function selectDealRow(id) {
    currentDealId = Number(id || 0);
    renderDeals();
}

async function saveLead() {
    const payload = {
        title: document.getElementById('leadFormTitle')?.value || '',
        client_name: document.getElementById('leadFormClient')?.value || '',
        contact_name: document.getElementById('leadFormContact')?.value || '',
        contact_email: document.getElementById('leadFormEmail')?.value || '',
        contact_phone: document.getElementById('leadFormPhone')?.value || '',
        source: document.getElementById('leadFormSource')?.value || '',
        stage: document.getElementById('leadFormStage')?.value || 'new',
        responsible: document.getElementById('leadFormResponsible')?.value || '',
        next_action: document.getElementById('leadFormNextAction')?.value || '',
        next_action_date: document.getElementById('leadFormNextActionDate')?.value || '',
        budget: Number(document.getElementById('leadFormBudget')?.value || 0),
        probability: Number(document.getElementById('leadFormProbability')?.value || 0),
        tags: String(document.getElementById('leadFormTags')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        comment: document.getElementById('leadFormComment')?.value || '',
        currency: 'RUB',
        priority: 'normal',
    };
    if (!payload.title.trim()) return customAlert('Укажи название лида.');
    const endpoint = editingLeadId ? `/crm/leads/${editingLeadId}` : '/crm/leads';
    const method = editingLeadId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить лид.');
    await loadCrmLeads();
    currentLeadId = Number(res.id || editingLeadId || currentLeadId);
    closeLeadEditor();
    renderLeads();
}

async function saveDeal() {
    const payload = {
        title: document.getElementById('dealFormTitle')?.value || '',
        client_name: document.getElementById('dealFormClient')?.value || '',
        contract_number: document.getElementById('dealFormContract')?.value || '',
        stage: document.getElementById('dealFormStage')?.value || 'qualification',
        responsible: document.getElementById('dealFormResponsible')?.value || '',
        next_action: document.getElementById('dealFormNextAction')?.value || '',
        next_action_date: document.getElementById('dealFormNextActionDate')?.value || '',
        expected_close_date: document.getElementById('dealFormExpectedCloseDate')?.value || '',
        amount: Number(document.getElementById('dealFormAmount')?.value || 0),
        margin_percent: Number(document.getElementById('dealFormMargin')?.value || 0),
        probability: Number(document.getElementById('dealFormProbability')?.value || 0),
        tags: String(document.getElementById('dealFormTags')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        comment: document.getElementById('dealFormComment')?.value || '',
        currency: 'RUB',
        priority: 'normal',
        status_color: '',
    };
    if (!payload.title.trim()) return customAlert('Укажи название сделки.');
    const endpoint = editingDealId ? `/crm/deals/${editingDealId}` : '/crm/deals';
    const method = editingDealId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить сделку.');
    await loadCrmDeals();
    currentDealId = Number(res.id || editingDealId || currentDealId);
    closeDealEditor();
    renderDeals();
}

async function createCrmActivity(entityType, entityId) {
    const prefix = entityType === 'lead' ? 'lead' : 'deal';
    const payload = {
        entity_type: entityType,
        entity_id: Number(entityId || 0),
        activity_type: document.getElementById(`${prefix}ActivityType`)?.value || 'note',
        subject: document.getElementById(`${prefix}ActivitySubject`)?.value || '',
        due_date: document.getElementById(`${prefix}ActivityDueDate`)?.value || '',
        summary: document.getElementById(`${prefix}ActivitySummary`)?.value || '',
        owner_name: currentUser?.name || '',
        status: 'open',
    };
    if (!payload.subject.trim()) return customAlert('Укажи тему активности.');
    const res = await apiCall('/crm/activities', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить активность.');
    if (entityType === 'lead') {
        await loadCrmLeads();
        renderLeads();
    } else {
        await loadCrmDeals();
        renderDeals();
    }
}

async function toggleCrmActivityStatus(activityId, entityType, entityId, status) {
    const res = await apiCall('/crm/activities', 'GET');
    const activities = Array.isArray(res) ? res : [];
    const row = activities.find(item => Number(item.id) === Number(activityId));
    if (!row) return customAlert('Активность не найдена.');
    const updatePayload = {
        entity_type: row.entity_type,
        entity_id: Number(row.entity_id || 0),
        activity_type: row.activity_type,
        subject: row.subject,
        summary: row.summary,
        due_date: row.due_date,
        status,
        owner_name: row.owner_name,
    };
    const saveRes = await apiCall(`/crm/activities/${activityId}`, 'PUT', updatePayload);
    if (!saveRes || saveRes.error) return customAlert(saveRes?.message || 'Не удалось обновить активность.');
    if (entityType === 'lead') {
        currentLeadId = Number(entityId || currentLeadId);
        await loadCrmLeads();
        renderLeads();
    } else {
        currentDealId = Number(entityId || currentDealId);
        await loadCrmDeals();
        renderDeals();
    }
}

async function convertLeadToDeal(leadId) {
    const res = await apiCall(`/crm/leads/${leadId}/convert`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось конвертировать лид.');
    await Promise.all([loadCrmLeads(), loadCrmDeals()]);
    currentDealId = Number(res.deal_id || 0);
    navigateTo('deals');
}

function setLeadViewMode(mode) {
    currentLeadViewMode = mode;
    renderLeads();
}

function setDealViewMode(mode) {
    currentDealViewMode = mode;
    renderDeals();
}

function applyLeadSearch(value) {
    currentLeadSearch = String(value || '').trim();
    renderLeads();
}

function applyDealSearch(value) {
    currentDealSearch = String(value || '').trim();
    renderDeals();
}

function setLeadStageFilter(value) {
    currentLeadStage = value || '';
    renderLeads();
}

function setDealStageFilter(value) {
    currentDealStage = value || '';
    renderDeals();
}

function setLeadResponsibleFilter(value) {
    currentLeadResponsible = value || '';
    renderLeads();
}

function setDealResponsibleFilter(value) {
    currentDealResponsible = value || '';
    renderDeals();
}

function setLeadSort(value) {
    currentLeadSort = value || 'due_asc';
    renderLeads();
}

function setDealSort(value) {
    currentDealSort = value || 'due_asc';
    renderDeals();
}

function saveLeadPreset() {
    const name = window.prompt('Название пресета для лидов');
    if (!name || !name.trim()) return;
    const presets = crmReadPresets('lead').filter(item => item.name !== name.trim());
    presets.push({
        name: name.trim(),
        search: currentLeadSearch,
        stage: currentLeadStage,
        responsible: currentLeadResponsible,
        sort: currentLeadSort,
    });
    presets.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    crmWritePresets('lead', presets);
    const presetSelect = document.getElementById('leadPresetSelect');
    if (presetSelect) presetSelect.value = name.trim();
    renderLeads();
}

function saveDealPreset() {
    const name = window.prompt('Название пресета для сделок');
    if (!name || !name.trim()) return;
    const presets = crmReadPresets('deal').filter(item => item.name !== name.trim());
    presets.push({
        name: name.trim(),
        search: currentDealSearch,
        stage: currentDealStage,
        responsible: currentDealResponsible,
        sort: currentDealSort,
    });
    presets.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    crmWritePresets('deal', presets);
    const presetSelect = document.getElementById('dealPresetSelect');
    if (presetSelect) presetSelect.value = name.trim();
    renderDeals();
}

function applyLeadPreset(name) {
    if (!name) {
        const presetSelect = document.getElementById('leadPresetSelect');
        if (presetSelect) presetSelect.value = '';
        return;
    }
    const preset = crmReadPresets('lead').find(item => item.name === name);
    if (!preset) return;
    currentLeadSearch = preset.search || '';
    currentLeadStage = preset.stage || '';
    currentLeadResponsible = preset.responsible || '';
    currentLeadSort = preset.sort || 'due_asc';
    renderLeads();
}

function applyDealPreset(name) {
    if (!name) {
        const presetSelect = document.getElementById('dealPresetSelect');
        if (presetSelect) presetSelect.value = '';
        return;
    }
    const preset = crmReadPresets('deal').find(item => item.name === name);
    if (!preset) return;
    currentDealSearch = preset.search || '';
    currentDealStage = preset.stage || '';
    currentDealResponsible = preset.responsible || '';
    currentDealSort = preset.sort || 'due_asc';
    renderDeals();
}

function resetLeadFilters() {
    currentLeadSearch = '';
    currentLeadStage = '';
    currentLeadResponsible = '';
    currentLeadSort = 'due_asc';
    const presetSelect = document.getElementById('leadPresetSelect');
    if (presetSelect) presetSelect.value = '';
    renderLeads();
}

function resetDealFilters() {
    currentDealSearch = '';
    currentDealStage = '';
    currentDealResponsible = '';
    currentDealSort = 'due_asc';
    const presetSelect = document.getElementById('dealPresetSelect');
    if (presetSelect) presetSelect.value = '';
    renderDeals();
}

async function renderLeads() {
    if (!Array.isArray(crmLeadsDB) || !crmLeadsDB.length) await loadCrmLeads();
    fillResponsibleSelect('leadResponsibleFilter', crmLeadsDB, currentLeadResponsible);
    crmFillPresetSelect('leadPresetSelect', crmReadPresets('lead'));
    renderLeadSummary();
    const searchInput = document.getElementById('leadSearchInput');
    const stageFilter = document.getElementById('leadStageFilter');
    const sortSelect = document.getElementById('leadSortSelect');
    if (searchInput) searchInput.value = currentLeadSearch;
    if (stageFilter) stageFilter.value = currentLeadStage;
    if (sortSelect) sortSelect.value = currentLeadSort;
    document.getElementById('leadModeRegistry')?.classList.toggle('active', currentLeadViewMode === 'registry');
    document.getElementById('leadModeKanban')?.classList.toggle('active', currentLeadViewMode === 'kanban');
    const mount = document.getElementById('leadsContentMount');
    if (!mount) return;
    const rows = leadRowsFiltered();
    mount.innerHTML = currentLeadViewMode === 'kanban'
        ? renderKanban([
            { key: 'new', label: 'Новые' },
            { key: 'qualified', label: 'Квалифицированы' },
            { key: 'proposal', label: 'КП / предложение' },
            { key: 'won', label: 'Конвертированы' },
            { key: 'lost', label: 'Потеряны' },
        ], rows, 'lead')
        : renderLeadRegistry();
}

async function renderDeals() {
    if (!Array.isArray(crmDealsDB) || !crmDealsDB.length) await loadCrmDeals();
    fillResponsibleSelect('dealResponsibleFilter', crmDealsDB, currentDealResponsible);
    crmFillPresetSelect('dealPresetSelect', crmReadPresets('deal'));
    renderDealSummary();
    const searchInput = document.getElementById('dealSearchInput');
    const stageFilter = document.getElementById('dealStageFilter');
    const sortSelect = document.getElementById('dealSortSelect');
    if (searchInput) searchInput.value = currentDealSearch;
    if (stageFilter) stageFilter.value = currentDealStage;
    if (sortSelect) sortSelect.value = currentDealSort;
    document.getElementById('dealModeRegistry')?.classList.toggle('active', currentDealViewMode === 'registry');
    document.getElementById('dealModeKanban')?.classList.toggle('active', currentDealViewMode === 'kanban');
    const mount = document.getElementById('dealsContentMount');
    if (!mount) return;
    const rows = dealRowsFiltered();
    mount.innerHTML = currentDealViewMode === 'kanban'
        ? renderKanban([
            { key: 'qualification', label: 'Квалификация' },
            { key: 'proposal', label: 'Предложение' },
            { key: 'negotiation', label: 'Переговоры' },
            { key: 'won', label: 'Выиграно' },
            { key: 'lost', label: 'Потеряно' },
        ], rows, 'deal')
        : renderDealRegistry();
}

window.renderLeads = renderLeads;
window.renderDeals = renderDeals;
window.openLeadEditor = openLeadEditor;
window.openDealEditor = openDealEditor;
window.closeLeadEditor = closeLeadEditor;
window.closeDealEditor = closeDealEditor;
window.selectLeadRow = selectLeadRow;
window.selectDealRow = selectDealRow;
window.saveLead = saveLead;
window.saveDeal = saveDeal;
window.createCrmActivity = createCrmActivity;
window.toggleCrmActivityStatus = toggleCrmActivityStatus;
window.convertLeadToDeal = convertLeadToDeal;
window.setLeadViewMode = setLeadViewMode;
window.setDealViewMode = setDealViewMode;
window.applyLeadSearch = applyLeadSearch;
window.applyDealSearch = applyDealSearch;
window.setLeadStageFilter = setLeadStageFilter;
window.setDealStageFilter = setDealStageFilter;
window.setLeadResponsibleFilter = setLeadResponsibleFilter;
window.setDealResponsibleFilter = setDealResponsibleFilter;
window.setLeadSort = setLeadSort;
window.setDealSort = setDealSort;
window.saveLeadPreset = saveLeadPreset;
window.saveDealPreset = saveDealPreset;
window.applyLeadPreset = applyLeadPreset;
window.applyDealPreset = applyDealPreset;
window.resetLeadFilters = resetLeadFilters;
window.resetDealFilters = resetDealFilters;
