let currentUsersTab = 'active';
let currentRoleFilter = ''; // Для фильтрации по отделам

function switchUsersTab(tab) {
    currentUsersTab = tab;
    document.getElementById('tabActiveUsers').classList.toggle('active', tab === 'active');
    document.getElementById('tabBannedUsers').classList.toggle('active', tab === 'banned');
    renderProfile();
}

function filterUsersByRole(role) {
    currentRoleFilter = role;
    document.querySelectorAll('.user-filter-btn').forEach(b => b.classList.remove('active'));
    if (event && event.target) event.target.classList.add('active');
    renderProfile();
}

function isUserAbsentOrUpcoming(u) {
    if (!u.abs_end) return false;
    const today = new Date(); today.setHours(0,0,0,0);
    const pEnd = u.abs_end.split('.');
    if (pEnd.length !== 3) return false;
    const dEnd = new Date(pEnd[2], pEnd[1]-1, pEnd[0]);
    return dEnd >= today; 
}

function renderKPI() {
    const container = document.getElementById('kpiListContainer'); if(!container) return;
    
    let html = '';
    allUsersDB.filter(u => u.status === 'approved' && u.role !== 'Директор').forEach(u => {
        let totalSeconds = 0;
        projectsDB.forEach(p => {
            if(p.time_logs) p.time_logs.filter(l => l.user === u.name).forEach(l => totalSeconds += l.seconds);
        });
        
        let timeStr = '0 мин';
        if (totalSeconds > 0 && totalSeconds < 60) {
            timeStr = `${totalSeconds} сек`;
        } else if (totalSeconds >= 60) {
            const h = Math.floor(totalSeconds / 3600);
            const m = Math.floor((totalSeconds % 3600) / 60);
            timeStr = h > 0 ? `${h} ч ${m} мин` : `${m} мин`;
        }
        
        let projectCheckboxesDone = 0;
        projectsDB.forEach(p => {
            if (p.checkedState) {
                Object.values(p.checkedState).forEach(val => {
                    if (val.includes(u.name)) projectCheckboxesDone++;
                });
            }
        });

        let tasksDone = tasksDB.filter(t => t.executor === u.name && t.status === 'completed').length;
        let tasksActive = tasksDB.filter(t => t.executor === u.name && t.status === 'active').length;
        
        let approvalsProcessed = 0;
        approvalsDB.forEach(a => {
            if (a.history.some(h => h.includes(u.name) && (h.includes('согласовал') || h.includes('отклонил')))) {
                approvalsProcessed++;
            }
        });

        html += `
        <div class="kpi-card fade-in">
            <div class="kpi-user">${u.name} <span style="font-size:12px; color:var(--secondary); font-weight:normal;">(${u.role})</span></div>
            <div class="kpi-stat">По таймеру: <b>${timeStr}</b></div>
            <div class="kpi-stat">Отметок в проектах: <b style="color:var(--primary)">${projectCheckboxesDone}</b></div>
            <div class="kpi-stat">Выполнено поручений: <b style="color:var(--success)">${tasksDone}</b></div>
            <div class="kpi-stat">Поручений в работе: <b style="color:var(--danger)">${tasksActive}</b></div>
            <div class="kpi-stat">Согласований: <b>${approvalsProcessed}</b></div>
        </div>`;
    });
    
    container.innerHTML = html || '<div style="grid-column: 1/-1; text-align:center; color:var(--secondary);">Сотрудников пока нет.</div>';
}

