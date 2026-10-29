export const MAX_SUGGESTED_FOLLOW_UPS = 3;
export const MAX_SUGGESTED_FOLLOW_UP_CHARS = 80;

/** Read the optional `suggested_follow_ups` list from a result payload. Anything malformed, empty, or over-long is dropped; older results without the field give undefined so no chips render. */
export function readSuggestedFollowUps(payload: Record<string, unknown> | undefined): string[] | undefined {
  const raw = payload?.suggested_follow_ups;
  if (!Array.isArray(raw)) return undefined;
  const seen = new Set<string>();
  const suggestions: string[] = [];
  for (const item of raw) {
    if (typeof item !== 'string') continue;
    const text = item.replace(/\s+/g, ' ').trim();
    const key = text.toLowerCase();
    if (!text || text.length > MAX_SUGGESTED_FOLLOW_UP_CHARS || seen.has(key)) continue;
    seen.add(key);
    suggestions.push(text);
    if (suggestions.length === MAX_SUGGESTED_FOLLOW_UPS) break;
  }
  return suggestions.length > 0 ? suggestions : undefined;
}
