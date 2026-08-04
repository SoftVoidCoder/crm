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
        qualified: 'Квалифицирован',
        proposal: 'КП / предложение',
        won: 'Конвертирован',
        lost: 'Потерян',
        qualification: 'Квалификация',
        negotiation: 'Переговоры',
    };
    return map[String(stage || '')] || (stage || 'Без стадии');
}

function crmPriorityLabel(priority) {
    return {
        low: 'Низкий',
        normal: 'Нормальный',
        high: 'Высокий',
    }[String(priority || '')] || 'Нормальный';
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
        if (currentDealStage && String(row.stage || '') !== currentDealStage) return false;
        if (currentDealResponsible && String(row.responsible || '') !== currentDealResponsible) return false;
        if (currentDealSearch) {
            const haystack = [row.title, row.client_name, row.contract_number, row.next_action].join(' ').toLowerCase();
            if (!haystack.includes(currentDealSearch.toLowerCase())) return false;
        }
        return true;
    }));
}

function renderLeadSummary() {
    const rows = leadRowsFiltered();
    const mount = document.getElementById('leadSummaryStrip');
    if (!mount) return;
    const hot = rows.filter(row => crmToneByDueDate(row.next_action_date) === 'critical' || String(row.priority || '') === 'high').length;
    const qualified = rows.filter(row => ['qualified', 'proposal'].includes(String(row.stage || ''))).length;
    const budget = rows.reduce((sum, row) => sum + Number(row.budget || 0), 0);
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Лиды в контуре</div><div class="crm-summary-value">${rows.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Тёплые лиды</div><div class="crm-summary-value">${qualified}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Нужен быстрый шаг</div><div class="crm-summary-value">${hot}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Потенциал</div><div class="crm-summary-value">${crmFormatMoney(budget)}</div></div>
    `;
}

function renderLeadRoutingPanel() {
    const mount = document.getElementById('leadRoutingPanel');
    if (!mount) return;
    const rows = leadRowsFiltered();
    const stats = crmLeadRoutingStats(rows);
    const settings = crmLeadRoutingSettings();
    const rules = crmLeadRoutingRules(settings);
    mount.innerHTML = `
        <section class="crm-intelligence-card">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Маршрутизация и скоринг лидов</h3>
                    <p class="section-subtitle">Автораспределение по отрасли, региону, бюджету, источнику и SLA первого касания.</p>
                </div>
                <div class="crm-toolbar__group">
                    <span class="crm-inline-pill crm-inline-pill--${stats.sla ? 'critical' : 'positive'}">SLA 24ч: ${stats.sla}</span>
                    <span class="crm-inline-pill crm-inline-pill--${stats.unrouted ? 'attention' : 'positive'}">Не закреплено: ${stats.unrouted}</span>
                    <button class="btn-secondary" onclick="autoAssignQualifiedLeads()">Автоназначить уверенные</button>
                    <button class="btn-secondary" onclick="exportLeadRoutingDirectorReport()">Отчёт директору</button>
                    <button class="btn-secondary" onclick="createLeadDemoScenario()">Подготовить демо</button>
                </div>
            </div>
            <div class="crm-intelligence-grid">
                <div class="crm-intelligence-metrics">
                    <div><span>Горячие</span><strong>${stats.hot}</strong></div>
                    <div><span>Стратегические</span><strong>${stats.strategic}</strong></div>
                    <div><span>Не распределено</span><strong>${stats.unrouted}</strong></div>
                    <div><span>SLA нарушено</span><strong>${stats.sla}</strong></div>
                    <div><span>Низкая уверенность</span><strong>${stats.lowConfidence}</strong></div>
                    <div><span>С категорией</span><strong>${stats.equipment}</strong></div>
                </div>
                <div class="crm-routing-rules">
                    <div class="crm-routing-settings">
                        <label><span>Порог крупной сделки</span><input id="leadRouteBudgetThreshold" class="auth-input" type="number" value="${crmEscape(settings.budgetThreshold)}"></label>
                        <label><span>Старший менеджер</span><input id="leadRouteSeniorManager" class="auth-input" type="text" value="${crmEscape(settings.seniorManager)}"></label>
                        <label><span>Тендеры</span><input id="leadRouteTenderManager" class="auth-input" type="text" value="${crmEscape(settings.tenderManager)}"></label>
                        <label><span>Отрасли</span><input id="leadRouteIndustryManager" class="auth-input" type="text" value="${crmEscape(settings.industryManager)}"></label>
                        <label><span>Оборудование</span><input id="leadRouteEquipmentManager" class="auth-input" type="text" value="${crmEscape(settings.equipmentManager)}"></label>
                        <label><span>Регион</span><input id="leadRouteRegionManager" class="auth-input" type="text" value="${crmEscape(settings.regionManager)}"></label>
                        <label><span>Типовые</span><input id="leadRouteDefaultManager" class="auth-input" type="text" value="${crmEscape(settings.defaultManager)}"></label>
                        <label><span>Мин. уверенность %</span><input id="leadRouteMinConfidence" class="auth-input" type="number" value="${crmEscape(settings.minConfidence)}"></label>
                        <div class="crm-routing-settings__actions">
                            <button class="btn-secondary" onclick="saveLeadRoutingSettings()">Сохранить правила</button>
                            <button class="btn-secondary" onclick="resetLeadRoutingSettings()">Сбросить</button>
                        </div>
                    </div>
                    ${rules.slice(0, 5).map(rule => `
                        <div class="crm-routing-rule">
                            <strong>${crmEscape(rule.label)}</strong>
                            <span>${crmEscape(rule.manager)} · ${crmEscape(rule.note)}</span>
                        </div>
                    `).join('')}
                </div>
                <div class="crm-routing-list">
                    ${stats.top.map(item => {
                        const row = item.row;
                        const info = item.info;
                        return `
                            <div class="crm-routing-item">
                                <div>
                                    <strong>${crmEscape(row.title || row.client_name || 'Лид')}</strong>
                                    <span>${crmEscape(info.route.label)} · ${info.route.confidence || 0}% · ${crmEscape(info.route.signalLabels?.join(', ') || 'сигналы не найдены')}</span>
                                    <span>ABC ${crmEscape(info.abc)} · ${crmEscape(info.temperature)} · ${info.flags.length ? crmEscape(info.flags.join(', ')) : 'без флагов'}</span>
                                </div>
                                <div class="crm-routing-item__actions">
                                    <span class="crm-inline-pill crm-inline-pill--${info.tone}">${info.score}</span>
                                    <button class="btn-secondary" onclick="applyLeadRouting(${Number(row.id || 0)}, '${crmEscape(info.route.manager)}')">Закрепить</button>
                                    <button class="btn-secondary" onclick="manualReassignLead(${Number(row.id || 0)})">Вручную</button>
                                </div>
                            </div>
                        `;
                    }).join('') || '<div class="empty-state">Лиды для маршрутизации не найдены.</div>'}
                </div>
            </div>
            <div class="crm-routing-note">
                <strong>Очередь нераспределённых:</strong>
                ${stats.queue.length ? stats.queue.map(item => `${crmEscape(item.row.title || item.row.client_name || 'Лид')} (${item.info.route.confidence || 0}%)`).join(' · ') : 'пусто'}
            </div>
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

function renderLeadDetail(row) {
    if (!row) {
        return `<div class="empty-state">Выбери лид из списка или открой создание нового.</div>`;
    }
    const leadInfo = crmLeadScore(row);
    const routingHistory = String(row.comment || '')
        .split('\n')
        .filter(line => line.includes('[Маршрутизация'))
        .slice(-5)
        .reverse();
    return `
        <div class="crm-detail-card">
            <div class="crm-detail-head">
                <div>
                    <div class="crm-detail-title">${crmEscape(row.title || 'Без названия')}</div>
                    <div class="crm-detail-meta">${crmEscape(row.client_name || 'Без клиента')} · ${crmEscape(row.contact_name || 'Без контакта')}</div>
                </div>
                <div class="crm-badge crm-badge--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</div>
            </div>
            <div class="crm-detail-grid">
                <div><span class="crm-detail-label">Источник</span><strong>${crmEscape(row.source || '—')}</strong></div>
                <div><span class="crm-detail-label">Ответственный</span><strong>${crmEscape(row.responsible || '—')}</strong></div>
                <div><span class="crm-detail-label">Потенциал</span><strong>${crmFormatMoney(row.budget, row.currency)}</strong></div>
                <div><span class="crm-detail-label">Вероятность</span><strong>${Math.round(Number(row.probability || 0))}%</strong></div>
                <div><span class="crm-detail-label">Следующий шаг</span><strong>${crmEscape(row.next_action || '—')}</strong></div>
                <div><span class="crm-detail-label">Дата шага</span><strong>${crmEscape(row.next_action_date || '—')}</strong></div>
            </div>
            <div class="crm-detail-actions">
                <button class="btn-secondary" onclick="openLeadEditor(${row.id})">Редактировать</button>
                <button class="btn-secondary" onclick="applyLeadRouting(${Number(row.id || 0)}, '${crmEscape(leadInfo.route.manager)}')">Закрепить по правилу</button>
                <button class="btn-secondary" onclick="manualReassignLead(${Number(row.id || 0)})">Переназначить</button>
                <button class="btn-secondary" onclick="convertLeadToDeal(${row.id})">Конвертировать в сделку</button>
            </div>
            <div class="crm-tags">${(row.tags || []).map(tag => `<span class="crm-tag">${crmEscape(tag)}</span>`).join('')}</div>
            <div class="crm-detail-note">${crmEscape(row.comment || 'Комментарий не заполнен.')}</div>
            <div class="crm-activity-block">
                <div class="section-header">
                    <div><h3 class="section-title">Скоринг и закрепление</h3><p class="section-subtitle">Почему лид важен, кому его вести и где риск первого касания.</p></div>
                    <span class="crm-inline-pill crm-inline-pill--${leadInfo.tone}">${leadInfo.score} · ${crmEscape(leadInfo.temperature)}</span>
                </div>
                <div class="crm-lead-score-grid">
                    <div><span>ABC</span><strong>${crmEscape(leadInfo.abc)}</strong></div>
                    <div><span>Правило</span><strong>${crmEscape(leadInfo.route.label)}</strong></div>
                    <div><span>Кому закрепить</span><strong>${crmEscape(row.responsible || leadInfo.route.manager)}</strong></div>
                    <div><span>SLA первого касания</span><strong>${leadInfo.firstTouchSlaViolated ? `нарушено · ${leadInfo.ageHours}ч` : 'в норме'}</strong></div>
                    <div><span>Уверенность</span><strong>${leadInfo.route.confidence || 0}%</strong></div>
                    <div><span>Регион / часовой пояс</span><strong>${crmEscape((leadInfo.signals.regions || []).map(item => `${item.label} ${item.timezone}`).join(', ') || 'не определён')}</strong></div>
                    <div><span>Оборудование</span><strong>${crmEscape((leadInfo.signals.equipment || []).map(item => item.label).join(', ') || 'не определено')}</strong></div>
                    <div><span>Отрасль</span><strong>${crmEscape((leadInfo.signals.industries || []).map(item => item.label).join(', ') || 'не определена')}</strong></div>
                </div>
                <div class="crm-routing-note">${crmEscape(leadInfo.route.note)} ${leadInfo.flags.length ? `Флаги: ${leadInfo.flags.join(', ')}.` : 'Критичных флагов нет.'}</div>
                <div class="crm-routing-note"><strong>История маршрутизации:</strong> ${routingHistory.length ? routingHistory.map(crmEscape).join(' / ') : 'пока нет записей.'}</div>
            </div>
            <div class="crm-activity-block">
                <div class="section-header"><div><h3 class="section-title">Активности</h3><p class="section-subtitle">Следующий шаг, звонки, письма и внутренние задачи.</p></div></div>
                <div class="crm-activity-form">
                    <select id="leadActivityType" class="auth-input">
                        <option value="call">Звонок</option>
                        <option value="email">Письмо</option>
                        <option value="meeting">Встреча</option>
                        <option value="task">Задача</option>
                        <option value="note">Заметка</option>
                    </select>
                    <input id="leadActivitySubject" class="auth-input" type="text" placeholder="Тема активности">
                    <input id="leadActivityDueDate" class="auth-input" type="text" placeholder="дд.мм.гггг">
                    <textarea id="leadActivitySummary" class="auth-input" rows="3" placeholder="Что нужно сделать"></textarea>
                    <button class="btn-primary" onclick="createCrmActivity('lead', ${row.id})">Добавить активность</button>
                </div>
                <div class="crm-activity-list">${renderCrmActivities('lead', row.id, row.activities || [])}</div>
            </div>
        </div>
    `;
}

function renderDealDetail(row) {
    if (!row) {
        return `<div class="empty-state">Выбери сделку из списка или открой создание новой.</div>`;
    }
    return `
        <div class="crm-detail-card">
            <div class="crm-detail-head">
                <div>
                    <div class="crm-detail-title">${crmEscape(row.title || 'Без названия')}</div>
                    <div class="crm-detail-meta">${crmEscape(row.client_name || 'Без клиента')} · ${crmEscape(row.contract_number || 'Без номера КП')}</div>
                </div>
                <div class="crm-badge crm-badge--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</div>
            </div>
            <div class="crm-detail-grid">
                <div><span class="crm-detail-label">Сумма</span><strong>${crmFormatMoney(row.amount, row.currency)}</strong></div>
                <div><span class="crm-detail-label">Маржа</span><strong>${Math.round(Number(row.margin_percent || 0))}%</strong></div>
                <div><span class="crm-detail-label">Вероятность</span><strong>${Math.round(Number(row.probability || 0))}%</strong></div>
                <div><span class="crm-detail-label">Ответственный</span><strong>${crmEscape(row.responsible || '—')}</strong></div>
                <div><span class="crm-detail-label">Следующий шаг</span><strong>${crmEscape(row.next_action || '—')}</strong></div>
                <div><span class="crm-detail-label">План закрытия</span><strong>${crmEscape(row.expected_close_date || '—')}</strong></div>
            </div>
            <div class="crm-detail-actions">
                <button class="btn-secondary" onclick="openDealEditor(${row.id})">Редактировать</button>
            </div>
            <div class="crm-tags">${(row.tags || []).map(tag => `<span class="crm-tag">${crmEscape(tag)}</span>`).join('')}</div>
            <div class="crm-detail-note">${crmEscape(row.comment || 'Комментарий не заполнен.')}</div>
            <div class="crm-activity-block">
                <div class="section-header"><div><h3 class="section-title">Активности</h3><p class="section-subtitle">Коммерческие шаги по текущей сделке.</p></div></div>
                <div class="crm-activity-form">
                    <select id="dealActivityType" class="auth-input">
                        <option value="call">Звонок</option>
                        <option value="email">Письмо</option>
                        <option value="meeting">Встреча</option>
                        <option value="task">Задача</option>
                        <option value="note">Заметка</option>
                    </select>
                    <input id="dealActivitySubject" class="auth-input" type="text" placeholder="Тема активности">
                    <input id="dealActivityDueDate" class="auth-input" type="text" placeholder="дд.мм.гггг">
                    <textarea id="dealActivitySummary" class="auth-input" rows="3" placeholder="Что нужно сделать"></textarea>
                    <button class="btn-primary" onclick="createCrmActivity('deal', ${row.id})">Добавить активность</button>
                </div>
                <div class="crm-activity-list">${renderCrmActivities('deal', row.id, row.activities || [])}</div>
            </div>
        </div>
    `;
}

function renderLeadRegistry() {
    const rows = leadRowsFiltered();
    if (!currentLeadId && rows.length) currentLeadId = Number(rows[0].id || 0);
    const selected = rows.find(row => Number(row.id) === Number(currentLeadId)) || null;
    return `
        <div class="crm-registry-layout">
            <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 320px;">
                        <col style="width: 150px;">
                        <col style="width: 220px;">
                        <col style="width: 290px;">
                        <col style="width: 140px;">
                        <col style="width: 150px;">
                        <col style="width: 180px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Лид</th>
                            <th>Источник</th>
                            <th>Ответственный</th>
                            <th>Следующее действие</th>
                            <th>Скоринг</th>
                            <th class="is-num">Потенциал</th>
                            <th>Стадия</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => {
                            const info = crmLeadScore(row);
                            return `
                            <tr class="${Number(row.id) === Number(currentLeadId) ? 'is-selected' : ''}" onclick="selectLeadRow(${row.id})">
                                <td class="crm-title-cell"><strong>${crmEscape(row.title || '—')}</strong><div class="table-subtext">${crmEscape(row.client_name || '—')}</div></td>
                                <td class="crm-meta-cell"><span class="crm-cell-single">${crmEscape(row.source || '—')}</span></td>
                                <td class="crm-meta-cell"><span class="crm-cell-single">${crmEscape(row.responsible || '—')}</span></td>
                                <td class="crm-action-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span><div class="table-subtext">${crmEscape(row.next_action || '—')}</div></td>
                                <td class="crm-stage-cell"><span class="crm-inline-pill crm-inline-pill--${info.tone}">${info.score} · ${crmEscape(info.abc)}</span><div class="table-subtext">${crmEscape(info.route.label)} · ${crmEscape(info.temperature)}</div></td>
                                <td class="is-num amount crm-amount-cell">${crmFormatMoney(row.budget, row.currency)}</td>
                                <td class="crm-stage-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</span></td>
                            </tr>
                        `; }).join('') || '<tr><td colspan="7"><div class="empty-state">Лиды по текущему фильтру не найдены.</div></td></tr>'}
                    </tbody>
                </table>
            </div>
            ${renderLeadDetail(selected)}
        </div>
    `;
}

function renderDealRegistry() {
    const rows = dealRowsFiltered();
    if (!currentDealId && rows.length) currentDealId = Number(rows[0].id || 0);
    const selected = rows.find(row => Number(row.id) === Number(currentDealId)) || null;
    return `
        <div class="crm-registry-layout">
            <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 360px;">
                        <col style="width: 240px;">
                        <col style="width: 320px;">
                        <col style="width: 170px;">
                        <col style="width: 120px;">
                        <col style="width: 180px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Сделка</th>
                            <th>Клиент</th>
                            <th>Следующее действие</th>
                            <th class="is-num">Сумма</th>
                            <th class="is-num">Маржа</th>
                            <th>Стадия</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr class="${Number(row.id) === Number(currentDealId) ? 'is-selected' : ''}" onclick="selectDealRow(${row.id})">
                                <td class="crm-title-cell"><strong>${crmEscape(row.title || '—')}</strong><div class="table-subtext">${crmEscape(row.contract_number || 'без номера')}</div></td>
                                <td class="crm-meta-cell"><span class="crm-cell-single">${crmEscape(row.client_name || '—')}</span></td>
                                <td class="crm-action-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(row.next_action_date || 'без даты')}</span><div class="table-subtext">${crmEscape(row.next_action || '—')}</div></td>
                                <td class="is-num amount crm-amount-cell">${crmFormatMoney(row.amount, row.currency)}</td>
                                <td class="is-num crm-amount-cell">${Math.round(Number(row.margin_percent || 0))}%</td>
                                <td class="crm-stage-cell"><span class="crm-inline-pill crm-inline-pill--${crmToneByDueDate(row.next_action_date)}">${crmEscape(crmStageLabel(row.stage))}</span></td>
                            </tr>
                        `).join('') || '<tr><td colspan="6"><div class="empty-state">Сделки по текущему фильтру не найдены.</div></td></tr>'}
                    </tbody>
                </table>
            </div>
            ${renderDealDetail(selected)}
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
    const row = (crmLeadsDB || []).find(item => Number(item.id) === editingLeadId) || { tags: [] };
    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="crm-editor-grid">
            <input id="leadFormTitle" class="auth-input" type="text" placeholder="Название лида" value="${crmEscape(row.title || '')}">
            <input id="leadFormClient" class="auth-input" type="text" placeholder="Компания" value="${crmEscape(row.client_name || '')}">
            <input id="leadFormContact" class="auth-input" type="text" placeholder="Контакт" value="${crmEscape(row.contact_name || '')}">
            <input id="leadFormEmail" class="auth-input" type="text" placeholder="Email" value="${crmEscape(row.contact_email || '')}">
            <input id="leadFormPhone" class="auth-input" type="text" placeholder="Телефон" value="${crmEscape(row.contact_phone || '')}">
            <input id="leadFormSource" class="auth-input" type="text" placeholder="Источник" value="${crmEscape(row.source || '')}">
            <select id="leadFormStage" class="auth-input">
                <option value="new" ${row.stage === 'new' ? 'selected' : ''}>Новый</option>
                <option value="qualified" ${row.stage === 'qualified' ? 'selected' : ''}>Квалифицирован</option>
                <option value="proposal" ${row.stage === 'proposal' ? 'selected' : ''}>КП / предложение</option>
                <option value="won" ${row.stage === 'won' ? 'selected' : ''}>Конвертирован</option>
                <option value="lost" ${row.stage === 'lost' ? 'selected' : ''}>Потерян</option>
            </select>
            <input id="leadFormResponsible" class="auth-input" type="text" placeholder="Ответственный" value="${crmEscape(row.responsible || currentUser?.name || '')}">
            <input id="leadFormNextAction" class="auth-input" type="text" placeholder="Следующее действие" value="${crmEscape(row.next_action || '')}">
            <input id="leadFormNextActionDate" class="auth-input" type="text" placeholder="дд.мм.гггг" value="${crmEscape(row.next_action_date || '')}">
            <input id="leadFormBudget" class="auth-input" type="number" placeholder="Потенциал" value="${crmEscape(row.budget || 0)}">
            <input id="leadFormProbability" class="auth-input" type="number" placeholder="Вероятность %" value="${crmEscape(row.probability || 0)}">
            <input id="leadFormTags" class="auth-input" type="text" placeholder="Теги через запятую" value="${crmEscape((row.tags || []).join(', '))}">
            <textarea id="leadFormComment" class="auth-input" rows="3" placeholder="Комментарий">${crmEscape(row.comment || '')}</textarea>
        </div>
        <div class="crm-editor-actions">
            <button class="btn-secondary" onclick="closeLeadEditor()">Скрыть</button>
            <button class="btn-primary" onclick="saveLead()">Сохранить</button>
        </div>
    `;
}

function openDealEditor(dealId = 0) {
    editingDealId = Number(dealId || 0);
    const panel = document.getElementById('dealEditorPanel');
    if (!panel) return;
    const row = (crmDealsDB || []).find(item => Number(item.id) === editingDealId) || { tags: [] };
    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="crm-editor-grid">
            <input id="dealFormTitle" class="auth-input" type="text" placeholder="Название сделки" value="${crmEscape(row.title || '')}">
            <input id="dealFormClient" class="auth-input" type="text" placeholder="Компания" value="${crmEscape(row.client_name || '')}">
            <input id="dealFormContract" class="auth-input" type="text" placeholder="Номер КП / договора" value="${crmEscape(row.contract_number || '')}">
            <select id="dealFormStage" class="auth-input">
                <option value="qualification" ${row.stage === 'qualification' ? 'selected' : ''}>Квалификация</option>
                <option value="proposal" ${row.stage === 'proposal' ? 'selected' : ''}>Предложение</option>
                <option value="negotiation" ${row.stage === 'negotiation' ? 'selected' : ''}>Переговоры</option>
                <option value="won" ${row.stage === 'won' ? 'selected' : ''}>Выиграно</option>
                <option value="lost" ${row.stage === 'lost' ? 'selected' : ''}>Потеряно</option>
            </select>
            <input id="dealFormResponsible" class="auth-input" type="text" placeholder="Ответственный" value="${crmEscape(row.responsible || currentUser?.name || '')}">
            <input id="dealFormNextAction" class="auth-input" type="text" placeholder="Следующее действие" value="${crmEscape(row.next_action || '')}">
            <input id="dealFormNextActionDate" class="auth-input" type="text" placeholder="дд.мм.гггг" value="${crmEscape(row.next_action_date || '')}">
            <input id="dealFormExpectedCloseDate" class="auth-input" type="text" placeholder="План закрытия" value="${crmEscape(row.expected_close_date || '')}">
            <input id="dealFormAmount" class="auth-input" type="number" placeholder="Сумма" value="${crmEscape(row.amount || 0)}">
            <input id="dealFormMargin" class="auth-input" type="number" placeholder="Маржа %" value="${crmEscape(row.margin_percent || 0)}">
            <input id="dealFormProbability" class="auth-input" type="number" placeholder="Вероятность %" value="${crmEscape(row.probability || 0)}">
            <input id="dealFormTags" class="auth-input" type="text" placeholder="Теги через запятую" value="${crmEscape((row.tags || []).join(', '))}">
            <textarea id="dealFormComment" class="auth-input" rows="3" placeholder="Комментарий">${crmEscape(row.comment || '')}</textarea>
        </div>
        <div class="crm-editor-actions">
            <button class="btn-secondary" onclick="closeDealEditor()">Скрыть</button>
            <button class="btn-primary" onclick="saveDeal()">Сохранить</button>
        </div>
    `;
}

