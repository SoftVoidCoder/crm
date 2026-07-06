// ==========================================
// 6. ПОЧТА (EMAIL)
// ==========================================

let currentEmailFilter = 'all';
let currentEmailAccountId = 0;
let currentEmailQuery = '';
let editingEmailAccountId = null;
let expandedReplyEmailId = null;

const EMAIL_PROVIDER_DEFAULTS = {
    yandex: {
        imap_host: 'imap.yandex.ru',
        imap_port: 993,
        smtp_host: 'smtp.yandex.ru',
        smtp_port: 465,
        inbox_folder: 'INBOX',
        archive_folder: 'Archive',
    },
    gmail: {
        imap_host: 'imap.gmail.com',
        imap_port: 993,
        smtp_host: 'smtp.gmail.com',
        smtp_port: 465,
        inbox_folder: 'INBOX',
        archive_folder: '[Gmail]/All Mail',
    },
    outlook: {
        imap_host: 'outlook.office365.com',
        imap_port: 993,
        smtp_host: 'smtp.office365.com',
        smtp_port: 465,
        inbox_folder: 'INBOX',
        archive_folder: 'Archive',
    },
    mailru: {
        imap_host: 'imap.mail.ru',
        imap_port: 993,
        smtp_host: 'smtp.mail.ru',
        smtp_port: 465,
        inbox_folder: 'INBOX',
        archive_folder: 'Archive',
    }
};

function getEmailProviderKey(address) {
    const domain = String(address || '').trim().toLowerCase().split('@')[1] || '';
    if (!domain) return '';
    if (['yandex.ru', 'ya.ru', 'yandex.com', 'yandex.kz', 'yandex.by', 'yandex.ua', 'yandex.uz'].includes(domain)) return 'yandex';
    if (domain === 'gmail.com') return 'gmail';
    if (['outlook.com', 'office365.com', 'hotmail.com', 'live.com', 'msn.com'].includes(domain)) return 'outlook';
    if (['mail.ru', 'bk.ru', 'inbox.ru', 'list.ru'].includes(domain)) return 'mailru';
    return '';
}

function getEmailProviderDefaults(address) {
    const provider = getEmailProviderKey(address);
    const defaults = EMAIL_PROVIDER_DEFAULTS[provider] || EMAIL_PROVIDER_DEFAULTS.yandex;
    const email = String(address || '').trim();
    const localPart = email.split('@')[0] || email;
    return {
        ...defaults,
        label: localPart || email,
        login: email,
        smtp_login: email,
    };
}

function getEmailSetupCopy(provider) {
    const copyMap = {
        yandex: {
    hint: 'Для Яндекс 360 обычно достаточно адреса ящика и пароля приложения. Параметры входящей и исходящей почты подставятся автоматически.',
            note: 'Используй пароль приложения Yandex, если обычный пароль не проходит.'
        },
        gmail: {
            hint: 'Для Gmail нужен адрес ящика и пароль приложения Google. Обычный пароль аккаунта часто не подходит.',
            note: 'Сначала включи двухэтапную аутентификацию Google, затем создай пароль приложения и вставь его сюда.'
        },
        outlook: {
            hint: 'Для Outlook чаще всего хватает адреса ящика и пароля приложения или пароля учетной записи Microsoft 365.',
            note: 'Если компания использует отдельные серверы, при необходимости открой дополнительные настройки.'
        },
        mailru: {
    hint: 'Для Mail.ru проверь, какой пароль разрешен для внешних приложений, и используй его для входящей и исходящей почты.',
    note: 'Если логин или пароль исходящей почты отличаются, задай их в дополнительных настройках.'
        },
        manual: {
    hint: 'Ручная настройка подходит для нестандартных серверов или если параметры входящей и исходящей почты отличаются от типовых значений.',
            note: 'Заполни адрес, пароль и при необходимости открой дополнительные настройки ниже.'
        },
        default: {
    hint: 'Выбери провайдера или просто введи адрес почты. Система сама попробует подставить нужные параметры.',
            note: 'Для безопасного подключения лучше использовать пароль приложения.'
        }
    };
    return copyMap[provider] || copyMap.default;
}

function updateEmailSetupCopy(provider = '') {
    const { hint, note } = getEmailSetupCopy(provider || 'default');
    const hintNode = document.getElementById('emailSetupHint');
    const noteNode = document.getElementById('emailAccountNote');
    if (hintNode) hintNode.textContent = hint;
    if (noteNode) noteNode.textContent = note;
}

function updateEmailSetupHintFromAddress() {
    const addressInput = document.getElementById('emailAccountAddress');
    const provider = getEmailProviderKey(addressInput?.value || '');
    updateEmailSetupCopy(provider || 'default');
}

function startEmailConnect(provider = '') {
    resetEmailAccountForm();
    if (provider && provider !== 'manual') {
        applyEmailProviderPreset(provider);
        updateEmailSetupCopy(provider);
    } else {
        updateEmailSetupCopy(provider || 'default');
    }
    const advanced = document.querySelector('.email-account-advanced');
    if (advanced && provider === 'manual') advanced.open = true;
    document.getElementById('emailAccountAddress')?.focus();
}

function openManualEmailSetup() {
    startEmailConnect('manual');
}

function syncEmailAccountQuickSetup(force = false) {
    const addressInput = document.getElementById('emailAccountAddress');
    const labelInput = document.getElementById('emailAccountLabel');
    const loginInput = document.getElementById('emailAccountLogin');
    const imapInput = document.getElementById('emailAccountImapHost');
    const imapPortInput = document.getElementById('emailAccountImapPort');
    const smtpInput = document.getElementById('emailAccountSmtpHost');
    const smtpPortInput = document.getElementById('emailAccountSmtpPort');
    const smtpLoginInput = document.getElementById('emailAccountSmtpLogin');
    const inboxInput = document.getElementById('emailAccountInboxFolder');
    const archiveInput = document.getElementById('emailAccountArchiveFolder');
    if (!addressInput) return;
    const address = addressInput.value.trim();
    if (!address) return;
    const defaults = getEmailProviderDefaults(address);

    if (force || !(labelInput?.value || '').trim()) {
        if (labelInput) labelInput.value = defaults.label;
    }
    if (force || !(loginInput?.value || '').trim()) {
        if (loginInput) loginInput.value = defaults.login;
    }
    if (force || !(imapInput?.value || '').trim()) {
        if (imapInput) imapInput.value = defaults.imap_host;
    }
    if (force || !(imapPortInput?.value || '').trim()) {
        if (imapPortInput) imapPortInput.value = String(defaults.imap_port);
    }
    if (force || !(smtpInput?.value || '').trim()) {
        if (smtpInput) smtpInput.value = defaults.smtp_host;
    }
    if (force || !(smtpPortInput?.value || '').trim()) {
        if (smtpPortInput) smtpPortInput.value = String(defaults.smtp_port);
    }
    if (force || !(smtpLoginInput?.value || '').trim()) {
        if (smtpLoginInput) smtpLoginInput.value = defaults.smtp_login;
    }
    if (force || !(inboxInput?.value || '').trim()) {
        if (inboxInput) inboxInput.value = defaults.inbox_folder;
    }
    if (force || !(archiveInput?.value || '').trim()) {
        if (archiveInput) archiveInput.value = defaults.archive_folder;
    }
}

