window.API_URL = window.API_URL || '/api';
const API_URL = window.API_URL;
let currentUser = null;
let projectsDB = [];
let clientsDB = [];
let allUsersDB = []; 
let meetingsDB = []; 
let calendarEventsDB = [];
let emailsDB = [];   
let emailAccountsDB = [];
let documentsDB = []; 
let documentPackagesDB = [];
let tasksDB = [];      
let knowledgeDB = [];  
let approvalsDB = []; 
let workflowDefinitionsDB = [];
let workflowInstancesDB = [];
let claimsDB = [];
let courtCasesDB = [];
let crmLeadsDB = [];
let crmDealsDB = [];
let auditLogsDB = [];
let notificationsDB = [];
let currentPermissions = {};
window.currentPermissionMeta = window.currentPermissionMeta || { field_permissions: [], field_policy_map: {}, scope: { legal_entities: [], business_units: [] }, two_factor_enabled: 0 };

let currentTab = 'active';
let currentProjectId = null;
let currentLegalTab = 'claims';
let statusChartObj = null;
let progressChartObj = null;
let currentDepartmentFilter = null; 
let viewMode = localStorage.getItem('korda_view_mode') || 'list'; 
let isChatVisible = localStorage.getItem('korda_chat_visible') !== 'false'; 

let isFirstLoad = true;
let seenToastIds = new Set();
let canvas, ctx, isDrawing = false;
window.__formPolicyCache = window.__formPolicyCache || {};

const availableRoles = ['Конструкторское бюро', 'Производство и ОТК', 'Склад', 'Менеджер', 'Бухгалтерия', 'Юрист', 'Секретарь / Канцелярия', 'Сотрудник', 'Директор'];

window.exchangeRates = { RUB: 1, USD: 90, EUR: 100, CNY: 12 };

function permissionRulesFor(module, entityType) {
    const policyMap = window.currentPermissionMeta?.field_policy_map || {};
    const directMap = policyMap?.[module || '']?.[entityType || ''];
    if (directMap && typeof directMap === 'object') {
        return Object.entries(directMap).map(([field_name, meta]) => ({
            module,
            entity_type: entityType,
            field_name,
            ...meta
        }));
    }
    const rules = Array.isArray(window.currentPermissionMeta?.field_permissions)
        ? window.currentPermissionMeta.field_permissions
        : [];
    return rules.filter(rule =>
        (rule.module || '') === (module || '')
        && (rule.entity_type || '') === (entityType || '')
        && Number(rule.is_active || 0) === 1
    );
}

function getFieldPermissionRule(module, entityType, fieldName) {
    return permissionRulesFor(module, entityType).find(rule => (rule.field_name || '') === (fieldName || '')) || null;
}

function canViewField(module, entityType, fieldName) {
    const rule = getFieldPermissionRule(module, entityType, fieldName);
    if (!rule) return true;
    return Number(rule.can_view || 0) === 1;
}

function canEditField(module, entityType, fieldName) {
    const rule = getFieldPermissionRule(module, entityType, fieldName);
    if (!rule) return true;
    return Number(rule.can_edit || 0) === 1;
}

function allowedFieldStatuses(module, entityType, fieldName = 'status') {
    const rule = getFieldPermissionRule(module, entityType, fieldName);
    return Array.isArray(rule?.allowed_statuses) ? rule.allowed_statuses.map(String).filter(Boolean) : [];
}

function findFieldWrapper(el) {
    if (!el || !el.parentElement) return null;
    return el.closest('.field-permission-wrapper')
        || el.closest('.form-field')
        || el.closest('.input-group')
        || el.closest('label')
        || el;
}

function setFieldVisibility(el, visible) {
    const wrapper = findFieldWrapper(el);
    if (wrapper) wrapper.style.display = visible ? '' : 'none';
    else el.style.display = visible ? '' : 'none';
}

function setFieldReadOnly(el, disabled) {
    if (!el) return;
    if ('disabled' in el) el.disabled = !!disabled;
    if ('readOnly' in el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
        el.readOnly = !!disabled;
    }
    el.dataset.permissionReadonly = disabled ? '1' : '0';
    if (disabled) {
        el.classList.add('is-readonly-field');
        if (!el.title) el.title = 'Поле доступно только для просмотра';
    } else {
        el.classList.remove('is-readonly-field');
        if (el.title === 'Поле доступно только для просмотра') el.title = '';
    }
}

function upsertFieldPermissionNote(el, message) {
    const wrapper = findFieldWrapper(el);
    if (!wrapper || wrapper === el) return;
    let note = wrapper.querySelector('.field-permission-note');
    if (!message) {
        if (note) note.remove();
        return;
    }
    if (!note) {
        note = document.createElement('div');
        note.className = 'field-permission-note';
        wrapper.appendChild(note);
    }
    note.innerText = message;
}

function buildFieldPermissionMessage(module, entityType, fieldName, canEdit, statuses = []) {
    const rule = getFieldPermissionRule(module, entityType, fieldName);
    if (!rule) return '';
    const parts = [];
    if (!canEdit) parts.push('Поле доступно только для просмотра');
    if (Array.isArray(statuses) && statuses.length) {
        parts.push(`Разрешённые статусы: ${statuses.join(', ')}`);
    }
    return parts.join('. ');
}

function applyStatusRestrictions(el, statuses = []) {
    if (!el || el.tagName !== 'SELECT') return;
    const allowed = new Set((statuses || []).map(String));
    Array.from(el.options).forEach(option => {
        option.hidden = allowed.size > 0 && !allowed.has(option.value);
        option.disabled = allowed.size > 0 && !allowed.has(option.value);
    });
    if (allowed.size > 0 && !allowed.has(el.value)) {
        const fallback = Array.from(el.options).find(option => !option.disabled && !option.hidden);
        if (fallback) el.value = fallback.value;
    }
}

