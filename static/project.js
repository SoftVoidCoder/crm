function createNewProject() { 
    const sel = document.getElementById('newProjClient');
    if(sel) sel.innerHTML = '<option value="">Свободный ввод или выберите из базы</option>' + clientsDB.map(c => `<option value="${c.name}">${c.name} (ИНН: ${c.inn})</option>`).join('');
    
    const tDiv = document.getElementById('newProjTeam');
    if(tDiv) {
        tDiv.innerHTML = allUsersDB.filter(u => u.role !== 'Директор').map(u => 
            `<label style="display:flex; gap:8px; align-items:center; margin-bottom:6px; cursor:pointer;"><input type="checkbox" value="${u.name}" class="team-cb-new"> <b>${u.name}</b> <span style="color:var(--secondary)">(${u.role})</span></label>`
        ).join('');
    }
    
    const nextNumber = projectsDB.length + 1;
    const currentYear = new Date().getFullYear();
    const formattedNumber = String(nextNumber).padStart(3, '0');
    const autoContractNum = `${currentYear}-КРД-${formattedNumber}`;
    
    const contractInput = document.getElementById('newProjContract');
    if (contractInput) contractInput.value = autoContractNum;
    
    const nameInput = document.getElementById('newProjName'); if (nameInput) nameInput.value = '';
    const managerInput = document.getElementById('newProjManager'); if (managerInput) managerInput.value = '';
    const budgetInput = document.getElementById('newProjBudget'); if (budgetInput) budgetInput.value = '';

    ProjectRolesManager.renderSelector('newProjRoles', []);

    const modal = document.getElementById('createProjectModal'); if(modal) modal.style.display = 'flex'; 
}

function closeCreateModal() { const modal = document.getElementById('createProjectModal'); if(modal) modal.style.display = 'none'; }

async function submitNewProject() {
    const nIn = document.getElementById('newProjName'); const name = nIn ? nIn.value.trim() : ''; if (!name) return;
    const cIn = document.getElementById('newProjClient'); const client = cIn ? cIn.value : '';
    const conIn = document.getElementById('newProjContract'); const contract = conIn ? conIn.value.trim() : 'ТБД';
    const mIn = document.getElementById('newProjManager'); const manager = mIn ? mIn.value.trim() : '';
    
    const teamCbs = document.querySelectorAll('.team-cb-new:checked');
    const team = Array.from(teamCbs).map(cb => cb.value);
    
    const budgetInput = document.getElementById('newProjBudget'); const budget = budgetInput ? parseFloat(budgetInput.value) || 0 : 0;
    
    const isEmptyChecked = document.getElementById('isEmptyChecklist').checked;
    let dynamicChecklist = [];
    
    if (!isEmptyChecked) {
        dynamicChecklist = JSON.parse(JSON.stringify(checklistTemplate));
        if (budget >= 3000000) {
            dynamicChecklist.splice(3, 0, {
                title: "3.1. [АВТО] Фин. контроль крупной сделки",
                responsibles: "Директор, Бухгалтерия",
                tasks: [
                    "Смета и маржинальность сделки свыше 3 млн руб. проверена и утверждена Директором.",
                    "Проведена расширенная проверка надежности контрагента."
                ]
            });
        }
    } else {
        dynamicChecklist = [];
    }

    const allowed_roles = ProjectRolesManager.getSelected('newProjRoles');

    await apiCall('/projects', 'POST', { 
        name: name, 
        contract: contract, 
        client: client, 
        manager: manager, 
        budget: budget, 
        team: team, 
        checklist: dynamicChecklist, 
        allowed_roles: allowed_roles 
    });
    
    closeCreateModal(); await loadProjects(); renderDashboard();
    showToast("Успех", "Проект успешно создан");
}

