// ==========================================
// 2. ОТРИСОВКА ДАШБОРДА (ПРОЕКТЫ) И ПОИСК
// ==========================================

// ГЛАВНАЯ ФУНКЦИЯ ПОИСКА (Вызывается из topbar.html)
function filterProjects() {
    const dashView = document.getElementById('dashboardView');
    const docsView = document.getElementById('documentsView');
    const clientsView = document.getElementById('clientsView');

    if (dashView && dashView.style.display === 'block') {
        renderDashboard(); 
    } 
    else if (docsView && docsView.style.display === 'block') {
        if (typeof renderDocuments === 'function') renderDocuments(); 
    }
    else if (clientsView && clientsView.style.display === 'block') {
        if (typeof renderClients === 'function') renderClients(); 
    }
}

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
        <p style="font-size: 12px; color: var(--secondary); margin-top: 4px;">Заказчик: ${p.client}</p>
        ${archiveHtml}
        <div class="card-progress" style="margin-top: 12px;">
            <div class="card-progress-fill" style="width: ${p.progress}%"></div>
        </div>
    </div>`;
}

function renderDashboard() {
    const list = document.getElementById('projectsList');
    const kanban = document.getElementById('kanbanBoard');
    const timeline = document.getElementById('timelineBoard');
    const sInput = document.getElementById('searchInput'); 
    const q = sInput ? sInput.value.toLowerCase().trim() : '';
    
    // БАЗОВЫЙ ФИЛЬТР ПО ТАБАМ (Активные/Архив/Отмена)
    let filt = projectsDB.filter(p => p.status === currentTab);
    
    // ЕСЛИ ЕСТЬ ТЕКСТ В ПОИСКЕ - ИЩЕМ ВЕЗДЕ (Бронебойный поиск)
    if (q) {
        filt = filt.filter(p => {
            const n = String(p.name || '').toLowerCase();
            const c = String(p.contract || '').toLowerCase();
            const cl = String(p.client || '').toLowerCase();
            const m = String(p.manager || '').toLowerCase();
            return n.includes(q) || c.includes(q) || cl.includes(q) || m.includes(q);
        });
    } 
    // ЕСЛИ ПОИСКА НЕТ - ПРИМЕНЯЕМ ФИЛЬТР ПО ОТДЕЛАМ
    else if (currentDepartmentFilter && currentTab === 'active') {
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
                list.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--secondary); padding: 40px;">Ничего не найдено.</div>`;
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
                kanban.innerHTML = `<div style="width: 100%; text-align: center; color: var(--secondary); padding: 40px;">Ничего не найдено.</div>`;
            } else {
                kanban.innerHTML = `
                <div class="kanban-column"><div class="kanban-header">1. Пр-во и КБ <span>${(c['prod'].match(/project-card/g)||[]).length}</span></div>${c['prod']}</div>
                <div class="kanban-column"><div class="kanban-header">2. Логистика <span>${(c['logistics'].match(/project-card/g)||[]).length}</span></div>${c['logistics']}</div>
                <div class="kanban-column"><div class="kanban-header">3. Финансы <span>${(c['finance'].match(/project-card/g)||[]).length}</span></div>${c['finance']}</div>
                <div class="kanban-column"><div class="kanban-header">4. Юристы <span>${(c['law'].match(/project-card/g)||[]).length}</span></div>${c['law']}</div>
                <div class="kanban-column" style="border-color: var(--success);"><div class="kanban-header" style="color: var(--success);">5. Готово <span>${(c['ready'].match(/project-card/g)||[]).length}</span></div>${c['ready']}</div>`;
            }
        }
    } else if (viewMode === 'timeline') {
        if (timeline) {
            timeline.style.display = 'block';
            if (filt.length === 0) {
                timeline.innerHTML = `<div style="width: 100%; text-align: center; color: var(--secondary); padding: 40px;">Ничего не найдено.</div>`;
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