function applyFieldPermissionsToForm(module, entityType, fieldMap = {}) {
    Object.entries(fieldMap).forEach(([fieldName, target]) => {
        const config = typeof target === 'string' ? { id: target } : (target || {});
        const el = document.getElementById(config.id);
        if (!el) return;
        const canView = canViewField(module, entityType, fieldName);
        const canEdit = canEditField(module, entityType, fieldName);
        const statuses = (config.statusField || fieldName === 'status' || fieldName === 'payment_status' || fieldName === 'sent_status' || fieldName === 'stage')
            ? allowedFieldStatuses(module, entityType, fieldName)
            : [];
        setFieldVisibility(el, canView);
        if (!canView) {
            upsertFieldPermissionNote(el, '');
            return;
        }
        setFieldReadOnly(el, !canEdit);
        if (config.statusField || fieldName === 'status' || fieldName === 'payment_status' || fieldName === 'sent_status' || fieldName === 'stage') {
            applyStatusRestrictions(el, statuses);
        }
        const message = buildFieldPermissionMessage(module, entityType, fieldName, canEdit, statuses);
        upsertFieldPermissionNote(el, message);
        if (message) el.title = message;
    });
}

window.getFieldPermissionRule = getFieldPermissionRule;
window.canViewField = canViewField;
window.canEditField = canEditField;
window.allowedFieldStatuses = allowedFieldStatuses;
window.applyFieldPermissionsToForm = applyFieldPermissionsToForm;

function resolveFormRoot(formRootIdOrEl) {
    if (!formRootIdOrEl) return document;
    if (typeof formRootIdOrEl === 'string') return document.getElementById(formRootIdOrEl) || document;
    return formRootIdOrEl;
}

function clearSingleFormError(fieldName, formRootIdOrEl) {
    if (!fieldName) return;
    const root = resolveFormRoot(formRootIdOrEl);
    const selector = `[data-field="${fieldName}"]`;
    const errorSelector = `[data-error-for="${fieldName}"]`;
    const input = root.querySelector(selector) || document.querySelector(selector);
    const error = root.querySelector(errorSelector) || document.querySelector(errorSelector);
    if (input) {
        input.classList.remove('is-invalid');
        input.removeAttribute('aria-invalid');
    }
    if (error) {
        error.textContent = '';
        error.classList.remove('is-hint', 'is-warning', 'is-error');
    }
}

window.clearFormErrors = function(formRootIdOrEl) {
    const root = resolveFormRoot(formRootIdOrEl);
    root.querySelectorAll('.is-invalid').forEach(el => {
        el.classList.remove('is-invalid');
        el.removeAttribute('aria-invalid');
    });
    root.querySelectorAll('.form-error').forEach(el => {
        el.textContent = '';
        el.classList.remove('is-hint', 'is-warning', 'is-error');
    });
};

window.showFormErrors = function(errors = [], formRootIdOrEl) {
    const root = resolveFormRoot(formRootIdOrEl);
    errors.forEach(error => {
        const field = error?.field || '';
        const message = error?.message || '';
        if (!field || !message) return;
        const selector = `[data-field="${field}"]`;
        const errorSelector = `[data-error-for="${field}"]`;
        const input = root.querySelector(selector) || document.querySelector(selector);
        const errorNode = root.querySelector(errorSelector) || document.querySelector(errorSelector);
        if (input) {
            input.classList.add('is-invalid');
            input.setAttribute('aria-invalid', 'true');
        }
        if (errorNode) {
            errorNode.textContent = message;
        }
    });
};

window.bindFormFieldErrorCleanup = function(formRootIdOrEl) {
    const root = resolveFormRoot(formRootIdOrEl);
    if (!root || root.dataset.formErrorsBound === '1') return;
    root.dataset.formErrorsBound = '1';
    root.addEventListener('input', event => {
        const field = event.target?.dataset?.field;
        if (field) clearSingleFormError(field, root);
    });
    root.addEventListener('change', event => {
        const field = event.target?.dataset?.field;
        if (field) clearSingleFormError(field, root);
    });
};

window.setSmartFieldHint = function(fieldId, message = '', tone = 'hint', formRootIdOrEl = document) {
    const root = resolveFormRoot(formRootIdOrEl);
    const input = root.querySelector(`[data-field="${fieldId}"]`) || document.getElementById(fieldId);
    const hint = root.querySelector(`[data-error-for="${fieldId}"]`) || document.querySelector(`[data-error-for="${fieldId}"]`);
    if (!hint) return;
    hint.textContent = message || '';
    hint.classList.toggle('is-hint', !!message && tone === 'hint');
    hint.classList.toggle('is-warning', !!message && tone === 'warning');
    hint.classList.toggle('is-error', !!message && tone === 'error');
    if (input) {
        const invalid = !!message && tone === 'error';
        input.classList.toggle('is-invalid', invalid);
        if (invalid) input.setAttribute('aria-invalid', 'true');
        else input.removeAttribute('aria-invalid');
    }
};

window.clearSmartFieldHint = function(fieldId, formRootIdOrEl = document) {
    window.setSmartFieldHint(fieldId, '', 'hint', formRootIdOrEl);
};

window.isValidRuDate = function(value) {
    const raw = String(value || '').trim();
    if (!raw) return true;
    const match = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    if (!match) return false;
    const day = Number(match[1]);
    const month = Number(match[2]);
    const year = Number(match[3]);
    const date = new Date(year, month - 1, day);
    return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
};

window.isValidInnValue = function(value) {
    const digits = String(value || '').replace(/\D/g, '');
    return !digits || digits.length === 10 || digits.length === 12;
};

