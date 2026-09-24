ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS auth_type TEXT DEFAULT 'password';
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS oauth_provider TEXT DEFAULT '';
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS oauth_access_token TEXT DEFAULT '';
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS oauth_refresh_token TEXT DEFAULT '';
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS oauth_expires_at BIGINT DEFAULT 0;
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS oauth_scope TEXT DEFAULT '';
ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS provider_account_id TEXT DEFAULT '';
