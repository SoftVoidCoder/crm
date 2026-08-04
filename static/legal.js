// ==========================================
// ЮРИДИЧЕСКИЙ МОДУЛЬ: ПРЕТЕНЗИИ И СУДЫ
// ==========================================
function getLegalScaleIcon() {
    return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 16v2a4 4 0 0 1-4 4 4 4 0 0 1-4-4v-2"></path><path d="M12 4v12"></path><path d="M3 7h18"></path><path d="m7 7-3 5a3 3 0 0 0 6 0L7 7Z"></path><path d="m17 7-3 5a3 3 0 0 0 6 0l-3-5Z"></path></svg>`;
}

function getLegalCreateIcon() {
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>`;
}

function getLegalExportIcon() {
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path></svg>`;
}

function getLegalDocIcon() {
    return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7Z"></path><path d="M14 2v5h5"></path><path d="M9 13h6"></path><path d="M9 17h6"></path></svg>`;
}

function getLegalSectionTitle(title, subtitle = '') {
    return `
        <div class="legal-title-row">
            <div class="legal-icon legal-icon--hero">${getLegalScaleIcon()}</div>
            <div>
                <h2 class="legal-page-title">${title}</h2>
                ${subtitle ? `<p class="legal-page-subtitle">${subtitle}</p>` : ''}
            </div>
        </div>
    `;
}

function getLegalCreateButtonLabel(tab) {
    const text = tab === 'claims' ? 'Создать претензию' : 'Добавить дело';
    return `${getLegalCreateIcon()}<span>${text}</span>`;
}

function renderLegalToolbarButton(kind) {
    const isClaims = kind === 'claims';
    const fileName = isClaims ? 'Реестр_Претензий' : 'Реестр_Судебных_Дел';
    const source = isClaims ? 'claimsDB' : 'courtCasesDB';
    return `
        <button class="btn-secondary legal-export-btn no-print" onclick="exportDataToExcel(${source}, '${fileName}')">
            ${getLegalExportIcon()}
            <span>Экспорт в таблицу</span>
        </button>
    `;
}