function renderProfile() {
    let completedTasks = 0; let upcomingDeadlines = 0;
    const today = new Date(); today.setHours(0,0,0,0);
    const nextWeek = new Date(today); nextWeek.setDate(today.getDate() + 7);

    projectsDB.forEach(p => {
        if (p.checkedState) { 
            Object.keys(p.checkedState).forEach(k => { 
                if (p.checkedState[k].includes(currentUser.name)) completedTasks++; 
            }); 
        }        
        if (p.status === 'active') {
            if(p.checklist) p.checklist.forEach((sec, sIdx) => {
                if (sec.responsibles.includes(currentUser.role) && p.deadlines && p.deadlines[sIdx]) {
                    const pts = p.deadlines[sIdx].split('.');
                    if (pts.length === 3) {
                        const dDate = new Date(pts[2], pts[1]-1, pts[0]);
                        if (dDate >= today && dDate <= nextWeek) upcomingDeadlines++;
                        else if (dDate < today) {
                            let secOk = true;
                            for (let t = 0; t < sec.tasks.length; t++) { 
                                if (!p.checkedState || !p.checkedState[`task_${sIdx}_${t}`] || p.checkedState[`task_${sIdx}_${t}`].startsWith('🟡')) secOk = false; 
                            }
                            if (!secOk) upcomingDeadlines++; 
                        }
                    }
                }
            });
        }
    });

    const elTasks = document.getElementById('profCompletedTasks'); if(elTasks) elTasks.innerText = completedTasks;
    const elDeadlines = document.getElementById('profUpcomingDeadlines'); if(elDeadlines) elDeadlines.innerText = upcomingDeadlines;
    
    const uData = allUsersDB.find(x => x.email === currentUser.email);
    const vType = document.getElementById('absType');
    const vStart = document.getElementById('absStart');
    const vEnd = document.getElementById('absEnd');
    const vReason = document.getElementById('absReason');
    const vDep = document.getElementById('vacationDeputy');
    
    if (vType && vStart && vEnd && vReason && vDep && uData) {
        flatpickr("#absStart", { locale: "ru", dateFormat: "d.m.Y" });
        flatpickr("#absEnd", { locale: "ru", dateFormat: "d.m.Y" });
        
        if(vStart._flatpickr) vStart._flatpickr.setDate(uData.abs_start || ''); else vStart.value = uData.abs_start || '';
        if(vEnd._flatpickr) vEnd._flatpickr.setDate(uData.abs_end || ''); else vEnd.value = uData.abs_end || '';
        
        let cleanAbsType = uData.abs_type ? uData.abs_type.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '').replace(/❓/g, '').replace(/✈️/g, '').trim() : 'Отпуск';
        vType.value = cleanAbsType || 'Отпуск';
        vReason.value = uData.abs_reason || '';
        
        let opts = '<option value="">Без заместителя</option>';
        allUsersDB.filter(x => x.email !== currentUser.email && x.status === 'approved').forEach(x => {
            opts += `<option value="${x.name}" ${uData.deputy === x.name ? 'selected' : ''}>${x.name} (${x.role})</option>`;
        });
        vDep.innerHTML = opts;
    }
    
    const dBlock = document.getElementById('directorUsersBlock');
    if (dBlock) {
        if (currentUser.role === 'Директор') {
            dBlock.style.display = 'block';
            document.getElementById('totalUsersCount').innerText = allUsersDB.length;
            
            let uHtml = '';
            let filteredUsers = allUsersDB.filter(u => currentUsersTab === 'active' ? u.status !== 'banned' : u.status === 'banned');
            
            // ПРИМЕНЕНИЕ ФИЛЬТРА ПО ОТДЕЛАМ
            if (currentRoleFilter) {
                filteredUsers = filteredUsers.filter(u => u.role === currentRoleFilter);
            }
            
            filteredUsers.forEach(u => {
                let statusBadge = '';
                if(u.status === 'approved') statusBadge = '<span class="status-badge" style="background: rgba(16, 185, 129, 0.1); color: var(--success);">Активен</span>';
                else if(u.status === 'pending') statusBadge = '<span class="status-badge" style="background: var(--bg); color: var(--secondary);">Ожидает</span>';
                else if(u.status === 'banned') statusBadge = '<span class="status-badge" style="background: rgba(239, 68, 68, 0.1); color: var(--danger);">Заблокирован</span>';
                
                let actionBtn = '';
                if(u.email === currentUser.email) actionBtn = '<span style="color:var(--secondary); font-size:12px;">Это вы</span>';
                else if (u.status === 'banned') actionBtn = `<button class="btn-success" style="padding: 6px 12px; font-size:12px; background:var(--success); color:white; border:none;" onclick="restoreUser('${u.email}')">🔓 Разблокировать</button>`;
                else {
                    const headBtnText = u.is_head === 1 ? "Снять права Рук." : "Сделать Рук-лем";
                    // ДОБАВЛЕНА КНОПКА СМЕНЫ ОТДЕЛА И ОБНОВЛЕНЫ СТИЛИ
                    actionBtn = `<div style="display:flex; gap:6px; flex-wrap:wrap;">
                        <button class="btn-secondary" style="padding: 4px 8px; font-size:11px;" onclick="changeUserRole('${u.email}', '${u.role}')">✏️ Сменить отдел</button>
                        <button class="btn-secondary" style="padding: 4px 8px; font-size:11px;" onclick="toggleHeadStatus('${u.email}', ${u.is_head === 1 ? 0 : 1})">${headBtnText}</button>
                        <button class="btn-danger" style="padding: 4px 8px; font-size:11px; background:var(--danger); color:white; border:none;" onclick="removeUser('${u.email}')">🔒 Заблок.</button>
                    </div>`;
                }

                const pwdHtml = `<span class="pwd-blur" onclick="this.classList.toggle('revealed')" title="Нажмите, чтобы показать" style="font-family: monospace; background: var(--bg); padding: 4px 8px; border-radius: 6px; font-size: 12px; cursor: pointer;">${u.password || '—'}</span>`;
                
                let vacHtml = '';
                if (isUserAbsentOrUpcoming(u)) {
                    let userAbsType = u.abs_type ? u.abs_type.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '').replace(/❓/g, '').replace(/✈️/g, '').trim() : 'Отпуск';
                    
                    let icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>';
                    if (userAbsType === 'Больничный') icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>';
                    if (userAbsType === 'Командировка') icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><path d="M22 2L11 13"></path><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
                    if (userAbsType === 'Другое') icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: middle;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
                    
                    const reasonText = u.abs_reason ? `Причина: ${u.abs_reason}.` : '';
                    const depText = u.deputy ? `Замещает: ${u.deputy}` : 'Без заместителя';
                    
                    let prefixText = 'до';
                    const pStart = u.abs_start ? u.abs_start.split('.') : [];
                    if (pStart.length === 3) {
                        const dStart = new Date(pStart[2], pStart[1]-1, pStart[0]);
                        if (dStart > today) prefixText = `с ${u.abs_start} по`;
                    }
                    
                    vacHtml = `<div style="font-size: 11px; margin-top: 4px; background: rgba(0,0,0,0.04); padding: 4px 8px; border-radius: 6px; display: inline-block;">
                        ${icon} <b>${userAbsType}</b> ${prefixText} ${u.abs_end}. <span style="color:var(--secondary)">${reasonText} ${depText}</span>
                    </div>`;
                }
                
                const roleText = u.is_head === 1 && u.role !== 'Директор' ? `<b>${u.role} (Руководитель)</b>` : (u.role || '-');

                uHtml += `<tr>
                    <td><b>${u.name}</b><br>${vacHtml}</td>
                    <td>${u.email}</td><td>${pwdHtml}</td><td>${roleText}</td><td>${statusBadge}</td><td>${actionBtn}</td>
                </tr>`;
            });
            const tBody = document.getElementById('allUsersListTable'); if(tBody) tBody.innerHTML = uHtml;
        } else {
            dBlock.style.display = 'none';
        }
    }
}

