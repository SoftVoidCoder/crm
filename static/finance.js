let financePaymentsDB = [];
let financeSummaryDB = null;
let financeMasterDataDB = null;
let financeErpSummaryDB = null;
let financeAnalyticsDB = null;
let financeJournalDB = [];
let financePeriodsDB = [];
let treasuryLimitsDB = [];
let reconciliationActsDB = [];
let financeSyncQueueDB = [];
let financeSyncConflictsDB = [];
let financeEdoSignaturesDB = [];
let financeFilter = 'all';
let editingFinancePaymentId = 0;
let currentClient360Id = 0;
let client360DB = null;
let selectedFinancePayments = new Set();
let financeEditLockId = 0;
let financeInboundPreviewState = null;

const financeFormFieldMap = {
    title: 'financeTitle',
    project_id: 'financeProjectId',
    client_id: 'financeClientId',
    legal_entity_id: 'financeLegalEntityId',
    business_unit_id: 'financeBusinessUnitId',
    treasury_article_id: 'financeTreasuryArticleId',
    vat_rate_id: 'financeVatRateId',
    source_document_type: 'financeSourceDocumentType',
    source_document_id: 'financeSourceDocumentId',
    kind: 'financeKind',
    category: 'financeCategory',
    amount: 'financeAmount',
    currency: 'financeCurrency',
    due_date: 'financeDueDate',
    paid_date: 'financePaidDate',
    status: { id: 'financeStatus', statusField: true },
    comment: 'financeComment',
};
const financeDraftFieldIds = ['financeTitle', 'financeProjectId', 'financeClientId', 'financeKind', 'financeCategory', 'financeAmount', 'financeCurrency', 'financeLegalEntityId', 'financeBusinessUnitId', 'financeTreasuryArticleId', 'financeVatRateId', 'financeDueDate', 'financePaidDate', 'financeSourceDocumentType', 'financeSourceDocumentId', 'financeStatus', 'financeComment'];

function financeEscapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[ch]));
}

function bindFinanceDraftAutosave() {
    if (typeof bindFormDraftAutosave !== 'function') return;
    bindFormDraftAutosave('finance_payment', {
        formId: 'financePaymentForm',
        fieldIds: financeDraftFieldIds,
        entityType: 'finance_payment',
        title: 'Черновик оплаты',
        sourceView: 'finance',
        shouldSave: () => !editingFinancePaymentId,
        shouldRestore: () => !editingFinancePaymentId,
        afterRestore: () => syncFinanceArticleOptions(),
    });
}

function selectedFinanceVatText() {
    const select = document.getElementById('financeVatRateId');
    return select?.selectedOptions?.[0]?.textContent || '';
}

function bindFinanceSmartHints() {
    if (typeof bindSmartFieldHints !== 'function') return;
    bindSmartFieldHints('financePaymentForm', [
        {
            field: 'financeClientId',
            validate: value => {
                const amount = String(document.getElementById('financeAmount')?.value || '').trim();
                if (amount && Number(value || 0) === 0) return { tone: 'warning', message: 'Платёж без контрагента потом сложнее сверять и искать в досье.' };
                return null;
            },
        },
        {
            field: 'financeAmount',
            validate: value => {
                const amount = Number(String(value || '').replace(',', '.')) || 0;
                if (!value) return null;
                if (!amount) return { tone: 'error', message: 'Сумма должна быть числом больше нуля.' };
                if (Number(document.getElementById('financeClientId')?.value || 0) === 0) {
                    window.setSmartFieldHint('financeClientId', 'Платёж без контрагента потом сложнее сверять и искать в досье.', 'warning', 'financePaymentForm');
                }
                const vatText = selectedFinanceVatText().toLowerCase();
                if (!vatText || vatText.includes('ставка')) return { tone: 'warning', message: 'Выбери ставку НДС: сумма с НДС или без НДС влияет на проводки.' };
                return { tone: 'hint', message: vatText.includes('без') || vatText.includes('0') ? 'Сумма будет сохранена как без НДС.' : `Проверь: сумма введена с выбранной ставкой НДС (${selectedFinanceVatText()}).` };
            },
        },
        {
            field: 'financeVatRateId',
            validate: value => {
                const amount = String(document.getElementById('financeAmount')?.value || '').trim();
                if (amount && Number(value || 0) === 0) return { tone: 'warning', message: 'Для суммы лучше явно указать ставку НДС или режим “без НДС”.' };
                return null;
            },
        },
        {
            field: 'financeDueDate',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'Дата оплаты нужна в формате дд.мм.гггг.' },
        },
        {
            field: 'financePaidDate',
            validate: value => !String(value || '').trim() || isValidRuDate(value)
                ? null
                : { tone: 'error', message: 'Фактическая дата нужна в формате дд.мм.гггг.' },
        },
    ]);
}

function formatMoney(value, currency = 'RUB') {
    const amount = Number(value || 0);
    const suffix = currency === 'RUB' ? '₽' : currency;
    return `${amount.toLocaleString('ru-RU')} ${suffix}`.trim();
}

function financeStatusLabel(status) {
    const map = {
        planned: 'План',
        issued: 'Выставлено',
        partially_paid: 'Частично оплачено',
        paid: 'Оплачено',
        overdue: 'Просрочено',
        approved: 'Согласовано',
        draft: 'Черновик',
    };
    return map[status] || status || 'Без статуса';
}

function financeStatusClass(status) {
    if (status === 'paid') return 'status-completed';
    if (status === 'overdue') return 'status-overdue';
    if (status === 'partially_paid') return 'status-active';
    return 'status-archived';
}

function financeTranslateLabel(value, fallback = '—') {
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
        imported: 'Загружено',
        answered: 'Отвечен',
        missed: 'Пропущен',
        incoming: 'Входящий',
        outgoing: 'Исходящий',
        call: 'Звонок',
        service: 'Сервис',
        normal: 'Обычный',
        draft: 'Черновик',
        open: 'Открыт',
        closed: 'Закрыт',
        signed: 'Подписано',
        queued: 'В очереди',
        synced: 'Синхронизировано',
        failed: 'Ошибка',
        retry: 'Повтор',
        processing: 'В обработке',
        conflict: 'Конфликт',
        shipped: 'Отгружено',
        proposal: 'КП отправлено',
        ordered: 'Заказано',
        in_progress: 'В работе',
        waiting_client: 'Ждёт клиента',
        maintenance: 'Сервисное обслуживание',
        invoice: 'Счёт',
        entity: 'Запись',
        finance_payment: 'Платёж',
        sales_document: 'Документ реализации',
        purchase_order: 'Заказ поставщику',
        production_order: 'Производственный заказ',
        stock_reservation: 'Резерв склада',
        nomenclature: 'Номенклатура',
        groups: 'Группы',
        warehouses: 'Склады',
        osno: 'ОСНО',
        payment: 'Платёж',
        expense: 'Расход',
        doc: 'Документ',
    };
    return map[raw] || raw;
}

function financeDisplayName(value, fallback = '') {
    const text = String(value || '').trim();
    if (!text) return fallback;
    return text
        .replace(/^QA Sync Client$/i, 'Тестовый клиент синхронизации')
        .replace(/^QA Enterprise Client$/i, 'Тестовый клиент ERP')
        .replace(/^QA Enterprise Project$/i, 'Тестовый проект ERP')
        .replace(/^QA Smoke Client\s*/i, 'Тестовый клиент ')
        .replace(/^QA Smoke Project\s*/i, 'Тестовый проект ')
        .replace(/\bSYNC-/g, 'обмен 1С №')
        .replace(/\bINV-/g, 'реализация №')
        .replace(/\bDEMO-/g, 'пример №')
        .replace(/\bDemo\b/g, 'пример')
        .replace(/\bdemo\b/g, 'пример')
        .replace(/\bexported\b/gi, 'выгружено');
}

async function loadFinanceModuleData() {
    const [summary, payments, masterData, erpSummary, analytics, journal, periods, limits, reconciliationActs, syncQueue, syncConflicts, edoSignatures] = await Promise.all([
        apiCall('/finance/summary'),
        apiCall(`/finance/payments${financeFilter !== 'all' ? `?status=${encodeURIComponent(financeFilter)}` : ''}`),
        apiCall('/finance/master_data'),
        apiCall('/finance/erp_summary'),
        apiCall('/finance/analytics'),
        apiCall('/finance/journal?limit=120'),
        apiCall('/finance/periods'),
        apiCall('/finance/treasury_limits'),
        apiCall('/finance/reconciliation_acts'),
        apiCall('/finance/sync_queue?limit=120'),
        apiCall('/finance/sync_conflicts?limit=120'),
        apiCall('/finance/edo_signatures?limit=120'),
    ]);
    financeSummaryDB = summary && !summary.error ? summary : null;
    financePaymentsDB = Array.isArray(payments) ? payments : [];
    financeMasterDataDB = masterData && !masterData.error ? masterData : null;
    financeErpSummaryDB = erpSummary && !erpSummary.error ? erpSummary : null;
    financeAnalyticsDB = analytics && !analytics.error ? analytics : null;
    financeJournalDB = Array.isArray(journal) ? journal : [];
    financePeriodsDB = Array.isArray(periods) ? periods : [];
    treasuryLimitsDB = Array.isArray(limits) ? limits : [];
    reconciliationActsDB = Array.isArray(reconciliationActs) ? reconciliationActs : [];
    financeSyncQueueDB = Array.isArray(syncQueue) ? syncQueue : [];
    financeSyncConflictsDB = Array.isArray(syncConflicts) ? syncConflicts : [];
    financeEdoSignaturesDB = Array.isArray(edoSignatures) ? edoSignatures : [];
    pruneSelectedFinancePayments();
}

function populateFinanceSelects() {
    const kindSelect = document.getElementById('financeKind');
    const projectSelect = document.getElementById('financeProjectId');
    const clientSelect = document.getElementById('financeClientId');
    const legalEntitySelect = document.getElementById('financeLegalEntityId');
    const businessUnitSelect = document.getElementById('financeBusinessUnitId');
    const treasuryArticleSelect = document.getElementById('financeTreasuryArticleId');
    const vatRateSelect = document.getElementById('financeVatRateId');
    const treasuryLimitLegalEntity = document.getElementById('treasuryLimitLegalEntityId');
    const treasuryLimitBusinessUnit = document.getElementById('treasuryLimitBusinessUnitId');
    const treasuryLimitArticle = document.getElementById('treasuryLimitArticleId');
    const reconciliationClientSelect = document.getElementById('reconciliationClientId');
    const masterBusinessUnitLegalEntity = document.getElementById('masterBusinessUnitLegalEntityId');
    const defaults = financeMasterDataDB?.defaults || {};
    if (projectSelect) {
        projectSelect.innerHTML = `<option value="0">Без проекта</option>${projectsDB.map(project => `
            <option value="${project.id}">${project.contract || 'Без договора'} · ${project.name}</option>
        `).join('')}`;
    }
    if (clientSelect) {
        clientSelect.innerHTML = `<option value="0">Без контрагента</option>${clientsDB
            .slice()
            .sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ru'))
            .map(client => `<option value="${client.id}">${client.name}</option>`)
            .join('')}`;
    }
    if (reconciliationClientSelect) {
        reconciliationClientSelect.innerHTML = clientSelect ? clientSelect.innerHTML.replace('Без контрагента', 'Контрагент сверки') : `<option value="0">Контрагент сверки</option>`;
    }
    if (legalEntitySelect) {
        legalEntitySelect.innerHTML = `<option value="0">Юрлицо</option>${(financeMasterDataDB?.legal_entities || []).map(item => `<option value="${item.id}">${item.short_name || item.name}</option>`).join('')}`;
        legalEntitySelect.value = String(defaults.legal_entity_id || 0);
    }
    if (businessUnitSelect) {
        businessUnitSelect.innerHTML = `<option value="0">Подразделение</option>${(financeMasterDataDB?.business_units || []).map(item => `<option value="${item.id}">${item.name}</option>`).join('')}`;
        businessUnitSelect.value = String(defaults.business_unit_id || 0);
    }
    if (treasuryArticleSelect) {
        const preferredKind = document.getElementById('financeKind')?.value || 'incoming';
        treasuryArticleSelect.innerHTML = `<option value="0">Статья ДДС</option>${(financeMasterDataDB?.treasury_articles || []).filter(item => item.flow_kind === preferredKind).map(item => `<option value="${item.id}">${item.name}</option>`).join('')}`;
        treasuryArticleSelect.value = String(defaults.treasury_article_id || 0);
    }
    if (vatRateSelect) {
        vatRateSelect.innerHTML = `<option value="0">Ставка НДС</option>${(financeMasterDataDB?.vat_rates || []).map(item => `<option value="${item.id}">${item.name}</option>`).join('')}`;
        vatRateSelect.value = String(defaults.vat_rate_id || 0);
    }
    if (treasuryLimitLegalEntity) {
        treasuryLimitLegalEntity.innerHTML = legalEntitySelect ? legalEntitySelect.innerHTML.replace('Юрлицо', 'Юрлицо лимита') : '';
        treasuryLimitLegalEntity.value = String(defaults.legal_entity_id || 0);
    }
    if (masterBusinessUnitLegalEntity) {
        masterBusinessUnitLegalEntity.innerHTML = legalEntitySelect ? legalEntitySelect.innerHTML.replace('Юрлицо', 'Юрлицо подразделения') : '<option value="0">Юрлицо подразделения</option>';
        masterBusinessUnitLegalEntity.value = String(defaults.legal_entity_id || 0);
    }
    if (treasuryLimitBusinessUnit) {
        treasuryLimitBusinessUnit.innerHTML = businessUnitSelect ? businessUnitSelect.innerHTML.replace('Подразделение', 'Подразделение лимита') : '';
        treasuryLimitBusinessUnit.value = String(defaults.business_unit_id || 0);
    }
    if (treasuryLimitArticle) {
        treasuryLimitArticle.innerHTML = `<option value="0">Статья ДДС лимита</option>${(financeMasterDataDB?.treasury_articles || []).filter(item => item.flow_kind === 'outgoing').map(item => `<option value="${item.id}">${item.name}</option>`).join('')}`;
    }
    if (kindSelect) {
        kindSelect.onchange = () => syncFinanceArticleOptions();
    }
}

