window.API_URL = window.API_URL || '/api';

function humanizeApiError(errorCode = '', payload = {}) {
    const normalized = String(errorCode || '').trim();
    if (!normalized) return '';
    if (payload && typeof payload.message === 'string' && payload.message.trim()) return payload.message.trim();
    if (normalized.startsWith('period_closed:')) return 'Период закрыт. Сначала открой период или измени дату операции.';
    const map = {
        forbidden: 'Недостаточно прав.',
        unauthorized: 'Сессия истекла. Войди заново.',
        forbidden_scope: 'Нет прав на это юрлицо или подразделение.',
        not_found: 'Запись не найдена.',
        client_not_found: 'Не найден контрагент.',
        supplier_required: 'Не выбран поставщик.',
        supplier_not_found: 'Поставщик не найден.',
        counterparty_required: 'Не выбран контрагент.',
        legal_entity_required: 'Не выбрано юрлицо.',
        business_unit_required: 'Не выбрано подразделение.',
        document_not_found: 'Выберите документ.',
        version_not_found: 'Версия документа не найдена.',
        inbound_not_found: 'Входящая запись не найдена.',
        connector_not_found: 'Узел интеграции не найден.',
        payment_not_found: 'Связанная оплата не найдена.',
        nomenclature_not_found: 'Номенклатура не найдена.',
        qty_required: 'Поле обязательно: укажи количество.',
        amount_required: 'Укажи сумму.',
        date_required: 'Укажи дату.',
        items_required: 'Добавьте хотя бы одну строку или позицию.',
        dimension_required: 'Выберите параметр аналитики.',
        stages_required: 'Выберите этапы маршрута.',
        orders_required: 'Выберите платёжные поручения.',
        orders_not_found: 'Платёжные поручения не найдены.',
        result_items_required: 'Добавьте результаты обработки.',
        source_required: 'Укажи источник данных.',
        nothing_to_fulfill: 'Нечего списывать по этой записи.',
        qty_exceeds_remaining: 'Количество больше остатка.',
        insufficient_stock: 'Недостаточно остатка на складе.',
        invalid_type: 'Указан неверный тип операции.',
        invalid_action: 'Недопустимое действие.',
        invalid_stage: 'Недопустимый этап процесса.',
        invalid_rule: 'Некорректное правило доступа.',
        invalid_date: 'Дата указана в неверном формате.',
        invalid_inn: 'ИНН должен быть из 10 или 12 цифр.',
        invalid_kpp: 'КПП должен быть из 9 цифр.',
        invalid_bik: 'БИК должен быть из 9 цифр.',
        invalid_email: 'Email указан в неверном формате.',
        invalid_amount: 'Сумма должна быть числом больше нуля.',
        invalid_vat: 'Проверь ставку и сумму НДС.',
        invalid_storage_cell: 'Складская ячейка не найдена.',
        invalid_otp: 'Неверный код двухфакторной защиты.',
        validation_error: 'Проверь обязательные поля.',
        db_locked: 'Система временно занята. Повтори действие.',
        policy_blocked: 'Действие запрещено правилами безопасности.',
        danger_blocked: 'Опасная операция заблокирована.',
        two_factor_required: 'Для этого действия нужно включить двухфакторную защиту.',
        reason_required: 'Укажи причину действия.',
        forbidden_field: 'Это поле недоступно для редактирования.',
        forbidden_status: 'Этот статус недоступен для текущей роли.',
        unsupported_report_type: 'Этот тип отчёта пока не поддерживается.',
        unsupported_connector_type: 'Этот тип подключения пока не поддерживается.',
        production_1c_connector_required: 'Боевой 1C-коннектор не настроен. Demo-обмен запрещён в production.',
        one_c_unavailable: '1C недоступна. Проверь подключение или повтори позже.',
        sync_failed: 'Синхронизация не прошла. Подробности есть в журнале обмена.',
        outbound_sync_failed: 'Не удалось отправить запись в 1C.',
        inbound_sync_failed: 'Не удалось принять данные из 1C.',
        file_validation_failed: 'Файл не прошёл проверку.',
        document_file_validation_failed: 'Файл документа не прошёл проверку.',
        antivirus_failed: 'Файл не прошёл антивирусную проверку.',
        mime_validation_failed: 'Тип файла не совпадает с содержимым.',
        draft_key_required: 'Не найден ключ черновика формы.',
        form_draft_not_found: 'Серверный черновик не найден.',
        source_url_required: 'Укажи ссылку на источник данных.',
        bulk_action_invalid: 'Выбери строки и действие для массовой операции.',
        bulk_action_not_supported: 'Это массовое действие недоступно для выбранных записей.',
        unsupported_entity: 'Этот тип записи пока не поддерживается.',
        smtp_not_configured: 'Почтовые уведомления пока не настроены.',
    };
    if (map[normalized]) return map[normalized];
    if (/^[a-z0-9_:-]+$/i.test(normalized)) {
        return 'Операция не выполнена. Подробности доступны в журнале системы.';
    }
    return '';
}

window.humanizeApiError = humanizeApiError;

async function apiCall(endpoint, method = 'GET', body = null) {
    const options = { method, headers: {}, credentials: 'same-origin' };
    if (body instanceof FormData) {
        options.body = body;
    } else if (body) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    try {
        const res = await fetch(window.API_URL + endpoint, options);
        const payload = await res.json();
        if (payload && payload.error && !payload.message) {
            const humanMessage = humanizeApiError(payload.error, payload);
            if (humanMessage) payload.message = humanMessage;
        }
        if (payload && !payload.message && Array.isArray(payload.field_errors) && payload.field_errors.length) {
            payload.message = payload.field_errors.map(item => item?.message).filter(Boolean)[0] || 'Проверь поля формы.';
        }
        return payload;
    } catch (e) {
        return { error: 'network_error', message: 'Не удалось связаться с сервером. Проверь подключение и попробуй ещё раз.' };
    }
}

