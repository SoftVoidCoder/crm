let outreachProspectsDB = [];
let outreachReportsDB = [];
let outreachImportsDB = [];
let outreachControlDB = [];
let outreachSelectedId = 0;
let outreachEditingId = 0;
let outreachClientEditMode = false;
let outreachSearch = '';
let outreachStatusFilter = '';
let outreachPriorityFilter = '';
let outreachManagerFilter = '';
let outreachProcessedFilter = '';
let outreachOnlyOverdue = false;
let outreachOnlyToday = false;
let outreachOnlyProblems = false;
let outreachQuickFilter = '';
let outreachSelectedIds = new Set();
let outreachReportExpanded = false;
let outreachLastImportResult = null;
let outreachImportPreview = null;
let outreachBitrixResults = [];
let outreachBitrixRows = null;
let outreachBitrixSelected = new Set();
let outreachBitrixLoading = false;
let outreachBitrixImporting = false;
let outreachBitrixAction = '';
let outreachBitrixConnection = null;
let outreachBitrixConnectionBusy = false;
let outreachBitrixStatusLoading = false;
let outreachBitrixStatusRequest = null;
let outreachLoadedScope = '';
let outreachPoolRows = [];
let outreachPoolSearch = '';
let outreachPoolRefreshTimer = 0;

