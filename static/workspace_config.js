const WORKSPACE_DASHBOARD_BLOCKS = [
    { key: 'first_run', id: 'dashboardFirstRunMount', label: 'Первый запуск' },
    { key: 'hero', id: 'dashboardHeroMount', label: 'Главный блок портфеля' },
    { key: 'role_workbench', id: 'dashboardRoleWorkbenchMount', label: 'Рабочий контур роли' },
    { key: 'deal_workbench', id: 'managerDealWorkbenchMount', label: 'Сделка под рукой' },
    { key: 'today', id: 'dashboardTodayMount', label: 'Мои дела и сигналы' },
    { key: 'quick_access', id: 'dashboardQuickAccessMount', label: 'Избранное, последние и подписки' },
    { key: 'quick_start', id: 'dashboardWorkbenchStrip', label: 'Быстрые подсказки и действия' },
];
const WORKSPACE_DEFAULT_SIDEBAR_GROUP_ORDER = ['main', 'crm', 'docflow', 'finance', 'operations', 'directories', 'analytics'];
const WORKSPACE_SHORTCUT_DEFS = {
    commandPalette: {
        label: 'Командная палитра',
        description: 'Быстрые команды, переходы и создание записей',
        defaults: {
            mac: { ctrl: false, meta: true, alt: false, shift: false, key: 'k' },
            windows: { ctrl: true, meta: false, alt: false, shift: false, key: 'k' },
        },
    },
    globalSearch: {
        label: 'Глобальный поиск',
        description: 'Фокус в верхнее поле поиска по разделам и записям',
        defaults: {
            mac: { ctrl: false, meta: true, alt: false, shift: true, key: 'f' },
            windows: { ctrl: true, meta: false, alt: false, shift: true, key: 'f' },
        },
    },
    notifications: {
        label: 'Уведомления',
        description: 'Открыть колокольчик и быстро перейти к новым событиям',
        defaults: {
            mac: { ctrl: false, meta: true, alt: false, shift: true, key: 'n' },
            windows: { ctrl: true, meta: false, alt: false, shift: true, key: 'n' },
        },
    },
    newTask: {
        label: 'Создать поручение',
        description: 'Открыть быстрое создание новой задачи',
        defaults: {
            mac: { ctrl: false, meta: true, alt: false, shift: true, key: 't' },
            windows: { ctrl: true, meta: false, alt: false, shift: true, key: 't' },
        },
    },
    newDocument: {
        label: 'Создать документ',
        description: 'Открыть карточку нового входящего или исходящего документа',
        defaults: {
            mac: { ctrl: false, meta: true, alt: false, shift: true, key: 'd' },
            windows: { ctrl: true, meta: false, alt: false, shift: true, key: 'd' },
        },
    },
    qrScanner: {
        label: 'QR-сканер',
        description: 'Открыть сканирование QR без перехода по меню',
        defaults: {
            mac: { ctrl: false, meta: true, alt: false, shift: true, key: 'q' },
            windows: { ctrl: true, meta: false, alt: false, shift: true, key: 'q' },
        },
    },
};

let workspaceConfigCache = null;
let workspaceConfigCacheKey = '';

function workspaceConfigStorageKey() {
    const email = String(currentUser?.email || currentUser?.name || 'guest').trim().toLowerCase();
    const role = typeof getRoleSlug === 'function' ? getRoleSlug(currentUser?.role || '') : 'default';
    return `korda_workspace_config:${email}:${role}`;
}

function uniqueWorkspaceList(values = []) {
    return Array.from(new Set((Array.isArray(values) ? values : []).map(value => String(value || '').trim()).filter(Boolean)));
}

function getWorkspaceSidebarMeta() {
    return Array.from(document.querySelectorAll('.nav-group[data-nav-group]')).map(group => ({
        id: String(group.dataset.navGroup || '').trim(),
        label: String(group.querySelector('.nav-label')?.textContent || group.dataset.navGroup || '').trim(),
        itemIds: Array.from(group.querySelectorAll('.nav-item[id]')).map(item => item.id),
    })).filter(group => group.id);
}

function getWorkspaceAllowedNavIds() {
    const roleConfig = typeof getRoleUiConfig === 'function' ? getRoleUiConfig() : { visibleNav: [] };
    return new Set([...(roleConfig.visibleNav || []), 'navProfile']);
}

function detectNativeShortcutPlatform() {
    return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || '') ? 'mac' : 'windows';
}

