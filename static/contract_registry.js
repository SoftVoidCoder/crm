// Реестр договоров и справочник контрагентов (API /api/cr/*).
const crState = {
    folder: 'all',
    period: 'all',
    statusFilter: '',
    mineApprovals: false,
    filesQuery: '',
    columnFilters: {},
    meta: { folders: [], total: 0, deleted: 0 },
    contracts: [],
    selectedId: 0,
    checked: new Set(),
    docTypes: [],
    counterparties: [],
    users: [],
    params: [],
    card: null,
    cardSection: 'main',
    mainTab: 'subject',
    cardDirty: false,
};
let crSearchTimer = null;

const CR_ROLES = ['Заказчик', 'Исполнитель', 'Поставщик', 'Покупатель', 'Подрядчик', 'Арендодатель', 'Арендатор', 'Займодавец', 'Заёмщик', 'Лизингодатель', 'Лизингополучатель', 'Наша организация', 'Другое'];
const CR_SIGNING_METHODS = ['', 'Бумажный оригинал', 'ЭДО', 'Скан-копия', 'Почта России', 'Курьер'];
const CR_ORIGINAL_STATUSES = ['', 'Оригинал у нас', 'Оригинал у контрагента', 'Ожидаем оригинал', 'Только скан'];
const CR_APPROVAL_LABELS = { pending: 'В процессе', approved: 'Согласовано', approved_with_notes: 'Согласовано с замечаниями', rejected: 'Отклонено' };
const CR_STATUSES = { draft: 'Черновик', approval: 'На согласовании', active: 'Действует', executed: 'Исполнен', terminated: 'Расторгнут', archive: 'Архив' };
const CR_MAIN_TABS = [
    ['subject', 'Предмет договора'], ['note', 'Примечание'], ['basis', 'Основание'],
    ['prepayment_terms', 'Предоплата и выполн. работ'], ['closing_info', 'Закрытие договора'], ['object_info', 'Объект'],
    ['insurance_info', 'Страхование'], ['owner_approval', 'Согласование с собственником'],
];

// Разделы карточки, которые хранятся строками (cr_items). [ключ, подпись, тип, варианты]
const CR_ITEM_SECTIONS = {
    payments: { title: 'Платежи и неустойка', totals: ['plan_amount', 'fact_amount'], cols: [
        ['kind', 'Вид', 'select', ['Платёж', 'Предоплата', 'Аванс', 'Окончательный расчёт', 'Неустойка', 'Штраф', 'Пени', 'Возврат']],
        ['direction', 'Направление', 'select', ['Входящий', 'Исходящий']],
        ['plan_date', 'Дата (план)', 'date'], ['plan_amount', 'Сумма (план)', 'money'],
        ['fact_date', 'Дата (факт)', 'date'], ['fact_amount', 'Сумма (факт)', 'money'],
        ['doc', 'Платёжный документ', 'text'], ['note', 'Примечание', 'text']] },
    specs: { title: 'Документы/Спецификации', totals: ['amount'], cols: [
        ['kind', 'Вид документа', 'select', ['Спецификация', 'Приложение', 'Счёт', 'Акт', 'УПД', 'Товарная накладная', 'Счёт-фактура', 'Другое']],
        ['number', 'Номер', 'text'], ['date', 'Дата', 'date'], ['amount', 'Сумма', 'money'],
        ['status', 'Статус', 'select', ['Черновик', 'На подписании', 'Подписан', 'Аннулирован']], ['note', 'Примечание', 'text']] },
    stages: { title: 'Этапы и виды работ', totals: ['amount'], cols: [
        ['name', 'Этап', 'text'], ['work_type', 'Вид работ', 'text'], ['plan_start', 'Начало (план)', 'date'],
        ['plan_end', 'Окончание (план)', 'date'], ['fact_end', 'Окончание (факт)', 'date'], ['amount', 'Стоимость', 'money'],
        ['responsible', 'Ответственный', 'user'], ['status', 'Статус', 'select', ['Не начат', 'В работе', 'Выполнен', 'Приостановлен']]] },
    court: { title: 'Судебные дела', totals: ['claim_amount'], cols: [
        ['case_no', '№ дела', 'text'], ['court', 'Суд', 'text'], ['our_role', 'Наша роль', 'select', ['Истец', 'Ответчик', 'Третье лицо']],
        ['subject', 'Предмет спора', 'text'], ['claim_amount', 'Сумма иска', 'money'], ['filed', 'Дата подачи', 'date'],
        ['next_hearing', 'Следующее заседание', 'date'],
        ['status', 'Статус', 'select', ['Подготовка', 'В производстве', 'Решение вынесено', 'Обжалуется', 'Исполнено', 'Закрыто']], ['result', 'Результат', 'text']] },
    claims: { title: 'Претензии', totals: ['amount'], cols: [
        ['number', 'Номер', 'text'], ['date', 'Дата', 'date'], ['direction', 'Направление', 'select', ['Исходящая', 'Входящая']],
        ['amount', 'Сумма требований', 'money'], ['answer_due', 'Срок ответа', 'date'],
        ['status', 'Статус', 'select', ['Направлена', 'Получена', 'Удовлетворена', 'Частично удовлетворена', 'Отклонена']], ['content', 'Суть претензии', 'text']] },
    other: { title: 'Прочее', cols: [['name', 'Наименование', 'text'], ['value', 'Значение', 'text'], ['note', 'Примечание', 'text']] },
    supplements: { title: 'Доп. соглашения', totals: ['amount_change'], cols: [
        ['number', 'Номер', 'text'], ['date', 'Дата', 'date'], ['subject', 'Предмет', 'text'], ['amount_change', 'Изменение суммы', 'money'],
        ['new_end_date', 'Новая дата окончания', 'date'], ['signed', 'Подписано', 'select', ['Нет', 'Да']]] },
    subcontracts: { title: 'Субподряды', totals: ['amount'], cols: [
        ['contractor', 'Субподрядчик', 'text'], ['contract_no', '№ договора', 'text'], ['date', 'Дата', 'date'], ['amount', 'Сумма', 'money'],
        ['end_date', 'Срок', 'date'], ['status', 'Статус', 'select', ['Действует', 'Исполнен', 'Расторгнут']]] },
    tasks: { title: 'Задачи', cols: [
        ['title', 'Задача', 'text'], ['assignee', 'Исполнитель', 'user'], ['due', 'Срок', 'date'],
        ['status', 'Статус', 'select', ['Новая', 'В работе', 'Выполнена', 'Отменена']], ['result', 'Результат', 'text']] },
    costs: { title: 'Затраты', totals: ['amount'], cols: [
        ['article', 'Статья затрат', 'text'], ['date', 'Дата', 'date'], ['amount', 'Сумма', 'money'], ['counterparty', 'Получатель', 'text'], ['note', 'Примечание', 'text']] },
    letters: { title: 'Письма', cols: [
        ['direction', 'Направление', 'select', ['Исходящее', 'Входящее']], ['number', 'Номер', 'text'], ['date', 'Дата', 'date'],
        ['correspondent', 'Корреспондент', 'text'], ['subject', 'Тема', 'text'], ['status', 'Статус', 'select', ['Зарегистрировано', 'Отправлено', 'Получено', 'Получен ответ']]] },
    access: { title: 'Права доступа', cols: [
        ['user', 'Пользователь', 'useremail'], ['level', 'Доступ', 'select', [['read', 'Только просмотр'], ['edit', 'Просмотр и изменение']]]] },
    movements: { title: 'Движения', cols: [
        ['date', 'Дата', 'date'], ['item', 'Что передано', 'select', ['Оригинал договора', 'Копия договора', 'Доп. соглашение', 'Акт', 'Другое']],
        ['from', 'Откуда / от кого', 'text'], ['to', 'Куда / кому', 'text'], ['handed_by', 'Передал', 'user'], ['received_by', 'Принял', 'text'], ['note', 'Примечание', 'text']] },
    poa: { title: 'Доверенности', cols: [
        ['number', 'Номер', 'text'], ['issue_date', 'Дата выдачи', 'date'], ['valid_to', 'Действует до', 'date'], ['attorney', 'Доверенное лицо', 'text'], ['powers', 'Полномочия', 'text']] },
    passes: { title: 'Пропуска', cols: [
        ['person', 'ФИО', 'text'], ['organization', 'Организация', 'text'], ['vehicle', 'Автомобиль / госномер', 'text'],
        ['valid_from', 'Действует с', 'date'], ['valid_to', 'Действует по', 'date'], ['object', 'Объект', 'text']] },
};

const CR_SECTIONS = [
    ['main', 'Основные'], ['parties', 'Контрагенты'], ['payments', 'Платежи и неустойка'], ['approvals', 'Согласования'],
    ['files', 'Файлы'], ['specs', 'Документы/Спецификации'], ['stages', 'Этапы и виды работ'], ['court', 'Судебные дела'],
    ['claims', 'Претензии'], ['other', 'Прочее'], ['supplements', 'Доп. соглашения'], ['subcontracts', 'Субподряды'],
    ['tasks', 'Задачи'], ['costs', 'Затраты'], ['letters', 'Письма'], ['access', 'Права доступа'], ['movements', 'Движения'],
    ['poa', 'Доверенности'], ['passes', 'Пропуска'],
];
const CR_HIDDEN_KEY = 'korda_cr_hidden_sections';

const crEsc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const crMoney = value => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const crDate = value => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
    return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
};
const crFail = res => !res || res.error;
const crErrorText = (res, fallback) => (res && (res.message || res.error)) || fallback;
const crToday = () => new Date().toISOString().slice(0, 10);

function crHiddenSections() {
    try { return new Set(JSON.parse(localStorage.getItem(CR_HIDDEN_KEY) || '[]')); } catch (e) { return new Set(); }
}

// ---------- modal ----------

function crModal(title, bodyHtml, footerHtml = '', options = {}) {
    const overlay = document.createElement('div');
    overlay.className = 'cr-modal-overlay';
    overlay.innerHTML = `
        <div class="cr-modal ${options.wide ? 'cr-modal--wide' : ''} ${options.full ? 'cr-modal--full' : ''}" role="dialog" aria-modal="true">
            <div class="cr-modal-head"><h2>${crEsc(title)}</h2><button type="button" class="cr-modal-close" aria-label="Закрыть">✕</button></div>
            <div class="cr-modal-body">${bodyHtml}</div>
            ${footerHtml ? `<div class="cr-modal-foot">${footerHtml}</div>` : ''}
        </div>`;
    const close = () => {
        if (options.onClose && options.onClose() === false) return;
        overlay.remove();
    };
    overlay.querySelector('.cr-modal-close').onclick = close;
    overlay.addEventListener('mousedown', event => { if (event.target === overlay) close(); });
    overlay.closeModal = () => overlay.remove();
    overlay.requestClose = close;
    document.body.appendChild(overlay);
    return overlay;
}

function crPromptName(title, initial = '') {
    return new Promise(resolve => {
        const modal = crModal(title, `<input class="cr-input" id="crPromptInput" value="${crEsc(initial)}" maxlength="500">`,
            `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button><button class="btn-primary" type="button" data-act="ok">Сохранить</button>`);
        const input = modal.querySelector('#crPromptInput');
        const finish = value => { modal.closeModal(); resolve(value); };
        modal.querySelector('[data-act="cancel"]').onclick = () => finish(null);
        modal.querySelector('[data-act="ok"]').onclick = () => finish(input.value.trim());
        input.addEventListener('keydown', event => { if (event.key === 'Enter') finish(input.value.trim()); });
        input.focus();
    });
}

function crChoose(title, label, options) {
    return new Promise(resolve => {
        const modal = crModal(title, `<label class="cr-form-label">${crEsc(label)}<select class="cr-input" id="crChooseSelect">${options.map(([v, t]) => `<option value="${crEsc(v)}">${crEsc(t)}</option>`).join('')}</select></label>`,
            `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button><button class="btn-primary" type="button" data-act="ok">Применить</button>`);
        modal.querySelector('[data-act="cancel"]').onclick = () => { modal.closeModal(); resolve(null); };
        modal.querySelector('[data-act="ok"]').onclick = () => { const v = modal.querySelector('#crChooseSelect').value; modal.closeModal(); resolve(v); };
    });
}

// ---------- registry ----------