function renderFinanceMasterData() {
    const legalEntitiesTbody = document.getElementById('financeMasterLegalEntitiesTable');
    const businessUnitsTbody = document.getElementById('financeMasterBusinessUnitsTable');
    const articlesTbody = document.getElementById('financeMasterArticlesTable');
    const vatRatesTbody = document.getElementById('financeMasterVatRatesTable');
    const legalEntities = financeMasterDataDB?.legal_entities || [];
    const businessUnits = financeMasterDataDB?.business_units || [];
    const treasuryArticles = financeMasterDataDB?.treasury_articles || [];
    const vatRates = financeMasterDataDB?.vat_rates || [];
    if (legalEntitiesTbody) {
        legalEntitiesTbody.innerHTML = legalEntities.length
            ? legalEntities.map(item => `
                <tr>
                    <td>${item.short_name || item.name || 'Юрлицо'}<div class="finance-row-meta">${item.name || 'Без полного названия'}</div></td>
                    <td>ИНН ${item.inn || '—'} · КПП ${item.kpp || '—'}<div class="finance-row-meta">${financeTranslateLabel(item.vat_mode || 'osno', 'ОСНО')} · ${item.default_currency || 'RUB'}</div></td>
                    <td><span class="status-badge ${item.is_active ? 'status-active' : 'status-archived'}">${item.is_active ? 'Активно' : 'Архив'}</span></td>
                </tr>
            `).join('')
            : '<tr><td colspan="3" class="nsi-empty-row">Юрлица пока не заведены.</td></tr>';
    }
    if (businessUnitsTbody) {
        businessUnitsTbody.innerHTML = businessUnits.length
            ? businessUnits.map(item => `
                <tr>
                    <td>${item.name || 'Подразделение'}<div class="finance-row-meta">${item.code || 'Без кода'}</div></td>
                    <td>${item.legal_entity_name || 'Юрлицо не задано'}<div class="finance-row-meta">${item.manager_name || 'Руководитель не указан'}</div></td>
                    <td><span class="status-badge ${item.is_active ? 'status-active' : 'status-archived'}">${item.is_active ? 'Активно' : 'Архив'}</span></td>
                </tr>
            `).join('')
            : '<tr><td colspan="3" class="nsi-empty-row">Подразделений пока нет.</td></tr>';
    }
    if (articlesTbody) {
        articlesTbody.innerHTML = treasuryArticles.length
            ? treasuryArticles.map(item => `
                <tr>
                    <td>${item.name || 'Статья ДДС'}<div class="finance-row-meta">${item.code || 'Без кода'} · ${item.category || 'Без категории'}</div></td>
                    <td>${item.flow_kind === 'outgoing' ? 'Исходящий поток' : 'Входящий поток'}</td>
                    <td><span class="status-badge ${item.is_active ? 'status-active' : 'status-archived'}">${item.is_active ? 'Активно' : 'Архив'}</span></td>
                </tr>
            `).join('')
            : '<tr><td colspan="3" class="nsi-empty-row">Статей ДДС пока нет.</td></tr>';
    }
    if (vatRatesTbody) {
        vatRatesTbody.innerHTML = vatRates.length
            ? vatRates.map(item => `
                <tr>
                    <td>${item.name || 'Ставка НДС'}</td>
                    <td>${Number(item.rate || 0).toLocaleString('ru-RU')} %<div class="finance-row-meta">${item.is_default ? 'По умолчанию' : 'Обычная'}</div></td>
                    <td><span class="status-badge ${item.is_active ? 'status-active' : 'status-archived'}">${item.is_active ? 'Активно' : 'Архив'}</span></td>
                </tr>
            `).join('')
            : '<tr><td colspan="3" class="nsi-empty-row">Ставок НДС пока нет.</td></tr>';
    }
}