function initClaimsUI() {
    const sidebar = document.querySelector('.sidebar');
    if (sidebar && !document.getElementById('navClaims')) {
        const btn = document.createElement('a');
        btn.href = "#"; btn.id = "navClaims"; btn.className = "nav-item";
        btn.innerHTML = `${getLegalScaleIcon()}<span>Претензии и Суды</span>`;
        btn.onclick = (e) => { 
            e.preventDefault();
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            btn.classList.add('active');
            if (typeof navigateTo === 'function') navigateTo('claims'); 
            renderClaims();
        };
        sidebar.appendChild(btn);
    }

    const mainContent = document.querySelector('.main-content');
    if (mainContent && !document.getElementById('claimsView')) {
        const claimsView = document.createElement('div');
        claimsView.id = "claimsView"; claimsView.className = "view-page fade-in legal-shell"; claimsView.style.display = "none";
        claimsView.innerHTML = `
            <div class="legal-hero">
                ${getLegalSectionTitle('Претензии и Суды', 'Единый реестр досудебной и судебной работы')}
                <button id="btnCreateLegal" class="btn-primary legal-create-btn" onclick="openCreateLegalModal()">${getLegalCreateButtonLabel('claims')}</button>
            </div>
            <div class="legal-toolbar">
                <div class="legal-tabs">
                    <button id="tabLegalClaims" class="btn-secondary active btn-sm" onclick="switchLegalTab('claims')">Досудебные претензии</button>
                    <button id="tabLegalCourts" class="btn-secondary btn-sm" onclick="switchLegalTab('courts')">Судебные дела</button>
                </div>
                <div id="legalToolbarActions" class="legal-toolbar-actions"></div>
            </div>
            <div class="legal-board"><div id="legalListContainer"></div></div>
        `;
        mainContent.appendChild(claimsView);
        if (typeof mountSectionGuideForView === 'function') mountSectionGuideForView('claimsView');
    }

    if (!document.getElementById('createCourtModal')) {
        document.body.insertAdjacentHTML('beforeend', `
        <div id="createCourtModal" class="modal modal-overlay-custom">
            <div class="modal-content fade-in modal-content-custom">
                <h3 class="legal-title legal-modal-title">${getLegalScaleIcon()}<span>Новое судебное дело</span></h3>
                <div class="form-grid">
                    <div><label class="form-label-custom">Номер дела</label><input type="text" id="courtNum" class="auth-input form-input-custom" placeholder="Например, А56-123/2024"></div>
                    <div><label class="form-label-custom">Суд</label><input type="text" id="courtName" class="auth-input form-input-custom" placeholder="АС г. Санкт-Петербурга"></div>
                    <div><label class="form-label-custom">Истец</label><input type="text" id="courtPlain" class="auth-input form-input-custom" value="ООО «КОРДА»"></div>
                    <div><label class="form-label-custom">Ответчик</label><input type="text" id="courtDef" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Сумма иска (₽)</label><input type="number" id="courtAmount" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Привязка к договору</label><select id="courtProj" class="auth-input form-input-custom"></select></div>
                    <div><label class="form-label-custom">Инстанция</label>
                        <select id="courtInst" class="auth-input form-input-custom">
                            <option value="Первая">Первая инстанция</option>
                            <option value="Апелляция">Апелляционная инстанция</option>
                            <option value="Кассация">Кассационная инстанция</option>
                        </select>
                    </div>
                    <div><label class="form-label-custom">Дата след. заседания</label><input type="date" id="courtHearing" class="auth-input form-input-custom"></div>
                </div>
                <div class="modal-footer-custom">
                    <button class="btn-secondary" onclick="document.getElementById('createCourtModal').style.display='none'">Отмена</button>
                    <button class="btn-primary" onclick="submitNewCourt()">Сохранить дело</button>
                </div>
            </div>
        </div>`);
    }

    if (!document.getElementById('createClaimModal')) {
        document.body.insertAdjacentHTML('beforeend', `
        <div id="createClaimModal" class="modal modal-overlay-custom">
            <div class="modal-content fade-in modal-content-custom medium">
                <h3 class="legal-title legal-modal-title">${getLegalScaleIcon()}<span>Новая претензия</span></h3>
                <div class="form-grid">
                    <div><label class="form-label-custom">Номер претензии</label><input type="text" id="claimNum" class="auth-input form-input-custom" placeholder="Например, ПР-01"></div>
                    <div><label class="form-label-custom">Дата составления</label><input type="date" id="claimDate" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Инициатор</label><input type="text" id="claimInit" class="auth-input form-input-custom" value="ООО «КОРДА»"></div>
                    <div><label class="form-label-custom">Адресат (Контрагент)</label><input type="text" id="claimAddr" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Сумма требований (₽)</label><input type="number" id="claimAmount" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Привязка к договору</label><select id="claimProj" class="auth-input form-input-custom"></select></div>
                    <div><label class="form-label-custom">Дата направления</label><input type="date" id="claimDateSent" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Срок ответа до</label><input type="date" id="claimDeadline" class="auth-input form-input-custom"></div>
                </div>
                <div class="modal-footer-custom">
                    <button class="btn-secondary" onclick="document.getElementById('createClaimModal').style.display='none'">Отмена</button>
                    <button class="btn-primary" onclick="submitNewClaim()">Сохранить в реестр</button>
                </div>
            </div>
        </div>`);
    }

    if (typeof window.navigateTo === 'function') {
        const origNav = window.navigateTo;
        if (!window.__kordaLegalNavigatePatched) {
            window.navigateTo = function(viewId, triggerRender = true) {
                origNav(viewId, triggerRender);
                const cv = document.getElementById('claimsView');
                if (cv) cv.style.display = viewId === 'claims' ? 'block' : 'none';
                if (viewId === 'claims') {
                    if (currentLegalTab === 'claims') renderClaims();
                    else renderCourts();
                }
            };
            window.__kordaLegalNavigatePatched = true;
        }
    }
}

window.openCreateLegalModal = function() {
    if (currentLegalTab === 'claims') openCreateClaimModal();
    else openCreateCourtModal();
};

window.switchLegalTab = function(tab) {
    currentLegalTab = tab;
    document.getElementById('tabLegalClaims').classList.toggle('active', tab === 'claims');
    document.getElementById('tabLegalCourts').classList.toggle('active', tab === 'courts');
    document.getElementById('btnCreateLegal').innerHTML = getLegalCreateButtonLabel(tab);
    if (tab === 'claims') renderClaims(); else renderCourts();
};

