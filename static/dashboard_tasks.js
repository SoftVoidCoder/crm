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

    return `<span style="color:var(--primary); font-weight:600;">${str}</span>`;
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
    
    filt.sort((a,b) => (b.priority === 'high' ? 1 : 0) - (a.priority === 'high' ? 1 : 0)); // Важные наверх

    if (filt.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding:30px; color:var(--secondary);">Нет поручений в этой категории.</div>`;
        return;
    }
    
    container.innerHTML = filt.map(t => {
        let actionBtn = '';
        if (t.status === 'active' && (t.executor === currentUser.name || currentUser.role === 'Директор')) {
            actionBtn = `<button class="btn-success" style="padding: 6px 12px; font-size: 12px; min-height:unset;" onclick="toggleTaskStatus(${t.id}, 'completed')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>Выполнено</button>`;
        } else if (t.status === 'completed' && (t.author === currentUser.name || currentUser.role === 'Директор')) {
            actionBtn = `<button class="btn-secondary" style="padding: 6px 12px; font-size: 12px; min-height:unset;" onclick="toggleTaskStatus(${t.id}, 'active')">Вернуть в работу</button>`;
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
    const prio = document.getElementById('taskPriority') && document.getElementById('taskPriority').checked ? 'high' : 'normal';
    const pId = document.getElementById('taskProjectId') ? (parseInt(document.getElementById('taskProjectId').value) || 0) : 0;
    
    if (!title || !exec || !dead) return customAlert("Заполните Суть, Исполнителя и Дедлайн");
    
    const res = await apiCall('/tasks', 'POST', { 
        title: title, 
        description: desc, 
        author: currentUser.name, 
        executor: exec, 
        deadline: dead,
        priority: prio,
        project_id: pId
    });
    
    if (!res || res.status !== 'success') {
        customAlert("⚠️ Ошибка сохранения! Пожалуйста, убедитесь, что вы перезапустили сервер (базу данных).");
        return;
    }
    
    document.getElementById('createTaskModal').style.display = 'none';
    document.getElementById('taskTitle').value = ''; 
    document.getElementById('taskDesc').value = '';
    
    await loadTasks(); 
    renderTasks();
}

window.delegateTask = async function(id) {
    const t = tasksDB.find(x => x.id === id);
    if (!t) return;
    const opts = allUsersDB.filter(u => u.status === 'approved' && u.name !== currentUser.name).map((u,i) => `${i+1} - ${u.name}`).join('\\n');
    const userIdx = await customPrompt(`Кому передать задачу?\\nВведите номер:\\n${opts}`);
    const userObj = allUsersDB.filter(u => u.status === 'approved' && u.name !== currentUser.name)[parseInt(userIdx)-1];
    if (!userObj) return;
    
    const now = new Date(); const tStr = `${now.getDate().toString().padStart(2,'0')}.${(now.getMonth()+1).toString().padStart(2,'0')} ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
    const msg = `↘️ ${currentUser.name} перенаправил(а) задачу на ${userObj.name} (${tStr})`;
    if(!t.history) t.history = []; t.history.push(msg);
    
    await apiCall(`/tasks/${id}`, 'PUT', { status: 'active', executor: userObj.name, history: t.history });
    await loadTasks(); renderTasks();
};

async function toggleTaskStatus(id, status) {
    await apiCall(`/tasks/${id}`, 'PUT', { status: status });
    await loadTasks(); 
    renderTasks();
}