function renderFinanceRoleWorkbench(metrics = {}) {
    const mount = document.getElementById('financeRoleWorkbenchMount');
    if (!mount || !currentUser) return;
    const role = String(currentUser.role || '').trim();
    if (role === 'Бухгалтерия') {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Бухгалтерский день</div>
                    <h3 class="section-title">Платежи, дебиторка, сверка и закрытие</h3>
                    <p class="section-subtitle">Операционный платёжный день должен идти сверху, а глубокий учёт и аналитика ниже как второй слой.</p>
                </div>
                <div class="role-workbench-stats">
                    <div class="role-workbench-stat"><span>Открытые выплаты</span><strong>${formatMoney(metrics.outgoing_open || 0)}</strong></div>
                    <div class="role-workbench-stat"><span>Просроченная дебиторка</span><strong>${formatMoney(metrics.overdue_receivables || 0)}</strong></div>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="presetFinanceFlow('outgoing')">Новый платёж</button>
                    <button class="btn-secondary" onclick="setFinanceFilter('overdue')">Дебиторка</button>
                    <button class="btn-secondary" onclick="document.getElementById('reconciliationClientId')?.focus()">Сверка</button>
                    <button class="btn-secondary" onclick="document.getElementById('financeClosePeriodSection')?.scrollIntoView({behavior:'smooth', block:'start'})">Закрытие периода</button>
                </div>
            </section>
        `;
        return;
    }
    if (role === 'Директор') {
        mount.innerHTML = `
            <section class="surface-card surface-card--padded role-workbench role-workbench--compact">
                <div class="role-workbench-copy">
                    <div class="view-eyebrow">Деньги</div>
                    <h3 class="section-title">Короткий управленческий вход в финансы</h3>
                    <p class="section-subtitle">Первый экран нужен для вопроса “где риск и что требует решения”, а не для всей бухгалтерской глубины сразу.</p>
                </div>
                <div class="role-workbench-actions">
                    <button class="btn-primary" onclick="setFinanceFilter('overdue')">Риски</button>
                    <button class="btn-secondary" onclick="presetFinanceFlow('outgoing')">Оплаты</button>
                    <button class="btn-secondary" onclick="navigateTo('executive')">Панель директора</button>
                </div>
            </section>
        `;
        return;
    }
    mount.innerHTML = '';
}

function resetFinanceForm() {
    releaseFinanceEditLock();
    editingFinancePaymentId = 0;
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('financePaymentForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('financePaymentForm');
    const masterDefaults = financeMasterDataDB?.defaults || {};
    const defaults = {
        financeTitle: '',
        financeProjectId: '0',
        financeClientId: '0',
        financeKind: 'incoming',
        financeCategory: 'payment',
        financeAmount: '',
        financeCurrency: 'RUB',
        financeLegalEntityId: String(masterDefaults.legal_entity_id || 0),
        financeBusinessUnitId: String(masterDefaults.business_unit_id || 0),
        financeTreasuryArticleId: '0',
        financeVatRateId: String(masterDefaults.vat_rate_id || 0),
        financeDueDate: '',
        financePaidDate: '',
        financeSourceDocumentType: '',
        financeSourceDocumentId: '',
        financeStatus: 'planned',
        financeComment: '',
    };
    Object.entries(defaults).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    syncFinanceArticleOptions();
    void applyFinanceFieldPermissions();
    if (typeof clearFormDraft === 'function') clearFormDraft('finance_payment');
}

window.openFinanceOperationForm = function() {
    const panel = document.getElementById('financeClosePeriodSection');
    if (!panel) return;
    panel.classList.add('is-open');
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.closeFinanceOperationForm = function() {
    document.getElementById('financeClosePeriodSection')?.classList.remove('is-open');
};

window.startFinanceOperation = function() {
    resetFinanceForm();
    openFinanceOperationForm();
    window.setTimeout(() => document.getElementById('financeTitle')?.focus(), 250);
};

window.cancelFinanceOperation = function() {
    resetFinanceForm();
    closeFinanceOperationForm();
};

async function editFinancePayment(paymentId) {
    const payment = financePaymentsDB.find(item => item.id === paymentId);
    if (!payment) return;
    const lockOk = await acquireFinanceEditLock(paymentId);
    if (!lockOk) return;
    editingFinancePaymentId = paymentId;
    document.getElementById('financeTitle').value = payment.title || '';
    document.getElementById('financeProjectId').value = String(payment.project_id || 0);
    document.getElementById('financeClientId').value = String(payment.client_id || 0);
    document.getElementById('financeKind').value = payment.kind || 'incoming';
    document.getElementById('financeCategory').value = payment.category || 'payment';
    document.getElementById('financeAmount').value = payment.amount || '';
    document.getElementById('financeCurrency').value = payment.currency || 'RUB';
    document.getElementById('financeLegalEntityId').value = String(payment.legal_entity_id || 0);
    document.getElementById('financeBusinessUnitId').value = String(payment.business_unit_id || 0);
    syncFinanceArticleOptions(payment.treasury_article_id || 0);
    document.getElementById('financeVatRateId').value = String(payment.vat_rate_id || 0);
    document.getElementById('financeDueDate').value = payment.due_date || '';
    document.getElementById('financePaidDate').value = payment.paid_date || '';
    document.getElementById('financeSourceDocumentType').value = payment.source_document_type || '';
    document.getElementById('financeSourceDocumentId').value = payment.source_document_id || '';
    document.getElementById('financeStatus').value = payment.status || 'planned';
    document.getElementById('financeComment').value = payment.comment || '';
    await applyFinanceFieldPermissions();
    openFinanceOperationForm();
}

function financePaymentCardField(label, value, options = {}) {
    const safeValue = String(value || '').trim() || 'Не указано';
    return `
        <div class="finance-payment-card__field${options.wide ? ' finance-payment-card__field--wide' : ''}">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(safeValue)}</strong>
        </div>
    `;
}

window.openFinancePaymentCard = function(paymentId) {
    const payment = financePaymentsDB.find(item => Number(item.id) === Number(paymentId));
    const modal = document.getElementById('genericModal');
    const title = document.getElementById('genModalTitle');
    const body = document.getElementById('genModalBody');
    const footer = document.getElementById('genModalFooter');
    if (!payment || !modal || !title || !body || !footer) return;

    const categoryLabels = {
        payment: 'Оплата',
        invoice: 'Счёт на оплату',
        advance: 'Аванс',
        expense: 'Расход',
        act: 'Акт / закрытие',
    };
    const sourceLabel = payment.source_document_type
        ? financeTranslateLabel(payment.source_document_type, payment.source_document_type)
        : 'Не указан';
    const canUpdate = (currentPermissions.finance || []).includes('update');
    const isPaid = payment.status === 'paid';

    title.innerText = payment.title || `Финансовая операция №${payment.id}`;
    body.innerHTML = `
        <article class="finance-payment-card">
            <div class="finance-payment-card__hero">
                <div>
                    <span>${payment.kind === 'incoming' ? 'Поступление денег' : 'Выплата денег'}</span>
                    <strong>${formatMoney(payment.amount, payment.currency)}</strong>
                </div>
                <span class="status-badge ${financeStatusClass(payment.status)}">${escapeHtml(financeStatusLabel(payment.status))}</span>
            </div>
            <section class="finance-payment-card__section">
                <h3>Все данные операции</h3>
                <div class="finance-payment-card__grid">
                    ${financePaymentCardField('Название или номер счёта', payment.title, { wide: true })}
                    ${financePaymentCardField('Проект', financeDisplayName(payment.project_contract || payment.project_name, 'Без проекта'))}
                    ${financePaymentCardField('Договор', payment.contract_number || (Number(payment.contract_id || 0) > 0 ? `Договор #${Number(payment.contract_id)}` : 'Без договора'))}
                    ${financePaymentCardField('Клиент или поставщик', payment.client_name)}
                    ${financePaymentCardField('Тип движения', payment.kind === 'incoming' ? 'Поступление денег' : 'Выплата денег')}
                    ${financePaymentCardField('Что фиксируем', categoryLabels[payment.category] || payment.category)}
                    ${financePaymentCardField('Сумма', formatMoney(payment.amount, payment.currency))}
                    ${financePaymentCardField('Валюта', payment.currency || 'RUB')}
                    ${financePaymentCardField('Юридическое лицо', payment.legal_entity_name)}
                    ${financePaymentCardField('Подразделение', payment.business_unit_name)}
                    ${financePaymentCardField('Статья ДДС', payment.treasury_article_name)}
                    ${financePaymentCardField('Ставка НДС', payment.vat_rate_name)}
                    ${financePaymentCardField('Оплатить до', payment.due_date)}
                    ${financePaymentCardField('Дата оплаты', payment.paid_date)}
                    ${financePaymentCardField('Источник документа', sourceLabel)}
                    ${financePaymentCardField('ID документа-источника', payment.source_document_id)}
                    ${financePaymentCardField('Статус', financeStatusLabel(payment.status))}
                    ${financePaymentCardField('Комментарий (необязательно)', payment.comment || 'Комментарий не добавлен.', { wide: true })}
                </div>
            </section>
        </article>
    `;
    footer.innerHTML = `
        ${canUpdate && !isPaid ? `<button class="btn-success" type="button" onclick="markFinancePaymentPaidFromCard(${Number(payment.id)})">Оплачено</button>` : ''}
        ${Number(payment.contract_id || 0) > 0 ? `<button class="btn-secondary" type="button" onclick="closeGenericModal(); openContractCard(${Number(payment.contract_id)})">Открыть договор</button>` : ''}
        ${canUpdate ? `<button class="btn-primary" type="button" onclick="editFinancePaymentFromCard(${Number(payment.id)})">Редактировать</button>` : ''}
        <button class="btn-secondary" type="button" id="genClose">Закрыть</button>
    `;
    document.getElementById('genClose').onclick = closeGenericModal;
    modal.style.display = 'flex';
};

window.editFinancePaymentFromCard = function(paymentId) {
    closeGenericModal();
    editFinancePayment(paymentId);
};

window.markFinancePaymentPaidFromCard = async function(paymentId) {
    closeGenericModal();
    await markFinancePaymentPaid(paymentId);
};

function syncFinanceArticleOptions(preferredId = 0) {
    const articleSelect = document.getElementById('financeTreasuryArticleId');
    if (!articleSelect || !financeMasterDataDB) return;
    const preferredKind = document.getElementById('financeKind')?.value || 'incoming';
    const defaults = financeMasterDataDB.defaults || {};
    articleSelect.innerHTML = `<option value="0">Статья ДДС</option>${(financeMasterDataDB.treasury_articles || [])
        .filter(item => item.flow_kind === preferredKind)
        .map(item => `<option value="${item.id}">${item.name}</option>`)
        .join('')}`;
    articleSelect.value = String(preferredId || defaults.treasury_article_id || 0);
}

async function applyFinanceFieldPermissions() {
    if (typeof applyFieldPermissionsWithFeedback === 'function') {
        await applyFieldPermissionsWithFeedback('finance', 'finance_payment', financeFormFieldMap, 'financePolicyBanner');
        return;
    }
    if (typeof applyFieldPermissionsToForm === 'function') {
        applyFieldPermissionsToForm('finance', 'finance_payment', financeFormFieldMap);
    }
}

async function releaseFinanceEditLock(force = 0) {
    if (!financeEditLockId) return;
    await apiCall('/locks/release', 'POST', {
        entity_type: 'finance_payment',
        entity_id: String(financeEditLockId),
        force: Number(force || 0),
    });
    financeEditLockId = 0;
}

async function acquireFinanceEditLock(paymentId) {
    await releaseFinanceEditLock();
    if (!paymentId) return true;
    const res = await apiCall('/locks/acquire', 'POST', {
        entity_type: 'finance_payment',
        entity_id: String(paymentId),
        force: 0,
    });
    if (!res || res.error) {
        const owner = res?.lock?.actor_name || res?.lock?.actor_email || 'другим пользователем';
        await customAlert(`Финансовая операция сейчас редактируется ${owner}.`);
        return false;
    }
    financeEditLockId = Number(paymentId || 0);
    return true;
}

function getTodayRuDate() {
    const now = new Date();
    return `${String(now.getDate()).padStart(2, '0')}.${String(now.getMonth() + 1).padStart(2, '0')}.${now.getFullYear()}`;
}

function pruneSelectedFinancePayments() {
    const ids = new Set(financePaymentsDB.map(item => Number(item.id)));
    selectedFinancePayments.forEach(id => {
        if (!ids.has(Number(id))) selectedFinancePayments.delete(Number(id));
    });
}

function getVisibleFinancePayments() {
    const searchInput = document.getElementById('financeRegistrySearch');
    const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
    if (!query) return financePaymentsDB.slice();
    return financePaymentsDB.filter(payment => {
        const haystack = [
            payment.title || '',
            payment.project_contract || '',
            payment.project_name || '',
            payment.client_name || '',
            payment.comment || '',
            payment.category || '',
        ].join(' ').toLowerCase();
        return haystack.includes(query);
    });
}

window.clearFinanceRegistrySearch = function() {
    const input = document.getElementById('financeRegistrySearch');
    if (input) input.value = '';
    renderFinancePayments();
};

window.toggleFinanceExtraFields = function(button) {
    const form = document.getElementById('financePaymentForm');
    if (!form) return;
    const isOpen = form.classList.toggle('finance-show-extra');
    if (button) button.textContent = isOpen ? 'Скрыть дополнительные реквизиты' : 'Дополнительные реквизиты';
};

function getSelectedFinanceRows() {
    pruneSelectedFinancePayments();
    return financePaymentsDB.filter(item => selectedFinancePayments.has(Number(item.id)));
}

function updateFinanceBulkBar(visibleRows = getVisibleFinancePayments()) {
    const summary = document.getElementById('financeBulkSummary');
    const selectAllCheckbox = document.getElementById('financeSelectAllCheckbox');
    const canUpdate = currentPermissions.finance && currentPermissions.finance.includes('update');
    const canDelete = currentPermissions.finance && currentPermissions.finance.includes('delete');
    const selectedCount = selectedFinancePayments.size;
    if (summary) {
        summary.innerText = selectedCount ? `Выделено операций: ${selectedCount}` : 'Выделение: 0 операций';
    }
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = visibleRows.length > 0 && visibleRows.every(row => selectedFinancePayments.has(Number(row.id)));
        selectAllCheckbox.indeterminate = visibleRows.length > 0 && !selectAllCheckbox.checked && visibleRows.some(row => selectedFinancePayments.has(Number(row.id)));
    }
    const clearBtn = document.getElementById('financeBulkClearBtn');
    const exportBtn = document.getElementById('financeBulkExportBtn');
    const paidBtn = document.getElementById('financeBulkPaidBtn');
    const overdueBtn = document.getElementById('financeBulkOverdueBtn');
    const deleteBtn = document.getElementById('financeBulkDeleteBtn');
    if (clearBtn) clearBtn.disabled = selectedCount === 0;
    if (exportBtn) exportBtn.disabled = selectedCount === 0;
    if (paidBtn) paidBtn.disabled = selectedCount === 0 || !canUpdate;
    if (overdueBtn) overdueBtn.disabled = selectedCount === 0 || !canUpdate;
    if (deleteBtn) deleteBtn.disabled = selectedCount === 0 || !canDelete;
}

window.toggleFinanceSelection = function(paymentId, checked) {
    const numericId = Number(paymentId);
    if (checked) selectedFinancePayments.add(numericId);
    else selectedFinancePayments.delete(numericId);
    updateFinanceBulkBar();
};

window.toggleAllFinanceOnPage = function(forceState) {
    const visibleRows = getVisibleFinancePayments();
    if (!visibleRows.length) return;
    const shouldSelect = typeof forceState === 'boolean'
        ? forceState
        : !visibleRows.every(row => selectedFinancePayments.has(Number(row.id)));
    visibleRows.forEach(row => {
        if (shouldSelect) selectedFinancePayments.add(Number(row.id));
        else selectedFinancePayments.delete(Number(row.id));
    });
    renderFinance();
};

window.clearSelectedFinancePayments = function() {
    selectedFinancePayments.clear();
    updateFinanceBulkBar();
    renderFinance();
};

function buildFinancePayload(payment, updates = {}) {
    return {
        title: payment.title || '',
        project_id: Number(payment.project_id || 0),
        client_id: Number(payment.client_id || 0),
        contract_id: Number(payment.contract_id || 0),
        object_id: Number(payment.object_id || 0),
        legal_entity_id: Number(payment.legal_entity_id || 0),
        business_unit_id: Number(payment.business_unit_id || 0),
        treasury_article_id: Number(payment.treasury_article_id || 0),
        vat_rate_id: Number(payment.vat_rate_id || 0),
        source_document_type: payment.source_document_type || '',
        source_document_id: Number(payment.source_document_id || 0),
        kind: payment.kind || 'incoming',
        category: payment.category || 'payment',
        amount: Number(payment.amount || 0),
        currency: payment.currency || 'RUB',
        due_date: payment.due_date || '',
        paid_date: payment.paid_date || '',
        status: payment.status || 'planned',
        comment: payment.comment || '',
        ...updates,
    };
}

async function updateFinancePaymentQuick(paymentId, updates, successMessage = '', options = {}) {
    const payment = financePaymentsDB.find(item => item.id === paymentId);
    if (!payment) return;
    const payload = buildFinancePayload(payment, updates);
    const lockOk = await acquireFinanceEditLock(paymentId);
    if (!lockOk) return { error: 'locked' };
    const res = await apiCall(`/finance/payments/${paymentId}`, 'PUT', payload);
    await releaseFinanceEditLock();
    if (!res || res.error) {
        return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось обновить финансовую операцию.');
    }
    if (options.refresh !== false) {
        await renderFinance();
        if (currentClient360Id) await loadClient360(currentClient360Id);
    }
    if (options.toast !== false && successMessage) {
        showToast('Финансы', successMessage);
    }
    return res;
}

window.markFinancePaymentPaid = async function(paymentId) {
    await updateFinancePaymentQuick(paymentId, { status: 'paid', paid_date: getTodayRuDate() }, 'Операция отмечена как оплаченная');
};

window.markFinancePaymentOverdue = async function(paymentId) {
    await updateFinancePaymentQuick(paymentId, { status: 'overdue' }, 'Операция отмечена как просроченная');
};

window.deleteFinancePayment = async function(paymentId) {
    const confirmed = await customConfirm('Удалить финансовую операцию безвозвратно?');
    if (!confirmed) return;
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('finance', 'finance_payment', 'delete');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/finance/payments/${paymentId}`, 'DELETE');
    if (!res || res.error) {
        return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось удалить финансовую операцию.');
    }
    await renderFinance();
    if (currentClient360Id) await loadClient360(currentClient360Id);
    showToast('Финансы', 'Операция удалена');
};

window.postFinancePayment = async function(paymentId) {
    if (typeof guardDangerousAction === 'function') {
        const guard = await guardDangerousAction('finance', 'finance_payment', 'post');
        if (!guard.allowed) return;
    }
    const res = await apiCall(`/finance/payments/${paymentId}/post`, 'POST');
    if (!res || res.error || res.detail) {
        return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.detail || res?.error || 'Не удалось провести финансовую операцию.'));
    }
    await renderFinance();
    showToast('Финансы', 'Операция проведена в журнале');
};

window.signFinancePaymentEdo = async function(paymentId) {
    const signerRole = (currentUser?.role || '').trim() || 'Бухгалтерия';
    const thumbprint = await customPrompt('Укажи отпечаток сертификата / thumbprint для ЭДО:', '');
    if (thumbprint === null) return;
    const res = await apiCall('/finance/edo_signatures', 'POST', {
        entity_type: 'finance_payment',
        entity_id: Number(paymentId || 0),
        signer_name: currentUser?.name || '',
        signer_role: signerRole,
        certificate_thumbprint: (thumbprint || '').trim(),
        signature_provider: '1С-ЭДО',
        signature_status: 'signed',
        signed_at: getTodayRuDate(),
        comment: 'Подписано из финансового контура',
    });
    if (!res || res.error) {
        return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : 'Не удалось зарегистрировать подпись ЭДО.');
    }
    await renderFinance();
    showToast('Финансы', 'Подпись ЭДО добавлена');
};

