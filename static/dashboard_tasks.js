// ==========================================
// TASK CENTER
// ==========================================

const TASK_CENTER_COLUMN_META = [
    { key: 'select', label: '', width: 44, sticky: true, hidden: false, system: true },
    { key: 'status', label: 'Статус', width: 110, sticky: true, hidden: false },
    { key: 'title', label: 'Задача', width: 240, sticky: true, hidden: false },
    { key: 'project', label: 'Проект', width: 140, hidden: false },
    { key: 'author', label: 'Поручил', width: 160, hidden: true },
    { key: 'executor', label: 'Исполнитель', width: 150, hidden: false },
    { key: 'priority', label: 'Приоритет', width: 130, hidden: true },
    { key: 'deadline', label: 'Срок', width: 130, hidden: false },
    { key: 'timeleft', label: 'Осталось', width: 120, hidden: false },
    { key: 'comments', label: 'Комментарии', width: 110, hidden: true },
    { key: 'updated_at', label: 'Обновлено', width: 150, hidden: true },
];

let currentTaskTab = 'active';
let taskCenterState = {
    mode: 'list',
    search: '',
    sortBy: 'deadline',
    sortDir: 'asc',
    selectedTaskId: null,
    selectedIds: [],
    filters: {
        statusScope: 'active',
        priority: 'all',
    },
    columns: loadTaskCenterColumns(),
    savedFilters: loadTaskCenterSavedFilters(),
};

function loadTaskCenterColumns() {
    try {
        const raw = JSON.parse(localStorage.getItem('korda_task_center_columns') || 'null');
        if (Array.isArray(raw) && raw.length) return raw;
    } catch (e) {}
    return TASK_CENTER_COLUMN_META.map(item => ({ ...item }));
}

function saveTaskCenterColumns() {
    localStorage.setItem('korda_task_center_columns', JSON.stringify(taskCenterState.columns));
}

function loadTaskCenterSavedFilters() {
    try {
        const raw = JSON.parse(localStorage.getItem('korda_task_center_saved_filters') || '[]');
        return Array.isArray(raw) ? raw : [];
    } catch (e) {
        return [];
    }
}

function saveTaskCenterSavedFilters() {
    localStorage.setItem('korda_task_center_saved_filters', JSON.stringify(taskCenterState.savedFilters));
}

function taskCenterStorageKey(key) {
    return `korda_task_center_${currentUser?.email || 'guest'}_${key}`;
}

function isDesignOfficeTaskRole() {
    const role = String(currentUser?.role || '').trim().toLowerCase();
    return role === 'конструкторское бюро' || role.includes('конструктор');
}

function taskCenterPersonMatches(value, name) {
    const actual = String(value || '').trim();
    const expected = String(name || '').trim();
    return Boolean(expected) && (actual === expected || actual.startsWith(`${expected} (И.О.`));
}

function taskCenterCanManage(task) {
    return String(currentUser?.role || '').trim() === 'Директор'
        || taskCenterPersonMatches(task?.author, currentUser?.name);
}

function taskCenterCanWork(task) {
    return taskCenterCanManage(task)
        || taskCenterPersonMatches(task?.executor, currentUser?.name);
}

function taskCenterIsExecutor(task) {
    return taskCenterPersonMatches(task?.executor, currentUser?.name);
}

function updateTaskCenterForRole() {
    const isKb = isDesignOfficeTaskRole();
    const view = document.getElementById('tasksView');
    if (view) view.classList.toggle('task-center-page--kb', isKb);
    const eyebrow = document.querySelector('#tasksView .view-eyebrow');
    const title = document.querySelector('#tasksView .view-title');
    const subtitle = document.querySelector('#tasksView .view-subtitle');
    const search = document.getElementById('taskCenterSearch');
    if (eyebrow) eyebrow.textContent = isKb ? 'Конструкторское бюро' : 'Рабочие поручения';
    if (title) title.textContent = isKb ? 'Мои поручения КБ' : 'Поручения';
    if (subtitle) {
        subtitle.textContent = isKb
            ? 'Здесь только то, что нужно выполнить: открыть поручение, понять задачу, написать комментарий и закрыть после выполнения.'
            : 'Простой список: что нужно сделать, кто отвечает, какой срок и что уже выполнено.';
    }
    if (search) {
        search.placeholder = isKb
            ? 'Найти поручение по названию, описанию или проекту'
            : 'Поиск по задаче, описанию, проекту, исполнителю';
    }
    taskCenterState.mode = 'list';
    taskCenterState.selectedIds = [];
    if (isKb && !['active', 'completed', 'overdue', 'all'].includes(taskCenterState.filters.statusScope)) {
        taskCenterState.filters.statusScope = 'active';
    }
}

function parseTaskDate(value) {
    if (!value) return null;
    const [datePart, timePart = '00:00'] = String(value).trim().split(' ');
    const [day, month, year] = datePart.split('.').map(Number);
    const [hour, minute] = timePart.split(':').map(Number);
    if (!day || !month || !year) return null;
    const date = new Date(year, month - 1, day, hour || 0, minute || 0);
    return Number.isNaN(date.getTime()) ? null : date;
}

