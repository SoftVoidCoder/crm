const API_URL = '/api';
let currentUser = JSON.parse(localStorage.getItem('korda_session'));
let projectsDB = [];
let clientsDB = [];
let allUsersDB = []; 
let meetingsDB = []; 
let emailsDB = [];   
let documentsDB = []; 
let tasksDB = [];      
let knowledgeDB = [];  
let approvalsDB = []; 
let claimsDB = [];
let courtCasesDB = [];

let currentTab = 'active';
let currentProjectId = null;
let currentLegalTab = 'claims';
let statusChartObj = null;
let progressChartObj = null;
let currentDepartmentFilter = null; 
let viewMode = localStorage.getItem('korda_view_mode') || 'list'; 
let isChatVisible = localStorage.getItem('korda_chat_visible') !== 'false'; 

let isFirstLoad = true;
let seenToastIds = new Set();
let canvas, ctx, isDrawing = false;

const availableRoles = ['Конструкторское бюро', 'Производство и ОТК', 'Менеджер', 'Бухгалтерия', 'Юрист', 'Директор'];

window.exchangeRates = { RUB: 1, USD: 90, EUR: 100, CNY: 12 };

async function fetchExchangeRates() {
    try {
        const res = await fetch('https://www.cbr-xml-daily.ru/daily_json.js');
        const data = await res.json();
        window.exchangeRates = {
            RUB: 1,
            USD: data.Valute.USD.Value,
            EUR: data.Valute.EUR.Value,
            CNY: data.Valute.CNY.Value
        };
    } catch (e) {
        console.error('Ошибка парсинга курсов ЦБ', e);
    }
}

const checklistTemplate = [
    { title: "1. Производство", responsibles: "Конструкторское бюро, Производство и ОТК, Директор", tasks: ["КД разработана, создана и передана на производство.", "Производство приняло КД и приступило к исполнению.", "Продукция произведена и успешно проверена ОТК.", "Готовая продукция отгружена Заказчику."] },
    { title: "2. Техническая и конструкторская документация (КД)", responsibles: "Конструкторское бюро", tasks: ["Финальная конструкторская документация (с учетом всех изменений) согласована, а исполнительная документация сформирована, прошита и передана Заказчику.", "Получена отметка Заказчика о приемке технической/исполнительной документации."] },
    { title: "3. Логистика и сдача-приемка (Акты и КС)", responsibles: "Менеджер", tasks: ["Оборудование / товар доставлены на объект (подписаны ТТН, транспортные накладные).", "Подписан полный комплект приемо-сдаточной документации со стороны Заказчика (акты входного контроля, КСК, ведомости ЗИП, формы КС-2 и КС-3, акты ПНР и ввода в эксплуатацию и др.)."] },
    { title: "4. Бухгалтерские закрывающие документы", responsibles: "Менеджер, Бухгалтерия", tasks: ["Оригиналы подписанных Заказчиком закрывающих документов (УПД, ТОРГ-12, Счета-фактуры) получены и сданы в бухгалтерию.", "Подписан двусторонний Акт сверки взаиморасчетов по договору (без расхождений)."] },
    { title: "5. Финансы и дебиторская задолженность", responsibles: "Менеджер, Бухгалтерия", tasks: ["Все финансовые расчеты по сделке завершены (финальный платеж поступил, дебиторская задолженность погашена).", "Банковские гарантии (авансовые, на исполнение) возвращены банком или срок их действия истек."] },
    { title: "6. Юридические вопросы и гарантия", responsibles: "Юрист", tasks: ["Возможные претензии и штрафы урегулированы. Оригинал Договора со всеми доп. соглашениями сдан в архив."] }
];

async function apiCall(endpoint, method = 'GET', body = null) {
    const options = { method, headers: {} };
    if (body instanceof FormData) { options.body = body; } 
    else if (body) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    try { const res = await fetch(API_URL + endpoint, options); return await res.json(); } 
    catch (e) { return null; }
}

async function loadProjects() { 
    const isHead = currentUser.is_head || 0;
    const url = `/projects?user_name=${encodeURIComponent(currentUser.name)}&user_role=${encodeURIComponent(currentUser.role)}&is_head=${isHead}`;
    const data = await apiCall(url); 
    if (data) projectsDB = data; 
}
async function loadClients() { const data = await apiCall('/clients'); if (data) clientsDB = data; }
async function loadAllUsers() { const data = await apiCall('/users/all'); if (data) allUsersDB = data; }
async function loadMeetings() { const data = await apiCall('/meetings'); if (data) meetingsDB = data; }
async function loadDocuments() { const data = await apiCall('/documents'); if (data) documentsDB = data; }
async function loadTasks() { const data = await apiCall('/tasks'); if(data) { tasksDB = data; if(typeof checkOverdueTasksGlobal === 'function') checkOverdueTasksGlobal(); } }
async function loadKnowledge() { const data = await apiCall('/knowledge'); if(data) knowledgeDB = data; }
async function loadApprovals() { const data = await apiCall('/approvals'); if(data) approvalsDB = data; }
async function loadClaims() { const data = await apiCall('/claims'); if (data) claimsDB = data; }
async function loadCourtCases() { const data = await apiCall('/court_cases'); if (data) courtCasesDB = data; }

// === КЛИЕНТ WEBSOCKET ===
let ws;
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    
    ws.onmessage = async (event) => {
        if(!currentUser || currentUser.status !== 'approved') return;
        const data = JSON.parse(event.data);
        
        if (data.type === 'projects') {
            await loadProjects();
            if(document.getElementById('dashboardView') && document.getElementById('dashboardView').style.display === 'block') { 
                if (viewMode === 'kanban') renderKanbanBoard();
                else if (typeof renderDashboard === 'function') renderDashboard(); 
                
                if(document.getElementById('analyticsView') && document.getElementById('analyticsView').style.display === 'block' && typeof drawCharts === 'function') drawCharts(); 
            }
            else if(document.getElementById('projectView') && document.getElementById('projectView').style.display === 'block') { 
                if (typeof updateChecklistUI === 'function') updateChecklistUI(); 
                if (typeof renderChat === 'function') renderChat(); 
                if (typeof renderFiles === 'function') renderFiles(); 
            }
            if (typeof renderNotifications === 'function') renderNotifications();
        } 
        else if (data.type === 'tasks') {
            await loadTasks();
            if(document.getElementById('tasksView') && document.getElementById('tasksView').style.display === 'block' && typeof renderTasks === 'function') renderTasks();
            if(document.getElementById('kpiView') && document.getElementById('kpiView').style.display === 'block' && typeof renderKPI === 'function') renderKPI();
        }
        else if (data.type === 'chats') {
            if (typeof loadGlobalChats === 'function') await loadGlobalChats();
            const messView = document.getElementById('messengerView');
            if(messView && messView.style.display === 'block') {
                if (typeof currentGlobalChatId !== 'undefined' && currentGlobalChatId !== null) {
                    if (typeof loadGlobalMessages === 'function') loadGlobalMessages(currentGlobalChatId, false);
                } else {
                    if (typeof renderGlobalChats === 'function') renderGlobalChats();
                }
            }
        }
        else if (data.type === 'documents') {
            await loadDocuments();
            if(document.getElementById('documentsView') && document.getElementById('documentsView').style.display === 'block' && typeof renderDocuments === 'function') renderDocuments();
        }
        else if (data.type === 'approvals') {
            await loadApprovals();
            if(document.getElementById('approvalsView') && document.getElementById('approvalsView').style.display === 'block' && typeof renderApprovals === 'function') renderApprovals();
        }
        else if (data.type === 'meetings') {
            await loadMeetings();
            if(document.getElementById('meetingsView') && document.getElementById('meetingsView').style.display === 'block' && typeof renderMeetings === 'function') renderMeetings();
        }
        else if (data.type === 'knowledge') {
            await loadKnowledge();
            if(document.getElementById('knowledgeView') && document.getElementById('knowledgeView').style.display === 'block' && typeof renderKnowledge === 'function') renderKnowledge();
        }
        else if (data.type === 'claims') {
            await loadClaims();
            if(document.getElementById('claimsView') && document.getElementById('claimsView').style.display === 'block' && typeof renderClaims === 'function' && currentLegalTab === 'claims') renderClaims();
        }
        else if (data.type === 'court_cases') {
            await loadCourtCases();
            if(document.getElementById('claimsView') && document.getElementById('claimsView').style.display === 'block' && typeof renderCourts === 'function' && currentLegalTab === 'courts') renderCourts();
        }
    };

    ws.onclose = () => { setTimeout(connectWebSocket, 5000); };
}

