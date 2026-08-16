// ==========================================
// 3. КАНЦЕЛЯРИЯ (ДОКУМЕНТЫ)
// ==========================================

let currentDocTab = 'incoming';
let documentsExtraFilter = 'all';
let selectedDocuments = new Set();
let documentsOneCImportPreviewState = null;
const documentDraftFieldIds = ['docType', 'docKind', 'docDate', 'docNumber', 'docClientSearch', 'docClientId', 'docClientSource', 'docClientSourceId', 'docContractSearch', 'docContractId', 'docExecutorName', 'docCorrespondent', 'docSubject', 'docDealId', 'docProductionOrderSearch', 'docProductionOrderId', 'docPriority'];
const TENDER_REQUIRED_DOCUMENTS = [
    { key: 'company_card', label: 'Карточка компании', keywords: ['карточк', 'реквизит', 'инн', 'кпп'] },
    { key: 'authority', label: 'Доверенность / полномочия', keywords: ['доверен', 'полномоч', 'приказ директор'] },
    { key: 'certificates', label: 'Сертификаты / лицензии', keywords: ['сертифик', 'лиценз', 'деклараци'] },
    { key: 'proposal', label: 'Коммерческое предложение', keywords: ['кп', 'коммерческ', 'предложен'] },
    { key: 'templates', label: 'Типовые письма и формы', keywords: ['письм', 'форма', 'шаблон'] },
    { key: 'tender_request', label: 'Тендерная заявка', keywords: ['тендер', 'закуп', 'заявк', 'площадк'] },
];

function bindDocumentDraftAutosave() {
    if (typeof bindFormDraftAutosave !== 'function') return;
    bindFormDraftAutosave('document', {
        formId: 'documentForm',
        fieldIds: documentDraftFieldIds,
        entityType: 'document',
        title: 'Черновик документа',
        sourceView: 'documents',
    });
}

function bindDocumentSmartHints() {
    if (typeof bindSmartFieldHints !== 'function') return;
    bindSmartFieldHints('createDocModal', [
        {
            field: 'docDate',
            validate: value => {
                if (!String(value || '').trim()) return null;
                return isValidRuDate(value)
                    ? { tone: 'hint', message: 'Дата распознана в формате дд.мм.гггг.' }
                    : { tone: 'error', message: 'Укажи дату в формате дд.мм.гггг, например 22.04.2026.' };
            },
        },
    ]);
}

function defaultDocumentDateValue() {
    const now = new Date();
    return `${String(now.getDate()).padStart(2, '0')}.${String(now.getMonth() + 1).padStart(2, '0')}.${now.getFullYear()}`;
}

const DOCUMENT_KIND_LABELS = {
    commercial_proposal: 'Коммерческое предложение',
    company_details: 'Карточка предприятия / реквизиты',
    technical_proposal: 'Техническое предложение',
    contract: 'Договор',
    contract_specification: 'Спецификация к договору',
    invoice: 'Счёт',
    act_upd: 'Акт / УПД',
    technical_task: 'Техническое задание',
    drawing: 'Чертёж',
    product_specification: 'Спецификация изделия',
    technology_card: 'Технологическая карта',
    production_order: 'Производственное задание',
    purchase_request: 'Заявка на закупку',
    supplier_order: 'Заказ поставщику',
    waybill: 'Накладная',
    quality_act: 'Акт ОТК',
    service_act: 'Сервисный / гарантийный акт',
    internal_memo: 'Служебная записка',
    other: 'Другой документ',
};

function documentKindLabel(code = '') {
    return DOCUMENT_KIND_LABELS[String(code || '').trim()] || 'Документ';
}

function inferredDocumentKindCode(doc = {}) {
    if (String(doc.document_kind_code || '').trim()) return String(doc.document_kind_code).trim();
    const text = `${doc.subject || ''} ${doc.number || ''}`.toLocaleLowerCase('ru-RU');
    if (/реквизит|карточк[аи] предприятия/.test(text)) return 'company_details';
    if (/коммерческ|(^|\s)кп([\s-]|$)/.test(text)) return 'commercial_proposal';
    if (/договор/.test(text)) return 'contract';
    if (/сч[её]т/.test(text)) return 'invoice';
    if (/акт|упд/.test(text)) return 'act_upd';
    if (/техническ.*задан|(^|\s)тз([\s-]|$)/.test(text)) return 'technical_task';
    if (/черт[её]ж/.test(text)) return 'drawing';
    if (/спецификац/.test(text)) return 'product_specification';
    return 'other';
}

window.documentKindLabel = documentKindLabel;

function documentClientById(clientId) {
    return (Array.isArray(clientsDB) ? clientsDB : []).find(client => Number(client.id || 0) === Number(clientId || 0)) || null;
}

function documentBitrixProspects() {
    const rows = (typeof outreachProspectsDB !== 'undefined' && Array.isArray(outreachProspectsDB) ? outreachProspectsDB : [])
        .filter(row => String(row.source_name || '').trim() === 'Bitrix24 API');
    const isRegularManager = String(currentUser?.role || '') === 'Менеджер' && Number(currentUser?.is_head || 0) !== 1;
    if (!isRegularManager) return rows;
    const actorEmail = String(currentUser?.email || '').trim().toLocaleLowerCase('ru-RU');
    return rows.filter(row => String(row.manager_email || '').trim().toLocaleLowerCase('ru-RU') === actorEmail);
}

function documentClientChoices() {
    const counterparties = (Array.isArray(clientsDB) ? clientsDB : []).map(client => ({
        source: 'client',
        sourceId: Number(client.id || 0),
        clientId: Number(client.id || 0),
        name: String(client.name || 'Клиент без названия'),
        inn: String(client.inn || ''),
        phone: String(client.phone || client.contact || ''),
        contact: String(client.contact || ''),
    }));
    const bitrixClients = documentBitrixProspects().map(prospect => ({
        source: 'bitrix24',
        sourceId: Number(prospect.id || 0),
        clientId: Number(prospect.converted_client_id || 0),
        name: String(prospect.company_name || prospect.contact_name || 'Клиент Bitrix24'),
        inn: String(prospect.company_inn || ''),
        phone: String(prospect.phone || ''),
        contact: String(prospect.contact_name || prospect.email || ''),
    }));
    return [...bitrixClients, ...counterparties];
}

function documentClientOptionLabel(choice = {}) {
    const sourceLabel = choice.source === 'bitrix24' ? 'Bitrix24' : 'Контрагент CRM';
    return [choice.name || 'Клиент без названия', choice.inn ? `ИНН ${choice.inn}` : '', choice.phone || '', sourceLabel].filter(Boolean).join(' — ');
}

function documentClientChoiceByReference(source = '', sourceId = 0, clientId = 0, fallbackName = '') {
    const choices = documentClientChoices();
    const sourceMatch = choices.find(item => item.source === String(source || '') && Number(item.sourceId || 0) === Number(sourceId || 0));
    if (sourceMatch) return sourceMatch;
    const clientMatch = choices.find(item => item.source === 'client' && Number(item.clientId || 0) === Number(clientId || 0));
    if (clientMatch) return clientMatch;
    const normalizedName = String(fallbackName || '').trim().toLocaleLowerCase('ru-RU');
    return choices.find(item => normalizedName && String(item.name || '').trim().toLocaleLowerCase('ru-RU') === normalizedName) || null;
}

function populateDocumentClientPicker(selectedClientId = 0, fallbackName = '', selectedSource = '', selectedSourceId = 0) {
    const options = document.getElementById('docClientOptions');
    const search = document.getElementById('docClientSearch');
    const hidden = document.getElementById('docClientId');
    const source = document.getElementById('docClientSource');
    const sourceId = document.getElementById('docClientSourceId');
    if (!options || !search || !hidden || !source || !sourceId) return;
    const choices = documentClientChoices();
    options.innerHTML = choices.map(choice => `<option value="${documentPackageEscape(documentClientOptionLabel(choice))}"></option>`).join('');
    const selected = documentClientChoiceByReference(selectedSource, selectedSourceId, selectedClientId, fallbackName);
    hidden.value = String(Number(selected?.clientId || 0));
    source.value = String(selected?.source || '');
    sourceId.value = String(Number(selected?.sourceId || 0));
    search.value = selected ? documentClientOptionLabel(selected) : String(fallbackName || '');
    handleDocumentClientChoice(search.value, false);
}

function handleDocumentClientChoice(value, fillRoute = true) {
    const hidden = document.getElementById('docClientId');
    const source = document.getElementById('docClientSource');
    const sourceId = document.getElementById('docClientSourceId');
    const hint = document.getElementById('docClientSelectionHint');
    const normalized = String(value || '').trim().toLocaleLowerCase('ru-RU');
    const choice = documentClientChoices().find(item => {
        return documentClientOptionLabel(item).toLocaleLowerCase('ru-RU') === normalized || String(item.name || '').trim().toLocaleLowerCase('ru-RU') === normalized;
    }) || null;
    if (hidden) hidden.value = String(Number(choice?.clientId || 0));
    if (source) source.value = String(choice?.source || '');
    if (sourceId) sourceId.value = String(Number(choice?.sourceId || 0));
    if (hint) {
        const sourceLabel = choice?.source === 'bitrix24' ? 'Bitrix24' : 'базы контрагентов';
        hint.textContent = choice ? `Выбран клиент из ${sourceLabel}: ${choice.name}${choice.inn ? ` · ИНН ${choice.inn}` : ''}` : (normalized ? 'Название будет сохранено вручную. Сделку можно выбрать только для клиента из CRM или Bitrix24.' : 'Можно выбрать клиента из CRM и Bitrix24 или указать название вручную.');
        hint.classList.toggle('is-selected', !!choice);
    }
    refreshDocumentDealPicker(0, choice);
    if (!fillRoute) return;
    const type = String(document.getElementById('docType')?.value || 'incoming');
    const name = String(choice?.name || value || '').trim();
    const corr = document.getElementById('docCorrespondent');
    const sender = document.getElementById('docSenderName');
    const recipient = document.getElementById('docRecipientName');
    if (corr) corr.value = name;
    if (type === 'outgoing') {
        if (recipient) recipient.value = name;
    } else if (type === 'incoming') {
        if (sender) sender.value = name;
    }
}

window.handleDocumentClientChoice = handleDocumentClientChoice;

function refreshDocumentDealPicker(selectedDealId = 0, selectedChoice = null) {
    const select = document.getElementById('docDealId');
    if (!select) return;
    const directlySelectedDeal = Number(selectedDealId || 0) > 0 && typeof crmDealsDB !== 'undefined' && Array.isArray(crmDealsDB)
        ? crmDealsDB.find(deal => Number(deal.id || 0) === Number(selectedDealId || 0))
        : null;
    const choice = selectedChoice || documentClientChoiceByReference(
        document.getElementById('docClientSource')?.value || '',
        Number(document.getElementById('docClientSourceId')?.value || 0),
        Number(document.getElementById('docClientId')?.value || 0),
        document.getElementById('docClientSearch')?.value || '',
    );
    if (!choice) {
        if (directlySelectedDeal) {
            select.innerHTML = `<option value="${Number(directlySelectedDeal.id || 0)}">${documentPackageEscape(directlySelectedDeal.title || directlySelectedDeal.client_name || `Сделка №${directlySelectedDeal.id}`)}</option>`;
            select.value = String(Number(directlySelectedDeal.id || 0));
            return;
        }
        select.innerHTML = '<option value="0">Сначала выберите клиента</option>';
        return;
    }
    const normalizedName = String(choice.name || '').trim().toLocaleLowerCase('ru-RU');
    const deals = (typeof crmDealsDB !== 'undefined' && Array.isArray(crmDealsDB) ? crmDealsDB : []).filter(deal => {
        const sameClientId = Number(choice.clientId || 0) > 0 && Number(deal.client_id || 0) === Number(choice.clientId || 0);
        const sameName = normalizedName && String(deal.client_name || deal.title || '').trim().toLocaleLowerCase('ru-RU') === normalizedName;
        return sameClientId || sameName;
    });
    select.innerHTML = `<option value="0">Без привязки к сделке</option>${deals.map(deal => `<option value="${Number(deal.id || 0)}">${documentPackageEscape(deal.title || deal.client_name || `Сделка №${deal.id}`)}</option>`).join('')}`;
    select.value = String(Number(selectedDealId || 0));
    if (!deals.length) select.innerHTML = '<option value="0">У клиента пока нет сделки</option>';
}

window.refreshDocumentDealPicker = refreshDocumentDealPicker;