window.bindSmartFieldHints = function(formRootIdOrEl, rules = []) {
    const root = resolveFormRoot(formRootIdOrEl);
    if (!root || !Array.isArray(rules)) return;
    rules.forEach(rule => {
        const fieldId = rule.field || rule.id;
        const input = root.querySelector(`[data-field="${fieldId}"]`) || document.getElementById(fieldId);
        if (!input || input.dataset.smartHintBound === '1') return;
        input.dataset.smartHintBound = '1';
        const run = () => {
            const result = typeof rule.validate === 'function' ? rule.validate(input.value, input) : null;
            if (!result || !result.message) {
                window.clearSmartFieldHint(fieldId, root);
                return;
            }
            window.setSmartFieldHint(fieldId, result.message, result.tone || 'hint', root);
        };
        input.addEventListener('input', run);
        input.addEventListener('change', run);
        run();
    });
};

function ensureUnifiedFieldHint(input, fieldId, root) {
    if (!input || !fieldId) return null;
    let hint = root.querySelector(`[data-error-for="${fieldId}"]`) || document.querySelector(`[data-error-for="${fieldId}"]`);
    if (hint) return hint;
    hint = document.createElement('div');
    hint.className = 'form-error';
    hint.dataset.errorFor = fieldId;
    const wrapper = input.closest('.form-group, .field, label') || input.parentElement;
    if (wrapper && wrapper !== document.body) wrapper.appendChild(hint);
    else input.insertAdjacentElement('afterend', hint);
    return hint;
}

function unifiedFieldText(input) {
    return [
        input.id,
        input.name,
        input.dataset?.field,
        input.dataset?.validation,
        input.placeholder,
        input.getAttribute('aria-label'),
        input.closest('label')?.textContent,
    ].filter(Boolean).join(' ').toLowerCase();
}

function parseUnifiedNumber(value) {
    const raw = String(value || '').trim().replace(/\s+/g, '').replace(',', '.');
    if (!raw) return null;
    if (!/^-?\d+(\.\d+)?$/.test(raw)) return NaN;
    return Number(raw);
}

function isValidUnifiedDate(value) {
    const raw = String(value || '').trim();
    if (!raw) return true;
    if (window.isValidRuDate(raw)) return true;
    const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return false;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(year, month - 1, day);
    return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
}

function validateUnifiedField(input) {
    if (!input || input.disabled || input.readOnly) return null;
    const value = String(input.value ?? '').trim();
    if (!value) return null;
    const text = unifiedFieldText(input);
    const type = String(input.type || '').toLowerCase();

    if (type === 'email' || /\bemail\b|почт/.test(text)) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? null : { tone: 'error', message: 'Email нужен в формате name@company.ru.' };
    }
    if (/\binn\b|инн/.test(text)) {
        return window.isValidInnValue(value) ? null : { tone: 'error', message: 'ИНН должен быть из 10 или 12 цифр.' };
    }
    if (/\bkpp\b|кпп/.test(text)) {
        return /^\d{9}$/.test(value.replace(/\D/g, '')) ? null : { tone: 'error', message: 'КПП должен быть из 9 цифр.' };
    }
    if (/\bbik\b|бик/.test(text)) {
        return /^\d{9}$/.test(value.replace(/\D/g, '')) ? null : { tone: 'error', message: 'БИК должен быть из 9 цифр.' };
    }
    if (type === 'date' || /\bdate\b|дата|deadline|due|valid_until|finish|start|issued|issue/.test(text)) {
        return isValidUnifiedDate(value) ? null : { tone: 'error', message: 'Дата нужна в формате дд.мм.гггг или гггг-мм-дд.' };
    }
    if (/vat|ндс/.test(text)) {
        const number = parseUnifiedNumber(value);
        if (Number.isNaN(number) || number < 0 || number > 100) return { tone: 'error', message: 'Ставка НДС должна быть числом от 0 до 100.' };
        return { tone: 'hint', message: number === 0 ? 'НДС 0%: проверь основание в документе.' : 'Проверь, сумма введена с НДС или без НДС.' };
    }
    if (/amount|sum|price|cost|qty|quantity|hours|rate|budget|limit|stock|fuel|odometer|progress|percent|сумм|цен|стоим|колич|час|процент|остат/.test(text)) {
        const number = parseUnifiedNumber(value);
        if (Number.isNaN(number)) return { tone: 'error', message: 'Значение должно быть числом. Можно использовать запятую или точку.' };
        if (/amount|sum|price|cost|qty|quantity|сумм|цен|стоим|колич/.test(text) && number <= 0) return { tone: 'error', message: 'Значение должно быть больше нуля.' };
        if (/progress|percent|процент/.test(text) && (number < 0 || number > 100)) return { tone: 'error', message: 'Процент должен быть от 0 до 100.' };
        if (number < 0) return { tone: 'error', message: 'Значение не может быть отрицательным.' };
        return null;
    }
    if (/article|артикул/.test(text) && value.length < 2) {
        return { tone: 'warning', message: 'Артикул слишком короткий. Проверь, что это не черновое значение.' };
    }
    if (/bin|cell|ячейк|складск/.test(text) && /\s/.test(value)) {
        return { tone: 'warning', message: 'В коде складской ячейки обычно не должно быть пробелов.' };
    }
    return null;
}

window.validateUnifiedForm = function(formRootIdOrEl = document) {
    const root = resolveFormRoot(formRootIdOrEl);
    const errors = [];
    root.querySelectorAll('input, select, textarea').forEach(input => {
        const fieldId = input.dataset?.field || input.id || input.name;
        if (!fieldId) return;
        const result = validateUnifiedField(input);
        if (!result || !result.message) {
            window.clearSmartFieldHint(fieldId, root);
            return;
        }
        ensureUnifiedFieldHint(input, fieldId, root);
        window.setSmartFieldHint(fieldId, result.message, result.tone || 'hint', root);
        if ((result.tone || 'hint') === 'error') errors.push({ field: fieldId, message: result.message });
    });
    return { ok: errors.length === 0, errors };
};

