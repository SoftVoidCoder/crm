// ==========================================
// 2. ОТРИСОВКА ДАШБОРДА (ПРОЕКТЫ) И ПОИСК
// ==========================================

let managerWorkbenchDB = null;
let managerWorkbenchLoadedFor = '';
let dashboardUXDB = { favorites: [], recent: [], filters: [], watches: [], today_items: [], watch_events: [], watch_summary: [] };
let dashboardUXLoadedFor = '';
let dashboardUXLoading = false;

function dashboardUXUserKey(suffix) {
    const email = currentUser?.email || 'anonymous';
    return `korda_${suffix}_${email}`;
}

function dashboardUXLoad(key, fallback = []) {
    try {
        const raw = localStorage.getItem(dashboardUXUserKey(key));
        return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
        return fallback;
    }
}

function dashboardUXSave(key, value) {
    localStorage.setItem(dashboardUXUserKey(key), JSON.stringify(value));
}

function dashboardUXCacheKey() {
    return currentUser ? `${currentUser.email}:${currentUser.role || ''}` : 'anonymous';
}

function dashboardUXServerReady() {
    return !!currentUser && dashboardUXLoadedFor === dashboardUXCacheKey();
}

function normalizeDashboardQuickItem(item) {
    if (!item) return null;
    const type = String(item.type || item.entity_type || '');
    const id = item.id ?? item.entity_id ?? '';
    if (!type || id === '') return null;
    return {
        ...item,
        type,
        id: String(id),
        title: String(item.title || id),
        meta: String(item.meta || ''),
        view: String(item.view || item.view_name || ''),
    };
}

async function loadDashboardUXData(force = false) {
    if (!currentUser) {
        dashboardUXDB = { favorites: [], recent: [], filters: [], watches: [], today_items: [], watch_events: [], watch_summary: [] };
        dashboardUXLoadedFor = '';
        return dashboardUXDB;
    }
    const cacheKey = dashboardUXCacheKey();
    if (!force && dashboardUXLoadedFor === cacheKey) return dashboardUXDB;
    if (dashboardUXLoading) return dashboardUXDB;
    dashboardUXLoading = true;
    try {
        const data = await apiCall('/workbench/quick_access');
        const digest = await apiCall('/workbench/watch_digest');
        if (data && !data.error) {
            dashboardUXDB = {
                favorites: Array.isArray(data.favorites) ? data.favorites.map(normalizeDashboardQuickItem).filter(Boolean) : [],
                recent: Array.isArray(data.recent) ? data.recent.map(normalizeDashboardQuickItem).filter(Boolean) : [],
                filters: Array.isArray(data.filters) ? data.filters : [],
                watches: Array.isArray(data.watches) ? data.watches.map(normalizeDashboardQuickItem).filter(Boolean) : [],
                today_items: Array.isArray(data.today_items) ? data.today_items : [],
                watch_events: digest && !digest.error && Array.isArray(digest.events) ? digest.events : [],
                watch_summary: digest && !digest.error && Array.isArray(digest.summary) ? digest.summary : [],
            };
            dashboardUXLoadedFor = cacheKey;
            dashboardUXSave('favorite_items', dashboardUXDB.favorites);
            dashboardUXSave('recent_items', dashboardUXDB.recent);
            dashboardUXSave('dashboard_filters', dashboardUXDB.filters);
            dashboardUXSave('watch_items', dashboardUXDB.watches);
        }
    } catch (error) {
        console.warn('Workbench UX fallback to local storage', error);
    } finally {
        dashboardUXLoading = false;
    }
    return dashboardUXDB;
}

function dashboardUXEntityKey(type, id) {
    return `${type}:${id}`;
}

function dashboardUXOpenItem(item) {
    if (!item) return;
    const normalized = normalizeDashboardQuickItem(item);
    if (!normalized) return;
    if (normalized.type === 'project' && normalized.id) return openProject(Number(normalized.id));
    if (typeof openOmniSearchResult === 'function') return openOmniSearchResult(normalized.type, normalized.id, normalized.view);
    if (normalized.view) return navigateTo(normalized.view);
}

function addDashboardRecentItem(item) {
    if (!item || !item.type || !item.id) return;
    const normalized = normalizeDashboardQuickItem({
        ...item,
        title: String(item.title || item.id),
        meta: String(item.meta || ''),
        view: String(item.view || ''),
        touched_at: Date.now(),
    });
    if (!normalized) return;
    const key = dashboardUXEntityKey(normalized.type, normalized.id);
    const recent = dashboardUXLoad('recent_items', []).filter(row => dashboardUXEntityKey(row.type, row.id) !== key);
    recent.unshift(normalized);
    dashboardUXSave('recent_items', recent.slice(0, 12));
    if (dashboardUXServerReady()) dashboardUXDB.recent = recent.slice(0, 12);
    apiCall('/workbench/recent', 'POST', {
        entity_type: normalized.type,
        entity_id: String(normalized.id),
        title: normalized.title,
        meta: normalized.meta,
        view_name: normalized.view,
        payload: normalized.payload || {},
    }).then(() => loadDashboardUXData(true)).catch(error => console.warn('Recent item was kept locally only', error));
}

function getDashboardFavoriteItems() {
    if (dashboardUXServerReady()) return dashboardUXDB.favorites || [];
    return dashboardUXLoad('favorite_items', []);
}

function isDashboardFavorite(type, id) {
    const key = dashboardUXEntityKey(type, id);
    return getDashboardFavoriteItems().some(item => dashboardUXEntityKey(item.type, item.id) === key);
}

function getDashboardWatchItems() {
    if (dashboardUXServerReady()) return dashboardUXDB.watches || [];
    return dashboardUXLoad('watch_items', []);
}

function isDashboardWatched(type, id) {
    const key = dashboardUXEntityKey(type, id);
    return getDashboardWatchItems().some(item => dashboardUXEntityKey(item.type, item.id) === key);
}

function defaultWatchCondition(type) {
    const map = {
        finance_payment: 'paid',
        document: 'signed',
        purchase_order: 'overdue',
        production_order: 'stage_changed',
    };
    return map[String(type || '')] || 'status_changed';
}

function watchConditionLabel(condition) {
    const labels = {
        paid: 'когда оплатят',
        signed: 'когда подпишут',
        overdue: 'когда просрочится',
        stage_changed: 'когда сменит этап',
        status_changed: 'когда сменит статус',
        file_added: 'когда добавят файл',
        any_change: 'при любом изменении',
    };
    return labels[String(condition || '')] || 'когда изменится';
}

function watchDigestLabel(mode) {
    const labels = {
        instant: 'сразу',
        daily: 'дайджест за день',
        weekly: 'дайджест за неделю',
    };
    return labels[String(mode || 'instant')] || 'сразу';
}

function dashboardJsArg(value) {
    return dashboardEscape(JSON.stringify(String(value ?? '')));
}

