let activeTimers = {}; 

function initSignaturePad() {
    canvas = document.getElementById('sigCanvas'); if(!canvas) return; ctx = canvas.getContext('2d'); ctx.lineWidth = 2; ctx.strokeStyle = document.documentElement.dataset.theme === 'dark' ? '#fff' : '#0f172a'; ctx.lineCap = 'round';
    const renderExistingSig = () => { const u = allUsersDB.find(x => x.email === currentUser.email); if (u && u.signature) { let img = new Image(); img.onload = () => ctx.drawImage(img, 0, 0); img.src = u.signature; } }; renderExistingSig();
    const getPos = (e) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = rect.width ? canvas.width / rect.width : 1;
        const scaleY = rect.height ? canvas.height / rect.height : 1;
        const cx = (e.clientX !== undefined) ? e.clientX : (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
        const cy = (e.clientY !== undefined) ? e.clientY : (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
        return { x: (cx - rect.left) * scaleX, y: (cy - rect.top) * scaleY };
    };
    const start = (e) => { isDrawing = true; const pos = getPos(e); ctx.beginPath(); ctx.moveTo(pos.x, pos.y); e.preventDefault(); };
    const draw = (e) => { if(isDrawing) { const pos = getPos(e); ctx.lineTo(pos.x, pos.y); ctx.stroke(); e.preventDefault(); } };
    const stop = () => { isDrawing = false; };
    canvas.addEventListener('mousedown', start); canvas.addEventListener('mousemove', draw); canvas.addEventListener('mouseup', stop); canvas.addEventListener('mouseout', stop); canvas.addEventListener('touchstart', start); canvas.addEventListener('touchmove', draw); canvas.addEventListener('touchend', stop);
}

function clearSignature() { if(ctx) ctx.clearRect(0, 0, canvas.width, canvas.height); }
async function saveSignature() { if(!canvas) return; const dataUrl = canvas.toDataURL(); const res = await apiCall('/users/signature', 'POST', { email: currentUser.email, signature: dataUrl }); if(res && res.status === 'success') { showToast('Система', 'Подпись сохранена!'); await loadAllUsers(); } }

function formatTime(s) {
    const h = Math.floor(s/3600).toString().padStart(2,'0');
    const m = Math.floor((s%3600)/60).toString().padStart(2,'0');
    const sc = (s%60).toString().padStart(2,'0');
    return `${h}:${m}:${sc}`;
}

function normalizeChecklistSections(rawChecklist) {
    let checklist = rawChecklist;
    if (typeof checklist === 'string') {
        const trimmed = checklist.trim();
        if (!trimmed) return [];
        try {
            checklist = JSON.parse(trimmed);
        } catch (error) {
            console.warn('Failed to parse checklist payload', error);
            return [];
        }
    }
    if (checklist && typeof checklist === 'object' && !Array.isArray(checklist) && Array.isArray(checklist.sections)) {
        checklist = checklist.sections;
    }
    if (!Array.isArray(checklist)) return [];
    return checklist.map((section, index) => {
        if (section && typeof section === 'object' && !Array.isArray(section)) {
            return {
                title: String(section.title || `\u042d\u0442\u0430\u043f ${index + 1}`),
                responsibles: String(section.responsibles || '\u041c\u0435\u043d\u0435\u0434\u0436\u0435\u0440'),
                tasks: Array.isArray(section.tasks) ? section.tasks.map(task => String(task || '')).filter(Boolean) : [],
            };
        }
        const title = String(section || '').trim();
        if (!title) return null;
        const templateSection = (typeof checklistTemplate !== 'undefined' && Array.isArray(checklistTemplate) && checklistTemplate[index]) ? checklistTemplate[index] : null;
        return {
            title,
            responsibles: String((templateSection && templateSection.responsibles) || '\u041c\u0435\u043d\u0435\u0434\u0436\u0435\u0440'),
            tasks: templateSection && Array.isArray(templateSection.tasks) ? templateSection.tasks.map(task => String(task || '')).filter(Boolean) : [],
        };
    }).filter(Boolean);
}

function renderChecklist(forceRedraw = false) {
    const container = document.getElementById('checklist'); if(!container) return;
    if(container.children.length > 0 && !forceRedraw) { updateChecklistUI(); return; }
    const p = projectsDB.find(x => x.id === currentProjectId); let secHtmlAll = '';
    if (p) p.checklist = normalizeChecklistSections(p.checklist);
    
    if(p && p.checklist && p.checklist.length > 0) {
        const isDirector = currentUser.role === 'Директор';
        p.checklist.forEach((sec, sIdx) => {
            const deleteSecBtn = isDirector ? `<button class="icon-btn no-print" style="color:var(--danger);" onclick="deleteSection(${sIdx})" title="Удалить этап"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>` : '';
            
            secHtmlAll += `<div class="section checklist-section fade-in" data-index="${sIdx}">
                <div class="section-header checklist-section-header">
                    <button type="button" class="checklist-section-trigger" onclick="this.parentElement.nextElementSibling.classList.toggle('active')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
                        <span class="checklist-section-title">${sec.title}</span>
                    </button>
                    <div class="checklist-section-actions">
                        <input type="text" id="date_${sIdx}" placeholder="Дедлайн" class="no-print date-picker auth-input checklist-deadline">
                        <span class="status checklist-counter"></span>
                        ${deleteSecBtn}
                    </div>
                </div>
                <div class="section-content ${sIdx === 0 ? 'active' : ''}" style="display: flex; flex-direction: column;">`;
                
            sec.tasks.forEach((tText, tIdx) => {
                const tId = `task_${sIdx}_${tIdx}`;
                const deleteBtn = isDirector ? `<button class="icon-btn no-print chk-task-del-btn" onclick="deleteTaskFromSection(${sIdx}, ${tIdx})" title="Удалить задачу"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>` : '';
                
                secHtmlAll += `
                <div class="task">
                    <div style="display: flex; align-items: flex-start; gap: 14px; width: 100%;">
                        <input type="checkbox" id="${tId}" onchange="handleCheck(this, '${tId}')" style="margin-top: 3px; width: 20px; height: 20px; cursor: pointer;">
                        
                        <div class="task-content-wrapper">
                            <div class="task-header-row">
                                <label class="task-text" for="${tId}" style="cursor: pointer;">${tText}</label>
                                
                                <div class="task-actions no-print">
                                    <button class="icon-btn" onclick="document.getElementById('cinput_row_${tId}').style.display='flex'; document.getElementById('input_${tId}').focus();" title="Написать комментарий">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                                    </button>
                                    <input type="file" id="finput_${tId}" style="display:none" onchange="uploadTaskFile(event, '${tId}')">
                                    <button class="icon-btn" onclick="document.getElementById('finput_${tId}').click()" title="Прикрепить файл">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>
                                    </button>
                                    <button class="icon-btn" onclick="addSubtask('${tId}')" title="Добавить подзадачу">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                                    </button>
                                    ${deleteBtn}
                                </div>
                            </div>

                            <div class="task-meta">
                                <div class="task-meta-group">
                                    <span class="task-pill">Ответственные <strong>${sec.responsibles}</strong></span>
                                    <span id="time_${tId}" style="display: flex; align-items: center; gap: 6px;"></span>
                                </div>
                                <div id="timer_block_${tId}" class="task-timer-block"></div>
                            </div>
                        </div>
                    </div>

                    <div class="task-detail-stack">
                        <div id="hard_lock_${tId}"></div>
                        <div id="subs_${tId}" class="checklist-subtasks"></div>
                        <div id="file_${tId}" style="display:none; font-size:12px; padding: 10px 14px; background: rgba(30, 58, 138, 0.03); border-radius: 8px; border: 1px dashed rgba(30, 58, 138, 0.2);"></div>
                        <div class="comment-text" id="text_${tId}" style="display:none;"></div>
                        <div id="sig_${tId}"></div>
                        
                        <div class="chk-comment-row" id="cinput_row_${tId}">
                            <input type="text" class="comment-input chk-comment-input" id="input_${tId}" placeholder="Написать комментарий и нажать Enter..." onkeypress="if(event.key === 'Enter') { saveMultipleComment('${tId}', this.value); this.value=''; this.parentElement.style.display='none'; }">
                            <button class="icon-btn" onclick="document.getElementById('cinput_row_${tId}').style.display='none'" title="Отмена"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--secondary)" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
                        </div>
                    </div>
                </div>`;
            });
            
            if (isDirector || sec.responsibles.includes(currentUser.role)) {
                secHtmlAll += `<div class="checklist-add-task-row"><button class="btn-secondary no-print checklist-add-task-btn" onclick="addTaskToSection(${sIdx})">Добавить задачу в этот этап</button></div>`;
            }
            secHtmlAll += `</div></div>`;
        });
        if (isDirector) {
            secHtmlAll += `<div class="checklist-add-section-row no-print" style="margin-top: 24px;"><button class="btn-secondary checklist-add-section-btn" onclick="addSectionToChecklist()">Создать новый этап</button></div>`;
        }
    } else {
        secHtmlAll = `<div class="project-empty-hint" style="padding:60px 20px;">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--border)" stroke-width="1.5" style="margin-bottom: 16px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
            <div style="font-size: 14px; font-weight: 500; color: var(--text); margin-bottom: 8px;">Чек-лист не настроен</div>
            <div style="font-size: 13px;">Создайте первый этап, чтобы начать работу над проектом.</div>
        </div>`;
        if (currentUser.role === 'Директор') {
            secHtmlAll += `<div class="checklist-add-section-row no-print" style="margin-top: 24px;"><button class="btn-secondary checklist-add-section-btn" onclick="addSectionToChecklist()">Создать новый этап</button></div>`;
        }
    }
    
    container.innerHTML = secHtmlAll;
    flatpickr(".date-picker", { locale: "ru", dateFormat: "d.m.Y", disableMobile: "true", onChange: function(s, d, i) { saveDeadline(i.element.id.split('_')[1], d); appendLog(`Установил дедлайн этапа на ${d}`); }});
    updateChecklistUI(); 
}

window.toggleTimer = function(tId) {
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!activeTimers[tId]) {
        activeTimers[tId] = { start: Date.now() };
        activeTimers[tId].interval = setInterval(() => {
            const el = document.getElementById(`timer_val_${tId}`);
            if(el) {
                const diff = Math.floor((Date.now() - activeTimers[tId].start) / 1000);
                el.innerText = formatTime(diff);
            }
        }, 1000);
        updateChecklistUI();
    } else {
        clearInterval(activeTimers[tId].interval);
        const seconds = Math.floor((Date.now() - activeTimers[tId].start) / 1000);
        delete activeTimers[tId];
        if(!p.time_logs) p.time_logs = [];
        p.time_logs.push({ tId: tId, user: currentUser.name, seconds: seconds, date: new Date().toLocaleDateString('ru-RU') });
        syncProject(p).then(() => { updateChecklistUI(); calcMargin(); appendLog(`Отработал над задачей: ${formatTime(seconds)}`); });
    }
}

