let docflowPlusDB = null;
let integrationPlusDB = null;
let securityPlusDB = null;
let docflowVersionDiffState = null;
let docflowTimelineState = null;
let integrationInboundPreviewState = null;

function opsPlusEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function opsPlusJsString(value) {
    return String(value || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function opsPlusPercent(value) {
    const percent = Math.max(0, Math.min(100, Number(value || 0)));
    return Number.isInteger(percent) ? String(percent) : percent.toFixed(1);
}

function opsPlusStatusBadge(value) {
    const tone = ['active', 'applied', 'generated', 'archived', 'synced'].includes(value) ? 'status-active'
        : ['error', 'failed', 'conflict', 'danger'].includes(value) ? 'status-overdue'
        : 'status-archived';
    return `<span class="status-badge ${tone}">${opsPlusEscape(opsPlusStatusLabel(value || 'draft'))}</span>`;
}

function opsPlusStatusLabel(value) {
    return {
        active: 'Активно',
        applied: 'Применено',
        generated: 'Сформировано',
        archived: 'В архиве',
        synced: 'Синхронизировано',
        error: 'Ошибка',
        failed: 'Сбой',
        conflict: 'Конфликт',
        danger: 'Риск',
        draft: 'Черновик',
        apply: 'Применить',
        preview: 'Предпросмотр',
        queue_only: 'Только в очередь',
        shared: 'Общий',
        typing_gap: 'Проблема типизации',
        logged: 'Зафиксировано',
        bidirectional: 'Двусторонний',
        inbound: 'Входящий',
        outbound: 'Исходящий',
        exported: 'Выгружено',
        healthy: 'В норме',
        stale: 'Зависло',
        attention: 'Требует внимания',
        open: 'Открыто',
        pending: 'Ожидает',
        unsigned: 'Не подписано',
        incoming: 'Регистрация',
        approval: 'Согласование',
        approved: 'Согласовано',
        not_started: 'Не начато',
        idle: 'Ожидает запуска',
        allow: 'Разрешено',
        deny: 'Запрещено',
        medium: 'Средний риск',
        high: 'Высокий риск',
        critical: 'Критичный риск',
    }[value] || value || 'Статус';
}

function opsPlusModuleLabel(value) {
    return {
        finance: 'Финансы',
        sales: 'Продажи',
        supply: 'Снабжение',
        production: 'Производство',
        documents: 'Документы',
        security: 'Безопасность',
        integration: 'Интеграции',
        accounting: 'Бухгалтерия',
        epl: 'ЭПЛ',
        nsi: 'НСИ',
        projects: 'Проекты',
        clients: 'Клиенты',
        service: 'Сервис',
        resources: 'Ресурсы',
        treasury: 'Казначейство',
        warehouse: 'Склад',
    }[value] || value || 'Модуль';
}

function opsPlusActionLabel(value) {
    return {
        create: 'создание',
        update: 'изменение',
        delete: 'удаление',
        view: 'просмотр',
        export: 'экспорт',
        sync_1c: 'обмен с 1С',
        close_period: 'закрытие периода',
        post: 'проведение',
        reserve: 'резервирование',
        receive: 'приёмка',
        ship: 'отгрузка',
        route: 'маршрутизация',
        sign_edo: 'подписание ЭДО',
        login_success: 'Успешный вход',
        project_updated: 'Обновление проекта',
        production_order_created: 'Создание производственного заказа',
        finance_payment_created: 'Создание платежа',
        sales_document_created: 'Создание документа продажи',
        inventory_document_created: 'Создание складского документа',
        workflow_token_action: 'Действие по маршруту согласования',
        stock_movement_created: 'Складское движение',
        stock_reserved: 'Резервирование товара',
        production_operation_created: 'Создание производственной операции',
        purchase_created: 'Создание закупки',
        project_created: 'Создание проекта',
        action: 'Действие',
    }[value] || value || 'действие';
}

function opsPlusEntityLabel(value) {
    const key = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    return {
        bank_accounts: 'Банковские счета',
        characteristics: 'Характеристики',
        employees: 'Сотрудники',
        epl_waybill: 'ЭПЛ',
        finance_payment: 'Платежи',
        financial_responsibility_centers: 'ЦФО',
        groups: 'Группы',
        income_expense_articles: 'Статьи доходов и расходов',
        legal_entities: 'Юрлица',
        nomenclature: 'Номенклатура',
        operation_types: 'Виды операций',
        positions: 'Должности',
        production_order: 'Производственные заказы',
        purchase_order: 'Закупки',
        sales_document: 'Реализации',
        stock_reservation: 'Складской резерв',
        stock_reservations: 'Складские резервы',
        storage_cells: 'Ячейки хранения',
        telephony_accounts: 'Линии телефонии',
        telephony_calls: 'Звонки',
        units: 'Единицы измерения',
        warehouses: 'Склады',
        bank_statement_lines: 'Строки банковской выписки',
        bi_reports: 'Аналитические витрины',
    }[key] || 'Раздел данных';
}

function opsPlusRecoveryLabel(value) {
    const key = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    const labels = {
        failed_queue: 'Очередь с ошибками',
        retry_queue: 'Очередь повторов',
        stale_processing: 'Зависшая обработка',
        recent_conflicts: 'Последние конфликты',
        inbound_errors: 'Ошибки входящих обновлений',
        open_errors: 'Открытые ошибки',
        critical_errors: 'Критичные ошибки',
        retryable_total: 'Можно повторить',
        idempotency_keys_total: 'Контроль дублей',
        idempotency_collisions: 'Конфликты дублей',
        consistency_alerts: 'Предупреждения целостности',
        bank_unreconciled: 'Несведённый банк',
        telephony_unlinked: 'Непривязанные звонки',
        mappings_total: 'Всего сопоставлений',
        queue_open: 'Открытая очередь',
        queue_failed: 'Ошибки очереди',
        reconciliation_runs: 'Прогоны сверки',
        inbound_received: 'Входящие обновления',
        bank_accounts_total: 'Банковские счета',
        telephony_accounts_total: 'Линии телефонии',
        bi_reports_total: 'Аналитические витрины',
        connectors_total: 'Подключения',
        mapping_coverage_entities: 'Покрытые сущности',
        documents_total: 'Всего документов',
        templates_total: 'Всего шаблонов',
        versions_total: 'Всего версий',
        linked_tasks_open: 'Открытые поручения',
        archive_total: 'Документов в архиве',
        print_forms_total: 'Печатные формы',
        certificates_active: 'Активные сертификаты',
        certificates_expiring: 'Истекающие сертификаты',
        coverage_gaps: 'Пробелы покрытия',
        doc_types_strict: 'Строгие типы документов',
        typing_issues: 'Проблемы типизации',
        archive_risks: 'Риски архива',
        template_families: 'Семейства шаблонов',
        policies_total: 'Всего правил',
        danger_rules_total: 'Опасных правил',
        field_rules_total: 'Правил по полям',
        sessions_total: 'Активных сессий',
        two_factor_users: 'Пользователей с 2FA',
        field_changes_total: 'Изменений полей',
        risky_actions_total: 'Опасных действий',
        matrix_rows_total: 'Строк матрицы',
        matrix_rows_covered: 'Покрыто строк',
        matrix_coverage_percent: 'Покрытие, %',
    };
    const modulePrefixes = {
        production: 'Производство',
        finance: 'Финансы',
        warehouse: 'Склад',
        stock: 'Склад',
        integration: 'Интеграции',
        integrations: 'Интеграции',
        security: 'Безопасность',
        backup: 'Резервное копирование',
    };
    for (const [prefix, label] of Object.entries(modulePrefixes)) {
        const prefixText = `${prefix}_`;
        if (key.startsWith(prefixText)) {
            return `${label}: ${labels[key.slice(prefixText.length)] || 'показатель контроля'}`;
        }
    }
    return labels[key] || 'Показатель контроля';
}

function opsPlusFieldLabel(value) {
    const key = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    if ((key.includes('item') || key.includes('position')) && (key.includes('name') || key.includes('наз'))) return 'наименование позиции';
    if ((key.includes('item') || key.includes('position')) && (key.includes('article') || key.includes('арт'))) return 'артикул позиции';
    if (key.includes('object') && (key.includes('identifier') || key.includes('иденти'))) return 'объект';
    if (key.includes('project') && (key.includes('identifier') || key.includes('иденти'))) return 'проект';
    if (key.includes('contract') && (key.includes('identifier') || key.includes('иденти'))) return 'договор';
    if (key.includes('expected') && key.includes('date')) return 'ожидаемая дата';
    return {
        id: 'идентификатор',
        identifier: 'идентификатор',
        external_id: 'внешний идентификатор',
        entity_id: 'идентификатор записи',
        entity_type: 'тип сущности',
        name: 'наименование',
        title: 'название',
        number: 'номер',
        code: 'код',
        article: 'артикул',
        article_kind: 'вид статьи',
        category: 'категория',
        kind: 'вид',
        status: 'статус',
        state: 'состояние',
        stage: 'этап',
        priority: 'приоритет',
        progress: 'готовность',
        is_active: 'активность',
        warehouse: 'склад',
        warehouse_id: 'склад',
        default_warehouse: 'склад по умолчанию',
        zone_name: 'зона склада',
        storage_cell: 'ячейка',
        storage_cell_id: 'ячейка',
        bin_code: 'код ячейки',
        serial_no: 'серийный номер',
        batch_no: 'партия',
        batch_code: 'код партии',
        qty: 'количество',
        quantity: 'количество',
        planned_qty: 'плановое количество',
        produced_qty: 'произведено',
        scrap_qty: 'брак',
        stock: 'остаток',
        fulfilled_qty: 'исполнено',
        reserved_qty: 'зарезервировано',
        price: 'цена',
        planned_cost: 'плановая себестоимость',
        actual_cost: 'фактическая себестоимость',
        labor_hours_plan: 'плановые трудозатраты',
        labor_hours_fact: 'фактические трудозатраты',
        project_id: 'проект',
        project_identifier: 'проект',
        project: 'проект',
        client_id: 'клиент',
        client_identifier: 'клиент',
        client: 'клиент',
        object_id: 'объект',
        object_identifier: 'объект',
        object: 'объект',
        contract_id: 'договор',
        contract_identifier: 'договор',
        contract: 'договор',
        item_id: 'позиция',
        item_identifier: 'позиция',
        item_name: 'наименование позиции',
        item_article: 'артикул позиции',
        expected_date: 'ожидаемая дата',
        received_date: 'дата получения',
        delivery_date: 'дата поставки',
        due_date: 'срок исполнения',
        paid_date: 'дата оплаты',
        doc_date: 'дата документа',
        doc_number: 'номер документа',
        doc_type: 'тип документа',
        source_document_id: 'исходный документ',
        source_document_type: 'тип исходного документа',
        supplier: 'поставщик',
        unit: 'единица измерения',
        unit_price: 'цена за единицу',
        manager_id: 'ответственный',
        manager_name: 'ответственный',
        full_name: 'ФИО',
        personnel_number: 'табельный номер',
        department_name: 'отдел',
        position_id: 'должность',
        phone: 'телефон',
        email: 'электронная почта',
        recipient_email: 'почта получателя',
        document_id: 'документ',
        order_id: 'заказ',
        order_name: 'заказ',
        amount: 'сумма',
        total_amount: 'итоговая сумма',
        vat_amount: 'НДС',
        vat_rate_id: 'ставка НДС',
        currency: 'валюта',
        payment_status: 'статус оплаты',
        shipment_status: 'статус отгрузки',
        sent_status: 'статус отправки',
        status_name: 'статус',
        account_number: 'расчётный счёт',
        bank_name: 'банк',
        bik: 'БИК',
        legal_entity_id: 'юридическое лицо',
        business_unit_id: 'подразделение',
        treasury_article_id: 'статья движения денег',
        flow_kind: 'вид движения',
        characteristic_type: 'тип характеристики',
        group_name: 'группа',
        module_name: 'модуль',
        route_name: 'маршрут',
        comment: 'комментарий',
        created_at: 'дата создания',
        updated_at: 'дата изменения',
    }[key] || 'дополнительное поле';
}

function opsPlusProviderLabel(value) {
    return {
        bank_api: 'Банковский интерфейс',
        telephony_api: 'Интерфейс телефонии',
        bi_export: 'Витрина аналитики',
        one_c: '1С',
        '1c': '1С',
    }[value] || value || 'Провайдер';
}

function opsPlusConnectorTypeLabel(value) {
    return {
        bank: 'Банк',
        telephony: 'Телефония',
        bi: 'Аналитика',
        '1c': '1С',
    }[value] || opsPlusProviderLabel(value);
}

function renderOpsPlusMetricCards(metrics) {
    const priorityKeys = [
        'matrix_coverage_percent',
        'queue_failed',
        'inbound_errors',
        'consistency_alerts',
        'connectors_total',
        'bank_unreconciled',
        'telephony_unlinked',
        'reconciliation_runs',
    ];
    const entries = Object.entries(metrics || {})
        .filter(([key]) => priorityKeys.includes(String(key)))
        .slice(0, 8);
    return (entries.length ? entries : Object.entries(metrics || {}).slice(0, 6)).map(([key, value]) => `
        <div class="metric-card">
            <div class="metric-title">${opsPlusEscape(opsPlusRecoveryLabel(key))}</div>
            <div class="metric-value">${opsPlusEscape(value)}</div>
        </div>
    `).join('');
}

function opsPlusMappingState(item) {
    const percent = Number(item?.coverage_percent || 0);
    const expected = Number(item?.expected_fields_total || 0);
    const mapped = Number(item?.active_mapped_total || 0);
    if (!expected) return { label: 'нет структуры', tone: 'status-archived' };
    if (percent >= 100) return { label: 'готово', tone: 'status-active' };
    if (mapped > 0) return { label: 'частично', tone: 'status-active' };
    return { label: 'не настроено', tone: 'status-overdue' };
}

function opsPlusDirectionLabel(directions = {}) {
    const inbound = Number(directions.inbound || 0);
    const outbound = Number(directions.outbound || 0);
    const both = Number(directions.bidirectional || 0);
    if (both > 0 || (inbound > 0 && outbound > 0)) return 'CRM ↔ 1С';
    if (inbound > 0) return '1С → CRM';
    if (outbound > 0) return 'CRM → 1С';
    return 'Не задано';
}

function renderOpsPlusMappingMatrix(rows = []) {
    const list = (Array.isArray(rows) ? rows : [])
        .filter(item => Number(item.expected_fields_total || 0) > 0);
    const incomplete = list.filter(item => Number(item.coverage_percent || 0) < 100);
    return `
        <div class="ops-plus-section-head">
            <div>
                <h4 class="section-title">Какие данные передаются в 1С</h4>
                <p class="section-subtitle">${incomplete.length ? `Требуют настройки: ${incomplete.length}.` : 'Все разделы настроены.'} Кнопка открывает параметры выбранного раздела и сама ничего не изменяет.</p>
            </div>
        </div>
        <div class="ops-plus-table-shell">
            <table class="ops-plus-table">
                <thead>
                    <tr>
                        <th>Раздел CRM</th>
                        <th>Направление</th>
                        <th>Поля</th>
                        <th>Состояние</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    ${list.length ? list.map(item => {
                        const state = opsPlusMappingState(item);
                        const expected = Number(item.expected_fields_total || 0);
                        const mapped = expected ? Math.min(Number(item.active_mapped_total || 0), expected) : 0;
                        return `
                            <tr>
                                <td><strong>${opsPlusEscape(opsPlusEntityLabel(item.entity_type))}</strong></td>
                                <td>${opsPlusEscape(opsPlusDirectionLabel(item.directions))}</td>
                                <td>${mapped} из ${expected}</td>
                                <td><span class="status-badge ${state.tone}">${state.label}</span></td>
                                <td><button class="btn-secondary" onclick="openIntegrationMappingSettings('${opsPlusJsString(item.entity_type)}')">Настроить</button></td>
                            </tr>
                        `;
                    }).join('') : '<tr><td colspan="5" class="ops-plus-empty-cell">Разделы для обмена пока не найдены.</td></tr>'}
                </tbody>
            </table>
        </div>
    `;
}

function renderOpsPlusAttentionBoard(source = {}) {
    const entries = Object.entries(source || {})
        .filter(([key, value]) => typeof value !== 'object' && Number(value || 0) > 0)
        .filter(([key]) => opsPlusIsAttentionMetric(key))
        .slice(0, 8);
    if (!entries.length) {
        return '<div class="empty-state">Критичных проблем обмена сейчас нет.</div>';
    }
    return `<div class="client360-list" style="margin-top:12px;">${entries.map(([key, value]) => `
        <div class="client360-item ops-plus-attention-row">
            <div>
                <div class="client360-item-title">${opsPlusEscape(opsPlusRecoveryLabel(key))}</div>
                <div class="client360-item-meta">${opsPlusEscape(opsPlusControlGroupLabel(key))}</div>
            </div>
            <div class="metric-value" style="font-size:22px;">${opsPlusEscape(value)}</div>
        </div>
    `).join('')}</div>`;
}

function opsPlusIsAttentionMetric(key) {
    const normalized = String(key || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    return [
        'error',
        'failed',
        'stale',
        'conflict',
        'collision',
        'unreconciled',
        'unlinked',
        'alert',
        'retry_queue',
        'failed_queue',
    ].some(token => normalized.includes(token));
}

function opsPlusMergeAttentionBoards(...boards) {
    const result = {};
    boards.forEach(board => {
        Object.entries(board || {}).forEach(([key, value]) => {
            if (typeof value === 'object' || !opsPlusIsAttentionMetric(key)) return;
            result[key] = Math.max(Number(result[key] || 0), Number(value || 0));
        });
    });
    return result;
}

function renderIntegrationAdvancedSettings(rows = []) {
    const options = (Array.isArray(rows) ? rows : [])
        .filter(item => Number(item.expected_fields_total || 0) > 0)
        .map(item => `<option value="${opsPlusEscape(item.entity_type)}">${opsPlusEscape(opsPlusEntityLabel(item.entity_type))}</option>`)
        .join('');
    return `
        <details id="integrationMappingSettings" class="ops-plus-advanced">
            <summary>
                <span>Настройки выбранного раздела</span>
                <small>Добавление одного поля или недостающих типовых полей</small>
            </summary>
            <div class="ops-plus-settings-form">
                <label>
                    <span>Раздел CRM</span>
                    <select id="integrationMappingEntitySelect" class="auth-input" onchange="selectIntegrationMappingEntity(this.value)">
                        <option value="">Выберите раздел</option>
                        ${options}
                    </select>
                </label>
                <label>
                    <span>Поле в CRM</span>
                    <select id="integrationMapLocal" class="auth-input">
                        <option value="">Сначала выберите раздел</option>
                    </select>
                </label>
                <label>
                    <span>Соответствующее поле в 1С</span>
                    <input id="integrationMapExternal" class="auth-input" placeholder="Например: Номер">
                </label>
                <input id="integrationMapEntity" type="hidden">
                <div class="ops-plus-settings-actions">
                    <button class="btn-primary" onclick="saveIntegrationMapping()">Добавить это поле</button>
                    <button class="btn-secondary" onclick="bootstrapSelectedIntegrationMapping()">Добавить недостающие типовые поля</button>
                </div>
            </div>
        </details>
    `;
}

function opsPlusControlGroupLabel(key) {
    const normalized = String(key || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    if (normalized.includes('production')) return 'Производственный контроль';
    if (normalized.includes('finance') || normalized.includes('bank')) return 'Финансовый контроль';
    if (normalized.includes('telephony')) return 'Телефония';
    if (normalized.includes('idempotency') || normalized.includes('consistency')) return 'Защита от дублей';
    return 'Операторский контроль';
}

function renderOpsPlusList(items, mapFn, emptyText) {
    return Array.isArray(items) && items.length
        ? `<div class="client360-list" style="margin-top:12px;">${items.slice(0, 20).map(mapFn).join('')}</div>`
        : `<div class="empty-state">${emptyText}</div>`;
}

function renderOpsPlusTimeline(items, emptyText) {
    return Array.isArray(items) && items.length
        ? `<div class="client360-list" style="margin-top:12px;">${items.slice(0, 20).map(item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${opsPlusEscape(item.title || 'Событие')}</div>
                    <div class="client360-item-meta">${opsPlusEscape(item.meta || '')}</div>
                </div>
                <div class="view-actions">
                    ${opsPlusStatusBadge(item.status || item.kind || 'logged')}
                    ${item.document_id ? `<button class="btn-secondary" onclick="focusDocumentFromTimeline(${Number(item.document_id)})">К документу</button>` : ''}
                </div>
            </div>
        `).join('')}</div>`
        : `<div class="empty-state">${emptyText}</div>`;
}

async function loadDocflowPlusData() {
    const data = await apiCall('/docflow/plus_summary');
    docflowPlusDB = data && !data.error ? data : null;
    return docflowPlusDB;
}

async function loadIntegrationPlusData() {
    const data = await apiCall('/integration/plus_summary');
    integrationPlusDB = data && !data.error ? data : null;
    return integrationPlusDB;
}

async function loadSecurityPlusData() {
    const data = await apiCall('/security/plus_summary');
    securityPlusDB = data && !data.error ? data : null;
    return securityPlusDB;
}

function renderDocflowPlusMount() {
    const mount = document.getElementById('docflowPlusMount');
    if (!mount || !docflowPlusDB) return;
    const docs = Array.isArray(documentsDB) ? documentsDB : [];
    const templates = docflowPlusDB.templates || [];
    const selectedDocumentId = Number(docflowTimelineState?.document_id || docflowPlusDB.coverage_gaps?.[0]?.document_id || docs[0]?.id || 0);
    const docOptions = docs.map(doc => `<option value="${doc.id}">${opsPlusEscape(doc.number || doc.id)} · ${opsPlusEscape(doc.subject || 'Без темы')}</option>`).join('');
    const templateOptions = templates.map(item => `<option value="${item.id}">${opsPlusEscape(item.title || `Шаблон ${item.id}`)}</option>`).join('');
    const metrics = docflowPlusDB.metrics || {};
    const cleanDocflowText = value => String(value || '')
        .replace(/DEMO-DOC/gi, 'ДОК')
        .replace(/DEMO/gi, 'Пример')
        .replace(/Demo/gi, 'Пример')
        .replace(/Демо/gi, 'Пример');
    const docTypeLabel = value => ({
        incoming: 'Входящий документ',
        outgoing: 'Исходящий документ',
        internal: 'Внутренний документ',
        internal_order: 'Приказ',
        internal_memo: 'Служебная записка',
        contract: 'Договор',
        invoice: 'Счет',
        act: 'Акт',
        upd: 'УПД',
    }[value] || cleanDocflowText(value) || 'Документ');
    const metricValue = (key, fallback = 0) => Number(metrics[key] ?? fallback ?? 0);
    const attentionItems = [
        ...(docflowPlusDB.legal_card_gaps || []).map(item => ({
            title: `Заполнить юридическую карточку ${cleanDocflowText(item.number || item.document_id)}`,
            meta: `Не хватает: ${cleanDocflowText((item.missing_legal || []).join(', ') || 'обязательных реквизитов')}`,
            document_id: item.document_id,
        })),
        ...(docflowPlusDB.file_revision_gaps || []).map(item => ({
            title: `Проверить файл ${cleanDocflowText(item.number || item.document_id)}`,
            meta: cleanDocflowText(item.history_gap_reason || 'Нет полной истории версий файла'),
            document_id: item.document_id,
        })),
        ...(docflowPlusDB.signature_gaps || []).map(item => ({
            title: `Проверить подпись ${cleanDocflowText(item.number || item.document_id)}`,
            meta: cleanDocflowText(item.gap_reason || 'Нет подтвержденной электронной подписи'),
            document_id: item.document_id,
        })),
        ...(docflowPlusDB.workflow_gaps || []).map(item => ({
            title: `Запустить маршрут ${cleanDocflowText(item.number || item.document_id)}`,
            meta: cleanDocflowText(item.block_reason || 'Документ не прошел рабочий маршрут'),
            document_id: item.document_id,
        })),
        ...(docflowPlusDB.retention_policy_gaps || []).map(item => ({
            title: `Назначить срок хранения ${cleanDocflowText(item.number || item.document_id)}`,
            meta: cleanDocflowText(item.gap_reason || 'Не настроена политика хранения'),
            document_id: item.document_id,
        })),
    ];
    const templateRows = (docflowPlusDB.template_catalog || []).slice(0, 5);
    const timelineRows = (docflowTimelineState?.timeline || docflowPlusDB.timeline || []).slice(0, 5);
    const problemCount = attentionItems.length + (docflowPlusDB.doc_typing_issues || []).length;
    mount.innerHTML = `
        <div class="surface-card surface-card--padded docflow-clean-panel">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Документы и ЭДО</h3>
                    <p class="section-subtitle">Рабочая сводка по документам: реестр, шаблоны, подписи, печатные формы и архив без технических счетчиков.</p>
                </div>
                <div class="view-actions">
                    <button class="btn-secondary" onclick="reloadDocflowPlus()">Обновить</button>
                </div>
            </div>
            <div class="docflow-clean-metrics">
                <div class="metric-card"><div class="metric-title">Документы в реестре</div><div class="metric-value">${opsPlusEscape(metricValue('documents_total', docs.length))}</div><div class="metric-caption">карточки и вложения</div></div>
                <div class="metric-card"><div class="metric-title">Шаблоны</div><div class="metric-value">${opsPlusEscape(metricValue('templates_total', templates.length))}</div><div class="metric-caption">печатные формы и маршруты</div></div>
                <div class="metric-card"><div class="metric-title">Активные сертификаты</div><div class="metric-value">${opsPlusEscape(metricValue('certificates_active'))}</div><div class="metric-caption">для подписи ЭДО</div></div>
                <div class="metric-card"><div class="metric-title">Нужно проверить</div><div class="metric-value">${opsPlusEscape(problemCount)}</div><div class="metric-caption">пробелы перед работой</div></div>
            </div>
            <div class="docflow-clean-grid">
                <div class="docflow-clean-section">
                    <h4 class="section-title" style="font-size:16px;">Что проверить</h4>
                    ${attentionItems.length ? `
                        <div class="client360-list" style="margin-top:12px;">
                            ${attentionItems.slice(0, 6).map(item => `
                                <div class="client360-item">
                                    <div>
                                        <div class="client360-item-title">${opsPlusEscape(item.title)}</div>
                                        <div class="client360-item-meta">${opsPlusEscape(item.meta)}</div>
                                    </div>
                                    <div class="view-actions">
                                        ${opsPlusStatusBadge('attention')}
                                        ${item.document_id ? `<button class="btn-secondary" onclick="focusDocumentFromTimeline(${Number(item.document_id)})">Открыть</button>` : ''}
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    ` : '<div class="empty-state">Критичных проблем по документам сейчас нет.</div>'}
                </div>
                <div class="docflow-clean-section">
                    <h4 class="section-title" style="font-size:16px;">Шаблоны и печать</h4>
                    ${templateRows.length ? `
                        <div class="client360-list" style="margin-top:12px;">
                            ${templateRows.map(item => `
                                <div class="client360-item">
                                    <div>
                                        <div class="client360-item-title">${opsPlusEscape(docTypeLabel(item.doc_type || item.doc_type_label))}</div>
                                        <div class="client360-item-meta">Шаблонов ${opsPlusEscape(item.templates_total || 0)} · активных ${opsPlusEscape(item.active_total || 0)} · последняя версия ${opsPlusEscape(cleanDocflowText(item.latest_version || 'не задана'))}</div>
                                    </div>
                                    <div class="metric-value" style="font-size:20px;">${opsPlusEscape(item.coverage_percent || 0)}%</div>
                                </div>
                            `).join('')}
                        </div>
                    ` : '<div class="empty-state">Шаблоны документов пока не настроены.</div>'}
                </div>
                <div class="docflow-clean-section">
                    <h4 class="section-title" style="font-size:16px;">История документов</h4>
                    ${renderOpsPlusTimeline(timelineRows.map(item => ({
                        ...item,
                        title: cleanDocflowText(item.title || item.number || 'Событие'),
                        meta: cleanDocflowText(item.meta || item.description || ''),
                    })), 'История документов пока пуста.')}
                </div>
                <div class="docflow-clean-section">
                    <h4 class="section-title" style="font-size:16px;">Быстрые действия</h4>
                    <p class="section-subtitle" style="margin-bottom:12px;">Выбери документ, чтобы посмотреть историю, собрать печатные формы или перейти к карточке.</p>
                    <div class="view-actions">
                        <select id="docflowTimelineDocumentId" class="auth-input" style="margin:0; min-width:280px;">
                            <option value="0">Выбери документ</option>${docOptions}
                        </select>
                        <button class="btn-secondary" onclick="loadDocflowDocumentTimeline()">История</button>
                        <button class="btn-secondary" onclick="generateDocflowPrintSet()">Печатные формы</button>
                    </div>
                    <details class="docflow-admin-actions">
                        <summary>Сервисные настройки</summary>
                        <div class="finance-form-grid" style="margin-top:12px;">
                            <input id="docflowTemplateTitle" class="auth-input" style="margin:0;" placeholder="Название шаблона">
                            <select id="docflowTemplateType" class="auth-input" style="margin:0;"><option value="incoming">Входящий</option><option value="outgoing">Исходящий</option><option value="internal_order">Приказ</option><option value="internal_memo">Служебная записка</option></select>
                            <input id="docflowTemplateVersion" class="auth-input" style="margin:0;" placeholder="Версия">
                            <button class="btn-primary" onclick="saveDocflowTemplate()">Сохранить шаблон</button>
                            <select id="docflowVersionDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ для версии</option>${docOptions}</select>
                            <input id="docflowVersionLabel" class="auth-input" style="margin:0;" placeholder="Метка версии">
                            <button class="btn-secondary" onclick="saveDocflowVersion()">Сохранить версию</button>
                            <select id="docflowPrintDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ для печати</option>${docOptions}</select>
                            <select id="docflowPrintTemplateId" class="auth-input" style="margin:0;"><option value="0">Шаблон печати</option>${templateOptions}</select>
                            <select id="docflowPrintFormat" class="auth-input" style="margin:0;"><option value="pdf">PDF</option><option value="docx">DOCX</option></select>
                            <button class="btn-secondary" onclick="saveDocflowPrintForm()">Добавить печатную форму</button>
                        </div>
                    </details>
                </div>
            </div>
        </div>
    `;
    const cleanTimelineSelect = document.getElementById('docflowTimelineDocumentId');
    if (cleanTimelineSelect && selectedDocumentId) {
        cleanTimelineSelect.value = String(selectedDocumentId);
    }
    return;
    mount.innerHTML = `
        <div class="surface-card surface-card--padded">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Документооборот и ЭДО+</h3>
                    <p class="section-subtitle">Каталог шаблонов, версии карточек, связанные поручения, сертификаты, архив юрзначимых документов и печатные формы PDF/DOCX.</p>
                </div>
                <div class="view-actions"><button class="btn-secondary" onclick="reloadDocflowPlus()">Обновить</button></div>
            </div>
            <div class="metrics-grid">${renderOpsPlusMetricCards(docflowPlusDB.metrics)}</div>
            <div class="system-ops-grid" style="margin-top:18px;">
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">Юридическая карточка</h4>
                    ${renderOpsPlusList(docflowPlusDB.legal_card_board, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.registration_number || item.number || item.document_id)} · ${opsPlusEscape(item.subject || 'Без темы')}</div>
                                <div class="client360-item-meta">${opsPlusEscape(item.classifier_name || 'без классификатора')} · дело ${opsPlusEscape(item.case_index || 'не назначено')} · хранить до ${opsPlusEscape(item.retention_until || 'не задано')}</div>
                            </div>
                            <div class="view-actions">${opsPlusStatusBadge(item.lifecycle_state || 'draft')}${opsPlusStatusBadge(item.quality_status || 'incomplete')}</div>
                        </div>
                    `, 'Юридические карточки пока не оформлены.')}
                    ${renderOpsPlusList(docflowPlusDB.legal_card_gaps, item => `<div class="client360-item"><div><div class="client360-item-title">Пробел: ${opsPlusEscape(item.number || item.document_id)}</div><div class="client360-item-meta">не хватает: ${opsPlusEscape((item.missing_legal || []).join(', '))}</div></div><div>${opsPlusStatusBadge('attention')}</div></div>`, 'Пробелов юридической карточки сейчас нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">Версии файлов</h4>
                    ${renderOpsPlusList(docflowPlusDB.file_revision_board, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.active_revision_label || 'нет активной ревизии')} · ${opsPlusEscape(item.number || item.document_id)}</div>
                                <div class="client360-item-meta">${opsPlusEscape(item.active_filename || 'история не заведена')} · ${opsPlusEscape(item.size_label || 'размер не определен')} · ревизий ${opsPlusEscape(item.revisions_total || 0)}</div>
                            </div>
                            <div class="view-actions">${opsPlusStatusBadge(item.revision_status || 'draft')}${item.is_current ? opsPlusStatusBadge('active') : ''}</div>
                        </div>
                    `, 'Файловые ревизии документов пока не ведутся.')}
                    ${renderOpsPlusList(docflowPlusDB.file_revision_gaps, item => `<div class="client360-item"><div><div class="client360-item-title">Пробел: ${opsPlusEscape(item.number || item.document_id)}</div><div class="client360-item-meta">${opsPlusEscape(item.history_gap_reason || 'история файлов неполная')}</div></div><div>${opsPlusStatusBadge('attention')}</div></div>`, 'Пробелов по файловым ревизиям сейчас нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">ЭП и юридическая значимость</h4>
                    ${renderOpsPlusList(docflowPlusDB.signature_board, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.number || item.document_id)} · ${opsPlusEscape(item.signature_kind || 'подпись не задана')}</div>
                                <div class="client360-item-meta">${opsPlusEscape(item.signer_name || 'подписант не указан')} · ${opsPlusEscape(item.signature_display_status || 'нет действительной подписи')} · текущая версия ${opsPlusEscape(item.current_revision_valid_signatures_total || 0)} · архивных записей ${opsPlusEscape(item.archive_total || 0)} · отпечаток ${opsPlusEscape(item.thumbprint_short || 'нет')}</div>
                            </div>
                            <div class="view-actions">${opsPlusStatusBadge(item.verification_status || 'pending')}${opsPlusStatusBadge(item.legal_force || 'unsigned')}</div>
                        </div>
                    `, 'Юридически значимые подписи документов пока не ведутся.')}
                    ${renderOpsPlusList(docflowPlusDB.signature_gaps, item => `<div class="client360-item"><div><div class="client360-item-title">Пробел: ${opsPlusEscape(item.number || item.document_id)}</div><div class="client360-item-meta">${opsPlusEscape(item.gap_reason || 'контур ЭП неполный')}</div></div><div>${opsPlusStatusBadge('attention')}</div></div>`, 'Пробелов по ЭП и юридической значимости сейчас нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">Сквозной маршрут документа</h4>
                    ${renderOpsPlusList(docflowPlusDB.workflow_board, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.number || item.document_id)} · ${opsPlusEscape(item.subject || 'Без темы')}</div>
                                <div class="client360-item-meta">этап: ${opsPlusEscape(opsPlusStatusLabel(item.workflow_stage || 'incoming'))} · готовность ${opsPlusEscape(item.progress_percent || 0)}% · согласование: ${opsPlusEscape(opsPlusStatusLabel(item.approval_status || 'pending'))} · архив: ${opsPlusEscape(opsPlusStatusLabel(item.archive_status || 'not_started'))}</div>
                            </div>
                            <div class="view-actions">${opsPlusStatusBadge(item.workflow_status || 'idle')}</div>
                        </div>
                    `, 'Сквозные маршруты документов пока не запущены.')}
                    ${renderOpsPlusList(docflowPlusDB.workflow_gaps, item => `<div class="client360-item"><div><div class="client360-item-title">Пробел: ${opsPlusEscape(item.number || item.document_id)}</div><div class="client360-item-meta">${opsPlusEscape(item.block_reason || 'маршрут остановлен')}</div></div><div>${opsPlusStatusBadge('attention')}</div></div>`, 'Блокеров по сквозному маршруту сейчас нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">Хранение и архивная политика</h4>
                    ${renderOpsPlusList(docflowPlusDB.retention_policy_board, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.number || item.document_id)} · ${opsPlusEscape(item.policy_name || 'policy не назначена')}</div>
                                <div class="client360-item-meta">хранить до ${opsPlusEscape(item.retention_until || 'не задано')} · дней осталось ${opsPlusEscape(item.days_left === null || item.days_left === undefined ? 'n/a' : item.days_left)} · роли ${opsPlusEscape((item.allowed_roles || []).join(', ') || 'не ограничено')}</div>
                            </div>
                            <div class="view-actions">${opsPlusStatusBadge(item.status || 'not_configured')}${item.archive_status ? opsPlusStatusBadge(item.archive_status) : ''}</div>
                        </div>
                    `, 'Политики хранения пока не настроены.')}
                    ${renderOpsPlusList(docflowPlusDB.retention_policy_gaps, item => `<div class="client360-item"><div><div class="client360-item-title">Пробел: ${opsPlusEscape(item.number || item.document_id)}</div><div class="client360-item-meta">${opsPlusEscape(item.gap_reason || 'контур хранения неполный')}</div></div><div>${opsPlusStatusBadge('attention')}</div></div>`, 'Пробелов по политике хранения сейчас нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">Структура и строгая типизация</h4>
                    <div class="client360-list" style="margin-top:12px;">
                        ${Object.entries(docflowPlusDB.strict_type_breakdown || {}).map(([key, value]) => `
                            <div class="client360-item">
                                <div>
                                    <div class="client360-item-title">${opsPlusEscape(key)}</div>
                                    <div class="client360-item-meta">Документов в строгом типе</div>
                                </div>
                                <div class="metric-value" style="font-size:22px;">${opsPlusEscape(value)}</div>
                            </div>
                        `).join('') || '<div class="empty-state">Структура документов пока не сформирована.</div>'}
                    </div>
                    ${renderOpsPlusList(docflowPlusDB.doc_typing_issues, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">№${opsPlusEscape(item.number || item.document_id)} · ${opsPlusEscape(item.subject || 'Без темы')}</div>
                                <div class="client360-item-meta">исходный тип: ${opsPlusEscape(item.raw_type)} · предложенный тип: ${opsPlusEscape(item.suggested_type)}</div>
                            </div>
                            <div class="view-actions">
                                ${opsPlusStatusBadge('typing_gap')}
                                <button class="btn-secondary" onclick="focusDocumentFromTimeline(${Number(item.document_id)})">К документу</button>
                            </div>
                        </div>
                    `, 'Проблем типизации сейчас нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">Каталог шаблонов и покрытие</h4>
                    ${renderOpsPlusList(docflowPlusDB.template_catalog, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.doc_type_label)}</div>
                                <div class="client360-item-meta">Шаблонов ${item.templates_total} · активных ${item.active_total} · последняя ${opsPlusEscape(item.latest_version)}</div>
                            </div>
                            <div class="metric-value" style="font-size:20px;">${opsPlusEscape(item.coverage_percent)}%</div>
                        </div>
                    `, 'Каталог шаблонов пока пуст.')}
                    ${renderOpsPlusList(docflowPlusDB.template_families, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.title || item.family_key)}</div>
                                <div class="client360-item-meta">${opsPlusEscape(item.doc_type_label)} · версий ${item.versions_total} · последняя ${opsPlusEscape(item.latest_version)}</div>
                            </div>
                            <div>${opsPlusStatusBadge(item.statuses?.[0] || 'draft')}</div>
                        </div>
                    `, 'Семейства шаблонов пока не сформированы.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">OCR и распознавание</h4>
                    <p class="section-subtitle" style="margin-bottom:10px;">Юрист видит распознанные поля, уверенность и применение OCR к карточке документа.</p>
                    ${renderOpsPlusList(docflowPlusDB.ocr_jobs, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">Документ #${opsPlusEscape(item.document_id || 0)} · ${opsPlusEscape(item.extracted_fields?.number || item.source_file || 'OCR')}</div>
                                <div class="client360-item-meta">${opsPlusEscape(item.extracted_fields?.correspondent || 'корреспондент не найден')} · ${opsPlusEscape(item.extracted_fields?.subject || 'тема не найдена')} · уверенность ${opsPlusEscape(item.confidence || 0)}</div>
                            </div>
                            <div class="view-actions">${opsPlusStatusBadge(item.status || 'queued')}<button class="btn-secondary" onclick="processDocflowOcrJob(${Number(item.id)})">Повторить</button></div>
                        </div>
                    `, 'OCR-задач пока нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded">
                    <h4 class="section-title" style="font-size:16px;">Шаблонные потоки</h4>
                    <p class="section-subtitle" style="margin-bottom:10px;">Правила входящих/исходящих потоков: направление, обязательные поля, шаблоны и запуск печатного комплекта.</p>
                    ${renderOpsPlusList(docflowPlusDB.template_flows, item => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(item.flow_name || item.flow_code || 'Поток')}</div>
                                <div class="client360-item-meta">${opsPlusEscape(item.direction || 'incoming')} · ${opsPlusEscape(item.doc_type || 'document')} · шаблонов ${(item.template_ids || []).length} · обязательных ${(item.required_fields || []).length}</div>
                            </div>
                            <div class="view-actions">${opsPlusStatusBadge(item.status || 'active')}<button class="btn-secondary" onclick="applyDocflowTemplateFlow(${Number(item.id)})">Применить</button></div>
                        </div>
                    `, 'Шаблонных потоков пока нет.')}
                </div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded" style="margin-top:16px;">
                <h4 class="section-title" style="font-size:16px;">Операции с документами</h4>
                <p class="section-subtitle" style="margin-bottom:10px;">Быстрое создание шаблона, версии, поручения, архива и печатных форм с полным покрытием PDF/DOCX.</p>
                <div class="view-actions" style="margin-bottom:12px;">
                    <select id="docflowTimelineDocumentId" class="auth-input" style="margin:0; min-width:300px;">
                        <option value="0">Документ для истории и печатных форм</option>${docOptions}
                    </select>
                    <button class="btn-secondary" onclick="loadDocflowDocumentTimeline()">История</button>
                    <button class="btn-secondary" onclick="generateDocflowPrintSet()">Печатные формы</button>
                </div>
                <div class="client360-list" style="margin-top:12px;">
                    ${Object.entries(docflowPlusDB.type_breakdown || {}).map(([key, value]) => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${opsPlusEscape(key)}</div>
                                <div class="client360-item-meta">исходный тип документов</div>
                            </div>
                            <div class="metric-value" style="font-size:22px;">${opsPlusEscape(value)}</div>
                        </div>
                    `).join('') || '<div class="empty-state">Структура документов пока не сформирована.</div>'}
                </div>
            </div>
            <div class="finance-form-grid" style="margin-top:16px;">
                <input id="docflowTemplateTitle" class="auth-input" style="margin:0;" placeholder="Шаблон документа">
                <select id="docflowTemplateType" class="auth-input" style="margin:0;"><option value="incoming">Входящий</option><option value="outgoing">Исходящий</option><option value="internal_order">Внутренний приказ</option><option value="internal_memo">Внутренняя записка</option></select>
                <input id="docflowTemplateVersion" class="auth-input" style="margin:0;" placeholder="Версия шаблона">
                <button class="btn-primary" onclick="saveDocflowTemplate()">Шаблон</button>
                <select id="docflowVersionDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ для версии</option>${docOptions}</select>
                <input id="docflowVersionLabel" class="auth-input" style="margin:0;" placeholder="Метка версии">
                <button class="btn-secondary" onclick="saveDocflowVersion()">Версия</button>
                <button class="btn-secondary" onclick="snapshotDocflowVersion()">Снимок</button>
                <select id="docflowTaskDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ для поручения</option>${docOptions}</select>
                <input id="docflowTaskTitle" class="auth-input" style="margin:0;" placeholder="Поручение">
                <input id="docflowTaskAssignee" class="auth-input" style="margin:0;" placeholder="Исполнитель">
                <input id="docflowTaskDeadline" class="auth-input" style="margin:0;" placeholder="Срок">
                <button class="btn-secondary" onclick="saveDocflowTask()">Поручение</button>
                <input id="docflowCertOwner" class="auth-input" style="margin:0;" placeholder="Владелец сертификата">
                <input id="docflowCertEmail" class="auth-input" style="margin:0;" placeholder="Эл. почта сертификата">
                <input id="docflowCertRole" class="auth-input" style="margin:0;" placeholder="Роль подписанта">
                <button class="btn-secondary" onclick="saveDocflowCertificate()">Сертификат</button>
                <select id="docflowArchiveDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ в архив</option>${docOptions}</select>
                <input id="docflowArchiveRetention" class="auth-input" style="margin:0;" placeholder="Хранить до">
                <input id="docflowArchivePath" class="auth-input" style="margin:0;" placeholder="Путь архива">
                <button class="btn-secondary" onclick="saveDocflowArchive()">Архив</button>
                <select id="docflowPrintDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ для печати</option>${docOptions}</select>
                <select id="docflowPrintTemplateId" class="auth-input" style="margin:0;"><option value="0">Шаблон печати</option>${templateOptions}</select>
                <select id="docflowPrintFormat" class="auth-input" style="margin:0;"><option value="pdf">PDF</option><option value="docx">DOCX</option></select>
                <button class="btn-secondary" onclick="saveDocflowPrintForm()">Печатная форма</button>
                <select id="docflowOcrDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ для OCR</option>${docOptions}</select>
                <select id="docflowOcrTemplateId" class="auth-input" style="margin:0;"><option value="0">Шаблон OCR</option>${templateOptions}</select>
                <input id="docflowOcrText" class="auth-input" style="margin:0; grid-column:1 / -1;" placeholder="Текст OCR: Входящий № 15 от ООО Ромашка ИНН ... тема ... сумма ...">
                <button class="btn-primary" onclick="createDocflowOcrJob()">OCR и применить</button>
                <input id="docflowTemplateFlowName" class="auth-input" style="margin:0;" placeholder="Название потока">
                <select id="docflowTemplateFlowDirection" class="auth-input" style="margin:0;"><option value="incoming">Входящий</option><option value="outgoing">Исходящий</option><option value="internal">Внутренний</option></select>
                <input id="docflowTemplateFlowDocType" class="auth-input" style="margin:0;" placeholder="Тип документа">
                <select id="docflowTemplateFlowTemplateId" class="auth-input" style="margin:0;"><option value="0">Шаблон потока</option>${templateOptions}</select>
                <select id="docflowTemplateFlowDocumentId" class="auth-input" style="margin:0;"><option value="0">Документ для потока</option>${docOptions}</select>
                <button class="btn-secondary" onclick="createDocflowTemplateFlow()">Поток</button>
            </div>
            <div class="system-ops-grid" style="margin-top:18px;">
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Шаблоны</h4>${renderOpsPlusList(docflowPlusDB.templates, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.title)}</div><div class="client360-item-meta">${opsPlusEscape(item.doc_type)} · ${opsPlusEscape(item.version_label)}</div></div><div class="view-actions">${opsPlusStatusBadge(item.status)}<button class="btn-secondary" onclick="applyDocflowTemplateToModal(${item.id})">В документ</button><button class="btn-danger" onclick="deleteDocflowTemplate(${item.id})">Удалить</button></div></div>`, 'Шаблонов пока нет.')}</div>
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Версии и сравнение</h4>${renderOpsPlusList(docflowPlusDB.versions, item => `<div class="client360-item"><div><div class="client360-item-title">Документ #${item.document_id} · ${opsPlusEscape(item.version_label || `v${item.version_no || 1}`)}</div><div class="client360-item-meta">${opsPlusEscape(item.comment || 'Версия карточки')} · изменений ${item.change_count || 0}</div></div><div class="view-actions">${opsPlusStatusBadge(item.version_status)}<button class="btn-secondary" onclick="showDocflowVersionDiff(${item.id})">Сравнить</button><button class="btn-danger" onclick="deleteDocflowVersion(${item.id})">Удалить</button></div></div>`, 'Версий пока нет.')}
                    ${docflowVersionDiffState ? `<div class="surface-card surface-card--padded" style="margin-top:12px;"><div class="section-header"><div><h4 class="section-title" style="font-size:15px;">Сравнение ${opsPlusEscape(docflowVersionDiffState.version_label || '')}</h4><p class="section-subtitle">Изменений: ${opsPlusEscape(docflowVersionDiffState.change_count || 0)}</p></div><div class="view-actions"><button class="btn-secondary" onclick="clearDocflowVersionDiff()">Скрыть</button></div></div>${renderOpsPlusList(docflowVersionDiffState.diff_items, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.field_name)}</div><div class="client360-item-meta">было: ${opsPlusEscape(item.before)} · стало: ${opsPlusEscape(item.after)}</div></div></div>`, 'Изменений относительно прошлой версии нет.')}</div>` : ''}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Поручения</h4>${renderOpsPlusList(docflowPlusDB.linked_tasks, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.title)}</div><div class="client360-item-meta">Документ #${item.document_id} · ${opsPlusEscape(item.assignee_name || 'не назначен')}</div></div><div class="view-actions">${opsPlusStatusBadge(item.status)}<button class="btn-danger" onclick="deleteDocflowTask(${item.id})">Удалить</button></div></div>`, 'Связанных поручений пока нет.')}</div>
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Сертификаты и архив</h4>${renderOpsPlusList([...(docflowPlusDB.certificates || []), ...(docflowPlusDB.legal_archive_board || [])], item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.owner_email || item.archive_code || 'Архив')}</div><div class="client360-item-meta">${opsPlusEscape(item.provider_name || item.storage_path || '')}${item.retention_until ? ` · хранить до ${opsPlusEscape(item.retention_until)}` : ''}</div></div><div>${opsPlusStatusBadge(item.status || item.archive_status)}</div></div>`, 'Сертификатов и архива пока нет.')}
                    ${renderOpsPlusList(docflowPlusDB.archive_risks, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.archive_code || item.document_number)}</div><div class="client360-item-meta">${opsPlusEscape(item.document_subject || '')} · до ${opsPlusEscape(item.retention_until)}</div></div><div>${opsPlusStatusBadge((item.days_left || 0) < 0 ? 'overdue' : 'attention')}</div></div>`, 'Критичных рисков архива сейчас нет.')}
                </div>
            </div>
            <div class="system-ops-grid" style="margin-top:18px;">
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Печатные формы и покрытие</h4>${renderOpsPlusList(docflowPlusDB.print_coverage, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.doc_type_label)}</div><div class="client360-item-meta">Документов ${item.documents_total} · c печатью ${item.with_print_forms}</div></div><div class="metric-value" style="font-size:20px;">${opsPlusEscape(item.coverage_percent)}%</div></div>`, 'Покрытие печатных форм пока не рассчитано.')}
                    ${renderOpsPlusList(docflowPlusDB.print_format_matrix, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.doc_type_label)}</div><div class="client360-item-meta">PDF ${item.pdf_total} · DOCX ${item.docx_total}</div></div><div>${opsPlusStatusBadge(item.missing_print_forms > 0 ? 'gap' : 'covered')}</div></div>`, 'Матрица печатных форм пока пуста.')}
                    ${renderOpsPlusList(docflowPlusDB.print_forms, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.form_name || 'Печатная форма')}</div><div class="client360-item-meta">Документ #${item.document_id} · ${opsPlusEscape(item.format_type)}</div></div><div class="view-actions">${opsPlusStatusBadge(item.status)}<button class="btn-danger" onclick="deleteDocflowPrintForm(${item.id})">Удалить</button></div></div>`, 'Печатных форм пока нет.')}
                </div>
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Пробелы покрытия и история</h4>${renderOpsPlusList(docflowPlusDB.coverage_gaps, item => `<div class="client360-item"><div><div class="client360-item-title">№${opsPlusEscape(item.number || item.document_id)} · ${opsPlusEscape(item.doc_type_label)}</div><div class="client360-item-meta">${opsPlusEscape(item.subject || 'Без темы')} · не хватает: ${opsPlusEscape((item.missing || []).join(', '))}</div></div><div class="view-actions"><button class="btn-secondary" onclick="loadDocflowDocumentTimeline(${Number(item.document_id)})">История</button><button class="btn-secondary" onclick="generateDocflowPrintSet(${Number(item.document_id)})">Печатные формы</button></div></div>`, 'Пробелов покрытия сейчас нет.')}
                    <div class="surface-card surface-card--padded" style="margin-top:12px;">
                        <div class="section-header">
                            <div>
                                <h4 class="section-title" style="font-size:15px;">История документа</h4>
                                <p class="section-subtitle">${selectedDocumentId ? `Документ #${selectedDocumentId}` : 'Выбери документ выше'}</p>
                            </div>
                        </div>
                        ${renderOpsPlusTimeline(docflowTimelineState?.timeline || docflowPlusDB.timeline, 'Документная лента пока пуста.')}
                    </div>
                </div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded" style="margin-top:18px;"><h4 class="section-title" style="font-size:16px;">Общая лента документа</h4>${renderOpsPlusTimeline(docflowPlusDB.timeline, 'Документная лента пока пуста.')}</div>
        </div>
    `;
    const timelineSelect = document.getElementById('docflowTimelineDocumentId');
    if (timelineSelect && selectedDocumentId) {
        timelineSelect.value = String(selectedDocumentId);
    }
}

function renderIntegrationPlusMount() {
    const mount = document.getElementById('integrationPlusMount');
    if (!mount || !integrationPlusDB) return;
    const mappings = Array.isArray(integrationPlusDB.mapping_matrix) ? integrationPlusDB.mapping_matrix : [];
    const supportedMappings = mappings.filter(item => Number(item.expected_fields_total || 0) > 0);
    const totalSections = supportedMappings.length;
    const readySections = supportedMappings.filter(item => Number(item.coverage_percent || 0) >= 100).length;
    const incompleteSections = supportedMappings.filter(item => Number(item.coverage_percent || 0) < 100).length;
    const operatorBoard = integrationPlusDB.operator_recovery_board || {};
    const qualityBoard = integrationPlusDB.production_quality || {};
    const attentionBoard = {
        failed_queue: Number(operatorBoard.failed_queue || 0),
        retry_queue: Number(operatorBoard.retry_queue || 0),
        stale_processing: Math.max(Number(operatorBoard.stale_processing || 0), Number(qualityBoard.stale_processing || 0)),
        recent_conflicts: Number(operatorBoard.recent_conflicts || 0),
        inbound_errors: Number(operatorBoard.inbound_errors || 0),
        production_open_errors: Math.max(Number(operatorBoard.production_open_errors || 0), Number(qualityBoard.open_errors || 0)),
        idempotency_collisions: Math.max(Number(operatorBoard.idempotency_collisions || 0), Number(qualityBoard.idempotency_collisions || 0)),
        consistency_alerts: Math.max(Number(operatorBoard.consistency_alerts || 0), Number(qualityBoard.consistency_alerts || 0)),
    };
    const exchangeErrors = Number(attentionBoard.failed_queue || 0)
        + Number(attentionBoard.inbound_errors || 0)
        + Number(attentionBoard.production_open_errors || 0);
    const consistencyIssues = Number(attentionBoard.consistency_alerts || 0);
    mount.innerHTML = `
        <section class="ops-plus-workspace">
            <div class="ops-plus-workspace-head">
                <div>
                    <h3 class="section-title">Настройка обмена с 1С</h3>
                    <p class="section-subtitle">Здесь видно, какие данные CRM передаёт в 1С и какие разделы ещё нужно настроить.</p>
                </div>
                <button class="btn-secondary" onclick="reloadIntegrationPlus()">Обновить данные</button>
            </div>
            <div class="ops-plus-summary-grid">
                <div class="ops-plus-summary-item"><span>Настроено разделов</span><strong>${readySections} из ${totalSections}</strong></div>
                <div class="ops-plus-summary-item"><span>Требуют настройки</span><strong>${incompleteSections}</strong></div>
                <div class="ops-plus-summary-item"><span>Ошибки обмена</span><strong>${exchangeErrors}</strong></div>
                <div class="ops-plus-summary-item"><span>Несовпадения данных</span><strong>${consistencyIssues}</strong></div>
            </div>
            <div class="ops-plus-main-grid">
                <div class="ops-plus-main-column">
                    ${renderOpsPlusMappingMatrix(mappings)}
                    ${renderIntegrationAdvancedSettings(mappings)}
                </div>
                <aside class="ops-plus-attention-panel">
                    <h4 class="section-title">Что нужно исправить</h4>
                    <p class="section-subtitle">Только ошибки, конфликты и зависшие операции.</p>
                    ${renderOpsPlusAttentionBoard(attentionBoard)}
                </aside>
            </div>
            <details class="ops-plus-advanced ops-plus-advanced--journal">
                <summary>
                    <span>Журнал для администратора</span>
                    <small>Подробные записи обмена, подключения и результаты сверки</small>
                </summary>
                <div class="system-ops-grid">
                    <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Сопоставленные поля</h4>${renderOpsPlusList(integrationPlusDB.mappings, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(opsPlusEntityLabel(item.entity_type))}</div><div class="client360-item-meta">${opsPlusEscape(opsPlusFieldLabel(item.local_field))} → ${opsPlusEscape(opsPlusFieldLabel(item.external_field))}</div></div><div class="view-actions">${opsPlusStatusBadge(item.direction)}<button class="btn-danger" onclick="deleteIntegrationMapping(${item.id})">Удалить</button></div></div>`, 'Сопоставление полей пока не настроено.')}</div>
                    <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Входящие обновления</h4>${renderOpsPlusList(integrationPlusDB.inbound_updates, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(opsPlusEntityLabel(item.entity_type))} #${item.entity_id}</div><div class="client360-item-meta">${opsPlusEscape(item.external_id || 'без external_id')} · ${opsPlusEscape(opsPlusStatusLabel(item.apply_mode || 'apply'))}</div></div><div class="view-actions">${opsPlusStatusBadge(item.apply_status)}<button class="btn-secondary" onclick="previewIntegrationInbound(${item.id})">Посмотреть</button><button class="btn-secondary" onclick="applyIntegrationInbound(${item.id})">Применить</button><button class="btn-danger" onclick="deleteIntegrationInbound(${item.id})">Удалить</button></div></div>`, 'Входящих обновлений пока нет.')}
                        ${integrationInboundPreviewState ? `<div class="surface-card surface-card--padded" style="margin-top:12px;"><div class="section-header"><div><h4 class="section-title" style="font-size:15px;">Предпросмотр изменений</h4><p class="section-subtitle">${opsPlusEscape(opsPlusEntityLabel(integrationInboundPreviewState.entity_type))} · цель ${opsPlusEscape(integrationInboundPreviewState.target_id || 0)}</p></div><div class="view-actions"><button class="btn-secondary" onclick="clearIntegrationInboundPreview()">Скрыть</button></div></div>${renderOpsPlusList(integrationInboundPreviewState.changes, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.field_name)}</div><div class="client360-item-meta">было: ${opsPlusEscape(item.before)} · станет: ${opsPlusEscape(item.after)}</div></div></div>`, integrationInboundPreviewState.matched ? 'Изменений нет.' : 'Сущность для входящего обновления не найдена.')}</div>` : ''}
                    </div>
                    <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Коннекторы и аналитика</h4>${renderOpsPlusList(integrationPlusDB.connectors, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(opsPlusConnectorTypeLabel(item.connector_type))} · ${opsPlusEscape(opsPlusProviderLabel(item.provider_name))}</div><div class="client360-item-meta">последний обмен: ${item.last_sync_at || 0}</div></div><div class="view-actions">${opsPlusStatusBadge(item.status)}<button class="btn-secondary" onclick="syncIntegrationConnector(${item.id})">Синхронизировать</button><button class="btn-secondary" onclick="heartbeatIntegrationConnector(${item.id})">Проверить</button><button class="btn-danger" onclick="deleteIntegrationConnector(${item.id})">Удалить</button></div></div>`, 'Коннекторов пока нет.')}
                        ${renderOpsPlusList(integrationPlusDB.connector_health, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(opsPlusConnectorTypeLabel(item.connector_type))} · ${opsPlusEscape(opsPlusProviderLabel(item.provider_name))}</div><div class="client360-item-meta">${item.last_sync_minutes_ago === null ? 'обмена ещё не было' : `обмен ${item.last_sync_minutes_ago} мин назад`}${item.last_error ? ` · ${opsPlusEscape(item.last_error)}` : ''}</div></div><div>${opsPlusStatusBadge(item.status)}</div></div>`, 'Состояние коннекторов пока пусто.')}</div>
                    <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Глубокая сверка</h4>${renderOpsPlusList(integrationPlusDB.reconciliation_runs, item => `<div class="client360-item"><div><div class="client360-item-title">Прогон #${item.id}</div><div class="client360-item-meta">расхождений ${item.mismatch_count || 0}</div></div><div>${opsPlusStatusBadge((item.mismatch_count || 0) > 0 ? 'attention' : 'synced')}</div></div>`, 'Сверка ещё не запускалась.')}
                        ${renderOpsPlusList(integrationPlusDB.conflicts, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(opsPlusEntityLabel(item.entity_type))} #${opsPlusEscape(item.entity_id)}</div><div class="client360-item-meta">${opsPlusEscape(item.message || opsPlusStatusLabel(item.state || 'conflict'))}</div></div><div>${opsPlusStatusBadge(item.state || 'conflict')}</div></div>`, 'Конфликтов сейчас нет.')}
                    </div>
                    <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Банк, телефония и аналитика</h4>
                        ${renderOpsPlusList((integrationPlusDB.bank_exchange_board?.latest_batches || []), item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(opsPlusProviderLabel(item.provider_name || 'Банк'))} · пакет #${opsPlusEscape(item.id)}</div><div class="client360-item-meta">строк ${opsPlusEscape(item.item_count)} · сумма ${opsPlusEscape(item.total_amount)}</div></div><div>${opsPlusStatusBadge(item.status)}</div></div>`, 'Банковских пакетов пока нет.')}
                        ${renderOpsPlusList((integrationPlusDB.telephony_board?.recent_unlinked || []), item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.phone_number || 'Номер')}</div><div class="client360-item-meta">${opsPlusEscape(item.summary || '')}</div></div><div>${opsPlusStatusBadge(item.status || 'open')}</div></div>`, 'Непривязанных звонков сейчас нет.')}
                        ${renderOpsPlusList(integrationPlusDB.bi_vitrines, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.title || item.report_type)}</div><div class="client360-item-meta">${opsPlusEscape(opsPlusRecoveryLabel(item.report_type))} · ${opsPlusEscape(opsPlusStatusLabel(item.scope || 'shared'))}</div></div><div>${opsPlusStatusBadge('shared')}</div></div>`, 'Аналитических витрин пока нет.')}
                    </div>
                </div>
            </details>
        </section>
    `;
}

window.reloadDocflowPlus = async function() { await loadDocflowPlusData(); renderDocflowPlusMount(); };
window.reloadIntegrationPlus = async function() { await loadIntegrationPlusData(); renderIntegrationPlusMount(); };

window.loadDocflowDocumentTimeline = async function(documentId) {
    const targetDocumentId = Number(documentId || document.getElementById('docflowTimelineDocumentId')?.value || 0);
    if (!targetDocumentId) return customAlert('Выбери документ для истории.');
    const res = await apiCall(`/docflow/documents/${targetDocumentId}/timeline`);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось загрузить историю документа.');
    docflowTimelineState = res;
    renderDocflowPlusMount();
};

window.showDocflowVersionDiff = async function(versionId) {
    const res = await apiCall(`/docflow/versions/${Number(versionId || 0)}/diff`);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось загрузить сравнение версии.');
    docflowVersionDiffState = res;
    renderDocflowPlusMount();
};

window.clearDocflowVersionDiff = function() {
    docflowVersionDiffState = null;
    renderDocflowPlusMount();
};

window.generateDocflowPrintSet = async function(documentId) {
    const targetDocumentId = Number(documentId || document.getElementById('docflowTimelineDocumentId')?.value || document.getElementById('docflowPrintDocumentId')?.value || 0);
    if (!targetDocumentId) return customAlert('Выбери документ для печатных форм.');
    const res = await apiCall(`/docflow/documents/${targetDocumentId}/generate_print_set`, 'POST');
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сгенерировать печатные формы.');
    showToast('Документы', `Сгенерировано печатных форм: ${Number(res.count || 0)}`);
    await reloadDocflowPlus();
};

window.saveDocflowTemplate = async function() {
    const payload = { title: document.getElementById('docflowTemplateTitle')?.value || '', doc_type: document.getElementById('docflowTemplateType')?.value || 'incoming', version_label: document.getElementById('docflowTemplateVersion')?.value || 'v1' };
    const res = await apiCall('/docflow/templates', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить шаблон.');
    await reloadDocflowPlus();
};

window.saveDocflowVersion = async function() {
    const payload = { document_id: Number(document.getElementById('docflowVersionDocumentId')?.value || 0), version_label: document.getElementById('docflowVersionLabel')?.value || '', version_status: 'draft', payload: {} };
    const res = await apiCall('/docflow/versions', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось создать версию.');
    await reloadDocflowPlus();
};

window.snapshotDocflowVersion = async function() {
    const documentId = Number(document.getElementById('docflowVersionDocumentId')?.value || 0);
    const res = await apiCall(`/docflow/documents/${documentId}/snapshot`, 'POST');
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сделать снимок документа.');
    await reloadDocflowPlus();
};

window.saveDocflowTask = async function() {
    const payload = { document_id: Number(document.getElementById('docflowTaskDocumentId')?.value || 0), title: document.getElementById('docflowTaskTitle')?.value || '', assignee_name: document.getElementById('docflowTaskAssignee')?.value || '', deadline: document.getElementById('docflowTaskDeadline')?.value || '', status: 'active' };
    const res = await apiCall('/docflow/linked_tasks', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось создать поручение.');
    await reloadDocflowPlus();
};

window.saveDocflowCertificate = async function() {
    const payload = { owner_name: document.getElementById('docflowCertOwner')?.value || '', owner_email: document.getElementById('docflowCertEmail')?.value || '', signer_role: document.getElementById('docflowCertRole')?.value || '', status: 'active' };
    const res = await apiCall('/docflow/certificates', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить сертификат.');
    await reloadDocflowPlus();
};

window.saveDocflowArchive = async function() {
    const payload = { document_id: Number(document.getElementById('docflowArchiveDocumentId')?.value || 0), retention_until: document.getElementById('docflowArchiveRetention')?.value || '', storage_path: document.getElementById('docflowArchivePath')?.value || '', archive_status: 'archived' };
    const res = await apiCall('/docflow/archive', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось отправить документ в архив.');
    await reloadDocflowPlus();
};

window.saveDocflowPrintForm = async function() {
    const payload = { document_id: Number(document.getElementById('docflowPrintDocumentId')?.value || 0), template_id: Number(document.getElementById('docflowPrintTemplateId')?.value || 0), format_type: document.getElementById('docflowPrintFormat')?.value || 'pdf', status: 'generated' };
    const res = await apiCall('/docflow/print_forms', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось создать печатную форму.');
    await reloadDocflowPlus();
};

window.createDocflowOcrJob = async function() {
    const payload = {
        document_id: Number(document.getElementById('docflowOcrDocumentId')?.value || 0),
        template_id: Number(document.getElementById('docflowOcrTemplateId')?.value || 0),
        input_text: document.getElementById('docflowOcrText')?.value || '',
        language: 'rus',
        auto_apply: 1,
    };
    if (!payload.document_id && !payload.input_text.trim()) return customAlert('Выбери документ или вставь текст для OCR.');
    const res = await apiCall('/docflow/ocr_jobs', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось выполнить OCR.');
    showToast('Документы', `OCR обработан, уверенность ${res.confidence || 0}`);
    await reloadDocflowPlus();
};

window.processDocflowOcrJob = async function(jobId) {
    const res = await apiCall(`/docflow/ocr_jobs/${Number(jobId || 0)}/process`, 'POST');
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось переобработать OCR.');
    showToast('Документы', `OCR переобработан, уверенность ${res.confidence || 0}`);
    await reloadDocflowPlus();
};

window.createDocflowTemplateFlow = async function() {
    const templateId = Number(document.getElementById('docflowTemplateFlowTemplateId')?.value || 0);
    const direction = document.getElementById('docflowTemplateFlowDirection')?.value || 'incoming';
    const payload = {
        flow_name: document.getElementById('docflowTemplateFlowName')?.value || '',
        direction,
        doc_type: document.getElementById('docflowTemplateFlowDocType')?.value || direction,
        template_ids: templateId ? [templateId] : [],
        required_fields: ['number', 'd_date', 'correspondent', 'subject'],
        status: 'active',
    };
    if (!payload.flow_name.trim()) return customAlert('Укажи название шаблонного потока.');
    const res = await apiCall('/docflow/template_flows', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось создать шаблонный поток.');
    await reloadDocflowPlus();
};

window.applyDocflowTemplateFlow = async function(flowId) {
    const documentId = Number(document.getElementById('docflowTemplateFlowDocumentId')?.value || document.getElementById('docflowTimelineDocumentId')?.value || document.getElementById('docflowPrintDocumentId')?.value || 0);
    if (!documentId) return customAlert('Выбери документ для применения потока.');
    const latestOcr = (docflowPlusDB?.ocr_jobs || []).find(item => Number(item.document_id || 0) === Number(documentId));
    const payload = {
        document_id: documentId,
        ocr_job_id: Number(latestOcr?.id || 0),
        comment: 'Применение из панели СЭД+',
    };
    const res = await apiCall(`/docflow/template_flows/${Number(flowId || 0)}/apply`, 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось применить шаблонный поток.');
    showToast('Документы', `Поток применён, печатных форм: ${(res.created_print_forms || []).length}`);
    await reloadDocflowPlus();
};

window.deleteDocflowTemplate = async id => { await apiCall(`/docflow/templates/${id}`, 'DELETE'); await reloadDocflowPlus(); };
window.deleteDocflowVersion = async id => { await apiCall(`/docflow/versions/${id}`, 'DELETE'); await reloadDocflowPlus(); };
window.deleteDocflowTask = async id => { await apiCall(`/docflow/linked_tasks/${id}`, 'DELETE'); await reloadDocflowPlus(); };
window.deleteDocflowPrintForm = async id => { await apiCall(`/docflow/print_forms/${id}`, 'DELETE'); await reloadDocflowPlus(); };
window.applyDocflowTemplateToModal = function(templateId) {
    const template = (docflowPlusDB?.templates || []).find(item => Number(item.id) === Number(templateId));
    if (!template) return customAlert('Шаблон не найден.');
    if (typeof window.openDocumentModalWithPreset !== 'function') {
        return customAlert('Карточка документа пока не готова к шаблонам. Обновите страницу.');
    }
    const body = String(template.body_text || '').trim();
    const subject = body || String(template.title || '').trim();
    const correspondent = String(template.comment || '').trim();
    window.openDocumentModalWithPreset({
        type: template.doc_type || 'incoming',
        subject,
        correspondent,
        d_date: (() => {
            const now = new Date();
            return `${String(now.getDate()).padStart(2, '0')}.${String(now.getMonth() + 1).padStart(2, '0')}.${now.getFullYear()}`;
        })(),
    });
};
window.focusDocumentFromTimeline = function(documentId) {
    const targetId = Number(documentId || 0);
    if (!targetId) return;
    if (typeof navigateTo === 'function') {
        navigateTo('documents');
    }
    setTimeout(() => {
        const row = document.querySelector(`#documentsListTable tr[data-document-id="${targetId}"]`);
        if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 200);
};