function dashboardEncodedJsonArg(value) {
    return encodeURIComponent(JSON.stringify(value || {})).replace(/'/g, '%27');
}

function renderEntityFavoriteButton(type, id, title = '', meta = '', view = '', rerender = '') {
    if (!type || id === undefined || id === null || id === '') return '';
    const active = isDashboardFavorite(type, id);
    return `<button class="btn-secondary" title="${active ? 'Убрать из избранного' : 'В избранное'}" onclick="event.stopPropagation(); toggleEntityFavorite(${dashboardJsArg(type)}, ${dashboardJsArg(id)}, ${dashboardJsArg(title)}, ${dashboardJsArg(meta)}, ${dashboardJsArg(view)}, ${dashboardJsArg(rerender)})" style="min-width:34px; padding:4px 8px; font-size:12px; min-height:unset;">${active ? '★' : '☆'}</button>`;
}

function toggleEntityFavorite(type, id, title = '', meta = '', view = '', rerender = '') {
    toggleDashboardFavorite(type, id, title, meta, view);
    if (rerender && typeof window[rerender] === 'function') {
        setTimeout(() => window[rerender](), 0);
    }
}

function renderEntityWatchButton(type, id, title = '', meta = '', view = '', rerender = '', condition = '') {
    if (!type || id === undefined || id === null || id === '') return '';
    const active = isDashboardWatched(type, id);
    const targetCondition = condition || defaultWatchCondition(type);
    const hint = active ? 'Не следить за объектом' : `Следить: ${watchConditionLabel(targetCondition)}`;
    return `<button class="btn-secondary entity-watch-btn ${active ? 'is-active' : ''}" title="${hint}" onclick="event.stopPropagation(); toggleEntityWatch(${dashboardJsArg(type)}, ${dashboardJsArg(id)}, ${dashboardJsArg(title)}, ${dashboardJsArg(meta)}, ${dashboardJsArg(view)}, ${dashboardJsArg(rerender)}, ${dashboardJsArg(targetCondition)})" style="min-width:34px; padding:4px 8px; font-size:12px; min-height:unset;">${active ? '●' : '○'}</button>`;
}

function toggleEntityWatch(type, id, title = '', meta = '', view = '', rerender = '', condition = '') {
    const key = dashboardUXEntityKey(type, id);
    const watches = getDashboardWatchItems();
    const exists = watches.some(item => dashboardUXEntityKey(item.type, item.id) === key);
    const targetCondition = condition || defaultWatchCondition(type);
    const next = exists
        ? watches.filter(item => dashboardUXEntityKey(item.type, item.id) !== key)
        : [normalizeDashboardQuickItem({ type, id, title: title || String(id), meta: meta || watchConditionLabel(targetCondition), view, condition_key: targetCondition, touched_at: Date.now() }), ...watches].filter(Boolean).slice(0, 40);
    dashboardUXSave('watch_items', next);
    if (dashboardUXServerReady()) dashboardUXDB.watches = next;
    if (typeof showToast === 'function') showToast('Наблюдение', exists ? 'Подписка отключена' : `Буду следить: ${watchConditionLabel(targetCondition)}`);
    const request = exists
        ? apiCall(`/workbench/watches/${encodeURIComponent(type)}/${encodeURIComponent(id)}`, 'DELETE')
        : apiCall('/workbench/watches', 'POST', { entity_type: String(type), entity_id: String(id), title: title || String(id), meta, view_name: view, condition_key: targetCondition });
    request
        .then(() => loadDashboardUXData(true))
        .then(() => {
            if (rerender && typeof window[rerender] === 'function') window[rerender]();
            if (typeof renderDashboard === 'function') renderDashboard();
        })
        .catch(error => console.warn('Watch item was kept locally only', error));
    if (rerender && typeof window[rerender] === 'function') {
        setTimeout(() => window[rerender](), 0);
    }
}

async function updateDashboardWatchOptions(itemJson, conditionKey = '', digestMode = '') {
    let item = {};
    try {
        item = typeof itemJson === 'string' ? JSON.parse(itemJson) : (itemJson || {});
    } catch (error) {
        return customAlert('Не удалось обновить подписку.');
    }
    const condition = conditionKey || item.condition_key || defaultWatchCondition(item.type);
    const digest = digestMode || item.digest_mode || 'instant';
    const res = await apiCall('/workbench/watches', 'POST', {
        entity_type: String(item.type || item.entity_type || ''),
        entity_id: String(item.id || item.entity_id || ''),
        title: item.title || String(item.id || ''),
        meta: item.meta || '',
        view_name: item.view || item.view_name || '',
        condition_key: condition,
        digest_mode: digest,
        event_types: [condition],
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить условия подписки.');
    await loadDashboardUXData(true);
    renderDashboardQuickAccess();
    showToast('Подписки', `Условие обновлено: ${watchConditionLabel(condition)}, ${watchDigestLabel(digest)}`);
}

function toggleDashboardFavorite(type, id, title = '', meta = '', view = '') {
    const key = dashboardUXEntityKey(type, id);
    const favorites = getDashboardFavoriteItems();
    const exists = favorites.some(item => dashboardUXEntityKey(item.type, item.id) === key);
    const next = exists
        ? favorites.filter(item => dashboardUXEntityKey(item.type, item.id) !== key)
        : [normalizeDashboardQuickItem({ type, id, title: title || String(id), meta, view, touched_at: Date.now() }), ...favorites].filter(Boolean).slice(0, 16);
    dashboardUXSave('favorite_items', next);
    if (dashboardUXServerReady()) dashboardUXDB.favorites = next;
    if (typeof showToast === 'function') showToast('Избранное', exists ? 'Убрано из избранного' : 'Добавлено в избранное');
    if (typeof renderDashboard === 'function') renderDashboard();
    const request = exists
        ? apiCall(`/workbench/favorites/${encodeURIComponent(type)}/${encodeURIComponent(id)}`, 'DELETE')
        : apiCall('/workbench/favorites', 'POST', { entity_type: String(type), entity_id: String(id), title: title || String(id), meta, view_name: view, payload: {} });
    request
        .then(() => loadDashboardUXData(true))
        .then(() => { if (typeof renderDashboard === 'function') renderDashboard(); })
        .catch(error => console.warn('Favorite item was kept locally only', error));
}

function toggleDashboardProjectFavorite(projectId) {
    const project = projectsDB.find(item => Number(item.id) === Number(projectId));
    if (!project) return;
    toggleDashboardFavorite('project', project.id, project.name || project.contract || `Проект #${project.id}`, `${project.contract || ''} · ${project.client || ''}`, 'dashboard');
}

function removeDashboardFavorite(type, id) {
    const key = dashboardUXEntityKey(type, id);
    const next = getDashboardFavoriteItems().filter(item => dashboardUXEntityKey(item.type, item.id) !== key);
    dashboardUXSave('favorite_items', next);
    if (dashboardUXServerReady()) dashboardUXDB.favorites = next;
    renderDashboard();
    apiCall(`/workbench/favorites/${encodeURIComponent(type)}/${encodeURIComponent(id)}`, 'DELETE')
        .then(() => loadDashboardUXData(true))
        .then(() => renderDashboard())
        .catch(error => console.warn('Favorite item removal was kept locally only', error));
}

function dashboardTodayDateOnly(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const match = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})/);
    if (match) return `${match[3]}-${match[2]}-${match[1]}`;
    if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10);
    return '';
}

function dashboardDaysUntil(value) {
    const iso = dashboardTodayDateOnly(value);
    if (!iso) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(target.getTime())) return null;
    return Math.round((target - today) / 86400000);
}

function dashboardTodayItems() {
    if (dashboardUXServerReady() && Array.isArray(dashboardUXDB.today_items)) {
        return dashboardUXDB.today_items.slice(0, 10);
    }
    const name = String(currentUser?.name || '');
    const email = String(currentUser?.email || '');
    const role = String(currentUser?.role || '');
    const items = [];
    (tasksDB || []).forEach(task => {
        const mine = !task.executor || String(task.executor).includes(name) || String(task.executor).includes(email);
        const days = dashboardDaysUntil(task.deadline);
        if (task.status !== 'completed' && mine && (days === null || days <= 1)) {
            items.push({ kind: 'task', title: task.title || 'Поручение', meta: `${task.executor || 'исполнитель не задан'} · ${task.deadline || 'без срока'}`, urgency: days !== null && days < 0 ? 'risk' : 'attention', view: 'tasks' });
        }
    });
    (approvalsDB || []).forEach(approval => {
        const routeText = `${approval.route || ''} ${approval.current_assignees || ''}`;
        const mine = role === 'Директор' || routeText.includes(name) || routeText.includes(role);
        if ((approval.status || '') === 'pending' && mine) {
            items.push({ kind: 'approval', title: approval.title || 'Согласование', meta: 'ожидает решения', urgency: 'attention', view: 'approvals' });
        }
    });
    (documentsDB || []).forEach(doc => {
        const status = String(doc.status || '').toLowerCase();
        if (['draft', 'new', 'registered', 'pending'].includes(status)) {
            items.push({ kind: 'document', title: doc.number || doc.subject || 'Документ', meta: `${doc.type || 'document'} · ${doc.d_date || 'без даты'}`, urgency: status === 'draft' ? 'muted' : 'attention', view: 'documents' });
        }
    });
    (notificationsDB || []).filter(item => !Number(item.is_read || 0)).slice(0, 6).forEach(note => {
        items.push({ kind: 'notification', title: note.title || 'Уведомление', meta: note.message || '', urgency: 'attention', view: 'profile' });
    });
    (projectsDB || []).filter(project => project.status === 'active' && checkOverdue(project)).slice(0, 4).forEach(project => {
        items.push({ kind: 'project', title: project.name || project.contract || 'Проект', meta: `${project.client || ''} · просрочка этапа`, urgency: 'risk', type: 'project', id: project.id });
    });
    const score = { risk: 0, attention: 1, muted: 2 };
    return items.sort((a, b) => (score[a.urgency] ?? 3) - (score[b.urgency] ?? 3)).slice(0, 10);
}

function dashboardUrgencyBadge(urgency) {
    const tone = urgency === 'risk' ? 'status-overdue' : urgency === 'attention' ? 'status-active' : 'status-archived';
    const label = urgency === 'risk' ? 'срочно' : urgency === 'attention' ? 'сегодня' : 'в работе';
    return `<span class="status-badge ${tone}">${label}</span>`;
}