async function renderContractRegistry() {
    await Promise.all([crLoadMeta(), crLoadContracts()]);
    const match = /^#cr=(\d+)$/.exec(location.hash || '');
    if (match) {
        history.replaceState(null, '', location.pathname + location.search);
        crOpenCard(Number(match[1]));
    }
}

async function crLoadMeta() {
    const res = await apiCall('/cr/meta');
    if (crFail(res)) return;
    crState.meta = res;
    crRenderFolders();
}

function crRenderFolders() {
    const list = document.getElementById('crFolderList');
    if (!list) return;
    const items = [
        { key: 'all', name: 'Все', count: crState.meta.total },
        { key: 'deleted', name: 'Удалённые', count: crState.meta.deleted },
        ...crState.meta.folders.map(folder => ({ key: String(folder.id), name: folder.name, count: folder.count })),
    ];
    list.innerHTML = items.map(item => `
        <li class="${String(crState.folder) === item.key ? 'active' : ''}" onclick="crSelectFolder('${item.key}')">
            <span class="cr-folder-icon">${item.key === 'deleted' ? '🗑' : '📁'}</span>
            <span class="cr-folder-name">${crEsc(item.name)}</span>
            <span class="cr-folder-count">${item.count}</span>
        </li>`).join('');
    const deleteBtn = document.getElementById('crDeleteBtn');
    if (deleteBtn) deleteBtn.textContent = crState.folder === 'deleted' ? 'Восстановить' : 'Удалить';
}

function crSelectFolder(key) {
    crState.folder = key;
    crState.selectedId = 0;
    crState.checked.clear();
    crRenderFolders();
    crLoadContracts();
}

function crSetPeriod(value) {
    crState.period = value;
    const radio = document.querySelector(`input[name="crPeriod"][value="${value}"]`);
    if (radio) radio.checked = true;
    crLoadContracts();
}

function crScheduleSearch() {
    clearTimeout(crSearchTimer);
    crSearchTimer = setTimeout(crLoadContracts, 250);
}

function crSetStatusFilter(value) {
    crState.statusFilter = value;
    crLoadContracts();
}

function crToggleMine() {
    crState.mineApprovals = !crState.mineApprovals;
    document.getElementById('crMineBtn')?.classList.toggle('cr-btn-active', crState.mineApprovals);
    crLoadContracts();
}

function crToggleFileSearch() {
    const input = document.getElementById('crFilesSearch');
    if (!input) return;
    const show = input.hidden;
    input.hidden = !show;
    document.getElementById('crFilesBtn')?.classList.toggle('cr-btn-active', show);
    if (show) input.focus();
    else if (input.value) { input.value = ''; crState.filesQuery = ''; crLoadContracts(); }
}

function crSetFilesQuery(value) {
    crState.filesQuery = value.trim();
    crScheduleSearch();
}

async function crLoadContracts() {
    const params = new URLSearchParams({ folder: crState.folder, period: crState.period });
    if (crState.period === 'range') {
        params.set('date_from', document.getElementById('crDateFrom')?.value || '');
        params.set('date_to', document.getElementById('crDateTo')?.value || '');
    }
    const query = document.getElementById('crSearch')?.value.trim();
    if (query) params.set('q', query);
    if (crState.statusFilter) params.set('status', crState.statusFilter);
    if (crState.mineApprovals) params.set('mine_approvals', '1');
    if (crState.filesQuery) params.set('files_q', crState.filesQuery);
    const res = await apiCall(`/cr/contracts?${params}`);
    if (crFail(res)) return;
    crState.contracts = res;
    crRenderTable();
}

function crRowClass(contract) {
    const flags = contract.flags || {};
    if (flags.overdue) return 'cr-row--overdue';
    if (flags.approvals_overdue) return 'cr-row--appr-overdue';
    if (flags.expiring) return 'cr-row--expiring';
    if (flags.approvals_open) return 'cr-row--appr-open';
    return '';
}

// Колонки реестра: [ключ фильтра, функция значения для фильтра]
const CR_COLUMNS = [
    ['index', null], ['number', c => c.number], ['seq_no', c => c.seq_no || ''], ['extra_number', c => c.extra_number],
    ['incoming_number', c => c.incoming_number], ['gov_reg_number', c => c.gov_reg_number], ['flagged', null],
    ['status', c => CR_STATUSES[c.status] || ''], ['doc_type_name', c => c.doc_type_name],
    ['parties', c => (c.parties || []).map(p => `${p.name} ${p.inn || ''}`).join(' ')],
    ['created_date', c => crDate(c.created_date)], ['concluded_date', c => crDate(c.concluded_date)],
    ['end_date', c => c.indefinite ? 'бессрочный' : crDate(c.end_date)], ['amount', c => crMoney(c.amount)], ['vat', null],
    ['vat_rate', null], ['vat_amount', null], ['amount_without_vat', null],
];

function crSetColumnFilter(key, value) {
    crState.columnFilters[key] = value;
    crRenderTable();
}

function crVisibleContracts() {
    const filters = Object.entries(crState.columnFilters).filter(([, v]) => String(v || '').trim());
    if (!filters.length) return crState.contracts;
    const getters = Object.fromEntries(CR_COLUMNS);
    return crState.contracts.filter(contract => filters.every(([key, value]) => {
        // "%" как в старой программе — просто «содержит».
        const needle = String(value).replace(/%/g, '').trim().toLowerCase();
        return !needle || String(getters[key]?.(contract) ?? '').toLowerCase().includes(needle);
    }));
}

function crRenderFilterRow() {
    const row = document.getElementById('crFilterRow');
    if (!row || row.dataset.ready) return;
    row.dataset.ready = '1';
    row.innerHTML = CR_COLUMNS.map(([key, getter]) => getter
        ? `<th><input class="cr-col-filter" placeholder="фильтр" value="${crEsc(crState.columnFilters[key] || '')}" oninput="crSetColumnFilter('${key}', this.value)"></th>`
        : '<th></th>').join('');
}

function crRenderTable() {
    crRenderFilterRow();
    const body = document.getElementById('crTableBody');
    if (!body) return;
    const rows = crVisibleContracts();
    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="${CR_COLUMNS.length}" class="cr-empty">${crState.contracts.length ? 'Ничего не найдено по фильтрам.' : 'Договоров нет. Нажми «+ Добавить договор», чтобы создать первый.'}</td></tr>`;
    } else {
        body.innerHTML = rows.map((contract, index) => `
            <tr class="${crRowClass(contract)} ${contract.id === crState.selectedId ? 'cr-row--selected' : ''}" onclick="crSelectRow(${contract.id})" ondblclick="crOpenCard(${contract.id})">
                <td>${index + 1}</td>
                <td><strong>${crEsc(contract.number)}</strong></td>
                <td>${contract.seq_no || ''}</td>
                <td>${crEsc(contract.extra_number)}</td>
                <td>${crEsc(contract.incoming_number)}</td>
                <td>${crEsc(contract.gov_reg_number)}</td>
                <td><input type="checkbox" ${crState.checked.has(contract.id) ? 'checked' : ''} onclick="event.stopPropagation(); crToggleCheck(${contract.id}, this.checked)"></td>
                <td><span class="cr-pill cr-pill--${crEsc(contract.status)}">${CR_STATUSES[contract.status] || ''}</span></td>
                <td class="cr-wrap">${crEsc(contract.doc_type_name)}</td>
                <td class="cr-wrap">${(contract.parties || []).map(p => crEsc(p.name)).join('<br>')}</td>
                <td>${crDate(contract.created_date)}</td>
                <td>${crDate(contract.concluded_date)}</td>
                <td>${contract.indefinite ? 'бессрочный' : crDate(contract.end_date)}</td>
                <td class="cr-num">${crMoney(contract.amount)}</td>
                <td>${contract.vat_enabled ? '✓' : ''}</td>
                <td class="cr-num">${contract.vat_enabled ? Number(contract.vat_rate || 0) : ''}</td>
                <td class="cr-num">${crMoney(contract.vat_enabled ? contract.vat_amount : 0)}</td>
                <td class="cr-num">${crMoney(contract.amount_without_vat)}</td>
            </tr>`).join('');
    }
    const sum = key => rows.reduce((acc, item) => acc + Number(key === 'vat_amount' && !item.vat_enabled ? 0 : item[key] || 0), 0);
    const footer = document.getElementById('crFooter');
    if (footer) {
        footer.innerHTML = `
            <span>Всего: <strong>${rows.length}</strong></span>
            <span>Отмечено: <strong>${crState.checked.size}</strong></span>
            <span class="cr-footer-sums">Сумма: <strong>${crMoney(sum('amount'))}</strong> · НДС: <strong>${crMoney(sum('vat_amount'))}</strong> · Без НДС: <strong>${crMoney(sum('amount_without_vat'))}</strong></span>`;
    }
}

function crSelectRow(id) {
    crState.selectedId = id;
    crRenderTable();
}

function crToggleCheck(id, checked) {
    if (checked) crState.checked.add(id);
    else crState.checked.delete(id);
    crRenderTable();
}

function crTargetIds() {
    if (crState.checked.size) return [...crState.checked];
    return crState.selectedId ? [crState.selectedId] : [];
}

function crOpenSelected() {
    if (!crState.selectedId) return customAlert('Выбери договор в таблице.');
    crOpenCard(crState.selectedId);
}

function crOpenInNewTab() {
    if (!crState.selectedId) return customAlert('Выбери договор в таблице.');
    window.open(`/app#cr=${crState.selectedId}`, '_blank', 'noopener');
}

async function crCopySelected() {
    if (!crState.selectedId) return customAlert('Выбери договор, который нужно скопировать.');
    const res = await apiCall(`/cr/contracts/${crState.selectedId}/copy`, 'POST');
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось скопировать договор.'));
    showToast('Договоры', 'Копия создана');
    await renderContractRegistry();
    crOpenCard(res.id);
}

async function crDeleteSelected() {
    const ids = crTargetIds();
    if (!ids.length) return customAlert('Выбери договор или отметь несколько галочками.');
    const restoring = crState.folder === 'deleted';
    if (!restoring && !(await customConfirm(`Переместить в «Удалённые» договоров: ${ids.length}? Их можно будет восстановить.`))) return;
    let failed = 0;
    for (const id of ids) {
        const res = await apiCall(restoring ? `/cr/contracts/${id}/restore` : `/cr/contracts/${id}`, restoring ? 'POST' : 'DELETE');
        if (crFail(res)) failed += 1;
    }
    crState.checked.clear();
    crState.selectedId = 0;
    showToast('Договоры', `${restoring ? 'Восстановлено' : 'Перемещено в «Удалённые»'}${failed ? ` · без прав: ${failed}` : ''}`, failed ? 'error' : 'success');
    renderContractRegistry();
}

async function crBulkStatus() {
    const ids = crTargetIds();
    if (!ids.length) return customAlert('Выбери договор или отметь несколько галочками.');
    const status = await crChoose('Статус договора', `Новый статус для договоров: ${ids.length}`, Object.entries(CR_STATUSES));
    if (!status) return;
    let failed = 0;
    for (const id of ids) {
        const res = await apiCall(`/cr/contracts/${id}`, 'PUT', { status });
        if (crFail(res)) failed += 1;
    }
    showToast('Договоры', failed ? `Статус изменён, без прав: ${failed}` : 'Статус изменён', failed ? 'error' : 'success');
    crLoadContracts();
}

function crRegistryRows() {
    return crVisibleContracts().map((c, i) => ({
        '№': i + 1,
        'Номер': c.number,
        'Порядковый номер': c.seq_no || '',
        'Доп. номер': c.extra_number,
        'Входящий номер': c.incoming_number,
        'Номер гос. регистрации': c.gov_reg_number,
        'Статус': CR_STATUSES[c.status] || '',
        'Тип документа': c.doc_type_name || '',
        'Контрагенты': (c.parties || []).map(p => `${p.name}${p.inn ? ` (ИНН ${p.inn})` : ''}`).join('; '),
        'Дата создания': crDate(c.created_date),
        'Дата заключения': crDate(c.concluded_date),
        'Дата окончания': c.indefinite ? 'бессрочный' : crDate(c.end_date),
        'Сумма': Number(c.amount || 0),
        'НДС': c.vat_enabled ? 'да' : 'нет',
        '% НДС': c.vat_enabled ? Number(c.vat_rate || 0) : '',
        'Сумма НДС': c.vat_enabled ? Number(c.vat_amount || 0) : 0,
        'Сумма без НДС': Number(c.amount_without_vat || 0),
        'Ответственный': c.responsible,
        'Предмет': c.subject,
    }));
}