function updateChecklistUI() {
    const p = projectsDB.find(x => x.id === currentProjectId); if(!p || !p.checklist) return;
    p.checklist = normalizeChecklistSections(p.checklist);
    const isDirector = currentUser.role === 'Директор'; let previousSectionCompleted = true;
    const activeDeputies = allUsersDB.filter(u => {
        if (u.deputy !== currentUser.name || !u.abs_start || !u.abs_end) return false;
        const today = new Date(); today.setHours(0,0,0,0);
        const pStart = u.abs_start.split('.'); const pEnd = u.abs_end.split('.');
        if (pStart.length !== 3 || pEnd.length !== 3) return false;
        const dStart = new Date(pStart[2], pStart[1]-1, pStart[0]); const dEnd = new Date(pEnd[2], pEnd[1]-1, pEnd[0]);
        return today >= dStart && today <= dEnd;
    }).map(u => u.role);
    
    p.checklist.forEach((sec, sIdx) => {
        const canEditRole = isDirector || sec.responsibles.includes(currentUser.role) || activeDeputies.some(r => sec.responsibles.includes(r));
        let isDisabled = !canEditRole || (!isDirector && !previousSectionCompleted);
        let checkedCount = 0;
        
        const dateInput = document.getElementById(`date_${sIdx}`);
        if(dateInput) { dateInput.disabled = !isDirector; dateInput.style.opacity = isDirector ? "1" : "0.5"; if (dateInput._flatpickr) dateInput._flatpickr.setDate(p.deadlines ? p.deadlines[sIdx] || '' : '', false); }
        
        sec.tasks.forEach((_, tIdx) => {
            const tId = `task_${sIdx}_${tIdx}`; 
            const stateStr = p.checkedState ? p.checkedState[tId] : null;
            const isChecked = !!stateStr; const isPending = isChecked && stateStr.startsWith('PENDING');
            if(isChecked && !isPending) checkedCount++; 
            
            let accSecs = 0;
            if(p.time_logs) { p.time_logs.filter(l => l.tId === tId).forEach(l => accSecs += l.seconds); }
            
            let timerHtml = '';
            if (accSecs > 0) timerHtml += `<span class="task-time-log">${formatTime(accSecs)}</span>`;
            
            if (!isChecked && canEditRole) {
                const isActive = !!activeTimers[tId];
                timerHtml += `<span id="timer_val_${tId}" class="chk-timer-val ${isActive ? 'active' : 'inactive'}">${isActive ? '...' : '00:00:00'}</span>`;
                
                const playIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`;
                const stopIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>`;
                
                timerHtml += `<button id="timer_btn_${tId}" class="icon-btn no-print chk-timer-btn ${isActive ? 'active' : 'inactive'}" onclick="toggleTimer('${tId}')" title="${isActive ? 'Остановить таймер' : 'Начать таймер'}">${isActive ? stopIcon : playIcon}</button>`;
            }
            
            const tb = document.getElementById(`timer_block_${tId}`); if(tb) tb.innerHTML = timerHtml;
            
            let subsDisabled = isDisabled; let allSubsChecked = true; let subtasksHtml = '';
            if (p.subtasks && p.subtasks[tId] && p.subtasks[tId].length > 0) {
                p.subtasks[tId].forEach(sub => {
                    if(!sub.checked) allSubsChecked = false;
                    subtasksHtml += `<div class="checklist-subtask"><input type="checkbox" style="margin:0; width:16px; height:16px; cursor: pointer;" ${sub.checked ? 'checked' : ''} onchange="toggleSubtask('${tId}', '${sub.id}', this.checked)" ${subsDisabled ? 'disabled' : ''}><span class="chk-subtask-text ${sub.checked ? 'checked' : 'unchecked'}" style="font-size:13px; font-weight: 500; flex: 1;">${sub.text}</span>${!subsDisabled ? `<button onclick="deleteSubtask('${tId}', '${sub.id}')" class="icon-btn chk-subtask-del-btn" title="Удалить подзадачу"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>` : ''}</div>`;
                });
            }
            const subsDiv = document.getElementById(`subs_${tId}`); if(subsDiv) subsDiv.innerHTML = subtasksHtml;
            
            let finalIsDisabled = isDisabled || (!isChecked && !allSubsChecked);
            const lockDiv = document.getElementById(`hard_lock_${tId}`);
            if(lockDiv) {
                if (!isDirector && !previousSectionCompleted) { lockDiv.innerHTML = `<div class="checklist-lock checklist-lock--danger"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg> Ожидает: "${p.checklist[sIdx-1]?.title || ''}"</div>`; } 
                else if (!isChecked && !allSubsChecked) { lockDiv.innerHTML = `<div class="checklist-lock checklist-lock--warning"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> Сначала завершите подзадачи</div>`; } 
                else { lockDiv.innerHTML = ''; }
            }
            
            const cb = document.getElementById(tId); 
            if(cb) { 
                cb.checked = isChecked; 
                cb.disabled = finalIsDisabled; 
                if (isPending) cb.classList.add('cb-pending'); else cb.classList.remove('cb-pending'); 
                
                const taskRow = cb.closest('.task');
                if (taskRow) {
                    if (isChecked) {
                        taskRow.style.background = 'rgba(16, 185, 129, 0.02)';
                    } else {
                        taskRow.style.background = 'transparent';
                    }
                }
            }
            
            const timeEl = document.getElementById(`time_${tId}`); 
            const sigEl = document.getElementById(`sig_${tId}`);
            
            let returnBtnHtml = ''; 
            if (isChecked && canEditRole) {
                returnBtnHtml = `<button class="icon-btn no-print" style="color: var(--danger); padding: 4px; margin-left: 8px;" onclick="rejectTask('${tId}')" title="Вернуть на доработку"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 14 4 9 9 4"></polyline><path d="M20 20v-7a4 4 0 0 0-4-4H4"></path></svg></button>`;
            }
            
            if(timeEl) {
                let cleanStateStr = stateStr ? stateStr.replace(/✅ |🟡 |✓ |DONE \| |PENDING \| /g, '').trim() : "";
                let statusIcon = "";
                
                if (stateStr) { 
                    if (stateStr.includes('DONE') || stateStr.includes('✅') || stateStr.includes('✓')) { 
                        statusIcon = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2" style="flex-shrink: 0;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`; 
                        timeEl.innerHTML = `<span style="color: var(--success); display: inline-flex; align-items: center; gap: 4px; font-weight: 600; background: rgba(16,185,129,0.1); padding: 4px 8px; border-radius: 6px;">${statusIcon} Утверждено: ${cleanStateStr}</span> ${returnBtnHtml}`;
                    } else { 
                        statusIcon = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" style="flex-shrink: 0;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`; 
                        timeEl.innerHTML = `<span style="color: var(--primary); display: inline-flex; align-items: center; gap: 4px; font-weight: 600; background: rgba(30,58,138,0.1); padding: 4px 8px; border-radius: 6px;">${statusIcon} Ожидает проверки: ${cleanStateStr}</span>`;
                    } 
                } else {
                    timeEl.innerHTML = "";
                }
            }
            
            if(sigEl) {
                if (stateStr && !isPending) {
                    let uName = stateStr.replace(/✅ |🟡 |✓ |DONE \| |PENDING \| /g, '').split(' | ')[0]; uName = uName.split(' (утв.')[0].trim();
                    const u = allUsersDB.find(x => x.name === uName);
                    if (u && u.signature) sigEl.innerHTML = `<img src="${u.signature}" style="height: 30px; opacity: 0.8; filter: grayscale(100%); margin-top: 4px;">`; else sigEl.innerHTML = '';
                } else sigEl.innerHTML = '';
            }
            
            const fDiv = document.getElementById(`file_${tId}`);
            if (fDiv) {
                if (p.taskFiles && p.taskFiles[tId]) { 
                    fDiv.style.display = 'block'; 
                    fDiv.innerHTML = `<div style="display:flex; align-items:center; gap:8px;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg> <span style="font-weight:500; color:var(--secondary);">Документ:</span> <a href="${p.taskFiles[tId].url}" target="_blank" style="color:var(--primary); text-decoration:none; font-weight:600;">${p.taskFiles[tId].name}</a></div>`; 
                } 
                else { fDiv.style.display = 'none'; fDiv.innerHTML = ''; }
            }
            
            const cTxt = document.getElementById(`text_${tId}`); 
            if(cTxt) { 
                let taskComments = p.comments ? p.comments[tId] : null;
                if (typeof taskComments === 'string') { taskComments = [{ text: taskComments, author: 'Пользователь', time: '' }]; p.comments[tId] = taskComments; }
                if(Array.isArray(taskComments) && taskComments.length > 0) { 
                    cTxt.style.display = 'flex'; cTxt.style.flexDirection = 'column'; cTxt.style.gap = '8px';
                    let cHtml = '';
                    taskComments.forEach((cmt, cIdx) => {
                        let isReturn = cmt.text && cmt.text.startsWith('ВОЗВРАТ');
                        let bgCol = isReturn ? 'rgba(239, 68, 68, 0.04)' : 'var(--bg)';
                        let brCol = isReturn ? 'var(--danger)' : 'var(--border)';
                        let tCol = isReturn ? 'var(--danger)' : 'var(--text)';
                        cHtml += `<div class="chk-comment-box ${isReturn ? 'return' : 'normal'}"><div class="chk-comment-inner"><div class="chk-comment-meta">${cmt.author || 'Пользователь'} ${cmt.time ? `<span class="chk-comment-time">• ${cmt.time}</span>` : ''}</div><div class="chk-comment-text ${isReturn ? 'return' : 'normal'}">${cmt.text}</div></div><button class="icon-btn no-print chk-comment-del-btn" onclick="deleteMultipleComment('${tId}', ${cIdx})" title="Удалить комментарий"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button></div>`;
                    });
                    cTxt.innerHTML = cHtml;
                } else { cTxt.style.display = 'none'; cTxt.innerHTML = ''; } 
            }
        });
        
        const secDiv = document.querySelector(`.section[data-index="${sIdx}"]`);
        if(secDiv) { 
            const sEl = secDiv.querySelector('.status'); 
            if(sEl) sEl.innerText = `${checkedCount}/${sec.tasks.length}`; 
            if(checkedCount === sec.tasks.length && sec.tasks.length > 0) secDiv.querySelector('.section-header').classList.add('completed'); 
            else secDiv.querySelector('.section-header').classList.remove('completed'); 
        }
        previousSectionCompleted = (checkedCount === sec.tasks.length);
    });
    updateProgress();
}