function renderDashboardToday() {
    const mount = document.getElementById('dashboardTodayMount');
    if (!mount || !currentUser) return;
    const items = dashboardTodayItems();
    mount.innerHTML = `
        <section class="surface-card surface-card--padded" style="margin-bottom:16px;">
            <div class="section-header">
                <div>
                    <div class="view-eyebrow">Сегодня</div>
                    <h3 class="section-title">Мои дела и сигналы</h3>
                    <p class="section-subtitle">Собрал задачи, согласования, незакрытые документы, уведомления и просрочки проектов в один короткий список.</p>
                </div>
                <div class="view-actions">
                    <button class="btn-secondary" onclick="navigateTo('tasks')">Поручения</button>
                    <button class="btn-secondary" onclick="navigateTo('approvals')">Согласования</button>
                </div>
            </div>
            <div class="client360-list">
                ${items.length ? items.map(item => {
                    const itemType = item.type || item.entity_type || item.kind || '';
                    const itemId = item.id ?? item.entity_id ?? '';
                    const targetView = item.view || item.view_name || 'dashboard';
                    return `
                    <div class="client360-item" style="cursor:pointer;" onclick="${itemType === 'project' ? `openProject(${Number(itemId || 0)})` : `navigateTo('${dashboardEscape(targetView)}')`}">
                        <div>
                            <div class="client360-item-title">${dashboardEscape(item.title)}</div>
                            <div class="client360-item-meta">${dashboardEscape(item.meta)}</div>
                        </div>
                        ${dashboardUrgencyBadge(item.urgency)}
                    </div>
                `;
                }).join('') : '<div class="empty-state">На сегодня критичных действий не видно. Можно спокойно работать из портфеля или открыть нужный раздел.</div>'}
            </div>
        </section>
    `;
}

function renderDashboardQuickAccess() {
    const mount = document.getElementById('dashboardQuickAccessMount');
    if (!mount || !currentUser) return;
    const favorites = getDashboardFavoriteItems();
    const recent = dashboardUXServerReady() ? (dashboardUXDB.recent || []) : dashboardUXLoad('recent_items', []);
    const watches = getDashboardWatchItems();
    const watchEvents = dashboardUXDB.watch_events || [];
    const card = (item, canRemove = false) => `
        <div class="client360-item">
            <div onclick="dashboardUXOpenItem(${dashboardEscape(JSON.stringify(item))})" style="cursor:pointer;">
                <div class="client360-item-title">${dashboardEscape(item.title)}</div>
                <div class="client360-item-meta">${dashboardEscape(item.meta || item.view || item.type)}</div>
            </div>
            ${canRemove ? `<button class="btn-secondary" onclick="removeDashboardFavorite('${dashboardEscape(item.type)}', '${dashboardEscape(item.id)}')">Убрать</button>` : '<span class="status-badge status-archived">недавно</span>'}
        </div>
    `;
    mount.innerHTML = `
        <div class="client360-grid" style="margin-bottom:16px;">
            <section class="surface-card surface-card--padded">
                <div class="section-header"><div><h3 class="section-title">Избранное</h3><p class="section-subtitle">Закрепи важные записи звездой, чтобы не искать их каждый раз.</p></div></div>
                <div class="client360-list">${favorites.length ? favorites.slice(0, 6).map(item => card(item, true)).join('') : '<div class="empty-state">Избранных объектов пока нет. Нажми звезду на нужной записи.</div>'}</div>
            </section>
            <section class="surface-card surface-card--padded">
                <div class="section-header"><div><h3 class="section-title">Последние открытые</h3><p class="section-subtitle">Быстрый возврат к тому, с чем ты только что работал.</p></div></div>
                <div class="client360-list">${recent.length ? recent.slice(0, 6).map(item => card(item, false)).join('') : '<div class="empty-state">История появится после открытия проекта или объекта из поиска.</div>'}</div>
            </section>
            <section class="surface-card surface-card--padded">
                <div class="section-header"><div><h3 class="section-title">Подписки</h3><p class="section-subtitle">Условия наблюдения и последние события по объектам.</p></div></div>
                <div class="client360-list">
                    ${watches.length ? watches.slice(0, 6).map(item => {
                        const encoded = dashboardEncodedJsonArg(item);
                        const condition = item.condition_key || defaultWatchCondition(item.type);
                        const digest = item.digest_mode || 'instant';
                        return `<div class="client360-item">
                            <div style="min-width:0;">
                                <div class="client360-item-title">${dashboardEscape(item.title)}</div>
                                <div class="client360-item-meta">${dashboardEscape(watchConditionLabel(condition))} · ${dashboardEscape(watchDigestLabel(digest))}</div>
                            </div>
                            <div class="view-actions">
                                <select class="auth-input bulk-actions-select" onchange="updateDashboardWatchOptions(decodeURIComponent('${encoded}'), this.value, '')">
                                    ${['paid', 'signed', 'overdue', 'stage_changed', 'status_changed', 'file_added', 'any_change'].map(value => `<option value="${value}" ${condition === value ? 'selected' : ''}>${watchConditionLabel(value)}</option>`).join('')}
                                </select>
                                <select class="auth-input bulk-actions-select" onchange="updateDashboardWatchOptions(decodeURIComponent('${encoded}'), '', this.value)">
                                    ${['instant', 'daily', 'weekly'].map(value => `<option value="${value}" ${digest === value ? 'selected' : ''}>${watchDigestLabel(value)}</option>`).join('')}
                                </select>
                            </div>
                        </div>`;
                    }).join('') : '<div class="empty-state">Подписок пока нет. Нажми кружок “следить” на оплате, документе, поставке или заказе.</div>'}
                    ${watchEvents.length ? `<div class="empty-state" style="text-align:left;">Последнее событие: ${dashboardEscape(watchEvents[0].title || watchEvents[0].message || 'объект изменился')}</div>` : ''}
                </div>
            </section>
        </div>
    `;
}

function getDashboardSavedFilters(scope = '') {
    const filters = dashboardUXServerReady() ? (dashboardUXDB.filters || []) : dashboardUXLoad('dashboard_filters', []);
    if (!scope) return filters;
    return filters.filter(item => String(item.filter_scope || 'dashboard') === String(scope));
}

function setDashboardSavedFilters(next) {
    dashboardUXSave('dashboard_filters', next);
    if (dashboardUXServerReady()) dashboardUXDB.filters = next;
}

function renderDashboardSavedFilters() {
    const mount = document.getElementById('dashboardSavedFiltersMount');
    if (!mount) return;
    const filters = getDashboardSavedFilters('dashboard');
    mount.innerHTML = `
        <button class="btn-secondary" onclick="saveCurrentDashboardFilter()">Сохранить фильтр</button>
        ${filters.slice(0, 4).map(item => `
            <span style="display:inline-flex; gap:4px; align-items:center;">
                <button class="btn-secondary" onclick="applyDashboardSavedFilter('${dashboardEscape(item.id)}')">${dashboardEscape(item.title)}</button>
                <button class="btn-secondary" title="Удалить фильтр" onclick="deleteDashboardSavedFilter('${dashboardEscape(item.id)}')" style="padding:7px 10px;">×</button>
            </span>
        `).join('')}
    `;
}

window.saveCurrentDashboardFilter = async function() {
    const title = await customPrompt('Название фильтра', 'Мой фильтр');
    if (!title) return;
    const searchInput = document.getElementById('searchInput');
    const otherFilters = getDashboardSavedFilters().filter(item => String(item.filter_scope || 'dashboard') !== 'dashboard' || item.title !== title);
    const payload = {
        currentTab,
        viewMode,
        query: searchInput ? searchInput.value : '',
        department: currentDepartmentFilter || '',
    };
    const localFilter = {
        id: String(Date.now()),
        title,
        filter_scope: 'dashboard',
        ...payload,
        filter_payload: payload,
    };
    setDashboardSavedFilters([localFilter, ...otherFilters].slice(0, 40));
    renderDashboardSavedFilters();
    showToast('Фильтр', 'Сохранён быстрый фильтр портфеля');
    apiCall('/workbench/saved_filters', 'POST', { filter_scope: 'dashboard', title, filter_payload: payload })
        .then(() => loadDashboardUXData(true))
        .then(() => renderDashboardSavedFilters())
        .catch(error => console.warn('Saved filter was kept locally only', error));
};

window.applyDashboardSavedFilter = function(id) {
    const filter = getDashboardSavedFilters('dashboard').find(item => String(item.id) === String(id));
    if (!filter) return;
    const payload = filter.filter_payload || filter;
    currentTab = payload.currentTab || 'active';
    viewMode = payload.viewMode || 'list';
    currentDepartmentFilter = payload.department || null;
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.value = payload.query || '';
    localStorage.setItem('korda_view_mode', viewMode);
    renderDashboard();
};

