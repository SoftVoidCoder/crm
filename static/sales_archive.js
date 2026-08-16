let salesArchiveKind = 'invoice';
let salesArchiveSearch = '';

const SALES_ARCHIVE_KINDS = [
    { key: 'invoice', label: 'Счета', singular: 'Счёт' },
    { key: 'act_upd', label: 'Акты / УПД', singular: 'Акт / УПД' },
    { key: 'waybill', label: 'Накладные', singular: 'Накладная' },
];

function salesArchiveEscape(value) {
    const div = document.createElement('div');
    div.textContent = String(value ?? '');
    return div.innerHTML;
}

function salesArchiveKindOf(doc = {}) {
    if (typeof inferredDocumentKindCode === 'function') return inferredDocumentKindCode(doc);
    return String(doc.document_kind_code || '').trim();
}

function salesArchiveStatus(value = '') {
    const statuses = {
        draft: { label: 'Черновик', tone: 'neutral' },
        registered: { label: 'Зарегистрирован', tone: 'info' },
        signed: { label: 'Подписан', tone: 'success' },
        archived: { label: 'В архиве', tone: 'neutral' },
        closed: { label: 'Закрыт', tone: 'success' },
        done: { label: 'Выполнен', tone: 'success' },
    };
    return statuses[String(value || '').trim()] || { label: 'Статус не указан', tone: 'neutral' };
}

function salesArchiveClientName(doc = {}) {
    if (typeof documentClientChoiceByReference === 'function') {
        const choice = documentClientChoiceByReference(
            doc.client_source,
            doc.client_source_id,
            doc.client_id,
            doc.correspondent || doc.sender_name || doc.recipient_name || '',
        );
        if (choice?.name) return choice.name;
    }
    if (typeof documentClientById === 'function') {
        const client = documentClientById(doc.client_id);
        if (client?.name) return client.name;
    }
    return String(doc.correspondent || doc.recipient_name || doc.sender_name || 'Клиент не указан');
}

function salesArchiveRows() {
    const query = salesArchiveSearch.trim().toLocaleLowerCase('ru-RU');
    return (Array.isArray(documentsDB) ? documentsDB : [])
        .filter(doc => salesArchiveKindOf(doc) === salesArchiveKind)
        .filter(doc => {
            if (!query) return true;
            return [doc.number, doc.subject, salesArchiveClientName(doc), doc.correspondent, doc.sender_name, doc.recipient_name]
                .some(value => String(value || '').toLocaleLowerCase('ru-RU').includes(query));
        })
        .sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
}

function salesArchiveTabCounts() {
    const rows = Array.isArray(documentsDB) ? documentsDB : [];
    return Object.fromEntries(SALES_ARCHIVE_KINDS.map(kind => [kind.key, rows.filter(doc => salesArchiveKindOf(doc) === kind.key).length]));
}

function renderSalesArchiveTabs() {
    const mount = document.getElementById('salesArchiveTabs');
    if (!mount) return;
    const counts = salesArchiveTabCounts();
    mount.innerHTML = SALES_ARCHIVE_KINDS.map(kind => `
        <button class="sales-archive-tab ${salesArchiveKind === kind.key ? 'is-active' : ''}" type="button" onclick="setSalesArchiveKind('${kind.key}')">
            <span>${kind.label}</span><strong>${Number(counts[kind.key] || 0)}</strong>
        </button>
    `).join('');
}

function renderSalesArchiveList() {
    const mount = document.getElementById('salesArchiveList');
    if (!mount) return;
    const rows = salesArchiveRows();
    const activeKind = SALES_ARCHIVE_KINDS.find(kind => kind.key === salesArchiveKind) || SALES_ARCHIVE_KINDS[0];
    if (!rows.length) {
        mount.innerHTML = `
            <div class="sales-archive-empty">
                <strong>${salesArchiveSearch ? 'По вашему запросу ничего не найдено' : `${activeKind.label} пока не добавлены`}</strong>
                <span>${salesArchiveSearch ? 'Измените запрос или сбросьте поиск.' : 'Загрузите документ в разделе «Документы компании» — после этого он автоматически появится здесь.'}</span>
                ${salesArchiveSearch ? '<button class="btn-secondary" type="button" onclick="resetSalesArchiveSearch()">Сбросить поиск</button>' : '<button class="btn-primary" type="button" onclick="navigateTo(\'documents\')">Перейти в Документы компании</button>'}
            </div>`;
        return;
    }
    mount.innerHTML = rows.map(doc => {
        const status = salesArchiveStatus(doc.status);
        const fileUrl = String(doc.file_url || '').trim();
        return `
            <article class="sales-archive-card">
                <div class="sales-archive-card__main">
                    <div class="sales-archive-card__title">
                        <span>${salesArchiveEscape(activeKind.singular)}</span>
                        <strong>${salesArchiveEscape(doc.number || `Документ №${doc.id}`)}</strong>
                        <em class="sales-archive-status sales-archive-status--${status.tone}">${salesArchiveEscape(status.label)}</em>
                    </div>
                    <h3>${salesArchiveEscape(doc.subject || 'Без названия')}</h3>
                    <div class="sales-archive-card__meta">
                        <span><small>Клиент</small><b>${salesArchiveEscape(salesArchiveClientName(doc))}</b></span>
                        <span><small>Дата</small><b>${salesArchiveEscape(doc.d_date || 'Не указана')}</b></span>
                        <span><small>Файл</small><b>${fileUrl ? 'Прикреплён' : 'Не загружен'}</b></span>
                    </div>
                </div>
                <div class="sales-archive-card__actions">
                    <button class="btn-secondary" type="button" onclick="openSalesArchiveDocument(${Number(doc.id || 0)})">Открыть карточку</button>
                    ${fileUrl ? `<a class="btn-primary" href="${salesArchiveEscape(fileUrl)}" target="_blank" rel="noopener">Открыть файл</a>` : '<span class="sales-archive-no-file">Файл отсутствует</span>'}
                </div>
            </article>`;
    }).join('');
}

