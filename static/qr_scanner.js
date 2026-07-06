let html5QrcodeScanner;
let currentPrintDocId = null;

function getDocumentFromCache(id) {
    return Array.isArray(documentsDB) ? documentsDB.find(x => Number(x.id) === Number(id)) : null;
}

function parseDocumentQrPayload(decodedText) {
    const raw = String(decodedText || '').trim();
    if (!raw) return null;
    try {
        const data = JSON.parse(raw);
        if (data && data.type === 'doc' && data.id) {
            return { id: Number(data.id), source: 'legacy-json' };
        }
    } catch (e) {}
    try {
        const url = new URL(raw, window.location.origin);
        const match = url.pathname.match(/\/qr\/doc\/(\d+)\/?$/);
        if (match) {
            return {
                id: Number(match[1]),
                source: 'url',
                url: url.toString(),
                token: url.searchParams.get('token') || '',
            };
        }
    } catch (e) {}
    return null;
}

async function ensureDocumentAvailable(id) {
    let doc = getDocumentFromCache(id);
    if (doc) return doc;
    if (typeof loadDocuments === 'function') {
        await loadDocuments();
        doc = getDocumentFromCache(id);
    }
    return doc || null;
}

async function getDocumentFileUrl(id) {
    const doc = await ensureDocumentAvailable(id);
    if (doc && doc.file_url) return doc.file_url;
    if (typeof apiCall !== 'function') return '';
    const res = await apiCall(`/docflow/documents/${Number(id)}/file_versions`);
    if (!res || res.error) return '';
    const activeFileUrl = res.active_revision?.file_url || res.document?.file_url || '';
    if (activeFileUrl && doc) doc.file_url = activeFileUrl;
    return activeFileUrl;
}

function openScannedDocumentFile(targetUrl) {
    if (!targetUrl) return false;
    const normalized = String(targetUrl).trim();
    const canOpenDirectly = normalized.startsWith('/uploads/') || /^https?:\/\//i.test(normalized);
    if (!canOpenDirectly) return false;
    const isMobileMode = typeof window.isMobileWorkspaceMode === 'function' && window.isMobileWorkspaceMode();
    if (isMobileMode) {
        window.location.href = normalized;
        return true;
    }
    const popup = window.open(normalized, '_blank', 'noopener,noreferrer');
    if (!popup) {
        window.location.href = normalized;
    }
    return true;
}

async function openDocumentFromQr(documentId) {
    const fileUrl = await getDocumentFileUrl(documentId);
    if (fileUrl) {
        return openScannedDocumentFile(fileUrl);
    }
    const doc = await ensureDocumentAvailable(documentId);
    if (!doc) {
        customAlert("Документ не найден в базе.");
        return false;
    }
    openPrintDoc(documentId);
    return true;
}

function renderPrintDocResolution(doc) {
    const block = document.getElementById('printDocResolutionBlock');
    const authorEl = document.getElementById('printDocResolutionAuthor');
    const assigneeEl = document.getElementById('printDocResolutionAssignee');
    const deadlineEl = document.getElementById('printDocResolutionDeadline');
    const textEl = document.getElementById('printDocResolutionText');
    const taskWrapEl = document.getElementById('printDocResolutionTaskWrap');
    const taskEl = document.getElementById('printDocResolutionTask');
    if (!block || !authorEl || !assigneeEl || !deadlineEl || !textEl || !taskWrapEl || !taskEl) return;

    if (!doc || !doc.resolution) {
        block.style.display = 'none';
        authorEl.innerText = '—';
        assigneeEl.innerText = '—';
        deadlineEl.innerText = '—';
        taskWrapEl.style.display = 'none';
        taskEl.innerText = '—';
        textEl.innerHTML = '';
        return;
    }

    block.style.display = 'block';
    authorEl.innerText = doc.resolution_author || 'Не указан';
    assigneeEl.innerText = doc.resolution_assignee || 'Не указан';
    deadlineEl.innerText = doc.resolution_deadline || 'Не указан';
    taskWrapEl.style.display = doc.resolution_task_id ? 'block' : 'none';
    taskEl.innerText = doc.resolution_task_id ? `#${doc.resolution_task_id}` : '—';
    textEl.innerHTML = nl2brSafe(doc.resolution);
}

