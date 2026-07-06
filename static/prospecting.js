let outreachProspectsDB = [];
let outreachReportsDB = [];
let outreachImportsDB = [];
let outreachSelectedId = 0;
let outreachEditingId = 0;
let outreachSearch = '';
let outreachStatusFilter = '';
let outreachPriorityFilter = '';
let outreachManagerFilter = '';
let outreachProcessedFilter = '';
let outreachOnlyOverdue = false;
let outreachOnlyToday = false;
let outreachSelectedIds = new Set();

function outreachEscape(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function outreachToday() {
    const now = new Date();
    const day = String(now.getDate()).padStart(2, '0');
    const month = String(now.getMonth() + 1).padStart(2, '0');
    return `${day}.${month}.${now.getFullYear()}`;
}

function outreachStatusLabel(status) {
    return {
        new: 'Не обработан',
        assigned: 'Назначен',
        in_progress: 'В работе',
        no_answer: 'Не дозвонились',
        follow_up: 'Повторный контакт',
        warm: 'Тёплый',
        meeting: 'Назначена встреча',
        converted: 'Переведён в лид',
        do_not_contact: 'Не беспокоить',
        archived: 'Архив',
    }[String(status || '')] || 'Без статуса';
}

function outreachTone(status, isOverdue = false) {
    if (isOverdue) return 'critical';
    const normalized = String(status || '');
    if (normalized === 'converted') return 'positive';
    if (normalized === 'warm' || normalized === 'meeting') return 'attention';
    if (normalized === 'do_not_contact' || normalized === 'archived') return 'neutral';
    if (normalized === 'no_answer') return 'critical';
    return 'neutral';
}

function outreachProcessedLabel(flag) {
    return Number(flag || 0) === 1 ? 'Обработан' : 'Не обработан';
}

function outreachPriorityLabel(priority) {
    return {
        high: 'Высокий',
        normal: 'Обычный',
        low: 'Низкий',
    }[String(priority || '')] || 'Обычный';
}

function outreachPriorityTone(priority) {
    const normalized = String(priority || 'normal');
    if (normalized === 'high') return 'critical';
    if (normalized === 'low') return 'neutral';
    return 'accent';
}

function outreachManagerCandidates() {
    const approvedUsers = Array.isArray(allUsersDB) ? allUsersDB.filter(user => String(user.status || '') === 'approved') : [];
    const names = approvedUsers.map(user => ({
        name: String(user.name || '').trim(),
        email: String(user.email || '').trim(),
    })).filter(user => user.name || user.email);
    if (currentUser?.name || currentUser?.email) {
        names.push({ name: String(currentUser.name || '').trim(), email: String(currentUser.email || '').trim() });
    }
    const uniq = new Map();
    names.forEach(item => {
        const key = `${item.name}|${item.email}`;
        if (!uniq.has(key)) uniq.set(key, item);
    });
    return Array.from(uniq.values()).sort((a, b) => String(a.name || a.email).localeCompare(String(b.name || b.email), 'ru'));
}

function outreachManagerOptions(withAll = true) {
    const options = outreachManagerCandidates().map(item => {
        const label = item.name && item.email ? `${item.name} · ${item.email}` : (item.name || item.email);
        return `<option value="${outreachEscape(item.email)}" data-name="${outreachEscape(item.name)}">${outreachEscape(label)}</option>`;
    }).join('');
    return `${withAll ? '<option value="">Все менеджеры</option>' : '<option value="">Без назначения</option>'}${options}`;
}

function outreachFindManagerNameByEmail(email) {
    const normalized = String(email || '').trim().toLowerCase();
    if (!normalized) return '';
    const item = outreachManagerCandidates().find(candidate => String(candidate.email || '').trim().toLowerCase() === normalized);
    return item?.name || '';
}

async function loadOutreachProspects() {
    const data = await apiCall('/outreach/prospects');
    outreachProspectsDB = Array.isArray(data) ? data : [];
    return outreachProspectsDB;
}

async function loadOutreachReports() {
    const data = await apiCall('/outreach/reports');
    outreachReportsDB = Array.isArray(data) ? data : [];
    return outreachReportsDB;
}

async function loadOutreachImports() {
    const data = await apiCall('/outreach/imports');
    outreachImportsDB = Array.isArray(data) ? data : [];
    return outreachImportsDB;
}

async function ensureOutreachData(force = false) {
    if (!Array.isArray(allUsersDB) || !allUsersDB.length) {
        await loadAllUsers();
    }
    if (force || !Array.isArray(outreachProspectsDB) || !outreachProspectsDB.length) {
        await loadOutreachProspects();
    }
    if (force || !Array.isArray(outreachReportsDB)) {
        await loadOutreachReports();
    }
    if (force || !Array.isArray(outreachImportsDB)) {
        await loadOutreachImports();
    }
}

function filteredOutreachRows() {
    const searchNeedle = outreachSearch.trim().toLowerCase();
    return (outreachProspectsDB || []).filter(row => {
        if (outreachStatusFilter && String(row.status || '') !== outreachStatusFilter) return false;
        if (outreachPriorityFilter && String(row.priority || '') !== outreachPriorityFilter) return false;
        if (outreachManagerFilter && String(row.manager_email || '') !== outreachManagerFilter) return false;
        if (outreachProcessedFilter === 'yes' && Number(row.is_processed || 0) !== 1) return false;
        if (outreachProcessedFilter === 'no' && Number(row.is_processed || 0) !== 0) return false;
        if (outreachOnlyOverdue && !row.is_overdue) return false;
        if (outreachOnlyToday && !row.is_due_today) return false;
        if (searchNeedle) {
            const haystack = [
                row.company_name,
                row.contact_name,
                row.phone,
                row.email,
                row.notes,
                row.city,
                row.source_name,
                row.last_result,
            ].join(' ').toLowerCase();
            if (!haystack.includes(searchNeedle)) return false;
        }
        return true;
    });
}

function renderOutreachSummary() {
    const rows = filteredOutreachRows();
    const mount = document.getElementById('outreachSummaryStrip');
    if (!mount) return;
    const unprocessed = rows.filter(row => Number(row.is_processed || 0) === 0).length;
    const overdue = rows.filter(row => row.is_overdue).length;
    const today = rows.filter(row => row.is_due_today).length;
    const warm = rows.filter(row => ['warm', 'meeting'].includes(String(row.status || ''))).length;
    const converted = rows.filter(row => String(row.status || '') === 'converted').length;
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Всего в базе</div><div class="crm-summary-value">${rows.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Не обработаны</div><div class="crm-summary-value">${unprocessed}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">План на сегодня</div><div class="crm-summary-value">${today}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Просрочено</div><div class="crm-summary-value">${overdue}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Тёплые</div><div class="crm-summary-value">${warm}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Переведены в лид</div><div class="crm-summary-value">${converted}</div></div>
    `;
}

function prospectingMetricsForCurrentUser() {
    const today = outreachToday();
    const rows = (outreachProspectsDB || []).filter(row => String(row.manager_email || '') === String(currentUser?.email || ''));
    const reportRows = (outreachReportsDB || []).filter(row => row.report_date === today && String(row.manager_email || '') === String(currentUser?.email || ''));
    const report = reportRows[0] || null;
    const dueToday = rows.filter(row => (row.planned_contact_date || row.next_action_date || '') === today).length;
    const processedToday = rows.filter(row => String(row.last_contact_at || '').startsWith(today)).length;
    let callsTotal = 0;
    let emailsTotal = 0;
    let meetingsTotal = 0;
    let convertedTotal = 0;
    rows.forEach(row => {
        const activities = Array.isArray(row.activities) ? row.activities : [];
        activities.forEach(activity => {
            const activityDate = Number(activity.created_at || 0) ? new Date(Number(activity.created_at || 0) * 1000) : null;
            if (!activityDate) return;
            const key = `${String(activityDate.getDate()).padStart(2, '0')}.${String(activityDate.getMonth() + 1).padStart(2, '0')}.${activityDate.getFullYear()}`;
            if (key !== today) return;
            if (activity.activity_type === 'call') callsTotal += 1;
            if (activity.activity_type === 'email') emailsTotal += 1;
            if (activity.activity_type === 'meeting') meetingsTotal += 1;
        });
        if (String(row.status || '') === 'converted' && String(row.last_contact_at || '').startsWith(today)) convertedTotal += 1;
    });
    return {
        report,
        dueToday,
        processedToday,
        callsTotal,
        emailsTotal,
        meetingsTotal,
        convertedTotal,
    };
}

function renderOutreachReportPanel() {
    const mount = document.getElementById('outreachReportPanel');
    if (!mount) return;
    const today = outreachToday();
    const metrics = prospectingMetricsForCurrentUser();
    const report = metrics.report || {};
    const field = (label, control, wide = false) => `
        <label class="prospecting-field ${wide ? 'prospecting-field--wide' : ''}">
            <span class="prospecting-field__label">${label}</span>
            ${control}
        </label>
    `;
    mount.innerHTML = `
        <div class="section-header">
            <div>
                <h3 class="section-title">Ежедневный отчёт менеджера</h3>
                <p class="section-subtitle">Фиксируй план, сколько обработано, какие были блокеры и что идёт на следующий день.</p>
            </div>
        </div>
        <div class="prospecting-report-grid">
            ${field('Дата отчёта', `<input id="outreachReportDate" class="auth-input" type="text" value="${outreachEscape(report.report_date || today)}" placeholder="дд.мм.гггг">`)}
            ${field('План на день', `<input id="outreachReportPlan" class="auth-input" type="number" value="${outreachEscape(report.plan_total ?? metrics.dueToday)}" placeholder="План, шт.">`)}
            ${field('Обработано', `<input id="outreachReportProcessed" class="auth-input" type="number" value="${outreachEscape(report.processed_total ?? metrics.processedToday)}" placeholder="Обработано, шт.">`)}
            ${field('Звонков', `<input id="outreachReportCalls" class="auth-input" type="number" value="${outreachEscape(report.calls_total ?? metrics.callsTotal)}" placeholder="Звонков">`)}
            ${field('Писем', `<input id="outreachReportEmails" class="auth-input" type="number" value="${outreachEscape(report.emails_total ?? metrics.emailsTotal)}" placeholder="Писем">`)}
            ${field('Встреч', `<input id="outreachReportMeetings" class="auth-input" type="number" value="${outreachEscape(report.meetings_total ?? metrics.meetingsTotal)}" placeholder="Встреч">`)}
            ${field('Переведено в лид', `<input id="outreachReportConverted" class="auth-input" type="number" value="${outreachEscape(report.converted_total ?? metrics.convertedTotal)}" placeholder="Переведено в лид">`)}
            ${field('Краткий итог дня', `<textarea id="outreachReportSummary" class="auth-input" rows="2" placeholder="Что сделали, какой итог">${outreachEscape(report.summary || '')}</textarea>`, true)}
            ${field('Что мешало', `<textarea id="outreachReportBlockers" class="auth-input" rows="2" placeholder="Блокеры, стоп-факторы, переносы">${outreachEscape(report.blockers || '')}</textarea>`, true)}
            ${field('Фокус на завтра', `<textarea id="outreachReportNextDay" class="auth-input" rows="2" placeholder="Кого добить, кого перевести в лид">${outreachEscape(report.next_day_focus || '')}</textarea>`, true)}
        </div>
        <div class="crm-editor-actions">
            <button class="btn-primary" onclick="saveOutreachReport()">Сдать отчёт</button>
        </div>
        <div class="client360-list" style="margin-top:16px;">
            ${(outreachReportsDB || []).slice(0, 5).map(item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${outreachEscape(item.report_date)} · ${outreachEscape(item.manager_name || item.manager_email || 'Менеджер')}</div>
                        <div class="client360-item-meta">план ${Number(item.plan_total || 0)} · обработано ${Number(item.processed_total || 0)} · звонков ${Number(item.calls_total || 0)} · писем ${Number(item.emails_total || 0)}</div>
                    </div>
                    <span class="crm-inline-pill crm-inline-pill--${item.report_date === today ? 'attention' : 'neutral'}">${item.report_date === today ? 'Сегодня' : 'Отчёт'}</span>
                </div>
            `).join('') || '<div class="empty-state">Отчётов пока нет.</div>'}
        </div>
    `;
}

function renderOutreachManagerSelects() {
    const filter = document.getElementById('outreachManagerFilter');
    const importSelect = document.getElementById('outreachImportManager');
    const bulk = document.getElementById('outreachBulkManager');
    if (filter) {
        filter.innerHTML = outreachManagerOptions(true);
        filter.value = outreachManagerFilter || '';
    }
    if (importSelect) {
        const currentValue = importSelect.value || '';
        importSelect.innerHTML = outreachManagerOptions(false);
        importSelect.value = currentValue || currentUser?.email || '';
    }
    if (bulk) {
        const currentValue = bulk.value || '';
        bulk.innerHTML = outreachManagerOptions(false);
        bulk.value = currentValue;
    }
}

function syncOutreachFilterControls() {
    const statusSelect = document.getElementById('outreachStatusFilter');
    const prioritySelect = document.getElementById('outreachPriorityFilter');
    const processedSelect = document.getElementById('outreachProcessedFilter');
    if (statusSelect) statusSelect.value = outreachStatusFilter || '';
    if (prioritySelect) prioritySelect.value = outreachPriorityFilter || '';
    if (processedSelect) processedSelect.value = outreachProcessedFilter || '';
}

function renderOutreachDetail(row) {
    if (!row) return `<div class="empty-state">Выбери карточку из реестра или создай новую запись.</div>`;
    const activities = Array.isArray(row.activities) ? row.activities : [];
    return `
        <div class="crm-detail-card prospecting-detail-card">
            <div class="crm-detail-head">
                <div>
                    <div class="crm-detail-title">${outreachEscape(row.company_name || 'Без компании')}</div>
                    <div class="crm-detail-meta">${outreachEscape(row.contact_name || 'Контакт не указан')} · ${outreachEscape(row.position || 'без должности')} · ${outreachEscape(row.city || 'город не указан')}</div>
                </div>
                <div class="prospecting-badge-stack">
                    <span class="crm-inline-pill crm-inline-pill--${outreachTone(row.status, row.is_overdue)}">${outreachEscape(outreachStatusLabel(row.status))}</span>
                    <span class="crm-inline-pill crm-inline-pill--${outreachPriorityTone(row.priority)}">${outreachEscape(outreachPriorityLabel(row.priority))}</span>
                    <span class="crm-inline-pill crm-inline-pill--${Number(row.is_processed || 0) ? 'positive' : 'neutral'}">${outreachEscape(outreachProcessedLabel(row.is_processed))}</span>
                </div>
            </div>
            <div class="crm-detail-grid">
                <div><span class="crm-detail-label">Телефон</span><strong>${outreachEscape(row.phone || '—')}</strong></div>
                <div><span class="crm-detail-label">Почта</span><strong>${outreachEscape(row.email || '—')}</strong></div>
                <div><span class="crm-detail-label">Как связаться</span><strong>${outreachEscape(row.contact_method || '—')}</strong></div>
                <div><span class="crm-detail-label">Менеджер</span><strong>${outreachEscape(row.manager_name || row.manager_email || 'не назначен')}</strong></div>
                <div><span class="crm-detail-label">Приоритет</span><strong>${outreachEscape(outreachPriorityLabel(row.priority))}</strong></div>
                <div><span class="crm-detail-label">План контакта</span><strong>${outreachEscape(row.planned_contact_date || '—')}</strong></div>
                <div><span class="crm-detail-label">Следующий шаг</span><strong>${outreachEscape(row.next_action_date || '—')}</strong></div>
                <div><span class="crm-detail-label">Попыток</span><strong>${Number(row.attempts_count || 0)}</strong></div>
                <div><span class="crm-detail-label">Последний результат</span><strong>${outreachEscape(row.last_result || '—')}</strong></div>
            </div>
            <div class="crm-detail-actions">
                <button class="btn-secondary" onclick="openOutreachEditor(${Number(row.id || 0)})">Редактировать</button>
                <button class="btn-secondary" onclick="markOutreachProcessed(${Number(row.id || 0)})">Отметить обработанным</button>
                <button class="btn-primary" onclick="convertOutreachProspect(${Number(row.id || 0)})">Перевести в лид</button>
            </div>
            <div class="crm-tags">${(row.tags || []).map(tag => `<span class="crm-tag">${outreachEscape(tag)}</span>`).join('') || '<span class="crm-tag">Без тегов</span>'}</div>
            <div class="crm-detail-note">${outreachEscape(row.notes || 'Комментарий не заполнен.')}</div>
            <div class="crm-activity-block">
                <div class="section-header">
                    <div>
                        <h3 class="section-title">Обработка клиента</h3>
                        <p class="section-subtitle">Звонок, письмо, повторный контакт, встреча, причина отказа и следующий шаг.</p>
                    </div>
                </div>
                <div class="prospecting-activity-grid">
                    <select id="outreachActivityType" class="auth-input">
                        <option value="call">Звонок</option>
                        <option value="email">Письмо</option>
                        <option value="message">Сообщение</option>
                        <option value="meeting">Встреча</option>
                        <option value="note">Заметка</option>
                    </select>
                    <select id="outreachActivityResult" class="auth-input">
                        <option value="">Результат</option>
                        <option value="no_answer">Нет ответа</option>
                        <option value="follow_up">Нужен повторный контакт</option>
                        <option value="warm">Есть интерес</option>
                        <option value="meeting">Назначена встреча</option>
                        <option value="converted">Готов к квалификации</option>
                        <option value="do_not_contact">Не интересно / стоп</option>
                    </select>
                    <input id="outreachActivityNextDate" class="auth-input" type="text" placeholder="Следующий шаг: дд.мм.гггг">
                    <input id="outreachActivityNextAction" class="auth-input" type="text" placeholder="Что дальше сделать">
                    <textarea id="outreachActivitySummary" class="auth-input" rows="2" placeholder="Комментарий по итогам контакта"></textarea>
                    <button class="btn-primary" onclick="saveOutreachActivity(${Number(row.id || 0)})">Сохранить контакт</button>
                </div>
                <div class="client360-list" style="margin-top:16px;">
                    ${activities.map(activity => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${outreachEscape(activity.activity_type || 'Контакт')} · ${outreachEscape(activity.result_status || 'без результата')}</div>
                                <div class="client360-item-meta">${outreachEscape(activity.manager_name || '')} · ${outreachEscape(activity.next_action_date || 'без даты')} · ${outreachEscape(activity.summary || 'без комментария')}</div>
                            </div>
                            <span class="crm-inline-pill crm-inline-pill--${outreachTone(activity.result_status || '')}">${outreachEscape(activity.channel || activity.activity_type || '')}</span>
                        </div>
                    `).join('') || '<div class="empty-state">Истории обработки пока нет.</div>'}
                </div>
            </div>
            <div class="crm-activity-block">
                <div class="section-header">
                    <div>
                        <h3 class="section-title">Последние импорты</h3>
                        <p class="section-subtitle">Чтобы быстро понять, откуда пришла база и кто её загружал.</p>
                    </div>
                </div>
                <div class="client360-list">
                    ${(outreachImportsDB || []).slice(0, 4).map(batch => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${outreachEscape(batch.source_filename || 'Импорт')}</div>
                                <div class="client360-item-meta">${outreachEscape(batch.source_name || 'без источника')} · строк ${Number(batch.rows_total || 0)} · +${Number(batch.created_total || 0)} / обновлено ${Number(batch.updated_total || 0)}</div>
                            </div>
                            <span class="crm-inline-pill crm-inline-pill--neutral">${outreachEscape(batch.actor_name || '')}</span>
                        </div>
                    `).join('') || '<div class="empty-state">Импорты ещё не запускались.</div>'}
                </div>
            </div>
        </div>
    `;
}

function renderOutreachRegistry() {
    const rows = filteredOutreachRows();
    if (!outreachSelectedId && rows.length) outreachSelectedId = Number(rows[0].id || 0);
    const selected = rows.find(row => Number(row.id) === Number(outreachSelectedId)) || null;
    const allSelected = rows.length > 0 && rows.every(row => outreachSelectedIds.has(Number(row.id)));
    return `
        <div class="crm-registry-layout">
            <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 52px;">
                        <col style="width: 210px;">
                        <col style="width: 160px;">
                        <col style="width: 180px;">
                        <col style="width: 150px;">
                        <col style="width: 120px;">
                        <col style="width: 210px;">
                        <col style="width: 90px;">
                        <col style="width: 130px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th style="width:36px;"><input type="checkbox" ${allSelected ? 'checked' : ''} onchange="toggleAllOutreachSelection(this.checked)"></th>
                            <th>Компания</th>
                            <th>Контакт</th>
                            <th>Связь</th>
                            <th>Менеджер</th>
                            <th>Приоритет</th>
                            <th>План / след. шаг</th>
                            <th class="is-num">Попытки</th>
                            <th>Статус</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr class="${Number(row.id) === Number(outreachSelectedId) ? 'is-selected' : ''}" onclick="selectOutreachRow(${Number(row.id || 0)})">
                                <td onclick="event.stopPropagation()"><input type="checkbox" ${outreachSelectedIds.has(Number(row.id)) ? 'checked' : ''} onchange="toggleOutreachSelection(${Number(row.id || 0)}, this.checked)"></td>
                                <td class="crm-title-cell">
                                    <strong>${outreachEscape(row.company_name || '—')}</strong>
                                    <div class="table-subtext">${outreachEscape(outreachProcessedLabel(row.is_processed))}</div>
                                </td>
                                <td class="crm-title-cell">${outreachEscape(row.contact_name || '—')}<div class="table-subtext">${outreachEscape(row.position || '—')}</div></td>
                                <td class="crm-contact-cell">${outreachEscape(row.phone || '—')}<div class="table-subtext">${outreachEscape(row.email || '—')}</div></td>
                                <td class="crm-meta-cell"><span class="crm-cell-single">${outreachEscape(row.manager_name || row.manager_email || 'не назначен')}</span></td>
                                <td><span class="crm-inline-pill crm-inline-pill--${outreachPriorityTone(row.priority)}">${outreachEscape(outreachPriorityLabel(row.priority))}</span></td>
                                <td class="crm-action-cell"><span class="crm-inline-pill crm-inline-pill--${row.is_overdue ? 'critical' : row.is_due_today ? 'attention' : 'neutral'}">${outreachEscape(row.next_action_date || row.planned_contact_date || 'без даты')}</span><div class="table-subtext">${outreachEscape(row.next_action || '—')}</div></td>
                                <td class="is-num crm-meta-cell">${Number(row.attempts_count || 0)}<div class="table-subtext">${outreachEscape(row.last_result || '—')}</div></td>
                                <td class="crm-stage-cell"><span class="crm-inline-pill crm-inline-pill--${outreachTone(row.status, row.is_overdue)}">${outreachEscape(outreachStatusLabel(row.status))}</span></td>
                            </tr>
                        `).join('') || '<tr><td colspan="9"><div class="empty-state">По текущему фильтру база не найдена.</div></td></tr>'}
                    </tbody>
                </table>
            </div>
            ${renderOutreachDetail(selected)}
        </div>
    `;
}

function renderOutreachEditor() {
    const panel = document.getElementById('outreachEditorPanel');
    if (!panel) return;
    const row = (outreachProspectsDB || []).find(item => Number(item.id) === Number(outreachEditingId)) || { tags: [] };
    panel.style.display = 'block';
    panel.innerHTML = `
        <div class="crm-editor-grid">
            <input id="outreachFormCompany" class="auth-input" type="text" placeholder="Компания" value="${outreachEscape(row.company_name || '')}">
            <input id="outreachFormInn" class="auth-input" type="text" placeholder="ИНН" value="${outreachEscape(row.company_inn || '')}">
            <input id="outreachFormContact" class="auth-input" type="text" placeholder="Контактное лицо" value="${outreachEscape(row.contact_name || '')}">
            <input id="outreachFormPosition" class="auth-input" type="text" placeholder="Должность" value="${outreachEscape(row.position || '')}">
            <input id="outreachFormPhone" class="auth-input" type="text" placeholder="Телефон" value="${outreachEscape(row.phone || '')}">
            <input id="outreachFormEmail" class="auth-input" type="text" placeholder="Почта" value="${outreachEscape(row.email || '')}">
            <input id="outreachFormWebsite" class="auth-input" type="text" placeholder="Сайт" value="${outreachEscape(row.website || '')}">
            <input id="outreachFormCity" class="auth-input" type="text" placeholder="Город" value="${outreachEscape(row.city || '')}">
            <select id="outreachFormMethod" class="auth-input">
                <option value="">Как связаться</option>
                <option value="phone" ${row.contact_method === 'phone' ? 'selected' : ''}>Телефон</option>
                <option value="email" ${row.contact_method === 'email' ? 'selected' : ''}>Email</option>
                <option value="message" ${row.contact_method === 'message' ? 'selected' : ''}>Сообщение</option>
                <option value="mixed" ${row.contact_method === 'mixed' ? 'selected' : ''}>Комбинированно</option>
            </select>
            <input id="outreachFormSource" class="auth-input" type="text" placeholder="Источник" value="${outreachEscape(row.source_name || '')}">
            <select id="outreachFormManager" class="auth-input"></select>
            <input id="outreachFormPlannedDate" class="auth-input" type="text" placeholder="План контакта: дд.мм.гггг" value="${outreachEscape(row.planned_contact_date || '')}">
            <select id="outreachFormPriority" class="auth-input">
                <option value="high" ${row.priority === 'high' ? 'selected' : ''}>Высокий приоритет</option>
                <option value="normal" ${String(row.priority || 'normal') === 'normal' ? 'selected' : ''}>Обычный приоритет</option>
                <option value="low" ${row.priority === 'low' ? 'selected' : ''}>Низкий приоритет</option>
            </select>
            <select id="outreachFormStatus" class="auth-input">
                <option value="new" ${row.status === 'new' ? 'selected' : ''}>Не обработан</option>
                <option value="assigned" ${row.status === 'assigned' ? 'selected' : ''}>Назначен</option>
                <option value="in_progress" ${row.status === 'in_progress' ? 'selected' : ''}>В работе</option>
                <option value="follow_up" ${row.status === 'follow_up' ? 'selected' : ''}>Повторный контакт</option>
                <option value="warm" ${row.status === 'warm' ? 'selected' : ''}>Тёплый</option>
                <option value="meeting" ${row.status === 'meeting' ? 'selected' : ''}>Встреча</option>
                <option value="do_not_contact" ${row.status === 'do_not_contact' ? 'selected' : ''}>Не беспокоить</option>
                <option value="archived" ${row.status === 'archived' ? 'selected' : ''}>Архив</option>
            </select>
            <input id="outreachFormTags" class="auth-input" type="text" placeholder="Теги через запятую" value="${outreachEscape((row.tags || []).join(', '))}">
            <textarea id="outreachFormNotes" class="auth-input" rows="3" placeholder="Комментарий">${outreachEscape(row.notes || '')}</textarea>
        </div>
        <div class="crm-editor-actions">
            <button class="btn-secondary" onclick="closeOutreachEditor()">Скрыть</button>
            <button class="btn-primary" onclick="saveOutreachProspect()">Сохранить</button>
        </div>
    `;
    const managerSelect = document.getElementById('outreachFormManager');
    if (managerSelect) {
        managerSelect.innerHTML = outreachManagerOptions(false);
        managerSelect.value = row.manager_email || currentUser?.email || '';
    }
}

function closeOutreachEditor() {
    outreachEditingId = 0;
    const panel = document.getElementById('outreachEditorPanel');
    if (panel) panel.style.display = 'none';
}

function openOutreachEditor(id = 0) {
    outreachEditingId = Number(id || 0);
    renderOutreachEditor();
}

function selectOutreachRow(id) {
    outreachSelectedId = Number(id || 0);
    const mount = document.getElementById('prospectingContentMount');
    if (mount) mount.innerHTML = renderOutreachRegistry();
}

function toggleOutreachSelection(id, checked) {
    const numericId = Number(id || 0);
    if (!numericId) return;
    if (checked) outreachSelectedIds.add(numericId);
    else outreachSelectedIds.delete(numericId);
    const mount = document.getElementById('prospectingContentMount');
    if (mount) mount.innerHTML = renderOutreachRegistry();
}

function toggleAllOutreachSelection(checked) {
    if (checked) {
        filteredOutreachRows().forEach(row => outreachSelectedIds.add(Number(row.id)));
    } else {
        outreachSelectedIds.clear();
    }
    const mount = document.getElementById('prospectingContentMount');
    if (mount) mount.innerHTML = renderOutreachRegistry();
}

function applyOutreachSearch(value) {
    outreachSearch = String(value || '').trim();
    renderProspecting();
}

function setOutreachStatusFilter(value) {
    outreachStatusFilter = value || '';
    renderProspecting();
}

function setOutreachPriorityFilter(value) {
    outreachPriorityFilter = value || '';
    renderProspecting();
}

function setOutreachManagerFilter(value) {
    outreachManagerFilter = value || '';
    renderProspecting();
}

function setOutreachProcessedFilter(value) {
    outreachProcessedFilter = value || '';
    renderProspecting();
}

function toggleOutreachOverdueFilter() {
    outreachOnlyOverdue = !outreachOnlyOverdue;
    renderProspecting();
}

function toggleOutreachTodayFilter() {
    outreachOnlyToday = !outreachOnlyToday;
    renderProspecting();
}

function resetOutreachFilters() {
    outreachSearch = '';
    outreachStatusFilter = '';
    outreachPriorityFilter = '';
    outreachManagerFilter = '';
    outreachProcessedFilter = '';
    outreachOnlyOverdue = false;
    outreachOnlyToday = false;
    const searchInput = document.getElementById('outreachSearchInput');
    if (searchInput) searchInput.value = '';
    renderProspecting();
}

async function saveOutreachProspect() {
    const managerEmail = document.getElementById('outreachFormManager')?.value || '';
    const payload = {
        company_name: document.getElementById('outreachFormCompany')?.value || '',
        company_inn: document.getElementById('outreachFormInn')?.value || '',
        contact_name: document.getElementById('outreachFormContact')?.value || '',
        position: document.getElementById('outreachFormPosition')?.value || '',
        phone: document.getElementById('outreachFormPhone')?.value || '',
        email: document.getElementById('outreachFormEmail')?.value || '',
        website: document.getElementById('outreachFormWebsite')?.value || '',
        city: document.getElementById('outreachFormCity')?.value || '',
        contact_method: document.getElementById('outreachFormMethod')?.value || '',
        source_name: document.getElementById('outreachFormSource')?.value || '',
        manager_email: managerEmail,
        manager_name: outreachFindManagerNameByEmail(managerEmail) || currentUser?.name || '',
        planned_contact_date: document.getElementById('outreachFormPlannedDate')?.value || '',
        priority: document.getElementById('outreachFormPriority')?.value || 'normal',
        status: document.getElementById('outreachFormStatus')?.value || 'new',
        tags: String(document.getElementById('outreachFormTags')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
        notes: document.getElementById('outreachFormNotes')?.value || '',
    };
    if (!payload.company_name.trim()) return customAlert('Укажи компанию.');
    const endpoint = outreachEditingId ? `/outreach/prospects/${outreachEditingId}` : '/outreach/prospects';
    const method = outreachEditingId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить запись.');
    outreachSelectedId = Number(res.id || outreachEditingId || outreachSelectedId);
    closeOutreachEditor();
    await renderProspecting(true);
}

async function saveOutreachActivity(prospectId) {
    const payload = {
        prospect_id: Number(prospectId || 0),
        activity_type: document.getElementById('outreachActivityType')?.value || 'call',
        result_status: document.getElementById('outreachActivityResult')?.value || '',
        next_action_date: document.getElementById('outreachActivityNextDate')?.value || '',
        next_action: document.getElementById('outreachActivityNextAction')?.value || '',
        summary: document.getElementById('outreachActivitySummary')?.value || '',
        prospect_status: document.getElementById('outreachActivityResult')?.value || '',
    };
    if (!payload.summary.trim() && !payload.next_action.trim() && !payload.result_status.trim()) {
        return customAlert('Заполни результат или комментарий по контакту.');
    }
    const res = await apiCall('/outreach/activities', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить контакт.');
    await renderProspecting(true);
}

async function saveOutreachReport() {
    const payload = {
        report_date: document.getElementById('outreachReportDate')?.value || outreachToday(),
        plan_total: Number(document.getElementById('outreachReportPlan')?.value || 0),
        processed_total: Number(document.getElementById('outreachReportProcessed')?.value || 0),
        calls_total: Number(document.getElementById('outreachReportCalls')?.value || 0),
        emails_total: Number(document.getElementById('outreachReportEmails')?.value || 0),
        meetings_total: Number(document.getElementById('outreachReportMeetings')?.value || 0),
        converted_total: Number(document.getElementById('outreachReportConverted')?.value || 0),
        summary: document.getElementById('outreachReportSummary')?.value || '',
        blockers: document.getElementById('outreachReportBlockers')?.value || '',
        next_day_focus: document.getElementById('outreachReportNextDay')?.value || '',
    };
    const res = await apiCall('/outreach/reports', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить отчёт.');
    await loadOutreachReports();
    renderOutreachReportPanel();
    showToast('База развития', 'Отчёт менеджера сохранён');
}

async function applyOutreachBulkAction() {
    const ids = Array.from(outreachSelectedIds);
    if (!ids.length && outreachSelectedId) ids.push(Number(outreachSelectedId));
    if (!ids.length) return customAlert('Выбери хотя бы одну строку.');
    const managerEmail = document.getElementById('outreachBulkManager')?.value || '';
    const payload = {
        ids,
        action: 'apply',
        manager_email: managerEmail,
        manager_name: outreachFindManagerNameByEmail(managerEmail),
        planned_contact_date: document.getElementById('outreachBulkPlanDate')?.value || '',
        status: document.getElementById('outreachBulkStatus')?.value || '',
        note: document.getElementById('outreachBulkNote')?.value || '',
    };
    const res = await apiCall('/outreach/prospects/bulk', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось применить массовое действие.');
    outreachSelectedIds.clear();
    await renderProspecting(true);
}

async function markOutreachProcessed(prospectId) {
    const res = await apiCall('/outreach/prospects/bulk', 'POST', {
        ids: [Number(prospectId || 0)],
        action: 'mark_processed',
        status: 'in_progress',
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось обновить статус.');
    await renderProspecting(true);
}

async function convertOutreachProspect(prospectId) {
    const res = await apiCall(`/outreach/prospects/${Number(prospectId || 0)}/convert`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось перевести запись в лид.');
    await Promise.all([loadOutreachProspects(), loadCrmLeads()]);
    showToast('База развития', 'Запись переведена в лид');
    if (typeof navigateTo === 'function') navigateTo('leads');
}

async function parseOutreachFile(file) {
    const lower = String(file?.name || '').toLowerCase();
    if (!file) return [];
    if (lower.endsWith('.json')) {
        const text = await file.text();
        const parsed = JSON.parse(text || '[]');
        return Array.isArray(parsed) ? parsed : [];
    }
    if (lower.endsWith('.txt')) {
        const text = await file.text();
        if (!/[,\t;]/.test(text)) {
            return text.split('\n').map(line => line.trim()).filter(Boolean).map(line => ({ company_name: line }));
        }
    }
    if (typeof XLSX === 'undefined') {
        throw new Error('Библиотека XLSX не загружена');
    }
    const buffer = await file.arrayBuffer();
    const workbook = XLSX.read(buffer, { type: 'array' });
    const firstSheet = workbook.SheetNames?.[0];
    if (!firstSheet) return [];
    return XLSX.utils.sheet_to_json(workbook.Sheets[firstSheet], { defval: '' });
}

async function importOutreachFile() {
    const fileInput = document.getElementById('outreachImportFile');
    const file = fileInput?.files?.[0];
    if (!file) return customAlert('Выбери файл со списком клиентов.');
    let rows = [];
    try {
        rows = await parseOutreachFile(file);
    } catch (error) {
        return customAlert(`Не удалось прочитать файл: ${error?.message || error}`);
    }
    if (!Array.isArray(rows) || !rows.length) return customAlert('Файл не содержит строк для загрузки.');
    const managerEmail = document.getElementById('outreachImportManager')?.value || '';
    const payload = {
        filename: file.name,
        source_name: document.getElementById('outreachImportSource')?.value || '',
        default_manager_email: managerEmail,
        default_manager_name: outreachFindManagerNameByEmail(managerEmail),
        planned_contact_date: document.getElementById('outreachImportPlanDate')?.value || '',
        rows,
    };
    const res = await apiCall('/outreach/prospects/import_rows', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось загрузить базу.');
    if (fileInput) fileInput.value = '';
    showToast('База развития', `Импорт завершён: +${Number(res.created || 0)}, обновлено ${Number(res.updated || 0)}`);
    await renderProspecting(true);
}

async function renderProspecting(forceReload = false) {
    await ensureOutreachData(forceReload);
    renderOutreachManagerSelects();
    syncOutreachFilterControls();
    renderOutreachSummary();
    renderOutreachReportPanel();
    const overdueBtn = document.getElementById('outreachOverdueBtn');
    const todayBtn = document.getElementById('outreachTodayBtn');
    if (overdueBtn) overdueBtn.classList.toggle('btn-primary', outreachOnlyOverdue);
    if (todayBtn) todayBtn.classList.toggle('btn-primary', outreachOnlyToday);
    const mount = document.getElementById('prospectingContentMount');
    if (mount) mount.innerHTML = renderOutreachRegistry();
}

window.renderProspecting = renderProspecting;
window.openOutreachEditor = openOutreachEditor;
window.closeOutreachEditor = closeOutreachEditor;
window.saveOutreachProspect = saveOutreachProspect;
window.selectOutreachRow = selectOutreachRow;
window.toggleOutreachSelection = toggleOutreachSelection;
window.toggleAllOutreachSelection = toggleAllOutreachSelection;
window.applyOutreachSearch = applyOutreachSearch;
window.setOutreachStatusFilter = setOutreachStatusFilter;
window.setOutreachPriorityFilter = setOutreachPriorityFilter;
window.setOutreachManagerFilter = setOutreachManagerFilter;
window.setOutreachProcessedFilter = setOutreachProcessedFilter;
window.toggleOutreachOverdueFilter = toggleOutreachOverdueFilter;
window.toggleOutreachTodayFilter = toggleOutreachTodayFilter;
window.resetOutreachFilters = resetOutreachFilters;
window.importOutreachFile = importOutreachFile;
window.applyOutreachBulkAction = applyOutreachBulkAction;
window.saveOutreachActivity = saveOutreachActivity;
window.saveOutreachReport = saveOutreachReport;
window.markOutreachProcessed = markOutreachProcessed;
window.convertOutreachProspect = convertOutreachProspect;
