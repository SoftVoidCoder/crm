// ==========================================
// COMMUNICATION HUB: FEED + CHATS
// ==========================================

let globalChats = [];
let currentGlobalChatId = null;
let currentMessageCount = 0;
let messengerActiveTab = 'feed';
let companyFeedDB = [];
let currentFeedPostType = 'announcement';
let currentFeedRoleFilter = 'all';
let currentFeedReadFilter = 'all';

function feedFormatDateTime(timestamp) {
    const date = new Date(Number(timestamp || 0) * 1000);
    if (Number.isNaN(date.getTime())) return '—';
    return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function messengerSwitchTab(tab) {
    messengerActiveTab = tab;
    const feedPane = document.getElementById('messengerFeedPane');
    const chatsPane = document.getElementById('messengerChatsPane');
    const feedBtn = document.getElementById('messengerTabFeed');
    const chatsBtn = document.getElementById('messengerTabChats');
    if (feedPane) feedPane.style.display = tab === 'feed' ? 'block' : 'none';
    if (chatsPane) chatsPane.style.display = tab === 'chats' ? 'block' : 'none';
    if (feedBtn) feedBtn.classList.toggle('active', tab === 'feed');
    if (chatsBtn) chatsBtn.classList.toggle('active', tab === 'chats');
    if (tab === 'feed') loadCompanyFeed();
    else loadGlobalChats();
}

function getGlobalChatMeta(chat) {
    if (chat.type === 'system') return 'Системный канал компании';
    if (chat.type === 'role') return 'Групповой канал подразделения';
    return 'Пользовательский диалог и рабочая координация';
}

function getGlobalChatKindLabel(chat) {
    if (chat.type === 'system') return 'Компания';
    if (chat.type === 'role') return 'Отдел';
    return 'Частный';
}

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
    const sysChats = globalChats.filter(chat => chat.type === 'system' || chat.type === 'role');
    if (sysChats.length > 0) {
        html += '<div class="crm-chat-group-label">Системные чаты</div>';
        sysChats.forEach(chat => {
            const icon = chat.type === 'system'
                ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect></svg>'
                : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path></svg>';
            html += `
                <div class="chat-list-item ${chat.id === currentGlobalChatId ? 'active' : ''}" onclick="openGlobalChat(${chat.id})">
                    <div class="chat-avatar">${icon}</div>
                    <div class="crm-chat-row__body">
                        <div class="crm-chat-row__title-line">
                            <div class="crm-chat-row__title">${escapeHtml(chat.name)}</div>
                            <span class="crm-chat-row__chip crm-chat-row__chip--${chat.type === 'system' ? 'system' : 'role'}">${escapeHtml(getGlobalChatKindLabel(chat))}</span>
                        </div>
                        <div class="crm-chat-row__meta">${getGlobalChatMeta(chat)}</div>
                    </div>
                </div>
            `;
        });
    }

    const customChats = globalChats.filter(chat => chat.type === 'custom');
    if (customChats.length > 0) {
        html += '<div class="crm-chat-group-label">Мои чаты</div>';
        customChats.forEach(chat => {
            const participantCount = Array.isArray(chat.participants) ? chat.participants.length : 0;
            html += `
                <div class="chat-list-item ${chat.id === currentGlobalChatId ? 'active' : ''}" onclick="openGlobalChat(${chat.id})">
                    <div class="chat-avatar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg></div>
                    <div class="crm-chat-row__body">
                        <div class="crm-chat-row__title-line">
                            <div class="crm-chat-row__title">${escapeHtml(chat.name)}</div>
                            <span class="crm-chat-row__chip crm-chat-row__chip--custom">${escapeHtml(getGlobalChatKindLabel(chat))}</span>
                        </div>
                        <div class="crm-chat-row__meta">${getGlobalChatMeta(chat)}${participantCount ? ` · ${participantCount} участников` : ''}</div>
                    </div>
                </div>
            `;
        });
    }
    container.innerHTML = html;
}

