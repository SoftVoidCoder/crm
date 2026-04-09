// ==========================================
// 4. СОГЛАСОВАНИЯ (БИЗНЕС-ПРОЦЕССЫ)
// ==========================================

let currentApprTab = 'pending';

function switchApprTab(tab) {
    currentApprTab = tab;
    document.getElementById('tabApprPending').classList.toggle('active', tab === 'pending');
    document.getElementById('tabApprCompleted').classList.toggle('active', tab === 'completed');
    renderApprovals();
}

// ФУНКЦИЯ ДЛЯ ОТКРЫТИЯ ПРОЕКТА ПО КЛИКУ ИЗ СОГЛАСОВАНИЙ
async function openProjectFromLink(link) {
    // Ищем проект по ID, номеру договора или названию
    const p = projectsDB.find(x => String(x.id) === String(link) || x.contract === link || x.name === link);
    
    if (p) {
        currentProjectId = p.id;
        
        // Переключаем экран на карточку проекта
        if (typeof navigateTo === 'function') navigateTo('project');
        
        // Заполняем данные карточки
        document.getElementById('projName').value = p.name || '';
        document.getElementById('projContract').value = p.contract || '';
        document.getElementById('projClient').value = p.client || '';
        document.getElementById('projManager').value = p.manager || '';
        if(document.getElementById('projBudget')) document.getElementById('projBudget').value = p.budget || 0;
        if(document.getElementById('projCosts')) document.getElementById('projCosts').value = p.costs || 0;
        
        // Обновляем все внутренние блоки (чек-лист, файлы, чат)
        if (typeof calcMargin === 'function') calcMargin();
        if (typeof updateChecklistUI === 'function') updateChecklistUI();
        if (typeof renderChat === 'function') renderChat();
        if (typeof renderFiles === 'function') renderFiles();
    } else {
        // ЗАМЕНА: customAlert вместо alert
        await customAlert("Проект с таким номером не найден в базе.\nВозможно, он был удален или у вас нет к нему доступа.");
    }
}

function renderApprovals() {
    const container = document.getElementById('approvalsListContainer'); 
    if (!container) return;
    
    const filt = approvalsDB.filter(a => {
        if (currentApprTab === 'pending') return a.status === 'pending';
        return a.status === 'completed' || a.status === 'rejected';
    });

    if (filt.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding:30px; color:var(--secondary);">Нет запущенных процессов.</div>`;
        return;
    }

    container.innerHTML = filt.map(a => {
        let routeHtml = '';
        
        // Логика 1С: Поддержка параллельных маршрутов и проверка текущего этапа
        const stepStr = a.route[a.current_step] || '';
        const stepUsers = stepStr.split(' и ').map(u => u.trim());
        // Проверяем, голосовал ли я уже именно на ЭТОМ этапе
        const iAlreadyApproved = a.history.some(h => h.startsWith(`✅ ${currentUser.name}`) && h.includes(`(Этап ${a.current_step + 1})`));
        const amI_Current = (a.status === 'pending' && stepUsers.includes(currentUser.name) && !iAlreadyApproved);
        
        a.route.forEach((person, idx) => {
            let cls = 'approval-step';
            if (idx < a.current_step) cls += ' done';
            else if (idx === a.current_step && a.status === 'pending') cls += ' active';
            else if (idx === a.current_step && a.status === 'rejected') cls += ' rejected';
            
            routeHtml += `<div class="${cls}">${person}</div>`;
            if (idx < a.route.length - 1) routeHtml += `<div class="approval-arrow">→</div>`;
        });

        let actionBtns = '';
        if (amI_Current || currentUser.role === 'Директор') {
            actionBtns = `
            <div style="display:flex; gap:8px; margin-top: 15px;">
                <button class="btn-success" onclick="processApprovalStep(${a.id}, 'approve')">✅ Согласовать</button>
                <button class="btn-danger" onclick="processApprovalStep(${a.id}, 'reject')">❌ Отклонить</button>
            </div>`;
        }
        
        let histHtml = '';
        if (a.history.length > 0) {
            histHtml = `<div style="margin-top:12px; font-size:11px; color:var(--secondary); background:var(--bg); padding:8px; border-radius:8px;">` 
                       + a.history.map(h => `<div>${h}</div>`).join('') + 
                       `</div>`;
        }

        return `
        <div class="approval-card">
            <div style="font-weight:600; font-size:16px;">${a.title}</div>
            <div style="font-size:12px; color:var(--secondary); margin-top:4px;">
                Документ: <span onclick="openProjectFromLink('${a.item_link}')" style="color:var(--primary); cursor:pointer; text-decoration:underline;">${a.item_link}</span> | Автор: ${a.author}
            </div>
            <div class="approval-route">${routeHtml}</div>
            ${histHtml}
            ${a.status === 'pending' ? actionBtns : ''}
        </div>`;
    }).join('');
}

