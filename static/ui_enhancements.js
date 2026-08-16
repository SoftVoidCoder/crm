(function () {
    'use strict';

    const DATE_ID_PATTERN = /(date|deadline|until|due|from|to|start|finish)$/i;
    const DATE_HINT_PATTERN = /(дд\.мм|дата|срок|начал|окончан|завершен)/i;
    const CLIENT_SELECT_PATTERN = /client(?:id)?$/i;
    const enhancedClientPickers = new Set();

    function uiEscape(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function ruDateToIso(value) {
        const raw = String(value || '').trim();
        const ru = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
        if (ru) return `${ru[3]}-${ru[2]}-${ru[1]}`;
        const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        return iso ? raw : '';
    }

    function isoDateToRu(value) {
        const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
        return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
    }

    function isDateField(input) {
        if (!(input instanceof HTMLInputElement) || input.dataset.calendarEnhanced === '1') return false;
        const type = String(input.type || 'text').toLowerCase();
        if (['hidden', 'file', 'checkbox', 'radio', 'button', 'submit', 'number', 'email', 'tel', 'search', 'time', 'datetime-local'].includes(type)) return false;
        if (type === 'date') return true;
        const identity = `${input.id || ''} ${input.name || ''}`.trim();
        const hint = `${input.placeholder || ''} ${input.getAttribute('aria-label') || ''}`;
        return DATE_ID_PATTERN.test(identity) || DATE_HINT_PATTERN.test(hint);
    }

    function enhanceNativeDate(input) {
        input.dataset.calendarEnhanced = '1';
        input.classList.add('ui-native-date');
        input.title = input.title || 'Выберите дату в календаре';
    }

    function enhanceTextDate(input) {
        input.dataset.calendarEnhanced = '1';
        const wrapper = document.createElement('span');
        wrapper.className = 'ui-date-field';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);
        input.classList.add('ui-date-field__input');
        input.setAttribute('autocomplete', 'off');

        const picker = document.createElement('input');
        picker.type = 'date';
        picker.className = 'ui-date-field__native';
        picker.tabIndex = -1;
        picker.setAttribute('aria-label', `Выбор даты: ${input.placeholder || input.id || 'дата'}`);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ui-date-field__button';
        button.title = 'Открыть календарь';
        button.setAttribute('aria-label', 'Открыть календарь');
        button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3v3M17 3v3M4.5 9h15M5 5.5h14a1.5 1.5 0 0 1 1.5 1.5v12A1.5 1.5 0 0 1 19 20.5H5A1.5 1.5 0 0 1 3.5 19V7A1.5 1.5 0 0 1 5 5.5Z"/></svg>';

        function syncPickerValue() {
            picker.value = ruDateToIso(input.value);
            button.disabled = input.disabled || input.readOnly;
        }

        button.addEventListener('click', () => {
            syncPickerValue();
            if (button.disabled) return;
            if (typeof picker.showPicker === 'function') picker.showPicker();
            else picker.click();
        });
        picker.addEventListener('change', () => {
            input.value = isoDateToRu(picker.value);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        });
        input.addEventListener('input', syncPickerValue);
        wrapper.appendChild(picker);
        wrapper.appendChild(button);
        syncPickerValue();
    }

    function enhanceDateFields(root) {
        const inputs = root instanceof HTMLInputElement ? [root] : Array.from(root.querySelectorAll?.('input') || []);
        inputs.forEach(input => {
            if (!isDateField(input)) return;
            if (String(input.type).toLowerCase() === 'date') enhanceNativeDate(input);
            else enhanceTextDate(input);
        });
    }

    function selectedClientLabel(select) {
        if (!select || Number(select.value || 0) <= 0) return '';
        return String(select.selectedOptions?.[0]?.textContent || '').trim();
    }

    function syncClientSearch(picker) {
        if (!picker || document.activeElement === picker.search) return;
        picker.search.value = selectedClientLabel(picker.select);
    }

    function ensureClientOptionEverywhere(clientId, clientName) {
        const id = Number(clientId || 0);
        const name = String(clientName || '').trim();
        if (!id || !name) return;
        enhancedClientPickers.forEach(picker => {
            let option = Array.from(picker.select.options).find(item => Number(item.value || 0) === id);
            if (!option) {
                option = new Option(name, String(id));
                picker.select.appendChild(option);
            } else {
                option.textContent = name;
            }
        });
        if (typeof clientsDB !== 'undefined' && Array.isArray(clientsDB)) {
            const existing = clientsDB.find(item => Number(item.id || 0) === id);
            if (!existing) clientsDB.push({ id, name, inn: '', contact: '' });
            else existing.name = name;
        }
    }

    function commitClientChoice(picker, clientId, clientName, sourceLabel) {
        ensureClientOptionEverywhere(clientId, clientName);
        picker.select.value = String(Number(clientId || 0));
        picker.search.value = String(clientName || '');
        picker.source.textContent = sourceLabel || 'CRM';
        picker.source.hidden = false;
        picker.results.hidden = true;
        picker.select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    async function chooseClientItem(picker, item) {
        if (!item) return;
        picker.search.disabled = true;
        try {
            if (item.kind === 'bitrix') {
                const response = await apiCall(`/client-picker/bitrix/${Number(item.id || 0)}/select`, 'POST', {});
                if (!response || response.error) {
                    await customAlert(response?.message || 'Не удалось выбрать клиента из Bitrix24.');
                    return;
                }
                commitClientChoice(picker, response.id, response.name || item.name, 'Bitrix24');
                if (typeof showToast === 'function') showToast('Клиент', 'Клиент из Bitrix24 выбран');
                return;
            }
            commitClientChoice(picker, item.id, item.name, item.source || 'CRM');
        } finally {
            picker.search.disabled = false;
        }
    }

    async function chooseManualClient(picker) {
        const name = String(picker.search.value || '').trim();
        if (name.length < 2) return customAlert('Введите название клиента минимум из двух символов.');
        picker.search.disabled = true;
        try {
            const response = await apiCall('/client-picker/manual', 'POST', { name, inn: '', kpp: '', ogrn: '', legal_address: '', contact: '' });
            if (!response || response.error) return customAlert(response?.message || 'Не удалось сохранить введённого клиента.');
            commitClientChoice(picker, response.id, response.name || name, response.created ? 'Введён вручную' : 'CRM');
            if (typeof showToast === 'function') showToast('Клиент', response.created ? 'Клиент добавлен и выбран' : 'Клиент выбран');
        } finally {
            picker.search.disabled = false;
        }
    }

    function renderClientResults(picker, items, query) {
        const rows = Array.isArray(items) ? items : [];
        picker.items = rows;
        picker.results.innerHTML = `
            <div class="ui-client-picker__list">
                ${rows.map((item, index) => `
                    <button type="button" class="ui-client-picker__result" data-client-result-index="${index}">
                        <span><strong>${uiEscape(item.name || 'Клиент')}</strong><small>${uiEscape(item.meta || 'Без дополнительных данных')}</small></span>
                        <em class="${item.source === 'Bitrix24' ? 'is-bitrix' : ''}">${uiEscape(item.source || 'CRM')}</em>
                    </button>
                `).join('') || '<div class="ui-client-picker__empty">Совпадений в CRM и Bitrix24 не найдено.</div>'}
            </div>
            ${String(query || '').trim() ? `<button type="button" class="ui-client-picker__manual">Использовать введённое: «${uiEscape(String(query).trim())}»</button>` : ''}
        `;
        picker.results.hidden = false;
    }

    async function loadClientResults(picker) {
        const query = String(picker.search.value || '').trim();
        const requestNo = ++picker.requestNo;
        picker.results.hidden = false;
        picker.results.innerHTML = '<div class="ui-client-picker__empty">Ищу клиентов…</div>';
        const response = await apiCall(`/client-picker/suggestions?query=${encodeURIComponent(query)}&limit=12`);
        if (requestNo !== picker.requestNo) return;
        if (!Array.isArray(response)) {
            picker.results.innerHTML = '<div class="ui-client-picker__empty">Не удалось загрузить список клиентов.</div>';
            return;
        }
        renderClientResults(picker, response, query);
    }

    function enhanceClientSelect(select) {
        if (!(select instanceof HTMLSelectElement) || select.multiple || select.dataset.clientPickerEnhanced === '1') return;
        if (!CLIENT_SELECT_PATTERN.test(select.id || '') && select.dataset.clientPicker !== '1') return;
        select.dataset.clientPickerEnhanced = '1';

        const wrapper = document.createElement('div');
        wrapper.className = 'ui-client-picker';
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(select);
        select.classList.add('ui-client-picker__native');

        const search = document.createElement('input');
        search.type = 'search';
        search.className = 'auth-input ui-client-picker__search';
        search.placeholder = 'Найти в CRM или Bitrix24 либо ввести вручную';
        search.autocomplete = 'off';

        const source = document.createElement('span');
        source.className = 'ui-client-picker__source';
        source.hidden = true;

        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'ui-client-picker__toggle';
        toggle.title = 'Открыть список клиентов';
        toggle.setAttribute('aria-label', 'Открыть список клиентов');
        toggle.textContent = '⌄';

        const results = document.createElement('div');
        results.className = 'ui-client-picker__results';
        results.hidden = true;
        wrapper.appendChild(search);
        wrapper.appendChild(source);
        wrapper.appendChild(toggle);
        wrapper.appendChild(results);

        const picker = { select, wrapper, search, source, toggle, results, items: [], requestNo: 0, timer: 0 };
        enhancedClientPickers.add(picker);

        search.value = selectedClientLabel(select);
        search.addEventListener('focus', () => loadClientResults(picker));
        search.addEventListener('input', () => {
            select.value = '';
            source.hidden = true;
            window.clearTimeout(picker.timer);
            picker.timer = window.setTimeout(() => loadClientResults(picker), 220);
        });
        toggle.addEventListener('click', () => {
            search.focus();
            loadClientResults(picker);
        });
        results.addEventListener('click', event => {
            const resultButton = event.target.closest('[data-client-result-index]');
            if (resultButton) return chooseClientItem(picker, picker.items[Number(resultButton.dataset.clientResultIndex || 0)]);
            if (event.target.closest('.ui-client-picker__manual')) return chooseManualClient(picker);
        });
        select.addEventListener('change', () => syncClientSearch(picker));

        const optionObserver = new MutationObserver(() => syncClientSearch(picker));
        optionObserver.observe(select, { childList: true, subtree: true });
    }

    function enhanceClientFields(root) {
        const selects = root instanceof HTMLSelectElement ? [root] : Array.from(root.querySelectorAll?.('select') || []);
        selects.forEach(enhanceClientSelect);
    }

    function enhanceUi(root = document) {
        enhanceDateFields(root);
        enhanceClientFields(root);
    }

    document.addEventListener('click', event => {
        enhancedClientPickers.forEach(picker => {
            if (!picker.wrapper.contains(event.target)) picker.results.hidden = true;
        });
    });

    const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => mutation.addedNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE) enhanceUi(node);
        }));
    });

    function startEnhancements() {
        enhanceUi(document);
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', startEnhancements, { once: true });
    else startEnhancements();

    window.refreshUniversalUiEnhancements = () => enhanceUi(document);
})();
