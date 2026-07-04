// Shared helpers for the tsd-boarddocs Pages Functions.
// Files prefixed with "_" are modules, not routes — importable, never served.

export const EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"; // 768-dim

// BGE is asymmetric: the retrieval instruction goes on the QUERY only, never on
// the passages. Passing isQuery=true reproduces exactly what build/backfill does
// NOT apply to passages, keeping both sides in the same vector space.
const QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: ";

export async function embedTexts(env, texts, isQuery = false) {
  const input = isQuery ? texts.map((t) => QUERY_INSTRUCTION + t) : texts;
  const out = await env.AI.run(EMBED_MODEL, { text: input });
  return out.data; // Array<number[768]>
}

// Core retrieval shared by /api/search, /api/fetch and the /mcp tools.
export async function searchCore(env, query, k = 8) {
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

export async function fetchCore(env, id) {
  const got = await env.VECTORIZE.getByIds([id]);
  const v = got && got[0];
  if (!v) return null;
  const md = v.metadata || {};
  return {
    id,
    title: md.title || md.file || id,
    meeting_date: md.meeting_date || "",
    url: md.url || "",
    text: md.text || "",
  };
}

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type",
};

export function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...CORS },
  });
}

// Preflight handler shared by every endpoint.
export function onOptions() {
  return new Response(null, { headers: CORS });
}
