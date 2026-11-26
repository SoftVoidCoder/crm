// Реестр «Документы компании» в стиле реестра договоров. Данные — documentsDB (/api/documents), создание — существующая форма.
const dcState = { journal: 'all', period: 'all', selectedId: 0, checked: new Set(), columnFilters: {} };

const DC_JOURNALS = [
    ['all', 'Все документы', 'folder'],
    ['incoming', 'Входящие', 'inbox'],
    ['outgoing', 'Исходящие', 'outbox'],
    ['internal', 'Внутренние', 'building'],
    ['drafts', 'Черновики', 'pencil'],
    ['archive', 'Архив', 'archive'],
];
const DC_TYPES = { incoming: ['Вх', 'dc-type--in'], outgoing: ['Исх', 'dc-type--out'] };
const DC_STATUS = {
    draft: ['Черновик', 'cr-pill--approval'], registered: ['Зарегистрирован', 'cr-pill--active'], signed: ['Подписан', 'cr-pill--executed'],
    done: ['Выполнен', 'cr-pill--executed'], closed: ['Закрыт', 'cr-pill--archive'], archived: ['В архиве', 'cr-pill--archive'],
};
const DC_ARCHIVED = new Set(['archived', 'closed']);

const dcEsc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

// Documents store dates as дд.мм.гггг (form) or гггг-мм-дд (API) — normalise to a Date.
function dcParseDate(value) {
    const raw = String(value || '').trim();
    let m = /^(\d{2})\.(\d{2})\.(\d{4})/.exec(raw);
    if (m) return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
    m = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw);
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return null;
}
const dcFmtDate = value => {
    const d = dcParseDate(value);
    return d ? d.toLocaleDateString('ru-RU') : (value || '');
};
const dcToday = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
const dcIsInternal = doc => String(doc.type || '').startsWith('internal') || !['incoming', 'outgoing'].includes(String(doc.type || ''));
const dcTypeBadge = doc => DC_TYPES[doc.type] || ['Внутр', 'dc-type--int'];
const dcCorrespondent = doc => doc.correspondent || (doc.type === 'incoming' ? doc.sender_name : doc.recipient_name) || '';
const dcFileUrl = doc => doc.file_url || doc.active_revision?.file_url || '';

function dcDocs() {
    return Array.isArray(window.documentsDB) ? window.documentsDB : (typeof documentsDB !== 'undefined' && Array.isArray(documentsDB) ? documentsDB : []);
}

function dcInJournal(doc, journal) {
    const archived = DC_ARCHIVED.has(String(doc.status || ''));
    if (journal === 'archive') return archived;
    if (journal === 'drafts') return doc.status === 'draft';
    if (archived) return false;
    if (journal === 'incoming') return doc.type === 'incoming';
    if (journal === 'outgoing') return doc.type === 'outgoing';
    if (journal === 'internal') return dcIsInternal(doc);
    return true;
}

function dcDeadlineState(doc) {
    const due = dcParseDate(doc.resolution_deadline);
    if (!due || DC_ARCHIVED.has(doc.status) || ['done', 'signed'].includes(doc.status)) return '';
    const days = Math.round((due - dcToday()) / 86400000);
    if (days < 0) return 'overdue';
    if (days <= 3) return 'soon';
    return '';
}

const DC_COLUMNS = [
    ['check', null], ['index', null], ['type', d => dcTypeBadge(d)[0]], ['number', d => d.number], ['date', d => dcFmtDate(d.d_date)],
    ['subject', d => d.subject], ['corr', d => dcCorrespondent(d)], ['executor', d => d.executor_name || d.resolution_assignee],
    ['deadline', d => dcFmtDate(d.resolution_deadline)], ['status', d => (DC_STATUS[d.status] || [d.status])[0]], ['file', null],
];

