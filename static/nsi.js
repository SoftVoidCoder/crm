// ==========================================
// ЯДРО НСИ И СКЛАДА (Номенклатура и Контакты)
// ==========================================

let nomenclatureDB = [];
let contactsDB = [];
let selectedProjectNomenclature = [];

// Загрузка справочников из БД
async function loadNSI() {
    nomenclatureDB = await apiCall('/nomenclature') || [];
    contactsDB = await apiCall('/contacts') || [];
}

// Запускаем загрузку данных с задержкой
setTimeout(async () => { 
    if (currentUser && currentUser.status === 'approved') {
        await loadNSI();
        if(document.getElementById('nomenclatureView')?.style.display === 'block') renderNomenclature();
        if(document.getElementById('contactsView')?.style.display === 'block') renderContacts();
    }
}, 1500);

// --- СКЛАД: ДОБАВЛЕНИЕ НОВОЙ ПОЗИЦИИ ---
async function addNomenclature() {
    const name = document.getElementById('addNomName').value.trim();
    const article = document.getElementById('addNomArticle').value.trim();
    const unit = document.getElementById('addNomUnit').value.trim();
    const price = parseFloat(document.getElementById('addNomPrice').value) || 0;
    const currency = document.getElementById('addNomCurrency') ? document.getElementById('addNomCurrency').value : 'RUB';

    if (!name) return customAlert("Введите наименование продукции!");

    await apiCall('/nomenclature', 'POST', { name, article, unit, price, stock: 0, currency });
    document.getElementById('addNomName').value = '';
    document.getElementById('addNomArticle').value = '';
    document.getElementById('addNomPrice').value = '0';
    
    await loadNSI();
    renderNomenclature();
    showToast("Склад", "Новая позиция добавлена в номенклатуру");
}

// --- СКЛАД: ОТРИСОВКА ОСТАТКОВ ---
window.renderNomenclature = function() {
    const tbody = document.getElementById('nomenclatureListTable');
    if (!tbody) return;
    
    if (!nomenclatureDB || nomenclatureDB.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px; color: var(--secondary);">Справочник пуст. Добавьте продукцию выше.</td></tr>';
        return;
    }
    
    tbody.innerHTML = nomenclatureDB.map(n => {
        const curSym = { RUB: '₽', USD: '$', EUR: '€', CNY: '¥' };
        const sym = curSym[n.currency || 'RUB'] || '₽';
        let priceHtml = `${n.price.toLocaleString('ru-RU')} ${sym}`;
        if (n.currency && n.currency !== 'RUB') {
            const rubEquivalent = n.price * (window.exchangeRates[n.currency] || 1);
            priceHtml += `<br><span style="font-size:10px; color:var(--secondary)">~ ${rubEquivalent.toLocaleString('ru-RU', {maximumFractionDigits:2})} ₽</span>`;
        }
        return `
        <tr>
            <td><b>${n.name}</b></td>
            <td>${n.article}</td>
            <td>${priceHtml}</td>
            <td><b style="color:var(--primary); font-size:16px;">${n.stock || 0}</b> <span style="font-size:11px;color:var(--secondary);">${n.unit}</span></td>
            <td style="text-align: right; display:flex; gap:6px; justify-content:flex-end;">
                <button class="btn-success" style="padding: 4px 8px; font-size: 11px;" onclick="moveStock('${n.article}', 'add')" title="Оприходовать товар">↓ Приход</button>
                <button class="btn-secondary" style="padding: 4px 8px; font-size: 11px;" onclick="moveStock('${n.article}', 'remove')" title="Списать товар">↑ Расход</button>
                <button class="btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="deleteNomenclature('${n.article}')" title="Удалить карточку товара">✕</button>
            </td>
        </tr>
        `;
    }).join('');
};

// --- СКЛАД: ОПРИХОДОВАНИЕ И СПИСАНИЕ ---
window.moveStock = async function(article, type) {
    const nom = nomenclatureDB.find(x => x.article === article);
    if (!nom) return;
    
    const actionName = type === 'add' ? 'Оприходование (Приход)' : 'Списание (Расход)';
    const qtyStr = await customPrompt(`${actionName}\nТовар: ${nom.name}\nУкажите количество:`, "1");
    if (!qtyStr) return;
    
    const qty = parseFloat(qtyStr);
    if (isNaN(qty) || qty <= 0) return customAlert("Введите корректное число больше нуля");

    if (type === 'remove' && (nom.stock || 0) < qty) {
        if (!(await customConfirm(`⚠️ На складе всего ${nom.stock || 0} ${nom.unit}.\nВы хотите списать ${qty} ${nom.unit} и уйти в минус?`))) return;
    }

    const res = await apiCall(`/nomenclature/${encodeURIComponent(article)}/movement`, 'POST', { qty: qty, type: type });
    if (res && res.status === 'success') {
        await loadNSI();
        renderNomenclature();
        showToast("Склад", "Остатки успешно обновлены");
    } else {
        customAlert("Ошибка при обновлении остатков");
    }
};