function applyChatVisibility() {
    const grid = document.getElementById('projectGrid');
    const btn = document.getElementById('btnToggleChat');
    if (!grid || !btn) return;
    if (isChatVisible) { grid.classList.remove('chat-hidden'); btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg> Скрыть чат'; } 
    else { grid.classList.add('chat-hidden'); btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg> Показать чат'; }
}

function toggleChat() {
    isChatVisible = !isChatVisible;
    localStorage.setItem('korda_chat_visible', isChatVisible);
    applyChatVisibility();
}

function openProject(id) {
    currentProjectId = id; const p = projectsDB.find(x => x.id === id);
    if (!p) return;

    ['dashboardView', 'analyticsView', 'adminView', 'clientsView', 'profileView', 'emailsView', 'meetingsView', 'messengerView', 'documentsView'].forEach(v => { const e = document.getElementById(v); if(e) e.style.display = 'none'; });
    
    const pView = document.getElementById('projectView'); if(pView) pView.style.display = 'block';
    document.querySelectorAll('.nav-item, .dept-item').forEach(el => el.classList.remove('active'));
    
    const pName = document.getElementById('projName'); if(pName) pName.value = p.name;
    const pContract = document.getElementById('projContract'); if(pContract) pContract.value = p.contract;
    const pClient = document.getElementById('projClient'); if(pClient) pClient.value = p.client;
    const pManager = document.getElementById('projManager'); if(pManager) pManager.value = p.manager;
    const pBudget = document.getElementById('projBudget'); if(pBudget) pBudget.value = p.budget || 0;
    
    // ИНЖЕКЦИЯ ПОЛЕЙ РЕЕСТРА ДОГОВОРОВ (ЕСЛИ ИХ ЕЩЕ НЕТ)
    const contractBlock = document.getElementById('projContract')?.parentElement;
    if (contractBlock && !document.getElementById('extendedContractDetails')) {
        const extHtml = `
            <div id="extendedContractDetails" style="margin-top:20px; padding:20px; background:var(--bg); border:1px solid var(--border); border-radius:10px; box-shadow: 0 2px 8px rgba(0,0,0,0.02);">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:15px; font-weight:600; font-size:14px; color:var(--text);">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                    Свойства и реквизиты договора
                </div>
                
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:15px; margin-bottom:20px;">
                    <div>
                        <label style="font-size:12px; font-weight:500; color:var(--secondary); display:block; margin-bottom:6px;">Доп. номер</label>
                        <input type="text" id="projContractAdd" class="auth-input" placeholder="Например, к ДС №1" style="margin:0; width:100%; box-sizing:border-box;">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:500; color:var(--secondary); display:block; margin-bottom:6px;">Входящий № (Заказчика)</label>
                        <input type="text" id="projContractInc" class="auth-input" placeholder="№ по учету контрагента" style="margin:0; width:100%; box-sizing:border-box;">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:500; color:var(--secondary); display:block; margin-bottom:6px;">Валюта договора</label>
                        <select id="projCurrency" class="auth-input" style="margin:0; width:100%; box-sizing:border-box;">
                            <option value="RUB">RUB (₽) - Рубль</option>
                            <option value="USD">USD ($) - Доллар США</option>
                            <option value="EUR">EUR (€) - Евро</option>
                            <option value="CNY">CNY (¥) - Юань</option>
                        </select>
                    </div>
                </div>

                <div style="border-top:1px solid var(--border); padding-top:15px; margin-top:10px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <div style="font-weight:600; font-size:13px; color:var(--text);">Пользовательские поля (Кастомные)</div>
                        <button class="btn-primary" style="padding:6px 12px; font-size:11px; border-radius:6px; display:flex; align-items:center; gap:4px;" onclick="addCustomField()">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                            Добавить поле
                        </button>
                    </div>
                    <div id="customFieldsContainer" style="display:flex; flex-direction:column; gap:8px;"></div>
                </div>
            </div>
        `;
        contractBlock.insertAdjacentHTML('afterend', extHtml);
    }

    const meta = p.archive_details?.contract_meta || {};
    if(document.getElementById('projContractAdd')) document.getElementById('projContractAdd').value = meta.add_num || '';
    if(document.getElementById('projContractInc')) document.getElementById('projContractInc').value = meta.inc_num || '';
    if(document.getElementById('projCurrency')) document.getElementById('projCurrency').value = meta.currency || 'RUB';
    window.currentCustomFields = meta.custom_fields || [];
    if(typeof renderCustomFields === 'function') renderCustomFields();
    
    const arcF = document.getElementById('arcFolder'); if(arcF) arcF.value = p.archive_details?.folder || '';
    const arcR = document.getElementById('arcRack'); if(arcR) arcR.value = p.archive_details?.rack || '';
    const arcD = document.getElementById('arcDate'); if(arcD) { if(arcD._flatpickr) arcD._flatpickr.setDate(p.archive_details?.date || ''); else arcD.value = p.archive_details?.date || ''; }
    
    const tDiv = document.getElementById('projTeam');
    if(tDiv) {
        tDiv.innerHTML = allUsersDB.filter(u => u.role !== 'Директор').map(u => {
            const isChecked = p.team && p.team.includes(u.name) ? 'checked' : '';
            return `<label style="display:flex; gap:8px; align-items:center; margin-bottom:6px; cursor:pointer;"><input type="checkbox" value="${u.name}" class="team-cb-edit" ${isChecked}> <b>${u.name}</b> <span style="color:var(--secondary)">(${u.role})</span></label>`;
        }).join('');
    }
    
    ProjectRolesManager.renderSelector('editProjRoles', p.allowed_roles || []);

    document.querySelectorAll('.finance-block').forEach(el => el.style.display = ['Директор', 'Бухгалтерия', 'Менеджер'].includes(currentUser.role) ? 'flex' : 'none');
    
    // ИНЖЕКЦИЯ КНОПОК СТАТУСОВ ДОГОВОРА
    const btnContainer = document.getElementById('projectToolbarStatusActions');
    if (btnContainer && !document.getElementById('btnProlong')) {
        btnContainer.innerHTML = `
            <button id="btnProlong" class="btn-secondary btn-prolong" onclick="prolongProject()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                Перевести на пролонгацию
            </button>
            <button id="btnTerminate" class="btn-danger btn-terminate" onclick="terminateProject()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>
                Расторгнуть договор
            </button>
        `;
    }
    
    const bCancel = document.getElementById('btnCancel'); if(bCancel) bCancel.style.display = p.status === 'active' ? 'block' : 'none';
    const bRestore = document.getElementById('btnRestore'); if(bRestore) bRestore.style.display = (p.status === 'canceled' || p.status === 'archive' || p.status === 'terminated') ? 'block' : 'none';
    const bProlong = document.getElementById('btnProlong'); if(bProlong) bProlong.style.display = p.status === 'active' ? 'block' : 'none';
    const bTerminate = document.getElementById('btnTerminate'); if(bTerminate) bTerminate.style.display = (p.status === 'active' || p.status === 'prolongation') ? 'block' : 'none';
    const bLogs = document.getElementById('btnLogs'); if(bLogs) bLogs.style.display = currentUser.role === 'Директор' ? 'block' : 'none';
    
    applyChatVisibility();
    const cList = document.getElementById('checklist'); if(cList) cList.innerHTML = ''; 
    renderChecklist(); 
    renderChat(); 
    renderFiles();

    if (typeof renderProjectNomenclature === 'function') renderProjectNomenclature();
    calcMargin();
}

function calcMargin() {
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p) return;
    
    const bEl = document.getElementById('projBudget');
    const b = bEl ? (parseFloat(bEl.value) || 0) : 0;
    
    // 1. Считаем трудозатраты (по таймерам чек-листа)
    let laborCosts = 0;
    if (p.time_logs) {
        p.time_logs.forEach(l => {
            const u = allUsersDB.find(x => x.name === l.user);
            const rate = u && u.hourly_rate ? u.hourly_rate : 500;
            laborCosts += (l.seconds / 3600) * rate;
        });
    }
    const laborEl = document.getElementById('projLaborCosts');
    if (laborEl) laborEl.innerText = `${Math.round(laborCosts).toLocaleString('ru-RU')} ₽`;

    // 2. Считаем стоимость материалов (из НСИ)
    let materialCosts = 0;
    if (p.nomenclature && p.nomenclature.length > 0) {
        p.nomenclature.forEach(n => {
            materialCosts += (n.price * n.qty);
        });
    }
    const matEl = document.getElementById('projMaterialCosts');
    if (matEl) matEl.innerText = `${Math.round(materialCosts).toLocaleString('ru-RU')} ₽`;

    // 3. Общая себестоимость = Материалы + Работа
    const totalCosts = materialCosts + laborCosts;
    
    const cEl = document.getElementById('projCosts'); 
    if (cEl) {
        cEl.value = Math.round(totalCosts);
        cEl.readOnly = true; 
    }
    
    // 4. Расчет чистой маржи
    const mEl = document.getElementById('projMargin'); 
    if(mEl) {
        const pureMargin = b - totalCosts;
        mEl.innerText = `${pureMargin.toLocaleString('ru-RU')} ₽ (${b>0 ? Math.round((pureMargin/b)*100) : 0}%)`;
        mEl.style.color = pureMargin >= 0 ? "var(--success)" : "var(--danger)";
    }
}

function appendLog(action) {
    const p = projectsDB.find(x => x.id === currentProjectId);
    if(!p.logs) p.logs = [];
    const now = new Date();
    p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: action});
}