window.renderClaims = function() {
    const container = document.getElementById('legalListContainer');
    const toolbarActions = document.getElementById('legalToolbarActions');
    if (!container) return;
    if (toolbarActions) toolbarActions.innerHTML = renderLegalToolbarButton('claims');

    if (claimsDB.length === 0) {
        container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--secondary); background:rgba(0,0,0,0.02); border-radius:8px; border:1px dashed var(--border);">Нет зарегистрированных претензий.</div>';
        return;
    }

    let html = '<table class="admin-table" style="width:100%; text-align:left; border-collapse:collapse;"><thead><tr style="border-bottom:2px solid var(--border);"><th>№ и Дата</th><th>Договор / Контрагент</th><th>Сумма (₽)</th><th>Статусы и Сроки</th><th>Действия</th></tr></thead><tbody>';
    const today = new Date(); today.setHours(0,0,0,0);
    
    claimsDB.forEach(c => {
        const p = projectsDB.find(x => x.id === c.proj_id);
        const pName = p ? p.contract : 'Договор не найден';
        
        let statusColor = 'var(--secondary)';
        if (c.status === 'Направлена') statusColor = 'var(--primary)';
        if (c.status === 'Ответ получен') statusColor = '#f59e0b';
        if (c.status === 'Урегулирована') statusColor = 'var(--success)';
        if (c.status === 'Отклонена') statusColor = 'var(--danger)';
        
        let deadlineColor = 'var(--text)';
        if (c.deadline && (c.status === 'Направлена' || c.status === 'Подготовка')) {
            const parts = c.deadline.split('-');
            if (parts.length === 3 && new Date(parts[0], parts[1]-1, parts[2]) < today) deadlineColor = 'var(--danger)';
        }

        html += `<tr style="border-bottom:1px solid var(--border);">
            <td style="padding:10px 5px;"><b>№ ${c.number}</b><br><span style="font-size:11px; color:var(--secondary);">от ${c.d_date}</span></td>
            <td style="padding:10px 5px;"><span style="color:var(--primary); cursor:pointer; font-weight:600; text-decoration:underline;" onclick="if(typeof openProject==='function'){openProject(${c.proj_id});}">${pName}</span><br><span style="font-size:12px;">${c.addressee}</span></td>
            <td style="padding:10px 5px; font-weight:bold;">${c.amount.toLocaleString('ru-RU')} ₽</td>
            <td style="padding:10px 5px;">
                <span style="background:${statusColor}; color:white; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600;">${c.status}</span>
                <div style="font-size:11px; margin-top:6px; color:var(--secondary);">Срок ответа: <b style="color:${deadlineColor};">${c.deadline || 'Не указан'}</b></div>
            </td>
            <td style="padding:10px 5px; display:flex; gap:5px; flex-direction:column;">
                <select class="auth-input legal-select" onchange="updateClaimStatus(${c.id}, this.value)">
                    <option value="Подготовка" ${c.status==='Подготовка'?'selected':''}>Подготовка</option>
                    <option value="Направлена" ${c.status==='Направлена'?'selected':''}>Направлена</option>
                    <option value="Ответ получен" ${c.status==='Ответ получен'?'selected':''}>Ответ получен</option>
                    <option value="Урегулирована" ${c.status==='Урегулирована'?'selected':''}>Урегулирована</option>
                    <option value="Отклонена" ${c.status==='Отклонена'?'selected':''}>Отклонена</option>
                </select>
                <button class="btn-secondary btn-xs legal-inline-btn" onclick="generateClaimTemplate(${c.id})">${getLegalDocIcon()}<span>Шаблон</span></button>
            </td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
};

window.openCreateClaimModal = function() {
    const sel = document.getElementById('claimProj');
    sel.innerHTML = '<option value="" disabled selected>Выберите договор...</option>' + projectsDB.map(p => `<option value="${p.id}">${p.contract} (${p.client})</option>`).join('');
    document.getElementById('claimDate').value = new Date().toISOString().split('T')[0];
    document.getElementById('createClaimModal').style.display = 'flex';
};

window.submitNewClaim = async function() {
    const data = {
        number: document.getElementById('claimNum').value || 'Б/Н',
        d_date: document.getElementById('claimDate').value || new Date().toISOString().split('T')[0],
        initiator: document.getElementById('claimInit').value || 'ООО КОРДА',
        addressee: document.getElementById('claimAddr').value || 'Не указан',
        amount: parseFloat(document.getElementById('claimAmount').value) || 0,
        proj_id: parseInt(document.getElementById('claimProj').value) || 0,
        date_sent: document.getElementById('claimDateSent').value || '',
        deadline: document.getElementById('claimDeadline').value || '',
        date_answered: '',
        status: 'Подготовка'
    };
    if(!data.proj_id) return customAlert("❌ Выберите связанный договор!");

    const res = await apiCall('/claims', 'POST', data);
    if(res && res.status === 'success') {
        document.getElementById('createClaimModal').style.display = 'none';
        await loadClaims(); renderClaims();
        if(typeof showToast === 'function') showToast("Претензии", "Претензия успешно создана");
        
        const p = projectsDB.find(x => x.id === data.proj_id);
        if (p) {
            if(!p.logs) p.logs = [];
            const now = new Date();
            p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: `⚖️ Зарегистрирована претензия №${data.number} на сумму ${data.amount} руб.`});
            await apiCall(`/projects/${p.id}`, 'PUT', p);
        }
    } else {
        customAlert("❌ Ошибка при создании");
    }
};

window.updateClaimStatus = async function(id, newStatus) {
    const c = claimsDB.find(x => x.id === id);
    if(!c) return;
    c.status = newStatus;
    await apiCall(`/claims/${c.id}`, 'PUT', c);
    await loadClaims(); renderClaims();
    if(typeof showToast === 'function') showToast("Претензии", `Статус изменен на: ${newStatus}`);
};

window.generateClaimTemplate = function(claimId) {
    const c = claimsDB.find(x => x.id === claimId);
    if (!c) return;
    const p = projectsDB.find(x => x.id === c.proj_id);
    if (!p) return;

    const docText = `ДОСУДЕБНАЯ ПРЕТЕНЗИЯ № ${c.number}\nДата: ${c.d_date}\n\nКому: ${c.addressee}\nОт кого: ${c.initiator}\n\nПо договору ${p.contract} от Заказчика/Исполнителя была выявлена задолженность (или неисполнение обязательств).\nСумма требований по настоящей претензии составляет: ${c.amount} руб.\n\nПросим урегулировать данную задолженность в срок до ${c.deadline || 'установленного договором времени'}. \nВ случае отсутствия ответа или отказа в удовлетворении требований, мы будем вынуждены обратиться в Арбитражный суд для защиты своих законных интересов, с возложением на Вас всех судебных издержек.\n\nС уважением,\nРуководитель ___________________`;
    const fileName = `Pretenziya_N${c.number.replace(/[\\/\\s\\?]/g, '_')}_${p.contract.replace(/[\\/\\s\\?]/g, '_')}.txt`;
    const blob = new Blob([docText], { type: 'text/plain;charset=utf-8' });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = fileName;
    link.click();
    URL.revokeObjectURL(link.href);
    if (typeof showToast === 'function') showToast("Шаблон", "Претензия скачана");
};

window.renderCourts = function() {
    const container = document.getElementById('legalListContainer');
    const toolbarActions = document.getElementById('legalToolbarActions');
    if (!container) return;
    if (toolbarActions) toolbarActions.innerHTML = renderLegalToolbarButton('courts');

    if (courtCasesDB.length === 0) {
        container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--secondary); background:rgba(0,0,0,0.02); border-radius:8px; border:1px dashed var(--border);">Нет зарегистрированных судебных дел.</div>';
        return;
    }

    let html = '<table class="admin-table" style="width:100%; text-align:left; border-collapse:collapse;"><thead><tr style="border-bottom:2px solid var(--border);"><th>Дело и Суд</th><th>Договор и Стороны</th><th>Сумма (₽)</th><th>Стадия и Заседания</th><th>Действия</th></tr></thead><tbody>';
    
    courtCasesDB.forEach(c => {
        const p = projectsDB.find(x => x.id === c.proj_id);
        const pName = p ? p.contract : 'Договор не найден';
        
        let stageColor = 'var(--primary)';
        if (c.stage === 'Закрыто') stageColor = 'var(--success)';
        if (c.stage === 'Приостановлено') stageColor = 'var(--secondary)';
        if (c.stage === 'Обжаловано') stageColor = '#f59e0b';
        if (c.stage === 'Вынесение решения') stageColor = '#8b5cf6';
        
        html += `<tr style="border-bottom:1px solid var(--border);">
            <td style="padding:10px 5px;"><b>${c.number}</b><br><span style="font-size:11px; color:var(--secondary);">${c.court_name}</span><br><span style="font-size:10px; background:rgba(0,0,0,0.05); padding:2px 4px; border-radius:4px; display:inline-block; margin-top:4px;">${c.instance}</span></td>
            <td style="padding:10px 5px;"><span style="color:var(--primary); cursor:pointer; font-weight:600; text-decoration:underline;" onclick="if(typeof openProject==='function'){openProject(${c.proj_id});}">${pName}</span><br><span style="font-size:11px; color:var(--secondary);">Истец:</span> <span style="font-size:11px;">${c.plaintiff}</span><br><span style="font-size:11px; color:var(--secondary);">Ответчик:</span> <span style="font-size:11px;">${c.defendant}</span></td>
            <td style="padding:10px 5px; font-weight:bold;">${c.amount.toLocaleString('ru-RU')} ₽</td>
            <td style="padding:10px 5px;">
                <span style="background:${stageColor}; color:white; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600;">${c.stage}</span>
                <div style="font-size:11px; margin-top:6px; color:var(--secondary);">След. заседание: <b style="color:var(--text);">${c.next_hearing || 'Не назначено'}</b></div>
            </td>
            <td style="padding:10px 5px; display:flex; gap:5px; flex-direction:column;">
                <select class="auth-input legal-select" onchange="updateCourtStage(${c.id}, this.value)">
                    <option value="Подготовка иска" ${c.stage==='Подготовка иска'?'selected':''}>Подготовка иска</option>
                    <option value="Подан иск" ${c.stage==='Подан иск'?'selected':''}>Подан иск</option>
                    <option value="Предварительное заседание" ${c.stage==='Предварительное заседание'?'selected':''}>Предварительное</option>
                    <option value="Основное заседание" ${c.stage==='Основное заседание'?'selected':''}>Основное заседание</option>
                    <option value="Вынесение решения" ${c.stage==='Вынесение решения'?'selected':''}>Вынесение решения</option>
                    <option value="Обжаловано" ${c.stage==='Обжаловано'?'selected':''}>Обжаловано</option>
                    <option value="Приостановлено" ${c.stage==='Приостановлено'?'selected':''}>Приостановлено</option>
                    <option value="Закрыто" ${c.stage==='Закрыто'?'selected':''}>Закрыто</option>
                </select>
                <input type="date" class="auth-input legal-select" title="Изменить дату заседания" value="${c.next_hearing || ''}" onchange="updateCourtHearing(${c.id}, this.value)">
            </td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
};

window.openCreateCourtModal = function() {
    const sel = document.getElementById('courtProj');
    sel.innerHTML = '<option value="" disabled selected>Выберите договор...</option>' + projectsDB.map(p => `<option value="${p.id}">${p.contract} (${p.client})</option>`).join('');
    document.getElementById('createCourtModal').style.display = 'flex';
};

window.submitNewCourt = async function() {
    const data = { number: document.getElementById('courtNum').value || 'Б/Н', court_name: document.getElementById('courtName').value || 'Не указан', plaintiff: document.getElementById('courtPlain').value || 'ООО КОРДА', defendant: document.getElementById('courtDef').value || 'Не указан', amount: parseFloat(document.getElementById('courtAmount').value) || 0, proj_id: parseInt(document.getElementById('courtProj').value) || 0, instance: document.getElementById('courtInst').value || 'Первая', next_hearing: document.getElementById('courtHearing').value || '', stage: 'Подготовка иска' };
    if(!data.proj_id) return customAlert("❌ Выберите связанный договор!");

    const res = await apiCall('/court_cases', 'POST', data);
    if(res && res.status === 'success') {
        document.getElementById('createCourtModal').style.display = 'none';
        await loadCourtCases(); renderCourts();
        if(typeof showToast === 'function') showToast("Судебные дела", "Дело успешно зарегистрировано");
        
        const p = projectsDB.find(x => x.id === data.proj_id);
        if (p) {
            if(!p.logs) p.logs = [];
            const now = new Date();
            p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: `⚖️ Зарегистрировано судебное дело №${data.number} (${data.instance}). Сумма иска: ${data.amount} руб.`});
            await apiCall(`/projects/${p.id}`, 'PUT', p);
        }
    } else {
        customAlert("❌ Ошибка при создании");
    }
};

window.updateCourtStage = async function(id, newStage) {
    const c = courtCasesDB.find(x => x.id === id);
    if(!c) return;
    c.stage = newStage;
    await apiCall(`/court_cases/${c.id}`, 'PUT', c);
    await loadCourtCases();
    renderCourts();
    if(typeof showToast === 'function') showToast("Судебные дела", `Стадия изменена на: ${newStage}`);
};

window.updateCourtHearing = async function(id, newDate) {
    const c = courtCasesDB.find(x => x.id === id);
    if(!c) return;
    c.next_hearing = newDate;
    await apiCall(`/court_cases/${c.id}`, 'PUT', c);
    await loadCourtCases();
    renderCourts();
    if(typeof showToast === 'function') showToast("Судебные дела", "Дата заседания обновлена");
};
