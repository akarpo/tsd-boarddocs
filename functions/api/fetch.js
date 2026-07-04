// GET /api/fetch?id=<chunk id> -> { id, title, meeting_date, url, text }
import { fetchCore, json, onOptions } from "../_shared.js";

export const onRequestOptions = onOptions;

export async function onRequestGet({ request, env }) {
  const id = new URL(request.url).searchParams.get("id");
  if (!id) return json({ error: "id required" }, 400);
  const doc = await fetchCore(env, id);
  return doc ? json(doc) : json({ error: "not found" }, 404);
}
