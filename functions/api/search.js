// GET /api/search?q=<query>&k=<n> -> { query, results:[{id,score,title,meeting_date,url,snippet}] }
import { searchCore, json, onOptions } from "../_shared.js";

export const onRequestOptions = onOptions;

export async function onRequestGet({ request, env }) {
  const u = new URL(request.url);
  const q = (u.searchParams.get("q") || "").trim();
  const k = parseInt(u.searchParams.get("k") || "8", 10) || 8;
  if (!q) return json({ error: "q required" }, 400);
  const results = await searchCore(env, q, k);
  return json({ query: q, results });
}
