let expenseRequestsDB = [];
let internalRequestsDB = [];
let resourceAllocationsDB = [];
let serviceCasesDB = [];
let budgetLinesDB = [];
let executiveSummaryDB = null;
let expenseSummaryDB = null;
let internalSummaryDB = null;
let resourceSummaryDB = null;
let serviceSummaryDB = null;
let erpProcessesDB = [];
let erpSummaryDB = null;
let erpDataQualityDB = null;
let integrationQueueDB = [];
let integrationMonitoringDB = null;
let executiveFinanceAnalyticsDB = null;
let executiveAnalyticsDeepDB = null;
let executiveDashboardHubDB = null;
let executiveDrilldownDB = null;
let operationsMonitoringDB = null;
let reconciliationRunsDB = [];
let bankAccountsOpsDB = [];
let bankStatementLinesOpsDB = [];
let telephonyAccountsOpsDB = [];
let telephonyCallsOpsDB = [];
let telephonySpeechRecognition = null;
let telephonySpeechBaseText = '';
let telephonyImportResultCache = null;
let savedReportsOpsDB = [];
let operationsReliabilityDB = null;
let operationsRuntimeDB = null;
let operationsEventStreamDB = [];
window.__executiveSecondaryExpanded = window.__executiveSecondaryExpanded || false;
window.__operationsSecondaryExpanded = window.__operationsSecondaryExpanded || false;

let editingExpenseId = 0;
let selectedExpenseId = 0;
let editingInternalId = 0;
let selectedInternalRequestId = 0;
let editingResourceId = 0;
let editingServiceId = 0;
const internalRequestBulkSelection = window.internalRequestBulkSelection || new Set();
window.internalRequestBulkSelection = internalRequestBulkSelection;

function getSelectedInternalRequestIds() {
    return Array.from(internalRequestBulkSelection).map(Number).filter(Boolean);
}

function getSelectedInternalRequests() {
    const ids = new Set(getSelectedInternalRequestIds());
    return internalRequestsDB.filter(item => ids.has(Number(item.id || 0)));
}

function pruneSelectedInternalRequests() {
    const validIds = new Set(internalRequestsDB.map(item => Number(item.id || 0)).filter(Boolean));
    Array.from(internalRequestBulkSelection).forEach(id => {
        if (!validIds.has(Number(id))) internalRequestBulkSelection.delete(id);
    });
}

function toggleInternalRequestSelection(requestId, checked) {
    const id = Number(requestId || 0);
    if (!id) return;
    if (checked) internalRequestBulkSelection.add(id);
    else internalRequestBulkSelection.delete(id);
    renderInternalRequestBulkToolbar();
}

function clearInternalRequestBulkSelection() {
    internalRequestBulkSelection.clear();
    renderInternalRequests();
}

function selectVisibleInternalRequests() {
    internalRequestsDB.forEach(item => {
        const id = Number(item.id || 0);
        if (id) internalRequestBulkSelection.add(id);
    });
    renderInternalRequests();
}

function renderInternalRequestBulkCheckbox(requestId) {
    const id = Number(requestId || 0);
    const checked = internalRequestBulkSelection.has(id) ? 'checked' : '';
    return `<input type="checkbox" class="bulk-row-checkbox" ${checked} aria-label="Выбрать заявку" onchange="toggleInternalRequestSelection(${id}, this.checked)">`;
}

function renderInternalRequestBulkToolbar() {
    const mount = document.getElementById('internalBulkActionsMount');
    if (!mount) return;
    const count = getSelectedInternalRequests().length;
    mount.innerHTML = `
        <div class="bulk-actions-bar ${count ? 'is-active' : ''}">
            <div class="bulk-actions-count">Выбрано: ${count}</div>
            <button class="btn-secondary" onclick="selectVisibleInternalRequests()">Выбрать видимые</button>
            <select id="internalBulkStatus" class="auth-input bulk-actions-select" ${count ? '' : 'disabled'}>
                <option value="new">Новая</option>
                <option value="in_work">В работе</option>
                <option value="done">Завершена</option>
                <option value="cancelled">Отменена</option>
            </select>
            <button class="btn-secondary" onclick="applyInternalRequestBulkStatus()" ${count ? '' : 'disabled'}>Сменить статус</button>
            <input id="internalBulkAssignee" class="auth-input bulk-actions-input" placeholder="Исполнитель" ${count ? '' : 'disabled'}>
            <button class="btn-secondary" onclick="assignInternalRequestBulkAssignee()" ${count ? '' : 'disabled'}>Назначить</button>
            <button class="btn-secondary" onclick="exportSelectedInternalRequests()" ${count ? '' : 'disabled'}>Экспорт</button>
            <button class="btn-secondary" onclick="clearInternalRequestBulkSelection()" ${count ? '' : 'disabled'}>Снять выбор</button>
        </div>
    `;
}

function internalRequestBulkPayload(item, overrides = {}) {
    return {
        project_id: Number(item.project_id || 0),
        contract_id: Number(item.contract_id || 0),
        object_id: Number(item.object_id || 0),
        title: item.title || '',
        request_type: item.request_type || 'purchase',
        target_role: item.target_role || 'Менеджер',
        assignee_name: item.assignee_name || '',
        deadline: item.deadline || '',
        priority: item.priority || 'normal',
        status: item.status || 'new',
        comment: item.comment || '',
        ...overrides,
    };
}

async function applyInternalRequestBulkStatus() {
    const rows = getSelectedInternalRequests();
    const status = document.getElementById('internalBulkStatus')?.value || '';
    if (!rows.length) return customAlert('Сначала выбери заявки.');
    if (!status) return customAlert('Выбери статус.');
    for (const row of rows) {
        const res = await apiCall(`/internal_requests/${row.id}`, 'PUT', internalRequestBulkPayload(row, { status }));
        if (!res || res.error) return customAlert(`Не удалось обновить заявку #${row.id}.`);
    }
    internalRequestBulkSelection.clear();
    await renderInternalRequests();
    showToast('Заявки', `Статус обновлён: ${rows.length}`);
}

async function assignInternalRequestBulkAssignee() {
    const rows = getSelectedInternalRequests();
    const assignee = document.getElementById('internalBulkAssignee')?.value.trim() || '';
    if (!rows.length) return customAlert('Сначала выбери заявки.');
    if (!assignee) return customAlert('Укажи исполнителя.');
    for (const row of rows) {
        const res = await apiCall(`/internal_requests/${row.id}`, 'PUT', internalRequestBulkPayload(row, { assignee_name: assignee }));
        if (!res || res.error) return customAlert(`Не удалось назначить исполнителя для заявки #${row.id}.`);
    }
    internalRequestBulkSelection.clear();
    await renderInternalRequests();
    showToast('Заявки', `Исполнитель назначен: ${rows.length}`);
}

function exportSelectedInternalRequests() {
    const rows = getSelectedInternalRequests();
    if (!rows.length) return customAlert('Сначала выбери заявки для экспорта.');
    if (typeof XLSX === 'undefined') return customAlert('Модуль экспорта пока не загрузился. Обнови страницу и попробуй ещё раз.');
    const exportRows = rows.map(item => ({
        'Заявка': item.title || '',
        'Проект': item.project_contract || item.project_name || '',
        'Тип': enterpriseStatusLabel(item.request_type || 'request'),
        'Отдел': item.target_role || '',
        'Исполнитель': item.assignee_name || '',
        'Приоритет': priorityLabel(item.priority),
        'Дедлайн': item.deadline || '',
        'Статус': enterpriseStatusLabel(item.status),
        'Комментарий': item.comment || '',
    }));
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Заявки');
    XLSX.writeFile(workbook, `korda-requests-selected-${new Date().toISOString().slice(0, 10)}.xlsx`);
    showToast('Заявки', `Выгружено заявок: ${rows.length}`);
}

