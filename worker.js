// tsd-boarddocs — single Cloudflare Worker.
//   static site (public/)  +  JSON API (/api/{search,fetch,embed})  +  remote MCP (/mcp)
// Bindings (wrangler.toml): AI (Workers AI), VECTORIZE (index "tsd-boarddocs"), ASSETS.
// One retrieval core; the website, the WebMCP tools, and the MCP connector all use it.

const EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"; // 768-dim
// BGE is asymmetric: the retrieval instruction goes on the QUERY only, never passages.
const QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: ";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,mcp-session-id,mcp-protocol-version,authorization",
};
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", ...CORS } });

async function embedTexts(env, texts, isQuery = false) {
  const input = isQuery ? texts.map((t) => QUERY_INSTRUCTION + t) : texts;
  const out = await env.AI.run(EMBED_MODEL, { text: input });
  return out.data; // Array<number[768]>
}

async function searchCore(env, query, k = 8) {
  const topK = Math.max(1, Math.min(k || 8, 20));
  const [vec] = await embedTexts(env, [query], true);
  const res = await env.VECTORIZE.query(vec, { topK, returnMetadata: "all" });
  return (res.matches || []).map((m) => {
    const md = m.metadata || {};
    return {
      id: m.id,
      score: m.score,
      title: md.title || md.file || m.id,
      meeting_date: md.meeting_date || "",
      url: md.url || "",
      snippet: String(md.text || "").slice(0, 400),
    };
  });
}

async function fetchCore(env, id) {
  const got = await env.VECTORIZE.getByIds([id]);
  const v = got && got[0];
  if (!v) return null;
  const md = v.metadata || {};
  return { id, title: md.title || md.file || id, meeting_date: md.meeting_date || "", url: md.url || "", text: md.text || "" };
}

// ---------- remote MCP (Streamable HTTP, stateless JSON-RPC 2.0) ----------
const MCP_PROTOCOL = "2025-06-18";
const TOOLS = [
  {
    name: "search",
    description:
      "Search public Troy School District (Michigan) Board of Education documents (BoardDocs). " +
      "Returns ranked passages, each with an id, title, meeting date, source PDF url, and a snippet. " +
      "Call fetch(id) to get the full text of any result.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Natural-language question or keywords." },
        k: { type: "number", description: "Number of passages to return (default 8, max 20)." },
      },
      required: ["query"],
    },
  },
  {
    name: "fetch",
    description: "Fetch the full text of a Troy SD BoardDocs passage by the id returned from search.",
    inputSchema: {
      type: "object",
      properties: { id: { type: "string", description: "The id from a search result." } },
      required: ["id"],
    },
  },
];

async function callTool(env, name, args) {
  if (name === "search") {
    const rows = await searchCore(env, String(args.query || ""), Number(args.k) || 8);
    const text = rows.length
      ? rows.map((r, i) => `[${i + 1}] id=${r.id}\n${r.title} — ${r.meeting_date}\n${r.url}\n${r.snippet}`).join("\n\n")
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
  try {
    msg = await request.json();
  } catch {
    return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
  }
  const { id, method, params } = msg || {};
  switch (method) {
    case "initialize":
      return json({
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: (params && params.protocolVersion) || MCP_PROTOCOL,
          capabilities: { tools: {} },
          serverInfo: { name: "tsd-boarddocs", version: "1.0.0" },
        },
      });
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
      try {
        return json({ jsonrpc: "2.0", id, result: await callTool(env, name, args) });
      } catch (e) {
        return json({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true } });
      }
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
      if (p === "/api/embed" && request.method === "POST") {
        let body;
        try { body = await request.json(); } catch { return json({ error: "invalid JSON" }, 400); }
        const texts = body && body.texts;
        if (!Array.isArray(texts) || !texts.length) return json({ error: "texts[] required" }, 400);
        if (texts.length > 100) return json({ error: "max 100 texts per call" }, 400);
        return json({ vectors: await embedTexts(env, texts, Boolean(body.query)) });
      }
    } catch (e) {
      return json({ error: String((e && e.message) || e) }, 500);
    }
    // Not an API/MCP route → serve static assets (index.html, etc.)
    return env.ASSETS.fetch(request);
  },
};