function checkOverdueTasksGlobal() {
    if (typeof tasksDB === 'undefined' || !currentUser) return;
    const today = new Date(); today.setHours(0,0,0,0);
    let overdueCount = 0;
    tasksDB.forEach(t => {
        if (t.status === 'active' && (t.executor === currentUser.name || t.executor.includes(currentUser.name))) {
            const pts = (t.deadline || '').split('.');
            if (pts.length === 3) {
                const d = new Date(pts[2], pts[1]-1, pts[0]);
                if (d < today) overdueCount++;
            }
        }
    });
    const ctrl = document.getElementById('topbarTaskControl');
    const countEl = document.getElementById('topbarOverdueCount');
    if (ctrl && countEl) {
        if (overdueCount > 0) { ctrl.style.display = 'flex'; countEl.innerText = overdueCount; }
        else { ctrl.style.display = 'none'; }
    }
}

window.onload = async () => {
    document.documentElement.dataset.theme = localStorage.getItem('theme') || 'light';
    const path = window.location.pathname;

    if (currentUser && currentUser.status === 'approved') {
        if (path.includes('login.html') || path.includes('register.html') || path === '/' || path === '') {
            window.location.href = '/app'; return;
        }
        await fetchExchangeRates();
        await loadProjects(); await loadClients(); await loadAllUsers(); await loadMeetings(); await loadDocuments(); await loadTasks(); await loadKnowledge(); await loadApprovals(); await loadClaims(); await loadCourtCases();
        
        if (document.getElementById('appLayout')) {
            document.getElementById('appLayout').style.display = 'flex';
            
            let titleStr = `${currentUser.name} (${currentUser.role})`;
            if (currentUser.is_head === 1 && currentUser.role !== 'Директор') titleStr += " 👑 Руководитель";
            const uNameEl = document.getElementById('topbarUserName');
            if (uNameEl) uNameEl.innerText = titleStr;
            
            const uInitEl = document.getElementById('topbarUserInitials');
            if (uInitEl && currentUser.name) {
                const parts = currentUser.name.split(' ');
                uInitEl.innerText = parts.length > 1 ? (parts[0][0] + parts[1][0]).toUpperCase() : parts[0][0].toUpperCase();
            }
            
            const adminBtn = document.getElementById('adminBtn');
            if (adminBtn) adminBtn.style.display = currentUser.role === 'Директор' ? 'flex' : 'none';
            
            const kpiBtn = document.getElementById('navKpi');
            if (kpiBtn) kpiBtn.style.display = currentUser.role === 'Директор' ? 'flex' : 'none';
            
            if (currentUser.role === 'Директор') {
                const pUsers = await apiCall('/users/pending');
                const badge = document.getElementById('pendingBadge');
                if (badge && pUsers && pUsers.length > 0) { badge.innerText = pUsers.length; badge.style.display = 'inline-block'; }
            }

            if (typeof Chart !== 'undefined') Chart.register(ChartDataLabels);
            if (typeof setViewMode === 'function') setViewMode(viewMode);
            if (typeof renderNotifications === 'function') renderNotifications();
            if (typeof initSignaturePad === 'function') initSignaturePad(); 
            checkOverdueTasksGlobal();
            if (typeof navigateTo === 'function') navigateTo('dashboard');
            
            connectWebSocket();
            initClaimsUI();
        }
    } else if (currentUser && currentUser.status === 'pending') {
        if (!path.includes('login.html') && !path.includes('register.html')) { window.location.href = 'login.html'; return; }
        if (path.includes('login.html')) { document.getElementById('loginFormCard').style.display = 'none'; document.getElementById('pendingCard').style.display = 'block'; }
    } else {
        if (!path.includes('login.html') && !path.includes('register.html')) { window.location.href = 'login.html'; }
    }
};

setInterval(async () => {
    if(!currentUser || currentUser.status !== 'approved') return;
    const res = await apiCall(`/status/${currentUser.email}`);
    if (res && res.status === 'banned') { 
        customAlert("🔒 Ваш аккаунт был заблокирован администратором.").then(() => logout()); 
        return; 
    }
    if (res && res.is_head !== undefined) {
        currentUser.is_head = res.is_head;
        localStorage.setItem('korda_session', JSON.stringify(currentUser));
    }
    if (currentUser.role === 'Директор' && document.getElementById('appLayout')) {
        for (let i = 0; i < projectsDB.length; i++) {
            let p = projectsDB[i];
            if (p.status !== 'active' || !p.checklist) continue;
            const today = new Date(); today.setHours(0,0,0,0);
            let projectChanged = false;
            p.checklist.forEach((sec, sIdx) => {
                if (p.deadlines && p.deadlines[sIdx]) {
                    const pts = p.deadlines[sIdx].split('.');
                    if (pts.length === 3) {
                        const dDate = new Date(pts[2], pts[1]-1, pts[0]);
                        if (dDate < today) {
                            let secOk = true;
                            for (let t = 0; t < sec.tasks.length; t++) { 
                                if (!p.checkedState || !p.checkedState[`task_${sIdx}_${t}`] || p.checkedState[`task_${sIdx}_${t}`].startsWith('🟡')) secOk = false; 
                            }
                            const escKey = `esc_${sIdx}`;
                            if (!secOk && (!p.escalations || !p.escalations[escKey])) {
                                if (!p.escalations) p.escalations = {};
                                p.escalations[escKey] = true;
                                if(!p.logs) p.logs = [];
                                const now = new Date();
                                const timeStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
                                p.logs.unshift({ time: timeStr, user: "Система", action: `⚠️ АВТО-ЭСКАЛАЦИЯ: Просрочен этап "${sec.title}". Ответственные: ${sec.responsibles}. Уведомлен Директор.` });
                                projectChanged = true; 
                            }
                        }
                    }
                }
            });
            if (projectChanged) await apiCall(`/projects/${p.id}`, 'PUT', p);
        }
    }
}, 60000); 

function toggleTheme() {
    const n = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = n; localStorage.setItem('theme', n);
    if(document.getElementById('analyticsView') && document.getElementById('analyticsView').style.display === 'block' && typeof drawCharts === 'function') drawCharts();
}

// ==========================================
// МОДУЛЬ: ПРЕТЕНЗИОННАЯ РАБОТА (ЮРИСwwТЫ)
// ==========================================
function getLegalScaleIcon() {
    return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 16v2a4 4 0 0 1-4 4 4 4 0 0 1-4-4v-2"></path><path d="M12 4v12"></path><path d="M3 7h18"></path><path d="m7 7-3 5a3 3 0 0 0 6 0L7 7Z"></path><path d="m17 7-3 5a3 3 0 0 0 6 0l-3-5Z"></path></svg>`;
}

function getLegalCreateIcon() {
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>`;
}

function getLegalExportIcon() {
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path></svg>`;
}

function getLegalDocIcon() {
    return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7Z"></path><path d="M14 2v5h5"></path><path d="M9 13h6"></path><path d="M9 17h6"></path></svg>`;
}

function getLegalSectionTitle(title, subtitle = '') {
    return `
        <div class="legal-title-row">
            <div class="legal-icon legal-icon--hero">${getLegalScaleIcon()}</div>
            <div>
                <h2 class="legal-page-title">${title}</h2>
                ${subtitle ? `<p class="legal-page-subtitle">${subtitle}</p>` : ''}
            </div>
        </div>
    `;
}

