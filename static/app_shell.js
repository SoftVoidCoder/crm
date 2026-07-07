let ws;

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function nl2brSafe(value) {
    return escapeHtml(value).replace(/\n/g, '<br>');
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onmessage = async (event) => {
        if (!currentUser || currentUser.status !== 'approved') return;
        const data = JSON.parse(event.data);

        if (data.type === 'projects') {
            await loadProjects();
            if (document.getElementById('dashboardView') && document.getElementById('dashboardView').style.display === 'block') {
                if (typeof renderDashboard === 'function') renderDashboard();
                if (document.getElementById('analyticsView') && document.getElementById('analyticsView').style.display === 'block' && typeof drawCharts === 'function') drawCharts();
            } else if (document.getElementById('projectView') && document.getElementById('projectView').style.display === 'block') {
                if (typeof updateChecklistUI === 'function') updateChecklistUI();
                if (typeof renderChat === 'function') renderChat();
                if (typeof renderFiles === 'function') renderFiles();
                if (typeof renderProjectSmartTools === 'function') renderProjectSmartTools();
            }
            if (typeof renderNotifications === 'function') renderNotifications();
        } else if (data.type === 'tasks') {
            await loadTasks();
            if (document.getElementById('tasksView') && document.getElementById('tasksView').style.display === 'block' && typeof renderTasks === 'function') renderTasks();
            if (document.getElementById('kpiView') && document.getElementById('kpiView').style.display === 'block' && typeof renderKPI === 'function') renderKPI();
        } else if (data.type === 'chats') {
            if (typeof loadGlobalChats === 'function') await loadGlobalChats();
            const messView = document.getElementById('messengerView');
            if (messView && messView.style.display === 'block') {
                if (typeof currentGlobalChatId !== 'undefined' && currentGlobalChatId !== null) {
                    if (typeof loadGlobalMessages === 'function') loadGlobalMessages(currentGlobalChatId, false);
                } else if (typeof renderGlobalChats === 'function') {
                    renderGlobalChats();
                }
            }
        } else if (data.type === 'feed') {
            const messView = document.getElementById('messengerView');
            if (messView && messView.style.display === 'block' && typeof loadCompanyFeed === 'function') {
                await loadCompanyFeed();
            }
        } else if (data.type === 'documents') {
            await loadDocuments();
            if (document.getElementById('documentsView') && document.getElementById('documentsView').style.display === 'block' && typeof renderDocuments === 'function') renderDocuments();
        } else if (data.type === 'approvals') {
            await loadApprovals();
            if (document.getElementById('approvalsView') && document.getElementById('approvalsView').style.display === 'block' && typeof renderApprovals === 'function') renderApprovals();
        } else if (data.type === 'meetings') {
            await loadMeetings();
            if (document.getElementById('meetingsView') && document.getElementById('meetingsView').style.display === 'block' && typeof renderMeetings === 'function') renderMeetings();
        } else if (data.type === 'knowledge') {
            await loadKnowledge();
            if (document.getElementById('knowledgeView') && document.getElementById('knowledgeView').style.display === 'block' && typeof renderKnowledge === 'function') renderKnowledge();
        } else if (data.type === 'claims') {
            await loadClaims();
            if (document.getElementById('claimsView') && document.getElementById('claimsView').style.display === 'block' && typeof renderClaims === 'function' && currentLegalTab === 'claims') renderClaims();
        } else if (data.type === 'court_cases') {
            await loadCourtCases();
            if (document.getElementById('claimsView') && document.getElementById('claimsView').style.display === 'block' && typeof renderCourts === 'function' && currentLegalTab === 'courts') renderCourts();
        } else if (data.type === 'notifications') {
            await loadNotifications();
            if (typeof renderNotifications === 'function') renderNotifications();
        }
    };

    ws.onclose = () => {
        setTimeout(connectWebSocket, 5000);
    };
}

async function login() {
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    const otpField = document.getElementById('loginOtpCode');
    const otpWrap = document.getElementById('loginOtpWrap');
    const otpHint = document.getElementById('loginOtpHint');
    const errorBox = document.getElementById('loginError');
    if (errorBox) errorBox.innerText = '';
    const res = await apiCall('/login', 'POST', { email, password, otp_code: otpField?.value || '' });
    if (res && res.error) {
        if (errorBox) errorBox.innerText = res.error;
        if (res.two_factor_required) {
            if (otpWrap) otpWrap.style.display = 'block';
            if (otpHint) otpHint.style.display = 'block';
        }
        return;
    }
    if (otpWrap) otpWrap.style.display = 'none';
    if (otpHint) otpHint.style.display = 'none';
    if (errorBox) errorBox.innerText = '';
    currentUser = res;
    window.location.href = currentUser && currentUser.status === 'approved' ? '/app' : '/static/login.html';
}

document.addEventListener('DOMContentLoaded', () => {
    updateCommandPaletteShortcutHints();
    const loginEmail = document.getElementById('loginEmail');
    const loginPassword = document.getElementById('loginPassword');
    const loginOtpCode = document.getElementById('loginOtpCode');
    const loginError = document.getElementById('loginError');
    if (loginEmail) {
        loginEmail.focus();
    }
    [loginEmail, loginPassword, loginOtpCode].forEach(field => {
        if (!field) return;
        field.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                login();
            }
        });
        field.addEventListener('input', () => {
            if (loginError) loginError.innerText = '';
        });
    });
});

async function register() {
    const name = document.getElementById('regName').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const pass = document.getElementById('regPassword').value;
    const errDiv = document.getElementById('regError');
    const btn = document.querySelector('#registerFormCard button');
    if (!name || !email || !pass) {
        errDiv.innerText = "Заполните все поля!";
        return;
    }
    if (btn) {
        btn.innerText = "Отправка...";
        btn.disabled = true;
    }
    const res = await apiCall('/register', 'POST', { email, password: pass, name });
    if (!res || res.error) {
        errDiv.innerText = (res && res.error) ? res.error : "Ошибка сервера";
        if (btn) {
            btn.innerText = "Отправить заявку";
            btn.disabled = false;
        }
        return;
    }
    currentUser = null;
    customAlert("Заявка успешно отправлена!\nОжидайте одобрения Директором.").then(() => {
        window.location.href = '/static/login.html';
    });
}

async function recoverPassword() {
    const email = document.getElementById('recEmail').value;
    if (!email) return;
    await apiCall('/recover', 'POST', { email });
    customAlert("Письмо для восстановления отправлено.");
    const recF = document.getElementById('recoverFormCard');
    if (recF) recF.style.display = 'none';
    const logF = document.getElementById('loginFormCard');
    if (logF) logF.style.display = 'block';
}

async function logout() {
    await apiCall('/logout', 'POST');
    currentUser = null;
    localStorage.removeItem('korda_session');
    window.location.href = '/static/login.html';
}

