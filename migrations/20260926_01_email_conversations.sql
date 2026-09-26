CREATE TABLE IF NOT EXISTS email_sent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER DEFAULT 0,
    source_message_id INTEGER DEFAULT 0,
    recipient TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    body_text TEXT DEFAULT '',
    attachments_json TEXT DEFAULT '[]',
    created_at INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_email_sent_messages_contact
ON email_sent_messages(account_id, recipient, created_at DESC);

INSERT INTO email_sent_messages (
    account_id, source_message_id, recipient, subject, body_text, attachments_json, created_at
)
SELECT
    e.account_id,
    e.message_id,
    e.recipient,
    e.subject,
    '',
    '[]',
    e.created_at
FROM email_delivery_events e
WHERE e.status='success'
  AND NOT EXISTS (
      SELECT 1
      FROM email_sent_messages s
      WHERE s.account_id=e.account_id
        AND s.source_message_id=e.message_id
        AND s.recipient=e.recipient
        AND s.subject=e.subject
        AND s.created_at=e.created_at
  );