window.bindUnifiedFieldValidation = function(formRootIdOrEl = document) {
    const root = resolveFormRoot(formRootIdOrEl);
    if (!root) return;
    root.querySelectorAll('input, select, textarea').forEach(input => {
        const fieldId = input.dataset?.field || input.id || input.name;
        if (!fieldId || input.dataset.unifiedValidationBound === '1') return;
        input.dataset.unifiedValidationBound = '1';
        const run = () => {
            const result = validateUnifiedField(input);
            if (!result || !result.message) {
                window.clearSmartFieldHint(fieldId, root);
                return;
            }
            ensureUnifiedFieldHint(input, fieldId, root);
            window.setSmartFieldHint(fieldId, result.message, result.tone || 'hint', root);
        };
        input.addEventListener('blur', run);
        input.addEventListener('change', run);
        input.addEventListener('input', () => {
            if (input.classList.contains('is-invalid')) run();
        });
    });
};

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => window.bindUnifiedFieldValidation(document), 0);
});

window.__workflowFocusState = window.__workflowFocusState || {};

window.markWorkflowFocus = function(key, id) {
    if (!key || !id) return;
    window.__workflowFocusState[key] = {
        id: Number(id),
        ts: Date.now(),
    };
};

window.isWorkflowFocused = function(key, id, ttlMs = 300000) {
    const state = window.__workflowFocusState?.[key];
    if (!state || !state.id) return false;
    if (Date.now() - Number(state.ts || 0) > ttlMs) return false;
    return Number(state.id) === Number(id);
};

window.clearWorkflowFocus = function(key) {
    if (!key) return;
    delete window.__workflowFocusState[key];
};

window.scrollToWorkflowTarget = function(target, options = {}) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return;
    const behavior = options.behavior || 'smooth';
    const block = options.block || 'start';
    requestAnimationFrame(() => {
        el.scrollIntoView({ behavior, block });
    });
};

window.focusFieldById = function(fieldId, delay = 80) {
    if (!fieldId) return;
    window.setTimeout(() => {
        const el = document.getElementById(fieldId);
        if (!el) return;
        if (typeof el.focus === 'function') el.focus();
        if (typeof el.select === 'function' && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
            el.select();
        }
    }, delay);
};

window.navigateAndFocus = function(viewName, fieldId, delay = 140) {
    if (typeof navigateTo === 'function' && viewName) navigateTo(viewName);
    if (fieldId) window.focusFieldById(fieldId, delay);
};

function normalizeRoleName(roleName = '') {
    return String(roleName || '').trim();
}

function getRoleSlug(roleName = '') {
    const role = normalizeRoleName(roleName);
    if (role === 'Директор') return 'director';
    if (role === 'Менеджер') return 'manager';
    if (role === 'Бухгалтерия') return 'accounting';
    if (role === 'Склад') return 'warehouse';
    if (role === 'Юрист') return 'legal';
    if (role === 'Секретарь / Канцелярия') return 'office';
    if (role === 'Сотрудник') return 'employee';
    if (role === 'Производство и ОТК' || role === 'Конструкторское бюро') return 'production';
    return 'default';
}

function getRoleUiConfig(roleName = '') {
    const role = normalizeRoleName(roleName || currentUser?.role || '');
    const common = {
        showDeptFilters: false,
        searchPlaceholder: 'Глобальный поиск (Сделки, Документы, Поручения)...',
        quickTaskLabel: 'Поручение',
        showScanner: true,
        visibleNav: ['navDashboard', 'navProfile'],
    };
    if (role === 'Директор') {
        return {
            ...common,
            slug: 'director',
            showDeptFilters: true,
            visibleNav: [
                'navDashboard', 'navDocuments', 'navTasks', 'navApprovals', 'navClaims', 'navFinance', 'navAccounting', 'navIntegrations',
                'navSupply', 'navSales', 'navProspecting', 'navLeads', 'navDeals', 'navProduction', 'navRequests', 'navService', 'navExecutive',
                'navOperations', 'navClients', 'navClient360', 'navContract360', 'navKnowledge', 'navMessenger',
                'navEmails', 'navMeetings', 'navNomenclature', 'navContacts', 'navAnalytics',
                'navKpi', 'navProfile', 'adminBtn'
            ],
        };
    }
    if (role === 'Менеджер') {
        return {
            ...common,
            slug: 'manager',
            quickTaskLabel: 'Задача',
            visibleNav: [
                'navDashboard', 'navDocuments', 'navTasks', 'navApprovals', 'navClaims', 'navFinance', 'navIntegrations',
                'navSupply', 'navSales', 'navProspecting', 'navLeads', 'navDeals', 'navExpenses', 'navRequests', 'navResources', 'navService', 'navContract360',
                'navClients', 'navClient360', 'navKnowledge', 'navMessenger', 'navEmails', 'navMeetings', 'navProfile'
            ],
        };
    }
    if (role === 'Бухгалтерия') {
        return {
            ...common,
            slug: 'accounting',
            quickTaskLabel: 'Платёж / задача',
            visibleNav: [
                'navFinance', 'navAccounting', 'navIntegrations', 'navDocuments', 'navApprovals', 'navExpenses', 'navDeals',
                'navRequests', 'navClients', 'navClient360', 'navContract360', 'navDashboard', 'navMessenger', 'navEmails', 'navMeetings', 'navProfile'
            ],
        };
    }
    if (role === 'Склад') {
        return {
            ...common,
            slug: 'warehouse',
            quickTaskLabel: 'Задача склада',
            visibleNav: [
                'navSupply', 'navNomenclature', 'navIntegrations', 'navDocuments', 'navTasks', 'navApprovals',
                'navRequests', 'navService', 'navDashboard', 'navMessenger', 'navMeetings', 'navProfile'
            ],
        };
    }
    if (role === 'Производство и ОТК' || role === 'Конструкторское бюро') {
        return {
            ...common,
            slug: 'production',
            quickTaskLabel: 'Задача цеха',
            visibleNav: [
                'navProduction', 'navSupply', 'navIntegrations', 'navDocuments', 'navTasks', 'navApprovals',
                'navRequests', 'navResources', 'navService', 'navDashboard', 'navMessenger', 'navMeetings', 'navProfile'
            ],
        };
    }
    if (role === 'Юрист') {
        return {
            ...common,
            slug: 'legal',
            quickTaskLabel: 'Юр. поручение',
            visibleNav: [
                'navApprovals', 'navClaims', 'navDocuments', 'navIntegrations', 'navService', 'navKnowledge', 'navDashboard', 'navClient360', 'navContract360',
                'navClients', 'navProspecting', 'navLeads', 'navDeals', 'navMessenger', 'navEmails', 'navMeetings', 'navProfile'
            ],
        };
    }
    if (role === 'Секретарь / Канцелярия') {
        return {
            ...common,
            slug: 'office',
            quickTaskLabel: 'Регистрация / поручение',
            visibleNav: [
                'navDocuments', 'navTasks', 'navApprovals', 'navClients', 'navProspecting', 'navLeads', 'navDeals', 'navClient360', 'navEmails',
                'navMeetings', 'navKnowledge', 'navMessenger', 'navDashboard', 'navProfile'
            ],
        };
    }
    if (role === 'Сотрудник') {
        return {
            ...common,
            slug: 'employee',
            quickTaskLabel: 'Поручение',
            showScanner: false,
            visibleNav: [
                'navTasks', 'navDocuments', 'navIntegrations', 'navExpenses', 'navRequests', 'navKnowledge', 'navMessenger', 'navMeetings', 'navProfile'
            ],
        };
    }
    return { ...common, slug: 'default' };
}