async function addTaskToSection(sIdx) {
    const text = await customPrompt("Введите описание новой задачи:");
    if (!text) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    p.checklist[sIdx].tasks.push(text.trim());
    appendLog(`Добавил задачу в этап "${p.checklist[sIdx].title}": ${text}`);
    await syncProject(p); renderChecklist(true);
}

async function addSectionToChecklist() {
    const title = await customPrompt("Название нового этапа:");
    if (!title) return;
    const resp = await customPrompt("Кто ответственные? (роли через запятую)", "Менеджер");
    const p = projectsDB.find(x => x.id === currentProjectId);
    if(!p.checklist) p.checklist = [];
    p.checklist.push({ title: title.trim(), responsibles: resp || "Менеджер", tasks: [] });
    appendLog(`Создал новый этап чек-листа: ${title}`);
    await syncProject(p); renderChecklist(true);
}

async function deleteTaskFromSection(sIdx, tIdx) {
    if (!(await customConfirm("Удалить эту задачу из списка?"))) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    const taskName = p.checklist[sIdx].tasks[tIdx];
    p.checklist[sIdx].tasks.splice(tIdx, 1);
    appendLog(`Удалил задачу: ${taskName}`);
    await syncProject(p); renderChecklist(true);
}

async function deleteSection(sIdx) {
    if (!(await customConfirm("Удалить весь этап и все задачи внутри него?"))) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    const secName = p.checklist[sIdx].title;
    p.checklist.splice(sIdx, 1);
    appendLog(`Удалил этап чек-листа: ${secName}`);
    await syncProject(p); renderChecklist(true);
}

