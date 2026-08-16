let currentLeadViewMode = 'registry';
let currentLeadSearch = '';
let currentLeadStage = '';
let currentLeadResponsible = '';
let currentLeadSort = 'due_asc';
let currentLeadId = 0;
let editingLeadId = 0;

const CRM_LEAD_ROUTING_SETTINGS_KEY = 'korda_crm_lead_routing_settings_v1';
const CRM_LEAD_ROUTING_DEFAULTS = {
    budgetThreshold: 3000000,
    seniorManager: 'Старший менеджер',
    tenderManager: 'Тендерный менеджер',
    industryManager: 'Отраслевой менеджер',
    regionManager: 'Региональный менеджер',
    equipmentManager: 'Продуктовый менеджер',
    defaultManager: 'Менеджер входящего потока',
    minConfidence: 45,
};

const CRM_LEAD_INDUSTRIES = [
    { key: 'construction', label: 'Строительство', managerKey: 'industryManager', words: ['строитель', 'строй', 'генподряд', 'монтаж', 'объект', 'площадк'] },
    { key: 'oilgas', label: 'Нефтегаз', managerKey: 'industryManager', words: ['нефт', 'газ', 'скваж', 'газпром', 'лукойл', 'трубопровод'] },
    { key: 'energy', label: 'Энергетика', managerKey: 'industryManager', words: ['энерг', 'тэс', 'гэс', 'подстанц', 'генерац', 'котельн'] },
    { key: 'manufacturing', label: 'Производство', managerKey: 'industryManager', words: ['производ', 'завод', 'цех', 'станок', 'линия', 'комбинат'] },
    { key: 'tender', label: 'Тендеры', managerKey: 'tenderManager', words: ['тендер', 'закуп', 'площадк', 'конкурс', '44-фз', '223-фз'] },
];

const CRM_LEAD_EQUIPMENT = [
    { key: 'kshz', label: 'КШЗ', words: ['кшз', 'кожух шумозащит', 'шумозащитн'] },
    { key: 'silencers', label: 'Шумоглушители', words: ['шумоглуш', 'глушител', 'silencer'] },
    { key: 'covers', label: 'Кожухи', words: ['кожух', 'окожуш', 'изоляц'] },
    { key: 'compressors', label: 'Компрессоры', words: ['компрессор', 'газодув', 'нагнетател'] },
    { key: 'cabins', label: 'Кабины', words: ['кабин', 'оператор', 'звукоизоляц'] },
];

const CRM_LEAD_REGIONS = [
    { key: 'moscow', label: 'Москва / ЦФО', district: 'ЦФО', timezone: 'МСК', words: ['москва', 'московск', 'цфо', 'центр'] },
    { key: 'volga', label: 'Поволжье', district: 'ПФО', timezone: 'МСК+1', words: ['казань', 'самара', 'уфа', 'перм', 'татарстан', 'башкир', 'поволжь'] },
    { key: 'ural', label: 'Урал', district: 'УФО', timezone: 'МСК+2', words: ['екатеринбург', 'челябинск', 'тюмень', 'урал', 'пермь'] },
    { key: 'siberia', label: 'Сибирь', district: 'СФО', timezone: 'МСК+4', words: ['новосибирск', 'красноярск', 'омск', 'сибир'] },
    { key: 'far_east', label: 'Дальний Восток', district: 'ДФО', timezone: 'МСК+7', words: ['владивосток', 'хабаровск', 'дальний восток', 'сахалин', 'якут'] },
    { key: 'northwest', label: 'Северо-Запад', district: 'СЗФО', timezone: 'МСК', words: ['санкт-петербург', 'спб', 'ленинград', 'северо-запад', 'мурманск'] },
];

let currentDealViewMode = 'registry';
let currentDealSearch = '';
let currentDealStage = '';
let currentDealResponsible = '';
let currentDealSort = 'due_asc';
let currentDealId = 0;
let editingDealId = 0;
let editingDealStep = 1;
let skipDealEditorAutoOpenOnce = false;
let currentDealArchiveView = false;
let dealSharedSyncInFlight = false;
let dealSharedSyncTimer = 0;

function crmEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function crmFormatMoney(value, currency = 'RUB') {
    if (typeof formatMoney === 'function') return formatMoney(value || 0, currency || 'RUB');
    return `${Number(value || 0).toLocaleString('ru-RU')} ${currency || 'RUB'}`;
}

function crmParseRuDate(value) {
    const raw = String(value || '').trim();
    const match = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    if (!match) return null;
    const date = new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]));
    return Number.isNaN(date.getTime()) ? null : date;
}

function crmDaysUntil(value) {
    const date = crmParseRuDate(value);
    if (!date) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((date - today) / 86400000);
}

function crmToneByDueDate(value) {
    const days = crmDaysUntil(value);
    if (days === null) return 'neutral';
    if (days < 0) return 'critical';
    if (days <= 1) return 'attention';
    return 'positive';
}

function crmStageLabel(stage) {
    const map = {
        new: 'Новый',
        qualified: 'Потребность подтверждена',
        proposal: 'Готовится предложение',
        won: 'Передан в сделку',
        lost: 'Закрыт без сделки',
        qualification: 'Квалификация',
        negotiation: 'Переговоры',
    };
    return map[String(stage || '')] || (stage || 'Без стадии');
}

function crmDealStageInfo(stage) {
    return {
        qualification: { label: 'Уточняем заказ', help: 'Подтвердите состав, количество, цену и сроки.' },
        proposal: { label: 'Готовим документы и счёт', help: 'Прикрепите КП, договор или счёт и отправьте клиенту.' },
        negotiation: { label: 'Согласовываем условия', help: 'Зафиксируйте изменения, решение клиента и следующую дату.' },
        won: { label: 'Успешно завершено', help: 'Продажа подтверждена. Проверьте оплату и передачу в исполнение.' },
        lost: { label: 'Закрыто без продажи', help: 'Укажите причину, чтобы она попала в аналитику.' },
    }[String(stage || '')] || { label: 'Уточняем заказ', help: 'Укажите следующий конкретный шаг.' };
}

function crmDealProducts(row = {}) {
    return Array.isArray(row.products) ? row.products.filter(item => item && String(item.name || '').trim()) : [];
}

function crmDealPayloadFromRow(row = {}, overrides = {}) {
    return {
        lead_id: Number(row.lead_id || 0),
        title: row.title || '', client_id: Number(row.client_id || 0), client_name: row.client_name || '',
        contact_name: row.contact_name || '', contact_position: row.contact_position || '', contact_phone: row.contact_phone || '', contact_email: row.contact_email || '', source: row.source || '',
        contract_number: row.contract_number || '', stage: row.stage || 'qualification', amount: Number(row.amount || 0), currency: row.currency || 'RUB',
        margin_percent: Number(row.margin_percent || 0), probability: Number(row.probability || 0), responsible: row.responsible || '', co_executors: row.co_executors || '',
        next_action: row.next_action || '', next_action_date: row.next_action_date || '', expected_close_date: row.expected_close_date || '', actual_close_date: row.actual_close_date || '',
        priority: row.priority || 'normal', status_color: row.status_color || '', tags: Array.isArray(row.tags) ? row.tags : [], comment: row.comment || '',
        loss_reason: row.loss_reason || '', project_id: Number(row.project_id || 0), products: crmDealProducts(row),
        ...overrides,
    };
}

function crmCanManageDeal(row = {}) {
    if (currentUser?.role === 'Директор') return true;
    if (typeof row.can_manage === 'boolean') return row.can_manage;
    if (row.can_manage === 1 || row.can_manage === '1') return true;
    return Boolean(
        String(row.responsible || '').trim()
        && String(row.responsible || '').trim().toLocaleLowerCase('ru-RU') === String(currentUser?.name || '').trim().toLocaleLowerCase('ru-RU')
    );
}

function crmDealAvailableDocuments(dealId) {
    return (Array.isArray(documentsDB) ? documentsDB : [])
        .filter(item => Number(item.deal_id || 0) === 0 || Number(item.deal_id || 0) === Number(dealId || 0))
        .sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
}

function crmDocumentKindLabel(code = '', doc = {}) {
    let resolvedCode = String(code || '').trim();
    if (!resolvedCode) {
        const text = `${doc.subject || ''} ${doc.number || ''}`.toLocaleLowerCase('ru-RU');
        if (/реквизит|карточк[аи] предприятия/.test(text)) resolvedCode = 'company_details';
        else if (/коммерческ|(^|\s)кп([\s-]|$)/.test(text)) resolvedCode = 'commercial_proposal';
        else if (/договор/.test(text)) resolvedCode = 'contract';
        else if (/сч[её]т/.test(text)) resolvedCode = 'invoice';
        else if (/акт|упд/.test(text)) resolvedCode = 'act_upd';
        else if (/техническ.*задан|(^|\s)тз([\s-]|$)/.test(text)) resolvedCode = 'technical_task';
        else if (/черт[её]ж/.test(text)) resolvedCode = 'drawing';
        else if (/спецификац/.test(text)) resolvedCode = 'product_specification';
        else resolvedCode = 'other';
    }
    if (typeof documentKindLabel === 'function') return documentKindLabel(resolvedCode);
    return {
        commercial_proposal: 'Коммерческое предложение', company_details: 'Карточка предприятия / реквизиты', technical_proposal: 'Техническое предложение',
        contract: 'Договор', contract_specification: 'Спецификация к договору', invoice: 'Счёт', act_upd: 'Акт / УПД',
        technical_task: 'Техническое задание', drawing: 'Чертёж', product_specification: 'Спецификация изделия',
        technology_card: 'Технологическая карта', production_order: 'Производственное задание', purchase_request: 'Заявка на закупку',
        supplier_order: 'Заказ поставщику', waybill: 'Накладная', quality_act: 'Акт ОТК', service_act: 'Сервисный / гарантийный акт',
        internal_memo: 'Служебная записка', other: 'Другой документ',
    }[resolvedCode] || 'Документ';
}

function openDealDocumentModal(dealId) {
    const row = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!row || typeof openDocumentModalWithPreset !== 'function') return;
    if (!crmCanManageDeal(row)) return customAlert('Эта сделка доступна только для просмотра. Изменять её может ответственный сотрудник или директор.');
    openDocumentModalWithPreset({
        type: 'outgoing',
        document_kind_code: 'commercial_proposal',
        client_id: Number(row.client_id || 0),
        client_name: row.client_name || row.title || '',
        deal_id: Number(row.id || 0),
    });
}

window.openDealDocumentModal = openDealDocumentModal;

function crmPriorityLabel(priority) {
    return {
        low: 'Низкий',
        normal: 'Нормальный',
        high: 'Высокий',
    }[String(priority || '')] || 'Нормальный';
}

function crmCanManageLeadRouting() {
    return String(currentUser?.role || '').trim() === 'Директор' || Number(currentUser?.is_head || 0) === 1;
}

function crmLeadPriorityView(info = {}) {
    if (info.firstTouchSlaViolated) return { label: 'Срочно связаться', tone: 'critical' };
    if (Number(info.score || 0) >= 76) return { label: 'Высокий приоритет', tone: 'positive' };
    if (Number(info.score || 0) >= 52) return { label: 'Средний приоритет', tone: 'attention' };
    return { label: 'Обычный приоритет', tone: 'neutral' };
}

function crmLeadPriorityReason(row = {}, info = {}) {
    if (info.firstTouchSlaViolated) return 'Первого контакта ещё не было, а срок уже прошёл.';
    if (!String(row.contact_phone || row.contact_email || '').trim()) return 'Не хватает телефона или почты — сначала уточните контакт.';
    if (!String(row.next_action || row.next_action_date || '').trim()) return 'Не указан следующий шаг — добавьте действие и дату.';
    if (Number(row.budget || 0) >= 3000000) return 'Крупный потенциальный заказ требует внимания.';
    if (Number(info.score || 0) >= 76) return 'Есть контакты, интерес и понятный следующий шаг.';
    if (Number(info.score || 0) >= 52) return 'Лид перспективный, но часть информации ещё нужно уточнить.';
    return 'Сначала подтвердите потребность, сроки и контактное лицо.';
}

function crmLeadStageGuide(stage) {
    const guides = {
        new: ['Первый контакт', 'Свяжитесь с клиентом, уточните потребность и обязательно поставьте следующий шаг с датой.'],
        qualified: ['Подготовить решение', 'Потребность подтверждена. Уточните бюджет и сроки, затем подготовьте предложение.'],
        proposal: ['Получить решение', 'Предложение отправлено. Узнайте обратную связь и зафиксируйте дату следующего контакта.'],
        won: ['Передан в сделку', 'Продолжайте работу в разделе «Сделки». В лиде дополнительных действий не требуется.'],
        lost: ['Работа завершена', 'Лид закрыт без сделки. Проверьте, что причина отказа записана в комментарии.'],
    };
    return guides[String(stage || '')] || guides.new;
}

function crmLeadTransferManagers(row = {}) {
    const currentResponsible = String(row.responsible || '').trim().toLowerCase();
    return (Array.isArray(allUsersDB) ? allUsersDB : [])
        .filter(user => String(user.status || '') === 'approved' && ['Менеджер', 'Директор'].includes(String(user.role || '')))
        .filter(user => String(user.name || '').trim())
        .filter(user => String(user.name || '').trim().toLowerCase() !== currentResponsible)
        .sort((left, right) => String(left.name || '').localeCompare(String(right.name || ''), 'ru'));
}

function crmActivityLabel(type) {
    return {
        note: 'Заметка',
        call: 'Звонок',
        email: 'Письмо',
        meeting: 'Встреча',
        task: 'Задача',
    }[String(type || '')] || 'Активность';
}

