let currentUsersTab = 'active';
let currentRoleFilter = ''; // Для фильтрации по отделам
let currentAuditFilter = 'all';
let currentAuditSearch = '';
let currentDirectorProfileTab = 'security';
let systemErrorsDB = [];
let systemBackupsDB = [];
let systemHealthDB = null;
let systemReadinessDB = null;
let userSessionsDB = [];
let fieldChangesDB = [];
let financeScopeMetaDB = { legal_entities: [], business_units: [] };
let fieldSecurityRulesDB = [];
let currentUser2faDB = null;
let employeeSelfServiceDB = null;
let employeeSelfServiceLoadedFor = '';

function hasDirectorWorkbenchAccess() {
    if (!currentUser) return false;
    const role = String(currentUser.role || '').trim();
    const email = String(currentUser.email || '').trim().toLowerCase();
    const name = String(currentUser.name || '').trim();
    return role === 'Директор'
        || role === 'Администратор'
        || email === 'admin'
        || name === 'Администратор'
        || Number(currentUser.is_head || 0) === 1;
}

function switchUsersTab(tab) {
    currentUsersTab = tab;
    document.getElementById('tabActiveUsers').classList.toggle('active', tab === 'active');
    document.getElementById('tabBannedUsers').classList.toggle('active', tab === 'banned');
    renderProfile();
}

function switchDirectorProfileTab(tab) {
    currentDirectorProfileTab = currentDirectorProfileTab === tab ? '' : (tab || '');
    applyDirectorProfileTabState();
}
window.switchDirectorProfileTab = switchDirectorProfileTab;
window.collapseDirectorProfilePanels = function() {
    currentDirectorProfileTab = '';
    applyDirectorProfileTabState();
};

function filterUsersByRole(role) {
    currentRoleFilter = role;
    document.querySelectorAll('.user-filter-btn').forEach(b => b.classList.remove('active'));
    if (event && event.target) event.target.classList.add('active');
    renderProfile();
}

function bindDirectorProfileTabs() {
    const tabs = [
        ['directorProfileTabSecurity', 'security'],
        ['directorProfileTabUsers', 'users'],
        ['directorProfileTabAudit', 'audit'],
        ['directorProfileTabFieldSecurity', 'field-security'],
        ['directorProfileTabSystem', 'system'],
    ];
    tabs.forEach(([id, tabKey]) => {
        const button = document.getElementById(id);
        if (!button || button.dataset.krdBound === '1') return;
        button.addEventListener('click', () => switchDirectorProfileTab(tabKey));
        button.dataset.krdBound = '1';
    });
}

function applyDirectorProfileTabState() {
    const tabsBlock = document.getElementById('directorProfileTabsBlock');
    const directorCanvas = document.getElementById('directorProfileCanvas');
    const collapseBtn = document.getElementById('directorProfileCollapseBtn');
    const securityGrid = document.getElementById('profileSecurityGrid');
    const auditGrid = document.getElementById('profileAuditGrid');
    const usersBlock = document.getElementById('directorUsersBlock');
    const securityBlock = document.getElementById('directorSecurityBlock');
    const auditBlock = document.getElementById('directorAuditBlock');
    const fieldSecurityBlock = document.getElementById('directorFieldSecurityBlock');
    const systemBlock = document.getElementById('directorSystemBlock');
    const securityPlusMount = document.getElementById('securityPlusMount');
    const isDirector = hasDirectorWorkbenchAccess();
    const managedBlocks = [tabsBlock, securityBlock, usersBlock, auditBlock, fieldSecurityBlock, systemBlock];

    if (!isDirector) {
        managedBlocks.forEach(block => block && block.classList.add('krd-is-hidden'));
        if (tabsBlock) tabsBlock.style.display = 'none';
        if (directorCanvas) directorCanvas.style.display = 'none';
        if (collapseBtn) {
            collapseBtn.disabled = true;
            collapseBtn.textContent = 'Свернуть';
        }
        if (securityPlusMount) securityPlusMount.style.display = 'none';
        return;
    }

    managedBlocks.forEach(block => block && block.classList.remove('krd-is-hidden'));
    if (tabsBlock) tabsBlock.style.display = 'block';
    if (directorCanvas) directorCanvas.style.display = currentDirectorProfileTab ? 'grid' : 'none';
    if (collapseBtn) {
        collapseBtn.disabled = !currentDirectorProfileTab;
        collapseBtn.textContent = currentDirectorProfileTab ? 'Свернуть' : 'Разделы скрыты';
    }
    bindDirectorProfileTabs();

    const tabMap = {
        security: 'directorProfileTabSecurity',
        users: 'directorProfileTabUsers',
        audit: 'directorProfileTabAudit',
        'field-security': 'directorProfileTabFieldSecurity',
        system: 'directorProfileTabSystem',
    };

    Object.entries(tabMap).forEach(([key, id]) => {
        const button = document.getElementById(id);
        if (button) button.classList.toggle('active', currentDirectorProfileTab === key);
    });

    if (securityGrid) securityGrid.style.display = currentDirectorProfileTab === 'security' ? 'grid' : 'none';
    if (usersBlock) usersBlock.style.display = currentDirectorProfileTab === 'users' ? 'block' : 'none';
    if (auditGrid) auditGrid.style.display = ['audit', 'field-security'].includes(currentDirectorProfileTab) ? 'grid' : 'none';
    if (systemBlock) systemBlock.style.display = currentDirectorProfileTab === 'system' ? 'block' : 'none';
    if (securityPlusMount) securityPlusMount.style.display = currentDirectorProfileTab === 'security' ? 'block' : 'none';

    if (securityBlock) securityBlock.style.display = currentDirectorProfileTab === 'security' ? 'block' : 'none';
    if (auditBlock) auditBlock.style.display = currentDirectorProfileTab === 'audit' ? 'block' : 'none';
    if (fieldSecurityBlock) fieldSecurityBlock.style.display = currentDirectorProfileTab === 'field-security' ? 'block' : 'none';
    if (usersBlock) usersBlock.hidden = currentDirectorProfileTab !== 'users';
    if (securityBlock) securityBlock.hidden = currentDirectorProfileTab !== 'security';
    if (auditBlock) auditBlock.hidden = currentDirectorProfileTab !== 'audit';
    if (fieldSecurityBlock) fieldSecurityBlock.hidden = currentDirectorProfileTab !== 'field-security';
    if (systemBlock) systemBlock.hidden = currentDirectorProfileTab !== 'system';
    if (securityPlusMount) securityPlusMount.hidden = currentDirectorProfileTab !== 'security';

    [auditBlock, fieldSecurityBlock].forEach(section => {
        if (!section) return;
        if (section.style.display === 'none') {
            section.style.gridColumn = '';
        } else {
            section.style.gridColumn = '1 / -1';
        }
    });
}

function setAuditFilter(filter) {
    currentAuditFilter = filter;
    renderAuditPanel();
}
window.setAuditFilter = setAuditFilter;

function handleAuditSearch(value) {
    currentAuditSearch = (value || '').toLowerCase().trim();
    renderAuditPanel();
}
window.handleAuditSearch = handleAuditSearch;

async function reloadAuditLogs() {
    if (typeof loadAuditLogs === 'function') {
        await loadAuditLogs();
    }
    renderAuditPanel();
}
window.reloadAuditLogs = reloadAuditLogs;

async function loadSecurityOps() {
    if (!hasDirectorWorkbenchAccess()) {
        userSessionsDB = [];
        fieldChangesDB = [];
        fieldSecurityRulesDB = [];
        return;
    }
    const [sessions, fieldChanges, fieldRules] = await Promise.all([
        apiCall('/users/sessions?limit=80'),
        apiCall('/audit/field_changes?limit=80'),
        apiCall('/users/field_rules'),
    ]);
    userSessionsDB = Array.isArray(sessions) ? sessions : [];
    fieldChangesDB = Array.isArray(fieldChanges) ? fieldChanges : [];
    fieldSecurityRulesDB = Array.isArray(fieldRules) ? fieldRules : [];
}

async function reloadSecurityOps() {
    await loadSecurityOps();
    renderSecurityOpsPanel();
    renderFieldSecurityRulesPanel();
}
window.reloadSecurityOps = reloadSecurityOps;

async function prepareCurrentUser2FA() {
    const res = await apiCall('/users/2fa/setup');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось подготовить двухфакторную защиту.');
    currentUser2faDB = res;
    renderCurrentUser2FA();
    showToast('Безопасность', 'Секрет двухфакторной защиты подготовлен');
}

async function enableCurrentUser2FA() {
    const otp_code = (document.getElementById('currentUser2faCode')?.value || '').trim();
    if (!otp_code) return customAlert('Введи 6-значный код из приложения-аутентификатора.');
    const res = await apiCall('/users/2fa/enable', 'POST', { otp_code });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось включить двухфакторную защиту.');
    currentUser.two_factor_enabled = 1;
    await loadAllUsers();
    renderCurrentUser2FA();
    showToast('Безопасность', 'Двухфакторная защита включена');
}

async function disableCurrentUser2FA() {
    const otp_code = (document.getElementById('currentUser2faCode')?.value || '').trim();
    if (!otp_code) return customAlert('Чтобы отключить двухфакторную защиту, введи текущий код из приложения.');
    const res = await apiCall('/users/2fa/disable', 'POST', { otp_code });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось отключить двухфакторную защиту.');
    currentUser.two_factor_enabled = 0;
    await loadAllUsers();
    renderCurrentUser2FA();
    showToast('Безопасность', 'Двухфакторная защита отключена');
}

function renderCurrentUser2FA() {
    const stateBlock = document.getElementById('currentUser2faState');
    const secretBlock = document.getElementById('currentUser2faSecret');
    if (!stateBlock || !secretBlock || !currentUser) return;
    stateBlock.innerHTML = `
        <div class="audit-log-item">
            <div class="audit-log-main">
                <div class="audit-log-title">${currentUser.name || currentUser.email}</div>
            <div class="audit-log-meta">${currentUser.two_factor_enabled ? 'Двухфакторная защита включена' : 'Двухфакторная защита пока выключена'}</div>
            </div>
            <div class="audit-log-time">${currentUser.email || ''}</div>
        </div>
    `;
    if (currentUser2faDB?.secret) {
        secretBlock.innerHTML = `
            <div><b>Секрет:</b> <span style="font-family:monospace;">${currentUser2faDB.secret}</span></div>
            <div style="margin-top:8px; color:var(--secondary); font-size:12px;">Добавь этот секрет в приложение-аутентификатор, менеджер паролей или другое приложение одноразовых кодов под именем ${currentUser2faDB.manual_entry || 'Korda CRM'}.</div>
        `;
    } else {
        secretBlock.innerHTML = 'Сначала нажми «Подготовить двухфакторную защиту», затем введи код из приложения-аутентификатора.';
    }
}

async function ensureFinanceScopeMeta() {
    if (financeScopeMetaDB.legal_entities.length || financeScopeMetaDB.business_units.length) return financeScopeMetaDB;
    const data = await apiCall('/finance/master_data');
    financeScopeMetaDB = data && !data.error ? data : { legal_entities: [], business_units: [] };
    return financeScopeMetaDB;
}

async function loadSystemOps() {
    if (!hasDirectorWorkbenchAccess()) {
        systemErrorsDB = [];
        systemBackupsDB = [];
        systemHealthDB = null;
        systemReadinessDB = null;
        return;
    }
    const [errors, backups, health, readiness] = await Promise.all([
        apiCall('/system/errors?limit=20'),
        apiCall('/system/backups?limit=20'),
        apiCall('/health/deep'),
        apiCall('/system/readiness')
    ]);
    systemErrorsDB = Array.isArray(errors) ? errors : [];
    systemBackupsDB = Array.isArray(backups) ? backups : [];
    systemHealthDB = health && !health.error ? health : null;
    systemReadinessDB = readiness && !readiness.error ? readiness : null;
}