async function bootstrapSession() {
    const data = await apiCall('/session');
    if (data && !data.error) {
        currentUser = data;
        return currentUser;
    }
    currentUser = null;
    localStorage.removeItem('korda_session');
    return null;
}

async function loadProjects() {
    const isHead = currentUser.is_head || 0;
    const url = `/projects?user_name=${encodeURIComponent(currentUser.name)}&user_role=${encodeURIComponent(currentUser.role)}&is_head=${isHead}`;
    const data = await apiCall(url);
    if (Array.isArray(data)) projectsDB = typeof normalizeProjectCollection === 'function' ? normalizeProjectCollection(data) : data;
    else projectsDB = [];
    return projectsDB;
}

async function loadClients() {
    const data = await apiCall('/clients');
    clientsDB = Array.isArray(data) ? data : [];
}

async function loadAllUsers() {
    const data = await apiCall('/users/all');
    allUsersDB = Array.isArray(data) ? data : [];
}

async function loadMeetings() {
    const data = await apiCall('/meetings');
    meetingsDB = Array.isArray(data) ? data : [];
}

async function loadCalendarEvents() {
    const data = await apiCall('/calendar/events');
    calendarEventsDB = Array.isArray(data) ? data : [];
}

async function loadCrmLeads() {
    const data = await apiCall('/crm/leads');
    crmLeadsDB = Array.isArray(data) ? data : [];
}

async function loadCrmDeals() {
    const data = await apiCall('/crm/deals');
    crmDealsDB = Array.isArray(data) ? data : [];
}

async function loadEmailAccounts() {
    const data = await apiCall('/email/accounts');
    emailAccountsDB = Array.isArray(data) ? data : [];
}

async function loadDocuments() {
    const data = await apiCall('/documents');
    documentsDB = Array.isArray(data) ? data : [];
    if (typeof loadDocumentPackages === 'function') await loadDocumentPackages();
}

async function loadTasks() {
    const data = await apiCall('/tasks');
    tasksDB = Array.isArray(data) ? data : [];
    if (typeof checkOverdueTasksGlobal === 'function') checkOverdueTasksGlobal();
}

async function loadKnowledge() {
    const data = await apiCall('/knowledge');
    knowledgeDB = Array.isArray(data) ? data : [];
}

async function loadApprovals() {
    const data = await apiCall('/approvals');
    approvalsDB = Array.isArray(data) ? data : [];
    if (typeof loadWorkflowDefinitions === 'function') await loadWorkflowDefinitions();
    if (typeof loadWorkflowInstances === 'function') await loadWorkflowInstances();
}

async function loadClaims() {
    const data = await apiCall('/claims');
    claimsDB = Array.isArray(data) ? data : [];
}

async function loadCourtCases() {
    const data = await apiCall('/court_cases');
    courtCasesDB = Array.isArray(data) ? data : [];
}

async function loadAuditLogs(limit = 120) {
    if (!currentUser || currentUser.role !== 'Директор') {
        auditLogsDB = [];
        return;
    }
    const data = await apiCall(`/audit/logs?limit=${limit}`);
    auditLogsDB = Array.isArray(data) ? data : [];
}

async function loadNotifications(limit = 80) {
    if (!currentUser || currentUser.status !== 'approved') {
        notificationsDB = [];
        return;
    }
    const data = await apiCall(`/notifications?limit=${limit}`);
    notificationsDB = Array.isArray(data) ? data : [];
}

async function loadPermissions() {
    if (!currentUser || currentUser.status !== 'approved') {
        currentPermissions = {};
        window.currentPermissionMeta = { field_permissions: [], field_policy_map: {}, scope: { legal_entities: [], business_units: [] }, two_factor_enabled: 0 };
        return;
    }
    const data = await apiCall('/permissions');
    currentPermissions = data && !data.error ? (data.permissions || {}) : {};
    window.currentPermissionMeta = data && !data.error
        ? {
            field_permissions: Array.isArray(data.field_permissions) ? data.field_permissions : [],
            field_policy_map: data.field_policy_map || {},
            scope: data.scope || { legal_entities: [], business_units: [] },
            two_factor_enabled: Number(data.two_factor_enabled || 0),
        }
        : { field_permissions: [], field_policy_map: {}, scope: { legal_entities: [], business_units: [] }, two_factor_enabled: 0 };
}

window.apiCall = apiCall;
window.bootstrapSession = bootstrapSession;
window.loadProjects = loadProjects;
window.loadClients = loadClients;
window.loadAllUsers = loadAllUsers;
window.loadMeetings = loadMeetings;
window.loadCalendarEvents = loadCalendarEvents;
window.loadCrmLeads = loadCrmLeads;
window.loadCrmDeals = loadCrmDeals;
window.loadEmailAccounts = loadEmailAccounts;
window.loadDocuments = loadDocuments;
window.loadTasks = loadTasks;
window.loadKnowledge = loadKnowledge;
window.loadApprovals = loadApprovals;
window.loadClaims = loadClaims;
window.loadCourtCases = loadCourtCases;
window.loadAuditLogs = loadAuditLogs;
window.loadNotifications = loadNotifications;
window.loadPermissions = loadPermissions;