function closeLeadEditor() {
    editingLeadId = 0;
    const panel = document.getElementById('leadEditorPanel');
    if (panel) panel.style.display = 'none';
}

function closeDealEditor() {
    editingDealId = 0;
    const panel = document.getElementById('dealEditorPanel');
    if (panel) panel.style.display = 'none';
}

function selectLeadRow(id) {
    currentLeadId = Number(id || 0);
    renderLeads();
}

function selectDealRow(id) {
    currentDealId = Number(id || 0);
    renderDeals();
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
    if (!payload.title.trim()) return customAlert('Укажи название лида.');
    const endpoint = editingLeadId ? `/crm/leads/${editingLeadId}` : '/crm/leads';
    const method = editingLeadId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить лид.');
    await loadCrmLeads();
    currentLeadId = Number(res.id || editingLeadId || currentLeadId);
    closeLeadEditor();
    renderLeads();
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

async function saveDeal() {
    const payload = {
        title: document.getElementById('dealFormTitle')?.value || '',
        client_name: document.getElementById('dealFormClient')?.value || '',
        contract_number: document.getElementById('dealFormContract')?.value || '',
        stage: document.getElementById('dealFormStage')?.value || 'qualification',
        responsible: document.getElementById('dealFormResponsible')?.value || '',
        next_action: document.getElementById('dealFormNextAction')?.value || '',
        next_action_date: document.getElementById('dealFormNextActionDate')?.value || '',
        expected_close_date: document.getElementById('dealFormExpectedCloseDate')?.value || '',
        amount: Number(document.getElementById('dealFormAmount')?.value || 0),
        margin_percent: Number(document.getElementById('dealFormMargin')?.value || 0),
        probability: Number(document.getElementById('dealFormProbability')?.value || 0),
        tags: String(document.getElementById('dealFormTags')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        comment: document.getElementById('dealFormComment')?.value || '',
        currency: 'RUB',
        priority: 'normal',
        status_color: '',
    };
    if (!payload.title.trim()) return customAlert('Укажи название сделки.');
    const endpoint = editingDealId ? `/crm/deals/${editingDealId}` : '/crm/deals';
    const method = editingDealId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить сделку.');
    await loadCrmDeals();
    currentDealId = Number(res.id || editingDealId || currentDealId);
    closeDealEditor();
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
    if (!payload.subject.trim()) return customAlert('Укажи тему активности.');
    const res = await apiCall('/crm/activities', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить активность.');
    if (entityType === 'lead') {
        await loadCrmLeads();
        renderLeads();
    } else {
        await loadCrmDeals();
        renderDeals();
    }
}

async function toggleCrmActivityStatus(activityId, entityType, entityId, status) {
    const res = await apiCall('/crm/activities', 'GET');
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
    const res = await apiCall(`/crm/leads/${leadId}/convert`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось конвертировать лид.');
    await Promise.all([loadCrmLeads(), loadCrmDeals()]);
    currentDealId = Number(res.deal_id || 0);
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
    fillResponsibleSelect('leadResponsibleFilter', crmLeadsDB, currentLeadResponsible);
    crmFillPresetSelect('leadPresetSelect', crmReadPresets('lead'));
    renderLeadSummary();
    renderLeadRoutingPanel();
    const searchInput = document.getElementById('leadSearchInput');
    const stageFilter = document.getElementById('leadStageFilter');
    const sortSelect = document.getElementById('leadSortSelect');
    if (searchInput) searchInput.value = currentLeadSearch;
    if (stageFilter) stageFilter.value = currentLeadStage;
    if (sortSelect) sortSelect.value = currentLeadSort;
    document.getElementById('leadModeRegistry')?.classList.toggle('active', currentLeadViewMode === 'registry');
    document.getElementById('leadModeKanban')?.classList.toggle('active', currentLeadViewMode === 'kanban');
    const mount = document.getElementById('leadsContentMount');
    if (!mount) return;
    const rows = leadRowsFiltered();
    mount.innerHTML = currentLeadViewMode === 'kanban'
        ? renderKanban([
            { key: 'new', label: 'Новые' },
            { key: 'qualified', label: 'Квалифицированы' },
            { key: 'proposal', label: 'КП / предложение' },
            { key: 'won', label: 'Конвертированы' },
            { key: 'lost', label: 'Потеряны' },
        ], rows, 'lead')
        : renderLeadRegistry();
}

async function renderDeals() {
    if (!Array.isArray(crmDealsDB) || !crmDealsDB.length) await loadCrmDeals();
    fillResponsibleSelect('dealResponsibleFilter', crmDealsDB, currentDealResponsible);
    crmFillPresetSelect('dealPresetSelect', crmReadPresets('deal'));
    renderDealSummary();
    const searchInput = document.getElementById('dealSearchInput');
    const stageFilter = document.getElementById('dealStageFilter');
    const sortSelect = document.getElementById('dealSortSelect');
    if (searchInput) searchInput.value = currentDealSearch;
    if (stageFilter) stageFilter.value = currentDealStage;
    if (sortSelect) sortSelect.value = currentDealSort;
    document.getElementById('dealModeRegistry')?.classList.toggle('active', currentDealViewMode === 'registry');
    document.getElementById('dealModeKanban')?.classList.toggle('active', currentDealViewMode === 'kanban');
    const mount = document.getElementById('dealsContentMount');
    if (!mount) return;
    const rows = dealRowsFiltered();
    mount.innerHTML = currentDealViewMode === 'kanban'
        ? renderKanban([
            { key: 'qualification', label: 'Квалификация' },
            { key: 'proposal', label: 'Предложение' },
            { key: 'negotiation', label: 'Переговоры' },
            { key: 'won', label: 'Выиграно' },
            { key: 'lost', label: 'Потеряно' },
        ], rows, 'deal')
        : renderDealRegistry();
}

window.renderLeads = renderLeads;
window.renderDeals = renderDeals;
window.openLeadEditor = openLeadEditor;
window.openDealEditor = openDealEditor;
window.closeLeadEditor = closeLeadEditor;
window.closeDealEditor = closeDealEditor;
window.selectLeadRow = selectLeadRow;
window.selectDealRow = selectDealRow;
window.saveLead = saveLead;
window.saveDeal = saveDeal;
window.applyLeadRouting = applyLeadRouting;
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