window.deleteDashboardSavedFilter = function(id) {
    const next = getDashboardSavedFilters().filter(item => String(item.id) !== String(id));
    setDashboardSavedFilters(next);
    renderDashboardSavedFilters();
    apiCall(`/workbench/saved_filters/${encodeURIComponent(id)}`, 'DELETE')
        .then(() => loadDashboardUXData(true))
        .then(() => renderDashboardSavedFilters())
        .catch(error => console.warn('Saved filter removal was kept locally only', error));
};

const workbenchSavedFilterScopes = {};

function registerWorkbenchSavedFilterScope(scope, config = {}) {
    if (!scope || !config.mountId) return;
    workbenchSavedFilterScopes[scope] = config;
    renderWorkbenchSavedFilters(scope);
}

function renderWorkbenchSavedFilters(scope) {
    const config = workbenchSavedFilterScopes[scope] || {};
    const mount = document.getElementById(config.mountId);
    if (!mount) return;
    const filters = getDashboardSavedFilters(scope);
    const presetButtons = (config.presets || []).map(preset => `
        <button id="${dashboardEscape(preset.id || '')}" class="btn-secondary" onclick="applyWorkbenchFilterPreset('${dashboardEscape(scope)}', '${dashboardEscape(preset.key)}')">${dashboardEscape(preset.label)}</button>
    `).join('');
    mount.innerHTML = `
        <button class="btn-secondary" onclick="saveWorkbenchScopedFilter('${dashboardEscape(scope)}')">Сохранить фильтр</button>
        ${presetButtons}
        ${filters.slice(0, 5).map(item => `
            <span style="display:inline-flex; gap:4px; align-items:center;">
                <button class="btn-secondary" onclick="applyWorkbenchSavedFilter('${dashboardEscape(scope)}', '${dashboardEscape(item.id)}')">${dashboardEscape(item.title)}</button>
                <button class="btn-secondary" title="Удалить фильтр" onclick="deleteWorkbenchSavedFilter('${dashboardEscape(scope)}', '${dashboardEscape(item.id)}')" style="padding:7px 10px;">×</button>
            </span>
        `).join('')}
    `;
    if (typeof config.updateState === 'function') config.updateState();
}

window.saveWorkbenchScopedFilter = async function(scope) {
    const config = workbenchSavedFilterScopes[scope] || {};
    if (!config.getPayload) return;
    const title = await customPrompt('Название фильтра', config.defaultTitle || 'Мой фильтр');
    if (!title) return;
    const payload = config.getPayload();
    const otherFilters = getDashboardSavedFilters().filter(item => String(item.filter_scope || 'dashboard') !== String(scope) || item.title !== title);
    const localFilter = {
        id: String(Date.now()),
        title,
        filter_scope: scope,
        filter_payload: payload,
    };
    setDashboardSavedFilters([localFilter, ...otherFilters].slice(0, 40));
    renderWorkbenchSavedFilters(scope);
    if (typeof showToast === 'function') showToast('Фильтр', 'Сохранён быстрый фильтр раздела');
    apiCall('/workbench/saved_filters', 'POST', { filter_scope: scope, title, filter_payload: payload })
        .then(() => loadDashboardUXData(true))
        .then(() => renderWorkbenchSavedFilters(scope))
        .catch(error => console.warn('Saved filter was kept locally only', error));
};

window.applyWorkbenchSavedFilter = function(scope, id) {
    const config = workbenchSavedFilterScopes[scope] || {};
    const filter = getDashboardSavedFilters(scope).find(item => String(item.id) === String(id));
    if (!filter || typeof config.applyPayload !== 'function') return;
    config.applyPayload(filter.filter_payload || filter);
    renderWorkbenchSavedFilters(scope);
};

window.deleteWorkbenchSavedFilter = function(scope, id) {
    const next = getDashboardSavedFilters().filter(item => String(item.id) !== String(id));
    setDashboardSavedFilters(next);
    renderWorkbenchSavedFilters(scope);
    apiCall(`/workbench/saved_filters/${encodeURIComponent(id)}`, 'DELETE')
        .then(() => loadDashboardUXData(true))
        .then(() => renderWorkbenchSavedFilters(scope))
        .catch(error => console.warn('Saved filter removal was kept locally only', error));
};

window.applyWorkbenchFilterPreset = function(scope, key) {
    const config = workbenchSavedFilterScopes[scope] || {};
    const preset = (config.presets || []).find(item => String(item.key) === String(key));
    if (!preset || typeof config.applyPayload !== 'function') return;
    config.applyPayload(typeof preset.payload === 'function' ? preset.payload() : (preset.payload || {}));
    renderWorkbenchSavedFilters(scope);
};

window.toggleDashboardFavorite = toggleDashboardFavorite;
window.toggleDashboardProjectFavorite = toggleDashboardProjectFavorite;
window.renderEntityFavoriteButton = renderEntityFavoriteButton;
window.toggleEntityFavorite = toggleEntityFavorite;
window.renderEntityWatchButton = renderEntityWatchButton;
window.toggleEntityWatch = toggleEntityWatch;
window.registerWorkbenchSavedFilterScope = registerWorkbenchSavedFilterScope;
window.renderWorkbenchSavedFilters = renderWorkbenchSavedFilters;
window.removeDashboardFavorite = removeDashboardFavorite;
window.dashboardUXOpenItem = dashboardUXOpenItem;
window.addDashboardRecentItem = addDashboardRecentItem;

// ГЛАВНАЯ ФУНКЦИЯ ПОИСКА (Вызывается из topbar.html)
function filterProjects() {
    const dashView = document.getElementById('dashboardView');
    const docsView = document.getElementById('documentsView');
    const clientsView = document.getElementById('clientsView');
    const financeView = document.getElementById('financeView');
    const client360View = document.getElementById('client360View');
    const supplyView = document.getElementById('supplyView');
    const salesView = document.getElementById('salesView');
    const productionView = document.getElementById('productionView');
    const expensesView = document.getElementById('expensesView');
    const requestsView = document.getElementById('requestsView');
    const resourcesView = document.getElementById('resourcesView');
    const serviceView = document.getElementById('serviceView');
    const executiveView = document.getElementById('executiveView');

    if (dashView && dashView.style.display === 'block') {
        renderDashboard(); 
    } 
    else if (docsView && docsView.style.display === 'block') {
        if (typeof renderDocuments === 'function') renderDocuments(); 
    }
    else if (clientsView && clientsView.style.display === 'block') {
        if (typeof renderClients === 'function') renderClients(); 
    }
    else if (financeView && financeView.style.display === 'block') {
        if (typeof renderFinance === 'function') renderFinance();
    }
    else if (client360View && client360View.style.display === 'block') {
        if (typeof renderClient360 === 'function') renderClient360();
    }
    else if (supplyView && supplyView.style.display === 'block') {
        if (typeof renderSupply === 'function') renderSupply();
    }
    else if (salesView && salesView.style.display === 'block') {
        if (typeof renderSales === 'function') renderSales();
    }
    else if (productionView && productionView.style.display === 'block') {
        if (typeof renderProduction === 'function') renderProduction();
    }
    else if (expensesView && expensesView.style.display === 'block') {
        if (typeof renderExpenses === 'function') renderExpenses();
    }
    else if (requestsView && requestsView.style.display === 'block') {
        if (typeof renderInternalRequests === 'function') renderInternalRequests();
    }
    else if (resourcesView && resourcesView.style.display === 'block') {
        if (typeof renderResources === 'function') renderResources();
    }
    else if (serviceView && serviceView.style.display === 'block') {
        if (typeof renderServiceCases === 'function') renderServiceCases();
    }
    else if (executiveView && executiveView.style.display === 'block') {
        if (typeof renderExecutiveDashboard === 'function') renderExecutiveDashboard();
    }
}

