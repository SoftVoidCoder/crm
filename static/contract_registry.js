// Реестр договоров и справочник контрагентов (API /api/cr/*).
const crState = {
    folder: 'all',
    period: 'all',
    meta: { folders: [], total: 0, deleted: 0 },
    contracts: [],
    selectedId: 0,
    checked: new Set(),
    docTypes: [],
    counterparties: [],
    users: [],
    card: null,
    cardSection: 'main',
    cardDirty: false,
};
let crSearchTimer = null;

const CR_ROLES = ['Заказчик', 'Исполнитель', 'Поставщик', 'Покупатель', 'Подрядчик', 'Арендодатель', 'Арендатор', 'Займодавец', 'Заёмщик', 'Лизингодатель', 'Лизингополучатель', 'Наша организация', 'Другое'];
const CR_SIGNING_METHODS = ['', 'Бумажный оригинал', 'ЭДО', 'Скан-копия', 'Почта России', 'Курьер'];
const CR_ORIGINAL_STATUSES = ['', 'Оригинал у нас', 'Оригинал у контрагента', 'Ожидаем оригинал', 'Только скан'];
const CR_APPROVAL_LABELS = { pending: 'В процессе', approved: 'Согласовано', approved_with_notes: 'Согласовано с замечаниями', rejected: 'Отклонено' };

const crEsc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const crMoney = value => Number(value || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const crDate = value => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
    return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
};
const crFail = res => !res || res.error;
const crErrorText = (res, fallback) => (res && (res.message || res.error)) || fallback;

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

// ---------- registry ----------

