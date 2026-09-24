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
    
    if (doRender) safeRenderView('dashboard', window.renderDashboard);
}

window.__navHistory = window.__navHistory || [];
window.__navCurrentView = window.__navCurrentView || '';
const MOBILE_WORKSPACE_MAX_WIDTH = 768;
const DISABLED_LEGACY_VIEWS = new Set([
    'tasks',
    'knowledge',
    'messenger',
    'meetings',
    'finance',
    'accounting',
    'integrations',
    'supply',
    'sales',
    'production',
    'expenses',
    'requests',
    'resources',
    'service',
    'executive',
    'operations',
    'prospecting',
    'myProspecting',
    'leads',
    'deals',
    'client360',
    'nomenclature',
    'contacts',
    'kpi',
    'profile',
]);

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

const ACTIVE_VIEW_IDS = [
    'dashboardView',
    'adminView',
    'projectView',
    'clientsView',
    'bitrixImportView',
    'approvalsView',
    'documentsView',
    'claimsView',
    'emailsView',
    'contract360View',
];

const ACTIVE_VIEW_RENDERERS = {
    dashboard: () => safeRenderView('dashboard', window.renderDashboard),
    approvals: () => safeRenderView('approvals', window.renderApprovals),
    clients: () => safeRenderView('clients', window.renderClients),
    bitrixImport: () => {
        safeRenderView('bitrixImport', window.renderBitrixImport);
    },
    contract360: () => {
        safeRenderView('contract360', window.renderContract360);
    },
    claims: () => {
        if (window.currentLegalTab === 'courts') safeRenderView('claims', window.renderCourts);
        else safeRenderView('claims', window.renderClaims);
    },
    documents: () => {
        safeRenderView('documents', window.renderDocuments);
        if (typeof ensureDocumentClientSources === 'function') {
            ensureDocumentClientSources().then(() => {
                if (document.getElementById('documentsView')?.style.display === 'block') safeRenderView('documents', window.renderDocuments);
            });
        }
    },
    emails: () => safeRenderView('emails', window.renderEmails),
    admin: () => safeRenderView('admin', window.openAdminPanelLogic),
};

function safeRenderView(view, renderer) {
    if (typeof renderer !== 'function') return;
    try {
        renderer();
    } catch (error) {
        console.error(`Failed to render ${view}`, error);
        if (typeof showToast === 'function') {
            showToast('Раздел не открылся', 'Обнови страницу и попробуй ещё раз. Ошибка записана в консоль.', 'error');
        }
    }
}

function canAccessViewForCurrentRole(view) {
    if (!currentUser || currentUser.status !== 'approved') return false;
    const target = String(view || '').trim();
    if (!target) return false;
    if (DISABLED_LEGACY_VIEWS.has(target)) return false;
    const config = typeof getRoleUiConfig === 'function' ? getRoleUiConfig(currentUser.role) : null;
    if (!config) return true;
    const navId = VIEW_NAV_MAP[target];
    if (!navId) return true;
    if (navId === 'navProfile') return true;
    return Array.isArray(config.visibleNav) && config.visibleNav.includes(navId);
}

function getSafeRoleLandingView() {
    const landing = typeof getRoleLandingView === 'function' ? getRoleLandingView() : 'dashboard';
    if (!DISABLED_LEGACY_VIEWS.has(landing) && canAccessViewForCurrentRole(landing)) return landing;
    return canAccessViewForCurrentRole('dashboard') ? 'dashboard' : 'documents';
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
    
    ACTIVE_VIEW_IDS.forEach(v => {
        const viewEl = document.getElementById(v);
        if (viewEl) viewEl.style.display = 'none';
    });
    
    const dashView = document.getElementById('dashboardView');
    if (dashView) {
        dashView.style.display = 'block';
        dashView.classList.add('fade-in');
    }
    scrollMainContentToTop();
    safeRenderView('dashboard', window.renderDashboard);
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

    ACTIVE_VIEW_IDS.forEach(v => {
        const el = document.getElementById(v);
        if(el) { el.style.display = 'none'; el.classList.remove('fade-in'); }
    });

    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    if (nextView !== 'dashboard') clearDepartmentFilter(false);
    const navId = VIEW_NAV_MAP[nextView];
    const nav = navId ? document.getElementById(navId) : null;
    if (nav) nav.classList.add('active');
    if (triggerRender && ACTIVE_VIEW_RENDERERS[nextView]) ACTIVE_VIEW_RENDERERS[nextView]();

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

function bindPrimaryNavigationClicks() {
    const bindings = [
        ['navDashboard', 'dashboard'],
        ['navApprovals', 'approvals'],
        ['navClients', 'clients'],
        ['navBitrixImport', 'bitrixImport'],
        ['navContract360', 'contract360'],
        ['navClaims', 'claims'],
        ['navDocuments', 'documents'],
        ['navEmails', 'emails'],
        ['adminBtn', 'admin'],
    ];
    bindings.forEach(([id, view]) => {
        const item = document.getElementById(id);
        if (!item || item.dataset.navBound === '1') return;
        item.dataset.navBound = '1';
        item.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            if (view === 'dashboard') clearDepartmentFilter(false);
            navigateTo(view);
        });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindPrimaryNavigationClicks);
} else {
    bindPrimaryNavigationClicks();
}

window.addEventListener('resize', () => {
    const wasMobile = document.documentElement.classList.contains('krd-mobile-communication-mode');
    const isMobile = syncMobileWorkspaceMode();
    if (wasMobile === isMobile) return;
    if (typeof applyRoleShell === 'function') applyRoleShell();
});