function humanizeMailboxError(errorText) {
    const text = String(errorText || '').trim();
    if (!text) return '';
    if (/nodename nor servname provided|name or service not known|getaddrinfo/i.test(text)) {
    return 'Не удаётся подключиться к серверу. Проверь параметры входящей и исходящей почты и интернет-соединение.';
    }
    if (/authentication failed|invalid credentials|login command error|auth/i.test(text)) {
        return 'Ошибка авторизации. Проверь логин, пароль и доступ приложения к почте.';
    }
    if (/timeout|timed out/i.test(text)) {
        return 'Сервер почты не ответил вовремя. Попробуй ещё раз или проверь таймауты и сеть.';
    }
    return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}

function applyEmailProviderPreset(provider) {
    const preset = EMAIL_PROVIDER_DEFAULTS[provider];
    if (!preset) return;
    const imap = document.getElementById('emailAccountImapHost');
    const smtp = document.getElementById('emailAccountSmtpHost');
    const inbox = document.getElementById('emailAccountInboxFolder');
    const archive = document.getElementById('emailAccountArchiveFolder');
    if (imap) imap.value = preset.imap_host;
    if (smtp) smtp.value = preset.smtp_host;
    if (inbox) inbox.value = preset.inbox_folder;
    if (archive) archive.value = preset.archive_folder;
    showToast('Почта', 'Пресет провайдера применён');
}

function setEmailFilter(filter) {
    currentEmailFilter = filter;
    ['all', 'new', 'read', 'archived'].forEach(key => {
        const btn = document.getElementById(`emailFilter${key.charAt(0).toUpperCase()}${key.slice(1)}`);
        if (btn) btn.classList.toggle('active', key === filter);
    });
    renderEmails();
}

function setEmailAccount(accountId) {
    currentEmailAccountId = Number(accountId) || 0;
    renderEmailAccounts();
    renderEmails();
}

function applyEmailSearch(value) {
    currentEmailQuery = (value || '').trim();
    renderEmails();
}

async function testMailbox(accountId) {
    const res = await apiCall(`/email/accounts/${accountId}/test`, 'POST');
    if (!res || res.error) {
        return customAlert(res?.error || 'Не удалось проверить ящик.');
    }
    const imapText = res.imap?.ok ? 'Входящая почта: норма' : `Входящая почта: ${res.imap?.error || 'ошибка'}`;
    const smtpText = res.smtp?.ok ? 'Исходящая почта: норма' : `Исходящая почта: ${res.smtp?.error || 'ошибка'}`;
    await loadEmailAccounts();
    renderEmailAccounts();
    showToast('Почта', `${imapText} · ${smtpText}`, res.status === 'success' ? 'success' : 'error');
}

async function retryFailedMailOps(accountId = 0) {
    const suffix = accountId ? `?account_id=${Number(accountId) || 0}` : '';
    const res = await apiCall(`/email/retry_failed${suffix}`, 'POST');
    if (!res || res.error) {
        return customAlert(res?.error || 'Не удалось повторить сбойные операции.');
    }
    await loadEmailAccounts();
    renderEmailAccounts();
    await renderEmails();
    const failedCount = Array.isArray(res.failed_accounts) ? res.failed_accounts.length : 0;
    const retriedCount = Number(res.count || 0);
    showToast('Почта', `Повторено: ${retriedCount}, ещё с ошибкой: ${failedCount}`, failedCount ? 'error' : 'success');
}

function renderEmailAccounts() {
    const container = document.getElementById('emailAccountsList');
    if (!container) return;
    const canManageAccounts = Array.isArray(currentPermissions?.emails) && currentPermissions.emails.includes('manage_accounts');
    const form = document.querySelector('.email-account-form');
    const newMailboxBtn = document.getElementById('newMailboxBtn');
    if (form) form.style.display = canManageAccounts ? 'flex' : 'none';
    if (newMailboxBtn) newMailboxBtn.style.display = canManageAccounts ? 'inline-flex' : 'none';
    if (!emailAccountsDB || emailAccountsDB.length === 0) {
        container.innerHTML = '<div class="empty-state">Почтовые ящики ещё не добавлены. Создай первый ящик выше.</div>';
        return;
    }

    container.innerHTML = `
        <button class="email-account-card ${currentEmailAccountId === 0 ? 'active' : ''}" onclick="setEmailAccount(0)">
            <div class="email-account-card-main">
                <div class="email-account-name">Все ящики</div>
                <div class="email-account-meta">Общая лента по всем активным адресам</div>
            </div>
        </button>
        ${emailAccountsDB.map(account => `
            <div class="email-account-card ${currentEmailAccountId === account.id ? 'active' : ''}">
                <button class="email-account-select" onclick="setEmailAccount(${account.id})">
                    <div class="email-account-card-main">
                        <div class="email-account-name">${account.label || account.address}</div>
                        <div class="email-account-meta">${account.address}</div>
                    </div>
                    <div class="email-account-counters">
                        <span>${account.unread_count || 0} новых</span>
                        <span>${account.archived_count || 0} в архиве</span>
                    </div>
                    <div class="email-account-status-line">
                        <span class="email-status-pill ${account.last_sync_status === 'error' ? 'email-status-pill--error' : 'email-status-pill--ok'}">
                            ${account.last_sync_status === 'error' ? 'Обмен с ошибкой' : 'Обмен в норме'}
                        </span>
                ${account.sync_fail_count ? `<span class="email-status-pill email-status-pill--muted">${account.sync_fail_count} повтор</span>` : ''}
                    </div>
                    ${account.next_retry_at ? `<div class="email-account-meta">Следующая авто-попытка: ${new Date(account.next_retry_at * 1000).toLocaleString('ru-RU')}</div>` : ''}
                    ${account.last_error ? `<div class="email-account-error">${humanizeMailboxError(account.last_error)}</div>` : ''}
                ${account.last_delivery_error ? `<div class="email-account-error">Исходящая почта: ${humanizeMailboxError(account.last_delivery_error)}</div>` : ''}
                </button>
                ${canManageAccounts ? `
                    <div class="email-account-card-actions">
                        <button class="btn-secondary" onclick="editEmailAccount(${account.id})">Редактировать</button>
                        <button class="btn-secondary" onclick="testMailbox(${account.id})">Проверить</button>
                        <button class="btn-secondary" onclick="syncMailbox(${account.id})">Обновить</button>
                        <button class="btn-secondary" onclick="retryFailedMailOps(${account.id})">Повторить сбои</button>
                        <button class="btn-danger" onclick="deleteMailbox(${account.id})">Удалить</button>
                    </div>
                ` : ''}
            </div>
        `).join('')}
    `;
}