function getLegalCreateButtonLabel(tab) {
    const text = tab === 'claims' ? 'Создать претензию' : 'Добавить дело';
    return `${getLegalCreateIcon()}<span>${text}</span>`;
}

function renderLegalToolbarButton(kind) {
    const isClaims = kind === 'claims';
    const fileName = isClaims ? 'Реестр_Претензий' : 'Реестр_Судебных_Дел';
    const source = isClaims ? 'claimsDB' : 'courtCasesDB';
    return `
        <button class="btn-secondary legal-export-btn no-print" onclick="exportDataToExcel(${source}, '${fileName}')">
            ${getLegalExportIcon()}
            <span>Экспорт в Excel</span>
        </button>
    `;
}

function initClaimsUI() {
    const sidebar = document.querySelector('.sidebar');
    if (sidebar && !document.getElementById('navClaims')) {
        const btn = document.createElement('a');
        btn.href = "#"; btn.id = "navClaims"; btn.className = "nav-item";
        btn.innerHTML = `${getLegalScaleIcon()}<span>Претензии и Суды</span>`;
        btn.onclick = (e) => { 
            e.preventDefault();
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            btn.classList.add('active');
            if (typeof navigateTo === 'function') navigateTo('claims'); 
            renderClaims();
        };
        sidebar.appendChild(btn);
    }

    const mainContent = document.querySelector('.main-content');
    if (mainContent && !document.getElementById('claimsView')) {
        const claimsView = document.createElement('div');
        claimsView.id = "claimsView"; claimsView.className = "fade-in legal-shell"; claimsView.style.display = "none";
        claimsView.innerHTML = `
<<<<<<< Updated upstream
            <div class="header" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h2 style="margin:0; color:var(--primary);">⚖️ Претензии и Суды</h2>
                <button id="btnCreateLegal" class="btn-primary" onclick="openCreateLegalModal()">+ Создать претензию</button>
            </div>
            <div style="display:flex; gap:10px; margin-bottom:20px;">
                <button id="tabLegalClaims" class="btn-secondary active" style="padding:6px 16px; font-size:13px;" onclick="switchLegalTab('claims')">Досудебные претензии</button>
                <button id="tabLegalCourts" class="btn-secondary" style="padding:6px 16px; font-size:13px;" onclick="switchLegalTab('courts')">Судебные дела</button>
=======
            <div class="legal-hero">
                ${getLegalSectionTitle('Претензии и Суды', 'Единый реестр досудебной и судебной работы')}
                <button id="btnCreateLegal" class="btn-primary legal-create-btn" onclick="openCreateLegalModal()">${getLegalCreateButtonLabel('claims')}</button>
            </div>
            <div class="legal-toolbar">
                <div class="legal-tabs">
                <button id="tabLegalClaims" class="btn-secondary active btn-sm" onclick="switchLegalTab('claims')">Досудебные претензии</button>
                <button id="tabLegalCourts" class="btn-secondary btn-sm" onclick="switchLegalTab('courts')">Судебные дела</button>
                </div>
                <div id="legalToolbarActions" class="legal-toolbar-actions"></div>
>>>>>>> Stashed changes
            </div>
            <div class="legal-board"><div id="legalListContainer"></div></div>
        `;
        mainContent.appendChild(claimsView);
    }

    if (!document.getElementById('createCourtModal')) {
        document.body.insertAdjacentHTML('beforeend', `
<<<<<<< Updated upstream
        <div id="createCourtModal" class="modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:9999;">
            <div class="modal-content fade-in" style="background:var(--bg); padding:25px; border-radius:12px; width:700px; max-width:95%; box-shadow:0 10px 25px rgba(0,0,0,0.2);">
                <h3 style="margin-top:0; color:var(--primary); margin-bottom:15px;">⚖️ Новое судебное дело</h3>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px; margin-bottom:20px;">
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Номер дела</label><input type="text" id="courtNum" class="auth-input" style="margin:0; width:100%;" placeholder="Например, А56-123/2024"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Суд</label><input type="text" id="courtName" class="auth-input" style="margin:0; width:100%;" placeholder="АС г. Санкт-Петербурга"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Истец</label><input type="text" id="courtPlain" class="auth-input" style="margin:0; width:100%;" value="ООО «КОРДА»"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Ответчик</label><input type="text" id="courtDef" class="auth-input" style="margin:0; width:100%;"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Сумма иска (₽)</label><input type="number" id="courtAmount" class="auth-input" style="margin:0; width:100%;"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Привязка к договору</label><select id="courtProj" class="auth-input" style="margin:0; width:100%;"></select></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Инстанция</label>
                        <select id="courtInst" class="auth-input" style="margin:0; width:100%;">
=======
        <div id="createCourtModal" class="modal modal-overlay-custom">
            <div class="modal-content fade-in modal-content-custom">
                <h3 class="legal-title legal-modal-title">${getLegalScaleIcon()}<span>Новое судебное дело</span></h3>
                <div class="form-grid">
                    <div><label class="form-label-custom">Номер дела</label><input type="text" id="courtNum" class="auth-input form-input-custom" placeholder="Например, А56-123/2024"></div>
                    <div><label class="form-label-custom">Суд</label><input type="text" id="courtName" class="auth-input form-input-custom" placeholder="АС г. Санкт-Петербурга"></div>
                    <div><label class="form-label-custom">Истец</label><input type="text" id="courtPlain" class="auth-input form-input-custom" value="ООО «КОРДА»"></div>
                    <div><label class="form-label-custom">Ответчик</label><input type="text" id="courtDef" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Сумма иска (₽)</label><input type="number" id="courtAmount" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Привязка к договору</label><select id="courtProj" class="auth-input form-input-custom"></select></div>
                    <div><label class="form-label-custom">Инстанция</label>
                        <select id="courtInst" class="auth-input form-input-custom">
>>>>>>> Stashed changes
                            <option value="Первая">Первая инстанция</option>
                            <option value="Апелляция">Апелляционная инстанция</option>
                            <option value="Кассация">Кассационная инстанция</option>
                        </select>
                    </div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Дата след. заседания</label><input type="date" id="courtHearing" class="auth-input" style="margin:0; width:100%;"></div>
                </div>
                <div style="display:flex; justify-content:flex-end; gap:10px; border-top:1px solid var(--border); padding-top:15px;">
                    <button class="btn-secondary" onclick="document.getElementById('createCourtModal').style.display='none'">Отмена</button>
                    <button class="btn-primary" onclick="submitNewCourt()">Сохранить дело</button>
                </div>
            </div>
        </div>`);
    }

    if (!document.getElementById('createClaimModal')) {
        document.body.insertAdjacentHTML('beforeend', `
<<<<<<< Updated upstream
        <div id="createClaimModal" class="modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:9999;">
            <div class="modal-content fade-in" style="background:var(--bg); padding:25px; border-radius:12px; width:600px; max-width:95%; box-shadow:0 10px 25px rgba(0,0,0,0.2);">
                <h3 style="margin-top:0; color:var(--primary); margin-bottom:15px;">⚖️ Новая претензия</h3>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px; margin-bottom:20px;">
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Номер претензии</label><input type="text" id="claimNum" class="auth-input" style="margin:0; width:100%;" placeholder="Например, ПР-01"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Дата составления</label><input type="date" id="claimDate" class="auth-input" style="margin:0; width:100%;"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Инициатор</label><input type="text" id="claimInit" class="auth-input" style="margin:0; width:100%;" value="ООО «КОРДА»"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Адресат (Контрагент)</label><input type="text" id="claimAddr" class="auth-input" style="margin:0; width:100%;"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Сумма требований (₽)</label><input type="number" id="claimAmount" class="auth-input" style="margin:0; width:100%;"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Привязка к договору</label><select id="claimProj" class="auth-input" style="margin:0; width:100%;"></select></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Дата направления</label><input type="date" id="claimDateSent" class="auth-input" style="margin:0; width:100%;"></div>
                    <div><label style="font-size:12px; color:var(--secondary); display:block; margin-bottom:4px;">Срок ответа до</label><input type="date" id="claimDeadline" class="auth-input" style="margin:0; width:100%;"></div>
=======
        <div id="createClaimModal" class="modal modal-overlay-custom">
            <div class="modal-content fade-in modal-content-custom medium">
                <h3 class="legal-title legal-modal-title">${getLegalScaleIcon()}<span>Новая претензия</span></h3>
                <div class="form-grid">
                    <div><label class="form-label-custom">Номер претензии</label><input type="text" id="claimNum" class="auth-input form-input-custom" placeholder="Например, ПР-01"></div>
                    <div><label class="form-label-custom">Дата составления</label><input type="date" id="claimDate" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Инициатор</label><input type="text" id="claimInit" class="auth-input form-input-custom" value="ООО «КОРДА»"></div>
                    <div><label class="form-label-custom">Адресат (Контрагент)</label><input type="text" id="claimAddr" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Сумма требований (₽)</label><input type="number" id="claimAmount" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Привязка к договору</label><select id="claimProj" class="auth-input form-input-custom"></select></div>
                    <div><label class="form-label-custom">Дата направления</label><input type="date" id="claimDateSent" class="auth-input form-input-custom"></div>
                    <div><label class="form-label-custom">Срок ответа до</label><input type="date" id="claimDeadline" class="auth-input form-input-custom"></div>
>>>>>>> Stashed changes
                </div>
                <div style="display:flex; justify-content:flex-end; gap:10px; border-top:1px solid var(--border); padding-top:15px;">
                    <button class="btn-secondary" onclick="document.getElementById('createClaimModal').style.display='none'">Отмена</button>
                    <button class="btn-primary" onclick="submitNewClaim()">Сохранить в реестр</button>
                </div>
            </div>
        </div>`);
    }

    if (typeof window.navigateTo === 'function') {
        const origNav = window.navigateTo;
        window.navigateTo = function(viewId) {
            origNav(viewId);
            const cv = document.getElementById('claimsView');
            if (cv) cv.style.display = viewId === 'claims' ? 'block' : 'none';
            if (viewId === 'claims') {
                if (currentLegalTab === 'claims') renderClaims();
                else renderCourts();
            }
        };
    }
}