function formatTaskDate(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return 'Без даты';
    return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`;
}

function taskDateToInputValue(value) {
    const raw = String(value || '').trim().split(' ')[0];
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    const match = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    return match ? `${match[3]}-${match[2]}-${match[1]}` : '';
}

function taskDateFromInputValue(value) {
    const match = String(value || '').trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return match ? `${match[3]}.${match[2]}.${match[1]}` : String(value || '').trim();
}

function formatTaskDateTime(timestamp) {
    const date = new Date(Number(timestamp || 0) * 1000);
    if (Number.isNaN(date.getTime())) return '—';
    return `${formatTaskDate(date)} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function taskProjectName(task) {
    const project = Array.isArray(projectsDB) ? projectsDB.find(item => Number(item.id || 0) === Number(task.project_id || 0)) : null;
    return project?.name || (task.project_id ? `Проект #${task.project_id}` : 'Без проекта');
}

function taskCommentCount(task) {
    return Array.isArray(task.chat) ? task.chat.length : 0;
}

function taskLastActor(task) {
    const chat = Array.isArray(task.chat) ? task.chat : [];
    return chat.length ? (chat[chat.length - 1].user || '') : (task.executor || '');
}

function getTaskTimeLeft(dateStr) {
    const deadlineDate = parseTaskDate(dateStr);
    if (!deadlineDate) return '<span class="task-center-time task-center-time--neutral">Без срока</span>';
    const now = new Date();
    const diff = deadlineDate - now;
    if (diff <= 0) return `<span class="task-center-time task-center-time--danger">Просрочено</span>`;
    const dLeft = Math.floor(diff / 86400000);
    const hLeft = Math.floor((diff / 3600000) % 24);
    const mLeft = Math.floor((diff / 60000) % 60);
    const parts = [];
    if (dLeft > 0) parts.push(`${dLeft} д`);
    if (hLeft > 0 || dLeft > 0) parts.push(`${hLeft} ч`);
    parts.push(`${mLeft} мин`);
    const className = dLeft >= 3 ? 'task-center-time--ok' : 'task-center-time--warn';
    return `<span class="task-center-time ${className}">${parts.join(' ')}</span>`;
}

function isTaskOverdue(task) {
    if ((task.status || '') === 'completed') return false;
    const date = parseTaskDate(task.deadline);
    return date ? date.getTime() < Date.now() : false;
}

function isTaskUnread(task) {
    const map = JSON.parse(localStorage.getItem(taskCenterStorageKey('seen_map')) || '{}');
    const seenAt = Number(map[String(task.id)] || 0);
    const updatedAt = Number(task.updated_at || 0);
    const lastAuthor = taskLastActor(task);
    return updatedAt > seenAt && lastAuthor && lastAuthor !== currentUser?.name;
}

function markTaskRead(taskId) {
    const task = tasksDB.find(item => Number(item.id) === Number(taskId));
    if (!task) return;
    const map = JSON.parse(localStorage.getItem(taskCenterStorageKey('seen_map')) || '{}');
    map[String(taskId)] = Number(task.updated_at || Math.floor(Date.now() / 1000));
    localStorage.setItem(taskCenterStorageKey('seen_map'), JSON.stringify(map));
}

function getTaskStatusMeta(task) {
    if ((task.status || '') === 'completed') return { label: 'Выполнено', className: 'done' };
    if (['assigned', 'new'].includes(task.status || '')) return { label: 'Назначено', className: 'pending' };
    if (isTaskOverdue(task)) return { label: 'Просрочено', className: 'overdue' };
    return { label: 'В работе', className: 'active' };
}

function getTaskPriorityMeta(priority) {
    return priority === 'high'
        ? { label: 'Высокий', className: 'high' }
        : { label: 'Нормальный', className: 'normal' };
}

function cloneFilters(filters) {
    return JSON.parse(JSON.stringify(filters || {}));
}

function syncTaskCenterControls() {
    updateTaskCenterForRole();
    const search = document.getElementById('taskCenterSearch');
    const status = document.getElementById('taskCenterStatusFilter');
    const priority = document.getElementById('taskCenterPriorityFilter');
    const saved = document.getElementById('taskCenterSavedFilter');
    if (search) search.value = taskCenterState.search || '';
    if (status) status.value = taskCenterState.filters.statusScope || 'active';
    if (priority) priority.value = taskCenterState.filters.priority || 'all';
    if (saved) {
        saved.innerHTML = '<option value="">Сохранённые фильтры</option>' + taskCenterState.savedFilters.map((item, index) => `<option value="${index}">${escapeHtml(item.name)}</option>`).join('');
    }
}

function getTaskCenterRows() {
    const search = String(taskCenterState.search || '').trim().toLowerCase();
    let rows = Array.isArray(tasksDB) ? [...tasksDB] : [];
    if (isDesignOfficeTaskRole()) {
        const me = String(currentUser?.name || '').trim();
        rows = rows.filter(task => {
            const executor = String(task.executor || '').trim();
            const author = String(task.author || '').trim();
            return !me || executor === me || author === me;
        });
    }

    rows = rows.filter(task => {
        const statusScope = taskCenterState.filters.statusScope || 'active';
        if (statusScope === 'active' && !['assigned', 'new', 'active'].includes(task.status || '')) return false;
        if (statusScope === 'completed' && task.status !== 'completed') return false;
        if (statusScope === 'overdue' && !isTaskOverdue(task)) return false;
        if (statusScope === 'mine' && task.executor !== currentUser?.name) return false;
        if (statusScope === 'delegated' && task.author !== currentUser?.name) return false;
        if ((taskCenterState.filters.priority || 'all') !== 'all' && (task.priority || 'normal') !== taskCenterState.filters.priority) return false;

        if (search) {
            const haystack = [
                task.title,
                task.description,
                task.author,
                task.executor,
                taskProjectName(task),
                task.deadline,
            ].join(' ').toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });

    const dir = taskCenterState.sortDir === 'desc' ? -1 : 1;
    const sortBy = taskCenterState.sortBy || 'deadline';
    rows.sort((a, b) => {
        let left = '';
        let right = '';
        if (sortBy === 'deadline') {
            left = parseTaskDate(a.deadline)?.getTime() || 0;
            right = parseTaskDate(b.deadline)?.getTime() || 0;
        } else if (sortBy === 'updated_at') {
            left = Number(a.updated_at || 0);
            right = Number(b.updated_at || 0);
        } else if (sortBy === 'comments') {
            left = taskCommentCount(a);
            right = taskCommentCount(b);
        } else if (sortBy === 'project') {
            left = taskProjectName(a);
            right = taskProjectName(b);
        } else {
            left = String(a[sortBy] || '').toLowerCase();
            right = String(b[sortBy] || '').toLowerCase();
        }
        if (left === right) return Number(b.id || 0) - Number(a.id || 0);
        return left > right ? dir : -dir;
    });

    return rows;
}

function taskCenterSwitchMode(mode) {
    taskCenterState.mode = mode;
    ['list', 'deadlines', 'plan', 'calendar', 'gantt'].forEach(key => {
        const button = document.getElementById(`taskMode${key.charAt(0).toUpperCase()}${key.slice(1)}`);
        if (button) button.classList.toggle('active', key === mode);
    });
    renderTasks();
}

function taskCenterHandleSearch(value) {
    taskCenterState.search = value || '';
    renderTasks();
}

function taskCenterSetFilter(key, value) {
    taskCenterState.filters[key] = value;
    if (key === 'statusScope') currentTaskTab = value === 'completed' ? 'completed' : 'active';
    renderTasks();
}

function switchTaskTab(tab) {
    currentTaskTab = tab;
    taskCenterState.filters.statusScope = tab === 'completed' ? 'completed' : 'active';
    taskCenterState.mode = 'list';
    renderTasks();
}

function taskCenterSort(key) {
    if (taskCenterState.sortBy === key) taskCenterState.sortDir = taskCenterState.sortDir === 'asc' ? 'desc' : 'asc';
    else {
        taskCenterState.sortBy = key;
        taskCenterState.sortDir = key === 'deadline' ? 'asc' : 'desc';
    }
    renderTasks();
}

function taskCenterToggleSelect(taskId, checked) {
    const task = tasksDB.find(item => Number(item.id) === Number(taskId));
    if (!taskCenterCanManage(task)) return;
    const id = Number(taskId);
    const set = new Set(taskCenterState.selectedIds.map(Number));
    if (checked) set.add(id);
    else set.delete(id);
    taskCenterState.selectedIds = Array.from(set);
    renderTaskCenterBulkBar();
}

function taskCenterToggleSelectAll(checked) {
    taskCenterState.selectedIds = checked
        ? getTaskCenterRows().filter(taskCenterCanManage).map(item => Number(item.id))
        : [];
    renderTasks();
}

function taskCenterSelectTask(taskId) {
    taskCenterState.selectedTaskId = Number(taskId);
    markTaskRead(taskId);
    renderTasks();
}

function taskCenterOpenDetails(taskId) {
    taskCenterState.selectedTaskId = Number(taskId);
    markTaskRead(taskId);
    renderTasks();
    window.requestAnimationFrame(() => {
        const panel = document.querySelector('#tasksView .task-center-side__card');
        if (!panel) return;
        panel.classList.remove('is-opened-from-list');
        void panel.offsetWidth;
        panel.classList.add('is-opened-from-list');
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        window.setTimeout(() => panel.classList.remove('is-opened-from-list'), 1200);
    });
}

function taskCenterResetLayout() {
    taskCenterState.mode = 'list';
    taskCenterState.search = '';
    taskCenterState.sortBy = 'deadline';
    taskCenterState.sortDir = 'asc';
    taskCenterState.selectedIds = [];
    taskCenterState.filters = { statusScope: 'active', priority: 'all' };
    taskCenterState.columns = TASK_CENTER_COLUMN_META.map(item => ({ ...item }));
    saveTaskCenterColumns();
    renderTasks();
}

function taskCenterSaveCurrentFilter() {
    const name = window.prompt('Название фильтра');
    if (!name) return;
    taskCenterState.savedFilters.push({
        name: name.trim(),
        filters: cloneFilters(taskCenterState.filters),
        search: taskCenterState.search,
        sortBy: taskCenterState.sortBy,
        sortDir: taskCenterState.sortDir,
    });
    saveTaskCenterSavedFilters();
    syncTaskCenterControls();
    showToast('Task Center', 'Фильтр сохранён.');
}

function taskCenterApplySavedFilter(index) {
    if (index === '') return;
    const item = taskCenterState.savedFilters[Number(index)];
    if (!item) return;
    taskCenterState.filters = cloneFilters(item.filters);
    taskCenterState.search = item.search || '';
    taskCenterState.sortBy = item.sortBy || 'deadline';
    taskCenterState.sortDir = item.sortDir || 'asc';
    renderTasks();
}

function taskCenterOpenColumns() {
    const modal = document.getElementById('genericModal');
    if (!modal) return;
    const body = document.getElementById('genModalBody');
    const footer = document.getElementById('genModalFooter');
    const title = document.getElementById('genModalTitle');
    if (!body || !footer || !title) return;
    title.innerText = 'Колонки Task Center';
    body.innerHTML = `
        <div class="task-columns-editor">
            ${taskCenterState.columns.filter(item => !item.system).map(item => `
                <label class="task-columns-editor__row">
                    <input type="checkbox" ${item.hidden ? '' : 'checked'} onchange="taskCenterToggleColumn('${item.key}', this.checked)">
                    <span>${escapeHtml(item.label)}</span>
                </label>
            `).join('')}
        </div>
    `;
    footer.innerHTML = `
        <button class="btn-secondary" onclick="document.getElementById('genericModal').style.display='none'">Закрыть</button>
        <button class="btn-primary" onclick="taskCenterRestoreDefaultColumns()">По умолчанию</button>
    `;
    modal.style.display = 'flex';
}

function taskCenterToggleColumn(key, isVisible) {
    taskCenterState.columns = taskCenterState.columns.map(item => item.key === key ? { ...item, hidden: !isVisible } : item);
    saveTaskCenterColumns();
    renderTasks();
}

function taskCenterRestoreDefaultColumns() {
    taskCenterState.columns = TASK_CENTER_COLUMN_META.map(item => ({ ...item }));
    saveTaskCenterColumns();
    document.getElementById('genericModal').style.display = 'none';
    renderTasks();
}

function taskCenterVisibleColumns() {
    return taskCenterState.columns.filter(item => !item.hidden);
}

function taskCell(task, column) {
    const statusMeta = getTaskStatusMeta(task);
    const priorityMeta = getTaskPriorityMeta(task.priority || 'normal');
    if (column.key === 'select') {
        return taskCenterCanManage(task)
            ? `<input type="checkbox" ${taskCenterState.selectedIds.includes(Number(task.id)) ? 'checked' : ''} onclick="event.stopPropagation()" onchange="taskCenterToggleSelect(${task.id}, this.checked)">`
            : '';
    }
    if (column.key === 'status') {
        if (!taskCenterCanWork(task)) return `<span class="task-status-pill task-status-pill--${statusMeta.className}">${statusMeta.label}</span>`;
        return `
            <div class="task-center-status-cell">
                <span class="task-status-pill task-status-pill--${statusMeta.className}">${statusMeta.label}</span>
                <select class="task-inline-select" onclick="event.stopPropagation()" onchange="taskCenterQuickUpdate(${task.id}, 'status', this.value)">
                    <option value="active" ${task.status === 'active' ? 'selected' : ''}>В работе</option>
                    <option value="completed" ${task.status === 'completed' ? 'selected' : ''}>Выполнено</option>
                </select>
            </div>
        `;
    }
    if (column.key === 'title') {
        return `
            <div class="task-title-cell">
                <div class="task-priority-dot task-priority-dot--${priorityMeta.className}"></div>
                <div>
                    <div class="task-title-cell__title">${escapeHtml(task.title || 'Без названия')}</div>
                    <div class="task-title-cell__sub">${escapeHtml((task.description || '').slice(0, 120) || 'Без описания')}</div>
                </div>
                ${isTaskUnread(task) ? '<span class="task-unread-dot"></span>' : ''}
            </div>
        `;
    }
    if (column.key === 'project') return escapeHtml(taskProjectName(task));
    if (column.key === 'author') return escapeHtml(task.author || '—');
    if (column.key === 'executor') {
        if (!taskCenterCanManage(task)) return escapeHtml(task.executor || '—');
        return `
            <select class="task-inline-select task-inline-select--wide" onclick="event.stopPropagation()" onchange="taskCenterQuickUpdate(${task.id}, 'executor', this.value)">
                ${allUsersDB.filter(user => user.status === 'approved').map(user => `<option value="${escapeHtml(user.name)}" ${user.name === task.executor ? 'selected' : ''}>${escapeHtml(user.name)}</option>`).join('')}
            </select>
        `;
    }
    if (column.key === 'priority') {
        if (!taskCenterCanManage(task)) return escapeHtml(priorityMeta.label);
        return `
            <select class="task-inline-select" onclick="event.stopPropagation()" onchange="taskCenterQuickUpdate(${task.id}, 'priority', this.value)">
                <option value="normal" ${task.priority !== 'high' ? 'selected' : ''}>Нормальный</option>
                <option value="high" ${task.priority === 'high' ? 'selected' : ''}>Высокий</option>
            </select>
        `;
    }
    if (column.key === 'deadline') return escapeHtml(task.deadline || '—');
    if (column.key === 'timeleft') return getTaskTimeLeft(task.deadline || '');
    if (column.key === 'comments') return `<span class="task-count-badge">${taskCommentCount(task)}</span>`;
    if (column.key === 'updated_at') return escapeHtml(formatTaskDateTime(task.updated_at));
    return escapeHtml(task[column.key] || '—');
}

function renderTaskTable(rows) {
    const columns = taskCenterVisibleColumns();
    const manageableRows = rows.filter(taskCenterCanManage);
    let stickyLeft = 0;
    const stickyMap = {};
    columns.forEach(column => {
        if (column.sticky) {
            stickyMap[column.key] = stickyLeft;
            stickyLeft += Number(column.width || 160);
        }
    });

    return `
        <div class="task-table-shell">
            <table class="task-table">
                <thead>
                    <tr>
                        ${columns.map(column => `
                            <th
                                class="${column.sticky ? 'is-sticky' : ''}"
                                style="width:${column.width || 160}px;min-width:${column.width || 160}px;max-width:${column.width || 160}px;${column.sticky ? `left:${stickyMap[column.key]}px;` : ''}"
                            >
                                ${column.key === 'select'
                                    ? (manageableRows.length ? `<input type="checkbox" ${manageableRows.every(task => taskCenterState.selectedIds.includes(Number(task.id))) ? 'checked' : ''} onchange="taskCenterToggleSelectAll(this.checked)">` : '')
                                    : `<button class="task-th-btn" onclick="taskCenterSort('${column.key}')">${escapeHtml(column.label)}${taskCenterState.sortBy === column.key ? `<span>${taskCenterState.sortDir === 'asc' ? '↑' : '↓'}</span>` : ''}</button>`
                                }
                            </th>
                        `).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(task => `
                        <tr class="${taskCenterState.selectedTaskId === Number(task.id) ? 'is-active' : ''}" onclick="taskCenterSelectTask(${task.id})">
                            ${columns.map(column => `
                                <td
                                    class="${column.sticky ? 'is-sticky' : ''}"
                                    style="width:${column.width || 160}px;min-width:${column.width || 160}px;max-width:${column.width || 160}px;${column.sticky ? `left:${stickyMap[column.key]}px;` : ''}"
                                >
                                    ${taskCell(task, column)}
                                </td>
                            `).join('')}
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderKbTaskList(rows) {
    const visible = rows.length ? rows : [];
    if (!visible.length) {
        return '<div class="task-center-empty">Для КБ сейчас нет поручений по выбранным условиям.</div>';
    }
    return `
        <div class="kb-task-list">
            ${visible.map(task => {
                const statusMeta = getTaskStatusMeta(task);
                const priorityMeta = getTaskPriorityMeta(task.priority || 'normal');
                const isSelected = taskCenterState.selectedTaskId === Number(task.id);
                const canManage = taskCenterCanManage(task);
                const canWork = taskCenterCanWork(task);
                return `
                    <article class="kb-task-card ${isSelected ? 'is-active' : ''}" onclick="taskCenterSelectTask(${Number(task.id)})" data-task-id="${Number(task.id)}">
                        <div class="kb-task-card__main">
                            <div class="kb-task-card__top">
                                <span class="task-status-pill task-status-pill--${statusMeta.className}">${escapeHtml(statusMeta.label)}</span>
                                <span class="kb-task-card__deadline">${escapeHtml(task.deadline || 'Без срока')}</span>
                            </div>
                            <h3>${escapeHtml(task.title || 'Без названия')}</h3>
                            <p>${escapeHtml((task.description || '').slice(0, 180) || 'Описание не добавлено.')}</p>
                            <div class="kb-task-card__meta">
                                <span>Исполнитель: ${escapeHtml(task.executor || 'Не назначен')}</span>
                                <span>Поручил: ${escapeHtml(task.author || 'Не указан')}</span>
                                <span>Проект: ${escapeHtml(taskProjectName(task))}</span>
                                <span>Приоритет: ${escapeHtml(priorityMeta.label)}</span>
                            </div>
                        </div>
                        <div class="kb-task-card__actions" onclick="event.stopPropagation()">
                            ${taskCenterIsExecutor(task) && ['assigned', 'new'].includes(task.status || '') ? `<button class="btn-primary" onclick="taskCenterQuickUpdate(${Number(task.id)}, 'status', 'active')">Взять в работу</button>` : ''}
                            ${canWork && task.status === 'active' ? `<button class="btn-primary" onclick="taskCenterQuickUpdate(${Number(task.id)}, 'status', 'completed')">Закрыть как выполнено</button>` : ''}
                            ${canWork && task.status === 'completed' ? `<button class="btn-secondary" onclick="taskCenterQuickUpdate(${Number(task.id)}, 'status', 'active')">Вернуть в работу</button>` : ''}
                            ${canManage ? `<button class="btn-secondary" onclick="taskCenterAssignTask(${Number(task.id)})">Передать</button>` : ''}
                            <button class="btn-secondary" onclick="taskCenterOpenDetails(${Number(task.id)})">Открыть детали</button>
                        </div>
                    </article>
                `;
            }).join('')}
        </div>
    `;
}

function renderTaskDeadlineBoard(rows) {
    const buckets = [
        { key: 'overdue', label: 'Просрочено', filter: task => isTaskOverdue(task) },
        { key: 'today', label: 'Сегодня', filter: task => {
            const date = parseTaskDate(task.deadline);
            if (!date || task.status === 'completed') return false;
            const now = new Date();
            return date.toDateString() === now.toDateString();
        }},
        { key: 'soon', label: 'Ближайшие 3 дня', filter: task => {
            const date = parseTaskDate(task.deadline);
            if (!date || task.status === 'completed') return false;
            const diff = date.getTime() - Date.now();
            return diff > 0 && diff <= 3 * 86400000;
        }},
        { key: 'later', label: 'Позже', filter: task => {
            const date = parseTaskDate(task.deadline);
            if (!date) return true;
            return !isTaskOverdue(task) && date.getTime() - Date.now() > 3 * 86400000;
        }},
    ];
    return `<div class="task-deadline-board">
        ${buckets.map(bucket => `
            <section class="task-deadline-column">
                <div class="task-deadline-column__head">
                    <span>${bucket.label}</span>
                    <b>${rows.filter(bucket.filter).length}</b>
                </div>
                <div class="task-deadline-column__list">
                    ${rows.filter(bucket.filter).map(task => `
                        <article class="task-deadline-card" onclick="taskCenterSelectTask(${task.id})">
                            <div class="task-deadline-card__title">${escapeHtml(task.title || '')}</div>
                            <div class="task-deadline-card__meta">${escapeHtml(task.executor || '—')} · ${escapeHtml(task.deadline || '—')}</div>
                            <div class="task-deadline-card__time">${getTaskTimeLeft(task.deadline || '')}</div>
                        </article>
                    `).join('') || '<div class="task-center-empty task-center-empty--small">Пусто</div>'}
                </div>
            </section>
        `).join('')}
    </div>`;
}

function renderTaskPlan(rows) {
    const groups = [
        { key: 'mine', label: 'Мои сейчас', rows: rows.filter(task => task.executor === currentUser?.name && ['assigned', 'new', 'active'].includes(task.status || '')) },
        { key: 'delegated', label: 'Ожидаю от коллег', rows: rows.filter(task => task.author === currentUser?.name && task.executor !== currentUser?.name && ['assigned', 'new', 'active'].includes(task.status || '')) },
        { key: 'done', label: 'Закрыто', rows: rows.filter(task => task.status === 'completed').slice(0, 8) },
    ];
    return `<div class="task-plan-grid">
        ${groups.map(group => `
            <section class="task-plan-column">
                <div class="task-plan-column__head">${group.label}<span>${group.rows.length}</span></div>
                <div class="task-plan-column__body">
                    ${group.rows.map(task => `
                        <article class="task-plan-card" onclick="taskCenterSelectTask(${task.id})">
                            <div class="task-plan-card__title">${escapeHtml(task.title || '')}</div>
                            <div class="task-plan-card__meta">${escapeHtml(taskProjectName(task))}</div>
                            <div class="task-plan-card__footer">
                                <span>${escapeHtml(task.executor || '—')}</span>
                                <span>${escapeHtml(task.deadline || '—')}</span>
                            </div>
                        </article>
                    `).join('') || '<div class="task-center-empty task-center-empty--small">Нет задач</div>'}
                </div>
            </section>
        `).join('')}
    </div>`;
}

function renderTaskCalendar(rows) {
    const days = [];
    const today = new Date();
    for (let offset = 0; offset < 14; offset += 1) {
        const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() + offset);
        const iso = date.toDateString();
        days.push({
            key: iso,
            label: formatTaskDate(date),
            items: rows.filter(task => parseTaskDate(task.deadline)?.toDateString() === iso),
        });
    }
    return `<div class="task-calendar-grid">
        ${days.map(day => `
            <section class="task-calendar-day">
                <div class="task-calendar-day__head">${day.label}<span>${day.items.length}</span></div>
                <div class="task-calendar-day__body">
                    ${day.items.map(task => `
                        <button class="task-calendar-item" onclick="taskCenterSelectTask(${task.id})">
                            <span>${escapeHtml(task.title || '')}</span>
                            <small>${escapeHtml(task.executor || '')}</small>
                        </button>
                    `).join('') || '<div class="task-center-empty task-center-empty--small">Нет задач</div>'}
                </div>
            </section>
        `).join('')}
    </div>`;
}

function renderTaskGantt(rows) {
    const dated = rows.filter(task => parseTaskDate(task.deadline));
    if (!dated.length) return '<div class="task-center-empty">Нет задач со сроком для диаграммы Ганта.</div>';
    const starts = dated.map(task => parseTaskDate(task.created_at) || new Date());
    const ends = dated.map(task => parseTaskDate(task.deadline));
    const min = Math.min(...starts.map(date => date.getTime()));
    const max = Math.max(...ends.map(date => date.getTime()));
    const range = Math.max(1, max - min);
    return `<div class="task-gantt-list">
        ${dated.map(task => {
            const start = (parseTaskDate(task.created_at) || new Date()).getTime();
            const end = (parseTaskDate(task.deadline) || new Date()).getTime();
            const left = ((start - min) / range) * 100;
            const width = Math.max(6, ((end - start) / range) * 100);
            return `
                <div class="task-gantt-row" onclick="taskCenterSelectTask(${task.id})">
                    <div class="task-gantt-row__meta">
                        <div class="task-gantt-row__title">${escapeHtml(task.title || '')}</div>
                        <div class="task-gantt-row__sub">${escapeHtml(task.executor || '—')} · ${escapeHtml(task.deadline || '—')}</div>
                    </div>
                    <div class="task-gantt-row__track">
                        <div class="task-gantt-row__bar task-gantt-row__bar--${getTaskStatusMeta(task).className}" style="left:${left}%; width:${width}%"></div>
                    </div>
                </div>
            `;
        }).join('')}
    </div>`;
}

function renderTaskCenterCounters(rows) {
    const counters = [
        { label: 'Активные', value: rows.filter(task => ['assigned', 'new', 'active'].includes(task.status || '')).length, tone: 'primary' },
        { label: 'Просрочено', value: rows.filter(task => isTaskOverdue(task)).length, tone: 'danger' },
        { label: 'Комментарии', value: rows.reduce((acc, task) => acc + taskCommentCount(task), 0), tone: 'neutral' },
        { label: 'Непрочитано', value: rows.filter(task => isTaskUnread(task)).length, tone: 'warning' },
    ];
    const container = document.getElementById('taskCenterCounters');
    if (!container) return;
    container.innerHTML = counters.map(counter => `
        <article class="task-counter task-counter--${counter.tone}">
            <div class="task-counter__label">${counter.label}</div>
            <div class="task-counter__value">${counter.value}</div>
        </article>
    `).join('');
}

function renderTaskCenterBulkBar() {
    const bar = document.getElementById('taskCenterBulkBar');
    if (!bar) return;
    const ids = taskCenterState.selectedIds || [];
    if (!ids.length) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'flex';
    bar.innerHTML = `
        <div class="task-center-bulkbar__meta">Выбрано: <b>${ids.length}</b></div>
        <div class="task-center-bulkbar__actions">
            <button class="btn-secondary" onclick="taskCenterBulkUpdate('status', 'active')">В работу</button>
            <button class="btn-secondary" onclick="taskCenterBulkUpdate('status', 'completed')">Выполнить</button>
            <button class="btn-secondary" onclick="taskCenterBulkUpdate('priority', 'high')">Высокий приоритет</button>
            <button class="btn-secondary" onclick="taskCenterBulkAssign()">Передать</button>
            <button class="btn-danger" onclick="taskCenterClearSelection()">Снять выбор</button>
        </div>
    `;
}

function renderTaskDetail() {
    const body = document.getElementById('taskDetailBody');
    const title = document.getElementById('taskDetailTitle');
    if (!body || !title) return;
    const task = tasksDB.find(item => Number(item.id) === Number(taskCenterState.selectedTaskId));
    if (!task) {
        title.innerText = 'Выбери задачу';
        body.innerHTML = '<div class="task-center-empty">Открой строку в реестре, чтобы увидеть историю, комментарии и быстрые действия.</div>';
        return;
    }
    title.innerText = task.title || 'Без названия';
    const history = Array.isArray(task.history) ? task.history : [];
    const chat = Array.isArray(task.chat) ? task.chat : [];
    const canManage = taskCenterCanManage(task);
    const canWork = taskCenterCanWork(task);
    body.innerHTML = `
        <div class="task-detail-grid">
            <div class="task-detail-item"><span>Статус</span><b>${escapeHtml(getTaskStatusMeta(task).label)}</b></div>
            <div class="task-detail-item"><span>Срок</span><b>${escapeHtml(task.deadline || 'Без срока')}</b></div>
            <div class="task-detail-item"><span>Исполнитель</span><b>${escapeHtml(task.executor || 'Не назначен')}</b></div>
            <div class="task-detail-item"><span>Поручил</span><b>${escapeHtml(task.author || 'Не указан')}</b></div>
            <div class="task-detail-item"><span>Проект</span><b>${escapeHtml(taskProjectName(task))}</b></div>
            <div class="task-detail-item"><span>Приоритет</span><b>${escapeHtml(getTaskPriorityMeta(task.priority || 'normal').label)}</b></div>
        </div>
        <div class="task-detail-section">
            <div class="task-detail-section__title">Что нужно сделать</div>
            <div class="task-detail-note">${nl2brSafe(task.description || 'Описание пока не добавлено. Если непонятно — напишите комментарий и уточните задачу.')}</div>
        </div>
        <div class="task-detail-section">
            <div class="task-detail-section__title">Комментарии</div>
            <div class="task-detail-chat">
                ${chat.length ? chat.slice(-6).map(message => `
                    <div class="task-detail-chat__item ${message.user === currentUser?.name ? 'is-mine' : ''}">
                        <div class="task-detail-chat__meta">${escapeHtml(message.user || '')} · ${escapeHtml(message.time || '')}</div>
                        <div class="task-detail-chat__bubble">${nl2brSafe(message.text || '')}</div>
                    </div>
                `).join('') : '<div class="task-center-empty task-center-empty--small">Комментариев пока нет</div>'}
            </div>
            ${canWork ? `<div class="task-detail-chat__composer">
                <textarea id="taskDetailMessage" class="auth-input" rows="3" placeholder="Комментарий по выполнению, вопрос или уточнение"></textarea>
                <button class="btn-primary" onclick="taskCenterSendMessage(${Number(task.id)})">Отправить</button>
            </div>` : '<div class="task-center-empty task-center-empty--small">Комментарии доступны исполнителю, автору поручения и директору.</div>'}
        </div>
        ${history.length ? `
            <details class="task-detail-section task-detail-history-collapse">
                <summary class="task-detail-section__title">История изменений (${history.length})</summary>
                <div class="task-detail-list">
                    ${history.slice(-8).map(item => `<div class="task-detail-history">${escapeHtml(item)}</div>`).join('')}
                </div>
            </details>
        ` : ''}
        <div class="kb-task-detail-actions">
            ${taskCenterIsExecutor(task) && ['assigned', 'new'].includes(task.status || '') ? `<button class="btn-primary" onclick="taskCenterQuickUpdate(${Number(task.id)}, 'status', 'active')">Взять в работу</button>` : ''}
            ${canWork && task.status === 'active' ? `<button class="btn-primary" onclick="taskCenterQuickUpdate(${Number(task.id)}, 'status', 'completed')">Закрыть поручение</button>` : ''}
            ${canWork && task.status === 'completed' ? `<button class="btn-secondary" onclick="taskCenterQuickUpdate(${Number(task.id)}, 'status', 'active')">Вернуть в работу</button>` : ''}
            ${canManage ? `<button class="btn-secondary" onclick="taskCenterAssignTask(${Number(task.id)})">Передать</button>` : ''}
            ${canManage ? `<button class="btn-secondary" onclick="taskCenterQuickUpdate(${Number(task.id)}, 'priority', '${task.priority === 'high' ? 'normal' : 'high'}')">${task.priority === 'high' ? 'Обычный приоритет' : 'Высокий приоритет'}</button>` : ''}
            ${canManage ? `<button class="btn-danger" onclick="taskCenterDeleteTask(${Number(task.id)})">Удалить поручение</button>` : ''}
        </div>
    `;
}

async function taskCenterSendMessage(taskId) {
    const task = tasksDB.find(item => Number(item.id) === Number(taskId));
    if (!taskCenterCanWork(task)) return customAlert('Комментарии доступны только исполнителю, автору поручения и директору.');
    const input = document.getElementById('taskDetailMessage');
    const text = input?.value?.trim();
    if (!text) return;
    const response = await apiCall(`/tasks/${taskId}/messages`, 'POST', { text });
    if (response?.error) return customAlert(response.message || 'Не удалось отправить комментарий.');
    if (input) input.value = '';
    await loadTasks();
    taskCenterState.selectedTaskId = Number(taskId);
    renderTasks();
}

async function taskCenterQuickUpdate(taskId, field, value) {
    const task = tasksDB.find(item => Number(item.id) === Number(taskId));
    if (field === 'status' && !taskCenterCanWork(task)) return customAlert('Менять статус может исполнитель, автор поручения или директор.');
    if (field !== 'status' && !taskCenterCanManage(task)) return customAlert('Изменять поручение может только его автор или директор.');
    const payload = { [field]: value };
    if (field === 'status') payload.status = value;
    const response = await apiCall(`/tasks/${taskId}`, 'PUT', payload);
    if (response?.error) return customAlert(response.message || 'Не удалось обновить задачу.');
    await loadTasks();
    taskCenterState.selectedTaskId = Number(taskId);
    renderTasks();
}

async function taskCenterAssignTask(taskId) {
    const task = tasksDB.find(item => Number(item.id) === Number(taskId));
    if (!taskCenterCanManage(task)) return customAlert('Передавать поручение может только его автор или директор.');
    const users = allUsersDB.filter(user => user.status === 'approved');
    if (!users.length) return customAlert('Нет доступных сотрудников для передачи поручения.');
    const list = users.map((user, index) => `${index + 1}. ${user.name} (${user.role || 'роль не указана'})`).join('\n');
    const answer = await customPrompt(`Кому передать поручение?\n${list}`);
    const assignee = users[Number(answer) - 1];
    if (!assignee) return;
    const response = await apiCall(`/tasks/${taskId}`, 'PUT', { executor: assignee.name });
    if (response?.error) return customAlert(response.message || 'Не удалось передать поручение.');
    await loadTasks();
    taskCenterState.selectedTaskId = Number(taskId);
    renderTasks();
    showToast('Поручения', `Передано: ${assignee.name}`);
}

async function taskCenterDeleteTask(taskId) {
    const task = tasksDB.find(item => Number(item.id) === Number(taskId));
    if (!taskCenterCanManage(task)) return customAlert('Удалить поручение может только тот, кто его создал, или директор.');
    if (!(await customConfirm(`Удалить поручение «${task?.title || 'Без названия'}» безвозвратно?`))) return;
    const response = await apiCall(`/tasks/${taskId}`, 'DELETE');
    if (response?.error) return customAlert(response.message || 'Не удалось удалить поручение.');
    taskCenterState.selectedTaskId = null;
    taskCenterState.selectedIds = taskCenterState.selectedIds.filter(id => Number(id) !== Number(taskId));
    await loadTasks();
    renderTasks();
    showToast('Поручения', 'Поручение удалено');
}

async function taskCenterBulkUpdate(field, value) {
    for (const id of taskCenterState.selectedIds) {
        await apiCall(`/tasks/${id}`, 'PUT', { [field]: value, ...(field === 'status' ? { status: value } : {}) });
    }
    await loadTasks();
    taskCenterClearSelection();
    renderTasks();
}

async function taskCenterBulkAssign() {
    const users = allUsersDB.filter(user => user.status === 'approved');
    const list = users.map((user, index) => `${index + 1}. ${user.name}`).join('\n');
    const answer = await customPrompt(`Кому передать выбранные задачи?\n${list}`);
    const assignee = users[Number(answer) - 1];
    if (!assignee) return;
    for (const id of taskCenterState.selectedIds) {
        await apiCall(`/tasks/${id}`, 'PUT', { executor: assignee.name });
    }
    await loadTasks();
    taskCenterClearSelection();
    renderTasks();
}

function taskCenterClearSelection() {
    taskCenterState.selectedIds = [];
    renderTasks();
}

function renderTasks() {
    syncTaskCenterControls();
    const rows = getTaskCenterRows();
    if (!rows.length) {
        const mount = document.getElementById('taskCenterViewMount');
        if (mount) {
            mount.innerHTML = typeof renderInlineEmptyState === 'function'
                ? renderInlineEmptyState(
                    isDesignOfficeTaskRole() ? 'Для КБ сейчас нет поручений.' : 'Поручений по выбранным условиям нет.',
                    isDesignOfficeTaskRole()
                        ? 'Когда директор, менеджер или производство назначит задачу на КБ, она появится здесь. Пока можно проверить документы или производство.'
                        : 'Сбросьте фильтр, измените поиск или создайте новое поручение.',
                    isDesignOfficeTaskRole()
                        ? '<button class="btn-primary" onclick="navigateTo(\'production\')">Производство</button><button class="btn-secondary" onclick="navigateTo(\'documents\')">Документы</button>'
                        : '<button class="btn-primary" onclick="openCreateTaskModal()">Новое поручение</button><button class="btn-secondary" onclick="taskCenterResetLayout()">Сбросить</button>'
                )
                : '<div class="task-center-empty">Под текущие условия задач не найдено.</div>';
        }
        renderTaskCenterCounters([]);
        taskCenterState.selectedTaskId = null;
        renderTaskCenterBulkBar();
        renderTaskDetail();
        return;
    }

    if (!taskCenterState.selectedTaskId || !rows.some(task => Number(task.id) === Number(taskCenterState.selectedTaskId))) {
        taskCenterState.selectedTaskId = Number(rows[0].id);
        markTaskRead(taskCenterState.selectedTaskId);
    }

    const mount = document.getElementById('taskCenterViewMount');
    if (mount) {
        mount.innerHTML = renderKbTaskList(rows);
    }
    renderTaskCenterCounters(rows);
    renderTaskCenterBulkBar();
    renderTaskDetail();
}

function openCreateTaskModal(preset = {}) {
    const sel = document.getElementById('taskExecutor');
    if (sel) {
        sel.innerHTML = '<option value="" disabled selected>Выберите исполнителя</option>' + allUsersDB.filter(user => user.status === 'approved').map(user => `<option value="${escapeHtml(user.name)}">${escapeHtml(user.name)} (${escapeHtml(user.role)})</option>`).join('');
    }
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('taskForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('taskForm');
    const titleEl = document.getElementById('taskTitle');
    const descEl = document.getElementById('taskDesc');
    const deadlineEl = document.getElementById('taskDeadline');
    const projectEl = document.getElementById('taskProjectId');
    const priorityEl = document.getElementById('taskPriority');
    const recurrenceEl = document.getElementById('taskRecurrence');
    if (titleEl) titleEl.value = preset.title || '';
    if (descEl) descEl.value = preset.description || '';
    if (deadlineEl) {
        deadlineEl.value = taskDateToInputValue(preset.deadline || '');
    }
    if (sel && preset.executor) sel.value = preset.executor;
    if (projectEl) {
        const options = ['<option value="0">Без проекта</option>'].concat((projectsDB || []).map(project => `<option value="${project.id}">${escapeHtml(project.name || `Проект #${project.id}`)}</option>`));
        projectEl.innerHTML = options.join('');
        projectEl.value = String(Number(preset.project_id || 0));
    }
    if (priorityEl) priorityEl.checked = !!preset.high_priority;
    if (recurrenceEl) recurrenceEl.value = preset.recurrence || 'none';
    document.getElementById('createTaskModal').style.display = 'flex';
    if (titleEl) titleEl.focus();
}

async function submitTask() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('taskForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('taskForm');
    const title = document.getElementById('taskTitle').value.trim();
    const desc = document.getElementById('taskDesc').value.trim();
    const exec = document.getElementById('taskExecutor').value;
    const dead = taskDateFromInputValue(document.getElementById('taskDeadline').value);
    const prio = document.getElementById('taskPriority') && document.getElementById('taskPriority').checked ? 'high' : 'normal';
    const recurrence = document.getElementById('taskRecurrence')?.value || 'none';
    const pId = document.getElementById('taskProjectId') ? (parseInt(document.getElementById('taskProjectId').value, 10) || 0) : 0;
    const errors = [];
    if (!title) errors.push({ field: 'taskTitle', message: 'Кратко сформулируйте поручение.' });
    if (!exec) errors.push({ field: 'taskExecutor', message: 'Выберите исполнителя.' });
    if (!dead) errors.push({ field: 'taskDeadline', message: 'Укажите срок исполнения.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'taskForm');
        return;
    }

    const res = await apiCall('/tasks', 'POST', {
        title,
        description: desc,
        author: currentUser.name,
        executor: exec,
        deadline: dead,
        recurrence,
        priority: prio,
        project_id: pId
    });

    if (!res || res.status !== 'success') {
        customAlert("Не удалось сохранить поручение. Проверь поля и повтори.");
        return;
    }

    document.getElementById('createTaskModal').style.display = 'none';
    document.getElementById('taskTitle').value = '';
    document.getElementById('taskDesc').value = '';
    await loadTasks();
    taskCenterState.selectedTaskId = Number(res.id || 0) || (tasksDB[0] ? Number(tasksDB[0].id) : null);
    taskCenterState.filters.statusScope = 'active';
    taskCenterState.mode = 'list';
    renderTasks();
}

window.delegateTask = async function(id) {
    const users = allUsersDB.filter(user => user.status === 'approved');
    const options = users.map((user, index) => `${index + 1} - ${user.name}`).join('\n');
    const userIdx = await customPrompt(`Кому передать задачу?\nВведите номер:\n${options}`);
    const userObj = users[parseInt(userIdx, 10) - 1];
    if (!userObj) return;

    const task = tasksDB.find(item => Number(item.id) === Number(id));
    const history = Array.isArray(task?.history) ? [...task.history] : [];
    history.push(`↘️ ${currentUser.name} перенаправил(а) задачу на ${userObj.name} (${formatTaskDateTime(Math.floor(Date.now() / 1000))})`);
    await apiCall(`/tasks/${id}`, 'PUT', { status: task?.status || 'active', executor: userObj.name, history });
    await loadTasks();
    renderTasks();
};

async function toggleTaskStatus(id, status) {
    await apiCall(`/tasks/${id}`, 'PUT', { status });
    await loadTasks();
    renderTasks();
}

window.renderTasks = renderTasks;
window.switchTaskTab = switchTaskTab;
window.openCreateTaskModal = openCreateTaskModal;
window.submitTask = submitTask;
window.toggleTaskStatus = toggleTaskStatus;
window.taskCenterSwitchMode = taskCenterSwitchMode;
window.taskCenterHandleSearch = taskCenterHandleSearch;
window.taskCenterSetFilter = taskCenterSetFilter;
window.taskCenterApplySavedFilter = taskCenterApplySavedFilter;
window.taskCenterSaveCurrentFilter = taskCenterSaveCurrentFilter;
window.taskCenterResetLayout = taskCenterResetLayout;
window.taskCenterOpenColumns = taskCenterOpenColumns;
window.taskCenterToggleColumn = taskCenterToggleColumn;
window.taskCenterRestoreDefaultColumns = taskCenterRestoreDefaultColumns;
window.taskCenterSelectTask = taskCenterSelectTask;
window.taskCenterOpenDetails = taskCenterOpenDetails;
window.taskCenterToggleSelect = taskCenterToggleSelect;
window.taskCenterToggleSelectAll = taskCenterToggleSelectAll;
window.taskCenterQuickUpdate = taskCenterQuickUpdate;
window.taskCenterAssignTask = taskCenterAssignTask;
window.taskCenterDeleteTask = taskCenterDeleteTask;
window.taskCenterBulkUpdate = taskCenterBulkUpdate;
window.taskCenterBulkAssign = taskCenterBulkAssign;
window.taskCenterClearSelection = taskCenterClearSelection;
window.taskCenterSendMessage = taskCenterSendMessage;
window.taskCenterSort = taskCenterSort;

setInterval(() => {
    const tasksView = document.getElementById('tasksView');
    if (tasksView && tasksView.style.display === 'block') renderTasks();
}, 60000);
