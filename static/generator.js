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
    if(pFList) pFList.innerHTML += `<span id="genLoader" style="font-size:13px; color:var(--primary); font-weight: bold;">🤖 Генерация договора...</span>`;

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
        p.logs.unshift({time: timeStr, user: currentUser.name, action: `🤖 Автоматически сгенерировал документ: ${fileName}`});
        
        await syncProject(p);
        renderFiles();
        showToast(p.name, "📄 Договор сгенерирован", p.id);
    } else {
        customAlert("❌ Ошибка при генерации файла. Проверьте, создана ли папка 'uploads' в папке с проектом.");
        renderFiles();
    }
}

// ==========================================
// СВЯЗАННЫЕ ДОКУМЕНТЫ (ДЕРЕВО 1С)
// ==========================================

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
    if(c) c.innerHTML += '<div style="color:var(--primary); font-size:12px; font-weight:bold; margin-top:10px;">🤖 Генерация документа...</div>';

    const res = await apiCall(`/projects/${currentProjectId}/upload`, 'POST', formData);
    if(res && res.status === 'success') {
        if(!p.files) p.files = []; 
        p.files.push(res.file);
        
        if(!p.logs) p.logs = [];
        const now = new Date();
        const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
        p.logs.unshift({time: timeStr, user: currentUser.name, action: `🤖 Автоматически сгенерировал связанный документ: ${fileName}`});
        
        await syncProject(p);
        if (typeof renderFiles === 'function') renderFiles();
        showDocumentTree();
        showToast(p.name, `📄 ${docType} сгенерирован(а)`, p.id);
    } else {
        customAlert("❌ Ошибка генерации документа.");
    }
};

window.showDocumentTree = function() {
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p || !p.files || p.files.length === 0) {
        return customAlert("В проекте пока нет загруженных файлов для построения дерева.");
    }
    
    let html = '<div style="text-align:left; font-size: 14px; background: var(--bg); padding: 15px; border-radius: 8px;">';
    
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
        const prefix = level > 0 ? '└─ ' : '📦 ';
        let badge = isDocType ? `<span style="background:var(--primary); color:white; padding:2px 6px; border-radius:4px; font-size:10px; margin-left:6px;">${node.doc_type}</span>` : '';
        
        let res = `<div style="padding: 6px 0; display:flex; align-items:center; border-bottom: 1px dashed var(--border);">
            ${indent}${prefix}
            <a href="${node.url}" target="_blank" style="color:var(--text); text-decoration:none; font-weight:500;">📄 ${node.name}</a> 
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
            res += `<div style="padding: 6px 0; background: rgba(0,0,0,0.02);">
                ${indent}<span style="display:inline-block; width:25px;"></span>└─ 
                <button class="btn-secondary" style="font-size:11px; padding:4px 8px; cursor:pointer; border: 1px dashed var(--secondary);" onclick="generateNextDoc('${nextType}', '${node.name}')">+ Создать на основании: ${nextType}</button>
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
        Object.assign(modal.style, { position:'fixed', top:'0', left:'0', width:'100%', height:'100%', backgroundColor:'rgba(0,0,0,0.6)', display:'flex', alignItems:'center', justifyContent:'center', zIndex:'9999' });
        
        const content = document.createElement('div');
        Object.assign(content.style, { backgroundColor:'var(--bg)', padding:'20px', borderRadius:'12px', minWidth:'550px', maxWidth:'90%', maxHeight:'85%', overflowY:'auto', boxShadow:'0 10px 25px rgba(0,0,0,0.2)' });
        
        content.innerHTML = '<h3 style="margin:0 0 15px 0; color:var(--text);">🌲 Дерево документов (Связи 1С)</h3><div id="treeHtmlContainer"></div><button class="btn-secondary" style="margin-top:20px; width:100%;" onclick="document.getElementById(\'treeModal\').style.display=\'none\'">Закрыть</button>';
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
            btn.className = 'btn-primary fade-in';
            Object.assign(btn.style, { width:'100%', marginBottom:'15px', padding:'10px', background:'var(--container)', color:'var(--primary)', border:'2px dashed var(--primary)', fontWeight:'bold' });
            btn.innerHTML = '🌲 Показать дерево документов (Связи 1С)';
            btn.onclick = showDocumentTree;
            list.parentNode.insertBefore(btn, list);
        }
    }, 1000);
});