window.deleteNomenclature = async function(article) {
    if (!(await customConfirm(`Удалить позицию (Арт: ${article}) из базы?`))) return;
    
    const res = await apiCall(`/nomenclature/${encodeURIComponent(article)}`, 'DELETE');
    if (res && res.status === 'success') {
        await loadNSI(); 
        renderNomenclature(); 
        showToast("Успех", "Позиция удалена из справочника");
    } else {
        customAlert("Ошибка при удалении");
    }
};

// --- КОНТАКТЫ ---
async function addContact() {
    const name = document.getElementById('addContactName').value.trim();
    const clientId = parseInt(document.getElementById('addContactClient').value) || 0;
    const phone = document.getElementById('addContactPhone').value.trim();
    const email = document.getElementById('addContactEmail').value.trim();
    const position = document.getElementById('addContactPosition').value.trim();

    if (!name || !clientId) return customAlert("Введите ФИО и выберите Контрагента!");

    await apiCall('/contacts', 'POST', { client_id: clientId, name, phone, email, position });
    document.getElementById('addContactName').value = '';
    document.getElementById('addContactPhone').value = '';
    document.getElementById('addContactEmail').value = '';
    document.getElementById('addContactPosition').value = '';
    
    await loadNSI();
    renderContacts();
    showToast("НСИ", "Контакт успешно добавлен");
}

window.renderContacts = function() {
    const ccSel = document.getElementById('addContactClient');
    if (ccSel && typeof clientsDB !== 'undefined') {
        const currentVal = ccSel.value; 
        ccSel.innerHTML = '<option value="">Выберите контрагента</option>' + 
                          clientsDB.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
        ccSel.value = currentVal;
    }

    const tbody = document.getElementById('contactsListTable');
    if (!tbody) return;
    
    if (contactsDB.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px; color: var(--secondary);">Нет добавленных контактов.</td></tr>';
        return;
    }

    tbody.innerHTML = contactsDB.map(c => {
        const clientObj = clientsDB.find(x => x.id === c.client_id);
        const cName = clientObj ? clientObj.name : 'Неизвестно';
        return `<tr><td><b>${c.name}</b></td><td><span class="status-badge" style="background:var(--bg);">${cName}</span></td><td>${c.position}</td><td>${c.phone}</td><td>${c.email}</td></tr>`;
    }).join('');
};

// ==========================================
// ИНТЕГРАЦИЯ НСИ В СОЗДАНИЕ ПРОЕКТА
// ==========================================

window.addNomToProjectList = function() {
    const input = document.getElementById('newProjNomInput');
    const qtyInp = document.getElementById('newProjNomQty');
    if (!input || !qtyInp) return;

    const name = input.value.trim();
    const qty = parseInt(qtyInp.value) || 1;

    if(!name) return;

    const nom = nomenclatureDB.find(n => n.name === name);
    
    // Предупреждаем менеджера, если товара не хватает на складе (но разрешаем добавить)
    if (nom && (nom.stock || 0) < qty) {
        showToast("Внимание", `Запрошено: ${qty}, На складе: ${nom.stock || 0}`, "error");
    }

    selectedProjectNomenclature.push({ 
        name: name, 
        qty: qty, 
        price: nom ? nom.price : 0, 
        unit: nom ? nom.unit : 'шт',
        article: nom ? nom.article : ''
    });
    
    input.value = ''; qtyInp.value = '';
    updateProjectNomList();
};

window.updateProjectNomList = function() {
    const list = document.getElementById('newProjNomList');
    if(!list) return;
    if(selectedProjectNomenclature.length === 0) {
        list.innerHTML = '<span style="color:var(--secondary);">Пока ничего не добавлено</span>';
        return;
    }
    list.innerHTML = selectedProjectNomenclature.map((item, index) =>
        `<div style="display:flex; justify-content:space-between; align-items:center; background:var(--bg); padding:8px 12px; border-radius:8px; margin-bottom:6px; border:1px solid var(--border);">
            <span><b>${item.name}</b> — ${item.qty} ${item.unit}</span>
            <span style="color:var(--danger); cursor:pointer; font-weight:bold; font-size: 16px;" onclick="selectedProjectNomenclature.splice(${index}, 1); updateProjectNomList();">×</span>
        </div>`
    ).join('');
};

