-- Admin login drops the admin key (2026-10-10, owner's request): a code texted to
-- bot_config.twilio_to is now the only factor, so "text me a code" is reachable by anyone who
-- passes Turnstile. These two columns carry a per-day cap on admin codes, which is what bounds
-- the SMS bill and the owner's phone buzzing if someone automates past the challenge. The
-- 60-second cooldown (sent_at) still applies on top.
ALTER TABLE admin_otp ADD COLUMN sends_day TEXT;
ALTER TABLE admin_otp ADD COLUMN sends_count INTEGER NOT NULL DEFAULT 0;
