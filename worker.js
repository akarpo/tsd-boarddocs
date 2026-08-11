// tsd-boarddocs — single Cloudflare Worker (D1 full-text search, no Workers AI).
//   static site (public/)  +  JSON API (/api/{search,fetch})  +  /doc (R2)  +  /mcp
// Bindings (wrangler.toml): DB (D1 FTS5 index), MEDIA (R2 bucket), ASSETS.
// Keyword/BM25 search over document text + titles — free tier, no neuron cap.

import { BD_BASE, BD_BY_DATENAME, BD_BY_NAME } from "./bd_links.js";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,mcp-session-id,mcp-protocol-version,authorization",
};
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", ...CORS } });

// Board/education acronym <-> expansion synonyms, expanded bidirectionally at query time.
const ACRONYMS = {
  rif: ["reduction in force"],
  fte: ["full time equivalent"],
  iep: ["individualized education program"],
  isd: ["intermediate school district"],
  gsrp: ["great start readiness program"],
  mtss: ["multi tiered system of supports"],
  boe: ["board of education"],
  rfp: ["request for proposal", "request for proposals"],
  mou: ["memorandum of understanding"],
  cte: ["career and technical education"],
  sped: ["special education"],
  sel: ["social emotional learning"],
  ell: ["english language learner", "english language learners"],
  pd: ["professional development"],
};

// Build a safe FTS5 MATCH string: quote each word token, OR-join (BM25 ranks the rest).
// A quoted multi-word expansion (e.g. "reduction in force") becomes an FTS phrase match.
function ftsQuery(q) {
  const raw = String(q || "").toLowerCase();
  const toks = (raw.match(/[\p{L}\p{N}]+/gu) || []).filter((t) => t.length > 1);
  if (!toks.length) return "";
  const terms = new Set(toks.map((t) => `"${t.replace(/"/g, "")}"`));
  toks.forEach((t) => { if (ACRONYMS[t]) ACRONYMS[t].forEach((e) => terms.add(`"${e}"`)); });
  for (const [acr, exps] of Object.entries(ACRONYMS)) if (exps.some((e) => raw.includes(e))) terms.add(`"${acr}"`);
  return [...terms].join(" OR ");
}

// Document-type taxonomy from the title (first match wins; "Other" = none matched).
const DOC_TYPES = {
  Resolution:   ["Resolution"],
  Financial:    ["Check Register", "ACH Report", "Treasurer", "P Card", "P-Card", "Financial Statement", "Wire Transfer", "Wires Transfer", "Disburse", "Warrant"],
  Budget:       ["Budget"],
  Policy:       ["Policy", "Policies", "Bylaw"],
  Contract:     ["Contract", "Agreement"],
  Presentation: ["Presentation"],
};
const DOC_TYPE_KEYS = Object.keys(DOC_TYPES);
const DOC_TYPE_ALL = Object.values(DOC_TYPES).flat();
function classifyDocType(title) {
  const t = String(title || "").toLowerCase();
  for (const type of DOC_TYPE_KEYS) if (DOC_TYPES[type].some((k) => t.includes(k.toLowerCase()))) return type;
  return "Other";
}
function docTypeCond(doctype) {
  if (!doctype) return null;
  if (doctype === "Other")
    return { sql: "NOT (" + DOC_TYPE_ALL.map(() => "title LIKE ?").join(" OR ") + ")", binds: DOC_TYPE_ALL.map((k) => `%${k}%`) };
  const kw = DOC_TYPES[doctype];
  return kw ? { sql: "(" + kw.map(() => "title LIKE ?").join(" OR ") + ")", binds: kw.map((k) => `%${k}%`) } : null;
}
// Deep-link a result to its BoardDocs meeting (date+file, name fallback).
function bdLink(r) {
  const mu = BD_BY_DATENAME[`${r.meeting_date}|${r.file}`] || BD_BY_NAME[r.file];
  return mu ? BD_BASE + mu : null;
}

const COLS = "id,url,title,meeting_date,meeting_name,meeting_type,agenda_item,file";
function buildConds(match, opts) {
  const conds = ["chunks MATCH ?"];
  const binds = [match];
  const types = (opts.types || []).filter(Boolean);
  if (types.length) { conds.push(`meeting_type IN (${types.map(() => "?").join(",")})`); binds.push(...types); }
  const years = (opts.years || []).filter(Boolean);
  if (years.length) { conds.push(`substr(meeting_date,1,4) IN (${years.map(() => "?").join(",")})`); binds.push(...years); }
  const exclude = (opts.exclude || []).filter(Boolean);
  if (exclude.length) { conds.push(`meeting_type NOT IN (${exclude.map(() => "?").join(",")})`); binds.push(...exclude); }
  const dt = docTypeCond(opts.doctype);
  if (dt) { conds.push(dt.sql); binds.push(...dt.binds); }
  return { where: conds.join(" AND "), binds };
}

async function searchCore(env, query, k = 8, opts = {}) {
  const match = ftsQuery(query);
  if (!match) return [];
  const topK = Math.max(1, Math.min(k || 8, 40));
  const { where, binds } = buildConds(match, opts);
  const sort = opts.sort === "newest" ? "newest" : opts.sort === "oldest" ? "oldest" : "relevance";
  let rows = [];
  if (sort === "relevance") {
    const sql = `SELECT ${COLS}, snippet(chunks,3,'','','…',18) AS snippet, bm25(chunks) AS score FROM chunks WHERE ${where} ORDER BY rank LIMIT ?`;
    const { results } = await env.DB.prepare(sql).bind(...binds, topK * 5).all();
    const seen = new Set();
    for (const r of (results || [])) {
      if (seen.has(r.url)) continue;
      seen.add(r.url); rows.push({ ...r, snippet: String(r.snippet || "") });
      if (rows.length >= topK) break;
    }
  } else {
    // Date sort: snippet() can't be used with GROUP BY, so pick the k docs by date first, then fetch snippets.
    const dir = sort === "newest" ? "DESC" : "ASC";
    const q1 = `SELECT url, max(meeting_date) AS md FROM chunks WHERE ${where} GROUP BY url ORDER BY md ${dir} LIMIT ?`;
    const { results: u } = await env.DB.prepare(q1).bind(...binds, topK).all();
    const urls = (u || []).map((r) => r.url);
    if (urls.length) {
      const ph = urls.map(() => "?").join(",");
      const q2 = `SELECT ${COLS}, snippet(chunks,3,'','','…',18) AS snippet, bm25(chunks) AS score FROM chunks WHERE ${where} AND url IN (${ph}) ORDER BY rank`;
      const { results: d } = await env.DB.prepare(q2).bind(...binds, ...urls).all();
      const byUrl = {};
      for (const r of (d || [])) if (!byUrl[r.url]) byUrl[r.url] = { ...r, snippet: String(r.snippet || "") };
      rows = urls.map((x) => byUrl[x]).filter(Boolean);
    }
  }
  rows.forEach((r) => { r.doc_type = classifyDocType(r.title); r.boarddocs_url = bdLink(r); });
  // attach each doc's paragraph summary (if generated) for the result card
  const urls = [...new Set(rows.map((r) => r.url))];
  if (urls.length) {
    const ph = urls.map(() => "?").join(",");
    const { results: sums } = await env.DB.prepare(`SELECT url,paragraph FROM summaries WHERE url IN (${ph})`).bind(...urls).all();
    const map = Object.fromEntries((sums || []).map((s) => [s.url, s.paragraph]));
    rows.forEach((r) => { if (map[r.url]) r.summary = map[r.url]; });
  }
  return rows;
}

