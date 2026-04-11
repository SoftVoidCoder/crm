// ==========================================
// 1. НАВИГАЦИЯ И БАЗОВЫЕ ФИЛЬТРЫ ДАШБОРДА
// ==========================================

function clearDepartmentFilter(doRender = true) {
    currentDepartmentFilter = null;
    document.querySelectorAll('.dept-item').forEach(el => el.classList.remove('active'));
    
    const titleEl = document.getElementById('dashboardTitle');
    if (titleEl) {
        titleEl.innerText = "ВСЕ ПРОЕКТЫ";
    }
    
    if (doRender) renderDashboard();
}

function filterByDepartment(role, el) {
    currentDepartmentFilter = role;
    
    document.querySelectorAll('.nav-item, .dept-item').forEach(e => e.classList.remove('active'));
    el.classList.add('active'); 
    
    currentTab = 'active';
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    
    const tActive = document.querySelector('.tab[onclick="switchTab(\'active\')"]'); 
    if (tActive) tActive.classList.add('active');
    
    const titleEl = document.getElementById('dashboardTitle'); 
    if (titleEl) titleEl.innerText = `ВХОДЯЩИЕ: ${role.toUpperCase()}`;
    
    const viewsToHide = [
        'analyticsView', 'adminView', 'projectView', 'clientsView', 
        'profileView', 'emailsView', 'meetingsView', 'messengerView', 
        'documentsView', 'tasksView', 'knowledgeView', 'approvalsView', 'kpiView'
    ];
    
    viewsToHide.forEach(id => { 
        const viewEl = document.getElementById(id); 
        if (viewEl) { 
            viewEl.style.display = 'none'; 
            viewEl.classList.remove('fade-in'); 
        } 
    });
    
    const target = document.getElementById('dashboardView'); 
    if (target) { 
        target.style.display = 'block'; 
        target.classList.add('fade-in'); 
    } 
    
    renderDashboard();
}

function navigateTo(view, triggerRender = true) {
    const viewsToHide = [
        'dashboardView', 'analyticsView', 'adminView', 'projectView', 
        'clientsView', 'profileView', 'emailsView', 'meetingsView', 
        'messengerView', 'documentsView', 'tasksView', 'knowledgeView', 
        'approvalsView', 'kpiView'
    ];
    
    viewsToHide.forEach(id => {
        const el = document.getElementById(id); 
        if (el) { 
            el.style.display = 'none'; 
            el.classList.remove('fade-in'); 
        }
    });
    
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    
    let viewId = view;
    
    if (view === 'profile') { 
        const nav = document.getElementById('navProfile'); 
        if(nav) nav.classList.add('active'); 
        renderProfile(); 
    } 
    else if (view === 'emails') { 
        const nav = document.getElementById('navEmails'); 
        if(nav) nav.classList.add('active'); 
        renderEmails(); 
    } 
    else if (view === 'meetings') { 
        const nav = document.getElementById('navMeetings'); 
        if(nav) nav.classList.add('active'); 
        renderMeetings(); 
    } 
    else if (view === 'messenger') { 
        const nav = document.getElementById('navMessenger'); 
        if(nav) nav.classList.add('active'); 
        loadGlobalChats(); 
    }
    else if (view === 'documents') { 
        const nav = document.getElementById('navDocuments'); 
        if(nav) nav.classList.add('active'); 
        renderDocuments(); 
    }
    else if (view === 'tasks') { 
        const nav = document.getElementById('navTasks'); 
        if(nav) nav.classList.add('active'); 
        renderTasks(); 
    }
    else if (view === 'knowledge') { 
        const nav = document.getElementById('navKnowledge'); 
        if(nav) nav.classList.add('active'); 
        renderKnowledge(); 
    }
    else if (view === 'approvals') { 
        const nav = document.getElementById('navApprovals'); 
        if(nav) nav.classList.add('active'); 
        renderApprovals(); 
    }
    else if (view === 'kpi') { 
        const nav = document.getElementById('navKpi'); 
        if(nav) nav.classList.add('active'); 
        renderKPI(); 
    }
    
    const target = document.getElementById(viewId + 'View');
    if (target) { 
        target.style.display = 'block'; 
        target.classList.add('fade-in'); 
    }
    
    if (view === 'dashboard') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navDashboard'); 
        if(nav) nav.classList.add('active'); 
        if(triggerRender) renderDashboard(); 
    } 
    else if (view === 'analytics') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navAnalytics'); 
        if(nav) nav.classList.add('active'); 
        requestAnimationFrame(() => drawCharts());
        setTimeout(() => drawCharts(), 120);
    } 
    else if (view === 'clients') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navClients'); 
        if(nav) nav.classList.add('active'); 
        renderClients(); 
    }
    else if (view === 'admin') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('adminBtn'); 
        if(nav) nav.classList.add('active'); 
        openAdminPanelLogic(); 
    }
}