function sanitizeWorkspacePlatformPreference(value) {
    const normalized = String(value || '').trim().toLowerCase();
    return ['auto', 'mac', 'windows'].includes(normalized) ? normalized : 'auto';
}

function resolveWorkspaceShortcutPlatform(preference = '') {
    const normalized = sanitizeWorkspacePlatformPreference(preference);
    if (normalized === 'mac' || normalized === 'windows') return normalized;
    return detectNativeShortcutPlatform();
}

function normalizeWorkspaceShortcut(rawShortcut = null, fallbackShortcut = {}) {
    const shortcut = rawShortcut && typeof rawShortcut === 'object' ? rawShortcut : {};
    const fallback = fallbackShortcut && typeof fallbackShortcut === 'object' ? fallbackShortcut : {};
    const rawKey = String(shortcut.key ?? fallback.key ?? '').trim();
    const key = rawKey.length ? rawKey.slice(0, 1).toLowerCase() : 'k';
    return {
        ctrl: Boolean(shortcut.ctrl ?? fallback.ctrl ?? false),
        meta: Boolean(shortcut.meta ?? fallback.meta ?? false),
        alt: Boolean(shortcut.alt ?? fallback.alt ?? false),
        shift: Boolean(shortcut.shift ?? fallback.shift ?? false),
        key,
    };
}

function getWorkspaceDefaultShortcuts(platform = detectNativeShortcutPlatform()) {
    const resolvedPlatform = resolveWorkspaceShortcutPlatform(platform);
    return Object.fromEntries(Object.entries(WORKSPACE_SHORTCUT_DEFS).map(([actionKey, definition]) => [
        actionKey,
        normalizeWorkspaceShortcut(definition.defaults?.[resolvedPlatform], definition.defaults?.windows),
    ]));
}

function shortcutLabelParts(shortcut = {}, platform = detectNativeShortcutPlatform()) {
    const parts = [];
    if (shortcut.ctrl) parts.push('Ctrl');
    if (shortcut.meta) parts.push(platform === 'mac' ? '⌘' : 'Win');
    if (shortcut.alt) parts.push(platform === 'mac' ? 'Option' : 'Alt');
    if (shortcut.shift) parts.push('Shift');
    const key = String(shortcut.key || '').trim();
    if (key) parts.push(key === ' ' ? 'Space' : key.toUpperCase());
    return parts;
}

function formatWorkspaceShortcutLabel(shortcut = {}, platform = detectNativeShortcutPlatform()) {
    const parts = shortcutLabelParts(shortcut, platform);
    return parts.length ? parts.join(' + ') : 'Не задано';
}

function getWorkspaceShortcutConfig(actionKey, config = null) {
    const definition = WORKSPACE_SHORTCUT_DEFS[actionKey];
    if (!definition) return normalizeWorkspaceShortcut({});
    const source = config && typeof config === 'object' ? config : loadWorkspaceConfig();
    const platform = resolveWorkspaceShortcutPlatform(source?.platformPreference);
    return normalizeWorkspaceShortcut(source?.shortcuts?.[actionKey], definition.defaults?.[platform] || definition.defaults?.windows);
}

function getWorkspaceDefaultConfig() {
    const sidebarMeta = getWorkspaceSidebarMeta();
    const sidebarGroupOrder = WORKSPACE_DEFAULT_SIDEBAR_GROUP_ORDER.filter(id => sidebarMeta.some(group => group.id === id));
    sidebarMeta.forEach(group => {
        if (!sidebarGroupOrder.includes(group.id)) sidebarGroupOrder.push(group.id);
    });
    return {
        version: 2,
        sidebarGroupOrder,
        hiddenGroups: [],
        hiddenNavItems: [],
        dashboardBlockOrder: WORKSPACE_DASHBOARD_BLOCKS.map(block => block.key),
        hiddenDashboardBlocks: [],
        platformPreference: 'auto',
        shortcutOrder: Object.keys(WORKSPACE_SHORTCUT_DEFS),
        shortcuts: getWorkspaceDefaultShortcuts(),
    };
}

