// Этот файл отвечает ТОЛЬКО за генерацию документов и шаблонов

async function generateContractDoc() {
    if (!currentProjectId) return;
    
    // Собираем свежие данные прямо с экрана
    const pName = (document.getElementById('projName').value || 'Не указано').trim();
    const pContract = (document.getElementById('projContract').value || 'БН').trim(); // Убираем слэш по умолчанию
    const pClient = (document.getElementById('projClient').value || 'Не указан').trim();
    const pBudget = document.getElementById('projBudget').value || '0';
    const pManager = document.getElementById('projManager').value || 'Не назначен';
    
    const today = new Date().toLocaleDateString('ru-RU');

    // Формируем строгий юридический текст
    const contractText = `
ДОГОВОР ПОСТАВКИ И ОКАЗАНИЯ УСЛУГ № ${pContract}

г. Санкт-Петербург                                                  «${today}»

Общество с ограниченной ответственностью «КОРДА», именуемое в дальнейшем «Исполнитель», в лице Генерального директора, действующего на основании Устава, с одной стороны, и 
${pClient}, именуемое(ый) в дальнейшем «Заказчик», с другой стороны, совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем:

1. ПРЕДМЕТ ДОГОВОРА
1.1. Исполнитель обязуется выполнить работы и осуществить поставку оборудования по объекту/проекту: «${pName}», а Заказчик обязуется принять результат работ и оплатить их в порядке и на условиях, предусмотренных настоящим Договором.
1.2. Качество поставляемой продукции и выполняемых работ должно соответствовать требованиям ГОСТ и ТУ, действующим на территории РФ.

2. СТОИМОСТЬ И ПОРЯДОК РАСЧЕТОВ
2.1. Общая стоимость работ и материалов по настоящему Договору составляет: ${pBudget} руб. (НДС не облагается / вкл. НДС).
2.2. Оплата производится безналичным путем на расчетный счет Исполнителя на основании выставленных счетов.

3. ОТВЕТСТВЕННОСТЬ СТОРОН И РАЗРЕШЕНИЕ СПОРОВ
3.1. За неисполнение или ненадлежащее исполнение обязательств Стороны несут ответственность в соответствии с законодательством РФ.
3.2. Все споры подлежат рассмотрению в Арбитражном суде г. Санкт-Петербурга и Ленинградской области.

4. АДРЕСА, РЕКВИЗИТЫ И ПОДПИСИ СТОРОН

ИСПОЛНИТЕЛЬ:                               ЗАКАЗЧИК:
ООО "КОРДА"                                ${pClient}
Ответственный менеджер: ${pManager}

_________________ /____________/           _________________ /____________/
      (подпись)         (ФИО)                    (подпись)         (ФИО)
    `;

    // ИСПРАВЛЕНИЕ: Очищаем имя файла от опасных символов (/, \, ?, *, :)
    let safeClient = pClient.replace(/[\/\s\?]/g, '_');
    let safeContract = pContract.replace(/[\/\s\?]/g, '-');
    const fileName = `Dogovor_${safeClient}_N${safeContract}.doc`;

    // Превращаем текст в полноценный Word документ
    const wordDocument = `<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
    <head><meta charset='utf-8'><title>Договор</title></head>
    <body style="font-family: 'Times New Roman'; font-size: 12pt;">${contractText.replace(/\n/g, '<br>')}</body></html>`;
    
    const blob = new Blob([wordDocument], { type: 'application/msword;charset=utf-8' });
    const file = new File([blob], fileName, { type: 'application/msword' });

    const formData = new FormData();
    formData.append("file", file);
    formData.append("user", currentUser.name);
    formData.append("doc_type", "Договор");
    formData.append("parent_file", "");

    const pFList = document.getElementById('projectFilesList');
    if(pFList) pFList.innerHTML += `<span id="genLoader" style="font-size:13px; color:var(--primary); font-weight: 700;">Подготавливаем договор...</span>`;

    const res = await apiCall(`/projects/${currentProjectId}/upload`, 'POST', formData);
    
    // Убираем надпись "Загрузка"
    const loader = document.getElementById('genLoader');
    if(loader) loader.remove();

    if(res && res.status === 'success') {
        const p = projectsDB.find(x => x.id === currentProjectId);
        if(!p.files) p.files = []; 
        p.files.push(res.file);
        
        if(!p.logs) p.logs = [];
        const now = new Date();
        const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
        p.logs.unshift({time: timeStr, user: currentUser.name, action: `Автоматически сгенерировал документ: ${fileName}`});
        
        await syncProject(p);
        renderFiles();
        showToast(p.name, "Договор сгенерирован", p.id);
    } else {
        customAlert("Ошибка при генерации файла. Проверьте, создана ли папка 'uploads' в папке с проектом.");
        renderFiles();
    }
}