function documentContractChoices() {
    const rows = typeof contractRegistryDB !== 'undefined' && Array.isArray(contractRegistryDB) ? contractRegistryDB : [];
    return rows.map(contract => ({
        id: Number(contract.id || 0),
        number: String(contract.contract_number || '').trim(),
        title: String(contract.title || '').trim(),
        client: String(contract.client_name || contract.client || '').trim(),
    })).filter(contract => contract.id > 0);
}

function documentContractLabel(contract = {}) {
    return [contract.number || `Договор №${contract.id || ''}`, contract.title || '', contract.client || ''].filter(Boolean).join(' — ');
}

function populateDocumentContractPicker(selectedContractId = 0) {
    const options = document.getElementById('docContractOptions');
    const search = document.getElementById('docContractSearch');
    const hidden = document.getElementById('docContractId');
    const hint = document.getElementById('docContractHint');
    if (!options || !search || !hidden) return;
    const choices = documentContractChoices();
    options.innerHTML = choices.map(contract => `<option value="${documentPackageEscape(documentContractLabel(contract))}"></option>`).join('');
    const selected = choices.find(contract => Number(contract.id || 0) === Number(selectedContractId || 0)) || null;
    hidden.value = String(Number(selected?.id || 0));
    search.value = selected ? documentContractLabel(selected) : '';
    if (hint) {
        hint.textContent = selected ? `Документ будет связан с договором ${selected.number || `№${selected.id}`}.` : 'Если выбрать договор, документ появится в его карточке.';
        hint.classList.toggle('is-selected', !!selected);
    }
}

function handleDocumentContractChoice(value) {
    const hidden = document.getElementById('docContractId');
    const hint = document.getElementById('docContractHint');
    const normalized = String(value || '').trim().toLocaleLowerCase('ru-RU');
    const choice = documentContractChoices().find(contract => {
        return documentContractLabel(contract).toLocaleLowerCase('ru-RU') === normalized
            || String(contract.number || '').toLocaleLowerCase('ru-RU') === normalized;
    }) || null;
    if (hidden) hidden.value = String(Number(choice?.id || 0));
    if (hint) {
        hint.textContent = choice ? `Документ будет связан с договором ${choice.number || `№${choice.id}`}.` : (normalized ? 'Выберите договор из выпадающего списка.' : 'Если выбрать договор, документ появится в его карточке.');
        hint.classList.toggle('is-selected', !!choice);
    }
}

window.handleDocumentContractChoice = handleDocumentContractChoice;

function documentProductionOrderChoices() {
    const rows = typeof productionOrdersDB !== 'undefined' && Array.isArray(productionOrdersDB) ? productionOrdersDB : [];
    return rows.map(order => ({
        id: Number(order.id || 0),
        name: String(order.order_name || `Заказ №${order.id || ''}`).trim(),
        client: String(order.client_name || '').trim(),
        stage: String(order.stage || '').trim(),
    })).filter(order => order.id > 0);
}

function documentProductionOrderLabel(order = {}) {
    return [order.name || `Заказ №${order.id || ''}`, order.client || '', order.stage || ''].filter(Boolean).join(' — ');
}

function populateDocumentProductionOrderPicker(selectedOrderId = 0) {
    const options = document.getElementById('docProductionOrderOptions');
    const search = document.getElementById('docProductionOrderSearch');
    const hidden = document.getElementById('docProductionOrderId');
    const hint = document.getElementById('docProductionOrderHint');
    if (!options || !search || !hidden) return;
    const choices = documentProductionOrderChoices();
    options.innerHTML = choices.map(order => `<option value="${documentPackageEscape(documentProductionOrderLabel(order))}"></option>`).join('');
    const selected = choices.find(order => Number(order.id || 0) === Number(selectedOrderId || 0)) || null;
    hidden.value = String(Number(selected?.id || 0));
    search.value = selected ? documentProductionOrderLabel(selected) : '';
    if (hint) {
        hint.textContent = selected ? `Документ будет связан с заказом: ${selected.name}` : 'Если выбрать заказ, документ появится в карточке этого заказа.';
        hint.classList.toggle('is-selected', !!selected);
    }
}

function handleDocumentProductionOrderChoice(value) {
    const hidden = document.getElementById('docProductionOrderId');
    const hint = document.getElementById('docProductionOrderHint');
    const normalized = String(value || '').trim().toLocaleLowerCase('ru-RU');
    const choice = documentProductionOrderChoices().find(order => {
        return documentProductionOrderLabel(order).toLocaleLowerCase('ru-RU') === normalized
            || String(order.name || '').trim().toLocaleLowerCase('ru-RU') === normalized;
    }) || null;
    if (hidden) hidden.value = String(Number(choice?.id || 0));
    if (hint) {
        hint.textContent = choice ? `Документ будет связан с заказом: ${choice.name}` : (normalized ? 'Выберите заказ из выпадающего списка.' : 'Если выбрать заказ, документ появится в карточке этого заказа.');
        hint.classList.toggle('is-selected', !!choice);
    }
}

window.handleDocumentProductionOrderChoice = handleDocumentProductionOrderChoice;

async function ensureDocumentClientSources() {
    const loaders = [];
    if (typeof loadClients === 'function') loaders.push(loadClients());
    if (typeof loadOutreachProspects === 'function') loaders.push(loadOutreachProspects());
    if (typeof loadCrmDeals === 'function') loaders.push(loadCrmDeals());
    if (typeof apiCall === 'function') {
        loaders.push(apiCall('/production/orders').then(rows => {
            if (Array.isArray(rows) && typeof productionOrdersDB !== 'undefined') productionOrdersDB = rows;
        }).catch(() => null));
        loaders.push(apiCall('/contracts').then(rows => {
            if (Array.isArray(rows) && typeof contractRegistryDB !== 'undefined') contractRegistryDB = rows;
        }).catch(() => null));
    }
    if (loaders.length) await Promise.allSettled(loaders);
}

window.ensureDocumentClientSources = ensureDocumentClientSources;

async function openDocumentModalWithPreset(preset = {}) {
    const modal = document.getElementById('createDocModal');
    if (!modal) return;
    await ensureDocumentClientSources();
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('documentForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('createDocModal');
    const typeEl = document.getElementById('docType');
    const kindEl = document.getElementById('docKind');
    const numberEl = document.getElementById('docNumber');
    const dateEl = document.getElementById('docDate');
    const senderEl = document.getElementById('docSenderName');
    const recipientEl = document.getElementById('docRecipientName');
    const sourceNumberEl = document.getElementById('docSourceNumber');
    const sourceDateEl = document.getElementById('docSourceDate');
    const deliveryMethodEl = document.getElementById('docDeliveryMethod');
    const signerEl = document.getElementById('docSignerName');
    const executorEl = document.getElementById('docExecutorName');
    const corrEl = document.getElementById('docCorrespondent');
    const subjEl = document.getElementById('docSubject');
    const priorityEl = document.getElementById('docPriority');
    const dealEl = document.getElementById('docDealId');
    const contractEl = document.getElementById('docContractId');
    const parentEl = document.getElementById('docParentId');
    const fileEl = document.getElementById('docFile');
    if (typeEl) typeEl.value = preset.type || 'outgoing';
    if (kindEl) kindEl.value = preset.document_kind_code || preset.document_kind || 'commercial_proposal';
    if (dateEl) dateEl.value = preset.d_date || defaultDocumentDateValue();
    if (senderEl) senderEl.value = preset.sender_name || '';
    if (recipientEl) recipientEl.value = preset.recipient_name || '';
    if (sourceNumberEl) sourceNumberEl.value = preset.source_number || '';
    if (sourceDateEl) sourceDateEl.value = preset.source_date || '';
    if (deliveryMethodEl) deliveryMethodEl.value = preset.delivery_method || '';
    if (signerEl) signerEl.value = preset.signer_name || '';
    if (executorEl) executorEl.value = preset.executor_name || currentUser?.name || '';
    if (corrEl) corrEl.value = preset.correspondent || '';
    if (subjEl) subjEl.value = preset.subject || '';
    if (priorityEl) priorityEl.checked = preset.priority === 'high';
    if (parentEl) parentEl.value = String(Number(preset.parent_id || 0));
    if (fileEl) fileEl.value = '';
    updateDocumentFileName();
    populateDocumentClientPicker(Number(preset.client_id || 0), preset.client_name || preset.correspondent || '', preset.client_source || '', Number(preset.client_source_id || 0));
    refreshDocumentDealPicker(Number(preset.deal_id || 0));
    populateDocumentContractPicker(Number(preset.contract_id || 0));
    populateDocumentProductionOrderPicker(Number(preset.production_order_id || 0));
    if (dealEl) dealEl.value = String(Number(preset.deal_id || 0));
    if (contractEl) contractEl.value = String(Number(preset.contract_id || 0));
    modal.style.display = 'flex';
    if (numberEl) {
        if (preset.number) numberEl.value = preset.number;
        else window.generateDocNumber?.();
    }
    syncDocumentKindWithDirection();
    const flow = modal.querySelector('.document-create-flow');
    if (flow) flow.scrollTop = 0;
}

window.openDocumentModalWithPreset = openDocumentModalWithPreset;

function closeDocumentCreateModal() {
    const modal = document.getElementById('createDocModal');
    if (modal) modal.style.display = 'none';
}

function updateDocumentFileName() {
    const file = document.getElementById('docFile')?.files?.[0] || null;
    const label = document.getElementById('docFileName');
    if (label) label.textContent = file ? file.name : 'Выберите файл с компьютера';
}

function syncDocumentKindWithDirection() {
    const direction = document.getElementById('docType')?.value || 'outgoing';
    const kind = document.getElementById('docKind');
    if (!kind) return;
    if (direction === 'internal_memo' && kind.value !== 'internal_memo') kind.value = 'internal_memo';
    if (direction !== 'internal_memo' && kind.value === 'internal_memo') kind.value = direction === 'outgoing' ? 'commercial_proposal' : 'other';
    window.generateDocNumber?.();
}

window.closeDocumentCreateModal = closeDocumentCreateModal;
window.updateDocumentFileName = updateDocumentFileName;
window.syncDocumentKindWithDirection = syncDocumentKindWithDirection;

window.duplicateDocument = function(id) {
    const doc = documentsDB.find(item => Number(item.id) === Number(id));
    if (!doc) return;
    openDocumentModalWithPreset({
        type: doc.type || 'incoming',
        document_kind_code: doc.document_kind_code || 'other',
        d_date: defaultDocumentDateValue(),
        number: '',
        sender_name: doc.sender_name || '',
        recipient_name: doc.recipient_name || '',
        source_number: doc.source_number || '',
        source_date: doc.source_date || '',
        delivery_method: doc.delivery_method || '',
        signer_name: doc.signer_name || '',
        executor_name: doc.executor_name || '',
        correspondent: doc.correspondent || '',
        subject: doc.subject ? `${doc.subject} (копия)` : '',
        priority: doc.priority || 'normal',
        client_id: doc.client_id || 0,
        client_source: doc.client_source || '',
        client_source_id: doc.client_source_id || 0,
        deal_id: 0,
        contract_id: doc.contract_id || 0,
        production_order_id: doc.production_order_id || 0,
        parent_id: doc.id || 0,
    });
    window.generateDocNumber?.();
    if (typeof showToast === 'function') showToast('Документы', 'Карточка похожего документа подготовлена');
};

function switchDocTab(tab) {
    currentDocTab = tab;
    const map = {
        incoming: 'tabDocIncoming',
        outgoing: 'tabDocOutgoing',
        internal: 'tabDocInternal',
        drafts: 'tabDocDrafts',
    };
    Object.entries(map).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (!el) return;
        const on = tab === key;
        el.classList.toggle('is-active', on);
        el.classList.toggle('active', on);
        el.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    const registryCopy = {
        incoming: {
            title: 'Входящие документы',
            hint: 'Письма, запросы, акты и другие документы, которые компания получила извне.',
        },
        outgoing: {
            title: 'Исходящие документы',
            hint: 'Официальные письма, ответы и коммерческие предложения, отправленные клиентам и партнёрам.',
        },
        internal: {
            title: 'Внутренние документы компании',
            hint: 'Приказы, служебные записки, регламенты и инструкции для сотрудников.',
        },
        drafts: {
            title: 'Не закончено',
            hint: 'Документы, которые сохранили, но ещё не зарегистрировали в общем архиве.',
        },
    }[tab] || {};
    const title = document.getElementById('documentsRegistryTitle');
    const hint = document.getElementById('documentsRegistryHint');
    if (title) title.textContent = registryCopy.title || 'Документы';
    if (hint) hint.textContent = registryCopy.hint || '';
    renderDocuments();
}

function documentMatchesExtraFilter(doc) {
    if (documentsExtraFilter === 'no_scan') return !doc.file_url;
    if (documentsExtraFilter === 'high_priority') return doc.priority === 'high';
    return true;
}

function getFilteredDocuments() {
    const searchInput = document.getElementById('documentRegistrySearch');
    const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
    const filtered = documentsDB.filter(doc => {
        const matchesTab = currentDocTab === 'drafts'
            ? doc.status === 'draft'
            : currentDocTab === 'internal'
                ? String(doc.type || '').startsWith('internal_') && doc.status !== 'draft'
                : doc.type === currentDocTab && doc.status !== 'draft';
        if (!matchesTab) return false;
        if (!documentMatchesExtraFilter(doc)) return false;
        if (!query) return true;
        const assignedChoice = documentClientChoiceByReference(doc.client_source, doc.client_source_id, doc.client_id, doc.correspondent || doc.sender_name || doc.recipient_name || '');
        const assignedDeal = (typeof crmDealsDB !== 'undefined' && Array.isArray(crmDealsDB) ? crmDealsDB : []).find(deal => Number(deal.id || 0) === Number(doc.deal_id || 0));
        const assignedContract = documentContractChoices().find(contract => Number(contract.id || 0) === Number(doc.contract_id || 0));
        const haystack = [
            doc.number || '',
            documentKindLabel(inferredDocumentKindCode(doc)),
            doc.correspondent || '',
            doc.sender_name || '',
            doc.recipient_name || '',
            doc.source_number || '',
            doc.signer_name || '',
            doc.executor_name || '',
            doc.subject || '',
            doc.status || '',
            assignedChoice?.name || '',
            assignedChoice?.inn || '',
            assignedChoice?.phone || '',
            assignedDeal?.title || '',
            assignedDeal?.client_name || '',
            assignedContract?.number || '',
            assignedContract?.title || '',
            assignedContract?.client || '',
            Number(doc.contract_id || 0) > 0 ? `договор ${Number(doc.contract_id)}` : '',
        ].join(' ').toLowerCase();
        return haystack.includes(query);
    });
    filtered.sort((a, b) => (b.priority === 'high' ? 1 : 0) - (a.priority === 'high' ? 1 : 0));
    return filtered;
}

window.clearDocumentRegistrySearch = function() {
    const input = document.getElementById('documentRegistrySearch');
    if (input) input.value = '';
    renderDocuments();
};

function setDocumentsExtraFilter(filter = 'all') {
    documentsExtraFilter = filter || 'all';
    renderDocuments();
}

function updateDocumentsFilterButtons() {
    const map = {
        all: 'documentsExtraAllBtn',
        no_scan: 'documentsExtraNoScanBtn',
        high_priority: 'documentsExtraHighPriorityBtn',
    };
    Object.values(map).forEach(id => document.getElementById(id)?.classList.remove('is-filter-active'));
    document.getElementById(map[documentsExtraFilter] || map.all)?.classList.add('is-filter-active');
}

function registerDocumentsSavedFilters() {
    if (typeof registerWorkbenchSavedFilterScope !== 'function') return;
    registerWorkbenchSavedFilterScope('documents', {
        mountId: 'documentsSavedFiltersMount',
        defaultTitle: documentsExtraFilter === 'no_scan' ? 'Документы без скана' : 'Мой фильтр документов',
        getPayload: () => ({
            currentDocTab,
            documentsExtraFilter,
            query: document.getElementById('documentRegistrySearch')?.value || '',
        }),
        applyPayload: payload => {
            currentDocTab = payload.currentDocTab || 'incoming';
            documentsExtraFilter = payload.documentsExtraFilter || 'all';
            const searchInput = document.getElementById('documentRegistrySearch');
            if (searchInput) searchInput.value = payload.query || '';
            switchDocTab(currentDocTab);
        },
        presets: [
            { id: 'documentsExtraAllBtn', key: 'all', label: 'Все', payload: () => ({ currentDocTab, documentsExtraFilter: 'all', query: document.getElementById('documentRegistrySearch')?.value || '' }) },
            { id: 'documentsExtraNoScanBtn', key: 'no_scan', label: 'Без скана', payload: () => ({ currentDocTab, documentsExtraFilter: 'no_scan', query: document.getElementById('documentRegistrySearch')?.value || '' }) },
            { id: 'documentsExtraHighPriorityBtn', key: 'high_priority', label: 'Приоритетные', payload: () => ({ currentDocTab, documentsExtraFilter: 'high_priority', query: document.getElementById('documentRegistrySearch')?.value || '' }) },
        ],
        updateState: updateDocumentsFilterButtons,
    });
}

function pruneSelectedDocuments() {
    const existingIds = new Set((documentsDB || []).map(doc => Number(doc.id)));
    selectedDocuments.forEach(id => {
        if (!existingIds.has(Number(id))) selectedDocuments.delete(Number(id));
    });
}

function getSelectedDocumentRows() {
    pruneSelectedDocuments();
    return documentsDB.filter(doc => selectedDocuments.has(Number(doc.id)));
}

function updateDocumentsBulkBar(visibleDocs = getFilteredDocuments()) {
    const summary = document.getElementById('documentsBulkSummary');
    const toolbar = document.getElementById('documentsBulkToolbar');
    const selectAllCheckbox = document.getElementById('documentsSelectAllCheckbox');
    const selectedCount = selectedDocuments.size;
    const visibleCount = visibleDocs.length;
    if (summary) {
        summary.innerText = selectedCount
            ? `Выделено документов: ${selectedCount}`
            : `Выделение: 0 документов`;
    }
    if (toolbar) toolbar.hidden = selectedCount === 0;
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = visibleCount > 0 && visibleDocs.every(doc => selectedDocuments.has(Number(doc.id)));
        selectAllCheckbox.indeterminate = visibleCount > 0 && !selectAllCheckbox.checked && visibleDocs.some(doc => selectedDocuments.has(Number(doc.id)));
    }
    ['documentsBulkRegisterBtn', 'documentsBulkArchiveBtn', 'documentsBulkExportBtn', 'documentsBulkDeleteBtn', 'documentsBulkClearBtn'].forEach(id => {
        const button = document.getElementById(id);
        if (button) button.disabled = selectedCount === 0;
    });
}

