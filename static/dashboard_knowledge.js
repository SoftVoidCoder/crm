// ==========================================
// 9. БАЗА ЗНАНИЙ
// ==========================================

function renderKnowledge() {
    const container = document.getElementById('knowledgeListContainer'); 
    if (!container) return;
    
    const btnCreate = document.getElementById('btnCreateKnowledge');
    if (btnCreate) btnCreate.style.display = currentUser.role === 'Директор' ? 'block' : 'none';
    
    if (knowledgeDB.length === 0) {
        container.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:30px; color:var(--secondary);">Нет опубликованных регламентов.</div>`;
        return;
    }
    
    container.innerHTML = knowledgeDB.map(k => {
        const isRequired = k.required_roles.includes(currentUser.role) || k.required_roles.includes('Все');
        const isRead = k.read_by.includes(currentUser.name);
        
        let badge = '';
        if (isRequired && !isRead) {
            badge = `<span style="background: var(--danger); color: white; padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: bold;">Требуется ознакомление</span>`;
        } else if (isRead) {
            badge = `<span style="background: rgba(16,185,129,0.1); color: var(--success); padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: bold;">Ознакомлен(а)</span>`;
        }
        
        return `
        <div style="background:var(--card-bg); border:1px solid var(--border); padding:20px; border-radius:16px; cursor:pointer; transition:all 0.2s;" onclick="openKnowledgeDoc(${k.id})" onmouseover="this.style.borderColor='var(--primary)'" onmouseout="this.style.borderColor='var(--border)'">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <b style="font-size:16px;">${k.title}</b> 
                ${badge}
            </div>
            <div style="font-size:12px; color:var(--secondary); margin-top:8px;">Опубликовал: ${k.author} | ${k.created_at}</div>
        </div>`;
    }).join('');
}

function openCreateKnowledgeModal() {
    const rDiv = document.getElementById('knowRoles');
    if (rDiv) {
        let html = `<label style="display:flex; align-items:center; gap:5px;"><input type="checkbox" class="know-role-cb" value="Все"> <b>Все сотрудники</b></label>`;
        availableRoles.forEach(r => {
            html += `<label style="display:flex; align-items:center; gap:5px;"><input type="checkbox" class="know-role-cb" value="${r}"> ${r}</label>`;
        });
        rDiv.innerHTML = html;
    }
    document.getElementById('createKnowledgeModal').style.display = 'flex';
}

async function submitKnowledge() {
    const title = document.getElementById('knowTitle').value;
    const content = document.getElementById('knowContent').value;
    const cbs = document.querySelectorAll('.know-role-cb:checked');
    const roles = Array.from(cbs).map(cb => cb.value);
    
    if (!title || !content) return customAlert("Заполните Название и Текст документа");
    if (roles.length === 0) return customAlert("Выберите, для кого обязателен регламент");
    
    await apiCall('/knowledge', 'POST', { title: title, content: content, author: currentUser.name, required_roles: roles });
    document.getElementById('createKnowledgeModal').style.display = 'none';
    
    document.getElementById('knowTitle').value = ''; 
    document.getElementById('knowContent').value = '';
    
    await loadKnowledge(); 
    renderKnowledge();
}

let currentKnowledgeId = null;

function openKnowledgeDoc(id) {
    currentKnowledgeId = id;
    const k = knowledgeDB.find(x => x.id === id);
    if (!k) return;
    
    document.getElementById('readKnowTitle').innerText = k.title;
    document.getElementById('readKnowMeta').innerText = `Опубликовал: ${k.author} | Дата: ${k.created_at}`;
    document.getElementById('readKnowContent').innerText = k.content;
    
    const btnRead = document.getElementById('btnMarkRead');
    const isRequired = k.required_roles.includes(currentUser.role) || k.required_roles.includes('Все');
    const isRead = k.read_by.includes(currentUser.name);
    
    if (isRequired && !isRead) {
        btnRead.style.display = 'flex';
    } else {
        btnRead.style.display = 'none';
    }
    
    const statsDiv = document.getElementById('readKnowStats');
    if (currentUser.role === 'Директор') {
        statsDiv.style.display = 'block';
        document.getElementById('readKnowUsers').innerText = k.read_by.length > 0 ? k.read_by.join(', ') : 'Никто не ознакомился';
    } else {
        statsDiv.style.display = 'none';
    }
    
    document.getElementById('readKnowledgeModal').style.display = 'flex';
}

async function markKnowledgeRead() {
    if (!currentKnowledgeId) return;
    await apiCall(`/knowledge/${currentKnowledgeId}/read`, 'POST', { user: currentUser.name });
    document.getElementById('readKnowledgeModal').style.display = 'none';
    await loadKnowledge(); 
    renderKnowledge();
}