function openLogsModal() {
    const p = projectsDB.find(x => x.id === currentProjectId);
    const l = document.getElementById('logsList'); if(!l) return;
    l.innerHTML = '';
    if(!p.logs || p.logs.length === 0) { l.innerHTML = "<p>История пуста</p>"; }
    else { p.logs.forEach(lg => l.innerHTML += `<div class="log-item"><div class="log-meta"><span>${lg.time}</span><span>👤 ${lg.user}</span></div><div class="log-action">${lg.action}</div></div>`); }
    const m = document.getElementById('logsModal'); if(m) m.style.display = 'flex';
}

async function saveProjectInfo() {
    const p = projectsDB.find(x => x.id === currentProjectId);
    const pName = document.getElementById('projName'); if(pName) p.name = pName.value;
    const pContract = document.getElementById('projContract'); if(pContract) p.contract = pContract.value;
    const pManager = document.getElementById('projManager'); if(pManager) p.manager = pManager.value;
    const pClient = document.getElementById('projClient'); if(pClient) p.client = pClient.value;
    
    if (!p.archive_details) p.archive_details = {};
    if (!p.archive_details.contract_meta) p.archive_details.contract_meta = {};
    const cAdd = document.getElementById('projContractAdd'); if(cAdd) p.archive_details.contract_meta.add_num = cAdd.value;
    const cInc = document.getElementById('projContractInc'); if(cInc) p.archive_details.contract_meta.inc_num = cInc.value;
    const cCur = document.getElementById('projCurrency'); if(cCur) p.archive_details.contract_meta.currency = cCur.value;
    p.archive_details.contract_meta.custom_fields = window.currentCustomFields || [];
    
    const teamCbs = document.querySelectorAll('.team-cb-edit:checked');
    const newTeam = Array.from(teamCbs).map(cb => cb.value);
    if(JSON.stringify(p.team || []) !== JSON.stringify(newTeam)) { appendLog(`Изменил состав Рабочей группы (приватность)`); p.team = newTeam; }
    
    const newRoles = ProjectRolesManager.getSelected('editProjRoles');
    if(JSON.stringify(p.allowed_roles || []) !== JSON.stringify(newRoles)) { 
        appendLog(`Изменил доступы по ролям`); 
        p.allowed_roles = newRoles; 
    }
    
    const pBudget = document.getElementById('projBudget');
    const newB = pBudget ? (parseFloat(pBudget.value) || 0) : 0;
    if(p.budget !== newB) appendLog(`Изменил сумму договора: с ${p.budget} на ${newB}`);
    p.budget = newB;
    
    const pCosts = document.getElementById('projCosts'); 
    p.costs = pCosts ? (parseFloat(pCosts.value) || 0) : 0; 
    
    await syncProject(p); 
    showToast("Система", "Данные проекта успешно сохранены");
}

