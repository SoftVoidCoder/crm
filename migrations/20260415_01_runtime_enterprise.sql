CREATE TABLE IF NOT EXISTS background_job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT DEFAULT '',
    job_group TEXT DEFAULT 'system',
    status TEXT DEFAULT 'running',
    started_at INTEGER DEFAULT 0,
    heartbeat_at INTEGER DEFAULT 0,
    finished_at INTEGER DEFAULT 0,
    details TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS recovery_workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name TEXT DEFAULT '',
    actor_email TEXT DEFAULT '',
    target_scope TEXT DEFAULT '',
    status TEXT DEFAULT 'running',
    started_at INTEGER DEFAULT 0,
    finished_at INTEGER DEFAULT 0,
    details TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_background_jobs_group_status_started
ON background_job_runs(job_group, status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_recovery_workflows_status_started
ON recovery_workflow_runs(status, started_at DESC);
