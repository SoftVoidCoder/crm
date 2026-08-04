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
        const requiredRoles = Array.isArray(k.required_roles) ? k.required_roles : [];
        const readBy = Array.isArray(k.read_by) ? k.read_by : [];
        const isRequired = requiredRoles.includes(currentUser.role) || requiredRoles.includes('Все');
        const isRead = readBy.includes(currentUser.name);
        
        let badge = '';
        if (isRequired && !isRead) {
            badge = `<span style="background: var(--danger); color: white; padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: bold;">Требуется ознакомление</span>`;
        } else if (isRead) {
            badge = `<span style="background: rgba(16,185,129,0.1); color: var(--success); padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: bold;">Ознакомлен(а)</span>`;
        }
        
        const excerpt = String(k.content || '').replace(/\s+/g, ' ').trim().slice(0, 180);
        return `
        <article class="knowledge-card" tabindex="0" role="button" onclick="openKnowledgeDoc(${Number(k.id)})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openKnowledgeDoc(${Number(k.id)});}">
            <div class="knowledge-header">
                <b class="knowledge-title">${escapeHtml(k.title || 'Регламент')}</b> 
                ${badge}
            </div>
            <div class="knowledge-meta">Опубликовал: ${escapeHtml(k.author || 'Система')} · ${escapeHtml(k.created_at || '')}</div>
            <div class="knowledge-excerpt">${escapeHtml(excerpt || 'Откройте карточку, чтобы посмотреть содержание.')}</div>
            <div class="knowledge-actions">
                <button class="btn-secondary" type="button" onclick="event.stopPropagation(); openKnowledgeDoc(${Number(k.id)})">Открыть</button>
                <button class="btn-secondary" type="button" onclick="event.stopPropagation(); downloadKnowledgeDoc(${Number(k.id)})">Скачать текст</button>
            </div>
        </article>`;
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
    
    const requiredRoles = Array.isArray(k.required_roles) ? k.required_roles : [];
    const readBy = Array.isArray(k.read_by) ? k.read_by : [];
    const titleEl = document.getElementById('readKnowTitle');
    const metaEl = document.getElementById('readKnowMeta');
    const contentEl = document.getElementById('readKnowContent');
    if (titleEl) titleEl.innerText = k.title || 'Регламент';
    if (metaEl) metaEl.innerText = `Опубликовал: ${k.author || 'Система'} · Дата: ${k.created_at || 'не указана'}`;
    if (contentEl) contentEl.innerText = k.content || 'Содержимое документа пока не заполнено.';
    
    const btnRead = document.getElementById('btnMarkRead');
    const isRequired = requiredRoles.includes(currentUser.role) || requiredRoles.includes('Все');
    const isRead = readBy.includes(currentUser.name);
    
    if (btnRead && isRequired && !isRead) {
        btnRead.style.display = 'flex';
    } else if (btnRead) {
        btnRead.style.display = 'none';
    }
    
    const statsDiv = document.getElementById('readKnowStats');
    const usersEl = document.getElementById('readKnowUsers');
    if (statsDiv && currentUser.role === 'Директор') {
        statsDiv.style.display = 'block';
        if (usersEl) usersEl.innerText = readBy.length > 0 ? readBy.join(', ') : 'Никто не ознакомился';
    } else if (statsDiv) {
        statsDiv.style.display = 'none';
    }
    
    const modal = document.getElementById('readKnowledgeModal');
    if (modal) modal.style.display = 'flex';
}

async function markKnowledgeRead() {
    if (!currentKnowledgeId) return;
    await apiCall(`/knowledge/${currentKnowledgeId}/read`, 'POST', { user: currentUser.name });
    document.getElementById('readKnowledgeModal').style.display = 'none';
    await loadKnowledge(); 
    renderKnowledge();
}

function downloadKnowledgeDoc(id = currentKnowledgeId) {
    const k = knowledgeDB.find(x => Number(x.id) === Number(id));
    if (!k) return customAlert('Документ базы знаний не найден.');
    const safeTitle = String(k.title || `knowledge-${k.id || 'document'}`).replace(/[\\/:*?"<>|]+/g, '-').slice(0, 80);
    const text = [
        k.title || 'Регламент',
        '',
        `Опубликовал: ${k.author || 'Система'}`,
        `Дата: ${k.created_at || 'не указана'}`,
        '',
        k.content || '',
    ].join('\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${safeTitle}.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}