window.openFinanceProject = function(projectId) {
    if (!projectId) return customAlert('У этой операции нет привязки к проекту.');
    openProject(projectId);
};

window.duplicateFinancePayment = async function(paymentId) {
    const payment = financePaymentsDB.find(item => item.id === paymentId);
    if (!payment) return;
    const payload = {
        title: `${payment.title || 'Операция'} (копия)`,
        project_id: Number(payment.project_id || 0),
        client_id: Number(payment.client_id || 0),
        contract_id: Number(payment.contract_id || 0),
        object_id: Number(payment.object_id || 0),
        legal_entity_id: Number(payment.legal_entity_id || 0),
        business_unit_id: Number(payment.business_unit_id || 0),
        treasury_article_id: Number(payment.treasury_article_id || 0),
        vat_rate_id: Number(payment.vat_rate_id || 0),
        source_document_type: payment.source_document_type || '',
        source_document_id: Number(payment.source_document_id || 0),
        kind: payment.kind || 'incoming',
        category: payment.category || 'payment',
        amount: Number(payment.amount || 0),
        currency: payment.currency || 'RUB',
        due_date: payment.due_date || '',
        paid_date: '',
        status: payment.status === 'paid' ? 'planned' : (payment.status || 'planned'),
        comment: payment.comment || '',
    };
    const res = await apiCall('/finance/payments', 'POST', payload);
    if (!res || res.error) {
        return customAlert('Не удалось продублировать финансовую операцию.');
    }
    await renderFinance();
    if (currentClient360Id) await loadClient360(currentClient360Id);
    showToast('Финансы', 'Операция продублирована');
};

window.exportFinanceToExcel = function() {
    exportFinanceRowsToExcel(getVisibleFinancePayments(), financeFilter);
};

function exportFinanceRowsToExcel(rows, suffix = 'all') {
    if (typeof XLSX === 'undefined') {
        return customAlert('Модуль экспорта пока не загрузился. Обновите страницу и попробуйте ещё раз.');
    }
    if (!rows.length) {
        return customAlert('По текущему фильтру нет финансовых операций для выгрузки.');
    }
    const exportRows = rows.map(payment => ({
        'Операция': payment.title || '',
        'Проект': payment.project_contract || payment.project_name || '',
        'Контрагент': payment.client_name || '',
        'Тип потока': payment.kind === 'incoming' ? 'Входящий' : 'Исходящий',
        'Категория': payment.category || '',
        'Сумма': Number(payment.amount || 0),
        'Валюта': payment.currency || 'RUB',
        'Плановая дата': payment.due_date || '',
        'Дата оплаты': payment.paid_date || '',
        'Статус': financeStatusLabel(payment.status),
        'Комментарий': payment.comment || '',
    }));
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Финансы');
    const now = new Date();
    const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    XLSX.writeFile(workbook, `korda-finance-${suffix}-${stamp}.xlsx`);
    showToast('Финансы', `Выгружено операций: ${exportRows.length}`);
}

window.exportSelectedFinanceToExcel = function() {
    exportFinanceRowsToExcel(getSelectedFinanceRows(), 'selected');
};

async function bulkUpdateFinancePayments(updater, successMessage) {
    const rows = getSelectedFinanceRows();
    if (!rows.length) {
        return customAlert('Сначала выделите финансовые операции.');
    }
    for (const row of rows) {
        const result = await updater(row);
        if (result && result.error) {
            return customAlert(`Не удалось обработать операцию "${row.title || row.id}".`);
        }
    }
    await renderFinance();
    if (currentClient360Id) await loadClient360(currentClient360Id);
    showToast('Финансы', successMessage.replace('{count}', String(rows.length)));
}

window.bulkMarkFinancePaymentsPaid = async function() {
    const rows = getSelectedFinanceRows();
    if (!rows.length) {
        return customAlert('Сначала выделите финансовые операции.');
    }
    const confirmed = await customConfirm(`Отметить как оплаченные ${rows.length} операций?`);
    if (!confirmed) return;
    await bulkUpdateFinancePayments(
        row => updateFinancePaymentQuick(row.id, { status: 'paid', paid_date: getTodayRuDate() }, '', { refresh: false, toast: false }),
        'Как оплаченные отмечено операций: {count}',
    );
};

window.bulkMarkFinancePaymentsOverdue = async function() {
    const rows = getSelectedFinanceRows();
    if (!rows.length) {
        return customAlert('Сначала выделите финансовые операции.');
    }
    const confirmed = await customConfirm(`Пометить как просроченные ${rows.length} операций?`);
    if (!confirmed) return;
    await bulkUpdateFinancePayments(
        row => updateFinancePaymentQuick(row.id, { status: 'overdue' }, '', { refresh: false, toast: false }),
        'Как просроченные отмечено операций: {count}',
    );
};

window.bulkDeleteFinancePayments = async function() {
    const rows = getSelectedFinanceRows();
    if (!rows.length) {
        return customAlert('Сначала выделите финансовые операции.');
    }
    const confirmed = await customConfirm(`Удалить ${rows.length} финансовых операций безвозвратно?`);
    if (!confirmed) return;
    await bulkUpdateFinancePayments(
        row => apiCall(`/finance/payments/${row.id}`, 'DELETE'),
        'Удалено операций: {count}',
    );
    selectedFinancePayments.clear();
};

async function saveFinancePayment() {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('financePaymentForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('financePaymentForm');
    const wasEditing = !!editingFinancePaymentId;
    const payload = {
        title: document.getElementById('financeTitle').value.trim(),
        project_id: Number(document.getElementById('financeProjectId').value || 0),
        client_id: Number(document.getElementById('financeClientId').value || 0),
        legal_entity_id: Number(document.getElementById('financeLegalEntityId').value || 0),
        business_unit_id: Number(document.getElementById('financeBusinessUnitId').value || 0),
        treasury_article_id: Number(document.getElementById('financeTreasuryArticleId').value || 0),
        vat_rate_id: Number(document.getElementById('financeVatRateId').value || 0),
        source_document_type: document.getElementById('financeSourceDocumentType').value || '',
        source_document_id: Number(document.getElementById('financeSourceDocumentId').value || 0),
        kind: document.getElementById('financeKind').value,
        category: document.getElementById('financeCategory').value,
        amount: Number((document.getElementById('financeAmount').value || '').replace(',', '.')) || 0,
        currency: document.getElementById('financeCurrency').value,
        due_date: document.getElementById('financeDueDate').value.trim(),
        paid_date: document.getElementById('financePaidDate').value.trim(),
        status: document.getElementById('financeStatus').value,
        comment: document.getElementById('financeComment').value.trim(),
    };

    const errors = [];
    if (!payload.title) {
        errors.push({ field: 'financeTitle', message: 'Укажите название операции.' });
    }
    if (!payload.amount) {
        errors.push({ field: 'financeAmount', message: 'Укажите сумму операции.' });
    }
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'financePaymentForm');
        return;
    }
    if (editingFinancePaymentId) {
        const lockOk = await acquireFinanceEditLock(editingFinancePaymentId);
        if (!lockOk) return;
    }

    const endpoint = editingFinancePaymentId ? `/finance/payments/${editingFinancePaymentId}` : '/finance/payments';
    const method = editingFinancePaymentId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (editingFinancePaymentId) {
        await releaseFinanceEditLock();
    }
    if (!res || res.error) {
        return customAlert(typeof explainApiPolicyError === 'function' ? explainApiPolicyError(res) : (res?.error || 'Не удалось сохранить финансовую операцию.'));
    }
    if (typeof markWorkflowFocus === 'function') {
        markWorkflowFocus('finance', Number(res.id || editingFinancePaymentId || 0));
    }

    resetFinanceForm();
    closeFinanceOperationForm();
    financeFilter = 'all';
    await renderFinance();
    if (currentClient360Id) await loadClient360(currentClient360Id);
    showToast('Финансы', wasEditing ? 'Операция обновлена' : 'Операция создана');
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('[data-finance-id].workflow-row-highlight, [data-finance-id]');
}

window.presetFinanceFlow = function(kind = 'incoming') {
    openFinanceOperationForm();
    const kindEl = document.getElementById('financeKind');
    const categoryEl = document.getElementById('financeCategory');
    const statusEl = document.getElementById('financeStatus');
    const titleEl = document.getElementById('financeTitle');
    if (kindEl) kindEl.value = kind;
    if (categoryEl) categoryEl.value = kind === 'incoming' ? 'payment' : 'expense';
    if (statusEl) statusEl.value = 'planned';
    if (titleEl && !titleEl.value.trim()) {
        titleEl.value = kind === 'incoming' ? 'Поступление от контрагента' : 'Исходящая оплата';
    }
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('#financePaymentForm', { block: 'center' });
    if (typeof focusFieldById === 'function') focusFieldById('financeTitle');
};

window.presetFinanceInvoice = function() {
    resetFinanceForm();
    openFinanceOperationForm();
    const kindEl = document.getElementById('financeKind');
    const categoryEl = document.getElementById('financeCategory');
    const statusEl = document.getElementById('financeStatus');
    const titleEl = document.getElementById('financeTitle');
    if (kindEl) kindEl.value = 'incoming';
    if (categoryEl) categoryEl.value = 'invoice';
    if (statusEl) statusEl.value = 'planned';
    if (titleEl) titleEl.value = 'Ожидаемая оплата по счёту';
    syncFinanceArticleOptions();
    window.setTimeout(() => document.getElementById('financeClientId')?.focus(), 250);
};

function setFinanceFilter(filter) {
    financeFilter = filter;
    renderFinance();
}

function registerFinanceSavedFilters() {
    setFinanceFilterButtonState();
}

function renderFinanceErpMetrics() {
    const target = document.getElementById('financeErpMetricsGrid');
    if (!target) return;
    const metrics = financeErpSummaryDB?.metrics || {};
    target.innerHTML = `
        <div class="metric-card"><div class="metric-title">Проведено</div><div class="metric-value">${formatMoney(metrics.posted_total || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">Очередь 1С</div><div class="metric-value">${metrics.queued_sync || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Ошибки обмена</div><div class="metric-value">${metrics.failed_sync || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Конфликты обмена</div><div class="metric-value">${metrics.sync_conflicts || 0}</div></div>
        <div class="metric-card"><div class="metric-title">Открытые периоды</div><div class="metric-value">${metrics.open_periods || 0}</div></div>
        <div class="metric-card success"><div class="metric-title">ЭДО подписано</div><div class="metric-value">${metrics.edo_signed || 0}</div></div>
        <div class="metric-card warning"><div class="metric-title">Нарушения лимитов</div><div class="metric-value">${metrics.limit_breaches || 0}</div></div>
    `;
}