window.request1CInvoice = async function() {
    if (!currentProjectId) return;
    const project = projectsDB.find(item => item.id === currentProjectId);
    if (!project) return;

    const confirmed = await customConfirm(`Запросить счёт из 1С для проекта «${project.name}»?`);
    if (!confirmed) return;

    showToast('1С:Бухгалтерия', 'Формирую счёт по проекту...');
    const response = await apiCall(`/projects/${currentProjectId}/1c_invoice`, 'POST');
    if (!response || response.error || response.status !== 'success') {
        return customAlert('Не удалось получить счёт из 1С. Попробуйте ещё раз.');
    }

    await loadProjects();
    renderFiles();
    if (typeof renderProjectSmartTools === 'function') renderProjectSmartTools();
    showToast('1С:Бухгалтерия', 'Счёт добавлен в файлы проекта');
};

// ==========================================
// СВЯЗАННЫЕ ДОКУМЕНТЫ (ДЕРЕВО 1С)
// ==========================================

function getTreeIconSvg() {
    return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"></path><path d="M7 8h10"></path><path d="M5 14h6"></path><path d="M13 14h6"></path><circle cx="7" cy="8" r="2"></circle><circle cx="17" cy="8" r="2"></circle><circle cx="5" cy="14" r="2"></circle><circle cx="19" cy="14" r="2"></circle></svg>`;
}

function getFileIconSvg() {
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;
}

window.generateNextDoc = async function(docType, parentName) {
    if (!currentProjectId) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p) return;
    
    const pName = p.name || 'Не указано';
    const pClient = p.client || 'Не указан';
    const pContract = p.contract || 'БН';
    
    let docText = '';
    let fileName = '';
    const today = new Date().toLocaleDateString('ru-RU');
    const safeClient = pClient.replace(/[\/\s\?]/g, '_');
    const safeContract = pContract.replace(/[\/\s\?]/g, '-');
    
    if (docType === 'Спецификация') {
        docText = `СПЕЦИФИКАЦИЯ №1\nк Договору ${pContract} от ${today}\n\nПроект: ${pName}\nЗаказчик: ${pClient}\n\n1. Наименование работ/услуг: согласно ТЗ\n2. Стоимость: ${p.budget || 0} руб.\n\nПОДПИСИ СТОРОН:\nИсполнитель: _______ / Заказчик: _______`;
        fileName = `Specifikaciya_${safeClient}_N${safeContract}.doc`;
    } else if (docType === 'Счет на оплату') {
        docText = `СЧЕТ НА ОПЛАТУ № ${Math.floor(Math.random()*1000)}\nот ${today}\n\nПокупатель: ${pClient}\nОснование: Спецификация к договору ${pContract}\n\nСумма к оплате: ${p.budget || 0} руб.\n\nРуководитель: _______ / Бухгалтер: _______`;
        fileName = `Schet_${safeClient}_N${safeContract}.doc`;
    } else if (docType === 'УПД / Акт') {
        docText = `УНИВЕРСАЛЬНЫЙ ПЕРЕДАТОЧНЫЙ ДОКУМЕНТ (АКТ)\nот ${today}\n\nПокупатель: ${pClient}\nОснование: Договор ${pContract}\n\nРаботы выполнены в полном объеме, претензий нет.\n\nСдал: _______ / Принял: _______`;
        fileName = `UPD_${safeClient}_N${safeContract}.doc`;
    }
    
    const wordDocument = `<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
    <head><meta charset='utf-8'><title>${docType}</title></head>
    <body style="font-family: 'Times New Roman'; font-size: 12pt;">${docText.replace(/\n/g, '<br>')}</body></html>`;
    
    const blob = new Blob([wordDocument], { type: 'application/msword;charset=utf-8' });
    const file = new File([blob], fileName, { type: 'application/msword' });

    const formData = new FormData();
    formData.append("file", file);
    formData.append("user", currentUser.name);
    formData.append("doc_type", docType);
    formData.append("parent_file", parentName);

    const c = document.getElementById('treeHtmlContainer');
    if(c) c.innerHTML += '<div style="color:var(--primary); font-size:12px; font-weight:700; margin-top:12px;">Подготавливаем документ...</div>';

    const res = await apiCall(`/projects/${currentProjectId}/upload`, 'POST', formData);
    if(res && res.status === 'success') {
        if(!p.files) p.files = []; 
        p.files.push(res.file);
        
        if(!p.logs) p.logs = [];
        const now = new Date();
        const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
        p.logs.unshift({time: timeStr, user: currentUser.name, action: `Автоматически сгенерировал связанный документ: ${fileName}`});
        
        await syncProject(p);
        if (typeof renderFiles === 'function') renderFiles();
        showDocumentTree();
        showToast(p.name, `${docType} сгенерирован(а)`, p.id);
    } else {
        customAlert("Ошибка генерации документа.");
    }
};

