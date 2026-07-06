const erpDeepDB = {
    production: null,
    finance: null,
    accounting: null,
};

function erpDeepEscape(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function erpDeepMoney(value, currency = 'RUB') {
    if (typeof formatMoney === 'function') return formatMoney(value || 0, currency);
    return `${Number(value || 0).toFixed(2)} ${currency}`;
}

function erpDeepStatusClass(status) {
    if (typeof enterpriseStatusClass === 'function') return enterpriseStatusClass(status || '');
    return 'status-active';
}

function erpDeepTranslateLabel(value, fallback = '—') {
    const raw = String(value || '').trim();
    if (!raw) return fallback;
    const map = {
        active: 'Активный',
        passive: 'Пассивный',
        active_passive: 'Активно-пассивный',
        full: 'Полная сумма',
        base: 'База',
        vat: 'НДС',
        assets: 'Активы',
        liabilities: 'Обязательства',
        equity: 'Капитал',
        future: 'Будущие',
        current: 'Текущие',
        overdue: 'Просрочено',
        draft: 'Черновик',
        open: 'Открыт',
        closed: 'Закрыт',
        approved: 'Согласовано',
        queued: 'В очереди',
        planned: 'Запланировано',
        in_progress: 'В работе',
        done: 'Выполнено',
        active: 'Активный',
        synced: 'Синхронизировано',
        failed: 'Ошибка',
        conflict: 'Конфликт',
        incoming: 'Приход',
        outgoing: 'Расход',
        imported: 'Загружено',
    };
    return map[raw] || raw;
}

function erpDeepDisplayName(value, fallback = '') {
    const text = String(value || '').trim();
    if (!text) return fallback;
    return text
        .replace(/^QA Sync Client$/i, 'Тестовый клиент синхронизации')
        .replace(/^QA Enterprise Client$/i, 'Тестовый клиент ERP')
        .replace(/^QA Enterprise Project$/i, 'Тестовый проект ERP')
        .replace(/^QA Smoke Client\s*/i, 'Тестовый клиент ')
        .replace(/^QA Smoke Project\s*/i, 'Тестовый проект ');
}

async function erpDeepSave(url, payload, successMessage) {
    const res = await apiCall(url, 'POST', payload);
    if (!res || res.error) {
        customAlert(res?.message || res?.error || 'Не удалось сохранить запись.');
        return false;
    }
    showToast('Система', successMessage || 'Сохранено');
    return true;
}

async function erpDeepDelete(url, successMessage) {
    const res = await apiCall(url, 'DELETE');
    if (!res || res.error) {
        customAlert(res?.message || res?.error || 'Не удалось удалить запись.');
        return false;
    }
    showToast('Система', successMessage || 'Удалено');
    return true;
}

function erpDeepSimpleRows(rows, rowRenderer, emptyText) {
    if (!Array.isArray(rows) || !rows.length) {
        return `<div class="empty-state">${emptyText}</div>`;
    }
    return rows.map(rowRenderer).join('');
}

async function loadProductionDeepData() {
    const res = await apiCall('/production/deep_summary');
    erpDeepDB.production = res && !res.error ? res : { metrics: {}, work_center_load: [], bottlenecks: [], spec_versions: [], tech_cards: [], shifts: [], jobs: [], material_norms: [], labor_norms: [], semifinished: [], rework: [], plan_fact: [], order_costing: [], shift_board: [], wip_board: {}, order_timelines: [], norm_fact_board: [], change_log: [], mrp_aps: { metrics: {}, shortages: [], capacity_plan: [], schedule_assignments: [], recommendations: [], scenarios: [], runs: [] } };
}

function productionDeepStageLabel(stage) {
    if (typeof productionStageLabel === 'function') return productionStageLabel(stage);
    return ({ queue: 'Очередь', in_work: 'В работе', otk: 'ОТК', done: 'Готово' }[stage] || stage || 'Статус');
}

function productionDeepStatusClass(level) {
    if (level === 'risk' || level === 'overdue') return 'status-overdue';
    if (level === 'warning' || level === 'active') return 'status-active';
    if (level === 'done' || level === 'ok') return 'status-completed';
    return 'status-neutral';
}

function productionActionEmptyState(message, actions = []) {
    return `
        <div class="empty-action-state">
            <div class="empty-state">${erpDeepEscape(message)}</div>
            ${actions.length ? `
                <div class="empty-state-actions">
                    ${actions.map(action => `<button class="${action.kind === 'primary' ? 'btn-primary' : 'btn-secondary'}" onclick="${action.onclick}">${erpDeepEscape(action.label)}</button>`).join('')}
                </div>
            ` : ''}
        </div>
    `;
}

window.focusProductionQueue = function() {
    document.getElementById('productionOrdersTable')?.closest('.surface-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.focusProductionOrderForm = function() {
    document.getElementById('productionOrderForm')?.closest('.surface-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.focusProductionOperations = function() {
    document.getElementById('productionOperationForm')?.closest('.surface-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.focusProductionDeepSection = function() {
    document.getElementById('productionDeepMount')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.selectFirstProductionOrder = function() {
    if (Array.isArray(window.productionOrdersDB) && window.productionOrdersDB.length) {
        selectedProductionOrderId = Number(window.productionOrdersDB[0].id || 0);
        renderProduction();
        return;
    }
    window.focusProductionOrderForm();
};

window.openSupplyFromProduction = function() {
    if (typeof navigateTo === 'function') navigateTo('supply');
};

function renderProductionWipBoard() {
    const data = erpDeepDB.production || {};
    const board = data.wip_board || {};
    const columns = [
        ['queue', 'Очередь'],
        ['in_work', 'В работе'],
        ['otk', 'ОТК'],
        ['done', 'Готово'],
    ];
    const selectedTimeline = (data.order_timelines || []).find(item => Number(item.order_id || 0) === Number(selectedProductionOrderId || 0)) || (data.order_timelines || [])[0] || null;
    const boardCount = columns.reduce((sum, [key]) => sum + ((board[key] || []).length), 0);
    if (!boardCount) {
        return productionActionEmptyState('Пока нет заказов, из которых можно собрать незавершённое производство и маршрут.', [
            { label: 'Создать заказ', onclick: 'focusProductionOrderForm()', kind: 'primary' },
            { label: 'Открыть очередь', onclick: 'focusProductionQueue()' },
        ]);
    }
    return `
        <div class="production-board">
            ${columns.map(([key, title]) => `
                <div class="production-board-column">
                    <div class="production-board-header">${erpDeepEscape(title)} <span>${(board[key] || []).length}</span></div>
                    <div class="production-board-list">
                        ${(board[key] || []).length ? board[key].slice(0, 6).map(item => `
                            <button class="production-queue-card ${Number(item.order_id || 0) === Number(selectedProductionOrderId || 0) ? 'is-selected' : ''}" onclick="selectProductionOrder(${Number(item.order_id || 0)}); renderProduction();">
                                <div class="production-queue-title">${erpDeepEscape(item.order_name || 'Заказ')}</div>
                                <div class="production-queue-meta">${erpDeepEscape(item.current_step || 'Шаг не определён')}</div>
                                <div class="production-queue-meta">${erpDeepEscape(item.responsible || 'Ответственный не задан')} · ${Number(item.progress || 0).toFixed(0)}%</div>
                                <div class="production-queue-tags">
                                    <span class="status-badge ${productionDeepStatusClass(item.overdue ? 'overdue' : (item.priority === 'critical' ? 'warning' : 'ok'))}">${item.overdue ? 'Просрочен' : erpDeepEscape(item.priority || 'normal')}</span>
                                    <span class="production-mini-pill">${Number(item.produced_qty || 0).toFixed(0)} / ${Number(item.planned_qty || 0).toFixed(0)}</span>
                                </div>
                            </button>
                        `).join('') : '<div class="empty-state">Пусто</div>'}
                    </div>
                </div>
            `).join('')}
        </div>
        <div class="production-focus-card" style="margin-top:16px;">
            <div class="production-focus-head">
                <div>
                    <div class="production-focus-title">${erpDeepEscape(selectedTimeline?.order_name || 'Маршрут не выбран')}</div>
                    <div class="production-focus-meta">${erpDeepEscape(selectedTimeline?.route_name || 'Без маршрута')} · ${productionDeepStageLabel(selectedTimeline?.stage || '')} · завершение ${Number(selectedTimeline?.completion_percent || 0).toFixed(0)}%</div>
                </div>
                <span class="status-badge ${productionDeepStatusClass(selectedTimeline?.stage === 'done' ? 'done' : 'active')}">${Number(selectedTimeline?.steps?.length || 0)} шагов</span>
            </div>
            <div class="production-step-list">
                ${selectedTimeline?.steps?.length ? selectedTimeline.steps.map(step => `
                    <div class="production-step ${step.is_current ? 'is-current' : ''}">
                        <div class="production-step-marker ${productionDeepStatusClass(step.risk_level)}"></div>
                        <div class="production-step-body">
                            <div class="production-step-title">#${Number(step.sequence_no || 0)} · ${erpDeepEscape(step.operation_name || 'Этап')}</div>
                            <div class="production-step-meta">${erpDeepEscape(step.work_center || 'Без центра')} · ${erpDeepEscape(step.started_at || 'старт не зафиксирован')}${step.finished_at ? ` → ${erpDeepEscape(step.finished_at)}` : ''}</div>
                            <div class="production-step-bar"><span style="width:${Math.max(6, Math.min(100, Number(step.planned_qty || 0) > 0 ? (Number(step.completed_qty || 0) / Number(step.planned_qty || 1)) * 100 : (step.status === 'done' ? 100 : step.status === 'in_progress' ? 55 : 12)))}%"></span></div>
                            <div class="production-step-meta">часы ${Number(step.planned_hours || 0).toFixed(1)} / ${Number(step.actual_hours || 0).toFixed(1)} · выпуск ${Number(step.completed_qty || 0).toFixed(1)} / ${Number(step.planned_qty || 0).toFixed(1)} · брак ${Number(step.scrap_qty || 0).toFixed(1)}</div>
                        </div>
                        <div class="production-step-side">
                            <span class="status-badge ${productionDeepStatusClass(step.risk_level)}">${erpDeepEscape(erpDeepTranslateLabel(step.status || 'planned', 'Запланировано'))}</span>
                            <div class="production-step-side-note">${Number(step.variance_hours || 0).toFixed(1)} ч</div>
                        </div>
                    </div>
                `).join('') : productionActionEmptyState('Выберите заказ в очереди, и здесь появится маршрутный фокус по операциям.', [
                    { label: 'Выбрать первый заказ', onclick: 'selectFirstProductionOrder()', kind: 'primary' },
                    { label: 'Открыть очередь', onclick: 'focusProductionQueue()' },
                ])}
            </div>
        </div>
    `;
}

function renderProductionShiftBoard() {
    const data = erpDeepDB.production || {};
    const centers = (data.work_center_load || []).slice(0, 6);
    const shifts = (data.shift_board || []).slice(0, 6);
    return `
        <div class="production-load-grid">
            <section class="surface-card surface-card--padded">
                <h4 class="section-title">Рабочие центры</h4>
                <div class="client360-list">
                    ${centers.length ? centers.map(item => `
                        <div class="production-load-row">
                            <div>
                                <div class="client360-item-title">${erpDeepEscape(item.work_center || 'Без центра')}</div>
                                <div class="client360-item-meta">мощность ${Number(item.capacity_hours || 0).toFixed(1)} ч · свободно ${Number(item.free_hours || 0).toFixed(1)} ч · активных ${Number(item.in_progress || 0)}</div>
                            </div>
                            <div class="production-load-side">
                                <div class="production-load-bar"><span style="width:${Math.max(6, Math.min(100, Number(item.load_percent || 0)))}%"></span></div>
                                <span class="status-badge ${productionDeepStatusClass(item.risk_level)}">${Number(item.load_percent || 0).toFixed(1)}%</span>
                            </div>
                        </div>
                    `).join('') : productionActionEmptyState('Загрузка центров пока не собрана.', [
                        { label: 'Открыть глубокий контур', onclick: 'focusProductionDeepSection()' },
                    ])}
                </div>
            </section>
            <section class="surface-card surface-card--padded">
                <h4 class="section-title">Сменный контур</h4>
                <div class="client360-list">
                    ${shifts.length ? shifts.map(item => `
                        <div class="client360-item client360-item--stack">
                            <div class="client360-item-title">${erpDeepEscape(item.shift_name || item.work_center || 'Смена')}</div>
                            <div class="client360-item-meta">${erpDeepEscape(item.shift_date || '')} · ${erpDeepEscape(item.work_center || 'Без центра')} · ${erpDeepEscape(item.team_name || 'Команда не задана')}</div>
                            <div class="client360-item-meta">${erpDeepEscape(item.supervisor_name || 'Старший не задан')} · заданий ${Number(item.jobs_total || 0)} · открыто ${Number(item.open_jobs || 0)}</div>
                            <div class="production-load-bar"><span style="width:${Math.max(6, Math.min(100, Number(item.load_percent || 0)))}%"></span></div>
                            <div class="production-inline-stats">
                                <span class="production-mini-pill">план ${Number(item.planned_hours || 0).toFixed(1)} ч</span>
                                <span class="production-mini-pill">факт ${Number(item.actual_hours || 0).toFixed(1)} ч</span>
                                <span class="status-badge ${productionDeepStatusClass(item.risk_level)}">${Number(item.load_percent || 0).toFixed(1)}%</span>
                            </div>
                        </div>
                    `).join('') : productionActionEmptyState('Смены пока не заведены.', [
                        { label: 'Открыть глубокий контур', onclick: 'focusProductionDeepSection()', kind: 'primary' },
                    ])}
                </div>
            </section>
        </div>
    `;
}

function renderProductionNormFactBoard() {
    const rows = (erpDeepDB.production?.norm_fact_board || []).slice(0, 8);
    return rows.length ? rows.map(item => `
        <div class="production-norm-card">
            <div class="production-norm-head">
                <div>
                    <div class="production-focus-title">${erpDeepEscape(item.order_name || 'Заказ')}</div>
                    <div class="production-focus-meta">материал ${Number(item.material_plan || 0).toFixed(1)} / ${Number(item.material_fact || 0).toFixed(1)} · труд ${Number(item.labor_plan_hours || 0).toFixed(1)} / ${Number(item.labor_fact_hours || 0).toFixed(1)}</div>
                </div>
                <span class="status-badge ${productionDeepStatusClass(item.risk_level)}">${item.risk_level === 'risk' ? 'Отклонение' : item.risk_level === 'ok' ? 'В норме' : 'Нейтрально'}</span>
            </div>
            <div class="production-inline-stats">
                <span class="production-mini-pill">мат. отклонение ${Number(item.material_gap || 0).toFixed(1)}</span>
                <span class="production-mini-pill">труд отклонение ${Number(item.labor_gap_hours || 0).toFixed(1)} ч</span>
                <span class="production-mini-pill">отклонение себестоимости ${erpDeepMoney(item.cost_gap || 0)}</span>
                <span class="production-mini-pill">брак ${Number(item.scrap_qty || 0).toFixed(1)}</span>
            </div>
        </div>
    `).join('') : productionActionEmptyState('Нормативно-фактические отклонения пока не собраны.', [
        { label: 'Выбрать заказ', onclick: 'selectFirstProductionOrder()', kind: 'primary' },
        { label: 'Открыть операции', onclick: 'focusProductionOperations()' },
    ]);
}

function renderProductionChangeLog() {
    const selectedOrderId = Number(selectedProductionOrderId || 0);
    const rows = (erpDeepDB.production?.change_log || []).filter(item => !selectedOrderId || Number(item.order_id || 0) === selectedOrderId).slice(0, 12);
    return rows.length ? `
        <div class="client360-list">
            ${rows.map(item => `
                <div class="client360-item client360-item--stack">
                    <div class="client360-item-title">${erpDeepEscape(item.title || item.action || 'Событие')}</div>
                    <div class="client360-item-meta">${erpDeepEscape(item.actor_name || 'Система')} · ${erpDeepEscape(item.action || '')}${item.work_center ? ` · ${erpDeepEscape(item.work_center)}` : ''}</div>
                    <div class="client360-item-meta">${item.created_at ? new Date(Number(item.created_at) * 1000).toLocaleString('ru-RU') : 'время не указано'}</div>
                </div>
            `).join('')}
        </div>
    ` : productionActionEmptyState(selectedOrderId ? 'По выбранному заказу журнал изменений пока пуст.' : 'Сначала выберите заказ, чтобы видеть журнал изменений.', [
        { label: 'Выбрать заказ', onclick: 'selectFirstProductionOrder()', kind: 'primary' },
        { label: 'Открыть очередь', onclick: 'focusProductionQueue()' },
    ]);
}

function renderProductionDeepMount() {
    const data = erpDeepDB.production || {};
    const mrp = data.mrp_aps || {};
    const mrpMetrics = mrp.metrics || {};
    const selectedOrder = typeof getSelectedProductionOrder === 'function' ? getSelectedProductionOrder() : null;
    const orderId = Number(selectedProductionOrderId || selectedOrder?.id || 0);
    const filteredSpec = (data.spec_versions || []).filter(item => !orderId || Number(item.order_id || 0) === orderId).slice(0, 8);
    const filteredTech = (data.tech_cards || []).filter(item => !orderId || Number(item.order_id || 0) === orderId).slice(0, 8);
    const filteredJobs = (data.jobs || []).filter(item => !orderId || Number(item.order_id || 0) === orderId).slice(0, 8);
    const filteredMat = (data.material_norms || []).filter(item => !orderId || Number(item.order_id || 0) === orderId).slice(0, 8);
    const filteredLabor = (data.labor_norms || []).filter(item => !orderId || Number(item.order_id || 0) === orderId).slice(0, 8);
    const filteredSemi = (data.semifinished || []).filter(item => !orderId || Number(item.order_id || 0) === orderId).slice(0, 8);
    const filteredRework = (data.rework || []).filter(item => !orderId || Number(item.order_id || 0) === orderId).slice(0, 8);
    const planFact = (data.plan_fact || []).slice(0, 8);
    const costingReport = (data.costing_report?.rows || []).slice(0, 8);
    const costing = costingReport.length ? costingReport.map(row => ({ ...row, total_cost: row.fact_cost })) : (data.order_costing || []).slice(0, 8);
    return `
        <div class="finance-layout" style="margin-top:24px;">
            <section class="surface-card surface-card--padded ops-form-card">
                <div class="section-header"><div><h3 class="section-title">Глубокий производственный контур</h3><p class="section-subtitle">Версии спецификаций, техкарты, смены, задания, нормы, полуфабрикаты и переработка брака.</p></div><span class="ops-section-chip">${erpDeepEscape(selectedOrder?.order_name || 'Весь контур')}</span></div>
                <div class="metrics-grid">
                    <div class="metric-card"><div class="metric-title">Версии спецификаций</div><div class="metric-value">${Number(data.metrics?.spec_versions || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Техкарты</div><div class="metric-value">${Number(data.metrics?.tech_cards || 0)}</div></div>
                    <div class="metric-card warning"><div class="metric-title">Открытые задания</div><div class="metric-value">${Number(data.metrics?.jobs_open || 0)}</div></div>
                    <div class="metric-card warning"><div class="metric-title">Открытая переработка</div><div class="metric-value">${Number(data.metrics?.rework_open || 0)}</div></div>
                    <div class="metric-card warning"><div class="metric-title">MRP дефициты</div><div class="metric-value">${Number(mrpMetrics.shortages || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">APS часы</div><div class="metric-value">${Number(mrpMetrics.scheduled_hours || 0).toFixed(1)}</div></div>
                </div>
                <div class="client360-grid" style="margin-top:16px;">
                    <div class="surface-card surface-card--padded">
                        <h3 class="section-title">Загрузка центров</h3>
                        <div class="client360-list">${erpDeepSimpleRows((data.work_center_load || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.work_center)}</div><div class="client360-item-meta">План ${Number(item.planned_hours || 0).toFixed(1)} ч · мощность ${Number(item.capacity_hours || 0).toFixed(1)} ч</div></div><span class="status-badge ${erpDeepStatusClass(item.load_percent > 90 ? 'overdue' : 'active')}">${Number(item.load_percent || 0).toFixed(1)}%</span></div>`, 'Пока нет загрузки по центрам.')}</div>
                    </div>
                    <div class="surface-card surface-card--padded">
                        <h3 class="section-title">Узкие места</h3>
                        <div class="client360-list">${erpDeepSimpleRows(data.bottlenecks || [], item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.work_center)}</div><div class="client360-item-meta">${erpDeepEscape(item.message)}</div></div><span class="status-badge ${erpDeepStatusClass('overdue')}">${Number(item.load_percent || 0).toFixed(1)}%</span></div>`, 'Критичных узких мест пока нет.')}</div>
                    </div>
                </div>
                <div class="finance-form-grid" style="margin-top:16px;">
                    <input id="prodSpecLabelDeep" class="auth-input" style="margin:0;" placeholder="Новая версия спецификации">
                    <input id="prodTechTitleDeep" class="auth-input" style="margin:0;" placeholder="Техкарта / техпроцесс">
                    <input id="prodShiftNameDeep" class="auth-input" style="margin:0;" placeholder="Смена">
                    <input id="prodJobTitleDeep" class="auth-input" style="margin:0;" placeholder="Производственное задание">
                    <input id="prodMaterialArticleDeep" class="auth-input" style="margin:0;" placeholder="Материал / артикул">
                    <input id="prodLaborOperationDeep" class="auth-input" style="margin:0;" placeholder="Норма труда / операция">
                    <input id="prodSemiArticleDeep" class="auth-input" style="margin:0;" placeholder="Полуфабрикат">
                    <input id="prodReworkDefectDeep" class="auth-input" style="margin:0;" placeholder="Брак / дефект">
                    <input id="prodScenarioNameDeep" class="auth-input" style="margin:0;" placeholder="MRP/APS сценарий">
                    <input id="prodScenarioHorizonDeep" class="auth-input" style="margin:0;" placeholder="Горизонт дней" value="30">
                    <input id="prodScenarioDemandDeep" class="auth-input" style="margin:0;" placeholder="Коэф. спроса" value="1">
                    <input id="prodScenarioCapacityDeep" class="auth-input" style="margin:0;" placeholder="Коэф. мощности" value="1">
                </div>
                <div class="finance-actions-row" style="margin-top:12px;">
                    <button class="btn-secondary" onclick="saveProductionSpecDeep()">Версия спецификации</button>
                    <button class="btn-secondary" onclick="saveProductionTechCardDeep()">Техкарта</button>
                    <button class="btn-secondary" onclick="saveProductionShiftDeep()">Смена</button>
                    <button class="btn-secondary" onclick="saveProductionJobDeep()">Задание</button>
                    <button class="btn-secondary" onclick="saveProductionMaterialNormDeep()">Мат. норма</button>
                    <button class="btn-secondary" onclick="saveProductionLaborNormDeep()">Труд. норма</button>
                    <button class="btn-secondary" onclick="saveProductionSemifinishedDeep()">Полуфабрикат</button>
                    <button class="btn-secondary" onclick="saveProductionReworkDeep()">Переработка</button>
                    <button class="btn-secondary" onclick="saveProductionScenarioDeep()">Сценарий MRP/APS</button>
                    <button class="btn-primary" onclick="runProductionMrpApsDeep()">Рассчитать MRP/APS</button>
                    <button class="btn-secondary" onclick="replanProductionMrpApsDeep()">Перепланировать</button>
                </div>
            </section>
            <section class="surface-card surface-card--padded ops-list-card">
                <h3 class="section-title">MRP/APS планирование</h3>
                <div class="client360-grid">
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Дефициты материалов</h3><div class="client360-list">${erpDeepSimpleRows((mrp.shortages || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.article || '')} · ${erpDeepEscape(item.item_name || '')}</div><div class="client360-item-meta">надо ${Number(item.required_qty || 0).toFixed(2)} · доступно ${Number(item.available_qty || 0).toFixed(2)} · дата ${erpDeepEscape(item.earliest_need_date || '')}</div></div><span class="status-badge ${productionDeepStatusClass(item.risk_level || 'warning')}">${Number(item.shortage_qty || 0).toFixed(2)}</span></div>`, 'Критичных дефицитов нет.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">APS загрузка смен</h3><div class="client360-list">${erpDeepSimpleRows((mrp.capacity_plan || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.work_center || '')}</div><div class="client360-item-meta">${erpDeepEscape(item.shift_date || '')} · план ${Number(item.planned_hours || 0).toFixed(1)} / ${Number(item.capacity_hours || 0).toFixed(1)} ч</div></div><span class="status-badge ${productionDeepStatusClass(item.risk_level || 'ok')}">${Number(item.load_percent || 0).toFixed(1)}%</span></div>`, 'Смены для APS пока не заведены.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Рекомендации и сценарии</h3><div class="client360-list">${erpDeepSimpleRows((mrp.recommendations || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item)}</div><div class="client360-item-meta">MRP/APS рекомендация</div></div></div>`, 'Рекомендаций пока нет.')}${erpDeepSimpleRows((mrp.scenarios || []).slice(0, 4), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.scenario_name || '')}</div><div class="client360-item-meta">${Number(item.planning_horizon_days || 0)} дней · ${erpDeepEscape(item.status || '')}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionScenarioDeep(${item.id})">Удалить</button></div></div>`, 'Сценарии пока не сохранены.')}</div></div>
                </div>
                <div class="table-shell" style="margin-top:16px;"><table class="admin-table"><thead><tr><th>Заказ</th><th>Операция</th><th>Центр</th><th>Смена</th><th>Часы</th></tr></thead><tbody>${(mrp.schedule_assignments || []).slice(0, 10).map(item => `<tr><td>${erpDeepEscape(item.order_name || '')}</td><td>${erpDeepEscape(item.operation_name || '')}</td><td>${erpDeepEscape(item.work_center || '')}</td><td>${erpDeepEscape(item.shift_date || '')}</td><td>${Number(item.planned_hours || 0).toFixed(1)}</td></tr>`).join('') || `<tr><td colspan="5">APS-расписание пока не рассчитано.</td></tr>`}</tbody></table></div>
            </section>
            <section class="surface-card surface-card--padded ops-list-card">
                <h3 class="section-title">План-факт и себестоимость</h3>
                <div class="table-shell"><table class="admin-table"><thead><tr><th>Заказ</th><th>План / факт</th><th>Часы</th><th>Материалы</th><th>Себестоимость</th></tr></thead><tbody>${planFact.map(item => {
                    const cost = costing.find(row => Number(row.order_id) === Number(item.order_id));
                    return `<tr><td>${erpDeepEscape(item.order_name)}</td><td>${Number(item.planned_qty || 0).toFixed(1)} / ${Number(item.fact_qty || 0).toFixed(1)}</td><td>${Number(item.planned_hours || 0).toFixed(1)} / ${Number(item.fact_hours || 0).toFixed(1)}</td><td>${Number(item.material_plan || 0).toFixed(1)} / ${Number(item.material_fact || 0).toFixed(1)}</td><td>${erpDeepMoney(cost?.total_cost || 0)}<div class="finance-row-meta">Откл. ${erpDeepMoney(cost?.variance || 0)}</div></td></tr>`;
                }).join('') || `<tr><td colspan="5">Пока нет данных по план-факту.</td></tr>`}</tbody></table></div>
                <div class="client360-grid" style="margin-top:16px;">
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Версии и техкарты</h3><div class="client360-list">${erpDeepSimpleRows(filteredSpec, item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.label)}</div><div class="client360-item-meta">${erpDeepEscape(item.comment || 'Без комментария')}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionSpecDeep(${item.id})">Удалить</button></div></div>`, 'Версий спецификаций пока нет.')}${erpDeepSimpleRows(filteredTech, item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.title)}</div><div class="client360-item-meta">${erpDeepEscape(item.work_center || 'Без центра')} · подготовка ${Number(item.setup_minutes || 0)} мин</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionTechCardDeep(${item.id})">Удалить</button></div></div>`, 'Техкарт пока нет.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Задания, смены, брак</h3><div class="client360-list">${erpDeepSimpleRows((data.shifts || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.shift_name || item.work_center)}</div><div class="client360-item-meta">${erpDeepEscape(item.shift_date || '')} · ${Number(item.capacity_hours || 0).toFixed(1)} ч</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionShiftDeep(${item.id})">Удалить</button></div></div>`, 'Смен пока нет.')}${erpDeepSimpleRows(filteredJobs, item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.title)}</div><div class="client360-item-meta">${erpDeepEscape(item.work_center || 'Без центра')} · ${erpDeepEscape(erpDeepTranslateLabel(item.status || 'queued', 'В очереди'))}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionJobDeep(${item.id})">Удалить</button></div></div>`, 'Заданий пока нет.')}${erpDeepSimpleRows(filteredRework, item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.defect_name)}</div><div class="client360-item-meta">${Number(item.qty || 0).toFixed(1)} шт · ${erpDeepEscape(item.reason || 'Без причины')}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionReworkDeep(${item.id})">Удалить</button></div></div>`, 'Переработок брака пока нет.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Нормы и полуфабрикаты</h3><div class="client360-list">${erpDeepSimpleRows(filteredMat, item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.article || item.item_name)}</div><div class="client360-item-meta">Норма ${Number(item.norm_qty || 0).toFixed(2)} ${erpDeepEscape(item.unit || '')}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionMaterialNormDeep(${item.id})">Удалить</button></div></div>`, 'Материальных норм пока нет.')}${erpDeepSimpleRows(filteredLabor, item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.operation_name)}</div><div class="client360-item-meta">${Number(item.norm_hours || 0).toFixed(2)} ч · ${erpDeepMoney(item.rate_per_hour || 0)}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionLaborNormDeep(${item.id})">Удалить</button></div></div>`, 'Трудовых норм пока нет.')}${erpDeepSimpleRows(filteredSemi, item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.article || item.item_name)}</div><div class="client360-item-meta">${Number(item.qty || 0).toFixed(1)} · ${erpDeepEscape(item.stage_name || '')}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteProductionSemifinishedDeep(${item.id})">Удалить</button></div></div>`, 'Полуфабрикатов пока нет.')}</div></div>
                </div>
            </section>
        </div>
    `;
}