// ==========================================
// 2. ОТРИСОВКА ДАШБОРДА (ПРОЕКТЫ)
// ==========================================

function drawCharts() {
    const tCol = document.documentElement.dataset.theme === 'dark' ? '#f8fafc' : '#0f172a';
    const a = projectsDB.filter(p => p.status === 'active').length;
    const ar = projectsDB.filter(p => p.status === 'archive').length;
    const c = projectsDB.filter(p => p.status === 'canceled').length;
    
    const dlConf = { 
        color: '#fff', 
        font: { weight: 'bold', size: 14 }, 
        formatter: (v, ctx) => { 
            const tot = ctx.chart.data.datasets[0].data.reduce((acc,b) => acc + b, 0); 
            return (tot === 0 || v === 0) ? '' : Math.round((v / tot) * 100) + '%'; 
        } 
    };

    if (statusChartObj) statusChartObj.destroy();
    
    const stEl = document.getElementById('statusChart');
    if (stEl) { 
        statusChartObj = new Chart(stEl, { 
            type: 'pie', 
            data: { 
                labels: ['В работе', 'Архив', 'Отменены'], 
                datasets: [{ 
                    data: [a, ar, c], 
                    backgroundColor: ['#1e3a8a', '#10b981', '#ef4444'], 
                    borderWidth: 0 
                }] 
            }, 
            options: { 
                plugins: { 
                    datalabels: dlConf, 
                    title: { display: true, text: 'Статусы проектов', color: tCol }, 
                    legend: { labels: { color: tCol } } 
                } 
            } 
        }); 
    }

    let l = 0, m = 0, h = 0; 
    projectsDB.filter(p => p.status === 'active').forEach(p => { 
        if (p.progress < 30) l++; 
        else if (p.progress < 80) m++; 
        else h++; 
    });
    
    if (progressChartObj) progressChartObj.destroy();
    
    const prEl = document.getElementById('progressChart');
    if (prEl) { 
        progressChartObj = new Chart(prEl, { 
            type: 'doughnut', 
            data: { 
                labels: ['0-30%', '30-80%', '80-100%'], 
                datasets: [{ 
                    data: [l, m, h], 
                    backgroundColor: ['#64748b', '#3b82f6', '#10b981'], 
                    borderWidth: 0 
                }] 
            }, 
            options: { 
                plugins: { 
                    datalabels: dlConf, 
                    title: { display: true, text: 'Прогресс активных', color: tCol }, 
                    legend: { labels: { color: tCol } } 
                } 
            } 
        }); 
    }

    // ИНЖЕКЦИЯ ЮРИДИЧЕСКОЙ АНАЛИТИКИ (ТЗ 2.6.2)
    const analyticsContainer = document.getElementById('analyticsView');
    if(analyticsContainer && !document.getElementById('legalStatsBlock')) {
        analyticsContainer.insertAdjacentHTML('beforeend', `
            <div id="legalStatsBlock" style="margin-top: 40px; border-top: 1px solid var(--border); padding-top: 20px;">
                <h3 style="margin-bottom: 20px; color: var(--primary);">⚖️ Юридическая аналитика</h3>
                <div class="metrics-grid">
                    <div class="metric-card warning"><div class="metric-title">Сумма в претензиях</div><div class="metric-value" id="statClaimsSum">0 ₽</div></div>
                    <div class="metric-card" style="border-color: var(--primary);"><div class="metric-title" style="color: var(--primary);">Сумма в судах</div><div class="metric-value" id="statCourtsSum" style="color: var(--primary);">0 ₽</div></div>
                    <div class="metric-card"><div class="metric-title">Судов выиграно / закрыто</div><div class="metric-value" id="statCourtsWon" style="color: var(--text);">0</div></div>
                </div>
            </div>
        `);
    }
    
    if(document.getElementById('statClaimsSum') && typeof claimsDB !== 'undefined') document.getElementById('statClaimsSum').innerText = claimsDB.reduce((a, c) => a + (c.amount || 0), 0).toLocaleString('ru-RU') + ' ₽';
    if(document.getElementById('statCourtsSum') && typeof courtCasesDB !== 'undefined') document.getElementById('statCourtsSum').innerText = courtCasesDB.reduce((a, c) => a + (c.amount || 0), 0).toLocaleString('ru-RU') + ' ₽';
    if(document.getElementById('statCourtsWon') && typeof courtCasesDB !== 'undefined') document.getElementById('statCourtsWon').innerText = courtCasesDB.filter(c => c.stage === 'Закрыто').length;
}