function setRoleShellAttributes(roleName = '') {
    const slug = getRoleSlug(roleName);
    document.body.dataset.roleSlug = slug;
    document.body.dataset.roleName = normalizeRoleName(roleName);
    const appLayout = document.getElementById('appLayout');
    if (appLayout) {
        appLayout.dataset.roleSlug = slug;
        appLayout.dataset.roleName = normalizeRoleName(roleName);
    }
}

function setNavVisibility(navId, isVisible) {
    const el = document.getElementById(navId);
    if (!el) return;
    el.style.display = isVisible ? 'flex' : 'none';
}

function refreshSidebarGroupsVisibility() {
    document.querySelectorAll('.nav-group[data-nav-group]').forEach(group => {
        const visibleItems = Array.from(group.querySelectorAll('.nav-item')).filter(item => item.style.display !== 'none');
        group.style.display = visibleItems.length ? '' : 'none';
    });
}

window.applyRoleShell = function() {
    const config = getRoleUiConfig();
    setRoleShellAttributes(currentUser?.role || '');
    const allNavIds = [
        'navDashboard', 'navApprovals', 'navTasks', 'navKnowledge', 'navDocuments', 'navMessenger',
        'navEmails', 'navMeetings', 'navFinance', 'navAccounting', 'navIntegrations', 'navSupply', 'navSales', 'navProspecting', 'navLeads', 'navDeals',
        'navProduction', 'navExpenses', 'navRequests', 'navResources', 'navService', 'navExecutive',
        'navOperations', 'navClients', 'navClient360', 'navClaims', 'navNomenclature', 'navContacts', 'navAnalytics',
        'navContract360', 'navKpi', 'navProfile', 'adminBtn'
    ];
    allNavIds.forEach(id => {
        const alwaysVisible = id === 'navProfile';
        setNavVisibility(id, alwaysVisible || config.visibleNav.includes(id));
    });
    refreshSidebarGroupsVisibility();
    const deptLabel = document.querySelector('.krd-shell-sidebar__footer .nav-label');
    if (deptLabel) deptLabel.style.display = config.showDeptFilters ? '' : 'none';
    document.querySelectorAll('.dept-item').forEach(el => {
        el.style.display = config.showDeptFilters ? 'flex' : 'none';
    });
    const deptGroup = document.querySelector('.krd-shell-sidebar__footer');
    if (deptGroup) deptGroup.style.display = config.showDeptFilters ? '' : 'none';
    const taskBtn = document.getElementById('topbarQuickTaskBtn');
    if (taskBtn) {
        const label = document.getElementById('topbarQuickTaskLabel');
        if (label) label.textContent = config.quickTaskLabel;
    }
    const scanBtn = document.getElementById('topbarQuickScanBtn');
    if (scanBtn) scanBtn.style.display = config.showScanner ? 'inline-flex' : 'none';
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.placeholder = config.searchPlaceholder;
    if (typeof applyWorkspaceConfig === 'function') applyWorkspaceConfig();
    if (typeof syncMobileWorkspaceMode === 'function') syncMobileWorkspaceMode();
};

window.getRoleUiConfig = getRoleUiConfig;
window.getRoleSlug = getRoleSlug;

window.getRoleLandingView = function() {
    const role = String(currentUser?.role || '').trim();
    if (role === 'Директор') return 'executive';
    if (role === 'Бухгалтерия') return 'finance';
    if (role === 'Склад') return 'supply';
    if (role === 'Производство и ОТК' || role === 'Конструкторское бюро') return 'production';
    if (role === 'Юрист') return 'approvals';
    if (role === 'Секретарь / Канцелярия') return 'documents';
    if (role === 'Менеджер') return 'dashboard';
    if (role === 'Сотрудник') return 'tasks';
    return 'dashboard';
};

window.renderTableLoadingRow = function(colspan = 1, message = 'Загрузка данных...') {
    return `<tr><td colspan="${Number(colspan || 1)}" class="table-loading-cell">${message}</td></tr>`;
};

window.renderTableEmptyRow = function(colspan = 1, title = 'Список пока пуст.', text = '', actionsHtml = '') {
    return `
        <tr>
            <td colspan="${Number(colspan || 1)}" class="table-empty-cell">
                <div class="empty-state empty-state--table">
                    <div class="empty-state-premium-title">${title}</div>
                    ${text ? `<div class="empty-state-premium-text">${text}</div>` : ''}
                    ${actionsHtml ? `<div class="empty-state-actions">${actionsHtml}</div>` : ''}
                </div>
            </td>
        </tr>
    `;
};

