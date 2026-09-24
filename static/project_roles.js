const ProjectRolesManager = {
    SYSTEM_ROLES: [],

    getSystemRoles: function() {
        return [];
    },

    renderSelector: function(containerId, selectedRoles = []) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const normalizedSelectedRoles = Array.isArray(selectedRoles) ? selectedRoles : [];
        const roles = this.getSystemRoles();

        container.innerHTML = '<div class="empty-state">Ограничений по ролям больше нет. Любого сотрудника можно добавить в любой проект.</div>';
    },

    getSelected: function(containerId) {
        const cbs = document.querySelectorAll(`.role-cb-${containerId}:checked`);
        return Array.from(cbs).map(cb => cb.value);
    }
};

window.ProjectRolesManager = ProjectRolesManager;