function toggleDocumentSelection(id, checked) {
    const numericId = Number(id);
    if (checked) selectedDocuments.add(numericId);
    else selectedDocuments.delete(numericId);
    updateDocumentsBulkBar();
}

window.toggleAllDocumentsOnPage = function(forceState) {
    const visibleDocs = getFilteredDocuments();
    if (!visibleDocs.length) return;
    const shouldSelect = typeof forceState === 'boolean'
        ? forceState
        : !visibleDocs.every(doc => selectedDocuments.has(Number(doc.id)));
    visibleDocs.forEach(doc => {
        if (shouldSelect) selectedDocuments.add(Number(doc.id));
        else selectedDocuments.delete(Number(doc.id));
    });
    renderDocuments();
};

window.clearSelectedDocuments = function() {
    selectedDocuments.clear();
    updateDocumentsBulkBar();
    renderDocuments();
};

function documentPackageEscape(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function parseDocumentsOneCImportPayload() {
    const payloadText = (document.getElementById('documentsOneCImportPayload')?.value || '').trim();
    if (!payloadText) {
        customAlert('Вставь JSON-массив или таблицу документов из 1С.');
        return null;
    }
    try {
        const items = JSON.parse(payloadText);
        if (!Array.isArray(items) || !items.length) {
            customAlert('Нужен непустой массив документов.');
            return null;
        }
        return items;
    } catch (error) {
        const rows = parseDocumentsOneCPastedTable(payloadText);
        if (rows.length) return rows;
        customAlert('Выгрузка не похожа на JSON или таблицу. Скопируй из Excel строку заголовков и строки документов.');
        return null;
    }
}

function parseDocumentsOneCPastedTable(text) {
    const lines = String(text || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    if (lines.length < 2) return [];
    const delimiter = lines[0].includes('\t') ? '\t' : (lines[0].includes(';') ? ';' : ',');
    const headers = lines[0].split(delimiter).map(item => item.trim()).filter(Boolean);
    if (!headers.length) return [];
    return lines.slice(1).map(line => {
        const cells = line.split(delimiter);
        const row = {};
        headers.forEach((header, index) => { row[header] = (cells[index] || '').trim(); });
        return row;
    }).filter(row => Object.values(row).some(Boolean));
}

function renderDocumentsOneCImportPreview() {
    const mount = document.getElementById('documentsOneCImportPreview');
    if (!mount) return;
    const preview = documentsOneCImportPreviewState;
    if (!preview) {
        mount.innerHTML = '<div class="nsi-empty-row" style="padding:14px;">Проверка ещё не запускалась. Вставь выгрузку из 1С и нажми «Проверить перенос».</div>';
        return;
    }
    const rows = Array.isArray(preview.rows) ? preview.rows : [];
    const stateLabel = { ready: 'Готово', conflict: 'Проверить', error: 'Ошибка' };
    const stateClass = { ready: 'status-completed', conflict: 'status-active', error: 'status-overdue' };
    mount.innerHTML = `
        <div class="metric-grid" style="grid-template-columns:repeat(4,minmax(120px,1fr)); margin-bottom:12px;">
            <div class="metric-card"><div class="metric-title">Документов</div><div class="metric-value">${preview.total || 0}</div></div>
            <div class="metric-card"><div class="metric-title">Готово</div><div class="metric-value">${preview.ready || 0}</div></div>
            <div class="metric-card warning"><div class="metric-title">Проверить</div><div class="metric-value">${preview.conflicts || 0}</div></div>
            <div class="metric-card warning"><div class="metric-title">Ошибки</div><div class="metric-value">${preview.errors || 0}</div></div>
        </div>
        <div class="client360-list">
            ${rows.map(row => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${documentPackageEscape(row.index)}. ${documentPackageEscape(row.normalized?.number || row.external_id || 'без номера')} ${row.target_id ? `#${documentPackageEscape(row.target_id)}` : ''}</div>
                        <div class="client360-item-meta">${documentPackageEscape(row.normalized?.d_date || 'без даты')} · ${documentPackageEscape(row.normalized?.correspondent || 'без контрагента')} · ${documentPackageEscape(row.normalized?.subject || 'без темы')}</div>
                        ${(row.errors || []).map(text => `<div class="finance-row-meta" style="color:#dc2626;">${documentPackageEscape(text)}</div>`).join('')}
                        ${(row.warnings || []).map(text => `<div class="finance-row-meta" style="color:#b45309;">${documentPackageEscape(text)}</div>`).join('')}
                        ${(row.changes || []).length ? `<div class="finance-row-meta">${row.changes.map(change => `${documentPackageEscape(change.field)}: ${documentPackageEscape(change.before || 'пусто')} -> ${documentPackageEscape(change.after || 'пусто')}`).join(' · ')}</div>` : ''}
                    </div>
                    <span class="status-badge ${stateClass[row.state] || 'status-active'}">${stateLabel[row.state] || 'Проверить'}</span>
                </div>
            `).join('') || '<div class="nsi-empty-row">Документы не найдены.</div>'}
        </div>
    `;
}

window.clearDocumentsOneCImport = function() {
    const payload = document.getElementById('documentsOneCImportPayload');
    const note = document.getElementById('documentsOneCImportNote');
    if (payload) payload.value = '';
    if (note) note.value = '';
    documentsOneCImportPreviewState = null;
    renderDocumentsOneCImportPreview();
};

window.previewDocumentsOneCImport = async function() {
    const items = parseDocumentsOneCImportPayload();
    if (!items) return null;
    const preview = await apiCall('/documents/1c/import/preview', 'POST', {
        items,
        source_system: '1C',
        actor_note: (document.getElementById('documentsOneCImportNote')?.value || '').trim(),
    });
    if (!preview || preview.error) {
        customAlert(preview?.message || preview?.error || 'Не удалось проверить перенос документов.');
        return null;
    }
    documentsOneCImportPreviewState = preview;
    renderDocumentsOneCImportPreview();
    return preview;
};

window.applyDocumentsOneCImport = async function() {
    const items = parseDocumentsOneCImportPayload();
    if (!items) return;
    const preview = await window.previewDocumentsOneCImport();
    if (!preview) return;
    if ((preview.errors || 0) > 0) {
        return customAlert('Документы не перенесены: исправь ошибки в предпросмотре.');
    }
    const confirmed = await customConfirm(`Перенести документов: ${preview.ready || 0}?`);
    if (!confirmed) return;
    const res = await apiCall('/documents/1c/import', 'POST', {
        items,
        source_system: '1C',
        actor_note: (document.getElementById('documentsOneCImportNote')?.value || '').trim(),
    });
    if (!res || res.error) {
        if (res?.status === 'validation_failed') {
            documentsOneCImportPreviewState = res;
            renderDocumentsOneCImportPreview();
            return customAlert(res?.message || 'Документы не перенесены: исправь ошибки структуры.');
        }
        return customAlert(res?.message || res?.error || 'Не удалось перенести документы.');
    }
    documentsOneCImportPreviewState = null;
    await loadDocuments();
    renderDocuments();
    renderDocumentsOneCImportPreview();
    showToast('Документы', `Перенос завершён: создано ${res.created || 0}, обновлено ${res.updated || 0}`);
};

async function loadDocumentPackages() {
    const res = await apiCall('/docflow/packages?limit=80');
    documentPackagesDB = res && !res.error ? (res.items || []) : [];
    return documentPackagesDB;
}

function renderDocumentPackagesMount() {
    const mount = document.getElementById('documentPackagesMount');
    if (!mount) return;
    const packages = Array.isArray(documentPackagesDB) ? documentPackagesDB.slice(0, 8) : [];
    const selectedCount = selectedDocuments.size;
    mount.innerHTML = `
        <div class="surface-card surface-card--padded toolbar-strip" style="display:flex; justify-content:space-between; gap:14px; align-items:flex-start; flex-wrap:wrap;">
            <div>
                <div class="section-title" style="font-size:16px;">Пакет документов</div>
                <div class="section-subtitle">Комплект: договор, счет, УПД, акт, переписка, согласования и подписи.</div>
                <div style="font-size:12px; color:var(--secondary); margin-top:4px;">Выбрано документов: ${selectedCount}</div>
            </div>
            <div class="view-actions">
                <button class="btn-primary" onclick="assembleDocumentPackageFromSelection()">Собрать пакет</button>
                <button class="btn-secondary" onclick="loadDocumentPackages().then(renderDocumentPackagesMount)">Обновить</button>
            </div>
            <div style="width:100%; display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:10px;">
                ${packages.length ? packages.map(pkg => {
                    const summary = pkg.summary || {};
                    const itemsTotal = summary.items_total ?? (pkg.items || []).length;
                    return `
                        <div class="surface-card surface-card--soft surface-card--padded">
                            <div style="display:flex; justify-content:space-between; gap:10px; align-items:flex-start;">
                                <div>
                                    <div class="client360-item-title">${documentPackageEscape(pkg.package_number || `Пакет #${pkg.id}`)}</div>
                                    <div class="client360-item-meta">${documentPackageEscape(pkg.title || '')} · документов ${documentPackageEscape(summary.documents_total || itemsTotal || 0)} · подписано ${documentPackageEscape(summary.signed_documents_total || 0)}</div>
                                </div>
                                <span class="status-badge">${documentPackageEscape(pkg.status || 'draft')}</span>
                            </div>
                            <div class="view-actions" style="margin-top:10px;">
                                <button class="btn-secondary" onclick="sendDocumentPackageApproval(${Number(pkg.id || 0)})">Согласовать</button>
                                <button class="btn-secondary" onclick="signDocumentPackage(${Number(pkg.id || 0)})">Подписать</button>
                                <button class="btn-secondary" onclick="downloadDocumentPackageRegistry(${Number(pkg.id || 0)})">Реестр</button>
                                <button class="btn-secondary" onclick="downloadDocumentPackageZip(${Number(pkg.id || 0)})">ZIP</button>
                            </div>
                        </div>`;
                }).join('') : '<div class="client360-empty">Пакеты документов пока не собраны.</div>'}
            </div>
        </div>`;
}

async function assembleDocumentPackageFromSelection() {
    const ids = Array.from(selectedDocuments).map(Number).filter(Boolean);
    if (!ids.length) return customAlert('Выбери документы галочками, потом собери пакет.');
    const title = await customPrompt('Название пакета документов:', `Пакет документов ${new Date().toLocaleDateString('ru-RU')}`);
    if (title === null) return;
    const res = await apiCall('/docflow/packages', 'POST', { title, document_ids: ids, package_kind: 'contract_set' });
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось собрать пакет.');
    selectedDocuments.clear();
    await loadDocumentPackages();
    renderDocuments();
    showToast('Документы', 'Пакет собран');
}

async function assembleTenderPackageFromSelection() {
    const ids = Array.from(selectedDocuments).map(Number).filter(Boolean);
    if (!ids.length) return customAlert('Выбери документы тендерного комплекта галочками.');
    const title = await customPrompt('Название тендерного пакета:', `Тендерный пакет ${new Date().toLocaleDateString('ru-RU')}`);
    if (title === null) return;
    const res = await apiCall('/docflow/packages', 'POST', { title, document_ids: ids, package_kind: 'tender_set' });
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось собрать тендерный пакет.');
    selectedDocuments.clear();
    await loadDocumentPackages();
    renderDocuments();
    showToast('Документы', 'Тендерный пакет собран');
}

window.assembleTenderPackageFromSelection = assembleTenderPackageFromSelection;

window.openTenderDocumentPreset = function() {
    openDocumentModalWithPreset({
        type: 'outgoing',
        correspondent: 'Тендерная площадка',
        subject: 'Тендерная заявка / комплект документов',
        delivery_method: 'ЭДО / площадка',
        priority: 'high',
        executor_name: currentUser?.name || '',
        resolution: 'Проверить комплект и сроки подачи',
    });
};

window.openReceptionIncomingPreset = function() {
    openDocumentModalWithPreset({
        type: 'incoming',
        sender_name: 'Ресепшен',
        correspondent: 'Входящее обращение',
        subject: 'Обращение клиента / звонок / входящий документ',
        delivery_method: 'Ресепшен',
        priority: 'high',
        executor_name: currentUser?.name || '',
    });
};

async function scheduleTenderDocumentReview() {
    const tender = buildTenderControl(allDocuments || []);
    const target = tender.states.find(item => item.document && ['expiring', 'expired', 'needs_file'].includes(item.status));
    if (!target) return customAlert('Нет тендерных документов, по которым нужно ставить напоминание.');
    const assignee = await customPrompt('Кому поставить напоминание по тендерному документу?', target.document.executor_name || target.document.resolution_assignee || currentUser?.name || '');
    if (assignee === null) return;
    const deadline = await customPrompt('Срок проверки документа (дд.мм.гггг).', target.document.resolution_deadline || new Date().toLocaleDateString('ru-RU'));
    if (deadline === null) return;
    await persistDocumentQuickUpdate(Number(target.document.id || 0), {
        executor_name: String(assignee || '').trim(),
        resolution_assignee: String(assignee || '').trim(),
        resolution_deadline: String(deadline || '').trim(),
        resolution: [target.document.resolution || '', `Проверить тендерный документ: ${target.label}. Статус: ${target.statusLabel}.`].filter(Boolean).join('\n'),
        status: target.document.status || 'review',
    }, 'Напоминание по тендерному документу поставлено');
}

async function sendDocumentPackageApproval(packageId) {
    const res = await apiCall(`/docflow/packages/${Number(packageId || 0)}/send_approval`, 'POST', {});
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось отправить пакет на согласование.');
    await loadDocumentPackages();
    renderDocumentPackagesMount();
    showToast('Документы', 'Пакет отправлен на согласование');
}

async function signDocumentPackage(packageId) {
    const confirmed = await customConfirm('Подписать комплект и зафиксировать checksum-реестр пакета?');
    if (!confirmed) return;
    const res = await apiCall(`/docflow/packages/${Number(packageId || 0)}/sign`, 'POST', { strict: 0 });
    if (!res || res.error) return customAlert(res?.message || res?.error || 'Не удалось подписать пакет.');
    await loadDocumentPackages();
    renderDocumentPackagesMount();
    showToast('Документы', res.package?.status === 'signed' ? 'Пакет подписан' : 'Пакет подписан с пробелами');
}

function downloadDocumentPackageRegistry(packageId) {
    window.open(`${window.API_URL}/docflow/packages/${Number(packageId || 0)}/export_registry`, '_blank');
}

function downloadDocumentPackageZip(packageId) {
    window.open(`${window.API_URL}/docflow/packages/${Number(packageId || 0)}/export_zip`, '_blank');
}

function buildDocumentUpdatePayload(doc, overrides = {}) {
    return {
        type: doc.type,
        document_kind_code: doc.document_kind_code || 'other',
        number: doc.number,
        d_date: doc.d_date || '',
        correspondent: doc.correspondent || '',
        sender_name: doc.sender_name || '',
        recipient_name: doc.recipient_name || '',
        source_number: doc.source_number || '',
        source_date: doc.source_date || '',
        delivery_method: doc.delivery_method || '',
        signer_name: doc.signer_name || '',
        executor_name: doc.executor_name || '',
        subject: doc.subject || '',
        status: doc.status || 'registered',
        client_id: Number(doc.client_id || 0),
        client_source: doc.client_source || '',
        client_source_id: Number(doc.client_source_id || 0),
        deal_id: Number(doc.deal_id || 0),
        project_id: Number(doc.project_id || 0),
        contract_id: Number(doc.contract_id || 0),
        object_id: Number(doc.object_id || 0),
        production_order_id: Number(doc.production_order_id || 0),
        parent_id: Number(doc.parent_id || 0),
        priority: doc.priority || 'normal',
        resolution: doc.resolution || '',
        resolution_author: doc.resolution_author || '',
        resolution_deadline: doc.resolution_deadline || '',
        resolution_assignee: doc.resolution_assignee || '',
        resolution_task_id: Number(doc.resolution_task_id || 0),
        ...overrides,
    };
}

function findDocumentRow(id) {
    return documentsDB.find(item => Number(item.id || 0) === Number(id || 0)) || null;
}

function isDocumentClosedState(value) {
    const normalized = String(value || '').trim().toLowerCase();
    return ['archived', 'signed', 'closed', 'done'].includes(normalized);
}

function isDocumentOverdue(row) {
    if (!row?.resolution_deadline || isDocumentClosedState(row.status)) return false;
    const parts = String(row.resolution_deadline).split('.');
    if (parts.length !== 3) return false;
    const due = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
    if (Number.isNaN(due.getTime())) return false;
    due.setHours(0, 0, 0, 0);
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    return due < now;
}

function documentParseRuDate(value) {
    const parts = String(value || '').split('.');
    if (parts.length !== 3) return null;
    const date = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
    if (Number.isNaN(date.getTime())) return null;
    date.setHours(0, 0, 0, 0);
    return date;
}

function documentDaysUntil(value) {
    const date = documentParseRuDate(value);
    if (!date) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((date - today) / 86400000);
}

function tenderDocumentFreshness(row) {
    if (!row) return { label: 'Нет', tone: 'critical', status: 'missing', days: null };
    if (!row.file_url) return { label: 'Требует файл', tone: 'attention', status: 'needs_file', days: null };
    const deadline = row.retention_until || row.resolution_deadline || '';
    const days = documentDaysUntil(deadline);
    if (days !== null && days < 0) return { label: 'Просрочен', tone: 'critical', status: 'expired', days };
    if (days !== null && days <= 30) return { label: 'Скоро истекает', tone: 'attention', status: 'expiring', days };
    if (isDocumentOverdue(row)) return { label: 'Просрочен', tone: 'critical', status: 'expired', days };
    return { label: 'Актуален', tone: 'positive', status: 'active', days };
}

function isRecentDocument(row) {
    if (!row?.d_date) return false;
    const parts = String(row.d_date).split('.');
    if (parts.length !== 3) return false;
    const docDate = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
    if (Number.isNaN(docDate.getTime())) return false;
    const now = new Date();
    const diff = Math.abs(now.getTime() - docDate.getTime());
    return diff <= 7 * 24 * 60 * 60 * 1000;
}

function renderDocumentsOpsCounters(rows) {
    const mount = document.getElementById('documentsOpsCounters');
    if (!mount) return;
    const controlled = rows.filter(item => item.resolution_task_id || item.resolution_deadline || item.resolution_assignee).length;
    const overdue = rows.filter(isDocumentOverdue).length;
    const needsAnswer = rows.filter(item => String(item.type || '').toLowerCase() === 'incoming' && !isDocumentClosedState(item.status) && (item.resolution_deadline || item.resolution_task_id)).length;
    const fresh = rows.filter(isRecentDocument).length;
    const withoutFile = rows.filter(item => !item.file_url && item.status !== 'draft').length;
    const counters = [
        { label: 'Добавлено недавно', value: fresh, note: 'за последние 7 дней', tone: 'accent' },
        { label: 'Нужно выполнить', value: controlled || needsAnswer, note: 'есть ответственный или срок', tone: controlled || needsAnswer ? 'warning' : 'positive' },
        { label: 'Срок уже прошёл', value: overdue, note: 'требует внимания', tone: overdue ? 'critical' : 'positive' },
        { label: 'Нет файла', value: withoutFile, note: 'нужно прикрепить скан или PDF', tone: withoutFile ? 'warning' : 'positive' },
    ];
    mount.innerHTML = counters.map(item => `
        <article class="documents-ops-counter documents-ops-counter--${item.tone}">
            <div class="documents-ops-counter__label">${item.label}</div>
            <div class="documents-ops-counter__value">${item.value}</div>
            <div class="documents-ops-counter__note">${item.note}</div>
        </article>
    `).join('');
}

function documentText(row) {
    return [row?.number, row?.subject, row?.correspondent, row?.sender_name, row?.recipient_name, row?.resolution, row?.type]
        .join(' ')
        .toLowerCase();
}

function tenderRequirementState(rows, requirement) {
    const match = rows.find(row => requirement.keywords.some(keyword => documentText(row).includes(keyword)));
    if (!match) return { ...requirement, status: 'missing', tone: 'critical', statusLabel: 'Нет', document: null };
    const freshness = tenderDocumentFreshness(match);
    if (freshness.status === 'active') return { ...requirement, status: 'ready', tone: freshness.tone, statusLabel: freshness.label, document: match, freshness };
    return { ...requirement, status: freshness.status, tone: freshness.tone, statusLabel: freshness.label, document: match, freshness };
}

function buildTenderControl(rows = []) {
    const tenderDocs = rows.filter(row => /тендер|закуп|заявк|площадк|кп|сертифик|лиценз|доверен|реквизит/i.test(documentText(row)));
    const states = TENDER_REQUIRED_DOCUMENTS.map(item => tenderRequirementState(rows, item));
    const ready = states.filter(item => item.status === 'ready').length;
    const missing = states.filter(item => item.status === 'missing').length;
    const attention = states.filter(item => item.status !== 'ready' && item.status !== 'missing').length;
    const expiring = states.filter(item => item.status === 'expiring').length;
    const expired = states.filter(item => item.status === 'expired').length;
    const readiness = Math.round((ready / states.length) * 100);
    const tenderPackages = (Array.isArray(documentPackagesDB) ? documentPackagesDB : []).filter(pkg => String(pkg.package_kind || '').includes('tender') || /тендер/i.test(pkg.title || ''));
    return { tenderDocs, states, ready, missing, attention, expiring, expired, readiness, tenderPackages };
}

function renderTenderDirectorMount(rows = []) {
    const mount = document.getElementById('tenderDirectorMount');
    if (!mount) return;
    const tender = buildTenderControl(rows);
    mount.innerHTML = `
        <section class="documents-director-card">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Тендерный пакет документов</h3>
                    <p class="section-subtitle">Чеклист стандартного комплекта: реквизиты, полномочия, сертификаты, КП, формы и заявка.</p>
                </div>
                <div class="view-actions">
                    <span class="crm-inline-pill crm-inline-pill--${tender.missing ? 'critical' : tender.attention ? 'attention' : 'positive'}">${tender.readiness}% готово</span>
                    <button class="btn-secondary" onclick="openTenderDocumentPreset()">+ Документ тендера</button>
                    <button class="btn-secondary" onclick="assembleTenderPackageFromSelection()">Собрать тендерный пакет</button>
                    <button class="btn-secondary" onclick="scheduleTenderDocumentReview()">Напомнить по срокам</button>
                    <button class="btn-secondary" onclick="exportTenderReceptionDirectorReport('tender')">Отчёт</button>
                </div>
            </div>
            <div class="documents-director-grid">
                <div class="documents-director-metrics">
                    <div><span>Документов по тендерам</span><strong>${tender.tenderDocs.length}</strong></div>
                    <div><span>Готово</span><strong>${tender.ready}</strong></div>
                    <div><span>Проверить</span><strong>${tender.attention}</strong></div>
                    <div><span>Не хватает</span><strong>${tender.missing}</strong></div>
                    <div><span>Скоро истекает</span><strong>${tender.expiring}</strong></div>
                    <div><span>Просрочено</span><strong>${tender.expired}</strong></div>
                </div>
                <div class="documents-checklist">
                    ${tender.states.map(item => `
                        <div class="documents-checklist-item">
                            <span class="crm-inline-pill crm-inline-pill--${item.tone}">${documentPackageEscape(item.statusLabel)}</span>
                            <strong>${documentPackageEscape(item.label)}</strong>
                            <small>${documentPackageEscape(item.document?.number || item.document?.subject || 'добавить в пакет')} · ${documentPackageEscape(item.document?.executor_name || item.document?.resolution_assignee || 'ответственный не задан')}</small>
                            <em>${documentPackageEscape(item.document?.retention_until || item.document?.resolution_deadline || item.document?.subject || item.status)}</em>
                        </div>
                    `).join('')}
                </div>
            </div>
            <div class="documents-director-grid" style="margin-top:12px;">
                <div class="documents-checklist">
                    <div class="documents-checklist-item"><span class="crm-inline-pill crm-inline-pill--attention">Архив</span><strong>Отправленные комплекты</strong><small>${tender.tenderPackages.length} пакетов</small><em>${tender.tenderPackages.slice(0, 3).map(pkg => pkg.package_number || pkg.title || `#${pkg.id}`).join(', ') || 'пока нет'}</em></div>
                </div>
                <div class="documents-checklist">
                    ${(tender.states.filter(item => ['expiring', 'expired', 'needs_file', 'missing'].includes(item.status)).slice(0, 3).map(item => `
                        <div class="documents-checklist-item">
                            <span class="crm-inline-pill crm-inline-pill--${item.tone}">Контроль</span>
                            <strong>${documentPackageEscape(item.label)}</strong>
                            <small>${documentPackageEscape(item.statusLabel)}</small>
                            <em>${documentPackageEscape(item.document?.executor_name || item.document?.resolution_assignee || 'назначить ответственного')}</em>
                        </div>
                    `).join('') || '<div class="client360-empty">Сроки тендерных документов в норме.</div>')}
                </div>
            </div>
        </section>
    `;
}

function buildReceptionControl(rows = []) {
    const incoming = rows.filter(row => String(row.type || '').toLowerCase() === 'incoming');
    const outgoing = rows.filter(row => String(row.type || '').toLowerCase() === 'outgoing');
    const closed = rows.filter(row => isDocumentClosedState(row.status));
    const unassigned = rows.filter(row => !isDocumentClosedState(row.status) && !String(row.executor_name || row.resolution_assignee || '').trim());
    const overdue = rows.filter(isDocumentOverdue);
    const noReaction = incoming.filter(row => !isDocumentClosedState(row.status) && !row.resolution && !row.resolution_task_id && !row.resolution_assignee);
    const receptionRows = rows.filter(row => /ресепш|секрет|звон|обращ|приемн|входящ/i.test(documentText(row))).slice(0, 8);
    const routes = {
        director: rows.filter(row => /директор|руковод|соглас/i.test(documentText(row))).length,
        sales: rows.filter(row => /клиент|заказ|кп|сделк|менедж/i.test(documentText(row))).length,
        accounting: rows.filter(row => /счет|счёт|акт|оплат|бухгалтер|упд/i.test(documentText(row))).length,
        production: rows.filter(row => /производ|цех|срок|изготов|отк/i.test(documentText(row))).length,
        supply: rows.filter(row => /снабж|закуп|постав|склад|материал/i.test(documentText(row))).length,
    };
    return { incoming, outgoing, closed, unassigned, overdue, noReaction, receptionRows, routes };
}

function receptionRouteSuggestion(row) {
    const text = documentText(row);
    if (/директор|руковод|жалоб|претенз|эскалац/i.test(text)) return { label: 'Директору', assignee: 'Директор', priority: 'high' };
    if (/счет|счёт|акт|оплат|бухгалтер|упд/i.test(text)) return { label: 'Бухгалтерии', assignee: 'Бухгалтерия', priority: 'normal' };
    if (/производ|цех|срок|изготов|отк/i.test(text)) return { label: 'Производству', assignee: 'Производство и ОТК', priority: 'high' };
    if (/снабж|закуп|постав|склад|материал/i.test(text)) return { label: 'Снабжению', assignee: 'Склад и закупки', priority: 'normal' };
    return { label: 'Менеджеру', assignee: 'Менеджер', priority: 'normal' };
}

function renderReceptionDirectorMount(rows = []) {
    const mount = document.getElementById('receptionDirectorMount');
    if (!mount) return;
    const reception = buildReceptionControl(rows);
    mount.innerHTML = `
        <section class="documents-director-card">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Документооборот и ресепшен</h3>
                    <p class="section-subtitle">Входящие, исходящие, обращения, исполнители, сроки реакции и просрочки секретариата.</p>
                </div>
                <div class="view-actions">
                    <span class="crm-inline-pill crm-inline-pill--${reception.overdue.length ? 'critical' : 'positive'}">Просрочено: ${reception.overdue.length}</span>
                    <button class="btn-secondary" onclick="openReceptionIncomingPreset()">+ Обращение</button>
                    <button class="btn-secondary" onclick="routeReceptionQueue()">Маршрутизировать очередь</button>
                    <button class="btn-secondary" onclick="exportTenderReceptionDirectorReport('reception')">Отчёт</button>
                </div>
            </div>
            <div class="documents-director-grid">
                <div class="documents-director-metrics">
                    <div><span>Входящие</span><strong>${reception.incoming.length}</strong></div>
                    <div><span>Исходящие</span><strong>${reception.outgoing.length}</strong></div>
                    <div><span>Закрыто</span><strong>${reception.closed.length}</strong></div>
                    <div><span>Без реакции</span><strong>${reception.noReaction.length}</strong></div>
                    <div><span>Без исполнителя</span><strong>${reception.unassigned.length}</strong></div>
                    <div><span>Просрочено</span><strong>${reception.overdue.length}</strong></div>
                </div>
                <div class="documents-reception-list">
                    ${(reception.overdue.concat(reception.noReaction).concat(reception.receptionRows)).slice(0, 8).map(row => `
                        <button type="button" class="documents-reception-item" onclick="quickDocumentTask(${Number(row.id || 0)})">
                            <strong>${documentPackageEscape(row.number || row.subject || `Документ #${row.id}`)}</strong>
                            <span>${documentPackageEscape(row.correspondent || row.sender_name || 'без корреспондента')} · ${documentPackageEscape(row.resolution_deadline || 'без срока')} · ${documentPackageEscape(row.executor_name || row.resolution_assignee || 'без исполнителя')} · ${documentPackageEscape(receptionRouteSuggestion(row).label)}</span>
                        </button>
                    `).join('') || '<div class="client360-empty">Критичных обращений сейчас нет.</div>'}
                </div>
            </div>
            <div class="documents-checklist" style="margin-top:12px;">
                <div class="documents-checklist-item"><span class="crm-inline-pill crm-inline-pill--attention">Маршруты</span><strong>Директор / продажи / бухгалтерия</strong><small>${reception.routes.director} / ${reception.routes.sales} / ${reception.routes.accounting}</small><em>Автоподсказка по теме обращения</em></div>
                <div class="documents-checklist-item"><span class="crm-inline-pill crm-inline-pill--attention">Производство</span><strong>Производство / снабжение</strong><small>${reception.routes.production} / ${reception.routes.supply}</small><em>Отдельный поток для операционных вопросов</em></div>
            </div>
        </section>
    `;
}

async function persistDocumentQuickUpdate(id, overrides = {}, successMessage = 'Документ обновлён') {
    const row = findDocumentRow(id);
    if (!row) {
        await customAlert('Документ не найден.');
        return null;
    }
    const res = await apiCall(`/documents/${id}`, 'PUT', buildDocumentUpdatePayload(row, overrides));
    if (!res || res.error) {
        await customAlert('Не удалось выполнить быстрое обновление документа.');
        return null;
    }
    await loadDocuments();
    renderDocuments();
    showToast('Канцелярия', successMessage);
    return res;
}

window.quickAssignDocument = async function(id) {
    const row = findDocumentRow(id);
    if (!row) return;
    const assignee = await customPrompt('Исполнитель или адресат резолюции.', row.resolution_assignee || row.executor_name || '');
    if (assignee === null) return;
    await persistDocumentQuickUpdate(id, {
        executor_name: String(assignee || '').trim(),
        resolution_assignee: String(assignee || '').trim(),
        resolution_author: currentUser?.name || row.resolution_author || '',
    }, 'Исполнитель документа обновлён');
};

window.quickDocumentStatus = async function(id) {
    const row = findDocumentRow(id);
    if (!row) return;
    const statusOptions = [
        { value: 'draft', label: 'Черновик' },
        { value: 'registered', label: 'Зарегистрирован' },
        { value: 'signed', label: 'Подписан' },
        { value: 'archived', label: 'В архиве' },
    ];
    const currentStatus = statusOptions.some(item => item.value === row.status) ? row.status : 'registered';
    const nextStatus = await customSelectPrompt('Выберите новый статус документа', statusOptions, currentStatus);
    if (nextStatus === null) return;
    await persistDocumentQuickUpdate(id, {
        status: nextStatus,
    }, 'Статус документа обновлён');
};

window.quickDocumentComment = async function(id) {
    const row = findDocumentRow(id);
    if (!row) return;
    const comment = await customPrompt('Комментарий / резолюция по документу.', row.resolution || '');
    if (comment === null) return;
    await persistDocumentQuickUpdate(id, {
        resolution: comment,
        resolution_author: currentUser?.name || row.resolution_author || '',
    }, 'Комментарий к документу обновлён');
};

window.quickDocumentTask = async function(id) {
    const row = findDocumentRow(id);
    if (!row) return;
    const assignee = await customPrompt('Кому поставить задачу?', row.resolution_assignee || row.executor_name || currentUser?.name || '');
    if (assignee === null) return;
    const deadline = await customPrompt('Срок исполнения (дд.мм.гггг).', row.resolution_deadline || '');
    if (deadline === null) return;
    const resolution = await customPrompt('Короткая резолюция / поручение.', row.resolution || row.subject || '');
    if (resolution === null) return;
    await persistDocumentQuickUpdate(id, {
        executor_name: String(assignee || '').trim(),
        resolution_assignee: String(assignee || '').trim(),
        resolution_deadline: String(deadline || '').trim(),
        resolution: String(resolution || '').trim(),
        resolution_author: currentUser?.name || row.resolution_author || '',
    }, 'Поручение по документу создано или обновлено');
};

window.quickDocumentReminder = async function(id) {
    const row = findDocumentRow(id);
    if (!row) return;
    const deadline = await customPrompt('Новый срок контроля / напоминания (дд.мм.гггг).', row.resolution_deadline || '');
    if (deadline === null) return;
    await persistDocumentQuickUpdate(id, {
        resolution_deadline: String(deadline || '').trim(),
        resolution_author: currentUser?.name || row.resolution_author || '',
    }, 'Срок контроля по документу обновлён');
};

window.routeReceptionQueue = async function() {
    const reception = buildReceptionControl(allDocuments || []);
    const queue = reception.noReaction
        .concat(reception.unassigned)
        .filter((row, index, arr) => arr.findIndex(item => Number(item.id) === Number(row.id)) === index)
        .slice(0, 12);
    if (!queue.length) return customAlert('Очередь ресепшена сейчас пустая.');
    if (!(await customConfirm(`Маршрутизировать обращений: ${queue.length}?`))) return;
    let done = 0;
    for (const row of queue) {
        const route = receptionRouteSuggestion(row);
        await persistDocumentQuickUpdate(Number(row.id || 0), {
            executor_name: route.assignee,
            resolution_assignee: route.assignee,
            priority: route.priority,
            resolution_deadline: row.resolution_deadline || new Date().toLocaleDateString('ru-RU'),
            resolution: [row.resolution || '', `Ресепшен-маршрут: ${route.label}. Проверить обращение и дать реакцию.`].filter(Boolean).join('\n'),
            resolution_author: currentUser?.name || row.resolution_author || '',
            status: row.status || 'registered',
        }, 'Обращение маршрутизировано');
        done += 1;
    }
    showToast('Ресепшен', `Маршрутизировано обращений: ${done}`);
};

window.exportTenderReceptionDirectorReport = function(scope = 'tender') {
    let rows = [];
    if (scope === 'tender') {
        const tender = buildTenderControl(allDocuments || []);
        rows = tender.states.map(item => ({
            'Блок': 'Тендерные документы',
            'Документ': item.label,
            'Статус': item.statusLabel,
            'Номер/тема': item.document?.number || item.document?.subject || '',
            'Ответственный': item.document?.executor_name || item.document?.resolution_assignee || '',
            'Срок/действует до': item.document?.retention_until || item.document?.resolution_deadline || '',
            'Файл': item.document?.file_url ? 'есть' : 'нет',
            'Комментарий': item.document?.resolution || '',
        }));
        rows.push({
            'Блок': 'Архив пакетов',
            'Документ': 'Тендерные пакеты',
            'Статус': `${tender.tenderPackages.length} пакетов`,
            'Номер/тема': tender.tenderPackages.map(pkg => pkg.package_number || pkg.title || `#${pkg.id}`).join(', '),
            'Ответственный': '',
            'Срок/действует до': '',
            'Файл': '',
            'Комментарий': `${tender.readiness}% готовности`,
        });
    } else {
        const reception = buildReceptionControl(allDocuments || []);
        rows = reception.incoming.concat(reception.outgoing).slice(0, 200).map(row => {
            const route = receptionRouteSuggestion(row);
            return {
                'Блок': 'Ресепшен',
                'Документ': row.number || `#${row.id}`,
                'Статус': row.status || '',
                'Тема': row.subject || '',
                'Корреспондент': row.correspondent || row.sender_name || row.recipient_name || '',
                'Ответственный': row.executor_name || row.resolution_assignee || '',
                'Срок реакции': row.resolution_deadline || '',
                'Маршрут': route.label,
                'Просрочено': isDocumentOverdue(row) ? 'да' : 'нет',
            };
        });
    }
    if (!rows.length) return customAlert('Нет данных для отчёта.');
    const header = Object.keys(rows[0]);
    const csv = [header.join(';')]
        .concat(rows.map(row => header.map(key => `"${String(row[key] ?? '').replace(/"/g, '""')}"`).join(';')))
        .join('\n');
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `korda-${scope}-director-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    showToast('Документы', 'Директорский отчёт выгружен');
};

window.openDocumentLinkedContext = function(id) {
    const row = findDocumentRow(id);
    if (!row) return;
    if (Number(row.contract_id || 0) > 0 && typeof openContractCard === 'function') {
        openContractCard(Number(row.contract_id || 0));
        return;
    }
    if (Number(row.project_id || 0) > 0 && typeof openProject === 'function') {
        openProject(Number(row.project_id || 0));
        return;
    }
    customAlert('У документа пока нет привязки к проекту или договору.');
};

function documentPreviewLabel(value, fallback = 'Не указано') {
    const text = String(value ?? '').trim();
    return text || fallback;
}

function documentTypeTitle(value) {
    const map = {
        incoming: 'Входящий документ',
        outgoing: 'Исходящий документ',
        internal: 'Внутренний документ',
        contract: 'Договор',
        act: 'Акт',
        invoice: 'Счёт',
        internal_order: 'Приказ',
        internal_memo: 'Служебная записка',
        internal_reg: 'Регламент',
    };
    return map[String(value || '').trim()] || documentPreviewLabel(value, 'Документ');
}

function documentStatusTitle(value) {
    const map = {
        draft: 'Черновик',
        registered: 'Зарегистрирован',
        signed: 'Подписан',
        archived: 'В архиве',
        closed: 'Закрыт',
        done: 'Выполнен',
    };
    return map[String(value || '').trim()] || documentPreviewLabel(value, 'Статус не указан');
}

function documentPreviewRow(label, value) {
    return `
        <div class="document-preview__row">
            <span>${documentPackageEscape(label)}</span>
            <strong>${documentPackageEscape(documentPreviewLabel(value))}</strong>
        </div>
    `;
}

window.openDocumentPreview = function(id) {
    const row = findDocumentRow(id);
    if (!row) {
        return customAlert('Документ не найден.');
    }
    const assignedChoice = documentClientChoiceByReference(row.client_source, row.client_source_id, row.client_id, row.correspondent || row.sender_name || row.recipient_name || '');
    const assignedClient = assignedChoice || documentClientById(row.client_id);
    const assignedDeal = (typeof crmDealsDB !== 'undefined' && Array.isArray(crmDealsDB) ? crmDealsDB : []).find(deal => Number(deal.id || 0) === Number(row.deal_id || 0)) || null;
    const assignedContract = documentContractChoices().find(contract => Number(contract.id || 0) === Number(row.contract_id || 0)) || null;
    const assignedOrder = (typeof productionOrdersDB !== 'undefined' && Array.isArray(productionOrdersDB) ? productionOrdersDB : []).find(order => Number(order.id || 0) === Number(row.production_order_id || 0)) || null;
    const fileUrl = String(row.file_url || '').trim();
    const modal = document.getElementById('genericModal');
    if (!modal) {
        if (fileUrl) window.open(fileUrl, '_blank', 'noopener');
        else customAlert('Карточка документа есть, но файл ещё не загружен.');
        return;
    }
    const card = modal.querySelector('.modal-card');
    if (card) card.style.maxWidth = '820px';
    document.getElementById('genModalTitle').innerText = row.number || `Документ #${row.id}`;
    document.getElementById('genModalBody').innerHTML = `
        <div class="document-preview">
            <div class="document-preview__hero">
                <div>
                    <span>${documentPackageEscape(documentTypeTitle(row.type))}</span>
                    <h3>${documentPackageEscape(row.subject || row.correspondent || row.number || `Документ #${row.id}`)}</h3>
                    <p>${documentPackageEscape(row.correspondent || row.sender_name || row.recipient_name || 'Корреспондент не указан')}</p>
                </div>
                <em>${documentPackageEscape(documentStatusTitle(row.status))}</em>
            </div>
            <div class="document-preview__grid">
                ${documentPreviewRow('Номер', row.number || `#${row.id}`)}
                ${documentPreviewRow('Дата', row.d_date)}
                ${documentPreviewRow('От кого', row.sender_name || row.correspondent)}
                ${documentPreviewRow('Кому', row.recipient_name || row.correspondent)}
                ${documentPreviewRow('Ответственный', row.executor_name || row.resolution_assignee)}
                ${documentPreviewRow('Срок ответа', row.resolution_deadline)}
                ${documentPreviewRow('Клиент', assignedClient ? `${assignedClient.name || 'Без названия'}${assignedChoice?.source === 'bitrix24' ? ' · Bitrix24' : ' · CRM'}` : '')}
                ${documentPreviewRow('Договор', assignedContract ? documentContractLabel(assignedContract) : '')}
                ${documentPreviewRow('Сделка', assignedDeal ? (assignedDeal.title || assignedDeal.client_name || `#${assignedDeal.id}`) : '')}
                ${documentPreviewRow('Заказ КБ', assignedOrder ? (assignedOrder.order_name || assignedOrder.project_name || `Заказ #${assignedOrder.id}`) : '')}
                ${documentPreviewRow('Файл', fileUrl ? 'Файл прикреплён' : 'Файл ещё не загружен')}
            </div>
            <div class="document-preview__note">
                <span>Комментарий / резолюция</span>
                <p>${documentPackageEscape(documentPreviewLabel(row.resolution || row.comment, 'Пока нет комментария.'))}</p>
            </div>
        </div>
    `;
    document.getElementById('genModalFooter').innerHTML = `
        ${fileUrl ? '<button class="btn-primary" id="docPreviewOpenFile">Открыть файл</button>' : '<button class="btn-primary" id="docPreviewUploadFile">Загрузить файл</button>'}
        ${Number(row.contract_id || 0) > 0 ? '<button class="btn-secondary" id="docPreviewOpenContract">Открыть договор</button>' : ''}
        <button class="btn-secondary" id="docPreviewEdit">Редактировать</button>
        <button class="btn-secondary" id="docPreviewClose">Закрыть</button>
    `;
    modal.style.display = 'flex';
    const close = () => {
        modal.style.display = 'none';
        if (card) card.style.maxWidth = '';
    };
    const openFileBtn = document.getElementById('docPreviewOpenFile');
    if (openFileBtn) openFileBtn.onclick = () => window.open(fileUrl, '_blank', 'noopener');
    const uploadBtn = document.getElementById('docPreviewUploadFile');
    if (uploadBtn) uploadBtn.onclick = () => {
        close();
        uploadDocFile(Number(row.id || 0));
    };
    const openContractBtn = document.getElementById('docPreviewOpenContract');
    if (openContractBtn) openContractBtn.onclick = () => {
        close();
        openContractCard(Number(row.contract_id || 0));
    };
    document.getElementById('docPreviewEdit').onclick = () => {
        close();
        editDocument(Number(row.id || 0));
    };
    document.getElementById('docPreviewClose').onclick = close;
};

function exportDocumentsToExcel(rows, suffix = 'selection') {
    if (typeof XLSX === 'undefined') {
        return customAlert('Модуль экспорта пока не загрузился. Обновите страницу и попробуйте ещё раз.');
    }
    if (!rows.length) {
        return customAlert('Нет документов для выгрузки.');
    }
    const exportRows = rows.map(doc => ({
        '№': doc.number || '',
        'Дата': doc.d_date || '',
        'Тип': doc.type || '',
        'Отправитель': doc.sender_name || '',
        'Адресат': doc.recipient_name || '',
        'Корреспондент / Отдел': doc.correspondent || '',
        'Исходящий номер': doc.source_number || '',
        'Дата исходящего': doc.source_date || '',
        'Способ доставки': doc.delivery_method || '',
        'Подписант': doc.signer_name || '',
        'Исполнитель': doc.executor_name || '',
        'Тема': doc.subject || '',
        'Статус': doc.status || '',
        'Исполнитель резолюции': doc.resolution_assignee || '',
        'Срок резолюции': doc.resolution_deadline || '',
        'Идентификатор проекта': Number(doc.project_id || 0),
    }));
    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Документы');
    const now = new Date();
    const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    XLSX.writeFile(workbook, `korda-documents-${suffix}-${stamp}.xlsx`);
    showToast('Канцелярия', `Выгружено документов: ${rows.length}`);
}

window.exportSelectedDocuments = function() {
    exportDocumentsToExcel(getSelectedDocumentRows(), 'selected');
};

async function applyDocumentBulkAction(actionName, handler, successMessage) {
    const rows = getSelectedDocumentRows();
    if (!rows.length) {
        return customAlert('Сначала выделите документы.');
    }
    for (const row of rows) {
        const result = await handler(row);
        if (result && result.error) {
            return customAlert(`Не удалось выполнить действие "${actionName}" для документа №${row.number || row.id}.`);
        }
    }
    await loadDocuments();
    pruneSelectedDocuments();
    renderDocuments();
    showToast('Канцелярия', successMessage.replace('{count}', String(rows.length)));
}

window.bulkUpdateDocumentsStatus = async function(status) {
    const rows = getSelectedDocumentRows();
    if (!rows.length) {
        return customAlert('Сначала выделите документы.');
    }
    const statusLabel = status === 'registered' ? 'зарегистрировать' : 'отправить в архив';
    const confirmed = await customConfirm(`Применить действие "${statusLabel}" к ${rows.length} документам?`);
    if (!confirmed) return;
    await applyDocumentBulkAction(
        statusLabel,
        row => apiCall(`/documents/${row.id}`, 'PUT', buildDocumentUpdatePayload(row, { status })),
        `Массовое действие выполнено: {count}`,
    );
};

window.bulkDeleteDocuments = async function() {
    const rows = getSelectedDocumentRows();
    if (!rows.length) {
        return customAlert('Сначала выделите документы.');
    }
    const confirmed = await customConfirm(`Удалить выбранные документы (${rows.length}) безвозвратно?`);
    if (!confirmed) return;
    await applyDocumentBulkAction(
        'удаление',
        row => apiCall(`/documents/${row.id}`, 'DELETE'),
        'Удалено документов: {count}',
    );
    selectedDocuments.clear();
};

function renderDocuments() {
    pruneSelectedDocuments();
    const container = document.getElementById('documentsListTable');
    if (!container) return;
    registerDocumentsSavedFilters();
    updateDocumentsFilterButtons();

    const filtered = getFilteredDocuments();
    updateDocumentsBulkBar(filtered);
    renderDocumentPackagesMount();
    renderDocumentsOpsCounters(Array.isArray(documentsDB) ? documentsDB : []);
    renderTenderDirectorMount(filtered);
    renderReceptionDirectorMount(filtered);

    // --- Empty state ---
    if (filtered.length === 0) {
        const query = document.getElementById('documentRegistrySearch')?.value?.trim();
        const title = query ? 'Документы по запросу не найдены.' : 'Документы пока пусты.';
        const text = query
            ? 'Смени вкладку или очисти поиск, чтобы вернуться к полному реестру.'
            : 'Зарегистрируй первый документ, чтобы здесь появился рабочий реестр.';
        const actions = query
            ? `<button class="krd-btn krd-btn--outline krd-btn--sm" onclick="clearDocumentRegistrySearch()">Сбросить поиск</button>`
            : `<button class="krd-btn krd-btn--primary krd-btn--sm" onclick="openDocumentModalWithPreset({ type: currentDocTab === 'drafts' ? 'incoming' : currentDocTab })">Зарегистрировать документ</button>`;
        container.innerHTML = `
            <div class="krd-empty">
                <div class="krd-empty__title">${title}</div>
                <div class="krd-empty__hint">${text}</div>
                <div class="krd-hstack krd-hstack--sm" style="justify-content:center;">${actions}</div>
            </div>`;
        return;
    }

    // --- Status badge ---
    const statusMap = {
        registered: { cls: 'krd-badge--success', label: 'Зарегистрирован' },
        draft:      { cls: 'krd-badge',          label: 'Черновик' },
        archived:   { cls: 'krd-badge',          label: 'В архиве' },
    };

    // --- Type label (sub-type for internal documents) ---
    const typeLabels = {
        internal_order: { label: 'Приказ', cls: 'krd-badge--primary' },
        internal_memo:  { label: 'Служ. записка', cls: 'krd-badge' },
        internal_reg:   { label: 'Регламент', cls: 'krd-badge--primary' },
    };

    const esc = v => documentPackageEscape(v);

    const renderRows = () => filtered.map(doc => {
        const id = Number(doc.id || 0);
        const assignedChoice = documentClientChoiceByReference(doc.client_source, doc.client_source_id, doc.client_id, doc.correspondent || doc.sender_name || doc.recipient_name || '');
        const assignedClient = assignedChoice || documentClientById(doc.client_id);
        const assignedDeal = (typeof crmDealsDB !== 'undefined' && Array.isArray(crmDealsDB) ? crmDealsDB : []).find(deal => Number(deal.id || 0) === Number(doc.deal_id || 0)) || null;
        const hasFile = !!doc.file_url;
        const status = statusMap[doc.status] || statusMap.archived;
        const subtype = typeLabels[doc.type];
        const kindLabel = documentKindLabel(inferredDocumentKindCode(doc));
        const isHighPriority = doc.priority === 'high';
        const favBtn = typeof renderEntityFavoriteButton === 'function'
            ? renderEntityFavoriteButton('document', doc.id, doc.number || doc.subject || `Документ #${doc.id}`, `${doc.type || ''} · ${doc.status || ''} · ${doc.correspondent || ''}`, 'documents', 'renderDocuments') : '';
        const watchBtn = typeof renderEntityWatchButton === 'function'
            ? renderEntityWatchButton('document', doc.id, doc.number || doc.subject || `Документ #${doc.id}`, `${doc.type || ''} · ${doc.status || ''} · ${doc.correspondent || ''}`, 'documents', 'renderDocuments', 'signed') : '';
        const rowHighlight = typeof isWorkflowFocused === 'function' && isWorkflowFocused('document', doc.id) ? ' krd-file-row--focused' : '';
        const resolution = doc.resolution_task_id
            ? `<span class="krd-badge krd-badge--info krd-badge--sm">Поручение #${esc(doc.resolution_task_id)}</span>`
            : '';
        const routeMeta = [doc.sender_name, doc.recipient_name].filter(Boolean).join(' -> ');
        const linkMeta = [
            assignedClient ? `Клиент: ${esc(assignedClient.name || 'Без названия')}` : '',
            assignedDeal ? `Сделка: ${esc(assignedDeal.title || assignedDeal.client_name || `№${assignedDeal.id}`)}` : '',
            Number(doc.contract_id || 0) > 0 ? `Договор #${esc(doc.contract_id)}` : '',
            Number(doc.project_id || 0) > 0 ? `Проект #${esc(doc.project_id)}` : '',
            Number(doc.object_id || 0) > 0 ? `Объект #${esc(doc.object_id)}` : '',
        ].filter(Boolean).join(' · ');
        const controlMeta = [
            doc.delivery_method || '',
            doc.source_number ? `Исх. №${esc(doc.source_number)}` : '',
            doc.resolution_deadline ? `Ответ до ${esc(doc.resolution_deadline)}` : '',
        ].filter(Boolean).join(' · ');
        const executorMeta = [
            doc.executor_name || doc.resolution_assignee || doc.signer_name || 'Не назначен',
            doc.resolution_author ? `Поставил: ${esc(doc.resolution_author)}` : '',
        ].filter(Boolean).join(' · ');

        // version badge on row — shows current known state; actual count loaded on expand
        const versionBadge = hasFile
            ? `<span class="krd-version-badge krd-version-badge--active">v${Number(doc.file_revision_no || 1)}</span>`
            : '';

        // right-side actions
        const previewAction = `<button class="krd-btn krd-btn--primary krd-btn--xs" onclick="openDocumentPreview(${id})">Просмотр</button>`;
        const fileAction = hasFile
            ? `<a class="krd-btn krd-btn--outline krd-btn--xs" href="${esc(doc.file_url)}" target="_blank" rel="noopener">
                <svg class="krd-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                Открыть файл
              </a>`
            : `<button class="krd-btn krd-btn--outline krd-btn--xs" onclick="uploadDocFile(${id})">
                <svg class="krd-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                Добавить файл
              </button>`;

        const newVersionBtn = hasFile
            ? `<button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="uploadDocFile(${id})" title="Загрузить новую версию">+ версия</button>`
            : '';

        const expandBtn = `<button class="krd-file-row__expand" onclick="toggleDocumentVersions(${id}, this)" aria-label="Показать версии файла" aria-controls="docVersions-${id}" ${hasFile ? '' : 'disabled'}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"></polyline></svg>
        </button>`;

        // main row
        const mainRow = `
        <div class="krd-file-row${rowHighlight}" data-document-id="${id}" id="docRow-${id}">
            ${expandBtn}
            <div class="krd-file-row__name">
                <div class="krd-file-row__name-main">
                    ${favBtn}${watchBtn}
                    <span>${esc(doc.number || `#${id}`)}</span>
                    ${versionBadge}
                    <span class="krd-badge krd-badge--primary krd-badge--sm">${esc(kindLabel)}</span>
                    ${subtype ? `<span class="krd-badge ${subtype.cls} krd-badge--sm">${esc(subtype.label)}</span>` : ''}
                    ${isHighPriority ? `<span class="krd-badge krd-badge--danger krd-badge--sm">Приоритет</span>` : ''}
                    ${assignedClient ? `<span class="krd-badge krd-badge--success krd-badge--sm">Для клиента: ${esc(assignedClient.name || 'Без названия')} · ${assignedChoice?.source === 'bitrix24' ? 'Bitrix24' : 'CRM'}</span>` : ''}
                    ${assignedDeal ? `<span class="krd-badge krd-badge--primary krd-badge--sm">В сделке</span>` : ''}
                </div>
                <div class="krd-file-row__name-meta">
                    <span>${esc(doc.subject || 'Без темы')}</span>
                    ${routeMeta ? `<span> · ${esc(routeMeta)}</span>` : ''}
                    ${resolution}
                </div>
            </div>
            <div class="krd-file-row__route">
                <div class="krd-file-row__cell-main">${esc(routeMeta || doc.correspondent || 'Маршрут не задан')}</div>
                <div class="krd-file-row__cell-meta">${esc(linkMeta || 'Без привязки к сущностям')}</div>
            </div>
            <div class="krd-file-row__control">
                <div class="krd-file-row__cell-main">${esc(doc.d_date || 'Без даты')}</div>
                <div class="krd-file-row__cell-meta">${esc(controlMeta || 'Без срока ответа и способа доставки')}</div>
            </div>
            <div class="krd-file-row__executor">
                <div class="krd-file-row__cell-main">${esc(doc.executor_name || doc.resolution_assignee || 'Не назначен')}</div>
                <div class="krd-file-row__cell-meta">${esc(executorMeta || 'Исполнитель не определён')}</div>
            </div>
            <div class="krd-file-row__status"><span class="krd-badge ${status.cls}">${esc(status.label)}</span></div>
            <div class="krd-file-row__actions krd-file-row__actions--wrap">
                <input type="checkbox" ${selectedDocuments.has(id) ? 'checked' : ''} onchange="toggleDocumentSelection(${id}, this.checked)" aria-label="Выделить документ">
                ${previewAction}
                ${fileAction}
                ${Number(doc.contract_id || 0) > 0 ? `<button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="openContractCard(${Number(doc.contract_id || 0)})">Открыть договор</button>` : ''}
                <button class="krd-btn krd-btn--outline krd-btn--xs" onclick="quickAssignDocument(${id})">Назначить ответственного</button>
                <details class="document-row-menu">
                    <summary class="krd-btn krd-btn--ghost krd-btn--xs">Ещё</summary>
                    <div class="document-row-menu__items">
                        ${newVersionBtn}
                        <button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="quickDocumentStatus(${id})">Изменить статус</button>
                        <button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="quickDocumentComment(${id})">Добавить комментарий</button>
                        <button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="quickDocumentTask(${id})">Создать задачу</button>
                        <button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="quickDocumentReminder(${id})">Установить срок</button>
                        ${Number(doc.contract_id || 0) > 0 ? '' : `<button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="openDocumentLinkedContext(${id})">Открыть проект</button>`}
                        <button class="krd-btn krd-btn--ghost krd-btn--xs" onclick="editDocument(${id})">Изменить данные</button>
                        <button class="krd-btn krd-btn--danger-ghost krd-btn--xs" onclick="deleteDocument(${id})">Удалить документ</button>
                    </div>
                </details>
            </div>
        </div>
        <div class="krd-file-history" id="docVersions-${id}" data-document-id="${id}" hidden></div>`;
        return mainRow;
    }).join('');

    if (typeof renderDeferredHtml === 'function') {
        renderDeferredHtml(container, renderRows, { size: filtered.length, threshold: 80, loadingMessage: 'Загружаю реестр документов...' });
    } else {
        container.innerHTML = renderRows();
    }
}

async function submitDocument(status = 'registered') {
    if (typeof bindFormFieldErrorCleanup === 'function') bindFormFieldErrorCleanup('documentForm');
    if (typeof clearFormErrors === 'function') clearFormErrors('createDocModal');
    const type = document.getElementById('docType').value;
    const documentKindCode = document.getElementById('docKind')?.value || '';
    const number = document.getElementById('docNumber').value.trim();
    const dDate = document.getElementById('docDate').value.trim();
    const senderName = document.getElementById('docSenderName')?.value.trim() || '';
    const recipientName = document.getElementById('docRecipientName')?.value.trim() || '';
    const sourceNumber = document.getElementById('docSourceNumber')?.value.trim() || '';
    const sourceDate = document.getElementById('docSourceDate')?.value.trim() || '';
    const deliveryMethod = document.getElementById('docDeliveryMethod')?.value || '';
    const signerName = document.getElementById('docSignerName')?.value.trim() || '';
    const executorName = document.getElementById('docExecutorName')?.value.trim() || '';
    const corr = document.getElementById('docCorrespondent').value.trim();
    const subj = document.getElementById('docSubject').value.trim();
    const clientId = parseInt(document.getElementById('docClientId')?.value || '0', 10) || 0;
    const clientSource = document.getElementById('docClientSource')?.value || '';
    const clientSourceId = parseInt(document.getElementById('docClientSourceId')?.value || '0', 10) || 0;
    const dealId = parseInt(document.getElementById('docDealId')?.value || '0', 10) || 0;
    const contractId = parseInt(document.getElementById('docContractId')?.value || '0', 10) || 0;
    const productionOrderId = parseInt(document.getElementById('docProductionOrderId')?.value || '0', 10) || 0;
    const parentId = parseInt(document.getElementById('docParentId')?.value || '0', 10) || 0;
    const priority = document.getElementById('docPriority')?.checked ? 'high' : 'normal';
    const file = document.getElementById('docFile')?.files?.[0] || null;

    const errors = [];
    if (!documentKindCode) errors.push({ field: 'docKind', message: 'Выберите вид документа.' });
    if (!number) errors.push({ field: 'docNumber', message: 'Укажите номер документа.' });
    if (!subj) errors.push({ field: 'docSubject', message: 'Укажите тему документа.' });
    if (!file) errors.push({ field: 'docFile', message: 'Прикрепите файл документа.' });
    if (errors.length) {
        if (typeof showFormErrors === 'function') showFormErrors(errors, 'createDocModal');
        return;
    }

    const res = await apiCall('/documents', 'POST', {
        type,
        document_kind_code: documentKindCode,
        number,
        d_date: dDate,
        correspondent: corr,
        sender_name: senderName,
        recipient_name: recipientName,
        source_number: sourceNumber,
        source_date: sourceDate,
        delivery_method: deliveryMethod,
        signer_name: signerName,
        executor_name: executorName,
        subject: subj,
        status,
        client_id: clientId,
        client_source: clientSource,
        client_source_id: clientSourceId,
        deal_id: dealId,
        contract_id: contractId,
        production_order_id: productionOrderId,
        parent_id: parentId,
        priority,
    });
    if (!res || res.error) {
        return customAlert(res?.message || "Не удалось сохранить документ. Проверьте заполнение полей и попробуйте ещё раз.");
    }
    const formData = new FormData();
    formData.append('file', file);
    const uploadRes = await apiCall(`/documents/${Number(res.id || 0)}/upload`, 'POST', formData);
    if (!uploadRes || uploadRes.error) {
        await apiCall(`/documents/${Number(res.id || 0)}`, 'DELETE');
        return customAlert(uploadRes?.message || 'Файл не загрузился. Карточка не создана — выберите файл и попробуйте ещё раз.');
    }
    if (typeof markWorkflowFocus === 'function') markWorkflowFocus('document', Number(res.id || 0));
    if (typeof clearFormDraft === 'function') clearFormDraft('document');

    closeDocumentCreateModal();
    document.getElementById('docNumber').value = '';
    document.getElementById('docDate').value = '';
    if (document.getElementById('docSenderName')) document.getElementById('docSenderName').value = '';
    if (document.getElementById('docRecipientName')) document.getElementById('docRecipientName').value = '';
    if (document.getElementById('docSourceNumber')) document.getElementById('docSourceNumber').value = '';
    if (document.getElementById('docSourceDate')) document.getElementById('docSourceDate').value = '';
    if (document.getElementById('docDeliveryMethod')) document.getElementById('docDeliveryMethod').value = '';
    if (document.getElementById('docSignerName')) document.getElementById('docSignerName').value = '';
    if (document.getElementById('docExecutorName')) document.getElementById('docExecutorName').value = '';
    document.getElementById('docCorrespondent').value = '';
    document.getElementById('docSubject').value = '';
    if (document.getElementById('docClientSearch')) document.getElementById('docClientSearch').value = '';
    if (document.getElementById('docClientId')) document.getElementById('docClientId').value = '0';
    if (document.getElementById('docClientSource')) document.getElementById('docClientSource').value = '';
    if (document.getElementById('docClientSourceId')) document.getElementById('docClientSourceId').value = '0';
    if (document.getElementById('docContractSearch')) document.getElementById('docContractSearch').value = '';
    if (document.getElementById('docContractId')) document.getElementById('docContractId').value = '0';
    if (document.getElementById('docProductionOrderSearch')) document.getElementById('docProductionOrderSearch').value = '';
    if (document.getElementById('docProductionOrderId')) document.getElementById('docProductionOrderId').value = '0';
    if (document.getElementById('docPriority')) document.getElementById('docPriority').checked = false;
    if (document.getElementById('docFile')) document.getElementById('docFile').value = '';
    updateDocumentFileName();
    if (document.getElementById('docDealId')) document.getElementById('docDealId').innerHTML = '<option value="0">Сначала выберите клиента</option>';
    if (document.getElementById('docParentId')) document.getElementById('docParentId').value = '0';

    await Promise.all([
        loadDocuments(),
        dealId > 0 && typeof loadCrmDeals === 'function' ? loadCrmDeals() : Promise.resolve(),
    ]);
    if (dealId > 0 && typeof openDealEditor === 'function' && Number(editingDealId || 0) === dealId) {
        openDealEditor(dealId);
        if (typeof switchDealEditorStep === 'function') switchDealEditorStep(5, false);
    }
    showToast('Канцелярия', status === 'draft' ? 'Документ сохранён в черновики' : 'Документ зарегистрирован');
    switchDocTab(status === 'draft' ? 'drafts' : (type.startsWith('internal_') ? 'internal' : type));
    if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget('[data-document-id].workflow-row-highlight, [data-document-id]');
}

async function uploadDocFile(id) {
    const input = document.createElement('input');
    input.type = 'file';
    input.onchange = async event => {
        const file = event.target.files[0];
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        await apiCall(`/documents/${id}/upload`, 'POST', formData);
        await loadDocuments();
        renderDocuments();
    };
    input.click();
}

async function editDocument(id) {
    const doc = documentsDB.find(item => item.id === id);
    if (!doc) return;

    const newSubject = await customPrompt("Изменить тему документа:", doc.subject);
    if (newSubject === null) return;
    const newCorrespondent = await customPrompt("Изменить корреспондента:", doc.correspondent || '');
    if (newCorrespondent === null) return;
    const isRegistered = await customConfirm("Этот документ активен? (Да - Зарегистрирован, Отмена - В архиве)");
    const newStatus = isRegistered ? 'registered' : 'archived';

    await apiCall(`/documents/${id}`, 'PUT', buildDocumentUpdatePayload(doc, {
        correspondent: newCorrespondent,
        subject: newSubject,
        status: newStatus,
    }));

    await loadDocuments();
    renderDocuments();
}

async function deleteDocument(id) {
    if (!(await customConfirm("Вы уверены, что хотите БЕЗВОЗВРАТНО удалить этот документ?"))) return;
    await apiCall(`/documents/${id}`, 'DELETE');
    selectedDocuments.delete(Number(id));
    await loadDocuments();
    renderDocuments();
}

window.generateDocNumber = function() {
    const type = document.getElementById('docType')?.value || 'incoming';
    const kind = document.getElementById('docKind')?.value || '';
    const dateValue = document.getElementById('docDate')?.value.trim() || '';
    const parts = dateValue ? dateValue.split('.') : [];
    const now = new Date();
    const day = parts[0] || String(now.getDate()).padStart(2, '0');
    const month = parts[1] || String(now.getMonth() + 1).padStart(2, '0');
    const year = (parts[2] || String(now.getFullYear())).slice(-2);
    const typePrefix = {
        commercial_proposal: 'КП',
        technical_proposal: 'ТП',
        contract: 'ДОГ',
        contract_specification: 'СПЕЦ',
        invoice: 'СЧ',
        act_upd: 'АКТ',
        technical_task: 'ТЗ',
        drawing: 'ЧЕРТ',
        product_specification: 'СИ',
        technology_card: 'ТК',
        production_order: 'ПЗ',
        purchase_request: 'ЗЗ',
        supplier_order: 'ЗП',
        waybill: 'НАКЛ',
        quality_act: 'ОТК',
        service_act: 'СЕРВ',
        internal_memo: 'СЗ',
        other: 'ДОК',
    }[kind] || ({
        incoming: 'ВХ',
        outgoing: 'ИСХ',
        internal_order: 'ПР',
        internal_memo: 'СЗ',
        internal_reg: 'РЕГ',
    }[type] || 'ДОК');
    const docPrefix = `${typePrefix}-${year}${month}${day}`;
    const siblings = documentsDB.filter(doc => String(doc.number || '').startsWith(docPrefix)).length + 1;
    const docNumberInput = document.getElementById('docNumber');
    if (docNumberInput) docNumberInput.value = `${docPrefix}-${String(siblings).padStart(3, '0')}`;
};

window.startBatchScan = async function() {
    const confirmed = await customConfirm('Запустить потоковое сканирование и автопривязку документов?');
    if (!confirmed) return;
    showToast('Сканирование', 'Обработка пачки документов запущена');
    const result = await apiCall('/documents/batch_scan', 'POST');
    if (!result || result.error) {
        return customAlert('Не удалось запустить потоковое сканирование.');
    }
    await loadDocuments();
    renderDocuments();
    const processed = result.processed || 0;
    showToast('Сканирование', processed ? `Обработано документов: ${processed}` : 'Пакет документов обработан');
};
