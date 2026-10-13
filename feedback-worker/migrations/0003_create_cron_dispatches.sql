CREATE TABLE IF NOT EXISTS cron_dispatches (
  dispatch_date TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'failed')),
  dispatched_at TEXT NOT NULL,
  completed_at TEXT,
  workflow_file TEXT NOT NULL,
  error_message TEXT
);