async function fetchCore(env, id) {
  return (await env.DB.prepare(
    "SELECT id,url,title,meeting_date,meeting_name,meeting_type,agenda_item,file,text FROM chunks WHERE id=?1"
  ).bind(id).first()) || null;
}

// ---------- remote MCP (Streamable HTTP, stateless JSON-RPC 2.0) ----------
const MCP_PROTOCOL = "2025-06-18";
const TOOLS = [
  {
    name: "search",
    description:
      "Search public Troy School District (Michigan) Board of Education documents (BoardDocs). " +
      "Returns ranked passages with id, title, meeting date/type, agenda item, source url, and a snippet. " +
      "Call fetch(id) for the full text of any result.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string" },
        k: { type: "number", description: "results (default 8, max 40)" },
        meeting_type: { type: "string", description: "optional filter: Regular, Workshop, or Special (Special = all other meeting types); omit for all" },
        years: { type: "string", description: "optional filter: comma-separated years, e.g. 2025,2026 (omit for all years)" },
        doc_type: { type: "string", description: "optional filter: Resolution, Financial, Budget, Policy, Contract, Presentation, or Other" },
        sort: { type: "string", description: "optional: relevance (default), newest, or oldest" },
      },
      required: ["query"],
    },
  },
  {
    name: "fetch",
    description: "Fetch the full text of a Troy SD BoardDocs passage by the id returned from search.",
    inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"] },
  },
];

async function callTool(env, name, args) {
  if (name === "search") {
    const mt = args.meeting_type ? String(args.meeting_type) : "";
    const types = mt && mt !== "Special" ? [mt] : [];
    const exclude = mt === "Special" ? ["Regular", "Workshop"] : [];
    const years = args.years ? String(args.years).split(",").map((s) => s.trim()).filter(Boolean) : [];
    const doctype = args.doc_type ? String(args.doc_type) : "";
    const sort = args.sort ? String(args.sort) : "";
    const rows = await searchCore(env, String(args.query || ""), Number(args.k) || 8, { types, years, exclude, doctype, sort });
    const text = rows.length
      ? rows.map((r, i) => `[${i + 1}] id=${r.id}\n${r.title} — ${r.meeting_type || ""} ${r.meeting_date || ""}${r.agenda_item ? ` Item ${r.agenda_item}` : ""}\n${r.url}\n${r.snippet}`).join("\n\n")
      : `No results for "${args.query}".`;
    return { content: [{ type: "text", text }], structuredContent: { results: rows } };
  }
  if (name === "fetch") {
    const doc = await fetchCore(env, String(args.id || ""));
    const text = doc ? `${doc.title} — ${doc.meeting_date}\n${doc.url}\n\n${doc.text}` : `No document for id ${args.id}.`;
    return { content: [{ type: "text", text }], structuredContent: doc || {} };
  }
  throw new Error(`unknown tool: ${name}`);
}

async function handleMcp(request, env) {
  if (request.method === "GET") return new Response("Method Not Allowed", { status: 405, headers: CORS });
  let msg;
  try { msg = await request.json(); } catch { return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }); }
  const { id, method, params } = msg || {};
  switch (method) {
    case "initialize":
      return json({ jsonrpc: "2.0", id, result: { protocolVersion: (params && params.protocolVersion) || MCP_PROTOCOL, capabilities: { tools: {} }, serverInfo: { name: "tsd-boarddocs", version: "2.0.0" } } });
    case "notifications/initialized":
    case "notifications/cancelled":
      return new Response(null, { status: 202, headers: CORS });
    case "ping":
      return json({ jsonrpc: "2.0", id, result: {} });
    case "tools/list":
      return json({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
    case "tools/call": {
      const name = params && params.name;
      const args = (params && params.arguments) || {};
      try { return json({ jsonrpc: "2.0", id, result: await callTool(env, name, args) }); }
      catch (e) { return json({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true } }); }
    }
    default:
      return json({ jsonrpc: "2.0", id: id ?? null, error: { code: -32601, message: `Method not found: ${method}` } });
  }
}

