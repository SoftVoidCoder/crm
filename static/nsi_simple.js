(function () {
    let nomSearch = '';
    let nomGroup = '';
    let selectedNomId = 0;
    let editingNomId = 0;
    let contactSearch = '';
    let selectedContactId = 0;
    let editingContactId = 0;

    const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
    const num = value => Number(value || 0) || 0;
    const can = (section, action) => typeof hasCurrentPermission !== 'function' || hasCurrentPermission(section, action);
    const currencySymbol = value => ({ RUB: '₽', USD: '$', EUR: '€', CNY: '¥' }[value] || value || '₽');
    const money = (value, currency) => `${num(value).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ${currencySymbol(currency)}`;

    async function loadSimpleNomenclature() {
        const rows = await apiCall('/nomenclature');
        nomenclatureDB = Array.isArray(rows) ? rows : [];
    }
    async function loadSimpleContacts() {
        const rows = await apiCall('/contacts');
        contactsDB = Array.isArray(rows) ? rows : [];
    }
    async function loadSimpleClients() {
        const rows = await apiCall('/clients');
        if (Array.isArray(rows)) clientsDB = rows;
    }
    function clientName(clientId) {
        const client = (typeof clientsDB !== 'undefined' ? clientsDB : []).find(item => Number(item.id) === Number(clientId));
        return client?.name || 'Компания не найдена';
    }

    function filteredNomRows() {
        const query = nomSearch.toLowerCase();
        return nomenclatureDB.filter(item => {
            const haystack = [item.name, item.article, item.group_name, item.default_warehouse].join(' ').toLowerCase();
            return (!query || haystack.includes(query)) && (!nomGroup || (item.group_name || '') === nomGroup);
        });
    }
    function renderNomFilters() {
        const select = document.getElementById('nomenclatureSimpleGroup');
        if (!select) return;
        const groups = [...new Set(nomenclatureDB.map(item => String(item.group_name || '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru'));
        select.innerHTML = `<option value="">Все группы</option>${groups.map(group => `<option value="${esc(group)}">${esc(group)}</option>`).join('')}`;
        select.value = nomGroup;
    }
    function renderNomMetrics() {
        const target = document.getElementById('nomenclatureSimpleMetrics');
        if (!target) return;
        const inStock = nomenclatureDB.filter(item => num(item.stock) > 0).length;
        const groups = new Set(nomenclatureDB.map(item => item.group_name).filter(Boolean)).size;
        target.innerHTML = `<div><span>Всего позиций</span><strong>${nomenclatureDB.length}</strong></div><div><span>Есть на складе</span><strong>${inStock}</strong></div><div><span>Нет остатка</span><strong>${nomenclatureDB.length - inStock}</strong></div><div><span>Групп</span><strong>${groups}</strong></div>`;
    }
    function renderNomList() {
        const target = document.getElementById('nomenclatureSimpleList');
        if (!target) return;
        const rows = filteredNomRows();
        target.innerHTML = rows.length ? rows.map(item => `<article class="nsi-simple-record ${Number(selectedNomId) === Number(item.id) ? 'is-selected' : ''}">
            <div class="nsi-simple-record__identity"><span class="nsi-simple-record__icon">${esc(String(item.name || '?').slice(0, 1).toUpperCase())}</span><div><h3>${esc(item.name || 'Без названия')}</h3><p>${item.article ? `Артикул ${esc(item.article)}` : 'Без артикула'} · ${esc(item.group_name || 'Без группы')}</p></div></div>
            <div class="nsi-simple-record__fact"><span>Остаток</span><strong class="${num(item.stock) > 0 ? 'is-positive' : 'is-empty'}">${num(item.stock).toLocaleString('ru-RU')} ${esc(item.unit || 'шт')}</strong></div>
            <div class="nsi-simple-record__fact"><span>Цена</span><strong>${money(item.price, item.currency)}</strong></div>
            <button class="btn-secondary" type="button" onclick="selectSimpleNomenclature(${num(item.id)})">Открыть карточку</button>
        </article>`).join('') : '<div class="nsi-simple-empty">Позиции по этому фильтру не найдены.</div>';
    }
    function renderNomDetail() {
        const target = document.getElementById('nomenclatureSimpleDetail');
        if (!target) return;
        const item = nomenclatureDB.find(row => Number(row.id) === Number(selectedNomId));
        if (!item) {
            target.innerHTML = '<div class="nsi-simple-empty">Откройте позицию из списка — здесь появится полная карточка.</div>';
            return;
        }
        target.innerHTML = `<article class="nsi-simple-card">
            <header class="nsi-simple-card__head"><div><span class="nsi-simple-badge">${esc(item.group_name || 'Без группы')}</span><h2>${esc(item.name)}</h2><p>${item.article ? `Артикул ${esc(item.article)}` : 'Артикул не указан'}</p></div><div class="view-actions">${can('nsi','update') ? `<button class="btn-primary" onclick="openSimpleNomenclatureEditor(${item.id})">Редактировать</button>` : ''}${can('nsi','delete') ? `<button class="btn-danger" onclick="deleteSimpleNomenclature(${item.id})">Удалить</button>` : ''}</div></header>
            <div class="nsi-simple-card__facts"><div><span>Единица</span><strong>${esc(item.unit || 'шт')}</strong></div><div><span>Остаток</span><strong>${num(item.stock).toLocaleString('ru-RU')} ${esc(item.unit || 'шт')}</strong></div><div><span>Базовая цена</span><strong>${money(item.price, item.currency)}</strong></div><div><span>Основной склад</span><strong>${esc(item.default_warehouse || 'Не указан')}</strong></div></div>
            <section class="nsi-simple-card__work"><div><h3>Движение остатка</h3><p>Фиксируйте только фактический приход, расход или перемещение.</p></div><div class="view-actions">${can('nsi','update') && item.article ? `<button class="btn-secondary" onclick="moveSimpleNomenclatureStock(${item.id},'add')">Приход</button><button class="btn-secondary" onclick="moveSimpleNomenclatureStock(${item.id},'remove')">Расход</button><button class="btn-secondary" onclick="moveSimpleNomenclatureStock(${item.id},'transfer')">Переместить</button>` : '<span class="nsi-simple-help">Для движения нужен артикул и право редактирования.</span>'}</div></section>
        </article>`;
    }

    window.renderNomenclature = async function () {
        await loadSimpleNomenclature();
        if (selectedNomId && !nomenclatureDB.some(item => Number(item.id) === Number(selectedNomId))) selectedNomId = 0;
        renderNomMetrics(); renderNomFilters(); renderNomList(); renderNomDetail();
    };
    window.setSimpleNomenclatureSearch = value => { nomSearch = String(value || '').trim(); renderNomList(); };
    window.setSimpleNomenclatureGroup = value => { nomGroup = value || ''; renderNomList(); };
    window.resetSimpleNomenclatureFilters = () => { nomSearch = ''; nomGroup = ''; document.getElementById('nomenclatureSimpleSearch').value = ''; document.getElementById('nomenclatureSimpleGroup').value = ''; renderNomList(); };
    window.selectSimpleNomenclature = id => { selectedNomId = Number(id); renderNomList(); renderNomDetail(); document.getElementById('nomenclatureSimpleDetail')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    window.openSimpleNomenclatureEditor = function (id = 0) {
        if (!can('nsi', id ? 'update' : 'create')) return customAlert('У вашей роли нет права изменять номенклатуру.');
        editingNomId = Number(id || 0);
        const item = nomenclatureDB.find(row => Number(row.id) === editingNomId) || {};
        const values = { simpleNomName: item.name || '', simpleNomArticle: item.article || '', simpleNomUnit: item.unit || 'шт', simpleNomGroupName: item.group_name || '', simpleNomWarehouse: item.default_warehouse || '', simpleNomPrice: num(item.price), simpleNomCurrency: item.currency || 'RUB' };
        Object.entries(values).forEach(([idKey, value]) => { const el = document.getElementById(idKey); if (el) el.value = value; });
        document.getElementById('nomenclatureSimpleEditorTitle').textContent = editingNomId ? 'Редактирование позиции' : 'Новая позиция';
        document.getElementById('nomenclatureSimpleList').hidden = true; document.getElementById('nomenclatureSimpleDetail').hidden = true;
        const editor = document.getElementById('nomenclatureSimpleEditor'); editor.hidden = false; editor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    window.closeSimpleNomenclatureEditor = () => { editingNomId = 0; document.getElementById('nomenclatureSimpleEditor').hidden = true; document.getElementById('nomenclatureSimpleList').hidden = false; document.getElementById('nomenclatureSimpleDetail').hidden = false; };
    window.saveSimpleNomenclature = async function () {
        const payload = { name: document.getElementById('simpleNomName').value.trim(), article: document.getElementById('simpleNomArticle').value.trim(), unit: document.getElementById('simpleNomUnit').value.trim(), group_name: document.getElementById('simpleNomGroupName').value.trim(), default_warehouse: document.getElementById('simpleNomWarehouse').value.trim(), price: num(document.getElementById('simpleNomPrice').value), stock: 0, currency: document.getElementById('simpleNomCurrency').value };
        if (!payload.name) return customAlert('Укажите название позиции.');
        if (!payload.unit) return customAlert('Укажите единицу измерения.');
        const endpoint = editingNomId ? `/nomenclature/by_id/${editingNomId}` : '/nomenclature';
        const res = await apiCall(endpoint, editingNomId ? 'PUT' : 'POST', payload);
        if (!res || res.error) return customAlert(res?.error === 'duplicate_candidate' ? 'Позиция с таким названием или артикулом уже существует.' : (res?.error || 'Не удалось сохранить позицию.'));
        selectedNomId = num(res.id || editingNomId); editingNomId = 0; closeSimpleNomenclatureEditor(); await renderNomenclature(); showToast('Номенклатура', 'Позиция сохранена');
    };
    window.deleteSimpleNomenclature = async function (id) {
        if (!(await customConfirm('Удалить позицию из справочника?'))) return;
        const res = await apiCall(`/nomenclature/by_id/${id}`, 'DELETE');
        if (!res || res.error) return customAlert(res?.error || 'Не удалось удалить позицию.');
        selectedNomId = 0; await renderNomenclature(); showToast('Номенклатура', 'Позиция удалена');
    };
    window.moveSimpleNomenclatureStock = function (id, type) {
        const item = nomenclatureDB.find(row => Number(row.id) === Number(id));
        if (!item?.article) return customAlert('Сначала укажите артикул позиции.');
        return moveStock(item.article, type);
    };

    function filteredContactRows() {
        const query = contactSearch.toLowerCase();
        return contactsDB.filter(item => !query || [item.name, item.position, item.phone, item.email, clientName(item.client_id)].join(' ').toLowerCase().includes(query));
    }
    function renderContactMetrics() {
        const target = document.getElementById('contactsSimpleMetrics'); if (!target) return;
        target.innerHTML = `<div><span>Всего контактов</span><strong>${contactsDB.length}</strong></div><div><span>С телефоном</span><strong>${contactsDB.filter(item => item.phone).length}</strong></div><div><span>С почтой</span><strong>${contactsDB.filter(item => item.email).length}</strong></div><div><span>Компаний</span><strong>${new Set(contactsDB.map(item => item.client_id).filter(Boolean)).size}</strong></div>`;
    }
    function renderContactList() {
        const target = document.getElementById('contactsSimpleList'); if (!target) return;
        const rows = filteredContactRows();
        target.innerHTML = rows.length ? rows.map(item => `<article class="nsi-simple-record nsi-simple-record--contact ${Number(selectedContactId) === Number(item.id) ? 'is-selected' : ''}"><div class="nsi-simple-record__identity"><span class="nsi-simple-record__icon">${esc(String(item.name || '?').slice(0,1).toUpperCase())}</span><div><h3>${esc(item.name || 'Без имени')}</h3><p>${esc(item.position || 'Должность не указана')} · ${esc(clientName(item.client_id))}</p></div></div><div class="nsi-simple-record__contact"><span>${esc(item.phone || 'Телефон не указан')}</span><small>${esc(item.email || 'Почта не указана')}</small></div><button class="btn-secondary" onclick="selectSimpleContact(${num(item.id)})">Открыть карточку</button></article>`).join('') : '<div class="nsi-simple-empty">Контакты по этому запросу не найдены.</div>';
    }
    function renderContactDetail() {
        const target = document.getElementById('contactsSimpleDetail'); if (!target) return;
        const item = contactsDB.find(row => Number(row.id) === Number(selectedContactId));
        if (!item) { target.innerHTML = '<div class="nsi-simple-empty">Откройте контакт из списка — здесь появится полная карточка.</div>'; return; }
        target.innerHTML = `<article class="nsi-simple-card"><header class="nsi-simple-card__head"><div><span class="nsi-simple-badge">${esc(item.position || 'Должность не указана')}</span><h2>${esc(item.name)}</h2><p>${esc(clientName(item.client_id))}</p></div><div class="view-actions">${can('clients','update') ? `<button class="btn-primary" onclick="openSimpleContactEditor(${item.id})">Редактировать</button>` : ''}${can('clients','delete') ? `<button class="btn-danger" onclick="deleteSimpleContact(${item.id})">Удалить</button>` : ''}</div></header><div class="nsi-simple-card__facts nsi-simple-card__facts--contact"><div><span>Компания</span><strong>${esc(clientName(item.client_id))}</strong></div><div><span>Должность</span><strong>${esc(item.position || 'Не указана')}</strong></div><div><span>Телефон</span><strong>${item.phone ? `<a href="tel:${esc(item.phone)}">${esc(item.phone)}</a>` : 'Не указан'}</strong></div><div><span>Почта</span><strong>${item.email ? `<a href="mailto:${esc(item.email)}">${esc(item.email)}</a>` : 'Не указана'}</strong></div></div></article>`;
    }
    window.renderContacts = async function () {
        await Promise.all([loadSimpleContacts(), loadSimpleClients()]);
        if (selectedContactId && !contactsDB.some(item => Number(item.id) === Number(selectedContactId))) selectedContactId = 0;
        renderContactMetrics(); renderContactList(); renderContactDetail();
        updateSimpleContactBitrixState();
    };
    window.setSimpleContactSearch = value => { contactSearch = String(value || '').trim(); renderContactList(); };
    window.resetSimpleContactSearch = () => { contactSearch = ''; document.getElementById('contactsSimpleSearch').value = ''; renderContactList(); };
    window.selectSimpleContact = id => { selectedContactId = Number(id); renderContactList(); renderContactDetail(); document.getElementById('contactsSimpleDetail')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    function fillContactClients(selectedId = 0) {
        const select = document.getElementById('simpleContactClientId'); if (!select) return;
        select.innerHTML = `<option value="">Выберите компанию</option>${(typeof clientsDB !== 'undefined' ? clientsDB : []).map(client => `<option value="${num(client.id)}">${esc(client.name)}</option>`).join('')}`;
        select.value = selectedId ? String(Number(selectedId)) : '';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        if (typeof window.refreshUniversalUiEnhancements === 'function') window.refreshUniversalUiEnhancements();
    }
    window.openSimpleContactEditor = function (id = 0) {
        if (!can('clients', id ? 'update' : 'create')) return customAlert('У вашей роли нет права изменять контакты.');
        editingContactId = Number(id || 0);
        const item = contactsDB.find(row => Number(row.id) === editingContactId) || {};
        fillContactClients(item.client_id || 0);
        const values = { simpleContactName: item.name || '', simpleContactPosition: item.position || '', simpleContactPhone: item.phone || '', simpleContactEmail: item.email || '' };
        Object.entries(values).forEach(([idKey,value]) => { const el = document.getElementById(idKey); if (el) el.value = value; });
        document.getElementById('contactSimpleEditorTitle').textContent = editingContactId ? 'Редактирование контакта' : 'Новый контакт';
        document.getElementById('contactsSimpleList').hidden = true; document.getElementById('contactsSimpleDetail').hidden = true; const editor = document.getElementById('contactSimpleEditor'); editor.hidden = false; editor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    window.closeSimpleContactEditor = () => { editingContactId = 0; document.getElementById('contactSimpleEditor').hidden = true; document.getElementById('contactsSimpleList').hidden = false; document.getElementById('contactsSimpleDetail').hidden = false; };
    window.saveSimpleContact = async function () {
        const clientId = Number(document.getElementById('simpleContactClientId').value || 0);
        const payload = { client_id: clientId, name: document.getElementById('simpleContactName').value.trim(), position: document.getElementById('simpleContactPosition').value.trim(), phone: document.getElementById('simpleContactPhone').value.trim(), email: document.getElementById('simpleContactEmail').value.trim() };
        if (!payload.client_id) return customAlert('Выберите клиента или контрагента из списка.');
        if (!payload.name) return customAlert('Укажите ФИО контакта.');
        if (!payload.phone && !payload.email) return customAlert('Укажите телефон или электронную почту.');
        const res = await apiCall(editingContactId ? `/contacts/${editingContactId}` : '/contacts', editingContactId ? 'PUT' : 'POST', payload);
        if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить контакт.');
        selectedContactId = num(res.id || editingContactId); editingContactId = 0; closeSimpleContactEditor(); await renderContacts(); showToast('Контакты', 'Контакт сохранён');
    };
    window.deleteSimpleContact = async function (id) {
        if (!(await customConfirm('Удалить контакт из справочника?'))) return;
        const res = await apiCall(`/contacts/${id}`, 'DELETE'); if (!res || res.error) return customAlert(res?.error || 'Не удалось удалить контакт.');
        selectedContactId = 0; await renderContacts(); showToast('Контакты', 'Контакт удалён');
    };
    async function updateSimpleContactBitrixState() {
        const button = document.getElementById('contactsBitrixSyncButton');
        const state = document.getElementById('contactsBitrixState');
        if (!button || !state) return;
        const response = await apiCall('/integrations/bitrix24/status');
        if (!response || response.error === 'forbidden') {
            button.hidden = true; state.hidden = true; return;
        }
        button.hidden = false; state.hidden = false;
        const connected = Boolean(response.configured);
        button.disabled = !connected;
        state.className = `nsi-contact-sync-state ${connected ? 'is-connected' : 'is-disconnected'}`;
        state.textContent = connected ? 'Bitrix24 подключён' : 'Bitrix24 не подключён';
        button.title = connected ? 'Загрузить новые и обновлённые компании из Bitrix24' : 'Сначала подключите Bitrix24 в разделе импорта клиентов';
    }
    window.syncSimpleContactsWithBitrix = async function () {
        const button = document.getElementById('contactsBitrixSyncButton');
        if (!button || button.disabled) return;
        button.disabled = true; button.textContent = 'Синхронизация…';
        try {
            const response = await apiCall('/integrations/bitrix24/sync', 'POST', { limit: 100 });
            if (!response || response.error || response.status === 'failed') return customAlert(response?.error || 'Не удалось синхронизировать Bitrix24.');
            await loadSimpleClients();
            fillContactClients(document.getElementById('simpleContactClientId')?.value || 0);
            showToast('Bitrix24', `Получено ${num(response.rows_total)}, новых ${num(response.created)}, обновлено ${num(response.updated)}`);
        } finally {
            button.textContent = 'Обновить из Bitrix24';
            await updateSimpleContactBitrixState();
        }
    };
})();