function dcVisible() {
    const query = (document.getElementById('dcSearch')?.value || '').trim().toLowerCase();
    const status = document.getElementById('dcStatusFilter')?.value || '';
    let from = null; let to = null;
    if (dcState.period === 'year') { from = dcToday(); from.setFullYear(from.getFullYear() - 1); }
    if (dcState.period === 'range') {
        const f = document.getElementById('dcDateFrom')?.value; const t = document.getElementById('dcDateTo')?.value;
        from = f ? dcParseDate(f) : null; to = t ? dcParseDate(t) : null;
    }
    const getters = Object.fromEntries(DC_COLUMNS);
    const filters = Object.entries(dcState.columnFilters).filter(([, v]) => String(v || '').trim());
    return dcDocs().filter(doc => {
        if (!dcInJournal(doc, dcState.journal)) return false;
        if (status && doc.status !== status) return false;
        const date = dcParseDate(doc.d_date);
        if (from && (!date || date < from)) return false;
        if (to && (!date || date > to)) return false;
        if (query && !`${doc.number} ${doc.subject} ${dcCorrespondent(doc)} ${doc.executor_name} ${doc.source_number}`.toLowerCase().includes(query)) return false;
        return filters.every(([key, value]) => String(getters[key]?.(doc) ?? '').toLowerCase().includes(String(value).replace(/%/g, '').trim().toLowerCase()));
    }).sort((a, b) => (dcParseDate(b.d_date) || 0) - (dcParseDate(a.d_date) || 0) || Number(b.id) - Number(a.id));
}

function dcRenderJournals() {
    const list = document.getElementById('dcJournalList');
    if (!list) return;
    const docs = dcDocs();
    list.innerHTML = DC_JOURNALS.map(([key, name, icon]) => `
        <li class="${dcState.journal === key ? 'active' : ''}" onclick="dcSelectJournal('${key}')">
            <span class="cr-folder-icon">${crIcon(icon)}</span><span class="cr-folder-name">${name}</span>
            <span class="cr-folder-count">${docs.filter(d => dcInJournal(d, key)).length}</span>
        </li>`).join('');
    const archiveBtn = document.getElementById('dcArchiveBtn');
    if (archiveBtn) archiveBtn.textContent = dcState.journal === 'archive' ? 'Вернуть из архива' : 'В архив';
}

function dcRenderFilterRow() {
    const row = document.getElementById('dcFilterRow');
    if (!row || row.dataset.ready) return;
    row.dataset.ready = '1';
    row.innerHTML = DC_COLUMNS.map(([key, getter]) => getter
        ? `<th><input class="cr-col-filter" placeholder="фильтр" oninput="dcState.columnFilters['${key}'] = this.value; dcRender()"></th>` : '<th></th>').join('');
}

