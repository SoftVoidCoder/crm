(function () {
    const TARGET_VIEWS = [
        'financeView',
        'productionView',
        'executiveView',
        'operationsView',
        'accountingView',
        'profileView',
        'documentsView',
        'emailsView',
        'salesView',
        'supplyView',
        'requestsView',
        'resourcesView',
        'nomenclatureView',
        'client360View',
        'contract360View',
    ];

    let refreshQueued = false;
    let suppressObserver = false;

    function unique(nodes) {
        return Array.from(new Set(nodes.filter(Boolean)));
    }

    function isNestedSurfaceCard(section, root) {
        let current = section.parentElement;
        while (current && current !== root) {
            if (current.classList && current.classList.contains('surface-card')) return true;
            current = current.parentElement;
        }
        return false;
    }

    function querySections(view, selector, options) {
        const settings = options || {};
        return Array.from(view.querySelectorAll(selector)).filter(function (section) {
            if (!(section instanceof HTMLElement)) return false;
            if (section.closest('.crm-chat-shell')) return false;
            if (settings.topLevelOnly && isNestedSurfaceCard(section, view)) return false;
            return true;
        });
    }

    function decorateView(view) {
        if (!view) return;
        view.classList.add('crm-page-shell', 'crm-page-shell--dense', 'crm-flow-page');

        Array.from(view.children).forEach(function (child, index) {
            if (!(child instanceof HTMLElement)) return;
            if (
                child.matches(
                    '.view-header, .ops-overview-card, .workbench-strip, .metrics-grid, .erp-cockpit-grid, .finance-layout, .client360-grid, .secondary-zone, .surface-card, .accounting-pulse-grid, .boardroom-brief, .tabs'
                )
            ) {
                child.classList.add('crm-shell-block');
                if (index >= 4) child.classList.add('crm-shell-block--deep');
            }
        });
    }

    function applyFlow(section, config) {
        if (!section) return;
        const tone = config && config.tone ? config.tone : 'secondary';

        section.classList.add('crm-flow-section');
        section.classList.toggle('crm-flow-section--primary', tone === 'primary');
        section.classList.toggle('crm-flow-section--secondary', tone !== 'primary');
        section.removeAttribute('data-crm-collapsible');
        section.removeAttribute('data-crm-collapsed');
        section.removeAttribute('data-crm-collapsed-default');
        section.removeAttribute('data-crm-collapse-mode');
        section.removeAttribute('data-crm-collapsible-peek');
        section.removeAttribute('data-crm-card-tone');

        const syntheticHeader = section.querySelector(':scope > .crm-collapsible__header--synthetic');
        if (syntheticHeader && !section.querySelector(':scope > .section-header')) {
            syntheticHeader.classList.remove('crm-collapsible__header--synthetic');
            syntheticHeader.classList.add('section-header');
        }

        const body = section.querySelector(':scope > .crm-collapsible__body');
        if (body) {
            while (body.firstChild) section.appendChild(body.firstChild);
            body.remove();
        }

        const preview = section.querySelector(':scope > .crm-collapsible__preview');
        if (preview) preview.remove();

        const toggle = section.querySelector('.crm-collapsible__toggle');
        if (toggle) toggle.remove();

        section.classList.remove(
            'crm-collapsible',
            'crm-collapsible--enabled',
            'crm-collapsible--is-collapsed',
            'crm-collapsible--primary',
            'crm-collapsible--secondary',
            'crm-collapsible--compact'
        );
    }

    function markSections(view, selector, resolver, options) {
        const settings = options || {};
        querySections(view, selector, settings).forEach(function (section, index) {
            const config = typeof resolver === 'function' ? resolver(section, index) : resolver;
            applyFlow(section, config);
        });
    }

    function markSequence(view, selector, options) {
        const settings = options || {};
        const primaryCount = settings.primaryCount != null ? settings.primaryCount : 1;

        markSections(
            view,
            selector,
            function (_section, index) {
                return {
                    tone: index < primaryCount ? 'primary' : 'secondary',
                };
            },
            settings
        );
    }

    function markAllFlow(view, selector, options) {
        markSections(
            view,
            selector,
            {
                tone: 'secondary',
            },
            options
        );
    }

    function applyGenericDenseRules(view) {
        const sections = unique(
            [
                '.secondary-zone > section.surface-card',
                '.finance-layout > section.surface-card',
                '.client360-grid > section.surface-card',
                '.accounting-pulse-grid > section.surface-card',
                '.contract360-master-grid > section.surface-card',
                '.ops-grid-two > section.surface-card',
                '.project-ops-grid > section.surface-card',
            ].flatMap(function (selector) {
                return querySections(view, selector, { topLevelOnly: true });
            })
        );

        if (sections.length < 2) return;

        sections.forEach(function (section, index) {
            applyFlow(section, { tone: index === 0 ? 'primary' : 'secondary' });
        });
    }

    function applyDenseRules(view) {
        if (!view) return;

        decorateView(view);

        if (view.id === 'financeView') {
            markSequence(view, '.finance-layout > section.surface-card', { primaryCount: 1, topLevelOnly: true });
            markAllFlow(view, '#financeDeepMount section.surface-card, #accountingDeepMount section.surface-card');
        }

        if (view.id === 'productionView') {
            markSequence(view, '.client360-grid.secondary-zone > section.surface-card', { primaryCount: 1, topLevelOnly: true });
            markSequence(view, '.finance-layout > section.surface-card', { primaryCount: 1, topLevelOnly: true });
        }

        if (view.id === 'executiveView') {
            markSequence(view, '.client360-grid > section.surface-card', { primaryCount: 1, topLevelOnly: true });
        }

        if (view.id === 'operationsView') {
            markSequence(view, '.client360-grid.secondary-zone > section.surface-card', { primaryCount: 1, topLevelOnly: true });
            markAllFlow(view, '#integrationPlusMount section.surface-card');
        }

        if (view.id === 'accountingView') {
            markSequence(view, '.accounting-pulse-grid > section.surface-card', { primaryCount: 1, topLevelOnly: true });
            markSequence(view, '#accountingWaybillsPanel .finance-layout > section.surface-card', { primaryCount: 1, topLevelOnly: true });
            markAllFlow(view, '#accountingWaybillsPanel > section.surface-card', { topLevelOnly: true });
            markSequence(view, '#accountingDriversPanel .finance-layout > section.surface-card', { primaryCount: 1, topLevelOnly: true });
            markSequence(view, '#accountingVehiclesPanel .finance-layout > section.surface-card', { primaryCount: 1, topLevelOnly: true });
            markAllFlow(view, '#accountingIntegrationPanel section.surface-card, #accountingDeepMount section.surface-card');
        }

        if (view.id === 'profileView') {
            markAllFlow(
                view,
                '#directorUsersBlock, #directorAuditBlock, #directorSecurityBlock, #directorFieldSecurityBlock, #directorSystemBlock, #securityPlusMount section.surface-card'
            );
        }

        if (view.id === 'documentsView') {
            markAllFlow(view, '#docflowPlusMount section.surface-card');
        }

        applyGenericDenseRules(view);
    }

    function getViewFlowSections(view) {
        if (!view) return [];
        const panels = view.querySelector(':scope > .crm-view-workspace .crm-workspace__panels');
        if (panels) return Array.from(panels.querySelectorAll(':scope > .crm-flow-section'));
        return Array.from(view.querySelectorAll('.crm-flow-section'));
    }

    function getSectionsForWorkspace(workspace) {
        if (!workspace) return [];
        const panels = workspace.querySelector(':scope > .crm-workspace__panels');
        if (!panels) return [];
        return Array.from(panels.querySelectorAll(':scope > .crm-flow-section'));
    }

    function getSectionLabel(section) {
        const titleNode = section.querySelector(':scope > .section-header .section-title, :scope > .section-title');
        const subtitleNode = section.querySelector(':scope > .section-header .section-subtitle, :scope > .section-subtitle');

        return {
            title: titleNode ? (titleNode.textContent || '').replace(/\s+/g, ' ').trim() : 'Раздел',
            subtitle: subtitleNode ? (subtitleNode.textContent || '').replace(/\s+/g, ' ').trim() : '',
        };
    }

    function activateWorkspaceTab(workspace, index) {
        const tabs = Array.from(workspace.querySelectorAll(':scope > .crm-workspace__nav .crm-workspace__tab'));
        const sections = getSectionsForWorkspace(workspace);
        if (!sections.length) return;

        const safeIndex = Math.max(0, Math.min(index, sections.length - 1));
        workspace.dataset.crmWorkspaceActive = String(safeIndex);

        tabs.forEach(function (tab, tabIndex) {
            const active = tabIndex === safeIndex;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', String(active));
            tab.setAttribute('tabindex', active ? '0' : '-1');
        });

        sections.forEach(function (section, sectionIndex) {
            const active = sectionIndex === safeIndex;
            section.hidden = !active;
            section.classList.toggle('is-active', active);
        });

        const select = workspace.querySelector(':scope > .crm-workspace__nav .crm-workspace__select');
        if (select) select.value = String(safeIndex);
        const currentLabel = workspace.querySelector(':scope > .crm-workspace__nav .crm-workspace__current');
        if (currentLabel) currentLabel.textContent = getSectionLabel(sections[safeIndex]).title;
    }

    function cleanupSourceContainers(view, workspace) {
        Array.from(view.querySelectorAll('.crm-flow-source')).forEach(function (source) {
            if (workspace && source === workspace) return;
            const hasSection = !!source.querySelector(':scope > .crm-flow-section, :scope > .crm-view-workspace, :scope > .crm-workspace__nav, :scope > .crm-workspace__panels');
            const hasMeaningfulText = Array.from(source.childNodes).some(function (node) {
                return node.nodeType === 3 && (node.textContent || '').trim().length > 0;
            });
            if (!hasSection && !hasMeaningfulText) {
                source.style.display = 'none';
                source.classList.add('crm-flow-source--empty');
            } else {
                source.style.display = '';
                source.classList.remove('crm-flow-source--empty');
            }
        });
    }

    function ensureWorkspaceTabs(view) {
        if (!view) return;
        if (view.id === 'profileView') return;
        const sections = getViewFlowSections(view);
        const sectionCount = sections.length;
        if (!sectionCount) return;

        let workspace = view.querySelector(':scope > .crm-view-workspace');
        let panels = workspace && workspace.querySelector(':scope > .crm-workspace__panels');
        let nav = workspace && workspace.querySelector(':scope > .crm-workspace__nav');

        if (!workspace) {
            workspace = document.createElement('div');
            workspace.className = 'crm-view-workspace crm-flow-stack crm-workspace';
            const firstSection = sections[0];
            const anchor = firstSection ? firstSection.parentElement : null;
            if (anchor && anchor.parentElement === view) {
                view.insertBefore(workspace, anchor);
            } else {
                view.appendChild(workspace);
            }
        }

        workspace.classList.add('crm-flow-stack', 'crm-workspace');
        workspace.classList.toggle('crm-flow-stack--single', sectionCount === 1);

        if (!panels) {
            panels = document.createElement('div');
            panels.className = 'crm-workspace__panels';
            workspace.appendChild(panels);
        }

        if (!nav) {
            nav = document.createElement('div');
            nav.className = 'crm-workspace__nav';
            nav.setAttribute('role', 'tablist');
            workspace.insertBefore(nav, panels);
        }

        sections.forEach(function (section) {
            const source = section.parentElement;
            if (source && source !== panels) source.classList.add('crm-flow-source');
            panels.appendChild(section);
        });

        cleanupSourceContainers(view, workspace);

        if (sectionCount < 2) {
            nav.remove();
            sections.forEach(function (section) {
                section.hidden = false;
                section.classList.remove('is-active');
            });
            delete workspace.dataset.crmWorkspaceActive;
            return;
        }

        nav.innerHTML = '';
        const useSectionPicker = sectionCount > 8;
        workspace.classList.toggle('crm-workspace--many-tabs', useSectionPicker);
        workspace.classList.toggle('crm-workspace--tabs', !useSectionPicker);

        if (useSectionPicker) {
            nav.removeAttribute('role');
            nav.setAttribute('aria-label', 'Выбор рабочего раздела');

            const summary = document.createElement('div');
            summary.className = 'crm-workspace__nav-summary';
            const caption = document.createElement('span');
            caption.textContent = 'Рабочий раздел';
            const current = document.createElement('strong');
            current.className = 'crm-workspace__current';
            summary.append(caption, current);

            const select = document.createElement('select');
            select.className = 'crm-workspace__select auth-input';
            select.setAttribute('aria-label', 'Рабочий раздел');
            sections.forEach(function (section, index) {
                const option = document.createElement('option');
                option.value = String(index);
                option.textContent = getSectionLabel(section).title;
                select.appendChild(option);
            });
            select.addEventListener('change', function () {
                activateWorkspaceTab(workspace, parseInt(select.value || '0', 10));
            });
            nav.append(summary, select);
        } else {
            nav.setAttribute('role', 'tablist');
            nav.removeAttribute('aria-label');
            sections.forEach(function (section, index) {
                const label = getSectionLabel(section);
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'crm-workspace__tab';
                button.setAttribute('role', 'tab');
                button.setAttribute('aria-selected', 'false');
                const title = document.createElement('span');
                title.className = 'crm-workspace__tab-title';
                title.textContent = label.title;
                button.appendChild(title);
                if (label.subtitle) button.title = label.subtitle;
                button.addEventListener('click', function () {
                    activateWorkspaceTab(workspace, index);
                });
                nav.appendChild(button);
            });
        }

        const preferredIndex = parseInt(workspace.dataset.crmWorkspaceActive || '0', 10);
        activateWorkspaceTab(workspace, Number.isFinite(preferredIndex) ? preferredIndex : 0);
    }

    function normalizeParentStacks(view) {
        ensureWorkspaceTabs(view);
    }

    function refresh(viewId) {
        const views = viewId
            ? [document.getElementById(viewId)].filter(Boolean)
            : TARGET_VIEWS.map(function (id) {
                  return document.getElementById(id);
              }).filter(Boolean);

        views.forEach(function (view) {
            applyDenseRules(view);
            normalizeParentStacks(view);
        });
    }

    function scheduleRefresh(viewId) {
        if (refreshQueued) return;
        refreshQueued = true;
        requestAnimationFrame(function () {
            refreshQueued = false;
            suppressObserver = true;
            try {
                refresh(viewId);
            } finally {
                setTimeout(function () {
                    suppressObserver = false;
                }, 0);
            }
        });
    }

    function observeChanges() {
        const root = document.querySelector('.main-content');
        if (!root) return;

        const observer = new MutationObserver(function () {
            if (suppressObserver) return;
            scheduleRefresh();
        });

        observer.observe(root, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['style', 'class'],
        });
    }

    function boot() {
        refresh();
        observeChanges();
        window.addEventListener('resize', function () {
            scheduleRefresh();
        });
    }

    window.refreshCollapsibleLayouts = function (viewId) {
        scheduleRefresh(viewId);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot, { once: true });
    } else {
        boot();
    }
})();
