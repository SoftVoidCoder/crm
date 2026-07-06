window.lastTenderDraft = null;
window.pendingProjectArchiveDetails = window.pendingProjectArchiveDetails || {};

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function severityMeta(level) {
    if (level === 'high') return { label: 'Высокий', cls: 'risk-pill risk-pill--high' };
    if (level === 'medium') return { label: 'Средний', cls: 'risk-pill risk-pill--medium' };
    return { label: 'Низкий', cls: 'risk-pill risk-pill--low' };
}

window.openTenderImportModal = function() {
    const modal = document.getElementById('tenderImportModal');
    const result = document.getElementById('tenderParseResult');
    if (!modal || !result) return;
    document.getElementById('tenderSourceInput').value = '';
    document.getElementById('tenderTextInput').value = '';
    result.innerHTML = '<div class="smart-tool-empty">Вставьте ссылку или описание закупки. После разбора я соберу черновик проекта и предложу позиции из НСИ.</div>';
    window.lastTenderDraft = null;
    modal.style.display = 'flex';
};

window.closeTenderImportModal = function() {
    const modal = document.getElementById('tenderImportModal');
    if (modal) modal.style.display = 'none';
};

window.parseTenderDraft = async function() {
    const source = document.getElementById('tenderSourceInput')?.value.trim() || '';
    const text = document.getElementById('tenderTextInput')?.value.trim() || '';
    const result = document.getElementById('tenderParseResult');
    if (!source && !text) return customAlert('Добавьте ссылку или текст закупки.');
    if (result) result.innerHTML = '<div class="smart-tool-empty">Разбираю тендер и ищу совпадения по НСИ...</div>';

    const response = await apiCall('/tenders/parse', 'POST', { source, text });
    if (!response) {
        if (result) result.innerHTML = '<div class="smart-tool-empty">Не удалось разобрать тендер. Попробуйте ещё раз.</div>';
        return;
    }

    window.lastTenderDraft = response;
    const suggestions = (response.suggested_nomenclature || []).map(item => `
        <div class="smart-result-row">
            <div>
                <strong>${escapeHtml(item.name)}</strong>
                <div class="smart-result-sub">${escapeHtml(item.article || 'Без артикула')} · ${escapeHtml(item.match_reason || 'Подобрано по совпадению')}</div>
            </div>
            <div class="smart-result-side">${Number(item.price || 0).toLocaleString('ru-RU')} ₽</div>
        </div>
    `).join('');

    if (result) {
        result.innerHTML = `
            <div class="smart-summary-card">
                <div class="smart-summary-title">${escapeHtml(response.name || 'Черновик проекта')}</div>
                <div class="smart-summary-text">${escapeHtml(response.summary || 'Проверьте данные перед созданием проекта.')}</div>
            </div>
            <div class="smart-result-grid">
                <div class="smart-result-chip"><span>Заказчик</span><strong>${escapeHtml(response.client || 'Не распознан')}</strong></div>
                <div class="smart-result-chip"><span>ИНН</span><strong>${escapeHtml(response.inn || 'Не найден')}</strong></div>
                <div class="smart-result-chip"><span>Дедлайн</span><strong>${escapeHtml(response.deadline || 'Не найден')}</strong></div>
                <div class="smart-result-chip"><span>Бюджет</span><strong>${response.budget ? Number(response.budget).toLocaleString('ru-RU') + ' ₽' : 'Не найден'}</strong></div>
            </div>
            <div class="smart-section-caption">Подходящие позиции из НСИ</div>
            <div class="smart-result-list">
                ${suggestions || '<div class="smart-tool-empty">Подходящие позиции из НСИ не найдены. Можно создать проект и добрать спецификацию вручную.</div>'}
            </div>
            <div class="smart-tool-actions">
                <button class="btn-primary" onclick="applyTenderDraftToProject()">Заполнить карточку проекта</button>
            </div>
        `;
    }
};

window.applyTenderDraftToProject = function() {
    if (!window.lastTenderDraft) return customAlert('Сначала разберите тендер.');
    if (typeof createNewProject === 'function') createNewProject();

    const draft = window.lastTenderDraft;
    const nameInput = document.getElementById('newProjName');
    const clientInput = document.getElementById('newProjClient');
    const budgetInput = document.getElementById('newProjBudget');
    const managerInput = document.getElementById('newProjManager');

    if (nameInput) nameInput.value = draft.name || '';
    if (clientInput) clientInput.value = draft.client || '';
    if (budgetInput) budgetInput.value = draft.budget || '';
    if (managerInput && !managerInput.value) managerInput.value = currentUser?.name || '';

    selectedProjectNomenclature = (draft.suggested_nomenclature || []).map(item => ({
        name: item.name,
        article: item.article,
        price: item.price || 0,
        unit: item.unit || 'шт',
        qty: item.qty || 1
    }));
    if (typeof updateProjectNomList === 'function') updateProjectNomList();

    window.pendingProjectArchiveDetails = draft.archive_details || {};
    closeTenderImportModal();
    showToast('Тендер', 'Черновик проекта заполнен из тендера');
};

function buildPortalUrl(project) {
    const token = project?.archive_details?.guest_portal?.token;
    return token ? `${window.location.origin}/portal/${token}` : '';
}