function crExport(format) {
    const rows = crRegistryRows();
    const stamp = new Date().toLocaleDateString('ru-RU');
    if (format === 'print') {
        const head = rows.length ? Object.keys(rows[0]) : [];
        return crPrintWindow('Реестр договоров', `<h1>Реестр договоров на ${stamp}</h1><table><tr>${head.map(h => `<th>${crEsc(h)}</th>`).join('')}</tr>
            ${rows.map(r => `<tr>${head.map(h => `<td>${crEsc(r[h])}</td>`).join('')}</tr>`).join('')}</table>`, true);
    }
    if (typeof XLSX === 'undefined') return customAlert('Выгрузка сейчас недоступна.');
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.json_to_sheet(rows), 'Договоры');
    XLSX.writeFile(book, `Реестр договоров ${stamp}.${format === 'csv' ? 'csv' : 'xlsx'}`, format === 'csv' ? { bookType: 'csv' } : undefined);
}

function crToggleExportMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('crExportMenu');
    if (!menu) return;
    menu.hidden = !menu.hidden;
    if (!menu.hidden) document.addEventListener('click', () => { menu.hidden = true; }, { once: true });
}

// ---------- folders ----------

function crCurrentFolder() {
    return crState.meta.folders.find(folder => String(folder.id) === String(crState.folder));
}

async function crAddFolder() {
    const name = await crPromptName('Новая папка');
    if (!name) return;
    const res = await apiCall('/cr/folders', 'POST', { name });
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось создать папку.'));
    crLoadMeta();
}

async function crRenameFolder() {
    const folder = crCurrentFolder();
    if (!folder) return customAlert('Выбери свою папку слева (не «Все» и не «Удалённые»).');
    const name = await crPromptName('Переименовать папку', folder.name);
    if (!name) return;
    const res = await apiCall(`/cr/folders/${folder.id}`, 'PUT', { name });
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось переименовать папку.'));
    crLoadMeta();
}

async function crDeleteFolder() {
    const folder = crCurrentFolder();
    if (!folder) return customAlert('Выбери свою папку слева (не «Все» и не «Удалённые»).');
    if (!(await customConfirm(`Удалить папку «${folder.name}»? Договоры из неё останутся в «Все».`))) return;
    await apiCall(`/cr/folders/${folder.id}`, 'DELETE');
    crSelectFolder('all');
    crLoadMeta();
}

// ---------- reference data ----------

async function crLoadDocTypes() {
    const res = await apiCall('/cr/doc_types');
    crState.docTypes = crFail(res) ? [] : res;
    return crState.docTypes;
}

async function crLoadCounterparties() {
    const res = await apiCall('/cr/counterparties');
    crState.counterparties = crFail(res) ? [] : res;
    return crState.counterparties;
}

async function crLoadParams() {
    const res = await apiCall('/cr/params');
    crState.params = crFail(res) ? [] : res;
    return crState.params;
}

async function crLoadUsers() {
    if (crState.users.length) return crState.users;
    const res = await apiCall('/users/all');
    crState.users = Array.isArray(res) ? res.filter(u => u.status === 'approved') : [];
    return crState.users;
}

function crFormatNumber(type, seq) {
    const digits = Math.max(0, Math.min(12, Number(type.digits || 0)));
    const core = digits ? String(seq).padStart(digits, '0') : String(seq);
    return `${type.prefix || ''}${core}${type.postfix || ''}${Number(type.add_year) ? new Date().getFullYear() : ''}`;
}

function crCounterpartyOptions(selectedId, emptyLabel = '— не выбран —') {
    return `<option value="0">${emptyLabel}</option>` + crState.counterparties.map(p =>
        `<option value="${p.id}" ${Number(selectedId) === Number(p.id) ? 'selected' : ''}>${crEsc(p.short_name || p.name)}${p.inn ? ` · ИНН ${crEsc(p.inn)}` : ''}</option>`).join('');
}

// ---------- document types ----------

// onPick(type, noAutonumber) — режим выбора типа из окна создания договора.
async function crOpenDocTypes(onPick = null) {
    await Promise.all([crLoadDocTypes(), crLoadCounterparties()]);
    let editingId = 0;
    const modal = crModal('Типы документов', `
        <div class="cr-form-grid cr-form-grid--types">
            <label class="cr-span-4">Наименование<input class="cr-input" id="crTypeName" placeholder="Например: ЕТС КОРДА (договор продажи товара)"></label>
            <label>Префикс<input class="cr-input" id="crTypePrefix" placeholder="ДПТ-"></label>
            <label>№ п/п (текущий)<input class="cr-input" id="crTypeCounter" type="number" min="0" value="0"></label>
            <label>Разрядность<input class="cr-input" id="crTypeDigits" type="number" min="0" max="12" value="0"></label>
            <label>Постпрефикс<input class="cr-input" id="crTypePostfix" placeholder="/П-"></label>
            <label class="cr-span-3">Наша организация / категория<select class="cr-input" id="crTypeCounterparty"></select></label>
            <label class="cr-check"><input type="checkbox" id="crTypeYear"> Добавлять год</label>
            <div class="cr-span-4 cr-type-preview">Следующий номер: <strong id="crTypePreview">—</strong></div>
        </div>
        <div class="cr-toolbar">
            <div class="cr-toolbar-group">
                ${onPick ? '<button class="btn-primary" type="button" data-act="pick">Выбрать</button><button class="btn-secondary" type="button" data-act="pick-manual">Выбрать без автонумерации</button>' : ''}
                <button class="btn-secondary" type="button" data-act="add">+ Добавить</button>
                <button class="btn-secondary" type="button" data-act="save">Сохранить изменения</button>
                <button class="btn-secondary" type="button" data-act="delete">Удалить</button>
                <button class="btn-secondary" type="button" data-act="clear">Очистить форму</button>
            </div>
            <input class="cr-search" id="crTypeFilter" type="search" placeholder="Фильтр по названию, префиксу…">
        </div>
        <div class="cr-table-wrap cr-table-wrap--modal">
            <table class="cr-table"><thead><tr><th>Наименование</th><th>Префикс</th><th>№ п/п</th><th>Разрядность</th><th>Постпрефикс</th><th>Год</th><th>Категория</th><th>Следующий номер</th></tr></thead><tbody id="crTypeBody"></tbody></table>
        </div>
        <p class="cr-hint">Номер собирается так: <b>Префикс</b> + порядковый номер, дополненный нулями до <b>Разрядности</b> + <b>Постпрефикс</b> + год (если отмечено).
        Пример: префикс «КР-», № 17, разрядность 5, постпрефикс «/П-», год → <b>КР-00017/П-${new Date().getFullYear()}</b>.
        «Выбрать без автонумерации» — тип запишется в договор, а номер введёшь вручную, счётчик не изменится.</p>`, '', { wide: true });

    const field = id => modal.querySelector(`#${id}`);
    const formValues = () => ({
        name: field('crTypeName').value.trim(),
        prefix: field('crTypePrefix').value,
        counter: Number(field('crTypeCounter').value || 0),
        digits: Number(field('crTypeDigits').value || 0),
        postfix: field('crTypePostfix').value,
        add_year: field('crTypeYear').checked ? 1 : 0,
        counterparty_id: Number(field('crTypeCounterparty').value || 0),
    });
    const updatePreview = () => { field('crTypePreview').textContent = crFormatNumber(formValues(), formValues().counter + 1); };
    const renderRows = () => {
        const filter = field('crTypeFilter').value.trim().toLowerCase();
        const rows = crState.docTypes.filter(t => !filter || `${t.name} ${t.prefix} ${t.counterparty_name}`.toLowerCase().includes(filter));
        field('crTypeBody').innerHTML = rows.length ? rows.map(t => `
            <tr class="${t.id === editingId ? 'cr-row--selected' : ''}" data-id="${t.id}">
                <td>${crEsc(t.name)}</td><td>${crEsc(t.prefix)}</td><td>${t.counter}</td><td>${t.digits}</td>
                <td>${crEsc(t.postfix)}</td><td>${Number(t.add_year) ? '✓' : ''}</td><td>${crEsc(t.counterparty_name)}</td><td>${crEsc(t.next_number)}</td>
            </tr>`).join('') : '<tr><td colspan="8" class="cr-empty">Типов пока нет. Заполни форму сверху и нажми «+ Добавить».</td></tr>';
        field('crTypeBody').querySelectorAll('tr[data-id]').forEach(row => {
            const type = crState.docTypes.find(t => t.id === Number(row.dataset.id));
            row.onclick = () => fill(type);
            row.ondblclick = () => { if (onPick) { modal.closeModal(); onPick(type, false); } };
        });
    };
    const fill = type => {
        editingId = type ? type.id : 0;
        field('crTypeName').value = type?.name || '';
        field('crTypePrefix').value = type?.prefix || '';
        field('crTypeCounter').value = type?.counter || 0;
        field('crTypeDigits').value = type?.digits || 0;
        field('crTypePostfix').value = type?.postfix || '';
        field('crTypeYear').checked = !!Number(type?.add_year);
        field('crTypeCounterparty').innerHTML = crCounterpartyOptions(type?.counterparty_id || 0, '— без категории —');
        updatePreview();
        renderRows();
    };
    ['crTypeName', 'crTypePrefix', 'crTypeCounter', 'crTypeDigits', 'crTypePostfix', 'crTypeYear'].forEach(id => field(id).addEventListener('input', updatePreview));
    field('crTypeFilter').addEventListener('input', renderRows);
    const reload = async () => { await crLoadDocTypes(); renderRows(); };
    modal.querySelector('[data-act="add"]').onclick = async () => {
        const res = await apiCall('/cr/doc_types', 'POST', formValues());
        if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось добавить тип.'));
        editingId = res.id;
        await reload();
        showToast('Типы документов', 'Тип добавлен');
    };
    modal.querySelector('[data-act="save"]').onclick = async () => {
        if (!editingId) return customAlert('Выбери тип в таблице, чтобы сохранить изменения.');
        const res = await apiCall(`/cr/doc_types/${editingId}`, 'PUT', formValues());
        if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось сохранить тип.'));
        await reload();
        showToast('Типы документов', 'Изменения сохранены');
    };
    modal.querySelector('[data-act="delete"]').onclick = async () => {
        if (!editingId) return customAlert('Выбери тип в таблице.');
        if (!(await customConfirm('Удалить выбранный тип документа?'))) return;
        const res = await apiCall(`/cr/doc_types/${editingId}`, 'DELETE');
        if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось удалить тип.'));
        fill(null);
        await reload();
    };
    modal.querySelector('[data-act="clear"]').onclick = () => fill(null);
    const pick = manual => {
        const type = crState.docTypes.find(t => t.id === editingId);
        if (!type) return customAlert('Выбери тип в таблице.');
        modal.closeModal();
        onPick(type, manual);
    };
    modal.querySelector('[data-act="pick"]')?.addEventListener('click', () => pick(false));
    modal.querySelector('[data-act="pick-manual"]')?.addEventListener('click', () => pick(true));
    fill(null);
}

// ---------- create ----------