function checkOverdue(p) {
    if (p.status !== 'active') return false; 
    let isOvd = false; 
    const today = new Date(); 
    today.setHours(0,0,0,0);
    
    if (!p.checklist) return false;
    
    for (let s = 0; s < p.checklist.length; s++) {
        if (p.deadlines && p.deadlines[s]) {
            const pts = p.deadlines[s].split('.'); 
            if (pts.length === 3 && new Date(pts[2], pts[1] - 1, pts[0]) < today) {
                let secOk = true;
                for (let t = 0; t < p.checklist[s].tasks.length; t++) { 
                    if (!p.checkedState || !p.checkedState[`task_${s}_${t}`] || p.checkedState[`task_${s}_${t}`].startsWith('🟡')) { 
                        secOk = false; 
                        break; 
                    } 
                }
                if (!secOk) { 
                    isOvd = true; 
                    break; 
                }
            }
        }
    }
    return isOvd;
}

function getProjectKanbanStage(p) {
    if (p.status === 'archive') return 'archive'; 
    if (p.status === 'canceled') return 'canceled'; 
    if (p.progress === 100) return 'ready';
    
    if (!p.checklist) return 'prod';
    
    for (let s = 0; s < p.checklist.length; s++) {
        for (let t = 0; t < p.checklist[s].tasks.length; t++) {
            if (!p.checkedState || !p.checkedState[`task_${s}_${t}`] || p.checkedState[`task_${s}_${t}`].startsWith('🟡')) {
                if (s <= 1) return 'prod'; 
                if (s === 2) return 'logistics'; 
                if (s <= 4) return 'finance'; 
                return 'law';
            }
        }
    }
    return 'prod';
}

function setViewMode(mode) {
    viewMode = mode; 
    localStorage.setItem('korda_view_mode', mode);
    
    const bList = document.getElementById('viewListBtn'); 
    if (bList) { 
        bList.style.background = mode === 'list' ? 'var(--card-bg)' : 'transparent'; 
        bList.style.boxShadow = mode === 'list' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'; 
    }
    
    const bKanban = document.getElementById('viewKanbanBtn'); 
    if (bKanban) { 
        bKanban.style.background = mode === 'kanban' ? 'var(--card-bg)' : 'transparent'; 
        bKanban.style.boxShadow = mode === 'kanban' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'; 
    }
    
    const bTL = document.getElementById('viewTimelineBtn'); 
    if (bTL) { 
        bTL.style.background = mode === 'timeline' ? 'var(--card-bg)' : 'transparent'; 
        bTL.style.boxShadow = mode === 'timeline' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'; 
    }
    
    renderDashboard();
}

