(function () {
    const warn = () => {
        if (window.__kordaLegacyDashboardWarned) return;
        window.__kordaLegacyDashboardWarned = true;
        console.warn('dashboard.js is deprecated. Korda CRM now loads split dashboard modules via index.html.');
    };

    warn();

    if (typeof window.renderDashboard !== 'function') {
        window.renderDashboard = function renderDashboardLegacyStub() {
            warn();
            return null;
        };
    }
})();
