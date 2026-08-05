#!/usr/bin/env bash
# a2p_resubmit.sh — correct the A2P 10DLC campaign for tsd-boarddocs.karpowitsch.org.
#
# WHY THIS EXISTS
# The campaign (console sid CM1084cf…) was submitted on 2026-08-02 with content that does not
# describe this site: the description said "Two Factor Auth / Query validation for access to AI
# Prompt", both message samples were the identical placeholder "Example: Your one time passcode
# is 123456", it declared HasEmbeddedLinks/HasEmbeddedPhone true when the OTP contains neither,
# and the opt-in was described as "End users opt in by going to tsd-boarddocs.karpowitsch.org and
# going to the AI Prompt mechanism and entering their phone number" -- a phone number typed into a
# form, which is not consent. Those are the documented causes of errors 30893 and 30909
# (see docs/TWILIO_A2P_10DLC.md, which lives in THIS repo as of 2026-08-05; it was previously
# referenced here but only ever existed in the foxhalltroy repo).
#
# The payload below is corrected: samples copied byte-for-byte from worker.js, flags matching the
# real message, and a MessageFlow quoting the consent checkbox that is now live on /ask.
#
# RESOLVED 2026-08-05: the bad campaign was DELETED AND RECREATED.
#   Starter Customer Profile ....... Approved
#   Sole Proprietor Brand .......... Registered   (BN350b79…, brand "Alex Karpowitsch")
#   Sole Proprietor Campaign ....... CM83307937aa2983ca225bf6af8474ab99 -- created 2026-08-05 with
#                                    the corrected payload, now "In progress" (carrier review,
#                                    2-3 weeks). Linked to the same MG125c5d71… the Worker targets.
# Waiting for the old submission to fail would have cost ~3 weeks before this could even be tried,
# so it was deleted instead; the brand survived as Registered, so only the campaign fee (~$15 +
# $2/month) was re-incurred. The "You have an unfinished A2P 10DLC registration" banner is still
# showing and that is correct -- it tracks campaign approval, which is pending.
#
# NOTE: the recreated campaign leaves OptInKeywords/OptInMessage BLANK. Opt-in is web-only, and
# the console says to leave them blank if you do not support opt-in by text. The payload below
# still sets OptInKeywords=START -- drop those two fields before reusing it on this campaign.
#
# YOU CANNOT RUN THIS WHILE THE CAMPAIGN IS UNDER REVIEW.
# Twilio only permits an update from a FAILURE state:
#     400 ... Campaign update is allowed only for FAILURE state(s).
#             It is not allowed in the current state PENDING_DCA1_REVIEW
# So: wait for the current review to finish. If it is approved, nothing to do. If it fails, run
# this immediately -- updating in place is cheaper than delete-and-recreate, which can re-trigger
# vetting fees.
#
# The console's "Edit Campaign" modal exposes every field this script sets (description, the five
# samples, the content-type checkboxes, the consent description, privacy/terms URLs) plus an
# "I agree the above information is correct" attestation tied to the vetting fee. It is a second
# route to the same API, so expect the same refusal while the state is not FAILURE -- but it costs
# nothing to try, and it is the only route that does not need the secrets file.
#
#   ./scripts/a2p_resubmit.sh status     # campaign state + any rejection reasons
#   ./scripts/a2p_resubmit.sh submit     # push the corrected payload (only works from FAILURE)
#
# Auth: prefers an API key (SK…/secret). TWILIO_AUTH_TOKEN works but is root-equivalent for the
# whole account -- issue a Standard key and use that instead.
#
# WHICH campaign this touches is decided by TWILIO_MESSAGING_SERVICE_SID + the credentials, NOT by
# the QE… sid. Two different identifiers are in play and they are easy to confuse:
#   CM… is what the console calls the Campaign SID (CM1084cf… here).
#   QE… is what GET /Services/$MG/Compliance/Usa2p returns as "sid" -- the compliance record, not
#        the campaign. Note the console separately reports "Compliance Registration SID: null",
#        so do not expect the two to line up.
# A 2026-08-04 note claimed the QE value collided across two unrelated accounts. That has NOT been
# re-verified since, and Twilio sids are meant to be globally unique -- treat it as unconfirmed.
# The safe rule stands either way: identify a campaign by MG + credentials, never by QE.
# Point the MG at the wrong service and you will edit the wrong project's campaign.
#
# THIS PROJECT'S ACCOUNT IS NOT FOX HALL'S. tsd-boarddocs is akarpo@gmail.com; foxhalltroy is
# admin@foxhalltroy.com. Separate accounts, separate brands, separate campaigns, near-identical
# OTP designs. Confirm the login email AND the account sid before touching anything.
set -euo pipefail

