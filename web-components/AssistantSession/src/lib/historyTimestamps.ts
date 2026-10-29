function parseHistoryDate(iso: string): Date | null {
  const normalized = iso.includes('T') ? iso : iso.replace(' ', 'T');
  const date = new Date(normalized.endsWith('Z') ? normalized : `${normalized}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatSidebarTimestamp(iso: string): string {
  const date = parseHistoryDate(iso);
  if (!date) return iso;
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export function formatDetailTimestamp(iso: string): string {
  const date = parseHistoryDate(iso);
  if (!date) return iso;
  const day = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  const time = date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  return `${day} · ${time}`;
}

export function formatRefinementTime(iso: string): string {
  const date = parseHistoryDate(iso);
  if (!date) return iso;
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}