function renderFinanceCockpit(visiblePayments) {
    const target = document.getElementById('financeCockpitMount');
    if (!target) return;
    const analyticsMetrics = financeAnalyticsDB?.metrics || {};
    const erpMetrics = financeErpSummaryDB?.metrics || {};
    const overdueCount = visiblePayments.filter(item => item.status === 'overdue').length;
    const issuedCount = visiblePayments.filter(item => item.status === 'issued').length;
    const plannedIncoming = visiblePayments
        .filter(item => item.kind === 'incoming' && item.status !== 'paid')
        .reduce((sum, item) => sum + Number(item.amount || 0), 0);
    const plannedOutgoing = visiblePayments
        .filter(item => item.kind === 'outgoing' && item.status !== 'paid')
        .reduce((sum, item) => sum + Number(item.amount || 0), 0);
    const topProject = Array.isArray(financeAnalyticsDB?.top_projects) ? financeAnalyticsDB.top_projects[0] : null;
    const warnings = [];
    if (overdueCount) warnings.push(`Просрочено ${overdueCount} операций`);
    if ((erpMetrics.failed_sync || 0) > 0) warnings.push(`Ошибок 1С: ${erpMetrics.failed_sync || 0}`);
    if ((erpMetrics.limit_breaches || 0) > 0) warnings.push(`Лимиты нарушены: ${erpMetrics.limit_breaches || 0}`);
    if ((analyticsMetrics.cash_gap_plan || 0) < 0) warnings.push(`Кассовый разрыв ${formatMoney(analyticsMetrics.cash_gap_plan || 0)}`);
    target.innerHTML = `
        <section class="surface-card surface-card--padded erp-cockpit-card">
            <div class="erp-cockpit-heading">
                <div>
                    <h3 class="section-title">Финансовый обзор</h3>
                    <p class="section-subtitle">Короткий срез для ежедневного решения: что горит по оплатам, 1С и лимитам.</p>
                </div>
                <span class="ops-section-chip">Фокус</span>
            </div>
            <div class="erp-cockpit-stats">
                <div class="erp-cockpit-stat">
                    <div class="erp-cockpit-label">К оплате / к поступлению</div>
                    <div class="erp-cockpit-value">${formatMoney(plannedOutgoing)} / ${formatMoney(plannedIncoming)}</div>
                </div>
                <div class="erp-cockpit-stat">
                    <div class="erp-cockpit-label">Выставлено / просрочено</div>
                    <div class="erp-cockpit-value">${issuedCount} / ${overdueCount}</div>
                </div>
                <div class="erp-cockpit-stat">
                    <div class="erp-cockpit-label">Маржа факт / план</div>
                    <div class="erp-cockpit-value">${formatMoney(analyticsMetrics.pnl_fact || 0)} / ${formatMoney(analyticsMetrics.pnl_plan || 0)}</div>
                </div>
            </div>
        </section>
        <section class="surface-card surface-card--padded erp-cockpit-card">
            <div class="erp-cockpit-heading">
                <div>
                    <h3 class="section-title">Следующий управленческий фокус</h3>
                    <p class="section-subtitle">${topProject ? 'Самый заметный проект по марже и открытым суммам.' : 'Как только появятся проектные данные, здесь будет главный фокус дня.'}</p>
                </div>
            </div>
            ${topProject ? `
                <div class="erp-cockpit-highlight">
                    <div class="erp-cockpit-highlight-title">${financeDisplayName(topProject.project_label, 'Без проекта')}</div>
                    <div class="erp-cockpit-highlight-meta">Маржа факт ${formatMoney(topProject.fact_margin || 0)} · открыто ${formatMoney(topProject.receivable_open || 0)} / ${formatMoney(topProject.payable_open || 0)}</div>
                </div>
            ` : '<div class="empty-state">Проектная маржинальность пока не собрана.</div>'}
            <div class="erp-cockpit-alerts">
                ${(warnings.length ? warnings : ['Критичных сигналов по финансам сейчас нет.']).map(item => `<div class="erp-cockpit-alert">${item}</div>`).join('')}
            </div>
        </section>
    `;
}