function showToast(title, message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const id = Date.now();
    const html = `
        <div id="toast_${id}" class="toast fade-in" style="border-left: 4px solid ${type === 'error' ? 'var(--danger)' : 'var(--primary)'}">
            <div style="font-weight:bold; font-size:13px;">${escapeHtml(title)}</div>
            <div style="font-size:12px; margin-top:4px; color:var(--secondary);">${escapeHtml(message)}</div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
    setTimeout(() => {
        const el = document.getElementById(`toast_${id}`);
        if (el) el.remove();
    }, 4000);
}

function customAlert(message) {
    return new Promise(resolve => {
        const m = document.getElementById('genericModal');
        if (!m) {
            window.alert(message);
            resolve();
            return;
        }
        document.getElementById('genModalTitle').innerText = 'Уведомление';
        document.getElementById('genModalBody').innerHTML = `<p>${nl2brSafe(message)}</p>`;
        document.getElementById('genModalFooter').innerHTML = `<button class="btn-primary" id="genOk">Понятно</button>`;
        m.style.display = 'flex';
        document.getElementById('genOk').onclick = () => {
            m.style.display = 'none';
            resolve();
        };
    });
}

function customConfirm(message) {
    return new Promise(resolve => {
        const m = document.getElementById('genericModal');
        if (!m) {
            resolve(window.confirm(message));
            return;
        }
        document.getElementById('genModalTitle').innerText = 'Подтверждение';
        document.getElementById('genModalBody').innerHTML = `<p>${nl2brSafe(message)}</p>`;
        document.getElementById('genModalFooter').innerHTML = `
            <button class="btn-secondary" id="genCancel">Отмена</button>
            <button class="btn-danger" id="genConfirm">Да, выполнить</button>
        `;
        m.style.display = 'flex';
        document.getElementById('genCancel').onclick = () => {
            m.style.display = 'none';
            resolve(false);
        };
        document.getElementById('genConfirm').onclick = () => {
            m.style.display = 'none';
            resolve(true);
        };
    });
}

function customPrompt(message, defaultValue = '') {
    return new Promise(resolve => {
        const m = document.getElementById('genericModal');
        if (!m) {
            resolve(window.prompt(message, defaultValue));
            return;
        }
        document.getElementById('genModalTitle').innerText = 'Ввод данных';
        document.getElementById('genModalBody').innerHTML = `
            <label style="font-size:13px; margin-bottom:8px; display:block;">${nl2brSafe(message)}</label>
            <input type="text" id="genInput" class="auth-input" value="${escapeHtml(defaultValue)}" style="margin:0;">
        `;
        document.getElementById('genModalFooter').innerHTML = `
            <button class="btn-secondary" id="genCancel">Отмена</button>
            <button class="btn-primary" id="genSubmit">Продолжить</button>
        `;
        m.style.display = 'flex';
        const input = document.getElementById('genInput');
        input.focus();
        input.onkeypress = (e) => {
            if (e.key === 'Enter') document.getElementById('genSubmit').click();
        };
        document.getElementById('genCancel').onclick = () => {
            m.style.display = 'none';
            resolve(null);
        };
        document.getElementById('genSubmit').onclick = () => {
            m.style.display = 'none';
            resolve(input.value);
        };
    });
}

function entityCardBadge(status) {
    const raw = String(status || '').toLowerCase();
    if (['green', 'success', 'synced', 'paid', 'done', 'completed', 'signed', 'posted'].includes(raw)) return 'status-completed';
    if (['red', 'failed', 'error', 'overdue', 'rejected', 'blocked'].includes(raw)) return 'status-overdue';
    return 'status-active';
}

function entityCardTime(ts) {
    const value = Number(ts || 0);
    return value ? new Date(value * 1000).toLocaleString('ru-RU') : '';
}

function renderEntityCardList(items, emptyText, renderer) {
    if (!Array.isArray(items) || !items.length) return `<div class="empty-state" style="text-align:left;">${escapeHtml(emptyText)}</div>`;
    return `<div class="audit-log-list">${items.map(renderer).join('')}</div>`;
}

async function openEntityCard(entityType, entityId) {
    const m = document.getElementById('genericModal');
    if (!m) return;
    document.getElementById('genModalTitle').innerText = 'Карточка объекта';
    document.getElementById('genModalBody').innerHTML = '<div class="empty-state">Загружаю карточку...</div>';
    document.getElementById('genModalFooter').innerHTML = '<button class="btn-secondary" id="genClose">Закрыть</button>';
    document.getElementById('genClose').onclick = () => { m.style.display = 'none'; };
    m.style.display = 'flex';
    const card = await apiCall(`/entity_cards/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`);
    if (!card || card.error) {
        document.getElementById('genModalBody').innerHTML = `<div class="empty-state">${escapeHtml(card?.message || card?.error || 'Карточка не найдена')}</div>`;
        return;
    }
    const integration = card.integration || {};
    const record = card.record || {};
    const favorite = card.favorite || {};
    const watch = card.watch || {};
    document.getElementById('genModalTitle').innerText = card.title || `Объект #${card.entity_id}`;
    document.getElementById('genModalBody').innerHTML = `
        <div class="metrics-grid" style="margin-bottom:14px;">
            <div class="metric-card"><div class="metric-title">Статус</div><div class="metric-value" style="font-size:22px;">${escapeHtml(card.state || '—')}</div></div>
            <div class="metric-card"><div class="metric-title">1C / обмен</div><div class="metric-value" style="font-size:22px;">${escapeHtml(integration.state || 'draft')}</div></div>
            <div class="metric-card"><div class="metric-title">Избранное</div><div class="metric-value" style="font-size:22px;">${favorite.id ? 'Да' : 'Нет'}</div></div>
            <div class="metric-card"><div class="metric-title">Наблюдение</div><div class="metric-value" style="font-size:22px;">${watch.id ? 'Да' : 'Нет'}</div></div>
        </div>
        <div class="system-ops-grid">
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title" style="font-size:16px;">Сводка</h4>
                <div class="client360-list" style="margin-top:12px;">
                    <div class="client360-item"><div><div class="client360-item-title">${escapeHtml(card.entity_type)} #${escapeHtml(card.entity_id)}</div><div class="client360-item-meta">${escapeHtml(card.module || '')}</div></div><span class="status-badge ${entityCardBadge(card.state)}">${escapeHtml(card.state || '—')}</span></div>
                    <div class="client360-item"><div><div class="client360-item-title">Внешний ID</div><div class="client360-item-meta">${escapeHtml(integration.external_id || 'не присвоен')}</div></div><span class="status-badge ${entityCardBadge(integration.state)}">${escapeHtml(integration.state || 'draft')}</span></div>
                    ${integration.last_error ? `<div class="client360-item"><div><div class="client360-item-title">Ошибка обмена</div><div class="client360-item-meta">${escapeHtml(integration.last_error)}</div></div><span class="status-badge status-overdue">Ошибка</span></div>` : ''}
                </div>
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title" style="font-size:16px;">Комментарии</h4>
                ${renderEntityCardList(card.comments, 'Комментариев в карточке пока нет.', item => `
                    <div class="audit-log-item"><div class="audit-log-main"><div class="audit-log-title">${escapeHtml(item.text || '')}</div><div class="audit-log-meta">${escapeHtml(item.source || '')}</div></div><div class="audit-log-time">${entityCardTime(item.created_at)}</div></div>
                `)}
            </div>
        </div>
        <div class="system-ops-grid" style="margin-top:14px;">
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title" style="font-size:16px;">Файлы и документы</h4>
                ${renderEntityCardList(card.documents, 'Связанных документов пока нет.', item => `
                    <div class="audit-log-item"><div class="audit-log-main"><div class="audit-log-title">${escapeHtml(item.number || `Документ #${item.id}`)}</div><div class="audit-log-meta">${escapeHtml(item.subject || item.correspondent || '')}</div></div><span class="status-badge ${entityCardBadge(item.status)}">${escapeHtml(item.status || '')}</span></div>
                `)}
            </div>
            <div class="surface-card surface-card--soft surface-card--padded">
                <h4 class="section-title" style="font-size:16px;">Связи</h4>
                ${renderEntityCardList(card.links, 'Связей с процессами пока нет.', item => `
                    <div class="audit-log-item"><div class="audit-log-main"><div class="audit-log-title">${escapeHtml(item.source_type)} #${escapeHtml(item.source_id)} → ${escapeHtml(item.target_type)} #${escapeHtml(item.target_id)}</div><div class="audit-log-meta">${escapeHtml(item.relation_type || 'related')}</div></div><div class="audit-log-time">${entityCardTime(item.created_at)}</div></div>
                `)}
            </div>
        </div>
        <div class="surface-card surface-card--soft surface-card--padded" style="margin-top:14px;">
            <h4 class="section-title" style="font-size:16px;">История</h4>
            ${renderEntityCardList(card.audit, 'Истории изменений пока нет.', item => `
                <div class="audit-log-item"><div class="audit-log-main"><div class="audit-log-title">${escapeHtml(item.action || 'Событие')}</div><div class="audit-log-meta">${escapeHtml(item.actor_name || item.actor_email || '')}</div></div><div class="audit-log-time">${entityCardTime(item.created_at)}</div></div>
            `)}
        </div>
    `;
    document.getElementById('genModalFooter').innerHTML = `
        ${record.project_id ? `<button class="btn-secondary" onclick="if(typeof openProject === 'function') openProject(${Number(record.project_id)})">Открыть проект</button>` : ''}
        <button class="btn-secondary" id="genClose">Закрыть</button>
    `;
    document.getElementById('genClose').onclick = () => { m.style.display = 'none'; };
}

window.openEntityCard = openEntityCard;

const formDraftRegistry = {};
const formDraftServerTimers = {};

function formDraftUserKey(key) {
    const email = currentUser?.email || 'anonymous';
    return `korda_form_draft_${email}_${key}`;
}

