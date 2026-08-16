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
const MOBILE_WORKSPACE_MAX_WIDTH = 768;

function isMobileWorkspaceMode() {
    return window.matchMedia(`(max-width: ${MOBILE_WORKSPACE_MAX_WIDTH}px)`).matches;
}

function syncMobileWorkspaceMode() {
    document.documentElement.classList.remove('krd-mobile-communication-mode');
    document.body.classList.remove('krd-mobile-communication-mode');
    return isMobileWorkspaceMode();
}

function coerceMobileWorkspaceView(view) {
    const nextView = String(view || '').trim();
    return nextView;
}

window.isMobileWorkspaceMode = isMobileWorkspaceMode;
window.syncMobileWorkspaceMode = syncMobileWorkspaceMode;

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
    myProspecting: 'navMyProspecting',
    bitrixImport: 'navBitrixImport',
    leads: 'navLeads',
    deals: 'navDeals',
    client360: 'navClient360',
    contract360: 'navContract360',
    nomenclature: 'navNomenclature',
    contacts: 'navContacts',
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
        'analyticsView', 'adminView', 'projectView', 'clientsView', 'bitrixImportView', 'prospectingView', 'myProspectingView', 'leadsView', 'dealsView',
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
    document.body.classList.remove('mobile-menu-open');
    syncMobileWorkspaceMode();
    const nextView = coerceMobileWorkspaceView(view);
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
    if (
        previousView === 'accounting'
        && nextView !== 'accounting'
        && typeof releaseEplWaybillLock === 'function'
    ) {
        releaseEplWaybillLock(0, true);
    }
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
        'clientsView', 'bitrixImportView', 'prospectingView', 'myProspectingView', 'leadsView', 'dealsView', 'profileView', 'emailsView', 'meetingsView',
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
    if (nextView === 'tasks') { 
        const nav = document.getElementById('navTasks'); 
        if(nav) nav.classList.add('active'); 
        renderTasks(); 
    } 
    else if (nextView === 'messenger') { 
        const nav = document.getElementById('navMessenger'); 
        if(nav) nav.classList.add('active'); 
        if (typeof messengerSwitchTab === 'function') messengerSwitchTab('chats');
        else loadGlobalChats(); 
    }
    else if (nextView === 'emails') { 
        const nav = document.getElementById('navEmails'); 
        if(nav) nav.classList.add('active'); 
        renderEmails(); 
    }
    else if (nextView === 'meetings') { 
        const nav = document.getElementById('navMeetings'); 
        if(nav) nav.classList.add('active'); 
        renderMeetings(); 
    }
    else if (nextView === 'finance') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navFinance');
        if (nav) nav.classList.add('active');
        if (typeof renderFinance === 'function') renderFinance();
    }
    else if (nextView === 'accounting') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navAccounting');
        if (nav) nav.classList.add('active');
        if (typeof renderAccounting === 'function') renderAccounting();
    }
    else if (nextView === 'integrations') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navIntegrations');
        if (nav) nav.classList.add('active');
        if (typeof renderIntegrations === 'function') renderIntegrations();
    }
    else if (nextView === 'supply') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navSupply');
        if (nav) nav.classList.add('active');
        if (typeof renderSupply === 'function') renderSupply();
    }
    else if (nextView === 'sales') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navSales');
        if (nav) nav.classList.add('active');
        if (typeof renderSales === 'function') renderSales();
    }
    else if (nextView === 'production') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navProduction');
        if (nav) nav.classList.add('active');
        if (typeof renderProduction === 'function') renderProduction();
    }
    else if (nextView === 'expenses') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navExpenses');
        if (nav) nav.classList.add('active');
        if (typeof renderExpenses === 'function') renderExpenses();
    }
    else if (nextView === 'requests') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navRequests');
        if (nav) nav.classList.add('active');
        if (typeof renderInternalRequests === 'function') renderInternalRequests();
    }
    else if (nextView === 'resources') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navResources');
        if (nav) nav.classList.add('active');
        if (typeof renderResources === 'function') renderResources();
    }
    else if (nextView === 'service') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navService');
        if (nav) nav.classList.add('active');
        if (typeof renderServiceCases === 'function') renderServiceCases();
    }
    else if (nextView === 'executive') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navExecutive');
        if (nav) nav.classList.add('active');
        if (typeof renderExecutiveDashboard === 'function') renderExecutiveDashboard();
    }
    else if (nextView === 'operations') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navOperations');
        if (nav) nav.classList.add('active');
        if (typeof renderOperationsCenter === 'function') renderOperationsCenter();
    }
    else if (nextView === 'documents') { 
        const nav = document.getElementById('navDocuments'); 
        if(nav) nav.classList.add('active'); 
        renderDocuments();
        if (typeof ensureDocumentClientSources === 'function') {
            ensureDocumentClientSources().then(() => {
                if (document.getElementById('documentsView')?.style.display === 'block') renderDocuments();
            });
        }
    }
    else if (nextView === 'claims') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navClaims');
        if (nav) nav.classList.add('active');
        if (currentLegalTab === 'courts' && typeof renderCourts === 'function') renderCourts();
        else if (typeof renderClaims === 'function') renderClaims();
    }
    else if (nextView === 'knowledge') { 
        const nav = document.getElementById('navKnowledge'); 
        if(nav) nav.classList.add('active'); 
        renderKnowledge(); 
    }
    else if (nextView === 'approvals') { 
        const nav = document.getElementById('navApprovals'); 
        if(nav) nav.classList.add('active'); 
        renderApprovals(); 
    }
    else if (nextView === 'kpi') { 
        const nav = document.getElementById('navKpi'); 
        if(nav) nav.classList.add('active'); 
        renderKPI(); 
    }
    else if (nextView === 'dashboard') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navDashboard'); 
        if(nav) nav.classList.add('active'); 
        if(triggerRender) renderDashboard(); 
    } 
    else if (nextView === 'clients') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navClients'); 
        if(nav) nav.classList.add('active'); 
        renderClients(); 
    } 
    else if (nextView === 'prospecting') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navProspecting');
        if (nav) nav.classList.add('active');
        if (typeof renderOutreachPoolPage === 'function') renderOutreachPoolPage();
    }
    else if (nextView === 'myProspecting') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navMyProspecting');
        if (nav) nav.classList.add('active');
        if (typeof renderMyProspecting === 'function') renderMyProspecting();
    }
    else if (nextView === 'bitrixImport') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navBitrixImport');
        if (nav) nav.classList.add('active');
        if (typeof renderBitrixImport === 'function') renderBitrixImport();
    }
    else if (nextView === 'leads') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navLeads');
        if (nav) nav.classList.add('active');
        if (typeof renderLeads === 'function') renderLeads();
    }
    else if (nextView === 'deals') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navDeals');
        if (nav) nav.classList.add('active');
        if (typeof refreshDealsFromServer === 'function') refreshDealsFromServer(true);
        else if (typeof renderDeals === 'function') renderDeals();
    }
    else if (nextView === 'client360') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navClient360');
        if (nav) nav.classList.add('active');
        if (typeof renderClient360 === 'function') renderClient360();
    }
    else if (nextView === 'contract360') {
        clearDepartmentFilter(false);
        const nav = document.getElementById('navContract360');
        if (nav) nav.classList.add('active');
        if (typeof renderContract360 === 'function') renderContract360();
    }
    else if (nextView === 'admin') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('adminBtn'); 
        if(nav) nav.classList.add('active'); 
        openAdminPanelLogic(); 
    } 
    else if (nextView === 'profile') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navProfile'); 
        if(nav) nav.classList.add('active'); 
        renderProfile(); 
    }
    else if (nextView === 'nomenclature') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navNomenclature'); 
        if(nav) nav.classList.add('active'); 
        if(typeof renderNomenclature === 'function') renderNomenclature(); 
    } 
    else if (nextView === 'contacts') { 
        clearDepartmentFilter(false); 
        const nav = document.getElementById('navContacts'); 
        if(nav) nav.classList.add('active'); 
        if(typeof renderContacts === 'function') renderContacts(); 
    }

    // 4. Показываем сам экран (контейнер)
    const target = document.getElementById(nextView + 'View');
    if (target) {
        target.classList.remove('krd-is-hidden');
        target.style.display = nextView === 'profile' ? 'flex' : 'block';
        target.classList.add('fade-in');
    }
    scrollMainContentToTop();
    updateBackButtonState();
    if (typeof window.removeMountedSectionGuides === 'function') {
        window.removeMountedSectionGuides(nextView + 'View');
    }
    if (typeof mountSectionGuideForView === 'function') {
        mountSectionGuideForView(nextView + 'View');
    }
    if (typeof window.refreshCollapsibleLayouts === 'function') {
        window.refreshCollapsibleLayouts(nextView + 'View');
    }
}

window.clearDepartmentFilter = clearDepartmentFilter;
window.filterByDepartment = filterByDepartment;
window.navigateTo = navigateTo;

window.addEventListener('resize', () => {
    const wasMobile = document.documentElement.classList.contains('krd-mobile-communication-mode');
    const isMobile = syncMobileWorkspaceMode();
    if (wasMobile === isMobile) return;
    if (typeof applyRoleShell === 'function') applyRoleShell();
});
