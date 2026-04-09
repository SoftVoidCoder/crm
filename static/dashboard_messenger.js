// ==========================================
// 5. ГЛОБАЛЬНЫЙ МЕССЕНДЖЕР
// ==========================================

let globalChats = [];
let currentGlobalChatId = null;
let currentMessageCount = 0;

async function loadGlobalChats() { 
    const url = `/chats?user_name=${encodeURIComponent(currentUser.name)}&user_role=${encodeURIComponent(currentUser.role)}`; 
    const data = await apiCall(url); 
    if (data) { 
        globalChats = data; 
        renderGlobalChats(); 
    } 
}

function renderGlobalChats() {
    const container = document.getElementById('messengerChatsList'); 
    if (!container) return; 
    
    let html = '';
    const sysChats = globalChats.filter(c => c.type === 'system' || c.type === 'role');
    
    if (sysChats.length > 0) {
        html += '<div style="font-size:11px; color:var(--secondary); text-transform:uppercase; font-weight:bold; margin: 10px 0 5px 5px;">Системные чаты</div>';
        sysChats.forEach(c => {
            let icon = c.type === 'system' 
                ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect></svg>' 
                : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path></svg>';
            let activeCls = c.id === currentGlobalChatId ? 'active' : ''; 
            html += `<div class="chat-list-item ${activeCls}" onclick="openGlobalChat(${c.id})"><div class="chat-avatar">${icon}</div><div style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${c.name}</div></div>`;
        });
    }
    
    const customChats = globalChats.filter(c => c.type === 'custom');
    if (customChats.length > 0) {
        html += '<div style="font-size:11px; color:var(--secondary); text-transform:uppercase; font-weight:bold; margin: 15px 0 5px 5px;">Мои чаты</div>';
        customChats.forEach(c => {
            let icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>';
            let activeCls = c.id === currentGlobalChatId ? 'active' : ''; 
            html += `<div class="chat-list-item ${activeCls}" onclick="openGlobalChat(${c.id})"><div class="chat-avatar">${icon}</div><div style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${c.name}</div></div>`;
        });
    }
    container.innerHTML = html;
}

async function openGlobalChat(id) {
    currentGlobalChatId = id; 
    renderGlobalChats(); 
    const chat = globalChats.find(c => c.id === id); 
    if (!chat) return;
    
    document.getElementById('mChatTitle').innerText = chat.name; 
    document.getElementById('messengerInputArea').style.display = 'flex'; 
    document.getElementById('messengerMessages').innerHTML = '<div style="text-align:center; color:var(--secondary); margin-top:50px;">Загрузка сообщений...</div>';
    
    const btnDel = document.getElementById('btnDeleteChat'); 
    if (chat.type === 'custom' && (chat.creator === currentUser.name || currentUser.role === 'Директор')) { 
        btnDel.style.display = 'block'; 
    } else { 
        btnDel.style.display = 'none'; 
    }
    
    currentMessageCount = 0; 
    await loadGlobalMessages(id, true);
}

async function loadGlobalMessages(id, forceScroll = false) {
    const data = await apiCall(`/chats/${id}/messages`);
    if (data) { 
        if (data.length !== currentMessageCount || forceScroll) { 
            currentMessageCount = data.length; 
            renderGlobalMessages(data); 
            if (forceScroll) { 
                const box = document.getElementById('messengerMessages'); 
                box.scrollTop = box.scrollHeight; 
            } 
        } 
    }
}

function renderGlobalMessages(messages) {
    const c = document.getElementById('messengerMessages'); 
    if (!c) return;
    
    if (messages.length === 0) { 
        c.innerHTML = '<div style="text-align:center; color:var(--secondary); margin-top:50px;">Здесь пока нет сообщений. Напишите первым!</div>'; 
        return; 
    }
    
    let html = ''; 
    messages.forEach(m => {
        const isMy = m.user === currentUser.name; 
        let roleColorClass = '';
        switch(m.role) { 
            case 'Директор': roleColorClass = 'role-director'; break; 
            case 'Конструкторское бюро': roleColorClass = 'role-kb'; break; 
            case 'Производство и ОТК': roleColorClass = 'role-prod'; break; 
            case 'Менеджер': roleColorClass = 'role-manager'; break; 
            case 'Бухгалтерия': roleColorClass = 'role-buh'; break; 
            case 'Юрист': roleColorClass = 'role-law'; break; 
            default: roleColorClass = ''; 
        }
        html += `
        <div class="chat-msg ${isMy ? 'my-msg' : ''}">
            <div class="chat-msg-meta"><span class="role-name ${roleColorClass}">${m.user} (${m.role})</span><span>${m.time}</span></div>
            <div class="chat-msg-bubble">${m.text}</div>
        </div>`; 
    });
    
    const isScrolledToBottom = c.scrollHeight - c.clientHeight <= c.scrollTop + 50; 
    c.innerHTML = html; 
    if (isScrolledToBottom) c.scrollTop = c.scrollHeight;
}

async function sendGlobalMessage() {
    const i = document.getElementById('messengerInput'); 
    const text = i.value.trim(); 
    if (!text || !currentGlobalChatId) return;
    
    i.value = ''; 
    await apiCall(`/chats/${currentGlobalChatId}/messages`, 'POST', { user: currentUser.name, role: currentUser.role, text: text }); 
    await loadGlobalMessages(currentGlobalChatId, true);
}

function openCreateChatModal() {
    const uDiv = document.getElementById('newChatUsers'); 
    if (uDiv) { 
        uDiv.innerHTML = allUsersDB.filter(u => u.name !== currentUser.name).map(u => 
            `<label style="display:flex; gap:8px; align-items:center; margin-bottom:6px; cursor:pointer;"><input type="checkbox" value="${u.name}" class="new-chat-cb"> <b>${u.name}</b> <span style="color:var(--secondary)">(${u.role})</span></label>`
        ).join(''); 
    }
    document.getElementById('createChatModal').style.display = 'flex';
}

async function submitNewChat() {
    const name = document.getElementById('newChatName').value.trim(); 
    if (!name) return customAlert("Введите название чата");
    
    const cbs = document.querySelectorAll('.new-chat-cb:checked'); 
    const participants = Array.from(cbs).map(cb => cb.value); 
    participants.push(currentUser.name); 
    
    await apiCall('/chats', 'POST', { name: name, creator: currentUser.name, participants: participants }); 
    document.getElementById('createChatModal').style.display = 'none'; 
    await loadGlobalChats();
}

async function deleteCurrentChat() {
    if (!currentGlobalChatId) return; 
    if (!(await customConfirm("Вы уверены, что хотите удалить этот чат? Восстановить сообщения будет невозможно."))) return;
    
    await apiCall(`/chats/${currentGlobalChatId}`, 'DELETE'); 
    currentGlobalChatId = null;
    
    document.getElementById('mChatTitle').innerText = "Выберите чат слева"; 
    document.getElementById('messengerInputArea').style.display = 'none'; 
    document.getElementById('messengerMessages').innerHTML = ''; 
    document.getElementById('btnDeleteChat').style.display = 'none'; 
    await loadGlobalChats();
}