// ==========================================
// 6. ПОЧТА (EMAIL)
// ==========================================

async function renderEmails(forceRefresh = false) {
    const container = document.getElementById('emailsListContainer'); 
    if (!container) return;
    
    if (forceRefresh || emailsDB.length === 0) { 
        container.innerHTML = '<span style="color:var(--primary); font-weight:600;">🔄 Идет подключение к почтовому серверу Яндекс...</span>'; 
        const data = await apiCall('/emails'); 
        if (data) emailsDB = data; 
    }
    
    if (emailsDB.length === 0) { 
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--secondary);">Писем нет или ошибка подключения</div>'; 
        return; 
    }
    
    container.innerHTML = emailsDB.map(e => `
    <div style="background: var(--card-bg); padding: 20px; border-radius: 12px; border: 1px solid var(--border); box-shadow: 0 2px 10px rgba(0,0,0,0.02);">
        <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
            <b style="font-size: 16px;">${e.subject}</b>
            <button class="btn-primary" style="padding: 6px 12px; font-size: 12px;" onclick="createProjectFromEmail(${e.id})">Сделать проектом</button>
        </div>
        <div style="font-size: 12px; color: var(--secondary); margin-bottom: 10px;">От: ${e.sender}</div>
        <div style="font-size: 14px; white-space: pre-wrap; color: var(--text); background: var(--bg); padding: 10px; border-radius: 6px;">${e.body}</div>
    </div>`).join('');
}

function createProjectFromEmail(id) { 
    const email = emailsDB.find(e => e.id === id); 
    if (!email) return; 
    
    createNewProject(); 
    setTimeout(() => { 
        document.getElementById('newProjName').value = "Email: " + email.subject.substring(0, 40); 
        document.getElementById('newProjContract').value = 'ПОЧТА'; 
    }, 100); 
}

// ==========================================
// 7. СОВЕЩАНИЯ И ПЛАНЕРКИ
// ==========================================

function renderMeetings() {
    const container = document.getElementById('meetingsListContainer'); 
    if (!container) return;
    
    if (meetingsDB.length === 0) { 
        container.innerHTML = '<div style="grid-column: 1/-1; padding: 20px; text-align: center; color: var(--secondary);">Нет запланированных совещаний.</div>'; 
        return; 
    }
    
    container.innerHTML = meetingsDB.map(m => {
        const bg = m.status === 'completed' ? 'var(--bg)' : 'var(--card-bg)'; 
        const opacity = m.status === 'completed' ? '0.7' : '1';
        return `
        <div style="background: ${bg}; opacity: ${opacity}; padding: 20px; border-radius: 12px; border: 1px solid var(--border); cursor: pointer;" onclick="openProtocol(${m.id})">
            <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                <span style="font-weight: 700;">${m.title}</span>
                <span style="font-size: 12px; color: var(--primary); font-weight: 600;">${m.m_date} ${m.m_time}</span>
            </div>
            <div style="font-size: 12px; color: var(--secondary); margin-bottom: 10px;">Участники: ${m.participants.join(', ')}</div>
            ${m.status === 'completed' 
                ? '<span style="font-size: 10px; background: var(--success); color: white; padding: 2px 6px; border-radius: 4px;">Проведено</span>' 
                : '<span style="font-size: 10px; background: #f59e0b; color: white; padding: 2px 6px; border-radius: 4px;">Запланировано</span>'}
        </div>`;
    }).join('');
}

function openMeetingModal() { 
    flatpickr("#meetDate", { locale: "ru", dateFormat: "d.m.Y" }); 
    const uDiv = document.getElementById('meetUsers'); 
    if (uDiv) { 
        uDiv.innerHTML = allUsersDB.map(u => 
            `<label style="display:flex; gap:8px; align-items:center; margin-bottom:6px; cursor:pointer;"><input type="checkbox" value="${u.name}" class="meet-cb"> <b>${u.name}</b> <span style="color:var(--secondary)">(${u.role})</span></label>`
        ).join(''); 
    } 
    document.getElementById('meetingModal').style.display = 'flex'; 
}

