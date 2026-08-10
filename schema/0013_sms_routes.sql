-- Inbound SMS routing. One Twilio number, one webhook, several projects behind it.
--
-- A phone number has exactly one sms_url, so whichever project owns the webhook owns *all*
-- inbound traffic to that number. Before this table that was tsd-boarddocs, and every message
-- from anyone other than the owner was answered with 403 and silence. That was fine while the
-- only sender was the owner. It stops being fine the moment a second project texts members of
-- the public, because those people reply -- to say STOP, to ask a question, or to send the code
-- back -- and their replies vanish.
--
-- So the webhook becomes a router. It still validates the Twilio signature itself (that is not
-- delegable: it needs the account auth token), then picks a route and either handles the message
-- locally or forwards it to the owning project over an HMAC-signed POST.
--
-- Matching: the first enabled route, by ascending priority, whose to_number, from_number and
-- pattern all match. NULL means "any" in each of those three columns.
--   to_number    E.164 destination -- which of our numbers it was texted to.
--   from_number  E.164 sender, or the literal '$owner' meaning bot_config.twilio_to.
--   pattern      JS regex source, tested case-insensitively against the trimmed body.
--   endpoint     NULL handles it in this Worker; otherwise an https URL to relay to.
--
-- No route matching is deliberately a 403, preserving the old behaviour for strangers rather
-- than inventing a reply for traffic nobody has claimed.

CREATE TABLE IF NOT EXISTS sms_routes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project     TEXT    NOT NULL,
  to_number   TEXT,
  from_number TEXT,
  pattern     TEXT,
  endpoint    TEXT,
  secret      TEXT,
  enabled     INTEGER NOT NULL DEFAULT 1,
  priority    INTEGER NOT NULL DEFAULT 100,
  note        TEXT,
  created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_sms_routes_lookup ON sms_routes(enabled, priority);

-- Seed the two live local flows plus a catch-all for the owner, reproducing exactly what the
-- handler did before routing existed. Priorities leave gaps so a project can be slotted between
-- them without renumbering.
INSERT INTO sms_routes (project,to_number,from_number,pattern,endpoint,enabled,priority,note,created_at)
SELECT 'tsd-boarddocs', NULL, '$owner', '^[12](\s*#?\s*\d+)?$', NULL, 1, 10,
       'registration approve/decline', strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE NOT EXISTS (SELECT 1 FROM sms_routes WHERE priority=10);

INSERT INTO sms_routes (project,to_number,from_number,pattern,endpoint,enabled,priority,note,created_at)
SELECT 'tsd-boarddocs', NULL, '$owner', '^(yes|no|y|n)\s*#?\s*\d+', NULL, 1, 20,
       'question moderation', strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE NOT EXISTS (SELECT 1 FROM sms_routes WHERE priority=20);

-- Anything else from the owner still gets the help text rather than a 403.
INSERT INTO sms_routes (project,to_number,from_number,pattern,endpoint,enabled,priority,note,created_at)
SELECT 'tsd-boarddocs', NULL, '$owner', NULL, NULL, 1, 900,
       'owner catch-all: help text', strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE NOT EXISTS (SELECT 1 FROM sms_routes WHERE priority=900);