async function openGlobalChat(id) {
    currentGlobalChatId = id;
    renderGlobalChats();
    const chat = globalChats.find(item => item.id === id);
    if (!chat) return;

    document.getElementById('mChatTitle').innerText = chat.name;
    document.getElementById('messengerInputArea').style.display = 'flex';
    document.getElementById('messengerMessages').innerHTML = '<div class="crm-chat-empty-state">Загрузка сообщений...</div>';

    const btnDel = document.getElementById('btnDeleteChat');
    if (chat.type === 'custom' && (chat.creator === currentUser.name || currentUser.role === 'Директор')) btnDel.style.display = 'block';
    else btnDel.style.display = 'none';

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
    const container = document.getElementById('messengerMessages');
    if (!container) return;
    if (!messages.length) {
        container.innerHTML = '<div class="crm-chat-empty-state">Здесь пока нет сообщений. Напишите первым.</div>';
        return;
    }
    const isScrolledToBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 50;
    container.innerHTML = messages.map(message => `
        <div class="chat-msg ${message.user === currentUser.name ? 'my-msg' : ''}">
            <div class="chat-msg-meta"><span>${escapeHtml(message.user)} (${escapeHtml(message.role)})</span><span>${escapeHtml(message.time || '')}</span></div>
            <div class="chat-msg-bubble">${nl2brSafe(message.text || '')}</div>
        </div>
    `).join('');
    if (isScrolledToBottom) container.scrollTop = container.scrollHeight;
}

async function sendGlobalMessage() {
    const input = document.getElementById('messengerInput');
    const text = input.value.trim();
    if (!text || !currentGlobalChatId) return;
    input.value = '';
    await apiCall(`/chats/${currentGlobalChatId}/messages`, 'POST', { user: currentUser.name, role: currentUser.role, text });
    await loadGlobalMessages(currentGlobalChatId, true);
}

function openCreateChatModal() {
    const usersDiv = document.getElementById('newChatUsers');
    if (usersDiv) {
        usersDiv.innerHTML = allUsersDB.filter(user => user.name !== currentUser.name).map(user =>
            `<label style="display:flex; gap:8px; align-items:center; margin-bottom:6px; cursor:pointer;"><input type="checkbox" value="${escapeHtml(user.name)}" class="new-chat-cb"> <b>${escapeHtml(user.name)}</b> <span style="color:var(--secondary)">(${escapeHtml(user.role)})</span></label>`
        ).join('');
    }
    document.getElementById('createChatModal').style.display = 'flex';
}

async function submitNewChat() {
    const name = document.getElementById('newChatName').value.trim();
    if (!name) return customAlert("Введите название чата");
    const cbs = document.querySelectorAll('.new-chat-cb:checked');
    const participants = Array.from(cbs).map(cb => cb.value);
    participants.push(currentUser.name);
    await apiCall('/chats', 'POST', { name, creator: currentUser.name, participants });
    document.getElementById('createChatModal').style.display = 'none';
    await loadGlobalChats();
    messengerSwitchTab('chats');
}

async function deleteCurrentChat() {
    if (!currentGlobalChatId) return;
    if (!(await customConfirm("Удалить этот чат без возможности восстановления?"))) return;
    await apiCall(`/chats/${currentGlobalChatId}`, 'DELETE');
    currentGlobalChatId = null;
    document.getElementById('mChatTitle').innerText = "Выберите чат слева";
    document.getElementById('messengerInputArea').style.display = 'none';
    document.getElementById('messengerMessages').innerHTML = '<div class="crm-chat-empty-state">Выберите чат слева или создайте новый рабочий канал.</div>';
    document.getElementById('btnDeleteChat').style.display = 'none';
    await loadGlobalChats();
}

function setFeedPostType(type) {
    currentFeedPostType = type;
    const announcement = document.getElementById('feedTypeAnnouncement');
    const poll = document.getElementById('feedTypePoll');
    const options = document.getElementById('feedPollOptions');
    if (announcement) announcement.classList.toggle('is-active', type === 'announcement');
    if (poll) poll.classList.toggle('is-active', type === 'poll');
    if (options) options.style.display = type === 'poll' ? 'grid' : 'none';
}

function hydrateFeedRoleControls() {
    const roles = ['Все отделы'].concat((availableRoles || []).filter(role => role !== 'Сотрудник'));
    const select = document.getElementById('feedRoleFilter');
    if (select) {
        select.innerHTML = '<option value="all">Все отделы</option>' + roles.filter(role => role !== 'Все отделы').map(role => `<option value="${escapeHtml(role)}">${escapeHtml(role)}</option>`).join('');
    }
    const target = document.getElementById('feedTargetRoles');
    if (target) {
        target.innerHTML = (availableRoles || []).filter(role => role !== 'Сотрудник').map(role => `
            <label class="feed-role-chip">
                <input type="checkbox" value="${escapeHtml(role)}" class="feed-role-checkbox">
                <span>${escapeHtml(role)}</span>
            </label>
        `).join('');
    }
}

async function loadCompanyFeed() {
    hydrateFeedRoleControls();
    const data = await apiCall('/feed/posts');
    companyFeedDB = Array.isArray(data) ? data : [];
    renderCompanyFeed();
}