window.createNewProject = function() { 
    const sel = document.getElementById('newProjClient');
    if(sel) {
        sel.innerHTML = '<option value="">Свободный ввод или выберите из базы</option>' + clientsDB.map(c => `<option value="${c.name}">${c.name} (ИНН: ${c.inn})</option>`).join('');
        
        sel.onchange = (e) => {
            const clientObj = clientsDB.find(x => x.name === e.target.value);
            const cSel = document.getElementById('newProjContact');
            if (clientObj) {
                const clientContacts = contactsDB.filter(x => x.client_id === clientObj.id);
                if(clientContacts.length > 0) {
                    cSel.style.display = 'block';
                    cSel.innerHTML = '<option value="">Выберите контактное лицо</option>' + clientContacts.map(c => `<option value="${c.name}">${c.name} (${c.position})</option>`).join('');
                } else {
                    cSel.style.display = 'none'; cSel.value = '';
                }
            } else {
                cSel.style.display = 'none'; cSel.value = '';
            }
        };
    }
    
    const tDiv = document.getElementById('newProjTeam');
    if(tDiv) {
        tDiv.innerHTML = allUsersDB.filter(u => u.role !== 'Директор').map(u => 
            `<label style="display:flex; gap:8px; align-items:center; margin-bottom:6px; cursor:pointer;"><input type="checkbox" value="${u.name}" class="team-cb-new"> <b>${u.name}</b> <span style="color:var(--secondary)">(${u.role})</span></label>`
        ).join('');
    }
    
    const nextNumber = projectsDB.length + 1;
    const currentYear = new Date().getFullYear();
    if (document.getElementById('newProjContract')) document.getElementById('newProjContract').value = `${currentYear}-КРД-${String(nextNumber).padStart(3, '0')}`;
    
    if (document.getElementById('newProjName')) document.getElementById('newProjName').value = '';
    if (document.getElementById('newProjManager')) document.getElementById('newProjManager').value = currentUser.name;
    if (document.getElementById('newProjBudget')) document.getElementById('newProjBudget').value = '';
    if (document.getElementById('newProjContact')) { document.getElementById('newProjContact').style.display = 'none'; document.getElementById('newProjContact').value = ''; }

    selectedProjectNomenclature = [];
    updateProjectNomList();
    
    // ДОБАВИЛИ ПОКАЗ ОСТАТКОВ ПРИ ВЫБОРЕ
    const dl = document.getElementById('nomDataList');
    if(dl) dl.innerHTML = nomenclatureDB.map(n => `<option value="${n.name}">Арт. ${n.article} | Склад: ${n.stock || 0} ${n.unit} | ${n.price} ₽</option>`).join('');

    if (window.ProjectRolesManager) window.ProjectRolesManager.renderSelector('newProjRoles');
    document.getElementById('createProjectModal').style.display = 'flex';
};

window.submitNewProject = async function() {
    const name = document.getElementById('newProjName').value.trim();
    if(!name) return customAlert("Введите наименование!");

    const contract = document.getElementById('newProjContract').value.trim();
    const client = document.getElementById('newProjClient').value;
    const manager = document.getElementById('newProjManager').value.trim();
    const budget = parseFloat(document.getElementById('newProjBudget').value) || 0;

    const team = Array.from(document.querySelectorAll('.team-cb-new:checked')).map(cb => cb.value);
    const roles = Array.from(document.querySelectorAll('.role-cb-newProjRoles:checked')).map(cb => cb.value);

    const contactSelect = document.getElementById('newProjContact');
    let finalClient = client;
    if (client && contactSelect && contactSelect.value) finalClient += ` (Контакт: ${contactSelect.value})`;

    const isEmptyChecked = document.getElementById('isEmptyChecklist') ? document.getElementById('isEmptyChecklist').checked : false;
    let dynamicChecklist = [];
    
    if (!isEmptyChecked && typeof checklistTemplate !== 'undefined') {
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
    }

    const req = {
        name: name,
        contract: contract,
        client: finalClient,
        manager: manager,
        budget: budget,
        costs: 0,
        team: team,
        checklist: dynamicChecklist,
        allowed_roles: roles,
        nomenclature: selectedProjectNomenclature
    };

    const res = await apiCall('/projects', 'POST', req);
    if(res && res.status === 'success') {
        document.getElementById('createProjectModal').style.display = 'none';
        await loadProjects();
        if(typeof renderDashboard === 'function') renderDashboard();
        showToast("Успех", "Проект успешно создан");
    } else {
        customAlert("Ошибка при создании");
    }
};