async function renderContractRegistry() {
    await Promise.all([crLoadMeta(), crLoadContracts()]);
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

async function crLoadContracts() {
    const params = new URLSearchParams({ folder: crState.folder, period: crState.period });
    if (crState.period === 'range') {
        params.set('date_from', document.getElementById('crDateFrom')?.value || '');
        params.set('date_to', document.getElementById('crDateTo')?.value || '');
    }
    const query = document.getElementById('crSearch')?.value.trim();
    if (query) params.set('q', query);
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

function crRenderTable() {
    const body = document.getElementById('crTableBody');
    if (!body) return;
    if (!crState.contracts.length) {
        body.innerHTML = `<tr><td colspan="17" class="cr-empty">Договоров нет. Нажми «+ Добавить договор», чтобы создать первый.</td></tr>`;
    } else {
        body.innerHTML = crState.contracts.map((contract, index) => `
            <tr class="${crRowClass(contract)} ${contract.id === crState.selectedId ? 'cr-row--selected' : ''}" onclick="crSelectRow(${contract.id})" ondblclick="crOpenCard(${contract.id})">
                <td>${index + 1}</td>
                <td><strong>${crEsc(contract.number)}</strong></td>
                <td>${contract.seq_no || ''}</td>
                <td>${crEsc(contract.extra_number)}</td>
                <td>${crEsc(contract.incoming_number)}</td>
                <td>${crEsc(contract.gov_reg_number)}</td>
                <td><input type="checkbox" ${crState.checked.has(contract.id) ? 'checked' : ''} onclick="event.stopPropagation(); crToggleCheck(${contract.id}, this.checked)"></td>
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
    const sum = key => crState.contracts.reduce((acc, item) => acc + Number(key === 'vat_amount' && !item.vat_enabled ? 0 : item[key] || 0), 0);
    const footer = document.getElementById('crFooter');
    if (footer) {
        footer.innerHTML = `
            <span>Всего: <strong>${crState.contracts.length}</strong></span>
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
    for (const id of ids) {
        await apiCall(restoring ? `/cr/contracts/${id}/restore` : `/cr/contracts/${id}`, restoring ? 'POST' : 'DELETE');
    }
    crState.checked.clear();
    crState.selectedId = 0;
    showToast('Договоры', restoring ? 'Восстановлено' : 'Перемещено в «Удалённые»');
    renderContractRegistry();
}

function crExportExcel() {
    if (typeof XLSX === 'undefined') return customAlert('Экспорт в Excel сейчас недоступен.');
    const rows = crState.contracts.map((c, i) => ({
        '№': i + 1,
        'Номер': c.number,
        'Порядковый номер': c.seq_no || '',
        'Доп. номер': c.extra_number,
        'Входящий номер': c.incoming_number,
        'Номер гос. регистрации': c.gov_reg_number,
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
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.json_to_sheet(rows), 'Договоры');
    XLSX.writeFile(book, `Реестр договоров ${new Date().toLocaleDateString('ru-RU')}.xlsx`);
}

// ---------- folders ----------

function crPromptName(title, initial = '') {
    return new Promise(resolve => {
        const modal = crModal(title, `<input class="cr-input" id="crPromptInput" value="${crEsc(initial)}" maxlength="120">`,
            `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button><button class="btn-primary" type="button" data-act="ok">Сохранить</button>`);
        const input = modal.querySelector('#crPromptInput');
        const finish = value => { modal.closeModal(); resolve(value); };
        modal.querySelector('[data-act="cancel"]').onclick = () => finish(null);
        modal.querySelector('[data-act="ok"]').onclick = () => finish(input.value.trim());
        input.addEventListener('keydown', event => { if (event.key === 'Enter') finish(input.value.trim()); });
        input.focus();
    });
}

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

// ---------- document types ----------

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

function crFormatNumber(type, seq) {
    const digits = Math.max(0, Math.min(12, Number(type.digits || 0)));
    const core = digits ? String(seq).padStart(digits, '0') : String(seq);
    return `${type.prefix || ''}${core}${type.postfix || ''}${Number(type.add_year) ? new Date().getFullYear() : ''}`;
}

function crCounterpartyOptions(selectedId, emptyLabel = '— не выбран —') {
    return `<option value="0">${emptyLabel}</option>` + crState.counterparties.map(p =>
        `<option value="${p.id}" ${Number(selectedId) === Number(p.id) ? 'selected' : ''}>${crEsc(p.short_name || p.name)}${p.inn ? ` · ИНН ${crEsc(p.inn)}` : ''}</option>`).join('');
}

// onPick(type) — режим выбора типа из окна создания договора.
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
                ${onPick ? '<button class="btn-primary" type="button" data-act="pick">Выбрать</button>' : ''}
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
        Пример: префикс «КР-», № 17, разрядность 5, постпрефикс «/П-», год → <b>КР-00017/П-${new Date().getFullYear()}</b>.</p>`, '', { wide: true });

    const field = id => modal.querySelector(`#${id}`);
    field('crTypeCounterparty').innerHTML = crCounterpartyOptions(0, '— без категории —');
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
            row.ondblclick = () => { if (onPick) { modal.closeModal(); onPick(type); } };
        });
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
    const pickBtn = modal.querySelector('[data-act="pick"]');
    if (pickBtn) pickBtn.onclick = () => {
        const type = crState.docTypes.find(t => t.id === editingId);
        if (!type) return customAlert('Выбери тип в таблице.');
        modal.closeModal();
        onPick(type);
    };
    fill(null);
}

// ---------- create ----------

async function crOpenCreate() {
    await crLoadDocTypes();
    let picked = null;
    const modal = crModal('Номер документа', `
        <div class="cr-form-grid cr-form-grid--2">
            <label class="cr-span-2">Тип документа
                <span class="cr-input-row"><input class="cr-input" id="crNewType" readonly placeholder="Не выбран"><button class="btn-secondary" type="button" data-act="type">Выбрать</button></span>
            </label>
            <label class="cr-span-2">Номер<input class="cr-input" id="crNewNumber" placeholder="Подставится по типу документа или введи вручную"></label>
        </div>
        <p class="cr-hint">После «Продолжить» откроется карточка договора. Тип документа — ваш справочник для классификации и автонумерации. Номер и тип можно поменять позже.</p>`,
        `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button>
         <button class="btn-secondary" type="button" data-act="random">Случайный номер</button>
         <button class="btn-primary" type="button" data-act="ok">Продолжить</button>`);
    const setType = type => {
        picked = type;
        modal.querySelector('#crNewType').value = type ? type.name : '';
        modal.querySelector('#crNewNumber').value = type ? crFormatNumber(type, Number(type.counter || 0) + 1) : '';
    };
    if (crState.docTypes.length === 1) setType(crState.docTypes[0]);
    modal.querySelector('[data-act="type"]').onclick = () => crOpenDocTypes(setType);
    modal.querySelector('[data-act="cancel"]').onclick = () => modal.closeModal();
    const submit = async random => {
        const folderId = /^\d+$/.test(String(crState.folder)) ? Number(crState.folder) : 0;
        const res = await apiCall('/cr/contracts', 'POST', {
            doc_type_id: picked ? picked.id : 0,
            number: modal.querySelector('#crNewNumber').value.trim(),
            random: random ? 1 : 0,
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

const CR_SECTIONS = [
    ['main', 'Основные'],
    ['parties', 'Контрагенты'],
    ['approvals', 'Согласования'],
    ['files', 'Файлы'],
];

async function crLoadUsers() {
    if (crState.users.length) return crState.users;
    const res = await apiCall('/users/all');
    crState.users = Array.isArray(res) ? res.filter(u => u.status === 'approved') : [];
    return crState.users;
}

async function crOpenCard(contractId) {
    const [contract] = await Promise.all([apiCall(`/cr/contracts/${contractId}`), crLoadDocTypes(), crLoadCounterparties(), crLoadUsers()]);
    if (crFail(contract)) return customAlert(crErrorText(contract, 'Не удалось открыть договор.'));
    crState.card = contract;
    crState.cardSection = 'main';
    crState.cardDirty = false;
    const modal = crModal(`Договор № ${contract.number}`, `
        <div class="cr-card">
            <nav class="cr-card-nav" id="crCardNav"></nav>
            <div class="cr-card-body" id="crCardBody"></div>
        </div>
        <datalist id="crUsersList">${crState.users.map(u => `<option value="${crEsc(u.name || u.email)}">`).join('')}</datalist>`,
        `<span class="cr-muted" id="crCardMeta"></span>
         <button class="btn-secondary" type="button" data-act="print">Карточка договора</button>
         <button class="btn-secondary" type="button" data-act="close">Закрыть</button>
         <button class="btn-primary" type="button" data-act="save">Сохранить</button>`,
        { full: true, onClose: () => {
            if (crState.cardDirty && !window.confirm('Есть несохранённые изменения. Закрыть без сохранения?')) return false;
            crState.card = null;
            renderContractRegistry();
            return true;
        } });
    crState.cardModal = modal;
    modal.querySelector('[data-act="close"]').onclick = () => modal.requestClose();
    modal.querySelector('[data-act="save"]').onclick = () => crSaveCard();
    modal.querySelector('[data-act="print"]').onclick = () => crPrintCard();
    crRenderCard();
}

function crRenderCard() {
    const modal = crState.cardModal;
    const contract = crState.card;
    if (!modal || !contract) return;
    modal.querySelector('.cr-modal-head h2').textContent = `Договор № ${contract.number}`;
    const counts = { parties: contract.parties.length, approvals: contract.approvals.length, files: contract.files.length };
    modal.querySelector('#crCardNav').innerHTML = CR_SECTIONS.map(([key, label]) => `
        <button type="button" class="${crState.cardSection === key ? 'active' : ''}" onclick="crSwitchSection('${key}')">${label}${key in counts ? ` <span>${counts[key]}</span>` : ''}</button>`).join('');
    const updated = contract.updated_at ? new Date(contract.updated_at * 1000).toLocaleString('ru-RU') : '';
    modal.querySelector('#crCardMeta').textContent = `ID ${contract.id}${updated ? ` · изменён ${updated}` : ''}${contract.updated_by ? ` · ${contract.updated_by}` : ''}`;
    const body = modal.querySelector('#crCardBody');
    if (crState.cardSection === 'main') body.innerHTML = crMainSectionHtml(contract);
    if (crState.cardSection === 'parties') body.innerHTML = crPartiesSectionHtml(contract);
    if (crState.cardSection === 'approvals') body.innerHTML = crApprovalsSectionHtml(contract);
    if (crState.cardSection === 'files') body.innerHTML = crFilesSectionHtml(contract);
    if (crState.cardSection === 'main') crBindMainSection(body);
}

function crSwitchSection(key) {
    if (crState.cardSection === 'main') crCollectMain();
    crState.cardSection = key;
    crRenderCard();
}

const crField = (label, name, value, type = 'text', extra = '') =>
    `<label>${label}<input class="cr-input" data-field="${name}" type="${type}" value="${crEsc(value ?? '')}" ${extra}></label>`;
const crCheck = (label, name, value) =>
    `<label class="cr-check"><input type="checkbox" data-field="${name}" ${Number(value) ? 'checked' : ''}> ${label}</label>`;
const crSelect = (label, name, value, options) =>
    `<label>${label}<select class="cr-input" data-field="${name}">${options.map(([v, text]) => `<option value="${crEsc(v)}" ${String(v) === String(value ?? '') ? 'selected' : ''}>${crEsc(text)}</option>`).join('')}</select></label>`;

function crMainSectionHtml(c) {
    const typeOptions = [['0', '— не выбран —'], ...crState.docTypes.map(t => [String(t.id), t.name])];
    const folderOptions = [['0', 'Все (без папки)'], ...crState.meta.folders.map(f => [String(f.id), f.name])];
    const currencyOptions = [['RUB', 'рубль'], ['USD', 'доллар США'], ['EUR', 'евро'], ['CNY', 'юань'], ['KZT', 'тенге']];
    return `
        <div class="cr-section-title">Основные</div>
        <div class="cr-form-grid">
            ${crField('Дата создания', 'created_date', c.created_date, 'date')}
            ${crField('Дата заключения', 'concluded_date', c.concluded_date, 'date')}
            ${crField('Дата окончания', 'end_date', c.end_date, 'date')}
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
        <div class="cr-section-title">Подписание / рассмотрение</div>
        <div class="cr-form-grid">
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
        <div class="cr-form-grid cr-form-grid--text">
            <label>Предмет договора<textarea class="cr-input" data-field="subject" rows="4">${crEsc(c.subject)}</textarea></label>
            <label>Примечание<textarea class="cr-input" data-field="note" rows="4">${crEsc(c.note)}</textarea></label>
            <label>Основание<textarea class="cr-input" data-field="basis" rows="4">${crEsc(c.basis)}</textarea></label>
        </div>`;
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
    body.querySelectorAll('[data-field]').forEach(el => el.addEventListener('input', () => { crState.cardDirty = true; recalc(); }));
    body.querySelectorAll('[data-field]').forEach(el => el.addEventListener('change', () => { crState.cardDirty = true; recalc(); }));
    recalc();
}

function crCollectMain() {
    const body = crState.cardModal?.querySelector('#crCardBody');
    if (!body || !crState.card) return;
    body.querySelectorAll('[data-field]').forEach(el => {
        crState.card[el.dataset.field] = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
    });
}

async function crSaveCard() {
    if (crState.cardSection === 'main') crCollectMain();
    const c = crState.card;
    if (!String(c.number || '').trim()) return customAlert('Номер договора не может быть пустым.');
    const fields = ['number', 'seq_no', 'extra_number', 'incoming_number', 'gov_reg_number', 'flagged', 'created_date', 'concluded_date', 'end_date',
        'amount', 'currency', 'vat_enabled', 'vat_rate', 'vat_manual', 'vat_amount', 'kind', 'responsible', 'initiator', 'tender', 'category',
        'subject', 'note', 'basis', 'notify_enabled', 'notify_days', 'notify_date', 'internal_only', 'payment_deferral', 'framework',
        'prolongation', 'prolongation_terms', 'indefinite', 'on_counterparty_signing', 'sent_for_signing_date', 'signed_date', 'signed',
        'signing_method', 'on_counterparty_review', 'sent_to_counterparty_date', 'original_status', 'doc_type_id', 'folder_id'];
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
    crState.card = { ...fresh, ...keep, parties: fresh.parties, approvals: fresh.approvals, files: fresh.files, flags: fresh.flags };
    crRenderCard();
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
        </div>
        <div class="cr-table-wrap">
            <table class="cr-table"><thead><tr><th>Контрагент (сторона договора)</th><th>Роль</th><th>ИНН</th><th>КПП</th><th>Авторассылка</th><th></th></tr></thead>
            <tbody>${c.parties.length ? c.parties.map(p => `
                <tr ondblclick="crOpenCounterparty(${p.counterparty_id})">
                    <td>${crEsc(p.name)}</td>
                    <td><select class="cr-input cr-input--sm" onchange="crUpdateParty(${p.id}, this.value, this.closest('tr').querySelector('input[type=checkbox]').checked ? 1 : 0)">${CR_ROLES.map(r => `<option ${r === p.role ? 'selected' : ''}>${r}</option>`).join('')}${CR_ROLES.includes(p.role) || !p.role ? '' : `<option selected>${crEsc(p.role)}</option>`}</select></td>
                    <td>${crEsc(p.inn)}</td><td>${crEsc(p.kpp)}</td>
                    <td><input type="checkbox" ${Number(p.auto_mailing) ? 'checked' : ''} onchange="crUpdateParty(${p.id}, this.closest('tr').querySelector('select').value, this.checked ? 1 : 0)"></td>
                    <td><button class="cr-link-danger" type="button" onclick="crDeleteParty(${p.id})">Удалить</button></td>
                </tr>`).join('') : '<tr><td colspan="6" class="cr-empty">Стороны не указаны.</td></tr>'}</tbody></table>
        </div>
        <p class="cr-hint">Двойной щелчок по строке откроет карточку контрагента.</p>`;
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

// ---- approvals

function crApprovalsSectionHtml(c) {
    const today = new Date().toISOString().slice(0, 10);
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
            <button class="btn-secondary" type="button" onclick="crPrintApprovals()">Печать листа согласования</button>
        </div>
        <div class="cr-table-wrap">
            <table class="cr-table"><thead><tr><th>№</th><th>Согласующий</th><th>Отдел</th><th>Должность</th><th>Срок</th><th>Дата решения</th><th>Состояние</th><th>Комментарий</th><th></th></tr></thead>
            <tbody>${c.approvals.length ? c.approvals.map((a, i) => `
                <tr class="${a.status === 'pending' && a.due_date && a.due_date < today ? 'cr-row--appr-overdue' : ''}">
                    <td>${i + 1}</td><td>${crEsc(a.approver)}</td><td>${crEsc(a.department)}</td><td>${crEsc(a.position)}</td>
                    <td>${crDate(a.due_date)}</td>
                    <td>${a.decided_at ? new Date(a.decided_at * 1000).toLocaleString('ru-RU') : ''}</td>
                    <td><span class="cr-status cr-status--${a.status}">${CR_APPROVAL_LABELS[a.status] || a.status}</span></td>
                    <td>${crEsc(a.comment)}</td>
                    <td class="cr-actions">
                        ${a.status === 'pending' ? `
                            <button type="button" onclick="crDecide(${a.id}, 'approved')">Согласовать</button>
                            <button type="button" onclick="crDecide(${a.id}, 'approved_with_notes')">С замечаниями</button>
                            <button type="button" onclick="crDecide(${a.id}, 'rejected')">Отклонить</button>` : `
                            <button type="button" onclick="crDecide(${a.id}, 'pending')">Вернуть в процесс</button>`}
                        <button type="button" class="cr-link-danger" onclick="crDeleteApproval(${a.id})">Удалить</button>
                    </td>
                </tr>`).join('') : '<tr><td colspan="9" class="cr-empty">Лист согласования пуст.</td></tr>'}</tbody></table>
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

// ---- files

function crFilesSectionHtml(c) {
    const size = bytes => bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`;
    return `
        <div class="cr-section-title">Файлы договора</div>
        <div class="cr-toolbar-group">
            <label class="btn-primary cr-upload">Загрузить файл<input type="file" multiple onchange="crUploadFiles(this)"></label>
            <span class="cr-muted">До 25 МБ на файл: скан, docx, pdf, xlsx…</span>
        </div>
        <div class="cr-table-wrap">
            <table class="cr-table"><thead><tr><th>Файл</th><th>Размер</th><th>Загрузил</th><th>Дата</th><th></th></tr></thead>
            <tbody>${c.files.length ? c.files.map(f => `
                <tr>
                    <td><a href="${crEsc(f.file_url)}" target="_blank" rel="noopener">${crEsc(f.filename)}</a></td>
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

function crPrintWindow(title, html) {
    const win = window.open('', '_blank');
    if (!win) return customAlert('Браузер заблокировал окно печати. Разреши всплывающие окна для сайта.');
    win.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${crEsc(title)}</title>
        <style>body{font:13px/1.45 Arial,sans-serif;color:#111;margin:24px}h1{font-size:18px}table{border-collapse:collapse;width:100%;margin:10px 0}
        td,th{border:1px solid #999;padding:5px 7px;text-align:left;vertical-align:top}th{background:#f1f1f1}.k{width:34%;color:#444}</style></head>
        <body>${html}<script>window.onload=()=>window.print()<\/script></body></html>`);
    win.document.close();
}

function crPrintCard() {
    const c = crState.card;
    const row = (k, v) => v ? `<tr><td class="k">${k}</td><td>${crEsc(v)}</td></tr>` : '';
    crPrintWindow(`Договор ${c.number}`, `<h1>Карточка договора № ${crEsc(c.number)}</h1><table>
        ${row('Тип документа', c.doc_type_name)}${row('Дата создания', crDate(c.created_date))}${row('Дата заключения', crDate(c.concluded_date))}
        ${row('Дата окончания', c.indefinite ? 'бессрочный' : crDate(c.end_date))}${row('Входящий номер', c.incoming_number)}${row('Доп. номер', c.extra_number)}
        ${row('Сумма', `${crMoney(c.amount)} ${c.currency}`)}${row('НДС', c.vat_enabled ? `${c.vat_rate}% — ${crMoney(c.vat_amount)}` : 'без НДС')}
        ${row('Ответственный', c.responsible)}${row('Инициатор', c.initiator)}${row('Предмет договора', c.subject)}${row('Примечание', c.note)}</table>
        <h1>Стороны</h1><table><tr><th>Контрагент</th><th>Роль</th><th>ИНН</th></tr>
        ${c.parties.map(p => `<tr><td>${crEsc(p.name)}</td><td>${crEsc(p.role)}</td><td>${crEsc(p.inn)}</td></tr>`).join('')}</table>`);
}

function crPrintApprovals() {
    const c = crState.card;
    crPrintWindow(`Лист согласования ${c.number}`, `<h1>Лист согласования договора № ${crEsc(c.number)}</h1>
        <p>${crEsc(c.doc_type_name || '')}${c.parties.length ? ` · ${c.parties.map(p => crEsc(p.name)).join(', ')}` : ''}</p>
        <table><tr><th>№</th><th>Согласующий</th><th>Отдел</th><th>Должность</th><th>Состояние</th><th>Дата</th><th>Комментарий</th><th>Подпись</th></tr>
        ${c.approvals.map((a, i) => `<tr><td>${i + 1}</td><td>${crEsc(a.approver)}</td><td>${crEsc(a.department)}</td><td>${crEsc(a.position)}</td>
        <td>${CR_APPROVAL_LABELS[a.status] || ''}</td><td>${a.decided_at ? new Date(a.decided_at * 1000).toLocaleDateString('ru-RU') : ''}</td><td>${crEsc(a.comment)}</td><td></td></tr>`).join('')}</table>`);
}

// ---------- counterparties ----------

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
            <td>${crEsc(p.inn)}</td><td>${crEsc(p.kpp)}</td><td>${crEsc(p.ogrn)}</td><td>${crEsc(p.legal_address)}</td>
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

Object.assign(window, {
    renderContractRegistry, renderCounterparties, crSelectFolder, crSetPeriod, crScheduleSearch, crSelectRow, crToggleCheck,
    crOpenSelected, crCopySelected, crDeleteSelected, crExportExcel, crAddFolder, crRenameFolder, crDeleteFolder,
    crOpenDocTypes, crOpenCreate, crOpenCard, crSwitchSection, crAddParty, crUpdateParty, crDeleteParty, crAddApproval,
    crDecide, crDeleteApproval, crUploadFiles, crDeleteFile, crPrintApprovals, crRenderCounterparties, crLookupInn,
    crOpenCounterparty, crAfterCounterpartyCreated,
});
