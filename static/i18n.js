(function () {
    const STORAGE_KEY = 'korda_ui_language';
    const SUPPORTED = ['ru', 'en', 'zh'];

    const technicalRu = new Map(Object.entries({
        'MAPPINGS TOTAL': 'Всего сопоставлений',
        'QUEUE OPEN': 'Открытая очередь',
        'QUEUE FAILED': 'Ошибки очереди',
        'RECONCILIATION RUNS': 'Прогоны сверки',
        'INBOUND RECEIVED': 'Входящие обновления',
        'BANK ACCOUNTS TOTAL': 'Банковские счета',
        'TELEPHONY ACCOUNTS TOTAL': 'Линии телефонии',
        'BI REPORTS TOTAL': 'Аналитические витрины',
        'MAPPING COVERAGE ENTITIES': 'Покрытые сущности',
        'BIDIRECTIONAL': 'Двусторонний',
        'EXPORTED': 'Выгружено',
        'Deep reconciliation': 'Глубокая сверка',
        'mismatch': 'расхождение',
        'stock_reservation': 'Складской резерв',
        'warehouse': 'склад',
        'status': 'статус',
        'serial_no': 'серийный номер',
        'fulfilled_qty': 'исполнено',
        'bank_api': 'Банковский интерфейс',
        'future': 'будущий период',
        'full': 'полное покрытие',
        'base': 'база',
        'vat': 'НДС',
        'assets': 'активы',
        'active': 'активный',
        'passive': 'пассивный',
        'queued': 'в очереди',
        'retry': 'повтор',
        'processing': 'обработка',
        'failed': 'ошибок',
        'stale': 'зависло',
        'DOCUMENTS TOTAL': 'Всего документов',
        'TEMPLATES TOTAL': 'Всего шаблонов',
        'VERSIONS TOTAL': 'Всего версий',
        'LINKED TASKS OPEN': 'Открытые поручения',
        'ARCHIVE TOTAL': 'Документов в архиве',
        'PRINT FORMS TOTAL': 'Печатные формы',
        'CERTIFICATES ACTIVE': 'Активные сертификаты',
        'CERTIFICATES EXPIRING': 'Истекающие сертификаты',
        'COVERAGE GAPS': 'Пробелы покрытия',
        'DOC TYPES STRICT': 'Строгие типы документов',
        'TYPING ISSUES': 'Проблемы типизации',
        'ARCHIVE RISKS': 'Риски архива',
        'TEMPLATE FAMILIES': 'Семейства шаблонов',
        'Timeline': 'История',
        'timeline': 'история',
        'Print set': 'Печатные формы',
        'print set': 'печатные формы',
        'Diff': 'Сравнение',
        'diff': 'сравнение',
        'before': 'было',
        'after': 'стало',
        'missing': 'не хватает',
        'suggested': 'предложено',
        'raw': 'исходный тип',
        'latest': 'последняя',
        'ECM': 'Документы',
        'Sync': 'Сверить',
        'sync': 'синхронизация',
        'queued': 'в очереди',
        'retry': 'повтор',
        'processing': 'обработка',
        'open': 'открыто',
        'closed': 'закрыто',
        'draft': 'черновик',
        'synced': 'синхронизировано',
        'archived': 'архив',
        'error': 'ошибка',
        'conflict': 'конфликт',
        'attention': 'требует внимания',
        'gap': 'пробел',
        'covered': 'покрыто',
        'shared': 'общий доступ',
        'incoming': 'входящий',
        'outgoing': 'исходящий',
        'internal': 'внутренний',
        'apply': 'применить',
        'preview': 'предпросмотр',
        'queue_only': 'только очередь',
        'exported': 'выгружено',
        'created': 'создано',
        'updated': 'обновлено',
        'paid': 'оплачено',
        'planned': 'план',
        'overdue': 'просрочено',
        'hold': 'удержание',
        'inspect': 'проверка',
        'accepted': 'принято',
        'rejected': 'отклонено',
        'base': 'база',
        'future': 'будущий период',
        'vat': 'НДС',
        'assets': 'активы',
        'stock_reservation': 'Складской резерв',
        'production_order': 'Производственный заказ',
        'sales_document': 'Документ продажи',
        'finance_payment': 'Финансовая операция',
        'purchase_order': 'Заказ поставщику',
        'nomenclature': 'Номенклатура',
        'groups': 'Группы',
        'warehouses': 'Склады',
        'warehouse': 'склад',
        'id': 'идентификатор',
        'name': 'название',
        'qty': 'количество',
        'fulfilled_qty': 'исполнено',
        'project_id': 'проект',
        'status': 'статус',
        'serial_no': 'серийный номер',
        'external_id': 'внешний идентификатор',
        'entity_id': 'идентификатор записи',
        'field': 'поле',
        'view': 'просмотр',
        'edit': 'редактирование',
        'active_total': 'активных',
        'documents_total': 'документов',
        'templates_total': 'шаблонов',
        'versions_total': 'версий',
        'mismatch': 'расхождение',
        'mismatches': 'расхождения',
        'stale locks': 'зависшие блокировки',
        'recovery': 'восстановление',
        'Bank accounts': 'Банковские счета',
        'Telephony': 'Телефония',
        'BI reports': 'Отчёты аналитики',
        'BI': 'Аналитика',
        'pipeline': 'воронка',
        'Pipeline': 'Воронка',
        'Rating': 'Рейтинг',
        'Reliability': 'Надёжность',
        'Qty': 'Количество',
        'qty': 'количество',
        'Average': 'Средняя',
        'average': 'средняя',
        'planned': 'запланировано',
        'partial': 'частично',
        'delivered': 'доставлено',
        'late': 'поздно',
        'approved': 'согласовано',
        'resolved': 'решено',
        'done': 'выполнено',
        'normal': 'обычный',
        'priority': 'приоритет',
        'critical': 'критично',
        'ready': 'готово',
        'stable': 'стабильно',
        'risk': 'риск',
        'on': 'включено',
        'off': 'выключено',
        'negative': 'минус',
        'external': 'внешний',
        'entity': 'сущность',
        'field': 'поле',
        'method': 'метод',
        'client': 'клиент',
        'provider': 'провайдер',
        'RUB': 'рубль',
        'USD': 'доллар',
        'EUR': 'евро',
        'CNY': 'юань',
        'FIFO': 'ФИФО',
        'LIFO': 'ЛИФО',
        'WIP': 'незавершёнка',

        /* --- Status tokens, частые в API ответах --- */
        'pending': 'ожидание',
        'completed': 'завершено',
        'cancelled': 'отменено',
        'canceled': 'отменено',
        'reconciled': 'сверено',
        'matched': 'сопоставлено',
        'unmatched': 'не сопоставлено',
        'verified': 'проверено',
        'confirmed': 'подтверждено',
        'signed': 'подписано',
        'delivered': 'доставлено',
        'shipped': 'отгружено',
        'received': 'получено',
        'processed': 'обработано',
        'reviewed': 'проверено',
        'escalated': 'эскалировано',
        'locked': 'заблокировано',
        'unlocked': 'разблокировано',
        'disabled': 'выключено',
        'enabled': 'включено',
        'hidden': 'скрыто',
        'visible': 'видимо',
        'primary': 'основное',
        'secondary': 'вторичное',
        'tertiary': 'третичное',
        'critical': 'критично',
        'major': 'крупное',
        'minor': 'мелкое',
        'info': 'инфо',
        'warning': 'предупреждение',
        'success': 'успех',
        'danger': 'риск',
        'released': 'выпущено',
        'departed': 'отправлено',
        'breached': 'нарушено',
        'banned': 'забанено',
        'blocked': 'заблокировано',
        'block': 'блок',
        'deferred': 'отложено',
        'applied': 'применено',
        'answered': 'отвечено',
        'archive': 'архив',
        'attention': 'требует внимания',
        'high': 'высокий',
        'medium': 'средний',
        'low': 'низкий',

        /* --- Operations / WMS --- */
        'pick': 'отбор',
        'putaway': 'размещение',
        'receiving': 'приёмка',
        'shipping': 'отгрузка',
        'storage': 'хранение',
        'cycle_count': 'инвентаризация',
        'complete_putaway': 'завершить размещение',
        'lookup': 'поиск',
        'dispatcher_departure': 'отправка диспетчером',
        'internal_memo': 'внутренняя записка',
        'internal_order': 'внутренний заказ',
        'any_change': 'любое изменение',

        /* --- Document / approval flow --- */
        'sent': 'отправлено',
        'received_back': 'возвращено',
        'in_review': 'на проверке',
        'partially_paid': 'частично оплачено',
        'partially_shipped': 'частично отгружено',
        'on_hold': 'на удержании',
        'returned': 'возврат',
        'reopened': 'переоткрыто',
        'closed_lost': 'закрыто проиграно',
        'closed_won': 'закрыто выиграно',
        'in_progress': 'в работе',
        'in_queue': 'в очереди',
        'scheduled': 'запланировано',
        'expired': 'истёк срок',

        /* --- Dashboard tabs / common --- */
        'all': 'все',
        'mine': 'мои',
        'today': 'сегодня',
        'week': 'неделя',
        'month': 'месяц',
        'quarter': 'квартал',
        'year': 'год',
        'overdue_only': 'только просрочка',
        'urgent': 'срочно',
        'low_priority': 'низкий приоритет',
        'high_priority': 'высокий приоритет',

        /* --- Connector / sync states --- */
        'idle': 'простой',
        'paused': 'на паузе',
        'running': 'запущено',
        'finished': 'завершено',
        'aborted': 'прервано',
        'timeout': 'таймаут',
        'unauthorized': 'нет доступа',
        'forbidden': 'запрещено',
        'not_found': 'не найдено',
        'rate_limited': 'лимит запросов',
    }));

    const dictionaries = {
        en: {
            'Язык': 'Language',
            'Русский': 'Russian',
            'Главная': 'Home',
            'Панель директора': 'Executive panel',
            'Операционный центр ERP': 'ERP operations center',
            'Операционный центр': 'Operations center',
            'Финансы': 'Finance',
            'Бухгалтерия': 'Accounting',
            'Снабжение': 'Procurement',
            'Продажи': 'Sales',
            'Производство': 'Production',
            'Склад': 'Warehouse',
            'НСИ': 'Master data',
            'Документы': 'Documents',
            'Безопасность': 'Security',
            'Интеграции': 'Integrations',
            'Проекты': 'Projects',
            'Клиенты': 'Clients',
            'Обновить': 'Refresh',
            'Удалить': 'Delete',
            'Сохранить': 'Save',
            'Добавить': 'Add',
            'Проверить': 'Check',
            'Синхронизировать': 'Sync',
            'Запустить': 'Run',
            'Экспорт': 'Export',
            'Импорт': 'Import',
            'Закрыть': 'Close',
            'Открыть': 'Open',
            'Активно': 'Active',
            'Черновик': 'Draft',
            'Ошибка': 'Error',
            'Сбой': 'Failure',
            'Конфликт': 'Conflict',
            'В очереди': 'Queued',
            'Двусторонний': 'Bidirectional',
            'Входящий': 'Inbound',
            'Исходящий': 'Outbound',
            'Выгружено': 'Exported',
            'Глубокая сверка': 'Deep reconciliation',
            'Всего сопоставлений': 'Mappings total',
            'Открытая очередь': 'Queue open',
            'Ошибки очереди': 'Queue failed',
            'Прогоны сверки': 'Reconciliation runs',
            'Входящие обновления': 'Inbound updates',
            'Банковские счета': 'Bank accounts',
            'Линии телефонии': 'Telephony lines',
            'Аналитические витрины': 'BI views',
            'Покрытые сущности': 'Covered entities',
            'Складской резерв': 'Stock reservation',
            'серийный номер': 'serial number',
            'исполнено': 'fulfilled',
            'склад': 'warehouse',
            'статус': 'status',
            'расхождений': 'mismatches',
            'Коннекторы и аналитика': 'Connectors and analytics',
            'Входящих обновлений пока нет.': 'No inbound updates yet.',
            'Конфликтов сейчас нет.': 'No conflicts right now.',
        },
        zh: {
            'Язык': '语言',
            'Русский': '俄语',
            'Главная': '首页',
            'Панель директора': '管理面板',
            'Операционный центр ERP': 'ERP运营中心',
            'Операционный центр': '运营中心',
            'Финансы': '财务',
            'Бухгалтерия': '会计',
            'Снабжение': '采购',
            'Продажи': '销售',
            'Производство': '生产',
            'Склад': '仓库',
            'НСИ': '主数据',
            'Документы': '文档',
            'Безопасность': '安全',
            'Интеграции': '集成',
            'Проекты': '项目',
            'Клиенты': '客户',
            'Обновить': '刷新',
            'Удалить': '删除',
            'Сохранить': '保存',
            'Добавить': '添加',
            'Проверить': '检查',
            'Синхронизировать': '同步',
            'Запустить': '运行',
            'Экспорт': '导出',
            'Импорт': '导入',
            'Закрыть': '关闭',
            'Открыть': '打开',
            'Активно': '启用',
            'Черновик': '草稿',
            'Ошибка': '错误',
            'Сбой': '失败',
            'Конфликт': '冲突',
            'В очереди': '队列中',
            'Двусторонний': '双向',
            'Входящий': '传入',
            'Исходящий': '传出',
            'Выгружено': '已导出',
            'Глубокая сверка': '深度对账',
            'Всего сопоставлений': '映射总数',
            'Открытая очередь': '开放队列',
            'Ошибки очереди': '队列错误',
            'Прогоны сверки': '对账运行',
            'Входящие обновления': '传入更新',
            'Банковские счета': '银行账户',
            'Линии телефонии': '电话线路',
            'Аналитические витрины': '分析看板',
            'Покрытые сущности': '覆盖实体',
            'Складской резерв': '库存预留',
            'серийный номер': '序列号',
            'исполнено': '已完成',
            'склад': '仓库',
            'статус': '状态',
            'расхождений': '差异',
            'Коннекторы и аналитика': '连接器和分析',
            'Входящих обновлений пока нет.': '暂无传入更新。',
            'Конфликтов сейчас нет.': '当前没有冲突。',
        },
    };

    let applying = false;
    let pending = 0;
    const originalTextNodes = new WeakMap();

    function currentLanguage() {
        const saved = localStorage.getItem(STORAGE_KEY) || 'ru';
        return SUPPORTED.includes(saved) ? saved : 'ru';
    }

    function escapeRegExp(value) {
        return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function replaceVisibleToken(text, source, target) {
        if (/^[A-Za-z0-9_]+$/.test(source)) {
            return text.replace(new RegExp(`\\b${escapeRegExp(source)}\\b`, 'g'), target);
        }
        return text.replaceAll(source, target);
    }

    function translatePlain(text, lang) {
        if (!text || !text.trim()) return text;
        const normalized = technicalRu.get(text.trim()) || text;
        if (lang === 'ru') return normalized;
        const dictionary = dictionaries[lang] || {};
        return dictionary[normalized] || normalized;
    }

    function translateMixed(text, lang) {
        if (!text || !text.trim()) return text;
        let result = text;
        Array.from(technicalRu.entries())
            .sort((a, b) => b[0].length - a[0].length)
            .forEach(([source, ru]) => {
                result = replaceVisibleToken(result, source, ru);
            });
        if (lang === 'ru') return result;
        const dictionary = dictionaries[lang] || {};
        Object.entries(dictionary)
            .sort((a, b) => b[0].length - a[0].length)
            .forEach(([source, target]) => {
                result = result.replaceAll(source, target);
            });
        return result;
    }

    function walkTextNodes(root, callback) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                if (['SCRIPT', 'STYLE', 'TEXTAREA'].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
                if (parent.closest('[data-i18n-skip]')) return NodeFilter.FILTER_REJECT;
                return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
            },
        });
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(callback);
    }

    function applyAppLanguage(root) {
        if (applying) return;
        applying = true;
        try {
            const lang = currentLanguage();
            const scope = root && root.nodeType === 1 ? root : document.body;
            const select = document.getElementById('appLanguageSelect');
            if (select && select.value !== lang) select.value = lang;
            if (document.documentElement) document.documentElement.lang = lang;
            if (!scope) return;
            walkTextNodes(scope, node => {
                if (!originalTextNodes.has(node)) originalTextNodes.set(node, node.nodeValue);
                const next = translateMixed(originalTextNodes.get(node), lang);
                if (next !== node.nodeValue) node.nodeValue = next;
            });
            scope.querySelectorAll('input[placeholder], textarea[placeholder], [title], [aria-label]').forEach(el => {
                ['placeholder', 'title', 'aria-label'].forEach(attr => {
                    const value = el.getAttribute(attr);
                    if (!value) return;
                    const originalAttr = `data-i18n-original-${attr}`;
                    if (!el.hasAttribute(originalAttr)) el.setAttribute(originalAttr, value);
                    const next = translateMixed(el.getAttribute(originalAttr), lang);
                    if (next !== value) el.setAttribute(attr, next);
                });
            });
        } finally {
            applying = false;
        }
    }

    function scheduleApply(root) {
        window.clearTimeout(pending);
        pending = window.setTimeout(() => applyAppLanguage(root || document.body), 80);
    }

    window.setAppLanguage = function setAppLanguage(lang) {
        const next = SUPPORTED.includes(lang) ? lang : 'ru';
        localStorage.setItem(STORAGE_KEY, next);
        applyAppLanguage(document.body);
        if (typeof showToast === 'function') {
            const label = next === 'ru' ? 'Русский' : next === 'en' ? 'Английский' : 'Китайский';
            showToast('Интерфейс', `Язык переключен: ${label}`);
        }
    };

    window.applyAppLanguage = applyAppLanguage;

    document.addEventListener('DOMContentLoaded', () => {
        applyAppLanguage(document.body);
        const observer = new MutationObserver(mutations => {
            if (applying) return;
            const root = mutations.find(item => item.addedNodes && item.addedNodes.length)?.target || document.body;
            scheduleApply(root);
        });
        observer.observe(document.body, { childList: true, subtree: true });
    });
})();