function formDraftUpdatedAtMs(draft) {
    const value = Number(draft?.updated_at || 0);
    if (!value) return 0;
    return value < 10000000000 ? value * 1000 : value;
}

function formDraftFieldValue(el) {
    if (!el) return '';
    if (el.type === 'checkbox') return !!el.checked;
    return el.value ?? '';
}

function setFormDraftFieldValue(el, value) {
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!value;
    else el.value = value ?? '';
}

function formDraftCollect(fieldIds) {
    const values = {};
    (fieldIds || []).forEach(id => {
        const el = document.getElementById(id);
        if (el) values[id] = formDraftFieldValue(el);
    });
    return values;
}

function formDraftHasContent(values) {
    return Object.values(values || {}).some(value => {
        if (typeof value === 'boolean') return value;
        return String(value ?? '').trim() !== '';
    });
}

function renderFormDraftHint(key, message = '') {
    const config = formDraftRegistry[key];
    if (!config || !config.formId) return;
    const form = document.getElementById(config.formId);
    if (!form) return;
    const hintId = `formDraftHint_${key}`;
    let hint = document.getElementById(hintId);
    if (!hint) {
        hint = document.createElement('div');
        hint.id = hintId;
        hint.className = 'form-draft-hint';
        form.parentElement?.insertBefore(hint, form);
    }
    const saved = readFormDraft(key);
    const timeMs = formDraftUpdatedAtMs(saved);
    const timeLabel = timeMs ? new Date(timeMs).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '';
    hint.innerHTML = `
        <span>${escapeHtml(message || (saved ? `Автосохранено в браузере и на сервере${timeLabel ? ` в ${timeLabel}` : ''}` : 'Автосохранение включено: браузер + сервер'))}</span>
        ${saved ? `<button type="button" class="btn-secondary btn-xs" onclick="clearFormDraft('${escapeHtml(key)}', true)">Очистить</button>` : ''}
    `;
}

function readFormDraft(key) {
    try {
        const raw = localStorage.getItem(formDraftUserKey(key));
        return raw ? JSON.parse(raw) : null;
    } catch (error) {
        return null;
    }
}

function saveFormDraft(key) {
    const config = formDraftRegistry[key];
    if (!config || (typeof config.shouldSave === 'function' && !config.shouldSave())) return;
    const values = formDraftCollect(config.fieldIds);
    if (!formDraftHasContent(values)) {
        localStorage.removeItem(formDraftUserKey(key));
        deleteServerFormDraft(key);
        renderFormDraftHint(key, 'Автосохранение включено');
        return;
    }
    const draft = { values, updated_at: Date.now() };
    localStorage.setItem(formDraftUserKey(key), JSON.stringify(draft));
    scheduleServerFormDraftSave(key, draft);
    renderFormDraftHint(key);
}

function restoreFormDraft(key) {
    const config = formDraftRegistry[key];
    if (!config || (typeof config.shouldRestore === 'function' && !config.shouldRestore())) return false;
    const draft = readFormDraft(key);
    if (!draft || !draft.values) {
        renderFormDraftHint(key, 'Автосохранение включено');
        return false;
    }
    Object.entries(draft.values).forEach(([id, value]) => setFormDraftFieldValue(document.getElementById(id), value));
    if (typeof config.afterRestore === 'function') config.afterRestore(draft.values);
    renderFormDraftHint(key, 'Восстановлен незавершённый ввод');
    return true;
}

function formDraftServerPayload(key, draft) {
    const config = formDraftRegistry[key] || {};
    return {
        draft_key: key,
        entity_type: config.entityType || key,
        entity_id: config.entityId || '',
        title: config.title || config.formTitle || key,
        source_view: config.sourceView || (typeof currentView !== 'undefined' ? currentView : ''),
        payload: {
            values: draft?.values || {},
            client_updated_at: formDraftUpdatedAtMs(draft) || Date.now(),
        },
    };
}

function scheduleServerFormDraftSave(key, draft) {
    if (!key || typeof apiCall !== 'function' || !currentUser?.email) return;
    clearTimeout(formDraftServerTimers[key]);
    formDraftServerTimers[key] = setTimeout(async () => {
        const result = await apiCall('/workbench/form_drafts', 'POST', formDraftServerPayload(key, draft));
        if (result?.error) {
            renderFormDraftHint(key, 'Сохранено в браузере. Серверный черновик пока недоступен');
            return;
        }
        renderFormDraftHint(key);
    }, 800);
}

async function deleteServerFormDraft(key) {
    if (!key || typeof apiCall !== 'function' || !currentUser?.email) return;
    clearTimeout(formDraftServerTimers[key]);
    try {
        await apiCall(`/workbench/form_drafts/${encodeURIComponent(key)}`, 'DELETE');
    } catch (error) {
        console.warn('Failed to clear server draft', error);
    }
}

async function restoreServerFormDraft(key) {
    const config = formDraftRegistry[key];
    if (!config || typeof apiCall !== 'function' || !currentUser?.email) return false;
    if (typeof config.shouldRestore === 'function' && !config.shouldRestore()) return false;
    const result = await apiCall(`/workbench/form_drafts/${encodeURIComponent(key)}`);
    if (result?.error || !result?.draft) return false;
    const serverPayload = result.draft.payload || {};
    const values = serverPayload.values || {};
    if (!formDraftHasContent(values)) return false;
    const serverDraft = {
        values,
        updated_at: Number(result.draft.updated_at || 0) * 1000 || Number(serverPayload.client_updated_at || 0) || Date.now(),
    };
    const localDraft = readFormDraft(key);
    if (localDraft && formDraftUpdatedAtMs(localDraft) > formDraftUpdatedAtMs(serverDraft)) return false;
    localStorage.setItem(formDraftUserKey(key), JSON.stringify(serverDraft));
    return restoreFormDraft(key);
}

window.bindFormDraftAutosave = function(key, config = {}) {
    if (!key || !config.formId || !Array.isArray(config.fieldIds)) return;
    formDraftRegistry[key] = { ...config };
    const form = document.getElementById(config.formId);
    if (!form) return;
    if (typeof bindUnifiedFieldValidation === 'function') bindUnifiedFieldValidation(form);
    config.fieldIds.forEach(id => {
        const el = document.getElementById(id);
        if (!el || el.dataset.formDraftBound === key) return;
        el.dataset.formDraftBound = key;
        const handler = () => saveFormDraft(key);
        el.addEventListener('input', handler);
        el.addEventListener('change', handler);
    });
    restoreFormDraft(key);
    restoreServerFormDraft(key).catch(error => console.warn('Failed to restore server draft', error));
};

window.clearFormDraft = function(key, notify = false) {
    if (!key) return;
    localStorage.removeItem(formDraftUserKey(key));
    deleteServerFormDraft(key);
    renderFormDraftHint(key, notify ? 'Сохранённый ввод очищен' : 'Автосохранение включено');
};

let omniSearchSeq = 0;
let commandPaletteResults = [];
let commandPaletteSelectedIndex = 0;
let commandPaletteSeq = 0;

function isMacShortcutPlatform() {
    if (typeof resolveWorkspaceShortcutPlatform === 'function') {
        const config = typeof loadWorkspaceConfig === 'function' ? loadWorkspaceConfig() : {};
        return resolveWorkspaceShortcutPlatform(config?.platformPreference) === 'mac';
    }
    return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || '');
}

function currentShortcutPlatform() {
    return isMacShortcutPlatform() ? 'mac' : 'windows';
}

function getShortcutConfig(actionKey) {
    if (typeof getWorkspaceShortcutConfig === 'function') {
        return getWorkspaceShortcutConfig(actionKey);
    }
    return actionKey === 'globalSearch'
        ? { ctrl: !isMacShortcutPlatform(), meta: isMacShortcutPlatform(), alt: false, shift: true, key: 'f' }
        : { ctrl: !isMacShortcutPlatform(), meta: isMacShortcutPlatform(), alt: false, shift: false, key: 'k' };
}

function shortcutLabel(actionKey) {
    const shortcut = getShortcutConfig(actionKey);
    if (typeof formatWorkspaceShortcutLabel === 'function') {
        return formatWorkspaceShortcutLabel(shortcut, currentShortcutPlatform());
    }
    return `${shortcut.ctrl ? 'Ctrl + ' : shortcut.meta ? '⌘ + ' : ''}${String(shortcut.key || '').toUpperCase()}`;
}