function enterpriseEscape(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function enterpriseDisplayText(value, fallback = '') {
    const text = String(value || '').trim();
    if (!text) return fallback;
    const direct = {
        approval: 'согласование',
        approvals: 'согласования',
        retry: 'повтор',
        failed: 'ошибка',
        conflict: 'конфликт',
        processing: 'в обработке',
        queued: 'в очереди',
        entity: 'запись',
        finance_payment: 'платёж',
        sales_document: 'документ реализации',
        purchase_order: 'заказ поставщику',
        production_order: 'производственный заказ',
        stock_reservation: 'резерв склада',
        service: 'сервис',
        services: 'сервис',
        resources: 'ресурсы',
        dashboard: 'панель',
    };
    if (direct[text]) return direct[text];
    return text
        .replace(/\bBoardroom heatmap\b/gi, 'Карта проблем')
        .replace(/\bTop bottlenecks\b/gi, 'Главные узкие места')
        .replace(/\bbottlenecks?\b/gi, 'узкие места')
        .replace(/\bapprovals?\b/gi, 'согласования')
        .replace(/\bretry\b/gi, 'повтор')
        .replace(/\bhotspots?\b/gi, 'перегрузки')
        .replace(/\bSLA\b/g, 'сроки сервиса')
        .replace(/\bGap\b/g, 'разрыв')
        .replace(/\bgap\b/g, 'разрыв')
        .replace(/\bSYNC-/g, 'обмен 1С №')
        .replace(/\bINV-/g, 'реализация №')
        .replace(/\bDEMO-/g, 'пример №')
        .replace(/\bDemo\b/g, 'пример')
        .replace(/\bdemo\b/g, 'пример');
}

function getExecutiveHealthState(metrics = {}, integrationMetrics = {}, analyticsMetrics = {}) {
    const riskScore =
        Number(metrics.cash_gap || 0) +
        Number(metrics.cash_overdue_receivables || 0) +
        Number(metrics.production_overdue || 0) * 50000 +
        Number(metrics.inventory_discrepancies || 0) * 25000 +
        Number(metrics.blocked_approvals || 0) * 60000 +
        Number(metrics.service_sla_breached || 0) * 40000 +
        Number(metrics.resource_hotspots || 0) * 35000 +
        Number(integrationMetrics.failed || 0) * 40000 +
        Number(analyticsMetrics.budget_variance_total || 0);
    if (riskScore >= 500000) {
        return {
            tone: 'alert',
            label: 'Требует вмешательства',
            summary: 'Есть набор сигналов, которые уже влияют на деньги, сроки или управляемость процесса.',
        };
    }
    if (riskScore >= 120000) {
        return {
            tone: 'watch',
            label: 'Под контролем, но с рисками',
            summary: 'Компания управляется через систему, но есть несколько мест, где директору лучше вмешаться заранее.',
        };
    }
    return {
        tone: 'ok',
        label: 'Компания под контролем',
        summary: 'Основные процессы идут через ERP-контур, а риски пока не выглядят критичными.',
    };
}

function executiveDecisionAction(targetView, actionLabel) {
    const mapped = ({ resources: 'projects', services: 'services', approvals: 'approvals', finance: 'finance', operations: 'operations' }[targetView] || targetView || 'operations');
    return `<button class="btn-secondary" onclick="navigateTo('${enterpriseEscape(mapped)}')">${enterpriseEscape(actionLabel || 'Открыть')}</button>`;
}

function buildExecutiveDecisionQueue(metrics = {}, integrationMetrics = {}, analyticsDeep = {}, executiveSummary = {}) {
    const items = [];
    const bottlenecks = Array.isArray(executiveSummary?.boardroom_bottlenecks) ? executiveSummary.boardroom_bottlenecks : [];
    bottlenecks.slice(0, 4).forEach(item => {
        items.push({
            title: item.title || 'Узкое место',
            meta: item.meta || 'Нужна управленческая реакция',
            action: executiveDecisionAction(item.target_view, item.action_label),
        });
    });
    if (Number(metrics.cash_gap || 0) > 0) {
        items.push({
            title: 'Кассовый риск',
            meta: `Нужно перераспределить платежи или ускорить входящие деньги. Разрыв: ${formatMoney(metrics.cash_gap || 0)}`,
            action: `<button class="btn-secondary" onclick="navigateTo('finance')">Открыть финансы</button>`,
        });
    }
    if (Number(metrics.production_overdue || 0) > 0) {
        items.push({
            title: 'Производство отстаёт от плана',
            meta: `Просроченных заказов: ${metrics.production_overdue || 0}. Покажи узкие места и маршрутный фокус.`,
            action: `<button class="btn-secondary" onclick="navigateTo('production')">Открыть производство</button>`,
        });
    }
    if (Number(metrics.inventory_discrepancies || 0) > 0) {
        items.push({
            title: 'Складские расхождения',
            meta: `Есть расхождения по складу. Их лучше показать как управляемый процесс, а не как ручную сверку.`,
            action: `<button class="btn-secondary" onclick="navigateTo('nomenclature')">Открыть склад</button>`,
        });
    }
    if (Number(integrationMetrics.failed || 0) > 0 || Number(integrationMetrics.stale_processing || 0) > 0) {
        items.push({
            title: 'Нужно восстановление интеграций',
            meta: `Ошибки: ${integrationMetrics.failed || 0}, зависло: ${integrationMetrics.stale_processing || 0}. Покажи, что операционный центр умеет это поднимать.`,
            action: `<button class="btn-secondary" onclick="navigateTo('operations')">Операционный центр</button>`,
        });
    }
    const breached = Number(analyticsDeep?.sla_summary?.breached_total || 0);
    if (breached > 0) {
        items.push({
            title: 'Нарушены сроки сервиса',
            meta: `Сервис и сопровождение требуют внимания. Нарушено сроков: ${breached}.`,
            action: `<button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('sla', 'breached')">Детализация</button>`,
        });
    }
    if (!items.length) {
        items.push({
            title: 'Система готова к показу',
            meta: 'На экране нет явных красных флагов. Можно вести директора от панели директора к финансам, производству и интеграциям.',
            action: `<button class="btn-secondary" onclick="navigateTo('operations')">Показать операционный центр</button>`,
        });
    }
    return items.slice(0, 6);
}

function toggleRoleSecondarySections(viewId, expanded) {
    document.querySelectorAll(`#${viewId} .secondary-zone`).forEach(section => {
        section.style.display = expanded ? '' : 'none';
    });
}

window.toggleExecutiveSecondary = function() {
    window.__executiveSecondaryExpanded = !window.__executiveSecondaryExpanded;
    toggleRoleSecondarySections('executiveView', !!window.__executiveSecondaryExpanded);
    renderExecutiveRoleWorkbench();
};

window.toggleOperationsSecondary = function() {
    window.__operationsSecondaryExpanded = !window.__operationsSecondaryExpanded;
    toggleRoleSecondarySections('operationsView', !!window.__operationsSecondaryExpanded);
    renderOperationsRoleWorkbench();
};

function renderExecutiveRoleWorkbench() {
    const mount = document.getElementById('executiveRoleWorkbenchMount');
    if (!mount) return;
    const expanded = !!window.__executiveSecondaryExpanded;
    mount.innerHTML = `
        <section class="surface-card surface-card--padded role-workbench role-workbench--compact role-workbench--director">
            <div class="role-workbench-copy">
                <div class="view-eyebrow">Директор</div>
                <h3 class="section-title">Риски, деньги, исполнение</h3>
                <p class="section-subtitle">В ежедневной работе сверху нужны только три управленческих вопроса. Длинный аналитический хвост и вторичные срезы открываются отдельно.</p>
            </div>
            <div class="role-workbench-actions">
                <button class="btn-primary" onclick="window.scrollTo({top:0, behavior:'smooth'})">Риски</button>
                <button class="btn-secondary" onclick="navigateTo('finance')">Деньги</button>
                <button class="btn-secondary" onclick="navigateTo('production')">Исполнение</button>
                <button class="btn-secondary" onclick="toggleExecutiveSecondary()">${expanded ? 'Скрыть аналитику' : 'Показать аналитику'}</button>
            </div>
        </section>
    `;
}

function renderOperationsRoleWorkbench() {
    const mount = document.getElementById('operationsRoleWorkbenchMount');
    if (!mount) return;
    const expanded = !!window.__operationsSecondaryExpanded;
    mount.innerHTML = `
        <section class="surface-card surface-card--padded role-workbench role-workbench--compact role-workbench--director">
            <div class="role-workbench-copy">
                <div class="view-eyebrow">Операционный контур</div>
                <h3 class="section-title">Блокеры, сверка, восстановление</h3>
                <p class="section-subtitle">Сначала то, что реально тормозит операционный день. Большой мониторинг и длинный журнал ниже открываются только по запросу.</p>
            </div>
            <div class="role-workbench-actions">
                <button class="btn-primary" onclick="processExecutiveIntegrationQueue()">Очередь</button>
                <button class="btn-secondary" onclick="runOperationsReconciliation()">Сверка</button>
                <button class="btn-secondary" onclick="runSystemRecoveryAction('release_stale_locks')">Восстановить</button>
                <button class="btn-secondary" onclick="toggleOperationsSecondary()">${expanded ? 'Скрыть мониторинг' : 'Показать мониторинг'}</button>
            </div>
        </section>
    `;
}

function renderExecutiveHeatmapPanel(heatmap = []) {
    if (!heatmap.length) {
        return `
            <div class="boardroom-empty">
                <strong>Карта проблем пока не собрана</strong>
                <span>Когда появятся согласования, просрочки, кассовые риски или сбои интеграций, они попадут сюда.</span>
            </div>
        `;
    }
    return `
        <div class="boardroom-risk-grid">
            ${heatmap.map(item => {
                const critical = Number(item.critical || 0);
                const warning = Number(item.warning || 0);
                const tone = critical > 0 ? 'critical' : warning > 0 ? 'warning' : 'ok';
                return `
                    <div class="boardroom-risk-card boardroom-risk-card--${tone}">
                        <div class="boardroom-risk-card__label">${enterpriseEscape(enterpriseDisplayText(item.label, 'Риск'))}</div>
                        <div class="boardroom-risk-card__counts">
                            <span><strong>${critical.toLocaleString('ru-RU')}</strong> критично</span>
                            <span><strong>${warning.toLocaleString('ru-RU')}</strong> внимание</span>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderExecutiveFocusPanel(priorityProjects = [], topClient = null, topProduct = null) {
    const rows = [
        {
            label: 'Проект под риском',
            value: priorityProjects[0]?.name || priorityProjects[0]?.contract || 'Сейчас нет критичного проекта',
            hint: 'Первое место, куда директору стоит смотреть при утреннем контроле.',
        },
        {
            label: 'Клиент с наибольшей маржей',
            value: topClient?.client_name || 'Данных по марже пока нет',
            hint: 'Клиент, который сильнее всего влияет на прибыльность портфеля.',
        },
        {
            label: 'Ключевая позиция',
            value: topProduct?.item_name || topProduct?.article || 'Данных по позициям пока нет',
            hint: 'Номенклатура или товар, заметный по обороту, марже или риску.',
        },
    ];
    return rows.map((row, index) => `
        <div class="boardroom-focus-row">
            <div class="boardroom-focus-row__num">${String(index + 1).padStart(2, '0')}</div>
            <div class="boardroom-focus-row__body">
                <span>${enterpriseEscape(row.label)}</span>
                <strong>${enterpriseEscape(row.value)}</strong>
                <small>${enterpriseEscape(row.hint)}</small>
            </div>
        </div>
    `).join('');
}

function renderExecutiveBottlenecksPanel(bottlenecks = []) {
    if (!bottlenecks.length) {
        return `
            <div class="boardroom-empty">
                <strong>Узких мест сейчас не видно</strong>
                <span>Система не нашла критичных задержек по срокам, платежам или ответственным.</span>
            </div>
        `;
    }
    return bottlenecks.slice(0, 3).map((item, index) => `
        <div class="boardroom-bottleneck-row">
            <span class="boardroom-bottleneck-row__mark">${String(index + 1).padStart(2, '0')}</span>
            <div>
                <strong>${enterpriseEscape(enterpriseDisplayText(item.title, 'Узкое место'))}</strong>
                <span>${enterpriseEscape(enterpriseDisplayText(item.meta, 'Нужна управленческая реакция'))}</span>
            </div>
        </div>
    `).join('');
}

function renderExecutiveBoardroom() {
    const mount = document.getElementById('executiveBoardroomBrief');
    const decisionMount = document.getElementById('executiveDecisionQueue');
    if (!mount) return;
    const metrics = executiveSummaryDB?.metrics || {};
    const integrationMetrics = integrationMonitoringDB?.metrics || {};
    const analyticsMetrics = executiveAnalyticsDeepDB?.metrics || {};
    const health = getExecutiveHealthState(metrics, integrationMetrics, analyticsMetrics);
    const priorityProjects = (executiveSummaryDB?.risk_projects || []).slice(0, 2);
    const topClient = (executiveAnalyticsDeepDB?.by_client || [])[0];
    const topProduct = (executiveAnalyticsDeepDB?.by_product || [])[0];
    const heatmap = Array.isArray(executiveSummaryDB?.boardroom_heatmap) ? executiveSummaryDB.boardroom_heatmap : [];
    const bottlenecks = Array.isArray(executiveSummaryDB?.boardroom_bottlenecks) ? executiveSummaryDB.boardroom_bottlenecks : [];
    const mismatches = Number(integrationMetrics.failed || 0) + Number(integrationMetrics.retry || 0);
    mount.innerHTML = `
        <section class="surface-card surface-card--padded boardroom-brief-card boardroom-brief-card--${health.tone}">
            <div class="boardroom-brief-top">
                <div>
                    <div class="boardroom-brief-eyebrow">Краткая сводка</div>
                    <h2 class="boardroom-brief-title">${enterpriseEscape(health.label)}</h2>
                    <p class="boardroom-brief-text">${enterpriseEscape(health.summary)}</p>
                </div>
                <div class="boardroom-brief-badge boardroom-brief-badge--${health.tone}">${enterpriseEscape(health.label)}</div>
            </div>
            <div class="boardroom-brief-metrics">
                <div class="boardroom-metric">
                    <div class="boardroom-metric-label">Застрявшие согласования</div>
                    <div class="boardroom-metric-value">${Number(metrics.blocked_approvals || 0).toLocaleString('ru-RU')}</div>
                    <div class="boardroom-metric-meta">красная зона по решениям</div>
                </div>
                <div class="boardroom-metric">
                    <div class="boardroom-metric-label">Деньги под риском</div>
                    <div class="boardroom-metric-value">${formatMoney((metrics.cash_overdue_receivables || 0) + (metrics.expense_pending || 0))}</div>
                    <div class="boardroom-metric-meta">просроченная дебиторка и подвисшие затраты</div>
                </div>
                <div class="boardroom-metric">
                    <div class="boardroom-metric-label">Сервис и ресурсы</div>
                    <div class="boardroom-metric-value">${Number(metrics.service_sla_breached || 0) + Number(metrics.resource_hotspots || 0)}</div>
                    <div class="boardroom-metric-meta">просроченный сервис и перегруженные люди</div>
                </div>
                <div class="boardroom-metric">
                    <div class="boardroom-metric-label">Интеграции</div>
                    <div class="boardroom-metric-value">${Math.max(mismatches, Number(metrics.integration_incidents || 0)).toLocaleString('ru-RU')}</div>
                    <div class="boardroom-metric-meta">ошибки, повторы и конфликты обмена</div>
                </div>
            </div>
            <div class="boardroom-brief-grid boardroom-brief-grid--studio">
                <div class="boardroom-panel boardroom-panel--risk-map">
                    <div class="boardroom-panel-head">
                        <div>
                            <div class="boardroom-panel-title">Карта проблем</div>
                            <div class="boardroom-panel-help">Сводка директорских рисков: где уже критично, а где нужно внимание до того, как появится пожар.</div>
                        </div>
                    </div>
                    ${renderExecutiveHeatmapPanel(heatmap)}
                </div>
                <div class="boardroom-panel boardroom-panel--focus">
                    <div class="boardroom-panel-head">
                        <div>
                            <div class="boardroom-panel-title">Главные акценты</div>
                            <div class="boardroom-panel-help">Три ориентира для быстрого решения: риск, прибыль и ключевая позиция.</div>
                        </div>
                    </div>
                    <div class="boardroom-focus-list">${renderExecutiveFocusPanel(priorityProjects, topClient, topProduct)}</div>
                </div>
                <div class="boardroom-panel boardroom-panel--bottlenecks">
                    <div class="boardroom-panel-head">
                        <div>
                            <div class="boardroom-panel-title">Главные узкие места</div>
                            <div class="boardroom-panel-help">Конкретные задержки и риски, которые мешают деньгам, срокам или исполнению.</div>
                        </div>
                    </div>
                    <div class="boardroom-bottleneck-list">${renderExecutiveBottlenecksPanel(bottlenecks)}</div>
                </div>
            </div>
        </section>
    `;
    if (decisionMount) {
        const items = buildExecutiveDecisionQueue(metrics, integrationMetrics, executiveAnalyticsDeepDB || {}, executiveSummaryDB || {});
        decisionMount.innerHTML = items.map(item => `
            <div class="client360-item boardroom-decision-item">
                <div>
                    <div class="client360-item-title">${enterpriseEscape(enterpriseDisplayText(item.title))}</div>
                    <div class="client360-item-meta">${enterpriseEscape(enterpriseDisplayText(item.meta))}</div>
                </div>
                <div class="view-actions">${item.action}</div>
            </div>
        `).join('');
    }
}

function enterpriseStatusLabel(value) {
    const labels = {
        draft: 'Черновик',
        pending: 'На согласовании',
        approved: 'Согласовано',
        paid: 'Оплачено',
        rejected: 'Отклонено',
        new: 'Новая',
        in_work: 'В работе',
        done: 'Готово',
        cancelled: 'Отменена',
        confirmed: 'Подтверждено',
        overloaded: 'Перегруз',
        released: 'Освобождён',
        open: 'Открыт',
        waiting_client: 'Ждёт клиента',
        closed: 'Закрыт',
        queued: 'В очереди',
        retry: 'Повтор',
        processing: 'Обработка',
        collecting: 'Сбор данных',
        ready: 'Готово к отправке',
        synced: 'Синхронизировано',
        failed: 'Ошибка',
        conflict: 'Конфликт',
        payment: 'Платёж',
        expense: 'Расход',
        service: 'Сервис',
    };
    return labels[value] || value || 'Статус';
}

function enterpriseStatusClass(value) {
    if (['paid', 'done', 'closed', 'approved', 'confirmed', 'released'].includes(value)) return 'status-completed';
    if (['pending', 'in_work', 'open', 'waiting_client', 'overloaded'].includes(value)) return 'status-active';
    if (['rejected', 'cancelled'].includes(value)) return 'status-overdue';
    return 'status-archived';
}

function priorityLabel(value) {
    return { normal: 'Обычный', high: 'Высокий', critical: 'Критичный' }[value] || value || 'Приоритет';
}

function serviceTypeLabel(value) {
    return { warranty: 'Гарантия', claim: 'Рекламация', maintenance: 'Сервисный выезд' }[value] || value || 'Кейс';
}

function enterpriseReportTypeLabel(value) {
    return {
        finance_analytics: 'Финансовая аналитика',
        analytics_deep: 'Глубокая ERP-аналитика',
        dashboard_hub: 'Ролевые панели',
        analytics_drilldown: 'Проваливание в первичку',
        integration_monitoring: 'Мониторинг 1С',
        operations_monitoring: 'Операционный центр',
        reliability_dashboard: 'Надёжность и восстановление',
    }[value] || value || 'Отчёт';
}

function enterpriseDashboardKindLabel(value) {
    return {
        table: 'Табличный режим',
        cockpit: 'Операционный пульт',
        dashboard: 'Панель',
    }[value] || value || 'Режим';
}

function operationsStateLabel(value) {
    return {
        queued: 'в очереди',
        retry: 'повтор',
        processing: 'обработка',
        failed: 'ошибка',
        conflict: 'конфликт',
        stale: 'зависло',
        active: 'активна',
        off: 'выкл',
        answered: 'отвечен',
        missed: 'пропущен',
        inbound: 'входящий',
        outbound: 'исходящий',
    }[value] || value || '—';
}

function databaseBackendLabel(value) {
    return {
        postgres: 'PostgreSQL',
        postgresql: 'PostgreSQL',
        sqlite: 'SQLite',
    }[String(value || '').toLowerCase()] || value || 'база';
}

function databaseIntegrityLabel(value) {
    return {
        ok: 'в норме',
        warning: 'есть замечания',
        error: 'ошибка',
        unknown: 'неизвестно',
    }[String(value || '').toLowerCase()] || value || 'неизвестно';
}

function jobGroupLabel(value) {
    return {
        system: 'система',
        integration: 'интеграции',
        finance: 'финансы',
        production: 'производство',
        email: 'почта',
    }[String(value || '').toLowerCase()] || value || 'система';
}

function jobStatusLabel(value) {
    return {
        running: 'в работе',
        done: 'завершено',
        failed: 'ошибка',
        queued: 'в очереди',
        retry: 'повтор',
        processing: 'обработка',
        active: 'активно',
        stale: 'зависло',
    }[String(value || '').toLowerCase()] || value || 'в работе';
}

function recoveryActionLabel(value) {
    return {
        recovery: 'восстановление',
        release_stale_locks: 'снять зависшие блокировки',
        recover_sync_queue: 'повторить очередь обмена',
    }[String(value || '').toLowerCase()] || value || 'восстановление';
}

function recoveryRunStatusLabel(value) {
    return {
        done: 'выполнено',
        running: 'в работе',
        failed: 'ошибка',
        queued: 'в очереди',
    }[String(value || '').toLowerCase()] || value || 'выполнено';
}

function riskLabel(value) {
    return {
        normal: 'обычный',
        medium: 'средний',
        high: 'высокий',
        critical: 'критичный',
    }[String(value || '').toLowerCase()] || value || 'обычный';
}

function scopeLabel(value) {
    return {
        private: 'личный',
        shared: 'общий',
        public: 'публичный',
    }[String(value || '').toLowerCase()] || value || 'личный';
}

function downloadEnterpriseJson(payload, filePrefix) {
    const blob = new Blob([JSON.stringify(payload || {}, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filePrefix}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function loadEnterpriseData() {
    const [
        expenseSummary,
        expenseRows,
        internalSummary,
        internalRows,
        resourceSummary,
        resourceRows,
        serviceSummary,
        serviceRows,
        executiveSummary,
        budgetRows,
        financePayments,
        erpSummary,
        erpProcesses,
        erpDataQuality,
        integrationQueue,
        integrationMonitoring,
        financeAnalytics,
        analyticsDeep,
        dashboards
    ] = await Promise.all([
        apiCall('/expenses/summary'),
        apiCall('/expenses/requests'),
        apiCall('/internal_requests/summary'),
        apiCall('/internal_requests'),
        apiCall('/resources/summary'),
        apiCall('/resources/allocations'),
        apiCall('/service/summary'),
        apiCall('/service/cases'),
        apiCall('/executive/summary'),
        apiCall('/budget/lines'),
        apiCall('/finance/payments'),
        apiCall('/erp/summary'),
        apiCall('/erp/processes'),
        apiCall('/erp/data_quality'),
        apiCall('/integration/1c/queue?limit=120'),
        apiCall('/integration/1c/monitoring?limit=120'),
        apiCall('/finance/analytics'),
        apiCall('/analytics/deep'),
        apiCall('/analytics/dashboards'),
    ]);
    expenseSummaryDB = expenseSummary && !expenseSummary.error ? expenseSummary : null;
    expenseRequestsDB = Array.isArray(expenseRows) ? expenseRows : [];
    internalSummaryDB = internalSummary && !internalSummary.error ? internalSummary : null;
    internalRequestsDB = Array.isArray(internalRows) ? internalRows : [];
    resourceSummaryDB = resourceSummary && !resourceSummary.error ? resourceSummary : null;
    resourceAllocationsDB = Array.isArray(resourceRows) ? resourceRows : [];
    serviceSummaryDB = serviceSummary && !serviceSummary.error ? serviceSummary : null;
    serviceCasesDB = Array.isArray(serviceRows) ? serviceRows : [];
    executiveSummaryDB = executiveSummary && !executiveSummary.error ? executiveSummary : null;
    budgetLinesDB = Array.isArray(budgetRows) ? budgetRows : [];
    if (Array.isArray(financePayments)) financePaymentsDB = financePayments;
    erpSummaryDB = erpSummary && !erpSummary.error ? erpSummary : null;
    erpProcessesDB = Array.isArray(erpProcesses) ? erpProcesses : [];
    erpDataQualityDB = erpDataQuality && !erpDataQuality.error ? erpDataQuality : (erpSummaryDB?.quality || null);
    integrationQueueDB = Array.isArray(integrationQueue) ? integrationQueue : [];
    integrationMonitoringDB = integrationMonitoring && !integrationMonitoring.error ? integrationMonitoring : null;
    executiveFinanceAnalyticsDB = financeAnalytics && !financeAnalytics.error ? financeAnalytics : null;
    executiveAnalyticsDeepDB = analyticsDeep && !analyticsDeep.error ? analyticsDeep : null;
    executiveDashboardHubDB = dashboards && !dashboards.error ? dashboards : null;
}

window.processExecutiveIntegrationQueue = async function() {
    const res = await apiCall('/integration/1c/process?limit=40', 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось обработать глобальную очередь 1С.');
    await renderExecutive();
    showToast('Система', `Очередь 1С обработана: ${Number(res.success || 0)} успешно, ${Number(res.failed || 0)} с проблемой`);
};

window.recoverExecutiveIntegration = async function(forceFailed = 0) {
    const res = await apiCall(`/integration/1c/recover?force_failed=${forceFailed ? 1 : 0}&stale_only=1`, 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось восстановить очередь 1С.');
    await renderExecutive();
    showToast('Система', `Восстановление выполнено: снято зависших ${Number(res.recovered || 0)}, повторно отправлено ${Number(res.retried_failed || 0)}`);
};

window.exportExecutiveDeepAnalytics = async function() {
    const payload = executiveAnalyticsDeepDB && !executiveAnalyticsDeepDB.error ? executiveAnalyticsDeepDB : await apiCall('/analytics/deep');
    if (!payload || payload.error) return customAlert(payload?.error || 'Не удалось выгрузить управленческую аналитику.');
    downloadEnterpriseJson(payload, 'korda-executive-analytics');
    showToast('Панель директора', 'Аналитика выгружена');
};

function formatEnterpriseDrilldownDate(value) {
    if (!value) return '—';
    if (String(value).match(/^\d+$/)) {
        return new Date(Number(value) * 1000).toLocaleString('ru-RU');
    }
    return value;
}

function renderEnterpriseDrilldown(targetId = 'executiveDrilldownList') {
    const mount = document.getElementById(targetId);
    if (!mount) return;
    const payload = executiveDrilldownDB;
    if (!payload || payload.error) {
        mount.innerHTML = '<div class="empty-state">Выбери метрику или карточку выше, чтобы провалиться в первичку.</div>';
        return;
    }
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    const summaryEntries = Object.entries(payload.summary || {});
    mount.innerHTML = `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${enterpriseEscape(payload.label || payload.dimension || 'Детализация')}</div>
                <div class="client360-item-meta">${enterpriseEscape(payload.dimension || 'срез')} · строк ${rows.length}</div>
            </div>
            <div class="client360-item-side">${summaryEntries.length ? enterpriseEscape(summaryEntries.map(([key, val]) => `${key}: ${val}`).join(' · ')) : 'детали'}</div>
        </div>
        ${rows.length ? rows.map(item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${enterpriseEscape(item.title || item.entity_type || 'Запись')}</div>
                    <div class="client360-item-meta">${enterpriseEscape(item.meta || 'Без деталей')}</div>
                    <div class="client360-item-meta">${enterpriseEscape(formatEnterpriseDrilldownDate(item.date || ''))}</div>
                </div>
                <div class="view-actions">
                    <span class="client360-item-side">${typeof item.amount === 'number' && item.amount ? formatMoney(item.amount || 0) : enterpriseEscape(item.status || 'view')}</span>
                    ${item.navigate_to ? `<button class="btn-secondary" onclick="navigateTo('${enterpriseEscape(item.navigate_to)}')">Открыть</button>` : ''}
                </div>
            </div>
        `).join('') : '<div class="empty-state">Для этой метрики первичка пока не нашлась.</div>'}
    `;
}

window.openExecutiveAnalyticsDrilldown = async function(dimension, label = '', valueId = 0, value = '') {
    const params = new URLSearchParams();
    params.set('dimension', dimension || '');
    if (label) params.set('value', label);
    if (value) params.set('value', value);
    if (Number(valueId || 0)) params.set('value_id', String(Number(valueId)));
    params.set('limit', '40');
    const payload = await apiCall(`/analytics/drilldown?${params.toString()}`);
    if (!payload || payload.error) return customAlert(payload?.error || 'Не удалось открыть детализацию.');
    executiveDrilldownDB = payload;
    renderEnterpriseDrilldown();
    showToast('Аналитика', `Открыта детализация: ${label || value || dimension}`);
};

function populateEnterpriseSelects() {
    const projectOptions = `<option value="0">Без проекта</option>${projectsDB.map(project => `<option value="${project.id}">${project.contract || 'Без договора'} · ${project.name}</option>`).join('')}`;
    const clientOptions = `<option value="0">Без контрагента</option>${clientsDB.map(client => `<option value="${client.id}">${client.name}</option>`).join('')}`;
    ['expenseProjectId', 'internalProjectId', 'resourceProjectId', 'serviceProjectId', 'erpProcessProjectId'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = projectOptions;
    });
    ['expenseClientId', 'serviceClientId', 'erpProcessClientId'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = clientOptions;
    });
    const linkedPayment = document.getElementById('expenseLinkedPayment');
    if (linkedPayment) {
        linkedPayment.innerHTML = `<option value="0">Без связанной оплаты</option>${financePaymentsDB.map(item => `<option value="${item.id}">${item.title} · ${formatMoney(item.amount, item.currency)}</option>`).join('')}`;
    }
}

function resetExpenseForm() {
    editingExpenseId = 0;
    [['expenseProjectId', '0'], ['expenseClientId', '0'], ['expenseTitle', ''], ['expenseType', 'payment'], ['expenseAmount', ''], ['expenseDueDate', ''], ['expenseCurrency', 'RUB'], ['expenseApproverRole', 'Директор'], ['expenseApproverName', ''], ['expenseLinkedPayment', '0'], ['expenseStatus', 'draft'], ['expenseComment', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) {
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    });
    const title = document.getElementById('expenseFormTitle');
    const saveButton = document.getElementById('expenseSaveButton');
    const cancelButton = document.getElementById('expenseCancelEditButton');
    if (title) title.textContent = 'Новый запрос';
    if (saveButton) saveButton.textContent = 'Создать запрос';
    if (cancelButton) cancelButton.hidden = true;
}

function activateExpenseWorkspaceTab(title) {
    const view = document.getElementById('expensesView');
    if (!view) return false;
    const tab = Array.from(view.querySelectorAll('.crm-workspace__tab')).find(button =>
        String(button.textContent || '').trim() === title
    );
    if (!tab) return false;
    tab.click();
    return true;
}

function showExpenseForm() {
    if (activateExpenseWorkspaceTab('Новый запрос')) return;
    const form = document.querySelector('#expensesView .ops-form-card');
    const registry = document.querySelector('#expensesView .ops-list-card');
    if (form) form.hidden = false;
    if (registry) registry.hidden = true;
}

function showExpenseRegistry() {
    if (activateExpenseWorkspaceTab('Реестр согласований')) return;
    const form = document.querySelector('#expensesView .ops-form-card');
    const registry = document.querySelector('#expensesView .ops-list-card');
    if (form) form.hidden = true;
    if (registry) registry.hidden = false;
}

function editExpenseRequest(id) {
    const item = expenseRequestsDB.find(row => row.id === id);
    if (!item) return;
    editingExpenseId = id;
    document.getElementById('expenseProjectId').value = String(item.project_id || 0);
    document.getElementById('expenseClientId').value = String(item.client_id || 0);
    document.getElementById('expenseTitle').value = item.title || '';
    document.getElementById('expenseType').value = item.request_type || 'payment';
    document.getElementById('expenseAmount').value = item.amount || '';
    document.getElementById('expenseDueDate').value = item.due_date || '';
    document.getElementById('expenseCurrency').value = item.currency || 'RUB';
    document.getElementById('expenseApproverRole').value = item.approver_role || 'Директор';
    document.getElementById('expenseApproverName').value = item.approver_name || '';
    document.getElementById('expenseLinkedPayment').value = String(item.linked_payment_id || 0);
    document.getElementById('expenseStatus').value = item.status || 'draft';
    document.getElementById('expenseComment').value = item.comment || '';
    const title = document.getElementById('expenseFormTitle');
    const saveButton = document.getElementById('expenseSaveButton');
    const cancelButton = document.getElementById('expenseCancelEditButton');
    if (title) title.textContent = 'Редактирование запроса';
    if (saveButton) saveButton.textContent = 'Сохранить изменения';
    if (cancelButton) cancelButton.hidden = false;
    showExpenseForm();
    document.querySelector('#expensesView .ops-form-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function saveExpenseRequest() {
    const targetId = Number(editingExpenseId || 0);
    const payload = {
        project_id: Number(document.getElementById('expenseProjectId').value || 0),
        client_id: Number(document.getElementById('expenseClientId').value || 0),
        title: document.getElementById('expenseTitle').value.trim(),
        request_type: document.getElementById('expenseType').value,
        amount: Number((document.getElementById('expenseAmount').value || '').replace(',', '.')) || 0,
        currency: document.getElementById('expenseCurrency').value,
        approver_role: document.getElementById('expenseApproverRole').value,
        approver_name: document.getElementById('expenseApproverName').value.trim(),
        due_date: document.getElementById('expenseDueDate').value.trim(),
        linked_payment_id: Number(document.getElementById('expenseLinkedPayment').value || 0),
        status: document.getElementById('expenseStatus').value,
        comment: document.getElementById('expenseComment').value.trim(),
    };
    if (!payload.title || !payload.amount) return customAlert('Заполни название запроса и сумму.');
    const endpoint = editingExpenseId ? `/expenses/requests/${editingExpenseId}` : '/expenses/requests';
    const method = editingExpenseId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить запрос на затраты.');
    selectedExpenseId = Number(res.id || targetId || 0);
    resetExpenseForm();
    await renderExpenses();
    showExpenseRegistry();
    requestAnimationFrame(() => {
        showExpenseRegistry();
        document.getElementById('expenseRequestDetailCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Затраты', 'Запрос сохранён');
}

async function deleteExpenseRequest(id) {
    const item = expenseRequestsDB.find(row => Number(row.id) === Number(id));
    if (!canDeleteExpenseRequest(item)) return customAlert('Удалить запрос может только его автор или директор.');
    if (!(await customConfirm('Удалить запрос на затраты и связанную оплату?'))) return;
    const res = await apiCall(`/expenses/requests/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.message || (res?.error === 'forbidden' ? 'Удалить запрос может только его автор или директор.' : 'Не удалось удалить запрос на затраты.'));
    if (editingExpenseId === id) resetExpenseForm();
    if (Number(selectedExpenseId) === Number(id)) selectedExpenseId = 0;
    await renderExpenses();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Затраты', 'Запрос удалён');
}

function resetInternalRequestForm() {
    editingInternalId = 0;
    [['internalProjectId', '0'], ['internalTitle', ''], ['internalType', 'purchase'], ['internalTargetRole', 'Склад'], ['internalAssigneeName', ''], ['internalDeadline', ''], ['internalPriority', 'normal'], ['internalStatus', 'new'], ['internalComment', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    const formTitle = document.getElementById('internalFormTitle');
    const saveButton = document.getElementById('internalSaveButton');
    const cancelButton = document.getElementById('internalCancelEditButton');
    const statusField = document.getElementById('internalStatusField');
    if (formTitle) formTitle.textContent = 'Новая заявка';
    if (saveButton) saveButton.textContent = 'Отправить заявку';
    if (cancelButton) cancelButton.hidden = true;
    if (statusField) statusField.hidden = true;
}

function setInternalRequestPreset(requestType, title, targetRole) {
    const type = document.getElementById('internalType');
    const titleInput = document.getElementById('internalTitle');
    const role = document.getElementById('internalTargetRole');
    if (type) type.value = requestType || 'other';
    if (titleInput) titleInput.value = title || '';
    if (role) role.value = targetRole || 'Менеджер';
    document.getElementById('internalComment')?.focus();
}

function activateInternalRequestWorkspaceTab(title) {
    const view = document.getElementById('requestsView');
    if (!view) return false;
    const tab = Array.from(view.querySelectorAll('.crm-workspace__tab')).find(button =>
        String(button.textContent || '').trim() === title
    );
    if (!tab) return false;
    tab.click();
    return true;
}

function showInternalRequestForm() {
    const formTab = document.getElementById('internalRequestFormTab');
    const registryTab = document.getElementById('internalRequestRegistryTab');
    if (formTab) {
        formTab.classList.add('is-active');
        formTab.setAttribute('aria-selected', 'true');
    }
    if (registryTab) {
        registryTab.classList.remove('is-active');
        registryTab.setAttribute('aria-selected', 'false');
    }
    if (activateInternalRequestWorkspaceTab('Новая заявка')) return;
    const form = document.getElementById('internalRequestFormCard');
    const registry = document.querySelector('#requestsView .internal-request-list-card');
    if (form) form.hidden = false;
    if (registry) registry.hidden = true;
}

function showInternalRequestRegistry() {
    const formTab = document.getElementById('internalRequestFormTab');
    const registryTab = document.getElementById('internalRequestRegistryTab');
    if (formTab) {
        formTab.classList.remove('is-active');
        formTab.setAttribute('aria-selected', 'false');
    }
    if (registryTab) {
        registryTab.classList.add('is-active');
        registryTab.setAttribute('aria-selected', 'true');
    }
    if (activateInternalRequestWorkspaceTab('Реестр заявок')) return;
    const form = document.getElementById('internalRequestFormCard');
    const registry = document.querySelector('#requestsView .internal-request-list-card');
    if (form) form.hidden = true;
    if (registry) registry.hidden = false;
}

function editInternalRequest(id) {
    const item = internalRequestsDB.find(row => row.id === id);
    if (!item) return;
    editingInternalId = id;
    document.getElementById('internalProjectId').value = String(item.project_id || 0);
    document.getElementById('internalTitle').value = item.title || '';
    document.getElementById('internalType').value = item.request_type || 'purchase';
    document.getElementById('internalTargetRole').value = item.target_role || 'Менеджер';
    document.getElementById('internalAssigneeName').value = item.assignee_name || '';
    document.getElementById('internalDeadline').value = item.deadline || '';
    document.getElementById('internalDeadline').dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('internalPriority').value = item.priority || 'normal';
    document.getElementById('internalStatus').value = item.status || 'new';
    document.getElementById('internalComment').value = item.comment || '';
    const formTitle = document.getElementById('internalFormTitle');
    const saveButton = document.getElementById('internalSaveButton');
    const cancelButton = document.getElementById('internalCancelEditButton');
    const statusField = document.getElementById('internalStatusField');
    if (formTitle) formTitle.textContent = 'Редактирование заявки';
    if (saveButton) saveButton.textContent = 'Сохранить изменения';
    if (cancelButton) cancelButton.hidden = false;
    if (statusField) statusField.hidden = false;
    showInternalRequestForm();
    document.getElementById('internalRequestFormCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function saveInternalRequest() {
    const targetId = Number(editingInternalId || 0);
    const payload = {
        project_id: Number(document.getElementById('internalProjectId').value || 0),
        title: document.getElementById('internalTitle').value.trim(),
        request_type: document.getElementById('internalType').value,
        target_role: document.getElementById('internalTargetRole').value,
        assignee_name: document.getElementById('internalAssigneeName').value.trim(),
        deadline: document.getElementById('internalDeadline').value.trim(),
        priority: document.getElementById('internalPriority').value,
        status: document.getElementById('internalStatus').value,
        comment: document.getElementById('internalComment').value.trim(),
    };
    if (!payload.title) return customAlert('Укажите, что нужно сделать.');
    if (!payload.target_role) return customAlert('Выберите отдел, которому отправляется заявка.');
    if (!payload.deadline) return customAlert('Укажите срок выполнения.');
    if (!payload.comment) return customAlert('Опишите ожидаемый результат.');
    const endpoint = editingInternalId ? `/internal_requests/${editingInternalId}` : '/internal_requests';
    const method = editingInternalId ? 'PUT' : 'POST';
    const wasEditing = Boolean(editingInternalId);
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить внутреннюю заявку.');
    selectedInternalRequestId = Number(res.id || targetId || 0);
    resetInternalRequestForm();
    await renderInternalRequests();
    showInternalRequestRegistry();
    requestAnimationFrame(() => {
        showInternalRequestRegistry();
        document.getElementById('internalRequestDetailCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Внутренние заявки', wasEditing ? 'Изменения сохранены' : 'Заявка отправлена выбранному отделу');
}

async function setInternalRequestStatus(id, status) {
    const item = internalRequestsDB.find(row => Number(row.id) === Number(id));
    if (!item || !hasCurrentPermission('requests', 'update')) return;
    const payload = {
        project_id: Number(item.project_id || 0),
        contract_id: Number(item.contract_id || 0),
        object_id: Number(item.object_id || 0),
        title: item.title || '',
        request_type: item.request_type || 'other',
        target_role: item.target_role || '',
        assignee_name: item.assignee_name || '',
        deadline: item.deadline || '',
        priority: item.priority || 'normal',
        status,
        comment: item.comment || '',
    };
    const res = await apiCall(`/internal_requests/${id}`, 'PUT', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось изменить статус заявки.');
    item.status = status;
    renderInternalRequestMetrics();
    renderInternalRequestList();
    renderInternalRequestDetailCard();
    showToast('Внутренние заявки', status === 'done' ? 'Заявка отмечена выполненной' : 'Заявка взята в работу');
}

async function deleteInternalRequest(id) {
    const item = internalRequestsDB.find(row => Number(row.id) === Number(id));
    if (!canDeleteInternalRequest(item)) return customAlert('Удалить заявку может только её автор или директор.');
    if (!(await customConfirm('Удалить внутреннюю заявку безвозвратно?'))) return;
    const res = await apiCall(`/internal_requests/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.message || (res?.error === 'forbidden' ? 'Удалить заявку может только её автор или директор.' : 'Не удалось удалить внутреннюю заявку.'));
    if (editingInternalId === id) resetInternalRequestForm();
    if (Number(selectedInternalRequestId) === Number(id)) selectedInternalRequestId = 0;
    internalRequestsDB = internalRequestsDB.filter(row => Number(row.id) !== Number(id));
    renderInternalRequestMetrics();
    renderInternalRequestList();
    renderInternalRequestDetailCard();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Заявки', 'Внутренняя заявка удалена');
}

function enterpriseProcessStageLabel(value) {
    return {
        request: 'Заявка',
        approval: 'Согласование',
        reserve: 'Резерв',
        purchase: 'Закупка',
        production: 'Производство',
        shipment: 'Отгрузка',
        payment: 'Оплата',
        done: 'Закрыто',
    }[value] || value || 'Этап';
}

function resetERPProcessForm() {
    [['erpProcessProjectId', '0'], ['erpProcessClientId', '0'], ['erpProcessTitle', ''], ['erpProcessType', 'purchase'], ['erpProcessAmount', ''], ['erpProcessDeadline', ''], ['erpProcessAssignee', ''], ['erpProcessApprover', ''], ['erpProcessItemArticle', ''], ['erpProcessItemName', ''], ['erpProcessQty', ''], ['erpProcessSupplier', ''], ['erpProcessComment', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    ['erpScenarioApproval', 'erpScenarioPurchase', 'erpScenarioShipment', 'erpScenarioPayment'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = true;
    });
    ['erpScenarioReserve', 'erpScenarioProduction'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
    });
}

function getERPScenario() {
    const scenario = ['request'];
    [['erpScenarioApproval', 'approval'], ['erpScenarioReserve', 'reserve'], ['erpScenarioPurchase', 'purchase'], ['erpScenarioProduction', 'production'], ['erpScenarioShipment', 'shipment'], ['erpScenarioPayment', 'payment']].forEach(([id, stage]) => {
        const el = document.getElementById(id);
        if (el && el.checked) scenario.push(stage);
    });
    return [...new Set(scenario)];
}

async function saveERPProcess() {
    const payload = {
        project_id: Number(document.getElementById('erpProcessProjectId')?.value || 0),
        client_id: Number(document.getElementById('erpProcessClientId')?.value || 0),
        title: document.getElementById('erpProcessTitle')?.value.trim() || '',
        request_type: document.getElementById('erpProcessType')?.value || 'purchase',
        scenario: getERPScenario(),
        due_date: document.getElementById('erpProcessDeadline')?.value.trim() || '',
        amount: Number((document.getElementById('erpProcessAmount')?.value || '').replace(',', '.')) || 0,
        assignee_name: document.getElementById('erpProcessAssignee')?.value.trim() || '',
        approver_name: document.getElementById('erpProcessApprover')?.value.trim() || '',
        target_role: document.getElementById('erpProcessType')?.value === 'production' ? 'Производство и ОТК' : 'Менеджер',
        item_article: document.getElementById('erpProcessItemArticle')?.value.trim() || '',
        item_name: document.getElementById('erpProcessItemName')?.value.trim() || '',
        qty: Number((document.getElementById('erpProcessQty')?.value || '').replace(',', '.')) || 0,
        supplier: document.getElementById('erpProcessSupplier')?.value.trim() || '',
        comment: document.getElementById('erpProcessComment')?.value.trim() || '',
    };
    if (!payload.title) return customAlert('Заполни название ERP-процесса.');
    const res = await apiCall('/erp/processes/start', 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось запустить ERP-процесс.');
    resetERPProcessForm();
    await renderInternalRequests();
    if (typeof renderExecutiveDashboard === 'function' && document.getElementById('executiveView')?.style.display === 'block') {
        await renderExecutiveDashboard();
    }
    showToast('Система', 'Сквозной процесс запущен');
}

async function advanceERPProcess(processId, stage) {
    const res = await apiCall(`/erp/processes/${processId}/advance`, 'POST', { target_stage: stage });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось перевести процесс на следующий этап.');
    await renderInternalRequests();
    if (typeof renderExecutiveDashboard === 'function' && document.getElementById('executiveView')?.style.display === 'block') {
        await renderExecutiveDashboard();
    }
    showToast('Система', `Этап «${enterpriseProcessStageLabel(stage)}» выполнен`);
}

async function exportERPProcessSnapshot() {
    const snapshot = await apiCall('/erp/export');
    if (!snapshot || snapshot.error) return customAlert(snapshot?.error || 'Не удалось выгрузить ERP-слепок.');
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `korda-erp-export-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast('Система', 'Экспорт готов');
}

function renderERPWidgets() {
    const metricsGrid = document.getElementById('erpSummaryMetricsGrid');
    const stageBreakdown = document.getElementById('erpStageBreakdown');
    const qualityList = document.getElementById('erpDataQualityList');
    const processesList = document.getElementById('erpProcessesList');
    const summary = erpSummaryDB;
    if (metricsGrid) {
        const metrics = summary?.metrics || {};
        metricsGrid.innerHTML = `
            <div class="metric-card"><div class="metric-title">Процессов</div><div class="metric-value">${metrics.processes_total || 0}</div></div>
            <div class="metric-card warning"><div class="metric-title">Застряло в согласовании</div><div class="metric-value">${metrics.blocked_approvals || 0}</div></div>
            <div class="metric-card"><div class="metric-title">Открытые деньги</div><div class="metric-value">${formatMoney(metrics.open_money || 0)}</div></div>
            <div class="metric-card danger"><div class="metric-title">Проблемы данных</div><div class="metric-value">${metrics.data_issues || 0}</div></div>
        `;
    }
    if (stageBreakdown) {
        const stageCounts = summary?.stage_counts || {};
        const entries = Object.entries(stageCounts);
        stageBreakdown.innerHTML = entries.length ? entries.map(([stage, count]) => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${enterpriseProcessStageLabel(stage)}</div>
                    <div class="client360-item-meta">Текущая загрузка по этапу</div>
                </div>
                <div class="client360-item-side">${count}</div>
            </div>
        `).join('') : '<div class="empty-state">ERP-процессов пока нет.</div>';
    }
    if (qualityList) {
        const quality = erpDataQualityDB || summary?.quality || {};
        const orphanCount = Object.values(quality.orphans || {}).reduce((sum, value) => sum + Number(value || 0), 0);
        const duplicateClients = (quality.clients_duplicates || []).length + (quality.clients_duplicate_inn || []).length;
        const duplicateNsi = (quality.nomenclature_duplicates || []).length;
        qualityList.innerHTML = `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Дубли клиентов</div>
                    <div class="client360-item-meta">Нужно объединить карточки и выбрать одну главную запись</div>
                </div>
                <div class="client360-item-side">${duplicateClients}</div>
            </div>
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Дубли номенклатуры</div>
                    <div class="client360-item-meta">Артикулы должны быть уникальным источником правды</div>
                </div>
                <div class="client360-item-side">${duplicateNsi}</div>
            </div>
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Осиротевшие связи</div>
                    <div class="client360-item-meta">Платежи, продажи или заявки без корректного проекта/клиента</div>
                </div>
                <div class="client360-item-side">${orphanCount}</div>
            </div>
        `;
    }
    if (processesList) {
        processesList.innerHTML = erpProcessesDB.length ? erpProcessesDB.slice(0, 20).map(item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title}</div>
                    <div class="client360-item-meta">${item.project_contract || item.project_name || 'Без проекта'} · ${item.client_name || 'Без контрагента'} · ${enterpriseProcessStageLabel(item.current_stage)}</div>
                    <div class="client360-item-meta">${item.due_date || 'без срока'} · ${formatMoney(item.amount || 0, item.currency)}</div>
                </div>
                <div class="view-actions">
                    <span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseStatusLabel(item.status)}</span>
                    ${item.current_stage !== 'approval' ? `<button class="btn-secondary" onclick="advanceERPProcess(${item.id}, 'approval')">Согласовать</button>` : ''}
                    ${item.current_stage !== 'reserve' ? `<button class="btn-secondary" onclick="advanceERPProcess(${item.id}, 'reserve')">Резерв</button>` : ''}
                    ${item.current_stage !== 'purchase' ? `<button class="btn-secondary" onclick="advanceERPProcess(${item.id}, 'purchase')">Закупка</button>` : ''}
                    ${item.current_stage !== 'production' ? `<button class="btn-secondary" onclick="advanceERPProcess(${item.id}, 'production')">Производство</button>` : ''}
                    ${item.current_stage !== 'shipment' ? `<button class="btn-secondary" onclick="advanceERPProcess(${item.id}, 'shipment')">Отгрузка</button>` : ''}
                    ${item.current_stage !== 'payment' ? `<button class="btn-secondary" onclick="advanceERPProcess(${item.id}, 'payment')">Оплата</button>` : ''}
                    ${item.current_stage !== 'done' ? `<button class="btn-primary" onclick="advanceERPProcess(${item.id}, 'done')">Закрыть</button>` : ''}
                </div>
            </div>
        `).join('') : '<div class="empty-state">ERP-процессов пока нет.</div>';
    }
}

function resetResourceForm() {
    editingResourceId = 0;
    [['resourceProjectId', '0'], ['resourceDepartment', 'Менеджер'], ['resourceName', ''], ['resourceRoleName', ''], ['resourceCrewName', ''], ['resourceCrewType', ''], ['resourceLoadPercent', ''], ['resourceDateFrom', ''], ['resourceDateTo', ''], ['resourceLocation', ''], ['resourceStatus', 'planned'], ['resourceComment', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    syncResourceEditorState();
}

function syncResourceEditorState() {
    const editor = document.getElementById('resourceEditorCard');
    const title = document.getElementById('resourceEditorTitle');
    const saveButton = document.getElementById('resourceSaveButton');
    const canCreate = hasCurrentPermission('resources', 'create');
    const canUpdate = hasCurrentPermission('resources', 'update');
    if (editor) editor.hidden = !(canCreate || canUpdate);
    if (title) title.textContent = editingResourceId ? 'Редактирование загрузки' : 'Новая загрузка ресурса';
    if (saveButton) {
        saveButton.hidden = editingResourceId ? !canUpdate : !canCreate;
        saveButton.textContent = editingResourceId ? 'Сохранить изменения' : 'Добавить в календарь';
    }
}

function editResourceAllocation(id) {
    if (!hasCurrentPermission('resources', 'update')) return customAlert('У вашей роли нет права редактировать календарь ресурсов.');
    const item = resourceAllocationsDB.find(row => row.id === id);
    if (!item) return;
    editingResourceId = id;
    document.getElementById('resourceProjectId').value = String(item.project_id || 0);
    document.getElementById('resourceDepartment').value = item.department || 'Менеджер';
    document.getElementById('resourceName').value = item.resource_name || '';
    document.getElementById('resourceRoleName').value = item.role_name || '';
    document.getElementById('resourceCrewName').value = item.crew_name || '';
    document.getElementById('resourceCrewType').value = item.crew_type || '';
    document.getElementById('resourceLoadPercent').value = item.load_percent || 0;
    document.getElementById('resourceDateFrom').value = item.date_from || '';
    document.getElementById('resourceDateTo').value = item.date_to || '';
    document.getElementById('resourceLocation').value = item.location || '';
    document.getElementById('resourceStatus').value = item.status || 'planned';
    document.getElementById('resourceComment').value = item.comment || '';
    syncResourceEditorState();
    document.getElementById('resourceEditorCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function saveResourceAllocation() {
    if (!editingResourceId && !hasCurrentPermission('resources', 'create')) return customAlert('У вашей роли нет права добавлять загрузку в календарь.');
    if (editingResourceId && !hasCurrentPermission('resources', 'update')) return customAlert('У вашей роли нет права редактировать календарь ресурсов.');
    const payload = {
        project_id: Number(document.getElementById('resourceProjectId').value || 0),
        department: document.getElementById('resourceDepartment').value,
        resource_name: document.getElementById('resourceName').value.trim(),
        role_name: document.getElementById('resourceRoleName').value.trim(),
        crew_name: document.getElementById('resourceCrewName').value.trim(),
        crew_type: document.getElementById('resourceCrewType').value,
        load_percent: Number(document.getElementById('resourceLoadPercent').value || 0) || 0,
        date_from: document.getElementById('resourceDateFrom').value.trim(),
        date_to: document.getElementById('resourceDateTo').value.trim(),
        location: document.getElementById('resourceLocation').value.trim(),
        status: document.getElementById('resourceStatus').value,
        comment: document.getElementById('resourceComment').value.trim(),
    };
    if (!payload.resource_name || !payload.load_percent) return customAlert('Заполни ресурс и процент загрузки.');
    const endpoint = editingResourceId ? `/resources/allocations/${editingResourceId}` : '/resources/allocations';
    const method = editingResourceId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.error === 'forbidden' ? 'Недостаточно прав для изменения календаря ресурсов. Обновите страницу и попробуйте ещё раз.' : (res?.error || 'Не удалось сохранить загрузку ресурса.'));
    resetResourceForm();
    await renderResources();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Ресурсы', 'Загрузка сохранена');
}

async function deleteResourceAllocation(id) {
    if (!hasCurrentPermission('resources', 'delete')) return customAlert('Удаление записей календаря доступно только сотрудникам с соответствующими правами.');
    if (!(await customConfirm('Удалить размещение ресурса безвозвратно?'))) return;
    const res = await apiCall(`/resources/allocations/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.error === 'forbidden' ? 'У вашей роли нет права удалять записи календаря.' : (res?.error || 'Не удалось удалить размещение ресурса.'));
    if (editingResourceId === id) resetResourceForm();
    await renderResources();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Ресурсы', 'Размещение удалено');
}

function resetServiceForm() {
    editingServiceId = 0;
    [['serviceProjectId', '0'], ['serviceClientId', '0'], ['serviceCaseNumber', ''], ['serviceTitle', ''], ['serviceCaseType', 'warranty'], ['serviceStatus', 'open'], ['servicePriority', 'normal'], ['serviceWarrantyUntil', ''], ['serviceSlaDeadline', ''], ['serviceResponsible', ''], ['serviceDefect', ''], ['serviceResolution', '']].forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    syncServiceEditorState();
}

function syncServiceEditorState() {
    const editor = document.getElementById('serviceEditorCard');
    const title = document.getElementById('serviceEditorTitle');
    const saveButton = document.getElementById('serviceSaveButton');
    const canCreate = hasCurrentPermission('service', 'create');
    const canUpdate = hasCurrentPermission('service', 'update');
    if (editor) editor.hidden = !(canCreate || canUpdate);
    if (title) title.textContent = editingServiceId ? 'Редактирование обращения' : 'Новое сервисное обращение';
    if (saveButton) {
        saveButton.hidden = editingServiceId ? !canUpdate : !canCreate;
        saveButton.textContent = editingServiceId ? 'Сохранить изменения' : 'Создать обращение';
    }
}

function editServiceCase(id) {
    if (!hasCurrentPermission('service', 'update')) return customAlert('У вашей роли нет права редактировать сервисные обращения.');
    const item = serviceCasesDB.find(row => row.id === id);
    if (!item) return;
    editingServiceId = id;
    document.getElementById('serviceProjectId').value = String(item.project_id || 0);
    document.getElementById('serviceClientId').value = String(item.client_id || 0);
    document.getElementById('serviceCaseNumber').value = item.case_number || '';
    document.getElementById('serviceTitle').value = item.title || '';
    document.getElementById('serviceCaseType').value = item.case_type || 'warranty';
    document.getElementById('serviceStatus').value = item.status || 'open';
    document.getElementById('servicePriority').value = item.priority || 'normal';
    document.getElementById('serviceWarrantyUntil').value = item.warranty_until || '';
    document.getElementById('serviceSlaDeadline').value = item.sla_deadline || '';
    document.getElementById('serviceResponsible').value = item.responsible || '';
    document.getElementById('serviceDefect').value = item.defect || '';
    document.getElementById('serviceResolution').value = item.resolution || '';
    syncServiceEditorState();
    document.getElementById('serviceEditorCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function saveServiceCase() {
    if (!editingServiceId && !hasCurrentPermission('service', 'create')) return customAlert('У вашей роли нет права создавать сервисные обращения.');
    if (editingServiceId && !hasCurrentPermission('service', 'update')) return customAlert('У вашей роли нет права редактировать сервисные обращения.');
    const payload = {
        project_id: Number(document.getElementById('serviceProjectId').value || 0),
        client_id: Number(document.getElementById('serviceClientId').value || 0),
        case_number: document.getElementById('serviceCaseNumber').value.trim(),
        title: document.getElementById('serviceTitle').value.trim(),
        case_type: document.getElementById('serviceCaseType').value,
        status: document.getElementById('serviceStatus').value,
        priority: document.getElementById('servicePriority').value,
        defect: document.getElementById('serviceDefect').value.trim(),
        warranty_until: document.getElementById('serviceWarrantyUntil').value.trim(),
        sla_deadline: document.getElementById('serviceSlaDeadline').value.trim(),
        responsible: document.getElementById('serviceResponsible').value.trim(),
        resolution: document.getElementById('serviceResolution').value.trim(),
    };
    if (!payload.title) return customAlert('Заполни название сервисного кейса.');
    const endpoint = editingServiceId ? `/service/cases/${editingServiceId}` : '/service/cases';
    const method = editingServiceId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.error === 'forbidden' ? 'Недостаточно прав для этого действия. Обновите страницу и повторите попытку.' : (res?.error || 'Не удалось сохранить сервисное обращение.'));
    resetServiceForm();
    await renderServiceCases();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Сервис', 'Сервисный кейс сохранён');
}

async function deleteServiceCase(id) {
    if (!hasCurrentPermission('service', 'delete')) return customAlert('Удаление сервисных обращений доступно только сотрудникам с соответствующими правами.');
    if (!(await customConfirm('Удалить сервисный кейс безвозвратно?'))) return;
    const res = await apiCall(`/service/cases/${id}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.error === 'forbidden' ? 'У вашей роли нет права удалять сервисные обращения.' : (res?.error || 'Не удалось удалить сервисный кейс.'));
    if (editingServiceId === id) resetServiceForm();
    await renderServiceCases();
    if (currentProjectId && typeof renderProjectOpsSummary === 'function') renderProjectOpsSummary();
    showToast('Сервис', 'Сервисный кейс удалён');
}

function expenseRequestTypeLabel(value) {
    return {
        payment: 'Оплата поставщику',
        expense: 'Внутренний расход',
        advance: 'Аванс',
        budget_shift: 'Сдвиг бюджета',
    }[value] || 'Расход';
}

function canDeleteExpenseRequest(item) {
    if (!item || !currentUser) return false;
    if (String(currentUser.role || '').trim() === 'Директор') return true;
    const actorEmail = String(currentUser.email || '').trim().toLowerCase();
    const authorEmail = String(item.created_by || '').trim().toLowerCase();
    return !!actorEmail && actorEmail === authorEmail;
}

function openExpenseRequestCard(id) {
    selectedExpenseId = Number(id || 0);
    renderExpenseRequestCard();
    showExpenseRegistry();
    document.getElementById('expenseRequestDetailCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function expenseCardValue(value, fallback = 'Не указано') {
    const text = String(value ?? '').trim();
    return enterpriseEscape(text || fallback);
}

function renderExpenseRequestCard() {
    const card = document.getElementById('expenseRequestDetailCard');
    const body = document.getElementById('expenseRequestDetailBody');
    if (!card || !body) return;
    const item = expenseRequestsDB.find(row => Number(row.id) === Number(selectedExpenseId));
    if (!item) {
        card.hidden = true;
        body.innerHTML = '';
        return;
    }
    card.hidden = false;
    const canEdit = typeof hasCurrentPermission !== 'function' || hasCurrentPermission('expenses', 'update');
    const canDelete = canDeleteExpenseRequest(item);
    const createdAt = Number(item.created_at || 0)
        ? new Date(Number(item.created_at) * 1000).toLocaleString('ru-RU')
        : 'Не указана';
    const paymentText = item.linked_payment_id
        ? `Оплата №${Number(item.linked_payment_id)} · ${financeStatusLabel(item.linked_payment_status || 'planned')}`
        : 'Будет создана после согласования';
    body.innerHTML = `
        <div class="expense-detail-card">
            <div class="expense-detail-card__header">
                <div>
                    <span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseEscape(enterpriseStatusLabel(item.status))}</span>
                    <h2>${expenseCardValue(item.title, 'Запрос на оплату')}</h2>
                    <p>Запрос №${Number(item.id)} · создан ${expenseCardValue(createdAt)}</p>
                </div>
                <div class="expense-detail-card__actions">
                    ${canEdit ? `<button class="btn-secondary" onclick="editExpenseRequest(${Number(item.id)})">Редактировать</button>` : ''}
                    ${canDelete ? `<button class="btn-danger" onclick="deleteExpenseRequest(${Number(item.id)})">Удалить</button>` : ''}
                </div>
            </div>
            <div class="expense-detail-card__facts">
                <div><span>Сумма</span><strong>${enterpriseEscape(formatMoney(item.amount || 0, item.currency))}</strong></div>
                <div><span>Тип</span><strong>${enterpriseEscape(expenseRequestTypeLabel(item.request_type))}</strong></div>
                <div><span>Оплатить до</span><strong>${expenseCardValue(item.due_date, 'Срок не указан')}</strong></div>
                <div><span>Статус</span><strong>${enterpriseEscape(enterpriseStatusLabel(item.status))}</strong></div>
            </div>
            <div class="expense-detail-card__sections">
                <section class="expense-detail-section">
                    <div class="expense-detail-section__title"><span>1</span><h3>Основание расхода</h3></div>
                    <dl>
                        <div><dt>Название</dt><dd>${expenseCardValue(item.title)}</dd></div>
                        <div><dt>Проект</dt><dd>${expenseCardValue(item.project_contract || item.project_name, 'Без проекта')}</dd></div>
                        <div><dt>Клиент / контрагент</dt><dd>${expenseCardValue(item.client_name, 'Не выбран')}</dd></div>
                        <div><dt>Комментарий</dt><dd>${expenseCardValue(item.comment)}</dd></div>
                    </dl>
                </section>
                <section class="expense-detail-section">
                    <div class="expense-detail-section__title"><span>2</span><h3>Согласование и оплата</h3></div>
                    <dl>
                        <div><dt>Согласующий отдел</dt><dd>${expenseCardValue(item.approver_role)}</dd></div>
                        <div><dt>Согласующий</dt><dd>${expenseCardValue(item.approver_name, 'Сотрудник роли')}</dd></div>
                        <div><dt>Создал</dt><dd>${expenseCardValue(item.created_by)}</dd></div>
                        <div><dt>Согласовал</dt><dd>${expenseCardValue(item.approved_by, 'Ожидает решения')}</dd></div>
                        <div><dt>Связанная оплата</dt><dd>${expenseCardValue(paymentText)}</dd></div>
                    </dl>
                </section>
            </div>
        </div>
    `;
}

async function renderExpenses() {
    await loadEnterpriseData();
    populateEnterpriseSelects();
    const metrics = expenseSummaryDB?.metrics || {};
    const metricsGrid = document.getElementById('expensesMetricsGrid');
    const tbody = document.getElementById('expenseRequestsTable');
    if (!metricsGrid || !tbody) return;
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">Черновики</div><div class="metric-value">${metrics.draft || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">На согласовании</div><div class="metric-value">${metrics.pending || 0}</div></div>
        <div class="metric-card success"><div class="metric-title">Согласовано / оплачено</div><div class="metric-value">${(metrics.approved || 0) + (metrics.paid || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">Сумма в ожидании</div><div class="metric-value">${formatMoney(metrics.pending_amount || 0)}</div></div>
    `;
    tbody.innerHTML = expenseRequestsDB.length ? expenseRequestsDB.map(item => `
        <tr>
            <td><div class="finance-row-title">${expenseCardValue(item.title)}</div><div class="finance-row-meta">${enterpriseEscape(expenseRequestTypeLabel(item.request_type))} · ${expenseCardValue(item.due_date, 'без срока')}</div></td>
            <td><div class="finance-row-title">${expenseCardValue(item.project_contract || item.project_name, 'Без проекта')}</div><div class="finance-row-meta">${expenseCardValue(item.client_name, 'Без контрагента')}</div></td>
            <td><div class="finance-row-title">${enterpriseEscape(formatMoney(item.amount || 0, item.currency))}</div><div class="finance-row-meta">${expenseCardValue(item.comment, 'Без комментария')}</div></td>
            <td><div class="finance-row-title">${expenseCardValue(item.approver_name || item.approver_role, 'Не назначен')}</div><div class="finance-row-meta">${item.approved_by ? 'Решение зафиксировано' : 'Ожидает решения'}</div></td>
            <td><span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseEscape(enterpriseStatusLabel(item.status))}</span><div class="finance-row-meta">${item.linked_payment_id ? `Оплата №${Number(item.linked_payment_id)} · ${enterpriseEscape(financeStatusLabel(item.linked_payment_status || 'planned'))}` : 'Оплата появится после согласования'}</div></td>
            <td><button class="btn-primary" onclick="openExpenseRequestCard(${Number(item.id)})">Открыть карточку</button></td>
        </tr>
    `).join('') : '<tr><td colspan="6" class="nsi-empty-row">Запросов на оплату пока нет.</td></tr>';
    renderExpenseRequestCard();
}

async function renderInternalRequests() {
    await loadEnterpriseData();
    populateEnterpriseSelects();
    const metricsGrid = document.getElementById('requestsMetricsGrid');
    const container = document.getElementById('internalRequestsList');
    if (!metricsGrid || !container) return;
    renderInternalRequestMetrics();
    const formCard = document.getElementById('internalRequestFormCard');
    const listCard = document.querySelector('#requestsView .internal-request-list-card');
    const registryActive = document.getElementById('internalRequestRegistryTab')?.getAttribute('aria-selected') === 'true';
    const canUseForm = hasCurrentPermission('requests', 'create') || hasCurrentPermission('requests', 'update');
    if (formCard) formCard.hidden = registryActive || !canUseForm;
    if (listCard) listCard.hidden = !registryActive;
    renderInternalRequestList();
    renderInternalRequestDetailCard();
}

function renderInternalRequestMetrics() {
    const metricsGrid = document.getElementById('requestsMetricsGrid');
    if (!metricsGrid) return;
    const metrics = {
        new: internalRequestsDB.filter(item => item.status === 'new').length,
        in_work: internalRequestsDB.filter(item => item.status === 'in_work').length,
        done: internalRequestsDB.filter(item => item.status === 'done').length,
    };
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">Ожидают начала</div><div class="metric-value">${metrics.new}</div></div>
        <div class="metric-card warning"><div class="metric-title">Сейчас в работе</div><div class="metric-value">${metrics.in_work}</div></div>
        <div class="metric-card success"><div class="metric-title">Выполнено</div><div class="metric-value">${metrics.done}</div></div>
    `;
}

function internalRequestTypeLabel(value) {
    return {
        purchase: 'Материалы или закупка',
        production: 'Производство',
        clarification: 'Уточнение информации',
        document: 'Документ',
        payment: 'Оплата',
        service: 'Сервис или ремонт',
        other: 'Другая задача',
    }[value] || 'Другая задача';
}

function canDeleteInternalRequest(item) {
    if (!item || !currentUser) return false;
    if (String(currentUser.role || '').trim() === 'Директор') return true;
    const actorEmail = String(currentUser.email || '').trim().toLowerCase();
    const authorEmail = String(item.created_by || '').trim().toLowerCase();
    return !!actorEmail && actorEmail === authorEmail;
}

function openInternalRequestCard(id) {
    selectedInternalRequestId = Number(id || 0);
    renderInternalRequestDetailCard();
    showInternalRequestRegistry();
    document.getElementById('internalRequestDetailCard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderInternalRequestDetailCard() {
    const card = document.getElementById('internalRequestDetailCard');
    const body = document.getElementById('internalRequestDetailBody');
    if (!card || !body) return;
    const item = internalRequestsDB.find(row => Number(row.id) === Number(selectedInternalRequestId));
    if (!item) {
        card.hidden = true;
        body.innerHTML = '';
        return;
    }
    const safe = value => enterpriseEscape(String(value ?? ''));
    const value = (input, fallback = 'Не указано') => safe(String(input ?? '').trim() || fallback);
    const canUpdate = hasCurrentPermission('requests', 'update');
    const canDelete = canDeleteInternalRequest(item);
    const createdAt = Number(item.created_at || 0)
        ? new Date(Number(item.created_at) * 1000).toLocaleString('ru-RU')
        : 'Не указана';
    const project = item.project_contract || item.project_name || 'Без проекта';
    const quickAction = !canUpdate ? '' : item.status === 'new'
        ? `<button class="btn-primary" onclick="setInternalRequestStatus(${Number(item.id)}, 'in_work')">Взять в работу</button>`
        : item.status === 'in_work'
            ? `<button class="btn-primary" onclick="setInternalRequestStatus(${Number(item.id)}, 'done')">Отметить выполненной</button>`
            : '';
    card.hidden = false;
    body.innerHTML = `
        <div class="internal-request-detail__header">
            <div>
                <div class="internal-request-detail__eyebrow">Внутренняя заявка №${Number(item.id)}</div>
                <h3>${value(item.title)}</h3>
                <div class="internal-request-detail__badges">
                    <span class="status-badge ${enterpriseStatusClass(item.status)}">${safe(enterpriseStatusLabel(item.status))}</span>
                    <span class="internal-request-priority">${safe(priorityLabel(item.priority || 'normal'))}</span>
                </div>
            </div>
            <button type="button" class="btn-secondary" onclick="selectedInternalRequestId=0; renderInternalRequestDetailCard()">Закрыть карточку</button>
        </div>
        <section class="internal-request-detail__result">
            <span>Ожидаемый результат</span>
            <p>${value(item.comment, 'Описание результата не добавлено')}</p>
        </section>
        <div class="internal-request-detail__grid">
            <div><span>Тип заявки</span><strong>${safe(internalRequestTypeLabel(item.request_type))}</strong></div>
            <div><span>Получатель</span><strong>${value(item.target_role)}</strong></div>
            <div><span>Исполнитель</span><strong>${value(item.assignee_name, 'Весь отдел')}</strong></div>
            <div><span>Выполнить до</span><strong>${value(item.deadline)}</strong></div>
            <div><span>Проект</span><strong>${value(project)}</strong></div>
            <div><span>Приоритет</span><strong>${safe(priorityLabel(item.priority || 'normal'))}</strong></div>
            <div><span>Автор</span><strong>${value(item.created_by)}</strong></div>
            <div><span>Создана</span><strong>${safe(createdAt)}</strong></div>
        </div>
        <div class="internal-request-detail__actions">
            ${quickAction}
            ${canUpdate ? `<button class="btn-secondary" onclick="editInternalRequest(${Number(item.id)})">Редактировать</button>` : ''}
            ${canDelete ? `<button class="btn-danger" onclick="deleteInternalRequest(${Number(item.id)})">Удалить</button>` : ''}
        </div>
    `;
}

function renderInternalRequestList() {
    const container = document.getElementById('internalRequestsList');
    if (!container) return;
    const safe = value => typeof escapeHtml === 'function' ? escapeHtml(String(value ?? '')) : String(value ?? '');
    const query = (document.getElementById('internalRequestSearch')?.value || '').trim().toLowerCase();
    const statusFilter = document.getElementById('internalRequestStatusFilter')?.value || 'active';
    const rows = internalRequestsDB.filter(item => {
        const matchesStatus = statusFilter === 'all'
            || (statusFilter === 'active' && ['new', 'in_work'].includes(item.status))
            || item.status === statusFilter;
        if (!matchesStatus) return false;
        if (!query) return true;
        return [item.title, item.comment, item.project_contract, item.project_name, item.target_role, item.assignee_name]
            .some(value => String(value || '').toLowerCase().includes(query));
    });

    container.innerHTML = rows.length ? rows.map(item => {
        const project = item.project_contract || item.project_name || 'Без проекта';
        const assignee = item.assignee_name ? `Исполнитель: ${item.assignee_name}` : `Получатель: ${item.target_role || 'отдел не выбран'}`;
        const deadline = item.deadline || 'Срок не указан';
        return `
            <article class="internal-request-card internal-request-card--${safe(item.priority || 'normal')}">
                <div class="internal-request-card__main">
                    <div class="internal-request-card__topline">
                        <span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseStatusLabel(item.status)}</span>
                        ${item.priority === 'normal' ? '' : `<span class="internal-request-priority">${safe(priorityLabel(item.priority))}</span>`}
                    </div>
                    <h4>${safe(item.title)}</h4>
                    <p>${safe(item.comment || 'Описание не добавлено')}</p>
                    <div class="internal-request-card__meta">
                        <span>${safe(project)}</span>
                        <span>${safe(assignee)}</span>
                        <span>${safe(deadline)}</span>
                    </div>
                </div>
                <div class="internal-request-card__actions">
                    <button class="btn-primary" onclick="openInternalRequestCard(${Number(item.id)})">Открыть карточку</button>
                </div>
            </article>
        `;
    }).join('') : `
        <div class="empty-state internal-request-empty">
            <strong>${query ? 'Ничего не найдено' : 'В этой очереди заявок нет'}</strong>
            <span>${query ? 'Измените запрос поиска.' : 'Новая заявка появится здесь сразу после отправки.'}</span>
        </div>
    `;
}

async function renderResources() {
    await loadEnterpriseData();
    populateEnterpriseSelects();
    const metrics = resourceSummaryDB?.metrics || {};
    const departmentLoad = resourceSummaryDB?.department_load || {};
    const crewRows = resourceAllocationsDB.filter(item => item.crew_name || item.crew_type);
    const uniqueCrews = [...new Set(crewRows.map(item => item.crew_name || `${item.crew_type || 'бригада'}:${item.location || 'объект'}`))];
    const metricsGrid = document.getElementById('resourcesMetricsGrid');
    const container = document.getElementById('resourceAllocationsList');
    if (!metricsGrid || !container) return;
    syncResourceEditorState();
    const canUpdate = hasCurrentPermission('resources', 'update');
    const canDelete = hasCurrentPermission('resources', 'delete');
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">Всего размещений</div><div class="metric-value">${metrics.allocations_total || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Перегруз</div><div class="metric-value">${metrics.overloaded || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Монтажных бригад</div><div class="metric-value">${uniqueCrews.length}</div></div>
        <div class="metric-card success"><div class="metric-title">Средняя загрузка</div><div class="metric-value">${metrics.avg_load || 0}%</div></div>
    `;
    const loadList = Object.entries(departmentLoad).map(([department, load]) => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${department}</div>
                <div class="client360-item-meta">Суммарная загрузка по действующим ресурсам</div>
            </div>
            <div class="client360-item-side">${load}%</div>
        </div>
    `).join('');
    const crewList = crewRows.length ? `
        <div class="ops-inline-section" style="margin-bottom:16px;">
            <div class="ops-inline-title">Выездные бригады и монтаж</div>
            <div class="client360-list" style="margin-top:12px;">
                ${crewRows.slice(0, 12).map(item => `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${item.crew_name || item.resource_name}</div>
                            <div class="client360-item-meta">${item.crew_type || 'Бригада'} · ${item.location || 'Локация не указана'}</div>
                            <div class="client360-item-meta">${item.project_contract || item.project_name || 'Без проекта'} · ${item.date_from || '—'} → ${item.date_to || '—'}</div>
                        </div>
                        <div class="client360-item-side">${item.load_percent || 0}%</div>
                    </div>
                `).join('')}
            </div>
        </div>
    ` : '';
    const itemsList = resourceAllocationsDB.map(item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.resource_name}</div>
                <div class="client360-item-meta">${item.department || 'Без отдела'} · ${item.role_name || 'Без роли'} · ${item.project_contract || item.project_name || 'Без проекта'}</div>
                <div class="client360-item-meta">${item.date_from || '—'} → ${item.date_to || '—'}${item.location ? ` · ${item.location}` : ''}</div>
                <div class="client360-item-meta">${item.crew_name ? `${item.crew_name}${item.crew_type ? ` · ${item.crew_type}` : ''}` : 'Индивидуальная загрузка'}</div>
            </div>
            <div class="view-actions">
                <span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseStatusLabel(item.status)}</span>
                <span class="client360-item-side">${item.load_percent || 0}%</span>
                ${canUpdate ? `<button class="btn-secondary" onclick="editResourceAllocation(${item.id})">Редактировать</button>` : ''}
                ${canDelete ? `<button class="btn-danger" onclick="deleteResourceAllocation(${item.id})">Удалить</button>` : ''}
            </div>
        </div>
    `).join('');
    container.innerHTML = `${crewList}${loadList}${itemsList}` || '<div class="empty-state">Загрузка ресурсов пока не задана.</div>';
}

async function renderServiceCases() {
    await loadEnterpriseData();
    populateEnterpriseSelects();
    const metrics = serviceSummaryDB?.metrics || {};
    const metricsGrid = document.getElementById('serviceMetricsGrid');
    const tbody = document.getElementById('serviceCasesTable');
    if (!metricsGrid || !tbody) return;
    syncServiceEditorState();
    const canUpdate = hasCurrentPermission('service', 'update');
    const canDelete = hasCurrentPermission('service', 'delete');
    metricsGrid.innerHTML = `
        <div class="metric-card warning"><div class="metric-title">Открытые кейсы</div><div class="metric-value">${metrics.open || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Гарантийные</div><div class="metric-value">${metrics.warranty || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Просрочен сервис</div><div class="metric-value">${metrics.overdue_sla || 0}</div></div>
        <div class="metric-card success"><div class="metric-title">Закрытые</div><div class="metric-value">${metrics.closed || 0}</div></div>
    `;
    tbody.innerHTML = serviceCasesDB.length ? serviceCasesDB.map(item => `
        <tr>
            <td><div class="finance-row-title finance-row-title--compact">${item.title}</div><div class="finance-row-meta">${item.case_number || 'без номера'} · ${item.responsible || 'без ответственного'}</div></td>
            <td><div class="finance-row-title finance-row-title--compact">${item.project_contract || item.project_name || 'Без проекта'}</div><div class="finance-row-meta">${item.client_name || 'Без контрагента'}</div></td>
            <td><div class="finance-row-title finance-row-title--compact">${serviceTypeLabel(item.case_type)}</div><div class="finance-row-meta">${priorityLabel(item.priority)}</div></td>
            <td><div class="finance-row-title finance-row-title--compact">${item.sla_deadline || '—'}</div><div class="finance-row-meta">Гарантия до ${item.warranty_until || 'не указана'}</div></td>
            <td><span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseStatusLabel(item.status)}</span></td>
            <td><div class="view-actions view-actions--table-actions">${canUpdate ? `<button class="btn-secondary" onclick="editServiceCase(${item.id})">Редактировать</button>` : '<span class="finance-row-meta">Только просмотр</span>'}${canDelete ? `<button class="btn-danger" onclick="deleteServiceCase(${item.id})">Удалить</button>` : ''}</div></td>
        </tr>
    `).join('') : '<tr><td colspan="6" class="nsi-empty-row">Сервисных кейсов пока нет.</td></tr>';
}

function renderExecutiveSimpleDashboard() {
    const statusMount = document.getElementById('executiveSimpleStatus');
    const metricsMount = document.getElementById('executiveSimpleMetrics');
    const queueMount = document.getElementById('executiveSimpleQueue');
    if (!statusMount || !metricsMount || !queueMount) return;

    if (!executiveSummaryDB) {
        statusMount.innerHTML = '<strong>Нет доступа к панели</strong><span>Панель директора доступна только пользователю с соответствующим правом.</span>';
        metricsMount.innerHTML = '';
        queueMount.innerHTML = '<div class="executive-simple-empty">Данные для контроля недоступны.</div>';
        return;
    }

    const metrics = executiveSummaryDB.metrics || {};
    const decisionItems = buildExecutiveDecisionQueue(metrics, {}, {}, executiveSummaryDB);
    const criticalCount = Number(metrics.blocked_approvals || 0)
        + Number(metrics.production_overdue || 0)
        + Number(metrics.service_sla_breached || 0)
        + Number(metrics.integration_incidents || 0);
    const attentionCount = criticalCount
        + Number(metrics.resource_overloaded || 0)
        + Number(metrics.inventory_discrepancies || 0);

    statusMount.className = `executive-simple-status ${criticalCount ? 'is-alert' : attentionCount ? 'is-warning' : 'is-ok'}`;
    statusMount.innerHTML = criticalCount
        ? `<div><span>Сейчас</span><strong>Требуется вмешательство</strong><small>Критичных сигналов: ${criticalCount}. Начните с очереди решений ниже.</small></div><button class="btn-primary" type="button" onclick="document.getElementById('executiveSimpleQueue').scrollIntoView({behavior:'smooth',block:'start'})">К решениям</button>`
        : `<div><span>Сейчас</span><strong>${attentionCount ? 'Есть вопросы для контроля' : 'Критичных проблем нет'}</strong><small>${attentionCount ? `Сигналов внимания: ${attentionCount}.` : 'Основные процессы работают без критичных отклонений.'}</small></div>`;

    metricsMount.innerHTML = `
        <button type="button" onclick="navigateTo('approvals')"><span>Зависшие согласования</span><strong>${Number(metrics.blocked_approvals || 0)}</strong><small>нужно решение</small></button>
        <button type="button" onclick="navigateTo('finance')"><span>Деньги под риском</span><strong>${formatMoney((metrics.cash_overdue_receivables || 0) + (metrics.expense_pending || 0))}</strong><small>дебиторка и затраты</small></button>
        <button type="button" onclick="navigateTo('dashboard')"><span>Рисковые проекты</span><strong>${(executiveSummaryDB.risk_projects || []).filter(item => Number(item.risk_score || 0) > 0).length}</strong><small>требуют контроля</small></button>
        <button type="button" onclick="navigateTo('production')"><span>Просрочка производства</span><strong>${Number(metrics.production_overdue || 0)}</strong><small>заказов вне срока</small></button>
    `;

    queueMount.innerHTML = decisionItems.length ? decisionItems.map((item, index) => `
        <article class="executive-simple-item">
            <span class="executive-simple-item__number">${index + 1}</span>
            <div><h3>${enterpriseEscape(enterpriseDisplayText(item.title, 'Требуется решение').replace(/^(\S+)\s+\1(?=\s|$)/i, '$1'))}</h3><p>${enterpriseEscape(enterpriseDisplayText(item.meta, 'Откройте рабочий раздел и проверьте источник.'))}</p></div>
            <div class="executive-simple-item__action">${item.action}</div>
        </article>
    `).join('') : '<div class="executive-simple-empty">Вопросов, требующих решения директора, сейчас нет.</div>';
}

async function renderExecutiveDashboard() {
    if (document.getElementById('executiveSimpleDashboard')) {
        const summary = await apiCall('/executive/summary');
        executiveSummaryDB = summary && !summary.error ? summary : null;
        renderExecutiveSimpleDashboard();
        return;
    }
    await loadEnterpriseData();
    renderExecutiveRoleWorkbench();
    toggleRoleSecondarySections('executiveView', !!window.__executiveSecondaryExpanded);
    const metrics = executiveSummaryDB?.metrics || {};
    const metricsGrid = document.getElementById('executiveMetricsGrid');
    const executiveErpMetrics = document.getElementById('executiveErpMetrics');
    const executiveDataQuality = document.getElementById('executiveDataQuality');
    if (!metricsGrid) return;
    if (!executiveSummaryDB) {
        metricsGrid.innerHTML = '<div class="empty-state">Панель директора доступна только директору.</div>';
        return;
    }
    renderExecutiveBoardroom();
    const erpMetrics = erpSummaryDB?.metrics || {};
    if (executiveErpMetrics) {
        executiveErpMetrics.innerHTML = `
            <div class="metric-card"><div class="metric-title">Сквозных процессов</div><div class="metric-value">${erpMetrics.processes_total || 0}</div></div>
            <div class="metric-card warning"><div class="metric-title">Просрочено</div><div class="metric-value">${erpMetrics.overdue_processes || 0}</div></div>
            <div class="metric-card"><div class="metric-title">Зарезервировано</div><div class="metric-value">${erpMetrics.stock_reserved_qty || 0}</div></div>
            <div class="metric-card danger"><div class="metric-title">Проблемы данных</div><div class="metric-value">${erpMetrics.data_issues || 0}</div></div>
        `;
    }
    if (executiveDataQuality) {
        const quality = erpDataQualityDB || erpSummaryDB?.quality || {};
        executiveDataQuality.innerHTML = `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Дубли клиентов</div>
                    <div class="client360-item-meta">Одинаковые карточки размывают один источник правды</div>
                </div>
                <div class="client360-item-side">${(quality.clients_duplicates || []).length + (quality.clients_duplicate_inn || []).length}</div>
            </div>
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Дубли номенклатуры</div>
                    <div class="client360-item-meta">Артикул должен быть единственным ключом справочника</div>
                </div>
                <div class="client360-item-side">${(quality.nomenclature_duplicates || []).length}</div>
            </div>
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Осиротевшие записи</div>
                    <div class="client360-item-meta">Нужно дочистить связи с проектами и клиентами</div>
                </div>
                <div class="client360-item-side">${Object.values(quality.orphans || {}).reduce((sum, value) => sum + Number(value || 0), 0)}</div>
            </div>
        `;
    }
    const queuedSync = integrationQueueDB.filter(item => ['queued', 'retry', 'processing'].includes(item.state)).length;
    const failedSync = integrationQueueDB.filter(item => ['failed', 'conflict'].includes(item.state)).length;
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">Активные проекты</div><div class="metric-value">${metrics.projects_active || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Кассовый разрыв</div><div class="metric-value">${formatMoney(metrics.cash_gap || 0)}</div></div>
        <div class="metric-card danger"><div class="metric-title">Просроченная дебиторка</div><div class="metric-value">${formatMoney(metrics.cash_overdue_receivables || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">Подвисшие затраты</div><div class="metric-value">${formatMoney(metrics.expense_pending || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">Перегруженные ресурсы</div><div class="metric-value">${metrics.resource_overloaded || 0}</div></div>
        <div class="metric-card danger"><div class="metric-title">Застрявшие согласования</div><div class="metric-value">${metrics.blocked_approvals || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Просрочен сервис</div><div class="metric-value">${metrics.service_sla_breached || 0}</div></div>
        <div class="metric-card danger"><div class="metric-title">Открытый сервис</div><div class="metric-value">${metrics.service_open || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Просрочено производство</div><div class="metric-value">${metrics.production_overdue || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Перегруз ресурсов</div><div class="metric-value">${metrics.resource_hotspots || 0}</div></div>
        <div class="metric-card danger"><div class="metric-title">Складские расхождения</div><div class="metric-value">${metrics.inventory_discrepancies || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Очередь 1С</div><div class="metric-value">${queuedSync}</div></div>
        <div class="metric-card warning"><div class="metric-title">Ошибки 1С</div><div class="metric-value">${Math.max(failedSync, metrics.integration_incidents || 0)}</div></div>
    `;
    const renderList = (items, mapFn, emptyText) => {
        return items && items.length ? items.map(mapFn).join('') : `<div class="empty-state">${emptyText}</div>`;
    };
    const riskProjects = document.getElementById('executiveRiskProjects');
    const resources = document.getElementById('executiveResources');
    const expenses = document.getElementById('executiveExpenses');
    const requests = document.getElementById('executiveRequests');
    const service = document.getElementById('executiveService');
    const bottlenecks = document.getElementById('executiveProductionBottlenecks');
    const discrepancies = document.getElementById('executiveInventoryDiscrepancies');
    const integrationQueue = document.getElementById('executiveIntegrationQueue');
    const integrationMonitoring = document.getElementById('executiveIntegrationMonitoring');
    const financeSlices = document.getElementById('executiveFinanceSlices');
    const warehouseTurnover = document.getElementById('executiveWarehouseTurnover');
    const clientMargin = document.getElementById('executiveClientMargin');
    const productMargin = document.getElementById('executiveProductMargin');
    const slaSummary = document.getElementById('executiveSlaSummary');
    const planFactSummary = document.getElementById('executivePlanFactSummary');
    const roleDashboards = document.getElementById('executiveRoleDashboards');
    const savedViews = document.getElementById('executiveSavedViews');
    if (riskProjects) riskProjects.innerHTML = renderList(executiveSummaryDB.risk_projects, item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.contract || '—'} · ${item.name}</div>
                <div class="client360-item-meta">${item.manager || 'Менеджер не задан'} · риск ${item.risk_score}/3</div>
                <div class="client360-item-meta">Открыто входящих: ${formatMoney(item.incoming_open)} · исходящих: ${formatMoney(item.outgoing_open)}</div>
            </div>
            <div class="view-actions">
                <span class="client360-item-side">${formatMoney(item.margin)}</span>
                <button class="btn-secondary" onclick="openProject(${item.id})">Открыть</button>
            </div>
        </div>
    `, 'Рисковых проектов пока нет.');
    if (resources) resources.innerHTML = renderList(executiveSummaryDB.overloaded_resources, item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.resource_name}</div>
                <div class="client360-item-meta">${item.department || 'Без отдела'} · ${item.project_contract || item.project_name || 'Без проекта'}</div>
                <div class="client360-item-meta">${item.date_from || '—'} → ${item.date_to || '—'}</div>
            </div>
            <div class="client360-item-side">${item.load_percent || 0}%</div>
        </div>
    `, 'Перегруженных ресурсов нет.');
    if (expenses) expenses.innerHTML = renderList(executiveSummaryDB.pending_expenses, item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.title}</div>
                <div class="client360-item-meta">${item.project_contract || item.project_name || 'Без проекта'} · ${item.approver_name || item.approver_role || 'без согласующего'}</div>
            </div>
            <div class="client360-item-side">${formatMoney(item.amount || 0, item.currency)}</div>
        </div>
    `, 'Подвисших затрат нет.');
    if (requests) requests.innerHTML = renderList(executiveSummaryDB.internal_requests, item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.title}</div>
                <div class="client360-item-meta">${item.target_role || 'Без отдела'} · ${item.assignee_name || 'исполнитель не задан'}</div>
            </div>
            <span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseStatusLabel(item.status)}</span>
        </div>
    `, 'Активных внутренних заявок нет.');
    if (service) service.innerHTML = renderList(executiveSummaryDB.service_cases, item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.title}</div>
                <div class="client360-item-meta">${item.project_contract || item.project_name || 'Без проекта'} · ${item.responsible || 'без ответственного'}</div>
            </div>
            <span class="status-badge ${enterpriseStatusClass(item.status)}">${enterpriseStatusLabel(item.status)}</span>
        </div>
    `, 'Открытых сервисных кейсов нет.');
    if (bottlenecks) bottlenecks.innerHTML = renderList(executiveSummaryDB.production_bottlenecks, item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.work_center || 'Без участка'}</div>
                <div class="client360-item-meta">Активных операций: ${item.active || 0} · всего операций: ${item.operations || 0}</div>
            </div>
            <div class="client360-item-side">${Number(item.hours || 0).toLocaleString('ru-RU')} ч</div>
        </div>
    `, 'Узких мест производства пока нет.');
    if (discrepancies) discrepancies.innerHTML = renderList(executiveSummaryDB.inventory_discrepancies, item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.doc_number || 'Акт'} · ${item.nomenclature_name || item.article}</div>
                <div class="client360-item-meta">${item.warehouse || 'Склад не указан'} / ${item.bin_code || 'ячейка не указана'} · ${item.reason || 'без причины'}</div>
            </div>
            <div class="client360-item-side">${Number(item.adjustment_qty || 0).toLocaleString('ru-RU')} ${item.unit || 'шт'}</div>
        </div>
    `, 'Складских расхождений нет.');
    if (integrationQueue) integrationQueue.innerHTML = renderList(integrationQueueDB.slice(0, 8), item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${integrationEntityLabel(item.entity_type)} · ${item.entity_key || item.external_id || 'без ключа'}</div>
                <div class="client360-item-meta">${operationsStateLabel(item.state)} · ${item.external_id || 'внешний идентификатор не присвоен'}</div>
                <div class="client360-item-meta">${item.last_error || 'Ошибок нет'}</div>
            </div>
            <div class="client360-item-side">${item.updated_at ? new Date(Number(item.updated_at) * 1000).toLocaleString('ru-RU') : '—'}</div>
        </div>
    `, 'Глобальная очередь 1С сейчас пуста.');
    if (integrationMonitoring) {
        const monitoringMetrics = integrationMonitoringDB?.metrics || {};
        const healthRows = integrationMonitoringDB?.entity_health || [];
        integrationMonitoring.innerHTML = `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Общее состояние очереди</div>
                    <div class="client360-item-meta">в очереди ${monitoringMetrics.queued || 0} · повтор ${monitoringMetrics.retry || 0} · обработка ${monitoringMetrics.processing || 0} · ошибок ${monitoringMetrics.failed || 0}</div>
                </div>
                <div class="client360-item-side">${monitoringMetrics.stale_processing || 0} зависло</div>
            </div>
            ${healthRows.length ? healthRows.slice(0, 8).map(item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${integrationEntityLabel(item.entity_type)}</div>
                        <div class="client360-item-meta">в очереди ${item.queued || 0} · повтор ${item.retry || 0} · обработка ${item.processing || 0}</div>
                    </div>
                    <div class="client360-item-side">${item.failed || 0} ошибок</div>
                </div>
            `).join('') : '<div class="empty-state">Проблемных очередей 1С не видно.</div>'}
        `;
    }
    if (financeSlices) {
        const legalRows = executiveFinanceAnalyticsDB?.by_legal_entity || [];
        const businessRows = executiveFinanceAnalyticsDB?.by_business_unit || [];
        financeSlices.innerHTML = `
            <div class="ops-inline-section">
                <div class="ops-inline-title">Юрлица</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${legalRows.length ? legalRows.slice(0, 5).map(item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${item.legal_entity_name || 'Без юрлица'}</div>
                                <div class="client360-item-meta">Входящий ${formatMoney(item.incoming || 0)} · исходящий ${formatMoney(item.outgoing || 0)}</div>
                            </div>
                            <div class="view-actions">
                                <span class="client360-item-side">${formatMoney(item.net || 0)}</span>
                                <button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('legal_entity', '${enterpriseEscape(item.legal_entity_name || '')}', ${Number(item.legal_entity_id || 0)})">Детализация</button>
                            </div>
                        </div>
                    `).join('') : '<div class="empty-state">Срез по юрлицам пока пуст.</div>'}
                </div>
            </div>
            <div class="ops-inline-section" style="margin-top:16px;">
                <div class="ops-inline-title">Подразделения</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${businessRows.length ? businessRows.slice(0, 5).map(item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${item.business_unit_name || 'Без подразделения'}</div>
                                <div class="client360-item-meta">Открыто ${formatMoney(item.open || 0)}</div>
                            </div>
                            <div class="view-actions">
                                <span class="client360-item-side">${formatMoney(item.net || 0)}</span>
                                <button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('business_unit', '${enterpriseEscape(item.business_unit_name || '')}', ${Number(item.business_unit_id || 0)})">Детализация</button>
                            </div>
                        </div>
                    `).join('') : '<div class="empty-state">Срез по подразделениям пока пуст.</div>'}
                </div>
            </div>
        `;
    }
    if (warehouseTurnover) warehouseTurnover.innerHTML = renderList(executiveFinanceAnalyticsDB?.warehouse_turnover || [], item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.warehouse || 'Без склада'}</div>
                <div class="client360-item-meta">Вход ${Number(item.qty_in || 0).toLocaleString('ru-RU')} · выход ${Number(item.qty_out || 0).toLocaleString('ru-RU')}</div>
            </div>
            <div class="view-actions">
                <span class="client360-item-side">${Number(item.net_qty || 0).toLocaleString('ru-RU')}</span>
                <button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('warehouse', '${enterpriseEscape(item.warehouse || '')}')">Детализация</button>
            </div>
        </div>
    `, 'Оборот склада пока пуст.');
    if (clientMargin) clientMargin.innerHTML = renderList(executiveAnalyticsDeepDB?.by_client || [], item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.client_name || 'Без клиента'}</div>
                <div class="client360-item-meta">Оплачено вход ${formatMoney(item.incoming_paid || 0)} · выход ${formatMoney(item.outgoing_paid || 0)}</div>
                <div class="client360-item-meta">Открытая экспозиция ${formatMoney(item.open_exposure || 0)}</div>
            </div>
            <div class="view-actions">
                <span class="client360-item-side">${formatMoney(item.fact_margin || 0)}</span>
                <button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('client', '${enterpriseEscape(item.client_name || '')}', ${Number(item.client_id || 0)})">Детализация</button>
            </div>
        </div>
    `, 'Клиентская маржинальность пока пуста.');
    if (productMargin) productMargin.innerHTML = renderList(executiveAnalyticsDeepDB?.by_product || [], item => `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">${item.item_name || item.article || 'Позиция'}</div>
                <div class="client360-item-meta">${item.article || 'Без артикула'} · закуплено ${Number(item.purchase_qty || 0).toLocaleString('ru-RU')}</div>
                <div class="client360-item-meta">Выручка ${formatMoney(item.planned_revenue || 0)} · себестоимость ${formatMoney(item.planned_cost || 0)}</div>
            </div>
            <div class="view-actions">
                <span class="client360-item-side">${formatMoney(item.gross_margin || 0)}</span>
                <button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('product', '${enterpriseEscape(item.article || item.item_name || '')}')">Детали</button>
            </div>
        </div>
    `, 'Продуктовая маржинальность пока пуста.');
    if (slaSummary) {
        const breached = executiveAnalyticsDeepDB?.sla_summary?.breached || [];
        const dueSoon = executiveAnalyticsDeepDB?.sla_summary?.due_soon || [];
        slaSummary.innerHTML = `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Открытый сервисный контур</div>
                    <div class="client360-item-meta">Открыто ${executiveAnalyticsDeepDB?.sla_summary?.open_total || 0} · нарушено ${executiveAnalyticsDeepDB?.sla_summary?.breached_total || 0}</div>
                </div>
                <div class="client360-item-side">${executiveAnalyticsDeepDB?.sla_summary?.due_soon_total || 0} скоро</div>
            </div>
            ${renderList(breached.slice(0, 4), item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${item.title}</div>
                        <div class="client360-item-meta">${item.responsible || 'Не назначен'} · срок ${item.sla_deadline || '—'}</div>
                    </div>
                    <div class="client360-item-side">${Math.abs(Number(item.days_delta || 0))} дн</div>
                </div>
            `, 'Просроченных сервисных сроков пока нет.')}
            ${renderList(dueSoon.slice(0, 4), item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${item.title}</div>
                        <div class="client360-item-meta">${item.responsible || 'Не назначен'} · срок ${item.sla_deadline || '—'}</div>
                    </div>
                    <div class="client360-item-side">${item.days_delta || 0} дн</div>
                </div>
            `, 'Срочных сервисных кейсов пока нет.')}
        `;
    }
    if (planFactSummary) {
        const budgetRows = executiveAnalyticsDeepDB?.budget_plan_fact || [];
        const productionRows = executiveAnalyticsDeepDB?.production_plan_fact || [];
        const purchaseRows = executiveAnalyticsDeepDB?.purchase_plan_fact || [];
        planFactSummary.innerHTML = `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Бюджеты</div>
                    <div class="client360-item-meta">Периодов ${budgetRows.length} · отклонение ${formatMoney(executiveAnalyticsDeepDB?.metrics?.budget_variance_total || 0)}</div>
                </div>
            </div>
            ${renderList(budgetRows.slice(0, 3), item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${item.period_key}</div>
                        <div class="client360-item-meta">План ${formatMoney(item.plan_amount || 0)} · факт ${formatMoney(item.fact_amount || 0)}</div>
                    </div>
                    <div class="view-actions">
                        <span class="client360-item-side">${formatMoney(item.variance || 0)}</span>
                        <button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('budget_period', '${enterpriseEscape(item.period_key || '')}')">Детали</button>
                    </div>
                </div>
            `, 'План-факт бюджета пока пуст.')}
            ${renderList(productionRows.slice(0, 3), item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${item.order_name}</div>
                        <div class="client360-item-meta">План ${Number(item.planned_qty || 0).toLocaleString('ru-RU')} · факт ${Number(item.produced_qty || 0).toLocaleString('ru-RU')}</div>
                    </div>
                    <div class="view-actions">
                        <span class="client360-item-side">${formatMoney(item.cost_variance || 0)}</span>
                        <button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('production_order', '${enterpriseEscape(item.order_name || '')}', ${Number(item.order_id || 0)})">Детали</button>
                    </div>
                </div>
            `, 'План-факт производства пока пуст.')}
            ${renderList(purchaseRows.slice(0, 3), item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${item.item_name || item.item_article || 'Закупка'}</div>
                        <div class="client360-item-meta">${item.period_key || 'период?'} · количество ${Number(item.qty_plan || 0).toLocaleString('ru-RU')} / ${Number(item.qty_fact || 0).toLocaleString('ru-RU')}</div>
                    </div>
                    <div class="client360-item-side">${formatMoney(item.amount_variance || 0)}</div>
                </div>
            `, 'План-факт закупок пока пуст.')}
        `;
    }
    if (roleDashboards) {
        const dashboards = executiveDashboardHubDB?.role_dashboards || [];
        roleDashboards.innerHTML = renderList(dashboards, item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${item.title}${item.is_current ? ' · твоя роль' : ''}</div>
                <div class="client360-item-meta">${item.role_name} · ${item.description || ''}</div>
                <div class="client360-list" style="margin-top:10px;">
                    ${(item.widgets || []).map(widget => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${widget.label}</div>
                                <div class="client360-item-meta">${widget.hint || ''}</div>
                            </div>
                            <div class="view-actions">
                                <span class="client360-item-side">${typeof widget.value === 'number' ? (String(widget.value).includes('.') ? Number(widget.value).toLocaleString('ru-RU') : Number(widget.value).toLocaleString('ru-RU')) : enterpriseEscape(widget.value || '0')}</span>
                                ${widget.drilldown?.dimension ? `<button class="btn-secondary" onclick="openExecutiveAnalyticsDrilldown('${enterpriseEscape(widget.drilldown.dimension)}', '${enterpriseEscape(widget.drilldown.value || '')}', ${Number(widget.drilldown.value_id || 0)})">Детали</button>` : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `, 'Ролевые панели пока не собраны.');
    }
    if (savedViews) {
        const privateViews = executiveDashboardHubDB?.saved_views?.private || [];
        const sharedViews = executiveDashboardHubDB?.saved_views?.shared || [];
        const byType = executiveDashboardHubDB?.saved_views?.by_type || [];
        savedViews.innerHTML = `
            <div class="ops-inline-section">
                <div class="ops-inline-title">Мои аналитические срезы</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${renderList(privateViews.slice(0, 6), item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${enterpriseEscape(item.title || 'Срез')}</div>
                                <div class="client360-item-meta">${enterpriseReportTypeLabel(item.report_type)} · ${enterpriseDashboardKindLabel(item.dashboard_kind)}</div>
                            </div>
                            <div class="view-actions">
                                <span class="client360-item-side">${enterpriseEscape((item.tags || []).join(', ') || scopeLabel(item.scope))}</span>
                                <button class="btn-secondary" onclick="runOperationsSavedReport(${Number(item.id || 0)})">Открыть</button>
                            </div>
                        </div>
                    `, 'Личных аналитических срезов пока нет.')}
                </div>
            </div>
            <div class="ops-inline-section" style="margin-top:16px;">
                <div class="ops-inline-title">Общие панели</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${renderList(sharedViews.slice(0, 6), item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${enterpriseEscape(item.title || 'Общая панель')}</div>
                                <div class="client360-item-meta">${enterpriseEscape(item.target_role || 'все роли')} · ${enterpriseReportTypeLabel(item.report_type)}</div>
                            </div>
                            <div class="client360-item-side">${scopeLabel(item.scope || 'shared')}</div>
                        </div>
                    `, 'Общих аналитических панелей пока нет.')}
                </div>
            </div>
            <div class="ops-inline-section" style="margin-top:16px;">
                <div class="ops-inline-title">Типы сохранённых срезов</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${renderList(byType, item => `
                        <div class="client360-item">
                            <div class="client360-item-title">${enterpriseReportTypeLabel(item.report_type)}</div>
                            <div class="client360-item-meta">Количество аналитических срезов этого типа</div>
                            <div class="client360-item-side">${Number(item.count || 0)}</div>
                        </div>
                    `, 'Типов сохранённых аналитических срезов пока нет.')}
                </div>
            </div>
        `;
    }
    renderEnterpriseDrilldown();
}

async function loadOperationsCenterData() {
    const [
        monitoring,
        reconciliationRuns,
        bankAccounts,
        bankLines,
        telephonyAccounts,
        telephonyCalls,
        savedReports,
        reliability,
        runtime,
        events,
    ] = await Promise.all([
        apiCall('/operations/monitoring'),
        apiCall('/integration/1c/reconciliation?limit=20'),
        apiCall('/banking/accounts'),
        apiCall('/banking/statements?unreconciled=1'),
        apiCall('/telephony/accounts'),
        apiCall('/telephony/calls'),
        apiCall('/analytics/reports'),
        apiCall('/system/reliability'),
        apiCall('/system/runtime'),
        apiCall('/system/events?limit=40'),
    ]);
    operationsMonitoringDB = monitoring && !monitoring.error ? monitoring : null;
    reconciliationRunsDB = Array.isArray(reconciliationRuns) ? reconciliationRuns : [];
    bankAccountsOpsDB = Array.isArray(bankAccounts) ? bankAccounts : [];
    bankStatementLinesOpsDB = Array.isArray(bankLines) ? bankLines : [];
    telephonyAccountsOpsDB = Array.isArray(telephonyAccounts) ? telephonyAccounts : [];
    telephonyCallsOpsDB = Array.isArray(telephonyCalls) ? telephonyCalls : [];
    savedReportsOpsDB = Array.isArray(savedReports) ? savedReports : [];
    operationsReliabilityDB = reliability && !reliability.error ? reliability : (operationsMonitoringDB?.reliability || null);
    operationsRuntimeDB = runtime && !runtime.error ? runtime : null;
    operationsEventStreamDB = Array.isArray(events) ? events : [];
}

function integrationEntityLabel(value) {
    const labels = {
        finance_payment: 'Финансы',
        purchase_order: 'Закупка',
        sales_document: 'Реализация',
        production_order: 'Производство',
        stock_reservation: 'Резерв',
        nomenclature: 'Номенклатура',
        groups: 'Группы номенклатуры',
        warehouses: 'Склады',
        units: 'Единицы измерения',
        epl_waybill: 'ЭПЛ',
        bank_accounts: 'Банковские счета',
        telephony_accounts: 'Линии телефонии',
        telephony_calls: 'Звонки',
        employees: 'Сотрудники',
        positions: 'Должности',
        characteristics: 'Характеристики',
        legal_entities: 'Юрлица',
        business_units: 'Подразделения',
        operation_types: 'Виды операций',
        contracts: 'Договоры',
        clients: 'Клиенты',
        projects: 'Проекты',
        cashflow_articles: 'Статьи ДДС',
        income_expense_articles: 'Статьи доходов и расходов',
        financial_responsibility_centers: 'ЦФО',
        stock_reservations: 'Складские резервы',
        storage_cells: 'Ячейки хранения',
        bank_statement_lines: 'Строки банковской выписки',
        bi_reports: 'Аналитические витрины',
        reconciliation_runs: 'Прогоны сверки',
        approval: 'Согласование',
        edo_certificate: 'Сертификат ЭДО',
        accounting_edo_operator: 'Оператор ЭДО',
        accounting_external_submission: 'Отправка отчётности',
        document_package: 'Пакет документов',
        saved_report: 'Сохранённый отчёт',
    };
    const raw = String(value || '').trim();
    if (labels[raw]) return labels[raw];
    return /^[a-z0-9_]+$/i.test(raw) ? 'Системный объект' : (raw || 'Сущность');
}

function operationsEventTitleLabel(value) {
    const raw = String(value || '').trim();
    const labels = {
        approval_action_applied: 'Выполнено действие по согласованию',
        approval_created: 'Создано согласование',
        edo_certificate_created: 'Добавлен сертификат ЭДО',
        accounting_edo_operator_created: 'Добавлен оператор ЭДО',
        accounting_external_submission_created: 'Отчёт отправлен во внешний контур',
        accounting_external_submission_retried: 'Повторная отправка отчёта',
        accounting_external_submission_synced: 'Обновлён статус отчёта',
        document_package_created: 'Собран пакет документов',
        document_package_sent_to_approval: 'Пакет отправлен на согласование',
        document_package_signed: 'Пакет документов подписан',
        login_success: 'Выполнен вход в систему',
        project_created: 'Создан проект',
        project_updated: 'Обновлён проект',
        production_order_created: 'Создан производственный заказ',
        finance_payment_created: 'Создан платёж',
        sales_document_created: 'Создан документ продажи',
        inventory_document_created: 'Создан складской документ',
        stock_movement_created: 'Зарегистрировано складское движение',
        saved_report_created: 'Создан сохранённый отчёт',
    };
    if (labels[raw]) return labels[raw];
    return /^[a-z0-9_]+$/i.test(raw) ? 'Системное событие' : (raw || 'Событие');
}

function integrationIssueLabel(value) {
    const labels = {
        mismatch: 'расхождение',
        missing_local: 'нет локальной записи',
        missing_queue: 'нет записи в очереди обмена',
        missing_external_id: 'не присвоен внешний идентификатор',
        no_sync_trace: 'нет записи об обмене',
        stale: 'зависшая запись',
        failed: 'ошибка обмена',
        conflict: 'конфликт данных',
        status: 'статус',
        warehouse: 'склад',
        serial_no: 'серийный номер',
        fulfilled_qty: 'исполненное количество',
        qty: 'количество',
    };
    return labels[value] || String(value || 'расхождение').replace(/_/g, ' ');
}

function operationsModuleLabel(value) {
    const key = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    const labels = {
        finance: 'Финансы',
        warehouse: 'Склад',
        stock: 'Склад',
        production: 'Производство',
        integrations: 'Интеграции',
        integration: 'Интеграции',
        security: 'Безопасность',
        backup: 'Резервное копирование',
        documents: 'Документы',
        docflow: 'Документооборот',
        crm: 'CRM',
        telephony: 'Телефония',
        bank: 'Банк',
        accounting: 'Бухгалтерия',
        sales: 'Продажи',
        supply: 'Снабжение',
    };
    return labels[key] || 'Модуль системы';
}

function operationsJobLabel(value) {
    const key = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    const labels = {
        integration_sync_runner: 'Обмен с внешними системами',
        backup_runner: 'Резервное копирование',
        notification_runner: 'Уведомления',
        mail_sync_runner: 'Синхронизация почты',
        telephony_import_runner: 'Импорт звонков',
        analytics_refresh_runner: 'Обновление аналитики',
        recovery_runner: 'Восстановление данных',
    };
    return labels[key] || 'Фоновое задание';
}

function operationsSeverityLabel(value) {
    const key = String(value || '').trim().toLowerCase();
    return {
        critical: 'критичный',
        high: 'высокий',
        warning: 'предупреждение',
        medium: 'средний',
        low: 'низкий',
        info: 'информация',
    }[key] || 'требует внимания';
}

function operationsIntegrityCodeLabel(value) {
    const key = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    return {
        orphan_accounting_entries: 'Проводки без связанного документа',
        orphan_payments: 'Платежи без связанного основания',
        orphan_documents: 'Документы без карточки клиента',
        stale_locks: 'Зависшие блокировки',
        failed_sync: 'Ошибки обмена',
        missing_external_id: 'Нет внешнего идентификатора',
        duplicate_external_id: 'Дубли внешних идентификаторов',
    }[key] || 'Проверка целостности';
}

function integrityExampleLabel(example) {
    if (!example || typeof example !== 'object') return 'Пример записи требует проверки';
    const parts = [];
    const entity = integrationEntityLabel(example.entity_type || example.table || example.kind || '');
    if (entity && entity !== 'Сущность') parts.push(entity);
    const id = example.id || example.entity_id || example.row_id || example.document_id || example.project_id || '';
    if (id) parts.push(`#${id}`);
    const title = example.title || example.name || example.contract || example.client || example.external_id || '';
    if (title) parts.push(String(title).slice(0, 90));
    return parts.length ? parts.join(' · ') : 'Пример записи требует проверки';
}

function lockAgeLabel(lock) {
    const seconds = Math.max(0, Math.round(Date.now() / 1000) - Number(lock?.locked_at || 0));
    if (seconds < 60) return `${seconds} сек`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} мин`;
    return `${Math.floor(seconds / 3600)} ч`;
}

function formatOperationsDuration(seconds) {
    seconds = Number(seconds || 0);
    if (!seconds) return '0 мин';
    if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} мин`;
    return `${Math.floor(seconds / 3600)} ч`;
}

function normalizeCallText(call) {
    return String(call?.summary || '').trim();
}

function callTextHas(text, words) {
    const lower = String(text || '').toLowerCase();
    return words.some(word => lower.includes(word));
}

function analyzeTelephonyCall(call) {
    const text = normalizeCallText(call);
    const hasRecording = !!String(call?.recording_url || '').trim();
    const hasTranscript = /транскрипт|расшифров|клиент:|менеджер:/i.test(text) || text.length > 180;
    const isMissed = ['missed', 'failed'].includes(call?.status || '');
    const isShort = Number(call?.duration_sec || 0) > 0 && Number(call?.duration_sec || 0) < 30;
    const unlinked = !Number(call?.client_id || 0) && !Number(call?.project_id || 0);
    const riskWords = ['жалоб', 'претенз', 'срыв', 'дорого', 'не интересно', 'неинтересно', 'конкурент', 'отказ', 'проблем', 'не работает'];
    const interestWords = ['кп', 'коммерчес', 'счет', 'счёт', 'встреч', 'интерес', 'расчет', 'расчёт', 'тендер', 'пилот'];
    const hasRisk = callTextHas(text, riskWords);
    const hasInterest = callTextHas(text, interestWords);
    const flags = [];
    if (isMissed) flags.push('пропущен');
    if (!hasRecording) flags.push('нет записи');
    if (!hasTranscript) flags.push('нет расшифровки');
    if (unlinked) flags.push('не привязан');
    if (hasRisk) flags.push('риск');
    if (hasInterest) flags.push('интерес');
    let score = 100;
    if (isMissed) score -= 35;
    if (!hasRecording) score -= 15;
    if (!hasTranscript) score -= 20;
    if (unlinked) score -= 15;
    if (isShort) score -= 10;
    if (hasRisk) score -= 10;
    if (hasInterest) score += 5;
    score = Math.max(0, Math.min(100, score));
    let tone = 'stable';
    let nextAction = 'Зафиксировать итог и следующий шаг';
    if (isMissed) {
        tone = 'danger';
        nextAction = 'Перезвонить и назначить ответственного';
    } else if (hasRisk || unlinked || !hasTranscript) {
        tone = 'attention';
        nextAction = hasRisk ? 'Разобрать риск и поставить задачу' : 'Допривязать звонок и заполнить расшифровку';
    } else if (hasInterest) {
        tone = 'success';
        nextAction = 'Перевести в лид или запланировать повторный контакт';
    }
    return { score, tone, flags, nextAction, hasRecording, hasTranscript, hasRisk, hasInterest, unlinked };
}

function callIntelligenceBadgeClass(tone) {
    if (tone === 'danger') return 'status-overdue';
    if (tone === 'attention') return 'status-active';
    if (tone === 'success') return 'status-completed';
    return 'status-archived';
}

const TELEPHONY_CALL_CONTROL_START = '[KORDA_CALL_CONTROL]';
const TELEPHONY_CALL_CONTROL_END = '[/KORDA_CALL_CONTROL]';
const TELEPHONY_PROCESSING_LABELS = {
    new: 'Новый',
    processing: 'Распознается',
    transcribed: 'Расшифрован',
    needs_review: 'Нужна проверка',
    processed: 'Обработан',
    follow_up: 'Повторный контакт',
    converted: 'Переведён дальше',
    lost: 'Потерян',
};
const TELEPHONY_RESULT_LABELS = {
    no_answer: 'Не дозвонились',
    interested: 'Есть интерес',
    not_interested: 'Не интересно',
    follow_up: 'Повторить контакт',
    meeting: 'Встреча',
    quote: 'Нужно КП',
    complaint: 'Жалоба / риск',
    wrong_contact: 'Не тот контакт',
    converted: 'Переведён в лид/сделку',
};

function stripTelephonyControlBlock(summary) {
    const text = String(summary || '');
    const start = text.indexOf(TELEPHONY_CALL_CONTROL_START);
    const end = text.indexOf(TELEPHONY_CALL_CONTROL_END);
    if (start < 0 || end < start) return text.trim();
    return `${text.slice(0, start)}${text.slice(end + TELEPHONY_CALL_CONTROL_END.length)}`.trim();
}

function parseTelephonyControl(summary) {
    const text = String(summary || '');
    const start = text.indexOf(TELEPHONY_CALL_CONTROL_START);
    const end = text.indexOf(TELEPHONY_CALL_CONTROL_END);
    if (start < 0 || end < start) return {};
    const raw = text.slice(start + TELEPHONY_CALL_CONTROL_START.length, end).trim();
    try {
        const payload = JSON.parse(raw);
        return payload && typeof payload === 'object' ? payload : {};
    } catch (_) {
        return {};
    }
}

function telephonyProcessingBadgeClass(status) {
    if (['processed', 'converted', 'transcribed'].includes(status)) return 'status-completed';
    if (['needs_review', 'follow_up'].includes(status)) return 'status-active';
    if (status === 'lost') return 'status-overdue';
    return 'status-archived';
}

function telephonyManagerErrorsCount(summary) {
    const match = String(summary || '').match(/Ошибки менеджера:\s*([\s\S]*)/i);
    if (!match) return 0;
    const block = match[1].split(TELEPHONY_CALL_CONTROL_START)[0] || '';
    if (/Критичных ошибок не найдено/i.test(block)) return 0;
    return block.split('\n').filter(line => line.trim().startsWith('-')).length;
}

function buildTelephonyControlBlock(payload) {
    const control = {
        manager_name: String(payload.manager_name || '').trim(),
        processing_status: String(payload.processing_status || 'new').trim(),
        call_result: String(payload.call_result || '').trim(),
        next_action: String(payload.next_action || '').trim(),
        manager_comment: String(payload.manager_comment || '').trim(),
        updated_at: new Date().toLocaleString('ru-RU'),
    };
    return `${TELEPHONY_CALL_CONTROL_START}${JSON.stringify(control)}${TELEPHONY_CALL_CONTROL_END}`;
}

function buildTelephonySummaryWithControl(summary, payload) {
    const clean = stripTelephonyControlBlock(summary);
    return [clean, buildTelephonyControlBlock(payload)].filter(Boolean).join('\n\n');
}

function renderOperationsCallIntelligence() {
    const mount = document.getElementById('operationsCallIntelligenceMount');
    if (!mount) return;
    const calls = Array.isArray(telephonyCallsOpsDB) ? telephonyCallsOpsDB : [];
    const analyzed = calls.map(call => ({ call, analysis: analyzeTelephonyCall(call) }));
    const recorded = analyzed.filter(item => item.analysis.hasRecording).length;
    const transcribed = analyzed.filter(item => item.analysis.hasTranscript).length;
    const processed = calls.filter(item => ['processed', 'converted'].includes(parseTelephonyControl(item.summary).processing_status || '')).length;
    const needsReview = calls.filter(item => (parseTelephonyControl(item.summary).processing_status || '') === 'needs_review').length;
    const managerErrors = calls.reduce((sum, item) => sum + telephonyManagerErrorsCount(item.summary), 0);
    const risky = analyzed.filter(item => item.analysis.tone === 'danger' || item.analysis.hasRisk).length;
    const unlinked = analyzed.filter(item => item.analysis.unlinked).length;
    const avgScore = analyzed.length ? Math.round(analyzed.reduce((sum, item) => sum + item.analysis.score, 0) / analyzed.length) : 0;
    const priorityCalls = analyzed
        .sort((a, b) => a.analysis.score - b.analysis.score)
        .slice(0, 6);
    mount.innerHTML = `
        <section class="ops-intelligence-card">
            <div class="section-header">
                <div>
                    <h3 class="section-title">ИИ-анализ звонков</h3>
                    <p class="section-subtitle">Запись, голос в текст, качество фиксации разговора и сигналы для руководителя.</p>
                </div>
                <span class="ops-section-chip">ИИ-контроль</span>
            </div>
            <div class="ops-intelligence-metrics">
                <div><span>Звонков</span><strong>${calls.length}</strong></div>
                <div><span>С записью</span><strong>${recorded}</strong></div>
                <div><span>Расшифровано</span><strong>${transcribed}</strong></div>
                <div><span>Обработано</span><strong>${processed}</strong></div>
                <div><span>Проверить</span><strong>${needsReview}</strong></div>
                <div><span>Ошибки менеджеров</span><strong>${managerErrors}</strong></div>
                <div><span>Риски</span><strong>${risky}</strong></div>
                <div><span>Без привязки</span><strong>${unlinked}</strong></div>
                <div><span>Качество</span><strong>${avgScore}%</strong></div>
            </div>
            <div class="ops-intelligence-list">
                ${priorityCalls.length ? priorityCalls.map(({ call, analysis }) => `
                    <div class="ops-intelligence-item">
                        <div>
                            <strong>${enterpriseEscape(call.contact_name || call.phone_number || 'Звонок')}</strong>
                            <span>${enterpriseEscape(call.client_name || 'Клиент не определён')} · ${enterpriseEscape(call.line_name || 'без линии')} · ${formatOperationsDuration(call.duration_sec)}</span>
                            <em>${enterpriseEscape(analysis.nextAction)}</em>
                            <small>${analysis.flags.length ? analysis.flags.map(enterpriseEscape).join(' · ') : 'данные заполнены'}</small>
                        </div>
                        <span class="status-badge ${callIntelligenceBadgeClass(analysis.tone)}">${analysis.score}%</span>
                    </div>
                `).join('') : '<div class="empty-state">Звонков для анализа пока нет. Добавь запись или импортируй журнал телефонии.</div>'}
            </div>
        </section>
    `;
}

function renderTelephonyImportResult() {
    const mount = document.getElementById('telephonyImportResult');
    if (!mount) return;
    const payload = telephonyImportResultCache;
    if (!payload) {
        mount.innerHTML = '';
        return;
    }
    const rows = Array.isArray(payload.results) ? payload.results : [];
    mount.innerHTML = `
        <section class="ops-intelligence-card telephony-import-result-card">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Результат распознавания записей</h3>
                    <p class="section-subtitle">Создано ${payload.created || 0}, ошибок ${payload.failed || 0}, всего файлов ${payload.total || rows.length || 0}.</p>
                </div>
                <span class="ops-section-chip">ИИ-анализ</span>
            </div>
            <div class="ops-intelligence-list">
                ${rows.length ? rows.map(item => {
                    const ok = item.status === 'success';
                    const duplicate = item.status === 'duplicate';
                    const errors = Array.isArray(item.manager_errors) ? item.manager_errors : [];
                    const dialog = Array.isArray(item.dialog) ? item.dialog : [];
                    return `
                        <div class="ops-intelligence-item telephony-import-result-row">
                            <div>
                                <strong>${enterpriseEscape(item.filename || 'recording')}</strong>
                                <span>${ok ? `Звонок #${item.call_id || 0} · ${enterpriseEscape(item.manager_name || 'менеджер не указан')} · ${TELEPHONY_PROCESSING_LABELS[item.processing_status] || 'Расшифрован'} · ${TELEPHONY_RESULT_LABELS[item.call_result] || telephonyDealSignalLabel(item.deal_signal) || 'нужно уточнить'} · роли ${Math.round(Number(item.role_confidence || 0) * 100)}% · текст ${Math.round(Number(item.transcription_confidence || 0) * 100)}%` : duplicate ? `Такая запись уже есть в журнале · звонок #${item.call_id || 0}` : enterpriseEscape(telephonyImportErrorLabel(item.error || 'ошибка'))}</span>
                                <em>${enterpriseEscape(item.summary || item.details || 'Подробности не получены')}</em>
                                <small>${errors.length ? errors.map(err => `${err.type || 'ошибка'}: ${err.recommendation || ''}`).join(' · ') : (ok ? 'Критичных ошибок менеджера не найдено' : '')}</small>
                                ${dialog.length ? `<small>${dialog.slice(0, 3).map(row => `${row.speaker === 'manager' ? 'Менеджер' : row.speaker === 'customer' ? 'Клиент' : 'Не определено'}: ${row.text || ''}`).join(' / ')}</small>` : ''}
                            </div>
                            <span class="status-badge ${ok || duplicate ? 'status-completed' : item.status === 'processing' ? 'status-active' : 'status-overdue'}">${ok ? 'готово' : duplicate ? 'уже загружено' : item.status === 'processing' ? 'идёт анализ' : 'ошибка'}</span>
                        </div>
                    `;
                }).join('') : '<div class="empty-state">Результатов импорта пока нет.</div>'}
            </div>
        </section>
    `;
}

function telephonyDealSignalLabel(value) {
    return {
        cold: 'холодный',
        neutral: 'нейтральный',
        warm: 'тёплый',
        hot: 'горячий',
        risk: 'риск',
    }[String(value || '').trim()] || '';
}

function telephonyImportErrorLabel(value) {
    return {
        unsupported_audio_format: 'неподдерживаемый формат файла',
        empty_file: 'пустой файл',
        file_too_large: 'файл слишком большой',
        invalid_audio_content: 'содержимое файла не похоже на аудиозапись',
        too_many_files: 'за один раз можно загрузить не более 20 файлов',
        gemini_unavailable: 'ИИ-сервис временно недоступен',
        import_failed: 'не удалось загрузить файл',
        forbidden: 'нет прав на загрузку звонков',
        no_files: 'файлы не выбраны',
    }[String(value || '').trim()] || 'не удалось распознать файл';
}

function promoteOperationsTelephonyPanel() {
    // The operations workspace now has explicit tabs, so sections keep their
    // stable DOM position instead of being moved during every render.
}

window.setOperationsTab = function(tabName, updateHash = true) {
    const view = document.getElementById('operationsView');
    if (!view) return;
    const allowed = new Set(['calls', 'exchange', 'bank', 'reliability', 'reports']);
    const target = allowed.has(tabName) ? tabName : 'calls';
    window.__operationsActiveTab = target;
    view.querySelectorAll('[data-operations-tab]').forEach(button => {
        const active = button.dataset.operationsTab === target;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    view.querySelectorAll('[data-operations-panel]').forEach(panel => {
        const active = panel.dataset.operationsPanel === target;
        panel.hidden = !active;
        panel.classList.toggle('is-active', active);
    });
    if (updateHash) {
        try { sessionStorage.setItem('korda_operations_tab', target); } catch (error) {}
    }
};

async function renderOperationsCenter() {
    await loadOperationsCenterData();
    promoteOperationsTelephonyPanel();
    renderOperationsRoleWorkbench();
    toggleRoleSecondarySections('operationsView', !!window.__operationsSecondaryExpanded);
    const cockpitTarget = document.getElementById('operationsCockpitMount');
    const integrationList = document.getElementById('operationsIntegrationList');
    const reconciliationList = document.getElementById('operationsReconciliationList');
    const locksList = document.getElementById('operationsLocksList');
    const bankList = document.getElementById('operationsBankList');
    const telephonyList = document.getElementById('operationsTelephonyList');
    const reportsList = document.getElementById('operationsReportsList');
    const reliabilityList = document.getElementById('operationsReliabilityList');
    const runtimeList = document.getElementById('operationsRuntimeList');
    const eventStreamList = document.getElementById('operationsEventStreamList');
    if (!integrationList) return;
    renderTelephonyImportResult();

    const renderList = (items, mapFn, emptyText) => (
        items && items.length ? items.map(mapFn).join('') : `<div class="empty-state">${emptyText}</div>`
    );

    const monitoringMetrics = operationsMonitoringDB?.integration?.metrics || {};
    const healthRows = operationsMonitoringDB?.integration?.entity_health || [];
    if (cockpitTarget) {
        const reliabilityMetrics = operationsReliabilityDB?.metrics || {};
        const mismatchTotal = reconciliationRunsDB.reduce((sum, run) => sum + Number(run.mismatch_count || 0), 0);
        cockpitTarget.innerHTML = `
            <section class="operations-section operations-exchange-summary">
                <div class="erp-cockpit-heading">
                    <div>
                        <h2 class="section-title">Состояние обмена с 1С</h2>
                        <p class="section-subtitle">Главные показатели текущей синхронизации.</p>
                    </div>
                </div>
                <div class="erp-cockpit-stats">
                    <div class="erp-cockpit-stat">
                        <div class="erp-cockpit-label">Ждут отправки</div>
                        <div class="erp-cockpit-value">${monitoringMetrics.queued || 0}</div>
                    </div>
                    <div class="erp-cockpit-stat">
                        <div class="erp-cockpit-label">Ошибки</div>
                        <div class="erp-cockpit-value">${monitoringMetrics.failed || 0}</div>
                    </div>
                    <div class="erp-cockpit-stat">
                        <div class="erp-cockpit-label">Зависшие записи</div>
                        <div class="erp-cockpit-value">${monitoringMetrics.stale_processing || 0}</div>
                    </div>
                    <div class="erp-cockpit-stat">
                        <div class="erp-cockpit-label">Расхождения</div>
                        <div class="erp-cockpit-value">${mismatchTotal}</div>
                    </div>
                </div>
            </section>
        `;
    }
    integrationList.innerHTML = `
        <div class="client360-item">
            <div>
                <div class="client360-item-title">Очередь 1С</div>
                <div class="client360-item-meta">в очереди ${monitoringMetrics.queued || 0} · повтор ${monitoringMetrics.retry || 0} · обработка ${monitoringMetrics.processing || 0}</div>
            </div>
            <div class="client360-item-side">${monitoringMetrics.failed || 0} ошибок</div>
        </div>
        <div class="client360-item">
            <div>
                <div class="client360-item-title">Состояние восстановления</div>
                <div class="client360-item-meta">зависло ${monitoringMetrics.stale_processing || 0} · всего ${monitoringMetrics.total || 0}</div>
            </div>
            <div class="client360-item-side">${monitoringMetrics.conflict || 0} конфликтов</div>
        </div>
        ${renderList(healthRows.slice(0, 8), item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${integrationEntityLabel(item.entity_type)}</div>
                    <div class="client360-item-meta">в очереди ${item.queued || 0} · повтор ${item.retry || 0} · обработка ${item.processing || 0}</div>
                </div>
                <div class="client360-item-side">${item.failed || 0} ошибок</div>
            </div>
        `, 'Очередь 1С сейчас спокойная.')}
    `;

    if (reconciliationList) {
        reconciliationList.innerHTML = renderList(reconciliationRunsDB.slice(0, 10), run => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">Прогон #${run.id} · ${new Date((run.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
                <div class="client360-item-meta">расхождений ${run.mismatch_count || 0} · ${run.created_by || 'система'}</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${Object.entries(run.summary?.entities || {}).slice(0, 6).map(([entityType, details]) => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${integrationEntityLabel(entityType)}</div>
                                <div class="client360-item-meta">строк ${details.rows || 0}</div>
                            </div>
                            <div class="client360-item-side">${details.mismatches || 0}</div>
                        </div>
                    `).join('') || '<div class="empty-state">Срезов пока нет.</div>'}
                </div>
                <div class="client360-list" style="margin-top:12px;">
                    ${(run.summary?.issues || []).slice(0, 6).map(issue => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${integrationEntityLabel(issue.entity_type)} · ${issue.entity_id || 'сущность'}</div>
                                <div class="client360-item-meta">${integrationIssueLabel(issue.issue)} · ${enterpriseStatusLabel(issue.state || 'draft')}</div>
                                <div class="client360-item-meta">${issue.last_error || issue.local_external_id || issue.queue_external_id || 'Нужно проверить карточку и очередь 1С'}</div>
                            </div>
                        </div>
                    `).join('') || '<div class="empty-state">Детальных конфликтов в этом прогоне нет.</div>'}
                </div>
            </div>
        `, 'Сверка 1С ещё не запускалась.');
    }

    if (locksList) {
        locksList.innerHTML = renderList(operationsMonitoringDB?.locks || [], item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${integrationEntityLabel(item.entity_type)} / ${item.entity_id}</div>
                    <div class="client360-item-meta">${item.actor_name || item.actor_email || 'пользователь'} · ${lockAgeLabel(item)}</div>
                </div>
                <div class="view-actions">
                    <span class="status-badge status-active">${item.session_id ? 'активна' : 'ручная'}</span>
                    <button class="btn-secondary" onclick="releaseOperationsLock('${item.entity_type}', '${item.entity_id}', 1)">Снять</button>
                </div>
            </div>
        `, 'Активных блокировок редактирования нет.');
    }

    if (bankList) {
        const accountsHtml = renderList(bankAccountsOpsDB.slice(0, 6), item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.name}</div>
                    <div class="client360-item-meta">${item.bank_name || 'Банк?'} · ${item.account_number || 'счёт не указан'}</div>
                </div>
                <div class="client360-item-side">${item.currency || 'RUB'}</div>
            </div>
        `, 'Банковских счетов пока нет.');
        const linesHtml = renderList(bankStatementLinesOpsDB.slice(0, 10), item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.counterparty || 'Контрагент не указан'}</div>
                    <div class="client360-item-meta">${item.bank_account_name || 'Без счёта'} · ${item.line_date || 'дата?'}</div>
                    <div class="client360-item-meta">${item.purpose || 'Назначение не указано'}</div>
                </div>
                <div class="view-actions">
                    <span class="client360-item-side">${formatMoney(item.amount || 0)}</span>
                    <button class="btn-secondary" onclick="reconcileOperationsBankLine(${item.id})">Свести</button>
                </div>
            </div>
        `, 'Непроведённых строк выписки нет.');
        bankList.innerHTML = `
            <div class="ops-inline-section">
                <div class="ops-inline-title">Счета</div>
                <div class="client360-list" style="margin-top:12px;">${accountsHtml}</div>
            </div>
            <div class="ops-inline-section" style="margin-top:16px;">
                <div class="ops-inline-title">Не сведённые строки</div>
                <div class="client360-list" style="margin-top:12px;">${linesHtml}</div>
            </div>
        `;
    }

    if (telephonyList) {
        const callsHtml = renderList(telephonyCallsOpsDB.slice(0, 10), item => {
            const analysis = analyzeTelephonyCall(item);
            const control = parseTelephonyControl(item.summary);
            const cleanSummary = stripTelephonyControlBlock(item.summary);
            const managerName = control.manager_name || item.created_by || 'менеджер не указан';
            const processingStatus = control.processing_status || (analysis.hasTranscript ? 'transcribed' : 'new');
            const resultLabel = TELEPHONY_RESULT_LABELS[control.call_result] || 'результат не указан';
            const nextAction = control.next_action || analysis.nextAction;
            const managerComment = control.manager_comment || '';
            const managerErrors = telephonyManagerErrorsCount(item.summary);
            return `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${enterpriseEscape(item.contact_name || item.phone_number || 'Звонок')}</div>
                    <div class="client360-item-meta">${enterpriseEscape(item.line_name || 'Без линии')} · ${operationsStateLabel(item.direction || 'inbound')} · ${item.call_at || 'время?'} · ${formatOperationsDuration(item.duration_sec)}</div>
                    <div class="client360-item-meta">Менеджер: ${enterpriseEscape(managerName)} · ${resultLabel} · ошибок менеджера: ${managerErrors}</div>
                    <div class="client360-item-meta">${enterpriseEscape(item.client_name || 'Клиент не определён')}${item.project_contract || item.project_name ? ` · ${enterpriseEscape(item.project_contract || item.project_name)}` : ''}</div>
                    <div class="client360-item-meta">${enterpriseEscape(cleanSummary || 'Итог пока не заполнен')}</div>
                    <div class="client360-item-meta">Следующий шаг: ${enterpriseEscape(nextAction || 'не задан')}</div>
                    ${managerComment ? `<div class="client360-item-meta">Комментарий: ${enterpriseEscape(managerComment)}</div>` : ''}
                    <div class="client360-item-meta">${item.recording_url ? 'Запись есть' : 'Без записи'} · ${analysis.hasTranscript ? 'расшифровка есть' : 'нет расшифровки'} · ${control.updated_at ? `контроль обновлён ${enterpriseEscape(control.updated_at)}` : 'контроль не обновлялся'}</div>
                    ${item.recording_url ? `<audio class="telephony-audio" controls preload="none" src="${enterpriseEscape(item.recording_url)}"></audio>` : ''}
                    ${cleanSummary ? `
                        <details class="telephony-analysis-details">
                            <summary>Расшифровка, роли и ошибки менеджера</summary>
                            <pre>${enterpriseEscape(cleanSummary)}</pre>
                        </details>
                    ` : ''}
                </div>
                <div class="view-actions">
                    <span class="status-badge ${telephonyProcessingBadgeClass(processingStatus)}">${TELEPHONY_PROCESSING_LABELS[processingStatus] || 'Новый'}</span>
                    <span class="status-badge ${callIntelligenceBadgeClass(analysis.tone)}">${analysis.score}%</span>
                    <span class="client360-item-side">${operationsStateLabel(item.status || 'answered')}</span>
                    <button class="btn-secondary" onclick="quickUpdateTelephonyCall(${Number(item.id || 0)}, 'processed')">Обработан</button>
                    <button class="btn-secondary" onclick="quickUpdateTelephonyCall(${Number(item.id || 0)}, 'follow_up')">Повтор</button>
                    <button class="btn-secondary" onclick="quickUpdateTelephonyCall(${Number(item.id || 0)}, 'needs_review')">Проверить</button>
                </div>
            </div>
        `;
        }, 'Журнал звонков пока пуст.');
        telephonyList.innerHTML = callsHtml;
        renderOperationsCallIntelligence();
    }

    if (reportsList) {
        reportsList.innerHTML = renderList(savedReportsOpsDB, item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item.title || 'Отчёт'}</div>
                    <div class="client360-item-meta">${enterpriseReportTypeLabel(item.report_type || 'finance_analytics')} · ${item.scope === 'shared' ? 'общий' : 'личный'} · ${enterpriseDashboardKindLabel(item.layout?.dashboard_kind || 'table')}</div>
                    <div class="client360-item-meta">${item.layout?.target_role || 'для всех ролей'}${(item.layout?.tags || []).length ? ` · ${(item.layout.tags || []).join(', ')}` : ''}</div>
                </div>
                <div class="view-actions">
                    <button class="btn-secondary" onclick="runOperationsSavedReport(${item.id})">Запустить</button>
                    <button class="btn-secondary" onclick="exportOperationsSavedReport(${item.id})">Экспорт</button>
                    <button class="btn-danger" onclick="deleteOperationsSavedReport(${item.id})">Удалить</button>
                </div>
            </div>
        `, 'Сохранённых операционных отчётов пока нет.');
    }

    if (reliabilityList) {
        const moduleHealth = operationsReliabilityDB?.module_health || [];
        const integrityIssues = operationsReliabilityDB?.integrity_issues || [];
        const recovery = operationsReliabilityDB?.recovery || {};
        reliabilityList.innerHTML = `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">Общая надёжность</div>
                    <div class="client360-item-meta">критичных ${operationsReliabilityDB?.metrics?.critical_issues || 0} · предупреждений ${operationsReliabilityDB?.metrics?.warning_issues || 0} · недавних ошибок ${operationsReliabilityDB?.metrics?.recent_errors || 0}</div>
                </div>
                <div class="client360-item-side">${operationsReliabilityDB?.metrics?.failed_sync || 0} ошибок</div>
            </div>
            ${renderList(moduleHealth, item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${operationsModuleLabel(item.module)}</div>
                        <div class="client360-item-meta">${enterpriseEscape(item.summary || 'Без деталей')}</div>
                    </div>
                    <div class="client360-item-side">${item.status === 'ok' ? 'в норме' : operationsSeverityLabel(item.status)}</div>
                </div>
            `, 'Проверки состояния модулей пока пусты.')}
            ${renderList(integrityIssues, item => `
                <div class="client360-item client360-item--stack">
                    <div class="client360-item-title">${enterpriseEscape(item.message || operationsIntegrityCodeLabel(item.code))}</div>
                    <div class="client360-item-meta">${operationsIntegrityCodeLabel(item.code)} · уровень ${operationsSeverityLabel(item.severity)} · количество ${item.count}</div>
                    <div class="client360-list" style="margin-top:8px;">
                        ${(item.examples || []).slice(0, 3).map(example => `
                        <div class="client360-item">
                                <div class="client360-item-meta">${enterpriseEscape(integrityExampleLabel(example))}</div>
                            </div>
                        `).join('') || '<div class="empty-state">Без примеров.</div>'}
                    </div>
                </div>
            `, 'Проблем целостности пока не найдено.')}
            ${renderList((recovery.stale_locks || []).slice(0, 4), item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">Зависшая блокировка · ${item.entity_type}/${item.entity_id}</div>
                        <div class="client360-item-meta">${item.actor_name || item.actor_email || 'пользователь'} · ${lockAgeLabel(item)}</div>
                    </div>
                </div>
            `, 'Зависших блокировок нет.')}
            ${renderList((recovery.recent_failures || []).slice(0, 4), item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${integrationEntityLabel(item.entity_type)} · ${item.entity_key || item.external_id || item.entity_id}</div>
                        <div class="client360-item-meta">${item.last_error || 'Нужно повторить обмен'}</div>
                    </div>
                </div>
            `, 'Сбойных обменов сейчас нет.')}
        `;
    }

    if (runtimeList) {
        const db = operationsRuntimeDB?.database || {};
        const jobRuns = operationsRuntimeDB?.background_jobs || [];
        const recoveryRuns = operationsRuntimeDB?.recovery_runs || [];
        const backups = operationsRuntimeDB?.backups || [];
        const policies = operationsRuntimeDB?.lock_policies || [];
        runtimeList.innerHTML = `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">База и миграции</div>
                    <div class="client360-item-meta">${databaseBackendLabel(db.backend)} · целостность ${databaseIntegrityLabel(db.integrity)} · журнал ${db.journal_mode || 'не указан'}</div>
                    <div class="client360-item-meta">применено ${db.migrations_applied || 0} · ожидает ${db.migrations_pending || 0} · размер ${formatMoney(db.estimated_size_bytes || 0, '', 0)} байт</div>
                </div>
                <div class="client360-item-side">${db.stale_locks || 0} зависло</div>
            </div>
            <div class="ops-inline-section" style="margin-top:16px;">
                <div class="ops-inline-title">Фоновые задания</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${renderList(jobRuns.slice(0, 8), item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${operationsJobLabel(item.job_name)}</div>
                                <div class="client360-item-meta">${jobGroupLabel(item.job_group)} · ${jobStatusLabel(item.status)}</div>
                                <div class="client360-item-meta">последний сигнал ${new Date(Number(item.heartbeat_at || 0) * 1000).toLocaleString('ru-RU')}</div>
                            </div>
                            <div class="client360-item-side">${Number(item.is_stale || 0) === 1 ? 'зависло' : 'активно'}</div>
                        </div>
                    `, 'Фоновых заданий пока нет.')}
                </div>
            </div>
            <div class="ops-inline-section" style="margin-top:16px;">
                <div class="ops-inline-title">Сценарии восстановления</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${renderList(recoveryRuns.slice(0, 8), item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${recoveryActionLabel(item.action_name)}</div>
                                <div class="client360-item-meta">${item.actor_email || 'система'} · ${recoveryRunStatusLabel(item.status)} · ${item.target_scope || 'общий контур'}</div>
                            </div>
                            <div class="client360-item-side">#${item.id}</div>
                        </div>
                    `, 'Сценарии восстановления пока пусты.')}
                </div>
            </div>
            <div class="ops-inline-section" style="margin-top:16px;">
                <div class="ops-inline-title">Политика блокировок и резервные копии</div>
                <div class="client360-list" style="margin-top:12px;">
                    ${renderList(policies.slice(0, 6), item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${integrationEntityLabel(item.entity_type)}</div>
                                <div class="client360-item-meta">срок жизни ${item.ttl_seconds || 0} сек · риск ${riskLabel(item.risk)}</div>
                            </div>
                        </div>
                    `, 'Политики блокировок пока не заданы.')}
                    ${renderList(backups.slice(0, 4), item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${item.filename || 'резервная копия'}</div>
                                <div class="client360-item-meta">${item.actor_email || 'система'} · ${new Date(Number(item.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
                            </div>
                        </div>
                    `, 'Резервных копий пока нет.')}
                </div>
            </div>
        `;
    }

    if (eventStreamList) {
        eventStreamList.innerHTML = renderList(operationsEventStreamDB.slice(0, 20), item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${enterpriseEscape(operationsEventTitleLabel(item.title))}</div>
                <div class="client360-item-meta">${enterpriseEscape(integrationEntityLabel(item.entity_type) || 'система')} · ${enterpriseEscape(item.entity_id || '')} · ${new Date(Number(item.timestamp || 0) * 1000).toLocaleString('ru-RU')}</div>
                <div class="client360-item-meta">${enterpriseEscape(item.actor_name || item.actor_email || 'система')}</div>
                <div class="client360-item-meta">${enterpriseEscape((item.message || '').slice(0, 220))}</div>
            </div>
        `, 'Событий пока нет.');
    }
    let savedOperationsTab = window.__operationsActiveTab;
    if (!savedOperationsTab) {
        try { savedOperationsTab = sessionStorage.getItem('korda_operations_tab'); } catch (error) {}
    }
    setOperationsTab(savedOperationsTab || 'calls', false);
}

window.reloadOperationsCenter = async function() {
    await renderOperationsCenter();
    showToast('Операционный центр', 'Операционный центр обновлён');
};

window.runSystemRecoveryAction = async function(actionName) {
    const res = await apiCall('/system/recovery/run', 'POST', {
        action_name: actionName,
        older_than_minutes: 15,
        stale_only: 1,
        force_failed: actionName === 'recover_sync_queue' ? 1 : 0,
    });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось запустить восстановление системы.');
    await renderOperationsCenter();
    showToast('Восстановление', `${recoveryActionLabel(actionName)}: затронуто ${Number(res.affected || 0)}`);
};

window.runOperationsReconciliation = async function() {
    const res = await apiCall('/integration/1c/reconciliation/run', 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось запустить сверку 1С.');
    await renderOperationsCenter();
    showToast('1С', `Сверка выполнена, расхождений: ${Number(res.mismatch_count || 0)}`);
};

window.saveBankAccount = async function() {
    const payload = {
        name: (document.getElementById('bankAccountName')?.value || '').trim(),
        bank_name: (document.getElementById('bankAccountBankName')?.value || '').trim(),
        account_number: (document.getElementById('bankAccountNumber')?.value || '').trim(),
        bik: (document.getElementById('bankAccountBik')?.value || '').trim(),
        currency: 'RUB',
        legal_entity_id: 0,
        is_active: 1,
    };
    if (!payload.name || !payload.bank_name) return customAlert('Укажи название счёта и банк.');
    const res = await apiCall('/banking/accounts', 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить банковский счёт.');
    ['bankAccountName', 'bankAccountBankName', 'bankAccountNumber', 'bankAccountBik'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    await renderOperationsCenter();
    showToast('Банк', 'Банковский счёт сохранён');
};

window.importBankStatementLines = async function() {
    const raw = (document.getElementById('bankStatementImportPayload')?.value || '').trim();
    if (!raw) return customAlert('Вставь JSON-массив строк выписки.');
    let lines = [];
    try {
        lines = JSON.parse(raw);
    } catch (err) {
        return customAlert('JSON выписки не разобрался. Проверь формат массива.');
    }
    if (!Array.isArray(lines) || !lines.length) return customAlert('Нужен непустой массив строк выписки.');
    const accountId = Number(bankAccountsOpsDB[0]?.id || 0);
    if (!accountId) return customAlert('Сначала создай хотя бы один банковский счёт.');
    const res = await apiCall('/banking/statements/import', 'POST', { bank_account_id: accountId, lines });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось импортировать выписку.');
    const el = document.getElementById('bankStatementImportPayload');
    if (el) el.value = '';
    await renderOperationsCenter();
    showToast('Банк', `Импортировано строк: ${Number(res.created || 0)}`);
};

window.reconcileOperationsBankLine = async function(lineId) {
    const res = await apiCall(`/banking/statements/${lineId}/reconcile`, 'POST', { payment_id: 0 });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось свести строку выписки.');
    await renderOperationsCenter();
    if (typeof renderFinance === 'function' && document.getElementById('financeView')?.style.display === 'block') {
        await renderFinance();
    }
    showToast('Банк', `Строка сводена с оплатой #${res.payment_id}`);
};

window.saveTelephonyAccount = async function() {
    const payload = {
        line_name: (document.getElementById('telephonyLineName')?.value || '').trim(),
        provider_name: (document.getElementById('telephonyProvider')?.value || '').trim(),
        external_line_id: '',
        is_active: 1,
    };
    if (!payload.line_name || !payload.provider_name) return customAlert('Укажи линию и провайдера.');
    const res = await apiCall('/telephony/accounts', 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить линию телефонии.');
    await renderOperationsCenter();
    showToast('Телефония', 'Линия сохранена');
};

window.prepareTelephonyDemoCall = function() {
    const values = {
        telephonyLineName: 'Отдел продаж',
        telephonyProvider: 'Mango / demo',
        telephonyManagerName: currentUser?.name || 'Анна менеджер',
        telephonyContactName: 'Ирина Орлова',
        telephonyPhone: '+7 927 333-78-90',
        telephonyDirection: 'inbound',
        telephonyCallStatus: 'answered',
        telephonyDurationSec: '352',
        telephonyCallSummary: 'Клиент запросил КП по шумозащитным кожухам, интерес к пилотному проекту, нужен расчет до пятницы.',
        telephonyRecordingUrl: 'https://telephony.example.local/records/korda-demo-001.mp3',
        telephonyProcessingStatus: 'transcribed',
        telephonyCallResult: 'quote',
        telephonyNextAction: 'Подготовить КП и запланировать повторный контакт на пятницу',
        telephonyManagerComment: 'Клиент тёплый, просит быстро дать срок и цену.',
        telephonyTranscript: 'Менеджер: Добрый день, компания Korda. Клиент: Нужен расчет по шумозащитным кожухам, бюджет около 3 млн, интересует срок и КП. Менеджер: Зафиксирую задачу и подготовлю предложение. Клиент: Жду до пятницы, если цена пройдет, готовы обсуждать пилот.',
    };
    Object.entries(values).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    showToast('Телефония', 'Демо-звонок подготовлен. Нажми «Звонок», чтобы сохранить.');
};

function setTelephonySpeechStatus(text, active = false) {
    const status = document.getElementById('telephonySpeechStatus');
    const startBtn = document.getElementById('telephonySpeechStartBtn');
    const stopBtn = document.getElementById('telephonySpeechStopBtn');
    if (status) {
        status.textContent = text;
        status.classList.toggle('is-active', !!active);
    }
    if (startBtn) startBtn.disabled = !!active;
    if (stopBtn) stopBtn.disabled = !active;
}

window.startTelephonySpeechRecognition = function() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        customAlert('В этом браузере нет Web Speech Recognition. Открой CRM в Chrome или подключи серверный speech-to-text для записей.');
        return;
    }
    const transcriptEl = document.getElementById('telephonyTranscript');
    if (!transcriptEl) return customAlert('Поле расшифровки не найдено.');
    if (telephonySpeechRecognition) {
        try { telephonySpeechRecognition.stop(); } catch (_) {}
        telephonySpeechRecognition = null;
    }
    telephonySpeechBaseText = String(transcriptEl.value || '').trim();
    const recognition = new SpeechRecognition();
    recognition.lang = 'ru-RU';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onstart = () => setTelephonySpeechStatus('Распознаёт голос...', true);
    recognition.onerror = event => {
        const message = event?.error === 'not-allowed'
            ? 'Нет доступа к микрофону'
            : `Ошибка распознавания: ${event?.error || 'unknown'}`;
        setTelephonySpeechStatus(message, false);
    };
    recognition.onend = () => {
        telephonySpeechRecognition = null;
        setTelephonySpeechStatus('Распознавание остановлено', false);
    };
    recognition.onresult = event => {
        let finalText = '';
        let interimText = '';
        for (let i = 0; i < event.results.length; i += 1) {
            const result = event.results[i];
            const text = String(result?.[0]?.transcript || '').trim();
            if (!text) continue;
            if (result.isFinal) finalText += `${text}. `;
            else interimText += `${text} `;
        }
        const parts = [telephonySpeechBaseText, finalText.trim(), interimText.trim()].filter(Boolean);
        transcriptEl.value = parts.join('\n');
    };
    telephonySpeechRecognition = recognition;
    recognition.start();
};

window.stopTelephonySpeechRecognition = function() {
    if (!telephonySpeechRecognition) {
        setTelephonySpeechStatus('Распознавание не запущено', false);
        return;
    }
    try {
        telephonySpeechRecognition.stop();
    } catch (_) {
        telephonySpeechRecognition = null;
        setTelephonySpeechStatus('Распознавание остановлено', false);
    }
};

window.openTelephonyFilePicker = function() {
    const input = document.getElementById('telephonyRecordingFiles');
    if (input) input.click();
};

window.updateTelephonyFileSelection = function() {
    const input = document.getElementById('telephonyRecordingFiles');
    const status = document.getElementById('telephonyFileSelectionStatus');
    const panel = document.querySelector('.telephony-upload-panel');
    const files = Array.from(input?.files || []);
    if (panel) panel.classList.toggle('telephony-upload-panel--attention', false);
    if (!status) return;
    if (!files.length) {
        status.textContent = 'Файлы не выбраны';
        status.classList.remove('is-ready');
        return;
    }
    const names = files.slice(0, 2).map(file => file.name).join(', ');
    const tail = files.length > 2 ? ` и ещё ${files.length - 2}` : '';
    status.textContent = `Выбрано: ${files.length} · ${names}${tail}`;
    status.classList.add('is-ready');
};

window.importTelephonyRecordings = async function() {
    const input = document.getElementById('telephonyRecordingFiles');
    const files = Array.from(input?.files || []);
    if (!files.length) {
        const panel = document.querySelector('.telephony-upload-panel');
        const status = document.getElementById('telephonyFileSelectionStatus');
        if (panel) panel.classList.add('telephony-upload-panel--attention');
        if (status) {
            status.textContent = 'Сначала выбери записи звонков';
            status.classList.remove('is-ready');
        }
        if (input) input.click();
        return;
    }
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    formData.append('line_name', (document.getElementById('telephonyLineName')?.value || 'Bitrix24').trim() || 'Bitrix24');
    formData.append('provider_name', (document.getElementById('telephonyProvider')?.value || 'Bitrix24').trim() || 'Bitrix24');
    formData.append('contact_name', (document.getElementById('telephonyContactName')?.value || '').trim());
    formData.append('phone_number', (document.getElementById('telephonyPhone')?.value || '').trim());
    formData.append('direction', document.getElementById('telephonyDirection')?.value || 'inbound');
    formData.append('manager_name', (document.getElementById('telephonyManagerName')?.value || currentUser?.name || '').trim());
    formData.append('manager_comment', (document.getElementById('telephonyManagerComment')?.value || '').trim());
    telephonyImportResultCache = {
        created: 0,
        failed: 0,
        total: files.length,
        results: files.map(file => ({ filename: file.name, status: 'processing', summary: 'Файл отправлен на распознавание...' })),
    };
    renderTelephonyImportResult();
    showToast('Телефония', `Отправлено файлов: ${files.length}`);
    const result = await apiCall('/telephony/calls/import_recordings', 'POST', formData);
    if (!result || result.error) {
        telephonyImportResultCache = {
            created: 0,
            failed: files.length,
            total: files.length,
            results: files.map(file => ({ filename: file.name, status: 'failed', error: result?.message || result?.error || 'import_failed' })),
        };
        renderTelephonyImportResult();
        return customAlert(result?.message || 'Не удалось распознать записи.');
    }
    telephonyImportResultCache = result;
    if (input) input.value = '';
    updateTelephonyFileSelection();
    await renderOperationsCenter();
    showToast('Телефония', `Распознано: ${result.created || 0}, ошибок: ${result.failed || 0}`);
};

window.quickUpdateTelephonyCall = async function(callId, processingStatus) {
    const call = telephonyCallsOpsDB.find(item => Number(item.id || 0) === Number(callId || 0));
    if (!call) return customAlert('Звонок не найден в текущем списке.');
    const control = parseTelephonyControl(call.summary);
    const payload = {
        manager_name: control.manager_name || currentUser?.name || call.created_by || '',
        processing_status: processingStatus || control.processing_status || 'processed',
        call_result: control.call_result || (processingStatus === 'follow_up' ? 'follow_up' : ''),
        next_action: control.next_action || (processingStatus === 'follow_up' ? 'Повторить контакт' : ''),
        manager_comment: control.manager_comment || '',
    };
    if (processingStatus === 'needs_review' && !payload.manager_comment) {
        payload.manager_comment = 'Нужна ручная проверка расшифровки или качества разговора.';
    }
    const res = await apiCall(`/telephony/calls/${Number(callId || 0)}/control`, 'PUT', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось обновить звонок.');
    await renderOperationsCenter();
    showToast('Телефония', 'Статус звонка обновлён');
};

window.saveTelephonyCall = async function() {
    const lineName = (document.getElementById('telephonyLineName')?.value || '').trim();
    const providerName = (document.getElementById('telephonyProvider')?.value || '').trim();
    let accountId = Number((telephonyAccountsOpsDB.find(item => item.line_name === lineName && item.provider_name === providerName) || {}).id || 0);
    if (!accountId && telephonyAccountsOpsDB.length === 1) {
        accountId = Number(telephonyAccountsOpsDB[0].id || 0);
    }
    if (!accountId && lineName && providerName) {
        const accountRes = await apiCall('/telephony/accounts', 'POST', {
            line_name: lineName,
            provider_name: providerName,
            external_line_id: '',
            is_active: 1,
        });
        if (!accountRes || accountRes.error) return customAlert(accountRes?.error || 'Не удалось сохранить линию телефонии.');
        accountId = Number(accountRes.id || 0);
    }
    const summary = (document.getElementById('telephonyCallSummary')?.value || '').trim();
    const transcript = (document.getElementById('telephonyTranscript')?.value || '').trim();
    const controlPayload = {
        manager_name: (document.getElementById('telephonyManagerName')?.value || currentUser?.name || '').trim(),
        processing_status: document.getElementById('telephonyProcessingStatus')?.value || (transcript ? 'transcribed' : 'new'),
        call_result: document.getElementById('telephonyCallResult')?.value || '',
        next_action: (document.getElementById('telephonyNextAction')?.value || '').trim(),
        manager_comment: (document.getElementById('telephonyManagerComment')?.value || '').trim(),
    };
    const baseSummary = [summary, transcript ? `Транскрипт: ${transcript}` : ''].filter(Boolean).join('\n\n');
    const payload = {
        account_id: accountId,
        client_id: 0,
        project_id: 0,
        contact_name: (document.getElementById('telephonyContactName')?.value || '').trim(),
        phone_number: (document.getElementById('telephonyPhone')?.value || '').trim(),
        direction: document.getElementById('telephonyDirection')?.value || 'inbound',
        status: document.getElementById('telephonyCallStatus')?.value || 'answered',
        duration_sec: Number(document.getElementById('telephonyDurationSec')?.value || 0) || 0,
        summary: buildTelephonySummaryWithControl(baseSummary, controlPayload),
        recording_url: (document.getElementById('telephonyRecordingUrl')?.value || '').trim(),
    };
    if (!payload.contact_name && !payload.phone_number) return customAlert('Укажи хотя бы контакт или телефон.');
    const res = await apiCall('/telephony/calls', 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить звонок.');
    if (telephonySpeechRecognition) {
        try { telephonySpeechRecognition.stop(); } catch (_) {}
        telephonySpeechRecognition = null;
    }
    ['telephonyContactName', 'telephonyPhone', 'telephonyDurationSec', 'telephonyCallSummary', 'telephonyRecordingUrl', 'telephonyNextAction', 'telephonyManagerComment', 'telephonyTranscript'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    setTelephonySpeechStatus('Ожидает запуска', false);
    await renderOperationsCenter();
    showToast('Телефония', 'Звонок сохранён');
};

window.saveOperationsReport = async function() {
    const tags = (document.getElementById('operationsReportTags')?.value || '')
        .split(',')
        .map(item => item.trim())
        .filter(Boolean);
    const targetRole = document.getElementById('operationsReportRole')?.value || '';
    const dimension = (document.getElementById('operationsReportDimension')?.value || '').trim();
    const payload = {
        title: (document.getElementById('operationsReportTitle')?.value || '').trim() || 'Управленческий отчёт',
        report_type: document.getElementById('operationsReportType')?.value || 'finance_analytics',
        scope: document.getElementById('operationsReportScope')?.value || 'private',
        filters: dimension ? { dimension, value: '', value_id: 0, limit: 40 } : {},
        layout: {
            target_role: targetRole,
            dashboard_kind: document.getElementById('operationsReportDashboardKind')?.value || 'table',
            tags,
            description: targetRole ? `Аналитика по роли ${targetRole}` : 'Сохранённый аналитический срез',
        },
    };
    const res = await apiCall('/analytics/reports', 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить отчёт.');
    const titleEl = document.getElementById('operationsReportTitle');
    if (titleEl) titleEl.value = '';
    ['operationsReportTags', 'operationsReportDimension'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    await renderOperationsCenter();
    showToast('Аналитика', 'Отчёт сохранён');
};

window.runOperationsSavedReport = async function(reportId) {
    const res = await apiCall(`/analytics/reports/${reportId}/run`, 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось выполнить отчёт.');
    const payload = res.payload || {};
    const preview = JSON.stringify(payload, null, 2).slice(0, 2500);
    await customAlert(`Отчёт: ${res.report?.title || reportId}\n\n${preview}`);
};

window.exportOperationsSavedReport = async function(reportId) {
    const res = await apiCall(`/analytics/reports/${reportId}/run`, 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось выгрузить отчёт.');
    downloadEnterpriseJson(res.payload || {}, `korda-report-${reportId}`);
    showToast('Аналитика', 'Отчёт выгружен в JSON');
};

window.deleteOperationsSavedReport = async function(reportId) {
    if (!(await customConfirm('Удалить сохранённый отчёт?'))) return;
    const res = await apiCall(`/analytics/reports/${reportId}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось удалить отчёт.');
    await renderOperationsCenter();
    showToast('Аналитика', 'Сохранённый отчёт удалён');
};

window.exportOperationsSnapshot = async function(kind) {
    let payload = {};
    let filePrefix = `korda-operations-${kind || 'snapshot'}`;
    if (kind === 'integration') {
        payload = operationsMonitoringDB?.integration || {};
    } else if (kind === 'reconciliation') {
        payload = reconciliationRunsDB || [];
    } else if (kind === 'bank') {
        payload = { accounts: bankAccountsOpsDB || [], lines: bankStatementLinesOpsDB || [] };
    } else if (kind === 'telephony') {
        payload = { accounts: telephonyAccountsOpsDB || [], calls: telephonyCallsOpsDB || [] };
    } else if (kind === 'reliability') {
        payload = operationsReliabilityDB || {};
    } else {
        payload = operationsMonitoringDB || {};
    }
    downloadEnterpriseJson(payload, filePrefix);
    showToast('Операционный центр', 'Снимок выгружен в JSON');
};

window.releaseOperationsLock = async function(entityType, entityId, force = 0) {
    const res = await apiCall('/locks/release', 'POST', { entity_type: entityType, entity_id: String(entityId), force: Number(force || 0) });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось снять блокировку.');
    await renderOperationsCenter();
    showToast('Операционный центр', 'Блокировка снята');
};