window.addSubtask = async function(tId) {
    const text = await customPrompt("Введите текст подзадачи (например: Собрать оригиналы):");
    if (!text) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    if(!p.subtasks) p.subtasks = {};
    if(!p.subtasks[tId]) p.subtasks[tId] = [];
    p.subtasks[tId].push({ id: Date.now().toString(), text: text, checked: false });
    appendLog(`Добавил подзадачу: ${text}`);
    updateChecklistUI(); await syncProject(p);
}

window.toggleSubtask = async function(tId, subId, isChecked) {
    const p = projectsDB.find(x => x.id === currentProjectId);
    const sub = p.subtasks[tId].find(s => s.id === subId);
    if(sub) { sub.checked = isChecked; appendLog(`Отметил подзадачу: ${sub.text}`); }
    updateChecklistUI(); await syncProject(p);
}

window.deleteSubtask = async function(tId, subId) {
    if(!(await customConfirm("Удалить подзадачу?"))) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    p.subtasks[tId] = p.subtasks[tId].filter(s => s.id !== subId);
    updateChecklistUI(); await syncProject(p);
}

async function uploadTaskFile(e, tId) {
    const file = e.target.files[0]; if(!file) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    document.getElementById(`file_${tId}`).style.display = 'block';
    document.getElementById(`file_${tId}`).innerHTML = `Загрузка файла...`;
    const formData = new FormData(); formData.append("file", file); formData.append("user", currentUser.name);
    const res = await apiCall(`/projects/${currentProjectId}/upload`, 'POST', formData);
    if(res && res.status === 'success') {
        if (!p.taskFiles) p.taskFiles = {};
        p.taskFiles[tId] = { url: res.file.url, name: res.file.name };
        appendLog(`Прикрепил подтверждающий документ к задаче`);
        await syncProject(p); updateChecklistUI();
    } else { customAlert("Ошибка загрузки"); updateChecklistUI(); }
    e.target.value = '';
}

