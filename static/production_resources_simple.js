(function () {
    let productionSearch = '';
    let productionStage = '';
    let productionEditingId = 0;
    let resourceSearch = '';
    let resourceDepartment = '';
    let selectedResourceId = 0;

    const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
    const number = value => Number(value || 0) || 0;
    const fmtDate = value => {
        if (!value) return 'Не указана';
        const raw = String(value).slice(0, 10);
        const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        return match ? `${match[3]}.${match[2]}.${match[1]}` : raw;
    };
    const today = () => new Date().toLocaleDateString('ru-RU');
    const dateValue = value => {
        const raw = String(value || '').trim();
        let match = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
        if (match) return Number(`${match[3]}${match[2]}${match[1]}`);
        match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        return match ? Number(`${match[1]}${match[2]}${match[3]}`) : 0;
    };
    const productionStageLabel = value => ({ queue: 'Очередь', in_work: 'В работе', otk: 'Проверка ОТК', done: 'Готово', cancelled: 'Отменён' }[value] || 'Очередь');
    const operationStatusLabel = value => ({ planned: 'Запланировано', in_progress: 'В работе', done: 'Готово', quality_hold: 'На проверке ОТК' }[value] || 'Запланировано');
    const resourceStatusLabel = value => ({ planned: 'План', confirmed: 'Подтверждено', overloaded: 'Перегруз', released: 'Освобождён' }[value] || 'План');
    const priorityLabel = value => ({ critical: 'Критичный', high: 'Высокий', normal: 'Обычный', low: 'Низкий' }[value] || 'Обычный');
    const can = (section, action) => typeof hasCurrentPermission !== 'function' || hasCurrentPermission(section, action);

    function projectTitle(projectId, fallback = '') {
        const project = (typeof projectsDB !== 'undefined' ? projectsDB : []).find(item => Number(item.id) === Number(projectId));
        return fallback || (project ? `${project.contract || 'Без договора'} · ${project.name || 'Проект'}` : 'Без проекта');
    }

    function fillProjectSelect(id, selected = 0) {
        const select = document.getElementById(id);
        if (!select) return;
        select.innerHTML = `<option value="0">Без проекта</option>${(typeof projectsDB !== 'undefined' ? projectsDB : []).map(project => `<option value="${number(project.id)}">${esc(project.contract || 'Без договора')} · ${esc(project.name || 'Проект')}</option>`).join('')}`;
        select.value = String(selected || 0);
    }

    function productionProgress(order) {
        const planned = number(order.planned_qty);
        return planned ? Math.min(100, Math.round(number(order.produced_qty) / planned * 100)) : Math.max(0, Math.min(100, number(order.progress)));
    }

    function filteredProductionOrders() {
        const query = productionSearch.toLowerCase();
        return (typeof productionOrdersDB !== 'undefined' ? productionOrdersDB : []).filter(order => {
            const haystack = [order.order_name, order.client_name, order.project_name, order.project_contract, order.responsible].join(' ').toLowerCase();
            return (!query || haystack.includes(query)) && (!productionStage || (order.stage || 'queue') === productionStage);
        });
    }

    function renderProductionList() {
        const list = document.getElementById('productionSimpleList');
        if (!list) return;
        const rows = filteredProductionOrders();
        list.innerHTML = rows.length ? rows.map(order => {
            const progress = productionProgress(order);
            return `<article class="simple-record-card ${Number(selectedProductionOrderId) === Number(order.id) ? 'is-selected' : ''}">
                <div class="simple-record-card__main"><div class="simple-record-card__top"><span class="simple-status simple-status--${esc(order.stage || 'queue')}">${productionStageLabel(order.stage)}</span><span class="simple-record-card__deadline">до ${fmtDate(order.planned_finish)}</span></div>
                <h3>${esc(order.order_name || 'Производственный заказ')}</h3><p>${esc(projectTitle(order.project_id, order.project_contract || order.project_name || ''))}</p><p>${esc(order.client_name || 'Клиент не указан')} · ${esc(order.responsible || 'Ответственный не назначен')}</p></div>
                <div class="simple-record-card__result"><strong>${number(order.produced_qty)} / ${number(order.planned_qty)}</strong><span>готово, ед.</span><div class="simple-progress"><i style="width:${progress}%"></i></div></div>
                <button class="btn-secondary" type="button" onclick="selectSimpleProductionOrder(${number(order.id)})">Открыть карточку</button>
            </article>`;
        }).join('') : '<div class="simple-empty">Производственных заказов по этому фильтру нет.</div>';
    }

    function productionStageActions(order) {
        if (!can('production', 'update')) return '';
        const stage = order.stage || 'queue';
        if (stage === 'queue') return `<button class="btn-primary" onclick="moveSimpleProductionStage(${order.id},'in_work')">Начать работу</button>`;
        if (stage === 'in_work') return `<button class="btn-primary" onclick="moveSimpleProductionStage(${order.id},'otk')">Передать в ОТК</button>`;
        if (stage === 'otk') return `<button class="btn-secondary" onclick="moveSimpleProductionStage(${order.id},'in_work')">Вернуть в работу</button><button class="btn-primary" onclick="finishSimpleProduction(${order.id})">Заказ готов</button>`;
        if (stage === 'done') return `<button class="btn-secondary" onclick="moveSimpleProductionStage(${order.id},'in_work')">Вернуть в работу</button>`;
        return '';
    }

    async function renderProductionWorkspace() {
        const target = document.getElementById('productionSimpleWorkspace');
        if (!target) return;
        const order = (typeof productionOrdersDB !== 'undefined' ? productionOrdersDB : []).find(item => Number(item.id) === Number(selectedProductionOrderId));
        if (!order) {
            target.innerHTML = '<div class="simple-empty">Откройте заказ из списка — здесь появятся его данные, операции, материалы и документы.</div>';
            return;
        }
        const operations = (typeof productionOperationsDB !== 'undefined' ? productionOperationsDB : []).filter(item => Number(item.order_id) === Number(order.id));
        const materials = (typeof productionBomDB !== 'undefined' ? productionBomDB : []).filter(item => Number(item.order_id) === Number(order.id));
        target.innerHTML = `<article class="simple-detail-card">
            <header class="simple-detail-card__head"><div><span class="simple-status simple-status--${esc(order.stage || 'queue')}">${productionStageLabel(order.stage)}</span><h2>${esc(order.order_name)}</h2><p>${esc(projectTitle(order.project_id, order.project_contract || order.project_name || ''))}</p></div><div class="view-actions">${can('production', 'update') ? `<button class="btn-secondary" onclick="openSimpleProductionEditor(${order.id})">Редактировать</button>` : ''}${productionStageActions(order)}</div></header>
            <div class="simple-detail-summary"><div><span>Клиент</span><strong>${esc(order.client_name || 'Не указан')}</strong></div><div><span>Ответственный</span><strong>${esc(order.responsible || 'Не назначен')}</strong></div><div><span>Срок</span><strong>${fmtDate(order.planned_finish)}</strong></div><div><span>Готовность</span><strong>${productionProgress(order)}%</strong></div></div>
            <div class="simple-workflow-grid">
                <section><div class="simple-section-head"><div><b>1. Заказ</b><small>Что и в каком количестве изготовить</small></div></div><dl class="simple-data-list"><div><dt>План</dt><dd>${number(order.planned_qty)} ед.</dd></div><div><dt>Готово</dt><dd>${number(order.produced_qty)} ед.</dd></div><div><dt>Брак</dt><dd>${number(order.scrap_qty)} ед.</dd></div><div><dt>Приоритет</dt><dd>${priorityLabel(order.priority)}</dd></div></dl>${order.comment ? `<p class="simple-note">${esc(order.comment)}</p>` : ''}</section>
                <section><div class="simple-section-head"><div><b>2. Операции</b><small>Последовательность изготовления</small></div>${can('production','update') ? '<button class="btn-secondary" onclick="openSimpleProductionOperation()">+ Добавить</button>' : ''}</div>${operations.length ? `<div class="simple-mini-list">${operations.map((item, index) => `<div><span>${index + 1}. ${esc(item.operation_name)}</span><small>${esc(item.work_center || 'Участок не указан')} · ${operationStatusLabel(item.status)}</small></div>`).join('')}</div>` : '<p class="simple-placeholder">Операции пока не добавлены.</p>'}</section>
                <section><div class="simple-section-head"><div><b>3. Материалы</b><small>Что потребуется для заказа</small></div>${can('production','update') ? '<button class="btn-secondary" onclick="openSimpleProductionMaterial()">+ Добавить</button>' : ''}</div>${materials.length ? `<div class="simple-mini-list">${materials.map(item => `<div><span>${esc(item.item_name || item.article || 'Материал')}</span><small>${number(item.planned_qty)} ${esc(item.unit || 'шт')} · ${esc(item.warehouse || 'Склад не указан')}</small></div>`).join('')}</div>` : '<p class="simple-placeholder">Материалы пока не добавлены.</p>'}</section>
                <section><div class="simple-section-head"><div><b>4. Документы и ОТК</b><small>Чертежи, ТЗ, спецификации и итог проверки</small></div>${can('production','update') ? '<button class="btn-secondary" onclick="openSimpleProductionDocuments()">+ Документ</button>' : ''}</div><div id="productionSimpleDocuments"><p class="simple-placeholder">Загружаем документы…</p></div></section>
            </div>
        </article>`;
        await renderSimpleProductionDocuments(order.id);
    }

    async function renderSimpleProductionDocuments(orderId) {
        const target = document.getElementById('productionSimpleDocuments');
        if (!target) return;
        const card = await apiCall(`/entity_cards/production_order/${orderId}`);
        const docs = Array.isArray(card?.documents) ? card.documents : [];
        const files = Array.isArray(card?.files) ? card.files : [];
        if (!docs.length && !files.length) {
            target.innerHTML = '<p class="simple-placeholder">Документы пока не прикреплены.</p>';
            return;
        }
        target.innerHTML = `<div class="simple-mini-list">${docs.map(doc => {
            const file = files.find(item => Number(item.document_id) === Number(doc.id));
            const url = file?.file_url || doc.file_url || '';
            return `<div><span>${esc(doc.number || doc.title || doc.subject || 'Документ')}</span><small>${esc(doc.document_kind || doc.doc_type || 'Документ')}</small>${url ? `<a class="simple-link" href="${esc(url)}" target="_blank" rel="noopener">Открыть</a>` : ''}</div>`;
        }).join('')}${files.filter(file => !docs.some(doc => Number(doc.id) === Number(file.document_id))).map(file => `<div><span>${esc(file.file_name || file.name || 'Файл')}</span>${file.file_url ? `<a class="simple-link" href="${esc(file.file_url)}" target="_blank" rel="noopener">Открыть</a>` : ''}</div>`).join('')}</div>`;
    }

    function productionPayload(order, changes = {}) {
        return Object.assign({
            project_id: number(order?.project_id), client_id: number(order?.client_id), client_name: order?.client_name || '',
            legal_entity_id: number(order?.legal_entity_id), business_unit_id: number(order?.business_unit_id), order_name: order?.order_name || '',
            responsible: order?.responsible || '', route_name: order?.route_name || '', stage: order?.stage || 'queue', priority: order?.priority || 'normal',
            planned_start: order?.planned_start || '', planned_finish: order?.planned_finish || '', actual_finish: order?.actual_finish || '',
            planned_qty: number(order?.planned_qty), produced_qty: number(order?.produced_qty), scrap_qty: number(order?.scrap_qty),
            planned_cost: number(order?.planned_cost), actual_cost: number(order?.actual_cost), labor_hours_plan: number(order?.labor_hours_plan), labor_hours_fact: number(order?.labor_hours_fact),
            progress: productionProgress(order || {}), comment: order?.comment || ''
        }, changes);
    }

    window.renderProduction = async function () {
        await loadOpsData();
        const rows = typeof productionOrdersDB !== 'undefined' ? productionOrdersDB : [];
        if (selectedProductionOrderId && !rows.some(item => Number(item.id) === Number(selectedProductionOrderId))) selectedProductionOrderId = 0;
        const metrics = document.getElementById('productionSimpleMetrics');
        if (metrics) {
            const count = stage => rows.filter(item => (item.stage || 'queue') === stage).length;
            metrics.innerHTML = `<div><span>В очереди</span><strong>${count('queue')}</strong></div><div><span>В работе</span><strong>${count('in_work')}</strong></div><div><span>На проверке ОТК</span><strong>${count('otk')}</strong></div><div><span>Готово</span><strong>${count('done')}</strong></div>`;
        }
        fillProjectSelect('simpleProductionProject');
        renderProductionList();
        await renderProductionWorkspace();
    };

    window.setSimpleProductionSearch = value => { productionSearch = String(value || '').trim(); renderProductionList(); };
    window.setSimpleProductionStage = value => { productionStage = value || ''; renderProductionList(); };
    window.resetSimpleProductionFilters = () => { productionSearch = ''; productionStage = ''; document.getElementById('productionSimpleSearch').value = ''; document.getElementById('productionSimpleStage').value = ''; renderProductionList(); };
    window.selectSimpleProductionOrder = async id => { selectedProductionOrderId = Number(id); renderProductionList(); await renderProductionWorkspace(); document.getElementById('productionSimpleWorkspace')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };

    function hideProductionPanels() {
        ['productionSimpleList', 'productionSimpleWorkspace', 'productionSimpleEditor', 'productionSimpleOperationForm', 'productionSimpleMaterialForm'].forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
    }
    function showProductionMain() {
        ['productionSimpleList', 'productionSimpleWorkspace'].forEach(id => { const el = document.getElementById(id); if (el) el.hidden = false; });
    }
    window.openSimpleProductionEditor = function (id = 0) {
        if (!can('production', id ? 'update' : 'create')) return customAlert('У вашей роли нет права изменять производственные заказы.');
        productionEditingId = Number(id || 0);
        const order = (typeof productionOrdersDB !== 'undefined' ? productionOrdersDB : []).find(item => Number(item.id) === productionEditingId) || {};
        hideProductionPanels();
        const editor = document.getElementById('productionSimpleEditor'); editor.hidden = false;
        document.getElementById('productionSimpleEditorTitle').textContent = productionEditingId ? 'Редактирование заказа' : 'Новый заказ';
        fillProjectSelect('simpleProductionProject', order.project_id);
        const values = { simpleProductionName: order.order_name || '', simpleProductionClient: order.client_name || '', simpleProductionResponsible: order.responsible || currentUser?.name || '', simpleProductionStatus: order.stage || 'queue', simpleProductionStart: order.planned_start || '', simpleProductionFinish: order.planned_finish || '', simpleProductionPlanQty: number(order.planned_qty) || '', simpleProductionDoneQty: number(order.produced_qty) || '', simpleProductionScrapQty: number(order.scrap_qty) || '', simpleProductionPriority: order.priority || 'normal', simpleProductionComment: order.comment || '' };
        Object.entries(values).forEach(([key, value]) => { const el = document.getElementById(key); if (el) el.value = value; });
        editor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    window.closeSimpleProductionEditor = async function () { productionEditingId = 0; document.getElementById('productionSimpleEditor').hidden = true; showProductionMain(); await renderProductionWorkspace(); };
    window.saveSimpleProductionOrder = async function () {
        const old = (typeof productionOrdersDB !== 'undefined' ? productionOrdersDB : []).find(item => Number(item.id) === productionEditingId) || {};
        const name = document.getElementById('simpleProductionName').value.trim();
        if (!name) return customAlert('Укажите название производственного заказа.');
        const payload = productionPayload(old, { order_name: name, project_id: number(document.getElementById('simpleProductionProject').value), client_name: document.getElementById('simpleProductionClient').value.trim(), responsible: document.getElementById('simpleProductionResponsible').value.trim(), stage: document.getElementById('simpleProductionStatus').value, planned_start: document.getElementById('simpleProductionStart').value.trim(), planned_finish: document.getElementById('simpleProductionFinish').value.trim(), planned_qty: number(document.getElementById('simpleProductionPlanQty').value), produced_qty: number(document.getElementById('simpleProductionDoneQty').value), scrap_qty: number(document.getElementById('simpleProductionScrapQty').value), priority: document.getElementById('simpleProductionPriority').value, comment: document.getElementById('simpleProductionComment').value.trim() });
        payload.progress = payload.planned_qty ? Math.min(100, Math.round(payload.produced_qty / payload.planned_qty * 100)) : 0;
        const res = await apiCall(productionEditingId ? `/production/orders/${productionEditingId}` : '/production/orders', productionEditingId ? 'PUT' : 'POST', payload);
        if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить производственный заказ.');
        selectedProductionOrderId = number(res.id || productionEditingId);
        productionEditingId = 0; document.getElementById('productionSimpleEditor').hidden = true; showProductionMain(); await renderProduction(); showToast('Производство', 'Заказ сохранён');
    };
    window.moveSimpleProductionStage = async function (id, stage) {
        const order = productionOrdersDB.find(item => Number(item.id) === Number(id)); if (!order) return;
        const res = await apiCall(`/production/orders/${id}`, 'PUT', productionPayload(order, { stage, actual_finish: stage === 'done' ? today() : order.actual_finish || '', progress: stage === 'done' ? 100 : productionProgress(order) }));
        if (!res || res.error) return customAlert(res?.error || 'Не удалось изменить этап заказа.');
        selectedProductionOrderId = Number(id); await renderProduction(); showToast('Производство', `Этап: ${productionStageLabel(stage)}`);
    };
    window.finishSimpleProduction = async function (id) {
        const result = await customPrompt('Результат проверки ОТК', 'Например: принято без замечаний');
        if (result === null) return;
        const order = productionOrdersDB.find(item => Number(item.id) === Number(id)); if (!order) return;
        const comment = [order.comment, result ? `ОТК: ${result}` : 'ОТК: принято'].filter(Boolean).join('\n');
        const res = await apiCall(`/production/orders/${id}`, 'PUT', productionPayload(order, { stage: 'done', actual_finish: today(), progress: 100, comment }));
        if (!res || res.error) return customAlert(res?.error || 'Не удалось завершить заказ.');
        await renderProduction(); showToast('Производство', 'Заказ завершён');
    };

    window.openSimpleProductionOperation = () => { hideProductionPanels(); document.getElementById('productionSimpleOperationForm').hidden = false; document.getElementById('productionSimpleOperationForm').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    window.openSimpleProductionMaterial = () => { hideProductionPanels(); document.getElementById('productionSimpleMaterialForm').hidden = false; document.getElementById('productionSimpleMaterialForm').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    window.closeSimpleProductionSubforms = async () => { ['productionSimpleOperationForm','productionSimpleMaterialForm'].forEach(id => document.getElementById(id).hidden = true); showProductionMain(); await renderProductionWorkspace(); };
    window.saveSimpleProductionOperation = async function () {
        const name = document.getElementById('simpleOperationName').value.trim(); if (!name) return customAlert('Укажите название операции.');
        const current = productionOperationsDB.filter(item => Number(item.order_id) === Number(selectedProductionOrderId));
        const payload = { order_id: number(selectedProductionOrderId), sequence_no: current.length + 1, operation_name: name, work_center: document.getElementById('simpleOperationCenter').value.trim(), status: document.getElementById('simpleOperationStatus').value, planned_hours: number(document.getElementById('simpleOperationHours').value), actual_hours: 0, planned_qty: number(document.getElementById('simpleOperationQty').value), completed_qty: 0, scrap_qty: 0, labor_rate: 0, material_cost: 0, overhead_cost: 0, started_at: '', finished_at: '', note: document.getElementById('simpleOperationComment').value.trim() };
        const res = await apiCall('/production/operations', 'POST', payload); if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить операцию.');
        await renderProduction(); closeSimpleProductionSubforms(); showToast('Производство', 'Операция добавлена');
    };
    window.saveSimpleProductionMaterial = async function () {
        const name = document.getElementById('simpleMaterialName').value.trim(); if (!name) return customAlert('Укажите материал.');
        const qty = number(document.getElementById('simpleMaterialQty').value);
        const payload = { order_id: number(selectedProductionOrderId), article: document.getElementById('simpleMaterialArticle').value.trim(), item_name: name, unit: document.getElementById('simpleMaterialUnit').value.trim() || 'шт', qty_per_unit: 0, planned_qty: qty, actual_qty: 0, unit_cost: 0, warehouse: document.getElementById('simpleMaterialWarehouse').value.trim(), bin_code: '', note: document.getElementById('simpleMaterialComment').value.trim() };
        const res = await apiCall('/production/bom', 'POST', payload); if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить материал.');
        await renderProduction(); closeSimpleProductionSubforms(); showToast('Производство', 'Материал добавлен');
    };
    window.openSimpleProductionDocuments = () => { if (typeof openProductionDocumentsOffice === 'function') return openProductionDocumentsOffice(); navigateTo('documents'); };

    function filteredResources() {
        const query = resourceSearch.toLowerCase();
        return (typeof resourceAllocationsDB !== 'undefined' ? resourceAllocationsDB : []).filter(item => {
            const haystack = [item.resource_name, item.department, item.role_name, item.project_name, item.project_contract, item.location].join(' ').toLowerCase();
            return (!query || haystack.includes(query)) && (!resourceDepartment || item.department === resourceDepartment);
        });
    }
    function renderResourceList() {
        const target = document.getElementById('resourcesSimpleList'); if (!target) return;
        const rows = filteredResources();
        target.innerHTML = rows.length ? rows.map(item => `<article class="simple-record-card ${Number(selectedResourceId) === Number(item.id) ? 'is-selected' : ''}"><div class="simple-record-card__main"><div class="simple-record-card__top"><span class="simple-status simple-status--${esc(item.status || 'planned')}">${resourceStatusLabel(item.status)}</span><span class="simple-record-card__deadline">${fmtDate(item.date_from)} — ${fmtDate(item.date_to)}</span></div><h3>${esc(item.resource_name || 'Ресурс')}</h3><p>${esc(item.department || 'Отдел не указан')} · ${esc(item.role_name || 'Функция не указана')}</p><p>${esc(projectTitle(item.project_id, item.project_contract || item.project_name || ''))}</p></div><div class="simple-record-card__result"><strong>${number(item.load_percent)}%</strong><span>загрузка</span></div><button class="btn-secondary" onclick="selectSimpleResource(${number(item.id)})">Открыть карточку</button></article>`).join('') : '<div class="simple-empty">Записей по этому фильтру нет.</div>';
    }
    function renderResourceDetail() {
        const target = document.getElementById('resourcesSimpleDetail'); if (!target) return;
        const item = resourceAllocationsDB.find(row => Number(row.id) === Number(selectedResourceId));
        if (!item) { target.innerHTML = '<div class="simple-empty">Откройте запись из списка — здесь появится полная карточка занятости.</div>'; return; }
        target.innerHTML = `<article class="simple-detail-card"><header class="simple-detail-card__head"><div><span class="simple-status simple-status--${esc(item.status || 'planned')}">${resourceStatusLabel(item.status)}</span><h2>${esc(item.resource_name)}</h2><p>${esc(item.role_name || 'Функция не указана')}</p></div><div class="view-actions">${can('resources','update') ? `<button class="btn-primary" onclick="openSimpleResourceEditor(${item.id})">Редактировать</button>` : ''}${can('resources','delete') ? `<button class="btn-danger" onclick="deleteResourceAllocation(${item.id})">Удалить</button>` : ''}</div></header><div class="simple-detail-summary"><div><span>Проект</span><strong>${esc(projectTitle(item.project_id, item.project_contract || item.project_name || ''))}</strong></div><div><span>Отдел</span><strong>${esc(item.department || 'Не указан')}</strong></div><div><span>Период</span><strong>${fmtDate(item.date_from)} — ${fmtDate(item.date_to)}</strong></div><div><span>Загрузка</span><strong>${number(item.load_percent)}%</strong></div></div><div class="resource-detail-grid"><div><span>Место работы</span><strong>${esc(item.location || 'Не указано')}</strong></div><div><span>Статус</span><strong>${resourceStatusLabel(item.status)}</strong></div>${item.comment ? `<div class="is-wide"><span>Комментарий</span><strong>${esc(item.comment)}</strong></div>` : ''}</div></article>`;
    }
    window.renderResources = async function () {
        await loadEnterpriseData(); fillProjectSelect('resourceProjectId');
        const rows = resourceAllocationsDB; if (selectedResourceId && !rows.some(item => Number(item.id) === Number(selectedResourceId))) selectedResourceId = 0;
        const active = rows.filter(item => item.status !== 'released'); const avg = active.length ? Math.round(active.reduce((sum,item) => sum + number(item.load_percent), 0) / active.length) : 0;
        const metrics = document.getElementById('resourcesSimpleMetrics'); if (metrics) metrics.innerHTML = `<div><span>Запланировано</span><strong>${rows.length}</strong></div><div><span>Сейчас заняты</span><strong>${active.length}</strong></div><div><span>Перегруз</span><strong>${rows.filter(item => item.status === 'overloaded' || number(item.load_percent) > 100).length}</strong></div><div><span>Средняя загрузка</span><strong>${avg}%</strong></div>`;
        renderResourceList(); renderResourceDetail();
    };
    window.setSimpleResourceSearch = value => { resourceSearch = String(value || '').trim(); renderResourceList(); };
    window.setSimpleResourceDepartment = value => { resourceDepartment = value || ''; renderResourceList(); };
    window.resetSimpleResourceFilters = () => { resourceSearch = ''; resourceDepartment = ''; document.getElementById('resourcesSimpleSearch').value = ''; document.getElementById('resourcesSimpleDepartment').value = ''; renderResourceList(); };
    window.selectSimpleResource = id => { selectedResourceId = Number(id); renderResourceList(); renderResourceDetail(); document.getElementById('resourcesSimpleDetail')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    window.openSimpleResourceEditor = function (id = 0) {
        if (!can('resources', id ? 'update' : 'create')) return customAlert('У вашей роли нет права изменять календарь ресурсов.');
        const item = resourceAllocationsDB.find(row => Number(row.id) === Number(id)); editingResourceId = Number(id || 0);
        fillProjectSelect('resourceProjectId', item?.project_id || 0);
        const values = { resourceDepartment: item?.department || 'Менеджер', resourceName: item?.resource_name || '', resourceRoleName: item?.role_name || '', resourceCrewName: item?.crew_name || '', resourceCrewType: item?.crew_type || '', resourceDateFrom: item?.date_from || '', resourceDateTo: item?.date_to || '', resourceLoadPercent: number(item?.load_percent) || '', resourceStatus: item?.status || 'planned', resourceLocation: item?.location || '', resourceComment: item?.comment || '' };
        Object.entries(values).forEach(([key,value]) => { const el = document.getElementById(key); if (el) el.value = value; });
        document.getElementById('resourceEditorTitle').textContent = id ? 'Редактирование загрузки' : 'Новая загрузка'; document.getElementById('resourceSaveButton').textContent = id ? 'Сохранить изменения' : 'Добавить в календарь';
        document.getElementById('resourcesSimpleList').hidden = true; document.getElementById('resourcesSimpleDetail').hidden = true; const editor = document.getElementById('resourceEditorCard'); editor.hidden = false; editor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    window.editResourceAllocation = id => openSimpleResourceEditor(id);
    window.closeSimpleResourceEditor = function () { editingResourceId = 0; document.getElementById('resourceEditorCard').hidden = true; document.getElementById('resourcesSimpleList').hidden = false; document.getElementById('resourcesSimpleDetail').hidden = false; };
    window.saveResourceAllocation = async function () {
        if (!can('resources', editingResourceId ? 'update' : 'create')) return customAlert('Недостаточно прав для изменения календаря.');
        const payload = { project_id: number(document.getElementById('resourceProjectId').value), department: document.getElementById('resourceDepartment').value, resource_name: document.getElementById('resourceName').value.trim(), role_name: document.getElementById('resourceRoleName').value.trim(), crew_name: '', crew_type: '', load_percent: number(document.getElementById('resourceLoadPercent').value), date_from: document.getElementById('resourceDateFrom').value.trim(), date_to: document.getElementById('resourceDateTo').value.trim(), location: document.getElementById('resourceLocation').value.trim(), status: document.getElementById('resourceStatus').value, comment: document.getElementById('resourceComment').value.trim() };
        if (!payload.resource_name) return customAlert('Укажите сотрудника или название ресурса.');
        if (!payload.date_from || !payload.date_to) return customAlert('Укажите дату начала и дату окончания.');
        if (dateValue(payload.date_to) < dateValue(payload.date_from)) return customAlert('Дата окончания не может быть раньше даты начала.');
        if (payload.load_percent < 1 || payload.load_percent > 100) return customAlert('Укажите загрузку от 1 до 100%.');
        const id = editingResourceId; const res = await apiCall(id ? `/resources/allocations/${id}` : '/resources/allocations', id ? 'PUT' : 'POST', payload); if (!res || res.error) return customAlert(res?.error || 'Не удалось сохранить загрузку ресурса.');
        selectedResourceId = number(res.id || id); editingResourceId = 0; closeSimpleResourceEditor(); await renderResources(); showToast('Календарь ресурсов', 'Загрузка сохранена');
    };
})();