function shortcutLabelBadges(actionKey) {
    const shortcut = getShortcutConfig(actionKey);
    const parts = typeof shortcutLabelParts === 'function'
        ? shortcutLabelParts(shortcut, currentShortcutPlatform())
        : shortcutLabel(actionKey).split(' + ');
    return parts.map(key => `<span class="command-palette-kbd">${escapeHtml(key)}</span>`).join('');
}

function searchQueryVariants(query) {
    const raw = String(query || '').trim().toLowerCase();
    if (!raw) return [];
    const variants = new Set([raw]);
    const latinToCyr = {
        q: 'й', w: 'ц', e: 'у', r: 'к', t: 'е', y: 'н', u: 'г', i: 'ш', o: 'щ', p: 'з',
        '[': 'х', ']': 'ъ', a: 'ф', s: 'ы', d: 'в', f: 'а', g: 'п', h: 'р', j: 'о', k: 'л',
        l: 'д', ';': 'ж', "'": 'э', z: 'я', x: 'ч', c: 'с', v: 'м', b: 'и', n: 'т', m: 'ь',
        ',': 'б', '.': 'ю', '`': 'ё',
    };
    const cyrToLatin = Object.fromEntries(Object.entries(latinToCyr).map(([latin, cyr]) => [cyr, latin]));
    const convert = (text, map) => text.split('').map(ch => map[ch] || ch).join('');
    variants.add(convert(raw, latinToCyr));
    variants.add(convert(raw, cyrToLatin));
    return Array.from(variants).filter(Boolean);
}

function matchesSearchNeedle(values, query) {
    const variants = searchQueryVariants(query);
    if (!variants.length) return false;
    const haystack = (Array.isArray(values) ? values : [values])
        .map(value => String(value || '').toLowerCase())
        .join(' ');
    return variants.some(needle => haystack.includes(needle));
}

function setFloatingPanelVisibility(element, isVisible, displayMode = 'block') {
    if (!element) return;
    element.classList.toggle('krd-is-hidden', !isVisible);
    element.style.display = isVisible ? displayMode : 'none';
}

function keyboardEventMatchesShortcut(event, shortcut) {
    const normalizedKey = String(event.key || '').toLowerCase();
    const targetKey = String(shortcut?.key || '').toLowerCase();
    return Boolean(targetKey)
        && normalizedKey === targetKey
        && Boolean(event.ctrlKey) === Boolean(shortcut?.ctrl)
        && Boolean(event.metaKey) === Boolean(shortcut?.meta)
        && Boolean(event.altKey) === Boolean(shortcut?.alt)
        && Boolean(event.shiftKey) === Boolean(shortcut?.shift);
}

function focusGlobalSearchInput(selectText = true) {
    const input = document.getElementById('searchInput');
    if (!input) return;
    input.focus();
    if (selectText) input.select();
}

function updateCommandPaletteShortcutHints() {
    const hint = document.getElementById('commandPaletteHint');
    const paletteLabel = shortcutLabel('commandPalette');
    const searchLabel = shortcutLabel('globalSearch');
    if (hint) {
        hint.innerText = paletteLabel;
        hint.title = `Командная палитра (${paletteLabel})`;
    }
    const shortcut = document.getElementById('commandPaletteShortcut');
    if (shortcut) shortcut.innerHTML = shortcutLabelBadges('commandPalette');
    const searchInput = document.getElementById('searchInput');
    if (searchInput) searchInput.title = `Глобальный поиск (${searchLabel})`;
}

function navigationSearchCatalog() {
    const descriptions = {
        navDashboard: 'Портфель проектов и стартовый экран',
        navApprovals: 'Маршруты согласования и визы',
        navTasks: 'Поручения, сроки и контроль',
        navExecutive: 'Панель директора и сводные риски',
        navClients: 'База клиентов и карточки контрагентов',
        navProspecting: 'База развития и обработка клиентского пула',
        navLeads: 'Лиды и первичная воронка',
        navDeals: 'Сделки и коммерческий контур',
        navClient360: 'Контрагент 360 и клиентское досье',
        navContract360: 'Договоры 360 и карточки договоров',
        navSales: 'Счета, акты и реализация',
        navClaims: 'Претензии и суды',
        navDocuments: 'Канцелярия, реестры и СЭД',
        navEmails: 'Почта, входящие и исходящие письма',
        navMeetings: 'Совещания и календарь встреч',
        navMessenger: 'Чаты компании и проектные каналы',
        navKnowledge: 'База знаний и регламенты',
        navFinance: 'Платежи, дебиторка и финансовый календарь',
        navAccounting: 'Учёт, ЭПЛ и обмен с 1С',
        navExpenses: 'Затраты и бюджетные отклонения',
        navSupply: 'Склад, закупки и резервы',
        navProduction: 'Производственные заказы и исполнение',
        navOperations: 'Операционный центр и сводный контроль',
        navService: 'Сервис и гарантийные обращения',
        navResources: 'Ресурсы, загрузка и календари',
        navNomenclature: 'НСИ, складские позиции и остатки',
        navContacts: 'Контакты и контактные лица',
        navAnalytics: 'Аналитика и показатели',
        navKpi: 'KPI и эффективность',
        navProfile: 'Личный кабинет и настройки',
    };
    const keywords = {
        navDashboard: 'главная проекты портфель рабочий стол',
        navProspecting: 'база развития prospecting обзвон клиенты',
        navLeads: 'лиды входящие запросы crm',
        navDeals: 'сделки продажи pipeline коммерция',
        navClient360: 'контрагент 360 досье клиент',
        navContract360: 'договор договоры 360 реестр номер договора',
        navDocuments: 'канцелярия документы входящие исходящие письма реестр',
        navEmails: 'почта email imap smtp входящие исходящие',
        navFinance: 'финансы оплаты дебиторка платежи ддс',
        navAccounting: 'учет 1с интеграции эпл путевые листы',
        navSupply: 'склад закупки снабжение резервы',
        navProduction: 'производство цех заказ исполнение',
        navOperations: 'операционный центр контроль',
        navResources: 'ресурсы календарь загрузка',
        navProfile: 'профиль личный кабинет настройки горячие клавиши',
    };
    const viewById = {
        navDashboard: 'dashboard',
        navApprovals: 'approvals',
        navTasks: 'tasks',
        navExecutive: 'executive',
        navClients: 'clients',
        navProspecting: 'prospecting',
        navLeads: 'leads',
        navDeals: 'deals',
        navClient360: 'client360',
        navContract360: 'contract360',
        navSales: 'sales',
        navClaims: 'claims',
        navDocuments: 'documents',
        navEmails: 'emails',
        navMeetings: 'meetings',
        navMessenger: 'messenger',
        navKnowledge: 'knowledge',
        navFinance: 'finance',
        navAccounting: 'accounting',
        navExpenses: 'expenses',
        navSupply: 'supply',
        navProduction: 'production',
        navOperations: 'operations',
        navService: 'service',
        navResources: 'resources',
        navNomenclature: 'nomenclature',
        navContacts: 'contacts',
        navAnalytics: 'analytics',
        navKpi: 'kpi',
        navProfile: 'profile',
    };
    return Array.from(document.querySelectorAll('.nav-item[id]'))
        .map(item => {
            const id = String(item.id || '').trim();
            const title = String(item.textContent || '').replace(/\s+/g, ' ').trim();
            const view = viewById[id] || '';
            if (!id || !title || !view || item.style.display === 'none') return null;
            return {
                type: 'Раздел',
                icon: 'NAV',
                title,
                desc: descriptions[id] || 'Раздел системы',
                keywords: keywords[id] || '',
                view,
                action: () => { if (typeof navigateTo === 'function') navigateTo(view); },
            };
        })
        .filter(Boolean);
}

function sectionSearchMatches(query) {
    const q = String(query || '').toLowerCase().trim();
    if (!q) return [];
    return navigationSearchCatalog().filter(item => matchesSearchNeedle([item.title, item.desc, item.keywords, item.view], q));
}

function openSearchSection(view) {
    closeOmniSearchResults();
    if (typeof navigateTo === 'function') navigateTo(view);
}

function closeCommandPalette() {
    const overlay = document.getElementById('commandPaletteOverlay');
    if (overlay) overlay.style.display = 'none';
}