function drawCharts() {
    const tCol = document.documentElement.dataset.theme === 'dark' ? '#f8fafc' : '#0f172a';
    const surfaceCol = document.documentElement.dataset.theme === 'dark' ? '#101c2c' : '#ffffff';
    const a = projectsDB.filter(p => p.status === 'active').length;
    const ar = projectsDB.filter(p => p.status === 'archive').length;
    const c = projectsDB.filter(p => p.status === 'canceled').length;
    const sharedOptions = {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 0,
        animation: {
            duration: 950,
            easing: 'easeOutCubic'
        }
    };
    
    const dlConf = { 
        color: '#fff', 
        font: { weight: 'bold', size: 14 }, 
        formatter: (v, ctx) => { 
            const tot = ctx.chart.data.datasets[0].data.reduce((acc,b) => acc + b, 0); 
            return (tot === 0 || v === 0) ? '' : Math.round((v / tot) * 100) + '%'; 
        } 
    };

    if (statusChartObj) statusChartObj.destroy();
    
    const stEl = document.getElementById('statusChart');
    if (stEl) { 
        statusChartObj = new Chart(stEl, { 
            type: 'pie', 
            data: { 
                labels: ['В работе', 'Завершённые', 'Отменённые'],
                datasets: [{ 
                    data: [a, ar, c], 
                    backgroundColor: ['#275df6', '#19bf88', '#e14852'], 
                    borderColor: surfaceCol,
                    borderWidth: 6,
                    hoverOffset: 10
                }] 
            }, 
            options: { 
                ...sharedOptions,
                plugins: { 
                    datalabels: dlConf, 
                    title: { display: true, text: 'Статусы проектов', color: tCol }, 
                    legend: { labels: { color: tCol } } 
                } 
            } 
        }); 
    }

    let l = 0, m = 0, h = 0; 
    projectsDB.filter(p => p.status === 'active').forEach(p => { 
        if (p.progress < 30) l++; 
        else if (p.progress < 80) m++; 
        else h++; 
    });
    
    if (progressChartObj) progressChartObj.destroy();
    
    const prEl = document.getElementById('progressChart');
    if (prEl) { 
        progressChartObj = new Chart(prEl, { 
            type: 'doughnut', 
            data: { 
                labels: ['0-30%', '30-80%', '80-100%'], 
                datasets: [{ 
                    data: [l, m, h], 
                    backgroundColor: ['#667892', '#4f8bff', '#1bd29a'], 
                    borderColor: surfaceCol,
                    borderWidth: 6,
                    hoverOffset: 8
                }] 
            }, 
            options: { 
                ...sharedOptions,
                cutout: '58%',
                plugins: { 
                    datalabels: dlConf, 
                    title: { display: true, text: 'Прогресс активных', color: tCol }, 
                    legend: { labels: { color: tCol } } 
                } 
            } 
        }); 
    }

    // Дополнительный пересчет после показа view, чтобы canvas не рендерился в нулевой ширине.
    requestAnimationFrame(() => {
        if (statusChartObj) {
            statusChartObj.resize();
            statusChartObj.update();
        }
        if (progressChartObj) {
            progressChartObj.resize();
            progressChartObj.update();
        }
    });
    setTimeout(() => {
        if (statusChartObj) {
            statusChartObj.resize();
            statusChartObj.update();
        }
        if (progressChartObj) {
            progressChartObj.resize();
            progressChartObj.update();
        }
    }, 140);
}

function checkOverdue(p) {
    if (p.status !== 'active') return false; 
    let isOvd = false; 
    const today = new Date(); 
    today.setHours(0,0,0,0);
    
    if (!p.checklist) return false;
    
    for (let s = 0; s < p.checklist.length; s++) {
        if (p.deadlines && p.deadlines[s]) {
            const pts = p.deadlines[s].split('.'); 
            if (pts.length === 3 && new Date(pts[2], pts[1] - 1, pts[0]) < today) {
                let secOk = true;
                for (let t = 0; t < p.checklist[s].tasks.length; t++) { 
                    if (!p.checkedState || !p.checkedState[`task_${s}_${t}`] || p.checkedState[`task_${s}_${t}`].startsWith('🟡')) { 
                        secOk = false; 
                        break; 
                    } 
                }
                if (!secOk) { 
                    isOvd = true; 
                    break; 
                }
            }
        }
    }
    return isOvd;
}

function getProjectKanbanStage(p) {
    if (p.status === 'archive') return 'archive'; 
    if (p.status === 'canceled') return 'canceled'; 
    if (p.progress === 100) return 'ready';
    
    if (!p.checklist) return 'prod';
    
    for (let s = 0; s < p.checklist.length; s++) {
        for (let t = 0; t < p.checklist[s].tasks.length; t++) {
            if (!p.checkedState || !p.checkedState[`task_${s}_${t}`] || p.checkedState[`task_${s}_${t}`].startsWith('🟡')) {
                if (s <= 1) return 'prod'; 
                if (s === 2) return 'logistics'; 
                if (s <= 4) return 'finance'; 
                return 'law';
            }
        }
    }
    return 'prod';
}

function setViewMode(mode) {
    viewMode = mode; 
    localStorage.setItem('korda_view_mode', mode);
    
    const bList = document.getElementById('viewListBtn'); 
    if (bList) { 
        bList.style.background = mode === 'list' ? 'var(--card-bg)' : 'transparent'; 
        bList.style.boxShadow = mode === 'list' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'; 
    }
    
    const bKanban = document.getElementById('viewKanbanBtn'); 
    if (bKanban) { 
        bKanban.style.background = mode === 'kanban' ? 'var(--card-bg)' : 'transparent'; 
        bKanban.style.boxShadow = mode === 'kanban' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'; 
    }
    
    const bTL = document.getElementById('viewTimelineBtn'); 
    if (bTL) { 
        bTL.style.background = mode === 'timeline' ? 'var(--card-bg)' : 'transparent'; 
        bTL.style.boxShadow = mode === 'timeline' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'; 
    }
    
    renderDashboard();
}

function generateCardHTML(p) {
    let bC = `status-${p.status}`;
    let bT = { 'active': 'В работе', 'archive': 'Завершён', 'canceled': 'Отменён', 'terminated': 'Расторгнут', 'prolongation': 'На продлении' }[p.status] || 'В работе';
    let cC = "";
    let oB = "";
    
    if (p.status === 'active' && p.progress === 100) { 
        bC = 'status-completed'; 
        bT = 'ГОТОВО'; 
    } else if (p.isOverdue) { 
        cC = "style='border-color: var(--danger); box-shadow: 0 12px 28px rgba(239,68,68,0.16);'"; 
        oB = `<span class="project-card-overdue"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg> Просрочка</span>`; 
    }
    
    let archiveHtml = '';
    if (p.status === 'archive' && p.archive_details && p.archive_details.folder) { 
        archiveHtml = `
        <div class="project-card-archive">
            <div class="project-card-archive-title">Физический архив</div>
            Стеллаж: <b>${p.archive_details.rack}</b> | Папка: <b>${p.archive_details.folder}</b><br>
            <span style="color: var(--secondary)">Отправлен: ${p.archive_details.date}</span>
        </div>`; 
    }
    const progress = Math.max(0, Math.min(100, Number(p.progress || 0)));
    const budget = Number(p.budget || 0);
    return `
    <article class="project-registry-row fade-in" ${cC} onclick="openProject(${Number(p.id || 0)})">
        <div class="project-registry-row__identity">
            <div class="project-card-badges"><span class="status-badge ${bC}">${bT}</span>${oB}</div>
            <h3>${dashboardEscape(p.name || 'Без названия')}</h3>
            <p>${dashboardEscape(p.client || 'Заказчик не указан')}</p>
        </div>
        <div class="project-registry-row__meta">
            <span>Договор</span>
            <strong>${dashboardEscape(p.contract || 'Не указан')}</strong>
        </div>
        <div class="project-registry-row__meta">
            <span>Ответственный</span>
            <strong>${dashboardEscape(p.manager || 'Не назначен')}</strong>
        </div>
        <div class="project-registry-row__meta">
            <span>Бюджет</span>
            <strong>${budget.toLocaleString('ru-RU')} ₽</strong>
        </div>
        <div class="project-registry-row__progress">
            <div><span>Готовность</span><strong>${progress}%</strong></div>
            <div class="card-progress"><div class="card-progress-fill" style="width:${progress}%"></div></div>
        </div>
        <button class="btn-secondary project-registry-row__open" type="button" onclick="event.stopPropagation(); openProject(${Number(p.id || 0)})">Открыть</button>
        ${archiveHtml}
    </article>`;
}

function getDashboardFilteredProjects() {
    const sInput = document.getElementById('projectRegistrySearch');
    const q = sInput ? sInput.value.toLowerCase().trim() : '';
    let filt = projectsDB.filter(p => p.status === currentTab);

    if (q) {
        filt = filt.filter(p => {
            const n = String(p.name || '').toLowerCase();
            const c = String(p.contract || '').toLowerCase();
            const cl = String(p.client || '').toLowerCase();
            const m = String(p.manager || '').toLowerCase();
            return n.includes(q) || c.includes(q) || cl.includes(q) || m.includes(q);
        });
    } else if (currentDepartmentFilter && currentTab === 'active') {
        filt = filt.filter(p => {
            const st = getProjectKanbanStage(p);
            if (currentDepartmentFilter === "Конструкторское бюро" || currentDepartmentFilter === "Производство и ОТК") return st === 'prod';
            if (currentDepartmentFilter === "Менеджер") return st === 'logistics' || st === 'finance';
            if (currentDepartmentFilter === "Бухгалтерия") return st === 'finance';
            if (currentDepartmentFilter === "Юрист") return st === 'law';
            return false;
        });
    }

    filt.forEach(p => p.isOverdue = checkOverdue(p));
    if (currentTab === 'active') {
        filt.sort((a, b) => (b.isOverdue ? 1 : 0) - (a.isOverdue ? 1 : 0));
    }
    return filt;
}