function renderFinanceAnalytics() {
    const metricsTarget = document.getElementById('financeAnalyticsMetricsGrid');
    const agingTbody = document.getElementById('financeAgingTable');
    const articlesTbody = document.getElementById('financeCashflowArticlesTable');
    const topProjectsTbody = document.getElementById('financeTopProjectsTable');
    const metrics = financeAnalyticsDB?.metrics || {};
    if (metricsTarget) {
        metricsTarget.innerHTML = `
            <div class="metric-card success"><div class="metric-title">P&L факт</div><div class="metric-value">${formatMoney(metrics.pnl_fact || 0)}</div></div>
            <div class="metric-card"><div class="metric-title">P&L план</div><div class="metric-value">${formatMoney(metrics.pnl_plan || 0)}</div></div>
            <div class="metric-card"><div class="metric-title">ДДС входящий факт</div><div class="metric-value">${formatMoney(metrics.dds_in_fact || 0)}</div></div>
            <div class="metric-card warning"><div class="metric-title">ДДС исходящий факт</div><div class="metric-value">${formatMoney(metrics.dds_out_fact || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">План кассового разрыва</div><div class="metric-value">${formatMoney(metrics.cash_gap_plan || 0)}</div></div>
            <div class="metric-card warning"><div class="metric-title">Открытая дебиторка / кредиторка</div><div class="metric-value">${formatMoney(metrics.receivable_open || 0)} / ${formatMoney(metrics.payable_open || 0)}</div></div>
        `;
    }
    if (agingTbody) {
        const receivable = financeAnalyticsDB?.aging?.receivable || {};
        const payable = financeAnalyticsDB?.aging?.payable || {};
        const rows = [
            ['Дебиторка', receivable],
            ['Кредиторка', payable],
        ];
        agingTbody.innerHTML = rows.map(([label, item]) => `
            <tr>
                <td>${label}</td>
                <td>${formatMoney(item.current || 0)}</td>
                <td>${formatMoney(item.bucket_1_30 || 0)}</td>
                <td>${formatMoney(item.bucket_31_60 || 0)}</td>
                <td>${formatMoney(item.bucket_60_plus || 0)}</td>
            </tr>
        `).join('');
    }
    if (articlesTbody) {
        const rows = financeAnalyticsDB?.cashflow_by_article || [];
        articlesTbody.innerHTML = rows.length ? rows.map(item => `
            <tr>
                <td>${item.article_name || 'Статья ДДС'}</td>
                <td>${formatMoney(item.incoming || 0)}</td>
                <td>${formatMoney(item.outgoing || 0)}</td>
                <td>${formatMoney(item.net || 0)}</td>
            </tr>
        `).join('') : '<tr><td colspan="4" class="nsi-empty-row">По статьям ДДС пока нет данных.</td></tr>';
    }
    if (topProjectsTbody) {
        const rows = financeAnalyticsDB?.top_projects || [];
        topProjectsTbody.innerHTML = rows.length ? rows.map(item => `
            <tr>
                <td>${item.project_label || 'Без проекта'}</td>
                <td>${formatMoney(item.incoming_plan || 0)} / ${formatMoney(item.outgoing_plan || 0)}</td>
                <td>${formatMoney(item.incoming_paid || 0)} / ${formatMoney(item.outgoing_paid || 0)}</td>
                <td>${formatMoney(item.receivable_open || 0)} / ${formatMoney(item.payable_open || 0)}</td>
                <td>${formatMoney(item.fact_margin || 0)}<div class="finance-row-meta">План: ${formatMoney(item.plan_margin || 0)}</div></td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="nsi-empty-row">Пока нет проектной маржинальности.</td></tr>';
    }
}

window.saveFinanceMasterRecord = async function(entityType) {
    if (!(currentPermissions.finance || []).includes('manage_master')) {
        return customAlert('Недостаточно прав для изменения мастер-справочников.');
    }
    let payload = null;
    if (entityType === 'legal_entities') {
        payload = {
            name: (document.getElementById('masterLegalEntityName')?.value || '').trim(),
            short_name: (document.getElementById('masterLegalEntityShortName')?.value || '').trim(),
            inn: (document.getElementById('masterLegalEntityInn')?.value || '').trim(),
            kpp: (document.getElementById('masterLegalEntityKpp')?.value || '').trim(),
            vat_mode: 'osno',
            default_currency: 'RUB',
            is_active: 1,
        };
        if (!payload.name) return customAlert('Для юрлица укажи название.');
    } else if (entityType === 'business_units') {
        payload = {
            legal_entity_id: Number(document.getElementById('masterBusinessUnitLegalEntityId')?.value || 0),
            name: (document.getElementById('masterBusinessUnitName')?.value || '').trim(),
            code: (document.getElementById('masterBusinessUnitCode')?.value || '').trim(),
            manager_name: (document.getElementById('masterBusinessUnitManagerName')?.value || '').trim(),
            is_active: 1,
        };
        if (!payload.legal_entity_id || !payload.name) return customAlert('Для подразделения выбери юрлицо и название.');
    } else if (entityType === 'treasury_articles') {
        payload = {
            name: (document.getElementById('masterTreasuryArticleName')?.value || '').trim(),
            code: (document.getElementById('masterTreasuryArticleCode')?.value || '').trim(),
            flow_kind: document.getElementById('masterTreasuryArticleFlowKind')?.value || 'incoming',
            category: (document.getElementById('masterTreasuryArticleCategory')?.value || '').trim(),
            is_active: 1,
        };
        if (!payload.name) return customAlert('Для статьи ДДС укажи название.');
    } else if (entityType === 'vat_rates') {
        payload = {
            name: (document.getElementById('masterVatRateName')?.value || '').trim(),
            rate: Number((document.getElementById('masterVatRateValue')?.value || '').replace(',', '.')) || 0,
            is_default: Number(document.getElementById('masterVatRateDefault')?.value || 0),
            is_active: 1,
        };
        if (!payload.name) return customAlert('Для ставки НДС укажи название.');
    }
    const res = await apiCall(`/finance/master_data/${entityType}`, 'POST', payload);
    if (!res || res.error) {
        return customAlert('Не удалось сохранить запись справочника.');
    }
    ['masterLegalEntityName', 'masterLegalEntityShortName', 'masterLegalEntityInn', 'masterLegalEntityKpp', 'masterBusinessUnitName', 'masterBusinessUnitCode', 'masterBusinessUnitManagerName', 'masterTreasuryArticleName', 'masterTreasuryArticleCode', 'masterTreasuryArticleCategory', 'masterVatRateName', 'masterVatRateValue'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const vatDefault = document.getElementById('masterVatRateDefault');
    if (vatDefault) vatDefault.value = '0';
    await renderFinance();
    showToast('Финансы', 'Запись мастер-справочника сохранена');
};

function renderFinanceJournal() {
    const tbody = document.getElementById('financeJournalTable');
    if (!tbody) return;
    if (!financeJournalDB.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="nsi-empty-row">Проводок пока нет.</td></tr>';
        return;
    }
    tbody.innerHTML = financeJournalDB.map(item => {
        const sourceId = Number(item.source_id || item.payment_id || 0);
        return `
        <tr ${sourceId ? `data-finance-id="${sourceId}"` : ''} class="${sourceId && typeof isWorkflowFocused === 'function' && isWorkflowFocused('finance', sourceId) ? 'workflow-row-highlight' : ''}">
            <td>${item.entry_date || '—'}</td>
            <td>
                <div class="finance-row-title">${item.source_title || item.description || 'Финансовая операция'}</div>
                <div class="finance-row-meta">${item.legal_entity_name || 'Без юрлица'} · ${item.business_unit_name || 'Без подразделения'}</div>
            </td>
            <td>${item.account_debit || '—'} / ${item.account_credit || '—'}</td>
            <td>${formatMoney(item.amount, item.currency)}<div class="finance-row-meta">НДС: ${formatMoney(item.vat_amount || 0, item.currency)}</div></td>
            <td>${item.period_key || '—'}</td>
            <td>${item.project_label || 'Без проекта'}<div class="finance-row-meta">${item.client_name || 'Без контрагента'} · ${item.treasury_article_name || 'Без статьи ДДС'}</div></td>
        </tr>
    `;
    }).join('');
}

function renderFinancePeriodsAndControls() {
    const periodsTbody = document.getElementById('financePeriodsTable');
    const limitsTbody = document.getElementById('financeLimitsTable');
    const actsTbody = document.getElementById('financeReconciliationTable');
    if (periodsTbody) {
        periodsTbody.innerHTML = financePeriodsDB.length
            ? financePeriodsDB.map(item => `
                <tr>
                    <td>${item.period_key || '—'}</td>
                    <td><span class="status-badge ${item.status === 'closed' ? 'status-completed' : 'status-active'}">${financeTranslateLabel(item.status || 'open', 'Открыт')}</span></td>
                    <td>${item.closed_by || '—'}</td>
                    <td>${item.comment || '—'}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="4" class="nsi-empty-row">Периоды пока не сформированы.</td></tr>';
    }
    if (limitsTbody) {
        limitsTbody.innerHTML = treasuryLimitsDB.length
            ? treasuryLimitsDB.map(item => `
                <tr>
                    <td>${item.legal_entity_name || 'Юрлицо'}<div class="finance-row-meta">${item.business_unit_name || 'Подразделение'} · ${item.treasury_article_name || 'Статья ДДС'}</div></td>
                    <td>${item.period_key || '—'}</td>
                    <td>${formatMoney(item.amount_limit || 0)}</td>
                    <td><span class="status-badge ${item.status === 'active' ? 'status-active' : 'status-archived'}">${financeTranslateLabel(item.status || 'active', 'Активный')}</span></td>
                </tr>
            `).join('')
            : '<tr><td colspan="4" class="nsi-empty-row">Лимитов пока нет.</td></tr>';
    }
    if (actsTbody) {
        actsTbody.innerHTML = reconciliationActsDB.length
            ? reconciliationActsDB.map(item => `
                <tr>
                    <td>${item.act_number || '—'}</td>
                    <td>${item.client_name || 'Без контрагента'}<div class="finance-row-meta">${item.contract_number || 'Без договора'}</div></td>
                    <td>${item.period_key || '—'}</td>
                    <td>${formatMoney(item.amount_receivable || 0)} / ${formatMoney(item.amount_payable || 0)}</td>
                    <td><span class="status-badge ${item.status === 'signed' ? 'status-completed' : 'status-active'}">${financeTranslateLabel(item.status || 'draft', 'Черновик')}</span></td>
                </tr>
            `).join('')
            : '<tr><td colspan="5" class="nsi-empty-row">Актов сверки пока нет.</td></tr>';
    }
}

function renderFinanceSyncAndEdo() {
    const syncTbody = document.getElementById('financeSyncQueueTable');
    const conflictsTbody = document.getElementById('financeSyncConflictsTable');
    const edoTbody = document.getElementById('financeEdoTable');
    if (syncTbody) {
        syncTbody.innerHTML = financeSyncQueueDB.length
            ? financeSyncQueueDB.map(item => `
                <tr>
                    <td>${financeTranslateLabel(item.entity_type || 'entity', 'Запись')} #${item.entity_id || '—'}</td>
                    <td><span class="status-badge ${item.state === 'synced' ? 'status-completed' : item.state === 'failed' ? 'status-overdue' : 'status-active'}">${financeTranslateLabel(item.state || 'queued', 'В очереди')}</span></td>
                    <td>${item.external_id || '—'}</td>
                    <td>${item.last_error || '—'}</td>
                    <td><button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="retryFinanceSync(${item.id})">Повторить</button></td>
                </tr>
            `).join('')
            : '<tr><td colspan="5" class="nsi-empty-row">Очередь 1С пока пуста.</td></tr>';
    }
    if (conflictsTbody) {
        conflictsTbody.innerHTML = financeSyncConflictsDB.length
            ? financeSyncConflictsDB.map(item => `
                <tr>
                    <td>${item.created_at ? new Date(Number(item.created_at) * 1000).toLocaleString('ru-RU') : '—'}</td>
                    <td>${financeTranslateLabel(item.entity_type || 'finance_payment', 'Платёж')} #${item.entity_id || '—'}</td>
                    <td>${item.message || 'Конфликт не расшифрован'}</td>
                    <td>${item.external_id || '—'}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="4" class="nsi-empty-row">Конфликтов входящего обмена пока нет.</td></tr>';
    }
    if (edoTbody) {
        edoTbody.innerHTML = financeEdoSignaturesDB.length
            ? financeEdoSignaturesDB.map(item => `
                <tr>
                    <td>${financeTranslateLabel(item.entity_type || 'finance_payment', 'Платёж')} #${item.entity_id || '—'}</td>
                    <td>${item.signer_name || '—'}<div class="finance-row-meta">${item.signer_role || '—'}</div></td>
                    <td><span class="status-badge ${item.signature_status === 'signed' ? 'status-completed' : 'status-active'}">${financeTranslateLabel(item.signature_status || 'signed', 'Подписано')}</span></td>
                    <td>${item.signed_at || '—'}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="4" class="nsi-empty-row">Подписей ЭДО пока нет.</td></tr>';
    }
}

window.clearFinanceInboundSync = function() {
    const payload = document.getElementById('financeInboundSyncPayload');
    const note = document.getElementById('financeInboundSyncNote');
    if (payload) payload.value = '';
    if (note) note.value = '';
    financeInboundPreviewState = null;
    renderFinanceInboundPreview();
};

function parseFinanceInboundSyncPayload() {
    const payloadText = (document.getElementById('financeInboundSyncPayload')?.value || '').trim();
    if (!payloadText) {
        customAlert('Вставь JSON-массив входящего ответа 1С.');
        return null;
    }
    try {
        const items = JSON.parse(payloadText);
        if (!Array.isArray(items) || !items.length) {
            customAlert('Нужен непустой массив элементов обмена.');
            return null;
        }
        return items;
    } catch (error) {
        customAlert('JSON входящего обмена не разобран. Проверь структуру массива.');
        return null;
    }
}

function renderFinanceInboundPreview() {
    const mount = document.getElementById('financeInboundSyncPreview');
    if (!mount) return;
    const preview = financeInboundPreviewState;
    if (!preview) {
        mount.innerHTML = '<div class="nsi-empty-row" style="padding:14px;">Проверка ещё не запускалась. Вставь пакет из 1С и нажми «Проверить пакет».</div>';
        return;
    }
    const rows = Array.isArray(preview.rows) ? preview.rows : [];
    const stateLabel = { ready: 'Готово', conflict: 'Проверить', error: 'Ошибка' };
    const stateClass = { ready: 'status-completed', conflict: 'status-active', error: 'status-overdue' };
    mount.innerHTML = `
        <div class="metric-grid" style="grid-template-columns:repeat(4,minmax(120px,1fr)); margin-bottom:12px;">
            <div class="metric-card"><div class="metric-title">Строк</div><div class="metric-value">${preview.total || 0}</div></div>
            <div class="metric-card"><div class="metric-title">Готово</div><div class="metric-value">${preview.ready || 0}</div></div>
            <div class="metric-card warning"><div class="metric-title">Конфликты</div><div class="metric-value">${preview.conflicts || 0}</div></div>
            <div class="metric-card warning"><div class="metric-title">Ошибки</div><div class="metric-value">${preview.errors || 0}</div></div>
        </div>
        <div class="client360-list">
            ${rows.map(row => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${financeEscapeHtml(row.index)}. ${financeEscapeHtml(row.entity_label || row.entity_type || 'Документ')} ${row.target_id ? `#${financeEscapeHtml(row.target_id)}` : ''}</div>
                        <div class="client360-item-meta">${financeEscapeHtml(row.external_id || 'без внешнего идентификатора')}</div>
                        ${(row.errors || []).map(text => `<div class="finance-row-meta" style="color:#dc2626;">${financeEscapeHtml(text)}</div>`).join('')}
                        ${(row.warnings || []).map(text => `<div class="finance-row-meta" style="color:#b45309;">${financeEscapeHtml(text)}</div>`).join('')}
                        ${(row.changes || []).length ? `<div class="finance-row-meta">${row.changes.map(change => `${financeEscapeHtml(change.field)}: ${financeEscapeHtml(change.before || 'пусто')} -> ${financeEscapeHtml(change.after || 'пусто')}`).join(' · ')}</div>` : ''}
                    </div>
                    <span class="status-badge ${stateClass[row.state] || 'status-active'}">${stateLabel[row.state] || 'Проверить'}</span>
                </div>
            `).join('') || '<div class="nsi-empty-row">Строки не найдены.</div>'}
        </div>
    `;
}

window.previewFinanceInboundSync = async function() {
    const items = parseFinanceInboundSyncPayload();
    if (!items) return null;
    const preview = await apiCall('/finance/sync_queue/inbound/preview', 'POST', {
        items,
        source_system: '1C',
        actor_note: (document.getElementById('financeInboundSyncNote')?.value || '').trim(),
    });
    if (!preview || preview.error) {
        customAlert(preview?.message || preview?.error || 'Не удалось проверить пакет 1С.');
        return null;
    }
    financeInboundPreviewState = preview;
    renderFinanceInboundPreview();
    return preview;
};

window.applyFinanceInboundSync = async function() {
    const items = parseFinanceInboundSyncPayload();
    if (!items) return;
    const preview = await window.previewFinanceInboundSync();
    if (!preview) return;
    if ((preview.errors || 0) > 0) {
        return customAlert('Пакет не применён: исправь ошибки, показанные в предпросмотре.');
    }
    if ((preview.conflicts || 0) > 0) {
        const confirmed = await customConfirm('В пакете есть конфликты. Применить готовые строки и записать конфликтные в журнал обмена?');
        if (!confirmed) return;
    }
    const res = await apiCall('/finance/sync_queue/inbound', 'POST', {
        items,
        source_system: '1C',
        actor_note: (document.getElementById('financeInboundSyncNote')?.value || '').trim(),
    });
    if (!res || res.error) {
        if (res?.status === 'validation_failed') {
            financeInboundPreviewState = res;
            renderFinanceInboundPreview();
            return customAlert(res?.message || 'Пакет не применён: исправь ошибки структуры.');
        }
        return customAlert(res?.message || res?.error || 'Не удалось применить входящий обмен.');
    }
    financeInboundPreviewState = null;
    await renderFinance();
    renderFinanceInboundPreview();
    showToast('Финансы', `Входящий обмен применён: ${res.applied || 0}, конфликтов: ${res.conflicts || 0}`);
};

window.processFinanceSyncQueue = async function() {
    const res = await apiCall('/finance/sync_queue/process?limit=20', 'POST');
    if (!res || res.error) {
        return customAlert('Не удалось обработать очередь 1С.');
    }
    await renderFinance();
    showToast('Финансы', `Очередь обработана: ${res.success || 0} успешно, ${res.failed || 0} с ошибкой`);
};

window.retryFinanceSync = async function(syncId) {
    const res = await apiCall(`/finance/sync_queue/${syncId}/retry`, 'POST');
    if (!res || res.error) {
        return customAlert('Не удалось вернуть задачу в очередь.');
    }
    await renderFinance();
    showToast('Финансы', 'Задача синхронизации отправлена на повтор');
};

window.renderIntegrations = function() {
    if (typeof renderDocumentsOneCImportPreview === 'function') renderDocumentsOneCImportPreview();
    renderFinanceInboundPreview();
};

window.closeFinancePeriod = async function() {
    const period_key = (document.getElementById('financeClosePeriodKey')?.value || '').trim();
    if (!period_key) return customAlert('Укажи период в формате YYYY-MM.');
    const res = await apiCall('/finance/periods/close', 'POST', {
        period_key,
        comment: (document.getElementById('financeClosePeriodComment')?.value || '').trim(),
    });
    if (!res || res.error) {
        return customAlert('Не удалось закрыть период.');
    }
    await renderFinance();
    if (Array.isArray(res.warnings) && res.warnings.length) {
        return customAlert(`Период ${period_key} закрыт с предупреждениями:\n\n${res.warnings.join('\n')}`);
    }
    showToast('Финансы', `Период ${period_key} закрыт`);
};

window.saveTreasuryLimit = async function() {
    const payload = {
        period_key: (document.getElementById('treasuryLimitPeriodKey')?.value || '').trim(),
        legal_entity_id: Number(document.getElementById('treasuryLimitLegalEntityId')?.value || 0),
        business_unit_id: Number(document.getElementById('treasuryLimitBusinessUnitId')?.value || 0),
        treasury_article_id: Number(document.getElementById('treasuryLimitArticleId')?.value || 0),
        amount_limit: Number((document.getElementById('treasuryLimitAmount')?.value || '').replace(',', '.')) || 0,
        status: document.getElementById('treasuryLimitStatus')?.value || 'active',
    };
    if (!payload.period_key || !payload.amount_limit || !payload.treasury_article_id) {
        return customAlert('Для лимита укажи период, статью ДДС и сумму.');
    }
    const res = await apiCall('/finance/treasury_limits', 'POST', payload);
    if (!res || res.error) {
        return customAlert('Не удалось сохранить лимит.');
    }
    await renderFinance();
    showToast('Финансы', 'Лимит сохранён');
};

window.createReconciliationAct = async function() {
    const detailsText = (document.getElementById('reconciliationDetails')?.value || '').trim();
    const payload = {
        client_id: Number(document.getElementById('reconciliationClientId')?.value || 0),
        period_key: (document.getElementById('reconciliationPeriodKey')?.value || '').trim(),
        act_number: (document.getElementById('reconciliationActNumber')?.value || '').trim(),
        amount_receivable: Number((document.getElementById('reconciliationReceivable')?.value || '').replace(',', '.')) || 0,
        amount_payable: Number((document.getElementById('reconciliationPayable')?.value || '').replace(',', '.')) || 0,
        details: detailsText ? { note: detailsText } : {},
        status: 'draft',
    };
    if (!payload.client_id || !payload.period_key) {
        return customAlert('Для акта сверки выбери контрагента и период.');
    }
    const res = await apiCall('/finance/reconciliation_acts', 'POST', payload);
    if (!res || res.error) {
        return customAlert('Не удалось создать акт сверки.');
    }
    await renderFinance();
    showToast('Финансы', `Акт сверки ${res.act_number || ''} создан`);
};

async function renderFinance() {
    const view = document.getElementById('financeView');
    if (!view) return;
    if (!currentPermissions.finance || !currentPermissions.finance.includes('read')) {
        view.innerHTML = `<div class="surface-card surface-card--padded">${typeof renderOnboardingEmptyState === 'function' ? renderOnboardingEmptyState('forbidden') : '<div class="empty-state">У тебя нет доступа к финансовому контуру. Обратись к директору.</div>'}</div>`;
        return;
    }

    await loadFinanceModuleData();
    populateFinanceSelects();
    await applyFinanceFieldPermissions();
    bindFinanceDraftAutosave();
    bindFinanceSmartHints();

    const metricsGrid = document.getElementById('financeMetricsGrid');
    const tbody = document.getElementById('financePaymentsTable');
    if (!metricsGrid || !tbody) return;
    const canCreateFinance = (currentPermissions.finance || []).includes('create');
    view.querySelectorAll('.finance-create-trigger').forEach(button => {
        button.hidden = !canCreateFinance;
    });
    registerFinanceSavedFilters();
    setFinanceFilterButtonState();

    const metrics = financeSummaryDB?.metrics || {};
    renderFinanceRoleWorkbench(metrics);
    metricsGrid.innerHTML = `
        <div class="metric-card"><div class="metric-title">Ожидаем от клиентов</div><div class="metric-value">${formatMoney(metrics.incoming_open || 0)}</div></div>
        <div class="metric-card"><div class="metric-title">Нужно оплатить</div><div class="metric-value">${formatMoney(metrics.outgoing_open || 0)}</div></div>
        <div class="metric-card warning"><div class="metric-title">Просрочено</div><div class="metric-value">${formatMoney(metrics.overdue_receivables || 0)}</div></div>
    `;
    renderFinanceErpMetrics();
    renderFinanceAnalytics();
    renderFinanceMasterData();
    renderFinanceJournal();
    renderFinancePeriodsAndControls();
    renderFinanceSyncAndEdo();

    const visiblePayments = getVisibleFinancePayments();
    renderFinanceCockpit(visiblePayments);
    updateFinanceBulkBar(visiblePayments);
    setFinanceFilterButtonState();

    if (!visiblePayments.length) {
        tbody.innerHTML = typeof renderTableEmptyRow === 'function'
            ? renderTableEmptyRow(
                6,
                'Финансовых операций пока нет.',
        'Создай первую операцию, чтобы увидеть платёжный календарь в работе.',
                `<button class="btn-primary" onclick="presetFinanceFlow('incoming')">Поступление</button><button class="btn-secondary" onclick="presetFinanceFlow('outgoing')">Оплата</button>`
            )
            : '<tr><td colspan="6" class="nsi-empty-row">Финансовых операций пока нет.</td></tr>';
        return;
    }
    const renderRows = () => visiblePayments.map(payment => {
        const actionButtons = [];
        const extraActionButtons = [];
        if (typeof renderEntityFavoriteButton === 'function') {
            extraActionButtons.push(renderEntityFavoriteButton(
                'finance_payment',
                payment.id,
                payment.title || `Платёж #${payment.id}`,
                `${payment.kind === 'incoming' ? 'Входящий' : 'Исходящий'} · ${formatMoney(payment.amount, payment.currency)} · ${financeStatusLabel(payment.status)}`,
                'finance',
                'renderFinance'
            ));
        }
        if (typeof renderEntityWatchButton === 'function') {
            extraActionButtons.push(renderEntityWatchButton(
                'finance_payment',
                payment.id,
                payment.title || `Платёж #${payment.id}`,
                `${formatMoney(payment.amount, payment.currency)} · ${financeStatusLabel(payment.status)}`,
                'finance',
                'renderFinance',
                'paid'
            ));
        }
        actionButtons.push(`<button class="btn-secondary" onclick="openFinancePaymentCard(${payment.id})">Открыть</button>`);
        if (payment.contract_id) {
            extraActionButtons.push(`<button class="btn-secondary" onclick="openContractCard(${Number(payment.contract_id)})">Открыть договор</button>`);
        }
        if (payment.project_id) {
            extraActionButtons.push(`<button class="btn-secondary" onclick="openFinanceProject(${payment.project_id})">Открыть проект</button>`);
        }
        if (currentPermissions.finance && currentPermissions.finance.includes('create')) {
            extraActionButtons.push(`<button class="btn-secondary" onclick="duplicateFinancePayment(${payment.id})">Создать копию</button>`);
        }
        if (currentPermissions.finance && currentPermissions.finance.includes('post')) {
            extraActionButtons.push(`<button class="btn-secondary" onclick="postFinancePayment(${payment.id})">Провести</button>`);
        }
        if (currentPermissions.finance && currentPermissions.finance.includes('update') && payment.status !== 'paid') {
            actionButtons.push(`<button class="btn-success" onclick="markFinancePaymentPaid(${payment.id})">Оплачено</button>`);
        }
        if (currentPermissions.finance && currentPermissions.finance.includes('update') && payment.status !== 'overdue' && payment.status !== 'paid') {
            extraActionButtons.push(`<button class="btn-secondary" onclick="markFinancePaymentOverdue(${payment.id})">Отметить просрочку</button>`);
        }
        if (currentPermissions.finance && currentPermissions.finance.includes('sign_edo')) {
            extraActionButtons.push(`<button class="btn-secondary" onclick="signFinancePaymentEdo(${payment.id})">Подписать в ЭДО</button>`);
        }
        if (currentPermissions.finance && currentPermissions.finance.includes('delete')) {
            extraActionButtons.push(`<button class="btn-danger" onclick="deleteFinancePayment(${payment.id})">Удалить</button>`);
        }
        const extraActions = '';
        return `
        <tr data-finance-id="${payment.id}" class="${typeof isWorkflowFocused === 'function' && isWorkflowFocused('finance', payment.id) ? 'workflow-row-highlight' : ''}">
            <td>
                <div class="finance-row-title">${payment.title || 'Операция'}</div>
                <div class="finance-row-meta">${financeTranslateLabel(payment.category || 'payment', 'Платёж')} · ${payment.kind === 'incoming' ? 'Поступление' : 'Выплата'}</div>
            </td>
            <td>
                <div class="finance-row-title">${payment.client_name || 'Контрагент не указан'}</div>
                <div class="finance-row-meta">${financeDisplayName(payment.project_contract || payment.project_name, 'Без проекта')}</div>
            </td>
            <td class="finance-row-amount">${formatMoney(payment.amount, payment.currency)}</td>
            <td>${payment.due_date || 'Без даты'}<div class="finance-row-meta">${payment.paid_date ? `Оплачено ${payment.paid_date}` : 'Ожидаем оплату'}</div></td>
            <td><span class="status-badge ${financeStatusClass(payment.status)}">${financeStatusLabel(payment.status)}</span></td>
            <td><div class="finance-row-actions">${actionButtons.join('')}${extraActions}</div></td>
        </tr>
    `;
    }).join('');
    if (typeof renderDeferredHtml === 'function') {
        renderDeferredHtml(tbody, renderRows, { size: visiblePayments.length, threshold: 90, colspan: 6, loadingMessage: 'Загружаю операции...' });
    } else {
        tbody.innerHTML = renderRows();
    }
}

function setFinanceFilterButtonState() {
    const map = {
        all: 'financeFilterAllBtn',
        planned: 'financeFilterPlannedBtn',
        overdue: 'financeFilterOverdueBtn',
        paid: 'financeFilterPaidBtn',
    };
    Object.values(map).forEach(id => document.getElementById(id)?.classList.remove('is-filter-active'));
    document.getElementById(map[financeFilter] || map.all)?.classList.add('is-filter-active');
}

async function loadClient360(clientId) {
    currentClient360Id = Number(clientId || 0);
    if (!currentClient360Id) {
        client360DB = null;
        return null;
    }
    const data = await apiCall(`/clients/${currentClient360Id}/dossier`);
    client360DB = data && !data.error ? data : null;
    return client360DB;
}

function renderClient360List(items, renderer, emptyText) {
    if (!Array.isArray(items) || !items.length) {
        return `<div class="empty-state">${emptyText}</div>`;
    }
    return items.map(renderer).join('');
}

function client360Money(value, currency = 'RUB') {
    return formatMoney(value || 0, currency || 'RUB');
}

function renderEntitySummaryCard(definition = {}) {
    const tone = definition.tone ? ` entity-summary-line--${financeEscapeHtml(definition.tone)}` : '';
    const noteHtml = definition.note
        ? `<div class="entity-summary-line__note">${financeEscapeHtml(definition.note)}</div>`
        : '';
    return `
        <div class="entity-summary-line entity-summary-line--focus${tone}">
            <span class="entity-summary-line__label">${financeEscapeHtml(definition.label || '')}</span>
            <span class="entity-summary-line__value">${financeEscapeHtml(definition.value ?? '0')}</span>
            ${noteHtml}
        </div>
    `;
}

function renderEntitySummaryFact(definition = {}) {
    const tone = definition.tone ? ` entity-summary-line--${financeEscapeHtml(definition.tone)}` : '';
    return `
        <div class="entity-summary-line${tone}">
            <span class="entity-summary-line__label">${financeEscapeHtml(definition.label || '')}</span>
            <span class="entity-summary-line__value">${financeEscapeHtml(definition.value ?? '0')}</span>
        </div>
    `;
}

window.renderEntitySummary = function renderEntitySummary(target, options = {}) {
    const mount = typeof target === 'string' ? document.getElementById(target) : target;
    if (!mount) return;

    const primary = Array.isArray(options.primary) ? options.primary : [];
    const secondary = Array.isArray(options.secondary) ? options.secondary : [];
    const variant = options.variant ? ` entity-summary--${financeEscapeHtml(options.variant)}` : '';
    const primaryHtml = primary.length
        ? `<div class="entity-summary__rail">${primary.map(renderEntitySummaryCard).join('')}</div>`
        : '';
    const secondaryHtml = secondary.length
        ? `<div class="entity-summary__matrix">${secondary.map(renderEntitySummaryFact).join('')}</div>`
        : `<div class="entity-summary__empty">${financeEscapeHtml(options.emptyHint || 'Дополнительных сигналов пока нет.')}</div>`;

    mount.classList.add('entity-summary-mount');
    if (options.kind) mount.dataset.entitySummary = String(options.kind);
    mount.innerHTML = `
        <section class="entity-summary${variant}">
            <div class="entity-summary__header">
                <div class="entity-summary__intro">
                    <div class="entity-summary__eyebrow">${financeEscapeHtml(options.eyebrow || 'Сводка')}</div>
                    <h3 class="entity-summary__headline">${financeEscapeHtml(options.headline || '')}</h3>
                    <p class="entity-summary__description">${financeEscapeHtml(options.description || '')}</p>
                </div>
                ${primaryHtml}
            </div>
            ${secondaryHtml}
        </section>
    `;
};
async function renderClient360() {
    const emptyState = document.getElementById('client360EmptyState');
    const content = document.getElementById('client360Content');
    if (!emptyState || !content) return;

    if (!clientsDB.length) {
        emptyState.style.display = 'block';
        content.style.display = 'none';
        return;
    }

    if (!currentClient360Id) {
        currentClient360Id = clientsDB[0].id;
    }

    await loadClient360(currentClient360Id);
    if (!client360DB) {
        emptyState.style.display = 'block';
        content.style.display = 'none';
        return;
    }

    emptyState.style.display = 'none';
    content.style.display = 'block';

    const {
        client,
        metrics,
        contacts,
        projects,
        finance,
        sales_quotes,
        client_terms,
        supplier_registry,
        bank_lines,
        telephony_calls,
        purchases,
        sales,
        production,
        epl_waybills,
        service_cases,
        documents,
        claims,
        court_cases,
        timeline,
    } = client360DB;
    document.getElementById('client360Name').innerText = financeDisplayName(client.name, 'Контрагент');
    document.getElementById('client360Inn').innerText = client.inn ? `ИНН ${client.inn}` : 'ИНН не указан';
    const clientMetaParts = [];
    if (client.kpp) clientMetaParts.push(`КПП ${client.kpp}`);
    if (client.ogrn) clientMetaParts.push(`ОГРН ${client.ogrn}`);
    if (client.contact) clientMetaParts.push(client.contact);
    if (client.legal_address) clientMetaParts.push(`Адрес: ${client.legal_address}`);
    document.getElementById('client360Contact').innerText = clientMetaParts.join(' · ') || 'Реквизиты и контакт пока не заполнены';

    const clientMetricsEl = document.getElementById('client360Metrics');
    if (clientMetricsEl && typeof window.renderEntitySummary === 'function') {
        const hasClientActivity = [
            Number(metrics.projects_total || 0),
            Number(metrics.active_projects || 0),
            Number(metrics.receivable_open || 0),
            Number(metrics.revenue_total || 0),
            Number(metrics.quotes_total || 0),
            Number(metrics.calls_total || 0),
            Number(metrics.purchases_total || 0),
            Number(metrics.epl_active || 0),
        ].some(value => value > 0);
        const receivableOpen = Number(metrics.receivable_open || 0);
        const revenueTotal = Number(metrics.revenue_total || 0);
        const clientHeadline = hasClientActivity
            ? `${Number(metrics.active_projects || 0)} активных проектов · ${Number(metrics.projects_total || 0)} сделок в системе`
            : 'Досье клиента готово, активный портфель пока не сформирован';
        const clientDescription = hasClientActivity
            ? `Денежный контур: дебиторка ${formatMoney(receivableOpen)}, выручка ${formatMoney(revenueTotal)} и закупки ${formatMoney(metrics.purchases_total || 0)}.`
            : 'Как только появятся сделки, оплаты или коммуникации, здесь будет короткий срез по клиенту без длинной стены карточек.';

        window.renderEntitySummary(clientMetricsEl, {
            kind: 'client',
            variant: 'client',
            eyebrow: 'Короткий срез',
            headline: clientHeadline,
            description: clientDescription,
            primary: [
                {
                    label: 'Активный портфель',
                    value: Number(metrics.active_projects || 0),
                    note: `из ${Number(metrics.projects_total || 0)} сделок`,
                    tone: Number(metrics.active_projects || 0) > 0 ? 'accent' : '',
                    hidden: Number(metrics.active_projects || 0) <= 0 && Number(metrics.projects_total || 0) <= 0,
                },
                {
                    label: 'Открытая дебиторка',
                    value: formatMoney(receivableOpen),
                    note: receivableOpen > 0 ? 'нужен контроль оплаты' : 'платёжный риск не открыт',
                    tone: receivableOpen > 0 ? 'warning' : 'positive',
                    hidden: receivableOpen <= 0,
                },
                {
                    label: 'Выручка по портфелю',
                    value: formatMoney(revenueTotal),
                    note: 'накоплено по клиенту',
                    tone: revenueTotal > 0 ? 'accent' : '',
                    hidden: revenueTotal <= 0,
                },
            ],
            secondary: [
                { label: 'КП в работе', value: client360Money(metrics.quotes_total || 0), hidden: Number(metrics.quotes_total || 0) <= 0 },
                { label: 'Макс. скидка', value: `${Number(metrics.discount_max || 0).toLocaleString('ru-RU')}%`, hidden: Number(metrics.discount_max || 0) <= 0 },
                { label: 'Банк. оборот', value: client360Money(metrics.bank_turnover || 0), hidden: Number(metrics.bank_turnover || 0) <= 0 },
                { label: 'Звонков', value: Number(metrics.calls_total || 0), hidden: Number(metrics.calls_total || 0) <= 0 },
                { label: 'Закупки', value: formatMoney(metrics.purchases_total || 0), hidden: Number(metrics.purchases_total || 0) <= 0 },
                { label: 'ЭПЛ в работе', value: Number(metrics.epl_active || 0), hidden: Number(metrics.epl_active || 0) <= 0 },
            ],
        });
    }

    document.getElementById('client360Projects').innerHTML = renderClient360List(
        projects,
        project => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${financeDisplayName(project.name, 'Проект')}</div>
                    <div class="client360-item-meta">${project.contract || 'Без договора'} · ${project.manager || 'Менеджер не назначен'}</div>
                </div>
                <div class="view-actions">
                    <button class="btn-secondary" onclick="openProject(${project.id})">Открыть</button>
                    <button class="btn-secondary" onclick="openContractCardForProject(${project.id})">Контракт 360</button>
                </div>
            </div>
        `,
        'У этого контрагента пока нет сделок в системе.'
    );

    document.getElementById('client360Contacts').innerHTML = renderClient360List(
        contacts,
        contact => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${contact.name}</div>
                <div class="client360-item-meta">${contact.position || 'Без должности'}</div>
                <div class="client360-item-meta">${contact.phone || 'Телефон не указан'} · ${contact.email || 'Эл. почта не указана'}</div>
            </div>
        `,
        'Контакты по этому контрагенту пока не заведены.'
    );

    document.getElementById('client360Finance').innerHTML = renderClient360List(
        finance,
        payment => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${payment.title || 'Финансовая операция'}</div>
                    <div class="client360-item-meta">${payment.kind === 'incoming' ? 'Входящий поток' : 'Исходящий поток'} · ${financeStatusLabel(payment.status)}</div>
                </div>
                <div class="client360-item-side">${formatMoney(payment.amount, payment.currency)}</div>
            </div>
        `,
        'Финансовые операции для этого контрагента пока не заведены.'
    );

    const commercialTarget = document.getElementById('client360Commercial');
    if (commercialTarget) {
        commercialTarget.innerHTML = renderClient360List(
            [
                ...(sales_quotes || []).map(item => ({ ...item, _group: 'quote' })),
                ...(client_terms || []).map(item => ({ ...item, _group: 'terms' })),
                ...(supplier_registry || []).map(item => ({ ...item, _group: 'supplier' })),
            ],
            item => {
                if (item._group === 'quote') {
                    return `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${financeDisplayName(item.title || item.quote_number, 'Коммерческое предложение')}</div>
                                <div class="client360-item-meta">${item.quote_number || 'без номера'} · ${financeTranslateLabel(item.stage || 'draft', 'Черновик')} · до ${item.valid_until || 'без срока'}</div>
                            </div>
                            <div class="client360-item-side">${client360Money(item.amount, item.currency)}</div>
                        </div>
                    `;
                }
                if (item._group === 'terms') {
                    return `
                        <div class="client360-item client360-item--stack">
                            <div class="client360-item-title">Условия клиента</div>
                            <div class="client360-item-meta">${item.price_list_name || 'Без прайса'} · приоритет ${financeTranslateLabel(item.shipment_priority || 'normal', 'Обычный')}</div>
                            <div class="client360-item-meta">Скидка ${Number(item.discount_percent || 0).toLocaleString('ru-RU')}% · отсрочка ${item.payment_delay_days || 0} дн. · лимит ${client360Money(item.credit_limit || 0)}</div>
                        </div>
                    `;
                }
                return `
                    <div class="client360-item client360-item--stack">
                        <div class="client360-item-title">${financeDisplayName(item.supplier_name, 'Поставщик')}</div>
                        <div class="client360-item-meta">${item.category || 'категория не указана'} · срок поставки ${item.lead_time_days || 0} дн.</div>
                        <div class="client360-item-meta">Рейтинг ${Number(item.rating || 0).toLocaleString('ru-RU')} · надежность ${Number(item.reliability_percent || 0).toLocaleString('ru-RU')}%</div>
                    </div>
                `;
            },
            'Коммерческие условия и котировки по этому контрагенту пока не заведены.'
        );
    }

    document.getElementById('client360Ops').innerHTML = renderClient360List(
        [
            ...(purchases || []).map(item => ({ ...item, _group: 'purchase' })),
            ...(sales || []).map(item => ({ ...item, _group: 'sales' })),
            ...(production || []).map(item => ({ ...item, _group: 'production' })),
        ],
        item => `
            <div class="client360-item">
                <div>
                    <div class="client360-item-title">${item._group === 'purchase' ? financeDisplayName(item.item_name, 'Закупка') : item._group === 'sales' ? `${financeTranslateLabel(item.doc_type || 'doc', 'Документ')} ${item.doc_number || ''}` : financeDisplayName(item.order_name, 'Заказ')}</div>
                    <div class="client360-item-meta">
                        ${item._group === 'purchase' ? `Закупка · ${item.status || '—'} · ${item.expected_date || 'без срока'}` : ''}
                        ${item._group === 'sales' ? `Реализация · ${item.status || '—'} · ${item.payment_status || 'оплата не указана'}` : ''}
                        ${item._group === 'production' ? `Производство · ${item.stage || '—'} · ${item.responsible || 'без ответственного'}` : ''}
                    </div>
                </div>
                <div class="client360-item-side">
                    ${item._group === 'purchase' ? formatMoney(item.total_amount || 0) : ''}
                    ${item._group === 'sales' ? formatMoney(item.amount || 0, item.currency) : ''}
                    ${item._group === 'production' ? `${item.progress || 0}%` : ''}
                </div>
            </div>
        `,
        'Закупки, реализация и производство по этому контрагенту пока не заведены.'
    );

    const eplTarget = document.getElementById('client360Epl');
    if (eplTarget) {
        eplTarget.innerHTML = renderClient360List(
            epl_waybills || [],
            item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${item.number || '\u042d\u041f\u041b'}</div>
                        <div class="client360-item-meta">${item.route_text || '\u041c\u0430\u0440\u0448\u0440\u0443\u0442 \u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d'} \u00b7 ${financeTranslateLabel(item.status || 'draft', 'Черновик')} \u00b7 1\u0421 ${financeTranslateLabel(item.integration_status || 'draft', 'Черновик')}</div>
                        <div class="client360-item-meta">${item.driver_name || '\u0412\u043e\u0434\u0438\u0442\u0435\u043b\u044c \u043d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d'} \u00b7 ${item.vehicle_label || '\u0422\u0421 \u043d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d\u043e'}</div>
                    </div>
                    <div class="view-actions">
                        <button class="btn-secondary" onclick="openEplModuleForWaybill(${item.id})">\u041e\u0442\u043a\u0440\u044b\u0442\u044c</button>
                    </div>
                </div>
            `,
            '\u041f\u043e \u044d\u0442\u043e\u043c\u0443 \u043a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u0443 \u042d\u041f\u041b \u043f\u043e\u043a\u0430 \u043d\u0435 \u0437\u0430\u0432\u0435\u0434\u0435\u043d\u044b.'
        );
    }

    const integrationsTarget = document.getElementById('client360Integrations');
    if (integrationsTarget) {
        integrationsTarget.innerHTML = renderClient360List(
            [
                ...(bank_lines || []).map(item => ({ ...item, _group: 'bank' })),
                ...(telephony_calls || []).map(item => ({ ...item, _group: 'call' })),
            ],
            item => {
                if (item._group === 'bank') {
                    return `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${financeDisplayName(item.counterparty, 'Банковская строка')}</div>
                                <div class="client360-item-meta">${item.bank_account_name || 'Счет не указан'} · ${financeTranslateLabel(item.status || 'imported', 'Загружено')} · ${item.line_date || ''}</div>
                                <div class="client360-item-meta">${item.payment_title || 'Без связанной оплаты'} · ${item.purpose || 'Назначение не указано'}</div>
                            </div>
                            <div class="client360-item-side">${client360Money(item.amount)}</div>
                        </div>
                    `;
                }
                return `
                    <div class="client360-item">
                        <div>
                            <div class="client360-item-title">${financeDisplayName(item.contact_name || item.phone_number, 'Звонок')}</div>
                            <div class="client360-item-meta">${financeTranslateLabel(item.direction || 'call', 'Звонок')} · ${financeTranslateLabel(item.status || 'answered', 'Отвечен')} · ${item.line_name || 'Линия не указана'}</div>
                            <div class="client360-item-meta">${item.summary || 'Без комментария'}</div>
                        </div>
                        <div class="client360-item-side">${item.call_at || ''}</div>
                    </div>
                `;
            },
            'Банковские строки и звонки по этому контрагенту пока не найдены.'
        );
    }

    document.getElementById('client360Documents').innerHTML = renderClient360List(
        documents,
        document => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${document.subject || 'Документ'}</div>
                <div class="client360-item-meta">${document.type || 'Документ'} · ${document.number || '—'} · ${document.d_date || ''}</div>
            </div>
        `,
        'Связанных документов пока нет.'
    );

    document.getElementById('client360Legal').innerHTML = renderClient360List(
        [...claims.map(item => ({ ...item, _type: 'claim' })), ...court_cases.map(item => ({ ...item, _type: 'court' }))],
        legal => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${legal._type === 'claim' ? 'Претензия' : 'Судебное дело'} ${legal.number || ''}</div>
                <div class="client360-item-meta">${legal.status || legal.stage || 'Без статуса'} · ${formatMoney(legal.amount || 0)}</div>
            </div>
        `,
        'Претензий и судов по этому контрагенту пока нет.'
    );

    const serviceTarget = document.getElementById('client360Service');
    if (serviceTarget) {
        serviceTarget.innerHTML = renderClient360List(
            service_cases,
            item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${financeDisplayName(item.title, 'Сервисный кейс')}</div>
                        <div class="client360-item-meta">${financeTranslateLabel(item.case_type || 'service', 'Сервис')} · ${item.responsible || 'без ответственного'}</div>
                    </div>
                    <span class="status-badge ${typeof enterpriseStatusClass === 'function' ? enterpriseStatusClass(item.status) : 'status-active'}">${financeTranslateLabel(item.status || 'open', 'Открыт')}</span>
                </div>
            `,
            'Сервисных кейсов по этому контрагенту пока нет.'
        );
    }

    document.getElementById('client360Timeline').innerHTML = renderClient360List(
        timeline,
        item => `
            <div class="client360-item client360-item--stack">
                <div class="client360-item-title">${item.title}</div>
                <div class="client360-item-meta">${item.meta || ''}</div>
                <div class="client360-item-meta">${item.time || ''}</div>
            </div>
        `,
        'Лента событий пока пуста.'
    );
}

window.openClientCard = async function openClientCard(id) {
    await loadClient360(id);
    navigateTo('client360');
};
