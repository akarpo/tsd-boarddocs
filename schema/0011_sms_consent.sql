-- SMS consent for the /ask registration, with its timestamp.
-- Carriers require A2P consent to be express, affirmative and PROVABLE. A phone number typed
-- into a form is not consent, so /ask now carries its own unchecked checkbox and the answer is
-- recorded here. Nullable on purpose: NULL = never asked (rows predating the checkbox),
-- 0 = asked and declined, 1 = consented. Those are different facts.
ALTER TABLE bot_users ADD COLUMN sms_consent    INTEGER;
ALTER TABLE bot_users ADD COLUMN sms_consent_at TEXT;
