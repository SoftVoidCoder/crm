/* Korda CRM Assistant — продуктовый чат-помощник.
   Основной режим: серверный Gemini через /api/assistant/ask.
   Резервный режим: локальные ответы из уже загруженных CRM-данных. */
(function () {
    'use strict';

    const STORAGE_KEY = 'kordaAssistant.history.v2';
    const STORAGE_OPEN = 'kordaAssistant.opened.v2';
    const MAX_HISTORY = 60;

    /* VIEW_LABELS — только реальные view-id, которые знает navigateTo()
       (см. dashboard_navigation.js: views[] и if-чейн).
       ВАЖНО: «Все проекты» — это и есть dashboardView, отдельного projectsView нет. */
    const VIEW_LABELS = {
        dashboard: 'Все проекты',
        clients: 'База клиентов',
        prospecting: 'База развития',
        leads: 'Лиды',
        deals: 'Сделки',
        client360: 'Клиент 360',
        contract360: 'Договоры 360',
        contacts: 'Контакты',
        documents: 'Документы',
        tasks: 'Поручения',
        approvals: 'Согласования',
        claims: 'Претензии',
        knowledge: 'База знаний',
        messenger: 'Мессенджер',
        emails: 'Почта',
        meetings: 'Встречи',
        finance: 'Финансы',
        accounting: 'Бухгалтерия',
        integrations: 'Интеграции',
        supply: 'Снабжение',
        sales: 'Продажи',
        production: 'Производство',
        expenses: 'Расходы',
        requests: 'Заявки',
        resources: 'Ресурсы',
        service: 'Сервис',
        executive: 'Директорский кабинет',
        operations: 'Операционный пульт',
        nomenclature: 'Номенклатура и склад',
        analytics: 'Аналитика',
        kpi: 'KPI и мотивация',
        profile: 'Мой профиль',
        admin: 'Администрирование',
    };

    /* VIEW_ALIASES: [needle, view-id]. Сортировано по длине needle убыванием — длинные совпадают первыми.
       Никаких client360/contract360/project — они требуют контекста и без него ломаются. */
    const VIEW_ALIASES = [
        ['база знаний', 'knowledge'],
        ['проводк', 'accounting'],
        ['бухгалт', 'accounting'],
        ['экспертн', 'analytics'],
        ['аналитик', 'analytics'],
        ['операцион', 'operations'],
        ['производст', 'production'],
        ['номенклат', 'nomenclature'],
        ['снабжен', 'supply'],
        ['закуп', 'supply'],
        ['поставщик', 'supply'],
        ['мессендж', 'messenger'],
        ['переписк', 'messenger'],
        ['чат', 'messenger'],
        ['чаты', 'messenger'],
        ['продаж', 'sales'],
        ['воронк', 'sales'],
        ['сделк', 'deals'],
        ['лид', 'leads'],
        ['база развития', 'prospecting'],
        ['обзвон', 'prospecting'],
        ['цех', 'production'],
        ['расход', 'expenses'],
        ['затрат', 'expenses'],
        ['заявк', 'requests'],
        ['тикет', 'requests'],
        ['обращен', 'requests'],
        ['ресурс', 'resources'],
        ['персонал', 'resources'],
        ['сотрудник', 'resources'],
        ['сервис', 'service'],
        ['обслужив', 'service'],
        ['наряд', 'service'],
        ['директор', 'executive'],
        ['boardroom', 'executive'],
        ['пульт', 'operations'],
        ['финанс', 'finance'],
        ['деньг', 'finance'],
        ['платеж', 'finance'],
        ['оплат', 'finance'],
        ['касс', 'finance'],
        ['1с', 'accounting'],
        ['эпл', 'accounting'],
        ['упд', 'accounting'],
        ['обмен', 'accounting'],
        ['коннект', 'integrations'],
        ['интеграц', 'integrations'],
        ['клиент', 'clients'],
        ['контрагент', 'clients'],
        ['заказчик', 'clients'],
        ['все проекты', 'dashboard'],
        ['проект', 'dashboard'],
        ['portfolio', 'dashboard'],
        ['документ', 'documents'],
        ['файл', 'documents'],
        ['реестр', 'documents'],
        ['задач', 'tasks'],
        ['поруч', 'tasks'],
        ['todo', 'tasks'],
        ['соглас', 'approvals'],
        ['виза', 'approvals'],
        ['маршрут', 'approvals'],
        ['претенз', 'claims'],
        ['рекламац', 'claims'],
        ['знани', 'knowledge'],
        ['wiki', 'knowledge'],
        ['почт', 'emails'],
        ['email', 'emails'],
        ['письм', 'emails'],
        ['встреч', 'meetings'],
        ['календар', 'meetings'],
        ['митинг', 'meetings'],
        ['склад', 'nomenclature'],
        ['товар', 'nomenclature'],
        ['остатк', 'nomenclature'],
        ['отчет', 'analytics'],
        ['kpi', 'kpi'],
        ['мотивац', 'kpi'],
        ['профил', 'profile'],
        ['настрой', 'profile'],
        ['админ', 'admin'],
        ['пользоват', 'admin'],
        ['дашборд', 'dashboard'],
        ['главная', 'dashboard'],
    ];

    const SECTION_HELP = {
        clients: 'База клиентов — справочник контрагентов с ИНН и контактами. Из карточки откроется досье 360.',
        documents: 'Документы — единый реестр входящих, исходящих и внутренних: версии, регистрация, подписи.',
        prospecting: 'База развития — отдельный контур для холодной базы: импорт, назначение менеджерам, статусы обработки, план-факт и отчёты.',
        leads: 'Лиды — первичные обращения и потенциальные клиенты перед переводом в сделки.',
        deals: 'Сделки — коммерческий pipeline: карточки сделок, этапы, ответственные и следующие действия.',
        client360: 'Клиент 360 — досье клиента: проекты, документы, сделки, финансы и коммуникации по одному контрагенту.',
        contract360: 'Договоры 360 — реестр и карточки договоров, задачи, документы и контроль исполнения.',
        tasks: 'Поручения — рабочий список задач: ответственные, дедлайны, статусы и контроль сроков.',
        approvals: 'Согласования — маршруты с визами: входящие, мои, завершённые. Можно запустить процесс из шаблона BPMN.',
        claims: 'Претензии — учёт рекламаций и реакций: сроки ответа, статусы, ответственные.',
        knowledge: 'База знаний — внутренние статьи, инструкции, регламенты с поиском.',
        messenger: 'Мессенджер — внутренние чаты, упоминания, групповые комнаты по проектам.',
        emails: 'Почта — корпоративная переписка с привязкой к проектам и клиентам.',
        meetings: 'Встречи — календарь, протоколы, повестки и решения.',
        finance: 'Финансы — платежи и поступления: статус, просрочка, привязка к проекту и контрагенту.',
        accounting: 'Бухгалтерия — проводки, акты, счета, синхронизация с 1С.',
        integrations: 'Интеграции — подключённые системы и состояние обмена.',
        supply: 'Снабжение — заявки, заказы поставщикам, графики поставок.',
        sales: 'Продажи — документы реализации: счета, акты, УПД, отгрузка, оплата и закрывающие документы.',
        production: 'Производство — заказы-наряды, цеха, производственный план.',
        expenses: 'Расходы — бюджет, согласования трат, факт.',
        requests: 'Заявки — внутренние и клиентские обращения.',
        resources: 'Ресурсы — занятость сотрудников, графики, замещение.',
        service: 'Сервис — наряды на обслуживание, SLA, выезды.',
        executive: 'Директорский кабинет — карта проблем, узкие места, KPI компании.',
        operations: 'Операционный пульт — сводка по операциям и статусам ключевых процессов.',
        nomenclature: 'Номенклатура и склад — справочник товаров, остатки, движения.',
        analytics: 'Аналитика — графики, срезы, экспорт.',
        kpi: 'KPI и мотивация — показатели сотрудников и команд, бонусы.',
        profile: 'Мой профиль — личные данные, права, уведомления.',
        admin: 'Администрирование — пользователи, роли, права, настройки системы.',
        dashboard: 'Все проекты / главный дашборд — реестр сделок и лента входящих, мои дела, быстрые действия.',
    };

    const SYSTEM_GUIDE = {
        tasks: {
            title: 'Поручения',
            contains: 'Задачи, поручители, исполнители, дедлайны, статусы, чат задачи и контроль просрочек.',
            buttons: 'Верхняя кнопка «Поручение» создает новую задачу. Внутри раздела доступны фильтры, карточка задачи и статусы.',
            create: 'Нажми верхнюю кнопку «Поручение», заполни название, исполнителя, срок и описание.',
            search: 'Ищи через глобальный поиск сверху или фильтры в разделе «Поручения».',
            access: 'Доступ есть у рабочих ролей; видимость зависит от роли и назначения.',
        },
        messenger: {
            title: 'Мессенджер',
            contains: 'Лента компании, объявления, опросы и корпоративные чаты.',
            buttons: 'Вверху есть «Лента», «Чаты» и «+ Чат». Для переписки открой вкладку «Корпоративные чаты».',
            create: 'Нажми «+ Чат», задай название и участников.',
            search: 'Открой «Мессенджер» и выбери чат слева.',
            access: 'Доступ к чатам зависит от роли, отдела и участников чата.',
        },
        deals: {
            title: 'Сделки',
            contains: 'Карточки сделок, этапы pipeline, сумма, маржа, ответственный, следующее действие.',
            buttons: 'Кнопка «+ Новая сделка», поиск по сделкам, фильтр стадий, ответственных, режим реестр/канбан.',
            create: 'Открой «Сделки» и нажми «+ Новая сделка».',
            search: 'Ищи по названию сделки, клиенту или номеру КП в строке поиска раздела или глобальном поиске.',
            access: 'Обычно доступен коммерческому контуру, менеджерам и руководителям.',
        },
        sales: {
            title: 'Продажи',
            contains: 'Документы реализации: счета, акты, УПД, статусы оплаты, отправки и отгрузки.',
            buttons: 'Быстрые кнопки «Счёт», «Акт», «УПД», форма нового документа и реестр документов реализации.',
            create: 'Выбери тип документа, проект/контрагента, сумму, статус и нажми «Сохранить».',
            search: 'Ищи документ реализации в реестре продаж или через глобальный поиск.',
            access: 'Доступ зависит от роли и прав на продажи/финансы.',
        },
        prospecting: {
            title: 'База развития',
            contains: 'Холодная база, импорт Bitrix/Excel, назначение менеджерам, статусы обработки, отчеты и контроль качества базы.',
            buttons: 'Импорт, предпросмотр импорта, фильтры, быстрые действия по строке, отчет менеджера, директорская сводка.',
            create: 'Загрузи файл или создай запись вручную, затем назначь менеджера и дату следующего контакта.',
            search: 'Ищи по компании, контакту, телефону, email, заметкам.',
            access: 'Менеджеры видят рабочую базу, руководители и директор видят контроль и сводки.',
        },
        executive: {
            title: 'Директорский кабинет',
            contains: 'Управленческие сводки, риски, узкие места, просрочки, финансы, производство и операционный контроль.',
            buttons: 'Переходы в финансы, производство, склад/НСИ, операционный центр и проблемные зоны.',
            create: 'Раздел не для создания записей, а для контроля и перехода к источнику проблемы.',
            search: 'Используй карточки проблем и кнопки перехода в связанные разделы.',
            access: 'Доступен директору и руководителям с соответствующими правами.',
        },
    };

    const QUICK_DEFAULT = [
        { icon: 'pulse', label: 'Сводка', q: 'сводка' },
        { icon: 'cash', label: 'Финансы', q: 'финансы' },
        { icon: 'flag', label: 'Риски', q: 'риски' },
        { icon: 'cash', label: 'Просрочки', q: 'финансы просрочки' },
        { icon: 'pulse', label: 'P&L и ДДС', q: 'p&l ддс' },
        { icon: 'folder', label: 'Мои проекты', q: 'мои проекты' },
        { icon: 'check', label: 'Мои задачи', q: 'мои задачи' },
        { icon: 'check', label: 'Согласования', q: 'мои согласования' },
        { icon: 'cash', label: 'Обмен с 1С', q: 'обмен 1с' },
        { icon: 'folder', label: 'Документы', q: 'документы' },
        { icon: 'folder', label: 'Клиенты', q: 'клиенты' },
        { icon: 'help', label: 'Как создать проект?', q: 'как создать проект' },
        { icon: 'help', label: 'Помощь', q: 'помощь' },
    ];

    const QUICK_VISIBLE_COUNT = 3;

    const CATEGORY_PROMPTS = {
        projects: ['Сколько активных проектов?', 'Покажи проекты в работе', 'Найди проект Демо', 'Как создать проект?'],
        finance: ['Сколько просрочек по платежам?', 'Сумма открытых платежей', 'Что в бухгалтерии?', 'Открой финансы'],
        documents: ['Сколько документов?', 'Как зарегистрировать документ?', 'Найди документ', 'Открой реестр'],
        tasks: ['Мои активные задачи', 'У кого больше задач?', 'Как назначить поручение?', 'Открой задачи'],
        approvals: ['Что в согласованиях?', 'Старые висящие визы', 'Как запустить маршрут?', 'Открой согласования'],
        risks: ['Карта проблем', 'Главные узкие места', 'Открой директорский кабинет'],
    };

    /* ---------- утилиты ---------- */

    const $ = sel => document.querySelector(sel);
    const $$ = sel => Array.from(document.querySelectorAll(sel));

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function asArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function tryParse(json) {
        if (!json) return null;
        try { return JSON.parse(json); } catch (_) { return null; }
    }

    function loadHistory() {
        const data = tryParse(localStorage.getItem(STORAGE_KEY));
        return Array.isArray(data) ? data.slice(-MAX_HISTORY) : [];
    }

    function saveHistory(messages) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-MAX_HISTORY))); }
        catch (_) { /* квоту переполнили — игнор */ }
    }

    function fmtMoney(value) {
        if (typeof formatMoney === 'function') return formatMoney(Number(value || 0));
        return `${Number(value || 0).toLocaleString('ru-RU')} ₽`;
    }

    function fmtNumber(value) {
        return Number(value || 0).toLocaleString('ru-RU');
    }

    function plural(n, forms) {
        const a = Math.abs(Number(n)) % 100;
        const b = a % 10;
        if (a > 10 && a < 20) return forms[2];
        if (b > 1 && b < 5) return forms[1];
        if (b === 1) return forms[0];
        return forms[2];
    }

    function readVar(name) {
        try { return window[name]; } catch (_) { return undefined; }
    }

    /* ---------- API fetch + кеш ----------
       Если глобальная DB пуста (пользователь не открывал раздел) —
       тянем напрямую через apiCall и кладём в window, чтобы и сами,
       и дальнейшая навигация не дёргали повторно.
    */
    const apiCache = {};      // ключ → результат
    const apiPromises = {};   // ключ → Promise (защита от гонок)

    function apiAvailable() {
        return typeof window.apiCall === 'function';
    }

    async function apiFetch(endpoint) {
        if (!apiAvailable()) return null;
        if (apiCache[endpoint] !== undefined) return apiCache[endpoint];
        if (apiPromises[endpoint]) return apiPromises[endpoint];
        const promise = (async () => {
            try {
                const result = await window.apiCall(endpoint);
                if (result && result.error) { apiCache[endpoint] = null; return null; }
                apiCache[endpoint] = result;
                return result;
            } catch (_) {
                apiCache[endpoint] = null;
                return null;
            } finally {
                delete apiPromises[endpoint];
            }
        })();
        apiPromises[endpoint] = promise;
        return promise;
    }

    /* Загружает недостающие DB по тегам нужных групп (parallel). */
    async function ensureLoaded(tags) {
        const tasks = [];
        const u = readVar('currentUser');
        const wantsAll = tags.includes('all');

        if ((wantsAll || tags.includes('finance')) && !readVar('financeSummaryDB')) {
            tasks.push(apiFetch('/finance/summary').then(r => { if (r) window.financeSummaryDB = r; }));
        }
        if ((wantsAll || tags.includes('finance-payments')) && !asArray(readVar('financePaymentsDB')).length) {
            tasks.push(apiFetch('/finance/payments').then(r => { if (Array.isArray(r)) window.financePaymentsDB = r; }));
        }
        if ((wantsAll || tags.includes('finance-sync')) && !asArray(readVar('financeSyncQueueDB')).length) {
            tasks.push(apiFetch('/finance/sync_queue?limit=50').then(r => { if (Array.isArray(r)) window.financeSyncQueueDB = r; }));
            tasks.push(apiFetch('/finance/sync_conflicts?limit=50').then(r => { if (Array.isArray(r)) window.financeSyncConflictsDB = r; }));
        }
        if ((wantsAll || tags.includes('executive')) && !readVar('executiveSummaryDB')) {
            tasks.push(apiFetch('/executive/summary').then(r => { if (r) window.executiveSummaryDB = r; }));
        }
        if ((wantsAll || tags.includes('projects')) && !asArray(readVar('projectsDB')).length && u) {
            const url = `/projects?user_name=${encodeURIComponent(u.name || '')}&user_role=${encodeURIComponent(u.role || '')}&is_head=${u.is_head || 0}`;
            tasks.push(apiFetch(url).then(r => {
                if (Array.isArray(r)) {
                    window.projectsDB = typeof normalizeProjectCollection === 'function' ? normalizeProjectCollection(r) : r;
                }
            }));
        }
        if ((wantsAll || tags.includes('clients')) && !asArray(readVar('clientsDB')).length) {
            tasks.push(apiFetch('/clients').then(r => { if (Array.isArray(r)) window.clientsDB = r; }));
        }
        if ((wantsAll || tags.includes('leads')) && !asArray(readVar('crmLeadsDB')).length) {
            tasks.push(apiFetch('/crm/leads').then(r => { if (Array.isArray(r)) window.crmLeadsDB = r; }));
        }
        if ((wantsAll || tags.includes('deals')) && !asArray(readVar('crmDealsDB')).length) {
            tasks.push(apiFetch('/crm/deals').then(r => { if (Array.isArray(r)) window.crmDealsDB = r; }));
        }
        if ((wantsAll || tags.includes('documents')) && !asArray(readVar('documentsDB')).length) {
            tasks.push(apiFetch('/documents').then(r => { if (Array.isArray(r)) window.documentsDB = r; }));
        }
        if ((wantsAll || tags.includes('tasks')) && !asArray(readVar('tasksDB')).length) {
            tasks.push(apiFetch('/tasks').then(r => { if (Array.isArray(r)) window.tasksDB = r; }));
        }
        if ((wantsAll || tags.includes('approvals')) && !asArray(readVar('approvalsDB')).length) {
            tasks.push(apiFetch('/approvals').then(r => { if (Array.isArray(r)) window.approvalsDB = r; }));
        }
        if ((wantsAll || tags.includes('claims')) && !asArray(readVar('claimsDB')).length) {
            tasks.push(apiFetch('/claims').then(r => { if (Array.isArray(r)) window.claimsDB = r; }));
        }
        if ((wantsAll || tags.includes('knowledge')) && !asArray(readVar('knowledgeDB')).length) {
            tasks.push(apiFetch('/knowledge').then(r => { if (Array.isArray(r)) window.knowledgeDB = r; }));
        }
        if ((wantsAll || tags.includes('meetings')) && !asArray(readVar('meetingsDB')).length) {
            tasks.push(apiFetch('/meetings').then(r => { if (Array.isArray(r)) window.meetingsDB = r; }));
        }
        if ((wantsAll || tags.includes('expenses')) && !asArray(readVar('expenseRequestsDB')).length) {
            tasks.push(apiFetch('/expenses/requests').then(r => { if (Array.isArray(r)) window.expenseRequestsDB = r; }));
        }
        if ((wantsAll || tags.includes('requests')) && !asArray(readVar('internalRequestsDB')).length) {
            tasks.push(apiFetch('/internal_requests').then(r => { if (Array.isArray(r)) window.internalRequestsDB = r; }));
        }
        if ((wantsAll || tags.includes('resources')) && !asArray(readVar('resourceAllocationsDB')).length) {
            tasks.push(apiFetch('/resources/allocations').then(r => { if (Array.isArray(r)) window.resourceAllocationsDB = r; }));
        }
        if ((wantsAll || tags.includes('service')) && !asArray(readVar('serviceCasesDB')).length) {
            tasks.push(apiFetch('/service/cases').then(r => { if (Array.isArray(r)) window.serviceCasesDB = r; }));
        }
        if ((wantsAll || tags.includes('contracts')) && !asArray(readVar('contractRegistryDB')).length) {
            tasks.push(apiFetch('/contracts').then(r => { if (Array.isArray(r)) window.contractRegistryDB = r; }));
        }
        if ((wantsAll || tags.includes('notifications')) && !asArray(readVar('notificationsDB')).length) {
            tasks.push(apiFetch('/notifications?limit=80').then(r => { if (Array.isArray(r)) window.notificationsDB = r; }));
        }
        if ((wantsAll || tags.includes('outreach')) && !asArray(readVar('outreachProspectsDB')).length) {
            tasks.push(apiFetch('/outreach/prospects').then(r => { if (Array.isArray(r)) window.outreachProspectsDB = r; }));
        }
        if ((wantsAll || tags.includes('outreach-control')) && !asArray(readVar('outreachControlDB')).length) {
            tasks.push(apiFetch('/outreach/manager_control').then(r => { if (Array.isArray(r)) window.outreachControlDB = r; }));
        }
        await Promise.all(tasks);
    }

    /* Возвращает список тегов данных, нужных для ответа на вопрос. */
    function tagsForQuery(lower) {
        const tags = new Set();
        if (/сводк|итог|что сейчас|обзор|статус компани/.test(lower)) {
            tags.add('finance'); tags.add('executive'); tags.add('projects'); tags.add('tasks'); tags.add('approvals'); tags.add('documents');
        }
        if (/риск|карта проблем|узк|боттлнек/.test(lower)) tags.add('executive');
        if (/обмен|1с|очеред|синхрониз|конфликт/.test(lower)) { tags.add('finance'); tags.add('finance-sync'); }
        if (/p&l|pnl|пнл|p\s*and\s*l|ддс|кассов(ый|ого) разрыв/.test(lower)) tags.add('finance');
        if (/финанс|деньг|платеж|оплат|касс|просроч|дебиторк|кредиторк|поступлен|выплат/.test(lower)) {
            tags.add('finance'); tags.add('finance-payments');
        }
        if (/проект/.test(lower)) tags.add('projects');
        if (/сделк|pipeline|воронк/.test(lower)) tags.add('deals');
        if (/лид/.test(lower)) tags.add('leads');
        if (/база развития|обзвон|менеджер|отчет|отчёт|перв(ый|ого) контакт|sla/.test(lower)) { tags.add('outreach'); tags.add('outreach-control'); }
        if (/контролировать|директору|кто просрочил|не сдал|сдали отчет|сдали отчёт|показать директору/.test(lower)) { tags.add('outreach-control'); tags.add('tasks'); tags.add('finance'); tags.add('executive'); tags.add('approvals'); }
        if (/клиент|контрагент|заказчик/.test(lower)) tags.add('clients');
        if (/документ|файл|реестр/.test(lower)) tags.add('documents');
        if (/задач|поруч/.test(lower)) tags.add('tasks');
        if (/соглас|виза|маршрут/.test(lower)) tags.add('approvals');
        if (/претенз|рекламац/.test(lower)) tags.add('claims');
        if (/знани|wiki|инструкц|статья/.test(lower)) tags.add('knowledge');
        if (/встреч|календар|митинг/.test(lower)) tags.add('meetings');
        if (/расход|затрат|бюджет/.test(lower)) tags.add('expenses');
        if (/заявк|тикет|обращен/.test(lower)) tags.add('requests');
        if (/ресурс|нагрузк|загрузк|сотрудник/.test(lower)) tags.add('resources');
        if (/сервис|обслужив|наряд/.test(lower)) tags.add('service');
        if (/договор|контракт/.test(lower)) tags.add('contracts');
        if (/уведомлен|нотификац|непрочитан/.test(lower)) tags.add('notifications');
        if (/найд|найти|покаж|где .*|карточк|открой/.test(lower)) {
            tags.add('projects'); tags.add('clients'); tags.add('documents'); tags.add('tasks');
            tags.add('contracts'); tags.add('deals'); tags.add('leads'); tags.add('outreach');
        }
        return Array.from(tags);
    }

    function dataSnapshot() {
        return {
            projects: asArray(readVar('projectsDB')),
            leads: asArray(readVar('crmLeadsDB')),
            deals: asArray(readVar('crmDealsDB')),
            clients: asArray(readVar('clientsDB')),
            documents: asArray(readVar('documentsDB')),
            tasks: asArray(readVar('tasksDB')),
            approvals: asArray(readVar('approvalsDB')),
            claims: asArray(readVar('claimsDB')),
            payments: asArray(readVar('financePaymentsDB')),
            financeSummary: readVar('financeSummaryDB') || null,
            financeJournal: asArray(readVar('financeJournalDB')),
            financeAnalytics: readVar('financeAnalyticsDB') || null,
            financeErp: readVar('financeErpSummaryDB') || null,
            financeSyncQueue: asArray(readVar('financeSyncQueueDB')),
            financeSyncConflicts: asArray(readVar('financeSyncConflictsDB')),
            production: asArray(readVar('productionOrdersDB')),
            stock: asArray(readVar('stockMovementsDB')),
            executive: readVar('executiveSummaryDB') || null,
            contracts: asArray(readVar('contractRegistryDB')),
            expenses: asArray(readVar('expenseRequestsDB')),
            internalRequests: asArray(readVar('internalRequestsDB')),
            resources: asArray(readVar('resourceAllocationsDB')),
            service: asArray(readVar('serviceCasesDB')),
            budgets: asArray(readVar('budgetLinesDB')),
            meetings: asArray(readVar('meetingsDB')),
            emails: asArray(readVar('emailsDB')),
            knowledge: asArray(readVar('knowledgeDB')),
            workflows: asArray(readVar('workflowDefinitionsDB')),
            workflowInstances: asArray(readVar('workflowInstancesDB')),
            notifications: asArray(readVar('notificationsDB')),
            outreachProspects: asArray(readVar('outreachProspectsDB')),
            outreachControl: asArray(readVar('outreachControlDB')),
            user: readVar('currentUser') || null,
            currentView: readVar('__navCurrentView') || '',
        };
    }

    function pickFields(row, fields) {
        const result = {};
        fields.forEach(field => {
            const value = row?.[field];
            if (value !== undefined && value !== null && value !== '') result[field] = value;
        });
        return result;
    }

    function compactAssistantContext(question, tags) {
        const d = dataSnapshot();
        const limit = 12;
        return {
            question: String(question || '').slice(0, 500),
            tags: asArray(tags).slice(0, 12),
            user: pickFields(d.user || {}, ['name', 'email', 'role', 'is_head']),
            navigation: {
                tasks: 'Левое меню: «Поручения». Верхняя кнопка «Поручение» создает новое поручение.',
                messenger: 'Левое меню: «Мессенджер», внутри вкладка «Корпоративные чаты».',
                deals: 'Левое меню: «Сделки». Это карточки сделок и pipeline.',
                sales: 'Левое меню: «Продажи». Это счета, акты, УПД, отгрузка и реализация.',
                prospecting: 'Левое меню: «База развития». Это импорт базы, обзвон, менеджеры и отчеты.',
                executive: 'Левое меню: «Директор». Это директорский кабинет, риски и управленческие сводки.',
            },
            counts: {
                projects: d.projects.length,
                clients: d.clients.length,
                documents: d.documents.length,
                tasks: d.tasks.length,
                approvals: d.approvals.length,
                payments: d.payments.length,
                contracts: d.contracts.length,
                meetings: d.meetings.length,
                notifications: d.notifications.length,
                leads: d.leads.length,
                deals: d.deals.length,
                outreachProspects: d.outreachProspects.length,
                currentView: d.currentView || '',
            },
            financeSummary: d.financeSummary || null,
            executive: d.executive || null,
            projects: d.projects.slice(0, limit).map(row => pickFields(row, ['id', 'name', 'client', 'manager', 'status', 'progress', 'budget', 'costs'])),
            leads: d.leads.slice(0, limit).map(row => pickFields(row, ['id', 'title', 'client_name', 'contact_name', 'status', 'source', 'next_action'])),
            deals: d.deals.slice(0, limit).map(row => pickFields(row, ['id', 'title', 'client_name', 'contract_number', 'stage', 'amount', 'responsible', 'next_action'])),
            tasks: d.tasks.slice(0, limit).map(row => pickFields(row, ['id', 'title', 'executor', 'deadline', 'status', 'priority'])),
            approvals: d.approvals.slice(0, limit).map(row => pickFields(row, ['id', 'title', 'status', 'created_by', 'current_stage', 'updated_at'])),
            documents: d.documents.slice(0, limit).map(row => pickFields(row, ['id', 'title', 'type', 'status', 'number', 'date', 'author'])),
            payments: d.payments.slice(0, limit).map(row => pickFields(row, ['id', 'title', 'kind', 'amount', 'currency', 'due_date', 'status', 'client_id', 'project_id'])),
            clients: d.clients.slice(0, limit).map(row => pickFields(row, ['id', 'name', 'inn', 'contact'])),
            contracts: d.contracts.slice(0, limit).map(row => pickFields(row, ['id', 'contract_number', 'title', 'status', 'amount', 'currency', 'manager_name'])),
            outreachControl: d.outreachControl.slice(0, limit).map(row => pickFields(row, ['name', 'email', 'plan', 'processed', 'calls', 'emails', 'overdue', 'first_contact_overdue', 'warm', 'leads', 'submitted'])),
            notifications: d.notifications.slice(0, limit).map(row => pickFields(row, ['id', 'title', 'message', 'is_read', 'created_at'])),
        };
    }

    function assistantOutOfScopeAnswer() {
        return {
            html: '<p>Я отвечаю только по Korda CRM: разделы, задачи, сроки, документы, проекты, клиенты, финансы и рабочие процессы. Сформулируй вопрос по системе.</p>',
        };
    }

    function isAssistantDomainQuestion(lower, tags) {
        if (asArray(tags).length) return true;
        if (findRoute(lower)) return true;
        if (/^(привет|здрав|добр|hello|hi|hey|йоу)\b/.test(lower)) return true;
        if (/помощь|help|что ты умеешь|какие команды|справка|спасиб|благодар|thanks/.test(lower)) return true;
        return /korda|корда|crm|црм|систем|раздел|карточк|создать|сделать|добавить|загруз|импорт|экспорт|отчет|отчёт|срок|дедлайн|задач|поруч|проект|клиент|контрагент|документ|договор|соглас|финанс|платеж|оплат|менеджер|директор|база|лид|bitrix|битрикс|1с|права|роль|пользоват|настрой|уведомл|встреч|почт|склад|производ|сервис|просроч|найд|покаж|открой/.test(lower);
    }

    async function askServerAi(question, tags) {
        if (!apiAvailable()) return null;
        try {
            const result = await window.apiCall('/assistant/ask', 'POST', {
                question,
                context: compactAssistantContext(question, tags),
            });
            if (!result || result.error || !result.answer) return null;
            return {
                html: `<p>${escapeHtml(result.answer).replace(/\n/g, '<br>')}</p>`,
                actions: [],
                ai: true,
            };
        } catch (_) {
            return null;
        }
    }

    function fmNum(value) { return Number(value || 0); }
    function hasNonZero(metrics, keys) {
        return keys.some(k => fmNum(metrics?.[k]) !== 0);
    }

    function statusLower(item, key = 'status') {
        return String(item?.[key] || '').toLowerCase();
    }

    function timeOfDayGreeting() {
        const h = new Date().getHours();
        if (h < 5) return 'Доброй ночи';
        if (h < 12) return 'Доброе утро';
        if (h < 18) return 'Добрый день';
        return 'Добрый вечер';
    }

    function userFirstName() {
        const name = String(typeof currentUser !== 'undefined' && currentUser?.name || '').trim();
        if (!name) return '';
        const parts = name.split(/\s+/);
        return parts.length > 1 ? parts[1] : parts[0];
    }

    function viewExistsInRoute(view) {
        return Object.prototype.hasOwnProperty.call(SECTION_HELP, view) || Object.prototype.hasOwnProperty.call(VIEW_LABELS, view);
    }

    /* ---------- intent matching ---------- */

    function normalize(text) {
        return String(text || '')
            .toLowerCase()
            .replace(/ё/g, 'е')
            .replace(/[^\p{L}\p{N}\s/]/gu, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function findRoute(text) {
        const lower = normalize(text);
        if (/чат|мессендж|переписк|написать|поговорить|связаться/.test(lower)) return 'messenger';
        let best = null;
        let bestLen = 0;
        for (const [needle, view] of VIEW_ALIASES) {
            if (lower.includes(needle) && needle.length > bestLen) {
                best = view; bestLen = needle.length;
            }
        }
        return best;
    }

    function routeGuide(view) {
        const label = VIEW_LABELS[view] || view;
        const guides = {
            tasks: {
                title: 'Поручения',
                text: 'Поручения находятся в левом меню: пункт «Поручения». Там список задач, ответственные, дедлайны и статусы. Быстро создать поручение можно верхней кнопкой «Поручение».',
            },
            messenger: {
                title: 'Мессенджер и чаты',
                text: 'Чаты находятся в левом меню: «Мессенджер». Внутри открой вкладку «Корпоративные чаты». Там можно выбрать существующий чат или нажать «+ Чат».',
            },
            deals: {
                title: 'Сделки',
                text: 'Сделки находятся в левом меню в коммерческом контуре: пункт «Сделки». Для конкретной сделки также используй глобальный поиск сверху: введи название сделки, клиента или номер.',
            },
            sales: {
                title: 'Продажи',
                text: 'Раздел «Продажи» в левом меню отвечает за документы реализации: счета, акты, УПД, отгрузку и оплату. Это не то же самое, что карточки сделок.',
            },
            executive: {
                title: 'Директорский кабинет',
                text: 'Директорский кабинет находится в левом меню: пункт «Директор». Там карта проблем, план-факт, риски и управленческие сводки.',
            },
            prospecting: {
                title: 'База развития',
                text: 'База развития находится в левом меню рядом с клиентским контуром: пункт «База развития». Там импорт Bitrix/Excel, назначение менеджерам, статусы обработки и отчёты.',
            },
        };
        const guide = guides[view] || { title: label, text: `Открой левое меню и выбери раздел «${label}». Если раздел скрыт, проверь роль и права доступа в профиле или у администратора.` };
        return {
            html: `<p class="ka-msg-lead">${escapeHtml(guide.title)}</p><p>${escapeHtml(guide.text)}</p>`,
            actions: viewExistsInRoute(view) ? [{ label: `Открыть «${label}»`, target: view }] : [],
        };
    }

    function answerSystemNavigation(question) {
        const lower = normalize(question);
        const wantsLocation = /где|куда|как найти|как открыть|где находится|где это|путь|в каком раздел|открой|перейди|поговорить|написать|связаться/.test(lower);
        if (!wantsLocation) return null;
        const route = findRoute(lower);
        if (route) return routeGuide(route);
        return {
            html: '<p>Уточни, какой именно раздел или объект нужно найти: поручения, сделки, чаты, документы, финансы, клиент, договор или база развития.</p>',
            actions: [
                { label: 'Поручения', target: 'tasks' },
                { label: 'Сделки', target: 'deals' },
                { label: 'Чаты', target: 'messenger' },
            ],
        };
    }

    function fuzzyMatchRows(rows, query, fields) {
        const term = normalize(query)
            .replace(/найди|поиск|покажи|открой|карточк|проект|клиент|контрагент|документ|задач|плате(ж|жи)|где/g, '')
            .trim();
        if (!term) return rows.slice(0, 5);
        const tokens = term.split(' ').filter(t => t.length >= 2);
        if (!tokens.length) return rows.slice(0, 5);
        const scored = rows.map(row => {
            const haystack = fields.map(f => normalize(row?.[f] || '')).join(' ');
            let score = 0;
            tokens.forEach(t => { if (haystack.includes(t)) score += 1; });
            return { row, score };
        }).filter(x => x.score > 0);
        scored.sort((a, b) => b.score - a.score);
        return scored.slice(0, 6).map(x => x.row);
    }

    function currentViewKey() {
        const fromNav = String(readVar('__navCurrentView') || '').trim();
        if (fromNav) return fromNav;
        const visible = $$('.view-page').find(el => {
            try { return getComputedStyle(el).display !== 'none' && !el.hidden; } catch (_) { return false; }
        });
        return String(visible?.id || '').replace(/View$/, '');
    }

    function cleanObjectSearchQuery(question) {
        return normalize(question)
            .replace(/(^|\s)(найди|найти|покажи|показать|где|находится|находятся|открой|открыть|карточка|карточку|есть|у|меня|мой|мои|мою|мое|моё|это|этот|эта|эти|по|номер|номеру|раздел|разделе)(?=\s|$)/g, ' ')
            .replace(/(^|\s)(сделка|сделку|сделки|лид|лида|лиды|клиент|клиента|клиенты|контрагент|контрагента|контрагенты|договор|договора|договоры|контракт|контракты|документ|документа|документы|задача|задачу|задачи|поручение|поручения|проект|проекта|проекты)(?=\s|$)/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function objectSearchTokens(value) {
        return normalize(value).split(' ').filter(token => token.length >= 2);
    }

    function rowTitle(row, fallback) {
        return row?.title || row?.name || row?.contract_number || row?.number || row?.company_name || fallback;
    }

    function rowSearchScore(row, fields, query) {
        const term = normalize(query);
        const tokens = objectSearchTokens(term);
        if (!tokens.length) return 0;
        const haystack = fields.map(field => normalize(row?.[field] || '')).join(' ');
        let score = haystack.includes(term) ? 8 : 0;
        tokens.forEach(token => {
            if (haystack.includes(token)) score += token.length >= 4 ? 2 : 1;
        });
        return score;
    }

    function objectSearchCollections(lower, d) {
        const collections = [];
        const add = item => {
            if (asArray(item.rows).length) collections.push(item);
        };
        const explicit = /сделк|лид|клиент|контрагент|договор|контракт|документ|задач|поруч|проект/.test(lower);
        if (/сделк|воронк|pipeline/.test(lower) || !explicit) add({
            type: 'deal', view: 'deals', label: 'Сделка', rows: d.deals,
            fields: ['title', 'client_name', 'contract_number', 'stage', 'responsible', 'next_action'],
            meta: row => [row.contract_number ? `№ ${row.contract_number}` : null, row.client_name, row.stage || row.status].filter(Boolean).join(' · '),
        });
        if (/лид/.test(lower) || !explicit) add({
            type: 'lead', view: 'leads', label: 'Лид', rows: d.leads,
            fields: ['title', 'client_name', 'contact_name', 'phone', 'email', 'source', 'next_action'],
            meta: row => [row.client_name, row.contact_name, row.source || row.status].filter(Boolean).join(' · '),
        });
        if (/клиент|контрагент|заказчик/.test(lower) || !explicit) add({
            type: 'client', view: 'clients', label: 'Клиент', rows: d.clients,
            fields: ['name', 'inn', 'contact', 'contacts', 'email', 'phone'],
            meta: row => [row.inn ? `ИНН ${row.inn}` : null, row.contact || row.email || row.phone].filter(Boolean).join(' · '),
        });
        if (/договор|контракт/.test(lower) || !explicit) add({
            type: 'contract', view: 'contract360', label: 'Договор', rows: d.contracts,
            fields: ['contract_number', 'number', 'title', 'name', 'client_name', 'counterparty', 'manager_name', 'status'],
            meta: row => [row.contract_number || row.number ? `№ ${row.contract_number || row.number}` : null, row.client_name || row.counterparty, row.status].filter(Boolean).join(' · '),
        });
        if (/документ|файл|реестр/.test(lower) || !explicit) add({
            type: 'document', view: 'documents', label: 'Документ', rows: d.documents,
            fields: ['title', 'name', 'subject', 'number', 'type', 'status', 'author', 'client_name', 'correspondent'],
            meta: row => [row.number ? `№ ${row.number}` : null, row.type, row.status].filter(Boolean).join(' · '),
        });
        if (/задач|поруч/.test(lower) || !explicit) add({
            type: 'task', view: 'tasks', label: 'Поручение', rows: d.tasks,
            fields: ['title', 'name', 'description', 'executor', 'author', 'deadline', 'status', 'project_name'],
            meta: row => [row.executor, row.deadline, row.status].filter(Boolean).join(' · '),
        });
        if (/проект/.test(lower) || !explicit) add({
            type: 'project', view: 'dashboard', label: 'Проект', rows: d.projects,
            fields: ['name', 'contract', 'client', 'client_name', 'manager', 'responsible', 'status', 'stage'],
            meta: row => [row.client_name || row.client, row.manager || row.responsible, row.status || row.stage].filter(Boolean).join(' · '),
        });
        return collections;
    }

    function answerObjectSearch(question) {
        const lower = normalize(question);
        if (!/(найд|найти|покаж|показать|где|находится|открой|карточк)/.test(lower)) return null;
        const query = cleanObjectSearchQuery(question);
        if (!objectSearchTokens(query).length) return null;
        const d = dataSnapshot();
        const matches = objectSearchCollections(lower, d).flatMap(collection => {
            return asArray(collection.rows).map(row => ({
                row,
                collection,
                score: rowSearchScore(row, collection.fields, query),
            })).filter(item => item.score > 0);
        }).sort((a, b) => b.score - a.score).slice(0, 6);
        if (!matches.length) return {
            html: `<p class="ka-msg-lead">Поиск по CRM</p><p>По запросу «${escapeHtml(query)}» ничего не нашёл в сделках, лидах, клиентах, договорах, документах, поручениях и проектах.</p><p class="ka-hint">Проверь написание или попробуй искать по ИНН, номеру договора, названию компании или части названия.</p>`,
            actions: [
                { label: 'Глобальный поиск', target: 'dashboard' },
                { label: 'База клиентов', target: 'clients' },
                { label: 'Сделки', target: 'deals' },
            ],
        };
        const items = matches.map(match => ({
            title: `${match.collection.label}: ${rowTitle(match.row, `#${match.row?.id || ''}`)}`,
            meta: match.collection.meta(match.row) || `ID ${match.row?.id || ''}`,
            tag: VIEW_LABELS[match.collection.view] || match.collection.view,
            tagTone: 'primary',
        }));
        const actions = matches.filter(match => match.row?.id).slice(0, 3).map(match => ({
            label: `Открыть ${match.collection.label.toLowerCase()}`,
            action: 'openEntity',
            entity: match.collection.type,
            id: match.row.id,
            view: match.collection.view,
        }));
        return {
            html: renderListAnswer(matches.length === 1 ? 'Нашёл объект' : `Нашёл ${matches.length} вариантов`, items),
            actions,
        };
    }

    function answerSystemGuide(question) {
        const lower = normalize(question);
        if (!/как|что нажать|что тут|что здесь|что внутри|кому доступ|где искать|создать/.test(lower)) return null;
        const view = findRoute(lower) || currentViewKey();
        const guide = SYSTEM_GUIDE[view];
        if (!guide) return null;
        return {
            html: `<p class="ka-msg-lead">${escapeHtml(guide.title)}</p>
<ul class="ka-bullets">
<li><strong>Что внутри:</strong> ${escapeHtml(guide.contains)}</li>
<li><strong>Основные кнопки:</strong> ${escapeHtml(guide.buttons)}</li>
<li><strong>Как создать:</strong> ${escapeHtml(guide.create)}</li>
<li><strong>Где искать:</strong> ${escapeHtml(guide.search)}</li>
<li><strong>Доступ:</strong> ${escapeHtml(guide.access)}</li>
</ul>`,
            actions: viewExistsInRoute(view) ? [{ label: `Открыть «${VIEW_LABELS[view] || guide.title}»`, target: view }] : [],
        };
    }

    function answerCurrentScreenQuestion(question) {
        const lower = normalize(question);
        if (!/тут|здесь|на этом экране|что нажать|что делать|как работать|что дальше/.test(lower)) return null;
        const view = currentViewKey();
        if (!view) return null;
        const guide = SYSTEM_GUIDE[view];
        if (guide) return answerSystemGuide(question);
        const label = VIEW_LABELS[view] || view;
        const help = SECTION_HELP[view] || `Ты сейчас в разделе «${label}».`;
        return {
            html: `<p class="ka-msg-lead">Ты сейчас в разделе «${escapeHtml(label)}»</p><p>${escapeHtml(help)}</p><p class="ka-hint">Задай вопрос по этому экрану: что создать, где искать или что контролировать.</p>`,
            actions: viewExistsInRoute(view) ? [{ label: `Открыть «${label}»`, target: view }] : [],
        };
    }

    function crmDateDaysUntil(value) {
        const raw = String(value || '').trim();
        if (!raw) return null;
        const normalized = raw.includes('.') ? raw.split('.').reverse().join('-') : raw.slice(0, 10);
        const date = new Date(`${normalized}T00:00:00`);
        if (Number.isNaN(date.getTime())) return null;
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        return Math.round((date - today) / 86400000);
    }

    function answerManagementCoach(question) {
        const lower = normalize(question);
        if (!/контролировать|директору|кто просрочил|не сдал|не сдали|сдали отчет|сдали отчёт|менеджер|sla|перв(ый|ого) контакт|причин|потер|дожать/.test(lower)) return null;
        const d = dataSnapshot();
        const managers = d.outreachControl;
        const missingReports = managers.filter(row => !row.submitted);
        const openTasks = d.tasks.filter(row => !['completed', 'done', 'closed'].includes(statusLower(row)));
        const overdueTasks = openTasks.filter(row => {
            const days = crmDateDaysUntil(row.deadline || row.due_date);
            return days !== null && days < 0;
        });
        const pendingApprovals = d.approvals.filter(row => ['pending', 'rework'].includes(statusLower(row)));
        const prospects = d.outreachProspects;
        const dueProspects = prospects.filter(row => ['warm', 'meeting', 'follow_up'].includes(String(row.status || '')) || row.is_due_today || row.is_overdue).slice(0, 6);

        if (/не сдал|не сдали|сдали отчет|сдали отчёт/.test(lower)) {
            const items = missingReports.slice(0, 8).map(row => ({
                title: row.name || row.email || 'Менеджер',
                meta: `${fmtNumber(row.overdue || 0)} просрочено · ${fmtNumber(row.warm || 0)} тёплых · SLA ${fmtNumber(row.first_contact_overdue || row.firstContactOverdue || 0)}`,
                tag: 'отчёт не сдан',
                tagTone: 'danger',
            }));
            return {
                html: renderListAnswer('Кто не сдал отчёт сегодня', items, { empty: 'По менеджерской сводке все отчёты за сегодня сданы.' }),
                actions: [{ label: 'Открыть базу развития', target: 'prospecting' }],
            };
        }

        if (/причин|потер|почему/.test(lower)) {
            const reasons = [
                ['Нет ответа', prospects.filter(row => String(row.status || '') === 'no_answer').length],
                ['Не интересно / отказ', prospects.filter(row => /do_not_contact|archived/.test(String(row.status || ''))).length],
                ['Нет контактов', prospects.filter(row => !String(row.phone || '').trim() && !String(row.email || '').trim()).length],
                ['Дубли', prospects.filter(row => String(row.status || '') === 'duplicate').length],
                ['В архиве', prospects.filter(row => String(row.status || '') === 'archived').length],
            ];
            return {
                html: renderListAnswer('Причины потерь по базе развития', reasons.map(([title, count]) => ({ title, meta: `${fmtNumber(count)} записей` }))),
                actions: [{ label: 'Открыть базу развития', target: 'prospecting' }],
            };
        }

        if (/дожать/.test(lower)) {
            const items = dueProspects.map(row => ({
                title: row.company_name || row.contact_name || `Запись #${row.id || ''}`,
                meta: [row.manager_name || row.manager_email, row.next_action_date || row.planned_contact_date, row.next_action].filter(Boolean).join(' · '),
                tag: row.status || 'к контакту',
                tagTone: row.is_overdue ? 'danger' : 'warning',
            }));
            return {
                html: renderListAnswer('Кого надо дожать сегодня', items, { empty: 'На сегодня нет тёплых/follow-up записей в загруженной базе.' }),
                actions: [{ label: 'Открыть базу развития', target: 'prospecting' }],
            };
        }

        const dept = managers.reduce((acc, row) => {
            acc.plan += Number(row.plan || 0);
            acc.processed += Number(row.processed || 0);
            acc.calls += Number(row.calls || 0);
            acc.emails += Number(row.emails || 0);
            acc.overdue += Number(row.overdue || 0);
            acc.sla += Number(row.first_contact_overdue || row.firstContactOverdue || 0);
            acc.warm += Number(row.warm || 0);
            acc.leads += Number(row.leads || 0);
            return acc;
        }, { plan: 0, processed: 0, calls: 0, emails: 0, overdue: 0, sla: 0, warm: 0, leads: 0 });
        const items = [
            { title: 'Менеджеры без отчёта', meta: `${fmtNumber(missingReports.length)} человек` },
            { title: 'SLA первого контакта 24ч', meta: `${fmtNumber(dept.sla)} нарушений` },
            { title: 'Просрочки менеджеров', meta: `${fmtNumber(dept.overdue)} записей` },
            { title: 'Просроченные поручения', meta: `${fmtNumber(overdueTasks.length)} задач` },
            { title: 'Висящие согласования', meta: `${fmtNumber(pendingApprovals.length)} согласований` },
        ];
        return {
            html: `<p class="ka-msg-lead">Что контролировать сегодня</p><p>Для директора важнее всего: отчёты менеджеров, SLA первого контакта, просрочки, тёплые клиенты и перевод в лиды.</p>` + renderListAnswer('', items),
            stats: [
                { label: 'План отдела', value: fmtNumber(dept.plan), tone: 'neutral' },
                { label: 'Обработано', value: fmtNumber(dept.processed), tone: dept.plan && dept.processed < dept.plan ? 'warning' : 'success' },
                { label: 'Звонки', value: fmtNumber(dept.calls), tone: 'neutral' },
                { label: 'Письма', value: fmtNumber(dept.emails), tone: 'neutral' },
                { label: 'Тёплые', value: fmtNumber(dept.warm), tone: 'primary' },
                { label: 'Лиды', value: fmtNumber(dept.leads), tone: 'success' },
                { label: 'SLA 24ч', value: fmtNumber(dept.sla), tone: dept.sla ? 'danger' : 'success' },
            ],
            actions: [
                { label: 'База развития', target: 'prospecting' },
                { label: 'Директорский кабинет', target: 'executive' },
                { label: 'Поручения', target: 'tasks' },
            ],
        };
    }

    /* ---------- ответы ---------- */

    function renderListAnswer(title, items, options = {}) {
        const intro = title ? `<p class="ka-msg-lead">${escapeHtml(title)}</p>` : '';
        if (!items.length) {
            return `${intro}<p class="ka-msg-empty">${escapeHtml(options.empty || 'Ничего не нашёл по этому запросу.')}</p>`;
        }
        const rows = items.map(item => {
            const meta = item.meta ? `<span class="ka-row-meta">${escapeHtml(item.meta)}</span>` : '';
            const tag = item.tag ? `<span class="ka-row-tag ka-row-tag--${item.tagTone || 'muted'}">${escapeHtml(item.tag)}</span>` : '';
            return `<li class="ka-row"><div class="ka-row-main"><strong>${escapeHtml(item.title)}</strong>${meta}</div>${tag}</li>`;
        }).join('');
        return `${intro}<ul class="ka-list">${rows}</ul>`;
    }

    function renderActions(actions) {
        if (!actions?.length) return '';
        return `<div class="ka-actions">${actions.map(a =>
            `<button type="button" class="ka-action" data-action="${escapeHtml(a.action || 'navigate')}" data-target="${escapeHtml(a.target || '')}" data-query="${escapeHtml(a.query || '')}" data-entity="${escapeHtml(a.entity || '')}" data-id="${escapeHtml(a.id || '')}" data-view="${escapeHtml(a.view || '')}">${escapeHtml(a.label)}</button>`
        ).join('')}</div>`;
    }

    function renderStats(stats) {
        if (!stats?.length) return '';
        return `<div class="ka-stats">${stats.map(s =>
            `<div class="ka-stat ka-stat--${s.tone || 'neutral'}"><span>${escapeHtml(s.label)}</span><strong>${escapeHtml(s.value)}</strong></div>`
        ).join('')}</div>`;
    }

    function answerGreeting() {
        const name = userFirstName();
        const hello = name ? `${timeOfDayGreeting()}, ${escapeHtml(name)}!` : `${timeOfDayGreeting()}!`;
        return {
            html: `<p class="ka-msg-lead">${hello}</p>
<p>Я Korda Assistant — помогу быстро посмотреть состояние проектов, документов, финансов и согласований. Задавай вопросы своими словами или нажимай чипы ниже.</p>`,
            actions: [
                { label: 'Сводка по компании', query: 'сводка' },
                { label: 'Где риски?', query: 'риски' },
                { label: 'Помощь', query: 'помощь' },
            ],
        };
    }

    function answerHelp() {
        return {
            html: `<p class="ka-msg-lead">Что я умею</p>
<ul class="ka-bullets">
<li><strong>Сводки.</strong> «сводка», «что сейчас», «итоги дня» — общий статус компании.</li>
<li><strong>Проекты.</strong> «активные проекты», «найди проект ___», «мои проекты».</li>
<li><strong>Финансы.</strong> «финансы», «просрочки», «дебиторка», «открытые поступления / выплаты», «кассовый разрыв».</li>
<li><strong>P&amp;L и ДДС.</strong> «p&amp;l», «ддс», «факт vs план».</li>
<li><strong>Обмен с 1С.</strong> «обмен 1с», «очередь», «конфликты».</li>
<li><strong>Задачи / согласования.</strong> «мои задачи», «висящие визы», «у кого больше задач».</li>
<li><strong>Документы / договоры / претензии.</strong> «сколько документов», «договор ___», «претензии».</li>
<li><strong>Расходы / заявки / ресурсы / сервис.</strong> «расходы», «открытые заявки», «нагрузка», «наряды».</li>
<li><strong>Встречи / почта / знания.</strong> «встречи», «почта», «база знаний ___».</li>
<li><strong>Производство / склад.</strong> «производство», «склад», «движения».</li>
<li><strong>Риски.</strong> «карта проблем», «узкие места», «директорские риски».</li>
<li><strong>Навигация.</strong> «открой ___» — любой раздел.</li>
<li><strong>Профиль.</strong> «кто я», «моя роль».</li>
<li><strong>Объяснения.</strong> «что такое ___», «как создать ___».</li>
</ul>
<p class="ka-hint">Слэш-команды: <code>/сводка</code>, <code>/риски</code>, <code>/финансы</code>, <code>/&lt;раздел&gt;</code>, <code>/очистить</code>, <code>/помощь</code>. Hotkeys: <kbd>Ctrl+/</kbd> — открыть, <kbd>Esc</kbd> — закрыть.</p>`,
        };
    }

    function answerSummary(d) {
        const fm = d.financeSummary?.metrics || {};
        const em = d.executive?.metrics || {};
        const activeProjects = fmNum(em.active_projects) || d.projects.filter(p => statusLower(p) === 'active').length;
        const archive = d.projects.filter(p => statusLower(p) === 'archive').length;
        const openTasks = d.tasks.filter(t => !['completed', 'done', 'closed'].includes(statusLower(t))).length;
        const myTasks = d.user ? d.tasks.filter(t => !['completed', 'done', 'closed'].includes(statusLower(t)) && String(t.executor || '').includes(d.user.name)).length : 0;
        const pendingApprovals = d.approvals.filter(a => ['pending', 'rework'].includes(statusLower(a))).length;
        const incoming = fmNum(fm.incoming_open);
        const outgoing = fmNum(fm.outgoing_open);
        const overdueRecv = fmNum(fm.overdue_receivables);
        const drafts = d.documents.filter(doc => statusLower(doc) === 'draft').length;

        const stats = [
            { label: 'Активные проекты', value: fmtNumber(activeProjects), tone: 'primary' },
            { label: 'Открытые задачи', value: fmtNumber(openTasks), tone: openTasks > 50 ? 'warning' : 'neutral' },
            { label: 'Мои задачи', value: fmtNumber(myTasks), tone: myTasks > 0 ? 'primary' : 'neutral' },
            { label: 'Висят визы', value: fmtNumber(pendingApprovals), tone: pendingApprovals > 0 ? 'warning' : 'success' },
        ];
        if (incoming || outgoing || overdueRecv) {
            stats.push(
                { label: 'Открытые поступления', value: fmtMoney(incoming), tone: 'success' },
                { label: 'Открытые выплаты', value: fmtMoney(outgoing), tone: outgoing > 0 ? 'warning' : 'neutral' },
                { label: 'Просроченная дебиторка', value: fmtMoney(overdueRecv), tone: overdueRecv > 0 ? 'danger' : 'success' },
            );
        }
        if (drafts) stats.push({ label: 'Черновики документов', value: fmtNumber(drafts), tone: 'warning' });

        return {
            html: `<p class="ka-msg-lead">Сводка по компании</p>
<p>В работе ${fmtNumber(activeProjects)} ${plural(activeProjects, ['активный проект', 'активных проекта', 'активных проектов'])} (в архиве — ${fmtNumber(archive)}).</p>`,
            stats,
            actions: [
                { label: 'Открыть проекты', target: 'dashboard' },
                { label: 'Открыть финансы', target: 'finance' },
                { label: 'Директорский кабинет', target: 'executive' },
            ],
        };
    }

    function answerProjects(d, q) {
        const lower = normalize(q);
        const wantsActive = /активн|в работе|сейчас/i.test(lower);
        const wantsArchive = /архив|закрыт|заверш/i.test(lower);
        const wantsCount = /сколько|количеств|итог/i.test(lower);

        if (wantsCount && !lower.replace(/проект|сколько|активн|количеств|итог|у|меня|компани[ия]|всего/g, '').trim()) {
            const a = d.projects.filter(p => statusLower(p) === 'active').length;
            const ar = d.projects.filter(p => statusLower(p) === 'archive').length;
            const c = d.projects.filter(p => statusLower(p) === 'canceled').length;
            return {
                html: `<p>Всего проектов: <strong>${fmtNumber(d.projects.length)}</strong>.</p>`,
                stats: [
                    { label: 'Активные', value: fmtNumber(a), tone: 'primary' },
                    { label: 'В архиве', value: fmtNumber(ar), tone: 'neutral' },
                    { label: 'Отменены', value: fmtNumber(c), tone: c > 0 ? 'warning' : 'neutral' },
                ],
                actions: [{ label: 'Открыть проекты', target: 'dashboard' }],
            };
        }

        let pool = d.projects;
        if (wantsActive) pool = pool.filter(p => statusLower(p) === 'active');
        if (wantsArchive) pool = pool.filter(p => statusLower(p) === 'archive');
        if (/мо[йи]|для меня/i.test(lower) && d.user) {
            pool = pool.filter(p => String(p.responsible || p.executor || p.owner || '').includes(d.user.name)
                || asArray(p.team).some(member => String(member).includes(d.user.name)));
        }

        const matches = fuzzyMatchRows(pool, q, ['name', 'contract', 'client', 'client_name', 'status', 'stage']);
        const items = matches.map(p => ({
            title: p.name || p.contract || `Проект #${p.id || ''}`,
            meta: [p.client_name || p.client, p.stage].filter(Boolean).join(' · ') || 'нет описания',
            tag: statusLower(p) === 'active' ? 'в работе' : statusLower(p) === 'archive' ? 'в архиве' : (p.status || ''),
            tagTone: statusLower(p) === 'active' ? 'success' : 'muted',
        }));

        return {
            html: renderListAnswer(items.length ? `Нашёл ${matches.length} ${plural(matches.length, ['проект', 'проекта', 'проектов'])}` : '', items, { empty: 'Подходящих проектов не нашёл. Попробуй уточнить название или открой реестр.' }),
            actions: [
                { label: 'Открыть проекты', target: 'dashboard' },
                { label: 'Создать проект', action: 'guide', query: 'как создать проект' },
            ],
        };
    }

    function answerClients(d, q) {
        const matches = fuzzyMatchRows(d.clients, q, ['name', 'inn', 'contact', 'contacts', 'email', 'phone']);
        const items = matches.map(c => ({
            title: c.name || `Контрагент #${c.id || ''}`,
            meta: [c.inn ? `ИНН ${c.inn}` : null, c.contact || c.contacts || c.email || c.phone].filter(Boolean).join(' · ') || 'данных нет',
        }));
        const total = d.clients.length;
        const lead = matches.length === 0 && /сколько|итог|количеств/i.test(q)
            ? `Контрагентов в базе: ${fmtNumber(total)}.`
            : '';
        return {
            html: (lead ? `<p>${escapeHtml(lead)}</p>` : '') + renderListAnswer(items.length ? `Нашёл ${matches.length} ${plural(matches.length, ['контрагента', 'контрагента', 'контрагентов'])}` : '', items, { empty: total ? 'Совпадений нет. Уточни название или ИНН.' : 'В базе пока нет контрагентов. Заведи первого в разделе «База клиентов».' }),
            actions: [
                { label: 'Открыть базу клиентов', target: 'clients' },
                { label: 'Как создать контрагента?', action: 'guide', query: 'как создать клиента' },
            ],
        };
    }

    function answerDocuments(d, q) {
        const lower = normalize(q);
        const total = d.documents.length;
        const registered = d.documents.filter(x => statusLower(x) === 'registered').length;
        const draft = d.documents.filter(x => statusLower(x) === 'draft').length;
        const matches = fuzzyMatchRows(d.documents, q, ['name', 'title', 'number', 'contract', 'client_name', 'type']);

        if (matches.length && /найд|поиск/i.test(lower)) {
            const items = matches.map(doc => ({
                title: doc.name || doc.title || `Документ #${doc.id || doc.number || ''}`,
                meta: [doc.type, doc.client_name, doc.number ? `№ ${doc.number}` : null].filter(Boolean).join(' · ') || 'без описания',
                tag: statusLower(doc) === 'registered' ? 'зарегистрирован' : statusLower(doc) === 'draft' ? 'черновик' : doc.status || '',
                tagTone: statusLower(doc) === 'registered' ? 'success' : 'muted',
            }));
            return {
                html: renderListAnswer(`Документы по запросу`, items),
                actions: [{ label: 'Открыть документы', target: 'documents' }],
            };
        }

        return {
            html: `<p class="ka-msg-lead">Документы</p><p>Всего ${fmtNumber(total)}. Зарегистрировано: ${fmtNumber(registered)}, в черновиках: ${fmtNumber(draft)}.</p>`,
            stats: [
                { label: 'Всего', value: fmtNumber(total), tone: 'neutral' },
                { label: 'Зарегистрировано', value: fmtNumber(registered), tone: 'success' },
                { label: 'Черновики', value: fmtNumber(draft), tone: draft > 0 ? 'warning' : 'neutral' },
            ],
            actions: [
                { label: 'Открыть реестр', target: 'documents' },
                { label: 'Как зарегистрировать?', action: 'guide', query: 'как зарегистрировать документ' },
            ],
        };
    }

    function answerTasks(d, q) {
        const lower = normalize(q);
        const open = d.tasks.filter(t => !['completed', 'done', 'closed'].includes(statusLower(t)));
        const closed = d.tasks.length - open.length;
        const mine = d.user ? open.filter(t => String(t.executor || '').includes(d.user.name)) : [];

        if (/у кого|кто/i.test(lower)) {
            const counts = {};
            open.forEach(t => {
                const exec = String(t.executor || '').split(/[,;]/)[0].trim();
                if (!exec) return;
                counts[exec] = (counts[exec] || 0) + 1;
            });
            const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5);
            const items = top.map(([name, n]) => ({
                title: name,
                meta: `${fmtNumber(n)} ${plural(n, ['открытая задача', 'открытых задачи', 'открытых задач'])}`,
            }));
            return {
                html: renderListAnswer('Топ-5 по открытым задачам', items, { empty: 'Открытых задач сейчас нет.' }),
                actions: [{ label: 'Открыть задачи', target: 'tasks' }],
            };
        }

        if (/мо[йи]|на мне/i.test(lower)) {
            const items = mine.slice(0, 6).map(t => ({
                title: t.title || t.name || `Задача #${t.id || ''}`,
                meta: [t.project_name, t.deadline].filter(Boolean).join(' · ') || 'без срока',
                tag: t.priority || '',
                tagTone: /срочн|критич/i.test(t.priority || '') ? 'danger' : 'muted',
            }));
            return {
                html: `<p class="ka-msg-lead">Мои задачи</p><p>На мне ${fmtNumber(mine.length)} ${plural(mine.length, ['открытая задача', 'открытых задачи', 'открытых задач'])} (всего открытых по компании — ${fmtNumber(open.length)}).</p>` + (items.length ? renderListAnswer('', items) : ''),
                actions: [{ label: 'Открыть задачи', target: 'tasks' }],
            };
        }

        return {
            html: `<p class="ka-msg-lead">Задачи и поручения</p>`,
            stats: [
                { label: 'Открытые', value: fmtNumber(open.length), tone: 'primary' },
                { label: 'Закрытые', value: fmtNumber(closed), tone: 'success' },
                { label: 'На мне', value: fmtNumber(mine.length), tone: mine.length > 0 ? 'warning' : 'neutral' },
            ],
            actions: [{ label: 'Открыть задачи', target: 'tasks' }],
        };
    }

    function answerApprovals(d, q) {
        const lower = normalize(q);
        const pending = d.approvals.filter(a => ['pending', 'rework'].includes(statusLower(a)));
        const completed = d.approvals.filter(a => ['completed', 'approved'].includes(statusLower(a)));
        const mine = d.user ? pending.filter(a => String(a.assignee || a.approver || '').includes(d.user.name)) : [];

        if (/стар|висящ|задерж/i.test(lower)) {
            const items = pending.slice(0, 6).map(a => ({
                title: a.title || a.subject || `Согласование #${a.id || ''}`,
                meta: [a.created_at, a.assignee || a.approver].filter(Boolean).join(' · ') || 'без даты',
                tag: a.status || '',
                tagTone: 'warning',
            }));
            return {
                html: renderListAnswer('Висящие согласования', items, { empty: 'Висящих сейчас нет — всё пройдено.' }),
                actions: [{ label: 'Открыть согласования', target: 'approvals' }],
            };
        }

        return {
            html: `<p class="ka-msg-lead">Согласования</p><p>В работе ${fmtNumber(pending.length)}, завершено ${fmtNumber(completed.length)}, всего ${fmtNumber(d.approvals.length)}.</p>${mine.length ? `<p class="ka-hint">На моей визе: ${fmtNumber(mine.length)}.</p>` : ''}`,
            stats: [
                { label: 'В работе', value: fmtNumber(pending.length), tone: pending.length > 0 ? 'warning' : 'success' },
                { label: 'Завершено', value: fmtNumber(completed.length), tone: 'success' },
                { label: 'На мне', value: fmtNumber(mine.length), tone: mine.length > 0 ? 'primary' : 'neutral' },
            ],
            actions: [
                { label: 'Открыть согласования', target: 'approvals' },
                { label: 'Как запустить маршрут?', action: 'guide', query: 'как запустить согласование' },
            ],
        };
    }

    function answerFinance(d, q) {
        const lower = normalize(q);
        const fm = d.financeSummary?.metrics || {};
        const incoming = fmNum(fm.incoming_open);
        const outgoing = fmNum(fm.outgoing_open);
        const overdueRecv = fmNum(fm.overdue_receivables);
        const cashGap = fmNum(fm.cash_gap || fm.cash_gap_plan);
        const receivableOpen = fmNum(fm.receivable_open);
        const payableOpen = fmNum(fm.payable_open);
        const pnlFact = fmNum(fm.pnl_fact);
        const pnlPlan = fmNum(fm.pnl_plan);
        const ddsIn = fmNum(fm.dds_in_fact);
        const ddsOut = fmNum(fm.dds_out_fact);
        const queued = fmNum(fm.queued_sync);
        const failed = fmNum(fm.failed_sync);
        const conflicts = fmNum(fm.sync_conflicts);

        // 1) Просрочки
        if (/просроч|долг|задолжен|дебиторк/.test(lower) && /просроч|долг|задолжен/.test(lower)) {
            const overdueRows = d.payments.filter(p => statusLower(p).includes('overdue'));
            const items = overdueRows.slice(0, 6).map(p => ({
                title: p.title || p.purpose || p.counterparty || `Платёж #${p.id || ''}`,
                meta: [p.client_name || p.counterparty, p.due_date, fmtMoney(p.amount)].filter(Boolean).join(' · '),
                tag: 'просрочка',
                tagTone: 'danger',
            }));
            return {
                html: `<p class="ka-msg-lead">Просрочки и дебиторка</p>
<p>Просроченная дебиторка по сводке: <strong>${fmtMoney(overdueRecv)}</strong>.${receivableOpen ? ` Открытая дебиторка всего: ${fmtMoney(receivableOpen)}.` : ''}</p>${overdueRows.length ? `<p class="ka-hint">В реестре платежей просроченных операций: ${fmtNumber(overdueRows.length)}.</p>` : ''}` + (items.length ? renderListAnswer('', items) : ''),
                stats: [
                    { label: 'Просрочка', value: fmtMoney(overdueRecv), tone: overdueRecv > 0 ? 'danger' : 'success' },
                    { label: 'Открытая дебиторка', value: fmtMoney(receivableOpen), tone: receivableOpen > 0 ? 'warning' : 'neutral' },
                    { label: 'Открытая кредиторка', value: fmtMoney(payableOpen), tone: payableOpen > 0 ? 'warning' : 'neutral' },
                ],
                actions: [{ label: 'Открыть финансы', target: 'finance' }],
            };
        }

        // 2) Открытые поступления / выплаты / кассовый разрыв (главные финансовые показатели)
        return {
            html: `<p class="ka-msg-lead">Финансы</p>
<p>Открытые поступления: <strong>${fmtMoney(incoming)}</strong>. Открытые выплаты: <strong>${fmtMoney(outgoing)}</strong>.${cashGap ? ` Кассовый разрыв: <strong>${fmtMoney(cashGap)}</strong>.` : ''}</p>`,
            stats: [
                { label: 'Открытые поступления', value: fmtMoney(incoming), tone: incoming > 0 ? 'success' : 'neutral' },
                { label: 'Открытые выплаты', value: fmtMoney(outgoing), tone: outgoing > 0 ? 'warning' : 'neutral' },
                { label: 'Просроченная дебиторка', value: fmtMoney(overdueRecv), tone: overdueRecv > 0 ? 'danger' : 'success' },
                { label: 'Кассовый разрыв', value: fmtMoney(cashGap), tone: cashGap < 0 ? 'danger' : (cashGap > 0 ? 'warning' : 'neutral') },
                { label: 'P&L факт / план', value: `${fmtMoney(pnlFact)} / ${fmtMoney(pnlPlan)}`, tone: pnlFact >= pnlPlan ? 'success' : 'warning' },
                { label: 'ДДС вход / исход', value: `${fmtMoney(ddsIn)} / ${fmtMoney(ddsOut)}`, tone: 'neutral' },
            ],
            actions: [
                { label: 'Открыть финансы', target: 'finance' },
                { label: 'Открыть бухгалтерию', target: 'accounting' },
                ...((queued + failed + conflicts) > 0 ? [{ label: '1С: статус обмена', query: 'обмен 1с' }] : []),
            ],
        };
    }

    function answerSync(d) {
        const fm = d.financeSummary?.metrics || {};
        const queued = fmNum(fm.queued_sync);
        const failed = fmNum(fm.failed_sync);
        const conflicts = fmNum(fm.sync_conflicts);
        const queuedRows = d.financeSyncQueue.slice(0, 5).map(r => ({
            title: r.title || r.entity || `Запись #${r.id || ''}`,
            meta: [r.created_at, r.target || '1С'].filter(Boolean).join(' · '),
            tag: r.status || 'в очереди',
            tagTone: 'warning',
        }));
        return {
            html: `<p class="ka-msg-lead">Обмен с 1С</p>`,
            stats: [
                { label: 'В очереди', value: fmtNumber(queued), tone: queued > 0 ? 'warning' : 'success' },
                { label: 'Ошибки', value: fmtNumber(failed), tone: failed > 0 ? 'danger' : 'success' },
                { label: 'Конфликты', value: fmtNumber(conflicts), tone: conflicts > 0 ? 'danger' : 'success' },
            ],
            actions: [
                { label: 'Открыть бухгалтерию', target: 'accounting' },
                { label: 'Открыть интеграции', target: 'integrations' },
            ],
        };
    }

    function answerPnl(d) {
        const fm = d.financeSummary?.metrics || {};
        const pnlFact = fmNum(fm.pnl_fact);
        const pnlPlan = fmNum(fm.pnl_plan);
        const ddsIn = fmNum(fm.dds_in_fact);
        const ddsOut = fmNum(fm.dds_out_fact);
        const cashGap = fmNum(fm.cash_gap || fm.cash_gap_plan);
        return {
            html: `<p class="ka-msg-lead">P&L и ДДС</p>
<p>P&L факт: <strong>${fmtMoney(pnlFact)}</strong> при плане ${fmtMoney(pnlPlan)} (${pnlPlan ? Math.round(pnlFact / pnlPlan * 100) : 0}%).</p>`,
            stats: [
                { label: 'P&L факт', value: fmtMoney(pnlFact), tone: pnlFact >= pnlPlan ? 'success' : 'warning' },
                { label: 'P&L план', value: fmtMoney(pnlPlan), tone: 'neutral' },
                { label: 'ДДС вход', value: fmtMoney(ddsIn), tone: 'success' },
                { label: 'ДДС исход', value: fmtMoney(ddsOut), tone: ddsOut > ddsIn ? 'warning' : 'neutral' },
                { label: 'Кассовый разрыв', value: fmtMoney(cashGap), tone: cashGap < 0 ? 'danger' : 'neutral' },
            ],
            actions: [{ label: 'Открыть финансы', target: 'finance' }],
        };
    }

    function answerContracts(d, q) {
        const total = d.contracts.length;
        const matches = fuzzyMatchRows(d.contracts, q, ['name', 'number', 'title', 'client_name', 'counterparty']);
        const items = matches.map(c => ({
            title: c.name || c.title || c.number || `Договор #${c.id || ''}`,
            meta: [c.number ? `№ ${c.number}` : null, c.client_name || c.counterparty, c.amount ? fmtMoney(c.amount) : null].filter(Boolean).join(' · '),
            tag: c.status || '',
            tagTone: 'muted',
        }));
        return {
            html: `<p class="ka-msg-lead">Договоры</p><p>Всего в реестре: ${fmtNumber(total)}.</p>` + (items.length ? renderListAnswer('Совпадения', items) : ''),
            actions: [{ label: 'Открыть документы', target: 'documents' }],
        };
    }

    function answerClaims(d) {
        const open = d.claims.filter(c => !['closed', 'resolved', 'done'].includes(statusLower(c)));
        return {
            html: `<p class="ka-msg-lead">Претензии</p>`,
            stats: [
                { label: 'Открытые', value: fmtNumber(open.length), tone: open.length > 0 ? 'warning' : 'success' },
                { label: 'Всего', value: fmtNumber(d.claims.length), tone: 'neutral' },
            ],
            actions: [{ label: 'Открыть претензии', target: 'claims' }],
        };
    }

    function answerExpenses(d) {
        const pending = d.expenses.filter(e => ['pending', 'review', 'submitted'].includes(statusLower(e)));
        const approved = d.expenses.filter(e => ['approved', 'paid'].includes(statusLower(e)));
        const sum = d.expenses.reduce((s, e) => s + fmNum(e.amount), 0);
        return {
            html: `<p class="ka-msg-lead">Расходы</p>`,
            stats: [
                { label: 'На согласовании', value: fmtNumber(pending.length), tone: pending.length > 0 ? 'warning' : 'success' },
                { label: 'Одобрено', value: fmtNumber(approved.length), tone: 'success' },
                { label: 'Сумма по реестру', value: fmtMoney(sum), tone: 'neutral' },
            ],
            actions: [{ label: 'Открыть расходы', target: 'expenses' }],
        };
    }

    function answerRequests(d) {
        const open = d.internalRequests.filter(r => !['closed', 'done', 'resolved'].includes(statusLower(r)));
        return {
            html: `<p class="ka-msg-lead">Заявки</p>`,
            stats: [
                { label: 'Открытые', value: fmtNumber(open.length), tone: open.length > 0 ? 'primary' : 'success' },
                { label: 'Всего', value: fmtNumber(d.internalRequests.length), tone: 'neutral' },
            ],
            actions: [{ label: 'Открыть заявки', target: 'requests' }],
        };
    }

    function answerResources(d) {
        return {
            html: `<p class="ka-msg-lead">Ресурсы и нагрузка</p>`,
            stats: [
                { label: 'Аллокаций', value: fmtNumber(d.resources.length), tone: 'neutral' },
                { label: 'Перегружены', value: fmtNumber(asArray(d.executive?.overloaded_resources).length), tone: asArray(d.executive?.overloaded_resources).length > 0 ? 'danger' : 'success' },
            ],
            actions: [{ label: 'Открыть ресурсы', target: 'resources' }],
        };
    }

    function answerService(d) {
        const open = d.service.filter(s => !['closed', 'done', 'resolved'].includes(statusLower(s)));
        return {
            html: `<p class="ka-msg-lead">Сервис</p>`,
            stats: [
                { label: 'Открытые наряды', value: fmtNumber(open.length), tone: open.length > 0 ? 'primary' : 'success' },
                { label: 'Всего', value: fmtNumber(d.service.length), tone: 'neutral' },
            ],
            actions: [{ label: 'Открыть сервис', target: 'service' }],
        };
    }

    function answerStock(d) {
        return {
            html: `<p class="ka-msg-lead">Склад и номенклатура</p><p>Движений по складу зафиксировано: ${fmtNumber(d.stock.length)}.</p>`,
            actions: [{ label: 'Открыть склад', target: 'nomenclature' }],
        };
    }

    function answerMeetings(d) {
        return {
            html: `<p class="ka-msg-lead">Встречи</p><p>В календаре записей: ${fmtNumber(d.meetings.length)}.</p>`,
            actions: [{ label: 'Открыть встречи', target: 'meetings' }],
        };
    }

    function answerEmails(d) {
        const unread = d.emails.filter(e => !e.read && !e.is_read).length;
        return {
            html: `<p class="ka-msg-lead">Почта</p>`,
            stats: [
                { label: 'Всего писем', value: fmtNumber(d.emails.length), tone: 'neutral' },
                { label: 'Непрочитано', value: fmtNumber(unread), tone: unread > 0 ? 'warning' : 'success' },
            ],
            actions: [{ label: 'Открыть почту', target: 'emails' }],
        };
    }

    function answerKnowledge(d, q) {
        const matches = fuzzyMatchRows(d.knowledge, q, ['title', 'name', 'content', 'tag', 'tags']);
        const items = matches.map(k => ({
            title: k.title || k.name || `Статья #${k.id || ''}`,
            meta: [k.section, k.tags || k.tag].filter(Boolean).join(' · ') || 'без тегов',
        }));
        return {
            html: `<p class="ka-msg-lead">База знаний</p><p>Статей в базе: ${fmtNumber(d.knowledge.length)}.</p>` + (items.length ? renderListAnswer('Совпадения', items) : ''),
            actions: [{ label: 'Открыть базу знаний', target: 'knowledge' }],
        };
    }

    function answerNotifications(d) {
        const unread = d.notifications.filter(n => !n.read && !n.is_read);
        const items = unread.slice(0, 5).map(n => ({
            title: n.title || n.message || 'Уведомление',
            meta: n.created_at || n.ts || '',
            tag: n.severity || 'new',
            tagTone: /critic|error|danger/i.test(n.severity || '') ? 'danger' : 'warning',
        }));
        return {
            html: `<p class="ka-msg-lead">Уведомления</p><p>Непрочитанных: ${fmtNumber(unread.length)} из ${fmtNumber(d.notifications.length)}.</p>` + (items.length ? renderListAnswer('', items) : ''),
            actions: [],
        };
    }

    function answerWho(d) {
        const u = d.user;
        if (!u) return { html: '<p>Я не вижу авторизованного пользователя. Войдите в систему — и я смогу подсказать о ваших задачах и доступах.</p>' };
        return {
            html: `<p class="ka-msg-lead">Профиль</p>
<p><strong>${escapeHtml(u.name || 'Пользователь')}</strong> · ${escapeHtml(u.role || 'без роли')}${u.is_head === 1 ? ' · Руководитель' : ''}.</p>
<p class="ka-hint">Email: ${escapeHtml(u.email || '—')}.</p>`,
            actions: [{ label: 'Открыть профиль', target: 'profile' }],
        };
    }

    function answerRisks(d) {
        const heatmap = asArray(d.executive?.boardroom_heatmap);
        const bottlenecks = asArray(d.executive?.boardroom_bottlenecks);
        const heatItems = heatmap.slice(0, 6).map(h => ({
            title: h.label || 'Зона риска',
            meta: `критично ${fmtNumber(h.critical || 0)} · внимание ${fmtNumber(h.warning || 0)}`,
            tag: Number(h.critical || 0) > 0 ? 'критично' : Number(h.warning || 0) > 0 ? 'внимание' : 'ок',
            tagTone: Number(h.critical || 0) > 0 ? 'danger' : Number(h.warning || 0) > 0 ? 'warning' : 'success',
        }));
        const bottleItems = bottlenecks.slice(0, 5).map(b => ({
            title: b.title || 'Узкое место',
            meta: b.meta || 'нужна реакция',
            tag: b.severity || '',
            tagTone: 'warning',
        }));
        return {
            html: `<p class="ka-msg-lead">Карта проблем</p><p>Сводка собирает риски по согласованиям, кассе, ресурсам, сервису и интеграциям.</p>`
                + (heatItems.length ? renderListAnswer('Тепловая карта', heatItems) : '<p class="ka-msg-empty">Карта пока не наполнена.</p>')
                + (bottleItems.length ? renderListAnswer('Главные узкие места', bottleItems) : ''),
            actions: [{ label: 'Открыть директорский кабинет', target: 'executive' }],
        };
    }

    function answerNavigate(view) {
        const label = VIEW_LABELS[view] || view;
        return {
            html: `<p>Открываю раздел: <strong>${escapeHtml(label)}</strong>.</p>`,
            actions: [],
            navigate: view,
        };
    }

    function answerSectionHelp(view) {
        const label = VIEW_LABELS[view] || view;
        const text = SECTION_HELP[view] || 'Этот раздел пока без описания.';
        return {
            html: `<p class="ka-msg-lead">${escapeHtml(label)}</p><p>${escapeHtml(text)}</p>`,
            actions: viewExistsInRoute(view) ? [{ label: `Открыть «${label}»`, target: view }] : [],
        };
    }

    function answerHowTo(q) {
        const lower = normalize(q);
        if (/проект/.test(lower)) {
            return {
                html: `<p class="ka-msg-lead">Как создать проект</p>
<ol class="ka-steps">
<li>Открой <strong>Все проекты</strong> и нажми «Новый проект».</li>
<li>Заполни клиента, договор/название и сроки.</li>
<li>Назначь рабочую группу и роль ответственного.</li>
<li>Сохрани — проект появится в реестре. Дальше — карточка, документы, задачи.</li>
</ol>`,
                actions: [{ label: 'Открыть проекты', target: 'dashboard' }],
            };
        }
        if (/клиент|контрагент/.test(lower)) {
            return {
                html: `<p class="ka-msg-lead">Как создать контрагента</p>
<ol class="ka-steps">
<li>Открой <strong>Базу клиентов</strong> и нажми «Добавить».</li>
<li>Заполни название, ИНН и контакты — телефон, email, ответственного.</li>
<li>После сохранения откроется досье 360, где можно добавить договор и оплаты.</li>
</ol>`,
                actions: [{ label: 'Открыть клиентов', target: 'clients' }],
            };
        }
        if (/документ|зарегистрир/.test(lower)) {
            return {
                html: `<p class="ka-msg-lead">Как зарегистрировать документ</p>
<ol class="ka-steps">
<li>В разделе <strong>Документы</strong> нажми «Загрузить» и выбери файл.</li>
<li>Укажи тип, контрагента и привязку к проекту.</li>
<li>Нажми «Зарегистрировать» — присвоится номер и появится в журнале.</li>
</ol>`,
                actions: [{ label: 'Открыть документы', target: 'documents' }],
            };
        }
        if (/соглас|маршрут|виз/.test(lower)) {
            return {
                html: `<p class="ka-msg-lead">Как запустить согласование</p>
<ol class="ka-steps">
<li>Открой <strong>Согласования</strong> и нажми «Запустить процесс».</li>
<li>Выбери шаблон BPMN или собери маршрут вручную (визирующие, порядок).</li>
<li>Прикрепи объект — документ, проект или платёж.</li>
<li>Нажми «Старт» — система разошлёт визы.</li>
</ol>`,
                actions: [{ label: 'Открыть согласования', target: 'approvals' }],
            };
        }
        if (/задач|поруч/.test(lower)) {
            return {
                html: `<p class="ka-msg-lead">Как назначить поручение</p>
<ol class="ka-steps">
<li>Открой <strong>Задачи</strong> или карточку проекта.</li>
<li>Нажми «Создать задачу», заполни тему, исполнителя и срок.</li>
<li>При необходимости — приоритет, чек-лист, файлы. Сохрани.</li>
</ol>`,
                actions: [{ label: 'Открыть задачи', target: 'tasks' }],
            };
        }
        return null;
    }

    function answerProduction(d) {
        const total = d.production.length;
        const open = d.production.filter(o => !['done', 'closed'].includes(statusLower(o))).length;
        return {
            html: `<p class="ka-msg-lead">Производство</p>`,
            stats: [
                { label: 'Заказов-нарядов', value: fmtNumber(total), tone: 'neutral' },
                { label: 'В работе', value: fmtNumber(open), tone: open > 0 ? 'primary' : 'success' },
                { label: 'Движений по складу', value: fmtNumber(d.stock.length), tone: 'neutral' },
            ],
            actions: [
                { label: 'Открыть производство', target: 'production' },
                { label: 'Открыть склад', target: 'nomenclature' },
            ],
        };
    }

    /* ---------- роутер интентов ---------- */

    function buildAnswer(question, ctx) {
        const q = String(question || '').trim();
        if (!q) return { html: '<p>Напиши вопрос — про проекты, документы, финансы, задачи или риски.</p>' };

        const lower = normalize(q);

        if (lower === 'помощь' || lower === 'help' || /что ты умеешь|какие команды|справка/.test(lower)) return answerHelp();
        if (/^(привет|здрав|добр|hello|hi|hey|йоу)\b/.test(lower)) return answerGreeting();
        if (/спасиб|благодар|thanks/.test(lower)) {
            return { html: '<p>Всегда рад. Спрашивай ещё — по проектам, финансам, документам, задачам.</p>' };
        }
        if (/(пока|до встречи|bye)/.test(lower)) {
            return { html: '<p>Хорошего дня! Я всегда здесь, в правом нижнем углу.</p>' };
        }

        const d = dataSnapshot();

        if (/сводк|итог|что сейчас|обзор|статус компани/.test(lower)) return answerSummary(d);
        if (/риск|карта проблем|узк|боттлнек/.test(lower)) return answerRisks(d);

        const howto = (/как (создать|сделать|зарегистрир|запустить|назначить|добавить)/.test(lower) || /^создать /.test(lower)) ? answerHowTo(lower) : null;
        if (howto) return howto;

        const wantsExplain = /что так(ое|ой|ая)|объясни|расскажи про/i.test(lower);

        if (/^(открой|перейди|покажи раздел|перейти|открыть)\b/.test(lower) || /открой |перейди /.test(lower)) {
            const view = findRoute(lower);
            if (view) return answerNavigate(view);
            return { html: '<p>Не понял, какой раздел открыть. Попробуй: «открой проекты», «открой финансы», «открой документы».</p>' };
        }

        if (wantsExplain) {
            const view = findRoute(lower);
            if (view) return answerSectionHelp(view);
        }

        if (/кто я|мой профил|мои данны|мой email|моя рол/.test(lower)) return answerWho(d);
        if (/уведомлен|нотификац|непрочитан/.test(lower)) return answerNotifications(d);

        if (/обмен.*1с|1с.*обмен|очеред.*1с|конфликт.*обмен|синхрониз/.test(lower)) return answerSync(d);
        if (/p&l|пнл|p\s*and\s*l|pnl|ддс|кассов(ый|ого) разрыв/.test(lower)) return answerPnl(d);

        if (/договор|контракт/.test(lower)) return answerContracts(d, q);
        if (/претенз|рекламац/.test(lower)) return answerClaims(d);
        if (/расход|затрат|бюджет/.test(lower)) return answerExpenses(d);
        if (/заявк|тикет|обращен/.test(lower)) return answerRequests(d);
        if (/ресурс|нагрузк|загрузк|сотрудник/.test(lower)) return answerResources(d);
        if (/сервис|обслужив|наряд/.test(lower)) return answerService(d);
        if (/встреч|календар|митинг/.test(lower)) return answerMeetings(d);
        if (/почт|письм|email/.test(lower)) return answerEmails(d);
        if (/знани|wiki|инструкц|статья/.test(lower)) return answerKnowledge(d, q);

        if (/проект/.test(lower)) return answerProjects(d, q);
        if (/клиент|контрагент|заказчик/.test(lower)) return answerClients(d, q);
        if (/документ|файл|реестр/.test(lower)) return answerDocuments(d, q);
        if (/соглас|виза|маршрут/.test(lower)) return answerApprovals(d, q);
        if (/задач|поруч/.test(lower)) return answerTasks(d, q);
        if (/финанс|деньг|платеж|оплат|касс|просроч|дебиторк|кредиторк|поступлен|выплат/.test(lower)) return answerFinance(d, q);
        if (/производст|цех|заказ-наряд/.test(lower)) return answerProduction(d);
        if (/склад|номенклат|товар|остатк/.test(lower)) return answerStock(d);

        if (/сколько/.test(lower)) {
            return {
                html: `<p>Уточни, чего: проектов, клиентов, документов, задач, согласований, платежей? Напиши, например, «сколько активных проектов».</p>`,
                actions: [
                    { label: 'Сводка', query: 'сводка' },
                    { label: 'Проекты', query: 'сколько активных проектов' },
                    { label: 'Документы', query: 'сколько документов' },
                ],
            };
        }

        // навигационная подсказка
        const route = findRoute(lower);
        if (route) {
            return {
                html: `<p>Похоже, ты про раздел <strong>${escapeHtml(VIEW_LABELS[route] || route)}</strong>. Открыть его или показать сводку?</p>`,
                actions: [
                    { label: `Открыть «${VIEW_LABELS[route] || route}»`, target: route },
                    { label: 'Что это за раздел?', action: 'guide', query: `что такое ${VIEW_LABELS[route] || route}` },
                ],
            };
        }

        return {
            html: `<p>Не нашёл точный ответ. Я уверенно отвечаю по: проектам, клиентам, документам, задачам, согласованиям, финансам, рискам. Также умею открывать разделы и объяснять, что они делают.</p>`,
            actions: [
                { label: 'Сводка', query: 'сводка' },
                { label: 'Помощь', query: 'помощь' },
            ],
        };
    }

    /* ---------- иконки ---------- */

    const ICONS = {
        bot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="6" width="16" height="12" rx="3"/><circle cx="9" cy="12" r="1.2" fill="currentColor"/><circle cx="15" cy="12" r="1.2" fill="currentColor"/><path d="M12 3v3M8 18l-2 3M16 18l2 3"/></svg>',
        send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l14-7-5 16-3-7-6-2z"/></svg>',
        close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
        clear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>',
        sparkle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.8 4.6L18 9.4l-4.2 1.8L12 15.8l-1.8-4.6L6 9.4l4.2-1.8L12 3z"/></svg>',
        pulse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2-6 4 12 2-6h6"/></svg>',
        flag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>',
        folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
        cash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 10v4M18 10v4"/></svg>',
        check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l5 5L20 6"/></svg>',
        help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4.5 1.5c-1 1-2 1.5-2 3M12 17h.01"/></svg>',
    };

    /* ---------- DOM ---------- */

    let state = {
        open: false,
        thinking: false,
        history: [],
    };

    function templateRoot() {
        return `
<div id="kordaAssistantRoot" class="korda-assistant" data-open="false" data-thinking="false">
    <button id="kordaAssistantFab" class="ka-fab" type="button" aria-label="Открыть Korda Assistant" title="Korda Assistant — Ctrl+/">
        <span class="ka-fab-icon">${ICONS.bot}</span>
        <span class="ka-fab-label">Помощник</span>
        <span class="ka-fab-dot" aria-hidden="true"></span>
    </button>
    <section id="kordaAssistantPanel" class="ka-panel" role="dialog" aria-label="Korda Assistant" aria-modal="false" hidden>
        <header class="ka-header">
            <div class="ka-header-id">
                <div class="ka-avatar">${ICONS.bot}</div>
                <div class="ka-header-text">
                    <strong>Korda Assistant</strong>
                    <span><i class="ka-status-dot"></i> На связи · отвечает по вашим данным</span>
                </div>
            </div>
            <div class="ka-header-actions">
                <button type="button" id="kordaAssistantClear" class="ka-icon-btn" title="Очистить чат" aria-label="Очистить чат">${ICONS.clear}</button>
                <button type="button" id="kordaAssistantClose" class="ka-icon-btn" title="Закрыть" aria-label="Закрыть">${ICONS.close}</button>
            </div>
        </header>
        <div id="kordaAssistantMessages" class="ka-messages" role="log" aria-live="polite"></div>
        <div id="kordaAssistantQuick" class="ka-quick"></div>
        <form id="kordaAssistantForm" class="ka-form" autocomplete="off">
            <div class="ka-input-wrap">
                <textarea id="kordaAssistantInput" rows="1" placeholder="Спроси про проекты, риски, документы, финансы…" maxlength="500"></textarea>
                <button type="submit" class="ka-send" aria-label="Отправить">${ICONS.send}</button>
            </div>
            <div class="ka-footer-hint">
                <span>Enter — отправить · Shift+Enter — перенос строки</span>
                <span class="ka-footer-hint-right">${ICONS.sparkle} работает на ваших данных</span>
            </div>
        </form>
    </section>
</div>`;
    }

    function ensureMounted() {
        if (document.getElementById('kordaAssistantRoot')) return;
        const wrapper = document.createElement('div');
        wrapper.innerHTML = templateRoot();
        document.body.appendChild(wrapper.firstElementChild);
        bindEvents();
        renderQuick();
        renderMessages();
        // На старте панель всегда свернута — открыта только FAB-кнопка «Помощник».
        // Пользователь сам кликает, чтобы развернуть чат.
        try { localStorage.removeItem(STORAGE_OPEN); } catch (_) { /* noop */ }
    }

    function bindEvents() {
        $('#kordaAssistantFab').addEventListener('click', () => togglePanel());
        $('#kordaAssistantClose').addEventListener('click', () => closePanel());
        $('#kordaAssistantClear').addEventListener('click', () => clearHistory());
        const form = $('#kordaAssistantForm');
        const input = $('#kordaAssistantInput');
        form.addEventListener('submit', e => {
            e.preventDefault();
            submitInput();
        });
        input.addEventListener('input', () => autoResize(input));
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitInput();
            }
        });
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && state.open) closePanel();
            if ((e.ctrlKey || e.metaKey) && e.key === '/') {
                e.preventDefault();
                togglePanel();
            }
        });
        document.getElementById('kordaAssistantMessages').addEventListener('click', handleMessageClick);
        document.getElementById('kordaAssistantQuick').addEventListener('click', e => {
            if (e.target.closest('[data-toggle-quick]')) {
                toggleQuickExpand();
                return;
            }
            const btn = e.target.closest('[data-quick]');
            if (!btn) return;
            ask(btn.dataset.quick);
        });
    }

    function autoResize(el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 140) + 'px';
    }

    function submitInput() {
        const input = $('#kordaAssistantInput');
        const value = input.value.trim();
        if (!value) return;
        input.value = '';
        autoResize(input);
        ask(value);
    }

    function handleMessageClick(e) {
        const btn = e.target.closest('.ka-action');
        if (!btn) return;
        const action = btn.dataset.action || 'navigate';
        const target = btn.dataset.target;
        const query = btn.dataset.query;
        const entity = btn.dataset.entity;
        const id = Number(btn.dataset.id || 0);
        const view = btn.dataset.view || target || '';
        if (action === 'navigate' && target) {
            navigateAndAnnounce(target);
        } else if (action === 'openEntity' && entity && id) {
            openAssistantEntity(entity, id, view);
        } else if (action === 'guide' && query) {
            ask(query);
        } else if (query) {
            ask(query);
        }
    }

    function openAssistantEntity(entity, id, view) {
        if (typeof window.openOmniSearchResult === 'function') {
            try {
                window.openOmniSearchResult(entity, Number(id), view || '');
                return;
            } catch (_) { /* fallback ниже */ }
        }
        if (view && typeof window.navigateTo === 'function') {
            try { window.navigateTo(view); } catch (_) { /* noop */ }
        }
    }

    function navigateAndAnnounce(view) {
        if (typeof window.navigateTo === 'function') {
            try { window.navigateTo(view); } catch (_) { /* noop */ }
            const label = VIEW_LABELS[view] || view;
            pushBot({ html: `<p>Открыл раздел <strong>${escapeHtml(label)}</strong>. Если нужно — продолжай задавать вопросы.</p>` });
        } else {
            pushBot({ html: '<p>Навигация недоступна. Открой раздел через левое меню.</p>' });
        }
    }

    function openPanel() {
        const root = $('#kordaAssistantRoot');
        const panel = $('#kordaAssistantPanel');
        if (!root || !panel) return;
        state.open = true;
        panel.hidden = false;
        root.dataset.open = 'true';
        localStorage.setItem(STORAGE_OPEN, '1');
        if (!state.history.length) {
            const greet = answerGreeting();
            pushBot(greet);
        }
        setTimeout(() => $('#kordaAssistantInput')?.focus(), 50);
        // фоновый preload — чтобы первый вопрос про финансы/исполнительную не ждал сети
        ensureLoaded(['finance', 'executive']).catch(() => {});
    }

    function closePanel() {
        const root = $('#kordaAssistantRoot');
        const panel = $('#kordaAssistantPanel');
        if (!root || !panel) return;
        state.open = false;
        panel.hidden = true;
        root.dataset.open = 'false';
        localStorage.setItem(STORAGE_OPEN, '0');
    }

    function togglePanel() {
        if (state.open) closePanel(); else openPanel();
    }

    function pushUser(text) {
        state.history.push({ role: 'user', text, ts: Date.now() });
        saveHistory(state.history);
        renderMessages();
    }

    function pushBot(answer) {
        state.history.push({ role: 'bot', html: answer.html || '', stats: answer.stats || null, actions: answer.actions || null, ts: Date.now() });
        saveHistory(state.history);
        renderMessages();
        if (answer.navigate && typeof window.navigateTo === 'function') {
            setTimeout(() => { try { window.navigateTo(answer.navigate); } catch (_) { /* noop */ } }, 250);
        }
    }

    function renderMessages() {
        const list = $('#kordaAssistantMessages');
        if (!list) return;
        if (!state.history.length) {
            list.innerHTML = `<div class="ka-empty">${ICONS.sparkle}<p>Я готов отвечать. Задайте вопрос или нажмите чип ниже.</p></div>`;
            return;
        }
        list.innerHTML = state.history.map(renderMessageEntry).join('') + (state.thinking ? renderThinking() : '');
        list.scrollTop = list.scrollHeight;
    }

    function renderMessageEntry(msg) {
        const time = new Date(msg.ts || Date.now()).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        if (msg.role === 'user') {
            return `<article class="ka-msg ka-msg--user"><div class="ka-bubble ka-bubble--user"><p>${escapeHtml(msg.text).replace(/\n/g, '<br>')}</p></div><span class="ka-time">${time}</span></article>`;
        }
        const stats = renderStats(msg.stats || []);
        const actions = renderActions(msg.actions || []);
        return `<article class="ka-msg ka-msg--bot">
<div class="ka-msg-avatar">${ICONS.bot}</div>
<div class="ka-msg-body">
<div class="ka-bubble ka-bubble--bot">${msg.html || ''}${stats}${actions}</div>
<span class="ka-time">Korda Assistant · ${time}</span>
</div>
</article>`;
    }

    function renderThinking() {
        return `<article class="ka-msg ka-msg--bot ka-msg--thinking">
<div class="ka-msg-avatar">${ICONS.bot}</div>
<div class="ka-msg-body">
<div class="ka-bubble ka-bubble--bot ka-typing"><span></span><span></span><span></span></div>
</div>
</article>`;
    }

    function renderQuick() {
        const list = $('#kordaAssistantQuick');
        if (!list) return;
        const total = QUICK_DEFAULT.length;
        const hidden = Math.max(0, total - QUICK_VISIBLE_COUNT);
        const chips = QUICK_DEFAULT.map((q, idx) => {
            const cls = idx >= QUICK_VISIBLE_COUNT ? ' class="ka-quick-extra"' : '';
            return `<button type="button" data-quick="${escapeHtml(q.q)}"${cls}><span class="ka-quick-ic">${ICONS[q.icon] || ICONS.sparkle}</span>${escapeHtml(q.label)}</button>`;
        }).join('');
        const toggle = hidden > 0
            ? `<button type="button" class="ka-quick-toggle" data-toggle-quick aria-expanded="false"><span class="ka-quick-toggle-more">Ещё ${hidden}</span><span class="ka-quick-toggle-less">Свернуть</span></button>`
            : '';
        list.innerHTML = chips + toggle;
    }

    function toggleQuickExpand() {
        const list = $('#kordaAssistantQuick');
        if (!list) return;
        const expanded = list.dataset.expanded === 'true';
        list.dataset.expanded = expanded ? 'false' : 'true';
        const btn = list.querySelector('[data-toggle-quick]');
        if (btn) btn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    }

    async function ask(text) {
        const value = String(text || '').trim();
        if (!value) return;
        if (!state.open) openPanel();
        if (value.startsWith('/')) {
            await handleSlash(value);
            return;
        }
        pushUser(value);
        showThinking();
        try {
            const lower = normalize(value);
            const tags = tagsForQuery(lower);
            if (lower === 'помощь' || lower === 'help' || /что ты умеешь|какие команды|справка/.test(lower) || /^(привет|здрав|добр|hello|hi|hey|йоу)\b/.test(lower) || /спасиб|благодар|thanks|пока|до встречи|bye/.test(lower)) {
                hideThinking();
                pushBot(buildAnswer(value));
                return;
            }
            const currentScreenAnswer = answerCurrentScreenQuestion(value);
            if (currentScreenAnswer) {
                hideThinking();
                pushBot(currentScreenAnswer);
                return;
            }
            if (!isAssistantDomainQuestion(lower, tags)) {
                hideThinking();
                pushBot(assistantOutOfScopeAnswer());
                return;
            }
            await ensureLoaded(tags);
            const objectAnswer = answerObjectSearch(value);
            if (objectAnswer) {
                hideThinking();
                pushBot(objectAnswer);
                return;
            }
            const managementAnswer = answerManagementCoach(value);
            if (managementAnswer) {
                hideThinking();
                pushBot(managementAnswer);
                return;
            }
            const guideAnswer = answerSystemGuide(value);
            if (guideAnswer) {
                hideThinking();
                pushBot(guideAnswer);
                return;
            }
            const deterministicAnswer = answerSystemNavigation(value);
            if (deterministicAnswer) {
                hideThinking();
                pushBot(deterministicAnswer);
                return;
            }
            const answer = await askServerAi(value, tags) || buildAnswer(value);
            hideThinking();
            pushBot(answer);
        } catch (err) {
            hideThinking();
            pushBot({ html: '<p>Не удалось получить данные. Проверь подключение и попробуй ещё раз.</p>' });
        }
    }

    async function handleSlash(cmd) {
        const lower = cmd.slice(1).trim().toLowerCase();
        if (!lower || lower === 'помощь' || lower === 'help') { pushBot(answerHelp()); return; }
        if (lower === 'очистить' || lower === 'clear' || lower === 'reset') { clearHistory(); return; }
        showThinking();
        try {
            await ensureLoaded(tagsForQuery(lower) .concat(['finance', 'executive']));
            const d = dataSnapshot();
            hideThinking();
            if (lower === 'сводка' || lower === 'summary') { pushBot(answerSummary(d)); return; }
            if (lower === 'риски' || lower === 'risks') { pushBot(answerRisks(d)); return; }
            if (lower === 'финансы' || lower === 'finance') { pushBot(answerFinance(d, lower)); return; }
            if (lower === 'p&l' || lower === 'pnl' || lower === 'ддс') { pushBot(answerPnl(d)); return; }
            if (lower === 'задачи' || lower === 'tasks') { pushBot(answerTasks(d, 'мои задачи')); return; }
            if (lower === 'согласования' || lower === 'approvals') { pushBot(answerApprovals(d, lower)); return; }
            if (lower === 'документы' || lower === 'docs') { pushBot(answerDocuments(d, lower)); return; }
            if (lower === 'клиенты' || lower === 'clients') { pushBot(answerClients(d, lower)); return; }
            if (lower === 'проекты' || lower === 'projects') { pushBot(answerProjects(d, lower)); return; }
            if (lower === 'претензии' || lower === 'claims') { pushBot(answerClaims(d)); return; }
            if (lower === 'расходы' || lower === 'expenses') { pushBot(answerExpenses(d)); return; }
            if (lower === 'заявки' || lower === 'requests') { pushBot(answerRequests(d)); return; }
            if (lower === 'ресурсы' || lower === 'resources') { pushBot(answerResources(d)); return; }
            if (lower === 'сервис' || lower === 'service') { pushBot(answerService(d)); return; }
            if (lower === 'почта' || lower === 'mail') { pushBot(answerEmails(d)); return; }
            if (lower === 'встречи' || lower === 'meetings') { pushBot(answerMeetings(d)); return; }
            if (lower === 'обмен' || lower === '1с' || lower === 'sync') { pushBot(answerSync(d)); return; }
            const route = findRoute(lower);
            if (route) { pushBot(answerNavigate(route)); return; }
            await ask(lower);
        } catch (err) {
            hideThinking();
            pushBot({ html: '<p>Не удалось обработать команду.</p>' });
        }
    }

    function clearHistory() {
        state.history = [];
        saveHistory(state.history);
        renderMessages();
        if (state.open) {
            const greet = answerGreeting();
            pushBot(greet);
        }
    }

    function showThinking() {
        state.thinking = true;
        const root = $('#kordaAssistantRoot');
        if (root) root.dataset.thinking = 'true';
        renderMessages();
    }

    function hideThinking() {
        state.thinking = false;
        const root = $('#kordaAssistantRoot');
        if (root) root.dataset.thinking = 'false';
    }

    /* ---------- init ---------- */

    function init() {
        state.history = loadHistory();
        ensureMounted();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    /* ---------- public api (back-compat) ---------- */

    window.kordaAssistant = {
        open: openPanel,
        close: closePanel,
        toggle: togglePanel,
        ask,
        clear: clearHistory,
    };
    // legacy aliases for any old callers
    window.crmAssistantAsk = ask;
    window.crmAssistantToggle = togglePanel;
})();