async function crOpenCreate() {
    await crLoadDocTypes();
    let picked = null;
    let noAutonumber = false;
    const modal = crModal('Номер документа', `
        <div class="cr-form-grid cr-form-grid--2">
            <label class="cr-span-2">Тип документа
                <span class="cr-input-row"><input class="cr-input" id="crNewType" readonly placeholder="Не выбран"><button class="btn-secondary" type="button" data-act="type">Выбрать</button></span>
            </label>
            <label class="cr-span-2">Номер<input class="cr-input" id="crNewNumber" placeholder="Подставится по типу документа или введи вручную"></label>
        </div>
        <p class="cr-hint" id="crNewHint">После «Продолжить» откроется карточка договора. Тип документа — ваш справочник для классификации и автонумерации. Номер и тип можно поменять позже.</p>`,
        `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button>
         <button class="btn-secondary" type="button" data-act="random">Случайный номер</button>
         <button class="btn-primary" type="button" data-act="ok">Продолжить</button>`);
    const setType = (type, manual = false) => {
        picked = type;
        noAutonumber = manual;
        modal.querySelector('#crNewType').value = type ? `${type.name}${manual ? ' (без автонумерации)' : ''}` : '';
        const numberInput = modal.querySelector('#crNewNumber');
        numberInput.value = type && !manual ? crFormatNumber(type, Number(type.counter || 0) + 1) : '';
        if (manual) numberInput.focus();
    };
    if (crState.docTypes.length === 1) setType(crState.docTypes[0]);
    modal.querySelector('[data-act="type"]').onclick = () => crOpenDocTypes(setType);
    modal.querySelector('[data-act="cancel"]').onclick = () => modal.closeModal();
    const submit = async random => {
        const folderId = /^\d+$/.test(String(crState.folder)) ? Number(crState.folder) : 0;
        const number = modal.querySelector('#crNewNumber').value.trim();
        if (noAutonumber && !number && !random) return customAlert('Введи номер договора вручную.');
        const res = await apiCall('/cr/contracts', 'POST', {
            doc_type_id: picked ? picked.id : 0,
            number,
            random: random ? 1 : 0,
            no_autonumber: noAutonumber ? 1 : 0,
            folder_id: folderId,
        });
        if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось создать договор.'));
        modal.closeModal();
        await renderContractRegistry();
        crOpenCard(res.id);
    };
    modal.querySelector('[data-act="ok"]').onclick = () => submit(false);
    modal.querySelector('[data-act="random"]').onclick = () => submit(true);
}

// ---------- contract card ----------

async function crOpenCard(contractId) {
    const [contract] = await Promise.all([apiCall(`/cr/contracts/${contractId}`), crLoadDocTypes(), crLoadCounterparties(), crLoadUsers(), crLoadParams()]);
    if (crFail(contract)) return customAlert(crErrorText(contract, 'Не удалось открыть договор.'));
    if (!crState.meta.folders.length) await crLoadMeta();
    crState.card = contract;
    crState.cardSection = 'main';
    crState.mainTab = 'subject';
    crState.cardDirty = false;
    const readOnly = contract.access_level !== 'edit';
    const modal = crModal(`Договор № ${contract.number}`, `
        <div class="cr-card ${readOnly ? 'cr-card--readonly' : ''}">
            <nav class="cr-card-nav" id="crCardNav"></nav>
            <div class="cr-card-body" id="crCardBody"></div>
        </div>
        <datalist id="crUsersList">${crState.users.map(u => `<option value="${crEsc(u.name || u.email)}">`).join('')}</datalist>`,
        `<span class="cr-muted" id="crCardMeta"></span>
         <button class="btn-secondary" type="button" data-act="tabs">Настройка вкладок</button>
         <button class="btn-secondary" type="button" data-act="param">Добавить польз. параметр</button>
         <button class="btn-secondary" type="button" data-act="profit">Рентабельность</button>
         <button class="btn-secondary" type="button" data-act="charts">Диаграммы</button>
         <button class="btn-secondary" type="button" data-act="print">Карточка договора</button>
         <button class="btn-secondary" type="button" data-act="close">Закрыть</button>
         ${readOnly ? '' : '<button class="btn-primary" type="button" data-act="save">Сохранить</button>'}`,
        { full: true, onClose: () => {
            if (crState.cardDirty && !window.confirm('Есть несохранённые изменения. Закрыть без сохранения?')) return false;
            crState.card = null;
            renderContractRegistry();
            return true;
        } });
    crState.cardModal = modal;
    modal.querySelector('[data-act="close"]').onclick = () => modal.requestClose();
    modal.querySelector('[data-act="save"]')?.addEventListener('click', () => crSaveCard());
    modal.querySelector('[data-act="print"]').onclick = () => crPrintCard();
    modal.querySelector('[data-act="tabs"]').onclick = () => crOpenTabSettings();
    modal.querySelector('[data-act="param"]').onclick = () => crOpenParamDialog();
    modal.querySelector('[data-act="profit"]').onclick = () => crSwitchSection('profit');
    modal.querySelector('[data-act="charts"]').onclick = () => crSwitchSection('charts');
    crRenderCard();
}

function crSectionCount(contract, key) {
    if (key === 'parties') return contract.parties.length;
    if (key === 'approvals') return contract.approvals.length;
    if (key === 'files') return contract.files.length;
    if (CR_ITEM_SECTIONS[key]) return (contract.items[key] || []).length;
    return null;
}

function crRenderCard() {
    const modal = crState.cardModal;
    const contract = crState.card;
    if (!modal || !contract) return;
    modal.querySelector('.cr-modal-head h2').textContent = `Договор № ${contract.number}${contract.access_level !== 'edit' ? ' · только просмотр' : ''}`;
    const hidden = crHiddenSections();
    modal.querySelector('#crCardNav').innerHTML = CR_SECTIONS.filter(([key]) => key === 'main' || !hidden.has(key)).map(([key, label]) => {
        const count = crSectionCount(contract, key);
        return `<button type="button" class="${crState.cardSection === key ? 'active' : ''}" onclick="crSwitchSection('${key}')">${label}${count !== null ? ` <span>${count}</span>` : ''}</button>`;
    }).join('');
    const updated = contract.updated_at ? new Date(contract.updated_at * 1000).toLocaleString('ru-RU') : '';
    modal.querySelector('#crCardMeta').textContent = `ID ${contract.id}${updated ? ` · изменён ${updated}` : ''}${contract.updated_by ? ` · ${contract.updated_by}` : ''}`;
    const body = modal.querySelector('#crCardBody');
    const section = crState.cardSection;
    if (section === 'main') { body.innerHTML = crMainSectionHtml(contract); crBindMainSection(body); }
    else if (section === 'parties') body.innerHTML = crPartiesSectionHtml(contract);
    else if (section === 'approvals') body.innerHTML = crApprovalsSectionHtml(contract);
    else if (section === 'files') body.innerHTML = crFilesSectionHtml(contract);
    else if (section === 'profit') body.innerHTML = crProfitHtml(contract);
    else if (section === 'charts') { body.innerHTML = crChartsHtml(); crDrawCharts(contract); }
    else if (CR_ITEM_SECTIONS[section]) body.innerHTML = crItemSectionHtml(contract, section);
    if (contract.access_level !== 'edit') body.querySelectorAll('input:not(.cr-keep), select, textarea, button:not(.cr-keep)').forEach(el => { el.disabled = true; });
}

function crSwitchSection(key) {
    if (crState.cardSection === 'main') crCollectMain();
    crState.cardSection = key;
    crRenderCard();
}

// ---- main

const crField = (label, name, value, type = 'text', extra = '') =>
    `<label>${label}<input class="cr-input" data-field="${name}" type="${type}" value="${crEsc(value ?? '')}" ${extra}></label>`;
const crCheck = (label, name, value) =>
    `<label class="cr-check"><input type="checkbox" data-field="${name}" ${Number(value) ? 'checked' : ''}> ${label}</label>`;
const crSelect = (label, name, value, options) =>
    `<label>${label}<select class="cr-input" data-field="${name}">${options.map(([v, text]) => `<option value="${crEsc(v)}" ${String(v) === String(value ?? '') ? 'selected' : ''}>${crEsc(text)}</option>`).join('')}</select></label>`;

function crParamInput(param, value) {
    const attrs = `class="cr-input" data-param="${param.id}"`;
    if (param.field_type === 'list') {
        const options = String(param.options || '').split(/[\n;]/).map(s => s.trim()).filter(Boolean);
        return `<select ${attrs}><option value=""></option>${options.map(o => `<option ${o === value ? 'selected' : ''}>${crEsc(o)}</option>`).join('')}</select>`;
    }
    if (param.field_type === 'bool') return `<input type="checkbox" data-param="${param.id}" ${value === 'Да' ? 'checked' : ''}>`;
    const type = { number: 'number', date: 'date' }[param.field_type] || 'text';
    return `<input ${attrs} type="${type}" value="${crEsc(value ?? '')}">`;
}

function crMainSectionHtml(c) {
    const typeOptions = [['0', '— не выбран —'], ...crState.docTypes.map(t => [String(t.id), t.name])];
    const folderOptions = [['0', 'Все (без папки)'], ...crState.meta.folders.map(f => [String(f.id), f.name])];
    const currencyOptions = [['RUB', 'рубль'], ['USD', 'доллар США'], ['EUR', 'евро'], ['CNY', 'юань'], ['KZT', 'тенге']];
    const custom = c.custom || {};
    return `
        <div class="cr-section-title">Основные</div>
        <div class="cr-form-grid">
            ${crField('Дата создания', 'created_date', c.created_date, 'date')}
            ${crField('Дата заключения', 'concluded_date', c.concluded_date, 'date')}
            ${crField('Дата окончания', 'end_date', c.end_date, 'date')}
            ${crSelect('Статус договора', 'status', c.status || 'draft', Object.entries(CR_STATUSES))}
            ${crField('Номер договора', 'number', c.number)}
            ${crField('Порядковый номер', 'seq_no', c.seq_no || '', 'number', 'min="0"')}
            ${crField('Входящий номер договора', 'incoming_number', c.incoming_number)}
            ${crField('Дополнительный номер', 'extra_number', c.extra_number)}
            ${crField('Номер гос. регистрации', 'gov_reg_number', c.gov_reg_number)}
            ${crField('Сумма', 'amount', c.amount || '', 'number', 'step="0.01" min="0"')}
            ${crSelect('Валюта', 'currency', c.currency || 'RUB', currencyOptions)}
            ${crCheck('НДС', 'vat_enabled', c.vat_enabled)}
            ${crField('Ставка НДС, %', 'vat_rate', c.vat_rate ?? 20, 'number', 'step="0.01" min="0"')}
            ${crCheck('Ручной ввод НДС', 'vat_manual', c.vat_manual)}
            ${crField('Сумма НДС', 'vat_amount', c.vat_amount || '', 'number', 'step="0.01" min="0"')}
            <label>Сумма без НДС<input class="cr-input" id="crNoVat" readonly></label>
        </div>
        <div class="cr-form-grid">
            ${crCheck('Для служебного пользования', 'internal_only', c.internal_only)}
            ${crCheck('Отсрочка платежа', 'payment_deferral', c.payment_deferral)}
            ${crCheck('Рамочный договор', 'framework', c.framework)}
            ${crCheck('Бессрочный договор', 'indefinite', c.indefinite)}
            ${crCheck('Пролонгация', 'prolongation', c.prolongation)}
            ${crField('Условия пролонгации', 'prolongation_terms', c.prolongation_terms, 'text', 'placeholder="например: автоматически на 1 год"')}
        </div>
        <div class="cr-form-grid">
            ${crField('Ответственный исполнитель', 'responsible', c.responsible, 'text', 'list="crUsersList"')}
            ${crField('Инициатор', 'initiator', c.initiator, 'text', 'list="crUsersList"')}
            ${crSelect('Тип договора', 'doc_type_id', c.doc_type_id || 0, typeOptions)}
            ${crSelect('Папка', 'folder_id', c.folder_id || 0, folderOptions)}
            ${crSelect('Вид договора', 'kind', c.kind || 'other', [['other', 'Другой'], ['expense', 'Расходный'], ['income', 'Доходный']])}
            ${crField('Тендер', 'tender', c.tender)}
            ${crField('Категория', 'category', c.category)}
            ${crCheck('Уведомлять об окончании', 'notify_enabled', c.notify_enabled)}
            ${crField('…за сколько дней', 'notify_days', c.notify_days || '', 'number', 'min="0"')}
            ${crField('Дата уведомления', 'notify_date', c.notify_date, 'date')}
        </div>
        <div class="cr-main-split">
            <div>
                <div class="cr-section-title">Подписание / рассмотрение</div>
                <div class="cr-form-grid cr-form-grid--3">
                    ${crCheck('На подписании у контрагента', 'on_counterparty_signing', c.on_counterparty_signing)}
                    ${crField('Дата передачи на подпись', 'sent_for_signing_date', c.sent_for_signing_date, 'date')}
                    ${crField('Дата подписания', 'signed_date', c.signed_date, 'date')}
                    ${crCheck('Подписан', 'signed', c.signed)}
                    ${crSelect('Способ подписания', 'signing_method', c.signing_method, CR_SIGNING_METHODS.map(v => [v, v || '— не выбран —']))}
                    ${crCheck('На рассмотрении у контрагента', 'on_counterparty_review', c.on_counterparty_review)}
                    ${crField('Дата отправки контрагенту', 'sent_to_counterparty_date', c.sent_to_counterparty_date, 'date')}
                    ${crSelect('Статус оригинала', 'original_status', c.original_status, CR_ORIGINAL_STATUSES.map(v => [v, v || '— не указан —']))}
                    ${crCheck('Отметка в реестре', 'flagged', c.flagged)}
                </div>
            </div>
            <div class="cr-params">
                <div class="cr-section-title">Пользовательские параметры</div>
                ${crState.params.length ? `<table class="cr-params-table">${crState.params.map(p => `
                    <tr><td>${crEsc(p.name)}</td><td>${crParamInput(p, custom[String(p.id)])}</td>
                    <td><button type="button" class="cr-link-danger" title="Удалить параметр у всех договоров" onclick="crDeleteParam(${p.id})">✕</button></td></tr>`).join('')}</table>`
                    : '<p class="cr-muted">Параметров нет. Нажми «Добавить польз. параметр» внизу.</p>'}
            </div>
        </div>
        <div class="cr-tabs">
            ${CR_MAIN_TABS.map(([key, label]) => `<button type="button" class="cr-keep ${crState.mainTab === key ? 'active' : ''}" onclick="crSwitchMainTab('${key}')">${label}</button>`).join('')}
        </div>
        ${CR_MAIN_TABS.map(([key]) => `<textarea class="cr-input cr-tab-text" data-field="${key}" rows="6" ${crState.mainTab === key ? '' : 'hidden'}>${crEsc(c[key])}</textarea>`).join('')}`;
}