function commandPaletteRunSafely(action) {
    closeCommandPalette();
    closeOmniSearchResults();
    const result = action();
    if (result && typeof result.then === 'function') {
        result.catch(error => {
            console.error('Command palette action failed', error);
            if (typeof showToast === 'function') showToast('Команда', 'Не удалось выполнить действие', 'error');
        });
    }
}

function navigateAndRun(view, action, delay = 120) {
    if (typeof navigateTo !== 'function') return;
    navigateTo(view);
    window.setTimeout(() => {
        if (typeof action === 'function') action();
    }, delay);
}

function commandCreateDocument(preset = {}) {
    navigateAndRun('documents', () => {
        if (typeof openDocumentModalWithPreset === 'function') openDocumentModalWithPreset(preset);
        else if (typeof focusFieldById === 'function') focusFieldById('docCorrespondent');
    });
}

function commandCreateFinance(kind = 'outgoing') {
    navigateAndRun('finance', () => {
        if (typeof presetFinanceFlow === 'function') presetFinanceFlow(kind);
    }, 180);
}

function commandCreateTask() {
    navigateAndRun('tasks', () => {
        if (typeof openCreateTaskModal === 'function') openCreateTaskModal({ executor: currentUser ? currentUser.name : '' });
    }, 140);
}

function commandCreatePurchase() {
    navigateAndRun('supply', () => {
        if (typeof presetSupplyMode === 'function') presetSupplyMode('purchase');
    }, 180);
}

function commandCreateSalesDoc(type = 'invoice') {
    navigateAndRun('sales', () => {
        if (typeof presetSalesDocument === 'function') presetSalesDocument(type);
    }, 180);
}

function commandCreateProductionOrder() {
    navigateAndRun('production', () => {
        if (typeof presetProductionFlow === 'function') presetProductionFlow('order');
    }, 180);
}

function commandPaletteStaticCommands() {
    return [
        { group: 'Создать', icon: 'PRJ', title: 'Создать проект', desc: 'Новый проект в портфеле', keywords: 'проект создать new project', action: () => { if (typeof createNewProject === 'function') createNewProject(); } },
        { group: 'Создать', icon: 'DOC', title: 'Создать документ', desc: 'Открыть карточку регистрации документа', keywords: 'документ сед входящий исходящий приказ scan', action: () => commandCreateDocument({}) },
        { group: 'Создать', icon: 'IN', title: 'Входящий документ', desc: 'Зарегистрировать входящее письмо или скан', keywords: 'входящий документ письмо скан', action: () => commandCreateDocument({ type: 'incoming' }) },
        { group: 'Создать', icon: 'OUT', title: 'Исходящий документ', desc: 'Зарегистрировать исходящий документ', keywords: 'исходящий документ', action: () => commandCreateDocument({ type: 'outgoing' }) },
        { group: 'Создать', icon: 'TSK', title: 'Поставить задачу', desc: 'Создать поручение с исполнителем и сроком', keywords: 'задача поручение task todo поставить', action: commandCreateTask },
        { group: 'Создать', icon: 'PAY', title: 'Новая оплата', desc: 'Создать исходящий платёж в финансах', keywords: 'платеж оплата финансы расход исходящий', action: () => commandCreateFinance('outgoing') },
        { group: 'Создать', icon: 'CASH', title: 'Новое поступление', desc: 'Создать входящий денежный поток', keywords: 'поступление финансы входящий дебиторка', action: () => commandCreateFinance('incoming') },
        { group: 'Создать', icon: 'BUY', title: 'Новая закупка', desc: 'Открыть форму закупки в снабжении', keywords: 'закупка поставка снабжение склад purchase', action: commandCreatePurchase },
        { group: 'Создать', icon: 'INV', title: 'Новый счёт клиенту', desc: 'Создать документ реализации', keywords: 'счет продажи реализация клиент invoice', action: () => commandCreateSalesDoc('invoice') },
        { group: 'Создать', icon: 'MFG', title: 'Производственный заказ', desc: 'Открыть форму нового заказа производства', keywords: 'производство заказ цех очередь', action: commandCreateProductionOrder },
        { group: 'Перейти', icon: 'HOME', title: 'Открыть дашборд', desc: 'Портфель и рабочий день', keywords: 'главная dashboard портфель', action: () => { if (typeof navigateTo === 'function') navigateTo('dashboard'); } },
        { group: 'Перейти', icon: 'PIPE', title: 'Открыть базу развития', desc: 'Обзвон, прогрев и клиентский пул', keywords: 'база развития prospecting обзвон клиенты', action: () => { if (typeof navigateTo === 'function') navigateTo('prospecting'); } },
        { group: 'Перейти', icon: 'LEAD', title: 'Открыть лиды', desc: 'Новые запросы и первичная воронка', keywords: 'лиды входящие crm', action: () => { if (typeof navigateTo === 'function') navigateTo('leads'); } },
        { group: 'Перейти', icon: 'DEAL', title: 'Открыть сделки', desc: 'Коммерческий pipeline и переговоры', keywords: 'сделки продажи crm', action: () => { if (typeof navigateTo === 'function') navigateTo('deals'); } },
        { group: 'Перейти', icon: 'DOC', title: 'Открыть документы', desc: 'Канцелярия и СЭД', keywords: 'документы сед сканы', action: () => { if (typeof navigateTo === 'function') navigateTo('documents'); } },
        { group: 'Перейти', icon: 'INT', title: 'Открыть интеграции', desc: 'Перенос из 1С и контроль обмена', keywords: 'интеграции 1с обмен перенос документы оплаты', action: () => { if (typeof navigateTo === 'function') navigateTo('integrations'); } },
        { group: 'Перейти', icon: 'TSK', title: 'Открыть задачи', desc: 'Поручения и контроль сроков', keywords: 'задачи поручения tasks', action: () => { if (typeof navigateTo === 'function') navigateTo('tasks'); } },
        { group: 'Перейти', icon: 'FIN', title: 'Открыть финансы', desc: 'Платёжный календарь и дебиторка', keywords: 'финансы платежи оплаты деньги', action: () => { if (typeof navigateTo === 'function') navigateTo('finance'); } },
        { group: 'Перейти', icon: 'CLN', title: 'Открыть клиентов', desc: 'Контрагенты и клиентские досье', keywords: 'клиенты контрагенты crm', action: () => { if (typeof navigateTo === 'function') navigateTo('clients'); } },
        { group: 'Перейти', icon: 'CTR', title: 'Открыть договоры 360', desc: 'Реестр и карточки договоров', keywords: 'договоры 360 реестр contract', action: () => { if (typeof navigateTo === 'function') navigateTo('contract360'); } },
        { group: 'Перейти', icon: 'BUY', title: 'Открыть склад и закупки', desc: 'Резервы, поставки, снабжение', keywords: 'склад закупки снабжение поставки', action: () => { if (typeof navigateTo === 'function') navigateTo('supply'); } },
        { group: 'Перейти', icon: 'INV', title: 'Открыть продажи', desc: 'Счета, акты, реализация', keywords: 'продажи счета акты реализация', action: () => { if (typeof navigateTo === 'function') navigateTo('sales'); } },
        { group: 'Перейти', icon: 'MFG', title: 'Открыть производство', desc: 'Очередь и операции цеха', keywords: 'производство цех заказы', action: () => { if (typeof navigateTo === 'function') navigateTo('production'); } },
        { group: 'Перейти', icon: 'MAIL', title: 'Открыть почту', desc: 'Входящие, исходящие и обработка писем', keywords: 'почта письма email', action: () => { if (typeof navigateTo === 'function') navigateTo('emails'); } },
        { group: 'Перейти', icon: 'EPL', title: 'Открыть ЭПЛ', desc: 'Путевые листы и интеграция 1С', keywords: 'эпл путевой лист accounting', action: () => { if (typeof navigateTo === 'function') navigateTo('accounting'); } },
    ];
}

function quickSearchActionCatalog() {
    return commandPaletteStaticCommands().map(item => ({
        type: 'Команда',
        title: item.title,
        desc: item.desc,
        icon: item.icon,
        chip: item.group,
        action: item.action,
    }));
}

function runQuickSearchCommand(index) {
    const item = quickSearchActionCatalog()[Number(index || 0)];
    if (item && typeof item.action === 'function') commandPaletteRunSafely(item.action);
}

