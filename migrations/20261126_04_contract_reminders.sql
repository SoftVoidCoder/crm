-- One row per reminder actually sent, so the hourly runner never repeats it (daily kinds use the date, one-off kinds use 'once').
CREATE TABLE IF NOT EXISTS cr_reminder_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT DEFAULT '',
    ref_id INTEGER DEFAULT 0,
    sent_on TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cr_reminder_log_unique ON cr_reminder_log(kind, ref_id, sent_on);
