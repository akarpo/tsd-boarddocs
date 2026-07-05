// tsd-boarddocs — single Cloudflare Worker (D1 full-text search, no Workers AI).
//   static site (public/)  +  JSON API (/api/{search,fetch})  +  /doc (R2)  +  /mcp
// Bindings (wrangler.toml): DB (D1 FTS5 index), MEDIA (R2 bucket), ASSETS.
// Keyword/BM25 search over document text + titles — free tier, no neuron cap.

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,mcp-session-id,mcp-protocol-version,authorization",
};
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", ...CORS } });

// Build a safe FTS5 MATCH string: quote each word token, OR-join (BM25 ranks the rest).
function ftsQuery(q) {
  const toks = (String(q || "").match(/[\p{L}\p{N}]+/gu) || []).filter((t) => t.length > 1);
  return toks.map((t) => `"${t.replace(/"/g, "")}"`).join(" OR ");
}

async function searchCore(env, query, k = 8) {
  const match = ftsQuery(query);
  if (!match) return [];
  const topK = Math.max(1, Math.min(k || 8, 25));
  const sql =
    "SELECT id,url,title,meeting_date,meeting_name,meeting_type,agenda_item,file," +
    "snippet(chunks,3,'','','…',18) AS snippet, bm25(chunks) AS score " +
    "FROM chunks WHERE chunks MATCH ?1 ORDER BY rank LIMIT ?2";
  const { results } = await env.DB.prepare(sql).bind(match, topK * 5).all();
  // one row per document (best-ranked; a 'sum:' summary row wins when it matches best)
  const rows = [];
  const seen = new Set();
  for (const r of (results || [])) {
    if (seen.has(r.url)) continue;
    seen.add(r.url);
    rows.push({ ...r, snippet: String(r.snippet || "") });
    if (rows.length >= topK) break;
  }
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
      properties: { query: { type: "string" }, k: { type: "number", description: "results (default 8, max 25)" } },
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
    const rows = await searchCore(env, String(args.query || ""), Number(args.k) || 8);
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
        return json({ query: q, results: await searchCore(env, q, k) });
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