function generateCardHTML(p) {
    let bC = `status-${p.status}`;
    let bT = { 'active': 'В работе', 'archive': 'В архиве', 'canceled': 'Отменен' }[p.status];
    let cC = "";
    let oB = "";
    
    if (p.status === 'active' && p.progress === 100) { 
        bC = 'status-completed'; 
        bT = 'ГОТОВО'; 
    } else if (p.isOverdue) { 
        cC = "style='border-color: var(--danger); box-shadow: 0 4px 15px rgba(239,68,68,0.15);'"; 
        oB = `<span style="background:var(--danger);color:white;display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:6px;font-size:11px;font-weight:700;margin-bottom:16px;margin-left:8px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg> ПРОСРОЧКА</span>`; 
    }
    
    let archiveHtml = '';
    if (p.status === 'archive' && p.archive_details && p.archive_details.folder) { 
        archiveHtml = `
        <div style="margin-top: 12px; font-size: 11px; background: rgba(30, 58, 138, 0.05); padding: 8px; border-radius: 8px; border: 1px solid rgba(30, 58, 138, 0.1);">
            <div style="font-weight: 600; margin-bottom: 4px;">🗄 Физический архив:</div>
            Стеллаж: <b>${p.archive_details.rack}</b> | Папка: <b>${p.archive_details.folder}</b><br>
            <span style="color: var(--secondary)">Отправлен: ${p.archive_details.date}</span>
        </div>`; 
    }
    
    return `
    <div class="project-card fade-in" ${cC} onclick="openProject(${p.id})">
        <div><span class="status-badge ${bC}">${bT}</span>${oB}</div>
        <h3>${p.name}</h3>
        <p>Договор: ${p.contract}</p>
        ${archiveHtml}
        <div class="card-progress">
            <div class="card-progress-fill" style="width: ${p.progress}%"></div>
        </div>
    </div>`;
}

function renderDashboard() {
    const list = document.getElementById('projectsList');
    const kanban = document.getElementById('kanbanBoard');
    const timeline = document.getElementById('timelineBoard');
    const sInput = document.getElementById('searchInput'); 
    const q = sInput ? sInput.value.toLowerCase() : '';
    
    // ИНЖЕКЦИЯ КНОПКИ ЭКСПОРТА ПРОЕКТОВ В EXCEL (ТЗ 2.7.4)
    const dashHeader = document.querySelector('#dashboardView .header') || document.querySelector('#dashboardView h2')?.parentElement;
    if (dashHeader && !document.getElementById('btnExportProjects')) {
        dashHeader.insertAdjacentHTML('beforeend', `<button id="btnExportProjects" class="btn-success no-print" style="margin-left:auto; padding: 6px 12px; font-size: 12px;" onclick="if(typeof exportDataToExcel === 'function') exportDataToExcel(projectsDB, 'Реестр_Проектов')">📊 Экспорт в Excel</button>`);
    }

    let filt = projectsDB.filter(p => p.status === currentTab && (p.name.toLowerCase().includes(q) || p.contract.toLowerCase().includes(q)));
    
    if (currentDepartmentFilter && currentTab === 'active') {
        filt = filt.filter(p => {
            const st = getProjectKanbanStage(p);
            if (currentDepartmentFilter === "Конструкторское бюро" || currentDepartmentFilter === "Производство и ОТК") return st === 'prod';
            if (currentDepartmentFilter === "Менеджер") return st === 'logistics' || st === 'finance';
            if (currentDepartmentFilter === "Бухгалтерия") return st === 'finance';
            if (currentDepartmentFilter === "Юрист") return st === 'law';
            return false;
        });
    }
    
    filt.forEach(p => p.isOverdue = checkOverdue(p)); 
    
    if (currentTab === 'active') {
        filt.sort((a, b) => (b.isOverdue ? 1 : 0) - (a.isOverdue ? 1 : 0));
    }
    
    if (list) list.style.display = 'none'; 
    if (kanban) kanban.style.display = 'none'; 
    if (timeline) timeline.style.display = 'none';
    
    if (viewMode === 'list') {
        if (list) { 
            list.style.display = 'grid'; 
            if (filt.length === 0) {
                list.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--secondary); padding: 40px;">Нет проектов.</div>`;
            } else {
                list.innerHTML = filt.map(generateCardHTML).join(''); 
            }
        }
    } else if (viewMode === 'kanban') {
        if (kanban) {
            kanban.style.display = 'flex'; 
            const c = { 'prod': '', 'logistics': '', 'finance': '', 'law': '', 'ready': '' };
            
            filt.forEach(p => { 
                const st = getProjectKanbanStage(p); 
                if (c[st] !== undefined) c[st] += generateCardHTML(p); 
            });
            
            if (filt.length === 0) {
                kanban.innerHTML = `<div style="width: 100%; text-align: center; color: var(--secondary); padding: 40px;">Нет проектов.</div>`;
            } else {
                kanban.innerHTML = `
                <div class="kanban-column"><div class="kanban-header">1. Пр-во и КБ <span>${(c['prod'].match(/project-card/g)||[]).length}</span></div>${c['prod']}</div>
                <div class="kanban-column"><div class="kanban-header">2. Логистика <span>${(c['logistics'].match(/project-card/g)||[]).length}</span></div>${c['logistics']}</div>
                <div class="kanban-column"><div class="kanban-header">3. Финансы <span>${(c['finance'].match(/project-card/g)||[]).length}</span></div>${c['finance']}</div>
                <div class="kanban-column"><div class="kanban-header">4. Юристы <span>${(c['law'].match(/project-card/g)||[]).length}</span></div>${c['law']}</div>
                <div class="kanban-column" style="border-color: var(--success); background: rgba(16, 185, 129, 0.02);"><div class="kanban-header" style="color: var(--success);">5. Готово <span>${(c['ready'].match(/project-card/g)||[]).length}</span></div>${c['ready']}</div>`;
            }
        }
    } else if (viewMode === 'timeline') {
        if (timeline) {
            timeline.style.display = 'block';
            if (filt.length === 0) {
                timeline.innerHTML = `<div style="width: 100%; text-align: center; color: var(--secondary); padding: 40px;">Нет проектов.</div>`;
            } else {
                timeline.innerHTML = filt.map(p => {
                    const startD = new Date(p.id).toLocaleDateString('ru-RU'); 
                    const dKeys = Object.keys(p.deadlines || {}); 
                    const endD = dKeys.length > 0 ? p.deadlines[dKeys[dKeys.length-1]] : 'Дедлайн не задан';
                    return `
                    <div class="tl-row fade-in" onclick="openProject(${p.id})">
                        <div class="tl-name">${p.name}</div>
                        <div class="tl-date">${startD}</div>
                        <div class="tl-bar-bg">
                            <div class="tl-bar-fill ${p.progress===100?'done':''}" style="width:${p.progress}%"></div>
                        </div>
                        <div class="tl-date" style="color:var(--danger)">${endD}</div>
                    </div>`;
                }).join('');
            }
        }
    }
}

