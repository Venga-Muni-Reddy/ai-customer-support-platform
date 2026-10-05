CREATE TABLE IF NOT EXISTS workspaces (
  id SERIAL PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  admin_hash TEXT NOT NULL,
  is_demo BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS documents (
  id SERIAL PRIMARY KEY,
  workspace_id INT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'upload',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chunks (
  id SERIAL PRIMARY KEY,
  document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  workspace_id INT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  idx INT NOT NULL,
  content TEXT NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_ws_idx ON chunks (workspace_id);
CREATE TABLE IF NOT EXISTS questions (
  id SERIAL PRIMARY KEY,
  workspace_id INT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  session_id TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT,
  confidence INT,
  status TEXT NOT NULL,            -- auto_resolved | escalated | human_resolved
  escalation_reason TEXT,
  sources JSONB NOT NULL DEFAULT '[]',
  verdict JSONB,
  trace JSONB NOT NULL DEFAULT '[]',
  human_reply TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS q_ws_idx ON questions (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS q_session_idx ON questions (session_id);

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  pw_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS owner_id INT REFERENCES users(id) ON DELETE CASCADE;