window.renderInlineEmptyState = function(title, text = '', actionsHtml = '') {
    return `
        <div class="empty-state empty-state--premium">
            <div class="empty-state-premium-title">${title}</div>
            ${text ? `<div class="empty-state-premium-text">${text}</div>` : ''}
            ${actionsHtml ? `<div class="empty-state-actions">${actionsHtml}</div>` : ''}
        </div>
    `;
};

window.renderOnboardingEmptyState = function(kind = 'default', overrides = {}) {
    const presets = {
        project: ['Создай первый проект.', 'После этого появятся этапы, документы, финансы и задачи по реальному объекту.', `<button class="btn-primary" onclick="createNewProject()">Создать проект</button>`],
        one_c: ['Подключи 1С.', 'Боевой обмен ещё не настроен: укажи коннектор в админке, чтобы выгружать документы и оплаты без тестового режима.', `<button class="btn-secondary" onclick="navigateTo('users')">Открыть админку</button>`],
        file: ['Загрузи первый файл.', 'Файлы попадут в версии, поиск по содержимому и юридически значимые карточки документов.', `<button class="btn-secondary" onclick="navigateTo('documents')">Открыть документы</button>`],
        forbidden: ['Нет доступа к разделу.', 'Обратись к директору или администратору, чтобы выдали права на юрлицо, подразделение или модуль.', `<button class="btn-secondary" onclick="navigateTo('profile')">Мой профиль</button>`],
        default: ['Здесь пока пусто.', 'Создай первую запись или смени фильтр, чтобы начать рабочий поток.', ''],
    };
    const [title, text, actions] = presets[kind] || presets.default;
    return window.renderInlineEmptyState(overrides.title || title, overrides.text || text, overrides.actionsHtml ?? actions);
};

window.renderDeferredHtml = function(container, htmlProducer, options = {}) {
    if (!container) return;
    const threshold = Number(options.threshold || 60);
    const size = Number(options.size || 0);
    if (size < threshold) {
        container.innerHTML = htmlProducer();
        return;
    }
    if (container.tagName === 'TBODY') {
        container.innerHTML = window.renderTableLoadingRow(
            Number(options.colspan || 1),
            options.loadingMessage || 'Загружаю записи...'
        );
    } else {
        container.innerHTML = `<div class="empty-state empty-state--loading">${options.loadingMessage || 'Загружаю данные...'}</div>`;
    }
    requestAnimationFrame(() => {
        container.innerHTML = htmlProducer();
    });
};

function renderFormPolicyBanner(bannerId, payload) {
    const el = typeof bannerId === 'string' ? document.getElementById(bannerId) : null;
    if (!el) return;
    const hidden = Array.isArray(payload?.hidden_fields) ? payload.hidden_fields : [];
    const readonly = Array.isArray(payload?.readonly_fields) ? payload.readonly_fields : [];
    const restrictedEntries = Object.entries(payload?.restricted_status_fields || {});
    const statusFields = Array.isArray(payload?.status_fields) ? payload.status_fields : [];
    const parts = [];
    if (hidden.length) {
        parts.push(`Скрыто полей: ${hidden.length}`);
    }
    if (readonly.length) {
        parts.push(`Только просмотр: ${readonly.length}`);
    }
    if (restrictedEntries.length) {
        parts.push(`Ограничения по статусам: ${restrictedEntries.length}`);
    }
    if (!parts.length) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }
    el.style.display = '';
    el.innerHTML = `
        <div class="form-policy-banner-title">Политика доступа формы</div>
        <div class="form-policy-banner-summary">${parts.join(' · ')}</div>
        <div class="form-policy-banner-chips">
            ${hidden.map(field => `<span class="form-policy-chip">Скрыто: ${field}</span>`).join('')}
            ${readonly.map(field => `<span class="form-policy-chip">Только чтение: ${field}</span>`).join('')}
            ${restrictedEntries.map(([field, statuses]) => `<span class="form-policy-chip">${field}: ${statuses.join(', ')}</span>`).join('')}
            ${statusFields.filter(field => !restrictedEntries.some(([name]) => name === field)).map(field => `<span class="form-policy-chip">Политика статуса: ${field}</span>`).join('')}
        </div>
    `;
}

async function applyFieldPermissionsWithFeedback(module, entityType, fieldMap = {}, bannerId = '') {
    applyFieldPermissionsToForm(module, entityType, fieldMap);
    const cacheKey = `${module}::${entityType}`;
    if (!window.__formPolicyCache[cacheKey]) {
        window.__formPolicyCache[cacheKey] = await fetchFormPolicy(module, entityType);
    }
    renderFormPolicyBanner(bannerId, window.__formPolicyCache[cacheKey]);
}

window.applyFieldPermissionsWithFeedback = applyFieldPermissionsWithFeedback;

async function fetchFormPolicy(module, entityType) {
    if (!module || !entityType) return null;
    try {
        return await apiCall(`/permissions/forms/${encodeURIComponent(module)}/${encodeURIComponent(entityType)}`);
    } catch (_err) {
        return null;
    }
}

window.fetchFormPolicy = fetchFormPolicy;

function explainApiPolicyError(payload = {}) {
    const errorCode = String(payload?.error || '').trim();
    if (errorCode === 'forbidden_field') {
        return `Поле «${payload.field || 'поле'}» нельзя менять по текущей политике.`;
    }
    if (errorCode === 'forbidden_status') {
        const allowed = Array.isArray(payload.allowed_statuses) ? payload.allowed_statuses.filter(Boolean) : [];
        return `Статус для «${payload.field || 'поля'}» запрещён.${allowed.length ? ` Разрешено: ${allowed.join(', ')}.` : ''}`;
    }
    if (errorCode === 'policy_blocked') return payload.message || 'Действие запрещено уровнем политик.';
    if (errorCode === 'danger_blocked') return payload.message || 'Опасная операция заблокирована для этой роли.';
if (errorCode === 'two_factor_required') return payload.message || 'Для этого действия нужно включить двухфакторную защиту.';
    if (errorCode === 'reason_required') return payload.message || 'Для этого действия нужно указать причину.';
    return payload?.message || payload?.error || 'Операция заблокирована политикой безопасности.';
}