let smartRouteData = [];

function openCreateApprovalModal() {
    smartRouteData = [];
    renderSmartRoute();
    document.getElementById('createApprovalModal').style.display = 'flex';
}

window.addSmartRouteStep = async function() {
    const type = await customPrompt("Тип этапа: 1 - Последовательный, 2 - Параллельный (одновременно)", "1");
    if(!type) return;
    
    let opts = allUsersDB.filter(u => u.status === 'approved').map((u, i) => `${i+1} - ${u.name}`).join('\n');
    const userIdx = await customPrompt(`Введите номер сотрудника:\n${opts}`);
    const userObj = allUsersDB.filter(u => u.status === 'approved')[parseInt(userIdx)-1];
    if(!userObj) return;

    if (type === "2" && smartRouteData.length > 0) {
        smartRouteData[smartRouteData.length - 1] += ` и ${userObj.name}`; // Объединяем в параллельный узел
    } else {
        smartRouteData.push(userObj.name); // Последовательный узел
    }
    renderSmartRoute();
};

window.autoGenerateRoute = async function() {
    const pId = await customPrompt("Умная маршрутизация 1С.\nВведите ID договора (сделки) для проверки суммы бюджета:");
    if (!pId) return;
    const p = projectsDB.find(x => x.id === parseInt(pId));
    if (!p) return customAlert("Проект с таким ID не найден.");
    
    smartRouteData = [];
    smartRouteData.push("Юрист");
    smartRouteData.push("Бухгалтерия");
    
    if (p.budget >= 3000000) {
        smartRouteData.push("Директор");
        showToast("Маршрутизация", `Бюджет ${p.budget.toLocaleString('ru-RU')} ₽. Автоматически добавлен Директор!`);
    } else {
        showToast("Маршрутизация", "Сформирован стандартный маршрут.");
    }
    renderSmartRoute();
};

function renderSmartRoute() {
    const c = document.getElementById('smartRouteContainer');
    if(smartRouteData.length === 0) { c.innerHTML = '<div style="text-align: center; color: var(--secondary); font-size: 12px; font-style: italic;">Маршрут пока пуст...</div>'; return; }
    
    c.innerHTML = smartRouteData.map((step, idx) => `
        <div style="display:flex; align-items:center; gap:10px; background:var(--card-bg); padding:8px 12px; border-radius:8px; border:1px solid var(--border);">
            <span style="background:var(--primary); color:white; width:20px; height:20px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:10px; font-weight:bold;">${idx+1}</span>
            <span style="flex:1; font-size:13px; font-weight:600;">${step.includes(' и ') ? '🔄 Параллельно: ' + step : '👤 ' + step}</span>
            <button class="btn-danger" style="padding:4px 8px; font-size:10px; min-height:unset;" onclick="smartRouteData.splice(${idx},1); renderSmartRoute()">✕</button>
        </div>
    `).join('');
}

async function submitApproval() {
    const title = document.getElementById('apprTitle').value;
    const link = document.getElementById('apprLink').value;
    
    if (!title || smartRouteData.length === 0) {
        return await customAlert("Заполните название и выберите маршрут");
    }
    
    await apiCall('/approvals', 'POST', { 
        title: title, 
        item_link: link, 
        route: smartRouteData, 
        author: currentUser.name 
    });
    
    document.getElementById('createApprovalModal').style.display = 'none';
    await loadApprovals(); 
    renderApprovals();
    showToast("Согласования", "Процесс успешно запущен");
}

async function processApprovalStep(id, action) {
    const a = approvalsDB.find(x => x.id === id);
    const now = new Date(); 
    const tStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
    
    if (action === 'approve') {
        // Записываем номер этапа в историю, чтобы избежать ложных срабатываний дублирующихся сотрудников
        a.history.push(`✅ ${currentUser.name} согласовал(а) (Этап ${a.current_step + 1}) (${tStr})`);
        
        // Логика 1С: Ждем всех участников параллельного узла
        const stepUsers = a.route[a.current_step].split(' и ').map(u => u.trim());
        const approvedCount = stepUsers.filter(u => 
            a.history.some(h => h.startsWith(`✅ ${u}`) && h.includes(`(Этап ${a.current_step + 1})`))
        ).length;

        if (approvedCount >= stepUsers.length) {
            a.current_step++;
            if (a.current_step >= a.route.length) a.status = 'completed';
        }
        showToast("Согласования", "Ваш голос учтен!");
    } else {
        // ЗАМЕНА: customPrompt вместо prompt
        const reason = await customPrompt("Причина отклонения:");
        a.history.push(`❌ ${currentUser.name} отклонил(а): ${reason || 'Без причины'} (${tStr})`);
        a.status = 'rejected';
        showToast("Внимание", "Документ отклонен", "error");
    }
    
    await apiCall(`/approvals/${a.id}`, 'PUT', a);
    await loadApprovals(); 
    renderApprovals();
}