function commandPaletteEntityCommands(query) {
    const q = String(query || '').toLowerCase().trim();
    if (!q) return [];
    const matches = (values) => matchesSearchNeedle(values, q);
    const rows = [];
    const projectRows = typeof projectsDB !== 'undefined' && Array.isArray(projectsDB) ? projectsDB : [];
    projectRows.forEach(item => {
        if (matches([item.name, item.contract, item.client])) rows.push({ group: 'Найдено', icon: 'PR', title: item.name || item.contract || `Проект #${item.id}`, desc: item.contract || item.client || 'Проект', chip: 'Проект', action: () => openProject(Number(item.id || 0)) });
    });
    const clientRows = typeof clientsDB !== 'undefined' && Array.isArray(clientsDB) ? clientsDB : [];
    clientRows.forEach(item => {
        if (matches([item.name, item.inn, item.contact])) rows.push({ group: 'Найдено', icon: 'CL', title: item.name || `Клиент #${item.id}`, desc: item.inn || item.contact || 'Контрагент', chip: 'Клиент', action: () => openOmniSearchResult('client', Number(item.id || 0), 'clients') });
    });
    const documentRows = typeof documentsDB !== 'undefined' && Array.isArray(documentsDB) ? documentsDB : [];
    documentRows.forEach(item => {
        if (matches([item.number, item.subject, item.correspondent])) rows.push({ group: 'Найдено', icon: 'DOC', title: item.number || `Документ #${item.id}`, desc: item.subject || item.correspondent || 'Документ', chip: 'Документ', action: () => openOmniSearchResult('document', Number(item.id || 0), 'documents') });
    });
    const taskRows = typeof tasksDB !== 'undefined' && Array.isArray(tasksDB) ? tasksDB : [];
    taskRows.forEach(item => {
        if (matches([item.title, item.executor, item.description])) rows.push({ group: 'Найдено', icon: 'TSK', title: item.title || `Задача #${item.id}`, desc: item.executor || item.deadline || 'Поручение', chip: 'Задача', action: () => openOmniSearchResult('task', Number(item.id || 0), 'tasks') });
    });
    const leadRows = typeof crmLeadsDB !== 'undefined' && Array.isArray(crmLeadsDB) ? crmLeadsDB : [];
    leadRows.forEach(item => {
        if (matches([item.title, item.client_name, item.contact_name, item.contact_email, item.contact_phone, item.next_action])) rows.push({ group: 'Найдено', icon: 'LEAD', title: item.title || `Лид #${item.id}`, desc: item.client_name || item.contact_name || item.source || 'Лид', chip: 'Лид', action: () => openOmniSearchResult('lead', Number(item.id || 0), 'leads') });
    });
    const dealRows = typeof crmDealsDB !== 'undefined' && Array.isArray(crmDealsDB) ? crmDealsDB : [];
    dealRows.forEach(item => {
        if (matches([item.title, item.client_name, item.contract_number, item.next_action, item.responsible])) rows.push({ group: 'Найдено', icon: 'DEAL', title: item.title || `Сделка #${item.id}`, desc: item.contract_number || item.client_name || item.next_action || 'Сделка', chip: 'Сделка', action: () => openOmniSearchResult('deal', Number(item.id || 0), 'deals') });
    });
    const financeRows = typeof financePaymentsDB !== 'undefined' && Array.isArray(financePaymentsDB) ? financePaymentsDB : [];
    if (financeRows.length) {
        financeRows.forEach(item => {
            if (matches([item.title, item.client_name, item.project_name, item.project_contract, item.comment])) rows.push({ group: 'Найдено', icon: 'FIN', title: item.title || `Платёж #${item.id}`, desc: `${item.client_name || item.project_name || 'Финансы'} · ${item.amount || ''}`, chip: 'Оплата', action: () => openOmniSearchResult('finance_payment', Number(item.id || 0), 'finance') });
        });
    }
    const purchaseRows = typeof purchasesDB !== 'undefined' && Array.isArray(purchasesDB) ? purchasesDB : [];
    purchaseRows.forEach(item => {
        if (matches([item.item_name, item.item_article, item.supplier, item.project_name, item.client_name])) rows.push({ group: 'Найдено', icon: 'PUR', title: item.item_name || `Закупка #${item.id}`, desc: item.supplier || item.expected_date || 'Закупка', chip: 'Закупка', action: () => openOmniSearchResult('purchase_order', Number(item.id || 0), 'supply') });
    });
    const productionRows = typeof productionOrdersDB !== 'undefined' && Array.isArray(productionOrdersDB) ? productionOrdersDB : [];
    productionRows.forEach(item => {
        if (matches([item.order_name, item.responsible, item.project_name, item.client_name, item.route_name])) rows.push({ group: 'Найдено', icon: 'MFG', title: item.order_name || `Производственный заказ #${item.id}`, desc: item.responsible || item.stage || 'Производство', chip: 'Производство', action: () => openOmniSearchResult('production_order', Number(item.id || 0), 'production') });
    });
    return rows.slice(0, 10);
}

function commandPaletteFilterLocal(query) {
    const q = String(query || '').toLowerCase().trim();
    const commands = commandPaletteStaticCommands().filter(item => {
        if (!q) return true;
        return matchesSearchNeedle([item.title, item.desc, item.group, item.keywords], q);
    });
    const sections = sectionSearchMatches(q).map(item => ({
        group: 'Разделы',
        icon: item.icon,
        title: item.title,
        desc: item.desc,
        chip: 'Раздел',
        action: item.action,
    }));
    return [...commands, ...sections, ...commandPaletteEntityCommands(q)].slice(0, 20);
}

function commandPaletteRender() {
    const list = document.getElementById('commandPaletteList');
    if (!list) return;
    if (!commandPaletteResults.length) {
        list.innerHTML = '<div class="command-palette-empty">Ничего не найдено. Попробуй “документ”, “оплата”, “проект” или “задача”.</div>';
        return;
    }
    let previousGroup = '';
    list.innerHTML = commandPaletteResults.map((item, index) => {
        const section = item.group !== previousGroup ? `<div class="command-palette-section">${escapeHtml(item.group || 'Команды')}</div>` : '';
        previousGroup = item.group;
        return `${section}
            <button class="command-palette-item ${index === commandPaletteSelectedIndex ? 'is-active' : ''}" data-command-index="${index}" type="button">
                <span class="command-palette-icon">${escapeHtml(item.icon || 'GO')}</span>
                <span>
                    <span class="command-palette-title">${escapeHtml(item.title)}</span>
                    <span class="command-palette-desc">${escapeHtml(item.desc || '')}</span>
                </span>
                <span class="command-palette-chip">${escapeHtml(item.chip || item.group || '')}</span>
            </button>`;
    }).join('');
}

async function commandPaletteSearch(query) {
    const seq = ++commandPaletteSeq;
    commandPaletteResults = commandPaletteFilterLocal(query);
    commandPaletteSelectedIndex = 0;
    commandPaletteRender();
    const q = String(query || '').trim();
    if (!q || q.length < 2) return;
    try {
        const server = await apiCall(`/search?q=${encodeURIComponent(q)}&limit=8`);
        if (seq !== commandPaletteSeq || !server || !Array.isArray(server.items)) return;
        const existing = new Set(commandPaletteResults.map(item => `${String(item.title).toLowerCase()}:${String(item.chip || item.group).toLowerCase()}`));
        server.items.forEach(item => {
            const entityType = String(item.entity_type || item.type || '').replace(/[^a-zA-Z0-9_]/g, '');
            const entityId = Number(item.entity_id || item.id || 0);
            const title = item.title || `Запись #${entityId}`;
            const key = `${String(title).toLowerCase()}:${String(item.type_label || entityType).toLowerCase()}`;
            if (existing.has(key)) return;
            existing.add(key);
            commandPaletteResults.push({
                group: 'Найдено',
                icon: omniSearchIconFor(item),
                title,
                desc: item.meta || '',
                chip: item.type_label || entityType || 'Запись',
                action: () => openOmniSearchResult(entityType, entityId, String(item.view || '').replace(/[^a-zA-Z0-9_]/g, '')),
            });
        });
        commandPaletteResults = commandPaletteResults.slice(0, 20);
        commandPaletteRender();
    } catch (error) {
        console.warn('Command palette server search unavailable', error);
    }
}

