// ==========================================
// 3. КАНЦЕЛЯРИЯ (ДОКУМЕНТЫ)
// ==========================================

let currentDocTab = 'incoming';

function switchDocTab(tab) {
    currentDocTab = tab;
    document.getElementById('tabDocIncoming').classList.toggle('active', tab === 'incoming');
    document.getElementById('tabDocOutgoing').classList.toggle('active', tab === 'outgoing');
    document.getElementById('tabDocInternal').classList.toggle('active', tab === 'internal');
    renderDocuments();
}

function renderDocuments() {
    const container = document.getElementById('documentsListTable'); 
    if (!container) return;
    
    // Получаем текст из поиска
    const sInput = document.getElementById('searchInput');
    const q = sInput ? sInput.value.toLowerCase().trim() : '';
    
    // Фильтруем документы
    const filt = documentsDB.filter(d => {
        // Проверяем, в нужной ли мы вкладке
        const matchesTab = currentDocTab === 'drafts' ? d.status === 'draft' : (d.type === currentDocTab && d.status !== 'draft');
        if (!matchesTab) return false;
        
        // Если поиск пустой — показываем все
        if (!q) return true;

        // Бронебойный поиск
        const num = String(d.number || '').toLowerCase();
        const corr = String(d.correspondent || '').toLowerCase();
        const subj = String(d.subject || '').toLowerCase();
        
        return num.includes(q) || corr.includes(q) || subj.includes(q);
    });
    
    filt.sort((a,b) => (b.priority === 'high' ? 1 : 0) - (a.priority === 'high' ? 1 : 0));

    if (filt.length === 0) { 
        container.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--secondary); padding: 30px;">По вашему запросу ничего не найдено.</td></tr>`; 
        return; 
    }
    
    container.innerHTML = filt.map(d => {
        let statusBadge = '';
        if (d.status === 'registered') statusBadge = '<span class="status-badge" style="background: rgba(16, 185, 129, 0.1); color: var(--success);">Зарегистрирован</span>';
        else if (d.status === 'draft') statusBadge = '<span class="status-badge" style="background: var(--bg); color: var(--secondary);">Черновик</span>';
        else statusBadge = '<span class="status-badge" style="background: var(--bg); color: var(--secondary);">В архиве</span>';
            
        // Кнопка файла
        let fileLink = d.file_url 
            ? `<a href="${d.file_url}" target="_blank" style="color:var(--primary); font-weight:600; text-decoration:none; display:flex; align-items:center; font-size:11px; padding:4px 8px; border:1px solid var(--border); border-radius:8px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>Открыть</a>` 
            : `<button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="uploadDocFile(${d.id})">📎 Прикрепить</button>`;
            
        // ВОТ ОНА, ВЕРНУЛАСЬ: Кнопка QR
        let printBtn = `<button class="btn-secondary" style="padding: 4px 8px; font-size: 11px; min-height:unset;" onclick="openPrintDoc(${d.id})">🖨️ Карточка с QR</button>`;
        
        // Кнопки CRUD
        let editBtn = `<button class="btn-secondary" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="editDocument(${d.id})">✏️ Изменить</button>`;
        let delBtn = `<button class="btn-danger" style="padding:4px 8px; font-size:11px; min-height:unset;" onclick="deleteDocument(${d.id})">🗑️ Удалить</button>`;
        
        let prioBadge = d.priority === 'high' ? `🔥 ` : '';
        
        let subTypeLabel = '';
        if (d.type === 'internal_order') subTypeLabel = '<br><span style="font-size:10px; color:var(--primary);">Приказ</span>';
        if (d.type === 'internal_memo') subTypeLabel = '<br><span style="font-size:10px; color:var(--secondary);">Служ. записка</span>';
        if (d.type === 'internal_reg') subTypeLabel = '<br><span style="font-size:10px; color:var(--primary);">Регламент</span>';
            
        return `
        <tr>
            <td style="font-weight:600;">${d.number}${subTypeLabel}</td>
            <td>${d.d_date}</td>
            <td>${d.correspondent || '-'}</td>
            <td><b style="color:${d.priority==='high'?'var(--danger)':'inherit'}">${prioBadge}${d.subject}</b></td>
            <td>${statusBadge}</td>
            <td><div style="display:flex; gap:5px; flex-wrap:wrap; align-items:center;">${fileLink} ${printBtn} ${editBtn} ${delBtn}</div></td>
        </tr>`;
    }).join('');
}

async function submitDocument() {
    const type = document.getElementById('docType').value; 
    const number = document.getElementById('docNumber').value; 
    const dDate = document.getElementById('docDate').value; 
    const corr = document.getElementById('docCorrespondent').value; 
    const subj = document.getElementById('docSubject').value;
    
    if (!number || !subj) return customAlert("Заполните Номер и Тему!");
    
    await apiCall('/documents', 'POST', { 
        type: type, 
        number: number, 
        d_date: dDate, 
        correspondent: corr, 
        subject: subj, 
        status: 'registered' 
    });
    
    document.getElementById('createDocModal').style.display = 'none'; 
    document.getElementById('docNumber').value = ''; 
    document.getElementById('docSubject').value = '';
    
    await loadDocuments(); 
    switchDocTab(type); 
}

async function uploadDocFile(id) {
    const input = document.createElement('input'); 
    input.type = 'file';
    input.onchange = async (e) => { 
        const file = e.target.files[0]; 
        if(!file) return; 
        const formData = new FormData(); 
        formData.append("file", file); 
        await apiCall(`/documents/${id}/upload`, 'POST', formData); 
        await loadDocuments(); 
        renderDocuments(); 
    }; 
    input.click();
}

async function editDocument(id) {
    const d = documentsDB.find(x => x.id === id);
    if (!d) return;
    
    const newSubj = await customPrompt("Изменить тему документа:", d.subject);
    if (newSubj === null) return; 
    
    const newCorr = await customPrompt("Изменить корреспондента:", d.correspondent || '');
    if (newCorr === null) return;
    
    const isRegistered = await customConfirm("Этот документ активен? (Да - Зарегистрирован, Отмена - В архиве)");
    const newStatus = isRegistered ? 'registered' : 'archived';
    
    await apiCall(`/documents/${id}`, 'PUT', { 
        type: d.type, 
        number: d.number, 
        d_date: d.d_date, 
        correspondent: newCorr, 
        subject: newSubj, 
        status: newStatus 
    });
    
    await loadDocuments();
    renderDocuments();
}

async function deleteDocument(id) {
    if (!(await customConfirm("Вы уверены, что хотите БЕЗВОЗВРАТНО удалить этот документ?"))) return;
    await apiCall(`/documents/${id}`, 'DELETE');
    await loadDocuments();
    renderDocuments();
}