async function cancelProject() { 
    if(await customConfirm("Отменить проект?")) { 
        const p = projectsDB.find(x => x.id === currentProjectId); 
        p.status = 'canceled'; appendLog("Отменил сделку"); 
        await syncProject(p); navigateTo('dashboard'); 
    } 
}
async function restoreProject() { 
    if(await customConfirm("Вернуть в работу?")) { 
        const p = projectsDB.find(x => x.id === currentProjectId); 
        p.status = 'active'; appendLog("Восстановил из отмененных/архива"); 
        await syncProject(p); navigateTo('dashboard'); 
    } 
}
async function syncProject(p) { await apiCall(`/projects/${p.id}`, 'PUT', p); }

// === ФУНКЦИИ РЕЕСТРА ДОГОВОРОВ ===
window.addCustomField = async function() {
    const name = await customPrompt("Название поля (например, 'Регион'):");
    if (!name) return;
    const val = await customPrompt(`Значение для поля '${name}':`);
    if (!val) return;
    window.currentCustomFields.push({name, value: val});
    renderCustomFields();
};

window.renderCustomFields = function() {
    const c = document.getElementById('customFieldsContainer');
    if(!c) return;
    
    if (window.currentCustomFields.length === 0) {
        c.innerHTML = '<div style="text-align:center; padding:15px; font-size:12px; color:var(--secondary); background:rgba(0,0,0,0.02); border-radius:8px; border:1px dashed var(--border);">Нет дополнительных полей. Нажмите «Добавить поле», чтобы создать кастомный реквизит.</div>';
        return;
    }

    c.innerHTML = window.currentCustomFields.map((cf, i) => `
        <div style="display:flex; gap:10px; align-items:center; background:var(--card-bg); padding:10px; border-radius:8px; border:1px solid var(--border);">
            <div style="flex:1;">
                <label style="font-size:10px; color:var(--secondary); display:block; margin-bottom:4px;">Название поля</label>
                <input type="text" class="auth-input" value="${cf.name}" onchange="currentCustomFields[${i}].name=this.value" style="margin:0; width:100%; box-sizing:border-box; font-size:13px; padding:6px 10px;" placeholder="Например, 'Регион'">
            </div>
            <div style="flex:2;">
                <label style="font-size:10px; color:var(--secondary); display:block; margin-bottom:4px;">Значение</label>
                <input type="text" class="auth-input" value="${cf.value}" onchange="currentCustomFields[${i}].value=this.value" style="margin:0; width:100%; box-sizing:border-box; font-size:13px; padding:6px 10px;" placeholder="Ввод значения...">
            </div>
            <div style="padding-top:18px;">
                <button class="btn-danger" style="padding:8px; border-radius:6px; background:rgba(239,68,68,0.1); color:var(--danger); border:none;" onclick="currentCustomFields.splice(${i},1); renderCustomFields();" title="Удалить поле">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </button>
            </div>
        </div>
    `).join('');
};

