-- Rows of the contract card sections (payments, stages, claims, ...): one table, the section schema lives in the UI.
CREATE TABLE IF NOT EXISTS cr_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER DEFAULT 0,
    section TEXT DEFAULT '',
    data_json TEXT DEFAULT '{}',
    created_by TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cr_items_contract ON cr_items(contract_id, section);

CREATE TABLE IF NOT EXISTS cr_param_defs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '',
    field_type TEXT DEFAULT 'text',
    options TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cr_approval_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '',
    rows_json TEXT DEFAULT '[]',
    created_by TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0
);

ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS prepayment_terms TEXT DEFAULT '';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS closing_info TEXT DEFAULT '';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS object_info TEXT DEFAULT '';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS insurance_info TEXT DEFAULT '';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS owner_approval TEXT DEFAULT '';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS custom_json TEXT DEFAULT '{}';

ALTER TABLE cr_contract_files ADD COLUMN IF NOT EXISTS content_text TEXT DEFAULT '';

INSERT INTO cr_param_defs (name, field_type, options, sort_order, created_at) VALUES
    ('Срок исполнения обязательств', 'date', '', 10, 0);
