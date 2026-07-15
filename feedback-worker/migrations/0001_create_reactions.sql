CREATE TABLE IF NOT EXISTS reactions (
  id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  episode_id TEXT NOT NULL,
  reaction TEXT NOT NULL CHECK (reaction IN ('new', 'known', 'tried')),
  occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source = 'apple_shortcuts'),
  linked_reaction_id TEXT,
  FOREIGN KEY (linked_reaction_id) REFERENCES reactions(id)
);

CREATE INDEX IF NOT EXISTS reactions_occurred_at_idx
  ON reactions(occurred_at DESC);

CREATE INDEX IF NOT EXISTS reactions_kind_occurred_at_idx
  ON reactions(reaction, occurred_at DESC);
