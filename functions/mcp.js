// POST /mcp — Streamable-HTTP MCP endpoint exposing `search` + `fetch` tools.
// Stateless JSON-RPC 2.0; works as a remote connector in Claude/ChatGPT and mirrors
// the same retrieval core the website and WebMCP tools use. The `search`/`fetch`
// naming matches the OpenAI Deep Research + Anthropic connector contract.
import { searchCore, fetchCore } from "./_shared.js";

const DEFAULT_PROTOCOL = "2025-06-18";
const SERVER_INFO = { name: "tsd-boarddocs", version: "1.0.0" };

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

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,mcp-session-id,mcp-protocol-version,authorization",
};
const HEADERS = { "content-type": "application/json", ...CORS };
const ok = (id, result) => ({ jsonrpc: "2.0", id, result });
const rpcErr = (id, code, message) => ({ jsonrpc: "2.0", id: id ?? null, error: { code, message } });
const reply = (obj) => new Response(JSON.stringify(obj), { headers: HEADERS });

export function onRequestOptions() {
  return new Response(null, { headers: CORS });
}

// The server->client SSE stream (GET) is optional in Streamable HTTP; this server
// is request/response only, so advertise that plainly.
export function onRequestGet() {
  return new Response("Method Not Allowed", { status: 405, headers: CORS });
}

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

export async function onRequestPost({ request, env }) {
  let msg;
  try {
    msg = await request.json();
  } catch {
    return reply(rpcErr(null, -32700, "Parse error"));
  }
  const { id, method, params } = msg || {};

  switch (method) {
    case "initialize":
      return reply(ok(id, {
        protocolVersion: (params && params.protocolVersion) || DEFAULT_PROTOCOL,
        capabilities: { tools: {} },
        serverInfo: SERVER_INFO,
      }));
    case "notifications/initialized":
    case "notifications/cancelled":
      return new Response(null, { status: 202, headers: CORS });
    case "ping":
      return reply(ok(id, {}));
    case "tools/list":
      return reply(ok(id, { tools: TOOLS }));
    case "tools/call": {
      const name = params && params.name;
      const args = (params && params.arguments) || {};
      try {
        return reply(ok(id, await callTool(env, name, args)));
      } catch (e) {
        return reply(ok(id, { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true }));
      }
    }
    default:
      return reply(rpcErr(id, -32601, `Method not found: ${method}`));
  }
}
