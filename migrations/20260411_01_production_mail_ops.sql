ALTER TABLE email_accounts ADD COLUMN smtp_login TEXT DEFAULT '';
ALTER TABLE email_accounts ADD COLUMN smtp_password TEXT DEFAULT '';
ALTER TABLE email_accounts ADD COLUMN sync_fail_count INTEGER DEFAULT 0;
ALTER TABLE email_accounts ADD COLUMN next_retry_at INTEGER DEFAULT 0;
ALTER TABLE email_accounts ADD COLUMN last_sync_status TEXT DEFAULT 'idle';
ALTER TABLE email_accounts ADD COLUMN last_alert_at INTEGER DEFAULT 0;
ALTER TABLE email_accounts ADD COLUMN delivery_fail_count INTEGER DEFAULT 0;
ALTER TABLE email_accounts ADD COLUMN last_delivery_at INTEGER DEFAULT 0;
ALTER TABLE email_accounts ADD COLUMN last_delivery_error TEXT DEFAULT '';

ALTER TABLE email_messages ADD COLUMN delivery_status TEXT DEFAULT 'received';
ALTER TABLE email_messages ADD COLUMN last_action_error TEXT DEFAULT '';
ALTER TABLE email_messages ADD COLUMN last_action_at INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS email_delivery_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER DEFAULT 0,
    message_id INTEGER DEFAULT 0,
    direction TEXT DEFAULT 'outbound',
    recipient TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    status TEXT DEFAULT 'queued',
    error_text TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_email_accounts_retry_state ON email_accounts(is_active, next_retry_at, sync_fail_count);
CREATE INDEX IF NOT EXISTS idx_email_delivery_events_created ON email_delivery_events(created_at DESC);