window.prolongProject = async function() {
    const newDate = await customPrompt("Введите новую дату окончания (ДД.ММ.ГГГГ):");
    if (!newDate) return;
    const reason = await customPrompt("Основание для пролонгации (например, 'Доп. соглашение №2'):");
    const p = projectsDB.find(x => x.id === currentProjectId);
    p.status = 'prolongation';
    if (!p.archive_details) p.archive_details = {};
    p.archive_details.prolongation = { date: newDate, reason: reason || 'Не указано' };
    appendLog(`Перевел договор на пролонгацию. Новая дата: ${newDate}. Основание: ${reason}`);
    await syncProject(p); navigateTo('dashboard');
};

window.terminateProject = async function() {
    const reason = await customPrompt("Укажите причину расторжения (например, 'Неисполнение обязательств'):");
    if (!reason) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    p.status = 'terminated';
    if (!p.archive_details) p.archive_details = {};
    p.archive_details.termination_reason = reason;
    appendLog(`Расторг договор. Причина: ${reason}`);
    await syncProject(p); navigateTo('dashboard');
};

async function archiveCurrentProject() { 
    const arcFolder = document.getElementById('arcFolder').value;
    const arcRack = document.getElementById('arcRack').value;
    const arcDate = document.getElementById('arcDate').value;

    if (!arcFolder || !arcRack || !arcDate) {
        await customAlert('⚠️ Для закрытия сделки необходимо заполнить номер папки, стеллаж и дату передачи оригинала в Архив!');
        return;
    }

    const hasReconciliation = await customConfirm("Подписан ли двусторонний Акт сверки взаиморасчетов (без расхождений)?\nЭто обязательное условие для закрытия договора.");
    if (!hasReconciliation) {
        await customAlert('⚠️ Получите и прикрепите Акт сверки перед закрытием!');
        return;
    }

    const p = projectsDB.find(x => x.id === currentProjectId); 
    p.status = 'archive'; 
    if(!p.archive_details) p.archive_details = {};
    p.archive_details.folder = arcFolder; p.archive_details.rack = arcRack; p.archive_details.date = arcDate;
    
    appendLog(`Передал оригинал в Архив. Стеллаж: ${arcRack}, Папка: ${arcFolder}, Дата: ${arcDate}. Акт сверки подтвержден.`); 
    await syncProject(p); 
    navigateTo('dashboard'); 
}