async function submitMeeting() {
    const title = document.getElementById('meetTitle').value; 
    const mDate = document.getElementById('meetDate').value; 
    const mTime = document.getElementById('meetTime').value;
    
    const participants = Array.from(document.querySelectorAll('.meet-cb:checked')).map(cb => cb.value);
    const agenda = document.getElementById('meetAgenda').value.split(',').map(s => s.trim()).filter(s => s.length > 0);
    
    if (!title || !mDate || !mTime) return customAlert("Заполните тему, дату и время");
    
    await apiCall('/meetings', 'POST', { title: title, m_date: mDate, m_time: mTime, participants: participants, agenda: agenda });
    
    document.getElementById('meetingModal').style.display = 'none'; 
    await loadMeetings(); 
    renderMeetings();
}

let currentMeetingId = null;

function openProtocol(id) {
    currentMeetingId = id; 
    const m = meetingsDB.find(x => x.id === id); 
    if (!m) return;
    
    document.getElementById('protTitle').innerText = m.title; 
    document.getElementById('protMeta').innerText = `Дата: ${m.m_date} ${m.m_time} | Участники: ${m.participants.join(', ')}`;
    
    let html = ''; 
    m.agenda.forEach((item, idx) => { 
        const dec = m.decisions[idx] || ''; 
        html += `
        <div style="margin-bottom: 15px; padding: 10px; background: var(--bg); border-radius: 8px;">
            <div style="font-weight: 600; font-size: 13px; margin-bottom: 6px;">Повестка ${idx+1}: ${item}</div>
            <textarea id="dec_${idx}" class="auth-input" style="margin:0; font-size:13px;" rows="2" placeholder="Решение по пункту...">${dec}</textarea>
        </div>`; 
    });
    
    document.getElementById('protAgendaList').innerHTML = html; 
    document.getElementById('protocolModal').style.display = 'flex';
}

async function saveProtocol() { 
    const m = meetingsDB.find(x => x.id === currentMeetingId); 
    m.agenda.forEach((_, idx) => { 
        m.decisions[idx] = document.getElementById(`dec_${idx}`).value; 
    }); 
    m.status = 'completed'; 
    
    await apiCall(`/meetings/${m.id}`, 'PUT', m); 
    await customAlert('Протокол сохранен!'); 
    document.getElementById('protocolModal').style.display = 'none'; 
    
    await loadMeetings(); 
    renderMeetings(); 
}

function generateProtocolPDF() { 
    const m = meetingsDB.find(x => x.id === currentMeetingId); 
    const container = document.createElement('div'); 
    container.style.padding = '10px'; 
    container.style.fontFamily = '"Times New Roman", Times, serif'; 
    container.style.color = '#000'; 
    container.style.background = '#fff'; 
    
    let html = `
    <h2 style="text-align:center; font-size:16px; margin-bottom:20px; text-transform:uppercase;">ПРОТОКОЛ СОВЕЩАНИЯ</h2>
    <p style="font-size:14px; margin:5px 0;"><b>Тема:</b> ${m.title}</p>
    <p style="font-size:14px; margin:5px 0;"><b>Дата и время:</b> ${m.m_date} в ${m.m_time}</p>
    <p style="font-size:14px; margin:5px 0; margin-bottom:20px;"><b>Присутствовали:</b> ${m.participants.join(', ')}</p>
    <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:5px;" border="1">
        <thead>
            <tr style="background:#f2f2f2;">
                <th style="padding:6px; width:5%;">№</th>
                <th style="padding:6px; width:45%;">Повестка (Слушали)</th>
                <th style="padding:6px; width:50%;">Решение (Постановили)</th>
            </tr>
        </thead>
        <tbody>`; 
        
    m.agenda.forEach((item, idx) => { 
        html += `<tr><td style="padding:6px; text-align:center;">${idx+1}</td><td style="padding:6px;">${item}</td><td style="padding:6px;">${m.decisions[idx] || ''}</td></tr>`; 
    }); 
    
    html += `</tbody></table>`; 
    container.innerHTML = html; 
    
    const opt = { 
        margin: [15, 15, 15, 15], 
        filename: `Протокол_${m.m_date}.pdf`, 
        image: { type: 'jpeg', quality: 1 }, 
        html2canvas: { scale: 2 }, 
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' } 
    }; 
    
    html2pdf().set(opt).from(container).save(); 
}