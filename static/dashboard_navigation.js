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

window.__navHistory = window.__navHistory || [];
window.__navCurrentView = window.__navCurrentView || '';

const VIEW_NAV_MAP = {
    dashboard: 'navDashboard',
    project: 'navDashboard',
    tasks: 'navTasks',
    approvals: 'navApprovals',
    claims: 'navClaims',
    knowledge: 'navKnowledge',
    documents: 'navDocuments',
    messenger: 'navMessenger',
    emails: 'navEmails',
    meetings: 'navMeetings',
    finance: 'navFinance',
    accounting: 'navAccounting',
    integrations: 'navIntegrations',
    supply: 'navSupply',
    sales: 'navSales',
    production: 'navProduction',
    expenses: 'navExpenses',
    requests: 'navRequests',
    resources: 'navResources',
    service: 'navService',
    executive: 'navExecutive',
    operations: 'navOperations',
    clients: 'navClients',
    prospecting: 'navProspecting',
    leads: 'navLeads',
    deals: 'navDeals',
    client360: 'navClient360',
    contract360: 'navContract360',
    nomenclature: 'navNomenclature',
    contacts: 'navContacts',
    analytics: 'navAnalytics',
    kpi: 'navKpi',
    profile: 'navProfile',
    admin: 'adminBtn',
};

function canAccessViewForCurrentRole(view) {
    if (!currentUser || currentUser.status !== 'approved') return false;
    const target = String(view || '').trim();
    if (!target) return false;
    const config = typeof getRoleUiConfig === 'function' ? getRoleUiConfig(currentUser.role) : null;
    if (!config) return true;
    const navId = VIEW_NAV_MAP[target];
    if (!navId) return true;
    if (navId === 'navProfile') return true;
    return Array.isArray(config.visibleNav) && config.visibleNav.includes(navId);
}

function getSafeRoleLandingView() {
    const landing = typeof getRoleLandingView === 'function' ? getRoleLandingView() : 'dashboard';
    if (canAccessViewForCurrentRole(landing)) return landing;
    return canAccessViewForCurrentRole('dashboard') ? 'dashboard' : 'profile';
}

window.canAccessViewForCurrentRole = canAccessViewForCurrentRole;

function updateBackButtonState() {
    const backBtn = document.getElementById('topbarBackBtn');
    if (!backBtn) return;
    const canGoBack = Array.isArray(window.__navHistory) && window.__navHistory.length > 0;
    backBtn.style.display = canGoBack ? 'inline-flex' : 'none';
    backBtn.disabled = !canGoBack;
}

window.navigateBack = function() {
    const history = Array.isArray(window.__navHistory) ? window.__navHistory : [];
    const fallback = typeof getRoleLandingView === 'function' ? getRoleLandingView() : 'dashboard';
    const previous = history.pop() || fallback;
    if (!previous) return;
    window.__navSkipHistoryPush = true;
    navigateTo(previous);
};

function scrollMainContentToTop() {
    const mainContent = document.querySelector('.main-content');
    if (mainContent) mainContent.scrollTop = 0;
    window.scrollTo(0, 0);
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
        'analyticsView', 'adminView', 'projectView', 'clientsView', 'prospectingView', 'leadsView', 'dealsView',
        'profileView', 'emailsView', 'meetingsView', 'messengerView', 
        'tasksView', 'knowledgeView', 'approvalsView', 'documentsView', 'claimsView', 'kpiView',
        'nomenclatureView', 'contactsView', 'financeView', 'accountingView', 'integrationsView', 'client360View', 'contract360View', 'supplyView', 'salesView', 'productionView', 'expensesView', 'requestsView', 'resourcesView', 'serviceView', 'executiveView', 'operationsView'
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
    scrollMainContentToTop();
    renderDashboard();
}