async function saveVacation() {
    const vType = document.getElementById('absType').value;
    const vStart = document.getElementById('absStart').value;
    const vEnd = document.getElementById('absEnd').value;
    const vReason = document.getElementById('absReason').value;
    const vDep = document.getElementById('vacationDeputy').value;
    
    if (!vStart || !vEnd) { alert("Пожалуйста, укажите даты начала и окончания отсутствия."); return; }

    const btn = document.querySelector('button[onclick="saveVacation()"]'); const oldText = btn.innerText;
    if(btn) { btn.innerText = "Сохранение..."; btn.disabled = true; }

    const res = await apiCall('/users/vacation', 'POST', { email: currentUser.email, abs_start: vStart, abs_end: vEnd, abs_type: vType, abs_reason: vReason, deputy: vDep });
    
    if (res && res.status === 'success') {
        if(btn) { btn.innerText = "✅ Настройки сохранены!"; btn.style.background = "var(--success)"; }
        await loadAllUsers(); renderProfile();
        setTimeout(() => { if(btn) { btn.innerText = oldText; btn.style.background = "var(--primary)"; btn.disabled = false; } }, 2500);
    } else {
        alert("❌ Ошибка соединения с сервером."); if(btn) { btn.innerText = oldText; btn.disabled = false; }
    }
}

