CREATE TABLE IF NOT EXISTS voice_feedbacks (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL UNIQUE,
  episode_id TEXT,
  raw_utterance TEXT NOT NULL,
  feedback_type TEXT,
  difficulty_signal TEXT,
  usefulness_signal TEXT,
  comment TEXT,
  metadata TEXT,
  occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('nagi_voice', 'api', 'manual'))
);

CREATE INDEX IF NOT EXISTS voice_feedbacks_occurred_at_idx
  ON voice_feedbacks(occurred_at DESC);

CREATE INDEX IF NOT EXISTS voice_feedbacks_episode_idx
  ON voice_feedbacks(episode_id, occurred_at DESC);