function switchTab(tab) { 
    currentTab = tab; 
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active')); 
    if (event && event.target) event.target.classList.add('active'); 
    renderDashboard(); 
}

function filterProjects() { 
    renderDashboard(); 
}

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
    
    const filt = documentsDB.filter(d => d.type === currentDocTab);
    
    if (filt.length === 0) { 
        container.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--secondary); padding: 30px;">В этой папке нет документов.</td></tr>`; 
        return; 
    }
    
    container.innerHTML = filt.map(d => {
        let statusBadge = d.status === 'registered' 
            ? '<span class="status-badge" style="background: rgba(16, 185, 129, 0.1); color: var(--success);">Зарегистрирован</span>' 
            : '<span class="status-badge" style="background: var(--bg); color: var(--secondary);">В архиве</span>';
            
        let fileLink = d.file_url 
            ? `<a href="${d.file_url}" target="_blank" style="color:var(--primary); font-weight:600; text-decoration:none;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle; margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>Открыть</a>` 
            : `<button class="btn-secondary" style="padding:4px 8px; font-size:11px;" onclick="uploadDocFile(${d.id})">Прикрепить</button>`;
            
        return `
        <tr>
            <td style="font-weight:600;">${d.number}</td>
            <td>${d.d_date}</td>
            <td>${d.correspondent || '-'}</td>
            <td>${d.subject}</td>
            <td>${statusBadge}</td>
            <td>${fileLink}</td>
        </tr>`;
    }).join('');
}