async function clearVacation() {
    if(!confirm("Сбросить статус отсутствия? Вы вернетесь к обычной работе.")) return;
    await apiCall('/users/vacation', 'POST', { email: currentUser.email, abs_start: "", abs_end: "", abs_type: "", abs_reason: "", deputy: "" });
    await loadAllUsers(); renderProfile(); alert("С возвращением!");
}

async function removeUser(email) { if(confirm(`Заблокировать пользователя ${email}? Он потеряет доступ к CRM.`)) { await apiCall('/users/remove', 'POST', { email: email }); await loadAllUsers(); renderProfile(); } }
async function restoreUser(email) { if(confirm(`Восстановить доступ пользователю ${email}?`)) { await apiCall('/users/restore', 'POST', { email: email }); await loadAllUsers(); renderProfile(); } }

async function toggleHeadStatus(email, status) {
    if(confirm(status === 1 ? `Назначить ${email} руководителем отдела?` : `Снять права руководителя с ${email}?`)) {
        await apiCall('/users/make_head', 'POST', { email: email, role: '', is_head: status });
        await loadAllUsers(); renderProfile();
    }
}

// НОВАЯ ФУНКЦИЯ ДЛЯ СМЕНЫ ОТДЕЛА
async function changeUserRole(email, currentRole) {
    const newRole = prompt(`Введите новую роль/отдел для ${email} (сейчас: ${currentRole}):`, currentRole);
    if (!newRole || newRole === currentRole) return;
    
    await apiCall(`/users/role`, 'PUT', { email: email, role: newRole });
    if (typeof loadAllUsers === 'function') await loadAllUsers(); 
    renderProfile();     
}