function customTextareaPrompt(title, label, defaultValue = '') {
    return new Promise(resolve => {
        const modal = document.getElementById('genericModal');
        if (!modal) {
            resolve(window.prompt(label, defaultValue));
            return;
        }
        document.getElementById('genModalTitle').innerText = title;
        document.getElementById('genModalBody').innerHTML = `
            <label style="font-size:13px; margin-bottom:8px; display:block;">${nl2brSafe(label)}</label>
            <textarea id="genTextarea" class="auth-input" style="margin:0; min-height:140px; resize:vertical;">${escapeHtml(defaultValue)}</textarea>
        `;
        document.getElementById('genModalFooter').innerHTML = `
            <button class="btn-secondary" id="genCancel">Отмена</button>
            <button class="btn-primary" id="genSubmit">Сохранить</button>
        `;
        modal.style.display = 'flex';
        const input = document.getElementById('genTextarea');
        input.focus();
        document.getElementById('genCancel').onclick = () => {
            modal.style.display = 'none';
            resolve(null);
        };
        document.getElementById('genSubmit').onclick = () => {
            modal.style.display = 'none';
            resolve(input.value);
        };
    });
}

function openScanner() {
    document.getElementById('scannerModal').style.display = 'flex';
    
    // Инициализация сканера (запрашивает доступ к камере)
    html5QrcodeScanner = new Html5QrcodeScanner("qr-reader", { 
        fps: 10, 
        qrbox: { width: 250, height: 250 },
        rememberLastUsedCamera: true
    }, false);
    
    html5QrcodeScanner.render(onScanSuccess, onScanFailure);
}

function closeScanner() {
    if (html5QrcodeScanner) {
        html5QrcodeScanner.clear();
    }
    document.getElementById('scannerModal').style.display = 'none';
}

function onScanSuccess(decodedText, decodedResult) {
    const parsed = parseDocumentQrPayload(decodedText);
    if (!parsed || !parsed.id) {
        customAlert("QR-код распознан, но он не принадлежит нашей системе.");
        return;
    }
    closeScanner();
    openDocumentFromQr(parsed.id);
}

function onScanFailure(error) {
    // Ошибки сканирования происходят каждый кадр, пока код не найден. Просто игнорируем.
}

// Функция открытия печатной формы документа из любого места
window.openPrintDoc = function(id) {
    const d = getDocumentFromCache(id);
    if (!d) {
        customAlert("Документ не найден в базе.");
        return;
    }
    currentPrintDocId = id;
    
    document.getElementById('printDocTitle').innerText = `Документ № ${d.number}`;
    document.getElementById('printDocDate').innerText = d.d_date || 'Не указана';
    document.getElementById('printDocCorr').innerText = d.correspondent || 'Не указан';
    document.getElementById('printDocSubj').innerText = d.subject || '';
    
    const qrImg = document.getElementById('printDocQr');
    if (d.qr_code) {
        qrImg.src = d.qr_code;
        qrImg.style.display = 'block';
    } else {
        qrImg.style.display = 'none';
    }
    const openFileBtn = document.getElementById('printDocOpenFileBtn');
    if (openFileBtn) {
        if (d.file_url) {
            openFileBtn.style.display = 'inline-flex';
            openFileBtn.onclick = () => openScannedDocumentFile(d.file_url);
        } else {
            openFileBtn.style.display = 'none';
            openFileBtn.onclick = null;
        }
    }
    renderPrintDocResolution(d);
    
    document.getElementById('printDocModal').style.display = 'flex';
};