function normalizeWorkspaceConfig(rawConfig = null) {
    const defaults = getWorkspaceDefaultConfig();
    const next = rawConfig && typeof rawConfig === 'object' ? rawConfig : {};
    const groupIds = defaults.sidebarGroupOrder;
    const dashboardKeys = defaults.dashboardBlockOrder;
    const sidebarGroupOrder = uniqueWorkspaceList(next.sidebarGroupOrder).filter(id => groupIds.includes(id));
    groupIds.forEach(id => {
        if (!sidebarGroupOrder.includes(id)) sidebarGroupOrder.push(id);
    });
    const dashboardBlockOrder = uniqueWorkspaceList(next.dashboardBlockOrder).filter(key => dashboardKeys.includes(key));
    dashboardKeys.forEach(key => {
        if (!dashboardBlockOrder.includes(key)) dashboardBlockOrder.push(key);
    });
    const allNavItemIds = uniqueWorkspaceList(getWorkspaceSidebarMeta().flatMap(group => group.itemIds));
    const platformPreference = sanitizeWorkspacePlatformPreference(next.platformPreference || defaults.platformPreference);
    const shortcutKeys = Object.keys(WORKSPACE_SHORTCUT_DEFS);
    const shortcutOrder = uniqueWorkspaceList(next.shortcutOrder).filter(key => shortcutKeys.includes(key));
    shortcutKeys.forEach(key => {
        if (!shortcutOrder.includes(key)) shortcutOrder.push(key);
    });
    const shortcuts = {};
    shortcutKeys.forEach(actionKey => {
        shortcuts[actionKey] = getWorkspaceShortcutConfig(actionKey, {
            ...defaults,
            platformPreference,
            shortcuts: next.shortcuts || {},
        });
    });
    return {
        version: 3,
        sidebarGroupOrder,
        hiddenGroups: uniqueWorkspaceList(next.hiddenGroups).filter(id => groupIds.includes(id)),
        hiddenNavItems: uniqueWorkspaceList(next.hiddenNavItems).filter(id => allNavItemIds.includes(id)),
        dashboardBlockOrder,
        hiddenDashboardBlocks: uniqueWorkspaceList(next.hiddenDashboardBlocks).filter(key => dashboardKeys.includes(key)),
        platformPreference,
        shortcutOrder,
        shortcuts,
    };
}

function loadWorkspaceConfig() {
    const storageKey = workspaceConfigStorageKey();
    if (workspaceConfigCache && workspaceConfigCacheKey === storageKey) return workspaceConfigCache;
    let raw = null;
    try {
        raw = JSON.parse(localStorage.getItem(storageKey) || 'null');
    } catch (_) {
        raw = null;
    }
    workspaceConfigCache = normalizeWorkspaceConfig(raw);
    workspaceConfigCacheKey = storageKey;
    return workspaceConfigCache;
}

function saveWorkspaceConfig(nextConfig) {
    const normalized = normalizeWorkspaceConfig(nextConfig);
    const storageKey = workspaceConfigStorageKey();
    localStorage.setItem(storageKey, JSON.stringify(normalized));
    workspaceConfigCache = normalized;
    workspaceConfigCacheKey = storageKey;
    return normalized;
}

function moveWorkspaceEntry(list = [], id, direction = 0) {
    const idx = list.indexOf(id);
    if (idx < 0) return list;
    const nextIdx = idx + Number(direction || 0);
    if (nextIdx < 0 || nextIdx >= list.length) return list;
    const clone = [...list];
    [clone[idx], clone[nextIdx]] = [clone[nextIdx], clone[idx]];
    return clone;
}

function workspaceEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function workspaceStateLabel(isVisible) {
    return isVisible ? 'Показан' : 'Скрыт';
}

function workspaceShortcutRead(prefix) {
    const keyValue = String(document.getElementById(`${prefix}key`)?.value || '').trim();
    return {
        ctrl: Boolean(document.getElementById(`${prefix}ctrl`)?.checked),
        meta: Boolean(document.getElementById(`${prefix}meta`)?.checked),
        alt: Boolean(document.getElementById(`${prefix}alt`)?.checked),
        shift: Boolean(document.getElementById(`${prefix}shift`)?.checked),
        key: keyValue ? keyValue.slice(0, 1).toLowerCase() : '',
    };
}

function workspaceShortcutSignature(shortcut = {}) {
    return [
        shortcut.ctrl ? 'ctrl' : '',
        shortcut.meta ? 'meta' : '',
        shortcut.alt ? 'alt' : '',
        shortcut.shift ? 'shift' : '',
        String(shortcut.key || '').trim().toLowerCase(),
    ].filter(Boolean).join('+');
}

function findWorkspaceShortcutConflict(actionKey, shortcut, config = loadWorkspaceConfig()) {
    const defs = window.WORKSPACE_SHORTCUT_DEFS || {};
    const signature = workspaceShortcutSignature(shortcut);
    if (!signature) return null;
    return Object.keys(defs).find(otherActionKey => {
        if (otherActionKey === actionKey) return false;
        return workspaceShortcutSignature(getWorkspaceShortcutConfig(otherActionKey, config)) === signature;
    }) || null;
}