function resetEmailAccountForm() {
    editingEmailAccountId = null;
    const defaults = {
        emailAccountLabel: '',
        emailAccountAddress: '',
        emailAccountLogin: '',
        emailAccountPassword: '',
        emailAccountImapHost: EMAIL_PROVIDER_DEFAULTS.yandex.imap_host,
        emailAccountImapPort: String(EMAIL_PROVIDER_DEFAULTS.yandex.imap_port),
        emailAccountSmtpHost: EMAIL_PROVIDER_DEFAULTS.yandex.smtp_host,
        emailAccountSmtpPort: String(EMAIL_PROVIDER_DEFAULTS.yandex.smtp_port),
        emailAccountSmtpLogin: '',
        emailAccountSmtpPassword: '',
        emailAccountInboxFolder: EMAIL_PROVIDER_DEFAULTS.yandex.inbox_folder,
        emailAccountArchiveFolder: EMAIL_PROVIDER_DEFAULTS.yandex.archive_folder
    };
    Object.entries(defaults).forEach(([id, value]) => {
        const input = document.getElementById(id);
        if (input) input.value = value;
    });
    const isDefault = document.getElementById('emailAccountDefault');
    const isActive = document.getElementById('emailAccountActive');
    if (isDefault) isDefault.checked = false;
    if (isActive) isActive.checked = true;
    const advanced = document.querySelector('.email-account-advanced');
    if (advanced) advanced.open = false;
    updateEmailSetupCopy('default');
}

function editEmailAccount(accountId) {
    const account = (emailAccountsDB || []).find(item => item.id === accountId);
    if (!account) return;
    editingEmailAccountId = account.id;
    document.getElementById('emailAccountLabel').value = account.label || '';
    document.getElementById('emailAccountAddress').value = account.address || '';
    document.getElementById('emailAccountLogin').value = account.login || account.address || '';
    document.getElementById('emailAccountPassword').value = '';
    document.getElementById('emailAccountImapHost').value = account.imap_host || 'imap.yandex.ru';
    document.getElementById('emailAccountSmtpHost').value = account.smtp_host || 'smtp.yandex.ru';
    document.getElementById('emailAccountSmtpLogin').value = account.smtp_login || account.login || '';
    document.getElementById('emailAccountSmtpPassword').value = '';
    document.getElementById('emailAccountInboxFolder').value = account.inbox_folder || 'INBOX';
    document.getElementById('emailAccountArchiveFolder').value = account.archive_folder || 'Archive';
    document.getElementById('emailAccountDefault').checked = !!account.is_default;
    document.getElementById('emailAccountActive').checked = !!account.is_active;
    const advanced = document.querySelector('.email-account-advanced');
    if (advanced) advanced.open = true;
    updateEmailSetupCopy(getEmailProviderKey(account.address || '') || 'manual');
}

async function saveEmailAccount() {
    syncEmailAccountQuickSetup(true);
    const payload = {
        label: document.getElementById('emailAccountLabel').value.trim(),
        address: document.getElementById('emailAccountAddress').value.trim(),
        login: document.getElementById('emailAccountLogin').value.trim(),
        password: document.getElementById('emailAccountPassword').value,
        imap_host: document.getElementById('emailAccountImapHost').value.trim(),
        imap_port: Number(document.getElementById('emailAccountImapPort')?.value || 0) || 0,
        smtp_host: document.getElementById('emailAccountSmtpHost').value.trim(),
        smtp_port: Number(document.getElementById('emailAccountSmtpPort')?.value || 0) || 0,
        smtp_login: document.getElementById('emailAccountSmtpLogin').value.trim(),
        smtp_password: document.getElementById('emailAccountSmtpPassword').value,
        inbox_folder: document.getElementById('emailAccountInboxFolder').value.trim(),
        archive_folder: document.getElementById('emailAccountArchiveFolder').value.trim(),
        is_default: document.getElementById('emailAccountDefault').checked ? 1 : 0,
        is_active: document.getElementById('emailAccountActive').checked ? 1 : 0
    };
    if (!payload.label || !payload.address || !payload.login || (!payload.password && !editingEmailAccountId)) {
        return customAlert('Заполни название ящика, адрес, логин и пароль.');
    }
    if (!payload.imap_host || !payload.smtp_host) {
        const defaults = getEmailProviderDefaults(payload.address);
        if (!payload.imap_host) payload.imap_host = defaults.imap_host;
        if (!payload.smtp_host) payload.smtp_host = defaults.smtp_host;
    }
    if (!payload.imap_port) payload.imap_port = getEmailProviderDefaults(payload.address).imap_port;
    if (!payload.smtp_port) payload.smtp_port = getEmailProviderDefaults(payload.address).smtp_port;
    if (!payload.inbox_folder) payload.inbox_folder = getEmailProviderDefaults(payload.address).inbox_folder;
    if (!payload.archive_folder) payload.archive_folder = getEmailProviderDefaults(payload.address).archive_folder;
    if (!payload.login) payload.login = payload.address;
    if (!payload.smtp_login) payload.smtp_login = payload.login;

    const endpoint = editingEmailAccountId ? `/email/accounts/${editingEmailAccountId}` : '/email/accounts';
    const method = editingEmailAccountId ? 'PUT' : 'POST';
    const res = await apiCall(endpoint, method, payload);
    if (!res || res.error) {
        return customAlert(res?.error || 'Не удалось сохранить почтовый ящик.');
    }

    await loadEmailAccounts();
    renderEmailAccounts();
    resetEmailAccountForm();
    await renderEmails(true);
    showToast('Почта', 'Почтовый ящик сохранён');
}