function navigateTo(view, triggerRender = true) {
    const nextView = String(view || '');
    if (!canAccessViewForCurrentRole(nextView)) {
        const fallback = getSafeRoleLandingView();
        if (window.__navCurrentView && canAccessViewForCurrentRole(window.__navCurrentView)) {
            if (typeof showToast === 'function') showToast('Навигация', 'Этот раздел скрыт для твоей роли.');
            return;
        }
        if (fallback && fallback !== nextView) {
            if (typeof showToast === 'function') showToast('Навигация', 'Открываю основной рабочий раздел твоей роли.');
            window.__navSkipHistoryPush = true;
            navigateTo(fallback, true);
        }
        return;
    }
    const previousView = window.__navCurrentView || '';
    if (previousView && previousView !== nextView && !window.__navSkipHistoryPush) {
        const history = Array.isArray(window.__navHistory) ? window.__navHistory : [];
        if (history[history.length - 1] !== previousView) history.push(previousView);
        window.__navHistory = history.slice(-20);
    }
    window.__navSkipHistoryPush = false;
    window.__navCurrentView = nextView;
    if (nextView) localStorage.setItem('korda_last_view', nextView);

    // 1. Скрываем вообще все экраны
    const views = [
        'dashboardView', 'analyticsView', 'adminView', 'projectView', 
        'clientsView', 'prospectingView', 'leadsView', 'dealsView', 'profileView', 'emailsView', 'meetingsView', 
        'messengerView', 'tasksView', 'knowledgeView', 'approvalsView', 
        'documentsView', 'claimsView', 'kpiView', 'nomenclatureView', 'contactsView', 'financeView', 'accountingView', 'integrationsView', 'client360View', 'contract360View', 'supplyView', 'salesView', 'productionView', 'expensesView', 'requestsView', 'resourcesView', 'serviceView', 'executiveView', 'operationsView'
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
        if (typeof messengerSwitchTab === 'function') messengerSwitchTab('feed');
        else loadGlobalChats(); 
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
    else if (view === 'finance') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navFinance');
        if (nav) nav.classList.add('active');
        if (typeof renderFinance === 'function') renderFinance();
    }
    else if (view === 'accounting') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navAccounting');
        if (nav) nav.classList.add('active');
        if (typeof renderAccounting === 'function') renderAccounting();
    }
    else if (view === 'integrations') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navIntegrations');
        if (nav) nav.classList.add('active');
        if (typeof renderIntegrations === 'function') renderIntegrations();
    }
    else if (view === 'supply') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navSupply');
        if (nav) nav.classList.add('active');
        if (typeof renderSupply === 'function') renderSupply();
    }
    else if (view === 'sales') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navSales');
        if (nav) nav.classList.add('active');
        if (typeof renderSales === 'function') renderSales();
    }
    else if (view === 'production') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navProduction');
        if (nav) nav.classList.add('active');
        if (typeof renderProduction === 'function') renderProduction();
    }
    else if (view === 'expenses') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navExpenses');
        if (nav) nav.classList.add('active');
        if (typeof renderExpenses === 'function') renderExpenses();
    }
    else if (view === 'requests') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navRequests');
        if (nav) nav.classList.add('active');
        if (typeof renderInternalRequests === 'function') renderInternalRequests();
    }
    else if (view === 'resources') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navResources');
        if (nav) nav.classList.add('active');
        if (typeof renderResources === 'function') renderResources();
    }
    else if (view === 'service') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navService');
        if (nav) nav.classList.add('active');
        if (typeof renderServiceCases === 'function') renderServiceCases();
    }
    else if (view === 'executive') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navExecutive');
        if (nav) nav.classList.add('active');
        if (typeof renderExecutiveDashboard === 'function') renderExecutiveDashboard();
    }
    else if (view === 'operations') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navOperations');
        if (nav) nav.classList.add('active');
        if (typeof renderOperationsCenter === 'function') renderOperationsCenter();
    }
    else if (view === 'documents') { 
        const nav = document.getElementById('navDocuments'); 
        if(nav) nav.classList.add('active'); 
        renderDocuments(); 
    }
    else if (view === 'claims') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navClaims');
        if (nav) nav.classList.add('active');
        if (currentLegalTab === 'courts' && typeof renderCourts === 'function') renderCourts();
        else if (typeof renderClaims === 'function') renderClaims();
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
        requestAnimationFrame(() => drawCharts());
        setTimeout(() => drawCharts(), 120);
    } 
    else if (view === 'clients') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navClients'); 
        if(nav) nav.classList.add('active'); 
        renderClients(); 
    } 
    else if (view === 'prospecting') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navProspecting');
        if (nav) nav.classList.add('active');
        if (typeof renderProspecting === 'function') renderProspecting();
    }
    else if (view === 'leads') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navLeads');
        if (nav) nav.classList.add('active');
        if (typeof renderLeads === 'function') renderLeads();
    }
    else if (view === 'deals') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navDeals');
        if (nav) nav.classList.add('active');
        if (typeof renderDeals === 'function') renderDeals();
    }
    else if (view === 'client360') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navClient360');
        if (nav) nav.classList.add('active');
        if (typeof renderClient360 === 'function') renderClient360();
    }
    else if (view === 'contract360') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navContract360');
        if (nav) nav.classList.add('active');
        if (typeof renderContract360 === 'function') renderContract360();
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
        target.classList.remove('krd-is-hidden');
        target.style.display = 'block';
        target.classList.add('fade-in');
    }
    scrollMainContentToTop();
    updateBackButtonState();
    if (typeof window.removeMountedSectionGuides === 'function') {
        window.removeMountedSectionGuides(view + 'View');
    }
    if (typeof mountSectionGuideForView === 'function') {
        mountSectionGuideForView(view + 'View');
    }
    if (typeof window.refreshCollapsibleLayouts === 'function') {
        window.refreshCollapsibleLayouts(view + 'View');
    }
}

window.clearDepartmentFilter = clearDepartmentFilter;
window.filterByDepartment = filterByDepartment;
window.navigateTo = navigateTo;