function crmCollectResponsibles(rows = []) {
    return Array.from(new Set((rows || []).map(row => String(row.responsible || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ru'));
}

function crmLeadRoutingSettings() {
    try {
        const parsed = JSON.parse(localStorage.getItem(CRM_LEAD_ROUTING_SETTINGS_KEY) || '{}');
        const settings = { ...CRM_LEAD_ROUTING_DEFAULTS, ...(parsed && typeof parsed === 'object' ? parsed : {}) };
        if (settings.seniorManager === 'Senior менеджер') settings.seniorManager = 'Старший менеджер';
        return settings;
    } catch {
        return { ...CRM_LEAD_ROUTING_DEFAULTS };
    }
}

function crmLeadRouteText(row) {
    return [
        row?.title,
        row?.client_name,
        row?.contact_name,
        row?.source,
        row?.next_action,
        row?.comment,
        Array.isArray(row?.tags) ? row.tags.join(' ') : '',
    ].join(' ').toLowerCase();
}

function crmMatchCatalog(text, catalog) {
    return catalog.filter(item => item.words.some(word => text.includes(word)));
}

function crmLeadRouteSignals(row) {
    const text = crmLeadRouteText(row);
    const industries = crmMatchCatalog(text, CRM_LEAD_INDUSTRIES);
    const equipment = crmMatchCatalog(text, CRM_LEAD_EQUIPMENT);
    const regions = crmMatchCatalog(text, CRM_LEAD_REGIONS);
    const budget = Number(row?.budget || 0);
    const sourceText = String(row?.source || '').toLowerCase();
    const isTender = industries.some(item => item.key === 'tender') || /тендер|закуп|площадк|конкурс|44-фз|223-фз/.test(text);
    const urgency = crmDaysUntil(row?.next_action_date);
    return {
        text,
        industries,
        equipment,
        regions,
        budget,
        isTender,
        sourceText,
        urgency,
        hasContact: !!String(row?.contact_phone || row?.contact_email || '').trim(),
    };
}

function crmLeadRoutingRules(settings = crmLeadRoutingSettings()) {
    const threshold = Math.max(0, Number(settings.budgetThreshold || CRM_LEAD_ROUTING_DEFAULTS.budgetThreshold));
    return [
        {
            key: 'strategic_budget',
            label: `Бюджет > ${crmFormatMoney(threshold)}`,
            manager: settings.seniorManager || CRM_LEAD_ROUTING_DEFAULTS.seniorManager,
            note: 'Крупные и стратегические сделки требуют опытного менеджера.',
            match: row => Number(row.budget || 0) >= threshold,
            confidence: row => Number(row.budget || 0) >= threshold * 1.5 ? 96 : 86,
        },
        {
            key: 'tender',
            label: 'Тендер / закупка',
            manager: settings.tenderManager || CRM_LEAD_ROUTING_DEFAULTS.tenderManager,
            note: 'Нужна проверка сроков, пакета документов и формальных требований.',
            match: row => /тендер|закуп|площадк|конкурс|44-фз|223-фз/i.test([row.source, row.title, row.comment, row.next_action].join(' ')),
            confidence: () => 90,
        },
        {
            key: 'equipment',
            label: 'Категория оборудования',
            manager: settings.equipmentManager || CRM_LEAD_ROUTING_DEFAULTS.equipmentManager,
            note: 'Заявка содержит конкретную категорию оборудования: КШЗ, шумоглушители, кожухи, компрессоры или кабины.',
            match: row => crmLeadRouteSignals(row).equipment.length > 0,
            confidence: row => Math.min(88, 58 + crmLeadRouteSignals(row).equipment.length * 12),
        },
        {
            key: 'industry',
            label: 'Отраслевое направление',
            manager: settings.industryManager || CRM_LEAD_ROUTING_DEFAULTS.industryManager,
            note: 'Есть признаки промышленного строительства, нефтегаза, энергетики или производства.',
            match: row => crmLeadRouteSignals(row).industries.filter(item => item.key !== 'tender').length > 0,
            confidence: row => Math.min(82, 50 + crmLeadRouteSignals(row).industries.length * 12),
        },
        {
            key: 'region',
            label: 'Региональная заявка',
            manager: settings.regionManager || CRM_LEAD_ROUTING_DEFAULTS.regionManager,
            note: 'Нужно учитывать логистику, часовой пояс и региональную ответственность.',
            match: row => crmLeadRouteSignals(row).regions.length > 0,
            confidence: row => Math.min(78, 48 + crmLeadRouteSignals(row).regions.length * 12),
        },
        {
            key: 'standard',
            label: 'Типовая заявка',
            manager: settings.defaultManager || CRM_LEAD_ROUTING_DEFAULTS.defaultManager,
            note: 'Типовую заявку можно распределять в общую очередь менеджеров.',
            match: () => true,
            confidence: row => crmLeadRouteSignals(row).hasContact ? 44 : 25,
        },
    ];
}

function crmLeadRoutingRule(row) {
    const settings = crmLeadRoutingSettings();
    const rules = crmLeadRoutingRules(settings);
    const matched = rules.find(rule => rule.match(row || {})) || rules[rules.length - 1];
    const signals = crmLeadRouteSignals(row || {});
    const confidence = Math.max(0, Math.min(100, Number(matched.confidence ? matched.confidence(row || {}) : 50)));
    const signalLabels = [
        ...signals.industries.map(item => item.label),
        ...signals.equipment.map(item => item.label),
        ...signals.regions.map(item => `${item.label} / ${item.timezone}`),
    ];
    if (confidence < Number(settings.minConfidence || CRM_LEAD_ROUTING_DEFAULTS.minConfidence)) {
        return {
            key: 'unassigned',
            label: 'Не распределено',
            manager: '',
            note: `Недостаточно уверенности (${confidence}%). Нужна ручная квалификация директором или РОПом.`,
            confidence,
            signals,
            signalLabels,
        };
    }
    return { ...matched, confidence, signals, signalLabels };
}

function crmLeadHasFirstTouch(row) {
    return (Array.isArray(row?.activities) ? row.activities : []).some(item => ['call', 'email', 'meeting'].includes(String(item.activity_type || '')));
}

function crmLeadCreatedAgeHours(row) {
    const created = Number(row?.created_at || 0);
    if (!created) return 0;
    return Math.max(0, Math.floor((Date.now() / 1000 - created) / 3600));
}

function crmLeadScore(row) {
    const budget = Number(row?.budget || 0);
    const probability = Number(row?.probability || 0);
    const route = crmLeadRoutingRule(row);
    const signals = route.signals || crmLeadRouteSignals(row);
    const hasPhone = !!String(row?.contact_phone || '').trim();
    const hasEmail = !!String(row?.contact_email || '').trim();
    const hasResponsible = !!String(row?.responsible || '').trim();
    const hasNextAction = !!String(row?.next_action || row?.next_action_date || '').trim();
    const sourceText = String(row?.source || '').toLowerCase();
    const days = crmDaysUntil(row?.next_action_date);
    const ageHours = crmLeadCreatedAgeHours(row);
    const firstTouchSlaViolated = !crmLeadHasFirstTouch(row) && (ageHours >= 24 || (days !== null && days < 0)) && !['won', 'lost'].includes(String(row?.stage || ''));
    let score = 20;
    if (budget >= 5000000) score += 30;
    else if (budget >= 1000000) score += 22;
    else if (budget >= 300000) score += 14;
    if (/тендер|директ|сайт|квиз|выстав|битрикс|bitrix/.test(sourceText)) score += 10;
    if (hasPhone) score += 8;
    if (hasEmail) score += 6;
    if (hasResponsible) score += 8;
    if (hasNextAction) score += 8;
    if (probability >= 70) score += 10;
    else if (probability >= 40) score += 6;
    if (days !== null && days <= 1) score += 8;
    if (String(row?.priority || '') === 'high') score += 6;
    if (signals.isTender) score += 8;
    if ((signals.industries || []).length) score += 6;
    if ((signals.equipment || []).length) score += 6;
    if ((signals.regions || []).length) score += 4;
    if (route.key === 'unassigned') score -= 8;
    if (firstTouchSlaViolated) score -= 18;
    score = Math.max(0, Math.min(100, Math.round(score)));
    const temperature = score >= 76 ? 'Горячий' : score >= 52 ? 'Тёплый' : 'Холодный';
    const abc = budget >= 3000000 || signals.isTender ? 'A / стратегический' : /повтор|регуляр|действующ|существующ/.test(sourceText + ' ' + row?.comment) ? 'B / регулярный' : /спящ|реактивац|стар/.test(sourceText + ' ' + row?.comment) ? 'C / спящий' : 'C / новый';
    const tone = firstTouchSlaViolated ? 'critical' : score >= 76 ? 'positive' : score >= 52 ? 'attention' : 'neutral';
    const flags = [];
    if (!hasPhone && !hasEmail) flags.push('нет контактов');
    else if (!hasPhone) flags.push('нет телефона');
    else if (!hasEmail) flags.push('нет email');
    if (!hasResponsible) flags.push('не закреплён');
    if (!hasNextAction) flags.push('нет следующего шага');
    if (firstTouchSlaViolated) flags.push('SLA 24ч');
    if (budget >= 3000000) flags.push('крупный бюджет');
    if (route.key === 'unassigned') flags.push('низкая уверенность маршрута');
    return { score, temperature, abc, tone, route, flags, firstTouchSlaViolated, ageHours, signals };
}

function crmLeadRoutingStats(rows = []) {
    const scored = rows.map(row => ({ row, info: crmLeadScore(row) }));
    return {
        hot: scored.filter(item => item.info.score >= 76).length,
        unrouted: scored.filter(item => !String(item.row.responsible || '').trim() || item.info.route.key === 'unassigned').length,
        sla: scored.filter(item => item.info.firstTouchSlaViolated).length,
        strategic: rows.filter(row => Number(row.budget || 0) >= 3000000).length,
        lowConfidence: scored.filter(item => item.info.route.key === 'unassigned').length,
        equipment: scored.filter(item => (item.info.signals.equipment || []).length).length,
        top: scored.sort((a, b) => b.info.score - a.info.score).slice(0, 6),
        queue: scored.filter(item => !String(item.row.responsible || '').trim() || item.info.route.key === 'unassigned').slice(0, 8),
    };
}

function crmDateOffset(days = 0) {
    const date = new Date();
    date.setDate(date.getDate() + Number(days || 0));
    return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`;
}

function crmPresetStorageKey(entityType) {
    const userKey = String(currentUser?.email || currentUser?.name || 'default')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9а-яё._-]+/gi, '_');
    return `korda_crm_ops_presets_v1:${userKey}:${entityType}`;
}

function crmReadPresets(entityType) {
    try {
        const raw = localStorage.getItem(crmPresetStorageKey(entityType));
        const parsed = JSON.parse(raw || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function crmWritePresets(entityType, presets) {
    localStorage.setItem(crmPresetStorageKey(entityType), JSON.stringify(presets || []));
}

function crmFillPresetSelect(selectId, presets = []) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const currentValue = el.value || '';
    el.innerHTML = `<option value="">Пресет фильтра</option>${presets.map(item => `
        <option value="${crmEscape(item.name)}">${crmEscape(item.name)}</option>
    `).join('')}`;
    el.value = presets.some(item => item.name === currentValue) ? currentValue : '';
}

function crmDateSortValue(value, direction = 'asc') {
    const date = crmParseRuDate(value);
    if (date) return date.getTime();
    return direction === 'asc' ? Number.MAX_SAFE_INTEGER : Number.MIN_SAFE_INTEGER;
}

function crmTextCompare(left, right) {
    return String(left || '').localeCompare(String(right || ''), 'ru');
}

function crmSortLeadRows(rows = []) {
    const sorted = rows.slice();
    sorted.sort((left, right) => {
        switch (currentLeadSort) {
        case 'due_desc':
            return crmDateSortValue(right.next_action_date, 'desc') - crmDateSortValue(left.next_action_date, 'desc');
        case 'budget_desc':
            return Number(right.budget || 0) - Number(left.budget || 0);
        case 'title_asc':
            return crmTextCompare(left.title, right.title);
        case 'probability_desc':
            return Number(right.probability || 0) - Number(left.probability || 0);
        case 'due_asc':
        default:
            return crmDateSortValue(left.next_action_date, 'asc') - crmDateSortValue(right.next_action_date, 'asc');
        }
    });
    return sorted;
}

function crmSortDealRows(rows = []) {
    const sorted = rows.slice();
    sorted.sort((left, right) => {
        switch (currentDealSort) {
        case 'due_desc':
            return crmDateSortValue(right.next_action_date, 'desc') - crmDateSortValue(left.next_action_date, 'desc');
        case 'amount_desc':
            return Number(right.amount || 0) - Number(left.amount || 0);
        case 'title_asc':
            return crmTextCompare(left.title, right.title);
        case 'margin_desc':
            return Number(right.margin_percent || 0) - Number(left.margin_percent || 0);
        case 'due_asc':
        default:
            return crmDateSortValue(left.next_action_date, 'asc') - crmDateSortValue(right.next_action_date, 'asc');
        }
    });
    return sorted;
}

function fillResponsibleSelect(selectId, rows = [], currentValue = '') {
    const el = document.getElementById(selectId);
    if (!el) return;
    const options = crmCollectResponsibles(rows).map(name => `<option value="${crmEscape(name)}" ${currentValue === name ? 'selected' : ''}>${crmEscape(name)}</option>`).join('');
    el.innerHTML = `<option value="">Все ответственные</option>${options}`;
    el.value = currentValue || '';
}

function leadRowsFiltered() {
    return crmSortLeadRows((crmLeadsDB || []).filter(row => {
        if (currentLeadStage && String(row.stage || '') !== currentLeadStage) return false;
        if (currentLeadResponsible && String(row.responsible || '') !== currentLeadResponsible) return false;
        if (currentLeadSearch) {
            const haystack = [row.title, row.client_name, row.contact_name, row.source, row.next_action].join(' ').toLowerCase();
            if (!haystack.includes(currentLeadSearch.toLowerCase())) return false;
        }
        return true;
    }));
}

function dealRowsFiltered() {
    return crmSortDealRows((crmDealsDB || []).filter(row => {
        if (Boolean(Number(row.is_archived || 0)) !== currentDealArchiveView) return false;
        if (currentDealStage && String(row.stage || '') !== currentDealStage) return false;
        if (currentDealResponsible && String(row.responsible || '') !== currentDealResponsible) return false;
        if (currentDealSearch) {
            const haystack = [row.title, row.client_name, row.contract_number, row.next_action].join(' ').toLowerCase();
            if (!haystack.includes(currentDealSearch.toLowerCase())) return false;
        }
        return true;
    }));
}

function crmDealSharedStateFingerprint(rows = crmDealsDB) {
    return (Array.isArray(rows) ? rows : [])
        .map(row => [Number(row.id || 0), Number(row.is_archived || 0), Number(row.archived_at || 0), Number(row.updated_at || 0)].join(':'))
        .sort()
        .join('|');
}

function isDealsViewVisible() {
    const view = document.getElementById('dealsView');
    return Boolean(view && view.style.display !== 'none' && !view.hidden);
}

async function refreshDealsFromServer(forceRender = false) {
    if (dealSharedSyncInFlight || editingDealId || (!forceRender && !isDealsViewVisible())) return;
    dealSharedSyncInFlight = true;
    const before = crmDealSharedStateFingerprint();
    try {
        await loadCrmDeals();
        const after = crmDealSharedStateFingerprint();
        if (!forceRender && before === after) return;
        const selected = (crmDealsDB || []).find(row => Number(row.id || 0) === Number(currentDealId || 0));
        if (selected && Boolean(Number(selected.is_archived || 0)) !== currentDealArchiveView) currentDealId = 0;
        if (!selected) currentDealId = 0;
        skipDealEditorAutoOpenOnce = true;
        await renderDeals();
    } finally {
        dealSharedSyncInFlight = false;
    }
}

function startDealSharedArchiveSync() {
    if (dealSharedSyncTimer) return;
    dealSharedSyncTimer = window.setInterval(() => refreshDealsFromServer(false), 5000);
    window.addEventListener('focus', () => refreshDealsFromServer(false));
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshDealsFromServer(false);
    });
}

function renderLeadSummary() {
    const rows = leadRowsFiltered();
    const mount = document.getElementById('leadSummaryStrip');
    if (!mount) return;
    const hot = rows.filter(row => crmToneByDueDate(row.next_action_date) === 'critical' || String(row.priority || '') === 'high').length;
    const qualified = rows.filter(row => ['qualified', 'proposal'].includes(String(row.stage || ''))).length;
    const budget = rows.reduce((sum, row) => sum + Number(row.budget || 0), 0);
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Всего лидов</div><div class="crm-summary-value">${rows.length}</div><div class="crm-summary-meta">по выбранному этапу</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Готовятся к сделке</div><div class="crm-summary-value">${qualified}</div><div class="crm-summary-meta">потребность подтверждена</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Нужно действие</div><div class="crm-summary-value">${hot}</div><div class="crm-summary-meta">сегодня или просрочено</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Возможная сумма</div><div class="crm-summary-value">${crmFormatMoney(budget)}</div><div class="crm-summary-meta">не подтверждённая выручка</div></div>
    `;
}

function renderLeadRoutingPanel() {
    const mount = document.getElementById('leadRoutingPanel');
    if (!mount) return;
    const rows = leadRowsFiltered();
    const stats = crmLeadRoutingStats(rows);
    const settings = crmLeadRoutingSettings();
    const rules = crmLeadRoutingRules(settings);
    const canManage = crmCanManageLeadRouting();
    const urgent = stats.top.slice(0, 4);
    mount.innerHTML = `
        <section class="crm-intelligence-card lead-priority-panel">
            <div class="section-header lead-priority-panel__head">
                <div>
                    <span class="view-eyebrow">Помощник менеджера</span>
                    <h3 class="section-title">Какие лиды обработать в первую очередь</h3>
                    <p class="section-subtitle">Система поднимает наверх просроченные и перспективные заявки. Оценка — это подсказка, а не отдельный этап работы.</p>
                </div>
                <div class="lead-priority-legend">
                    <span><i class="is-critical"></i>Срочно</span>
                    <span><i class="is-positive"></i>Высокий приоритет</span>
                    <span><i class="is-neutral"></i>Обычный</span>
                </div>
            </div>
            <div class="lead-priority-stats">
                <div><span>Срочно связаться</span><strong>${stats.sla}</strong><small>первый контакт просрочен</small></div>
                <div><span>Высокий приоритет</span><strong>${stats.hot}</strong><small>самые перспективные</small></div>
                <div><span>Без менеджера</span><strong>${stats.unrouted}</strong><small>нужно назначить ответственного</small></div>
            </div>
            <div class="lead-priority-list">
                ${urgent.map(item => {
                    const row = item.row;
                    const info = item.info;
                    const priority = crmLeadPriorityView(info);
                    return `
                        <div class="lead-priority-item">
                            <div class="lead-priority-item__main">
                                <strong>${crmEscape(row.title || row.client_name || 'Лид')}</strong>
                                <span>${crmEscape(crmLeadPriorityReason(row, info))}</span>
                            </div>
                            <div class="lead-priority-item__owner"><span>Ответственный</span><strong>${crmEscape(row.responsible || 'не назначен')}</strong></div>
                            <span class="crm-inline-pill crm-inline-pill--${priority.tone}">${priority.label}</span>
                            <button class="btn-secondary" type="button" onclick="selectLeadRow(${Number(row.id || 0)})">Открыть</button>
                        </div>`;
                }).join('') || '<div class="empty-state">Лидов пока нет.</div>'}
            </div>
            ${canManage ? `
                <details class="lead-routing-admin">
                    <summary>Настройки распределения для руководителя</summary>
                    <p>Здесь задаётся, кому система рекомендует передавать крупные, тендерные, отраслевые и региональные заявки.</p>
                    <div class="lead-routing-admin__actions">
                        <button class="btn-secondary" type="button" onclick="autoAssignQualifiedLeads()">Назначить подходящие лиды</button>
                        <button class="btn-secondary" type="button" onclick="exportLeadRoutingDirectorReport()">Скачать отчёт</button>
                    </div>
                    <div class="crm-routing-settings">
                        <label><span>Сумма крупного лида</span><input id="leadRouteBudgetThreshold" class="auth-input" type="number" value="${crmEscape(settings.budgetThreshold)}"></label>
                        <label><span>Крупные лиды</span><input id="leadRouteSeniorManager" class="auth-input" type="text" value="${crmEscape(settings.seniorManager)}"></label>
                        <label><span>Тендеры</span><input id="leadRouteTenderManager" class="auth-input" type="text" value="${crmEscape(settings.tenderManager)}"></label>
                        <label><span>Отраслевые заявки</span><input id="leadRouteIndustryManager" class="auth-input" type="text" value="${crmEscape(settings.industryManager)}"></label>
                        <label><span>Оборудование</span><input id="leadRouteEquipmentManager" class="auth-input" type="text" value="${crmEscape(settings.equipmentManager)}"></label>
                        <label><span>Региональные заявки</span><input id="leadRouteRegionManager" class="auth-input" type="text" value="${crmEscape(settings.regionManager)}"></label>
                        <label><span>Обычные лиды</span><input id="leadRouteDefaultManager" class="auth-input" type="text" value="${crmEscape(settings.defaultManager)}"></label>
                        <label><span>Точность рекомендации, %</span><input id="leadRouteMinConfidence" class="auth-input" type="number" value="${crmEscape(settings.minConfidence)}"></label>
                        <div class="crm-routing-settings__actions"><button class="btn-primary" onclick="saveLeadRoutingSettings()">Сохранить правила</button><button class="btn-secondary" onclick="resetLeadRoutingSettings()">Вернуть стандартные</button></div>
                    </div>
                    <div class="lead-routing-rule-list">${rules.slice(0, 5).map(rule => `<div><strong>${crmEscape(rule.label)}</strong><span>${crmEscape(rule.manager)} · ${crmEscape(rule.note)}</span></div>`).join('')}</div>
                </details>` : ''}
        </section>
    `;
}

function renderDealSummary() {
    const rows = dealRowsFiltered();
    const mount = document.getElementById('dealSummaryStrip');
    if (!mount) return;
    const pipeline = rows.reduce((sum, row) => sum + Number(row.amount || 0), 0);
    const hot = rows.filter(row => crmToneByDueDate(row.next_action_date) === 'critical' || String(row.stage || '') === 'negotiation').length;
    const won = rows.filter(row => String(row.stage || '') === 'won').length;
    const avgMargin = rows.length ? Math.round(rows.reduce((sum, row) => sum + Number(row.margin_percent || 0), 0) / rows.length) : 0;
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Сделок в работе</div><div class="crm-summary-value">${rows.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Горячие переговоры</div><div class="crm-summary-value">${hot}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Выиграно</div><div class="crm-summary-value">${won}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Pipeline</div><div class="crm-summary-value">${crmFormatMoney(pipeline)}</div><div class="crm-summary-meta">ср. маржа ${avgMargin}%</div></div>
    `;
}

function renderCrmActivities(entityType, entityId, activities = []) {
    if (!activities.length) {
        return `<div class="empty-state">Активностей пока нет.</div>`;
    }
    return activities.map(item => `
        <div class="crm-activity-item">
            <div class="crm-activity-main">
                <div class="crm-activity-title">${crmEscape(item.subject || crmActivityLabel(item.activity_type))}</div>
                <div class="crm-activity-meta">${crmEscape(crmActivityLabel(item.activity_type))} · ${crmEscape(item.owner_name || 'не назначен')} · ${crmEscape(item.due_date || 'без срока')}</div>
                <div class="crm-activity-text">${crmEscape(item.summary || '')}</div>
            </div>
            <button class="btn-secondary" onclick="toggleCrmActivityStatus(${item.id}, '${crmEscape(entityType)}', ${entityId}, '${item.status === 'done' ? 'open' : 'done'}')">${item.status === 'done' ? 'Открыть' : 'Готово'}</button>
        </div>
    `).join('');
}

function crmLeadVisibleComment(value) {
    return String(value || '').split('\n').filter(line => !/^\[(Маршрутизация|КП)\b/.test(line.trim())).join('\n').trim();
}

function renderLeadDetail(row) {
    if (!row) return `<div class="lead-empty-card"><h3>Откройте лид из списка</h3><p>После открытия здесь появятся данные клиента, следующий шаг и рабочие действия.</p></div>`;
    const transferManagers = crmLeadTransferManagers(row);
    const isConverted = Number(row.linked_deal_id || 0) > 0;
    const isLost = String(row.stage || '') === 'lost';
    const isClosed = isConverted || isLost;
    const needsDealRecovery = String(row.stage || '') === 'won' && !isConverted;
    const visibleComment = crmLeadVisibleComment(row.comment);
    const activities = Array.isArray(row.activities) ? row.activities : [];
    return `
        <article class="lead-card">
            <div class="lead-card__head">
                <div>
                    <span class="view-eyebrow">Карточка лида №${Number(row.id || 0)}</span>
                    <h2>${crmEscape(row.title || 'Без названия')}</h2>
                    <p>${crmEscape(row.client_name || 'Компания не указана')} · ${crmEscape(row.contact_name || 'контакт не указан')}</p>
                </div>
                <span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</span>
            </div>

            <section class="lead-card__next crm-badge--${crmToneByDueDate(row.next_action_date)}">
                <div><span>Что сделать дальше</span><strong>${crmEscape(row.next_action || 'Следующий шаг не указан')}</strong></div>
                <div><span>До какого числа</span><strong>${crmEscape(row.next_action_date || 'Дата не указана')}</strong></div>
            </section>

            <div class="lead-card__columns">
                <section class="lead-card__section">
                    <h3>Клиент и контакты</h3>
                    <dl class="lead-card__data">
                        <div><dt>Компания</dt><dd>${crmEscape(row.client_name || 'Не указана')}</dd></div>
                        <div><dt>Контактное лицо</dt><dd>${crmEscape(row.contact_name || 'Не указано')}</dd></div>
                        <div><dt>Телефон</dt><dd>${crmEscape(row.contact_phone || 'Не указан')}</dd></div>
                        <div><dt>Почта</dt><dd>${crmEscape(row.contact_email || 'Не указана')}</dd></div>
                        <div><dt>Источник</dt><dd>${crmEscape(row.source || 'Не указан')}</dd></div>
                    </dl>
                </section>
                <section class="lead-card__section">
                    <h3>Квалификация</h3>
                    <dl class="lead-card__data">
                        <div><dt>Этап</dt><dd>${crmEscape(crmStageLabel(row.stage))}</dd></div>
                        <div><dt>Ответственный</dt><dd>${crmEscape(row.responsible || 'Не назначен')}</dd></div>
                        <div><dt>Возможная сумма</dt><dd>${crmFormatMoney(row.budget, row.currency)}</dd></div>
                        <div><dt>Вероятность</dt><dd>${Math.round(Number(row.probability || 0))}%</dd></div>
                    </dl>
                </section>
            </div>

            <section class="lead-card__section lead-card__need">
                <h3>Потребность и договорённости</h3>
                <p>${crmEscape(visibleComment || 'Потребность пока не описана.')}</p>
            </section>

            ${needsDealRecovery ? `<div class="lead-card__warning"><strong>Сделка ещё не создана</strong><span>Лид отмечен как переданный, но связанной сделки нет. Нажмите «Создать сделку» ниже — данные клиента перенесутся автоматически.</span></div>` : ''}

            <details class="lead-card__history">
                <summary>История контактов <span>${activities.length}</span></summary>
                <div class="crm-activity-list">${renderCrmActivities('lead', row.id, activities)}</div>
            </details>

            <div id="leadActivityPanel-${Number(row.id || 0)}" class="lead-card__panel" hidden>
                <div class="lead-card__panel-head"><div><h3>Зафиксировать контакт</h3><p>Запишите итог и назначьте следующий шаг.</p></div><button class="btn-secondary" type="button" onclick="toggleLeadActivityPanel(${Number(row.id || 0)}, false)">Закрыть</button></div>
                <div class="lead-activity-form">
                    <label><span>Как связались</span><select id="leadActivityType" class="auth-input"><option value="call">Звонок</option><option value="email">Письмо</option><option value="meeting">Встреча</option><option value="note">Заметка</option></select></label>
                    <label><span>Что сделать дальше *</span><input id="leadActivitySubject" class="auth-input" type="text" placeholder="Например: отправить уточнённое КП"></label>
                    <label><span>До какого числа *</span><input id="leadActivityDueDate" class="auth-input date-picker" type="text" placeholder="дд.мм.гггг" autocomplete="off"></label>
                    <label class="lead-activity-form__summary"><span>Результат контакта *</span><textarea id="leadActivitySummary" class="auth-input" rows="3" placeholder="О чём договорились и что важно учесть"></textarea></label>
                    <button class="btn-primary" type="button" onclick="createCrmActivity('lead', ${Number(row.id || 0)})">Сохранить контакт</button>
                </div>
            </div>

            ${!isClosed && transferManagers.length ? `
                <div id="leadTransferPanel-${Number(row.id || 0)}" class="lead-transfer-panel" style="display:none;">
                    <div><strong>Передать лид</strong><span>После сохранения лид исчезнет из вашего списка и появится у выбранного сотрудника.</span></div>
                    <label><span>Новый ответственный</span><select id="leadTransferManager-${Number(row.id || 0)}" class="auth-input"><option value="">Выберите сотрудника</option>${transferManagers.map(user => `<option value="${crmEscape(user.email || '')}">${crmEscape(user.name || '')} — ${crmEscape(user.role || '')}</option>`).join('')}</select></label>
                    <div class="lead-transfer-panel__actions"><button class="btn-secondary" type="button" onclick="toggleLeadTransferPanel(${Number(row.id || 0)}, false)">Отмена</button><button class="btn-primary" type="button" onclick="transferLeadToManager(${Number(row.id || 0)})">Сохранить передачу</button></div>
                </div>` : ''}

            <div id="leadLossPanel-${Number(row.id || 0)}" class="lead-loss-panel" hidden>
                <div><h3>Почему лид закрывается без сделки?</h3><p>Причина обязательна и сохранится в истории.</p></div>
                <textarea id="leadLossReason-${Number(row.id || 0)}" class="auth-input" rows="3" placeholder="Например: клиент отложил проект из-за отсутствия бюджета"></textarea>
                <div><button class="btn-secondary" type="button" onclick="toggleLeadLossPanel(${Number(row.id || 0)}, false)">Отмена</button><button class="btn-danger" type="button" onclick="closeLeadWithoutDeal(${Number(row.id || 0)})">Закрыть лид</button></div>
            </div>

            <div class="lead-card__actions">
                <button class="btn-secondary" type="button" onclick="openLeadEditor(${Number(row.id || 0)})">Изменить</button>
                ${!isClosed ? `<button class="btn-secondary" type="button" onclick="toggleLeadActivityPanel(${Number(row.id || 0)}, true)">Зафиксировать контакт</button>` : ''}
                ${!isClosed && transferManagers.length ? `<button class="btn-secondary" type="button" onclick="toggleLeadTransferPanel(${Number(row.id || 0)})">Передать</button>` : ''}
                ${!['proposal', 'won', 'lost'].includes(String(row.stage || '')) ? `<button class="btn-secondary" type="button" onclick="markLeadProposalSent(${Number(row.id || 0)})">КП отправлено</button>` : ''}
                ${isConverted ? `<button class="btn-primary" type="button" onclick="openLeadDeal(${Number(row.linked_deal_id || 0)})">Открыть сделку</button>` : (!isLost ? `<button class="btn-primary" type="button" onclick="convertLeadToDeal(${Number(row.id || 0)})">${needsDealRecovery ? 'Создать сделку' : 'Перевести в сделку'}</button>` : '')}
                ${!isClosed ? `<button class="btn-danger" type="button" onclick="toggleLeadLossPanel(${Number(row.id || 0)}, true)">Закрыть без сделки</button>` : ''}
            </div>
        </article>`;
}

function renderDealDetail(row) {
    if (!row) {
        return `<div class="empty-state">Выберите сделку из списка или добавьте новую.</div>`;
    }
    const stage = crmDealStageInfo(row.stage);
    const products = crmDealProducts(row);
    const attachedDocuments = Array.isArray(row.documents) ? row.documents : [];
    const stageKeys = ['qualification', 'proposal', 'negotiation', 'won'];
    const activeStageIndex = Math.max(0, stageKeys.indexOf(String(row.stage || 'qualification')));
    const canManage = crmCanManageDeal(row);
    return `
        <div class="crm-detail-card deal-detail-card">
            <div class="crm-detail-head deal-detail-head">
                <div>
                    <span class="view-eyebrow">Сделка №${Number(row.id || 0)}</span>
                    <div class="crm-detail-title">${crmEscape(row.title || 'Без названия')}</div>
                    <div class="crm-detail-meta">${crmEscape(row.client_name || 'Клиент не указан')} · создана ${crmEscape(row.created_at ? new Date(Number(row.created_at) * 1000).toLocaleDateString('ru-RU') : '—')}</div>
                </div>
                <div class="view-actions">
                    ${!canManage ? '<span class="crm-inline-pill crm-inline-pill--neutral">Только просмотр</span>' : ''}
                </div>
            </div>

            <section class="deal-stage-panel">
                <div class="deal-stage-panel__copy"><span>Текущий этап</span><strong>${crmEscape(stage.label)}</strong><small>${crmEscape(stage.help)}</small></div>
                <div class="deal-stage-track">
                    ${stageKeys.map((key, index) => `<div class="deal-stage-step ${index <= activeStageIndex && row.stage !== 'lost' ? 'is-complete' : ''} ${row.stage === key ? 'is-active' : ''}"><i>${index + 1}</i><span>${crmEscape(crmDealStageInfo(key).label)}</span></div>`).join('')}
                    <div class="deal-stage-step deal-stage-step--lost ${row.stage === 'lost' ? 'is-active' : ''}"><i>×</i><span>Клиент отказался</span></div>
                </div>
            </section>

            <section class="deal-next-step crm-badge--${crmToneByDueDate(row.next_action_date)}">
                <div><span>Что сделать дальше</span><strong>${crmEscape(row.next_action || 'Следующий шаг не указан')}</strong></div>
                <div><span>Срок</span><strong>${crmEscape(row.next_action_date || 'Нет даты')}</strong></div>
            </section>

            <div class="deal-info-grid">
                <section class="deal-section-card">
                    <div class="deal-section-card__head"><div><h3>Клиент и контакты</h3><p>С кем менеджер ведёт переговоры.</p></div></div>
                    <dl class="deal-data-list">
                        <div><dt>Компания</dt><dd>${crmEscape(row.client_name || 'Не указана')}</dd></div>
                        <div><dt>Контакт</dt><dd>${crmEscape([row.contact_name, row.contact_position].filter(Boolean).join(', ') || 'Не указан')}</dd></div>
                        <div><dt>Телефон</dt><dd>${crmEscape(row.contact_phone || 'Не указан')}</dd></div>
                        <div><dt>Почта</dt><dd>${crmEscape(row.contact_email || 'Не указана')}</dd></div>
                        <div><dt>Источник</dt><dd>${crmEscape(row.source || 'Не указан')}</dd></div>
                    </dl>
                </section>
                <section class="deal-section-card">
                    <div class="deal-section-card__head"><div><h3>Деньги и сроки</h3><p>Плановые показатели сделки.</p></div></div>
                    <dl class="deal-data-list">
                        <div><dt>Сумма</dt><dd>${crmFormatMoney(row.amount, row.currency)}</dd></div>
                        <div><dt>Маржа</dt><dd>${Math.round(Number(row.margin_percent || 0))}%</dd></div>
                        <div><dt>Вероятность</dt><dd>${Math.round(Number(row.probability || 0))}%</dd></div>
                        <div><dt>План завершения</dt><dd>${crmEscape(row.expected_close_date || 'Не указан')}</dd></div>
                        <div><dt>Фактически завершена</dt><dd>${crmEscape(row.actual_close_date || '—')}</dd></div>
                    </dl>
                </section>
                <section class="deal-section-card">
                    <div class="deal-section-card__head"><div><h3>Ответственные</h3><p>Кто ведёт сделку и помогает.</p></div></div>
                    <dl class="deal-data-list">
                        <div><dt>Менеджер</dt><dd>${crmEscape(row.responsible || 'Не назначен')}</dd></div>
                        <div><dt>Помогают</dt><dd>${crmEscape(row.co_executors || 'Не указаны')}</dd></div>
                        <div><dt>№ КП / договора</dt><dd>${crmEscape(row.contract_number || 'Не указан')}</dd></div>
                    </dl>
                </section>
            </div>

            <section class="deal-section-card deal-products-card">
                <div class="deal-section-card__head"><div><h3>Что продаём</h3><p>Товары и услуги, входящие в сделку.</p></div></div>
                <div class="deal-products-table">
                    <div class="deal-products-table__head"><span>Товар или услуга</span><span>Количество</span><span>Цена</span><span>Сумма</span></div>
                    ${products.map(item => { const quantity = Number(item.quantity || 0); const price = Number(item.unit_price || 0); return `<div><strong>${crmEscape(item.name)}</strong><span>${quantity || 1}</span><span>${crmFormatMoney(price, row.currency)}</span><strong>${crmFormatMoney((quantity || 1) * price, row.currency)}</strong></div>`; }).join('') || '<div class="empty-state">Состав продажи ещё не заполнен.</div>'}
                </div>
            </section>

            <section class="deal-section-card deal-documents-card">
                <div class="deal-section-card__head"><div><h3>Документы и файлы</h3><p>КП, договоры, счета, акты и технические задания по этой сделке.</p></div><button class="btn-secondary" onclick="navigateTo('documents')">Открыть общий архив</button></div>
                <div class="deal-attached-documents deal-attached-documents--summary">${attachedDocuments.map(doc => `<div class="deal-attached-document"><div><strong>${crmEscape(doc.number || `#${doc.id}`)}</strong><span>${crmEscape(doc.subject || 'Без темы')}</span></div><div>${doc.file_url ? `<a class="btn-secondary" href="${crmEscape(doc.file_url)}" target="_blank" rel="noopener">Открыть файл</a>` : '<span class="crm-inline-pill">Файл не загружен</span>'}</div></div>`).join('') || '<div class="empty-state">Документы к сделке пока не прикреплены.</div>'}</div>
            </section>

            <section class="deal-section-card">
                <div class="deal-section-card__head"><div><h3>Комментарии</h3><p>Особые условия и важные договорённости.</p></div></div>
                <div class="crm-detail-note">${crmEscape(row.comment || 'Комментариев пока нет.')}</div>
                ${['won', 'lost'].includes(String(row.stage || '')) ? `<div class="deal-loss-reason"><span>${row.stage === 'won' ? 'Причина успешного завершения' : 'Причина отказа клиента'}</span><strong>${crmEscape(row.loss_reason || 'Не указана')}</strong></div>` : ''}
            </section>

            <div class="deal-card-actions">
                ${!canManage ? '<span class="deal-card-actions__note">Карточка доступна только для просмотра</span>' : ''}
                ${canManage && Number(row.is_archived || 0) ? `<button class="btn-secondary" type="button" onclick="restoreDealFromArchive(${row.id})">Вернуть из архива</button>` : ''}
                ${canManage && !Number(row.is_archived || 0) && ['won', 'lost'].includes(String(row.stage || '')) ? `<button class="btn-secondary" type="button" onclick="archiveDeal(${row.id})">Отправить в архив</button>` : ''}
                ${canManage && !Number(row.is_archived || 0) ? `<button class="btn-primary" type="button" onclick="openDealEditor(${row.id})">Редактировать сделку</button>` : ''}
            </div>

        </div>
    `;
}

function renderLeadRegistry() {
    const rows = leadRowsFiltered();
    const selected = rows.find(row => Number(row.id) === Number(currentLeadId)) || null;
    return `
        <div class="crm-registry-layout">
            <section class="lead-list-card">
                <div class="lead-list-card__head"><div><h2>Список лидов</h2><p>Откройте лид, чтобы увидеть всю информацию и продолжить работу.</p></div><strong>${rows.length}</strong></div>
                <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 25%;">
                        <col style="width: 18%;">
                        <col style="width: 15%;">
                        <col style="width: 20%;">
                        <col style="width: 10%;">
                        <col style="width: 12%;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Лид</th>
                            <th>Контакт</th>
                            <th>Этап</th>
                            <th>Следующее действие</th>
                            <th class="is-num">Сумма</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => {
                            return `
                            <tr class="${Number(row.id) === Number(currentLeadId) ? 'is-selected' : ''}" onclick="selectLeadRow(${row.id})">
                                <td class="crm-title-cell"><strong>${crmEscape(row.title || '—')}</strong><div class="table-subtext">${crmEscape(row.client_name || 'Компания не указана')}</div></td>
                                <td class="crm-contact-cell"><strong>${crmEscape(row.contact_name || 'Не указан')}</strong><div class="table-subtext">${crmEscape(row.contact_phone || row.contact_email || 'Нет контактов')}</div></td>
                                <td><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</span><div class="table-subtext">${crmEscape(row.responsible || 'не назначен')}</div></td>
                                <td class="crm-action-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span><div class="table-subtext">${crmEscape(row.next_action || '—')}</div></td>
                                <td class="is-num amount crm-amount-cell">${crmFormatMoney(row.budget, row.currency)}</td>
                                <td class="lead-table-action"><button class="btn-secondary" type="button" onclick="event.stopPropagation(); selectLeadRow(${row.id})">Открыть лид</button></td>
                            </tr>
                        `; }).join('') || '<tr><td colspan="6"><div class="empty-state">Лиды по текущему фильтру не найдены.</div></td></tr>'}
                    </tbody>
                </table>
                </div>
            </section>
            <div class="lead-card-workspace">
                <div id="leadEditorPanel" class="crm-editor-panel" style="display:none;"></div>
                ${renderLeadDetail(selected)}
            </div>
        </div>
    `;
}

function renderDealRegistry() {
    const rows = dealRowsFiltered();
    if (!rows.some(row => Number(row.id) === Number(currentDealId))) currentDealId = Number(rows[0]?.id || 0);
    const selected = rows.find(row => Number(row.id) === Number(currentDealId)) || null;
    return `
        <div class="crm-registry-layout">
            <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 29%;">
                        <col style="width: 24%;">
                        <col style="width: 23%;">
                        <col style="width: 14%;">
                        <col style="width: 10%;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Сделка</th>
                            <th>Этап</th>
                            <th>Следующее действие</th>
                            <th class="is-num">Сумма</th>
                            <th>Действие</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr class="${Number(row.id) === Number(currentDealId) ? 'is-selected' : ''}" onclick="selectDealRow(${row.id})">
                                <td class="crm-title-cell"><strong>${crmEscape(row.title || '—')}</strong><div class="table-subtext">${crmEscape(row.client_name || 'Клиент не указан')}</div><div class="table-subtext">${crmEscape(row.responsible || 'Ответственный не назначен')}</div></td>
                                <td class="crm-stage-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmDealStageInfo(row.stage).label)}</span><div class="table-subtext">Вероятность ${Math.round(Number(row.probability || 0))}%</div></td>
                                <td class="crm-action-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span><div class="table-subtext">${crmEscape(row.next_action || '—')}</div></td>
                                <td class="is-num amount crm-amount-cell">${crmFormatMoney(row.amount, row.currency)}</td>
                                <td><button class="btn-secondary" type="button" onclick="event.stopPropagation(); selectDealRow(${row.id})">Открыть</button></td>
                            </tr>
                        `).join('') || `<tr><td colspan="5"><div class="empty-state">${currentDealArchiveView ? 'В архиве пока нет сделок.' : 'Сделки по текущему фильтру не найдены.'}</div></td></tr>`}
                    </tbody>
                </table>
            </div>
            <div class="deal-card-workspace">
                <div id="dealEditorPanel" class="crm-editor-panel" style="display:none;"></div>
                ${renderDealDetail(selected)}
            </div>
            <div id="dealSummaryStrip" class="crm-summary-strip"></div>
        </div>
    `;
}

function renderKanban(columns, rows, entityType) {
    return `
        <div class="crm-kanban">
            ${columns.map(column => `
                <div class="crm-kanban-column">
                    <div class="crm-kanban-head">
                        <div class="crm-kanban-title">${crmEscape(column.label)}</div>
                        <div class="crm-kanban-count">${rows.filter(row => String(row.stage || '') === column.key).length}</div>
                    </div>
                    <div class="crm-kanban-cards">
                        ${rows.filter(row => String(row.stage || '') === column.key).map(row => `
                            <button class="crm-kanban-card" onclick="${entityType === 'lead' ? `selectLeadRow(${row.id})` : `selectDealRow(${row.id})`}">
                                <div class="crm-kanban-card-title">${crmEscape(row.title || '—')}</div>
                                <div class="crm-kanban-card-meta">${crmEscape(row.client_name || '—')}</div>
                                <div class="crm-kanban-card-footer">
                                    <span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span>
                                    <strong>${entityType === 'lead' ? crmFormatMoney(row.budget, row.currency) : crmFormatMoney(row.amount, row.currency)}</strong>
                                </div>
                            </button>
                        `).join('') || '<div class="empty-state">Пусто</div>'}
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function openLeadEditor(leadId = 0) {
    editingLeadId = Number(leadId || 0);
    const panel = document.getElementById('leadEditorPanel');
    if (!panel) return;
    const detail = document.querySelector('#leadsView .lead-card-workspace > .lead-card, #leadsView .lead-card-workspace > .lead-empty-card');
    const row = (crmLeadsDB || []).find(item => Number(item.id) === editingLeadId) || { tags: [] };
    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="lead-editor-head"><div><span class="view-eyebrow">${editingLeadId ? 'Редактирование лида' : 'Создание лида'}</span><h3>${editingLeadId ? crmEscape(row.title || 'Изменить лид') : 'Новый лид'}</h3><p>Пройдите три коротких шага. После сохранения появится готовая карточка лида.</p></div></div>
        <div class="lead-editor-steps">
            <section class="lead-editor-step">
                <div class="lead-editor-step__head"><span>1</span><div><h4>Клиент и потребность</h4><p>Кто обратился и что ему требуется.</p></div></div>
                <div class="lead-editor-grid">
                    <label><span>Название лида *</span><input id="leadFormTitle" class="auth-input" type="text" placeholder="Например: поставка шумоглушителей" value="${crmEscape(row.title || '')}"></label>
                    <label><span>Компания *</span><input id="leadFormClient" class="auth-input" type="text" placeholder="Название компании" value="${crmEscape(row.client_name || '')}"></label>
                    <label><span>Контактное лицо</span><input id="leadFormContact" class="auth-input" type="text" placeholder="ФИО и должность" value="${crmEscape(row.contact_name || '')}"></label>
                    <label><span>Телефон</span><input id="leadFormPhone" class="auth-input" type="tel" placeholder="+7 ..." value="${crmEscape(row.contact_phone || '')}"></label>
                    <label><span>Почта</span><input id="leadFormEmail" class="auth-input" type="email" placeholder="name@company.ru" value="${crmEscape(row.contact_email || '')}"></label>
                    <label><span>Источник</span><input id="leadFormSource" class="auth-input" type="text" placeholder="Bitrix24, сайт, рекомендация" value="${crmEscape(row.source || '')}"></label>
                    <label class="lead-editor-grid__wide"><span>Потребность и договорённости *</span><textarea id="leadFormComment" class="auth-input" rows="3" placeholder="Что нужно клиенту, объём, сроки и важные условия">${crmEscape(crmLeadVisibleComment(row.comment))}</textarea></label>
                </div>
            </section>
            <section class="lead-editor-step">
                <div class="lead-editor-step__head"><span>2</span><div><h4>Квалификация</h4><p>Насколько понятна и перспективна заявка.</p></div></div>
                <div class="lead-editor-grid">
                    <label><span>Этап</span><select id="leadFormStage" class="auth-input">
                        <option value="new" ${row.stage === 'new' ? 'selected' : ''}>Новый — уточняем потребность</option>
                        <option value="qualified" ${row.stage === 'qualified' ? 'selected' : ''}>Потребность подтверждена</option>
                        <option value="proposal" ${row.stage === 'proposal' ? 'selected' : ''}>Готовится или отправлено КП</option>
                        ${row.stage === 'won' ? '<option value="won" selected disabled>Передан в сделку — меняется кнопкой в карточке</option>' : ''}
                        ${row.stage === 'lost' ? '<option value="lost" selected disabled>Закрыт без сделки — указана причина</option>' : ''}
                    </select></label>
                    <label><span>Возможная сумма, ₽</span><input id="leadFormBudget" class="auth-input" type="number" min="0" placeholder="0" value="${crmEscape(row.budget || 0)}"></label>
                    <label><span>Вероятность сделки, %</span><input id="leadFormProbability" class="auth-input" type="number" min="0" max="100" placeholder="0" value="${crmEscape(row.probability || 0)}"></label>
                    <label><span>Ответственный</span><input id="leadFormResponsible" class="auth-input" type="text" value="${crmEscape(row.responsible || currentUser?.name || '')}" readonly></label>
                    <input id="leadFormTags" type="hidden" value="${crmEscape((row.tags || []).join(', '))}">
                </div>
            </section>
            <section class="lead-editor-step">
                <div class="lead-editor-step__head"><span>3</span><div><h4>Следующее действие</h4><p>Что конкретно менеджер делает дальше и до какой даты.</p></div></div>
                <div class="lead-editor-grid">
                    <label><span>Следующий шаг *</span><input id="leadFormNextAction" class="auth-input" type="text" placeholder="Например: уточнить объём и подготовить КП" value="${crmEscape(row.next_action || '')}"></label>
                    <label><span>До какого числа *</span><input id="leadFormNextActionDate" class="auth-input date-picker" type="text" placeholder="дд.мм.гггг" value="${crmEscape(row.next_action_date || '')}" autocomplete="off"></label>
                </div>
            </section>
        </div>
        <div class="crm-editor-actions">
            <button class="btn-secondary" onclick="closeLeadEditor()">Отмена</button>
            <button class="btn-primary" onclick="saveLead()">Сохранить лид</button>
        </div>
    `;
    if (detail) detail.hidden = true;
    initLeadDatePickers();
    panel.scrollIntoView({ behavior: 'auto', block: 'start' });
    window.setTimeout(() => document.getElementById('leadFormTitle')?.focus(), 0);
}

function openDealEditor(dealId = 0) {
    editingDealId = Number(dealId || 0);
    editingDealStep = 1;
    const panel = document.getElementById('dealEditorPanel');
    if (!panel) return;
    const detail = document.querySelector('#dealsView .deal-card-workspace > .deal-detail-card');
    const row = (crmDealsDB || []).find(item => Number(item.id) === editingDealId) || { tags: [] };
    if (editingDealId && !crmCanManageDeal(row)) {
        editingDealId = 0;
        panel.style.display = 'none';
        if (detail) detail.hidden = false;
        return customAlert('Эта сделка доступна только для просмотра. Изменять её может ответственный сотрудник или директор.');
    }
    if (detail) detail.hidden = true;
    const productsText = crmDealProducts(row).map(item => `${item.name || ''} | ${Number(item.quantity || 1)} | ${Number(item.unit_price || 0)}`).join('\n');
    const attachedDocumentIds = new Set((Array.isArray(row.documents) ? row.documents : []).map(item => Number(item.id || 0)));
    const normalizedClientName = String(row.client_name || row.title || '').trim().toLocaleLowerCase('ru-RU');
    const editorDocuments = (Array.isArray(documentsDB) ? documentsDB : []).map(doc => {
        const documentDealId = Number(doc.deal_id || 0);
        const documentClientId = Number(doc.client_id || 0);
        const intendedById = documentClientId > 0 && Number(row.client_id || 0) > 0 && documentClientId === Number(row.client_id || 0);
        const documentRoute = [doc.correspondent, doc.sender_name, doc.recipient_name].map(value => String(value || '').trim().toLocaleLowerCase('ru-RU'));
        const intendedByName = Boolean(normalizedClientName) && documentRoute.includes(normalizedClientName);
        return {
            ...doc,
            _attached: attachedDocumentIds.has(Number(doc.id || 0)),
            _intendedForClient: intendedById || intendedByName,
            _linkedToCurrentDeal: documentDealId > 0 && documentDealId === editingDealId,
            _hasFile: Boolean(doc.file_url),
            _belongsToOtherDeal: documentDealId > 0 && documentDealId !== editingDealId,
        };
    }).filter(doc => !doc._belongsToOtherDeal || doc._intendedForClient)
      .sort((left, right) => Number(right._attached) - Number(left._attached)
        || Number(right._linkedToCurrentDeal) - Number(left._linkedToCurrentDeal)
        || Number(right._intendedForClient) - Number(left._intendedForClient)
        || Number(right.id || 0) - Number(left.id || 0));
    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="deal-editor-head"><div><span class="view-eyebrow">${editingDealId ? 'Подготовка и ведение сделки' : 'Новая сделка'}</span><h3>${editingDealId ? crmEscape(row.title || 'Сделка') : 'Добавить сделку'}</h3><p id="dealEditorStageNote">Шаг 1 из 5 · укажите текущий этап и ближайшее действие менеджера.</p></div></div>
        <nav class="deal-editor-stepper" aria-label="Шаги заполнения сделки">
            <button type="button" class="deal-editor-step is-active" data-deal-editor-step-button="1" onclick="switchDealEditorStep(1)"><i>1</i><span>Этап и действие</span></button>
            <button type="button" class="deal-editor-step" data-deal-editor-step-button="2" onclick="switchDealEditorStep(2)"><i>2</i><span>Клиент</span></button>
            <button type="button" class="deal-editor-step" data-deal-editor-step-button="3" onclick="switchDealEditorStep(3)"><i>3</i><span>Состав продажи</span></button>
            <button type="button" class="deal-editor-step" data-deal-editor-step-button="4" onclick="switchDealEditorStep(4)"><i>4</i><span>Деньги и сроки</span></button>
            <button type="button" class="deal-editor-step" data-deal-editor-step-button="5" onclick="switchDealEditorStep(5)"><i>5</i><span>Документы и итог</span></button>
        </nav>
        <div class="deal-editor-sections">
            <section class="deal-editor-section is-active" data-deal-editor-step="1"><h4>Текущий этап сделки</h4><p>Это основной рабочий шаг менеджера по этому клиенту.</p><div class="deal-editor-grid">
                <label class="deal-editor-grid__wide"><span>Клиент / компания *</span><input id="dealFormClient" class="auth-input" type="text" placeholder="Название клиента или компании" value="${crmEscape(row.client_name || row.title || '')}"></label>
                <label><span>Рабочий этап</span><select id="dealFormStage" class="auth-input"><option value="qualification" ${row.stage === 'qualification' ? 'selected' : ''}>Уточняем заказ</option><option value="proposal" ${row.stage === 'proposal' ? 'selected' : ''}>Готовим документы и счёт</option><option value="negotiation" ${row.stage === 'negotiation' ? 'selected' : ''}>Согласовываем условия</option>${row.stage === 'won' ? '<option value="won" selected>Успешно завершено</option>' : ''}${row.stage === 'lost' ? '<option value="lost" selected>Клиент отказался</option>' : ''}</select></label>
                <label><span>Ответственный</span><input id="dealFormResponsible" class="auth-input" type="text" placeholder="ФИО менеджера" value="${crmEscape(row.responsible || currentUser?.name || '')}"></label>
                <label><span>Следующий шаг *</span><input id="dealFormNextAction" class="auth-input" type="text" placeholder="Например: согласовать договор" value="${crmEscape(row.next_action || '')}"></label>
                <label><span>Выполнить до</span><input id="dealFormNextActionDate" class="auth-input" type="text" placeholder="дд.мм.гггг" value="${crmEscape(row.next_action_date || '')}"></label>
            </div></section>
            <section class="deal-editor-section" data-deal-editor-step="2"><h4>Контакт клиента</h4><p>Заполните данные человека, с которым идёт работа по сделке.</p><div class="deal-editor-grid">
                <label><span>ФИО</span><input id="dealFormContactName" class="auth-input" type="text" placeholder="Контактное лицо" value="${crmEscape(row.contact_name || '')}"></label>
                <label><span>Должность</span><input id="dealFormContactPosition" class="auth-input" type="text" placeholder="Должность" value="${crmEscape(row.contact_position || '')}"></label>
                <label><span>Телефон</span><input id="dealFormContactPhone" class="auth-input" type="text" placeholder="+7 ..." value="${crmEscape(row.contact_phone || '')}"></label>
                <label><span>Почта</span><input id="dealFormContactEmail" class="auth-input" type="email" placeholder="name@company.ru" value="${crmEscape(row.contact_email || '')}"></label>
                <label><span>Источник клиента</span><input id="dealFormSource" class="auth-input" type="text" placeholder="Сайт, рекомендация, выставка" value="${crmEscape(row.source || '')}"></label>
                <label><span>Кто помогает</span><input id="dealFormCoExecutors" class="auth-input" type="text" placeholder="ФИО через запятую" value="${crmEscape(row.co_executors || '')}"></label>
            </div></section>
            <section class="deal-editor-section" data-deal-editor-step="3"><h4>Состав продажи</h4><p>Каждая строка: название | количество | цена за единицу.</p><textarea id="dealFormProducts" class="auth-input" rows="5" placeholder="Шумоглушитель | 2 | 450000">${crmEscape(productsText)}</textarea></section>
            <section class="deal-editor-section" data-deal-editor-step="4"><h4>Деньги и сроки</h4><p>Плановые показатели. Фактическое завершение указывается только на последнем шаге.</p><div class="deal-editor-grid">
                <label><span>Сумма сделки</span><input id="dealFormAmount" class="auth-input" type="number" min="0" value="${crmEscape(row.amount || 0)}"></label>
                <label><span>Маржа, %</span><input id="dealFormMargin" class="auth-input" type="number" value="${crmEscape(row.margin_percent || 0)}"></label>
                <label><span>Вероятность, %</span><input id="dealFormProbability" class="auth-input" type="number" min="0" max="100" value="${crmEscape(row.probability || 0)}"></label>
                <label><span>План завершения</span><input id="dealFormExpectedCloseDate" class="auth-input" type="text" placeholder="дд.мм.гггг" value="${crmEscape(row.expected_close_date || '')}"></label>
                <label><span>№ КП или договора</span><input id="dealFormContract" class="auth-input" type="text" placeholder="Например: КП-124" value="${crmEscape(row.contract_number || '')}"></label>
            </div></section>
            <section class="deal-editor-section" data-deal-editor-step="5"><h4>Документы и итог сделки</h4><p>Выберите документы из Канцелярии, добавьте комментарий и при необходимости завершите сделку.</p>
                <div class="deal-editor-documents">
                    <div class="deal-editor-documents__head"><div><strong>Документы по этой сделке</strong><span>Сначала показаны файлы, уже связанные со сделкой и клиентом. Документ без файла прикрепить нельзя.</span></div><button class="btn-secondary" type="button" onclick="openDealDocumentModal(${Number(editingDealId || 0)})">+ Добавить документ</button></div>
                    <div class="deal-editor-document-list">${editorDocuments.map(doc => {
                        const selected = doc._attached;
                        const unavailable = doc._belongsToOtherDeal || !doc._hasFile;
                        const statusLabel = !doc._hasFile ? 'Нет файла' : doc._belongsToOtherDeal ? 'В другой сделке' : selected ? 'Прикреплён' : doc._intendedForClient ? 'Для этого клиента' : 'Доступен';
                        const statusClass = unavailable ? 'is-unavailable' : selected ? 'is-attached' : doc._intendedForClient ? 'is-intended' : 'is-free';
                        return `<label class="deal-editor-document-option ${selected ? 'is-selected' : ''} ${unavailable ? 'is-disabled' : ''}"><input type="checkbox" name="dealFormDocumentIds" value="${Number(doc.id || 0)}" ${selected ? 'checked' : ''} ${unavailable ? 'disabled' : ''} onchange="this.closest('.deal-editor-document-option')?.classList.toggle('is-selected', this.checked)"><span><strong>${crmEscape(crmDocumentKindLabel(doc.document_kind_code, doc))} · ${crmEscape(doc.number || `№${doc.id}`)}</strong><small>${crmEscape(doc.subject || 'Без названия')}${doc.file_url ? ' · файл загружен' : ''}</small></span><em class="deal-editor-document-status ${statusClass}">${statusLabel}</em></label>`;
                    }).join('') || '<div class="empty-state">В Канцелярии пока нет доступных документов.</div>'}</div>
                </div>
                <input id="dealFormActualCloseDate" type="hidden" value="${crmEscape(row.actual_close_date || '')}">
                <input id="dealFormLossReason" type="hidden" value="${crmEscape(row.loss_reason || '')}">
                <div class="deal-editor-grid">
                <label><span>Метки</span><input id="dealFormTags" class="auth-input" type="text" placeholder="Через запятую" value="${crmEscape((row.tags || []).join(', '))}"></label>
                <label class="deal-editor-grid__wide"><span>Комментарий</span><textarea id="dealFormComment" class="auth-input" rows="3" placeholder="Особые условия и договорённости">${crmEscape(row.comment || '')}</textarea></label>
            </div></section>
        </div>
        <div class="crm-editor-actions">
            <button class="btn-secondary" onclick="closeDealEditor()">Отмена</button>
            <div class="deal-editor-actions__progress">Шаг <strong id="dealEditorStepCurrent">1</strong> из 5</div>
            <button id="dealEditorBackBtn" class="btn-secondary" onclick="dealEditorPreviousStep()" hidden>Назад</button>
            <button id="dealEditorNextBtn" class="btn-primary" onclick="dealEditorNextStep()">Далее</button>
            <button id="dealEditorSaveBtn" class="btn-primary" onclick="saveDeal()" hidden>Сохранить изменения</button>
            <button id="dealEditorWonBtn" class="btn-success" onclick="saveDeal('won')" hidden>Сделка завершена</button>
            <button id="dealEditorLostBtn" class="btn-danger" onclick="saveDeal('lost')" hidden>Клиент отказался</button>
        </div>
    `;
    updateDealEditorStageFields();
    switchDealEditorStep(1, false);
}

function closeLeadEditor() {
    editingLeadId = 0;
    const panel = document.getElementById('leadEditorPanel');
    if (panel) panel.style.display = 'none';
    const detail = document.querySelector('#leadsView .lead-card-workspace > .lead-card, #leadsView .lead-card-workspace > .lead-empty-card');
    if (detail) detail.hidden = false;
}

function initLeadDatePickers() {
    if (typeof flatpickr !== 'function') return;
    ['leadFormNextActionDate', 'leadActivityDueDate'].forEach(id => {
        const input = document.getElementById(id);
        if (!input || input._flatpickr) return;
        flatpickr(input, { locale: 'ru', dateFormat: 'd.m.Y', disableMobile: true, allowInput: true });
    });
}

function toggleLeadActivityPanel(leadId, show) {
    const panel = document.getElementById(`leadActivityPanel-${Number(leadId || 0)}`);
    if (!panel) return;
    panel.hidden = !show;
    if (show) {
        initLeadDatePickers();
        panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function toggleLeadLossPanel(leadId, show) {
    const panel = document.getElementById(`leadLossPanel-${Number(leadId || 0)}`);
    if (!panel) return;
    panel.hidden = !show;
    if (show) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(() => document.getElementById(`leadLossReason-${Number(leadId || 0)}`)?.focus(), 180);
    }
}

function crmLeadPayloadFromRow(row, overrides = {}) {
    return {
        title: row.title || '',
        client_name: row.client_name || '',
        contact_name: row.contact_name || '',
        contact_email: row.contact_email || '',
        contact_phone: row.contact_phone || '',
        source: row.source || '',
        stage: row.stage || 'new',
        responsible: row.responsible || '',
        next_action: row.next_action || '',
        next_action_date: row.next_action_date || '',
        budget: Number(row.budget || 0),
        probability: Number(row.probability || 0),
        tags: Array.isArray(row.tags) ? row.tags : [],
        comment: row.comment || '',
        currency: row.currency || 'RUB',
        priority: row.priority || 'normal',
        linked_client_id: Number(row.linked_client_id || 0),
        linked_project_id: Number(row.linked_project_id || 0),
        linked_deal_id: Number(row.linked_deal_id || 0),
        ...overrides,
    };
}

async function closeLeadWithoutDeal(leadId) {
    const id = Number(leadId || 0);
    const row = (crmLeadsDB || []).find(item => Number(item.id || 0) === id);
    if (!row) return customAlert('Лид не найден.');
    const reason = String(document.getElementById(`leadLossReason-${id}`)?.value || '').trim();
    if (reason.length < 3) return customAlert('Укажите причину закрытия лида.');
    const today = crmDateOffset(0);
    const result = await apiCall(`/crm/leads/${id}`, 'PUT', crmLeadPayloadFromRow(row, {
        stage: 'lost',
        next_action: '',
        next_action_date: '',
        comment: [crmLeadVisibleComment(row.comment), `[Закрыт без сделки ${today}] Причина: ${reason}`].filter(Boolean).join('\n'),
    }));
    if (!result || result.error) return customAlert(result?.message || 'Не удалось закрыть лид.');
    await apiCall('/crm/activities', 'POST', {
        entity_type: 'lead',
        entity_id: id,
        activity_type: 'note',
        subject: 'Лид закрыт без сделки',
        summary: `Причина: ${reason}`,
        due_date: today,
        owner_name: currentUser?.name || '',
        status: 'done',
    });
    currentLeadId = id;
    await loadCrmLeads();
    renderLeads();
    showToast('Лиды', 'Лид закрыт, причина сохранена');
}

function dealEditorStepCopy(step) {
    return {
        1: 'Шаг 1 из 5 · укажите текущий этап и ближайшее действие менеджера.',
        2: 'Шаг 2 из 5 · проверьте данные клиента и контактного лица.',
        3: 'Шаг 3 из 5 · укажите, какие товары или услуги входят в сделку.',
        4: 'Шаг 4 из 5 · заполните сумму, вероятность и плановые сроки.',
        5: 'Шаг 5 из 5 · выберите документы, укажите итог и сохраните сделку.',
    }[Number(step || 1)];
}

function switchDealEditorStep(step, validateCurrent = true) {
    const targetStep = Math.max(1, Math.min(5, Number(step || 1)));
    if (validateCurrent && targetStep > editingDealStep && !validateDealEditorStep(editingDealStep)) return;
    editingDealStep = targetStep;
    document.querySelectorAll('[data-deal-editor-step]').forEach(section => section.classList.toggle('is-active', Number(section.dataset.dealEditorStep) === targetStep));
    document.querySelectorAll('[data-deal-editor-step-button]').forEach(button => {
        const buttonStep = Number(button.dataset.dealEditorStepButton || 0);
        button.classList.toggle('is-active', buttonStep === targetStep);
        button.classList.toggle('is-complete', buttonStep < targetStep);
    });
    const note = document.getElementById('dealEditorStageNote');
    if (note) note.textContent = dealEditorStepCopy(targetStep);
    const current = document.getElementById('dealEditorStepCurrent');
    if (current) current.textContent = String(targetStep);
    const back = document.getElementById('dealEditorBackBtn');
    const next = document.getElementById('dealEditorNextBtn');
    const save = document.getElementById('dealEditorSaveBtn');
    const won = document.getElementById('dealEditorWonBtn');
    const lost = document.getElementById('dealEditorLostBtn');
    if (back) back.hidden = targetStep <= 1;
    if (next) next.hidden = targetStep >= 5;
    if (save) save.hidden = targetStep !== 5;
    if (won) won.hidden = targetStep !== 5;
    if (lost) lost.hidden = targetStep !== 5;
}

function validateDealEditorStep(step) {
    const value = id => String(document.getElementById(id)?.value || '').trim();
    if (Number(step) === 1) {
        if (!value('dealFormClient')) { customAlert('Укажите клиента или компанию.'); return false; }
        const stage = value('dealFormStage');
        if (!['won', 'lost'].includes(stage) && !value('dealFormNextAction')) { customAlert('Укажите следующий шаг по сделке.'); return false; }
    }
    return true;
}

function dealEditorNextStep() {
    if (!validateDealEditorStep(editingDealStep)) return;
    switchDealEditorStep(editingDealStep + 1, false);
}

function dealEditorPreviousStep() {
    switchDealEditorStep(editingDealStep - 1, false);
}

function updateDealEditorStageFields() {
    const stage = String(document.getElementById('dealFormStage')?.value || 'qualification');
    const actualCloseInput = document.getElementById('dealFormActualCloseDate');
    if (actualCloseInput && ['won', 'lost'].includes(stage) && !actualCloseInput.value) actualCloseInput.value = crmDateOffset(0);
    const nextAction = document.getElementById('dealFormNextAction');
    if (nextAction) nextAction.closest('label')?.classList.toggle('is-optional', ['won', 'lost'].includes(stage));
}

function closeDealEditor() {
    editingDealId = 0;
    editingDealStep = 1;
    const panel = document.getElementById('dealEditorPanel');
    if (panel) panel.style.display = 'none';
    const detail = document.querySelector('#dealsView .deal-card-workspace > .deal-detail-card');
    if (detail) detail.hidden = false;
}

function selectLeadRow(id) {
    currentLeadId = Number(id || 0);
    closeLeadEditor();
    renderLeads();
}

function selectDealRow(id) {
    currentDealId = Number(id || 0);
    const row = (crmDealsDB || []).find(item => Number(item.id || 0) === currentDealId);
    if (row && (Number(row.is_archived || 0) || ['won', 'lost'].includes(String(row.stage || '')))) {
        skipDealEditorAutoOpenOnce = true;
    }
    renderDeals();
}

function updateDealArchiveToggle() {
    const button = document.getElementById('dealArchiveToggle');
    if (!button) return;
    const archivedCount = (crmDealsDB || []).filter(row => Number(row.is_archived || 0) === 1).length;
    button.textContent = currentDealArchiveView ? 'Вернуться к сделкам' : `Архив${archivedCount ? ` (${archivedCount})` : ''}`;
    button.classList.toggle('active', currentDealArchiveView);
}

function toggleDealArchiveView() {
    currentDealArchiveView = !currentDealArchiveView;
    currentDealId = 0;
    editingDealId = 0;
    skipDealEditorAutoOpenOnce = true;
    renderDeals();
}

async function archiveDeal(dealId) {
    const row = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!row) return customAlert('Сделка не найдена.');
    if (!crmCanManageDeal(row)) return customAlert('Эта сделка доступна только для просмотра.');
    if (!['won', 'lost'].includes(String(row.stage || ''))) return customAlert('Сначала завершите сделку или укажите отказ клиента.');
    const confirmed = await customConfirm(`Отправить сделку «${row.title || row.client_name || dealId}» в архив?`);
    if (!confirmed) return;
    const res = await apiCall(`/crm/deals/${Number(dealId || 0)}/archive`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось отправить сделку в архив.');
    await loadCrmDeals();
    currentDealId = 0;
    skipDealEditorAutoOpenOnce = true;
    renderDeals();
    showToast('Сделки', 'Сделка отправлена в архив');
}

async function restoreDealFromArchive(dealId) {
    const row = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!row || !crmCanManageDeal(row)) return customAlert('Эта сделка доступна только для просмотра.');
    const res = await apiCall(`/crm/deals/${Number(dealId || 0)}/restore`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось вернуть сделку из архива.');
    await loadCrmDeals();
    currentDealId = Number(dealId || 0);
    currentDealArchiveView = false;
    skipDealEditorAutoOpenOnce = true;
    renderDeals();
    showToast('Сделки', 'Сделка возвращена из архива');
}

async function saveLead() {
    const payload = {
        title: document.getElementById('leadFormTitle')?.value || '',
        client_name: document.getElementById('leadFormClient')?.value || '',
        contact_name: document.getElementById('leadFormContact')?.value || '',
        contact_email: document.getElementById('leadFormEmail')?.value || '',
        contact_phone: document.getElementById('leadFormPhone')?.value || '',
        source: document.getElementById('leadFormSource')?.value || '',
        stage: document.getElementById('leadFormStage')?.value || 'new',
        responsible: document.getElementById('leadFormResponsible')?.value || '',
        next_action: document.getElementById('leadFormNextAction')?.value || '',
        next_action_date: document.getElementById('leadFormNextActionDate')?.value || '',
        budget: Number(document.getElementById('leadFormBudget')?.value || 0),
        probability: Number(document.getElementById('leadFormProbability')?.value || 0),
        tags: String(document.getElementById('leadFormTags')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        comment: document.getElementById('leadFormComment')?.value || '',
        currency: 'RUB',
        priority: 'normal',
    };
    if (!payload.title.trim()) return customAlert('Укажите название лида.');
    if (!payload.client_name.trim()) return customAlert('Укажите компанию клиента.');
    if (!payload.contact_phone.trim() && !payload.contact_email.trim()) return customAlert('Укажите телефон или почту клиента.');
    if (!payload.comment.trim()) return customAlert('Опишите потребность клиента и основные договорённости.');
    if (!['won', 'lost'].includes(payload.stage) && !payload.next_action.trim()) return customAlert('Укажите конкретный следующий шаг по лиду.');
    if (!['won', 'lost'].includes(payload.stage) && !payload.next_action_date.trim()) return customAlert('Выберите дату следующего действия.');
    const endpoint = editingLeadId ? `/crm/leads/${editingLeadId}` : '/crm/leads';
    const method = editingLeadId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить лид.');
    await loadCrmLeads();
    currentLeadId = Number(res.id || editingLeadId || currentLeadId);
    closeLeadEditor();
    renderLeads();
    showToast('Лиды', 'Лид сохранён');
}

async function applyLeadRouting(leadId, managerName = '') {
    const row = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!row) return customAlert('Лид не найден.');
    const info = crmLeadScore(row);
    const responsible = String(managerName || info.route.manager || row.responsible || currentUser?.name || '').trim();
    if (!responsible) return customAlert('Система не уверена в назначении. Выбери менеджера вручную.');
    const historyLine = `[Маршрутизация ${new Date().toLocaleString('ru-RU')}] ${currentUser?.name || 'Система'} -> ${responsible}; правило: ${info.route.label}; уверенность ${info.route.confidence || 0}%; скоринг ${info.score}; сигналы: ${(info.route.signalLabels || []).join(', ') || 'нет'}.`;
    const payload = {
        title: row.title || '',
        client_name: row.client_name || '',
        contact_name: row.contact_name || '',
        contact_email: row.contact_email || '',
        contact_phone: row.contact_phone || '',
        source: row.source || '',
        stage: row.stage || 'new',
        responsible,
        next_action: row.next_action || (info.firstTouchSlaViolated ? 'Срочно сделать первое касание' : 'Первое касание и квалификация'),
        next_action_date: row.next_action_date || '',
        budget: Number(row.budget || 0),
        probability: Number(row.probability || 0),
        tags: Array.isArray(row.tags) ? row.tags : [],
        comment: [row.comment || '', historyLine].filter(Boolean).join('\n'),
        currency: row.currency || 'RUB',
        priority: info.score >= 76 || info.firstTouchSlaViolated ? 'high' : (row.priority || 'normal'),
        linked_client_id: Number(row.linked_client_id || 0),
        linked_project_id: Number(row.linked_project_id || 0),
        linked_deal_id: Number(row.linked_deal_id || 0),
    };
    const res = await apiCall(`/crm/leads/${Number(leadId || 0)}`, 'PUT', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось закрепить лид.');
    await loadCrmLeads();
    currentLeadId = Number(leadId || currentLeadId);
    renderLeads();
    showToast('Лиды', `Лид закреплён: ${responsible}`);
}

async function manualReassignLead(leadId) {
    const row = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!row) return customAlert('Лид не найден.');
    const current = row.responsible || crmLeadScore(row).route.manager || currentUser?.name || '';
    const manager = await customPrompt('Кому вручную закрепить лида?', current);
    if (manager === null) return;
    await applyLeadRouting(leadId, String(manager || '').trim());
}

function toggleLeadTransferPanel(leadId, forceOpen = null) {
    const panel = document.getElementById(`leadTransferPanel-${Number(leadId || 0)}`);
    if (!panel) return;
    const shouldOpen = forceOpen === null ? panel.style.display === 'none' : Boolean(forceOpen);
    panel.style.display = shouldOpen ? 'grid' : 'none';
}

async function transferLeadToManager(leadId) {
    const select = document.getElementById(`leadTransferManager-${Number(leadId || 0)}`);
    const managerEmail = String(select?.value || '').trim();
    if (!managerEmail) return customAlert('Выберите сотрудника, которому нужно передать лид.');
    const managerName = select?.selectedOptions?.[0]?.textContent?.trim() || 'другому сотруднику';
    if (!(await customConfirm(`Передать лид сотруднику «${managerName}»? После передачи он исчезнет из вашего списка.`))) return;
    const res = await apiCall(`/crm/leads/${Number(leadId || 0)}/transfer`, 'POST', { manager_email: managerEmail });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось передать лид.');
    currentLeadId = 0;
    await loadCrmLeads();
    renderLeads();
    showToast('Лиды', `Лид передан: ${res.manager_name || managerName}`);
}

async function markLeadProposalSent(leadId) {
    const row = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!row) return customAlert('Лид не найден.');
    if (!(await customConfirm('Отметить, что коммерческое предложение уже отправлено? Лид перейдёт в этап «Готовится предложение», а следующим шагом станет получение обратной связи.'))) return;
    const today = crmDateOffset(0);
    const followUpDate = crmDateOffset(3);
    const result = await apiCall(`/crm/leads/${Number(leadId || 0)}`, 'PUT', {
        title: row.title || '',
        client_name: row.client_name || '',
        contact_name: row.contact_name || '',
        contact_email: row.contact_email || '',
        contact_phone: row.contact_phone || '',
        source: row.source || '',
        stage: 'proposal',
        probability: Number(row.probability || 0),
        budget: Number(row.budget || 0),
        currency: row.currency || 'RUB',
        responsible: row.responsible || '',
        next_action: 'Получить обратную связь по КП',
        next_action_date: followUpDate,
        priority: row.priority || 'normal',
        tags: Array.isArray(row.tags) ? row.tags : [],
        comment: [row.comment || '', `[КП ${today}] Коммерческое предложение отправлено.`].filter(Boolean).join('\n'),
        linked_client_id: Number(row.linked_client_id || 0),
        linked_project_id: Number(row.linked_project_id || 0),
        linked_deal_id: Number(row.linked_deal_id || 0),
    });
    if (!result || result.error) return customAlert(result?.message || 'Не удалось обновить лид.');
    const activity = await apiCall('/crm/activities', 'POST', {
        entity_type: 'lead',
        entity_id: Number(leadId || 0),
        activity_type: 'email',
        subject: 'Коммерческое предложение отправлено',
        summary: 'Зафиксирована отправка КП. Следующее действие: получить обратную связь.',
        due_date: today,
        owner_name: currentUser?.name || '',
        status: 'done',
    });
    if (!activity || activity.error) return customAlert(activity?.message || 'Этап обновлён, но не удалось записать действие.');
    currentLeadId = Number(leadId || 0);
    await loadCrmLeads();
    renderLeads();
    showToast('Лиды', 'КП отмечено как отправленное');
}

async function autoAssignQualifiedLeads() {
    const settings = crmLeadRoutingSettings();
    const minConfidence = Number(settings.minConfidence || CRM_LEAD_ROUTING_DEFAULTS.minConfidence);
    const candidates = (crmLeadsDB || [])
        .map(row => ({ row, info: crmLeadScore(row) }))
        .filter(item => !String(item.row.responsible || '').trim() && item.info.route.manager && Number(item.info.route.confidence || 0) >= minConfidence);
    if (!candidates.length) return customAlert('Нет уверенных нераспределённых лидов для автоназначения.');
    if (!(await customConfirm(`Автоматически закрепить лиды: ${candidates.length}?`))) return;
    let done = 0;
    for (const item of candidates) {
        await applyLeadRouting(Number(item.row.id || 0), item.info.route.manager);
        done += 1;
    }
    showToast('Лиды', `Автоназначено лидов: ${done}`);
}

function exportLeadRoutingDirectorReport() {
    const rows = (leadRowsFiltered() || []).map(row => {
        const info = crmLeadScore(row);
        return {
            'Заявка': row.title || '',
            'Клиент': row.client_name || '',
            'Бюджет': Number(row.budget || 0),
            'Скоринг': info.score,
            'ABC': info.abc,
            'Температура': info.temperature,
            'Ответственный сейчас': row.responsible || '',
            'Правило': info.route.label,
            'Кому назначить': info.route.manager || 'не распределено',
            'Уверенность маршрута': `${info.route.confidence || 0}%`,
            'Отрасль': (info.signals.industries || []).map(item => item.label).join(', '),
            'Оборудование': (info.signals.equipment || []).map(item => item.label).join(', '),
            'Регион': (info.signals.regions || []).map(item => `${item.label} ${item.timezone}`).join(', '),
            'SLA': info.firstTouchSlaViolated ? `нарушено ${info.ageHours}ч` : 'в норме',
            'Флаги': info.flags.join(', '),
        };
    });
    if (!rows.length) return customAlert('Нет лидов для отчёта.');
    const header = Object.keys(rows[0]);
    const csv = [header.join(';')]
        .concat(rows.map(row => header.map(key => `"${String(row[key] ?? '').replace(/"/g, '""')}"`).join(';')))
        .join('\n');
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `korda-lead-routing-director-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    showToast('Лиды', 'Директорский отчёт по маршрутизации выгружен');
}

function saveLeadRoutingSettings() {
    const settings = {
        budgetThreshold: Number(document.getElementById('leadRouteBudgetThreshold')?.value || CRM_LEAD_ROUTING_DEFAULTS.budgetThreshold),
        seniorManager: document.getElementById('leadRouteSeniorManager')?.value || CRM_LEAD_ROUTING_DEFAULTS.seniorManager,
        tenderManager: document.getElementById('leadRouteTenderManager')?.value || CRM_LEAD_ROUTING_DEFAULTS.tenderManager,
        industryManager: document.getElementById('leadRouteIndustryManager')?.value || CRM_LEAD_ROUTING_DEFAULTS.industryManager,
        equipmentManager: document.getElementById('leadRouteEquipmentManager')?.value || CRM_LEAD_ROUTING_DEFAULTS.equipmentManager,
        regionManager: document.getElementById('leadRouteRegionManager')?.value || CRM_LEAD_ROUTING_DEFAULTS.regionManager,
        defaultManager: document.getElementById('leadRouteDefaultManager')?.value || CRM_LEAD_ROUTING_DEFAULTS.defaultManager,
        minConfidence: Number(document.getElementById('leadRouteMinConfidence')?.value || CRM_LEAD_ROUTING_DEFAULTS.minConfidence),
    };
    localStorage.setItem(CRM_LEAD_ROUTING_SETTINGS_KEY, JSON.stringify(settings));
    renderLeads();
    showToast('Лиды', 'Правила распределения сохранены');
}

function resetLeadRoutingSettings() {
    localStorage.removeItem(CRM_LEAD_ROUTING_SETTINGS_KEY);
    renderLeads();
    showToast('Лиды', 'Правила распределения сброшены');
}

async function createLeadDemoScenario() {
    const marker = '[KORDA DEMO]';
    const existing = (crmLeadsDB || []).filter(row => String(row.title || '').includes(marker)).length;
    if (existing) {
        const confirmed = await customConfirm(`Демо-лиды уже есть: ${existing}. Создать ещё один набор для показа?`);
        if (!confirmed) {
            currentLeadSearch = marker;
            renderLeads();
            return;
        }
    }
    const demoRows = [
        {
            title: `${marker} Крупный бюджет: компрессорная станция`,
            client_name: 'ГазПромСервис Урал',
            contact_name: 'Андрей Николаев',
            contact_email: 'nikolaev.demo@example.com',
            contact_phone: '+7 343 777-00-21',
            source: 'Bitrix24 / входящая заявка',
            stage: 'new',
            responsible: '',
            next_action: 'Первый звонок и квалификация бюджета',
            next_action_date: crmDateOffset(0),
            budget: 6500000,
            probability: 55,
            tags: ['demo', 'крупный бюджет', 'компрессоры'],
            comment: 'Показывает правило: бюджет выше порога -> старший менеджер.',
            priority: 'high',
        },
        {
            title: `${marker} Тендер: шумозащитные кожухи`,
            client_name: 'Тендерная площадка / СеверМаш',
            contact_name: 'Елена Захарова',
            contact_email: 'tender.demo@example.com',
            contact_phone: '+7 921 100-55-22',
            source: 'Тендерная площадка 223-ФЗ',
            stage: 'new',
            responsible: '',
            next_action: 'Проверить сроки подачи и пакет документов',
            next_action_date: crmDateOffset(1),
            budget: 2400000,
            probability: 45,
            tags: ['demo', 'тендер'],
            comment: 'Показывает правило: тендер -> тендерный менеджер и пакет документов.',
            priority: 'high',
        },
        {
            title: `${marker} Регион: Казань, энергетика`,
            client_name: 'Казанская ТЭЦ',
            contact_name: 'Ирина Петрова',
            contact_email: 'petrova.demo@example.com',
            contact_phone: '+7 927 333-78-90',
            source: 'Квиз-сайт',
            stage: 'qualified',
            responsible: '',
            next_action: 'Уточнить региональную логистику',
            next_action_date: crmDateOffset(2),
            budget: 980000,
            probability: 60,
            tags: ['demo', 'регион', 'энергетика'],
            comment: 'Показывает правило: региональная заявка -> региональный менеджер.',
            priority: 'normal',
        },
        {
            title: `${marker} Без ответственного и контактов`,
            client_name: 'Необработанная компания',
            contact_name: '',
            contact_email: '',
            contact_phone: '',
            source: 'Импорт из старой базы',
            stage: 'new',
            responsible: '',
            next_action: '',
            next_action_date: '',
            budget: 320000,
            probability: 20,
            tags: ['demo', 'проблемная база'],
            comment: 'Показывает флаги: нет контактов, не закреплён, нет следующего шага.',
            priority: 'normal',
        },
        {
            title: `${marker} SLA просрочен: первый контакт не сделан`,
            client_name: 'ПромШум / пилотный объект',
            contact_name: 'Сергей Белов',
            contact_email: 'belov.demo@example.com',
            contact_phone: '+7 911 200-44-11',
            source: 'Сайт',
            stage: 'new',
            responsible: '',
            next_action: 'Первый контакт должен был быть вчера',
            next_action_date: crmDateOffset(-1),
            budget: 760000,
            probability: 35,
            tags: ['demo', 'sla'],
            comment: 'Показывает нарушение SLA первого касания.',
            priority: 'high',
        },
        {
            title: `${marker} Отрасль: промышленные кабины КШЗ`,
            client_name: 'АрктикМаш производство',
            contact_name: 'Ольга Соколова',
            contact_email: 'sokolova.demo@example.com',
            contact_phone: '+7 921 100-55-22',
            source: 'Выставка / промышленное строительство',
            stage: 'qualified',
            responsible: '',
            next_action: 'Подготовить подбор оборудования',
            next_action_date: crmDateOffset(1),
            budget: 1800000,
            probability: 65,
            tags: ['demo', 'КШЗ', 'производство'],
            comment: 'Показывает правило: промышленное направление -> отраслевой менеджер.',
            priority: 'normal',
        },
        {
            title: `${marker} Типовая заявка с высокой вероятностью`,
            client_name: 'ТурбоКит',
            contact_name: 'Павел Сурков',
            contact_email: 'surkov.demo@example.com',
            contact_phone: '+7 831 500-11-77',
            source: 'Повторное обращение',
            stage: 'proposal',
            responsible: currentUser?.name || 'Менеджер входящего потока',
            next_action: 'Отправить КП и зафиксировать следующий шаг',
            next_action_date: crmDateOffset(0),
            budget: 540000,
            probability: 78,
            tags: ['demo', 'типовая заявка'],
            comment: 'Показывает тёплый лид без критичных флагов.',
            priority: 'normal',
        },
    ];
    for (const row of demoRows) {
        const payload = { ...row, currency: 'RUB', linked_client_id: 0, linked_project_id: 0, linked_deal_id: 0 };
        const created = await apiCall('/crm/leads', 'POST', payload);
        if (!created || created.error) return customAlert(created?.message || 'Не удалось создать демо-лиды.');
        if (!row.responsible && created.id) {
            await apiCall(`/crm/leads/${Number(created.id || 0)}`, 'PUT', payload);
        }
    }
    await loadCrmLeads();
    currentLeadSearch = marker;
    currentLeadStage = '';
    currentLeadResponsible = '';
    currentLeadViewMode = 'registry';
    renderLeads();
    showToast('Лиды', `Демо-сценарий создан: ${demoRows.length} лидов`);
}

async function saveDeal(closeStage = '') {
    for (const step of [1, 3, 4, 5]) {
        if (!validateDealEditorStep(step)) {
            switchDealEditorStep(step, false);
            return;
        }
    }
    let closeReason = String(document.getElementById('dealFormLossReason')?.value || '').trim();
    if (['won', 'lost'].includes(String(closeStage || ''))) {
        const promptText = closeStage === 'won' ? 'Почему сделка успешно завершена?' : 'Почему клиент отказался от сделки?';
        const reason = await customPrompt(promptText, closeReason);
        if (reason === null) return;
        closeReason = String(reason || '').trim();
        if (!closeReason) return customAlert(closeStage === 'won' ? 'Укажите причину успешного завершения сделки.' : 'Укажите причину отказа клиента.');
    }
    const products = String(document.getElementById('dealFormProducts')?.value || '').split(/\r?\n/).map(line => {
        const [name, quantityRaw, unitPriceRaw] = line.split('|').map(value => String(value || '').trim());
        const quantity = Number(quantityRaw || 1);
        const unitPrice = Number(unitPriceRaw || 0);
        return { name, quantity: Number.isFinite(quantity) && quantity > 0 ? quantity : 1, unit_price: Number.isFinite(unitPrice) && unitPrice >= 0 ? unitPrice : 0 };
    }).filter(item => item.name);
    const clientName = String(document.getElementById('dealFormClient')?.value || '').trim();
    const selectedDocumentIds = new Set(Array.from(document.querySelectorAll('input[name="dealFormDocumentIds"]:checked')).map(input => Number(input.value || 0)).filter(Boolean));
    const previousDocumentIds = new Set(((crmDealsDB || []).find(item => Number(item.id || 0) === Number(editingDealId || 0))?.documents || []).map(item => Number(item.id || 0)));
    const payload = {
        title: clientName,
        client_name: clientName,
        contact_name: document.getElementById('dealFormContactName')?.value || '',
        contact_position: document.getElementById('dealFormContactPosition')?.value || '',
        contact_phone: document.getElementById('dealFormContactPhone')?.value || '',
        contact_email: document.getElementById('dealFormContactEmail')?.value || '',
        source: document.getElementById('dealFormSource')?.value || '',
        contract_number: document.getElementById('dealFormContract')?.value || '',
        stage: closeStage || document.getElementById('dealFormStage')?.value || 'qualification',
        responsible: document.getElementById('dealFormResponsible')?.value || '',
        next_action: document.getElementById('dealFormNextAction')?.value || '',
        next_action_date: document.getElementById('dealFormNextActionDate')?.value || '',
        expected_close_date: document.getElementById('dealFormExpectedCloseDate')?.value || '',
        actual_close_date: document.getElementById('dealFormActualCloseDate')?.value || '',
        amount: Number(document.getElementById('dealFormAmount')?.value || 0),
        margin_percent: Number(document.getElementById('dealFormMargin')?.value || 0),
        probability: Math.max(0, Math.min(100, Number(document.getElementById('dealFormProbability')?.value || 0))),
        tags: String(document.getElementById('dealFormTags')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        comment: document.getElementById('dealFormComment')?.value || '',
        loss_reason: closeReason,
        co_executors: document.getElementById('dealFormCoExecutors')?.value || '',
        products,
        currency: 'RUB',
        priority: 'normal',
        status_color: '',
    };
    if (!payload.client_name.trim()) return customAlert('Укажите клиента или компанию.');
    if (!['won', 'lost'].includes(payload.stage) && !payload.next_action.trim()) return customAlert('Укажите конкретный следующий шаг по сделке.');
    if (['won', 'lost'].includes(payload.stage) && !payload.loss_reason.trim()) return customAlert(payload.stage === 'won' ? 'Укажите причину успешного завершения сделки.' : 'Укажите причину отказа клиента.');
    if (['won', 'lost'].includes(payload.stage)) {
        payload.actual_close_date = payload.actual_close_date || crmDateOffset(0);
        payload.next_action = '';
        payload.next_action_date = '';
    }
    const endpoint = editingDealId ? `/crm/deals/${editingDealId}` : '/crm/deals';
    const method = editingDealId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить сделку.');
    const savedDealId = Number(res.id || editingDealId || currentDealId);
    const documentErrors = [];
    for (const documentId of selectedDocumentIds) {
        if (previousDocumentIds.has(documentId)) continue;
        const attachRes = await apiCall(`/crm/deals/${savedDealId}/documents/${documentId}`, 'POST');
        if (!attachRes || attachRes.error) documentErrors.push(documentId);
    }
    for (const documentId of previousDocumentIds) {
        if (selectedDocumentIds.has(documentId)) continue;
        const detachRes = await apiCall(`/crm/deals/${savedDealId}/documents/${documentId}`, 'DELETE');
        if (!detachRes || detachRes.error) documentErrors.push(documentId);
    }
    await Promise.all([loadCrmDeals(), loadDocuments()]);
    currentDealId = savedDealId;
    closeDealEditor();
    skipDealEditorAutoOpenOnce = true;
    renderDeals();
    if (documentErrors.length) return customAlert('Данные сделки сохранены, но часть документов не удалось прикрепить. Проверьте права доступа к Канцелярии.');
    showToast('Сделки', ['won', 'lost'].includes(payload.stage) ? 'Сделка закрыта, итог сохранён' : 'Сделка и документы сохранены');
}

async function setDealStageQuick(dealId, stage) {
    const row = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!row || String(row.stage || '') === String(stage || '')) return;
    if (!crmCanManageDeal(row)) return customAlert('Эта сделка доступна только для просмотра.');
    const overrides = { stage };
    if (stage === 'lost') {
        const reason = await customPrompt('Почему клиент отказался от сделки?', row.loss_reason || '');
        if (reason === null) return;
        if (!String(reason || '').trim()) return customAlert('Укажите причину отказа клиента.');
        overrides.loss_reason = String(reason).trim();
        overrides.actual_close_date = crmDateOffset(0);
        overrides.next_action = '';
        overrides.next_action_date = '';
    } else if (stage === 'won') {
        const reason = await customPrompt('Почему сделка успешно завершена?', row.loss_reason || '');
        if (reason === null) return;
        if (!String(reason || '').trim()) return customAlert('Укажите причину успешного завершения сделки.');
        overrides.actual_close_date = row.actual_close_date || crmDateOffset(0);
        overrides.loss_reason = String(reason).trim();
        overrides.next_action = '';
        overrides.next_action_date = '';
    } else {
        overrides.actual_close_date = '';
        overrides.loss_reason = '';
    }
    const res = await apiCall(`/crm/deals/${Number(dealId || 0)}`, 'PUT', crmDealPayloadFromRow(row, overrides));
    if (!res || res.error) return customAlert(res?.message || 'Не удалось изменить этап сделки.');
    await loadCrmDeals();
    currentDealId = Number(dealId || 0);
    renderDeals();
}

function startDealDocumentDrag(event, documentId) {
    event.dataTransfer.setData('text/plain', String(Number(documentId || 0)));
    event.dataTransfer.effectAllowed = 'move';
}

function allowDealDocumentDrop(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    event.currentTarget?.classList.add('is-dragover');
}

async function attachDocumentToDeal(dealId, documentId) {
    const row = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!row || !crmCanManageDeal(row)) return customAlert('Эта сделка доступна только для просмотра.');
    if (!Number(documentId || 0)) return customAlert('Выберите документ из общего архива.');
    const res = await apiCall(`/crm/deals/${Number(dealId || 0)}/documents/${Number(documentId || 0)}`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось прикрепить документ.');
    await Promise.all([loadCrmDeals(), loadDocuments()]);
    currentDealId = Number(dealId || 0);
    renderDeals();
    showToast('Сделки', 'Документ прикреплён к сделке');
}

async function dropDocumentOnDeal(event, dealId) {
    event.preventDefault();
    event.currentTarget?.classList.remove('is-dragover');
    await attachDocumentToDeal(dealId, Number(event.dataTransfer.getData('text/plain') || 0));
}

async function attachSelectedDocumentToDeal(dealId) {
    const documentId = Number(document.getElementById(`dealDocumentSelect-${Number(dealId || 0)}`)?.value || 0);
    await attachDocumentToDeal(dealId, documentId);
}

async function detachDocumentFromDeal(dealId, documentId) {
    const row = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!row || !crmCanManageDeal(row)) return customAlert('Эта сделка доступна только для просмотра.');
    if (!(await customConfirm('Убрать связь документа со сделкой? Сам документ останется в общем архиве.'))) return;
    const res = await apiCall(`/crm/deals/${Number(dealId || 0)}/documents/${Number(documentId || 0)}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось убрать связь документа.');
    await Promise.all([loadCrmDeals(), loadDocuments()]);
    currentDealId = Number(dealId || 0);
    renderDeals();
}

async function createCrmActivity(entityType, entityId) {
    const prefix = entityType === 'lead' ? 'lead' : 'deal';
    const payload = {
        entity_type: entityType,
        entity_id: Number(entityId || 0),
        activity_type: document.getElementById(`${prefix}ActivityType`)?.value || 'note',
        subject: document.getElementById(`${prefix}ActivitySubject`)?.value || '',
        due_date: document.getElementById(`${prefix}ActivityDueDate`)?.value || '',
        summary: document.getElementById(`${prefix}ActivitySummary`)?.value || '',
        owner_name: currentUser?.name || '',
        status: 'open',
    };
    if (!payload.subject.trim()) return customAlert(entityType === 'lead' ? 'Укажите, что нужно сделать дальше.' : 'Укажите тему активности.');
    if (entityType === 'lead' && !payload.due_date.trim()) return customAlert('Выберите дату следующего действия.');
    if (entityType === 'lead' && !payload.summary.trim()) return customAlert('Запишите результат контакта.');
    const res = await apiCall('/crm/activities', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить активность.');
    if (entityType === 'lead') {
        const row = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(entityId || 0));
        if (row) {
            const update = await apiCall(`/crm/leads/${Number(entityId || 0)}`, 'PUT', crmLeadPayloadFromRow(row, {
                next_action: payload.subject,
                next_action_date: payload.due_date,
            }));
            if (!update || update.error) return customAlert(update?.message || 'Контакт сохранён, но следующий шаг лида не обновился.');
        }
        await loadCrmLeads();
        renderLeads();
        showToast('Лиды', 'Контакт и следующий шаг сохранены');
    } else {
        await loadCrmDeals();
        renderDeals();
    }
}

async function toggleCrmActivityStatus(activityId, entityType, entityId, status) {
    const res = await apiCall(`/crm/activities?entity_type=${encodeURIComponent(entityType)}&entity_id=${Number(entityId || 0)}`, 'GET');
    const activities = Array.isArray(res) ? res : [];
    const row = activities.find(item => Number(item.id) === Number(activityId));
    if (!row) return customAlert('Активность не найдена.');
    const updatePayload = {
        entity_type: row.entity_type,
        entity_id: Number(row.entity_id || 0),
        activity_type: row.activity_type,
        subject: row.subject,
        summary: row.summary,
        due_date: row.due_date,
        status,
        owner_name: row.owner_name,
    };
    const saveRes = await apiCall(`/crm/activities/${activityId}`, 'PUT', updatePayload);
    if (!saveRes || saveRes.error) return customAlert(saveRes?.message || 'Не удалось обновить активность.');
    if (entityType === 'lead') {
        currentLeadId = Number(entityId || currentLeadId);
        await loadCrmLeads();
        renderLeads();
    } else {
        currentDealId = Number(entityId || currentDealId);
        await loadCrmDeals();
        renderDeals();
    }
}

async function convertLeadToDeal(leadId) {
    const row = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!row) return customAlert('Лид не найден. Обновите страницу и попробуйте ещё раз.');
    if (!(await customConfirm(`Перевести лид «${row.title || row.client_name || leadId}» в сделку? Все заполненные данные клиента будут перенесены.`))) return;
    const res = await apiCall(`/crm/leads/${leadId}/convert`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось конвертировать лид.');
    await Promise.all([loadCrmLeads(), loadCrmDeals()]);
    currentDealId = Number(res.deal_id || 0);
    navigateTo('deals');
}

async function openLeadDeal(dealId) {
    const id = Number(dealId || 0);
    if (!id) return customAlert('Связанная сделка не найдена.');
    await loadCrmDeals();
    const deal = (crmDealsDB || []).find(item => Number(item.id || 0) === id);
    if (!deal) return customAlert('Связанная сделка больше недоступна или была удалена.');
    currentDealSearch = '';
    currentDealStage = '';
    currentDealResponsible = '';
    currentDealArchiveView = Number(deal.is_archived || 0) === 1;
    currentDealId = id;
    navigateTo('deals');
}

function setLeadViewMode(mode) {
    currentLeadViewMode = mode;
    renderLeads();
}

function setDealViewMode(mode) {
    currentDealViewMode = mode;
    renderDeals();
}

function applyLeadSearch(value) {
    currentLeadSearch = String(value || '').trim();
    renderLeads();
}

function applyDealSearch(value) {
    currentDealSearch = String(value || '').trim();
    renderDeals();
}

function setLeadStageFilter(value) {
    currentLeadStage = value || '';
    renderLeads();
}

function setDealStageFilter(value) {
    currentDealStage = value || '';
    renderDeals();
}

function setLeadResponsibleFilter(value) {
    currentLeadResponsible = value || '';
    renderLeads();
}

function setDealResponsibleFilter(value) {
    currentDealResponsible = value || '';
    renderDeals();
}

function setLeadSort(value) {
    currentLeadSort = value || 'due_asc';
    renderLeads();
}

function setDealSort(value) {
    currentDealSort = value || 'due_asc';
    renderDeals();
}

function saveLeadPreset() {
    const name = window.prompt('Название пресета для лидов');
    if (!name || !name.trim()) return;
    const presets = crmReadPresets('lead').filter(item => item.name !== name.trim());
    presets.push({
        name: name.trim(),
        search: currentLeadSearch,
        stage: currentLeadStage,
        responsible: currentLeadResponsible,
        sort: currentLeadSort,
    });
    presets.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    crmWritePresets('lead', presets);
    const presetSelect = document.getElementById('leadPresetSelect');
    if (presetSelect) presetSelect.value = name.trim();
    renderLeads();
}

function saveDealPreset() {
    const name = window.prompt('Название пресета для сделок');
    if (!name || !name.trim()) return;
    const presets = crmReadPresets('deal').filter(item => item.name !== name.trim());
    presets.push({
        name: name.trim(),
        search: currentDealSearch,
        stage: currentDealStage,
        responsible: currentDealResponsible,
        sort: currentDealSort,
    });
    presets.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    crmWritePresets('deal', presets);
    const presetSelect = document.getElementById('dealPresetSelect');
    if (presetSelect) presetSelect.value = name.trim();
    renderDeals();
}

function applyLeadPreset(name) {
    if (!name) {
        const presetSelect = document.getElementById('leadPresetSelect');
        if (presetSelect) presetSelect.value = '';
        return;
    }
    const preset = crmReadPresets('lead').find(item => item.name === name);
    if (!preset) return;
    currentLeadSearch = preset.search || '';
    currentLeadStage = preset.stage || '';
    currentLeadResponsible = preset.responsible || '';
    currentLeadSort = preset.sort || 'due_asc';
    renderLeads();
}

function applyDealPreset(name) {
    if (!name) {
        const presetSelect = document.getElementById('dealPresetSelect');
        if (presetSelect) presetSelect.value = '';
        return;
    }
    const preset = crmReadPresets('deal').find(item => item.name === name);
    if (!preset) return;
    currentDealSearch = preset.search || '';
    currentDealStage = preset.stage || '';
    currentDealResponsible = preset.responsible || '';
    currentDealSort = preset.sort || 'due_asc';
    renderDeals();
}

function resetLeadFilters() {
    currentLeadSearch = '';
    currentLeadStage = '';
    currentLeadResponsible = '';
    currentLeadSort = 'due_asc';
    const presetSelect = document.getElementById('leadPresetSelect');
    if (presetSelect) presetSelect.value = '';
    renderLeads();
}

function resetDealFilters() {
    currentDealSearch = '';
    currentDealStage = '';
    currentDealResponsible = '';
    currentDealSort = 'due_asc';
    const presetSelect = document.getElementById('dealPresetSelect');
    if (presetSelect) presetSelect.value = '';
    renderDeals();
}

async function renderLeads() {
    if (!Array.isArray(crmLeadsDB) || !crmLeadsDB.length) await loadCrmLeads();
    if (!Array.isArray(allUsersDB) || !allUsersDB.length) await loadAllUsers();
    fillResponsibleSelect('leadResponsibleFilter', crmLeadsDB, currentLeadResponsible);
    crmFillPresetSelect('leadPresetSelect', crmReadPresets('lead'));
    renderLeadSummary();
    const searchInput = document.getElementById('leadSearchInput');
    const stageFilter = document.getElementById('leadStageFilter');
    if (searchInput) searchInput.value = currentLeadSearch;
    if (stageFilter) stageFilter.value = currentLeadStage;
    const mount = document.getElementById('leadsContentMount');
    if (!mount) return;
    currentLeadViewMode = 'registry';
    mount.innerHTML = renderLeadRegistry();
}

async function renderDeals() {
    if (!Array.isArray(crmDealsDB) || !crmDealsDB.length) await loadCrmDeals();
    if (!Array.isArray(documentsDB) || !documentsDB.length) await loadDocuments();
    fillResponsibleSelect('dealResponsibleFilter', crmDealsDB, currentDealResponsible);
    crmFillPresetSelect('dealPresetSelect', crmReadPresets('deal'));
    const searchInput = document.getElementById('dealSearchInput');
    const stageFilter = document.getElementById('dealStageFilter');
    if (searchInput) searchInput.value = currentDealSearch;
    if (stageFilter) stageFilter.value = currentDealStage;
    updateDealArchiveToggle();
    const mount = document.getElementById('dealsContentMount');
    if (!mount) return;
    currentDealViewMode = 'registry';
    mount.innerHTML = renderDealRegistry();
    renderDealSummary();
    // Opening a row always shows the saved card. Editing starts only from the
    // explicit button below the card, for every role including the owner.
    skipDealEditorAutoOpenOnce = false;
}

window.renderLeads = renderLeads;
window.renderDeals = renderDeals;
window.refreshDealsFromServer = refreshDealsFromServer;
window.openLeadEditor = openLeadEditor;
window.openDealEditor = openDealEditor;
window.switchDealEditorStep = switchDealEditorStep;
window.dealEditorNextStep = dealEditorNextStep;
window.dealEditorPreviousStep = dealEditorPreviousStep;
window.updateDealEditorStageFields = updateDealEditorStageFields;
window.closeLeadEditor = closeLeadEditor;
window.toggleLeadActivityPanel = toggleLeadActivityPanel;
window.toggleLeadLossPanel = toggleLeadLossPanel;
window.closeLeadWithoutDeal = closeLeadWithoutDeal;
window.closeDealEditor = closeDealEditor;
window.selectLeadRow = selectLeadRow;
window.selectDealRow = selectDealRow;
window.toggleDealArchiveView = toggleDealArchiveView;
window.archiveDeal = archiveDeal;
window.restoreDealFromArchive = restoreDealFromArchive;
window.saveLead = saveLead;
window.saveDeal = saveDeal;
window.setDealStageQuick = setDealStageQuick;
window.startDealDocumentDrag = startDealDocumentDrag;
window.allowDealDocumentDrop = allowDealDocumentDrop;
window.dropDocumentOnDeal = dropDocumentOnDeal;
window.attachSelectedDocumentToDeal = attachSelectedDocumentToDeal;
window.detachDocumentFromDeal = detachDocumentFromDeal;
window.applyLeadRouting = applyLeadRouting;
window.toggleLeadTransferPanel = toggleLeadTransferPanel;
window.transferLeadToManager = transferLeadToManager;
window.markLeadProposalSent = markLeadProposalSent;
window.saveLeadRoutingSettings = saveLeadRoutingSettings;
window.resetLeadRoutingSettings = resetLeadRoutingSettings;
window.createLeadDemoScenario = createLeadDemoScenario;
window.createCrmActivity = createCrmActivity;
window.toggleCrmActivityStatus = toggleCrmActivityStatus;
window.convertLeadToDeal = convertLeadToDeal;
window.setLeadViewMode = setLeadViewMode;
window.setDealViewMode = setDealViewMode;
window.applyLeadSearch = applyLeadSearch;
window.applyDealSearch = applyDealSearch;
window.setLeadStageFilter = setLeadStageFilter;
window.setDealStageFilter = setDealStageFilter;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startDealSharedArchiveSync, { once: true });
} else {
    startDealSharedArchiveSync();
}
window.setLeadResponsibleFilter = setLeadResponsibleFilter;
window.setDealResponsibleFilter = setDealResponsibleFilter;
window.setLeadSort = setLeadSort;
window.setDealSort = setDealSort;
window.saveLeadPreset = saveLeadPreset;
window.saveDealPreset = saveDealPreset;
window.applyLeadPreset = applyLeadPreset;
window.applyDealPreset = applyDealPreset;
window.resetLeadFilters = resetLeadFilters;
window.resetDealFilters = resetDealFilters;