async function handleCheck(cb, tId) {
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p) return;
    const previousCheckedState = JSON.parse(JSON.stringify(p.checkedState || {}));
    const previousComments = JSON.parse(JSON.stringify(p.comments || {}));
    if (!p.checkedState) p.checkedState = {};
    const stateStr = p.checkedState[tId];
    const now = new Date(); const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
    if (!stateStr) {
        if (currentUser.role === 'Директор') { p.checkedState[tId] = `DONE | ${currentUser.name} | ${timeStr}`; appendLog(`Утвердил задачу: ${tId}`); } 
        else { p.checkedState[tId] = `PENDING | ${currentUser.name} | ${timeStr}`; appendLog(`Выполнил задачу (ожидает проверки): ${tId}`); }
        if (p.comments && p.comments[tId]) {
            if (typeof p.comments[tId] === 'string' && p.comments[tId].includes('ВОЗВРАТ')) delete p.comments[tId];
            else if (Array.isArray(p.comments[tId])) { p.comments[tId] = p.comments[tId].filter(c => !c.text.includes('ВОЗВРАТ')); if(p.comments[tId].length === 0) delete p.comments[tId]; }
        }
    } else if (stateStr.startsWith('PENDING') || stateStr.startsWith('🟡')) {
        if (currentUser.role === 'Директор') { 
            const originalUser = stateStr.replace(/PENDING \| |🟡 /g, '').split(' | ')[0];
            p.checkedState[tId] = `DONE | ${originalUser} (утв. ${currentUser.name}) | ${timeStr}`; 
            appendLog(`Утвердил задачу после проверки: ${tId}`); cb.checked = true; 
        } else { delete p.checkedState[tId]; appendLog(`Отменил выполнение: ${tId}`); }
    } else { delete p.checkedState[tId]; appendLog(`Снял утверждение: ${tId}`); }
    updateChecklistUI();
    if (cb) cb.disabled = true;
    const currentSnapshot = typeof normalizeProjectPayload === 'function'
        ? normalizeProjectPayload(JSON.parse(JSON.stringify(p)))
        : JSON.parse(JSON.stringify(p));
    const response = await syncProject(p);
    if (!response || response.error) {
        p.checkedState = previousCheckedState;
        p.comments = previousComments;
        updateChecklistUI();
        if (cb) cb.disabled = false;
        showToast('Чек-лист', response?.message || 'Не удалось сохранить изменение', 'error');
        return;
    }
    await loadProjects();
    if (!projectsDB.find(item => item.id === currentProjectId)) {
        projectsDB.push(currentSnapshot);
    }
    updateChecklistUI();
    if (typeof calcMargin === 'function') calcMargin();
}