# Identifiers come from the secrets file outside the repo, never hardcoded: GitHub push
# protection rejects a committed Twilio Account SID, and it is the right call -- an AC SID plus a
# leaked token is a whole account.
SECRETS="${TSD_SECRETS_FILE:-$HOME/Downloads/tsd-boarddocs-keysandsupportingfiles/tsd-secrets.env}"
[[ -f "$SECRETS" ]] && set -a && . "$SECRETS" && set +a

AC="${TWILIO_ACCOUNT_SID:-}"
MG="${TWILIO_MESSAGING_SERVICE_SID:-}"
QE="${TWILIO_CAMPAIGN_SID:-}"
if [[ -z "$AC" || -z "$MG" || -z "$QE" ]]; then
  echo "missing TWILIO_ACCOUNT_SID / TWILIO_MESSAGING_SERVICE_SID / TWILIO_CAMPAIGN_SID" >&2
  echo "  put them in $SECRETS, or export them" >&2
  exit 2
fi

if [[ -n "${TWILIO_API_KEY_SID:-}" && -n "${TWILIO_API_SECRET:-}" ]]; then
  AUTH="$TWILIO_API_KEY_SID:$TWILIO_API_SECRET"
elif [[ -n "${TWILIO_AUTH_TOKEN:-}" ]]; then
  AUTH="$AC:$TWILIO_AUTH_TOKEN"
else
  echo "set TWILIO_API_KEY_SID + TWILIO_API_SECRET (preferred), or TWILIO_AUTH_TOKEN" >&2
  exit 2
fi

API="https://messaging.twilio.com/v1/Services/$MG/Compliance/Usa2p"

case "${1:-status}" in
status)
  curl -sS -u "$AUTH" "$API" | python3 -c '
import json,sys
c=(json.load(sys.stdin).get("compliance") or [{}])[0]
print("campaign :", c.get("sid"))
print("status   :", c.get("campaign_status"))
print("brand    :", c.get("brand_registration_sid"))
print("updated  :", c.get("date_updated"))
errs=c.get("errors") or []
print(f"errors ({len(errs)}):")
for e in errs:
    print("  ", e.get("error_code"), e.get("description"))
    if e.get("fields"): print("     fields:", e["fields"])
print("samples  :")
for s in c.get("message_samples") or []: print("   -", s)
'
  ;;
submit)
  # Quoted from the live page. If the wording on /ask changes, change it here too -- a reviewer
  # compares them, and a flow describing something that is not on the page is error 30909.
  FLOW='Consumers opt in on https://tsd-boarddocs.karpowitsch.org/ask . On the "Register" tab they enter their name, email, mobile phone and reason for access, and must separately tick an unchecked checkbox labelled "Text me my sign-in codes". The disclosure beside that checkbox reads: "By ticking this box you agree to receive one-time sign-in codes by text message from the Troy SD Archive (tsd-boarddocs.karpowitsch.org) at the number above. Codes are sent only when you ask to sign in - roughly 2-4 messages a month, and never marketing. Msg & data rates may apply. Reply STOP to opt out or HELP for help. Consent is not a condition of access - say no and we will email your codes instead." The checkbox is visible on page load and is not pre-checked; consent and its timestamp are stored per user, and no text is sent unless it is set. Users who decline receive their codes by email instead. Terms: https://tsd-boarddocs.karpowitsch.org/terms . Privacy: https://tsd-boarddocs.karpowitsch.org/privacy .'

  curl -sS -u "$AUTH" -X POST "$API/$QE" \
    --data-urlencode "Description=One-time passcodes for sign-in to the Troy SD Archive, a public searchable archive of Troy School District Board of Education documents. Users register, are manually approved, then receive a 6-digit code by text to sign in. No marketing." \
    --data-urlencode "MessageFlow=$FLOW" \
    --data-urlencode "MessageSamples=Your Troy SD Archive sign-in code is 481920. It expires in 10 minutes." \
    --data-urlencode "MessageSamples=Your Troy SD Archive sign-in code is 736154. It expires in 10 minutes." \
    --data-urlencode "HasEmbeddedLinks=false" \
    --data-urlencode "HasEmbeddedPhone=false" \
    --data-urlencode "AgeGated=false" \
    --data-urlencode "DirectLending=false" \
    --data-urlencode "OptInKeywords=START" \
    --data-urlencode "OptInMessage=Troy SD Archive: you are opted in to sign-in codes. Msg & data rates may apply. Reply HELP for help, STOP to opt out." \
    --data-urlencode "OptOutKeywords=STOP" \
    --data-urlencode "OptOutMessage=Troy SD Archive: you are unsubscribed and will get no further texts. Your sign-in codes will be emailed instead. Reply START to resubscribe." \
    --data-urlencode "HelpKeywords=HELP" \
    --data-urlencode "HelpMessage=Troy SD Archive sign-in codes. Email admin@karpowitsch.org for help. Msg & data rates may apply. Reply STOP to opt out." \
    | python3 -m json.tool
  ;;
*)
  echo "usage: $0 [status|submit]" >&2; exit 2 ;;
esac