async function renderSales() {
    await Promise.all([
        typeof loadDocuments === 'function' ? loadDocuments() : Promise.resolve(),
        typeof loadClients === 'function' && (!Array.isArray(clientsDB) || !clientsDB.length) ? loadClients() : Promise.resolve(),
        typeof loadCrmDeals === 'function' && (!Array.isArray(crmDealsDB) || !crmDealsDB.length) ? loadCrmDeals() : Promise.resolve(),
    ]);
    const search = document.getElementById('salesArchiveSearch');
    if (search) search.value = salesArchiveSearch;
    renderSalesArchiveTabs();
    renderSalesArchiveList();
}

function setSalesArchiveKind(kind) {
    if (!SALES_ARCHIVE_KINDS.some(item => item.key === kind)) return;
    salesArchiveKind = kind;
    renderSalesArchiveTabs();
    renderSalesArchiveList();
}

function setSalesArchiveSearch(value) {
    salesArchiveSearch = String(value || '');
    renderSalesArchiveList();
}

function resetSalesArchiveSearch() {
    salesArchiveSearch = '';
    const search = document.getElementById('salesArchiveSearch');
    if (search) search.value = '';
    renderSalesArchiveList();
}

function salesArchivePreviewRow(label, value) {
    return `<div><span>${salesArchiveEscape(label)}</span><strong>${salesArchiveEscape(String(value || '').trim() || 'Не указано')}</strong></div>`;
}

function openSalesArchiveDocument(id) {
    const doc = (Array.isArray(documentsDB) ? documentsDB : []).find(item => Number(item.id || 0) === Number(id || 0));
    if (!doc) return customAlert('Документ не найден. Обновите страницу и попробуйте ещё раз.');
    const modal = document.getElementById('genericModal');
    if (!modal) return typeof openDocumentPreview === 'function' ? openDocumentPreview(id) : null;
    const kind = SALES_ARCHIVE_KINDS.find(item => item.key === salesArchiveKindOf(doc)) || { singular: 'Документ' };
    const status = salesArchiveStatus(doc.status);
    const fileUrl = String(doc.file_url || '').trim();
    const deal = (Array.isArray(crmDealsDB) ? crmDealsDB : []).find(item => Number(item.id || 0) === Number(doc.deal_id || 0));
    const card = modal.querySelector('.modal-card');
    if (card) card.style.maxWidth = '780px';
    document.getElementById('genModalTitle').innerText = doc.number || `${kind.singular} №${doc.id}`;
    document.getElementById('genModalBody').innerHTML = `
        <div class="sales-archive-preview">
            <div class="sales-archive-preview__head">
                <div><span>${salesArchiveEscape(kind.singular)}</span><h3>${salesArchiveEscape(doc.subject || doc.number || 'Без названия')}</h3><p>${salesArchiveEscape(salesArchiveClientName(doc))}</p></div>
                <em class="sales-archive-status sales-archive-status--${status.tone}">${salesArchiveEscape(status.label)}</em>
            </div>
            <div class="sales-archive-preview__grid">
                ${salesArchivePreviewRow('Номер', doc.number)}
                ${salesArchivePreviewRow('Дата документа', doc.d_date)}
                ${salesArchivePreviewRow('Клиент / контрагент', salesArchiveClientName(doc))}
                ${salesArchivePreviewRow('Сделка', deal ? (deal.title || deal.client_name || `№${deal.id}`) : '')}
                ${salesArchivePreviewRow('Отправитель', doc.sender_name)}
                ${salesArchivePreviewRow('Получатель', doc.recipient_name)}
                ${salesArchivePreviewRow('Ответственный', doc.executor_name || doc.resolution_assignee)}
                ${salesArchivePreviewRow('Файл', fileUrl ? 'Прикреплён' : 'Не загружен')}
            </div>
            <div class="sales-archive-preview__comment"><span>Комментарий</span><p>${salesArchiveEscape(doc.resolution || doc.comment || 'Комментария нет.')}</p></div>
        </div>`;
    document.getElementById('genModalFooter').innerHTML = `
        ${fileUrl ? `<a class="btn-primary" href="${salesArchiveEscape(fileUrl)}" target="_blank" rel="noopener">Открыть файл</a>` : ''}
        <button class="btn-secondary" id="salesArchivePreviewClose" type="button">Закрыть</button>`;
    modal.style.display = 'flex';
    document.getElementById('salesArchivePreviewClose').onclick = () => {
        modal.style.display = 'none';
        if (card) card.style.maxWidth = '';
    };
}

window.renderSales = renderSales;
window.setSalesArchiveKind = setSalesArchiveKind;
window.setSalesArchiveSearch = setSalesArchiveSearch;
window.resetSalesArchiveSearch = resetSalesArchiveSearch;
window.openSalesArchiveDocument = openSalesArchiveDocument;