function renderWorkspaceShortcutSection(config = loadWorkspaceConfig()) {
    const preference = String(config?.platformPreference || 'auto');
    const resolvedPlatform = resolveWorkspaceShortcutPlatform(preference);
    const defs = window.WORKSPACE_SHORTCUT_DEFS || {};
    const shortcutOrder = Array.isArray(config?.shortcutOrder) && config.shortcutOrder.length
        ? config.shortcutOrder.filter(actionKey => defs[actionKey])
        : Object.keys(defs);
    const actionOptions = Object.entries(defs).map(([optionKey, optionDefinition]) => ({
        key: optionKey,
        label: optionDefinition.label || optionKey,
    }));
    const rows = shortcutOrder.map((actionKey, slotIndex) => {
        const definition = defs[actionKey];
        const shortcut = getWorkspaceShortcutConfig(actionKey, config);
        const preview = formatWorkspaceShortcutLabel(shortcut, resolvedPlatform);
        const slotLabel = `Сочетание ${slotIndex + 1}`;
        const prefix = `workspaceShortcut_slot${slotIndex}_`;
        const optionsHtml = actionOptions.map(option => `
            <option value="${workspaceEscape(option.key)}" ${option.key === actionKey ? 'selected' : ''}>${workspaceEscape(option.label)}</option>
        `).join('');
        return `
            <div class="profile-shortcut-row">
                <div class="profile-shortcut-copy">
                    <div class="profile-shortcut-head">
                        <div>
                            <div class="profile-shortcut-keylabel">${workspaceEscape(slotLabel)}</div>
                            <div class="profile-shortcut-title">Действие сочетания</div>
                        </div>
                        <span class="profile-shortcut-preview">${workspaceEscape(preview)}</span>
                    </div>
                    <div class="profile-shortcut-actionwrap">
                        <span class="profile-shortcut-keylabel">Что делает сочетание</span>
                        <select id="${prefix}action" class="auth-input profile-shortcut-action" onchange="changeWorkspaceShortcutAction(${slotIndex}, this.value)">
                            ${optionsHtml}
                        </select>
                    </div>
                    <div class="profile-shortcut-text">
                        <strong>${workspaceEscape(definition.label || actionKey)}</strong>.<br>
                        Сначала выбери действие, потом выставь модификаторы и клавишу. ${workspaceEscape(definition.description || '')}
                    </div>
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
                    <div class="profile-shortcut-keywrap">
                        <span class="profile-shortcut-keylabel">Клавиша</span>
                        <input id="${prefix}key" class="auth-input profile-shortcut-key" type="text" maxlength="1" value="${workspaceEscape(shortcut.key || '')}" placeholder="K">
                    </div>
                    <div class="profile-shortcut-actions">
                        <button class="btn-primary" type="button" onclick="saveWorkspaceShortcutSlot(${slotIndex})">Сохранить</button>
                        <button class="btn-secondary" type="button" onclick="resetWorkspaceShortcutSlot(${slotIndex})">По умолчанию</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    return `
        <section class="workspace-config-section">
            <div class="workspace-config-section-head">
                <div>
                    <div class="workspace-config-eyebrow">Горячие клавиши</div>
                    <h3 class="workspace-config-title">Командная палитра и поиск</h3>
                    <p class="workspace-config-text">Выбери платформу, затем задай каждой комбинации конкретное действие. Конфиг меняется сразу для текущего пользователя.</p>
                </div>
                <div class="workspace-config-header-actions">
                    <select id="workspaceConfigPlatformPreference" class="auth-input" onchange="saveWorkspacePlatformPreference(this.value); renderWorkspaceConfigModal(); if (typeof updateCommandPaletteShortcutHints === 'function') updateCommandPaletteShortcutHints();">
                        <option value="auto" ${preference === 'auto' ? 'selected' : ''}>Автоопределение</option>
                        <option value="windows" ${preference === 'windows' ? 'selected' : ''}>Windows / Ctrl</option>
                        <option value="mac" ${preference === 'mac' ? 'selected' : ''}>macOS / Command</option>
                    </select>
                    <span class="ops-section-chip ops-section-chip--primary">${resolvedPlatform === 'mac' ? 'macOS' : 'Windows/PC'}</span>
                </div>
            </div>
            <div class="workspace-config-stack">
                <div class="profile-shortcut-grid">${rows}</div>
            </div>
        </section>
    `;
}

function applySidebarWorkspaceConfig() {
    const sidebar = document.querySelector('.krd-shell-sidebar, .sidebar');
    if (!sidebar) return;
    const config = loadWorkspaceConfig();
    const allowedNavIds = getWorkspaceAllowedNavIds();
    const footer = sidebar.querySelector('.krd-shell-sidebar__footer');
    const hiddenGroups = new Set(config.hiddenGroups || []);
    const hiddenNavItems = new Set(config.hiddenNavItems || []);
    const sidebarMeta = getWorkspaceSidebarMeta();

    config.sidebarGroupOrder.forEach(groupId => {
        const groupEl = sidebar.querySelector(`.nav-group[data-nav-group="${groupId}"]`);
        if (groupEl && footer) sidebar.insertBefore(groupEl, footer);
    });

    sidebarMeta.forEach(group => {
        const groupEl = sidebar.querySelector(`.nav-group[data-nav-group="${group.id}"]`);
        if (!groupEl) return;
        let visibleCount = 0;
        group.itemIds.forEach(itemId => {
            const itemEl = document.getElementById(itemId);
            if (!itemEl) return;
            const visible = allowedNavIds.has(itemId) && !hiddenGroups.has(group.id) && !hiddenNavItems.has(itemId);
            itemEl.style.display = visible ? 'flex' : 'none';
            if (visible) visibleCount += 1;
        });
        groupEl.style.display = hiddenGroups.has(group.id) || visibleCount === 0 ? 'none' : '';
    });
}

function applyDashboardWorkspaceConfig() {
    const dashboardView = document.getElementById('dashboardView');
    if (!dashboardView) return;
    const toolbar = dashboardView.querySelector('.dashboard-toolbar');
    if (!toolbar) return;
    const config = loadWorkspaceConfig();
    const hiddenBlocks = new Set(config.hiddenDashboardBlocks || []);

    config.dashboardBlockOrder.forEach(key => {
        const def = WORKSPACE_DASHBOARD_BLOCKS.find(item => item.key === key);
        const blockEl = def ? document.getElementById(def.id) : null;
        if (blockEl) dashboardView.insertBefore(blockEl, toolbar);
    });

    WORKSPACE_DASHBOARD_BLOCKS.forEach(block => {
        const blockEl = document.getElementById(block.id);
        if (!blockEl) return;
        blockEl.style.display = hiddenBlocks.has(block.key) ? 'none' : '';
    });
}

function applyWorkspaceConfig() {
    if (!currentUser || currentUser.status !== 'approved') return;
    applySidebarWorkspaceConfig();
    applyDashboardWorkspaceConfig();
}

function renderWorkspaceConfigModal() {
    const modal = document.getElementById('workspaceConfigModal');
    const body = document.getElementById('workspaceConfigBody');
    if (!modal || !body || !currentUser || currentUser.status !== 'approved') return;

    const config = loadWorkspaceConfig();
    const allowedNavIds = getWorkspaceAllowedNavIds();
    const sidebarGroups = getWorkspaceSidebarMeta()
        .filter(group => group.itemIds.some(itemId => allowedNavIds.has(itemId)))
        .sort((a, b) => config.sidebarGroupOrder.indexOf(a.id) - config.sidebarGroupOrder.indexOf(b.id));

    const sidebarHtml = sidebarGroups.map((group, index) => {
        const items = group.itemIds
            .filter(itemId => allowedNavIds.has(itemId))
            .map(itemId => {
                const itemEl = document.getElementById(itemId);
                const label = String(itemEl?.textContent || itemId).trim();
                const checked = !config.hiddenNavItems.includes(itemId);
                return `
                    <label class="workspace-config-item">
                        <input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleWorkspaceNavItem('${workspaceEscape(itemId)}')">
                        <span class="workspace-config-check" aria-hidden="true"></span>
                        <span class="workspace-config-label-wrap">
                            <span class="workspace-config-label">${workspaceEscape(label)}</span>
                            <span class="workspace-config-state">${workspaceStateLabel(checked)}</span>
                        </span>
                    </label>
                `;
            }).join('');
        const checked = !config.hiddenGroups.includes(group.id);
        return `
            <div class="workspace-config-card">
                <div class="workspace-config-card-head">
                    <label class="workspace-config-switch">
                        <input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleWorkspaceGroup('${workspaceEscape(group.id)}')">
                        <span class="workspace-config-check" aria-hidden="true"></span>
                        <span class="workspace-config-label-wrap">
                            <span class="workspace-config-label">${workspaceEscape(group.label)}</span>
                            <span class="workspace-config-state">${workspaceStateLabel(checked)}</span>
                        </span>
                    </label>
                    <div class="workspace-config-move">
                        <button class="btn-secondary" ${index === 0 ? 'disabled' : ''} onclick="moveWorkspaceGroup('${workspaceEscape(group.id)}', -1)">↑</button>
                        <button class="btn-secondary" ${index === sidebarGroups.length - 1 ? 'disabled' : ''} onclick="moveWorkspaceGroup('${workspaceEscape(group.id)}', 1)">↓</button>
                    </div>
                </div>
                <div class="workspace-config-list">${items}</div>
            </div>
        `;
    }).join('');

    const dashboardBlocks = WORKSPACE_DASHBOARD_BLOCKS
        .filter(block => document.getElementById(block.id))
        .sort((a, b) => config.dashboardBlockOrder.indexOf(a.key) - config.dashboardBlockOrder.indexOf(b.key));

    const dashboardHtml = dashboardBlocks.map((block, index) => {
        const checked = !config.hiddenDashboardBlocks.includes(block.key);
        return `
            <div class="workspace-config-row">
                <label class="workspace-config-switch">
                    <input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleWorkspaceDashboardBlock('${workspaceEscape(block.key)}')">
                    <span class="workspace-config-check" aria-hidden="true"></span>
                    <span class="workspace-config-label-wrap">
                        <span class="workspace-config-label">${workspaceEscape(block.label)}</span>
                        <span class="workspace-config-state">${workspaceStateLabel(checked)}</span>
                    </span>
                </label>
                <div class="workspace-config-move">
                    <button class="btn-secondary" ${index === 0 ? 'disabled' : ''} onclick="moveWorkspaceDashboardBlock('${workspaceEscape(block.key)}', -1)">↑</button>
                    <button class="btn-secondary" ${index === dashboardBlocks.length - 1 ? 'disabled' : ''} onclick="moveWorkspaceDashboardBlock('${workspaceEscape(block.key)}', 1)">↓</button>
                </div>
            </div>
        `;
    }).join('');

    body.innerHTML = `
        <div class="workspace-config-grid">
            <section class="workspace-config-section">
                <div class="workspace-config-section-head">
                    <div>
                        <div class="workspace-config-eyebrow">Левая навигация</div>
                        <h3 class="workspace-config-title">Категории и разделы</h3>
                        <p class="workspace-config-text">Скрывай лишние разделы для своей роли и меняй порядок категорий в меню.</p>
                    </div>
                </div>
                <div class="workspace-config-stack">${sidebarHtml || '<div class="empty-state">Для этой роли нет настраиваемых категорий.</div>'}</div>
            </section>
            <section class="workspace-config-section">
                <div class="workspace-config-section-head">
                    <div>
                        <div class="workspace-config-eyebrow">Дашборд</div>
                        <h3 class="workspace-config-title">Порядок блоков</h3>
                        <p class="workspace-config-text">Определи, какие блоки нужны на первом экране и в каком порядке их показывать.</p>
                    </div>
                </div>
                <div class="workspace-config-stack">${dashboardHtml || '<div class="empty-state">Блоки дашборда пока недоступны для настройки.</div>'}</div>
            </section>
        </div>
        ${renderWorkspaceShortcutSection(config)}
        <div class="workspace-config-note">Личный кабинет и служебные зоны остаются закреплены. Конфиг сохраняется отдельно для каждого пользователя и роли.</div>
    `;
}

function mutateWorkspaceConfig(mutator) {
    const draft = JSON.parse(JSON.stringify(loadWorkspaceConfig()));
    mutator(draft);
    saveWorkspaceConfig(draft);
    applyWorkspaceConfig();
    renderWorkspaceConfigModal();
}

function openWorkspaceConfigModal() {
    const modal = document.getElementById('workspaceConfigModal');
    if (!modal) return;
    renderWorkspaceConfigModal();
    document.body.classList.add('workspace-config-open');
    modal.style.display = 'flex';
}

function closeWorkspaceConfigModal() {
    const modal = document.getElementById('workspaceConfigModal');
    if (modal) modal.style.display = 'none';
    document.body.classList.remove('workspace-config-open');
}

function toggleWorkspaceGroup(groupId) {
    mutateWorkspaceConfig(config => {
        const hidden = new Set(config.hiddenGroups || []);
        if (hidden.has(groupId)) hidden.delete(groupId);
        else hidden.add(groupId);
        config.hiddenGroups = Array.from(hidden);
    });
}

function moveWorkspaceGroup(groupId, direction) {
    mutateWorkspaceConfig(config => {
        config.sidebarGroupOrder = moveWorkspaceEntry(config.sidebarGroupOrder, groupId, direction);
    });
}

function toggleWorkspaceNavItem(itemId) {
    mutateWorkspaceConfig(config => {
        const hidden = new Set(config.hiddenNavItems || []);
        if (hidden.has(itemId)) hidden.delete(itemId);
        else hidden.add(itemId);
        config.hiddenNavItems = Array.from(hidden);
    });
}

function toggleWorkspaceDashboardBlock(blockKey) {
    mutateWorkspaceConfig(config => {
        const hidden = new Set(config.hiddenDashboardBlocks || []);
        if (hidden.has(blockKey)) hidden.delete(blockKey);
        else hidden.add(blockKey);
        config.hiddenDashboardBlocks = Array.from(hidden);
    });
}

function moveWorkspaceDashboardBlock(blockKey, direction) {
    mutateWorkspaceConfig(config => {
        config.dashboardBlockOrder = moveWorkspaceEntry(config.dashboardBlockOrder, blockKey, direction);
    });
}

function saveWorkspacePlatformPreference(value) {
    mutateWorkspaceConfig(config => {
        config.platformPreference = sanitizeWorkspacePlatformPreference(value);
    });
    return loadWorkspaceConfig();
}

function saveWorkspaceShortcutConfig(actionKey, nextShortcut) {
    if (!WORKSPACE_SHORTCUT_DEFS[actionKey]) return loadWorkspaceConfig();
    mutateWorkspaceConfig(config => {
        config.shortcuts = config.shortcuts || {};
        config.shortcuts[actionKey] = normalizeWorkspaceShortcut(
            nextShortcut,
            WORKSPACE_SHORTCUT_DEFS[actionKey].defaults?.[resolveWorkspaceShortcutPlatform(config.platformPreference)] || {}
        );
    });
    return loadWorkspaceConfig();
}

function saveWorkspaceShortcutOrder(nextOrder = []) {
    mutateWorkspaceConfig(config => {
        const shortcutKeys = Object.keys(WORKSPACE_SHORTCUT_DEFS);
        const normalized = uniqueWorkspaceList(nextOrder).filter(key => shortcutKeys.includes(key));
        shortcutKeys.forEach(key => {
            if (!normalized.includes(key)) normalized.push(key);
        });
        config.shortcutOrder = normalized;
    });
    return loadWorkspaceConfig();
}

function resetWorkspaceShortcutConfig(actionKey) {
    if (!WORKSPACE_SHORTCUT_DEFS[actionKey]) return loadWorkspaceConfig();
    mutateWorkspaceConfig(config => {
        config.shortcuts = config.shortcuts || {};
        delete config.shortcuts[actionKey];
    });
    return loadWorkspaceConfig();
}

function changeWorkspaceShortcutAction(slotIndex, nextActionKey) {
    const defs = window.WORKSPACE_SHORTCUT_DEFS || {};
    if (!defs[nextActionKey]) return;
    const config = loadWorkspaceConfig();
    const fallbackOrder = Object.keys(defs);
    const order = Array.isArray(config?.shortcutOrder) && config.shortcutOrder.length
        ? [...config.shortcutOrder]
        : [...fallbackOrder];
    const currentActionKey = order[slotIndex];
    if (!currentActionKey || currentActionKey === nextActionKey) return;
    const existingIndex = order.indexOf(nextActionKey);
    if (existingIndex >= 0) {
        [order[slotIndex], order[existingIndex]] = [order[existingIndex], order[slotIndex]];
    } else {
        order[slotIndex] = nextActionKey;
    }
    saveWorkspaceShortcutOrder(order);
    renderWorkspaceConfigModal();
    if (typeof updateCommandPaletteShortcutHints === 'function') updateCommandPaletteShortcutHints();
    if (typeof showToast === 'function') showToast('Горячие клавиши', 'Назначение действия обновлено');
}

function saveWorkspaceShortcutSlot(slotIndex) {
    const actionKey = String(document.getElementById(`workspaceShortcut_slot${slotIndex}_action`)?.value || '').trim();
    const shortcut = workspaceShortcutRead(`workspaceShortcut_slot${slotIndex}_`);
    const defs = window.WORKSPACE_SHORTCUT_DEFS || {};
    if (!actionKey) {
        if (typeof customAlert === 'function') customAlert('Выбери действие для сочетания.');
        return;
    }
    if (!shortcut.key) {
        if (typeof customAlert === 'function') customAlert('Укажи клавишу для сочетания.');
        return;
    }
    if (!shortcut.ctrl && !shortcut.meta && !shortcut.alt && !shortcut.shift) {
        if (typeof customAlert === 'function') customAlert('Выбери хотя бы один модификатор: Ctrl, Cmd/Win, Alt или Shift.');
        return;
    }
    const conflictActionKey = findWorkspaceShortcutConflict(actionKey, shortcut);
    if (conflictActionKey) {
        const currentLabel = defs[actionKey]?.label || actionKey;
        const conflictLabel = defs[conflictActionKey]?.label || conflictActionKey;
        if (typeof customAlert === 'function') {
            customAlert(`Сочетание уже занято.\n\n"${currentLabel}" конфликтует с действием "${conflictLabel}".\nВыбери другую комбинацию или сначала сбрось конфликтующее действие.`);
        }
        return;
    }
    saveWorkspaceShortcutConfig(actionKey, shortcut);
    renderWorkspaceConfigModal();
    if (typeof updateCommandPaletteShortcutHints === 'function') updateCommandPaletteShortcutHints();
    if (typeof showToast === 'function') showToast('Горячие клавиши', `Сочетание сохранено для "${defs[actionKey]?.label || actionKey}"`);
}

function resetWorkspaceShortcutSlot(slotIndex) {
    const actionKey = String(document.getElementById(`workspaceShortcut_slot${slotIndex}_action`)?.value || '').trim();
    if (!actionKey) return;
    resetWorkspaceShortcutConfig(actionKey);
    renderWorkspaceConfigModal();
    if (typeof updateCommandPaletteShortcutHints === 'function') updateCommandPaletteShortcutHints();
    if (typeof showToast === 'function') showToast('Горячие клавиши', 'Сочетание сброшено');
}

async function resetWorkspaceConfig() {
    const shouldReset = typeof customConfirm === 'function'
        ? await customConfirm('Сбросить персональную конфигурацию интерфейса и вернуть порядок по умолчанию?')
        : true;
    if (!shouldReset) return;
    const storageKey = workspaceConfigStorageKey();
    localStorage.removeItem(storageKey);
    workspaceConfigCache = null;
    workspaceConfigCacheKey = '';
    if (typeof applyRoleShell === 'function') applyRoleShell();
    if (typeof renderDashboard === 'function') renderDashboard();
    renderWorkspaceConfigModal();
    if (typeof showToast === 'function') showToast('Конфиг интерфейса', 'Настройки возвращены к состоянию по умолчанию');
}

window.loadWorkspaceConfig = loadWorkspaceConfig;
window.applyWorkspaceConfig = applyWorkspaceConfig;
window.applyDashboardWorkspaceConfig = applyDashboardWorkspaceConfig;
window.openWorkspaceConfigModal = openWorkspaceConfigModal;
window.closeWorkspaceConfigModal = closeWorkspaceConfigModal;
window.toggleWorkspaceGroup = toggleWorkspaceGroup;
window.moveWorkspaceGroup = moveWorkspaceGroup;
window.toggleWorkspaceNavItem = toggleWorkspaceNavItem;
window.toggleWorkspaceDashboardBlock = toggleWorkspaceDashboardBlock;
window.moveWorkspaceDashboardBlock = moveWorkspaceDashboardBlock;
window.resetWorkspaceConfig = resetWorkspaceConfig;
window.WORKSPACE_SHORTCUT_DEFS = WORKSPACE_SHORTCUT_DEFS;
window.detectNativeShortcutPlatform = detectNativeShortcutPlatform;
window.resolveWorkspaceShortcutPlatform = resolveWorkspaceShortcutPlatform;
window.getWorkspaceShortcutConfig = getWorkspaceShortcutConfig;
window.formatWorkspaceShortcutLabel = formatWorkspaceShortcutLabel;
window.shortcutLabelParts = shortcutLabelParts;
window.saveWorkspacePlatformPreference = saveWorkspacePlatformPreference;
window.saveWorkspaceShortcutConfig = saveWorkspaceShortcutConfig;
window.saveWorkspaceShortcutOrder = saveWorkspaceShortcutOrder;
window.resetWorkspaceShortcutConfig = resetWorkspaceShortcutConfig;
window.changeWorkspaceShortcutAction = changeWorkspaceShortcutAction;
window.saveWorkspaceShortcutSlot = saveWorkspaceShortcutSlot;
window.resetWorkspaceShortcutSlot = resetWorkspaceShortcutSlot;
