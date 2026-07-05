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
      if (p === "/doc") {
        // Serve an R2 object same-origin (avoids cross-origin iframe issues).
        const key = url.searchParams.get("key");
        if (!key) return new Response("key required", { status: 400, headers: CORS });
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