async function securityGuardCheck(moduleName, entityType, actionName, statusName = '', reason = '') {
    if (!currentUser || currentUser.status !== 'approved') {
        return { error: 'forbidden', message: 'Нужна активная сессия.' };
    }
    return await apiCall('/security/guard/check', 'POST', {
        module_name: moduleName || '',
        entity_type: entityType || '',
        action_name: actionName || '',
        status_name: statusName || '',
        reason: reason || '',
    });
}

async function guardDangerousAction(moduleName, entityType, actionName, options = {}) {
    let reason = String(options.reason || '').trim();
    const statusName = String(options.statusName || '').trim();
    let probe = await securityGuardCheck(moduleName, entityType, actionName, statusName, reason);
    if (!probe || probe.error === 'forbidden') {
        await customAlert(explainApiPolicyError(probe || {}));
        return { allowed: false, reason: '' };
    }
    if (probe.error === 'reason_required') {
        reason = await customPrompt(probe.message || 'Укажи причину операции.', '');
        if (reason === null) return { allowed: false, reason: '' };
        probe = await securityGuardCheck(moduleName, entityType, actionName, statusName, reason);
    }
    if (probe?.error) {
        await customAlert(explainApiPolicyError(probe));
        return { allowed: false, reason: '' };
    }
    return { allowed: true, reason };
}

window.explainApiPolicyError = explainApiPolicyError;
window.securityGuardCheck = securityGuardCheck;
window.guardDangerousAction = guardDangerousAction;

async function fetchExchangeRates() {
    try {
        const res = await fetch('https://www.cbr-xml-daily.ru/daily_json.js');
        const data = await res.json();
        window.exchangeRates = {
            RUB: 1,
            USD: data.Valute.USD.Value,
            EUR: data.Valute.EUR.Value,
            CNY: data.Valute.CNY.Value
        };
    } catch (e) {
        console.error('Ошибка парсинга курсов ЦБ', e);
    }
}

const checklistTemplate = [
    { title: "1. Производство", responsibles: "Конструкторское бюро, Производство и ОТК, Директор", tasks: ["КД разработана, создана и передана на производство.", "Производство приняло КД и приступило к исполнению.", "Продукция произведена и успешно проверена ОТК.", "Готовая продукция отгружена Заказчику."] },
    { title: "2. Техническая и конструкторская документация (КД)", responsibles: "Конструкторское бюро", tasks: ["Финальная конструкторская документация (с учетом всех изменений) согласована, а исполнительная документация сформирована, прошита и передана Заказчику.", "Получена отметка Заказчика о приемке технической/исполнительной документации."] },
    { title: "3. Логистика и сдача-приемка (Акты и КС)", responsibles: "Менеджер", tasks: ["Оборудование / товар доставлены на объект (подписаны ТТН, транспортные накладные).", "Подписан полный комплект приемо-сдаточной документации со стороны Заказчика (акты входного контроля, КСК, ведомости ЗИП, формы КС-2 и КС-3, акты ПНР и ввода в эксплуатацию и др.)."] },
    { title: "4. Бухгалтерские закрывающие документы", responsibles: "Менеджер, Бухгалтерия", tasks: ["Оригиналы подписанных Заказчиком закрывающих документов (УПД, ТОРГ-12, Счета-фактуры) получены и сданы в бухгалтерию.", "Подписан двусторонний Акт сверки взаиморасчетов по договору (без расхождений)."] },
    { title: "5. Финансы и дебиторская задолженность", responsibles: "Менеджер, Бухгалтерия", tasks: ["Все финансовые расчеты по сделке завершены (финальный платеж поступил, дебиторская задолженность погашена).", "Банковские гарантии (авансовые, на исполнение) возвращены банком или срок их действия истек."] },
    { title: "6. Юридические вопросы и гарантия", responsibles: "Юрист", tasks: ["Возможные претензии и штрафы урегулированы. Оригинал Договора со всеми доп. соглашениями сдан в архив."] }
];

// API/session/websocket helpers were extracted into app_api.js and app_shell.js.

function checkOverdueTasksGlobal() {
    if (typeof tasksDB === 'undefined' || !currentUser) return;
    const today = new Date(); today.setHours(0,0,0,0);
    let overdueCount = 0;
    tasksDB.forEach(t => {
        if (t.status === 'active' && (t.executor === currentUser.name || t.executor.includes(currentUser.name))) {
            const pts = (t.deadline || '').split('.');
            if (pts.length === 3) {
                const d = new Date(pts[2], pts[1]-1, pts[0]);
                if (d < today) overdueCount++;
            }
        }
    });
    const ctrl = document.getElementById('topbarTaskControl');
    const countEl = document.getElementById('topbarOverdueCount');
    if (ctrl && countEl) {
        if (overdueCount > 0) { ctrl.style.display = 'flex'; countEl.innerText = overdueCount; }
        else { ctrl.style.display = 'none'; }
    }
}