async function deleteMailbox(accountId) {
    if (!(await customConfirm('Удалить почтовый ящик и локальный кеш его писем?'))) return;
    const res = await apiCall(`/email/accounts/${accountId}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось удалить ящик.');
    if (currentEmailAccountId === accountId) currentEmailAccountId = 0;
    await loadEmailAccounts();
    renderEmailAccounts();
    await renderEmails();
}

async function syncMailbox(accountId) {
    const res = await apiCall(`/email/accounts/${accountId}/sync`, 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось синхронизировать ящик.');
    await loadEmailAccounts();
    renderEmailAccounts();
    await renderEmails();
    if (res.status === 'deferred') {
        showToast('Почта', 'Ящик пока в режиме паузы после ошибок. Автоповтор уже запланирован.', 'error');
        return;
    }
    if (res.status === 'error') {
        showToast('Почта', 'Синхронизация завершилась с ошибкой. Детали записаны в карточке ящика.', 'error');
        return;
    }
    showToast('Почта', 'Синхронизация завершена');
}

async function renderEmails(forceRefresh = false) {
    const container = document.getElementById('emailsListContainer'); 
    if (!container) return;

    if (typeof loadEmailAccounts === 'function') {
        await loadEmailAccounts();
    }
    renderEmailAccounts();

    if (emailAccountsDB.length === 0) {
        container.innerHTML = '<div class="email-empty">Сначала добавь хотя бы один корпоративный почтовый ящик.</div>';
        return;
    }

    container.innerHTML = '<div class="email-loading">Собираем письма, статусы и архив по выбранным ящикам...</div>';
    const params = new URLSearchParams();
    if (currentEmailAccountId) params.set('account_id', currentEmailAccountId);
    params.set('filter_name', currentEmailFilter);
    if (currentEmailQuery) params.set('query', currentEmailQuery);
    if (forceRefresh) params.set('force_refresh', '1');
    const data = await apiCall(`/emails?${params.toString()}`);
    emailsDB = Array.isArray(data) ? data : [];

    if (emailsDB.length === 0) {
        container.innerHTML = '<div class="email-empty">По этому фильтру писем пока нет. Попробуй другой ящик, архив или обновление.</div>';
        return;
    }

    container.innerHTML = emailsDB.map(e => {
        const canCreateProject = !!(e.sender_email || '').trim() && !/система/i.test(e.sender || '') && !/login command error|syntax error/i.test(`${e.subject || ''} ${e.body_text || ''}`);
        return `
        <div data-email-id="${e.id}" class="email-card ${e.is_read ? '' : 'unread'} ${typeof isWorkflowFocused === 'function' && isWorkflowFocused('email', e.id) ? 'workflow-row-highlight' : ''}">
            <div class="email-card-top">
                <div class="email-card-main">
                    <div class="email-card-tags">
                        <span class="status-badge ${e.is_read ? 'status-archived' : 'status-active'}">${e.is_read ? 'Прочитано' : 'Новое'}</span>
                        <span class="status-badge ${e.is_archived ? 'status-archived' : 'status-completed'}">${e.is_archived ? 'Архив' : 'Входящие'}</span>
                        <span class="email-mailbox-chip">${e.account_label || e.account_address || 'Почта'}</span>
                        ${e.delivery_status === 'failed' ? '<span class="status-badge status-overdue">Ошибка ответа</span>' : ''}
                    ${e.delivery_status === 'replied' ? '<span class="status-badge status-completed">Ответ отправлен</span>' : ''}
                </div>
                <div class="email-subject">${e.subject}</div>
                <div class="email-sender">От: <strong>${e.sender}</strong> · ${e.received_at || 'без даты'}</div>
                <div class="ops-note">${e.account_address ? `Ящик: ${e.account_address}` : 'Источник письма не указан'}${e.sender_email ? ` · reply-to: ${e.sender_email}` : ''}</div>
            </div>
            <div class="email-actions">
                <button class="btn-secondary" onclick="toggleEmailRead(${e.id}, ${e.is_read ? 0 : 1})">${e.is_read ? 'Как новое' : 'Прочитать'}</button>
                <button class="btn-secondary" onclick="toggleEmailReply(${e.id})">${expandedReplyEmailId === e.id ? 'Скрыть ответ' : 'Ответить'}</button>
                    ${!e.is_archived ? `<button class="btn-secondary" onclick="archiveEmailMessage(${e.id})">В архив</button>` : `<button class="btn-secondary" onclick="restoreEmailMessage(${e.id})">Вернуть</button>`}
                    ${canCreateProject ? `<button class="btn-primary" onclick="createProjectFromEmail(${e.id})">Сделать проектом</button>` : ''}
                    <button class="btn-danger" onclick="deleteEmailMessage(${e.id})">Удалить</button>
                </div>
            </div>
            ${(e.attachments || []).length ? `
                <div class="email-attachments">
                    ${(e.attachments || []).map(att => `
                        <a class="file-item" href="${att.stored_path}" target="_blank">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 1 1 5.66 5.66L9.41 17.41a2 2 0 1 1-2.83-2.83l8.48-8.48"></path></svg>
                            ${att.filename}
                        </a>
                    `).join('')}
                </div>
            ` : ''}
            <div class="email-body">${e.body_text || e.body_preview || ''}</div>
            ${e.last_action_error ? `<div class="email-account-error">Последняя ошибка: ${humanizeMailboxError(e.last_action_error)}</div>` : ''}
            ${expandedReplyEmailId === e.id ? `
                <div class="email-reply-box">
                    <textarea id="replyBody_${e.id}" class="auth-input" rows="4" style="margin:0;" placeholder="Ответ для ${e.sender_email || e.sender}..."></textarea>
                    <input id="replyFiles_${e.id}" type="file" class="auth-input" style="margin:0;" multiple>
                    <div class="email-reply-actions">
                        <button class="btn-primary" onclick="sendEmailReply(${e.id})">Отправить ответ</button>
                    </div>
                </div>
            ` : ''}
        </div>
    `;
    }).join('');
}

function createProjectFromEmail(id) { 
    const email = emailsDB.find(e => e.id === id); 
    if (!email) return; 
    
    createNewProject(); 
    setTimeout(() => { 
        document.getElementById('newProjName').value = "Почта: " + email.subject.substring(0, 40);
        document.getElementById('newProjContract').value = 'ПОЧТА';
        const clientInput = document.getElementById('newProjClient');
        if (clientInput) clientInput.value = email.sender || '';
    }, 100); 
}

async function toggleEmailRead(messageId, read) {
    const res = await apiCall(`/emails/${messageId}/read`, 'POST', { read });
    if (!res || res.error) return customAlert(res?.error || 'Не удалось сменить статус письма.');
    await renderEmails();
}

function toggleEmailReply(messageId) {
    expandedReplyEmailId = expandedReplyEmailId === messageId ? null : messageId;
    renderEmails();
}

async function sendEmailReply(messageId) {
    const bodyInput = document.getElementById(`replyBody_${messageId}`);
    const fileInput = document.getElementById(`replyFiles_${messageId}`);
    const body = bodyInput ? bodyInput.value.trim() : '';
    if (!body) return customAlert('Напиши текст ответа.');

    const formData = new FormData();
    formData.append('body', body);
    Array.from(fileInput?.files || []).forEach(file => formData.append('files', file));
    const res = await apiCall(`/emails/${messageId}/reply`, 'POST', formData);
    if (!res || res.error) return customAlert(res?.error || 'Не удалось отправить ответ.');
    showToast('Почта', 'Ответ отправлен');
    expandedReplyEmailId = null;
    await renderEmails();
}

async function archiveEmailMessage(messageId) {
    const res = await apiCall(`/emails/${messageId}/archive`, 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось отправить письмо в архив.');
    await renderEmails(true);
}

async function restoreEmailMessage(messageId) {
    const res = await apiCall(`/emails/${messageId}/restore`, 'POST');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось вернуть письмо из архива.');
    await renderEmails(true);
}

async function deleteEmailMessage(messageId) {
    if (!(await customConfirm('Удалить письмо? Это действие затронет и серверный ящик.'))) return;
    const res = await apiCall(`/emails/${messageId}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.error || 'Не удалось удалить письмо.');
    await renderEmails(true);
}