async function reloadSystemOps() {
    await loadSystemOps();
    renderSystemOpsPanel();
}

async function createSystemBackup() {
    const res = await apiCall('/system/backup', 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось создать резервную копию.');
    showToast('Резервная копия', `Создан файл ${res.filename}`);
    await reloadSystemOps();
}

async function restoreSystemBackup(filename) {
    if (!(await customConfirm(`Восстановить систему из резервной копии ${filename}? Это перезапишет текущую базу данных.`))) return;
    const formData = new FormData();
    formData.append('filename', filename);
    const res = await apiCall('/system/restore', 'POST', formData);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось восстановить резервную копию.');
    showToast('Резервная копия', `Система восстановлена из ${res.source}`);
    await reloadSystemOps();
    window.location.href = '/static/login.html';
}

async function uploadAndRestoreBackup(file) {
    if (!file) return;
    if (!(await customConfirm(`Загрузить и восстановить резервную копию ${file.name}? Это перезапишет текущую базу данных.`))) {
        const input = document.getElementById('systemRestoreFile');
        if (input) input.value = '';
        return;
    }
    const formData = new FormData();
    formData.append('upload', file);
    const res = await apiCall('/system/restore', 'POST', formData);
    const input = document.getElementById('systemRestoreFile');
    if (input) input.value = '';
    if (!res || res.error) return customAlert(res?.error || 'Не удалось загрузить резервную копию.');
    showToast('Резервная копия', `Система восстановлена из ${res.source}`);
    await reloadSystemOps();
    window.location.href = '/static/login.html';
}

function renderSystemOpsPanel() {
    const block = document.getElementById('directorSystemBlock');
    const errorsList = document.getElementById('systemErrorsList');
    const backupsList = document.getElementById('systemBackupsList');
    const healthSummary = document.getElementById('systemHealthSummary');
    if (!block || !errorsList || !backupsList || !healthSummary) return;
    if (!hasDirectorWorkbenchAccess()) {
        block.style.display = 'none';
        return;
    }
    block.style.display = currentDirectorProfileTab === 'system' ? 'block' : 'none';
    if (systemReadinessDB) {
        const statusLabel = { green: 'Готово', yellow: 'Внимание', red: 'Критично' };
        const checks = Array.isArray(systemReadinessDB.checks) ? systemReadinessDB.checks : [];
        const cardsHtml = checks.map(item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${profileEscape(item.title || item.key || 'Проверка')}</div>
                <div class="client360-item-meta">${profileEscape(item.message || '')}</div>
                <span class="status-badge ${item.status === 'green' ? 'status-completed' : item.status === 'red' ? 'status-overdue' : 'status-active'}">${statusLabel[item.status] || item.status}</span>
            </div>
        `).join('');
        healthSummary.innerHTML = `
            <div class="section-header">
                <div>
                    <h4 class="section-title" style="font-size:16px;">Готовность системы</h4>
                    <p class="section-subtitle">База, миграции, 1С, подписи, распознавание документов, антивирус, почта, резервные копии, тестовые режимы и ошибки.</p>
                </div>
                <div class="view-actions">
                    <span class="status-badge ${systemReadinessDB.status === 'green' ? 'status-completed' : systemReadinessDB.status === 'red' ? 'status-overdue' : 'status-active'}">${statusLabel[systemReadinessDB.status] || systemReadinessDB.status}</span>
                    <span class="email-account-meta">${profileEscape(systemReadinessDB.app_env || 'development')}</span>
                </div>
            </div>
            <div class="metrics-grid" style="margin: 12px 0 14px;">
                <div class="metric-card danger"><div class="metric-title">Критично</div><div class="metric-value">${Number(systemReadinessDB.summary?.red || 0)}</div></div>
                <div class="metric-card warning"><div class="metric-title">Внимание</div><div class="metric-value">${Number(systemReadinessDB.summary?.yellow || 0)}</div></div>
                <div class="metric-card success"><div class="metric-title">Готово</div><div class="metric-value">${Number(systemReadinessDB.summary?.green || 0)}</div></div>
            </div>
            <div class="client360-list">${cardsHtml || '<div class="empty-state">Проверки пока не собраны.</div>'}</div>
        `;
    } else if (systemHealthDB) {
        const checks = systemHealthDB.checks || {};
        const checksHtml = Object.entries(checks).map(([key, value]) => `
            <span class="email-status-pill ${value ? 'email-status-pill--ok' : 'email-status-pill--error'}">${key}: ${value ? 'норма' : 'ошибка'}</span>
        `).join('');
        healthSummary.innerHTML = `
            <div class="section-header">
                <div>
                    <h4 class="section-title" style="font-size:16px;">Проверка состояния</h4>
                    <p class="section-subtitle">Статус ядра системы, файловых директорий и базы данных.</p>
                </div>
                <div class="view-actions">
                    <span class="status-badge ${systemHealthDB.status === 'ok' ? 'status-completed' : 'status-overdue'}">${systemHealthDB.status}</span>
                    <span class="email-account-meta">Задержка базы: ${systemHealthDB.db_latency_ms || 0} мс</span>
                </div>
            </div>
            <div class="email-account-status-line">${checksHtml}</div>
        `;
    } else {
        healthSummary.innerHTML = '<div class="empty-state">Сводка состояния пока не доступна.</div>';
    }

    errorsList.innerHTML = systemErrorsDB.length ? systemErrorsDB.map(log => `
        <div class="audit-log-item">
            <div class="audit-log-main">
                <div class="audit-log-title">${log.source}: ${log.message}</div>
        <div class="audit-log-meta">${log.method || 'МЕТОД'} · ${log.path || '/'} · ${log.actor_email || 'аноним'}</div>
            </div>
            <div class="audit-log-time">${new Date((log.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
        </div>
    `).join('') : '<div class="empty-state">Критичных ошибок пока не зафиксировано.</div>';

    backupsList.innerHTML = systemBackupsDB.length ? systemBackupsDB.map(item => `
        <div class="audit-log-item">
            <div class="audit-log-main">
                <div class="audit-log-title">${item.filename}</div>
        <div class="audit-log-meta">Размер: ${Math.round((item.file_size || 0) / 1024)} КБ · ${item.actor_email || 'система'}</div>
            </div>
            <div class="system-backup-meta">
                <div class="audit-log-time">${new Date((item.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
                <div class="system-backup-actions">
                    <a class="btn-secondary" href="/api/system/backups/${item.filename}" target="_blank" style="text-decoration:none;">Скачать</a>
                    <button class="btn-danger" onclick="restoreSystemBackup('${item.filename}')">Восстановить</button>
                </div>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Резервные копии ещё не создавались.</div>';
}

function renderAuditPanel() {
    const block = document.getElementById('directorAuditBlock');
    const list = document.getElementById('auditLogList');
    if (!block || !list) return;
    if (!hasDirectorWorkbenchAccess()) {
        block.style.display = 'none';
        return;
    }

    block.style.display = currentDirectorProfileTab === 'audit' ? 'block' : 'none';
    const filtered = (auditLogsDB || []).filter(log => {
        if (currentAuditFilter === 'auth' && !String(log.action || '').includes('login') && !String(log.action || '').includes('register') && !String(log.action || '').includes('recover')) {
            return false;
        }
        if (currentAuditFilter === 'users' && !String(log.entity_type || '').includes('user')) {
            return false;
        }
        if (!currentAuditSearch) return true;
        const haystack = [
            log.action,
            log.actor_email,
            log.actor_name,
            log.entity_type,
            log.entity_id,
            JSON.stringify(log.details || {})
        ].join(' ').toLowerCase();
        return haystack.includes(currentAuditSearch);
    });

    if (!filtered.length) {
        list.innerHTML = '<div class="empty-state">Подходящих событий пока нет.</div>';
        return;
    }

    list.innerHTML = filtered.slice(0, 120).map(log => {
        const details = log.details && Object.keys(log.details).length
            ? `<div class="audit-log-meta">Детали: ${Object.entries(log.details).map(([key, value]) => `${key}: ${value}`).join(' • ')}</div>`
            : '';
        return `
            <div class="audit-log-item">
                <div class="audit-log-main">
                    <div class="audit-log-title">${log.action}</div>
                    <div class="audit-log-meta">
                        ${log.actor_name || 'Система'} · ${log.actor_email || 'без почты'} · ${log.entity_type || 'сущность'} / ${log.entity_id || 'нет'}
                    </div>
                    ${details}
                </div>
                <div class="audit-log-time">${new Date((log.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
            </div>
        `;
    }).join('');
}

function renderSecurityOpsPanel() {
    const block = document.getElementById('directorSecurityBlock');
    const sessionsList = document.getElementById('userSessionsList');
    const fieldChangesList = document.getElementById('fieldChangesList');
    if (!block || !sessionsList || !fieldChangesList) return;
    if (!hasDirectorWorkbenchAccess()) {
        block.style.display = 'none';
        return;
    }
    block.style.display = currentDirectorProfileTab === 'security' ? 'block' : 'none';

    sessionsList.innerHTML = userSessionsDB.length ? userSessionsDB.slice(0, 60).map(item => `
        <div class="audit-log-item">
            <div class="audit-log-main">
                <div class="audit-log-title">${item.user_name || item.user_email || 'Пользователь'}${item.is_current ? ' · текущая сессия' : ''}</div>
                <div class="audit-log-meta">${item.user_role || 'роль не указана'} · ${item.user_email || ''}</div>
                <div class="audit-log-meta">${item.ip_address || 'IP не указан'} · ${item.user_agent || 'клиент не указан'} </div>
            </div>
            <div class="system-backup-meta">
                <div class="audit-log-time">${new Date((item.last_seen_at || item.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
                <div class="system-backup-actions">
                    ${item.is_current ? '<span class="btn-secondary" style="pointer-events:none;opacity:.7;">Активна</span>' : `<button class="btn-danger" onclick="revokeUserSession('${item.session_id}', '${item.user_email || ''}')">Завершить</button>`}
                </div>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Активных сессий пока нет.</div>';

    fieldChangesList.innerHTML = fieldChangesDB.length ? fieldChangesDB.slice(0, 80).map(item => `
        <div class="audit-log-item">
            <div class="audit-log-main">
                <div class="audit-log-title">${item.entity_type || 'entity'} / ${item.entity_id || 'n/a'} · ${item.field_name || 'field'}</div>
    <div class="audit-log-meta">${item.actor_name || 'Система'} · ${item.actor_email || 'без почты'}</div>
                <div class="audit-log-meta">Было: ${item.old_value || '—'} · Стало: ${item.new_value || '—'}</div>
            </div>
            <div class="audit-log-time">${new Date((item.created_at || 0) * 1000).toLocaleString('ru-RU')}</div>
        </div>
    `).join('') : '<div class="empty-state">Изменений полей пока нет.</div>';
}

function renderFieldSecurityRulesPanel() {
    const block = document.getElementById('directorFieldSecurityBlock');
    const list = document.getElementById('fieldSecurityRulesList');
    if (!block || !list) return;
    if (!hasDirectorWorkbenchAccess()) {
        block.style.display = 'none';
        return;
    }
    block.style.display = currentDirectorProfileTab === 'field-security' ? 'block' : 'none';
    list.innerHTML = fieldSecurityRulesDB.length ? fieldSecurityRulesDB.map(item => `
        <div class="audit-log-item">
            <div class="audit-log-main">
                <div class="audit-log-title">${item.role_name} · ${item.module_name} / ${item.entity_type} / ${item.field_name}</div>
                <div class="audit-log-meta">view ${Number(item.can_view || 0)} · edit ${Number(item.can_edit || 0)}${(item.allowed_statuses || []).length ? ` · статусы: ${(item.allowed_statuses || []).join(', ')}` : ''}</div>
            </div>
            <div class="system-backup-actions">
                <button class="btn-danger" onclick="deleteFieldSecurityRule(${item.id})">Удалить</button>
            </div>
        </div>
    `).join('') : '<div class="empty-state">Правил по полям пока нет.</div>';
}

async function reloadFieldSecurityRules() {
    if (!hasDirectorWorkbenchAccess()) return;
    const data = await apiCall('/users/field_rules');
    fieldSecurityRulesDB = Array.isArray(data) ? data : [];
    renderFieldSecurityRulesPanel();
}
window.reloadFieldSecurityRules = reloadFieldSecurityRules;

async function saveFieldSecurityRule() {
    const payload = {
        role: (document.getElementById('fieldRuleRole')?.value || '').trim(),
        module: (document.getElementById('fieldRuleModule')?.value || '').trim(),
        entity_type: (document.getElementById('fieldRuleEntity')?.value || '').trim(),
        field_name: (document.getElementById('fieldRuleField')?.value || '').trim(),
        can_view: Number(document.getElementById('fieldRuleCanView')?.value || 0),
        can_edit: Number(document.getElementById('fieldRuleCanEdit')?.value || 0),
        allowed_statuses: (document.getElementById('fieldRuleAllowedStatuses')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        is_active: 1,
    };
    if (!payload.role || !payload.module || !payload.entity_type || !payload.field_name) return customAlert('Заполни роль, модуль, сущность и поле.');
    const res = await apiCall('/users/field_rules', 'POST', payload);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить правило по полям.');
    await reloadFieldSecurityRules();
    showToast('Безопасность', 'Правило по полям сохранено');
}

async function deleteFieldSecurityRule(ruleId) {
    if (!(await customConfirm('Удалить это правило по полям?'))) return;
    const res = await apiCall(`/users/field_rules/${ruleId}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось удалить правило.');
    await reloadFieldSecurityRules();
    showToast('Безопасность', 'Правило удалено');
}

function isUserAbsentOrUpcoming(u) {
    if (!u.abs_end) return false;
    const today = new Date(); today.setHours(0,0,0,0);
    const pEnd = u.abs_end.split('.');
    if (pEnd.length !== 3) return false;
    const dEnd = new Date(pEnd[2], pEnd[1]-1, pEnd[0]);
    return dEnd >= today; 
}

function renderKPI() {
    const container = document.getElementById('kpiListContainer'); if(!container) return;
    
    let html = '';
    allUsersDB.filter(u => u.status === 'approved' && u.role !== 'Директор').forEach(u => {
        let totalSeconds = 0;
        projectsDB.forEach(p => {
            if(p.time_logs) p.time_logs.filter(l => l.user === u.name).forEach(l => totalSeconds += l.seconds);
        });
        
        let timeStr = '0 мин';
        if (totalSeconds > 0 && totalSeconds < 60) {
            timeStr = `${totalSeconds} сек`;
        } else if (totalSeconds >= 60) {
            const h = Math.floor(totalSeconds / 3600);
            const m = Math.floor((totalSeconds % 3600) / 60);
            timeStr = h > 0 ? `${h} ч ${m} мин` : `${m} мин`;
        }
        
        let projectCheckboxesDone = 0;
        projectsDB.forEach(p => {
            if (p.checkedState) {
                Object.values(p.checkedState).forEach(val => {
                    if (val.includes(u.name)) projectCheckboxesDone++;
                });
            }
        });

        let tasksDone = tasksDB.filter(t => t.executor === u.name && t.status === 'completed').length;
        let tasksActive = tasksDB.filter(t => t.executor === u.name && t.status === 'active').length;
        
        let approvalsProcessed = 0;
        approvalsDB.forEach(a => {
            if (a.history.some(h => h.includes(u.name) && (h.includes('согласовал') || h.includes('отклонил')))) {
                approvalsProcessed++;
            }
        });

        html += `
        <div class="kpi-card fade-in">
            <div class="kpi-user">${u.name} <span style="font-size:12px; color:var(--secondary); font-weight:normal;">(${u.role})</span></div>
            <div class="kpi-stat">По таймеру: <b>${timeStr}</b></div>
            <div class="kpi-stat">Отметок в проектах: <b style="color:var(--primary)">${projectCheckboxesDone}</b></div>
            <div class="kpi-stat">Выполнено поручений: <b style="color:var(--success)">${tasksDone}</b></div>
            <div class="kpi-stat">Поручений в работе: <b style="color:var(--danger)">${tasksActive}</b></div>
            <div class="kpi-stat">Согласований: <b>${approvalsProcessed}</b></div>
        </div>`;
    });
    
    container.innerHTML = html || '<div style="grid-column: 1/-1; text-align:center; color:var(--secondary);">Сотрудников пока нет.</div>';
}

function renderProfile() {
    try {
    let completedTasks = 0; let upcomingDeadlines = 0;
    const today = new Date(); today.setHours(0,0,0,0);
    const nextWeek = new Date(today); nextWeek.setDate(today.getDate() + 7);

    projectsDB.forEach(p => {
        if (p.checkedState) { 
            Object.keys(p.checkedState).forEach(k => { 
                if (p.checkedState[k].includes(currentUser.name)) completedTasks++; 
            }); 
        }        
        if (p.status === 'active') {
            if (p.checklist) p.checklist.forEach((sec, sIdx) => {
                const responsibles = Array.isArray(sec?.responsibles) ? sec.responsibles : [];
                if (responsibles.includes(currentUser.role) && p.deadlines && p.deadlines[sIdx]) {
                    const pts = p.deadlines[sIdx].split('.');
                    if (pts.length === 3) {
                        const dDate = new Date(pts[2], pts[1]-1, pts[0]);
                        if (dDate >= today && dDate <= nextWeek) upcomingDeadlines++;
                        else if (dDate < today) {
                            let secOk = true;
                            for (let t = 0; t < sec.tasks.length; t++) { 
                                if (!p.checkedState || !p.checkedState[`task_${sIdx}_${t}`] || p.checkedState[`task_${sIdx}_${t}`].startsWith('🟡')) secOk = false; 
                            }
                            if (!secOk) upcomingDeadlines++; 
                        }
                    }
                }
            });
        }
    });

    const elTasks = document.getElementById('profCompletedTasks'); if(elTasks) elTasks.innerText = completedTasks;
    const elDeadlines = document.getElementById('profUpcomingDeadlines'); if(elDeadlines) elDeadlines.innerText = upcomingDeadlines;
    const heroMount = document.getElementById('profileHeroMount');
    
    const uData = allUsersDB.find(x => x.email === currentUser.email);
    const vType = document.getElementById('absType');
    const vStart = document.getElementById('absStart');
    const vEnd = document.getElementById('absEnd');
    const vReason = document.getElementById('absReason');
    const vDep = document.getElementById('vacationDeputy');
    
    if (vType && vStart && vEnd && vReason && vDep && uData) {
        if (typeof flatpickr === 'function') {
            flatpickr("#absStart", { locale: "ru", dateFormat: "d.m.Y" });
            flatpickr("#absEnd", { locale: "ru", dateFormat: "d.m.Y" });
        }
        
        if(vStart._flatpickr) vStart._flatpickr.setDate(uData.abs_start || ''); else vStart.value = uData.abs_start || '';
        if(vEnd._flatpickr) vEnd._flatpickr.setDate(uData.abs_end || ''); else vEnd.value = uData.abs_end || '';
        
        let cleanAbsType = uData.abs_type ? uData.abs_type.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '').replace(/❓/g, '').replace(/✈️/g, '').trim() : 'Отпуск';
        vType.value = cleanAbsType || 'Отпуск';
        vReason.value = uData.abs_reason || '';
        
        let opts = '<option value="">Без заместителя</option>';
        allUsersDB.filter(x => x.email !== currentUser.email && x.status === 'approved').forEach(x => {
            opts += `<option value="${x.name}" ${uData.deputy === x.name ? 'selected' : ''}>${x.name} (${x.role})</option>`;
        });
        vDep.innerHTML = opts;
    }
    if (heroMount && currentUser) {
        const initials = (currentUser.name || '?').split(' ').map(item => item[0]).slice(0, 2).join('').toUpperCase() || '?';
        const has2fa = Number(currentUser.two_factor_enabled || 0) === 1;
        const deputy = uData?.deputy || 'не назначен';
        const absence = uData?.abs_start && uData?.abs_end
            ? `${uData.abs_type || 'Отсутствие'} · ${uData.abs_start} — ${uData.abs_end}`
            : 'Отсутствия не задано';
        heroMount.innerHTML = `
            <section class="surface-card surface-card--padded profile-hero-card">
                <div class="profile-hero-main">
                    <div class="profile-hero-avatar">${initials}</div>
                    <div>
                        <div class="profile-hero-eyebrow">${currentUser.role === 'Директор' ? 'Кабинет директора' : 'Личный рабочий кабинет'}</div>
                        <h2 class="profile-hero-title">${currentUser.name || currentUser.email}</h2>
                        <p class="profile-hero-text">${currentUser.role || 'Сотрудник'} · ${currentUser.email || ''}</p>
                        <div class="profile-hero-chips">
                            <span class="profile-hero-chip">${has2fa ? 'Двухфакторная защита включена' : 'Двухфакторная защита выключена'}</span>
                            <span class="profile-hero-chip">${currentUser.is_head === 1 ? 'Руководитель' : 'Личный кабинет'}</span>
                            <span class="profile-hero-chip">${absence}</span>
                        </div>
                    </div>
                </div>
                <div class="profile-hero-side">
                    <div class="profile-hero-side-item">
                        <div class="profile-hero-side-label">Замещение</div>
                        <div class="profile-hero-side-value">${deputy}</div>
                    </div>
                    <div class="profile-hero-side-item">
                        <div class="profile-hero-side-label">Задач закрыто</div>
                        <div class="profile-hero-side-value">${completedTasks}</div>
                    </div>
                    <div class="profile-hero-side-item">
                        <div class="profile-hero-side-label">Ближайшие дедлайны</div>
                        <div class="profile-hero-side-value">${upcomingDeadlines}</div>
                    </div>
                </div>
            </section>
        `;
    }
    
    const dBlock = document.getElementById('directorUsersBlock');
    const tabsBlock = document.getElementById('directorProfileTabsBlock');
    if (tabsBlock) {
        tabsBlock.style.display = hasDirectorWorkbenchAccess() ? 'block' : 'none';
    }
    if (dBlock) {
        if (hasDirectorWorkbenchAccess()) {
            dBlock.style.display = currentDirectorProfileTab === 'users' ? 'block' : 'none';
            document.getElementById('totalUsersCount').innerText = allUsersDB.length;
            
            let uHtml = '';
            let filteredUsers = allUsersDB.filter(u => currentUsersTab === 'active' ? u.status !== 'banned' : u.status === 'banned');
            
            // ПРИМЕНЕНИЕ ФИЛЬТРА ПО ОТДЕЛАМ
            if (currentRoleFilter) {
                filteredUsers = filteredUsers.filter(u => u.role === currentRoleFilter);
            }
            
            filteredUsers.forEach(u => {
                let statusBadge = '';
                if(u.status === 'approved') statusBadge = '<span class="status-badge" style="background: rgba(16, 185, 129, 0.1); color: var(--success);">Активен</span>';
                else if(u.status === 'pending') statusBadge = '<span class="status-badge" style="background: var(--bg); color: var(--secondary);">Ожидает</span>';
                else if(u.status === 'banned') statusBadge = '<span class="status-badge" style="background: rgba(239, 68, 68, 0.1); color: var(--danger);">Заблокирован</span>';
                
                let actionBtn = '';
                if(u.email === currentUser.email) actionBtn = '<span style="color:var(--secondary); font-size:12px;">Это вы</span>';
                else if (u.status === 'banned') actionBtn = `<button class="btn-success" style="padding: 6px 12px; font-size:12px; background:var(--success); color:white; border:none;" onclick="restoreUser('${u.email}')">Разблокировать</button>`;
                else {
                    const headBtnText = u.is_head === 1 ? "Снять права Рук." : "Сделать Рук-лем";
                    const scopeSummary = `Юрлица: ${(u.allowed_legal_entities || []).join(', ') || 'все'} · Подразделения: ${(u.allowed_business_units || []).join(', ') || 'все'}${u.two_factor_enabled ? ' · двухфакторная защита' : ''}`;
                    actionBtn = `<div style="display:flex; gap:6px; flex-wrap:wrap;">
                        <button class="btn-secondary" style="padding: 4px 8px; font-size:11px;" onclick="changeUserRole('${u.email}', '${u.role}')">Сменить отдел</button>
                        <button class="btn-secondary" style="padding: 4px 8px; font-size:11px;" onclick="changeUserAccessScope('${u.email}')">Область доступа</button>
                        <button class="btn-secondary" style="padding: 4px 8px; font-size:11px;" onclick="toggleHeadStatus('${u.email}', ${u.is_head === 1 ? 0 : 1})">${headBtnText}</button>
                        <button class="btn-danger" style="padding: 4px 8px; font-size:11px; background:var(--danger); color:white; border:none;" onclick="removeUser('${u.email}')">Заблокировать</button>
                        <span style="width:100%; font-size:11px; color:var(--secondary);">${scopeSummary}</span>
                    </div>`;
                }

                const pwdHtml = u.has_password
                    ? `<span style="font-size:12px; color:var(--success); font-weight:600;">Защищен</span>`
                    : `<span style="font-size:12px; color:var(--secondary);">Не задан</span>`;
                
                let vacHtml = '';
                if (isUserAbsentOrUpcoming(u)) {
                    let userAbsType = u.abs_type ? u.abs_type.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '').replace(/❓/g, '').replace(/✈️/g, '').trim() : 'Отпуск';
                    
                    let icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>';
                    if (userAbsType === 'Больничный') icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>';
                    if (userAbsType === 'Командировка') icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><path d="M22 2L11 13"></path><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
                    if (userAbsType === 'Другое') icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
                    
                    const reasonText = u.abs_reason ? `Причина: ${u.abs_reason}.` : '';
                    const depText = u.deputy ? `Замещает: ${u.deputy}` : 'Без заместителя';
                    
                    let prefixText = 'до';
                    const pStart = u.abs_start ? u.abs_start.split('.') : [];
                    if (pStart.length === 3) {
                        const dStart = new Date(pStart[2], pStart[1]-1, pStart[0]);
                        if (dStart > today) prefixText = `с ${u.abs_start} по`;
                    }
                    
                    vacHtml = `<div style="font-size: 11px; margin-top: 4px; background: rgba(0,0,0,0.04); padding: 4px 8px; border-radius: 6px; display: inline-block;">
                        ${icon} <b>${userAbsType}</b> ${prefixText} ${u.abs_end}. <span style="color:var(--secondary)">${reasonText} ${depText}</span>
                    </div>`;
                }
                
                const roleText = u.is_head === 1 && u.role !== 'Директор' ? `<b>${u.role} (Руководитель)</b>` : (u.role || '-');

                uHtml += `<tr>
                    <td><b>${u.name}</b><br>${vacHtml}</td>
                    <td>${u.email}</td><td>${pwdHtml}</td><td>${roleText}</td><td>${statusBadge}</td><td>${actionBtn}</td>
                </tr>`;
            });
            const tBody = document.getElementById('allUsersListTable'); if(tBody) tBody.innerHTML = uHtml;
        } else {
            dBlock.style.display = 'none';
        }
    }
    renderAuditPanel();
    renderSecurityOpsPanel();
    renderFieldSecurityRulesPanel();
    renderCurrentUser2FA();
    renderEmployeeSelfServicePanel();
    renderWorkspacePreferencePanel();
    if (hasDirectorWorkbenchAccess()) {
        loadSecurityOps().then(() => renderSecurityOpsPanel());
        loadSystemOps().then(() => renderSystemOpsPanel());
        loadSecurityOps().then(() => renderFieldSecurityRulesPanel());
    }
    renderSystemOpsPanel();
    applyDirectorProfileTabState();
    } catch (error) {
        console.error('renderProfile error', error);
        const heroMount = document.getElementById('profileHeroMount');
        if (heroMount) {
            heroMount.innerHTML = `
                <section class="surface-card surface-card--padded profile-hero-card">
                    <div class="profile-hero-main">
                        <div class="profile-hero-avatar">${(currentUser?.name || currentUser?.email || '?').slice(0, 2).toUpperCase()}</div>
                        <div>
                            <div class="profile-hero-eyebrow">Личный рабочий кабинет</div>
                            <h2 class="profile-hero-title">${currentUser?.name || 'Пользователь'}</h2>
                            <p class="profile-hero-text">${currentUser?.role || 'Сотрудник'} · ${currentUser?.email || ''}</p>
                        </div>
                    </div>
                </section>
            `;
        }
        if (typeof showToast === 'function') {
            showToast('Профиль', 'Часть данных профиля не загрузилась, но кабинет открыт.');
        }
    }
}

function profileEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function canShowEmployeeSelfService() {
    return !!currentUser && currentUser.role !== 'Директор';
}

async function loadEmployeeSelfServiceData(force = false) {
    if (!canShowEmployeeSelfService()) {
        employeeSelfServiceDB = null;
        employeeSelfServiceLoadedFor = '';
        return null;
    }
    const targetEmail = currentUser.email || '';
    if (!force && employeeSelfServiceLoadedFor === targetEmail && employeeSelfServiceDB) {
        return employeeSelfServiceDB;
    }
    const data = await apiCall(`/users/self_service/summary?user_email=${encodeURIComponent(targetEmail)}`);
    employeeSelfServiceDB = data && !data.error ? data : {
        metrics: {},
        leave_requests: [],
        timesheet_entries: [],
        equipment_requests: [],
        substitutions: [],
        business_trips: [],
    };
    employeeSelfServiceLoadedFor = targetEmail;
    return employeeSelfServiceDB;
}

function renderSelfServiceMetric(title, value, subtitle = '') {
    return `
        <div class="metric-card">
            <div class="metric-title">${profileEscape(title)}</div>
            <div class="metric-value">${profileEscape(value)}</div>
            <div class="section-subtitle" style="margin-top:8px;">${profileEscape(subtitle)}</div>
        </div>
    `;
}

function profileShortcutRead(actionKey) {
    const prefix = `profileShortcut_${actionKey}_`;
    const keyValue = String(document.getElementById(`${prefix}key`)?.value || '').trim();
    return {
        ctrl: Boolean(document.getElementById(`${prefix}ctrl`)?.checked),
        meta: Boolean(document.getElementById(`${prefix}meta`)?.checked),
        alt: Boolean(document.getElementById(`${prefix}alt`)?.checked),
        shift: Boolean(document.getElementById(`${prefix}shift`)?.checked),
        key: keyValue ? keyValue.slice(0, 1).toLowerCase() : '',
    };
}

function renderWorkspacePreferencePanel() {
    const mount = document.getElementById('profileWorkspacePrefsMount');
    if (!mount) return;
    const config = typeof loadWorkspaceConfig === 'function' ? loadWorkspaceConfig() : null;
    const preference = String(config?.platformPreference || 'auto');
    const resolvedPlatform = typeof resolveWorkspaceShortcutPlatform === 'function'
        ? resolveWorkspaceShortcutPlatform(preference)
        : 'windows';
    const defs = window.WORKSPACE_SHORTCUT_DEFS || {};
    const rows = Object.entries(defs).map(([actionKey, definition]) => {
        const shortcut = typeof getWorkspaceShortcutConfig === 'function'
            ? getWorkspaceShortcutConfig(actionKey, config)
            : { ctrl: false, meta: true, alt: false, shift: false, key: 'k' };
        const preview = typeof formatWorkspaceShortcutLabel === 'function'
            ? formatWorkspaceShortcutLabel(shortcut, resolvedPlatform)
            : shortcut.key;
        const prefix = `profileShortcut_${actionKey}_`;
        return `
            <div class="profile-shortcut-row">
                <div class="profile-shortcut-copy">
                    <div class="profile-shortcut-title">${profileEscape(definition.label || actionKey)}</div>
                    <div class="profile-shortcut-text">${profileEscape(definition.description || '')}</div>
                </div>
                <div class="profile-shortcut-form">
                    <label class="profile-shortcut-toggle">
                        <input id="${prefix}ctrl" type="checkbox" ${shortcut.ctrl ? 'checked' : ''}>
                        <span>Ctrl</span>
                    </label>
                    <label class="profile-shortcut-toggle">
                        <input id="${prefix}meta" type="checkbox" ${shortcut.meta ? 'checked' : ''}>
                        <span>${resolvedPlatform === 'mac' ? '⌘ Cmd' : 'Win'}</span>
                    </label>
                    <label class="profile-shortcut-toggle">
                        <input id="${prefix}alt" type="checkbox" ${shortcut.alt ? 'checked' : ''}>
                        <span>${resolvedPlatform === 'mac' ? 'Option' : 'Alt'}</span>
                    </label>
                    <label class="profile-shortcut-toggle">
                        <input id="${prefix}shift" type="checkbox" ${shortcut.shift ? 'checked' : ''}>
                        <span>Shift</span>
                    </label>
                    <input id="${prefix}key" class="auth-input profile-shortcut-key" type="text" maxlength="1" value="${profileEscape(shortcut.key || '')}" placeholder="K">
                    <span class="profile-shortcut-preview">${profileEscape(preview)}</span>
                    <button class="btn-primary" type="button" onclick="saveProfileShortcut('${actionKey}')">Сохранить</button>
                    <button class="btn-secondary" type="button" onclick="resetProfileShortcut('${actionKey}')">По умолчанию</button>
                </div>
            </div>
        `;
    }).join('');
    mount.innerHTML = `
        <div class="section-header">
            <div>
                <h3 class="section-title">Поиск и горячие клавиши</h3>
                <p class="section-subtitle">Выберите платформу и настройте сочетания так, как привыкли работать в Windows или macOS.</p>
            </div>
            <span class="ops-section-chip ops-section-chip--primary">${resolvedPlatform === 'mac' ? 'macOS' : 'Windows/PC'}</span>
        </div>
        <div class="profile-workspace-prefs">
            <div class="profile-platform-card">
                <label class="profile-platform-label" for="profilePlatformPreference">Платформа сочетаний</label>
                <select id="profilePlatformPreference" class="auth-input" onchange="saveProfilePlatformPreference(this.value)">
                    <option value="auto" ${preference === 'auto' ? 'selected' : ''}>Автоопределение</option>
                    <option value="windows" ${preference === 'windows' ? 'selected' : ''}>Windows / Ctrl</option>
                    <option value="mac" ${preference === 'mac' ? 'selected' : ''}>macOS / Command</option>
                </select>
                <div class="profile-platform-note">Сейчас используется: ${resolvedPlatform === 'mac' ? 'macOS' : 'Windows/PC'}.</div>
            </div>
            <div class="profile-shortcut-grid">${rows}</div>
        </div>
    `;
}

window.saveProfilePlatformPreference = function(value) {
    if (typeof saveWorkspacePlatformPreference === 'function') saveWorkspacePlatformPreference(value);
    if (typeof updateCommandPaletteShortcutHints === 'function') updateCommandPaletteShortcutHints();
    renderWorkspacePreferencePanel();
    if (typeof showToast === 'function') showToast('Рабочая среда', 'Платформа сочетаний сохранена');
};

window.saveProfileShortcut = function(actionKey) {
    const shortcut = profileShortcutRead(actionKey);
    if (!shortcut.key) {
        if (typeof customAlert === 'function') customAlert('Укажи клавишу для сочетания.');
        return;
    }
    if (!shortcut.ctrl && !shortcut.meta && !shortcut.alt && !shortcut.shift) {
        if (typeof customAlert === 'function') customAlert('Выбери хотя бы один модификатор: Ctrl, Cmd/Win, Alt или Shift.');
        return;
    }
    if (typeof saveWorkspaceShortcutConfig === 'function') saveWorkspaceShortcutConfig(actionKey, shortcut);
    if (typeof updateCommandPaletteShortcutHints === 'function') updateCommandPaletteShortcutHints();
    renderWorkspacePreferencePanel();
    if (typeof showToast === 'function') showToast('Горячие клавиши', 'Сочетание сохранено');
};

window.resetProfileShortcut = function(actionKey) {
    if (typeof resetWorkspaceShortcutConfig === 'function') resetWorkspaceShortcutConfig(actionKey);
    if (typeof updateCommandPaletteShortcutHints === 'function') updateCommandPaletteShortcutHints();
    renderWorkspacePreferencePanel();
    if (typeof showToast === 'function') showToast('Горячие клавиши', 'Сочетание сброшено к умолчанию');
};

function renderSelfServiceList(items, renderer, emptyText) {
    if (!Array.isArray(items) || !items.length) {
        return `<div class="empty-state" style="text-align:left;">${profileEscape(emptyText)}</div>`;
    }
    return items.map(renderer).join('');
}

function renderEmployeeSelfServicePanel() {
    const mount = document.getElementById('employeeSelfServiceMount');
    if (!mount) return;
    if (!canShowEmployeeSelfService()) {
        mount.innerHTML = '';
        return;
    }
    if (!employeeSelfServiceDB || employeeSelfServiceLoadedFor !== currentUser.email) {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded">
                <div class="section-header">
                    <div>
                        <h3 class="section-title">Self-service кабинет</h3>
                        <p class="section-subtitle">Загружаю отпуск, табель, оснащение, замещения и командировки.</p>
                    </div>
                </div>
            </section>
        `;
        loadEmployeeSelfServiceData(true).then(() => {
            const profileView = document.getElementById('profileView');
            if (profileView && profileView.style.display === 'block') renderProfile();
        });
        return;
    }
    const summary = employeeSelfServiceDB || {};
    const metrics = summary.metrics || {};
    const projectOptions = ['<option value="0">Без проекта</option>']
        .concat((projectsDB || []).map(item => `<option value="${Number(item.id || 0)}">${profileEscape(item.name || `Проект #${item.id}`)}</option>`))
        .join('');
    const colleagueOptions = ['<option value="">Без выбора</option>']
        .concat((allUsersDB || [])
            .filter(item => item.email !== currentUser.email && item.status === 'approved')
            .map(item => `<option value="${profileEscape(item.name)}">${profileEscape(item.name)} (${profileEscape(item.role || '')})</option>`))
        .join('');
    mount.innerHTML = `
        <section class="surface-card surface-card--padded role-workbench role-workbench--compact" style="margin-bottom:16px;">
            <div class="role-workbench-copy">
                <div class="view-eyebrow">Self-service</div>
                <h3 class="section-title">Личный HR-контур сотрудника</h3>
                <p class="section-subtitle">Отпуск, табель, оснащение, замещения и командировки теперь живут в одном кабинете без прыжков по разделам.</p>
            </div>
            <div class="role-workbench-actions">
                <button class="btn-primary" onclick="document.getElementById('ssTimesheetDate')?.focus()">Табель</button>
                <button class="btn-secondary" onclick="document.getElementById('ssLeaveFrom')?.focus()">Отпуск</button>
                <button class="btn-secondary" onclick="document.getElementById('ssEquipmentItem')?.focus()">Оснащение</button>
            </div>
        </section>
        <div class="metrics-grid" style="margin-bottom:16px;">
            ${renderSelfServiceMetric('Открытых HR-запросов', (Number(metrics.leave_pending || 0) + Number(metrics.equipment_open || 0) + Number(metrics.business_trips_open || 0)), 'в очереди на обработку')}
            ${renderSelfServiceMetric('Часов за месяц', Number(metrics.timesheet_hours_month || 0), 'подано в табель')}
            ${renderSelfServiceMetric('Замещения', Number(metrics.substitutions_active || 0), 'активные и ожидающие')}
            ${renderSelfServiceMetric('Мои задачи', Number(metrics.open_tasks || 0), 'ещё в работе')}
        </div>
        <div class="finance-layout">
            <section class="surface-card surface-card--padded ops-form-card">
                <div class="section-header">
                    <div>
                        <h3 class="section-title">Новые обращения</h3>
                        <p class="section-subtitle">Заполняй типовой self-service без свободных писем и ручных переписок.</p>
                    </div>
                </div>

                <div class="ops-inline-section">
                    <div class="ops-inline-title">Отпуск / отсутствие</div>
                    <div class="finance-form-grid" style="margin-top:12px;">
                        <select id="ssLeaveType" class="auth-input" style="margin:0;">
                            <option value="vacation">Отпуск</option>
                            <option value="sick_leave">Больничный</option>
                            <option value="day_off">Отгул</option>
                            <option value="other">Другое</option>
                        </select>
                        <input id="ssLeaveFrom" class="auth-input" style="margin:0;" placeholder="С даты">
                        <input id="ssLeaveTo" class="auth-input" style="margin:0;" placeholder="По дату">
                        <select id="ssLeaveDeputy" class="auth-input" style="margin:0;">${colleagueOptions}</select>
                        <textarea id="ssLeaveComment" class="auth-input" style="margin:0; min-height:76px; grid-column:1 / -1;" placeholder="Комментарий или основание"></textarea>
                    </div>
                    <div class="finance-actions-row" style="margin-top:10px;"><button class="btn-primary" onclick="saveEmployeeLeaveRequest()">Подать отсутствие</button></div>
                </div>

                <div class="ops-inline-section" style="margin-top:18px;">
                    <div class="ops-inline-title">Табель</div>
                    <div class="finance-form-grid" style="margin-top:12px;">
                        <input id="ssTimesheetDate" class="auth-input" style="margin:0;" placeholder="Дата">
                        <select id="ssTimesheetProject" class="auth-input" style="margin:0;">${projectOptions}</select>
                        <input id="ssTimesheetHours" class="auth-input" style="margin:0;" placeholder="Часы">
                        <select id="ssTimesheetMode" class="auth-input" style="margin:0;">
                            <option value="office">Офис</option>
                            <option value="remote">Удалённо</option>
                            <option value="onsite">На объекте</option>
                        </select>
                        <textarea id="ssTimesheetComment" class="auth-input" style="margin:0; min-height:76px; grid-column:1 / -1;" placeholder="Что было сделано"></textarea>
                    </div>
                    <div class="finance-actions-row" style="margin-top:10px;"><button class="btn-primary" onclick="saveEmployeeTimesheetEntry()">Записать часы</button></div>
                </div>

                <div class="ops-inline-section" style="margin-top:18px;">
                    <div class="ops-inline-title">Заявка на оснащение</div>
                    <div class="finance-form-grid" style="margin-top:12px;">
                        <select id="ssEquipmentCategory" class="auth-input" style="margin:0;">
                            <option value="workplace">Рабочее место</option>
                            <option value="hardware">Техника</option>
                            <option value="access">Доступы</option>
                            <option value="tools">Инструмент</option>
                        </select>
                        <input id="ssEquipmentItem" class="auth-input" style="margin:0;" placeholder="Что нужно">
                        <input id="ssEquipmentQty" class="auth-input" style="margin:0;" placeholder="Кол-во">
                        <input id="ssEquipmentNeededBy" class="auth-input" style="margin:0;" placeholder="Нужно к дате">
                        <textarea id="ssEquipmentJustification" class="auth-input" style="margin:0; min-height:76px; grid-column:1 / -1;" placeholder="Для чего нужно"></textarea>
                    </div>
                    <div class="finance-actions-row" style="margin-top:10px;"><button class="btn-primary" onclick="saveEmployeeEquipmentRequest()">Запросить оснащение</button></div>
                </div>

                <div class="ops-inline-section" style="margin-top:18px;">
                    <div class="ops-inline-title">Замещение</div>
                    <div class="finance-form-grid" style="margin-top:12px;">
                        <select id="ssSubstituteName" class="auth-input" style="margin:0;">${colleagueOptions}</select>
                        <input id="ssSubstituteFrom" class="auth-input" style="margin:0;" placeholder="С даты">
                        <input id="ssSubstituteTo" class="auth-input" style="margin:0;" placeholder="По дату">
                        <textarea id="ssSubstituteReason" class="auth-input" style="margin:0; min-height:76px; grid-column:1 / -1;" placeholder="Что должен покрыть заместитель"></textarea>
                    </div>
                    <div class="finance-actions-row" style="margin-top:10px;"><button class="btn-primary" onclick="saveEmployeeSubstitutionRequest()">Назначить замещение</button></div>
                </div>

                <div class="ops-inline-section" style="margin-top:18px;">
                    <div class="ops-inline-title">Командировка</div>
                    <div class="finance-form-grid" style="margin-top:12px;">
                        <input id="ssTripDestination" class="auth-input" style="margin:0;" placeholder="Куда">
                        <input id="ssTripFrom" class="auth-input" style="margin:0;" placeholder="С даты">
                        <input id="ssTripTo" class="auth-input" style="margin:0;" placeholder="По дату">
                        <select id="ssTripTransport" class="auth-input" style="margin:0;">
                            <option value="train">Поезд</option>
                            <option value="plane">Самолёт</option>
                            <option value="car">Авто</option>
                            <option value="other">Другое</option>
                        </select>
                        <input id="ssTripCost" class="auth-input" style="margin:0;" placeholder="Оценка затрат">
                        <textarea id="ssTripPurpose" class="auth-input" style="margin:0; min-height:76px; grid-column:1 / -1;" placeholder="Цель поездки"></textarea>
                    </div>
                    <div class="finance-actions-row" style="margin-top:10px;"><button class="btn-primary" onclick="saveEmployeeBusinessTrip()">Подать командировку</button></div>
                </div>
            </section>

            <section class="surface-card surface-card--padded ops-list-card">
                <div class="section-header">
                    <div>
                        <h3 class="section-title">Мой self-service реестр</h3>
                        <p class="section-subtitle">Последние записи по HR-контуру и оснащению с текущими статусами.</p>
                    </div>
                </div>

                <div class="ops-inline-section">
                    <div class="ops-inline-title">Отсутствия</div>
                    <div class="client360-list" style="margin-top:12px;">
                        ${renderSelfServiceList(summary.leave_requests, item => `
                            <div class="client360-item">
                                <div>
                                    <div class="client360-item-title">${profileEscape(item.leave_type || 'leave')} · ${profileEscape(item.date_from || '')} - ${profileEscape(item.date_to || '')}</div>
                                    <div class="client360-item-meta">${profileEscape(item.status || '')}${item.deputy_name ? ` · заместитель ${profileEscape(item.deputy_name)}` : ''}</div>
                                </div>
                                <button class="btn-secondary" onclick="deleteEmployeeSelfServiceItem('leave_requests', ${Number(item.id || 0)})">Удалить</button>
                            </div>
                        `, 'Заявок на отсутствие пока нет.')}
                    </div>
                </div>

                <div class="ops-inline-section" style="margin-top:18px;">
                    <div class="ops-inline-title">Табель</div>
                    <div class="client360-list" style="margin-top:12px;">
                        ${renderSelfServiceList(summary.timesheet_entries, item => `
                            <div class="client360-item">
                                <div>
                                    <div class="client360-item-title">${profileEscape(item.entry_date || '')} · ${profileEscape(item.hours || 0)} ч</div>
                                    <div class="client360-item-meta">${profileEscape(item.project_name || 'Без проекта')} · ${profileEscape(item.work_mode || '')} · ${profileEscape(item.status || '')}</div>
                                </div>
                                <button class="btn-secondary" onclick="deleteEmployeeSelfServiceItem('timesheets', ${Number(item.id || 0)})">Удалить</button>
                            </div>
                        `, 'Табельных записей пока нет.')}
                    </div>
                </div>

                <div class="ops-inline-section" style="margin-top:18px;">
                    <div class="ops-inline-title">Оснащение</div>
                    <div class="client360-list" style="margin-top:12px;">
                        ${renderSelfServiceList(summary.equipment_requests, item => `
                            <div class="client360-item">
                                <div>
                                    <div class="client360-item-title">${profileEscape(item.item_name || '')} · ${profileEscape(item.qty || 1)} шт</div>
                                    <div class="client360-item-meta">${profileEscape(item.category || '')} · ${profileEscape(item.status || '')} · к ${profileEscape(item.needed_by || '')}</div>
                                </div>
                                <button class="btn-secondary" onclick="deleteEmployeeSelfServiceItem('equipment_requests', ${Number(item.id || 0)})">Удалить</button>
                            </div>
                        `, 'Заявок на оснащение пока нет.')}
                    </div>
                </div>

                <div class="ops-inline-section" style="margin-top:18px;">
                    <div class="ops-inline-title">Замещения и командировки</div>
                    <div class="client360-list" style="margin-top:12px;">
                        ${renderSelfServiceList([...(summary.substitutions || []), ...(summary.business_trips || [])], item => {
                            const kind = item.destination ? 'business_trips' : 'substitutions';
                            const title = item.destination
                                ? `${profileEscape(item.destination)} · ${profileEscape(item.date_from || '')} - ${profileEscape(item.date_to || '')}`
                                : `${profileEscape(item.substitute_name || 'Замещение')} · ${profileEscape(item.date_from || '')} - ${profileEscape(item.date_to || '')}`;
                            const meta = item.destination
                                ? `${profileEscape(item.transport_mode || '')} · ${profileEscape(item.status || '')}`
                                : `${profileEscape(item.reason || '')} · ${profileEscape(item.status || '')}`;
                            return `
                                <div class="client360-item">
                                    <div>
                                        <div class="client360-item-title">${title}</div>
                                        <div class="client360-item-meta">${meta}</div>
                                    </div>
                                    <button class="btn-secondary" onclick="deleteEmployeeSelfServiceItem('${kind}', ${Number(item.id || 0)})">Удалить</button>
                                </div>
                            `;
                        }, 'Замещений и командировок пока нет.')}
                    </div>
                </div>
            </section>
        </div>
    `;
}

async function refreshEmployeeSelfServicePanel() {
    await loadEmployeeSelfServiceData(true);
    renderEmployeeSelfServicePanel();
}

async function saveEmployeeLeaveRequest() {
    const payload = {
        user_email: currentUser.email,
        leave_type: document.getElementById('ssLeaveType')?.value || 'vacation',
        date_from: document.getElementById('ssLeaveFrom')?.value || '',
        date_to: document.getElementById('ssLeaveTo')?.value || '',
        deputy_name: document.getElementById('ssLeaveDeputy')?.value || '',
        comment: document.getElementById('ssLeaveComment')?.value || '',
        status: 'pending',
    };
    if (!payload.date_from || !payload.date_to) return customAlert('Укажи период отсутствия.');
    const res = await apiCall('/users/self_service/leave_requests', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить отсутствие.');
    document.getElementById('ssLeaveComment').value = '';
    showToast('Self-service', 'Запрос на отсутствие создан');
    await refreshEmployeeSelfServicePanel();
}

async function saveEmployeeTimesheetEntry() {
    const payload = {
        user_email: currentUser.email,
        entry_date: document.getElementById('ssTimesheetDate')?.value || '',
        project_id: Number(document.getElementById('ssTimesheetProject')?.value || 0),
        hours: Number(document.getElementById('ssTimesheetHours')?.value || 0),
        work_mode: document.getElementById('ssTimesheetMode')?.value || 'office',
        comment: document.getElementById('ssTimesheetComment')?.value || '',
        status: 'submitted',
    };
    if (!payload.entry_date || !payload.hours) return customAlert('Укажи дату и часы.');
    const res = await apiCall('/users/self_service/timesheets', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить табель.');
    document.getElementById('ssTimesheetComment').value = '';
    document.getElementById('ssTimesheetHours').value = '';
    showToast('Self-service', 'Табельная запись добавлена');
    await refreshEmployeeSelfServicePanel();
}

async function saveEmployeeEquipmentRequest() {
    const payload = {
        user_email: currentUser.email,
        category: document.getElementById('ssEquipmentCategory')?.value || 'workplace',
        item_name: document.getElementById('ssEquipmentItem')?.value || '',
        qty: Number(document.getElementById('ssEquipmentQty')?.value || 1),
        needed_by: document.getElementById('ssEquipmentNeededBy')?.value || '',
        justification: document.getElementById('ssEquipmentJustification')?.value || '',
        status: 'pending',
    };
    if (!payload.item_name) return customAlert('Укажи, что нужно выдать.');
    const res = await apiCall('/users/self_service/equipment_requests', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить заявку на оснащение.');
    document.getElementById('ssEquipmentItem').value = '';
    document.getElementById('ssEquipmentQty').value = '';
    document.getElementById('ssEquipmentJustification').value = '';
    showToast('Self-service', 'Заявка на оснащение создана');
    await refreshEmployeeSelfServicePanel();
}

async function saveEmployeeSubstitutionRequest() {
    const payload = {
        user_email: currentUser.email,
        substitute_name: document.getElementById('ssSubstituteName')?.value || '',
        date_from: document.getElementById('ssSubstituteFrom')?.value || '',
        date_to: document.getElementById('ssSubstituteTo')?.value || '',
        reason: document.getElementById('ssSubstituteReason')?.value || '',
        status: 'pending',
    };
    if (!payload.substitute_name || !payload.date_from || !payload.date_to) return customAlert('Укажи заместителя и период.');
    const res = await apiCall('/users/self_service/substitutions', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить замещение.');
    document.getElementById('ssSubstituteReason').value = '';
    showToast('Self-service', 'Замещение отправлено');
    await refreshEmployeeSelfServicePanel();
}

async function saveEmployeeBusinessTrip() {
    const payload = {
        user_email: currentUser.email,
        destination: document.getElementById('ssTripDestination')?.value || '',
        date_from: document.getElementById('ssTripFrom')?.value || '',
        date_to: document.getElementById('ssTripTo')?.value || '',
        purpose: document.getElementById('ssTripPurpose')?.value || '',
        transport_mode: document.getElementById('ssTripTransport')?.value || 'train',
        estimated_cost: Number(document.getElementById('ssTripCost')?.value || 0),
        status: 'pending',
    };
    if (!payload.destination || !payload.date_from || !payload.date_to) return customAlert('Укажи направление и даты командировки.');
    const res = await apiCall('/users/self_service/business_trips', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить командировку.');
    document.getElementById('ssTripDestination').value = '';
    document.getElementById('ssTripPurpose').value = '';
    document.getElementById('ssTripCost').value = '';
    showToast('Self-service', 'Командировка отправлена');
    await refreshEmployeeSelfServicePanel();
}

async function deleteEmployeeSelfServiceItem(kind, id) {
    const pathMap = {
        leave_requests: `/users/self_service/leave_requests/${id}`,
        timesheets: `/users/self_service/timesheets/${id}`,
        equipment_requests: `/users/self_service/equipment_requests/${id}`,
        substitutions: `/users/self_service/substitutions/${id}`,
        business_trips: `/users/self_service/business_trips/${id}`,
    };
    const endpoint = pathMap[kind];
    if (!endpoint) return;
    if (!(await customConfirm('Удалить запись из self-service?'))) return;
    const res = await apiCall(endpoint, 'DELETE');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось удалить запись.');
    showToast('Self-service', 'Запись удалена');
    await refreshEmployeeSelfServicePanel();
}

async function saveVacation() {
    const vType = document.getElementById('absType').value;
    const vStart = document.getElementById('absStart').value;
    const vEnd = document.getElementById('absEnd').value;
    const vReason = document.getElementById('absReason').value;
    const vDep = document.getElementById('vacationDeputy').value;
    
    if (!vStart || !vEnd) { await customAlert("Пожалуйста, укажите даты начала и окончания отсутствия."); return; }

    const btn = document.querySelector('button[onclick="saveVacation()"]'); const oldText = btn.innerText;
    if(btn) { btn.innerText = "Сохранение..."; btn.disabled = true; }

    const res = await apiCall('/users/vacation', 'POST', { email: currentUser.email, abs_start: vStart, abs_end: vEnd, abs_type: vType, abs_reason: vReason, deputy: vDep });
    
    if (res && res.status === 'success') {
        if(btn) { btn.innerText = "✅ Настройки сохранены!"; btn.style.background = "var(--success)"; }
        await loadAllUsers(); renderProfile();
        setTimeout(() => { if(btn) { btn.innerText = oldText; btn.style.background = "var(--primary)"; btn.disabled = false; } }, 2500);
    } else {
        await customAlert("Ошибка соединения с сервером."); if(btn) { btn.innerText = oldText; btn.disabled = false; }
    }
}

async function clearVacation() {
    if(!(await customConfirm("Сбросить статус отсутствия? Вы вернетесь к обычной работе."))) return;
    await apiCall('/users/vacation', 'POST', { email: currentUser.email, abs_start: "", abs_end: "", abs_type: "", abs_reason: "", deputy: "" });
    await loadAllUsers(); renderProfile(); await customAlert("С возвращением!");
}

async function removeUser(email) { if(await customConfirm(`Заблокировать пользователя ${email}? Он потеряет доступ к системе.`)) { await apiCall('/users/remove', 'POST', { email: email }); await loadAllUsers(); if (typeof loadAuditLogs === 'function') await loadAuditLogs(); renderProfile(); } }
async function restoreUser(email) { if(await customConfirm(`Восстановить доступ пользователю ${email}?`)) { await apiCall('/users/restore', 'POST', { email: email }); await loadAllUsers(); if (typeof loadAuditLogs === 'function') await loadAuditLogs(); renderProfile(); } }

async function toggleHeadStatus(email, status) {
    if(await customConfirm(status === 1 ? `Назначить ${email} руководителем отдела?` : `Снять права руководителя с ${email}?`)) {
        await apiCall('/users/make_head', 'POST', { email: email, role: '', is_head: status });
        await loadAllUsers(); if (typeof loadAuditLogs === 'function') await loadAuditLogs(); renderProfile();
    }
}

// НОВАЯ ФУНКЦИЯ ДЛЯ СМЕНЫ ОТДЕЛА
async function changeUserRole(email, currentRole) {
    const newRole = await customPrompt(`Введите новую роль/отдел для ${email} (сейчас: ${currentRole}):`, currentRole);
    if (!newRole || newRole === currentRole) return;
    
    await apiCall(`/users/role`, 'PUT', { email: email, role: newRole });
    showToast('Пользователи', 'Роль сотрудника обновлена');
    if (typeof loadAllUsers === 'function') await loadAllUsers();
    if (typeof loadAuditLogs === 'function') await loadAuditLogs();
    renderProfile();     
}

async function changeUserAccessScope(email) {
    const user = (allUsersDB || []).find(item => item.email === email);
    if (!user) return customAlert('Пользователь не найден.');
    const meta = await ensureFinanceScopeMeta();
    const legalHint = (meta.legal_entities || []).map(item => `${item.id} - ${item.short_name || item.name}`).join('\n') || 'Справочник юрлиц пока пуст.';
    const buHint = (meta.business_units || []).map(item => `${item.id} - ${item.name} (${item.legal_entity_name || 'LE?'})`).join('\n') || 'Справочник подразделений пока пуст.';
    const legalRaw = await customPrompt(`Укажи идентификаторы доступных юрлиц для ${user.name} через запятую.\nПусто = доступ ко всем.\n\n${legalHint}`, (user.allowed_legal_entities || []).join(', '));
    if (legalRaw === null) return;
    const buRaw = await customPrompt(`Укажи идентификаторы доступных подразделений для ${user.name} через запятую.\nПусто = доступ ко всем.\n\n${buHint}`, (user.allowed_business_units || []).join(', '));
    if (buRaw === null) return;
    const enable2fa = await customConfirm(`Включить двухфакторную защиту для ${user.name}? Сейчас: ${user.two_factor_enabled ? 'включена' : 'выключена'}`);
    const parseIds = (value) => String(value || '')
        .split(',')
        .map(item => parseInt(item.trim(), 10))
        .filter(item => Number.isFinite(item) && item > 0);
    const res = await apiCall('/users/access_scope', 'PUT', {
        email,
        allowed_legal_entities: parseIds(legalRaw),
        allowed_business_units: parseIds(buRaw),
        two_factor_enabled: enable2fa ? 1 : 0,
    });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить область доступа.');
    showToast('Пользователи', 'Область доступа и флаг безопасности обновлены');
    await loadAllUsers();
    await reloadSecurityOps();
    if (typeof loadAuditLogs === 'function') await loadAuditLogs();
    renderProfile();
}

async function revokeUserSession(sessionId, userEmail) {
    if (!(await customConfirm(`Завершить сессию ${userEmail || 'пользователя'}?`))) return;
    const res = await apiCall('/users/sessions/revoke', 'POST', { session_id: sessionId, user_email: userEmail || '' });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось завершить сессию.');
    showToast('Безопасность', 'Сессия завершена');
    await reloadSecurityOps();
}

function renderNotifications() {
    let html = '';
    const notifications = notificationsDB || [];
    const unread = notifications.filter(n => !n.is_read).length;

    const categoryLabel = (category) => ({
        task: 'Задачи',
        approval: 'Согласования',
        project: 'Проекты',
        user: 'Пользователи',
        email: 'Почта',
        lead: 'Лиды',
        deal: 'Сделки',
        finance: 'Оплаты',
        expense: 'Оплаты',
        request: 'Заявки',
        service: 'Сервис',
        system: 'Система',
    }[String(category || 'system').toLowerCase()] || 'Событие');

    const iconSvg = (category) => ({
        task: '<path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>',
        approval: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>',
        project: '<path d="M3 7h18"></path><path d="M7 3v4"></path><path d="M17 3v4"></path><rect x="3" y="5" width="18" height="16" rx="2"></rect>',
        user: '<path d="M20 21a8 8 0 1 0-16 0"></path><circle cx="12" cy="7" r="4"></circle>',
        email: '<path d="M4 4h16v16H4z"></path><path d="m22 6-10 7L2 6"></path>',
        lead: '<path d="M12 2v20"></path><path d="M2 12h20"></path>',
        deal: '<circle cx="12" cy="12" r="9"></circle><path d="M9 12h6"></path><path d="M12 9v6"></path>',
        finance: '<path d="M12 1v22"></path><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>',
        expense: '<path d="M12 1v22"></path><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>',
        request: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path>',
        service: '<path d="M12 1v6"></path><path d="M12 17v6"></path><path d="m4.93 4.93 4.24 4.24"></path><path d="m14.83 14.83 4.24 4.24"></path><path d="M1 12h6"></path><path d="M17 12h6"></path><path d="m4.93 19.07 4.24-4.24"></path><path d="m14.83 9.17 4.24-4.24"></path>',
        system: '<path d="M12 2v20"></path><path d="M2 12h20"></path>',
    }[String(category || 'system').toLowerCase()] || '<path d="M12 2v20"></path><path d="M2 12h20"></path>');

    notifications.slice(0, 40).forEach(n => {
        const notifId = `notif_${n.id}`;
        if (!seenToastIds.has(notifId)) {
            seenToastIds.add(notifId);
            if (!isFirstLoad && !n.is_read) {
                showToast(n.title || 'Уведомление', n.message || '', n.entity_type === 'project' ? Number(n.entity_id || 0) : null);
            }
        }

        const createdAt = new Date((n.created_at || 0) * 1000).toLocaleString('ru-RU');
        const category = n.category || 'system';
        const iconClass =
            category === 'task' ? 'notif-yellow' :
            category === 'approval' ? 'notif-blue' :
            category === 'project' ? 'notif-green' :
            category === 'finance' || category === 'expense' ? 'notif-yellow' :
            category === 'email' ? 'notif-blue' :
            category === 'lead' ? 'notif-blue' :
            category === 'deal' ? 'notif-green' :
            category === 'user' ? 'notif-red' : 'notif-blue';

        const onClick = `onclick="openNotificationItem('${String(n.entity_type || '').replace(/'/g, '&#39;')}', '${String(n.entity_id || '').replace(/'/g, '&#39;')}', '${String(n.id || '').replace(/'/g, '&#39;')}', ${Number(n.synthetic || 0)})"`;

        html += `<div class="notif-item ${n.is_read ? '' : 'notif-item--unread'}" ${onClick}>
                    <div class="notif-icon ${iconClass}">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${iconSvg(category)}</svg>
                    </div>
                    <div class="notif-content">
                        <div class="notif-header-row">
                            <span class="notif-project">${categoryLabel(category)}</span>
                            <span class="notif-time">${createdAt}</span>
                        </div>
                        <div class="notif-text">
                            <b>${n.title || 'Уведомление'}</b><br>${n.message || ''}
                        </div>
                    </div>
                </div>`;
    });

    if (notifications.length === 0) html = '<div class="notif-empty">Пока нет серверных уведомлений</div>';
    const list = document.getElementById('notifList'); if(list) list.innerHTML = html;
    const badge = document.getElementById('notifBadge'); if(badge) { if(unread > 0) { badge.style.display = 'flex'; badge.innerText = unread > 99 ? '99+' : unread; } else { badge.style.display = 'none'; } }
    isFirstLoad = false;
}

function showToast(title, action, proj_id) {
    const container = document.getElementById('toastContainer'); if (!container) return;
    let cleanText = action; let borderColor = 'var(--success)';
    let toastTitle = title || 'Korda CRM';
    if (cleanText.includes('Выполнил задачу')) { cleanText = 'Поставил отметку в Чек-листе (Ждет проверки)'; borderColor = '#f59e0b'; }
    if (cleanText.includes('Утвердил')) cleanText = 'Задача проверена Директором';
    if (cleanText.includes('Снял галочку') || cleanText.includes('Снял утверждение')) { cleanText = 'Снял отметку в Чек-листе'; borderColor = 'var(--danger)'; }
    if (cleanText.includes('Вернул этап на доработку')) { cleanText = 'Внимание: этап возвращен на доработку!'; borderColor = '#f59e0b'; }
    if (cleanText.includes('АВТО-ЭСКАЛАЦИЯ')) borderColor = 'var(--danger)';
    if (title === 'Внимание') borderColor = '#f59e0b';
    if (title === 'Успех') borderColor = 'var(--success)';
    if (title === 'Ошибка') borderColor = 'var(--danger)';

    const toast = document.createElement('div'); toast.className = 'toast'; toast.style.borderLeftColor = borderColor;
    toast.innerHTML = `<div class="toast-title">${toastTitle}</div><div class="toast-desc">${cleanText}</div>`;
    if (typeof proj_id === 'number' && !Number.isNaN(proj_id)) {
        toast.onclick = () => openProject(proj_id);
    }
    container.appendChild(toast); setTimeout(() => toast.classList.add('show'), 100); 
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 400); }, 5000);
}

async function markNotificationRead(notificationId, closeAfter = false) {
    if (!notificationId || String(notificationId).startsWith('live-')) {
        if (closeAfter) {
            const dropdown = document.getElementById('notifDropdown');
            if (dropdown) {
                dropdown.classList.add('krd-is-hidden');
                dropdown.style.display = 'none';
            }
        }
        return;
    }
    await apiCall(`/notifications/${notificationId}/read`, 'POST');
    if (typeof loadNotifications === 'function') await loadNotifications();
    renderNotifications();
    if (closeAfter) {
        const dropdown = document.getElementById('notifDropdown');
        if (dropdown) {
            dropdown.classList.add('krd-is-hidden');
            dropdown.style.display = 'none';
        }
    }
}

async function markAllNotificationsRead() {
    await apiCall('/notifications/read_all', 'POST');
    if (typeof loadNotifications === 'function') await loadNotifications();
    renderNotifications();
}

window.openNotificationItem = async function(entityType, entityId, notificationId, synthetic = 0) {
    const type = String(entityType || '').toLowerCase();
    const rawId = String(entityId || '').trim();
    const numericId = Number(rawId || 0);

    if (type && rawId && typeof openOmniSearchResult === 'function') {
        await openOmniSearchResult(type, Number.isFinite(numericId) ? numericId : rawId, '');
    }

    await markNotificationRead(notificationId, true);

    if (synthetic) {
        if (typeof loadNotifications === 'function') await loadNotifications();
        renderNotifications();
    }
};

async function toggleNotifications(forceToggle = true) {
    const dropdown = document.getElementById('notifDropdown');
    if(!dropdown) return;
    const isOpen = !dropdown.classList.contains('krd-is-hidden') && dropdown.style.display === 'flex';
    if (isOpen && forceToggle) {
        dropdown.classList.add('krd-is-hidden');
        dropdown.style.display = 'none';
    } else {
        if (typeof loadNotifications === 'function') await loadNotifications();
        renderNotifications();
        dropdown.classList.remove('krd-is-hidden');
        dropdown.style.display = 'flex';
    }
}
document.addEventListener('click', (e) => {
    const wrap = document.querySelector('.notif-wrapper');
    const drop = document.getElementById('notifDropdown');
    if (wrap && !wrap.contains(e.target) && drop && drop.style.display === 'flex') {
        drop.classList.add('krd-is-hidden');
        drop.style.display = 'none';
    }
});

function renderClients() {
    const tbody = document.getElementById('clientsListTable');
    if (!tbody) return;
    bindClientSmartHints();

    const viewShell = tbody.closest('.surface-card, .project-panel, .table-shell') || tbody.closest('div');
    if (viewShell && !document.getElementById('btnExportClients')) {
        const btn = document.createElement('button');
        btn.id = 'btnExportClients';
        btn.className = 'btn-secondary no-print';
        btn.style.marginBottom = '16px';
        btn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            Экспорт контрагентов
        `;
        btn.onclick = () => exportDataToExcel(clientsDB, 'Реестр_Контрагентов');
        viewShell.insertBefore(btn, viewShell.firstChild);
    }

    if (clientsDB.length === 0) {
        tbody.innerHTML = typeof renderTableEmptyRow === 'function'
            ? renderTableEmptyRow(
                5,
                'Контрагенты пока не добавлены.',
                'Создай первого контрагента вручную или импортируй CSV/JSON, чтобы открыть клиентское досье.',
                `<button class="btn-primary" onclick="focusFieldById('addClientName')">Новый контрагент</button><button class="btn-secondary" onclick="document.getElementById('clientsImportFile')?.click()">Импорт файла</button>`
            )
            : `<tr><td colspan="5" class="nsi-empty-row">Контрагенты пока не добавлены.</td></tr>`;
        return;
    }

    const renderRows = () => clientsDB.map((client) => `
        <tr>
            <td>
                <div style="display:flex; align-items:center; gap:6px;">
                    ${typeof renderEntityFavoriteButton === 'function' ? renderEntityFavoriteButton('client', client.id, client.name || `Контрагент #${client.id}`, `${client.inn || ''} · ${client.contact || ''}`, 'clients', 'renderClients') : ''}
                    <button class="client-link-btn" onclick="openClientCard(${client.id})" title="Открыть досье контрагента">
                        ${client.name}
                    </button>
                </div>
            </td>
            <td>${client.inn || 'Не указан'}${client.kpp ? `<div style="font-size:12px; color:var(--secondary); margin-top:4px;">КПП ${client.kpp}</div>` : ''}</td>
            <td>${client.ogrn || 'Не указан'}</td>
            <td>${client.legal_address || 'Не указан'}</td>
            <td>${client.contact || 'Не указан'}</td>
        </tr>
    `).join('');
    if (typeof renderDeferredHtml === 'function') {
        renderDeferredHtml(tbody, renderRows, { size: clientsDB.length, threshold: 120, colspan: 5, loadingMessage: 'Загружаю контрагентов...' });
    } else {
        tbody.innerHTML = renderRows();
    }
}

function bindClientSmartHints() {
    if (typeof bindSmartFieldHints !== 'function') return;
    bindSmartFieldHints('clientsView', [
        {
            field: 'addClientInn',
            validate: value => {
                const digits = String(value || '').replace(/\D/g, '');
                if (!digits) return null;
                if (digits.length !== 10 && digits.length !== 12) {
                    return { tone: 'warning', message: 'ИНН обычно содержит 10 цифр для организации или 12 для ИП/физлица.' };
                }
                return { tone: 'hint', message: digits.length === 10 ? 'ИНН юрлица выглядит корректно.' : 'ИНН ИП/физлица выглядит корректно.' };
            },
        },
    ]);
}
async function addClient() {
    const n = document.getElementById('addClientName').value;
    const i = document.getElementById('addClientInn').value;
    const k = document.getElementById('addClientKpp')?.value || '';
    const o = document.getElementById('addClientOgrn')?.value || '';
    const a = document.getElementById('addClientLegalAddress')?.value || '';
    const c = document.getElementById('addClientContact').value;
    if(!n) return customAlert("Введите название!");
    const res = await apiCall('/clients', 'POST', {name: n, inn: i, kpp: k, ogrn: o, legal_address: a, contact: c});
    document.getElementById('addClientName').value = '';
    document.getElementById('addClientInn').value = '';
    if (document.getElementById('addClientKpp')) document.getElementById('addClientKpp').value = '';
    if (document.getElementById('addClientOgrn')) document.getElementById('addClientOgrn').value = '';
    if (document.getElementById('addClientLegalAddress')) document.getElementById('addClientLegalAddress').value = '';
    document.getElementById('addClientContact').value = '';
    await loadClients();
    renderClients();
    const clientId = Number(res?.id || 0) || Number((clientsDB.find(item => item.name === n && (item.inn || '') === (i || '')) || {}).id || 0);
    if (clientId && typeof openClientCard === 'function') {
        showToast('Контрагенты', 'Карточка создана, открываю досье');
        await openClientCard(clientId);
        return;
    }
    showToast('Контрагенты', 'Контрагент добавлен');
}

async function lookupClientInn() {
    const innInput = document.getElementById('addClientInn');
    const inn = String(innInput?.value || '').replace(/\D/g, '');
    if (!inn) return customAlert('Сначала укажите ИНН.');
    const res = await apiCall(`/clients/lookup_inn?inn=${encodeURIComponent(inn)}`);
    if (!res || res.error) {
        return customAlert(res?.error || 'Не удалось проверить ИНН.');
    }
    if (res.status === 'integration_not_configured') {
        return customAlert('Интеграция проверки ИНН не настроена. Нужно заполнить KORDA_DADATA_TOKEN в .env.');
    }
    if (res.status !== 'success' || !res.client) {
        return customAlert('Организация по этому ИНН не найдена.');
    }
    const client = res.client || {};
    if (document.getElementById('addClientName') && client.name) document.getElementById('addClientName').value = client.name;
    if (document.getElementById('addClientKpp') && client.kpp) document.getElementById('addClientKpp').value = client.kpp;
    if (document.getElementById('addClientOgrn') && client.ogrn) document.getElementById('addClientOgrn').value = client.ogrn;
    if (document.getElementById('addClientLegalAddress') && client.legal_address) document.getElementById('addClientLegalAddress').value = client.legal_address;
    if (document.getElementById('addClientContact') && client.contact && !document.getElementById('addClientContact').value) {
        document.getElementById('addClientContact').value = client.contact;
    }
    showToast('Контрагенты', 'Реквизиты по ИНН подтянуты');
}

window.lookupClientInn = lookupClientInn;

window.openFirstClientCard = async function() {
    if (!Array.isArray(clientsDB) || !clientsDB.length) {
        return customAlert('В базе пока нет контрагентов.');
    }
    await openClientCard(clientsDB[0].id);
};

async function importClientsFile() {
    const fileInput = document.getElementById('clientsImportFile');
    const file = fileInput?.files?.[0];
    if (!file) return customAlert('Выберите CSV или JSON файл с контрагентами.');
    const formData = new FormData();
    formData.append('upload', file);
    const res = await apiCall('/clients/import', 'POST', formData);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось импортировать контрагентов.');
    if (fileInput) fileInput.value = '';
    await loadClients();
    renderClients();
    if (typeof loadNSI === 'function') await loadNSI();
    showToast('Контрагенты', `Импорт завершён: +${res.created || 0}, обновлено ${res.updated || 0}`);
}

async function mergeClientsPrompt() {
    const masterId = await customPrompt('Идентификатор основной карточки клиента', '');
    if (!masterId) return;
    const duplicateIdsRaw = await customPrompt('Идентификаторы дублей через запятую', '');
    if (!duplicateIdsRaw) return;
    const duplicateIds = duplicateIdsRaw.split(',').map(item => Number(item.trim())).filter(Boolean);
    if (!duplicateIds.length) return customAlert('Нужен хотя бы один идентификатор дубля.');
    const res = await apiCall('/clients/merge', 'POST', { master_id: Number(masterId), duplicate_ids: duplicateIds });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось объединить контрагентов.');
    await loadClients();
    renderClients();
    showToast('Контрагенты', `Объединено дублей: ${res.merged || 0}`);
}

async function openAdminPanelLogic() { 
    const users = await apiCall('/users/pending'); 
    const tbody = document.getElementById('adminUsersList'); if(!tbody) return; 
    tbody.innerHTML = ''; 
    const opts = availableRoles.map(r => `<option value="${r}">${r}</option>`).join(''); 
    users.forEach((u, i) => { 
        tbody.innerHTML += `<tr>
            <td>${u.name}</td><td>${u.email}</td>
            <td><select id="role_${i}"><option disabled selected>Выбрать</option>${opts}</select></td>
            <td><label style="font-size:12px; display:flex; align-items:center; gap:5px;"><input type="checkbox" id="head_${i}"> Руководитель</label></td>
            <td><button class="btn-primary" onclick="approveUser('${u.email}', ${i})">Одобрить</button></td>
        </tr>`; 
    }); 
}

async function approveUser(e, i) { 
    const isHead = document.getElementById(`head_${i}`).checked ? 1 : 0;
    const res = await apiCall('/users/approve', 'POST', { email: e, role: document.getElementById(`role_${i}`).value, is_head: isHead });
    if (res && res.error) {
        return customAlert(res.error);
    }
    await openAdminPanelLogic();
    await loadAllUsers();
    if (typeof loadAuditLogs === 'function') await loadAuditLogs();
    renderProfile();
}

// Enterprise RLS panel overrides
function profileUiEscape(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function profileUiReadFlag(id) {
    const element = document.getElementById(id);
    if (!element) return 0;
    if (element.type === 'checkbox') return element.checked ? 1 : 0;
    return Number(element.value || 0);
}

renderFieldSecurityRulesPanel = function() {
    const block = document.getElementById('directorFieldSecurityBlock');
    const list = document.getElementById('fieldSecurityRulesList');
    if (!block || !list) return;

    if (!currentUser || currentUser.role !== 'Директор') {
        block.style.display = 'none';
        return;
    }

    block.style.display = 'block';

    if (!fieldSecurityRulesDB.length) {
        list.innerHTML = `
            <div class="krd-empty">
                <div class="krd-empty__title">Правил по полям пока нет</div>
                <div class="krd-empty__hint">Добавьте первое правило, чтобы ограничивать просмотр и редактирование на уровне записей.</div>
            </div>
        `;
        return;
    }

    const modules = new Set(fieldSecurityRulesDB.map(item => item.module_name).filter(Boolean));
    const roles = new Set(fieldSecurityRulesDB.map(item => item.role_name).filter(Boolean));
    const editable = fieldSecurityRulesDB.filter(item => Number(item.can_edit || 0) === 1).length;

    list.innerHTML = `
        <div class="krd-rls-summary">
            <div class="krd-rls-summary__item">
                <div class="krd-rls-summary__label">Правил</div>
                <div class="krd-rls-summary__value">${fieldSecurityRulesDB.length}</div>
            </div>
            <div class="krd-rls-summary__item">
                <div class="krd-rls-summary__label">Модулей</div>
                <div class="krd-rls-summary__value">${modules.size}</div>
            </div>
            <div class="krd-rls-summary__item">
                <div class="krd-rls-summary__label">Редактируемых</div>
                <div class="krd-rls-summary__value">${editable}</div>
            </div>
        </div>
        <div class="krd-rls-list">
            ${fieldSecurityRulesDB.map(item => `
                <div class="krd-rls-rule">
                    <div class="krd-rls-rule__main">
                        <div class="krd-rls-rule__title">${profileUiEscape(item.role_name)} · ${profileUiEscape(item.module_name)} / ${profileUiEscape(item.entity_type)} / ${profileUiEscape(item.field_name)}</div>
                        <div class="krd-rls-rule__meta">
                            <span class="ops-pill ${Number(item.can_view || 0) ? 'ops-pill--primary' : 'ops-pill--danger'}">${Number(item.can_view || 0) ? 'видно' : 'скрыто'}</span>
                            <span class="ops-pill ${Number(item.can_edit || 0) ? 'ops-pill--success' : ''}">${Number(item.can_edit || 0) ? 'редактирование разрешено' : 'только чтение'}</span>
                            <span>ролей под покрытием: ${roles.size}</span>
                        </div>
                        ${(item.allowed_statuses || []).length ? `
                            <div class="krd-rls-rule__statuses">
                                ${(item.allowed_statuses || []).map(status => `<span class="ops-pill">${profileUiEscape(status)}</span>`).join('')}
                            </div>
                        ` : '<div class="krd-rls-rule__meta">Статусы не ограничены.</div>'}
                    </div>
                    <div class="krd-rls-rule__actions">
                        <button class="btn-danger" onclick="deleteFieldSecurityRule(${Number(item.id)})">Удалить</button>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
};

saveFieldSecurityRule = async function() {
    const payload = {
        role: (document.getElementById('fieldRuleRole')?.value || '').trim(),
        module: (document.getElementById('fieldRuleModule')?.value || '').trim(),
        entity_type: (document.getElementById('fieldRuleEntity')?.value || '').trim(),
        field_name: (document.getElementById('fieldRuleField')?.value || '').trim(),
        can_view: profileUiReadFlag('fieldRuleCanView'),
        can_edit: profileUiReadFlag('fieldRuleCanEdit'),
        allowed_statuses: (document.getElementById('fieldRuleAllowedStatuses')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        is_active: 1,
    };

    if (!payload.role || !payload.module || !payload.entity_type || !payload.field_name) {
        return customAlert('Заполните роль, модуль, сущность и поле.');
    }

    const result = await apiCall('/users/field_rules', 'POST', payload);
    if (!result || result.error) return customAlert(result?.error || 'Не удалось сохранить правило по полям.');

    await reloadFieldSecurityRules();
    showToast('Безопасность', 'Правило по полям сохранено');
};