async function submitDocument() {
    const type = document.getElementById('docType').value; 
    const number = document.getElementById('docNumber').value; 
    const dDate = document.getElementById('docDate').value; 
    const corr = document.getElementById('docCorrespondent').value; 
    const subj = document.getElementById('docSubject').value;
    
    if (!number || !subj) return alert("Заполните Номер и Тему!");
    
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

// ==========================================
// 4. СОГЛАСОВАНИЯ (БИЗНЕС-ПРОЦЕССЫ)
// ==========================================

let currentApprTab = 'pending';

function switchApprTab(tab) {
    currentApprTab = tab;
    document.getElementById('tabApprPending').classList.toggle('active', tab === 'pending');
    document.getElementById('tabApprCompleted').classList.toggle('active', tab === 'completed');
    renderApprovals();
}

function renderApprovals() {
    const container = document.getElementById('approvalsListContainer'); 
    if (!container) return;
    
    const filt = approvalsDB.filter(a => {
        if (currentApprTab === 'pending') return a.status === 'pending';
        return a.status === 'completed' || a.status === 'rejected';
    });

    if (filt.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding:30px; color:var(--secondary);">Нет запущенных процессов.</div>`;
        return;
    }

    container.innerHTML = filt.map(a => {
        let routeHtml = '';
        const amI_Current = (a.status === 'pending' && a.route[a.current_step] === currentUser.name);
        
        a.route.forEach((person, idx) => {
            let cls = 'approval-step';
            if (idx < a.current_step) cls += ' done';
            else if (idx === a.current_step && a.status === 'pending') cls += ' active';
            else if (idx === a.current_step && a.status === 'rejected') cls += ' rejected';
            
            routeHtml += `<div class="${cls}">${person}</div>`;
            if (idx < a.route.length - 1) routeHtml += `<div class="approval-arrow">→</div>`;
        });

        let actionBtns = '';
        if (amI_Current || currentUser.role === 'Директор') {
            actionBtns = `
            <div style="display:flex; gap:8px; margin-top: 15px;">
                <button class="btn-success" onclick="processApprovalStep(${a.id}, 'approve')">✅ Согласовать</button>
                <button class="btn-danger" onclick="processApprovalStep(${a.id}, 'reject')">❌ Отклонить</button>
            </div>`;
        }
        
        let histHtml = '';
        if (a.history.length > 0) {
            histHtml = `<div style="margin-top:12px; font-size:11px; color:var(--secondary); background:var(--bg); padding:8px; border-radius:8px;">` 
                       + a.history.map(h => `<div>${h}</div>`).join('') + 
                       `</div>`;
        }

        return `
        <div class="approval-card">
            <div style="font-weight:600; font-size:16px;">${a.title}</div>
            <div style="font-size:12px; color:var(--secondary); margin-top:4px;">
                Документ: <a href="#" style="color:var(--primary);">${a.item_link}</a> | Автор: ${a.author}
            </div>
            <div class="approval-route">${routeHtml}</div>
            ${histHtml}
            ${a.status === 'pending' ? actionBtns : ''}
        </div>`;
    }).join('');
}

function openCreateApprovalModal() {
    const sel = document.getElementById('apprRoles');
    if (sel) {
        sel.innerHTML = allUsersDB.filter(u => u.status === 'approved').map(u => 
            `<label style="display:flex; align-items:center; gap:5px;"><input type="checkbox" value="${u.name}" class="appr-cb"> ${u.name} (${u.role})</label>`
        ).join('');
    }
    document.getElementById('createApprovalModal').style.display = 'flex';
}

async function submitApproval() {
    const title = document.getElementById('apprTitle').value;
    const link = document.getElementById('apprLink').value;
    const route = Array.from(document.querySelectorAll('.appr-cb:checked')).map(cb => cb.value);
    
    if (!title || route.length === 0) return alert("Заполните название и выберите маршрут");
    
    await apiCall('/approvals', 'POST', { 
        title: title, 
        item_link: link, 
        route: route, 
        author: currentUser.name 
    });
    
    document.getElementById('createApprovalModal').style.display = 'none';
    await loadApprovals(); 
    renderApprovals();
}

async function processApprovalStep(id, action) {
    const a = approvalsDB.find(x => x.id === id);
    const now = new Date(); 
    const tStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
    
    if (action === 'approve') {
        a.history.push(`✅ ${currentUser.name} согласовал(а) (${tStr})`);
        a.current_step++;
        if (a.current_step >= a.route.length) a.status = 'completed';
    } else {
        const reason = prompt("Причина отклонения:");
        a.history.push(`❌ ${currentUser.name} отклонил(а): ${reason || 'Без причины'} (${tStr})`);
        a.status = 'rejected';
    }
    
    await apiCall(`/approvals/${a.id}`, 'PUT', a);
    await loadApprovals(); 
    renderApprovals();
}

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
    if (!name) return alert("Введите название чата");
    
    const cbs = document.querySelectorAll('.new-chat-cb:checked'); 
    const participants = Array.from(cbs).map(cb => cb.value); 
    participants.push(currentUser.name); 
    
    await apiCall('/chats', 'POST', { name: name, creator: currentUser.name, participants: participants }); 
    document.getElementById('createChatModal').style.display = 'none'; 
    await loadGlobalChats();
}

