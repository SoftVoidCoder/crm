// ==========================================
// НАВИГАЦИЯ И БАЗОВЫЕ ФИЛЬТРЫ ДАШБОРДА
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
        'tasksView', 'knowledgeView', 'approvalsView', 'documentsView', 'kpiView',
        'nomenclatureView', 'contactsView'
    ];
    viewsToHide.forEach(v => {
        const viewEl = document.getElementById(v);
        if (viewEl) viewEl.style.display = 'none';
    });
    
    const dashView = document.getElementById('dashboardView');
    if (dashView) {
        dashView.style.display = 'block';
        dashView.classList.add('fade-in');
    }
    
    renderDashboard();
}

function navigateTo(view, triggerRender = true) {
    // 1. Скрываем вообще все экраны
    const views = [
        'dashboardView', 'analyticsView', 'adminView', 'projectView', 
        'clientsView', 'profileView', 'emailsView', 'meetingsView', 
        'messengerView', 'tasksView', 'knowledgeView', 'approvalsView', 
        'documentsView', 'kpiView', 'nomenclatureView', 'contactsView'
    ];
    views.forEach(v => {
        const el = document.getElementById(v);
        if(el) { el.style.display = 'none'; el.classList.remove('fade-in'); }
    });

    // 2. Снимаем выделение (подсветку) со всех пунктов левого меню
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    // 3. Выполняем логику и подсвечиваем нужный пункт меню
    if (view === 'tasks') { 
        const nav = document.getElementById('navTasks'); 
        if(nav) nav.classList.add('active'); 
        renderTasks(); 
    } 
    else if (view === 'messenger') { 
        const nav = document.getElementById('navMessenger'); 
        if(nav) nav.classList.add('active'); 
        loadGlobalChats(); 
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
    else if (view === 'documents') { 
        const nav = document.getElementById('navDocuments'); 
        if(nav) nav.classList.add('active'); 
        renderDocuments(); 
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
    else if (view === 'dashboard') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navDashboard'); 
        if(nav) nav.classList.add('active'); 
        if(triggerRender) renderDashboard(); 
    } 
    else if (view === 'analytics') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navAnalytics'); 
        if(nav) nav.classList.add('active'); 
        drawCharts(); 
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
    else if (view === 'profile') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navProfile'); 
        if(nav) nav.classList.add('active'); 
        renderProfile(); 
    }
    else if (view === 'nomenclature') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navNomenclature'); 
        if(nav) nav.classList.add('active'); 
        if(typeof renderNomenclature === 'function') renderNomenclature(); 
    } 
    else if (view === 'contacts') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navContacts'); 
        if(nav) nav.classList.add('active'); 
        if(typeof renderContacts === 'function') renderContacts(); 
    }

    // 4. Показываем сам экран (контейнер)
    const target = document.getElementById(view + 'View');
    if (target) { 
        target.style.display = 'block'; 
        target.classList.add('fade-in'); 
    }
}