window.showDocumentTree = function() {
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p || !p.files || p.files.length === 0) {
        return customAlert("В проекте пока нет загруженных файлов для построения дерева.");
    }
    
    let html = '<div style="text-align:left; font-size: 14px; background: linear-gradient(180deg, rgba(246,250,255,0.96), rgba(240,246,255,0.92)); padding: 18px; border-radius: 18px; border: 1px solid rgba(31, 79, 209, 0.08);">';
    
    const files = p.files;
    const tree = {};
    const roots = [];
    
    files.forEach(f => { tree[f.name] = []; });
    files.forEach(f => {
        if (f.parent && tree[f.parent]) tree[f.parent].push(f);
        else roots.push(f);
    });
    
    function renderNode(node, level) {
        const isDocType = !!node.doc_type;
        const indent = '<span style="display:inline-block; width:' + (level * 25) + 'px;"></span>';
        const prefix = level > 0 ? '└─' : '';
        let badge = isDocType ? `<span class="tree-badge">${node.doc_type}</span>` : '';
        
        let res = `<div class="tree-node">
            ${indent}
            <div class="tree-link-row">
                ${prefix ? `<span style="color: var(--secondary); font-weight: 700;">${prefix}</span>` : ''}
                <span class="tree-icon">${getFileIconSvg()}</span>
                <a href="${node.url}" target="_blank" class="tree-link">${node.name}</a>
            </div>
            ${badge}
        </div>`;
        
        if (tree[node.name]) {
            tree[node.name].forEach(child => {
                res += renderNode(child, level + 1);
            });
        }
        
        // Логика связи: Договор -> Спецификация -> Счет на оплату -> УПД / Акт
        let nextType = '';
        if (node.doc_type === 'Договор') nextType = 'Спецификация';
        else if (node.doc_type === 'Спецификация') nextType = 'Счет на оплату';
        else if (node.doc_type === 'Счет на оплату') nextType = 'УПД / Акт';
        
        if (nextType) {
            res += `<div class="tree-actions">
                ${indent}<span style="display:inline-block; width:25px;"></span>
                <button class="tree-btn" onclick="generateNextDoc('${nextType}', '${node.name}')">Создать на основании: ${nextType}</button>
            </div>`;
        }
        
        return res;
    }
    
    roots.forEach(r => { html += renderNode(r, 0); });
    html += '</div>';
    
    let modal = document.getElementById('treeModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'treeModal';
        modal.className = 'tree-modal-overlay';
        
        const content = document.createElement('div');
        content.className = 'tree-modal-content';
        
        content.innerHTML = `
            <div class="tree-modal-header">
                <div>
                    <h3 class="tree-modal-title">${getTreeIconSvg()} Дерево документов</h3>
                    <p class="tree-modal-subtitle">Связи между договором, спецификацией, счетом и закрывающими документами.</p>
                </div>
            </div>
            <div id="treeHtmlContainer"></div>
            <button class="btn-secondary" style="margin-top:20px; width:100%;" onclick="document.getElementById('treeModal').style.display='none'">Закрыть</button>
        `;
        modal.appendChild(content); document.body.appendChild(modal);
    }
    
    document.getElementById('treeHtmlContainer').innerHTML = html;
    modal.style.display = 'flex';
};

// Безопасное внедрение кнопки Дерева в UI проекта, не ломая остальную разметку
document.addEventListener('DOMContentLoaded', () => {
    setInterval(() => {
        const list = document.getElementById('projectFilesList');
        if (list && !document.getElementById('btnShowTree')) {
            const btn = document.createElement('button');
            btn.id = 'btnShowTree';
            btn.className = 'btn-show-tree fade-in';
            btn.innerHTML = `${getTreeIconSvg()} Показать дерево документов`;
            btn.onclick = showDocumentTree;
            list.parentNode.insertBefore(btn, list);
        }
    }, 1000);
});