// ---------- assistant: registration-gated public Q&A, answered by a Claude Code
// runner polling from the owner's machine (outbound only — no tunnel). Tables:
// bot_users (status pending/approved/denied), bot_sessions, bot_questions,
// bot_config (admin_key / agent_key). See assistant/README.md.
const enc = new TextEncoder();
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const nowIso = () => new Date().toISOString();
async function pbkdf2(pw, saltHex) {
  const key = await crypto.subtle.importKey("raw", enc.encode(pw), "PBKDF2", false, ["deriveBits"]);
  const salt = new Uint8Array(saltHex.match(/../g).map((h) => parseInt(h, 16)));
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: 100000 }, key, 256);
  return hex(bits);
}
function safeEq(a, b) {
  a = String(a || ""); b = String(b || "");
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
let _cfg = null, _cfgAt = 0;
async function botCfg(env) {
  if (!_cfg || Date.now() - _cfgAt > 60000) {          // 60s TTL so new config lands without a redeploy
    const { results } = await env.DB.prepare("SELECT k, v FROM bot_config").all();
    _cfg = Object.fromEntries((results || []).map((r) => [r.k, r.v]));
    _cfgAt = Date.now();
  }
  return _cfg;
}
// ---------- Cloudflare Turnstile ----------
// Guards the two public, unauthenticated forms: /register and /otp/start. The rate limits and
// this solve different halves of the same problem -- the challenge stops scripted abuse, the
// per-number cooldown stops one person hammering "text me a code", and the cooldown is what caps
// the SMS bill. Neither replaces the other.
//
// FAILS CLOSED. If turnstile_sitekey is configured but turnstile_secret is missing, the endpoint
// refuses rather than quietly accepting unverified submissions -- a guard that silently disables
// itself is worse than none, because the logs look identical to a working one. If neither is
// configured the challenge is simply not enabled yet and the forms work as before.
const TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

function turnstileEnabled(cfg) { return !!cfg.turnstile_sitekey; }

async function verifyTurnstile(cfg, token, ip) {
  if (!turnstileEnabled(cfg)) return { ok: true, skipped: true };
  if (!cfg.turnstile_secret) {
    console.error("[turnstile] sitekey set but turnstile_secret missing — refusing the submission");
    return { ok: false, status: 503, message: "This form isn't fully configured yet. Please try again later." };
  }
  if (!token) return { ok: false, status: 400, message: "Please complete the human check." };

  const form = new URLSearchParams({ secret: cfg.turnstile_secret, response: token });
  if (ip) form.set("remoteip", ip);
  try {
    const r = await fetch(TURNSTILE_VERIFY, { method: "POST", body: form });
    const d = await r.json();
    if (d.success) return { ok: true };
    console.warn("[turnstile] rejected:", d["error-codes"]);
    return { ok: false, status: 400, message: "That human check didn't pass — please try again." };
  } catch (e) {
    // Cloudflare unreachable. Fail closed: this endpoint can send SMS and create accounts.
    console.error("[turnstile] verify call failed:", e.message);
    return { ok: false, status: 503, message: "Couldn't complete the human check. Please try again." };
  }
}

function twilioReady(cfg) {
  return !!(cfg.twilio_sid && cfg.twilio_token && cfg.twilio_from && cfg.twilio_to);
}
async function twilioSend(cfg, body, to) {
  const r = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${cfg.twilio_sid}/Messages.json`, {
    method: "POST",
    headers: { authorization: "Basic " + btoa(`${cfg.twilio_sid}:${cfg.twilio_token}`),
               "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ To: to || cfg.twilio_to, From: cfg.twilio_from, Body: body }),
  });
  if (!r.ok) throw new Error(`twilio ${r.status}: ${(await r.text()).slice(0, 200)}`);
}
async function sha256hex(s) {
  return hex(await crypto.subtle.digest("SHA-256", enc.encode(s)));
}
// ----- Microsoft Graph mailer (send-only as mail_from, e.g. admin@karpowitsch.org).
// Mirrors the FoxHall pattern: client-credentials + Mail.Send application permission.
// Config rows in bot_config: graph_tenant_id, graph_client_id, graph_client_secret, mail_from.
function emailReady(cfg) {
  return !!(cfg.mail_from && (cfg.resend_api_key ||
    (cfg.graph_tenant_id && cfg.graph_client_id && cfg.graph_client_secret)));
}
async function resendSend(cfg, to, subject, text) {
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${cfg.resend_api_key}`, "content-type": "application/json" },
    body: JSON.stringify({ from: `Troy SD Archive <${cfg.mail_from}>`, to: [to], subject, text }),
  });
  if (!r.ok) throw new Error(`resend ${r.status}: ${(await r.text()).slice(0, 200)}`);
}
async function sendEmail(cfg, to, subject, text) {
  if (cfg.resend_api_key) return resendSend(cfg, to, subject, text);
  return graphSendMail(cfg, to, subject, text);
}
let _gTok = null, _gTokExp = 0;
async function graphToken(cfg) {
  if (_gTok && Date.now() < _gTokExp) return _gTok;
  const r = await fetch(`https://login.microsoftonline.com/${cfg.graph_tenant_id}/oauth2/v2.0/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "client_credentials", client_id: cfg.graph_client_id,
      client_secret: cfg.graph_client_secret, scope: "https://graph.microsoft.com/.default" }),
  });
  if (!r.ok) throw new Error(`graph token ${r.status}`);
  const d = await r.json();
  _gTok = d.access_token; _gTokExp = Date.now() + Math.max(60, (d.expires_in || 3600) - 300) * 1000;
  return _gTok;
}
async function graphSendMail(cfg, to, subject, text) {
  const tok = await graphToken(cfg);
  const r = await fetch(
    `https://graph.microsoft.com/v1.0/users/${encodeURIComponent(cfg.mail_from)}/sendMail`, {
      method: "POST",
      headers: { authorization: `Bearer ${tok}`, "content-type": "application/json" },
      body: JSON.stringify({ message: {
        subject, body: { contentType: "Text", content: text },
        toRecipients: [{ emailAddress: { address: to } }],
      }, saveToSentItems: false }),
    });
  if (!r.ok && r.status !== 202) throw new Error(`graph send ${r.status}: ${(await r.text()).slice(0, 200)}`);
}
function normPhone(raw) {
  const digits = String(raw || "").replace(/\D/g, "");
  if (digits.length < 10 || digits.length > 15) return null;
  return "+" + (digits.length === 10 ? "1" + digits : digits);
}
async function twilioSigValid(cfg, url, params) {
  // X-Twilio-Signature = Base64(HMAC-SHA1(auth_token, url + concat(sorted k+v)))
  let data = url;
  for (const k of [...params.keys()].sort()) data += k + params.get(k);
  const key = await crypto.subtle.importKey("raw", enc.encode(cfg.twilio_token),
    { name: "HMAC", hash: "SHA-1" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(data));
  return btoa(String.fromCharCode(...new Uint8Array(mac)));
}
function cookieToken(request) {
  const m = /(?:^|;\s*)tsd_sess=([A-Za-z0-9-]+)/.exec(request.headers.get("cookie") || "");
  return m ? m[1] : null;
}
async function sessionUser(request, env) {
  const tok = cookieToken(request);
  if (!tok) return null;
  return await env.DB.prepare(
    "SELECT u.id, u.email, u.name, u.status FROM bot_sessions s JOIN bot_users u ON u.id=s.user_id WHERE s.token=?1"
  ).bind(tok).first();
}
const QUESTION_MAX = 600, OPEN_CAP = 2, DAILY_CAP = 10;
const ADMIN_SESSION_HOURS = 12;
const RELAY_TIMEOUT_MS = 5000;   // Twilio abandons a webhook at ~10s; stay well inside it

// ---------- inbound SMS routing ----------
// One number, one webhook, several projects. See schema/0013_sms_routes.sql for the matching
// rules. Returns the first enabled route that matches, or null.
async function pickSmsRoute(env, cfg, { to, from, body }) {
  const { results } = await env.DB.prepare(
    "SELECT * FROM sms_routes WHERE enabled=1 ORDER BY priority, id").all();
  const text = String(body || "").trim();
  for (const r of results || []) {
    if (r.to_number && r.to_number !== to) continue;
    if (r.from_number) {
      const want = r.from_number === "$owner" ? cfg.twilio_to : r.from_number;
      if (!want || want !== from) continue;
    }
    if (r.pattern) {
      // A bad pattern must not take the webhook down for every other project, so a route that
      // will not compile is skipped and logged rather than thrown.
      let re;
      try { re = new RegExp(r.pattern, "i"); }
      catch (e) { console.error(`[sms] route ${r.id} bad pattern: ${e.message}`); continue; }
      if (!re.test(text)) continue;
    }
    return r;
  }
  return null;
}

// Every inbound message is recorded, whichever way it was disposed of: handled here, relayed to
// a peer, or claimed by nobody. Best-effort by construction -- a logging failure must never turn
// a working reply into a 500, so this swallows its own errors.
//
// `from_number` is stored in full. tsdfeedback-2026 hashes the sender in its own copy, and that
// is the right call for a store whose subjects are survey respondents; here the admin panel
// already lists registrants' numbers, the panel is behind 2FA and single-user, and an inbound
// log whose sender you cannot read does not answer the question you open it to ask.
async function logSmsInbound(env, row) {
  try {
    await env.DB.prepare(
      "INSERT INTO sms_inbound (received_at,from_number,to_number,body,message_sid,route_id,project,disposition,reply)" +
      " VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)"
    ).bind(nowIso(), row.from || null, row.to || null, String(row.body || "").slice(0, 1600),
           row.message_sid || null, row.route_id || null, row.project || null,
           row.disposition, row.reply || null).run();
  } catch (e) { console.error("[sms] log failed:", e.message); }
}

// The tsd-boarddocs command grammar, lifted out of the request handler so that every branch
// returns a string instead of a Response. That is what lets the caller log the reply it is about
// to send -- previously each branch returned TwiML directly and there was no single point where
// the outcome was known.
async function ownerCommandReply(env, bodyTxt) {
  // ----- registration approvals: "1" approve / "2" decline, optional id -----
  // Digits rather than words on purpose. YES, START and UNSTOP are reserved carrier opt-in
  // keywords on US long codes: a bare "YES" is intercepted upstream and the TwiML reply never
  // reaches the handset, even though the webhook fires and looks healthy in the logs.
  const reg = /^([12])\s*#?\s*(\d+)?$/.exec(bodyTxt);
  if (reg) {
    const approveReg = reg[1] === "1";
    let uid = reg[2] ? Number(reg[2]) : null;
    if (uid === null) {
      const { results } = await env.DB.prepare(
        "SELECT id,email FROM bot_users WHERE status='pending' ORDER BY id").all();
      const pend = results || [];
      // Never guess which one when several are waiting. A bare "1" is convenient exactly
      // because there is usually one applicant; guessing wrong hands archive access to
      // somebody who was never vetted, which is not a recoverable mistake by text message.
      if (!pend.length) return "No registrations are pending.";
      if (pend.length > 1)
        return `${pend.length} pending: ` + pend.map((u) => `#${u.id} ${u.email}`).join(", ") +
          `. Reply "1 ${pend[0].id}" or "2 ${pend[0].id}".`;
      uid = pend[0].id;
    }
    const ru = await env.DB.prepare("SELECT id,email,status FROM bot_users WHERE id=?1").bind(uid).first();
    if (!ru) return `No registration #${uid}.`;
    if (ru.status !== "pending") return `#${uid} ${ru.email} is already ${ru.status}.`;
    const decision = approveReg ? "approved" : "denied";
    await env.DB.prepare("UPDATE bot_users SET status=?1, decided_at=?2 WHERE id=?3")
      .bind(decision, nowIso(), uid).run();
    // Mirrors /admin/decide: a denial must not leave a live session behind.
    if (!approveReg) await env.DB.prepare("DELETE FROM bot_sessions WHERE user_id=?1").bind(uid).run();
    return `#${uid} ${ru.email} ${decision}.`;
  }

  const m = /^\s*(yes|no|y|n)\s*#?\s*(\d+)/i.exec(bodyTxt);
  if (!m) return 'Reply "1"/"2" to approve or decline a registration, or "YES <id>"/"NO <id>" for a question.';
  const approve = m[1].toLowerCase().startsWith("y"), qid = Number(m[2]);
  const row = await env.DB.prepare("SELECT id,status FROM bot_questions WHERE id=?1").bind(qid).first();
  if (!row) return `No question #${qid}.`;
  if (row.status !== "awaiting_approval") return `#${qid} is already ${row.status}.`;
  await env.DB.prepare("UPDATE bot_questions SET status=?1, error=?2 WHERE id=?3")
    .bind(approve ? "pending" : "declined", approve ? null : "declined by the moderator", qid).run();
  return approve ? `#${qid} approved — answering now.` : `#${qid} declined.`;
}

// Relay a message to the project that owns it. The peer proves it holds the same secret by
// verifying our signature; we prove nothing about the peer beyond TLS, which is why the secret
// is per-route rather than shared account-wide.
//
// Signature is over `timestamp + "." + body` so a captured POST cannot be replayed later.
async function relayToProject(route, payload) {
  const bodyText = JSON.stringify(payload);
  const ts = Math.floor(Date.now() / 1000).toString();
  const key = await crypto.subtle.importKey("raw", enc.encode(route.secret || ""),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`${ts}.${bodyText}`));
  const sig = hex(new Uint8Array(mac));

  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), RELAY_TIMEOUT_MS);
  try {
    const r = await fetch(route.endpoint, {
      method: "POST", signal: ctl.signal,
      headers: {
        "content-type": "application/json",
        "x-sms-relay-project": route.project,
        "x-sms-relay-timestamp": ts,
        "x-sms-relay-signature": `sha256=${sig}`,
      },
      body: bodyText,
    });
    const txt = (await r.text()).slice(0, 2000);
    if (!r.ok) {
      console.error(`[sms] relay ${route.project} -> ${r.status}: ${txt.slice(0, 200)}`);
      return { ok: false, status: r.status };
    }
    let d = {};
    try { d = txt ? JSON.parse(txt) : {}; } catch { /* a peer may legitimately reply empty */ }
    return { ok: true, reply: typeof d.reply === "string" ? d.reply : "" };
  } catch (e) {
    console.error(`[sms] relay ${route.project} failed: ${e.name === "AbortError" ? "timeout" : e.message}`);
    return { ok: false, status: 0 };
  } finally { clearTimeout(timer); }
}