window.openCreateLegalModal = function() {
    if (currentLegalTab === 'claims') {
        openCreateClaimModal();
    } else {
        openCreateCourtModal();
    }
}

window.switchLegalTab = function(tab) {
    currentLegalTab = tab;
    document.getElementById('tabLegalClaims').classList.toggle('active', tab === 'claims');
    document.getElementById('tabLegalCourts').classList.toggle('active', tab === 'courts');
    document.getElementById('btnCreateLegal').innerHTML = getLegalCreateButtonLabel(tab);
    if (tab === 'claims') renderClaims(); else renderCourts();
};

window.renderClaims = function() {
    const container = document.getElementById('legalListContainer');
    const toolbarActions = document.getElementById('legalToolbarActions');
    if (!container) return;
    if (toolbarActions) toolbarActions.innerHTML = renderLegalToolbarButton('claims');

    if (claimsDB.length === 0) {
        container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--secondary); background:rgba(0,0,0,0.02); border-radius:8px; border:1px dashed var(--border);">Нет зарегистрированных претензий.</div>';
        return;
    }

    let html = '<table class="admin-table" style="width:100%; text-align:left; border-collapse:collapse;"><thead><tr style="border-bottom:2px solid var(--border);"><th>№ и Дата</th><th>Договор / Контрагент</th><th>Сумма (₽)</th><th>Статусы и Сроки</th><th>Действия</th></tr></thead><tbody>';
    const today = new Date(); today.setHours(0,0,0,0);
    
    claimsDB.forEach(c => {
        const p = projectsDB.find(x => x.id === c.proj_id);
        const pName = p ? p.contract : 'Договор не найден';
        
        let statusColor = 'var(--secondary)';
        if (c.status === 'Направлена') statusColor = 'var(--primary)';
        if (c.status === 'Ответ получен') statusColor = '#f59e0b';
        if (c.status === 'Урегулирована') statusColor = 'var(--success)';
        if (c.status === 'Отклонена') statusColor = 'var(--danger)';
        
        let deadlineColor = 'var(--text)';
        if (c.deadline && (c.status === 'Направлена' || c.status === 'Подготовка')) {
            const parts = c.deadline.split('-');
            if (parts.length === 3 && new Date(parts[0], parts[1]-1, parts[2]) < today) deadlineColor = 'var(--danger)';
        }

        html += `<tr style="border-bottom:1px solid var(--border);">
            <td style="padding:10px 5px;"><b>№ ${c.number}</b><br><span style="font-size:11px; color:var(--secondary);">от ${c.d_date}</span></td>
            <td style="padding:10px 5px;"><span style="color:var(--primary); cursor:pointer; font-weight:600; text-decoration:underline;" onclick="if(typeof openProject==='function'){openProject(${c.proj_id});}">${pName}</span><br><span style="font-size:12px;">${c.addressee}</span></td>
            <td style="padding:10px 5px; font-weight:bold;">${c.amount.toLocaleString('ru-RU')} ₽</td>
            <td style="padding:10px 5px;">
                <span style="background:${statusColor}; color:white; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600;">${c.status}</span>
                <div style="font-size:11px; margin-top:6px; color:var(--secondary);">Срок ответа: <b style="color:${deadlineColor};">${c.deadline || 'Не указан'}</b></div>
            </td>
            <td style="padding:10px 5px; display:flex; gap:5px; flex-direction:column;">
                <select class="auth-input" onchange="updateClaimStatus(${c.id}, this.value)" style="margin:0; padding:4px; font-size:12px; height:auto;">
                    <option value="Подготовка" ${c.status==='Подготовка'?'selected':''}>Подготовка</option>
                    <option value="Направлена" ${c.status==='Направлена'?'selected':''}>Направлена</option>
                    <option value="Ответ получен" ${c.status==='Ответ получен'?'selected':''}>Ответ получен</option>
                    <option value="Урегулирована" ${c.status==='Урегулирована'?'selected':''}>Урегулирована</option>
                    <option value="Отклонена" ${c.status==='Отклонена'?'selected':''}>Отклонена</option>
                </select>
<<<<<<< Updated upstream
                <button class="btn-secondary" style="padding:4px; font-size:11px;" onclick="generateClaimTemplate(${c.id})">📄 Шаблон</button>
=======
                <button class="btn-secondary btn-xs legal-inline-btn" onclick="generateClaimTemplate(${c.id})">${getLegalDocIcon()}<span>Шаблон</span></button>
>>>>>>> Stashed changes
            </td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
};

window.openCreateClaimModal = function() {
    const sel = document.getElementById('claimProj');
    sel.innerHTML = '<option value="" disabled selected>Выберите договор...</option>' + projectsDB.map(p => `<option value="${p.id}">${p.contract} (${p.client})</option>`).join('');
    document.getElementById('claimDate').value = new Date().toISOString().split('T')[0];
    document.getElementById('createClaimModal').style.display = 'flex';
};

window.submitNewClaim = async function() {
    const data = {
        number: document.getElementById('claimNum').value || 'Б/Н',
        d_date: document.getElementById('claimDate').value || new Date().toISOString().split('T')[0],
        initiator: document.getElementById('claimInit').value || 'ООО КОРДА',
        addressee: document.getElementById('claimAddr').value || 'Не указан',
        amount: parseFloat(document.getElementById('claimAmount').value) || 0,
        proj_id: parseInt(document.getElementById('claimProj').value) || 0,
        date_sent: document.getElementById('claimDateSent').value || '',
        deadline: document.getElementById('claimDeadline').value || '',
        date_answered: '',
        status: 'Подготовка'
    };
    if(!data.proj_id) return typeof customAlert === 'function' ? customAlert("❌ Выберите связанный договор!") : alert("❌ Выберите связанный договор!");

    const res = await apiCall('/claims', 'POST', data);
    if(res && res.status === 'success') {
        document.getElementById('createClaimModal').style.display = 'none';
        await loadClaims(); renderClaims();
        if(typeof showToast === 'function') showToast("Претензии", "Претензия успешно создана");
        
        const p = projectsDB.find(x => x.id === data.proj_id);
        if (p) {
            if(!p.logs) p.logs = [];
            const now = new Date();
            p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: `⚖️ Зарегистрирована претензия №${data.number} на сумму ${data.amount} руб.`});
            await apiCall(`/projects/${p.id}`, 'PUT', p);
        }
    } else {
        typeof customAlert === 'function' ? customAlert("❌ Ошибка при создании") : alert("Ошибка");
    }
};

window.updateClaimStatus = async function(id, newStatus) {
    const c = claimsDB.find(x => x.id === id);
    if(!c) return;
    c.status = newStatus;
    await apiCall(`/claims/${c.id}`, 'PUT', c);
    await loadClaims(); renderClaims();
    if(typeof showToast === 'function') showToast("Претензии", `Статус изменен на: ${newStatus}`);
};

window.generateClaimTemplate = function(claimId) {
    const c = claimsDB.find(x => x.id === claimId);
    if (!c) return;
    const p = projectsDB.find(x => x.id === c.proj_id);
    if (!p) return;

    const docText = `ДОСУДЕБНАЯ ПРЕТЕНЗИЯ № ${c.number}\nДата: ${c.d_date}\n\nКому: ${c.addressee}\nОт кого: ${c.initiator}\n\nПо договору ${p.contract} от Заказчика/Исполнителя была выявлена задолженность (или неисполнение обязательств).\nСумма требований по настоящей претензии составляет: ${c.amount} руб.\n\nПросим урегулировать данную задолженность в срок до ${c.deadline || 'установленного договором времени'}. \nВ случае отсутствия ответа или отказа в удовлетворении требований, мы будем вынуждены обратиться в Арбитражный суд для защиты своих законных интересов, с возложением на Вас всех судебных издержек.\n\nС уважением,\nРуководитель ___________________`;
    const fileName = `Pretenziya_N${c.number.replace(/[\\/\\s\\?]/g, '_')}_${p.contract.replace(/[\\/\\s\\?]/g, '_')}.txt`;
    const blob = new Blob([docText], { type: 'text/plain;charset=utf-8' });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = fileName;
    link.click();
    URL.revokeObjectURL(link.href);
    if (typeof showToast === 'function') showToast("Шаблон", "Претензия скачана");
};

// === ФУНКЦИИ СУДЕБНЫХ ДЕЛ ===
window.renderCourts = function() {
    const container = document.getElementById('legalListContainer');
    const toolbarActions = document.getElementById('legalToolbarActions');
    if (!container) return;
    if (toolbarActions) toolbarActions.innerHTML = renderLegalToolbarButton('courts');

    if (courtCasesDB.length === 0) {
        container.innerHTML = '<div style="text-align:center; padding:30px; color:var(--secondary); background:rgba(0,0,0,0.02); border-radius:8px; border:1px dashed var(--border);">Нет зарегистрированных судебных дел.</div>';
        return;
    }

    let html = '<table class="admin-table" style="width:100%; text-align:left; border-collapse:collapse;"><thead><tr style="border-bottom:2px solid var(--border);"><th>Дело и Суд</th><th>Договор и Стороны</th><th>Сумма (₽)</th><th>Стадия и Заседания</th><th>Действия</th></tr></thead><tbody>';
    
    courtCasesDB.forEach(c => {
        const p = projectsDB.find(x => x.id === c.proj_id);
        const pName = p ? p.contract : 'Договор не найден';
        
        let stageColor = 'var(--primary)';
        if (c.stage === 'Закрыто') stageColor = 'var(--success)';
        if (c.stage === 'Приостановлено') stageColor = 'var(--secondary)';
        if (c.stage === 'Обжаловано') stageColor = '#f59e0b';
        if (c.stage === 'Вынесение решения') stageColor = '#8b5cf6';
        
        html += `<tr style="border-bottom:1px solid var(--border);">
            <td style="padding:10px 5px;"><b>${c.number}</b><br><span style="font-size:11px; color:var(--secondary);">${c.court_name}</span><br><span style="font-size:10px; background:rgba(0,0,0,0.05); padding:2px 4px; border-radius:4px; display:inline-block; margin-top:4px;">${c.instance}</span></td>
            <td style="padding:10px 5px;"><span style="color:var(--primary); cursor:pointer; font-weight:600; text-decoration:underline;" onclick="if(typeof openProject==='function'){openProject(${c.proj_id});}">${pName}</span><br><span style="font-size:11px; color:var(--secondary);">Истец:</span> <span style="font-size:11px;">${c.plaintiff}</span><br><span style="font-size:11px; color:var(--secondary);">Ответчик:</span> <span style="font-size:11px;">${c.defendant}</span></td>
            <td style="padding:10px 5px; font-weight:bold;">${c.amount.toLocaleString('ru-RU')} ₽</td>
            <td style="padding:10px 5px;">
                <span style="background:${stageColor}; color:white; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600;">${c.stage}</span>
                <div style="font-size:11px; margin-top:6px; color:var(--secondary);">След. заседание: <b style="color:var(--text);">${c.next_hearing || 'Не назначено'}</b></div>
            </td>
            <td style="padding:10px 5px; display:flex; gap:5px; flex-direction:column;">
                <select class="auth-input" onchange="updateCourtStage(${c.id}, this.value)" style="margin:0; padding:4px; font-size:11px; height:auto;">
                    <option value="Подготовка иска" ${c.stage==='Подготовка иска'?'selected':''}>Подготовка иска</option>
                    <option value="Подан иск" ${c.stage==='Подан иск'?'selected':''}>Подан иск</option>
                    <option value="Предварительное заседание" ${c.stage==='Предварительное заседание'?'selected':''}>Предварительное</option>
                    <option value="Основное заседание" ${c.stage==='Основное заседание'?'selected':''}>Основное заседание</option>
                    <option value="Вынесение решения" ${c.stage==='Вынесение решения'?'selected':''}>Вынесение решения</option>
                    <option value="Обжаловано" ${c.stage==='Обжаловано'?'selected':''}>Обжаловано</option>
                    <option value="Приостановлено" ${c.stage==='Приостановлено'?'selected':''}>Приостановлено</option>
                    <option value="Закрыто" ${c.stage==='Закрыто'?'selected':''}>Закрыто</option>
                </select>
                <input type="date" class="auth-input" title="Изменить дату заседания" value="${c.next_hearing || ''}" onchange="updateCourtHearing(${c.id}, this.value)" style="margin:0; padding:4px; font-size:11px; height:auto;">
            </td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
};

window.openCreateCourtModal = function() {
    const sel = document.getElementById('courtProj');
    sel.innerHTML = '<option value="" disabled selected>Выберите договор...</option>' + projectsDB.map(p => `<option value="${p.id}">${p.contract} (${p.client})</option>`).join('');
    document.getElementById('createCourtModal').style.display = 'flex';
};

window.submitNewCourt = async function() {
    const data = { number: document.getElementById('courtNum').value || 'Б/Н', court_name: document.getElementById('courtName').value || 'Не указан', plaintiff: document.getElementById('courtPlain').value || 'ООО КОРДА', defendant: document.getElementById('courtDef').value || 'Не указан', amount: parseFloat(document.getElementById('courtAmount').value) || 0, proj_id: parseInt(document.getElementById('courtProj').value) || 0, instance: document.getElementById('courtInst').value || 'Первая', next_hearing: document.getElementById('courtHearing').value || '', stage: 'Подготовка иска' };
    if(!data.proj_id) return typeof customAlert === 'function' ? customAlert("❌ Выберите связанный договор!") : alert("❌ Выберите связанный договор!");

    const res = await apiCall('/court_cases', 'POST', data);
    if(res && res.status === 'success') {
        document.getElementById('createCourtModal').style.display = 'none';
        await loadCourtCases(); renderCourts();
        if(typeof showToast === 'function') showToast("Судебные дела", "Дело успешно зарегистрировано");
        
        const p = projectsDB.find(x => x.id === data.proj_id);
        if (p) {
            if(!p.logs) p.logs = []; const now = new Date();
            p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: `⚖️ Зарегистрировано судебное дело №${data.number} (${data.instance}). Сумма иска: ${data.amount} руб.`});
            await apiCall(`/projects/${p.id}`, 'PUT', p);
        }
    } else { typeof customAlert === 'function' ? customAlert("❌ Ошибка при создании") : alert("Ошибка"); }
};