async function deleteCurrentChat() {
    if (!currentGlobalChatId) return; 
    if (!confirm("Вы уверены, что хотите удалить этот чат? Восстановить сообщения будет невозможно.")) return;
    
    await apiCall(`/chats/${currentGlobalChatId}`, 'DELETE'); 
    currentGlobalChatId = null;
    
    document.getElementById('mChatTitle').innerText = "Выберите чат слева"; 
    document.getElementById('messengerInputArea').style.display = 'none'; 
    document.getElementById('messengerMessages').innerHTML = ''; 
    document.getElementById('btnDeleteChat').style.display = 'none'; 
    await loadGlobalChats();
}

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
    
    if (!title || !mDate || !mTime) return alert("Заполните тему, дату и время");
    
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
    alert('Протокол сохранен!'); 
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

// ==========================================
// 8. ПОРУЧЕНИЯ И ТАЙМЕРЫ
// ==========================================

let currentTaskTab = 'active';

function switchTaskTab(tab) {
    currentTaskTab = tab;
    document.getElementById('tabTaskActive').classList.toggle('active', tab === 'active');
    document.getElementById('tabTaskCompleted').classList.toggle('active', tab === 'completed');
    renderTasks();
}

// ФУНКЦИЯ ДЛЯ ВЫЧИСЛЕНИЯ ОСТАВШЕГОСЯ ВРЕМЕНИ ПО ПОРУЧЕНИЮ
function getTaskTimeLeft(dateStr) {
    if (!dateStr) return '';
    const pts = dateStr.split(' ');
    const dPts = pts[0].split('.');
    let hrs = 0, mins = 0;
    
    if (pts[1]) {
        const tPts = pts[1].split(':');
        hrs = parseInt(tPts[0] || 0);
        mins = parseInt(tPts[1] || 0);
    }
    
    // В JS месяцы начинаются с 0
    const deadlineDate = new Date(dPts[2], dPts[1] - 1, dPts[0], hrs, mins);
    const now = new Date();
    const diff = deadlineDate - now;

    if (diff <= 0) return `<span style="color:var(--danger); font-weight:700;">⚠️ Просрочено</span>`;

    const dLeft = Math.floor(diff / (1000 * 60 * 60 * 24));
    const hLeft = Math.floor((diff / (1000 * 60 * 60)) % 24);
    const mLeft = Math.floor((diff / 1000 / 60) % 60);

    let str = '⏳ Осталось: ';
    if (dLeft > 0) str += `${dLeft} дн. `;
    if (hLeft > 0 || dLeft > 0) str += `${hLeft} ч. `;
    str += `${mLeft} мин.`;

    return `<span style="color:#f59e0b; font-weight:600;">${str}</span>`;
}

// Запускаем фоновое обновление таймеров в поручениях раз в минуту
setInterval(() => {
    document.querySelectorAll('.task-countdown').forEach(el => {
        const dl = el.getAttribute('data-deadline');
        if (dl) el.innerHTML = getTaskTimeLeft(dl);
    });
}, 60000);

