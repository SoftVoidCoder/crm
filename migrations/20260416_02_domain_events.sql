CREATE TABLE IF NOT EXISTS domain_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_name TEXT NOT NULL DEFAULT '',
    event_name TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    actor_email TEXT NOT NULL DEFAULT '',
    actor_name TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    severity TEXT NOT NULL DEFAULT 'info',
    created_at INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_domain_events_domain_created
    ON domain_events(domain_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_domain_events_entity_created
    ON domain_events(entity_type, entity_id, created_at DESC);