// ==========================================
// 7. СОВЕЩАНИЯ И ПЛАНЕРКИ
// ==========================================

let currentCalendarMode = 'month';
let currentCalendarFilter = 'all';
let currentCalendarDepartment = '';
let currentCalendarAnchorDate = new Date();
let editingCalendarEventId = 0;

function calendarParseDate(value) {
    if (!value || typeof value !== 'string') return null;
    const parts = value.split('.');
    if (parts.length !== 3) return null;
    const date = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
    if (Number.isNaN(date.getTime())) return null;
    date.setHours(0, 0, 0, 0);
    return date;
}

function calendarFormatDate(value) {
    const date = value instanceof Date ? value : calendarParseDate(value);
    if (!date) return '';
    const dd = String(date.getDate()).padStart(2, '0');
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    return `${dd}.${mm}.${date.getFullYear()}`;
}

function calendarCloneDate(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function calendarStartOfWeek(date) {
    const clone = calendarCloneDate(date);
    const day = clone.getDay() || 7;
    clone.setDate(clone.getDate() - day + 1);
    clone.setHours(0, 0, 0, 0);
    return clone;
}

function calendarEndOfWeek(date) {
    const clone = calendarStartOfWeek(date);
    clone.setDate(clone.getDate() + 6);
    return clone;
}

function calendarDateDiff(value) {
    const date = value instanceof Date ? value : calendarParseDate(value);
    if (!date) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((date - today) / 86400000);
}

function calendarTone(item) {
    if (!item) return 'neutral';
    if (item.kind === 'meeting') return item.status === 'completed' ? 'positive' : 'attention';
    if (item.status === 'completed' || item.status === 'done') return 'positive';
    const diff = calendarDateDiff(item.date);
    if (diff !== null && diff < 0) return 'critical';
    if (diff !== null && diff <= 1) return 'attention';
    if (item.kind === 'project') return 'accent';
    return 'neutral';
}

function calendarKindLabel(kind) {
    return {
        event: 'Событие',
        meeting: 'Совещание',
        task: 'Поручение',
        project: 'Этап проекта',
    }[String(kind || '')] || 'Запись';
}

function calendarScopeLabel(scope) {
    return {
        personal: 'Личный',
        shared: 'Общий',
        department: 'Отдел',
    }[String(scope || '')] || 'Контур';
}

function calendarCollectDepartments() {
    const departmentSet = new Set();
    (calendarEventsDB || []).forEach(item => {
        const department = String(item.department || '').trim();
        if (department) departmentSet.add(department);
    });
    (allUsersDB || []).forEach(user => {
        const role = String(user.role || '').trim();
        if (role) departmentSet.add(role);
    });
    return Array.from(departmentSet).sort((a, b) => a.localeCompare(b, 'ru'));
}

function calendarRangeBounds() {
    const anchor = calendarCloneDate(currentCalendarAnchorDate);
    if (currentCalendarMode === 'day') {
        return { start: anchor, end: anchor };
    }
    if (currentCalendarMode === 'week') {
        return { start: calendarStartOfWeek(anchor), end: calendarEndOfWeek(anchor) };
    }
    if (currentCalendarMode === 'schedule') {
        const start = anchor;
        const end = calendarCloneDate(anchor);
        end.setDate(end.getDate() + 13);
        return { start, end };
    }
    const start = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
    start.setHours(0, 0, 0, 0);
    end.setHours(0, 0, 0, 0);
    return { start, end };
}

function calendarRangeLabel() {
    const { start, end } = calendarRangeBounds();
    const months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
    if (currentCalendarMode === 'day') return `${start.getDate()} ${months[start.getMonth()]} ${start.getFullYear()}`;
    if (currentCalendarMode === 'week') return `${calendarFormatDate(start)} - ${calendarFormatDate(end)}`;
    if (currentCalendarMode === 'schedule') return `Расписание · ${calendarFormatDate(start)} - ${calendarFormatDate(end)}`;
    return `${months[start.getMonth()]} ${start.getFullYear()}`;
}

function calendarEventProjectLabel(projectId) {
    const project = (projectsDB || []).find(item => Number(item.id || 0) === Number(projectId || 0));
    return project?.name || project?.contract || '';
}

function calendarBuildItems() {
    const items = [];
    (calendarEventsDB || []).forEach(event => {
        items.push({
            id: Number(event.id || 0),
            kind: 'event',
            title: event.title || 'Событие',
            date: event.event_date || '',
            time: event.start_time || '',
            endTime: event.end_time || '',
            status: event.status || 'planned',
            scope: event.scope || 'personal',
            department: event.department || '',
            location: event.location || '',
            description: event.description || '',
            projectId: Number(event.project_id || 0),
            meetingId: Number(event.meeting_id || 0),
            owner: event.owner_name || '',
            meta: [calendarScopeLabel(event.scope), event.department || '', calendarEventProjectLabel(event.project_id)].filter(Boolean).join(' · '),
        });
    });
    (meetingsDB || []).forEach(meeting => {
        items.push({
            id: Number(meeting.id || 0),
            kind: 'meeting',
            title: meeting.title || 'Совещание',
            date: meeting.m_date || '',
            time: meeting.m_time || '',
            status: meeting.status || 'planned',
            scope: 'shared',
            meta: Array.isArray(meeting.participants) ? meeting.participants.slice(0, 3).join(', ') : '',
            description: Array.isArray(meeting.agenda) ? meeting.agenda.join('; ') : '',
        });
    });
    (tasksDB || []).forEach(task => {
        if (!task.deadline) return;
        items.push({
            id: Number(task.id || 0),
            kind: 'task',
            title: task.title || 'Поручение',
            date: task.deadline || '',
            time: '',
            status: task.status || 'active',
            scope: 'shared',
            meta: [task.executor || 'исполнитель не задан', task.author ? `автор: ${task.author}` : ''].filter(Boolean).join(' · '),
            description: task.description || '',
        });
    });
    (projectsDB || []).forEach(project => {
        const deadlines = project?.deadlines && typeof project.deadlines === 'object' ? project.deadlines : {};
        Object.entries(deadlines).forEach(([stageIndex, deadline]) => {
            if (!deadline) return;
            const checklistItem = Array.isArray(project.checklist) ? project.checklist[Number(stageIndex)] : null;
            const stageTitle = checklistItem?.title || `Этап ${Number(stageIndex) + 1}`;
            items.push({
                id: Number(project.id || 0) * 1000 + Number(stageIndex || 0),
                projectId: Number(project.id || 0),
                stageIndex: Number(stageIndex || 0),
                kind: 'project',
                title: `${project.name || project.contract || 'Проект'} · ${stageTitle}`,
                date: deadline,
                time: '',
                status: project.status || 'active',
                scope: 'shared',
                meta: [project.client || '', project.manager || ''].filter(Boolean).join(' · '),
                description: project.contract || '',
            });
        });
    });
    return items
        .filter(item => item.date)
        .filter(item => {
            if (currentCalendarFilter === 'all') return true;
            if (currentCalendarFilter === 'meetings') return item.kind === 'meeting';
            if (currentCalendarFilter === 'tasks') return item.kind === 'task';
            if (currentCalendarFilter === 'projects') return item.kind === 'project';
            if (item.kind !== 'event') return false;
            if (currentCalendarFilter === 'personal') return item.scope === 'personal';
            if (currentCalendarFilter === 'shared') return item.scope === 'shared';
            if (currentCalendarFilter === 'department') {
                if (item.scope !== 'department') return false;
                if (currentCalendarDepartment && String(item.department || '') !== currentCalendarDepartment) return false;
                return true;
            }
            return true;
        })
        .sort((left, right) => {
            const leftDate = calendarParseDate(left.date)?.getTime() || 0;
            const rightDate = calendarParseDate(right.date)?.getTime() || 0;
            if (leftDate !== rightDate) return leftDate - rightDate;
            return String(left.time || '').localeCompare(String(right.time || ''));
        });
}

function fillCalendarDepartmentFilter() {
    const select = document.getElementById('calendarDepartmentFilter');
    if (!select) return;
    const departments = calendarCollectDepartments();
    select.innerHTML = `<option value="">Все отделы</option>${departments.map(department => `
        <option value="${department}">${department}</option>
    `).join('')}`;
    select.value = currentCalendarDepartment || '';
    select.disabled = currentCalendarFilter !== 'department';
}

function calendarItemsInRange(items) {
    const { start, end } = calendarRangeBounds();
    return items.filter(item => {
        const date = calendarParseDate(item.date);
        if (!date) return false;
        return date >= start && date <= end;
    });
}

function renderCalendarSummary(items) {
    const mount = document.getElementById('calendarSummaryStrip');
    if (!mount) return;
    const meetings = items.filter(item => item.kind === 'meeting').length;
    const tasks = items.filter(item => item.kind === 'task').length;
    const projects = items.filter(item => item.kind === 'project').length;
    const overdue = items.filter(item => calendarTone(item) === 'critical').length;
    mount.innerHTML = `
        <div class="crm-summary-card"><div class="crm-summary-label">Событий в диапазоне</div><div class="crm-summary-value">${items.length}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Совещания</div><div class="crm-summary-value">${meetings}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Дедлайны задач</div><div class="crm-summary-value">${tasks}</div></div>
        <div class="crm-summary-card"><div class="crm-summary-label">Этапы проектов</div><div class="crm-summary-value">${projects}</div><div class="crm-summary-meta">${overdue} критичных точек</div></div>
    `;
}

function renderCalendarSidebar(items) {
    const mount = document.getElementById('calendarSidebarList');
    if (!mount) return;
    mount.innerHTML = items.length
        ? items.slice(0, 16).map(item => `
            <button class="calendar-list-item" onclick="openCalendarItem('${item.kind}', ${Number(item.id || 0)}, ${Number(item.projectId || 0)})">
                <div class="calendar-list-item__main">
                    <div class="calendar-list-item__title">${item.title}</div>
                    <div class="calendar-list-item__meta">${calendarKindLabel(item.kind)} · ${item.date}${item.time ? ` · ${item.time}` : ''}</div>
                    <div class="calendar-list-item__sub">${item.meta || item.description || 'Без комментария'}</div>
                </div>
                <span class="crm-inline-pill crm-inline-pill--${calendarTone(item)}">${calendarKindLabel(item.kind)}</span>
            </button>
        `).join('')
        : '<div class="empty-state">В этом диапазоне записей нет.</div>';
}

function renderCalendarMonthBoard(items) {
    const start = new Date(currentCalendarAnchorDate.getFullYear(), currentCalendarAnchorDate.getMonth(), 1);
    const gridStart = calendarStartOfWeek(start);
    const cells = [];
    for (let offset = 0; offset < 42; offset += 1) {
        const day = calendarCloneDate(gridStart);
        day.setDate(day.getDate() + offset);
        const dayKey = calendarFormatDate(day);
        const dayItems = items.filter(item => item.date === dayKey);
        const isForeign = day.getMonth() !== currentCalendarAnchorDate.getMonth();
        cells.push(`
            <div class="calendar-month-cell ${isForeign ? 'is-foreign' : ''}">
                <div class="calendar-month-cell__head">
                    <span>${day.getDate()}</span>
                    <span>${dayItems.length ? dayItems.length : ''}</span>
                </div>
                <div class="calendar-month-cell__items">
                    ${dayItems.slice(0, 4).map(item => `
                        <button class="calendar-chip calendar-chip--${calendarTone(item)}" onclick="openCalendarItem('${item.kind}', ${Number(item.id || 0)}, ${Number(item.projectId || 0)})">
                            ${item.time ? `${item.time} · ` : ''}${item.title}
                        </button>
                    `).join('')}
                    ${dayItems.length > 4 ? `<div class="calendar-month-cell__more">+ ещё ${dayItems.length - 4}</div>` : ''}
                </div>
            </div>
        `);
    }
    return `
        <div class="calendar-month-grid">
            ${['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(day => `<div class="calendar-month-grid__day">${day}</div>`).join('')}
            ${cells.join('')}
        </div>
    `;
}

function renderCalendarWeekBoard(items) {
    const start = calendarStartOfWeek(currentCalendarAnchorDate);
    const days = [];
    for (let index = 0; index < 7; index += 1) {
        const date = calendarCloneDate(start);
        date.setDate(date.getDate() + index);
        const key = calendarFormatDate(date);
        const dayItems = items.filter(item => item.date === key);
        days.push(`
            <section class="calendar-day-column">
                <div class="calendar-day-column__head">
                    <strong>${['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][index]}</strong>
                    <span>${key}</span>
                </div>
                <div class="calendar-day-column__items">
                    ${dayItems.length ? dayItems.map(item => `
                        <button class="calendar-stack-item calendar-stack-item--${calendarTone(item)}" onclick="openCalendarItem('${item.kind}', ${Number(item.id || 0)}, ${Number(item.projectId || 0)})">
                            <div class="calendar-stack-item__title">${item.title}</div>
                            <div class="calendar-stack-item__meta">${item.time || 'весь день'} · ${calendarKindLabel(item.kind)}</div>
                        </button>
                    `).join('') : '<div class="empty-state">Пусто</div>'}
                </div>
            </section>
        `);
    }
    return `<div class="calendar-week-grid">${days.join('')}</div>`;
}

function renderCalendarDayBoard(items) {
    const key = calendarFormatDate(currentCalendarAnchorDate);
    const dayItems = items.filter(item => item.date === key);
    return `
        <div class="calendar-schedule-list">
            ${dayItems.length ? dayItems.map(item => `
                <button class="calendar-schedule-item calendar-schedule-item--${calendarTone(item)}" onclick="openCalendarItem('${item.kind}', ${Number(item.id || 0)}, ${Number(item.projectId || 0)})">
                    <div class="calendar-schedule-item__time">${item.time || 'весь день'}</div>
                    <div class="calendar-schedule-item__body">
                        <div class="calendar-schedule-item__title">${item.title}</div>
                        <div class="calendar-schedule-item__meta">${calendarKindLabel(item.kind)} · ${item.meta || 'без описания'}</div>
                    </div>
                </button>
            `).join('') : '<div class="empty-state">На выбранный день ничего не запланировано.</div>'}
        </div>
    `;
}

function renderCalendarScheduleBoard(items) {
    const groups = {};
    items.forEach(item => {
        groups[item.date] = groups[item.date] || [];
        groups[item.date].push(item);
    });
    return Object.keys(groups).length
        ? `<div class="calendar-schedule-groups">${Object.keys(groups).sort((a, b) => (calendarParseDate(a)?.getTime() || 0) - (calendarParseDate(b)?.getTime() || 0)).map(date => `
            <section class="calendar-schedule-group">
                <div class="calendar-schedule-group__title">${date}</div>
                <div class="calendar-schedule-list">
                    ${groups[date].map(item => `
                        <button class="calendar-schedule-item calendar-schedule-item--${calendarTone(item)}" onclick="openCalendarItem('${item.kind}', ${Number(item.id || 0)}, ${Number(item.projectId || 0)})">
                            <div class="calendar-schedule-item__time">${item.time || 'весь день'}</div>
                            <div class="calendar-schedule-item__body">
                                <div class="calendar-schedule-item__title">${item.title}</div>
                                <div class="calendar-schedule-item__meta">${calendarKindLabel(item.kind)} · ${item.meta || 'без описания'}</div>
                            </div>
                        </button>
                    `).join('')}
                </div>
            </section>
        `).join('')}</div>`
        : '<div class="empty-state">В расписании пока нет записей.</div>';
}

async function renderMeetings() {
    if (!Array.isArray(calendarEventsDB) || !calendarEventsDB.length) {
        await loadCalendarEvents();
    }
    fillCalendarDepartmentFilter();
    const rangeLabel = document.getElementById('calendarRangeLabel');
    if (rangeLabel) rangeLabel.innerText = calendarRangeLabel();
    ['day', 'week', 'month', 'schedule'].forEach(mode => {
        document.getElementById(`calendarMode${mode.charAt(0).toUpperCase()}${mode.slice(1)}`)?.classList.toggle('active', currentCalendarMode === mode);
    });
    [
        ['All', 'all'],
        ['Personal', 'personal'],
        ['Shared', 'shared'],
        ['Department', 'department'],
        ['Meetings', 'meetings'],
        ['Tasks', 'tasks'],
        ['Projects', 'projects'],
    ].forEach(([suffix, value]) => {
        document.getElementById(`calendarFilter${suffix}`)?.classList.toggle('active', currentCalendarFilter === value);
    });

    const items = calendarItemsInRange(calendarBuildItems());
    renderCalendarSummary(items);
    renderCalendarSidebar(items);

    const board = document.getElementById('calendarBoardMount');
    if (!board) return;
    if (currentCalendarMode === 'day') board.innerHTML = renderCalendarDayBoard(items);
    else if (currentCalendarMode === 'week') board.innerHTML = renderCalendarWeekBoard(items);
    else if (currentCalendarMode === 'schedule') board.innerHTML = renderCalendarScheduleBoard(items);
    else board.innerHTML = renderCalendarMonthBoard(items);
}

function setCalendarMode(mode) {
    currentCalendarMode = mode || 'month';
    renderMeetings();
}

function setCalendarFilter(filter) {
    currentCalendarFilter = filter || 'all';
    renderMeetings();
}

function setCalendarDepartmentFilter(department) {
    currentCalendarDepartment = String(department || '').trim();
    renderMeetings();
}

function shiftCalendarRange(step) {
    const shift = Number(step || 0);
    if (currentCalendarMode === 'day') currentCalendarAnchorDate.setDate(currentCalendarAnchorDate.getDate() + shift);
    else if (currentCalendarMode === 'week') currentCalendarAnchorDate.setDate(currentCalendarAnchorDate.getDate() + shift * 7);
    else if (currentCalendarMode === 'schedule') currentCalendarAnchorDate.setDate(currentCalendarAnchorDate.getDate() + shift * 14);
    else currentCalendarAnchorDate.setMonth(currentCalendarAnchorDate.getMonth() + shift);
    renderMeetings();
}

function resetCalendarToday() {
    currentCalendarAnchorDate = new Date();
    renderMeetings();
}

function fillCalendarEventProjectOptions(selectedId = 0) {
    const select = document.getElementById('calendarEventProject');
    if (!select) return;
    select.innerHTML = `<option value="0">Без проекта</option>${(projectsDB || []).map(project => `
        <option value="${project.id}" ${Number(project.id || 0) === Number(selectedId || 0) ? 'selected' : ''}>${project.name || project.contract || `Проект #${project.id}`}</option>
    `).join('')}`;
}

function fillCalendarEventMeetingOptions(selectedId = 0) {
    const select = document.getElementById('calendarEventMeeting');
    if (!select) return;
    select.innerHTML = `<option value="0">Без совещания</option>${(meetingsDB || []).map(meeting => `
        <option value="${meeting.id}" ${Number(meeting.id || 0) === Number(selectedId || 0) ? 'selected' : ''}>${meeting.m_date || ''} · ${meeting.title || `Совещание #${meeting.id}`}</option>
    `).join('')}`;
}

function openCalendarEventModal(eventId = 0) {
    editingCalendarEventId = Number(eventId || 0);
    const row = (calendarEventsDB || []).find(item => Number(item.id || 0) === editingCalendarEventId) || {};
    fillCalendarEventProjectOptions(row.project_id || 0);
    fillCalendarEventMeetingOptions(row.meeting_id || 0);
    document.getElementById('calendarEventModalTitle').innerText = editingCalendarEventId ? 'Изменить событие' : 'Новое событие';
    document.getElementById('calendarEventTitle').value = row.title || '';
    document.getElementById('calendarEventDate').value = row.event_date || calendarFormatDate(currentCalendarAnchorDate);
    document.getElementById('calendarEventStartTime').value = row.start_time || '';
    document.getElementById('calendarEventEndTime').value = row.end_time || '';
    document.getElementById('calendarEventScope').value = row.scope || 'personal';
    document.getElementById('calendarEventDepartment').value = row.department || (currentUser?.role || '');
    document.getElementById('calendarEventProject').value = String(row.project_id || 0);
    document.getElementById('calendarEventMeeting').value = String(row.meeting_id || 0);
    document.getElementById('calendarEventLocation').value = row.location || '';
    document.getElementById('calendarEventStatus').value = row.status || 'planned';
    document.getElementById('calendarEventDescription').value = row.description || '';
    document.getElementById('calendarEventDeleteBtn').style.display = editingCalendarEventId ? 'inline-flex' : 'none';
    flatpickr('#calendarEventDate', { locale: 'ru', dateFormat: 'd.m.Y' });
    document.getElementById('calendarEventModal').style.display = 'flex';
}

function closeCalendarEventModal() {
    editingCalendarEventId = 0;
    const modal = document.getElementById('calendarEventModal');
    if (modal) modal.style.display = 'none';
}

async function saveCalendarEvent() {
    const payload = {
        title: document.getElementById('calendarEventTitle')?.value?.trim() || '',
        event_date: document.getElementById('calendarEventDate')?.value?.trim() || '',
        start_time: document.getElementById('calendarEventStartTime')?.value || '',
        end_time: document.getElementById('calendarEventEndTime')?.value || '',
        scope: document.getElementById('calendarEventScope')?.value || 'personal',
        department: document.getElementById('calendarEventDepartment')?.value?.trim() || '',
        project_id: Number(document.getElementById('calendarEventProject')?.value || 0),
        meeting_id: Number(document.getElementById('calendarEventMeeting')?.value || 0),
        status: document.getElementById('calendarEventStatus')?.value || 'planned',
        location: document.getElementById('calendarEventLocation')?.value?.trim() || '',
        description: document.getElementById('calendarEventDescription')?.value?.trim() || '',
        owner_email: currentUser?.email || '',
        owner_name: currentUser?.name || '',
    };
    if (!payload.title || !payload.event_date) return customAlert('Укажи название и дату события.');
    const res = editingCalendarEventId
        ? await apiCall(`/calendar/events/${editingCalendarEventId}`, 'PUT', payload)
        : await apiCall('/calendar/events', 'POST', payload);
    if (!res || res.error) return customAlert(res?.message || 'Не удалось сохранить событие.');
    await loadCalendarEvents();
    closeCalendarEventModal();
    renderMeetings();
}

async function deleteCalendarEvent() {
    if (!editingCalendarEventId) return;
    if (!(await customConfirm('Удалить событие из календаря?'))) return;
    const res = await apiCall(`/calendar/events/${editingCalendarEventId}`, 'DELETE');
    if (!res || res.error) return customAlert(res?.message || 'Не удалось удалить событие.');
    await loadCalendarEvents();
    closeCalendarEventModal();
    renderMeetings();
}

function openCalendarItem(kind, id, projectId = 0) {
    if (kind === 'event') return openCalendarEventModal(id);
    if (kind === 'meeting') return openProtocol(id);
    if (kind === 'task') return navigateTo('tasks');
    if (kind === 'project') return openProject(projectId || id);
}

window.setCalendarMode = setCalendarMode;
window.setCalendarFilter = setCalendarFilter;
window.setCalendarDepartmentFilter = setCalendarDepartmentFilter;
window.shiftCalendarRange = shiftCalendarRange;
window.resetCalendarToday = resetCalendarToday;
window.openCalendarEventModal = openCalendarEventModal;
window.closeCalendarEventModal = closeCalendarEventModal;
window.saveCalendarEvent = saveCalendarEvent;
window.deleteCalendarEvent = deleteCalendarEvent;
window.openCalendarItem = openCalendarItem;

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