async function rejectTask(tId) { 
    const reason = await customPrompt("Укажите причину возврата на доработку:"); 
    if (!reason) return; 
    const p = projectsDB.find(x => x.id === currentProjectId); 
    delete p.checkedState[tId]; 
    if (!p.comments) p.comments = {}; 
    if (!Array.isArray(p.comments[tId])) { p.comments[tId] = p.comments[tId] ? [{text: p.comments[tId], author: 'Пользователь', time: ''}] : []; }
    const now = new Date(); const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
    p.comments[tId].push({ text: `ВОЗВРАТ: ${reason}`, author: currentUser.name, time: timeStr });
    appendLog(`Вернул этап на доработку. Причина: ${reason}`); updateChecklistUI(); await syncProject(p); 
    showToast(p.name, `Вернул этап на доработку: ${reason}`); 
}

window.saveMultipleComment = async function(tId, text) {
    if (!text.trim()) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p) return;
    if (!p.comments) p.comments = {};
    if (!p.comments[tId] || typeof p.comments[tId] === 'string') { p.comments[tId] = p.comments[tId] ? [{ text: p.comments[tId], author: 'Пользователь', time: '' }] : []; }
    const now = new Date(); const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
    p.comments[tId].push({ text: text.trim(), author: currentUser.name, time: timeStr });
    appendLog(`Написал комментарий: ${text.trim()}`); updateChecklistUI(); await syncProject(p);
}

