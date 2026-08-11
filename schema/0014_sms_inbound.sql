-- A log of every inbound SMS the router sees, whichever way it was disposed of.
--
-- Before this, inbound messages left no trace here at all. The owner's "1" approved a
-- registration and vanished; a stranger's text produced a 403 and vanished; a relayed message
-- was recorded by the peer project but not by the router that handed it over. Twilio's own
-- message log held all of them, which meant the only way to answer "what did somebody text us"
-- was to open a different vendor's console.
--
-- `disposition` records which of four things happened:
--   local         handled by this project's command grammar (registration / question replies)
--   relayed       forwarded to a peer project, which accepted it
--   relay_failed  forwarded, but the peer was unreachable or rejected the signature
--   unrouted      no route claimed it; the sender got a 403 and no reply
--
-- `unrouted` is the row type most worth having. Those messages are invisible everywhere except
-- Twilio precisely because nobody claimed them, so they are the ones that reveal a routing gap.
--
-- from_number is stored in full, unlike tsdfeedback-2026's copy which hashes it. Hashing is
-- right there: its subjects are survey respondents and it only needs to correlate, not read.
-- Here the admin panel already lists registrants' phone numbers, it is behind two-factor auth
-- and has one user, and a log whose sender you cannot read fails to answer the question you
-- opened it to ask.

CREATE TABLE IF NOT EXISTS sms_inbound (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at TEXT    NOT NULL,
  from_number TEXT,
  to_number   TEXT,
  body        TEXT    NOT NULL DEFAULT '',
  message_sid TEXT,
  route_id    INTEGER,
  project     TEXT,
  disposition TEXT    NOT NULL,
  reply       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sms_inbound_recent ON sms_inbound(id DESC);
