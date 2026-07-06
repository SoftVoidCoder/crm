const ProjectRolesManager = {
    SYSTEM_ROLES: ['Конструкторское бюро', 'Производство и ОТК', 'Склад', 'Менеджер', 'Бухгалтерия', 'Юрист', 'Секретарь / Канцелярия', 'Сотрудник'],

    getSystemRoles: function() {
        if (typeof availableRoles !== 'undefined' && Array.isArray(availableRoles) && availableRoles.length) {
            return availableRoles.filter(role => role && role !== 'Директор');
        }
        return this.SYSTEM_ROLES.slice();
    },

    renderSelector: function(containerId, selectedRoles = []) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const normalizedSelectedRoles = Array.isArray(selectedRoles) ? selectedRoles : [];
        const roles = this.getSystemRoles();

        let html = '<label style="font-size: 12px; color: var(--primary); margin-top: 15px; display: block; font-weight: 600; text-align: left;">ДОСТУП К ПРОЕКТУ ПО РОЛЯМ:</label>';
        html += '<div style="background: var(--bg); padding: 10px; border-radius: 12px; border: 1px solid var(--border); font-size: 13px; text-align: left;">';

        html += roles.map(role => {
            const isChecked = normalizedSelectedRoles.includes(role) ? 'checked' : '';
            return `<label style="display:flex; gap:8px; align-items:center; margin-bottom:6px; cursor:pointer;">
                        <input type="checkbox" value="${role}" class="role-cb-${containerId}" ${isChecked}>
                        <span style="color: var(--text);">${role}</span>
                    </label>`;
        }).join('');

        html += '</div><p style="font-size: 11px; color: var(--secondary); margin-top: 4px; margin-bottom: 10px; text-align: left;">Отметьте роли, которые смогут видеть этот проект, даже если они не включены в рабочую группу.</p>';
        container.innerHTML = html;
    },

    getSelected: function(containerId) {
        const cbs = document.querySelectorAll(`.role-cb-${containerId}:checked`);
        return Array.from(cbs).map(cb => cb.value);
    }
};

window.ProjectRolesManager = ProjectRolesManager;