function crSwitchMainTab(key) {
    crState.mainTab = key;
    const body = crState.cardModal?.querySelector('#crCardBody');
    body?.querySelectorAll('.cr-tab-text').forEach(el => { el.hidden = el.dataset.field !== key; });
    body?.querySelectorAll('.cr-tabs button').forEach(btn => btn.classList.toggle('active', btn.getAttribute('onclick').includes(`'${key}'`)));
}

function crBindMainSection(body) {
    const get = name => body.querySelector(`[data-field="${name}"]`);
    const recalc = () => {
        const amount = Number(get('amount').value || 0);
        const vatOn = get('vat_enabled').checked;
        const manual = get('vat_manual').checked;
        const rate = Number(get('vat_rate').value || 0);
        get('vat_rate').disabled = !vatOn;
        get('vat_manual').disabled = !vatOn;
        get('vat_amount').readOnly = !(vatOn && manual);
        if (vatOn && !manual) get('vat_amount').value = rate > 0 ? (amount * rate / (100 + rate)).toFixed(2) : '0.00';
        const vat = vatOn ? Number(get('vat_amount').value || 0) : 0;
        body.querySelector('#crNoVat').value = crMoney(amount - vat);
        get('end_date').disabled = get('indefinite').checked;
        get('prolongation_terms').disabled = !get('prolongation').checked;
    };
    body.querySelectorAll('[data-field], [data-param]').forEach(el => {
        el.addEventListener('input', () => { crState.cardDirty = true; recalc(); });
        el.addEventListener('change', () => { crState.cardDirty = true; recalc(); });
    });
    recalc();
}

function crCollectMain() {
    const body = crState.cardModal?.querySelector('#crCardBody');
    if (!body || !crState.card || crState.cardSection !== 'main') return;
    body.querySelectorAll('[data-field]').forEach(el => {
        crState.card[el.dataset.field] = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
    });
    const custom = { ...(crState.card.custom || {}) };
    body.querySelectorAll('[data-param]').forEach(el => {
        custom[el.dataset.param] = el.type === 'checkbox' ? (el.checked ? 'Да' : '') : el.value;
    });
    crState.card.custom = custom;
}

async function crSaveCard() {
    if (crState.cardSection === 'main') crCollectMain();
    const c = crState.card;
    if (!String(c.number || '').trim()) return customAlert('Номер договора не может быть пустым.');
    const fields = ['number', 'seq_no', 'extra_number', 'incoming_number', 'gov_reg_number', 'flagged', 'created_date', 'concluded_date', 'end_date',
        'amount', 'currency', 'vat_enabled', 'vat_rate', 'vat_manual', 'vat_amount', 'kind', 'responsible', 'initiator', 'tender', 'category',
        'notify_enabled', 'notify_days', 'notify_date', 'internal_only', 'payment_deferral', 'framework',
        'prolongation', 'prolongation_terms', 'indefinite', 'on_counterparty_signing', 'sent_for_signing_date', 'signed_date', 'signed',
        'signing_method', 'on_counterparty_review', 'sent_to_counterparty_date', 'original_status', 'doc_type_id', 'folder_id', 'status',
        ...CR_MAIN_TABS.map(([key]) => key), 'custom'];
    const payload = Object.fromEntries(fields.map(key => [key, c[key]]));
    const res = await apiCall(`/cr/contracts/${c.id}`, 'PUT', payload);
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось сохранить договор.'));
    crState.card = { ...c, ...res.contract };
    crState.cardDirty = false;
    crRenderCard();
    showToast('Договоры', 'Договор сохранён');
}

async function crReloadCard() {
    const fresh = await apiCall(`/cr/contracts/${crState.card.id}`);
    if (crFail(fresh)) return;
    if (crState.cardSection === 'main') crCollectMain();
    const keep = crState.cardDirty ? crState.card : {};
    crState.card = { ...fresh, ...keep, parties: fresh.parties, approvals: fresh.approvals, files: fresh.files, items: fresh.items, flags: fresh.flags, access_level: fresh.access_level };
    crRenderCard();
}

// ---- tab settings & custom params

function crOpenTabSettings() {
    const hidden = crHiddenSections();
    const modal = crModal('Настройка вкладок', `
        <p class="cr-hint">Сними галочки у разделов, которыми не пользуешься, — они пропадут из меню карточки. Настройка сохраняется в этом браузере.</p>
        <div class="cr-form-grid cr-form-grid--2">
            ${CR_SECTIONS.filter(([key]) => key !== 'main').map(([key, label]) => `<label class="cr-check"><input type="checkbox" data-sec="${key}" ${hidden.has(key) ? '' : 'checked'}> ${label}</label>`).join('')}
        </div>`,
        `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button><button class="btn-primary" type="button" data-act="ok">Применить</button>`);
    modal.querySelector('[data-act="cancel"]').onclick = () => modal.closeModal();
    modal.querySelector('[data-act="ok"]').onclick = () => {
        const next = [...modal.querySelectorAll('[data-sec]')].filter(el => !el.checked).map(el => el.dataset.sec);
        try { localStorage.setItem(CR_HIDDEN_KEY, JSON.stringify(next)); } catch (e) { /* private mode: setting just won't persist */ }
        modal.closeModal();
        if (next.includes(crState.cardSection)) crState.cardSection = 'main';
        crRenderCard();
    };
}

function crOpenParamDialog() {
    const modal = crModal('Новый пользовательский параметр', `
        <div class="cr-form-grid cr-form-grid--2">
            <label class="cr-span-2">Название<input class="cr-input" id="crParamName" placeholder="Например: Срок исполнения обязательств"></label>
            <label>Тип<select class="cr-input" id="crParamType">
                <option value="text">Текст</option><option value="number">Число</option><option value="date">Дата</option>
                <option value="list">Список значений</option><option value="bool">Да / нет</option></select></label>
            <label>Значения списка<input class="cr-input" id="crParamOptions" placeholder="через ; — только для типа «Список»"></label>
        </div>
        <p class="cr-hint">Параметр появится во всех договорах в блоке «Пользовательские параметры».</p>`,
        `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button><button class="btn-primary" type="button" data-act="ok">Добавить</button>`);
    modal.querySelector('[data-act="cancel"]').onclick = () => modal.closeModal();
    modal.querySelector('[data-act="ok"]').onclick = async () => {
        const res = await apiCall('/cr/params', 'POST', {
            name: modal.querySelector('#crParamName').value.trim(),
            field_type: modal.querySelector('#crParamType').value,
            options: modal.querySelector('#crParamOptions').value,
        });
        if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось добавить параметр.'));
        modal.closeModal();
        if (crState.cardSection === 'main') crCollectMain();
        await crLoadParams();
        crState.cardSection = 'main';
        crRenderCard();
    };
}

async function crDeleteParam(paramId) {
    if (!(await customConfirm('Удалить параметр из всех договоров? Введённые значения перестанут показываться.'))) return;
    crCollectMain();
    await apiCall(`/cr/params/${paramId}`, 'DELETE');
    await crLoadParams();
    crRenderCard();
}

// ---- generic sections (payments, stages, claims...)

function crItemInput(col, value) {
    const [key, label, type, options] = col;
    const attrs = `class="cr-input" data-item="${key}"`;
    if (type === 'select') {
        const opts = options.map(o => Array.isArray(o) ? o : [o, o]);
        return `<label>${label}<select ${attrs}>${opts.map(([v, t]) => `<option value="${crEsc(v)}" ${String(v) === String(value ?? '') ? 'selected' : ''}>${crEsc(t)}</option>`).join('')}</select></label>`;
    }
    if (type === 'useremail') {
        return `<label>${label}<select ${attrs}><option value="">— выбери —</option>${crState.users.map(u => `<option value="${crEsc(String(u.email).toLowerCase())}" ${String(u.email).toLowerCase() === String(value || '') ? 'selected' : ''}>${crEsc(u.name || u.email)} (${crEsc(u.email)})</option>`).join('')}</select></label>`;
    }
    const inputType = { date: 'date', money: 'number' }[type] || 'text';
    return `<label>${label}<input ${attrs} type="${inputType}" ${type === 'money' ? 'step="0.01"' : ''} ${type === 'user' ? 'list="crUsersList"' : ''} value="${crEsc(value ?? '')}"></label>`;
}

function crItemCell(col, value) {
    const [, , type, options] = col;
    if (type === 'date') return crDate(value);
    if (type === 'money') return value === '' || value === undefined ? '' : crMoney(value);
    if (type === 'select' && Array.isArray(options?.[0])) return crEsc((options.find(([v]) => v === value) || [value, value])[1]);
    if (type === 'useremail') {
        const user = crState.users.find(u => String(u.email).toLowerCase() === String(value || '').toLowerCase());
        return crEsc(user ? `${user.name || user.email}` : value);
    }
    return crEsc(value);
}

function crItemSectionHtml(contract, section) {
    const schema = CR_ITEM_SECTIONS[section];
    const rows = contract.items[section] || [];
    const editing = crState.editingItem && crState.editingItem.section === section ? crState.editingItem : null;
    const values = editing ? rows.find(r => r.id === editing.id) || {} : {};
    const totals = (schema.totals || []).map(key => {
        const col = schema.cols.find(c => c[0] === key);
        return `${col[1]}: <strong>${crMoney(rows.reduce((acc, r) => acc + Number(r[key] || 0), 0))}</strong>`;
    }).join(' · ');
    const accessHint = section === 'access'
        ? '<p class="cr-hint">Если список пуст — договор видят все сотрудники с доступом к документам. Если добавить хотя бы одного человека — договор видят только директор, автор договора и люди из списка.</p>' : '';
    return `
        <div class="cr-section-title">${schema.title}</div>
        ${accessHint}
        <div class="cr-form-grid cr-item-form">${schema.cols.map(col => crItemInput(col, values[col[0]])).join('')}</div>
        <div class="cr-toolbar-group">
            <button class="btn-primary" type="button" onclick="crSaveItem('${section}')">${editing ? 'Сохранить строку' : 'Добавить'}</button>
            ${editing ? `<button class="btn-secondary" type="button" onclick="crCancelItemEdit()">Отмена</button>` : ''}
            <button class="btn-secondary cr-keep" type="button" onclick="crExportItems('${section}')">Excel</button>
        </div>
        <div class="cr-table-wrap">
            <table class="cr-table"><thead><tr><th>№</th>${schema.cols.map(c => `<th>${c[1]}</th>`).join('')}<th>Добавил</th><th></th></tr></thead>
            <tbody>${rows.length ? rows.map((r, i) => `
                <tr class="${editing && editing.id === r.id ? 'cr-row--selected' : ''}" ondblclick="crEditItem('${section}', ${r.id})">
                    <td>${i + 1}</td>${schema.cols.map(c => `<td class="${c[2] === 'money' ? 'cr-num' : ''}">${crItemCell(c, r[c[0]])}</td>`).join('')}
                    <td class="cr-muted">${crEsc(r.created_by)}</td>
                    <td class="cr-actions"><button type="button" onclick="crEditItem('${section}', ${r.id})">Изменить</button><button type="button" class="cr-link-danger" onclick="crDeleteItem(${r.id})">Удалить</button></td>
                </tr>`).join('') : `<tr><td colspan="${schema.cols.length + 3}" class="cr-empty">Записей нет.</td></tr>`}</tbody></table>
        </div>
        ${totals ? `<div class="cr-footer">${totals}</div>` : ''}`;
}