window.updateCourtStage = async function(id, newStage) { const c = courtCasesDB.find(x => x.id === id); if(!c) return; c.stage = newStage; await apiCall(`/court_cases/${c.id}`, 'PUT', c); await loadCourtCases(); renderCourts(); if(typeof showToast === 'function') showToast("Судебные дела", `Стадия изменена на: ${newStage}`); };
window.updateCourtHearing = async function(id, newDate) { const c = courtCasesDB.find(x => x.id === id); if(!c) return; c.next_hearing = newDate; await apiCall(`/court_cases/${c.id}`, 'PUT', c); await loadCourtCases(); renderCourts(); if(typeof showToast === 'function') showToast("Судебные дела", `Дата заседания обновлена`); };

async function login() {
    const e = document.getElementById('loginEmail').value, p = document.getElementById('loginPassword').value;
    const res = await apiCall('/login', 'POST', { email: e, password: p });
    if (res && res.error) { document.getElementById('loginError').innerText = res.error; return; }
    currentUser = res; localStorage.setItem('korda_session', JSON.stringify(currentUser)); window.location.href = '/app';
}

async function register() {
    const name = document.getElementById('regName').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const pass = document.getElementById('regPassword').value;
    const errDiv = document.getElementById('regError');
    const btn = document.querySelector('#registerFormCard button');
    if(!name || !email || !pass) { errDiv.innerText = "Заполните все поля!"; return; }
    if(btn) { btn.innerText = "Отправка..."; btn.disabled = true; }
    const res = await apiCall('/register', 'POST', { email, password: pass, name });
    if (!res || res.error) { 
        errDiv.innerText = (res && res.error) ? res.error : "Ошибка сервера"; 
        if(btn) { btn.innerText = "Отправить заявку"; btn.disabled = false; }
        return; 
    }
    currentUser = { email, name, status: 'pending', role: null }; 
    localStorage.setItem('korda_session', JSON.stringify(currentUser)); 
    customAlert("Заявка успешно отправлена!\nОжидайте одобрения Директором.").then(() => { window.location.href = 'login.html'; });
}