const OUTREACH_KNOWLEDGE_BLOCKS = [
    {
        title: 'Адреса и реквизиты',
        text: 'Единый источник для КП, писем, договоров и тендерных пакетов.',
        items: ['юридический адрес', 'почтовый адрес', 'ИНН/КПП', 'типовая подпись'],
    },
    {
        title: 'Шаблоны писем',
        text: 'Готовые формулировки для первого касания, повторного письма и дожима тёплого клиента.',
        items: ['первое письмо', 'follow-up', 'после звонка', 'запрос документов'],
    },
    {
        title: 'Корпоративный стиль',
        text: 'Одинаковый тон общения: коротко, по делу, без свободных обещаний и лишних скидок.',
        items: ['тон письма', 'запрещённые формулировки', 'подпись', 'вложения'],
    },
];

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
        role: String(user.role || '').trim(),
    })).filter(user => user.name || user.email);
    if (currentUser?.name || currentUser?.email) {
        names.push({ name: String(currentUser.name || '').trim(), email: String(currentUser.email || '').trim(), role: String(currentUser.role || '').trim() });
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

function outreachIsSupervisor() {
    return String(currentUser?.role || '') === 'Директор' || Number(currentUser?.is_head || 0) === 1;
}

function outreachManagerMatches(row, manager) {
    const rowEmail = String(row?.manager_email || '').trim().toLowerCase();
    const rowName = String(row?.manager_name || '').trim().toLowerCase();
    const managerEmail = String(manager?.email || '').trim().toLowerCase();
    const managerName = String(manager?.name || '').trim().toLowerCase();
    return (managerEmail && rowEmail === managerEmail) || (!managerEmail && managerName && rowName === managerName);
}

function outreachActivityIsToday(activity, today = outreachToday()) {
    const activityDate = Number(activity?.created_at || 0) ? new Date(Number(activity.created_at || 0) * 1000) : null;
    if (!activityDate) return false;
    const key = `${String(activityDate.getDate()).padStart(2, '0')}.${String(activityDate.getMonth() + 1).padStart(2, '0')}.${activityDate.getFullYear()}`;
    return key === today;
}

function outreachReportForManager(manager, today = outreachToday()) {
    const managerEmail = String(manager?.email || '').trim().toLowerCase();
    const managerName = String(manager?.name || '').trim().toLowerCase();
    return (outreachReportsDB || []).find(report => {
        if (String(report.report_date || '') !== today) return false;
        const reportEmail = String(report.manager_email || '').trim().toLowerCase();
        const reportName = String(report.manager_name || '').trim().toLowerCase();
        return (managerEmail && reportEmail === managerEmail) || (!managerEmail && managerName && reportName === managerName);
    }) || null;
}

function buildOutreachManagerControlRows() {
    const today = outreachToday();
    const managers = new Map();
    const addManager = (name, email, role = '') => {
        const key = String(email || name || '').trim().toLowerCase();
        if (!key) return;
        if (!managers.has(key)) managers.set(key, { name: String(name || '').trim(), email: String(email || '').trim(), role: String(role || '').trim() });
    };
    (outreachProspectsDB || []).forEach(row => addManager(row.manager_name, row.manager_email, ''));
    (outreachReportsDB || []).filter(report => report.report_date === today).forEach(report => addManager(report.manager_name, report.manager_email, ''));
    return Array.from(managers.values()).map(manager => {
        const rows = (outreachProspectsDB || []).filter(row => outreachManagerMatches(row, manager));
        const report = outreachReportForManager(manager, today);
        let callsToday = 0;
        let emailsToday = 0;
        rows.forEach(row => {
            (Array.isArray(row.activities) ? row.activities : []).forEach(activity => {
                if (!outreachActivityIsToday(activity, today)) return;
                if (activity.activity_type === 'call') callsToday += 1;
                if (activity.activity_type === 'email') emailsToday += 1;
            });
        });
        const processedToday = rows.filter(row => String(row.last_contact_at || '').startsWith(today)).length;
        const convertedToday = rows.filter(row => String(row.status || '') === 'converted' && String(row.last_contact_at || '').startsWith(today)).length;
        return {
            ...manager,
            report,
            plan: Number(report?.plan_total ?? rows.filter(row => row.is_due_today).length),
            processed: Number(report?.processed_total ?? processedToday),
            calls: Number(report?.calls_total ?? callsToday),
            emails: Number(report?.emails_total ?? emailsToday),
            overdue: rows.filter(row => row.is_overdue).length,
            first_contact_overdue: rows.filter(row => row.is_first_contact_overdue).length,
            warm: rows.filter(row => ['warm', 'meeting'].includes(String(row.status || ''))).length,
            leads: Number(report?.converted_total ?? convertedToday),
            submitted: !!report,
        };
    }).sort((a, b) => (Number(a.submitted) - Number(b.submitted)) || (b.overdue - a.overdue) || String(a.name || a.email).localeCompare(String(b.name || b.email), 'ru'));
}

function outreachManagerConversion(row) {
    const processed = Number(row?.processed || 0);
    const warm = Number(row?.warm || 0);
    const leads = Number(row?.leads || 0);
    if (!processed) return { warmRate: 0, leadRate: 0, label: '0%' };
    const warmRate = Math.round((warm / processed) * 100);
    const leadRate = Math.round((leads / processed) * 100);
    return { warmRate, leadRate, label: `${leadRate}%` };
}

function outreachManagerQuality(row) {
    const plan = Number(row?.plan || 0);
    const processed = Number(row?.processed || 0);
    const overdue = Number(row?.overdue || 0);
    const firstContactOverdue = Number(row?.first_contact_overdue || row?.firstContactOverdue || 0);
    const calls = Number(row?.calls || 0);
    const emails = Number(row?.emails || 0);
    const submitted = !!row?.submitted;
    const conversion = outreachManagerConversion(row);
    const planRate = plan ? Math.min(140, Math.round((processed / plan) * 100)) : (processed ? 100 : 0);
    const flags = [];
    let score = 100;
    if (!submitted) {
        score -= 28;
        flags.push('нет отчёта');
    }
    if (plan && processed < plan) {
        score -= Math.min(28, Math.round(((plan - processed) / plan) * 28));
        flags.push(`план ${planRate}%`);
    }
    if (overdue) {
        score -= Math.min(20, overdue * 4);
        flags.push(`просрочки ${overdue}`);
    }
    if (firstContactOverdue) {
        score -= Math.min(18, firstContactOverdue * 6);
        flags.push(`SLA ${firstContactOverdue}`);
    }
    if (processed > 0 && calls + emails === 0) {
        score -= 10;
        flags.push('нет касаний');
    }
    if (processed >= 5 && conversion.warmRate === 0) {
        score -= 8;
        flags.push('нет тёплых');
    }
    score = Math.max(0, Math.min(100, score));
    const tone = score >= 82 ? 'positive' : score >= 62 ? 'attention' : 'critical';
    const label = score >= 82 ? 'Хорошо' : score >= 62 ? 'Контроль' : 'Риск';
    let recommendation = 'Оставить в плане, держит рабочий ритм.';
    if (!submitted) recommendation = 'Потребовать дневной отчёт до конца дня.';
    else if (firstContactOverdue) recommendation = 'Разобрать SLA первого касания и переназначить хвосты.';
    else if (overdue) recommendation = 'Снять просрочки и поставить следующий шаг.';
    else if (plan && processed < plan) recommendation = 'Дожать план-факт и зафиксировать причины отставания.';
    else if (processed && !conversion.leadRate) recommendation = 'Проверить качество разговоров и тёплые переходы.';
    return { score, tone, label, flags, recommendation, planRate };
}

function buildOutreachReportAnalysis(rows = []) {
    const analyzed = rows.map(row => ({ row, quality: outreachManagerQuality(row) }));
    const avgScore = analyzed.length ? Math.round(analyzed.reduce((sum, item) => sum + item.quality.score, 0) / analyzed.length) : 0;
    return {
        avgScore,
        riskManagers: analyzed.filter(item => item.quality.score < 62).length,
        needControl: analyzed.filter(item => item.quality.score >= 62 && item.quality.score < 82).length,
        okManagers: analyzed.filter(item => item.quality.score >= 82).length,
        topFlags: analyzed.flatMap(item => item.quality.flags).slice(0, 8),
    };
}

function buildOutreachDepartmentMetrics(rows = []) {
    return rows.reduce((acc, row) => {
        acc.plan += Number(row.plan || 0);
        acc.processed += Number(row.processed || 0);
        acc.calls += Number(row.calls || 0);
        acc.emails += Number(row.emails || 0);
        acc.overdue += Number(row.overdue || 0);
        acc.firstContactOverdue += Number(row.first_contact_overdue || row.firstContactOverdue || 0);
        acc.warm += Number(row.warm || 0);
        acc.leads += Number(row.leads || 0);
        return acc;
    }, { plan: 0, processed: 0, calls: 0, emails: 0, overdue: 0, firstContactOverdue: 0, warm: 0, leads: 0 });
}

function outreachCleanPhone(value) {
    const digits = String(value || '').replace(/\D+/g, '');
    return digits ? digits.slice(-11) : '';
}

function buildOutreachQualityMetrics() {
    const rows = Array.isArray(outreachProspectsDB) ? outreachProspectsDB : [];
    const closed = new Set(['converted', 'archived', 'do_not_contact']);
    const duplicateGroups = new Map();
    rows.forEach(row => {
        const email = String(row.email || '').trim().toLowerCase();
        const company = String(row.company_name || '').trim().toLowerCase();
        const phone = outreachCleanPhone(row.phone);
        const key = email ? `email:${email}` : (company && phone ? `company_phone:${company}:${phone}` : '');
        if (!key) return;
        duplicateGroups.set(key, (duplicateGroups.get(key) || 0) + 1);
    });
    const duplicateRows = Array.from(duplicateGroups.values()).filter(count => count > 1).reduce((sum, count) => sum + count, 0);
    return {
        noContact: rows.filter(row => !String(row.phone || '').trim() && !String(row.email || '').trim()).length,
        noManager: rows.filter(row => !String(row.manager_name || '').trim() && !String(row.manager_email || '').trim()).length,
        duplicates: duplicateRows,
        firstContactOverdue: rows.filter(row => row.is_first_contact_overdue).length,
        noNextStep: rows.filter(row => !closed.has(String(row.status || '')) && !String(row.next_action || '').trim() && !String(row.next_action_date || '').trim()).length,
    };
}

function outreachRowHasProblem(row) {
    const closed = new Set(['converted', 'archived', 'do_not_contact']);
    const noContact = !String(row?.phone || '').trim() && !String(row?.email || '').trim();
    const noManager = !String(row?.manager_name || '').trim() && !String(row?.manager_email || '').trim();
    const noNextStep = !closed.has(String(row?.status || '')) && !String(row?.next_action || '').trim() && !String(row?.next_action_date || '').trim();
    return noContact || noManager || !!row?.is_first_contact_overdue || noNextStep;
}

function outreachClientDossier(row) {
    const activities = Array.isArray(row?.activities) ? row.activities : [];
    const checks = [
        { label: 'Компания', ok: !!String(row?.company_name || '').trim() },
        { label: 'Контакт', ok: !!String(row?.contact_name || '').trim() },
        { label: 'Телефон/email', ok: !!String(row?.phone || row?.email || '').trim() },
        { label: 'Ответственный', ok: !!String(row?.manager_name || row?.manager_email || '').trim() },
        { label: 'Источник', ok: !!String(row?.source_name || '').trim() },
        { label: 'Следующий шаг', ok: !!String(row?.next_action || row?.next_action_date || '').trim() },
        { label: 'История касаний', ok: activities.length > 0 },
        { label: 'Комментарий', ok: !!String(row?.notes || '').trim() },
    ];
    const ready = checks.filter(item => item.ok).length;
    const score = Math.round((ready / checks.length) * 100);
    const tone = score >= 80 ? 'positive' : score >= 55 ? 'attention' : 'critical';
    const missing = checks.filter(item => !item.ok).map(item => item.label.toLowerCase());
    return { checks, score, tone, missing };
}

function buildOutreachLossReasons() {
    const rows = Array.isArray(outreachProspectsDB) ? outreachProspectsDB : [];
    const quality = buildOutreachQualityMetrics();
    return {
        noAnswer: rows.filter(row => String(row.status || '') === 'no_answer' || String(row.last_result || '') === 'no_answer').length,
        notInterested: rows.filter(row => String(row.status || '') === 'do_not_contact' || String(row.last_result || '') === 'do_not_contact').length,
        noContacts: quality.noContact,
        duplicates: quality.duplicates,
        archived: rows.filter(row => String(row.status || '') === 'archived').length,
    };
}

function buildOutreachImportProtocol(source) {
    const latest = source || outreachImportPreview || outreachLastImportResult || (outreachImportsDB || [])[0] || null;
    if (!latest) return [];
    const rowsTotal = Number(latest.rows_total ?? latest.rows ?? 0);
    const recognized = Number(latest.recognized_columns || 0);
    const totalColumns = Number(latest.columns_total || 0);
    const created = Number(latest.created_total ?? latest.created ?? 0);
    const updated = Number(latest.updated_total ?? latest.updated ?? 0);
    const skipped = Number(latest.skipped_total ?? latest.skipped ?? latest.problem_rows ?? 0);
    const problemRows = Number(latest.problem_rows ?? skipped);
    return [
        { label: 'Файл прочитан', ok: rowsTotal > 0, value: `${rowsTotal} строк` },
        { label: 'Колонки распознаны', ok: !totalColumns || recognized >= Math.min(totalColumns, 6), value: totalColumns ? `${recognized}/${totalColumns}` : 'история' },
        { label: 'Дубли обработаны', ok: updated >= 0, value: `${updated} обновлено` },
        { label: 'Новые записи созданы', ok: created > 0 || updated > 0, value: `${created} создано` },
        { label: 'Проблемные строки выделены', ok: problemRows === 0, value: `${problemRows} проблем` },
    ];
}

function outreachCsvEscape(value) {
    const raw = String(value ?? '');
    return /[",\n;]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

function downloadOutreachBlob(filename, mime, content) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

function exportOutreachDirectorReport() {
    const rows = (Array.isArray(outreachControlDB) && outreachControlDB.length) ? outreachControlDB : buildOutreachManagerControlRows();
    const dept = buildOutreachDepartmentMetrics(rows);
    const quality = buildOutreachQualityMetrics();
    const loss = buildOutreachLossReasons();
    const pushList = buildOutreachPushList(20);
    const dateKey = outreachToday().replace(/\./g, '-');
    const managerRows = rows.map(row => {
        const conversion = outreachManagerConversion(row);
        const managerQuality = outreachManagerQuality(row);
        return {
            'Менеджер': row.name || row.email || 'Без имени',
            'Email': row.email || '',
            'План': Number(row.plan || 0),
            'Обработано': Number(row.processed || 0),
            'Звонки': Number(row.calls || 0),
            'Письма': Number(row.emails || 0),
            'Просрочено': Number(row.overdue || 0),
            'SLA 24ч нарушено': Number(row.first_contact_overdue || row.firstContactOverdue || 0),
            'Тёплые': Number(row.warm || 0),
            'Лиды': Number(row.leads || 0),
            'Конверсия в лид, %': Number(conversion.leadRate || 0),
            'Отчёт': row.submitted ? 'Сдан' : 'Нет',
            'Качество, %': managerQuality.score,
            'Контрольные флаги': managerQuality.flags.join(', '),
            'Рекомендация': managerQuality.recommendation,
        };
    });
    if (window.XLSX?.utils && window.XLSX?.writeFile) {
        const workbook = window.XLSX.utils.book_new();
        window.XLSX.utils.book_append_sheet(workbook, window.XLSX.utils.json_to_sheet([{
            'Дата': outreachToday(),
            'План отдела': dept.plan,
            'Обработано': dept.processed,
            'Звонки': dept.calls,
            'Письма': dept.emails,
            'Тёплые': dept.warm,
            'Лиды': dept.leads,
            'Просрочки': dept.overdue,
            'SLA 24ч нарушено': dept.firstContactOverdue,
        }]), 'Сводка');
        window.XLSX.utils.book_append_sheet(workbook, window.XLSX.utils.json_to_sheet(managerRows), 'Менеджеры');
        window.XLSX.utils.book_append_sheet(workbook, window.XLSX.utils.json_to_sheet([
            { 'Показатель': 'Без телефона/email', 'Значение': quality.noContact },
            { 'Показатель': 'Без ответственного', 'Значение': quality.noManager },
            { 'Показатель': 'Дубли', 'Значение': quality.duplicates },
            { 'Показатель': 'SLA первого контакта', 'Значение': quality.firstContactOverdue },
            { 'Показатель': 'Нет следующего шага', 'Значение': quality.noNextStep },
            { 'Показатель': 'Не дозвонились', 'Значение': loss.noAnswer },
            { 'Показатель': 'Не интересно', 'Значение': loss.notInterested },
            { 'Показатель': 'Архив', 'Значение': loss.archived },
        ]), 'Качество');
        window.XLSX.utils.book_append_sheet(workbook, window.XLSX.utils.json_to_sheet(pushList.map(row => ({
            'Компания': row.company_name || '',
            'Контакт': row.contact_name || '',
            'Телефон': row.phone || '',
            'Email': row.email || '',
            'Статус': outreachStatusLabel(row.status),
            'Дата шага': row.next_action_date || row.planned_contact_date || '',
            'Менеджер': row.manager_name || row.manager_email || '',
        }))), 'Дожать сегодня');
        window.XLSX.writeFile(workbook, `korda_outreach_director_report_${dateKey}.xlsx`);
        return;
    }
    const headers = Object.keys(managerRows[0] || {
        'Менеджер': '', 'Email': '', 'План': '', 'Обработано': '', 'Звонки': '', 'Письма': '', 'Просрочено': '', 'SLA 24ч нарушено': '', 'Тёплые': '', 'Лиды': '', 'Конверсия в лид, %': '', 'Отчёт': '', 'Качество, %': '', 'Контрольные флаги': '', 'Рекомендация': '',
    });
    const csv = [headers.join(';')]
        .concat(managerRows.map(row => headers.map(header => outreachCsvEscape(row[header])).join(';')))
        .join('\n');
    downloadOutreachBlob(`korda_outreach_director_report_${dateKey}.csv`, 'text/csv;charset=utf-8', `\uFEFF${csv}`);
}

function buildOutreachPushList(limit = 8) {
    const today = outreachToday();
    const priority = { meeting: 1, warm: 2, follow_up: 3, no_answer: 4 };
    return (Array.isArray(outreachProspectsDB) ? outreachProspectsDB : [])
        .filter(row => ['warm', 'meeting', 'follow_up', 'no_answer'].includes(String(row.status || '')) || row.is_due_today || row.is_overdue)
        .filter(row => !['converted', 'archived', 'do_not_contact'].includes(String(row.status || '')))
        .sort((a, b) => {
            const aScore = (a.is_overdue ? 0 : a.is_due_today ? 1 : 2) + (priority[a.status] || 9);
            const bScore = (b.is_overdue ? 0 : b.is_due_today ? 1 : 2) + (priority[b.status] || 9);
            return aScore - bScore || String(a.next_action_date || a.planned_contact_date || today).localeCompare(String(b.next_action_date || b.planned_contact_date || today), 'ru');
        })
        .slice(0, limit);
}

function parseOutreachDelimitedText(text, delimiter = ',') {
    const rows = [];
    let current = '';
    let row = [];
    let quoted = false;
    const raw = String(text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    for (let index = 0; index < raw.length; index += 1) {
        const char = raw[index];
        const next = raw[index + 1];
        if (char === '"') {
            if (quoted && next === '"') {
                current += '"';
                index += 1;
            } else {
                quoted = !quoted;
            }
            continue;
        }
        if (char === delimiter && !quoted) {
            row.push(current);
            current = '';
            continue;
        }
        if (char === '\n' && !quoted) {
            row.push(current);
            if (row.some(cell => String(cell || '').trim())) rows.push(row);
            row = [];
            current = '';
            continue;
        }
        current += char;
    }
    row.push(current);
    if (row.some(cell => String(cell || '').trim())) rows.push(row);
    if (!rows.length) return [];
    const headers = rows[0].map((cell, idx) => String(cell || '').trim() || `field_${idx + 1}`);
    return rows.slice(1).map(cells => {
        const item = {};
        headers.forEach((header, idx) => {
            item[header] = String(cells[idx] ?? '').trim();
        });
        return item;
    }).filter(item => Object.values(item).some(value => String(value || '').trim()));
}

function detectOutreachDelimiter(text, filename = '') {
    const lower = String(filename || '').toLowerCase();
    if (lower.endsWith('.tsv')) return '\t';
    const sample = String(text || '').split(/\r?\n/).slice(0, 5).join('\n');
    const variants = [
        { delimiter: '\t', count: (sample.match(/\t/g) || []).length },
        { delimiter: ';', count: (sample.match(/;/g) || []).length },
        { delimiter: ',', count: (sample.match(/,/g) || []).length },
    ];
    variants.sort((a, b) => b.count - a.count);
    return variants[0].count ? variants[0].delimiter : ',';
}

async function loadOutreachProspects(scope = '') {
    const scopeQuery = scope ? `?scope=${encodeURIComponent(scope)}` : '';
    const data = await apiCall(`/outreach/prospects${scopeQuery}`);
    outreachProspectsDB = Array.isArray(data) ? data : [];
    outreachLoadedScope = scope || 'all';
    return outreachProspectsDB;
}

async function loadOutreachReports() {
    const data = await apiCall('/outreach/reports');
    outreachReportsDB = Array.isArray(data) ? data : [];
    return outreachReportsDB;
}

async function loadOutreachControl() {
    if (!outreachIsSupervisor()) {
        outreachControlDB = [];
        return outreachControlDB;
    }
    const data = await apiCall('/outreach/manager_control');
    outreachControlDB = Array.isArray(data) ? data : [];
    return outreachControlDB;
}

async function loadOutreachImports() {
    const data = await apiCall('/outreach/imports');
    outreachImportsDB = Array.isArray(data) ? data : [];
    return outreachImportsDB;
}

async function ensureOutreachData(force = false, scope = 'mine') {
    if (!Array.isArray(allUsersDB) || !allUsersDB.length) {
        await loadAllUsers();
    }
    if (force || outreachLoadedScope !== scope || !Array.isArray(outreachProspectsDB)) {
        await loadOutreachProspects(scope);
    }
    if (force || !Array.isArray(outreachReportsDB)) {
        await loadOutreachReports();
    }
    if (force || (outreachIsSupervisor() && (!Array.isArray(outreachControlDB) || !outreachControlDB.length))) {
        await loadOutreachControl();
    }
    if (force || !Array.isArray(outreachImportsDB)) {
        await loadOutreachImports();
    }
}

function filteredOutreachRows() {
    const searchNeedle = outreachSearch.trim().toLowerCase();
    return (outreachProspectsDB || []).filter(row => {
        if (outreachQuickFilter === 'called' && String(row.last_channel || '') !== 'call') return false;
        if (outreachQuickFilter === 'emailed' && String(row.last_channel || '') !== 'email') return false;
        if (outreachQuickFilter === 'no_answer' && String(row.status || '') !== 'no_answer' && String(row.last_result || '') !== 'no_answer') return false;
        if (outreachQuickFilter === 'warm' && !['warm', 'meeting'].includes(String(row.status || '')) && String(row.last_result || '') !== 'warm') return false;
        if (outreachQuickFilter === 'converted' && String(row.status || '') !== 'converted') return false;
        if (outreachStatusFilter && String(row.status || '') !== outreachStatusFilter) return false;
        if (outreachPriorityFilter && String(row.priority || '') !== outreachPriorityFilter) return false;
        if (outreachManagerFilter && String(row.manager_email || '') !== outreachManagerFilter) return false;
        if (outreachProcessedFilter === 'yes' && Number(row.is_processed || 0) !== 1) return false;
        if (outreachProcessedFilter === 'no' && Number(row.is_processed || 0) !== 0) return false;
        if (outreachOnlyOverdue && !row.is_overdue) return false;
        if (outreachOnlyToday && !row.is_due_today) return false;
        if (outreachOnlyProblems && !outreachRowHasProblem(row)) return false;
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
    const overdue = rows.filter(row => row.is_overdue).length;
    const today = rows.filter(row => row.is_due_today).length;
    const warm = rows.filter(row => ['warm', 'meeting'].includes(String(row.status || ''))).length;
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Мои клиенты</div><div class="crm-summary-value">${rows.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Связаться сегодня</div><div class="crm-summary-value">${today}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Просрочено</div><div class="crm-summary-value">${overdue}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Есть интерес</div><div class="crm-summary-value">${warm}</div></div>
    `;
}

function renderOutreachDirectorPanel() {
    const mount = document.getElementById('outreachDirectorPanel');
    if (!mount) return;
    if (!outreachIsSupervisor()) {
        mount.innerHTML = '';
        return;
    }
    const rows = (Array.isArray(outreachControlDB) && outreachControlDB.length) ? outreachControlDB : buildOutreachManagerControlRows();
    const missing = rows.filter(row => !row.submitted);
    const dept = buildOutreachDepartmentMetrics(rows);
    const quality = buildOutreachQualityMetrics();
    const loss = buildOutreachLossReasons();
    const pushList = buildOutreachPushList();
    const reportAnalysis = buildOutreachReportAnalysis(rows);
    const departmentPlanFact = dept.plan ? Math.round((dept.processed / dept.plan) * 100) : 0;
    mount.innerHTML = `
        <section class="prospecting-control-panel">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Контроль менеджеров сегодня</h3>
                    <p class="section-subtitle">План-факт отдела, качество базы, дожим и сдача отчётов.</p>
                </div>
                <div class="crm-toolbar__group">
                    <button class="btn-secondary" onclick="exportOutreachDirectorReport()">Скачать отчёт</button>
                    <span class="crm-inline-pill crm-inline-pill--${missing.length ? 'critical' : 'positive'}">Не сдали отчёт: ${missing.length}</span>
                </div>
            </div>
            <div class="prospecting-dept-strip">
                <div><span>План отдела</span><strong>${dept.plan}</strong></div>
                <div><span>Обработано</span><strong>${dept.processed}</strong><small>${departmentPlanFact}% плана</small></div>
                <div><span>Звонки</span><strong>${dept.calls}</strong></div>
                <div><span>Письма</span><strong>${dept.emails}</strong></div>
                <div><span>Тёплые</span><strong>${dept.warm}</strong></div>
                <div><span>Лиды</span><strong>${dept.leads}</strong></div>
                <div><span>Просрочки</span><strong>${dept.overdue}</strong></div>
                <div><span>SLA 24ч</span><strong>${dept.firstContactOverdue}</strong></div>
                <div><span>Качество отчётов</span><strong>${reportAnalysis.avgScore}%</strong><small>${reportAnalysis.riskManagers} в риске</small></div>
            </div>
            <div class="prospecting-control-layout">
                <div class="table-shell prospecting-control-table">
                    <table class="admin-table admin-table--dense">
                        <thead>
                            <tr>
                                <th>Менеджер</th>
                                <th class="is-num">План</th>
                                <th class="is-num">Обработано</th>
                                <th class="is-num">Звонки</th>
                                <th class="is-num">Письма</th>
                                <th class="is-num">Просрочено</th>
                                <th class="is-num">SLA 24ч</th>
                                <th class="is-num">Тёплые</th>
                                <th class="is-num">Лиды</th>
                                <th>Конверсия</th>
                                <th>Отчёт</th>
                                <th>Качество</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rows.map(row => {
                                const conversion = outreachManagerConversion(row);
                                const managerQuality = outreachManagerQuality(row);
                                return `
                                <tr>
                                    <td class="crm-title-cell"><strong>${outreachEscape(row.name || row.email || 'Без имени')}</strong><div class="table-subtext">${outreachEscape(row.email || 'email не указан')}</div></td>
                                    <td class="is-num">${row.plan}</td>
                                    <td class="is-num">${row.processed}</td>
                                    <td class="is-num">${row.calls}</td>
                                    <td class="is-num">${row.emails}</td>
                                    <td class="is-num"><span class="crm-inline-pill crm-inline-pill--${row.overdue ? 'critical' : 'neutral'}">${row.overdue}</span></td>
                                    <td class="is-num"><span class="crm-inline-pill crm-inline-pill--${Number(row.first_contact_overdue || row.firstContactOverdue || 0) ? 'critical' : 'neutral'}">${Number(row.first_contact_overdue || row.firstContactOverdue || 0)}</span></td>
                                    <td class="is-num">${row.warm}</td>
                                    <td class="is-num">${row.leads}</td>
                                    <td><span class="crm-inline-pill crm-inline-pill--${conversion.leadRate ? 'positive' : conversion.warmRate ? 'attention' : 'neutral'}">${conversion.label}</span><div class="table-subtext">${row.processed} / ${row.warm} / ${row.leads}</div></td>
                                    <td><span class="crm-inline-pill crm-inline-pill--${row.submitted ? 'positive' : 'critical'}">${row.submitted ? 'Сдан' : 'Нет'}</span></td>
                                    <td>
                                        <span class="crm-inline-pill crm-inline-pill--${managerQuality.tone}">${managerQuality.score}% · ${outreachEscape(managerQuality.label)}</span>
                                        <div class="table-subtext">${outreachEscape(managerQuality.recommendation)}</div>
                                    </td>
                                </tr>
                            `; }).join('') || '<tr><td colspan="12"><div class="empty-state">Менеджеры пока не назначены.</div></td></tr>'}
                        </tbody>
                    </table>
                </div>
                <div class="prospecting-control-side">
                    <div class="prospecting-quality-card">
                        <div class="prospecting-side-title">Автоанализ отчётов</div>
                        <div class="prospecting-quality-grid">
                            <div><span>Среднее качество</span><strong>${reportAnalysis.avgScore}%</strong></div>
                            <div><span>В риске</span><strong>${reportAnalysis.riskManagers}</strong></div>
                            <div><span>На контроле</span><strong>${reportAnalysis.needControl}</strong></div>
                            <div><span>Без замечаний</span><strong>${reportAnalysis.okManagers}</strong></div>
                        </div>
                        <div class="prospecting-mini-list">
                            ${reportAnalysis.topFlags.map(flag => `<span>${outreachEscape(flag)}</span>`).join('') || '<span>Критичных флагов нет</span>'}
                        </div>
                    </div>
                    <div class="prospecting-quality-card">
                        <div class="prospecting-side-title">Качество базы</div>
                        <div class="prospecting-quality-grid">
                            <div><span>Без телефона/email</span><strong>${quality.noContact}</strong></div>
                            <div><span>Без ответственного</span><strong>${quality.noManager}</strong></div>
                            <div><span>Дубли</span><strong>${quality.duplicates}</strong></div>
                            <div><span>SLA первого контакта</span><strong>${quality.firstContactOverdue}</strong></div>
                            <div><span>Нет следующего шага</span><strong>${quality.noNextStep}</strong></div>
                        </div>
                    </div>
                    <div class="prospecting-loss-card">
                        <div class="prospecting-side-title">Причины потерь</div>
                        <div class="prospecting-loss-grid">
                            <div><span>Не дозвонились</span><strong>${loss.noAnswer}</strong></div>
                            <div><span>Не интересно</span><strong>${loss.notInterested}</strong></div>
                            <div><span>Нет контактов</span><strong>${loss.noContacts}</strong></div>
                            <div><span>Дубли</span><strong>${loss.duplicates}</strong></div>
                            <div><span>Архив</span><strong>${loss.archived}</strong></div>
                        </div>
                    </div>
                    <div class="prospecting-missing-report">
                        <div class="prospecting-side-title">Кто не сдал отчёт</div>
                        ${missing.slice(0, 8).map(row => `<div class="prospecting-missing-report__item"><strong>${outreachEscape(row.name || row.email || 'Менеджер')}</strong><span>${row.overdue} просрочено · ${row.warm} тёплых</span></div>`).join('') || '<div class="empty-state">Все отчёты за сегодня сданы.</div>'}
                    </div>
                    <div class="prospecting-push-list">
                        <div class="prospecting-side-title">Дожать сегодня</div>
                        ${pushList.map(row => `
                            <button type="button" class="prospecting-push-item" onclick="selectOutreachRow(${Number(row.id || 0)})">
                                <strong>${outreachEscape(row.company_name || 'Без компании')}</strong>
                                <span>${outreachEscape(outreachStatusLabel(row.status))} · ${outreachEscape(row.next_action_date || row.planned_contact_date || 'без даты')}</span>
                            </button>
                        `).join('') || '<div class="empty-state">Нет срочных клиентов на дожим.</div>'}
                    </div>
                </div>
            </div>
        </section>
    `;
}

function askOutreachAssistant(text) {
    const prompt = String(text || '').trim();
    if (!prompt) return;
    if (window.kordaAssistant?.ask) {
        window.kordaAssistant.ask(prompt);
    } else if (window.crmAssistantAsk) {
        window.crmAssistantAsk(prompt);
    } else {
        customAlert('Ассистент пока не загружен.');
    }
}

function renderOutreachKnowledgePanel() {
    const mount = document.getElementById('outreachKnowledgePanel');
    if (!mount) return;
    mount.innerHTML = `
        <section class="prospecting-knowledge-card">
            <div class="section-header">
                <div>
                    <h3 class="section-title">Единая база менеджера</h3>
                    <p class="section-subtitle">Адреса, шаблоны писем, стиль общения и подсказки бота для обработки холодной базы.</p>
                </div>
                <div class="crm-toolbar__group">
                    <button class="btn-secondary" onclick="askOutreachAssistant('Как менеджеру сегодня обработать назначенную базу развития?')">Спросить бота</button>
                    <button class="btn-secondary" onclick="askOutreachAssistant('Покажи шаблон первого письма клиенту из базы развития')">Шаблон письма</button>
                </div>
            </div>
            <div class="prospecting-knowledge-grid">
                ${OUTREACH_KNOWLEDGE_BLOCKS.map(block => `
                    <div class="prospecting-knowledge-block">
                        <strong>${outreachEscape(block.title)}</strong>
                        <p>${outreachEscape(block.text)}</p>
                        <div class="prospecting-mini-list">
                            ${block.items.map(item => `<span>${outreachEscape(item)}</span>`).join('')}
                        </div>
                    </div>
                `).join('')}
                <div class="prospecting-knowledge-block prospecting-knowledge-block--accent">
                    <strong>Умный бот по системе</strong>
                    <p>Отвечает по CRM: где база, что нажать, кому назначено, какие сроки и что показать директору.</p>
                    <div class="prospecting-mini-list">
                        <button type="button" onclick="askOutreachAssistant('Что мне сегодня контролировать в базе развития?')">контроль дня</button>
                        <button type="button" onclick="askOutreachAssistant('Кто не сдал отчёт сегодня по менеджерам?')">отчёты</button>
                        <button type="button" onclick="askOutreachAssistant('Как проверить качество импортированной базы?')">проверка базы</button>
                    </div>
                </div>
            </div>
        </section>
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
    const collapsed = !outreachReportExpanded;
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
                <p class="section-subtitle">План, факт, касания и фокус на завтра.</p>
            </div>
            <button class="btn-secondary" onclick="toggleOutreachReportPanel()">${collapsed ? 'Заполнить отчёт' : 'Свернуть'}</button>
        </div>
        <div class="prospecting-report-kpis">
            <div><span>План сегодня</span><strong>${Number(report.plan_total ?? metrics.dueToday ?? 0)}</strong></div>
            <div><span>Обработано</span><strong>${Number(report.processed_total ?? metrics.processedToday ?? 0)}</strong></div>
            <div><span>Звонков</span><strong>${Number(report.calls_total ?? metrics.callsTotal ?? 0)}</strong></div>
            <div><span>Лидов</span><strong>${Number(report.converted_total ?? metrics.convertedTotal ?? 0)}</strong></div>
        </div>
        <div class="prospecting-report-grid ${collapsed ? 'is-collapsed' : ''}">
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
        <div class="crm-editor-actions ${collapsed ? 'is-collapsed' : ''}">
            <button class="btn-primary" onclick="saveOutreachReport()">Сдать отчёт</button>
        </div>
        ${collapsed ? '' : `<div class="client360-list" style="margin-top:16px;">
            ${(outreachReportsDB || []).slice(0, 5).map(item => `
                <div class="client360-item">
                    <div>
                        <div class="client360-item-title">${outreachEscape(item.report_date)} · ${outreachEscape(item.manager_name || item.manager_email || 'Менеджер')}</div>
                        <div class="client360-item-meta">план ${Number(item.plan_total || 0)} · обработано ${Number(item.processed_total || 0)} · звонков ${Number(item.calls_total || 0)} · писем ${Number(item.emails_total || 0)}</div>
                    </div>
                    <span class="crm-inline-pill crm-inline-pill--${item.report_date === today ? 'attention' : 'neutral'}">${item.report_date === today ? 'Сегодня' : 'Отчёт'}</span>
                </div>
            `).join('') || '<div class="empty-state">Отчётов пока нет.</div>'}
        </div>`}
    `;
}

function toggleOutreachReportPanel() {
    outreachReportExpanded = !outreachReportExpanded;
    renderOutreachReportPanel();
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

function renderOutreachImportResult() {
    const mount = document.getElementById('outreachImportResult');
    if (!mount) return;
    const latest = outreachLastImportResult || (outreachImportsDB || [])[0] || null;
    if (!latest) {
        mount.innerHTML = '';
        return;
    }
    const rowsTotal = Number(latest.rows_total ?? latest.rows ?? 0);
    const created = Number(latest.created_total ?? latest.created ?? 0);
    const updated = Number(latest.updated_total ?? latest.updated ?? 0);
    const skipped = Number(latest.skipped_total ?? latest.skipped ?? 0);
    const protocol = buildOutreachImportProtocol(latest);
    mount.innerHTML = `
        <div class="prospecting-import-result__item"><span>Загружено</span><strong>${rowsTotal}</strong></div>
        <div class="prospecting-import-result__item"><span>Создано</span><strong>${created}</strong></div>
        <div class="prospecting-import-result__item"><span>Обновлено дублей</span><strong>${updated}</strong></div>
        <div class="prospecting-import-result__item"><span>Пропущено</span><strong>${skipped}</strong></div>
        <div class="prospecting-import-protocol">
            <div class="prospecting-side-title">Протокол проверки загрузки</div>
            ${protocol.map(item => `
                <div class="prospecting-protocol-row">
                    <span class="crm-inline-pill crm-inline-pill--${item.ok ? 'positive' : 'critical'}">${item.ok ? 'OK' : 'Проверить'}</span>
                    <strong>${outreachEscape(item.label)}</strong>
                    <small>${outreachEscape(item.value)}</small>
                </div>
            `).join('')}
        </div>
    `;
}

function renderOutreachImportPreview() {
    const mount = document.getElementById('outreachImportPreview');
    if (!mount) return;
    const preview = outreachImportPreview;
    if (!preview) {
        mount.innerHTML = '';
        return;
    }
    const recognized = Number(preview.recognized_columns || 0);
    const total = Number(preview.columns_total || 0);
    const problemRows = Number(preview.problem_rows ?? preview.skipped ?? 0);
    const tone = problemRows ? 'critical' : 'positive';
    const columnsLabel = total ? `${recognized} из ${total}` : '0';
    const protocol = buildOutreachImportProtocol(preview);
    mount.innerHTML = `
        <div class="prospecting-preview-head">
            <div>
                <div class="prospecting-preview-title">Предпросмотр импорта</div>
                <div class="prospecting-preview-subtitle">Колонки распознаны: ${outreachEscape(columnsLabel)} · файл: ${outreachEscape(preview.filename || '')}</div>
            </div>
            <span class="crm-inline-pill crm-inline-pill--${tone}">Проблемных строк: ${problemRows}</span>
        </div>
        <div class="prospecting-import-result">
            <div class="prospecting-import-result__item"><span>Строк в файле</span><strong>${Number(preview.rows_total || 0)}</strong></div>
            <div class="prospecting-import-result__item"><span>Создастся</span><strong>${Number(preview.created || 0)}</strong></div>
            <div class="prospecting-import-result__item"><span>Обновится</span><strong>${Number(preview.updated || 0)}</strong></div>
            <div class="prospecting-import-result__item"><span>Пропустится</span><strong>${Number(preview.skipped || 0)}</strong></div>
        </div>
        ${(preview.problems || []).length ? `<div class="prospecting-preview-problems">
            ${(preview.problems || []).slice(0, 6).map(item => `<span>Строка ${Number(item.row || 0)}: ${outreachEscape(item.reason || 'ошибка')}</span>`).join('')}
        </div>` : ''}
        <div class="prospecting-import-protocol">
            <div class="prospecting-side-title">Тест перед загрузкой</div>
            ${protocol.map(item => `
                <div class="prospecting-protocol-row">
                    <span class="crm-inline-pill crm-inline-pill--${item.ok ? 'positive' : 'critical'}">${item.ok ? 'OK' : 'Проверить'}</span>
                    <strong>${outreachEscape(item.label)}</strong>
                    <small>${outreachEscape(item.value)}</small>
                </div>
            `).join('')}
        </div>
    `;
}

function bitrixSelectionKey(item) {
    return `${String(item?.type || '')}:${String(item?.id || '')}`;
}

async function loadBitrixImportRows() {
    const data = await apiCall('/outreach/prospects');
    if (Array.isArray(data)) outreachBitrixRows = data;
    // The personal client screen uses its own scope; it must not overwrite these totals.
    renderBitrixImportStats();
    return outreachBitrixRows;
}

function renderBitrixImportStats() {
    const mount = document.getElementById('bitrixImportStats');
    if (!mount) return;
    const loaded = Array.isArray(outreachBitrixRows);
    const rows = (loaded ? outreachBitrixRows : []).filter(row => String(row.source_name || '') === 'Bitrix24 API');
    const withContacts = rows.filter(row => String(row.phone || row.email || row.contact_name || '').trim()).length;
    const emptyContacts = rows.length - withContacts;
    const lastImport = (Array.isArray(outreachImportsDB) ? outreachImportsDB : [])
        .filter(row => String(row.source_name || '') === 'Bitrix24 API')
        .sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0))[0];
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Доступно из Bitrix24</div><div class="crm-summary-value">${loaded ? rows.length : '—'}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">С контактами</div><div class="crm-summary-value">${loaded ? withContacts : '—'}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Без контактов</div><div class="crm-summary-value">${loaded ? emptyContacts : '—'}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Последний импорт</div><div class="crm-summary-value">${lastImport ? Number(lastImport.rows_total || 0) : 0}</div></div>
    `;
}

async function renderBitrixImport() {
    const view = document.getElementById('bitrixImportView');
    if (view) {
        view.style.display = 'block';
        view.classList.add('fade-in');
    }
    await Promise.all([loadBitrixImportRows(), loadOutreachImports(), loadBitrixConnectionStatus()]);
    renderBitrixImportStats();
    renderOutreachBitrixPanel();
}

async function refreshBitrixImportData() {
    await Promise.all([loadBitrixImportRows(), loadOutreachImports()]);
    renderBitrixImportStats();
    renderOutreachBitrixPanel();
}

function canManageBitrixConnection() {
    return typeof hasCurrentPermission === 'function' && hasCurrentPermission('clients', 'import');
}

function canUseBitrixImport() {
    return typeof hasCurrentPermission === 'function'
        && ['Директор', 'Менеджер'].includes(String(currentUser?.role || ''))
        && hasCurrentPermission('clients', 'read');
}

function renderBitrixConnectionStatus() {
    const mount = document.getElementById('bitrixConnectionStatus');
    const input = document.getElementById('bitrixWebhookInput');
    const testButton = document.getElementById('bitrixTestButton');
    const saveButton = document.getElementById('bitrixSaveButton');
    const form = input?.closest('.bitrix-connection-form');
    const hint = document.querySelector('#bitrixConnectionPanel .bitrix-connection-hint');
    if (!mount) return;
    const allowed = canManageBitrixConnection();
    const canUse = canUseBitrixImport();
    const configured = Boolean(outreachBitrixConnection?.configured);
    const settings = document.getElementById('bitrixConnectionSettings');
    if (settings) settings.hidden = !allowed;
    const portal = String(outreachBitrixConnection?.portal || '');
    if (form) {
        if (allowed) form.style.removeProperty('display');
        else form.style.setProperty('display', 'none', 'important');
    }
    if (hint) hint.textContent = allowed
        ? 'Адрес скрыт после сохранения. Для замены подключения вставьте новый вебхук.'
        : 'Подключение защищено. Менеджер может запускать выгрузку, но не может менять вебхук.';
    if (input) input.disabled = !allowed || outreachBitrixConnectionBusy;
    if (testButton) testButton.disabled = !allowed || outreachBitrixConnectionBusy;
    if (saveButton) saveButton.disabled = !allowed || outreachBitrixConnectionBusy;
    if (!canUse) {
        const poolStatus = document.getElementById('outreachBitrixStatus');
        if (poolStatus) poolStatus.hidden = true;
        mount.innerHTML = '<span class="crm-inline-pill crm-inline-pill--neutral">Нет доступа</span>';
        return;
    }
    let portalLink = '';
    try {
        const url = new URL(portal);
        if (url.protocol === 'https:') portalLink = `<a class="bitrix-portal-link" href="${outreachEscape(url.origin)}" target="_blank" rel="noopener noreferrer">${outreachEscape(url.hostname)} ↗</a>`;
    } catch (_) { /* A missing portal must not create a broken link. */ }
    let statusHtml;
    if (outreachBitrixStatusLoading) {
        statusHtml = '<span class="crm-inline-pill crm-inline-pill--neutral">Проверяем подключение…</span>' + portalLink;
    } else if (outreachBitrixConnection?.error) {
        statusHtml = '<span class="crm-inline-pill crm-inline-pill--warning">Статус не обновлён</span>' + portalLink
            + '<button class="btn-secondary bitrix-status-retry" type="button" onclick="loadBitrixConnectionStatus()">Повторить</button>';
    } else if (configured) {
        statusHtml = '<span class="crm-inline-pill crm-inline-pill--positive">Подключено</span>' + portalLink;
    } else if (!outreachBitrixConnection) {
        statusHtml = '<span class="crm-inline-pill crm-inline-pill--neutral">Проверяем подключение…</span>';
    } else {
        statusHtml = '<span class="crm-inline-pill crm-inline-pill--critical">Не подключено</span><small>Сохраните входящий вебхук</small>';
    }
    mount.innerHTML = statusHtml;
    const poolStatus = document.getElementById('outreachBitrixStatus');
    if (poolStatus) {
        poolStatus.hidden = !canUse;
        poolStatus.innerHTML = statusHtml;
    }
}

async function loadBitrixConnectionStatus() {
    if (outreachBitrixStatusRequest) return outreachBitrixStatusRequest;
    if (!canUseBitrixImport()) {
        outreachBitrixConnection = { configured: false, forbidden: true };
        renderBitrixConnectionStatus();
        return outreachBitrixConnection;
    }
    outreachBitrixStatusLoading = true;
    renderBitrixConnectionStatus();
    outreachBitrixStatusRequest = (async () => {
        let timeout;
        try {
            const res = await Promise.race([
                apiCall('/integrations/bitrix24/status'),
                new Promise(resolve => { timeout = window.setTimeout(() => resolve({ error: 'status_timeout' }), 12000); }),
            ]);
            if (!res || res.error || typeof res.configured !== 'boolean') {
                // Network failures do not mean the saved integration was disconnected.
                outreachBitrixConnection = { ...outreachBitrixConnection, error: res?.error || 'status_failed' };
            } else {
                outreachBitrixConnection = res;
            }
        } catch (_) {
            outreachBitrixConnection = { ...outreachBitrixConnection, error: 'status_failed' };
        } finally {
            window.clearTimeout(timeout);
            outreachBitrixStatusLoading = false;
            outreachBitrixStatusRequest = null;
            renderBitrixConnectionStatus();
            renderOutreachBitrixPanel();
        }
        return outreachBitrixConnection;
    })();
    return outreachBitrixStatusRequest;
}

function bitrixWebhookValue() {
    return String(document.getElementById('bitrixWebhookInput')?.value || '').trim();
}

async function testBitrixConnection() {
    const webhookUrl = bitrixWebhookValue();
    if (!webhookUrl && !outreachBitrixConnection?.configured) {
        return customAlert('Вставьте входящий вебхук Bitrix24.');
    }
    outreachBitrixConnectionBusy = true;
    renderBitrixConnectionStatus();
    const res = await apiCall('/integrations/bitrix24/test', 'POST', { webhook_url: webhookUrl });
    outreachBitrixConnectionBusy = false;
    renderBitrixConnectionStatus();
    if (!res || res.error || res.status === 'failed') return customAlert(res?.error || 'Не удалось подключиться к Bitrix24.');
    outreachBitrixConnection = res;
    renderBitrixConnectionStatus();
    renderOutreachBitrixPanel();
    showToast('Bitrix24', 'Подключение работает');
}

async function saveBitrixConnection() {
    const webhookUrl = bitrixWebhookValue();
    if (!webhookUrl) return customAlert('Вставьте входящий вебхук Bitrix24.');
    outreachBitrixConnectionBusy = true;
    renderBitrixConnectionStatus();
    const res = await apiCall('/integrations/bitrix24/configure', 'POST', { webhook_url: webhookUrl });
    outreachBitrixConnectionBusy = false;
    if (!res || res.error || res.status === 'failed') {
        renderBitrixConnectionStatus();
        return customAlert(res?.error || 'Не удалось сохранить подключение Bitrix24.');
    }
    outreachBitrixConnection = res;
    const input = document.getElementById('bitrixWebhookInput');
    if (input) input.value = '';
    renderBitrixConnectionStatus();
    renderOutreachBitrixPanel();
    showToast('Bitrix24', 'Подключение сохранено в CRM');
}

function renderOutreachBitrixPanel() {
    const mount = document.getElementById('outreachBitrixResults');
    if (!mount) return;
    const searchButton = document.getElementById('outreachBitrixSearchButton');
    const importButton = document.getElementById('outreachBitrixImportButton');
    const syncButton = document.getElementById('outreachBitrixSyncButton');
    const updateButton = document.getElementById('outreachBitrixUpdateButton');
    const clearButton = document.getElementById('outreachBitrixClearButton');
    const configured = Boolean(outreachBitrixConnection?.configured);
    const busy = outreachBitrixLoading || outreachBitrixImporting || Boolean(outreachBitrixAction);
    if (searchButton) searchButton.disabled = busy || !configured;
    if (importButton) {
        importButton.disabled = busy || !configured || !outreachBitrixSelected.size;
        importButton.textContent = outreachBitrixSelected.size ? `Загрузить выбранных (${outreachBitrixSelected.size})` : 'Загрузить выбранных';
    }
    if (syncButton) syncButton.disabled = busy || !configured;
    if (updateButton) updateButton.disabled = busy || !configured;
    if (clearButton) {
        clearButton.disabled = busy;
        clearButton.style.display = canManageBitrixConnection() ? '' : 'none';
    }
    if (outreachBitrixLoading) {
        mount.innerHTML = '<div class="empty-state">Ищу в Bitrix24...</div>';
        return;
    }
    if (outreachBitrixImporting) {
        mount.innerHTML = '<div class="empty-state">Загружаю выбранных клиентов...</div>';
        return;
    }
    if (outreachBitrixAction) {
        mount.innerHTML = `<div class="empty-state">${outreachEscape(outreachBitrixAction)}</div>`;
        return;
    }
    if (!configured) {
        const message = outreachBitrixStatusLoading || !outreachBitrixConnection
            ? 'Проверяем сохранённое подключение Bitrix24…'
            : outreachBitrixConnection.error
                ? 'Не удалось получить статус подключения. Нажмите «Повторить» выше.'
                : 'Сначала сохраните подключение Bitrix24 выше.';
        mount.innerHTML = `<div class="empty-state">${message}</div>`;
        return;
    }
    if (!Array.isArray(outreachBitrixResults) || !outreachBitrixResults.length) {
        mount.innerHTML = '<div class="empty-state">Введите название, телефон или email и нажмите «Найти в Bitrix24».</div>';
        return;
    }
    mount.innerHTML = `
        <div class="table-shell bitrix-search-table">
            <table class="admin-table admin-table--dense">
                <thead>
                    <tr>
                        <th style="width:42px;"></th>
                        <th>Тип</th>
                        <th>Клиент</th>
                        <th>Контакт</th>
                        <th>Телефон / email</th>
                        <th>Обновлен</th>
                    </tr>
                </thead>
                <tbody>
                    ${outreachBitrixResults.map(item => {
                        const key = bitrixSelectionKey(item);
                        return `
                            <tr>
                                <td><input type="checkbox" aria-label="Выбрать ${outreachEscape(item.title || 'клиента')}" ${outreachBitrixSelected.has(key) ? 'checked' : ''} onchange="toggleBitrixClientSelection('${outreachEscape(key)}', this.checked)"></td>
                                <td><span class="crm-inline-pill crm-inline-pill--neutral">${outreachEscape(({company: 'Компания', contact: 'Контакт', lead: 'Лид'})[item.type] || item.type || '')}</span></td>
                                <td class="crm-title-cell"><strong>${outreachEscape(item.title || 'Без названия')}</strong><div class="table-subtext">Bitrix ID ${outreachEscape(item.id || '')}</div></td>
                                <td>${outreachEscape(item.contact_name || '—')}</td>
                                <td class="crm-contact-cell">${outreachEscape(item.phone || '—')}<div class="table-subtext">${outreachEscape(item.email || '—')}</div></td>
                                <td>${outreachEscape(item.date_modify || '—')}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function searchBitrixClients() {
    const query = String(document.getElementById('outreachBitrixSearch')?.value || '').trim();
    if (!query) return customAlert('Введите название, контакт, телефон или email для поиска в Bitrix24.');
    if (query.length < 3) return customAlert('Введите минимум 3 символа, чтобы поиск в Bitrix24 не подвисал на слишком широком запросе.');
    outreachBitrixLoading = true;
    renderOutreachBitrixPanel();
    const res = await apiCall('/integrations/bitrix24/search', 'POST', { query, limit: 12 });
    outreachBitrixLoading = false;
    if (!res || res.error || res.status === 'failed') {
        renderOutreachBitrixPanel();
        return customAlert(res?.message || res?.error || 'Не удалось найти клиентов в Bitrix24.');
    }
    outreachBitrixResults = Array.isArray(res.items) ? res.items : [];
    outreachBitrixSelected = new Set(outreachBitrixResults.map(item => bitrixSelectionKey(item)));
    renderOutreachBitrixPanel();
    showToast('Bitrix24', `Найдено: ${outreachBitrixResults.length}`);
    renderBitrixImportStats();
}

function toggleBitrixClientSelection(key, checked) {
    if (!key) return;
    if (checked) outreachBitrixSelected.add(key);
    else outreachBitrixSelected.delete(key);
    const button = document.getElementById('outreachBitrixImportButton');
    if (button) {
        button.disabled = !outreachBitrixSelected.size || !outreachBitrixConnection?.configured || outreachBitrixLoading || outreachBitrixImporting || Boolean(outreachBitrixAction);
        button.textContent = outreachBitrixSelected.size ? `Загрузить выбранных (${outreachBitrixSelected.size})` : 'Загрузить выбранных';
    }
}

async function importSelectedBitrixClients() {
    const items = (outreachBitrixResults || []).filter(item => outreachBitrixSelected.has(bitrixSelectionKey(item)));
    if (!items.length) return customAlert('Выберите клиента из результатов Bitrix24.');
    outreachBitrixImporting = true;
    renderOutreachBitrixPanel();
    const res = await apiCall('/integrations/bitrix24/import_selected', 'POST', { items });
    outreachBitrixImporting = false;
    if (!res || res.error || res.status === 'failed') {
        renderOutreachBitrixPanel();
        return customAlert(res?.message || res?.error || 'Не удалось загрузить выбранных клиентов из Bitrix24.');
    }
    outreachLastImportResult = {
        filename: 'Bitrix24 selected',
        rows_total: Number(res.rows_total || 0),
        created: Number(res.created || 0),
        updated: Number(res.updated || 0),
        skipped: Number(res.skipped || 0),
    };
    showToast('Bitrix24', `Загружено: ${Number(res.rows_total || 0)}, создано ${Number(res.created || 0)}, обновлено ${Number(res.updated || 0)}`);
    await refreshBitrixImportData();
}

function getBitrixSyncLimit() {
    const value = Number(document.getElementById('outreachBitrixSyncLimit')?.value || 0);
    if (!value) return 0;
    return [25, 50, 100].includes(value) ? value : 25;
}

async function runBitrixSync(actionLabel) {
    const limit = getBitrixSyncLimit();
    outreachBitrixAction = limit ? `${actionLabel}: ${limit} последних клиентов из Bitrix24...` : `${actionLabel}: все клиенты из Bitrix24...`;
    renderOutreachBitrixPanel();
    const res = await apiCall('/integrations/bitrix24/sync', 'POST', { limit });
    outreachBitrixAction = '';
    if (!res || res.error || res.status === 'failed') {
        renderOutreachBitrixPanel();
        return customAlert(res?.message || res?.error || 'Не удалось синхронизировать Bitrix24.');
    }
    outreachLastImportResult = {
        filename: limit ? `Bitrix24 ${limit}` : 'Bitrix24 all',
        rows_total: Number(res.rows_total || 0),
        created: Number(res.created || 0),
        updated: Number(res.updated || 0),
        skipped: Number(res.skipped || 0),
    };
    showToast('Bitrix24', `Получено: ${Number(res.rows_total || 0)}, новых ${Number(res.created || 0)}, обновлено ${Number(res.updated || 0)}`);
    await refreshBitrixImportData();
}

async function syncBitrixClientsNow() {
    await runBitrixSync('Выгружаю');
}

async function updateBitrixClientsNow() {
    await runBitrixSync('Обновляю');
}

async function syncRecentBitrixClients() {
    await runBitrixSync('Обновляю');
}

async function clearBitrixClientList() {
    if (!await customConfirm('Очистить список клиентов, загруженных из Bitrix24? Настройка Bitrix24 останется.')) return;
    outreachBitrixAction = 'Очищаю список клиентов из Bitrix24...';
    renderOutreachBitrixPanel();
    const res = await apiCall('/integrations/bitrix24/outreach', 'DELETE');
    outreachBitrixAction = '';
    if (!res || res.error || res.status === 'failed') {
        renderOutreachBitrixPanel();
        return customAlert(res?.message || res?.error || 'Не удалось очистить список Bitrix24.');
    }
    outreachBitrixResults = [];
    outreachBitrixSelected = new Set();
    outreachLastImportResult = {
        filename: 'Bitrix24 cleared',
        rows_total: Number(res.removed || 0),
        created: 0,
        updated: 0,
        skipped: 0,
    };
    showToast('Bitrix24', `Очищено записей: ${Number(res.removed || 0)}`);
    await refreshBitrixImportData();
}

function syncOutreachFilterControls() {
    const statusSelect = document.getElementById('outreachStatusFilter');
    const prioritySelect = document.getElementById('outreachPriorityFilter');
    const processedSelect = document.getElementById('outreachProcessedFilter');
    const problemsButton = document.getElementById('outreachProblemsBtn');
    const advancedCount = document.getElementById('outreachAdvancedCount');
    document.querySelectorAll('[data-outreach-quick-filter]').forEach(button => {
        const active = String(button.dataset.outreachQuickFilter || '') === outreachQuickFilter;
        button.classList.toggle('btn-primary', active);
        button.classList.toggle('btn-secondary', !active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    if (statusSelect) statusSelect.value = outreachStatusFilter || '';
    if (prioritySelect) prioritySelect.value = outreachPriorityFilter || '';
    if (processedSelect) processedSelect.value = outreachProcessedFilter || '';
    if (problemsButton) problemsButton.setAttribute('aria-pressed', outreachOnlyProblems ? 'true' : 'false');
    if (advancedCount) {
        const count = Number(Boolean(outreachPriorityFilter)) + Number(Boolean(outreachProcessedFilter)) + Number(outreachOnlyProblems);
        advancedCount.textContent = String(count);
        advancedCount.classList.toggle('is-active', count > 0);
    }
}

function outreachContactMethodLabel(value) {
    return {
        phone: 'Телефон',
        email: 'Почта',
        message: 'Сообщение',
        mixed: 'Любой способ',
    }[String(value || '')] || 'Не указан';
}

function outreachActivityTypeLabel(value) {
    return {
        call: 'Звонок',
        email: 'Письмо',
        message: 'Сообщение',
        meeting: 'Встреча',
        note: 'Заметка',
    }[String(value || '')] || 'Контакт';
}

function outreachJourneyRecords(row) {
    const leadId = Number(row?.converted_lead_id || 0);
    const lead = (typeof crmLeadsDB !== 'undefined' ? crmLeadsDB : []).find(item => Number(item.id || 0) === leadId) || null;
    const dealId = Number(lead?.linked_deal_id || 0);
    const deal = (typeof crmDealsDB !== 'undefined' ? crmDealsDB : []).find(item => Number(item.id || 0) === dealId || Number(item.lead_id || 0) === leadId) || null;
    return { lead, deal };
}

function outreachJourneyState(row, lead, deal) {
    if (String(row?.status || '') === 'do_not_contact' || String(lead?.stage || '') === 'lost' || String(deal?.stage || '') === 'lost') return 'result';
    if (String(deal?.stage || '') === 'won') return 'result';
    if (deal) return 'deal';
    if (lead) return 'lead';
    return 'contact';
}

function outreachJourneyHeader(row, lead = null, deal = null) {
    const current = outreachJourneyState(row, lead, deal);
    const order = ['contact', 'lead', 'deal', 'result'];
    const activeIndex = order.indexOf(current);
    const labels = {
        contact: ['1', 'Первый контакт'],
        lead: ['2', 'Квалификация'],
        deal: ['3', 'Сделка'],
        result: ['4', 'Результат'],
    };
    return `<nav class="client-journey" aria-label="Путь клиента">
        ${order.map((key, index) => `<div class="client-journey__step ${index < activeIndex ? 'is-complete' : ''} ${index === activeIndex ? 'is-active' : ''}"><i>${labels[key][0]}</i><span>${labels[key][1]}</span></div>`).join('')}
    </nav>`;
}

function outreachLeadPayload(row, overrides = {}) {
    return {
        title: row.title || '', client_name: row.client_name || '', contact_name: row.contact_name || '',
        contact_email: row.contact_email || '', contact_phone: row.contact_phone || '', source: row.source || '',
        stage: row.stage || 'qualified', responsible: row.responsible || '', next_action: row.next_action || '',
        next_action_date: row.next_action_date || '', budget: Number(row.budget || 0), probability: Number(row.probability || 0),
        tags: Array.isArray(row.tags) ? row.tags : [], comment: row.comment || '', currency: row.currency || 'RUB',
        priority: row.priority || 'normal', linked_client_id: Number(row.linked_client_id || 0),
        linked_project_id: Number(row.linked_project_id || 0), linked_deal_id: Number(row.linked_deal_id || 0),
        ...overrides,
    };
}

function outreachDealPayload(row, overrides = {}) {
    return {
        lead_id: Number(row.lead_id || 0), title: row.title || row.client_name || '', client_id: Number(row.client_id || 0),
        client_name: row.client_name || '', contact_name: row.contact_name || '', contact_position: row.contact_position || '',
        contact_phone: row.contact_phone || '', contact_email: row.contact_email || '', source: row.source || '',
        contract_number: row.contract_number || '', stage: row.stage || 'qualification', amount: Number(row.amount || 0),
        currency: row.currency || 'RUB', margin_percent: Number(row.margin_percent || 0), probability: Number(row.probability || 0),
        responsible: row.responsible || '', next_action: row.next_action || '', next_action_date: row.next_action_date || '',
        expected_close_date: row.expected_close_date || '', priority: row.priority || 'normal', status_color: row.status_color || '',
        tags: Array.isArray(row.tags) ? row.tags : [], comment: row.comment || '', project_id: Number(row.project_id || 0),
        products: typeof crmDealProducts === 'function' ? crmDealProducts(row) : (Array.isArray(row.products) ? row.products : []),
        co_executors: row.co_executors || '', actual_close_date: row.actual_close_date || '', loss_reason: row.loss_reason || '',
        ...overrides,
    };
}

function outreachMoney(value, currency = 'RUB') {
    return typeof crmFormatMoney === 'function'
        ? crmFormatMoney(value, currency)
        : `${Number(value || 0).toLocaleString('ru-RU')} ₽`;
}

function outreachActivityHistory(activities = []) {
    if (!activities.length) return '<div class="empty-state">История пока пуста.</div>';
    return activities.map(item => `<div class="client360-item"><div><div class="client360-item-title">${outreachEscape(item.subject || outreachActivityTypeLabel(item.activity_type))}</div><div class="client360-item-meta">${outreachEscape(item.owner_name || item.manager_name || '')} · ${outreachEscape(item.due_date || item.next_action_date || 'без даты')}</div><div class="client360-item-meta">${outreachEscape(item.summary || 'без комментария')}</div></div></div>`).join('');
}

function renderOutreachLeadJourney(row, lead, activities) {
    const isLost = String(lead.stage || '') === 'lost';
    const need = typeof crmLeadVisibleComment === 'function' ? crmLeadVisibleComment(lead.comment) : String(lead.comment || '');
    return `<article class="unified-client-card">
        ${outreachJourneyHeader(row, lead)}
        <header class="unified-client-card__head"><div><span class="view-eyebrow">Квалификация клиента</span><h2>${outreachEscape(row.company_name || lead.client_name || 'Без компании')}</h2><p>${outreachEscape(row.contact_name || lead.contact_name || 'Контакт не указан')} · ${outreachEscape(row.phone || lead.contact_phone || 'телефон не указан')}</p></div><span class="crm-inline-pill ${isLost ? 'crm-inline-pill--neutral' : 'crm-inline-pill--attention'}">${isLost ? 'Закрыт без сделки' : 'Нужно принять решение'}</span></header>
        ${isLost ? `<section class="unified-client-outcome"><h3>Работа завершена без сделки</h3><p>${outreachEscape(need || 'Причина сохранена в истории клиента.')}</p></section>` : `
        <section class="unified-next-action"><div><span>Что сделать сейчас</span><strong>${outreachEscape(lead.next_action || 'Уточнить потребность клиента')}</strong><small>${outreachEscape(lead.next_action_date ? `Выполнить до ${lead.next_action_date}` : 'Назначьте срок следующего действия')}</small></div><button class="btn-primary" type="button" onclick="toggleUnifiedPanel('unifiedLeadContactPanel', true)">Зафиксировать контакт</button></section>
        <section class="unified-work-section"><div class="unified-work-section__head"><div><h3>Квалификация</h3><p>Заполните четыре рабочих поля. Остальные данные уже перенесены из первого контакта.</p></div></div>
            <div class="unified-form-grid">
                <label class="unified-field unified-field--wide"><span>Потребность и договорённости *</span><textarea id="unifiedLeadNeed" class="auth-input" rows="3" placeholder="Что нужно клиенту, объём и важные условия">${outreachEscape(need)}</textarea></label>
                <label class="unified-field"><span>Ожидаемая сумма</span><input id="unifiedLeadBudget" class="auth-input" type="number" min="0" value="${Number(lead.budget || 0)}"></label>
                <label class="unified-field"><span>Состояние</span><select id="unifiedLeadStage" class="auth-input"><option value="qualified" ${lead.stage === 'qualified' ? 'selected' : ''}>Потребность подтверждена</option><option value="proposal" ${lead.stage === 'proposal' ? 'selected' : ''}>Готовится предложение</option></select></label>
                <label class="unified-field"><span>Следующий шаг *</span><input id="unifiedLeadNextAction" class="auth-input" value="${outreachEscape(lead.next_action || '')}" placeholder="Например: подготовить расчёт"></label>
                <label class="unified-field"><span>Выполнить до *</span><input id="unifiedLeadNextDate" class="auth-input date-picker" value="${outreachEscape(lead.next_action_date || '')}" placeholder="дд.мм.гггг"></label>
            </div>
            <div class="unified-actions"><button class="btn-secondary" type="button" onclick="saveUnifiedLead(${Number(lead.id)})">Сохранить изменения</button><button class="btn-primary" type="button" onclick="convertUnifiedLeadToDeal(${Number(lead.id)})">Создать сделку</button><button class="btn-danger" type="button" onclick="toggleUnifiedPanel('unifiedLeadLossPanel', true)">Закрыть без сделки</button></div>
        </section>
        <section id="unifiedLeadContactPanel" class="unified-inline-panel" hidden><div class="unified-inline-panel__head"><div><h3>Результат контакта</h3><p>Запись попадёт в общую историю и обновит следующий шаг.</p></div><button class="btn-ghost" type="button" onclick="toggleUnifiedPanel('unifiedLeadContactPanel', false)">Закрыть</button></div><div class="unified-form-grid"><label class="unified-field"><span>Как связались</span><select id="unifiedLeadActivityType" class="auth-input"><option value="call">Звонок</option><option value="email">Письмо</option><option value="meeting">Встреча</option><option value="note">Заметка</option></select></label><label class="unified-field"><span>Следующий шаг *</span><input id="unifiedLeadActivityNext" class="auth-input" value="${outreachEscape(lead.next_action || '')}"></label><label class="unified-field"><span>Выполнить до *</span><input id="unifiedLeadActivityDate" class="auth-input date-picker" value="${outreachEscape(lead.next_action_date || '')}" placeholder="дд.мм.гггг"></label><label class="unified-field unified-field--wide"><span>Итог контакта *</span><textarea id="unifiedLeadActivitySummary" class="auth-input" rows="3"></textarea></label></div><button class="btn-primary" type="button" onclick="saveUnifiedLeadContact(${Number(lead.id)})">Сохранить контакт</button></section>
        <section id="unifiedLeadLossPanel" class="unified-inline-panel unified-inline-panel--danger" hidden><h3>Почему работа прекращается?</h3><textarea id="unifiedLeadLossReason" class="auth-input" rows="3" placeholder="Причина обязательна"></textarea><div class="unified-actions"><button class="btn-secondary" type="button" onclick="toggleUnifiedPanel('unifiedLeadLossPanel', false)">Отмена</button><button class="btn-danger" type="button" onclick="closeUnifiedLead(${Number(lead.id)})">Подтвердить закрытие</button></div></section>`}
        <details class="my-client-details"><summary>Данные клиента и история <span>${activities.length + (lead.activities || []).length}</span></summary><div class="my-client-data-grid"><div><span>Компания</span><strong>${outreachEscape(row.company_name || lead.client_name || '—')}</strong></div><div><span>Контакт</span><strong>${outreachEscape(row.contact_name || lead.contact_name || '—')}</strong></div><div><span>Телефон</span><strong>${outreachEscape(row.phone || lead.contact_phone || '—')}</strong></div><div><span>Почта</span><strong>${outreachEscape(row.email || lead.contact_email || '—')}</strong></div></div><div class="client360-list">${outreachActivityHistory([...(lead.activities || []), ...activities])}</div></details>
    </article>`;
}

function renderOutreachDealJourney(row, lead, deal, activities) {
    const isClosed = ['won', 'lost'].includes(String(deal.stage || ''));
    const won = String(deal.stage || '') === 'won';
    const products = typeof crmDealProducts === 'function' ? crmDealProducts(deal) : [];
    const documents = Array.isArray(deal.documents) ? deal.documents : [];
    return `<article class="unified-client-card">
        ${outreachJourneyHeader(row, lead, deal)}
        <header class="unified-client-card__head"><div><span class="view-eyebrow">${isClosed ? 'Результат работы' : 'Сделка в работе'}</span><h2>${outreachEscape(deal.client_name || row.company_name || 'Без компании')}</h2><p>${outreachEscape(deal.contact_name || row.contact_name || 'Контакт не указан')} · ${outreachMoney(deal.amount, deal.currency)}</p></div><span class="crm-inline-pill crm-inline-pill--${won ? 'positive' : isClosed ? 'neutral' : 'attention'}">${outreachEscape(typeof crmDealStageInfo === 'function' ? crmDealStageInfo(deal.stage).label : deal.stage)}</span></header>
        ${isClosed ? `<section class="unified-client-outcome ${won ? 'is-won' : ''}"><h3>${won ? 'Продажа состоялась' : 'Клиент отказался'}</h3><p>${outreachEscape(deal.loss_reason || 'Итог сохранён.')}</p><small>Дата завершения: ${outreachEscape(deal.actual_close_date || 'не указана')}</small></section>` : `
        <section class="unified-next-action"><div><span>Что сделать сейчас</span><strong>${outreachEscape(deal.next_action || 'Назначить следующий шаг')}</strong><small>${outreachEscape(deal.next_action_date ? `Выполнить до ${deal.next_action_date}` : 'Срок не назначен')}</small></div><button class="btn-primary" type="button" onclick="toggleUnifiedPanel('unifiedDealContactPanel', true)">Зафиксировать контакт</button></section>
        <section class="unified-work-section"><div class="unified-work-section__head"><div><h3>Управление сделкой</h3><p>Этап, ближайшее действие и деньги обновляются без большой формы.</p></div></div><div class="unified-form-grid">
            <label class="unified-field"><span>Этап сделки</span><select id="unifiedDealStage" class="auth-input"><option value="qualification" ${deal.stage === 'qualification' ? 'selected' : ''}>Уточняем заказ</option><option value="proposal" ${deal.stage === 'proposal' ? 'selected' : ''}>Расчёт, КП и документы</option><option value="negotiation" ${deal.stage === 'negotiation' ? 'selected' : ''}>Согласовываем условия</option></select></label>
            <label class="unified-field"><span>Сумма</span><input id="unifiedDealAmount" class="auth-input" type="number" min="0" value="${Number(deal.amount || 0)}"></label>
            <label class="unified-field unified-field--wide"><span>Следующий шаг *</span><input id="unifiedDealNextAction" class="auth-input" value="${outreachEscape(deal.next_action || '')}" placeholder="Например: согласовать договор"></label>
            <label class="unified-field"><span>Выполнить до</span><input id="unifiedDealNextDate" class="auth-input date-picker" value="${outreachEscape(deal.next_action_date || '')}" placeholder="дд.мм.гггг"></label>
            <label class="unified-field"><span>План завершения</span><input id="unifiedDealCloseDate" class="auth-input date-picker" value="${outreachEscape(deal.expected_close_date || '')}" placeholder="дд.мм.гггг"></label>
        </div><div class="unified-actions"><button class="btn-primary" type="button" onclick="saveUnifiedDeal(${Number(deal.id)})">Сохранить и продолжить</button><button class="btn-secondary" type="button" onclick="toggleUnifiedPanel('unifiedDealDetailsPanel', true)">Данные сделки</button><button class="btn-success" type="button" onclick="openUnifiedDealOutcome('won')">Продажа состоялась</button><button class="btn-danger" type="button" onclick="openUnifiedDealOutcome('lost')">Клиент отказался</button></div></section>
        <section id="unifiedDealContactPanel" class="unified-inline-panel" hidden><div class="unified-inline-panel__head"><div><h3>Результат контакта</h3><p>Зафиксируйте договорённость и новый следующий шаг.</p></div><button class="btn-ghost" type="button" onclick="toggleUnifiedPanel('unifiedDealContactPanel', false)">Закрыть</button></div><div class="unified-form-grid"><label class="unified-field"><span>Как связались</span><select id="unifiedDealActivityType" class="auth-input"><option value="call">Звонок</option><option value="email">Письмо</option><option value="meeting">Встреча</option><option value="note">Заметка</option></select></label><label class="unified-field"><span>Следующий шаг *</span><input id="unifiedDealActivityNext" class="auth-input" value="${outreachEscape(deal.next_action || '')}"></label><label class="unified-field"><span>Выполнить до</span><input id="unifiedDealActivityDate" class="auth-input date-picker" value="${outreachEscape(deal.next_action_date || '')}" placeholder="дд.мм.гггг"></label><label class="unified-field unified-field--wide"><span>Итог контакта *</span><textarea id="unifiedDealActivitySummary" class="auth-input" rows="3"></textarea></label></div><button class="btn-primary" type="button" onclick="saveUnifiedDealContact(${Number(deal.id)})">Сохранить контакт</button></section>
        <section id="unifiedDealDetailsPanel" class="unified-inline-panel" hidden><div class="unified-inline-panel__head"><div><h3>Данные сделки</h3><p>Реквизиты, которые меняются реже рабочего статуса.</p></div><button class="btn-ghost" type="button" onclick="toggleUnifiedPanel('unifiedDealDetailsPanel', false)">Закрыть</button></div><div class="unified-form-grid"><label class="unified-field"><span>Контактное лицо</span><input id="unifiedDealContactName" class="auth-input" value="${outreachEscape(deal.contact_name || '')}"></label><label class="unified-field"><span>Телефон</span><input id="unifiedDealContactPhone" class="auth-input" value="${outreachEscape(deal.contact_phone || '')}"></label><label class="unified-field"><span>Почта</span><input id="unifiedDealContactEmail" class="auth-input" value="${outreachEscape(deal.contact_email || '')}"></label><label class="unified-field"><span>№ КП / договора</span><input id="unifiedDealContract" class="auth-input" value="${outreachEscape(deal.contract_number || '')}"></label><label class="unified-field unified-field--wide"><span>Товары и услуги</span><textarea id="unifiedDealProducts" class="auth-input" rows="4" placeholder="Название | количество | цена">${outreachEscape(products.map(item => `${item.name || ''} | ${Number(item.quantity || 1)} | ${Number(item.unit_price || 0)}`).join('\n'))}</textarea></label><label class="unified-field unified-field--wide"><span>Комментарий</span><textarea id="unifiedDealComment" class="auth-input" rows="3">${outreachEscape(deal.comment || '')}</textarea></label></div><button class="btn-primary" type="button" onclick="saveUnifiedDealDetails(${Number(deal.id)})">Сохранить данные сделки</button></section>
        <section id="unifiedDealOutcomePanel" class="unified-inline-panel unified-inline-panel--danger" hidden><h3 id="unifiedDealOutcomeTitle">Завершение сделки</h3><input id="unifiedDealOutcomeType" type="hidden"><textarea id="unifiedDealOutcomeReason" class="auth-input" rows="3" placeholder="Укажите причину результата"></textarea><div class="unified-actions"><button class="btn-secondary" type="button" onclick="toggleUnifiedPanel('unifiedDealOutcomePanel', false)">Отмена</button><button class="btn-primary" type="button" onclick="closeUnifiedDeal(${Number(deal.id)})">Сохранить результат</button></div></section>`}
        <details class="my-client-details"><summary>История и документы <span>${(lead.activities || []).length + (deal.activities || []).length + documents.length}</span></summary><div class="client360-list">${outreachActivityHistory([...(deal.activities || []), ...(lead.activities || []), ...activities])}${documents.map(doc => `<div class="client360-item"><div><div class="client360-item-title">Документ ${outreachEscape(doc.number || `#${doc.id}`)}</div><div class="client360-item-meta">${outreachEscape(doc.subject || 'Без названия')}</div></div>${doc.file_url ? `<a class="btn-secondary" href="${outreachEscape(doc.file_url)}" target="_blank" rel="noopener">Открыть</a>` : ''}</div>`).join('')}</div></details>
    </article>`;
}

function renderOutreachSavedClientCard(row, activities) {
    const { lead, deal } = outreachJourneyRecords(row);
    if (deal) return renderOutreachDealJourney(row, lead, deal, activities);
    if (lead) return renderOutreachLeadJourney(row, lead, activities);
    const isConverted = String(row.status || '') === 'converted';
    const isRejected = String(row.status || '') === 'do_not_contact';
    const lastActivity = activities[0] || null;
    const tags = Array.isArray(row.tags) ? row.tags : [];
    return `
        <article id="myClientCardStep" class="my-client-result-card ${isConverted ? 'is-complete' : ''}">
            ${outreachJourneyHeader(row)}
            <div class="my-client-result-card__head">
                <div>
                    <span class="my-client-card__step-label">Карточка клиента</span>
                    <h2>${outreachEscape(row.company_name || 'Без компании')}</h2>
                    <p>Все сохранённые данные и результаты работы с клиентом.</p>
                </div>
                <span class="crm-inline-pill crm-inline-pill--${outreachTone(row.status, row.is_overdue)}">${outreachEscape(outreachStatusLabel(row.status))}</span>
            </div>

            <section class="my-client-data-section">
                <h3>Компания и контактное лицо</h3>
                <div class="my-client-data-grid">
                    <div><span>Компания</span><strong>${outreachEscape(row.company_name || 'Не указана')}</strong></div>
                    <div><span>ИНН</span><strong>${outreachEscape(row.company_inn || 'Не указан')}</strong></div>
                    <div><span>Контактное лицо</span><strong>${outreachEscape(row.contact_name || 'Не указано')}</strong></div>
                    <div><span>Должность</span><strong>${outreachEscape(row.position || 'Не указана')}</strong></div>
                    <div><span>Телефон</span><strong>${outreachEscape(row.phone || 'Не указан')}</strong></div>
                    <div><span>Почта</span><strong>${outreachEscape(row.email || 'Не указана')}</strong></div>
                    <div><span>Сайт</span><strong>${outreachEscape(row.website || 'Не указан')}</strong></div>
                    <div><span>Город</span><strong>${outreachEscape(row.city || 'Не указан')}</strong></div>
                </div>
            </section>

            <section class="my-client-data-section">
                <h3>Работа с клиентом</h3>
                <div class="my-client-data-grid">
                    <div><span>Предпочтительный способ связи</span><strong>${outreachEscape(outreachContactMethodLabel(row.contact_method))}</strong></div>
                    <div><span>Источник</span><strong>${outreachEscape(row.source_name || 'Не указан')}</strong></div>
                    <div><span>Ответственный</span><strong>${outreachEscape(row.manager_name || row.manager_email || 'Не назначен')}</strong></div>
                    <div><span>Первичный контакт до</span><strong>${outreachEscape(row.planned_contact_date || 'Не назначен')}</strong></div>
                    <div><span>Приоритет</span><strong>${outreachEscape(outreachPriorityLabel(row.priority))}</strong></div>
                    <div><span>Статус</span><strong>${outreachEscape(outreachStatusLabel(row.status))}</strong></div>
                    <div><span>Следующее действие</span><strong>${outreachEscape(row.next_action || 'Не назначено')}</strong></div>
                    <div><span>До какого числа</span><strong>${outreachEscape(row.next_action_date || 'Не назначено')}</strong></div>
                </div>
                <div class="my-client-result-card__note"><span>Что узнали о клиенте</span><p>${outreachEscape(row.notes || 'Дополнительная информация не заполнена.')}</p></div>
                ${tags.length ? `<div class="crm-tags">${tags.map(tag => `<span class="crm-tag">${outreachEscape(tag)}</span>`).join('')}</div>` : ''}
            </section>

            <section class="my-client-data-section">
                <div class="my-client-data-section__head">
                    <h3>Последний контакт</h3>
                    <span>${activities.length} ${activities.length === 1 ? 'запись' : 'записей'}</span>
                </div>
                <div class="my-client-contact-result">
                    <div><span>Как связались</span><strong>${outreachEscape(lastActivity ? outreachActivityTypeLabel(lastActivity.activity_type) : 'Не указано')}</strong></div>
                    <div><span>Результат</span><strong>${outreachEscape(lastActivity ? outreachStatusLabel(lastActivity.result_status) : 'Не указан')}</strong></div>
                    <div><span>Следующий шаг</span><strong>${outreachEscape(lastActivity?.next_action || row.next_action || 'Не назначен')}</strong></div>
                    <div><span>Дата следующего контакта</span><strong>${outreachEscape(lastActivity?.next_action_date || row.next_action_date || 'Не назначена')}</strong></div>
                </div>
                <div class="my-client-result-card__note"><span>Комментарий по итогам</span><p>${outreachEscape(lastActivity?.summary || 'Комментарий не заполнен.')}</p></div>
            </section>

            <details class="my-client-details my-client-history">
                <summary>Вся история контактов <span>${activities.length}</span></summary>
                <div class="client360-list">
                    ${activities.map(activity => `
                        <div class="client360-item">
                            <div>
                                <div class="client360-item-title">${outreachEscape(outreachActivityTypeLabel(activity.activity_type))} · ${outreachEscape(outreachStatusLabel(activity.result_status || ''))}</div>
                                <div class="client360-item-meta">${outreachEscape(activity.manager_name || '')} · ${outreachEscape(activity.next_action_date || 'без следующей даты')}</div>
                                <div class="client360-item-meta">${outreachEscape(activity.summary || 'без комментария')}</div>
                            </div>
                        </div>
                    `).join('') || '<div class="empty-state">Истории обработки пока нет.</div>'}
                </div>
            </details>

            ${!isConverted && !isRejected ? `<section id="outreachFollowupPanel" class="unified-inline-panel" hidden>
                <div class="unified-inline-panel__head"><div><h3>Новый контакт</h3><p>Зафиксируйте результат и сразу назначьте следующий шаг.</p></div><button class="btn-ghost" type="button" onclick="toggleUnifiedPanel('outreachFollowupPanel', false)">Закрыть</button></div>
                <div class="unified-form-grid">
                    <label class="unified-field"><span>Как связались</span><select id="outreachActivityType" class="auth-input"><option value="call">Звонок</option><option value="email">Письмо</option><option value="message">Сообщение</option><option value="meeting">Встреча</option></select></label>
                    <label class="unified-field"><span>Результат *</span><select id="outreachActivityResult" class="auth-input" onchange="applyOutreachActivityResult(this.value)"><option value="">Выберите результат</option><option value="no_answer">Нет ответа</option><option value="follow_up">Перезвонить позже</option><option value="warm">Есть интерес</option><option value="meeting">Назначена встреча</option><option value="do_not_contact">Не интересно / больше не звонить</option></select></label>
                    <label class="unified-field"><span>Что сделать дальше</span><input id="outreachActivityNextAction" class="auth-input" value="${outreachEscape(row.next_action || '')}"></label>
                    <label class="unified-field"><span>До какого числа</span><input id="outreachActivityNextDate" class="auth-input date-picker" value="${outreachEscape(row.next_action_date || '')}" placeholder="дд.мм.гггг"></label>
                    <label class="unified-field unified-field--wide"><span>Итог контакта *</span><textarea id="outreachActivitySummary" class="auth-input" rows="3"></textarea></label>
                </div><button class="btn-primary" type="button" onclick="saveOutreachActivity(${Number(row.id || 0)})">Сохранить контакт</button>
            </section>` : ''}

            <div id="outreachRejectPanel" class="my-client-reject-panel" hidden>
                <div>
                    <h3>Укажите причину отказа</h3>
                    <p>Причина сохранится в истории клиента. Без неё отказаться от клиента нельзя.</p>
                </div>
                <textarea id="outreachRejectReason" class="auth-input" rows="3" placeholder="Например: клиент отказался от предложения из-за бюджета"></textarea>
                <div class="my-client-reject-panel__actions">
                    <button class="btn-secondary" type="button" onclick="toggleOutreachRejectForm(false)">Отмена</button>
                    <button class="btn-danger" type="button" onclick="rejectOutreachClient(${Number(row.id || 0)})">Подтвердить отказ</button>
                </div>
            </div>

            <div class="my-client-result-card__actions">
                <button class="btn-secondary" type="button" onclick="editOutreachClient(${Number(row.id || 0)})">Изменить</button>
                ${!isConverted && !isRejected ? '<button class="btn-secondary" type="button" onclick="toggleUnifiedPanel(\'outreachFollowupPanel\', true)">Зафиксировать контакт</button>' : ''}
                ${isConverted
                    ? '<button class="btn-primary" type="button" onclick="renderProspecting(true)">Продолжить работу</button>'
                    : (!isRejected ? `<button class="btn-primary" type="button" onclick="convertOutreachProspect(${Number(row.id || 0)})">Перевести в лид</button>` : '')}
                ${!isConverted && !isRejected ? '<button class="btn-danger" type="button" onclick="toggleOutreachRejectForm(true)">Отказ клиента</button>' : ''}
            </div>
        </article>
    `;
}

function renderOutreachDetail(row) {
    if (!row) {
        const hasClients = filteredOutreachRows().length > 0;
        return `
        <div class="my-clients-empty">
            <span class="my-clients-empty__number">1</span>
            <h3>${hasClients ? 'Выберите клиента в таблице' : 'Сначала заберите клиента'}</h3>
            <p>${hasClients ? 'Нажмите «Открыть клиента»: появится номер для звонка и три шага работы.' : 'Свободные клиенты находятся в «Базе развития». После выбора клиент появится здесь и исчезнет у других менеджеров.'}</p>
            ${hasClients ? '' : '<button class="btn-primary" type="button" onclick="navigateTo(\'prospecting\')">Перейти в базу развития</button>'}
        </div>
        `;
    }
    const activities = Array.isArray(row.activities) ? row.activities : [];
    const journey = outreachJourneyRecords(row);
    const isConverted = String(row.status || '') === 'converted';
    const cleanPhone = String(row.phone || '').replace(/[^\d+]/g, '');
    const managerName = row.manager_name || row.manager_email || currentUser?.name || 'Не назначен';
    if (!outreachClientEditMode && (journey.lead || journey.deal || activities.length > 0)) {
        return renderOutreachSavedClientCard(row, activities);
    }
    return `
        <div class="my-client-workspace">
            ${outreachJourneyHeader(row)}
            <section id="myClientProfileStep" class="my-client-work-step my-client-profile-step">
                <div class="my-client-work-step__head my-client-work-step__head--spread">
                    <div class="my-client-work-step__title">
                        <span class="my-client-work-step__number">1</span>
                        <div>
                            <h3>Позвоните клиенту и уточните данные</h3>
                            <p>Если дозвонились, заполните известные данные компании и контактного лица.</p>
                        </div>
                    </div>
                    ${row.phone
                        ? `<a class="my-client-phone" href="tel:${outreachEscape(cleanPhone)}"><span>Позвонить</span><strong>${outreachEscape(row.phone)}</strong></a>`
                        : '<div class="my-client-phone my-client-phone--empty"><span>Телефон</span><strong>Номер не указан</strong></div>'}
                </div>
                <div class="my-client-profile-grid">
                    <label class="my-client-field"><span>Компания *</span><input id="outreachFormCompany" class="auth-input" type="text" value="${outreachEscape(row.company_name || '')}" placeholder="Название компании"></label>
                    <label class="my-client-field"><span>ИНН</span><input id="outreachFormInn" class="auth-input" type="text" value="${outreachEscape(row.company_inn || '')}" placeholder="ИНН компании"></label>
                    <label class="my-client-field"><span>Контактное лицо</span><input id="outreachFormContact" class="auth-input" type="text" value="${outreachEscape(row.contact_name || '')}" placeholder="ФИО"></label>
                    <label class="my-client-field"><span>Должность</span><input id="outreachFormPosition" class="auth-input" type="text" value="${outreachEscape(row.position || '')}" placeholder="Должность"></label>
                    <label class="my-client-field"><span>Телефон</span><input id="outreachFormPhone" class="auth-input" type="tel" value="${outreachEscape(row.phone || '')}" placeholder="+7 ..."></label>
                    <label class="my-client-field"><span>Почта</span><input id="outreachFormEmail" class="auth-input" type="email" value="${outreachEscape(row.email || '')}" placeholder="name@company.ru"></label>
                    <label class="my-client-field"><span>Сайт</span><input id="outreachFormWebsite" class="auth-input" type="text" value="${outreachEscape(row.website || '')}" placeholder="company.ru"></label>
                    <label class="my-client-field"><span>Город</span><input id="outreachFormCity" class="auth-input" type="text" value="${outreachEscape(row.city || '')}" placeholder="Город"></label>
                    <label class="my-client-field"><span>Как удобнее связаться</span><select id="outreachFormMethod" class="auth-input">
                        <option value="">Не указано</option>
                        <option value="phone" ${row.contact_method === 'phone' ? 'selected' : ''}>Телефон</option>
                        <option value="email" ${row.contact_method === 'email' ? 'selected' : ''}>Почта</option>
                        <option value="message" ${row.contact_method === 'message' ? 'selected' : ''}>Сообщение</option>
                        <option value="mixed" ${row.contact_method === 'mixed' ? 'selected' : ''}>Любой способ</option>
                    </select></label>
                    <label class="my-client-field"><span>Источник</span><input id="outreachFormSource" class="auth-input" type="text" value="${outreachEscape(row.source_name || '')}" placeholder="Например: Bitrix24"></label>
                    <label class="my-client-field"><span>Ответственный</span><input class="auth-input" type="text" value="${outreachEscape(managerName)}" readonly><input id="outreachFormManager" type="hidden" value="${outreachEscape(row.manager_email || currentUser?.email || '')}"></label>
                    <label class="my-client-field"><span>Первичный контакт до</span><input id="outreachFormPlannedDate" class="auth-input date-picker" type="text" value="${outreachEscape(row.planned_contact_date || '')}" placeholder="дд.мм.гггг" autocomplete="off"></label>
                    <label class="my-client-field"><span>Приоритет</span><select id="outreachFormPriority" class="auth-input">
                        <option value="high" ${row.priority === 'high' ? 'selected' : ''}>Высокий</option>
                        <option value="normal" ${String(row.priority || 'normal') === 'normal' ? 'selected' : ''}>Обычный</option>
                        <option value="low" ${row.priority === 'low' ? 'selected' : ''}>Низкий</option>
                    </select></label>
                    <label class="my-client-field"><span>Текущий статус</span><select id="outreachFormStatus" class="auth-input">
                        <option value="new" ${row.status === 'new' ? 'selected' : ''}>Новый клиент</option>
                        <option value="assigned" ${row.status === 'assigned' ? 'selected' : ''}>Новый клиент</option>
                        <option value="in_progress" ${row.status === 'in_progress' ? 'selected' : ''}>В работе</option>
                        <option value="no_answer" ${row.status === 'no_answer' ? 'selected' : ''}>Не дозвонились</option>
                        <option value="follow_up" ${row.status === 'follow_up' ? 'selected' : ''}>Повторный контакт</option>
                        <option value="warm" ${row.status === 'warm' ? 'selected' : ''}>Есть интерес</option>
                        <option value="meeting" ${row.status === 'meeting' ? 'selected' : ''}>Назначена встреча</option>
                        <option value="do_not_contact" ${row.status === 'do_not_contact' ? 'selected' : ''}>Не беспокоить</option>
                        <option value="converted" ${row.status === 'converted' ? 'selected' : ''}>Переведён в лид</option>
                        <option value="archived" ${row.status === 'archived' ? 'selected' : ''}>Архив</option>
                    </select></label>
                    <input id="outreachFormTags" type="hidden" value="${outreachEscape((row.tags || []).join(', '))}">
                    <label class="my-client-field my-client-field--wide"><span>Что узнали о клиенте</span><textarea id="outreachFormNotes" class="auth-input" rows="3" placeholder="Потребность, объём, особенности и важные детали">${outreachEscape(row.notes || '')}</textarea></label>
                </div>
                <div class="my-client-work-step__footer">
                    <span>Сначала сохраните уточнённые данные, затем зафиксируйте итог разговора.</span>
                    <button class="btn-primary" type="button" onclick="saveMyClientProfile(${Number(row.id || 0)})">Сохранить данные и продолжить</button>
                </div>
            </section>

            <section id="myClientContactStep" class="my-client-work-step">
                <div class="my-client-work-step__head">
                    <span class="my-client-work-step__number">2</span>
                    <div>
                        <h3>Зафиксируйте контакт</h3>
                        <p>После звонка, письма или встречи заполните результат и нажмите «Сохранить контакт».</p>
                    </div>
                </div>
                <div class="prospecting-activity-grid">
                    <label class="my-client-field"><span>Как связались</span><select id="outreachActivityType" class="auth-input">
                            <option value="call">Звонок</option>
                            <option value="email">Письмо</option>
                            <option value="message">Сообщение</option>
                            <option value="meeting">Встреча</option>
                        </select></label>
                    <label class="my-client-field"><span>Результат контакта *</span><select id="outreachActivityResult" class="auth-input" onchange="applyOutreachActivityResult(this.value)">
                            <option value="">Выберите результат</option>
                            <option value="no_answer">Нет ответа</option>
                            <option value="follow_up">Просил перезвонить</option>
                            <option value="warm">Есть интерес</option>
                            <option value="meeting">Назначена встреча</option>
                            <option value="do_not_contact">Не интересно / больше не звонить</option>
                        </select></label>
                    <label class="my-client-field"><span>Что сделать дальше</span><input id="outreachActivityNextAction" class="auth-input" type="text" placeholder="Например: отправить КП"></label>
                    <label class="my-client-field"><span>До какого числа</span><input id="outreachActivityNextDate" class="auth-input date-picker" type="text" placeholder="дд.мм.гггг" autocomplete="off"></label>
                    <label class="my-client-field my-client-field--wide"><span>Комментарий по итогам *</span><textarea id="outreachActivitySummary" class="auth-input" rows="3" placeholder="Коротко: о чём договорились и что важно учесть"></textarea></label>
                </div>
                <div class="my-client-work-step__footer">
                    <span>Сохранение добавит запись в историю и обновит статус клиента.</span>
                    <button class="btn-primary" type="button" onclick="saveOutreachActivity(${Number(row.id || 0)})">Сохранить контакт</button>
                </div>
            </section>

        </div>
    `;
}

function renderOutreachRegistry() {
    const rows = filteredOutreachRows();
    const selected = rows.find(row => Number(row.id) === Number(outreachSelectedId)) || null;
    return `
        <div class="crm-registry-layout">
            <section class="my-clients-list">
                <div class="my-clients-list__head">
                    <div><span class="my-client-list-icon">К</span><div><h2>Список моих клиентов</h2><p>Номер и ближайшее действие видны сразу. Для работы откройте карточку.</p></div></div>
                    <strong>${rows.length}</strong>
                </div>
                <div class="table-shell">
                <table class="admin-table admin-table--dense crm-registry-table">
                    <colgroup>
                        <col style="width: 27%;">
                        <col style="width: 18%;">
                        <col style="width: 21%;">
                        <col style="width: 20%;">
                        <col style="width: 14%;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Клиент</th>
                            <th>Телефон</th>
                            <th>Контактное лицо</th>
                            <th>Следующее действие</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => `
                            <tr class="${Number(row.id) === Number(outreachSelectedId) ? 'is-selected' : ''}" onclick="selectOutreachRow(${Number(row.id || 0)})">
                                <td class="crm-title-cell">
                                    <strong>${outreachEscape(row.company_name || '—')}</strong>
                                    <div class="table-subtext">${outreachEscape(outreachJourneyListLabel(row))}</div>
                                </td>
                                <td class="crm-contact-cell"><strong>${outreachEscape(row.phone || 'Не указан')}</strong><div class="table-subtext">${outreachEscape(row.email || '')}</div></td>
                                <td><strong>${outreachEscape(row.contact_name || 'Не указан')}</strong><div class="table-subtext">${outreachEscape(row.position || 'Должность не указана')}</div></td>
                                <td class="crm-action-cell"><strong>${outreachEscape(row.next_action || 'Связаться с клиентом')}</strong><div class="table-subtext ${row.is_overdue ? 'is-overdue' : ''}">${outreachEscape(row.next_action_date || row.planned_contact_date || 'Дата не назначена')}</div></td>
                                <td onclick="event.stopPropagation()">
                                    <button class="btn-secondary prospecting-open-client" type="button" onclick="selectOutreachRow(${Number(row.id || 0)})">Открыть клиента</button>
                                </td>
                            </tr>
                        `).join('') || '<tr><td colspan="5"><div class="empty-state">По текущему фильтру клиентов нет.</div></td></tr>'}
                    </tbody>
                </table>
                </div>
            </section>
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
        if (outreachIsSupervisor()) {
            managerSelect.innerHTML = outreachManagerOptions(false);
            managerSelect.value = row.manager_email || currentUser?.email || '';
        } else {
            managerSelect.innerHTML = `<option value="${outreachEscape(currentUser?.email || '')}" data-name="${outreachEscape(currentUser?.name || '')}">${outreachEscape(currentUser?.name || currentUser?.email || 'Менеджер')}</option>`;
            managerSelect.disabled = true;
        }
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
    document.getElementById('outreachEditorPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function selectOutreachRow(id) {
    outreachSelectedId = Number(id || 0);
    outreachClientEditMode = false;
    const mount = document.getElementById('prospectingContentMount');
    if (mount) mount.innerHTML = renderOutreachRegistry();
    initOutreachDatePicker();
}

function initOutreachDatePicker() {
    if (typeof flatpickr !== 'function') return;
    ['outreachFormPlannedDate', 'outreachActivityNextDate', 'unifiedLeadNextDate', 'unifiedLeadActivityDate', 'unifiedDealNextDate', 'unifiedDealCloseDate', 'unifiedDealActivityDate'].forEach(id => {
        const input = document.getElementById(id);
        if (!input || input._flatpickr) return;
        flatpickr(input, { locale: 'ru', dateFormat: 'd.m.Y', disableMobile: true, allowInput: true });
    });
}

function outreachJourneyListLabel(row) {
    const { lead, deal } = outreachJourneyRecords(row);
    if (deal) {
        if (deal.stage === 'won') return 'Продажа состоялась';
        if (deal.stage === 'lost') return 'Сделка закрыта';
        return `Сделка: ${typeof crmDealStageInfo === 'function' ? crmDealStageInfo(deal.stage).label : deal.stage}`;
    }
    if (lead) return lead.stage === 'lost' ? 'Закрыт без сделки' : 'Квалификация';
    return outreachStatusLabel(row.status);
}

function toggleUnifiedPanel(id, show) {
    const panel = document.getElementById(id);
    if (!panel) return;
    panel.hidden = !show;
    if (show) {
        initOutreachDatePicker();
        panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

async function refreshUnifiedJourney(reloadOutreach = false) {
    await Promise.all([
        typeof loadCrmLeads === 'function' ? loadCrmLeads() : Promise.resolve(),
        typeof loadCrmDeals === 'function' ? loadCrmDeals() : Promise.resolve(),
    ]);
    await renderProspecting(reloadOutreach);
}

async function saveUnifiedLead(leadId) {
    const lead = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!lead) return customAlert('Лид не найден. Обновите страницу.');
    const comment = String(document.getElementById('unifiedLeadNeed')?.value || '').trim();
    const nextAction = String(document.getElementById('unifiedLeadNextAction')?.value || '').trim();
    const nextDate = String(document.getElementById('unifiedLeadNextDate')?.value || '').trim();
    if (!comment) return customAlert('Опишите потребность клиента и договорённости.');
    if (!nextAction) return customAlert('Укажите конкретный следующий шаг.');
    if (!nextDate) return customAlert('Выберите срок следующего действия.');
    const res = await apiCall(`/crm/leads/${Number(leadId)}`, 'PUT', outreachLeadPayload(lead, {
        comment,
        stage: document.getElementById('unifiedLeadStage')?.value || 'qualified',
        budget: Number(document.getElementById('unifiedLeadBudget')?.value || 0),
        next_action: nextAction,
        next_action_date: nextDate,
    }));
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить квалификацию.');
    await refreshUnifiedJourney();
    showToast('Мои клиенты', 'Квалификация и следующий шаг сохранены');
}

async function saveUnifiedLeadContact(leadId) {
    const lead = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!lead) return customAlert('Лид не найден.');
    const subject = String(document.getElementById('unifiedLeadActivityNext')?.value || '').trim();
    const dueDate = String(document.getElementById('unifiedLeadActivityDate')?.value || '').trim();
    const summary = String(document.getElementById('unifiedLeadActivitySummary')?.value || '').trim();
    if (!summary) return customAlert('Запишите итог контакта.');
    if (!subject) return customAlert('Укажите, что сделать дальше.');
    if (!dueDate) return customAlert('Выберите срок следующего действия.');
    const activity = await apiCall('/crm/activities', 'POST', {
        entity_type: 'lead', entity_id: Number(leadId), activity_type: document.getElementById('unifiedLeadActivityType')?.value || 'call',
        subject, summary, due_date: dueDate, owner_name: currentUser?.name || '', status: 'open',
    });
    if (!activity || activity.error) return customAlert(activity?.message || 'Не удалось сохранить контакт.');
    const update = await apiCall(`/crm/leads/${Number(leadId)}`, 'PUT', outreachLeadPayload(lead, { next_action: subject, next_action_date: dueDate }));
    if (!update || update.error) return customAlert(update?.message || 'Контакт сохранён, но следующий шаг не обновился.');
    await refreshUnifiedJourney();
    showToast('Мои клиенты', 'Контакт и следующий шаг сохранены');
}

async function convertUnifiedLeadToDeal(leadId) {
    const lead = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!lead) return customAlert('Лид не найден.');
    const need = String(document.getElementById('unifiedLeadNeed')?.value || '').trim();
    const nextAction = String(document.getElementById('unifiedLeadNextAction')?.value || '').trim();
    const nextDate = String(document.getElementById('unifiedLeadNextDate')?.value || '').trim();
    if (!need || !nextAction || !nextDate) return customAlert('Перед созданием сделки заполните потребность, следующий шаг и срок.');
    const save = await apiCall(`/crm/leads/${Number(leadId)}`, 'PUT', outreachLeadPayload(lead, {
        comment: need, stage: document.getElementById('unifiedLeadStage')?.value || 'qualified',
        budget: Number(document.getElementById('unifiedLeadBudget')?.value || 0), next_action: nextAction, next_action_date: nextDate,
    }));
    if (!save || save.error) return customAlert(save?.message || 'Не удалось сохранить данные перед созданием сделки.');
    const res = await apiCall(`/crm/leads/${Number(leadId)}/convert`, 'POST');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось создать сделку.');
    await refreshUnifiedJourney();
    showToast('Мои клиенты', 'Сделка создана и открыта в этой карточке');
}

async function closeUnifiedLead(leadId) {
    const lead = (crmLeadsDB || []).find(item => Number(item.id || 0) === Number(leadId || 0));
    if (!lead) return customAlert('Лид не найден.');
    const reason = String(document.getElementById('unifiedLeadLossReason')?.value || '').trim();
    if (reason.length < 3) return customAlert('Укажите причину закрытия.');
    const date = outreachToday();
    const res = await apiCall(`/crm/leads/${Number(leadId)}`, 'PUT', outreachLeadPayload(lead, {
        stage: 'lost', next_action: '', next_action_date: '', comment: `${lead.comment || ''}\n[Закрыт без сделки ${date}] Причина: ${reason}`.trim(),
    }));
    if (!res || res.error) return customAlert(res?.message || 'Не удалось закрыть клиента без сделки.');
    await apiCall('/crm/activities', 'POST', { entity_type: 'lead', entity_id: Number(leadId), activity_type: 'note', subject: 'Закрыт без сделки', summary: reason, due_date: date, owner_name: currentUser?.name || '', status: 'done' });
    await refreshUnifiedJourney();
    showToast('Мои клиенты', 'Результат и причина сохранены');
}

function unifiedDealProductsFromInput() {
    return String(document.getElementById('unifiedDealProducts')?.value || '').split('\n').map(line => {
        const [name = '', quantityText = '1', priceText = '0'] = line.split('|').map(item => item.trim());
        return { name, quantity: Math.max(1, Number(quantityText || 1)), unit_price: Math.max(0, Number(priceText || 0)) };
    }).filter(item => item.name);
}

async function saveUnifiedDeal(dealId) {
    const deal = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!deal) return customAlert('Сделка не найдена.');
    const nextAction = String(document.getElementById('unifiedDealNextAction')?.value || '').trim();
    if (!nextAction) return customAlert('Укажите конкретный следующий шаг по сделке.');
    const res = await apiCall(`/crm/deals/${Number(dealId)}`, 'PUT', outreachDealPayload(deal, {
        stage: document.getElementById('unifiedDealStage')?.value || 'qualification', amount: Number(document.getElementById('unifiedDealAmount')?.value || 0),
        next_action: nextAction, next_action_date: document.getElementById('unifiedDealNextDate')?.value || '', expected_close_date: document.getElementById('unifiedDealCloseDate')?.value || '',
    }));
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить сделку.');
    await refreshUnifiedJourney();
    showToast('Мои клиенты', 'Этап и следующий шаг сделки сохранены');
}

async function saveUnifiedDealDetails(dealId) {
    const deal = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!deal) return customAlert('Сделка не найдена.');
    const res = await apiCall(`/crm/deals/${Number(dealId)}`, 'PUT', outreachDealPayload(deal, {
        contact_name: document.getElementById('unifiedDealContactName')?.value || '', contact_phone: document.getElementById('unifiedDealContactPhone')?.value || '',
        contact_email: document.getElementById('unifiedDealContactEmail')?.value || '', contract_number: document.getElementById('unifiedDealContract')?.value || '',
        products: unifiedDealProductsFromInput(), comment: document.getElementById('unifiedDealComment')?.value || '',
    }));
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить данные сделки.');
    await refreshUnifiedJourney();
    showToast('Мои клиенты', 'Данные сделки сохранены');
}

async function saveUnifiedDealContact(dealId) {
    const deal = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!deal) return customAlert('Сделка не найдена.');
    const subject = String(document.getElementById('unifiedDealActivityNext')?.value || '').trim();
    const summary = String(document.getElementById('unifiedDealActivitySummary')?.value || '').trim();
    const dueDate = String(document.getElementById('unifiedDealActivityDate')?.value || '').trim();
    if (!summary) return customAlert('Запишите итог контакта.');
    if (!subject) return customAlert('Укажите следующий шаг.');
    const activity = await apiCall('/crm/activities', 'POST', { entity_type: 'deal', entity_id: Number(dealId), activity_type: document.getElementById('unifiedDealActivityType')?.value || 'call', subject, summary, due_date: dueDate, owner_name: currentUser?.name || '', status: 'open' });
    if (!activity || activity.error) return customAlert(activity?.message || 'Не удалось сохранить контакт.');
    const update = await apiCall(`/crm/deals/${Number(dealId)}`, 'PUT', outreachDealPayload(deal, { next_action: subject, next_action_date: dueDate }));
    if (!update || update.error) return customAlert(update?.message || 'Контакт сохранён, но следующий шаг не обновился.');
    await refreshUnifiedJourney();
    showToast('Мои клиенты', 'Контакт и следующий шаг сделки сохранены');
}

function openUnifiedDealOutcome(type) {
    const won = String(type || '') === 'won';
    const input = document.getElementById('unifiedDealOutcomeType');
    const title = document.getElementById('unifiedDealOutcomeTitle');
    const panel = document.getElementById('unifiedDealOutcomePanel');
    if (input) input.value = won ? 'won' : 'lost';
    if (title) title.textContent = won ? 'Почему продажа состоялась?' : 'Почему клиент отказался?';
    panel?.classList.toggle('unified-inline-panel--danger', !won);
    toggleUnifiedPanel('unifiedDealOutcomePanel', true);
}

async function closeUnifiedDeal(dealId) {
    const deal = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    if (!deal) return customAlert('Сделка не найдена.');
    const stage = document.getElementById('unifiedDealOutcomeType')?.value || '';
    const reason = String(document.getElementById('unifiedDealOutcomeReason')?.value || '').trim();
    if (!['won', 'lost'].includes(stage)) return customAlert('Выберите результат сделки.');
    if (reason.length < 3) return customAlert('Укажите причину результата.');
    const res = await apiCall(`/crm/deals/${Number(dealId)}`, 'PUT', outreachDealPayload(deal, { stage, loss_reason: reason, actual_close_date: outreachToday(), next_action: '', next_action_date: '' }));
    if (!res || res.error) return customAlert(res?.message || 'Не удалось завершить сделку.');
    await refreshUnifiedJourney();
    showToast('Мои клиенты', stage === 'won' ? 'Продажа успешно завершена' : 'Отказ клиента сохранён');
}

async function openOutreachJourneyByLead(leadId) {
    await ensureOutreachData(false, 'mine');
    const row = (outreachProspectsDB || []).find(item => Number(item.converted_lead_id || 0) === Number(leadId || 0));
    if (row) outreachSelectedId = Number(row.id || 0);
    navigateTo('myProspecting');
}

async function openOutreachJourneyByDeal(dealId) {
    await Promise.all([loadCrmLeads(), loadCrmDeals(), ensureOutreachData(false, 'mine')]);
    const deal = (crmDealsDB || []).find(item => Number(item.id || 0) === Number(dealId || 0));
    const row = (outreachProspectsDB || []).find(item => Number(item.converted_lead_id || 0) === Number(deal?.lead_id || 0));
    if (row) outreachSelectedId = Number(row.id || 0);
    navigateTo('myProspecting');
}

function scrollToMyClientStep(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function saveMyClientProfile(id) {
    outreachEditingId = Number(id || 0);
    await saveOutreachProspect('myClientContactStep');
}

function editOutreachClient(id) {
    outreachSelectedId = Number(id || outreachSelectedId || 0);
    outreachClientEditMode = true;
    const mount = document.getElementById('prospectingContentMount');
    if (mount) mount.innerHTML = renderOutreachRegistry();
    initOutreachDatePicker();
    scrollToMyClientStep('myClientProfileStep');
}

function toggleOutreachRejectForm(show) {
    const panel = document.getElementById('outreachRejectPanel');
    if (!panel) return;
    panel.hidden = !show;
    if (show) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(() => document.getElementById('outreachRejectReason')?.focus(), 180);
    }
}

async function rejectOutreachClient(prospectId) {
    const reason = String(document.getElementById('outreachRejectReason')?.value || '').trim();
    if (reason.length < 3) return customAlert('Укажите причину отказа клиента.');
    const res = await apiCall('/outreach/activities', 'POST', {
        prospect_id: Number(prospectId || 0),
        activity_type: 'note',
        result_status: 'do_not_contact',
        prospect_status: 'do_not_contact',
        next_action: '',
        next_action_date: '',
        summary: `Причина отказа: ${reason}`,
    });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить отказ клиента.');
    outreachClientEditMode = false;
    await renderProspecting(true);
    showToast('Мои клиенты', 'Отказ и причина сохранены в карточке');
}

function applyOutreachActivityResult(result) {
    const nextAction = document.getElementById('outreachActivityNextAction');
    const suggestions = {
        no_answer: 'Перезвонить',
        follow_up: 'Связаться повторно',
        warm: 'Подготовить и отправить предложение',
        meeting: 'Провести встречу',
        converted: 'Перевести в лид',
        do_not_contact: '',
    };
    if (nextAction && !nextAction.value.trim()) nextAction.value = suggestions[String(result || '')] || '';
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

function toggleOutreachAdvancedFilters() {
    const panel = document.querySelector('#myProspectingView .prospecting-filter-panel');
    const toggle = document.getElementById('outreachAdvancedToggle');
    const advanced = document.getElementById('outreachAdvancedFilters');
    if (!panel || !toggle || !advanced) return;
    const expanded = panel.classList.toggle('prospecting-filter-panel--advanced');
    toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    advanced.setAttribute('aria-hidden', expanded ? 'false' : 'true');
}

function toggleOutreachOverdueFilter() {
    outreachOnlyOverdue = !outreachOnlyOverdue;
    renderProspecting();
}

function toggleOutreachTodayFilter() {
    outreachOnlyToday = !outreachOnlyToday;
    renderProspecting();
}

function toggleOutreachProblemFilter() {
    outreachOnlyProblems = !outreachOnlyProblems;
    renderProspecting();
}

function setOutreachQuickFilter(value) {
    outreachQuickFilter = outreachQuickFilter === value ? '' : String(value || '');
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
    outreachOnlyProblems = false;
    outreachQuickFilter = '';
    const searchInput = document.getElementById('outreachSearchInput');
    if (searchInput) searchInput.value = '';
    renderProspecting();
}

async function saveOutreachProspect(nextStepId = '') {
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
    if (nextStepId) scrollToMyClientStep(nextStepId);
    showToast('Мои клиенты', 'Данные клиента сохранены');
    return true;
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
    if (!payload.result_status.trim()) return customAlert('Выберите результат контакта.');
    if (!payload.summary.trim()) return customAlert('Коротко напишите, чем закончился контакт.');
    const requiresNextStep = ['no_answer', 'follow_up', 'warm', 'meeting'].includes(payload.result_status);
    if (requiresNextStep && !payload.next_action.trim()) return customAlert('Укажите, что нужно сделать дальше.');
    if (requiresNextStep && !payload.next_action_date.trim()) return customAlert('Выберите дату следующего контакта.');
    const res = await apiCall('/outreach/activities', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить контакт.');
    outreachClientEditMode = false;
    await renderProspecting(true);
    scrollToMyClientStep('myClientCardStep');
    showToast('Мои клиенты', 'Контакт сохранён, следующий шаг обновлён');
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
    await loadOutreachControl();
    renderOutreachDirectorPanel();
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
    const id = Number(prospectId || 0);
    if (!id) return customAlert('\u041d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d\u0430 \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0430 \u043a\u043b\u0438\u0435\u043d\u0442\u0430.');
    outreachSelectedId = id;
    const res = await apiCall('/outreach/prospects/bulk', 'POST', {
        ids: [id],
        action: 'mark_processed',
        status: 'in_progress',
    });
    if (!res || res.error) return customAlert(res?.message || '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043c\u0435\u0442\u0438\u0442\u044c \u043a\u043b\u0438\u0435\u043d\u0442\u0430 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043d\u044b\u043c.');
    await renderProspecting(true);
    showToast('\u0411\u0430\u0437\u0430 \u0440\u0430\u0437\u0432\u0438\u0442\u0438\u044f', '\u041a\u043b\u0438\u0435\u043d\u0442 \u043e\u0442\u043c\u0435\u0447\u0435\u043d \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043d\u044b\u043c');
}

async function convertOutreachProspect(prospectId) {
    const id = Number(prospectId || 0);
    if (!id) return customAlert('\u041d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d\u0430 \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0430 \u043a\u043b\u0438\u0435\u043d\u0442\u0430.');
    outreachSelectedId = id;
    if (!(await customConfirm('Перевести клиента к квалификации? Карточка останется на этой странице, а все заполненные данные сохранятся.'))) return;
    const res = await apiCall(`/outreach/prospects/${id}/convert`, 'POST');
    if (!res || res.error) return customAlert(res?.message || '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0435\u0440\u0435\u0432\u0435\u0441\u0442\u0438 \u043a\u043b\u0438\u0435\u043d\u0442\u0430 \u0432 \u043b\u0438\u0434.');
    await Promise.all([loadOutreachProspects(), loadCrmLeads(), loadCrmDeals()]);
    await renderProspecting(true);
    showToast('Мои клиенты', 'Квалификация открыта в карточке клиента');
}

async function quickOutreachAction(event, prospectId, action) {
    if (event) event.stopPropagation();
    const id = Number(prospectId || 0);
    if (!id) return;
    if (action === 'convert') {
        const res = await apiCall(`/outreach/prospects/${id}/convert`, 'POST');
        if (!res || res.error) return customAlert(res?.message || 'Не удалось перевести запись в лид.');
        await Promise.all([loadOutreachProspects(), loadCrmLeads()]);
        showToast('База развития', 'Запись переведена в лид');
        await renderProspecting(true);
        return;
    }
    const configs = {
        call: { activity_type: 'call', result_status: '', prospect_status: 'in_progress', summary: 'Быстрый звонок' },
        email: { activity_type: 'email', result_status: '', prospect_status: 'in_progress', summary: 'Быстрое письмо' },
        no_answer: { activity_type: 'call', result_status: 'no_answer', prospect_status: 'no_answer', summary: 'Нет ответа' },
        warm: { activity_type: 'call', result_status: 'warm', prospect_status: 'warm', summary: 'Есть интерес' },
    };
    const config = configs[action];
    if (!config) return;
    const res = await apiCall('/outreach/activities', 'POST', { prospect_id: id, ...config });
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить быстрое действие.');
    await renderProspecting(true);
}

async function parseOutreachFile(file) {
    const lower = String(file?.name || '').toLowerCase();
    if (!file) return [];
    if (lower.endsWith('.json')) {
        const text = await file.text();
        const parsed = JSON.parse(text || '[]');
        return Array.isArray(parsed) ? parsed : [];
    }
    if (lower.endsWith('.csv') || lower.endsWith('.tsv')) {
        const text = await file.text();
        return parseOutreachDelimitedText(text, detectOutreachDelimiter(text, lower));
    }
    if (lower.endsWith('.txt')) {
        const text = await file.text();
        if (!/[,\t;]/.test(text)) {
            return text.split('\n').map(line => line.trim()).filter(Boolean).map(line => ({ company_name: line }));
        }
        return parseOutreachDelimitedText(text, detectOutreachDelimiter(text, lower));
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

function buildOutreachImportPayload(file, rows) {
    if (!Array.isArray(rows) || !rows.length) return customAlert('Файл не содержит строк для загрузки.');
    const managerEmail = document.getElementById('outreachImportManager')?.value || '';
    return {
        filename: file.name,
        source_name: document.getElementById('outreachImportSource')?.value || '',
        default_manager_email: managerEmail,
        default_manager_name: outreachFindManagerNameByEmail(managerEmail),
        planned_contact_date: document.getElementById('outreachImportPlanDate')?.value || '',
        rows,
    };
}

async function readOutreachImportSelection() {
    const fileInput = document.getElementById('outreachImportFile');
    const file = fileInput?.files?.[0];
    if (!file) {
        customAlert('Выбери файл со списком клиентов.');
        return null;
    }
    let rows = [];
    try {
        rows = await parseOutreachFile(file);
    } catch (error) {
        customAlert(`Не удалось прочитать файл: ${error?.message || error}`);
        return null;
    }
    if (!Array.isArray(rows) || !rows.length) {
        customAlert('Файл не содержит строк для загрузки.');
        return null;
    }
    return { file, rows, payload: buildOutreachImportPayload(file, rows) };
}

async function previewOutreachImport() {
    const selection = await readOutreachImportSelection();
    if (!selection) return;
    const res = await apiCall('/outreach/prospects/import_preview', 'POST', selection.payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось построить предпросмотр.');
    outreachImportPreview = { ...res, filename: selection.file.name };
    renderOutreachImportPreview();
}

async function importOutreachFile() {
    const fileInput = document.getElementById('outreachImportFile');
    const selection = await readOutreachImportSelection();
    if (!selection) return;
    const { file, rows, payload } = selection;
    const res = await apiCall('/outreach/prospects/import_rows', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось загрузить базу.');
    outreachLastImportResult = {
        filename: file.name,
        rows_total: rows.length,
        created: Number(res.created || 0),
        updated: Number(res.updated || 0),
        skipped: Number(res.skipped || 0),
    };
    outreachImportPreview = null;
    if (fileInput) fileInput.value = '';
    showToast('База развития', `Импорт: загружено ${rows.length}, создано ${Number(res.created || 0)}, обновлено ${Number(res.updated || 0)}, пропущено ${Number(res.skipped || 0)}`);
    await renderProspecting(true);
}

function filteredOutreachPoolRows() {
    const needle = outreachPoolSearch.trim().toLowerCase();
    if (!needle) return outreachPoolRows;
    return outreachPoolRows.filter(row => [
        row.company_name,
        row.contact_name,
        row.phone,
        row.email,
        row.source_name,
        row.city,
    ].join(' ').toLowerCase().includes(needle));
}

function outreachPoolDate(value) {
    const timestamp = Number(value || 0);
    if (!timestamp) return '—';
    return new Date(timestamp * 1000).toLocaleDateString('ru-RU');
}

function renderOutreachPoolSummary() {
    const mount = document.getElementById('outreachPoolSummary');
    if (!mount) return;
    const rows = outreachPoolRows || [];
    const withPhone = rows.filter(row => String(row.phone || '').trim()).length;
    const withEmail = rows.filter(row => String(row.email || '').trim()).length;
    const bitrix = rows.filter(row => String(row.source_name || '') === 'Bitrix24 API').length;
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Свободно сейчас</div><div class="crm-summary-value">${rows.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">С телефоном</div><div class="crm-summary-value">${withPhone}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">С почтой</div><div class="crm-summary-value">${withEmail}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Из Bitrix24</div><div class="crm-summary-value">${bitrix}</div></div>
    `;
}

function renderOutreachPool() {
    const mount = document.getElementById('outreachPoolMount');
    if (!mount) return;
    const rows = filteredOutreachPoolRows();
    mount.innerHTML = `
        <div class="table-shell outreach-pool-table-shell">
            <table class="admin-table admin-table--dense outreach-pool-table">
                <colgroup>
                    <col style="width: 28%;">
                    <col style="width: 20%;">
                    <col style="width: 23%;">
                    <col style="width: 14%;">
                    <col style="width: 15%;">
                </colgroup>
                <thead>
                    <tr>
                        <th>Компания</th>
                        <th>Контакт</th>
                        <th>Связь</th>
                        <th>Источник</th>
                        <th>Действие</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(row => `
                        <tr data-pool-prospect-id="${Number(row.id || 0)}">
                            <td class="crm-title-cell"><strong>${outreachEscape(row.company_name || 'Без названия')}</strong><div class="table-subtext">Обновлено ${outreachPoolDate(row.updated_at)}</div></td>
                            <td class="crm-title-cell">${outreachEscape(row.contact_name || '—')}<div class="table-subtext">${outreachEscape(row.position || '')}</div></td>
                            <td class="crm-contact-cell">${outreachEscape(row.phone || '—')}<div class="table-subtext">${outreachEscape(row.email || '—')}</div></td>
                            <td><span class="crm-inline-pill crm-inline-pill--neutral">${outreachEscape(row.source_name || 'CRM')}</span></td>
                            <td><button class="btn-primary outreach-claim-button" type="button" onclick="claimOutreachProspect(${Number(row.id || 0)}, this)">Забрать себе</button></td>
                        </tr>
                    `).join('') || '<tr><td colspan="5"><div class="empty-state">Свободных клиентов по этому запросу нет. Обновите выгрузку Bitrix24 или очистите поиск.</div></td></tr>'}
                </tbody>
            </table>
        </div>
    `;
}

async function refreshOutreachPool(showLoading = false) {
    const mount = document.getElementById('outreachPoolMount');
    if (showLoading && mount) mount.innerHTML = '<div class="empty-state">Обновляю свободную базу...</div>';
    const data = await apiCall('/outreach/prospects?scope=free');
    if (!Array.isArray(data)) {
        if (showLoading && mount) {
            renderOutreachPool();
            const notice = document.getElementById('outreachPoolNotice');
            if (notice) {
                notice.hidden = false;
                notice.textContent = outreachPoolRows.length ? 'Не удалось обновить список. Показаны ранее загруженные клиенты. Нажмите «Обновить», чтобы повторить.' : 'Не удалось загрузить клиентов. Нажмите «Обновить», чтобы повторить.';
            }
        }
        return outreachPoolRows;
    }
    outreachPoolRows = data;
    const notice = document.getElementById('outreachPoolNotice');
    if (notice) notice.hidden = true;
    renderOutreachPoolSummary();
    renderOutreachPool();
    return outreachPoolRows;
}

function setOutreachPoolSearch(value) {
    outreachPoolSearch = String(value || '');
    renderOutreachPool();
}

async function claimOutreachProspect(prospectId, button = null) {
    const id = Number(prospectId || 0);
    if (!id) return;
    if (button) {
        button.disabled = true;
        button.textContent = 'Забираю...';
    }
    const res = await apiCall(`/outreach/prospects/${id}/claim`, 'POST');
    if (!res || res.error || res.status === 'conflict') {
        await refreshOutreachPool(false);
        return customAlert(res?.error === 'already_claimed'
            ? 'Этого клиента уже забрал другой менеджер. Список свободных клиентов обновлён.'
            : 'Не удалось забрать клиента. Обновите страницу и попробуйте ещё раз.');
    }
    outreachPoolRows = outreachPoolRows.filter(row => Number(row.id) !== id);
    renderOutreachPoolSummary();
    renderOutreachPool();
    outreachSelectedId = id;
    await ensureOutreachData(true, 'mine');
    navigateTo('myProspecting');
    showToast('База развития', 'Клиент ваш. Рабочая карточка уже открыта');
}

async function renderOutreachPoolPage() {
    const bitrixButton = document.getElementById('outreachBitrixNavButton');
    if (bitrixButton) bitrixButton.style.display = canUseBitrixImport() ? '' : 'none';
    await Promise.all([refreshOutreachPool(!outreachPoolRows.length), loadBitrixConnectionStatus()]);
    if (!outreachPoolRefreshTimer) {
        outreachPoolRefreshTimer = window.setInterval(() => {
            if (window.__navCurrentView === 'prospecting') refreshOutreachPool(false);
        }, 12000);
    }
}

async function renderProspecting(forceReload = false) {
    await Promise.all([
        ensureOutreachData(forceReload, 'mine'),
        typeof loadCrmLeads === 'function' ? loadCrmLeads() : Promise.resolve(),
        typeof loadCrmDeals === 'function' ? loadCrmDeals() : Promise.resolve(),
    ]);
    renderOutreachManagerSelects();
    renderOutreachImportPreview();
    renderOutreachImportResult();
    renderOutreachBitrixPanel();
    syncOutreachFilterControls();
    renderOutreachSummary();
    renderOutreachDirectorPanel();
    renderOutreachKnowledgePanel();
    renderOutreachReportPanel();
    const overdueBtn = document.getElementById('outreachOverdueBtn');
    const todayBtn = document.getElementById('outreachTodayBtn');
    const problemsBtn = document.getElementById('outreachProblemsBtn');
    [
        [overdueBtn, outreachOnlyOverdue],
        [todayBtn, outreachOnlyToday],
        [problemsBtn, outreachOnlyProblems],
    ].forEach(([button, active]) => {
        if (!button) return;
        button.classList.toggle('btn-primary', Boolean(active));
        button.classList.toggle('btn-secondary', !active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const mount = document.getElementById('prospectingContentMount');
    if (mount) mount.innerHTML = renderOutreachRegistry();
    initOutreachDatePicker();
}

window.renderProspecting = renderProspecting;
window.renderMyProspecting = renderProspecting;
window.renderOutreachPoolPage = renderOutreachPoolPage;
window.renderBitrixImport = renderBitrixImport;
window.openOutreachEditor = openOutreachEditor;
window.closeOutreachEditor = closeOutreachEditor;
window.saveOutreachProspect = saveOutreachProspect;
window.selectOutreachRow = selectOutreachRow;
window.applyOutreachActivityResult = applyOutreachActivityResult;
window.saveMyClientProfile = saveMyClientProfile;
window.scrollToMyClientStep = scrollToMyClientStep;
window.editOutreachClient = editOutreachClient;
window.toggleOutreachRejectForm = toggleOutreachRejectForm;
window.rejectOutreachClient = rejectOutreachClient;
window.toggleOutreachSelection = toggleOutreachSelection;
window.toggleAllOutreachSelection = toggleAllOutreachSelection;
window.applyOutreachSearch = applyOutreachSearch;
window.setOutreachStatusFilter = setOutreachStatusFilter;
window.setOutreachPriorityFilter = setOutreachPriorityFilter;
window.setOutreachManagerFilter = setOutreachManagerFilter;
window.setOutreachProcessedFilter = setOutreachProcessedFilter;
window.toggleOutreachOverdueFilter = toggleOutreachOverdueFilter;
window.toggleOutreachTodayFilter = toggleOutreachTodayFilter;
window.toggleOutreachProblemFilter = toggleOutreachProblemFilter;
window.setOutreachQuickFilter = setOutreachQuickFilter;
window.resetOutreachFilters = resetOutreachFilters;
window.previewOutreachImport = previewOutreachImport;
window.importOutreachFile = importOutreachFile;
window.searchBitrixClients = searchBitrixClients;
window.toggleBitrixClientSelection = toggleBitrixClientSelection;
window.importSelectedBitrixClients = importSelectedBitrixClients;
window.syncBitrixClientsNow = syncBitrixClientsNow;
window.updateBitrixClientsNow = updateBitrixClientsNow;
window.clearBitrixClientList = clearBitrixClientList;
window.testBitrixConnection = testBitrixConnection;
window.saveBitrixConnection = saveBitrixConnection;
window.refreshOutreachPool = refreshOutreachPool;
window.setOutreachPoolSearch = setOutreachPoolSearch;
window.claimOutreachProspect = claimOutreachProspect;
window.exportOutreachDirectorReport = exportOutreachDirectorReport;
window.askOutreachAssistant = askOutreachAssistant;
window.applyOutreachBulkAction = applyOutreachBulkAction;
window.saveOutreachActivity = saveOutreachActivity;
window.saveOutreachReport = saveOutreachReport;
window.markOutreachProcessed = markOutreachProcessed;
window.convertOutreachProspect = convertOutreachProspect;
window.toggleOutreachReportPanel = toggleOutreachReportPanel;
window.quickOutreachAction = quickOutreachAction;
window.toggleUnifiedPanel = toggleUnifiedPanel;
window.saveUnifiedLead = saveUnifiedLead;
window.saveUnifiedLeadContact = saveUnifiedLeadContact;
window.convertUnifiedLeadToDeal = convertUnifiedLeadToDeal;
window.closeUnifiedLead = closeUnifiedLead;
window.saveUnifiedDeal = saveUnifiedDeal;
window.saveUnifiedDealDetails = saveUnifiedDealDetails;
window.saveUnifiedDealContact = saveUnifiedDealContact;
window.openUnifiedDealOutcome = openUnifiedDealOutcome;
window.closeUnifiedDeal = closeUnifiedDeal;
window.openOutreachJourneyByLead = openOutreachJourneyByLead;
window.openOutreachJourneyByDeal = openOutreachJourneyByDeal;
