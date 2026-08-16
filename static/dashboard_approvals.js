// ==========================================
// 4. СОГЛАСОВАНИЯ (БИЗНЕС-ПРОЦЕССЫ)
// ==========================================

let currentApprTab = 'pending';
let workflowDesignerOpen = false;
let workflowDesignerState = { nodes: [], edges: [] };
const approvalBulkSelection = window.approvalBulkSelection || new Set();
window.approvalBulkSelection = approvalBulkSelection;

function workflowEscape(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function isDesignOfficeApprovalRole() {
    const role = String(currentUser?.role || '').trim().toLowerCase();
    return role === 'конструкторское бюро' || role.includes('конструктор');
}

function approvalTextBlob(item = {}) {
    return [
        item.title,
        item.item_link,
        item.author,
        item.active_stage?.stage_name,
        ...(Array.isArray(item.route) ? item.route : []),
        ...(Array.isArray(item.current_assignees) ? item.current_assignees : []),
    ].join(' ').toLowerCase();
}

function isTechnicalApprovalNoise(item = {}) {
    const text = approvalTextBlob(item);
    return (
        text.includes('lifecycle director') ||
        text.includes('erp для удаления заявки') ||
        text.includes('/erp/process/') ||
        text.includes('delete request') ||
        text.includes('system workflow')
    );
}

function approvalStatusLabel(status) {
    const map = {
        pending: 'Ждёт решения',
        rework: 'На доработке',
        completed: 'Согласовано',
        rejected: 'Отклонено',
    };
    return map[String(status || '').trim()] || String(status || 'Ждёт решения');
}

function approvalHumanTitle(item = {}) {
    const raw = String(item.title || '').trim();
    const clean = raw.replace(/^Согласование:\s*/i, '').trim();
    if (isTechnicalApprovalNoise(item)) return 'Системное согласование';
    if (/черт|тз|техническ|спецификац|кб|производ/i.test(clean)) return clean || 'Техническое согласование';
    if (clean) return clean;
    return `Согласование #${item.id || ''}`;
}

function approvalHumanLink(item = {}) {
    const link = String(item.item_link || '').trim();
    if (!link) return 'Документ или заказ не указан';
    if (link.startsWith('/erp/process/')) return 'Внутренний ERP-процесс';
    if (link.startsWith('/documents/')) return `Документ #${link.split('/').filter(Boolean).pop() || ''}`;
    if (link.startsWith('/production/')) return `Производственный заказ #${link.split('/').filter(Boolean).pop() || ''}`;
    if (link.startsWith('/projects/') || link.startsWith('/project/')) return `Проект #${link.split('/').filter(Boolean).pop() || ''}`;
    return link;
}

function cleanApprovalPersonName(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (/lifecycle director/i.test(raw)) return 'Система';
    return raw;
}

function updateApprovalsPageForRole() {
    const isKb = isDesignOfficeApprovalRole();
    const title = document.querySelector('#approvalsView .view-title');
    const subtitle = document.querySelector('#approvalsView .view-subtitle');
    const actions = document.querySelector('#approvalsView .approvals-simple-header .view-actions');
    if (title) title.textContent = isKb ? 'Согласования КБ' : 'Согласования';
    if (subtitle) {
        subtitle.textContent = isKb
            ? 'Здесь КБ проверяет чертежи, ТЗ, спецификации и технические решения. Системные ERP-маршруты скрыты.'
            : 'Откройте документ, проверьте его и выберите одно понятное решение.';
    }
    if (actions) actions.style.display = isKb ? 'none' : '';
    if (isKb) workflowDesignerOpen = false;
}

function roleFilteredApprovalsForCurrentTab() {
    const isKb = isDesignOfficeApprovalRole();
    return approvalsDB.filter(item => {
        const statusOk = currentApprTab === 'pending'
            ? item.status === 'pending' || item.status === 'rework'
            : item.status === 'completed' || item.status === 'rejected';
        if (!statusOk) return false;
        if (isKb && isTechnicalApprovalNoise(item)) return false;
        return true;
    });
}

async function loadWorkflowDefinitions() {
    const res = await apiCall('/workflows/definitions');
    workflowDefinitionsDB = res && Array.isArray(res.items) ? res.items : [];
}

async function loadWorkflowInstances() {
    const res = await apiCall('/workflows/instances?limit=80');
    workflowInstancesDB = res && Array.isArray(res.items) ? res.items : [];
}

function switchApprTab(tab) {
    currentApprTab = tab;
    document.getElementById('tabApprPending').classList.toggle('active', tab === 'pending');
    document.getElementById('tabApprCompleted').classList.toggle('active', tab === 'completed');
    document.getElementById('tabApprPending').setAttribute('aria-selected', String(tab === 'pending'));
    document.getElementById('tabApprCompleted').setAttribute('aria-selected', String(tab === 'completed'));
    renderApprovals();
}

function getSelectedApprovals() {
    return approvalsDB.filter(item => approvalBulkSelection.has(Number(item.id)));
}

function toggleApprovalBulkSelection(id, checked) {
    if (checked) approvalBulkSelection.add(Number(id));
    else approvalBulkSelection.delete(Number(id));
    renderApprovals();
}

function selectVisibleApprovalsBulk() {
    const visible = approvalsDB.filter(a => currentApprTab === 'pending' ? (a.status === 'pending' || a.status === 'rework') : (a.status === 'completed' || a.status === 'rejected'));
    visible.forEach(item => approvalBulkSelection.add(Number(item.id)));
    renderApprovals();
}

function clearApprovalBulkSelection() {
    approvalBulkSelection.clear();
    renderApprovals();
}

function renderApprovalBulkToolbar() {
    const count = getSelectedApprovals().length;
    return `
        <div class="bulk-actions-bar ${count ? 'is-active' : ''}">
            <div class="bulk-actions-count">Выбрано согласований: ${count}</div>
            <button class="btn-secondary" onclick="selectVisibleApprovalsBulk()">Выбрать видимые</button>
            <select id="approvalBulkStatus" class="auth-input bulk-actions-select" ${count ? '' : 'disabled'}>
                <option value="pending">На согласовании</option>
                <option value="rework">Доработка</option>
                <option value="completed">Завершено</option>
                <option value="rejected">Отклонено</option>
            </select>
            <button class="btn-secondary" onclick="applyApprovalBulkStatus()" ${count ? '' : 'disabled'}>Сменить статус</button>
            <input id="approvalBulkDelegateUser" class="auth-input bulk-actions-input" placeholder="Кому делегировать" ${count ? '' : 'disabled'}>
            <button class="btn-secondary" onclick="delegateApprovalBulk()" ${count ? '' : 'disabled'}>Назначить</button>
            <button class="btn-success" onclick="applyApprovalBulkAction('approve')" ${count ? '' : 'disabled'}>Согласовать</button>
            <button class="btn-secondary" onclick="sendApprovalBulkToOneC()" ${count ? '' : 'disabled'}>В 1C</button>
            <button class="btn-secondary" onclick="exportApprovalBulkSelection()" ${count ? '' : 'disabled'}>Экспорт</button>
            <button class="btn-danger" onclick="deleteApprovalBulkSelection()" ${count ? '' : 'disabled'}>Удалить</button>
            <button class="btn-secondary" onclick="clearApprovalBulkSelection()" ${count ? '' : 'disabled'}>Снять выбор</button>
        </div>
    `;
}

async function applyApprovalBulkStatus() {
    const rows = getSelectedApprovals();
    const status = document.getElementById('approvalBulkStatus')?.value || '';
    if (!rows.length) return customAlert('Сначала выбери согласования.');
    const res = await apiCall('/workbench/bulk_actions', 'POST', {
        entity_type: 'approval',
        action: 'update_status',
        ids: rows.map(row => Number(row.id)).filter(Boolean),
        status,
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сменить статус согласований.');
    approvalBulkSelection.clear();
    await loadApprovals();
    renderApprovals();
    showToast('Согласования', `Статус обновлён: ${res.count || rows.length}`);
}

async function applyApprovalBulkAction(actionName) {
    const rows = getSelectedApprovals();
    if (!rows.length) return customAlert('Сначала выбери согласования.');
    const comment = await customPrompt('Комментарий к массовому действию:', 'Массовое действие');
    for (const row of rows) {
        const res = await apiCall(`/approvals/${row.id}/actions`, 'POST', { action_name: actionName, comment: comment || 'Массовое действие' });
        if (!res || res.error) return customAlert(res?.message || `Не удалось обработать согласование #${row.id}.`);
    }
    approvalBulkSelection.clear();
    await loadApprovals();
    renderApprovals();
    showToast('Согласования', `Обработано: ${rows.length}`);
}

async function delegateApprovalBulk() {
    const rows = getSelectedApprovals();
    const targetUser = document.getElementById('approvalBulkDelegateUser')?.value.trim() || '';
    if (!rows.length) return customAlert('Сначала выбери согласования.');
    if (!targetUser) return customAlert('Укажи сотрудника для назначения.');
    for (const row of rows) {
        const res = await apiCall(`/approvals/${row.id}/actions`, 'POST', { action_name: 'delegate', target_user: targetUser, comment: 'Массовое назначение' });
        if (!res || res.error) return customAlert(res?.message || `Не удалось делегировать согласование #${row.id}.`);
    }
    approvalBulkSelection.clear();
    await loadApprovals();
    renderApprovals();
    showToast('Согласования', `Назначено: ${rows.length}`);
}

async function deleteApprovalBulkSelection() {
    const rows = getSelectedApprovals();
    if (!rows.length) return customAlert('Сначала выбери согласования.');
    if (!(await customConfirm(`Удалить выбранные согласования (${rows.length})?`))) return;
    const res = await apiCall('/workbench/bulk_actions', 'POST', {
        entity_type: 'approval',
        action: 'delete',
        ids: rows.map(row => Number(row.id)).filter(Boolean),
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось удалить согласования.');
    approvalBulkSelection.clear();
    await loadApprovals();
    renderApprovals();
    showToast('Согласования', `Удалено: ${res.count || rows.length}`);
}

async function sendApprovalBulkToOneC() {
    const rows = getSelectedApprovals();
    if (!rows.length) return customAlert('Сначала выбери согласования.');
    const res = await apiCall('/workbench/bulk_actions', 'POST', {
        entity_type: 'approval',
        action: 'send_1c',
        ids: rows.map(row => Number(row.id)).filter(Boolean),
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось поставить согласования в очередь 1C.');
    showToast('Согласования', `В очередь 1C поставлено: ${res.queued ?? res.count ?? 0}`);
}

function exportApprovalBulkSelection() {
    const rows = getSelectedApprovals();
    if (!rows.length) return customAlert('Сначала выбери согласования.');
    if (typeof XLSX === 'undefined') return customAlert('Модуль экспорта пока не загрузился.');
    const exportRows = rows.map(item => ({
        'ID': item.id,
        'Название': item.title || '',
        'Статус': item.status || '',
        'Автор': item.author || '',
        'Этап': item.active_stage?.stage_name || '',
        'Исполнители': Array.isArray(item.current_assignees) ? item.current_assignees.join(', ') : '',
        'Срок реакции': item.sla_status || '',
        'Срок': item.due_at_display || '',
    }));
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Согласования');
    XLSX.writeFile(workbook, `korda-soglasovaniya-${new Date().toISOString().slice(0, 10)}.xlsx`);
    showToast('Согласования', `Выгружено: ${rows.length}`);
}

function renderApprovalsRoleWorkbench() {
    const mount = document.getElementById('approvalsRoleWorkbenchMount');
    if (!mount || !currentUser) return;
    updateApprovalsPageForRole();
    const role = String(currentUser.role || '').trim();
    if (isDesignOfficeApprovalRole()) {
        const visibleRows = roleFilteredApprovalsForCurrentTab();
        const pendingCount = approvalsDB.filter(item => !isTechnicalApprovalNoise(item) && (item.status === 'pending' || item.status === 'rework')).length;
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact approvals-kb-workbench">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Конструкторское бюро</div>
                    <h3 class="section-title">Что здесь делать</h3>
                    <p class="section-subtitle">Проверяйте только технические решения: чертежи, ТЗ, спецификации, маршрут изготовления и документы по заказу. Системные ERP-согласования для КБ скрыты.</p>
                </div>
                <div class="role-workbench-stats">
                    <div class="role-workbench-stat"><span>Видимых согласований</span><strong>${visibleRows.length}</strong></div>
                    <div class="role-workbench-stat"><span>Ждут решения</span><strong>${pendingCount}</strong></div>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="switchApprTab('pending')">К решению</button>
                    <button class="btn-secondary" onclick="navigateTo('production')">Производство</button>
                    <button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>
                    <button class="btn-secondary" onclick="navigateTo('tasks')">Поручения</button>
                </div>
            </section>
        `;
        return;
    }
    if (role === 'Юрист') {
        const pendingCount = approvalsDB.filter(item => item.status === 'pending').length;
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Юрист</div>
                    <h3 class="section-title">Что ждёт моего решения</h3>
                    <p class="section-subtitle">Для юридической роли приоритетом должны быть маршруты, документы, архив и претензионный контур, а не общий ERP-поток.</p>
                </div>
                <div class="role-workbench-stats">
                    <div class="role-workbench-stat"><span>На согласовании</span><strong>${pendingCount}</strong></div>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="switchApprTab('pending')">Активные</button>
                    <button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>
                    <button class="btn-secondary" onclick="navigateTo('client360')">Досье и претензии</button>
                </div>
            </section>
        `;
        return;
    }
    mount.innerHTML = '';
}

function ensureWorkflowDesignerDefaults() {
    if (workflowDesignerState.nodes.length) return;
    workflowDesignerState = {
        nodes: [
            { node_key: 'start', node_type: 'start', title: 'Старт', x: 0, y: 0 },
            { node_key: 'legal', node_type: 'approval', title: 'Юридическая проверка', role_name: 'Юрист', sla_hours: 8, x: 1, y: 0 },
            { node_key: 'amount_split', node_type: 'parallel_gateway', title: 'Параллельные проверки', x: 2, y: 0 },
            { node_key: 'finance', node_type: 'approval', title: 'Финансовый контроль', role_name: 'Бухгалтерия', sla_hours: 8, x: 3, y: -1 },
            { node_key: 'director', node_type: 'approval', title: 'Директор при сумме', role_name: 'Директор', sla_hours: 4, config: { sla_seconds: 14400 }, x: 3, y: 1 },
            { node_key: 'end', node_type: 'end', title: 'Готово', x: 4, y: 0 },
        ],
        edges: [
            { source_node_key: 'start', target_node_key: 'legal', condition_label: '' },
            { source_node_key: 'legal', target_node_key: 'amount_split', condition_label: '' },
            { source_node_key: 'amount_split', target_node_key: 'finance', condition_label: 'всегда' },
            { source_node_key: 'amount_split', target_node_key: 'director', condition: { field: 'amount', op: '>', value: 3000000 }, condition_label: 'amount > 3 000 000' },
            { source_node_key: 'finance', target_node_key: 'end', condition_label: '' },
            { source_node_key: 'director', target_node_key: 'end', condition_label: '' },
        ],
    };
}

function renderWorkflowNodeCard(node) {
    const typeMap = {
        start: 'Старт',
        approval: 'Согласование',
        parallel_gateway: 'Параллельно',
        exclusive_gateway: 'Условие',
        timer: 'Таймер',
        end: 'Финиш',
    };
    const meta = [
        typeMap[node.node_type] || node.node_type || 'Узел',
        node.role_name ? `роль ${node.role_name}` : '',
        node.assignee_name ? `исполнитель ${node.assignee_name}` : '',
        node.sla_hours ? `срок ${node.sla_hours}ч` : '',
        node.timer_seconds ? `таймер ${node.timer_seconds}с` : '',
    ].filter(Boolean).join(' · ');
    return `
        <div class="workflow-designer-node">
            <div class="workflow-designer-node-key">${workflowEscape(node.node_key)}</div>
            <div class="workflow-designer-node-title">${workflowEscape(node.title || node.node_key)}</div>
            <div class="workflow-designer-node-meta">${workflowEscape(meta)}</div>
        </div>
    `;
}

function renderWorkflowInstancesPanel() {
    const active = (workflowInstancesDB || []).slice(0, 6);
    if (!active.length) {
        return '<div class="approval-empty">Запущенных BPMN-процессов пока нет.</div>';
    }
    return active.map(instance => {
        const tokens = Array.isArray(instance.active_tokens) ? instance.active_tokens : [];
        const tokenHtml = tokens.map(token => `
            <div class="workflow-token-row">
                <div>
                    <div class="client360-item-title">${workflowEscape(token.node_key)} · ${workflowEscape(token.assignee_name || token.role_name || 'без исполнителя')}</div>
                    <div class="client360-item-meta">${workflowEscape(token.token_status)}${token.due_at ? ` · срок до ${new Date(Number(token.due_at) * 1000).toLocaleString('ru-RU')}` : ''}</div>
                </div>
                <div class="view-actions">
                    <button class="btn-success" onclick="processWorkflowToken(${Number(token.id)}, 'approve')">ОК</button>
                    <button class="btn-secondary" onclick="processWorkflowToken(${Number(token.id)}, 'delegate')">Передать</button>
                    <button class="btn-secondary" onclick="processWorkflowToken(${Number(token.id)}, 'return_rework')">Доработка</button>
                </div>
            </div>
        `).join('') || '<div class="client360-item-meta">Активных токенов нет.</div>';
        return `
            <div class="workflow-instance-row">
                <div class="workflow-instance-head">
                    <div>
                        <div class="client360-item-title">${workflowEscape(instance.title || instance.workflow_code || `Процесс #${instance.id}`)}</div>
                        <div class="client360-item-meta">${workflowEscape(instance.status)} · ${workflowEscape(instance.entity_type || 'entity')} #${workflowEscape(instance.entity_id || '')}</div>
                    </div>
                    <span class="status-badge ${instance.status === 'completed' ? 'status-completed' : instance.status === 'rejected' ? 'status-overdue' : 'status-active'}">${workflowEscape(instance.status)}</span>
                </div>
                ${tokenHtml}
            </div>
        `;
    }).join('');
}

function renderWorkflowDesignerMount() {
    const mount = document.getElementById('workflowDesignerMount');
    if (!mount) return;
    if (!workflowDesignerOpen) {
        mount.innerHTML = '';
        return;
    }
    ensureWorkflowDesignerDefaults();
    const edgesHtml = workflowDesignerState.edges.map(edge => {
        const condition = edge.condition_label || (edge.condition ? `${edge.condition.field || ''} ${edge.condition.op || ''} ${edge.condition.value ?? ''}` : '');
        return `<div class="workflow-edge-row"><strong>${workflowEscape(edge.source_node_key)}</strong><span>→</span><strong>${workflowEscape(edge.target_node_key)}</strong><span>${workflowEscape(condition || 'без условия')}</span></div>`;
    }).join('');
    const definitions = (workflowDefinitionsDB || []).slice(0, 8).map(def => `
        <div class="workflow-definition-row">
            <div>
                <div class="client360-item-title">${workflowEscape(def.workflow_name || def.workflow_code)}</div>
                <div class="client360-item-meta">${workflowEscape(def.entity_type || 'любой объект')} · v${Number(def.version || 1)} · узлов ${(def.nodes || []).length}</div>
            </div>
            <button class="btn-secondary" onclick="startWorkflowDefinition(${Number(def.id)})">Запустить</button>
        </div>
    `).join('') || '<div class="approval-empty">Сохранённых BPMN-маршрутов пока нет.</div>';
    mount.innerHTML = `
        <section class="surface-card surface-card--padded workflow-designer">
            <div class="workflow-designer-head">
                <div>
                    <div class="view-eyebrow">BPMN</div>
                    <h3 class="section-title">Конструктор бизнес-процессов</h3>
                    <p class="section-subtitle">Условия, параллельные ветки, таймеры, сроки реакции, эскалации, возврат и делегирование в одном маршруте.</p>
                </div>
                <div class="view-actions">
                    <button class="btn-secondary" onclick="addWorkflowNode()">Узел</button>
                    <button class="btn-secondary" onclick="connectWorkflowNodes()">Связь</button>
                    <button class="btn-primary" onclick="saveWorkflowDefinition()">Сохранить</button>
                    <button class="btn-secondary" onclick="workflowDesignerOpen=false; renderWorkflowDesignerMount()">Скрыть</button>
                </div>
            </div>
            <div class="workflow-designer-grid">
                <div>
                    <div class="section-title" style="font-size:15px;">Схема</div>
                    <div class="workflow-node-board">${workflowDesignerState.nodes.map(renderWorkflowNodeCard).join('')}</div>
                    <div class="workflow-edge-list">${edgesHtml}</div>
                </div>
                <div>
                    <div class="section-title" style="font-size:15px;">Шаблоны</div>
                    <div class="workflow-definition-list">${definitions}</div>
                    <div class="section-title" style="font-size:15px; margin-top:16px;">Запущенные процессы</div>
                    <div class="workflow-instance-list">${renderWorkflowInstancesPanel()}</div>
                    <div class="view-actions" style="margin-top:12px;">
                        <button class="btn-secondary" onclick="processWorkflowAutomation()">Обработать таймеры и сроки</button>
                    </div>
                </div>
            </div>
        </section>
    `;
}

async function openWorkflowDesigner() {
    workflowDesignerOpen = true;
    ensureWorkflowDesignerDefaults();
    await loadWorkflowDefinitions();
    await loadWorkflowInstances();
    renderWorkflowDesignerMount();
    const mount = document.getElementById('workflowDesignerMount');
    if (mount) mount.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function addWorkflowNode() {
    ensureWorkflowDesignerDefaults();
    const nodeKey = await customPrompt('Ключ узла:', `node_${workflowDesignerState.nodes.length + 1}`);
    if (!nodeKey) return;
    const nodeType = await customPrompt('Тип: approval, parallel_gateway, exclusive_gateway, timer, end', 'approval');
    const title = await customPrompt('Название узла:', 'Новый этап');
    const roleName = nodeType === 'approval' ? await customPrompt('Роль исполнителя:', 'Директор') : '';
    const slaHours = nodeType === 'approval' ? Number(await customPrompt('Срок реакции в часах:', '24') || 24) : 0;
    const timerSeconds = nodeType === 'timer' ? Number(await customPrompt('Таймер в секундах:', '3600') || 3600) : 0;
    workflowDesignerState.nodes.push({
        node_key: nodeKey.trim(),
        node_type: (nodeType || 'approval').trim(),
        title: title || nodeKey,
        role_name: roleName || '',
        sla_hours: slaHours,
        timer_seconds: timerSeconds,
        x: workflowDesignerState.nodes.length,
        y: 0,
    });
    renderWorkflowDesignerMount();
}

async function connectWorkflowNodes() {
    ensureWorkflowDesignerDefaults();
    const source = await customPrompt('Откуда:', workflowDesignerState.nodes.at(-2)?.node_key || 'start');
    if (!source) return;
    const target = await customPrompt('Куда:', workflowDesignerState.nodes.at(-1)?.node_key || 'end');
    if (!target) return;
    const rawCondition = await customPrompt('Условие, например amount > 3000000. Пусто = всегда:', '');
    let condition = {};
    let label = '';
    if (rawCondition && rawCondition.trim()) {
        const parts = rawCondition.trim().split(/\s+/);
        if (parts.length >= 3) {
            condition = { field: parts[0], op: parts[1], value: Number.isNaN(Number(parts.slice(2).join(' '))) ? parts.slice(2).join(' ') : Number(parts.slice(2).join(' ')) };
            label = rawCondition.trim();
        }
    }
    workflowDesignerState.edges.push({ source_node_key: source.trim(), target_node_key: target.trim(), condition, condition_label: label });
    renderWorkflowDesignerMount();
}

async function saveWorkflowDefinition() {
    ensureWorkflowDesignerDefaults();
    const workflowName = await customPrompt('Название маршрута:', 'BPMN маршрут договора');
    if (!workflowName) return;
    const entityType = await customPrompt('Тип объекта:', 'document');
    const workflowCode = `WF-${Date.now()}`;
    const res = await apiCall('/workflows/definitions', 'POST', {
        workflow_code: workflowCode,
        workflow_name: workflowName,
        entity_type: entityType || '',
        status: 'active',
        is_active: 1,
        nodes: workflowDesignerState.nodes,
        edges: workflowDesignerState.edges,
        conditions: {},
    });
    if (res?.error) return;
    showToast('BPMN', 'Маршрут сохранён');
    await loadWorkflowDefinitions();
    renderWorkflowDesignerMount();
}

async function startWorkflowDefinition(definitionId) {
    const amountRaw = await customPrompt('Сумма для условий маршрута:', '5000000');
    if (amountRaw === null) return;
    const entityType = await customPrompt('Тип объекта:', 'document');
    const entityId = await customPrompt('ID объекта:', '');
    const res = await apiCall(`/workflows/definitions/${Number(definitionId)}/start`, 'POST', {
        entity_type: entityType || 'document',
        entity_id: entityId || '',
        title: 'BPMN процесс',
        context: {
            amount: Number(amountRaw || 0),
            entity_type: entityType || 'document',
            entity_id: entityId || '',
            legal_entity_id: 0,
            doc_type: entityType || 'document',
        },
    });
    if (res?.error) return;
    showToast('BPMN', 'Процесс запущен');
    await loadWorkflowInstances();
    renderWorkflowDesignerMount();
}

async function processWorkflowToken(tokenId, action) {
    const payload = { action_name: action };
    if (action === 'delegate') {
        const opts = allUsersDB.filter(u => u.status === 'approved').map((u, i) => `${i + 1} - ${u.name}`).join('\n');
        const userIdx = await customPrompt(`Кому передать?\n${opts}`);
        const userObj = allUsersDB.filter(u => u.status === 'approved')[parseInt(userIdx) - 1];
        if (!userObj) return;
        payload.target_user = userObj.name;
    }
    if (action === 'return_rework') {
        payload.comment = await customPrompt('Комментарий для доработки:', '') || '';
        payload.target_node_key = await customPrompt('Ключ узла возврата:', 'legal') || 'legal';
    }
    const res = await apiCall(`/workflows/tokens/${Number(tokenId)}/actions`, 'POST', payload);
    if (res?.error) return;
    showToast('BPMN', action === 'approve' ? 'Токен согласован' : 'Действие выполнено');
    await loadWorkflowInstances();
    renderWorkflowDesignerMount();
}

async function processWorkflowAutomation() {
    const res = await apiCall('/workflows/process_automation', 'POST', {});
    if (res?.error) return;
    showToast('BPMN', `Обработано событий: ${Number(res.count || 0)}`);
    await loadWorkflowInstances();
    renderWorkflowDesignerMount();
}

// ФУНКЦИЯ ДЛЯ ОТКРЫТИЯ ПРОЕКТА ПО КЛИКУ ИЗ СОГЛАСОВАНИЙ
async function openProjectFromLink(link) {
    const cleanLink = String(link || '').trim();
    const documentMatch = cleanLink.match(/^\/documents\/(\d+)\/?$/i);
    if (documentMatch) {
        navigateTo('documents');
        window.setTimeout(() => {
            if (typeof openDocumentPreview === 'function') openDocumentPreview(Number(documentMatch[1]));
        }, 250);
        return;
    }
    const productionMatch = cleanLink.match(/^\/production\/(\d+)\/?$/i);
    if (productionMatch) {
        navigateTo('production');
        window.setTimeout(() => {
            if (typeof selectSimpleProductionOrder === 'function') selectSimpleProductionOrder(Number(productionMatch[1]));
        }, 250);
        return;
    }
    const projectMatch = cleanLink.match(/^\/projects?\/(\d+)\/?$/i);
    if (projectMatch) link = projectMatch[1];
    // Ищем проект по ID, номеру договора или названию
    const p = projectsDB.find(x => String(x.id) === String(link) || x.contract === link || x.name === link);
    
    if (p) {
        currentProjectId = p.id;
        
        // Переключаем экран на карточку проекта
        if (typeof navigateTo === 'function') navigateTo('project');
        
        // Заполняем данные карточки
        document.getElementById('projName').value = p.name || '';
        document.getElementById('projContract').value = p.contract || '';
        document.getElementById('projClient').value = p.client || '';
        document.getElementById('projManager').value = p.manager || '';
        if(document.getElementById('projBudget')) document.getElementById('projBudget').value = p.budget || 0;
        if(document.getElementById('projCosts')) document.getElementById('projCosts').value = p.costs || 0;
        
        // Обновляем все внутренние блоки (чек-лист, файлы, чат)
        if (typeof calcMargin === 'function') calcMargin();
        if (typeof updateChecklistUI === 'function') updateChecklistUI();
        if (typeof renderChat === 'function') renderChat();
        if (typeof renderFiles === 'function') renderFiles();
    } else {
        // ЗАМЕНА: customAlert вместо alert
        await customAlert("Проект с таким номером не найден в базе.\nВозможно, он был удален или у вас нет к нему доступа.");
    }
}

function renderApprovals() {
    const container = document.getElementById('approvalsListContainer'); 
    if (!container) return;
    renderApprovalsRoleWorkbench();
    renderWorkflowDesignerMount();
    
    const filt = approvalsDB.filter(a => {
        if (currentApprTab === 'pending') return a.status === 'pending' || a.status === 'rework';
        return a.status === 'completed' || a.status === 'rejected';
    });

    if (filt.length === 0) {
        container.innerHTML = typeof renderInlineEmptyState === 'function'
            ? renderInlineEmptyState(
                currentApprTab === 'pending' ? 'Активных согласований пока нет.' : 'Завершённых маршрутов пока нет.',
                currentApprTab === 'pending'
                    ? 'Запусти первый маршрут или открой документы, чтобы согласование появилось из реального процесса.'
                    : 'История завершённых согласований будет собираться здесь автоматически.',
                currentApprTab === 'pending'
                    ? `<button class="btn-primary" onclick="openCreateApprovalModal({})">Новый маршрут</button><button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>`
                    : `<button class="btn-secondary" onclick="switchApprTab('pending')">На согласовании</button>`
            )
            : `<div style="text-align:center; padding:30px; color:var(--secondary);">Нет запущенных процессов.</div>`;
        return;
    }

    const renderCards = () => renderApprovalBulkToolbar() + filt.map(a => {
        let routeHtml = '';
        
        // Логика 1С: Поддержка параллельных маршрутов и проверка текущего этапа
        const stepStr = a.route[a.current_step] || '';
        const stepUsers = Array.isArray(a.current_assignees) && a.current_assignees.length ? a.current_assignees : stepStr.split(' и ').map(u => u.trim());
        // Проверяем, голосовал ли я уже именно на ЭТОМ этапе
        const iAlreadyApproved = a.history.some(h => h.startsWith(`✅ ${currentUser.name}`) && h.includes(`(Этап ${a.current_step + 1})`));
        const amI_Current = ((a.status === 'pending' || a.status === 'rework') && stepUsers.includes(currentUser.name) && !iAlreadyApproved);
        
        a.route.forEach((person, idx) => {
            let cls = 'approval-step';
            if (idx < a.current_step) cls += ' done';
            else if (idx === a.current_step && a.status === 'pending') cls += ' active';
            else if (idx === a.current_step && a.status === 'rejected') cls += ' rejected';
            
            routeHtml += `<div class="${cls}">${person}</div>`;
            if (idx < a.route.length - 1) routeHtml += `<div class="approval-arrow">→</div>`;
        });

        let actionBtns = '';
        if (amI_Current || currentUser.role === 'Директор') {
            actionBtns = `
            <div style="display:flex; gap:8px; margin-top: 15px;">
                <button class="btn-success" onclick="processApprovalStep(${a.id}, 'approve')">Согласовать</button>
                <button class="btn-danger" onclick="processApprovalStep(${a.id}, 'reject')">Отклонить</button>
                <button class="btn-secondary" onclick="processApprovalStep(${a.id}, 'return_rework')">На доработку</button>
                <button class="btn-secondary" onclick="processApprovalStep(${a.id}, 'delegate')">Делегировать</button>
            </div>`;
        }
        
        let histHtml = '';
        if (a.history.length > 0) {
            histHtml = `<div style="margin-top:12px; font-size:11px; color:var(--secondary); background:var(--bg); padding:8px; border-radius:8px;">` 
                       + a.history.map(h => `<div>${h}</div>`).join('') + 
                       `</div>`;
        }

        return `
        <div data-approval-id="${a.id}" class="approval-card ${typeof isWorkflowFocused === 'function' && isWorkflowFocused('approval', a.id) ? 'workflow-row-highlight' : ''}">
            <div style="display:flex; align-items:flex-start; gap:10px;">
                <input type="checkbox" class="bulk-row-checkbox" ${approvalBulkSelection.has(Number(a.id)) ? 'checked' : ''} aria-label="Выбрать согласование" onchange="toggleApprovalBulkSelection(${Number(a.id)}, this.checked)">
                <div style="min-width:0; flex:1;">
                    <div style="font-weight:600; font-size:16px;">${a.title}</div>
                    <div style="font-size:12px; color:var(--secondary); margin-top:4px;">
                        Документ: <span onclick="openProjectFromLink('${a.item_link}')" style="color:var(--primary); cursor:pointer; text-decoration:underline;">${a.item_link}</span> | Автор: ${a.author}
                    </div>
                    <div style="font-size:12px; color:var(--secondary); margin-top:6px;">
                        Активный этап: ${a.active_stage?.stage_name || 'не определён'} · срок реакции ${a.sla_status || 'стабильно'}${a.due_at_display ? ` · до ${a.due_at_display}` : ''}
                    </div>
                </div>
            </div>
            <div class="approval-route">${routeHtml}</div>
            ${histHtml}
            ${a.status === 'pending' ? actionBtns : ''}
        </div>`;
    }).join('');
    if (typeof renderDeferredHtml === 'function') {
        renderDeferredHtml(container, renderCards, { size: filt.length, threshold: 40, loadingMessage: 'Загружаю маршруты согласования...' });
    } else {
        container.innerHTML = renderCards();
    }
}

let smartRouteData = [];

function openCreateApprovalModal(preset = {}) {
    smartRouteData = [];
    renderSmartRoute();
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('approvalForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('createApprovalModal');
    const titleEl = document.getElementById('apprTitle');
    const linkEl = document.getElementById('apprLink');
    if (titleEl) titleEl.value = preset.title || '';
    if (linkEl) {
        const documentOptions = (Array.isArray(documentsDB) ? documentsDB : []).map(document => ({
            value: `/documents/${Number(document.id)}`,
            label: `${document.number || `Документ #${document.id}`} — ${document.subject || 'без темы'}`,
        }));
        const projectOptions = (Array.isArray(projectsDB) ? projectsDB : []).map(project => ({
            value: String(project.id),
            label: `Проект: ${project.contract || project.name || `#${project.id}`}`,
        }));
        const options = [...documentOptions, ...projectOptions];
        const presetValue = String(preset.item_link || '');
        if (presetValue && !options.some(option => option.value === presetValue)) options.unshift({ value: presetValue, label: presetValue });
        linkEl.innerHTML = `<option value="">Выберите документ или проект</option>${options.map(option => `<option value="${workflowEscape(option.value)}">${workflowEscape(option.label)}</option>`).join('')}`;
        linkEl.value = presetValue;
        linkEl.onchange = () => {
            if (!titleEl || titleEl.value.trim() || !linkEl.value) return;
            titleEl.value = `Согласование: ${String(linkEl.selectedOptions?.[0]?.textContent || '').trim()}`;
        };
    }
    const userSelect = document.getElementById('apprRouteUser');
    if (userSelect) {
        const users = (Array.isArray(allUsersDB) ? allUsersDB : []).filter(user => user.status === 'approved' && user.name);
        userSelect.innerHTML = `<option value="">Выберите сотрудника</option>${users.map(user => `<option value="${workflowEscape(user.name)}">${workflowEscape(user.name)} · ${workflowEscape(user.role || 'Сотрудник')}</option>`).join('')}`;
    }
    document.getElementById('createApprovalModal').style.display = 'flex';
    if (titleEl) titleEl.focus();
}

window.addApprovalRouteUser = function() {
    const select = document.getElementById('apprRouteUser');
    const userName = String(select?.value || '').trim();
    if (!userName) return customAlert('Выберите сотрудника, который должен согласовать документ.');
    if (smartRouteData.includes(userName)) return customAlert('Этот сотрудник уже добавлен в маршрут.');
    smartRouteData.push(userName);
    select.value = '';
    renderSmartRoute();
};

window.addSmartRouteStep = async function() {
    const type = await customPrompt("Тип этапа: 1 - Последовательный, 2 - Параллельный (одновременно)", "1");
    if(!type) return;
    
    let opts = allUsersDB.filter(u => u.status === 'approved').map((u, i) => `${i+1} - ${u.name}`).join('\n');
    const userIdx = await customPrompt(`Введите номер сотрудника:\n${opts}`);
    const userObj = allUsersDB.filter(u => u.status === 'approved')[parseInt(userIdx)-1];
    if(!userObj) return;

    if (type === "2" && smartRouteData.length > 0) {
        smartRouteData[smartRouteData.length - 1] += ` и ${userObj.name}`; // Объединяем в параллельный узел
    } else {
        smartRouteData.push(userObj.name); // Последовательный узел
    }
    renderSmartRoute();
};

window.autoGenerateRoute = async function() {
    const pId = await customPrompt("Умная маршрутизация 1С.\nВведите идентификатор договора (сделки) для проверки суммы бюджета:");
    if (!pId) return;
    const p = projectsDB.find(x => x.id === parseInt(pId));
    if (!p) return customAlert("Проект с таким идентификатором не найден.");
    
    smartRouteData = [];
    smartRouteData.push("Юрист");
    smartRouteData.push("Бухгалтерия");
    
    if (p.budget >= 3000000) {
        smartRouteData.push("Директор");
        showToast("Маршрутизация", `Бюджет ${p.budget.toLocaleString('ru-RU')} ₽. Автоматически добавлен Директор!`);
    } else {
        showToast("Маршрутизация", "Сформирован стандартный маршрут.");
    }
    renderSmartRoute();
};

function renderSmartRoute() {
    const c = document.getElementById('smartRouteContainer');
    if (!c) return;
    if(smartRouteData.length === 0) { c.innerHTML = '<div class="approval-create-route__empty">Согласующие пока не выбраны.</div>'; return; }
    
    c.innerHTML = smartRouteData.map((step, idx) => `
        <div class="approval-create-route__item">
            <span>${idx+1}</span>
            <strong>${workflowEscape(step)}</strong>
            <button class="btn-secondary" type="button" onclick="smartRouteData.splice(${idx},1); renderSmartRoute()">Удалить</button>
        </div>
    `).join('');
}

async function submitApproval() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('approvalForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('createApprovalModal');
    const title = document.getElementById('apprTitle').value.trim();
    const link = document.getElementById('apprLink').value.trim();
    const errors = [];
    if (!title) errors.push({ field: 'apprTitle', message: 'Укажите название процесса или документа.' });
    if (!link) errors.push({ field: 'apprLink', message: 'Выберите документ или проект для согласования.' });
    if (smartRouteData.length === 0) errors.push({ field: 'smartRouteContainer', message: 'Добавьте хотя бы один этап маршрута.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'createApprovalModal');
        return;
    }
    
    const res = await apiCall('/approvals', 'POST', { 
        title: title, 
        item_link: link, 
        route: smartRouteData, 
        author: currentUser.name 
    });
    if (res && !res.error && typeof markWorkflowFocus === 'function') {
        markWorkflowFocus('approval', Number(res.id || 0));
    }
    
    document.getElementById('createApprovalModal').style.display = 'none';
    await loadApprovals(); 
    switchApprTab('pending');
    showToast("Согласования", "Процесс успешно запущен");
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('[data-approval-id].workflow-row-highlight, [data-approval-id]');
}

async function processApprovalStep(id, action) {
    const a = approvalsDB.find(x => x.id === id);
    let payload = { action_name: action };
    if (action === 'reject') {
        const reason = await customPrompt("Причина отклонения:");
        payload.comment = reason || '';
    }
    if (action === 'return_rework') {
        const reason = await customPrompt("Комментарий для возврата на доработку:");
        payload.comment = reason || '';
        payload.target_stage_key = a.route_steps?.[Math.max(0, (a.current_step || 0) - 1)]?.stage_key || '';
    }
    if (action === 'delegate') {
        let opts = allUsersDB.filter(u => u.status === 'approved').map((u, i) => `${i+1} - ${u.name}`).join('\n');
        const userIdx = await customPrompt(`Кому делегировать?\n${opts}`);
        const userObj = allUsersDB.filter(u => u.status === 'approved')[parseInt(userIdx)-1];
        if (!userObj) return;
        payload.target_user = userObj.name;
        payload.comment = await customPrompt("Комментарий к делегированию:", "") || '';
    }
    const res = await apiCall(`/approvals/${a.id}/actions`, 'POST', payload);
    if (res?.error) return;
    if (action === 'approve') showToast("Согласования", "Ваш голос учтен!");
    if (action === 'reject') showToast("Внимание", "Документ отклонен", "error");
    if (action === 'return_rework') showToast("Согласования", "Маршрут возвращён на доработку");
    if (action === 'delegate') showToast("Согласования", "Маршрут делегирован");
    await loadApprovals(); 
    renderApprovals();
}

// Enterprise approvals and workflow designer overrides
function approvalUiJsString(value) {
    return String(value ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n');
}

function approvalUiStatusTone(status) {
    if (status === 'completed') return 'krd-approval-pill--completed';
    if (status === 'rejected') return 'krd-approval-pill--rejected';
    if (status === 'rework') return 'krd-approval-pill--rework';
    return 'krd-approval-pill--pending';
}

renderApprovalBulkToolbar = function() {
    const count = getSelectedApprovals().length;
    return `
        <div class="krd-approval-bulk">
            <div class="krd-approval-bulk__count">Выбрано маршрутов: ${count}</div>
            <button class="btn-secondary" onclick="selectVisibleApprovalsBulk()">Выбрать видимые</button>
            <select id="approvalBulkStatus" class="auth-input" ${count ? '' : 'disabled'}>
                <option value="pending">На согласовании</option>
                <option value="rework">Доработка</option>
                <option value="completed">Завершено</option>
                <option value="rejected">Отклонено</option>
            </select>
            <button class="btn-secondary" onclick="applyApprovalBulkStatus()" ${count ? '' : 'disabled'}>Сменить статус</button>
            <input id="approvalBulkDelegateUser" class="auth-input" placeholder="Кому делегировать" ${count ? '' : 'disabled'}>
            <button class="btn-secondary" onclick="delegateApprovalBulk()" ${count ? '' : 'disabled'}>Назначить</button>
            <div class="krd-approval-bulk__spacer"></div>
            <button class="btn-success" onclick="applyApprovalBulkAction('approve')" ${count ? '' : 'disabled'}>Согласовать</button>
            <button class="btn-secondary" onclick="sendApprovalBulkToOneC()" ${count ? '' : 'disabled'}>В 1C</button>
            <button class="btn-secondary" onclick="exportApprovalBulkSelection()" ${count ? '' : 'disabled'}>Экспорт</button>
            <button class="btn-danger" onclick="deleteApprovalBulkSelection()" ${count ? '' : 'disabled'}>Удалить</button>
            <button class="btn-secondary" onclick="clearApprovalBulkSelection()" ${count ? '' : 'disabled'}>Снять выбор</button>
        </div>
    `;
};

renderWorkflowDesignerMount = function() {
    const mount = document.getElementById('workflowDesignerMount');
    if (!mount) return;
    if (!workflowDesignerOpen) {
        mount.innerHTML = '';
        return;
    }

    ensureWorkflowDesignerDefaults();

    const edgesHtml = workflowDesignerState.edges.map(edge => {
        const condition = edge.condition_label || (edge.condition ? `${edge.condition.field || ''} ${edge.condition.op || ''} ${edge.condition.value ?? ''}` : '');
        return `<div class="workflow-edge-row"><strong>${workflowEscape(edge.source_node_key)}</strong><span>→</span><strong>${workflowEscape(edge.target_node_key)}</strong><span>${workflowEscape(condition || 'без условия')}</span></div>`;
    }).join('') || '<div class="krd-empty"><div class="krd-empty__title">Переходы не заданы</div><div class="krd-empty__hint">Свяжите узлы, чтобы превратить схему в реальный маршрут.</div></div>';

    const definitions = (workflowDefinitionsDB || []).slice(0, 8).map(definition => `
        <div class="workflow-definition-row">
            <div>
                <div class="client360-item-title">${workflowEscape(definition.workflow_name || definition.workflow_code)}</div>
                <div class="client360-item-meta">${workflowEscape(definition.entity_type || 'любой объект')} · ${Number(definition.version || 1)} версия · узлов ${(definition.nodes || []).length}</div>
            </div>
            <button class="btn-secondary" onclick="startWorkflowDefinition(${Number(definition.id)})">Запустить</button>
        </div>
    `).join('') || `
        <div class="krd-empty">
            <div class="krd-empty__title">Шаблоны маршрутов ещё не сохранены</div>
            <div class="krd-empty__hint">Соберите схему и сохраните её как корпоративный шаблон процесса.</div>
        </div>
    `;

    mount.innerHTML = `
        <section class="krd-card krd-card--pad krd-designer-shell">
            <div class="krd-card__head">
                <div>
                    <div class="krd-card__title">Конструктор бизнес-процессов</div>
                    <div class="krd-card__subtitle">Визуальная сборка маршрутов с ролями, ветвлениями, таймерами и живыми экземплярами процесса.</div>
                </div>
                <div class="krd-designer-actions">
                    <button class="btn-secondary" onclick="addWorkflowNode()">Узел</button>
                    <button class="btn-secondary" onclick="connectWorkflowNodes()">Связь</button>
                    <button class="btn-primary" onclick="saveWorkflowDefinition()">Сохранить маршрут</button>
                    <button class="btn-secondary" onclick="workflowDesignerOpen=false; renderWorkflowDesignerMount()">Скрыть</button>
                </div>
            </div>

            <div class="krd-designer-grid">
                <div class="krd-designer-panel">
                    <div class="krd-designer-section-title">Дерево маршрута</div>
                    <div class="workflow-node-board">${workflowDesignerState.nodes.map(renderWorkflowNodeCard).join('')}</div>
                    <div class="krd-designer-section-title krd-designer-section-title--spaced">Переходы и условия</div>
                    <div class="workflow-edge-list">${edgesHtml}</div>
                </div>

                <div class="krd-designer-panel">
                    <div class="krd-designer-section-title">Шаблоны маршрутов</div>
                    <div class="workflow-definition-list">${definitions}</div>
                    <div class="krd-designer-section-title krd-designer-section-title--spaced">Живые процессы</div>
                    <div class="workflow-instance-list">${renderWorkflowInstancesPanel()}</div>
                    <div class="krd-designer-actions krd-designer-foot">
                        <button class="btn-secondary" onclick="processWorkflowAutomation()">Обработать таймеры и сроки</button>
                    </div>
                </div>
            </div>
        </section>
    `;
};

renderApprovals = function() {
    const container = document.getElementById('approvalsListContainer');
    if (!container) return;
    const currentUserName = currentUser?.name || '';
    const currentUserRole = currentUser?.role || '';
    const isKb = isDesignOfficeApprovalRole();

    renderApprovalsRoleWorkbench();
    renderWorkflowDesignerMount();

    const filtered = roleFilteredApprovalsForCurrentTab();

    if (!filtered.length) {
        container.innerHTML = typeof renderInlineEmptyState === 'function'
            ? renderInlineEmptyState(
                isKb
                    ? (currentApprTab === 'pending' ? 'Для КБ сейчас нет согласований.' : 'Истории согласований КБ пока нет.')
                    : (currentApprTab === 'pending' ? 'Активных согласований пока нет.' : 'Завершённых маршрутов пока нет.'),
                isKb
                    ? 'Когда менеджер, директор или производство отправит на проверку чертёж, ТЗ, спецификацию или заказ — он появится здесь.'
                    : (currentApprTab === 'pending'
                    ? 'Запустите первый маршрут или откройте документы, чтобы согласование появилось из реального процесса.'
                    : 'История завершённых маршрутов будет собираться здесь автоматически.'),
                isKb
                    ? `<button class="btn-primary" onclick="navigateTo('production')">Открыть производство</button><button class="btn-secondary" onclick="navigateTo('documents')">Документы КБ</button>`
                    : (currentApprTab === 'pending'
                    ? `<button class="btn-primary" onclick="openCreateApprovalModal({})">Новый маршрут</button><button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>`
                    : `<button class="btn-secondary" onclick="switchApprTab('pending')">На согласовании</button>`)
            )
            : '<div class="krd-empty"><div class="krd-empty__title">Маршрутов пока нет</div></div>';
        return;
    }

    const renderCards = () => {
        return (isKb ? '' : renderApprovalBulkToolbar()) + filtered.map(item => {
            const history = Array.isArray(item.history) ? item.history : [];
            const route = Array.isArray(item.route) ? item.route : [];
            const currentStep = Number(item.current_step || 0);
            const activeStepRaw = route[currentStep] || '';
            const stepUsers = Array.isArray(item.current_assignees) && item.current_assignees.length
                ? item.current_assignees
                : activeStepRaw.split(' и ').map(name => name.trim()).filter(Boolean);
            const iAlreadyApproved = history.some(entry => entry.startsWith(`✅ ${currentUserName}`) && entry.includes(`(Этап ${currentStep + 1})`));
            const amICurrent = ((item.status === 'pending' || item.status === 'rework') && stepUsers.includes(currentUserName) && !iAlreadyApproved);
            const canAct = amICurrent || currentUserRole === 'Директор';
            const safeLink = approvalUiJsString(item.item_link || '');
            const displayTitle = approvalHumanTitle(item);
            const displayLink = approvalHumanLink(item);
            const displayAuthor = cleanApprovalPersonName(item.author) || 'Не указан';
            const displayStep = item.active_stage?.stage_name || `Этап ${currentStep + 1}`;
            const visibleStepUsers = stepUsers.map(cleanApprovalPersonName).filter(Boolean);

            const routeHtml = route.map((person, idx) => {
                let stepClass = 'krd-approval-step';
                if (idx < currentStep) stepClass += ' krd-approval-step--done';
                else if (idx === currentStep && item.status === 'rejected') stepClass += ' krd-approval-step--rejected';
                else if (idx === currentStep && (item.status === 'pending' || item.status === 'rework')) stepClass += ' krd-approval-step--active';
                return `
                    <span class="${stepClass}">${workflowEscape(cleanApprovalPersonName(person))}</span>
                    ${idx < route.length - 1 ? '<span class="krd-approval-arrow">→</span>' : ''}
                `;
            }).join('');

            const actions = canAct ? `
                <div class="krd-approval-actions">
                    <button class="btn-success" onclick="processApprovalStep(${Number(item.id)}, 'approve')">Согласовать</button>
                    <button class="btn-secondary" onclick="processApprovalStep(${Number(item.id)}, 'return_rework')">Вернуть на исправление</button>
                    <button class="btn-danger" onclick="processApprovalStep(${Number(item.id)}, 'reject')">Отказать</button>
                    <button class="btn-secondary" onclick="processApprovalStep(${Number(item.id)}, 'delegate')">Передать другому</button>
                </div>
            ` : '';

            const historyBlock = history.length ? `
                <details class="krd-approval-history">
                    <summary>История маршрута (${history.length})</summary>
                    <div class="krd-approval-history__body">
                        ${history.map(entry => `<div class="krd-approval-history__item">${workflowEscape(entry)}</div>`).join('')}
                    </div>
                </details>
            ` : '';

            return `
                <article data-approval-id="${Number(item.id)}" class="krd-approval-card ${typeof isWorkflowFocused === 'function' && isWorkflowFocused('approval', item.id) ? 'workflow-row-highlight' : ''}">
                    <div class="krd-approval-card__main">
                        <div class="krd-approval-card__select">
                            <input type="checkbox" class="bulk-row-checkbox" ${approvalBulkSelection.has(Number(item.id)) ? 'checked' : ''} aria-label="Выбрать согласование" onchange="toggleApprovalBulkSelection(${Number(item.id)}, this.checked)">
                        </div>

                        <div class="krd-approval-card__body">
                            <div class="krd-approval-card__head">
                                <div>
                                    <h3 class="krd-approval-card__title">${workflowEscape(displayTitle)}</h3>
                                    <div class="krd-approval-card__meta">
                                        <span>${isKb ? 'Что согласовать:' : 'Документ:'}</span>
                                        <button class="krd-inline-link" onclick="openProjectFromLink('${safeLink}')">${workflowEscape(displayLink)}</button>
                                        <span>•</span>
                                        <span>Отправил: ${workflowEscape(displayAuthor)}</span>
                                    </div>
                                    <div class="krd-approval-card__submeta">
                                        <span>${isKb ? 'Текущий шаг' : 'Активный этап'}: ${workflowEscape(displayStep)}</span>
                                        <span>•</span>
                                        <span>${workflowEscape(item.sla_status === 'stable' ? 'срок в норме' : item.sla_status || 'срок в норме')}</span>
                                        ${item.due_at_display ? `<span>•</span><span>до ${workflowEscape(item.due_at_display)}</span>` : ''}
                                    </div>
                                </div>
                                <div class="krd-approval-card__badges">
                                    <span class="krd-approval-pill ${approvalUiStatusTone(item.status)}">${workflowEscape(approvalStatusLabel(item.status))}</span>
                                    ${visibleStepUsers.length ? `<span class="krd-approval-pill krd-approval-pill--sla">${workflowEscape(`сейчас: ${visibleStepUsers.join(', ')}`)}</span>` : ''}
                                </div>
                            </div>

                            <div class="krd-approval-route">${routeHtml}</div>
                            ${actions}
                        </div>
                    </div>
                    ${historyBlock}
                </article>
            `;
        }).join('');
    };

    if (typeof renderDeferredHtml === 'function') {
        renderDeferredHtml(container, renderCards, { size: filtered.length, threshold: 40, loadingMessage: 'Загружаю маршруты согласования…' });
    } else {
        container.innerHTML = renderCards();
    }
};

/* Daily approvals workspace: one document, one responsible person, one decision. */
window.__approvalSimpleSearch = window.__approvalSimpleSearch || '';

window.setApprovalSimpleSearch = function(value) {
    window.__approvalSimpleSearch = String(value || '').trim().toLowerCase();
    renderApprovals();
};

function renderApprovalsSimpleMetrics(rows) {
    const mount = document.getElementById('approvalsSimpleMetrics');
    if (!mount) return;
    const currentName = String(currentUser?.name || '');
    const meaningful = rows.filter(item => !isTechnicalApprovalNoise(item));
    const pending = meaningful.filter(item => item.status === 'pending');
    const rework = meaningful.filter(item => item.status === 'rework');
    const mine = pending.filter(item => {
        const assignees = Array.isArray(item.current_assignees) ? item.current_assignees : [];
        return assignees.includes(currentName) || (Array.isArray(item.route) && String(item.route[Number(item.current_step || 0)] || '').includes(currentName));
    });
    mount.innerHTML = `
        <div><span>Ждут решения</span><strong>${pending.length}</strong></div>
        <div><span>Назначено мне</span><strong>${mine.length}</strong></div>
        <div><span>На исправлении</span><strong>${rework.length}</strong></div>
    `;
}

renderApprovals = function() {
    const container = document.getElementById('approvalsListContainer');
    if (!container) return;
    updateApprovalsPageForRole();
    renderApprovalsSimpleMetrics(approvalsDB);

    const currentUserName = String(currentUser?.name || '');
    const currentUserRole = String(currentUser?.role || '');
    const query = String(window.__approvalSimpleSearch || '');
    const rows = approvalsDB.filter(item => {
        if (isTechnicalApprovalNoise(item)) return false;
        const statusMatches = currentApprTab === 'pending'
            ? item.status === 'pending' || item.status === 'rework'
            : item.status === 'completed' || item.status === 'rejected';
        if (!statusMatches) return false;
        return !query || approvalTextBlob(item).includes(query);
    });

    if (!rows.length) {
        const hasQuery = Boolean(query);
        container.innerHTML = `
            <div class="approvals-simple-empty">
                <strong>${hasQuery ? 'Ничего не найдено' : (currentApprTab === 'pending' ? 'Документов на согласовании нет' : 'Завершённых согласований нет')}</strong>
                <span>${hasQuery ? 'Измените запрос или очистите поиск.' : (currentApprTab === 'pending' ? 'Создайте согласование, когда документ действительно требует решения другого сотрудника.' : 'Результаты появятся здесь после первого решения.')}</span>
                ${hasQuery ? '<button class="btn-secondary" type="button" onclick="document.getElementById(\'approvalsSimpleSearch\').value=\'\'; setApprovalSimpleSearch(\'\')">Очистить поиск</button>' : ''}
            </div>`;
        return;
    }

    container.innerHTML = rows.map(item => {
        const history = Array.isArray(item.history) ? item.history : [];
        const route = Array.isArray(item.route) ? item.route : [];
        const currentStep = Number(item.current_step || 0);
        const rawAssignees = Array.isArray(item.current_assignees) && item.current_assignees.length
            ? item.current_assignees
            : String(route[currentStep] || '').split(' и ').map(value => value.trim()).filter(Boolean);
        const assignees = rawAssignees.map(cleanApprovalPersonName).filter(Boolean);
        const alreadyApproved = history.some(entry => entry.startsWith(`✅ ${currentUserName}`) && entry.includes(`(Этап ${currentStep + 1})`));
        const assignedToMe = (item.status === 'pending' || item.status === 'rework') && rawAssignees.includes(currentUserName) && !alreadyApproved;
        const canAct = assignedToMe || currentUserRole === 'Директор';
        const displayTitle = approvalHumanTitle(item);
        const displayLink = approvalHumanLink(item);
        const safeLink = approvalUiJsString(item.item_link || '');
        const status = approvalStatusLabel(item.status);
        const lastHistory = history.length ? history[history.length - 1] : '';
        const openButton = item.item_link
            ? `<button class="btn-secondary" type="button" onclick="openProjectFromLink('${safeLink}')">Открыть документ</button>`
            : '<button class="btn-secondary" type="button" disabled>Документ не указан</button>';
        const actions = currentApprTab === 'pending' && canAct ? `
            <div class="approvals-simple-card__actions">
                <button class="btn-success" type="button" onclick="processApprovalStep(${Number(item.id)}, 'approve')">Согласовать</button>
                <button class="btn-secondary" type="button" onclick="processApprovalStep(${Number(item.id)}, 'return_rework')">Вернуть на исправление</button>
                <button class="btn-danger" type="button" onclick="processApprovalStep(${Number(item.id)}, 'reject')">Отклонить</button>
                <button class="btn-secondary" type="button" onclick="processApprovalStep(${Number(item.id)}, 'delegate')">Передать другому</button>
            </div>` : '';
        return `
            <article data-approval-id="${Number(item.id)}" class="approvals-simple-card ${item.status === 'rework' ? 'is-rework' : ''}">
                <header>
                    <div><span class="krd-approval-pill ${approvalUiStatusTone(item.status)}">${workflowEscape(status)}</span><h3>${workflowEscape(displayTitle)}</h3><p>${workflowEscape(displayLink)}</p></div>
                    ${openButton}
                </header>
                <div class="approvals-simple-card__facts">
                    <div><span>Отправил</span><strong>${workflowEscape(cleanApprovalPersonName(item.author) || 'Не указан')}</strong></div>
                    <div><span>Сейчас проверяет</span><strong>${workflowEscape(assignees.join(', ') || 'Не назначено')}</strong></div>
                    <div><span>Срок решения</span><strong>${workflowEscape(item.due_at_display || 'Без срока')}</strong></div>
                </div>
                ${lastHistory && currentApprTab === 'completed' ? `<div class="approvals-simple-card__result"><span>Последнее решение</span><strong>${workflowEscape(lastHistory)}</strong></div>` : ''}
                ${actions}
            </article>`;
    }).join('');
};