function renderChat() {
    const p = projectsDB.find(x => x.id === currentProjectId); const c = document.getElementById('chatMessages'); if(!c) return;
    if (!p.chat) p.chat = [];
    
    // Формируем общую ленту
    let feedItems = [];
    
    // Добавляем чат
    p.chat.forEach(m => feedItems.push({ type: 'chat', timeStr: m.time, data: m }));
    
    // Добавляем официальные документы канцелярии (связанные с проектом)
    if (typeof documentsDB !== 'undefined') {
        const linkedDocs = documentsDB.filter(d => d.project_id === currentProjectId && d.status !== 'draft');
        linkedDocs.forEach(d => feedItems.push({ type: 'doc', timeStr: (d.d_date || '') + ' 12:00', data: d }));
    }
    
    // Сортируем ленту хронологически
    feedItems.sort((a,b) => {
        const parseT = (ts) => { try { const [d, t] = ts.split(' '); const [day, mo, yr] = d.split('.'); const [hr, min] = (t||'00:00').split(':'); return new Date(yr, mo-1, day, hr, min).getTime(); } catch(e) { return 0; } };
        return parseT(a.timeStr) - parseT(b.timeStr);
    });

    let h = ''; if (feedItems.length === 0) h = `<div style="text-align:center; color:var(--secondary); margin-top:50px; font-size:13px;">Лента пуста. Напишите первым!</div>`;
    else feedItems.forEach(item => { 
        if (item.type === 'chat') {
            const m = item.data;
            const isMy = m.user === currentUser.name; 
            let roleColorClass = '';
            switch(m.role) { case 'Директор': roleColorClass = 'role-director'; break; case 'Конструкторское бюро': roleColorClass = 'role-kb'; break; case 'Производство и ОТК': roleColorClass = 'role-prod'; break; case 'Менеджер': roleColorClass = 'role-manager'; break; case 'Бухгалтерия': roleColorClass = 'role-buh'; break; case 'Юрист': roleColorClass = 'role-law'; break; default: roleColorClass = ''; }
            h += `<div class="chat-msg ${isMy ? 'my-msg' : ''}"><div class="chat-msg-meta"><span class="role-name ${roleColorClass}">${m.user} (${m.role})</span><span>${m.time}</span></div><div class="chat-msg-bubble">${m.text}</div></div>`; 
        } else if (item.type === 'doc') {
            const d = item.data;
            let tName = d.type === 'incoming' ? '📥 Входящее' : d.type === 'outgoing' ? '📤 Исходящее' : '📄 Внутренний акт';
            h += `<div class="chat-msg" style="align-self: center; width: 95%; max-width: 400px; margin-top: 10px; margin-bottom: 10px;"><div class="chat-msg-meta" style="justify-content: center; color: var(--primary);"><b>Официальный документооборот</b></div><div class="chat-msg-bubble" style="background: var(--card-bg); border: 1px solid var(--primary); color: var(--text); border-radius: 8px;"><b>${tName} №${d.number}</b> от ${d.d_date}<br><span style="font-size:11px; color:var(--secondary); display:block; margin-top:4px;">${d.subject}</span><button class="btn-secondary" onclick="openPrintDoc(${d.id})" style="width:100%; margin-top:8px; font-size:11px; padding:6px; min-height:unset;">Открыть карточку</button></div></div>`;
        }
    });
    
    c.innerHTML = h; c.scrollTop = c.scrollHeight;
}

