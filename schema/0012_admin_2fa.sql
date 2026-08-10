-- Admin login becomes two-factor: the admin key proves knowledge, a six-digit code texted to
-- bot_config.twilio_to proves possession. After this migration the key alone opens nothing --
-- /admin/* accepts only a session minted by completing both steps.
--
-- Both tables are read with env.DB directly and never through botCfg(). That cache has a 60s TTL,
-- so routing OTP state through it would let the verify step read back a hash from before the
-- start step wrote it -- a login that fails for exactly one minute and then starts working.

-- Single-row table; the CHECK is what keeps it single-row rather than convention.
CREATE TABLE IF NOT EXISTS admin_otp (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  code_hash  TEXT,
  expires    TEXT,
  sent_at    TEXT,
  attempts   INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO admin_otp (id) VALUES (1);

CREATE TABLE IF NOT EXISTS admin_sessions (
  token      TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  expires    TEXT NOT NULL
);

-- Expired rows are swept opportunistically on each successful login; the index keeps that sweep
-- from turning into a table scan.
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires);