window.openDocResolution = async function() {
    const doc = documentsDB.find(item => item.id === currentPrintDocId);
    if (!doc) {
        return customAlert('Сначала откройте карточку документа.');
    }
    const modal = document.getElementById('genericModal');
    if (!modal) {
        return customAlert('Не удалось открыть редактор резолюции.');
    }
    const approvedUsers = (Array.isArray(allUsersDB) ? allUsersDB : []).filter(user => user.status === 'approved');
    const assigneeOptions = approvedUsers.map(user => {
        const selected = user.name === (doc.resolution_assignee || '') ? 'selected' : '';
        return `<option value="${escapeHtml(user.name)}" ${selected}>${escapeHtml(user.name)} (${escapeHtml(user.role || 'роль не указана')})</option>`;
    }).join('');
    document.getElementById('genModalTitle').innerText = 'Резолюция и поручение';
    document.getElementById('genModalBody').innerHTML = `
        <div style="display:grid; gap:12px;">
            <div>
                <label style="display:block; font-size:12px; color:var(--secondary); margin-bottom:6px;">Исполнитель</label>
                <select id="resolutionAssigneeInput" class="auth-input" style="margin:0; appearance:auto;">
                    <option value="">Не назначен</option>
                    ${assigneeOptions}
                </select>
            </div>
            <div>
                <label style="display:block; font-size:12px; color:var(--secondary); margin-bottom:6px;">Срок исполнения</label>
                <input id="resolutionDeadlineInput" class="auth-input" style="margin:0;" placeholder="дд.мм.гггг" value="${escapeHtml(doc.resolution_deadline || '')}">
            </div>
            <div>
                <label style="display:block; font-size:12px; color:var(--secondary); margin-bottom:6px;">Текст резолюции</label>
                <textarea id="resolutionTextInput" class="auth-input" style="margin:0; min-height:160px; resize:vertical;">${escapeHtml(doc.resolution || '')}</textarea>
            </div>
            <div style="font-size:12px; color:var(--secondary);">
                После сохранения система автоматически создаст или обновит поручение по документу и уведомит исполнителя.
            </div>
        </div>
    `;
    document.getElementById('genModalFooter').innerHTML = `
        <button class="btn-secondary" id="genCancel">Отмена</button>
        <button class="btn-primary" id="genSubmit">Сохранить</button>
    `;
    modal.style.display = 'flex';

    const assigneeInput = document.getElementById('resolutionAssigneeInput');
    const deadlineInput = document.getElementById('resolutionDeadlineInput');
    const textInput = document.getElementById('resolutionTextInput');
    textInput.focus();

    const modalResult = await new Promise(resolve => {
        document.getElementById('genCancel').onclick = () => {
            modal.style.display = 'none';
            resolve(null);
        };
        document.getElementById('genSubmit').onclick = () => {
            modal.style.display = 'none';
            resolve({
                assignee: assigneeInput.value.trim(),
                deadline: deadlineInput.value.trim(),
                text: textInput.value.trim(),
            });
        };
    });
    if (!modalResult) return;
    if (!modalResult.text) {
        return customAlert('Заполните текст резолюции.');
    }
    if (!modalResult.assignee) {
        return customAlert('Укажите исполнителя, чтобы поручение было создано автоматически.');
    }

    const payload = {
        type: doc.type,
        number: doc.number,
        d_date: doc.d_date || '',
        correspondent: doc.correspondent || '',
        subject: doc.subject || '',
        status: doc.status || 'registered',
        project_id: doc.project_id || 0,
        parent_id: doc.parent_id || 0,
        priority: doc.priority || 'normal',
        resolution: modalResult.text,
        resolution_author: currentUser?.name || doc.resolution_author || '',
        resolution_assignee: modalResult.assignee,
        resolution_deadline: modalResult.deadline,
    };

    const res = await apiCall(`/documents/${doc.id}`, 'PUT', payload);
    if (!res || res.error) {
        return customAlert('Не удалось сохранить резолюцию.');
    }

    Object.assign(doc, payload);
    doc.resolution_task_id = Number(res.resolution_task_id || 0);
    renderPrintDocResolution(doc);
    showToast('Документ', doc.resolution_task_id ? `Резолюция сохранена, поручение #${doc.resolution_task_id} обновлено` : 'Резолюция сохранена');
};
