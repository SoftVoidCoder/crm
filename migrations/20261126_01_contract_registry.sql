CREATE TABLE IF NOT EXISTS cr_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cr_counterparties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '',
    short_name TEXT DEFAULT '',
    inn TEXT DEFAULT '',
    kpp TEXT DEFAULT '',
    ogrn TEXT DEFAULT '',
    legal_address TEXT DEFAULT '',
    director TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    status TEXT DEFAULT '',
    is_own INTEGER DEFAULT 0,
    note TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cr_counterparties_inn ON cr_counterparties(inn);

CREATE TABLE IF NOT EXISTS cr_doc_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '',
    prefix TEXT DEFAULT '',
    counter INTEGER DEFAULT 0,
    digits INTEGER DEFAULT 0,
    postfix TEXT DEFAULT '',
    add_year INTEGER DEFAULT 0,
    counterparty_id INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cr_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type_id INTEGER DEFAULT 0,
    folder_id INTEGER DEFAULT 0,
    number TEXT DEFAULT '',
    seq_no INTEGER DEFAULT 0,
    extra_number TEXT DEFAULT '',
    incoming_number TEXT DEFAULT '',
    gov_reg_number TEXT DEFAULT '',
    flagged INTEGER DEFAULT 0,
    created_date TEXT DEFAULT '',
    concluded_date TEXT DEFAULT '',
    end_date TEXT DEFAULT '',
    amount REAL DEFAULT 0,
    currency TEXT DEFAULT 'RUB',
    vat_enabled INTEGER DEFAULT 0,
    vat_rate REAL DEFAULT 20,
    vat_manual INTEGER DEFAULT 0,
    vat_amount REAL DEFAULT 0,
    kind TEXT DEFAULT 'other',
    responsible TEXT DEFAULT '',
    initiator TEXT DEFAULT '',
    tender TEXT DEFAULT '',
    category TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    note TEXT DEFAULT '',
    basis TEXT DEFAULT '',
    notify_enabled INTEGER DEFAULT 0,
    notify_days INTEGER DEFAULT 0,
    notify_date TEXT DEFAULT '',
    internal_only INTEGER DEFAULT 0,
    payment_deferral INTEGER DEFAULT 0,
    framework INTEGER DEFAULT 0,
    prolongation INTEGER DEFAULT 0,
    prolongation_terms TEXT DEFAULT '',
    indefinite INTEGER DEFAULT 0,
    on_counterparty_signing INTEGER DEFAULT 0,
    sent_for_signing_date TEXT DEFAULT '',
    signed_date TEXT DEFAULT '',
    signed INTEGER DEFAULT 0,
    signing_method TEXT DEFAULT '',
    on_counterparty_review INTEGER DEFAULT 0,
    sent_to_counterparty_date TEXT DEFAULT '',
    original_status TEXT DEFAULT '',
    is_deleted INTEGER DEFAULT 0,
    created_by TEXT DEFAULT '',
    updated_by TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cr_contracts_folder ON cr_contracts(folder_id, is_deleted);

CREATE TABLE IF NOT EXISTS cr_contract_parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER DEFAULT 0,
    counterparty_id INTEGER DEFAULT 0,
    role TEXT DEFAULT '',
    auto_mailing INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cr_contract_parties_contract ON cr_contract_parties(contract_id);

CREATE TABLE IF NOT EXISTS cr_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER DEFAULT 0,
    approver TEXT DEFAULT '',
    department TEXT DEFAULT '',
    position TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    due_date TEXT DEFAULT '',
    decided_at INTEGER DEFAULT 0,
    comment TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cr_approvals_contract ON cr_approvals(contract_id);

CREATE TABLE IF NOT EXISTS cr_contract_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER DEFAULT 0,
    filename TEXT DEFAULT '',
    file_url TEXT DEFAULT '',
    size_bytes INTEGER DEFAULT 0,
    uploaded_by TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cr_contract_files_contract ON cr_contract_files(contract_id);

INSERT INTO cr_folders (name, sort_order, created_at) VALUES
    ('Аренда', 10, 0),
    ('Соглашение по ЭДО', 20, 0),
    ('ГПХ, самозанятые', 30, 0),
    ('Лизинг', 40, 0),
    ('Займы', 50, 0);