window.exportToExcel = function() {
    if (typeof XLSX === 'undefined') {
        return customAlert('Модуль экспорта пока не загрузился. Обновите страницу и попробуйте ещё раз.');
    }
    const filteredProjects = getDashboardFilteredProjects();
    if (!filteredProjects.length) {
        return customAlert('Нет проектов для выгрузки по текущему фильтру.');
    }

    const rows = filteredProjects.map(project => ({
        'Статус': project.status || '',
        'Проект': project.name || '',
        'Договор': project.contract || '',
        'Заказчик': project.client || '',
        'Менеджер': project.manager || '',
        'Прогресс, %': Number(project.progress || 0),
        'Бюджет, ₽': Number(project.budget || 0),
        'Затраты, ₽': Number(project.costs || 0),
        'Просрочка': project.isOverdue ? 'Да' : 'Нет',
        'Команда': Array.isArray(project.team) ? project.team.join(', ') : '',
    }));

    const worksheet = XLSX.utils.json_to_sheet(rows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Проекты');
    const now = new Date();
    const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    XLSX.writeFile(workbook, `korda-projects-${currentTab}-${stamp}.xlsx`);
    showToast('Экспорт', `Выгружено проектов: ${rows.length}`);
};

function renderDashboard() {
    const list = document.getElementById('projectsList');
    const kanban = document.getElementById('kanbanBoard');
    const timeline = document.getElementById('timelineBoard');
    if (currentUser && !dashboardUXServerReady() && !dashboardUXLoading) {
        loadDashboardUXData(true).then(() => {
            const dashView = document.getElementById('dashboardView');
            if (dashView && dashView.style.display === 'block') renderDashboard();
        });
    }
    const filt = getDashboardFilteredProjects();
    renderDashboardFirstRun();
    renderDashboardHero(filt);
    renderDashboardRoleWorkbench();
    renderManagerDealWorkbench();
    renderDashboardToday();
    renderDashboardQuickAccess();
    renderDashboardSavedFilters();
    
    if (list) list.style.display = 'none'; 
    if (kanban) kanban.style.display = 'none'; 
    if (timeline) timeline.style.display = 'none';
    
    if (viewMode === 'list') {
        if (list) { 
            list.style.display = 'grid'; 
            if (filt.length === 0) {
                list.innerHTML = dashboardEmptyStateHTML('Портфель проектов пока пуст.', 'Создай первый проект или переключись на другой фильтр, чтобы увидеть активный поток компании.');
            } else {
                list.innerHTML = filt.map(generateCardHTML).join(''); 
            }
        }
    } else if (viewMode === 'kanban') {
        if (kanban) {
            kanban.style.display = 'flex'; 
            const c = { 'prod': '', 'logistics': '', 'finance': '', 'law': '', 'ready': '' };
            
            filt.forEach(p => { 
                const st = getProjectKanbanStage(p); 
                if (c[st] !== undefined) c[st] += generateCardHTML(p); 
            });
            
            if (filt.length === 0) {
                kanban.innerHTML = dashboardEmptyStateHTML('На доске пока нет карточек.', 'Смени вкладку или создай проект, чтобы маршрут компании появился на канбан-доске.');
            } else {
                kanban.innerHTML = `
                <div class="kanban-column"><div class="kanban-header">1. Пр-во и КБ <span>${(c['prod'].match(/project-card/g)||[]).length}</span></div>${c['prod']}</div>
                <div class="kanban-column"><div class="kanban-header">2. Логистика <span>${(c['logistics'].match(/project-card/g)||[]).length}</span></div>${c['logistics']}</div>
                <div class="kanban-column"><div class="kanban-header">3. Финансы <span>${(c['finance'].match(/project-card/g)||[]).length}</span></div>${c['finance']}</div>
                <div class="kanban-column"><div class="kanban-header">4. Юристы <span>${(c['law'].match(/project-card/g)||[]).length}</span></div>${c['law']}</div>
                <div class="kanban-column" style="border-color: var(--success);"><div class="kanban-header" style="color: var(--success);">5. Готово <span>${(c['ready'].match(/project-card/g)||[]).length}</span></div>${c['ready']}</div>`;
            }
        }
    } else if (viewMode === 'timeline') {
        if (timeline) {
            timeline.style.display = 'block';
            if (filt.length === 0) {
                timeline.innerHTML = dashboardEmptyStateHTML('Таймлайн пока пуст.', 'Когда в системе появятся проекты с движением и сроками, здесь будет виден весь ритм портфеля.');
            } else {
                timeline.innerHTML = filt.map(p => {
                    const startD = new Date(p.id).toLocaleDateString('ru-RU'); 
                    const dKeys = Object.keys(p.deadlines || {}); 
                    const endD = dKeys.length > 0 ? p.deadlines[dKeys[dKeys.length-1]] : 'Дедлайн не задан';
                    return `
                    <div class="tl-row fade-in" onclick="openProject(${p.id})">
                        <div class="tl-name">${p.name}</div>
                        <div class="tl-date">${startD}</div>
                        <div class="tl-bar-bg">
                            <div class="tl-bar-fill ${p.progress===100?'done':''}" style="width:${p.progress}%"></div>
                        </div>
                        <div class="tl-date" style="color:var(--danger)">${endD}</div>
                    </div>`;
                }).join('');
            }
        }
    }
    if (typeof applyDashboardWorkspaceConfig === 'function') applyDashboardWorkspaceConfig();
}

function dashboardEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function loadManagerWorkbenchData(force = false) {
    if (!currentUser || !['Менеджер', 'Директор'].includes(currentUser.role || '')) {
        managerWorkbenchDB = null;
        managerWorkbenchLoadedFor = '';
        return null;
    }
    const cacheKey = `${currentUser.email}:${currentUser.role}`;
    if (!force && managerWorkbenchLoadedFor === cacheKey && managerWorkbenchDB) return managerWorkbenchDB;
    const data = await apiCall('/manager/workbench');
    managerWorkbenchDB = data && !data.error ? data : { metrics: {}, focus_projects: [], recent_documents: [], recent_purchases: [], recent_sales_documents: [], recent_shipments: [] };
    managerWorkbenchLoadedFor = cacheKey;
    return managerWorkbenchDB;
}

function renderManagerDealWorkbench() {
    const mount = document.getElementById('managerDealWorkbenchMount');
    if (!mount || !currentUser) return;
    if (!['Менеджер', 'Директор'].includes(currentUser.role || '')) {
        mount.innerHTML = '';
        return;
    }
    if (!managerWorkbenchDB || managerWorkbenchLoadedFor !== `${currentUser.email}:${currentUser.role}`) {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact" style="margin-bottom:16px;">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Рабочее место сделки</div>
                    <h3 class="section-title">Собираю единый контур сделки</h3>
                    <p class="section-subtitle">Подтягиваю закупки, реализации, отгрузки, дебиторку и документы в один рабочий экран.</p>
                </div>
            </section>
        `;
        loadManagerWorkbenchData(true).then(() => {
            const dashView = document.getElementById('dashboardView');
            if (dashView && dashView.style.display === 'block') renderDashboard();
        });
        return;
    }
    const metrics = managerWorkbenchDB.metrics || {};
    const focusProjects = Array.isArray(managerWorkbenchDB.focus_projects) ? managerWorkbenchDB.focus_projects : [];
    const recentDocuments = Array.isArray(managerWorkbenchDB.recent_documents) ? managerWorkbenchDB.recent_documents : [];
    mount.innerHTML = `
        <section class="surface-card surface-card--padded role-workbench" style="margin-bottom:16px;">
            <div class="role-workbench-copy">
                <div class="view-eyebrow">Рабочее место сделки</div>
                <h3 class="section-title">Сделка под рукой: продажи, закупки, отгрузки, дебиторка и документы</h3>
                <p class="section-subtitle">Это единая точка входа менеджера, где видно не только проект, но и то, где именно застрял коммерческий поток.</p>
            </div>
            <div class="role-workbench-actions">
                <button class="btn-primary" onclick="navigateAndFocus('sales', 'salesProjectId')">Продажи</button>
                <button class="btn-secondary" onclick="navigateAndFocus('supply', 'purchaseProjectId')">Закупки</button>
                <button class="btn-secondary" onclick="navigateTo('finance')">Дебиторка</button>
                <button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>
            </div>
        </section>
        <div class="erp-cockpit-grid" style="margin-bottom:16px;">
            <section class="surface-card surface-card--padded erp-cockpit-card">
                <div class="erp-cockpit-heading">Пульс сделок</div>
                <div class="erp-cockpit-stats">
                    <div class="erp-cockpit-stat"><span>Активных</span><strong>${dashboardEscape(metrics.active_deals || 0)}</strong></div>
                    <div class="erp-cockpit-stat"><span>Закупки в ходе</span><strong>${dashboardEscape(metrics.purchases_in_progress || 0)}</strong></div>
                    <div class="erp-cockpit-stat"><span>Отгрузки ждут</span><strong>${dashboardEscape(metrics.shipments_pending || 0)}</strong></div>
                </div>
            </section>
            <section class="surface-card surface-card--padded erp-cockpit-card">
                <div class="erp-cockpit-heading">Коммерция и деньги</div>
                <div class="erp-cockpit-stats">
                    <div class="erp-cockpit-highlight"><span>КП в работе</span><strong>${dashboardEscape(formatMoney(metrics.quotes_pipeline || 0))}</strong></div>
                    <div class="erp-cockpit-highlight"><span>Открытая дебиторка</span><strong>${dashboardEscape(formatMoney(metrics.receivable_open || 0))}</strong></div>
                    <div class="erp-cockpit-highlight"><span>Просрочка</span><strong>${dashboardEscape(formatMoney(metrics.overdue_receivable || 0))}</strong></div>
                </div>
            </section>
            <section class="surface-card surface-card--padded erp-cockpit-card">
                <div class="erp-cockpit-heading">Документы и действия</div>
                <div class="erp-cockpit-stats">
                    <div class="erp-cockpit-stat"><span>Открытых документов</span><strong>${dashboardEscape(metrics.documents_open || 0)}</strong></div>
                    <div class="erp-cockpit-stat"><span>Фокус-проектов</span><strong>${dashboardEscape(focusProjects.length)}</strong></div>
                    <div class="erp-cockpit-stat"><span>Последние документы</span><strong>${dashboardEscape(recentDocuments.length)}</strong></div>
                </div>
            </section>
        </div>
        <div class="client360-grid" style="margin-bottom:16px;">
            <section class="surface-card surface-card--padded">
                <div class="section-header">
                    <div>
                        <h3 class="section-title">Проекты в фокусе</h3>
                        <p class="section-subtitle">Где застряла сделка: закупка, отгрузка, дебиторка или документы.</p>
                    </div>
                </div>
                <div class="client360-list">
                    ${focusProjects.length
                        ? focusProjects.map(item => `
                            <div class="client360-item" onclick="openProject(${Number(item.project_id || 0)})" style="cursor:pointer;">
                                <div>
                                    <div class="client360-item-title">${dashboardEscape(item.project_name || '')}</div>
                                    <div class="client360-item-meta">${dashboardEscape(item.contract || '')} · ${dashboardEscape(item.client || '')}</div>
                                    <div class="client360-item-meta">КП ${dashboardEscape(item.quotes_total || 0)} · закупки ${dashboardEscape(item.purchases_in_progress || 0)} · отгрузки ${dashboardEscape(item.shipments_pending || 0)} · документы ${dashboardEscape(item.documents_open || 0)}</div>
                                </div>
                                <div style="text-align:right;">
                                    <div class="metric-value" style="font-size:20px;">${dashboardEscape(formatMoney(item.receivable_open || 0))}</div>
                                    <div class="section-subtitle" style="margin-top:6px;">просрочка ${dashboardEscape(formatMoney(item.overdue_receivable || 0))}</div>
                                </div>
                            </div>
                        `).join('')
                        : `<div class="empty-state" style="text-align:left;">Сделки в фокусе появятся здесь, когда у менеджера будет связанный контур продаж и исполнения.</div>`}
                </div>
            </section>
            <section class="surface-card surface-card--padded">
                <div class="section-header">
                    <div>
                        <h3 class="section-title">Последние документы по сделкам</h3>
                        <p class="section-subtitle">Быстрый вход в первичку и переписку по текущему портфелю.</p>
                    </div>
                </div>
                <div class="client360-list">
                    ${recentDocuments.length
                        ? recentDocuments.map(item => `
                            <div class="client360-item">
                                <div>
                                    <div class="client360-item-title">${dashboardEscape(item.number || item.subject || 'Документ')}</div>
                                    <div class="client360-item-meta">${dashboardEscape(item.type || '')} · ${dashboardEscape(item.status || '')} · ${dashboardEscape(item.d_date || '')}</div>
                                </div>
                                <button class="btn-secondary" onclick="navigateTo('documents')">Открыть</button>
                            </div>
                        `).join('')
                        : `<div class="empty-state" style="text-align:left;">Документы по сделкам пока не найдены.</div>`}
                </div>
            </section>
        </div>
    `;
}

function renderDashboardRoleWorkbench() {
    const mount = document.getElementById('dashboardRoleWorkbenchMount');
    if (!mount || !currentUser) return;
    const role = String(currentUser.role || '').trim();
    const activeTasks = Array.isArray(tasksDB)
        ? tasksDB.filter(item => item.status === 'active' && String(item.executor || '').includes(currentUser.name || '')).length
        : 0;
    if (role === 'Менеджер') {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Мой день</div>
                    <h3 class="section-title">Рабочий контур менеджера</h3>
                    <p class="section-subtitle">Сначала проект, документ, реализация и клиент. Склад, производство и глубокие финансы не должны мешать первому экрану.</p>
                </div>
                <div class="role-workbench-stats">
                    <div class="role-workbench-stat"><span>Активных проектов</span><strong>${projectsDB.filter(item => item.status === 'active').length}</strong></div>
                    <div class="role-workbench-stat"><span>Моих поручений</span><strong>${activeTasks}</strong></div>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="createNewProject()">Проект</button>
                    <button class="btn-secondary" onclick="navigateAndFocus('documents', 'docCorrespondent')">Документ</button>
                    <button class="btn-secondary" onclick="navigateAndFocus('sales', 'salesProjectId')">Реализация</button>
                    <button class="btn-secondary" onclick="navigateAndFocus('clients', 'addClientName')">Клиент</button>
                </div>
            </section>
        `;
        return;
    }
    if (role === 'Сотрудник') {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--minimal">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Мой день</div>
                    <h3 class="section-title">Только рабочие действия</h3>
                    <p class="section-subtitle">Здесь нужен не ERP-обзор, а короткий набор действий: поручения, документы, заявки и уведомления.</p>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="navigateTo('tasks')">Поручения</button>
                    <button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>
                    <button class="btn-secondary" onclick="navigateTo('requests')">Заявки</button>
                    <button class="btn-secondary" onclick="navigateTo('profile')">Профиль</button>
                </div>
            </section>
        `;
        return;
    }
    if (role === 'Бухгалтерия') {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Бухгалтерия</div>
                    <h3 class="section-title">Старт дня в один ряд</h3>
                    <p class="section-subtitle">Платёжный день, дебиторка и закрытие периода должны открываться быстрее, чем весь ERP-портфель.</p>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="navigateTo('finance')">Платежи</button>
                    <button class="btn-secondary" onclick="navigateTo('accounting')">Учёт</button>
                    <button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>
                </div>
            </section>
        `;
        return;
    }
    if (role === 'Юрист') {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Юрист</div>
                    <h3 class="section-title">Что ждёт решения сейчас</h3>
                    <p class="section-subtitle">Приоритет для юриста: согласования, документы, архив и претензионный контур, без отвлечения на остальные ERP-блоки.</p>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="navigateTo('approvals')">Согласования</button>
                    <button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>
                    <button class="btn-secondary" onclick="navigateTo('client360')">Досье</button>
                </div>
            </section>
        `;
        return;
    }
    mount.innerHTML = '';
}

function dashboardEmptyStateHTML(title, subtitle) {
    return `
        <div class="empty-state empty-state--premium" style="grid-column: 1 / -1;">
            <div class="empty-state-premium-title">${title}</div>
            <div class="empty-state-premium-text">${subtitle}</div>
            <div class="empty-state-premium-actions">
                <button class="btn-primary" onclick="createNewProject()">Создать проект</button>
                ${currentUser && currentUser.role === 'Директор'
                    ? `<button class="btn-secondary" onclick="navigateTo('executive')">Панель директора</button><button class="btn-secondary" onclick="navigateTo('finance')">Финансы</button>`
                    : `<button class="btn-secondary" onclick="navigateTo('documents')">Документы</button><button class="btn-secondary" onclick="navigateTo('tasks')">Поручения</button>`}
            </div>
        </div>
    `;
}

function renderDashboardFirstRun() {
    const mount = document.getElementById('dashboardFirstRunMount');
    if (!mount) return;
    const role = String(currentUser?.role || '').trim();
    const hasProjects = Array.isArray(projectsDB) && projectsDB.length > 0;
    const hasClients = Array.isArray(clientsDB) && clientsDB.length > 0;
    const hasDocs = Array.isArray(documentsDB) && documentsDB.length > 0;
    if (hasProjects || hasClients || hasDocs) {
        mount.innerHTML = '';
        return;
    }
    let title = 'Система готова к первому рабочему дню';
    let text = 'Сначала создай базовые данные и открой главный маршрут своей роли, чтобы не блуждать по меню.';
    let actions = `
        <button class="btn-primary" onclick="createNewProject()">Первый проект</button>
        <button class="btn-secondary" onclick="navigateAndFocus('clients', 'addClientName')">Первый контрагент</button>
    `;
    if (role === 'Директор') {
        title = 'Первый запуск директора';
        text = 'Начни с управленческой панели, затем проверь финансы, производство и операционный центр по фактическим данным CRM.';
        actions = `
            <button class="btn-primary" onclick="navigateTo('executive')">Панель директора</button>
            <button class="btn-secondary" onclick="navigateTo('finance')">Финансы</button>
            <button class="btn-secondary" onclick="navigateTo('operations')">Операционный центр</button>
        `;
    } else if (role === 'Бухгалтерия') {
        title = 'Старт для бухгалтерии';
        text = 'Открой финансы, создай первую операцию и проверь платёжный календарь. Остальные блоки уже вторичны.';
        actions = `
            <button class="btn-primary" onclick="navigateTo('finance')">В финансы</button>
            <button class="btn-secondary" onclick="presetFinanceFlow('outgoing')">Новый платёж</button>
            <button class="btn-secondary" onclick="navigateTo('accounting')">1С ЭПЛ</button>
        `;
    } else if (role === 'Производство и ОТК' || role === 'Конструкторское бюро') {
        title = 'Старт для производства';
        text = 'Открой очередь производства, выбери заказ в фокус и только потом уходи в маршрут, незавершённое производство и загрузку центров.';
        actions = `
            <button class="btn-primary" onclick="navigateTo('production')">Производство</button>
            <button class="btn-secondary" onclick="presetProductionFlow('queue')">Очередь</button>
            <button class="btn-secondary" onclick="presetProductionFlow('new')">Новый заказ</button>
        `;
    } else if (role === 'Юрист') {
        title = 'Старт для юриста';
        text = 'Проверь согласования и документы. Это первый экран, где обычно лежит то, что ждёт твоего решения.';
        actions = `
            <button class="btn-primary" onclick="navigateTo('approvals')">Согласования</button>
            <button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>
        `;
    }
    mount.innerHTML = `
        <section class="surface-card surface-card--padded dashboard-first-run">
            <div class="dashboard-first-run-copy">
                <div class="view-eyebrow">Первый запуск</div>
                <h2 class="dashboard-title">${title}</h2>
                <p class="view-subtitle">${text}</p>
            </div>
            <div class="empty-state-actions">
                ${actions}
            </div>
        </section>
    `;
}

function renderDashboardHero(filteredProjects = []) {
    const mount = document.getElementById('dashboardHeroMount');
    if (!mount) return;
    const activeProjects = projectsDB.filter(p => p.status === 'active');
    const overdueProjects = activeProjects.filter(checkOverdue);
    const totalBudget = activeProjects.reduce((sum, item) => sum + Number(item.budget || 0), 0);
    const totalCosts = activeProjects.reduce((sum, item) => sum + Number(item.costs || 0), 0);
    const totalMargin = totalBudget - totalCosts;
    const avgProgress = activeProjects.length ? Math.round(activeProjects.reduce((sum, item) => sum + Number(item.progress || 0), 0) / activeProjects.length) : 0;
    const topProject = [...activeProjects].sort((a, b) => Number(b.budget || 0) - Number(a.budget || 0))[0];
    const role = String(currentUser?.role || '').trim();
    const roleLabel = role === 'Директор' ? 'Портфель' : (role === 'Менеджер' ? 'Мой день' : 'Проекты');
    let title = 'Портфель проектов';
    let text = 'Активные проекты, бюджет, затраты и просрочки в одном экране.';
    // Создание проекта уже доступно в шапке списка ниже. Не дублируем
    // одинаковое действие в обзорном блоке портфеля.
    let primaryAction = '';
    let secondaryAction = currentUser && currentUser.role === 'Директор'
        ? `<button class="btn-secondary" onclick="navigateTo('executive')">Панель директора</button>`
        : `<button class="btn-secondary" onclick="setViewMode('kanban')">Доска</button>`;
    if (role === 'Менеджер') {
        title = 'Мой день менеджера';
        text = 'Быстрый вход в проекты, документы, клиентов и реализацию без лишнего ERP-шума.';
        primaryAction = '';
        secondaryAction = `<button class="btn-secondary" onclick="navigateAndFocus('sales', 'salesProjectId')">Реализация</button>`;
    } else if (role === 'Сотрудник') {
        title = 'Мой рабочий день';
        text = 'Первый экран для сотрудника должен вести только в задачи, документы и заявки.';
        primaryAction = `<button class="btn-primary" onclick="navigateTo('tasks')">Поручения</button>`;
        secondaryAction = `<button class="btn-secondary" onclick="navigateTo('documents')">Документы</button>`;
    } else if (role === 'Бухгалтерия') {
        title = 'Рабочий поток бухгалтерии';
        text = 'Проекты остаются контекстом, но день начинается с платежей, дебиторки и закрытия периода.';
        primaryAction = `<button class="btn-primary" onclick="navigateTo('finance')">Платежи</button>`;
        secondaryAction = `<button class="btn-secondary" onclick="navigateTo('accounting')">Учёт</button>`;
    }
    mount.innerHTML = `
        <section class="dashboard-hero-card">
            <div class="dashboard-hero-main">
                <div class="dashboard-hero-eyebrow">${roleLabel}</div>
                <h2 class="dashboard-hero-title">${title}</h2>
                <p class="dashboard-hero-text">${text}</p>
                <div class="dashboard-hero-actions">
                    ${primaryAction}
                    ${secondaryAction}
                </div>
            </div>
            <div class="dashboard-hero-side">
                <div class="dashboard-hero-stat">
                    <div class="dashboard-hero-stat-label">Активные проекты</div>
                    <div class="dashboard-hero-stat-value">${activeProjects.length}</div>
                    <div class="dashboard-hero-stat-meta">в работе</div>
                </div>
                <div class="dashboard-hero-stat">
                    <div class="dashboard-hero-stat-label">Средний прогресс</div>
                    <div class="dashboard-hero-stat-value">${avgProgress}%</div>
                    <div class="dashboard-hero-stat-meta">среднее значение</div>
                </div>
            </div>
            <div class="dashboard-hero-grid">
                <div class="dashboard-hero-metric">
                    <div class="dashboard-hero-metric-label">Портфель бюджета</div>
                    <div class="dashboard-hero-metric-value">${formatMoney(totalBudget)}</div>
                </div>
                <div class="dashboard-hero-metric">
                    <div class="dashboard-hero-metric-label">Текущие затраты</div>
                    <div class="dashboard-hero-metric-value">${formatMoney(totalCosts)}</div>
                </div>
                <div class="dashboard-hero-metric">
                    <div class="dashboard-hero-metric-label">Валовая дельта</div>
                    <div class="dashboard-hero-metric-value">${formatMoney(totalMargin)}</div>
                </div>
                <div class="dashboard-hero-metric">
                    <div class="dashboard-hero-metric-label">Просрочки</div>
                    <div class="dashboard-hero-metric-value">${overdueProjects.length}</div>
                </div>
            </div>
            <div class="dashboard-hero-callout">
                <div class="dashboard-hero-callout-title">Фокус</div>
                <div class="dashboard-hero-callout-text">
                    ${topProject
                        ? `${topProject.contract || topProject.name}: бюджет ${formatMoney(topProject.budget || 0)}, прогресс ${Number(topProject.progress || 0)}%.`
                        : 'Главный проектный акцент появится здесь, когда в системе будут активные данные.'}
                </div>
                <div class="dashboard-hero-callout-text">В текущем фильтре: ${filteredProjects.length} проектов.</div>
            </div>
        </section>
    `;
}

function switchTab(tab) { 
    currentTab = tab; 
    document.querySelectorAll('#dashboardView .tab').forEach(t => t.classList.remove('active')); 
    const activeBtn = Array.from(document.querySelectorAll('#dashboardView .tab')).find(btn => btn.getAttribute('onclick') === `switchTab('${tab}')`);
    if (activeBtn) activeBtn.classList.add('active');
    renderDashboard(); 
}