function feedVisiblePosts() {
    return companyFeedDB.filter(post => {
        if (currentFeedRoleFilter !== 'all' && !(Array.isArray(post.target_roles) && post.target_roles.includes(currentFeedRoleFilter))) return false;
        if (currentFeedReadFilter === 'unread' && Number(post.is_read || 0) === 1) return false;
        if (currentFeedReadFilter === 'pinned' && Number(post.is_pinned || 0) !== 1) return false;
        return true;
    });
}

function renderFeedStats(posts) {
    const mount = document.getElementById('feedQuickStats');
    if (!mount) return;
    const unread = posts.filter(post => Number(post.is_read || 0) === 0).length;
    const polls = posts.filter(post => post.post_type === 'poll').length;
    const pins = posts.filter(post => Number(post.is_pinned || 0) === 1).length;
    mount.innerHTML = `
        <div class="feed-stat"><span>Непрочитано</span><b>${unread}</b></div>
        <div class="feed-stat"><span>Опросы</span><b>${polls}</b></div>
        <div class="feed-stat"><span>Закрепы</span><b>${pins}</b></div>
    `;
}

function reactionCount(post, key) {
    const reactions = Array.isArray(post.reactions) ? post.reactions : [];
    const found = reactions.find(item => item.reaction_key === key);
    return Number(found?.total || 0);
}

function renderCompanyFeed() {
    const posts = feedVisiblePosts();
    const list = document.getElementById('companyFeedList');
    if (!list) return;
    renderFeedStats(companyFeedDB);
    if (!posts.length) {
        list.innerHTML = '<div class="task-center-empty">Под выбранные фильтры в ленте пока ничего нет.</div>';
        return;
    }
    list.innerHTML = posts.map(post => `
        <article class="feed-post ${Number(post.is_pinned || 0) === 1 ? 'is-pinned' : ''}" onclick="markFeedPostRead(${post.id})">
            <div class="feed-post__head">
                <div>
                    <div class="feed-post__title-row">
                        <span class="feed-post__type feed-post__type--${escapeHtml(post.post_type || 'announcement')}">${post.post_type === 'poll' ? 'Опрос' : 'Объявление'}</span>
                        ${Number(post.is_pinned || 0) === 1 ? '<span class="feed-post__pin">Закреплено</span>' : ''}
                        ${Number(post.is_read || 0) === 0 ? '<span class="feed-post__unread">Не прочитано</span>' : ''}
                    </div>
                    <div class="feed-post__title">${escapeHtml(post.title || 'Без заголовка')}</div>
                    <div class="feed-post__meta">${escapeHtml(post.author_name || '')} · ${escapeHtml(post.author_role || '')} · ${escapeHtml(feedFormatDateTime(post.updated_at))}</div>
                </div>
                <div class="feed-post__head-actions">
                    ${currentUser?.role === 'Директор' ? `<button class="btn-secondary" onclick="event.stopPropagation(); toggleFeedPin(${post.id}, ${Number(post.is_pinned || 0) ? 0 : 1})">${Number(post.is_pinned || 0) ? 'Открепить' : 'Закрепить'}</button>` : ''}
                </div>
            </div>
            <div class="feed-post__body">${nl2brSafe(post.content || '')}</div>
            ${(Array.isArray(post.target_roles) && post.target_roles.length) ? `<div class="feed-post__targets">${post.target_roles.map(role => `<span class="feed-target-pill">${escapeHtml(role)}</span>`).join('')}</div>` : ''}
            ${post.post_type === 'poll' ? `
                <div class="feed-poll">
                    ${(post.poll_options || []).map(option => `
                        <button class="feed-poll-option ${post.my_vote === option.id ? 'is-selected' : ''}" onclick="event.stopPropagation(); voteFeedPost(${post.id}, '${escapeHtml(option.id)}')">
                            <span>${escapeHtml(option.label || '')}</span>
                            <b>${Number(option.votes || 0)}</b>
                        </button>
                    `).join('')}
                </div>
            ` : ''}
            <div class="feed-post__reactions">
                ${['like', 'fire', 'check'].map(reaction => `
                    <button class="feed-reaction ${post.my_reaction === reaction ? 'is-active' : ''}" onclick="event.stopPropagation(); reactToFeedPost(${post.id}, '${reaction}')">
                        <span>${reaction === 'like' ? '👍' : reaction === 'fire' ? '🔥' : '✅'}</span>
                        <b>${reactionCount(post, reaction)}</b>
                    </button>
                `).join('')}
            </div>
            <div class="feed-post__comments">
                ${(post.comments || []).map(comment => `
                    <div class="feed-comment">
                        <div class="feed-comment__meta">${escapeHtml(comment.user_name || '')} · ${escapeHtml(comment.user_role || '')} · ${escapeHtml(feedFormatDateTime(comment.created_at))}</div>
                        <div class="feed-comment__text">${nl2brSafe(comment.comment_text || '')}</div>
                    </div>
                `).join('') || '<div class="task-center-empty task-center-empty--small">Комментариев пока нет</div>'}
            </div>
            <div class="feed-post__compose">
                <input id="feedComment_${post.id}" type="text" class="auth-input" placeholder="Комментарий по записи" onclick="event.stopPropagation()" onkeypress="if(event.key === 'Enter'){event.preventDefault(); submitFeedComment(${post.id});}">
                <button class="btn-secondary" onclick="event.stopPropagation(); submitFeedComment(${post.id})">Ответить</button>
            </div>
        </article>
    `).join('');
}