async function sendChatMessage() {
    const i = document.getElementById('chatInput'); if(!i) return;
    const t = i.value.trim(); if (!t) return;
    const p = projectsDB.find(x => x.id === currentProjectId); if (!p.chat) p.chat = [];
    const now = new Date(); p.chat.push({ user: currentUser.name, role: currentUser.role, text: t, time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}` });
    i.value = ''; renderChat(); await syncProject(p);
}

function renderFiles() {
    const p = projectsDB.find(x => x.id === currentProjectId);
    const c = document.getElementById('projectFilesList'); if(!c) return;
    c.innerHTML = '';
    
    if(!p.files || p.files.length === 0) { c.innerHTML = '<span style="font-size:13px; color:var(--secondary);">Нет прикрепленных документов</span>'; return; }
    
    const grouped = {};
    p.files.forEach(f => {
        const bName = f.base_name || f.name;
        if (!grouped[bName]) grouped[bName] = [];
        grouped[bName].push(f);
    });
    
    Object.keys(grouped).forEach(bName => {
        const versions = grouped[bName].sort((a,b) => (a.version||1) - (b.version||1));
        const latest = versions[versions.length - 1];
        
        const safeName = latest.name.replace(/'/g, "\\'");
        const safeBase = bName.replace(/'/g, "\\'");
        const isLocked = !!latest.lockedBy; 
        const lockedByMe = latest.lockedBy === currentUser.name;
        const canEdit = !isLocked || lockedByMe || currentUser.role === 'Директор';

        let lockHtml = ''; 
        if (isLocked) {
            lockHtml = `<span style="font-size: 10px; background: rgba(239, 68, 68, 0.1); color: var(--danger); padding: 2px 6px; border-radius: 4px; margin-left: 8px; font-weight: 700; display:inline-flex; align-items:center; gap:4px;">🔒 Занят: ${latest.lockedBy}</span>`;
        }
        
        let lockBtn = ''; 
        if (!isLocked) { 
            lockBtn = `<button class="btn-secondary" style="padding: 4px 8px; font-size: 10px; background: var(--card-bg); min-height:unset;" onclick="toggleLock('${safeBase}')">🔒 Захватить</button>`; 
        } else if (lockedByMe || currentUser.role === 'Директор') { 
            lockBtn = `<button class="btn-success" style="padding: 4px 8px; font-size: 10px; min-height:unset;" onclick="toggleLock('${safeBase}')">🔓 Освободить</button>`; 
        }
        
        let deleteBtn = canEdit ? `<button class="file-delete-btn" onclick="deleteFile('${safeName}')" title="Удалить последнюю версию"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>` : '';
        
        let historyBtn = versions.length > 1 ? `<button class="btn-secondary" style="padding: 4px 8px; font-size: 10px; min-height:unset;" onclick="openFileHistory('${safeBase}')">История (${versions.length})</button>` : '';

        const lockedStyle = (isLocked && !lockedByMe) ? 'opacity: 0.6; background: rgba(15, 23, 42, 0.03);' : '';

        c.innerHTML += `
        <div class="file-item" style="display: flex; justify-content: space-between; align-items: center; width: 100%; box-sizing: border-box; ${lockedStyle}">
            <a href="${latest.url}" target="_blank" style="display: flex; align-items: center; gap: 8px; text-decoration: none; color: inherit; flex: 1; overflow: hidden;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${isLocked ? 'var(--danger)' : 'var(--primary)'}" stroke-width="1.5" flex-shrink="0"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg> 
                <span style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${latest.name}</span>
                <span style="background: var(--primary); color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 5px;">v.${latest.version || 1}</span>
                ${lockHtml}
            </a>
            <div style="display: flex; align-items: center; gap: 12px; flex-shrink: 0;">
                <span style="font-size: 11px; color: var(--secondary);">${latest.time} | ${latest.user}</span>
                ${historyBtn}${lockBtn}${deleteBtn}
            </div>
        </div>`;
    });
}

function openFileHistory(baseName) {
    const p = projectsDB.find(x => x.id === currentProjectId);
    const versions = p.files.filter(f => (f.base_name || f.name) === baseName).sort((a,b) => (b.version||1) - (a.version||1));
    const list = document.getElementById('fileHistoryList');
    if (!list) return;
    list.innerHTML = versions.map(v => `
        <div style="display: flex; justify-content: space-between; padding: 12px; border-bottom: 1px solid var(--border); background: var(--bg); border-radius: 8px; margin-bottom: 8px;">
            <div>
                <a href="${v.url}" target="_blank" style="color: var(--primary); font-weight: bold; text-decoration: none;">${v.name}</a>
                <div style="font-size: 11px; color: var(--secondary); margin-top: 4px; font-weight: bold;">Версия: v.${v.version || 1}</div>
            </div>
            <div style="text-align: right; font-size: 11px; color: var(--secondary);">
                <div>${v.time}</div>
                <div style="margin-top: 4px;">Загрузил: <span style="color: var(--text);">${v.user}</span></div>
            </div>
        </div>
    `).join('');
    document.getElementById('fileHistoryModal').style.display = 'flex';
}

async function toggleLock(baseName) {
    const p = projectsDB.find(x => x.id === currentProjectId); 
    const versions = p.files.filter(f => (f.base_name || f.name) === baseName).sort((a,b) => (a.version||1) - (b.version||1));
    if (versions.length === 0) return;
    const file = versions[versions.length - 1];

    if (file.lockedBy) {
        if (file.lockedBy !== currentUser.name && currentUser.role !== 'Директор') { 
            await customAlert(`❌ Файл занят пользователем ${file.lockedBy}. Только он или Директор могут его освободить.`); 
            return; 
        }
        file.lockedBy = null; 
        appendLog(`Освободил файл из режима редактирования: ${file.base_name || file.name}`);
    } else { 
        file.lockedBy = currentUser.name; 
        appendLog(`Захватил файл для редактирования: ${file.base_name || file.name}`); 
    }
    await syncProject(p); 
    renderFiles();
}

async function uploadFile(e) {
    const file = e.target.files[0]; if(!file) return;
    const formData = new FormData(); formData.append("file", file); formData.append("user", currentUser.name);
    const pFList = document.getElementById('projectFilesList'); 
    if(pFList) pFList.innerHTML = `<span style="font-size:13px; color:var(--secondary);">Загрузка...</span>` + pFList.innerHTML;
    
    const res = await apiCall(`/projects/${currentProjectId}/upload`, 'POST', formData);
    if(res && res.status === 'success') { 
        await loadProjects(); renderFiles(); e.target.value = ''; 
    } else if (res && res.detail) {
        await customAlert(`❌ Ошибка: ${res.detail}`);
        renderFiles(); e.target.value = '';
    } else {
        await customAlert("❌ Произошла ошибка при загрузке файла");
        renderFiles(); e.target.value = '';
    }
}

async function deleteFile(fileName) {
    const p = projectsDB.find(x => x.id === currentProjectId); 
    const file = p.files.find(f => f.name === fileName);
    
    if (file && file.lockedBy && file.lockedBy !== currentUser.name && currentUser.role !== 'Директор') { 
        await customAlert(`❌ Нельзя удалить файл. Он занят пользователем: ${file.lockedBy}`); 
        return; 
    }
    
    if(!(await customConfirm(`Вы точно хотите удалить последнюю версию файла "${fileName}"?`))) return;
    
    const fileIndex = p.files.findIndex(f => f.name === fileName);
    if(fileIndex > -1) { 
        p.files.splice(fileIndex, 1); 
        appendLog(`Удалил версию файла: ${fileName}`); 
        await syncProject(p); renderFiles(); 
        showToast("Файлы", "Версия файла удалена"); 
    }
}

// === ФУНКЦИИ НОМЕНКЛАТУРЫ ===

function openAddNomToProjectModal() {
    const sel = document.getElementById('projNomSelect');
    const unitDisp = document.getElementById('projNomUnitDisplay');
    
    if (typeof nomenclatureDB === 'undefined' || nomenclatureDB.length === 0) {
        customAlert("Справочник номенклатуры пуст. Добавьте продукцию в разделе НСИ.");
        return;
    }
    
    sel.innerHTML = '<option value="" disabled selected>Выберите позицию</option>' + 
        nomenclatureDB.map(n => `<option value="${n.article}" data-price="${n.price}" data-unit="${n.unit}">${n.name} (Арт: ${n.article}) - ${n.price} ₽</option>`).join('');
    
    sel.onchange = function() {
        const selectedOption = this.options[this.selectedIndex];
        unitDisp.value = selectedOption.getAttribute('data-unit') || 'шт';
    };
    
    document.getElementById('projNomQty').value = '';
    unitDisp.value = '';
    document.getElementById('addNomToProjectModal').style.display = 'flex';
}

async function confirmAddNomToProject() {
    const sel = document.getElementById('projNomSelect');
    const qty = parseFloat(document.getElementById('projNomQty').value);
    
    if (sel.selectedIndex <= 0 || !qty || qty <= 0) {
        return await customAlert("Выберите позицию и укажите количество больше нуля.");
    }
    
    const opt = sel.options[sel.selectedIndex];
    const item = {
        name: opt.text.split(' (Арт:')[0].trim(),
        article: opt.value,
        price: parseFloat(opt.getAttribute('data-price')),
        unit: opt.getAttribute('data-unit'),
        qty: qty
    };
    
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p.nomenclature) p.nomenclature = [];
    p.nomenclature.push(item);
    
    appendLog(`Добавил в спецификацию: ${item.name} (${qty} ${item.unit})`);
    await syncProject(p);
    
    document.getElementById('addNomToProjectModal').style.display = 'none';
    renderProjectNomenclature(); 
    calcMargin(); 
    showToast("Спецификация", "Позиция добавлена");
}

async function removeNomFromProject(index) {
    if (!(await customConfirm("Удалить позицию из спецификации? Это изменит себестоимость проекта."))) return;
    
    const p = projectsDB.find(x => x.id === currentProjectId);
    const removedItem = p.nomenclature[index];
    p.nomenclature.splice(index, 1);
    
    appendLog(`Удалил из спецификации: ${removedItem.name}`);
    await syncProject(p);
    
    renderProjectNomenclature();
    calcMargin();
}

function renderProjectNomenclature() {
    const p = projectsDB.find(x => x.id === currentProjectId);
    const container = document.getElementById('projNomenclatureTable');
    if (!container) return;
    
    if (!p.nomenclature || p.nomenclature.length === 0) {
        container.innerHTML = '<div style="color:var(--secondary); text-align:center; padding: 10px;">Спецификация пуста</div>';
        return;
    }
    
    let html = `<table class="admin-table" style="margin-top: 10px; width: 100%;">
                    <thead><tr><th>Наименование</th><th>Арт.</th><th>Кол-во</th><th>Сумма</th><th class="no-print" style="width:40px;"></th></tr></thead><tbody>`;
    
    p.nomenclature.forEach((n, idx) => {
        const sum = n.price * n.qty;
        html += `<tr>
                    <td>${n.name}</td>
                    <td>${n.article}</td>
                    <td><b>${n.qty}</b> <span style="color:var(--secondary); font-size:11px;">${n.unit}</span></td>
                    <td>${sum.toLocaleString('ru-RU')} ₽</td>
                    <td class="no-print" style="text-align:right;">
                        <button class="btn-danger" style="padding:4px 8px; font-size:10px; border-radius:6px;" onclick="removeNomFromProject(${idx})">✕</button>
                    </td>
                 </tr>`;
    });
    html += `</tbody></table>`;
    container.innerHTML = html;
}