function ensureCommandPalette() {
    if (document.getElementById('commandPaletteOverlay')) return;
    document.body.insertAdjacentHTML('beforeend', `
        <div id="commandPaletteOverlay" class="command-palette-backdrop">
            <div class="command-palette" role="dialog" aria-modal="true" aria-label="Командная палитра">
                <div class="command-palette-header">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--secondary)" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><path d="M21 21l-4.3-4.3"></path></svg>
                    <input id="commandPaletteInput" class="command-palette-input" autocomplete="off" placeholder="Команда или запись: документ, оплата, проект, задача...">
                    <span id="commandPaletteShortcut" class="command-palette-shortcut"></span>
                </div>
                <div id="commandPaletteList" class="command-palette-list"></div>
                <div class="command-palette-footer">
                    <span><span class="command-palette-kbd">↑</span> <span class="command-palette-kbd">↓</span> выбор</span>
                    <span><span class="command-palette-kbd">Enter</span> открыть</span>
                    <span><span class="command-palette-kbd">Esc</span> закрыть</span>
                </div>
            </div>
        </div>
    `);
    const overlay = document.getElementById('commandPaletteOverlay');
    const input = document.getElementById('commandPaletteInput');
    overlay.addEventListener('mousedown', event => {
        if (event.target === overlay) closeCommandPalette();
    });
    document.getElementById('commandPaletteList').addEventListener('click', event => {
        const button = event.target.closest('[data-command-index]');
        if (!button) return;
        const item = commandPaletteResults[Number(button.dataset.commandIndex || 0)];
        if (item && typeof item.action === 'function') commandPaletteRunSafely(item.action);
    });
    input.addEventListener('input', () => commandPaletteSearch(input.value));
    input.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            commandPaletteSelectedIndex = Math.min(commandPaletteSelectedIndex + 1, commandPaletteResults.length - 1);
            commandPaletteRender();
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            commandPaletteSelectedIndex = Math.max(commandPaletteSelectedIndex - 1, 0);
            commandPaletteRender();
        } else if (event.key === 'Enter') {
            event.preventDefault();
            const item = commandPaletteResults[commandPaletteSelectedIndex];
            if (item && typeof item.action === 'function') commandPaletteRunSafely(item.action);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            closeCommandPalette();
        }
    });
    updateCommandPaletteShortcutHints();
}

window.openCommandPalette = function(initialQuery = '') {
    ensureCommandPalette();
    closeOmniSearchResults();
    const overlay = document.getElementById('commandPaletteOverlay');
    const input = document.getElementById('commandPaletteInput');
    overlay.style.display = 'flex';
    input.value = initialQuery || '';
    commandPaletteSearch(input.value);
    window.setTimeout(() => {
        input.focus();
        input.select();
    }, 0);
};

function omniSearchActionFor(item) {
    const type = String(item.entity_type || item.type || '').toLowerCase();
    const id = item.id ?? item.entity_id ?? '';
    if (type === 'project' && id) return `openProject(${Number(id)}); closeOmniSearchResults();`;
    const viewByType = {
        client: 'clients',
        document: 'documents',
        task: 'tasks',
        finance_payment: 'finance',
        finance_request: 'finance',
        finance_obligation: 'finance',
        purchase_order: 'supply',
        procurement_request: 'supply',
        stock_reservation: 'supply',
        inventory_document: 'nomenclature',
        production_order: 'production',
        contract: 'contract360',
        epl_waybill: 'accounting',
        approval: 'approvals',
        email: 'emails',
    };
    const targetView = String(item.view || item.view_name || viewByType[type] || 'dashboard');
    const safeView = /^[a-z0-9_]+$/i.test(targetView) ? targetView : 'dashboard';
    return `navigateTo('${safeView}'); closeOmniSearchResults();`;
}

function omniSearchIconFor(item) {
    const type = String(item.entity_type || item.type || '').toLowerCase();
    if (type === 'project') return 'PR';
    if (type === 'client') return 'CL';
    if (type === 'document') return 'DOC';
    if (type === 'task') return 'TSK';
    if (type === 'lead') return 'LEAD';
    if (type === 'deal') return 'DEAL';
    if (type.startsWith('finance_')) return 'FIN';
    if (type === 'purchase_order' || type === 'procurement_request') return 'PUR';
    if (type === 'stock_reservation' || type === 'inventory_document') return 'STK';
    if (type === 'production_order') return 'MFG';
    if (type === 'contract') return 'CTR';
    if (type === 'epl_waybill') return 'EPL';
    if (type === 'approval') return 'OK';
    if (type === 'email') return 'MAIL';
    return item.icon || 'GO';
}

function closeOmniSearchResults() {
    const box = document.getElementById('omniSearchResults');
    setFloatingPanelVisibility(box, false, 'flex');
}

function omniStarterResults() {
    const quickActions = quickSearchActionCatalog().slice(0, 4).map((action, index) => ({
        type: 'Команда',
        title: action.title,
        desc: action.desc,
        link: `runQuickSearchCommand(${index})`,
        icon: action.icon || 'GO',
    }));
    const sections = navigationSearchCatalog().slice(0, 6).map(section => ({
        type: 'Раздел',
        title: section.title,
        desc: section.desc,
        link: section.view ? `openSearchSection('${section.view}')` : 'closeOmniSearchResults()',
        icon: section.icon || 'NAV',
    }));
    return [...quickActions, ...sections];
}

function workflowFocusForSearchType(type) {
    const map = {
        document: { key: 'document', selector: id => `[data-document-id="${id}"]` },
        task: { key: 'task', selector: id => `[data-task-id="${id}"]` },
        finance_payment: { key: 'finance', selector: id => `[data-finance-id="${id}"]` },
        lead: { key: 'lead', selector: () => '.crm-registry-table tr.is-selected' },
        deal: { key: 'deal', selector: () => '.crm-registry-table tr.is-selected' },
        purchase_order: { key: 'purchase', selector: id => `[data-purchase-id="${id}"]` },
        production_order: { key: 'production', selector: id => `[data-production-id="${id}"]` },
        approval: { key: 'approval', selector: id => `[data-approval-id="${id}"]` },
        email: { key: 'email', selector: id => `[data-email-id="${id}"]` },
    };
    return map[type] || null;
}

function focusSearchResultRow(type, id, delay = 140) {
    const focus = workflowFocusForSearchType(type);
    if (!focus || !id) return;
    if (typeof markWorkflowFocus === 'function') markWorkflowFocus(focus.key, Number(id));
    window.setTimeout(() => {
        const selector = focus.selector(Number(id));
        if (typeof scrollToWorkflowTarget === 'function') scrollToWorkflowTarget(selector, { block: 'center' });
    }, delay);
}

function documentTabForSearchResult(doc) {
    if (!doc) return '';
    if (doc.status === 'draft') return 'drafts';
    if (String(doc.type || '').startsWith('internal_')) return 'internal';
    return doc.type || 'incoming';
}

window.openOmniSearchResult = async function(entityType, entityId, viewName = '') {
    const type = String(entityType || '').toLowerCase();
    const id = Number(entityId || 0);
    closeOmniSearchResults();

    if (type === 'project' && id && typeof openProject === 'function') {
        openProject(id);
        return;
    }

    if (type === 'client' && id) {
        if (typeof loadClients === 'function') await loadClients();
        if (typeof openClientCard === 'function') {
            await openClientCard(id);
            return;
        }
        navigateTo('clients');
        return;
    }

    if (type === 'document' && id) {
        if (typeof loadDocuments === 'function') await loadDocuments();
        const doc = (documentsDB || []).find(item => Number(item.id) === id);
        focusSearchResultRow(type, id, 180);
        navigateTo('documents');
        const targetTab = documentTabForSearchResult(doc);
        if (targetTab && typeof switchDocTab === 'function') switchDocTab(targetTab);
        return;
    }

    if (type === 'task' && id) {
        if (typeof loadTasks === 'function') await loadTasks();
        const task = (tasksDB || []).find(item => Number(item.id) === id);
        focusSearchResultRow(type, id, 180);
        navigateTo('tasks');
        if (task && typeof switchTaskTab === 'function') switchTaskTab(task.status === 'completed' ? 'completed' : 'active');
        return;
    }

    if (type === 'lead' && id) {
        if (typeof loadCrmLeads === 'function') await loadCrmLeads();
        navigateTo('leads');
        window.setTimeout(() => {
            if (typeof selectLeadRow === 'function') selectLeadRow(id);
            focusSearchResultRow(type, id, 80);
        }, 180);
        return;
    }

    if (type === 'deal' && id) {
        if (typeof loadCrmDeals === 'function') await loadCrmDeals();
        navigateTo('deals');
        window.setTimeout(() => {
            if (typeof selectDealRow === 'function') selectDealRow(id);
            focusSearchResultRow(type, id, 80);
        }, 180);
        return;
    }

    if (type === 'contract' && id && typeof openContractCard === 'function') {
        await openContractCard(id);
        return;
    }

    if (type === 'epl_waybill' && id && typeof openEplModuleForWaybill === 'function') {
        await openEplModuleForWaybill(id);
        return;
    }

    if (type === 'email' && id) {
        if (typeof currentEmailFilter !== 'undefined') currentEmailFilter = 'all';
        focusSearchResultRow(type, id, 260);
        navigateTo('emails');
        return;
    }

    const targetView = String(viewName || ({
        finance_request: 'finance',
        finance_obligation: 'finance',
        procurement_request: 'supply',
        stock_reservation: 'supply',
        inventory_document: 'nomenclature',
    }[type] || 'dashboard'));
    const safeView = /^[a-z0-9_]+$/i.test(targetView) ? targetView : 'dashboard';
    focusSearchResultRow(type, id, 180);
    navigateTo(safeView);
};