async function submitFeedPost() {
    const title = document.getElementById('feedPostTitle')?.value?.trim() || '';
    const content = document.getElementById('feedPostContent')?.value?.trim() || '';
    const pollOptions = [1, 2, 3].map(index => ({
        id: `opt_${index}`,
        label: document.getElementById(`feedPollOption${index}`)?.value?.trim() || '',
    })).filter(item => item.label);
    const targetRoles = Array.from(document.querySelectorAll('.feed-role-checkbox:checked')).map(node => node.value);
    const isPinned = document.getElementById('feedPinFlag')?.checked ? 1 : 0;
    const response = await apiCall('/feed/posts', 'POST', {
        post_type: currentFeedPostType,
        title,
        content,
        poll_options: pollOptions,
        target_roles: targetRoles,
        is_pinned: isPinned,
    });
    if (response?.error) return customAlert(response.message || 'Не удалось опубликовать запись.');
    ['feedPostTitle', 'feedPostContent', 'feedPollOption1', 'feedPollOption2', 'feedPollOption3'].forEach(id => {
        const node = document.getElementById(id);
        if (node) node.value = '';
    });
    document.querySelectorAll('.feed-role-checkbox').forEach(node => { node.checked = false; });
    const pin = document.getElementById('feedPinFlag');
    if (pin) pin.checked = false;
    await loadCompanyFeed();
}

async function submitFeedComment(postId) {
    const input = document.getElementById(`feedComment_${postId}`);
    const text = input?.value?.trim();
    if (!text) return;
    const response = await apiCall(`/feed/posts/${postId}/comments`, 'POST', { text });
    if (response?.error) return customAlert(response.message || 'Не удалось сохранить комментарий.');
    if (input) input.value = '';
    await loadCompanyFeed();
}

async function reactToFeedPost(postId, reactionKey) {
    await apiCall(`/feed/posts/${postId}/react`, 'POST', { reaction_key: reactionKey });
    await loadCompanyFeed();
}

async function voteFeedPost(postId, optionKey) {
    await apiCall(`/feed/posts/${postId}/vote`, 'POST', { option_key: optionKey });
    await loadCompanyFeed();
}

async function markFeedPostRead(postId) {
    await apiCall(`/feed/posts/${postId}/read`, 'POST');
    const post = companyFeedDB.find(item => Number(item.id) === Number(postId));
    if (post) post.is_read = 1;
    renderCompanyFeed();
}

async function toggleFeedPin(postId, nextValue) {
    const response = await apiCall(`/feed/posts/${postId}/pin`, 'POST', { is_pinned: nextValue });
    if (response?.error) return customAlert(response.message || 'Не удалось изменить закреп.');
    await loadCompanyFeed();
}

function setFeedRoleFilter(value) {
    currentFeedRoleFilter = value || 'all';
    renderCompanyFeed();
}

function setFeedReadFilter(value) {
    currentFeedReadFilter = value || 'all';
    renderCompanyFeed();
}

window.loadGlobalChats = loadGlobalChats;
window.openGlobalChat = openGlobalChat;
window.sendGlobalMessage = sendGlobalMessage;
window.openCreateChatModal = openCreateChatModal;
window.submitNewChat = submitNewChat;
window.deleteCurrentChat = deleteCurrentChat;
window.messengerSwitchTab = messengerSwitchTab;
window.loadCompanyFeed = loadCompanyFeed;
window.setFeedPostType = setFeedPostType;
window.submitFeedPost = submitFeedPost;
window.submitFeedComment = submitFeedComment;
window.reactToFeedPost = reactToFeedPost;
window.voteFeedPost = voteFeedPost;
window.markFeedPostRead = markFeedPostRead;
window.toggleFeedPin = toggleFeedPin;
window.setFeedRoleFilter = setFeedRoleFilter;
window.setFeedReadFilter = setFeedReadFilter;