window.deleteMultipleComment = async function(tId, cIdx) {
    if (!(await customConfirm("Удалить этот комментарий?"))) return;
    const p = projectsDB.find(x => x.id === currentProjectId);
    if (!p || !p.comments || !Array.isArray(p.comments[tId])) return;
    p.comments[tId].splice(cIdx, 1);
    updateChecklistUI(); await syncProject(p);
}

async function saveDeadline(sIdx, date) { const p = projectsDB.find(x => x.id === currentProjectId); if(!p.deadlines) p.deadlines = {}; p.deadlines[sIdx] = date; await syncProject(p); }

function updateProgress() {
    const p = projectsDB.find(x => x.id === currentProjectId); if(!p || !p.checklist) return;
    p.checklist = normalizeChecklistSections(p.checklist);
    let approvedCount = 0; if (p.checkedState) Object.values(p.checkedState).forEach(val => { if (val.includes('DONE') || val.includes('✅') || val.includes('✓')) approvedCount++; });
    const total = p.checklist.reduce((a, c) => a + c.tasks.length, 0); p.progress = total === 0 ? 0 : (approvedCount / total) * 100;
    const pb = document.getElementById('progressBar'); if(pb) pb.style.width = p.progress + '%';
    const fb = document.getElementById('finalBlock'); if(fb) fb.style.display = p.progress === 100 ? 'block' : 'none';
    const btnA = document.getElementById('btnArchiveFinal'); if (btnA) btnA.style.display = p.status === 'active' ? 'flex' : 'none';
}

