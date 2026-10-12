-- Private application schema: never expose supplier data or password/session records
-- through Supabase's public Data API. Only the backend database connection uses it.
CREATE SCHEMA IF NOT EXISTS tve;
CREATE TABLE IF NOT EXISTS tve.store (
  id INTEGER PRIMARY KEY CHECK(id=1), revision BIGINT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tve.audit (
  id TEXT PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, label TEXT NOT NULL,
  before_data TEXT NOT NULL, after_data TEXT NOT NULL,
  seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);
CREATE INDEX IF NOT EXISTS audit_time_idx ON tve.audit(at DESC, seq DESC);
CREATE TABLE IF NOT EXISTS tve.users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tve.sessions (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES tve.users(id), expires DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS session_expiry_idx ON tve.sessions(expires);
CREATE TABLE IF NOT EXISTS tve.imports (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, payload TEXT NOT NULL, created DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS tve.rate_limits (
  key TEXT PRIMARY KEY, count INTEGER NOT NULL, until DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS tve.settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tve.user_access (
  user_id TEXT PRIMARY KEY REFERENCES tve.users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('admin','company')), company_ids TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
  display_name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tve.invitations (
  id TEXT PRIMARY KEY, email TEXT NOT NULL, display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','company')), company_ids TEXT NOT NULL,
  token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL,
  invited_by TEXT NOT NULL REFERENCES tve.users(id) ON DELETE CASCADE,
  used_at TEXT, canceled_at TEXT
);
CREATE TABLE IF NOT EXISTS tve.access_audit (
  id TEXT PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL
);
REVOKE ALL ON SCHEMA tve FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA tve FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA tve FROM PUBLIC;
DO $secure$
DECLARE r TEXT;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA tve FROM %I',r);
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA tve FROM %I',r);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA tve FROM %I',r);
    END IF;
  END LOOP;
END $secure$;