async function recoverPassword() {
    const email = document.getElementById('recEmail').value;
    if(!email) return; await apiCall('/recover', 'POST', { email });
    customAlert("Письмо для восстановления отправлено."); 
    const recF = document.getElementById('recoverFormCard'); if(recF) recF.style.display='none'; 
    const logF = document.getElementById('loginFormCard'); if(logF) logF.style.display='block';
}

function logout() { currentUser = null; localStorage.removeItem('korda_session'); window.location.href = 'login.html'; }

// --- UI UTILITIES: CUSTOM WINDOWS ---
function showToast(title, message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if(!container) return;
    const id = Date.now();
    const html = `
        <div id="toast_${id}" class="toast fade-in" style="border-left: 4px solid ${type === 'error' ? 'var(--danger)' : 'var(--primary)'}">
            <div style="font-weight:bold; font-size:13px;">${title}</div>
            <div style="font-size:12px; margin-top:4px; color:var(--secondary);">${message}</div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
    setTimeout(() => { const el = document.getElementById(`toast_${id}`); if(el) el.remove(); }, 4000);
}

function customAlert(message) {
    return new Promise(resolve => {
        const m = document.getElementById('genericModal');
        document.getElementById('genModalTitle').innerText = 'Уведомление';
        document.getElementById('genModalBody').innerHTML = `<p>${message}</p>`;
        document.getElementById('genModalFooter').innerHTML = `<button class="btn-primary" id="genOk">Понятно</button>`;
        m.style.display = 'flex';
        document.getElementById('genOk').onclick = () => { m.style.display = 'none'; resolve(); };
    });
}

function customConfirm(message) {
    return new Promise(resolve => {
        const m = document.getElementById('genericModal');
        document.getElementById('genModalTitle').innerText = 'Подтверждение';
        document.getElementById('genModalBody').innerHTML = `<p>${message}</p>`;
        document.getElementById('genModalFooter').innerHTML = `
            <button class="btn-secondary" id="genCancel">Отмена</button>
            <button class="btn-danger" id="genConfirm">Да, выполнить</button>
        `;
        m.style.display = 'flex';
        document.getElementById('genCancel').onclick = () => { m.style.display = 'none'; resolve(false); };
        document.getElementById('genConfirm').onclick = () => { m.style.display = 'none'; resolve(true); };
    });
}

function customPrompt(message, defaultValue = '') {
    return new Promise(resolve => {
        const m = document.getElementById('genericModal');
        document.getElementById('genModalTitle').innerText = 'Ввод данных';
        document.getElementById('genModalBody').innerHTML = `
            <label style="font-size:13px; margin-bottom:8px; display:block;">${message}</label>
            <input type="text" id="genInput" class="auth-input" value="${defaultValue}" style="margin:0;">
        `;
        document.getElementById('genModalFooter').innerHTML = `
            <button class="btn-secondary" id="genCancel">Отмена</button>
            <button class="btn-primary" id="genSubmit">Продолжить</button>
        `;
        m.style.display = 'flex';
        const inp = document.getElementById('genInput');
        inp.focus();
        inp.onkeypress = (e) => { if(e.key === 'Enter') document.getElementById('genSubmit').click(); };
        document.getElementById('genCancel').onclick = () => { m.style.display = 'none'; resolve(null); };
        document.getElementById('genSubmit').onclick = () => { m.style.display = 'none'; resolve(inp.value); };
    });
}

// ==========================================
// ГЛОБАЛЬНЫЙ OMNI-ПОИСК (1С-СТАНДАРТ)
// ==========================================
window.handleOmniSearch = function() {
    const q = document.getElementById('searchInput').value.toLowerCase().trim();
    const resBox = document.getElementById('omniSearchResults');
    if (!q) { resBox.style.display = 'none'; filterProjects(); return; }
    
    filterProjects(); // Оставляем локальную фильтрацию для списков
    
    let results = [];
    projectsDB.forEach(p => { if((p.name||'').toLowerCase().includes(q) || (p.contract||'').toLowerCase().includes(q)) results.push({type: 'Проект', title: p.name, desc: p.contract, link: `openProject(${p.id}); document.getElementById('omniSearchResults').style.display='none';`, icon: '📁'}); });
    documentsDB.forEach(d => { if((d.number||'').toLowerCase().includes(q) || (d.subject||'').toLowerCase().includes(q)) results.push({type: 'Документ', title: `№ ${d.number}`, desc: d.subject, link: `navigateTo('documents'); document.getElementById('omniSearchResults').style.display='none';`, icon: '📄'}); });
    tasksDB.forEach(t => { if((t.title||'').toLowerCase().includes(q)) results.push({type: 'Поручение', title: t.title, desc: `Исполнитель: ${t.executor}`, link: `navigateTo('tasks'); document.getElementById('omniSearchResults').style.display='none';`, icon: '⚡'}); });
    
    if (results.length === 0) {
        resBox.innerHTML = '<div style="color:var(--secondary); font-size:12px; text-align:center; padding:10px;">Ничего не найдено</div>';
    } else {
        resBox.innerHTML = results.map(r => `
            <div onclick="${r.link}" style="padding: 8px 10px; background: var(--bg); border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 10px; border: 1px solid transparent;" onmouseover="this.style.borderColor='var(--primary)'" onmouseout="this.style.borderColor='transparent'">
                <div style="font-size: 16px;">${r.icon}</div>
                <div>
                    <div style="font-size: 12px; font-weight: bold; color: var(--text);">${r.title}</div>
                    <div style="font-size: 10px; color: var(--secondary);">${r.type} • ${r.desc.substring(0, 40)}</div>
                </div>
            </div>
        `).join('');
    }
    resBox.style.display = 'flex';
};

document.addEventListener('click', (e) => { const sb = document.querySelector('.search-bar'); const box = document.getElementById('omniSearchResults'); if(sb && !sb.contains(e.target) && box) box.style.display = 'none'; });

window.exportDataToExcel = function(data, filename) {
    if (typeof XLSX === 'undefined') return customAlert("Библиотека XLSX не загружена");
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Реестр");
    XLSX.writeFile(wb, filename + ".xlsx");
};

window.openClientCard = function(id) {
    const client = clientsDB.find(c => c.id === id);
    if(!client) return;
    
    const cProjs = projectsDB.filter(p => (p.client || '').includes(client.name));
    const cClaims = claimsDB.filter(c => (c.addressee || '').includes(client.name) || (c.initiator || '').includes(client.name) || cProjs.some(p => p.id === c.proj_id));
    const cCourts = courtCasesDB.filter(c => (c.plaintiff || '').includes(client.name) || (c.defendant || '').includes(client.name) || cProjs.some(p => p.id === c.proj_id));

    let html = `<div style="display:flex; gap:20px; flex-wrap:wrap;">
        <div style="flex:1; min-width:250px; background:var(--bg); padding:15px; border-radius:12px; border:1px solid var(--border);">
            <h4 style="margin-top:0; color:var(--primary); display:flex; justify-content:space-between;">Сделки <span>${cProjs.length}</span></h4>
            ${cProjs.length === 0 ? '<span style="font-size:12px; color:var(--secondary);">Нет сделок</span>' : cProjs.map(p => `<div style="font-size:12px; margin-bottom:8px; padding-bottom:8px; border-bottom:1px dashed var(--border);"><a href="#" onclick="openProject(${p.id}); document.getElementById('clientCardModal').style.display='none';"><b>${p.contract}</b></a><br><span style="color:var(--secondary)">Сумма:</span> ${p.budget.toLocaleString()} ₽<br><span style="color:var(--secondary)">Статус:</span> ${p.status}</div>`).join('')}
        </div>
        <div style="flex:1; min-width:250px; background:var(--bg); padding:15px; border-radius:12px; border:1px solid var(--danger);">
            <h4 style="margin-top:0; color:var(--danger); display:flex; justify-content:space-between;">Претензии <span>${cClaims.length}</span></h4>
            ${cClaims.length === 0 ? '<span style="font-size:12px; color:var(--secondary);">Нет претензий</span>' : cClaims.map(c => `<div style="font-size:12px; margin-bottom:8px; padding-bottom:8px; border-bottom:1px dashed var(--danger);"><b style="color:var(--danger)">№${c.number}</b><br><span style="color:var(--secondary)">Сумма:</span> ${c.amount.toLocaleString()} ₽<br><span style="color:var(--secondary)">Статус:</span> ${c.status}</div>`).join('')}
        </div>
        <div style="flex:1; min-width:250px; background:var(--bg); padding:15px; border-radius:12px; border:1px solid #8b5cf6;">
            <h4 style="margin-top:0; color:#8b5cf6; display:flex; justify-content:space-between;">Суды <span>${cCourts.length}</span></h4>
            ${cCourts.length === 0 ? '<span style="font-size:12px; color:var(--secondary);">Нет судов</span>' : cCourts.map(c => `<div style="font-size:12px; margin-bottom:8px; padding-bottom:8px; border-bottom:1px dashed #8b5cf6;"><b style="color:#8b5cf6">${c.number}</b><br><span style="color:var(--secondary)">Сумма:</span> ${c.amount.toLocaleString()} ₽<br><span style="color:var(--secondary)">Стадия:</span> ${c.stage}</div>`).join('')}
        </div>
    </div>`;

    let modal = document.getElementById('clientCardModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'clientCardModal';
        modal.className = 'modal-overlay';
        modal.style.zIndex = '10005';
        modal.innerHTML = `
            <div class="modal-card" style="max-width: 1000px; width: 95%;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 20px;">
                    <h2 id="clientCardTitle" style="margin:0;"></h2>
                    <button class="btn-danger" onclick="document.getElementById('clientCardModal').style.display='none'">✕</button>
                </div>
                <div style="font-size:13px; color:var(--secondary); margin-bottom: 20px; background:var(--bg); padding:10px; border-radius:8px;">
                    ИНН: <b id="clientCardInn" style="color:var(--text)"></b> | Контакт: <b id="clientCardContact" style="color:var(--text)"></b>
                </div>
                <div id="clientCardContent" style="max-height: 60vh; overflow-y: auto; padding-right: 10px;"></div>
            </div>`;
        document.body.appendChild(modal);
    }
    document.getElementById('clientCardTitle').innerText = `Досье контрагента: ${client.name}`;
    document.getElementById('clientCardInn').innerText = client.inn || 'Не указан';
    document.getElementById('clientCardContact').innerText = client.contact || 'Не указан';
    document.getElementById('clientCardContent').innerHTML = html;
    modal.style.display = 'flex';
};

// Переопределяем функцию рендера клиентов глобально, чтобы добавить кнопку экспорта
window.renderClients = function() { 
    const tbody = document.getElementById('clientsListTable'); if(!tbody) return; 
    
    const viewHeader = tbody.closest('table').parentElement;
    if (viewHeader && !document.getElementById('btnExportClients')) {
        const btn = document.createElement('button');
        btn.id = 'btnExportClients';
        btn.className = 'btn-success no-print';
        btn.style.marginBottom = '15px';
        btn.innerHTML = '📊 Экспорт реестра в Excel';
        btn.onclick = () => exportDataToExcel(clientsDB, 'Реестр_Контрагентов');
        viewHeader.insertBefore(btn, viewHeader.firstChild);
    }

    tbody.innerHTML = ''; 
    clientsDB.forEach(c => { 
        tbody.innerHTML += `<tr><td><b style="color:var(--primary); cursor:pointer; text-decoration:underline;" onclick="openClientCard(${c.id})" title="Открыть досье контрагента 360°">${c.name}</b></td><td>${c.inn}</td><td>${c.contact}</td></tr>`; 
    }); 
};

// === KANBAN BOARD LOGIC ===
window.setViewMode = function(mode) {
    viewMode = mode;
    localStorage.setItem('korda_view_mode', mode);
    
    document.querySelectorAll('.view-toggle button').forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector(`.view-toggle button[onclick="setViewMode('${mode}')"]`);
    if(activeBtn) activeBtn.classList.add('active');

    if (document.getElementById('dashboardView') && document.getElementById('dashboardView').style.display === 'block') {
        const listContainer = document.getElementById('projectsListContainer');
        if (!listContainer) return;

        if (mode === 'kanban') {
            const table = listContainer.querySelector('table');
            if (table) table.style.display = 'none';
            renderKanbanBoard(listContainer);
        } else {
            const kb = listContainer.querySelector('.kanban-board');
            if (kb) kb.remove();
            const table = listContainer.querySelector('table');
            if (table) table.style.display = 'table';
            if (typeof renderDashboard === 'function') renderDashboard();
        }
    }
};

window.renderKanbanBoard = function(container) {
    if (!container) container = document.getElementById('projectsListContainer');
    if (!container) return;

    let existingKb = container.querySelector('.kanban-board');
    if (existingKb) existingKb.remove();

    let counts = { active: 0, prolongation: 0, archive: 0, canceled: 0, terminated: 0 };
    let filteredProjs = projectsDB; 
    
    if (typeof currentDepartmentFilter !== 'undefined' && currentDepartmentFilter !== 'all') {
        filteredProjs = projectsDB.filter(p => p.manager === currentDepartmentFilter || (p.team && p.team.includes(currentDepartmentFilter)));
    }

    filteredProjs.forEach(p => { if(counts[p.status] !== undefined) counts[p.status]++; });

    const kanbanHtml = `
        <div class="kanban-board">
            <div class="kanban-col" data-status="active" style="background: rgba(0,0,0,0.02); border: 1px solid var(--border);">
                <h3 style="margin: 0 0 15px 0; color: var(--primary); display: flex; justify-content: space-between; font-size: 16px;">
                    В работе <span class="badge" style="background: var(--primary); color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">${counts.active}</span>
                </h3>
                <div class="kanban-list" id="kb-active"></div>
            </div>
        <div class="kanban-col" data-status="prolongation" style="background: rgba(245, 158, 11, 0.05); border: 1px solid var(--warning, #f59e0b);">
            <h3 style="margin: 0 0 15px 0; color: var(--warning, #f59e0b); display: flex; justify-content: space-between; font-size: 16px;">
                На пролонгации <span class="badge" style="background: var(--warning, #f59e0b); color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">${counts.prolongation}</span>
            </h3>
            <div class="kanban-list" id="kb-prolongation"></div>
        </div>
            <div class="kanban-col" data-status="archive" style="background: rgba(16, 185, 129, 0.05); border: 1px solid var(--success);">
                <h3 style="margin: 0 0 15px 0; color: var(--success); display: flex; justify-content: space-between; font-size: 16px;">
                    Завершено <span class="badge" style="background: var(--success); color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">${counts.archive}</span>
                </h3>
                <div class="kanban-list" id="kb-archive"></div>
            </div>
            <div class="kanban-col" data-status="canceled" style="background: rgba(239, 68, 68, 0.05); border: 1px solid var(--danger);">
                <h3 style="margin: 0 0 15px 0; color: var(--danger); display: flex; justify-content: space-between; font-size: 16px;">
                    Отменено <span class="badge" style="background: var(--danger); color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">${counts.canceled}</span>
                </h3>
                <div class="kanban-list" id="kb-canceled"></div>
            </div>
        <div class="kanban-col" data-status="terminated" style="background: rgba(100, 116, 139, 0.05); border: 1px solid #64748b;">
            <h3 style="margin: 0 0 15px 0; color: #64748b; display: flex; justify-content: space-between; font-size: 16px;">
                Расторгнут <span class="badge" style="background: #64748b; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">${counts.terminated}</span>
            </h3>
            <div class="kanban-list" id="kb-terminated"></div>
        </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', kanbanHtml);

    filteredProjs.forEach(p => {
        const col = document.getElementById(`kb-${p.status}`);
        if (!col) return;

        let totalTasks = 0; let doneTasks = 0;
        if (p.checklist) {
            p.checklist.forEach((sec, sIdx) => {
                sec.tasks.forEach((t, tIdx) => {
                    totalTasks++;
                    if (p.checkedState && p.checkedState[`task_${sIdx}_${tIdx}`] && p.checkedState[`task_${sIdx}_${tIdx}`].startsWith('✅')) doneTasks++;
                });
            });
        }
        const progress = totalTasks === 0 ? 0 : Math.round((doneTasks / totalTasks) * 100);

        col.innerHTML += `
            <div class="kanban-card" data-id="${p.id}" style="background: var(--card-bg); padding: 15px; border-radius: 10px; border: 1px solid var(--border); cursor: grab; display: flex; flex-direction: column; gap: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 11px; color: var(--secondary); font-weight: bold; padding: 2px 6px; background: var(--bg); border-radius: 4px;">${p.contract}</span>
                    <span style="font-size: 12px; color: ${progress === 100 ? 'var(--success)' : 'var(--primary)'}; font-weight: bold;">${progress}%</span>
                </div>
                <div style="font-weight: bold; font-size: 14px; line-height: 1.3;">${p.name}</div>
                <div style="font-size: 12px; color: var(--secondary); display: flex; align-items: center; gap: 4px;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                    ${p.manager}
                </div>
                <div style="font-size: 12px; color: var(--text); background: rgba(0,0,0,0.03); padding: 6px; border-radius: 6px; margin-top: 4px;">
                    🏢 ${p.client || 'Без заказчика'}
                </div>
                <button class="btn-secondary no-drag" style="width: 100%; margin-top: 5px; padding: 6px; font-size: 12px; justify-content: center; cursor: pointer;" onclick="openProject(${p.id})">Открыть сделку</button>
            </div>
        `;
    });

    if (typeof Sortable !== 'undefined') {
        ['kb-active', 'kb-prolongation', 'kb-archive', 'kb-canceled', 'kb-terminated'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                new Sortable(el, {
                    group: 'shared-kanban',
                    animation: 150,
                    ghostClass: 'kanban-ghost',
                    filter: '.no-drag', 
                    preventOnFilter: false,
                    delay: window.innerWidth <= 768 ? 100 : 0, 
                    delayOnTouchOnly: true,
                    onEnd: async function (evt) {
                        const itemEl = evt.item;  
                        const newStatus = evt.to.parentElement.parentElement.getAttribute('data-status');
                        const projId = parseInt(itemEl.getAttribute('data-id'));

                        const p = projectsDB.find(x => x.id === projId);
                        if (!p || p.status === newStatus) return; 

                        if (newStatus === 'archive') {
                        const hasRec = await customConfirm("Подписан ли двусторонний Акт сверки взаиморасчетов?\nБез него закрытие договора невозможно.");
                        if (!hasRec) {
                            renderKanbanBoard(container);
                            return customAlert("Перенос отменен: требуется Акт сверки.");
                        }
                            const folder = await customPrompt("Сделка завершена! Введите номер папки для физического архива:");
                            const rack = await customPrompt("Введите номер стеллажа:");
                            if (!folder || !rack) {
                                renderKanbanBoard(container); 
                                return customAlert("Перенос отменен: для закрытия сделки обязательно указать данные архива.");
                            }
                            if (!p.archive_details) p.archive_details = {};
                            p.archive_details.folder = folder; p.archive_details.rack = rack;
                            const now = new Date();
                            p.archive_details.date = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')}.${now.getFullYear()}`;
                            
                            if (!p.logs) p.logs = [];
                            p.logs.unshift({time: p.archive_details.date + " 00:00", user: currentUser.name, action: `Перенес сделку в Архив (Drag & Drop). Стеллаж: ${rack}, Папка: ${folder}`});
                        } 
                        else if (newStatus === 'canceled') {
                            if (!(await customConfirm(`Вы уверены, что хотите отменить проект "${p.name}"?`))) {
                                renderKanbanBoard(container); return;
                            }
                            if (!p.logs) p.logs = [];
                            const now = new Date();
                            p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: "Отменил проект (Drag & Drop)"});
                    }
                    else if (newStatus === 'prolongation') {
                        const newDate = await customPrompt("Введите новую дату окончания (ДД.ММ.ГГГГ):");
                        if (!newDate) { renderKanbanBoard(container); return customAlert("Отменено."); }
                        if (!p.archive_details) p.archive_details = {};
                        p.archive_details.prolongation = { date: newDate, reason: "Drag & Drop" };
                        if (!p.logs) p.logs = [];
                        const now = new Date();
                        p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: `Перевел договор на пролонгацию. До: ${newDate}`});
                    }
                    else if (newStatus === 'terminated') {
                        const reason = await customPrompt("Укажите причину расторжения:");
                        if (!reason) { renderKanbanBoard(container); return customAlert("Отменено."); }
                        if (!p.archive_details) p.archive_details = {};
                        p.archive_details.termination_reason = reason;
                        if (!p.logs) p.logs = [];
                        const now = new Date();
                        p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: `Расторг договор. Причина: ${reason}`});
                        }
                        else if (newStatus === 'active') {
                            if (!p.logs) p.logs = [];
                            const now = new Date();
                            p.logs.unshift({time: `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`, user: currentUser.name, action: "Восстановил проект в работу (Drag & Drop)"});
                        }

                        p.status = newStatus;
                        await apiCall(`/projects/${p.id}`, 'PUT', p); 
                        showToast("Канбан", "Статус проекта обновлен");
                    },
                });
            }
        });
    }
};