function crEditItem(section, id) {
    crState.editingItem = { section, id };
    crRenderCard();
}

function crCancelItemEdit() {
    crState.editingItem = null;
    crRenderCard();
}

async function crSaveItem(section) {
    const body = crState.cardModal.querySelector('#crCardBody');
    const data = {};
    body.querySelectorAll('[data-item]').forEach(el => {
        const col = CR_ITEM_SECTIONS[section].cols.find(c => c[0] === el.dataset.item);
        data[el.dataset.item] = col && col[2] === 'money' && el.value !== '' ? Number(el.value) : el.value.trim();
    });
    if (!Object.values(data).some(v => v !== '' && v !== undefined)) return customAlert('Заполни хотя бы одно поле.');
    const editing = crState.editingItem && crState.editingItem.section === section ? crState.editingItem : null;
    const res = editing
        ? await apiCall(`/cr/items/${editing.id}`, 'PUT', { data })
        : await apiCall(`/cr/contracts/${crState.card.id}/items`, 'POST', { section, data });
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось сохранить запись.'));
    crState.editingItem = null;
    crReloadCard();
}

async function crDeleteItem(itemId) {
    if (!(await customConfirm('Удалить запись?'))) return;
    const res = await apiCall(`/cr/items/${itemId}`, 'DELETE');
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось удалить запись.'));
    crState.editingItem = null;
    crReloadCard();
}

function crExportItems(section) {
    if (typeof XLSX === 'undefined') return customAlert('Выгрузка сейчас недоступна.');
    const schema = CR_ITEM_SECTIONS[section];
    const rows = (crState.card.items[section] || []).map(r => Object.fromEntries(schema.cols.map(c => [c[1], c[2] === 'money' ? Number(r[c[0]] || 0) : (c[2] === 'date' ? crDate(r[c[0]]) : r[c[0]] ?? '')])));
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.json_to_sheet(rows), schema.title.slice(0, 30).replace(/[\\/?*[\]:]/g, ' '));
    XLSX.writeFile(book, `${schema.title.replace(/[\\/:*?"<>|]/g, ' ')} ${crState.card.number.replace(/[\\/:*?"<>|]/g, '_')}.xlsx`);
}

// ---- profitability & charts

function crSum(rows, key, filter = () => true) {
    return (rows || []).filter(filter).reduce((acc, r) => acc + Number(r[key] || 0), 0);
}

function crProfitData(c) {
    const items = c.items || {};
    const base = Number(c.amount || 0) - (Number(c.vat_enabled) ? Number(c.vat_amount || 0) : 0);
    const supplements = crSum(items.supplements, 'amount_change');
    const contractValue = base + supplements;
    const costs = crSum(items.costs, 'amount');
    const subcontracts = crSum(items.subcontracts, 'amount');
    const payIn = crSum(items.payments, 'fact_amount', r => r.direction !== 'Исходящий');
    const payOut = crSum(items.payments, 'fact_amount', r => r.direction === 'Исходящий');
    const planIn = crSum(items.payments, 'plan_amount', r => r.direction !== 'Исходящий');
    const penalties = crSum(items.payments, 'fact_amount', r => ['Неустойка', 'Штраф', 'Пени'].includes(r.kind));
    const expenses = costs + subcontracts;
    const profit = c.kind === 'expense' ? -(contractValue + expenses) : contractValue - expenses;
    return { base, supplements, contractValue, costs, subcontracts, expenses, payIn, payOut, planIn, penalties, profit,
        margin: contractValue ? (profit / contractValue) * 100 : 0 };
}

function crProfitHtml(c) {
    const d = crProfitData(c);
    const row = (label, value, strong = false) => `<tr><td>${label}</td><td class="cr-num">${strong ? '<strong>' : ''}${crMoney(value)}${strong ? '</strong>' : ''}</td></tr>`;
    return `
        <div class="cr-section-title">Рентабельность договора</div>
        <div class="cr-kpis">
            <div><span>Стоимость договора без НДС</span><strong>${crMoney(d.contractValue)}</strong></div>
            <div><span>Расходы (затраты + субподряды)</span><strong>${crMoney(d.expenses)}</strong></div>
            <div><span>${c.kind === 'expense' ? 'Итого расходов по договору' : 'Прибыль'}</span><strong class="${d.profit < 0 ? 'cr-neg' : 'cr-pos'}">${crMoney(d.profit)}</strong></div>
            <div><span>Рентабельность</span><strong>${c.kind === 'expense' ? '—' : `${d.margin.toFixed(1)} %`}</strong></div>
        </div>
        <table class="cr-table cr-table--compact">
            ${row('Сумма договора без НДС', d.base)}
            ${row('Изменения по доп. соглашениям', d.supplements)}
            ${row('Затраты', d.costs)}
            ${row('Субподряды', d.subcontracts)}
            ${row('Поступило оплат (факт)', d.payIn)}
            ${row('Ожидается поступлений (план)', d.planIn)}
            ${row('Оплачено нами (факт)', d.payOut)}
            ${row('Неустойки, штрафы, пени', d.penalties)}
            ${row(c.kind === 'expense' ? 'Итого расходов' : 'Прибыль', d.profit, true)}
        </table>
        <p class="cr-hint">Считается по разделам «Платежи и неустойка», «Затраты», «Субподряды» и «Доп. соглашения». Вид договора «Расходный» показывает итог расходов вместо прибыли.</p>`;
}

function crChartsHtml() {
    return `
        <div class="cr-section-title">Диаграммы</div>
        <div class="cr-charts">
            <div><h4>Платежи по месяцам: план и факт</h4><div class="cr-chart-box"><canvas id="crChartPayments"></canvas></div></div>
            <div><h4>Структура расходов</h4><div class="cr-chart-box"><canvas id="crChartCosts"></canvas></div></div>
        </div>
        <p class="cr-hint" id="crChartsHint"></p>`;
}