async function loadFinanceDeepData() {
    const res = await apiCall('/finance/deep_summary');
    erpDeepDB.finance = res && !res.error ? res : { metrics: {}, management_balance: {}, payment_requests: [], project_limits: [], budgets: [], obligations: [], cash_gap_scenarios: [], payment_calendar: [], payment_obligation_reconciliation: [], budget_variance: [], factor_variance: [], treasury_routes: [], treasury_approval_board: [], bank_payment_orders: [], exchange_batches: [] };
}

function renderFinanceDeepMount() {
    const data = erpDeepDB.finance || {};
    return `
        <div class="finance-layout" style="margin-top:24px;">
            <section class="surface-card surface-card--padded ops-form-card">
                <div class="section-header"><div><h3 class="section-title">Глубокий контур казначейства</h3><p class="section-subtitle">Заявки на оплату, лимиты по проектам, бюджеты, обязательства, сценарии кассового разрыва, баланс и факторный анализ.</p></div></div>
                <div class="metrics-grid">
                    <div class="metric-card"><div class="metric-title">Открытые заявки</div><div class="metric-value">${Number(data.metrics?.requests_open || 0)}</div></div>
                    <div class="metric-card warning"><div class="metric-title">Открытые обязательства</div><div class="metric-value">${Number(data.metrics?.obligations_open || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Денежные средства</div><div class="metric-value">${erpDeepMoney(data.management_balance?.cash || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Оборотный капитал</div><div class="metric-value">${erpDeepMoney(data.management_balance?.net_working_capital || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Маршрутов</div><div class="metric-value">${Number(data.metrics?.treasury_routes || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Банковские поручения</div><div class="metric-value">${Number(data.metrics?.bank_orders || 0)}</div></div>
                </div>
                <div class="finance-form-grid" style="margin-top:16px;">
                    <input id="financeRequestTitleDeep" class="auth-input" style="margin:0;" placeholder="Заявка на оплату">
                    <input id="financeRequestAmountDeep" class="auth-input" style="margin:0;" placeholder="Сумма заявки">
                    <input id="financeLimitProjectDeep" class="auth-input" style="margin:0;" placeholder="Идентификатор проекта для лимита">
                    <input id="financeLimitAmountDeep" class="auth-input" style="margin:0;" placeholder="Лимит проекта">
                    <input id="financeBudgetArticleDeep" class="auth-input" style="margin:0;" placeholder="Бюджет / статья">
                    <input id="financeBudgetPlanDeep" class="auth-input" style="margin:0;" placeholder="План бюджета">
                    <input id="financeObligationTitleDeep" class="auth-input" style="margin:0;" placeholder="Обязательство">
                    <input id="financeObligationAmountDeep" class="auth-input" style="margin:0;" placeholder="Сумма обязательства">
                    <input id="financeScenarioNameDeep" class="auth-input" style="margin:0;" placeholder="Сценарий кассового разрыва">
                    <input id="financeScenarioGapDeep" class="auth-input" style="margin:0;" placeholder="Разрыв">
                    <input id="financeTreasuryRouteNameDeep" class="auth-input" style="margin:0;" placeholder="Маршрут согласования">
                    <input id="financeTreasuryRouteMinDeep" class="auth-input" style="margin:0;" placeholder="Мин. сумма маршрута">
                    <input id="financeTreasuryRouteMaxDeep" class="auth-input" style="margin:0;" placeholder="Макс. сумма маршрута">
                    <input id="financeTreasuryRouteStagesDeep" class="auth-input" style="margin:0;" placeholder="Роли через запятую: Бухгалтер, Финдир, Директор">
                </div>
                <div class="finance-actions-row" style="margin-top:12px;">
                    <button class="btn-secondary" onclick="saveFinanceRequestDeep()">Заявка</button>
                    <button class="btn-secondary" onclick="saveFinanceLimitDeep()">Лимит проекта</button>
                    <button class="btn-secondary" onclick="saveFinanceBudgetDeep()">Бюджет</button>
                    <button class="btn-secondary" onclick="saveFinanceObligationDeep()">Обязательство</button>
                    <button class="btn-secondary" onclick="saveTreasuryRouteDeep()">Маршрут</button>
                    <button class="btn-primary" onclick="saveFinanceScenarioDeep()">Сохранить сценарий</button>
                </div>
            </section>
            <section class="surface-card surface-card--padded ops-list-card">
                <h3 class="section-title">Платежный календарь и бюджеты</h3>
                <div class="table-shell"><table class="admin-table"><thead><tr><th>Дата</th><th>Входящий</th><th>Исходящий</th><th>Итог</th></tr></thead><tbody>${(data.payment_calendar || []).slice(0, 8).map(item => `<tr><td>${erpDeepEscape(item.due_date)}</td><td>${erpDeepMoney(item.incoming || 0)}</td><td>${erpDeepMoney(item.outgoing || 0)}</td><td>${erpDeepMoney(item.net || 0)}</td></tr>`).join('') || `<tr><td colspan="4">Календарь пока пуст.</td></tr>`}</tbody></table></div>
                <div class="client360-grid" style="margin-top:16px;">
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Заявки и лимиты</h3><div class="client360-list">${erpDeepSimpleRows((data.payment_requests || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.title)}</div><div class="client360-item-meta">${erpDeepMoney(item.amount || 0, item.currency)} · ${erpDeepEscape(erpDeepTranslateLabel(item.request_status || 'draft', 'Черновик'))}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteFinanceRequestDeep(${item.id})">Удалить</button></div></div>`, 'Заявок на оплату пока нет.')}${erpDeepSimpleRows((data.project_limits || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">Проект ${Number(item.project_id || 0)}</div><div class="client360-item-meta">${erpDeepMoney(item.amount_limit || 0)} · ${erpDeepEscape(item.period_key || '')}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteFinanceLimitDeep(${item.id})">Удалить</button></div></div>`, 'Проектных лимитов пока нет.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Бюджеты и отклонения</h3><div class="client360-list">${erpDeepSimpleRows((data.budgets || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.article_name)}</div><div class="client360-item-meta">${erpDeepMoney(item.plan_amount || 0)} / ${erpDeepMoney(item.fact_amount || 0)}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteFinanceBudgetDeep(${item.id})">Удалить</button></div></div>`, 'Бюджетов пока нет.')}${erpDeepSimpleRows((data.budget_variance || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.article_name)}</div><div class="client360-item-meta">${erpDeepEscape(item.budget_type)} · отклонение ${erpDeepMoney(item.gap || 0)}</div></div></div>`, 'Отклонений пока нет.')}${erpDeepSimpleRows((data.factor_variance || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.article_name)}</div><div class="client360-item-meta">план ${erpDeepMoney(item.plan_amount || 0)} · факт ${erpDeepMoney(item.actual_amount || 0)}</div></div><div class="client360-item-side">${erpDeepMoney(item.variance || 0)}</div></div>`, 'Факторный анализ пока пуст.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Обязательства, маршруты и банковский обмен</h3><div class="client360-list">${erpDeepSimpleRows((data.obligations || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.title)}</div><div class="client360-item-meta">${erpDeepMoney(item.amount || 0, item.currency)} · ${erpDeepEscape(erpDeepTranslateLabel(item.status || 'open', 'Открыто'))}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteFinanceObligationDeep(${item.id})">Удалить</button></div></div>`, 'Обязательств пока нет.')}${erpDeepSimpleRows((data.cash_gap_scenarios || []).slice(0, 4), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.scenario_name)}</div><div class="client360-item-meta">${erpDeepMoney(item.gap_amount || 0)} · ${erpDeepEscape(item.period_key || '')}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteFinanceScenarioDeep(${item.id})">Удалить</button></div></div>`, 'Сценариев кассового разрыва пока нет.')}${erpDeepSimpleRows((data.treasury_approval_board || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.title)}</div><div class="client360-item-meta">${erpDeepEscape(item.route_name || 'Без маршрута')} · ${erpDeepEscape(item.pending_role || '')}</div></div><div class="client360-item-side">${erpDeepMoney(item.amount || 0)}</div></div>`, 'Маршруты согласования пока не собраны.')}${erpDeepSimpleRows((data.bank_payment_orders || []).slice(0, 4), item => `<div class="client360-item"><div><div class="client360-item-title">Поручение #${Number(item.id || 0)}</div><div class="client360-item-meta">${erpDeepEscape(item.counterparty || '')} · ${erpDeepEscape(erpDeepTranslateLabel(item.status || 'draft', 'Черновик'))}</div></div><div class="client360-item-side">${erpDeepMoney(item.amount || 0, item.currency)}</div></div>`, 'Платёжных поручений пока нет.')}</div></div>
                </div>
            </section>
        </div>
    `;
}

async function loadAccountingDeepData() {
    const res = await apiCall('/accounting/deep_summary');
    erpDeepDB.accounting = res && !res.error ? res : { metrics: {}, vat_summary: {}, management_balance: {}, manual_operations: [], debt_adjustments: [], cash_operations: [], purchase_book: [], sales_book: [], counterparty_settlements: [], contract_settlements: [], bank_accounts: [], bank_statements: [], posting_templates: [], vat_by_rate: [], balance_sheet_lines: [], bank_payment_orders: [], exchange_batches: [], edo_operators: [], external_submissions: [], external_events: [], external_reporting_metrics: {}, edo_exchange_health: {}, close_cycle: {} };
}

function renderAccountingDeepMount() {
    const data = erpDeepDB.accounting || {};
    const close = data.close_cycle || {};
    const externalMetrics = data.external_reporting_metrics || {};
    const exchangeHealth = data.edo_exchange_health || {};
    return `
        <div class="finance-layout" style="margin-top:24px;">
            <section class="surface-card surface-card--padded ops-form-card">
                <div class="section-header"><div><h3 class="section-title">Глубокая бухгалтерия</h3><p class="section-subtitle">План счетов, автоматические проводки, ручные операции, НДС, взаиморасчеты, касса и банковские движения.</p></div></div>
                <div class="metrics-grid">
                    <div class="metric-card"><div class="metric-title">Проводок</div><div class="metric-value">${Number(data.metrics?.entries_total || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Счетов</div><div class="metric-value">${Number(data.metrics?.accounts_total || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Шаблонов</div><div class="metric-value">${Number(data.metrics?.posting_templates || 0)}</div></div>
                    <div class="metric-card warning"><div class="metric-title">НДС к уплате</div><div class="metric-value">${erpDeepMoney(data.vat_summary?.net || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Собственный капитал</div><div class="metric-value">${erpDeepMoney(data.management_balance?.equity || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Банковские поручения</div><div class="metric-value">${Number(data.metrics?.bank_orders || 0)}</div></div>
                    <div class="metric-card"><div class="metric-title">Операторы ЭДО</div><div class="metric-value">${Number(externalMetrics.operators_active || 0)} / ${Number(externalMetrics.operators_total || 0)}</div></div>
                    <div class="metric-card warning"><div class="metric-title">Внешняя отчётность в очереди</div><div class="metric-value">${Number(externalMetrics.submissions_waiting || 0)}</div></div>
                    <div class="metric-card ${Number(externalMetrics.submissions_failed || 0) ? 'danger' : ''}"><div class="metric-title">Сбой внешнего контура</div><div class="metric-value">${Number(externalMetrics.submissions_failed || 0)}</div></div>
                </div>
                <div class="finance-form-grid" style="margin-top:16px;">
                    <input id="accManualDescDeep" class="auth-input" style="margin:0;" placeholder="Ручная операция / описание">
                    <input id="accManualAmountDeep" class="auth-input" style="margin:0;" placeholder="Сумма ручной операции">
                    <input id="accManualDebitDeep" class="auth-input" style="margin:0;" placeholder="Дт">
                    <input id="accManualCreditDeep" class="auth-input" style="margin:0;" placeholder="Кт">
                    <input id="accDebtReasonDeep" class="auth-input" style="margin:0;" placeholder="Корректировка долга">
                    <input id="accDebtAmountDeep" class="auth-input" style="margin:0;" placeholder="Сумма корректировки">
                    <input id="accCashCounterpartyDeep" class="auth-input" style="margin:0;" placeholder="Касса / контрагент">
                    <input id="accCashAmountDeep" class="auth-input" style="margin:0;" placeholder="Сумма кассовой операции">
                    <input id="accBankPaymentIdDeep" class="auth-input" style="margin:0;" placeholder="Идентификатор фин. операции для платежного поручения">
                    <input id="accBankAccountIdDeep" class="auth-input" style="margin:0;" placeholder="Идентификатор банковского счета">
                    <input id="accBankOrderPurposeDeep" class="auth-input" style="margin:0;" placeholder="Назначение платежа">
                    <input id="accBankOrderAmountDeep" class="auth-input" style="margin:0;" placeholder="Сумма поручения">
                    <input id="accBankImportOrderIdDeep" class="auth-input" style="margin:0;" placeholder="Идентификатор поручения для импорта статуса">
                    <input id="accBankImportExternalDeep" class="auth-input" style="margin:0;" placeholder="Банковская ссылка / внешний идентификатор">
                    <input id="accClosePeriodDeep" class="auth-input" style="margin:0;" placeholder="Период закрытия YYYY-MM" value="${erpDeepEscape(close.selected_period_key || new Date().toISOString().slice(0, 7))}">
                    <input id="accCloseCommentDeep" class="auth-input" style="margin:0;" placeholder="Комментарий к закрытию периода">
                    <input id="accExternalOperatorNameDeep" class="auth-input" style="margin:0;" placeholder="Оператор ЭДО / провайдер">
                    <input id="accExternalApiDeep" class="auth-input" style="margin:0;" placeholder="API endpoint внешнего контура">
                    <input id="accExternalNamespaceDeep" class="auth-input" style="margin:0;" placeholder="Пространство идемпотентности">
                    <input id="accExternalOperatorIdDeep" class="auth-input" style="margin:0;" placeholder="ID оператора для отправки">
                    <input id="accExternalReportTypeDeep" class="auth-input" style="margin:0;" placeholder="Тип отчёта, например vat_return">
                    <input id="accExternalPeriodDeep" class="auth-input" style="margin:0;" placeholder="Период YYYY-MM" value="${erpDeepEscape(close.selected_period_key || new Date().toISOString().slice(0, 7))}">
                </div>
                <div class="finance-actions-row" style="margin-top:12px;">
                    <button class="btn-secondary" onclick="saveAccountingManualDeep()">Ручная операция</button>
                    <button class="btn-secondary" onclick="saveAccountingDebtDeep()">Корректировка долга</button>
                    <button class="btn-secondary" onclick="saveAccountingCashDeep()">Кассовая операция</button>
                    <button class="btn-secondary" onclick="saveBankPaymentOrderDeep()">Поручение</button>
                    <button class="btn-secondary" onclick="exportBankExchangeDeep()">Выгрузить банк</button>
                    <button class="btn-secondary" onclick="importBankExchangeDeep()">Загрузить банк</button>
                    <button class="btn-secondary" onclick="closeAccountingPeriodDeep()">Закрыть период</button>
                    <button class="btn-secondary" onclick="saveAccountingEdoOperatorDeep()">Сохранить оператора ЭДО</button>
                    <button class="btn-secondary" onclick="submitAccountingExternalReportDeep()">Отправить внешнюю отчётность</button>
                    <button class="btn-primary" onclick="rebuildAccountingDeep()">Пересобрать проводки</button>
                </div>
            </section>
            <section class="surface-card surface-card--padded ops-list-card">
                <h3 class="section-title">Книги, регистры и расчеты</h3>
                <div class="table-shell"><table class="admin-table"><thead><tr><th>Счет</th><th>Название</th><th>Тип</th></tr></thead><tbody>${(data.accounts || []).slice(0, 20).map(item => `<tr><td>${erpDeepEscape(item.code)}</td><td>${erpDeepEscape(item.name)}</td><td>${erpDeepEscape(erpDeepTranslateLabel(item.account_type, 'Тип счета'))}</td></tr>`).join('') || `<tr><td colspan="3">План счетов пока пуст.</td></tr>`}</tbody></table></div>
                <div class="client360-grid" style="margin-top:16px;">
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Шаблоны, ручные и касса</h3><div class="client360-list">${erpDeepSimpleRows((data.posting_templates || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.source_label || item.source_type)}</div><div class="client360-item-meta">${erpDeepEscape(item.account_debit)} / ${erpDeepEscape(item.account_credit)} · ${erpDeepEscape(erpDeepTranslateLabel(item.amount_rule || 'full', 'Полная сумма'))}</div></div></div>`, 'Шаблонов проводок пока нет.')}${erpDeepSimpleRows((data.manual_operations || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.description)}</div><div class="client360-item-meta">${erpDeepEscape(item.account_debit)} / ${erpDeepEscape(item.account_credit)} · ${erpDeepMoney(item.amount || 0)}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteAccountingManualDeep(${item.id})">Удалить</button></div></div>`, 'Ручных операций пока нет.')}${erpDeepSimpleRows((data.cash_operations || []).slice(0, 4), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.counterparty_name || item.cashbox_name || 'Касса')}</div><div class="client360-item-meta">${erpDeepMoney(item.amount || 0, item.currency)} · ${erpDeepEscape(erpDeepTranslateLabel(item.direction || '', 'Операция'))}</div></div><div class="view-actions"><button class="btn-danger" onclick="deleteAccountingCashDeep(${item.id})">Удалить</button></div></div>`, 'Кассовых операций пока нет.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">НДС, баланс и книги</h3><div class="client360-list">${erpDeepSimpleRows(data.tax_registers || [], item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.register_name)}</div></div><div class="client360-item-side">${erpDeepMoney(item.value || 0)}</div></div>`, 'Налоговых регистров пока нет.')}${erpDeepSimpleRows((data.vat_by_rate || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.rate_name || 'Ставка')}</div><div class="client360-item-meta">вход ${erpDeepMoney(item.input || 0)} · выход ${erpDeepMoney(item.output || 0)}</div></div><div class="client360-item-side">${erpDeepMoney(item.net || 0)}</div></div>`, 'Раскладки НДС по ставкам пока нет.')}${erpDeepSimpleRows((data.balance_sheet_lines || []).slice(0, 7), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.line_name)}</div><div class="client360-item-meta">${erpDeepEscape(erpDeepTranslateLabel(item.section || '', 'Раздел'))}</div></div><div class="client360-item-side">${erpDeepMoney(item.value || 0)}</div></div>`, 'Баланс пока пуст.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Взаиморасчёты и банковский обмен</h3><div class="client360-list">${erpDeepSimpleRows((data.counterparty_settlements || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(erpDeepDisplayName(item.client_name, `Контрагент ${Number(item.client_id || 0)}`))}</div><div class="client360-item-meta">${erpDeepEscape(erpDeepTranslateLabel(item.aging_bucket || 'future', 'Будущие'))} · ${Number(item.days_overdue || 0)} дн.</div></div><div class="client360-item-side">${erpDeepMoney(item.balance || 0)}</div></div>`, 'Взаиморасчётов с контрагентами пока нет.')}${erpDeepSimpleRows((data.contract_settlements || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.contract_name || `Договор ${Number(item.contract_id || 0)}`)}</div><div class="client360-item-meta">${erpDeepEscape(erpDeepTranslateLabel(item.aging_bucket || 'future', 'Будущие'))} · ${Number(item.days_overdue || 0)} дн.</div></div><div class="client360-item-side">${erpDeepMoney(item.balance || 0)}</div></div>`, 'Взаиморасчётов по договорам пока нет.')}${erpDeepSimpleRows((data.bank_payment_orders || []).slice(0, 6), item => `<div class="client360-item"><div><div class="client360-item-title">Поручение #${Number(item.id || 0)}</div><div class="client360-item-meta">${erpDeepEscape(erpDeepDisplayName(item.counterparty || '', ''))} · ${erpDeepEscape(erpDeepTranslateLabel(item.status || 'draft', 'Черновик'))}</div></div><div class="client360-item-side">${erpDeepMoney(item.amount || 0, item.currency)}</div></div>`, 'Платёжных поручений пока нет.')}${erpDeepSimpleRows((data.exchange_batches || []).slice(0, 4), item => `<div class="client360-item"><div><div class="client360-item-title">Пакет #${Number(item.id || 0)}</div><div class="client360-item-meta">${erpDeepEscape(item.provider_name || '')} · ${erpDeepEscape(erpDeepTranslateLabel(item.status || '', 'Статус'))}</div></div><div class="client360-item-side">${Number(item.item_count || 0)}</div></div>`, 'Пакетов банковского обмена пока нет.')}</div></div>
                </div>
            </section>
            <section class="surface-card surface-card--padded ops-list-card">
                <h3 class="section-title">Закрытие периода и регламентированный контур</h3>
                <div class="client360-grid">
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Периоды и чек-лист</h3><div class="client360-list">${erpDeepSimpleRows((close.periods || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.period_key || '')}</div><div class="client360-item-meta">${erpDeepEscape(erpDeepTranslateLabel(item.status || 'open', 'Открыт'))}</div></div><div class="client360-item-side">${item.closed_at ? new Date(Number(item.closed_at || 0) * 1000).toLocaleDateString('ru-RU') : 'open'}</div></div>`, 'Периоды пока не зарегистрированы.')}${erpDeepSimpleRows((close.checklist || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.title || item.code || '')}</div><div class="client360-item-meta">${erpDeepEscape(item.message || '')}</div></div><div class="client360-item-side">${erpDeepEscape(erpDeepTranslateLabel(item.status || 'pass', 'Статус'))}</div></div>`, 'Чек-лист закрытия пока не собран.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Налоги и отчетность</h3><div class="client360-list">${erpDeepSimpleRows((close.tax_accruals || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.tax_name || item.tax_type || '')}</div><div class="client360-item-meta">${erpDeepEscape(item.account_debit || '')} / ${erpDeepEscape(item.account_credit || '')} · ${erpDeepEscape(erpDeepTranslateLabel(item.status || 'draft', 'Черновик'))}</div></div><div class="client360-item-side">${erpDeepMoney(item.amount || 0)}</div></div>`, 'Налоговые начисления еще не сформированы.')}${erpDeepSimpleRows((close.report_snapshots || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.report_name || item.report_type || '')}</div><div class="client360-item-meta">${Number(item.line_count || 0)} строк</div></div><div class="client360-item-side">${erpDeepMoney(item.amount_total || 0)}</div></div>`, 'Снимков отчетности пока нет.')}</div></div>
                    <div class="surface-card surface-card--padded"><h3 class="section-title">Сверка регистров и ОСВ</h3><div class="client360-list">${erpDeepSimpleRows((close.register_reconciliations || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.register_name || '')}</div><div class="client360-item-meta">${erpDeepEscape(erpDeepTranslateLabel(item.status || 'ok', 'Ок'))}</div></div><div class="client360-item-side">${Number(item.mismatch_count || 0)}</div></div>`, 'Сверок регистров пока нет.')}${erpDeepSimpleRows((close.trial_balance || []).slice(0, 8), item => `<div class="client360-item"><div><div class="client360-item-title">${erpDeepEscape(item.account_code || '')} ${erpDeepEscape(item.account_name || '')}</div><div class="client360-item-meta">оборот ${erpDeepMoney(item.turnover_debit || 0)} / ${erpDeepMoney(item.turnover_credit || 0)}</div></div><div class="client360-item-side">${erpDeepMoney((item.closing_debit || 0) - (item.closing_credit || 0))}</div></div>`, 'ОСВ пока не собрана.')}</div></div>
                </div>
            </section>
            <section class="surface-card surface-card--padded ops-list-card">
                <h3 class="section-title">Внешний ЭДО и налоговый контур</h3>
                <div class="client360-grid">
                    <div class="surface-card surface-card--padded">
                        <h3 class="section-title">Операторы и здоровье контура</h3>
                        <div class="client360-list">
                            ${erpDeepSimpleRows((data.edo_operators || []).slice(0, 8), item => `<div class="client360-item client360-item--stack"><div class="client360-item-title">${erpDeepEscape(item.operator_name || item.provider_name || 'Оператор')}</div><div class="client360-item-meta">${erpDeepEscape(item.provider_name || '')} · ${erpDeepEscape(erpDeepTranslateLabel(item.status || 'active', 'Активный'))}</div><div class="client360-item-meta">${erpDeepEscape(item.contour_type || 'reporting')} · namespace ${erpDeepEscape(item.idempotency_namespace || '—')}</div><div class="client360-item-meta">${erpDeepEscape(item.api_endpoint || 'endpoint не задан')} · ошибок ${erpDeepEscape(item.last_error || 'нет')}</div></div>`, 'Операторы ЭДО пока не заведены.')}
                            <div class="client360-item">
                                <div>
                                    <div class="client360-item-title">Подписи и сертификаты</div>
                                    <div class="client360-item-meta">Валидных подписей: ${Number(exchangeHealth.verified_signatures || 0)} · невалидных: ${Number(exchangeHealth.invalid_signatures || 0)}</div>
                                </div>
                                <div class="client360-item-side">${Number(exchangeHealth.certificates_expiring || 0)} истекает</div>
                            </div>
                        </div>
                    </div>
                    <div class="surface-card surface-card--padded">
                        <h3 class="section-title">Отправки и статусы</h3>
                        <div class="client360-list">
                            ${erpDeepSimpleRows((data.external_submissions || []).slice(0, 10), item => `<div class="client360-item client360-item--stack"><div class="client360-item-title">${erpDeepEscape(item.report_type || 'regulated_report')} · ${erpDeepEscape(item.period_key || '')}</div><div class="client360-item-meta">${erpDeepEscape(item.operator_name || item.provider_name || 'Оператор')} · ${erpDeepEscape(erpDeepTranslateLabel(item.submission_status || 'queued', 'Статус'))}</div><div class="client360-item-meta">Протокол ${erpDeepEscape(item.protocol_number || '—')} · квитанция ${erpDeepEscape(item.receipt_number || '—')}</div><div class="view-actions" style="margin-top:8px;"><button class="btn-secondary" onclick="acceptAccountingExternalReportDeep(${Number(item.id || 0)})">Принять статус</button><button class="btn-secondary" onclick="retryAccountingExternalReportDeep(${Number(item.id || 0)})">Повторить</button></div></div>`, 'Отправок во внешний контур пока нет.')}
                        </div>
                    </div>
                    <div class="surface-card surface-card--padded">
                        <h3 class="section-title">Журнал обмена</h3>
                        <div class="client360-list">
                            ${erpDeepSimpleRows((data.external_events || []).slice(0, 12), item => `<div class="client360-item client360-item--stack"><div class="client360-item-title">${erpDeepEscape(item.event_type || 'event')} · ${erpDeepEscape(erpDeepTranslateLabel(item.status_after || '', 'Статус'))}</div><div class="client360-item-meta">${erpDeepEscape(item.message || 'Сообщение не заполнено')}</div><div class="client360-item-meta">${erpDeepEscape(item.created_by || 'system')} · ${Number(item.created_at || 0) ? new Date(Number(item.created_at || 0) * 1000).toLocaleString('ru-RU') : '—'}</div></div>`, 'Событий внешнего контура пока нет.')}
                        </div>
                    </div>
                </div>
            </section>
        </div>
    `;
}

async function saveProductionSpecDeep() {
    const order = typeof getSelectedProductionOrder === 'function' ? getSelectedProductionOrder() : null;
    const ok = await erpDeepSave('/production/spec_versions', { order_id: Number(selectedProductionOrderId || order?.id || 0), project_id: Number(order?.project_id || 0), label: document.getElementById('prodSpecLabelDeep')?.value.trim() || '', comment: `снимок ${new Date().toLocaleString('ru-RU')}` }, 'Версия спецификации сохранена');
    if (ok) await renderProduction();
}
async function saveProductionTechCardDeep() { const ok = await erpDeepSave('/production/tech_cards/deep', { order_id: Number(selectedProductionOrderId || 0), title: document.getElementById('prodTechTitleDeep')?.value.trim() || '', work_center: getSelectedProductionOrder?.()?.route_name || '' }, 'Техкарта сохранена'); if (ok) await renderProduction(); }
async function saveProductionShiftDeep() { const ok = await erpDeepSave('/production/shifts/deep', { legal_entity_id: Number(document.getElementById('productionLegalEntityId')?.value || 0), business_unit_id: Number(document.getElementById('productionBusinessUnitId')?.value || 0), shift_name: document.getElementById('prodShiftNameDeep')?.value.trim() || '', shift_date: new Date().toLocaleDateString('ru-RU'), work_center: getSelectedProductionOrder?.()?.route_name || '', capacity_hours: 8 }, 'Смена сохранена'); if (ok) await renderProduction(); }
async function saveProductionJobDeep() { const ok = await erpDeepSave('/production/jobs/deep', { order_id: Number(selectedProductionOrderId || 0), title: document.getElementById('prodJobTitleDeep')?.value.trim() || '', work_center: getSelectedProductionOrder?.()?.route_name || '', planned_qty: Number(document.getElementById('productionPlannedQty')?.value || 0), status: 'queued' }, 'Задание сохранено'); if (ok) await renderProduction(); }
async function saveProductionMaterialNormDeep() { const ok = await erpDeepSave('/production/material_norms/deep', { order_id: Number(selectedProductionOrderId || 0), article: document.getElementById('prodMaterialArticleDeep')?.value.trim() || '', item_name: document.getElementById('prodMaterialArticleDeep')?.value.trim() || '', norm_qty: Number(document.getElementById('productionBomQtyPerUnit')?.value || 1) || 1 }, 'Материальная норма сохранена'); if (ok) await renderProduction(); }
async function saveProductionLaborNormDeep() { const ok = await erpDeepSave('/production/labor_norms/deep', { order_id: Number(selectedProductionOrderId || 0), operation_name: document.getElementById('prodLaborOperationDeep')?.value.trim() || '', work_center: getSelectedProductionOrder?.()?.route_name || '', norm_hours: Number(document.getElementById('productionOperationPlannedHours')?.value || 1) || 1, rate_per_hour: Number(document.getElementById('productionOperationLaborRate')?.value || 0) }, 'Трудовая норма сохранена'); if (ok) await renderProduction(); }
async function saveProductionSemifinishedDeep() { const ok = await erpDeepSave('/production/semifinished/deep', { order_id: Number(selectedProductionOrderId || 0), article: document.getElementById('prodSemiArticleDeep')?.value.trim() || '', item_name: document.getElementById('prodSemiArticleDeep')?.value.trim() || '', qty: Number(document.getElementById('productionProducedQty')?.value || 0), stage_name: getSelectedProductionOrder?.()?.stage || '', unit_cost: Number(document.getElementById('productionActualCost')?.value || 0) }, 'Полуфабрикат сохранен'); if (ok) await renderProduction(); }
async function saveProductionReworkDeep() { const ok = await erpDeepSave('/production/rework/deep', { order_id: Number(selectedProductionOrderId || 0), defect_name: document.getElementById('prodReworkDefectDeep')?.value.trim() || '', qty: Number(document.getElementById('productionScrapQty')?.value || 0), reason: 'оперативная фиксация', extra_cost: Number(document.getElementById('productionActualCost')?.value || 0) * 0.1 }, 'Переработка брака сохранена'); if (ok) await renderProduction(); }
async function deleteProductionSpecDeep(id) { if (await erpDeepDelete(`/production/spec_versions/${id}`, 'Версия удалена')) await renderProduction(); }
async function deleteProductionTechCardDeep(id) { if (await erpDeepDelete(`/production/tech_cards/deep/${id}`, 'Техкарта удалена')) await renderProduction(); }
async function deleteProductionShiftDeep(id) { if (await erpDeepDelete(`/production/shifts/deep/${id}`, 'Смена удалена')) await renderProduction(); }
async function deleteProductionJobDeep(id) { if (await erpDeepDelete(`/production/jobs/deep/${id}`, 'Задание удалено')) await renderProduction(); }
async function deleteProductionMaterialNormDeep(id) { if (await erpDeepDelete(`/production/material_norms/deep/${id}`, 'Матнорма удалена')) await renderProduction(); }
async function deleteProductionLaborNormDeep(id) { if (await erpDeepDelete(`/production/labor_norms/deep/${id}`, 'Труднорма удалена')) await renderProduction(); }
async function deleteProductionSemifinishedDeep(id) { if (await erpDeepDelete(`/production/semifinished/deep/${id}`, 'Полуфабрикат удален')) await renderProduction(); }
async function deleteProductionReworkDeep(id) { if (await erpDeepDelete(`/production/rework/deep/${id}`, 'Переработка удалена')) await renderProduction(); }
function selectedProductionPlanningScenarioId() {
    const scenarios = erpDeepDB.production?.mrp_aps?.scenarios || [];
    const active = scenarios.find(item => String(item.status || '') === 'active') || scenarios[0];
    return Number(active?.id || 0);
}
async function saveProductionScenarioDeep() {
    const scenarioName = document.getElementById('prodScenarioNameDeep')?.value.trim() || `MRP/APS ${new Date().toLocaleDateString('ru-RU')}`;
    const ok = await erpDeepSave('/production/mrp_aps/scenarios', {
        scenario_name: scenarioName,
        planning_horizon_days: Number(document.getElementById('prodScenarioHorizonDeep')?.value || 30) || 30,
        demand_mode: 'confirmed_orders',
        status: 'active',
        demand_multiplier: Number(document.getElementById('prodScenarioDemandDeep')?.value || 1) || 1,
        capacity_multiplier: Number(document.getElementById('prodScenarioCapacityDeep')?.value || 1) || 1,
        lead_time_days: 0,
        freeze_days: 0,
        comment: 'Сценарий MRP/APS из производственного контура',
    }, 'Сценарий MRP/APS сохранен');
    if (ok) await renderProduction();
}
async function runProductionMrpApsDeep() {
    const res = await apiCall('/production/mrp_aps/run', 'POST', {
        scenario_id: selectedProductionPlanningScenarioId(),
        run_name: `MRP/APS ${new Date().toLocaleString('ru-RU')}`,
        persist: 1,
    });
    if (!res || res.error) {
        await customAlert(res?.message || res?.error || 'Не удалось рассчитать MRP/APS.');
        return;
    }
    await renderProduction();
    showToast('Производство', `MRP/APS рассчитан: дефицитов ${Number(res.plan?.metrics?.shortages || 0)}`);
}
async function replanProductionMrpApsDeep() {
    const res = await apiCall('/production/mrp_aps/replan', 'POST', {
        scenario_id: selectedProductionPlanningScenarioId(),
        run_name: `Перепланирование ${new Date().toLocaleString('ru-RU')}`,
        persist: 1,
    });
    if (!res || res.error) {
        await customAlert(res?.message || res?.error || 'Не удалось выполнить перепланирование.');
        return;
    }
    await renderProduction();
    showToast('Производство', `Перепланировано: операций без мощности ${Number(res.plan?.metrics?.unscheduled_operations || 0)}`);
}
async function deleteProductionScenarioDeep(id) { if (await erpDeepDelete(`/production/mrp_aps/scenarios/${id}`, 'Сценарий MRP/APS удален')) await renderProduction(); }

async function saveFinanceRequestDeep() { const ok = await erpDeepSave('/finance/payment_requests', { title: document.getElementById('financeRequestTitleDeep')?.value.trim() || '', amount: Number(document.getElementById('financeRequestAmountDeep')?.value || 0), currency: 'RUB', due_date: new Date().toLocaleDateString('ru-RU'), legal_entity_id: Number(document.getElementById('financeLegalEntityId')?.value || 0), business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0), request_status: 'approved' }, 'Заявка на оплату сохранена'); if (ok) await renderFinance(); }
async function saveFinanceLimitDeep() { const ok = await erpDeepSave('/finance/project_limits', { project_id: Number(document.getElementById('financeLimitProjectDeep')?.value || 0), business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0), amount_limit: Number(document.getElementById('financeLimitAmountDeep')?.value || 0), period_key: new Date().toISOString().slice(0, 7) }, 'Лимит проекта сохранен'); if (ok) await renderFinance(); }
async function saveFinanceBudgetDeep() { const ok = await erpDeepSave('/finance/budgets/deep', { budget_type: 'pnl', period_key: new Date().toISOString().slice(0, 7), article_name: document.getElementById('financeBudgetArticleDeep')?.value.trim() || '', plan_amount: Number(document.getElementById('financeBudgetPlanDeep')?.value || 0), fact_amount: 0, business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0) }, 'Бюджет сохранен'); if (ok) await renderFinance(); }
async function saveFinanceObligationDeep() { const ok = await erpDeepSave('/finance/obligations/deep', { title: document.getElementById('financeObligationTitleDeep')?.value.trim() || '', amount: Number(document.getElementById('financeObligationAmountDeep')?.value || 0), currency: 'RUB', due_date: new Date().toLocaleDateString('ru-RU'), status: 'open' }, 'Обязательство сохранено'); if (ok) await renderFinance(); }
async function saveFinanceScenarioDeep() { const ok = await erpDeepSave('/finance/cash_gap_scenarios', { scenario_name: document.getElementById('financeScenarioNameDeep')?.value.trim() || '', period_key: new Date().toISOString().slice(0, 7), gap_amount: Number(document.getElementById('financeScenarioGapDeep')?.value || 0), opening_balance: 0, expected_inflow: 0, expected_outflow: Number(document.getElementById('financeScenarioGapDeep')?.value || 0) }, 'Сценарий кассового разрыва сохранён'); if (ok) await renderFinance(); }
async function saveTreasuryRouteDeep() {
    const stages = (document.getElementById('financeTreasuryRouteStagesDeep')?.value || '')
        .split(',')
        .map(item => item.trim())
        .filter(Boolean)
        .map((role, index) => ({ step: index + 1, role }));
    const ok = await erpDeepSave('/finance/treasury_routes', {
        route_name: document.getElementById('financeTreasuryRouteNameDeep')?.value.trim() || 'Маршрут согласования',
        legal_entity_id: Number(document.getElementById('financeLegalEntityId')?.value || 0),
        business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0),
        min_amount: Number(document.getElementById('financeTreasuryRouteMinDeep')?.value || 0),
        max_amount: Number(document.getElementById('financeTreasuryRouteMaxDeep')?.value || 0),
        currency: 'RUB',
        stages,
        is_active: 1,
    }, 'Маршрут казначейства сохранен');
    if (ok) await renderFinance();
}
async function deleteFinanceRequestDeep(id) { if (await erpDeepDelete(`/finance/payment_requests/${id}`, 'Заявка удалена')) await renderFinance(); }
async function deleteFinanceLimitDeep(id) { if (await erpDeepDelete(`/finance/project_limits/${id}`, 'Лимит удален')) await renderFinance(); }
async function deleteFinanceBudgetDeep(id) { if (await erpDeepDelete(`/finance/budgets/deep/${id}`, 'Бюджет удален')) await renderFinance(); }
async function deleteFinanceObligationDeep(id) { if (await erpDeepDelete(`/finance/obligations/deep/${id}`, 'Обязательство удалено')) await renderFinance(); }
async function deleteFinanceScenarioDeep(id) { if (await erpDeepDelete(`/finance/cash_gap_scenarios/${id}`, 'Сценарий удален')) await renderFinance(); }

async function saveAccountingManualDeep() { const ok = await erpDeepSave('/accounting/manual_operations', { entry_date: new Date().toLocaleDateString('ru-RU'), legal_entity_id: Number(document.getElementById('financeLegalEntityId')?.value || 0), business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0), account_debit: document.getElementById('accManualDebitDeep')?.value.trim() || '76', account_credit: document.getElementById('accManualCreditDeep')?.value.trim() || '91.01', amount: Number(document.getElementById('accManualAmountDeep')?.value || 0), description: document.getElementById('accManualDescDeep')?.value.trim() || 'Ручная операция' }, 'Ручная операция сохранена'); if (ok) await renderAccounting(); }
async function saveAccountingDebtDeep() { const ok = await erpDeepSave('/accounting/debt_adjustments', { adjustment_date: new Date().toLocaleDateString('ru-RU'), amount: Number(document.getElementById('accDebtAmountDeep')?.value || 0), reason: document.getElementById('accDebtReasonDeep')?.value.trim() || '', account_debit: '91.02', account_credit: '62.01' }, 'Корректировка долга сохранена'); if (ok) await renderAccounting(); }
async function saveAccountingCashDeep() { const ok = await erpDeepSave('/accounting/cash_operations', { operation_date: new Date().toLocaleDateString('ru-RU'), legal_entity_id: Number(document.getElementById('financeLegalEntityId')?.value || 0), business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0), direction: 'incoming', amount: Number(document.getElementById('accCashAmountDeep')?.value || 0), currency: 'RUB', counterparty_name: document.getElementById('accCashCounterpartyDeep')?.value.trim() || '' }, 'Кассовая операция сохранена'); if (ok) await renderAccounting(); }
async function saveBankPaymentOrderDeep() {
    const ok = await erpDeepSave('/banking/payment_orders', {
        payment_id: Number(document.getElementById('accBankPaymentIdDeep')?.value || 0),
        bank_account_id: Number(document.getElementById('accBankAccountIdDeep')?.value || 0),
        legal_entity_id: Number(document.getElementById('financeLegalEntityId')?.value || 0),
        business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0),
        order_date: new Date().toLocaleDateString('ru-RU'),
        amount: Number(document.getElementById('accBankOrderAmountDeep')?.value || 0),
        currency: 'RUB',
        purpose: document.getElementById('accBankOrderPurposeDeep')?.value.trim() || '',
    }, 'Платежное поручение сохранено');
    if (ok) await renderAccounting();
}
async function exportBankExchangeDeep() {
    const orders = (erpDeepDB.accounting?.bank_payment_orders || []).filter(item => item.status === 'draft').slice(0, 10).map(item => Number(item.id));
    if (!orders.length) { await customAlert('Нет draft-платежных поручений для экспорта.'); return; }
    const ok = await erpDeepSave('/banking/exchange_batches/export', {
        provider_name: 'bank_api',
        batch_type: 'payment_exchange',
        bank_account_id: Number(document.getElementById('accBankAccountIdDeep')?.value || 0),
        payment_order_ids: orders,
    }, 'Пакет банковского обмена выгружен');
    if (ok) await renderAccounting();
}
async function importBankExchangeDeep() {
    const orderId = Number(document.getElementById('accBankImportOrderIdDeep')?.value || 0);
    if (!orderId) { await customAlert('Укажи идентификатор платежного поручения для импорта статуса.'); return; }
    const ok = await erpDeepSave('/banking/exchange_batches/import_result', {
        provider_name: 'bank_api',
        batch_type: 'payment_exchange',
        result_items: [{
            payment_order_id: orderId,
            status: 'executed',
            external_payment_id: document.getElementById('accBankImportExternalDeep')?.value.trim() || `BANK-${orderId}`,
            executed_at: new Date().toLocaleDateString('ru-RU'),
        }],
    }, 'Статус банковского обмена импортирован');
    if (ok) await renderAccounting();
}
async function closeAccountingPeriodDeep() {
    const period_key = document.getElementById('accClosePeriodDeep')?.value.trim() || '';
    if (!period_key) { await customAlert('Укажи период в формате YYYY-MM.'); return; }
    const res = await apiCall('/accounting/periods/close_cycle', 'POST', {
        period_key,
        comment: document.getElementById('accCloseCommentDeep')?.value.trim() || '',
    });
    if (!res || res.error) {
        await customAlert(res?.error || 'Не удалось закрыть период.');
        return;
    }
    await renderAccounting();
    if (Array.isArray(res.warnings) && res.warnings.length) {
        await customAlert(`Период ${period_key} закрыт с предупреждениями:\n\n${res.warnings.join('\n')}`);
        return;
    }
    showToast('Бухгалтерия', res.already_closed ? `Период ${period_key} уже был закрыт` : `Период ${period_key} закрыт`);
}
async function saveAccountingEdoOperatorDeep() {
    const ok = await erpDeepSave('/accounting/edo_operators', {
        operator_name: document.getElementById('accExternalOperatorNameDeep')?.value.trim() || '',
        provider_name: '1С-ЭДО',
        contour_type: 'tax',
        api_endpoint: document.getElementById('accExternalApiDeep')?.value.trim() || '',
        legal_entity_id: Number(document.getElementById('financeLegalEntityId')?.value || 0),
        business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0),
        idempotency_namespace: document.getElementById('accExternalNamespaceDeep')?.value.trim() || '',
        capabilities: ['reporting', 'edo', 'tax'],
        retry_policy: { max_retries: 3, delay_minutes: 15 },
    }, 'Оператор внешнего контура сохранён');
    if (ok) await renderAccounting();
}
async function submitAccountingExternalReportDeep() {
    const fallbackOperator = Number(erpDeepDB.accounting?.edo_operators?.[0]?.id || 0);
    const period_key = document.getElementById('accExternalPeriodDeep')?.value.trim() || new Date().toISOString().slice(0, 7);
    const report_type = document.getElementById('accExternalReportTypeDeep')?.value.trim() || 'vat_return';
    const ok = await erpDeepSave('/accounting/external_reporting/submissions', {
        operator_id: Number(document.getElementById('accExternalOperatorIdDeep')?.value || fallbackOperator),
        contour_type: 'tax',
        report_type,
        period_key,
        legal_entity_id: Number(document.getElementById('financeLegalEntityId')?.value || 0),
        business_unit_id: Number(document.getElementById('financeBusinessUnitId')?.value || 0),
    }, 'Отчётность отправлена во внешний контур');
    if (ok) await renderAccounting();
}
async function retryAccountingExternalReportDeep(id) {
    const res = await apiCall(`/accounting/external_reporting/submissions/${id}/retry`, 'POST', {});
    if (!res || res.error) {
        await customAlert(res?.message || res?.error || 'Не удалось повторить отправку.');
        return;
    }
    showToast('Бухгалтерия', 'Повторная отправка поставлена в работу');
    await renderAccounting();
}
async function acceptAccountingExternalReportDeep(id) {
    const res = await apiCall(`/accounting/external_reporting/submissions/${id}/sync_status`, 'POST', {
        submission_status: 'accepted',
        protocol_number: `PROT-${id}`,
        receipt_number: `RCPT-${id}`,
        message: 'Отчётность принята оператором',
    });
    if (!res || res.error) {
        await customAlert(res?.message || res?.error || 'Не удалось синхронизировать статус.');
        return;
    }
    showToast('Бухгалтерия', 'Статус оператора обновлён');
    await renderAccounting();
}
async function rebuildAccountingDeep() { const ok = await erpDeepSave('/accounting/rebuild_auto', {}, 'Автопроводки пересобраны'); if (ok) await renderAccounting(); }
async function deleteAccountingManualDeep(id) { if (await erpDeepDelete(`/accounting/manual_operations/${id}`, 'Ручная операция удалена')) await renderAccounting(); }
async function deleteAccountingDebtDeep(id) { if (await erpDeepDelete(`/accounting/debt_adjustments/${id}`, 'Корректировка удалена')) await renderAccounting(); }
async function deleteAccountingCashDeep(id) { if (await erpDeepDelete(`/accounting/cash_operations/${id}`, 'Кассовая операция удалена')) await renderAccounting(); }

const baseRenderProductionDeep = typeof renderProduction === 'function' ? renderProduction : null;
if (baseRenderProductionDeep) {
    renderProduction = async function renderProductionWithDeep() {
        await baseRenderProductionDeep();
        await loadProductionDeepData();
        const wipMount = document.getElementById('productionWipBoardMount');
        const shiftMount = document.getElementById('productionShiftBoardMount');
        const normMount = document.getElementById('productionNormFactMount');
        const logMount = document.getElementById('productionChangeLogMount');
        if (wipMount) wipMount.innerHTML = renderProductionWipBoard();
        if (shiftMount) shiftMount.innerHTML = renderProductionShiftBoard();
        if (normMount) normMount.innerHTML = renderProductionNormFactBoard();
        if (logMount) logMount.innerHTML = renderProductionChangeLog();
        const mount = document.getElementById('productionDeepMount');
        if (mount) mount.innerHTML = renderProductionDeepMount();
    };
    window.renderProduction = renderProduction;
}

const baseRenderFinanceDeep = typeof renderFinance === 'function' ? renderFinance : null;
if (baseRenderFinanceDeep) {
    renderFinance = async function renderFinanceWithDeep() {
        await baseRenderFinanceDeep();
        await loadFinanceDeepData();
        await loadAccountingDeepData();
        const mount = document.getElementById('financeDeepMount');
        if (mount) mount.innerHTML = renderFinanceDeepMount();
        const accountingMount = document.getElementById('accountingDeepMount');
        if (accountingMount) accountingMount.innerHTML = renderAccountingDeepMount();
    };
    window.renderFinance = renderFinance;
}

const baseRenderAccountingDeep = typeof renderAccounting === 'function' ? renderAccounting : null;
if (baseRenderAccountingDeep) {
    renderAccounting = async function renderAccountingWithDeep() {
        await baseRenderAccountingDeep();
        await loadAccountingDeepData();
        const mount = document.getElementById('accountingDeepMount');
        if (mount) mount.innerHTML = renderAccountingDeepMount();
    };
    window.renderAccounting = renderAccounting;
}

window.saveProductionSpecDeep = saveProductionSpecDeep;
window.saveProductionTechCardDeep = saveProductionTechCardDeep;
window.saveProductionShiftDeep = saveProductionShiftDeep;
window.saveProductionJobDeep = saveProductionJobDeep;
window.saveProductionMaterialNormDeep = saveProductionMaterialNormDeep;
window.saveProductionLaborNormDeep = saveProductionLaborNormDeep;
window.saveProductionSemifinishedDeep = saveProductionSemifinishedDeep;
window.saveProductionReworkDeep = saveProductionReworkDeep;
window.deleteProductionSpecDeep = deleteProductionSpecDeep;
window.deleteProductionTechCardDeep = deleteProductionTechCardDeep;
window.deleteProductionShiftDeep = deleteProductionShiftDeep;
window.deleteProductionJobDeep = deleteProductionJobDeep;
window.deleteProductionMaterialNormDeep = deleteProductionMaterialNormDeep;
window.deleteProductionLaborNormDeep = deleteProductionLaborNormDeep;
window.deleteProductionSemifinishedDeep = deleteProductionSemifinishedDeep;
window.deleteProductionReworkDeep = deleteProductionReworkDeep;
window.saveProductionScenarioDeep = saveProductionScenarioDeep;
window.runProductionMrpApsDeep = runProductionMrpApsDeep;
window.replanProductionMrpApsDeep = replanProductionMrpApsDeep;
window.deleteProductionScenarioDeep = deleteProductionScenarioDeep;
window.saveFinanceRequestDeep = saveFinanceRequestDeep;
window.saveFinanceLimitDeep = saveFinanceLimitDeep;
window.saveFinanceBudgetDeep = saveFinanceBudgetDeep;
window.saveFinanceObligationDeep = saveFinanceObligationDeep;
window.saveFinanceScenarioDeep = saveFinanceScenarioDeep;
window.saveTreasuryRouteDeep = saveTreasuryRouteDeep;
window.deleteFinanceRequestDeep = deleteFinanceRequestDeep;
window.deleteFinanceLimitDeep = deleteFinanceLimitDeep;
window.deleteFinanceBudgetDeep = deleteFinanceBudgetDeep;
window.deleteFinanceObligationDeep = deleteFinanceObligationDeep;
window.deleteFinanceScenarioDeep = deleteFinanceScenarioDeep;
window.saveAccountingManualDeep = saveAccountingManualDeep;
window.saveAccountingDebtDeep = saveAccountingDebtDeep;
window.saveAccountingCashDeep = saveAccountingCashDeep;
window.saveBankPaymentOrderDeep = saveBankPaymentOrderDeep;
window.exportBankExchangeDeep = exportBankExchangeDeep;
window.importBankExchangeDeep = importBankExchangeDeep;
window.saveAccountingEdoOperatorDeep = saveAccountingEdoOperatorDeep;
window.submitAccountingExternalReportDeep = submitAccountingExternalReportDeep;
window.retryAccountingExternalReportDeep = retryAccountingExternalReportDeep;
window.acceptAccountingExternalReportDeep = acceptAccountingExternalReportDeep;
window.rebuildAccountingDeep = rebuildAccountingDeep;
window.deleteAccountingManualDeep = deleteAccountingManualDeep;
window.deleteAccountingDebtDeep = deleteAccountingDebtDeep;
window.deleteAccountingCashDeep = deleteAccountingCashDeep;