function renderOmniResults(resBox, results) {
    if (results.length === 0) {
        resBox.innerHTML = '<div style="color:var(--secondary); font-size:12px; text-align:center; padding:10px;">Ничего не найдено</div>';
    } else {
        resBox.innerHTML = results.map(r => `
            <div onclick="${r.link}" style="padding: 8px 10px; background: var(--bg); border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 10px; border: 1px solid transparent;" onmouseover="this.style.borderColor='var(--primary)'" onmouseout="this.style.borderColor='transparent'">
                <div style="font-size: 10px; min-width: 36px; height: 26px; display:flex; align-items:center; justify-content:center; border-radius: 999px; background: rgba(31,79,209,0.08); color: var(--primary); font-weight: 800; letter-spacing: 0.06em;">${escapeHtml(r.icon)}</div>
                <div>
                    <div style="font-size: 12px; font-weight: bold; color: var(--text);">${escapeHtml(r.title)}</div>
                    <div style="font-size: 10px; color: var(--secondary);">${escapeHtml(`${r.type} • ${(r.desc || '').substring(0, 40)}`)}</div>
                </div>
            </div>
        `).join('');
    }
    setFloatingPanelVisibility(resBox, true, 'flex');
}

window.handleOmniSearch = async function() {
    const searchInput = document.getElementById('searchInput');
    const resBox = document.getElementById('omniSearchResults');
    if (!searchInput || !resBox) return;
    const q = String(searchInput.value || '').toLowerCase().trim();
    const seq = ++omniSearchSeq;
    if (!q) {
        closeOmniSearchResults();
        filterProjects();
        return;
    }

    filterProjects();

    const results = [];
    quickSearchActionCatalog().forEach((action, index) => {
        if (q.startsWith('/') || matchesSearchNeedle([action.title, action.desc, action.chip || '', action.type || ''], q)) {
            results.push({
                type: 'Команда',
                title: action.title,
                desc: action.desc,
                link: `runQuickSearchCommand(${index})`,
                icon: action.icon || 'GO',
            });
        }
    });
    sectionSearchMatches(q).forEach(section => {
        const navItem = navigationSearchCatalog().find(item => item.title === section.title);
        results.push({
            type: 'Раздел',
            title: section.title,
            desc: section.desc,
            link: navItem?.view ? `openSearchSection('${navItem.view}')` : "closeOmniSearchResults();",
            icon: section.icon,
        });
    });
    projectsDB.forEach(p => {
        if (matchesSearchNeedle([p.name, p.contract, p.client, p.manager], q)) {
            results.push({ type: 'Проект', title: p.name, desc: p.contract, link: `openProject(${p.id}); closeOmniSearchResults();`, icon: 'PR' });
        }
    });
    clientsDB.forEach(c => {
        if (matchesSearchNeedle([c.name, c.inn, c.contact], q)) {
            results.push({ type: 'Клиент', title: c.name, desc: c.inn || c.contact || 'контрагент', link: `openOmniSearchResult('client', ${Number(c.id || 0)}, 'clients')`, icon: 'CL' });
        }
    });
    documentsDB.forEach(d => {
        if (matchesSearchNeedle([d.number, d.subject, d.correspondent, d.type, d.status], q)) {
            results.push({ type: 'Документ', title: `№ ${d.number}`, desc: d.subject, link: `openOmniSearchResult('document', ${Number(d.id || 0)}, 'documents')`, icon: 'DOC' });
        }
    });
    tasksDB.forEach(t => {
        if (matchesSearchNeedle([t.title, t.executor, t.description, t.status], q)) {
            results.push({ type: 'Поручение', title: t.title, desc: `Исполнитель: ${t.executor}`, link: `openOmniSearchResult('task', ${Number(t.id || 0)}, 'tasks')`, icon: 'TSK' });
        }
    });
    (crmLeadsDB || []).forEach(lead => {
        if (matchesSearchNeedle([lead.title, lead.client_name, lead.contact_name, lead.contact_email, lead.contact_phone, lead.next_action, lead.source], q)) {
            results.push({ type: 'Лид', title: lead.title || `Лид #${lead.id}`, desc: `${lead.client_name || 'без компании'} · ${lead.contact_name || lead.source || 'без контакта'}`, link: `openOmniSearchResult('lead', ${Number(lead.id || 0)}, 'leads')`, icon: 'LEAD' });
        }
    });
    (crmDealsDB || []).forEach(deal => {
        if (matchesSearchNeedle([deal.title, deal.client_name, deal.contract_number, deal.next_action, deal.responsible, deal.stage], q)) {
            results.push({ type: 'Сделка', title: deal.title || `Сделка #${deal.id}`, desc: `${deal.contract_number || 'без номера'} · ${deal.client_name || 'без клиента'}`, link: `openOmniSearchResult('deal', ${Number(deal.id || 0)}, 'deals')`, icon: 'DEAL' });
        }
    });

    renderOmniResults(resBox, results.slice(0, 12));

    try {
        if (q.length < 2) return;
        const server = await apiCall(`/search?q=${encodeURIComponent(q)}&limit=8`);
        if (seq !== omniSearchSeq || !server || !Array.isArray(server.items)) return;
        const existingKeys = new Set(results.map(item => `${String(item.type).toLowerCase()}:${String(item.title).toLowerCase()}`));
        server.items.forEach(item => {
            const normalized = {
                type: item.type_label || item.type || item.entity_type || 'Результат',
                title: item.title || item.id || 'Найдено',
                desc: item.meta || item.desc || '',
                link: `openOmniSearchResult('${String(item.entity_type || item.type || '').replace(/[^a-zA-Z0-9_]/g, '')}', ${Number(item.entity_id || item.id || 0)}, '${String(item.view || '').replace(/[^a-zA-Z0-9_]/g, '')}')`,
                icon: omniSearchIconFor(item),
            };
            const key = `${String(normalized.type).toLowerCase()}:${String(normalized.title).toLowerCase()}`;
            if (!existingKeys.has(key)) {
                results.push(normalized);
                existingKeys.add(key);
            }
        });
        renderOmniResults(resBox, results.slice(0, 12));
    } catch (error) {
        console.warn('Server search unavailable, using local omni results', error);
    }
};

window.openOmniSearchSuggestions = function() {
    const searchInput = document.getElementById('searchInput');
    const resBox = document.getElementById('omniSearchResults');
    if (!searchInput || !resBox) return;
    const query = String(searchInput.value || '').trim();
    if (query) {
        window.handleOmniSearch();
        return;
    }
    renderOmniResults(resBox, omniStarterResults());
};

document.addEventListener('keydown', (e) => {
    if (keyboardEventMatchesShortcut(e, getShortcutConfig('commandPalette'))) {
        e.preventDefault();
        if (typeof openCommandPalette === 'function') openCommandPalette();
        return;
    }
    if (keyboardEventMatchesShortcut(e, getShortcutConfig('globalSearch'))) {
        e.preventDefault();
        focusGlobalSearchInput();
    }
});

document.addEventListener('click', (e) => {
    const sb = document.querySelector('.search-bar');
    const box = document.getElementById('omniSearchResults');
    if (sb && !sb.contains(e.target) && box) closeOmniSearchResults();
});