function renderContractScanResult(scan) {
    if (!scan) {
        return '<div class="smart-tool-empty">Пока нет анализа. Вставьте текст договора выше и запустите проверку.</div>';
    }

    const findings = (scan.findings || []).map(item => {
        const meta = severityMeta(item.severity);
        return `
            <div class="risk-item">
                <div class="risk-item-head">
                    <strong>${escapeHtml(item.title)}</strong>
                    <span class="${meta.cls}">${meta.label}</span>
                </div>
                <div class="smart-result-sub">${escapeHtml(item.details)}</div>
            </div>
        `;
    }).join('');

    const recommendations = (scan.recommendations || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');

    return `
        <div class="scan-score-row">
            <div>
                <div class="scan-score-value">${scan.score}/100</div>
                <div class="smart-result-sub">${escapeHtml(scan.status)}</div>
            </div>
            <div class="smart-result-sub">Сканировано: ${escapeHtml(scan.scanned_at || '')}</div>
        </div>
        <div class="risk-list">${findings || '<div class="smart-tool-empty">Явных отклонений не найдено.</div>'}</div>
        <div class="smart-section-caption">Что предложить на переговорах</div>
        <ul class="smart-recommendations">${recommendations}</ul>
    `;
}

window.renderProjectSmartTools = function() {
    const project = projectsDB.find(item => item.id === currentProjectId);
    if (!project) return;

    const portalLinkInput = document.getElementById('guestPortalLink');
    if (portalLinkInput) portalLinkInput.value = buildPortalUrl(project);

    const scanResult = document.getElementById('contractScanResult');
    if (scanResult) scanResult.innerHTML = renderContractScanResult(project.archive_details?.contract_scan);

    const tenderCard = document.getElementById('tenderSourceCard');
    if (tenderCard) {
        const tender = project.archive_details?.tender_source;
        if (tender) {
            tenderCard.innerHTML = `
                <div class="smart-result-grid">
                    <div class="smart-result-chip"><span>Источник</span><strong>${escapeHtml(tender.url || 'Вручную')}</strong></div>
                    <div class="smart-result-chip"><span>Заказчик</span><strong>${escapeHtml(tender.client || project.client || 'Не указан')}</strong></div>
                    <div class="smart-result-chip"><span>Дедлайн</span><strong>${escapeHtml(tender.deadline || 'Не найден')}</strong></div>
                    <div class="smart-result-chip"><span>Бюджет</span><strong>${tender.budget ? Number(tender.budget).toLocaleString('ru-RU') + ' ₽' : 'Не найден'}</strong></div>
                </div>
                <div class="smart-section-caption">Фрагмент исходных данных</div>
                <div class="smart-source-preview">${escapeHtml((tender.raw_excerpt || '').slice(0, 320) || 'Источник сохранён без текста.')}</div>
            `;
        } else {
            tenderCard.innerHTML = '<div class="smart-tool-empty">Этот проект пока не связан с тендерным источником. Для новых проектов используй кнопку «Создать из тендера» на дашборде.</div>';
        }
    }
};

window.generateGuestPortalLink = async function(regenerate = false) {
    if (!currentProjectId) return;
    const suffix = regenerate ? '?regenerate=1' : '';
    const response = await apiCall(`/projects/${currentProjectId}/guest_portal${suffix}`, 'POST');
    if (!response || response.status !== 'success') return customAlert('Не удалось сгенерировать ссылку.');

    const project = projectsDB.find(item => item.id === currentProjectId);
    if (project) {
        if (!project.archive_details) project.archive_details = {};
        if (!project.archive_details.guest_portal) project.archive_details.guest_portal = {};
        project.archive_details.guest_portal.token = response.token;
    }

    const input = document.getElementById('guestPortalLink');
    const link = `${window.location.origin}${response.url}`;
    if (input) input.value = link;
    showToast('Портал заказчика', 'Ссылка для клиента готова');
};

window.copyGuestPortalLink = async function() {
    const input = document.getElementById('guestPortalLink');
    const value = input?.value || '';
    if (!value) return customAlert('Сначала сгенерируйте ссылку.');
    try {
        await navigator.clipboard.writeText(value);
        showToast('Портал заказчика', 'Ссылка скопирована');
    } catch (error) {
        customAlert(`Не удалось скопировать автоматически. Вот ссылка:\n${value}`);
    }
};

window.openGuestPortal = function() {
    const input = document.getElementById('guestPortalLink');
    const value = input?.value || '';
    if (!value) return customAlert('Сначала сгенерируйте ссылку.');
    window.open(value, '_blank', 'noopener');
};

window.runContractRiskScan = async function() {
    if (!currentProjectId) return;
    const text = document.getElementById('contractScanInput')?.value.trim() || '';
    if (!text) return customAlert('Вставьте текст договора или проблемного раздела.');

    const container = document.getElementById('contractScanResult');
    if (container) container.innerHTML = '<div class="smart-tool-empty">Проверяю договор по внутренним правилам...</div>';

    const response = await apiCall(`/projects/${currentProjectId}/contract_scan`, 'POST', { text });
    if (!response || response.status !== 'success') {
        if (container) container.innerHTML = '<div class="smart-tool-empty">Не удалось выполнить анализ договора.</div>';
        return;
    }

    const project = projectsDB.find(item => item.id === currentProjectId);
    if (project) {
        if (!project.archive_details) project.archive_details = {};
        project.archive_details.contract_scan = response.result;
    }

    if (container) container.innerHTML = renderContractScanResult(response.result);
    showToast('Сканер договора', 'Риски по договору обновлены');
};