window.saveIntegrationMapping = async function() {
    const payload = {
        entity_type: String(document.getElementById('integrationMapEntity')?.value || '').trim(),
        local_field: String(document.getElementById('integrationMapLocal')?.value || '').trim(),
        external_field: String(document.getElementById('integrationMapExternal')?.value || '').trim(),
    };
    if (!payload.entity_type) return customAlert('Сначала выберите раздел CRM.');
    if (!payload.local_field || !payload.external_field) return customAlert('Укажите поле в CRM и соответствующее поле в 1С.');
    const res = await apiCall('/integration/mappings/designer', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить сопоставление.');
    showToast('Обмен с 1С', `Поле добавлено в раздел «${opsPlusEntityLabel(payload.entity_type)}».`);
    await reloadIntegrationPlus();
    openIntegrationMappingSettings(payload.entity_type);
};

window.bootstrapIntegrationMappings = async function(entityType) {
    const target = String(entityType || '').trim();
    if (!target) return customAlert('Укажи тип сущности для автозаполнения.');
    const res = await apiCall(`/integration/mappings/bootstrap/${encodeURIComponent(target)}`, 'POST');
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось выполнить автозаполнение сопоставления.');
    showToast('Интеграции', `Созданы базовые правила для раздела «${opsPlusEntityLabel(target)}»: ${Number(res.created || 0)}`);
    await reloadIntegrationPlus();
};

window.selectIntegrationMappingEntity = function(entityType) {
    const target = String(entityType || '').trim();
    const select = document.getElementById('integrationMappingEntitySelect');
    const input = document.getElementById('integrationMapEntity');
    if (select) select.value = target;
    if (input) input.value = target;
    const localFieldSelect = document.getElementById('integrationMapLocal');
    if (localFieldSelect) {
        const section = (integrationPlusDB?.mapping_matrix || [])
            .find(item => String(item.entity_type || '') === target);
        const fields = Array.isArray(section?.expected_fields) ? section.expected_fields : [];
        localFieldSelect.innerHTML = fields.length
            ? `<option value="">Выберите поле</option>${fields.map(field => `<option value="${opsPlusEscape(field)}">${opsPlusEscape(opsPlusFieldLabel(field))}</option>`).join('')}`
            : '<option value="">Для раздела нет доступных полей</option>';
    }
};

window.openIntegrationMappingSettings = function(entityType) {
    const target = String(entityType || '').trim();
    selectIntegrationMappingEntity(target);
    const details = document.getElementById('integrationMappingSettings');
    if (details) {
        details.open = true;
        details.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    const localField = document.getElementById('integrationMapLocal');
    if (localField) window.setTimeout(() => localField.focus(), 250);
};

window.bootstrapSelectedIntegrationMapping = async function() {
    const target = String(
        document.getElementById('integrationMappingEntitySelect')?.value
        || document.getElementById('integrationMapEntity')?.value
        || ''
    ).trim();
    if (!target) return customAlert('Сначала выбери один раздел для настройки.');
    const message = `Создать базовые правила только для раздела «${opsPlusEntityLabel(target)}»? Остальные разделы не изменятся.`;
    const confirmed = typeof customConfirm === 'function' ? await customConfirm(message) : window.confirm(message);
    if (!confirmed) return;
    await bootstrapIntegrationMappings(target);
};

window.bootstrapMissingIntegrationMappings = function() {
    return customAlert('Массовое автозаполнение отключено. Выбери один раздел и создай правила только для него.');
};

window.saveIntegrationInbound = async function() {
    let payloadJson = {};
    try { payloadJson = JSON.parse(document.getElementById('integrationInboundPayload')?.value || '{}'); } catch (e) { return customAlert('Входящие данные должны быть валидным JSON.'); }
    const payload = { entity_type: document.getElementById('integrationInboundEntity')?.value || '', entity_id: Number(document.getElementById('integrationInboundId')?.value || 0), external_id: document.getElementById('integrationInboundExternalId')?.value || '', payload: payloadJson, apply_mode: document.getElementById('integrationInboundMode')?.value || 'apply' };
    const res = await apiCall('/integration/inbound_updates', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить входящее обновление.');
    if (res.outcome && res.outcome.changes) integrationInboundPreviewState = res.outcome;
    await reloadIntegrationPlus();
};

window.saveIntegrationConnector = async function() {
    const payload = { connector_type: document.getElementById('integrationConnectorType')?.value || '1c', provider_name: document.getElementById('integrationConnectorProvider')?.value || '', status: document.getElementById('integrationConnectorStatus')?.value || 'active', settings: {}, scope: {} };
    const res = await apiCall('/integration/connectors', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить коннектор.');
    await reloadIntegrationPlus();
};

window.deleteIntegrationMapping = async id => { await apiCall(`/integration/mappings/designer/${id}`, 'DELETE'); await reloadIntegrationPlus(); };
window.deleteIntegrationInbound = async id => { await apiCall(`/integration/inbound_updates/${id}`, 'DELETE'); await reloadIntegrationPlus(); };
window.deleteIntegrationConnector = async id => { await apiCall(`/integration/connectors/${id}`, 'DELETE'); await reloadIntegrationPlus(); };
window.heartbeatIntegrationConnector = async id => { await apiCall(`/integration/connectors/${id}/heartbeat`, 'POST'); await reloadIntegrationPlus(); };
window.previewIntegrationInbound = async function(id) {
    const res = await apiCall(`/integration/inbound_updates/${id}/preview`);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось проверить входящее обновление.');
    integrationInboundPreviewState = res;
    renderIntegrationPlusMount();
};
window.applyIntegrationInbound = async function(id) {
    const res = await apiCall(`/integration/inbound_updates/${id}/apply`, 'POST');
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось применить входящее обновление.');
    integrationInboundPreviewState = null;
    await reloadIntegrationPlus();
};
window.clearIntegrationInboundPreview = function() {
    integrationInboundPreviewState = null;
    renderIntegrationPlusMount();
};
window.autoResolveIntegrationReconciliation = async function() {
    const res = await apiCall('/integration/reconciliation/auto_resolve', 'POST');
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось выполнить авторазбор.');
    showToast('Интеграции', `Авторазбор: было ${Number(res.before_mismatches || 0)} -> стало ${Number(res.after_mismatches || 0)}`);
    await reloadIntegrationPlus();
};
window.syncIntegrationConnector = async function(id) {
    const res = await apiCall(`/integration/connectors/${id}/sync`, 'POST');
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось выполнить синхронизацию подключения.');
    await reloadIntegrationPlus();
};

function renderSecurityPlusMount() {
    const mount = document.getElementById('securityPlusMount');
    if (!mount || !securityPlusDB || !(typeof hasDirectorWorkbenchAccess === 'function' ? hasDirectorWorkbenchAccess() : (currentUser && currentUser.role === 'Директор'))) return;
    mount.innerHTML = `
        <div class="surface-card surface-card--padded">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Контур правил безопасности</h3>
                    <p class="section-subtitle">Отдельные правила по статусам и действиям, блокировка опасных операций, аудит действий и усиленный контроль сессий.</p>
                </div>
                <div class="view-actions"><button class="btn-secondary" onclick="reloadSecurityPlus()">Обновить</button></div>
            </div>
            <div class="metrics-grid">${renderOpsPlusMetricCards(securityPlusDB.metrics)}</div>
            <div class="finance-form-grid" style="margin-top:16px;">
                <input id="securityPolicyRole" class="auth-input" style="margin:0;" placeholder="Роль">
                <input id="securityPolicyModule" class="auth-input" style="margin:0;" placeholder="Модуль">
                <input id="securityPolicyEntity" class="auth-input" style="margin:0;" placeholder="Сущность">
                <input id="securityPolicyAction" class="auth-input" style="margin:0;" placeholder="Действие">
                <input id="securityPolicyStatus" class="auth-input" style="margin:0;" placeholder="Статус">
                <select id="securityPolicyAllow" class="auth-input" style="margin:0;"><option value="1">Разрешить</option><option value="0">Запретить</option></select>
                <select id="securityPolicy2fa" class="auth-input" style="margin:0;"><option value="0">Без 2FA</option><option value="1">Требовать 2FA</option></select>
                <select id="securityPolicyReason" class="auth-input" style="margin:0;"><option value="0">Без причины</option><option value="1">Требовать причину</option></select>
                <button class="btn-primary" onclick="saveSecurityPolicy()">Сохранить правило</button>
                <input id="securityDangerModule" class="auth-input" style="margin:0;" placeholder="Модуль риска">
                <input id="securityDangerEntity" class="auth-input" style="margin:0;" placeholder="Сущность риска">
                <input id="securityDangerAction" class="auth-input" style="margin:0;" placeholder="Действие риска">
                <input id="securityDangerRoles" class="auth-input" style="margin:0;" placeholder="Запрещённые роли через запятую">
                <select id="securityDangerLevel" class="auth-input" style="margin:0;"><option value="medium">средний</option><option value="high">высокий</option><option value="critical">критичный</option></select>
                <select id="securityDanger2fa" class="auth-input" style="margin:0;"><option value="0">Без 2FA</option><option value="1">Требовать 2FA</option></select>
                <select id="securityDangerReason" class="auth-input" style="margin:0;"><option value="1">Требовать причину</option><option value="0">Без причины</option></select>
                <button class="btn-secondary" onclick="saveSecurityDangerRule()">Сохранить риск</button>
                <input id="securitySessionsEmail" class="auth-input" style="margin:0;" placeholder="Эл. почта для сброса сессий">
                <input id="securitySessionsOlder" class="auth-input" style="margin:0;" placeholder="Старше минут">
                <button class="btn-secondary" onclick="revokeAllSecuritySessions()">Сбросить все</button>
                <button class="btn-danger" onclick="revokeStaleSecuritySessions()">Сбросить зависшие</button>
            </div>
            <div class="system-ops-grid" style="margin-top:18px;">
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Правила действий</h4>${renderOpsPlusList(securityPlusDB.policies, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.role_name)} · ${opsPlusEscape(opsPlusModuleLabel(item.module_name))}</div><div class="client360-item-meta">${opsPlusEscape(opsPlusEntityLabel(item.entity_type))} / ${opsPlusEscape(opsPlusActionLabel(item.action_name))} / ${opsPlusEscape(item.status_name ? opsPlusStatusLabel(item.status_name) : 'любой')}</div><div class="client360-item-meta">${Number(item.require_2fa || 0) ? '2FA' : 'без 2FA'} · ${Number(item.require_reason || 0) ? 'с причиной' : 'без причины'}</div></div><div class="view-actions">${opsPlusStatusBadge(Number(item.allow_execute || 0) === 1 ? 'allow' : 'deny')}<button class="btn-danger" onclick="deleteSecurityPolicy(${item.id})">Удалить</button></div></div>`, 'Правил действий пока нет.')}</div>
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Правила риска</h4>${renderOpsPlusList(securityPlusDB.danger_rules, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(opsPlusModuleLabel(item.module_name))} / ${opsPlusEscape(opsPlusActionLabel(item.action_name))}</div><div class="client360-item-meta">${opsPlusEscape((item.blocked_roles || []).join(', ') || 'роль не ограничена')} · ${Number(item.require_2fa || 0) ? '2FA' : 'без 2FA'} · ${Number(item.require_reason || 0) ? 'с причиной' : 'без причины'}</div></div><div class="view-actions">${opsPlusStatusBadge(item.risk_level)}<button class="btn-danger" onclick="deleteSecurityDangerRule(${item.id})">Удалить</button></div></div>`, 'Правил риска пока нет.')}</div>
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Сессии</h4>${renderOpsPlusList(securityPlusDB.sessions, item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.user_email || 'пользователь')}</div><div class="client360-item-meta">${opsPlusEscape(item.ip_address || 'IP не указан')} · ${opsPlusEscape(item.user_agent || 'устройство не указано')}</div></div><div class="view-actions"><button class="btn-danger" onclick="revokeOneSecuritySession('${opsPlusEscape(item.session_id)}', '${opsPlusEscape(item.user_email || '')}')">Завершить</button></div></div>`, 'Активных сессий нет.')}</div>
                <div class="surface-card surface-card--soft surface-card--padded"><h4 class="section-title" style="font-size:16px;">Матрица и доступ по полям</h4>${renderOpsPlusList([...(securityPlusDB.policy_matrix || []).slice(0, 12)], item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.role_name)} · ${opsPlusEscape(opsPlusModuleLabel(item.module_name))}</div><div class="client360-item-meta">действий ${item.actions_total || 0} · полей ${item.field_rules_total || 0} · статусов ${item.status_rules_total || 0} · рисков ${item.danger_rules_total || 0}</div></div><div class="view-actions">${opsPlusStatusBadge(item.covered ? 'allow' : 'attention')}</div></div>`, 'Матрица пока пустая.')}${renderOpsPlusList([...(securityPlusDB.top_actions || []), ...(securityPlusDB.top_field_changes || [])], item => `<div class="client360-item"><div><div class="client360-item-title">${opsPlusEscape(item.action ? opsPlusActionLabel(item.action) : opsPlusFieldLabel(item.field_key || 'audit'))}</div><div class="client360-item-meta">количество ${item.count || 0}</div></div></div>`, 'Аудит пока пуст.')}</div>
            </div>
        </div>
    `;
}

window.reloadSecurityPlus = async function() { await loadSecurityPlusData(); renderSecurityPlusMount(); };

window.saveSecurityPolicy = async function() {
    const payload = {
        role_name: document.getElementById('securityPolicyRole')?.value || '',
        module_name: document.getElementById('securityPolicyModule')?.value || '',
        entity_type: document.getElementById('securityPolicyEntity')?.value || '',
        action_name: document.getElementById('securityPolicyAction')?.value || '',
        status_name: document.getElementById('securityPolicyStatus')?.value || '',
        allow_execute: Number(document.getElementById('securityPolicyAllow')?.value || 1),
        require_2fa: Number(document.getElementById('securityPolicy2fa')?.value || 0),
        require_reason: Number(document.getElementById('securityPolicyReason')?.value || 0),
    };
    const res = await apiCall('/security/action_policies', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить правило безопасности.');
    await reloadSecurityPlus();
};

window.saveSecurityDangerRule = async function() {
    const payload = {
        module_name: document.getElementById('securityDangerModule')?.value || '',
        entity_type: document.getElementById('securityDangerEntity')?.value || '',
        action_name: document.getElementById('securityDangerAction')?.value || '',
        blocked_roles: (document.getElementById('securityDangerRoles')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        risk_level: document.getElementById('securityDangerLevel')?.value || 'medium',
        require_2fa: Number(document.getElementById('securityDanger2fa')?.value || 0),
        require_reason: Number(document.getElementById('securityDangerReason')?.value || 1),
    };
    const res = await apiCall('/security/danger_rules', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить правило риска.');
    await reloadSecurityPlus();
};

window.deleteSecurityPolicy = async id => { await apiCall(`/security/action_policies/${id}`, 'DELETE'); await reloadSecurityPlus(); };
window.deleteSecurityDangerRule = async id => { await apiCall(`/security/danger_rules/${id}`, 'DELETE'); await reloadSecurityPlus(); };
window.revokeOneSecuritySession = async (sessionId, userEmail) => { await apiCall('/security/sessions/control', 'POST', { action_name: 'revoke_one', session_id: sessionId, user_email: userEmail }); await reloadSecurityPlus(); };
window.revokeAllSecuritySessions = async () => { await apiCall('/security/sessions/control', 'POST', { action_name: 'revoke_all', user_email: document.getElementById('securitySessionsEmail')?.value || '' }); await reloadSecurityPlus(); };
window.revokeStaleSecuritySessions = async () => { await apiCall('/security/sessions/control', 'POST', { action_name: 'revoke_stale', older_than_minutes: Number(document.getElementById('securitySessionsOlder')?.value || 0) || 60 }); await reloadSecurityPlus(); };

function wrapOpsPlusRenderers() {
    const originalRenderDocuments = window.renderDocuments;
    if (typeof originalRenderDocuments === 'function' && !window.__opsPlusDocumentsWrapped) {
        window.renderDocuments = function(...args) {
            const result = originalRenderDocuments.apply(this, args);
            loadDocflowPlusData().then(renderDocflowPlusMount);
            return result;
        };
        window.__opsPlusDocumentsWrapped = true;
    }
    const originalRenderOperationsCenter = window.renderOperationsCenter;
    if (typeof originalRenderOperationsCenter === 'function' && !window.__opsPlusOperationsWrapped) {
        window.renderOperationsCenter = async function(...args) {
            const result = await originalRenderOperationsCenter.apply(this, args);
            await loadIntegrationPlusData();
            renderIntegrationPlusMount();
            return result;
        };
        window.__opsPlusOperationsWrapped = true;
    }
    const originalRenderProfile = window.renderProfile;
    if (typeof originalRenderProfile === 'function' && !window.__opsPlusProfileWrapped) {
        window.renderProfile = function(...args) {
            const result = originalRenderProfile.apply(this, args);
            if (typeof hasDirectorWorkbenchAccess === 'function' ? hasDirectorWorkbenchAccess() : (currentUser && currentUser.role === 'Директор')) {
                loadSecurityPlusData().then(renderSecurityPlusMount);
            }
            return result;
        };
        window.__opsPlusProfileWrapped = true;
    }
}

window.addEventListener('load', () => {
    wrapOpsPlusRenderers();
});

// Enterprise security studio overrides
function opsPlusReadFlag(id) {
    const element = document.getElementById(id);
    if (!element) return 0;
    if (element.type === 'checkbox') return element.checked ? 1 : 0;
    return Number(element.value || 0);
}

function opsPlusJsString(value) {
    return String(value ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n');
}

renderSecurityPlusMount = function() {
    const mount = document.getElementById('securityPlusMount');
    if (!mount || !securityPlusDB || !(typeof hasDirectorWorkbenchAccess === 'function' ? hasDirectorWorkbenchAccess() : (currentUser && currentUser.role === 'Директор'))) return;

    const policiesHtml = renderOpsPlusList(
        securityPlusDB.policies,
        item => `
            <div class="krd-policy-row">
                <div class="krd-policy-row__main">
                    <div class="krd-policy-row__title">${opsPlusEscape(item.role_name)} · ${opsPlusEscape(opsPlusModuleLabel(item.module_name))}</div>
                    <div class="krd-policy-row__meta">
                        <span>${opsPlusEscape(opsPlusEntityLabel(item.entity_type))}</span>
                        <span>•</span>
                        <span>${opsPlusEscape(opsPlusActionLabel(item.action_name))}</span>
                        <span>•</span>
                        <span>${opsPlusEscape(item.status_name ? opsPlusStatusLabel(item.status_name) : 'любой статус')}</span>
                    </div>
                    <div class="krd-policy-row__meta">
                        <span class="ops-pill ${Number(item.allow_execute || 0) === 1 ? 'ops-pill--success' : 'ops-pill--danger'}">${Number(item.allow_execute || 0) === 1 ? 'разрешено' : 'запрещено'}</span>
                        <span class="ops-pill">${Number(item.require_2fa || 0) ? '2FA' : 'без 2FA'}</span>
                        <span class="ops-pill">${Number(item.require_reason || 0) ? 'с причиной' : 'без причины'}</span>
                    </div>
                </div>
                <div class="krd-policy-row__actions">
                    <button class="btn-danger" onclick="deleteSecurityPolicy(${Number(item.id)})">Удалить</button>
                </div>
            </div>
        `,
        'Правил действий пока нет.'
    );

    const dangerHtml = renderOpsPlusList(
        securityPlusDB.danger_rules,
        item => `
            <div class="krd-policy-row">
                <div class="krd-policy-row__main">
                    <div class="krd-policy-row__title">${opsPlusEscape(opsPlusModuleLabel(item.module_name))} / ${opsPlusEscape(opsPlusActionLabel(item.action_name))}</div>
                    <div class="krd-policy-row__meta">
                        <span>${opsPlusEscape(opsPlusEntityLabel(item.entity_type))}</span>
                        <span>•</span>
                        <span>${opsPlusEscape((item.blocked_roles || []).join(', ') || 'роль не ограничена')}</span>
                    </div>
                    <div class="krd-policy-row__meta">
                        <span class="ops-pill ${item.risk_level === 'critical' ? 'ops-pill--danger' : item.risk_level === 'high' ? 'ops-pill--warning' : ''}">${opsPlusEscape(item.risk_level || 'medium')}</span>
                        <span class="ops-pill">${Number(item.require_2fa || 0) ? '2FA' : 'без 2FA'}</span>
                        <span class="ops-pill">${Number(item.require_reason || 0) ? 'с причиной' : 'без причины'}</span>
                    </div>
                </div>
                <div class="krd-policy-row__actions">
                    <button class="btn-danger" onclick="deleteSecurityDangerRule(${Number(item.id)})">Удалить</button>
                </div>
            </div>
        `,
        'Правил риска пока нет.'
    );

    const sessionsHtml = renderOpsPlusList(
        securityPlusDB.sessions,
        item => `
            <div class="krd-policy-row">
                <div class="krd-policy-row__main">
                    <div class="krd-policy-row__title">${opsPlusEscape(item.user_email || 'пользователь')}</div>
                    <div class="krd-policy-row__meta">
                        <span>${opsPlusEscape(item.ip_address || 'IP не указан')}</span>
                        <span>•</span>
                        <span>${opsPlusEscape(item.user_agent || 'устройство не указано')}</span>
                    </div>
                </div>
                <div class="krd-policy-row__actions">
                    <button class="btn-danger" onclick="revokeOneSecuritySession('${opsPlusJsString(item.session_id)}', '${opsPlusJsString(item.user_email || '')}')">Завершить</button>
                </div>
            </div>
        `,
        'Активных сессий нет.'
    );

    const matrixHtml = renderOpsPlusList(
        [ ...(securityPlusDB.policy_matrix || []).slice(0, 12) ],
        item => `
            <div class="krd-policy-row">
                <div class="krd-policy-row__main">
                    <div class="krd-policy-row__title">${opsPlusEscape(item.role_name)} · ${opsPlusEscape(opsPlusModuleLabel(item.module_name))}</div>
                    <div class="krd-policy-row__meta">
                        <span>действий ${item.actions_total || 0}</span>
                        <span>•</span>
                        <span>полей ${item.field_rules_total || 0}</span>
                        <span>•</span>
                        <span>статусов ${item.status_rules_total || 0}</span>
                        <span>•</span>
                        <span>рисков ${item.danger_rules_total || 0}</span>
                    </div>
                </div>
                <div class="krd-policy-row__actions">${opsPlusStatusBadge(item.covered ? 'allow' : 'attention')}</div>
            </div>
        `,
        'Матрица пока пустая.'
    );

    const auditHtml = renderOpsPlusList(
        [ ...(securityPlusDB.top_actions || []), ...(securityPlusDB.top_field_changes || []) ],
        item => `
            <div class="krd-policy-row">
                <div class="krd-policy-row__main">
                    <div class="krd-policy-row__title">${opsPlusEscape(item.action ? opsPlusActionLabel(item.action) : opsPlusFieldLabel(item.field_key || 'audit'))}</div>
                    <div class="krd-policy-row__meta">Количество: ${item.count || 0}</div>
                </div>
            </div>
        `,
        'Аудит пока пуст.'
    );

    mount.innerHTML = `
        <details class="krd-profile-advanced-panel">
            <summary class="krd-profile-advanced-panel__summary">Расширенные правила безопасности</summary>
            <div class="krd-profile-advanced-panel__body">
                <section class="krd-policy-studio">
                    <div class="surface-card surface-card--padded">
                        <div class="section-header">
                            <div>
                                <h3 class="section-title">Контур правил безопасности</h3>
                                <p class="section-subtitle">Правила доступа по статусам и действиям, опасные операции, сессии и аудит — в одном компактном экране.</p>
                            </div>
                            <div class="view-actions">
                                <button class="btn-secondary" onclick="reloadSecurityPlus()">Обновить</button>
                            </div>
                        </div>
                        <div class="metrics-grid">${renderOpsPlusMetricCards(securityPlusDB.metrics)}</div>
                    </div>

                    <div class="krd-policy-studio__grid">
                        <div class="krd-policy-card">
                            <div class="krd-policy-card__head">
                                <div>
                                    <div class="krd-card__title">Политика действий</div>
                                    <div class="krd-card__subtitle">Разрешайте или запрещайте действия по модулю, сущности и статусу.</div>
                                </div>
                                <span class="ops-section-chip">Политика действий</span>
                            </div>

                            <div class="krd-policy-form">
                                <div class="krd-policy-form__grid">
                                    <input id="securityPolicyRole" class="auth-input" placeholder="Роль">
                                    <input id="securityPolicyModule" class="auth-input" placeholder="Модуль">
                                    <input id="securityPolicyEntity" class="auth-input" placeholder="Сущность">
                                    <input id="securityPolicyAction" class="auth-input" placeholder="Действие">
                                    <input id="securityPolicyStatus" class="auth-input" placeholder="Статус">
                                </div>
                                <div class="krd-policy-form__toggles">
                                    <label class="krd-toggle">
                                        <input id="securityPolicyAllow" class="krd-toggle__input" type="checkbox" checked>
                                        <span class="krd-toggle__track"></span>
                                        <span>Разрешить действие</span>
                                    </label>
                                    <label class="krd-toggle">
                                        <input id="securityPolicy2fa" class="krd-toggle__input" type="checkbox">
                                        <span class="krd-toggle__track"></span>
                                        <span>Требовать 2FA</span>
                                    </label>
                                    <label class="krd-toggle">
                                        <input id="securityPolicyReason" class="krd-toggle__input" type="checkbox">
                                        <span class="krd-toggle__track"></span>
                                        <span>Требовать причину</span>
                                    </label>
                                </div>
                                <div class="view-actions">
                                    <button class="btn-primary" onclick="saveSecurityPolicy()">Сохранить правило</button>
                                </div>
                            </div>

                            <div class="krd-policy-list">${policiesHtml}</div>
                        </div>

                        <div class="krd-policy-card">
                            <div class="krd-policy-card__head">
                                <div>
                                    <div class="krd-card__title">Опасные операции</div>
                                    <div class="krd-card__subtitle">Критичные действия, которые нужно блокировать или усиливать 2FA.</div>
                                </div>
                                <span class="ops-section-chip">Правила риска</span>
                            </div>

                            <div class="krd-policy-form">
                                <div class="krd-policy-form__grid">
                                    <input id="securityDangerModule" class="auth-input" placeholder="Модуль риска">
                                    <input id="securityDangerEntity" class="auth-input" placeholder="Сущность риска">
                                    <input id="securityDangerAction" class="auth-input" placeholder="Действие риска">
                                    <input id="securityDangerRoles" class="auth-input" placeholder="Запрещённые роли через запятую">
                                    <select id="securityDangerLevel" class="auth-input">
                                        <option value="medium">средний</option>
                                        <option value="high">высокий</option>
                                        <option value="critical">критичный</option>
                                    </select>
                                </div>
                                <div class="krd-policy-form__toggles">
                                    <label class="krd-toggle">
                                        <input id="securityDanger2fa" class="krd-toggle__input" type="checkbox">
                                        <span class="krd-toggle__track"></span>
                                        <span>Требовать 2FA</span>
                                    </label>
                                    <label class="krd-toggle">
                                        <input id="securityDangerReason" class="krd-toggle__input" type="checkbox" checked>
                                        <span class="krd-toggle__track"></span>
                                        <span>Требовать причину</span>
                                    </label>
                                </div>
                                <div class="view-actions">
                                    <button class="btn-secondary" onclick="saveSecurityDangerRule()">Сохранить риск</button>
                                </div>
                            </div>

                            <div class="krd-policy-list">${dangerHtml}</div>
                        </div>
                    </div>

                    <div class="krd-policy-studio__grid">
                        <div class="krd-policy-card">
                            <div class="krd-policy-card__head">
                                <div>
                                    <div class="krd-card__title">Контроль сессий</div>
                                    <div class="krd-card__subtitle">Быстрый сброс активных или зависших сессий по пользователям.</div>
                                </div>
                                <span class="ops-section-chip">Сессии</span>
                            </div>

                            <div class="krd-policy-form">
                                <div class="krd-policy-form__grid">
                                    <input id="securitySessionsEmail" class="auth-input" placeholder="Эл. почта для сброса сессий">
                                    <input id="securitySessionsOlder" class="auth-input" placeholder="Старше минут">
                                </div>
                                <div class="view-actions">
                                    <button class="btn-secondary" onclick="revokeAllSecuritySessions()">Сбросить все</button>
                                    <button class="btn-danger" onclick="revokeStaleSecuritySessions()">Сбросить зависшие</button>
                                </div>
                            </div>

                            <div class="krd-policy-list">${sessionsHtml}</div>
                        </div>

                        <div class="krd-policy-card">
                            <div class="krd-policy-card__head">
                                <div>
                                    <div class="krd-card__title">Матрица покрытия и аудит</div>
                                    <div class="krd-card__subtitle">Показывает, где матрица доступа уже покрыта правилами, а где остались пробелы.</div>
                                </div>
                                <span class="ops-section-chip">Покрытие</span>
                            </div>

                            <div class="krd-policy-list">${matrixHtml}</div>
                            <div class="krd-card__subtitle">Частые действия и изменения полей</div>
                            <div class="krd-policy-list">${auditHtml}</div>
                        </div>
                    </div>
                </section>
            </div>
        </details>
    `;
};

window.saveSecurityPolicy = async function() {
    const payload = {
        role_name: document.getElementById('securityPolicyRole')?.value || '',
        module_name: document.getElementById('securityPolicyModule')?.value || '',
        entity_type: document.getElementById('securityPolicyEntity')?.value || '',
        action_name: document.getElementById('securityPolicyAction')?.value || '',
        status_name: document.getElementById('securityPolicyStatus')?.value || '',
        allow_execute: opsPlusReadFlag('securityPolicyAllow'),
        require_2fa: opsPlusReadFlag('securityPolicy2fa'),
        require_reason: opsPlusReadFlag('securityPolicyReason'),
    };
    const result = await apiCall('/security/action_policies', 'POST', payload);
    if (!result || result.error) return customAlert(result?.message || result?.error || 'Не удалось сохранить правило безопасности.');
    await reloadSecurityPlus();
};

window.saveSecurityDangerRule = async function() {
    const payload = {
        module_name: document.getElementById('securityDangerModule')?.value || '',
        entity_type: document.getElementById('securityDangerEntity')?.value || '',
        action_name: document.getElementById('securityDangerAction')?.value || '',
        blocked_roles: (document.getElementById('securityDangerRoles')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        risk_level: document.getElementById('securityDangerLevel')?.value || 'medium',
        require_2fa: opsPlusReadFlag('securityDanger2fa'),
        require_reason: opsPlusReadFlag('securityDangerReason'),
    };
    const result = await apiCall('/security/danger_rules', 'POST', payload);
    if (!result || result.error) return customAlert(result?.message || result?.error || 'Не удалось сохранить правило риска.');
    await reloadSecurityPlus();
};