window.onload = async () => {
    document.documentElement.dataset.theme = 'light';
    localStorage.removeItem('theme');
    const path = window.location.pathname;
    await bootstrapSession();

    if (currentUser && currentUser.status === 'approved') {
        if (path.includes('login.html') || path.includes('register.html') || path === '/' || path === '') {
            window.location.href = '/app'; return;
        }
        await fetchExchangeRates();
        await loadPermissions();
        await loadProjects(); await loadClients(); await loadAllUsers(); await loadMeetings(); await loadCalendarEvents(); await loadCrmLeads(); await loadCrmDeals(); await loadEmailAccounts(); await loadDocuments(); await loadTasks(); await loadKnowledge(); await loadApprovals(); await loadClaims(); await loadCourtCases(); await loadAuditLogs(); await loadNotifications();
        
        if (document.getElementById('appLayout')) {
            document.getElementById('appLayout').classList.remove('krd-is-hidden');
            document.getElementById('appLayout').style.display = 'flex';
            
            let titleStr = `${currentUser.name} (${currentUser.role})`;
            if (currentUser.is_head === 1 && currentUser.role !== 'Директор') titleStr += " · Руководитель";
            const uNameEl = document.getElementById('topbarUserName');
            if (uNameEl) uNameEl.innerText = titleStr;
            const roleBadgeEl = document.getElementById('topbarRoleBadge');
            if (roleBadgeEl) roleBadgeEl.innerText = currentUser.role === 'Директор' ? 'Директор' : currentUser.role || 'Роль';
            const modeBadgeEl = document.getElementById('topbarModeBadge');
            if (modeBadgeEl) {
                modeBadgeEl.innerText = currentUser.role === 'Директор' ? 'Директор' : (currentUser.is_head === 1 ? 'Руководитель' : 'Рабочий контур');
            }
            
            const uInitEl = document.getElementById('topbarUserInitials');
            if (uInitEl && currentUser.name) {
                const parts = currentUser.name.split(' ');
                uInitEl.innerText = parts.length > 1 ? (parts[0][0] + parts[1][0]).toUpperCase() : parts[0][0].toUpperCase();
            }
            
            const adminBtn = document.getElementById('adminBtn');
            if (adminBtn) adminBtn.style.display = currentUser.role === 'Директор' ? 'flex' : 'none';
            
            const kpiBtn = document.getElementById('navKpi');
            if (kpiBtn) kpiBtn.style.display = currentUser.role === 'Директор' ? 'flex' : 'none';

            const executiveBtn = document.getElementById('navExecutive');
            if (executiveBtn) executiveBtn.style.display = currentUser.role === 'Директор' ? 'flex' : 'none';
            if (typeof applyRoleShell === 'function') applyRoleShell();
            if (typeof syncMobileWorkspaceMode === 'function') syncMobileWorkspaceMode();
            
            if (currentUser.role === 'Директор') {
                const pUsers = await apiCall('/users/pending');
                const badge = document.getElementById('pendingBadge');
                if (badge && pUsers && pUsers.length > 0) { badge.innerText = pUsers.length; badge.style.display = 'inline-block'; }
            }

            if (typeof Chart !== 'undefined') Chart.register(ChartDataLabels);
            if (typeof setViewMode === 'function') setViewMode(viewMode);
            if (typeof renderNotifications === 'function') renderNotifications();
            if (typeof initSignaturePad === 'function') initSignaturePad(); 
            checkOverdueTasksGlobal();
            if (typeof initClaimsUI === 'function') initClaimsUI();
            const savedView = localStorage.getItem('korda_last_view');
            const landingView = savedView || (typeof getRoleLandingView === 'function' ? getRoleLandingView() : 'dashboard');
            if (typeof navigateTo === 'function') navigateTo(landingView);
            
            connectWebSocket();
        }
    } else if (currentUser && currentUser.status === 'pending') {
        if (!path.includes('login.html') && !path.includes('register.html')) { window.location.href = '/static/login.html'; return; }
        if (path.includes('login.html')) { document.getElementById('loginFormCard').style.display = 'none'; document.getElementById('pendingCard').style.display = 'block'; }
    } else {
        if (!path.includes('login.html') && !path.includes('register.html')) { window.location.href = '/static/login.html'; }
    }
};

setInterval(async () => {
    if(!currentUser || currentUser.status !== 'approved') return;
    const res = await apiCall(`/status/${currentUser.email}`);
    if (res && res.status === 'banned') { 
        customAlert("Ваш аккаунт был заблокирован администратором.").then(() => logout()); 
        return; 
    }
    if (res && res.is_head !== undefined) {
        currentUser.is_head = res.is_head;
    }
    if (currentUser.role === 'Директор' && document.getElementById('appLayout')) {
        for (let i = 0; i < projectsDB.length; i++) {
            let p = projectsDB[i];
            if (p.status !== 'active' || !p.checklist) continue;
            const today = new Date(); today.setHours(0,0,0,0);
            let projectChanged = false;
            p.checklist.forEach((sec, sIdx) => {
                if (p.deadlines && p.deadlines[sIdx]) {
                    const pts = p.deadlines[sIdx].split('.');
                    if (pts.length === 3) {
                        const dDate = new Date(pts[2], pts[1]-1, pts[0]);
                        if (dDate < today) {
                            let secOk = true;
                            for (let t = 0; t < sec.tasks.length; t++) { 
                                if (!p.checkedState || !p.checkedState[`task_${sIdx}_${t}`] || p.checkedState[`task_${sIdx}_${t}`].startsWith('🟡')) secOk = false; 
                            }
                            const escKey = `esc_${sIdx}`;
                            if (!secOk && (!p.escalations || !p.escalations[escKey])) {
                                if (!p.escalations) p.escalations = {};
                                p.escalations[escKey] = true;
                                if(!p.logs) p.logs = [];
                                const now = new Date();
                                const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
                                p.logs.unshift({ time: timeStr, user: "Система", action: `⚠️ АВТО-ЭСКАЛАЦИЯ: Просрочен этап "${sec.title}". Ответственные: ${sec.responsibles}. Уведомлен Директор.` });
                                projectChanged = true; 
                            }
                        }
                    }
                }
            });
            if (projectChanged) await apiCall(`/projects/${p.id}`, 'PUT', p);
        }
    }
}, 60000); 

setInterval(async () => {
    if (!currentUser || currentUser.status !== 'approved') return;
    await loadNotifications();
    if (typeof renderNotifications === 'function') renderNotifications();
}, 20000);

// Theme/auth/modal/search shell moved into app_shell.js.