function dcRender() {
    dcRenderJournals();
    dcRenderFilterRow();
    const body = document.getElementById('dcTableBody');
    if (!body) return;
    const rows = dcVisible();
    const known = new Set(dcDocs().map(d => Number(d.id)));
    dcState.checked.forEach(id => { if (!known.has(id)) dcState.checked.delete(id); });
    body.innerHTML = rows.length ? rows.map((doc, i) => {
        const [typeLabel, typeClass] = dcTypeBadge(doc);
        const [statusLabel, statusClass] = DC_STATUS[doc.status] || [doc.status || '—', ''];
        const deadline = dcDeadlineState(doc);
        const file = dcFileUrl(doc);
        const rowClass = deadline === 'overdue' ? 'cr-row--overdue' : deadline === 'soon' ? 'cr-row--expiring' : (!file ? 'dc-row--nofile' : '');
        return `<tr class="${rowClass} ${Number(doc.id) === dcState.selectedId ? 'cr-row--selected' : ''}" onclick="dcSelect(${doc.id})" ondblclick="dcOpenView(${doc.id})">
            <td><input type="checkbox" ${dcState.checked.has(Number(doc.id)) ? 'checked' : ''} onclick="event.stopPropagation(); dcToggle(${doc.id}, this.checked)"></td>
            <td>${i + 1}</td>
            <td><span class="dc-type ${typeClass}">${typeLabel}</span></td>
            <td><strong>${dcEsc(doc.number)}</strong></td>
            <td>${dcEsc(dcFmtDate(doc.d_date))}</td>
            <td class="cr-wrap dc-subject">${dcEsc(doc.subject)}</td>
            <td class="cr-wrap">${dcEsc(dcCorrespondent(doc)) || '<span class="cr-muted">—</span>'}</td>
            <td>${dcEsc(doc.executor_name || doc.resolution_assignee) || '<span class="cr-muted">—</span>'}</td>
            <td>${dcEsc(dcFmtDate(doc.resolution_deadline)) || '<span class="cr-muted">—</span>'}</td>
            <td><span class="cr-pill ${statusClass}">${dcEsc(statusLabel)}</span></td>
            <td>${file ? `<a href="${dcEsc(file)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="Открыть файл" class="dc-file">${crIcon('clip')}<span>открыть</span></a>` : '<span class="cr-muted">нет</span>'}</td>
        </tr>`;
    }).join('') : `<tr><td colspan="${DC_COLUMNS.length}" class="cr-empty">${dcDocs().length ? 'Ничего не найдено. Смени журнал или очисти поиск.' : 'Документов пока нет. Нажми «+ Добавить документ».'}</td></tr>`;
    const footer = document.getElementById('dcFooter');
    if (footer) {
        const noFile = rows.filter(d => !dcFileUrl(d)).length;
        const overdue = rows.filter(d => dcDeadlineState(d) === 'overdue').length;
        footer.innerHTML = `<span>Всего: <strong>${rows.length}</strong></span><span>Отмечено: <strong>${dcState.checked.size}</strong></span>
            <span class="cr-footer-sums">${overdue ? `Срок прошёл: <strong>${overdue}</strong> · ` : ''}Без файла: <strong>${noFile}</strong></span>`;
    }
}

function renderDocumentsRegistry() {
    dcRender();
}

function dcSelectJournal(key) {
    dcState.journal = key;
    dcState.selectedId = 0;
    dcState.checked.clear();
    dcRender();
}

function dcSetPeriod(value) {
    dcState.period = value;
    const radio = document.querySelector(`input[name="dcPeriod"][value="${value}"]`);
    if (radio) radio.checked = true;
    dcRender();
}

function dcSelect(id) { dcState.selectedId = Number(id); dcRender(); }
function dcToggle(id, on) { if (on) dcState.checked.add(Number(id)); else dcState.checked.delete(Number(id)); dcRender(); }
function dcToggleAll(on) { dcVisible().forEach(d => on ? dcState.checked.add(Number(d.id)) : dcState.checked.delete(Number(d.id))); dcRender(); }
const dcFind = id => dcDocs().find(d => Number(d.id) === Number(id));
const dcTargets = () => dcState.checked.size ? [...dcState.checked] : (dcState.selectedId ? [dcState.selectedId] : []);

function dcRequireSelected() {
    if (!dcState.selectedId) { customAlert('Выбери документ в таблице.'); return null; }
    return dcFind(dcState.selectedId);
}

function dcOpenSelected() { const d = dcRequireSelected(); if (d) dcOpenView(d.id); }
function dcEditSelected() { const d = dcRequireSelected(); if (d) dcOpenEdit(d.id); }
function dcDownloadSelected() {
    const d = dcRequireSelected();
    if (!d) return;
    const url = dcFileUrl(d);
    if (!url) return customAlert('У этого документа нет файла. Прикрепи его в «Изменить».');
    window.open(url, '_blank', 'noopener');
}

async function dcReload() {
    if (typeof loadDocuments === 'function') await loadDocuments();
    dcRender();
}

async function dcArchiveSelected() {
    const ids = dcTargets();
    if (!ids.length) return customAlert('Выбери документ или отметь несколько галочками.');
    const restore = dcState.journal === 'archive';
    let failed = 0;
    for (const id of ids) {
        const doc = dcFind(id);
        if (!doc) continue;
        const res = await apiCall(`/documents/${id}`, 'PUT', buildDocumentUpdatePayload(doc, { status: restore ? 'registered' : 'archived' }));
        if (!res || res.error) failed += 1;
    }
    dcState.checked.clear();
    showToast('Документы', `${restore ? 'Возвращено из архива' : 'Перенесено в архив'}${failed ? ` · не удалось: ${failed}` : ''}`, failed ? 'error' : 'success');
    dcReload();
}

async function dcDeleteSelected() {
    const ids = dcTargets();
    if (!ids.length) return customAlert('Выбери документ или отметь несколько галочками.');
    const names = ids.slice(0, 5).map(id => dcFind(id)?.number).filter(Boolean).join(', ');
    if (!(await customConfirm(`Удалить навсегда документов: ${ids.length} (${names}${ids.length > 5 ? '…' : ''})? Восстановить будет нельзя. Если документ просто больше не нужен в работе — лучше «В архив».`))) return;
    let failed = 0;
    for (const id of ids) {
        const res = await apiCall(`/documents/${id}`, 'DELETE');
        if (!res || res.error) failed += 1;
    }
    dcState.checked.clear();
    dcState.selectedId = 0;
    showToast('Документы', failed ? `Удалено с ошибками: ${failed}` : 'Удалено', failed ? 'error' : 'success');
    dcReload();
}

function dcToggleExportMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('dcExportMenu');
    if (!menu) return;
    menu.hidden = !menu.hidden;
    if (!menu.hidden) document.addEventListener('click', () => { menu.hidden = true; }, { once: true });
}

function dcExport(kind) {
    const rows = (dcState.checked.size ? dcVisible().filter(d => dcState.checked.has(Number(d.id))) : dcVisible()).map((d, i) => ({
        '№': i + 1, 'Тип': dcTypeBadge(d)[0], 'Номер': d.number, 'Дата': dcFmtDate(d.d_date), 'Тема': d.subject,
        'Корреспондент': dcCorrespondent(d), 'Исполнитель': d.executor_name || '', 'Срок': dcFmtDate(d.resolution_deadline),
        'Статус': (DC_STATUS[d.status] || [d.status])[0], 'Файл': dcFileUrl(d) ? 'есть' : 'нет',
    }));
    const stamp = new Date().toLocaleDateString('ru-RU');
    if (kind === 'print') {
        const head = rows.length ? Object.keys(rows[0]) : [];
        return crPrintWindow('Реестр документов', `<h1>Реестр документов на ${stamp}</h1><table><tr>${head.map(h => `<th>${dcEsc(h)}</th>`).join('')}</tr>
            ${rows.map(r => `<tr>${head.map(h => `<td>${dcEsc(r[h])}</td>`).join('')}</tr>`).join('')}</table>`, true);
    }
    if (typeof XLSX === 'undefined') return customAlert('Выгрузка сейчас недоступна.');
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.json_to_sheet(rows), 'Документы');
    XLSX.writeFile(book, `Реестр документов ${stamp}.xlsx`);
}

// ---------- card ----------

function dcViewHtml(d) {
    const [typeLabel] = dcTypeBadge(d);
    const typeTitle = typeof documentTypeTitle === 'function' ? documentTypeTitle(d.type) : typeLabel;
    const kind = typeof documentKindLabel === 'function' ? documentKindLabel(d.document_kind_code) : '';
    const [statusLabel, statusClass] = DC_STATUS[d.status] || [d.status || '', ''];
    const deadline = dcDeadlineState(d);
    const facts = [
        ['Дата регистрации', dcFmtDate(d.d_date)], ['Вид документа', kind], ['Корреспондент', dcCorrespondent(d)],
        ['Отправитель', d.sender_name], ['Получатель', d.recipient_name], ['Исходящий номер отправителя', d.source_number],
        ['Дата отправителя', dcFmtDate(d.source_date)], ['Способ доставки', d.delivery_method], ['Подписант', d.signer_name],
        ['Исполнитель', d.executor_name], ['Зарегистрировал', d.registered_by],
    ].filter(([, v]) => String(v || '').trim());
    const resolution = [d.resolution && ['Резолюция', d.resolution], d.resolution_author && ['Автор резолюции', d.resolution_author],
        d.resolution_assignee && ['Кому поручено', d.resolution_assignee], d.resolution_deadline && ['Срок исполнения', dcFmtDate(d.resolution_deadline)]].filter(Boolean);
    const file = dcFileUrl(d);
    const factsHtml = rows => `<dl class="crv-facts">${rows.map(([k, v]) => `<div><dt>${dcEsc(k)}</dt><dd>${dcEsc(v)}</dd></div>`).join('')}</dl>`;
    return `<div class="crv">
        <header class="crv-hero">
            <div>
                <div class="crv-eyebrow">${dcEsc(typeTitle)}</div>
                <h2>№ ${dcEsc(d.number)}</h2>
                <div class="crv-tags"><span class="cr-pill ${statusClass}">${dcEsc(statusLabel)}</span>
                ${deadline === 'overdue' ? '<span class="crv-tag crv-tag--bad">срок исполнения прошёл</span>' : deadline === 'soon' ? '<span class="crv-tag crv-tag--warn">срок скоро</span>' : ''}
                ${file ? '' : '<span class="crv-tag">нет файла</span>'}</div>
            </div>
            <div class="crv-sum"><strong style="font-size:20px">${dcEsc(dcFmtDate(d.d_date))}</strong><small>дата документа</small></div>
        </header>
        <section class="crv-block"><h3>Тема</h3><p style="margin:0;font-size:15px;line-height:1.5">${dcEsc(d.subject) || '—'}</p></section>
        ${facts.length ? `<section class="crv-block"><h3>Реквизиты</h3>${factsHtml(facts)}</section>` : ''}
        ${resolution.length ? `<section class="crv-block"><h3>Резолюция и исполнение</h3>${factsHtml(resolution)}</section>` : ''}
        <section class="crv-block"><h3>Файл</h3>${file
            ? `<ul class="crv-files"><li><a href="${dcEsc(file)}" target="_blank" rel="noopener">${dcEsc(d.original_filename || d.active_revision?.original_filename || 'Открыть файл')}</a><small>${dcEsc(d.active_revision?.revision_no ? `версия ${d.active_revision.revision_no}` : '')}</small></li></ul>`
            : '<p class="crv-sub">Файл не прикреплён. Прикрепи его через «Изменить».</p>'}</section>
    </div>`;
}

function dcOpenView(id) {
    const d = dcFind(id);
    if (!d) return;
    dcState.selectedId = Number(id);
    const modal = crModal(`Документ № ${d.number}`, dcViewHtml(d),
        `<button class="btn-secondary" type="button" data-act="print">Печать</button>
         ${dcFileUrl(d) ? '<button class="btn-secondary" type="button" data-act="file">Скачать файл</button>' : ''}
         <button class="btn-secondary" type="button" data-act="close">Закрыть</button>
         <button class="btn-primary" type="button" data-act="edit">Изменить</button>`, { wide: true });
    modal.querySelector('.cr-modal').classList.add('cr-modal--view');
    modal.querySelector('[data-act="close"]').onclick = () => modal.closeModal();
    modal.querySelector('[data-act="edit"]').onclick = () => { modal.closeModal(); dcOpenEdit(id); };
    modal.querySelector('[data-act="file"]')?.addEventListener('click', () => window.open(dcFileUrl(d), '_blank', 'noopener'));
    modal.querySelector('[data-act="print"]').onclick = () => crPrintWindow(`Документ ${d.number}`, `<link rel="stylesheet" href="/static/styles/contract_registry.css">${dcViewHtml(d)}`);
}

function dcOpenEdit(id) {
    const d = dcFind(id);
    if (!d) return;
    const toIso = v => { const x = dcParseDate(v); return x ? `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}` : ''; };
    const toRu = v => { const x = dcParseDate(v); return x ? x.toLocaleDateString('ru-RU') : ''; };
    const field = (label, name, value, type = 'text') => `<label>${label}<input class="cr-input" data-dc="${name}" type="${type}" value="${dcEsc(value ?? '')}"></label>`;
    const typeOptions = [['incoming', 'Входящий'], ['outgoing', 'Исходящий'], ['internal', 'Внутренний']];
    const currentType = ['incoming', 'outgoing'].includes(d.type) ? d.type : 'internal';
    const modal = crModal(`Изменить документ № ${d.number}`, `
        <div class="cr-form-grid">
            <label>Тип<select class="cr-input" data-dc="type">${typeOptions.map(([v, t]) => `<option value="${v}" ${v === currentType ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
            ${field('Номер', 'number', d.number)}
            ${field('Дата', 'd_date', toIso(d.d_date), 'date')}
            <label>Статус<select class="cr-input" data-dc="status">${Object.entries(DC_STATUS).map(([v, [t]]) => `<option value="${v}" ${v === d.status ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
            <label class="cr-span-4">Тема<textarea class="cr-input" data-dc="subject" rows="2">${dcEsc(d.subject)}</textarea></label>
            ${field('Корреспондент', 'correspondent', dcCorrespondent(d))}
            ${field('Исполнитель', 'executor_name', d.executor_name)}
            ${field('Срок исполнения', 'resolution_deadline', toIso(d.resolution_deadline), 'date')}
            ${field('Резолюция', 'resolution', d.resolution)}
        </div>
        <div class="cr-toolbar-group">
            <label class="btn-secondary cr-upload">${dcFileUrl(d) ? 'Заменить файл (новая версия)' : 'Прикрепить файл'}<input type="file" data-dc-file></label>
            <span class="cr-muted" data-dc-filename>${dcFileUrl(d) ? 'Сейчас файл прикреплён' : 'Файла нет'}</span>
        </div>`,
        `<button class="btn-secondary" type="button" data-act="cancel">Отмена</button><button class="btn-primary" type="button" data-act="save">Сохранить</button>`, { wide: true });
    const fileInput = modal.querySelector('[data-dc-file]');
    fileInput.onchange = () => { modal.querySelector('[data-dc-filename]').textContent = fileInput.files[0]?.name || ''; };
    modal.querySelector('[data-act="cancel"]').onclick = () => modal.closeModal();
    modal.querySelector('[data-act="save"]').onclick = async () => {
        const v = {};
        modal.querySelectorAll('[data-dc]').forEach(el => { v[el.dataset.dc] = el.value.trim(); });
        if (!v.number || !v.subject) return customAlert('Номер и тема обязательны.');
        const res = await apiCall(`/documents/${id}`, 'PUT', buildDocumentUpdatePayload(d, {
            ...v, d_date: toRu(v.d_date) || d.d_date, resolution_deadline: toRu(v.resolution_deadline),
        }));
        if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось сохранить документ.');
        if (fileInput.files[0]) {
            const form = new FormData();
            form.append('file', fileInput.files[0]);
            const up = await apiCall(`/documents/${id}/upload`, 'POST', form);
            if (!up || up.error) customAlert(up?.message || 'Документ сохранён, но файл не загрузился.');
        }
        modal.closeModal();
        showToast('Документы', 'Сохранено');
        dcReload();
    };
}

// The old renderer drew the card-style list; route every existing call (navigation, websocket, create form) here.
window.renderDocuments = renderDocumentsRegistry;

Object.assign(window, {
    dcState, renderDocumentsRegistry, dcRender, dcSelectJournal, dcSetPeriod, dcSelect, dcToggle, dcToggleAll, dcOpenSelected,
    dcEditSelected, dcDownloadSelected, dcArchiveSelected, dcDeleteSelected, dcToggleExportMenu, dcExport, dcOpenView, dcOpenEdit,
});