function crDrawCharts(c) {
    const hint = document.getElementById('crChartsHint');
    if (typeof Chart === 'undefined') { if (hint) hint.textContent = 'Библиотека диаграмм не загрузилась.'; return; }
    const payments = c.items.payments || [];
    const months = new Map();
    const bump = (date, key, value) => {
        if (!date) return;
        const month = String(date).slice(0, 7);
        if (!months.has(month)) months.set(month, { plan: 0, fact: 0 });
        months.get(month)[key] += Number(value || 0);
    };
    payments.forEach(p => { bump(p.plan_date, 'plan', p.plan_amount); bump(p.fact_date, 'fact', p.fact_amount); });
    const labels = [...months.keys()].sort();
    (crState.charts || []).forEach(chart => chart.destroy());
    crState.charts = [];
    crState.charts.push(new Chart(document.getElementById('crChartPayments'), {
        type: 'bar',
        data: { labels: labels.map(m => m.split('-').reverse().join('.')), datasets: [
            { label: 'План', data: labels.map(m => months.get(m).plan), backgroundColor: '#9cc9c3' },
            { label: 'Факт', data: labels.map(m => months.get(m).fact), backgroundColor: '#0f766e' }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { datalabels: { display: false } } },
    }));
    const byArticle = {};
    (c.items.costs || []).forEach(r => { byArticle[r.article || 'Без статьи'] = (byArticle[r.article || 'Без статьи'] || 0) + Number(r.amount || 0); });
    const subTotal = crSum(c.items.subcontracts, 'amount');
    if (subTotal) byArticle['Субподряды'] = subTotal;
    const palette = ['#0f766e', '#d97706', '#2563eb', '#c2413b', '#7c3aed', '#059669', '#64748b'];
    crState.charts.push(new Chart(document.getElementById('crChartCosts'), {
        type: 'doughnut',
        data: { labels: Object.keys(byArticle), datasets: [{ data: Object.values(byArticle), backgroundColor: Object.keys(byArticle).map((_, i) => palette[i % palette.length]) }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { datalabels: { display: false } } },
    }));
    if (hint) hint.textContent = !labels.length && !Object.keys(byArticle).length ? 'Данных пока нет: заполни разделы «Платежи и неустойка» и «Затраты».' : '';
}

// ---- parties

function crPartiesSectionHtml(c) {
    return `
        <div class="cr-section-title">Контрагенты (стороны договора)</div>
        <div class="cr-form-grid cr-form-grid--party">
            <label class="cr-span-2">Контрагент<select class="cr-input" id="crPartyCounterparty">${crCounterpartyOptions(0, '— выбери контрагента —')}</select></label>
            <label>Роль<select class="cr-input" id="crPartyRole">${CR_ROLES.map(r => `<option>${r}</option>`).join('')}</select></label>
            <label class="cr-check"><input type="checkbox" id="crPartyMailing"> Участвует в авторассылке</label>
        </div>
        <div class="cr-toolbar-group">
            <button class="btn-primary" type="button" onclick="crAddParty()">Добавить сторону</button>
            <button class="btn-secondary" type="button" onclick="crOpenCounterparty(0, crAfterCounterpartyCreated)">+ Новый контрагент</button>
            <button class="btn-secondary cr-keep" type="button" onclick="crExportParties()">Excel</button>
            <button class="btn-secondary cr-keep" type="button" onclick="crPrintEnvelope()">Печать конверта</button>
        </div>
        <div class="cr-table-wrap">
            <table class="cr-table"><thead><tr><th></th><th>Контрагент (сторона договора)</th><th>Роль</th><th>ИНН</th><th>КПП</th><th>Авторассылка</th><th></th></tr></thead>
            <tbody>${c.parties.length ? c.parties.map(p => `
                <tr ondblclick="crOpenCounterparty(${p.counterparty_id})">
                    <td><input type="radio" name="crEnvelopeParty" value="${p.id}" class="cr-keep" title="Для печати конверта"></td>
                    <td class="cr-wrap">${crEsc(p.name)}</td>
                    <td><select class="cr-input cr-input--sm" onchange="crUpdateParty(${p.id}, this.value, this.closest('tr').querySelector('input[type=checkbox]').checked ? 1 : 0)">${CR_ROLES.map(r => `<option ${r === p.role ? 'selected' : ''}>${r}</option>`).join('')}${CR_ROLES.includes(p.role) || !p.role ? '' : `<option selected>${crEsc(p.role)}</option>`}</select></td>
                    <td>${crEsc(p.inn)}</td><td>${crEsc(p.kpp)}</td>
                    <td><input type="checkbox" ${Number(p.auto_mailing) ? 'checked' : ''} onchange="crUpdateParty(${p.id}, this.closest('tr').querySelector('select').value, this.checked ? 1 : 0)"></td>
                    <td><button class="cr-link-danger" type="button" onclick="crDeleteParty(${p.id})">Удалить</button></td>
                </tr>`).join('') : '<tr><td colspan="7" class="cr-empty">Стороны не указаны.</td></tr>'}</tbody></table>
        </div>
        <p class="cr-hint">Двойной щелчок по строке откроет карточку контрагента. Для печати конверта отметь получателя кружком слева.</p>`;
}

async function crAfterCounterpartyCreated(id) {
    await crLoadCounterparties();
    crRenderCard();
    const select = document.getElementById('crPartyCounterparty');
    if (select && id) select.value = String(id);
}

async function crAddParty() {
    const counterpartyId = Number(document.getElementById('crPartyCounterparty')?.value || 0);
    if (!counterpartyId) return customAlert('Выбери контрагента или создай нового.');
    const res = await apiCall(`/cr/contracts/${crState.card.id}/parties`, 'POST', {
        counterparty_id: counterpartyId,
        role: document.getElementById('crPartyRole').value,
        auto_mailing: document.getElementById('crPartyMailing').checked ? 1 : 0,
    });
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось добавить сторону.'));
    crReloadCard();
}

async function crUpdateParty(partyId, role, autoMailing) {
    const res = await apiCall(`/cr/parties/${partyId}`, 'PUT', { role, auto_mailing: autoMailing });
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось изменить сторону.'));
    crReloadCard();
}

async function crDeleteParty(partyId) {
    if (!(await customConfirm('Убрать контрагента из договора?'))) return;
    await apiCall(`/cr/parties/${partyId}`, 'DELETE');
    crReloadCard();
}

function crExportParties() {
    if (typeof XLSX === 'undefined') return customAlert('Выгрузка сейчас недоступна.');
    const rows = crState.card.parties.map(p => ({ 'Контрагент': p.name, 'Роль': p.role, 'ИНН': p.inn, 'КПП': p.kpp, 'Адрес': p.legal_address, 'Авторассылка': Number(p.auto_mailing) ? 'да' : 'нет' }));
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.json_to_sheet(rows), 'Стороны');
    XLSX.writeFile(book, `Стороны договора ${crState.card.number.replace(/[\\/:*?"<>|]/g, '_')}.xlsx`);
}

function crPrintEnvelope() {
    const c = crState.card;
    const pickedId = Number(document.querySelector('input[name="crEnvelopeParty"]:checked')?.value || 0);
    const recipient = c.parties.find(p => p.id === pickedId) || c.parties.find(p => p.role !== 'Наша организация');
    if (!recipient) return customAlert('Добавь контрагента в договор или отметь получателя кружком.');
    const sender = c.parties.find(p => p.role === 'Наша организация' && p.id !== recipient.id);
    if (!recipient.legal_address) customAlert('У получателя не заполнен адрес — конверт напечатается без него. Адрес можно указать в карточке контрагента.');
    crPrintWindow(`Конверт ${recipient.name}`, `
        <style>@page{size:220mm 110mm;margin:0}body{margin:0}.env{width:220mm;height:110mm;position:relative;font:14px Arial,sans-serif}
        .from{position:absolute;left:12mm;top:10mm;width:90mm;font-size:12px}.to{position:absolute;right:14mm;bottom:16mm;width:105mm;font-size:15px;line-height:1.5}
        .lbl{font-size:10px;color:#555;text-transform:uppercase}</style>
        <div class="env">
            <div class="from"><div class="lbl">От кого</div>${crEsc(sender?.name || '')}<br>${crEsc(sender?.legal_address || '')}</div>
            <div class="to"><div class="lbl">Кому</div><strong>${crEsc(recipient.name)}</strong><br>${crEsc(recipient.legal_address || '')}</div>
        </div>`, false, true);
}

// ---- approvals

function crApprovalsSectionHtml(c) {
    const today = crToday();
    const time = ts => ts ? new Date(ts * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '';
    return `
        <div class="cr-section-title">Согласования</div>
        <div class="cr-form-grid cr-form-grid--party">
            <label>Согласующий<input class="cr-input" id="crApprover" list="crUsersList" placeholder="ФИО"></label>
            <label>Отдел<input class="cr-input" id="crApproverDept" placeholder="Юридический отдел"></label>
            <label>Должность<input class="cr-input" id="crApproverPos" placeholder="Юрист"></label>
            <label>Согласовать до<input class="cr-input" id="crApproverDue" type="date"></label>
        </div>
        <div class="cr-toolbar-group">
            <button class="btn-primary" type="button" onclick="crAddApproval()">Добавить в лист согласования</button>
            <button class="btn-secondary" type="button" onclick="crOpenApprovalTemplates()">Шаблоны листа согласования</button>
            <button class="btn-secondary cr-keep" type="button" onclick="crPrintApprovals()">Печать листа согласования</button>
            <button class="btn-secondary cr-keep" type="button" onclick="crExportApprovals()">Excel</button>
        </div>
        <div class="cr-table-wrap">
            <table class="cr-table"><thead><tr><th>№</th><th>Дата согласования</th><th>Время факт.</th><th>Согласующий</th><th>Отдел</th><th>Должность</th><th>Срок</th><th>Состояние</th><th>Комментарий</th><th></th></tr></thead>
            <tbody>${c.approvals.length ? c.approvals.map((a, i) => `
                <tr class="${a.status === 'pending' && a.due_date && a.due_date < today ? 'cr-row--appr-overdue' : ''}">
                    <td>${i + 1}</td>
                    <td>${a.decided_at ? new Date(a.decided_at * 1000).toLocaleDateString('ru-RU') : ''}</td>
                    <td>${time(a.decided_at)}</td>
                    <td>${crEsc(a.approver)}</td><td>${crEsc(a.department)}</td><td>${crEsc(a.position)}</td>
                    <td>${crDate(a.due_date)}</td>
                    <td><span class="cr-status cr-status--${a.status}">${CR_APPROVAL_LABELS[a.status] || a.status}</span></td>
                    <td class="cr-wrap">${crEsc(a.comment)}</td>
                    <td class="cr-actions">
                        ${a.status === 'pending' ? `
                            <button type="button" onclick="crDecide(${a.id}, 'approved')">Согласовать</button>
                            <button type="button" onclick="crDecide(${a.id}, 'approved_with_notes')">С замечаниями</button>
                            <button type="button" onclick="crDecide(${a.id}, 'rejected')">Отклонить</button>` : `
                            <button type="button" onclick="crDecide(${a.id}, 'pending')">Вернуть в процесс</button>`}
                        <button type="button" class="cr-link-danger" onclick="crDeleteApproval(${a.id})">Удалить</button>
                    </td>
                </tr>`).join('') : '<tr><td colspan="10" class="cr-empty">Лист согласования пуст. Добавь согласующих или примени шаблон.</td></tr>'}</tbody></table>
        </div>`;
}

async function crAddApproval() {
    const approver = document.getElementById('crApprover').value.trim();
    if (!approver) return customAlert('Укажи согласующего.');
    const res = await apiCall(`/cr/contracts/${crState.card.id}/approvals`, 'POST', {
        approver,
        department: document.getElementById('crApproverDept').value.trim(),
        position: document.getElementById('crApproverPos').value.trim(),
        due_date: document.getElementById('crApproverDue').value,
    });
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось добавить согласующего.'));
    crReloadCard();
}

async function crDecide(approvalId, status) {
    let comment = '';
    if (status === 'approved_with_notes' || status === 'rejected') {
        comment = await crPromptName(status === 'rejected' ? 'Причина отклонения' : 'Замечания');
        if (comment === null) return;
    }
    const res = await apiCall(`/cr/approvals/${approvalId}`, 'PUT', { status, comment });
    if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось сохранить решение.'));
    crReloadCard();
}

async function crDeleteApproval(approvalId) {
    if (!(await customConfirm('Удалить строку из листа согласования?'))) return;
    await apiCall(`/cr/approvals/${approvalId}`, 'DELETE');
    crReloadCard();
}

async function crOpenApprovalTemplates() {
    const res = await apiCall('/cr/approval_templates');
    const templates = crFail(res) ? [] : res;
    const modal = crModal('Шаблоны листа согласования', `
        <p class="cr-hint">Шаблон — готовый список согласующих (например: юрист → бухгалтерия → директор). Применение добавит их всех в этот договор.</p>
        <div class="cr-table-wrap cr-table-wrap--modal">
            <table class="cr-table"><thead><tr><th>Шаблон</th><th>Согласующие</th><th></th></tr></thead>
            <tbody>${templates.length ? templates.map(t => `
                <tr><td><strong>${crEsc(t.name)}</strong></td><td class="cr-wrap">${t.rows.map(r => crEsc([r.approver, r.position].filter(Boolean).join(', '))).join(' → ')}</td>
                <td class="cr-actions"><button type="button" data-apply="${t.id}">Применить</button><button type="button" class="cr-link-danger" data-del="${t.id}">Удалить</button></td></tr>`).join('')
                : '<tr><td colspan="3" class="cr-empty">Шаблонов пока нет.</td></tr>'}</tbody></table>
        </div>
        <div class="cr-form-grid cr-form-grid--2">
            <label>Срок согласования для применяемого шаблона<input class="cr-input" type="date" id="crTplDue"></label>
            <label>Сохранить текущий лист как шаблон<span class="cr-input-row"><input class="cr-input" id="crTplName" placeholder="Название шаблона"><button class="btn-secondary" type="button" data-act="save">Сохранить</button></span></label>
        </div>`, '', { wide: true });
    modal.querySelectorAll('[data-apply]').forEach(btn => btn.onclick = async () => {
        const r = await apiCall(`/cr/contracts/${crState.card.id}/approvals/apply_template`, 'POST', { template_id: Number(btn.dataset.apply), due_date: modal.querySelector('#crTplDue').value });
        if (crFail(r)) return customAlert(crErrorText(r, 'Не удалось применить шаблон.'));
        modal.closeModal();
        crReloadCard();
    });
    modal.querySelectorAll('[data-del]').forEach(btn => btn.onclick = async () => {
        if (!(await customConfirm('Удалить шаблон?'))) return;
        await apiCall(`/cr/approval_templates/${btn.dataset.del}`, 'DELETE');
        modal.closeModal();
        crOpenApprovalTemplates();
    });
    modal.querySelector('[data-act="save"]').onclick = async () => {
        const name = modal.querySelector('#crTplName').value.trim();
        if (!name) return customAlert('Укажи название шаблона.');
        const r = await apiCall('/cr/approval_templates', 'POST', { name, contract_id: crState.card.id });
        if (crFail(r)) return customAlert(crErrorText(r, 'Не удалось сохранить шаблон.'));
        modal.closeModal();
        showToast('Согласования', 'Шаблон сохранён');
        crOpenApprovalTemplates();
    };
}

function crExportApprovals() {
    if (typeof XLSX === 'undefined') return customAlert('Выгрузка сейчас недоступна.');
    const rows = crState.card.approvals.map((a, i) => ({
        '№': i + 1, 'Дата согласования': a.decided_at ? new Date(a.decided_at * 1000).toLocaleString('ru-RU') : '',
        'Согласующий': a.approver, 'Отдел': a.department, 'Должность': a.position, 'Срок': crDate(a.due_date),
        'Состояние': CR_APPROVAL_LABELS[a.status] || a.status, 'Комментарий': a.comment,
    }));
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.json_to_sheet(rows), 'Согласования');
    XLSX.writeFile(book, `Согласования ${crState.card.number.replace(/[\\/:*?"<>|]/g, '_')}.xlsx`);
}

// ---- files

function crFilesSectionHtml(c) {
    const size = bytes => bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`;
    return `
        <div class="cr-section-title">Файлы договора</div>
        <div class="cr-toolbar-group">
            <label class="btn-primary cr-upload">Загрузить файл<input type="file" multiple onchange="crUploadFiles(this)"></label>
            <span class="cr-muted">До 25 МБ на файл. Текст из PDF, DOCX и TXT индексируется — по нему работает поиск «По файлам» в реестре.</span>
        </div>
        <div class="cr-table-wrap">
            <table class="cr-table"><thead><tr><th>Файл</th><th>Размер</th><th>Загрузил</th><th>Дата</th><th></th></tr></thead>
            <tbody>${c.files.length ? c.files.map(f => `
                <tr>
                    <td class="cr-wrap"><a href="${crEsc(f.file_url)}" target="_blank" rel="noopener">${crEsc(f.filename)}</a></td>
                    <td>${size(Number(f.size_bytes || 0))}</td><td>${crEsc(f.uploaded_by)}</td>
                    <td>${new Date(f.created_at * 1000).toLocaleString('ru-RU')}</td>
                    <td><button class="cr-link-danger" type="button" onclick="crDeleteFile(${f.id})">Удалить</button></td>
                </tr>`).join('') : '<tr><td colspan="5" class="cr-empty">Файлов пока нет.</td></tr>'}</tbody></table>
        </div>`;
}

async function crUploadFiles(input) {
    const files = [...(input.files || [])];
    for (const file of files) {
        const form = new FormData();
        form.append('file', file);
        const res = await apiCall(`/cr/contracts/${crState.card.id}/files`, 'POST', form);
        if (crFail(res)) customAlert(`${file.name}: ${crErrorText(res, 'не загрузился')}`);
    }
    input.value = '';
    crReloadCard();
}

async function crDeleteFile(fileId) {
    if (!(await customConfirm('Удалить файл из договора?'))) return;
    await apiCall(`/cr/files/${fileId}`, 'DELETE');
    crReloadCard();
}

// ---- print

function crPrintWindow(title, html, landscape = false, bare = false) {
    const win = window.open('', '_blank');
    if (!win) return customAlert('Браузер заблокировал окно печати. Разреши всплывающие окна для сайта.');
    const base = bare ? '' : `body{font:13px/1.45 Arial,sans-serif;color:#111;margin:24px}h1{font-size:18px}table{border-collapse:collapse;width:100%;margin:10px 0}
        td,th{border:1px solid #999;padding:5px 7px;text-align:left;vertical-align:top}th{background:#f1f1f1}.k{width:34%;color:#444}${landscape ? '@page{size:landscape}' : ''}`;
    win.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${crEsc(title)}</title><style>${base}</style></head>
        <body>${html}<script>window.onload=()=>window.print()<\/script></body></html>`);
    win.document.close();
}

function crPrintCard() {
    if (crState.cardSection === 'main') crCollectMain();
    const c = crState.card;
    const row = (k, v) => v ? `<tr><td class="k">${k}</td><td>${crEsc(v)}</td></tr>` : '';
    const custom = c.custom || {};
    crPrintWindow(`Договор ${c.number}`, `<h1>Карточка договора № ${crEsc(c.number)}</h1><table>
        ${row('Тип документа', c.doc_type_name)}${row('Статус', CR_STATUSES[c.status])}${row('Дата создания', crDate(c.created_date))}${row('Дата заключения', crDate(c.concluded_date))}
        ${row('Дата окончания', c.indefinite ? 'бессрочный' : crDate(c.end_date))}${row('Входящий номер', c.incoming_number)}${row('Доп. номер', c.extra_number)}
        ${row('Сумма', `${crMoney(c.amount)} ${c.currency}`)}${row('НДС', Number(c.vat_enabled) ? `${c.vat_rate}% — ${crMoney(c.vat_amount)}` : 'без НДС')}
        ${row('Ответственный', c.responsible)}${row('Инициатор', c.initiator)}
        ${CR_MAIN_TABS.map(([key, label]) => row(label, c[key])).join('')}
        ${crState.params.map(p => row(p.name, custom[String(p.id)])).join('')}</table>
        <h1>Стороны</h1><table><tr><th>Контрагент</th><th>Роль</th><th>ИНН</th></tr>
        ${c.parties.map(p => `<tr><td>${crEsc(p.name)}</td><td>${crEsc(p.role)}</td><td>${crEsc(p.inn)}</td></tr>`).join('')}</table>`);
}

function crPrintApprovals() {
    const c = crState.card;
    crPrintWindow(`Лист согласования ${c.number}`, `<h1>Лист согласования договора № ${crEsc(c.number)}</h1>
        <p>${crEsc(c.doc_type_name || '')}${c.parties.length ? ` · ${c.parties.map(p => crEsc(p.name)).join(', ')}` : ''}</p>
        <table><tr><th>№</th><th>Согласующий</th><th>Отдел</th><th>Должность</th><th>Состояние</th><th>Дата</th><th>Комментарий</th><th>Подпись</th></tr>
        ${c.approvals.map((a, i) => `<tr><td>${i + 1}</td><td>${crEsc(a.approver)}</td><td>${crEsc(a.department)}</td><td>${crEsc(a.position)}</td>
        <td>${CR_APPROVAL_LABELS[a.status] || ''}</td><td>${a.decided_at ? new Date(a.decided_at * 1000).toLocaleString('ru-RU') : ''}</td><td>${crEsc(a.comment)}</td><td></td></tr>`).join('')}</table>`);
}

// ---------- counterparties ----------

function crSwitchPageTab(tab) {
    crState.pageTab = tab;
    const isContracts = tab === 'contracts';
    document.getElementById('crTabContracts')?.classList.toggle('active', isContracts);
    document.getElementById('crTabCounterparties')?.classList.toggle('active', !isContracts);
    ['crPanelContracts', 'crActionsContracts'].forEach(id => { const el = document.getElementById(id); if (el) el.hidden = !isContracts; });
    ['crPanelCounterparties', 'crActionsCounterparties'].forEach(id => { const el = document.getElementById(id); if (el) el.hidden = isContracts; });
    const status = document.getElementById('crInnStatus');
    if (status) status.textContent = '';
    if (isContracts) renderContractRegistry();
    else renderCounterparties();
}

async function renderCounterparties() {
    await crLoadCounterparties();
    crRenderCounterparties();
}

function crRenderCounterparties() {
    const body = document.getElementById('crCounterpartyBody');
    if (!body) return;
    const query = (document.getElementById('crCounterpartySearch')?.value || '').trim().toLowerCase();
    const rows = crState.counterparties.filter(p => !query || `${p.name} ${p.short_name} ${p.inn} ${p.ogrn}`.toLowerCase().includes(query));
    body.innerHTML = rows.length ? rows.map(p => `
        <tr onclick="crOpenCounterparty(${p.id})">
            <td><strong>${crEsc(p.short_name || p.name)}</strong>${Number(p.is_own) ? ' <span class="cr-badge">наша</span>' : ''}${p.short_name && p.short_name !== p.name ? `<div class="cr-muted">${crEsc(p.name)}</div>` : ''}</td>
            <td>${crEsc(p.inn)}</td><td>${crEsc(p.kpp)}</td><td>${crEsc(p.ogrn)}</td><td class="cr-wrap">${crEsc(p.legal_address)}</td>
            <td>${crEsc(p.director)}</td><td>${crEsc(p.status)}</td><td class="cr-num">${p.contracts_count || 0}</td>
        </tr>`).join('') : `<tr><td colspan="8" class="cr-empty">${query ? 'Ничего не найдено.' : 'Контрагентов пока нет. Найди организацию по ИНН или добавь вручную.'}</td></tr>`;
}

async function crLookupInn() {
    const input = document.getElementById('crInnQuery');
    const status = document.getElementById('crInnStatus');
    const inn = (input?.value || '').replace(/\D+/g, '');
    if (inn.length !== 10 && inn.length !== 12) {
        status.textContent = 'ИНН должен содержать 10 или 12 цифр.';
        return;
    }
    const existing = crState.counterparties.find(p => p.inn === inn);
    if (existing) {
        status.textContent = 'Такой контрагент уже есть в справочнике.';
        return crOpenCounterparty(existing.id);
    }
    status.textContent = 'Ищем…';
    const res = await apiCall(`/cr/counterparties/lookup?inn=${encodeURIComponent(inn)}`);
    if (crFail(res)) {
        status.textContent = crErrorText(res, 'Не удалось найти организацию.');
        if (res && res.error === 'integration_not_configured') crOpenCounterparty(0, null, { inn });
        return;
    }
    status.textContent = `Найдено: ${res.counterparty.name}`;
    crOpenCounterparty(0, null, res.counterparty);
}

async function crOpenCounterparty(id, onSaved = null, prefill = null) {
    if (!crState.counterparties.length) await crLoadCounterparties();
    const p = id ? crState.counterparties.find(item => item.id === id) : { ...(prefill || {}) };
    if (!p) return customAlert('Контрагент не найден.');
    const f = (label, name, extra = '') => `<label>${label}<input class="cr-input" data-cp="${name}" value="${crEsc(p[name] || '')}" ${extra}></label>`;
    const modal = crModal(id ? 'Карточка контрагента' : 'Новый контрагент', `
        <div class="cr-form-grid cr-form-grid--2">
            <label class="cr-span-2">ИНН<span class="cr-input-row"><input class="cr-input" data-cp="inn" value="${crEsc(p.inn || '')}" inputmode="numeric" maxlength="12"><button class="btn-secondary" type="button" data-act="lookup">Заполнить по ИНН</button></span></label>
            <label class="cr-span-2">Полное наименование<input class="cr-input" data-cp="name" value="${crEsc(p.name || '')}"></label>
            ${f('Краткое наименование', 'short_name')}
            ${f('КПП', 'kpp', 'maxlength="9"')}
            ${f('ОГРН', 'ogrn', 'maxlength="15"')}
            ${f('Руководитель', 'director')}
            <label class="cr-span-2">Юридический адрес<input class="cr-input" data-cp="legal_address" value="${crEsc(p.legal_address || '')}"></label>
            ${f('Телефон', 'phone')}
            ${f('Email', 'email')}
            ${f('Статус', 'status')}
            <label class="cr-check"><input type="checkbox" data-cp="is_own" ${Number(p.is_own) ? 'checked' : ''}> Наша организация</label>
            <label class="cr-span-2">Примечание<textarea class="cr-input" data-cp="note" rows="3">${crEsc(p.note || '')}</textarea></label>
        </div>
        <p class="cr-muted" data-act="lookup-status"></p>`,
        `${id ? '<button class="btn-secondary cr-left" type="button" data-act="delete">Удалить</button>' : ''}
         <button class="btn-secondary" type="button" data-act="cancel">Отмена</button>
         <button class="btn-primary" type="button" data-act="save">Сохранить</button>`, { wide: true });
    const values = () => {
        const out = {};
        modal.querySelectorAll('[data-cp]').forEach(el => { out[el.dataset.cp] = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value.trim(); });
        return out;
    };
    modal.querySelector('[data-act="cancel"]').onclick = () => modal.closeModal();
    modal.querySelector('[data-act="lookup"]').onclick = async () => {
        const statusEl = modal.querySelector('[data-act="lookup-status"]');
        const inn = values().inn.replace(/\D+/g, '');
        statusEl.textContent = 'Ищем…';
        const res = await apiCall(`/cr/counterparties/lookup?inn=${encodeURIComponent(inn)}`);
        if (crFail(res)) { statusEl.textContent = crErrorText(res, 'Не найдено.'); return; }
        Object.entries(res.counterparty).forEach(([key, value]) => {
            const el = modal.querySelector(`[data-cp="${key}"]`);
            if (el && value) el.value = value;
        });
        statusEl.textContent = 'Реквизиты заполнены. Проверь и сохрани.';
    };
    modal.querySelector('[data-act="save"]').onclick = async () => {
        const payload = values();
        if (!payload.name) return customAlert('Укажи наименование контрагента.');
        const res = await apiCall(id ? `/cr/counterparties/${id}` : '/cr/counterparties', id ? 'PUT' : 'POST', payload);
        if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось сохранить контрагента.'));
        modal.closeModal();
        showToast('Контрагенты', 'Сохранено');
        await crLoadCounterparties();
        crRenderCounterparties();
        if (onSaved) onSaved(id || res.id);
    };
    const deleteBtn = modal.querySelector('[data-act="delete"]');
    if (deleteBtn) deleteBtn.onclick = async () => {
        if (!(await customConfirm('Удалить контрагента из справочника?'))) return;
        const res = await apiCall(`/cr/counterparties/${id}`, 'DELETE');
        if (crFail(res)) return customAlert(crErrorText(res, 'Не удалось удалить контрагента.'));
        modal.closeModal();
        await crLoadCounterparties();
        crRenderCounterparties();
    };
}

// Ссылка «На новой вкладке» (#cr=ID): открываем реестр при старте приложения.
try {
    // "Контрагенты" used to be a separate page; it now lives inside "Договоры".
    if (localStorage.getItem('korda_last_view') === 'counterparties') localStorage.setItem('korda_last_view', 'contract360');
} catch (e) { /* storage blocked */ }
if (/^#cr=\d+$/.test(location.hash || '')) {
    try { localStorage.setItem('korda_last_view', 'contract360'); } catch (e) { /* storage blocked: user lands on default view */ }
}

Object.assign(window, {
    renderContractRegistry, renderCounterparties, crSelectFolder, crSetPeriod, crScheduleSearch, crSelectRow, crToggleCheck,
    crOpenSelected, crOpenInNewTab, crCopySelected, crDeleteSelected, crBulkStatus, crExport, crToggleExportMenu, crAddFolder,
    crRenameFolder, crDeleteFolder, crOpenDocTypes, crOpenCreate, crOpenCard, crSwitchSection, crSwitchMainTab, crAddParty,
    crUpdateParty, crDeleteParty, crExportParties, crPrintEnvelope, crAddApproval, crDecide, crDeleteApproval,
    crOpenApprovalTemplates, crExportApprovals, crUploadFiles, crDeleteFile, crPrintApprovals, crRenderCounterparties,
    crLookupInn, crOpenCounterparty, crSwitchPageTab, crAfterCounterpartyCreated, crSetStatusFilter, crToggleMine, crToggleFileSearch,
    crSetFilesQuery, crSetColumnFilter, crEditItem, crCancelItemEdit, crSaveItem, crDeleteItem, crExportItems, crDeleteParam,
});