function renderTasks() {
    const container = document.getElementById('tasksListContainer'); 
    if (!container) return;
    
    const myTasks = tasksDB.filter(t => t.author === currentUser.name || t.executor === currentUser.name || currentUser.role === 'Директор');
    const filt = myTasks.filter(t => t.status === currentTaskTab);
    
    if (filt.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding:30px; color:var(--secondary);">Нет поручений в этой категории.</div>`;
        return;
    }
    
    container.innerHTML = filt.map(t => {
        let actionBtn = '';
        if (t.status === 'active' && (t.executor === currentUser.name || currentUser.role === 'Директор')) {
            actionBtn = `<button class="btn-success" style="padding: 6px 12px; font-size: 12px;" onclick="toggleTaskStatus(${t.id}, 'completed')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;"><polyline points="20 6 9 17 4 12"></polyline></svg>Выполнено</button>`;
        } else if (t.status === 'completed' && (t.author === currentUser.name || currentUser.role === 'Директор')) {
            actionBtn = `<button class="btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="toggleTaskStatus(${t.id}, 'active')">Вернуть в работу</button>`;
        }
        
        let timeBadge = t.status === 'active' 
            ? `<div class="task-countdown" data-deadline="${t.deadline}" style="font-size: 11px; background: rgba(245, 158, 11, 0.1); padding: 4px 8px; border-radius: 6px; display: inline-block; margin-top: 6px;">${getTaskTimeLeft(t.deadline)}</div>` 
            : '';
        
        return `
        <div style="background:var(--card-bg); border:1px solid var(--border); border-radius:16px; padding:20px; box-shadow:0 2px 10px rgba(0,0,0,0.02);">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
                <div>
                    <div style="font-weight:600; font-size:16px;">${t.title}</div>
                    ${timeBadge}
                </div>
                <div style="color:var(--danger); font-weight:600; font-size:12px; text-align:right;">Дедлайн:<br>${t.deadline}</div>
            </div>
            <div style="font-size:14px; color:var(--text); margin-bottom:15px;">${t.description}</div>
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-size:12px; color:var(--secondary);">Поручил: <b>${t.author}</b> → Исполнитель: <b>${t.executor}</b></div>
                ${actionBtn}
            </div>
        </div>`;
    }).join('');
}

function openCreateTaskModal() {
    // Календарь с выбором минут и часов
    flatpickr("#taskDeadline", { 
        locale: "ru", 
        enableTime: true, 
        time_24hr: true, 
        dateFormat: "d.m.Y H:i",
        minDate: "today"
    });
    
    const sel = document.getElementById('taskExecutor');
    if (sel) {
        sel.innerHTML = '<option value="" disabled selected>Выберите исполнителя</option>' + allUsersDB.filter(u => u.status === 'approved').map(u => `<option value="${u.name}">${u.name} (${u.role})</option>`).join('');
    }
    document.getElementById('createTaskModal').style.display = 'flex';
}

async function submitTask() {
    const title = document.getElementById('taskTitle').value;
    const desc = document.getElementById('taskDesc').value;
    const exec = document.getElementById('taskExecutor').value;
    const dead = document.getElementById('taskDeadline').value;
    
    if (!title || !exec || !dead) return alert("Заполните Суть, Исполнителя и Дедлайн");
    
    const res = await apiCall('/tasks', 'POST', { 
        title: title, 
        description: desc, 
        author: currentUser.name, 
        executor: exec, 
        deadline: dead 
    });
    
    if (!res || res.status !== 'success') {
        alert("⚠️ Ошибка сохранения! Пожалуйста, убедитесь, что вы перезапустили сервер (базу данных).");
        return;
    }
    
    document.getElementById('createTaskModal').style.display = 'none';
    document.getElementById('taskTitle').value = ''; 
    document.getElementById('taskDesc').value = '';
    
    await loadTasks(); 
    renderTasks();
}

async function toggleTaskStatus(id, status) {
    await apiCall(`/tasks/${id}`, 'PUT', { status: status });
    await loadTasks(); 
    renderTasks();
}

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
    
    if (!title || !content) return alert("Заполните Название и Текст документа");
    if (roles.length === 0) return alert("Выберите, для кого обязателен регламент");
    
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