function renderNotifications() {
    let allLogs = [];
    projectsDB.forEach(p => {
        if(p.logs) {
            p.logs.forEach(log => {
                if (log.action.includes('Выполнил задачу') || log.action.includes('Утвердил') || log.action.includes('Снял галочку') || log.action.includes('Вернул этап на доработку') || log.action.includes('сгенерировал документ') || log.action.includes('АВТО-ЭСКАЛАЦИЯ')) {
                    allLogs.push({ proj_id: p.id, proj_name: p.name, time: log.time, user: log.user, action: log.action });
                }
            });
        }
    });

    allLogs.sort((a, b) => { const pT = str => { const [d, t] = str.split(' '); const [day, mo, yr] = d.split('.'); const [hr, min] = t.split(':'); return new Date(yr, mo-1, day, hr, min).getTime(); }; return pT(b.time) - pT(a.time); });

    let unread = parseInt(localStorage.getItem('korda_unread_count')) || 0;
    let html = '';

    allLogs.slice(0, 30).forEach(l => {
        const logId = `${l.proj_id}_${l.time}_${l.action}_${l.user}`;
        if (!seenToastIds.has(logId)) {
            seenToastIds.add(logId);
            if (!isFirstLoad && l.user !== currentUser.name) {
                if (l.user === "🤖 СИСТЕМА" && currentUser.role !== 'Директор') { } 
                else { showToast(l.proj_name, l.action, l.proj_id); unread++; localStorage.setItem('korda_unread_count', unread); }
            }
        }
        
        let actionText = l.action;
        let iconSvg = '';
        let iconBg = '';
        let iconColor = '';
        
        if (actionText.includes('сгенерировал документ')) {
            let docName = actionText.split('документ:')[1] || "документ";
            actionText = `сгенерировал(а) ${docName.trim()}`;
            iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>';
            iconBg = 'rgba(59, 130, 246, 0.1)'; iconColor = 'var(--primary)';
        } else if (actionText.includes('Выполнил задачу')) {
            actionText = 'поставил(а) отметку выполнения (ожидает проверки)';
            iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>';
            iconBg = 'rgba(245, 158, 11, 0.1)'; iconColor = '#f59e0b';
        } else if (actionText.includes('Утвердил')) {
            actionText = 'проверил(а) и утвердил(а) задачу';
            iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
            iconBg = 'rgba(16, 185, 129, 0.1)'; iconColor = 'var(--success)';
        } else if (actionText.includes('Снял галочку') || actionText.includes('Снял утверждение')) {
            actionText = 'снял(а) отметку о выполнении';
            iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
            iconBg = 'rgba(239, 68, 68, 0.1)'; iconColor = 'var(--danger)';
        } else if (actionText.includes('Вернул этап на доработку')) {
            let reason = actionText.split('Причина:')[1] || "";
            actionText = `вернул(а) этап на доработку.<br><span style="color:var(--danger); font-size: 11px; margin-top: 4px; display: block;">Причина: ${reason}</span>`;
            iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 14 4 9 9 4"></polyline><path d="M20 20v-7a4 4 0 0 0-4-4H4"></path></svg>';
            iconBg = 'rgba(245, 158, 11, 0.1)'; iconColor = '#f59e0b';
        } else if (actionText.includes('АВТО-ЭСКАЛАЦИЯ')) {
            let details = actionText.replace('⚠️ АВТО-ЭСКАЛАЦИЯ: ', '').replace('АВТО-ЭСКАЛАЦИЯ: ', '');
            actionText = `<span style="color:var(--danger); font-weight:600;">Внимание!</span> ${details}`;
            iconSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>';
            iconBg = 'rgba(239, 68, 68, 0.1)'; iconColor = 'var(--danger)';
        }
        
        let displayUser = l.user === "🤖 СИСТЕМА" ? "Система" : l.user;

        html += `<div class="notif-item" onclick="openProject(${l.proj_id}); toggleNotifications();">
                    <div class="notif-icon" style="background: ${iconBg}; color: ${iconColor};">
                        ${iconSvg}
                    </div>
                    <div class="notif-content">
                        <div class="notif-header-row">
                            <span class="notif-project">${l.proj_name}</span>
                            <span class="notif-time">${l.time}</span>
                        </div>
                        <div class="notif-text">
                            <b>${displayUser}</b> ${actionText}
                        </div>
                    </div>
                </div>`;
    });

    if (allLogs.length === 0) html = '<div style="padding: 20px; text-align: center; color: var(--secondary); font-size: 13px;">Пока нет отметок в проектах</div>';
    const list = document.getElementById('notifList'); if(list) list.innerHTML = html;
    const badge = document.getElementById('notifBadge'); if(badge) { if(unread > 0) { badge.style.display = 'flex'; badge.innerText = unread > 99 ? '99+' : unread; } else { badge.style.display = 'none'; } }
    isFirstLoad = false;
}

