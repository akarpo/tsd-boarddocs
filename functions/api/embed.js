// POST /api/embed  { texts: string[], query?: boolean } -> { vectors: number[][] }
// Internal endpoint the backfill/daily-update scripts call to embed passages via
// Workers AI (so no torch/model runs locally or in CI — same model as query time).
import { embedTexts, json, onOptions } from "../_shared.js";

export const onRequestOptions = onOptions;

export async function onRequestPost({ request, env }) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "invalid JSON body" }, 400);
  }
  const texts = body && body.texts;
  if (!Array.isArray(texts) || texts.length === 0) {
    return json({ error: "texts[] required" }, 400);
  }
  if (texts.length > 100) {
    return json({ error: "max 100 texts per call" }, 400);
  }
  const vectors = await embedTexts(env, texts, Boolean(body.query));
  return json({ vectors });
}