// Admin sessions are checked against the table on every request rather than being self-signed,
// so /admin/logout and an expiry sweep can actually revoke one. Expired rows are deleted on
// sight: leaving them would let a clock change resurrect a session that has already lapsed.
async function adminSessionValid(request, env) {
  const tok = request.headers.get("x-admin-session") || "";
  if (!tok) return false;
  const row = await env.DB.prepare("SELECT token,expires FROM admin_sessions WHERE token=?1").bind(tok).first();
  if (!row) return false;
  if (Date.parse(row.expires || 0) < Date.now()) {
    await env.DB.prepare("DELETE FROM admin_sessions WHERE token=?1").bind(tok).run().catch(() => {});
    return false;
  }
  return true;
}

async function handleAssistant(request, env, url) {
  const p = url.pathname.slice("/api/assistant".length);
  const method = request.method;
  // Twilio posts form-encoded and its handler reads the raw body itself — a body can only be read once
  const body = (method === "POST" && p !== "/twilio/inbound")
    ? await request.json().catch(() => ({})) : {};

  if (p === "/register" && method === "POST") {
    const email = String(body.email || "").trim().toLowerCase();
    const name = String(body.name || "").trim().slice(0, 80);
    const reason = String(body.reason || "").trim().slice(0, 400);
    const phone = normPhone(body.phone);
    // Express SMS consent from the checkbox on /ask. Recorded with its timestamp because consent
    // without a date is not evidence, and the A2P campaign stands or falls on being able to show
    // it. 0 (declined) and NULL (never asked) are deliberately different.
    const smsConsent = body.sms_consent === 1 || body.sms_consent === true ? 1 : 0;

    const tsR = await verifyTurnstile(await botCfg(env), body.turnstile_token, request.headers.get("cf-connecting-ip"));
    if (!tsR.ok) return json({ error: tsR.message }, tsR.status);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json({ error: "valid email required" }, 400);
    if (!phone) return json({ error: "valid mobile number required" }, 400);
    let rid;
    try {
      const ins = await env.DB.prepare(
        "INSERT INTO bot_users (email,name,reason,phone,pw_hash,pw_salt,status,created_at,sms_consent,sms_consent_at) VALUES (?1,?2,?3,?4,'','','pending',?5,?6,?7)"
      ).bind(email, name, reason, phone, nowIso(), smsConsent, smsConsent === 1 ? nowIso() : null).run();
      rid = ins.meta.last_row_id;
    } catch { return json({ error: "that email or phone number is already registered" }, 409); }

    // Text the owner so approving someone does not require opening the admin panel. Registration
    // itself sends the applicant nothing -- their first message is the sign-in code, and only
    // after approval, because /otp/start refuses anyone who is not 'approved'.
    //
    // Best-effort: the row is already committed, so a failed notification must not turn a
    // successful registration into an error the applicant sees. /admin/users still lists them.
    const cfgR = await botCfg(env);
    if (twilioReady(cfgR)) {
      try {
        await twilioSend(cfgR,
          `TSD Archive registration #${rid}\n${name || "(no name given)"} <${email}>\n${phone}` +
          (reason ? `\n"${reason.slice(0, 120)}"` : "") +
          `\n\nReply 1 to approve or 2 to decline.`);
      } catch { /* admin panel remains the fallback */ }
    }
    return json({ ok: true, status: "pending" });
  }

  // passwordless sign-in: a 6-digit code texted to the registered (and approved) phone
  if (p === "/otp/start" && method === "POST") {
    const phone = normPhone(body.phone);
    if (!phone) return json({ error: "valid mobile number required" }, 400);
    const cfgO = await botCfg(env);
    // channel ladder: SMS once Twilio's campaign is armed; email via Graph meanwhile
    if (!twilioReady(cfgO) && !emailReady(cfgO))
      return json({ error: "sign-in isn't open yet — check back soon" }, 503);
    const tsO = await verifyTurnstile(await botCfg(env), body.turnstile_token, request.headers.get("cf-connecting-ip"));
    if (!tsO.ok) return json({ error: tsO.message }, tsO.status);

    const u = await env.DB.prepare("SELECT * FROM bot_users WHERE phone=?1").bind(phone).first();
    // don't leak which numbers exist: unknown/unapproved get the same neutral reply
    if (!u || u.status !== "approved") return json({ ok: true, sent: true });
    if (u.otp_sent_at && Date.now() - Date.parse(u.otp_sent_at) < 60e3)
      return json({ error: "code already sent — wait a minute before retrying" }, 429);
    const code = String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, "0");
    await env.DB.prepare(
      "UPDATE bot_users SET otp_hash=?1, otp_expires=?2, otp_sent_at=?3, otp_attempts=0 WHERE id=?4")
      .bind(await sha256hex(code + phone), new Date(Date.now() + 600e3).toISOString(), nowIso(), u.id).run();
    const msg = `Your Troy SD Archive sign-in code is ${code}. It expires in 10 minutes.`;
    let channel = null;
    // THREE things must be true to text: a configured transport, and EXPRESS CONSENT from this
    // user. A number in the database is not permission to use it -- texting without opt-in
    // revokes the 10DLC campaign and is a per-message TCPA liability. Users who registered
    // before the consent checkbox existed have sms_consent NULL and are emailed instead, which
    // is the correct default: they were never asked.
    if (twilioReady(cfgO) && u.sms_consent === 1) {
      try { await twilioSend(cfgO, msg, phone); channel = "sms"; }
      catch (e) {
        // 21610 = the user replied STOP. Twilio enforces that at the carrier and will reject
        // every later send; nothing tells us otherwise, so record the revocation here or we
        // retry SMS forever and they silently lose access.
        if (String(e && e.message || "").includes("21610")) {
          await env.DB.prepare("UPDATE bot_users SET sms_consent=0, sms_consent_at=?1 WHERE id=?2")
            .bind(nowIso(), u.id).run().catch(() => {});
        }
        /* fall through to email */
      }
    }
    if (!channel && emailReady(cfgO)) {
      try {
        await sendEmail(cfgO, u.email, "Your Troy SD Archive sign-in code", msg +
          "\n\nIf you didn't request this, you can ignore it.\n— tsd-boarddocs.karpowitsch.org");
        channel = "email";
      } catch { /* both failed */ }
    }
    if (!channel) return json({ error: "could not send the code — try again later" }, 502);
    return json({ ok: true, sent: true, channel });
  }

  if (p === "/otp/verify" && method === "POST") {
    const phone = normPhone(body.phone);
    const code = String(body.code || "").replace(/\D/g, "");
    if (!phone || code.length !== 6) return json({ error: "enter the 6-digit code" }, 400);
    const u = await env.DB.prepare("SELECT * FROM bot_users WHERE phone=?1").bind(phone).first();
    if (!u || u.status !== "approved" || !u.otp_hash) return json({ error: "wrong code" }, 401);
    if (Date.parse(u.otp_expires || 0) < Date.now()) return json({ error: "code expired — request a new one" }, 401);
    if ((u.otp_attempts || 0) >= 5) return json({ error: "too many attempts — request a new code" }, 429);
    if (!safeEq(await sha256hex(code + phone), u.otp_hash)) {
      await env.DB.prepare("UPDATE bot_users SET otp_attempts=otp_attempts+1 WHERE id=?1").bind(u.id).run();
      return json({ error: "wrong code" }, 401);
    }
    await env.DB.prepare("UPDATE bot_users SET otp_hash=NULL, otp_expires=NULL WHERE id=?1").bind(u.id).run();
    const tok = crypto.randomUUID() + "-" + crypto.randomUUID();
    await env.DB.prepare("INSERT INTO bot_sessions (token,user_id,created_at) VALUES (?1,?2,?3)")
      .bind(tok, u.id, nowIso()).run();
    return new Response(JSON.stringify({ ok: true, status: "approved", email: u.email }), {
      headers: { "content-type": "application/json",
        "set-cookie": `tsd_sess=${tok}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`, ...CORS } });
  }

  if (p === "/logout" && method === "POST") {
    const tok = cookieToken(request);
    if (tok) await env.DB.prepare("DELETE FROM bot_sessions WHERE token=?1").bind(tok).run();
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "content-type": "application/json",
        "set-cookie": "tsd_sess=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0", ...CORS } });
  }

  if (p === "/me") {
    const u = await sessionUser(request, env);
    // The sitekey is public by design -- it is rendered into the page. Served here rather than
    // hardcoded so rotating the widget needs no redeploy.
    const c = await botCfg(env);
    return json({ ...(u ? { email: u.email, name: u.name, status: u.status } : {}),
                  turnstile_sitekey: c.turnstile_sitekey || null });
  }

  if (p === "/ask" && method === "POST") {
    const u = await sessionUser(request, env);
    if (!u || u.status !== "approved") return json({ error: "not authorized" }, 401);
    const q = String(body.question || "").trim();
    if (q.length < 5) return json({ error: "ask a real question" }, 400);
    if (q.length > QUESTION_MAX) return json({ error: `keep it under ${QUESTION_MAX} characters` }, 400);
    const open = await env.DB.prepare(
      "SELECT count(*) c FROM bot_questions WHERE user_id=?1 AND status IN ('pending','answering')").bind(u.id).first();
    if (open.c >= OPEN_CAP) return json({ error: "wait for your open questions to finish" }, 429);
    const today = await env.DB.prepare(
      "SELECT count(*) c FROM bot_questions WHERE user_id=?1 AND asked_at > ?2")
      .bind(u.id, new Date(Date.now() - 86400e3).toISOString()).first();
    if (today.c >= DAILY_CAP) return json({ error: `daily limit of ${DAILY_CAP} questions reached` }, 429);
    const cfgA = await botCfg(env);
    const moderate = twilioReady(cfgA);
    const r = await env.DB.prepare(
      "INSERT INTO bot_questions (user_id,question,status,asked_at) VALUES (?1,?2,?3,?4)")
      .bind(u.id, q, moderate ? "awaiting_approval" : "pending", nowIso()).run();
    const qid = r.meta.last_row_id;
    if (moderate) {
      try {
        await twilioSend(cfgA,
          `TSD Q&A #${qid} from ${u.email}:\n"${q.slice(0, 320)}"\n\nReply YES ${qid} to approve or NO ${qid} to decline.`);
      } catch (e) {
        // SMS failure must not strand the question — degrade to unmoderated
        await env.DB.prepare("UPDATE bot_questions SET status='pending' WHERE id=?1").bind(qid).run();
      }
    }
    return json({ ok: true, id: qid });
  }

  if (p === "/questions") {
    const u = await sessionUser(request, env);
    if (!u) return json({ error: "not authorized" }, 401);
    const { results } = await env.DB.prepare(
      "SELECT id,question,status,answer,error,asked_at,answered_at FROM bot_questions WHERE user_id=?1 ORDER BY id DESC LIMIT 30"
    ).bind(u.id).all();
    return json({ questions: results || [] });
  }

  // ----- Twilio inbound from the owner's phone: "1"/"2" registrations, "YES 12"/"NO 12" questions -----
  if (p === "/twilio/inbound" && method === "POST") {
    const cfgT = await botCfg(env);
    const raw = await request.text();
    const params = new URLSearchParams(raw);
    const sig = request.headers.get("x-twilio-signature") || "";
    const expected = twilioReady(cfgT) ? await twilioSigValid(cfgT, url.origin + url.pathname, params) : "";
    // Replies quote registrant emails back, which are user-controlled, so escape before they
    // reach the XML. An unescaped & or < is enough to make Twilio drop the whole response.
    const xmlEsc = (s) => String(s).replace(/[<>&'"]/g, (c) =>
      ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]));
    const twiml = (m) => new Response(
      `<?xml version="1.0" encoding="UTF-8"?><Response>${m ? `<Message>${xmlEsc(m)}</Message>` : ""}</Response>`,
      { headers: { "content-type": "text/xml" } });
    // Signature first, unconditionally. It is the only proof the request came from Twilio, and
    // it is the one check that cannot be delegated to a peer project: verifying it needs the
    // account auth token, which is exactly what we are not handing out.
    if (!expected || !safeEq(sig, expected))
      return new Response("forbidden", { status: 403 });

    const bodyTxt = (params.get("Body") || "").trim();
    const smsTo = params.get("To") || "", smsFrom = params.get("From") || "";

    // Which project owns this message? Matching is by destination number, sender, and body --
    // see schema/0013_sms_routes.sql. The old hardcoded `From === twilio_to` test now lives in
    // the seeded routes as from_number='$owner'.
    const route = await pickSmsRoute(env, cfgT, { to: smsTo, from: smsFrom, body: bodyTxt });
    const msgSid = params.get("MessageSid") || params.get("SmsMessageSid") || "";
    const logRow = { from: smsFrom, to: smsTo, body: bodyTxt, message_sid: msgSid,
                     route_id: route ? route.id : null, project: route ? route.project : null };

    // Every path below records the message before answering, so the admin panel shows what came
    // in regardless of who ended up handling it. Unrouted traffic is the case that most needs
    // recording: it is invisible everywhere else precisely because nobody claimed it.
    if (!route) {
      // Unclaimed traffic stays a 403, exactly as before routing existed. Inventing a reply for
      // a stranger's text would put an outbound message on a campaign that never described one.
      await logSmsInbound(env, { ...logRow, disposition: "unrouted" });
      return new Response("forbidden", { status: 403 });
    }

    if (route.endpoint) {
      const out = await relayToProject(route, {
        project: route.project, from: smsFrom, to: smsTo, body: bodyTxt,
        message_sid: msgSid, received_at: nowIso(),
      });
      // A peer being down must not look to the sender like their message was ignored.
      const reply = out.ok ? (out.reply || "")
                           : "Sorry — that service isn't reachable right now. Please try again shortly.";
      await logSmsInbound(env, { ...logRow, disposition: out.ok ? "relayed" : "relay_failed", reply });
      return twiml(reply);
    }

    // endpoint IS NULL -> this project's own command grammar
    const reply = await ownerCommandReply(env, bodyTxt);
    await logSmsInbound(env, { ...logRow, disposition: "local", reply });
    return twiml(reply);
  }

  // ----- admin: two-factor login (key + code texted to twilio_to) -----
  // The key alone opens nothing. It is the knowledge factor and it gates *sending* the code;
  // possession of the handset is what actually authenticates. Everything under /admin/ therefore
  // requires a session minted by completing both steps, and the browser never stores the key.
  const cfg = await botCfg(env);

  if (p === "/admin/login/start" && method === "POST") {
    // Gating the send on the key matters twice over: an unauthenticated caller could otherwise
    // bill SMS at will and ring the owner's phone at 3am, and the cooldown below would be the
    // only thing standing between the panel and a paid denial-of-sleep attack.
    if (!safeEq(String(body.key || ""), cfg.admin_key)) return json({ error: "bad admin key" }, 401);
    if (!twilioReady(cfg)) return json({ error: "SMS isn't configured — cannot send an admin code" }, 503);
    const cur = await env.DB.prepare("SELECT sent_at FROM admin_otp WHERE id=1").first();
    if (cur && cur.sent_at && Date.now() - Date.parse(cur.sent_at) < 60e3)
      return json({ error: "code already sent — wait a minute before retrying" }, 429);
    const code = String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, "0");
    await env.DB.prepare("UPDATE admin_otp SET code_hash=?1, expires=?2, sent_at=?3, attempts=0 WHERE id=1")
      .bind(await sha256hex(code + cfg.twilio_to), new Date(Date.now() + 600e3).toISOString(), nowIso()).run();
    try {
      await twilioSend(cfg, `Troy SD Archive admin sign-in code: ${code}\nExpires in 10 minutes. ` +
        `If you did not request it, your admin key is compromised.`);
    } catch { return json({ error: "could not send the code — try again later" }, 502); }
    return json({ ok: true });
  }

  if (p === "/admin/login/verify" && method === "POST") {
    if (!safeEq(String(body.key || ""), cfg.admin_key)) return json({ error: "bad admin key" }, 401);
    const code = String(body.code || "").replace(/\D/g, "");
    const row = await env.DB.prepare("SELECT code_hash,expires,attempts FROM admin_otp WHERE id=1").first();
    if (!row || !row.code_hash) return json({ error: "request a code first" }, 400);
    if (Date.parse(row.expires || 0) < Date.now()) return json({ error: "code expired — request a new one" }, 401);
    if ((row.attempts || 0) >= 5) return json({ error: "too many attempts — request a new code" }, 429);
    // Count the attempt before checking it, so a crash mid-verify cannot hand out a free guess.
    await env.DB.prepare("UPDATE admin_otp SET attempts=attempts+1 WHERE id=1").run();
    if (!safeEq(await sha256hex(code + cfg.twilio_to), row.code_hash)) return json({ error: "wrong code" }, 401);
    // One use only: a code that survives its own redemption is a password with a short life.
    await env.DB.prepare("UPDATE admin_otp SET code_hash=NULL, expires=NULL, attempts=0 WHERE id=1").run();
    const tok = crypto.randomUUID() + crypto.randomUUID().replace(/-/g, "");
    const exp = new Date(Date.now() + ADMIN_SESSION_HOURS * 3600e3).toISOString();
    await env.DB.prepare("INSERT INTO admin_sessions (token,created_at,expires) VALUES (?1,?2,?3)")
      .bind(tok, nowIso(), exp).run();
    await env.DB.prepare("DELETE FROM admin_sessions WHERE expires < ?1").bind(nowIso()).run().catch(() => {});
    return json({ ok: true, token: tok, expires: exp });
  }

  if (p === "/admin/logout" && method === "POST") {
    const t = request.headers.get("x-admin-session") || "";
    if (t) await env.DB.prepare("DELETE FROM admin_sessions WHERE token=?1").bind(t).run();
    return json({ ok: true });
  }

  const isAdmin = await adminSessionValid(request, env);
  if (p === "/admin/users" && isAdmin) {
    const { results } = await env.DB.prepare(
      "SELECT id,email,name,reason,phone,status,created_at,decided_at FROM bot_users ORDER BY (status='pending') DESC, id DESC LIMIT 200").all();
    return json({ users: results || [] });
  }
  if (p === "/admin/decide" && method === "POST" && isAdmin) {
    const decision = body.decision === "approved" ? "approved" : "denied";
    await env.DB.prepare("UPDATE bot_users SET status=?1, decided_at=?2 WHERE id=?3")
      .bind(decision, nowIso(), Number(body.id)).run();
    if (decision === "denied")
      await env.DB.prepare("DELETE FROM bot_sessions WHERE user_id=?1").bind(Number(body.id)).run();
    return json({ ok: true });
  }
  if (p === "/admin/moderate" && method === "POST" && isAdmin) {
    const approve = body.decision === "approve";
    await env.DB.prepare("UPDATE bot_questions SET status=?1, error=?2 WHERE id=?3 AND status='awaiting_approval'")
      .bind(approve ? "pending" : "declined", approve ? null : "declined by the moderator", Number(body.id)).run();
    return json({ ok: true });
  }
  if (p === "/admin/sms-inbound" && isAdmin) {
    const { results } = await env.DB.prepare(
      "SELECT id,received_at,from_number,to_number,body,project,disposition,reply" +
      "  FROM sms_inbound ORDER BY id DESC LIMIT 100").all();
    return json({ messages: results || [] });
  }

  // ----- inbound SMS routes -----
  if (p === "/admin/sms-routes" && method === "GET" && isAdmin) {
    // Never return `secret`. Report only whether one is set and its length, which is enough to
    // diagnose "we configured different secrets" without putting the value in a browser tab.
    const { results } = await env.DB.prepare(
      "SELECT id,project,to_number,from_number,pattern,endpoint,enabled,priority,note,created_at," +
      "       CASE WHEN secret IS NULL OR secret='' THEN 0 ELSE length(secret) END AS secret_len" +
      "  FROM sms_routes ORDER BY priority, id").all();
    return json({ routes: results || [] });
  }

  if (p === "/admin/sms-routes" && method === "POST" && isAdmin) {
    const b = body || {};
    if (!b.project) return json({ error: "project is required" }, 400);
    if (b.endpoint && !/^https:\/\//.test(b.endpoint))
      return json({ error: "endpoint must be https" }, 400);
    if (b.endpoint && !b.secret && !b.id)
      return json({ error: "a forwarding route needs a secret" }, 400);
    // Reject a pattern that will not compile here rather than at 2am on a live message.
    if (b.pattern) {
      try { new RegExp(b.pattern, "i"); }
      catch (e) { return json({ error: `bad pattern: ${e.message}` }, 400); }
    }
    if (b.id) {
      await env.DB.prepare(
        "UPDATE sms_routes SET project=?1,to_number=?2,from_number=?3,pattern=?4,endpoint=?5," +
        "secret=COALESCE(?6,secret),enabled=?7,priority=?8,note=?9 WHERE id=?10"
      ).bind(b.project, b.to_number || null, b.from_number || null, b.pattern || null,
             b.endpoint || null, b.secret || null, b.enabled === 0 ? 0 : 1,
             Number(b.priority) || 100, b.note || null, Number(b.id)).run();
      return json({ ok: true, id: Number(b.id) });
    }
    const r = await env.DB.prepare(
      "INSERT INTO sms_routes (project,to_number,from_number,pattern,endpoint,secret,enabled,priority,note,created_at)" +
      " VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)"
    ).bind(b.project, b.to_number || null, b.from_number || null, b.pattern || null,
           b.endpoint || null, b.secret || null, b.enabled === 0 ? 0 : 1,
           Number(b.priority) || 100, b.note || null, nowIso()).run();
    return json({ ok: true, id: r.meta.last_row_id });
  }

  if (p === "/admin/sms-routes/delete" && method === "POST" && isAdmin) {
    await env.DB.prepare("DELETE FROM sms_routes WHERE id=?1").bind(Number(body.id)).run();
    return json({ ok: true });
  }

  // Credential check: does the peer actually hold the same secret we do? Sends a signed probe
  // that carries no message, so it is safe to run any time and cannot approve or change anything.
  // A peer is expected to verify the signature and answer {"ok":true}.
  if (p === "/admin/sms-routes/check" && method === "POST" && isAdmin) {
    const { results } = await env.DB.prepare(
      "SELECT * FROM sms_routes WHERE enabled=1 AND endpoint IS NOT NULL" +
      (body && body.id ? " AND id=?1" : "")).bind(...(body && body.id ? [Number(body.id)] : [])).all();
    const out = [];
    for (const r of results || []) {
      if (!r.secret) { out.push({ id: r.id, project: r.project, ok: false, detail: "no secret stored on this side" }); continue; }
      const res = await relayToProject(r, { probe: true, project: r.project, sent_at: nowIso() });
      out.push({
        id: r.id, project: r.project, endpoint: r.endpoint,
        ok: res.ok,
        detail: res.ok ? "peer accepted the signature"
              : res.status === 401 || res.status === 403 ? "peer rejected the signature — secrets differ"
              : res.status ? `peer returned HTTP ${res.status}`
              : "unreachable or timed out",
      });
    }
    if (!out.length) return json({ checked: [], note: "no enabled forwarding routes configured" });
    return json({ checked: out });
  }

  if (p === "/admin/questions" && isAdmin) {
    const { results } = await env.DB.prepare(
      "SELECT q.id,u.email,q.question,q.status,q.answer,q.error,q.asked_at,q.tokens_used FROM bot_questions q JOIN bot_users u ON u.id=q.user_id ORDER BY q.id DESC LIMIT 50").all();
    return json({ questions: results || [] });
  }
  // Deliberately not "bad admin key" any more: the key is no longer what grants access, and a
  // message naming it sends you off checking the wrong secret when the session has simply lapsed.
  if (p.startsWith("/admin/")) return json({ error: "admin sign-in required" }, 401);

  // ----- agent (X-Agent-Key): the Claude Code runner on the owner's machine -----
  const isAgent = safeEq(request.headers.get("x-agent-key"), cfg.agent_key);
  if (p === "/agent/next" && isAgent) {
    // pending first; else retry questions stuck in 'answering' >20 min (crashed runner)
    const stale = new Date(Date.now() - 20 * 60e3).toISOString();
    const q = await env.DB.prepare(
      "SELECT id,question FROM bot_questions WHERE status='pending' OR (status='answering' AND asked_at < ?1) ORDER BY (status='pending') DESC, id LIMIT 1"
    ).bind(stale).first();
    if (!q) return json({});
    await env.DB.prepare("UPDATE bot_questions SET status='answering' WHERE id=?1").bind(q.id).run();
    return json(q);
  }
  if (p === "/agent/answer" && method === "POST" && isAgent) {
    const toks = Number(body.tokens_used) || null;
    if (body.error)
      await env.DB.prepare("UPDATE bot_questions SET status='error', error=?1, answered_at=?2, tokens_used=?3 WHERE id=?4")
        .bind(String(body.error).slice(0, 500), nowIso(), toks, Number(body.id)).run();
    else
      await env.DB.prepare("UPDATE bot_questions SET status='answered', answer=?1, answered_at=?2, tokens_used=?3 WHERE id=?4")
        .bind(String(body.answer || "").slice(0, 20000), nowIso(), toks, Number(body.id)).run();
    return json({ ok: true });
  }
  if (p.startsWith("/agent/")) return json({ error: "bad agent key" }, 401);

  return json({ error: "not found" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    try {
      if (p === "/mcp") return await handleMcp(request, env);
      if (p === "/api/search") {
        const q = (url.searchParams.get("q") || "").trim();
        const k = parseInt(url.searchParams.get("k") || "8", 10) || 8;
        if (!q) return json({ error: "q required" }, 400);
        const types = (url.searchParams.get("types") || "").split(",").map((s) => s.trim()).filter(Boolean);
        const years = (url.searchParams.get("years") || "").split(",").map((s) => s.trim()).filter(Boolean);
        const exclude = (url.searchParams.get("exclude") || "").split(",").map((s) => s.trim()).filter(Boolean);
        const doctype = (url.searchParams.get("doctype") || "").trim();
        const sort = (url.searchParams.get("sort") || "").trim();
        return json({ query: q, results: await searchCore(env, q, k, { types, years, exclude, doctype, sort }) });
      }
      if (p === "/api/fetch") {
        const fid = url.searchParams.get("id");
        if (!fid) return json({ error: "id required" }, 400);
        const doc = await fetchCore(env, fid);
        return doc ? json(doc) : json({ error: "not found" }, 404);
      }
      if (p === "/api/summary") {
        const u = url.searchParams.get("url");
        if (!u) return json({ error: "url required" }, 400);
        const s = await env.DB.prepare("SELECT url,paragraph,page,verbose FROM summaries WHERE url=?1").bind(u).first();
        return json(s || {});
      }
      if (p === "/api/meetings") {
        // Timeline: one row per meeting (newest first) with a document count.
        const { results } = await env.DB.prepare(
          "SELECT meeting_date, meeting_name, meeting_type, count(DISTINCT file) AS docs, min(file) AS samplefile " +
          "FROM chunks WHERE source!='summary' AND meeting_date!='' GROUP BY meeting_date, meeting_name ORDER BY meeting_date DESC, meeting_name"
        ).all();
        const meetings = (results || []).map((m) => ({
          date: m.meeting_date, name: m.meeting_name, type: m.meeting_type, docs: m.docs,
          boarddocs_url: bdLink({ meeting_date: m.meeting_date, file: m.samplefile }),
        }));
        return json({ meetings });
      }
      if (p === "/api/meeting") {
        const date = url.searchParams.get("date") || "", name = url.searchParams.get("name") || "";
        if (!date) return json({ error: "date required" }, 400);
        const { results } = await env.DB.prepare(
          "SELECT DISTINCT url,title,file,agenda_item,meeting_date,meeting_name,meeting_type FROM chunks " +
          "WHERE source!='summary' AND meeting_date=?1 AND meeting_name=?2 ORDER BY agenda_item, title"
        ).bind(date, name).all();
        const docs = (results || []).map((r) => ({ ...r, doc_type: classifyDocType(r.title), boarddocs_url: bdLink(r) }));
        const urls = docs.map((d) => d.url);
        if (urls.length) {
          const ph = urls.map(() => "?").join(",");
          const { results: sums } = await env.DB.prepare(`SELECT url,paragraph FROM summaries WHERE url IN (${ph})`).bind(...urls).all();
          const map = Object.fromEntries((sums || []).map((s) => [s.url, s.paragraph]));
          docs.forEach((d) => { if (map[d.url]) d.summary = map[d.url]; });
        }
        return json({ date, name, docs });
      }
      if (p === "/api/recording") {
        // Meeting recording (YouTube) + attributed transcript + agenda-item chapters.
        // Empty object when no recording has been ingested for the meeting.
        const date = url.searchParams.get("date") || "", name = url.searchParams.get("name") || "";
        if (!date) return json({ error: "date required" }, 400);
        let rec = null;
        try {
          rec = await env.DB.prepare(
            "SELECT youtube_id, duration_s FROM recordings WHERE meeting_date=?1 AND meeting_name=?2"
          ).bind(date, name).first();
        } catch { return json({}); }              // tables not created yet
        if (!rec) return json({});
        const { results: anchors } = await env.DB.prepare(
          "SELECT start_ms, label FROM transcript_anchors WHERE meeting_date=?1 AND meeting_name=?2 ORDER BY start_ms"
        ).bind(date, name).all();
        const { results: utts } = await env.DB.prepare(
          "SELECT start_ms, end_ms, speaker, text FROM transcript_utts WHERE meeting_date=?1 AND meeting_name=?2 ORDER BY idx"
        ).bind(date, name).all();
        return json({ youtube_id: rec.youtube_id, duration_s: rec.duration_s,
                      anchors: anchors || [], utterances: utts || [] });
      }
      if (p.startsWith("/api/assistant/")) return await handleAssistant(request, env, url);
      if (p === "/doc") {
        // Serve an R2 object same-origin (avoids cross-origin iframe issues).
        const key = url.searchParams.get("key");
        if (!key) return new Response("key required", { status: 400, headers: CORS });
        if (request.method === "HEAD") {
          const head = await env.MEDIA.head(key);
          return new Response(null, { status: head ? 200 : 404, headers: CORS });
        }
        const obj = await env.MEDIA.get(key);
        if (!obj) return new Response("Not found", { status: 404, headers: CORS });
        const h = new Headers();
        obj.writeHttpMetadata(h);
        h.set("cache-control", "public, max-age=3600");
        h.set("access-control-allow-origin", "*");
        return new Response(obj.body, { headers: h });
      }
    } catch (e) {
      return json({ error: String((e && e.message) || e) }, 500);
    }
    return env.ASSETS.fetch(request);
  },
};