function showToast(title, action, proj_id) {
    const container = document.getElementById('toastContainer'); if (!container) return;
    let cleanText = action; let borderColor = 'var(--success)';
    if (cleanText.includes('Выполнил задачу')) { cleanText = 'Поставил отметку в Чек-листе (Ждет проверки)'; borderColor = '#f59e0b'; }
    if (cleanText.includes('Утвердил')) cleanText = 'Задача проверена Директором';
    if (cleanText.includes('Снял галочку') || cleanText.includes('Снял утверждение')) { cleanText = 'Снял отметку в Чек-листе'; borderColor = 'var(--danger)'; }
    if (cleanText.includes('Вернул этап на доработку')) { cleanText = 'Внимание: этап возвращен на доработку!'; borderColor = '#f59e0b'; }
    if (cleanText.includes('АВТО-ЭСКАЛАЦИЯ')) borderColor = 'var(--danger)';

    const toast = document.createElement('div'); toast.className = 'toast'; toast.style.borderLeftColor = borderColor;
    toast.innerHTML = `<div class="toast-title">${title}</div><div class="toast-desc">${cleanText}</div>`;
    toast.onclick = () => openProject(proj_id);
    container.appendChild(toast); setTimeout(() => toast.classList.add('show'), 100); 
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 400); }, 5000);
}

function toggleNotifications() { const dropdown = document.getElementById('notifDropdown'); if(!dropdown) return; if(dropdown.style.display === 'flex') { dropdown.style.display = 'none'; } else { dropdown.style.display = 'flex'; localStorage.setItem('korda_unread_count', 0); const badge = document.getElementById('notifBadge'); if(badge) badge.style.display = 'none'; } }
document.addEventListener('click', (e) => { const wrap = document.querySelector('.notif-wrapper'); const drop = document.getElementById('notifDropdown'); if(wrap && !wrap.contains(e.target) && drop && drop.style.display === 'flex') { drop.style.display = 'none'; localStorage.setItem('korda_unread_count', 0); const badge = document.getElementById('notifBadge'); if(badge) badge.style.display = 'none'; } });

function renderClients() { const tbody = document.getElementById('clientsListTable'); if(!tbody) return; tbody.innerHTML = ''; clientsDB.forEach(c => { tbody.innerHTML += `<tr><td><b>${c.name}</b></td><td>${c.inn}</td><td>${c.contact}</td></tr>`; }); }
async function addClient() { const n = document.getElementById('addClientName').value, i = document.getElementById('addClientInn').value, c = document.getElementById('addClientContact').value; if(!n) return alert("Введите название!"); await apiCall('/clients', 'POST', {name: n, inn: i, contact: c}); document.getElementById('addClientName').value = ''; document.getElementById('addClientInn').value = ''; document.getElementById('addClientContact').value = ''; await loadClients(); renderClients(); }

async function openAdminPanelLogic() { 
    const users = await apiCall('/users/pending'); 
    const tbody = document.getElementById('adminUsersList'); if(!tbody) return; 
    tbody.innerHTML = ''; 
    const opts = availableRoles.map(r => `<option value="${r}">${r}</option>`).join(''); 
    users.forEach((u, i) => { 
        tbody.innerHTML += `<tr>
            <td>${u.name}</td><td>${u.email}</td>
            <td><select id="role_${i}"><option disabled selected>Выбрать</option>${opts}</select></td>
            <td><label style="font-size:12px; display:flex; align-items:center; gap:5px;"><input type="checkbox" id="head_${i}"> Руководитель</label></td>
            <td><button class="btn-primary" onclick="approveUser('${u.email}', ${i})">Одобрить</button></td>
        </tr>`; 
    }); 
}

async function approveUser(e, i) { 
    const isHead = document.getElementById(`head_${i}`).checked ? 1 : 0;
    await apiCall('/users/approve', 'POST', { email: e, role: document.getElementById(`role_${i}`).value, is_head: isHead }); 
    openAdminPanelLogic(); 
}