function downloadPDF() {
    const p = projectsDB.find(x => x.id === currentProjectId); if(!p || !p.checklist) return;
    p.checklist = normalizeChecklistSections(p.checklist);
    const container = document.createElement('div'); container.style.padding = '10px'; container.style.fontFamily = '"Times New Roman", Times, serif'; container.style.color = '#000'; container.style.background = '#fff';
    const currentName = document.getElementById('projName').value || '___________________'; const currentContract = document.getElementById('projContract').value || '___________________'; const currentClient = document.getElementById('projClient').value || '___________________'; const currentManager = document.getElementById('projManager').value || '___________________'; const lastDeadline = (p.deadlines && p.deadlines[p.checklist.length-1]) ? p.deadlines[p.checklist.length-1] : '___________________';
    const qrData = encodeURIComponent(`${window.location.origin}/?project_id=${p.id}`); const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=100x100&data=${qrData}`;
    let html = `<div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px;"><div style="flex: 1;"><h2 style="font-size:16px; margin-bottom:20px; text-transform:uppercase;">ЧЕК-ЛИСТ<br>ПРОИЗВОДСТВА и ЗАКРЫТИЯ СДЕЛКИ</h2><p style="font-size:14px; margin:5px 0;"><b>Наименование объекта:</b> ${currentName}</p><p style="font-size:14px; margin:5px 0;"><b>Договор №:</b> ${currentContract}</p><p style="font-size:14px; margin:5px 0;"><b>Заказчик:</b> ${currentClient}</p><p style="font-size:14px; margin:5px 0;"><b>Менеджер:</b> ${currentManager}</p></div><div style="text-align: right; padding-left: 20px;"><img src="${qrUrl}" crossorigin="anonymous" style="width: 80px; height: 80px; border: 1px solid #ccc; padding: 4px;"><div style="font-size: 9px; color: #666; margin-top: 4px;">Идентификатор: ${p.id}</div></div></div><p style="font-size:14px; margin:5px 0; margin-bottom:20px;"><b>Плановая дата закрытия:</b> ${lastDeadline}</p>`;
    p.checklist.forEach((sec, sIdx) => { html += `<h3 style="font-size:14px; margin-top:15px; margin-bottom:5px;">${sec.title}</h3><table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:5px;" border="1"><thead><tr style="background:#f2f2f2;"><th style="padding:6px; width:5%;">№</th><th style="padding:6px; width:40%;">Мероприятие / Документ</th><th style="padding:6px; width:10%;">Статус</th><th style="padding:6px; width:15%;">Дата</th><th style="padding:6px; width:30%;">ФИО и Подпись ответственного</th></tr></thead><tbody>`; sec.tasks.forEach((task, tIdx) => { const tId = `task_${sIdx}_${tIdx}`; const state = p.checkedState ? p.checkedState[tId] : null; let status = "Нет", date = "", fio = "", sigHtml = ""; 
    if (state && (state.includes('DONE') || state.includes('✅') || state.includes('✓'))) { status = "Да"; const parts = state.replace(/DONE \| |✅ |✓ /g, '').split(' | '); if (parts.length === 2) { fio = parts[0]; date = parts[1]; } else { fio = state; } } 
    if (fio) { let sigName = fio.split(' (утв.')[0].trim(); const u = allUsersDB.find(x => x.name === sigName); if (u && u.signature) sigHtml = `<br><img src="${u.signature}" style="max-height: 40px; margin-top: 5px;">`; } 
    html += `<tr><td style="padding:6px; text-align:center;">${sIdx+1}.${tIdx+1}</td><td style="padding:6px;">${task}</td><td style="padding:6px; text-align:center; font-weight:bold;">${status}</td><td style="padding:6px; text-align:center;">${date}</td><td style="padding:6px; text-align:center;">${fio} ${sigHtml}</td></tr>`; }); html += `</tbody></table><p style="font-size:11px; font-style:italic; margin-bottom:15px; color:#333;">Ответственные: ${sec.responsibles}</p>`; });
    const folder = p.archive_details?.folder || "_____"; const rack = p.archive_details?.rack || "_____"; const aDate = p.archive_details?.date || "_____";
    html += `<div style="margin-top: 30px; page-break-inside: avoid;"><h3 style="font-size: 14px;">ИТОГОВОЕ ЗАКРЫТИЕ СДЕЛКИ:</h3><p style="font-size: 12px; margin-bottom: 5px;">Все этапы чек-листа пройдены. Оригинал передан в архив.</p><p style="font-size: 12px; margin-bottom: 20px;"><b>Папка:</b> ${folder} | <b>Стеллаж:</b> ${rack} | <b>Дата передачи:</b> ${aDate}</p><p style="font-size: 14px; margin-bottom: 5px;">Руководитель проекта: ___________________ / _______________________ /</p><p style="font-size: 14px; margin-bottom: 20px;">Дата: «___» _______ 202__ г.</p></div>`;
    container.innerHTML = html; const opt = { margin: [15, 15, 15, 15], filename: `Чек-лист_${currentName}.pdf`, image: { type: 'jpeg', quality: 1 }, html2canvas: { scale: 2, useCORS: true }, jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' } }; html2pdf().set(opt).from(container).save().then(() => { appendLog("Скачал ГОСТ PDF-отчет"); });
}
